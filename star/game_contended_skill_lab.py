"""Offline multi-load timing curriculum for Star's game-learning research.

Purpose: the original synthetic timing learner optimized only for a quiet PC.
This lab trains separate *bounded* timing hints from practice-only observations
collected under simulated idle, game+OBS, and heavy-contention workloads, then
freezes them and evaluates on independent, paired unseen scenarios.

The load label is a host-measured context in a future integration, never
inferred from the future action's real latency. Here *all* evidence is synthetic.
No models, microphones, games, devices, OBS, networking, or real permissions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import random
from typing import Mapping

from .game_latency_skill_lab import (
    TimingScenario, _exact_one_sided_p, generate_scenarios,
    play_timing_scenario,
)

# Public, finite synthetic envelopes in milliseconds. The random realization
# inside an episode is NOT exposed to the timing policy.
# Only these named practice profiles may ever produce a calibrated hint.
_TRAIN_LOADS = {
    "idle": ((0.0, 0.0), (0.0, 0.0)),
    "stream_live": ((15.0, 45.0), (20.0, 45.0)),
    "heavy_contention": ((30.0, 75.0), (35.0, 65.0)),
}
# Never trained: deliberately out of distribution and outside the policy map.
_UNKNOWN_LOAD = ((90.0, 125.0), (75.0, 110.0))
_PROFILE_INDEX = {"idle": 101, "stream_live": 211, "heavy_contention": 307}
_CANDIDATES = range(-230, 41, 10)


@dataclass(frozen=True)
class LoadCase:
    """One secretly delayed synthetic episode; policy receives only profile."""
    profile: str
    scene: TimingScenario
    extra_inference_ms: float
    extra_dispatch_ms: float

    def __post_init__(self) -> None:
        if self.profile not in (*_TRAIN_LOADS, "unseen_contention"):
            raise ValueError("unknown synthetic workload label")
        if type(self.scene) is not TimingScenario:
            raise ValueError("typed scenario required")
        for value in (self.extra_inference_ms, self.extra_dispatch_ms):
            if type(value) not in (int, float):
                raise ValueError("finite synthetic contention required")
            try:
                numeric = float(value)
            except (OverflowError, ValueError) as exc:
                raise ValueError("finite synthetic contention required") from exc
            if not math.isfinite(numeric) or not 0 <= numeric <= 300:
                raise ValueError("synthetic contention must be 0..300ms")


@dataclass(frozen=True)
class LoadPolicy:
    """Frozen practice-only mapping, not a gameplay or model permission."""
    profile_offsets: tuple[tuple[str, int], ...]
    synthetic_only: bool = True
    authorizes_real_gameplay: bool = False
    authorizes_skill_promotion: bool = False
    authorizes_broadcast: bool = False

    def __post_init__(self) -> None:
        if (type(self.profile_offsets) is not tuple
                or tuple(name for name, _ in self.profile_offsets)
                != tuple(_TRAIN_LOADS)):
            raise ValueError("every known workload must have exactly one calibration")
        for _, value in self.profile_offsets:
            if type(value) is not int or value not in _CANDIDATES:
                raise ValueError("calibration outside bounded practice search")

    def correction(self, profile: str) -> int | None:
        """Unknown, unverified hardware state must not guess a timing hint."""
        if type(profile) is not str:
            return None
        return dict(self.profile_offsets).get(profile)


@dataclass(frozen=True)
class LoadEval:
    profile: str
    holdout_count: int
    static_success_rate: float
    adaptive_success_rate: float
    improvements: int
    regressions: int
    exact_one_sided_p: float


@dataclass(frozen=True)
class ContendedGameLabReport:
    """Experiment is NOT evidence of real gaming, inference or social ability."""
    practice_count_per_profile: int
    holdout_count_per_profile: int
    frozen_offsets_ms: tuple[tuple[str, int], ...]
    profiles: tuple[LoadEval, ...]
    untrained_profile_abstentions: int
    synthetic_only: bool = True
    authorizes_real_gameplay: bool = False
    authorizes_skill_promotion: bool = False
    authorizes_broadcast: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def make_cases(*, seed: int, count: int, profile: str) -> tuple[LoadCase, ...]:
    """Generate blinded delay realizations from a separate, bounded RNG.

    Seed and profile are public precommitments. The caller must never reuse
    the training seed as the holdout seed in the same study.
    """
    if type(seed) is not int or not 0 <= seed <= 2**63 - 2048:
        raise ValueError("bounded nonnegative seed required")
    if profile not in (*_TRAIN_LOADS, "unseen_contention"):
        raise ValueError("unsupported synthetic workload profile")
    distribution = (_TRAIN_LOADS[profile] if profile in _TRAIN_LOADS
                    else _UNKNOWN_LOAD)
    # No Python randomized hash(); reproducible on Windows and Linux.
    salt = _PROFILE_INDEX.get(profile, 499)
    scenes = generate_scenarios(seed=seed + salt, count=count)
    delay_rng = random.Random(seed + salt + 947)
    inference_range, dispatch_range = distribution
    return tuple(LoadCase(
        profile=profile, scene=scene,
        extra_inference_ms=delay_rng.uniform(*inference_range),
        extra_dispatch_ms=delay_rng.uniform(*dispatch_range),
    ) for scene in scenes)


def attempt(case: LoadCase, correction_ms: int) -> bool:
    """Use only the selected *profile* correction, not realized future delay."""
    if not isinstance(case, LoadCase):
        raise TypeError("typed synthetic load episode required")
    return play_timing_scenario(
        case.scene, correction_ms=correction_ms,
        inference_penalty_ms=case.extra_inference_ms,
        dispatch_penalty_ms=case.extra_dispatch_ms,
    ).success


def fit_profile_policy(practice: Mapping[str, tuple[LoadCase, ...]]) -> LoadPolicy:
    """Small deterministic search using practice data ONLY.

    Each profile needs enough examples. If an unfamiliar label or contaminated
    profile appears, fail rather than invent an unsafe live mapping.
    """
    if not isinstance(practice, Mapping) or set(practice) != set(_TRAIN_LOADS):
        raise ValueError("exactly the three pre-registered training profiles required")
    fitted: list[tuple[str, int]] = []
    for name in _TRAIN_LOADS:
        rows = practice[name]
        if (type(rows) is not tuple or not 40 <= len(rows) <= 2000
                or any(type(row) is not LoadCase or row.profile != name
                       for row in rows)):
            raise ValueError("at least 40 bounded, correctly labeled trials required")
        scores = {offset: sum(attempt(case, offset) for case in rows)
                  for offset in _CANDIDATES}
        best = max(_CANDIDATES, key=lambda c: (scores[c], -abs(c), -c))
        fitted.append((name, best))
    return LoadPolicy(tuple(fitted))


def evaluate_profile(cases: tuple[LoadCase, ...], *,
                     fixed_correction: int, adapted_correction: int) -> LoadEval:
    """Matched comparison from a frozen policy on an untouched holdout."""
    if (type(cases) is not tuple or len(cases) < 40
            or any(type(case) is not LoadCase for case in cases)):
        raise ValueError(">=40 typed holdout cases required")
    if len({case.profile for case in cases}) != 1:
        raise ValueError("one evaluation profile at a time")
    baseline = [attempt(case, fixed_correction) for case in cases]
    adapted = [attempt(case, adapted_correction) for case in cases]
    improvements = sum(a and not b for b, a in zip(baseline, adapted))
    regressions = sum(b and not a for b, a in zip(baseline, adapted))
    rate = lambda values: round(sum(values) / len(values), 4)
    return LoadEval(
        profile=cases[0].profile, holdout_count=len(cases),
        static_success_rate=rate(baseline), adaptive_success_rate=rate(adapted),
        improvements=improvements, regressions=regressions,
        exact_one_sided_p=_exact_one_sided_p(improvements, regressions),
    )


def run_contended_game_lab(*, practice_seed: int, holdout_seed: int,
                           practice_count: int = 96,
                           holdout_count: int = 128) -> ContendedGameLabReport:
    """Train once, freeze, and compare on disjoint seeded load profiles.

    This is a test of the offline *methodology*, not evidence that Star
    measured real OBS load or learned a new game. The unknown workload
    must abstain, not silently route through an idle configuration.
    """
    if (type(practice_seed) is not int or type(holdout_seed) is not int
            or practice_seed == holdout_seed):
        raise ValueError("different integral practice/holdout seeds required")
    training = {p: make_cases(seed=practice_seed, count=practice_count, profile=p)
                for p in _TRAIN_LOADS}
    # Different top-level seeds alone are NOT proof of independent scenarios:
    # seed+profile salts may accidentally collide across training and holdout.
    # Compare the underlying world states across the entire split before any
    # reported score is allowed to count as independent evidence.
    practiced_scenes = {case.scene for rows in training.values() for case in rows}
    policy = fit_profile_policy(training)
    fixed = policy.correction("idle")
    assert fixed is not None
    measured: list[LoadEval] = []
    for name in _TRAIN_LOADS:
        test = make_cases(seed=holdout_seed, count=holdout_count, profile=name)
        if any(case.scene in practiced_scenes for case in test):
            raise ValueError("practice/holdout scene collision; re-register seeds")
        correction = policy.correction(name)
        assert correction is not None
        measured.append(evaluate_profile(
            test, fixed_correction=fixed, adapted_correction=correction,
        ))
    unknown = make_cases(
        seed=holdout_seed, count=holdout_count, profile="unseen_contention"
    )
    if any(case.scene in practiced_scenes for case in unknown):
        raise ValueError("practice/unknown-load scene collision")
    abstained = sum(policy.correction(row.profile) is None for row in unknown)
    return ContendedGameLabReport(
        practice_count_per_profile=practice_count,
        holdout_count_per_profile=holdout_count,
        frozen_offsets_ms=policy.profile_offsets, profiles=tuple(measured),
        untrained_profile_abstentions=abstained,
    )


if __name__ == "__main__":
    print(run_contended_game_lab(
        practice_seed=2026110303, holdout_seed=2026110304,
    ).to_json())
