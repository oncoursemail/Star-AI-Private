"""Read-only transport-health veto for paired voice + Roblox + OBS experiments.

GetStats tracks OBS rendering/output-thread frame health. GetStreamStatus
tracks the stream output's delivered and skipped frames, connection state,
and bytes. These are DISTINCT counters and must not be substituted.

A trusted host precommits pair IDs, captures before/after snapshots in the
same OBS process, and watches reconnect transitions between the snapshots.
This offline module neither authenticates that host nor contacts OBS, changes
configuration, chooses models, or starts a stream. A successful verdict grants
only eligibility for a human-supervised pilot.
"""
from __future__ import annotations

from typing import cast

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

from .stream_obs_qos_gate import ObsFrameWindow, ObsQoSReport, compare_realtime_with_obs
from .stream_realtime_benchmark import RealtimeRun

_MAX_COUNTER = (1 << 53) - 1
_FIELDS = frozenset({
    "pair_id", "variant", "game_id", "game_version", "session_id",
    "start_ms", "end_ms", "before", "after", "reconnect_observed",
})
_STATUS_FIELDS = frozenset({
    "outputActive", "outputReconnecting", "outputDuration", "outputBytes",
    "outputSkippedFrames", "outputTotalFrames", "outputCongestion",
})


def _uint(value: object, name: str) -> int:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be an unsigned integer")
    try:
        value_float = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} is outside the precise integer range") from exc
    if not math.isfinite(value_float) or not 0 <= value_float <= _MAX_COUNTER:
        raise ValueError(f"{name} is outside the precise integer range")
    if int(value_float) != value:
        raise ValueError(f"{name} must be integral")
    return int(cast(int | float, value))


def _finite(value: object, name: str, *, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    try:
        amount = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} is outside the supported range") from exc
    if not math.isfinite(amount) or not 0 <= amount <= maximum:
        raise ValueError(f"{name} is outside the supported range")
    return amount


@dataclass(frozen=True)
class ObsStreamStatus:
    """Allowlisted fields from OBS WebSocket 5.x GetStreamStatus.

    Congestion is stored only as a diagnostic number: OBS does not specify
    a portable normalized range for it, so this evaluator does NOT assume
    that it represents a percentage. Null is not a healthy observation.
    """

    active: bool
    reconnecting: bool
    duration_ms: float
    bytes_sent: int
    skipped_frames: int
    total_frames: int
    congestion: float

    def __post_init__(self) -> None:
        if type(self.active) is not bool or type(self.reconnecting) is not bool:
            raise ValueError("stream status requires OBS booleans")
        object.__setattr__(self, "duration_ms",
                           _finite(self.duration_ms, "duration_ms", maximum=1e13))
        for name in ("bytes_sent", "skipped_frames", "total_frames"):
            object.__setattr__(self, name, _uint(getattr(self, name), name))
        object.__setattr__(self, "congestion",
                           _finite(self.congestion, "congestion", maximum=100))
        if self.skipped_frames > self.total_frames:
            raise ValueError("skipped stream frames exceed output frames")

    @classmethod
    def from_getstreamstatus(cls, raw: object) -> ObsStreamStatus:
        if not isinstance(raw, Mapping) or not _STATUS_FIELDS.issubset(raw):
            raise ValueError("GetStreamStatus missing required transport counters")
        # Do not retain outputTimecode, tokens, URLs, IDs or arbitrary host data.
        return cls(
            active=raw["outputActive"],
            reconnecting=raw["outputReconnecting"],
            duration_ms=raw["outputDuration"],
            bytes_sent=raw["outputBytes"],
            skipped_frames=raw["outputSkippedFrames"],
            total_frames=raw["outputTotalFrames"],
            congestion=raw["outputCongestion"],
        )


@dataclass(frozen=True)
class ObsTransportWindow:
    """A host-monotonic observation window, scoped to a precommitted run."""

    pair_id: str
    variant: str
    game_id: str
    game_version: str
    session_id: str
    start_ms: float
    end_ms: float
    before: ObsStreamStatus
    after: ObsStreamStatus
    reconnect_observed: bool

    def __post_init__(self) -> None:
        # Reuse exact conservative identity and clock constraints from the
        # already validated GetStats window, without mixing the two counters.
        from .stream_obs_qos_gate import _id
        for name in ("pair_id", "game_id", "game_version", "session_id"):
            _id(getattr(self, name), name)
        if self.variant not in ("baseline", "candidate"):
            raise ValueError("invalid transport benchmark variant")
        before = _finite(self.start_ms, "start_ms", maximum=1e13)
        after = _finite(self.end_ms, "end_ms", maximum=1e13)
        if not 2000 <= after - before <= 600_000:
            raise ValueError("transport interval must be 2 seconds to 10 minutes")
        if type(self.before) is not ObsStreamStatus or type(self.after) is not ObsStreamStatus:
            raise TypeError("transport window requires GetStreamStatus snapshots")
        if type(self.reconnect_observed) is not bool:
            raise ValueError("reconnect_observed must be a host boolean")
        for name in ("duration_ms", "bytes_sent", "skipped_frames", "total_frames"):
            if getattr(self.after, name) < getattr(self.before, name):
                raise ValueError(f"GetStreamStatus {name} reset within a window")
        if self.total_frames < 120:
            raise ValueError("too few stream output frames for a representative window")
        if self.skipped_frames > self.total_frames:
            raise ValueError("stream skipped-frame delta exceeds delivered frames")

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms

    @property
    def output_duration_ms(self) -> float:
        return self.after.duration_ms - self.before.duration_ms

    @property
    def total_frames(self) -> int:
        return self.after.total_frames - self.before.total_frames

    @property
    def skipped_frames(self) -> int:
        return self.after.skipped_frames - self.before.skipped_frames

    @property
    def bytes_sent(self) -> int:
        return self.after.bytes_sent - self.before.bytes_sent

    @property
    def connected(self) -> bool:
        return (
            self.before.active and self.after.active
            and not self.before.reconnecting and not self.after.reconnecting
            and not self.reconnect_observed and self.bytes_sent > 0
            # An active output should advance for most of the observation.
            and self.output_duration_ms >= 0.8 * self.duration_ms
        )

    @classmethod
    def from_dict(cls, row: object) -> ObsTransportWindow:
        if type(row) is not dict or set(row) != _FIELDS:
            raise ValueError("transport JSONL must have exactly ten allowlisted fields")
        args = dict(row)
        args["before"] = ObsStreamStatus.from_getstreamstatus(args["before"])
        args["after"] = ObsStreamStatus.from_getstreamstatus(args["after"])
        return cls(**args)


@dataclass(frozen=True)
class ObsTransportReport:
    verdict: str
    frame_and_game_verdict: str
    matched_windows: int
    missing_windows: int
    candidate_network_skipped_pct: float | None
    network_skip_increase_pp: float | None
    worst_candidate_network_skipped_pct: float | None
    candidate_disrupted_windows: int
    note: str = ("host-attested, offline transport audit; skipped stream frames "
                 "are not the same as network packet loss; no automatic promotion")


def compare_realtime_obs_transport(
    runs: Sequence[RealtimeRun],
    frame_windows: Sequence[ObsFrameWindow],
    transport_windows: Sequence[ObsTransportWindow],
    *,
    minimum_pairs: int = 20,
    gpu_budget_mib: float = 6656,
    max_skipped_pct: float = 0.5,
    max_increase_pp: float = 0.2,
    max_worst_window_pct: float = 1.0,
) -> ObsTransportReport:
    """Veto a 'faster' setup if OBS's NETWORK stream output deteriorates.

    Preserve all existing TTFA, game FPS, memory and rendering gates.
    Invalid/missing baseline data is INCONCLUSIVE, never a favorable result.
    A candidate disruption is REGRESSED. Network metrics cannot override a
    rejected original benchmark. Exposed as advisory evidence only.
    """
    if type(runs) not in (list, tuple) or type(frame_windows) not in (list, tuple):
        raise TypeError("expected bounded materialized realtime/OBS observations")
    if type(transport_windows) not in (list, tuple) or len(transport_windows) > 1000:
        raise TypeError("expected at most 1000 materialized transport observations")
    for label, value, bound in (
        ("max_skipped_pct", max_skipped_pct, 5),
        ("max_increase_pp", max_increase_pp, 3),
        ("max_worst_window_pct", max_worst_window_pct, 10),
    ):
        if _finite(value, label, maximum=100) > bound:
            raise ValueError(f"{label} exceeds the conservative allowed bound")
    base: ObsQoSReport = compare_realtime_with_obs(
        runs, frame_windows,
        minimum_pairs=minimum_pairs, gpu_budget_mib=gpu_budget_mib,
    )
    run_by_key = {(r.pair_id, r.variant): r for r in runs}
    frame_by_key = {(r.pair_id, r.variant): r for r in frame_windows}
    transport: dict[tuple[str, str], ObsTransportWindow] = {}
    for row in transport_windows:
        if type(row) is not ObsTransportWindow:
            raise TypeError("expected validated GetStreamStatus transport window")
        key = (row.pair_id, row.variant)
        if key not in run_by_key:
            raise ValueError("transport window does not match precommitted run")
        if key in transport:
            raise ValueError("duplicate transport window cannot be cherry-picked")
        run = run_by_key[key]
        if (row.game_id, row.game_version) != (run.game_id, run.game_version):
            raise ValueError("transport and game/version scopes differ")
        if key in frame_by_key:
            frame = frame_by_key[key]
            if row.session_id != frame.session_id:
                raise ValueError("OBS process session differs between snapshots")
            # Snapshots must span substantially the same interval. Host clock
            # is common; these bounds allow polling jitter, not separate runs.
            tolerance = max(1000.0, 0.1 * frame.duration_ms)
            if (abs(row.start_ms - frame.start_ms) > tolerance
                    or abs(row.end_ms - frame.end_ms) > tolerance):
                raise ValueError("GetStats and GetStreamStatus intervals do not match")
        transport[key] = row

    missing = len(run_by_key) - len(transport)
    def report(verdict: str, matched: int, disrupted: int = 0,
               skipped: float | None = None, drift: float | None = None,
               worst: float | None = None) -> ObsTransportReport:
        return ObsTransportReport(verdict, base.verdict, matched, missing,
                                  skipped, drift, worst, disrupted)
    if missing or not run_by_key or base.missing_windows:
        verdict = "regressed" if base.verdict == "regressed" else "inconclusive"
        return report(verdict, len(transport) // 2)

    pairs: dict[str, dict[str, ObsTransportWindow]] = {}
    for row in transport.values():
        pairs.setdefault(row.pair_id, {})[row.variant] = row
    baseline, candidate = [], []
    for pair in pairs.values():
        if set(pair) != {"baseline", "candidate"}:
            return report("inconclusive", len(pairs))
        b, c = pair["baseline"], pair["candidate"]
        if abs(b.duration_ms - c.duration_ms) > 0.2 * max(b.duration_ms, c.duration_ms):
            raise ValueError("unfair paired transport exposure durations")
        baseline.append(b)
        candidate.append(c)

    def rate(windows: list[ObsTransportWindow]) -> float:
        return 100.0 * sum(x.skipped_frames for x in windows) / sum(
            x.total_frames for x in windows
        )

    if not all(row.connected for row in baseline):
        return report("regressed" if base.verdict == "regressed" else "inconclusive",
                      len(pairs))
    b_rate = rate(baseline)
    c_rate = rate(candidate)
    drift = c_rate - b_rate
    worst = max(100.0 * row.skipped_frames / row.total_frames for row in candidate)
    disrupted = sum(not x.connected for x in candidate)
    bad = (disrupted > 0 or c_rate > max_skipped_pct
           or drift > max_increase_pp or worst > max_worst_window_pct)
    final = (
        "regressed" if bad or base.verdict == "regressed" else
        "eligible_for_manual_pilot" if base.verdict == "eligible_for_manual_pilot"
        else "inconclusive"
    )
    return report(final, len(pairs), disrupted,
                  round(c_rate, 4), round(drift, 4), round(worst, 4))


def read_transport_jsonl(path: str | Path) -> list[ObsTransportWindow]:
    """Local metadata only; rejects accidental private fields and large files."""
    source = Path(path)
    if source.stat().st_size > 2_000_000:
        raise ValueError("transport metadata exceeds 2 MB")
    result: list[ObsTransportWindow] = []
    with source.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                if len(line) > 4096 or len(result) >= 1000:
                    raise ValueError("oversized or excessive transport metadata")
                result.append(ObsTransportWindow.from_dict(json.loads(line)))
    return result


def main() -> None:
    import argparse
    from dataclasses import asdict

    from .stream_obs_qos_gate import read_obs_jsonl
    from .stream_realtime_benchmark import read_jsonl

    parser = argparse.ArgumentParser(
        description="Offline TTFA/Roblox FPS/OBS render/network transport audit"
    )
    parser.add_argument("realtime_jsonl")
    parser.add_argument("obs_getstats_jsonl")
    parser.add_argument("obs_getstreamstatus_jsonl")
    parser.add_argument("--gpu-budget-mib", type=float, default=6656)
    args = parser.parse_args()
    print(json.dumps(asdict(compare_realtime_obs_transport(
        read_jsonl(args.realtime_jsonl), read_obs_jsonl(args.obs_getstats_jsonl),
        read_transport_jsonl(args.obs_getstreamstatus_jsonl),
        gpu_budget_mib=args.gpu_budget_mib,
    )), sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = [
    "ObsStreamStatus", "ObsTransportWindow", "ObsTransportReport",
    "compare_realtime_obs_transport", "read_transport_jsonl",
]
