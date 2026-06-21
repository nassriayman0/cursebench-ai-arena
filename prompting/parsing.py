"""prompting/parsing.py — the small-model safety net (04 §3).

call_model_json already strips fences, grabs the first JSON object, validates, and
repairs once. This layer adds the final step: on a second failure (or a provider
being down), substitute a SAFE DEFAULT and log it — never crash a match.
"""

from __future__ import annotations

from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from models.base import CallBudgetExceeded
from models.providers import ProviderUnavailable
from models.structured import StructuredOutputError, call_model_json
from util.logging import CallMeter, get_logger

_log = get_logger("jjk.parsing")
T = TypeVar("T", bound=BaseModel)


def safe_json_call(
    model_id: str,
    system: str,
    user: str,
    schema: Type[T],
    default: T,
    *,
    temperature: float = 0.3,
    call_type: str = "json",
    meter: Optional[CallMeter] = None,
) -> T:
    """Validated structured call that degrades to `default` instead of raising.

    Handles: invalid JSON after repair, provider down (no key/package), and the
    per-match call budget. Returns a well-typed object every time.
    """
    try:
        return call_model_json(
            model_id, system, [{"role": "user", "content": user}], schema,
            temperature=temperature, call_type=call_type, meter=meter,
        )
    except StructuredOutputError as exc:
        _log.warning("%s: invalid JSON after repair -> safe default (%s)", call_type, exc)
    except ProviderUnavailable as exc:
        _log.warning("%s: provider unavailable -> safe default (%s)", call_type, exc)
    except CallBudgetExceeded as exc:
        _log.warning("%s: call budget hit -> safe default (%s)", call_type, exc)
    except Exception as exc:  # noqa: BLE001 - last-resort: a bad call never crashes a match
        _log.warning("%s: unexpected error -> safe default (%s)", call_type, exc)
    return default
