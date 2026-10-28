"""Opt-in RAM-only visual recall for an authorized gaming vision worker.

A small, compressed history lets Star's *host* revisit earlier game frames
instead of repeatedly querying a slow vision model. No model/viewer/game pixel
may grant permissions, select a capture target, fetch arbitrary files, or send
images over the network. History is advisory visual evidence, never a win
receipt. Capture permission and the underlying worker's own opt-in are separate.

Decoded PIL buffers and copies made by external callers cannot be reliably
zeroized in Python. Stored JPEG bytearrays and outstanding inspection handles
are best-effort wiped at eviction, expiration and disable.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from io import BytesIO
import math
from threading import RLock
from typing import Callable

from .stream_visual_perception import MAX_PIXELS
from .stream_windows_game_capture import CapturedVisionFrame, WorkerReport


@dataclass(frozen=True)
class RecallBookmark:
    """Metadata only, with an epoch-scoped identifier rather than pixels."""

    frame_id: str
    captured_ms: float
    width: int
    height: int


@dataclass
class InspectedCrop:
    """Temporary image handed only to the trusted host; call erase() after use."""

    frame_id: str
    captured_ms: float
    jpeg: bytearray
    width: int
    height: int

    def erase(self) -> None:
        self.jpeg[:] = b"\x00" * len(self.jpeg)


@dataclass
class _Entry:
    bookmark: RecallBookmark
    jpeg: bytearray

    def erase(self) -> None:
        self.jpeg[:] = b"\x00" * len(self.jpeg)


def _clock(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host monotonic milliseconds required")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1e13:
        raise ValueError("invalid host monotonic clock")
    return number


def _box(value: object) -> tuple[int, int, int, int]:
    if (type(value) is not tuple or len(value) != 4
            or any(type(part) is not int or not 0 <= part <= 1000
                   for part in value)):
        raise ValueError("host-selected ROI must be a normalized integer tuple")
    x0, y0, x1, y1 = value
    if x1 - x0 < 50 or y1 - y0 < 50:
        raise ValueError("ROI must be at least five percent wide and high")
    return value


class VisualRecallHost:
    """Compose with a trusted WindowsGameCaptureHost worker (no new capture).

    The callback has exactly the existing CapturedVisionFrame -> WorkerReport
    shape, so host applications can explicitly pass this object as their
    trusted_worker. Recording happens only after a successful, confirmed-stop
    worker report. It adds no JPEG processing if disabled, and never changes
    the worker's outcome, permissions, lease or timeout/quarantine policy.

    Indexing and ROI inspection do not create VLM calls or game input.
    """

    def __init__(
        self, worker: Callable[[CapturedVisionFrame], WorkerReport], *,
        max_frames: int = 5, ttl_ms: int = 15000,
        max_bytes: int = 1_000_000, storage_side: int = 480,
        inspection_side: int = 256, min_spacing_ms: int = 200,
    ) -> None:
        if not callable(worker):
            raise TypeError("trusted capture worker callback required")
        for name, value, minimum, maximum in (
            ("max_frames", max_frames, 2, 8),
            ("ttl_ms", ttl_ms, 2000, 30000),
            ("max_bytes", max_bytes, 128000, 2000000),
            ("storage_side", storage_side, 128, 640),
            ("inspection_side", inspection_side, 128, 512),
            ("min_spacing_ms", min_spacing_ms, 100, 2000),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} outside hard privacy/resource limit")
        self._worker = worker
        self._max_frames = max_frames
        self._ttl_ms = ttl_ms
        self._max_bytes = max_bytes
        self._storage_side = storage_side
        self._inspection_side = inspection_side
        self._spacing = min_spacing_ms
        self._lock = RLock()
        self._enabled = False
        self._epoch = 0
        self._serial = 0
        self._last_clock = -1.0
        self._entries: deque[_Entry] = deque()
        self._outstanding: deque[InspectedCrop] = deque()
        self._counts = dict(recorded=0, duplicate=0, throttled=0,
                            evicted=0, expired=0, rejected=0,
                            inspected=0, worker_uncertain=0)

    def _clear(self) -> None:
        while self._entries:
            self._entries.popleft().erase()
        while self._outstanding:
            self._outstanding.popleft().erase()

    def enable(self, *, owner_approved: bool = False,
               game_capture_approved: bool = False) -> None:
        if owner_approved is not True or game_capture_approved is not True:
            raise PermissionError("owner and authorized game capture opt-in required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable current recall session first")
            self._clear()
            self._epoch += 1
            self._serial = 0
            self._last_clock = -1.0
            self._enabled = True

    def disable(self) -> None:
        """Erase every managed JPEG/crop; does not stop the underlying worker."""
        with self._lock:
            self._enabled = False
            self._epoch += 1
            self._last_clock = -1.0
            self._clear()

    def _prune(self, now: float) -> None:
        while self._entries and now - self._entries[0].bookmark.captured_ms > self._ttl_ms:
            self._entries.popleft().erase()
            self._counts["expired"] += 1

    def _encoded(self, frame: CapturedVisionFrame) -> bytearray:
        if type(frame) is not CapturedVisionFrame:
            raise ValueError("trusted captured frame required")
        w, h = frame.width, frame.height
        _clock(frame.captured_ms)
        if (type(w) is not int or type(h) is not int
                or not 9 <= w <= 8192 or not 8 <= h <= 8192
                or w * h > MAX_PIXELS
                or not isinstance(frame.rgb, memoryview)
                or frame.rgb.ndim != 1 or len(frame.rgb) != w * h * 3):
            raise ValueError("malformed captured RGB frame")
        from PIL import Image
        image = Image.frombytes("RGB", (w, h), frame.rgb.tobytes())
        try:
            if max(image.size) > self._storage_side:
                scale = self._storage_side / max(image.size)
                resized = image.resize(
                    (max(1, round(w * scale)), max(1, round(h * scale))),
                    Image.Resampling.BILINEAR,
                )
                image.close()
                image = resized
            with BytesIO() as output:
                image.save(output, format="JPEG", quality=65)
                encoded = bytearray(output.getvalue())
            if len(encoded) > 400000:
                encoded[:] = b"\x00" * len(encoded)
                raise ValueError("snapshot exceeds per-frame budget")
            return encoded
        finally:
            image.close()

    def __call__(self, frame: CapturedVisionFrame) -> WorkerReport:
        """Preserve underlying worker semantics, including uncertain timeouts."""
        with self._lock:
            session = self._epoch if self._enabled else None
        try:
            report = self._worker(frame)
        except BaseException:
            with self._lock:
                self._clear()
                self._counts["worker_uncertain"] += 1
            raise
        if type(report) is not WorkerReport:
            with self._lock:
                self._clear()
            raise TypeError("trusted worker returned invalid report")
        with self._lock:
            if report.stopped is not True:
                self._clear()
                self._counts["worker_uncertain"] += 1
                return report
            if (session is None or not self._enabled or session != self._epoch
                    or report.succeeded is not True):
                return report
            try:
                when = _clock(frame.captured_ms)
                if when < self._last_clock:
                    self._counts["rejected"] += 1
                    return report
                self._last_clock = when
                self._prune(when)
                # Skip preparing a JPEG when the inter-frame spacing is too
                # small; this stays off the expensive inference path.
                if (self._entries and when - self._entries[-1].bookmark.captured_ms
                        < self._spacing):
                    self._counts["throttled"] += 1
                    return report
                encoded = self._encoded(frame)
                if self._entries and self._entries[-1].jpeg == encoded:
                    encoded[:] = b"\x00" * len(encoded)
                    self._counts["duplicate"] += 1
                    return report
                if len(encoded) > self._max_bytes:
                    encoded[:] = b"\x00" * len(encoded)
                    self._counts["rejected"] += 1
                    return report
                self._serial += 1
                bookmark = RecallBookmark(
                    f"{self._epoch}:{self._serial}", when, frame.width, frame.height
                )
                self._entries.append(_Entry(bookmark, encoded))
                while (len(self._entries) > self._max_frames
                       or sum(len(item.jpeg) for item in self._entries) > self._max_bytes):
                    self._entries.popleft().erase()
                    self._counts["evicted"] += 1
                self._counts["recorded"] += 1
            except (ValueError, TypeError, OSError, ImportError):
                # Recall is best-effort and must never change worker success.
                self._counts["rejected"] += 1
            return report

    def recent(self, *, now_ms: float) -> tuple[RecallBookmark, ...]:
        """Metadata for a host-owned inspect UI; no JPEG or viewer information."""
        now = _clock(now_ms)
        with self._lock:
            if not self._enabled:
                return ()
            if now < self._last_clock:
                raise ValueError("host clock reversed")
            self._last_clock = now
            self._prune(now)
            return tuple(item.bookmark for item in self._entries)

    def inspect(
        self, frame_id: str, *, focus_box: tuple[int, int, int, int],
        now_ms: float, owner_approved: bool = False,
        inspection_approved: bool = False,
    ) -> InspectedCrop | None:
        """Return a bounded ROI JPEG only after separate explicit host approval.

        An inspector must erase() the returned buffer after use. disable()
        also wipes outstanding buffers still owned by this object.
        """
        if owner_approved is not True or inspection_approved is not True:
            raise PermissionError("owner and local visual-inspection permission required")
        box = _box(focus_box)
        now = _clock(now_ms)
        if type(frame_id) is not str or len(frame_id) > 40:
            raise ValueError("invalid frame bookmark")
        with self._lock:
            if not self._enabled:
                return None
            if now < self._last_clock:
                raise ValueError("host clock reversed")
            self._last_clock = now
            self._prune(now)
            entry = next((entry for entry in self._entries
                          if entry.bookmark.frame_id == frame_id), None)
            if entry is None:
                return None
            from PIL import Image
            with Image.open(BytesIO(entry.jpeg)) as source:
                w, h = source.size
                x0, y0, x1, y1 = box
                left, top = w * x0 // 1000, h * y0 // 1000
                right, bottom = w * x1 // 1000, h * y1 // 1000
                if right - left < 8 or bottom - top < 8:
                    return None
                crop = source.crop((left, top, right, bottom))
            try:
                if max(crop.size) > self._inspection_side:
                    scale = self._inspection_side / max(crop.size)
                    smaller = crop.resize(
                        (max(1, round(crop.width * scale)),
                         max(1, round(crop.height * scale))),
                        Image.Resampling.BILINEAR,
                    )
                    crop.close()
                    crop = smaller
                with BytesIO() as output:
                    crop.save(output, format="JPEG", quality=70)
                    encoded = bytearray(output.getvalue())
                if len(encoded) > 300000:
                    encoded[:] = b"\x00" * len(encoded)
                    return None
                while len(self._outstanding) >= 4:
                    self._outstanding.popleft().erase()
                inspected = InspectedCrop(frame_id, entry.bookmark.captured_ms,
                                         encoded, *crop.size)
                self._outstanding.append(inspected)
                self._counts["inspected"] += 1
                return inspected
            finally:
                crop.close()

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate counts only; never expose image data or frame identifiers."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "frames_cached": len(self._entries),
                    "bytes_cached": sum(len(entry.jpeg) for entry in self._entries),
                    "inspection_handles": len(self._outstanding)}


__all__ = ["RecallBookmark", "InspectedCrop", "VisualRecallHost"]
