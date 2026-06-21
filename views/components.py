"""views/components.py — shared Streamlit rendering helpers (bars, cards, events)."""

from __future__ import annotations

import streamlit as st

from config.models import is_local
from game.combat import net_power
from game.state import Fighter, RoundRecord, Technique

# JJK-flavored per-company accent colors.
COMPANY_COLORS = {
    "Anthropic": "#d97757", "OpenAI": "#10a37f", "Google": "#4285f4",
    "xAI": "#888888", "Meta": "#0668e1", "Qwen": "#a855f7", "Mistral": "#ff7000",
    "DeepSeek": "#4d6bfe",
}

EVENT_EMOJI = {
    "BLACK FLASH": "⚡", "DOMAIN EXPANSION": "🌀", "DOMAIN CLASH": "💥",
    "DOMAIN CLASH COLLAPSE": "🌋", "SURE-HIT LANDED": "🎯", "SOUL STRIKE": "👻",
    "BETRAYAL": "🗡️", "ALLIANCE FORMED": "🤝", "BINDING VOW STRUCK": "⛓️",
    "HANDICAP ACCEPTED": "⚖️", "KO": "💀", "LAST ONE STANDING": "🏆",
    "AMPLIFICATION NEGATE": "🛡️", "CURSED STORM": "⛈️", "SURE-HIT": "🎯",
    "TECHNIQUE REVEALED": "🎭", "EVADED": "💨", "GRAZED": "➰", "POSITION SWAP": "🔀",
    "FLOW STATE": "🔥", "RCT CIRCUIT RESTORED": "♻️",
}

# (css class, accent color) per event for the animated banners.
EVENT_STYLE = {
    "BLACK FLASH": ("jjk-flash", "#fde047"),
    "DOMAIN EXPANSION": ("jjk-domain", "#a855f7"),
    "DOMAIN CLASH": ("jjk-domain", "#c084fc"),
    "DOMAIN CLASH COLLAPSE": ("jjk-collapse", "#f97316"),
    "BETRAYAL": ("jjk-shake", "#ef4444"),
    "ALLIANCE FORMED": ("jjk-soft", "#22c55e"),
    "BINDING VOW STRUCK": ("jjk-soft", "#eab308"),
    "HANDICAP ACCEPTED": ("jjk-soft", "#eab308"),
    "CURSED STORM": ("jjk-storm", "#60a5fa"),
    "SOUL STRIKE": ("jjk-soft", "#d946ef"),
    "SURE-HIT LANDED": ("jjk-soft", "#f59e0b"),
    "KO": ("jjk-shake", "#9ca3af"),
    "LAST ONE STANDING": ("jjk-win", "#22c55e"),
    "TECHNIQUE REVEALED": ("jjk-domain", "#eab308"),
    "FLOW STATE": ("jjk-flash", "#fb923c"),
    "RCT CIRCUIT RESTORED": ("jjk-soft", "#34d399"),
    "EVADED": ("jjk-soft", "#60a5fa"),
    "GRAZED": ("jjk-soft", "#9ca3af"),
    "POSITION SWAP": ("jjk-soft", "#22d3ee"),
}

_THEME_CSS = """
<style>
.stApp { background:
  radial-gradient(1200px 600px at 80% -10%, #1b1038 0%, rgba(10,10,20,0) 60%),
  radial-gradient(900px 500px at -10% 110%, #2a0e2e 0%, rgba(10,10,20,0) 55%), #0a0a14; }
h1, h2, h3 { letter-spacing: .3px; }
h1 { text-shadow: 0 0 18px #a855f766; }
/* event banners */
.jjk-event { border-left: 4px solid var(--accent, #a855f7); background: #15152a;
  padding: 6px 12px; margin: 5px 0; border-radius: 8px; animation: jjkIn .35s ease; }
.jjk-event b { color: var(--accent, #c4b5fd); }
.jjk-detail { color: #9ca3af; font-size: .85rem; }
@keyframes jjkIn { from{opacity:0; transform:translateX(-10px)} to{opacity:1; transform:none} }
@keyframes jjkPulse { 0%,100%{box-shadow:0 0 8px var(--accent)} 50%{box-shadow:0 0 24px var(--accent)} }
@keyframes jjkFlashBg { 0%{} 12%{background:#fff;color:#000} 30%{background:#15152a} 100%{} }
@keyframes jjkShake { 0%,100%{transform:none} 20%{transform:translateX(-5px)} 60%{transform:translateX(5px)} }
.jjk-flash { box-shadow:0 0 16px #fde04799; animation: jjkIn .35s ease, jjkFlashBg .7s ease 1; }
.jjk-domain { box-shadow:0 0 18px var(--accent); animation: jjkIn .35s ease, jjkPulse 1.6s ease-in-out 2; }
.jjk-collapse { box-shadow:0 0 20px var(--accent); animation: jjkIn .35s ease, jjkShake .5s ease 2; }
.jjk-shake { animation: jjkIn .35s ease, jjkShake .5s ease 1; }
.jjk-storm { box-shadow:0 0 16px var(--accent); }
.jjk-soft { box-shadow:0 0 12px var(--accent); }
.jjk-win { box-shadow:0 0 22px var(--accent); font-weight:700; animation: jjkIn .35s ease, jjkPulse 1.8s ease-in-out 3; }
.jjk-tech { border:1px solid #2a2a44; border-radius:8px; padding:8px 10px; margin:6px 0;
  background:#12121f; box-shadow: inset 0 0 18px #a855f71a; }
</style>
"""


def inject_theme() -> None:
    """One-time CSS injection: cursed-energy background + animated event styles."""
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def feed_html(lines: list[str]) -> str:
    """Render engine on_line output as a styled live feed (inner thoughts highlighted)."""
    out = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if s.startswith("💭"):  # inner monologue / strategy
            out.append(f"<div style='border-left:3px solid #a855f7;background:#1a1430;"
                       f"padding:5px 9px;margin:3px 0;border-radius:6px;font-style:italic;"
                       f"color:#d8b4fe;font-size:0.86rem'>{s}</div>")
        elif s.startswith("🎭"):  # technique reveal
            out.append(f"<div style='border-left:3px solid #eab308;background:#2a230a;"
                       f"padding:5px 9px;margin:3px 0;border-radius:6px;color:#fde68a'>{s}</div>")
        elif s.startswith("==="):
            out.append(f"<div style='font-weight:700;margin:8px 0 2px;color:#c4b5fd'>{s}</div>")
        elif s.startswith("-- tick"):
            out.append(f"<div style='color:#6b7280;border-top:1px solid #2a2a44;"
                       f"margin:7px 0 2px;font-size:0.8rem'>{s}</div>")
        elif s.startswith("***"):
            out.append(f"<div style='font-weight:700;color:#22c55e;margin:4px 0'>{s}</div>")
        elif s.startswith("📊"):
            out.append(f"<div style='font-weight:600;color:#93c5fd'>{s}</div>")
        else:
            out.append(f"<div style='color:#cbd5e1;font-size:0.86rem'>{s}</div>")
    return ("<div style='max-height:420px;overflow-y:auto;padding:6px 8px;background:#0e0e1a;"
            "border:1px solid #2a2a44;border-radius:10px'>" + "".join(out) + "</div>")


def event_banner(e) -> str:
    cls, color = EVENT_STYLE.get(e.type, ("jjk-event", "#a855f7"))
    emoji = EVENT_EMOJI.get(e.type, "•")
    who = ", ".join(e.actors)
    detail = f"<span class='jjk-detail'>— {e.detail}</span>" if e.detail else ""
    return (f"<div class='jjk-event {cls}' style='--accent:{color}'>"
            f"{emoji} <b>{e.type}</b> {who} {detail}</div>")


def _bar(label: str, cur: int, mx: int, color: str) -> str:
    pct = 0 if mx <= 0 else max(0.0, min(1.0, cur / mx))
    return (
        f'<div style="margin:3px 0">'
        f'<div style="font-size:0.72rem;color:#bbb">{label} {cur}/{mx}</div>'
        f'<div style="background:#2b2b2b;border-radius:4px;height:9px;width:100%">'
        f'<div style="background:{color};width:{pct*100:.0f}%;height:9px;border-radius:4px"></div>'
        f'</div></div>'
    )


def kind_badge(model_id: str) -> str:
    """A colored 🖥️ LOCAL / ☁️ FRONTIER pill for a model."""
    if is_local(model_id):
        return ("<span style='background:#374151;color:#d1d5db;border-radius:6px;"
                "padding:1px 6px;font-size:0.68rem'>🖥️ LOCAL</span>")
    return ("<span style='background:#7c2d12;color:#fed7aa;border-radius:6px;"
            "padding:1px 6px;font-size:0.68rem'>☁️ FRONTIER</span>")


def technique_details(tech: Technique, *, new: bool = False) -> None:
    """Render one technique with FULL info: power, net power, flags, complications."""
    flags = (["domain"] if tech.is_domain else []) + (["rct"] if tech.is_rct else [])
    flags += (["revealed"] if tech.revealed else []) + list(tech.tags)
    flagstr = (" · " + " ".join(flags)) if flags else ""
    head = (f"{'🆕 ' if new else ''}**{tech.name}** — P{tech.power} "
            f"(net {net_power(tech):.1f}){flagstr}")
    st.markdown(head)
    if tech.description:
        st.caption(tech.description)
    for c in tech.complications:
        mark = " ⚠️ exploitable" if c.exploitable else ""
        st.caption(f"• {c.name} (cost {c.cost}){mark} — {c.description}")


def fighter_card(f: Fighter) -> None:
    color = COMPANY_COLORS.get(f.company, "#888")
    dead = (not f.alive_this_round) or f.hp <= 0
    title = f"{'💀 ' if dead else ''}{f.character_name}"
    st.markdown(f"**{title}**  \n{kind_badge(f.model_id)} "
                f"<span style='color:{color};font-size:0.78rem'>{f.company} · {f.model_id}</span>",
                unsafe_allow_html=True)
    st.markdown(_bar("HP", f.hp, f.max_hp, "#e23b3b"), unsafe_allow_html=True)
    st.markdown(_bar("CE", f.ce, f.max_ce, "#3b82e2"), unsafe_allow_html=True)
    chips = [f"🏆 {f.rounds_won}"]
    chips += [f"⚖️{h.kind}" for h in f.handicaps]
    chips += list(f.status)
    if f.soul_damage:
        chips.append(f"soul-{f.soul_damage}")
    st.caption(" · ".join(chips))
    with st.expander(f"Arsenal ({len(f.techniques)})"):
        if not f.techniques:
            st.caption("none yet")
        for i, t in enumerate(f.techniques):
            technique_details(t, new=(i == len(f.techniques) - 1))


def render_events(events) -> None:
    if not events:
        st.caption("No special events.")
        return
    st.markdown("".join(event_banner(e) for e in events), unsafe_allow_html=True)


def banner(text: str, kind: str = "info") -> None:
    colors = {"info": "#1f2937", "win": "#14532d", "phase": "#3b0764"}
    bg = colors.get(kind, "#1f2937")
    st.markdown(
        f"<div style='background:{bg};padding:8px 14px;border-radius:8px;"
        f"margin:4px 0;font-weight:600'>{text}</div>", unsafe_allow_html=True)


def hp_timeline_chart(record: RoundRecord) -> None:
    if not record.hp_ce_timeline:
        return
    names = list(record.hp_ce_timeline[-1].get("hp", {}).keys())
    series = {n: [snap.get("hp", {}).get(n, 0) for snap in record.hp_ce_timeline]
              for n in names}
    st.line_chart(series, height=220)
