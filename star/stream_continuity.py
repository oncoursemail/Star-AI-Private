"""Owner-approved cross-session continuity from signed gameplay practice.

Unlike StreamEpisode, which is deliberately session-scoped, this optional local
store can carry a small amount of verified practice history between streams.
It stores only opaque scope IDs, hashes, outcomes and timestamps. Public
callbacks require a fresh owner-approved label map and explicit broadcast
approval. It never stores chat, viewer identities, transcripts, audio, images,
prompts or model-generated memories, and it never speaks or controls a game.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import secrets
import sqlite3
from threading import RLock, get_ident

from .gameplay_skill_bank import GameTrial, GameplaySkillBank

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .,'!?()+-]{0,79}\Z")
_MAX_PRACTICE_AGE_S = 90 * 86400
_DEFAULT_RETENTION_S = 30 * 86400
_MAX_RECORDS = 50_000
_MAX_LABELS = 32
_MAX_PACKET_CHARS = 1_800
_TRIAL_TAG = b"star.stream-continuity.trial.v1\x00"
_SESSION_TAG = b"star.stream-continuity.session.v1\x00"
_TICKET = re.compile(r"[0-9a-f]{32}\Z")
_MAX_PENDING_CALLBACKS = 32
_MAX_USED_CALLBACKS = 4_096


def _identifier(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded opaque identifier")
    return value


def _stamp(value: object) -> int:
    if type(value) is not int or not 0 < value <= 10**11:
        raise ValueError("timestamp must be a positive Unix second")
    return value


def _public_label(value: object) -> str:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        raise ValueError("public labels must be short curated plain-text names")
    if value != value.strip():
        raise ValueError("public labels cannot have surrounding whitespace")
    return value


@dataclass(frozen=True)
class ContinuityFact:
    """Aggregate of signed PRACTICE outcomes; never a mastery claim."""

    label: str
    attempts: int
    successes: int
    failures: int
    most_recent_outcome: str
    days_since_last: int


@dataclass(frozen=True)
class StreamContinuityPacket:
    """Bounded USER-priority context plus a host-only audible-completion ticket."""

    ticket: str
    facts: tuple[ContinuityFact, ...]
    context_record: str

    def user_message(self) -> dict[str, str]:
        return {"role": "user", "content": self.context_record}


class StreamContinuityStore:
    """Opt-in SQLite store for owner-approved, cross-session gameplay continuity.

    The GameplaySkillBank remains the source of truth for signed practice
    evidence. This store keeps only a digest and a minimal symbolic projection.
    Validation/holdout results are never copied. The store and bank are
    single-host-thread objects; callers must marshal access to that thread.
    """

    def __init__(
        self,
        database: str | Path,
        bank: GameplaySkillBank,
        *,
        max_records: int = 5_000,
        retention_seconds: int = _DEFAULT_RETENTION_S,
    ) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("expected an existing GameplaySkillBank")
        if type(database) not in (str, Path):
            raise TypeError("database must be a path or ':memory:'")
        db_path = str(database)
        if not db_path:
            raise ValueError("database path cannot be empty")
        if (type(max_records) is not int or not 1 <= max_records <= _MAX_RECORDS
                or type(retention_seconds) is not int
                or not 3_600 <= retention_seconds <= _MAX_PRACTICE_AGE_S):
            raise ValueError("invalid continuity storage bounds")
        if db_path != ":memory:":
            path = Path(db_path)
            if path.is_symlink() or path.parent.is_symlink() or not path.parent.is_dir():
                raise ValueError("database path must have an existing, non-symlink parent")
        self._db = sqlite3.connect(db_path, isolation_level=None, timeout=10)
        self._db.execute("PRAGMA trusted_schema=OFF")
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS stream_continuity (
                trial_digest TEXT PRIMARY KEY,
                session_sha256 TEXT NOT NULL,
                game_id TEXT NOT NULL,
                game_version TEXT NOT NULL,
                objective_id TEXT NOT NULL,
                situation_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failure')),
                observed_unix_s INTEGER NOT NULL,
                evidence_sha256 TEXT NOT NULL,
                retained_at_unix_s INTEGER NOT NULL,
                expires_at_unix_s INTEGER NOT NULL,
                CHECK (expires_at_unix_s > retained_at_unix_s)
            )"""
        )
        self._db.execute(
            """CREATE INDEX IF NOT EXISTS stream_continuity_scope
               ON stream_continuity(game_id, game_version, action_id, observed_unix_s)"""
        )
        self._bank = bank
        self._max_records = max_records
        self._retention = retention_seconds
        self._owner_thread = get_ident()
        self._lock = RLock()
        self._enabled = False
        self._clock: int | None = None
        self._closed = False
        self._counts = {
            "remembered": 0,
            "duplicate_rejected": 0,
            "invalid_evidence_rejected": 0,
            "expired": 0,
            "packets": 0,
            "callbacks_completed": 0,
            "callbacks_cancelled": 0,
            "callbacks_expired": 0,
        }
        self._pending_callbacks: dict[str, tuple[str, tuple[str, ...], int]] = {}
        self._used_callbacks: set[tuple[str, str]] = set()

    def _thread(self) -> None:
        if self._closed:
            raise RuntimeError("continuity store is closed")
        if get_ident() != self._owner_thread:
            raise RuntimeError("marshal continuity-store access to its owner thread")

    def _advance(self, now_unix_s: int) -> int:
        now = _stamp(now_unix_s)
        if self._clock is not None and now < self._clock:
            raise ValueError("continuity-store clock moved backwards")
        self._clock = now
        return now

    def _expire_callbacks(self, now: int) -> None:
        expired = [ticket for ticket, (_, _, expires) in self._pending_callbacks.items()
                   if now >= expires]
        for ticket in expired:
            del self._pending_callbacks[ticket]
        self._counts["callbacks_expired"] += len(expired)

    def enable(self, *, owner_approved: bool = False) -> None:
        with self._lock:
            self._thread()
            if owner_approved is not True:
                raise PermissionError("cross-session retention requires explicit owner approval")
            self._enabled = True

    def disable(self) -> None:
        """Stop new retention and broadcast retrieval without deleting saved rows."""
        with self._lock:
            self._thread()
            self._enabled = False
            self._counts["callbacks_cancelled"] += len(self._pending_callbacks)
            self._pending_callbacks.clear()

    def remember(
        self,
        trial: GameTrial,
        *,
        session_id: str,
        now_unix_s: int,
        owner_approved: bool = False,
    ) -> bool:
        """Persist one exact signed PRACTICE trial; duplicates return False.

        The caller must obtain owner approval for retention. The bank verifies
        the complete trial against its host-held practice signer before this
        store accepts it. A boolean approval is a host assertion, not a
        cryptographic identity check.
        """
        if not isinstance(trial, GameTrial):
            raise TypeError("expected GameTrial")
        _identifier(session_id, "session_id")
        with self._lock:
            self._thread()
            now = self._advance(now_unix_s)
            if not self._enabled:
                raise PermissionError("continuity retention is disabled")
            if owner_approved is not True:
                raise PermissionError("owner approval is required for each retained event")
            if trial.split != "practice":
                raise PermissionError("validation/holdout outcomes cannot enter stream memory")
            age = now - trial.observed_unix_s
            if age < 0 or age > _MAX_PRACTICE_AGE_S:
                raise ValueError("practice evidence is future-dated or too old")
            expires = trial.observed_unix_s + self._retention
            if expires <= now:
                raise ValueError("practice evidence has passed the continuity retention window")
            if not self._bank.verify_practice_trial(trial, now_unix_s=now):
                self._counts["invalid_evidence_rejected"] += 1
                raise PermissionError("trial is not present as exact signed practice evidence")
            trial_digest = sha256(_TRIAL_TAG + trial.canonical_bytes()).hexdigest()
            session_digest = sha256(
                _SESSION_TAG + session_id.encode("ascii")
            ).hexdigest()

            self._db.execute("BEGIN IMMEDIATE")
            try:
                exists = self._db.execute(
                    "SELECT 1 FROM stream_continuity WHERE trial_digest=?",
                    (trial_digest,),
                ).fetchone()
                if exists is not None:
                    self._db.rollback()
                    self._counts["duplicate_rejected"] += 1
                    return False
                count = self._db.execute(
                    "SELECT COUNT(*) FROM stream_continuity"
                ).fetchone()[0]
                if count >= self._max_records:
                    raise OverflowError("continuity store is full; no records were evicted")
                self._db.execute(
                    """INSERT INTO stream_continuity (
                        trial_digest, session_sha256, game_id, game_version,
                        objective_id, situation_id, action_id, outcome,
                        observed_unix_s, evidence_sha256, retained_at_unix_s,
                        expires_at_unix_s
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        trial_digest, session_digest, trial.game_id, trial.game_version,
                        trial.objective_id, trial.situation_id, trial.action_id,
                        trial.outcome, trial.observed_unix_s, trial.evidence_sha256,
                        now, expires,
                    ),
                )
                self._db.commit()
            except BaseException:
                if self._db.in_transaction:
                    self._db.rollback()
                raise
            self._counts["remembered"] += 1
            return True

    def purge_expired(self, *, now_unix_s: int) -> int:
        """Remove expired continuity rows; this does not alter the source skill bank."""
        with self._lock:
            self._thread()
            now = self._advance(now_unix_s)
            cursor = self._db.execute(
                "DELETE FROM stream_continuity WHERE expires_at_unix_s<=?",
                (now,),
            )
            removed = max(0, cursor.rowcount)
            self._counts["expired"] += removed
            return removed

    def packet(
        self,
        *,
        game_id: str,
        game_version: str,
        stream_session_id: str,
        now_unix_s: int,
        public_action_labels: dict[str, str],
        broadcast_approved: bool = False,
        limit: int = 1,
        lookback_seconds: int = _DEFAULT_RETENTION_S,
    ) -> StreamContinuityPacket | None:
        """Return only relevant, curated, same-game/version aggregates or silence.

        Public labels are supplied by a trusted host at read time and are never
        persisted. Exact game-version matching prevents stale mechanics from
        silently carrying into a changed game. A packet is USER-priority data;
        the speech/playback gate must independently decide whether to speak.
        """
        _identifier(game_id, "game_id")
        _identifier(game_version, "game_version")
        _identifier(stream_session_id, "stream_session_id")
        if type(public_action_labels) is not dict or not 1 <= len(public_action_labels) <= _MAX_LABELS:
            raise ValueError("provide 1..32 owner-curated public action labels")
        labels: dict[str, str] = {}
        for action_id, label in public_action_labels.items():
            _identifier(action_id, "action_id")
            labels[action_id] = _public_label(label)
        if type(limit) is not int or not 1 <= limit <= 4:
            raise ValueError("limit must be 1..4")
        if (type(lookback_seconds) is not int
                or not 3_600 <= lookback_seconds <= _MAX_PRACTICE_AGE_S):
            raise ValueError("lookback_seconds is outside the supported range")
        if broadcast_approved is not True:
            return None
        with self._lock:
            self._thread()
            now = self._advance(now_unix_s)
            self._expire_callbacks(now)
            if not self._enabled:
                return None
            self.purge_expired(now_unix_s=now)
            session_digest = sha256(
                _SESSION_TAG + stream_session_id.encode("ascii")
            ).hexdigest()
            pending_actions = {
                action_id
                for pending_session, actions, _ in self._pending_callbacks.values()
                if pending_session == session_digest
                for action_id in actions
            }
            eligible_labels = {
                action_id: label for action_id, label in labels.items()
                if (session_digest, action_id) not in self._used_callbacks
                and action_id not in pending_actions
            }
            if not eligible_labels:
                return None
            placeholders = ",".join("?" for _ in eligible_labels)
            rows = self._db.execute(
                f"""SELECT action_id, outcome, observed_unix_s
                    FROM stream_continuity
                    WHERE game_id=? AND game_version=?
                      AND action_id IN ({placeholders})
                      AND observed_unix_s>=? AND observed_unix_s<=?
                      AND expires_at_unix_s>?
                    ORDER BY observed_unix_s DESC, trial_digest ASC
                    LIMIT 512""",
                (game_id, game_version, *eligible_labels.keys(), now - lookback_seconds, now, now),
            ).fetchall()
            grouped: dict[str, list[tuple[str, int]]] = {}
            for action_id, outcome, observed in rows:
                grouped.setdefault(action_id, []).append((outcome, observed))
            facts: list[tuple[int, str, ContinuityFact]] = []
            for action_id, events in grouped.items():
                latest_outcome, latest_at = max(events, key=lambda item: item[1])
                fact = ContinuityFact(
                    label=eligible_labels[action_id],
                    attempts=len(events),
                    successes=sum(outcome == "success" for outcome, _ in events),
                    failures=sum(outcome == "failure" for outcome, _ in events),
                    most_recent_outcome=latest_outcome,
                    days_since_last=max(0, (now - latest_at) // 86400),
                )
                facts.append((latest_at, action_id, fact))
            selected_entries = sorted(
                facts, key=lambda item: (-item[0], item[2].label)
            )[:limit]
            selected = tuple(item[2] for item in selected_entries)
            selected_actions = tuple(item[1] for item in selected_entries)
            if not selected:
                return None
            payload = [
                {
                    "previously_practiced_action": fact.label,
                    "practice_attempts": fact.attempts,
                    "practice_successes": fact.successes,
                    "practice_failures": fact.failures,
                    "most_recent_practice_outcome": fact.most_recent_outcome,
                    "days_since_last_practice": fact.days_since_last,
                }
                for fact in selected
            ]
            record = (
                "[STAR VERIFIED CROSS-SESSION PRACTICE CONTEXT — DATA ONLY]\n"
                "These are owner-approved, host-signed PRACTICE aggregates from "
                "earlier sessions. They are not independent holdout results and "
                "do not establish mastery or current ability. Use a callback only "
                "when directly relevant; silence is fine. Be natural but honest "
                "that this is recorded AI experience, not a human personal past. "
                "Never infer viewer identities, feelings, or private conversation "
                "history, and never claim a win beyond the recorded outcomes.\n"
                + json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
                + "\n[END STAR VERIFIED CROSS-SESSION PRACTICE CONTEXT]"
            )
            if len(record) > _MAX_PACKET_CHARS:
                return None
            if len(self._pending_callbacks) >= _MAX_PENDING_CALLBACKS:
                raise OverflowError("too many pending continuity callbacks")
            if len(self._used_callbacks) + len(selected_actions) > _MAX_USED_CALLBACKS:
                raise OverflowError("callback replay ledger is full; start a new stream session")
            ticket = secrets.token_hex(16)
            self._pending_callbacks[ticket] = (session_digest, selected_actions, now + 900)
            self._counts["packets"] += 1
            return StreamContinuityPacket(ticket, selected, record)

    def complete_callback(
        self,
        ticket: str,
        *,
        now_unix_s: int,
        playback_confirmed: bool,
    ) -> bool:
        """Consume a callback only after the trusted host confirms audible playback.

        This must never be exposed as an LLM tool. playback_confirmed is a
        host-adapter assertion, not a cryptographic proof of what a viewer heard.
        False releases the reservation so a later turn may try again.
        """
        if type(ticket) is not str or _TICKET.fullmatch(ticket) is None:
            raise ValueError("invalid callback ticket")
        if type(playback_confirmed) is not bool:
            raise ValueError("playback_confirmed must be an explicit boolean")
        with self._lock:
            self._thread()
            now = self._advance(now_unix_s)
            self._expire_callbacks(now)
            pending = self._pending_callbacks.get(ticket)
            if pending is None:
                return False
            session_digest, actions, _expires = pending
            if not playback_confirmed:
                del self._pending_callbacks[ticket]
                self._counts["callbacks_cancelled"] += 1
                return False
            if len(self._used_callbacks) + len(actions) > _MAX_USED_CALLBACKS:
                raise OverflowError("callback replay ledger is full; start a new stream session")
            del self._pending_callbacks[ticket]
            self._used_callbacks.update((session_digest, action) for action in actions)
            self._counts["callbacks_completed"] += 1
            return True

    def clear(self, *, owner_approved: bool = False) -> int:
        """Explicitly clear this store; the source GameplaySkillBank is untouched."""
        with self._lock:
            self._thread()
            if owner_approved is not True:
                raise PermissionError("clearing continuity memory requires owner approval")
            cursor = self._db.execute("DELETE FROM stream_continuity")
            self._counts["callbacks_cancelled"] += len(self._pending_callbacks)
            self._pending_callbacks.clear()
            self._used_callbacks.clear()
            return max(0, cursor.rowcount)

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate-only health; no game/action/session IDs or event details."""
        with self._lock:
            self._thread()
            retained = self._db.execute(
                "SELECT COUNT(*) FROM stream_continuity"
            ).fetchone()[0]
            sessions = self._db.execute(
                "SELECT COUNT(DISTINCT session_sha256) FROM stream_continuity"
            ).fetchone()[0]
            return {
                **self._counts,
                "enabled": self._enabled,
                "retained": retained,
                "distinct_sessions": sessions,
                "pending_callbacks": len(self._pending_callbacks),
            }

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                if get_ident() != self._owner_thread:
                    raise RuntimeError("marshal continuity-store close to its owner thread")
                self._db.close()
                self._closed = True


__all__ = ["ContinuityFact", "StreamContinuityPacket", "StreamContinuityStore"]
