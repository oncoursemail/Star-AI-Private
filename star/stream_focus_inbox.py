"""Ephemeral, moderated viewer-question follow-up after intense gameplay.

A natural streamer need not answer chat in the middle of a difficult fight,
but a 35-second live-event TTL can lose a good question entirely. This tiny
owner-opted host component holds at most a few already-moderated questions
during *trusted-host reported* critical gameplay, then reoffers one to the
existing StreamDirector after focus returns. The existing speech, moderation,
QoS, physical audio and stage authorizations still apply independently.

No network, games, voice generation, chat ingestion, prompts, background jobs,
recordings, durable storage or tool permissions are touched. Raw viewer IDs
are immediately replaced by session-only HMAC pseudonyms. Questions remain
untrusted DATA even when they are later reoffered to the speaking planner.
"""
from __future__ import annotations

from typing import cast

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import hmac
import math
import re
import secrets
from threading import RLock

from .stream_director import StreamDirector, StreamSignal

# Only canonical, stable platform account IDs, never display names or event IDs.
# Whitespace/control/confusable characters must be normalized upstream by the
# trusted chat host, not treated as new independent viewers in this queue.
_SPEAKER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")


def _time(value: object) -> float:
    if type(value) not in (float, int):
        raise ValueError("expected monotonic seconds")
    try:
        seconds = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("monotonic clock conversion failed") from exc
    if not math.isfinite(seconds) or not 0 <= seconds <= 1e13:
        raise ValueError("expected finite nonnegative monotonic seconds")
    return seconds


@dataclass(frozen=True)
class _Deferred:
    serial: int
    asked_at: float
    deadline_at: float
    question: str
    speaker_tag: str


class StreamFocusInbox:
    """Single-session, tiny FIFO; never produces a speech or game action.

    The host must independently authenticate chat/moderation, provide the same
    monotonic clock used by StreamDirector, and explicitly report critical
    gameplay. Reoffered signals still need StreamDirector.propose(), the
    StarStage and a real audio device. The inbox is deliberately OFF by default.
    """

    def __init__(
        self, *, max_questions: int = 4, max_age_seconds: float = 100.0,
    ) -> None:
        if type(max_questions) is not int or not 1 <= max_questions <= 8:
            raise ValueError("max_questions must be 1..8")
        age = _time(max_age_seconds)
        if not 15 <= age <= 180:
            raise ValueError("max_age_seconds must be 15..180")
        self.max_questions = max_questions
        self.max_age_seconds = age
        self._lock = RLock()
        self._enabled = False
        self._focus = False
        self._epoch = 0
        self._next_serial = 0
        self._last_now: float | None = None
        self._session_salt: bytes | None = None
        self._pending: deque[_Deferred] = deque()
        self._seen: deque[str] = deque()
        self._seen_set: set[str] = set()
        self._counts = dict(accepted=0, declined=0, expired=0, released=0,
                            director_busy=0)

    def _forget(self) -> None:
        self._focus = False
        self._last_now = None
        self._session_salt = None
        self._pending.clear()
        self._seen.clear()
        self._seen_set.clear()

    def enable(
        self, *, owner_approved: bool = False,
        moderated_chat_retention_approved: bool = False,
    ) -> None:
        """Authorize only a bounded in-memory follow-up queue, not a broadcast."""
        if owner_approved is not True or moderated_chat_retention_approved is not True:
            raise PermissionError("owner and moderated-chat retention opt-ins required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable the existing session before enabling")
            self._forget()
            self._session_salt = secrets.token_bytes(32)
            self._epoch += 1
            self._next_serial = 0
            self._enabled = True

    def disable(self) -> None:
        """Immediately drop questions, per-session pseudonyms and duplicate keys."""
        with self._lock:
            self._enabled = False
            self._epoch += 1
            self._forget()

    def _advance(self, now: float) -> float:
        seconds = _time(now)
        if self._last_now is not None and seconds < self._last_now:
            raise ValueError("focus inbox clock went backwards")
        self._last_now = seconds
        before = len(self._pending)
        self._pending = deque(
            item for item in self._pending if seconds <= item.deadline_at
        )
        self._counts["expired"] += before - len(self._pending)
        return seconds

    def update_focus(self, *, gameplay_critical: bool, now: float) -> bool:
        """Host reports whether returning to a past question is appropriate."""
        if type(gameplay_critical) is not bool:
            raise TypeError("gameplay_critical must come from trusted host state")
        with self._lock:
            self._advance(now)
            if not self._enabled:
                return False
            self._focus = gameplay_critical
            return self._focus

    def capture(
        self, signal: StreamSignal, *, now: float, moderated: bool = False,
    ) -> bool:
        """Hold one recent, reported, moderated question during a game crisis.

        Calling this after a raw chat event, or with model-generated evidence,
        does not bypass upstream moderation. The source host must attest both
        moderation and the origin; neither is provable from a Python boolean.
        """
        if not isinstance(signal, StreamSignal):
            raise TypeError("expected an existing validated StreamSignal")
        if type(moderated) is not bool:
            raise TypeError("moderation attestation must be bool")
        with self._lock:
            now = self._advance(now)
            if (not self._enabled or not self._focus or not moderated
                    or signal.kind != "viewer_question"
                    or signal.evidence != "reported"
                    # Per-speaker fairness needs a stable, host-supplied ID.
                    # signal_id is per-event and must never stand in for it.
                    or _SPEAKER_ID.fullmatch(signal.speaker_id) is None
                    or not 0 <= now - signal.timestamp <= 5.0
                    or len(signal.detail) > 350):
                self._counts["declined"] += 1
                return False
            assert self._session_salt is not None
            normalized = " ".join(signal.detail.casefold().split())
            # Secret-keyed within this session, not linkable across broadcasts.
            digest = hmac.new(self._session_salt, normalized.encode("utf-8"),
                              sha256).hexdigest()
            # Host must supply a stable identity after authenticating chat;
            # hash it immediately to avoid retaining the original identifier.
            speaker_tag = "v" + hmac.new(
                self._session_salt, signal.speaker_id.encode("utf-8"), sha256
            ).hexdigest()[:24]
            if (digest in self._seen_set or
                    any(item.speaker_tag == speaker_tag for item in self._pending)
                    or len(self._pending) >= self.max_questions):
                self._counts["declined"] += 1
                return False
            if len(self._seen) == 256:
                old = self._seen.popleft()
                self._seen_set.remove(old)
            self._seen.append(digest)
            self._seen_set.add(digest)
            self._next_serial += 1
            self._pending.append(_Deferred(
                serial=self._next_serial, asked_at=signal.timestamp,
                deadline_at=signal.timestamp + self.max_age_seconds,
                question=signal.detail, speaker_tag=speaker_tag,
            ))
            self._counts["accepted"] += 1
            return True

    def release_one(
        self, director: StreamDirector, *, now: float,
        gameplay_critical: bool = False,
    ) -> bool:
        """Reoffer at most one question; existing director may still say NO.

        A reoffered event has a new *offer* time, but its context explicitly
        identifies how long ago it was asked. This avoids silently presenting
        older chat as a live observation. Never returns a speaking permission.
        A busy director leaves the original bounded question in this inbox.
        """
        if not isinstance(director, StreamDirector):
            raise TypeError("expected the existing StreamDirector")
        if type(gameplay_critical) is not bool:
            raise TypeError("critical-game state must be a trusted boolean")
        with self._lock:
            now = self._advance(now)
            if (not self._enabled or self._focus or gameplay_critical
                    or not self._pending or not director.enabled):
                return False
            if director.metrics()["queued"] >= director.max_events:
                self._counts["director_busy"] += 1
                return False
            entry = self._pending[0]
            elapsed_s = int(max(0.0, now - entry.asked_at))
            context = (
                f"Earlier viewer question (asked {elapsed_s}s ago during gameplay): "
                + entry.question
            )
            offered = StreamSignal(
                signal_id=f"focus_{self._epoch}_{entry.serial}",
                kind="viewer_question", timestamp=now, detail=context,
                speaker_id=entry.speaker_tag, evidence="reported",
            )
            if not director.offer(offered, now=now):
                self._counts["director_busy"] += 1
                return False
            self._pending.popleft()
            self._counts["released"] += 1
            return True

    def metrics(self) -> dict[str, int | bool]:
        """Only anonymous aggregate statistics; no questions or viewer IDs."""
        with self._lock:
            return {
                **self._counts, "queued": len(self._pending),
                "enabled": self._enabled, "critical_focus": self._focus,
            }


__all__ = ["StreamFocusInbox"]
