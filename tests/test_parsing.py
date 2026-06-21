"""Fail-soft tests: bad model output / dead provider -> safe default, never crash.

Covers the Step 6 DoD ("a corrupted model reply falls back to wait without
crashing") without needing a live model.
"""

from pydantic import BaseModel

from config import settings
from game.state import Fighter
from interfaces.agent import MoveResponse, SorcererAgent
from models.providers import ProviderUnavailable
from models.structured import StructuredOutputError
from prompting.parsing import safe_json_call


class Foo(BaseModel):
    x: int = 0


def test_safe_json_call_default_on_structured_error(monkeypatch):
    def boom(*a, **k):
        raise StructuredOutputError("invalid twice", raw="{")
    monkeypatch.setattr("prompting.parsing.call_model_json", boom)
    default = Foo(x=42)
    assert safe_json_call("qwen2.5:7b", "sys", "user", Foo, default) is default


def test_safe_json_call_default_on_provider_unavailable(monkeypatch):
    def boom(*a, **k):
        raise ProviderUnavailable("no key")
    monkeypatch.setattr("prompting.parsing.call_model_json", boom)
    default = Foo(x=7)
    assert safe_json_call("claude-opus-4-8", "s", "u", Foo, default) is default


def test_agent_coerces_junk_action_to_wait():
    f = Fighter(company="T", model_id="qwen2.5:7b", character_name="A", ce=50)
    agent = SorcererAgent("A", "qwen2.5:7b")
    move = agent._to_move(f, MoveResponse(
        action="frobnicate", ce_spend=9999, intent="x" * 999, dialogue="d" * 999))
    assert move.action == "wait"
    assert move.ce_spend == 50  # clamped to available CE
    assert len(move.intent) <= settings.INTENT_MAX_CHARS
    assert len(move.dialogue) <= settings.DIALOGUE_MAX_CHARS
