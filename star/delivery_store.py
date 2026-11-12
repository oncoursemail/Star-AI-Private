"""SQLite WAL persistence for STAR's content-free delivery ledger.

The database stores only opaque IDs, state/version metadata, timing metadata,
and SHA-256 digests. It never stores speech text, transcripts, audio, prompts,
viewer identities, voiceprints, or credentials.

Use a local disk path, not a network share or cloud-synchronized directory.
An in-flight claim/playback found after restart is fenced as RECOVERY_REQUIRED;
the host must stop and confirm old workers before reconciliation and retry.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable

from .delivery_ledger import (
    DeliveryConflict,
    DeliveryLease,
    DeliveryRecord,
    DeliveryReapReport,
    DeliveryState,
    DeliveryLedger,
)

_SCHEMA_VERSION = 1
_MAX_WALL_MS = 9_000_000_000_000_000
_DEFAULT_MAX_EVENTS = 100_000


class DeliveryStoreError(RuntimeError):
    """The durable delivery store could not safely commit or recover state."""


class DeliveryStoreConflict(DeliveryStoreError):
    """The SQLite record changed outside this ledger instance."""


class DeliveryStoreCorrupt(DeliveryStoreError):
    """Persisted delivery metadata failed schema or integrity validation."""


class SQLiteDeliveryLedger(DeliveryLedger):
    """DeliveryLedger with SQLite WAL snapshots and bounded transition history.

    Every successful state mutation is committed before returning. If SQLite
    fails, the in-memory mutation is rolled back. Monotonic times are rebased
    at startup from persisted wall-clock metadata; old leases are never trusted
    across a process/clock epoch.

    This is a single-writer runtime primitive. Version checks detect a second
    writer rather than silently overwriting it.
    """

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        clock_epoch: str,
        now_ms: int,
        wall_clock_ms: Callable[[], int] | None = None,
        max_records: int = 4096,
        max_lease_ms: int = 30_000,
        max_events: int = _DEFAULT_MAX_EVENTS,
    ) -> None:
        raw_path = os.fspath(database_path)
        if raw_path == ":memory:" or not raw_path:
            raise ValueError("database_path must be a durable local filesystem path")
        if type(max_events) is not int or not 100 <= max_events <= 1_000_000:
            raise ValueError("max_events must be in 100..1000000")
        self.database_path = Path(raw_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._wall_clock = wall_clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.max_events = max_events
        self._created_wall_by_id: dict[str, int] = {}
        self._updated_wall_by_id: dict[str, int] = {}
        self._deadline_wall_by_id: dict[str, int | None] = {}
        self._closed = False
        super().__init__(
            clock_epoch=clock_epoch,
            max_records=max_records,
            max_lease_ms=max_lease_ms,
        )
        self._now(now_ms)
        self._db = sqlite3.connect(
            str(self.database_path),
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        try:
            self._initialize_schema()
            self._load(now_ms=now_ms)
        except BaseException:
            self._db.close()
            self._closed = True
            raise
        if os.name != "nt":
            try:
                os.chmod(self.database_path, 0o600)
            except OSError:
                pass

    @staticmethod
    def _wall_value(value: object) -> int:
        if type(value) is not int or not 0 <= value <= _MAX_WALL_MS:
            raise ValueError("wall clock must be a bounded integer millisecond timestamp")
        return value

    def _wall_now(self) -> int:
        return self._wall_value(self._wall_clock())

    @staticmethod
    def _encode(record: DeliveryRecord) -> str:
        payload = asdict(record)
        payload["state"] = record.state.value
        payload["segment_sha256s"] = list(record.segment_sha256s)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(raw: str) -> DeliveryRecord:
        try:
            payload = json.loads(raw)
            expected = {
                "delivery_id", "task_id", "task_version", "result_sha256",
                "segment_sha256s", "completed_segments", "state", "version",
                "generation", "created_ms", "updated_ms", "deadline_ms",
                "attempt_id", "lease_expires_ms", "active_segment", "playback_id",
                "last_played_ms", "failure_code",
            }
            if type(payload) is not dict or set(payload) != expected:
                raise ValueError("unexpected delivery snapshot fields")
            if type(payload["segment_sha256s"]) is not list:
                raise ValueError("segment_sha256s must be a JSON array")
            payload["segment_sha256s"] = tuple(payload["segment_sha256s"])
            payload["state"] = DeliveryState(payload["state"])
            record = DeliveryRecord(**payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DeliveryStoreCorrupt("invalid persisted delivery snapshot") from exc

        DeliveryLedger._identifier(record.delivery_id, "delivery_id")
        DeliveryLedger._identifier(record.task_id, "task_id")
        DeliveryLedger._digest(record.result_sha256, "result_sha256")
        if not 1 <= len(record.segment_sha256s) <= 256:
            raise DeliveryStoreCorrupt("persisted segment count is out of bounds")
        for index, digest in enumerate(record.segment_sha256s):
            DeliveryLedger._digest(digest, f"segment_sha256s[{index}]")
        integer_fields = (
            ("task_version", record.task_version, 1),
            ("completed_segments", record.completed_segments, 0),
            ("version", record.version, 1),
            ("generation", record.generation, 0),
            ("created_ms", record.created_ms, 0),
            ("updated_ms", record.updated_ms, 0),
            ("last_played_ms", record.last_played_ms, 0),
        )
        for label, value, minimum in integer_fields:
            if type(value) is not int or value < minimum:
                raise DeliveryStoreCorrupt(f"invalid persisted {label}")
        if record.completed_segments > len(record.segment_sha256s):
            raise DeliveryStoreCorrupt("completed segment cursor exceeds segment count")
        for label, value in (
            ("deadline_ms", record.deadline_ms),
            ("lease_expires_ms", record.lease_expires_ms),
            ("active_segment", record.active_segment),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise DeliveryStoreCorrupt(f"invalid persisted {label}")
        for label, value in (
            ("attempt_id", record.attempt_id),
            ("playback_id", record.playback_id),
            ("failure_code", record.failure_code),
        ):
            if value is not None:
                DeliveryLedger._identifier(value, label)
        if record.state is DeliveryState.DELIVERED and record.completed_segments != len(record.segment_sha256s):
            raise DeliveryStoreCorrupt("delivered record has incomplete segments")
        if record.state in (DeliveryState.CLAIMED, DeliveryState.PLAYING):
            if (
                record.attempt_id is None
                or record.lease_expires_ms is None
                or record.active_segment != record.completed_segments
                or (record.state is DeliveryState.PLAYING and record.playback_id is None)
                or (record.state is DeliveryState.CLAIMED and record.playback_id is not None)
            ):
                raise DeliveryStoreCorrupt("active delivery has inconsistent lease metadata")
        elif any(value is not None for value in (
            record.attempt_id, record.lease_expires_ms, record.active_segment, record.playback_id
        )):
            raise DeliveryStoreCorrupt("inactive delivery retains active lease metadata")
        return record

    def _initialize_schema(self) -> None:
        mode = self._db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise DeliveryStoreError("SQLite refused WAL mode; use a supported local filesystem")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=5000")
        version = int(self._db.execute("PRAGMA user_version").fetchone()[0])
        if version not in (0, _SCHEMA_VERSION):
            raise DeliveryStoreError(f"unsupported delivery database schema version: {version}")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS delivery_records (
                delivery_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                state TEXT NOT NULL,
                record_json TEXT NOT NULL,
                created_wall_ms INTEGER NOT NULL,
                updated_wall_ms INTEGER NOT NULL,
                deadline_wall_ms INTEGER
            );
            CREATE TABLE IF NOT EXISTS delivery_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                state TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                recorded_wall_ms INTEGER NOT NULL,
                UNIQUE(delivery_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_delivery_events_delivery
                ON delivery_events(delivery_id, event_id);
            """
        )
        if version == 0:
            self._db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def _load(self, *, now_ms: int) -> None:
        wall_now = self._wall_now()
        rows = self._db.execute(
            """
            SELECT delivery_id, version, record_json, created_wall_ms,
                   updated_wall_ms, deadline_wall_ms
            FROM delivery_records ORDER BY created_wall_ms, delivery_id
            """
        ).fetchall()
        if len(rows) > self.max_records:
            raise DeliveryStoreCorrupt("persisted record count exceeds configured max_records")

        before: dict[str, DeliveryRecord] = {}
        for row in rows:
            record = self._decode(row["record_json"])
            if record.delivery_id != row["delivery_id"] or record.version != row["version"]:
                raise DeliveryStoreCorrupt("record key/version does not match its snapshot")
            created_wall = self._wall_value(row["created_wall_ms"])
            updated_wall = self._wall_value(row["updated_wall_ms"])
            deadline_wall = (
                None if row["deadline_wall_ms"] is None
                else self._wall_value(row["deadline_wall_ms"])
            )
            self._created_wall_by_id[record.delivery_id] = created_wall
            self._updated_wall_by_id[record.delivery_id] = updated_wall
            self._deadline_wall_by_id[record.delivery_id] = deadline_wall

            age = max(0, wall_now - created_wall)
            created_mono = max(0, now_ms - age)
            rebased_deadline = None
            wall_rollback = wall_now < updated_wall
            if deadline_wall is not None and not wall_rollback and deadline_wall > wall_now:
                rebased_deadline = now_ms + (deadline_wall - wall_now)

            rebased = replace(
                record,
                created_ms=created_mono,
                updated_ms=now_ms,
                deadline_ms=rebased_deadline,
            )
            before[record.delivery_id] = rebased
            self._records[record.delivery_id] = rebased

            deadline_due = (
                deadline_wall is not None
                and (wall_rollback or wall_now >= deadline_wall)
            )
            if deadline_due and rebased.state not in (
                DeliveryState.DELIVERED, DeliveryState.CANCELLED, DeliveryState.EXPIRED
            ):
                expired = replace(
                    rebased,
                    state=DeliveryState.EXPIRED,
                    version=rebased.version + 1,
                    generation=rebased.generation + 1,
                    updated_ms=now_ms,
                    attempt_id=None,
                    lease_expires_ms=None,
                    active_segment=None,
                    playback_id=None,
                    failure_code="deadline_expired_on_restore",
                )
                self._records[record.delivery_id] = expired
            elif rebased.state in (DeliveryState.CLAIMED, DeliveryState.PLAYING):
                super().mark_recovery_required(
                    record.delivery_id, rebased.version, now_ms=now_ms
                )

        self._persist_changes(before)

    def _persist_changes(self, before: dict[str, DeliveryRecord]) -> None:
        changed = [
            record for delivery_id, record in self._records.items()
            if before.get(delivery_id) != record
        ]
        if not changed:
            return
        wall_now = self._wall_now()
        metadata_updates: dict[str, tuple[int, int, int | None]] = {}
        self._db.execute("BEGIN IMMEDIATE")
        try:
            for record in changed:
                previous = before.get(record.delivery_id)
                row = self._db.execute(
                    """
                    SELECT version, created_wall_ms, deadline_wall_ms
                    FROM delivery_records WHERE delivery_id=?
                    """,
                    (record.delivery_id,),
                ).fetchone()
                if previous is None:
                    if row is not None:
                        raise DeliveryStoreConflict("delivery ID already exists in durable store")
                    created_wall = wall_now
                    deadline_wall = (
                        None if record.deadline_ms is None
                        else wall_now + max(0, record.deadline_ms - record.created_ms)
                    )
                    self._db.execute(
                        """
                        INSERT INTO delivery_records
                        (delivery_id, version, state, record_json, created_wall_ms,
                         updated_wall_ms, deadline_wall_ms)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.delivery_id, record.version, record.state.value,
                            self._encode(record), created_wall, wall_now, deadline_wall,
                        ),
                    )
                else:
                    if row is None or int(row["version"]) != previous.version:
                        raise DeliveryStoreConflict("durable delivery version changed outside this instance")
                    created_wall = int(row["created_wall_ms"])
                    deadline_wall = row["deadline_wall_ms"]
                    cursor = self._db.execute(
                        """
                        UPDATE delivery_records
                        SET version=?, state=?, record_json=?, updated_wall_ms=?
                        WHERE delivery_id=? AND version=?
                        """,
                        (
                            record.version, record.state.value, self._encode(record),
                            wall_now, record.delivery_id, previous.version,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise DeliveryStoreConflict("durable compare-and-swap update lost")
                self._db.execute(
                    """
                    INSERT INTO delivery_events
                    (delivery_id, version, state, snapshot_json, recorded_wall_ms)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record.delivery_id, record.version, record.state.value,
                        self._encode(record), wall_now,
                    ),
                )
                metadata_updates[record.delivery_id] = (
                    created_wall, wall_now,
                    None if deadline_wall is None else int(deadline_wall),
                )
            self._db.execute(
                """
                DELETE FROM delivery_events
                WHERE event_id <= (
                    SELECT COALESCE(MAX(event_id), 0) - ? FROM delivery_events
                )
                """,
                (self.max_events,),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        for delivery_id, (created_wall, updated_wall, deadline_wall) in metadata_updates.items():
            self._created_wall_by_id[delivery_id] = created_wall
            self._updated_wall_by_id[delivery_id] = updated_wall
            self._deadline_wall_by_id[delivery_id] = deadline_wall

    def _mutate(self, method_name: str, *args, **kwargs):
        with self._lock:
            if self._closed:
                raise DeliveryStoreError("delivery store is closed")
            before = dict(self._records)
            previous_now = self._last_now_ms
            method = getattr(super(SQLiteDeliveryLedger, self), method_name)
            try:
                result = method(*args, **kwargs)
            except BaseException:
                try:
                    self._persist_changes(before)
                except BaseException:
                    self._records = before
                    self._last_now_ms = previous_now
                    raise
                raise
            try:
                self._persist_changes(before)
            except BaseException:
                self._records = before
                self._last_now_ms = previous_now
                raise
            return result

    def create(self, *args, **kwargs) -> DeliveryRecord:
        return self._mutate("create", *args, **kwargs)

    def claim(self, *args, **kwargs) -> DeliveryLease:
        return self._mutate("claim", *args, **kwargs)

    def start_playback(self, *args, **kwargs) -> DeliveryLease:
        return self._mutate("start_playback", *args, **kwargs)

    def acknowledge_playback(self, *args, **kwargs) -> DeliveryRecord:
        return self._mutate("acknowledge_playback", *args, **kwargs)

    def fail(self, *args, **kwargs) -> DeliveryRecord:
        return self._mutate("fail", *args, **kwargs)

    def recover_expired_lease(self, *args, **kwargs) -> DeliveryRecord:
        return self._mutate("recover_expired_lease", *args, **kwargs)

    def mark_recovery_required(self, *args, **kwargs) -> DeliveryRecord:
        return self._mutate("mark_recovery_required", *args, **kwargs)

    def reconcile_after_restart(self, *args, **kwargs) -> DeliveryRecord:
        return self._mutate("reconcile_after_restart", *args, **kwargs)

    def cancel(self, *args, **kwargs) -> DeliveryRecord:
        return self._mutate("cancel", *args, **kwargs)

    def reap(self, *args, **kwargs) -> DeliveryReapReport:
        return self._mutate("reap", *args, **kwargs)

    def integrity_check(self) -> str:
        with self._lock:
            if self._closed:
                raise DeliveryStoreError("delivery store is closed")
            rows = self._db.execute("PRAGMA integrity_check").fetchall()
            result = "; ".join(str(row[0]) for row in rows)
            if result != "ok":
                raise DeliveryStoreCorrupt(result)
            return result

    def checkpoint(self, *, truncate: bool = False) -> tuple[int, int, int]:
        with self._lock:
            if self._closed:
                raise DeliveryStoreError("delivery store is closed")
            mode = "TRUNCATE" if truncate else "PASSIVE"
            row = self._db.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
            return int(row[0]), int(row[1]), int(row[2])

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def __enter__(self) -> "SQLiteDeliveryLedger":
        if self._closed:
            raise DeliveryStoreError("delivery store is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = [
    "DeliveryStoreError", "DeliveryStoreConflict", "DeliveryStoreCorrupt",
    "SQLiteDeliveryLedger",
]
