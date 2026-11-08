"""Offline, deterministic game timing skill lab (NO live game or device access).

Unlike speed-only inference benchmarks, the toy world never pauses while the
agent thinks or while input is dispatched. A small policy can learn to
compensate for capture age + input delay using *practice-only* outcomes.
Holdout and degraded-load trials are evaluated AFTER calibration. This is a
simulation proving a test harness works, NOT evidence of better real gameplay.

All timing and ground truth here are synthetic. Never feed these results to
Star's signed GameplaySkillBank, stream reactions, or a promotion gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import random
from typing import cast


def _bounded(value: object, label: str, low: float, high: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label}: finite number required")
    try:
        n = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label}: overflow") from exc
    if not math.isfinite(n) or not low <= n <= high:
        raise ValueError(f"{label}: outside permitted range")
    return n


@dataclass(frozen=True)
class TimingScenario:
    """Hidden collision timestamp and a noisy, aged visual observation.

    All timestamps are milliseconds relative to a synthetic frame capture.
    `collision_ms` is engine-only truth, never a feature for the policy.
    """
    collision_ms: float
    observed_ttc_ms: float
    screenshot_age_ms: float
    inference_ms: float
    input_dispatch_ms: float

    def __post_init__(self) -> None:
        _bounded(self.collision_ms, "collision_ms", 200, 2000)
        _bounded(self.observed_ttc_ms, "observed_ttc_ms", 100, 2200)
        _bounded(self.screenshot_age_ms, "screenshot_age_ms", 0, 200)
        _bounded(self.inference_ms, "inference_ms", 0, 1000)
        _bounded(self.input_dispatch_ms, "input_dispatch_ms", 0, 1000)


@dataclass(frozen=True)
class TimingAttempt:
    """An independent engine-scored reaction; no learning authorization."""
    success: bool
    action_ack_ms: float
    lead_at_ack_ms: float
    missed_collision: bool


@dataclass(frozen=True)
class TimingLabReport:
    """Synthetic lab evidence, never permission to act, broadcast, or promote."""
    train_episodes: int
    holdout_episodes: int
    calibration_offset_ms: int
    train_success_rate: float
    baseline_holdout_rate: float
    calibrated_holdout_rate: float
    baseline_stress_rate: float
    calibrated_stress_rate: float
    paired_improvements: int
    paired_regressions: int
    one_sided_exact_p: float
    synthetic_only: bool = True
    authorizes_real_gameplay: bool = False
    authorizes_skill_promotion: bool = False
    authorizes_broadcast: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def play_timing_scenario(
    scene: TimingScenario, *, correction_ms: int = 0,
    inference_penalty_ms: float = 0, dispatch_penalty_ms: float = 0,
) -> TimingAttempt:
    """Simulated world keeps running through inference, scheduling, and key ack.

    The policy sees only `observed_ttc_ms`; it aims to jump 170 ms before
    predicted collision. `correction_ms` is learned exclusively from practice.
    A key sent before inference completes is impossible: it is clamped forward.
    A jump counts only if acknowledged 125..205 ms before actual collision.
    """
    if type(scene) is not TimingScenario:
        raise TypeError("a typed synthetic scenario is required")
    if type(correction_ms) is not int or not -300 <= correction_ms <= 100:
        raise ValueError("bounded integral timing correction required")
    extra_infer = _bounded(inference_penalty_ms, "inference_penalty_ms", 0, 1000)
    extra_dispatch = _bounded(dispatch_penalty_ms, "dispatch_penalty_ms", 0, 1000)
    inference_finished = scene.screenshot_age_ms + scene.inference_ms + extra_infer
    planned_dispatch = scene.observed_ttc_ms - 170.0 + correction_ms
    actual_dispatch = max(inference_finished, planned_dispatch)
    ack = actual_dispatch + scene.input_dispatch_ms + extra_dispatch
    lead = scene.collision_ms - ack
    return TimingAttempt(
        success=125 <= lead <= 205,
        action_ack_ms=round(ack, 3),
        lead_at_ack_ms=round(lead, 3),
        missed_collision=lead <= 0,
    )


def generate_scenarios(*, seed: int, count: int) -> tuple[TimingScenario, ...]:
    """Reproducible scenarios; practice and evaluation MUST use distinct seeds."""
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("seed must be a nonnegative bounded integer")
    if type(count) is not int or not 40 <= count <= 2000:
        raise ValueError("40..2000 scenarios required")
    rng = random.Random(seed)
    return tuple(
        _draw_scenario(rng) for _ in range(count)
    )


def _draw_scenario(rng: random.Random) -> TimingScenario:
    collision = rng.uniform(270, 1100)
    return TimingScenario(
        collision_ms=collision,
        observed_ttc_ms=collision + rng.uniform(-23, 23),
        screenshot_age_ms=rng.uniform(12, 62),
        inference_ms=rng.uniform(30, 80),
        input_dispatch_ms=rng.uniform(55, 112),
    )


def learn_timing_correction(practice: tuple[TimingScenario, ...]) -> tuple[int, int]:
    """Exhaustive, deterministic small policy search, not neural model tuning."""
    if type(practice) is not tuple or len(practice) < 40 or any(
        type(row) is not TimingScenario for row in practice
    ):
        raise ValueError(">=40 typed practice trials required")
    candidates = range(-200, 41, 10)
    # Deterministic tie breaking prefers smaller absolute correction, then lower.
    scores = {
        offset: sum(play_timing_scenario(row, correction_ms=offset).success
                    for row in practice)
        for offset in candidates
    }
    offset = max(candidates, key=lambda c: (scores[c], -abs(c), -c))
    return offset, scores[offset]


def _exact_one_sided_p(improved: int, regressed: int) -> float:
    """Exact paired sign test: only discordant episodes contribute."""
    n = improved + regressed
    if not n:
        return 1.0
    # sum of a binomial(n, 0.5) upper tail; no asymptotic approximation.
    return sum(math.comb(n, k) for k in range(improved, n + 1)) / (2 ** n)


def run_timing_skill_lab(
    *, practice_seed: int, holdout_seed: int,
    practice_count: int = 96, holdout_count: int = 128,
    stress_inference_penalty_ms: float = 40,
    stress_dispatch_penalty_ms: float = 35,
) -> TimingLabReport:
    """One-shot matched synthetic evaluation with untouched holdout trials.

    Never adapt or reselect the policy using holdout results. For serious
    research, preregister seeds and re-run with fresh independent holdouts.
    """
    if type(practice_seed) is not int or type(holdout_seed) is not int:
        raise ValueError("two integral seeds required")
    if practice_seed == holdout_seed:
        raise ValueError("practice and holdout must use distinct seeds")
    practice = generate_scenarios(seed=practice_seed, count=practice_count)
    offset, wins = learn_timing_correction(practice)
    holdout = generate_scenarios(seed=holdout_seed, count=holdout_count)
    base = [play_timing_scenario(s) for s in holdout]
    candidate = [play_timing_scenario(s, correction_ms=offset) for s in holdout]
    stress_base = [
        play_timing_scenario(s, inference_penalty_ms=stress_inference_penalty_ms,
                             dispatch_penalty_ms=stress_dispatch_penalty_ms)
        for s in holdout
    ]
    stress_candidate = [
        play_timing_scenario(s, correction_ms=offset,
                             inference_penalty_ms=stress_inference_penalty_ms,
                             dispatch_penalty_ms=stress_dispatch_penalty_ms)
        for s in holdout
    ]
    improved = sum(c.success and not b.success for b, c in zip(base, candidate))
    regressed = sum(b.success and not c.success for b, c in zip(base, candidate))
    rate = lambda rows: round(sum(row.success for row in rows) / len(rows), 4)
    return TimingLabReport(
        train_episodes=len(practice), holdout_episodes=len(holdout),
        calibration_offset_ms=offset,
        train_success_rate=round(wins / len(practice), 4),
        baseline_holdout_rate=rate(base),
        calibrated_holdout_rate=rate(candidate),
        baseline_stress_rate=rate(stress_base),
        calibrated_stress_rate=rate(stress_candidate),
        paired_improvements=improved, paired_regressions=regressed,
        one_sided_exact_p=_exact_one_sided_p(improved, regressed),
    )


if __name__ == "__main__":
    print(run_timing_skill_lab(
        practice_seed=2026110301, holdout_seed=2026110302,
    ).to_json())
