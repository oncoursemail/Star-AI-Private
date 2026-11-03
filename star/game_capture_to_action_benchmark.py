"""Offline capture-to-input gameplay benchmark, including real-world clock costs.

The November 1, 2026 GameScaling evaluation correction illustrates why model
decode latency is not an end-to-end real-time measurement. This analyzer uses
trusted, same-host monotonically timestamped capture, transfer, preprocess,
inference and OS input acknowledgement markers. World progression is sampled
from an independently advancing game clock. No game I/O, signing or promotion.
Host-reported booleans and world frames are NOT cryptographic authentication.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import re
from typing import Iterable, cast

_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MAX_RECORDS = 1000


def _number(item: object, name: str, high: float) -> float:
    if type(item) not in (float, int):
        raise ValueError(f"{name}: expected finite host metric")
    try:
        value = float(cast(float | int, item))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name}: numeric overflow") from exc
    if not math.isfinite(value) or not 0 <= value <= high:
        raise ValueError(f"{name}: out of bounds")
    return value


def _identifier(item: object, name: str) -> str:
    if type(item) is not str or _ID.fullmatch(item) is None:
        raise ValueError(f"{name}: invalid opaque identifier")
    return item


def _p95(items: list[float]) -> float | None:
    if not items:
        return None
    return round(sorted(items)[math.ceil(len(items) * .95) - 1], 3)


def _lower_ci(diffs: list[float]) -> float | None:
    if not diffs:
        return None
    rng = random.Random(int.from_bytes(sha256(b"star.fullpath.v1").digest()[:8], "big"))
    n = len(diffs)
    estimates = sorted(
        sum(diffs[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(1600)
    )
    return round(estimates[39], 4)


@dataclass(frozen=True)
class CaptureToActionTrial:
    """Host measurements for a separately reset paired game attempt.

    All times originate from one monotonic host clock, in milliseconds.
    world_frame_* are *independently sampled engine frames*, not screenshot
    counts. Every field is a restricted metric; no screenshots, audio or
    player information is accepted. Validated input is NOT verified input.
    """

    pair_id: str
    variant: str
    episode_id: str
    game_id: str
    game_version: str
    scenario_id: str
    initial_state_sha256: str
    capture_start_ms: float
    capture_end_ms: float
    transfer_end_ms: float
    preprocess_end_ms: float
    inference_end_ms: float
    input_ack_ms: float | None
    scene_deadline_ms: float
    world_frame_at_capture: int
    world_frame_at_preprocess: int
    world_frame_at_inference: int
    world_frame_at_ack: int | None
    nominal_world_fps: float
    progress_before: float
    progress_after: float
    objective_success: bool
    game_p99_frame_ms: float
    obs_dropped_pct: float
    independently_measured: bool

    def __post_init__(self) -> None:
        for name in ("pair_id", "episode_id", "game_id", "game_version", "scenario_id"):
            _identifier(getattr(self, name), name)
        if type(self.variant) is not str or self.variant not in ("baseline", "candidate"):
            raise ValueError("invalid variant")
        if type(self.initial_state_sha256) is not str or _SHA.fullmatch(self.initial_state_sha256) is None:
            raise ValueError("invalid starting-state fingerprint")
        for name in ("objective_success", "independently_measured"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"invalid {name} flag")
        times = ("capture_start_ms", "capture_end_ms", "transfer_end_ms",
                 "preprocess_end_ms", "inference_end_ms")
        stamps = [_number(getattr(self, name), name, 1e13) for name in times]
        if not (stamps[0] < stamps[1] <= stamps[2] <= stamps[3] < stamps[4]):
            raise ValueError("capture-to-inference stage order invalid")
        deadline = _number(self.scene_deadline_ms, "scene_deadline_ms", 1e13)
        if not stamps[0] < deadline <= stamps[0] + 60_000:
            raise ValueError("invalid scene deadline")
        for name in ("world_frame_at_capture", "world_frame_at_preprocess",
                     "world_frame_at_inference"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 10**12:
                raise ValueError("invalid game world frame")
        if not (self.world_frame_at_capture <= self.world_frame_at_preprocess
                <= self.world_frame_at_inference):
            raise ValueError("game world frames must be monotonic")
        _number(self.nominal_world_fps, "nominal_world_fps", 240)
        if not 10 <= self.nominal_world_fps <= 240:
            raise ValueError("world FPS must be 10..240")
        if self.input_ack_ms is None:
            if self.world_frame_at_ack is not None:
                raise ValueError("unacknowledged input must not have an acknowledged world frame")
        else:
            ack = _number(self.input_ack_ms, "input_ack_ms", 1e13)
            if ack < stamps[4] or ack - stamps[0] > 60_000:
                raise ValueError("invalid input ack")
            if (type(self.world_frame_at_ack) is not int
                    or not self.world_frame_at_inference <= self.world_frame_at_ack <= 10**12):
                raise ValueError("trusted world frame must not reverse at ack")
        _number(self.progress_before, "progress_before", 1)
        _number(self.progress_after, "progress_after", 1)
        _number(self.game_p99_frame_ms, "game_p99_frame_ms", 10_000)
        _number(self.obs_dropped_pct, "obs_dropped_pct", 100)

    @classmethod
    def from_dict(cls, row: object) -> CaptureToActionTrial:
        if type(row) is not dict or set(row) != {field.name for field in fields(cls)}:
            raise ValueError("bounded host metrics schema required")
        return cls(**row)

    @property
    def end_to_end_ms(self) -> float | None:
        return None if self.input_ack_ms is None else self.input_ack_ms - self.capture_start_ms

    @property
    def timely_success(self) -> bool:
        return (self.input_ack_ms is not None
                and self.input_ack_ms <= self.scene_deadline_ms
                and self.objective_success)

    @property
    def world_kept_running(self) -> bool:
        """Reject a pause hidden during screenshot/transfer/preprocessing.

        Frames must advance relative to the entire capture-to-ack wall period,
        not merely the model-inference window. Approximate tolerance accounts
        for frame rounding/simulation slowdown, not for a dishonest host.
        """
        if self.input_ack_ms is None or self.world_frame_at_ack is None:
            return False
        stages = (
            (self.capture_start_ms, self.preprocess_end_ms,
             self.world_frame_at_capture, self.world_frame_at_preprocess),
            (self.preprocess_end_ms, self.inference_end_ms,
             self.world_frame_at_preprocess, self.world_frame_at_inference),
            (self.inference_end_ms, self.input_ack_ms,
             self.world_frame_at_inference, self.world_frame_at_ack),
            (self.capture_start_ms, self.input_ack_ms,
             self.world_frame_at_capture, self.world_frame_at_ack),
        )
        # Check each interval separately: a paused capture cannot be hidden
        # by artificially accelerating the world during later inference.
        for beginning, end, frame_start, frame_end in stages:
            elapsed = end - beginning
            observed = frame_end - frame_start
            expected = elapsed * self.nominal_world_fps / 1000
            if (observed < .60 * expected - 1
                    or observed > 1.50 * expected + 2
                    or (elapsed >= 30 and observed < 1)):
                return False
        return True

    def stage_durations(self) -> dict[str, float]:
        if self.input_ack_ms is None:
            return {}
        return {
            "capture": self.capture_end_ms - self.capture_start_ms,
            "transfer": self.transfer_end_ms - self.capture_end_ms,
            "preprocess": self.preprocess_end_ms - self.transfer_end_ms,
            "inference": self.inference_end_ms - self.preprocess_end_ms,
            "dispatch": self.input_ack_ms - self.inference_end_ms,
        }


@dataclass(frozen=True)
class CaptureToActionReport:
    verdict: str
    paired: int
    incomplete: int
    unverified: int
    non_live: int
    candidate_late_or_missing: int
    candidate_new_failures: int
    qos_regressions: int
    baseline_p95_ms: float | None
    candidate_p95_ms: float | None
    latency_gain_ci95_lower_ms: float | None
    candidate_stage_p95_ms: dict[str, float]
    progress_gain_ci95_lower: float | None = None
    authorized_to_act: bool = False
    note: str = (
        "Offline metrics only. No source authentication, no inference speed "
        "claim, no autonomous deployment, no permission to control games or stream."
    )


def compare_capture_to_action(
    records: Iterable[CaptureToActionTrial], *, minimum_pairs: int = 20,
    max_frame_regression_ms: float = 8, max_obs_dropped_regression_pct: float = 0.5,
) -> CaptureToActionReport:
    if type(minimum_pairs) is not int or not 10 <= minimum_pairs <= 500:
        raise ValueError("minimum_pairs must be 10..500")
    _number(max_frame_regression_ms, "max_frame_regression_ms", 100)
    _number(max_obs_dropped_regression_pct, "max_obs_dropped_regression_pct", 10)
    pairs: dict[str, dict[str, CaptureToActionTrial]] = {}
    episodes: set[str] = set()
    scope: tuple[str, str] | None = None
    for count, rec in enumerate(records, start=1):
        if count > _MAX_RECORDS:
            raise ValueError("too many records")
        if type(rec) is not CaptureToActionTrial:
            raise TypeError("CaptureToActionTrial required")
        current = (rec.game_id, rec.game_version)
        if scope is None:
            scope = current
        elif current != scope:
            raise ValueError("cannot pool unrelated game/version")
        if rec.episode_id in episodes:
            raise ValueError("episode replay: independent reset required")
        episodes.add(rec.episode_id)
        pair = pairs.setdefault(rec.pair_id, {})
        if rec.variant in pair:
            raise ValueError("duplicate variant: no cherry picking")
        pair[rec.variant] = rec
    matched = [p for p in pairs.values() if len(p) == 2]
    incomplete = len(pairs) - len(matched)
    for pair in matched:
        b, c = pair["baseline"], pair["candidate"]
        if (b.scenario_id != c.scenario_id
                or b.initial_state_sha256 != c.initial_state_sha256
                or abs(b.progress_before - c.progress_before) > .001
                or abs((b.scene_deadline_ms - b.capture_start_ms)
                       - (c.scene_deadline_ms - c.capture_start_ms)) > 1
                or b.nominal_world_fps != c.nominal_world_fps):
            raise ValueError("paired baseline/candidate must share reset state, deadline, world rate")
    unverified = sum(
        not pair["baseline"].independently_measured
        or not pair["candidate"].independently_measured
        for pair in matched
    )
    non_live = sum(
        not pair["baseline"].world_kept_running
        or not pair["candidate"].world_kept_running
        for pair in matched
    )
    # Count missing inputs, new losses and QoS degradation even in sessions
    # excluded from performance analysis due to a stopped game clock.
    # Otherwise a failed candidate can disappear from the reported failures.
    trusted = [
        pair for pair in matched
        if all(r.independently_measured for r in pair.values())
    ]
    late = sum(
        pair["candidate"].input_ack_ms is None
        or pair["candidate"].input_ack_ms > pair["candidate"].scene_deadline_ms
        for pair in trusted
    )
    baseline_late = sum(
        pair["baseline"].input_ack_ms is None
        or pair["baseline"].input_ack_ms > pair["baseline"].scene_deadline_ms
        for pair in trusted
    )
    new_failures = sum(
        pair["baseline"].timely_success and not pair["candidate"].timely_success
        for pair in trusted
    )
    qos = sum(
        pair["candidate"].game_p99_frame_ms - pair["baseline"].game_p99_frame_ms
        > max_frame_regression_ms
        or pair["candidate"].obs_dropped_pct - pair["baseline"].obs_dropped_pct
        > max_obs_dropped_regression_pct
        for pair in trusted
    )
    regressed = new_failures > 0 or qos > 0 or late > baseline_late
    valid = [
        pair for pair in trusted
        if all(r.world_kept_running for r in pair.values())
    ]
    if not valid:
        return CaptureToActionReport(
            "regressed" if regressed else "inconclusive",
            len(matched), incomplete, unverified, non_live, late,
            new_failures, qos, None, None, None, {},
        )
    baseline = [pair["baseline"] for pair in valid]
    candidate = [pair["candidate"] for pair in valid]
    b_times = [r.end_to_end_ms for r in baseline if r.end_to_end_ms is not None]
    c_times = [r.end_to_end_ms for r in candidate if r.end_to_end_ms is not None]
    paired_gain = [b.end_to_end_ms - c.end_to_end_ms for b, c in zip(baseline, candidate)
                   if b.end_to_end_ms is not None and c.end_to_end_ms is not None]
    base_p95 = _p95(b_times)
    cand_p95 = _p95(c_times)
    lower = _lower_ci(paired_gain)
    progress_gain = _lower_ci([
        (c.progress_after - c.progress_before)
        - (b.progress_after - b.progress_before)
        for b, c in zip(baseline, candidate)
    ])
    stages = {
        key: _p95([r.stage_durations()[key] for r in candidate if r.input_ack_ms is not None])
        for key in ("capture", "transfer", "preprocess", "inference", "dispatch")
    }
    regressed = (
        regressed or
        sum(c.timely_success for c in candidate)
        < sum(b.timely_success for b in baseline)
    )
    eligible = (
        not regressed and incomplete == unverified == non_live == 0
        and len(matched) >= minimum_pairs
        and len(paired_gain) == len(matched)
        and lower is not None and lower > 10
        and progress_gain is not None and progress_gain > .02
        and base_p95 is not None and cand_p95 is not None
        and cand_p95 < base_p95
        and sum(c.timely_success for c in candidate) > sum(b.timely_success for b in baseline)
    )
    return CaptureToActionReport(
        "regressed" if regressed else ("manual_pilot_candidate" if eligible else "inconclusive"),
        len(matched), incomplete, unverified, non_live, late, new_failures, qos,
        base_p95, cand_p95, lower, {k: v for k, v in stages.items() if v is not None},
        progress_gain_ci95_lower=progress_gain,
    )


def read_jsonl(path: str | Path) -> list[CaptureToActionTrial]:
    source = Path(path)
    if source.stat().st_size > 2_000_000:
        raise ValueError("input file exceeds 2 MB")
    output: list[CaptureToActionTrial] = []
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            if len(output) >= _MAX_RECORDS:
                raise ValueError("too many records")
            if not line.strip():
                continue
            if len(line) > 8192:
                raise ValueError("overlong host record")
            def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for k, value in pairs:
                    if k in result:
                        raise ValueError("duplicate host field")
                    result[k] = value
                return result
            output.append(CaptureToActionTrial.from_dict(
                json.loads(line, object_pairs_hook=unique_fields),
            ))
    return output


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Offline, host-reported capture-to-ack audit")
    parser.add_argument("jsonl", type=Path)
    args = parser.parse_args()
    print(json.dumps(asdict(compare_capture_to_action(read_jsonl(args.jsonl))),
                     sort_keys=True))


if __name__ == "__main__":
    main()
