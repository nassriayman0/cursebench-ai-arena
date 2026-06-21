"""game/setup.py — build a GameState + agents from a seat lineup.

Shared by run_console.py and the Streamlit UI so match construction lives in one
place. Seats are model-agnostic: each seat is any registry model_id + a name.
"""

from __future__ import annotations

from typing import Optional

from config.models import NAME_PRESETS, get_spec
from game.state import Fighter, GameState
from interfaces.agent import SorcererAgent
from prompting.personas import voice_for
from util.logging import CallMeter

DEFAULT_OPTIONS = {
    "enable_negotiation": True,
    "enable_handicaps": True,
    "enable_reflect": True,
    "enable_react": False,
    "enable_director": False,
}


def unique_name(company: str, used: set[str]) -> str:
    base = NAME_PRESETS.get(company, f"{company} Sorcerer")
    name, n = base, 2
    while name in used:
        name, n = f"{base} {n}", n + 1
    used.add(name)
    return name


def build_game_state(seats: list[str], names: Optional[list[str]] = None, *,
                     seed: int, options: Optional[dict] = None,
                     match_id: Optional[str] = None) -> GameState:
    names = names or []
    fighters: dict[str, Fighter] = {}
    used: set[str] = set()
    for i, seat in enumerate(seats):
        spec = get_spec(seat)  # raises on unknown id
        if i < len(names) and names[i]:
            name = names[i]
            used.add(name)
        else:
            name = unique_name(spec.company, used)
        fighters[name] = Fighter(
            company=spec.company, model_id=seat, character_name=name,
            voice_style=voice_for(spec.company),
        )
    match_options = {**DEFAULT_OPTIONS, **(options or {})}
    match_options.setdefault("seats", list(seats))
    match_options.setdefault("match_id", match_id or f"match_seed{seed}")
    return GameState(fighters=fighters, rng_seed=seed, match_options=match_options)


def build_agents(state: GameState, meter: Optional[CallMeter] = None) -> dict[str, SorcererAgent]:
    return {name: SorcererAgent(name, f.model_id, meter)
            for name, f in state.fighters.items()}
