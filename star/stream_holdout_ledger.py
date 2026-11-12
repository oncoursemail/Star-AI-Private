"""Transactional, one-use ledger for private STAR evaluation holdouts.

The ledger stores only hashes of content-free evaluation data and opaque
session-group IDs. It is a local integrity guard, not a tamper-proof service.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .stream_turntaking_eval import SilenceSpan

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_SPANS = 20_000
_MAX_GROUPS = 20_000
_MAX_TIMESTAMP_MS = 9_223_372_036_854_775_807
_EVALUATOR_VERSION = "star-turntaking-validation-v1"


class HoldoutAlreadyConsumed(RuntimeError):
    """Raised when the exact holdout dataset has already been evaluated."""


class HoldoutGroupAlreadyConsumed(RuntimeError):
    """Raised when any conversation/session group has appeared in an earlier holdout."""


@dataclass(frozen=True)
class HoldoutClaim:
    """Non-sensitive receipt returned after an atomic holdout claim."""

    dataset_digest: str
    group_count: int
    claimed_at_ms: int


class HoldoutLedger:
    """Persist one-use holdout and group claims in a local SQLite database.

    Each claim uses BEGIN IMMEDIATE plus unique constraints. A concurrent
    process cannot successfully claim the same dataset or any overlapping
    session group twice through the same ledger file.

    The caller must keep the ledger file in an owner-controlled location and
    back it up with the evaluation artifacts. Deleting/restoring/copying the
    ledger can bypass this local guard; it is not a remote attestation system.
    """

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0) -> None:
        if not isinstance(path, (str, Path)) or not str(path).strip():
            raise ValueError("path must be a nonempty filesystem path")
        raw_path = str(path)
        if raw_path == ":memory:" or raw_path.startswith("file:"):
            raise ValueError("ledger requires a persistent filesystem path")
        if type(timeout_seconds) not in (int, float):
            raise ValueError("timeout_seconds must be finite and in 0.1..30")
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or not 0.1 <= timeout <= 30.0:
            raise ValueError("timeout_seconds must be finite and in 0.1..30")

        resolved = Path(path).expanduser()
        if resolved.exists() and resolved.is_dir():
            raise ValueError("ledger path must name a file, not a directory")
        if not resolved.parent.exists():
            raise FileNotFoundError("ledger parent directory must already exist")
        self._path = str(resolved)
        self._timeout_seconds = timeout
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=self._timeout_seconds,
            isolation_level=None,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS holdout_claims (
                    dataset_digest TEXT PRIMARY KEY
                        CHECK(length(dataset_digest) = 64),
                    claimed_at_ms INTEGER NOT NULL
                        CHECK(claimed_at_ms >= 0),
                    evaluator_version TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS holdout_groups (
                    group_digest TEXT PRIMARY KEY
                        CHECK(length(group_digest) = 64),
                    dataset_digest TEXT NOT NULL
                        REFERENCES holdout_claims(dataset_digest)
                        ON DELETE CASCADE
                )
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _hash(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()

    @classmethod
    def _canonical_payload(
        cls,
        spans: Sequence[SilenceSpan],
        group_ids_by_turn: Mapping[str, str],
    ) -> tuple[str, tuple[str, ...]]:
        if not isinstance(spans, (tuple, list)) or not 1 <= len(spans) <= _MAX_SPANS:
            raise ValueError("spans must contain 1..20000 observations")
        if not isinstance(group_ids_by_turn, Mapping):
            raise TypeError("group_ids_by_turn must be a mapping")

        rows = tuple(spans)
        if any(not isinstance(span, SilenceSpan) for span in rows):
            raise TypeError("spans must contain SilenceSpan values")
        span_ids = [span.span_id for span in rows]
        if len(set(span_ids)) != len(span_ids):
            raise ValueError("span IDs must be unique")

        turn_ids = {span.turn_id for span in rows}
        if not turn_ids.issubset(group_ids_by_turn):
            raise ValueError("every holdout turn must have an opaque group ID")

        turn_groups: list[list[str]] = []
        unique_groups: set[str] = set()
        for turn_id in sorted(turn_ids):
            group_id = group_ids_by_turn[turn_id]
            if type(group_id) is not str or _ID.fullmatch(group_id) is None:
                raise ValueError("group IDs must be bounded opaque identifiers")
            turn_groups.append([turn_id, group_id])
            unique_groups.add(group_id)

        if not 1 <= len(unique_groups) <= _MAX_GROUPS:
            raise ValueError("holdout must contain 1..20000 distinct groups")

        canonical_spans = []
        for span in sorted(rows, key=lambda item: item.span_id):
            canonical_spans.append(
                {
                    "span_id": span.span_id,
                    "turn_id": span.turn_id,
                    "environment_id": span.environment_id,
                    "kind": span.kind.value,
                    "duration_ms": span.duration_ms,
                    "scores": [
                        [point.elapsed_ms, float(point.score)]
                        for point in span.scores
                    ],
                }
            )

        payload = json.dumps(
            {
                "schema": 1,
                "groups": turn_groups,
                "spans": canonical_spans,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        dataset_digest = cls._hash(b"STAR-HOLDOUT-v1\0" + payload)
        group_digests = tuple(
            sorted(
                cls._hash(b"STAR-GROUP-v1\\0" + group_id.encode("utf-8"))
                for group_id in unique_groups
            )
        )
        return dataset_digest, group_digests

    def claim(
        self,
        spans: Sequence[SilenceSpan],
        group_ids_by_turn: Mapping[str, str],
        *,
        claimed_at_ms: int | None = None,
    ) -> HoldoutClaim:
        """Atomically consume a holdout dataset and all of its session groups.

        A claim is committed before the caller scores the holdout. If scoring
        crashes afterward, the holdout remains consumed by design: inspecting
        it is enough to make repeated tuning an adaptive reuse risk.
        """
        if claimed_at_ms is None:
            timestamp = time.time_ns() // 1_000_000
        else:
            if type(claimed_at_ms) is not int:
                raise ValueError("claimed_at_ms must be a nonnegative integer")
            timestamp = claimed_at_ms
        if not 0 <= timestamp <= _MAX_TIMESTAMP_MS:
            raise ValueError("claimed_at_ms must be a nonnegative integer")

        dataset_digest, group_digests = self._canonical_payload(
            spans, group_ids_by_turn
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                inserted = connection.execute(
                    """
                    INSERT OR IGNORE INTO holdout_claims
                    (dataset_digest, claimed_at_ms, evaluator_version)
                    VALUES (?, ?, ?)
                    """,
                    (dataset_digest, timestamp, _EVALUATOR_VERSION),
                )
                if inserted.rowcount != 1:
                    raise HoldoutAlreadyConsumed(
                        "this exact holdout dataset has already been consumed"
                    )

                for group_digest in group_digests:
                    inserted_group = connection.execute(
                        """
                        INSERT OR IGNORE INTO holdout_groups
                        (group_digest, dataset_digest)
                        VALUES (?, ?)
                        """,
                        (group_digest, dataset_digest),
                    )
                    if inserted_group.rowcount != 1:
                        raise HoldoutGroupAlreadyConsumed(
                            "one or more session groups were used by an earlier holdout"
                        )

                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        finally:
            connection.close()

        return HoldoutClaim(
            dataset_digest=dataset_digest,
            group_count=len(group_digests),
            claimed_at_ms=timestamp,
        )


__all__ = [
    "HoldoutAlreadyConsumed",
    "HoldoutGroupAlreadyConsumed",
    "HoldoutClaim",
    "HoldoutLedger",
]
