"""app.py — Streamlit entrypoint + page router for JJK AI Arena.

The engine runs in plain Python; Streamlit only renders state and triggers steps.
The live GameState + agents live in st.session_state across reruns.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from views import arena, components, leaderboard, records, setup

st.set_page_config(page_title="JJK AI Arena", page_icon="⚔️", layout="wide")
components.inject_theme()

PAGES = {
    "Setup": setup,
    "Arena": arena,
    "Records": records,
    "Leaderboard": leaderboard,
}

# Session defaults
st.session_state.setdefault("page", "Setup")

with st.sidebar:
    st.title("⚔️ JJK AI Arena")
    st.caption("Four AI models embody cursed sorcerers and fight a 10-round tournament. "
               "The models do the strategy; a deterministic engine referees.")
    page_names = list(PAGES)
    current = st.session_state.get("page", "Setup")
    idx = page_names.index(current) if current in page_names else 0
    chosen = st.radio("Navigate", page_names, index=idx)
    st.session_state.page = chosen

    state = st.session_state.get("state")
    if state is not None:
        st.divider()
        st.caption(f"Match seed {state.rng_seed} · "
                   f"round {st.session_state.get('round_cursor', 1)}"
                   f"/{st.session_state.get('rounds', '?')}")

PAGES[st.session_state.page].render()
