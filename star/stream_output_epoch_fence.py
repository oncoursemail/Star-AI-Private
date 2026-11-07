"""Host-only epoch fence for asynchronous model, TTS and VTuber output.

Prevents stale generated chunks from being submitted after a trusted host revokes
a turn. This does not itself synthesize, play, record or transmit anything.
Only the local output worker may hold tickets and callbacks; never expose the
ticket or cancel capabilities to viewers, prompts, model tools or plugins.

All callbacks MUST be fast, nonblocking, epoch-scoped host operations. Do not
call dispatch on the audio callback thread. An accepted submit means only that
the host accepted a chunk, NOT that a speaker was audible or a rig moved.
The existing NaturalTurnPhysicalHost remains responsible for stopping/draining
PCM and neutralizing the avatar. No OBS or game-input authorization is granted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from threading import RLock
from typing import Callable, cast

from .stream_director import SpeechIntent
from .stream_natural_turn_physical_host import PhysicalTurnResult

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_KINDS = frozenset({"model_text", "tts_pcm", "avatar_motion"})
_REASONS = frozenset(
    {
        "owner_interrupt",
        "critical_gameplay",
        "unhealthy_output",
        "session_end",
        "timeout",
        "submission_failed",
        "physical_stop",
    }
)
_MAX_CLOCK = 1e13


def _ms(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("finite host-monotonic milliseconds required")
    try:
        out = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid host-monotonic clock") from exc
    if not math.isfinite(out) or not 0 <= out <= _MAX_CLOCK:
        raise ValueError("invalid host-monotonic clock")
    return out


@dataclass(frozen=True, eq=False)
class OutputEpochTicket:
    """Opaque identity ticket. Identity is checked, not user-supplied fields."""

    serial: int
    epoch: str = field(repr=False)


@dataclass(frozen=True)
class OutputFenceResult:
    status: str  # accepted | rejected | revoked | fault | settled
    reason: str
    authorizes_broadcast: bool = False
    authorizes_game_input: bool = False


class StreamOutputEpochFence:
    """Short-lived local output lease with explicit cancellation + quiet ACK.

    The host's trusted generator and TTS engine must honor cancellation by
    generation/PCM epoch, and report independent idle/drained evidence. A new
    turn is not issued until BOTH generation lanes and physical output have
    been verified quiet. Cancel callbacks are invoked once and never blindly
    retried against a possibly reused native process or playout epoch.
    """

    def __init__(
        self,
        *,
        cancel_model: Callable[[str], bool],
        cancel_tts: Callable[[str], bool],
        max_age_ms: float = 30_000.0,
        max_chunks: int = 8192,
    ) -> None:
        if not callable(cancel_model) or not callable(cancel_tts):
            raise TypeError("trusted host cancellation callbacks required")
        max_age = _ms(max_age_ms)
        if not 1 <= max_age <= 120_000:
            raise ValueError("turn age budget must be 1..120000 ms")
        if type(max_chunks) is not int or not 1 <= max_chunks <= 100_000:
            raise ValueError("bounded number of chunks required")
        self._cancel_model = cancel_model
        self._cancel_tts = cancel_tts
        self._max_age = max_age
        self._max_chunks = max_chunks
        self._lock = RLock()
        self._enabled = False
        self._serial = 0
        self._active: OutputEpochTicket | None = None
        self._pending: OutputEpochTicket | None = None
        self._cancel_ok = (False, False)
        self._started_ms: float | None = None
        self._last_ms: float | None = None
        self._chunks = 0
        self._dispatching = False
        self._faulted = False
        self._counts = dict(issued=0, accepted=0, rejected=0, revoked=0, settled=0)

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("local owner opt-in required")
        with self._lock:
            if self._active is not None or self._pending is not None or self._faulted:
                raise RuntimeError("previous output epoch is not settled")
            self._enabled = True

    def issue(self, prepared: PhysicalTurnResult, *, epoch: str, now_ms: float) -> OutputEpochTicket:
        """Attach to trusted host-reviewed 'prepare'; never starts playback."""
        now = _ms(now_ms)
        if (
            type(prepared) is not PhysicalTurnResult
            or prepared.action != "prepare"
            or type(prepared.intent) is not SpeechIntent
        ):
            raise ValueError("trusted prepared dialogue required")
        if prepared.authorizes_playback or prepared.authorizes_broadcast:
            raise ValueError("untrusted playback authorization")
        if type(epoch) is not str or _EPOCH.fullmatch(epoch) is None:
            raise ValueError("bounded native epoch required")
        with self._lock:
            if not self._enabled or self._active is not None or self._pending is not None or self._faulted:
                raise RuntimeError("output lease not available")
            if self._last_ms is not None and now < self._last_ms:
                raise ValueError("host monotonic clock moved backwards")
            self._serial += 1
            ticket = OutputEpochTicket(self._serial, epoch)
            self._active = ticket
            self._started_ms = self._last_ms = now
            self._chunks = 0
            self._counts["issued"] += 1
            return ticket

    @staticmethod
    def _call(callback: Callable[[str], bool], epoch: str) -> bool:
        try:
            return callback(epoch) is True
        except Exception:
            return False

    def _revoke_locked(self, ticket: OutputEpochTicket) -> bool:
        if ticket is not self._active:
            return False
        # Invalidate the output ticket BEFORE calling potentially reentrant
        # host cancellation callbacks. The old ticket will never work again.
        self._active = None
        self._pending = ticket
        self._cancel_ok = (False, False)
        self._counts["revoked"] += 1
        first = self._call(self._cancel_model, ticket.epoch)
        second = self._call(self._cancel_tts, ticket.epoch)
        self._cancel_ok = (first, second)
        self._faulted = not (first and second)
        return first and second

    def revoke(self, ticket: OutputEpochTicket, *, reason: str) -> OutputFenceResult:
        """Trusted host calls on owner barge-in/danger before physical stop."""
        if type(reason) is not str or reason not in _REASONS:
            raise ValueError("fixed host reason required")
        with self._lock:
            if ticket is not self._active:
                self._counts["rejected"] += 1
                return OutputFenceResult("rejected", "stale_output_epoch")
            ok = self._revoke_locked(ticket)
            return OutputFenceResult(
                "revoked" if ok else "fault", "awaiting_independent_quiet" if ok else "cancel_uncertain"
            )

    def dispatch(
        self, ticket: OutputEpochTicket, *, kind: str, now_ms: float, submit: Callable[[str, str], bool]
    ) -> OutputFenceResult:
        """Host-only atomic fence+submit. submit must be a fast queue operation.

        Caller supplies a sealed, nonblocking queue closure. No generated
        transcript, PCM bytes, viewer data or native handle enters this class.
        The output worker must NOT bypass this fence when feeding its queues.
        """
        now = _ms(now_ms)
        if type(kind) is not str or kind not in _KINDS or not callable(submit):
            raise ValueError("approved output kind and host submit required")
        with self._lock:
            if not self._enabled or ticket is not self._active or self._dispatching:
                self._counts["rejected"] += 1
                return OutputFenceResult("rejected", "stale_or_disabled_epoch")
            assert self._started_ms is not None
            if (
                self._last_ms is not None
                and now < self._last_ms
                or now - self._started_ms > self._max_age
                or self._chunks >= self._max_chunks
            ):
                self._revoke_locked(ticket)
                return OutputFenceResult("revoked", "epoch_budget_or_clock_invalid")
            self._last_ms = now
            self._dispatching = True
            try:
                ok = submit(ticket.epoch, kind) is True
            except Exception:
                ok = False
            finally:
                self._dispatching = False
            if not ok or ticket is not self._active:
                if ticket is self._active:
                    self._revoke_locked(ticket)
                return OutputFenceResult("fault", "submit_failed_or_reentrant_revoke")
            self._chunks += 1
            self._counts["accepted"] += 1
            return OutputFenceResult("accepted", "host_queue_accepted")

    @staticmethod
    def _quiet(*, model_idle: bool, tts_idle: bool, pcm_drained: bool, avatar_neutral: bool) -> bool:
        return model_idle is True and tts_idle is True and pcm_drained is True and avatar_neutral is True

    def settle(
        self,
        ticket: OutputEpochTicket,
        *,
        model_idle: bool,
        tts_idle: bool,
        pcm_drained: bool,
        avatar_neutral: bool,
        owner_recovery: bool = False,
    ) -> OutputFenceResult:
        """Close revoked epoch only after independent device/lane observation."""
        for value in (model_idle, tts_idle, pcm_drained, avatar_neutral, owner_recovery):
            if type(value) is not bool:
                raise ValueError("trusted independent boolean observations required")
        with self._lock:
            if ticket is not self._pending:
                return OutputFenceResult("rejected", "no_matching_revoked_epoch")
            if self._faulted and not owner_recovery:
                return OutputFenceResult("fault", "owner_recovery_required")
            if not self._quiet(
                model_idle=model_idle, tts_idle=tts_idle, pcm_drained=pcm_drained, avatar_neutral=avatar_neutral
            ):
                return OutputFenceResult("rejected", "unconfirmed_lanes_or_device")
            if not all(self._cancel_ok) and not owner_recovery:
                return OutputFenceResult("fault", "cancel_unconfirmed")
            self._pending = None
            self._faulted = False
            self._counts["settled"] += 1
            # No automatic new turn after cancellation.
            self._enabled = False
            return OutputFenceResult("settled", "verified_quiet_after_revoke")

    def retire_finished(
        self, ticket: OutputEpochTicket, *, model_idle: bool, tts_idle: bool, pcm_drained: bool, avatar_neutral: bool
    ) -> bool:
        """Natural completion must also prevent late model/TTS output."""
        for value in (model_idle, tts_idle, pcm_drained, avatar_neutral):
            if type(value) is not bool:
                raise ValueError("trusted independent boolean observations required")
        with self._lock:
            if ticket is not self._active or self._dispatching:
                return False
            if not self._quiet(
                model_idle=model_idle, tts_idle=tts_idle, pcm_drained=pcm_drained, avatar_neutral=avatar_neutral
            ):
                return False
            self._active = None
            self._counts["settled"] += 1
            return True

    def disable(self) -> OutputFenceResult:
        """Owner shutdown invalidates every active ticket, never auto-rearms."""
        with self._lock:
            self._enabled = False
            if self._active is not None:
                ok = self._revoke_locked(self._active)
                return OutputFenceResult("revoked" if ok else "fault", "session_disabled")
            return OutputFenceResult("rejected", "already_inactive")

    def metrics(self) -> dict[str, int | bool]:
        """Bounded counters only: no transcripts, audio, epochs or secrets."""
        with self._lock:
            return {
                **self._counts,
                "enabled": self._enabled,
                "active": self._active is not None,
                "quiet_pending": self._pending is not None,
                "faulted": self._faulted,
            }


__all__ = ["OutputEpochTicket", "OutputFenceResult", "StreamOutputEpochFence"]
