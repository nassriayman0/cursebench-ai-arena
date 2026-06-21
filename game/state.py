"""game/state.py — all game-state & LLM-output schemas (pydantic v2).

The source of truth for a match is a plain-Python GameState (NOT Streamlit
session_state). LLMs never write numbers here; they propose a Move and the engine
computes outcomes, validating every LLM output against these schemas first.

Identity note: fighters are keyed by `character_name` (unique per match) rather
than company, so two seats may run the same company/model — essential for the
"compare AI models" goal. `company` is a flavor/voice tag only.
"""

from __future__ import annotations

import random
from typing import Literal, Optional

from pydantic import BaseModel, Field, PrivateAttr

from config import settings

ActionType = Literal[
    "attack", "domain_expansion", "domain_amplification", "simple_domain",
    "heal_rct", "reinforce", "dodge", "ally_propose", "ally_accept", "betray",
    "explain_technique", "wait", "binding_vow",
]

HandicapKind = Literal["no_rct", "no_domain", "reduced_ce", "frail_body", "no_extension"]


# ---------------------------------------------------------------------------
# Techniques & complications
# ---------------------------------------------------------------------------
class Complication(BaseModel):
    name: str
    description: str
    cost: int = Field(ge=1, le=10)        # how much it offsets power
    exploitable: bool = False             # is this a baitable/dodgeable opening?


class Technique(BaseModel):
    name: str
    theme: str = ""                       # e.g. "shadow", "luck", "blood"
    description: str = ""
    power: int = Field(ge=settings.POWER_MIN, le=settings.POWER_MAX)
    complications: list[Complication] = Field(default_factory=list)
    is_domain: bool = False
    is_rct: bool = False                  # reverse cursed technique (healing)
    tags: list[str] = Field(default_factory=list)   # ["sure-hit","ranged","soul","aoe"]
    phase_origin: int = 1                 # which round it was generated in
    revealed: bool = False                # explained to enemies? (R8: +1 power next use)
    accuracy: float = settings.DEFAULT_ACCURACY   # v5: 0.5-1.0; high ignores dodge, low is evadable
    tier: str = ""                        # v5: S/A/B/C (set for canon-phase kits)

    def total_complication_cost(self) -> int:
        return sum(c.cost for c in self.complications)


class Handicap(BaseModel):
    kind: HandicapKind
    description: str = ""


# ---------------------------------------------------------------------------
# Fighters
# ---------------------------------------------------------------------------
class Fighter(BaseModel):
    company: str                          # flavor/voice tag (e.g. "Anthropic")
    model_id: str
    character_name: str                   # unique identity / dict key
    voice_style: str = ""

    hp: int = settings.START_HP
    max_hp: int = settings.START_HP
    ce: int = settings.START_CE
    max_ce: int = settings.START_CE

    techniques: list[Technique] = Field(default_factory=list)
    handicaps: list[Handicap] = Field(default_factory=list)
    status: list[str] = Field(default_factory=list)   # transient: bleeding/domain-open/...
    traits: list[str] = Field(default_factory=list)   # persistent: soul_sight/heavenly_restriction
    alive_this_round: bool = True
    rounds_won: int = 0

    # combat bookkeeping (engine-managed; LLMs never touch these)
    soul_damage: int = 0                  # caps healable HP; needs soul_sight to clear
    consecutive_ce_hits: int = 0          # Black Flash flow counter
    reinforce_ce: int = 0                 # CE invested in reinforce this tick (mitigation)
    active_domain: Optional[Technique] = None
    last_action: Optional[str] = None     # for Black Flash "last was a CE melee" check
    pending_power_bonus: int = 0          # owed power bump from a binding vow (R8)
    # v2-B passivity / engagement economy
    consecutive_passive_ticks: int = 0    # wait/reinforce in a row -> "passive" status
    engaged_last_tick: bool = False       # acted offensively last tick -> +CE this tick
    passive_carry: bool = False           # ended a round passive -> reduced CE regen next
    # v2-C Black Flash rebuilds RCT
    rct_charge: int = 0                   # banked charges: next heals are cheaper + stronger
    # v5 bookkeeping
    has_acted: bool = False               # first-tick protection: can't be KO'd before acting
    last_technique_name: str = ""         # avoid handing the same base technique two rounds running

    def has_handicap(self, kind: str) -> bool:
        return any(h.kind == kind for h in self.handicaps)

    def technique_by_name(self, name: Optional[str]) -> Optional[Technique]:
        if not name:
            return None
        for t in self.techniques:
            if t.name == name:
                return t
        return None

    def effective_max_hp(self) -> int:
        """Soul damage lowers the ceiling RCT can heal back to (02 §7)."""
        return max(0, self.max_hp - self.soul_damage)


# ---------------------------------------------------------------------------
# Moves & records
# ---------------------------------------------------------------------------
class Move(BaseModel):
    actor: str
    action: ActionType
    target: Optional[str] = None
    technique_name: Optional[str] = None
    ce_spend: int = 0
    intent: str = ""
    dialogue: str = ""
    thinking: str = ""   # step-by-step inner monologue / strategy (shown live)


class SpecialEvent(BaseModel):
    tick: int
    type: str                              # "BLACK FLASH", "DOMAIN CLASH COLLAPSE", ...
    actors: list[str] = Field(default_factory=list)
    detail: str = ""

    def render(self) -> str:
        who = ", ".join(self.actors)
        return f"[t{self.tick}] {self.type}" + (f" — {who}" if who else "") + \
               (f": {self.detail}" if self.detail else "")


class RoundRecord(BaseModel):
    round_number: int
    phase: str
    generated_techniques: dict[str, Technique] = Field(default_factory=dict)  # name -> tech
    private_messages: list[dict] = Field(default_factory=list)
    moves: list[Move] = Field(default_factory=list)
    counters: list[dict] = Field(default_factory=list)
    special_events: list[SpecialEvent] = Field(default_factory=list)
    hp_ce_timeline: list[dict] = Field(default_factory=list)
    analyses: dict[str, str] = Field(default_factory=dict)  # name -> step-by-step debrief
    damage_dealt: dict[str, int] = Field(default_factory=dict)  # v2-E: per-fighter damage
    decided_by: str = "technique"        # v2-F: "technique" | "storm"
    summary: str = ""                    # v2-E: factual one-liner computed in Python
    survivor: Optional[str] = None
    round_winner: Optional[str] = None
    narration: str = ""


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------
class GameState(BaseModel):
    fighters: dict[str, Fighter]           # keyed by character_name
    round_number: int = 0
    records: list[RoundRecord] = Field(default_factory=list)
    match_options: dict = Field(default_factory=dict)
    rng_seed: int = settings.DEFAULT_SEED

    _rng: Optional[random.Random] = PrivateAttr(default=None)

    @property
    def rng(self) -> random.Random:
        """Seeded RNG — the single source of all randomness (reproducible replays)."""
        if self._rng is None:
            self._rng = random.Random(self.rng_seed)
        return self._rng

    def living_fighters(self) -> list[Fighter]:
        return [f for f in self.fighters.values() if f.alive_this_round and f.hp > 0]

    def fighter(self, name: str) -> Optional[Fighter]:
        return self.fighters.get(name)
