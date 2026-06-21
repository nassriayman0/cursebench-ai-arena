"""prompting/templates.py — prompt builders for each LLM decision (04 §2).

Keep context small (04 §GLOBAL.3): only this fighter's card, opponents' visible
stats, this round's techniques, and a short memory note. Every prompt ends by
re-stating the exact JSON shape and forbids prose outside it.
"""

from __future__ import annotations

from config import settings
from game.counters import counter_rows_for
from game.state import Fighter, GameState, Handicap, Technique


def _tech_brief(t: Technique, show_complications: bool) -> str:
    base = f"{t.name} (P{t.power}, {t.theme or 'technique'}"
    flags = []
    if t.is_domain:
        flags.append("domain")
    if t.is_rct:
        flags.append("rct")
    if t.tags:
        flags.append("/".join(t.tags))
    if flags:
        base += ", " + " ".join(flags)
    base += ")"
    if show_complications and t.complications:
        weak = "; ".join(f"{c.name}" + ("*" if c.exploitable else "") for c in t.complications)
        base += f" weaknesses: {weak}"
    return base


def self_card(f: Fighter) -> str:
    techs = "; ".join(_tech_brief(t, True) for t in f.techniques) or "none"
    hcs = ", ".join(h.kind for h in f.handicaps) or "none"
    st = ", ".join(f.status) or "none"
    return (f"{f.character_name} | HP {f.hp}/{f.max_hp} | CE {f.ce}/{f.max_ce} | "
            f"handicaps: {hcs} | status: {st}\n  techniques: {techs}")


def enemy_brief(f: Fighter) -> str:
    # Only reveal complications of techniques the enemy has explained (canon).
    techs = "; ".join(_tech_brief(t, t.revealed) for t in f.techniques) or "unknown"
    st = ", ".join(f.status) or "none"
    return f"{f.character_name} | HP {f.hp}/{f.max_hp} | CE {f.ce}/{f.max_ce} | status: {st} | {techs}"


def battlefield(state: GameState, me: Fighter) -> str:
    return "\n".join(enemy_brief(f) for f in state.living_fighters()
                     if f.character_name != me.character_name) or "no living enemies"


# ---------------------------------------------------------------------------
# 2.2 choose_move (the one Stage A uses every tick) — temp 0.3
# ---------------------------------------------------------------------------
CHOOSE_MOVE_SCHEMA = (
    '{"thinking": "<step-by-step inner strategy, <=500 chars. Name the opponents\' '
    'techniques and their counters, and your what-ifs — e.g. \'he has Infinity so melee is '
    'useless; I amplify, but if he opens his domain I clash instead\'>", '
    '"action": "<one action>", "target": "<enemy name or null>", '
    '"technique_name": "<name or null>", "ce_spend": <integer>, '
    '"intent": "<why, <=200 chars>", "dialogue": "<in-character line, <=240 chars>"}'
)

# Condensed tactical playbook (04 §TACTICAL PLAYBOOK). Pushes models off passivity.
_PLAYBOOK = """TACTICS — do NOT just wait. Turtling is PUNISHED: 2+ waits/reinforces in a row makes you "passive" (+15% damage taken, less CE next round).
- Offense IS survival: landing consecutive CE attacks builds Black Flash, which rebuilds your RCT healing. Focus-fire ONE target; don't spread damage.
- You only regain CE when you ACT (attack/domain/counter); waiting gives you 0. Keep ~20-25% CE for a finisher or emergency heal, never hit 0 in a live fight.
- Exploit the NAMED weakness of an enemy technique: touch-required -> stay ranged; clap/spoken tell -> interrupt the tick they wind up; single-use -> bait it then strike. Name the weakness in your intent.
- When an enemy is in one-hit range, COMMIT your biggest hit instead of chipping.
- Domains: never be the 3rd to open (3+ collapse, all lose). Pop Amplification the tick you predict their big technique. Simple Domain delays ONE sure-hit, it is not a wall.
- Soul attacks beat self-healers (soul damage can't be healed back). Reinforce only helps vs normal hits, never a sure-hit.
- 4-way: gang up on whoever is winning; ally to cover your weakness; betray on the finisher when a round win is in reach."""


def choose_move_prompt(state: GameState, me: Fighter, round_number: int,
                       tick: int, memory: str) -> str:
    phase = settings.phase_name(settings.phase_for_round(round_number))
    latest = me.techniques[-1] if me.techniques else None
    new_tech = _tech_brief(latest, True) if latest else "none"
    enemy_techs = [t for f in state.living_fighters()
                   if f.character_name != me.character_name for t in f.techniques]
    rows = counter_rows_for(enemy_techs)
    counters = ("\nYOUR OPPONENTS' TECHNIQUES AND THEIR CANON COUNTERS — exploit the matrix "
                "(e.g. NEVER melee into Infinity):\n- " + "\n- ".join(rows) + "\n") if rows else ""
    return f"""ROUND {round_number}, TICK {tick}, PHASE: {phase}.
YOU: {self_card(me)}
ENEMIES (alive):
{battlefield(state, me)}
THIS ROUND'S NEW TECHNIQUE: {new_tech}
YOUR MEMORY: {memory or "(none yet)"}
{counters}
Choose ONE action. Allowed actions and required slots:
- "attack": target, technique_name, ce_spend
- "domain_expansion": technique_name, ce_spend   (needs >= {settings.DOMAIN_CE_COST} CE; sure-hit; risky if others open domains too)
- "domain_amplification": ce_spend               (blocks one enemy technique; you cannot use your own technique this tick)
- "simple_domain": ce_spend                      (defensive; buys time vs a sure-hit)
- "heal_rct": ce_spend                           (CE -> HP; illegal if you have no_rct)
- "reinforce": ce_spend                          (reduce incoming non-sure-hit damage this tick)
- "dodge": (free; auto-evades telegraphed/low-accuracy attacks this tick; useless vs a domain sure-hit)
- "explain_technique": technique_name            (REVEAL it as a GAMBLE: it gets STRONGER all round (+power, +accuracy, +15% damage) — but enemies learn its weakness and will counter it. High risk, high reward.)
- "wait": (do nothing — turtling is punished)

Rules: you cannot spend more CE than you have ({me.ce}). First THINK step by step (in "thinking"): what do my opponents run, what counters them, what's my plan and the what-ifs? Then pick the action that best exploits an enemy's complication or sets up your win.

{_PLAYBOOK}

Reply with ONE JSON object, exactly:
{CHOOSE_MOVE_SCHEMA}"""


# ---------------------------------------------------------------------------
# 2.1 negotiate (Stage B) — temp 0.7
# ---------------------------------------------------------------------------
def negotiate_prompt(state: GameState, me: Fighter, round_number: int,
                     memory: str) -> str:
    phase = settings.phase_name(settings.phase_for_round(round_number))
    return f"""ROUND {round_number}, PHASE: {phase}. Before combat you may send private messages to other sorcerers to propose an alliance, a combo, or to set up a betrayal.

VISIBLE BATTLEFIELD:
{battlefield(state, me)}
YOUR MEMORY: {memory or "(none yet)"}

Decide who (if anyone) to message and why (complementary techniques, ganging up on the strongest, or feeding a lie).

Reply with ONE JSON object, exactly:
{{"messages": [{{"to": "<enemy name or 'none'>", "content": "<=200 chars", "true_intent": "<your real plan, <=120 chars>"}}]}}
If you want to stay silent: {{"messages": []}}"""


# ---------------------------------------------------------------------------
# 2.3 react (Stage B) — temp 0.3
# ---------------------------------------------------------------------------
def react_prompt(state: GameState, me: Fighter, attacker_name: str,
                 incoming_summary: str, memory: str) -> str:
    return f"""{attacker_name} just declared: {incoming_summary} targeting you.
YOU: {self_card(me)}
YOUR MEMORY: {memory or "(none yet)"}

Do two things: (1) PREDICT their likely NEXT move, (2) choose your COUNTER now.
Counters: dodge, simple_domain (vs sure-hit), domain_amplification (negate one technique, but you can't use yours), domain_expansion (clash), reinforce, heal_rct, counter_attack, bait, wait.

Reply with ONE JSON object, exactly:
{{"prediction": "<their probable next move, <=140 chars>", "counter_action": "<one of the counters>", "target": "<enemy name or null>", "ce_spend": <integer>, "intent": "<=160 chars", "dialogue": "<=200 chars"}}"""


# ---------------------------------------------------------------------------
# 2.4 on_technique_revealed (Stage B) — temp 0.3
# ---------------------------------------------------------------------------
def on_revealed_prompt(owner_name: str, technique: Technique) -> str:
    comp = "; ".join(f"{c.name}: {c.description}" for c in technique.complications) or "none"
    return f"""{owner_name} revealed their technique: {technique.name} (P{technique.power}). Complications: {comp}
Find the single most exploitable complication and how you would punish it.

Reply with ONE JSON object, exactly:
{{"weak_point": "<the complication to exploit, <=140 chars>", "plan": "<how you'll punish it, <=160 chars>", "threat_level": "<low|medium|high>"}}"""


# ---------------------------------------------------------------------------
# 2.5 reflect (Stage B) — temp 0.5
# ---------------------------------------------------------------------------
def reflect_prompt(round_number: int, survivor: str, events: list[str],
                   me: Fighter, won: bool) -> str:
    ev = "; ".join(events) or "nothing notable"
    outcome = "You WON this round." if won else f"You LOST this round (winner: {survivor})."
    return f"""Round {round_number} is over. {outcome} Key events: {ev}.
YOUR STATE: {self_card(me)}

Two things:
1) analysis: think STEP BY STEP and explain, for the audience, HOW you won or WHY you lost — your strategy, the key moment, and what you'd change. Be concrete and in-character.
2) memory_note: a short PRIVATE note to your future self (who to trust/target, what to save CE for).

Reply with ONE JSON object, exactly:
{{"analysis": "<=400 chars, step-by-step, in-character>", "memory_note": "<=300 chars, private notes>"}}"""


# ---------------------------------------------------------------------------
# binding vow / handicap (Stage B, round 5+) — temp 0.3
# ---------------------------------------------------------------------------
def handicap_prompt(fighter: Fighter, options: list[Handicap], round_number: int) -> str:
    opts = "; ".join(f"{h.kind}: {h.description}" for h in options)
    return f"""ROUND {round_number}. A BINDING VOW is offered to {fighter.character_name}.
Accept ONE restriction now in exchange for a guaranteed +{settings.BINDING_VOW_POWER_BUMP} power on your technique this round. You may also decline and stay flexible.
Options: {opts}
Accept only if the restriction won't cripple your game plan; the power bump compounds across rounds.

Reply with ONE JSON object, exactly:
{{"accept": <true|false>, "choice": "<one option kind or null>", "dialogue": "<=160 chars, in-character>"}}"""
