"""game/counters.py — canon hard-counter matrix (v5 PART 4).

Mirrors 03_JJK_CANON.md §I. `counter_rows_for` returns the advice lines relevant to
a set of opponent techniques, which the agent's choose_move/react prompts include so
play is technique-aware (e.g. never melee into Infinity).
"""

from __future__ import annotations

# keyword (matched in a technique name, lowercase) -> counter advice
COUNTER_MATRIX: dict[str, str] = {
    "infinity": ("Infinity / Limitless (space denial): anything that must physically "
                 "approach NEVER arrives. BEAT IT with Domain Amplification, space-cutting "
                 "/ space-targeting attacks, technique-nullifiers, or by overwhelming a "
                 "domain clash. Do NOT spam melee into it — bait their cursed energy instead."),
    "limitless": ("Limitless: do not melee into it. Use amplification, nullify, space-cut, "
                  "or bait their CE."),
    "ten shadows": ("Ten Shadows: versatile shikigami, each with a role. Mahoraga ADAPTS to "
                    "anything it has seen — but its summon ritual kills the user unless they "
                    "win, so it's a last resort. Force them to over-commit; vary your attacks."),
    "mahoraga": "Mahoraga adapts to any technique it has seen — vary attacks; never repeat the same hit.",
    "idle transfiguration": ("Idle Transfiguration kills on touch (soul) — STAY RANGED; "
                             "counter with ranged soul-hits."),
    "cursed speech": ("Cursed Speech must be HEARD — interrupt/deny hearing to negate it; "
                      "strong commands also damage the user's own throat."),
    "star rage": ("Star Rage is telegraphed heavy mass with NO extra durability — DODGE / "
                  "reposition to auto-evade it, then punish."),
    "granite blast": ("Granite Blast is a wide telegraphed beam — dodge / reposition to "
                      "evade, then punish the recovery."),
    "bird strike": "Bird Strike is interceptable before contact — destroy the crow or block its line.",
    "shrine": ("Malevolent Shrine / Dismantle is a barrierless sure-hit cut you can't dodge — "
               "answer with Simple Domain, Amplification, or out-clash the domain."),
    "ratio": "Ratio needs melee range and a precise 7:3 point — keep distance and break their rhythm.",
    "resonance": "Straw Doll Resonance needs a physical fragment of you first — deny them a sample.",
    "uzumaki": "Maximum Uzumaki is a slow-charging bomb — pressure them before it charges.",
}

# Self-heal counter, keyed off is_rct / heal-self rather than a name.
_HEAL_COUNTER = ("Self-healers (RCT / Idle Transfiguration): use SOUL-damage — it can't be "
                 "healed without soul-sight and caps their max HP.")


def counter_rows_for(opponent_techs) -> list[str]:
    """Advice lines for the canon counters of the given opponent techniques."""
    rows: list[str] = []
    seen: set[str] = set()
    for t in opponent_techs:
        low = (t.name or "").lower()
        for key, advice in COUNTER_MATRIX.items():
            if key in low and key not in seen:
                rows.append(advice)
                seen.add(key)
        if (getattr(t, "is_rct", False) or "heal-self" in (t.tags or [])) and "heal" not in seen:
            rows.append(_HEAL_COUNTER)
            seen.add("heal")
    return rows
