"""interfaces/agent.py — SorcererAgent: one model + memory + 5 decision calls.

Exposes the contracts from 04 §2 / 08:
    negotiate / choose_move / react / on_technique_revealed / reflect
choose_move matches the engine's Policy interface, so a SorcererAgent is a
drop-in replacement for StubPolicy. Every call is structured + repaired + safely
defaulted (a corrupted reply falls back to `wait`, never crashing the match).
"""

from __future__ import annotations

from typing import Optional, get_args

from pydantic import BaseModel, Field

from config import settings
from game.state import ActionType, Fighter, GameState, Handicap, Move, Technique
from prompting import templates
from prompting.parsing import safe_json_call
from prompting.personas import build_persona
from util.logging import CallMeter, get_logger

_log = get_logger("jjk.agent")
ALLOWED_ACTIONS = set(get_args(ActionType))


# --- Lenient response schemas (coerced to validated game objects) ---
class MoveResponse(BaseModel):
    thinking: str = ""     # step-by-step inner monologue (what-ifs, counters)
    action: str = "wait"
    target: Optional[str] = None
    technique_name: Optional[str] = None
    ce_spend: int = 0
    intent: str = ""
    dialogue: str = ""


class NegotiateResponse(BaseModel):
    messages: list[dict] = Field(default_factory=list)


class ReactResponse(BaseModel):
    prediction: str = ""
    counter_action: str = "wait"
    target: Optional[str] = None
    ce_spend: int = 0
    intent: str = ""
    dialogue: str = ""


class RevealedResponse(BaseModel):
    weak_point: str = ""
    plan: str = ""
    threat_level: str = "medium"


class ReflectResponse(BaseModel):
    analysis: str = ""
    memory_note: str = ""


class HandicapResponse(BaseModel):
    accept: bool = False
    choice: Optional[str] = None
    dialogue: str = ""


class SorcererAgent:
    def __init__(self, character_name: str, model_id: str,
                 meter: Optional[CallMeter] = None) -> None:
        self.name = character_name
        self.model_id = model_id
        self.meter = meter
        self.memory: str = ""

    # ---- 2.2 choose_move (engine Policy interface) ----
    def choose_move(self, state: GameState, fighter: Fighter,
                    round_number: int, tick: int) -> Move:
        system = build_persona(fighter)
        user = templates.choose_move_prompt(state, fighter, round_number, tick, self.memory)
        default = MoveResponse(action="wait", intent="hesitate", dialogue="...")
        resp = safe_json_call(self.model_id, system, user, MoveResponse, default,
                              temperature=settings.TEMP_DISCIPLINED,
                              call_type="choose_move", meter=self.meter)
        return self._to_move(fighter, resp)

    def _to_move(self, fighter: Fighter, resp: MoveResponse) -> Move:
        action = resp.action if resp.action in ALLOWED_ACTIONS else "wait"
        ce = max(0, min(int(resp.ce_spend or 0), fighter.ce))
        return Move(
            actor=fighter.character_name,
            action=action,  # type: ignore[arg-type]
            target=resp.target or None,
            technique_name=resp.technique_name or None,
            ce_spend=ce,
            intent=(resp.intent or "")[:settings.INTENT_MAX_CHARS],
            dialogue=(resp.dialogue or "")[:settings.DIALOGUE_MAX_CHARS],
            thinking=(resp.thinking or "")[:settings.THINKING_MAX_CHARS],
        )

    # ---- 2.1 negotiate (Stage B) ----
    def negotiate(self, state: GameState, fighter: Fighter,
                  round_number: int) -> list[dict]:
        system = build_persona(fighter)
        user = templates.negotiate_prompt(state, fighter, round_number, self.memory)
        default = NegotiateResponse(messages=[])
        resp = safe_json_call(self.model_id, system, user, NegotiateResponse, default,
                              temperature=settings.TEMP_CREATIVE,
                              call_type="negotiate", meter=self.meter)
        return resp.messages

    # ---- 2.3 react (Stage B) ----
    def react(self, state: GameState, fighter: Fighter, attacker_name: str,
              incoming_summary: str) -> ReactResponse:
        system = build_persona(fighter)
        user = templates.react_prompt(state, fighter, attacker_name,
                                      incoming_summary, self.memory)
        default = ReactResponse(counter_action="reinforce", intent="brace")
        return safe_json_call(self.model_id, system, user, ReactResponse, default,
                              temperature=settings.TEMP_DISCIPLINED,
                              call_type="react", meter=self.meter)

    # ---- 2.4 on_technique_revealed (Stage B) ----
    def on_technique_revealed(self, fighter: Fighter, owner_name: str,
                              technique: Technique) -> RevealedResponse:
        system = build_persona(fighter)
        user = templates.on_revealed_prompt(owner_name, technique)
        default = RevealedResponse(weak_point="unknown", plan="probe it",
                                   threat_level="medium")
        return safe_json_call(self.model_id, system, user, RevealedResponse, default,
                              temperature=settings.TEMP_DISCIPLINED,
                              call_type="on_revealed", meter=self.meter)

    # ---- binding vow / handicap (Stage B, round 5+) ----
    def decide_handicap(self, fighter: Fighter, options: list[Handicap],
                        round_number: int) -> HandicapResponse:
        system = build_persona(fighter)
        user = templates.handicap_prompt(fighter, options, round_number)
        default = HandicapResponse(accept=False)
        return safe_json_call(self.model_id, system, user, HandicapResponse, default,
                              temperature=settings.TEMP_DISCIPLINED,
                              call_type="handicap", meter=self.meter)

    # ---- 2.5 reflect (Stage B) — updates memory, returns the public debrief ----
    def reflect(self, fighter: Fighter, round_number: int, survivor: str,
                events: list[str]) -> str:
        won = survivor == fighter.character_name
        system = build_persona(fighter)
        user = templates.reflect_prompt(round_number, survivor, events, fighter, won)
        default = ReflectResponse(memory_note=self.memory)
        resp = safe_json_call(self.model_id, system, user, ReflectResponse, default,
                              temperature=settings.TEMP_REFLECT,
                              call_type="reflect", meter=self.meter)
        if resp.memory_note:
            self.memory = resp.memory_note[:settings.MEMORY_MAX_CHARS]
        return resp.analysis.strip()  # public step-by-step debrief for the UI
