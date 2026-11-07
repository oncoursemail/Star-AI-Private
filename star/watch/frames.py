"""Live adaptive frame sampling while a video plays.

star/video_understanding.adaptive_frames picks frames out of a file with a known length; here the video is playing
on screen, so frames arrive one at a time and the question is only "is this one new enough to keep?". The same
thumbnail signature and distance as star/video_sampling.py decide: a frame is kept when it differs from the last kept
frame by at least `min_novelty` (a still talking head is kept once, not every 4 seconds), and `cut` marks a scene
change. Only the newest `keep` frames stay on disk; the rest are deleted. A screenshot is shrunk first (a full screen
is more pixels than video_sampling accepts, and the model does not need them).
"""
from __future__ import annotations

from collections import deque
from pathlib import Path

from ..video_sampling import distance, inspect_candidate
from .model import Frame

MAX_SIDE = 640


class LiveFrameSampler:
    def __init__(self, folder: Path, *, keep: int = 6, min_novelty: float = 0.03, cut: float = 0.22) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.keep, self.min_novelty, self.cut = max(1, keep), min_novelty, cut
        self.frames: deque[Frame] = deque()
        self.offered = 0
        self._last = None
        self._n = 0

    def offer(self, image: Path, at: float) -> Frame | None:
        """Keep `image` (a screenshot) if it is new; returns the kept Frame or None. A broken image is skipped."""
        self.offered += 1
        small = self.folder / f"f{self._n:05d}.jpg"
        try:
            from ..pil_safe import Image
            with Image.open(image) as picture:
                shrunk = picture.convert("RGB")
                shrunk.thumbnail((MAX_SIDE, MAX_SIDE))
                shrunk.save(small, "JPEG", quality=80)
            candidate = inspect_candidate(0, at, small)
        except (OSError, ValueError):
            small.unlink(missing_ok=True)
            return None
        novelty = distance(candidate, self._last) if self._last is not None else 1.0
        if self._last is not None and novelty < self.min_novelty:
            small.unlink(missing_ok=True)
            return None
        self._n += 1
        self._last = candidate
        frame = Frame(at, small, round(novelty, 4), cut=self._n > 1 and novelty >= self.cut)
        self.frames.append(frame)
        while len(self.frames) > self.keep:
            self.frames.popleft().path.unlink(missing_ok=True)
        return frame

    def pick(self, count: int = 3) -> list[Frame]:
        """The newest frame plus the most novel earlier ones, in time order (what the vision model is shown)."""
        frames = list(self.frames)
        if len(frames) <= count:
            return frames
        chosen = {frames[-1].path}
        for frame in sorted(frames[:-1], key=lambda f: -f.novelty)[:count - 1]:
            chosen.add(frame.path)
        return [f for f in frames if f.path in chosen]

    def clear(self) -> None:
        for frame in self.frames:
            frame.path.unlink(missing_ok=True)
        self.frames.clear()
        self._last = None
