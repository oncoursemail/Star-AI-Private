"""Seeing the game: frames from the screen (or fake frames in tests), newest frame always, never a backlog.

Backends, fastest first (pick with `open_capture`):
  dxcam     DXGI Desktop Duplication through the dxcam package (GPU copy; 1080p at well over 60 fps per its
            README), used when installed;
  mss       BitBlt through the mss package, used when installed;
  gdi       BitBlt into a numpy-mapped DIB section (ctypes only), always available on Windows: measured
            17-27 ms p50 at 720p and 35 ms at 1080p on the dev PC (Pillow's ImageGrab: 60-66 ms): 20 Hz at 720p.
Each frame carries its capture time, so the loop can measure capture -> input latency.
"""
from __future__ import annotations

import ctypes
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol, cast

if TYPE_CHECKING:
    import numpy as np

# DXcam 0.3.0 returns one camera per output/backend. Independent STAR sources
# must not borrow that singleton and then release each other's live resources.
_DXCAM_OWNER = threading.Lock()


@dataclass(frozen=True)
class Frame:
    index: int
    t: float                           # capture time (time.perf_counter: the clock every play loop part uses)
    image: np.ndarray                  # H x W x 3, uint8, RGB

    @property
    def size(self) -> tuple[int, int]:
        return self.image.shape[1], self.image.shape[0]


class FrameSource(Protocol):
    name: str

    def grab(self) -> Frame | None: ...

    def close(self) -> None: ...


class FakeFrames:
    """Frames drawn by `make(index) -> image` (tests and the latency bench)."""
    name = "fake"

    def __init__(self, make: Callable[[int], np.ndarray], clock: Callable[[], float] = time.perf_counter) -> None:
        self.make, self.clock, self.index = make, clock, 0

    def grab(self) -> Frame | None:
        image = self.make(self.index)
        frame = Frame(self.index, self.clock(), image)
        self.index += 1
        return frame

    def close(self) -> None:
        pass


def window_rect(title_part: str) -> tuple[int, int, int, int] | None:  # pragma: no cover - needs a Windows desktop
    """Client area (left, top, right, bottom) in screen pixels of the first visible window whose title contains
    `title_part`, or None."""
    user32 = ctypes.windll.user32  # pyright: ignore[reportAttributeAccessIssue]
    found: list[int] = []
    part = title_part.lower()
    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)  # pyright: ignore[reportAttributeAccessIssue]

    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            if part in buf.value.lower():
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(proc(visit), 0)
    if not found:
        return None

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    rect, origin = RECT(), POINT(0, 0)
    user32.GetClientRect(found[0], ctypes.byref(rect))
    user32.ClientToScreen(found[0], ctypes.byref(origin))
    return origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom


class GdiCapture:  # pragma: no cover - reads the real screen
    """BitBlt from the screen into a DIB section that numpy reads in place (no PIL round trip): measured 17-27 ms
    p50 at 1280x720 on the owner's dev PC versus 60 ms for Pillow's ImageGrab (docs/agents/game-play-20261026.md)."""
    name = "gdi"

    def __init__(self, region: tuple[int, int, int, int] | None = None) -> None:
        import ctypes.wintypes as wt
        import numpy

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                        ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                        ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                        ("biClrImportant", wt.DWORD), ("colors", wt.DWORD * 3)]

        user32, self._gdi = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")   # own copies: argtypes stay local  # pyright: ignore[reportAttributeAccessIssue]
        user32.GetDC.restype = wt.HDC
        self._gdi.CreateCompatibleDC.restype = wt.HDC
        self._gdi.CreateCompatibleDC.argtypes = [wt.HDC]
        self._gdi.DeleteObject.argtypes = [wt.HGDIOBJ]
        self._gdi.DeleteDC.argtypes = [wt.HDC]
        user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        self._user32 = user32
        self._gdi.CreateDIBSection.restype = wt.HBITMAP
        self._gdi.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p),
                                               wt.HANDLE, wt.DWORD]
        self._gdi.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
        self._gdi.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC,
                                     ctypes.c_int, ctypes.c_int, wt.DWORD]
        if region is None:
            region = (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
        self.left, self.top = region[0], region[1]
        self.width, self.height = region[2] - region[0], region[3] - region[1]
        self._src = user32.GetDC(None)
        self._mem = self._gdi.CreateCompatibleDC(self._src)
        info = BITMAPINFOHEADER()
        info.biSize, info.biWidth, info.biHeight, info.biPlanes, info.biBitCount = 40, self.width, -self.height, 1, 32
        bits = ctypes.c_void_p()
        self._bitmap = self._gdi.CreateDIBSection(self._mem, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        self._gdi.SelectObject(self._mem, self._bitmap)
        buffer = (ctypes.c_ubyte * (self.width * self.height * 4)).from_address(cast(int, bits.value))
        self._bgra = numpy.frombuffer(buffer, dtype=numpy.uint8).reshape(self.height, self.width, 4)
        self.index = 0

    def grab(self) -> Frame | None:
        t = time.perf_counter()
        self._gdi.BitBlt(self._mem, 0, 0, self.width, self.height, self._src, self.left, self.top, 0x00CC0020)
        self.index += 1
        return Frame(self.index, t, self._bgra[:, :, 2::-1].copy())

    def close(self) -> None:
        self._gdi.DeleteObject(self._bitmap)
        self._gdi.DeleteDC(self._mem)
        self._user32.ReleaseDC(None, self._src)


class MssCapture:  # pragma: no cover - reads the real screen
    name = "mss"

    def __init__(self, region: tuple[int, int, int, int] | None = None) -> None:
        import mss
        import numpy
        self._np, self._mss = numpy, mss.mss()
        try:
            if region is None:
                monitor = self._mss.monitors[1]
                region = (monitor['left'], monitor['top'], monitor['left'] + monitor['width'],
                          monitor['top'] + monitor['height'])
            left, top, right, bottom = region
            if right <= left or bottom <= top:
                raise ValueError('invalid capture region')
            self._box = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        except BaseException:
            self._mss.close()
            raise
        self.index = 0

    def grab(self) -> Frame | None:
        t = time.perf_counter()
        raw = self._np.asarray(self._mss.grab(self._box))           # BGRA
        self.index += 1
        return Frame(self.index, t, raw[:, :, 2::-1].copy())

    def close(self) -> None:
        self._mss.close()


class DxcamCapture:  # pragma: no cover - reads the real screen through the GPU
    name = "dxcam"

    def __init__(self, region: tuple[int, int, int, int] | None = None, *, fresh_snapshot: bool = False) -> None:
        import dxcam
        if not _DXCAM_OWNER.acquire(blocking=False):
            raise RuntimeError('DXcam output already owned by another STAR capture')
        try:
            self._cam = dxcam.create(output_color="RGB")
        except BaseException:
            _DXCAM_OWNER.release()
            raise
        self._owns_camera = True
        self.region, self.index = region, 0
        self._fresh_snapshot = fresh_snapshot
        self.timestamp_kind = 'sample_confirmation_started' if fresh_snapshot else 'new_frame_poll_started'

    def grab(self) -> Frame | None:
        t = time.perf_counter()
        # A fresh snapshot explicitly asks DXcam to confirm the current state even
        # when pixels have not changed. Never re-date a locally cached old image.
        camera = self._cam
        if camera is None:
            return None
        kwargs = {'new_frame_only': False} if getattr(self, '_fresh_snapshot', False) else {}
        image = camera.grab(region=self.region, **kwargs)
        if image is None:
            return None
        self.index += 1
        return Frame(self.index, t, image)

    def close(self) -> None:
        camera = self._cam
        if camera is not None:
            camera.release()
            self._cam = None
            if getattr(self, '_owns_camera', False):
                self._owns_camera = False
                _DXCAM_OWNER.release()


def open_capture(region: tuple[int, int, int, int] | None = None, prefer: tuple[str, ...] = ("dxcam", "mss", "gdi"),
                 *, fresh_snapshot: bool = False
                 ) -> FrameSource:  # pragma: no cover - picks a real backend
    errors = []
    for name in prefer:
        try:
            if name == 'dxcam':
                return DxcamCapture(region, fresh_snapshot=fresh_snapshot)
            return {"dxcam": DxcamCapture, "mss": MssCapture, "gdi": GdiCapture}[name](region)
        except Exception as exc:                               # missing package or no desktop: try the next one
            errors.append(f"{name}: {type(exc).__name__}")
    raise RuntimeError("no screen capture backend works here (" + "; ".join(errors) + ")")
