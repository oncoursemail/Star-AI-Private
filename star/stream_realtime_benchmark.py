"""Offline, paired CPU/GPU streaming evaluation with no microphone or game access.

A trusted capture host supplies same-clock first-audible times and per-frame
durations. The analyzer deliberately cannot start a stream, choose model
routes, authenticate telemetry, or promote a candidate configuration. It
reports only aggregate numbers, not voice, chat, content, player names or IDs.
"""
from __future__ import annotations

from typing import cast

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import random
import re
from typing import Iterable

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_RUN_FIELDS = frozenset({
    "pair_id", "variant", "game_id", "game_version", "first_audio_ms",
    "frame_times_ms", "gpu_peak_mib", "audio_finished",
})


def _bounded(value: object, name: str, lower: float, upper: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    try:
        val = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(val) or not lower <= val <= upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return val


def _id(value: object, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a short opaque identifier")
    return value


def _pct(values: Iterable[float], proportion: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(proportion * len(ordered)) - 1)]


@dataclass(frozen=True)
class RealtimeRun:
    """One whole observation: a paired A/B experiment's host measurements.

    Frame times are in milliseconds from actual game presentation, not an
    unrelated idle GPU benchmark. At least 120 frames are required to report
    a descriptive p99 frametime (1%-low FPS proxy).
    """

    pair_id: str
    variant: str                 # baseline | candidate
    game_id: str
    game_version: str
    first_audio_ms: float        # speech request -> first *audible* PCM
    frame_times_ms: tuple[float, ...]
    gpu_peak_mib: float
    audio_finished: bool

    def __post_init__(self) -> None:
        for name in ("pair_id", "game_id", "game_version"):
            _id(getattr(self, name), name)
        if self.variant not in ("baseline", "candidate"):
            raise ValueError("variant must be baseline or candidate")
        _bounded(self.first_audio_ms, "first_audio_ms", 0, 120_000)
        _bounded(self.gpu_peak_mib, "gpu_peak_mib", 0, 262_144)
        if type(self.audio_finished) is not bool:
            raise ValueError("audio_finished must be a host boolean")
        if type(self.frame_times_ms) is not tuple or not (
            120 <= len(self.frame_times_ms) <= 5000
        ):
            raise ValueError("frame_times_ms must have 120..5000 samples")
        for duration in self.frame_times_ms:
            _bounded(duration, "frame duration", 0.01, 10_000)

    @classmethod
    def from_dict(cls, row: object) -> RealtimeRun:
        if type(row) is not dict or set(row) != _RUN_FIELDS:
            raise ValueError("expected only the eight bounded timing fields")
        values = dict(row)
        if type(values["frame_times_ms"]) is not list:
            raise ValueError("frame_times_ms must be a JSON array")
        values["frame_times_ms"] = tuple(values["frame_times_ms"])
        return cls(**values)


@dataclass(frozen=True)
class RealtimeComparison:
    scope: str
    complete_pairs: int
    incomplete_pairs: int
    failed_pairs: int
    baseline_ttfa_p95_ms: float | None
    candidate_ttfa_p95_ms: float | None
    ttfa_mean_gain_ms: float | None
    ttfa_gain_ci95_ms: tuple[float, float] | None
    fps_1pct_low_mean_baseline: float | None
    fps_1pct_low_mean_candidate: float | None
    fps_gain_ci95: tuple[float, float] | None
    candidate_gpu_peak_mib: float | None
    verdict: str                 # eligible_for_manual_pilot | regressed | inconclusive
    note: str = "host-measured only; no automatic deployment or causal claim"


def _bootstrap_mean_ci(diffs: list[float], *, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    draws = []
    for _ in range(1600):
        draws.append(sum(diffs[rng.randrange(n)] for _ in range(n)) / n)
    return round(_pct(draws, 0.025), 3), round(_pct(draws, 0.975), 3)


def _low_fps(run: RealtimeRun) -> float:
    return 1000.0 / _pct(run.frame_times_ms, 0.99)


def compare_realtime(
    runs: Iterable[RealtimeRun], *, minimum_pairs: int = 20,
    gpu_budget_mib: float = 6656,
) -> RealtimeComparison:
    """Evaluate completed matched recordings, never decide live routing.

    Conservative pilot criterion: 20+ pre-registered complete pairs,
    uninterrupted speech, bootstrap lower CI of TTFA gain > 30 ms, p95 TTFA
    no worse, bootstrap lower CI of 1%-low FPS delta >= -3 FPS, candidate
    GPU peak within a manually chosen budget. The CI quantifies sampling
    uncertainty only, not uncontrolled changes, measurement bias or causality.
    """
    if type(minimum_pairs) is not int or not 10 <= minimum_pairs <= 500:
        raise ValueError("minimum_pairs must be 10..500")
    budget = _bounded(gpu_budget_mib, "gpu_budget_mib", 512, 262_144)
    pairs: dict[str, dict[str, RealtimeRun]] = {}
    scope: tuple[str, str] | None = None
    count = 0
    for row in runs:
        if not isinstance(row, RealtimeRun):
            raise TypeError("expected RealtimeRun")
        count += 1
        if count > 1000:
            raise ValueError("too many recorded runs")
        this_scope = (row.game_id, row.game_version)
        if scope is None:
            scope = this_scope
        elif scope != this_scope:
            raise ValueError("do not pool unrelated game versions or scenes")
        variants = pairs.setdefault(row.pair_id, {})
        if row.variant in variants:
            raise ValueError("duplicate pair/variant: do not choose a best run")
        variants[row.variant] = row
    if not pairs:
        return RealtimeComparison("none", 0, 0, 0, None, None, None, None,
                                  None, None, None, None, "inconclusive")
    # A nonempty pair collection is constructed only from a concrete scope.
    if scope is None:
        raise RuntimeError("matched gameplay scope unavailable")
    completed = [p for p in pairs.values() if len(p) == 2]
    incomplete = len(pairs) - len(completed)
    failures = sum(
        not pair["baseline"].audio_finished or not pair["candidate"].audio_finished
        for pair in completed
    )
    valid = [pair for pair in completed if (
        pair["baseline"].audio_finished and pair["candidate"].audio_finished
    )]
    scope_id = f"{scope[0]}:{scope[1]}"
    if not valid:
        return RealtimeComparison(
            scope_id, len(completed), incomplete, failures, None, None, None,
            None, None, None, None, None,
            "regressed" if failures else "inconclusive",
        )
    baseline = [p["baseline"] for p in valid]
    candidate = [p["candidate"] for p in valid]
    ttfa_diffs = [b.first_audio_ms - c.first_audio_ms
                  for b, c in zip(baseline, candidate)]
    fps_diffs = [_low_fps(c) - _low_fps(b)
                 for b, c in zip(baseline, candidate)]
    ci = _bootstrap_mean_ci(ttfa_diffs, seed=2510)
    fps_ci = _bootstrap_mean_ci(fps_diffs, seed=2601)
    p95_base = _pct((r.first_audio_ms for r in baseline), 0.95)
    p95_new = _pct((r.first_audio_ms for r in candidate), 0.95)
    peak = max(r.gpu_peak_mib for r in candidate)
    mean_diff = sum(ttfa_diffs) / len(ttfa_diffs)
    fps_base = sum(_low_fps(r) for r in baseline) / len(baseline)
    fps_new = sum(_low_fps(r) for r in candidate) / len(candidate)

    eligible = (
        len(completed) >= minimum_pairs and incomplete == 0 and failures == 0
        and ci[0] > 30 and p95_new <= p95_base and fps_ci[0] >= -3
        and peak <= budget
    )
    regressed = (
        ci[1] < -30 or fps_ci[1] < -3 or peak > budget or failures > 0
    )
    verdict = ("eligible_for_manual_pilot" if eligible else
               "regressed" if regressed else "inconclusive")
    return RealtimeComparison(
        scope_id, len(completed), incomplete, failures,
        round(p95_base, 3), round(p95_new, 3),
        round(mean_diff, 3), ci, round(fps_base, 3), round(fps_new, 3),
        fps_ci, round(peak, 3), verdict,
    )


def read_jsonl(path: str | Path) -> list[RealtimeRun]:
    """Explicit opt-in only; local JSONL records, no event text or networking."""
    path = Path(path)
    if path.stat().st_size > 8_000_000:
        raise ValueError("benchmark input exceeds 8 MB")
    rows = []
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if line.strip():
                if len(line) > 110_000:
                    raise ValueError("oversized run record")
                rows.append(RealtimeRun.from_dict(json.loads(line)))
                if len(rows) > 1000:
                    raise ValueError("too many run records")
    return rows


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Offline, advisory A/B analysis; never changes stream settings"
    )
    parser.add_argument("jsonl", help="explicit path to trusted host measurements")
    parser.add_argument("--gpu-budget-mib", type=float, default=6656)
    args = parser.parse_args()
    result = compare_realtime(
        read_jsonl(args.jsonl), gpu_budget_mib=args.gpu_budget_mib
    )
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
