"""Bounded, local-only content-aware keyframe screening for video understanding.

A video model cannot examine every frame of a long gameplay video on an 8 GiB GPU.
This module uses *small decoded thumbnails* to select representatives of separate
time windows. It has no ML model, cloud calls, persistence or game controls.

This is a heuristic. In particular it cannot detect an event that occurred
between sampled times, infer a video's meaning, or guarantee better Video QA.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

# Cheap enough to score up to 18 thumbnail candidates per video request.
_THUMBNAIL = (24, 14)
_FRACTIONS = (0.20, 0.50, 0.80)
_MAX_FRAMES = 6
# A deliberately conservative comparison: only nearly-identical images collapse.
_DUPLICATE_DISTANCE = 0.008


@dataclass(frozen=True)
class Candidate:
    window: int
    second: float
    path: Path
    pixels: tuple[int, ...]
    quality: float


def candidate_times(duration: float, windows: int) -> list[tuple[int, float]]:
    """Distribute three candidate timestamps within each temporal window."""
    if not isinstance(windows, int) or isinstance(windows, bool) or not 1 <= windows <= _MAX_FRAMES:
        raise ValueError("Use 1-6 video frame windows")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0 or duration > 5400:
        raise ValueError("Video duration must be 0-5400 seconds")
    return [(slot, duration * (slot + fraction) / windows)
            for slot in range(windows) for fraction in _FRACTIONS]


def inspect_candidate(window: int, second: float, path: Path) -> Candidate:
    """Inspect only a tiny sanitized JPEG; refuse oversized/malformed previews."""
    from .pil_safe import Image

    with Image.open(path) as picture:
        if not picture.width or not picture.height or picture.width * picture.height > 500_000:
            raise ValueError("Invalid video preview resolution")
        # EXIF is not a source of instructions; only the decoded RGB pixels matter.
        pixels = tuple(picture.convert("RGB").resize(_THUMBNAIL, Image.Resampling.BILINEAR).tobytes())
    if len(pixels) != _THUMBNAIL[0] * _THUMBNAIL[1] * 3:
        raise ValueError("Invalid video preview pixels")
    # Avoid black transitions / loading screens, but don't call brightness "importance".
    brightness = sum(pixels) / len(pixels) / 255
    contrast = (max(pixels) - min(pixels)) / 255
    quality = 0.55 * min(brightness / 0.25, 1.0) + 0.45 * min(contrast / 0.30, 1.0)
    return Candidate(window, second, path, pixels, quality)


def distance(a: Candidate, b: Candidate) -> float:
    """Normalized RGB mean absolute distance in [0, 1]."""
    if len(a.pixels) != len(b.pixels) or not a.pixels:
        raise ValueError("Keyframe signatures have incompatible sizes")
    return sum(abs(x - y) for x, y in zip(a.pixels, b.pixels)) / (len(a.pixels) * 255)


def choose_keyframes(candidates: list[Candidate], windows: int) -> list[Candidate]:
    """Select chronologically ordered representative/novel frames, at most one/window.

    A local medoid term avoids choosing an isolated flash solely for novelty.
    Near-exact repeated frames are omitted to reduce expensive vision tokens.
    All windows are examined; no assumed gameplay outcomes are invented.
    """
    if not 1 <= windows <= _MAX_FRAMES:
        raise ValueError("Invalid window count")
    selected: list[Candidate] = []
    previous: Candidate | None = None
    for window in range(windows):
        peers = [candidate for candidate in candidates if candidate.window == window]
        if not peers:
            continue
        centre = (min(x.second for x in peers) + max(x.second for x in peers)) / 2
        span = max(max(x.second for x in peers) - min(x.second for x in peers), 0.001)

        def rank(candidate: Candidate) -> tuple[float, float]:
            representative = 1 - sum(distance(candidate, p) for p in peers) / len(peers)
            novelty = distance(candidate, previous) if previous is not None else 0
            central = 1 - min(1, abs(candidate.second - centre) / span * 2)
            return (0.45 * representative + 0.30 * novelty
                    + 0.20 * candidate.quality + 0.05 * central,
                    -abs(candidate.second - centre))

        winner = max(peers, key=rank)
        if previous is not None and distance(previous, winner) <= _DUPLICATE_DISTANCE:
            continue
        selected.append(winner)
        previous = winner
    return selected
