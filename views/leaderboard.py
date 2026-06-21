"""views/leaderboard.py — cross-match standings per model (the comparison view)."""

from __future__ import annotations

import streamlit as st

from game import scoring
from views import components as C


def render() -> None:
    st.header("🏆 Leaderboard — which AI wins more?")

    # Current match standings (if a match is loaded)
    state = st.session_state.get("state")
    if state is not None and state.records:
        st.subheader("This match")
        rows = []
        for f in scoring.standings(state):
            rows.append({"character": f.character_name, "model": f.model_id,
                         "company": f.company, "rounds_won": f.rounds_won})
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("All-time (per model, across matches)")
    board = scoring.load_leaderboard()
    rows = scoring.leaderboard_rows(board)
    if not rows:
        st.caption("No completed matches recorded yet. Finish a match in the Arena.")
        return
    table = [{
        "model": r["model_id"], "company": r.get("company", ""),
        "matches": r["matches"], "match_wins": r["match_wins"],
        "win_rate": f"{r['win_rate']*100:.0f}%",
        "rounds_won": r["rounds_won"], "rounds_played": r["rounds_played"],
    } for r in rows]
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"{board.get('matches_recorded', 0)} matches recorded total.")
