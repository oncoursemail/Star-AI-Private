"""Screenshots for the computer-use loop: PIL images of the screen or a region, and a cheap "did the pixels change"
test. The real eye uses the GDI capture from star/play/capture.py (17-27 ms at 720p on the dev PC) and falls back to
Pillow's ImageGrab; tests pass a fake with the same two methods."""
from __future__ import annotations

from typing import Protocol

Rect = tuple[int, int, int, int]


class Eye(Protocol):
    def grab(self, region: Rect | None = None): ...


class ScreenEye:  # pragma: no cover - reads the real screen
    def __init__(self) -> None:
        self._sources: dict = {}

    def grab(self, region: Rect | None = None):
        from PIL import Image
        try:
            from ..play.capture import GdiCapture
            source = self._sources.get(region)
            if source is None:
                source = self._sources[region] = GdiCapture(region)
            return Image.fromarray(source.grab().image)
        except Exception:
            from PIL import ImageGrab
            return ImageGrab.grab(bbox=region, all_screens=False).convert("RGB")


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
