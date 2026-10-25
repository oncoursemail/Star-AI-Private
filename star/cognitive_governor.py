"""STAR Cognitive Governor: evidence-based effort, initiative, and practice advice.

A small, local-first metacognitive controller. A *trusted host* feeds independently
graded development-task receipts; the governor remembers ONLY bounded identifiers
and numerical outcomes, not prompts, model text, secrets, or any user conversations.

This module never calls a model, a network tool, Studio, or a shell; never changes
permissions or evaluates a candidate; and cannot approve lessons or model weights.
Calling record_grade from an agent/model tool would destroy the trust boundary.
The supplied SHA256 is a receipt reference, NOT cryptographic attestation by itself.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics
import time


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_RESULTS = frozenset({"pass", "fail", "error"})
_VERIFIERS = frozenset({"independent_eval", "studio_lab", "owner_review"})
_STAKES = frozenset({"low", "medium", "high"})
_MAX_CASES = 20_000
_MAX_AGE_DAYS = 90


def _label(value: str, what: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{what} must be a bounded identifier, never raw prompt text")
    return value


@dataclass(frozen=True)
class GradeReceipt:
    """Metadata from an *externally validated* development-task run.

    A host adapter must authenticate the source and independently validate that
    the result actually matches the artifact. Model-reported grades do not count.
    Holdout cases must not be fed back into this learning/effort selector.
    """

    project: str
    family: str
    model: str
    revision: str
    run_id: str
    case_id: str
    result: str
    elapsed_ms: int
    verifier: str
    evidence_sha256: str
    split: str = "development"

    def __post_init__(self) -> None:
        for field in ("project", "family", "model", "revision", "run_id", "case_id"):
            _label(getattr(self, field), field)
        if self.result not in _RESULTS:
            raise ValueError("A grade must be pass, fail or error")
        if self.verifier not in _VERIFIERS:
            raise ValueError("Untrusted/model self-grading is not evidence")
        if self.split != "development":
            raise ValueError("Holdout and production cases are not learning signals")
        if type(self.elapsed_ms) is not int or not 0 <= self.elapsed_ms <= 86_400_000:
            raise ValueError("Elapsed time must be a finite bounded integer")
        if type(self.evidence_sha256) is not str or not _SHA.fullmatch(self.evidence_sha256):
            raise ValueError("A grade requires an independently stored artifact digest")


@dataclass(frozen=True)
class OutcomeSummary:
    project: str
    family: str
    model: str
    revision: str
    distinct_cases: int
    passed: int
    failed: int
    errored: int
    observed_pass_rate: float | None
    wilson_lower_95: float | None
    median_ms: int | None
    p95_ms: int | None

    @property
    def eligible_for_fast(self) -> bool:
        # Repeated re-runs of one case never create fictitious confidence.
        return self.distinct_cases >= 16 and self.wilson_lower_95 is not None and self.wilson_lower_95 >= 0.75


@dataclass(frozen=True)
class EffortBudget:
    model_calls: int = 2
    wall_seconds: int = 45
    available_parallel_slots: int = 1

    def __post_init__(self) -> None:
        if (type(self.model_calls) is not int or not 1 <= self.model_calls <= 8
                or type(self.wall_seconds) is not int or not 1 <= self.wall_seconds <= 3600
                or type(self.available_parallel_slots) is not int
                or not 1 <= self.available_parallel_slots <= 8):
            raise ValueError("Budget outside fixed bounds")


@dataclass(frozen=True)
class EffortAdvice:
    mode: str
    candidate_count: int
    external_verification_required: bool
    owner_approval_required: bool
    observed_lower_bound: float | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PracticeSuggestion:
    family: str
    priority: float
    distinct_cases: int
    reason: str


@dataclass(frozen=True)
class InitiativeAdvice:
    action: str
    reason: str


class OutcomeLedger:
    """Append-only, project/model/revision-scoped evidence metadata.

    The *host* chooses the profile path and invokes record_grade; never register
    recording as an agent tool. Each run/case key is idempotent. Only the
    first externally graded run PER DISTINCT CASE contributes to baseline
    reliability; later retries cannot make a failing first attempt disappear.
    """

    def __init__(self, path: Path):
        if not isinstance(path, Path):
            raise TypeError("Database path must be host-supplied Path")
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("Refusing symlinked cognitive evidence database")
        self.path = path

    def _connect(self, *, create: bool) -> sqlite3.Connection | None:
        if not create and not self.path.exists():
            return None
        if self.path.is_symlink():
            raise ValueError("Refusing symlinked cognitive evidence database")
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.path, timeout=4)
        db.execute("PRAGMA busy_timeout=4000")
        if create:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS grades (
                    id INTEGER PRIMARY KEY,
                    project TEXT NOT NULL,
                    family TEXT NOT NULL,
                    model TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    result TEXT NOT NULL CHECK(result IN ('pass','fail','error')),
                    elapsed_ms INTEGER NOT NULL,
                    verifier TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    observed_at INTEGER NOT NULL,
                    UNIQUE(project,family,model,revision,run_id,case_id)
                );
                CREATE INDEX IF NOT EXISTS grades_family_idx
                    ON grades(project,family,model,revision,case_id,id);
                CREATE TRIGGER IF NOT EXISTS grades_no_update
                    BEFORE UPDATE ON grades BEGIN SELECT RAISE(ABORT, 'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS grades_no_delete
                    BEFORE DELETE ON grades BEGIN SELECT RAISE(ABORT, 'immutable'); END;
                """
            )
            db.commit()
            # Never relax pre-existing profile-directory permissions.
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        return db

    def record_grade(self, receipt: GradeReceipt) -> bool:
        """Accept only trusted-host supplied and checked grade receipts.

        Return True if appended; False for an exact idempotent retry. A retry
        with different evidence for the same run/case is rejected, not counted.
        """
        if not isinstance(receipt, GradeReceipt):
            raise TypeError("Expected a validated host GradeReceipt")
        db = self._connect(create=True)
        assert db is not None
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")  # atomically serialize duplicate checks
                row = db.execute(
                    """SELECT result,elapsed_ms,verifier,evidence_sha256 FROM grades
                       WHERE project=? AND family=? AND model=? AND revision=?
                       AND run_id=? AND case_id=?""",
                    (receipt.project, receipt.family, receipt.model, receipt.revision,
                     receipt.run_id, receipt.case_id),
                ).fetchone()
                signature = (receipt.result, receipt.elapsed_ms, receipt.verifier, receipt.evidence_sha256)
                if row:
                    if tuple(row) != signature:
                        raise ValueError("Conflicting receipt for an existing run/case")
                    return False
                if db.execute("SELECT COUNT(*) FROM grades").fetchone()[0] >= _MAX_CASES:
                    raise OverflowError("Evidence ledger full; operator archive required")
                db.execute(
                    """INSERT INTO grades
                       (project,family,model,revision,run_id,case_id,result,
                        elapsed_ms,verifier,evidence_sha256,observed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (receipt.project, receipt.family, receipt.model, receipt.revision,
                     receipt.run_id, receipt.case_id, receipt.result, receipt.elapsed_ms,
                     receipt.verifier, receipt.evidence_sha256, int(time.time())),
                )
            return True
        finally:
            db.close()

    def summary(self, *, project: str, family: str, model: str,
                revision: str, now: int | None = None) -> OutcomeSummary:
        for key, value in (("project", project), ("family", family),
                           ("model", model), ("revision", revision)):
            _label(value, key)
        if now is not None and (type(now) is not int or now < 0):
            raise ValueError("Report time must be a nonnegative Unix timestamp")
        cutoff = int(time.time() if now is None else now) - _MAX_AGE_DAYS * 86400
        db = self._connect(create=False)
        rows: list[tuple[str, int]] = []
        if db is not None:
            try:
                rows = db.execute(
                    """SELECT g.result,g.elapsed_ms FROM grades AS g
                       JOIN (
                         SELECT MIN(id) AS first_id FROM grades
                         WHERE project=? AND family=? AND model=? AND revision=?
                         GROUP BY case_id
                       ) AS first ON g.id=first.first_id
                       WHERE g.observed_at>=?""",
                    (project, family, model, revision, cutoff),
                ).fetchall()
            finally:
                db.close()
        n = len(rows)
        passed = sum(result == "pass" for result, _ in rows)
        failed = sum(result == "fail" for result, _ in rows)
        errored = n - passed - failed
        if n:
            p = passed / n
            z = 1.959963984540054
            d = 1 + z * z / n
            lower = (p + z * z / (2 * n) - z * math.sqrt(
                p * (1 - p) / n + z * z / (4 * n * n))) / d
            durations = sorted(duration for _, duration in rows)
            p95 = durations[min(n - 1, math.ceil(0.95 * n) - 1)]
            median = round(statistics.median(durations))
        else:
            p = lower = None
            median = p95 = None
        return OutcomeSummary(project, family, model, revision, n, passed, failed,
                              errored, p, lower, median, p95)

    def suggest_practice(self, *, project: str, model: str, revision: str,
                         families: tuple[str, ...], limit: int = 3) -> tuple[PracticeSuggestion, ...]:
        """Rank operator-allowed development families; does not generate or run tasks."""
        if not isinstance(families, tuple) or not 1 <= len(families) <= 32:
            raise ValueError("Choose 1..32 reviewed development-task families")
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError("Invalid practice limit")
        if len(set(families)) != len(families):
            raise ValueError("Duplicate practice families")
        ranking = []
        for family in families:
            if family.lower().startswith(("holdout", "sealed", "private-test")):
                raise ValueError("Protected families cannot be selected for practice")
            stats = self.summary(project=project, family=family, model=model, revision=revision)
            if not stats.distinct_cases:
                priority, reason = 0.85, "No independently verified development examples"
            else:
                priority = min(1.0, 1.0 - (stats.wilson_lower_95 or 0.0))
                priority += min(0.15, stats.errored / stats.distinct_cases * 0.15)
                reason = f"{stats.failed} failed and {stats.errored} errored out of {stats.distinct_cases}"
            ranking.append(PracticeSuggestion(family, round(priority, 4),
                                              stats.distinct_cases, reason))
        return tuple(sorted(ranking, key=lambda item: (-item.priority, item.family))[:limit])


def advise_effort(summary: OutcomeSummary, budget: EffortBudget, *, stakes: str,
                  external_verifier_available: bool, action_is_reversible: bool = True) -> EffortAdvice:
    """Choose *advice* from external outcomes, not an LLM's confidence claim.

    Recommendations never authorize file edits, publication, extra credentials,
    self-promotion, unsafe tool calls or deployments. A fast route is not
    permission to bypass a verifier.
    """
    if not isinstance(summary, OutcomeSummary) or not isinstance(budget, EffortBudget):
        raise TypeError("Need verified history and a bounded model budget")
    if stakes not in _STAKES or type(external_verifier_available) is not bool or type(action_is_reversible) is not bool:
        raise ValueError("Unknown stakes or availability")
    base = (f"{summary.distinct_cases} distinct externally graded cases in the same model revision",)
    if stakes == "high" or not action_is_reversible:
        return EffortAdvice("OWNER_REVIEW", 1, True, True, summary.wilson_lower_95,
                            base + ("High-impact or irreversible actions require a person",))
    if not external_verifier_available:
        return EffortAdvice("GET_EVIDENCE", 1, True, stakes == "medium",
                            summary.wilson_lower_95,
                            base + ("No independent checker available; never self-certify",))
    if stakes == "low" and summary.eligible_for_fast:
        return EffortAdvice("FAST_VERIFY", 1, True, False, summary.wilson_lower_95,
                            base + ("Strong repeated results justify one candidate, not skipping checks",))
    if (budget.model_calls >= 3 and budget.wall_seconds >= 35
            and budget.available_parallel_slots >= 2
            and (summary.distinct_cases < 8 or
                 (summary.wilson_lower_95 is not None and summary.wilson_lower_95 < 0.60))):
        return EffortAdvice("BEST_OF_N_VERIFY", min(4, budget.model_calls,
                                                  budget.available_parallel_slots),
                            True, False, summary.wilson_lower_95,
                            base + ("Extra candidate search reserved for weak or sparse evidence",))
    return EffortAdvice("STANDARD_VERIFY", 1, True, False, summary.wilson_lower_95,
                        base + ("Use one attempt and real checks within the budget",))


def advise_initiative(*, event: str, opt_in: bool, evidence_sha256: str | None,
                      user_speaking: bool, quiet_hours: bool, approval_pending: bool = False) -> InitiativeAdvice:
    """Should a companion proactively offer help? Advisory only, no notifications.

    Human-like means responsive and considerate, never pretending to be human,
    secretly surveilling or inventing feelings/needs. No idle chatter prompts.
    """
    if (type(opt_in) is not bool or type(user_speaking) is not bool
            or type(quiet_hours) is not bool or type(approval_pending) is not bool):
        raise ValueError("Initiative signals must come from trusted host state")
    if not opt_in:
        return InitiativeAdvice("SILENT", "Proactive interaction has not been enabled")
    if quiet_hours or user_speaking:
        return InitiativeAdvice("WAIT", "Respect attention and speaking turns")
    if event not in {"approved_job_complete", "verified_failure", "human_approval_needed",
                     "scheduled_review"}:
        return InitiativeAdvice("SILENT", "No consented actionable event")
    if type(evidence_sha256) is not str or not _SHA.fullmatch(evidence_sha256):
        return InitiativeAdvice("SILENT", "No external evidence for a proactive claim")
    if approval_pending or event == "human_approval_needed":
        return InitiativeAdvice("ASK_PERMISSION", "Surface pending decision without taking it")
    return InitiativeAdvice("OFFER_UPDATE", "Offer a brief, evidence-linked progress update")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only local STAR Cognitive Governor report")
    parser.add_argument("--db", required=True, type=Path)
    for name in ("project", "family", "model", "revision"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--stakes", choices=sorted(_STAKES), default="low")
    options = parser.parse_args()
    ledger = OutcomeLedger(options.db)
    stats = ledger.summary(project=options.project, family=options.family,
                           model=options.model, revision=options.revision)
    advice = advise_effort(stats, EffortBudget(), stakes=options.stakes,
                           external_verifier_available=True)
    print(json.dumps({"summary": asdict(stats), "advice": asdict(advice)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
