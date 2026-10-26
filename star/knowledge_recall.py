"""Owner-curated, source-pinned general-knowledge recall practice (default OFF).

This is an OFFLINE scheduling/control plane, not a model trainer. Only a trusted
host can map opaque question IDs to prompts, independently grade model answers,
sign the results, and persist the sealed checkpoint. The agent cannot award
itself a successful attempt, read an answer key, approve a source, or promote
new knowledge to a trusted fact.

Uses the existing KnowledgeStore's reviewed notes and the same StreamTelemetry
resource gate as gameplay practice. No inference, web, camera, audio, game
controls, or network operations happen here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import re
import secrets
from threading import get_ident
from typing import Sequence

from .knowledge import KnowledgeStore, _project
from .stream_budget import StreamTelemetry, advise_workload

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_INTERVALS = (3600, 21600, 86400, 259200, 604800, 1209600)
_MAX_ATTEMPTS = 64
_MAX_SESSION_SECONDS = 300
_TAG = b"star.knowledge-recall.receipt.v1\0"
_SEAL = b"star.knowledge-recall.checkpoint.v1\0"


def _id(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} needs a bounded opaque ID")
    return value


def _stamp(value: object) -> int:
    if type(value) is not int or not 0 < value <= 10**11:
        raise ValueError("timestamp must be a valid positive Unix second")
    return value


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def note_fingerprint(*, text: str, source: str, revision: str) -> str:
    """Pin all three provenance-bearing fields, never the model's summary."""
    if any(type(v) is not str or not v.strip() for v in (text, source, revision)):
        raise ValueError("note must have complete provenance")
    return sha256(b"star.knowledge-recall.note.v1\0" + _canonical(
        [text, source, revision])).hexdigest()


@dataclass(frozen=True)
class RecallCard:
    """An owner-approved question label referring to one reviewed local note."""
    question_id: str
    domain: str
    note_id: int
    source_sha256: str

    def __post_init__(self) -> None:
        _id(self.question_id, "question_id")
        _id(self.domain, "domain")
        if type(self.note_id) is not int or self.note_id <= 0:
            raise ValueError("note_id must be positive")
        if type(self.source_sha256) is not str or _HEX.fullmatch(self.source_sha256) is None:
            raise ValueError("pinned source digest must be SHA-256")


@dataclass(frozen=True)
class RecallAdvice:
    status: str
    reason: str
    question_id: str | None = None
    domain: str | None = None
    ticket: str | None = None
    attempts: int = 0
    next_due_unix_s: int | None = None
    authorized_to_run_model: bool = False


@dataclass(frozen=True)
class GradedRecall:
    """One externally graded practice response, not a hidden benchmark result."""
    question_id: str
    ticket: str
    source_sha256: str
    outcome: str  # correct | incorrect | abstained
    observed_unix_s: int
    grader_revision: str
    receipt: str

    def canonical_bytes(self) -> bytes:
        _id(self.question_id, "question_id")
        if type(self.ticket) is not str or re.fullmatch(r"[0-9a-f]{32}", self.ticket) is None:
            raise ValueError("invalid opaque reservation ticket")
        if type(self.source_sha256) is not str or _HEX.fullmatch(self.source_sha256) is None:
            raise ValueError("invalid source fingerprint")
        if self.outcome not in {"correct", "incorrect", "abstained"}:
            raise ValueError("unsupported independent grade")
        _stamp(self.observed_unix_s)
        _id(self.grader_revision, "grader_revision")
        return _TAG + _canonical([self.question_id, self.ticket, self.source_sha256,
                                   self.outcome, self.observed_unix_s, self.grader_revision])


@dataclass
class _Progress:
    attempts: int = 0
    correct: int = 0
    streak: int = 0
    due: int = 0


class KnowledgeRecallPlanner:
    """Bounded, source-checked offline rehearsal with authenticated feedback.

    This object and its KnowledgeStore belong to the same host thread. Trusted
    feedback keys MUST stay outside all LLM tool schemas, model prompts, GitHub,
    gameplay packets, and broadcast context. The host checks the independent
    grader itself; possession of an HMAC receipt does not prove factual truth.
    """

    def __init__(self, store: KnowledgeStore, *, project: str,
                 cards: Sequence[RecallCard], verification_key: bytes) -> None:
        if not isinstance(store, KnowledgeStore):
            raise TypeError("expected KnowledgeStore")
        self._project = _project(project)
        if (type(cards) not in (tuple, list) or not 1 <= len(cards) <= 96
                or any(not isinstance(card, RecallCard) for card in cards)):
            raise ValueError("provide 1..96 owner-curated RecallCard objects")
        if len({card.question_id for card in cards}) != len(cards):
            raise ValueError("duplicate question IDs")
        if len({card.note_id for card in cards}) != len(cards):
            raise ValueError("one question per reviewed note in a scheduler")
        if type(verification_key) is not bytes or len(verification_key) < 32:
            raise ValueError("host-held HMAC verification key must be >=32 bytes")
        self._store = store
        self._cards = tuple(sorted(cards, key=lambda card: card.question_id))
        self._by_id = {card.question_id: card for card in self._cards}
        self._progress = {card.question_id: _Progress() for card in self._cards}
        self._key = verification_key
        self._owner_thread = get_ident()
        self._manifest = sha256(b"star.knowledge-recall.roster.v1\0"
                                + _canonical([[c.question_id, c.domain, c.note_id,
                                               c.source_sha256] for c in self._cards])).hexdigest()
        self._enabled = False
        self._clock: int | None = None
        self._pending: tuple[str, str, int] | None = None
        self._counts = {"offered": 0, "verified": 0, "rejected": 0,
                        "expired": 0, "deferred": 0}

    def _thread(self) -> None:
        if get_ident() != self._owner_thread:
            raise RuntimeError("marshal KnowledgeStore access to the constructing host thread")

    def _advance(self, now_unix_s: int) -> int:
        self._thread()
        now = _stamp(now_unix_s)
        if self._clock is not None and now < self._clock:
            raise ValueError("host clock moved backwards")
        self._clock = now
        if self._pending is not None and now > self._pending[2] + _MAX_SESSION_SECONDS:
            self._pending = None
            self._counts["expired"] += 1
        return now

    def _current_cards(self, cards: Sequence[RecallCard]) -> tuple[RecallCard, ...]:
        """One parameterized SQLite read, even for a 96-item rehearsal roster."""
        if not cards:
            return ()
        placeholders = ",".join("?" for _ in cards)
        rows = self._store.db.execute(
            "SELECT id,text,source,revision FROM notes "
            "WHERE project=? AND reviewed=1 AND kind IN ('fact','reference','fix') "
            f"AND id IN ({placeholders})",
            (self._project, *(card.note_id for card in cards)),
        )
        current = {row["id"]: row for row in rows}
        return tuple(
            card for card in cards
            if card.note_id in current and
            hmac.compare_digest(note_fingerprint(
                text=current[card.note_id]["text"],
                source=current[card.note_id]["source"],
                revision=current[card.note_id]["revision"],
            ), card.source_sha256)
        )

    def _source_is_current(self, card: RecallCard) -> bool:
        return bool(self._current_cards((card,)))

    def pinned_source_for(self, question_id: str) -> str | None:
        """Host-only pinned digest, without exposing the reviewed note body.

        A trusted execution bridge compares this against its owner-approved
        question manifest before sending any prompt to a local model. This
        method does not authorize inference or attest source freshness; reserve
        performs the reviewed-source check independently.
        """
        self._thread()
        _id(question_id, "question_id")
        card = self._by_id.get(question_id)
        return None if card is None else card.source_sha256

    def enable(self, *, owner_approved: bool = False) -> None:
        self._thread()
        if owner_approved is not True:
            raise PermissionError("trusted owner must opt into offline knowledge rehearsal")
        if self._enabled or self._pending is not None:
            raise RuntimeError("previous recall session is active")
        self._enabled = True

    def disable(self) -> None:
        self._thread()
        self._enabled = False
        self._pending = None
        # Preserve verified progress and time until an authenticated checkpoint.

    def reserve(self, *, now_unix_s: int,
                telemetry: StreamTelemetry | None) -> RecallAdvice:
        now = self._advance(now_unix_s)

        def defer(reason: str, due: int | None = None) -> RecallAdvice:
            self._counts["deferred"] += 1
            return RecallAdvice("deferred", reason, next_due_unix_s=due)

        if not self._enabled:
            return defer("offline_recall_opt_in_missing")
        if self._pending is not None:
            return defer("graded_recall_pending")
        if telemetry is None:
            return defer("trusted_telemetry_missing")
        if not isinstance(telemetry, StreamTelemetry):
            raise TypeError("trusted telemetry must be StreamTelemetry")
        if telemetry.live:
            return defer("never_run_rehearsal_while_live")
        if telemetry.game_active and telemetry.game_fps < 50:
            return defer("gameplay_fps_protection")
        if telemetry.speech_backlog_ms > 250:
            return defer("speech_backlog_protection")
        if not advise_workload("training", telemetry).allowed:
            return defer("insufficient_offline_compute_headroom")

        valid = self._current_cards(tuple(
            card for card in self._cards
            if self._progress[card.question_id].attempts < _MAX_ATTEMPTS))
        if not valid:
            return defer("no_current_reviewed_pinned_sources")
        due = [card for card in valid if self._progress[card.question_id].due <= now]
        if not due:
            return defer("no_practice_due", min(self._progress[c.question_id].due for c in valid))
        # Domain coverage comes before repeated drilling: prioritize the domain
        # with fewest host-verified attempts, then overdue, then source ID.
        domain_load = Counter()
        for card in valid:
            domain_load[card.domain] += self._progress[card.question_id].attempts
        selected = min(due, key=lambda c: (
            domain_load[c.domain], self._progress[c.question_id].attempts,
            self._progress[c.question_id].due, c.question_id))
        ticket = secrets.token_hex(16)
        self._pending = (selected.question_id, ticket, now)
        self._counts["offered"] += 1
        return RecallAdvice("practice_candidate", "reviewed_source_due_for_retrieval",
                            selected.question_id, selected.domain, ticket,
                            self._progress[selected.question_id].attempts)

    def finish(self, feedback: GradedRecall, *, now_unix_s: int) -> bool:
        now = self._advance(now_unix_s)
        if not isinstance(feedback, GradedRecall):
            raise TypeError("external GradedRecall required")
        pending = self._pending
        if not self._enabled or pending is None:
            self._counts["rejected"] += 1
            return False
        question_id, ticket, started = pending
        card = self._by_id[question_id]
        if feedback.question_id != question_id or not hmac.compare_digest(feedback.ticket, ticket):
            self._counts["rejected"] += 1
            return False
        if (feedback.source_sha256 != card.source_sha256
                or not started <= feedback.observed_unix_s <= now
                or now - feedback.observed_unix_s > _MAX_SESSION_SECONDS
                or not self._source_is_current(card)):
            self._counts["rejected"] += 1
            return False
        if type(feedback.receipt) is not str or _HEX.fullmatch(feedback.receipt) is None:
            self._counts["rejected"] += 1
            return False
        expected = hmac.new(self._key, feedback.canonical_bytes(), "sha256").hexdigest()
        if not hmac.compare_digest(expected, feedback.receipt):
            self._counts["rejected"] += 1
            return False
        state = self._progress[question_id]
        state.attempts += 1
        if feedback.outcome == "correct":
            state.correct += 1
            state.streak = min(state.streak + 1, len(_INTERVALS))
            delay = _INTERVALS[state.streak - 1]
        else:
            state.streak = 0
            delay = 900 if feedback.outcome == "incorrect" else 1800
        state.due = now + delay
        self._pending = None
        self._counts["verified"] += 1
        return True

    def cancel(self, *, ticket: str, now_unix_s: int) -> bool:
        self._advance(now_unix_s)
        if type(ticket) is not str or self._pending is None:
            return False
        if not hmac.compare_digest(ticket, self._pending[1]):
            return False
        self._pending = None
        return True

    def checkpoint(self) -> bytes:
        """Seal an opaque progress snapshot. Trusted host stores it locally."""
        self._thread()
        if self._enabled or self._pending is not None:
            raise RuntimeError("disable and release reservations before checkpointing")
        payload = {"version": 1, "manifest_sha256": self._manifest,
                   "last_unix_s": self._clock,
                   "rows": [[name, p.attempts, p.correct, p.streak, p.due]
                            for name, p in sorted(self._progress.items())]}
        body = _canonical(payload)
        seal = hmac.new(self._key, _SEAL + body, "sha256").hexdigest()
        return _canonical({"payload": payload, "seal": seal})

    def restore(self, sealed: bytes) -> None:
        """Accept only a matching, authenticated exact-roster snapshot.

        The host must separately prevent replaying an *older* valid snapshot:
        a MAC authenticates bytes, but cannot provide anti-rollback storage.
        """
        self._thread()
        if self._enabled or self._pending is not None or self._clock is not None:
            raise RuntimeError("restore into a fresh disabled planner only")
        if type(sealed) is not bytes or len(sealed) > 16_384:
            raise ValueError("invalid bounded checkpoint")
        try:
            outer = json.loads(sealed.decode("ascii"))
            if type(outer) is not dict or set(outer) != {"payload", "seal"}:
                raise ValueError("checkpoint wrapper fields invalid")
            payload, seal = outer["payload"], outer["seal"]
            if (type(payload) is not dict or
                    set(payload) != {"version", "manifest_sha256", "last_unix_s", "rows"}
                    or payload["version"] != 1 or
                    payload["manifest_sha256"] != self._manifest or
                    type(seal) is not str or _HEX.fullmatch(seal) is None):
                raise ValueError("checkpoint roster or format mismatch")
            want = hmac.new(self._key, _SEAL + _canonical(payload), "sha256").hexdigest()
            if not hmac.compare_digest(want, seal):
                raise PermissionError("checkpoint authentication failed")
            clock = payload["last_unix_s"]
            if clock is not None:
                _stamp(clock)
            rows = payload["rows"]
            if type(rows) is not list or len(rows) != len(self._cards):
                raise ValueError("checkpoint card count mismatch")
            progress: dict[str, _Progress] = {}
            for row in rows:
                if type(row) is not list or len(row) != 5:
                    raise ValueError("checkpoint progress row invalid")
                name, attempts, correct, streak, due = row
                if name not in self._by_id or name in progress:
                    raise ValueError("unknown or repeated card")
                if any(type(v) is not int for v in (attempts, correct, streak, due)):
                    raise ValueError("checkpoint counters must be integers")
                if (not 0 <= correct <= attempts <= _MAX_ATTEMPTS or
                        not 0 <= streak <= min(correct, len(_INTERVALS)) or
                        not 0 <= due <= 10**11):
                    raise ValueError("checkpoint progress out of bounds")
                if attempts and clock is None:
                    raise ValueError("missing checkpoint clock")
                progress[name] = _Progress(attempts, correct, streak, due)
            self._progress = progress
            self._clock = clock
        except (UnicodeError, json.JSONDecodeError, OverflowError, TypeError) as exc:
            raise ValueError("invalid checkpoint encoding") from exc

    def metrics(self) -> dict[str, int | bool]:
        self._thread()
        return {**self._counts, "enabled": self._enabled,
                "pending": self._pending is not None,
                "cards": len(self._cards),
                "attempts": sum(row.attempts for row in self._progress.values()),
                "correct": sum(row.correct for row in self._progress.values())}


__all__ = ["RecallCard", "RecallAdvice", "GradedRecall",
           "KnowledgeRecallPlanner", "note_fingerprint"]
