"""Fail-conservative host boundary for STAR's realtime gaming intelligence.

Connect existing real telemetry -> inference admission -> StarStage turn plans.
Unlike a generated prompt, an inference request cannot provide its own GPU,
game FPS, audio-backlog, or CPU measurements. Unknown device measurements fail
closed. The host, not this coordinator or an AI model, owns device callbacks,
worker execution, sound playback, authorization and physical stop.

This is a *control plane*: admissions reserve capacity, but do not run models,
read chat, move a character, start OBS, touch the microphone, or play sound.
Only a trusted local host may invoke these methods and attest worker termination
and audible output. Never expose the governor's callbacks as LLM tools.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
import time
from typing import Callable

from .stream_director import StreamSignal
from .stream_episode import EpisodePacket
from .stream_knowledge import KnowledgePacket
from .stream_hardware_telemetry import LiveHostSample, RealtimeTelemetryHost
from .stream_qos import AdaptiveQoS, InferenceJob, QoSDecision
from .stream_stage import StagePlan, StarStage
from .stream_turntaking import TurnAdvice
from .stream_timeline_context import TimelineContextPacket
from .stream_multiparty_floor import (
    FloorDecision, FloorObservation, StreamMultipartyFloorGate,
)


def _now(clock: Callable[[], float]) -> float:
    try:
        value = clock()
        if type(value) not in (int, float):
            raise ValueError("invalid host clock")
        number = float(value)
        if not math.isfinite(number) or not 0 <= number <= 1e13:
            raise ValueError("invalid host clock")
        return number
    except Exception as exc:
        raise ValueError("trusted host monotonic clock unavailable") from exc


@dataclass(frozen=True)
class BrainLease:
    """Opaque in-session ticket; no job text or model-constructible capability."""
    generation: int
    ticket: int
    device: str
    kind: str
    expires_ms: float


@dataclass(frozen=True)
class BrainAdmission:
    admitted: bool
    reason: str
    lease: BrainLease | None = None
    predicted_p95_ms: float | None = None


class StreamBrainGovernor:
    """Owner-authorized bridge between existing telemetry, QoS and StarStage.

    The host must collect actual game frame presents, NVIDIA/OS usage and real
    speaker queue depth before planning speech or admitting model work.
    Stale/missing samples cannot be made fresh by stamping the current time.

    disable() does NOT pretend to stop a worker or speaker. Active worker
    reservations survive until the local host calls acknowledge_worker_stopped.
    Queued/audible audio requires a confirmed physical stop/flush first.
    A scene switch must stop all workers and audio before a new session.
    """

    def __init__(
        self, *,
        telemetry: RealtimeTelemetryHost,
        qos: AdaptiveQoS,
        stage: StarStage,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        multiparty_floor: StreamMultipartyFloorGate | None = None,
    ) -> None:
        if not isinstance(telemetry, RealtimeTelemetryHost):
            raise TypeError("telemetry must be a RealtimeTelemetryHost")
        if not isinstance(qos, AdaptiveQoS) or not isinstance(stage, StarStage):
            raise TypeError("expected existing AdaptiveQoS and StarStage")
        if not callable(clock_ms):
            raise TypeError("host clock must be callable")
        if multiparty_floor is not None and not isinstance(multiparty_floor, StreamMultipartyFloorGate):
            raise TypeError("multiparty_floor must be StreamMultipartyFloorGate or None")
        self._telemetry, self._qos, self._stage = telemetry, qos, stage
        self._clock = clock_ms
        self._multiparty_floor = multiparty_floor
        self._lock = RLock()
        self._enabled = False
        self._generation = 0
        self._leases: dict[int, BrainLease] = {}
        self._speech_binding: tuple[StagePlan, BrainLease] | None = None
        self._last_floor_decision: FloorDecision | None = None
        self._counts = {
            "admitted": 0, "deferred": 0, "stopped": 0,
            "successful": 0, "stale_lease": 0, "missing_sensor": 0,
            "speech_prepared": 0, "audio_abandoned": 0,
            "audio_interrupted": 0, "floor_admitted": 0,
            "floor_suppressed": 0, "floor_rejected": 0, "floor_missing": 0,
        }

    def enable(
        self, *, owner_approved: bool = False,
        live: bool, game_active: bool,
        mode: str = "normal", reduced_motion: bool = False,
    ) -> None:
        """Opt into one measured local session, never an actual broadcast."""
        if owner_approved is not True:
            raise PermissionError("authenticated owner must enable the stream brain")
        if type(live) is not bool or type(game_active) is not bool:
            raise ValueError("session flags must be booleans")
        with self._lock:
            if self._enabled or self._leases or self._speech_binding is not None:
                raise RuntimeError("stop the previous session, audio and workers first")
            if self._qos.status()["inflight"] or self._stage.metrics()["phase"] != "idle":
                raise RuntimeError("existing model or audio reservations are active")
            _now(self._clock)
            self._stage.enable(
                owner_approved=True, mode=mode, reduced_motion=reduced_motion
            )
            floor_started = False
            try:
                self._qos.enable(owner_approved=True)
                self._telemetry.set_context(
                    live=live, game_active=game_active, owner_approved=True
                )
                if self._multiparty_floor is not None:
                    self._multiparty_floor.enable(owner_approved=True)
                    floor_started = True
            except Exception:
                if floor_started and self._multiparty_floor is not None:
                    self._multiparty_floor.disable()
                self._qos.disable()
                self._telemetry.disable()
                self._stage.disable()
                raise
            self._enabled = True
            self._generation += 1

    def disable(self, *, audio_stopped_and_flushed: bool = False) -> None:
        """Stop admissions. Hardware stop must be completed by the host first.

        An actual speaker needs an epoch-specific device stop/flush; a boolean
        here is a trusted-host attestation, never proof from generated text.
        Stopping admission while a worker is running leaves its VRAM reserved.
        """
        if type(audio_stopped_and_flushed) is not bool:
            raise TypeError("physical audio stop acknowledgement must be a boolean")
        with self._lock:
            phase = self._stage.metrics()["phase"]
            if (phase in {"queued", "audible"} or self._speech_binding is not None) and not audio_stopped_and_flushed:
                raise RuntimeError("physical sound device and rig queue not stopped")
            if self._enabled:
                self._enabled = False
                self._generation += 1
                self._qos.disable()  # quarantine workers; do not release memory
                if self._multiparty_floor is not None:
                    self._multiparty_floor.disable()
                self._telemetry.disable()
                self._stage.disable()
                self._speech_binding = None
                self._last_floor_decision = None

    def _sample(self) -> LiveHostSample | None:
        sample = self._telemetry.snapshot()
        if sample is None or sample.qos is None:
            self._counts["missing_sensor"] += 1
            return None
        # The public telemetry adapter is deliberately off the hot path and
        # reports its actual sample time. QoS enforces the tighter live limit.
        return sample

    def admit(self, job: InferenceJob) -> BrainAdmission:
        """Advisory one-shot reservation. Host executes only its allowed tools."""
        if not isinstance(job, InferenceJob):
            raise TypeError("expected an InferenceJob")
        with self._lock:
            if not self._enabled:
                self._counts["deferred"] += 1
                return BrainAdmission(False, "owner_opt_in_missing")
            now = _now(self._clock)
            sample = self._sample()
            if sample is None:
                self._counts["deferred"] += 1
                return BrainAdmission(False, "trusted_game_gpu_audio_cpu_sample_missing")
            assert sample.qos is not None
            decision: QoSDecision = self._qos.admit(
                job, sample.qos, now_ms=now
            )
            if not decision.admitted:
                self._counts["deferred"] += 1
                return BrainAdmission(False, decision.reason)
            assert decision.ticket is not None
            assert decision.device is not None
            assert decision.expires_ms is not None
            lease = BrainLease(
                self._generation, decision.ticket,
                decision.device, job.kind, decision.expires_ms,
            )
            self._leases[lease.ticket] = lease
            self._counts["admitted"] += 1
            return BrainAdmission(
                True, decision.reason, lease, decision.predicted_p95_ms
            )

    def acknowledge_worker_stopped(
        self, lease: BrainLease, *, worker_stopped: bool,
        succeeded: bool = False,
    ) -> bool:
        """Remove a reservation only after trusted host confirms termination.

        Stale/expired work must never train route timing, even if a model
        returns its result later. Merely requesting cancellation is not enough.
        """
        if not isinstance(lease, BrainLease):
            raise TypeError("expected issued BrainLease")
        if type(worker_stopped) is not bool or type(succeeded) is not bool:
            raise TypeError("explicit host termination and result booleans required")
        with self._lock:
            if self._leases.get(lease.ticket) is not lease:
                self._counts["stale_lease"] += 1
                return False
            if not worker_stopped:
                return False  # must retain RAM/VRAM quarantine
            now = _now(self._clock)
            # QoS owns deadlines, elapsed-time learning and disabled-worker
            # release semantics. Never mark old-session results successful.
            accepted = self._qos.finish(
                lease.ticket, now_ms=now,
                succeeded=(succeeded and self._enabled
                           and lease.generation == self._generation),
            )
            del self._leases[lease.ticket]
            self._counts["stopped"] += 1
            if accepted and succeeded:
                self._counts["successful"] += 1
            return bool(accepted and succeeded)

    def offer(
        self, signal: StreamSignal, *, moderated: bool = False,
        spoken_turn: bool = False,
        floor_observation: FloorObservation | None = None,
    ) -> bool:
        """Queue an event; spoken viewer turns may require addressee proof.

        The optional floor gate applies only to host-classified spoken viewer
        questions/comments. Ordinary chat, game events and the authenticated
        owner-interrupt path retain their existing routing. A floor receipt is
        content-free and must bind the exact signal ID and same monotonic clock.
        """
        if not isinstance(signal, StreamSignal):
            raise TypeError("expected StreamSignal")
        if type(moderated) is not bool or type(spoken_turn) is not bool:
            raise TypeError("moderated and spoken_turn must be booleans")
        if floor_observation is not None and type(floor_observation) is not FloorObservation:
            raise TypeError("floor_observation must be FloorObservation or None")
        if spoken_turn and signal.kind not in {"viewer_question", "viewer_comment"}:
            raise ValueError("multiparty floor gating is only for spoken viewer events")
        if not spoken_turn and floor_observation is not None:
            raise ValueError("floor_observation requires spoken_turn=True")
        with self._lock:
            self._last_floor_decision = None
            if not self._enabled:
                return False
            floor_authorized = False
            if spoken_turn:
                gate = self._multiparty_floor
                if gate is None or floor_observation is None:
                    self._counts["floor_missing"] += 1
                    return False
                if not moderated:
                    self._counts["floor_rejected"] += 1
                    return False
                if floor_observation.turn_id != signal.signal_id:
                    self._counts["floor_rejected"] += 1
                    return False
                skew = abs(signal.timestamp * 1000.0 - float(floor_observation.captured_ms))
                if skew > gate.policy.max_signal_skew_ms:
                    self._counts["floor_rejected"] += 1
                    return False
                if not gate.observe(floor_observation):
                    self._counts["floor_rejected"] += 1
                    return False
                decision = gate.decide(signal.signal_id, now_ms=_now(self._clock))
                self._last_floor_decision = decision
                if not decision.should_speak:
                    self._counts["floor_suppressed"] += 1
                    return False
                floor_authorized = True
            queued = self._stage.offer(
                signal, now=_now(self._clock) / 1000, moderated=moderated
            )
            if queued and floor_authorized:
                self._counts["floor_admitted"] += 1
            elif floor_authorized:
                # Do not expose a response authorization for an event the
                # existing stage rejected at its own admission boundary.
                self._last_floor_decision = None
            return queued

    def take_floor_decision(self, signal_id: str) -> FloorDecision | None:
        """Consume the most recent one-use floor result for the exact event.

        A trusted host can route a non-spoken `backchannel` result to the
        existing avatar/listener-cue path. This method does not play audio,
        move the rig, or make the decision reusable.
        """
        if type(signal_id) is not str:
            raise TypeError("signal_id must be a string")
        with self._lock:
            decision = self._last_floor_decision
            if decision is None or decision.turn_id != signal_id:
                return None
            if (not self._enabled or self._multiparty_floor is None
                    or decision.session_epoch != self._multiparty_floor.session_epoch):
                self._last_floor_decision = None
                return None
            self._last_floor_decision = None
            return decision

    def prepare(
        self, *, voice_speaking: bool = False,
        viewer_speaking: bool = False,
        gameplay_critical: bool = False,
        turn: TurnAdvice | None = None,
        knowledge: KnowledgePacket | None = None,
        episode: EpisodePacket | None = None,
        timeline_context: TimelineContextPacket | None = None,
    ) -> StagePlan | None:
        """Propose contextual speech only with fresh trusted hardware data.

        Source-approved knowledge and signed practice histories remain USER-
        priority evidence, never tools, instructions or performance claims.
        The stage itself restricts which event types can consume each packet.
        """
        if knowledge is not None and not isinstance(knowledge, KnowledgePacket):
            raise TypeError("expected reviewed KnowledgePacket")
        if episode is not None and not isinstance(episode, EpisodePacket):
            raise TypeError("expected verified EpisodePacket")
        if timeline_context is not None and not isinstance(timeline_context, TimelineContextPacket):
            raise TypeError("expected validated TimelineContextPacket")
        with self._lock:
            if not self._enabled:
                return None
            sample = self._sample()
            if sample is None:
                return None
            plan = self._stage.prepare(
                now=_now(self._clock) / 1000,
                telemetry=sample.telemetry,
                voice_speaking=voice_speaking,
                viewer_speaking=viewer_speaking,
                gameplay_critical=gameplay_critical,
                turn=turn, knowledge=knowledge, episode=episode,
                timeline_context=timeline_context,
            )
            if plan is not None:
                self._counts["speech_prepared"] += 1
            return plan

    def queue_audio(self, plan: StagePlan, *, speech_lease: BrainLease) -> bool:
        """Require a *real* QoS speech reservation before audio may be queued.

        The bound lease must be issued by this exact governor and session. A
        model-supplied numeric ticket, expired job, or GPU-only research lease
        cannot bypass measurement-based admission. The host separately owns
        TTS execution and local playback-device control.
        """
        if not isinstance(plan, StagePlan) or not isinstance(speech_lease, BrainLease):
            raise TypeError("expected StagePlan and issued BrainLease")
        with self._lock:
            if not self._enabled or self._speech_binding is not None:
                return False
            now = _now(self._clock)
            if (self._leases.get(speech_lease.ticket) is not speech_lease
                    or speech_lease.generation != self._generation
                    or speech_lease.kind != "speech"
                    or speech_lease.expires_ms <= now):
                return False
            if self._sample() is None:
                if self._stage.finish(
                    plan, now=now / 1000, played_to_end=False
                ):
                    self._counts["audio_abandoned"] += 1
                return False
            if not self._stage.queue_audio(plan, now=now / 1000):
                return False
            self._speech_binding = (plan, speech_lease)
            return True

    def acknowledge_audible(
        self, plan: StagePlan, *, sound_device_confirmed: bool = False
    ) -> bool:
        """Only the local playback host may attest the first audible frame."""
        if not isinstance(plan, StagePlan):
            raise TypeError("expected StagePlan")
        if sound_device_confirmed is not True:
            return False
        with self._lock:
            if (not self._enabled or self._speech_binding is None
                    or self._speech_binding[0] is not plan):
                return False
            return self._stage.acknowledge_audible(
                plan, now=_now(self._clock) / 1000
            )

    def finish_audio(
        self, plan: StagePlan, *, device_playback_finished: bool
    ) -> bool:
        """Forward physical playback completion, not synthesized-text success."""
        if not isinstance(plan, StagePlan):
            raise TypeError("expected StagePlan")
        if type(device_playback_finished) is not bool:
            raise TypeError("device acknowledgement must be a boolean")
        with self._lock:
            if (not self._enabled or self._speech_binding is None
                    or self._speech_binding[0] is not plan):
                return False
            finished = self._stage.finish(
                plan, now=_now(self._clock) / 1000,
                played_to_end=device_playback_finished
            )
            if finished:
                self._speech_binding = None
            return finished

    def reconcile_interrupted_audio(
        self, plan: StagePlan, *, sound_device_stopped: bool,
        animation_queue_flushed: bool,
    ) -> bool:
        """Release one speech binding only AFTER a trusted physical stop.

        StreamInterruptionHost may already have invalidated the stage on an
        owner barge-in. In that case finish_audio() cannot match the old plan;
        without reconciliation all later turns remain blocked. This host-only
        acknowledgement requires both epoch-scoped device stop and animation
        flush. Never expose it to a language model, a viewer or event text.

        Only the *same plan object* may be retired; a delayed callback from a
        previous sentence cannot cancel or clear a newer audio binding.
        The speech worker's QoS lease is independent and remains reserved
        until acknowledge_worker_stopped() confirms termination.
        """
        if not isinstance(plan, StagePlan):
            raise TypeError("expected StagePlan")
        if (type(sound_device_stopped) is not bool
                or type(animation_queue_flushed) is not bool):
            raise TypeError("physical host acknowledgements must be booleans")
        with self._lock:
            if self._speech_binding is None or self._speech_binding[0] is not plan:
                return False
            if not (sound_device_stopped and animation_queue_flushed):
                return False
            # Once the device is stopped, abandon an un-revoked plan. If a
            # different stage plan replaced it, finish() is a safe no-op.
            self._stage.finish(plan, now=_now(self._clock) / 1000,
                               played_to_end=False)
            self._speech_binding = None
            self._counts["audio_interrupted"] += 1
            return True

    def status(self) -> dict[str, object]:
        """Anonymous health counters only, never audience or prompt contents."""
        with self._lock:
            return {
                **self._counts, "enabled": self._enabled,
                "reserved_workers": len(self._leases),
                "pending_hardware_stop": (
                    len(self._leases) if not self._enabled else 0
                ),
                "pending_audio_stop": self._speech_binding is not None,
                "stage_phase": self._stage.metrics()["phase"],
                "qos_expired_reservations":
                    self._qos.status()["expired_awaiting_host_stop"],
                "multiparty_floor_enabled": (
                    self._multiparty_floor.status()["enabled"]
                    if self._multiparty_floor is not None else False
                ),
                "multiparty_floor_session_epoch": (
                    self._multiparty_floor.session_epoch
                    if self._multiparty_floor is not None and self._enabled else None
                ),
            }


__all__ = ["BrainLease", "BrainAdmission", "StreamBrainGovernor"]
