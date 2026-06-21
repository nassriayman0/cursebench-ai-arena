"""run_console.py — the Stage A vertical slice.

Builds a 4-fighter match and runs one full round to last-one-standing, printing a
readable tick-by-tick log, then saves the match JSON to ./saves/.

Examples:
    python run_console.py                      # 4 default Ollama seats, real agents
    python run_console.py --stub               # engine only, NO model calls (offline)
    python run_console.py --rounds 3 --seed 7
    python run_console.py --seats claude-sonnet-4-6 qwen2.5:7b gemma2:9b llama3.1:8b
"""

from __future__ import annotations

import argparse

from config import settings
from config.models import DEFAULT_SEATS, is_available
from game.engine import StubPolicy, run_round
from game.setup import build_agents, build_game_state
from util.logging import CallMeter
from util.persistence import save_match

# Keep the console slice fast; the Streamlit UI exposes these as toggles.
_CONSOLE_OPTS = {
    "enable_negotiation": False, "enable_reflect": False,
    "enable_handicaps": True, "enable_react": False,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="JJK Arena — console vertical slice")
    ap.add_argument("--seats", nargs="+", default=list(DEFAULT_SEATS),
                    help="4 model_ids from the registry (order = seats)")
    ap.add_argument("--names", nargs="*", default=[], help="character names per seat")
    ap.add_argument("--seed", type=int, default=settings.DEFAULT_SEED)
    ap.add_argument("--rounds", type=int, default=1, help="rounds to run (slice=1)")
    ap.add_argument("--stub", action="store_true",
                    help="use the heuristic stub policy + offline generation (no LLM)")
    args = ap.parse_args()

    if len(args.seats) != 4:
        print(f"Need exactly 4 seats, got {len(args.seats)}: {args.seats}")
        return 1

    state = build_game_state(args.seats, args.names, seed=args.seed,
                             options=_CONSOLE_OPTS,
                             match_id=f"console_seed{args.seed}")
    meter = CallMeter()

    print("=" * 64)
    print("JJK ARENA — console slice")
    print(f"seed={args.seed}  mode={'STUB (offline)' if args.stub else 'LLM agents'}")
    for f in state.fighters.values():
        avail = "" if (args.stub or is_available(f.model_id)) else "  [UNAVAILABLE - will fall back to wait]"
        print(f"  {f.character_name:28s} <- {f.model_id} ({f.company}){avail}")
    print("=" * 64)

    if args.stub:
        agents = {n: StubPolicy() for n in state.fighters}
    else:
        agents = build_agents(state, meter)

    for r in range(1, args.rounds + 1):
        run_round(state, agents, round_number=r, meter=meter, on_line=print,
                  use_llm_generation=not args.stub)

    print("\n" + "=" * 64)
    print("Rounds won:")
    for f in sorted(state.fighters.values(), key=lambda x: -x.rounds_won):
        print(f"  {f.character_name:28s} {f.rounds_won}")
    if not args.stub:
        print(f"\nModel calls: {meter.summary()}")
    path = save_match(state)
    print(f"Saved match -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
