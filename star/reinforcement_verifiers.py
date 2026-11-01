"""Verifier ensembles and compute-allocation policy for Litha's reinforcement loop.

The core loop deliberately accepts a tiny `Verifier` protocol. This module adds
production-oriented composition around it: multiple independent checks,
hard-veto/required checks, disagreement detection, and a conservative heuristic
for allocating more test-time compute only where it is likely to help.

None of this changes model weights. It only decides how much search to spend
and whether a candidate has enough independent evidence to be promoted.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Callable, Sequence

from .reinforcement_loop import LoopConfig, Verification

SingleVerifier = Callable[[str, str], Verification]


@dataclass(frozen=True)
class VerifierSpec:
    """One independent verifier in a panel."""

    name: str
    verify: SingleVerifier
    weight: float = 1.0
    required: bool = True
    veto_below: float | None = None

    def validate(self) -> "VerifierSpec":
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("verifier name is required")
        if not callable(self.verify):
            raise TypeError("verifier must be callable")
        if not isinstance(self.weight, (int, float)) or isinstance(self.weight, bool) or self.weight <= 0:
            raise ValueError("verifier weight must be positive")
        if type(self.required) is not bool:
            raise TypeError("required must be bool")
        if self.veto_below is not None and (
            not isinstance(self.veto_below, (int, float))
            or isinstance(self.veto_below, bool)
            or not 0.0 <= float(self.veto_below) <= 1.0
        ):
            raise ValueError("veto_below must be in [0, 1]")
        return self


@dataclass(frozen=True)
class ComponentEvidence:
    name: str
    score: float
    passed: bool
    trusted: bool
    evidence_sha256: str
    evidence_excerpt: str


@dataclass(frozen=True)
class PanelReport:
    score: float
    passed: bool
    disagreement: float
    components: tuple[ComponentEvidence, ...]
    hard_failures: tuple[str, ...]

    def as_verification(self) -> Verification:
        pieces = [
            f"{c.name}={c.score:.3f}:{'pass' if c.passed else 'fail'}:{c.evidence_excerpt}"
            for c in self.components
        ]
        suffix = ""
        if self.hard_failures:
            suffix = " | blocked=" + ",".join(self.hard_failures)
        return Verification(
            score=self.score,
            passed=self.passed,
            evidence=" | ".join(pieces) + suffix,
            verifier="panel:" + "+".join(c.name for c in self.components),
            trusted=all(c.trusted for c in self.components),
        )


def _excerpt(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    return compact[:limit] + ("…" if len(compact) > limit else "")


class VerificationPanel:
    """Aggregate independent verifiers without letting a mean hide hard failures."""

    def __init__(
        self,
        specs: Sequence[VerifierSpec],
        *,
        pass_score: float = 0.90,
        max_disagreement: float = 0.30,
        min_trusted: int = 1,
    ):
        self.specs = tuple(spec.validate() for spec in specs)
        if not self.specs:
            raise ValueError("at least one verifier is required")
        if not 0.0 <= pass_score <= 1.0:
            raise ValueError("pass_score must be in [0, 1]")
        if not 0.0 <= max_disagreement <= 1.0:
            raise ValueError("max_disagreement must be in [0, 1]")
        if not 1 <= min_trusted <= len(self.specs):
            raise ValueError("min_trusted is out of range")
        self.pass_score = float(pass_score)
        self.max_disagreement = float(max_disagreement)
        self.min_trusted = min_trusted

    def evaluate(self, task: str, candidate: str) -> PanelReport:
        components: list[ComponentEvidence] = []
        weights: list[float] = []
        scores: list[float] = []
        hard_failures: list[str] = []
        trusted_count = 0

        for spec in self.specs:
            verdict = spec.verify(task, candidate)
            if type(verdict) is not Verification:
                raise TypeError(f"{spec.name} must return Verification")
            verdict.validate()
            if verdict.trusted:
                trusted_count += 1
            else:
                hard_failures.append(spec.name + ":untrusted")
            if spec.required and not verdict.passed:
                hard_failures.append(spec.name + ":required")
            if spec.veto_below is not None and verdict.score < spec.veto_below:
                hard_failures.append(spec.name + ":veto")
            weights.append(float(spec.weight))
            scores.append(float(verdict.score))
            components.append(
                ComponentEvidence(
                    name=spec.name,
                    score=float(verdict.score),
                    passed=verdict.passed,
                    trusted=verdict.trusted,
                    evidence_sha256=hashlib.sha256(verdict.evidence.encode("utf-8")).hexdigest(),
                    evidence_excerpt=_excerpt(verdict.evidence),
                )
            )

        total_weight = sum(weights)
        mean = sum(w * s for w, s in zip(weights, scores)) / total_weight
        variance = sum(w * (s - mean) ** 2 for w, s in zip(weights, scores)) / total_weight
        disagreement = math.sqrt(max(0.0, variance))

        if trusted_count < self.min_trusted:
            hard_failures.append("panel:not_enough_trusted")
        if disagreement > self.max_disagreement:
            hard_failures.append("panel:disagreement")
        if mean < self.pass_score:
            hard_failures.append("panel:score")

        unique_failures = tuple(dict.fromkeys(hard_failures))
        return PanelReport(
            score=mean,
            passed=not unique_failures,
            disagreement=disagreement,
            components=tuple(components),
            hard_failures=unique_failures,
        )

    def __call__(self, task: str, candidate: str) -> Verification:
        return self.evaluate(task, candidate).as_verification()


@dataclass(frozen=True)
class DifficultySignal:
    """Cheap routing signal used before expensive test-time scaling."""

    estimated_pass_probability: float
    verifier_cost: float = 0.25
    risk: float = 0.50
    latency_priority: float = 0.50

    def validate(self) -> "DifficultySignal":
        for name, value in (
            ("estimated_pass_probability", self.estimated_pass_probability),
            ("verifier_cost", self.verifier_cost),
            ("risk", self.risk),
            ("latency_priority", self.latency_priority),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        return self


def compute_optimal_config(signal: DifficultySignal, *, base: LoopConfig | None = None) -> LoopConfig:
    """Conservative test-time-compute heuristic.

    Easy tasks get a small budget, useful-hard tasks get the largest search,
    and near-impossible tasks are capped to avoid compute sinks. Calibrate
    these starting values against Litha's own pass-rate/latency curves.
    """
    signal.validate()
    base = (base or LoopConfig()).validate()
    p = float(signal.estimated_pass_probability)

    if p >= 0.85:
        initial, rounds, refinements = 2, 1, 1
    elif p >= 0.45:
        initial, rounds, refinements = 4, 3, 2
    elif p >= 0.12:
        initial, rounds, refinements = 6, 4, 3
    else:
        initial, rounds, refinements = 4, 2, 2

    if signal.risk >= 0.75:
        initial += 1
        rounds += 1
    if signal.verifier_cost >= 0.75:
        initial = max(2, initial - 2)
        refinements = max(1, refinements - 1)
    if signal.latency_priority >= 0.75:
        initial = max(2, initial - 1)
        rounds = max(1, rounds - 1)

    return LoopConfig(
        initial_candidates=min(16, initial),
        max_rounds=min(8, rounds),
        refinements_per_round=min(8, refinements),
        min_improvement=base.min_improvement,
        pass_score=base.pass_score,
        max_candidate_chars=base.max_candidate_chars,
    )
