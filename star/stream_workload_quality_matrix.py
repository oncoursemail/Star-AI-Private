"""Cross-skill, read-only quality gate for a gaming VTuber's speed experiments.

A fast gameplay response must not hide a regression in general knowledge,
Roblox creation, or live dialogue. Run the existing independently witnessed
speed+quality gate *separately* in four predeclared streaming workloads, then
require all four before recommending a manually supervised rehearsal.

This does not inspect media, use a model, authorize tools, change a route,
operate OBS, start broadcasts or prove that operator attestations are true.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .stream_realtime_benchmark import RealtimeRun
from .stream_realtime_quality_gate import QualityWitness, assess_quality_gate

REQUIRED_WORKLOADS = (
    "gameplay_commentary",
    "general_knowledge",
    "roblox_creation",
    "live_dialogue",
)


@dataclass(frozen=True)
class WorkloadEvidence:
    """Host-predeclared, independently paired observations for one workload."""

    workload: str
    runs: tuple[RealtimeRun, ...]
    witnesses: tuple[QualityWitness, ...]

    def __post_init__(self) -> None:
        if type(self.workload) is not str or self.workload not in REQUIRED_WORKLOADS:
            raise ValueError("unrecognized or unregistered streaming workload")
        if (type(self.runs) is not tuple or not 1 <= len(self.runs) <= 1000
                or any(not isinstance(r, RealtimeRun) for r in self.runs)):
            raise ValueError("workload requires 1..1000 measured RealtimeRun records")
        if (type(self.witnesses) is not tuple or len(self.witnesses) > 1000
                or any(not isinstance(w, QualityWitness) for w in self.witnesses)):
            raise ValueError("witnesses must be a bounded tuple of quality observations")


@dataclass(frozen=True)
class WorkloadVerdict:
    """Aggregate status only: no prompts, raw case IDs or viewer content."""

    workload: str
    status: str
    matched_pairs: int
    witness_coverage: int
    expected_witnesses: int


@dataclass(frozen=True)
class WorkloadMatrixReport:
    status: str
    results: tuple[WorkloadVerdict, ...]
    observed_workloads: int
    required_workloads: int
    total_matched_pairs: int
    total_quality_witnesses: int
    authorized_to_stream: bool = False
    note: str = (
        "Advisory only; host-attested and non-authenticating. "
        "A positive result needs independent review and cannot deploy a model."
    )


def assess_workload_matrix(
    batches: Iterable[WorkloadEvidence], *,
    minimum_pairs_per_workload: int = 20,
    gpu_budget_mib: float = 6656,
    max_av_p95_ms: float = 100,
    minimum_correct_ratio: float = 0.95,
) -> WorkloadMatrixReport:
    """Prevent pooling or skipping hard skills when testing faster live models.

    The trusted host must preregister four workload rosters and independently
    observe correctness, gameplay grounding and OBS audio. A pair ID cannot
    count twice across skills. Missing workloads or witnesses never pass.
    """
    if type(minimum_pairs_per_workload) is not int or not 10 <= minimum_pairs_per_workload <= 200:
        raise ValueError("minimum per-workload sample size must be 10..200")
    by_workload: dict[str, WorkloadEvidence] = {}
    used_pairs: set[str] = set()
    for batch in batches:
        if not isinstance(batch, WorkloadEvidence):
            raise TypeError("expected WorkloadEvidence, not user/model-generated dicts")
        if batch.workload in by_workload:
            raise ValueError("duplicate workload: do not choose the best trial batch")
        if len(by_workload) >= len(REQUIRED_WORKLOADS):
            raise ValueError("too many workload groups")
        pairs = {run.pair_id for run in batch.runs}
        if used_pairs & pairs:
            raise ValueError("pair IDs reused across workloads")
        used_pairs.update(pairs)
        by_workload[batch.workload] = batch

    results: list[WorkloadVerdict] = []
    for workload in REQUIRED_WORKLOADS:
        batch = by_workload.get(workload)
        if batch is None:
            results.append(WorkloadVerdict(workload, "missing", 0, 0, 0))
            continue
        report = assess_quality_gate(
            batch.runs, batch.witnesses,
            minimum_pairs=minimum_pairs_per_workload,
            gpu_budget_mib=gpu_budget_mib,
            max_av_p95_ms=max_av_p95_ms,
            minimum_correct_ratio=minimum_correct_ratio,
        )
        results.append(WorkloadVerdict(
            workload, report.status, report.matched_pairs,
            report.witness_coverage, report.expected_witnesses,
        ))

    statuses = {item.status for item in results}
    if "missing" in statuses or "insufficient_evidence" in statuses:
        status = "insufficient_evidence"
    elif "quality_regressed" in statuses:
        status = "quality_regressed"
    elif "speed_not_verified" in statuses:
        status = "speed_not_verified"
    elif statuses == {"eligible_for_manual_rehearsal"}:
        status = "eligible_for_manual_review"
    else:
        status = "inconclusive"
    return WorkloadMatrixReport(
        status=status,
        results=tuple(results),
        observed_workloads=len(by_workload),
        required_workloads=len(REQUIRED_WORKLOADS),
        total_matched_pairs=sum(r.matched_pairs for r in results),
        total_quality_witnesses=sum(r.witness_coverage for r in results),
    )


__all__ = [
    "REQUIRED_WORKLOADS", "WorkloadEvidence", "WorkloadVerdict",
    "WorkloadMatrixReport", "assess_workload_matrix",
]
