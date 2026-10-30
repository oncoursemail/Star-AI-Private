"""Optional bridge from accepted game vision packets to understated VTuber cues.

Only a *trusted* host may feed genuine CaptureDispatch objects here. Models,
viewers, game UIs and webpages must never be able to invoke this interface.
This bridge does not speak, run a VLM, automate gameplay, or verify a win.
It limits chatter and marks every visual-only impression as "reported" so
StarStage cannot turn a model guess into a victory or danger animation.
"""
from __future__ import annotations

from typing import cast

from dataclasses import dataclass
import math
from threading import RLock

from .stream_director import StreamSignal
from .stream_stage import StarStage
from .stream_visual_perception import VisualPacket
from .stream_windows_game_capture import CaptureDispatch

# Every phrase is fixed, deliberately noncommittal, and never model-authored.
# The actual voice agent can choose to stay silent when gameplay needs focus.
_PUBLIC_CUES = {
    "hud_change": "An on-screen HUD element may have changed.",
    "scene_change": "The scene seems to have changed.",
    "player_motion": "Something appears to be moving in the game.",
    "object_appeared": "Something may have appeared on the screen.",
    "menu_change": "A game menu looks different.",
    "hazard_indicator": "There may be a warning indicator on the HUD.",
}


def _ms(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("trusted monotonic clock required")
    number = float(cast(int | float, value))
    if not math.isfinite(number) or not 0 <= number <= 1e13:
        raise ValueError("trusted monotonic clock unavailable")
    return number


@dataclass(frozen=True)
class VisionReactionDecision:
    """Neither a spoken reaction nor permission to activate voice/OBS."""

    offered: bool
    reason: str


class GameVisualCueHost:
    """Two-frame confirmation and deliberate silence for visual-only events.

    The same category + region must recur in distinct, fresh, accepted frame
    results. This is corroboration by repeated model *guesses*, NOT a game
    truth assertion. A screenshot cannot independently certify success.
    """

    def __init__(
        self, stage: StarStage, *, min_confidence: float = 0.85,
        min_spacing_ms: int = 150, max_gap_ms: int = 2500,
        max_age_ms: int = 1500, cooldown_ms: int = 18000,
    ) -> None:
        if not isinstance(stage, StarStage):
            raise TypeError("expected existing authorized StarStage")
        confidence = _ms(min_confidence)
        if not 0.50 <= confidence <= 0.99:
            raise ValueError("min_confidence must be 0.50..0.99")
        for key, value, low, high in (
            ("min_spacing_ms", min_spacing_ms, 100, 1000),
            ("max_gap_ms", max_gap_ms, 500, 5000),
            ("max_age_ms", max_age_ms, 200, 2000),
            ("cooldown_ms", cooldown_ms, 5000, 60000),
        ):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key} must be a bounded integer")
        if min_spacing_ms >= max_gap_ms:
            raise ValueError("confirmation window must exceed frame spacing")
        self._stage = stage
        self._confidence = confidence
        self._spacing = min_spacing_ms
        self._gap = max_gap_ms
        self._age = max_age_ms
        self._cooldown = cooldown_ms
        self._lock = RLock()
        self._enabled = False
        self._epoch = 0
        self._serial = 0
        self._last_now_ms = -1.0
        self._last_frame_ms = -1.0
        self._pending: dict[tuple[str, str], float] = {}
        self._last_offered: dict[tuple[str, str], float] = {}
        self._counts = dict(offered=0, rejected=0, stale=0, quiet=0, repeated=0)

    def enable(
        self, *, owner_approved: bool = False, broadcast_approved: bool = False,
    ) -> None:
        """Host permission is distinct from physical audio/broadcast permission."""
        if owner_approved is not True or broadcast_approved is not True:
            raise PermissionError("owner and stream opt-in required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable prior cue session first")
            if self._stage.metrics()["enabled"] is not True:
                raise RuntimeError("enable stream stage separately")
            self._epoch += 1
            self._enabled = True
            self._last_now_ms = -1.0
            self._last_frame_ms = -1.0
            self._pending.clear()
            self._last_offered.clear()

    def disable(self) -> None:
        """Do not disable the stage, mute audio or deactivate camera capture."""
        with self._lock:
            self._enabled = False
            self._epoch += 1
            self._pending.clear()
            self._last_offered.clear()

    def observe(
        self, dispatch: CaptureDispatch, *, now_ms: float,
    ) -> VisionReactionDecision:
        """Offer at most one unverified, fixed-category cue to StarStage.

        The host must pass the result from its own WindowsGameCaptureHost, not
        accept a deserialized/model-created CaptureDispatch or a chat tool.
        Two frames must be distinct admissions; no raw captions leave the
        observation worker. Unknown visual states produce silence.
        """
        now = _ms(now_ms)
        if not isinstance(dispatch, CaptureDispatch):
            raise TypeError("trusted capture dispatch required")
        with self._lock:
            def reject(reason: str, *, stale: bool = False) -> VisionReactionDecision:
                self._counts["rejected"] += 1
                if stale:
                    self._counts["stale"] += 1
                return VisionReactionDecision(False, reason)

            if not self._enabled:
                return reject("visual_reactions_disabled")
            if now < self._last_now_ms:
                self._pending.clear()
                self._last_offered.clear()
                return reject("host_clock_reversed", stale=True)
            self._last_now_ms = now
            packet = dispatch.perception
            if (dispatch.worker_accepted is not True
                    or dispatch.state != "worker_result_accepted"
                    or type(packet) is not VisualPacket):
                return reject("no_accepted_visual_packet")
            if (packet.captured_ms <= self._last_frame_ms
                    or packet.captured_ms > now + 20
                    or now - packet.captured_ms > self._age):
                return reject("out_of_order_or_stale_visual_packet", stale=True)
            self._last_frame_ms = packet.captured_ms

            # Prune old pending candidates; avoid unbounded cross-frame memory.
            self._pending = {
                key: when for key, when in self._pending.items()
                if 0 <= packet.captured_ms - when <= self._gap
            }
            self._last_offered = {
                key: when for key, when in self._last_offered.items()
                if 0 <= now - when < self._cooldown
            }
            eligible = sorted(
                (finding for finding in packet.findings
                 if finding.kind in _PUBLIC_CUES and finding.confidence >= self._confidence),
                key=lambda finding: (-finding.confidence, finding.kind, finding.region),
            )
            if not eligible:
                self._counts["quiet"] += 1
                return VisionReactionDecision(False, "no_confident_visual_cue")
            for finding in eligible:
                key = finding.kind, finding.region
                if key in self._last_offered:
                    self._counts["repeated"] += 1
                    continue
                previous = self._pending.get(key)
                if previous is None or not self._spacing <= packet.captured_ms - previous <= self._gap:
                    self._pending[key] = packet.captured_ms
                    continue
                # Consumption is one-shot even if the stage is busy. The
                # next frame must reconfirm; never accumulate a TTS queue.
                self._pending.pop(key, None)
                self._serial += 1
                event = StreamSignal(
                    signal_id=f"gv:{self._epoch}:{self._serial}",
                    kind="game_observation", timestamp=now / 1000.0,
                    detail=_PUBLIC_CUES[finding.kind], evidence="reported",
                )
                if self._stage.offer(event, now=now / 1000.0):
                    self._counts["offered"] += 1
                    self._last_offered[key] = now
                    return VisionReactionDecision(True, "visual_cue_offered")
                return reject("stream_stage_declined")
            self._counts["quiet"] += 1
            return VisionReactionDecision(False, "awaiting_confirmation_or_cooldown")

    def status(self) -> dict[str, int | bool]:
        """Aggregate metadata only; no frames, HWND, identities or captions."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "pending_categories": len(self._pending)}


__all__ = ["GameVisualCueHost", "VisionReactionDecision"]
