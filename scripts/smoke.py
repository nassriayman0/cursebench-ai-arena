"""scripts/smoke.py — prove the model layer works.

Asks each AVAILABLE registered model to return {"ok": true} and validates it.
Unavailable models (missing API key) are listed and skipped, not failed.

    python scripts/smoke.py                # test every available model
    python scripts/smoke.py qwen2.5:7b claude-sonnet-4-6   # test a subset
"""

from __future__ import annotations

import os
import sys

# Make the project root importable when run as `python scripts/smoke.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pydantic import BaseModel  # noqa: E402

from config.models import MODEL_REGISTRY, available_models, get_spec, is_available  # noqa: E402
from models.structured import call_model_json  # noqa: E402


class OK(BaseModel):
    ok: bool


def test_model(model_id: str) -> bool:
    try:
        result = call_model_json(
            model_id,
            system="You are a connectivity test. Answer only with the requested JSON.",
            messages=[{"role": "user", "content": 'Reply with exactly: {"ok": true}'}],
            schema=OK,
            temperature=0.0,
            call_type="smoke",
        )
        ok = bool(result.ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {model_id}  -> ok={result.ok}")
        return ok
    except Exception as exc:  # noqa: BLE001 - smoke test reports, never crashes
        print(f"  FAIL  {model_id}  -> {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    requested = sys.argv[1:]
    targets = requested or available_models()

    if not targets:
        print("No available models. Add ANTHROPIC_API_KEY to .env, or start Ollama "
              "and `ollama pull qwen2.5:7b`.")
        return 1

    # Report what's being skipped for visibility.
    skipped = [m for m in MODEL_REGISTRY
               if m not in targets and not is_available(m)]
    if skipped and not requested:
        print(f"Skipping {len(skipped)} model(s) with no API key: {', '.join(skipped)}\n")

    print(f"Smoke-testing {len(targets)} model(s):")
    passed = 0
    for model_id in targets:
        if model_id not in MODEL_REGISTRY:
            print(f"  FAIL  {model_id}  -> not in registry")
            continue
        if not is_available(model_id):
            spec = get_spec(model_id)
            print(f"  SKIP  {model_id}  -> needs {spec.needs_key}")
            continue
        passed += test_model(model_id)

    tested = sum(1 for m in targets if m in MODEL_REGISTRY and is_available(m))
    print(f"\n{passed}/{tested} available model(s) passed.")
    return 0 if passed == tested and tested > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
