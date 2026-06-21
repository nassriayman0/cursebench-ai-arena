"""game/engine.py — the referee. Full multi-round match (Stage B).

Round sequence (01 §6.1):
  1. (round 5+) offer each fighter a binding-vow handicap; apply if accepted
  2. generate one technique per fighter (+ any owed vow power bump); announce
  3. negotiation: private messages -> informal alliances (betrayal allowed)
  4. combat ticks in CE-weighted initiative order:
       prep moves -> settle domains -> action moves (+ optional react layer)
  5. round ends at last-one-standing (or MAX_TICKS -> highest HP)
  6. reflection: each agent writes a private memory note for later rounds

Everything beyond the core tick loop is gated by `state.match_options` flags and
guarded with hasattr(), so the offline StubPolicy still drives a round with zero
model calls. `run_match` runs all rounds, then scores + persists.

Match option flags (defaults): enable_negotiation, enable_handicaps,
enable_reflect = True; enable_react, enable_director = False.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional, Protocol

from config import settings
from config.models import get_spec, is_available
from game import combat, scoring
from game.generator import (assign_canon_round, balance_round_spread, cursed_strike,
                            generate_technique, is_damage_capable, pick_unused_canon,
                            safe_fallback)
from models.base import call_model
from game.phases import (apply_binding_vow, eligible_for_handicap,
                         escalation_banner, offer_handicaps)
from game.state import Fighter, GameState, Move, RoundRecord, SpecialEvent
from util.logging import CallMeter, get_logger
from util.persistence import save_match

_log = get_logger("jjk.engine")
Line = Callable[[str], None]

_PREP_ACTIONS = {"domain_expansion", "domain_amplification", "simple_domain", "reinforce"}
# v2-B engagement: which actions count as "acting" vs turtling.
_ENGAGED_ACTIONS = {"attack", "domain_expansion", "domain_amplification",
                    "simple_domain", "betray"}
_PASSIVE_ACTIONS = {"wait", "reinforce"}
_ATTACK_VERBS = ("attack", "strike", "slash", "blast", "unleash", "assault",
                 "barrage", "relentless", "pummel", "onslaught")
_ALLY_KEYWORDS = ("ally", "alliance", "team", "together", "truce", "pact", "join",
                  "cooperate", "work with", "side with", "partner")


class Policy(Protocol):
    def choose_move(self, state: GameState, fighter: Fighter,
                    round_number: int, tick: int) -> Move: ...


class StubPolicy:
    """Heuristic (no LLM): attack the lowest-HP enemy with a chunk of CE; else wait."""

    def choose_move(self, state: GameState, fighter: Fighter,
                    round_number: int, tick: int) -> Move:
        enemies = [f for f in state.living_fighters()
                   if f.character_name != fighter.character_name]
        if not enemies or fighter.ce <= 0 or not fighter.techniques:
            return Move(actor=fighter.character_name, action="wait",
                        intent="conserve", dialogue="...")
        target = min(enemies, key=lambda e: e.hp)
        tech = fighter.techniques[-1]
        spend = min(fighter.ce, max(10, fighter.max_ce // 4))
        return Move(actor=fighter.character_name, action="attack",
                    target=target.character_name, technique_name=tech.name,
                    ce_spend=spend, intent="focus the weakest",
                    dialogue=f"Fall, {target.character_name}.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _opt(state: GameState, key: str, default: bool) -> bool:
    return bool(state.match_options.get(key, default))


def _should_parallelize(state: GameState) -> bool:
    """Run per-phase model calls concurrently — unless it would hurt.

    Four DIFFERENT local models on one GPU thrash (constant VRAM swaps) when
    called concurrently, so those stay sequential. Claude/API seats and a single
    shared local model parallelize safely (~Nx faster ticks). Override with
    match_options['parallel'].
    """
    override = state.match_options.get("parallel")
    if override is not None:
        return bool(override)
    models = {f.model_id for f in state.fighters.values()}
    providers = {get_spec(f.model_id).provider for f in state.fighters.values()}
    if providers == {"ollama"} and len(models) > 1:
        return False
    return True


def _pmap(fn, items, parallel: bool) -> list:
    """Map fn over items, concurrently when `parallel` (calls are I/O-bound)."""
    items = list(items)
    if not parallel or len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=min(len(items), 8)) as ex:
        return list(ex.map(fn, items))


def _generator_model_for(fighter: Fighter) -> str:
    """Default: the fighter generates its OWN technique with its OWN model (fast + varied).
    A shared generator is only used if JJK_GENERATOR_MODEL is set and available."""
    gen = settings.GENERATOR_MODEL_ID
    if gen and is_available(gen):
        return gen
    return fighter.model_id


def _dedupe_techniques(techs: list, fighters: list, round_number: int, on_line: Line) -> None:
    """v2.1/v5-P1: no two fighters share a technique in a round, AND no seat repeats the
    base technique it had last round. Phase-1 collisions snap to an unused REAL canon
    technique (same tier); phase 2/3 collisions get a per-fighter variant name.
    (Phase 1 rarely triggers — assign_canon_round already enforces both rules.)"""
    phase = settings.phase_for_round(round_number)
    seen: set[str] = set()
    for i, t in enumerate(techs):
        key = t.name.strip().lower()
        own_last = (fighters[i].last_technique_name or "").lower()
        if key in seen or (own_last and key == own_last):
            avoid = seen | ({own_last} if own_last else set())
            if phase == 1:
                alt = pick_unused_canon(avoid, fighters[i], round_number)
                alt.tier = t.tier or alt.tier
                on_line(f"  (dup/repeat [{t.name}] -> [{alt.name}] for {fighters[i].character_name})")
                techs[i] = alt
                key = alt.name.strip().lower()
            else:
                techs[i].name = f"{t.name} — {fighters[i].character_name}'s variant"
                key = techs[i].name.strip().lower()
        seen.add(key)


def _director_model_for(state: GameState) -> str:
    """Pick an available seat model for the one-per-round director line."""
    gen = settings.GENERATOR_MODEL_ID
    if gen and is_available(gen):
        return gen
    for f in state.fighters.values():
        if is_available(f.model_id):
            return f.model_id
    return next(iter(state.fighters.values())).model_id


def reset_for_round(state: GameState) -> None:
    for f in state.fighters.values():
        f.alive_this_round = True
        if settings.HP_RESETS_EACH_ROUND:
            f.hp = f.max_hp
        regen = round(f.max_ce * settings.CE_REGEN_BETWEEN_ROUNDS)
        if f.passive_carry:   # v2-B: ended last round passive -> regen less CE
            regen = round(regen * (1 - settings.PASSIVE_CE_REGEN_PENALTY))
        f.ce = min(f.max_ce, f.ce + regen)
        f.status = []
        f.reinforce_ce = 0
        f.consecutive_ce_hits = 0
        f.active_domain = None
        f.soul_damage = 0
        f.last_action = None
        f.consecutive_passive_ticks = 0
        f.engaged_last_tick = False
        f.rct_charge = 0
        f.has_acted = False   # v5 first-tick protection
        # passive_carry persists until they take an offensive action (v2-B)
        # last_technique_name persists (used to avoid a repeat this round)


def _update_engagement(f: Fighter, action: str) -> None:
    """Track turtling vs acting for the v2-B passivity penalty + engagement CE reward."""
    if action in _ENGAGED_ACTIONS:
        f.engaged_last_tick = True
        f.consecutive_passive_ticks = 0
        f.passive_carry = False
        if "passive" in f.status:
            f.status.remove("passive")
    elif action in _PASSIVE_ACTIONS:
        f.consecutive_passive_ticks += 1
        if f.consecutive_passive_ticks >= settings.PASSIVE_TICK_THRESHOLD:
            if "passive" not in f.status:
                f.status.append("passive")
            f.passive_carry = True
    # explain_technique / ally_* are neutral: neither rewarded nor penalized.


def _snapshot(state: GameState, tick: int) -> dict:
    return {
        "tick": tick,
        "hp": {n: f.hp for n, f in state.fighters.items()},
        "ce": {n: f.ce for n, f in state.fighters.items()},
    }


def _check_kos(state: GameState, events: list[SpecialEvent], tick: int, on_line: Line) -> None:
    for f in state.fighters.values():
        if f.alive_this_round and f.hp <= 0:
            f.hp = 0
            f.alive_this_round = False
            combat.emit(events, tick, "KO", [f.character_name], "down")
            on_line(f"    KO! {f.character_name} is down.")


def _decide_winner(state: GameState) -> Optional[Fighter]:
    survivors = state.living_fighters()
    if len(survivors) == 1:
        return survivors[0]
    if not survivors:
        return None
    return max(survivors, key=lambda f: (f.hp, f.ce))


def _sudden_death(state: GameState, tick: int, events: list[SpecialEvent],
                  on_line: Line) -> None:
    """Mounting cursed storm: damage standing fighters weakest-first until one remains.

    Guarantees a round ends at LAST-ONE-STANDING (the other three at 0 HP) instead of
    petering out at a tick cap.
    """
    dmg = (settings.SUDDEN_DEATH_BASE
           + settings.SUDDEN_DEATH_RAMP * (tick - settings.SUDDEN_DEATH_START_TICK))
    combat.emit(events, tick, "CURSED STORM", [], f"{dmg} to all standing")
    on_line(f"  ⛈️ CURSED STORM — {dmg} damage to every standing sorcerer")
    for f in sorted(state.living_fighters(), key=lambda x: x.hp):
        if len(state.living_fighters()) <= 1:
            break
        f.hp = max(0, f.hp - dmg)
        if f.hp <= 0:
            f.alive_this_round = False
            combat.emit(events, tick, "KO", [f.character_name], "consumed by the storm")
            on_line(f"    KO! {f.character_name} falls to the storm.")


# ---------------------------------------------------------------------------
# Phase helpers (LLM; skipped for StubPolicy via hasattr guards)
# ---------------------------------------------------------------------------
def _offer_handicaps(state: GameState, agents: dict, round_number: int,
                     events: list[SpecialEvent], on_line: Line, parallel: bool) -> None:
    # Build options sequentially (uses state.rng — not thread-safe), then ask in parallel.
    eligible = []
    for f in state.fighters.values():
        if not eligible_for_handicap(f, round_number):
            continue
        agent = agents.get(f.character_name)
        if hasattr(agent, "decide_handicap"):
            eligible.append((f, agent, offer_handicaps(state, f)))
    if not eligible:
        return
    resps = _pmap(lambda t: t[1].decide_handicap(t[0], t[2], round_number), eligible, parallel)
    for (f, _agent, options), resp in zip(eligible, resps):
        if not resp.accept:
            continue
        chosen = next((h for h in options if h.kind == resp.choice), options[0])
        apply_binding_vow(f, chosen)
        combat.emit(events, 0, "BINDING VOW STRUCK", [f.character_name],
                    f"{chosen.kind} for +{settings.BINDING_VOW_POWER_BUMP} power")
        combat.emit(events, 0, "HANDICAP ACCEPTED", [f.character_name], chosen.kind)
        on_line(f"  BINDING VOW: {f.character_name} accepts [{chosen.kind}] "
                f"-> +power  \"{resp.dialogue}\"")


def _negotiation_phase(state: GameState, agents: dict, round_number: int,
                       record: RoundRecord, events: list[SpecialEvent],
                       on_line: Line, parallel: bool) -> dict[str, set[str]]:
    """Collect private messages, derive informal alliances, return declared allies."""
    proposals: dict[str, set[str]] = {n: set() for n in state.fighters}
    livers = [f for f in state.living_fighters()
              if hasattr(agents.get(f.character_name), "negotiate")]
    msg_lists = _pmap(lambda f: agents[f.character_name].negotiate(state, f, round_number),
                      livers, parallel)
    for f, msgs in zip(livers, msg_lists):
        for m in msgs:
            to = m.get("to")
            record.private_messages.append({"from": f.character_name, **m})
            content = f"{m.get('content', '')} {m.get('true_intent', '')}".lower()
            if to in state.fighters and to != f.character_name and \
                    any(k in content for k in _ALLY_KEYWORDS):
                proposals[f.character_name].add(to)
            if to and to != "none":
                on_line(f"  [whisper] {f.character_name} -> {to}: "
                        f"{m.get('content', '')[:80]}")

    formed: set[tuple] = set()
    for a, targets in proposals.items():
        for b in targets:
            if a in proposals.get(b, set()):
                pair = tuple(sorted((a, b)))
                if pair not in formed:
                    formed.add(pair)
                    combat.emit(events, 0, "ALLIANCE FORMED", list(pair), "informal pact")
                    on_line(f"  ALLIANCE FORMED: {pair[0]} & {pair[1]}")
    return proposals  # a fighter "betrays" anyone they courted then attacked


def _round_summary(record: RoundRecord, winner: Optional[Fighter]) -> str:
    """v2-E: a factual one-liner built ONLY from the RoundRecord data."""
    dd = record.damage_dealt
    storm_kos = sum(1 for e in record.special_events
                    if e.type == "KO" and "storm" in (e.detail or "").lower())
    if winner is None:
        return "Mutual KO — no survivor this round."
    wdmg = dd.get(winner.character_name, 0)
    if record.decided_by == "storm":
        how = "by survival (storm tiebreaker)"
    elif wdmg == 0:
        how = "by survival — threw no damaging hit"
    else:
        how = "by combat"
    parts = [f"{winner.character_name} won at {winner.hp} HP {how}."]
    if storm_kos:
        parts.append(f"Storm KO'd {storm_kos}.")
    if dd:
        top_name, top_dmg = max(dd.items(), key=lambda kv: kv[1])
        if top_dmg > 0:
            parts.append(f"Most damage: {top_name} ({top_dmg}).")
    return " ".join(parts)


def _director_line(state: GameState, record: RoundRecord, meter, on_line: Line) -> None:
    """v2-E: ONE commentator sentence grounded in the record. The model may only
    narrate what the data shows; a line that credits a 0-damage fighter with an
    attack is rejected (the factual summary still stands)."""
    model_id = _director_model_for(state)
    dd = record.damage_dealt
    zero_dmg = [n for n in state.fighters if dd.get(n, 0) == 0]
    dmg_str = ", ".join(f"{n} {d}" for n, d in dd.items()) or "no damage dealt by anyone"
    facts = (f"Winner: {record.round_winner or 'none'} ({record.decided_by}). "
             f"Damage dealt: {dmg_str}. Dealt ZERO damage: {', '.join(zero_dmg) or 'none'}. "
             f"Events: {'; '.join(e.type for e in record.special_events[:10])}.")
    system = ("You are the Arena Director — a vivid sports commentator. Describe ONLY what "
              "the data shows. NEVER invent attacks. If the winner won by surviving rather "
              "than attacking, say so plainly. Reply with ONE punchy sentence (<=200 chars).")
    user = f"Round {record.round_number} FACTS — {facts}\nGive ONE line consistent with these facts."
    try:
        line = call_model(model_id, system, [{"role": "user", "content": user}],
                          temperature=0.7, json_mode=False, call_type="director", meter=meter)
        line = line.strip().strip('"')[:240]
        if _credits_nonattacker(line, zero_dmg):
            on_line("  🎙️ Director line rejected (credited a non-attacker); factual summary stands.")
            return
        record.narration = line
        if line:
            on_line(f"  🎙️ Director: {line}")
    except Exception as exc:  # noqa: BLE001 - narration is optional flavor
        _log.info("director narration skipped: %s", exc)


def _credits_nonattacker(line: str, zero_dmg: list[str]) -> bool:
    """True if the narration names a 0-damage fighter close before an attack verb."""
    low = line.lower()
    for name in zero_dmg:
        idx = low.find(name.lower())
        if idx == -1:
            continue
        window = low[idx: idx + len(name) + 35]
        if any(v in window for v in _ATTACK_VERBS):
            return True
    return False


def _reflect_phase(state: GameState, agents: dict, round_number: int,
                   record: RoundRecord, on_line: Line, parallel: bool) -> None:
    survivor = record.round_winner or "no one"
    event_types = [e.type for e in record.special_events]
    fighters = [f for f in state.fighters.values()
                if hasattr(agents.get(f.character_name), "reflect")]
    analyses = _pmap(
        lambda f: agents[f.character_name].reflect(f, round_number, survivor, event_types),
        fighters, parallel)
    for f, analysis in zip(fighters, analyses):
        if analysis:
            record.analyses[f.character_name] = analysis
            on_line(f"  🧠 {f.character_name}: {analysis[:100]}")


# ---------------------------------------------------------------------------
# The round
# ---------------------------------------------------------------------------
def prepare_round(state: GameState, agents: dict[str, Policy], round_number: int,
                  *, meter: Optional[CallMeter] = None, on_line: Optional[Line] = None,
                  use_llm_generation: bool = True) -> tuple[RoundRecord, dict[str, set[str]]]:
    """Phase 1-3 of a round: handicaps, generate techniques, negotiate.

    Returns the (partial) RoundRecord and the declared-allies map. The techniques
    are now visible for the user to read BEFORE combat — call fight_round next.
    """
    on_line = on_line or (lambda _s: None)
    phase = settings.phase_for_round(round_number)
    record = RoundRecord(round_number=round_number, phase=settings.phase_name(phase))
    events = record.special_events
    state.round_number = round_number
    reset_for_round(state)

    on_line(f"\n=== ROUND {round_number} — {settings.phase_name(phase)} phase ===")
    on_line(escalation_banner(round_number))
    parallel = _should_parallelize(state)

    # --- 1. binding-vow handicap offers (round 5+) ---
    if use_llm_generation and _opt(state, "enable_handicaps", True):
        _offer_handicaps(state, agents, round_number, events, on_line, parallel)

    # --- 2. techniques ---
    fighters = list(state.fighters.values())
    if phase == 1:
        # v5 PART 3: canon phase — engine hands every fighter a UNIQUE real technique of
        # the SAME tier (fast, fair, canon-faithful). No LLM/cache for phase 1.
        on_line("Assigning canon techniques (same tier)...")
        techs = assign_canon_round(fighters, round_number, state.rng)
        on_line(f"  (round tier: {techs[0].tier})")
    elif use_llm_generation:
        on_line("Generating techniques...")
        techs = _pmap(lambda f: generate_technique(_generator_model_for(f), f,
                                                   round_number, meter=meter),
                      fighters, parallel)
    else:
        techs = [safe_fallback(phase, round_number, [h.kind for h in f.handicaps])
                 for f in fighters]
    for f, tech in zip(fighters, techs):
        if f.pending_power_bonus:
            tech.power = min(settings.POWER_MAX, tech.power + f.pending_power_bonus)
            on_line(f"  (binding vow pays out: {f.character_name}'s technique +{f.pending_power_bonus} power)")
            f.pending_power_bonus = 0
    # v2.1/v5-P1: no two fighters share a technique, and no seat repeats its own last one.
    _dedupe_techniques(techs, fighters, round_number, on_line)
    # v2-D: cap the per-round power spread (lift weak outliers) before committing.
    balance_round_spread(techs, round_number)
    for f, tech in zip(fighters, techs):
        f.techniques.append(tech)
        f.last_technique_name = tech.name           # v5-P1 per-seat history
        record.generated_techniques[f.character_name] = tech
        comp = "; ".join(f"{c.name}({c.cost})" for c in tech.complications) or "none"
        on_line(f"  {f.character_name}: [{tech.name}] {tech.tier or '-'} P{tech.power} "
                f"net{combat.net_power(tech):.1f} acc{tech.accuracy:.2f} — {comp}")
    # v2-D: guarantee every fighter has a damage option (no unwinnable pure-utility draw).
    for f in fighters:
        if not any(is_damage_capable(t) for t in f.techniques):
            cs = cursed_strike(round_number)
            f.techniques.append(cs)
            on_line(f"  ⚔️ {f.character_name} had no damage option — granted [{cs.name}]")

    # --- 3. negotiation / alliances ---
    declared: dict[str, set[str]] = {n: set() for n in state.fighters}
    if use_llm_generation and _opt(state, "enable_negotiation", True):
        declared = _negotiation_phase(state, agents, round_number, record, events,
                                      on_line, parallel)

    record.hp_ce_timeline.append(_snapshot(state, 0))
    return record, declared


def fight_round(state: GameState, agents: dict[str, Policy], round_number: int,
                record: RoundRecord, declared: dict[str, set[str]], *,
                meter: Optional[CallMeter] = None, on_line: Optional[Line] = None,
                use_llm_generation: bool = True) -> RoundRecord:
    """Phase 4-6: combat ticks to last-one-standing, then narration + debrief.

    Appends the finished record to state.records and returns it.
    """
    on_line = on_line or (lambda _s: None)
    events = record.special_events
    parallel = _should_parallelize(state)

    # --- 4. combat ticks (run until ONE stands; CE trickles back + sudden death) ---
    enable_react = _opt(state, "enable_react", False)
    for tick in range(1, settings.HARD_TICK_CAP + 1):
        if len(state.living_fighters()) <= 1:
            break
        on_line(f"\n-- tick {tick} --")
        # v2-B: engagement CE reward — only fighters who acted last tick regain CE.
        for f in state.living_fighters():
            if f.engaged_last_tick:
                f.ce = min(f.max_ce, f.ce + settings.ENGAGED_CE_PER_TICK)
            f.engaged_last_tick = False
        # v2-F: the storm is a TIEBREAKER — it only fires past the cap (2+ still alive).
        if tick >= settings.SUDDEN_DEATH_START_TICK:
            record.decided_by = "storm"
            _sudden_death(state, tick, events, on_line)
            if len(state.living_fighters()) <= 1:
                record.hp_ce_timeline.append(_snapshot(state, tick))
                break
        order = combat.initiative_order(state, state.living_fighters())

        # All living fighters pick from the same pre-tick snapshot -> safe to parallelize.
        chosen = _pmap(lambda f: agents[f.character_name].choose_move(state, f, round_number, tick),
                       order, parallel)
        queued: list[tuple[Fighter, Move]] = []
        for f, move in zip(order, chosen):
            reason = combat.validate_move(state, f, move)
            if reason:
                _log.info("illegal move by %s (%s) -> wait", f.character_name, reason)
                move = Move(actor=f.character_name, action="wait",
                            intent=f"(illegal: {reason})", dialogue="")
            queued.append((f, move))
            record.moves.append(move)
        # v5-P2: what each fighter chose this tick (for the accuracy/evade read).
        tick_actions = {f.character_name: move.action for f, move in queued}
        # v6: stream each fighter's inner strategy BEFORE the moves resolve.
        for f, move in queued:
            if move.thinking:
                on_line(f"  💭 {f.character_name}: {move.thinking}")

        # preparation moves
        for f, move in queued:
            if move.action in _PREP_ACTIONS:
                f.has_acted = True   # v5: prep counts as having acted (first-tick protection)
            if move.action == "domain_expansion":
                combat.open_domain(f, f.technique_by_name(move.technique_name),
                                   move.ce_spend, events, tick)
                on_line(f"  {f.character_name} OPENS DOMAIN [{move.technique_name}] "
                        f"({move.ce_spend} CE)")
            elif move.action == "domain_amplification":
                combat.open_amplification(f, move.ce_spend)
                on_line(f"  {f.character_name} amplifies (negation shell)")
            elif move.action == "simple_domain":
                combat.open_simple_domain(f, move.ce_spend)
                on_line(f"  {f.character_name} raises a Simple Domain")
            elif move.action == "reinforce":
                combat.reinforce(f, move.ce_spend)
                on_line(f"  {f.character_name} reinforces")

        sure_hit = combat.resolve_domains_this_tick(state, events, tick)
        _check_kos(state, events, tick, on_line)

        # optional react/counter layer (transcript chess; gated — slow on local).
        # v4-P0: skip tick 1 entirely — no opponent move exists to predict yet, so no
        # empty-string predictions get stored or shown.
        if enable_react and tick > 1:
            _react_layer(state, agents, queued, record, tick, on_line)

        # action moves
        for f, move in queued:
            if move.action in _PREP_ACTIONS:
                continue
            if not f.alive_this_round or f.hp <= 0:
                continue
            f.has_acted = True   # v5 first-tick protection: this fighter has now acted
            _apply_action(state, f, move, sure_hit, declared, record, events, tick,
                          on_line, tick_actions)
            _check_kos(state, events, tick, on_line)
            if len(state.living_fighters()) <= 1:
                break

        # v2-B: record engagement/passivity from this tick's chosen moves.
        for f, move in queued:
            _update_engagement(f, move.action)
        for f in state.fighters.values():
            combat.clear_per_tick_status(f)
        record.hp_ce_timeline.append(_snapshot(state, tick))

    # --- 5. decide the round ---
    winner = _decide_winner(state)
    if winner is not None:
        winner.rounds_won += 1
        record.survivor = winner.character_name
        record.round_winner = winner.character_name
        combat.emit(events, settings.MAX_TICKS, "LAST ONE STANDING",
                    [winner.character_name], f"wins round {round_number} at {winner.hp} HP")
        on_line(f"\n*** {winner.character_name} wins round {round_number} (HP {winner.hp}) ***")
    else:
        on_line(f"\n*** Round {round_number}: no survivor (mutual KO) ***")

    # v2-E: factual one-liner computed in Python (the authoritative record line).
    record.summary = _round_summary(record, winner)
    on_line(f"  📊 {record.summary}")

    # --- 6. director narration (optional) + reflection (memory for later rounds) ---
    if use_llm_generation and _opt(state, "enable_director", False):
        _director_line(state, record, meter, on_line)
    if use_llm_generation and _opt(state, "enable_reflect", True):
        _reflect_phase(state, agents, round_number, record, on_line, parallel)

    state.records.append(record)
    return record


def run_round(state: GameState, agents: dict[str, Policy], round_number: int,
              *, meter: Optional[CallMeter] = None, on_line: Optional[Line] = None,
              use_llm_generation: bool = True) -> RoundRecord:
    """Run a whole round in one call (prepare -> fight). Used by console + sim."""
    record, declared = prepare_round(state, agents, round_number, meter=meter,
                                     on_line=on_line, use_llm_generation=use_llm_generation)
    return fight_round(state, agents, round_number, record, declared, meter=meter,
                       on_line=on_line, use_llm_generation=use_llm_generation)


def _react_layer(state: GameState, agents: dict, queued, record: RoundRecord,
                 tick: int, on_line: Line) -> None:
    for f, move in queued:
        if move.action != "attack" or not move.target:
            continue
        defender = state.fighter(move.target)
        if defender is None or not defender.alive_this_round:
            continue
        dagent = agents.get(defender.character_name)
        if not hasattr(dagent, "react"):
            continue
        summary = f"{move.technique_name or 'a strike'} ({move.ce_spend} CE)"
        r = dagent.react(state, defender, f.character_name, summary)
        if not (r.prediction or "").strip():
            continue   # v4-P0: never store/show an empty-string prediction
        record.counters.append({
            "tick": tick, "defender": defender.character_name,
            "attacker": f.character_name, "prediction": r.prediction,
            "counter": r.counter_action, "intent": r.intent,
        })
        on_line(f"    [react] {defender.character_name}: predicts \"{r.prediction[:60]}\" "
                f"-> {r.counter_action}")


def _apply_action(state: GameState, f: Fighter, move: Move, sure_hit: dict[str, bool],
                  declared: dict[str, set[str]], record: RoundRecord,
                  events: list[SpecialEvent], tick: int, on_line: Line,
                  tick_actions: Optional[dict[str, str]] = None) -> None:
    tick_actions = tick_actions or {}
    if move.action == "attack":
        target = state.fighter(move.target)
        tech = f.technique_by_name(move.technique_name)
        if target is None or tech is None or not target.alive_this_round:
            return
        # Betrayal: striking someone you courted as an ally this round.
        if move.target in declared.get(f.character_name, set()):
            combat.emit(events, tick, "BETRAYAL", [f.character_name, move.target],
                        "struck a would-be ally")
            record.counters.append({"tick": tick, "type": "betrayal",
                                    "by": f.character_name, "on": move.target})
            declared[f.character_name].discard(move.target)
            on_line(f"  BETRAYAL! {f.character_name} turns on {move.target}")
        dmg = combat.resolve_attack(
            state, f, target, tech, move.ce_spend,
            sure_hit_active=sure_hit.get(f.character_name, False),
            events=events, tick=tick,
            target_action=tick_actions.get(move.target),   # v5-P2 accuracy read
        )
        record.damage_dealt[f.character_name] = record.damage_dealt.get(f.character_name, 0) + dmg
        if "melee" in tech.tags and "melee-committed" not in f.status:
            f.status.append("melee-committed")
        line = move.dialogue or move.intent or "attacks"
        on_line(f"  {f.character_name} -> {target.character_name}: [{tech.name}] "
                f"{dmg} dmg (HP {target.hp}/{target.max_hp})  \"{line}\"")

    elif move.action == "heal_rct":
        healed = combat.heal_rct(f, move.ce_spend, events=events, tick=tick)
        on_line(f"  {f.character_name} heals {healed} HP (RCT) -> {f.hp}/{f.max_hp}")

    elif move.action == "explain_technique":
        tech = f.technique_by_name(move.technique_name)
        if tech is not None and not tech.revealed:
            # v6 reveal gamble: stronger on all fronts, but the weakness is now public.
            tech.revealed = True
            tech.power = min(settings.POWER_MAX, tech.power + settings.REVEAL_POWER_BUMP)
            tech.accuracy = min(1.0, tech.accuracy + settings.REVEAL_ACCURACY_BUMP)
            if "revealed-resolve" not in f.status:
                f.status.append("revealed-resolve")
            f.last_action = "explain_technique"
            combat.emit(events, tick, "TECHNIQUE REVEALED", [f.character_name],
                        f"{tech.name} grows stronger — but its weakness is now exposed")
            on_line(f"  🎭 {f.character_name} REVEALS [{tech.name}] — +power/+accuracy/+damage "
                    f"this round, but enemies now see its weakness")

    elif move.action == "dodge":          # v5-P2: a free evasive read
        f.last_action = "dodge"
        f.consecutive_ce_hits = 0
        on_line(f"  {f.character_name} dodges/repositions"
                + (f"  \"{move.dialogue}\"" if move.dialogue else ""))

    elif move.action in ("ally_propose", "ally_accept", "betray", "binding_vow"):
        f.last_action = move.action
        if move.action == "betray" and move.target:
            combat.emit(events, tick, "BETRAYAL", [f.character_name, move.target], "declared betrayal")
            declared.get(f.character_name, set()).discard(move.target)
        on_line(f"  {f.character_name} {move.action} {move.target or ''}".rstrip()
                + (f"  \"{move.dialogue}\"" if move.dialogue else ""))

    else:  # wait
        f.last_action = "wait"
        f.consecutive_ce_hits = 0
        if move.dialogue:
            on_line(f"  {f.character_name} waits.  \"{move.dialogue}\"")


# ---------------------------------------------------------------------------
# The match
# ---------------------------------------------------------------------------
def run_match(state: GameState, agents: dict[str, Policy], *,
              rounds: Optional[int] = None, meter: Optional[CallMeter] = None,
              on_line: Optional[Line] = None, use_llm_generation: bool = True,
              save: bool = True, update_board: bool = True) -> Optional[Fighter]:
    """Run all rounds, then score + (optionally) persist and update the leaderboard."""
    on_line = on_line or (lambda _s: None)
    rounds = rounds or settings.NUM_ROUNDS

    for r in range(1, rounds + 1):
        run_round(state, agents, r, meter=meter, on_line=on_line,
                  use_llm_generation=use_llm_generation)

    winner = scoring.match_winner(state)
    on_line("\n" + "=" * 60)
    if winner:
        on_line(f"MATCH WINNER: {winner.character_name} ({winner.model_id}) "
                f"with {winner.rounds_won} rounds")
    if save:
        path = save_match(state)
        on_line(f"Saved match -> {path}")
    if update_board:
        scoring.update_leaderboard(state)
    return winner
