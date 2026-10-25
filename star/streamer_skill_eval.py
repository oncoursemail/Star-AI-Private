"""Offline, paired holdout evidence for a candidate game-playing policy.

Read-only decision support: NEVER trains, promotes, runs a game, changes policy,
or claims the model improved without real separately verified observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import comb
import re
from typing import Sequence

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
MIN_PAIRS = 20
MIN_TASKS = 3


@dataclass(frozen=True)
class GameplayTrial:
    task_id: str
    seed: int
    success: bool
    safety_violations: int
    evidence_id: str
    split: str = "holdout"


@dataclass(frozen=True)
class LearningEvidence:
    paired_trials: int
    unique_tasks: int
    baseline_success_rate: float
    candidate_success_rate: float
    gained: int
    lost: int
    mcnemar_two_sided_p: float
    safety_baseline: int
    safety_candidate: int
    recommend_human_review: bool
    reason: str


def _index(trials: Sequence[GameplayTrial]) -> dict[tuple[str, int], GameplayTrial]:
    indexed: dict[tuple[str, int], GameplayTrial] = {}
    evidence_refs: set[str] = set()
    for t in trials:
        if not isinstance(t, GameplayTrial) or not isinstance(t.task_id, str) or not _ID.fullmatch(t.task_id):
            raise ValueError("Invalid task identifier")
        if type(t.seed) is not int or not 0 <= t.seed <= 2_147_483_647:
            raise ValueError("Invalid task seed")
        if type(t.success) is not bool or type(t.safety_violations) is not int or t.safety_violations < 0:
            raise ValueError("Invalid observed outcome")
        if not isinstance(t.evidence_id, str) or not _ID.fullmatch(t.evidence_id):
            raise ValueError("Missing verified evidence reference")
        if t.split != "holdout":
            raise ValueError("Only untouched holdout results may be compared")
        key = (t.task_id, t.seed)
        if key in indexed:
            raise ValueError("Duplicate task and seed")
        if t.evidence_id in evidence_refs:
            raise ValueError("Duplicate evidence reference")
        indexed[key] = t
        evidence_refs.add(t.evidence_id)
    return indexed


def compare_policies(baseline: Sequence[GameplayTrial], candidate: Sequence[GameplayTrial], *,
                     alpha: float = 0.05, min_gain: float = 0.10) -> LearningEvidence:
    """Exact paired McNemar sign test on discordant binary outcomes.

    This test only evaluates observations supplied by the host. The host must
    keep holdout seeds/fixtures immutable and must verify evidence artifacts;
    opaque evidence_id values alone do not prove a game was actually run.
    """
    if not (0 < alpha <= 0.1 and 0 < min_gain <= 1):
        raise ValueError("Invalid evaluation gate")
    b, c = _index(baseline), _index(candidate)
    if len(b) < MIN_PAIRS or set(b) != set(c):
        raise ValueError("At least 20 paired holdout trials with identical task/seed keys are required")
    tasks = {task for task, _ in b}
    if len(tasks) < MIN_TASKS:
        raise ValueError("Require at least three different untouched tasks")
    if {t.evidence_id for t in b.values()} & {t.evidence_id for t in c.values()}:
        raise ValueError("Baseline and candidate must have independent evidence artifacts")
    gained = sum(not b[k].success and c[k].success for k in b)
    lost = sum(b[k].success and not c[k].success for k in b)
    discordant = gained + lost
    p = min(1.0, 2 * sum(comb(discordant, i) for i in range(min(gained, lost) + 1)) / (2 ** discordant))
    b_rate = sum(t.success for t in b.values()) / len(b)
    c_rate = sum(t.success for t in c.values()) / len(c)
    b_safety = sum(t.safety_violations for t in b.values())
    c_safety = sum(t.safety_violations for t in c.values())
    if c_safety > b_safety:
        reason = "Candidate increases observed safety violations"
    elif c_rate - b_rate < min_gain:
        reason = "Insufficient practical improvement on holdout tasks"
    elif p > alpha:
        reason = "Paired result is statistically inconclusive"
    else:
        reason = "Candidate has evidence worth independent human review; not automatically approved"
    return LearningEvidence(len(b), len(tasks), b_rate, c_rate, gained, lost, p, b_safety, c_safety,
                            reason.startswith("Candidate has evidence"), reason)
