"""views/records.py — per-round transcript: dialogue, strategy, moves, counters, timeline."""

from __future__ import annotations

import streamlit as st

from views import components as C


def render() -> None:
    state = st.session_state.get("state")
    if state is None or not state.records:
        st.info("No rounds recorded yet. Run a round in the **Arena**.")
        return

    nums = [r.round_number for r in state.records]
    sel = st.selectbox("Round", nums, index=len(nums) - 1)
    rec = next(r for r in state.records if r.round_number == sel)

    C.banner(f"Round {rec.round_number} — {rec.phase} Phase"
             + (f"  ·  winner: {rec.round_winner}" if rec.round_winner else ""))
    if getattr(rec, "summary", ""):
        st.markdown(f"**📊 {rec.summary}**")
    if getattr(rec, "narration", ""):
        st.markdown(f"> 🎙️ *{rec.narration}*")

    st.subheader("Each fighter's techniques (full arsenal through this round)")
    # Cumulative arsenal = every technique generated in rounds up to and including `sel`.
    arsenal: dict[str, list] = {name: [] for name in state.fighters}
    new_this_round: set = set()
    for r in state.records:
        if r.round_number > sel:
            break
        for name, tech in r.generated_techniques.items():
            arsenal.setdefault(name, []).append(tech)
            if r.round_number == sel:
                new_this_round.add((name, tech.name))

    fcols = st.columns(len(state.fighters))
    for col, (name, f) in zip(fcols, state.fighters.items()):
        with col:
            st.markdown(f"**{name}** {C.kind_badge(f.model_id)}", unsafe_allow_html=True)
            techs = arsenal.get(name, [])
            if not techs:
                st.caption("none yet")
            for t in techs:
                C.technique_details(t, new=((name, t.name) in new_this_round))

    if rec.private_messages:
        with st.expander(f"🤝 Negotiation ({len(rec.private_messages)} messages)"):
            for m in rec.private_messages:
                st.markdown(f"**{m.get('from')} → {m.get('to')}**: {m.get('content', '')}"
                            + (f"  \n_hidden intent: {m.get('true_intent')}_"
                               if m.get('true_intent') else ""))

    st.subheader("Moves & strategy")
    for m in rec.moves:
        head = f"**{m.actor}** · `{m.action}`" + (f" → {m.target}" if m.target else "")
        if m.technique_name:
            head += f" · {m.technique_name}"
        if m.ce_spend:
            head += f" · {m.ce_spend} CE"
        st.markdown(head)
        if getattr(m, "thinking", ""):
            st.markdown(f"<div style='border-left:3px solid #a855f7;background:#1a1430;"
                        f"padding:4px 9px;margin:2px 0;border-radius:6px;font-style:italic;"
                        f"color:#d8b4fe;font-size:0.85rem'>💭 {m.thinking}</div>",
                        unsafe_allow_html=True)
        detail = []
        if m.dialogue:
            detail.append(f"💬 *{m.dialogue}*")
        if m.intent:
            detail.append(f"🧠 {m.intent}")
        if detail:
            st.caption("  ".join(detail))

    if rec.counters:
        with st.expander(f"🛡️ Counters & predictions ({len(rec.counters)})"):
            for c in rec.counters:
                st.write(c)

    st.subheader("Special events")
    C.render_events(rec.special_events)

    analyses = getattr(rec, "analyses", {}) or {}
    if analyses:
        st.subheader("🧠 Strategy debriefs — how each fighter won or lost")
        order = ([rec.round_winner] if rec.round_winner in analyses else []) \
            + [n for n in analyses if n != rec.round_winner]
        for name in order:
            tag = " 🏆 (winner)" if name == rec.round_winner else ""
            st.markdown(f"**{name}{tag}:** {analyses[name]}")

    st.subheader("HP timeline")
    C.hp_timeline_chart(rec)
