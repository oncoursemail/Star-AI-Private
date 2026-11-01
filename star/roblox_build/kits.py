"""Kit library: hand-made, style-aware builders for architecture, furniture, lights, nature and story props.

Every kit is `fn(ctx, **params) -> list[part]` in LOCAL space: origin on the floor (y = 0 is the floor top), the
front faces -Z, the kit is centred on x = 0. The scene compiler rotates (yaw) and moves it. Sizes are studs and
follow the Roblox character (about 5 studs tall, shoulders 2 wide): seats ~2 high, tables ~3, doors 8 x 5.

Register with @kit(name, summary, params) where params = {name: (default, low, high)} (numbers) or
{name: (default, [choices])} (text). The LLM sees the summaries; values are clamped before the call.
"""
from __future__ import annotations

import math

from .geom import Ctx, aabb, axis_aligned, lathe, light, part, rot_matrix, shade, transform

KITS: dict[str, dict] = {}


def kit(name: str, summary: str, params: dict | None = None, footprint=(4, 4), tags: tuple = ()):
    def register(fn):
        KITS[name] = {"fn": fn, "summary": summary, "params": params or {}, "footprint": footprint, "tags": tags}
        return fn
    return register


def clean_params(name: str, raw: dict | None) -> dict:
    spec = KITS[name]["params"]
    out = {}
    raw = raw if isinstance(raw, dict) else {}
    for key, rule in spec.items():
        default = rule[0]
        value = raw.get(key, default)
        if isinstance(rule[1], list):
            out[key] = value if value in rule[1] else default
        else:
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = float(default)
            if not math.isfinite(number):
                number = float(default)
            out[key] = max(rule[1], min(rule[2], number))
    return out


def build_kit(ctx: Ctx, name: str, params: dict | None = None) -> list[dict]:
    if name not in KITS:
        raise KeyError(name)
    parts = KITS[name]["fn"](ctx, **clean_params(name, params))
    _settle_faces(parts)
    for p in parts:
        p.setdefault("kit", name)
    return parts


def _settle_faces(parts: list[dict], step: float = 0.04, passes: int = 6) -> None:
    """Remove z-fighting inside one kit: where two axis-aligned opaque blocks have coplanar, same-facing, overlapping
    faces (same rule as checks.z_fighting), pull the smaller face 0.04 studs inward by trimming that part (or nudging
    it when it is too thin to trim). Invisible at play distance; the floating contact tolerance (0.08) is kept."""
    done: set[tuple] = set()          # (part, axis, sign): each face is pulled at most once
    for _ in range(passes):
        faces: dict[tuple, list[int]] = {}
        boxes = {}
        for i, p in enumerate(parts):
            if p["s"] != "B" or not axis_aligned(p) or p.get("t", 0) >= 0.95:
                continue
            boxes[i] = aabb(p)
            lo, hi = boxes[i]
            for axis in range(3):
                for sign, coord in ((-1, lo[axis]), (1, hi[axis])):
                    if axis == 1 and sign == -1:
                        continue
                    faces.setdefault((axis, sign, round(coord * 50)), []).append(i)
        touched: set[int] = set()     # parts changed in this pass (their boxes are stale until the next pass)
        for (axis, sign, _), members in faces.items():
            if len(members) < 2 or len(members) > 400:
                continue
            others = [a for a in range(3) if a != axis]
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    i, j = members[x], members[y]
                    if i in touched or j in touched:
                        continue
                    a, b = boxes[i], boxes[j]
                    area = 1.0
                    for o in others:
                        area *= max(0.0, min(a[1][o], b[1][o]) - max(a[0][o], b[0][o]))
                    pi, pj = parts[i], parts[j]
                    close = pi["m"] == pj["m"] and sum(abs(pi["c"][k] - pj["c"][k]) for k in range(3)) < 40
                    if area <= 0.25 or close:
                        continue
                    fa = math.prod(a[1][o] - a[0][o] for o in others)
                    fb = math.prod(b[1][o] - b[0][o] for o in others)
                    order = (i, j) if fa <= fb else (j, i)   # the smaller face (the detail) gives way
                    k = next((c for c in order if (c, axis, sign) not in done), None)
                    if k is None:
                        continue
                    _pull_face(parts[k], axis, sign, step)
                    done.add((k, axis, sign))
                    touched.add(k)
        if not touched:
            return


def _pull_face(p: dict, axis: int, sign: int, step: float) -> None:
    """Move the face of block p on world `axis` / `sign` inward by `step` (trim, or shift if the block is thin)."""
    m = rot_matrix(*p.get("r", (0, 0, 0)))
    local = max(range(3), key=lambda j: abs(m[axis][j]))
    if p["z"][local] - step >= 0.1:
        p["z"][local] = round(p["z"][local] - step, 3)
        p["p"][axis] = round(p["p"][axis] - sign * step / 2, 3)
    else:
        p["p"][axis] = round(p["p"][axis] - sign * step, 3)


def catalog() -> str:
    """One line per kit for prompts: name(params): summary."""
    lines = []
    for name, info in sorted(KITS.items()):
        ps = []
        for key, rule in info["params"].items():
            ps.append(f"{key}={'|'.join(rule[1])}" if isinstance(rule[1], list) else f"{key}={rule[0]:g}")
        lines.append(f"{name}({', '.join(ps)}): {info['summary']}")
    return "\n".join(lines)


def _cyl_y(ctx, d, h, pos, **kw):
    """Upright cylinder (Roblox cylinders run along X, so rotate 90 about Z)."""
    return part(ctx, "C", (h, d, d), pos, rot=(0, 0, 90), **kw)


def _ring(ctx, radius, y, thick, height, segments, **kw):
    """A ring of blocks (rims, tank edges, wheel rims)."""
    out = []
    seg_len = 2 * math.pi * radius / segments * 1.04
    for i in range(segments):
        a = 2 * math.pi * i / segments
        out.append(part(ctx, "B", (seg_len, height, thick), (math.sin(a) * radius, y, math.cos(a) * radius),
                        rot=(0, math.degrees(a), 0), **kw))
    return out


def _abandoned(ctx) -> bool:
    return ctx.state == "abandoned"


# =========================================================================== architecture

@kit("column", "round or square column with base and capital", {"h": (12, 4, 40), "w": (2, 1, 6),
     "shape": ("round", ["round", "square"]), "mat": ("stone", ["stone", "marble", "wood", "concrete", "metal", "brick"]),
     "broken": (0, 0, 1)}, footprint=(3, 3), tags=("structure",))
def column(ctx, h, w, shape, mat, broken):
    out = []
    base_h = max(0.6, w * 0.35)
    out.append(part(ctx, "B", (w * 1.5, base_h, w * 1.5), (0, base_h / 2, 0), mat=mat, vary=0.03))
    shaft_h = h - base_h * 2 if not broken else h * 0.55
    if ctx.style in ("midpoly", "highpoly") and shape == "round":
        out.append(part(ctx, "B", (w * 1.3, base_h * 0.4, w * 1.3), (0, base_h + base_h * 0.2, 0), mat=mat))
    if shape == "round" and ctx.style == "highpoly":
        r = w / 2
        prof = [(r * 1.25, 0), (r * 1.3, 0.25), (r * 1.1, 0.5), (r * 1.02, 0.8)]
        for k in range(1, 7):                       # entasis: the shaft swells slightly a third of the way up
            t = k / 7
            prof.append((r * (1.02 + 0.05 * math.sin(math.pi * min(1, t * 1.5)) - 0.1 * t), 0.8 + (shaft_h - 1.6) * t))
        prof += [(r * 0.95, shaft_h - 0.8), (r * 1.1, shaft_h - 0.5), (r * 1.3, shaft_h - 0.25), (r * 1.25, shaft_h)]
        out.append(lathe(ctx, prof, (0, base_h, 0), mat=mat, vary=0.03))
        if not broken:
            for i in range(12):
                a = 2 * math.pi * i / 12
                out.append(part(ctx, "B", (0.12, shaft_h * 0.8, 0.2), (math.sin(a) * r * 0.97, base_h + shaft_h / 2,
                                math.cos(a) * r * 0.97), rot=(0, math.degrees(a), 0), mat=mat, color=shade(ctx.color(mat), 0.88)))
    elif shape == "round" and ctx.style != "stud":
        out.append(_cyl_y(ctx, w, shaft_h, (0, base_h + shaft_h / 2, 0), mat=mat, vary=0.03))
        if ctx.style == "highpoly":   # fluting: thin vertical strips
            for i in range(8):
                a = 2 * math.pi * i / 8
                out.append(part(ctx, "B", (0.15, shaft_h * 0.92, 0.25), (math.sin(a) * w / 2, base_h + shaft_h / 2,
                                math.cos(a) * w / 2), rot=(0, math.degrees(a), 0), mat=mat, color=shade(ctx.color(mat), 0.85)))
    else:
        out.append(part(ctx, "B", (w, shaft_h, w), (0, base_h + shaft_h / 2, 0), mat=mat, vary=0.03))
        if ctx.style == "stud":   # banding rings like classic brick columns
            for y in (base_h + shaft_h * 0.33, base_h + shaft_h * 0.66):
                out.append(part(ctx, "B", (w + 0.4, 0.4, w + 0.4), (0, y, 0), mat=mat, color=shade(ctx.color(mat), 0.85)))
    if not broken:
        out.append(part(ctx, "B", (w * 1.5, base_h, w * 1.5), (0, h - base_h / 2, 0), mat=mat, vary=0.03))
        if ctx.style in ("midpoly", "highpoly"):
            out.append(part(ctx, "B", (w * 1.25, base_h * 0.4, w * 1.25), (0, h - base_h - base_h * 0.2, 0), mat=mat))
    else:   # fallen drum on the floor beside it
        out.append(part(ctx, "C" if shape == "round" and ctx.style != "stud" else "B", (h * 0.3, w, w),
                        (w * 1.6, w / 2, w * 0.6), rot=(0, 25, 0), mat=mat, vary=0.05))
    return out


@kit("arch", "free-standing arch / doorway frame (voussoirs follow the style)", {"w": (8, 4, 30), "h": (12, 6, 40),
     "depth": (2, 1, 6), "mat": ("stone", ["stone", "brick", "wood", "marble", "concrete"])}, footprint=(10, 3),
     tags=("structure",))
def arch(ctx, w, h, depth, mat):
    out = []
    pier = max(1.0, w * 0.15)
    spring = h - w / 2
    for sx in (-1, 1):
        out.append(part(ctx, "B", (pier, spring, depth), (sx * (w / 2 + pier / 2), spring / 2, 0), mat=mat, vary=0.03))
    n = ctx.detail()
    r = w / 2 + pier / 2
    for i in range(n):
        a0, a1 = math.pi * i / n, math.pi * (i + 1) / n
        am = (a0 + a1) / 2
        seg = 2 * r * math.sin((a1 - a0) / 2) * 1.08
        out.append(part(ctx, "B", (seg, pier, depth), (math.cos(am) * r, spring + math.sin(am) * r, 0),
                        rot=(0, 0, math.degrees(am) + 90), mat=mat, vary=0.04))
    # keystone
    out.append(part(ctx, "B", (pier * 0.8, pier * 1.3, depth * 1.08), (0, spring + r, 0), mat=mat,
                    color=shade(ctx.color(mat), 0.9)))
    return out


@kit("stairs", "straight staircase going up towards -Z", {"w": (6, 2, 24), "rise": (6, 1, 30), "steps": (8, 2, 40),
     "mat": ("stone", ["stone", "wood", "plank", "concrete", "marble", "metal"]), "rail": (1, 0, 1)}, footprint=(6, 10))
def stairs(ctx, w, rise, steps, mat, rail):
    out = []
    n = int(steps)
    sh = rise / n
    run = max(1.0, sh * 1.6)
    for i in range(n):
        y = sh * (i + 1)
        out.append(part(ctx, "B", (w, y, run), (0, y / 2, -run * i), mat=mat, vary=0.02))
        if ctx.style in ("midpoly", "highpoly"):
            out.append(part(ctx, "B", (w + 0.1, 0.15, 0.3), (0, y + 0.05, -run * i + run / 2 - 0.15), mat=mat,
                            color=shade(ctx.color(mat), 0.8)))
    if rail:
        length = math.hypot(run * n, rise)
        ang = math.degrees(math.atan2(rise, run * n))
        for sx in (-1, 1):
            out.append(part(ctx, "B", (0.3, 0.3, length), (sx * (w / 2 - 0.2), rise / 2 + 3, -run * (n - 1) / 2),
                            rot=(-ang, 0, 0) if False else (ang, 0, 0), mat="wood" if mat != "metal" else "metal"))
            for i in range(0, n, 3):
                y = sh * (i + 1)
                out.append(part(ctx, "B", (0.25, 3, 0.25), (sx * (w / 2 - 0.2), y + 1.5, -run * i),
                                mat="wood" if mat != "metal" else "metal"))
    return out


@kit("railing", "balustrade / railing segment along X", {"len": (12, 2, 60), "h": (3, 2, 5),
     "mat": ("wood", ["wood", "metal", "stone", "marble"])}, footprint=(12, 1))
def railing(ctx, len, h, mat):  # noqa: A002 (kit parameter names the model writes)
    out = [part(ctx, "B", (len, 0.4, 0.6), (0, h, 0), mat=mat), part(ctx, "B", (len, 0.3, 0.4), (0, 0.15, 0), mat=mat)]
    step = 1.2 if ctx.style == "highpoly" else 2.0
    n = max(2, int(len / step))
    for i in range(n + 1):
        x = -len / 2 + len * i / n
        if ctx.style == "highpoly" and mat != "stone":
            out.append(_cyl_y(ctx, 0.25, h - 0.3, (x, h / 2, 0), mat=mat))
        else:
            out.append(part(ctx, "B", (0.3, h - 0.3, 0.3), (x, h / 2, 0), mat=mat))
    return out


@kit("fence", "wooden or metal fence along X (posts + rails)", {"len": (16, 4, 80), "h": (3, 2, 6),
     "kind": ("picket", ["picket", "rail", "iron", "broken"])}, footprint=(16, 1))
def fence(ctx, len, h, kind):  # noqa: A002 (kit parameter names the model writes)
    mat = "metal" if kind == "iron" else "wood"
    out = []
    posts = max(2, int(len / 6) + 1)
    for i in range(posts):
        x = -len / 2 + len * i / (posts - 1)
        tilt = ctx.rng.uniform(-8, 8) if kind == "broken" else 0
        out.append(part(ctx, "B", (0.5, h + 0.4, 0.5), (x, (h + 0.4) / 2, 0), rot=(tilt, 0, 0), mat=mat, vary=0.06))
    for y in (h * 0.35, h * 0.8):
        if kind == "broken" and ctx.rng.random() < 0.4:
            seg = len * 0.45
            out.append(part(ctx, "B", (seg, 0.35, 0.25), (-len / 4, y, 0.2), rot=(0, 0, ctx.rng.uniform(-12, 12)), mat=mat))
            continue
        out.append(part(ctx, "B", (len, 0.35, 0.25), (0, y, 0.2), mat=mat, vary=0.05))
    if kind in ("picket", "iron"):
        n = int(len / (0.9 if kind == "picket" else 0.7))
        for i in range(n):
            x = -len / 2 + 0.4 + i * len / n
            out.append(part(ctx, "B", (0.35 if kind == "picket" else 0.12, h * 0.95, 0.15),
                            (x, h * 0.95 / 2, 0.38), mat=mat, vary=0.05))
    return out


@kit("platform", "raised platform / stage / obby block", {"w": (8, 2, 60), "d": (8, 2, 60), "h": (1, 0.4, 30),
     "mat": ("stone", ["stone", "wood", "plank", "concrete", "marble", "metal", "grass", "neon", "brick"]),
     "edge": (1, 0, 1)}, footprint=(8, 8))
def platform(ctx, w, d, h, mat, edge):
    out = [part(ctx, "B", (w, h, d), (0, h / 2, 0), mat=mat, vary=0.03)]
    if edge and ctx.style != "stud" and h >= 0.8:
        trim = ctx.palette["trim"]
        out.append(part(ctx, "B", (w + 0.2, 0.25, d + 0.2), (0, h - 0.1, 0), mat="stone" if mat != "wood" else "wood",
                        color=trim))
    return out


@kit("cliff", "terraced cliff / rock mass (stacked staggered blocks, moss drips)", {"w": (16, 6, 80), "d": (10, 4, 60),
     "h": (14, 4, 60), "mat": ("rock", ["rock", "sandstone", "stone", "ground", "snow"]), "moss": (1, 0, 1)},
     footprint=(16, 10), tags=("nature",))
def cliff(ctx, w, d, h, mat, moss):
    out = []
    rng = ctx.rng
    layers = max(2, int(h / 4))
    lh = h / layers
    base_c = ctx.color(mat)
    alt_c = shade(base_c, 1.12) if ctx.style != "stud" else ctx.tone(shade(base_c, 1.25))
    for li in range(layers):
        shrink = li / layers
        cw, cd = w * (1 - 0.35 * shrink), d * (1 - 0.3 * shrink)
        blocks = 3 + int(cw / 8)
        x = -cw / 2
        # upper layers start below the top of the layer beneath so every block rests on it (stud rounding included)
        sink = 0 if li == 0 else lh * 0.2 + (0.5 if ctx.style == "stud" else 0)
        layer_top = prev_top = -1.0
        for bi in range(blocks):
            bw = cw / blocks * rng.uniform(0.85, 1.25)
            bh = ctx.snap(lh * rng.uniform(0.9, 1.35) + sink)
            bd = cd * rng.uniform(0.8, 1.0)
            off = rng.uniform(-1.5, 1.5)
            colr = alt_c if (bi + li) % 3 == 0 else base_c
            y0 = li * lh - sink
            if abs(y0 + bh - prev_top) < 0.05:   # snapped neighbours of equal height would z-fight on top
                bh += 1 if ctx.style == "stud" else 0.15
            out.append(part(ctx, "B", (ctx.snap(bw), bh, ctx.snap(bd)),
                            (x + bw / 2, y0 + bh / 2, off * (1 if li else 0.3)), mat=mat, color=colr))
            layer_top = max(layer_top, y0 + bh)
            prev_top = y0 + bh
            x += bw * 0.95
        if moss:
            top_y = layer_top   # the moss slab sits on the tallest block of this layer
            out.append(part(ctx, "B", (cw * 0.9, 0.6, cd * 0.85), (0, top_y + 0.1, 0), mat="grass", vary=0.05))
            for _ in range(int(cw / 5)):   # drips down the slab's front edge, clustered, not uniform
                dx = rng.uniform(-cw / 2.4, cw / 2.4)
                dl = rng.uniform(0.8, lh * 0.8)
                out.append(part(ctx, "B", (rng.choice((0.6, 1, 1.4)), dl, 0.3), (dx, top_y - dl / 2, -cd * 0.425 - 0.15),
                                mat="grass", color=shade(ctx.color("grass"), 1.05)))
    return out


# =========================================================================== furniture

@kit("pew", "church pew / long bench with back", {"len": (10, 4, 20), "broken": (0, 0, 1)}, footprint=(10, 3))
def pew(ctx, len, broken):  # noqa: A002 (kit parameter names the model writes)
    out = []
    tilt = ctx.rng.uniform(-10, 10) if broken else 0
    out.append(part(ctx, "B", (len, 0.4, 2), (0, 2, 0), rot=(0, 0, tilt * 0.3), mat="wood", vary=0.04))
    out.append(part(ctx, "B", (len, 3, 0.35), (0, 3.4, 0.95), rot=(tilt, 0, 0), mat="wood", vary=0.04))
    for sx in (-1, 1):
        end_h = 4.8 if ctx.style != "lowpoly" else 4.4
        out.append(part(ctx, "B", (0.5, end_h, 2.3), (sx * len / 2, end_h / 2, 0.15),
                        mat="wood", color=shade(ctx.color("wood"), 0.85)))
    if ctx.style in ("midpoly", "highpoly"):
        out.append(part(ctx, "B", (len - 0.6, 0.25, 0.6), (0, 0.8, 0.6), mat="wood"))   # kneeler rail
        out.append(part(ctx, "B", (len - 0.6, 0.15, 1.6), (0, 2.25, -0.1), mat="fabric", role="accent"))
    return out


@kit("bench", "simple bench (park / waiting)", {"len": (6, 3, 14), "mat": ("wood", ["wood", "metal", "stone"])},
     footprint=(6, 2))
def bench(ctx, len, mat):  # noqa: A002 (kit parameter names the model writes)
    out = [part(ctx, "B", (len, 0.3, 1.8), (0, 1.9, 0), mat=mat if mat != "metal" else "plank", vary=0.04)]
    out.append(part(ctx, "B", (len, 1.5, 0.25), (0, 2.75, 0.8), rot=(-10, 0, 0), mat=mat if mat != "metal" else "plank"))
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.35, 1.8, 1.6), (sx * (len / 2 - 0.5), 0.9, 0), mat="metal" if mat != "stone" else "stone",
                        color=ctx.palette["trim"]))
    return out


@kit("table", "table (square/long/round) with optional place settings", {"w": (4, 2, 16), "d": (3, 2, 8),
     "round": (0, 0, 1), "setting": (1, 0, 1), "mat": ("wood", ["wood", "metal", "marble", "stone", "plank"])},
     footprint=(5, 4))
def table(ctx, w, d, round, setting, mat):  # noqa: A002 (kit parameter names the model writes)
    out = []
    top_y = 3.0
    if round and ctx.style != "stud":
        out.append(part(ctx, "C", (0.3, w, w), (0, top_y, 0), rot=(0, 0, 90), mat=mat, vary=0.03))
        out.append(_cyl_y(ctx, 0.5, top_y - 0.2, (0, (top_y - 0.2) / 2, 0), mat="metal", color=ctx.palette["trim"]))
        out.append(_cyl_y(ctx, w * 0.45, 0.2, (0, 0.1, 0), mat="metal", color=ctx.palette["trim"]))
    else:
        out.append(part(ctx, "B", (w, 0.3, d), (0, top_y, 0), mat=mat, vary=0.03))
        for sx in (-1, 1):
            for sz in (-1, 1):
                out.append(part(ctx, "B", (0.35, top_y - 0.15, 0.35), (sx * (w / 2 - 0.4), (top_y - 0.15) / 2,
                                sz * (d / 2 - 0.4)), mat=mat, color=shade(ctx.color(mat), 0.85)))
    if setting:
        out += _tabletop(ctx, w, d, top_y + 0.15)
    return out


def _tabletop(ctx, w, d, y):
    """A few objects with intent: a cup by each seat side, one centrepiece."""
    out = []
    rng = ctx.rng
    for sx in (-1, 1):
        if rng.random() < 0.8:
            out.append(part(ctx, "C" if ctx.style != "stud" else "B", (0.6, 0.45, 0.45) if ctx.style != "stud" else (0.5, 0.6, 0.5),
                            (sx * w * 0.25, y + 0.3, rng.uniform(-d * 0.2, d * 0.2)),
                            rot=(0, 0, 90) if ctx.style != "stud" else (0, 0, 0), mat="ceramic", role="primary", collide=False))
            out.append(part(ctx, "B", (1.0, 0.06, 1.0), (sx * w * 0.25, y + 0.03, 0), mat="ceramic", collide=False,
                            color=(236, 232, 222)))
    out.append(part(ctx, "B" if ctx.style == "stud" else "C", (0.5, 0.9, 0.5) if ctx.style == "stud" else (0.9, 0.5, 0.5),
                    (0, y + 0.45, 0), rot=(0, 0, 0) if ctx.style == "stud" else (0, 0, 90), mat="glass", collide=False))
    out.append(part(ctx, "S" if ctx.style != "stud" else "B", (0.7, 0.7, 0.7), (0, y + 1.1, 0), mat="foliage",
                    role="accent", collide=False))
    return out


@kit("chair", "chair facing -Z", {"mat": ("wood", ["wood", "metal", "fabric", "plastic"]), "fallen": (0, 0, 1)},
     footprint=(2, 2))
def chair(ctx, mat, fallen):
    out = [part(ctx, "B", (1.8, 0.3, 1.8), (0, 2.0, 0), mat=mat if mat != "fabric" else "wood"),
           part(ctx, "B", (1.8, 2.2, 0.25), (0, 3.2, 0.8), mat=mat if mat != "fabric" else "wood")]
    if mat == "fabric":
        out.append(part(ctx, "B", (1.6, 0.25, 1.6), (0, 2.25, -0.05), mat="fabric", role="accent"))
    for sx in (-1, 1):
        for sz in (-1, 1):
            out.append(part(ctx, "B", (0.25, 1.85, 0.25), (sx * 0.75, 0.925, sz * 0.75), mat=mat if mat != "fabric" else "wood",
                            color=shade(ctx.color(mat if mat != "fabric" else "wood"), 0.85)))
    if fallen:
        transform(out, (0, 0, 0), 0)
        for p in out:   # tipped over backwards, lying on its back
            x, y, z = p["p"]
            p["p"] = [x, z + 0.95, -(y) + 2.2]
            p["r"] = [90, 0, 0]
    return out


@kit("stool", "bar stool (round seat)", {}, footprint=(2, 2))
def stool(ctx):
    out = []
    if ctx.style == "stud":
        out.append(part(ctx, "B", (1.6, 0.4, 1.6), (0, 3.2, 0), mat="fabric", role="accent"))
        out.append(part(ctx, "B", (0.5, 3.0, 0.5), (0, 1.5, 0), mat="metal"))
        out.append(part(ctx, "B", (1.4, 0.2, 1.4), (0, 0.1, 0), mat="metal"))
        return out
    out.append(part(ctx, "C", (0.45, 1.7, 1.7), (0, 3.25, 0), rot=(0, 0, 90), mat="leather" if ctx.style != "lowpoly" else "fabric",
                    role="accent"))
    out.append(_cyl_y(ctx, 0.35, 3.0, (0, 1.5, 0), mat="metal", color=ctx.palette["trim"]))
    out.append(part(ctx, "C", (0.15, 1.3, 1.3), (0, 1.1, 0), rot=(0, 0, 90), mat="metal", color=ctx.palette["trim"]))
    out.append(part(ctx, "C", (0.2, 1.4, 1.4), (0, 0.1, 0), rot=(0, 0, 90), mat="metal", color=ctx.palette["trim"]))
    return out


@kit("booth", "diner/cafe booth seat (two benches facing a table)", {"len": (6, 4, 10)}, footprint=(6, 9))
def booth(ctx, len):  # noqa: A002 (kit parameter names the model writes)
    out = []
    for sz in (-1, 1):
        out.append(part(ctx, "B", (len, 2.0, 2.4), (0, 1.0, sz * 3.4), mat="fabric", role="accent"))
        out.append(part(ctx, "B", (len, 3.4, 0.9), (0, 3.6, sz * 4.4), mat="fabric", role="accent"))
        out.append(part(ctx, "B", (len + 0.2, 0.3, 1.1), (0, 5.4, sz * 4.4), mat="wood", color=ctx.palette["trim"]))
    out += table(ctx, len - 1, 3, 0, 1, "wood")
    return out


@kit("sofa", "sofa / couch facing -Z", {"len": (7, 3, 14)}, footprint=(7, 3))
def sofa(ctx, len):  # noqa: A002 (kit parameter names the model writes)
    out = [part(ctx, "B", (len, 1.7, 3), (0, 0.85, 0), mat="fabric", role="accent"),
           part(ctx, "B", (len, 2.4, 0.9), (0, 2.6, 1.1), mat="fabric", role="accent", vary=0.03)]
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.9, 2.7, 3), (sx * (len / 2 - 0.45), 1.35, 0), mat="fabric", role="accent", vary=0.03))
    cushions = max(2, int(len / 3))
    for i in range(cushions):
        x = -len / 2 + 0.9 + (len - 1.8) * (i + 0.5) / cushions
        out.append(part(ctx, "B", ((len - 1.8) / cushions - 0.1, 0.5, 2.2), (x, 1.95, -0.25), mat="fabric",
                        color=shade(ctx.palette["accent"], 1.08)))
    if ctx.style in ("midpoly", "highpoly"):
        out.append(part(ctx, "B", (1.2, 1.2, 0.4), (len / 2 - 1.6, 2.6, 0.4), rot=(-15, 10, 0), mat="fabric", role="primary"))
    return out


@kit("bed", "bed with headboard, blanket and pillow; head at +Z", {"w": (5, 3, 8)}, footprint=(5, 8))
def bed(ctx, w):
    out = [part(ctx, "B", (w, 1.4, 7.5), (0, 0.9, 0), mat="wood"),
           part(ctx, "B", (w - 0.2, 0.8, 7.2), (0, 2.0, 0), mat="fabric", color=(236, 232, 222)),
           part(ctx, "B", (w + 0.1, 0.35, 5), (0, 2.5, -1.2), mat="fabric", role="accent"),
           part(ctx, "B", (w * 0.7, 0.6, 1.4), (0, 2.6, 2.85), mat="fabric", color=(240, 238, 232)),
           part(ctx, "B", (w + 0.4, 4.5, 0.5), (0, 2.25, 3.9), mat="wood", color=shade(ctx.color("wood"), 0.85))]
    return out


@kit("counter", "shop/cafe/bar counter along X, with top and clutter", {"len": (12, 4, 40),
     "clutter": (1, 0, 1)}, footprint=(12, 3))
def counter(ctx, len, clutter):  # noqa: A002 (kit parameter names the model writes)
    out = [part(ctx, "B", (len, 3.6, 2.4), (0, 1.8, 0), mat="wood", role="secondary"),
           part(ctx, "B", (len + 0.4, 0.3, 2.9), (0, 3.75, -0.1), mat="marble" if ctx.style != "stud" else "plastic",
                role="primary" if ctx.style == "stud" else "")]
    if ctx.style in ("midpoly", "highpoly"):
        n = int(len / 3)
        for i in range(n):   # front panelling
            out.append(part(ctx, "B", (len / n - 0.5, 2.4, 0.15), (-len / 2 + len / n * (i + 0.5), 1.8, -1.25),
                            mat="wood", color=shade(ctx.palette["secondary"], 0.85)))
        out.append(part(ctx, "B", (len, 0.4, 0.3), (0, 0.2, -1.3), mat="metal", color=ctx.palette["trim"]))
    if clutter:
        rng = ctx.rng
        x = -len / 2 + 1.2
        while x < len / 2 - 1:
            pick = rng.random()
            if pick < 0.3:   # register / machine block
                out.append(part(ctx, "B", (1.6, 1.2, 1.2), (x, 4.5, 0.2), mat="metal", color=ctx.palette["trim"]))
                out.append(part(ctx, "B", (1.2, 0.5, 0.15), (x, 5.0, -0.42), mat="neon", color=(160, 220, 255), collide=False))
                x += 2.6
            elif pick < 0.6:   # cups / jars cluster
                for k in range(rng.randint(2, 4)):
                    out.append(part(ctx, "C" if ctx.style != "stud" else "B", (0.7, 0.5, 0.5) if ctx.style != "stud" else (0.5, 0.7, 0.5),
                                    (x + k * 0.6, 4.25, rng.uniform(-0.3, 0.6)), rot=(0, 0, 90) if ctx.style != "stud" else (0, 0, 0),
                                    mat="ceramic", role=rng.choice(("primary", "accent")), collide=False))
                x += 3.2
            else:
                x += rng.uniform(1.5, 3.5)
    return out


@kit("shelf", "wall shelf unit with books/jars/boxes (back at +Z)", {"w": (6, 2, 16), "h": (8, 3, 16),
     "fill": ("books", ["books", "jars", "boxes", "mixed", "empty", "bottles"])}, footprint=(6, 2))
def shelf(ctx, w, h, fill):
    out = []
    depth = 1.6
    out.append(part(ctx, "B", (w, h, 0.25), (0, h / 2, depth / 2 - 0.12), mat="wood", role="secondary"))
    for sx in (-1, 1):
        out.append(part(ctx, "B", (0.3, h, depth), (sx * (w / 2 - 0.15), h / 2, 0), mat="wood", role="secondary"))
    levels = max(2, int(h / 2.2))
    rng = ctx.rng
    book_cols = [ctx.palette["accent"], ctx.palette["primary"], ctx.palette["trim"], ctx.palette["secondary"],
                 shade(ctx.palette["accent"], 0.7)]
    for li in range(levels + 1):
        y = 0.3 + li * (h - 0.6) / levels
        out.append(part(ctx, "B", (w - 0.5, 0.2, depth), (0, y, 0), mat="wood", role="secondary"))
        if li == levels or fill == "empty":
            continue
        gap = (h - 0.6) / levels - 0.3
        x = -w / 2 + 0.5
        mode = fill if fill != "mixed" else rng.choice(("books", "jars", "boxes"))
        while x < w / 2 - 0.6:
            if mode == "books":
                run = rng.randint(3, 9)   # books come in runs, with a gap or a leaning book between runs
                for _ in range(run):
                    bw = rng.choice((0.25, 0.3, 0.35, 0.4))
                    bh = gap * rng.uniform(0.6, 0.95)
                    if x + bw > w / 2 - 0.5:
                        break
                    out.append(part(ctx, "B", (bw, bh, depth * 0.75), (x + bw / 2, y + 0.1 + bh / 2, 0), mat="paper",
                                    color=rng.choice(book_cols), collide=False))
                    x += bw + 0.02
                x += rng.uniform(0.3, 1.0)
            elif mode in ("jars", "bottles"):
                s = 0.6 if mode == "jars" else 0.35
                hh = gap * (0.5 if mode == "jars" else 0.8)
                out.append(part(ctx, "C" if ctx.style != "stud" else "B", (hh, s, s) if ctx.style != "stud" else (s, hh, s),
                                (x + s / 2, y + 0.1 + hh / 2, 0), rot=(0, 0, 90) if ctx.style != "stud" else (0, 0, 0),
                                mat="glass", color=rng.choice(book_cols), t=0.25, collide=False))
                x += s + rng.uniform(0.15, 0.5)
            else:
                bw = rng.uniform(0.8, 1.6)
                bh = gap * rng.uniform(0.4, 0.85)
                out.append(part(ctx, "B", (bw, bh, depth * 0.8), (x + bw / 2, y + 0.1 + bh / 2, 0), mat="cardboard",
                                vary=0.08, collide=False))
                x += bw + rng.uniform(0.2, 0.8)
    return out


@kit("display_case", "museum/shop glass display case with an object inside", {"w": (4, 2, 10),
     "item": ("vase", ["vase", "skull", "gem", "book", "sword", "fossil"])}, footprint=(4, 3))
def display_case(ctx, w, item):
    d = 2.6
    out = [part(ctx, "B", (w, 3, d), (0, 1.5, 0), mat="wood", role="secondary"),
           part(ctx, "B", (w + 0.2, 0.2, d + 0.2), (0, 3.1, 0), mat="metal", color=ctx.palette["trim"]),
           part(ctx, "B", (w, 2.4, d), (0, 4.4, 0), mat="glass", t=0.75, collide=True),
           part(ctx, "B", (w + 0.2, 0.2, d + 0.2), (0, 5.7, 0), mat="metal", color=ctx.palette["trim"])]
    y = 3.2
    if item == "vase" and ctx.style == "highpoly":
        out.append(lathe(ctx, [(0.3, 0), (0.55, 0.3), (0.6, 0.8), (0.35, 1.3), (0.22, 1.6), (0.32, 1.8)], (0, y, 0), mat="ceramic",
                         role="accent", collide=False))
    elif item == "vase":
        out.append(part(ctx, "S" if ctx.style != "stud" else "B", (1.0, 1.2, 1.0), (0, y + 0.6, 0), mat="ceramic", role="accent", collide=False))
        out.append(part(ctx, "C" if ctx.style != "stud" else "B", (0.6, 0.5, 0.5) if ctx.style != "stud" else (0.5, 0.6, 0.5),
                        (0, y + 1.4, 0), rot=(0, 0, 90) if ctx.style != "stud" else (0, 0, 0), mat="ceramic", role="accent", collide=False))
    elif item == "gem":
        out.append(part(ctx, "B", (0.8, 0.8, 0.8), (0, y + 0.8, 0), rot=(45, 0, 45), mat="neon", role="accent", collide=False,
                        light=light("point", ctx.palette["accent"], 0.8, 6, shadows=False)))
    elif item == "skull":
        out.append(part(ctx, "S" if ctx.style != "stud" else "B", (1.0, 1.0, 1.1), (0, y + 0.55, 0), mat="ceramic", color=(226, 218, 196), collide=False))
    elif item == "sword":
        out.append(part(ctx, "B", (0.15, 0.3, 2.2), (0, y + 0.35, 0), rot=(0, 30, 0), mat="metal", collide=False))
    elif item == "fossil":
        for i in range(5):
            out.append(part(ctx, "B", (0.25, 0.15, 1.6 - i * 0.2), (-0.8 + i * 0.4, y + 0.1, 0), mat="ceramic", color=(220, 206, 176), collide=False))
    else:
        out.append(part(ctx, "B", (1.2, 0.3, 1.6), (0, y + 0.15, 0), rot=(0, 15, 0), mat="leather", role="accent", collide=False))
    return out


@kit("pedestal", "plinth with statue/bust/sculpture (focal object)", {"h": (4, 2, 8),
     "statue": ("bust", ["bust", "figure", "orb", "abstract", "none"])}, footprint=(3, 3))
def pedestal(ctx, h, statue):
    out = [part(ctx, "B", (2.6, 0.5, 2.6), (0, 0.25, 0), mat="marble"),
           part(ctx, "B", (2.0, h - 1, 2.0), (0, 0.5 + (h - 1) / 2, 0), mat="marble", vary=0.02),
           part(ctx, "B", (2.6, 0.5, 2.6), (0, h - 0.25, 0), mat="marble")]
    sc = (190, 190, 186) if not _abandoned(ctx) else (150, 150, 140)
    if statue == "bust":
        out.append(part(ctx, "B", (1.8, 1.2, 1.0), (0, h + 0.6, 0), mat="marble", color=sc))
        out.append(part(ctx, "S" if ctx.style != "stud" else "B", (1.1, 1.3, 1.1), (0, h + 1.8, 0), mat="marble", color=sc))
    elif statue == "figure":
        out.append(part(ctx, "B", (1.4, 3.0, 0.8), (0, h + 1.5, 0), mat="marble", color=sc))
        out.append(part(ctx, "S" if ctx.style != "stud" else "B", (0.9, 0.9, 0.9), (0, h + 3.5, 0), mat="marble", color=sc))
        out.append(part(ctx, "B", (0.4, 2.2, 0.4), (0.9, h + 2.0, 0), rot=(0, 0, -25), mat="marble", color=sc))
    elif statue == "orb":
        out.append(part(ctx, "S", (1.6, 1.6, 1.6), (0, h + 0.8, 0), mat="neon", role="accent",
                        light=light("point", ctx.palette["accent"], 1.2, 12)))
    elif statue == "abstract":
        out.append(part(ctx, "B", (1.0, 2.6, 1.0), (0, h + 1.3, 0), rot=(20, 35, 15), mat="metal", role="accent"))
    return out


@kit("fireplace", "stone fireplace with fire glow and mantel (back at +Z)", {"w": (7, 5, 12)}, footprint=(7, 3))
def fireplace(ctx, w):
    out = [part(ctx, "B", (w, 7, 2.2), (0, 3.5, 0.6), mat="brick" if ctx.style != "stud" else "stone"),
           part(ctx, "B", (w * 0.55, 3.4, 1.2), (0, 1.7, -0.3), mat="stone", color=(30, 26, 24)),
           part(ctx, "B", (w + 0.8, 0.5, 2.7), (0, 4.6, 0.25), mat="wood", role="secondary"),   # back 0.1 short of the wall face
           part(ctx, "B", (w * 0.4, 0.6, 0.8), (0, 0.5, -0.3), mat="neon", color=(255, 130, 50), collide=False,
                light=light("point", (255, 150, 80), 2.2, 20)),
           part(ctx, "B", (w * 0.45, 0.4, 0.5), (0, 0.25, -0.4), rot=(0, 10, 0), mat="wood")]
    for i, x in enumerate((-w * 0.3, 0, w * 0.3)):   # mantel objects
        out.append(part(ctx, "B", (0.6, 0.9 + i * 0.2, 0.5), (x, 5.3 + i * 0.1, 0.3), mat="ceramic",
                        role=("accent", "primary", "trim")[i], collide=False))
    return out


@kit("rug", "floor rug with border (zoning device)", {"w": (8, 2, 30), "d": (6, 2, 30)}, footprint=(8, 6))
def rug(ctx, w, d):
    out = [part(ctx, "B", (w, 0.08, d), (0, 0.04, 0), mat="carpet", role="accent", collide=False)]
    if ctx.style != "stud":
        out.append(part(ctx, "B", (w - 1.2, 0.12, d - 1.2), (0, 0.06, 0), mat="carpet", color=shade(ctx.palette["accent"], 0.7),
                        collide=False))
        out.append(part(ctx, "B", (w - 2.0, 0.16, d - 2.0), (0, 0.08, 0), mat="carpet", role="accent", collide=False))
    return out


@kit("cabinet", "low cabinet / sideboard / dresser (back at +Z)", {"w": (5, 2, 12), "h": (3.5, 2, 7)}, footprint=(5, 2))
def cabinet(ctx, w, h):
    out = [part(ctx, "B", (w, h, 2), (0, h / 2, 0), mat="wood", role="secondary"),
           part(ctx, "B", (w + 0.2, 0.2, 2.2), (0, h + 0.1, 0), mat="wood", color=shade(ctx.palette["secondary"], 0.85))]
    n = max(2, int(w / 2))
    for i in range(n):
        x = -w / 2 + w / n * (i + 0.5)
        out.append(part(ctx, "B", (w / n - 0.3, h - 0.8, 0.12), (x, h / 2, -1.02), mat="wood",
                        color=shade(ctx.palette["secondary"], 1.08)))
        out.append(part(ctx, "B", (0.15, 0.5, 0.15), (x + (w / n) * 0.3, h / 2, -1.12), mat="metal", color=(200, 170, 90)))
    return out


@kit("picture", "framed painting on a wall (back at +Z, hangs at y)", {"w": (4, 1, 12), "h": (3, 1, 10),
     "y": (6, 2, 30)}, footprint=(4, 1))
def picture(ctx, w, h, y):
    rng = ctx.rng
    out = [part(ctx, "B", (w, h, 0.3), (0, y, 0), mat="wood", color=(180, 140, 70) if ctx.style != "stud" else (245, 205, 48)),
           part(ctx, "B", (w - 0.6, h - 0.6, 0.1), (0, y, -0.15), mat="paint", role="primary")]
    # a simple composition inside: horizon + sun/shape so it reads as a painting, not a blank card
    out.append(part(ctx, "B", (w - 0.6, (h - 0.6) * 0.4, 0.1), (0, y - (h - 0.6) * 0.3, -0.18), mat="paint", role="secondary",
                    collide=False))
    out.append(part(ctx, "B", (0.7, 0.7, 0.1), (rng.uniform(-w / 4, w / 4), y + (h - 0.6) * 0.15, -0.2), mat="paint",
                    role="accent", collide=False))
    return out


@kit("sign", "sign board with text (wall or standing), front -Z", {"w": (6, 2, 20), "h": (2, 1, 6), "y": (8, 1, 30),
     "glow": (0, 0, 1)}, footprint=(6, 1))
def sign(ctx, w, h, y, glow):
    out = [part(ctx, "B", (w, h, 0.4), (0, y, 0), mat="wood" if not glow else "metal", role="trim")]
    p = part(ctx, "B", (w - 0.4, h - 0.4, 0.1), (0, y, -0.22), mat="neon" if glow else "paint", role="accent" if glow else "primary",
             collide=False, light=light("point", ctx.palette["accent"], 0.9, 10, shadows=False) if glow else None)
    p["text"] = True     # the compiler puts the scene's sign text on it (SurfaceGui)
    out.append(p)
    return out


# =========================================================================== lights (the mood makers)

@kit("pendant_lamp", "hanging pendant lamp from ceiling height y (warm pool of light)", {"y": (12, 6, 40),
     "drop": (4, 1, 20), "color": ("warm", ["warm", "cool", "amber", "red", "green"])}, footprint=(2, 2), tags=("light",))
def pendant_lamp(ctx, y, drop, color):
    col = {"warm": (255, 196, 130), "cool": (190, 220, 255), "amber": (255, 160, 70), "red": (255, 90, 80),
           "green": (150, 255, 160)}[color]
    out = [part(ctx, "B", (0.12, drop + 0.6, 0.12), (0, y - drop / 2 + 0.3, 0), mat="metal", color=(30, 30, 30), collide=False)]
    if ctx.style == "stud":
        out.append(part(ctx, "B", (1.6, 1.0, 1.6), (0, y - drop - 0.5, 0), mat="metal", role="trim", collide=False))
    else:
        out.append(part(ctx, "C", (1.0, 1.6, 1.6), (0, y - drop - 0.5, 0), rot=(0, 0, 90), mat="metal", role="trim", collide=False))
        out.append(part(ctx, "W", (1.6, 0.6, 0.8), (0, y - drop + 0.2, 0.4), mat="metal", role="trim", collide=False))
    out.append(part(ctx, "B" if ctx.style == "stud" else "S", (0.7, 0.7, 0.7), (0, y - drop - 1.05, 0), mat="neon", color=col,
                    collide=False, light=light("spot", col, 2.4, 22, angle=95, face="Bottom")))
    return out


@kit("chandelier", "chandelier with candles/bulbs hanging from y", {"y": (20, 8, 60), "r": (3, 1.5, 8),
     "drop": (5, 1, 20)}, footprint=(6, 6), tags=("light",))
def chandelier(ctx, y, r, drop):
    cy = y - drop
    out = [part(ctx, "B", (0.2, drop + 0.6, 0.2), (0, y - drop / 2 + 0.3, 0), mat="metal", color=(40, 36, 32), collide=False)]
    n = 6 if ctx.style in ("stud", "lowpoly") else (8 if ctx.style == "midpoly" else 12)
    out += _ring(ctx, r, cy, 0.25, 0.3, max(8, n), mat="metal", color=(170, 140, 80), collide=False)
    for i in range(4 if ctx.style in ("stud", "lowpoly") else 6):   # arms from the hub to the ring
        a = 2 * math.pi * i / (4 if ctx.style in ("stud", "lowpoly") else 6)
        out.append(part(ctx, "B", (0.2, 0.2, r), (math.sin(a) * r / 2, cy + 0.05, math.cos(a) * r / 2), rot=(0, math.degrees(a), 0),
                        mat="metal", color=(170, 140, 80), collide=False))
    if _abandoned(ctx):
        lit = ctx.rng.sample(range(n), max(1, n // 3))
    else:
        lit = list(range(n))
    for i in range(n):
        a = 2 * math.pi * i / n
        x, z = math.sin(a) * r, math.cos(a) * r
        out.append(part(ctx, "B", (0.3, 0.9, 0.3), (x, cy + 0.6, z), mat="paper", color=(240, 232, 210), collide=False))
        if i in lit:
            out.append(part(ctx, "B", (0.18, 0.3, 0.18), (x, cy + 1.2, z), mat="neon", color=(255, 190, 110), collide=False))
    out.append(part(ctx, "B", (0.8, 1.2, 0.8), (0, cy, 0), mat="metal", color=(170, 140, 80), collide=False,
                    light=light("point", (255, 190, 120), 1.6 if lit else 0.4, 24 + r * 2)))
    return out


@kit("sconce", "wall sconce / wall lamp (back at +Z)", {"y": (7, 3, 30), "color": ("warm", ["warm", "cool", "amber", "red"])},
     footprint=(1, 1), tags=("light",))
def sconce(ctx, y, color):
    col = {"warm": (255, 196, 130), "cool": (190, 220, 255), "amber": (255, 160, 70), "red": (255, 90, 80)}[color]
    return [part(ctx, "B", (0.8, 1.2, 0.3), (0, y, 0.15), mat="metal", role="trim", collide=False),
            part(ctx, "B", (0.25, 0.25, 0.9), (0, y - 0.2, -0.3), mat="metal", role="trim", collide=False),
            part(ctx, "B", (0.7, 0.9, 0.7), (0, y + 0.3, -0.8), mat="glass", color=col, t=0.2, collide=False,
                 light=light("point", col, 1.2, 14))]


@kit("floor_lamp", "standing floor lamp", {"color": ("warm", ["warm", "cool", "amber"])}, footprint=(2, 2), tags=("light",))
def floor_lamp(ctx, color):
    col = {"warm": (255, 196, 130), "cool": (190, 220, 255), "amber": (255, 160, 70)}[color]
    return [part(ctx, "B", (1.4, 0.2, 1.4), (0, 0.1, 0), mat="metal", role="trim"),
            part(ctx, "B", (0.2, 5.5, 0.2), (0, 2.85, 0), mat="metal", role="trim"),
            (lathe(ctx, [(1.1, 0), (0.65, 1.4)], (0, 5.5, 0), mat="fabric", color=(240, 225, 190), t=0.1, collide=False,
                   light=light("point", col, 1.4, 14)) if ctx.style == "highpoly" else
             part(ctx, "B" if ctx.style == "stud" else "C", (1.8, 1.4, 1.8) if ctx.style == "stud" else (1.4, 1.9, 1.9),
                  (0, 6.2, 0), rot=(0, 0, 0) if ctx.style == "stud" else (0, 0, 90), mat="fabric", color=(240, 225, 190),
                  t=0.1, collide=False, light=light("point", col, 1.4, 14)))]


@kit("lamp_post", "street / park lamp post", {"h": (10, 6, 18), "color": ("warm", ["warm", "cool", "amber"]),
     "broken": (0, 0, 1)}, footprint=(2, 2), tags=("light",))
def lamp_post(ctx, h, color, broken):
    col = {"warm": (255, 196, 130), "cool": (190, 220, 255), "amber": (255, 160, 70)}[color]
    out = [part(ctx, "B", (1.4, 1.0, 1.4), (0, 0.5, 0), mat="metal", role="trim"),
           (part(ctx, "B", (0.45, h, 0.45), (0, h / 2, 0), mat="metal", role="trim") if ctx.style == "stud"
            else _cyl_y(ctx, 0.45, h, (0, h / 2, 0), mat="metal", role="trim")),
           part(ctx, "B", (1.6, 0.3, 1.6), (0, h + 0.15, 0), mat="metal", role="trim")]
    out.append(part(ctx, "B", (1.1, 1.4, 1.1), (0, h + 1.0, 0), mat="glass", color=col, t=0.15, collide=False,
                    light=None if broken else light("point", col, 1.8, 22)))
    out.append(part(ctx, "W" if ctx.style != "stud" else "B", (1.7, 0.6, 1.7), (0, h + 2.0, 0), mat="metal", role="trim"))
    return out


@kit("string_lights", "festoon string of bulbs between two points (along X at height y)", {"len": (16, 4, 60),
     "y": (10, 4, 30), "sag": (1.5, 0, 6)}, footprint=(16, 1), tags=("light",))
def string_lights(ctx, len, y, sag):  # noqa: A002 (kit parameter names the model writes)
    out = []
    n = max(4, int(len / 2.2))
    for i in range(n + 1):
        t = i / n
        x = -len / 2 + len * t
        yy = y - sag * 4 * t * (1 - t)
        lit = i % 2 == 0
        out.append(part(ctx, "B" if ctx.style == "stud" else "S", (0.4, 0.5, 0.4), (x, yy - 0.3, 0), mat="neon",
                        color=(255, 210, 140), collide=False,
                        light=light("point", (255, 200, 130), 0.6, 8, shadows=False) if lit and i % 4 == 0 else None))
        if i < n:
            t2 = (i + 1) / n
            y2 = y - sag * 4 * t2 * (1 - t2)
            seg = math.hypot(len / n, y2 - yy)
            out.append(part(ctx, "B", (seg, 0.08, 0.08), (x + len / n / 2, (yy + y2) / 2, 0),
                            rot=(0, 0, math.degrees(math.atan2(y2 - yy, len / n))), mat="metal", color=(30, 30, 30), collide=False))
    return out


@kit("candles", "cluster of candles of different heights (floor or table, y = base)", {"y": (0, 0, 30), "n": (5, 1, 12)},
     footprint=(2, 2), tags=("light",))
def candles(ctx, y, n):
    out = []
    rng = ctx.rng
    for i in range(int(n)):
        a = rng.uniform(0, 2 * math.pi)
        rr = rng.uniform(0, 0.9)
        hh = rng.choice((0.6, 0.9, 1.3, 1.8))
        x, z = math.sin(a) * rr, math.cos(a) * rr
        out.append(part(ctx, "B" if ctx.style == "stud" else "C", (0.35, hh, 0.35) if ctx.style == "stud" else (hh, 0.35, 0.35),
                        (x, y + hh / 2, z), rot=(0, 0, 0) if ctx.style == "stud" else (0, 0, 90), mat="paper",
                        color=(240, 232, 210), collide=False))
        out.append(part(ctx, "B", (0.12, 0.25, 0.12), (x, y + hh + 0.15, z), mat="neon", color=(255, 180, 90), collide=False,
                        light=light("point", (255, 170, 90), 0.9, 9, shadows=False) if i == 0 else None))
    return out


@kit("led_strip", "linear light strip (under shelves / along counters), along X at height y", {"len": (8, 2, 40),
     "y": (6, 1, 30), "color": ("warm", ["warm", "cool", "pink", "cyan"])}, footprint=(8, 1), tags=("light",))
def led_strip(ctx, len, y, color):  # noqa: A002 (kit parameter names the model writes)
    col = {"warm": (255, 200, 140), "cool": (200, 225, 255), "pink": (255, 110, 190), "cyan": (90, 230, 255)}[color]
    p = part(ctx, "B", (len, 0.15, 0.2), (0, y, 0), mat="neon", color=col, collide=False,
             light=light("surface", col, 0.8, 10, angle=120, face="Bottom", shadows=False))
    return [p]


@kit("lantern", "standing/hanging lantern (y = base)", {"y": (0, 0, 30)}, footprint=(1, 1), tags=("light",))
def lantern(ctx, y):
    return [part(ctx, "B", (0.9, 0.2, 0.9), (0, y + 0.1, 0), mat="metal", role="trim"),
            part(ctx, "B", (0.7, 1.0, 0.7), (0, y + 0.7, 0), mat="glass", color=(255, 190, 110), t=0.2, collide=False,
                 light=light("point", (255, 170, 90), 1.0, 10)),
            part(ctx, "W" if ctx.style != "stud" else "B", (0.9, 0.4, 0.9), (0, y + 1.4, 0), mat="metal", role="trim"),
            part(ctx, "B", (0.1, 0.5, 0.1), (0, y + 1.8, 0), mat="metal", role="trim")]


@kit("campfire", "campfire ring with logs and glow", {}, footprint=(4, 4), tags=("light",))
def campfire(ctx):
    out = []
    for i in range(8):
        a = 2 * math.pi * i / 8
        out.append(part(ctx, "B", (0.9, 0.6, 0.9), (math.sin(a) * 1.7, 0.3, math.cos(a) * 1.7), rot=(0, ctx.rng.uniform(0, 90), 0),
                        mat="rock", vary=0.1))
    for a in (0, 60, 120):
        out.append(part(ctx, "B", (2.6, 0.45, 0.45), (0, 0.5, 0), rot=(0, a, 18), mat="wood"))
    out.append(part(ctx, "B", (0.8, 1.2, 0.8), (0, 1.0, 0), rot=(0, 45, 0), mat="neon", color=(255, 140, 50), collide=False,
                    light=light("point", (255, 150, 70), 2.4, 24)))
    return out


# =========================================================================== nature

@kit("tree", "tree (kind follows the style: blocky tiers for stud, faceted for lowpoly)", {"h": (14, 5, 40),
     "kind": ("oak", ["oak", "pine", "palm", "dead", "cherry", "birch"])}, footprint=(8, 8), tags=("nature",))
def tree(ctx, h, kind):
    out = []
    rng = ctx.rng
    trunk_h = h * (0.45 if kind in ("oak", "cherry") else 0.3 if kind == "pine" else 0.85)
    tw = max(0.8, h * 0.07)
    trunk_mat = "wood"
    if kind == "palm":
        segs = 5
        lean = rng.uniform(6, 14)
        x = y = 0.0
        for i in range(segs):
            seg_h = trunk_h / segs
            ang = lean * (i + 1) / segs
            x += math.sin(math.radians(ang)) * seg_h
            out.append(part(ctx, "B", (tw * (1 - i * 0.08), seg_h * 1.05, tw * (1 - i * 0.08)), (x, y + seg_h / 2, 0),
                            rot=(0, 0, -ang), mat=trunk_mat, color=shade(ctx.color("wood"), 1.2 - (i % 2) * 0.1)))
            y += seg_h * math.cos(math.radians(ang))
        for i in range(7):
            a = 360 * i / 7 + rng.uniform(-10, 10)
            out.append(part(ctx, "W" if ctx.style != "stud" else "B", (1.6, 0.4, h * 0.32),
                            (x + math.sin(math.radians(a)) * h * 0.14, y - 0.4, math.cos(math.radians(a)) * h * 0.14),
                            rot=(-18, a, 0), mat="foliage", vary=0.08, collide=False))
        return out
    stem = h * 0.95 if kind == "pine" else trunk_h   # a pine trunk runs up inside the tiers so every tier sits on it
    out.append(part(ctx, "B", (tw, stem, tw), (0, stem / 2, 0), mat=trunk_mat, vary=0.05,
                    color=(220, 220, 214) if kind == "birch" else None))
    if kind == "dead":
        for _ in range(4):
            a = rng.uniform(0, 360)
            bl = h * rng.uniform(0.2, 0.35)
            yy = trunk_h * rng.uniform(0.55, 0.95)
            out.append(part(ctx, "B", (tw * 0.45, bl, tw * 0.45), (math.sin(math.radians(a)) * bl * 0.35, yy + bl * 0.35,
                            math.cos(math.radians(a)) * bl * 0.35), rot=(math.cos(math.radians(a)) * 40, 0, -math.sin(math.radians(a)) * 40),
                            mat=trunk_mat, color=shade(ctx.color("wood"), 0.8)))
        return out
    leaf = ctx.color("foliage", vary=0.06) if kind != "cherry" else ctx.tone((236, 160, 190))
    if kind == "pine":
        tiers = 4 if ctx.style in ("stud", "lowpoly") else 6
        for i in range(tiers):
            frac = i / tiers
            w = h * 0.45 * (1 - frac * 0.8)
            th = (h - trunk_h) / tiers * 1.25
            yy = trunk_h + i * (h - trunk_h) / tiers + th / 2
            if ctx.style == "lowpoly":
                for a in (0, 90, 180, 270):   # four wedges = a faceted cone tier
                    out.append(part(ctx, "W", (w, th, w / 2), (math.sin(math.radians(a)) * w / 4, yy, math.cos(math.radians(a)) * w / 4),
                                    rot=(0, a + 180, 0), mat="foliage", color=shade(leaf, 1 + 0.05 * (i % 2)), collide=False))
            else:
                out.append(part(ctx, "B", (ctx.snap(w), ctx.snap(max(1, th * 0.8)), ctx.snap(w)), (0, yy, 0),
                                rot=(0, 45 * (i % 2) if ctx.style != "stud" else 0, 0), mat="foliage",
                                color=shade(leaf, 1 + 0.06 * (i % 2)), collide=False))
        return out
    # oak / cherry / birch: 3-6 canopy clumps placed asymmetrically
    clumps = {"stud": 4, "lowpoly": 4, "midpoly": 6, "highpoly": 9}[ctx.style]
    canopy_y = trunk_h + h * 0.18
    for i in range(clumps):
        a = 2 * math.pi * i / clumps + rng.uniform(-0.4, 0.4)
        rr = h * rng.uniform(0.08, 0.2)
        s = h * rng.uniform(0.26, 0.36)
        pos = (math.sin(a) * rr, canopy_y + rng.uniform(-h * 0.06, h * 0.1), math.cos(a) * rr)
        if ctx.style == "stud":
            out.append(part(ctx, "B", (round(s), round(s * 0.7), round(s)), pos, mat="foliage", color=shade(leaf, 1 + 0.06 * (i % 2)),
                            collide=False))
        elif ctx.style == "lowpoly":
            out.append(part(ctx, "B", (s, s * 0.8, s), pos, rot=(rng.uniform(0, 40), rng.uniform(0, 90), rng.uniform(0, 40)),
                            mat="foliage", color=shade(leaf, 1 + 0.07 * (i % 2)), collide=False))
        else:
            out.append(part(ctx, "S", (s, s * 0.85, s), pos, mat="foliage", color=shade(leaf, 1 + 0.05 * (i % 3 - 1)),
                            collide=False))
    out.append(part(ctx, "S" if ctx.style not in ("stud", "lowpoly") else "B", (h * 0.38, h * 0.3, h * 0.38),
                    (0, canopy_y + h * 0.16, 0), mat="foliage", color=shade(leaf, 1.08), collide=False))
    # two branches into the canopy so clumps do not float
    for sx in (-1, 1):
        out.append(part(ctx, "B", (tw * 0.5, h * 0.25, tw * 0.5), (sx * h * 0.06, trunk_h + h * 0.08, 0), rot=(0, 0, -sx * 30),
                        mat=trunk_mat, vary=0.05))
    return out


@kit("bush", "shrub / hedge clump", {"w": (3, 1, 12), "flowers": (0, 0, 1)}, footprint=(3, 3), tags=("nature",))
def bush(ctx, w, flowers):
    out = []
    rng = ctx.rng
    n = 3 if ctx.style in ("stud", "lowpoly") else 5
    clumps = []
    for i in range(n):
        s = w * rng.uniform(0.5, 0.8)
        pos = (rng.uniform(-w / 4, w / 4), s * 0.4, rng.uniform(-w / 4, w / 4))
        clumps.append((pos, s))
        shape = "S" if ctx.style in ("midpoly", "highpoly") else "B"
        out.append(part(ctx, shape, (s, s * 0.8, s), pos, rot=(0, rng.uniform(0, 90), 0) if shape == "B" and ctx.style == "lowpoly" else (0, 0, 0),
                        mat="foliage", vary=0.08, collide=False))
    if flowers:
        for _ in range(int(w * 2)):   # flowers sit on the crown of a clump
            (cx, _cy, cz), s = rng.choice(clumps)
            out.append(part(ctx, "B", (0.35, 0.35, 0.35), (cx + rng.uniform(-s / 4, s / 4), s * 0.775, cz + rng.uniform(-s / 4, s / 4)),
                            mat="paint", role="accent", collide=False))
    return out


@kit("rocks", "cluster of rocks/boulders", {"w": (4, 1, 20)}, footprint=(4, 4), tags=("nature",))
def rocks(ctx, w):
    out = []
    rng = ctx.rng
    n = 3 + int(w / 4)
    for i in range(n):
        s = w * (0.45 if i == 0 else rng.uniform(0.15, 0.3))
        pos = (rng.uniform(-w / 3, w / 3) if i else 0, s * 0.35, rng.uniform(-w / 3, w / 3) if i else 0)
        if ctx.style == "stud":
            out.append(part(ctx, "B", (round(max(1, s)), round(max(1, s * 0.7)), round(max(1, s * 0.9))), pos, mat="rock"))
        elif ctx.style == "lowpoly":
            out.append(part(ctx, "B", (s, s * 0.75, s * 0.9), pos, rot=(rng.uniform(-20, 20), rng.uniform(0, 90), rng.uniform(-20, 20)),
                            mat="rock", vary=0.08))
        else:
            out.append(part(ctx, "S" if i % 2 else "B", (s, s * 0.7, s * 0.9), pos,
                            rot=(rng.uniform(-15, 15), rng.uniform(0, 90), rng.uniform(-15, 15)), mat="rock", vary=0.1))
    return out


@kit("grass_tufts", "small grass tufts / flowers patch (ground dressing)", {"w": (6, 2, 30), "flowers": (1, 0, 1)},
     footprint=(6, 6), tags=("nature",))
def grass_tufts(ctx, w, flowers):
    out = []
    rng = ctx.rng
    n = int(w * 1.2)
    for _ in range(n):
        x, z = rng.gauss(0, w / 4), rng.gauss(0, w / 4)
        hh = rng.uniform(0.4, 1.1)
        out.append(part(ctx, "B" if ctx.style != "lowpoly" else "W", (0.3, hh, 0.3 if ctx.style != "lowpoly" else 0.6), (x, hh / 2, z),
                        rot=(0, rng.uniform(0, 90), 0) if ctx.style != "stud" else (0, 0, 0), mat="grass",
                        color=shade(ctx.color("grass"), rng.uniform(0.95, 1.2)), collide=False))
        if flowers and rng.random() < 0.25:
            out.append(part(ctx, "B", (0.3, 0.3, 0.3), (x, hh + 0.1, z), mat="paint", role="accent", collide=False))
    return out


@kit("water", "water surface (pond/lake/pool), top at y", {"w": (20, 4, 400), "d": (20, 4, 400), "y": (-0.5, -10, 10)},
     footprint=(20, 20), tags=("nature",))
def water(ctx, w, d, y):
    out = [part(ctx, "B", (w, 0.6, d), (0, y - 0.3, 0), mat="water", t=0.25 if ctx.style != "stud" else 0.2,
                color=ctx.tone((70, 140, 170)), collide=False, cast=False)]
    out.append(part(ctx, "B", (w, 0.4, d), (0, y - 3.0, 0), mat="sand", color=shade(ctx.color("sand"), 0.7)))
    return out


# =========================================================================== story props (clutter with intent)

@kit("crate", "wooden crate stack", {"n": (1, 1, 6)}, footprint=(3, 3))
def crate(ctx, n):
    out = []
    rng = ctx.rng
    y = 0
    for i in range(int(n)):
        s = rng.choice((2.0, 2.5, 3.0)) if i == 0 else rng.choice((1.6, 2.0, 2.5))
        out.append(part(ctx, "B", (s, s, s), (rng.uniform(-0.3, 0.3) if i else 0, y + s / 2, rng.uniform(-0.3, 0.3) if i else 0),
                        rot=(0, rng.uniform(-15, 15) if ctx.style != "stud" else 0, 0), mat="plank", vary=0.08))
        if ctx.style in ("midpoly", "highpoly"):
            out.append(part(ctx, "B", (s + 0.05, 0.3, 0.3), (out[-1]["p"][0], y + s / 2, out[-1]["p"][2] - s / 2), rot=(0, 0, 45),
                            mat="wood", color=shade(ctx.color("plank"), 0.75)))
        y += s
        if rng.random() < 0.35:
            break
    return out


@kit("barrel", "barrel (upright or tipped)", {"tipped": (0, 0, 1)}, footprint=(2, 2))
def barrel(ctx, tipped):
    if ctx.style == "stud":
        out = [part(ctx, "B", (2, 3, 2), (0, 1.5, 0), mat="wood")]
        out.append(part(ctx, "B", (2.2, 0.3, 2.2), (0, 2.2, 0), mat="metal"))
        return out
    if tipped:
        return [part(ctx, "C", (3, 2.2, 2.2), (0, 1.1, 0), rot=(0, ctx.rng.uniform(0, 180), 0), mat="wood", vary=0.06),
                part(ctx, "C", (0.25, 2.35, 2.35), (0, 1.1, 0), mat="metal", color=(70, 64, 60))]
    if ctx.style == "highpoly":
        prof = [(0.95, 0), (1.05, 0.4), (1.17, 1.0), (1.22, 1.5), (1.17, 2.0), (1.05, 2.6), (0.95, 3.0)]
        return [lathe(ctx, prof, (0, 0, 0), mat="wood", vary=0.06),
                lathe(ctx, [(1.09, 0), (1.14, 0.25)], (0, 0.45, 0), mat="metal", color=(70, 64, 60)),
                lathe(ctx, [(1.14, 0), (1.09, 0.25)], (0, 2.3, 0), mat="metal", color=(70, 64, 60))]
    return [_cyl_y(ctx, 2.2, 3, (0, 1.5, 0), mat="wood", vary=0.06),
            _cyl_y(ctx, 2.35, 0.25, (0, 0.6, 0), mat="metal", color=(70, 64, 60)),
            _cyl_y(ctx, 2.35, 0.25, (0, 2.4, 0), mat="metal", color=(70, 64, 60))]


@kit("rubble", "collapsed debris pile (broken stone/planks) - place near walls or under holes", {"w": (5, 2, 20),
     "mat": ("stone", ["stone", "brick", "plank", "concrete", "rock"])}, footprint=(5, 5))
def rubble(ctx, w, mat):
    out = []
    rng = ctx.rng
    n = int(5 + w * 1.5)
    for i in range(n):
        s = rng.uniform(0.4, 1.4) * (1.6 if i < 2 else 1)
        rr = abs(rng.gauss(0, w / 4))
        a = rng.uniform(0, 2 * math.pi)
        x, z = math.sin(a) * rr, math.cos(a) * rr
        y = max(s * 0.3, (w / 3) * math.exp(-(rr / (w / 3)) ** 2) * 0.6)
        size = (s * 1.3, s * 0.6, s) if mat != "plank" else (s * 3, 0.25, 0.7)
        if ctx.style == "stud":
            size = tuple(max(1, round(v)) for v in size) if mat != "plank" else (3, 0.4, 1)
            y = size[1] / 2 + (out[0]["z"][1] if 0 < i < 3 and out else 0)   # on the floor; two stacked on the first
            if 0 < i < 3 and out:
                x, z = out[0]["p"][0] + rng.uniform(-0.3, 0.3), out[0]["p"][2] + rng.uniform(-0.3, 0.3)
            out.append(part(ctx, "B", size, (x, y, z), rot=(0, rng.choice((0, 90)), 0), mat=mat))
        else:
            out.append(part(ctx, "B", size, (x, y, z), rot=(rng.uniform(-25, 25), rng.uniform(0, 180), rng.uniform(-25, 25)),
                            mat=mat, vary=0.1))
    return out


@kit("planks", "loose/fallen planks or boards leaning on a wall", {"n": (3, 1, 8)}, footprint=(4, 2))
def planks(ctx, n):
    out = []
    rng = ctx.rng
    for i in range(int(n)):
        ln = rng.uniform(4, 7)
        lean = rng.uniform(15, 30)
        out.append(part(ctx, "B", (0.9, ln, 0.2), (i * 1.0 - n / 2, ln / 2 * math.cos(math.radians(lean)), math.sin(math.radians(lean)) * ln / 2 - 0.5),
                        rot=(-lean, rng.uniform(-6, 6), 0), mat="plank", vary=0.1))
    return out


@kit("cobweb", "corner cobweb (thin translucent strands) at height y", {"y": (10, 3, 40), "s": (3, 1, 8)}, footprint=(1, 1))
def cobweb(ctx, y, s):
    """Corner web: a faint sheet across the corner plus three sagging threads (corner at local +Z back)."""
    out = [part(ctx, "W", (s, s * 0.7, 0.04), (0, y - s * 0.35, -0.05), rot=(0, 0, 180), mat="plastic",
                color=(225, 225, 220), t=0.82, collide=False, cast=False)]
    for k, f in enumerate((0.45, 0.7, 0.95)):
        out.append(part(ctx, "B", (s * f, 0.03, 0.03), (0, y - s * 0.7 * (1 - f) - 0.05 * k, -0.1), rot=(0, 0, 4 - 4 * k),
                        mat="plastic", color=(220, 220, 215), t=0.55, collide=False, cast=False))
    return out


@kit("vines", "hanging vines / moss drips down a wall from height y (back at +Z)", {"y": (12, 3, 40), "w": (4, 1, 16)},
     footprint=(4, 1), tags=("nature",))
def vines(ctx, y, w):
    out = []
    rng = ctx.rng
    for _ in range(int(w * 1.4)):
        x = rng.uniform(-w / 2, w / 2)
        ln = rng.uniform(1.5, y * 0.5)
        out.append(part(ctx, "B", (rng.choice((0.3, 0.5, 0.7)), ln, 0.2), (x, y - ln / 2, -0.1 - rng.choice((0, 0.05, 0.1))), mat="foliage",
                        color=shade(ctx.color("foliage"), rng.uniform(0.9, 1.15)), collide=False))
    out.append(part(ctx, "B", (w, 0.6, 0.6), (0, y, -0.2), mat="foliage", vary=0.05, collide=False))
    return out


@kit("papers", "scattered papers / leaves on the floor (story trail)", {"w": (4, 1, 16)}, footprint=(4, 4))
def papers(ctx, w):
    out = []
    rng = ctx.rng
    for _ in range(int(w * 2)):
        out.append(part(ctx, "B", (0.8, 0.04, 1.1), (rng.gauss(0, w / 4), 0.03, rng.gauss(0, w / 4)), rot=(0, rng.uniform(0, 180), 0),
                        mat="paper", vary=0.06, collide=False, cast=False))
    return out


@kit("puddle", "water puddle on the floor", {"w": (4, 1, 14)}, footprint=(4, 4))
def puddle(ctx, w):
    return [part(ctx, "C" if ctx.style != "stud" else "B", (0.05, w, w * 0.7) if ctx.style != "stud" else (w, 0.05, w * 0.7),
                 (0, 0.03, 0), rot=(0, 0, 90) if ctx.style != "stud" else (0, 0, 0), mat="water", t=0.35, collide=False,
                 color=ctx.tone((60, 80, 90)), cast=False)]


@kit("potted_plant", "plant in a pot (indoor)", {"h": (4, 2, 9)}, footprint=(2, 2), tags=("nature",))
def potted_plant(ctx, h):
    out = [part(ctx, "B" if ctx.style == "stud" else "C", (1.6, 1.6, 1.6) if ctx.style == "stud" else (1.6, 1.7, 1.7), (0, 0.8, 0),
                rot=(0, 0, 0) if ctx.style == "stud" else (0, 0, 90), mat="ceramic", role="primary")]
    if ctx.style == "highpoly":
        out = [lathe(ctx, [(0.6, 0), (0.7, 0.1), (0.85, 1.1), (0.95, 1.45), (0.88, 1.6)], (0, 0, 0), mat="ceramic", role="primary"),
               part(ctx, "C", (0.1, 1.6, 1.6), (0, 1.5, 0), rot=(0, 0, 90), mat="ground", color=(70, 52, 40), collide=False)]
    rng = ctx.rng
    n = 4 if ctx.style in ("stud", "lowpoly") else 7
    for i in range(n):
        a = 2 * math.pi * i / n
        lh = h * rng.uniform(0.5, 0.9)
        out.append(part(ctx, "W" if ctx.style == "lowpoly" else "B", (0.5, lh, 1.0 if ctx.style != "stud" else 1),
                        (math.sin(a) * 0.5, 1.6 + lh / 2, math.cos(a) * 0.5), rot=(math.cos(a) * 18, math.degrees(a), -math.sin(a) * 18) if ctx.style != "stud" else (0, 0, 0),
                        mat="foliage", vary=0.07, collide=False))
    return out


@kit("trash", "trash bags / cans by a wall", {}, footprint=(3, 2))
def trash(ctx):
    rng = ctx.rng
    out = []
    for i in range(3):
        s = rng.uniform(1.2, 1.8)
        out.append(part(ctx, "S" if ctx.style in ("midpoly", "highpoly") else "B", (s, s * 0.85, s), (i * 1.2 - 1.2, s * 0.4, rng.uniform(-0.3, 0.3)),
                        mat="plastic", color=(34, 36, 38), collide=False))
    return out
