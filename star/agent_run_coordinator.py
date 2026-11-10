"""Durable, single-host lease coordination for STAR's read-only agent DAGs.

This module coordinates trusted application-defined workers across processes.
It does not execute tools or workers. Every claim receives a monotonically
increasing run-scoped fencing token; expired/replaced workers cannot commit
results to this coordinator's ledger.

Important boundary: the fencing token protects this SQLite result ledger only.
It does NOT make arbitrary filesystem, Git, Roblox, HTTP, or device side effects
safe. Mutating workers must use a separate resource-side fencing/CAS gateway.
This v1 rejects Task contracts that declare writes.
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

_SCHEMA_VERSION = 2
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_ERROR = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_TERMINAL = frozenset({"completed", "failed", "blocked", "cancelled"})


class CoordinatorError(RuntimeError):
    """Base class for durable coordinator errors."""


class StaleLeaseError(CoordinatorError):
    """The lease is expired, replaced, aborted, or otherwise no longer current."""


class PlanMismatchError(CoordinatorError):
    """A run ID was reused with a different immutable task plan."""


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


class AgentRunCoordinator:
    """SQLite-backed lease coordinator for read-only multi-process agent runs.

    Use a local filesystem (NTFS/ext4/APFS), not a network share or sync folder.
    Multiple processes on the same host may open the same database. SQLite's
    BEGIN IMMEDIATE serializes claims; WAL allows concurrent readers.

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
        if database.is_symlink() or (database.exists() and not database.is_file()):
            raise PermissionError("Coordinator database must be an ordinary file")
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
            if version not in (0, _SCHEMA_VERSION):
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
                PRAGMA user_version=2;
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
        """Register an immutable read-only plan; return False if already identical."""
        self._validate_identifier(run_id, "run_id")
        if not isinstance(plan, TaskPlan) or not plan.tasks or len(plan.tasks) > 64:
            raise ValueError("Expected a nonempty TaskPlan containing at most 64 tasks")
        if any(task.writes for task in plan.tasks.values()):
            raise PermissionError(
                "Durable coordinator v1 accepts read-only tasks only; "
                "mutations need a resource-side fencing gateway"
            )
        digest = _plan_hash(plan)
        now = self._now()
        with self._transaction() as db:
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
            data = json.loads(payload)
            output.append(DependencyResult(
                dependency, row["role"], data["answer"],
                tuple(data["evidence"]), data["elapsed_ms"], digest,
            ))
        return tuple(output)

    def claim_next(self, run_id: str, worker_id: str) -> AgentLease | None:
        """Atomically claim one ready task and return only its direct dependency results."""
        self._validate_identifier(run_id, "run_id")
        self._validate_identifier(worker_id, "worker_id")
        now = self._now()
        plan = self._plans.get(run_id)
        if plan is None:
            raise CoordinatorError("Register the immutable plan on this coordinator instance first")
        with self._transaction() as db:
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
        now = self._now()
        with self._transaction() as db:
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
        now = self._now()
        with self._transaction() as db:
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

    def fail(self, lease: AgentLease, *, error_code: str, retryable: bool) -> str:
        """Release a current lease as pending (retry) or failed (terminal)."""
        if not isinstance(lease, AgentLease) or type(retryable) is not bool:
            raise TypeError("Expected an AgentLease and boolean retryable flag")
        if type(error_code) is not str or not _ERROR.fullmatch(error_code):
            raise ValueError("Invalid bounded error code")
        now = self._now()
        with self._transaction() as db:
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
        self._verify_plan(run_id, plan)
        now = self._now()
        with self._transaction() as db:
            count = self._expire_leases(db, run_id, now)
            self._block_failed_dependents(db, run_id, plan)
            return count

    def _verify_plan(self, run_id: str, plan: TaskPlan) -> None:
        if not isinstance(plan, TaskPlan) or _plan_hash(plan) != self._registered_plan_hash(run_id):
            raise PlanMismatchError("Caller plan does not match the registered run")

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
        self._verify_plan(run_id, plan)
        with self._transaction() as db:
            run = db.execute("SELECT state FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise CoordinatorError("Unknown run")
            if run["state"] != "active":
                return run["state"]
            self._block_failed_dependents(db, run_id, plan)
            states = [row["state"] for row in db.execute(
                "SELECT state FROM tasks WHERE run_id=?", (run_id,)
            ).fetchall()]
            if any(state in {"pending", "leased"} for state in states):
                raise RunNotReadyError("Pending or leased tasks remain")
            final = "completed" if all(state == "completed" for state in states) else "finished_with_failures"
            db.execute("UPDATE runs SET state=? WHERE run_id=?", (final, run_id))
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

