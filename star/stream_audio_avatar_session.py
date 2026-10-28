"""Owner-scoped end-to-end adapter: consumed PCM -> live VTube Studio parameters.

A Windows audio backend (not this module) must attest *actually consumed*
output samples; a separately authenticated loopback VTube Studio host must own
the websocket. Star's language model and viewer chat are not allowed to call
this coordinator. Calls must be serialized through this object, not directly
to the device or renderer while a session is active.

This is an integration boundary, not a proof of audible sound at the listener,
a TTS synthesizer, an OBS broadcaster, or a new gaming permission.
"""
from __future__ import annotations

from threading import RLock
import math
import time
from typing import Callable

from .stream_audio_sample_host import DeviceAudibleSampleHost, DevicePlayoutEpoch
from .stream_stage import StagePlan, StarStage
from .vtube_local_host import VTubeLocalHost, VTSHostError


class AudibleAvatarSession:
    """One trusted, bounded speech epoch; never queues animation or audio.

    The device backend must call report_played() and render() on the same
    authorized worker. On any renderer failure, this object stops sending
    expressions and closes VTS. The host must physically stop/flush PCM before
    end() and must never treat closing this socket as an audio stop.
    """

    def __init__(
        self, stage: StarStage, device: DeviceAudibleSampleHost,
        renderer: VTubeLocalHost, *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (not isinstance(stage, StarStage)
                or not isinstance(device, DeviceAudibleSampleHost)
                or not isinstance(renderer, VTubeLocalHost)
                or not callable(clock)):
            raise TypeError("expected existing Stage, device, renderer and trusted clock")
        # Constructor-time identity check; no substitute stages/foreign audio.
        if (device._playout._stage is not stage
                or renderer._bridge._stage is not stage):
            raise ValueError("all three adapters must share the exact StarStage")
        self._stage = stage
        self._device = device
        self._renderer = renderer
        self._clock = clock
        self._lock = RLock()
        self._enabled = False
        self._plan: StagePlan | None = None
        self._epoch: DevicePlayoutEpoch | None = None
        self._name: str | None = None
        self._faulted = False
        self._counts = {
            "bound": 0, "rendered": 0, "suppressed": 0,
            "silences": 0, "stops": 0, "faults": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for live avatar outputs")
        with self._lock:
            if self._epoch is not None:
                raise RuntimeError("stop the previous audio epoch first")
            self._enabled = True

    def bind(
        self, plan: StagePlan, epoch: DevicePlayoutEpoch, *,
        playback_epoch: str,
    ) -> bool:
        """Bind already armed, authenticated stage/audio/VTS to one utterance.

        The host must already have enabled and armed StarStage/StarPlayoutClock,
        bound DeviceAudibleSampleHost, and authenticated/registered VTS.
        Never arm this from a queued TTS buffer or a viewer command.
        """
        with self._lock:
            if (not self._enabled or self._epoch is not None
                    or not self._stage.current(plan)
                    or not self._device.active_for(epoch, plan)
                    or not self._renderer.ready):
                return False
            if not self._renderer._bridge.bind(plan, playback_epoch=playback_epoch):
                return False
            if not self._device.active_for(epoch, plan):
                self._renderer.close()
                return False
            self._plan = plan
            self._epoch = epoch
            self._name = playback_epoch
            self._faulted = False
            self._counts["bound"] += 1
            return True

    def _fault(self) -> None:
        """Close the renderer, NEVER assert that physical playback stopped."""
        if not self._faulted:
            self._counts["faults"] += 1
        self._faulted = True
        self._renderer.close()

    def _silence(self) -> None:
        """Immediate neutral hold for a paused or unobserved output cursor."""
        assert self._plan is not None and self._name is not None
        if not self._stage.current(self._plan):
            self._fault()
            return
        try:
            now = self._clock()
            if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
                raise ValueError("invalid host clock")
            if self._renderer.send_silence(
                self._plan, playback_epoch=self._name, sampled_ms=now * 1000,
                host_reports_no_fresh_playback=True,
            ):
                self._counts["silences"] += 1
        except (VTSHostError, ValueError, PermissionError):
            self._fault()

    def report_played(
        self, epoch: DevicePlayoutEpoch, *,
        played_samples: int, sampled_at: float, playing: bool = True,
    ) -> bool:
        """Trusted output backend reports consumed samples, never queued PCM."""
        with self._lock:
            if not self._enabled or self._faulted or epoch is not self._epoch:
                return False
            if not self._device.report_played(
                epoch, played_samples=played_samples,
                sampled_at=sampled_at, playing=playing,
            ):
                self._fault()
                return False
            if playing is not True or played_samples in (0, epoch.total_samples):
                self._silence()
            return not self._faulted

    def render(self, epoch: DevicePlayoutEpoch) -> bool:
        """At most one fresh audible frame, revalidated before VTS network I/O."""
        with self._lock:
            if not self._enabled or self._faulted or epoch is not self._epoch:
                return False
            assert self._plan is not None and self._name is not None
            if (not self._stage.current(self._plan)
                    or not self._device.active_for(epoch, self._plan)):
                self._fault()
                return False
            pose = self._device.sample(epoch)
            if pose is None or not self._device.current(epoch, pose):
                self._counts["suppressed"] += 1
                self._silence()
                return False
            try:
                sent = self._renderer.send_frame(
                    self._plan, playback_epoch=self._name,
                    frame=pose.motion, audible_cursor_s=pose.playhead_s,
                    sampled_ms=pose.sampled_at * 1000,
                )
            except (VTSHostError, ValueError):
                self._fault()
                return False
            if sent:
                self._counts["rendered"] += 1
            else:
                self._counts["suppressed"] += 1
            return sent

    def end(
        self, epoch: DevicePlayoutEpoch, *,
        output_stopped_and_flushed: bool = False,
    ) -> bool:
        """Only real PCM stop/flush lets the host send a final neutral pose."""
        if output_stopped_and_flushed is not True:
            raise RuntimeError("stop and flush physical PCM before ending the avatar turn")
        with self._lock:
            if epoch is not self._epoch:
                return False
            assert self._plan is not None and self._name is not None
            plan, name = self._plan, self._name
            self._device.stop(epoch, output_stopped_and_flushed=True)
            try:
                if self._renderer.connected and not self._faulted:
                    self._renderer.send_neutral(
                        plan, playback_epoch=name, playback_stopped=True,
                    )
            except (VTSHostError, ValueError, PermissionError):
                self._fault()
            finally:
                self._plan = None
                self._epoch = None
                self._name = None
                self._faulted = False
                self._counts["stops"] += 1
            return True

    def disable(self, *, output_stopped_and_flushed: bool = False) -> None:
        """Disabling never stops the user's audio device by itself."""
        with self._lock:
            if self._epoch is not None:
                if output_stopped_and_flushed is not True:
                    raise RuntimeError("device must be stopped and flushed first")
                self.end(self._epoch, output_stopped_and_flushed=True)
            self._enabled = False

    def metrics(self) -> dict[str, int | bool]:
        """Counts only: no TTS, viewers, audio, auth token or gameplay content."""
        with self._lock:
            return {
                **self._counts,
                "enabled": self._enabled,
                "active": self._epoch is not None,
                "faulted": self._faulted,
            }


__all__ = ["AudibleAvatarSession"]
