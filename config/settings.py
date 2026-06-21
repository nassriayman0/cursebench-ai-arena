"""config/settings.py — the single source of truth for every tunable constant.

Ported from `02_COMBAT_MATH.md` and `03_JJK_CANON.md §A`. `game/combat.py`,
`game/generator.py`, and `game/phases.py` read ONLY from here so balance is tuned
in one place (see `simulate.py` in Stage B).

Nothing in this module imports game code — keep it dependency-free so it can be
imported anywhere (including tests) without side effects.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 1. CORE STATS (02 §1)
# ---------------------------------------------------------------------------
START_HP: int = 80     # v2: lowered from 100 so decisive hits can close out kills
START_CE: int = 100

HP_RESETS_EACH_ROUND: bool = True      # rounds are independent bouts
CE_REGEN_BETWEEN_ROUNDS: float = 0.50  # restore 50% of max CE at round start
# rounds_won persists across rounds (handled in scoring, not a constant).

# ---------------------------------------------------------------------------
# 2. EFFECTIVE TECHNIQUE STRENGTH (02 §2)
#     net_power(t)   = power - NET_POWER_COMPLICATION_WEIGHT * sum(cost)   [floor]
#     ce_factor      = clamp(spend / (CE_FACTOR_FRACTION * max_ce), lo, hi)
#     base_damage    = BASE_DMG * net_power * ce_factor
# ---------------------------------------------------------------------------
BASE_DMG: float = 7.0   # v2: raised from 4 so committed hits do 12-25 and resolve fights
NET_POWER_COMPLICATION_WEIGHT: float = 0.5
NET_POWER_FLOOR: float = 1.0

CE_FACTOR_FRACTION: float = 0.20   # v2: spending ~20% of max CE == "full" investment
CE_FACTOR_MIN: float = 0.4
CE_FACTOR_MAX: float = 1.6

# ---------------------------------------------------------------------------
# 3. MATCHUP MULTIPLIERS (02 §4) — applied multiplicatively, start at 1.0
# ---------------------------------------------------------------------------
SURE_HIT_DOMAIN_MULT: float = 1.30     # sure-hit inside a successful open domain
SOUL_MULT: float = 1.10                # 'soul' tag
RANGED_VS_MELEE_MULT: float = 1.15     # 'ranged' vs a melee-committed target
AOE_SPLIT_MULT: float = 0.70           # 'aoe' split across a cluster, per target
REINFORCED_DAMAGE_MULT: float = 0.60   # target reinforced last tick (unless sure-hit)
SIMPLE_DOMAIN_PARTIAL_MULT: float = 0.50   # sure-hit vs simple domain when gap is large
SIMPLE_DOMAIN_GAP_THRESHOLD: float = 4.0   # net_power gap above which simple domain only delays
HEAVENLY_RESTRICTION_MELEE_BONUS: float = 1.20  # +20% physical melee vs a frail/no-CE body

# ---------------------------------------------------------------------------
# 4. MITIGATION (02 §5)
# ---------------------------------------------------------------------------
DEFENSE_FLAT: float = 2.0   # v2: lowered from 3 so chip attacks aren't reduced to 0
# reinforced flat add = REINFORCE_MITIGATION_FACTOR * max_hp * (ce_reinforced / (CE_FACTOR_FRACTION * max_ce))
REINFORCE_MITIGATION_FACTOR: float = 0.15
PASSIVE_DAMAGE_BONUS: float = 0.15   # v2-B: a "passive" fighter takes +15% damage

# ---------------------------------------------------------------------------
# 5. BLACK FLASH (02 §6, 03 §A) — not at-will; lucky proc on a CE-melee hit
# ---------------------------------------------------------------------------
BLACK_FLASH_BASE_CHANCE: float = 0.08
BLACK_FLASH_FLOW_BONUS_PER_HIT: float = 0.06   # per consecutive CE hit
BLACK_FLASH_FLOW_BONUS_CAP: float = 0.24       # v2-C: raised from 0.18 (reward sustained pressure)
BLACK_FLASH_IN_FLOW_BONUS: float = 0.05        # extra while already 'flow'
BLACK_FLASH_MULTIPLIER: float = 2.5
FLOW_BUFF: float = 1.20                         # net_power x1.20 for the rest of the round

# v2-C: Black Flash rebuilds RCT. Each charge makes the NEXT heal cheaper + stronger.
RCT_CHARGE_CAP: int = 3
RCT_CHARGE_CE_DISCOUNT: float = 0.30           # -30% CE cost per charge consumed
RCT_CHARGE_HEAL_BONUS: float = 0.30            # +30% HP healed per charge consumed

# ---------------------------------------------------------------------------
# 6. HEALING — RCT / RCE (02 §7)
# ---------------------------------------------------------------------------
# v4/v5 PART 0 — damage caps (applied as the LAST step, after all multipliers).
MAX_SINGLE_HIT_FRACTION: float = 0.55   # no single hit exceeds 55% of target max_hp
BLACK_FLASH_CE_FACTOR_CAP: float = 1.0  # on a crit, ce_factor is clamped to 1.0
# (on the Black-Flash hit, the FLOW net_power buff does NOT also stack — see combat.py)

# v5 PART 2 — accuracy as a read, not a dice roll.
DEFAULT_ACCURACY: float = 0.85          # mid: grazed (halved) if the target evades
HIGH_ACCURACY_THRESHOLD: float = 0.9    # >= this IGNORES dodging (sure-hit / precision / contact)
LOW_ACCURACY_THRESHOLD: float = 0.7     # <= this AUTO-MISSES vs an evading target (heavy telegraph)
ACCURACY_RNG_TIEBREAK: float = 0.10     # +-10% RNG nudge near the boundary, never the main factor
GRAZE_MULT: float = 0.5                 # mid-accuracy attack into an evading target is halved
EVASIVE_ACTIONS: frozenset[str] = frozenset({
    "dodge", "simple_domain", "domain_amplification", "reinforce",
})

RCT_CE_TO_HP: float = 1.5   # 1 CE spent -> 1.5 HP healed
# Soul damage caps the max HP a fighter can heal back to (max_hp - soul_damage),
# and cannot be healed at all without the 'soul_sight' trait.

# ---------------------------------------------------------------------------
# 7. DOMAINS (02 §8) — [DECISION] concrete CE costs
# ---------------------------------------------------------------------------
DOMAIN_CE_COST: int = 45        # "high": ~one lethal domain per round
AMPLIFICATION_CE_COST: int = 20  # "medium"
SIMPLE_DOMAIN_CE_COST: int = 15  # "low"
DOMAIN_CLASH_CLOSE_GAP: float = 1.0   # |net_power diff| < this -> both domains cancel
DOMAIN_COLLAPSE_BACKLASH: int = 8      # HP backlash per user on a 3+ domain collapse
SIMPLE_DOMAIN_NET_POWER: float = 5.0   # a simple domain's neutralizing strength (02 §4/R5)

# ---------------------------------------------------------------------------
# 8. TURN ORDER & TICK LOOP (02 §9) — [DECISION] CE-weighted initiative, 12-tick cap
# ---------------------------------------------------------------------------
INITIATIVE_CE_WEIGHT: float = 0.5
INITIATIVE_RNG_SPAN: float = 20.0
MAX_TICKS: int = 14   # v2-F: combat cap; the storm is a tiebreaker that starts AFTER this

# v2-B engagement economy: fighters who acted (offense/domain/counter) last tick regain
# CE; passive (wait/reinforce) fighters get nothing and accrue the "passive" penalty.
ENGAGED_CE_PER_TICK: int = 4           # +CE next tick for acting last tick (waiters get 0)
PASSIVE_TICK_THRESHOLD: int = 2        # 2+ consecutive wait/reinforce -> "passive"
PASSIVE_CE_REGEN_PENALTY: float = 0.30  # passive fighters regen 30% less CE at round start

# v2-F: storm is a TIEBREAKER. It only fires past MAX_TICKS (so only if 2+ are still
# alive at the cap), starts soft, and ramps, dropping fighters one by one to a survivor.
SUDDEN_DEATH_START_TICK: int = MAX_TICKS + 1   # storm begins the tick after the cap
SUDDEN_DEATH_BASE: int = 4             # v2: softened from 6
SUDDEN_DEATH_RAMP: int = 5             # extra storm damage per tick past the start
HARD_TICK_CAP: int = 60                # absolute backstop to prevent an infinite loop

# ---------------------------------------------------------------------------
# 9. GENERATOR / BALANCE LAW (01 §5.3, 03 §A & §D)
# ---------------------------------------------------------------------------
POWER_MIN: int = 1
POWER_MAX: int = 10
BASELINE_POWER: int = 3   # complications only required above this

# REQUIRED_COMPLICATION_COST(power) = max(0, power - BASELINE_POWER)
COMPLICATION_COST_MIN: int = 1
COMPLICATION_COST_MAX: int = 10

# Which model invents techniques. DEFAULT "" = each fighter uses its OWN model (fast +
# varied — a gpt seat invents differently from a claude seat, and there's no slow shared
# local bottleneck). Set JJK_GENERATOR_MODEL to force one shared generator instead.
GENERATOR_MODEL_ID: str = os.getenv("JJK_GENERATOR_MODEL", "")
GENERATOR_MAX_TRIES: int = 2   # initial call + one repair, then clamp to a safe technique

# v2-D generator fairness: every fighter must have a damage option, and the per-round
# net_power spread is capped so no one gets an unwinnable pure-utility draw.
DAMAGE_TAGS: frozenset[str] = frozenset({
    "attack", "ranged", "melee", "aoe", "soul", "crit", "finisher", "ranged-finisher",
})
NET_POWER_SPREAD_MAX: float = 2.5   # max (highest - lowest) net_power across a round
NET_POWER_ROUND_FLOOR: float = 2.5  # v5: no technique in a round below this net_power

# v5 PART 3 — tier system. Phase 1 (rounds 1-3): all four fighters get a same-tier kit so
# only tactics differ. Each tier maps to a net_power band.
PHASE1_TIERS: tuple[str, ...] = ("S", "A", "B")   # picked per round (never C in canon phase)
TIER_NET_BAND: dict[str, tuple[int, int]] = {
    "S": (5, 6), "A": (4, 5), "B": (3, 4), "C": (2, 3),
}

# ---------------------------------------------------------------------------
# 10. PHASES (01 §5.2, 03 §A & §D)
#     phase 1 = rounds 1-3 (canon), 2 = 4-6 (imaginary-lawful), 3 = 7-10 (bizarre-weak)
# ---------------------------------------------------------------------------
NUM_ROUNDS: int = 10
PHASE_BOUNDARIES: tuple[int, int, int] = (3, 6, 10)  # last round of phases 1, 2, 3
PHASE_POWER_CEILING: dict[int, int] = {1: 7, 2: 9, 3: 4}
PHASE_POWER_RANGE: dict[int, tuple[int, int]] = {1: (4, 7), 2: (5, 9), 3: (1, 4)}
PHASE_NAMES: dict[int, str] = {
    1: "Canon",
    2: "Imaginary",
    3: "Bizarre",
}

# ---------------------------------------------------------------------------
# 11. HANDICAPS (01 §7) — Stage B; defined here so combat legality can read them
# ---------------------------------------------------------------------------
HANDICAP_UNLOCK_ROUND: int = 5
MAX_HANDICAPS_PER_FIGHTER: int = 1
HANDICAP_KINDS: tuple[str, ...] = (
    "no_rct", "no_domain", "reduced_ce", "frail_body", "no_extension",
)
FRAIL_BODY_HP_FACTOR: float = 0.6    # frail_body: lower HP...
FRAIL_BODY_DAMAGE_FACTOR: float = 1.3  # ...higher damage dealt
REDUCED_CE_FACTOR: float = 0.6
BINDING_VOW_POWER_BUMP: int = 2      # validated power bump granted for accepting a restriction
# Reveal gamble: explaining a technique makes it STRONGER on all fronts, but enemies see
# its weakness and can counter it (they get its full complications in their prompt).
REVEAL_POWER_BUMP: int = 1           # +power on the revealed technique
REVEAL_ACCURACY_BUMP: float = 0.05   # +accuracy (harder to dodge) on the revealed technique
REVEAL_DAMAGE_BONUS: float = 0.15    # round-long "revealed-resolve" -> +15% outgoing damage

# ---------------------------------------------------------------------------
# 12. PROMPTING CAPS (04 §GLOBAL) — enforced in templates and truncated in code
# ---------------------------------------------------------------------------
DIALOGUE_MAX_CHARS: int = 240
INTENT_MAX_CHARS: int = 200
THINKING_MAX_CHARS: int = 500   # inner-monologue strategy shown live
MEMORY_MAX_CHARS: int = 300
TEMP_CREATIVE: float = 0.7    # negotiate / dialogue
TEMP_DISCIPLINED: float = 0.3  # choose_move / react
TEMP_REFLECT: float = 0.5

# ---------------------------------------------------------------------------
# 13. MISC — seed, call budget, retries
# ---------------------------------------------------------------------------
DEFAULT_SEED: int = int(os.getenv("JJK_DEFAULT_SEED", "42"))
MAX_MODEL_CALLS: int = int(os.getenv("JJK_MAX_MODEL_CALLS", "0"))  # 0 = unlimited
MODEL_MAX_RETRIES: int = 3          # tenacity attempts per provider call
MODEL_RETRY_BASE_WAIT: float = 1.0  # exponential backoff base (seconds)
MODEL_TIMEOUT_S: float = 120.0
MODEL_MAX_TOKENS: int = 1024        # cap on generated tokens per call (Anthropic requires this)


# ---------------------------------------------------------------------------
# Pure helpers (no game imports). Combat/generator/phases call these.
# ---------------------------------------------------------------------------
def required_complication_cost(power: int) -> int:
    """Minimum total complication cost a technique of this power must carry."""
    return max(0, power - BASELINE_POWER)


def phase_for_round(round_number: int) -> int:
    """Map a 1-indexed round number to a phase (1, 2, or 3)."""
    p1, p2, _p3 = PHASE_BOUNDARIES
    if round_number <= p1:
        return 1
    if round_number <= p2:
        return 2
    return 3


def phase_name(phase: int) -> str:
    return PHASE_NAMES.get(phase, "Unknown")


def power_ceiling_for_phase(phase: int) -> int:
    return PHASE_POWER_CEILING.get(phase, POWER_MAX)
