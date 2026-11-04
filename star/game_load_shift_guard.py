"""Read-only latency drift audit for Star's real-time game/VTuber rehearsal.

Compares *successive* measured host windows, not synthetic score estimates or
paired A/B model evaluations.  The host should sample all attempts, including
timeouts; missing dispatch must never disappear from a successful-window p95.

No sockets, game input, model inference, OBS control, or streaming permissions.
The "independently_measured" field is a host assertion, NOT authentication.
A stable window cannot make a synthetic practice correction safe for live use.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import math
from pathlib import Path
import re
from typing import Iterable, cast

_PROFILE_SET = frozenset({"idle", "stream_live", "heavy_contention"})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_MAX_ROWS = 200


def _bounded(value: object, label: str, upper: float, *, positive: bool = False) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label}: numeric host measurement required")
    try:
        number = float(cast(float | int, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label}: measurement overflow") from exc
    if not math.isfinite(number) or not (0 < number if positive else 0 <= number) or number > upper:
        raise ValueError(f"{label}: out of allowed range")
    return number


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label}: opaque ID required")
    return value


def _p95(numbers: list[float]) -> float:
    if not numbers:
        raise ValueError("cannot compute p95 without observations")
    return sorted(numbers)[math.ceil(.95 * len(numbers)) - 1]


@dataclass(frozen=True)
class GameLoadSample:
    """One permitted host observation, with no images, chat or player IDs.

    Latencies are measured on one monotonic clock.  An absent input ack is a
    failed attempted dispatch, not a zero-latency observation.  The OBS skip
    percentage is the host-calculated interval delta from GetStats counters,
    never an unconstrained rolling total.  A callback alone is not proof that
    game input was consumed, or that the world advanced.
    """

    episode_id: str
    host_session_id: str
    game_scope: str
    profile: str
    observed_at_ms: float
    capture_to_ack_ms: float | None
    inference_ms: float
    dispatch_ms: float | None
    game_p99_frame_ms: float
    obs_skipped_pct: float
    gpu_free_mib: int
    independently_measured: bool

    def __post_init__(self) -> None:
        for key in ("episode_id", "host_session_id", "game_scope"):
            _id(getattr(self, key), key)
        if type(self.profile) is not str or self.profile not in _PROFILE_SET:
            raise ValueError("unregistered hardware workload profile")
        _bounded(self.observed_at_ms, "observed_at_ms", 1e13)
        _bounded(self.inference_ms, "inference_ms", 60000, positive=True)
        _bounded(self.game_p99_frame_ms, "game_p99_frame_ms", 10000, positive=True)
        _bounded(self.obs_skipped_pct, "obs_skipped_pct", 100)
        if type(self.gpu_free_mib) is not int or not 0 <= self.gpu_free_mib <= 1_048_576:
            raise ValueError("invalid GPU headroom")
        if type(self.independently_measured) is not bool:
            raise ValueError("independent evidence flag must be bool")
        if self.capture_to_ack_ms is None:
            if self.dispatch_ms is not None:
                raise ValueError("missing input ack cannot report dispatch latency")
        else:
            end = _bounded(self.capture_to_ack_ms, "capture_to_ack_ms", 60000, positive=True)
            if self.dispatch_ms is None:
                raise ValueError("acknowledged input requires measured dispatch")
            dispatched = _bounded(self.dispatch_ms, "dispatch_ms", 60000)
            if end + 0.001 < self.inference_ms + dispatched:
                raise ValueError("end-to-end measurement shorter than included stages")

    @classmethod
    def from_dict(cls, raw: object) -> GameLoadSample:
        if type(raw) is not dict or set(raw) != {field.name for field in fields(cls)}:
            raise ValueError("unrecognized or incomplete host schema")
        return cls(**raw)


@dataclass(frozen=True)
class GameLoadDriftReport:
    """Aggregated advisory.  Neither data nor verdict authenticates a host."""

    status: str
    reasons: tuple[str, ...]
    baseline_count: int
    current_count: int
    profile: str | None
    baseline_p95_ms: float | None
    current_p95_ms: float | None
    missed_input_acks: int
    min_gpu_free_mib: int | None
    candidate_for_manual_rehearsal: bool = False
    authorizes_real_gameplay: bool = False
    authorizes_skill_promotion: bool = False
    authorizes_broadcast: bool = False
    note: str = (
        "Host-asserted passive metrics; no cryptographic authentication, "
        "gameplay-skill proof, model improvement, control or broadcast permission."
    )

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def assess_game_load_shift(
    baseline: Iterable[GameLoadSample],
    current: Iterable[GameLoadSample], *,
    now_ms: float, minimum_per_window: int = 20,
    max_fresh_age_ms: float = 5000, max_between_windows_ms: float = 1_200_000,
    max_p95_regression_ms: float = 25,
    max_single_latency_regression_ms: float = 100,
    max_frame_regression_ms: float = 8,
    max_obs_regression_pct: float = .5,
    gpu_reserve_mib: int = 1536,
) -> GameLoadDriftReport:
    """Require stable, fresh, independent temporal windows; fail conservatively.

    A baseline is an earlier sample window on the *same verified host/session*
    and profile.  This does not compare two different model configurations,
    evaluate gameplay success, or authorize use of synthetic LoadPolicy hints.
    """
    now = _bounded(now_ms, "now_ms", 1e13)
    if type(minimum_per_window) is not int or not 10 <= minimum_per_window <= 200:
        raise ValueError("invalid minimum window size")
    for label, value, bound in (
        ("max_fresh_age_ms", max_fresh_age_ms, 60000),
        ("max_between_windows_ms", max_between_windows_ms, 3_600_000),
        ("max_p95_regression_ms", max_p95_regression_ms, 1000),
        ("max_single_latency_regression_ms", max_single_latency_regression_ms, 5000),
        ("max_frame_regression_ms", max_frame_regression_ms, 100),
        ("max_obs_regression_pct", max_obs_regression_pct, 10),
    ):
        _bounded(value, label, bound, positive=True)
    if type(gpu_reserve_mib) is not int or not 512 <= gpu_reserve_mib <= 16384:
        raise ValueError("invalid GPU reserve")

    # Bounded materialization: refuse endlessly generated or partial evidence.
    def take(rows: Iterable[GameLoadSample]) -> tuple[GameLoadSample, ...]:
        output: list[GameLoadSample] = []
        for item in rows:
            if len(output) >= _MAX_ROWS:
                raise ValueError("host window too large")
            if type(item) is not GameLoadSample:
                raise TypeError("structured GameLoadSample required")
            output.append(item)
        return tuple(output)

    before, after = take(baseline), take(current)
    problems: list[str] = []
    if len(before) < minimum_per_window or len(after) < minimum_per_window:
        problems.append("insufficient_samples")
    combined = before + after
    unique = {r.episode_id for r in combined}
    if len(unique) != len(combined):
        problems.append("repeated_episode_id")
    scopes = {(r.host_session_id, r.game_scope, r.profile) for r in combined}
    if len(scopes) != 1:
        problems.append("changed_host_game_or_load_profile")
    if any(not r.independently_measured for r in combined):
        problems.append("untrusted_host_evidence")
    for window in (before, after):
        if any(right.observed_at_ms <= left.observed_at_ms
               for left, right in zip(window, window[1:])):
            problems.append("out_of_order_or_duplicate_clock")
        if len(window) >= 2 and any(right.observed_at_ms - left.observed_at_ms > 15000
                                    for left, right in zip(window, window[1:])):
            problems.append("gapped_host_sampling")
    if before and after:
        if after[0].observed_at_ms <= before[-1].observed_at_ms:
            problems.append("overlapping_or_reversed_windows")
        elif after[0].observed_at_ms - before[-1].observed_at_ms > max_between_windows_ms:
            problems.append("stale_baseline_window")
    if after and (after[-1].observed_at_ms > now
                  or now - after[-1].observed_at_ms > max_fresh_age_ms):
        problems.append("stale_or_future_current_window")
    elif not after:
        problems.append("missing_current_window")
    if not before:
        problems.append("missing_baseline_window")

    profile = next(iter(scopes))[2] if len(scopes) == 1 else None
    missed = sum(r.capture_to_ack_ms is None for r in after)
    min_free = min((r.gpu_free_mib for r in after), default=None)
    valid_before = [float(r.capture_to_ack_ms) for r in before
                    if r.capture_to_ack_ms is not None]
    valid_after = [float(r.capture_to_ack_ms) for r in after
                   if r.capture_to_ack_ms is not None]
    before_p95 = _p95(valid_before) if valid_before else None
    after_p95 = _p95(valid_after) if valid_after else None
    if problems:
        status = "inconclusive"
    else:
        if missed or len(valid_before) != len(before):
            problems.append("missing_input_ack")
        if before_p95 is None or after_p95 is None:
            problems.append("no_latency_distribution")
        elif after_p95 > before_p95 + max_p95_regression_ms:
            problems.append("capture_to_input_latency_regression")
        # A single emergency-stop-level stall can fall outside p95.
        if (valid_before and valid_after and
                max(valid_after) > max(valid_before) + max_single_latency_regression_ms):
            problems.append("single_action_latency_spike")
        if (max(r.game_p99_frame_ms for r in after)
                > max(r.game_p99_frame_ms for r in before) + max_frame_regression_ms):
            problems.append("game_frame_stall_regression")
        if (max(r.obs_skipped_pct for r in after)
                > max(r.obs_skipped_pct for r in before) + max_obs_regression_pct):
            problems.append("obs_frame_skip_regression")
        if min_free is not None and min_free < gpu_reserve_mib:
            problems.append("gpu_headroom_exhausted")
        status = "degraded" if problems else "stable_observation"

    return GameLoadDriftReport(
        status=status, reasons=tuple(dict.fromkeys(problems)),
        baseline_count=len(before), current_count=len(after), profile=profile,
        baseline_p95_ms=round(before_p95, 3) if before_p95 is not None else None,
        current_p95_ms=round(after_p95, 3) if after_p95 is not None else None,
        missed_input_acks=missed, min_gpu_free_mib=min_free,
    )


def read_host_jsonl(path: str | Path) -> tuple[GameLoadSample, ...]:
    """Parse a small, allowlisted local trace without persisting raw input."""
    file = Path(path)
    if file.stat().st_size > 400_000:
        raise ValueError("host trace exceeds 400kB")
    output: list[GameLoadSample] = []

    def unique_fields(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate host JSON field")
            result[key] = value
        return result

    with file.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            if len(line) > 4096 or len(output) >= _MAX_ROWS:
                raise ValueError("oversized host sample")
            output.append(GameLoadSample.from_dict(
                json.loads(line, object_pairs_hook=unique_fields),
            ))
    return tuple(output)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Passive, offline Star game/OBS latency drift audit")
    parser.add_argument("baseline_jsonl", type=Path)
    parser.add_argument("current_jsonl", type=Path)
    parser.add_argument("--now-ms", type=float, required=True,
                        help="same trusted host monotonic clock as the traces")
    args = parser.parse_args()
    print(assess_game_load_shift(
        read_host_jsonl(args.baseline_jsonl),
        read_host_jsonl(args.current_jsonl),
        now_ms=args.now_ms,
    ).to_json())


if __name__ == "__main__":
    main()
