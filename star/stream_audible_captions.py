"""Playback-gated, opt-in captions for Star's live gaming VTuber.

A trusted output backend first reports *consumed* PCM frames to the existing
DeviceAudibleSampleHost. This adapter can then use its short-lived, validated
PlayoutRigFrame to offer a caption matching the corresponding speech chunk.

This module never transcribes microphone input, guesses word timings, opens
OBS, touches viewer chat, sends to a browser, or authorizes a broadcast.
The Windows overlay host must clear its caption whenever sample/current fails,
and must render strings as TEXT (not raw HTML).
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from threading import RLock
from typing import Sequence

from .stream_audio_sample_host import DeviceAudibleSampleHost, DevicePlayoutEpoch
from .stream_playout_clock import PlayoutRigFrame
from .stream_stage import StagePlan, StarStage


@dataclass(frozen=True)
class CaptionSegment:
    """One externally aligned, host-approved TTS phrase (not ASR or a guess)."""

    text: str
    start_sample: int
    end_sample: int

    def __post_init__(self) -> None:
        if (type(self.text) is not str or not 1 <= len(self.text) <= 100
                or self.text.strip() != self.text
                or not self.text.isprintable()
                or any(char in self.text for char in "<>")):
            raise ValueError("captions must be short, printable, single-line plain text")
        if (type(self.start_sample) is not int
                or type(self.end_sample) is not int
                or self.start_sample < 0
                or self.end_sample <= self.start_sample):
            raise ValueError("captions need a positive, ordered PCM interval")


@dataclass(frozen=True, eq=False)
class CaptionRender:
    """Identity-bound proposal: the overlay MUST call current() before display."""

    text: str
    stage_sequence: int
    audio_generation: int
    sampled_at: float
    _rig: PlayoutRigFrame


class AudibleCaptionLane:
    """Tiny O(log N) caption lookup sharing Star's existing PCM clock and stage.

    This is an independent renderer lane; sampling a caption does not consume
    a second device frame. The host passes the very same PlayoutRigFrame it
    already obtained for VTube Studio. The host must never fabricate one.

    Caption content requires independent *on-air* moderation and chunk-alignment
    by the trusted TTS/playback host. Captions describe the active chunk, not
    proof that every word has already finished playing. Disabling does not
    physically erase a browser overlay: the caller must clear it immediately.
    """

    def __init__(
        self, stage: StarStage, device: DeviceAudibleSampleHost, *,
        max_hold_s: float = 0.65,
    ) -> None:
        if not isinstance(stage, StarStage) or not isinstance(device, DeviceAudibleSampleHost):
            raise TypeError("expected existing StarStage and DeviceAudibleSampleHost")
        if device._playout._stage is not stage:
            raise ValueError("caption and PCM hosts must share the exact stage")
        if (type(max_hold_s) not in (int, float)
                or not math.isfinite(max_hold_s)
                or not 0.10 <= max_hold_s <= 1.50):
            raise ValueError("caption hold must be 0.10..1.50 seconds")
        self._stage = stage
        self._device = device
        self._hold = float(max_hold_s)
        self._lock = RLock()
        self._enabled = False
        self._epoch: DevicePlayoutEpoch | None = None
        self._plan: StagePlan | None = None
        self._segments: tuple[CaptionSegment, ...] = ()
        self._starts: tuple[int, ...] = ()
        self._issued: CaptionRender | None = None
        self._highest_generation = 0
        self._emitted = 0
        self._hidden = 0

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit owner approval is required for captions")
        with self._lock:
            if self._epoch is not None:
                raise RuntimeError("stop old caption epoch before re-enabling")
            self._enabled = True

    def bind(
        self, plan: StagePlan, epoch: DevicePlayoutEpoch,
        segments: Sequence[CaptionSegment], *,
        text_approved_for_broadcast: bool = False,
    ) -> bool:
        """Bind approved TTS text only to the live, active audio epoch.

        The separate trusted host must align these phrases with the exact
        committed PCM, *after* content moderation. Never pass raw viewer text.
        """
        if text_approved_for_broadcast is not True:
            raise PermissionError("trusted on-air text approval required")
        if (type(segments) not in (tuple, list)
                or not 1 <= len(segments) <= 48
                or any(not isinstance(s, CaptionSegment) for s in segments)):
            raise ValueError("require 1..48 bounded, approved caption segments")
        if not isinstance(plan, StagePlan) or not isinstance(epoch, DevicePlayoutEpoch):
            raise TypeError("expected existing stage plan and PCM epoch")
        previous_end = -1
        for segment in segments:
            if (segment.start_sample < previous_end
                    or segment.end_sample > epoch.total_samples):
                raise ValueError("caption timings overlap or exceed played PCM")
            previous_end = segment.end_sample
        with self._lock:
            if (not self._enabled or self._epoch is not None
                    or epoch.generation <= self._highest_generation):
                return False
            if not self._stage.current(plan) or not self._device.active_for(epoch, plan):
                return False
            self._plan, self._epoch = plan, epoch
            self._segments = tuple(segments)
            self._starts = tuple(s.start_sample for s in segments)
            self._issued = None
            self._highest_generation = epoch.generation
            return True

    def _blank(self) -> None:
        if self._issued is not None:
            self._hidden += 1
        self._issued = None

    def sample(
        self, epoch: DevicePlayoutEpoch, rig: PlayoutRigFrame | None,
    ) -> CaptionRender | None:
        """Only propose text when a *fresh* host-attested PCM frame is current."""
        with self._lock:
            if (not self._enabled or epoch is not self._epoch
                    or self._plan is None or not isinstance(rig, PlayoutRigFrame)
                    or not self._stage.current(self._plan)
                    or not self._device.current(epoch, rig)):
                self._blank()
                return None
            heard_sample = round(rig.playhead_s * epoch.sample_rate_hz)
            index = bisect_right(self._starts, heard_sample) - 1
            if index < 0:
                self._blank()
                return None
            segment = self._segments[index]
            hold_until = segment.end_sample + round(self._hold * epoch.sample_rate_hz)
            if heard_sample >= hold_until:
                self._blank()
                return None
            proposal = CaptionRender(
                segment.text, self._plan.sequence, epoch.generation,
                rig.sampled_at, rig,
            )
            self._issued = proposal
            self._emitted += 1
            return proposal

    def current(self, epoch: DevicePlayoutEpoch, render: CaptionRender) -> bool:
        """Revalidate immediately before emitting overlay TEXT; do not cache."""
        with self._lock:
            return bool(
                self._enabled and render is self._issued and epoch is self._epoch
                and self._plan is not None and self._stage.current(self._plan)
                and self._device.current(epoch, render._rig)
            )

    def clear(self) -> None:
        """Invalidate a displayed caption; the overlay host must also blank."""
        with self._lock:
            self._blank()

    def stop(self, epoch: DevicePlayoutEpoch) -> None:
        """Forget this turn; caller must clear output even if ticket is stale."""
        with self._lock:
            if epoch is not self._epoch:
                return
            self._blank()
            self._plan = None
            self._epoch = None
            self._segments = ()
            self._starts = ()

    def disable(self) -> None:
        """Disable proposals without pretending to stop TTS or clear OBS."""
        with self._lock:
            if self._epoch is not None:
                self.stop(self._epoch)
            self._enabled = False

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "active": self._epoch is not None,
                "emitted": self._emitted,
                "hidden": self._hidden,
            }


__all__ = ["CaptionSegment", "CaptionRender", "AudibleCaptionLane"]
