"""config/models.py — the model registry.

ONE editable place for every selectable model. Model names change over time —
edit them here and nowhere else. Seats are model-agnostic: any entry here can be
assigned to any of the four fighter seats at setup (local or frontier, mixed freely).

Providers:
  - ollama    : local, free, key-free (OpenAI-compatible endpoint)
  - anthropic : Claude — FUNCTIONAL (needs ANTHROPIC_API_KEY)
  - openai    : scaffold (needs OPENAI_API_KEY)   — reuses the OpenAI SDK
  - xai       : scaffold (needs XAI_API_KEY)       — reuses the OpenAI SDK
  - google    : scaffold (needs GOOGLE_API_KEY + google-generativeai installed)

A model is "available" iff its provider needs no key (ollama) or its key env var
is present. The setup UI / smoke test hide unavailable entries.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str          # stable registry key (also what seats reference)
    provider: str          # ollama | anthropic | openai | xai | google
    api_model_name: str    # the string the provider's API expects
    display_name: str
    company: str           # flavor/voice tag (drives persona voice), NOT a seat lock
    cost_tier: str         # free | low | medium | high
    needs_key: str | None  # env var that must be set, or None for key-free (ollama)
    price_in: float = 0.0  # USD per 1M input tokens (0 for local)
    price_out: float = 0.0  # USD per 1M output tokens (0 for local)


# --- The registry -----------------------------------------------------------
# NOTE: frontier model names change frequently. Update the api_model_name column
# as providers release new tiers; nothing else in the codebase hardcodes them.
MODEL_REGISTRY: dict[str, ModelSpec] = {
    # ---- Ollama (local, free, default lineup: 7-9B "sweet spot") ----
    "qwen2.5:7b": ModelSpec("qwen2.5:7b", "ollama", "qwen2.5:7b",
                            "Qwen2.5 7B", "Qwen", "free", None),
    "gemma2:9b": ModelSpec("gemma2:9b", "ollama", "gemma2:9b",
                           "Gemma2 9B", "Google", "free", None),
    "llama3.1:8b": ModelSpec("llama3.1:8b", "ollama", "llama3.1:8b",
                             "Llama 3.1 8B", "Meta", "free", None),
    "mistral:7b": ModelSpec("mistral:7b", "ollama", "mistral:7b",
                            "Mistral 7B", "Mistral", "free", None),
    # handy sharper local picks (pull only if your hardware allows)
    "qwen2.5:14b": ModelSpec("qwen2.5:14b", "ollama", "qwen2.5:14b",
                             "Qwen2.5 14B", "Qwen", "free", None),
    "qwen2.5:3b": ModelSpec("qwen2.5:3b", "ollama", "qwen2.5:3b",
                            "Qwen2.5 3B", "Qwen", "free", None),
    "llama3.2:3b": ModelSpec("llama3.2:3b", "ollama", "llama3.2:3b",
                             "Llama 3.2 3B", "Meta", "free", None),

    # ---- Company-authentic OPEN-WEIGHT local models ----
    # OpenAI's open models (Apache-2.0). gpt-oss:20b is the practical local size.
    "gpt-oss:20b": ModelSpec("gpt-oss:20b", "ollama", "gpt-oss:20b",
                             "GPT-OSS 20B", "OpenAI", "free", None),
    "gpt-oss:120b": ModelSpec("gpt-oss:120b", "ollama", "gpt-oss:120b",
                              "GPT-OSS 120B", "OpenAI", "free", None),
    # Google's open family (Gemma 3 is newer/stronger than gemma2).
    "gemma3:4b": ModelSpec("gemma3:4b", "ollama", "gemma3:4b",
                           "Gemma 3 4B", "Google", "free", None),
    "gemma3:12b": ModelSpec("gemma3:12b", "ollama", "gemma3:12b",
                            "Gemma 3 12B", "Google", "free", None),
    "gemma3:27b": ModelSpec("gemma3:27b", "ollama", "gemma3:27b",
                            "Gemma 3 27B", "Google", "free", None),
    # NOTE: Anthropic ships NO open weights (API-only), and xAI's Grok weights
    # (314B+) aren't practical to run locally — use their API entries below.

    # ---- Anthropic / Claude (FUNCTIONAL — you have a key) ----
    "claude-opus-4-8": ModelSpec("claude-opus-4-8", "anthropic", "claude-opus-4-8",
                                 "Claude Opus 4.8", "Anthropic", "high",
                                 "ANTHROPIC_API_KEY", 5.0, 25.0),
    "claude-sonnet-4-6": ModelSpec("claude-sonnet-4-6", "anthropic", "claude-sonnet-4-6",
                                   "Claude Sonnet 4.6", "Anthropic", "medium",
                                   "ANTHROPIC_API_KEY", 3.0, 15.0),
    "claude-haiku-4-5": ModelSpec("claude-haiku-4-5", "anthropic", "claude-haiku-4-5",
                                  "Claude Haiku 4.5", "Anthropic", "low",
                                  "ANTHROPIC_API_KEY", 1.0, 5.0),

    # ---- OpenAI (scaffold — needs OPENAI_API_KEY; update names as released) ----
    "gpt-5.1": ModelSpec("gpt-5.1", "openai", "gpt-5.1",
                         "GPT-5.1", "OpenAI", "high", "OPENAI_API_KEY", 5.0, 15.0),
    "gpt-4.1-mini": ModelSpec("gpt-4.1-mini", "openai", "gpt-4.1-mini",
                              "GPT-4.1 mini", "OpenAI", "low", "OPENAI_API_KEY", 0.4, 1.6),

    # ---- xAI / Grok (scaffold — needs XAI_API_KEY; OpenAI-compatible) ----
    "grok-4": ModelSpec("grok-4", "xai", "grok-4",
                        "Grok 4", "xAI", "high", "XAI_API_KEY", 3.0, 15.0),
    "grok-3-mini": ModelSpec("grok-3-mini", "xai", "grok-3-mini",
                             "Grok 3 mini", "xAI", "low", "XAI_API_KEY", 0.3, 0.5),

    # ---- DeepSeek (OpenAI-compatible; needs DEEPSEEK_API_KEY) ----
    "deepseek-chat": ModelSpec("deepseek-chat", "deepseek", "deepseek-chat",
                               "DeepSeek V3 (chat)", "DeepSeek", "low",
                               "DEEPSEEK_API_KEY", 0.27, 1.10),
    "deepseek-reasoner": ModelSpec("deepseek-reasoner", "deepseek", "deepseek-reasoner",
                                   "DeepSeek R1 (reasoner)", "DeepSeek", "medium",
                                   "DEEPSEEK_API_KEY", 0.55, 2.19),

    # ---- Google / Gemini (scaffold — needs GOOGLE_API_KEY + google-generativeai) ----
    "gemini-2.5-pro": ModelSpec("gemini-2.5-pro", "google", "gemini-2.5-pro",
                                "Gemini 2.5 Pro", "Google", "high", "GOOGLE_API_KEY", 1.25, 10.0),
    "gemini-2.5-flash": ModelSpec("gemini-2.5-flash", "google", "gemini-2.5-flash",
                                  "Gemini 2.5 Flash", "Google", "low", "GOOGLE_API_KEY", 0.3, 2.5),
}

# Default four-seat lineup (the 7-9B sweet spot). Editable; used by run_console / setup.
DEFAULT_SEATS: tuple[str, str, str, str] = (
    "qwen2.5:7b", "gemma2:9b", "llama3.1:8b", "mistral:7b",
)

# Suggested character-name presets per company (04 §5). Setup may offer these.
NAME_PRESETS: dict[str, str] = {
    "OpenAI": "Sage of the Open Eye",
    "Anthropic": "The Principled Blade",
    "Google": "Index, the All-Seer",
    "xAI": "Grok the Unchained",
    "Meta": "The Open Sorcerer",
    "Qwen": "Whisper of the Thousand Forms",
    "Mistral": "The Mistral Gale",
    "DeepSeek": "The Deep Seeker",
}


def get_spec(model_id: str) -> ModelSpec:
    try:
        return MODEL_REGISTRY[model_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown model_id '{model_id}'. Known: {sorted(MODEL_REGISTRY)}"
        ) from exc


LOCAL_PROVIDERS = {"ollama"}


def is_local(model_id: str) -> bool:
    """True for locally-run models (Ollama); False for frontier API models."""
    return get_spec(model_id).provider in LOCAL_PROVIDERS


def kind_label(model_id: str) -> str:
    return "LOCAL" if is_local(model_id) else "FRONTIER"


def is_available(model_id: str) -> bool:
    """True if this model can actually be called (no key needed, or its key is set)."""
    spec = get_spec(model_id)
    if spec.needs_key is None:
        return True  # ollama — assumed reachable; the smoke test proves it
    return bool(os.getenv(spec.needs_key))


def available_models() -> list[str]:
    return [mid for mid in MODEL_REGISTRY if is_available(mid)]
