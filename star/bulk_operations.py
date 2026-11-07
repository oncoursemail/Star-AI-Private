"""Durable, bounded bulk operations over trusted semantic adapters.

Submitting prepares an immutable intent; only ``run_batch`` dispatches it. The
integration owns authorization, preview approval, adapter policy, and feature
enablement. This module never interprets a command or executes a shell.

One engine owns a local ledger for its lifetime. Incomplete accepted/running
operations become ``outcome_unknown`` on recovery and are never replayed. This
is deliberately not an exactly-once protocol for external side effects.
Cancellation stops new dispatch and signals adapters; it cannot terminate a
remote request, undo an edit, or kill a Python callback.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
import uuid


_APPLICATION_ID = 0x5342554C  # SBUL; do not open an unrelated SQLite database.
_SCHEMA_VERSION = 1
_TERMINAL_BATCHES = frozenset({
    "succeeded", "partial", "failed", "cancelled", "expired", "stopped", "outcome_unknown",
})
_NO_RESULT = object()


class BulkValidationError(ValueError):
    """The requested intent is invalid or outside the adapter's target catalog."""


class _AdapterOutcome(RuntimeError):
    """Explicit adapter evidence, with a safe message and optional JSON receipt.

    The integration must remove credentials and private exception details before
    constructing these outcomes. Messages and bounded receipts reach status UI.
    """

    def __init__(self, message: str, *, result: Any = _NO_RESULT):
        super().__init__(message)
        self.result = result


class BulkConflictError(_AdapterOutcome):
    """An immutable intent, ownership, or precondition conflicts.

    An adapter may raise this only when it knows it did not make an uncertain
    change. Use OutcomeUnknown after a potentially applied mutation instead.
    """


class BulkNotFoundError(KeyError):
    """The requested batch does not exist."""


class OutcomeUnknown(_AdapterOutcome):
    """An adapter cannot determine whether its external effect completed."""


class OperationFailed(_AdapterOutcome):
    """The adapter confirms failure without an uncertain external effect."""


class OperationCancelled(_AdapterOutcome):
    """The adapter confirms safe cancellation, with no uncertain effect."""


class OperationPartial(_AdapterOutcome):
    """Some effects completed and the remaining effects conclusively did not.

    Include verified applied receipts in ``result``. If any remaining effect is
    uncertain, use OutcomeUnknown with those receipts instead.
    """


@dataclass(frozen=True)
class OperationContext:
    batch_id: str
    operation_id: str
    action: str
    target_id: str
    payload: dict[str, Any]
    expires_at: float | None
    cancel_event: threading.Event


@dataclass(frozen=True)
class BulkAdapter:
    run: Callable[[OperationContext], Any]
    targets: Callable[[], Collection[str]]
    mutating: bool = True
    version: str = "1"


def _identifier(value: Any, name: str, limit: int = 256) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > limit or any(ord(char) < 32 for char in value)):
        raise BulkValidationError(f"{name} must be a nonempty, bounded identifier")
    return value


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise BulkValidationError(f"{name} must be an integer from {low} to {high}")
    return value


def _json_chunks(value: Any):
    # Reject coercions such as integer dictionary keys, custom object encoders,
    # and excessive nesting. The adapter contract uses ordinary JSON values.
    pending = [(value, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if depth > 40 or visited > 250_000:
            raise BulkValidationError("JSON value is too deeply nested or complex")
        if type(item) is dict:
            if not all(isinstance(key, str) for key in item):
                raise BulkValidationError("JSON object keys must be strings")
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif item is not None and type(item) not in (str, bool, int, float):
            raise BulkValidationError("Only JSON-compatible values are accepted")
    return json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False,
                            separators=(",", ":")).iterencode(value)


def _json_bytes(value: Any, limit: int) -> tuple[bytes, bool]:
    data = bytearray()
    for chunk in _json_chunks(value):
        encoded = chunk.encode("utf-8")
        remaining = limit - len(data)
        data.extend(encoded[:remaining])
        if len(encoded) > remaining:
            return bytes(data), True
    return bytes(data), False


class _LedgerLock:
    """An OS-owned lock; a dead process releases it, a second live owner fails."""

    def __init__(self, path: Path):
        self.fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.fstat(self.fd).st_size == 0:
                os.write(self.fd, b"\0")
            os.lseek(self.fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self.fd)
            self.fd = -1
            raise BulkConflictError("This bulk ledger already has a live owner") from exc

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


class BulkOperationEngine:
    """Single-owner local ledger and a globally bounded adapter executor.

    ``run_batch`` is synchronous; the application may call it in its own
    background coordinator. The executor is shared across batches, so their
    combined callbacks never exceed ``max_workers``. The OS lock is held until
    ``close``; closing while a coordinator is active raises BulkConflictError.
    Use a dedicated local file, never a network-shared SQLite database.
    """

    def __init__(self, db_path: str | Path, adapters: Mapping[str, BulkAdapter], *,
                 max_workers: int = 4, max_targets: int = 32,
                 payload_limit_bytes: int = 2 * 1024 * 1024,
                 result_limit_bytes: int = 16384,
                 clock: Callable[[], float] = time.time):
        self.max_workers = _integer(max_workers, "max_workers", 1, 4)
        self.max_targets = _integer(max_targets, "max_targets", 1, 32)
        self.payload_limit_bytes = _integer(payload_limit_bytes, "payload_limit_bytes", 256, 2 * 1024 * 1024)
        self.result_limit_bytes = _integer(result_limit_bytes, "result_limit_bytes", 256, 65536)
        if not callable(clock):
            raise BulkValidationError("clock must be callable")
        self._clock = clock
        self._adapters = dict(adapters)
        for action, adapter in self._adapters.items():
            _identifier(action, "action", 64)
            if (not isinstance(adapter, BulkAdapter) or not callable(adapter.run)
                    or not callable(adapter.targets) or type(adapter.mutating) is not bool):
                raise BulkValidationError("Each action must register a trusted BulkAdapter")
            _identifier(adapter.version, "adapter version", 64)
        if str(db_path) == ":memory:":
            raise BulkValidationError("A durable local ledger file is required")
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state_lock = threading.RLock()
        self._active: dict[str, threading.Event] = {}
        self._closed = False
        self._owner = _LedgerLock(self.path.with_name(self.path.name + ".lock"))
        try:
            self._initialize()
            self._recover()
            self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="star-bulk")
        except BaseException:
            self._owner.close()
            raise

    def _ensure_open(self):
        if self._closed:
            raise BulkConflictError("The bulk engine is closed")

    @contextmanager
    def _transaction(self):
        # Serialize short local transactions with close as well as each other.
        # Callback execution never holds this lock.
        with self._state_lock:
            self._ensure_open()
            connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _initialize(self):
        with self._transaction() as connection:
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if application not in (0, _APPLICATION_ID) or (application == 0 and tables):
                raise BulkConflictError("The selected file is not a bulk-operations ledger")
            if version not in (0, _SCHEMA_VERSION):
                raise BulkConflictError("Unsupported bulk ledger schema version")
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            if mode != "delete":
                raise BulkConflictError("The bulk ledger requires SQLite rollback journal mode")
            connection.execute("""CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                intent_sha256 TEXT NOT NULL, action TEXT NOT NULL,
                adapter_version TEXT NOT NULL, mutating INTEGER NOT NULL,
                targets_json TEXT NOT NULL, payload_json TEXT NOT NULL,
                canary_size INTEGER NOT NULL, failure_cutoff INTEGER NOT NULL,
                concurrency INTEGER NOT NULL, expires_at REAL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                started_at REAL, finished_at REAL, status TEXT NOT NULL,
                cancellation_requested INTEGER NOT NULL DEFAULT 0, stop_reason TEXT
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES batches(batch_id),
                target_id TEXT NOT NULL, position INTEGER NOT NULL, status TEXT NOT NULL,
                accepted_at REAL, started_at REAL, finished_at REAL,
                result_json TEXT, result_truncated INTEGER NOT NULL DEFAULT 0,
                error TEXT, error_code TEXT,
                UNIQUE(batch_id, target_id), UNIQUE(batch_id, position)
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS batches_recent ON batches(created_at DESC)")
            connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def _recover(self):
        now = self._clock()
        with self._transaction() as connection:
            rows = connection.execute("SELECT batch_id FROM batches WHERE status IN ('prepared','running')").fetchall()
            for row in rows:
                batch_id = row["batch_id"]
                changed = connection.execute("""UPDATE operations SET status='outcome_unknown',
                    finished_at=?, error_code='owner_interrupted',
                    error='Previous owner stopped before recording a conclusive result.'
                    WHERE batch_id=? AND status IN ('accepted','running')""", (now, batch_id)).rowcount
                if changed:
                    self._skip_pending(connection, batch_id, "skipped", "recovery_requires_review", now)
                    connection.execute("UPDATE batches SET stop_reason='recovery_requires_review' WHERE batch_id=?",
                                       (batch_id,))
                else:
                    batch = self._batch_row(connection, batch_id)
                    if batch["cancellation_requested"]:
                        self._skip_pending(connection, batch_id, "cancelled", "cancellation_requested", now)
                    elif batch["expires_at"] is not None and batch["expires_at"] <= now:
                        self._skip_pending(connection, batch_id, "expired", "deadline_expired", now)
                self._finish(connection, batch_id, now)

    @staticmethod
    def _batch_row(connection, batch_id: str):
        row = connection.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if row is None:
            raise BulkNotFoundError(batch_id)
        return row

    def _catalog(self, adapter: BulkAdapter) -> set[str]:
        catalog = adapter.targets()
        if not isinstance(catalog, Collection) or isinstance(catalog, (str, bytes)):
            raise BulkValidationError("The trusted adapter must return an explicit target collection")
        return {_identifier(target, "catalog target", 1024) for target in catalog}

    def submit(self, action: str, targets: Sequence[str], payload: Mapping[str, Any], *,
               idempotency_key: str, canary_size: int = 1, failure_cutoff: int = 1,
               concurrency: int | None = None, expires_at: float | None = None) -> dict:
        """Prepare one immutable, deduplicated explicit target list; never run it."""
        self._ensure_open()
        _identifier(action, "action", 64)
        _identifier(idempotency_key, "idempotency_key")
        adapter = self._adapters.get(action)
        if adapter is None:
            raise BulkValidationError("Unknown bulk action")
        if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)) or not targets:
            raise BulkValidationError("Select an explicit nonempty target list")
        if len(targets) > self.max_targets * 4:
            raise BulkValidationError("Too many input targets")
        selected = list(dict.fromkeys(_identifier(target, "target", 1024) for target in targets))
        _integer(len(selected), "target count", 1, self.max_targets)
        _integer(canary_size, "canary_size", 1, len(selected))
        _integer(failure_cutoff, "failure_cutoff", 1, self.max_targets)
        concurrency = self.max_workers if concurrency is None else concurrency
        _integer(concurrency, "concurrency", 1, self.max_workers)
        if expires_at is not None:
            if type(expires_at) not in (int, float) or not math.isfinite(expires_at) or expires_at <= 0:
                raise BulkValidationError("expires_at must be a finite Unix timestamp")
            expires_at = float(expires_at)
        if not isinstance(payload, Mapping):
            raise BulkValidationError("payload must be a JSON object")
        try:
            payload_bytes, too_large = _json_bytes(dict(payload), self.payload_limit_bytes)
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise BulkValidationError("payload must contain bounded JSON-compatible values") from exc
        if too_large:
            raise BulkValidationError("Bulk payload exceeds its byte limit")
        intent = dict(action=action, targets=selected, payload=json.loads(payload_bytes),
                      adapter_version=adapter.version, mutating=adapter.mutating,
                      canary_size=canary_size, failure_cutoff=failure_cutoff,
                      concurrency=concurrency, expires_at=expires_at)
        hasher = hashlib.sha256()
        for chunk in _json_chunks(intent):
            hasher.update(chunk.encode("utf-8"))
        digest = hasher.hexdigest()
        with self._transaction() as connection:
            existing = connection.execute("SELECT * FROM batches WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                if existing["intent_sha256"] != digest:
                    raise BulkConflictError("The idempotency key already belongs to a different intent")
                return self._snapshot(connection, existing, include_operations=True)
        if set(selected) - self._catalog(adapter):
            raise BulkValidationError("One or more selected targets are unknown to this action")
        now = self._clock()
        if expires_at is not None and expires_at <= now:
            raise BulkValidationError("The proposed batch has already expired")
        batch_id = uuid.uuid4().hex
        with self._transaction() as connection:
            # Another submitter may have prepared the same key during catalog validation.
            existing = connection.execute("SELECT * FROM batches WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                if existing["intent_sha256"] != digest:
                    raise BulkConflictError("The idempotency key already belongs to a different intent")
                return self._snapshot(connection, existing, include_operations=True)
            connection.execute("""INSERT INTO batches
                (batch_id,idempotency_key,intent_sha256,action,adapter_version,mutating,
                 targets_json,payload_json,canary_size,failure_cutoff,concurrency,expires_at,
                 created_at,updated_at,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'prepared')""",
                (batch_id, idempotency_key, digest, action, adapter.version, int(adapter.mutating),
                 json.dumps(selected), payload_bytes.decode("utf-8"), canary_size, failure_cutoff,
                 concurrency, expires_at, now, now))
            for position, target_id in enumerate(selected):
                operation_id = uuid.uuid5(uuid.UUID(batch_id), action + "\0" + target_id).hex
                connection.execute("""INSERT INTO operations
                    (operation_id,batch_id,target_id,position,status) VALUES (?,?,?,?, 'pending')""",
                    (operation_id, batch_id, target_id, position))
            return self._snapshot(connection, self._batch_row(connection, batch_id), include_operations=True)

    def _expire_prepared(self, connection, batch_id: str):
        row = self._batch_row(connection, batch_id)
        now = self._clock()
        if row["status"] == "prepared" and row["expires_at"] is not None and row["expires_at"] <= now:
            self._skip_pending(connection, batch_id, "expired", "deadline_expired", now)
            connection.execute("UPDATE batches SET stop_reason='deadline_expired' WHERE batch_id=?", (batch_id,))
            self._finish(connection, batch_id, now)

    def get_batch(self, batch_id: str) -> dict:
        with self._transaction() as connection:
            self._expire_prepared(connection, batch_id)
            return self._snapshot(connection, self._batch_row(connection, batch_id), include_operations=True)

    def get_payload(self, batch_id: str) -> dict:
        """Trusted-host access only; normal status responses omit potentially large/private input."""
        with self._transaction() as connection:
            return json.loads(self._batch_row(connection, batch_id)["payload_json"])

    def list_batches(self, limit: int = 50) -> list[dict]:
        _integer(limit, "limit", 1, 100)
        with self._transaction() as connection:
            rows = connection.execute("SELECT batch_id FROM batches ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                      (limit,)).fetchall()
            result = []
            for row in rows:
                self._expire_prepared(connection, row["batch_id"])
                result.append(self._snapshot(connection, self._batch_row(connection, row["batch_id"]),
                                             include_operations=False))
            return result

    @staticmethod
    def _snapshot(connection, row, *, include_operations: bool) -> dict:
        result = {key: row[key] for key in row.keys() if key not in ("targets_json", "payload_json")}
        result["targets"] = json.loads(row["targets_json"])
        result["cancellation_requested"] = bool(result["cancellation_requested"])
        result["mutating"] = bool(result["mutating"])
        result["terminal"] = result["status"] in _TERMINAL_BATCHES
        operations = connection.execute("SELECT * FROM operations WHERE batch_id=? ORDER BY position",
                                        (row["batch_id"],)).fetchall()
        result["counts"] = dict(Counter(operation["status"] for operation in operations))
        if include_operations:
            result["operations"] = []
            for operation in operations:
                item = dict(operation)
                encoded = item.pop("result_json")
                item["result"] = json.loads(encoded) if encoded is not None else None
                item["result_truncated"] = bool(item["result_truncated"])
                result["operations"].append(item)
        return result

    def cancel_batch(self, batch_id: str) -> dict:
        """Persist a cancellation request; do not infer remote termination."""
        with self._transaction() as connection:
            row = self._batch_row(connection, batch_id)
            if row["status"] not in _TERMINAL_BATCHES:
                now = self._clock()
                connection.execute("""UPDATE batches SET cancellation_requested=1,
                    stop_reason='cancellation_requested', updated_at=? WHERE batch_id=?""", (now, batch_id))
                self._skip_pending(connection, batch_id, "cancelled", "cancellation_requested", now)
                with self._state_lock:
                    event = self._active.get(batch_id)
                    if event is not None:
                        event.set()
                if row["status"] == "prepared":
                    self._finish(connection, batch_id, now)
            return self._snapshot(connection, self._batch_row(connection, batch_id), include_operations=True)

    @staticmethod
    def _skip_pending(connection, batch_id: str, status: str, reason: str, now: float):
        connection.execute("""UPDATE operations SET status=?,error_code=?,finished_at=?
            WHERE batch_id=? AND status='pending'""", (status, reason, now, batch_id))

    @staticmethod
    def _finish(connection, batch_id: str, now: float):
        statuses = Counter(row[0] for row in connection.execute("SELECT status FROM operations WHERE batch_id=?",
                                                               (batch_id,)))
        if statuses["outcome_unknown"]:
            status = "outcome_unknown"
        elif statuses["accepted"] or statuses["running"]:
            status = "running"
        elif statuses["pending"]:
            status = "prepared"
        elif len(statuses) == 1 and statuses["succeeded"]:
            status = "succeeded"
        elif statuses["succeeded"] or statuses["partial"]:
            status = "partial"
        elif statuses["failed"] or statuses["conflict"]:
            status = "failed"
        elif statuses["expired"]:
            status = "expired"
        elif statuses["cancelled"]:
            status = "cancelled"
        else:
            status = "stopped"
        connection.execute("UPDATE batches SET status=?,updated_at=?,finished_at=? WHERE batch_id=?",
                           (status, now, now if status in _TERMINAL_BATCHES else None, batch_id))

    def run_batch(self, batch_id: str, *, expected_intent_sha256: str | None = None) -> dict:
        """Explicitly execute a prepared batch; terminal/unknown operations never replay.

        Expiry limits admission, not an adapter's physical execution. Running
        adapters receive a cancellation signal on expiry and may still return a
        factual success. Callbacks must apply their own I/O timeouts.
        """
        with self._state_lock:
            self._ensure_open()
            if batch_id in self._active:
                raise BulkConflictError("This batch already has an active coordinator")
            event = threading.Event()
            self._active[batch_id] = event
        inflight: set[Future] = set()
        started = False
        try:
            snapshot = self.get_batch(batch_id)
            if expected_intent_sha256 is not None and snapshot["intent_sha256"] != expected_intent_sha256:
                raise BulkConflictError("The reviewed bulk intent digest does not match")
            if snapshot["status"] != "prepared":
                return snapshot
            adapter = self._adapters.get(snapshot["action"])
            if (adapter is None or adapter.version != snapshot["adapter_version"]
                    or adapter.mutating != snapshot["mutating"]):
                raise BulkConflictError("The prepared adapter is no longer registered with the same version")
            catalog = self._catalog(adapter)
            missing = set(snapshot["targets"]) - catalog
            with self._transaction() as connection:
                row = self._batch_row(connection, batch_id)
                if row["status"] != "prepared":
                    return self._snapshot(connection, row, include_operations=True)
                now = self._clock()
                if missing:
                    for target_id in missing:
                        connection.execute("""UPDATE operations SET status='conflict',
                            error_code='target_unavailable',finished_at=? WHERE batch_id=? AND target_id=?
                            AND status='pending'""", (now, batch_id, target_id))
                    self._skip_pending(connection, batch_id, "skipped", "target_unavailable", now)
                    connection.execute("UPDATE batches SET stop_reason='target_unavailable' WHERE batch_id=?", (batch_id,))
                    self._finish(connection, batch_id, now)
                    return self._snapshot(connection, self._batch_row(connection, batch_id), include_operations=True)
                connection.execute("""UPDATE batches SET status='running',started_at=COALESCE(started_at,?),
                    updated_at=? WHERE batch_id=?""", (now, now, batch_id))
                started = True
            self._run_stage(batch_id, adapter, event, snapshot, canary=True, inflight=inflight)
            with self._transaction() as connection:
                canaries = connection.execute("""SELECT status FROM operations WHERE batch_id=?
                    AND position<?""", (batch_id, snapshot["canary_size"])).fetchall()
                if any(row[0] != "succeeded" for row in canaries):
                    self._skip_pending(connection, batch_id, "skipped", "canary_not_successful", self._clock())
                    connection.execute("UPDATE batches SET stop_reason=COALESCE(stop_reason,'canary_not_successful')"
                                       " WHERE batch_id=?", (batch_id,))
                    proceed = False
                else:
                    proceed = True
            if proceed:
                self._run_stage(batch_id, adapter, event, snapshot, canary=False, inflight=inflight)
            with self._transaction() as connection:
                self._finish(connection, batch_id, self._clock())
            return self.get_batch(batch_id)
        except BaseException:
            # Never release ownership while callbacks could still apply effects.
            event.set()
            if inflight:
                wait(inflight)
            if started:
                try:
                    with self._transaction() as connection:
                        now = self._clock()
                        connection.execute("""UPDATE operations SET status='outcome_unknown',
                            finished_at=?,error_code='coordinator_interrupted'
                            WHERE batch_id=? AND status IN ('accepted','running')""", (now, batch_id))
                        self._skip_pending(connection, batch_id, "skipped", "coordinator_interrupted", now)
                        connection.execute("UPDATE batches SET stop_reason='coordinator_interrupted' WHERE batch_id=?",
                                           (batch_id,))
                        self._finish(connection, batch_id, now)
                except (OSError, sqlite3.Error):
                    # Propagate the original failure. Reopening the ledger will
                    # conservatively reconcile any unrecorded completions.
                    pass
            raise
        finally:
            with self._state_lock:
                self._active.pop(batch_id, None)

    def _run_stage(self, batch_id: str, adapter: BulkAdapter, event: threading.Event,
                   snapshot: dict, *, canary: bool, inflight: set[Future]):
        while True:
            completed = {future for future in inflight if future.done()}
            for future in completed:
                # Ledger failures must interrupt admission, not masquerade as adapter success.
                future.result()
            inflight.difference_update(completed)
            with self._transaction() as connection:
                now = self._clock()
                batch = self._batch_row(connection, batch_id)
                failures = connection.execute("""SELECT COUNT(*) FROM operations WHERE batch_id=?
                    AND status IN ('failed','conflict','partial','outcome_unknown')""", (batch_id,)).fetchone()[0]
                unknown = connection.execute("""SELECT 1 FROM operations WHERE batch_id=?
                    AND status='outcome_unknown' LIMIT 1""", (batch_id,)).fetchone()
                if batch["cancellation_requested"]:
                    event.set()
                    self._skip_pending(connection, batch_id, "cancelled", "cancellation_requested", now)
                elif batch["expires_at"] is not None and batch["expires_at"] <= now:
                    event.set()
                    self._skip_pending(connection, batch_id, "expired", "deadline_expired", now)
                    connection.execute("UPDATE batches SET stop_reason='deadline_expired' WHERE batch_id=?", (batch_id,))
                elif unknown or failures >= batch["failure_cutoff"]:
                    event.set()
                    reason = "outcome_requires_review" if unknown else "failure_cutoff"
                    self._skip_pending(connection, batch_id, "skipped", reason, now)
                    connection.execute("UPDATE batches SET stop_reason=? WHERE batch_id=?", (reason, batch_id))
                operator = "<" if canary else ">="
                available = batch["concurrency"] - len(inflight)
                rows = connection.execute(f"""SELECT operation_id FROM operations WHERE batch_id=?
                    AND status='pending' AND position {operator} ? ORDER BY position LIMIT ?""",
                    (batch_id, snapshot["canary_size"], available)).fetchall()
                for row in rows:
                    connection.execute("UPDATE operations SET status='accepted',accepted_at=? WHERE operation_id=?",
                                       (now, row["operation_id"]))
            # Persist acceptance before a callback can begin. A crash in this gap
            # is intentionally recovered as unknown, never automatically retried.
            for row in rows:
                inflight.add(self._pool.submit(self._invoke, batch_id, row["operation_id"], adapter, event))
            if not inflight:
                return
            wait(inflight, timeout=0.05, return_when=FIRST_COMPLETED)

    def _prevent_start(self, connection, batch, operation_id: str, event: threading.Event, now: float) -> bool:
        """Recheck queued admission under the same transaction that starts work.

        A callback that is already running may finish after another target fails.
        An accepted callback waiting in the shared pool must still pass this gate.
        """
        counts = Counter(row[0] for row in connection.execute(
            "SELECT status FROM operations WHERE batch_id=?", (batch["batch_id"],)))
        failures = sum(counts[status] for status in ("failed", "conflict", "partial", "outcome_unknown"))
        if batch["cancellation_requested"]:
            status, reason = "cancelled", "cancellation_requested"
        elif batch["expires_at"] is not None and batch["expires_at"] <= now:
            status, reason = "expired", "deadline_expired"
        elif counts["outcome_unknown"] or failures >= batch["failure_cutoff"]:
            status = "skipped"
            reason = "outcome_requires_review" if counts["outcome_unknown"] else "failure_cutoff"
        elif event.is_set():
            status, reason = "skipped", "coordinator_stopped"
        else:
            return False
        event.set()
        connection.execute("UPDATE operations SET status=?,finished_at=?,error_code=? WHERE operation_id=?",
                           (status, now, reason, operation_id))
        connection.execute("UPDATE batches SET stop_reason=COALESCE(stop_reason,?) WHERE batch_id=?",
                           (reason, batch["batch_id"]))
        return True

    def _invoke(self, batch_id: str, operation_id: str, adapter: BulkAdapter, event: threading.Event):
        with self._transaction() as connection:
            batch = self._batch_row(connection, batch_id)
            operation = connection.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            now = self._clock()
            if self._prevent_start(connection, batch, operation_id, event, now):
                return
            context = OperationContext(batch_id, operation_id, batch["action"], operation["target_id"],
                                       json.loads(batch["payload_json"]), batch["expires_at"], event)
        # Recheck membership immediately before execution as well as once before
        # the batch. The adapter still owns policy/precondition checks at mutation.
        try:
            if context.target_id not in self._catalog(adapter):
                raise BulkConflictError("Target is no longer available to this action")
        except Exception as exc:
            self._record(operation_id, "conflict", error=exc, error_code="target_preflight_failed")
            return
        with self._transaction() as connection:
            batch = self._batch_row(connection, batch_id)
            now = self._clock()
            if self._prevent_start(connection, batch, operation_id, event, now):
                return
            connection.execute("UPDATE operations SET status='running',started_at=? WHERE operation_id=?", (now, operation_id))
        try:
            result = adapter.run(context)
        except OutcomeUnknown as exc:
            self._record(operation_id, "outcome_unknown", result=exc.result,
                         error=exc, error_code="adapter_outcome_unknown")
        except BulkConflictError as exc:
            self._record(operation_id, "conflict", result=exc.result, error=exc, error_code="adapter_conflict")
        except OperationCancelled as exc:
            status = "expired" if context.expires_at is not None and context.expires_at <= self._clock() else "cancelled"
            self._record(operation_id, status, result=exc.result, error=exc, error_code="adapter_confirmed_cancel")
        except OperationPartial as exc:
            self._record(operation_id, "partial", result=exc.result, error=exc, error_code="adapter_confirmed_partial")
        except OperationFailed as exc:
            self._record(operation_id, "failed", result=exc.result, error=exc, error_code="adapter_confirmed_failure")
        except BaseException as exc:
            self._record(operation_id, "outcome_unknown" if adapter.mutating else "failed",
                         error=exc, error_code="adapter_exception")
        else:
            # A cancellation request cannot erase a returned, completed result.
            self._record(operation_id, "succeeded", result=result)

    def _record(self, operation_id: str, status: str, *, result: Any = _NO_RESULT,
                error: BaseException | None = None, error_code: str | None = None):
        encoded = None
        truncated = False
        if result is not _NO_RESULT:
            try:
                data, truncated = _json_bytes(result, self.result_limit_bytes)
                if truncated:
                    preview = data[:(self.result_limit_bytes - 128) // 6].decode("utf-8", errors="ignore")
                    encoded = json.dumps({"_truncated": True, "preview": preview}, ensure_ascii=False)
                else:
                    encoded = data.decode("utf-8")
            except (ValueError, TypeError, UnicodeError, RecursionError):
                encoded = '{"result_unavailable":"not_json_serializable"}'
        message = None
        if error is not None:
            if isinstance(error, _AdapterOutcome):
                try:
                    message = str(error)
                except Exception:
                    message = "Adapter could not provide an error message"
            else:
                message = "Adapter raised an unexpected exception; detailed messages are not exposed."
            message = message.encode("utf-8", errors="replace")[:min(4096, self.result_limit_bytes)].decode("utf-8", errors="ignore")
        with self._transaction() as connection:
            connection.execute("""UPDATE operations SET status=?,finished_at=?,result_json=?,
                result_truncated=?,error=?,error_code=? WHERE operation_id=?""",
                (status, self._clock(), encoded, int(truncated), message, error_code, operation_id))

    def close(self):
        """Release ownership only when all application coordinators have returned."""
        with self._state_lock:
            if self._closed:
                return
            if self._active:
                raise BulkConflictError("Cancel active batches and wait for their coordinators before closing")
            self._closed = True
        self._pool.shutdown(wait=True, cancel_futures=True)
        self._owner.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
