"""Themed kit library: aquarium, theme park, coast, museum, subway, obby, camp/winter, Japanese garden,
hospital/library and beach kits on top of the core kits in kits.py.

Same contract as kits.py: `fn(ctx, **params) -> list[part]` in LOCAL space (origin on the floor centre, y = 0 is the
floor top, front faces -Z, back +Z), sizes in studs against a 5-stud character, registered with @kit so the scene
compiler and the LLM catalogue see them. Importing this module registers the kits.
"""
from __future__ import annotations

import math

from .geom import SHAPES, STYLES, Ctx, _angles, _mul, aabb, light, mix, part, rot_matrix, shade, transform
from .kits import KITS, _abandoned, _cyl_y, _ring, build_kit, chair, cobweb, crate, kit, lamp_post, papers

WHITE = (240, 238, 232)
BLACK = (34, 32, 32)
GOLD = (212, 170, 80)
BRASS = (190, 150, 70)
BONE = (226, 214, 186)
VERMILION = (196, 62, 40)
SAFETY = (245, 205, 48)
STEEL = (186, 190, 196)


# =========================================================================== helpers

def _hi(ctx) -> bool:
    return ctx.style == "highpoly"


def _round(ctx) -> bool:
    return ctx.style in ("midpoly", "highpoly")


def _stud(ctx) -> bool:
    return ctx.style == "stud"


def _sn(ctx, v):
    """Snap big dimensions to whole studs in the stud style; thin parts stay thin."""
    if ctx.style == "stud" and v >= 0.75:
        return max(1, round(v))
    return v


def _col(ctx, rgb, mat=""):
    """An explicit colour that still gets the abandoned grime (ctx.color does this for roles/materials)."""
    if ctx.state == "abandoned" and mat not in ("neon", "glass", "water"):
        return mix(rgb, (90, 86, 80), 0.25)
    return rgb


def _lit(ctx) -> bool:
    """Is this light on? new: all, worn: most, abandoned: a few."""
    if ctx.state == "abandoned":
        return ctx.rng.random() < 0.25
    if ctx.state == "worn":
        return ctx.rng.random() < 0.9
    return True


def _rise_x(rise, run):
    """Angles rx that tilts a flat slab so its +Z (back) end is `rise` higher over `run`."""
    return -math.degrees(math.atan2(rise, run))


def _beam(ctx, a, b, sx, sz=None, shape="B", ext=0.0, **kw):
    """A block (long axis local Y) or cylinder from point a to point b."""
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    ln = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.05
    ux, uy, uz = dx / ln, dy / ln, dz / ln
    rz = -math.degrees(math.asin(max(-1.0, min(1.0, ux))))
    rx = math.degrees(math.atan2(uz, uy))
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
    if shape == "C":
        return part(ctx, "C", (ln + ext, sx, sx), mid, rot=(rx, 0, rz + 90), **kw)
    return part(ctx, "B", (sx, ln + ext, sz if sz is not None else sx), mid, rot=(rx, 0, rz), **kw)


def _up(ctx, d, h, pos, **kw):
    """Upright pole/post: square in stud, turned square in lowpoly, cylinder in the round styles."""
    if ctx.style == "stud":
        return part(ctx, "B", (d, h, d), pos, **kw)
    if ctx.style == "lowpoly":
        return part(ctx, "B", (d * 0.9, h, d * 0.9), pos, rot=(0, 45, 0), **kw)
    return _cyl_y(ctx, d, h, pos, **kw)


def _prism(ctx, d, h, pos, **kw) -> list:
    """Round slab/drum: an octagon of two blocks in stud/lowpoly, a cylinder in the round styles."""
    if ctx.style in ("stud", "lowpoly"):
        s = _sn(ctx, d * 0.924)
        return [part(ctx, "B", (s, h, s), pos, **kw), part(ctx, "B", (s, h, s), pos, rot=(0, 45, 0), **kw)]
    return [_cyl_y(ctx, d, h, pos, **kw)]


def _ball(ctx, size, pos, **kw):
    if ctx.style == "stud":
        return part(ctx, "B", tuple(_sn(ctx, v) for v in size), pos, **kw)
    if ctx.style == "lowpoly":
        return part(ctx, "B", tuple(v * 0.85 for v in size), pos, rot=(0, 45, 0), **kw)
    return part(ctx, "S", size, pos, **kw)


def _cone(ctx, r, y0, rise, n, cols, mat="fabric", square=False, **kw) -> list:
    """Cone/pyramid roof of wedge facets (alternating colours = stripes); stepped tiers in the stud style."""
    out = []
    if ctx.style == "stud":
        tiers = max(2, min(4, int(round(rise))))
        th = rise / tiers
        for i in range(tiers):
            d = 2 * r * (1 - i / tiers)
            pos = (0, y0 + th * (i + 0.5), 0)
            c = cols[i % len(cols)]
            if square:
                out.append(part(ctx, "B", (_sn(ctx, d), th, _sn(ctx, d)), pos, mat=mat, color=c, **kw))
            else:
                out += _prism(ctx, d, th, pos, mat=mat, color=c, **kw)
        return out
    if square:
        n = 4
    w = 2 * r * math.tan(math.pi / n) * 1.02
    for i in range(n):
        a = 2 * math.pi * i / n
        out.append(part(ctx, "W", (w, rise, r), (math.sin(a) * r / 2, y0 + rise / 2, math.cos(a) * r / 2),
                        rot=(0, math.degrees(a) + 180, 0), mat=mat, color=cols[i % len(cols)], **kw))
    return out


def _rotate_group(parts, pivot, rx=0.0, ry=0.0, rz=0.0):
    """Rotate already-built parts as one rigid group about `pivot` (world-frame Angles rx, ry, rz)."""
    m = rot_matrix(rx, ry, rz)
    px, py, pz = pivot
    for p in parts:
        x, y, z = p["p"][0] - px, p["p"][1] - py, p["p"][2] - pz
        p["p"] = [round(m[i][0] * x + m[i][1] * y + m[i][2] * z + (px, py, pz)[i], 3) for i in range(3)]
        r = list(_angles(_mul(m, rot_matrix(*p.get("r", (0, 0, 0))))))
        if any(r):
            p["r"] = r
        else:
            p.pop("r", None)
    return parts


def _ground(p):
    """Drop a loose (rotated) part so its lowest point rests on the floor."""
    p["p"][1] = round(p["p"][1] - aabb(p)[0][1], 3)
    return p


def _text(p):
    p["text"] = True     # the compiler puts the scene's sign text on it (SurfaceGui), like kits.sign
    return p


def _fish(ctx, s, color):
    """One fish facing +X at the origin (s = body length)."""
    if ctx.style == "stud":
        body = part(ctx, "B", (s, s * 0.5, s * 0.3), (0, 0, 0), color=color, collide=False)
    elif ctx.style == "lowpoly":
        body = part(ctx, "B", (s, s * 0.4, s * 0.4), (0, 0, 0), rot=(45, 0, 0), color=color, collide=False)
    else:
        body = part(ctx, "S", (s, s * 0.5, s * 0.28), (0, 0, 0), color=color, collide=False)
    out = [body, part(ctx, "W", (s * 0.08, s * 0.5, s * 0.35), (-s * 0.62, 0, 0), rot=(0, -90, 0),
                      color=shade(color, 0.85), collide=False)]
    if _hi(ctx):
        out.append(part(ctx, "W", (s * 0.06, s * 0.22, s * 0.35), (-s * 0.05, s * 0.3, 0), rot=(0, -90, 0),
                        color=shade(color, 0.85), collide=False))
    return out


# =========================================================================== aquarium

@kit("aquarium_tank", "wall aquarium on a cabinet: frame, glass front, water, sand, rocks, seaweed, fish (back at +Z)",
     {"w": (10, 4, 30), "h": (6, 3, 14), "d": (3, 2, 8), "base": (3, 0, 6)}, footprint=(10, 4), tags=("aquarium",))
def aquarium_tank(ctx, w, h, d, base):
    rng, ab = ctx.rng, _abandoned(ctx)
    w, h, d = _sn(ctx, w), _sn(ctx, h), _sn(ctx, d)
    base = _sn(ctx, base) if base >= 0.75 else 0
    trim = ctx.color("metal", "trim")
    out = []
    if base:
        out.append(part(ctx, "B", (w + 0.6, base, d + 0.6), (0, base / 2, 0), mat="wood", role="secondary", vary=0.03))
        if _round(ctx) and base >= 1.5:
            for sx in (-1, 1):
                out.append(part(ctx, "B", (w / 2 - 0.5, base - 0.8, 0.12), (sx * w / 4, base / 2, -d / 2 - 0.33), mat="wood",
                                color=shade(ctx.color("wood", "secondary"), 1.1)))
                out.append(part(ctx, "B", (0.15, 0.6, 0.15), (sx * 0.5, base / 2, -d / 2 - 0.45), mat="metal",
                                color=_col(ctx, BRASS), collide=False))
    iy = base + 0.4
    out.append(part(ctx, "B", (w + 0.4, 0.4, d + 0.4), (0, base + 0.2, 0), mat="metal", color=trim))
    out.append(part(ctx, "B", (w + 0.4, 0.7, d + 0.4), (0, iy + h + 0.35, 0), mat="metal", color=trim))
    for sx in (-1, 1):
        for sz in (-1, 1):
            out.append(part(ctx, "B", (0.3, h, 0.3), (sx * (w / 2 + 0.05), iy + h / 2, sz * (d / 2 + 0.05)), mat="metal",
                            color=trim))
    out.append(part(ctx, "B", (w, h, 0.15), (0, iy + h / 2, d / 2 - 0.08), mat="paint", color=_col(ctx, (24, 62, 86))))
    out.append(part(ctx, "B", (w - 0.2, 0.6, d - 0.3), (0, iy + 0.3, 0), mat="sand", vary=0.03))
    if _round(ctx):   # sand banked up towards the back, the classic aquascape slope
        out.append(part(ctx, "W", (w - 0.2, 0.9, d * 0.45), (0, iy + 1.05, d / 2 - 0.15 - d * 0.225), mat="sand",
                        collide=False))
    level = h * {"new": 0.92, "worn": 0.86}.get(ctx.state, 0.45)
    out.append(part(ctx, "B", (w - 0.2, level - 0.6, d - 0.3), (0, iy + 0.6 + (level - 0.6) / 2, 0), mat="water",
                    color=(60, 150, 180) if not ab else (84, 112, 66), t=0.55, collide=False, cast=False))
    out.append(part(ctx, "B", (w, h, 0.12), (0, iy + h / 2, -d / 2), mat="glass",
                    color=(200, 230, 240) if not ab else (150, 170, 140), t=0.72 if not ab else 0.45))
    # rock cluster in the left third, one lone stone on the right
    rx = -w * 0.28
    big = min(h * 0.4, d * 0.55)
    for i, (dx, dz, f) in enumerate(((0, 0.1, 1.0), (big * 0.7, -0.2, 0.55), (-big * 0.6, 0.25, 0.45), (w * 0.45, 0.2, 0.4))):
        s = big * f
        pos = (rx + dx, iy + 0.6 + s * 0.3, dz * d * 0.3)
        if ctx.style == "stud":
            out.append(part(ctx, "B", (_sn(ctx, s), _sn(ctx, s * 0.7), _sn(ctx, s * 0.8)), pos, mat="rock"))
        elif ctx.style == "lowpoly":
            out.append(part(ctx, "B", (s, s * 0.7, s * 0.8), pos, rot=(rng.uniform(-15, 15), rng.uniform(0, 90), rng.uniform(-15, 15)),
                            mat="rock", vary=0.08))
        else:
            out.append(part(ctx, "S" if i % 2 == 0 else "B", (s, s * 0.7, s * 0.8), pos, rot=(rng.uniform(-10, 10), rng.uniform(0, 90), 0),
                            mat="rock", vary=0.1))
    # seaweed: one clump behind the rocks, one in the back-right corner
    weed = (60, 130, 70) if not ab else (110, 96, 60)
    nweed = {"stud": 3, "lowpoly": 4, "midpoly": 6, "highpoly": 9}[ctx.style]
    segs = {"stud": 1, "lowpoly": 1, "midpoly": 2, "highpoly": 3}[ctx.style]
    for i in range(nweed):
        cx = rx + rng.uniform(-big * 0.6, big * 0.6) if i < nweed * 0.6 else w * 0.38 + rng.uniform(-0.6, 0.6)
        cx = max(-w / 2 + 0.4, min(w / 2 - 0.4, cx))
        cz = d * 0.25 + rng.uniform(-0.2, 0.2)
        hh = (level - 0.6) * rng.uniform(0.45, 0.9) * (0.5 if ab else 1)
        sh = hh / segs
        for k in range(segs):
            sway = ((k % 2) * 2 - 1) * 8 if segs > 1 else rng.uniform(-6, 6)
            out.append(part(ctx, "B", (0.4 if _stud(ctx) else 0.3, sh * 1.05, 0.2 if _stud(ctx) else 0.12),
                            (cx + (0.12 * sway / 8 if segs > 1 else 0), iy + 0.6 + sh * (k + 0.5), cz), rot=(0, 0, sway),
                            mat="foliage", color=shade(weed, 1 + 0.06 * k), collide=False))
    if not ab:   # a school heading one way, one straggler the other way
        nf = {"stud": 3, "lowpoly": 4, "midpoly": 5, "highpoly": 7}[ctx.style]
        cols = [(255, 140, 40), (250, 210, 60), ctx.color("plastic", "accent")]
        fy = iy + 0.6 + (level - 0.6) * 0.55
        for i in range(nf):
            f = _fish(ctx, rng.uniform(0.5, 0.8), cols[i % 3])
            pos = (max(-w / 2 + 0.8, min(w / 2 - 0.8, w * 0.12 + rng.gauss(0, w * 0.08))), fy + rng.uniform(-0.4, 0.4),
                   rng.uniform(-d * 0.2, d * 0.15))
            out += transform(f, pos, 180 if i == nf - 1 else rng.uniform(-15, 15))
        out.append(part(ctx, "B", (w * 0.8, 0.12, d * 0.35), (0, iy + h - 0.06, -d * 0.1), mat="neon", color=(190, 230, 255),
                        collide=False, light=light("surface", (170, 220, 255), 1.0, 12, angle=110, face="Bottom", shadows=False)))
    else:   # one fish belly-up at the surface
        f = _rotate_group(_fish(ctx, 0.6, (200, 190, 160)), (0, 0, 0), rx=180)
        out += transform(f, (w * 0.2, iy + level - 0.1, 0), 20)
    if _hi(ctx) and not ab:
        bx = w * 0.36
        out.append(part(ctx, "B", (0.5, 0.3, 0.5), (bx, iy + 0.75, 0.1), mat="rock", color=(90, 90, 96)))
        for k in range(5):
            out.append(part(ctx, "S", (0.22, 0.22, 0.22), (bx + 0.1 * (k % 2), iy + 0.9 + k * (level - 1.0) / 5, 0.1), mat="glass",
                            color=(230, 245, 255), t=0.4, collide=False, cast=False))
    if ab:   # cracks radiating from one impact point on the glass
        cx0, cy0 = w * 0.15, iy + h * 0.6
        for a in (20, 75, 140, 200, 300):
            ln = rng.uniform(0.8, min(w, h) * 0.35)
            out.append(part(ctx, "B", (ln, 0.06, 0.05), (cx0 + math.cos(math.radians(a)) * ln / 2, cy0 + math.sin(math.radians(a)) * ln / 2,
                            -d / 2 - 0.09), rot=(0, 0, a), color=(230, 236, 232), t=0.3, collide=False, cast=False))
    if ctx.state != "new":   # algae creeps from the bottom corners
        for k in range(3 if ab else 1):
            sx = -1 if k % 2 == 0 else 1
            aw = min(rng.uniform(0.8, 1.6) * (1.5 if ab else 1), w / 3)
            out.append(part(ctx, "B", (aw, aw * 0.7, 0.05), (sx * (w / 2 - aw / 2 - 0.1), iy + 0.6 + aw * 0.35 + k * 0.3, -d / 2 + 0.1),
                            color=(70, 110, 50), t=0.35, collide=False, cast=False))
    return out


@kit("fish_school", "small school of fish swimming the same way (place in water; y = centre height)",
     {"n": (7, 3, 16), "y": (4, 0, 30), "size": (0.8, 0.3, 3)}, footprint=(4, 3), tags=("aquarium",))
def fish_school(ctx, n, y, size):
    rng = ctx.rng
    pal = [(255, 140, 40), (250, 210, 60), (176, 190, 200), ctx.color("plastic", "accent")]
    main = rng.choice(pal)
    odd = rng.choice([c for c in pal if c != main])
    if _abandoned(ctx):
        main, odd = mix(main, (120, 120, 110), 0.5), mix(odd, (120, 120, 110), 0.5)
    count = int(n) if not _abandoned(ctx) else max(2, int(n) // 2)
    spread = size * (1.2 + count * 0.12)
    out = []
    for i in range(count):
        f = _fish(ctx, size * rng.uniform(0.85, 1.15), odd if i == count - 1 else main)
        pos = (rng.gauss(0, spread), y + rng.gauss(0, spread * 0.35), rng.gauss(0, spread * 0.7))
        out += transform(f, pos, rng.uniform(-12, 12))
    return out


@kit("coral", "coral cluster on a rock (branch / brain / fan / mixed); bleached when abandoned",
     {"w": (3, 1, 10), "kind": ("mixed", ["mixed", "branch", "brain", "fan"])}, footprint=(3, 3), tags=("aquarium", "nature"))
def coral(ctx, w, kind):
    rng, ab = ctx.rng, _abandoned(ctx)
    bleach = (222, 216, 204)
    pink = ctx.color("plastic", "accent") if not ab else bleach
    orange = _col(ctx, (255, 150, 80)) if not ab else bleach
    purple = _col(ctx, (150, 90, 190)) if not ab else shade(bleach, 0.92)
    out = [_ball(ctx, (w * 0.7, w * 0.35, w * 0.55), (0, w * 0.12, 0), mat="rock", vary=0.08)]
    top = w * 0.28
    kinds = ("branch", "brain", "fan") if kind == "mixed" else (kind,)
    spots = {"branch": (-w * 0.18, -w * 0.05), "brain": (w * 0.18, -w * 0.1), "fan": (w * 0.05, w * 0.15)}
    if kind != "mixed":
        spots = {kind: (0, 0)}
    shp = "C" if _round(ctx) else "B"
    for k in kinds:
        bx, bz = spots[k]
        if k == "branch":
            nb = {"stud": 2, "lowpoly": 3, "midpoly": 4, "highpoly": 6}[ctx.style]
            for i in range(nb):
                a = 2 * math.pi * i / nb + rng.uniform(-0.3, 0.3)
                hh = w * rng.uniform(0.35, 0.6)
                base = (bx, top, bz)
                tip = (bx + math.sin(a) * w * 0.15, top + hh, bz + math.cos(a) * w * 0.15)
                out.append(_beam(ctx, base, tip, max(0.15, w * 0.07), shape=shp, mat="plastic", color=pink, collide=False))
                if _round(ctx):
                    mid = tuple(base[j] + (tip[j] - base[j]) * 0.6 for j in range(3))
                    side = (mid[0] + math.cos(a) * w * 0.12, mid[1] + hh * 0.3, mid[2] - math.sin(a) * w * 0.12)
                    out.append(_beam(ctx, mid, side, max(0.12, w * 0.05), shape=shp, mat="plastic", color=pink, collide=False))
        elif k == "brain":
            s = w * 0.4
            out.append(_ball(ctx, (s, s * 0.7, s), (bx, top + s * 0.2, bz), mat="plastic", color=orange, collide=False))
            if _hi(ctx):
                for j in range(3):
                    out.append(part(ctx, "B", (s * 0.9, 0.08, 0.1), (bx, top + s * 0.52, bz - s * 0.25 + j * s * 0.25),
                                    rot=(0, 0, 0), color=shade(orange, 0.8), collide=False))
        else:
            fw = w * 0.55
            out.append(part(ctx, "B", (fw, fw * 1.1, 0.1), (bx, top + fw * 0.5, bz), rot=(0, rng.uniform(-20, 20), rng.uniform(-8, 8)),
                            mat="plastic", color=purple, t=0.1, collide=False))
            if _round(ctx):
                for j in (-1, 1):
                    out.append(part(ctx, "B", (0.08, fw * 0.9, 0.12), (bx + j * fw * 0.2, top + fw * 0.45, bz), rot=(0, 0, -j * 15),
                                    color=shade(purple, 0.8), collide=False))
    return out


@kit("tunnel_tank", "walk-through aquarium tunnel segment along Z: arched glass, steel ribs, water, sand banks and sea life",
     {"length": (16, 8, 48), "r": (7, 5, 12)}, footprint=(20, 16), tags=("aquarium",))
def tunnel_tank(ctx, length, r):
    rng, ab = ctx.rng, _abandoned(ctx)
    L, r = _sn(ctx, length), _sn(ctx, r)
    n = {"stud": 6, "lowpoly": 6, "midpoly": 8, "highpoly": 12}[ctx.style]
    trim = ctx.color("metal", "trim")
    out = [part(ctx, "B", (2 * r, 0.3, L), (0, 0.15, 0), mat="tile", color=_col(ctx, (50, 56, 64)))]
    cyan = (90, 220, 255)
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.8, 0.6, L), (sx * (r - 0.4), 0.3, 0), mat="concrete", color=trim))
        if not ab or sx < 0:
            out.append(part(ctx, "B", (0.15, 0.1, L), (sx * (r - 0.9), 0.65, 0), mat="neon", color=cyan, collide=False,
                            light=light("surface", cyan, 0.6 if not ab else 0.2, 10, angle=120, face="Top", shadows=False)))
    pts = [(math.cos(math.pi * i / n) * r, 0.3 + math.sin(math.pi * i / n) * r) for i in range(n + 1)]
    broken = set(rng.sample(range(n), 2)) if ab else set()
    for i in range(n):
        a, b = pts[i], pts[i + 1]
        if i in broken:   # the pane is gone: one shard left in the frame, glass on the floor
            out.append(_beam(ctx, (a[0], a[1], -L * 0.3), (b[0], b[1], -L * 0.3), 0.25, L * 0.25, mat="glass",
                             color=(170, 190, 180), t=0.5))
            out.append(part(ctx, "B", (2.5, 0.06, 2.0), (a[0] * 0.6, 0.33, rng.uniform(-L / 4, L / 4)), rot=(0, rng.uniform(0, 90), 0),
                            mat="water", color=(70, 90, 80), t=0.35, collide=False, cast=False))
            continue
        out.append(_beam(ctx, (a[0], a[1], 0), (b[0], b[1], 0), 0.25, L, ext=0.15, mat="glass", color=(200, 232, 245), t=0.7))
    ro = r + 1.6
    level = 0.3 + r * 0.5
    wpts = [(math.cos(math.pi * i / n) * ro, 0.3 + math.sin(math.pi * i / n) * ro) for i in range(n + 1)]
    if not ab:
        for i in range(n):
            a, b = wpts[i], wpts[i + 1]
            out.append(_beam(ctx, (a[0], a[1], 0), (b[0], b[1], 0), 3.0, L, ext=0.4, mat="water",
                             color=(50, 120, 170), t=0.45, collide=False, cast=False))
    else:   # drained: only murky water pooled low on both sides
        for sx in (-1, 1):
            out.append(part(ctx, "B", (3.0, level - 0.3, L), (sx * (r + 1.6), (0.3 + level) / 2, 0), mat="water",
                            color=(70, 100, 70), t=0.45, collide=False, cast=False))
    ribs = max(2, int(L / 8) + 1)
    for k in range(ribs):
        z = -L / 2 + 0.3 + (L - 0.6) * k / (ribs - 1)
        rp = [(math.cos(math.pi * i / n) * (r + 0.2), 0.3 + math.sin(math.pi * i / n) * (r + 0.2)) for i in range(n + 1)]
        for i in range(n):
            out.append(_beam(ctx, (rp[i][0], rp[i][1], z), (rp[i + 1][0], rp[i + 1][1], z), 0.5, 0.6, ext=0.3, mat="metal", color=trim))
    for sx in (-1, 1):
        out.append(part(ctx, "B", (3.5, 1.5, L), (sx * (r + 2.2), 0.75, 0), mat="sand"))
    out += transform(coral(ctx, 3, "mixed"), (r + 2.2, 1.5, -L * 0.2))
    if _round(ctx):
        out += transform(coral(ctx, 2, "fan"), (-(r + 2.4), 1.5, L * 0.25))
    for j in range(3 if _round(ctx) else 2):
        s = rng.uniform(1.0, 1.8)
        out.append(_ball(ctx, (s, s * 0.7, s), (-(r + 2.2) + rng.uniform(-0.6, 0.6), 1.5 + s * 0.2, -L * 0.2 + j * 1.2), mat="rock", vary=0.08))
    if not ab:   # a school swimming along the tunnel inside the water band; gone once the tank has drained
        ang = math.radians(30)
        out += transform(fish_school(ctx, 5 if _round(ctx) else 4, 0, 0.5),
                         (-math.cos(ang) * (ro - 0.3), 0.3 + math.sin(ang) * (ro - 0.3), L * 0.1), 90)
    if not ab:
        for z in (-L / 4, L / 4):
            out.append(part(ctx, "B", (1.0, 0.2, 1.0), (0, r + 2.4, z), mat="neon", color=(120, 200, 255), collide=False,
                            light=light("point", (90, 180, 255), 1.2, 30, shadows=False)))
    return out


# =========================================================================== theme park

def _horse(ctx, coat, saddle):
    """Carousel horse facing -Z, origin at the belly centre; front legs raised in a gallop."""
    m = "paint"
    out = [part(ctx, "B", (0.9, 1.0, 2.4), (0, 0, 0), mat=m, color=coat, collide=False),
           part(ctx, "B", (0.6, 1.5, 0.7), (0, 0.95, -1.05), rot=(-25, 0, 0), mat=m, color=coat, collide=False),
           part(ctx, "B", (0.55, 0.6, 1.15), (0, 1.6, -1.65), rot=(-15, 0, 0), mat=m, color=coat, collide=False),
           part(ctx, "B", (0.95, 0.15, 0.9), (0, 0.55, 0.05), mat="leather", color=saddle, collide=False)]
    c, s = math.cos(math.radians(-30)), math.sin(math.radians(-30))
    out.append(part(ctx, "B", (0.2, 1.1, 0.25), (0, 0.2 - 0.55 * c, 1.2 - 0.55 * s), rot=(-30, 0, 0), mat=m,
                    color=shade(coat, 0.8), collide=False))
    for sx in (-1, 1):
        for jz, ang in ((-0.95, 50 if sx < 0 else 35), (0.95, -20)):
            c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            out.append(part(ctx, "B", (0.25, 1.3, 0.25), (sx * 0.3, -0.4 - 0.65 * c, jz - 0.65 * s), rot=(ang, 0, 0), mat=m,
                            color=shade(coat, 0.95), collide=False))
    if _hi(ctx):
        out.append(part(ctx, "B", (0.2, 1.2, 0.3), (0, 1.05, -0.8), rot=(-25, 0, 0), mat=m, color=saddle, collide=False))
    return out


@kit("carousel", "merry-go-round: round deck, centre drum, striped cone roof with bulbs, horses on brass poles",
     {"r": (8, 5, 14), "horses": (8, 4, 12)}, footprint=(17, 17), tags=("themepark",))
def carousel(ctx, r, horses):
    rng, ab = ctx.rng, _abandoned(ctx)
    r = _sn(ctx, r)
    eave, deck = 10.0, 1.1
    n = {"stud": 8, "lowpoly": 8, "midpoly": 12, "highpoly": 16}[ctx.style]
    acc, pri = ctx.color("fabric", "accent"), ctx.color("fabric", "primary")
    brass = _col(ctx, BRASS)
    out = _prism(ctx, 2 * r + 1, 0.6, (0, 0.3, 0), mat="wood", role="trim")
    out += _prism(ctx, 2 * r, 0.5, (0, 0.85, 0), mat="plank", role="secondary")
    drum_h = eave - deck
    out.append(_up(ctx, r * 0.5, drum_h, (0, deck + drum_h / 2, 0), mat="paint", role="primary"))
    if _round(ctx):   # mirror panels on the drum
        rr = r * 0.25 + 0.06
        for i in range(6):
            a = 2 * math.pi * (i + 0.5) / 6
            out.append(part(ctx, "B", (2 * math.pi * rr / 6 * 0.7, drum_h * 0.45, 0.1), (math.sin(a) * rr, deck + drum_h * 0.45, math.cos(a) * rr),
                            rot=(0, math.degrees(a), 0), mat="glass", color=(225, 232, 240), t=0.2, collide=False))
    out += _prism(ctx, 2 * r + 0.6, 0.4, (0, eave + 0.2, 0), mat="wood", role="trim")
    out += _cone(ctx, r + 0.3, eave + 0.4, r * 0.45, n, [acc, pri])
    top = eave + 0.4 + r * 0.45
    out.append(_ball(ctx, (0.9, 0.9, 0.9), (0, top + 0.3, 0), mat="metal", color=_col(ctx, GOLD)))
    out.append(part(ctx, "B", (0.12, 2.0, 0.12), (0, top + 1.6, 0), mat="metal", color=brass, collide=False))
    if not ab:
        out.append(part(ctx, "W", (0.06, 0.7, 1.2), (0.6, top + 2.2, 0), rot=(0, -90, 0), mat="fabric", color=acc, collide=False))
    if _hi(ctx):   # scalloped valance under the eave
        rv = r + 0.35
        seg = 2 * rv * math.sin(math.pi / n)
        for i in range(n):
            a = 2 * math.pi * (i + 0.5) / n
            out.append(part(ctx, "B", (seg * 0.95, 0.8, 0.1), (math.sin(a) * rv, eave - 0.2, math.cos(a) * rv), rot=(0, math.degrees(a), 0),
                            mat="fabric", color=pri if i % 2 else acc, collide=False))
    nb = n // 2
    for i in range(nb):
        a = 2 * math.pi * i / nb
        on = _lit(ctx)
        lt = light("point", (255, 200, 130), 1.4, 18, shadows=False) if on and i % max(1, nb // 3) == 0 else None
        out.append(part(ctx, "B" if _stud(ctx) else "S", (0.4, 0.4, 0.4), (math.sin(a) * (r + 0.5), eave + 0.2, math.cos(a) * (r + 0.5)),
                        mat="neon" if on else "glass", color=(255, 214, 150) if on else (120, 110, 90), collide=False, light=lt))
    nh = int(horses) if _round(ctx) else min(int(horses), 6)
    coats = [_col(ctx, WHITE), ctx.color("paint", "primary")]
    gone = rng.randrange(nh) if ab else -1
    tipped = (gone + 2) % nh if ab else -1
    for i in range(nh):
        a = 2 * math.pi * i / nh
        x, z = math.sin(a) * r * 0.68, math.cos(a) * r * 0.68
        out.append(_up(ctx, 0.2, drum_h, (x, deck + drum_h / 2, z), mat="metal", color=brass, collide=False))
        if i == gone:
            continue
        horse = _horse(ctx, coats[i % 2], ctx.color("leather", "accent"))
        if i == tipped:
            _rotate_group(horse, (0, 0, 0), rz=35)
        out += transform(horse, (x, deck + 2.2 + (0.8 if i % 2 else 0), z), math.degrees(a) - 90)   # alternate heights = motion
    return out


@kit("ferris_wheel", "ferris wheel: twin rims with spokes, hanging gondolas, A-frame legs, boarding deck (wheel faces -Z)",
     {"size": (30, 16, 60)}, footprint=(34, 12), tags=("themepark",))
def ferris_wheel(ctx, size):
    rng, ab = ctx.rng, _abandoned(ctx)
    R = _sn(ctx, size / 2)
    hub = R + 4
    segs = {"stud": 12, "lowpoly": 12, "midpoly": 16, "highpoly": 20}[ctx.style]
    zr = 1.4
    steel = _col(ctx, (232, 232, 228))
    dark = _col(ctx, (60, 60, 64))
    pts = [(math.sin(2 * math.pi * i / segs) * R, hub + math.cos(2 * math.pi * i / segs) * R) for i in range(segs)]
    out = []
    for zs in (-zr, zr):
        for i in range(segs):
            a, b = pts[i], pts[(i + 1) % segs]
            out.append(_beam(ctx, (a[0], a[1], zs), (b[0], b[1], zs), 0.5, 0.5, ext=0.3, mat="metal", color=steel))
        for i in range(0, segs, 2):
            out.append(_beam(ctx, (0, hub, zs), (pts[i][0], pts[i][1], zs), 0.25, 0.25, mat="metal", color=steel))
    out.append(part(ctx, "C", (2 * zr + 2.8, 1.6, 1.6), (0, hub, 0), rot=(0, 90, 0), mat="metal", color=dark))
    hub_lit = _lit(ctx)
    acc = ctx.color("neon", "accent")
    for zs in (-1, 1):
        out.append(part(ctx, "C", (0.3, 3.0, 3.0), (0, hub, zs * (zr + 0.5)), rot=(0, 90, 0), mat="neon" if hub_lit else "metal",
                        color=acc if hub_lit else dark, light=light("point", acc, 2.0, 30) if hub_lit and zs < 0 else None))
    for zs in (-1, 1):
        for sx in (-1, 1):
            foot = (sx * R * 0.55, 0, zs * (zr + 3.5))
            out.append(_beam(ctx, foot, (sx * 0.4, hub, zs * (zr + 1.3)), 1.0, mat="metal", color=steel))
            out.append(part(ctx, "B", (2, 1, 2), (foot[0], 0.5, foot[2]), mat="concrete"))
        zb = zs * (zr + 3.5 - 2.2 * 0.45)
        out.append(part(ctx, "B", (R * 0.6, 0.5, 0.5), (0, hub * 0.45, zb), mat="metal", color=steel))
    out.append(part(ctx, "B", (5, 0.8, 5.5), (0, 0.4, 0), mat="plank", role="secondary"))
    out.append(part(ctx, "B", (5, 0.4, 1.2), (0, 0.2, -3.3), mat="plank", role="secondary"))
    cab = [ctx.color("paint", "accent"), ctx.color("paint", "primary"), ctx.color("paint", "secondary")]
    fallen = rng.randrange(segs // 2) if ab else -1
    for k, i in enumerate(range(0, segs, 2)):
        px, py = pts[i]
        out.append(part(ctx, "B", (0.3, 0.3, 2 * zr), (px, py, 0), mat="metal", color=steel))
        if k == fallen:   # one gondola came down and lies by the deck
            out.append(part(ctx, "B", (2.0, 1.8, 2.2), (R * 0.3, 0.9, -zr - 5), rot=(0, 30, 14), mat="paint", color=cab[k % 3]))
            continue
        out.append(part(ctx, "B", (0.18, 1.4, 0.18), (px, py - 0.7, 0), mat="metal", color=dark, collide=False))
        out.append(part(ctx, "B", (2.0, 1.8, 2.2), (px, py - 2.3, 0), mat="paint", color=cab[k % 3]))
        out.append(part(ctx, "B", (2.3, 0.3, 2.5), (px, py - 1.35, 0), mat="metal", color=steel))
        if _round(ctx):
            out.append(part(ctx, "B", (2.06, 0.7, 2.26), (px, py - 2.0, 0), mat="glass", color=(200, 225, 235), t=0.5))
    if _round(ctx):
        step = 1 if _hi(ctx) else 2
        for i in range(0, segs, step):
            on = _lit(ctx)
            out.append(part(ctx, "S", (0.4, 0.4, 0.4), (pts[i][0], pts[i][1], -zr - 0.35), mat="neon" if on else "glass",
                            color=(acc if i % 2 else (255, 230, 170)) if on else (110, 110, 110), collide=False))
    return out


@kit("ticket_booth", "small ticket booth: glass window, counter ledge, overhang roof, lit sign with text",
     {"w": (5, 4, 8)}, footprint=(6, 6), tags=("themepark",))
def ticket_booth(ctx, w):
    rng, ab = ctx.rng, _abandoned(ctx)
    w = _sn(ctx, w)
    d, h = 4.0, 7.5
    out = [part(ctx, "B", (w, h, 0.4), (0, h / 2, d / 2), mat="paint", role="primary"),
           part(ctx, "B", (w, 3.2, 0.4), (0, 1.6, -d / 2), mat="paint", role="primary"),
           part(ctx, "B", (w, 1.3, 0.4), (0, h - 0.65, -d / 2), mat="paint", role="primary")]
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.4, h, d), (sx * (w / 2 - 0.2), h / 2, 0), mat="paint", role="primary"))
        for sz in (-1, 1):
            out.append(part(ctx, "B", (0.5, h, 0.5), (sx * w / 2, h / 2, sz * d / 2), mat="wood", role="trim"))
    out.append(part(ctx, "B", (0.1, 6, 2.2), (w / 2 + 0.05, 3, 0.4), mat="wood", role="secondary"))
    if not ab:
        out.append(part(ctx, "B", (w - 0.8, 3.0, 0.1), (0, 4.7, -d / 2), mat="glass", color=(200, 225, 235), t=0.6))
        if _round(ctx):
            out.append(part(ctx, "C", (0.12, 0.6, 0.6), (0, 4.2, -d / 2 - 0.06), rot=(0, 90, 0), color=(40, 40, 44), collide=False))
    else:   # window smashed: shards on the ground in front
        for i in range(3):
            out.append(part(ctx, "B", (rng.uniform(0.4, 0.9), 0.05, rng.uniform(0.3, 0.7)), (rng.uniform(-w / 3, w / 3), 0.03, -d / 2 - rng.uniform(0.5, 1.5)),
                            rot=(0, rng.uniform(0, 90), 0), mat="glass", color=(200, 225, 235), t=0.4, collide=False, cast=False))
    out.append(part(ctx, "B", (w, 0.2, 1.0), (0, 3.3, -d / 2 - 0.5), mat="wood", role="trim"))
    out.append(part(ctx, "B", (w + 1.6, 0.5, d + 1.6), (0, h + 0.25, 0), mat="paint", role="accent"))
    if _round(ctx):
        out.append(part(ctx, "B", (w + 1.8, 0.2, d + 1.8), (0, h + 0.05, 0), mat="wood", role="trim"))
    glow = not ab
    sign = [part(ctx, "B", (w, 1.4, 0.3), (0, h + 1.2, -d / 2 + 0.3), mat="wood", role="trim"),
            _text(part(ctx, "B", (w - 0.4, 1.0, 0.1), (0, h + 1.2, -d / 2 + 0.1), mat="neon" if glow else "paint",
                       role="accent" if glow else "primary", collide=False,
                       light=light("point", ctx.palette["accent"], 0.9, 10, shadows=False) if glow else None))]
    if ab:
        _rotate_group(sign, (w / 2, h + 0.5, 0), rz=10)
    out += sign
    lit = _lit(ctx)
    out.append(part(ctx, "B", (0.8, 0.2, 0.8), (0, h - 0.15, 0), mat="neon" if lit else "glass", color=(255, 220, 160), collide=False,
                    light=light("point", (255, 210, 150), 1.2, 12) if lit else None))
    out.append(part(ctx, "B", (1.2, 2.2, 1.2), (0, 1.1, 0.6), mat="wood", role="secondary"))
    return out


@kit("striped_tent", "round circus/fair tent with alternating stripes, cone roof, pole pennant, open front flap",
     {"w": (12, 6, 30), "h": (10, 5, 20)}, footprint=(13, 13), tags=("themepark",))
def striped_tent(ctx, w, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    w, h = _sn(ctx, w), _sn(ctx, h)
    n = {"stud": 8, "lowpoly": 8, "midpoly": 12, "highpoly": 16}[ctx.style]
    r = w / 2
    wall_h, rise = h * 0.42, h * 0.58
    cols = [ctx.color("fabric", "accent"), ctx.color("fabric", "primary")]
    seg = 2 * r * math.sin(math.pi / n) * 1.05
    rin = r * math.cos(math.pi / n)
    torn = rng.randrange(1, n) if ab else -1
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        if i == n // 2:   # the panel facing -Z is the entrance: two flaps tied back
            for s in (-1, 1):
                out.append(part(ctx, "B", (seg * 0.4, wall_h, 0.15), (math.sin(a) * rin + s * seg * 0.55, wall_h / 2, math.cos(a) * rin - 0.25),
                                rot=(0, s * 35, 0), mat="fabric", color=cols[1], collide=False))
            continue
        if i == torn:   # half-torn panel, sagging
            out.append(part(ctx, "B", (seg, wall_h * 0.5, 0.2), (math.sin(a) * rin, wall_h * 0.75, math.cos(a) * rin),
                            rot=(0, math.degrees(a), 8), mat="fabric", color=cols[i % 2]))
            continue
        out.append(part(ctx, "B", (seg, wall_h, 0.2), (math.sin(a) * rin, wall_h / 2, math.cos(a) * rin), rot=(0, math.degrees(a), 0),
                        mat="fabric", color=cols[i % 2]))
    out += _cone(ctx, r + 0.4, wall_h, rise, n, cols)
    out.append(_up(ctx, 0.4, h + 2, (0, (h + 2) / 2, 0), mat="wood"))
    if not ab:
        out.append(part(ctx, "W", (0.06, 0.9, 1.6), (0.8, h + 1.4, 0), rot=(0, -90, 0), mat="fabric", color=cols[0], collide=False))
    out += _prism(ctx, w * 0.8, 0.06, (0, 0.03, 0), mat="carpet", color=_col(ctx, (150, 40, 44)), collide=False)
    if _round(ctx):
        rv = r + 0.5
        for i in range(n):
            a = 2 * math.pi * (i + 0.5) / n
            out.append(part(ctx, "B", (seg * 0.9, 0.8, 0.12), (math.sin(a) * rv, wall_h - 0.3, math.cos(a) * rv), rot=(0, math.degrees(a), 0),
                            mat="fabric", color=cols[(i + 1) % 2], collide=False))
        for k in range(4 if not ab else 2):
            a = math.pi / 4 + k * math.pi / 2
            top = (math.sin(a) * (r + 0.3), wall_h, math.cos(a) * (r + 0.3))
            peg = (math.sin(a) * (r + 3), 0.3, math.cos(a) * (r + 3))
            out.append(_beam(ctx, top, peg, 0.08, mat="fabric", color=(200, 190, 160), collide=False))
            out.append(part(ctx, "B", (0.25, 0.6, 0.25), peg, mat="wood"))
    return out


@kit("park_arch_gate", "theme park entrance arch: two towers with finials and flags, curved arch with bulbs, sign with text",
     {"w": (20, 10, 40), "h": (16, 10, 30)}, footprint=(28, 5), tags=("themepark",))
def park_arch_gate(ctx, w, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    w, h = _sn(ctx, w), _sn(ctx, h)
    tw = 3.0
    acc = ctx.color("paint", "accent")
    pri = ctx.color("paint", "primary")
    out = []
    for sx in (-1, 1):
        x = sx * (w / 2 + tw / 2)
        out.append(part(ctx, "B", (tw + 0.8, 1.2, tw + 0.8), (x, 0.6, 0), mat="stone", role="trim"))
        if _round(ctx):
            out.append(_cyl_y(ctx, tw, h - 1.2, (x, 1.2 + (h - 1.2) / 2, 0), mat="plaster", color=pri))
            for y in (h * 0.45, h - 1.0):
                out.append(_cyl_y(ctx, tw + 0.3, 0.6, (x, y, 0), mat="paint", color=acc))
            roof = transform(_cone(ctx, tw / 2 + 0.5, 0, 3.0, ctx.detail(), [acc, shade(acc, 0.85)], mat="roof"), (x, h, 0))
        else:
            out.append(part(ctx, "B", (tw, h - 1.2, tw), (x, 1.2 + (h - 1.2) / 2, 0), mat="plaster", color=pri))
            for y in (h * 0.45, h - 1.0):
                out.append(part(ctx, "B", (tw + 0.4, 0.6, tw + 0.4), (x, y, 0), mat="paint", color=acc))
            roof = transform(_cone(ctx, tw / 2 + 0.5, 0, 3.0, 4, [acc], mat="roof", square=True), (x, h, 0))
        out += roof
        out.append(_ball(ctx, (0.8, 0.8, 0.8), (x, h + 3.3, 0), mat="metal", color=_col(ctx, GOLD)))
        if not (ab and sx > 0):
            out.append(part(ctx, "B", (0.12, 2.4, 0.12), (x, h + 4.6, 0), mat="metal", color=(60, 60, 60), collide=False))
            out.append(part(ctx, "W" if not _stud(ctx) else "B", (0.06, 1.0, 1.8), (x + 0.9, h + 5.2, 0), rot=(0, -90, 0), mat="fabric",
                            color=acc, collide=False))
        lit = _lit(ctx)
        out.append(part(ctx, "B", (0.6, 0.6, 0.3), (x, h - 2.0, -tw / 2 - 0.2), mat="neon" if lit else "glass", color=(255, 220, 160),
                        collide=False, light=light("spot", (255, 210, 150), 1.6, 18, angle=80, face="Front") if lit else None))
    base_y = h - 4.0
    bulbs = []
    if _round(ctx):
        n = ctx.detail() // 2 + 3
        ry = w * 0.22
        pts = [(math.cos(math.pi * i / n) * (w / 2 + 0.5), base_y + math.sin(math.pi * i / n) * ry) for i in range(n + 1)]
        for i in range(n):
            out.append(_beam(ctx, (pts[i][0], pts[i][1], 0), (pts[i + 1][0], pts[i + 1][1], 0), 1.4, 1.6, ext=0.4, mat="paint", color=acc))
        bulbs = [(p[0], p[1] - 0.4) for p in pts[1:-1]]
        sign_y = base_y + ry * 0.45
    else:
        out.append(part(ctx, "B", (w + 1, 2.0, 1.6), (0, base_y + 1.0, 0), mat="paint", color=acc))
        out.append(part(ctx, "B", (w * 0.4, 1.0, 1.6), (0, base_y + 2.5, 0), mat="paint", color=acc))
        bulbs = [(-w / 2 + w * (i + 0.5) / 6, base_y) for i in range(6)]
        sign_y = base_y - 1.4
    for bx, by in bulbs:
        on = _lit(ctx)
        out.append(part(ctx, "B" if _stud(ctx) else "S", (0.45, 0.45, 0.45), (bx, by, -0.9), mat="neon" if on else "glass",
                        color=(255, 220, 150) if on else (110, 104, 90), collide=False))
    sign = [part(ctx, "B", (w * 0.6, 2.6, 0.5), (0, sign_y, -1.0), mat="wood", role="trim"),
            _text(part(ctx, "B", (w * 0.6 - 0.5, 2.1, 0.1), (0, sign_y, -1.3), mat="paint", role="primary", collide=False))]
    if ab:
        _rotate_group(sign, (-w * 0.3, sign_y + 1.3, -1.0), rz=-9)
    out += sign
    return out


@kit("bumper_car", "bumper car (dodgem): rubber bumper ring, glossy shell, seat, wheel, sparking pole (front -Z)", {},
     footprint=(4, 6), tags=("themepark",))
def bumper_car(ctx):
    rng, ab = ctx.rng, _abandoned(ctx)
    L, W = 5.5, 3.6
    rubber = _col(ctx, (30, 30, 32))
    out = []
    if _round(ctx):
        out.append(part(ctx, "B", (W + 0.4, 0.8, L - 0.4), (0, 0.6, 0), mat="plastic", color=rubber))
        out.append(part(ctx, "B", (W - 0.4, 0.8, L + 0.4), (0, 0.6, 0), mat="plastic", color=rubber))
        for sx in (-1, 1):
            for sz in (-1, 1):
                out.append(_cyl_y(ctx, 0.8, 0.8, (sx * (W / 2 - 0.2), 0.6, sz * (L / 2 - 0.2)), mat="plastic", color=rubber))
    else:
        out.append(part(ctx, "B", (W + 0.6, 0.8, L + 0.6), (0, 0.6, 0), mat="plastic", color=rubber))
    shell = ctx.color("paint", "accent")
    out.append(part(ctx, "B", (W, 0.8, L), (0, 0.4, 0), mat="metal", color=(50, 50, 54)))   # chassis on the floor
    out.append(part(ctx, "B", (W - 0.2, 1.2, L * 0.6), (0, 1.4, L * 0.15), mat="paint", color=shell))
    out.append(part(ctx, "W", (W - 0.2, 1.2, L * 0.4), (0, 1.4, -L * 0.3), mat="paint", color=shell))
    out.append(part(ctx, "B", (W - 1.2, 0.4, 1.4), (0, 2.2, L * 0.15), mat="leather", role="secondary"))
    out.append(part(ctx, "B", (W - 1.2, 1.6, 0.3), (0, 2.8, L * 0.38), mat="leather", role="secondary"))
    out.append(_beam(ctx, (0, 1.8, -0.9), (0, 2.7, -0.5), 0.2, mat="metal", color=(40, 40, 40)))
    out.append(_beam(ctx, (0, 2.7, -0.5), (0, 2.78, -0.46), 1.1, shape="C", mat="plastic", color=(30, 30, 30)))
    pole_top = (0, 8.5, L / 2 - 0.3)
    if ab:   # bent pole, no spark
        knee = (0.3, 5.0, L / 2 - 0.3)
        out.append(_beam(ctx, (0, 2.0, L / 2 - 0.3), knee, 0.18, mat="metal", color=(120, 110, 100)))
        out.append(_beam(ctx, knee, (1.6, 7.2, L / 2 + 0.4), 0.18, mat="metal", color=(120, 110, 100)))
    else:
        out.append(part(ctx, "B", (0.18, 6.5, 0.18), (0, 5.25, L / 2 - 0.3), mat="metal", color=(170, 170, 170)))
        out.append(part(ctx, "B", (0.5, 0.3, 0.5), pole_top, mat="neon", color=(200, 230, 255), collide=False,
                        light=light("point", (180, 220, 255), 0.8, 8, shadows=False)))
    if _hi(ctx):
        for sx in (-1, 1):
            out.append(part(ctx, "C", (0.05, 0.9, 0.9), (sx * (W / 2 - 0.08), 1.4, L * 0.15), color=WHITE, collide=False))
            out.append(part(ctx, "B", (0.5, 0.3, 0.1), (sx * 1.0, 1.3, -L / 2 - 0.02), mat="neon", color=(255, 240, 200), collide=False))
    return out


# =========================================================================== fishing / coast

@kit("dock", "wooden pier: plank deck on piles running from the shore (z = 0) out towards -Z, optional railing, lamp and ladder at the end",
     {"length": (24, 8, 80), "w": (6, 4, 14), "rail": (1, 0, 1)}, footprint=(6, 24), tags=("coast",))
def dock(ctx, length, w, rail):
    rng, ab = ctx.rng, _abandoned(ctx)
    L, w = _sn(ctx, length), _sn(ctx, w)
    deck_y = 1.6
    pd = max({"stud": 2, "lowpoly": 2, "midpoly": 1.2, "highpoly": 1.0}[ctx.style], L / 60)
    n = int(L / pd)
    vary = 0.05 if ctx.state == "new" else 0.12
    out = []
    for i in range(n):
        z = 1 - pd * (i + 0.5)
        if ab and i < n - 5 and rng.random() < 0.12:   # the far end, where the lamp and clutter stand, stays decked
            continue
        tilt = (0, rng.uniform(-6, 6), rng.uniform(-10, 10)) if ab and rng.random() < 0.08 else (0, 0, 0)
        out.append(part(ctx, "B", (w, 0.3, pd if _stud(ctx) else pd - 0.12), (0, deck_y - 0.15, z), rot=tilt, mat="plank", vary=vary))
    zc = 1 - L / 2
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.6, 0.6, L), (sx * (w / 2 - 0.6), deck_y - 0.6, zc), mat="wood"))
    bays = max(1, int(L / 6))
    top = deck_y + (3.2 if rail else 0.6)
    post_z = [1 - 0.4 - (L - 0.8) * k / bays for k in range(bays + 1)]
    broken = rng.randrange(bays) if ab else -1
    for sx in (-1, 1):
        x = sx * (w / 2 - 0.3)
        for k, z in enumerate(post_z):
            out.append(_up(ctx, 0.9, top + 4, (x, (top - 4) / 2, z), mat="wood", vary=0.06))
            if _hi(ctx) and k < bays:
                out.append(_beam(ctx, (x, -3, z), (x, deck_y - 0.9, post_z[k + 1]), 0.3, mat="wood"))
        if rail:
            for k in range(bays):
                z0, z1 = post_z[k], post_z[k + 1]
                if k == broken and sx > 0:   # rail snapped, one half hanging down
                    out.append(_beam(ctx, (x, top - 0.2, z0), (x, deck_y + 0.6, (z0 + z1) / 2), 0.3, mat="wood"))
                    continue
                out.append(part(ctx, "B", (0.3, 0.3, abs(z1 - z0)), (x, top - 0.2, (z0 + z1) / 2), mat="wood"))
                if _round(ctx):
                    out.append(part(ctx, "B", (0.2, 0.2, abs(z1 - z0)), (x, deck_y + 1.4, (z0 + z1) / 2), mat="wood"))
    zend = 1 - L
    for k in range(4 if _round(ctx) else 3):   # ladder down to the water at the end
        out.append(part(ctx, "B", (1.6, 0.2, 0.2), (0, deck_y - 0.8 - k * 1.0, zend - 0.1), mat="metal", color=_col(ctx, (120, 120, 124))))
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.2, 4.4, 0.2), (sx * 0.8, deck_y - 2.0, zend - 0.1), mat="metal", color=_col(ctx, (120, 120, 124))))
    out += transform(lamp_post(ctx, 8, "warm", 1 if ab else 0), (w / 2 - 0.9, deck_y, zend + 1.0))
    # clutter cluster at the far corner: crate, rope coil, bucket
    cx = -w / 2 + 1.4
    out += transform(crate(ctx, 2), (cx, deck_y, zend + 1.6))
    if _round(ctx):
        out.append(part(ctx, "C", (0.35, 1.4, 1.4), (cx + 1.6, deck_y + 0.18, zend + 3.2), rot=(0, 0, 90), mat="fabric", color=_col(ctx, (190, 170, 120))))
        out.append(_cyl_y(ctx, 0.9, 1.0, (cx + 0.2, deck_y + 0.5, zend + 3.6), mat="metal", color=_col(ctx, (120, 130, 140))))
        for sx in (-1, 1):
            out.append(_up(ctx, 0.5, 0.7, (sx * (w / 2 - 1.2), deck_y + 0.35, zend + 0.5), mat="metal", color=(40, 40, 44)))
    return out


@kit("rowboat", "wooden rowboat with thwarts and oars, bow at -Z (sits on the floor/water line)",
     {"length": (7, 5, 12)}, footprint=(4, 7), tags=("coast",))
def rowboat(ctx, length):
    rng, ab = ctx.rng, _abandoned(ctx)
    L = _sn(ctx, length)
    W, H = L * 0.42, 1.4
    hull = ctx.color("paint", "primary")
    flare = 12 if _round(ctx) else 0
    out = [part(ctx, "B", (W * 0.6, 0.3, L * 0.62), (0, 0.15, L * 0.08), mat="wood"),
           part(ctx, "B", (W * 0.35, 0.3, L * 0.22), (0, 0.15, -L * 0.33), mat="wood")]
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.25, H, L * 0.62), (sx * (W / 2 - 0.12), H / 2 + 0.1, L * 0.08), rot=(0, 0, -sx * flare),
                        mat="paint", color=hull))
        ang = math.atan2(W / 2, L * 0.27)
        bl = math.hypot(W / 2, L * 0.27)
        out.append(part(ctx, "B", (0.25, H, bl), (sx * W / 4, H / 2 + 0.1, -L * 0.365), rot=(0, sx * math.degrees(ang), 0),
                        mat="paint", color=hull))
        if _round(ctx):
            out.append(part(ctx, "B", (0.35, 0.15, L * 0.62), (sx * (W / 2 - 0.05), H + 0.12, L * 0.08), mat="wood", role="accent"))
            out.append(part(ctx, "B", (0.35, 0.15, bl), (sx * W / 4, H + 0.12, -L * 0.365), rot=(0, sx * math.degrees(ang), 0),
                            mat="wood", role="accent"))
    out.append(part(ctx, "B", (0.3, H + 0.4, 0.3), (0, (H + 0.4) / 2 + 0.1, -L / 2 + 0.15), mat="wood", role="trim"))
    out.append(part(ctx, "B", (W * 0.9, H * 0.9, 0.25), (0, H / 2 + 0.1, L * 0.39), mat="paint", color=hull))
    for z in (-L * 0.1, L * 0.22):
        out.append(part(ctx, "B", (W - 0.5, 0.2, 0.7), (0, H * 0.7, z), mat="wood", vary=0.05))
    if _round(ctx):
        out.append(part(ctx, "B", (W * 0.55, 0.1, L * 0.6), (0, 0.35, L * 0.08), mat="plank", vary=0.05))
    oars = 1 if ab else 2
    for k in range(oars):
        sx = (-1, 1)[k]
        oar = [part(ctx, "B", (0.2, 0.12, L * 0.85), (0, 0, 0), mat="wood"),
               part(ctx, "B", (0.5, 0.06, 1.2), (0, 0, L * 0.42), mat="wood", role="accent")]
        out += transform(oar, (sx * 0.5, H * 0.7 + 0.18, 0), sx * 8)
    if _hi(ctx):
        for sx in (-1, 1):
            out.append(part(ctx, "B", (0.15, 0.35, 0.3), (sx * (W / 2 - 0.05), H + 0.35, -L * 0.05), mat="metal", color=(60, 60, 60)))
        for z in (-L * 0.25, L * 0.05, L * 0.3):
            out.append(part(ctx, "B", (W * 0.7, 0.15, 0.2), (0, 0.4, z), mat="wood", color=shade(ctx.color("wood"), 0.8)))
    if ab:
        out.append(part(ctx, "B", (W * 0.5, 0.1, L * 0.4), (0, 0.45, L * 0.1), mat="water", color=(70, 90, 80), t=0.3, collide=False, cast=False))
        _rotate_group(out, (0, 0, 0), rz=14)
        for p in out:
            p["p"][1] = round(p["p"][1] + 0.25, 3)
    return out


@kit("fishing_rod_stand", "rack of fishing rods with a bucket, tackle box and net (clustered by the water)",
     {}, footprint=(5, 3), tags=("coast",))
def fishing_rod_stand(ctx):
    rng, ab = ctx.rng, _abandoned(ctx)
    out = []
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.3, 4, 0.3), (sx * 1.6, 2, 0.4), mat="wood", vary=0.05))
    out.append(part(ctx, "B", (3.6, 0.3, 0.3), (0, 3.8, 0.4), mat="wood"))
    out.append(part(ctx, "B", (3.6, 0.3, 0.6), (0, 0.6, -0.1), mat="wood"))
    rods = 4
    fallen = rng.randrange(rods) if ab else -1
    for i in range(rods):
        x = -1.2 + i * 0.8
        if i == fallen:
            out.append(part(ctx, "B", (0.1, 0.1, 7), (x + 0.3, 0.06, -2.2), rot=(0, 25, 0), mat="metal", color=(40, 40, 44), collide=False))
            continue
        base, tip = (x, 0.2, -0.1), (x + rng.uniform(-0.3, 0.3), 7.5, 0.7)
        out.append(_beam(ctx, base, tip, 0.1, mat="metal", color=(40, 40, 44), collide=False))
        out.append(part(ctx, "B", (0.3, 0.3, 0.3), (x, 1.5, 0.0), mat="metal", color=ctx.color("plastic", "accent"), collide=False))
    out.append(_up(ctx, 1.2, 1.2, (2.6, 0.6, -0.6), mat="metal", color=_col(ctx, (120, 130, 140))))
    if not ab:
        tail = _fish(ctx, 0.8, (170, 180, 170))
        _rotate_group(tail, (0, 0, 0), rz=80)
        out += transform(tail, (2.6, 1.4, -0.6), 0)
    out.append(part(ctx, "B", (1.6, 0.8, 0.9), (-2.7, 0.4, -0.7), mat="plastic", color=ctx.color("plastic", "accent")))
    out.append(part(ctx, "B", (1.65, 0.15, 0.95), (-2.7, 0.88, -0.7), rot=(0 if not ab else -30, 0, 0), mat="plastic",
                    color=shade(ctx.color("plastic", "accent"), 0.8)))
    if _round(ctx):
        out.append(_beam(ctx, (2.0, 0.1, 0.9), (1.4, 3.6, 1.2), 0.12, mat="wood"))
        out.append(part(ctx, "B", (1.4, 1.4, 0.1), (1.3, 4.0, 1.25), rot=(0, 0, 12), mat="fabric", color=(200, 196, 180), t=0.6, collide=False))
    return out


@kit("buoy", "floating buoy (ball or marker with lamp); y = 0 is the water line",
     {"kind": ("marker", ["marker", "ball"]), "color": ("red", ["red", "green", "yellow"])}, footprint=(3, 3), tags=("coast",))
def buoy(ctx, kind, color):
    ab = _abandoned(ctx)
    col = _col(ctx, {"red": (200, 50, 40), "green": (40, 150, 70), "yellow": (240, 190, 40)}[color])
    lamp = {"red": (255, 80, 60), "green": (90, 255, 120), "yellow": (255, 210, 90)}[color]
    out = []
    if kind == "ball":
        out.append(_ball(ctx, (2.4, 2.4, 2.4), (0, 0.6, 0), mat="plastic", color=col))
        if _round(ctx):
            out.append(_cyl_y(ctx, 2.45, 0.4, (0, 0.7, 0), mat="plastic", color=WHITE))
        out.append(part(ctx, "B", (0.15, 0.6, 0.5), (0, 1.95, 0), mat="metal", color=(80, 80, 80)))
    else:
        out += _prism(ctx, 2.6, 1.4, (0, 0.2, 0), mat="plastic", color=col)
        apex = (0, 5.0, 0)
        legs = 3 if not _stud(ctx) else 4
        for k in range(legs):
            a = 2 * math.pi * k / legs
            out.append(_beam(ctx, (math.sin(a) * 1.0, 0.9, math.cos(a) * 1.0), apex, 0.2, mat="metal", color=col))
        if _hi(ctx):
            out.append(_ring(ctx, 0.6, 3.0, 0.1, 0.15, 6, mat="metal", color=col)[0])
        on = not ab
        out.append(part(ctx, "B" if _stud(ctx) else "S", (0.6, 0.6, 0.6), (0, 5.3, 0), mat="neon" if on else "glass",
                        color=lamp if on else (90, 90, 90), collide=False, light=light("point", lamp, 1.5, 24) if on else None))
        out.append(part(ctx, "B", (0.8, 0.15, 0.8), (0, 5.7, 0), mat="metal", color=(60, 60, 60)))
    out.append(part(ctx, "B", (0.15, 3.0, 0.15), (0, -1.6, 0), mat="metal", color=(70, 64, 60), collide=False))
    if ab:
        _rotate_group(out, (0, 0, 0), rz=18)
    return out


@kit("bait_shop_stall", "small bait & tackle stall: counter, striped awning, roof sign with text, cooler, buckets, hanging fish, lantern",
     {"w": (8, 6, 14)}, footprint=(9, 8), tags=("coast",))
def bait_shop_stall(ctx, w):
    rng, ab = ctx.rng, _abandoned(ctx)
    w = _sn(ctx, w)
    d = 5.0
    out = [part(ctx, "B", (w, 3.4, 1.2), (0, 1.7, -d / 2 + 0.6), mat="plank", role="secondary", vary=0.04),
           part(ctx, "B", (w + 0.3, 0.25, 1.6), (0, 3.5, -d / 2 + 0.6), mat="wood"),
           part(ctx, "B", (w, 8, 0.3), (0, 4, d / 2), mat="plank", vary=0.05)]
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.3, 3.4, d), (sx * (w / 2 - 0.15), 1.7, 0), mat="plank", vary=0.05))
        # corner posts 0.05 proud of the walls on the outside so no faces are coplanar
        out.append(part(ctx, "B", (0.5, 7.4, 0.5), (sx * (w / 2 - 0.2), 3.7, -d / 2 + 0.2), mat="wood", role="trim"))
        out.append(part(ctx, "B", (0.5, 8.4, 0.5), (sx * (w / 2 - 0.2), 4.2, d / 2 - 0.2), mat="wood", role="trim"))
    out.append(part(ctx, "B", (w + 0.6, 0.3, d + 0.8), (0, 8.0, 0), rot=(math.degrees(math.atan2(-1.0, d)), 0, 0), mat="roof", role="trim"))
    k = {"stud": 4, "lowpoly": 6, "midpoly": 8, "highpoly": 10}[ctx.style]
    cols = [ctx.color("fabric", "accent"), ctx.color("fabric", "primary")]
    kept = set()
    for i in range(k):
        if ab and rng.random() < 0.2:
            continue
        kept.add(i)
        x = -w / 2 + w * (i + 0.5) / k
        out.append(part(ctx, "W", (w / k, 1.2, 2.0), (x, 6.9, -d / 2 - 1.0), mat="fabric", color=cols[i % 2], collide=False))
        if _hi(ctx):
            out.append(part(ctx, "B", (w / k * 0.9, 0.5, 0.1), (x, 6.05, -d / 2 - 2.0), mat="fabric", color=cols[(i + 1) % 2], collide=False))
    sign = [part(ctx, "B", (w * 0.7, 1.4, 0.3), (0, 9.2, -d / 2 + 0.2), mat="wood", role="trim"),
            _text(part(ctx, "B", (w * 0.7 - 0.4, 1.0, 0.1), (0, 9.2, -d / 2 + 0.02), mat="paint", role="primary", collide=False))]
    if ab:
        _rotate_group(sign, (w * 0.35, 9.2, 0), rz=8)
    out += sign
    # customer side: cooler beside the counter; on the counter: bait buckets clustered left
    out.append(part(ctx, "B", (2.2, 1.6, 1.4), (w / 2 + 1.4, 0.8, -d / 2 + 0.8), mat="plastic", color=_col(ctx, WHITE)))
    out.append(part(ctx, "B", (2.3, 0.3, 1.5), (w / 2 + 1.4, 1.75, -d / 2 + 0.8), rot=(-35 if ab else 0, 0, 0), mat="plastic",
                    color=ctx.color("plastic", "accent")))
    for j in range(3 if _round(ctx) else 2):
        out.append(_up(ctx, 0.8, 0.8, (-w / 2 + 1.0 + j * 0.9, 4.0, -d / 2 + 0.6), mat="plastic", color=_col(ctx, (90, 120, 150))))
    nf = 3 if _round(ctx) else 2
    for j in range(nf):
        x = w * 0.15 + j * 0.9
        if int((x + w / 2) / (w / k)) not in kept:   # its awning strip is gone, so nothing to hang from
            continue
        out.append(part(ctx, "B", (0.06, 0.8, 0.06), (x, 6.0, -d / 2 - 1.2), color=(60, 60, 60), collide=False))
        f = _rotate_group(_fish(ctx, 0.9, (150, 165, 170)), (0, 0, 0), rz=90)
        out += transform(f, (x, 5.1, -d / 2 - 1.2), 90)
    lit = _lit(ctx)
    out.append(part(ctx, "B", (0.08, 1.5, 0.08), (0, 7.55, 0), color=(30, 30, 30), collide=False))   # hanging cord to the roof
    out.append(part(ctx, "B", (0.6, 0.8, 0.6), (0, 6.4, 0), mat="glass", color=(255, 190, 110), t=0.2, collide=False,
                    light=light("point", (255, 180, 100), 1.2, 14) if lit else None))
    return out


@kit("lighthouse", "striped lighthouse: tapered tower, keeper's hut, gallery railing, lantern room with beam light, cone roof",
     {"h": (36, 16, 60)}, footprint=(12, 14), tags=("coast", "light"))
def lighthouse(ctx, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    h = _sn(ctx, h)
    tiers = {"stud": 4, "lowpoly": 5, "midpoly": 6, "highpoly": 8}[ctx.style]
    rb, rt = 4.5, 2.8
    red, white = ctx.color("paint", "accent"), _col(ctx, WHITE)
    out = _prism(ctx, 2 * rb + 1.5, 1.2, (0, 0.6, 0), mat="stone")
    th = (h - 1.2) / tiers
    for i in range(tiers):
        rr = rb + (rt - rb) * (i + 0.5) / tiers
        out += _prism(ctx, 2 * rr, th, (0, 1.2 + th * (i + 0.5), 0), mat="plaster", color=red if i % 2 else white)
        if _hi(ctx) and i:
            out.append(_cyl_y(ctx, 2 * (rb + (rt - rb) * i / tiers) + 0.3, 0.25, (0, 1.2 + th * i, 0), mat="metal", role="trim"))
    for k, f in enumerate((0.3, 0.55, 0.8)):
        rr = rb + (rt - rb) * f
        out.append(part(ctx, "B", (0.9, 1.4, 0.2), (0, 1.2 + (h - 1.2) * f, -rr * 0.93 - 0.05), mat="glass", color=(40, 50, 60), t=0.2))
    out.append(part(ctx, "B", (2.2, 4, 0.3), (0, 3.2, -rb * 0.95), mat="wood", role="secondary"))
    out.append(part(ctx, "B", (2.8, 0.4, 0.4), (0, 5.4, -rb * 0.95 - 0.05), mat="stone", role="trim"))
    out.append(part(ctx, "B", (8, 6, 6), (0, 3, rb + 2.5), mat="plaster", color=white))
    roof_c = ctx.color("roof", "trim")
    for s in (-1, 1):
        out.append(part(ctx, "W", (6.6, 2.4, 4.3), (s * 2.1, 7.2, rb + 2.5), rot=(0, 90 * s, 0), mat="roof", color=roof_c))
    out += _prism(ctx, 2 * rt + 3, 0.5, (0, h + 0.25, 0), mat="metal", role="trim")
    np_ = {"stud": 8, "lowpoly": 8, "midpoly": 12, "highpoly": 16}[ctx.style]
    rr = rt + 1.3
    for i in range(np_):
        if ab and rng.random() < 0.25:
            continue
        a = 2 * math.pi * i / np_
        out.append(part(ctx, "B", (0.15, 1.6, 0.15), (math.sin(a) * rr, h + 1.3, math.cos(a) * rr), mat="metal", role="trim", collide=False))
    out += _ring(ctx, rr, h + 2.1, 0.15, 0.15, np_, mat="metal", role="trim")
    out += _prism(ctx, 2 * rt * 0.8, 3.2, (0, h + 2.1, 0), mat="glass", color=(255, 240, 200) if not ab else (90, 96, 100), t=0.4 if not ab else 0.2)
    if _hi(ctx):
        for i in range(8):
            a = 2 * math.pi * i / 8
            out.append(part(ctx, "B", (0.12, 3.2, 0.12), (math.sin(a) * rt * 0.8, h + 2.1, math.cos(a) * rt * 0.8), mat="metal", role="trim"))
    if not ab:
        out.append(_ball(ctx, (1.6, 1.6, 1.6), (0, h + 2.1, 0), mat="neon", color=(255, 235, 170), collide=False,
                         light=light("point", (255, 230, 170), 3.0, 60)))
        out.append(part(ctx, "B", (1.0, 1.0, 0.3), (0, h + 2.1, -0.9), mat="neon", color=(255, 245, 210), collide=False,
                        light=light("spot", (255, 240, 200), 4.0, 60, angle=30, face="Front")))
    else:
        out.append(_ball(ctx, (1.6, 1.6, 1.6), (0, h + 2.1, 0), mat="glass", color=(80, 80, 76), t=0.1))
    out += _cone(ctx, rt * 0.95, h + 3.7, 2.6, np_, [roof_c], mat="metal")
    out.append(_ball(ctx, (0.7, 0.7, 0.7), (0, h + 6.6, 0), mat="metal", role="trim"))
    return out


# =========================================================================== museum

@kit("dino_skeleton", "stylised dinosaur skeleton on a low plinth: vertebrae, ribs, skull with jaw, legs, support rods (side view from -Z)",
     {"length": (16, 8, 30)}, footprint=(17, 6), tags=("museum",))
def dino_skeleton(ctx, length):
    rng, ab = ctx.rng, _abandoned(ctx)
    L = _sn(ctx, length)
    bone = _col(ctx, BONE)
    ctrl = [(0.0, 0.14), (0.2, 0.25), (0.38, 0.33), (0.6, 0.31), (0.78, 0.36), (0.92, 0.42)]

    def spine(t):
        for (t0, y0), (t1, y1) in zip(ctrl, ctrl[1:]):
            if t <= t1:
                f = (t - t0) / (t1 - t0)
                f = f * f * (3 - 2 * f)
                return (L * 0.5 - t * L * 0.95, 0.8 + L * (y0 + (y1 - y0) * f), 0.0)
        return (L * 0.5 - t * L * 0.95, 0.8 + L * ctrl[-1][1], 0.0)

    out = [part(ctx, "B", (L * 1.02, 0.8, L * 0.35), (0, 0.4, 0), mat="stone", role="trim")]
    if _round(ctx):
        out.append(part(ctx, "B", (L * 1.04, 0.15, L * 0.37), (0, 0.82, 0), mat="marble"))
    out.append(_text(part(ctx, "B", (L * 0.2, 0.5, 0.06), (0, 0.45, -L * 0.175 - 0.04), mat="metal", color=_col(ctx, BRASS), collide=False)))
    nv = {"stud": 10, "lowpoly": 12, "midpoly": 16, "highpoly": 22}[ctx.style]
    ts = [0.92 * i / (nv - 1) for i in range(nv)]
    for i in range(nv - 1):
        tm = (ts[i] + ts[i + 1]) / 2
        s = max(0.22, L * 0.045 * (0.35 + 0.65 * math.sin(math.pi * min(1.0, tm / 0.85))))
        a, b = spine(ts[i]), spine(ts[i + 1])
        if ab and i < 2:   # tail tip fell off: bones lying on the plinth
            out.append(part(ctx, "B", (s, L * 0.04, s), (L * 0.42 - i * 0.6, 0.8 + s / 2, rng.uniform(-L * 0.1, L * 0.1)),
                            rot=(0, rng.uniform(0, 180), 90), mat="ceramic", color=bone, collide=False))
            continue
        a2 = tuple(a[j] + (b[j] - a[j]) * 0.02 for j in range(3))   # hairline joints: reads as vertebrae, still touching
        b2 = tuple(b[j] - (b[j] - a[j]) * 0.02 for j in range(3))
        out.append(_beam(ctx, a2, b2, s, s * 0.9, mat="ceramic", color=bone))
        if 0.18 < tm < 0.78 and (_hi(ctx) or (ctx.style == "midpoly" and i % 2 == 0)):
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + s * 0.9, 0)
            out.append(part(ctx, "B", (0.18, s * 1.2, s * 0.45), m, mat="ceramic", color=bone, collide=False))
    pairs = {"stud": 3, "lowpoly": 4, "midpoly": 5, "highpoly": 6}[ctx.style]
    rw = L * 0.07
    for k in range(pairs):
        t = 0.44 + 0.3 * k / max(1, pairs - 1)
        P = spine(t)
        rl = L * 0.13 * math.sin(math.pi * (t - 0.4) / 0.38) + 0.6
        th = 0.4 if _stud(ctx) else 0.18
        for sz in (-1, 1):
            if _round(ctx):
                m = (P[0], P[1] - rl * 0.3, sz * rw * 1.05)
                e = (P[0] + L * 0.015, P[1] - rl, sz * rw * 0.55)
                out.append(_beam(ctx, P, m, th, mat="ceramic", color=bone, collide=False))
                out.append(_beam(ctx, m, e, th, mat="ceramic", color=bone, collide=False))
            else:
                out.append(_beam(ctx, P, (P[0] + 0.2, P[1] - rl, sz * rw), th, mat="ceramic", color=bone, collide=False))
    hip = spine(0.38)
    pel = (hip[0], hip[1] - L * 0.04, 0)
    out.append(part(ctx, "B", (L * 0.09, L * 0.08, L * 0.1), pel, mat="ceramic", color=bone))
    for sz in (-1, 1):
        hp = (pel[0], pel[1] - 0.2, sz * L * 0.055)
        knee = (hp[0] - L * 0.06, 0.8 + (hp[1] - 0.8) * 0.5, hp[2])
        ankle = (hp[0] + L * 0.03, 0.8 + L * 0.05, hp[2])
        toe = (hp[0] - L * 0.05, 0.95, hp[2])
        out.append(_beam(ctx, hp, knee, L * 0.035, mat="ceramic", color=bone))
        out.append(_beam(ctx, knee, ankle, L * 0.028, mat="ceramic", color=bone))
        out.append(_beam(ctx, ankle, toe, 0.3, 0.5, mat="ceramic", color=bone))
    sh = spine(0.8)
    for sz in ((-1,) if ab else (-1, 1)):
        S = (sh[0], sh[1] - L * 0.008, 0)   # shoulder joint on the spine, upper arm angles out and down
        el = (S[0] - L * 0.02, S[1] - L * 0.06, sz * L * 0.04)
        out.append(_beam(ctx, S, el, 0.2, mat="ceramic", color=bone, collide=False))
        out.append(_beam(ctx, el, (S[0] - L * 0.06, S[1] - L * 0.065, el[2]), 0.18, mat="ceramic", color=bone, collide=False))
    H = spine(0.92)
    out.append(part(ctx, "B", (L * 0.15, L * 0.07, L * 0.065), (H[0] - L * 0.07, H[1] + L * 0.005, 0), mat="ceramic", color=bone))
    if ab:   # the jaw dropped onto the plinth
        out.append(part(ctx, "B", (L * 0.13, L * 0.022, L * 0.055), (H[0] - L * 0.05, 0.8 + L * 0.011, -L * 0.08), rot=(0, 25, 0),
                        mat="ceramic", color=bone, collide=False))
    else:
        out.append(part(ctx, "B", (L * 0.13, L * 0.022, L * 0.055), (H[0] - L * 0.075, H[1] - L * 0.045, 0), rot=(0, 0, 10),
                        mat="ceramic", color=bone))
    if _hi(ctx):
        for sz in (-1, 1):
            out.append(part(ctx, "B", (L * 0.025, L * 0.022, 0.06), (H[0] - L * 0.04, H[1] + L * 0.012, sz * L * 0.033), color=(40, 34, 30),
                            collide=False))
            for j in range(3):
                out.append(part(ctx, "B", (0.12, 0.25, 0.12), (H[0] - L * 0.13 + j * L * 0.025, H[1] - L * 0.03, sz * L * 0.025),
                                color=bone, collide=False))
    for t in (0.4, 0.75):
        P = spine(t)
        hh = P[1] - 0.8 - 0.3
        out.append(_up(ctx, 0.12, hh, (P[0], 0.8 + hh / 2, 0), mat="metal", color=(50, 50, 54), collide=False))
    return out


@kit("stanchion_rope", "museum/queue barrier: brass posts along X with sagging velvet rope",
     {"length": (10, 4, 40)}, footprint=(10, 1), tags=("museum",))
def stanchion_rope(ctx, length):
    rng, ab = ctx.rng, _abandoned(ctx)
    L = _sn(ctx, length)
    n = max(2, int(L / 4) + 1)
    brass = _col(ctx, BRASS)
    rope = ctx.color("fabric", "accent")
    xs = [-L / 2 + L * i / (n - 1) for i in range(n)]
    down = rng.randrange(n) if ab else -1
    out = []
    for i, x in enumerate(xs):
        post = _prism(ctx, 1.0, 0.2, (x, 0.1, 0), mat="metal", color=brass)
        post.append(_up(ctx, 0.25, 3.0, (x, 1.7, 0), mat="metal", color=brass))
        post.append(_ball(ctx, (0.45, 0.45, 0.45), (x, 3.3, 0), mat="metal", color=brass))
        if i == down:
            _rotate_group(post, (x, 0, 0), rz=-80 if x < 0 else 80)
        out += post
    segs = {"stud": 1, "lowpoly": 1, "midpoly": 2, "highpoly": 4}[ctx.style]
    for i in range(n - 1):
        x0, x1 = xs[i], xs[i + 1]
        if down in (i, i + 1):   # rope dropped to the floor from the standing post
            xs_up = x0 if down == i + 1 else x1
            xs_dn = x1 if down == i + 1 else x0
            out.append(_beam(ctx, (xs_up, 2.9, 0), (xs_dn * 0.7 + xs_up * 0.3, 0.1, -0.4), 0.15, mat="fabric", color=rope, collide=False))
            continue
        for k in range(segs):
            ta, tb = k / segs, (k + 1) / segs
            ya = 2.9 - 0.5 * 4 * ta * (1 - ta) * (1 if segs > 1 else 0)
            yb = 2.9 - 0.5 * 4 * tb * (1 - tb) * (1 if segs > 1 else 0)
            out.append(_beam(ctx, (x0 + (x1 - x0) * ta, ya, 0), (x0 + (x1 - x0) * tb, yb, 0), 0.15, ext=0.05, mat="fabric", color=rope,
                             collide=False))
    return out


@kit("info_plaque", "exhibit info plaque with text: standing lectern or wall plate with a picture light",
     {"kind": ("stand", ["stand", "wall"]), "y": (5, 3, 12)}, footprint=(3, 2), tags=("museum",))
def info_plaque(ctx, kind, y):
    ab = _abandoned(ctx)
    brass = _col(ctx, BRASS)
    out = []
    if kind == "stand":
        out.append(part(ctx, "B", (1.4, 0.2, 1.0), (0, 0.1, 0), mat="metal", color=brass))
        out.append(_up(ctx, 0.3, 3.2, (0, 1.8, 0), mat="metal", color=brass))
        th = 35
        n = (0, math.sin(math.radians(th)), -math.cos(math.radians(th)))
        c = (0, 3.6, 0)
        out.append(part(ctx, "B", (2.6, 1.8, 0.2), c, rot=(th, 0, 0), mat="wood", role="secondary"))
        out.append(_text(part(ctx, "B", (2.3, 1.5, 0.05), (0, c[1] + n[1] * 0.12, n[2] * 0.12), rot=(th, 0, 0), mat="paint",
                              role="primary", collide=False)))
        if ab:
            _rotate_group(out, (0, 0, 0), rz=6)
    else:
        out.append(part(ctx, "B", (2.6, 1.8, 0.15), (0, y, 0), mat="metal", color=brass))
        out.append(_text(part(ctx, "B", (2.3, 1.5, 0.05), (0, y, -0.1), mat="paint", role="primary", collide=False)))
        out.append(part(ctx, "B", (0.1, 0.1, 0.8), (0, y + 1.3, -0.35), mat="metal", color=brass, collide=False))
        lit = not ab
        out.append(part(ctx, "B", (1.8, 0.15, 0.25), (0, y + 1.3, -0.75), mat="neon" if lit else "metal", color=(255, 230, 180) if lit else brass,
                        collide=False, light=light("spot", (255, 220, 170), 1.2, 8, angle=60, face="Bottom") if lit else None))
    return out


# =========================================================================== subway / urban

@kit("subway_car", "subway train car along X: steel shell, window band, sliding doors both sides, livery stripe, seats, poles, ceiling light",
     {"length": (40, 20, 60)}, footprint=(40, 10), tags=("urban",))
def subway_car(ctx, length):
    rng, ab = ctx.rng, _abandoned(ctx)
    L = _sn(ctx, length)
    W, fy, ry = 9.0, 2.6, 11.0
    body, dark = _col(ctx, STEEL), _col(ctx, (44, 44, 48))
    stripe = ctx.color("paint", "accent")
    out = [part(ctx, "B", (L - 6, 1.6, W - 2.6), (0, 1.6, 0), mat="metal", color=dark)]
    for bx in (-L * 0.36, L * 0.36):
        out.append(part(ctx, "B", (5, 0.8, W - 2.4), (bx, 1.1, 0), mat="metal", color=dark))
        for dx in (-1.6, 1.6):
            for sz in (-1, 1):
                out.append(part(ctx, "C", (0.5, 2.0, 2.0), (bx + dx, 1.0, sz * (W / 2 - 1.0)), rot=(0, 90, 0), mat="metal",
                                color=_col(ctx, (70, 66, 62))))
    out.append(part(ctx, "B", (L, 0.4, W), (0, fy - 0.2, 0), mat="paint", color=_col(ctx, (90, 92, 96))))
    out.append(part(ctx, "B", (L, 0.5, W - 1.2), (0, ry, 0), mat="metal", color=body))
    if _round(ctx):
        for sz in (-1, 1):
            out.append(part(ctx, "C", (L, 1.4, 1.4), (0, ry - 0.35, sz * (W / 2 - 0.7)), mat="metal", color=body))
    elif ctx.style == "lowpoly":
        for sz in (-1, 1):
            out.append(part(ctx, "W", (L, 1.0, 0.6), (0, ry - 0.25, sz * (W / 2 - 0.3)), rot=(0, 0 if sz < 0 else 180, 0), mat="metal",
                            color=body))
    else:
        out.append(part(ctx, "B", (L, 0.5, W), (0, ry - 0.5, 0), mat="metal", color=body))
    doors = [-L / 3, 0, L / 3] if L >= 30 else [-L / 4, L / 4]
    dw = 4.0
    step = 4.0 if _stud(ctx) else 3.5
    open_leaf = (doors[0], -1) if ab else None
    for sz in (-1, 1):
        zw = sz * (W / 2 - 0.15)
        out.append(part(ctx, "B", (L, 3.2, 0.3), (0, fy + 1.6, zw), mat="metal", color=body))
        out.append(part(ctx, "B", (L, 1.95, 0.3), (0, 9.775, zw), mat="metal", color=body))
        out.append(part(ctx, "B", (L - 0.4, 3.0, 0.12), (0, 7.3, zw), mat="glass", color=(150, 180, 200) if not ab else (110, 120, 120), t=0.5))
        out.append(part(ctx, "B", (L, 0.45, 0.06), (0, 5.2, zw + sz * 0.18), mat="paint", color=stripe))
        x = -L / 2 + 1.5
        while x <= L / 2 - 1.5:
            if not any(abs(x - dc) < dw / 2 + 0.5 for dc in doors):
                out.append(part(ctx, "B", (0.7, 3.0, 0.32), (x, 7.3, zw), mat="metal", color=body))
            x += step
        for dc in doors:
            for s in (-1, 1):
                if open_leaf == (dc, sz) and s < 0:
                    continue
                out.append(part(ctx, "B", (1.95, 6.2, 0.14), (dc + s * 0.98, fy + 3.2, zw + sz * 0.16), mat="metal", color=shade(body, 0.92)))
                out.append(part(ctx, "B", (1.1, 2.2, 0.06), (dc + s * 0.98, 7.2, zw + sz * 0.24), mat="glass", color=(150, 180, 200), t=0.45))
            if _hi(ctx):
                out.append(part(ctx, "B", (dw + 0.4, 0.3, 0.1), (dc, fy + 6.4, zw + sz * 0.2), mat="paint", color=stripe))
        dest = _text(part(ctx, "B", (5, 0.9, 0.06), (L / 2 - 4, 9.8, zw + sz * 0.18), mat="neon" if not ab else "paint",
                          color=(255, 170, 60) if not ab else (40, 40, 40), collide=False))
        out.append(dest)
    for ex in (-1, 1):
        out.append(part(ctx, "B", (0.3, ry - fy, W), (ex * (L / 2 - 0.15), (fy + ry) / 2, 0), mat="metal", color=body))
        out.append(part(ctx, "B", (0.08, 3.0, 3.2), (ex * (L / 2 + 0.02), 7.3, 0), mat="glass", color=(150, 180, 200), t=0.4))
        if _round(ctx):
            for sz in (-1, 1):
                lt = light("spot", (255, 245, 220), 2.0, 40, angle=40, face="Right") if ex > 0 and sz < 0 and not ab else None
                out.append(part(ctx, "B", (0.08, 0.5, 0.8), (ex * (L / 2 + 0.04), 4.2, sz * 2.6), mat="neon" if not ab else "glass",
                                color=(255, 245, 220) if not ab else (90, 90, 90), collide=False, light=lt))
    bounds = [-L / 2 + 0.8]
    for dc in doors:
        bounds += [dc - dw / 2 - 0.4, dc + dw / 2 + 0.4]
    bounds.append(L / 2 - 0.8)
    seat = ctx.color("fabric", "secondary")
    for k in range(0, len(bounds), 2):
        x0, x1 = bounds[k], bounds[k + 1]
        if x1 - x0 < 1.5:
            continue
        for sz in (-1, 1):
            out.append(part(ctx, "B", (x1 - x0, 0.5, 1.6), ((x0 + x1) / 2, fy + 1.6, sz * (W / 2 - 1.2)), mat="fabric", color=seat))
            out.append(part(ctx, "B", (x1 - x0, 1.8, 0.25), ((x0 + x1) / 2, fy + 2.8, sz * (W / 2 - 0.45)), mat="fabric", color=seat))
            if _round(ctx):
                out.append(part(ctx, "B", (x1 - x0 - 0.4, 1.3, 0.15), ((x0 + x1) / 2, fy + 0.65, sz * (W / 2 - 1.9)), mat="metal", color=dark))
    pole_c = _col(ctx, (210, 212, 216))
    for dc in doors:
        for sz in (-1, 1):
            out.append(_up(ctx, 0.18, ry - fy - 0.5, (dc, fy + (ry - fy - 0.5) / 2, sz * 2.2), mat="metal", color=pole_c, collide=False))
    for sz in (-1, 1):
        if _round(ctx):
            out.append(part(ctx, "C", (L - 2, 0.15, 0.15), (0, ry - 1.6, sz * 2.2), mat="metal", color=pole_c, collide=False))
        else:
            out.append(part(ctx, "B", (L - 2, 0.15, 0.15), (0, ry - 1.6, sz * 2.2), mat="metal", color=pole_c, collide=False))
    if not ab:
        out.append(part(ctx, "B", (L - 3, 0.12, 0.9), (0, ry - 0.33, 0), mat="neon", color=(235, 245, 255), collide=False,
                        light=light("surface", (230, 240, 255), 1.0, 14, angle=120, face="Bottom", shadows=False)))
    else:   # dead strip with one flickering tube
        out.append(part(ctx, "B", (L - 3, 0.12, 0.9), (0, ry - 0.33, 0), mat="plastic", color=(150, 150, 150), collide=False))
        out.append(part(ctx, "B", (3, 0.14, 0.9), (L * 0.2, ry - 0.34, 0), mat="neon", color=(200, 220, 230), collide=False,
                        light=light("point", (200, 220, 230), 0.5, 10, shadows=False)))
        out += transform(papers(ctx, 4), (0, fy, 0))
        for j in range(4):   # spray tags clustered by the first door
            out.append(part(ctx, "B", (rng.uniform(1.0, 2.2), rng.uniform(0.6, 1.4), 0.05),
                            (doors[0] + 3.2 + j * 0.9, fy + 1.2 + rng.uniform(0, 1.4), -W / 2 - 0.05),
                            color=rng.choice(((220, 60, 160), (60, 200, 230), (240, 220, 50))), collide=False, cast=False))
    if _hi(ctx):
        for x in (-L / 4, L / 4):
            out.append(part(ctx, "B", (4, 0.8, 4), (x, ry + 0.65, 0), mat="metal", color=shade(body, 0.85)))
    return out


@kit("platform_edge", "subway platform edge along X: concrete coping, yellow safety line, tactile strip, drop face to the track (-Z)",
     {"length": (24, 8, 80)}, footprint=(24, 4), tags=("urban",))
def platform_edge(ctx, length):
    rng, ab = ctx.rng, _abandoned(ctx)
    L = _sn(ctx, length)
    yellow = _col(ctx, SAFETY)
    out = []
    seg = 4.0 if _round(ctx) else L
    nseg = max(1, int(round(L / seg)))
    seg = L / nseg
    missing = rng.randrange(nseg) if ab and nseg > 2 else -1
    for i in range(nseg):
        x = -L / 2 + seg * (i + 0.5)
        if i == missing:
            out.append(part(ctx, "B", (seg - 0.6, 0.15, 1.2), (x, -0.45, -0.7), mat="concrete", color=_col(ctx, (70, 68, 64))))
            out.append(part(ctx, "B", (1.0, 0.4, 0.8), (x + 0.6, -0.3, -0.5), rot=(10, 30, 15), mat="concrete"))
            continue
        out.append(part(ctx, "B", (seg - (0.05 if _round(ctx) else 0), 0.4, 1.4), (x, -0.2, -0.7), mat="concrete",
                        color=shade(ctx.color("concrete"), 1.15 if i % 2 else 1.1)))
        out.append(part(ctx, "B", (seg, 0.05, 0.5), (x, 0.025, -0.9), mat="paint", color=yellow, collide=False))
    out.append(part(ctx, "B", (L, 0.08, 1.2), (0, 0.04, 0.6), mat="plastic", color=yellow, collide=False))
    if _hi(ctx):
        sp = max(0.9, L / 30)
        nb = int(L / sp)
        for row in (0.3, 0.9):
            for i in range(nb):
                out.append(part(ctx, "C", (0.06, 0.3, 0.3), (-L / 2 + sp * (i + 0.5), 0.11, row), rot=(0, 0, 90), mat="plastic",
                                color=shade(yellow, 0.92), collide=False, cast=False))
    elif ctx.style == "midpoly":
        sp = max(1.2, L / 30)
        for i in range(int(L / sp)):
            out.append(part(ctx, "B", (0.25, 0.06, 1.0), (-L / 2 + sp * (i + 0.5), 0.1, 0.6), mat="plastic", color=shade(yellow, 0.92),
                            collide=False, cast=False))
    out.append(part(ctx, "B", (L, 4.5, 0.4), (0, -2.65, -1.2), mat="concrete", color=shade(ctx.color("concrete"), 0.8)))
    if _round(ctx):
        out.append(part(ctx, "B", (L, 0.15, 0.25), (0, -0.07, -1.5), mat="plastic", color=(30, 30, 32)))
    if ctx.state != "new":   # grime streaks running down the drop face
        for i in range(int(L / 6) + 1):
            out.append(part(ctx, "B", (rng.uniform(0.3, 1.0), rng.uniform(1.0, 3.0), 0.05), (rng.uniform(-L / 2 + 1, L / 2 - 1), -1.6, -1.43),
                            color=(60, 56, 50), t=0.4, collide=False, cast=False))
    if ab:
        out.append(part(ctx, "C", (0.05, 3, 2), (rng.uniform(-L / 3, L / 3), 0.03, 1.6), rot=(0, 0, 90), mat="water", color=(60, 80, 90),
                        t=0.35, collide=False, cast=False))
    return out


@kit("turnstile", "row of subway tripod turnstiles: cabinets with card readers and three-arm rotors, lanes along X",
     {"n": (3, 1, 6)}, footprint=(10, 4), tags=("urban",))
def turnstile(ctx, n):
    rng, ab = ctx.rng, _abandoned(ctx)
    n = int(n)
    lane = 3.2
    steel = _col(ctx, STEEL)
    trim = ctx.color("metal", "trim")
    out = []
    for i in range(n + 1):
        x = (i - n / 2) * lane
        out.append(part(ctx, "B", (1.2, 3.4, 3.2), (x, 1.7, 0), rot=(0, 0, 4 if ab and i == 1 else 0), mat="metal", color=steel))
        out.append(part(ctx, "B", (1.4, 0.15, 3.4), (x, 3.47, 0), mat="metal", color=trim))
        if _round(ctx):
            for sz in (-1, 1):
                out.append(_cyl_y(ctx, 1.2, 3.4, (x, 1.7, sz * 1.6), mat="metal", color=steel))
            out.append(part(ctx, "B", (1.25, 0.6, 3.25), (x, 0.3, 0), mat="metal", color=trim))
        if i < n:
            ok = not ab
            out.append(part(ctx, "B", (0.6, 0.08, 0.6), (x + 0.3, 3.58, -0.9), mat="neon" if ok else "glass",
                            color=(60, 255, 120) if ok else (120, 40, 40), collide=False,
                            light=light("point", (60, 255, 120), 0.4, 4, shadows=False) if ok else None))
            hub = (x + 0.75, 2.8, -0.3)
            out.append(part(ctx, "C", (0.4, 0.5, 0.5), hub, mat="metal", color=trim))
            shp = "C" if _round(ctx) else "B"
            arms = [(x + lane - 0.9, hub[1], hub[2]), (hub[0] + 0.9, hub[1] - 1.1, hub[2] + 0.6), (hub[0] + 0.9, hub[1] - 1.1, hub[2] - 0.6)]
            for j, tip in enumerate(arms):
                if ab and i == 0 and j == 0:   # bent arm hanging down
                    tip = (hub[0] + 0.5, hub[1] - 1.6, hub[2] - 0.2)
                out.append(_beam(ctx, hub, tip, 0.15, shape=shp, mat="metal", color=steel))
    return out


@kit("vending_machine", "lit vending machine (drinks or snacks) with product rows, keypad, pickup bin, logo strip (back at +Z)",
     {"kind": ("drinks", ["drinks", "snacks"])}, footprint=(4, 3), tags=("urban",))
def vending_machine(ctx, kind):
    rng, ab = ctx.rng, _abandoned(ctx)
    W, H, D = 4.0, 7.0, 3.0
    out = [part(ctx, "B", (W, H, D), (0, H / 2, 0), mat="paint", role="accent")]
    gx, gy, gw, gh = -W * 0.15, H * 0.58, W * 0.6, H * 0.6
    out.append(part(ctx, "B", (gw + 0.1, gh + 0.1, 0.1), (gx, gy, -D / 2 - 0.02), mat="glass", color=(200, 225, 235), t=0.55))
    out.append(part(ctx, "B", (gw, gh, 0.1), (gx, gy, -D / 2 + 0.7), mat="neon" if not ab else "plastic",
                    color=(240, 245, 255) if not ab else (120, 120, 120), collide=False,
                    light=light("surface", (235, 242, 255), 0.6, 10, angle=120, face="Front", shadows=False) if not ab else None))
    rows, cols = {"stud": (3, 3), "lowpoly": (4, 3), "midpoly": (5, 4), "highpoly": (6, 5)}[ctx.style]
    prod = [ctx.color("plastic", "accent"), ctx.color("plastic", "primary"), _col(ctx, (220, 40, 40)), _col(ctx, (40, 120, 220)),
            _col(ctx, (250, 200, 40))]
    cw, rh = gw / cols, gh / rows
    for r_ in range(rows):
        y = gy - gh / 2 + rh * (r_ + 0.15)
        if _hi(ctx):
            out.append(part(ctx, "B", (gw, 0.06, 0.8), (gx, y - 0.05, -D / 2 + 0.4), mat="metal", color=(160, 160, 166), collide=False))
        for c in range(cols):
            if ab and rng.random() < 0.35:
                continue
            x = gx - gw / 2 + cw * (c + 0.5)
            col = prod[c % len(prod)]   # one product per column, as stocked
            if kind == "drinks":
                hh = rh * 0.6
                out.append(_up(ctx, min(0.5, cw * 0.7), hh, (x, y + hh / 2, -D / 2 + 0.35), mat="metal", color=col, collide=False))
            else:
                out.append(part(ctx, "B", (cw * 0.7, rh * 0.55, 0.15), (x, y + rh * 0.3, -D / 2 + 0.35), rot=(-8, 0, 0), mat="plastic",
                                color=col, collide=False))
    out.append(part(ctx, "B", (W * 0.25, H * 0.35, 0.12), (W * 0.33, H * 0.62, -D / 2 - 0.02), mat="metal", role="trim"))
    out.append(part(ctx, "B", (W * 0.18, 0.4, 0.06), (W * 0.33, H * 0.74, -D / 2 - 0.09), mat="neon" if not ab else "plastic",
                    color=(90, 255, 140) if not ab else (40, 40, 40), collide=False))
    if _hi(ctx):
        for r_ in range(3):
            for c in range(3):
                out.append(part(ctx, "B", (0.18, 0.18, 0.06), (W * 0.33 - 0.25 + c * 0.25, H * 0.62 - r_ * 0.28, -D / 2 - 0.1),
                                color=(210, 210, 214), collide=False))
    else:
        out.append(part(ctx, "B", (W * 0.18, 0.8, 0.06), (W * 0.33, H * 0.6, -D / 2 - 0.09), color=(210, 210, 214), collide=False))
    out.append(part(ctx, "B", (0.25, 0.4, 0.06), (W * 0.33, H * 0.48, -D / 2 - 0.09), color=(30, 30, 30), collide=False))
    out.append(part(ctx, "B", (W * 0.6, 0.8, 0.15), (gx, 1.2, -D / 2 - 0.03), color=(24, 24, 26)))
    out.append(_text(part(ctx, "B", (W, 0.8, 0.1), (0, H - 0.5, -D / 2 - 0.03), mat="neon" if not ab else "paint",
                          color=shade(ctx.palette["accent"], 1.3), collide=False)))
    if ab:
        cx0, cy0 = gx + 0.4, gy + 0.6
        for a in (30, 110, 200, 290):
            out.append(part(ctx, "B", (1.1, 0.05, 0.05), (cx0 + math.cos(math.radians(a)) * 0.55, cy0 + math.sin(math.radians(a)) * 0.55,
                            -D / 2 - 0.09), rot=(0, 0, a), color=(230, 236, 232), t=0.3, collide=False, cast=False))
        _rotate_group(out, (0, 0, -D / 2), rx=-6)
    return out


@kit("tiled_pillar", "square station pillar clad in tile: dark skirt, colour band, cap, station name panel with text",
     {"h": (12, 6, 30), "w": (2.5, 1.5, 5)}, footprint=(3, 3), tags=("urban",))
def tiled_pillar(ctx, h, w):
    rng, ab = ctx.rng, _abandoned(ctx)
    h, w = _sn(ctx, h), _sn(ctx, w)
    tile = ctx.color("tile")
    out = [part(ctx, "B", (w, h, w), (0, h / 2, 0), mat="tile"),
           part(ctx, "B", (w + 0.3, 1.4, w + 0.3), (0, 0.7, 0), mat="tile", role="trim"),
           part(ctx, "B", (w + 0.4, 0.8, w + 0.4), (0, h - 0.4, 0), mat="tile", role="trim"),
           part(ctx, "B", (w + 0.12, 0.8, w + 0.12), (0, h * 0.5, 0), mat="tile", color=ctx.color("tile", "accent"))]
    out.append(_text(part(ctx, "B", (w - 0.3, 0.9, 0.08), (0, h * 0.5 + 1.3, -w / 2 - 0.08), mat="paint", role="accent", collide=False)))
    if _round(ctx):
        for sx in (-1, 1):
            for sz in (-1, 1):
                out.append(part(ctx, "B", (0.2, h - 2.2, 0.2), (sx * w / 2, 1.4 + (h - 2.2) / 2, sz * w / 2), mat="tile", color=shade(tile, 0.9)))
    if _hi(ctx):
        grout = shade(tile, 0.75)
        for k in range(1, int(h - 2.2)):
            out.append(part(ctx, "B", (w + 0.02, 0.05, w + 0.02), (0, 1.4 + k, 0), mat="tile", color=grout, collide=False, cast=False))
        out.append(part(ctx, "B", (0.05, h - 2.2, w + 0.02), (0, 1.4 + (h - 2.2) / 2, 0), mat="tile", color=grout, collide=False, cast=False))
        out.append(part(ctx, "B", (w + 0.02, h - 2.2, 0.05), (0, 1.4 + (h - 2.2) / 2, 0), mat="tile", color=grout, collide=False, cast=False))
    if ctx.state != "new":
        out.append(part(ctx, "B", (w + 0.32, 0.4, w + 0.32), (0, 1.6, 0), color=(90, 78, 60), t=0.5, collide=False, cast=False))
    if ab:   # tiles popped off near the base and a corner, lying on the floor
        for k in range(4):
            sx = rng.choice((-1, 1))
            out.append(part(ctx, "B", (0.9, 0.9, 0.05), (sx * rng.uniform(0, w / 2 - 0.5), rng.uniform(1.8, 4.0), -w / 2 - 0.03),
                            mat="concrete", collide=False))
            out.append(part(ctx, "B", (0.8, 0.06, 0.8), (rng.uniform(-w, w), 0.03, -w / 2 - rng.uniform(0.4, 1.5)), rot=(0, rng.uniform(0, 90), 0),
                            mat="tile", collide=False, cast=False))
    return out


# =========================================================================== obby / minigame

def _obby_base(ctx, w, h):
    out = [part(ctx, "B", (_sn(ctx, w), _sn(ctx, h) if h >= 0.75 else h, _sn(ctx, w)), (0, h / 2, 0), mat="plastic", color=ctx.color("plastic", "primary"))]
    if ctx.style == "lowpoly":
        out.append(part(ctx, "B", (w - 0.6, 0.3, w - 0.6), (0, h + 0.15, 0), mat="plastic", color=shade(ctx.color("plastic", "primary"), 1.12)))
    elif _round(ctx):
        out.append(part(ctx, "B", (w + 0.2, 0.2, w + 0.2), (0, h - 0.07, 0), mat="plastic", color=ctx.color("plastic", "trim")))   # lip 0.03 above the top
    return out


@kit("checkpoint", "obby checkpoint pad: glowing ring, white centre, flag on a pole, green light (name Checkpoint)", {},
     footprint=(5, 5), tags=("obby",))
def checkpoint(ctx):
    ab = _abandoned(ctx)
    green = (60, 255, 120)
    out = _prism(ctx, 5, 0.4, (0, 0.2, 0), mat="plastic", role="trim")
    ring = _prism(ctx, 4.2, 0.1, (0, 0.45, 0), mat="neon" if not ab else "plastic", color=green if not ab else (60, 120, 70), name="Checkpoint")
    ring[0]["light"] = light("point", green, 1.2 if not ab else 0.3, 14, shadows=False)
    out += ring
    out += _prism(ctx, 3.4, 0.12, (0, 0.52, 0), mat="plastic", color=_col(ctx, WHITE), name="Checkpoint")
    out.append(_up(ctx, 0.25, 7, (1.9, 3.9, 1.9), mat="metal", color=_col(ctx, WHITE)))
    out.append(_ball(ctx, (0.45, 0.45, 0.45), (1.9, 7.5, 1.9), mat="metal", color=_col(ctx, GOLD)))
    flag = ctx.color("fabric", "accent")
    if ab:
        out.append(part(ctx, "B", (1.4, 0.9, 0.1), (2.6, 6.2, 1.9), rot=(0, 0, -18), mat="fabric", color=flag, collide=False))
    elif _round(ctx):
        out.append(part(ctx, "B", (1.2, 1.5, 0.1), (2.5, 6.6, 1.9), rot=(0, 6, 0), mat="fabric", color=flag, collide=False))
        out.append(part(ctx, "B", (1.2, 1.5, 0.1), (3.65, 6.6, 1.82), rot=(0, -8, 0), mat="fabric", color=flag, collide=False))
    else:
        out.append(part(ctx, "B", (2.4, 1.5, 0.1), (3.1, 6.6, 1.9), mat="fabric", color=flag, collide=False))
    return out


@kit("obby_platform", "obby block: plain, checkpoint pad, kill brick (neon red), spinner bar, or climbing truss",
     {"kind": ("plain", ["plain", "checkpoint", "kill", "spinner", "truss"]), "w": (8, 3, 30), "h": (1, 0.4, 20),
      "tall": (12, 4, 40)}, footprint=(8, 8), tags=("obby",))
def obby_platform(ctx, kind, w, h, tall):
    rng, ab = ctx.rng, _abandoned(ctx)
    red = (255, 40, 40)
    if kind == "truss":
        tall = _sn(ctx, tall)
        steel = _col(ctx, (170, 172, 176))
        out = [part(ctx, "B", (3, 0.4, 3), (0, 0.2, 0), mat="plastic", role="trim")]
        for sx in (-1, 1):
            for sz in (-1, 1):
                out.append(part(ctx, "B", (0.3, tall, 0.3), (sx, 0.4 + tall / 2, sz), mat="metal", color=steel, name="Truss"))
        levels = max(2, int(tall / 2))
        for k in range(levels):
            y = 0.4 + tall * (k + 0.5) / levels
            for sz in (-1, 1):
                out.append(part(ctx, "B", (2, 0.25, 0.25), (0, y, sz), mat="metal", color=steel, name="Truss"))
            sx = 1 if k % 2 else -1
            for side in (-1, 1):
                out.append(_beam(ctx, (side, y - tall / levels / 2, -sx), (side, y + tall / levels / 2, sx), 0.2, mat="metal", color=steel))
        if ab:
            _rotate_group(out, (0, 0, 0), rz=3)
        return out
    out = _obby_base(ctx, w, h)
    if kind == "checkpoint":
        out += transform(checkpoint(ctx), (0, h, 0))
    elif kind == "kill":
        on = not ab
        out.append(part(ctx, "B", (w * 0.8, 0.3, w * 0.8), (0, h + 0.15, 0), mat="neon" if on else "plastic", color=red if on else (150, 50, 46),
                        name="KillBrick", light=light("point", red, 0.8, 10, shadows=False) if on else None))
        k = {"stud": 4, "lowpoly": 4, "midpoly": 6, "highpoly": 8}[ctx.style]
        sw = w / k
        for i in range(k):   # black/yellow hazard edge on the front and back
            for sz in (-1, 1):
                out.append(part(ctx, "B", (sw, 0.15, w * 0.1), (-w / 2 + sw * (i + 0.5), h + 0.075, sz * w * 0.45), mat="plastic",
                                color=SAFETY if (i + (sz > 0)) % 2 else (30, 30, 30)))
    elif kind == "spinner":
        out.append(_up(ctx, 1.2, 1.6, (0, h + 0.8, 0), mat="metal", role="trim"))
        k = {"stud": 4, "lowpoly": 4, "midpoly": 6, "highpoly": 8}[ctx.style]
        bl = w * 0.95
        for i in range(k):
            out.append(part(ctx, "B", (bl / k, 0.6, 0.6), (-bl / 2 + bl / k * (i + 0.5), h + 1.4, 0), mat="neon" if i % 2 == 0 and not ab else "plastic",
                            color=red if i % 2 == 0 else _col(ctx, WHITE), name="Spinner"))
        out.append(_ball(ctx, (0.8, 0.8, 0.8), (0, h + 1.8, 0), mat="metal", role="trim"))
        if _round(ctx):   # motion ghosts: faint copies trailing the bar
            for a in (-18, -34):
                out.append(part(ctx, "B", (bl, 0.5, 0.5), (0, h + 1.4, 0), rot=(0, a, 0), mat="glass", color=(255, 120, 110), t=0.85,
                                collide=False, cast=False))
    if ab and kind != "checkpoint":
        out.append(part(ctx, "W", (w * 0.3, h * 0.6 + 0.2, w * 0.25), (w * 0.4, (h * 0.6 + 0.2) / 2, -w * 0.62), rot=(0, 30, 0),
                        mat="plastic", color=ctx.color("plastic", "primary")))
    return out


@kit("finish_pad", "obby finish: checkerboard pad, FINISH banner arch with text, gold trim, light (name Finish)",
     {"w": (12, 6, 24)}, footprint=(13, 13), tags=("obby",))
def finish_pad(ctx, w):
    rng, ab = ctx.rng, _abandoned(ctx)
    w = _sn(ctx, w)
    out = [part(ctx, "B", (w + 1, 0.6, w + 1), (0, 0.3, 0), mat="plastic", role="trim")]
    k = {"stud": 4, "lowpoly": 4, "midpoly": 6, "highpoly": 8}[ctx.style]
    t = w / k
    for i in range(k):
        for j in range(k):
            if ab and rng.random() < 0.08:
                continue
            out.append(part(ctx, "B", (t, 0.15, t), (-w / 2 + t * (i + 0.5), 0.675, -w / 2 + t * (j + 0.5)), mat="plastic",
                            color=_col(ctx, WHITE) if (i + j) % 2 else (30, 30, 32), name="Finish"))
    gold = _col(ctx, GOLD)
    if _round(ctx):
        for sx, sz, lx, lz in ((0, -1, w + 1, 0.2), (0, 1, w + 1, 0.2), (-1, 0, 0.2, w + 1), (1, 0, 0.2, w + 1)):
            out.append(part(ctx, "B", (lx, 0.12, lz), (sx * (w + 1) / 2, 0.66, sz * (w + 1) / 2), mat="neon" if not ab else "metal", color=gold,
                            collide=False))
    for sx in (-1, 1):
        ph = 10 if not (ab and sx > 0) else 8.6
        out.append(part(ctx, "B", (1, ph, 1), (sx * (w / 2 + 0.2), 0.6 + ph / 2, 0), mat="metal", role="trim"))
    banner = [part(ctx, "B", (w + 1.4, 2.4, 0.6), (0, 9.5, 0), mat="paint", role="accent"),
              _text(part(ctx, "B", (w - 0.6, 1.8, 0.1), (0, 9.5, -0.36), mat="paint", color=_col(ctx, WHITE), collide=False))]
    if ab:
        _rotate_group(banner, (-(w / 2 + 0.2), 10.6, 0), rz=-7)
    out += banner
    on = not ab
    out.append(part(ctx, "B", (w * 0.6, 0.15, 0.3), (0, 10.78, -0.2), mat="neon" if on else "metal", color=gold, collide=False,
                    light=light("point", (255, 220, 120), 1.5, 24) if on else None))
    if _hi(ctx) and not ab:   # trophy on the back edge, confetti around the centre (swept away once abandoned)
        out.append(part(ctx, "B", (1.2, 0.4, 1.2), (0, 0.95, w / 2 - 1.2), mat="metal", color=(40, 40, 40)))
        out.append(_cyl_y(ctx, 0.3, 0.8, (0, 1.55, w / 2 - 1.2), mat="metal", color=gold))
        out.append(part(ctx, "S", (1.0, 1.0, 1.0), (0, 2.3, w / 2 - 1.2), mat="metal", color=gold))
        for _ in range(10):
            a, rr = rng.uniform(0, 2 * math.pi), abs(rng.gauss(0, w / 6))
            out.append(part(ctx, "B", (0.3, 0.05, 0.3), (math.sin(a) * rr, 0.78, math.cos(a) * rr), rot=(0, rng.uniform(0, 90), 0),
                            color=rng.choice((ctx.palette["accent"], (60, 160, 255), SAFETY)), collide=False, cast=False))
    return out


@kit("arena_cover", "low cover for minigame arenas: concrete wall, sandbag stack or crate pile (along X)",
     {"length": (8, 4, 20), "h": (3.5, 2, 6), "kind": ("wall", ["wall", "sandbag", "crate"])}, footprint=(8, 2), tags=("obby",))
def arena_cover(ctx, length, h, kind):
    rng, ab = ctx.rng, _abandoned(ctx)
    L, h = _sn(ctx, length), _sn(ctx, h)
    out = []
    if kind == "wall":
        pieces = [(-L / 2, L / 2)] if not ab else [(-L / 2, -L * 0.1), (L * 0.15, L / 2)]
        for x0, x1 in pieces:
            out.append(part(ctx, "B", (x1 - x0, h, 1.2), ((x0 + x1) / 2, h / 2, 0), mat="concrete", vary=0.03))
            out.append(part(ctx, "B", (x1 - x0 + 0.2, 0.3, 1.4), ((x0 + x1) / 2, h + 0.15, 0), mat="concrete", role="trim"))
        if _round(ctx):
            for i in range(1, int(L / 4)):
                x = -L / 2 + 4 * i
                if ab and -L * 0.1 < x < L * 0.15:
                    continue
                out.append(part(ctx, "B", (0.1, h - 0.2, 1.25), (x, h / 2, 0), mat="concrete", color=shade(ctx.color("concrete"), 0.8)))
        if ctx.state != "new":   # chipped top corner, chunks at the foot
            out.append(part(ctx, "B", (0.8, 0.5, 0.6), (L / 2 - 0.5, h + 0.1, -0.5), mat="concrete", color=shade(ctx.color("concrete"), 0.7)))
            for _ in range(3):
                s = rng.uniform(0.3, 0.7)
                out.append(part(ctx, "B", (s, s * 0.6, s), (L / 2 + rng.uniform(-0.5, 0.8), s * 0.3, -1.0 - rng.uniform(0, 0.8)),
                                rot=(rng.uniform(-20, 20), rng.uniform(0, 90), 0), mat="concrete"))
        if ab:
            for k in range(3):
                out.append(_beam(ctx, (-L * 0.1, 0.8 + k * 0.9, 0), (-L * 0.1 + rng.uniform(0.5, 1.2), 1.0 + k * 0.9, rng.uniform(-0.3, 0.3)),
                                 0.12, mat="rust", collide=False))
    elif kind == "sandbag":
        rows = max(2, int(h / 0.7))
        per = max(2, int(L / 1.6))
        for r_ in range(rows):
            off = 0.8 if r_ % 2 else 0
            for i in range(per - (1 if r_ % 2 else 0)):
                if ab and r_ == rows - 1 and rng.random() < 0.4:
                    continue
                x = -L / 2 + 0.8 + off + i * (L - 1.6) / max(1, per - 1)
                pos = (x, 0.35 + r_ * 0.65, rng.uniform(-0.08, 0.08))
                if _round(ctx):
                    out.append(part(ctx, "S", (1.7, 0.75, 1.0), pos, rot=(0, rng.uniform(-6, 6), 0), mat="fabric", color=ctx.color("sand", vary=0.06)))
                else:
                    out.append(part(ctx, "B", (1.6, 0.7, 1.0), pos, rot=(0, rng.uniform(-6, 6) if ctx.style == "lowpoly" else 0, 0),
                                    mat="fabric", color=ctx.color("sand")))
    else:
        for (x, y, z, s, yaw) in ((-L * 0.25, 0, 0, 3.0, 0), (-L * 0.25 + 0.3, 3.0, 0.1, 2.0, 12), (L * 0.2, 0, -0.2, 2.5, -8)):
            out.append(part(ctx, "B", (s, s, s), (x, y + s / 2, z), rot=(0, yaw if not _stud(ctx) else 0, 0), mat="plank", vary=0.06))
            if _round(ctx):
                for dy in (-s / 2 + 0.15, s / 2 - 0.15):
                    out += transform([part(ctx, "B", (s + 0.05, 0.3, 0.3), (0, dy, -s / 2), mat="wood", color=shade(ctx.color("plank"), 0.75))],
                                     (x, y + s / 2, z), yaw)
    return out


@kit("spawn_pad", "spawn location pad: trimmed slab, glowing inset ring, centre emblem, front chevrons (name SpawnLocation)",
     {"w": (6, 4, 12)}, footprint=(6, 6), tags=("obby",))
def spawn_pad(ctx, w):
    ab = _abandoned(ctx)
    w = _sn(ctx, w)
    acc = ctx.color("neon", "accent")
    on = not ab
    out = [part(ctx, "B", (w, 0.6, w), (0, 0.3, 0), mat="plastic", role="trim"),
           part(ctx, "B", (w - 1, 0.15, w - 1), (0, 0.675, 0), mat="plastic", color=ctx.color("plastic", "primary"), name="SpawnLocation")]
    for i, (sx, sz, lx, lz) in enumerate(((0, -1, w - 0.6, 0.2), (0, 1, w - 0.6, 0.2), (-1, 0, 0.2, w - 0.6), (1, 0, 0.2, w - 0.6))):
        out.append(part(ctx, "B", (lx, 0.14, lz), (sx * (w - 0.8) / 2, 0.68, sz * (w - 0.8) / 2), mat="neon" if on else "plastic",
                        color=acc if on else shade(acc, 0.5), collide=False,
                        light=light("point", acc, 1.0, 12, shadows=False) if on and i == 0 else None))
    out += _prism(ctx, w * 0.35, 0.12, (0, 0.8, 0), mat="plastic", color=acc)
    if _round(ctx):
        for k in range(2):
            for s in (-1, 1):
                out.append(part(ctx, "B", (0.9, 0.06, 0.25), (s * 0.3, 0.78, -w * 0.3 + k * 0.5), rot=(0, s * 45, 0), mat="plastic",
                                color=_col(ctx, WHITE), collide=False))
        for sx in (-1, 1):
            for sz in (-1, 1):
                out.append(_up(ctx, 0.5, 1.2, (sx * (w / 2 - 0.3), 1.2, sz * (w / 2 - 0.3)), mat="metal", role="trim"))
                out.append(part(ctx, "B", (0.45, 0.15, 0.45), (sx * (w / 2 - 0.3), 1.88, sz * (w / 2 - 0.3)), mat="neon" if on else "plastic",
                                color=acc, collide=False))
    if ab:
        out.append(part(ctx, "B", (1.2, 0.5, 1.0), (w / 2 + 0.3, 0.25, -w / 2 + 0.4), rot=(8, 25, 12), mat="plastic", role="trim"))
    return out


# =========================================================================== camp / winter

@kit("tent", "camping tent (A-frame ridge along Z or dome), door at -Z, groundsheet, guy lines",
     {"kind": ("a_frame", ["a_frame", "dome"]), "size": (6, 4, 12)}, footprint=(6, 8), tags=("camp",))
def tent(ctx, kind, size):
    rng, ab = ctx.rng, _abandoned(ctx)
    s = _sn(ctx, size)
    fab = ctx.color("fabric", "accent")
    dark = (40, 36, 32)
    out = []
    if kind == "a_frame":
        W, D, H = s * 0.8, s, s * 0.6 * (0.65 if ab else 1)
        out.append(part(ctx, "B", (W + 1, 0.06, D + 1), (0, 0.03, 0), mat="fabric", color=ctx.color("fabric", "secondary"), collide=False))
        for side in (-1, 1):
            out.append(part(ctx, "W", (D, H, W / 2), (side * W / 4, H / 2, 0), rot=(0, -90 * side, 0), mat="fabric", color=fab))
            out.append(part(ctx, "W", (0.06, H * 0.75, W * 0.3), (side * W * 0.15, H * 0.375, -D / 2 - 0.04), rot=(0, -90 * side, 0),
                            color=dark, collide=False))
        out.append(part(ctx, "B", (1.2, 0.3, 2.2), (0, 0.2, -D / 2 + 1.2), mat="fabric", color=_col(ctx, (70, 110, 160)), collide=False))
        if _round(ctx):
            ridge = part(ctx, "C", (D + 0.8, 0.2, 0.2), (0, H + 0.05, 0), rot=(0, 90, 0), mat="metal", color=(80, 80, 84), collide=False)
            if ab:
                ridge["r"] = [0, 90, 10]
            out.append(ridge)
            for sz in (-1, 1):
                out.append(part(ctx, "B", (0.15, H + 0.4, 0.15), (0, (H + 0.4) / 2, sz * (D / 2 + 0.1)), mat="metal", color=(80, 80, 84), collide=False))
                if ab and sz > 0:
                    continue
                stake = (0, 0.3, sz * (D / 2 + 2.2))
                out.append(_beam(ctx, (0, H + 0.3, sz * (D / 2 + 0.1)), stake, 0.06, mat="fabric", color=(220, 210, 180), collide=False))
                out.append(part(ctx, "B", (0.2, 0.6, 0.2), stake, mat="wood"))
            if _hi(ctx):
                out.append(part(ctx, "C", (W * 0.3, 0.35, 0.35), (0, H * 0.78, -D / 2 - 0.15), mat="fabric", color=shade(fab, 0.85), collide=False))
        if ab:   # a rip in the side
            out.append(part(ctx, "B", (0.08, H * 0.3, D * 0.25), (W * 0.22, H * 0.45, D * 0.1), rot=(0, 0, -34), color=dark, collide=False))
    else:
        r, H = s / 2, s * 0.45
        out += _prism(ctx, s + 1, 0.06, (0, 0.03, 0), mat="fabric", color=ctx.color("fabric", "secondary"), collide=False)
        if _stud(ctx):
            out += _cone(ctx, r, 0, H, 8, [fab, shade(fab, 0.9)])
        elif ctx.style == "lowpoly":
            out += _cone(ctx, r, 0, H, 6, [fab, shade(fab, 0.9)])
        else:
            out.append(part(ctx, "S", (s, 2 * H, s), (0, 0, 0), mat="fabric", color=fab))
            n = 8 if _hi(ctx) else 5
            for axis in (0, 1):
                pts = [(math.cos(math.pi * i / n) * r * 1.01, math.sin(math.pi * i / n) * H * 1.01) for i in range(n + 1)]
                for i in range(n):
                    a = (pts[i][0], pts[i][1], 0) if axis == 0 else (0, pts[i][1], pts[i][0])
                    b = (pts[i + 1][0], pts[i + 1][1], 0) if axis == 0 else (0, pts[i + 1][1], pts[i + 1][0])
                    # both hoops turned 45 degrees so they cross diagonally over the door
                    a, b = transform([{"p": list(a)}], (0, 0, 0), 45)[0]["p"], transform([{"p": list(b)}], (0, 0, 0), 45)[0]["p"]
                    out.append(_beam(ctx, a, b, 0.12, ext=0.1, mat="metal", color=(70, 70, 74), collide=False))
        out.append(part(ctx, "B", (1.6, min(2.2, H * 0.8), 0.1), (0, min(2.2, H * 0.8) / 2, -r * 0.9), color=dark, collide=False))
        if ab:
            _rotate_group(out, (0, 0, 0), rz=5)
    return out


@kit("log_seat", "log bench along X (carved seat top in the round styles), chocks, optional snow cap",
     {"length": (5, 3, 10), "snow": (0, 0, 1)}, footprint=(5, 2), tags=("camp", "nature"))
def log_seat(ctx, length, snow):
    rng, ab = ctx.rng, _abandoned(ctx)
    L = _sn(ctx, length)
    bark = ctx.color("wood", vary=0.05)
    bark = shade(bark, 0.8)
    out = []
    if _stud(ctx):
        out.append(part(ctx, "B", (L, 2, 2), (0, 1, 0), mat="wood", color=bark))
        top = 2.0
    elif ctx.style == "lowpoly":
        out.append(part(ctx, "B", (L, 1.4, 1.4), (0, 0.8, 0), mat="wood", color=bark))
        out.append(part(ctx, "B", (L, 1.4, 1.4), (0, 0.8, 0), rot=(45, 0, 0), mat="wood", color=shade(bark, 0.95)))
        top = 1.6
    else:
        out.append(part(ctx, "C", (L, 1.6, 1.6), (0, 0.8, 0), mat="wood", color=bark))
        out.append(part(ctx, "B", (L * 0.85, 0.12, 0.9), (0, 1.56, 0), mat="wood", color=_col(ctx, (196, 160, 110))))
        for sx in (-1, 1):
            out.append(part(ctx, "C", (0.08, 1.45, 1.45), (sx * L / 2, 0.8, 0), mat="wood", color=_col(ctx, (196, 160, 110))))
            if _hi(ctx):
                out.append(part(ctx, "C", (0.1, 0.8, 0.8), (sx * L / 2, 0.8, 0), mat="wood", color=_col(ctx, (160, 120, 80))))
        if _hi(ctx):
            out.append(_beam(ctx, (L * 0.2, 1.1, 0.6), (L * 0.25, 1.5, 1.2), 0.25, mat="wood", color=bark))
        top = 1.62
    for sx in (-1, 1):
        out.append(part(ctx, "W", (0.6, 0.5, 0.6), (sx * L * 0.35, 0.25, -0.9), mat="wood", color=shade(bark, 0.9)))
        out.append(part(ctx, "W", (0.6, 0.5, 0.6), (sx * L * 0.35, 0.25, 0.9), rot=(0, 180, 0), mat="wood", color=shade(bark, 0.9)))
    if snow:
        out.append(part(ctx, "B", (L * 0.9, 0.3, 1.0), (0, top + 0.15, 0.1), mat="snow", collide=False))
    if ctx.state != "new":   # moss along the shady back side
        out.append(part(ctx, "B", (L * 0.5, 0.4, 0.1), (-L * 0.15, 0.9, 0.82 if not _stud(ctx) else 1.02), mat="grass", collide=False))
    if ab:   # rot: a crack and mushrooms clustered at one end
        out.append(part(ctx, "B", (L * 0.4, 0.1, 0.05), (L * 0.1, 1.1, -0.82 if not _stud(ctx) else -1.02), color=(40, 30, 24), collide=False))
        for k in range(3):
            out.append(_up(ctx, 0.12, 0.3, (L / 2 - 0.3 - k * 0.3, 0.15, -0.9 - k * 0.15), mat="paper", color=(230, 220, 200), collide=False))
            out.append(_ball(ctx, (0.4, 0.2, 0.4), (L / 2 - 0.3 - k * 0.3, 0.35, -0.9 - k * 0.15), mat="plastic", color=(170, 100, 60), collide=False))
    return out


@kit("cabin_porch", "log cabin front porch: deck on footings, steps, posts, shed roof, log wall with door and lit window, railings, firewood",
     {"w": (12, 8, 24), "d": (6, 4, 10)}, footprint=(13, 10), tags=("camp",))
def cabin_porch(ctx, w, d):
    rng, ab = ctx.rng, _abandoned(ctx)
    w, d = _sn(ctx, w), _sn(ctx, d)
    deck_y, post_h = 1.6, 7.5
    out = []
    for sx in (-1, 0, 1):
        for sz in (-1, 1):
            out.append(part(ctx, "B", (0.8, deck_y, 0.8), (sx * (w / 2 - 0.5), deck_y / 2, sz * (d / 2 - 0.5)), mat="stone"))
    pitch = {"stud": 1.0, "lowpoly": 1.0, "midpoly": 0.8, "highpoly": 0.6}[ctx.style]
    nb = int(d / pitch)
    for i in range(nb):
        if ab and rng.random() < 0.1:
            continue
        out.append(part(ctx, "B", (w, 0.25, pitch - (0 if _stud(ctx) else 0.06)), (0, deck_y - 0.125, -d / 2 + pitch * (i + 0.5)), mat="plank",
                        vary=0.06))
    out.append(part(ctx, "B", (w, 0.6, 0.3), (0, deck_y - 0.55, -d / 2), mat="wood"))
    for k, hh in enumerate((deck_y * 2 / 3, deck_y / 3)):
        out.append(part(ctx, "B", (4, hh, 1.2), (0, hh / 2, -d / 2 - 0.6 - 1.2 * k), mat="plank"))
    for x in (-(w / 2 - 0.4), -2.4, 2.4, w / 2 - 0.4):
        out.append(part(ctx, "B", (0.6, post_h, 0.6), (x, deck_y + post_h / 2, -d / 2 + 0.4), mat="wood", vary=0.04))
    out.append(part(ctx, "B", (w + 0.4, 0.6, 0.6), (0, deck_y + post_h - 0.3, -d / 2 + 0.4), mat="wood"))
    roof_c = ctx.color("roof", "trim")
    ry = deck_y + post_h
    if _round(ctx):
        rise, run = 1.6, d + 1.2
        out.append(part(ctx, "B", (w + 1.2, 0.35, math.hypot(rise, run)), (0, ry + rise / 2 + 0.2, 0), rot=(_rise_x(rise, run), 0, 0),
                        mat="roof", color=roof_c))
        out.append(part(ctx, "B", (w + 1.3, 0.4, 0.15), (0, ry + 0.1, -d / 2 - 0.65), mat="wood"))
    else:
        out.append(part(ctx, "W", (w + 1.2, 1.6, d + 1.2), (0, ry + 0.8, 0), mat="roof", color=roof_c))
    wall_h = 9.5
    if _round(ctx):
        n = int(wall_h / 1.0)
        for i in range(n):
            out.append(part(ctx, "C", (w + 0.8, 1.05, 1.05), (0, deck_y + 0.5 + i * 1.0, d / 2 + 0.5), mat="wood", vary=0.05))
    else:
        out.append(part(ctx, "B", (w, wall_h, 1.0), (0, deck_y + wall_h / 2, d / 2 + 0.5), mat="wood"))
    out.append(part(ctx, "B", (3.4, 7, 0.3), (w * 0.15, deck_y + 3.5, d / 2 - 0.1), mat="wood", role="secondary"))
    out.append(part(ctx, "B", (0.3, 0.3, 0.2), (w * 0.15 + 1.2, deck_y + 3.3, d / 2 - 0.3), mat="metal", color=_col(ctx, BRASS), collide=False))
    lit = _lit(ctx)
    out.append(part(ctx, "B", (2.6, 2.2, 0.1), (-w * 0.28, deck_y + 4.6, d / 2 - 0.05), mat="glass",
                    color=(255, 200, 120) if lit else (60, 64, 70), t=0.3, light=light("point", (255, 190, 110), 1.0, 12) if lit else None))
    out.append(part(ctx, "B", (3.0, 0.3, 0.4), (-w * 0.28, deck_y + 3.4, d / 2 - 0.2), mat="wood"))
    out.append(part(ctx, "B", (3.0, 0.3, 0.2), (-w * 0.28, deck_y + 5.8, d / 2 - 0.1), mat="wood"))
    # railings: front either side of the steps, and both sides
    bp = {"stud": 2.0, "lowpoly": 2.0, "midpoly": 1.2, "highpoly": 0.8}[ctx.style]
    rail_y = deck_y + 3.0
    runs = [((-w / 2 + 0.3, -d / 2 + 0.2), (-2.2, -d / 2 + 0.2)), ((2.2, -d / 2 + 0.2), (w / 2 - 0.3, -d / 2 + 0.2)),
            ((-w / 2 + 0.15, -d / 2 + 0.2), (-w / 2 + 0.15, d / 2 - 0.2)), ((w / 2 - 0.15, -d / 2 + 0.2), (w / 2 - 0.15, d / 2 - 0.2))]
    for (x0, z0), (x1, z1) in runs:
        out.append(_beam(ctx, (x0, rail_y, z0), (x1, rail_y, z1), 0.3, mat="wood"))
        ln = math.hypot(x1 - x0, z1 - z0)
        k = max(1, int(ln / bp))
        for j in range(1, k):
            if ab and rng.random() < 0.15:
                continue
            f = j / k
            tilt = (rng.uniform(-15, 15), 0, 0) if ab and rng.random() < 0.15 else (0, 0, 0)
            out.append(part(ctx, "B", (0.2, 2.8, 0.2), (x0 + (x1 - x0) * f, deck_y + 1.5, z0 + (z1 - z0) * f), rot=tilt, mat="wood"))
    # lantern hanging from the front beam
    on = _lit(ctx)
    out.append(part(ctx, "B", (0.08, 0.8, 0.08), (-1.2, ry - 1.0, -d / 2 + 0.4), color=(30, 30, 30), collide=False))
    out.append(part(ctx, "B", (0.6, 0.8, 0.6), (-1.2, ry - 1.8, -d / 2 + 0.4), mat="glass", color=(255, 190, 110), t=0.2, collide=False,
                    light=light("point", (255, 180, 100), 1.2, 16) if on else None))
    # firewood stacked in the back-right corner
    fx, fz = w / 2 - 1.6, d / 2 - 0.8
    for row, cnt in enumerate((3, 2, 1)):
        for j in range(cnt):
            pos = (fx, deck_y + 0.35 + row * 0.6, fz - 0.7 + j * 0.7 + row * 0.35)
            if _stud(ctx):
                out.append(part(ctx, "B", (2.0, 0.6, 0.6), pos, mat="wood", vary=0.08))
            else:
                out.append(part(ctx, "C", (2.0, 0.65, 0.65), pos, mat="wood", vary=0.08))
    out += transform(chair(ctx, "wood", 1 if ab else 0), (-w / 2 + 2.0, deck_y, -0.4), 20)
    out.append(part(ctx, "B", (2.2, 0.06, 1.4), (w * 0.15, deck_y + 0.03, d / 2 - 1.0), mat="carpet", role="accent", collide=False))
    if ab:
        out += transform(cobweb(ctx, 0, 2), (w / 2 - 0.8, ry - 0.4, -d / 2 + 0.6))
    return out


@kit("snow_pine", "snow-laden pine: tiered foliage with snow caps on every tier and a snow mound at the base",
     {"h": (14, 6, 40)}, footprint=(7, 7), tags=("nature", "winter"))
def snow_pine(ctx, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    h = _sn(ctx, h)
    leaf = shade(ctx.color("foliage", vary=0.05), 0.75)
    snow = ctx.color("snow")
    trunk_h = h * 0.25
    tw = max(0.7, h * 0.06)
    # the trunk runs up inside the crown, so every tier hangs on it (and stays put when a lower tier breaks off)
    out = [part(ctx, "B", (tw, h * 0.9, tw), (0, h * 0.45, 0), mat="wood", vary=0.05)]
    tiers = {"stud": 4, "lowpoly": 4, "midpoly": 5, "highpoly": 6}[ctx.style]
    span = h - trunk_h
    for i in range(tiers):
        if ab and i == 0:
            out.append(part(ctx, "B", (tw * 0.5, h * 0.25, tw * 0.5), (h * 0.18, 0.3, -h * 0.1), rot=(0, 30, 88), mat="wood"))
            continue
        frac = i / tiers
        w = h * 0.45 * (1 - frac * 0.8)
        th = span / tiers * 1.25
        y0 = trunk_h + i * span / tiers
        if _stud(ctx):
            out.append(part(ctx, "B", (_sn(ctx, w), _sn(ctx, th * 0.8), _sn(ctx, w)), (0, y0 + th * 0.4, 0), mat="foliage", color=leaf, collide=False))
            out.append(part(ctx, "B", (_sn(ctx, w * 0.8), 0.4, _sn(ctx, w * 0.8)), (0, y0 + th * 0.8 + 0.2, 0), mat="snow", color=snow, collide=False))
        elif ctx.style == "lowpoly":
            for a in (0, 90, 180, 270):
                out.append(part(ctx, "W", (w, th, w / 2), (math.sin(math.radians(a)) * w / 4, y0 + th / 2, math.cos(math.radians(a)) * w / 4),
                                rot=(0, a + 180, 0), mat="foliage", color=shade(leaf, 1 + 0.05 * (i % 2)), collide=False))
                out.append(part(ctx, "W", (w * 0.55, th * 0.35, w * 0.28), (math.sin(math.radians(a)) * w * 0.14, y0 + th * 0.72, math.cos(math.radians(a)) * w * 0.14),
                                rot=(0, a + 180, 0), mat="snow", color=snow, collide=False))
        elif ctx.style == "midpoly":
            yaw = 45 * (i % 2)
            out.append(part(ctx, "B", (w, th * 0.75, w), (0, y0 + th * 0.4, 0), rot=(0, yaw, 0), mat="foliage", color=shade(leaf, 1 + 0.05 * (i % 2)), collide=False))
            out.append(part(ctx, "B", (w * 0.85, 0.35, w * 0.85), (0, y0 + th * 0.78 + 0.17, 0), rot=(0, yaw, 0), mat="snow", color=snow, collide=False))
            out.append(part(ctx, "B", (0.5, 0.6, 0.3), (math.sin(math.radians(yaw)) * w * 0.42, y0 + th * 0.62, -math.cos(math.radians(yaw)) * w * 0.42),
                            rot=(0, yaw, 0), mat="snow", color=snow, collide=False))
        else:
            out += _cone(ctx, w / 2, y0, th, 8, [leaf, shade(leaf, 1.06)], mat="foliage", collide=False)
            out += _cone(ctx, w * 0.36, y0 + th * 0.45, th * 0.55, 8, [snow], mat="snow", collide=False)
    out.append(_ball(ctx, (0.8, 0.8, 0.8), (0, h + 0.2, 0), mat="snow", color=snow, collide=False))
    if _round(ctx):
        out.append(part(ctx, "S", (h * 0.4, 1.0, h * 0.4), (0, 0, 0), mat="snow", color=snow, collide=False))
    else:
        out.append(part(ctx, "B", (_sn(ctx, h * 0.35), 0.4, _sn(ctx, h * 0.35)), (0, 0.2, 0), mat="snow", color=snow, collide=False))
    return out


@kit("snowman", "snowman: three snowballs, coal eyes and buttons, carrot nose, stick arms, top hat, scarf; melting when abandoned",
     {"h": (6, 3, 10)}, footprint=(3, 3), tags=("winter",))
def snowman(ctx, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    snow = ctx.color("snow")
    coal = (30, 30, 32)
    s1, s2, s3 = h * 0.42, h * 0.32, h * 0.24
    y1 = s1 * 0.45
    y2 = y1 + s1 * 0.42 + s2 * 0.42
    y3 = y2 + s2 * 0.42 + s3 * 0.45
    out = [_ball(ctx, (s1, s1 * 0.95, s1), (0, y1, 0), mat="snow", color=snow),
           _ball(ctx, (s2, s2 * 0.95, s2), (0, y2, 0), mat="snow", color=snow)]
    for k in range(3):
        yy = y2 - s2 * 0.25 + k * s2 * 0.25 if k < 2 else y1 + s1 * 0.2
        zz = -(s2 if k < 2 else s1) * 0.47
        out.append(_ball(ctx, (0.25, 0.25, 0.15), (0, yy, zz), mat="rock", color=coal, collide=False))
    scarf = ctx.color("fabric", "accent")
    out += _prism(ctx, s2 * 0.75, 0.4, (0, y2 + s2 * 0.4, 0), mat="fabric", color=scarf, collide=False)
    out.append(part(ctx, "B", (0.5, 1.2, 0.15), (s2 * 0.2, y2 + s2 * 0.1, -s2 * 0.42), rot=(0, 0, 8), mat="fabric", color=scarf, collide=False))
    for sx in (-1, 1):
        base = (sx * s2 * 0.45, y2 + s2 * 0.1, 0)
        tip = (sx * (s2 * 0.45 + h * 0.3), y2 + s2 * 0.1 + h * 0.18, 0)
        out.append(_beam(ctx, base, tip, 0.15, mat="wood", collide=False))
        if _hi(ctx):
            fork = (tip[0] - sx * 0.15, tip[1] + 0.4, 0.15)
            out.append(_beam(ctx, (tip[0] - sx * h * 0.06, tip[1] - h * 0.035, 0), fork, 0.1, mat="wood", collide=False))
    head = [_ball(ctx, (s3, s3, s3), (0, y3, 0), mat="snow", color=snow)]
    face = (_sn(ctx, s3) if _stud(ctx) else s3) / 2   # the stud head is snapped, so measure its real front face
    for sx in (-1, 1):
        head.append(_ball(ctx, (0.22, 0.22, 0.12), (sx * s3 * 0.2, y3 + s3 * 0.12, -face * 0.9), mat="rock", color=coal, collide=False))
    nose_c = _col(ctx, (240, 130, 40))
    if _stud(ctx):
        head.append(part(ctx, "B", (0.25, 0.25, 0.9), (0, y3, -face - 0.35), mat="plastic", color=nose_c, collide=False))
    else:
        head.append(part(ctx, "C", (0.9, 0.25, 0.25), (0, y3, -face - 0.35), rot=(0, 90, 0), mat="plastic", color=nose_c, collide=False))
        if _hi(ctx):
            head.append(part(ctx, "C", (0.35, 0.15, 0.15), (0, y3, -face - 0.95), rot=(0, 90, 0), mat="plastic", color=nose_c, collide=False))
            for k in range(5):
                a = math.radians(-40 + k * 20)
                head.append(part(ctx, "B", (0.12, 0.12, 0.08), (math.sin(a) * s3 * 0.25, y3 - s3 * 0.15 - math.cos(a) * 0.08, -s3 * 0.46),
                                 color=coal, collide=False))
    hat = [part(ctx, "C" if _round(ctx) else "B", (0.15, s3 * 0.95, s3 * 0.95) if _round(ctx) else (s3 * 0.95, 0.15, s3 * 0.95),
                (0, y3 + s3 * 0.45, 0), rot=(0, 0, 90) if _round(ctx) else (0, 0, 0), mat="fabric", color=coal),
           _up(ctx, s3 * 0.6, s3 * 0.55, (0, y3 + s3 * 0.45 + s3 * 0.28, 0), mat="fabric", color=coal),
           _up(ctx, s3 * 0.62, 0.15, (0, y3 + s3 * 0.55, 0), mat="fabric", color=scarf)]
    if ab:   # melting: head slumps sideways, hat on the ground, puddle around
        _rotate_group(head, (0, y3 - s3 * 0.5, 0), rz=22)
        for p in head:
            p["p"][1] = round(p["p"][1] - s3 * 0.15, 3)
        hat = transform(_rotate_group(hat, (0, y3 + s3 * 0.45, 0), rx=80), (s1 * 0.9, -y3 + 0.4, -s1 * 0.4))
        out.append(part(ctx, "C", (0.05, s1 * 1.8, s1 * 1.6), (0, 0.03, 0), rot=(0, 0, 90), mat="water", color=(150, 180, 200), t=0.35,
                        collide=False, cast=False))
    out += head + hat
    out.append(part(ctx, "S" if _round(ctx) else "B", (s1 * 1.4, 0.6, s1 * 1.4), (0, 0.1, 0), mat="snow", color=snow, collide=False))
    return out


# =========================================================================== Japanese garden

@kit("torii_gate", "torii gate: vermilion pillars with black sleeves, nuki tie beam, upswept black kasagi, centre plaque with text",
     {"w": (14, 8, 30), "h": (14, 8, 30)}, footprint=(18, 3), tags=("japanese",))
def torii_gate(ctx, w, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    w, h = _sn(ctx, w), _sn(ctx, h)
    verm, black = _col(ctx, VERMILION), _col(ctx, BLACK)
    out = []
    for sx in (-1, 1):
        x = sx * w / 2
        out.append(_up(ctx, 1.3, h, (x, h / 2, 0), mat="paint", color=verm))
        out.append(_up(ctx, 1.65, 1.2, (x, 0.6, 0), mat="paint", color=black))
    out.append(part(ctx, "B", (w + 3.0, 0.9, 0.7), (0, h * 0.72, 0), mat="paint", color=verm))
    if _hi(ctx):
        for sx in (-1, 1):
            out.append(part(ctx, "B", (0.3, 1.0, 0.9), (sx * (w / 2 + 0.85), h * 0.72, 0), mat="wood", color=black))
    gak_h = h - 0.8 - h * 0.72 - 0.45
    out.append(part(ctx, "B", (0.8, gak_h, 0.6), (0, h * 0.72 + 0.45 + gak_h / 2, 0), mat="paint", color=verm))
    out.append(part(ctx, "B", (1.6, min(2.4, gak_h * 0.9), 0.3), (0, h * 0.72 + 0.45 + gak_h / 2, -0.4), mat="wood", color=black))
    out.append(_text(part(ctx, "B", (1.2, min(2.0, gak_h * 0.75), 0.05), (0, h * 0.72 + 0.45 + gak_h / 2, -0.58), mat="paint",
                          color=_col(ctx, GOLD), collide=False)))
    out.append(part(ctx, "B", (w + 3.6, 0.8, 1.0), (0, h - 0.4, 0), mat="paint", color=verm))
    out.append(part(ctx, "B", (w + 2, 0.9, 1.3), (0, h + 0.45, 0), mat="wood", color=black))
    lost = rng.choice((-1, 1)) if ab else 0
    for sx in (-1, 1):
        if _stud(ctx):
            pieces = [(2.0, 0.4)]
        elif ctx.style == "lowpoly":
            pieces = [(2.4, 8)]
        else:
            pieces = [(1.2, 4), (1.2, 8), (1.0, 12)]
        x = sx * (w / 2 + 1)
        y = h + 0.45
        for k, (ln, val) in enumerate(pieces):
            if _stud(ctx):   # blocky step up instead of a curve
                seg = part(ctx, "B", (ln, 0.9, 1.3), (x + sx * ln / 2, y + val, 0), mat="wood", color=black)
                x += sx * ln
            else:
                a = math.radians(val)
                cx, cy = x + sx * math.cos(a) * ln / 2, y + math.sin(a) * ln / 2
                seg = part(ctx, "B", (ln + 0.05, 0.9, 1.3), (cx, cy, 0), rot=(0, 0, sx * val), mat="wood", color=black)
                x, y = x + sx * math.cos(a) * ln, y + math.sin(a) * ln
            if sx == lost and k == len(pieces) - 1:   # the end broke off and lies at the pillar foot
                seg["p"] = [round(sx * (w / 2 + 2), 3), 0.5, -1.5]
                seg["r"] = [0, 35, 0]
            out.append(seg)
    if ctx.state != "new":
        out.append(part(ctx, "B", (w * 0.6, 0.12, 1.1), (-w * 0.1, h + 0.95, 0), mat="grass", collide=False))
    return out


@kit("stone_lantern", "Japanese stone lantern (toro): base, pillar, platform, light box with glowing windows, wide roof, finial",
     {"h": (5, 3, 9)}, footprint=(3, 3), tags=("japanese", "light"))
def stone_lantern(ctx, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    k = h / 5
    out = _prism(ctx, 2.2 * k, 0.6 * k, (0, 0.3 * k, 0), mat="stone", vary=0.03)
    ph = h * 0.35
    out.append(_up(ctx, 0.8 * k, ph, (0, 0.6 * k + ph / 2, 0), mat="stone"))
    y = 0.6 * k + ph
    out += _prism(ctx, 1.8 * k, 0.45 * k, (0, y + 0.22 * k, 0), mat="stone")
    y += 0.45 * k
    bh = 1.1 * k
    out.append(part(ctx, "B", (1.3 * k, bh, 1.3 * k), (0, y + bh / 2, 0), mat="stone"))
    lit = not ab and _lit(ctx)
    warm = (255, 196, 120)
    faces = ((0, -1), (0, 1)) if not _round(ctx) else ((0, -1), (0, 1), (-1, 0), (1, 0))
    for j, (fx, fz) in enumerate(faces):
        size = (0.7 * k, 0.6 * k, 0.06) if fx == 0 else (0.06, 0.6 * k, 0.7 * k)
        out.append(part(ctx, "B", size, (fx * 0.66 * k, y + bh / 2, fz * 0.66 * k), mat="neon" if lit else "glass",
                        color=warm if lit else (40, 38, 36), collide=False,
                        light=light("point", warm, 1.0, 12) if lit and j == 0 else None))
    y += bh
    roof = []
    if _stud(ctx):
        roof.append(part(ctx, "B", (_sn(ctx, 2.6 * k), 0.5 * k, _sn(ctx, 2.6 * k)), (0, y + 0.25 * k, 0), mat="stone"))
        roof.append(part(ctx, "B", (_sn(ctx, 1.6 * k), 0.4 * k, _sn(ctx, 1.6 * k)), (0, y + 0.7 * k, 0), mat="stone"))
        top = y + 0.9 * k
    else:
        n = 6 if ctx.style == "lowpoly" else 8
        roof += _cone(ctx, 1.6 * k, y, 1.0 * k, n, [ctx.color("stone", vary=0.03)], mat="stone")
        top = y + 1.0 * k
        if _hi(ctx):
            for i in range(4):
                a = math.pi / 4 + i * math.pi / 2
                roof.append(part(ctx, "B", (0.25 * k, 0.35 * k, 0.4 * k), (math.sin(a) * 1.45 * k, y + 0.15 * k, math.cos(a) * 1.45 * k),
                                 rot=(-30, math.degrees(a), 0), mat="stone"))
    roof.append(_ball(ctx, (0.6 * k, 0.6 * k, 0.6 * k), (0, top + 0.3 * k, 0), mat="stone"))
    if ab:
        _rotate_group(roof, (0, y, 0), rz=8)
    out += roof
    if ctx.state != "new":
        out.append(part(ctx, "B", (1.0 * k, 0.15, 0.8 * k), (-0.3 * k, y + 0.1, -0.2 * k), mat="grass", collide=False))
        out.append(part(ctx, "B", (0.9 * k, 0.2, 0.9 * k), (0.3 * k, 0.62 * k, 0.4 * k), mat="grass", collide=False))
    return out


@kit("koi_pond_edge", "koi pond: ring of irregular rim stones around a water surface, koi under the surface, lily pads clustered at the back",
     {"r": (8, 4, 20)}, footprint=(18, 18), tags=("japanese", "nature"))
def koi_pond_edge(ctx, r):
    rng, ab = ctx.rng, _abandoned(ctx)
    r = _sn(ctx, r)
    wy = -0.3 if not ab else -0.9
    out = _prism(ctx, 2 * r, 0.4, (0, wy - 0.2, 0), mat="water", color=(60, 120, 120) if not ab else (80, 100, 60), t=0.35,
                 collide=False, cast=False)
    out += _prism(ctx, 2 * r, 0.3, (0, -2.2, 0), mat="pebble", color=(40, 50, 46))
    n = {"stud": 10, "lowpoly": 12, "midpoly": 16, "highpoly": 24}[ctx.style]
    tumbled = set(rng.sample(range(n), 2)) if ab else set()
    for i in range(n):
        a = 2 * math.pi * i / n
        front = abs(math.degrees(a) - 180) < 360 / n / 2 + 1   # one big flat viewing stone at the front
        ln = 2 * math.pi * (r + 0.4) / n * (1.6 if front else rng.uniform(1.0, 1.25))
        hh = 0.5 if front else rng.uniform(0.6, 1.1)
        dep = 1.8 if front else rng.uniform(1.0, 1.5)
        rr = r + 0.4 + (0.3 if front else 0)
        pos = (math.sin(a) * rr, hh / 2 - 0.2, math.cos(a) * rr)
        if i in tumbled:
            pos = (math.sin(a) * (r - 1.2), wy - 0.3, math.cos(a) * (r - 1.2))
        if _stud(ctx):
            out.append(part(ctx, "B", (_sn(ctx, ln), _sn(ctx, hh), _sn(ctx, dep)), pos, rot=(0, math.degrees(a), 0), mat="stone"))
        elif ctx.style == "lowpoly" or i % 2 or front:
            out.append(part(ctx, "B", (ln, hh, dep), pos, rot=(rng.uniform(-6, 6), math.degrees(a) + rng.uniform(-8, 8), rng.uniform(-6, 6)),
                            mat="stone", vary=0.08))
        else:
            out.append(part(ctx, "S", (ln, hh * 1.3, dep), pos, rot=(0, math.degrees(a), 0), mat="rock", vary=0.08))
    nk = 0 if ab else {"stud": 3, "lowpoly": 4, "midpoly": 5, "highpoly": 6}[ctx.style]
    kc = [(255, 120, 40), _col(ctx, WHITE), (220, 60, 40)]
    for i in range(nk):   # swimming a lazy arc around the pond
        a = 0.8 + i * 0.55
        rr = r * 0.55 + rng.uniform(-0.6, 0.6)
        f = _fish(ctx, rng.uniform(1.0, 1.4), kc[i % 3])
        out += transform(f, (math.cos(a) * rr, wy - 0.45, -math.sin(a) * rr), math.degrees(a) + 90)
    npads = {"stud": 3, "lowpoly": 3, "midpoly": 5, "highpoly": 6}[ctx.style]
    for i in range(npads):
        a = math.radians(rng.uniform(20, 80))
        rr = r * rng.uniform(0.45, 0.85)
        d = rng.uniform(1.0, 1.8)
        pos = (-math.cos(a) * rr, wy + 0.03, math.sin(a) * rr)
        if _stud(ctx):
            out.append(part(ctx, "B", (_sn(ctx, d), 0.1, _sn(ctx, d)), pos, mat="foliage", color=(70, 130, 60), collide=False))
        else:
            out.append(part(ctx, "C", (0.06, d, d), pos, rot=(0, 0, 90), mat="foliage", color=(70, 130, 60), collide=False))
        if i == 0 and not ab:
            out.append(_ball(ctx, (0.5, 0.4, 0.5), (pos[0], pos[1] + 0.2, pos[2]), mat="plastic", color=(240, 160, 190), collide=False))
    if ab:
        for _ in range(3):
            out.append(part(ctx, "B", (rng.uniform(1.5, 3), 0.05, rng.uniform(1, 2)), (rng.uniform(-r / 2, r / 2), wy + 0.02, rng.uniform(-r / 2, r / 2)),
                            rot=(0, rng.uniform(0, 90), 0), color=(90, 110, 50), t=0.2, collide=False, cast=False))
    return out


@kit("arched_bridge", "Japanese arched (taiko) bridge spanning along Z: curved plank deck, vermilion railings with bronze finials",
     {"length": (16, 8, 30), "w": (5, 3, 10)}, footprint=(6, 16), tags=("japanese",))
def arched_bridge(ctx, length, w):
    rng, ab = ctx.rng, _abandoned(ctx)
    L, w = _sn(ctx, length), _sn(ctx, w)
    rise = L * 0.2
    n = {"stud": 6, "lowpoly": 6, "midpoly": 10, "highpoly": 14}[ctx.style]
    verm = _col(ctx, VERMILION)
    zs = [-L / 2 + L * i / n for i in range(n + 1)]
    ys = [rise * (1 - (2 * z / L) ** 2) + 0.3 for z in zs]
    m0 = rng.randrange(1, n - 2) if ab else -9
    missing = {m0, m0 + 1}   # one two-plank hole: each half of the deck still reaches its bank
    out = []
    for i in range(n):
        if i in missing:
            continue
        if _stud(ctx):   # stepped deck: each step reaches down to the one below it, the end steps reach the ground
            lo, hi = min(ys[i], ys[i + 1]) - 0.6, max(ys[i], ys[i + 1])
            out.append(part(ctx, "B", (w, hi - lo, L / n), (0, (lo + hi) / 2, (zs[i] + zs[i + 1]) / 2), mat="plank"))
        else:
            out.append(_beam(ctx, (0, ys[i] - 0.25, zs[i]), (0, ys[i + 1] - 0.25, zs[i + 1]), w, 0.5, ext=0.1, mat="plank", vary=0.05))
            if _round(ctx):
                for sx in (-1, 1):
                    out.append(_beam(ctx, (sx * (w / 2 - 0.3), ys[i] - 0.9, zs[i]), (sx * (w / 2 - 0.3), ys[i + 1] - 0.9, zs[i + 1]), 0.5, 0.9,
                                     ext=0.1, mat="wood", color=shade(ctx.color("wood"), 0.8)))
    broken = rng.randrange(n) if ab else -1
    for sx in (-1, 1):
        x = sx * (w / 2 - 0.15)
        for i in range(0, n + 1, 2):
            out.append(part(ctx, "B", (0.35, 2.6, 0.35), (x, ys[i] + 1.3, zs[i]), mat="paint", color=verm))
        for i in range(n):
            a, b = (x, ys[i] + 2.5, zs[i]), (x, ys[i + 1] + 2.5, zs[i + 1])
            if i == broken and sx > 0:
                if _stud(ctx):   # blocky style: the rail section is simply missing
                    continue
                b = (x + 0.4, ys[i + 1] + 0.6, zs[i + 1])
            if _stud(ctx):   # stepped rail block spanning both post heights so the rail stays one piece
                lo, hi = min(a[1], b[1]) - 0.15, max(a[1], b[1]) + 0.15
                out.append(part(ctx, "B", (0.3, hi - lo, L / n), (x, (lo + hi) / 2, (zs[i] + zs[i + 1]) / 2), mat="paint", color=verm))
            else:
                out.append(_beam(ctx, a, b, 0.3, ext=0.15, mat="paint", color=verm))
        for i in (0, n):
            out.append(_ball(ctx, (0.55, 0.55, 0.55), (x, ys[i] + 2.9, zs[i]), mat="metal", color=_col(ctx, (150, 120, 60))))
            if _hi(ctx):
                out.append(part(ctx, "W", (0.3, 0.35, 0.3), (x, ys[i] + 3.3, zs[i]), mat="metal", color=_col(ctx, (150, 120, 60))))
    if ctx.state != "new":   # moss on the crown segment of the left rail
        c = n // 2
        out.append(part(ctx, "B", (0.4, 0.15, L / n * 0.9), (-(w / 2 - 0.15), (ys[c] + ys[c + 1]) / 2 + 2.68, (zs[c] + zs[c + 1]) / 2),
                        mat="grass", collide=False))
    return out


@kit("bamboo_cluster", "bamboo grove clump: culms with node rings leaning out from clump centres, leaf sprays at the top",
     {"n": (9, 3, 20), "h": (16, 6, 30)}, footprint=(5, 5), tags=("japanese", "nature"))
def bamboo_cluster(ctx, n, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    count = int(n)
    clumps = [(rng.uniform(-1.2, 1.2), rng.uniform(-1.2, 1.2)) for _ in range(1 + count // 6)]
    green = (104, 150, 64) if not ab else (176, 160, 100)
    old = (170, 170, 90) if not ab else (150, 130, 90)
    leaf = ctx.color("foliage") if not ab else _col(ctx, (170, 150, 90))
    node_step = {"stud": 0, "lowpoly": 0, "midpoly": 3.0, "highpoly": 2.2}[ctx.style]
    broken = rng.randrange(count) if ab else -1
    out = []
    for i in range(count):
        cx, cz = clumps[i % len(clumps)]
        x, z = cx + rng.gauss(0, 0.6), cz + rng.gauss(0, 0.6)
        hh = h * rng.uniform(0.6, 1.0)
        d = rng.uniform(0.35, 0.6)
        col = ctx.tone(shade(old if rng.random() < 0.25 else green, rng.uniform(0.92, 1.08)))
        if _stud(ctx):
            out.append(part(ctx, "B", (d, hh, d), (x, hh / 2, z), mat="wood", color=col, collide=False))
            continue
        ox, oz = x - cx, z - cz
        lean = 0.06 * hh
        nrm = math.hypot(ox, oz) or 1
        base, top = (x, 0, z), (x + ox / nrm * lean, hh, z + oz / nrm * lean)
        if i == broken:   # snapped culm leaning across the others
            top = (x + hh * 0.6, hh * 0.5, z + 0.5)
        shp = "C" if _round(ctx) else "B"
        out.append(_beam(ctx, base, top, d, shape=shp, mat="wood", color=col, collide=False))
        u = tuple((top[j] - base[j]) / hh for j in range(3))
        if ctx.style == "lowpoly":
            p = tuple(base[j] + (top[j] - base[j]) * 0.5 for j in range(3))
            out.append(_beam(ctx, tuple(p[j] - u[j] * 0.1 for j in range(3)), tuple(p[j] + u[j] * 0.1 for j in range(3)), d * 1.25,
                             mat="wood", color=shade(col, 0.9), collide=False))
        elif node_step:
            k = 1
            while k * node_step < hh - 0.5:
                f = k * node_step / hh
                p = tuple(base[j] + (top[j] - base[j]) * f for j in range(3))
                out.append(_beam(ctx, tuple(p[j] - u[j] * 0.08 for j in range(3)), tuple(p[j] + u[j] * 0.08 for j in range(3)), d * 1.2,
                                 shape="C", mat="wood", color=shade(col, 0.88), collide=False))
                k += 1
        sprays = 0 if ctx.style == "lowpoly" else (1 if ctx.style == "midpoly" else 2)
        for s in range(sprays):
            yaw = rng.uniform(0, 360)
            out.append(part(ctx, "W", (0.6, 0.1, 2.0), (top[0] + math.sin(math.radians(yaw)) * 0.8, top[1] - 0.8 - s * 1.2,
                            top[2] + math.cos(math.radians(yaw)) * 0.8), rot=(-20, yaw, 0), mat="foliage", color=leaf, collide=False))
    if _hi(ctx):
        for _ in range(6):
            out.append(part(ctx, "B", (0.3, 0.05, 1.0), (rng.gauss(0, 1.2), 0.03, rng.gauss(0, 1.2)), rot=(0, rng.uniform(0, 180), 0),
                            mat="paper", color=_col(ctx, (190, 170, 110)), collide=False, cast=False))
    return out


@kit("paper_screen", "shoji wall: sliding panels with wooden kumiko lattice and translucent paper, one panel slid open (back at +Z)",
     {"w": (6, 3, 16), "h": (7, 4, 10), "lit": (0, 0, 1)}, footprint=(6, 1), tags=("japanese",))
def paper_screen(ctx, w, h, lit):
    rng, ab = ctx.rng, _abandoned(ctx)
    w, h = _sn(ctx, w), _sn(ctx, h)
    panels = max(1, round(w / 3))
    pw = w / panels
    wood = ctx.color("wood", "secondary")
    cols, rows = {"stud": (2, 3), "lowpoly": (2, 3), "midpoly": (3, 5), "highpoly": (4, 7)}[ctx.style]
    bar = 0.2 if _stud(ctx) else 0.08
    torn = rng.randrange(panels) if ab else -1
    out = [part(ctx, "B", (w + 0.4, 0.25, 0.6), (0, 0.12, 0), mat="wood", color=shade(wood, 0.8)),
           part(ctx, "B", (w + 0.4, 0.25, 0.6), (0, h + 0.12, 0), mat="wood", color=shade(wood, 0.8))]
    for j in range(panels):
        xc = -w / 2 + pw * (j + 0.5)
        zc = 0
        if panels > 1 and j == panels - 1:   # last panel slid behind its neighbour
            xc -= pw * 0.35
            zc = 0.15
        pnl = []
        y0, y1 = 0.25, h
        for s in (-1, 1):
            pnl.append(part(ctx, "B", (0.25, y1 - y0, 0.3), (xc + s * (pw / 2 - 0.125), (y0 + y1) / 2, zc), mat="wood", color=wood))
        pnl.append(part(ctx, "B", (pw, 0.3, 0.3), (xc, y1 - 0.15, zc), mat="wood", color=wood))
        pnl.append(part(ctx, "B", (pw, 0.9, 0.25), (xc, y0 + 0.45, zc), mat="wood", color=wood))
        ay0, ay1 = y0 + 0.9, y1 - 0.3
        ah = ay1 - ay0
        iw = pw - 0.5
        for c in range(1, cols):
            pnl.append(part(ctx, "B", (bar, ah, 0.1), (xc - iw / 2 + iw * c / cols, ay0 + ah / 2, zc - 0.05), mat="wood", color=wood, collide=False))
        for r_ in range(1, rows):
            pnl.append(part(ctx, "B", (iw, bar, 0.1), (xc, ay0 + ah * r_ / rows, zc - 0.05), mat="wood", color=wood, collide=False))
        paper = (255, 226, 170) if lit else (240, 234, 214)
        if j == torn:
            for k in range(2):
                pnl.append(part(ctx, "B", (iw * 0.35, ah * 0.25, 0.05), (xc - iw * 0.2 + k * iw * 0.4, ay0 + ah * (0.2 + k * 0.5), zc + 0.02),
                                rot=(0, 0, rng.uniform(-20, 20)), mat="paper", color=_col(ctx, paper), t=0.15, collide=False))
            _rotate_group(pnl, (xc, 0, zc), rz=4)
        else:
            pnl.append(part(ctx, "B", (iw, ah, 0.05), (xc, ay0 + ah / 2, zc + 0.02), mat="paper", color=_col(ctx, paper), t=0.15))
        out += pnl
    if lit:   # andon lamp behind the paper makes it glow
        on = not ab
        out.append(part(ctx, "B", (0.6, 1.0, 0.6), (-w * 0.2, 0.5, 1.2), mat="neon" if on else "paper", color=(255, 210, 150), collide=False,
                        light=light("point", (255, 200, 140), 1.2, 12) if on else None))
    return out


# =========================================================================== hospital / library

@kit("hospital_bed", "hospital bed on castors: raised head section at +Z, mattress, blanket, side rails, chart at the foot",
     {}, footprint=(4, 8), tags=("hospital",))
def hospital_bed(ctx):
    rng, ab = ctx.rng, _abandoned(ctx)
    W, Lb = 3.6, 7.5
    metal = _col(ctx, (200, 204, 210))
    out = [part(ctx, "B", (W, 0.3, Lb), (0, 1.6, 0), mat="metal", color=metal),
           part(ctx, "B", (W - 0.6, 0.2, Lb - 1), (0, 0.6, 0), mat="metal", color=_col(ctx, (90, 94, 100)))]
    for sx in (-1, 1):
        for sz in (-1, 1):
            out.append(part(ctx, "B", (0.25, 1.1, 0.25), (sx * (W / 2 - 0.3), 1.0, sz * (Lb / 2 - 0.4)), mat="metal", color=metal))
            if _round(ctx):
                out.append(part(ctx, "C", (0.25, 0.5, 0.5), (sx * (W / 2 - 0.3), 0.25, sz * (Lb / 2 - 0.4)), mat="plastic", color=(40, 40, 42)))
            else:
                out.append(part(ctx, "B", (0.3, 0.45, 0.45), (sx * (W / 2 - 0.3), 0.23, sz * (Lb / 2 - 0.4)), mat="plastic", color=(40, 40, 42)))
    mat_c = _col(ctx, (230, 236, 240)) if not ab else (176, 160, 130)
    flat = Lb * 0.62
    out.append(part(ctx, "B", (W - 0.2, 0.6, flat), (0, 2.05, -Lb / 2 + flat / 2), mat="fabric", color=mat_c))
    hinge = -Lb / 2 + flat
    hl = Lb - flat
    th = 30
    c, s = math.cos(math.radians(th)), math.sin(math.radians(th))
    head = [part(ctx, "B", (W - 0.2, 0.6, hl), (0, 2.05 + s * hl / 2, hinge + c * hl / 2), rot=(-th, 0, 0), mat="fabric", color=mat_c)]
    if not ab:
        head.append(part(ctx, "B", (W * 0.7, 0.5, 1.2), (0, 2.6 + s * (hl - 0.9), hinge + c * (hl - 0.9) - 0.25), rot=(-th, 0, 0),
                         mat="fabric", color=_col(ctx, WHITE), collide=False))
    out += head
    if not ab:
        blanket = _col(ctx, (150, 190, 215))
        out.append(part(ctx, "B", (W, 0.2, Lb * 0.5), (0, 2.45, -Lb * 0.2), mat="fabric", color=blanket))
        out.append(part(ctx, "B", (W + 0.02, 0.22, 0.5), (0, 2.46, -Lb * 0.2 + Lb * 0.25 - 0.25), mat="fabric", color=_col(ctx, WHITE)))
    else:   # stains on the bare mattress
        out.append(part(ctx, "B", (1.2, 0.05, 1.6), (0.3, 2.37, -0.5), color=(120, 96, 70), t=0.3, collide=False, cast=False))
    out.append(part(ctx, "B", (W + 0.2, 2.8, 0.3), (0, 2.5, Lb / 2 + 0.1), mat="plastic", role="trim"))
    out.append(part(ctx, "B", (W + 0.2, 1.8, 0.3), (0, 2.1, -Lb / 2 - 0.1), mat="plastic", role="trim"))
    for sx in (-1, 1):
        down = ab and sx > 0
        out.append(part(ctx, "B", (0.15, 0.7, Lb * 0.4), (sx * (W / 2 + 0.1), 1.9 if down else 2.75, Lb * 0.1), mat="metal", color=metal))
    out.append(part(ctx, "B", (1.0, 1.3, 0.1), (0.6, 2.2, -Lb / 2 - 0.3), mat="paper", color=_col(ctx, WHITE), collide=False))
    out.append(part(ctx, "B", (0.4, 0.15, 0.12), (0.6, 2.85, -Lb / 2 - 0.32), mat="metal", color=(80, 80, 80), collide=False))
    if _hi(ctx):
        out.append(part(ctx, "B", (0.05, 1.2, 0.05), (-W / 2 - 0.15, 2.4, 1.0), color=(200, 200, 200), collide=False))
        out.append(part(ctx, "B", (0.3, 0.6, 0.2), (-W / 2 - 0.15, 1.6, 1.0), mat="plastic", color=_col(ctx, WHITE), collide=False))
    if ab:
        _rotate_group(out, (0, 0, 0), ry=7)
    return out


@kit("curtain_divider", "hospital privacy curtain along X: ceiling track, pleated fabric, mesh band at the top",
     {"length": (8, 4, 20), "h": (8, 6, 12)}, footprint=(8, 1), tags=("hospital",))
def curtain_divider(ctx, length, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    L, h = _sn(ctx, length), _sn(ctx, h)
    metal = _col(ctx, (200, 204, 210))
    out = [part(ctx, "B", (L, 0.2, 0.3), (0, h, 0), mat="metal", color=metal, collide=False)]
    for x in (-L / 2 - 0.1, L / 2 + 0.1):   # free-standing frame: end posts on splayed feet carry the track
        out.append(part(ctx, "B", (0.15, h + 0.1, 0.15), (x, (h + 0.1) / 2, 0), mat="metal", color=metal))
        out.append(part(ctx, "B", (0.2, 0.15, 1.6), (x, 0.075, 0), mat="metal", color=metal))
    pitch = max({"stud": 1.0, "lowpoly": 1.0, "midpoly": 0.7, "highpoly": 0.5}[ctx.style], L / 40)
    n = int(L / pitch)
    fab = _col(ctx, (150, 200, 190))
    top, bottom = h - 0.1, 0.8
    gap0 = rng.randrange(n - 2) if ab and n > 4 else -9
    mesh = 1.0 if _hi(ctx) else 0
    for i in range(n):
        if gap0 <= i < gap0 + 2:   # torn away
            continue
        x = -L / 2 + pitch * (i + 0.5)
        bot = bottom + (rng.uniform(0.5, 2.0) if ab and rng.random() < 0.25 else 0)
        ch = top - mesh - bot
        if _stud(ctx):
            out.append(part(ctx, "B", (pitch, ch, 0.15), (x, bot + ch / 2, 0.1 * (1 if i % 2 else -1)), mat="fabric", color=fab, collide=False))
        else:
            out.append(part(ctx, "B", (pitch * 1.15, ch, 0.12), (x, bot + ch / 2, 0.12 * (1 if i % 2 else -1)), rot=(0, 12 * (1 if i % 2 else -1), 0),
                            mat="fabric", color=shade(fab, 1 + 0.04 * (i % 2)), collide=False))
    if mesh:
        out.append(part(ctx, "B", (L, mesh, 0.1), (0, top - mesh / 2, 0), mat="fabric", color=shade(fab, 1.25), t=0.4, collide=False))
    return out


@kit("iv_stand", "IV drip stand: five-leg castor base, pole, hooks, IV bag with fluid level, tube, pump box",
     {}, footprint=(2, 2), tags=("hospital",))
def iv_stand(ctx):
    rng, ab = ctx.rng, _abandoned(ctx)
    metal = _col(ctx, (210, 214, 220))
    legs = 4 if _stud(ctx) else 5
    out = []
    for k in range(legs):
        a = 2 * math.pi * k / legs
        tip = (math.sin(a) * 1.1, 0.35, math.cos(a) * 1.1)
        out.append(_beam(ctx, (0, 0.45, 0), tip, 0.15, mat="metal", color=metal))
        out.append(_ball(ctx, (0.3, 0.3, 0.3), (tip[0], 0.15, tip[2]), mat="plastic", color=(40, 40, 42)))
    out.append(_up(ctx, 0.15, 6.4, (0, 3.6, 0), mat="metal", color=metal))
    out.append(part(ctx, "B", (1.6, 0.1, 0.1), (0, 6.8, 0), mat="metal", color=metal))
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.08, 0.3, 0.08), (sx * 0.75, 6.65, 0), mat="metal", color=metal, collide=False))
    out.append(part(ctx, "B", (0.7, 1.1, 0.25), (0.6, 6.0, 0), mat="glass", color=(225, 240, 245), t=0.35, collide=False))
    lvl = {"new": 0.85, "worn": 0.5}.get(ctx.state, 0.1)
    out.append(part(ctx, "B", (0.6, 1.0 * lvl, 0.18), (0.6, 5.5 + 0.5 * lvl, 0), mat="glass", color=(240, 236, 200), t=0.25, collide=False))
    pts = [(0.6, 5.4, 0), (0.75, 4.2, -0.3), (0.9, 3.0, -0.6), (1.3, 3.4, -1.0)]
    for a, b in zip(pts, pts[1:]):
        out.append(_beam(ctx, a, b, 0.06, mat="plastic", color=(230, 236, 240), t=0.3, collide=False))
    if _round(ctx):
        out.append(_up(ctx, 0.2, 0.4, (0.6, 5.25, 0), mat="glass", color=(230, 240, 245), t=0.3, collide=False))
        out.append(part(ctx, "B", (0.8, 1.0, 0.6), (0, 4.2, -0.4), mat="plastic", role="trim"))
        out.append(part(ctx, "B", (0.5, 0.3, 0.05), (0, 4.4, -0.72), mat="neon" if not ab else "plastic",
                        color=(90, 255, 160) if not ab else (30, 30, 30), collide=False))
    if ab:
        _rotate_group(out, (0, 0, 0), rz=6)
    return out


@kit("bookcase_tall", "tall library bookcase: crown cornice, plinth, books in runs with gaps and ornaments, brass rail and rolling ladder",
     {"w": (8, 4, 16), "h": (16, 8, 30), "ladder": (1, 0, 1)}, footprint=(8, 5), tags=("library",))
def bookcase_tall(ctx, w, h, ladder):
    rng, ab = ctx.rng, _abandoned(ctx)
    w, h = _sn(ctx, w), _sn(ctx, h)
    depth = 2.0
    wood = ctx.color("wood", "secondary")
    out = [part(ctx, "B", (w, h, 0.2), (0, h / 2, depth / 2 - 0.1), mat="wood", color=shade(wood, 0.85)),
           part(ctx, "B", (w + 0.4, 0.8, depth + 0.3), (0, 0.4, 0), mat="wood", color=wood),
           part(ctx, "B", (w + 0.8, 0.6, depth + 0.5), (0, h + 0.3, 0), mat="wood", color=wood)]
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.4, h, depth), (sx * (w / 2 - 0.2), h / 2, 0), mat="wood", color=wood))
    if _round(ctx):
        out.append(part(ctx, "B", (w + 1.2, 0.3, depth + 0.8), (0, h + 0.75, 0), mat="wood", color=shade(wood, 1.1)))
    books = [ctx.color("paper", r) for r in ("accent", "primary", "trim", "secondary")] + [shade(ctx.color("paper", "accent"), 0.7)]
    bw_range = {"stud": (0.6, 1.0), "lowpoly": (0.5, 0.9), "midpoly": (0.35, 0.6), "highpoly": (0.25, 0.45)}[ctx.style]
    levels = max(3, int((h - 0.8) / 2.2))
    lh = (h - 0.8) / levels
    sag = rng.randrange(1, levels) if ab else -1
    budget = 125 if not ladder else 108
    for li in range(levels + 1):
        y = 0.8 + li * lh
        rot = (0, 0, 4) if li == sag else (0, 0, 0)
        out.append(part(ctx, "B", (w - 0.8, 0.2, depth - 0.2), (0, y, -0.05), rot=rot, mat="wood", color=wood))
        if li == levels:
            break
        gap = lh - 0.3
        x = -w / 2 + 0.5
        mode = "folio" if li == 0 else ("ornament" if li == levels // 2 else "books")
        while x < w / 2 - 0.6 and len(out) < budget:
            if mode == "ornament" and abs(x) < 0.8:   # a globe-like ornament and a lying stack mid-shelf
                out.append(_ball(ctx, (0.9, 0.9, 0.9), (x + 0.45, y + 0.55, 0), mat="ceramic", role="accent", collide=False))
                for k in range(3):
                    out.append(part(ctx, "B", (1.2, 0.25, 1.2), (x + 1.6, y + 0.22 + k * 0.25, 0), rot=(0, k * 8, 0), mat="paper",
                                    color=books[k], collide=False))
                x += 2.4
                continue
            if ab and rng.random() < 0.3:
                x += rng.uniform(0.6, 1.4)
                continue
            run = rng.randint(3, 8)
            for _ in range(run):
                bw = rng.uniform(*bw_range) * (1.4 if mode == "folio" else 1)
                bh = gap * (rng.uniform(0.8, 0.95) if mode == "folio" else rng.uniform(0.6, 0.9))
                if x + bw > w / 2 - 0.5 or len(out) >= budget:
                    break
                out.append(part(ctx, "B", (bw, bh, depth * 0.7), (x + bw / 2, y + 0.1 + bh / 2, -0.1), mat="paper",
                                color=rng.choice(books), collide=False))
                x += bw + 0.02
            if x < w / 2 - 1.2 and rng.random() < 0.4:   # one book leaning at the end of a run
                bh = gap * 0.75
                out.append(part(ctx, "B", (0.35, bh, depth * 0.7), (x + 0.35, y + 0.1 + bh / 2 * 0.95, -0.1), rot=(0, 0, -18), mat="paper",
                                color=rng.choice(books), collide=False))
                x += 0.8
            x += rng.uniform(0.2, 0.7)
    if ladder:
        brass = _col(ctx, BRASS)
        rz = -depth / 2 - 0.6
        out.append(part(ctx, "B", (w + 1, 0.15, 0.15), (0, h - 0.6, rz), mat="metal", color=brass, collide=False))
        for sx in (-1, 1):
            out.append(part(ctx, "B", (0.15, 0.15, 0.6), (sx * (w / 2 - 0.3), h - 0.6, rz + 0.3), mat="metal", color=brass, collide=False))
        x0 = w * 0.25
        foot_z = -depth / 2 - 2.8
        for sx in (-1, 1):
            out.append(_beam(ctx, (x0 + sx * 0.7, 0, foot_z), (x0 + sx * 0.7, h - 0.6, rz), 0.2, mat="wood"))
        pitch = max(1.2, h / 12)
        k = 1
        while k * pitch < h - 1.2:
            f = k * pitch / (h - 0.6)
            out.append(part(ctx, "B", (1.4, 0.15, 0.25), (x0, k * pitch, foot_z + (rz - foot_z) * f), mat="wood", collide=False))
            k += 1
    if ab:   # books slid off the sagging shelf into a pile at the foot
        for k in range(5):
            out.append(_ground(part(ctx, "B", (0.4, 1.3, 1.0), (rng.uniform(-w / 3, w / 3), 0, -depth / 2 - rng.uniform(0.5, 1.5)),
                                    rot=(rng.uniform(70, 90), rng.uniform(0, 180), 0), mat="paper", color=rng.choice(books), collide=False)))
        out += transform(cobweb(ctx, 0, 2), (w / 2 - 0.6, h - 0.5, -depth / 2))
    return out


@kit("reading_table", "long library reading table with two green banker's lamps (lit), an open book and a stack",
     {"w": (8, 4, 14)}, footprint=(8, 4), tags=("library", "light"))
def reading_table(ctx, w):
    rng, ab = ctx.rng, _abandoned(ctx)
    w = _sn(ctx, w)
    d, ty = 4.0, 3.0
    wood = ctx.color("wood", "secondary")
    out = [part(ctx, "B", (w, 0.3, d), (0, ty, 0), mat="wood", color=wood, vary=0.03),
           part(ctx, "B", (w - 0.8, 0.5, d - 0.8), (0, ty - 0.4, 0), mat="wood", color=shade(wood, 0.9))]
    if _round(ctx):
        out.append(part(ctx, "B", (w - 1, 0.05, d - 1), (0, ty + 0.17, 0), mat="leather", color=_col(ctx, (60, 90, 60))))
        out.append(part(ctx, "B", (w - 1.0, 0.25, 0.25), (0, 0.6, 0), mat="wood", color=wood))   # H-stretcher between the leg pairs
        for sx in (-1, 1):
            out.append(part(ctx, "B", (0.25, 0.25, d - 1.0), (sx * (w / 2 - 0.5), 0.6, 0), mat="wood", color=wood))
    for sx in (-1, 1):
        for sz in (-1, 1):
            p = (sx * (w / 2 - 0.5), (ty - 0.15) / 2, sz * (d / 2 - 0.5))
            if _round(ctx):
                out.append(_cyl_y(ctx, 0.5, ty - 0.15, p, mat="wood", color=wood))
                if _hi(ctx):
                    out.append(_cyl_y(ctx, 0.7, 0.3, (p[0], 1.0, p[2]), mat="wood", color=shade(wood, 1.1)))
            else:
                out.append(part(ctx, "B", (0.45, ty - 0.15, 0.45), p, mat="wood", color=wood))
    brass = _col(ctx, BRASS)
    green = (40, 120, 70)
    for k, sx in enumerate((-1, 1)):
        x = sx * w * 0.25
        out += _prism(ctx, 0.9, 0.15, (x, ty + 0.23, 0.6), mat="metal", color=brass)
        out.append(_up(ctx, 0.12, 1.2, (x, ty + 0.9, 0.6), mat="metal", color=brass))
        if _stud(ctx):
            out.append(part(ctx, "B", (1.4, 0.5, 0.7), (x, ty + 1.6, 0.4), mat="glass", color=green, t=0.15, collide=False))
        else:
            out.append(part(ctx, "C", (1.4, 0.75, 0.75), (x, ty + 1.6, 0.4), mat="glass", color=green, t=0.15, collide=False))
        on = not (ab and k == 1) and _lit(ctx)
        out.append(part(ctx, "B", (0.5, 0.15, 0.3), (x, ty + 1.2, 0.4), mat="neon" if on else "glass", color=(255, 220, 160) if on else (90, 90, 80),
                        collide=False, light=light("spot", (255, 214, 150), 1.6, 12, angle=100, face="Bottom") if on else None))
    bx = -w * 0.25
    out.append(part(ctx, "B", (1.7, 0.08, 1.2), (bx, ty + 0.2, -0.7), mat="leather", role="accent", collide=False))
    for s in (-1, 1):
        out.append(part(ctx, "B", (0.8, 0.05, 1.1), (bx + s * 0.4, ty + 0.28, -0.7), rot=(0, 0, -s * 8), mat="paper", color=_col(ctx, (236, 228, 206)),
                        collide=False))
    for k in range(3 if _round(ctx) else 2):
        out.append(part(ctx, "B", (1.3 - k * 0.1, 0.3, 1.0), (w * 0.3, ty + 0.3 + k * 0.3, -0.8), rot=(0, rng.uniform(-12, 12), 0),
                        mat="paper", color=ctx.color("paper", ("accent", "trim", "primary")[k]), collide=False))
    if ab:
        out += transform(papers(ctx, 4), (0, 0, -d))
    return out


@kit("globe", "floor-standing library globe: tripod stand, tilted meridian ring, antique sphere with land patches",
     {"h": (4, 2, 6)}, footprint=(2, 2), tags=("library",))
def globe(ctx, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    R = h * 0.22
    cy = h - R
    wood = ctx.color("wood", "secondary")
    brass = _col(ctx, BRASS)
    out = []
    if _stud(ctx):
        out.append(part(ctx, "B", (1.6, 0.3, 1.6), (0, 0.15, 0), mat="wood", color=wood))
        out.append(part(ctx, "B", (0.3, cy - R - 0.3, 0.3), (0, 0.3 + (cy - R - 0.3) / 2, 0), mat="wood", color=wood))
    else:
        for k in range(3):
            a = 2 * math.pi * k / 3
            out.append(_beam(ctx, (math.sin(a) * R * 1.1, 0, math.cos(a) * R * 1.1), (0, cy - R * 0.9, 0), 0.18, mat="wood", color=wood))
    ocean = _col(ctx, (196, 176, 128))
    land = _col(ctx, (140, 104, 66))
    if ctx.style == "lowpoly":
        out.append(part(ctx, "B", (2 * R * 0.85, 2 * R * 0.85, 2 * R * 0.85), (0, cy, 0), rot=(0, 45, 0), mat="paper", color=ocean))
        out.append(part(ctx, "B", (2 * R * 0.85, 2 * R * 0.85, 2 * R * 0.85), (0, cy, 0), rot=(45, 0, 45), mat="paper", color=shade(ocean, 0.95)))
    else:
        out.append(part(ctx, "S", (2 * R, 2 * R, 2 * R), (0, cy, 0), mat="paper", color=ocean))
    spots = [(20, 30), (-10, 120), (40, -60), (-35, -150)] if _round(ctx) else [(20, 30), (-10, 160)]
    for lat, lon in spots:
        la, lo = math.radians(lat), math.radians(lon)
        nrm = (math.cos(la) * math.sin(lo), math.sin(la), -math.cos(la) * math.cos(lo))
        a = tuple((0, cy, 0)[j] + nrm[j] * (R - 0.05) for j in range(3))
        b = tuple((0, cy, 0)[j] + nrm[j] * (R + 0.05) for j in range(3))
        out.append(_beam(ctx, a, b, R * 0.6, R * 0.45, mat="paper", color=land, collide=False))
    n = {"stud": 6, "lowpoly": 6, "midpoly": 8, "highpoly": 12}[ctx.style]
    rr = R + 0.15
    pts = [(math.sin(math.pi * i / n) * rr, cy + math.cos(math.pi * i / n) * rr, 0) for i in range(n + 1)]
    ring = [_beam(ctx, pts[i], pts[i + 1], 0.12, 0.2, ext=0.05, mat="metal", color=brass, collide=False) for i in range(n)]
    out += _rotate_group(ring, (0, cy, 0), rz=23.5)
    if _hi(ctx):
        out += _ring(ctx, R + 0.3, cy, 0.12, 0.15, 12, mat="wood", color=wood, collide=False)
    if ab:
        _rotate_group(out, (0, 0, 0), rz=4)
    return out


# =========================================================================== beach

@kit("beach_umbrella", "striped beach umbrella stuck in the sand at a tilt, with fringe", {"r": (4, 2.5, 7), "tilt": (10, 0, 30)},
     footprint=(8, 8), tags=("beach",))
def beach_umbrella(ctx, r, tilt):
    rng, ab = ctx.rng, _abandoned(ctx)
    n = {"stud": 8, "lowpoly": 8, "midpoly": 10, "highpoly": 12}[ctx.style]
    cols = [ctx.color("fabric", "accent"), ctx.color("fabric", "primary")]
    out = [_up(ctx, 0.25, 7.5, (0, 3.25, 0), mat="metal" if not ab else "rust", color=_col(ctx, WHITE))]
    canopy = _cone(ctx, r, 6.4, 1.4, n, cols)
    if ab and not _stud(ctx):
        canopy.pop(rng.randrange(len(canopy)))
    out += canopy
    out.append(_ball(ctx, (0.4, 0.4, 0.4), (0, 7.9, 0), mat="plastic", color=cols[0]))
    if _hi(ctx):
        rv = r + 0.05
        seg = 2 * rv * math.sin(math.pi / n)
        for i in range(n):
            a = 2 * math.pi * (i + 0.5) / n
            out.append(part(ctx, "B", (seg * 0.9, 0.4, 0.08), (math.sin(a) * rv, 6.2, math.cos(a) * rv), rot=(0, math.degrees(a), 0), mat="fabric",
                            color=cols[(i + 1) % 2], collide=False))
    _rotate_group(out, (0, 0, 0), rz=(tilt + 15) if ab else tilt)
    out.append(_ball(ctx, (1.2, 0.5, 1.2), (0, 0.1, 0), mat="sand", collide=False))
    return out


@kit("beach_towel", "striped beach towel with a rolled pillow, sunglasses, sunscreen and flip-flops clustered at the head",
     {"w": (3, 2, 5), "l": (6, 4, 8)}, footprint=(4, 7), tags=("beach",))
def beach_towel(ctx, w, l):
    rng, ab = ctx.rng, _abandoned(ctx)
    w, l = _sn(ctx, w), _sn(ctx, l)
    k = {"stud": 3, "lowpoly": 4, "midpoly": 5, "highpoly": 7}[ctx.style]
    cols = [ctx.color("fabric", "accent"), ctx.color("fabric", "primary"), _col(ctx, WHITE)]
    out = []
    for i in range(k):
        out.append(part(ctx, "B", (w, 0.06, l / k), (0, 0.03, -l / 2 + l / k * (i + 0.5)), mat="fabric", color=cols[i % 3], collide=False, cast=False))
    if _stud(ctx):
        out.append(part(ctx, "B", (w * 0.9, 0.5, 0.6), (0, 0.3, l / 2 - 0.4), mat="fabric", color=_col(ctx, WHITE), collide=False))
    else:
        out.append(part(ctx, "C", (w * 0.9, 0.5, 0.5), (0, 0.3, l / 2 - 0.4), mat="fabric", color=_col(ctx, WHITE), collide=False))
    out.append(_up(ctx, 0.35, 0.9, (w / 2 + 0.5, 0.45, l / 2 - 0.6), mat="plastic", color=_col(ctx, (250, 200, 60)), collide=False))
    for s in (-1, 1):
        out.append(part(ctx, "B", (0.4, 0.06, 0.3), (s * 0.25, 0.1, l / 2 - 1.2), mat="glass", color=(30, 30, 34), t=0.2, collide=False))
    out.append(part(ctx, "B", (0.15, 0.06, 0.08), (0, 0.1, l / 2 - 1.2), color=(30, 30, 34), collide=False))
    for s in (-1, 1):
        out.append(part(ctx, "B", (0.5, 0.1, 1.1), (w / 2 + 0.6 + s * 0.35, 0.05, -l / 2 + 0.4), rot=(0, s * 8, 0), mat="plastic",
                        role="accent", collide=False))
    if _hi(ctx):
        out.append(part(ctx, "B", (1.0, 0.15, 1.3), (-w * 0.2, 0.12, 0.2), rot=(0, 20, 0), mat="paper", role="trim", collide=False))
    if ab:   # sand drifting over the towel
        for _ in range(2):
            out.append(_ball(ctx, (rng.uniform(1.2, 2.0), 0.4, rng.uniform(1.0, 1.6)), (rng.uniform(-w / 2, w / 2), 0.08, rng.uniform(-l / 2, 0)),
                             mat="sand", collide=False))
    return transform(out, (0, 0, 0), rng.uniform(-12, 12))


@kit("lifeguard_tower", "raised lifeguard hut on splayed legs: braced frame, deck, hut with propped shutter, pyramid roof, ladder, flag, buoy",
     {"h": (8, 5, 14)}, footprint=(8, 10), tags=("beach",))
def lifeguard_tower(ctx, h):
    rng, ab = ctx.rng, _abandoned(ctx)
    h = _sn(ctx, h)
    dy = h * 0.75
    wood = _col(ctx, WHITE)
    wall = ctx.color("paint", "primary")
    acc = ctx.color("paint", "accent")
    out = []
    feet = []
    for sx in (-1, 1):
        for sz in (-1, 1):
            foot = (sx * 3.6, 0, sz * 3.6)
            feet.append(foot)
            out.append(_beam(ctx, foot, (sx * 2.8, dy, sz * 2.8), 0.5, mat="wood", color=wood))
    for (a, b) in ((0, 1), (1, 3), (2, 3)):   # X braces on the sides and back, front left open
        fa, fb = feet[a], feet[b]
        out.append(_beam(ctx, fa, (fb[0] * 0.78, dy * 0.95, fb[2] * 0.78), 0.25, mat="wood", color=wood))
        out.append(_beam(ctx, fb, (fa[0] * 0.78, dy * 0.95, fa[2] * 0.78), 0.25, mat="wood", color=wood))
    out.append(part(ctx, "B", (7, 0.4, 7.5), (0, dy, -0.25), mat="plank", vary=0.05))
    hy = dy + 0.2
    gone = rng.choice(("left", "back")) if ab else ""
    out.append(part(ctx, "B", (6, 4, 0.3), (0, hy + 2, 2.85), mat="paint", color=wall) if gone != "back" else
               part(ctx, "B", (6, 2.2, 0.3), (0, hy + 2.9, 2.85), mat="paint", color=wall))
    for sx in (-1, 1):
        if gone == "left" and sx < 0:
            out.append(part(ctx, "B", (0.3, 4, 3.5), (sx * 2.85, hy + 2, 1.25), mat="paint", color=wall))
        else:
            out.append(part(ctx, "B", (0.3, 4, 6), (sx * 2.85, hy + 2, 0), mat="paint", color=wall))
        out.append(part(ctx, "B", (0.06, 0.5, 6), (sx * 3.03, hy + 1.8, 0), mat="paint", color=acc, collide=False))
    out.append(part(ctx, "B", (6, 1.6, 0.3), (0, hy + 0.8, -2.85), mat="paint", color=acc))
    out.append(part(ctx, "B", (6, 0.6, 0.3), (0, hy + 3.7, -2.85), mat="paint", color=wall))
    out.append(_text(part(ctx, "B", (2.4, 0.5, 0.08), (0, hy + 3.7, -3.04), mat="paint", color=_col(ctx, WHITE), collide=False)))
    if _round(ctx):
        th = 70
        c, s = math.cos(math.radians(th)), math.sin(math.radians(th))
        hinge = (0, hy + 3.4, -2.95)
        out.append(part(ctx, "B", (6, 1.6, 0.15), (0, hinge[1] - 0.8 * c, hinge[2] - 0.8 * s), rot=(th, 0, 0), mat="paint", color=acc))
        out.append(part(ctx, "B", (6.6, 0.3, 6.6), (0, hy + 4.1, 0), mat="wood", color=wood))
    roof_c = ctx.color("roof", "accent")
    roof_y = hy + (4.2 if _round(ctx) else 4.0)   # round styles rest the roof on the eave slab, the others on the walls
    out += _cone(ctx, 4.6, roof_y, 1.6, 4, [roof_c, shade(roof_c, 0.9)], mat="roof", square=True)
    if not ab:
        apex = roof_y + 1.6
        out.append(part(ctx, "B", (0.12, 3, 0.12), (0, apex + 1.3, 0), mat="metal", color=(60, 60, 60), collide=False))
        out.append(part(ctx, "B", (1.6, 1.0, 0.06), (0.86, apex + 2.2, 0), mat="fabric", color=_col(ctx, (210, 40, 30)), collide=False))
    foot_z, top_z = -6.5, -3.9
    for sx in (-1, 1):
        out.append(_beam(ctx, (sx * 0.8, 0, foot_z), (sx * 0.8, dy, top_z), 0.25, mat="wood", color=wood))
    pitch = max(0.9, dy / 10)
    k = 1
    while k * pitch < dy - 0.3:
        f = k * pitch / dy
        out.append(part(ctx, "B", (1.6, 0.15, 0.3), (0, k * pitch, foot_z + (top_z - foot_z) * f), mat="wood", color=wood))
        k += 1
    out.append(part(ctx, "C", (0.4, 1.6, 1.6), (3.15, hy + 2.2, 0), mat="plastic", color=_col(ctx, (230, 90, 40))))
    if _hi(ctx):
        for j in range(4):
            a = math.pi / 4 + j * math.pi / 2
            out.append(part(ctx, "B", (0.42, 0.35, 0.35), (3.15, hy + 2.2 + math.sin(a) * 0.65, math.cos(a) * 0.65), color=_col(ctx, WHITE), collide=False))
    if _round(ctx):
        out.append(part(ctx, "B", (0.8, 3.0, 0.3), (3.0, 1.5, -3.6), rot=(12, 0, 0), mat="plastic", color=_col(ctx, (220, 40, 30))))
    if ab:
        _rotate_group(out, (0, 0, 0), rz=3)
    return out


@kit("sandcastle", "sandcastle: mound, corner towers with crenellations, walls, gate, keep with flag, moat, bucket and spade",
     {"w": (6, 3, 14)}, footprint=(7, 7), tags=("beach",))
def sandcastle(ctx, w):
    rng, ab = ctx.rng, _abandoned(ctx)
    w = _sn(ctx, w)
    sand = ctx.color("sand")
    wet = shade(sand, 0.85)
    out = []
    if _round(ctx):
        out.append(part(ctx, "S", (w * 1.2, 1.0, w * 1.2), (0, 0, 0), mat="sand", color=sand))
        out += _ring(ctx, w * 0.68, 0.05, 0.6, 0.1, 16 if _hi(ctx) else 12, mat="sand", color=wet, collide=False)
    else:
        out.append(part(ctx, "B", (_sn(ctx, w), 0.6, _sn(ctx, w)), (0, 0.3, 0), mat="sand", color=sand))
    base = 0.5
    tp = w * 0.32
    crn = {"stud": 0, "lowpoly": 4, "midpoly": 4, "highpoly": 6}[ctx.style]
    collapsed = rng.randrange(4) if ab else -1
    for i, (sx, sz) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
        x, z = sx * tp, sz * tp
        if i == collapsed:
            out.append(_ball(ctx, (1.6, 0.8, 1.6), (x, base + 0.2, z), mat="sand", color=wet))
            continue
        th = 2.2 * (0.6 if ab else 1)
        out.append(_up(ctx, 1.3, th, (x, base + th / 2, z), mat="sand", color=sand))
        for c in range(crn):
            if ab and rng.random() < 0.5:
                continue
            a = 2 * math.pi * c / crn
            out.append(part(ctx, "B", (0.3, 0.3, 0.3), (x + math.sin(a) * 0.5, base + th + 0.15, z + math.cos(a) * 0.5), mat="sand", color=sand))
        if _stud(ctx):
            out.append(part(ctx, "B", (0.5, 0.4, 0.5), (x, base + th + 0.2, z), mat="sand", color=sand))
    wl = 2 * tp - 1.2
    for (cx, cz, lx, lz) in ((0, -tp, wl, 0.5), (0, tp, wl, 0.5), (-tp, 0, 0.5, wl), (tp, 0, 0.5, wl)):
        out.append(part(ctx, "B", (lx, 1.2, lz), (cx, base + 0.6, cz), mat="sand", color=sand))
    out.append(part(ctx, "B", (0.8, 0.9, 0.1), (0, base + 0.45, -tp - 0.27), color=shade(sand, 0.55), collide=False))
    kh = 3.0 * (0.7 if ab else 1)
    if _round(ctx):
        out.append(_cyl_y(ctx, 2.0, kh, (0, base + kh / 2, 0), mat="sand", color=sand))
        out += _cone(ctx, 1.0, base + kh, 1.0, ctx.detail() // 2, [sand], mat="sand")
    else:
        out.append(part(ctx, "B", (_sn(ctx, 1.8), _sn(ctx, kh), _sn(ctx, 1.8)), (0, base + _sn(ctx, kh) / 2, 0), mat="sand", color=sand))
    keep_top = base + kh + 1.0 if _round(ctx) else base + _sn(ctx, kh)
    if not ab:
        out.append(part(ctx, "B", (0.08, 1.4, 0.08), (0, keep_top + 0.6, 0), mat="wood", collide=False))
        out.append(part(ctx, "B", (0.7, 0.45, 0.05), (0.39, keep_top + 1.05, 0), mat="fabric", role="accent", collide=False))
    bx, bz = w * 0.55 + 0.8, -w * 0.35
    out.append(_up(ctx, 1.0, 1.0, (bx, 0.5, bz), mat="plastic", role="accent"))
    out.append(_beam(ctx, (bx - 0.6, 0.05, bz - 0.8), (bx - 0.3, 1.6, bz - 0.3), 0.12, mat="plastic", color=_col(ctx, (250, 200, 60))))
    out.append(part(ctx, "W", (0.6, 0.1, 0.7), (bx - 0.68, 0.06, bz - 1.2), rot=(0, 180, 0), mat="plastic", color=_col(ctx, (250, 200, 60))))
    for k in range(3 if _round(ctx) else 2):
        out.append(_ball(ctx, (0.3, 0.15, 0.3), (0.6 + k * 0.4, 0.1, -tp - 1.2 - k * 0.2), mat="ceramic",
                         color=((240, 230, 220), (240, 180, 180), (230, 210, 170))[k], collide=False))
    return out


# =========================================================================== self-test

def _selftest():
    import math as _m
    themed = {n for n, info in KITS.items() if info["fn"].__module__ == __name__}
    states = ("new", "worn", "abandoned")
    table, errors, warnings = {}, [], []

    def check(name, style, state, params=None):
        ctx = Ctx(style, seed=11, state=state)
        parts = build_kit(ctx, name, params)
        n = len(parts)
        if not 1 <= n <= 400:
            raise AssertionError(f"{n} parts")
        for p in parts:
            if p["s"] not in SHAPES:
                raise AssertionError(f"bad shape {p['s']}")
            if not all(_m.isfinite(v) and v >= 0.05 - 1e-9 for v in p["z"]):
                raise AssertionError(f"bad size {p['z']}")
            if not all(_m.isfinite(v) for v in p["p"]) or not all(_m.isfinite(v) for v in p.get("r", (0, 0, 0))):
                raise AssertionError(f"bad position/rotation {p}")
            if not all(0 <= c <= 255 for c in p["c"]):
                raise AssertionError(f"bad colour {p['c']}")
        return n

    for name in sorted(KITS):
        row = {}
        for style in STYLES:
            best = 0
            for state in states:
                try:
                    best = max(best, check(name, style, state))
                except Exception as exc:   # collect everything, report at the end
                    errors.append(f"{name}/{style}/{state}: {type(exc).__name__}: {exc}")
            row[style] = best
        table[name] = row
        if name in themed and row["highpoly"] > 150:
            warnings.append(f"{name}: {row['highpoly']} parts at highpoly (budget ~150)")
    # robustness: themed kits at the low and high ends of every numeric param
    for name in sorted(themed):
        spec = KITS[name]["params"]
        for end in (1, 2):
            params = {k: (r[end] if not isinstance(r[1], list) else r[0]) for k, r in spec.items()}
            for style in ("stud", "highpoly"):
                try:
                    check(name, style, "abandoned", params)
                except Exception as exc:
                    errors.append(f"{name}/{style}/extreme{end}: {type(exc).__name__}: {exc}")
    print(f"{'kit':22s} {'stud':>5s} {'lowp':>5s} {'midp':>5s} {'high':>5s}")
    for name in sorted(table):
        r = table[name]
        mark = " *" if name in themed else ""
        print(f"{name:22s} {r['stud']:5d} {r['lowpoly']:5d} {r['midpoly']:5d} {r['highpoly']:5d}{mark}")
    for style in STYLES:
        top = max(table, key=lambda n: table[n][style])
        ttop = max(themed, key=lambda n: table[n][style])
        print(f"max {style}: {table[top][style]} ({top}); themed max {table[ttop][style]} ({ttop})")
    print(f"{len(table)} kits ({len(themed)} themed, * above), 4 styles x 3 states")
    for w in warnings:
        print("WARN", w)
    if errors:
        for e in errors:
            print("FAIL", e)
        raise SystemExit(1)
    print("selftest OK")


if __name__ == "__main__":
    _selftest()
