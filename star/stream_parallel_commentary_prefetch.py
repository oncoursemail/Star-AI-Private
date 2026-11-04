"""Bounded parallel commentary drafting for Star's opt-in gaming VTuber.

During one *already audible* utterance, a host may reserve at most two
low-priority events and generate their next candidate text on another worker.
This avoids serializing text generation behind audio playout. It does NOT
synthesize, queue, play, publish or approve audio, nor control a game or OBS.

A candidate is usable only if a newly chosen, real StarStage plan still matches
the original event, the scene epoch and worker identity are unchanged, the
draft was moderated by the trusted host, and the utterance is still fresh.
StarStage.queue_audio(), preplay_clearance(), real PCM device evidence and the
live output fence remain mandatory AFTER consumption. A model or viewer must
not supply host_verified, model_epoch, scene_epoch, or moderation assertions.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
from typing import cast

from .stream_director import StreamSignal
from .stream_stage import StagePlan, StarStage

_ALLOWED = frozenset({"game_success", "game_observation", "viewer_question"})
_MAX_CLOCK_S = 1e10
_MAX_EPOCH = 10**12


def _time(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host clock must be numeric")
    try:
        number = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid host clock") from exc
    if not math.isfinite(number) or not 0 <= number <= _MAX_CLOCK_S:
        raise ValueError("invalid host clock")
    return number


def _epoch(value: object, label: str) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_EPOCH:
        raise ValueError(f"{label} must be a trusted positive integer")
    return value


@dataclass(frozen=True)
class PrefetchTicket:
    """Opaque in-process one-shot reservation, not a speech authorization."""
    serial: int
    session_epoch: int


@dataclass(frozen=True)
class PreparedComment:
    """Moderated candidate text; still NOT authorized for audio playback."""
    text: str
    signal_id: str
    authorizes_audio_output: bool = False
    authorizes_broadcast: bool = False


@dataclass
class _Entry:
    ticket: PrefetchTicket
    signal: StreamSignal
    scene_epoch: int
    model_epoch: int
    expires_at: float
    text: str | None = None


class StreamParallelCommentaryPrefetch:
    """Optional small staging buffer for *text only* during ongoing audio.

    No thread or model is spawned: the host reserves, runs its own model worker
    concurrently, then submits the result. Host must use a low-priority worker
    and stop speculative inference under GPU/OBS/voice pressure. This component
    only enforces bound/identity/expiry at the handoff.
    """

    def __init__(self, *, capacity: int = 2, max_age_s: float = 4.0) -> None:
        if type(capacity) is not int or not 1 <= capacity <= 3:
            raise ValueError("capacity must be 1..3")
        age = _time(max_age_s)
        if not 0.2 <= age <= 8.0:
            raise ValueError("prefetch age must be 0.2..8 seconds")
        self._capacity = capacity
        self._max_age = age
        self._lock = RLock()
        self._enabled = False
        self._session_epoch = 0
        self._serial = 0
        self._pending: dict[int, _Entry] = {}
        self._counts = {
            "reserved": 0, "prepared": 0, "consumed": 0,
            "rejected": 0, "stale": 0, "cancelled": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("speculative commentary requires host opt-in")
        with self._lock:
            # Each new session invalidates even an identical older signal.
            self._session_epoch += 1
            self._pending.clear()
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._session_epoch += 1
            self._counts["cancelled"] += len(self._pending)
            self._pending.clear()
            self._enabled = False

    def scene_changed(self, *, host_verified: bool = False) -> None:
        """Flush old-game drafts *before* the host transitions StarStage."""
        if host_verified is not True:
            raise PermissionError("trusted host scene transition required")
        with self._lock:
            self._session_epoch += 1
            self._counts["cancelled"] += len(self._pending)
            self._pending.clear()

    def _expire(self, now: float) -> None:
        expired = [i for i, item in self._pending.items() if now > item.expires_at]
        for i in expired:
            self._pending.pop(i)
        self._counts["stale"] += len(expired)

    def reserve(
        self, signal: StreamSignal, *, stage: StarStage, audible_plan: StagePlan,
        now_s: float, model_epoch: int, scene_epoch: int,
        host_verified: bool = False, moderated_source: bool = False,
        spare_compute: bool = False,
    ) -> PrefetchTicket | None:
        """Reserve low-priority work only while an existing plan is audible.

        The trusted host should call stage.offer(signal) separately first. An
        accepted source is no guarantee the event wins later arbitration.
        """
        now = _time(now_s)
        model = _epoch(model_epoch, "model_epoch")
        scene = _epoch(scene_epoch, "scene_epoch")
        if not isinstance(signal, StreamSignal):
            raise TypeError("typed moderated stream signal required")
        if not isinstance(stage, StarStage) or not isinstance(audible_plan, StagePlan):
            raise TypeError("an actual audible StarStage plan is required")
        with self._lock:
            self._expire(now)
            if (not self._enabled or host_verified is not True
                    or moderated_source is not True or spare_compute is not True
                    or not stage.current(audible_plan)
                    or signal.kind not in _ALLOWED
                    or (signal.kind.startswith("game_") and (
                        signal.evidence != "observed" or not signal.game_scope
                    ))
                    or not 0 <= now - signal.timestamp <= self._max_age
                    or len(self._pending) >= self._capacity
                    or any(e.signal.signal_id == signal.signal_id
                           for e in self._pending.values())):
                self._counts["rejected"] += 1
                return None
            self._serial += 1
            ticket = PrefetchTicket(self._serial, self._session_epoch)
            self._pending[ticket.serial] = _Entry(
                ticket=ticket, signal=signal,
                scene_epoch=scene, model_epoch=model,
                expires_at=min(signal.timestamp + self._max_age,
                               now + self._max_age),
            )
            self._counts["reserved"] += 1
            return ticket

    def complete(
        self, ticket: PrefetchTicket, *, text: str, now_s: float,
        model_epoch: int, host_moderated: bool = False,
    ) -> bool:
        """Accept an independently moderated draft from the *same* AI worker."""
        now = _time(now_s)
        model = _epoch(model_epoch, "model_epoch")
        if (type(text) is not str or not 1 <= len(text) <= 320
                or any(not char.isprintable() for char in text)):
            raise ValueError("candidate must be one printable short utterance")
        if not isinstance(ticket, PrefetchTicket):
            raise TypeError("expected an issued PrefetchTicket")
        with self._lock:
            self._expire(now)
            entry = self._pending.get(ticket.serial)
            if (not self._enabled or host_moderated is not True
                    or entry is None or entry.ticket is not ticket
                    or ticket.session_epoch != self._session_epoch
                    or entry.model_epoch != model or entry.text is not None):
                self._counts["rejected"] += 1
                return False
            entry.text = text
            self._counts["prepared"] += 1
            return True

    def take_for_plan(
        self, ticket: PrefetchTicket, *, stage: StarStage, plan: StagePlan,
        now_s: float, model_epoch: int, scene_epoch: int,
        host_verified: bool = False, spare_compute: bool = False,
    ) -> PreparedComment | None:
        """One-time text handoff; host STILL verifies playback via StarStage.

        If the arbitrator selects a different event, a previous round, or a
        newer worker, nothing is returned. A stage transition after this return
        invalidates the original plan: re-check stage.prepared(plan) before PCM.
        """
        now = _time(now_s)
        model = _epoch(model_epoch, "model_epoch")
        scene = _epoch(scene_epoch, "scene_epoch")
        if not isinstance(ticket, PrefetchTicket):
            raise TypeError("expected issued ticket")
        if not isinstance(stage, StarStage) or not isinstance(plan, StagePlan):
            raise TypeError("a real prepared plan is required")
        with self._lock:
            self._expire(now)
            entry = self._pending.get(ticket.serial)
            # Never consume another reservation when a forged/stale receipt
            # happens to reuse the same serial number.
            if entry is None or entry.ticket is not ticket:
                self._counts["rejected"] += 1
                return None
            if (not self._enabled or host_verified is not True
                    or spare_compute is not True
                    or ticket.session_epoch != self._session_epoch
                    or entry.scene_epoch != scene or entry.model_epoch != model
                    or entry.text is None or not stage.prepared(plan)
                    or plan.deadline_at < now
                    or plan.signal_id != entry.signal.signal_id
                    or plan.kind != entry.signal.kind
                    or plan.evidence != entry.signal.evidence
                    or plan.game_scope != entry.signal.game_scope):
                # Mismatch is terminal: never recycle a stale draft into another turn.
                self._pending.pop(ticket.serial)
                self._counts["rejected"] += 1
                return None
            self._pending.pop(ticket.serial)
            self._counts["consumed"] += 1
            return PreparedComment(entry.text, entry.signal.signal_id)

    def metrics(self) -> dict[str, int | bool]:
        """Privacy-minimal counts only; no chat, utterance, model or game IDs."""
        with self._lock:
            return {**self._counts, "pending": len(self._pending),
                    "enabled": self._enabled}


__all__ = ["PreparedComment", "PrefetchTicket", "StreamParallelCommentaryPrefetch"]
