"""Offline counterfactual synthetic HUD replay: one-frame flickers vs stable state.

Run PYTHONPATH=. python benchmarks/stream_focus_replay.py. The only measured
quantities are theoretical admitted *requests* from two equal policy budgets,
and the local Python overhead of the temporal focus gate; neither demonstrates
real model calls, FPS increases, semantic recognition or live broadcast quality.
"""
from __future__ import annotations

from statistics import median
from time import perf_counter_ns

from star.stream_budget import StreamTelemetry
from star.stream_focus_stability import TemporalFocusGate
from star.stream_observe import FocusSample, FrameCue, ObservationGovernor

REGION = (100, 20, 64, 24)
STATES = (0, 1, 0, 1, 0, 1, 1, 1, 0, 0, 1, 0, 1, 0)


def replay(*, confirm_focus: bool) -> tuple[int, int, float]:
    governor = ObservationGovernor(
        calls_per_minute=120, burst=4, refresh_ms=120000,
    )
    governor.enable(owner_approved=True)
    gate = TemporalFocusGate() if confirm_focus else None
    telemetry = StreamTelemetry(True, True, 4000, 8192, 60, 20)
    offers = 0
    deferred_novelty = 0
    durations = []
    for index, state in enumerate(STATES):
        captured = 1000.0 + 1200 * index
        frame = FrameCue(
            captured, 0, focus_samples=(FocusSample(
                REGION, 0, 0 if state == 0 else 20 << 36,
            ),),
        )
        if gate is not None:
            start = perf_counter_ns()
            frame = gate.filter(frame).frame
            durations.append((perf_counter_ns() - start) / 1e3)
        decision = governor.consider(
            frame, telemetry, now_ms=captured,
            capture_authorized=True,
        )
        if decision.admitted:
            offers += 1
            assert governor.complete(
                ticket=decision.ticket, now_ms=captured + 10, succeeded=True
            )
        if decision.reason == "low_visual_novelty":
            deferred_novelty += 1
    return offers, deferred_novelty, median(durations) if durations else 0.0


if __name__ == "__main__":
    old = replay(confirm_focus=False)
    new = replay(confirm_focus=True)
    print("14 synthetic 1.2-s-apart focus signatures; sustained and transient transitions")
    print(f"Default: {old[0]} admitted vision requests, {old[1]} novelty-deferrals")
    print(f"Opt-in: {new[0]} admitted vision requests, {new[1]} novelty-deferrals")
    print(f"Gate Python median overhead: {new[2]:.2f} microseconds per already-fingerprinted frame")
