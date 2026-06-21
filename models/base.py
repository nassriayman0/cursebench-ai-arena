"""models/base.py — the provider-agnostic entrypoint.

    call_model(model_id, system, messages, temperature, json_mode) -> str

Wraps every provider behind one interface with tenacity retry, token/cost/latency
metering, and an optional per-match call budget. Swapping models requires zero
changes elsewhere (01 §0.5).
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from dotenv import load_dotenv
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

from config import settings
from config.models import get_spec
from models.cache import ResponseCache
from models.providers import (ModelCallError, ProviderUnavailable,
                              provider_chat)
from util.logging import (CallMeter, CallRecord, DEFAULT_METER, estimate_cost,
                          get_logger)

load_dotenv()  # read .env once at import
_log = get_logger("jjk.models")

# Process-wide call counter for the budget guard (MAX_MODEL_CALLS; 0 = unlimited).
_CALL_COUNT = 0
# Optional per-match response cache (installed by the engine/UI for stable replays).
_ACTIVE_CACHE: Optional[ResponseCache] = None
# Guards shared state (counter / meter / cache) when calls run concurrently.
_LOCK = threading.Lock()


def set_active_cache(cache: Optional[ResponseCache]) -> None:
    global _ACTIVE_CACHE
    _ACTIVE_CACHE = cache


class CallBudgetExceeded(RuntimeError):
    """Raised when a match exceeds JJK_MAX_MODEL_CALLS."""


def reset_call_count() -> None:
    global _CALL_COUNT
    _CALL_COUNT = 0


def call_count() -> int:
    return _CALL_COUNT


@retry(
    reraise=True,
    stop=stop_after_attempt(settings.MODEL_MAX_RETRIES),
    wait=wait_exponential(multiplier=settings.MODEL_RETRY_BASE_WAIT, min=1, max=20),
    retry=retry_if_exception_type(ModelCallError),
)
def _call_with_retry(spec, system, messages, temperature, json_mode, max_tokens):
    # ProviderUnavailable is NOT in the retry set → it surfaces immediately.
    return provider_chat(spec, system, messages, temperature, json_mode, max_tokens)


def call_model(
    model_id: str,
    system: str,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    json_mode: bool = False,
    max_tokens: Optional[int] = None,
    call_type: str = "generic",
    meter: Optional[CallMeter] = None,
    use_cache: bool = True,
) -> str:
    """Call any registered model and return its raw text reply.

    `use_cache=False` bypasses the per-match response cache (e.g. for technique
    generation, which must vary by round and never be served stale).

    Raises ProviderUnavailable (missing key/package) or ModelCallError (after
    retries). Never silently returns junk — callers validate/repair downstream.
    """
    global _CALL_COUNT
    spec = get_spec(model_id)
    max_tokens = max_tokens or settings.MODEL_MAX_TOKENS
    meter = meter or DEFAULT_METER
    cache = _ACTIVE_CACHE if use_cache else None
    ckey = (cache.make_key(model_id, system, messages, json_mode, temperature)
            if cache is not None else None)

    # Budget check + cache read under the lock (calls may run concurrently).
    with _LOCK:
        if settings.MAX_MODEL_CALLS and _CALL_COUNT >= settings.MAX_MODEL_CALLS:
            raise CallBudgetExceeded(
                f"Per-match call budget ({settings.MAX_MODEL_CALLS}) reached.")
        if ckey is not None and cache.has(ckey):
            hit = cache.get(ckey) or ""
            _CALL_COUNT += 1
            return hit

    start = time.perf_counter()
    ok = False
    cached = False
    text, usage = "", {"input_tokens": 0, "output_tokens": 0}
    try:
        text, usage = _call_with_retry(spec, system, messages, temperature,
                                       json_mode, max_tokens)
        ok = True
        return text
    finally:
        latency = time.perf_counter() - start
        with _LOCK:
            _CALL_COUNT += 1
            if ckey is not None and ok:
                cache.put(ckey, text)
        cost = estimate_cost(spec.price_in, spec.price_out,
                             usage["input_tokens"], usage["output_tokens"])
        meter.add(CallRecord(
            model_id=model_id, provider=spec.provider, call_type=call_type,
            input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
            cost_usd=cost, latency_s=latency, ok=ok,
        ))
        tag = "HIT" if cached else ("ok " if ok else "ERR")
        _log.info("%s %-18s %-9s %.2fs in=%d out=%d $%.4f%s",
                  tag, model_id, call_type, latency,
                  usage["input_tokens"], usage["output_tokens"], cost,
                  "" if ok else "  <-- failed")
