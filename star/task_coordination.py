"""Durable, generation-fenced task coordination for STAR.

Use an explicit SQLite path. now is UTC Unix time so worker leases survive process
restarts; do not pass monotonic-clock values. This ledger records state and
communication acknowledgements only: it never executes tools or grants permissions.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import hmac
import math
import sqlite3
import threading
from typing import Iterator


class TaskLedgerError(RuntimeError):
    """Base ledger error."""


class StaleGenerationError(TaskLedgerError):
    """A stale worker generation or lease attempted a write."""


class InvalidTransitionError(TaskLedgerError):
    """A state transition is not permitted."""


class DuplicateEventError(TaskLedgerError):
    """An idempotency key was reused for another operation."""


class TaskStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReportStatus(str, Enum):
    QUEUED = "queued"
    PLAYED = "played"
    RETRACTED = "retracted"


@dataclass(frozen=True)
class TaskLedgerConfig:
    max_tasks: int = 10_000
    max_events: int = 8_192
    max_reports: int = 10_000
    max_title_chars: int = 512
    max_reference_chars: int = 1_024
    busy_timeout_ms: int = 1_500

    def __post_init__(self) -> None:
        for name, low, high in (
            ("max_tasks", 1, 100_000),
            ("max_events", 1, 1_000_000),
            ("max_reports", 1, 100_000),
            ("max_title_chars", 1, 16_384),
            ("max_reference_chars", 1, 16_384),
            ("busy_timeout_ms", 1, 60_000),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer from {low} to {high}")


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    generation: int
    status: TaskStatus
    title: str
    priority: int
    created_at: float
    updated_at: float
    checkpoint_ref: str | None = None
    result_ref: str | None = None
    evidence_ref: str | None = None
    error_code: str | None = None
    lease_owner: str | None = None
    lease_expires_at: float | None = None


@dataclass(frozen=True)
class TaskClaim:
    """Lease token returned only to the claimant; keep it private."""

    task: TaskRecord
    lease_id: str = field(repr=False)


@dataclass(frozen=True)
class TaskReport:
    report_id: str
    task_id: str
    generation: int
    content_ref: str
    evidence_ref: str
    status: ReportStatus
    created_at: float
    updated_at: float
    playback_id: str | None = None
    played_at: float | None = None


@dataclass(frozen=True)
class TaskLedgerStats:
    tasks: int
    events: int
    reports: int
    queued_reports: int
    completed_tasks: int
    stale_reports: int


_ALLOWED = {
    TaskStatus.PROPOSED: {TaskStatus.ACCEPTED, TaskStatus.CANCELLED},
    TaskStatus.ACCEPTED: {TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.BLOCKED, TaskStatus.COMPLETED, TaskStatus.CANCELLED},
    TaskStatus.BLOCKED: {TaskStatus.ACCEPTED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
}


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    value = value.strip()
    if not value or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} must be non-empty and at most {limit} characters")
    return value


def _time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("now must be a finite non-negative UTC Unix timestamp")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or value < 0:
        raise ValueError("now must be a finite non-negative UTC Unix timestamp")
    return float(value)


def _lease_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("lease_seconds must be between 5 and 3600")
    try:
        valid = math.isfinite(value) and 5 <= value <= 3600
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("lease_seconds must be between 5 and 3600")
    return float(value)


class TaskLedger:
    """SQLite task state, worker leases, evidence references, and spoken-report receipts.

    The database stores a hash of each lease token, not the token itself. Task titles
    and artifact references are untrusted data. Store references rather than raw
    transcripts, audio, credentials, or viewer profiles.
    """

    SCHEMA_VERSION = 1

    def __init__(self, database: str, config: TaskLedgerConfig | None = None) -> None:
        if not isinstance(database, str) or not database.strip():
            raise ValueError("an explicit SQLite database path is required")
        if config is not None and not isinstance(config, TaskLedgerConfig):
            raise TypeError("config must be a TaskLedgerConfig")
        self.config = config or TaskLedgerConfig()
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(
            database, timeout=self.config.busy_timeout_ms / 1000,
            isolation_level=None, check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute(f"PRAGMA busy_timeout = {self.config.busy_timeout_ms}")
            if database != ":memory:":
                self._db.execute("PRAGMA journal_mode = WAL")
                self._db.execute("PRAGMA synchronous = NORMAL")
            self._init_schema()
        except Exception:
            self._db.close()
            self._closed = True
            raise

    def __enter__(self) -> "TaskLedger":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    @contextmanager
    def _tx(self) -> Iterator[None]:
        with self._lock:
            self._ensure_open()
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._db.execute("ROLLBACK")
                raise
            else:
                try:
                    self._db.execute("COMMIT")
                except Exception:
                    self._db.execute("ROLLBACK")
                    raise

    def _ensure_open(self) -> None:
        if self._closed:
            raise TaskLedgerError("task ledger is closed")

    def _init_schema(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > self.SCHEMA_VERSION:
            raise TaskLedgerError("database schema is newer than this STAR build")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                generation INTEGER NOT NULL CHECK(generation >= 1),
                status TEXT NOT NULL,
                title TEXT NOT NULL,
                priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 100),
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                checkpoint_ref TEXT,
                result_ref TEXT,
                evidence_ref TEXT,
                error_code TEXT,
                lease_owner TEXT,
                lease_hash TEXT,
                lease_expires_at REAL
            );
            CREATE TABLE IF NOT EXISTS task_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                task_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS task_events_task
                ON task_events(task_id, sequence);
            CREATE TABLE IF NOT EXISTS task_reports (
                report_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                generation INTEGER NOT NULL,
                content_ref TEXT NOT NULL,
                evidence_ref TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                playback_id TEXT,
                played_at REAL
            );
            CREATE INDEX IF NOT EXISTS task_reports_pending
                ON task_reports(status, task_id, generation, created_at);
            """
        )
        if version == 0:
            self._db.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    @staticmethod
    def _hash_lease(lease_id: str) -> str:
        return hashlib.sha256(lease_id.encode("utf-8")).hexdigest()

    def _event_seen(self, event_id: str, task_id: str, generation: int, kind: str) -> bool:
        row = self._db.execute(
            "SELECT task_id, generation, event_type FROM task_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return False
        if (row["task_id"], row["generation"], row["event_type"]) != (task_id, generation, kind):
            raise DuplicateEventError("event_id was already used for another operation")
        return True

    def _event(self, event_id: str, task_id: str, generation: int, kind: str, now: float) -> None:
        self._db.execute(
            "INSERT INTO task_events(event_id, task_id, generation, event_type, occurred_at) VALUES(?,?,?,?,?)",
            (event_id, task_id, generation, kind, now),
        )
        excess = self._db.execute("SELECT COUNT(*) FROM task_events").fetchone()[0] - self.config.max_events
        if excess > 0:
            self._db.execute(
                "DELETE FROM task_events WHERE sequence IN "
                "(SELECT sequence FROM task_events ORDER BY sequence LIMIT ?)", (excess,),
            )

    def _task(self, task_id: str) -> TaskRecord:
        row = self._db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown task: {task_id}")
        return TaskRecord(
            task_id=row["task_id"], generation=row["generation"], status=TaskStatus(row["status"]),
            title=row["title"], priority=row["priority"], created_at=row["created_at"],
            updated_at=row["updated_at"], checkpoint_ref=row["checkpoint_ref"],
            result_ref=row["result_ref"], evidence_ref=row["evidence_ref"],
            error_code=row["error_code"], lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
        )

    def _report(self, report_id: str) -> TaskReport:
        row = self._db.execute("SELECT * FROM task_reports WHERE report_id = ?", (report_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown report: {report_id}")
        return TaskReport(
            report_id=row["report_id"], task_id=row["task_id"], generation=row["generation"],
            content_ref=row["content_ref"], evidence_ref=row["evidence_ref"],
            status=ReportStatus(row["status"]), created_at=row["created_at"],
            updated_at=row["updated_at"], playback_id=row["playback_id"], played_at=row["played_at"],
        )

    @staticmethod
    def _generation(task: TaskRecord, expected: int) -> None:
        if task.generation != expected:
            raise StaleGenerationError(f"task is at generation {task.generation}, not {expected}")

    def _lease(self, task: TaskRecord, lease_id: str, now: float) -> None:
        row = self._db.execute("SELECT lease_hash FROM tasks WHERE task_id = ?", (task.task_id,)).fetchone()
        stored = row["lease_hash"] if row else None
        if task.status is not TaskStatus.RUNNING or stored is None:
            raise StaleGenerationError("worker does not own the running task")
        if not hmac.compare_digest(stored, self._hash_lease(lease_id)):
            raise StaleGenerationError("worker lease token is stale")
        if task.lease_expires_at is None or now >= task.lease_expires_at:
            raise StaleGenerationError("worker lease has expired")

    def create_task(self, task_id: str, title: str, *, now: float, event_id: str, priority: int = 50) -> TaskRecord:
        task_id = _text(task_id, "task_id", 128)
        title = _text(title, "title", self.config.max_title_chars)
        event_id = _text(event_id, "event_id", 128)
        now = _time(now)
        if type(priority) is not int or not 0 <= priority <= 100:
            raise ValueError("priority must be an integer from 0 to 100")
        with self._tx():
            if self._event_seen(event_id, task_id, 1, "create"):
                return self._task(task_id)
            if self._db.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone():
                raise DuplicateEventError("task_id already exists")
            count = self._db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            if count >= self.config.max_tasks:
                raise TaskLedgerError("task capacity reached")
            self._db.execute(
                "INSERT INTO tasks(task_id,generation,status,title,priority,created_at,updated_at) "
                "VALUES(?,1,?,?,?,?,?)",
                (task_id, TaskStatus.PROPOSED.value, title, priority, now, now),
            )
            self._event(event_id, task_id, 1, "create", now)
            return self._task(task_id)

    def transition(
        self, task_id: str, generation: int, target: TaskStatus, *,
        now: float, event_id: str, lease_id: str | None = None,
        checkpoint_ref: str | None = None, result_ref: str | None = None,
        evidence_ref: str | None = None, error_code: str | None = None,
    ) -> TaskRecord:
        task_id = _text(task_id, "task_id", 128)
        event_id = _text(event_id, "event_id", 128)
        now = _time(now)
        if type(generation) is not int or generation < 1 or not isinstance(target, TaskStatus):
            raise ValueError("generation or target is invalid")
        if target is TaskStatus.COMPLETED and (not result_ref or not evidence_ref):
            raise ValueError("completion requires result_ref and evidence_ref")
        checkpoint_ref = _text(checkpoint_ref, "checkpoint_ref", self.config.max_reference_chars) if checkpoint_ref else None
        result_ref = _text(result_ref, "result_ref", self.config.max_reference_chars) if result_ref else None
        evidence_ref = _text(evidence_ref, "evidence_ref", self.config.max_reference_chars) if evidence_ref else None
        error_code = _text(error_code, "error_code", 96) if error_code else None
        lease_id = _text(lease_id, "lease_id", 128) if lease_id else None
        with self._tx():
            kind = f"transition:{target.value}"
            if self._event_seen(event_id, task_id, generation, kind):
                return self._task(task_id)
            task = self._task(task_id)
            self._generation(task, generation)
            if target not in _ALLOWED[task.status]:
                raise InvalidTransitionError(f"cannot transition {task.status.value} to {target.value}")
            if task.status is TaskStatus.RUNNING:
                if lease_id is None:
                    raise InvalidTransitionError("running transitions require the worker lease")
                self._lease(task, lease_id, now)
            elif lease_id is not None:
                raise InvalidTransitionError("lease_id is valid only for a running task")
            if checkpoint_ref and target not in {TaskStatus.BLOCKED, TaskStatus.RUNNING}:
                raise InvalidTransitionError("checkpoint_ref requires running or blocked state")
            self._db.execute(
                """UPDATE tasks SET status=?,updated_at=?,checkpoint_ref=COALESCE(?,checkpoint_ref),
                   result_ref=?,evidence_ref=?,error_code=?,lease_owner=NULL,lease_hash=NULL,
                   lease_expires_at=NULL WHERE task_id=?""",
                (target.value, now, checkpoint_ref,
                 result_ref if target is TaskStatus.COMPLETED else None,
                 evidence_ref if target is TaskStatus.COMPLETED else None,
                 error_code if target in {TaskStatus.BLOCKED, TaskStatus.CANCELLED} else None, task_id),
            )
            self._event(event_id, task_id, generation, kind, now)
            return self._task(task_id)

    def claim_task(
        self, task_id: str, generation: int, worker_id: str, lease_id: str, *,
        now: float, event_id: str, lease_seconds: float = 90.0,
    ) -> TaskClaim:
        task_id = _text(task_id, "task_id", 128)
        worker_id = _text(worker_id, "worker_id", 128)
        lease_id = _text(lease_id, "lease_id", 128)
        event_id = _text(event_id, "event_id", 128)
        now, lease_seconds = _time(now), _lease_duration(lease_seconds)
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be positive")
        with self._tx():
            if self._event_seen(event_id, task_id, generation, "claim"):
                task = self._task(task_id)
                self._generation(task, generation)
                self._lease(task, lease_id, now)
                return TaskClaim(task, lease_id)
            task = self._task(task_id)
            self._generation(task, generation)
            next_generation = generation
            if task.status is TaskStatus.RUNNING:
                if task.lease_expires_at is None or now < task.lease_expires_at:
                    raise InvalidTransitionError("task already has an active lease")
                next_generation += 1
            elif task.status is not TaskStatus.ACCEPTED:
                raise InvalidTransitionError("only accepted or expired running tasks can be claimed")
            self._db.execute(
                """UPDATE tasks SET generation=?,status=?,updated_at=?,lease_owner=?,lease_hash=?,
                   lease_expires_at=? WHERE task_id=?""",
                (next_generation, TaskStatus.RUNNING.value, now, worker_id,
                 self._hash_lease(lease_id), now + lease_seconds, task_id),
            )
            self._event(event_id, task_id, generation, "claim", now)
            return TaskClaim(self._task(task_id), lease_id)

    def renew_lease(
        self, task_id: str, generation: int, lease_id: str, *,
        now: float, event_id: str, lease_seconds: float = 90.0,
    ) -> TaskClaim:
        task_id, lease_id = _text(task_id, "task_id", 128), _text(lease_id, "lease_id", 128)
        event_id = _text(event_id, "event_id", 128)
        now, lease_seconds = _time(now), _lease_duration(lease_seconds)
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be positive")
        with self._tx():
            if self._event_seen(event_id, task_id, generation, "renew"):
                task = self._task(task_id)
                self._generation(task, generation)
                self._lease(task, lease_id, now)
                return TaskClaim(task, lease_id)
            task = self._task(task_id)
            self._generation(task, generation)
            self._lease(task, lease_id, now)
            self._db.execute(
                "UPDATE tasks SET lease_expires_at=?,updated_at=? WHERE task_id=?",
                (now + lease_seconds, now, task_id),
            )
            self._event(event_id, task_id, generation, "renew", now)
            return TaskClaim(self._task(task_id), lease_id)

    def checkpoint_task(
        self, task_id: str, generation: int, checkpoint_ref: str, *,
        now: float, event_id: str, lease_id: str,
    ) -> TaskRecord:
        task_id = _text(task_id, "task_id", 128)
        checkpoint_ref = _text(checkpoint_ref, "checkpoint_ref", self.config.max_reference_chars)
        event_id, lease_id = _text(event_id, "event_id", 128), _text(lease_id, "lease_id", 128)
        now = _time(now)
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be positive")
        with self._tx():
            if self._event_seen(event_id, task_id, generation, "checkpoint"):
                return self._task(task_id)
            task = self._task(task_id)
            self._generation(task, generation)
            self._lease(task, lease_id, now)
            self._db.execute(
                "UPDATE tasks SET checkpoint_ref=?,updated_at=? WHERE task_id=?",
                (checkpoint_ref, now, task_id),
            )
            self._event(event_id, task_id, generation, "checkpoint", now)
            return self._task(task_id)

    def retry_task(
        self, task_id: str, generation: int, *, now: float, event_id: str,
        checkpoint_ref: str | None = None,
    ) -> TaskRecord:
        task_id, event_id = _text(task_id, "task_id", 128), _text(event_id, "event_id", 128)
        now = _time(now)
        checkpoint_ref = _text(checkpoint_ref, "checkpoint_ref", self.config.max_reference_chars) if checkpoint_ref else None
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be positive")
        with self._tx():
            if self._event_seen(event_id, task_id, generation, "retry"):
                return self._task(task_id)
            task = self._task(task_id)
            self._generation(task, generation)
            if task.status not in {TaskStatus.BLOCKED, TaskStatus.COMPLETED}:
                raise InvalidTransitionError("only blocked/completed tasks can be retried")
            self._db.execute(
                """UPDATE tasks SET generation=?,status=?,updated_at=?,checkpoint_ref=COALESCE(?,checkpoint_ref),
                   result_ref=NULL,evidence_ref=NULL,error_code=NULL,lease_owner=NULL,lease_hash=NULL,
                   lease_expires_at=NULL WHERE task_id=?""",
                (generation + 1, TaskStatus.ACCEPTED.value, now, checkpoint_ref, task_id),
            )
            self._event(event_id, task_id, generation, "retry", now)
            return self._task(task_id)

    def queue_report(
        self, report_id: str, task_id: str, generation: int, content_ref: str,
        evidence_ref: str, *, now: float, event_id: str,
    ) -> TaskReport:
        report_id, task_id = _text(report_id, "report_id", 128), _text(task_id, "task_id", 128)
        content_ref = _text(content_ref, "content_ref", self.config.max_reference_chars)
        evidence_ref = _text(evidence_ref, "evidence_ref", self.config.max_reference_chars)
        event_id, now = _text(event_id, "event_id", 128), _time(now)
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be positive")
        kind = f"report:{report_id}"
        with self._tx():
            if self._event_seen(event_id, task_id, generation, kind):
                return self._report(report_id)
            task = self._task(task_id)
            self._generation(task, generation)
            if task.status not in {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.COMPLETED}:
                raise InvalidTransitionError("reports require a running, blocked, or completed task")
            if task.status is TaskStatus.COMPLETED and task.evidence_ref != evidence_ref:
                raise ValueError("completion report must reference verified task evidence")
            if self._db.execute("SELECT 1 FROM task_reports WHERE report_id=?", (report_id,)).fetchone():
                raise DuplicateEventError("report_id already exists")
            count = self._db.execute("SELECT COUNT(*) FROM task_reports").fetchone()[0]
            if count >= self.config.max_reports:
                raise TaskLedgerError("report capacity reached")
            self._db.execute(
                """INSERT INTO task_reports(report_id,task_id,generation,content_ref,evidence_ref,status,
                   created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
                (report_id, task_id, generation, content_ref, evidence_ref,
                 ReportStatus.QUEUED.value, now, now),
            )
            self._event(event_id, task_id, generation, kind, now)
            return self._report(report_id)

    def mark_report_played(
        self, report_id: str, generation: int, playback_id: str, *,
        now: float, event_id: str,
    ) -> TaskReport:
        report_id, playback_id = _text(report_id, "report_id", 128), _text(playback_id, "playback_id", 128)
        event_id, now = _text(event_id, "event_id", 128), _time(now)
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be positive")
        with self._tx():
            report = self._report(report_id)
            kind = f"played:{report_id}"
            if self._event_seen(event_id, report.task_id, generation, kind):
                return self._report(report_id)
            if report.generation != generation:
                raise StaleGenerationError("report belongs to another task generation")
            task = self._task(report.task_id)
            self._generation(task, generation)
            if report.status is ReportStatus.PLAYED:
                if report.playback_id == playback_id:
                    return report
                raise InvalidTransitionError("report already acknowledged by another playback")
            if report.status is not ReportStatus.QUEUED or now < report.created_at:
                raise InvalidTransitionError("report is not queued or playback time is invalid")
            self._db.execute(
                "UPDATE task_reports SET status=?,playback_id=?,played_at=?,updated_at=? WHERE report_id=?",
                (ReportStatus.PLAYED.value, playback_id, now, now, report_id),
            )
            self._event(event_id, report.task_id, generation, kind, now)
            return self._report(report_id)

    def retract_report(self, report_id: str, generation: int, *, now: float, event_id: str) -> TaskReport:
        report_id, event_id = _text(report_id, "report_id", 128), _text(event_id, "event_id", 128)
        now = _time(now)
        if type(generation) is not int or generation < 1:
            raise ValueError("generation must be positive")
        with self._tx():
            report = self._report(report_id)
            kind = f"retract:{report_id}"
            if self._event_seen(event_id, report.task_id, generation, kind):
                return self._report(report_id)
            task = self._task(report.task_id)
            self._generation(task, generation)
            if report.generation != generation:
                raise StaleGenerationError("cannot retract an old-generation report")
            if report.status is not ReportStatus.QUEUED:
                raise InvalidTransitionError("only queued reports can be retracted")
            self._db.execute(
                "UPDATE task_reports SET status=?,updated_at=? WHERE report_id=?",
                (ReportStatus.RETRACTED.value, now, report_id),
            )
            self._event(event_id, report.task_id, generation, kind, now)
            return self._report(report_id)

    def get_task(self, task_id: str) -> TaskRecord | None:
        task_id = _text(task_id, "task_id", 128)
        with self._lock:
            self._ensure_open()
            row = self._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return self._task_from_row(row) if row else None

    def pending_reports(self, *, limit: int = 100) -> tuple[TaskReport, ...]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be from 1 to 500")
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                """SELECT r.* FROM task_reports r JOIN tasks t ON t.task_id=r.task_id
                   WHERE r.status=? AND r.generation=t.generation AND t.status!=?
                   ORDER BY t.priority DESC,r.created_at ASC LIMIT ?""",
                (ReportStatus.QUEUED.value, TaskStatus.CANCELLED.value, limit),
            ).fetchall()
            return tuple(self._report_from_row(row) for row in rows)

    @property
    def stats(self) -> TaskLedgerStats:
        with self._lock:
            self._ensure_open()
            count = lambda sql, args=(): self._db.execute(sql, args).fetchone()[0]
            return TaskLedgerStats(
                count("SELECT COUNT(*) FROM tasks"),
                count("SELECT COUNT(*) FROM task_events"),
                count("SELECT COUNT(*) FROM task_reports"),
                count("""SELECT COUNT(*) FROM task_reports r JOIN tasks t ON t.task_id=r.task_id
                         WHERE r.status=? AND r.generation=t.generation AND t.status!=?""",
                      (ReportStatus.QUEUED.value, TaskStatus.CANCELLED.value)),
                count("SELECT COUNT(*) FROM tasks WHERE status=?", (TaskStatus.COMPLETED.value,)),
                count("""SELECT COUNT(*) FROM task_reports r JOIN tasks t ON t.task_id=r.task_id
                         WHERE r.generation!=t.generation"""),
            )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            row["task_id"], row["generation"], TaskStatus(row["status"]), row["title"],
            row["priority"], row["created_at"], row["updated_at"], row["checkpoint_ref"],
            row["result_ref"], row["evidence_ref"], row["error_code"],
            row["lease_owner"], row["lease_expires_at"],
        )

    @staticmethod
    def _report_from_row(row: sqlite3.Row) -> TaskReport:
        return TaskReport(
            row["report_id"], row["task_id"], row["generation"], row["content_ref"],
            row["evidence_ref"], ReportStatus(row["status"]), row["created_at"],
            row["updated_at"], row["playback_id"], row["played_at"],
        )
