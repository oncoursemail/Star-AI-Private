"""Durable write-ahead intent journal for STAR artifact staging promotions.

The journal makes a single-host staging replacement recoverable across process
crashes. It does not make filesystem rename and SQLite commit one atomic
transaction, provide multi-process writer safety, or authorize source-tree writes.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_OPERATION_ID = re.compile(r"^[a-f0-9]{32}$")
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SCHEMA_VERSION = 1
_DATABASE_NAME = ".star-promotion-journal.sqlite3"


class PromotionJournalError(RuntimeError):
    """The durable staging journal could not safely record or reconcile work."""


@dataclass(frozen=True)
class PromotionIntent:
    operation_id: str
    run_id: str
    resource: str
    artifact_version: int
    expected_sha256: str | None
    new_sha256: str
    target_relpath: str
    temp_relpath: str
    created_ns: int


@dataclass(frozen=True)
class PromotionRecovery:
    operation_id: str
    status: str
    error_code: str = ""


class ArtifactPromotionJournal:
    """Small SQLite WAL journal for one trusted staging-root writer.

    Each PREPARED record is committed before the filesystem replacement. A
    later recovery pass can then determine whether the replacement happened,
    can safely finish it, or must stop on a compare-and-swap conflict.
    """

    def __init__(self, database_path: Path) -> None:
        if type(database_path) is not Path or not database_path.is_absolute():
            raise ValueError("Journal database path must be an absolute pathlib.Path")
        if database_path.name != _DATABASE_NAME or not database_path.parent.is_dir():
            raise ValueError("Journal database must be inside an existing staging root")
        if database_path.is_symlink():
            raise PromotionJournalError("Journal database cannot be a symlink")
        if database_path.exists() and not database_path.is_file():
            raise PromotionJournalError("Journal database must be a regular file")
        self.database_path = database_path
        if not database_path.exists():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(database_path, flags, 0o600)
            except FileExistsError:
                descriptor = None
            if descriptor is not None:
                os.close(descriptor)
        try:
            with closing(self._connect()) as db:
                mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if str(mode).lower() != "wal":
                    raise PromotionJournalError("SQLite WAL mode is required")
                version = int(db.execute("PRAGMA user_version").fetchone()[0])
                if version > _SCHEMA_VERSION:
                    raise PromotionJournalError("Journal schema is newer than this runtime")
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute(
                        """
                        CREATE TABLE IF NOT EXISTS promotions (
                            operation_id TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL,
                            resource TEXT NOT NULL,
                            artifact_version INTEGER NOT NULL CHECK(artifact_version > 0),
                            expected_sha256 TEXT,
                            new_sha256 TEXT NOT NULL,
                            target_relpath TEXT NOT NULL,
                            temp_relpath TEXT NOT NULL,
                            state TEXT NOT NULL CHECK(
                                state IN ('prepared','committed','conflict','aborted')
                            ),
                            error_code TEXT NOT NULL DEFAULT '',
                            created_ns INTEGER NOT NULL,
                            updated_ns INTEGER NOT NULL
                        )
                        """
                    )
                    db.execute(
                        "CREATE INDEX IF NOT EXISTS promotions_pending "
                        "ON promotions(state, created_ns, operation_id)"
                    )
                    required_columns = {
                        "operation_id", "run_id", "resource", "artifact_version",
                        "expected_sha256", "new_sha256", "target_relpath",
                        "temp_relpath", "state", "error_code", "created_ns", "updated_ns",
                    }
                    actual_columns = {
                        row[1] for row in db.execute("PRAGMA table_info(promotions)")
                    }
                    if not required_columns.issubset(actual_columns):
                        raise PromotionJournalError("Promotion journal schema is incomplete")
                    db.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
        except (sqlite3.Error, OSError) as exc:
            raise PromotionJournalError("Could not initialize the durable promotion journal") from exc
        if os.name == "posix":
            try:
                database_path.chmod(0o600)
            except OSError as exc:
                raise PromotionJournalError("Could not restrict journal database permissions") from exc

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _validate_paths(
        run_id: str,
        resource: str,
        target_relpath: str,
        temp_relpath: str,
    ) -> None:
        if type(run_id) is not str or not _ID.fullmatch(run_id):
            raise ValueError("Invalid run identifier")
        if (type(resource) is not str or not resource or len(resource) > 500
                or resource.startswith("/") or resource.endswith("/")
                or "\\" in resource or ":" in resource or "//" in resource):
            raise ValueError("Invalid resource path")
        parts = resource.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError("Invalid resource path")
        if target_relpath != f"{run_id}/{resource}":
            raise ValueError("Target path does not match the run and resource")
        if (type(temp_relpath) is not str or "\\" in temp_relpath
                or temp_relpath.startswith("/") or ":" in temp_relpath):
            raise ValueError("Invalid temporary path")
        temp_parts = temp_relpath.split("/")
        target_parts = target_relpath.split("/")
        if (len(temp_parts) != len(target_parts)
                or temp_parts[:-1] != target_parts[:-1]
                or not temp_parts[-1].startswith(".star-stage-")
                or any(part in ("", ".", "..") for part in temp_parts)):
            raise ValueError("Temporary file must be beside its target")

    def prepare(
        self,
        *,
        run_id: str,
        resource: str,
        artifact_version: int,
        expected_sha256: str | None,
        new_sha256: str,
        target_relpath: str,
        temp_relpath: str,
    ) -> PromotionIntent:
        self._validate_paths(run_id, resource, target_relpath, temp_relpath)
        if type(artifact_version) is not int or artifact_version < 1:
            raise ValueError("Artifact version must be a positive integer")
        if type(new_sha256) is not str or not _SHA256.fullmatch(new_sha256):
            raise ValueError("New content digest must be lowercase SHA-256")
        if expected_sha256 is not None and (
            type(expected_sha256) is not str or not _SHA256.fullmatch(expected_sha256)
        ):
            raise ValueError("Expected content digest must be lowercase SHA-256")
        operation_id = uuid4().hex
        now = time.time_ns()
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    db.execute(
                        """
                        INSERT INTO promotions (
                            operation_id,run_id,resource,artifact_version,
                            expected_sha256,new_sha256,target_relpath,temp_relpath,
                            state,error_code,created_ns,updated_ns
                        ) VALUES (?,?,?,?,?,?,?,?, 'prepared','',?,?)
                        """,
                        (
                            operation_id, run_id, resource, artifact_version,
                            expected_sha256, new_sha256, target_relpath,
                            temp_relpath, now, now,
                        ),
                    )
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
        except sqlite3.Error as exc:
            raise PromotionJournalError("Could not persist promotion intent") from exc
        return PromotionIntent(
            operation_id, run_id, resource, artifact_version, expected_sha256,
            new_sha256, target_relpath, temp_relpath, now,
        )

    def pending(self) -> tuple[PromotionIntent, ...]:
        try:
            with closing(self._connect()) as db:
                rows = db.execute(
                    """
                    SELECT operation_id,run_id,resource,artifact_version,
                           expected_sha256,new_sha256,target_relpath,temp_relpath,created_ns
                    FROM promotions
                    WHERE state='prepared'
                    ORDER BY created_ns,operation_id
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise PromotionJournalError("Could not read pending promotion intents") from exc
        return tuple(
            PromotionIntent(
                row["operation_id"], row["run_id"], row["resource"],
                row["artifact_version"], row["expected_sha256"], row["new_sha256"],
                row["target_relpath"], row["temp_relpath"], row["created_ns"],
            )
            for row in rows
        )

    def finish(
        self,
        operation_id: str,
        state: str,
        *,
        error_code: str = "",
    ) -> None:
        if type(operation_id) is not str or not _OPERATION_ID.fullmatch(operation_id):
            raise ValueError("Invalid promotion operation identifier")
        if state not in {"committed", "conflict", "aborted"}:
            raise ValueError("Invalid terminal promotion state")
        if error_code and (type(error_code) is not str or not _ERROR_CODE.fullmatch(error_code)):
            raise ValueError("Invalid promotion error code")
        now = time.time_ns()
        try:
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    row = db.execute(
                        "SELECT state,error_code FROM promotions WHERE operation_id=?",
                        (operation_id,),
                    ).fetchone()
                    if row is None:
                        raise PromotionJournalError("Unknown promotion operation")
                    if row["state"] == state:
                        db.commit()
                        return
                    if row["state"] != "prepared":
                        raise PromotionJournalError("Promotion operation is already terminal")
                    db.execute(
                        "UPDATE promotions SET state=?,error_code=?,updated_ns=? "
                        "WHERE operation_id=? AND state='prepared'",
                        (state, error_code, now, operation_id),
                    )
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
        except sqlite3.Error as exc:
            raise PromotionJournalError("Could not finalize promotion journal record") from exc
