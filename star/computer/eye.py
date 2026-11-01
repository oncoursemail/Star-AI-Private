"""Continuous memory-only capture for computer use, plus a cheap pixel-change check."""
from __future__ import annotations

import threading
from typing import Callable, Protocol

from ..play.capture import FrameSource, open_capture
from .live_vision import LatestFrameCapture

Rect = tuple[int, int, int, int]


class Eye(Protocol):
    def grab(self, region: Rect | None = None): ...


class ScreenEye:
    def __init__(self, source_factory: Callable[[Rect | None], FrameSource] | None = None, *, hz: float = 30,
                 max_age_s: float = .5, stopped: Callable[[], bool] | None = None) -> None:
        # Explicit rectangles use desktop coordinates, including negative monitor
        # origins. DXcam's region is relative to its selected output instead.
        self._factory = source_factory or (lambda region: open_capture(
            region, prefer=('mss', 'gdi') if region is not None else ('dxcam', 'mss', 'gdi'), fresh_snapshot=True))
        self._hz, self._max_age_s, self._stopped = hz, max_age_s, stopped
        self._lock = threading.RLock()
        self._capture: LatestFrameCapture | None = None
        self._region: Rect | None = None
        self._closed = False
        self._switching = False

    def start(self, region: Rect | None = None) -> LatestFrameCapture:
        with self._lock:
            if self._closed:
                raise RuntimeError('screen eye is closed')
            if self._switching:
                raise RuntimeError('screen capture region is changing')
            previous = self._capture
            if previous is not None and region == self._region:
                return previous
            self._switching = True
        try:
            if previous is not None:
                if not previous.close():
                    raise RuntimeError('previous screen capture is still closing')
            capture = LatestFrameCapture(lambda: self._factory(region), hz=self._hz,
                                         max_age_s=self._max_age_s, stopped=self._stopped)
            with self._lock:
                if self._closed:
                    raise RuntimeError('screen eye is closed')
                self._region, self._capture = region, capture
        finally:
            with self._lock:
                self._switching = False
        capture.start()
        return capture

    def grab_frame(self, region: Rect | None = None):
        capture = self.start(region)
        return capture.grab(timeout=1)

    def grab(self, region: Rect | None = None):
        from PIL import Image
        frame = self.grab_frame(region)
        if frame is None:
            raise RuntimeError('no fresh desktop frame is available')
        return Image.fromarray(frame.image)

    def status(self) -> dict:
        with self._lock:
            capture, closed = self._capture, self._closed
        return capture.status() if capture is not None else {
            'available': False, 'closed': closed, 'perception_connected': False,
            'cleanup_complete': closed, 'buffered_frames': 0}

    def close(self, timeout: float = 1) -> bool:
        with self._lock:
            self._closed = True
            capture = self._capture
        return capture.close(timeout) if capture is not None else True


def changed_fraction(before, after, cell: int = 16, threshold: int = 24) -> float:
    """Share of 16x16-pixel cells whose average brightness moved by more than `threshold` (0..1). Images of different
    sizes count as fully changed. The mouse pointer alone moves well under 1% of the cells."""
    if before.size != after.size:
        return 1.0
    w, h = before.size
    small = (max(1, w // cell), max(1, h // cell))
    a = before.convert("L").resize(small)
    b = after.convert("L").resize(small)
    diffs = [abs(x - y) > threshold for x, y in zip(a.tobytes(), b.tobytes())]
    return sum(diffs) / len(diffs)
