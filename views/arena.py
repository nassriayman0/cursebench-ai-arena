"""views/arena.py — main battle view: two-step Generate -> read -> Fight, with
animated events, HP/CE bars, this-round techniques, and per-round strategy debriefs."""

from __future__ import annotations

import glob
import os

import streamlit as st

from config import settings
from game import scoring
from game.engine import fight_round, prepare_round, run_round
from game.phases import escalation_banner
from models import base as model_base
from util.persistence import SAVES_DIR, load_match, save_match
from views import components as C


def _cache_on() -> None:
    model_base.set_active_cache(st.session_state.get("cache"))


def _finish_if_done() -> None:
    if st.session_state.round_cursor > st.session_state.rounds:
        scoring.update_leaderboard(st.session_state.state)


def _streamer(live):
    """Return (lines, on_line) where on_line streams the live feed into `live`."""
    lines: list[str] = []

    def on_line(s: str) -> None:
        lines.append(s)
        live.markdown(C.feed_html(lines[-40:]), unsafe_allow_html=True)

    return lines, on_line


def _generate(live) -> None:
    state, agents = st.session_state.state, st.session_state.agents
    cursor = st.session_state.round_cursor
    lines, on_line = _streamer(live)
    _cache_on()
    try:
        with st.spinner(f"Round {cursor}: each sorcerer is manifesting a technique..."):
            record, declared = prepare_round(state, agents, cursor,
                                             meter=st.session_state.meter, on_line=on_line)
    finally:
        model_base.set_active_cache(None)
    st.session_state.pending = {"record": record, "declared": declared}
    st.session_state.feed = lines
    st.rerun()


def _fight(live) -> None:
    state, agents = st.session_state.state, st.session_state.agents
    cursor = st.session_state.round_cursor
    pending = st.session_state.pending
    lines, on_line = _streamer(live)
    _cache_on()
    try:
        with st.spinner(f"Round {cursor}: FIGHT — last sorcerer standing wins..."):
            fight_round(state, agents, cursor, pending["record"], pending["declared"],
                        meter=st.session_state.meter, on_line=on_line)
    finally:
        model_base.set_active_cache(None)
    st.session_state.pending = None
    st.session_state.round_cursor = cursor + 1
    st.session_state.feed = lines
    save_match(state)
    _finish_if_done()
    st.rerun()


def _run_rest(live) -> None:
    state, agents = st.session_state.state, st.session_state.agents
    rounds = st.session_state.rounds
    lines, on_line = _streamer(live)
    _cache_on()
    try:
        if st.session_state.get("pending"):
            p = st.session_state.pending
            with st.spinner(f"Round {st.session_state.round_cursor}: fighting..."):
                fight_round(state, agents, st.session_state.round_cursor,
                            p["record"], p["declared"], meter=st.session_state.meter,
                            on_line=on_line)
            st.session_state.pending = None
            st.session_state.round_cursor += 1
        while st.session_state.round_cursor <= rounds:
            r = st.session_state.round_cursor
            with st.spinner(f"Auto-running round {r}/{rounds}..."):
                run_round(state, agents, r, meter=st.session_state.meter, on_line=on_line)
            st.session_state.round_cursor += 1
    finally:
        model_base.set_active_cache(None)
    st.session_state.feed = lines
    save_match(state)
    _finish_if_done()
    st.rerun()


def _load_panel() -> None:
    files = sorted(glob.glob(os.path.join(SAVES_DIR, "*.json")))
    files = [f for f in files if not f.endswith("leaderboard.json")]
    if not files:
        st.caption("No saved matches yet.")
        return
    choice = st.selectbox("Load a saved match", files,
                          format_func=os.path.basename, key="load_choice")
    if st.button("📂 Load", use_container_width=True):
        from game.setup import build_agents
        state = load_match(choice)
        st.session_state.state = state
        st.session_state.agents = build_agents(state, st.session_state.get("meter"))
        st.session_state.rounds = state.match_options.get("rounds", len(state.records))
        st.session_state.round_cursor = len(state.records) + 1
        st.session_state.pending = None
        st.session_state.feed = []
        st.rerun()


def _techniques_to_read(record) -> None:
    """The 'read before you fight' panel — full info on each fighter's new technique."""
    st.subheader("📜 This round's techniques — read them, then fight")
    cols = st.columns(len(record.generated_techniques))
    for col, (name, tech) in zip(cols, record.generated_techniques.items()):
        with col:
            st.markdown(f"**{name}**")
            C.technique_details(tech, new=True)
    if record.special_events:
        st.caption("Pre-combat:")
        C.render_events(record.special_events)


def render() -> None:
    state = st.session_state.get("state")
    if state is None:
        st.info("No match yet — head to **Setup** to start one.")
        with st.expander("Or load a previous match"):
            _load_panel()
        return

    rounds = st.session_state.get("rounds", settings.NUM_ROUNDS)
    cursor = st.session_state.get("round_cursor", 1)
    pending = st.session_state.get("pending")
    done = cursor > rounds

    if done:
        winner = scoring.match_winner(state)
        if winner:
            C.banner(f"🏆 MATCH OVER — {winner.character_name} ({winner.model_id}) "
                     f"wins with {winner.rounds_won} rounds", kind="win")
    else:
        phase = settings.phase_name(settings.phase_for_round(cursor))
        state_word = "techniques ready — FIGHT" if pending else "ready to generate"
        C.banner(f"Round {cursor} / {rounds} — {phase} Phase  ·  {state_word}", kind="phase")
        st.caption(escalation_banner(cursor))

    # Fighter cards
    cols = st.columns(len(state.fighters))
    for col, f in zip(cols, state.fighters.values()):
        with col:
            C.fighter_card(f)

    # Live inner-thoughts / battle feed (streams during a run, top-level full width).
    live = st.empty()

    # Controls (two-step: Generate -> read -> Fight)
    if not done:
        b1, b2, b3 = st.columns(3)
        if pending:
            with b1:
                if st.button(f"⚔️ FIGHT Round {cursor}", type="primary", use_container_width=True):
                    _fight(live)
        else:
            with b1:
                if st.button(f"🎲 Generate Round {cursor}", type="primary", use_container_width=True):
                    _generate(live)
        with b2:
            if st.button("⏩ Auto-run rest", use_container_width=True):
                _run_rest(live)
        with b3:
            if st.button("💾 Save", use_container_width=True):
                st.success(f"Saved -> {os.path.basename(save_match(state))}")

    if "meter" in st.session_state:
        st.caption(f"Model usage: {st.session_state.meter.summary()}  ·  "
                   f"cache: {len(st.session_state.get('cache') or [])} entries")

    # The "read before you fight" panel
    if pending:
        _techniques_to_read(pending["record"])

    # Last completed round: factual summary, events, debriefs (winner first).
    # getattr() guards against records created by an older code version held in
    # session_state across a hot-reload.
    if state.records:
        rec = state.records[-1]
        if getattr(rec, "summary", ""):
            C.banner(f"📊 {rec.summary}")
        if getattr(rec, "narration", ""):
            st.markdown(f"> 🎙️ *{rec.narration}*")
        st.subheader(f"Round {rec.round_number} events")
        C.render_events(rec.special_events)
        analyses = getattr(rec, "analyses", {}) or {}
        if analyses:
            with st.expander("🧠 Strategy debriefs — how each fighter won or lost", expanded=True):
                order = ([rec.round_winner] if rec.round_winner in analyses else []) \
                    + [n for n in analyses if n != rec.round_winner]
                for name in order:
                    tag = " 🏆 (winner)" if name == rec.round_winner else ""
                    st.markdown(f"**{name}{tag}:** {analyses[name]}")

    if st.session_state.get("feed"):
        with st.expander("📜 Battle feed + inner thoughts (last run)", expanded=False):
            st.markdown(C.feed_html(st.session_state.feed), unsafe_allow_html=True)

    with st.expander("Save / Load"):
        _load_panel()
