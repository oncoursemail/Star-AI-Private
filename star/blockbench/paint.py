"""Deterministic pixel-art face painters for Minecraft-style cuboid models.

Every face is painted on its own texel grid (1 texel per model unit times the model density) from a
hue-shifted ramp (palette.ramp). Patterns are clustered and structured (plank seams, stone cells,
fur strands, rivets) instead of per-pixel noise, there are no smooth gradients and no blur, and the
light comes from the top-left. Same inputs -> same pixels.
"""
from __future__ import annotations

import random
import zlib

from .palette import parse_hex, ramp

BASE = 3
KINDS = ("plain", "wood_planks", "log", "stone", "cobble", "brick", "metal", "gold", "cloth", "wool",
         "leather", "fur", "skin", "scales", "leaves", "glass", "glow", "crystal", "bone", "paper", "slime")
DECALS = ("eyes", "glow_eyes", "mouth", "nose", "spots", "stripe", "window", "keyhole", "button", "rune",
          "border", "belly", "teeth", "planks_cross")
NO_BEVEL = {"glass", "glow"}


class Face:
    """A w x h grid of ramp indices (int 0..5) or explicit RGBA tuples."""

    def __init__(self, w: int, h: int, fill=BASE):
        self.w, self.h = w, h
        self.px = [[fill] * w for _ in range(h)]

    def get(self, x, y):
        return self.px[y][x]

    def set(self, x, y, v):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = v

    def add(self, x, y, d):
        if 0 <= x < self.w and 0 <= y < self.h and isinstance(self.px[y][x], int):
            self.px[y][x] = max(0, min(5, self.px[y][x] + d))


def seed_of(*parts) -> int:
    return zlib.crc32("|".join(str(p) for p in parts).encode())


# ---- material patterns -------------------------------------------------------------------------

def _plain(f, role, rng, d):
    return


def _wood_planks(f, role, rng, d):
    ph = max(2, 4 * d)
    if f.h < ph:  # thin post or rail: grain streaks only, no plank seams
        for _ in range(max(1, f.w // 3)):
            y, x0 = rng.randrange(f.h), rng.randrange(max(1, f.w - 2))
            for x in range(x0, min(f.w, x0 + rng.randint(2, 4))):
                f.set(x, y, 2)
        return
    for y in range(f.h):
        row = y // ph
        if y % ph == ph - 1:
            for x in range(f.w):
                f.set(x, y, 1)
        elif y % ph == 0:
            for x in range(f.w):
                if rng.random() < 0.7:
                    f.set(x, y, 4)
    for row in range((f.h + ph - 1) // ph):
        if f.w >= 6:
            sx = (row * 5 + rng.randrange(f.w)) % f.w
            for y in range(row * ph, min(f.h, row * ph + ph - 1)):
                f.set(sx, y, 1)
                f.set(sx + 1, y, 4) if y % ph else None
        # grain streaks, 2-4 long, never single pixels
        for _ in range(max(1, f.w // 6)):
            y = row * ph + 1 + rng.randrange(max(1, ph - 2))
            x0 = rng.randrange(max(1, f.w - 3))
            for x in range(x0, min(f.w, x0 + rng.randint(2, 4))):
                if y < f.h and f.get(x, y) == BASE:
                    f.set(x, y, 2)


def _log(f, role, rng, d):
    if role != "side":
        cx, cy = (f.w - 1) / 2, (f.h - 1) / 2
        for y in range(f.h):
            for x in range(f.w):
                r = max(abs(x - cx), abs(y - cy))
                edge = max(cx, cy)
                if r > edge - 1:
                    f.set(x, y, 1)
                else:
                    f.set(x, y, 4 if int(r) % 3 == 1 else 3)
        return
    x = rng.randrange(3)
    while x < f.w:
        y = rng.randrange(2)
        while y < f.h:
            run = rng.randint(3, 6)
            for yy in range(y, min(f.h, y + run)):
                f.set(x, yy, 1)
                f.set(x + 1, yy, 4) if x + 1 < f.w else None
            y += run + rng.randint(1, 3)
        x += rng.randint(3, 4)


def _cells(f, rng, size, dark, two_tone=True):
    pts = []
    for gy in range(-1, f.h // size + 2):
        for gx in range(-1, f.w // size + 2):
            pts.append((gx * size + rng.uniform(0, size), gy * size + rng.uniform(0, size),
                        rng.choice((2, 3, 3, 4)) if two_tone else BASE))
    owner = [[0] * f.w for _ in range(f.h)]
    for y in range(f.h):
        for x in range(f.w):
            best, bi = 1e9, 0
            for i, (px, py, _) in enumerate(pts):
                dd = abs(px - x - 0.5) + abs(py - y - 0.5) * 1.25
                if dd < best:
                    best, bi = dd, i
            owner[y][x] = bi
            f.set(x, y, pts[bi][2])
    for y in range(f.h):
        for x in range(f.w):
            o = owner[y][x]
            if (x + 1 < f.w and owner[y][x + 1] != o) or (y + 1 < f.h and owner[y + 1][x] != o):
                f.set(x, y, dark)
            elif ((x > 0 and owner[y][x - 1] != o) or (y > 0 and owner[y - 1][x] != o)) and f.get(x, y) < 4:
                f.add(x, y, 1)


def _stone(f, role, rng, d):
    _cells(f, rng, 4 * d + 1, 1)


def _cobble(f, role, rng, d):
    _cells(f, rng, 5 * d, 0)


def _brick(f, role, rng, d):
    bh, bw = 4 * d, 8 * d
    for y in range(f.h):
        row = y // bh
        off = (bw // 2) if row % 2 else 0
        for x in range(f.w):
            if y % bh == bh - 1 or (x + off) % bw == bw - 1:
                f.set(x, y, 5)
            elif y % bh == 0:
                f.set(x, y, 4)
            elif y % bh == bh - 2:
                f.set(x, y, 2)


def _metal(f, role, rng, d, sparkle=False):
    if f.h >= 4:
        band = max(1, f.h // 4)
        for x in range(f.w):
            f.set(x, band, 5 if x % 7 not in (5, 6) else 4)
            f.set(x, band + 1, 4)
        for y in range(f.h - max(1, f.h // 4), f.h):
            for x in range(f.w):
                f.set(x, y, 2)
    if f.w >= 5 and f.h >= 5:
        for (x, y) in ((1, 1), (f.w - 2, 1), (1, f.h - 2), (f.w - 2, f.h - 2)):
            f.set(x, y, 5)
            f.set(x + 1, y + 1, 1) if x + 1 < f.w - 1 else None
    if sparkle and f.w >= 4 and f.h >= 4:
        for _ in range(max(1, f.w * f.h // 40)):
            x, y = rng.randrange(1, f.w - 1), rng.randrange(1, f.h - 1)
            f.set(x, y, 5)
            f.set(x + 1, y, 4)


def _gold(f, role, rng, d):
    _metal(f, role, rng, d, sparkle=True)


def _cloth(f, role, rng, d):
    """Soft padded fabric: darker rim, lit top-left cushion, a couple of fold creases."""
    if f.w >= 4 and f.h >= 3:
        for y in range(f.h):
            for x in range(f.w):
                if x in (0, f.w - 1) or y in (0, f.h - 1):
                    f.set(x, y, 2)
        for (x, y) in ((0, 0), (f.w - 1, 0), (0, f.h - 1), (f.w - 1, f.h - 1)):
            f.set(x, y, 1)
        for y in range(1, max(2, f.h // 2)):
            for x in range(1, max(2, f.w // 2)):
                if x + y < max(3, (f.w + f.h) // 4):
                    f.set(x, y, 4)
    for _ in range(max(0, (f.w * f.h) // 60)):
        x, y = rng.randrange(2, max(3, f.w - 2)), rng.randrange(2, max(3, f.h - 2))
        for i in range(rng.randint(2, 3)):
            f.set(x + i, y + (i if rng.random() < 0.3 else 0), 2)


def _wool(f, role, rng, d):
    for y in range(0, f.h, 2):
        for x in range(0, f.w, 2):
            v = rng.choice((2, 3, 3, 3, 4))
            for yy in (y, y + 1):
                for xx in (x, x + 1):
                    f.set(xx, yy, v)


def _leather(f, role, rng, d):
    if f.w >= 6 and f.h >= 6:
        for x in range(2, f.w - 2):
            if x % 2 == 0:
                f.set(x, 1, 5)
                f.set(x, f.h - 2, 5)
        for y in range(2, f.h - 2):
            if y % 2 == 0:
                f.set(1, y, 5)
                f.set(f.w - 2, y, 5)
    for _ in range(max(1, f.w * f.h // 50)):
        x, y = rng.randrange(f.w), rng.randrange(f.h)
        for i in range(rng.randint(2, 3)):
            f.set(x + i, y, 2)


def _fur(f, role, rng, d):
    """Short tufts: 2-3 px darker strokes with a light tip, sparse and clustered, never per-pixel noise."""
    n = max(1, f.w * f.h // 12)
    for _ in range(n):
        x, y = rng.randrange(f.w), rng.randrange(f.h)
        length = rng.randint(2, 3)
        f.set(x, y, 4)
        for i in range(1, length):
            f.set(x, y + i, 2)
    if role == "side" and f.h >= 4:
        for x in range(f.w):
            if rng.random() < 0.5:
                f.set(x, f.h - 2, 2)


def _skin(f, role, rng, d):
    return


def _scales(f, role, rng, d):
    sw, sh = 4 * d, 3 * d
    for y in range(f.h):
        row = y // sh
        off = sw // 2 if row % 2 else 0
        for x in range(f.w):
            lx, ly = (x + off) % sw, y % sh
            if ly == sh - 1 or lx == 0 and ly > 0:
                f.set(x, y, 1)
            elif ly == 0 and lx in (1, 2):
                f.set(x, y, 4)


def _leaves(f, role, rng, d):
    for y in range(f.h):
        for x in range(f.w):
            f.set(x, y, 2)
    for _ in range(max(2, f.w * f.h // 6)):
        x, y = rng.randrange(f.w), rng.randrange(f.h)
        t = rng.choice((3, 3, 4))
        f.set(x, y, t)
        f.set(x + 1, y, t)
        f.set(x, y + 1, 3)
    for _ in range(max(1, f.w * f.h // 20)):
        x, y = rng.randrange(f.w), rng.randrange(f.h)
        f.set(x, y, 0)
        f.set(x + 1, y, 1)


def _glass(f, role, rng, d):
    for y in range(f.h):
        for x in range(f.w):
            edge = x in (0, f.w - 1) or y in (0, f.h - 1)
            f.set(x, y, 4 if edge else (0, 0, 0, 0))
    if f.w >= 4 and f.h >= 4:
        for i in range(min(f.w, f.h) // 2):
            x, y = 1 + i + f.w // 4, f.h - 2 - i
            if 0 < x < f.w - 1 and 0 < y < f.h - 1:
                f.set(x, y, 5)


def _glow(f, role, rng, d):
    cx, cy = (f.w - 1) / 2, (f.h - 1) / 2
    for y in range(f.h):
        for x in range(f.w):
            r = max(abs(x - cx) / max(1, cx + 0.5), abs(y - cy) / max(1, cy + 0.5))
            f.set(x, y, 5 if r < 0.35 else (4 if r < 0.7 else 3))


def _crystal(f, role, rng, d):
    for y in range(f.h):
        for x in range(f.w):
            a = x * f.h - y * f.w
            if abs(a) < max(f.w, f.h) // 2 + 1:
                f.set(x, y, 5)
            else:
                f.set(x, y, 4 if a > 0 else 2)
    for x in range(f.w):
        f.set(x, f.h - 1, 1)


def _bone(f, role, rng, d):
    for _ in range(max(1, f.w * f.h // 30)):
        x, y = rng.randrange(f.w), rng.randrange(f.h)
        f.set(x, y, 2)
        f.set(x + 1, y, 2)


def _paper(f, role, rng, d):
    for y in range(2, f.h - 1, 2):
        x0 = 1 + rng.randrange(2)
        for x in range(x0, max(x0, f.w - 1 - rng.randrange(3))):
            f.set(x, y, 2)


def _slime(f, role, rng, d):
    if f.w >= 4 and f.h >= 4:
        f.set(1, 1, 5)
        f.set(2, 1, 5)
        f.set(1, 2, 4)
        for x in range(f.w):
            f.set(x, f.h - 1, 2)


PATTERNS = {
    "plain": _plain, "wood_planks": _wood_planks, "log": _log, "stone": _stone, "cobble": _cobble,
    "brick": _brick, "metal": _metal, "gold": _gold, "cloth": _cloth, "wool": _wool, "leather": _leather,
    "fur": _fur, "skin": _skin, "scales": _scales, "leaves": _leaves, "glass": _glass, "glow": _glow,
    "crystal": _crystal, "bone": _bone, "paper": _paper, "slime": _slime,
}
assert set(PATTERNS) == set(KINDS)


def _bevel(f, role):
    if f.w < 3 or f.h < 3:
        return
    if role == "bottom":
        for y in range(f.h):
            for x in range(f.w):
                f.add(x, y, -1)
        return
    for x in range(f.w):
        f.add(x, 0, 1)
        f.add(x, f.h - 1, -1)
    if role == "side" and f.w >= 6:
        for y in range(1, f.h - 1):
            f.add(f.w - 1, y, -1)


# ---- decals --------------------------------------------------------------------------------------

def _rgba(hexcolor, k=BASE):
    return ramp(hexcolor)[k]


def _decal(f, kind, color, mat_ramp, rng):
    w, h = f.w, f.h
    c = color
    if kind in ("eyes", "glow_eyes"):
        if w < 3 or h < 3:
            return
        ew = 2 if w >= 7 else 1
        y = max(1, min(h - 2, round(h * 0.42)))
        gap = max(1, round(w * 0.18))
        lx = w // 2 - gap - ew
        rx = w - lx - ew
        lx, rx = max(0, lx), min(w - ew, rx)
        for x0, inner_right in ((lx, True), (rx, False)):
            for i in range(ew):
                if kind == "glow_eyes":
                    f.set(x0 + i, y, _rgba(c or "#d846ff", 5 if i == 0 else 4))
                else:
                    pupil = (i == ew - 1) if inner_right else (i == 0)
                    if ew == 1:
                        f.set(x0, y, _rgba(c or "#1c1a24", 3))
                    else:
                        f.set(x0 + i, y, _rgba(c or "#1c1a24", 3) if pupil else (236, 236, 236, 255))
    elif kind == "mouth":
        y = min(h - 1, round(h * 0.75))
        mw = max(2, w // 3)
        for x in range((w - mw) // 2, (w - mw) // 2 + mw):
            f.set(x, y, _rgba(c, 1) if c else mat_ramp[0])
    elif kind == "teeth":
        y = min(h - 1, round(h * 0.75))
        mw = max(2, w // 3)
        for i, x in enumerate(range((w - mw) // 2, (w - mw) // 2 + mw)):
            f.set(x, y, (232, 228, 214, 255) if i % 2 == 0 else mat_ramp[0])
    elif kind == "nose":
        y = min(h - 1, round(h * 0.6))
        x = w // 2 - 1
        for xx in (x, x + 1):
            f.set(xx, y, _rgba(c, 2) if c else mat_ramp[1])
        if w >= 6 and h >= 6:
            f.set(x, y + 1, _rgba(c, 0) if c else mat_ramp[0])
            f.set(x + 1, y + 1, _rgba(c, 0) if c else mat_ramp[0])
    elif kind == "spots":
        r = ramp(c or "#3a2a20")
        for _ in range(max(1, w * h // 24)):
            x, y = rng.randrange(1, max(2, w - 2)), rng.randrange(1, max(2, h - 2))
            for dx, dy, k in ((0, 0, 3), (1, 0, 3), (0, 1, 2), (1, 1, 2)):
                f.set(x + dx, y + dy, r[k])
    elif kind == "stripe":
        r = ramp(c or "#c03030")
        y0 = h // 2 - 1
        for x in range(w):
            f.set(x, y0, r[4])
            f.set(x, y0 + 1, r[2])
    elif kind == "window":
        if w < 5 or h < 5:
            return
        r = ramp(c or "#9ad0e6")
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                edge = x in (1, w - 2) or y in (1, h - 2)
                f.set(x, y, mat_ramp[1] if edge else r[3])
        f.set(2, 2, r[5])
        f.set(3, 2, r[4]) if w > 5 else None
    elif kind == "keyhole":
        x, y = w // 2, h // 2
        k = _rgba(c or "#141018", 3)
        f.set(x, y - 1, k)
        f.set(x, y, k)
    elif kind == "button":
        r = ramp(c or "#c8a040")
        x, y = w // 2 - 1, h // 2 - 1
        for dx, dy, k in ((0, 0, 5), (1, 0, 4), (0, 1, 3), (1, 1, 1)):
            f.set(x + dx, y + dy, r[k])
    elif kind == "rune":
        r = ramp(c or "#58e0ff")
        x, y = w // 2 - 1, h // 2 - 1
        for dx, dy in ((1, 0), (0, 1), (1, 1), (2, 1), (1, 2)):
            f.set(x + dx, y + dy, r[5] if (dx, dy) == (1, 1) else r[4])
    elif kind == "border":
        r = ramp(c) if c else mat_ramp
        for x in range(w):
            f.set(x, 0, r[4])
            f.set(x, h - 1, r[1])
        for y in range(1, h - 1):
            f.set(0, y, r[3])
            f.set(w - 1, y, r[2])
    elif kind == "belly":
        r = ramp(c) if c else None
        x0, x1 = w // 4, w - w // 4
        y0, y1 = h // 3, h - 1
        for y in range(y0, y1):
            for x in range(x0, x1):
                if r:
                    f.set(x, y, r[4 if y == y0 else 3])
                else:
                    f.add(x, y, 1)
    elif kind == "planks_cross":
        for i in range(min(w, h)):
            f.set(i, i, mat_ramp[1])
            f.set(w - 1 - i, i, mat_ramp[1])


def paint_face(material: dict, role: str, w: int, h: int, *, density: int = 1, seed: int = 0,
               decals=()) -> list[list[tuple[int, int, int, int]]]:
    """Return an h x w RGBA grid for one face. role: side | top | bottom."""
    kind = material.get("kind", "plain")
    if kind not in PATTERNS:
        kind = "plain"
    r = ramp(material["color"], contrast=float(material.get("contrast", 1.0)))
    rng = random.Random(seed)
    transpose = ((kind in ("wood_planks", "scales", "brick") and h > w * 1.3)
                 or (kind == "log" and role == "side" and w > h * 1.3))
    f = Face(h, w) if transpose else Face(w, h)
    PATTERNS[kind](f, role, rng, max(1, int(density)))
    if transpose:
        t = Face(w, h)
        t.px = [[f.px[x][y] for x in range(w)] for y in range(h)]
        f = t
    if kind not in NO_BEVEL:
        _bevel(f, role)
    for dec in decals or ():
        color = dec.get("color")
        if color:
            parse_hex(color)
        _decal(f, dec.get("kind"), color, r, random.Random(seed ^ 0x5bd1))
    out = []
    for row in f.px:
        out.append([r[v] if isinstance(v, int) else tuple(v) for v in row])
    return out
