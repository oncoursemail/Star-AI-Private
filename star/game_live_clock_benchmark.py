"""Independent, offline evaluation of real-time game *outcomes*, not token speed.

Paired baseline/candidate episodes must use a trusted host clock while the
game actually advances through inference AND input acknowledgment. Score is read from game state by an independent host,
not inferred from model text or screenshots. This module neither runs a game
nor certifies the host, controls keys, authorizes streaming, or promotes AI.
No personal, screen, speech, game-state or viewer contents are stored.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
import random
import re
from pathlib import Path
from typing import Iterable, cast

_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MAX_CLOCK = 1e13


def _id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded opaque identifier")
    return value


def _ms(value: object, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite host-clock millisecond value")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result) or not 0 <= result <= _MAX_CLOCK:
        raise ValueError(f"{name} must be in host-clock bounds")
    return result


def _ratio(value: object, name: str, upper: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be finite")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result) or not 0 <= result <= upper:
        raise ValueError(f"{name} must be between 0 and {upper}")
    return result


def _p95(samples: list[float]) -> float | None:
    if not samples:
        return None
    return round(sorted(samples)[math.ceil(len(samples) * .95) - 1], 3)


def _ci95(deltas: list[float]) -> tuple[float, float] | None:
    if not deltas:
        return None
    # Fixed seed permits reproducing evaluations across machines/runs.
    seed = int.from_bytes(hashlib.sha256(b"star.live-clock.v1").digest()[:8], "big")
    rng = random.Random(seed)
    n = len(deltas)
    estimates = sorted(
        sum(deltas[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(2000)
    )
    return round(estimates[49], 4), round(estimates[1949], 4)


@dataclass(frozen=True)
class LiveClockTrial:
    """One separately reset attempt, independently measured on a running game.

    Both variants within a pair must be recorded from the SAME initial game
    state but different episodes. The model must not choose scenario, ID,
    initial-state fingerprint, timing, or score. A boolean witness flag is
    metadata, NOT proof: the capture host must be independently trusted.
    """

    pair_id: str
    variant: str                         # baseline | candidate
    episode_id: str
    game_id: str
    game_version: str
    scenario_id: str
    initial_state_sha256: str
    observed_at_ms: float
    inference_started_ms: float
    inference_finished_ms: float
    input_ack_ms: float | None
    scene_deadline_ms: float
    world_advanced_ms: float              # host-observed world clock through inference
    world_advanced_to_input_ack_ms: float | None  # world clock through OS input ack
    progress_before: float
    progress_after: float
    objective_success: bool
    game_p99_frame_ms: float
    obs_dropped_pct: float
    independently_scored: bool

    def __post_init__(self) -> None:
        for name in ("pair_id", "episode_id", "game_id", "game_version", "scenario_id"):
            _id(getattr(self, name), name)
        if type(self.variant) is not str or self.variant not in ("baseline", "candidate"):
            raise ValueError("variant must be baseline or candidate")
        if type(self.initial_state_sha256) is not str or _SHA.fullmatch(self.initial_state_sha256) is None:
            raise ValueError("SHA-256 initial game state fingerprint required")
        for name in ("objective_success", "independently_scored"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        for name in ("observed_at_ms", "inference_started_ms",
                     "inference_finished_ms", "scene_deadline_ms"):
            _ms(getattr(self, name), name)
        if not (self.observed_at_ms <= self.inference_started_ms
                <= self.inference_finished_ms):
            raise ValueError("host observation/inference clock order invalid")
        if self.scene_deadline_ms <= self.observed_at_ms:
            raise ValueError("scene deadline must follow observation")
        if self.scene_deadline_ms - self.observed_at_ms > 60_000:
            raise ValueError("scene deadline cannot exceed 60 seconds")
        if self.input_ack_ms is not None:
            _ms(self.input_ack_ms, "input_ack_ms")
            if self.input_ack_ms < self.inference_finished_ms:
                raise ValueError("cannot confirm input before inference ends")
        _ms(self.world_advanced_ms, "world_advanced_ms")
        # The host must sample the *independent game-world* clock again at
        # input acknowledgment. Otherwise a game paused during dispatch can
        # falsely qualify as a continuously advancing real-time trial.
        if self.input_ack_ms is None:
            if self.world_advanced_to_input_ack_ms is not None:
                raise ValueError("world clock at input ack requires actual input ack")
        else:
            if self.world_advanced_to_input_ack_ms is None:
                raise ValueError("world clock at input ack is required")
            _ms(self.world_advanced_to_input_ack_ms, "world_advanced_to_input_ack_ms")
            if self.world_advanced_to_input_ack_ms < self.world_advanced_ms:
                raise ValueError("world clock cannot run backwards after inference")
        _ratio(self.progress_before, "progress_before", 1.0)
        _ratio(self.progress_after, "progress_after", 1.0)
        _ratio(self.game_p99_frame_ms, "game_p99_frame_ms", 10_000.0)
        _ratio(self.obs_dropped_pct, "obs_dropped_pct", 100.0)

    @classmethod
    def from_dict(cls, item: object) -> LiveClockTrial:
        if type(item) is not dict or set(item) != {field.name for field in fields(cls)}:
            raise ValueError("only the bounded, named host metrics are accepted")
        return cls(**item)

    @property
    def world_kept_running(self) -> bool:
        """Distinguish live-clock gaming from pause-during-inference tests.

        60% is an explicit tolerance for simulation slowdown. It is not
        evidence the host truthfully measured the game; only a host can
        prove the world clock was sampled from real game state.
        """
        inference_elapsed = self.inference_finished_ms - self.observed_at_ms
        inference_live = (
            inference_elapsed > 0
            and 0.60 * inference_elapsed <= self.world_advanced_ms
            <= 1.50 * inference_elapsed + 2
        )
        if not inference_live:
            return False
        if self.input_ack_ms is None:
            # A missing input is a failed attempt, not grounds to discard the
            # entire paired trial. Never count it as successful gameplay.
            return True
        # A continuous game must also advance while the host dispatches the
        # action. Checking only inference makes freeze-after-inference
        # experiments appear like better gameplay.
        assert self.world_advanced_to_input_ack_ms is not None
        until_ack = self.input_ack_ms - self.observed_at_ms
        cumulative = self.world_advanced_to_input_ack_ms
        if not 0.60 * until_ack <= cumulative <= 1.50 * until_ack + 2:
            return False
        dispatch_elapsed = self.input_ack_ms - self.inference_finished_ms
        dispatch_advanced = cumulative - self.world_advanced_ms
        return (
            0.60 * dispatch_elapsed <= dispatch_advanced
            <= 1.50 * dispatch_elapsed + 2
        )

    @property
    def timely_input(self) -> bool:
        return self.input_ack_ms is not None and self.input_ack_ms <= self.scene_deadline_ms

    @property
    def timely_success(self) -> bool:
        return self.timely_input and self.objective_success

    @property
    def response_ms(self) -> float | None:
        return None if self.input_ack_ms is None else self.input_ack_ms - self.observed_at_ms


@dataclass(frozen=True)
class LiveClockReport:
    verdict: str                           # manual_pilot_candidate | regressed | inconclusive
    matched_pairs: int
    incomplete_pairs: int
    unverified_pairs: int
    non_live_pairs: int
    baseline_timely_successes: int
    candidate_timely_successes: int
    candidate_missed_or_late_inputs: int
    candidate_new_failures: int
    candidate_qos_regressions: int
    baseline_action_p95_ms: float | None
    candidate_action_p95_ms: float | None
    progress_gain_mean: float | None
    progress_gain_ci95: tuple[float, float] | None
    authorized_to_act: bool = False
    note: str = (
        "Offline matched game-state outcomes; host attestations are not "
        "authenticated by this analyzer. No automatic deployment, gaming or streaming."
    )


def assess_live_clock(
    trials: Iterable[LiveClockTrial], *, minimum_pairs: int = 20,
    max_frame_p99_regression_ms: float = 8.0,
    max_obs_dropped_regression_pct: float = 0.5,
) -> LiveClockReport:
    """Compare live-clock outcomes against independently reset matched cases.

    Model latency alone is not evidence of playing well. Holdout scenarios
    must be pre-registered outside the agent, and tested in a real progressing
    game: a late input never qualifies as a timely successful decision.
    Any incomplete or unverified pair prevents a positive recommendation.
    """
    if type(minimum_pairs) is not int or not 10 <= minimum_pairs <= 500:
        raise ValueError("minimum_pairs must be 10..500")
    _ratio(max_frame_p99_regression_ms, "max_frame_p99_regression_ms", 100)
    _ratio(max_obs_dropped_regression_pct, "max_obs_dropped_regression_pct", 10)
    pairs: dict[str, dict[str, LiveClockTrial]] = {}
    episode_ids: set[str] = set()
    scope: tuple[str, str] | None = None
    count = 0
    for item in trials:
        if not isinstance(item, LiveClockTrial):
            raise TypeError("expected LiveClockTrial records")
        count += 1
        if count > 1000:
            raise ValueError("at most 1000 host observations")
        this_scope = item.game_id, item.game_version
        if scope is None:
            scope = this_scope
        elif this_scope != scope:
            raise ValueError("do not pool different games or versions")
        if item.episode_id in episode_ids:
            raise ValueError("episode reused: independent resets required")
        episode_ids.add(item.episode_id)
        pair = pairs.setdefault(item.pair_id, {})
        if item.variant in pair:
            raise ValueError("duplicate variant: no cherry picking")
        pair[item.variant] = item

    full = [p for p in pairs.values() if len(p) == 2]
    incomplete = len(pairs) - len(full)
    for pair in full:
        b, c = pair["baseline"], pair["candidate"]
        if (b.scenario_id != c.scenario_id
                or b.initial_state_sha256 != c.initial_state_sha256
                or abs(b.progress_before - c.progress_before) > .001
                or abs((b.scene_deadline_ms - b.observed_at_ms)
                       - (c.scene_deadline_ms - c.observed_at_ms)) > 1.0):
            raise ValueError("paired attempts must restart with identical scenario, state and time budget")
    unverified = sum(not p["baseline"].independently_scored
                     or not p["candidate"].independently_scored for p in full)
    non_live = sum(not p["baseline"].world_kept_running
                   or not p["candidate"].world_kept_running for p in full)
    verified = [p for p in full if p["baseline"].independently_scored
                and p["candidate"].independently_scored
                and p["baseline"].world_kept_running
                and p["candidate"].world_kept_running]
    if not verified:
        return LiveClockReport("inconclusive", len(full), incomplete, unverified,
                               non_live, 0, 0, 0, 0, 0, None, None, None, None)
    baseline = [p["baseline"] for p in verified]
    candidate = [p["candidate"] for p in verified]
    base_success = sum(x.timely_success for x in baseline)
    cand_success = sum(x.timely_success for x in candidate)
    missed = sum(not x.timely_input for x in candidate)
    newly_failed = sum(b.timely_success and not c.timely_success
                       for b, c in zip(baseline, candidate))
    qos_regressions = sum(
        c.game_p99_frame_ms - b.game_p99_frame_ms > max_frame_p99_regression_ms
        or c.obs_dropped_pct - b.obs_dropped_pct > max_obs_dropped_regression_pct
        for b, c in zip(baseline, candidate)
    )
    progress_deltas = [(c.progress_after - c.progress_before)
                       - (b.progress_after - b.progress_before)
                       for b, c in zip(baseline, candidate)]
    mean_gain = sum(progress_deltas) / len(progress_deltas)
    ci = _ci95(progress_deltas)
    base_p95 = _p95([t.response_ms for t in baseline if t.response_ms is not None])
    cand_p95 = _p95([t.response_ms for t in candidate if t.response_ms is not None])
    regressed = (newly_failed > 0 or qos_regressions > 0
                 or cand_success < base_success or missed > sum(not b.timely_input for b in baseline))
    # Every observed comparison matters. Do not wash out excluded pairs or
    # trade a gameplay failure for marginally faster first-token latency.
    eligible = (
        not regressed and not incomplete and not unverified and not non_live
        and len(full) >= minimum_pairs and ci is not None and ci[0] > 0.02
        and cand_success > base_success
        and cand_p95 is not None and base_p95 is not None
        and cand_p95 <= base_p95 + 25.0
    )
    verdict = "regressed" if regressed else ("manual_pilot_candidate" if eligible else "inconclusive")
    return LiveClockReport(
        verdict, len(full), incomplete, unverified, non_live, base_success, cand_success,
        missed, newly_failed, qos_regressions, base_p95, cand_p95,
        round(mean_gain, 4), ci,
    )


def read_jsonl(path: str | Path) -> list[LiveClockTrial]:
    """Opt-in local host-statistics reader; never ingest player/media content."""
    source = Path(path)
    if source.stat().st_size > 2_000_000:
        raise ValueError("game benchmark input exceeds 2 MB")
    trials: list[LiveClockTrial] = []
    with source.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            if len(line) > 4096:
                raise ValueError("oversized game benchmark record")
            trials.append(LiveClockTrial.from_dict(json.loads(line)))
            if len(trials) > 1000:
                raise ValueError("too many game benchmark records")
    return trials


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Offline paired live-game-clock outcomes; no game or device I/O"
    )
    parser.add_argument("jsonl", help="opt-in host metrics, no raw screenshots or audio")
    parser.add_argument("--minimum-pairs", type=int, default=20)
    args = parser.parse_args()
    report = assess_live_clock(read_jsonl(args.jsonl), minimum_pairs=args.minimum_pairs)
    print(json.dumps(asdict(report), sort_keys=True))


__all__ = ["LiveClockTrial", "LiveClockReport", "assess_live_clock", "read_jsonl"]


if __name__ == "__main__":
    main()
