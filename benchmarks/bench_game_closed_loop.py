"""Deterministic toy-game rehearsal, NOT a live game/AI/streaming benchmark.

Usage: PYTHONPATH=. python -m benchmarks.bench_game_closed_loop --seeds 32
Validates the host -> advice -> dispatch ACK -> observed outcome contract.
Results measure only tiny pure-Python planning loops; no model or GPU runs.
"""
from __future__ import annotations

import argparse
import json
from random import Random
from time import perf_counter

from star.game_closed_loop import ClosedLoopPilot, PracticeScope
from star.game_navigation import GameFrame, SeenTile


def fixture(seed: int, size: int = 8) -> tuple[str, ...]:
    """Held-out seeded walls plus a guaranteed, hidden safe path to goal."""
    rng = Random(seed)
    board = [["#" if rng.random() < 0.26 else "." for _ in range(size)] for _ in range(size)]
    for x in range(size):
        board[0][x] = "."
    for y in range(size):
        board[y][size - 1] = "."
    board[0][0] = "S"
    board[-1][-1] = "G"
    return tuple("".join(row) for row in board)


def host_frame(world: tuple[str, ...], position: tuple[int, int], seq: int, seed: int) -> GameFrame:
    x0, y0 = position
    visible = []
    for x, y in ((x0, y0), (x0 + 1, y0), (x0 - 1, y0), (x0, y0 + 1), (x0, y0 - 1)):
        if 0 <= x < len(world[0]) and 0 <= y < len(world):
            cell = world[y][x]
            visible.append(SeenTile((x, y), "wall" if cell == "#" else
                                    "goal" if cell == "G" else "floor"))
    return GameFrame("toy", f"seed_{seed}", seq, len(world[0]), len(world),
                     position, tuple(visible))


def trial(seed: int, *, mode: str = "practice") -> dict[str, int | bool | str | None]:
    """Independent host applies allowed movement; agent never sees hidden map."""
    world = fixture(seed)
    pilot = ClosedLoopPilot(PracticeScope("toy", f"seed_{seed}", len(world[0]),
                                           len(world), mode=mode,
                                           sandbox_approved=mode == "practice",
                                           max_actions=180))
    position = (0, 0)
    for seq in range(1, 182):
        t = 10 * seq
        receipt = pilot.observe(host_frame(world, position, seq, seed),
                                observed_ms=t, trusted_host=True)
        if receipt.goal_reached or receipt.stopped_reason:
            break
        offer = pilot.offer(now_ms=t + 1)
        if offer is None:
            break
        if not pilot.acknowledge_dispatched(offer.ticket, now_ms=t + 2,
                                           host_dispatched=True):
            raise AssertionError("Host ACK failed in deterministic rehearsal")
        x, y = offer.destination
        if world[y][x] not in "#":
            position = (x, y)
        # If host reports the player still at old location, the pilot should
        # detect blocked movement on the following frame and permanently stop.
    metrics = pilot.summary()
    return {"seed": seed, "reached_goal": metrics["stopped_reason"] == "goal_reached",
            "actions": metrics["actions_dispatched"],
            "verified": metrics["movements_verified"],
            "halt": metrics["stopped_reason"] or "abstained"}


def run(seeds: int) -> dict:
    if type(seeds) is not int or not 1 <= seeds <= 128:
        raise ValueError("seeds must be 1..128")
    start = perf_counter()
    rows = [trial(seed) for seed in range(seeds)]
    elapsed_ms = round((perf_counter() - start) * 1000, 2)
    return {"kind": "synthetic_grid_rehearsal_only", "seed_count": seeds,
            "completed": sum(r["reached_goal"] for r in rows),
            "blocked": sum(r["halt"] == "movement_mismatch" for r in rows),
            "abstained": sum(r["halt"] == "abstained" for r in rows),
            "actions": sum(r["actions"] for r in rows),
            "host_verified_moves": sum(r["verified"] for r in rows),
            "local_python_wall_ms": elapsed_ms,
            "note": "NOT Roblox, GPU throughput, higher model intelligence, or live broadcasting."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=32)
    args = parser.parse_args()
    print(json.dumps(run(args.seeds), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
