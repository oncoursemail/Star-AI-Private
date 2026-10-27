"""Bounded CPU fingerprints of pixels already captured by an authorized host.

Edge (dHash) detects structure. Seven coarse tone/color bins also detect
uniform fades, HUD color changes, and similar-luminance color transitions that
dHash alone cannot see. Neither is image understanding or event verification.

No camera/screen access, model calls, persistence, network, or frame copies.
All signals are *heuristics* and can miss tiny text or unsampled UI changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

Region: TypeAlias = tuple[int, int, int, int]  # left, top, width, height
_FORMATS = {
    "GRAY": (1, None), "RGB": (3, (0, 1, 2)),
    "BGR": (3, (2, 1, 0)), "RGBA": (4, (0, 1, 2)),
    "BGRA": (4, (2, 1, 0)),
}
_MAX_RAW_BYTES = 64 * 1024 * 1024
_MAX_DIMENSION = 8192
_TONE_BITS = 42  # seven unsigned six-bit coarse statistics


@dataclass(frozen=True)
class VisualFingerprint:
    """64-bit edge fingerprint plus seven quantized color/luminance bins."""

    edge_hash: int
    tone_signature: int


def tone_distance(first: int, second: int) -> int:
    """Largest difference of any six-bit RGB/quad-luminance bin, 0..63."""
    if (type(first) is not int or type(second) is not int
            or not 0 <= first < 1 << _TONE_BITS
            or not 0 <= second < 1 << _TONE_BITS):
        raise ValueError("invalid 42-bit tone signatures")
    return max(
        abs(((first >> shift) & 63) - ((second >> shift) & 63))
        for shift in range(0, _TONE_BITS, 6)
    )


def visual_fingerprint(
    pixels: bytes | bytearray | memoryview, *, width: int, height: int,
    pixel_format: str = "BGRA", row_stride: int | None = None,
    region: Region | None = None,
) -> VisualFingerprint:
    """Return edge and color-aware signatures in ONE bounded pixel sampling pass.

    Processes 9x8 evenly spread positions, sampling a 2x2 square per position
    (<=288 pixels/ROI). Keeps only seven six-bit tone statistics and dHash.
    Alpha is intentionally ignored. Frame memory belongs to the caller.
    Small or unsampled changes may still be missed; never certify game events.
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

    xs = [left + min(rw - 1, ((2 * col + 1) * rw) // 18)
          for col in range(9)]
    ys = [top + min(rh - 1, ((2 * row + 1) * rh) // 16)
          for row in range(8)]
    right, bottom = left + rw - 1, top + rh - 1
    luminances: list[int] = []
    rgb_total = [0, 0, 0]
    quad_lum = [0, 0, 0, 0]
    quad_count = [0, 0, 0, 0]
    for row, y in enumerate(ys):
        for col, x in enumerate(xs):
            total_lum = 0
            quad = 2 * (row >= 4) + (col >= 4)
            for yy in (y, min(y + 1, bottom)):
                for xx in (x, min(x + 1, right)):
                    offset = yy * stride + xx * channels
                    if rgb_indices is None:
                        r = g = b = view[offset]
                    else:
                        ri, gi, bi = rgb_indices
                        r, g, b = (view[offset + ri], view[offset + gi],
                                   view[offset + bi])
                    rgb_total[0] += r
                    rgb_total[1] += g
                    rgb_total[2] += b
                    total_lum += 77 * r + 150 * g + 29 * b
            luminances.append(total_lum)
            quad_lum[quad] += total_lum
            quad_count[quad] += 4

    edge_hash = 0
    for row in range(8):
        start = row * 9
        for col in range(8):
            edge_hash = (edge_hash << 1) | int(
                luminances[start + col] > luminances[start + col + 1]
            )
    # 72 sample positions x 4 pixels. Divide each eight-bit average by 4
    # into robust, six-bit bins. Quads have 16/20 samples depending on column.
    tone_bins = [min(63, total // (72 * 4 * 4)) for total in rgb_total]
    tone_bins += [
        min(63, total // (count * 256 * 4))
        for total, count in zip(quad_lum, quad_count)
    ]
    tone_signature = 0
    for bin_value in tone_bins:
        tone_signature = (tone_signature << 6) | bin_value
    return VisualFingerprint(edge_hash, tone_signature)


def difference_hash(
    pixels: bytes | bytearray | memoryview, *, width: int, height: int,
    pixel_format: str = "BGRA", row_stride: int | None = None,
    region: Region | None = None,
) -> int:
    """Backward-compatible 64-bit edge hash; ignores absolute tone/color."""
    return visual_fingerprint(
        pixels, width=width, height=height, pixel_format=pixel_format,
        row_stride=row_stride, region=region,
    ).edge_hash


__all__ = [
    "Region", "VisualFingerprint", "visual_fingerprint", "difference_hash",
    "tone_distance",
]
