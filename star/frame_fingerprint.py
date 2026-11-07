"""Tiny CPU-only, read-only fingerprint of an already authorized game frame.

The embedding Windows/OBS/Studio host owns capture and permission checks.
This module accepts *raw pixels already held by that host*; it never touches a
screen, network, file, GPU, player input, or speech stream. Only 64-bit hashes
are returned. No frame bytes survive the call.

The relative-luminance difference hash is a cheap visual-novelty heuristic,
NOT an object detector, an objective verification, a privacy anonymizer, or
a cryptographic hash. A uniform color shift or a small text/HUD change may
remain undetected. Independent event/success verification remains required.
"""
from __future__ import annotations

from typing import TypeAlias

Region: TypeAlias = tuple[int, int, int, int]  # left, top, width, height
_FORMATS = {"GRAY": (1, None), "RGB": (3, (0, 1, 2)),
            "BGR": (3, (2, 1, 0)), "RGBA": (4, (0, 1, 2)),
            "BGRA": (4, (2, 1, 0))}
_MAX_RAW_BYTES = 64 * 1024 * 1024
_MAX_DIMENSION = 8192


def difference_hash(
    pixels: bytes | bytearray | memoryview, *, width: int, height: int,
    pixel_format: str = "BGRA", row_stride: int | None = None,
    region: Region | None = None,
) -> int:
    """Compute a 64-bit luminance difference hash without decoding or copying.

    Nine columns by eight rows of tiny 2x2 luminance samples are compared
    horizontally. A game-view ROI can ignore overlays; an additional HUD ROI
    should be separately fingerprinted if small UI changes also matter.

    Input is tightly packed or padded 8-bit GRAY/RGB/BGR/RGBA/BGRA, with
    top-to-bottom positive row stride. Region bounds are half-open. The
    caller must *not* pass untrusted dimensions or pixels from a model tool.
    All work is bounded (at most 288 sampled pixels irrespective of 4K size).
    """
    if type(width) is not int or type(height) is not int:
        raise ValueError("pixel dimensions must be integers")
    if not 9 <= width <= _MAX_DIMENSION or not 8 <= height <= _MAX_DIMENSION:
        raise ValueError("pixel dimensions must be 9..8192 wide and 8..8192 tall")
    if type(pixel_format) is not str or pixel_format not in _FORMATS:
        raise ValueError("unsupported pixel format")
    if not isinstance(pixels, (bytes, bytearray, memoryview)):
        raise TypeError("pixels must be a raw contiguous byte buffer")
    try:
        view = memoryview(pixels).cast("B")
    except (TypeError, ValueError) as exc:
        raise ValueError("pixels must be a contiguous 8-bit byte buffer") from exc
    channels, rgb_indices = _FORMATS[pixel_format]
    packed = width * channels
    stride = packed if row_stride is None else row_stride
    if type(stride) is not int or stride < packed or stride > _MAX_RAW_BYTES:
        raise ValueError("invalid row stride")
    minimum = (height - 1) * stride + packed
    maximum = height * stride
    if (minimum > _MAX_RAW_BYTES or maximum > _MAX_RAW_BYTES
            or not minimum <= len(view) <= maximum):
        raise ValueError("pixel buffer length or allocation exceeds limit")

    if region is None:
        left, top, rw, rh = 0, 0, width, height
    else:
        if (type(region) is not tuple or len(region) != 4
                or any(type(part) is not int for part in region)):
            raise ValueError("region must be a four-integer crop")
        left, top, rw, rh = region
        if (left < 0 or top < 0 or rw < 9 or rh < 8
                or left + rw > width or top + rh > height):
            raise ValueError("region outside frame or too small")

    # Pixel center selection samples the same normalized scene when the host
    # changes capture resolution; the extra neighboring samples smooth
    # isolated sensor noise. No full-frame transform or allocation occurs.
    xs = [left + min(rw - 1, ((2 * col + 1) * rw) // 18)
          for col in range(9)]
    ys = [top + min(rh - 1, ((2 * row + 1) * rh) // 16)
          for row in range(8)]
    luminances: list[int] = []
    right = left + rw - 1
    bottom = top + rh - 1
    for y in ys:
        for x in xs:
            total = 0
            for yy in (y, min(y + 1, bottom)):
                for xx in (x, min(x + 1, right)):
                    offset = yy * stride + xx * channels
                    if rgb_indices is None:
                        total += view[offset] * 256
                    else:
                        red, green, blue = rgb_indices
                        total += (77 * view[offset + red]
                                  + 150 * view[offset + green]
                                  + 29 * view[offset + blue])
            luminances.append(total)

    fingerprint = 0
    for row in range(8):
        start = row * 9
        for col in range(8):
            fingerprint = (fingerprint << 1) | int(
                luminances[start + col] > luminances[start + col + 1]
            )
    return fingerprint


__all__ = ["Region", "difference_hash"]
