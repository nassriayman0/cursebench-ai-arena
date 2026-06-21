"""game/scoring.py — round/match outcomes + the cross-match leaderboard.

Round winner = last one standing (even at 1 HP) — decided in the engine. Match
winner = most rounds won; tiebreak = total surviving HP across rounds, then
head-to-head. The leaderboard aggregates per model_id so you can compare which AI
actually wins more (the point of the whole app).
"""

from __future__ import annotations

import json
import os
from typing import Optional

from game.state import Fighter, GameState

LEADERBOARD_PATH = os.path.join(os.getcwd(), "saves", "leaderboard.json")


def _total_surviving_hp(state: GameState, name: str) -> int:
    """Sum of this fighter's HP at the end of each round (tiebreaker)."""
    total = 0
    for rec in state.records:
        if rec.hp_ce_timeline:
            total += rec.hp_ce_timeline[-1].get("hp", {}).get(name, 0)
    return total


def _head_to_head(state: GameState, name: str) -> int:
    """Rounds this fighter won where it was the sole survivor (secondary tiebreak)."""
    return sum(1 for rec in state.records if rec.round_winner == name)


def standings(state: GameState) -> list[Fighter]:
    """Fighters sorted best-first by (rounds_won, total surviving HP, head-to-head)."""
    return sorted(
        state.fighters.values(),
        key=lambda f: (f.rounds_won,
                       _total_surviving_hp(state, f.character_name),
                       _head_to_head(state, f.character_name)),
        reverse=True,
    )


def match_winner(state: GameState) -> Optional[Fighter]:
    ranked = standings(state)
    return ranked[0] if ranked else None


# ---------------------------------------------------------------------------
# Leaderboard (persisted across matches)
# ---------------------------------------------------------------------------
def load_leaderboard(path: str = LEADERBOARD_PATH) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    return {"models": {}, "matches_recorded": 0}


def update_leaderboard(state: GameState, path: str = LEADERBOARD_PATH) -> dict:
    """Fold a finished match into the leaderboard and persist it."""
    board = load_leaderboard(path)
    models = board.setdefault("models", {})
    winner = match_winner(state)
    winner_name = winner.character_name if winner else None
    rounds_played = len(state.records)

    for f in state.fighters.values():
        entry = models.setdefault(f.model_id, {
            "display": f.model_id, "company": f.company,
            "matches": 0, "match_wins": 0, "rounds_won": 0, "rounds_played": 0,
        })
        entry["matches"] += 1
        entry["rounds_won"] += f.rounds_won
        entry["rounds_played"] += rounds_played
        if f.character_name == winner_name:
            entry["match_wins"] += 1

    board["matches_recorded"] = board.get("matches_recorded", 0) + 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(board, fh, indent=2, ensure_ascii=False)
    return board


def leaderboard_rows(board: dict) -> list[dict]:
    """Flatten the leaderboard into sorted rows for display."""
    rows = []
    for model_id, e in board.get("models", {}).items():
        winrate = (e["match_wins"] / e["matches"]) if e["matches"] else 0.0
        rows.append({"model_id": model_id, **e, "win_rate": winrate})
    return sorted(rows, key=lambda r: (r["match_wins"], r["rounds_won"]), reverse=True)
