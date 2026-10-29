"""Hue-shifted colour ramps for Minecraft-style pixel art.

Hand-made pixel art shades with a small ramp per material: shadows drift toward blue/purple and gain
saturation, highlights drift toward yellow and lose saturation. Flat value-only darkening is one of the
clearest "generated" tells, so every material in this package is painted from a ramp built here.
"""
from __future__ import annotations

import colorsys
import re

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
STEPS = (-3, -2, -1, 0, 1, 2)  # index 3 is the base colour


def parse_hex(value: str) -> tuple[int, int, int]:
    m = _HEX.match(str(value).strip())
    if not m:
        raise ValueError(f"colour must be #rrggbb, got {value!r}")
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb[:3])


def _shift_hue(h: float, target: float, amount: float) -> float:
    d = ((target - h + 0.5) % 1.0) - 0.5
    step = max(-amount, min(amount, d))
    return (h + step) % 1.0


def ramp(base: str, *, contrast: float = 1.0) -> list[tuple[int, int, int, int]]:
    """Six RGBA tones for steps -3..+2; index 3 is the base colour unchanged."""
    r, g, b = (c / 255.0 for c in parse_hex(base))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    grey = s < 0.08
    out = []
    for k in STEPS:
        if k == 0:
            out.append((round(r * 255), round(g * 255), round(b * 255), 255))
            continue
        kk = k * contrast
        if k < 0:
            nv = v * (1.0 - 0.17 * -kk)
            ns = min(1.0, s + (0.03 if grey else 0.07) * -kk)
            nh = _shift_hue(h, 0.68, 0.025 * -kk) if not grey else 0.66
        else:
            nv = min(1.0, v + (1.0 - v) * 0.22 * kk + 0.04 * kk)
            ns = max(0.0, s - 0.09 * kk)
            nh = _shift_hue(h, 0.14, 0.022 * kk) if not grey else 0.13
            if grey:
                ns = min(ns, 0.05)
        rr, gg, bb = colorsys.hsv_to_rgb(nh, ns, max(0.0, nv))
        out.append((round(rr * 255), round(gg * 255), round(bb * 255), 255))
    return out


def luminance(rgb) -> float:
    r, g, b = (c / 255.0 for c in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def distance(a, b) -> float:
    """Cheap perceptual distance (redmean), 0..~765."""
    rm = (a[0] + b[0]) / 2.0
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5
