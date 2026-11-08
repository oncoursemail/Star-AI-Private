"""Owner-host-only handoff from reviewed VTuber dialogue to epoch-scoped PCM.

This joins two existing otherwise independent safety fences: StreamPreplayGate
and LocalEpochPCMSink. A trusted native host must exclusively own both objects,
run methods off the audio callback thread, and provide *independent* native
quiet evidence. App-queue emptiness and caller booleans are NOT proof of actual
hardware silence. This module does not create devices, play by itself, start
OBS, access microphones/game input, or establish audible listener receipt.

The bridge is opt-in and deliberately narrow: it handles reviewed playout and
STOP+FLUSH on shutdown. Normal audible completion needs a separate trusted
native-output acknowledgement path; do not call gate.settle() early to bypass
this bridge. Failed stop stays quarantined until manual device recovery.
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

    def __init__(self, gate: StreamPreplayGate, sink: LocalEpochPCMSink) -> None:
        if type(gate) is not StreamPreplayGate or type(sink) is not LocalEpochPCMSink:
            raise TypeError("existing trusted preplay gate and PCM sink required")
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
            return PCMBridgeAdvice("ready", "reviewed_intent_and_unique_native_epoch")

    def submit(self, intent: SpeechIntent, *, epoch: str, pcm16: bytes) -> bool:
        """Forward bounded PCM into the host-owned, pre-started sink only.

        A successful submission is QUEUED audio, not proof it played or was
        heard. The sink still checks PCM format, buffer and native epoch.
        """
        with self._lock:
            if (not self._enabled or self._stopping or self._faulted
                    or self._intent is not intent or self._epoch != epoch
                    or not self._gate.reviewed_for_host(intent)):
                self._rejected += 1
                return False
            result = self._sink.submit(epoch, "tts_pcm", pcm16)
            if not result:
                self._rejected += 1
            return result

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
                "pcm_rejected": self._rejected,
            }


__all__ = ["PCMBridgeAdvice", "StreamPreplayPCMBridge"]
