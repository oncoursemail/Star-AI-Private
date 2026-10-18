"""Offline, evidence-based screening for STAR's proposed self-improvements.

The AI may propose experiments, but it cannot call this a successful release,
automatically install a model, publish code, train weights, or approve learning.
This module compares paired, independently checked holdout results and produces
ONLY a review recommendation. No network, shell, DB writes, or background tasks.

Run: python -m star.innovation_gate /path/to/paired-results.json
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_CASES = 512
MIN_HOLDOUT_CASES = 40


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name}: use a bounded identifier")
    return value


def _measurement(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid {name}: expected numeric measurement")
    value = float(value)
    if not math.isfinite(value) or not 0 < value <= 10_000_000:
        raise ValueError(f"Invalid {name}: must be finite and positive")
    return value


@dataclass(frozen=True)
class PairedCase:
    """One baseline/candidate comparison on the same, previously hidden task."""

    case_id: str
    domain: str
    baseline_pass: bool
    candidate_pass: bool
    baseline_ms: float
    candidate_ms: float
    baseline_peak_mib: float
    candidate_peak_mib: float
    independent: bool
    blind_holdout: bool
    critical: bool
    evidence_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        _identifier(self.domain, "domain")
        for name in ("baseline_pass", "candidate_pass", "independent", "blind_holdout", "critical"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be true or false")
        for name in ("baseline_ms", "candidate_ms", "baseline_peak_mib", "candidate_peak_mib"):
            _measurement(getattr(self, name), name)
        if not isinstance(self.evidence_sha256, str) or not _SHA256.fullmatch(self.evidence_sha256):
            raise ValueError("Each case requires a 64-character SHA-256 evidence digest")


@dataclass(frozen=True)
class PairedExperiment:
    experiment_id: str
    objective: str
    baseline_revision: str
    candidate_revision: str
    baseline_hardware: str
    candidate_hardware: str
    baseline_suite_sha256: str
    candidate_suite_sha256: str
    cases: tuple[PairedCase, ...]

    def __post_init__(self) -> None:
        _identifier(self.experiment_id, "experiment_id")
        _identifier(self.baseline_revision, "baseline_revision")
        _identifier(self.candidate_revision, "candidate_revision")
        if self.baseline_revision == self.candidate_revision:
            raise ValueError("The baseline and candidate revisions must differ")
        if self.objective not in ("quality", "speed"):
            raise ValueError("Objective must be 'quality' or 'speed'")
        for name in ("baseline_hardware", "candidate_hardware"):
            _identifier(getattr(self, name), name)
        for name in ("baseline_suite_sha256", "candidate_suite_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ValueError(f"Invalid {name}")
        if not isinstance(self.cases, tuple) or not 1 <= len(self.cases) <= MAX_CASES:
            raise ValueError(f"An experiment requires 1 to {MAX_CASES} cases")
        if not all(isinstance(case, PairedCase) for case in self.cases):
            raise TypeError("cases must be PairedCase records")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case identifiers")


@dataclass(frozen=True)
class ReviewResult:
    experiment_id: str
    recommendation: str
    objective: str
    cases: int
    domains: tuple[str, ...]
    baseline_pass_rate: float
    candidate_pass_rate: float
    wins: int
    losses: int
    ties: int
    one_sided_sign_p: float
    baseline_p95_ms: float
    candidate_p95_ms: float
    baseline_peak_mib: float
    candidate_peak_mib: float
    reasons: tuple[str, ...]
    requires_owner_review: bool = True


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _one_sided_sign_p(wins: int, losses: int) -> float:
    """Exact paired sign test excluding ties; returns 1 if no quality gain."""
    n = wins + losses
    if not n or wins <= losses:
        return 1.0
    return sum(math.comb(n, i) for i in range(wins, n + 1)) / (2 ** n)


def review_experiment(experiment: PairedExperiment) -> ReviewResult:
    """Screen evidence; never claim a verified gain without paired tests.

    Statuses are invalid_evidence, reject_regression, needs_more_evidence
    and review_candidate. Even review_candidate cannot mutate any project.
    """
    cases = experiment.cases
    wins = sum(case.candidate_pass and not case.baseline_pass for case in cases)
    losses = sum(case.baseline_pass and not case.candidate_pass for case in cases)
    total = len(cases)
    base_p95 = _p95([case.baseline_ms for case in cases])
    cand_p95 = _p95([case.candidate_ms for case in cases])
    base_memory = max(case.baseline_peak_mib for case in cases)
    cand_memory = max(case.candidate_peak_mib for case in cases)
    base_rate = sum(case.baseline_pass for case in cases) / total
    cand_rate = sum(case.candidate_pass for case in cases) / total
    p_value = _one_sided_sign_p(wins, losses)
    reasons: list[str] = []

    if (experiment.baseline_hardware != experiment.candidate_hardware
            or experiment.baseline_suite_sha256 != experiment.candidate_suite_sha256):
        reasons.append("Baseline and candidate must share hardware and locked evaluation suite")
    if any(not case.independent or not case.blind_holdout for case in cases):
        reasons.append("Every case must use independent checks and a blind holdout")
    if reasons:
        status = "invalid_evidence"
    elif any(case.critical and case.baseline_pass and not case.candidate_pass for case in cases):
        status = "reject_regression"
        reasons.append("Safety-critical or project-critical holdout regression")
    elif cand_memory > base_memory * 1.05:
        status = "reject_regression"
        reasons.append("Peak memory increased more than 5% on matched cases")
    elif experiment.objective == "quality" and cand_p95 > base_p95 * 1.15:
        status = "reject_regression"
        reasons.append("Quality candidate increased p95 latency more than 15%")
    elif experiment.objective == "speed" and losses:
        status = "reject_regression"
        reasons.append("Speed optimization failed at least one previously passing holdout")
    elif total < MIN_HOLDOUT_CASES:
        status = "needs_more_evidence"
        reasons.append(f"Need at least {MIN_HOLDOUT_CASES} unique blind holdout cases")
    elif experiment.objective == "quality":
        if wins > losses and p_value < 0.05 and cand_rate >= base_rate:
            status = "review_candidate"
            reasons.append("Paired task outcomes suggest a quality gain; independent owner review is still required")
        else:
            status = "needs_more_evidence"
            reasons.append("No statistically supported quality gain from paired pass/fail outcomes")
    elif cand_p95 <= base_p95 * 0.90 and cand_rate >= base_rate:
        status = "review_candidate"
        reasons.append("Measured p95 latency improved at least 10% without holdout failures")
    else:
        status = "needs_more_evidence"
        reasons.append("No qualifying speed improvement on matched holdout tasks")

    return ReviewResult(
        experiment_id=experiment.experiment_id,
        recommendation=status,
        objective=experiment.objective,
        cases=total,
        domains=tuple(sorted({case.domain for case in cases})),
        baseline_pass_rate=round(base_rate, 6),
        candidate_pass_rate=round(cand_rate, 6),
        wins=wins, losses=losses, ties=total - wins - losses,
        one_sided_sign_p=p_value,
        baseline_p95_ms=base_p95, candidate_p95_ms=cand_p95,
        baseline_peak_mib=base_memory, candidate_peak_mib=cand_memory,
        reasons=tuple(reasons),
    )


def parse_experiment(payload: dict) -> PairedExperiment:
    """Parse strict local JSON for external benchmark runners and human review."""
    if not isinstance(payload, dict):
        raise ValueError("Experiment must be a JSON object")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases must be a JSON array")
    try:
        return PairedExperiment(**{**payload, "cases": tuple(PairedCase(**x) for x in cases)})
    except (TypeError, KeyError) as exc:
        raise ValueError("Malformed experiment or case structure") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STAR offline holdout experiment quality gate")
    parser.add_argument("results", type=Path, help="JSON file of paired baseline/candidate holdout results")
    args = parser.parse_args(argv)
    try:
        with args.results.open("r", encoding="utf-8") as stream:
            experiment = parse_experiment(json.load(stream))
        print(json.dumps(asdict(review_experiment(experiment)), indent=2, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"Invalid experiment: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
