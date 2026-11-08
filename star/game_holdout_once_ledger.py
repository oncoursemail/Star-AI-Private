"""Fail-closed, single-use holdout reservations for STAR's private game audits.

Reserve before collecting paired paused/realtime results. Case HMACs and SQLite
uniqueness stop accidental reuse across protocols and processes; aborted or
invalid runs permanently consume their cohort. The caller supplies and securely
backs up an independent persistent key. This module does not launch games,
stream, train models, or authenticate a compromised measurement host.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import os
from pathlib import Path
import secrets
import sqlite3
from threading import RLock
from typing import Sequence

from .game_gap_failure_atlas import GameGapFailureAtlas, audit_game_gap_failure_atlas
from .game_realtime_gap_audit import GameModeGapPair, GameModeGapProtocol


@dataclass(frozen=True)
class HoldoutReservation:
    receipt: str
    protocol_sha256: str
    case_count: int
    authorizes_play: bool = False
    authorizes_streaming: bool = False
    authorizes_training: bool = False
    authorizes_promotion: bool = False


@dataclass(frozen=True)
class RecordedHoldout:
    atlas: GameGapFailureAtlas
    status: str = "owner_review_only"
    authorizes_play: bool = False
    authorizes_streaming: bool = False
    authorizes_training: bool = False
    authorizes_promotion: bool = False


class HoldoutOnceLedger:
    """A host-owned ledger, not an engine or cryptographic outcome witness."""

    def __init__(self, database: str | Path, *, hmac_secret: bytes) -> None:
        if type(hmac_secret) is not bytes or not 32 <= len(hmac_secret) <= 128 or not any(hmac_secret):
            raise ValueError("supply an independently retained, nonzero 32..128-byte HMAC key")
        path = str(database)
        new = False
        if path != ":memory:":
            p = Path(path)
            if (
                not p.is_absolute()
                or not p.parent.is_dir()
                or p.parent.is_symlink()
                or p.is_symlink()
                or (p.exists() and (not p.is_file() or p.stat().st_nlink != 1))
            ):
                raise ValueError("database must be an absolute regular non-link local path")
            new = not p.exists()
        self._lock = RLock()
        self._secret = hmac_secret
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=5)
        try:
            if new:
                os.chmod(path, 0o600)
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.execute("PRAGMA trusted_schema=OFF")
            self._db.execute("CREATE TABLE IF NOT EXISTS holdout_meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS holdout_runs "
                "(receipt TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, "
                "status TEXT NOT NULL CHECK(status IN "
                "('reserved','sealed','invalid','abandoned','finalized')), "
                "cases INTEGER NOT NULL, summary TEXT)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS holdout_cases "
                "(token TEXT PRIMARY KEY, receipt TEXT NOT NULL "
                "REFERENCES holdout_runs(receipt))"
            )
            self._db.execute("BEGIN IMMEDIATE")
            try:
                fingerprint = hmac.new(hmac_secret, b"star.holdout.key.v1", sha256).hexdigest()
                old = self._db.execute("SELECT value FROM holdout_meta WHERE name='fingerprint'").fetchone()
                if old and old[0] != fingerprint:
                    raise ValueError("ledger is bound to a different HMAC secret")
                if old is None:
                    self._db.execute(
                        "INSERT INTO holdout_meta(name,value) VALUES('fingerprint',?)",
                        (fingerprint,),
                    )
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _token(self, protocol: GameModeGapProtocol, name: str, seed: int) -> str:
        raw = (protocol.game_scope + "\0" + name + "\0" + str(seed)).encode("ascii")
        return hmac.new(self._secret, b"star.holdout.case.v1\0" + raw, sha256).hexdigest()

    def reserve(self, protocol: GameModeGapProtocol, *, owner_approved: bool = False) -> HoldoutReservation:
        """Consume exact unseen cases BEFORE any game run, including failures."""
        if owner_approved is not True:
            raise PermissionError("owner session opt-in required")
        if not isinstance(protocol, GameModeGapProtocol):
            raise TypeError("immutable host-owned protocol required")
        tokens = [self._token(protocol, name, seed) for name, seed in protocol.cases]
        ticket = secrets.token_hex(16)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT INTO holdout_runs(receipt,digest,status,cases) VALUES(?,?,'reserved',?)",
                    (ticket, protocol.digest, len(tokens)),
                )
                self._db.executemany(
                    "INSERT INTO holdout_cases(token,receipt) VALUES(?,?)",
                    [(token, ticket) for token in tokens],
                )
                self._db.commit()
            except sqlite3.IntegrityError as exc:
                self._db.rollback()
                raise ValueError("holdout protocol or case already reserved") from exc
            except BaseException:
                self._db.rollback()
                raise
        return HoldoutReservation(ticket, protocol.digest, len(tokens))

    def _transition(
        self,
        protocol: GameModeGapProtocol,
        receipt: HoldoutReservation,
        *,
        before: str,
        after: str,
        summary: str | None = None,
    ) -> None:
        if not isinstance(receipt, HoldoutReservation) or not isinstance(protocol, GameModeGapProtocol):
            raise TypeError("matching typed protocol and reservation required")
        if receipt.protocol_sha256 != protocol.digest or receipt.case_count != len(protocol.cases):
            raise ValueError("receipt belongs to another cohort")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                rows = self._db.execute(
                    "UPDATE holdout_runs SET status=?,summary=? WHERE receipt=? AND digest=? AND cases=? AND status=?",
                    (after, summary, receipt.receipt, protocol.digest, len(protocol.cases), before),
                ).rowcount
                if rows != 1:
                    raise ValueError("reservation is missing or already consumed")
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def finalize(
        self,
        protocol: GameModeGapProtocol,
        pairs: Sequence[GameModeGapPair],
        *,
        receipt: HoldoutReservation,
    ) -> RecordedHoldout:
        """Seal on FIRST result submission so invalid/partial runs cannot be retried."""
        self._transition(protocol, receipt, before="reserved", after="sealed")
        try:
            if type(pairs) not in (list, tuple):
                raise ValueError("submit one complete list/tuple of matched results")
            atlas = audit_game_gap_failure_atlas(protocol, tuple(pairs))
        except BaseException:
            self._transition(protocol, receipt, before="sealed", after="invalid")
            raise
        self._transition(
            protocol,
            receipt,
            before="sealed",
            after="finalized",
            summary=atlas.gap_status,
        )
        return RecordedHoldout(atlas)

    def abandon(self, protocol: GameModeGapProtocol, *, receipt: HoldoutReservation) -> None:
        """Burn an unused or failed reservation; never recycle its test cases."""
        self._transition(protocol, receipt, before="reserved", after="abandoned")

    def counts(self) -> dict[str, int]:
        """Only aggregated statuses; never seeds, scenario names or scores."""
        with self._lock:
            return dict(self._db.execute("SELECT status,COUNT(*) FROM holdout_runs GROUP BY status").fetchall())


__all__ = ["HoldoutOnceLedger", "HoldoutReservation", "RecordedHoldout"]
