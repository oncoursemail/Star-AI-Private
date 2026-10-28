"""Owner-scoped Windows game-window capture into STAR's live vision governor.

Unlike desktop screenshots, this backend *only* requests a pinned HWND using
Pillow's Windows window= API. The trusted host pins the HWND and process ID
out of band; viewer text, an LLM, or a game UI can never choose either.

The module never persists images, streams, controls a game, starts OBS, or
declares game events successful. Capture is OFF by default and requires two
explicit host approvals and a separately enabled StreamVisionHost.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import math
import os
from threading import RLock
import time
from typing import Callable

from .frame_fingerprint import Region
from .stream_vision_host import StreamVisionHost, VisionAdmission

MAX_CAPTURE_PIXELS = 3840 * 2160
MAX_CAPTURE_AGE_MS = 1500.0


@dataclass(frozen=True)
class WindowState:
    hwnd: int
    pid: int
    visible: bool
    minimized: bool
    width: int
    height: int


def probe_windows_window(hwnd: int) -> WindowState:
    """Read OS window identity and visibility; never capture the desktop."""
    if os.name != "nt":
        raise RuntimeError("window-only capture requires Windows")
    if type(hwnd) is not int or hwnd <= 0:
        raise ValueError("invalid host-selected HWND")
    user32 = ctypes.windll.user32
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    if not user32.IsWindow(hwnd):
        raise RuntimeError("configured window has closed")
    pid = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
        raise RuntimeError("window process identity unavailable")
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("window geometry unavailable")
    return WindowState(
        hwnd, int(pid.value), bool(user32.IsWindowVisible(hwnd)),
        bool(user32.IsIconic(hwnd)), rect.right - rect.left,
        rect.bottom - rect.top,
    )


def grab_windows_window(hwnd: int) -> object:
    """Pillow 11.2.1+ HWND API; NEVER fall back to bbox or whole-desktop grab."""
    if os.name != "nt":
        raise RuntimeError("window-only capture requires Windows")
    try:
        from PIL import ImageGrab
        import inspect
        if "window" not in inspect.signature(ImageGrab.grab).parameters:
            raise RuntimeError("Pillow window= capture requires Pillow 11.2.1+")
        return ImageGrab.grab(window=hwnd)
    except ImportError as exc:
        raise RuntimeError("Pillow 11.2.1+ is required for game-window capture") from exc


def _clock_ms(clock: Callable[[], float]) -> float:
    value = clock()
    if type(value) not in (float, int):
        raise ValueError("capture monotonic clock unavailable")
    stamp = float(value)
    if not math.isfinite(stamp) or not 0 <= stamp <= 1e13:
        raise ValueError("capture monotonic clock unavailable")
    return stamp


class WindowsGameCaptureHost:
    """Bounded one-window observation adapter. No model-facing capture API.

    The pinned PID is a *host authentication guard* against a recycled HWND,
    not evidence that the window contains a particular game or that a match
    happened. Host authorization must still approve the chosen game process.
    Never reuse this object after changing to a different game/window.

    The caller must acknowledge physical vision-worker termination through
    StreamVisionHost, independently of stopping this capture loop.
    """

    def __init__(
        self, vision: StreamVisionHost, *, hwnd: int, pid: int,
        min_interval_ms: float = 500,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        probe: Callable[[int], WindowState] = probe_windows_window,
        grab: Callable[[int], object] = grab_windows_window,
        game_region: Region | None = None,
        hud_region: Region | None = None,
        focus_regions: tuple[Region, ...] = (),
    ) -> None:
        if not isinstance(vision, StreamVisionHost):
            raise TypeError("real StreamVisionHost required")
        if type(hwnd) is not int or hwnd <= 0 or type(pid) is not int or pid <= 0:
            raise ValueError("trusted positive window handle and process ID required")
        if type(min_interval_ms) not in (int, float) or not 250 <= float(min_interval_ms) <= 5000:
            raise ValueError("capture interval must be 250..5000 milliseconds")
        if not all(callable(f) for f in (clock_ms, probe, grab)):
            raise TypeError("trusted probe, grabber and monotonic clock required")
        if type(focus_regions) is not tuple or len(focus_regions) > 4:
            raise ValueError("up to four host-defined focus regions allowed")
        for roi in (game_region, hud_region, *focus_regions):
            if roi is not None and (
                type(roi) is not tuple or len(roi) != 4
                or any(type(x) is not int for x in roi)
                or roi[0] < 0 or roi[1] < 0 or roi[2] < 9 or roi[3] < 8
            ):
                raise ValueError("invalid host-defined image region")
        if len(set(focus_regions)) != len(focus_regions):
            raise ValueError("focus regions must be distinct")
        self._vision = vision
        self._hwnd, self._pid = hwnd, pid
        self._interval_ms = float(min_interval_ms)
        self._clock, self._probe, self._grab = clock_ms, probe, grab
        self._game_region, self._hud_region = game_region, hud_region
        self._focus_regions = focus_regions
        self._lock = RLock()
        self._enabled = False
        self._busy = False
        self._epoch = 0
        self._last_attempt = float("-inf")
        self._counts = dict(
            captures=0, admitted=0, deferred=0, capture_failed=0,
            stale_discarded=0, identity_rejected=0, preflight_skipped=0,
        )

    def enable(self, *, owner_approved: bool = False, capture_approved: bool = False) -> None:
        """Does not enable the vision worker or grant Windows screenshot rights."""
        if owner_approved is not True or capture_approved is not True:
            raise PermissionError("owner and separately granted capture approval required")
        with self._lock:
            if self._enabled or self._busy:
                raise RuntimeError("disable old capture session before re-enabling")
            if self._vision.status()["enabled"] is not True:
                raise RuntimeError("host must separately enable hardware-governed vision")
            self._enabled = True
            self._epoch += 1
            self._last_attempt = float("-inf")

    def disable(self) -> None:
        """Invalidate in-flight capture results; caller still stops vision workers."""
        with self._lock:
            self._enabled = False
            self._epoch += 1

    def _window_valid(self, state: WindowState) -> bool:
        return (
            type(state) is WindowState and state.hwnd == self._hwnd
            and state.pid == self._pid and state.visible and not state.minimized
            and 9 <= state.width <= 8192 and 8 <= state.height <= 8192
            and state.width * state.height <= MAX_CAPTURE_PIXELS
        )

    def capture_once(self) -> VisionAdmission:
        """Capture only after CPU/GPU/FPS preflight; never return raw frame data."""
        with self._lock:
            if not self._enabled:
                return VisionAdmission(False, "window_capture_disabled", 0)
            if self._busy:
                return VisionAdmission(False, "window_capture_in_flight", 0)
            start = _clock_ms(self._clock)
            if start < self._last_attempt:
                self._counts["stale_discarded"] += 1
                return VisionAdmission(False, "capture_clock_reversed", 0)
            if start - self._last_attempt < self._interval_ms:
                self._counts["deferred"] += 1
                return VisionAdmission(False, "window_capture_interval", 0)
            preflight = self._vision.capture_preflight()
            if not preflight.admitted:
                self._counts["preflight_skipped"] += 1
                return preflight
            self._last_attempt = start
            self._busy = True
            epoch = self._epoch
        try:
            before = self._probe(self._hwnd)
            if not self._window_valid(before):
                with self._lock:
                    self._counts["identity_rejected"] += 1
                return VisionAdmission(False, "window_identity_or_size_rejected", 0)
            # Window-only native grab; NO whole screen fallback on any error.
            image = self._grab(self._hwnd)
            size = getattr(image, "size", None)
            if (type(size) is not tuple or len(size) != 2
                    or any(type(x) is not int for x in size)
                    or size[0] < 9 or size[1] < 8
                    or size[0] * size[1] > MAX_CAPTURE_PIXELS
                    or size[0] > 8192 or size[1] > 8192):
                raise ValueError("window screenshot dimensions invalid")
            rgb = image.convert("RGB")
            width, height = rgb.size
            pixels = rgb.tobytes()
            if len(pixels) != width * height * 3:
                raise ValueError("window screenshot layout invalid")
            end = _clock_ms(self._clock)
            after = self._probe(self._hwnd)
            if not self._window_valid(after) or after != before:
                with self._lock:
                    self._counts["identity_rejected"] += 1
                return VisionAdmission(False, "window_changed_during_capture", 0)
            if end < start or end - start > MAX_CAPTURE_AGE_MS:
                with self._lock:
                    self._counts["stale_discarded"] += 1
                return VisionAdmission(False, "window_capture_stale", 0)
            with self._lock:
                if not self._enabled or epoch != self._epoch:
                    self._counts["stale_discarded"] += 1
                    return VisionAdmission(False, "window_capture_revoked", 0)
                self._counts["captures"] += 1
                decision = self._vision.consider_pixels(
                    pixels, captured_ms=end, width=width, height=height,
                    pixel_format="RGB", cue="none",
                    game_region=self._game_region, hud_region=self._hud_region,
                    focus_regions=self._focus_regions,
                )
                self._counts["admitted" if decision.admitted else "deferred"] += 1
                return decision
        except Exception:
            # Never log, retain, serialize or return raw pixels or OS window details.
            with self._lock:
                self._counts["capture_failed"] += 1
            return VisionAdmission(False, "window_capture_backend_failed", 0)
        finally:
            with self._lock:
                self._busy = False

    def status(self) -> dict[str, int | bool]:
        """Only aggregate counts; no window titles, identifiers or images."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled, "capture_busy": self._busy}


__all__ = [
    "WindowState", "WindowsGameCaptureHost",
    "probe_windows_window", "grab_windows_window",
]
