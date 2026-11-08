"""Offline, playback-locked VTube Studio parameter bridge for Star's original Live2D rig.

Converts *already audible*, host-clocked StagePlan motion into the documented
VTube Studio parameter API. No websocket, microphone, TTS, network, OBS or
authentication is implemented here. A trusted local host must authenticate its
own VTube Studio plugin session, create/map parameters, serialize approved
packets, recheck StarStage.current(plan) immediately before transmitting, and
own cancellation/queue flushing.

The model and chat MUST NOT choose parameter IDs or impersonate playback
acknowledgements. This is a bounded adapter, not verified speech synchronization.
"""

from __future__ import annotations

from typing import cast

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Any

from .stream_motion import MotionFrame, neutral_frame
from .stream_stage import StagePlan, StarStage

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_FIELD_LIMITS = (
    ("mouth_open", "StarMouthOpen", 0.0, 1.0, 0.0),
    ("eye_open_left", "StarEyeOpenLeft", 0.0, 1.0, 1.0),
    ("eye_open_right", "StarEyeOpenRight", 0.0, 1.0, 1.0),
    ("smile", "StarSmile", 0.0, 1.0, 0.0),
    ("brow_raise", "StarBrowRaise", 0.0, 1.0, 0.0),
    ("head_x", "StarHeadX", -1.0, 1.0, 0.0),
    ("head_y", "StarHeadY", -1.0, 1.0, 0.0),
    ("body_lean", "StarBodyLean", -1.0, 1.0, 0.0),
    ("shoulder_lift", "StarShoulderLift", 0.0, 1.0, 0.0),
    ("gaze_x", "StarGazeX", -1.0, 1.0, 0.0),
    ("ear_left", "StarEarLeft", -1.0, 1.0, 0.0),
    ("ear_right", "StarEarRight", -1.0, 1.0, 0.0),
    ("tail_sway", "StarTailSway", -1.0, 1.0, 0.0),
    ("hair_sway", "StarHairSway", -1.0, 1.0, 0.0),
)


def _number(value: object, name: str, low: float, high: float) -> float:
    if type(value) not in (float, int):
        raise ValueError(f"{name} must be a finite number")
    try:
        value = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} outside {low}..{high}")
    return value


def _epoch(value: object) -> str:
    if type(value) is not str or not _EPOCH.fullmatch(value):
        raise ValueError("playback epoch must be a bounded opaque identifier")
    return value


def _request(message_type: str, request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiName": "VTubeStudioPublicAPI",
        "apiVersion": "1.0",
        "requestID": request_id,
        "messageType": message_type,
        "data": data,
    }


@dataclass(frozen=True)
class BridgeStatus:
    active: bool
    accepted_frames: int
    rejected_frames: int
    neutral_resets: int
    active_sequence: int | None


class VTubeLive2DBridge:
    """Opt-in StagePlan-to-VTube Studio API adapter without external side effects.

    Inputs must come from a trusted host, never from the language model. The host
    provides the actual sound device cursor, monotonic sample time, and playback
    epoch. A host transport MUST discard queued frames on interruption, honor
    its own authentication, and recheck stage.current() at actual send time.
    """

    def __init__(self, stage: StarStage, *, owner_approved: bool = False, min_frame_interval_ms: float = 33.0) -> None:
        if not isinstance(stage, StarStage):
            raise TypeError("expected StarStage")
        if owner_approved is not True:
            raise PermissionError("authorized owner must opt in to avatar control")
        self._interval_ms = _number(min_frame_interval_ms, "frame interval ms", 16.0, 200.0)
        self._stage = stage
        self._lock = RLock()
        self._plan: StagePlan | None = None
        self._epoch: str | None = None
        self._generation = 0
        self._counter = 0
        self._last_bound_sequence = 0
        self._last_frame_s = -1.0
        self._last_cursor_s = -1.0
        self._last_clock_ms = -1.0
        self._last_sent_ms = -1.0
        self._accepted = 0
        self._rejected = 0
        self._neutral = 0
        self._silenced = False

    def registration_requests(self) -> tuple[dict[str, Any], ...]:
        """Declare unique, mapped Live2D *custom* inputs for the local host.

        Does not connect to VTube Studio or change the rig; an authenticated
        host must create these parameters and map them in the VTS model UI.
        """
        return tuple(
            _request(
                "ParameterCreationRequest",
                f"StarRegister{index}",
                {
                    "parameterName": name,
                    "explanation": f"Star original Live2D rig {field} control",
                    "min": low,
                    "max": high,
                    "defaultValue": default,
                },
            )
            for index, (field, name, low, high, default) in enumerate(_FIELD_LIMITS, 1)
        )

    def bind(self, plan: StagePlan, *, playback_epoch: str) -> bool:
        """Start exactly one *host-confirmed audible* playback epoch."""
        epoch = _epoch(playback_epoch)
        with self._lock:
            if (
                self._plan is not None
                or not isinstance(plan, StagePlan)
                or plan.sequence <= self._last_bound_sequence
                or not self._stage.current(plan)
            ):
                return False
            self._generation += 1
            self._counter = 0
            self._last_bound_sequence = plan.sequence
            self._plan = plan
            self._epoch = epoch
            self._last_frame_s = -1.0
            self._last_cursor_s = -1.0
            self._last_clock_ms = -1.0
            self._last_sent_ms = -1.0
            self._silenced = False
            return True

    @staticmethod
    def _values(frame: MotionFrame) -> list[dict[str, Any]]:
        if not isinstance(frame, MotionFrame):
            raise TypeError("expected MotionFrame")
        _number(frame.at_s, "frame at_s", 0, 15)
        return [
            {
                "id": name,
                "value": _number(getattr(frame, field), field, low, high),
                "weight": 1.0,
            }
            for field, name, low, high, _ in _FIELD_LIMITS
        ]

    def frame_packet(
        self, plan: StagePlan, *, playback_epoch: str, frame: MotionFrame, audible_cursor_s: float, sampled_ms: float
    ) -> dict[str, Any] | None:
        """Emit a packet only for fresh, monotonically played audio.

        The host's audio cursor must have *reached* the frame timestamp. Drop
        frames lagging >100ms, sampling faster than the configured rate, or
        entering an old/invalid playback epoch. No buffered future animation.
        """
        epoch = _epoch(playback_epoch)
        cursor = _number(audible_cursor_s, "audible cursor", 0, 15)
        clock = _number(sampled_ms, "sampled ms", 0, 1e13)
        values = self._values(frame)
        with self._lock:
            if (
                self._plan is not plan
                or self._epoch != epoch
                or not self._stage.current(plan)
                or cursor < self._last_cursor_s
                or clock < self._last_clock_ms
                or frame.at_s <= self._last_frame_s
                or frame.at_s > cursor + 1e-9
                or cursor - frame.at_s > 0.100
                or (self._last_sent_ms >= 0 and clock - self._last_sent_ms < self._interval_ms)
            ):
                self._rejected += 1
                return None
            self._counter += 1
            self._last_frame_s = frame.at_s
            self._last_cursor_s = cursor
            self._last_clock_ms = clock
            self._last_sent_ms = clock
            self._accepted += 1
            self._silenced = False
            return _request(
                "InjectParameterDataRequest",
                f"StarMotion{self._generation}-{self._counter}",
                {"mode": "set", "parameterValues": values},
            )

    def hold_silence(
        self, plan: StagePlan, *, playback_epoch: str,
        sampled_ms: float, host_reports_no_fresh_playback: bool = False,
    ) -> dict[str, Any] | None:
        """Neutralize a paused/stalled mouth without ending the speech epoch.

        The trusted audio host must have stopped receiving fresh consumed-frame
        evidence. This is one *neutral* override, not an invented audio cursor,
        permission to speak, or a reset that prevents an eventual resume.
        """
        if host_reports_no_fresh_playback is not True:
            raise PermissionError("only the trusted audio host can request silence")
        epoch = _epoch(playback_epoch)
        clock = _number(sampled_ms, "sampled ms", 0, 1e13)
        with self._lock:
            if (self._plan is not plan or self._epoch != epoch
                    or not self._stage.current(plan)
                    or clock < self._last_clock_ms or self._silenced):
                return None
            self._silenced = True
            self._last_clock_ms = clock
            self._last_sent_ms = clock
            self._counter += 1
            return _request(
                "InjectParameterDataRequest",
                f"StarSilence{self._generation}-{self._counter}",
                {"mode": "set", "parameterValues": self._values(neutral_frame())},
            )

    def reset(self, plan: StagePlan, *, playback_epoch: str, playback_stopped: bool = False) -> dict[str, Any] | None:
        """Prepare one neutral packet *after* the host has stopped real audio.

        Never reset an unrelated new turn: both plan object and epoch must
        match. The host must flush stale outbound frames before sending this
        packet and should not send old packets after it.
        """
        epoch = _epoch(playback_epoch)
        if playback_stopped is not True:
            raise PermissionError("host must confirm playback stopped")
        with self._lock:
            if self._plan is not plan or self._epoch != epoch:
                return None
            self._counter += 1
            payload = _request(
                "InjectParameterDataRequest",
                f"StarNeutral{self._generation}-{self._counter}",
                {
                    "mode": "set",
                    "parameterValues": self._values(neutral_frame()),
                },
            )
            self._plan = None
            self._epoch = None
            self._neutral += 1
            return payload

    def status(self) -> BridgeStatus:
        with self._lock:
            return BridgeStatus(
                active=self._plan is not None,
                accepted_frames=self._accepted,
                rejected_frames=self._rejected,
                neutral_resets=self._neutral,
                active_sequence=self._plan.sequence if self._plan else None,
            )


__all__ = ["BridgeStatus", "VTubeLive2DBridge"]
