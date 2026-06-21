"""game/phases.py — escalation flavor + the binding-vow handicap system (01 §7).

Phase boundaries / ceilings / ranges already live in config/settings.py (read by
the generator). This module adds:
  - escalation banner text per round (canon -> imaginary -> bizarre)
  - the round-5+ handicap offer: exactly one per fighter, framed as a binding vow
    (accept a restriction now for a validated power bump on this round's technique).
"""

from __future__ import annotations

from config import settings
from game.state import Fighter, GameState, Handicap

ESCALATION_BANNERS = {
    1: "Canon Phase — real JJK techniques. Fight by the book.",
    2: "Imaginary Phase — invented but lawful. Power spikes; drawbacks bite harder. "
       "Binding-vow handicaps are now on the table.",
    3: "Bizarre Phase — rare, narrow, deliberately weak techniques. Win with cleverness, not power.",
}

HANDICAP_DESCRIPTIONS = {
    "no_rct": "Forsake Reverse Cursed Technique — you can no longer heal.",
    "no_domain": "Forsake Domain Expansion — no sure-hit zone for you.",
    "reduced_ce": "Bind your cursed energy — your max CE is cut.",
    "frail_body": "A Heavenly-Restriction body — far less HP, but your strikes hit harder.",
    "no_extension": "Seal your technique's extensions — only its base form remains.",
}


def escalation_banner(round_number: int) -> str:
    phase = settings.phase_for_round(round_number)
    return ESCALATION_BANNERS.get(phase, "")


def eligible_for_handicap(fighter: Fighter, round_number: int) -> bool:
    return (round_number >= settings.HANDICAP_UNLOCK_ROUND
            and len(fighter.handicaps) < settings.MAX_HANDICAPS_PER_FIGHTER)


def offer_handicaps(state: GameState, fighter: Fighter, n: int = 3) -> list[Handicap]:
    """Engine offers a small menu of balanced restrictions for a binding vow."""
    kinds = list(settings.HANDICAP_KINDS)
    state.rng.shuffle(kinds)
    chosen = kinds[:max(1, min(n, len(kinds)))]
    return [Handicap(kind=k, description=HANDICAP_DESCRIPTIONS[k]) for k in chosen]


def apply_binding_vow(fighter: Fighter, handicap: Handicap) -> None:
    """Apply the accepted restriction's effects and grant the power bump (R8)."""
    if len(fighter.handicaps) >= settings.MAX_HANDICAPS_PER_FIGHTER:
        return
    fighter.handicaps.append(handicap)

    if handicap.kind == "reduced_ce":
        fighter.max_ce = round(fighter.max_ce * settings.REDUCED_CE_FACTOR)
        fighter.ce = min(fighter.ce, fighter.max_ce)
    elif handicap.kind == "frail_body":
        fighter.max_hp = round(fighter.max_hp * settings.FRAIL_BODY_HP_FACTOR)
        fighter.hp = min(fighter.hp, fighter.max_hp)
        if "frail_body" not in fighter.traits:
            fighter.traits.append("frail_body")
    # no_rct / no_domain / no_extension are enforced via legality / flavor.

    # The validated power bump applies to this round's (or the next) technique.
    fighter.pending_power_bonus += settings.BINDING_VOW_POWER_BUMP
