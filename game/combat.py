"""game/combat.py — the deterministic resolution engine (02_COMBAT_MATH.md).

No LLM touches these numbers. Every formula is ported from 02 exactly; all
randomness draws from `state.rng` so the same seed reproduces a match. Constants
live in config/settings.py.

The engine (game/engine.py) orchestrates the tick loop and calls these
primitives: net_power / ce_factor / base_damage, black_flash_check, the domain
resolver, resolve_attack, heal_rct, the reinforce/domain/amplification openers,
initiative_order, and validate_move.
"""

from __future__ import annotations

from typing import Optional

from config import settings
from game.state import Fighter, GameState, Move, SpecialEvent, Technique


# ---------------------------------------------------------------------------
# Event helper
# ---------------------------------------------------------------------------
def emit(events: list[SpecialEvent], tick: int, type_: str,
         actors: list[str], detail: str = "") -> None:
    events.append(SpecialEvent(tick=tick, type=type_, actors=actors, detail=detail))


# ---------------------------------------------------------------------------
# 2. EFFECTIVE TECHNIQUE STRENGTH (02 §2)
# ---------------------------------------------------------------------------
def net_power(tech: Technique) -> float:
    """power - 0.5*sum(complication cost), floored at 1 (02 §2)."""
    raw = tech.power - settings.NET_POWER_COMPLICATION_WEIGHT * tech.total_complication_cost()
    return max(settings.NET_POWER_FLOOR, raw)


def effective_net_power(fighter: Fighter, tech: Technique) -> float:
    """net_power with the round-long FLOW buff applied (after a Black Flash)."""
    buff = settings.FLOW_BUFF if "flow" in fighter.status else 1.0
    return net_power(tech) * buff


def ce_factor(spend: int, max_ce: int) -> float:
    """clamp(spend / (0.25*max_ce), 0.4, 1.6) — spending ~25% CE == full (02 §2)."""
    if max_ce <= 0:
        return settings.CE_FACTOR_MIN
    raw = spend / (settings.CE_FACTOR_FRACTION * max_ce)
    return max(settings.CE_FACTOR_MIN, min(settings.CE_FACTOR_MAX, raw))


def base_damage(fighter: Fighter, tech: Technique, spend: int) -> float:
    """BASE_DMG * effective_net_power * ce_factor (02 §2)."""
    return settings.BASE_DMG * effective_net_power(fighter, tech) * ce_factor(spend, fighter.max_ce)


# ---------------------------------------------------------------------------
# 6. BLACK FLASH (02 §6) — not at-will; lucky proc on a CE-melee hit
# ---------------------------------------------------------------------------
def black_flash_check(state: GameState, attacker: Fighter,
                      events: list[SpecialEvent], tick: int) -> float:
    """Return the crit multiplier (1.0 or 2.5); set 'flow' + emit on a proc."""
    chance = settings.BLACK_FLASH_BASE_CHANCE + min(
        settings.BLACK_FLASH_FLOW_BONUS_CAP,
        settings.BLACK_FLASH_FLOW_BONUS_PER_HIT * attacker.consecutive_ce_hits,
    )
    if "flow" in attacker.status:
        chance += settings.BLACK_FLASH_IN_FLOW_BONUS
    if state.rng.random() < chance:
        newly_flow = "flow" not in attacker.status
        if newly_flow:
            attacker.status.append("flow")
        # v2-C: consecutive Black Flashes rebuild RCT (charges, NOT direct CE).
        attacker.rct_charge = min(settings.RCT_CHARGE_CAP, attacker.rct_charge + 1)
        emit(events, tick, "BLACK FLASH", [attacker.character_name],
             f"x{settings.BLACK_FLASH_MULTIPLIER} crit · RCT charge {attacker.rct_charge}")
        if newly_flow:
            emit(events, tick, "FLOW STATE", [attacker.character_name],
                 "120% potential for the rest of the round")
        return settings.BLACK_FLASH_MULTIPLIER
    return 1.0


# ---------------------------------------------------------------------------
# 5. MITIGATION (02 §5)
# ---------------------------------------------------------------------------
def target_mitigation(target: Fighter) -> float:
    base = settings.DEFENSE_FLAT
    if "reinforced" in target.status and target.max_ce > 0:
        base += (settings.REINFORCE_MITIGATION_FACTOR * target.max_hp *
                 (target.reinforce_ce / (settings.CE_FACTOR_FRACTION * target.max_ce)))
    return base


# ---------------------------------------------------------------------------
# 3 + 4. ATTACK RESOLUTION & MATCHUP MULTIPLIERS (02 §3, §4)
# ---------------------------------------------------------------------------
def _is_ce_melee(tech: Technique, ce_spend: int) -> bool:
    return ce_spend > 0 and "ranged" not in tech.tags


def resolve_attack(state: GameState, attacker: Fighter, target: Fighter,
                   tech: Technique, ce_spend: int, *, sure_hit_active: bool,
                   events: list[SpecialEvent], tick: int,
                   is_cluster: bool = False, target_action: Optional[str] = None) -> int:
    """Resolve one attack deterministically; mutate state; return damage dealt.

    `target_action` is what the TARGET chose this tick — used by the v5 accuracy read:
    a low/mid-accuracy (telegraphed) attack misses or grazes a target who dodged/countered;
    a high-accuracy or domain sure-hit ignores dodging. RNG is only a ±10% boundary nudge.
    """
    tags = set(tech.tags)
    tstatus = set(target.status)
    attacker.last_action = "attack"
    attacker.ce = max(0, attacker.ce - ce_spend)

    # Domain Amplification on the target negates the FIRST technique that touches
    # them this tick (×0), and is consumed (02 §4, R4).
    if "amplifying" in tstatus:
        if "amplifying" in target.status:
            target.status.remove("amplifying")
        emit(events, tick, "AMPLIFICATION NEGATE",
             [target.character_name], f"negated {attacker.character_name}'s {tech.name}")
        attacker.consecutive_ce_hits = 0
        return 0

    # --- Sure-hit determination (domain success, with its counters) ---
    sure_hit = ("sure-hit" in tags) and sure_hit_active
    if sure_hit and "heavenly_restriction" in target.traits:
        sure_hit = False  # R9: immune to domain sure-hits
    partial_mult: Optional[float] = None
    broke_simple = False
    if sure_hit and "simple-domain" in tstatus:
        gap = effective_net_power(attacker, tech) - settings.SIMPLE_DOMAIN_NET_POWER
        sure_hit = False
        if gap > settings.SIMPLE_DOMAIN_GAP_THRESHOLD:
            partial_mult = settings.SIMPLE_DOMAIN_PARTIAL_MULT  # only delayed, ×0.5
            broke_simple = True

    # --- v5 PART 2: accuracy as a read (sure-hits / high-accuracy ignore dodging) ---
    graze = 1.0
    acc = getattr(tech, "accuracy", settings.DEFAULT_ACCURACY)
    if (not sure_hit and acc < settings.HIGH_ACCURACY_THRESHOLD
            and target_action in settings.EVASIVE_ACTIONS):
        eff = acc + (state.rng.random() * 2 - 1) * settings.ACCURACY_RNG_TIEBREAK
        if eff <= settings.LOW_ACCURACY_THRESHOLD:
            emit(events, tick, "EVADED", [target.character_name, attacker.character_name],
                 f"read the telegraph of {tech.name}")
            attacker.consecutive_ce_hits = 0
            return 0
        graze = settings.GRAZE_MULT
        emit(events, tick, "GRAZED", [attacker.character_name, target.character_name],
             f"{tech.name} only clipped a dodging target")

    # --- Multiplier stack (multiplicative) ---
    mult = graze
    if sure_hit:
        mult *= settings.SURE_HIT_DOMAIN_MULT
    if partial_mult is not None:
        mult *= partial_mult
    if "soul" in tags:
        mult *= settings.SOUL_MULT
    if "ranged" in tags and "melee-committed" in tstatus:
        mult *= settings.RANGED_VS_MELEE_MULT
    if "reinforced" in tstatus and not sure_hit:
        mult *= settings.REINFORCED_DAMAGE_MULT
    if "aoe" in tags and is_cluster:
        mult *= settings.AOE_SPLIT_MULT
    if "heavenly_restriction" in target.traits and "melee" in tags:
        mult *= settings.HEAVENLY_RESTRICTION_MELEE_BONUS
    if "frail_body" in attacker.traits:        # binding-vow: less HP, harder hits
        mult *= settings.FRAIL_BODY_DAMAGE_FACTOR
    if "passive" in tstatus:                   # v2-B: turtling is punished
        mult *= (1 + settings.PASSIVE_DAMAGE_BONUS)
    if "revealed-resolve" in attacker.status:  # v6: revealing a technique buffs all damage
        mult *= (1 + settings.REVEAL_DAMAGE_BONUS)

    # --- Black Flash (only on a CE-melee, only if not fully negated) ---
    crit = 1.0
    if _is_ce_melee(tech, ce_spend):
        crit = black_flash_check(state, attacker, events, tick)

    # --- Damage ---
    if crit > 1.0:
        # v4-P0: on the Black-Flash hit, FLOW does NOT also stack (base net_power) and
        # ce_factor is clamped to 1.0 — the 2.5x is the whole story.
        cf = min(ce_factor(ce_spend, attacker.max_ce), settings.BLACK_FLASH_CE_FACTOR_CAP)
        raw = settings.BASE_DMG * net_power(tech) * cf
    else:
        raw = base_damage(attacker, tech, ce_spend)
    mitig = 0.0 if sure_hit else target_mitigation(target)
    dmg = max(0, round(raw * mult * crit - mitig))
    # v4-P0: cap any single hit at a fraction of the target's max HP (no one-shots).
    dmg = min(dmg, round(settings.MAX_SINGLE_HIT_FRACTION * target.max_hp))
    target.hp -= dmg
    # v4-P0: first-tick protection — a fighter can't be dropped below 1 HP before acting.
    if not target.has_acted and target.hp < 1:
        target.hp = 1

    # --- Side effects ---
    if "soul" in tags and dmg > 0:
        target.soul_damage = min(target.max_hp, target.soul_damage + dmg)
        emit(events, tick, "SOUL STRIKE", [attacker.character_name, target.character_name],
             f"{dmg} soul damage (RCT can't heal it)")
    if sure_hit and dmg > 0:
        emit(events, tick, "SURE-HIT LANDED",
             [attacker.character_name, target.character_name], f"{dmg} damage")
    if broke_simple and "simple-domain" in target.status:
        target.status.remove("simple-domain")

    # v2-D: a swap technique has a real consequence — it rips the target out of their
    # setup (reinforce / simple domain / amplification / open domain), not just flavor.
    if "swap" in tags:
        broke = [s for s in ("reinforced", "simple-domain", "amplifying")
                 if s in target.status]
        for s in broke:
            target.status.remove(s)
        if "domain-open" in target.status:
            target.status.remove("domain-open")
            target.active_domain = None
            broke.append("domain")
        if broke:
            emit(events, tick, "POSITION SWAP", [attacker.character_name, target.character_name],
                 "swapped out of their setup: " + ", ".join(broke))

    if _is_ce_melee(tech, ce_spend) and dmg > 0:
        attacker.consecutive_ce_hits += 1
    else:
        attacker.consecutive_ce_hits = 0
    return dmg


# ---------------------------------------------------------------------------
# 7. HEALING — RCT / RCE (02 §7)
# ---------------------------------------------------------------------------
def heal_rct(fighter: Fighter, ce_spend: int, *,
             events: Optional[list[SpecialEvent]] = None, tick: int = 0) -> int:
    """Convert CE -> HP. Legality (no_rct) is checked by the engine first.

    v2-C: if the fighter banked an RCT charge from a Black Flash, this heal costs
    30% less CE and heals 30% more HP (one charge consumed).
    """
    discount = bonus = 0.0
    if fighter.rct_charge > 0:
        discount = settings.RCT_CHARGE_CE_DISCOUNT
        bonus = settings.RCT_CHARGE_HEAL_BONUS
        fighter.rct_charge -= 1
        if events is not None:
            emit(events, tick, "RCT CIRCUIT RESTORED", [fighter.character_name],
                 "Black Flash rebuilt RCT — cheaper, stronger heal")
    heal = round(settings.RCT_CE_TO_HP * ce_spend * (1 + bonus))
    cap = fighter.max_hp if "soul_sight" in fighter.traits else fighter.effective_max_hp()
    before = fighter.hp
    fighter.hp = min(cap, fighter.hp + heal)
    fighter.ce = max(0, fighter.ce - round(ce_spend * (1 - discount)))
    fighter.last_action = "heal_rct"
    fighter.consecutive_ce_hits = 0
    return fighter.hp - before


# ---------------------------------------------------------------------------
# 8. DOMAINS (02 §8)
# ---------------------------------------------------------------------------
def open_domain(fighter: Fighter, tech: Technique, ce_spend: int,
                events: list[SpecialEvent], tick: int) -> None:
    if "domain-open" not in fighter.status:
        fighter.status.append("domain-open")
    fighter.active_domain = tech
    fighter.ce = max(0, fighter.ce - ce_spend)
    fighter.last_action = "domain_expansion"
    emit(events, tick, "DOMAIN EXPANSION", [fighter.character_name], tech.name)


def open_amplification(fighter: Fighter, ce_spend: int) -> None:
    if "amplifying" not in fighter.status:
        fighter.status.append("amplifying")
    fighter.ce = max(0, fighter.ce - ce_spend)
    fighter.last_action = "domain_amplification"
    fighter.consecutive_ce_hits = 0


def open_simple_domain(fighter: Fighter, ce_spend: int) -> None:
    if "simple-domain" not in fighter.status:
        fighter.status.append("simple-domain")
    fighter.ce = max(0, fighter.ce - ce_spend)
    fighter.last_action = "simple_domain"
    fighter.consecutive_ce_hits = 0


def reinforce(fighter: Fighter, ce_spend: int) -> None:
    if "reinforced" not in fighter.status:
        fighter.status.append("reinforced")
    fighter.reinforce_ce = ce_spend
    fighter.ce = max(0, fighter.ce - ce_spend)
    fighter.last_action = "reinforce"
    fighter.consecutive_ce_hits = 0


def resolve_domains_this_tick(state: GameState, events: list[SpecialEvent],
                              tick: int) -> dict[str, bool]:
    """Settle domains BEFORE damage. Returns {character_name: sure_hit_active}.

    0 domains: nobody. 1: that fighter's sure-hit applies. 2: higher net power
    wins (close gap cancels). 3+: TOTAL COLLAPSE, all break, backlash (R3).
    """
    open_fighters = [f for f in state.living_fighters()
                     if "domain-open" in f.status and f.active_domain is not None]
    result: dict[str, bool] = {f.character_name: False for f in open_fighters}
    n = len(open_fighters)
    if n == 0:
        return result

    if n == 1:
        f = open_fighters[0]
        result[f.character_name] = True
    elif n == 2:
        a, b = open_fighters
        na, nb = net_power(a.active_domain), net_power(b.active_domain)
        if abs(na - nb) < settings.DOMAIN_CLASH_CLOSE_GAP:
            emit(events, tick, "DOMAIN CLASH",
                 [a.character_name, b.character_name], "evenly matched — both void")
        else:
            winner = a if na > nb else b
            loser = b if winner is a else a
            result[winner.character_name] = True
            emit(events, tick, "DOMAIN CLASH",
                 [winner.character_name, loser.character_name],
                 f"{winner.character_name}'s domain is more refined")
    else:  # n >= 3 — canon R3
        for f in open_fighters:
            f.hp -= settings.DOMAIN_COLLAPSE_BACKLASH
            if "domain-open" in f.status:
                f.status.remove("domain-open")
            f.active_domain = None
            result[f.character_name] = False
        emit(events, tick, "DOMAIN CLASH COLLAPSE",
             [f.character_name for f in open_fighters],
             "3+ domains collided — all collapse, no winner")
    return result


# ---------------------------------------------------------------------------
# 9. TURN ORDER (02 §9)
# ---------------------------------------------------------------------------
def initiative_order(state: GameState, fighters: list[Fighter]) -> list[Fighter]:
    """Sort by CE-weighted roll, descending (02 §9)."""
    return sorted(
        fighters,
        key=lambda f: f.ce * settings.INITIATIVE_CE_WEIGHT
        + state.rng.random() * settings.INITIATIVE_RNG_SPAN,
        reverse=True,
    )


def clear_per_tick_status(fighter: Fighter) -> None:
    """Drop transient one-tick statuses; keep domain-open and flow (round-long)."""
    for s in ("reinforced", "amplifying", "simple-domain", "melee-committed"):
        if s in fighter.status:
            fighter.status.remove(s)
    fighter.reinforce_ce = 0


# ---------------------------------------------------------------------------
# 10. LEGALITY (02 §10) — engine rejects, agent re-picks once, else 'wait'
# ---------------------------------------------------------------------------
_TECH_REQUIRED = {"attack", "domain_expansion", "explain_technique"}


def validate_move(state: GameState, fighter: Fighter, move: Move) -> Optional[str]:
    """Return a reason string if the move is illegal, else None."""
    if move.ce_spend < 0:
        return "negative ce_spend"
    if move.ce_spend > fighter.ce:
        return f"ce_spend {move.ce_spend} > available {fighter.ce}"

    if move.action in _TECH_REQUIRED:
        if fighter.technique_by_name(move.technique_name) is None:
            return f"unknown technique '{move.technique_name}'"

    if move.action == "heal_rct" and fighter.has_handicap("no_rct"):
        return "no_rct handicap forbids healing"
    if move.action == "domain_expansion":
        if fighter.has_handicap("no_domain"):
            return "no_domain handicap forbids domains"
        if move.ce_spend < settings.DOMAIN_CE_COST:
            return f"domain needs >= {settings.DOMAIN_CE_COST} CE"

    if move.action == "attack":
        if not move.target:
            return "attack needs a target"
        if move.target == fighter.character_name:
            return "cannot attack self"
        tgt = state.fighter(move.target)
        if tgt is None or not tgt.alive_this_round or tgt.hp <= 0:
            return f"target '{move.target}' is not a living fighter"

    return None
