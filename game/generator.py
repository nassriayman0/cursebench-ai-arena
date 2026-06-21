"""game/generator.py — the phase-aware technique generator + the BALANCE CORE.

Two parts:
  1. `enforce_law` — pure-Python validator/clamp. This is where balance lives
     (01 §5.3, 03 §D). Deterministic and unit-tested. Guarantees a lawful
     Technique no matter what the LLM produced.
  2. `generate_technique` — builds a phase-specific prompt from data/jjk_canon.md,
     asks the generator model for a strict-JSON draft, then runs `enforce_law`.
     On repeated parse failure it falls back to a safe lawful technique
     (never crashes a match).

LLMs propose flavor + numbers; Python enforces `sum(cost) >= max(0, power-3)`,
the phase ceiling, ≥1 exploitable complication, and handicap consistency.
"""

from __future__ import annotations

import math
import os
import random
from functools import lru_cache
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from config import settings
from game.state import Complication, Fighter, Technique
from models.structured import StructuredOutputError, call_model_json
from util.logging import CallMeter, get_logger

_log = get_logger("jjk.generator")
_CANON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "jjk_canon.md")

# Phrases that signal a vague (non-exploitable) complication — rejected (03 §D.2).
_VAGUE_MARKERS = ("sometimes", "maybe", "a bit", "somewhat", "occasionally",
                  "might be weaker", "can be weaker", "slightly")

# Real JJK techniques for phase 1 (rounds 1-3). If a small model invents something
# non-canon in phase 1, we SNAP to one of these so the user always sees a real one.
# (name, theme, power, tags, built-in complication)
CANON_BANK = [
    ("Limitless: Infinity", "space", 7, ["ranged", "defense", "sure-hit"],
     "Colossal CE cost and brain strain — overuse leaves you open; nullify-tools bypass it"),
    ("Ten Shadows Technique", "summoning", 7, ["summon", "adaptive", "melee"],
     "A destroyed shikigami is gone for good; the strongest one can turn on you"),
    ("Malevolent Shrine: Dismantle & Cleave", "cutting", 7, ["melee", "ranged", "aoe", "sure-hit"],
     "Barrierless domain has a smaller sure-hit radius; the flame needs the cooking steps first"),
    ("Straw Doll Technique: Resonance", "voodoo", 6, ["ranged", "soul"],
     "Needs a physical fragment (hair/blood) of the target first; CE-heavy"),
    ("Cursed Speech", "command", 6, ["control", "self-damage", "ranged"],
     "Strong commands tear your own throat (self-damage) and must be heard"),
    ("Ratio Technique", "precision", 6, ["melee", "crit"],
     "Melee range only; struggles badly against ranged foes"),
    ("Idle Transfiguration", "soul", 7, ["melee", "soul", "heal-self"],
     "Requires touch; only soul attacks can hurt you back"),
    ("Boogie Woogie", "swap", 5, ["utility", "mobility"],
     "Needs a clap (telegraph); pure utility, no direct damage"),
    ("Blood Manipulation: Piercing Blood", "blood", 6, ["ranged", "melee"],
     "Convergence charge-up leaves you open; weak to water and anemia"),
    ("Construction", "creation", 7, ["utility", "ranged", "summon"],
     "Extremely CE-inefficient — only a few uses before you run dry"),
    ("Star Rage: Bonbaie", "mass", 7, ["melee", "ranged-finisher"],
     "Adds force but NOT durability to you; heavily telegraphed"),
    ("Projection Sorcery", "frames", 7, ["melee", "control", "self-risk"],
     "You must also obey the 24-fps rule or freeze yourself; readable"),
    ("Cursed Spirit Manipulation: Maximum Uzumaki", "curses", 7, ["summon", "aoe"],
     "Absorbing curses costs CE and mental burden; Uzumaki is slow to charge"),
    ("Disaster Flames", "fire", 7, ["ranged", "aoe", "fire"],
     "Big eruptions need a charge; vulnerable while winding up"),
    ("Disaster Plants", "nature", 6, ["melee", "ranged", "summon"],
     "Weak to fire; the draining seeds work slowly"),
    ("Mythical Beast Amber", "lightning", 7, ["ranged", "sure-hit", "melee"],
     "ONE-TIME use — your body crumbles afterward"),
    ("Idle Death Gamble: Jackpot", "luck", 7, ["heal-self", "buff"],
     "Jackpot odds are 1 in 239 — near-useless until it finally hits"),
    ("Jacob's Ladder", "holy", 7, ["ranged", "nullify", "anti-technique"],
     "Hesitation and mercy weaken it; reduced output when you are wounded"),
    ("Sky Manipulation: Thin Ice Breaker", "space", 7, ["ranged", "defense", "melee"],
     "The frames are readable; your domain is hard to manifest"),
    ("Granite Blast", "output", 7, ["ranged", "finisher"],
     "Pure raw output, no finesse and no defense boost; heavily telegraphed"),
]
CANON_NAMES = [e[0] for e in CANON_BANK]

# v5 PART 3 — tier of each canon technique (S/A/B/C). Mirrors 03_JJK_CANON.md §H.
TECHNIQUE_TIERS = {
    "Limitless: Infinity": "S",
    "Malevolent Shrine: Dismantle & Cleave": "S",
    "Idle Transfiguration": "S",
    "Cursed Spirit Manipulation: Maximum Uzumaki": "S",
    "Ten Shadows Technique": "A",
    "Cursed Speech": "A",
    "Blood Manipulation: Piercing Blood": "A",
    "Construction": "A",
    "Star Rage: Bonbaie": "A",          # high-A, deliberately NOT S
    "Projection Sorcery": "A",
    "Disaster Flames": "A",
    "Mythical Beast Amber": "A",
    "Idle Death Gamble: Jackpot": "A",
    "Jacob's Ladder": "A",
    "Sky Manipulation: Thin Ice Breaker": "A",
    "Granite Blast": "A",
    "Straw Doll Technique: Resonance": "B",
    "Ratio Technique": "B",
    "Boogie Woogie": "B",
    "Disaster Plants": "B",
}


def tier_of(name: str) -> str:
    return TECHNIQUE_TIERS.get(name, "B")


def _accuracy_from_tags(tags) -> float:
    """v5 PART 2: derive canon accuracy from tags. Sure-hit/precision/contact ~0.95
    (ignores dodging); telegraphed heavy hitters ~0.60 (evadable); else mid (0.85)."""
    s = set(tags)
    if s & {"sure-hit", "crit", "soul"}:
        return 0.95
    if s & {"finisher", "ranged-finisher", "aoe"}:
        return 0.60
    return settings.DEFAULT_ACCURACY
# Distinctive words that mark a name as canon (for the phase-1 keep/snap check).
_CANON_KEYWORDS = {
    "limitless", "infinity", "shadows", "mahoraga", "shikigami", "malevolent", "shrine",
    "dismantle", "cleave", "straw doll", "resonance", "cursed speech", "ratio", "idle",
    "transfiguration", "boogie", "woogie", "blood", "piercing", "construction", "star rage",
    "bonbaie", "projection", "uzumaki", "cursed spirit", "disaster", "flames", "plants",
    "tides", "amber", "kashimo", "jackpot", "death gamble", "jacob", "ladder", "sky",
    "thin ice", "copy", "comedian", "bird", "granite", "blast", "rendezvous", "contractual",
    "domain", "void",
}


# --- Lenient draft schemas (the LLM fills these; enforce_law clamps to spec) ---
class ComplicationDraft(BaseModel):
    name: str = ""
    description: str = ""
    cost: int = 1
    exploitable: bool = False


class TechniqueDraft(BaseModel):
    name: str = "Unnamed Technique"
    theme: str = ""
    description: str = ""
    power: int = 4
    complications: list[ComplicationDraft] = Field(default_factory=list)
    is_domain: bool = False
    is_rct: bool = False
    tags: list[str] = Field(default_factory=list)


@lru_cache(maxsize=1)
def _canon_text() -> str:
    try:
        with open(_CANON_PATH, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# THE BALANCE CORE — pure Python, deterministic
# ---------------------------------------------------------------------------
def _is_vague(text: str) -> bool:
    low = text.lower().strip()
    if len(low) < 8:                       # too short to be a concrete, exploitable condition
        return True
    return any(marker in low for marker in _VAGUE_MARKERS)


def law_violations(tech: Technique, phase: int) -> list[str]:
    """Return a list of balance-law violations (empty == lawful). Used by tests."""
    problems: list[str] = []
    ceiling = settings.power_ceiling_for_phase(phase)
    if not (settings.POWER_MIN <= tech.power <= ceiling):
        problems.append(f"power {tech.power} outside [{settings.POWER_MIN}, {ceiling}]")
    required = settings.required_complication_cost(tech.power)
    if tech.total_complication_cost() < required:
        problems.append(
            f"complication cost {tech.total_complication_cost()} < required {required}")
    if tech.power > settings.BASELINE_POWER and not any(c.exploitable for c in tech.complications):
        problems.append("no opponent-exploitable complication")
    if any(_is_vague(c.description) for c in tech.complications):
        problems.append("contains a vague (non-concrete) complication")
    return problems


def is_lawful(tech: Technique, phase: int) -> bool:
    return not law_violations(tech, phase)


def enforce_law(draft: TechniqueDraft, phase: int, round_number: int,
                handicaps: Iterable[str] = ()) -> Technique:
    """Turn any draft into a guaranteed-lawful Technique by clamping/repairing.

    Steps (deterministic):
      - drop vague complications; clamp each cost to [1, 10]
      - clamp power to [POWER_MIN, phase ceiling]
      - if total cost < required(power), clamp power DOWN to total_cost + BASELINE
        (strong-but-conditional -> moderate-and-clean; never fabricate fake drawbacks)
      - guarantee >=1 exploitable complication when power > BASELINE
      - force is_domain/is_rct false if a handicap forbids them
    """
    handicaps = set(handicaps)

    # 1. clean complications
    comps: list[Complication] = []
    for c in draft.complications:
        if _is_vague(c.description):
            continue
        comps.append(Complication(
            name=c.name or "Condition",
            description=c.description,
            cost=max(settings.COMPLICATION_COST_MIN, min(settings.COMPLICATION_COST_MAX, c.cost)),
            exploitable=c.exploitable,
        ))

    # 2. clamp power to phase ceiling
    ceiling = settings.power_ceiling_for_phase(phase)
    power = max(settings.POWER_MIN, min(draft.power, ceiling))

    # 3. enforce the ratio by clamping power down to what the drawbacks support
    total_cost = sum(c.cost for c in comps)
    if total_cost < settings.required_complication_cost(power):
        power = max(settings.POWER_MIN, total_cost + settings.BASELINE_POWER)
        power = min(power, ceiling)

    # 4. guarantee an exploitable opening above baseline
    if power > settings.BASELINE_POWER and comps and not any(c.exploitable for c in comps):
        top = max(range(len(comps)), key=lambda i: comps[i].cost)
        comps[top] = comps[top].model_copy(update={"exploitable": True})

    # 5. handicap consistency
    is_domain = draft.is_domain and "no_domain" not in handicaps
    is_rct = draft.is_rct and "no_rct" not in handicaps

    clean_tags = [t for t in draft.tags if t]
    return Technique(
        name=draft.name or "Unnamed Technique",
        theme=draft.theme,
        description=draft.description,
        power=power,
        complications=comps,
        is_domain=is_domain,
        is_rct=is_rct,
        tags=clean_tags,
        phase_origin=round_number,
        accuracy=_accuracy_from_tags(clean_tags),
    )


def _net_power(tech: Technique) -> float:
    return max(settings.NET_POWER_FLOOR,
               tech.power - settings.NET_POWER_COMPLICATION_WEIGHT * tech.total_complication_cost())


def is_damage_capable(tech: Technique) -> bool:
    """True if the technique can actually deal damage (v2-D)."""
    return any(t in settings.DAMAGE_TAGS for t in tech.tags)


def cursed_strike(round_number: int) -> Technique:
    """The basic CE-strike fallback granted to a fighter with no damage option (v2-D)."""
    return Technique(name="Cursed Strike", theme="raw cursed energy",
                     description="A basic burst of cursed energy shaped into a blow.",
                     power=3, complications=[], tags=["melee"], phase_origin=round_number,
                     accuracy=_accuracy_from_tags(["melee"]))


def balance_round_spread(techs: list[Technique], round_number: int) -> None:
    """v2-D: cap the per-round net_power spread at NET_POWER_SPREAD_MAX by lifting the
    low outliers (never nerfing) so no fighter gets an unwinnable weak draw."""
    if len(techs) < 2:
        return
    ceiling = settings.power_ceiling_for_phase(settings.phase_for_round(round_number))
    # v5: lift weak outliers to within SPREAD_MAX of the top AND to the absolute round floor.
    target_floor = max(max(_net_power(t) for t in techs) - settings.NET_POWER_SPREAD_MAX,
                       settings.NET_POWER_ROUND_FLOOR)
    for t in techs:
        if _net_power(t) < target_floor:
            need = target_floor + settings.NET_POWER_COMPLICATION_WEIGHT * t.total_complication_cost()
            t.power = max(t.power, min(ceiling, math.ceil(need)))  # ceil so net actually clears floor


def safe_fallback(phase: int, round_number: int,
                  handicaps: Iterable[str] = ()) -> Technique:
    """A deterministic lawful technique used when generation can't produce one."""
    ceiling = settings.power_ceiling_for_phase(phase)
    power = min(4, ceiling)
    return Technique(
        name="Cursed Strike",
        theme="raw cursed energy",
        description="A reliable burst of cursed energy shaped into a striking blow.",
        power=power,
        complications=[Complication(
            name="Telegraphed wind-up",
            description="A visible charge-up the enemy can read and dodge or interrupt.",
            cost=2, exploitable=True,
        )],
        tags=["melee"],
        phase_origin=round_number,
        accuracy=_accuracy_from_tags(["melee"]),
    )


# ---------------------------------------------------------------------------
# Generation (LLM)
# ---------------------------------------------------------------------------
_PHASE_GUIDANCE = {
    1: ("CANON", "Choose ONE REAL Jujutsu Kaisen technique from the Technique Bank and "
                 "keep its REAL name (re-flavor the description only). Do NOT invent one."),
    2: ("IMAGINARY-LAWFUL", "Invent a fresh technique (luck, memory, rule-rewrite, "
                            "gravity, time-slice...). High power demands harsh, concrete, "
                            "exploitable complications."),
    3: ("BIZARRE-WEAK", "Invent a strange, narrow, deliberately WEAK technique (affects "
                        "only X; works only while doing Y). Force clever use of a weak tool."),
}


def _build_prompt(fighter: Fighter, phase: int, round_number: int) -> tuple[str, str]:
    name, instruction = _PHASE_GUIDANCE[phase]
    lo, hi = settings.PHASE_POWER_RANGE[phase]
    ceiling = settings.power_ceiling_for_phase(phase)
    known = ", ".join(t.theme or t.name for t in fighter.techniques) or "none yet"

    system = (
        "You are the JJK Arena technique generator. You invent ONE balanced cursed "
        "technique as a single strict JSON object. Follow the canon and the balance law.\n\n"
        + _canon_text()
    )
    canon_line = ""
    if phase == 1:
        canon_line = ("REAL techniques to choose from (use one of these EXACT names): "
                      + "; ".join(CANON_NAMES) + ".\n")
    user = (
        f"Generate ONE technique for the sorcerer '{fighter.character_name}'.\n"
        f"ROUND {round_number} — PHASE: {name}. {instruction}\n"
        f"{canon_line}"
        f"Power range this phase: {lo}-{hi} (hard ceiling {ceiling}).\n"
        f"This fighter's existing themes: {known}.\n"
        f"BALANCE LAW: sum(complication.cost) >= max(0, power - {settings.BASELINE_POWER}). "
        f"At least one complication MUST be opponent-exploitable (baitable/dodgeable) — set "
        f'its "exploitable" field true. Complications must be concrete and triggered, never vague.\n\n'
        "Reply with ONE JSON object, exactly these keys:\n"
        '{"name": str, "theme": str, "description": str, "power": int, '
        '"complications": [{"name": str, "description": str, "cost": int(1-10), '
        '"exploitable": bool}], "is_domain": bool, "is_rct": bool, "tags": [str]}'
    )
    return system, user


def _is_canon_name(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in _CANON_KEYWORDS)


def _canon_technique(entry: tuple, fighter: Fighter, round_number: int) -> Technique:
    name, theme, power, tags, weak = entry
    draft = TechniqueDraft(
        name=name, theme=theme,
        description=f"The cursed technique {name}, wielded by {fighter.character_name}.",
        power=power, tags=list(tags),
        complications=[ComplicationDraft(name="Canon weakness", description=weak,
                                         cost=max(2, power - settings.BASELINE_POWER),
                                         exploitable=True)],
    )
    tech = enforce_law(draft, phase=1, round_number=round_number,
                       handicaps=[h.kind for h in fighter.handicaps])
    tech.tier = tier_of(name)
    return tech


def _canon_technique_tiered(entry: tuple, fighter: Fighter, round_number: int,
                            tier: str, target_net: float) -> Technique:
    """Build a canon technique with net_power set to the tier band (v5 PART 3).

    Canon-phase kits are balanced by being the SAME tier, so we set net_power directly
    from the band rather than via the complication ratio (a deliberate exception)."""
    name, theme, _bank_power, tags, weak = entry
    comp_cost = 3
    power = max(1, min(settings.POWER_MAX,
                       round(target_net + settings.NET_POWER_COMPLICATION_WEIGHT * comp_cost)))
    return Technique(
        name=name, theme=theme,
        description=f"The cursed technique {name}, wielded by {fighter.character_name}.",
        power=power,
        complications=[Complication(name="Canon weakness", description=weak,
                                    cost=comp_cost, exploitable=True)],
        tags=list(tags), phase_origin=round_number,
        accuracy=_accuracy_from_tags(tags), tier=tier,
    )


def assign_canon_round(fighters: list[Fighter], round_number: int, rng) -> list[Technique]:
    """v5 PART 3: in the canon phase, hand every fighter a UNIQUE real technique of the
    SAME tier so kits are equally powerful and only tactics differ."""
    n = len(fighters)
    viable = [t for t in settings.PHASE1_TIERS
              if sum(1 for e in CANON_BANK if tier_of(e[0]) == t) >= n]
    tier = rng.choice(viable) if viable else "A"
    lo, hi = settings.TIER_NET_BAND[tier]
    target_net = (lo + hi) / 2.0
    pool = [e for e in CANON_BANK if tier_of(e[0]) == tier]
    rng.shuffle(pool)

    techs: list[Technique] = []
    used: set[str] = set()
    for f in fighters:
        entry = next((e for e in pool if e[0].lower() not in used
                      and e[0] != f.last_technique_name), None)
        if entry is None:  # all used / all match last -> allow a repeat of an unused one
            entry = next((e for e in pool if e[0].lower() not in used), pool[0])
        used.add(entry[0].lower())
        techs.append(_canon_technique_tiered(entry, f, round_number, tier, target_net))
    return techs


def _canon_seed(fighter: Fighter, round_number: int) -> int:
    return round_number * 1009 + sum(ord(c) for c in fighter.character_name)


def pick_canon_technique(fighter: Fighter, round_number: int) -> Technique:
    """A real JJK technique, chosen deterministically per fighter/round (phase 1)."""
    entry = random.Random(_canon_seed(fighter, round_number)).choice(CANON_BANK)
    return _canon_technique(entry, fighter, round_number)


def pick_unused_canon(used_names: set[str], fighter: Fighter, round_number: int) -> Technique:
    """A real JJK technique whose name isn't already taken this round (for dedup)."""
    bank = CANON_BANK[:]
    random.Random(_canon_seed(fighter, round_number)).shuffle(bank)
    used_low = {n.lower() for n in used_names}
    for entry in bank:
        if entry[0].lower() not in used_low:
            return _canon_technique(entry, fighter, round_number)
    return _canon_technique(bank[0], fighter, round_number)  # all taken (>20 fighters)


def generate_technique(model_id: str, fighter: Fighter, round_number: int,
                       *, meter: Optional[CallMeter] = None) -> Technique:
    """Generate one lawful technique for a fighter this round (LLM + enforce_law).

    In phase 1 (rounds 1-3) the result MUST be a real JJK technique — if the model
    invents something non-canon, we snap to one from CANON_BANK.
    """
    phase = settings.phase_for_round(round_number)
    handicaps = [h.kind for h in fighter.handicaps]
    system, user = _build_prompt(fighter, phase, round_number)

    for attempt in range(settings.GENERATOR_MAX_TRIES):
        try:
            draft = call_model_json(
                model_id, system, [{"role": "user", "content": user}],
                schema=TechniqueDraft, temperature=settings.TEMP_CREATIVE,
                call_type="generate", meter=meter, use_cache=False,
            )
            tech = enforce_law(draft, phase, round_number, handicaps)
            if phase == 1 and not _is_canon_name(tech.name):
                snapped = pick_canon_technique(fighter, round_number)
                _log.info("phase-1 non-canon '%s' -> snapped to '%s' for %s",
                          tech.name, snapped.name, fighter.character_name)
                tech = snapped
            _log.info("generated '%s' P%d cost%d (phase %d) for %s",
                      tech.name, tech.power, tech.total_complication_cost(),
                      phase, fighter.character_name)
            return tech
        except StructuredOutputError as exc:
            _log.warning("technique gen attempt %d failed for %s: %s",
                         attempt + 1, fighter.character_name, exc)
        except Exception as exc:  # noqa: BLE001 - provider down / budget: never crash a round
            _log.warning("technique gen errored for %s (%s) -> fallback",
                         fighter.character_name, exc)
            break

    if phase == 1:
        return pick_canon_technique(fighter, round_number)
    _log.warning("falling back to safe technique for %s", fighter.character_name)
    return safe_fallback(phase, round_number, handicaps)
