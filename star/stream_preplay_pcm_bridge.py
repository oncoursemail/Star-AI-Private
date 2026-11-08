"""Owner-host-only handoff from reviewed VTuber dialogue to epoch-scoped PCM.

This joins two existing otherwise independent safety fences: StreamPreplayGate
and LocalEpochPCMSink. A trusted native host must exclusively own both objects,
run methods off the audio callback thread, and provide *independent* native
quiet evidence. App-queue emptiness and caller booleans are NOT proof of actual
hardware silence. This module does not create devices, play by itself, start
OBS, access microphones/game input, or establish audible listener receipt.

The bridge is opt-in and deliberately narrow: it handles reviewed playout and
STOP+FLUSH on shutdown, including a bound on continuous synthesized speech.
A separately witnessed normal completion is supported only after queued PCM
has drained and native audibility/quiet receipts agree. Do not call
gate.settle() independently to bypass this bridge. Failed stop stays
quarantined until manual device recovery.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .stream_director import SpeechIntent
from .stream_epoch_pcm_sink import LocalEpochPCMSink
from .stream_preplay_gate import PreplayDecision, StreamPreplayGate


@dataclass(frozen=True)
class PCMBridgeAdvice:
    state: str  # disabled | ready | held | stop_requested | quiet | fault
    reason: str
    permits_broadcast: bool = False
    confirms_audibility: bool = False
    permits_game_input: bool = False


class StreamPreplayPCMBridge:
    """Serialized single-turn integration of speech review and native PCM.

    The host must never share the gate or PCM sink with another independent
    producer/consumer while this bridge owns them. All native stop evidence
    comes from an authorized device observer, not the LLM or viewer messages.
    """

    def __init__(
        self, gate: StreamPreplayGate, sink: LocalEpochPCMSink, *,
        max_turn_pcm_ms: int = 30_000,
    ) -> None:
        if type(gate) is not StreamPreplayGate or type(sink) is not LocalEpochPCMSink:
            raise TypeError("existing trusted preplay gate and PCM sink required")
        if type(max_turn_pcm_ms) is not int or not 1_000 <= max_turn_pcm_ms <= 60_000:
            raise ValueError("per-turn PCM budget must be 1..60 seconds")
        self._max_turn_pcm_ms = max_turn_pcm_ms
        # PCM is 16-bit mono; an integer byte budget avoids float rounding
        # errors and does not rely on a model-estimated speaking duration.
        self._max_pcm_bytes = sink.sample_rate * max_turn_pcm_ms // 500
        self._turn_pcm_bytes = 0
        self._budget_stops = 0
        self._spoken_completions = 0
        self._gate = gate
        self._sink = sink
        self._lock = RLock()
        self._enabled = False
        self._intent: SpeechIntent | None = None
        self._epoch: str | None = None
        self._stopping = False
        self._faulted = False
        self._stopped = 0
        self._rejected = 0

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must approve local PCM handoff")
        with self._lock:
            if self._enabled or self._intent is not None or self._faulted:
                raise RuntimeError("complete prior PCM stop/recovery first")
            # Caller must separately enable gate and sink. Never enable either
            # component on behalf of an unverified local caller.
            self._enabled = True

    def admit(
        self, review: PreplayDecision, *, epoch: str, now_s: float,
        independently_quiet: bool = False,
    ) -> PCMBridgeAdvice:
        """Bind a fresh hardware epoch ONLY for the actual reviewed intent.

        Return value is not broadcast or audible-output authorization. A
        separate authorized host owns the SoundSpeaker and OBS boundaries.
        """
        if type(independently_quiet) is not bool:
            raise ValueError("independent native quiet flag must be boolean")
        if type(review) is not PreplayDecision:
            raise TypeError("typed preplay decision required")
        with self._lock:
            if not self._enabled or self._faulted or self._stopping:
                return PCMBridgeAdvice("disabled", "owner_handoff_unavailable")
            if self._intent is not None:
                return PCMBridgeAdvice("held", "previous_native_epoch_not_settled")
            if (review.status != "reviewed" or review.intent is None
                    or not self._gate.reviewed_for_host(review.intent, now_s=now_s)):
                return PCMBridgeAdvice("held", "stale_or_unreviewed_dialogue")
            result = self._sink.bind(epoch, independently_quiet=independently_quiet)
            if result.status != "ready":
                return PCMBridgeAdvice("held", "pcm_" + result.reason)
            self._intent = review.intent
            self._epoch = epoch
            self._turn_pcm_bytes = 0
            return PCMBridgeAdvice("ready", "reviewed_intent_and_unique_native_epoch")

    def submit(self, intent: SpeechIntent, *, epoch: str, pcm16: bytes) -> bool:
        """Forward bounded PCM into the host-owned, pre-started sink only.

        A successful submission is QUEUED audio, not proof it played or was
        heard. The sink still checks PCM format, buffer and native epoch.
        """
        with self._lock:
            if (not self._enabled or self._stopping or self._faulted
                    or self._intent is not intent or self._epoch != epoch
                    or not self._gate.reviewed_for_host(intent)
                    or type(pcm16) is not bytes):
                self._rejected += 1
                return False
            if self._turn_pcm_bytes + len(pcm16) > self._max_pcm_bytes:
                # Stop the physical queue, not just the generator. Otherwise
                # unbounded streaming TTS can talk over a new game moment for
                # minutes while a short per-buffer limit appears healthy.
                # Shutdown stays quarantined until native STOP+FLUSH evidence.
                self._rejected += 1
                self._budget_stops += 1
                self.disable()
                return False
            result = self._sink.submit(epoch, "tts_pcm", pcm16)
            if result:
                self._turn_pcm_bytes += len(pcm16)
            else:
                self._rejected += 1
            return result

    def complete_turn(
        self, intent: SpeechIntent, *, epoch: str, now_s: float,
        host_verified: bool = False,
        independent_audible_pcm: bool = False,
        native_output_flushed: bool = False,
    ) -> PCMBridgeAdvice:
        """Settle a normal spoken turn only after independent native evidence.

        The device host must have observed nonzero TTS PCM in the matching
        output epoch AND independently confirmed its final output is drained.
        This cannot prove any particular human heard the sound. The app queue
        check here must precede stop(): stop() itself can erase queued audio,
        so checking an emptied queue *after* stopping would be misleading.
        """
        if any(type(flag) is not bool for flag in (
            host_verified, independent_audible_pcm, native_output_flushed,
        )):
            raise ValueError("strict independent output receipt flags required")
        with self._lock:
            if (not self._enabled or self._stopping or self._faulted
                    or self._intent is not intent or self._epoch != epoch):
                return PCMBridgeAdvice("held", "wrong_or_inactive_spoken_epoch")
            if (not host_verified or not independent_audible_pcm
                    or not native_output_flushed or self._turn_pcm_bytes == 0):
                return PCMBridgeAdvice("held", "independent_audible_quiet_receipts_missing")
            # Do not let stop() make still-queued audio appear to have played.
            pending = self._sink.buffered_ms()
            if pending is None or pending > 0:
                return PCMBridgeAdvice("held", "app_pcm_not_naturally_drained")
            if not self._gate.reviewed_for_host(intent):
                return PCMBridgeAdvice("held", "reviewed_dialogue_revoked")
            # Once stop begins, failures must not allow a new speech plan.
            self._enabled = False
            self._stopping = True
            try:
                stopped = self._sink.request_stop(epoch)
            except Exception:
                stopped = False
            if not stopped:
                self._faulted = True
                self._gate.disable()
                return PCMBridgeAdvice("fault", "native_complete_stop_failed")
            quiet = self._sink.observe_quiet(
                epoch, native_output_flushed=native_output_flushed,
            )
            if quiet.status != "quiet":
                self._faulted = True
                self._gate.disable()
                return PCMBridgeAdvice("fault", "native_complete_quiet_not_confirmed")
            try:
                settled = self._gate.settle(
                    intent, now_s=now_s, audible_confirmed=True,
                )
            except (ValueError, RuntimeError):
                settled = False
            if not settled:
                self._faulted = True
                self._gate.disable()
                return PCMBridgeAdvice("fault", "spoken_completion_commit_failed")
            self._intent = None
            self._epoch = None
            self._turn_pcm_bytes = 0
            self._stopping = False
            self._enabled = True
            self._spoken_completions += 1
            return PCMBridgeAdvice("quiet", "host_witnessed_audible_turn_completed")

    def disable(self) -> PCMBridgeAdvice:
        """Invalidate dialogue BEFORE requesting native STOP. Never auto-rearm."""
        with self._lock:
            self._enabled = False
            if self._stopping:
                return PCMBridgeAdvice("held", "native_stop_already_outstanding")
            self._stopping = self._intent is not None
            # Prevent future review even if native stop raises or fails.
            self._gate.disable()
            if self._intent is None:
                return PCMBridgeAdvice("disabled", "no_active_native_playout")
            assert self._epoch is not None
            try:
                stopped = self._sink.request_stop(self._epoch)
            except Exception:
                stopped = False
            if not stopped:
                self._faulted = True
                return PCMBridgeAdvice("fault", "native_stop_failed_manual_recovery")
            return PCMBridgeAdvice("stop_requested", "native_quiet_still_unverified")

    def attest_quiet(
        self, intent: SpeechIntent, *, epoch: str, now_s: float,
        host_verified: bool = False, native_output_flushed: bool = False,
    ) -> PCMBridgeAdvice:
        """Join native quiet evidence to quarantine release, exactly once.

        Only the trusted local host may supply genuine independent OS/device
        output evidence. The sink checks its own application buffer as well;
        neither source alone is conclusive. No hidden auto-retry on failure.
        """
        if type(host_verified) is not bool or type(native_output_flushed) is not bool:
            raise ValueError("strict host/physical evidence booleans required")
        with self._lock:
            if (not self._stopping or self._faulted or self._intent is not intent
                    or self._epoch != epoch or self._enabled):
                return PCMBridgeAdvice("held", "wrong_or_unstopped_audio_epoch")
            # A failed probe must preserve quarantine so that an old tail
            # cannot bleed into a new utterance on planner restart.
            outcome = self._sink.observe_quiet(
                epoch, native_output_flushed=native_output_flushed and host_verified,
            )
            if outcome.status != "quiet":
                if outcome.status == "fault":
                    self._faulted = True
                return PCMBridgeAdvice("held", "native_quiet_not_confirmed")
            try:
                acknowledged = self._gate.acknowledge_host_drain(
                    intent, now_s=now_s, host_verified=host_verified,
                    audio_drained=native_output_flushed,
                )
            except (ValueError, RuntimeError):
                acknowledged = False
            if not acknowledged:
                # A native reset was observed, but the planner was not
                # positively cleared: refuse restart until manual review.
                self._faulted = True
                return PCMBridgeAdvice("fault", "dialogue_quarantine_ack_failed")
            self._intent = None
            self._epoch = None
            self._turn_pcm_bytes = 0
            self._stopping = False
            self._stopped += 1
            return PCMBridgeAdvice("quiet", "native_epoch_drained_and_planner_released")

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "native_epoch_active": self._intent is not None,
                "stop_outstanding": self._stopping,
                "faulted": self._faulted,
                "stops_verified": self._stopped,
                "spoken_completions": self._spoken_completions,
                "pcm_rejected": self._rejected,
                "utterance_budget_stops": self._budget_stops,
                "max_turn_pcm_ms": self._max_turn_pcm_ms,
                "turn_pcm_ms_submitted": (
                    self._turn_pcm_bytes * 500 // self._sink.sample_rate
                ),
            }


__all__ = ["PCMBridgeAdvice", "StreamPreplayPCMBridge"]
