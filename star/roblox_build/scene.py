"""Scene spec -> parts, lighting and cameras.

Coordinates of a spec: x across, z deep, y up; the build is centred on (0, 0) with size [W, D]. Sides: N = -Z edge,
S = +Z edge, W = -X edge, E = +X edge. Ground top is y = 0; a room floor top is y = FLOOR.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from . import kits
from . import kits_themed  # noqa: F401  (registers the themed kits)
from .geom import STYLES, Ctx, MATERIALS, aabb, clamp, hex_rgb, light, part, shade

FLOOR = 0.2
WALL_T = {"stud": 1.0, "lowpoly": 1.2, "midpoly": 1.2, "highpoly": 1.4}
MOODS = ("sunny_day", "warm_evening", "cozy_interior", "overcast", "foggy_horror", "cold_night", "underwater_dim",
         "golden_hour", "neon_night")
STATES = ("new", "worn", "abandoned")
ROOFS = ("flat", "gable", "vault", "none", "broken")
SIDES = ("N", "S", "E", "W")
OPENINGS = ("door", "window", "arch", "open")
WINDOWS = ("plain", "stained", "arched", "none")
MAX_SIZE = 400
MAX_PROPS = 160
MAX_PARTS = 9000

# Lighting presets (Roblox Lighting / Atmosphere / post properties). Future lighting for every mood.
LIGHTING = {
    "sunny_day": {"ClockTime": 13.5, "Brightness": 2.6, "Ambient": (110, 110, 118), "OutdoorAmbient": (140, 140, 150),
                  "ShadowSoftness": 0.25, "EnvDiffuse": 1, "EnvSpecular": 1,
                  "Atmosphere": {"Density": 0.28, "Offset": 0.1, "Color": (199, 214, 230), "Decay": (106, 136, 170), "Glare": 0.2, "Haze": 1.2},
                  "CC": {"Brightness": 0.02, "Contrast": 0.08, "Saturation": 0.12, "Tint": (255, 252, 246)},
                  "Bloom": {"Intensity": 0.6, "Size": 24, "Threshold": 1.4}, "SunRays": {"Intensity": 0.06, "Spread": 0.8}},
    "golden_hour": {"ClockTime": 17.6, "Brightness": 2.2, "Ambient": (100, 84, 74), "OutdoorAmbient": (150, 120, 100),
                    "ShadowSoftness": 0.3, "EnvDiffuse": 1, "EnvSpecular": 1,
                    "Atmosphere": {"Density": 0.35, "Offset": 0.15, "Color": (255, 206, 160), "Decay": (190, 120, 90), "Glare": 0.6, "Haze": 1.8},
                    "CC": {"Brightness": 0.0, "Contrast": 0.12, "Saturation": 0.15, "Tint": (255, 236, 214)},
                    "Bloom": {"Intensity": 0.8, "Size": 28, "Threshold": 1.2}, "SunRays": {"Intensity": 0.12, "Spread": 0.7}},
    "warm_evening": {"ClockTime": 18.6, "Brightness": 1.5, "Ambient": (90, 76, 72), "OutdoorAmbient": (112, 96, 104),
                     "ShadowSoftness": 0.35, "EnvDiffuse": 0.7, "EnvSpecular": 0.8,
                     "Atmosphere": {"Density": 0.38, "Offset": 0.2, "Color": (220, 160, 140), "Decay": (110, 70, 90), "Glare": 0.4, "Haze": 2.0},
                     "CC": {"Brightness": 0.0, "Contrast": 0.15, "Saturation": 0.1, "Tint": (255, 232, 210)},
                     "Bloom": {"Intensity": 0.9, "Size": 28, "Threshold": 1.0}, "SunRays": {"Intensity": 0.08, "Spread": 0.6}},
    "cozy_interior": {"ClockTime": 16.8, "Brightness": 1.8, "Ambient": (104, 90, 78), "OutdoorAmbient": (128, 112, 100),
                      "ShadowSoftness": 0.4, "EnvDiffuse": 0.6, "EnvSpecular": 0.6,
                      "Atmosphere": {"Density": 0.3, "Offset": 0.1, "Color": (240, 200, 160), "Decay": (140, 100, 80), "Glare": 0.2, "Haze": 1.0},
                      "CC": {"Brightness": 0.03, "Contrast": 0.12, "Saturation": 0.08, "Tint": (255, 236, 214)},
                      "Bloom": {"Intensity": 0.8, "Size": 26, "Threshold": 1.0}, "SunRays": {"Intensity": 0.04, "Spread": 0.5}},
    "overcast": {"ClockTime": 12.0, "Brightness": 1.3, "Ambient": (100, 104, 110), "OutdoorAmbient": (130, 134, 140),
                 "ShadowSoftness": 0.8, "EnvDiffuse": 1, "EnvSpecular": 0.5,
                 "Atmosphere": {"Density": 0.42, "Offset": 0.25, "Color": (190, 196, 204), "Decay": (120, 126, 136), "Glare": 0, "Haze": 2.2},
                 "CC": {"Brightness": 0.0, "Contrast": 0.05, "Saturation": -0.15, "Tint": (240, 244, 250)},
                 "Bloom": {"Intensity": 0.3, "Size": 20, "Threshold": 1.6}, "SunRays": {"Intensity": 0.0, "Spread": 0.5}},
    "foggy_horror": {"ClockTime": 7.4, "Brightness": 1.6, "Ambient": (74, 80, 92), "OutdoorAmbient": (96, 104, 118),
                     "ShadowSoftness": 0.5, "EnvDiffuse": 0.5, "EnvSpecular": 0.5,
                     "Atmosphere": {"Density": 0.42, "Offset": 0.05, "Color": (120, 130, 138), "Decay": (60, 70, 80), "Glare": 0, "Haze": 2.4},
                     "CC": {"Brightness": 0.02, "Contrast": 0.2, "Saturation": -0.3, "Tint": (214, 228, 236)},
                     "Bloom": {"Intensity": 1.0, "Size": 30, "Threshold": 0.9}, "SunRays": {"Intensity": 0.0, "Spread": 0.5}},
    "cold_night": {"ClockTime": 22.5, "Brightness": 1.0, "Ambient": (60, 68, 92), "OutdoorAmbient": (80, 92, 124),
                   "ShadowSoftness": 0.4, "EnvDiffuse": 0.5, "EnvSpecular": 0.6,
                   "Atmosphere": {"Density": 0.35, "Offset": 0.1, "Color": (120, 140, 180), "Decay": (50, 60, 90), "Glare": 0.1, "Haze": 1.5},
                   "CC": {"Brightness": 0.0, "Contrast": 0.15, "Saturation": -0.1, "Tint": (220, 232, 255)},
                   "Bloom": {"Intensity": 1.0, "Size": 30, "Threshold": 0.9}, "SunRays": {"Intensity": 0.0, "Spread": 0.5}},
    "underwater_dim": {"ClockTime": 14.0, "Brightness": 0.8, "Ambient": (30, 70, 90), "OutdoorAmbient": (40, 90, 110),
                       "ShadowSoftness": 0.6, "EnvDiffuse": 0.6, "EnvSpecular": 0.8,
                       "Atmosphere": {"Density": 0.5, "Offset": 0.0, "Color": (60, 140, 170), "Decay": (20, 70, 100), "Glare": 0, "Haze": 2.5},
                       "CC": {"Brightness": 0.0, "Contrast": 0.12, "Saturation": -0.05, "Tint": (200, 236, 255)},
                       "Bloom": {"Intensity": 1.0, "Size": 30, "Threshold": 0.9}, "SunRays": {"Intensity": 0.0, "Spread": 0.5}},
    "neon_night": {"ClockTime": 23.0, "Brightness": 0.8, "Ambient": (60, 48, 84), "OutdoorAmbient": (80, 60, 110),
                   "ShadowSoftness": 0.3, "EnvDiffuse": 0.5, "EnvSpecular": 1,
                   "Atmosphere": {"Density": 0.4, "Offset": 0.1, "Color": (120, 80, 160), "Decay": (40, 20, 80), "Glare": 0.2, "Haze": 1.8},
                   "CC": {"Brightness": 0.0, "Contrast": 0.2, "Saturation": 0.2, "Tint": (236, 226, 255)},
                   "Bloom": {"Intensity": 1.2, "Size": 32, "Threshold": 0.8}, "SunRays": {"Intensity": 0.0, "Spread": 0.5}},
}


# --------------------------------------------------------------------------- spec normalisation

def _num(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return clamp(number, low, high)


def _xz(value, half_w, half_d):
    if isinstance(value, dict):
        value = [value.get("x"), value.get("z")]
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    x, z = _num(value[0], None, -half_w, half_w), _num(value[-1] if len(value) == 2 else value[2], None, -half_d, half_d)
    if x is None or z is None:
        return None
    return [round(x, 2), round(z, 2)]


def prop_from_list(row: list) -> dict | None:
    """[kit, x, z, rot, {params}, n, dx, dz] -> prop dict (the compact form the prompts ask for)."""
    if not row or not isinstance(row[0], str):
        return None
    out = {"kit": row[0], "at": list(row[1:3]) if len(row) >= 3 else None, "rot": row[3] if len(row) > 3 else 0}
    params = row[4] if len(row) > 4 and isinstance(row[4], dict) else {}
    if "y" in params:
        params = dict(params)
        out["y"] = params.pop("y")
    out["params"] = params
    if len(row) > 7:
        out["repeat"] = {"n": row[5], "step": [row[6], row[7]]}
    return out


def normalize(raw: dict) -> tuple[dict, list[str]]:
    """Clamp and clean an LLM-written spec. Returns (spec, notes about what was dropped or changed)."""
    notes: list[str] = []
    raw = raw if isinstance(raw, dict) else {}
    style = raw.get("style") if raw.get("style") in STYLES else "midpoly"
    if raw.get("style") not in STYLES:
        notes.append(f"style {raw.get('style')!r} unknown -> midpoly")
    size_raw = raw.get("size")
    size = size_raw if isinstance(size_raw, list) and len(size_raw) == 2 else [80, 80]
    w, d = _num(size[0], 80, 20, MAX_SIZE), _num(size[1], 80, 20, MAX_SIZE)
    hw, hd = w / 2, d / 2
    pal_raw = raw.get("palette")
    pal = pal_raw if isinstance(pal_raw, dict) else {}
    spec = {
        "name": str(raw.get("name") or "Build")[:48], "style": style,
        "state": raw.get("state") if raw.get("state") in STATES else "worn",
        "mood": raw.get("mood") if raw.get("mood") in MOODS else "sunny_day",
        "palette": {k: v for k, v in pal.items() if k in ("primary", "secondary", "accent", "trim") and hex_rgb(v)},
        "size": [w, d], "ground": raw.get("ground") if raw.get("ground") in MATERIALS else "grass",
        "sign_text": str(raw.get("sign_text") or "")[:40], "seed": int(_num(raw.get("seed"), 7, 0, 10 ** 6)),
        "zones": [], "rooms": [], "props": [], "paths": [], "focal": [], "spawn": [0, hd - 6],
        "budget": bool(raw.get("budget")),
    }
    if raw.get("preset"):
        from ..roblox_lighting_presets import PRESET_NAMES
        if raw["preset"] in PRESET_NAMES:
            spec["preset"] = raw["preset"]
    if raw.get("mood") not in MOODS:
        notes.append(f"mood {raw.get('mood')!r} unknown -> sunny_day")
    zone_ids = set()
    for z in (raw.get("zones") or [])[:16]:
        if not isinstance(z, dict) or not isinstance(z.get("rect"), list) or len(z["rect"]) != 4:
            notes.append("zone without rect dropped")
            continue
        x0, z0, x1, z1 = (_num(v, 0, -MAX_SIZE, MAX_SIZE) for v in z["rect"])
        x0, x1 = sorted((clamp(x0, -hw, hw), clamp(x1, -hw, hw)))
        z0, z1 = sorted((clamp(z0, -hd, hd), clamp(z1, -hd, hd)))
        if x1 - x0 < 4 or z1 - z0 < 4:
            notes.append(f"zone {z.get('id')} too small dropped")
            continue
        for prev in spec["zones"]:
            px0, pz0, px1, pz1 = prev["rect"]
            ox, oz = min(x1, px1) - max(x0, px0), min(z1, pz1) - max(z0, pz0)
            inside = (px0 <= x0 and x1 <= px1 and pz0 <= z0 and z1 <= pz1) or (x0 <= px0 and px1 <= x1 and z0 <= pz0 and pz1 <= z1)
            if ox > 0.5 and oz > 0.5 and not inside:   # nested zones (a house in a garden) are fine
                # cut along the axis with the smaller overlap, on the side that keeps the most area
                if ox <= oz:
                    x0, x1 = (px1, x1) if (x1 - px1) >= (px0 - x0) else (x0, px0)
                else:
                    z0, z1 = (pz1, z1) if (z1 - pz1) >= (pz0 - z0) else (z0, pz0)
        if x1 - x0 < 4 or z1 - z0 < 4:
            notes.append(f"zone {z.get('id')} overlapped another zone and was dropped")
            continue
        zid = str(z.get("id") or f"zone{len(spec['zones'])}")[:24]
        zone_ids.add(zid)
        spec["zones"].append({"id": zid, "rect": [round(x0, 1), round(z0, 1), round(x1, 1), round(z1, 1)],
                              "floor": z.get("floor") if z.get("floor") in MATERIALS else "",
                              "purpose": str(z.get("purpose") or "")[:80]})
    for r in (raw.get("rooms") or [])[:8]:
        if not isinstance(r, dict) or r.get("zone") not in zone_ids:
            notes.append(f"room for unknown zone {r.get('zone') if isinstance(r, dict) else r!r} dropped")
            continue
        openings = []
        for o in (r.get("openings") or [])[:12]:
            if not isinstance(o, dict) or o.get("side") not in SIDES:
                continue
            openings.append({"side": o["side"], "at": _num(o.get("at"), 0.5, 0.05, 0.95),
                             "w": _num(o.get("w"), 6, 3, 40), "h": _num(o.get("h"), 9, 3, 60),
                             "kind": o.get("kind") if o.get("kind") in OPENINGS else "door"})
        zone_row = next(z for z in spec["zones"] if z["id"] == r["zone"])
        if not zone_row["floor"]:   # an indoor room never shows the outdoor ground
            zone_row["floor"] = "plank" if r.get("wall") in ("wood", "plank", "plaster") else "stone"
        spec["rooms"].append({"zone": r["zone"], "h": _num(r.get("h"), 14, 8, 80),
                              "wall": r.get("wall") if r.get("wall") in MATERIALS else "plaster",
                              "roof": r.get("roof") if r.get("roof") in ROOFS else "flat",
                              "windows": r.get("windows") if r.get("windows") in WINDOWS else "plain",
                              "openings": openings})
    for p in (raw.get("props") or [])[:MAX_PROPS]:
        if isinstance(p, list):
            p = prop_from_list(p)
        if not isinstance(p, dict) or p.get("kit") not in kits.KITS:
            notes.append(f"unknown kit {p.get('kit') if isinstance(p, dict) else p!r} dropped")
            continue
        at = _xz(p.get("at"), hw, hd)
        if at is None:
            notes.append(f"{p.get('kit')} without a valid 'at' dropped")
            continue
        item = {"kit": p["kit"], "at": at, "rot": _num(p.get("rot"), 0, -360, 360),
                "params": kits.clean_params(p["kit"], p.get("params")), "why": str(p.get("why") or "")[:80]}
        if p.get("y") is not None:
            item["y"] = _num(p.get("y"), 0, -20, 80)
        rep = p.get("repeat")
        if isinstance(rep, dict):
            n = int(_num(rep.get("n"), 1, 1, 24))
            step_raw = rep.get("step")
            step = step_raw if isinstance(step_raw, list) and len(step_raw) == 2 else [0, 0]
            if n > 1:
                item["repeat"] = {"n": n, "step": [_num(step[0], 0, -60, 60), _num(step[1], 0, -60, 60)]}
        spec["props"].append(item)
    for f in (raw.get("focal") or [])[:6]:
        at = _xz(f.get("at") if isinstance(f, dict) else None, hw, hd)
        if at:
            spec["focal"].append({"id": str(f.get("id") or "focal")[:24], "at": at, "why": str(f.get("why") or "")[:80]})
    for pth in (raw.get("paths") or [])[:12]:
        if not isinstance(pth, dict):
            continue
        a, b = _xz(pth.get("from"), hw, hd), _xz(pth.get("to"), hw, hd)
        if a and b:
            spec["paths"].append({"from": a, "to": b, "w": _num(pth.get("w"), 6, 2, 30),
                                  "mat": pth.get("mat") if pth.get("mat") in MATERIALS else "cobble"})
    sp = _xz(raw.get("spawn"), hw, hd)
    if sp:
        spec["spawn"] = sp
    if not spec["focal"]:
        notes.append("no focal point: the scene centre is used")
        spec["focal"].append({"id": "centre", "at": [0, 0], "why": "default"})
    return spec, notes


# --------------------------------------------------------------------------- compile

def zone_at(spec: dict, x: float, z: float) -> dict | None:
    """The innermost zone at (x, z)."""
    best = None
    for zone in spec["zones"]:
        x0, z0, x1, z1 = zone["rect"]
        if x0 <= x <= x1 and z0 <= z <= z1 and (best is None or (x1 - x0) * (z1 - z0) < _area(best)):
            best = zone
    return best


def _area(zone: dict) -> float:
    x0, z0, x1, z1 = zone["rect"]
    return (x1 - x0) * (z1 - z0)


def floor_y(spec: dict, x: float, z: float) -> float:
    zone = zone_at(spec, x, z)
    return FLOOR if zone and zone.get("floor") else 0.0


def _room_of(spec: dict, zone_id: str) -> dict | None:
    return next((r for r in spec["rooms"] if r["zone"] == zone_id), None)


def _wall_pieces(ctx: Ctx, length: float, h: float, openings: list[dict], t: float, mat: str, windows: str,
                 base: float) -> list[dict]:
    """One wall along local X from -length/2 to length/2, outer face at +Z/2 - in local space centred on 0."""
    out = []
    holes = []
    for o in sorted(openings, key=lambda o: o["at"]):
        cx = -length / 2 + o["at"] * length
        w = min(o["w"], length - 2)
        if o["kind"] == "window":
            sill, top = min(3.5, h * 0.25), min(h - 2, 3.5 + o["h"])
        elif o["kind"] == "open":
            sill, top = 0, h
        else:
            sill, top = 0, min(h - 1.5, o["h"])
        if any(abs(cx - hx) < (w + hw) / 2 + 0.5 for hx, hw, *_ in holes):
            continue
        holes.append((cx, w, sill, top, o["kind"]))
    x = -length / 2
    for cx, w, sill, top, kind in sorted(holes):
        left = cx - w / 2
        if left - x > 0.05:
            out.append(part(ctx, "B", (left - x, h, t), ((x + left) / 2, base + h / 2, 0), mat=mat, vary=0.02))
        if sill > 0:
            out.append(part(ctx, "B", (w, sill, t), (cx, base + sill / 2, 0), mat=mat, vary=0.02))
        if top < h:
            out.append(part(ctx, "B", (w, h - top, t), (cx, base + top + (h - top) / 2, 0), mat=mat, vary=0.02))
        trim_c = ctx.palette["trim"]
        if kind in ("door", "window", "arch") and ctx.style != "stud":
            fw = 0.5
            out.append(part(ctx, "B", (w - 0.02, fw, t + 0.3), (cx, base + top - fw / 2, 0), mat="wood", color=trim_c))
            for sx in (-1, 1):
                out.append(part(ctx, "B", (fw, top - sill - fw - 0.02, t + 0.3),
                                (cx + sx * (w / 2 - fw / 2 - 0.01), base + sill + (top - sill - fw) / 2, 0), mat="wood", color=trim_c))
        elif kind in ("door", "window") and ctx.style == "stud":
            out.append(part(ctx, "B", (w + 2, 1, t + 0.4), (cx, base + top + 0.5, 0), mat=mat, color=shade(ctx.color(mat), 0.8)))
        if kind == "arch" and top - sill > w * 0.6:   # rounded head inside the opening
            n = ctx.detail()
            r = w / 2
            for i in range(n):
                a0, a1 = math.pi * i / n, math.pi * (i + 1) / n
                am = (a0 + a1) / 2
                yy = top - r + math.sin(am) * r
                fill_h = top - yy
                if fill_h > 0.2:
                    out.append(part(ctx, "B", (w / n * 1.02, fill_h, t), (cx - r + (i + 0.5) * w / n, base + yy + fill_h / 2, 0),
                                    mat=mat, vary=0.02))
        if kind == "window":
            if windows == "stained":
                pal = [ctx.palette["accent"], (40, 70, 150), (190, 140, 50), (60, 120, 80), (120, 40, 90), ctx.palette["primary"]]
                rows, colsn = max(3, int((top - sill) / 2.2)), max(2, int(w / 1.6))
                ph, pw = (top - sill) / rows, w / colsn
                for ri in range(rows):
                    for ci in range(colsn):
                        sym = min(ci, colsn - 1 - ci)       # mirror-symmetric pattern like real tracery
                        colr = pal[(sym * 2 + ri * 3 + (ri // 2)) % len(pal)]
                        out.append(part(ctx, "B", (pw, ph, 0.2), (cx - w / 2 + (ci + 0.5) * pw, base + sill + (ri + 0.5) * ph, 0),
                                        mat="glass", color=colr, t=0.35, collide=True, cast=False))
                lead = (28, 26, 24)
                for ci in range(1, colsn):
                    out.append(part(ctx, "B", (0.12, top - sill, 0.3), (cx - w / 2 + ci * pw, base + sill + (top - sill) / 2, 0),
                                    mat="metal", color=lead, collide=False))
                for ri in range(1, rows):
                    out.append(part(ctx, "B", (w, 0.12, 0.3), (cx, base + sill + ri * ph, 0), mat="metal", color=lead, collide=False))
            else:
                broken = ctx.state == "abandoned" and ctx.rng.random() < 0.5
                if not broken:
                    out.append(part(ctx, "B", (w, top - sill, 0.2), (cx, base + sill + (top - sill) / 2, 0), mat="glass", t=0.6))
                if ctx.style != "stud":
                    out.append(part(ctx, "B", (0.3, top - sill, t * 0.6), (cx, base + sill + (top - sill) / 2, 0), mat="wood", color=trim_c))
                    out.append(part(ctx, "B", (w, 0.3, t * 0.6), (cx, base + sill + (top - sill) / 2, 0), mat="wood", color=trim_c))
        x = cx + w / 2
    if length / 2 - x > 0.05:
        out.append(part(ctx, "B", (length / 2 - x, h, t), ((x + length / 2) / 2, base + h / 2, 0), mat=mat, vary=0.02))
    if ctx.state == "abandoned" and ctx.style != "stud":   # broken wall top: a few blocks missing along the top edge
        pass
    return out


def _auto_windows(room: dict, side: str, length: float) -> list[dict]:
    if room["windows"] == "none":
        return []
    have = [o for o in room["openings"] if o["side"] == side]
    out = []
    count = int(length // 14)
    for i in range(count):
        at = (i + 0.5) / count
        if any(abs(at - o["at"]) * length < (o["w"] + 6) / 2 + 2 for o in have):
            continue
        out.append({"side": side, "at": at, "w": 4 if room["windows"] != "stained" else 5,
                    "h": min(room["h"] * 0.55, 14), "kind": "arch" if room["windows"] == "arched" and False else "window"})
    return out


def room_parts(ctx: Ctx, spec: dict, room: dict) -> list[dict]:
    zone = next(z for z in spec["zones"] if z["id"] == room["zone"])
    x0, z0, x1, z1 = zone["rect"]
    t = WALL_T[ctx.style]
    h = room["h"]
    out = []
    base = 0.0
    sides = {"N": (x1 - x0, ((x0 + x1) / 2, z0 + t / 2), 0), "S": (x1 - x0, ((x0 + x1) / 2, z1 - t / 2), 180),
             "W": (z1 - z0 - 2 * t, (x0 + t / 2, (z0 + z1) / 2), 90), "E": (z1 - z0 - 2 * t, (x1 - t / 2, (z0 + z1) / 2), -90)}
    from .geom import transform
    for side, (length, (cx, cz), yaw) in sides.items():
        openings = [o for o in room["openings"] if o["side"] == side] + _auto_windows(room, side, length)
        if side in ("W", "E"):   # local +X of a yaw-90 wall runs towards -Z; flip 'at' so at=0 is the N end
            openings = [dict(o, at=1 - o["at"]) for o in openings] if side == "W" else openings
        if side == "S":
            openings = [dict(o, at=1 - o["at"]) for o in openings]
        pieces = _wall_pieces(ctx, length, h, openings, t, room["wall"], room["windows"], base)
        out += transform(pieces, (cx, 0, cz), yaw)
        # trim lines: baseboard + crown inside (mid/high), a contrasting plinth course outside (stud/lowpoly)
        trim = []
        if ctx.style in ("midpoly", "highpoly"):
            trim.append(part(ctx, "B", (length - 2 * t, 0.7, 0.25), (0, FLOOR + 0.35, t / 2 + 0.12), mat="wood",
                             color=ctx.palette["trim"]))
            trim.append(part(ctx, "B", (length - 2 * t, 0.6, 0.4), (0, h - 0.3, t / 2 + 0.2), mat="wood", color=ctx.palette["trim"]))
        else:
            trim.append(part(ctx, "B", (length + 0.4, 1.0, t + 0.4), (0, 0.5, 0), mat=room["wall"],
                             color=shade(ctx.color(room["wall"]), 0.75)))
        out += transform(trim, (cx, 0, cz), yaw)
    # corner piers (stop the wall ends from looking like cardboard)
    if ctx.style != "lowpoly":
        for cx in (x0 + t / 2, x1 - t / 2):
            for cz in (z0 + t / 2, z1 - t / 2):
                out.append(part(ctx, "B", (t * 1.8, h + 0.6, t * 1.8), (cx, h / 2 + 0.3, cz), mat=room["wall"],
                                color=shade(ctx.color(room["wall"]), 0.85)))
    for rp in roof_parts(ctx, room, (x0, z0, x1, z1), h, t):
        rp["roof"] = True
        out.append(rp)
    return out


def roof_parts(ctx: Ctx, room: dict, rect, h: float, t: float) -> list[dict]:
    x0, z0, x1, z1 = rect
    w, d = x1 - x0, z1 - z0
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    roof = room["roof"]
    out = []
    if roof == "none":
        return out
    ceiling_mat = "plaster" if room["wall"] not in ("stone", "brick", "concrete") else room["wall"]
    if roof in ("flat", "broken"):
        n = max(2, int(d / 8))
        holes = set(ctx.rng.sample(range(n), max(1, n // 3))) if roof == "broken" else set()
        for i in range(n):
            if i in holes:
                continue
            seg = d / n
            out.append(part(ctx, "B", (w, 1, seg), (cx, h + 0.5, z0 + seg * (i + 0.5)), mat=ceiling_mat, vary=0.02))
        if ctx.style in ("midpoly", "highpoly") and roof == "flat":   # ceiling beams
            for i in range(1, int(w / 8)):
                out.append(part(ctx, "B", (0.8, 0.9, d - 2 * t), (x0 + i * w / int(w / 8), h - 0.45, cz), mat="wood",
                                color=ctx.palette["trim"]))
        return out
    if roof == "gable":
        along_x = w >= d
        span, length = (d, w) if along_x else (w, d)
        rise = span * 0.35
        slope = math.hypot(span / 2, rise)
        ang = math.degrees(math.atan2(rise, span / 2))
        roof_mat = "roof" if ctx.style in ("midpoly", "highpoly") else "brick"
        roof_col = ctx.palette["secondary"]
        for s in (-1, 1):
            if along_x:
                out.append(part(ctx, "B", (length + 2, 0.8, slope + 1), (cx, h + rise / 2, cz + s * span / 4),
                                rot=(s * ang, 0, 0), mat=roof_mat, color=roof_col))
            else:
                out.append(part(ctx, "B", (slope + 1, 0.8, length + 2), (cx + s * span / 4, h + rise / 2, cz),
                                rot=(0, 0, -s * ang), mat=roof_mat, color=roof_col))
        # gable end triangles: two wedges per end
        for e in (-1, 1):
            for s in (-1, 1):
                if along_x:
                    out.append(part(ctx, "W", (t, rise, span / 2), (cx + e * (length / 2 - t / 2), h + rise / 2, cz + s * span / 4),
                                    rot=(0, 0 if s < 0 else 180, 0), mat=room["wall"]))
                else:
                    out.append(part(ctx, "W", (t, rise, span / 2), (cx + s * span / 4, h + rise / 2, cz + e * (length / 2 - t / 2)),
                                    rot=(0, 90 if s < 0 else -90, 0), mat=room["wall"]))
        out.append(part(ctx, "B", (w - 2 * t, 0.5, d - 2 * t), (cx, h + 0.25, cz), mat=ceiling_mat))   # ceiling
        return out
    if roof == "vault":   # elliptical barrel vault along the long axis, ribs every ~10 studs
        along_x = w >= d
        span, length = (d, w) if along_x else (w, d)
        n = ctx.detail() + 2
        ribs = max(2, int(length / 10))

        def chords(r, k):
            pts = [(math.cos(math.pi * i / k) * r, math.sin(math.pi * i / k) * r * 0.6) for i in range(k + 1)]
            for (a, b), (c, e) in zip(pts, pts[1:]):
                yield (a + c) / 2, (b + e) / 2, math.hypot(c - a, e - b), c - a, e - b
        for off, y, seg, du, dy in chords(span / 2, n):
            if along_x:
                out.append(part(ctx, "B", (length, 0.8, seg * 1.04), (cx, h + y, cz + off),
                                rot=(math.degrees(math.atan2(-dy, du)), 0, 0), mat=room["wall"], vary=0.02))
            else:
                out.append(part(ctx, "B", (seg * 1.04, 0.8, length), (cx + off, h + y, cz),
                                rot=(0, 0, math.degrees(math.atan2(dy, du))), mat=room["wall"], vary=0.02))
        rib_c = shade(ctx.color(room["wall"]), 0.8)
        for k in range(ribs + 1):
            pos = -length / 2 + t + (length - 2 * t) * k / ribs
            for off, y, seg, du, dy in chords(span / 2 - 0.7, n):
                if along_x:
                    out.append(part(ctx, "B", (0.9, 0.9, seg * 1.06), (cx + pos, h + y - 0.2, cz + off),
                                    rot=(math.degrees(math.atan2(-dy, du)), 0, 0), mat="stone", color=rib_c))
                else:
                    out.append(part(ctx, "B", (seg * 1.06, 0.9, 0.9), (cx + off, h + y - 0.2, cz + pos),
                                    rot=(0, 0, math.degrees(math.atan2(dy, du))), mat="stone", color=rib_c))
        return out
    return out


def path_parts(ctx: Ctx, spec: dict, pth: dict) -> list[dict]:
    (ax, az), (bx, bz) = pth["from"], pth["to"]
    length = math.hypot(bx - ax, bz - az)
    if length < 1:
        return []
    yaw = math.degrees(math.atan2(bx - ax, bz - az))
    y = max(floor_y(spec, ax, az), floor_y(spec, bx, bz))
    out = [part(ctx, "B", (pth["w"], 0.12, length), ((ax + bx) / 2, y + 0.06, (az + bz) / 2), rot=(0, yaw, 0), mat=pth["mat"],
                collide=False, cast=False)]
    if ctx.style in ("midpoly", "highpoly", "stud"):   # kerb stones along both edges
        a = math.radians(yaw)
        nx, nz = math.cos(a), -math.sin(a)
        for s in (-1, 1):
            out.append(part(ctx, "B", (0.6, 0.3, length), ((ax + bx) / 2 + s * nx * (pth["w"] / 2 + 0.3), y + 0.15,
                            (az + bz) / 2 + s * nz * (pth["w"] / 2 + 0.3)), rot=(0, yaw, 0), mat="stone",
                            color=shade(ctx.color(pth["mat"]), 0.8), cast=False))
    return out


WALL_KITS = {"shelf", "picture", "sconce", "vines", "cabinet", "fireplace", "cobweb", "bookcase_tall", "aquarium_tank",
             "vending_machine", "paper_screen", "info_plaque", "planks", "trash"}
HANGING_KITS = {"chandelier", "pendant_lamp"}


def _room_rect(spec: dict, x: float, z: float) -> tuple[Any, Any]:
    for room in spec["rooms"]:
        zone = next(zz for zz in spec["zones"] if zz["id"] == room["zone"])
        x0, z0, x1, z1 = zone["rect"]
        if x0 < x < x1 and z0 < z < z1:
            return room, zone["rect"]
    return None, None


def snap_to_wall(spec: dict, x: float, z: float, reach: float = 8.0):
    """Wall props: (inner face coordinate, inward normal (nx, nz), yaw that turns the back (+Z) to the wall)."""
    room, rect = _room_rect(spec, x, z)
    if room is None:
        return None
    t = WALL_T[spec["style"]]
    x0, z0, x1, z1 = rect
    options = [(x - x0, (x0 + t, (1, 0), -90)), (x1 - x, (x1 - t, (-1, 0), 90)),
               (z - z0, (z0 + t, (0, 1), 180)), (z1 - z, (z1 - t, (0, -1), 0))]
    dist, target = min(options, key=lambda o: o[0])
    return target if dist <= reach else None


def ceiling_y(spec: dict, x: float, z: float) -> float | None:
    room, rect = _room_rect(spec, x, z)
    if room is None or room["roof"] in ("none",):
        return None
    if room["roof"] == "vault":
        x0, z0, x1, z1 = rect
        along_x = (x1 - x0) >= (z1 - z0)
        r = ((z1 - z0) if along_x else (x1 - x0)) / 2
        off = (z - (z0 + z1) / 2) if along_x else (x - (x0 + x1) / 2)
        return round(room["h"] + 0.6 * r * math.sqrt(max(0.0, 1 - (off / r) ** 2)) - 0.6, 2)
    if room["roof"] == "gable":
        return room["h"]
    return room["h"]


def compile_spec(spec: dict) -> dict:
    """Spec (normalised) -> {"parts": [...], "lighting": {...}, "cameras": [...], "notes": [...]}."""
    ctx = Ctx(spec["style"], spec["palette"], seed=spec["seed"], state=spec["state"])
    w, d = spec["size"]
    parts: list[dict] = []
    notes: list[str] = []
    # ground: the playable area plus a wide skirt so outdoor shots have no void at the edges
    g = part(ctx, "B", (w, 2, d), (0, -1, 0), mat=spec["ground"], vary=0.0, name="Ground")
    g["kit"] = "ground"
    parts.append(g)
    skirt = part(ctx, "B", (w + 900, 2, d + 900), (0, -1.3, 0), mat=spec["ground"], color=shade(ctx.color(spec["ground"]), 0.9),
                 name="Skirt", cast=False)
    skirt["kit"] = "ground"
    parts.append(skirt)
    parts += ground_patches(ctx, spec)
    for zone in spec["zones"]:
        if zone["floor"]:
            x0, z0, x1, z1 = zone["rect"]
            lift = 0.02 * sum(1 for other in spec["zones"] if other is not zone and other["floor"] and _area(other) > _area(zone))
            f = part(ctx, "B", (x1 - x0 - 0.1, 0.4, z1 - z0 - 0.1), ((x0 + x1) / 2, FLOOR - 0.2 + lift, (z0 + z1) / 2), mat=zone["floor"],
                     name=f"Floor_{zone['id']}", cast=False)
            f["kit"] = "floor"
            parts.append(f)
    for room in spec["rooms"]:
        for p in room_parts(ctx, spec, room):
            p["kit"] = "room"
            p["zone"] = room["zone"]
            parts.append(p)
    for pth in spec["paths"]:
        for p in path_parts(ctx, spec, pth):
            p["kit"] = "path"
            parts.append(p)
    from .geom import transform
    for index, prop in enumerate(spec["props"]):
        rep = prop.get("repeat") or {"n": 1, "step": [0, 0]}
        for k in range(rep["n"]):
            x = prop["at"][0] + rep["step"][0] * k
            z = prop["at"][1] + rep["step"][1] * k
            if abs(x) > w / 2 or abs(z) > d / 2:
                notes.append(f"{prop['kit']} copy {k} outside the map dropped")
                continue
            y = prop.get("y", floor_y(spec, x, z))
            params, yaw = dict(prop["params"]), prop["rot"]
            if prop["kit"] == "water" and "y" not in prop and floor_y(spec, x, z) == 0.0:
                params["y"] = max(params.get("y", -0.5), 0.15)   # a part ground would hide the default -0.5
            snapped = snap_to_wall(spec, x, z) if prop["kit"] in WALL_KITS else None
            if prop["kit"] in HANGING_KITS and "y" in params:
                top = ceiling_y(spec, x, z)
                if top is not None:
                    params["y"] = top
                    if prop["kit"] == "chandelier":
                        params["drop"] = max(params.get("drop", 5), top - 14)
            built = kits.build_kit(ctx, prop["kit"], params)
            if snapped:
                back = max(aabb(p)[1][2] for p in built)
                face, normal, yaw = snapped
                # local +Z (the back) points along -normal after the turn; put the back on the face
                x, z = (face + normal[0] * (back + 0.02), z) if normal[0] else (x, face + normal[1] * (back + 0.02))
            for p in transform(built, (x, y, z), yaw):
                p["prop"] = index
                p["copy"] = k
                parts.append(p)
            if len(parts) > MAX_PARTS:
                notes.append("part budget reached: later props dropped")
                break
        if len(parts) > MAX_PARTS:
            break
    parts += fill_lights(ctx, spec)
    if spec.get("preset"):
        practicals(spec, parts)
    if spec.get("budget"):   # performance pass: shadows on the 20 brightest lights only, at most 44 lights
        lit = sorted((p for p in parts if p.get("light")), key=lambda p: -p["light"]["b"] * p["light"]["r"])
        for k, p in enumerate(lit):
            if k >= 20:
                p["light"]["sh"] = False
            if k >= 44:
                p.pop("light")
    if spec["sign_text"]:
        for p in parts:
            if p.get("text"):
                p["text"] = spec["sign_text"]
    return {"parts": parts, "lighting": copy.deepcopy(LIGHTING[spec["mood"]]), "preset": spec.get("preset"),
            "cameras": clear_cameras(cameras(spec), parts),
            "candidates": camera_candidates(spec, parts), "notes": notes}


WARM_MOODS = ("cozy_interior", "warm_evening", "golden_hour", "sunny_day")


def fill_lights(ctx: Ctx, spec: dict) -> list[dict]:
    """Soft invisible fill lights in every roofed room (shadowless), so interiors read; tinted by mood."""
    col = (255, 214, 170) if spec["mood"] in WARM_MOODS else (170, 190, 220) if spec["mood"] != "neon_night" else (200, 160, 255)
    out = []
    for room in spec["rooms"]:
        if room["roof"] == "none":
            continue
        zone = next(z for z in spec["zones"] if z["id"] == room["zone"])
        x0, z0, x1, z1 = zone["rect"]
        nx, nz = max(1, round((x1 - x0) / 22)), max(1, round((z1 - z0) / 22))
        for i in range(nx):
            for k in range(nz):
                p = part(ctx, "B", (0.5, 0.5, 0.5), (x0 + (i + 0.5) * (x1 - x0) / nx, room["h"] * 0.6, z0 + (k + 0.5) * (z1 - z0) / nz),
                         mat="plastic", color=(255, 255, 255), t=1, collide=False, cast=False,
                         light=light("point", col, 1.25, min(60, 30 + room["h"] * 0.7), shadows=False))
                p["kit"] = "fill_light"
                out.append(p)
    return out


def _seg_hits(a, b, box) -> float | None:
    """Fraction t in [0, 1] where segment a->b enters box, or None."""
    t0, t1 = 0.0, 1.0
    for i in range(3):
        d = b[i] - a[i]
        if abs(d) < 1e-9:
            if a[i] < box[0][i] or a[i] > box[1][i]:
                return None
            continue
        u0, u1 = (box[0][i] - a[i]) / d, (box[1][i] - a[i]) / d
        if u0 > u1:
            u0, u1 = u1, u0
        t0, t1 = max(t0, u0), min(t1, u1)
        if t0 > t1:
            return None
    return t0


def clear_cameras(cams: list[dict], parts: list[dict]) -> list[dict]:
    """Move cameras out of solid parts and away from occluders in front of the lens."""
    boxes = [aabb(p) for p in parts if p.get("t", 0) < 0.6 and p.get("kit") not in ("ground", "fill_light")]

    def inside(pt):
        return any(all(b[0][i] - 0.3 <= pt[i] <= b[1][i] + 0.3 for i in range(3)) for b in boxes)

    def blockers(pos, look):
        n = 0
        for b in boxes:
            if all(b[0][i] <= look[i] <= b[1][i] for i in range(3)):
                continue
            t = _seg_hits(pos, look, b)
            if t is not None and t < 0.6:
                n += 1 + (t < 0.15) * 3
        return n
    out = []
    for cam in cams:
        pos, look = list(cam["position"]), cam["look_at"]
        best = (blockers(pos, look) + (50 if inside(pos) else 0), pos)
        if best[0]:
            for dy in (0, 2, 4, -1.5):
                for side in (0, 3, -3, 6, -6):
                    for pull in (0, 0.15, 0.3):
                        cand = [pos[0] + (look[0] - pos[0]) * pull + side * (1 if cam["id"] != "overview" else 0),
                                pos[1] + dy, pos[2] + (look[2] - pos[2]) * pull + side * 0.5]
                        score = blockers(cand, look) + (50 if inside(cand) else 0)
                        if score < best[0]:
                            best = (score, cand)
        out.append(dict(cam, position=[round(v, 2) for v in best[1]], blockers=best[0]))
    return out


# --------------------------------------------------------------------------- cameras

def _inside(spec: dict, x: float, z: float) -> dict | None:
    for room in spec["rooms"]:
        zone = next(zz for zz in spec["zones"] if zz["id"] == room["zone"])
        x0, z0, x1, z1 = zone["rect"]
        if x0 < x < x1 and z0 < z < z1:
            return {"rect": zone["rect"], "h": room["h"]}
    return None


def cameras(spec: dict) -> list[dict]:
    """Four shots: hero (eye level from spawn to the main focal point), wide corner, reverse/second focal, overview."""
    w, d = spec["size"]
    sx, sz = spec["spawn"]
    focal = spec["focal"][0]["at"]
    fx, fz = focal
    out = []
    room = _inside(spec, fx, fz)

    def clampin(x, z, margin=2.5):
        r = _inside(spec, x, z)
        if r:
            x0, z0, x1, z1 = r["rect"]
            return clamp(x, x0 + margin, x1 - margin), clamp(z, z0 + margin, z1 - margin)
        return clamp(x, -w / 2 + 1, w / 2 - 1), clamp(z, -d / 2 + 1, d / 2 - 1)

    # hero: from a bit behind spawn towards focal, at eye height
    dx, dz = fx - sx, fz - sz
    dist = max(1.0, math.hypot(dx, dz))
    hx, hz = clampin(sx - dx / dist * 4, sz - dz / dist * 4)
    base = floor_y(spec, hx, hz)
    out.append({"id": "hero", "position": [hx, base + 6.0, hz], "look_at": [fx, floor_y(spec, fx, fz) + 4.5, fz]})
    # wide: from the corner farthest from the focal, high
    if room:
        x0, z0, x1, z1 = room["rect"]
        corners = [(x0, z0), (x0, z1), (x1, z0), (x1, z1)]
        cx, cz = max(corners, key=lambda c: math.hypot(c[0] - fx, c[1] - fz))
        cx, cz = clampin(cx, cz, 3)
        out.append({"id": "wide", "position": [cx, min(room["h"] * 0.75, room["h"] - 2), cz],
                    "look_at": [(x0 + x1) / 2, room["h"] * 0.25, (z0 + z1) / 2]})
    else:
        out.append({"id": "wide", "position": [-w * 0.45, max(w, d) * 0.28, d * 0.45], "look_at": [fx * 0.5, 2, fz * 0.5]})
    # reverse: from beside the focal back towards spawn, or a second focal point
    if len(spec["focal"]) > 1:
        f2 = spec["focal"][1]["at"]
        px, pz = clampin(f2[0] + (f2[0] - fx) * 0.15 + 6, f2[1] + 6)
        out.append({"id": "detail", "position": [px, floor_y(spec, px, pz) + 5.5, pz], "look_at": [f2[0], floor_y(spec, *f2) + 3, f2[1]]})
    else:
        px, pz = clampin(fx + 5, fz + 3)
        out.append({"id": "detail", "position": [px, floor_y(spec, px, pz) + 6, pz], "look_at": [sx, 4, sz]})
    # overview: 3/4 from outside, high
    span = max(w, d)
    if spec["rooms"]:   # roofs are hidden for this shot: look down into the rooms (cut-away)
        out.append({"id": "overview", "position": [w * 0.3, span * 0.85, d * 0.62], "look_at": [0, 0, 0]})
    else:
        out.append({"id": "overview", "position": [w * 0.55, span * 0.55, d * 0.75], "look_at": [0, 0, 0]})
    for c in out:
        c["position"] = [round(v, 2) for v in c["position"]]
        c["look_at"] = [round(v, 2) for v in c["look_at"]]
    return out


# --------------------------------------------------------------------------- ground variation

def zone_room(spec: dict, x: float, z: float) -> bool:
    return _room_rect(spec, x, z)[0] is not None


def ground_patches(ctx: Ctx, spec: dict) -> list[dict]:
    """Stud/low-poly part ground: large low-contrast patches of the ground colour (lighter/darker) so the ground
    does not read as one flat baseplate; worn paths get a dirt margin."""
    w, d = spec["size"]
    rng = ctx.rng
    out = []
    col = ctx.color(spec["ground"])
    for i in range(int(min(18, max(5, w * d / 1400)))):
        pw, pd = rng.uniform(10, 26), rng.uniform(8, 22)
        x, z = rng.uniform(-w / 2 + pw / 2, w / 2 - pw / 2), rng.uniform(-d / 2 + pd / 2, d / 2 - pd / 2)
        if zone_room(spec, x, z):
            continue
        p = part(ctx, "B", (pw, 0.1 + 0.02 * i, pd), (x, 0.03 + 0.01 * i, z), rot=(0, rng.choice((0, 15, 30, 45, 60)), 0),
                 mat=spec["ground"], color=shade(col, rng.choice((0.86, 0.92, 1.08, 1.12))), collide=False, cast=False,
                 studs=ctx.style == "stud")
        p["kit"] = "ground"
        out.append(p)
    if spec["ground"] in ("grass", "foliage"):
        for pth in spec["paths"]:
            if pth["mat"] in ("plank", "wood"):
                continue
            for q in path_parts(ctx, spec, dict(pth, w=pth["w"] + 3, mat="ground"))[:1]:
                q["p"][1] -= 0.04
                q["c"] = list(ctx.tone(shade(ctx.color("ground"), 1.1)))
                q["kit"] = "ground"
                out.append(q)
    return out


# --------------------------------------------------------------------------- practical lights from a preset

PRACTICAL_ROLE = {"pendant_lamp": "pendant", "chandelier": "pendant", "sconce": "sconce", "floor_lamp": "lamp",
                  "candles": "lamp", "reading_table": "lamp", "lamp_post": "street", "string_lights": "street",
                  "lantern": "lantern", "stone_lantern": "lantern", "campfire": "lantern", "led_strip": "neon",
                  "sign": "neon", "vending_machine": "neon", "ticket_booth": "neon", "lighthouse": "street"}


def practicals(spec: dict, parts: list[dict], max_windows: int = 12) -> None:
    """Retint the kit lights with the preset's practical recipes (kelvin, brightness, range) and, at night, light
    the window glass of rooms (warm windows against a cool night)."""
    from .. import roblox_lighting_presets as presets
    preset = presets.resolve(spec["preset"])
    recipes = {role: presets._clean_practical(role, (preset.get("practicals") or {}).get(role)) for role in presets.ROLES}
    for p in parts:
        if not p.get("light") or p.get("kit") == "fill_light" or p.get("prop") is None:
            continue
        role = PRACTICAL_ROLE.get(spec["props"][p["prop"]]["kit"])
        r = recipes.get(role) if role else None
        if not r:
            continue
        p["light"]["c"] = list(r["color"])
        p["light"]["b"] = round(max(p["light"]["b"] * 0.5, r["brightness"]), 2)
        p["light"]["r"] = round(clamp(max(p["light"]["r"], r["range"]), 2, 60), 1)
        if p.get("m") == "Neon":
            p["c"] = list(r["color"])
    win = recipes.get("window")
    if win and spec["mood"] in ("cold_night", "neon_night", "foggy_horror", "warm_evening"):
        n = 0
        for p in parts:
            if n >= max_windows:
                break
            if p.get("kit") == "room" and p.get("sem") == "glass" and not p.get("light") and p["z"][0] * p["z"][1] > 6:
                p["light"] = light("surface", win["color"], win["brightness"] * 1.6, win["range"], angle=win.get("angle", 80),
                                   face="Back", shadows=False)
                n += 1


# --------------------------------------------------------------------------- camera candidates (picked in Studio)

def _inst_box(parts: list[dict], index: int):
    lo, hi = [1e9] * 3, [-1e9] * 3
    for p in parts:
        if p.get("prop") == index and p.get("copy", 0) == 0:
            a, b = aabb(p)
            lo = [min(lo[i], a[i]) for i in range(3)]
            hi = [max(hi[i], b[i]) for i in range(3)]
    return (lo, hi) if lo[0] < 1e8 else None


def hero_prop(spec: dict, parts: list[dict]):
    """The biggest non-structural prop near the main focal point (the detail shot's subject)."""
    fx, fz = spec["focal"][0]["at"]
    best, best_v = None, 0.0
    for i, prop in enumerate(spec["props"]):
        if prop["kit"] in ("water", "rug", "grass_tufts", "papers", "puddle", "cobweb", "cliff"):
            continue
        dist = math.hypot(prop["at"][0] - fx, prop["at"][1] - fz)
        if dist > 26:
            continue
        box = _inst_box(parts, i)
        if not box:
            continue
        lo, hi = box
        vol = max(0.5, hi[0] - lo[0]) * max(0.5, hi[1] - lo[1]) * max(0.5, hi[2] - lo[2])
        score = vol / (1 + dist / 10)
        if score > best_v:
            best, best_v = box, score
    return best


def camera_candidates(spec: dict, parts: list[dict]) -> dict:
    """Several framings per shot; Studio raycasts pick the clearest one (luau.pick_cameras_luau).
    hero = eye level from the spawn side towards the focal point; wide = establishing view; detail = the hero prop
    close up at a 3/4 angle; overview = high 3/4 (roofs hidden)."""
    w, d = spec["size"]
    sx, sz = spec["spawn"]
    fx, fz = spec["focal"][0]["at"]
    fy = floor_y(spec, fx, fz)
    room = _inside(spec, fx, fz)

    def clampin(x, z, margin=2.5):
        r = _inside(spec, x, z)
        if r:
            x0, z0, x1, z1 = r["rect"]
            return clamp(x, x0 + margin, x1 - margin), clamp(z, z0 + margin, z1 - margin)
        return clamp(x, -w / 2 + 1, w / 2 - 1), clamp(z, -d / 2 + 1, d / 2 - 1)

    out: dict[str, list[dict]] = {"hero": [], "wide": [], "detail": [], "overview": []}
    base_ang = math.atan2(sx - fx, sz - fz)
    dist0 = clamp(math.hypot(sx - fx, sz - fz) + 4, 12, 70)
    for dang in (0, 15, -15, 30, -30, 50, -50, 75, -75):
        for k in (1.0, 0.7, 0.45):
            a = base_ang + math.radians(dang)
            x, z = clampin(fx + math.sin(a) * dist0 * k, fz + math.cos(a) * dist0 * k)
            for eye in (5.5, 9.0):
                out["hero"].append({"position": [x, floor_y(spec, x, z) + eye, z], "look_at": [fx, fy + 4.0, fz]})
    if room:
        x0, z0, x1, z1 = room["rect"]
        h = room["h"]
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
        for px, pz in ((x0, z0), (x0, z1), (x1, z0), (x1, z1), (cx, z0), (cx, z1), (x0, cz), (x1, cz)):
            x, z = clampin(px, pz, 3)
            out["wide"].append({"position": [x, min(h * 0.72, h - 2), z], "look_at": [cx, h * 0.22, cz]})
    else:
        span = max(w, d)
        for k in range(8):
            a = base_ang + k * math.pi / 4
            r = span * 0.5
            out["wide"].append({"position": [math.sin(a) * r, span * 0.22 + 6, math.cos(a) * r],
                                "look_at": [fx * 0.5, 2, fz * 0.5]})
    box = hero_prop(spec, parts)
    if box:
        lo, hi = box
        c = [(lo[i] + hi[i]) / 2 for i in range(3)]
        size = max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
        r = clamp(size * 1.5 + 5, 8, 34)
        for k in range(8):
            a = base_ang + math.radians(35) + k * math.pi / 4
            for elev in (0.35, 0.7):
                x, z = clampin(c[0] + math.sin(a) * r, c[2] + math.cos(a) * r)
                out["detail"].append({"position": [x, max(floor_y(spec, x, z) + 3.5, c[1] + r * elev * 0.5), z],
                                      "look_at": [c[0], c[1], c[2]]})
    else:
        for c in cameras(spec):
            if c["id"] == "detail":
                out["detail"].append({"position": c["position"], "look_at": c["look_at"]})
    span = max(w, d)
    for sxn, szn in ((0.3, 0.62), (-0.3, 0.62), (0.3, -0.62), (-0.3, -0.62)):
        h = span * (0.85 if spec["rooms"] else 0.55)
        out["overview"].append({"position": [w * sxn * (1 if spec["rooms"] else 1.8), h, d * szn * (1 if spec["rooms"] else 1.2)],
                                "look_at": [0, 0, 0]})
    for shots in out.values():
        for c in shots:
            c["position"] = [round(v, 2) for v in c["position"]]
            c["look_at"] = [round(v, 2) for v in c["look_at"]]
    return out
