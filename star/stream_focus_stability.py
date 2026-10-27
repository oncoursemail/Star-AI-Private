"""Optional temporal confirmation of nonsemantic focal HUD fingerprint changes.

A blinking cursor, damage flash, capture artifact or one noisy frame should
not necessarily trigger an expensive model observation. In opt-in mode the
trusted stream host compares owner-selected, already-captured focus signatures
across distinct, fresh frames. Only stable transitions reach the existing
vision novelty governor; urgent trusted game cues and whole-scene changes
remain untouched. This is *not* recognition or proof of game events.

No pixels, frame copies, identities, viewer text, audio or recordings survive
this function. Scope resets never reclassify an old capture as a new one.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .frame_fingerprint import Region, tone_distance
from .stream_observe import FocusSample, FrameCue


@dataclass(frozen=True)
class FocusGateResult:
    frame: FrameCue
    suppressed: int = 0
    confirmed: tuple[Region, ...] = ()


def _same(a: FocusSample, b: FocusSample, *, edges: int, tones: int) -> bool:
    return (a.region == b.region
            and (a.edge_hash ^ b.edge_hash).bit_count() < edges
            and tone_distance(a.tone_signature, b.tone_signature) < tones)


class TemporalFocusGate:
    """O(8) session-local temporal denoiser; owner-configurable and OFF by default.

    The first capture of any new ROI configuration establishes a baseline and
    remains visible to the downstream novelty governor. Later changes require
    repeated independent captures to be promoted. A new ROI scope always goes
    through unchanged to force downstream scope re-comparison.

    This filters focus samples ONLY. It never suppresses trusted game cues,
    whole-game hashes, HUD hashes, or their tone signatures. The ordinary
    vision governor still independently enforces authorization, freshness,
    single-flight workers, budgets, consent and game-FPS headroom.
    """

    def __init__(
        self, *, confirm_frames: int = 2, max_gap_ms: float = 1800.0,
        edge_threshold: int = 4, tone_threshold: int = 3,
    ) -> None:
        if type(confirm_frames) is not int or not 2 <= confirm_frames <= 5:
            raise ValueError("confirm_frames must be 2..5")
        if type(max_gap_ms) not in (float, int):
            raise ValueError("max_gap_ms must be finite and between 30 and 3000")
        try:
            gap = float(max_gap_ms)
        except (ValueError, OverflowError) as exc:
            raise ValueError("max_gap_ms must be finite and between 30 and 3000") from exc
        if not math.isfinite(gap) or not 30 <= gap <= 3000:
            raise ValueError("max_gap_ms must be finite and between 30 and 3000")
        if type(edge_threshold) is not int or not 1 <= edge_threshold <= 64:
            raise ValueError("edge_threshold must be 1..64")
        if type(tone_threshold) is not int or not 1 <= tone_threshold <= 63:
            raise ValueError("tone_threshold must be 1..63")
        self.confirm_frames = confirm_frames
        self.max_gap_ms = gap
        self.edge_threshold = edge_threshold
        self.tone_threshold = tone_threshold
        self.reset()

    def reset(self) -> None:
        self._last_capture_ms: float | None = None
        self._scope: tuple[Region, ...] | None = None
        self._stable: dict[Region, FocusSample] = {}
        self._pending: dict[Region, tuple[FocusSample, int, float]] = {}

    def _similar(self, a: FocusSample, b: FocusSample) -> bool:
        return _same(a, b, edges=self.edge_threshold, tones=self.tone_threshold)

    def filter(self, frame: FrameCue) -> FocusGateResult:
        if not isinstance(frame, FrameCue):
            raise TypeError("expected validated host FrameCue")
        regions = tuple(sample.region for sample in frame.focus_samples)
        captured = frame.captured_ms
        if self._last_capture_ms is not None and captured <= self._last_capture_ms:
            # Never count a duplicate/out-of-order capture toward confirmation.
            # The independent governor decides whether the frame is admissible.
            if regions != self._scope:
                return FocusGateResult(frame)
            return FocusGateResult(replace(
                frame, focus_samples=tuple(self._stable[r] for r in regions)
            ))
        self._last_capture_ms = captured
        if regions != self._scope:
            self._scope = regions
            self._stable = {sample.region: sample for sample in frame.focus_samples}
            self._pending.clear()
            return FocusGateResult(frame)

        output: list[FocusSample] = []
        suppressed = 0
        confirmed: list[Region] = []
        for sample in frame.focus_samples:
            baseline = self._stable[sample.region]
            if self._similar(sample, baseline):
                self._pending.pop(sample.region, None)
                output.append(baseline)
                continue
            candidate = self._pending.get(sample.region)
            if (candidate is not None
                    and captured - candidate[2] <= self.max_gap_ms
                    and self._similar(sample, candidate[0])):
                steps = candidate[1] + 1
            else:
                steps = 1
            if steps >= self.confirm_frames:
                self._stable[sample.region] = sample
                self._pending.pop(sample.region, None)
                output.append(sample)
                confirmed.append(sample.region)
            else:
                self._pending[sample.region] = (sample, steps, captured)
                output.append(baseline)
                suppressed += 1
        return FocusGateResult(
            frame=replace(frame, focus_samples=tuple(output)),
            suppressed=suppressed,
            confirmed=tuple(confirmed),
        )


__all__ = ["FocusGateResult", "TemporalFocusGate"]
