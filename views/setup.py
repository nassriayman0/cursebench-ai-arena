"""views/setup.py — pre-game: pick 4 models, name characters, set options."""

from __future__ import annotations

import streamlit as st

from config import settings
from config.models import (DEFAULT_SEATS, MODEL_REGISTRY, get_spec, is_available,
                           is_local)
from game.setup import build_agents, build_game_state, unique_name
from models.cache import ResponseCache
from util.logging import CallMeter

_MODEL_IDS = list(MODEL_REGISTRY.keys())


def _label(mid: str) -> str:
    spec = MODEL_REGISTRY[mid]
    kind = "🖥️ local" if is_local(mid) else "☁️ frontier"
    mark = "" if is_available(mid) else "  ⚠ no key/not pulled"
    return f"{spec.display_name} · {kind} [{spec.company}]{mark}"


def render() -> None:
    st.header("⚙️ Setup the Match")
    st.write("Pick four models (local or frontier — mix freely), name your sorcerers, "
             "and set the rules. Seats are model-agnostic, so Claude-vs-locals is fair game.")

    cols = st.columns(4)
    seats, names = [], []
    used: set[str] = set()
    for i, col in enumerate(cols):
        with col:
            default = DEFAULT_SEATS[i] if i < len(DEFAULT_SEATS) else _MODEL_IDS[0]
            idx = _MODEL_IDS.index(default) if default in _MODEL_IDS else 0
            seat = st.selectbox(f"Seat {i + 1}", _MODEL_IDS, index=idx,
                                format_func=_label, key=f"seat_{i}")
            spec = get_spec(seat)
            default_name = unique_name(spec.company, used)
            name = st.text_input(f"Name {i + 1}", value=default_name, key=f"name_{i}")
            seats.append(seat)
            names.append(name)

    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1:
        rounds = st.number_input("Rounds", 1, 20, settings.NUM_ROUNDS)
        seed = st.number_input("Seed", 0, 10_000_000, settings.DEFAULT_SEED)
    with c2:
        enable_negotiation = st.checkbox("Negotiation / alliances", value=True)
        enable_handicaps = st.checkbox("Binding-vow handicaps (round 5+)", value=True)
    with c3:
        enable_reflect = st.checkbox("Reflection + strategy debrief", value=True)
        enable_react = st.checkbox("React / counter layer (slow!)", value=False)
        enable_director = st.checkbox("Director commentary", value=False)

    st.caption("⚠ Local 7-9B models are slow (~15-30s/call) and a full match is many calls. "
               "For a quick run, lower rounds, disable react/reflect, or use Claude Haiku seats.")

    if st.button("⚔️  Start Match", type="primary", use_container_width=True):
        if len(set(names)) != len(names) or any(not n.strip() for n in names):
            st.error("Character names must be unique and non-empty.")
            return
        options = {
            "enable_negotiation": enable_negotiation,
            "enable_handicaps": enable_handicaps,
            "enable_reflect": enable_reflect,
            "enable_react": enable_react,
            "enable_director": enable_director,
            "rounds": int(rounds),
        }
        state = build_game_state(seats, names, seed=int(seed), options=options,
                                 match_id=f"match_seed{int(seed)}")
        meter = CallMeter()
        st.session_state.state = state
        st.session_state.agents = build_agents(state, meter)
        st.session_state.meter = meter
        st.session_state.cache = ResponseCache()
        st.session_state.feed = []
        st.session_state.pending = None
        st.session_state.round_cursor = 1
        st.session_state.rounds = int(rounds)
        st.session_state.page = "Arena"
        st.rerun()
