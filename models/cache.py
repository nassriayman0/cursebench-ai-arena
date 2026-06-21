"""models/cache.py — per-match response cache for stable replays (00 / 12).

LLMs aren't deterministic, so caching each (model, prompt) response per match lets
a saved match replay identically and avoids re-calling models on Streamlit reruns.
The cache is opt-in: base.set_active_cache(cache) installs one for a match; without
it, call_model behaves exactly as before.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional


class ResponseCache:
    def __init__(self, store: Optional[dict] = None) -> None:
        self._store: dict[str, str] = dict(store or {})

    @staticmethod
    def make_key(model_id: str, system: str, messages: list[dict],
                 json_mode: bool, temperature: float) -> str:
        payload = json.dumps(
            {"m": model_id, "s": system, "msgs": messages,
             "j": json_mode, "t": round(temperature, 3)},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def has(self, key: str) -> bool:
        return key in self._store

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def put(self, key: str, value: str) -> None:
        self._store[key] = value

    def to_dict(self) -> dict:
        return dict(self._store)

    def __len__(self) -> int:
        return len(self._store)
