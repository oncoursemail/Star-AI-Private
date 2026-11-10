"""Durable, single-host lease coordination and fenced virtual artifacts for STAR.

This module coordinates trusted application-defined workers across processes.
It does not execute tools or workers. Every claim receives a monotonically
increasing run-scoped fencing token. Mutating tasks may write only to the
transactional SQLite artifact workspace through commit_artifact(); direct
filesystem, Git, Roblox, HTTP, and device side effects remain out of scope.

The SQLite database is the protected resource and validates the current lease,
fence, declared write scope, and content compare-and-swap in one transaction.
Workers must never receive the database path or direct SQL access. The workspace
is local-host only and is not a multi-machine consensus or filesystem gateway.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Callable, Iterator
from uuid import uuid4

from .orchestration import Task, TaskPlan

_SCHEMA_VERSION = 3
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_RUN_ARTIFACT_BYTES = 64 * 1024 * 1024
_MAX_RUN_ARTIFACTS = 256
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_ERROR = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_TERMINAL = frozenset({"completed", "failed", "blocked", "cancelled"})


class CoordinatorError(RuntimeError):
    """Base class for durable coordinator errors."""


class StaleLeaseError(CoordinatorError):
    """The lease is expired, replaced, aborted, or otherwise no longer current."""


class PlanMismatchError(CoordinatorError):
    """A run ID was reused with a different immutable task plan."""


class ArtifactConflictError(CoordinatorError):
    """An artifact compare-and-swap or commit-id check failed."""


class RunNotReadyError(CoordinatorError):
    """A run cannot be finalized while pending or leased tasks remain."""


@dataclass(frozen=True)
class DependencyResult:
    task_id: str
    role: str
    answer: str
    evidence: tuple[str, ...]
    elapsed_ms: int
    digest: str


@dataclass(frozen=True)
class AgentLease:
    run_id: str
    task: Task
    worker_id: str
    lease_id: str
    fencing_token: int
    attempt: int
    lease_expires_ns: int
    plan_hash: str
    dependency_results: tuple[DependencyResult, ...]


@dataclass(frozen=True)
class ArtifactCommit:
    run_id: str
    resource: str
    commit_id: str
    sha256: str
    version: int
    fencing_token: int
    created_ns: int
    status: str


@dataclass(frozen=True)
class ArtifactRecord:
    run_id: str
    resource: str
    content: bytes
    sha256: str
    version: int
    updated_task_id: str
    fencing_token: int
    updated_ns: int


def _task_payload(task: Task) -> dict:
    return {
        "id": task.id,
        "role": task.role,
        "goal": task.goal,
        "dependencies": list(task.dependencies),
        "reads": list(task.reads),
        "writes": list(task.writes),
        "references": list(task.references),
        "evidence": list(task.evidence),
    }


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _plan_hash(plan: TaskPlan) -> str:
    payload = {
        "schema": _SCHEMA_VERSION,
        "max_parallel": plan.max_parallel,
        "tasks": [_task_payload(task) for task in plan.tasks.values()],
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _snapshot_plan(plan: TaskPlan) -> TaskPlan:
    """Detach the coordinator from the caller's mutable TaskPlan dictionary."""
    tasks = [
        Task(
            task.id,
            task.role,
            task.goal,
            tuple(task.dependencies),
            tuple(task.reads),
            tuple(task.writes),
            tuple(task.references),
            tuple(task.evidence),
        )
        for task in plan.tasks.values()
    ]
    return TaskPlan(tasks, max_parallel=plan.max_parallel)


def _result_payload(answer: str, evidence: tuple[str, ...], elapsed_ms: int) -> str:
    if type(answer) is not str or not answer.strip() or len(answer) > 12000:
        raise ValueError("Answer must be nonempty text of at most 12,000 characters")
    if (type(evidence) is not tuple or len(evidence) > 20
            or any(type(item) is not str or len(item) > 500 for item in evidence)):
        raise ValueError("Evidence must contain at most 20 strings of at most 500 characters")
    if type(elapsed_ms) is not int or not 0 <= elapsed_ms <= 3_600_000:
        raise ValueError("Elapsed time must be an integer from 0 to 3,600,000 ms")
    return _canonical({
        "answer": answer,
        "evidence": list(evidence),
        "elapsed_ms": elapsed_ms,
    })


def _artifact_path(value: str) -> str:
    """Normalize a virtual-workspace path without interpreting it on the host OS."""
    if (type(value) is not str or not value or len(value) > 500
            or value.startswith("/") or value.endswith("/")
            or "\\" in value or "//" in value or ":" in value):
        raise ValueError("Artifact path must be a bounded relative POSIX path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Artifact path traversal is not allowed")
    if any(any(ord(char) < 32 or ord(char) == 127 for char in part) for part in parts):
        raise ValueError("Artifact path contains control characters")
    return value


def _within_scope(resource: str, scopes: tuple[str, ...]) -> bool:
    return any(resource == scope or resource.startswith(scope + "/") for scope in scopes)


class AgentRunCoordinator:
    """SQLite-backed lease coordinator with a fenced virtual-artifact workspace.

    Use a local filesystem (NTFS/ext4/APFS), not a network share or sync folder.
    Multiple processes on the same host may open the same database. SQLite's
    BEGIN IMMEDIATE serializes claims and artifact commits; WAL allows readers.

    Leases use the host wall clock because expiry must survive process restarts.
    A forward clock jump may cause safe rework; a backward jump may delay reclaim.
    Fencing tokens reject stale result commits even after an early expiry/reclaim.
    The host must keep this database private and must not expose its contents to
    untrusted workers. On Windows, provision a private ACL on the parent folder.
    """

    def __init__(
        self,
        database: Path,
        *,
        lease_seconds: float = 30.0,
        max_attempts: int = 3,
        busy_timeout_ms: int = 5000,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not isinstance(database, Path) or not database.is_absolute():
            raise ValueError("Database path must be an absolute pathlib.Path")
        if (database.is_symlink() or database.parent.is_symlink()
                or (database.exists() and not database.is_file())):
            raise PermissionError("Coordinator database and parent must not be symlinks")
        database = database.resolve(strict=False)
        if not database.parent.is_dir():
            raise FileNotFoundError("Create the private coordinator directory first")
        if os.name == "posix" and stat.S_IMODE(database.parent.stat().st_mode) & 0o077:
            raise PermissionError("Coordinator directory must be private (mode 0700 on POSIX)")
        if (type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds)
                or not 1.0 <= lease_seconds <= 3600.0):
            raise ValueError("Lease duration must be between 1 and 3600 seconds")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if type(busy_timeout_ms) is not int or not 1 <= busy_timeout_ms <= 30000:
            raise ValueError("busy_timeout_ms must be between 1 and 30000")
        if not callable(clock_ns):
            raise TypeError("clock_ns must be a trusted callable")
        self.database = database
        self.lease_ns = int(float(lease_seconds) * 1_000_000_000)
        self.max_attempts = max_attempts
        self.busy_timeout_ms = busy_timeout_ms
        self._clock_ns = clock_ns
        self._plans: dict[str, TaskPlan] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database),
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA wal_autocheckpoint=1000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise CoordinatorError("SQLite WAL mode is required on the local database")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 2, _SCHEMA_VERSION):
                raise CoordinatorError("Unsupported coordinator database schema")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    plan_hash TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('active','completed','finished_with_failures','aborted')
                    ),
                    max_parallel INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    lease_ns INTEGER NOT NULL,
                    next_fence INTEGER NOT NULL DEFAULT 0,
                    created_ns INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('pending','leased','completed','failed','blocked','cancelled')
                    ),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    fence_token INTEGER NOT NULL DEFAULT 0,
                    lease_id TEXT,
                    lease_owner TEXT,
                    lease_expires_ns INTEGER,
                    completed_lease_id TEXT,
                    completed_fence_token INTEGER,
                    result_json TEXT,
                    result_sha256 TEXT,
                    error_code TEXT,
                    PRIMARY KEY (run_id, task_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS tasks_run_state
                    ON tasks(run_id, state, lease_expires_ns);
                CREATE TABLE IF NOT EXISTS artifacts (
                    run_id TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    content BLOB NOT NULL,
                    sha256 TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0),
                    updated_task_id TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL CHECK (fencing_token > 0),
                    updated_ns INTEGER NOT NULL,
                    PRIMARY KEY (run_id, resource),
                    FOREIGN KEY (run_id, updated_task_id)
                        REFERENCES tasks(run_id, task_id)
                );
                CREATE TABLE IF NOT EXISTS artifact_commits (
                    run_id TEXT NOT NULL,
                    commit_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    expected_sha256 TEXT,
                    new_sha256 TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_ns INTEGER NOT NULL,
                    PRIMARY KEY (run_id, commit_id),
                    UNIQUE (run_id, resource, version),
                    FOREIGN KEY (run_id, task_id)
                        REFERENCES tasks(run_id, task_id)
                );
                CREATE INDEX IF NOT EXISTS artifacts_run_updated
                    ON artifacts(run_id, updated_ns);
                PRAGMA user_version=3;
                """
            )
            if self.database.exists() and self.database.stat().st_size > 0:
                try:
                    if self.database.stat().st_mode & 0o777 != 0o600:
                        self.database.chmod(0o600)
                except OSError:
                    # Windows ACLs are inherited from the trusted host directory.
                    pass
        finally:
            connection.close()

    def _now(self) -> int:
        value = self._clock_ns()
        if type(value) is not int or value <= 0:
            raise CoordinatorError("Trusted clock returned an invalid timestamp")
        return value

    @staticmethod
    def _validate_identifier(value: str, label: str) -> str:
        if type(value) is not str or not _ID.fullmatch(value):
            raise ValueError(f"Invalid {label}")
        return value

    def register_run(self, run_id: str, plan: TaskPlan) -> bool:
        """Register an immutable plan; writes are limited to the fenced artifact workspace."""
        self._validate_identifier(run_id, "run_id")
        if not isinstance(plan, TaskPlan) or not plan.tasks or len(plan.tasks) > 64:
            raise ValueError("Expected a nonempty TaskPlan containing at most 64 tasks")
        plan = _snapshot_plan(plan)
        digest = _plan_hash(plan)
        with self._transaction() as db:
            now = self._now()
            existing = db.execute(
                "SELECT plan_hash,max_parallel,max_attempts,lease_ns FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if existing:
                if (existing["plan_hash"] != digest
                        or existing["max_parallel"] != plan.max_parallel
                        or existing["max_attempts"] != self.max_attempts
                        or existing["lease_ns"] != self.lease_ns):
                    raise PlanMismatchError("Run ID is already bound to a different plan/policy")
                self._plans[run_id] = plan
                return False
            db.execute(
                "INSERT INTO runs(run_id,plan_hash,state,max_parallel,max_attempts,lease_ns,next_fence,created_ns) "
                "VALUES(?,?, 'active', ?, ?, ?, 0, ?)",
                (run_id, digest, plan.max_parallel, self.max_attempts, self.lease_ns, now),
            )
            db.executemany(
                "INSERT INTO tasks(run_id,task_id,role,contract_json,state) VALUES(?,?,?,?, 'pending')",
                [
                    (run_id, task.id, task.role, _canonical(_task_payload(task)))
                    for task in plan.tasks.values()
                ],
            )
        self._plans[run_id] = plan
        return True

    def _expire_leases(self, db: sqlite3.Connection, run_id: str, now: int) -> int:
        run = db.execute(
            "SELECT max_attempts FROM runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if run is None:
            raise CoordinatorError("Unknown run")
        rows = db.execute(
            "SELECT task_id,attempts FROM tasks "
            "WHERE run_id=? AND state='leased' AND lease_expires_ns<=?",
            (run_id, now),
        ).fetchall()
        for row in rows:
            exhausted = row["attempts"] >= run["max_attempts"]
            db.execute(
                "UPDATE tasks SET state=?, lease_id=NULL, lease_owner=NULL, "
                "lease_expires_ns=NULL, error_code=? WHERE run_id=? AND task_id=? "
                "AND state='leased'",
                (
                    "failed" if exhausted else "pending",
                    "lease_expired_attempts_exhausted" if exhausted else "lease_expired",
                    run_id,
                    row["task_id"],
                ),
            )
        return len(rows)

    def _block_failed_dependents(
        self, db: sqlite3.Connection, run_id: str, plan: TaskPlan
    ) -> int:
        changed_total = 0
        while True:
            states = {
                row["task_id"]: row["state"]
                for row in db.execute(
                    "SELECT task_id,state FROM tasks WHERE run_id=?", (run_id,)
                ).fetchall()
            }
            blocked = [
                task.id for task in plan.tasks.values()
                if states.get(task.id) == "pending"
                and any(states.get(dep) in {"failed", "blocked", "cancelled"}
                        for dep in task.dependencies)
            ]
            if not blocked:
                return changed_total
            db.executemany(
                "UPDATE tasks SET state='blocked',error_code='dependency_failed' "
                "WHERE run_id=? AND task_id=? AND state='pending'",
                [(run_id, task_id) for task_id in blocked],
            )
            changed_total += len(blocked)

    def _dependency_results(
        self, db: sqlite3.Connection, run_id: str, task: Task
    ) -> tuple[DependencyResult, ...]:
        output: list[DependencyResult] = []
        for dependency in task.dependencies:
            row = db.execute(
                "SELECT role,state,result_json,result_sha256 FROM tasks "
                "WHERE run_id=? AND task_id=?",
                (run_id, dependency),
            ).fetchone()
            if row is None or row["state"] != "completed":
                raise CoordinatorError("A dependency is not durably completed")
            payload = row["result_json"]
            digest = row["result_sha256"]
            if (not isinstance(payload, str) or not isinstance(digest, str)
                    or hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest):
                raise CoordinatorError("Stored dependency result failed integrity validation")
            try:
                data = json.loads(payload)
                if type(data) is not dict or set(data) != {"answer", "evidence", "elapsed_ms"}:
                    raise ValueError("Unexpected dependency result fields")
                if type(data["evidence"]) is not list:
                    raise ValueError("Invalid dependency evidence")
                normalized = _result_payload(
                    data["answer"], tuple(data["evidence"]), data["elapsed_ms"]
                )
                if normalized != payload:
                    raise ValueError("Noncanonical dependency result")
            except (TypeError, KeyError, ValueError) as exc:
                raise CoordinatorError("Stored dependency result is invalid") from exc
            output.append(DependencyResult(
                dependency, row["role"], data["answer"],
                tuple(data["evidence"]), data["elapsed_ms"], digest,
            ))
        return tuple(output)

    def claim_next(self, run_id: str, worker_id: str) -> AgentLease | None:
        """Atomically claim one ready task and return only its direct dependency results."""
        self._validate_identifier(run_id, "run_id")
        self._validate_identifier(worker_id, "worker_id")
        plan = self._plans.get(run_id)
        if plan is None:
            raise CoordinatorError("Register the immutable plan on this coordinator instance first")
        with self._transaction() as db:
            now = self._now()
            run = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise CoordinatorError("Unknown run")
            if run["state"] != "active":
                return None
            self._expire_leases(db, run_id, now)
            self._block_failed_dependents(db, run_id, plan)
            rows = db.execute(
                "SELECT task_id,state FROM tasks WHERE run_id=?", (run_id,)
            ).fetchall()
            states = {row["task_id"]: row["state"] for row in rows}
            completed = {task_id for task_id, state in states.items() if state == "completed"}
            running = {task_id for task_id, state in states.items() if state == "leased"}
            finished = {task_id for task_id, state in states.items() if state in _TERMINAL}
            ready = plan.ready(completed, running, finished=finished)
            for task in ready:
                row = db.execute(
                    "SELECT state,attempts,contract_json FROM tasks WHERE run_id=? AND task_id=?",
                    (run_id, task.id),
                ).fetchone()
                if row is None or row["state"] != "pending":
                    continue
                if row["contract_json"] != _canonical(_task_payload(task)):
                    raise PlanMismatchError("Registered task contract changed")
                fence = int(run["next_fence"]) + 1
                lease_id = uuid4().hex
                expires = now + self.lease_ns
                attempt = int(row["attempts"]) + 1
                db.execute(
                    "UPDATE tasks SET state='leased',attempts=?,fence_token=?,lease_id=?,"
                    "lease_owner=?,lease_expires_ns=?,error_code=NULL "
                    "WHERE run_id=? AND task_id=? AND state='pending'",
                    (attempt, fence, lease_id, worker_id, expires, run_id, task.id),
                )
                db.execute(
                    "UPDATE runs SET next_fence=? WHERE run_id=?",
                    (fence, run_id),
                )
                return AgentLease(
                    run_id, task, worker_id, lease_id, fence, attempt, expires,
                    run["plan_hash"], self._dependency_results(db, run_id, task),
                )
            return None

    def _current_row(
        self, db: sqlite3.Connection, lease: AgentLease, now: int
    ) -> sqlite3.Row:
        run = db.execute(
            "SELECT state,plan_hash FROM runs WHERE run_id=?", (lease.run_id,)
        ).fetchone()
        row = db.execute(
            "SELECT * FROM tasks WHERE run_id=? AND task_id=?",
            (lease.run_id, lease.task.id),
        ).fetchone()
        if (run is None or row is None or run["state"] != "active"
                or run["plan_hash"] != lease.plan_hash
                or row["state"] != "leased"
                or row["lease_id"] != lease.lease_id
                or row["lease_owner"] != lease.worker_id
                or row["fence_token"] != lease.fencing_token
                or row["contract_json"] != _canonical(_task_payload(lease.task))):
            raise StaleLeaseError("Lease no longer owns this task")
        if row["lease_expires_ns"] is None or row["lease_expires_ns"] <= now:
            raise StaleLeaseError("Lease has expired")
        return row

    def renew(self, lease: AgentLease) -> AgentLease:
        """Renew the same ownership; renewal never increments its fencing token."""
        if not isinstance(lease, AgentLease):
            raise TypeError("Expected an AgentLease")
        with self._transaction() as db:
            now = self._now()
            current = self._current_row(db, lease, now)
            expires = max(now + self.lease_ns, current["lease_expires_ns"])
            db.execute(
                "UPDATE tasks SET lease_expires_ns=? WHERE run_id=? AND task_id=? "
                "AND lease_id=? AND fence_token=?",
                (expires, lease.run_id, lease.task.id, lease.lease_id, lease.fencing_token),
            )
        return replace(lease, lease_expires_ns=expires)

    def complete(
        self,
        lease: AgentLease,
        *,
        answer: str,
        evidence: tuple[str, ...] = (),
        elapsed_ms: int = 0,
    ) -> str:
        """Commit a result only from the current unexpired lease.

        Returns 'completed' for the first commit and 'already_completed' for an
        identical retry from the same lease. A different/stale result is rejected.
        """
        if not isinstance(lease, AgentLease):
            raise TypeError("Expected an AgentLease")
        if type(evidence) is list:
            evidence = tuple(evidence)
        payload = _result_payload(answer, evidence, elapsed_ms)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with self._transaction() as db:
            now = self._now()
            row = db.execute(
                "SELECT * FROM tasks WHERE run_id=? AND task_id=?",
                (lease.run_id, lease.task.id),
            ).fetchone()
            if (row is not None and row["state"] == "completed"
                    and row["completed_lease_id"] == lease.lease_id
                    and row["completed_fence_token"] == lease.fencing_token):
                if row["result_sha256"] == digest:
                    return "already_completed"
                raise StaleLeaseError("A completed lease cannot replace its result")
            self._current_row(db, lease, now)
            db.execute(
                "UPDATE tasks SET state='completed',lease_id=NULL,lease_owner=NULL,"
                "lease_expires_ns=NULL,completed_lease_id=?,completed_fence_token=?,"
                "result_json=?,result_sha256=?,error_code=NULL "
                "WHERE run_id=? AND task_id=? AND state='leased' "
                "AND lease_id=? AND fence_token=?",
                (
                    lease.lease_id, lease.fencing_token, payload, digest,
                    lease.run_id, lease.task.id, lease.lease_id, lease.fencing_token,
                ),
            )
        return "completed"


    def commit_artifact(
        self,
        lease: AgentLease,
        *,
        resource: str,
        content: str | bytes,
        commit_id: str,
        expected_sha256: str | None = None,
    ) -> ArtifactCommit:
        """Atomically commit a virtual-workspace artifact under the current lease.

        This is the resource-side fencing boundary for STAR's *logical* workspace:
        lease validation, compare-and-swap, artifact bytes, and the immutable commit
        receipt are written in one SQLite BEGIN IMMEDIATE transaction. It does not
        write to the host filesystem, Git, Roblox, or external services.
        """
        if not isinstance(lease, AgentLease):
            raise TypeError("Expected an AgentLease")
        resource = _artifact_path(resource)
        self._validate_identifier(commit_id, "commit_id")
        if type(content) is str:
            payload = content.encode("utf-8")
        elif type(content) is bytes:
            payload = content
        else:
            raise TypeError("Artifact content must be UTF-8 text or bytes")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise ValueError("Artifact exceeds the 4 MiB per-file limit")
        if expected_sha256 is not None and (
            type(expected_sha256) is not str or not _SHA256.fullmatch(expected_sha256)
        ):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest or None")
        if not _within_scope(resource, lease.task.writes):
            raise PermissionError("Artifact path is outside this task's declared write scopes")
        digest = hashlib.sha256(payload).hexdigest()

        with self._transaction() as db:
            now = self._now()
            self._current_row(db, lease, now)
            previous_commit = db.execute(
                "SELECT task_id,resource,fencing_token,expected_sha256,new_sha256,version,created_ns "
                "FROM artifact_commits WHERE run_id=? AND commit_id=?",
                (lease.run_id, commit_id),
            ).fetchone()
            if previous_commit is not None:
                same = (
                    previous_commit["task_id"] == lease.task.id
                    and previous_commit["resource"] == resource
                    and previous_commit["fencing_token"] == lease.fencing_token
                    and previous_commit["expected_sha256"] == expected_sha256
                    and previous_commit["new_sha256"] == digest
                )
                if not same:
                    raise ArtifactConflictError("Commit ID was already used for different content or ownership")
                return ArtifactCommit(
                    lease.run_id, resource, commit_id, digest,
                    previous_commit["version"], lease.fencing_token,
                    previous_commit["created_ns"], "already_committed",
                )

            current = db.execute(
                "SELECT sha256,version,length(content) AS size,updated_task_id FROM artifacts "
                "WHERE run_id=? AND resource=?",
                (lease.run_id, resource),
            ).fetchone()
            if current is not None and current["updated_task_id"] != lease.task.id:
                source = db.execute(
                    "SELECT state FROM tasks WHERE run_id=? AND task_id=?",
                    (lease.run_id, current["updated_task_id"]),
                ).fetchone()
                if source is None or source["state"] != "completed":
                    raise ArtifactConflictError("Artifact from another task is not published until that task completes")
            if current is None:
                if expected_sha256 is not None:
                    raise ArtifactConflictError("Artifact does not exist at the expected digest")
                version = 1
                old_size = 0
            else:
                if expected_sha256 is None or current["sha256"] != expected_sha256:
                    raise ArtifactConflictError("Artifact changed since the worker's read; refresh and retry")
                version = int(current["version"]) + 1
                old_size = int(current["size"])

            totals = db.execute(
                "SELECT COUNT(*) AS files,COALESCE(SUM(length(content)),0) AS bytes "
                "FROM artifacts WHERE run_id=?",
                (lease.run_id,),
            ).fetchone()
            if current is None and int(totals["files"]) >= _MAX_RUN_ARTIFACTS:
                raise CoordinatorError("Run artifact-count budget exceeded")
            new_total = int(totals["bytes"]) - old_size + len(payload)
            if new_total > _MAX_RUN_ARTIFACT_BYTES:
                raise CoordinatorError("Run artifact-storage budget exceeded")

            db.execute(
                "INSERT INTO artifacts(run_id,resource,content,sha256,version,updated_task_id,fencing_token,updated_ns) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_id,resource) DO UPDATE SET "
                "content=excluded.content,sha256=excluded.sha256,version=excluded.version,"
                "updated_task_id=excluded.updated_task_id,fencing_token=excluded.fencing_token,"
                "updated_ns=excluded.updated_ns",
                (
                    lease.run_id, resource, sqlite3.Binary(payload), digest, version,
                    lease.task.id, lease.fencing_token, now,
                ),
            )
            db.execute(
                "INSERT INTO artifact_commits(run_id,commit_id,task_id,resource,fencing_token,"
                "expected_sha256,new_sha256,version,created_ns) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    lease.run_id, commit_id, lease.task.id, resource, lease.fencing_token,
                    expected_sha256, digest, version, now,
                ),
            )
        return ArtifactCommit(
            lease.run_id, resource, commit_id, digest, version,
            lease.fencing_token, now, "committed",
        )

    def read_completed_artifact(self, run_id: str, resource: str) -> ArtifactRecord | None:
        """Read an artifact for host-side export after the entire run succeeds.

        Unlike read_artifact(), this is not a worker API: it accepts no lease and
        is intended only for the trusted host that owns the coordinator. Workers
        must never receive the coordinator database path or direct SQL access.

        Export is allowed only after finish_run() marks the complete task plan
        successful. The writer task, its completion fence, declared write scope,
        latest commit receipt, artifact version, and content digest are checked
        in one read transaction.
        """
        self._validate_identifier(run_id, "run_id")
        resource = _artifact_path(resource)
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN")
                run = db.execute(
                    "SELECT state FROM runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if run is None:
                    raise CoordinatorError("Unknown run")
                if run["state"] != "completed":
                    raise ArtifactConflictError(
                        "Artifacts can be exported only after a fully successful run"
                    )
                row = db.execute(
                    "SELECT content,sha256,version,updated_task_id,fencing_token,updated_ns "
                    "FROM artifacts WHERE run_id=? AND resource=?",
                    (run_id, resource),
                ).fetchone()
                if row is None:
                    db.commit()
                    return None
                writer = db.execute(
                    "SELECT state,completed_fence_token,contract_json "
                    "FROM tasks WHERE run_id=? AND task_id=?",
                    (run_id, row["updated_task_id"]),
                ).fetchone()
                if (writer is None or writer["state"] != "completed"
                        or writer["completed_fence_token"] != row["fencing_token"]):
                    raise ArtifactConflictError(
                        "Artifact writer completion does not match its fencing token"
                    )
                try:
                    contract = json.loads(writer["contract_json"])
                    write_scopes = tuple(contract["writes"])
                except (TypeError, ValueError, KeyError) as exc:
                    raise CoordinatorError("Stored writer contract is invalid") from exc
                if not _within_scope(resource, write_scopes):
                    raise CoordinatorError("Artifact is outside the completed writer's scope")
                receipt = db.execute(
                    "SELECT task_id,resource,fencing_token,new_sha256,version "
                    "FROM artifact_commits WHERE run_id=? AND resource=? AND version=?",
                    (run_id, resource, row["version"]),
                ).fetchone()
                if (receipt is None or receipt["task_id"] != row["updated_task_id"]
                        or receipt["resource"] != resource
                        or receipt["fencing_token"] != row["fencing_token"]
                        or receipt["new_sha256"] != row["sha256"]
                        or receipt["version"] != row["version"]):
                    raise CoordinatorError("Artifact commit receipt does not match stored content")
                payload = bytes(row["content"])
                digest = hashlib.sha256(payload).hexdigest()
                if digest != row["sha256"]:
                    raise CoordinatorError("Stored artifact failed integrity validation")
                result = ArtifactRecord(
                    run_id, resource, payload, digest, row["version"],
                    row["updated_task_id"], row["fencing_token"], row["updated_ns"],
                )
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise

    def read_artifact(self, lease: AgentLease, resource: str) -> ArtifactRecord | None:
        """Read a workspace artifact only within the active task's declared scopes."""
        if not isinstance(lease, AgentLease):
            raise TypeError("Expected an AgentLease")
        resource = _artifact_path(resource)
        allowed_scopes = tuple(lease.task.reads) + tuple(lease.task.writes)
        if not _within_scope(resource, allowed_scopes):
            raise PermissionError("Artifact path is outside this task's declared read/write scopes")
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN")
                now = self._now()
                self._current_row(db, lease, now)
                row = db.execute(
                    "SELECT content,sha256,version,updated_task_id,fencing_token,updated_ns "
                    "FROM artifacts WHERE run_id=? AND resource=?",
                    (lease.run_id, resource),
                ).fetchone()
                if row is None:
                    db.commit()
                    return None
                if row["updated_task_id"] != lease.task.id:
                    source = db.execute(
                        "SELECT state FROM tasks WHERE run_id=? AND task_id=?",
                        (lease.run_id, row["updated_task_id"]),
                    ).fetchone()
                    if source is None or source["state"] != "completed":
                        raise ArtifactConflictError("Artifact is not visible until its writer task completes")
                payload = bytes(row["content"])
                digest = hashlib.sha256(payload).hexdigest()
                if digest != row["sha256"]:
                    raise CoordinatorError("Stored artifact failed integrity validation")
                result = ArtifactRecord(
                    lease.run_id, resource, payload, digest, row["version"],
                    row["updated_task_id"], row["fencing_token"], row["updated_ns"],
                )
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise

    def fail(self, lease: AgentLease, *, error_code: str, retryable: bool) -> str:
        """Release a current lease as pending (retry) or failed (terminal)."""
        if not isinstance(lease, AgentLease) or type(retryable) is not bool:
            raise TypeError("Expected an AgentLease and boolean retryable flag")
        if type(error_code) is not str or not _ERROR.fullmatch(error_code):
            raise ValueError("Invalid bounded error code")
        with self._transaction() as db:
            now = self._now()
            row = self._current_row(db, lease, now)
            run = db.execute(
                "SELECT max_attempts FROM runs WHERE run_id=?", (lease.run_id,)
            ).fetchone()
            can_retry = retryable and row["attempts"] < run["max_attempts"]
            state = "pending" if can_retry else "failed"
            db.execute(
                "UPDATE tasks SET state=?,lease_id=NULL,lease_owner=NULL,"
                "lease_expires_ns=NULL,error_code=? "
                "WHERE run_id=? AND task_id=? AND lease_id=? AND fence_token=?",
                (state, error_code, lease.run_id, lease.task.id,
                 lease.lease_id, lease.fencing_token),
            )
        return state

    def reap_expired(self, run_id: str, plan: TaskPlan) -> int:
        """Expire old leases and block descendants whose dependencies failed."""
        self._validate_identifier(run_id, "run_id")
        plan = self._verified_plan(run_id, plan)
        with self._transaction() as db:
            now = self._now()
            count = self._expire_leases(db, run_id, now)
            self._block_failed_dependents(db, run_id, plan)
            return count

    def _verified_plan(self, run_id: str, plan: TaskPlan) -> TaskPlan:
        if not isinstance(plan, TaskPlan):
            raise PlanMismatchError("Caller plan does not match the registered run")
        snapshot = _snapshot_plan(plan)
        if _plan_hash(snapshot) != self._registered_plan_hash(run_id):
            raise PlanMismatchError("Caller plan does not match the registered run")
        return snapshot

    def _registered_plan_hash(self, run_id: str) -> str:
        with closing(self._connect()) as db:
            row = db.execute("SELECT plan_hash FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise CoordinatorError("Unknown run")
            return row["plan_hash"]

    def status(self, run_id: str) -> dict[str, object]:
        self._validate_identifier(run_id, "run_id")
        with closing(self._connect()) as db:
            run = db.execute(
                "SELECT plan_hash,state,max_parallel,max_attempts,lease_ns,next_fence "
                "FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise CoordinatorError("Unknown run")
            counts = {state: 0 for state in
                      ("pending", "leased", "completed", "failed", "blocked", "cancelled")}
            for row in db.execute(
                "SELECT state,COUNT(*) AS count FROM tasks WHERE run_id=? GROUP BY state",
                (run_id,),
            ).fetchall():
                counts[row["state"]] = row["count"]
            return {
                "run_id": run_id,
                "plan_hash": run["plan_hash"],
                "state": run["state"],
                "max_parallel": run["max_parallel"],
                "max_attempts": run["max_attempts"],
                "lease_ns": run["lease_ns"],
                "next_fencing_token": run["next_fence"],
                "counts": counts,
            }

    def finish_run(self, run_id: str, plan: TaskPlan) -> str:
        """Finalize only after every task is completed or terminally blocked/failed."""
        self._validate_identifier(run_id, "run_id")
        plan = self._verified_plan(run_id, plan)
        not_ready = False
        final: str | None = None
        with self._transaction() as db:
            now = self._now()
            run = db.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise CoordinatorError("Unknown run")
            if run["state"] != "active":
                return run["state"]
            self._expire_leases(db, run_id, now)
            self._block_failed_dependents(db, run_id, plan)
            states = [row["state"] for row in db.execute(
                "SELECT state FROM tasks WHERE run_id=?", (run_id,)
            ).fetchall()]
            if any(state in {"pending", "leased"} for state in states):
                not_ready = True
            else:
                final = "completed" if all(state == "completed" for state in states) else "finished_with_failures"
                db.execute("UPDATE runs SET state=? WHERE run_id=?", (final, run_id))
        if not_ready:
            raise RunNotReadyError("Pending or leased tasks remain")
        if final is None:
            raise CoordinatorError("Run finalization did not produce a state")
        return final

    def abort_run(self, run_id: str) -> bool:
        """Invalidate all leases and stop further claims; does not kill worker processes."""
        self._validate_identifier(run_id, "run_id")
        with self._transaction() as db:
            run = db.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise CoordinatorError("Unknown run")
            if run["state"] != "active":
                return False
            db.execute(
                "UPDATE tasks SET state='cancelled',lease_id=NULL,lease_owner=NULL,"
                "lease_expires_ns=NULL,error_code='run_aborted' "
                "WHERE run_id=? AND state IN ('pending','leased')",
                (run_id,),
            )
            db.execute("UPDATE runs SET state='aborted' WHERE run_id=?", (run_id,))
            return True

