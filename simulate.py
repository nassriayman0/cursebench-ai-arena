"""simulate.py — headless balance harness (Step 10).

Runs N matches with fixed seeds and reports: win-rate by seat, median round
length, Black Flash frequency, and % of rounds touched by domains. Tune the
constants in config/settings.py until: no seat > 35% win-rate over 50 matches,
median round length 4-9 ticks, Black Flash ~once per 2-3 rounds.

By default runs in --stub mode (deterministic stub policy + offline generation,
NO model calls) so you can tune the combat MATH for free and fast. Use
--no-stub to test strategy balance with real models (slow + may cost money).

    python simulate.py --matches 50 --seed 42                 # fast mechanics balance
    python simulate.py --matches 6 --no-stub --model qwen2.5:7b
"""

from __future__ import annotations

import argparse
import statistics

from config import settings
from config.models import DEFAULT_SEATS
from game.engine import StubPolicy, run_match
from game.setup import build_agents, build_game_state
from game.scoring import match_winner
from util.logging import CallMeter


def _noop(_s: str) -> None:
    pass


def run_one(seats: list[str], seed: int, rounds: int, stub: bool,
            meter: CallMeter) -> dict:
    options = {
        "enable_negotiation": not stub, "enable_handicaps": not stub,
        "enable_reflect": False, "enable_react": False,
    }
    state = build_game_state(seats, seed=seed, options=options)
    if stub:
        agents = {n: StubPolicy() for n in state.fighters}
    else:
        agents = build_agents(state, meter)
    run_match(state, agents, rounds=rounds, meter=meter, on_line=_noop,
              use_llm_generation=not stub, save=False, update_board=False)

    seat_order = list(state.fighters)
    winner = match_winner(state)
    win_idx = seat_order.index(winner.character_name) if winner else None
    ticks, black_flash, domain_rounds, storm_rounds = [], 0, 0, 0
    attacks = waits = actions = 0
    tech_kos: list[int] = []
    for rec in state.records:
        ticks.append(max(0, len(rec.hp_ce_timeline) - 1))
        types = [e.type for e in rec.special_events]
        black_flash += types.count("BLACK FLASH")
        if any(t.startswith("DOMAIN") for t in types):
            domain_rounds += 1
        if rec.decided_by == "storm":
            storm_rounds += 1
        for m in rec.moves:
            actions += 1
            if m.action == "attack":
                attacks += 1
            elif m.action == "wait":
                waits += 1
        tech_kos.append(sum(1 for e in rec.special_events
                            if e.type == "KO" and "storm" not in (e.detail or "").lower()))
    return {"win_idx": win_idx, "ticks": ticks, "black_flash": black_flash,
            "domain_rounds": domain_rounds, "rounds": len(state.records),
            "storm_rounds": storm_rounds, "attacks": attacks, "waits": waits,
            "actions": actions, "tech_kos": tech_kos, "num_fighters": len(state.fighters)}


def main() -> int:
    ap = argparse.ArgumentParser(description="JJK Arena headless balance sim")
    ap.add_argument("--matches", type=int, default=50)
    ap.add_argument("--seed", type=int, default=settings.DEFAULT_SEED)
    ap.add_argument("--rounds", type=int, default=settings.NUM_ROUNDS)
    ap.add_argument("--model", default=None,
                    help="use one model for all 4 seats (real-model runs)")
    ap.add_argument("--no-stub", dest="stub", action="store_false",
                    help="run with real LLM agents (slow, may cost money)")
    ap.set_defaults(stub=True)
    args = ap.parse_args()

    if args.model:
        seats = [args.model] * 4
    else:
        seats = list(DEFAULT_SEATS)

    meter = CallMeter()
    seat_wins = [0, 0, 0, 0]
    all_ticks: list[int] = []
    all_tech_kos: list[int] = []
    total_bf = total_rounds = total_domain_rounds = total_storm = 0
    total_attacks = total_waits = total_actions = 0
    num_fighters = 4

    print(f"Simulating {args.matches} matches "
          f"({'STUB/offline' if args.stub else 'REAL models'}), "
          f"{args.rounds} rounds each, seats={seats}\n")
    for i in range(args.matches):
        res = run_one(seats, args.seed + i, args.rounds, args.stub, meter)
        if res["win_idx"] is not None:
            seat_wins[res["win_idx"]] += 1
        all_ticks += res["ticks"]
        all_tech_kos += res["tech_kos"]
        total_bf += res["black_flash"]
        total_rounds += res["rounds"]
        total_domain_rounds += res["domain_rounds"]
        total_storm += res["storm_rounds"]
        total_attacks += res["attacks"]
        total_waits += res["waits"]
        total_actions += res["actions"]
        num_fighters = res["num_fighters"]
        print(f"  match {i + 1}/{args.matches}: winner seat "
              f"{res['win_idx']}  rounds={res['rounds']}")

    n = max(1, args.matches)
    rounds = max(1, total_rounds)
    acts = max(1, total_actions)

    def flag(ok: bool) -> str:
        return "  OK" if ok else "  <-- OFF TARGET"

    print("\n" + "=" * 60)
    print("v2 BALANCE REPORT")
    print("=" * 60)
    print("Win-rate by seat (target: none > 35%):")
    for idx in range(4):
        rate = seat_wins[idx] / n * 100
        print(f"  seat {idx}: {seat_wins[idx]:3d}/{n}  ({rate:4.0f}%)"
              + ("  <-- DOMINANT" if rate > 35 else ""))

    med_ticks = statistics.median(all_ticks) if all_ticks else 0
    print(f"\nRound length:      median {med_ticks:.1f} ticks (target 5-10)"
          f"{flag(5 <= med_ticks <= 10)}")

    storm_pct = total_storm / rounds * 100
    print(f"Storm-decided:     {total_storm}/{total_rounds} rounds ({storm_pct:.0f}%) "
          f"(target < 20%){flag(storm_pct < 20)}")

    med_tech_kos = statistics.median(all_tech_kos) if all_tech_kos else 0
    print(f"KOs by technique:  median {med_tech_kos:.1f}/round (target >= 2)"
          f"{flag(med_tech_kos >= 2)}")

    apf = total_attacks / (rounds * num_fighters)
    print(f"Attacks / fighter: {apf:.2f} per round (target >= 3)"
          f"{flag(apf >= 3)}"
          + ("   [meaningful with --no-stub]" if args.stub else ""))

    wait_pct = total_waits / acts * 100
    print(f"Wait actions:      {wait_pct:.0f}% of all actions (target < 35%)"
          f"{flag(wait_pct < 35)}"
          + ("   [meaningful with --no-stub]" if args.stub else ""))

    per = rounds / total_bf if total_bf else float("inf")
    print(f"Black Flash:       {total_bf} over {total_rounds} rounds "
          f"(1 per {per:.1f}; target every 2-3){flag(2 <= per <= 3.5)}")
    print(f"Domains touched:   {total_domain_rounds}/{total_rounds} rounds "
          f"({total_domain_rounds / rounds * 100:.0f}%)")
    if not args.stub:
        print(f"\nModel calls: {meter.summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
