"""Trusted *played-sample* adapter for Star's audio-synchronized VTuber rig.

Only the owner-controlled sound output backend may call report_played().
Its counter MUST count samples actually played by the output device, not
queued/submitted/decoded samples or a TTS estimate. This adapter deliberately
does not open any device, read a microphone, broadcast or generate speech.

StarPlayoutClock remains the final authority for timing and render leases.
A driver/backend capable of reporting consumed output frames must be wired
separately; simply passing generated PCM length is NOT a valid integration.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .stream_motion import MotionFrame, neutral_frame
from .stream_playout_clock import PlayoutRigFrame, StarPlayoutClock
from .stream_stage import StagePlan


@dataclass(frozen=True, eq=False)
class DevicePlayoutEpoch:
    """Identity-only host ticket; not a cryptographic authentication token."""

    sequence: int
    generation: int
    sample_rate_hz: int
    total_samples: int


class DeviceAudibleSampleHost:
    """Fail-closed bridge from real output-device sample counts to avatar frames.

    This class is designed for a Windows WASAPI/PortAudio-style *host* adapter,
    not as a tool that can be called by a language model or viewers.

    The trusted device owner must:
      1. stop/flush a previous utterance before switching epochs,
      2. acknowledge that audio has actually reached the output path,
      3. report consumed (not buffered) frames with monotonic timestamps,
      4. call current() just before transmitting rig parameters, and
      5. send neutral_frame() on pause, failure, interruption or stop.

    In particular, acknowledgement and sample counts are host attestations;
    this class cannot prove physical audio playback without the device backend.
    """

    def __init__(self, playout: StarPlayoutClock) -> None:
        if not isinstance(playout, StarPlayoutClock):
            raise TypeError("expected StarPlayoutClock")
        self._playout = playout
        self._lock = RLock()
        self._enabled = False
        self._generation = 0
        self._active: DevicePlayoutEpoch | None = None
        self._plan: StagePlan | None = None
        self._last_samples: int | None = None
        self._counts = {
            "bound": 0, "observed": 0, "rejected": 0,
            "stale_epochs": 0, "rendered": 0, "stops": 0,
            "finished": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit owner approval is required")
        with self._lock:
            if self._active is not None:
                raise RuntimeError("cannot re-enable active audio")
            self._enabled = True

    def bind(
        self, plan: StagePlan, *, sample_rate_hz: int, total_samples: int,
    ) -> DevicePlayoutEpoch | None:
        """Bind one already-audible, already-armed StarStage speech turn.

        The audio buffer's sample count must match StarPlayoutClock's planned
        duration within 20 ms (or two samples), avoiding an unrelated PCM
        buffer being attached to another stage turn.
        """
        if not isinstance(plan, StagePlan):
            raise TypeError("expected StagePlan")
        if (type(sample_rate_hz) is not int or
                not 8000 <= sample_rate_hz <= 192000):
            raise ValueError("unsupported PCM sample rate")
        if type(total_samples) is not int or not 0 < total_samples <= 2880000:
            raise ValueError("invalid bounded PCM sample count")
        duration_s = total_samples / sample_rate_hz
        if not 0 < duration_s <= 15.0:
            raise ValueError("PCM duration must be at most 15 seconds")
        with self._lock:
            if not self._enabled or self._active is not None:
                return None
            track_s = self._playout.duration_if_armed(plan)
            if track_s is None:
                return None
            if abs(track_s - duration_s) > max(0.020, 2 / sample_rate_hz):
                raise ValueError("PCM duration does not match armed animation")
            self._generation += 1
            ticket = DevicePlayoutEpoch(
                plan.sequence, self._generation, sample_rate_hz, total_samples,
            )
            self._active = ticket
            self._plan = plan
            self._last_samples = None
            self._counts["bound"] += 1
            return ticket

    def _invalidate(self) -> None:
        """Revoke only this bridge's active epoch, including queued rig poses."""
        self._active = None
        self._plan = None
        self._last_samples = None
        self._playout.reset()

    def report_played(
        self, epoch: DevicePlayoutEpoch, *,
        played_samples: int, sampled_at: float, playing: bool = True,
    ) -> bool:
        """Receive a trusted output-device *consumed* frame count.

        sampled_at uses the same host monotonic seconds clock as StarPlayoutClock.
        The backend must explicitly mark a paused/stopped stream as not playing.
        Invalid observations revoke this epoch rather than inventing playback.
        Delayed callbacks from older epochs cannot cancel newer speech turns.
        """
        with self._lock:
            if not self._enabled or epoch is not self._active:
                self._counts["stale_epochs"] += 1
                return False
            assert self._plan is not None
            if (type(played_samples) is not int or
                    not 0 <= played_samples <= epoch.total_samples or
                    type(playing) is not bool or
                    (self._last_samples is not None and
                     played_samples < self._last_samples)):
                self._counts["rejected"] += 1
                self._invalidate()
                return False
            # Zero consumed samples is not permission to animate early speech;
            # exhausted PCM frames are never treated as actively audible.
            device_playing = playing and 0 < played_samples < epoch.total_samples
            accepted = self._playout.observe_playhead(
                self._plan,
                position_s=played_samples / epoch.sample_rate_hz,
                sampled_at=sampled_at, playing=device_playing,
            )
            if not accepted:
                self._counts["rejected"] += 1
                self._invalidate()
                return False
            if (played_samples == epoch.total_samples
                    and self._last_samples != epoch.total_samples):
                self._counts["finished"] += 1
            self._last_samples = played_samples
            self._counts["observed"] += 1
            return True

    def sample(self, epoch: DevicePlayoutEpoch) -> PlayoutRigFrame | None:
        """Get an advisory frame, only after audible sample advancement."""
        with self._lock:
            if not self._enabled or epoch is not self._active:
                return None
            assert self._plan is not None
            frame = self._playout.sample(self._plan)
            if frame is not None:
                self._counts["rendered"] += 1
            return frame

    def current(self, epoch: DevicePlayoutEpoch, frame: PlayoutRigFrame) -> bool:
        """Final render-boundary recheck; no asynchronous rig write happens here."""
        with self._lock:
            return (
                self._enabled and epoch is self._active
                and self._playout.current(frame)
            )

    def stop(
        self, epoch: DevicePlayoutEpoch, *, output_stopped_and_flushed: bool,
    ) -> MotionFrame | None:
        """Forget an epoch only after the host stopped and flushed its device."""
        if output_stopped_and_flushed is not True:
            raise RuntimeError("stop/flush the physical audio queue first")
        with self._lock:
            if epoch is not self._active:
                return None
            self._counts["stops"] += 1
            self._invalidate()
            return neutral_frame()

    def disable(self, *, output_stopped_and_flushed: bool = False) -> MotionFrame:
        """Disable intake and motion; never pretend to stop a real audio device."""
        with self._lock:
            if self._active is not None and output_stopped_and_flushed is not True:
                raise RuntimeError("stop/flush the physical audio queue first")
            self._enabled = False
            self._generation += 1
            self._invalidate()
            self._playout.disable()
            return neutral_frame()

    def metrics(self) -> dict[str, int | bool]:
        """Bounded aggregate diagnostics with no chat/audio/identity content."""
        with self._lock:
            return {
                **self._counts, "enabled": self._enabled,
                "active": self._active is not None,
            }


__all__ = ["DeviceAudibleSampleHost", "DevicePlayoutEpoch"]
