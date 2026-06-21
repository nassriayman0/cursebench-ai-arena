"""models/structured.py — forced + validated JSON output.

    call_model_json(model_id, system, messages, schema) -> validated pydantic model

Small local models break JSON constantly, so this is the single highest-ROI
layer (00): force json-mode, extract the first JSON object, validate against a
pydantic schema, and repair ONCE before giving up. Callers (the agent) wrap this
to substitute a safe default rather than crash a match (12 §guardrails).
"""

from __future__ import annotations

import json
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from config import settings
from models.base import call_model
from util.logging import CallMeter

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """JSON could not be parsed/validated even after one repair attempt."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


def extract_first_json(text: str) -> Optional[str]:
    """Return the first balanced {...} object in `text`, or None.

    Strips ```json / ``` fences and any prose before/after. Brace matching
    ignores braces inside double-quoted strings (with escapes).
    """
    if not text:
        return None
    s = text.strip()
    # Drop code fences if the whole thing is fenced.
    if s.startswith("```"):
        s = s.split("```", 2)
        s = s[1] if len(s) > 1 else text
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _parse(text: str) -> dict:
    block = extract_first_json(text)
    if block is None:
        raise ValueError("no JSON object found in reply")
    return json.loads(block)


def call_model_json(
    model_id: str,
    system: str,
    messages: list[dict],
    schema: Type[T],
    *,
    temperature: float = 0.3,
    call_type: str = "json",
    max_tokens: Optional[int] = None,
    meter: Optional[CallMeter] = None,
    use_cache: bool = True,
) -> T:
    """Call a model and return a validated instance of `schema`.

    One repair retry on parse/validation failure, then StructuredOutputError.
    `use_cache=False` bypasses the per-match response cache.
    """
    raw = call_model(model_id, system, messages, temperature=temperature,
                     json_mode=True, max_tokens=max_tokens, call_type=call_type,
                     meter=meter, use_cache=use_cache)
    try:
        return schema.model_validate(_parse(raw))
    except (ValueError, ValidationError, json.JSONDecodeError) as first_err:
        expected = ", ".join(schema.model_fields.keys())
        repair = (f'Your last reply was invalid ({first_err}). '
                  f'Reply with ONLY one JSON object, no prose, no code fences, '
                  f'with exactly these keys: {{{expected}}}.')
        repaired_messages = messages + [
            {"role": "assistant", "content": raw[:settings.MODEL_MAX_TOKENS]},
            {"role": "user", "content": repair},
        ]
        # Anthropic rejects a trailing assistant turn; the repair user turn after
        # it keeps the sequence valid (…, assistant, user).
        raw2 = call_model(model_id, system, repaired_messages,
                          temperature=temperature, json_mode=True,
                          max_tokens=max_tokens, call_type=call_type + ":repair",
                          meter=meter, use_cache=use_cache)
        try:
            return schema.model_validate(_parse(raw2))
        except (ValueError, ValidationError, json.JSONDecodeError) as second_err:
            raise StructuredOutputError(
                f"{model_id} returned invalid JSON twice: {second_err}", raw=raw2
            ) from second_err
