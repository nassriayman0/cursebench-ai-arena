"""util/persistence.py — save/load a GameState (+ records) to ./saves/*.json.

Persists the seeded RNG's internal state alongside the model so a reloaded match
replays bit-for-bit (combined with per-match LLM response caching in Stage B).
"""

from __future__ import annotations

import json
import os
import random
from typing import Optional

from game.state import GameState

SAVES_DIR = os.path.join(os.getcwd(), "saves")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def default_match_id(state: GameState) -> str:
    explicit = state.match_options.get("match_id")
    return explicit or f"match_seed{state.rng_seed}_r{state.round_number}"


def save_match(state: GameState, match_id: Optional[str] = None,
               saves_dir: str = SAVES_DIR) -> str:
    """Write the GameState to <saves_dir>/<match_id>.json and return the path."""
    _ensure_dir(saves_dir)
    match_id = match_id or default_match_id(state)
    data = state.model_dump(mode="json")

    # Capture RNG internal state for exact resumption (getstate initializes from
    # seed if untouched, which is still the correct pre-roll state).
    version, internal, gauss = state.rng.getstate()
    data["_rng_state"] = [version, list(internal), gauss]

    path = os.path.join(saves_dir, f"{match_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return path


def load_match(path: str) -> GameState:
    """Load a GameState from a saved JSON file, restoring RNG state if present."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    rng_state = data.pop("_rng_state", None)
    state = GameState.model_validate(data)
    if rng_state is not None:
        version, internal, gauss = rng_state
        rng = random.Random()
        rng.setstate((version, tuple(internal), gauss))
        state._rng = rng
    return state
