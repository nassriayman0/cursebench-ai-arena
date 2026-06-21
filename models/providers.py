"""models/providers.py — per-provider adapters behind one uniform call.

Each adapter takes (spec, system, messages, temperature, json_mode, max_tokens)
and returns (text: str, usage: {"input_tokens": int, "output_tokens": int}).

Error model:
  ProviderUnavailable — missing key/package; FATAL, never retried.
  ModelCallError      — the API call failed; RETRYABLE (base.py retries).

This module imports no game code and does not import models.base (so base can
import it without a cycle).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from config.models import ModelSpec
from config import settings


class ProviderUnavailable(RuntimeError):
    """A provider can't be used (missing API key or SDK package). Not retryable."""


class ModelCallError(RuntimeError):
    """A provider call failed (network/5xx/parse). Retryable by base.py."""


# ---------------------------------------------------------------------------
# Key handling
# ---------------------------------------------------------------------------
def _require_key(spec: ModelSpec) -> str:
    if spec.needs_key is None:
        return os.getenv("OLLAMA_API_KEY", "ollama")  # any non-empty string
    key = os.getenv(spec.needs_key)
    if not key:
        raise ProviderUnavailable(
            f"{spec.provider} model '{spec.model_id}' needs {spec.needs_key} in .env"
        )
    return key


# ---------------------------------------------------------------------------
# OpenAI-compatible providers: ollama, openai, xai
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8)
def _openai_client(base_url: str, api_key: str):
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - openai is a core dep
        raise ProviderUnavailable("The 'openai' package is not installed.") from exc
    return OpenAI(base_url=base_url, api_key=api_key, timeout=settings.MODEL_TIMEOUT_S)


_BASE_URL_ENV = {
    "ollama": ("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    "openai": ("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "xai": ("XAI_BASE_URL", "https://api.x.ai/v1"),
    "deepseek": ("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
}

# OpenAI "reasoning" families (GPT-5, o-series) reject `max_tokens` and a custom
# `temperature`: they need `max_completion_tokens` and only the default temperature.
_OPENAI_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_openai_reasoning(spec: ModelSpec) -> bool:
    return spec.provider == "openai" and spec.api_model_name.startswith(_OPENAI_REASONING_PREFIXES)


def _openai_compatible_chat(spec: ModelSpec, system: str, messages: list[dict],
                            temperature: float, json_mode: bool,
                            max_tokens: int) -> tuple[str, dict]:
    env_name, default_url = _BASE_URL_ENV[spec.provider]
    base_url = os.getenv(env_name, default_url)
    api_key = _require_key(spec)
    client = _openai_client(base_url, api_key)

    full_messages: list[dict] = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    # Reasoning models (GPT-5/o-series, DeepSeek-R1) spend tokens THINKING before the
    # answer, so a small max_tokens truncates before the JSON ever appears. Give headroom
    # and omit temperature (they reject or ignore it).
    name_l = spec.api_model_name.lower()
    is_reasoner = "reasoner" in name_l or name_l.startswith(("o1", "o3", "o4"))
    reasoning = _is_openai_reasoning(spec) or is_reasoner

    kwargs: dict[str, Any] = {"model": spec.api_model_name, "messages": full_messages}
    if _is_openai_reasoning(spec):
        kwargs["max_completion_tokens"] = max(max_tokens, 4096)
    elif is_reasoner:                       # e.g. deepseek-reasoner — needs lots of room
        kwargs["max_tokens"] = max(max_tokens, 8192)
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature
    if json_mode:
        # Ollama maps this to its native format=json; OpenAI/xAI honor it directly.
        kwargs["response_format"] = {"type": "json_object"}

    try:
        resp = client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        usage = {
            "input_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "completion_tokens", 0) or 0,
        }
        return text, usage
    except ProviderUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize to a retryable error
        raise ModelCallError(f"{spec.provider} call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Anthropic / Claude (functional)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _anthropic_client(api_key: str):
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderUnavailable(
            "The 'anthropic' package is not installed (pip install anthropic)."
        ) from exc
    return anthropic.Anthropic(api_key=api_key, timeout=settings.MODEL_TIMEOUT_S)


# A single forced tool is the most reliable way to get strict JSON out of Claude.
_EMIT_TOOL = {
    "name": "emit_json",
    "description": "Return your answer as a single JSON object exactly matching the "
                   "shape requested in the prompt. Put nothing outside the JSON.",
    "input_schema": {"type": "object"},
}


def _anthropic_chat(spec: ModelSpec, system: str, messages: list[dict],
                    temperature: float, json_mode: bool,
                    max_tokens: int) -> tuple[str, dict]:
    api_key = _require_key(spec)
    client = _anthropic_client(api_key)

    # NOTE: temperature is intentionally NOT sent — Opus 4.8 rejects sampling
    # params. We also omit `thinking` (defaults off → faster turns).
    kwargs: dict[str, Any] = {
        "model": spec.api_model_name,
        "max_tokens": max_tokens,            # required by the Messages API
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if json_mode:
        kwargs["tools"] = [_EMIT_TOOL]
        kwargs["tool_choice"] = {"type": "tool", "name": "emit_json"}

    try:
        resp = client.messages.create(**kwargs)
        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(resp.usage, "output_tokens", 0) or 0,
        }
        if json_mode:
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    return json.dumps(block.input), usage
            # Fall through: model answered in text instead of the tool.
        text = "".join(getattr(b, "text", "") for b in resp.content
                       if getattr(b, "type", None) == "text")
        return text, usage
    except ProviderUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ModelCallError(f"anthropic call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Google / Gemini (scaffold)
# ---------------------------------------------------------------------------
def _google_chat(spec: ModelSpec, system: str, messages: list[dict],
                 temperature: float, json_mode: bool,
                 max_tokens: int) -> tuple[str, dict]:
    api_key = _require_key(spec)
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise ProviderUnavailable(
            "google-generativeai not installed (pip install google-generativeai)."
        ) from exc

    genai.configure(api_key=api_key)
    gen_config: dict[str, Any] = {"temperature": temperature,
                                  "max_output_tokens": max_tokens}
    if json_mode:
        gen_config["response_mime_type"] = "application/json"

    # Flatten our messages to a single prompt string (sufficient for our one-shot calls).
    prompt = "\n\n".join(m.get("content", "") if isinstance(m.get("content"), str)
                         else str(m.get("content")) for m in messages)
    try:
        model = genai.GenerativeModel(spec.api_model_name,
                                      system_instruction=system or None)
        resp = model.generate_content(prompt, generation_config=gen_config)
        meta = getattr(resp, "usage_metadata", None)
        usage = {
            "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
            "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
        }
        return (resp.text or ""), usage
    except ProviderUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ModelCallError(f"google call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
PROVIDER_DISPATCH = {
    "ollama": _openai_compatible_chat,
    "openai": _openai_compatible_chat,
    "xai": _openai_compatible_chat,
    "deepseek": _openai_compatible_chat,   # OpenAI-compatible endpoint
    "anthropic": _anthropic_chat,
    "google": _google_chat,
}


def provider_chat(spec: ModelSpec, system: str, messages: list[dict],
                  temperature: float, json_mode: bool,
                  max_tokens: int) -> tuple[str, dict]:
    fn = PROVIDER_DISPATCH.get(spec.provider)
    if fn is None:
        raise ProviderUnavailable(f"No adapter for provider '{spec.provider}'.")
    return fn(spec, system, messages, temperature, json_mode, max_tokens)
