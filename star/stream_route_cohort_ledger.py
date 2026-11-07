"""Host-only one-shot receipt for an owner-reviewed faster gaming/VTuber model pilot.

This is a persistent replay barrier for signed *evaluations*, not a model launcher.
Do not expose the ledger path or key to model/agent/chat tools. A protected host
must attest the scoring and the owner's opt-in. No game, OBS, voice or deployment
action occurs here. The file is an operational replay barrier, not tamper-proof
storage against an OS administrator or a deleted database.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3
import stat

from .stream_host_model_catalog import HostInferenceCatalog
from .stream_quality_route_selector import QualityGatedRouteSelector
from .stream_route_measured_evaluator import MeasuredSealedRouteEvidence

_SHA = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class PilotClaimResult:
    recorded: bool
    route_alias: str | None
    reason: str
    authorizes_model_launch: bool = False
    authorizes_game_action: bool = False
    authorizes_broadcast: bool = False


def _private_ledger_file(path: Path) -> None:
    """Create mode-0600 database if absent; refuse symlinks/insecure preexisting files.

    The caller must protect parent directories and preserve this file between
    processes and restarts. File precreation uses O_EXCL to avoid accidental
    truncation on concurrent workers. SQLite enforces the actual atomic claim.
    """
    if not path.is_absolute() or not path.parent.is_dir():
        raise ValueError("ledger must use an existing, private absolute directory")
    parent_mode = path.parent.stat()
    if stat.S_IMODE(parent_mode.st_mode) & 0o022:
        raise ValueError("ledger parent directory must not be group/world writable")
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    # Refuse redirection or a preexisting readable-by-other-users database.
    meta = path.lstat()
    if (not stat.S_ISREG(meta.st_mode) or (stat.S_IMODE(meta.st_mode) & 0o077)
            or (hasattr(os, "geteuid") and meta.st_uid != os.geteuid())):
        raise ValueError("ledger file must be a private regular file (mode 0600)")


def claim_verified_fast_route(*, ledger_path: Path,
                              catalog: HostInferenceCatalog,
                              bundle: MeasuredSealedRouteEvidence,
                              host_verification_key: bytes,
                              expected_evaluator_build_sha256: str,
                              owner_approved: bool,
                              baseline_alias: str,
                              task_kind: str,
                              workload: str,
                              suite_sha256: str,
                              now_unix_s: int,
                              max_p95_ms: float,
                              max_total_gpu_mib: float) -> PilotClaimResult:
    """Atomically record a *single* approved candidate pilot per signed cohort.

    Must be invoked by the owner-controlled host only after independent scoring.
    A recorded claim is an audit receipt, NOT permission to launch a model, play,
    spend money, deploy a release, or start a stream. All such actions have
    separate gates. Failure to write/lock/read the ledger raises and fails closed.
    """
    if type(owner_approved) is not bool:
        raise ValueError("owner_approved must be a boolean host decision")
    if not owner_approved:
        return PilotClaimResult(False, None, "owner_opt_in_missing")
    if type(bundle) is not MeasuredSealedRouteEvidence:
        raise TypeError("exact protected host evidence bundle required")
    if (type(expected_evaluator_build_sha256) is not str or
            _SHA.fullmatch(expected_evaluator_build_sha256) is None):
        raise ValueError("pinned evaluator build requires lowercase SHA256")
    if bundle.seal.evaluator_build_sha256 != expected_evaluator_build_sha256:
        return PilotClaimResult(False, None, "evaluator_build_not_pinned")
    # The selector authenticates the seal and enforces matched cohort, case-
    # level non-regression, critical tasks, freshness, GPU cap, and p95 latency.
    selector = QualityGatedRouteSelector(
        catalog=catalog, summaries=bundle.summaries,
        paired_cases=bundle.paired_cases, require_signed_evidence=True,
        evidence_seal=bundle.seal,
        evidence_verification_key=host_verification_key,
    )
    advice = selector.advise(
        owner_approved=True, baseline_alias=baseline_alias,
        task_kind=task_kind, workload=workload, suite_sha256=suite_sha256,
        now_unix_s=now_unix_s, max_p95_ms=max_p95_ms,
        max_total_gpu_mib=max_total_gpu_mib,
    )
    if advice.route_alias is None:
        return PilotClaimResult(False, None, advice.reason)
    if advice.route_alias == baseline_alias:
        return PilotClaimResult(False, None, "no_faster_verified_candidate")
    if advice.reason != "faster_verified_route_for_manual_pilot":
        return PilotClaimResult(False, None, "unexpected_route_advice")

    if not isinstance(ledger_path, Path):
        raise TypeError("host ledger_path must be a Path")
    _private_ledger_file(ledger_path)
    with closing(sqlite3.connect(str(ledger_path), timeout=10, isolation_level=None)) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS route_pilot_claims (
                    cohort_sha256 TEXT PRIMARY KEY,
                    signature_hmac_sha256 TEXT NOT NULL,
                    suite_sha256 TEXT NOT NULL,
                    baseline_alias TEXT NOT NULL,
                    candidate_alias TEXT NOT NULL,
                    evaluator_build_sha256 TEXT NOT NULL,
                    artifact_manifest_sha256 TEXT NOT NULL,
                    claimed_unix_s INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS no_route_pilot_claim_updates
                BEFORE UPDATE ON route_pilot_claims
                BEGIN SELECT RAISE(ABORT, 'pilot claims are immutable'); END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS no_route_pilot_claim_deletes
                BEFORE DELETE ON route_pilot_claims
                BEGIN SELECT RAISE(ABORT, 'pilot claims cannot be deleted'); END
            """)
            # An immutable cohort ID is the primary key, *independent* of route,
            # signature or scope, so it cannot be replayed for any other pilot.
            # BEGIN IMMEDIATE serializes competing processes before INSERT.
            try:
                conn.execute("""
                    INSERT INTO route_pilot_claims (
                        cohort_sha256, signature_hmac_sha256, suite_sha256,
                        baseline_alias, candidate_alias, evaluator_build_sha256,
                        artifact_manifest_sha256, claimed_unix_s
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    bundle.seal.cohort_sha256,
                    bundle.seal.signature_hmac_sha256,
                    suite_sha256, baseline_alias, advice.route_alias,
                    bundle.seal.evaluator_build_sha256,
                    bundle.seal.artifact_manifest_sha256,
                    now_unix_s,
                ))
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT 1 FROM route_pilot_claims WHERE cohort_sha256 = ?",
                    (bundle.seal.cohort_sha256,),
                ).fetchone()
                if row is None:
                    raise  # Schema corruption/other constraint: fail closed.
                conn.rollback()
                return PilotClaimResult(False, None, "evaluation_cohort_already_consumed")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return PilotClaimResult(True, advice.route_alias, "owner_pilot_receipt_recorded")


__all__ = ["PilotClaimResult", "claim_verified_fast_route"]
