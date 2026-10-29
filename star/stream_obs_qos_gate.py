"""Independent OBS frame-loss veto for Star's paired gaming/voice benchmark.

The existing stream_realtime_benchmark checks first-audible latency, game FPS,
and GPU memory. This OPTIONAL offline companion adds OBS's actual render/output
thread counters from a trusted host, preventing a faster TTS/VLM configuration
from being called a win when the broadcast stutters. It does not connect to
OBS, run a game, start a broadcast, authenticate a source or promote a model.

Use two GetStats snapshots from the SAME OBS process per test window, plus an
independent GetStreamStatus active/reconnect attestation. OBS counter windows
must be paired by precommitted test ID and game/version. There is no storage of
chat, audio, video, player identifiers, prompts or OBS credentials.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import math
import re
from typing import Mapping, Sequence

from .stream_realtime_benchmark import (
    RealtimeComparison, RealtimeRun, compare_realtime,
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_STATS_KEYS = frozenset({
    "renderTotalFrames", "renderSkippedFrames",
    "outputTotalFrames", "outputSkippedFrames",
})
_MAX_COUNTER = (1 << 53) - 1
_WINDOW_FIELDS = frozenset({
    "pair_id", "variant", "game_id", "game_version", "session_id",
    "start_ms", "end_ms", "before", "after", "stream_active",
    "reconnect_observed",
})


def _id(value: object, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a short opaque identifier")
    return value


def _counter(value: object, name: str) -> int:
    # obs-websocket transmits JSON numbers. It sometimes decodes integer
    # counters as integral floats; reject booleans, NaN, fractions and strings.
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be an integer OBS counter")
    if not 0 <= value <= _MAX_COUNTER:
        raise ValueError(f"{name} outside precise OBS counter range")
    if not math.isfinite(value):
        raise ValueError(f"{name} outside precise OBS counter range")
    if int(value) != value:
        raise ValueError(f"{name} must be integral")
    return int(value)


def _millis(value: object, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must use host monotonic milliseconds")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} out of range") from exc
    if not math.isfinite(result) or not 0 <= result <= 1e13:
        raise ValueError(f"{name} out of range")
    return result


@dataclass(frozen=True)
class ObsStatsCounters:
    """Four cumulative frame counters from OBS 5.x GetStats, no other fields."""

    render_total: int
    render_skipped: int
    output_total: int
    output_skipped: int

    def __post_init__(self) -> None:
        for name in ("render_total", "render_skipped", "output_total", "output_skipped"):
            object.__setattr__(self, name, _counter(getattr(self, name), name))
        if (self.render_skipped > self.render_total
                or self.output_skipped > self.output_total):
            raise ValueError("OBS skipped frames cannot exceed total frames")

    @classmethod
    def from_getstats(cls, payload: Mapping[str, object]) -> ObsStatsCounters:
        """Project allowlisted GetStats fields; do not retain other OBS data."""
        if not isinstance(payload, Mapping) or not _STATS_KEYS.issubset(payload):
            raise ValueError("missing required OBS GetStats frame counters")
        return cls(
            _counter(payload["renderTotalFrames"], "renderTotalFrames"),
            _counter(payload["renderSkippedFrames"], "renderSkippedFrames"),
            _counter(payload["outputTotalFrames"], "outputTotalFrames"),
            _counter(payload["outputSkippedFrames"], "outputSkippedFrames"),
        )


@dataclass(frozen=True)
class ObsFrameWindow:
    """One continuous OBS-process window matching one paired runtime run.

    The host asserts session_id continuity. A different process/restart must
    create a different session_id; if a reset is hidden, offline counters alone
    cannot detect it. Exactly one baseline and candidate per pair is required.
    """

    pair_id: str
    variant: str
    game_id: str
    game_version: str
    session_id: str
    start_ms: float
    end_ms: float
    before: ObsStatsCounters
    after: ObsStatsCounters
    stream_active: bool
    reconnect_observed: bool

    def __post_init__(self) -> None:
        for name in ("pair_id", "game_id", "game_version", "session_id"):
            _id(getattr(self, name), name)
        if type(self.variant) is not str or self.variant not in ("baseline", "candidate"):
            raise ValueError("OBS window variant must be baseline or candidate")
        start = _millis(self.start_ms, "start_ms")
        end = _millis(self.end_ms, "end_ms")
        if not 2000 <= end - start <= 600_000:
            raise ValueError("OBS window must span 2 seconds to 10 minutes")
        if (type(self.before) is not ObsStatsCounters
                or type(self.after) is not ObsStatsCounters):
            raise TypeError("OBS window requires before/after frame counters")
        if type(self.stream_active) is not bool or type(self.reconnect_observed) is not bool:
            raise ValueError("OBS status must be host-attested booleans")
        for field in ("render_total", "render_skipped", "output_total", "output_skipped"):
            if getattr(self.after, field) < getattr(self.before, field):
                raise ValueError("OBS counters went backwards: process restart or reset")
        if (self.render_total < 120 or self.output_total < 120
                or self.render_skipped > self.render_total
                or self.output_skipped > self.output_total):
            raise ValueError("OBS window has too few frames or invalid skip deltas")

    @classmethod
    def from_dict(cls, row: object) -> ObsFrameWindow:
        if type(row) is not dict or set(row) != _WINDOW_FIELDS:
            raise ValueError("OBS JSONL rows must contain exactly the eleven window fields")
        values = dict(row)
        values["before"] = ObsStatsCounters.from_getstats(values["before"])
        values["after"] = ObsStatsCounters.from_getstats(values["after"])
        return cls(**values)

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms

    @property
    def render_total(self) -> int:
        return self.after.render_total - self.before.render_total

    @property
    def render_skipped(self) -> int:
        return self.after.render_skipped - self.before.render_skipped

    @property
    def output_total(self) -> int:
        return self.after.output_total - self.before.output_total

    @property
    def output_skipped(self) -> int:
        return self.after.output_skipped - self.before.output_skipped


@dataclass(frozen=True)
class ObsQoSReport:
    """Aggregates only; no pair identifiers or private telemetry payloads."""

    verdict: str
    performance_verdict: str
    paired_windows: int
    missing_windows: int
    candidate_render_skipped_pct: float | None
    candidate_output_skipped_pct: float | None
    render_skip_increase_pp: float | None
    output_skip_increase_pp: float | None
    worst_candidate_render_pct: float | None
    worst_candidate_output_pct: float | None
    candidate_reconnections: int
    note: str = ("advisory, host-attested OBS counters; no network-loss guarantee "
                 "or automatic stream/model changes")


def _rate(skipped: int, total: int) -> float:
    return 100.0 * skipped / total


def compare_realtime_with_obs(
    runs: Sequence[RealtimeRun],
    windows: Sequence[ObsFrameWindow],
    *,
    minimum_pairs: int = 20,
    gpu_budget_mib: float = 6656,
    max_render_skip_pct: float = 0.5,
    max_output_skip_pct: float = 0.5,
    max_increase_pp: float = 0.2,
    max_worst_window_pct: float = 1.0,
) -> ObsQoSReport:
    """Require existing audio/game success AND matched low-loss OBS telemetry.

    OBS limits are conservative, owner-tunable acceptance gates, not claims
    about human noticeability. Drops in GetStats' output thread are not the
    same as transport/network drops from GetStreamStatus; monitor those apart.
    No auto-promotion occurs. Missing windows -> inconclusive, never eligible.
    An actually damaged candidate stream -> regressed, even if TTS is faster.
    """
    for label, value, lower, upper in (
        ("max_render_skip_pct", max_render_skip_pct, 0.0, 5.0),
        ("max_output_skip_pct", max_output_skip_pct, 0.0, 5.0),
        ("max_increase_pp", max_increase_pp, 0.0, 3.0),
        ("max_worst_window_pct", max_worst_window_pct, 0.0, 10.0),
    ):
        amount = _millis(value, label)
        if not lower <= amount <= upper:
            raise ValueError(f"{label} exceeds conservative bounds")
    if type(runs) not in (tuple, list) or type(windows) not in (tuple, list):
        raise TypeError("supply bounded, fully materialized paired observations")
    # Delegate the full paired TTFA/game FPS/GPU evaluation; do not substitute
    # our OBS-only success for the original performance evidence.
    performance: RealtimeComparison = compare_realtime(
        runs, minimum_pairs=minimum_pairs, gpu_budget_mib=gpu_budget_mib,
    )
    if len(windows) > 1000:
        raise ValueError("at most 1000 OBS windows")
    expected: dict[tuple[str, str], RealtimeRun] = {}
    for run in runs:
        expected[(run.pair_id, run.variant)] = run
    received: dict[tuple[str, str], ObsFrameWindow] = {}
    for window in windows:
        if type(window) is not ObsFrameWindow:
            raise TypeError("expected validated OBS counter window")
        key = (window.pair_id, window.variant)
        if key not in expected:
            raise ValueError("unexpected OBS variant or unmatched benchmark pair")
        if key in received:
            raise ValueError("duplicate OBS window: cannot cherry-pick best run")
        corresponding = expected[key]
        if ((window.game_id, window.game_version)
                != (corresponding.game_id, corresponding.game_version)):
            raise ValueError("OBS and gaming benchmark scopes differ")
        received[key] = window

    missing = len(expected) - len(received)
    def report(verdict: str, *, reconnections: int = 0) -> ObsQoSReport:
        return ObsQoSReport(verdict, performance.verdict,
                            sum(all((pid, v) in received for v in ("baseline", "candidate"))
                                for pid in {r.pair_id for r in runs}), missing,
                            None, None, None, None, None, None, reconnections)
    if missing or not expected:
        return report("regressed" if performance.verdict == "regressed" else "inconclusive")
    cohorts: dict[str, dict[str, ObsFrameWindow]] = {}
    for window in received.values():
        cohorts.setdefault(window.pair_id, {})[window.variant] = window
    for pair in cohorts.values():
        base, cand = pair["baseline"], pair["candidate"]
        if (abs(base.duration_ms - cand.duration_ms)
                > 0.2 * max(base.duration_ms, cand.duration_ms)):
            raise ValueError("baseline and candidate OBS windows have different exposure")
        # Baseline must be a meaningful comparison; candidate connectivity
        # disruptions are a failure even when its framing counters look fine.
        if not base.stream_active or base.reconnect_observed:
            return report("inconclusive")
    base_wins = [pair["baseline"] for pair in cohorts.values()]
    cand_wins = [pair["candidate"] for pair in cohorts.values()]
    def aggregate(rows: list[ObsFrameWindow], prefix: str) -> float:
        return _rate(sum(getattr(x, f"{prefix}_skipped") for x in rows),
                     sum(getattr(x, f"{prefix}_total") for x in rows))
    base_render = aggregate(base_wins, "render")
    base_output = aggregate(base_wins, "output")
    cand_render = aggregate(cand_wins, "render")
    cand_output = aggregate(cand_wins, "output")
    worst_render = max(_rate(x.render_skipped, x.render_total) for x in cand_wins)
    worst_output = max(_rate(x.output_skipped, x.output_total) for x in cand_wins)
    candidate_bad = sum(not x.stream_active or x.reconnect_observed for x in cand_wins)
    drift_render = cand_render - base_render
    drift_output = cand_output - base_output
    exceeded = (
        candidate_bad > 0
        or cand_render > max_render_skip_pct
        or cand_output > max_output_skip_pct
        or drift_render > max_increase_pp
        or drift_output > max_increase_pp
        or worst_render > max_worst_window_pct
        or worst_output > max_worst_window_pct
    )
    verdict = (
        "regressed" if exceeded or performance.verdict == "regressed" else
        "eligible_for_manual_pilot" if performance.verdict == "eligible_for_manual_pilot" else
        "inconclusive"
    )
    return ObsQoSReport(
        verdict, performance.verdict, len(cohorts), 0,
        round(cand_render, 4), round(cand_output, 4),
        round(drift_render, 4), round(drift_output, 4),
        round(worst_render, 4), round(worst_output, 4), candidate_bad,
    )


def read_obs_jsonl(path: str | Path) -> list[ObsFrameWindow]:
    """Opt-in local OBS metadata only; fail on oversized/unexpected fields."""
    source = Path(path)
    if source.stat().st_size > 2_000_000:
        raise ValueError("OBS benchmark metadata exceeds 2 MB")
    windows: list[ObsFrameWindow] = []
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            if len(line) > 4096 or len(windows) >= 1000:
                raise ValueError("OBS benchmark has too many or oversized records")
            windows.append(ObsFrameWindow.from_dict(json.loads(line)))
    return windows


def main() -> None:
    import argparse
    from .stream_realtime_benchmark import read_jsonl

    parser = argparse.ArgumentParser(
        description="Offline paired voice/game/OBS audit; makes NO streaming changes"
    )
    parser.add_argument("realtime_jsonl", help="existing paired RealtimeRun JSONL")
    parser.add_argument("obs_jsonl", help="paired counter-window JSONL from trusted host")
    parser.add_argument("--gpu-budget-mib", type=float, default=6656)
    args = parser.parse_args()
    result = compare_realtime_with_obs(
        read_jsonl(args.realtime_jsonl), read_obs_jsonl(args.obs_jsonl),
        gpu_budget_mib=args.gpu_budget_mib,
    )
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = [
    "ObsStatsCounters", "ObsFrameWindow", "ObsQoSReport",
    "compare_realtime_with_obs", "read_obs_jsonl",
]
