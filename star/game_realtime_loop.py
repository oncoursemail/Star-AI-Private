"""Two-phase, opt-in real-time game cognition bridge for Star.

The trusted game host owns the OBS evidence, frame capture, model execution,
focus check and input adapter. A fast model receives only an *advisory* lease:
an out-of-order model answer never becomes a live action just because it was
valid for an older screenshot. This module calls no model and sends no keys.

Sequence:
  owner starts -> host records reactive latency -> offer(scene) -> host runs
  its approved fast model -> finish(lease, same scene, model hint) ->
  host rechecks real focus/permission -> claim(issued permit) -> key-up ->
  host release(permit). The input adapter MUST use this exact issued permit.

A teacher/research task is deliberately absent from this live path.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import math
from threading import RLock
from typing import Sequence, cast

from .game_action_gate import (
    ActionPermit, GameActionGate, GameActionHint, GameFrame, GameScope,
)
from .game_deadline_router import GameDeadlineRouter
from .stream_budget import StreamTelemetry
from .stream_load_governor import StreamLoadGovernor


def _clock_ms(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host clock must be a finite millisecond number")
    try:
        now = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid host clock") from exc
    if not math.isfinite(now) or not 0 <= now <= 1e13:
        raise ValueError("invalid host clock")
    return now


def _stream_epoch(value: object) -> int | None:
    """Validate an optional *host-observed* OBS transition counter.

    This only validates shape; the trusted desktop host must derive it from
    lossless OBS output events, never from a model or untrusted game content.
    """
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= (2**63 - 1):
        raise ValueError("stream_epoch must be a nonnegative 63-bit integer")
    return value


@dataclass(frozen=True)
class GameThinkLease:
    """Host-only advice, not permission to launch a model or press a key."""

    route: str                 # reactive | skip
    reason: str
    frame_sequence: int | None = None
    expires_ms: float | None = None
    authorizes_model_launch: bool = False
    authorized_to_play: bool = False
    # Snapshot of host-attested OBS state when this particular worker was offered.
    stream_live_at_offer: bool | None = None
    # Optional strict, monotonic, host-attested OBS output transition epoch.
    stream_epoch_at_offer: int | None = None


class RealtimeGameLoop:
    """Bind measured quick inference to the *same* current verified game frame.

    Owns two independently permissioned, session-scoped advisory controllers.
    The caller supplies fresh, independently trusted host telemetry at each
    boundary. No viewer text, screen pixels or model output is recorded.
    """

    def __init__(
        self, *, router: GameDeadlineRouter | None = None,
        action_gate: GameActionGate | None = None,
        pre_dispatch_reserve_ms: int = 40,
    ) -> None:
        if type(pre_dispatch_reserve_ms) is not int or not (
            20 <= pre_dispatch_reserve_ms <= 100
        ):
            raise ValueError("reserve must be an integer 20..100 ms")
        if router is not None and not isinstance(router, GameDeadlineRouter):
            raise TypeError("router must be a GameDeadlineRouter")
        if action_gate is not None and not isinstance(action_gate, GameActionGate):
            raise TypeError("action_gate must be a GameActionGate")
        self._router = router if router is not None else GameDeadlineRouter()
        self._gate = action_gate if action_gate is not None else GameActionGate()
        if pre_dispatch_reserve_ms >= self._gate.frame_max_age_ms:
            raise ValueError("reserve must be shorter than scene lifetime")
        self._reserve = pre_dispatch_reserve_ms
        self._lock = RLock()
        self._scope: GameScope | None = None
        self._scope_key = ""
        self._lease: GameThinkLease | None = None
        self._lease_frame: GameFrame | None = None
        # A superseded or stopped advisory can still have a live worker.
        # Clearing its lease is NOT evidence that its process terminated.
        self._worker_stop_pending = False
        self._permit: ActionPermit | None = None
        self._last_frame_sequence = 0
        self._last_capture_ms: float | None = None
        self._last_host_ms: float | None = None
        self._last_stream_epoch: int | None = None
        self._permit_stream_epoch: int | None = None
        self._counts = dict(offered=0, skipped=0, superseded=0,
                            finished=0, rejected=0, claimed=0, released=0,
                            worker_stops_confirmed=0)

    def start(
        self, scope: GameScope, action_ids: Sequence[str], *,
        owner_approved: bool = False,
    ) -> None:
        """Enable one owner-approved game/episode and curated symbolic actions."""
        if owner_approved is not True:
            raise PermissionError("owner approval is required")
        if not isinstance(scope, GameScope):
            raise TypeError("scope must be GameScope")
        key = sha256(
            (scope.game_id + "\0" + scope.version_id + "\0" +
             scope.episode_id).encode("utf-8")
        ).hexdigest()
        with self._lock:
            if (self._scope is not None or self._permit is not None
                    or self._worker_stop_pending):
                raise RuntimeError("stop, attest worker termination, and release keys first")
            # Action gate refuses to start if a previous ticket still awaits
            # host-confirmed key-up, including after revoke().
            self._gate.start(scope, action_ids, owner_approved=True)
            try:
                self._router.enable(owner_approved=True, game_scope=key)
            except Exception:
                self._gate.revoke()
                raise
            self._scope = scope
            self._scope_key = key
            self._lease = None
            self._lease_frame = None
            self._last_frame_sequence = 0
            self._last_capture_ms = None
            self._last_host_ms = None
            self._last_stream_epoch = None
            self._permit_stream_epoch = None

    def stop(self) -> None:
        """Invalidate model work; pending host keys still require confirmation."""
        with self._lock:
            if self._lease is not None:
                self._worker_stop_pending = True
            self._lease = None
            self._lease_frame = None
            self._scope = None
            self._scope_key = ""
            self._router.disable()
            self._gate.revoke()

    def acknowledge_worker_stopped(self, *, host_confirmed_stopped: bool = False) -> bool:
        """Clear an invalidated worker only after independent termination proof.

        Never infer termination from dropping a stale model response or
        resetting a session. The trusted host owns the actual worker handle.
        """
        if type(host_confirmed_stopped) is not bool:
            raise ValueError("host stop confirmation must be a strict boolean")
        with self._lock:
            if (not self._worker_stop_pending or not host_confirmed_stopped
                    or self._lease is not None):
                return False
            self._worker_stop_pending = False
            self._counts["worker_stops_confirmed"] += 1
            return True

    def record_reactive_latency(
        self, *, sample_id: int, duration_ms: float, sample_host_ms: float,
        host_measured: bool = False, completed: bool = True,
        stream_live: bool = False,
    ) -> bool:
        """Pass independently measured *completion* timings, not model guesses."""
        with self._lock:
            if self._scope is None:
                return False
            return self._router.record_reactive_latency(
                game_scope=self._scope_key, sample_id=sample_id,
                duration_ms=duration_ms, sample_host_ms=sample_host_ms,
                host_measured=host_measured, completed=completed,
                stream_live=stream_live,
            )

    def record_input_ack_latency(
        self, *, sample_id: int, duration_ms: float, sample_host_ms: float,
        host_measured: bool = False, completed: bool = True,
        stream_live: bool = False,
    ) -> bool:
        """Offer trusted OS-input acknowledgement timing to the router.

        Called by a separately authorized host AFTER checking an actual OS
        input acknowledgement (or reporting its timeout). This method does
        not issue key input or validate whether the game reacted to a key.
        """
        with self._lock:
            if self._scope is None:
                return False
            return self._router.record_input_ack_latency(
                game_scope=self._scope_key, sample_id=sample_id,
                duration_ms=duration_ms, sample_host_ms=sample_host_ms,
                host_measured=host_measured, completed=completed,
                stream_live=stream_live,
            )

    def _skip(self, reason: str) -> GameThinkLease:
        self._counts["skipped"] += 1
        return GameThinkLease("skip", reason)

    def offer(
        self, frame: GameFrame, *, now_ms: float, host_verified: bool = False,
        telemetry: StreamTelemetry | None = None,
        stream_live: bool = False,
        stream_governor: StreamLoadGovernor | None = None,
        cpu_pressure: bool = False, gpu_pressure: bool = False,
        previous_worker_stopped: bool = False,
        stream_epoch: int | None = None,
    ) -> GameThinkLease:
        """Offer an identity-bound fast-model slot for the newest game frame.

        A later verified scene supersedes an in-flight recommendation. Another
        worker is considered only after the host confirms the previous worker
        has actually stopped; merely discarding a reply is NOT cancellation.
        """
        if not isinstance(frame, GameFrame):
            raise TypeError("frame must be GameFrame")
        now = _clock_ms(now_ms)
        stream_epoch = _stream_epoch(stream_epoch)
        if any(type(flag) is not bool for flag in (
            host_verified, stream_live, cpu_pressure, gpu_pressure,
            previous_worker_stopped,
        )):
            raise ValueError("host flags must be strict booleans")
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be StreamTelemetry")
        with self._lock:
            if self._scope is None or frame.scope != self._scope:
                return self._skip("disabled_or_wrong_game_session")
            if not host_verified:
                return self._skip("trusted_observation_missing")
            # Once OBS transition-event evidence is used in an episode, a
            # later caller cannot silently drop it or rewind its counter.
            if self._last_stream_epoch is not None:
                if stream_epoch is None:
                    return self._skip("stream_epoch_evidence_missing")
                if stream_epoch < self._last_stream_epoch:
                    return self._skip("stream_epoch_reversed")
            if self._last_host_ms is not None and now < self._last_host_ms:
                return self._skip("host_clock_reversed")
            if (frame.sequence <= self._last_frame_sequence
                or (self._last_capture_ms is not None
                    and frame.captured_ms <= self._last_capture_ms)):
                return self._skip("stale_or_replayed_scene")
            if frame.captured_ms > now + 15:
                return self._skip("future_scene_capture")
            self._last_host_ms = now
            self._last_frame_sequence = frame.sequence
            self._last_capture_ms = frame.captured_ms
            if self._lease is not None:
                self._counts["superseded"] += 1
                self._worker_stop_pending = True
            self._lease = None
            self._lease_frame = None
            # Persistent quarantine: a second or third frame must NOT admit
            # new inference simply because the first superseding frame
            # discarded the prior lease. Only the host can attest termination.
            if self._worker_stop_pending:
                if not previous_worker_stopped:
                    return self._skip("previous_inference_worker_not_stopped")
                self._worker_stop_pending = False
                self._counts["worker_stops_confirmed"] += 1
            if self._permit is not None:
                return self._skip("pending_host_key_release")
            if not frame.focus_confirmed or not frame.playable:
                return self._skip("game_unfocused_or_in_menu")
            if frame.perception_confidence < self._gate.min_confidence:
                return self._skip("uncertain_scene")
            if telemetry is None or not telemetry.game_active:
                return self._skip("game_telemetry_missing_or_inactive")
            if telemetry.game_fps < 30 or telemetry.speech_backlog_ms > 350:
                return self._skip("realtime_game_or_voice_pressure")
            if telemetry.live != stream_live:
                return self._skip("stream_state_conflict")
            expiry = frame.captured_ms + self._gate.frame_max_age_ms - self._reserve
            if now >= expiry:
                return self._skip("insufficient_time_before_scene_deadline")
            advice = self._router.advise(
                game_scope=self._scope_key, game_active=True,
                observation_age_ms=max(0.0, now - frame.captured_ms),
                now_host_ms=now,
                max_observation_age_ms=self._gate.frame_max_age_ms,
                host_verified=True, stream_live=stream_live,
                stream_governor=stream_governor,
                cpu_pressure=cpu_pressure, gpu_pressure=gpu_pressure,
            )
            if advice.route != "reactive":
                return self._skip(advice.reason)
            lease = GameThinkLease(
                "reactive", "host_may_consider_fast_inference",
                frame.sequence, expiry,
                stream_live_at_offer=stream_live,
                stream_epoch_at_offer=stream_epoch,
            )
            if stream_epoch is not None:
                self._last_stream_epoch = stream_epoch
            self._lease = lease
            self._lease_frame = frame
            self._counts["offered"] += 1
            return lease

    def finish(
        self, lease: GameThinkLease, frame: GameFrame,
        hint: GameActionHint, *, now_ms: float,
        host_verified: bool = False, telemetry: StreamTelemetry | None = None,
        stream_live: bool = False,
        stream_governor: StreamLoadGovernor | None = None,
        cpu_pressure: bool = False, gpu_pressure: bool = False,
        stream_epoch: int | None = None,
    ) -> ActionPermit:
        """Consume one lease and recheck deadline and stream before action gate.

        The input adapter must still claim_offered on the *same* issued permit
        after checking actual focus and owner authorization at the final edge.
        """
        if not isinstance(frame, GameFrame) or not isinstance(hint, GameActionHint):
            raise TypeError("expected GameFrame and GameActionHint")
        now = _clock_ms(now_ms)
        stream_epoch = _stream_epoch(stream_epoch)
        if any(type(flag) is not bool for flag in (
            host_verified, stream_live, cpu_pressure, gpu_pressure,
        )):
            raise ValueError("host flags must be strict booleans")
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be StreamTelemetry")
        with self._lock:
            def reject(reason: str) -> ActionPermit:
                self._counts["rejected"] += 1
                return ActionPermit(False, reason)

            if (self._scope is None or self._lease is None
                    or lease is not self._lease or frame is not self._lease_frame):
                return reject("unknown_superseded_or_consumed_lease")
            # A bad, timed-out or untrusted answer cannot be replayed later.
            self._lease = None
            self._lease_frame = None
            if not host_verified:
                # Losing trust in a purported completion is not proof that
                # the underlying inference process has actually exited.
                self._worker_stop_pending = True
                return reject("trusted_completion_missing")
            if self._last_host_ms is not None and now < self._last_host_ms:
                # A reversed host clock also makes completion unverifiable.
                # Keep the worker quarantined until host termination proof.
                self._worker_stop_pending = True
                return reject("host_clock_reversed")
            self._last_host_ms = now
            if lease.expires_ms is None or now >= lease.expires_ms:
                return reject("inference_finished_after_scene_deadline")
            # A worker admitted before OBS entered or exited broadcast mode
            # cannot become an action under different live resource/consent
            # conditions. The final host state alone is not the offered state.
            if stream_live is not lease.stream_live_at_offer:
                return reject("stream_state_changed_during_inference")
            # A boolean can miss OFF->ON->OFF during inference. The trusted
            # host must count *every* OBS output state transition and attest
            # the same epoch at offer and completion.
            if (lease.stream_epoch_at_offer is not None
                    or stream_epoch is not None):
                if lease.stream_epoch_at_offer is None or stream_epoch is None:
                    return reject("stream_epoch_evidence_missing")
                if (self._last_stream_epoch is not None
                        and stream_epoch < self._last_stream_epoch):
                    return reject("stream_epoch_reversed")
                self._last_stream_epoch = stream_epoch
                if stream_epoch != lease.stream_epoch_at_offer:
                    return reject("stream_epoch_changed_during_inference")
            if telemetry is None or not telemetry.game_active:
                return reject("game_telemetry_missing_or_inactive")
            if telemetry.live != stream_live:
                return reject("stream_state_conflict")
            # Critically, current OBS/CPU/GPU pressure is checked AFTER model
            # completion, not copied from the earlier inference admission.
            advice = self._router.advise(
                game_scope=self._scope_key, game_active=True,
                observation_age_ms=max(0.0, now - frame.captured_ms),
                now_host_ms=now,
                max_observation_age_ms=self._gate.frame_max_age_ms,
                host_verified=True, stream_live=stream_live,
                stream_governor=stream_governor,
                cpu_pressure=cpu_pressure, gpu_pressure=gpu_pressure,
                completed_inference=True,
            )
            if advice.route != "completed":
                return reject(advice.reason)
            permit = self._gate.request(
                frame, hint, now_ms=now, host_verified=True,
                telemetry=telemetry,
            )
            if not permit.offered:
                return reject(permit.reason)
            self._permit = permit
            self._permit_stream_epoch = stream_epoch
            self._counts["finished"] += 1
            return permit

    def claim(
        self, permit: ActionPermit, *, now_ms: float,
        host_focus_and_permission: bool = False,
        stream_epoch: int | None = None,
    ) -> bool:
        """Final host-only, identity-bound one-shot claim; no input dispatched."""
        now = _clock_ms(now_ms)
        stream_epoch = _stream_epoch(stream_epoch)
        if type(host_focus_and_permission) is not bool:
            raise ValueError("host_focus_and_permission must be boolean")
        with self._lock:
            if permit is not self._permit or self._permit is None:
                return False
            if (self._permit_stream_epoch is not None
                    or stream_epoch is not None):
                if stream_epoch != self._permit_stream_epoch:
                    # Revoke, not merely defer: restoring the old counter
                    # must never make this previously stale ticket claimable.
                    self._gate.revoke()
                    return False
            accepted = self._gate.claim_offered(
                permit, now_ms=now,
                host_focus_and_permission=host_focus_and_permission,
            )
            if accepted:
                self._counts["claimed"] += 1
            return accepted

    def release(
        self, permit: ActionPermit, *, now_ms: float,
        host_confirmed_released: bool = False,
    ) -> bool:
        """Only independent key-up confirmation can free the action slot."""
        now = _clock_ms(now_ms)
        if type(host_confirmed_released) is not bool:
            raise ValueError("host_confirmed_released must be boolean")
        with self._lock:
            if permit is not self._permit or self._permit is None:
                return False
            released = self._gate.release(
                permit.ticket, now_ms=now,
                host_confirmed_released=host_confirmed_released,
            ) if permit.ticket is not None else False
            if released:
                self._permit = None
                self._permit_stream_epoch = None
                self._counts["released"] += 1
            return released

    def metrics(self) -> dict[str, int | bool]:
        """No scene ID, event content, input bindings or viewer data in output."""
        with self._lock:
            return {**self._counts, "enabled": self._scope is not None,
                    "inflight": self._lease is not None,
                    "worker_stop_pending": self._worker_stop_pending,
                    "awaiting_release": self._permit is not None}
