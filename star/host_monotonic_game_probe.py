"""Local, opt-in host event clock for private gameplay-latency diagnostics.

Records event times by calling one process-local monotonic_ns clock itself,
rather than trusting a list of externally supplied timestamps. This does NOT
establish an independently trusted game host, prove that game input moved a
character, control games, make network calls, or publish OBS broadcasts.

An authorized application must call capture/decision_ready/action_submitted/
action_ack at the corresponding REAL host lifecycle boundaries. Acknowledgment
must be from the host, not a language-model assertion. Clock readings and
in-flight event details never leave memory through report APIs.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event, RLock
from time import monotonic_ns
from typing import Callable, NoReturn

from .measured_game_latency import (
    LocalFrameTiming, PrivateLatencyReplay, prepare_private_latency_replay,
)

_MAX_NS = (1 << 63) - 1
_MAX_FRAMES = 256


@dataclass(slots=True)
class _PendingFrame:
    capture_ns: int
    decision_ready_ns: int | None = None
    action_submit_ns: int | None = None
    pre_submit_check_ns: int | None = None


class HostMonotonicGameProbe:
    """Single-use, local-only host recorder; all public methods are threadsafe.

    Host owns all callback sources. A user/model cannot prove successful game
    movement by supplying a callback name. Failures revoke the entire window:
    partially completed, reordered, or aborted frames must never disappear
    from a successful latency benchmark.

    The optional clock is only for deterministic testing; injection is not
    independently attested and must not be presented as hardware proof.
    """

    def __init__(
        self, *, owner_approved: bool = False,
        clock: Callable[[], int] | None = None,
        require_frame_opportunities: bool = False,
        max_queue_wait_ns: int | None = None,
        max_action_age_ns: int | None = None,
        require_submit_confirmation: bool = False,
        max_ack_wait_ns: int | None = None,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("private host timing requires owner approval")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be a callable monotonic_ns source")
        if type(require_frame_opportunities) is not bool:
            raise TypeError("require_frame_opportunities must be bool")
        if max_queue_wait_ns is not None:
            if not require_frame_opportunities:
                raise ValueError("queue deadline requires frame-opportunity coverage")
            if type(max_queue_wait_ns) is not int or not 1_000_000 <= max_queue_wait_ns <= 10_000_000_000:
                raise ValueError("max_queue_wait_ns must be 1ms..10s integer")
        if max_action_age_ns is not None:
            if type(max_action_age_ns) is not int or not 1_000_000 <= max_action_age_ns <= 10_000_000_000:
                raise ValueError("max_action_age_ns must be 1ms..10s integer")
        if type(require_submit_confirmation) is not bool:
            raise TypeError("require_submit_confirmation must be bool")
        if require_submit_confirmation and max_action_age_ns is None:
            raise ValueError("host submission confirmation requires an action deadline")
        if max_ack_wait_ns is not None:
            if type(max_ack_wait_ns) is not int or not 1_000_000 <= max_ack_wait_ns <= 10_000_000_000:
                raise ValueError("max_ack_wait_ns must be 1ms..10s integer")
        self._max_ack_wait_ns = max_ack_wait_ns
        self._ack_deadline_violations = 0
        self._require_submit_confirmation = require_submit_confirmation
        self._host_submit_rejections = 0
        self._max_action_age_ns = max_action_age_ns
        self._action_deadline_violations = 0
        self._max_queue_wait_ns = max_queue_wait_ns
        self._coverage_required = require_frame_opportunities
        self._opportunities: dict[int, int] = {}
        self._opportunity_total = 0
        self._dropped_opportunities = 0
        self._clock = monotonic_ns if clock is None else clock
        self._lock = RLock()
        # A native host callback can block while holding _lock. This fence is
        # deliberately set without acquiring _lock on emergency abort.
        self._abort_signal = Event()
        self._last_clock_ns: int | None = None
        self._started = 0
        self._next_ack = 1
        self._pending: dict[int, _PendingFrame] = {}
        self._completed: dict[int, LocalFrameTiming] = {}
        self._revoked = False
        self._in_host_dispatch = False
        self._finalized = False
        self._replay: PrivateLatencyReplay | None = None

    def _clear_and_revoke(self) -> None:
        self._abort_signal.set()
        self._revoked = True
        self._pending.clear()
        self._completed.clear()
        self._opportunities.clear()
        self._replay = None

    def _require_open(self) -> None:
        # Emergency abort must be effective even when another thread could not
        # acquire _lock while a native submission callback was blocked.
        if self._abort_signal.is_set():
            self._clear_and_revoke()
            raise RuntimeError("private timing window revoked")
        # Host callbacks are reentrant under RLock, but must never change the
        # active window while their side effect is in progress.
        if self._in_host_dispatch:
            self._clear_and_revoke()
            raise RuntimeError("host callback attempted reentrant probe mutation")
        if self._revoked:
            raise RuntimeError("private timing window revoked")
        if self._finalized:
            raise RuntimeError("private timing window already finalized")

    def _fail(self, reason: str) -> NoReturn:
        self._clear_and_revoke()
        raise ValueError(reason)

    def _sample(self) -> int:
        try:
            now = self._clock()
        except Exception as exc:
            self._clear_and_revoke()
            raise RuntimeError("host monotonic clock failed") from exc
        if type(now) is not int or not 0 <= now <= _MAX_NS:
            self._fail("host clock must return a nonnegative int64 monotonic_ns")
        if self._last_clock_ns is not None and now < self._last_clock_ns:
            self._fail("host monotonic clock moved backward")
        self._last_clock_ns = now
        return now

    def frame_available(self) -> int:
        """Witness a frame *before* deciding whether to process it.

        The approved host must call this for EVERY frame it offers to the
        agent. This is host-reported coverage, not independent attestation.
        """
        with self._lock:
            self._require_open()
            if not self._coverage_required:
                self._fail("frame-opportunity coverage was not enabled")
            if self._opportunity_total >= _MAX_FRAMES:
                self._fail("host frame-opportunity window exceeded 256 frames")
            now = self._sample()
            self._opportunity_total += 1
            self._opportunities[self._opportunity_total] = now
            return self._opportunity_total

    def drop_frame(self, opportunity: int, *, reason: str) -> None:
        """Explicit host-observed drop aborts the entire benchmark window.

        Keeping a counter makes the failure visible without reporting raw
        frames or permitting a success-only latency sample to be finalized.
        """
        with self._lock:
            self._require_open()
            allowed = {"capture_overrun", "inference_timeout", "host_error", "privacy_stop"}
            if (not self._coverage_required or type(opportunity) is not int
                    or opportunity not in self._opportunities
                    or type(reason) is not str or reason not in allowed):
                self._fail("invalid dropped-frame report")
            self._dropped_opportunities += 1
            self._fail("host observed a dropped frame; timing window revoked")

    def capture(self, *, opportunity: int | None = None) -> int:
        """Start frame processing; optionally account for time spent queued.

        With frame-opportunity coverage on, frame_available must have
        witnessed every frame, and each must be claimed in arrival order.
        The original host-available time is used as the capture timestamp.
        """
        with self._lock:
            self._require_open()
            if self._started >= _MAX_FRAMES:
                self._fail("host timing window exceeded 256 frames")
            if self._coverage_required:
                if (type(opportunity) is not int or opportunity != self._started + 1
                        or opportunity not in self._opportunities):
                    self._fail("missing, duplicated, or out-of-order frame opportunity")
                processing_ns = self._sample()
                capture_ns = self._opportunities.pop(opportunity)
                if (self._max_queue_wait_ns is not None
                        and processing_ns - capture_ns > self._max_queue_wait_ns):
                    self._dropped_opportunities += 1
                    self._fail("frame queue wait exceeded configured deadline")
            else:
                if opportunity is not None:
                    self._fail("unexpected frame opportunity in legacy mode")
                capture_ns = self._sample()
            self._started += 1
            self._pending[self._started] = _PendingFrame(capture_ns)
            return self._started

    def _get(self, sequence: int) -> _PendingFrame:
        if type(sequence) is not int or sequence not in self._pending:
            self._fail("unknown or already acknowledged frame")
        return self._pending[sequence]

    def decision_ready(self, sequence: int) -> None:
        """Mark completion of reasoning; this does not authorize input."""
        with self._lock:
            self._require_open()
            pending = self._get(sequence)
            if pending.decision_ready_ns is not None:
                self._fail("duplicate decision-ready event")
            pending.decision_ready_ns = self._sample()

    def pre_submit_check(self, sequence: int) -> None:
        """Check frame age immediately BEFORE the approved host issues input.

        This is a local deadline gate, NOT an input authorization, signed
        observation, or guarantee about actions the host later performs.
        Integrators must call it on the actual submission path and must not
        send input if it raises. A second check at action_submitted detects
        time spent between this gate and the host acknowledgment of submission.
        """
        with self._lock:
            self._require_open()
            if self._max_action_age_ns is None:
                self._fail("action freshness deadline was not enabled")
            pending = self._get(sequence)
            if (pending.decision_ready_ns is None or pending.action_submit_ns is not None
                    or pending.pre_submit_check_ns is not None):
                self._fail("pre-submit check requires one ready, unsubmitted decision")
            now = self._sample()
            if now - pending.capture_ns > self._max_action_age_ns:
                self._action_deadline_violations += 1
                self._fail("action deadline expired before host input")
            pending.pre_submit_check_ns = now

    def guarded_dispatch(self, sequence: int, submit: Callable[[], object]) -> None:
        """Invoke one approved host callback only while the frame is fresh.

        Opt-in alternative to calling pre_submit_check() and action_submitted()
        separately. The probe invokes the callback synchronously while holding
        its state lock, samples time immediately before and after it, and
        revokes the entire evidence window if submission fails or expires.

        The callback MUST be supplied by an owner-approved host. It is NOT a
        game controller, a trust proof, or an uninterruptible hardware gate:
        a blocking callback can still submit stale input before returning.
        A callback returning False is always rejected. When the opt-in
        require_submit_confirmation flag is enabled, the callback MUST return
        exactly True, meaning the host accepted the input *submission request*.
        This is neither OS/device delivery proof nor a game-state transition.
        """
        with self._lock:
            self._require_open()
            if self._max_action_age_ns is None:
                self._fail("guarded dispatch requires an action age deadline")
            if not callable(submit):
                self._fail("guarded dispatch requires a host callback")
            pending = self._get(sequence)
            if (pending.decision_ready_ns is None or pending.action_submit_ns is not None
                    or pending.pre_submit_check_ns is not None):
                self._fail("guarded dispatch requires one ready, unchecked decision")

            now = self._sample()
            if now - pending.capture_ns > self._max_action_age_ns:
                self._action_deadline_violations += 1
                self._fail("action deadline expired before guarded dispatch")
            pending.pre_submit_check_ns = now

            self._in_host_dispatch = True
            returned = False
            confirmation: object = None
            try:
                confirmation = submit()
                returned = True
            finally:
                self._in_host_dispatch = False
                if not returned:
                    # Even if the callback had partial side effects, it must
                    # never be silently counted as a successful submission.
                    self._clear_and_revoke()

            self._require_open()
            if confirmation is False or (
                self._require_submit_confirmation and confirmation is not True
            ):
                self._host_submit_rejections += 1
                self._fail("approved host did not confirm input submission")
            submitted_ns = self._sample()
            if submitted_ns - pending.capture_ns > self._max_action_age_ns:
                self._action_deadline_violations += 1
                self._fail("action deadline expired during guarded dispatch")
            pending.action_submit_ns = submitted_ns

    def action_submitted(self, sequence: int) -> None:
        """Mark legacy host submission; forbidden under strict confirmation.

        Strict-mode hosts must use guarded_dispatch(), which invokes the
        approved callback and verifies its exact-True acceptance response.
        """
        with self._lock:
            self._require_open()
            if self._require_submit_confirmation:
                self._fail("strict host confirmation requires guarded_dispatch")
            pending = self._get(sequence)
            if pending.decision_ready_ns is None or pending.action_submit_ns is not None:
                self._fail("submission requires one prior decision-ready event")
            if self._max_action_age_ns is not None and pending.pre_submit_check_ns is None:
                self._fail("action submission requires a pre-submit deadline check")
            now = self._sample()
            if self._max_action_age_ns is not None and now - pending.capture_ns > self._max_action_age_ns:
                self._action_deadline_violations += 1
                self._fail("action deadline expired during host submission")
            pending.action_submit_ns = now

    def action_ack(self, sequence: int) -> None:
        """Mark observed host ACK (not proof of movement or game success)."""
        with self._lock:
            self._require_open()
            pending = self._get(sequence)
            ready_ns = pending.decision_ready_ns
            submitted_ns = pending.action_submit_ns
            if ready_ns is None or submitted_ns is None or sequence != self._next_ack:
                self._fail("ACK requires host submission and in-order completion")
            now = self._sample()
            if (self._max_ack_wait_ns is not None
                    and now - submitted_ns > self._max_ack_wait_ns):
                self._ack_deadline_violations += 1
                self._fail("host acknowledgment deadline exceeded")
            # LocalFrameTiming independently validates intra-frame ordering
            # and rejects stalled/mixed-clock intervals over 30 seconds.
            try:
                timing = LocalFrameTiming(
                    sequence=sequence, capture_ns=pending.capture_ns,
                    decision_ready_ns=ready_ns,
                    action_submit_ns=submitted_ns, action_ack_ns=now,
                )
            except (ValueError, TypeError) as exc:
                self._clear_and_revoke()
                raise ValueError("invalid host frame timing") from exc
            self._completed[sequence] = timing
            del self._pending[sequence]
            self._next_ack += 1

    def abort(self) -> None:
        """Immediately latch cancellation; never wait for a blocked host callback.

        Only the evidence window is cancelled. An already-running native input
        callback can still have side effects, so a separate native host must
        enforce cancellation, all-keys-up and maximum key-hold deadlines.
        If dispatch owns the state lock, the in-flight method purges the
        window when it returns; no later operation can finalize that window.
        """
        self._abort_signal.set()
        if self._lock.acquire(blocking=False):
            try:
                self._clear_and_revoke()
            finally:
                self._lock.release()

    def status(self) -> dict[str, int | bool]:
        """Counts only, including incomplete frames; no raw times or media."""
        with self._lock:
            result: dict[str, int | bool] = {
                "started_frames": self._started,
                "completed_frames": len(self._completed) if not self._finalized and not self._revoked
                                    else (self._started if self._finalized else 0),
                "pending_frames": len(self._pending),
                "revoked": self._revoked,
                "finalized": self._finalized,
                "independent_gameplay_proof": False,
                "timing_attested": False,
            }
            if self._max_action_age_ns is not None:
                result.update({
                    "action_deadline_guard_active": True,
                    "action_deadline_violations": self._action_deadline_violations,
                    "action_freshness_attested": False,
                })
            if self._max_ack_wait_ns is not None:
                result.update({
                    "ack_deadline_guard_active": True,
                    "ack_deadline_violations": self._ack_deadline_violations,
                    "ack_delivery_attested": False,
                })
            if self._require_submit_confirmation:
                result.update({
                    "host_submit_confirmation_required": True,
                    "host_submit_rejections": self._host_submit_rejections,
                    "host_submission_attested": False,
                })
            if self._coverage_required:
                result.update({
                    "frame_opportunities": self._opportunity_total,
                    "unclaimed_opportunities": self._opportunity_total - self._started,
                    "dropped_opportunities": self._dropped_opportunities,
                    "host_coverage_attested": False,
                })
            return result

    def finalize(self, *, tick_ns: int = 100_000_000) -> PrivateLatencyReplay:
        """Consume complete observations; reject any missing/cancelled frame."""
        with self._lock:
            self._require_open()
            if (not self._started or self._pending or len(self._completed) != self._started
                    or (self._coverage_required and (
                        self._opportunities or self._opportunity_total != self._started
                    ))):
                self._clear_and_revoke()
                raise ValueError("incomplete window cannot produce a success-only replay")
            captures = tuple(self._completed[n] for n in range(1, self._started + 1))
            try:
                replay = prepare_private_latency_replay(
                    captures, owner_approved=True, tick_ns=tick_ns,
                )
            except (ValueError, TypeError):
                self._clear_and_revoke()
                raise
            finally:
                # Destroy retained raw monotonic timestamps on finalization.
                self._completed.clear()
                self._pending.clear()
            # An abort may be posted by another thread while replay assembly
            # owns the state lock; discard the result rather than publish it.
            if self._abort_signal.is_set():
                self._clear_and_revoke()
                raise RuntimeError("private timing window revoked")
            self._finalized = True
            self._replay = replay
            return replay


__all__ = ["HostMonotonicGameProbe"]