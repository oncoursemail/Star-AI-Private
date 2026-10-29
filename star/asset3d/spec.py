"""Asset spec for STAR's 3D prop pipeline: validation, mirror expansion, style presets, budgets.

A spec is plain JSON written by STAR's model and built by trusted code (build_bpy.py inside Blender). Units are
metres; X = length (front is +X), Y = width, Z = up. The model never sends Blender code.
"""
from __future__ import annotations

import copy
import math
import re

CATEGORIES = ("weapon", "vehicle", "furniture", "prop", "accessory")
STYLES = ("pbr", "stylized", "lowpoly", "roblox")
PART_TYPES = ("box", "cylinder", "cone", "sphere", "torus", "profile", "lathe", "tube")
MATERIALS = ("painted_metal", "bare_metal", "gunmetal", "anodized", "chrome", "gold", "brass", "polymer", "plastic",
             "rubber", "wood", "dark_wood", "leather", "fabric", "glass", "emissive", "stone", "ceramic")
CUT_SHAPES = ("box", "cylinder")
MAX_PARTS = 80
MAX_CUTS = 12
MAX_POINTS = 48

# Real-world size ranges (longest side, metres) per category: a sanity check, not a template.
SIZE_RANGE = {"weapon": (0.12, 2.2), "vehicle": (1.2, 9.0), "furniture": (0.3, 3.0), "prop": (0.1, 2.5),
              "accessory": (0.08, 1.2)}
# Triangle budget for LOD0 (the whole asset; Roblox also caps every mesh at 20k).
TRI_BUDGET = {"pbr": {"weapon": 16000, "vehicle": 30000, "furniture": 12000, "prop": 8000, "accessory": 10000},
              "stylized": {"weapon": 8000, "vehicle": 16000, "furniture": 6000, "prop": 5000, "accessory": 6000},
              "lowpoly": {"weapon": 1500, "vehicle": 4000, "furniture": 1500, "prop": 1200, "accessory": 1500},
              "roblox": {"weapon": 8000, "vehicle": 19000, "furniture": 8000, "prop": 6000, "accessory": 6000}}
ROBLOX_MESH_TRIS = 20000
ROBLOX_TEX = 1024

# Style presets used by the builder (bevel = default chamfer width in metres before clamping to the part size).
STYLE = {
    "pbr": {"bevel": 0.003, "segments": 3, "circle": 32, "tex": 2048, "shade": "smooth", "bake": True},
    "stylized": {"bevel": 0.010, "segments": 2, "circle": 16, "tex": 1024, "shade": "smooth", "bake": True},
    "lowpoly": {"bevel": 0.0, "segments": 1, "circle": 8, "tex": 512, "shade": "flat", "bake": True},
    "roblox": {"bevel": 0.006, "segments": 2, "circle": 16, "tex": ROBLOX_TEX, "shade": "smooth", "bake": True},
}

_HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")


class SpecError(ValueError):
    pass


def _num(v, name, lo=-50.0, hi=50.0):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise SpecError(f"{name} must be a number from {lo} to {hi}")
    return float(v)


def _vec(v, name, n=3, lo=-50.0, hi=50.0):
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise SpecError(f"{name} must be a list of {n} numbers")
    return [_num(x, f"{name}[{i}]", lo, hi) for i, x in enumerate(v)]


def _segments_cross(a, b, c, d) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def polygon_is_simple(points) -> bool:
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if _segments_cross(a, b, points[j], points[(j + 1) % n]):
                return False
    return True


def polygon_area(points) -> float:
    return 0.5 * sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1]
                     for i in range(len(points)))


def _cut(c, where):
    if not isinstance(c, dict) or c.get("shape") not in CUT_SHAPES:
        raise SpecError(f"{where}.shape must be one of {CUT_SHAPES}")
    out = {"shape": c["shape"], "pos": _vec(c.get("pos", [0, 0, 0]), f"{where}.pos"),
           "rot": _vec(c.get("rot", [0, 0, 0]), f"{where}.rot", lo=-360, hi=360)}
    if c["shape"] == "box":
        out["size"] = _vec(c.get("size"), f"{where}.size", lo=0.0005, hi=20)
    else:
        out["radius"] = _num(c.get("radius"), f"{where}.radius", 0.0005, 10)
        out["depth"] = _num(c.get("depth"), f"{where}.depth", 0.0005, 20)
        out["axis"] = c.get("axis", "z") if c.get("axis", "z") in ("x", "y", "z") else "z"
    count = c.get("count", 1)
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 24:
        raise SpecError(f"{where}.count must be an integer 1-24")
    out["count"] = count
    out["step"] = _vec(c.get("step", [0, 0, 0]), f"{where}.step")
    return out


def validate_part(p, i):
    where = f"parts[{i}]"
    if not isinstance(p, dict):
        raise SpecError(f"{where} must be an object")
    t = p.get("type")
    if t not in PART_TYPES:
        raise SpecError(f"{where}.type must be one of {PART_TYPES}")
    out = {"id": str(p.get("id") or f"part{i}")[:40], "type": t,
           "pos": _vec(p.get("pos", [0, 0, 0]), f"{where}.pos"),
           "rot": _vec(p.get("rot", [0, 0, 0]), f"{where}.rot", lo=-360, hi=360)}
    mat = p.get("mat", "plastic")
    out["mat"] = mat if mat in MATERIALS else "plastic"
    color = p.get("color")
    if color is not None:
        if not isinstance(color, str) or not _HEX.match(color):
            raise SpecError(f"{where}.color must be #rrggbb")
        out["color"] = color.lower()
    if "bevel" in p:
        out["bevel"] = _num(p["bevel"], f"{where}.bevel", 0.0, 0.2)
    if t == "box":
        out["size"] = _vec(p.get("size"), f"{where}.size", lo=0.0005, hi=20)
        if "taper" in p:
            out["taper"] = _vec(p["taper"], f"{where}.taper", n=2, lo=0.05, hi=3.0)
    elif t in ("cylinder", "cone"):
        out["radius"] = _num(p.get("radius"), f"{where}.radius", 0.0005, 10)
        out["depth"] = _num(p.get("depth"), f"{where}.depth", 0.0005, 20)
        out["axis"] = p.get("axis", "z") if p.get("axis", "z") in ("x", "y", "z") else "z"
        if t == "cone":
            out["radius2"] = _num(p.get("radius2", 0.0), f"{where}.radius2", 0.0, 10)
    elif t == "sphere":
        out["radius"] = _num(p.get("radius"), f"{where}.radius", 0.0005, 10)
        out["scale"] = _vec(p.get("scale", [1, 1, 1]), f"{where}.scale", lo=0.05, hi=20)
    elif t == "torus":
        out["radius"] = _num(p.get("radius"), f"{where}.radius", 0.001, 10)
        out["tube"] = _num(p.get("tube"), f"{where}.tube", 0.0005, 5)
        out["axis"] = p.get("axis", "y") if p.get("axis", "y") in ("x", "y", "z") else "y"
        if out["tube"] >= out["radius"]:
            raise SpecError(f"{where}.tube must be smaller than radius")
    elif t == "profile":
        pts = p.get("points")
        if not isinstance(pts, list) or not 3 <= len(pts) <= MAX_POINTS:
            raise SpecError(f"{where}.points must be 3-{MAX_POINTS} [x, z] pairs")
        pts = [_vec(q, f"{where}.points[{k}]", n=2) for k, q in enumerate(pts)]
        if abs(polygon_area(pts)) < 1e-7:
            raise SpecError(f"{where}.points enclose no area")
        if not polygon_is_simple(pts):
            raise SpecError(f"{where}.points cross each other (the outline must not self-intersect)")
        out["points"] = pts
        out["thickness"] = _num(p.get("thickness"), f"{where}.thickness", 0.0005, 20)
    elif t == "lathe":
        pts = p.get("points")
        if not isinstance(pts, list) or not 2 <= len(pts) <= MAX_POINTS:
            raise SpecError(f"{where}.points must be 2-{MAX_POINTS} [position_along_axis, radius] pairs")
        pts = [_vec(q, f"{where}.points[{k}]", n=2) for k, q in enumerate(pts)]
        out["points"] = [[a, max(0.0, r)] for a, r in pts]
        if max(r for _, r in out["points"]) <= 0:
            raise SpecError(f"{where}.points need a radius > 0 (second number)")
        out["axis"] = p.get("axis", "z") if p.get("axis", "z") in ("x", "y", "z") else "z"
    elif t == "tube":
        pts = p.get("points")
        if not isinstance(pts, list) or not 2 <= len(pts) <= MAX_POINTS:
            raise SpecError(f"{where}.points must be 2-{MAX_POINTS} [x, y, z] points")
        out["points"] = [_vec(q, f"{where}.points[{k}]") for k, q in enumerate(pts)]
        out["radius"] = _num(p.get("radius"), f"{where}.radius", 0.0005, 5)
    cuts = p.get("cuts", [])
    if not isinstance(cuts, list) or len(cuts) > MAX_CUTS:
        raise SpecError(f"{where}.cuts must be a list of at most {MAX_CUTS}")
    out["cuts"] = [_cut(c, f"{where}.cuts[{k}]") for k, c in enumerate(cuts)]
    seams = p.get("seams", [])
    if not isinstance(seams, list) or len(seams) > 4:
        raise SpecError(f"{where}.seams must be a list of at most 4")
    out["seams"] = []
    for k, s in enumerate(seams):
        if not isinstance(s, dict) or s.get("axis") not in ("x", "y", "z") or not isinstance(s.get("at"), list):
            raise SpecError(f"{where}.seams[{k}] needs axis x|y|z and at: [positions]")
        out["seams"].append({"axis": s["axis"], "at": [_num(a, f"{where}.seams[{k}].at") for a in s["at"][:8]]})
    out["mirror_y"] = bool(p.get("mirror_y", False))
    att = p.get("attach") if isinstance(p.get("attach"), dict) else {}
    count = p.get("count", att.get("count", 1))
    out["count"] = count if isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 24 else 1
    out["step"] = _vec(p.get("step", att.get("step", [0, 0, 0])), f"{where}.step") if out["count"] > 1 else [0, 0, 0]
    return out


def validate(spec) -> dict:
    """Return a cleaned copy of the spec or raise SpecError with a message the model can act on."""
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    out = {"name": str(spec.get("name") or "asset")[:60]}
    cat = spec.get("category")
    out["category"] = cat if cat in CATEGORIES else "prop"
    style = spec.get("style")
    out["style"] = style if style in STYLES else "pbr"
    out["dims"] = _vec(spec.get("dims", [1, 1, 1]), "dims", lo=0.01, hi=20)
    parts = spec.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        raise SpecError(f"parts must be a list of 1-{MAX_PARTS} parts")
    out["parts"] = [validate_part(p, i) for i, p in enumerate(parts)]
    return out


def _mirror_rot(r):
    return [-r[0], r[1], -r[2]]


def expand_arrays(spec: dict) -> dict:
    """Repeat parts with count > 1 along their step (rail slots, bolts, slats)."""
    out = copy.deepcopy(spec)
    parts = []
    for p in out["parts"]:
        n, st = p.pop("count", 1), p.pop("step", [0, 0, 0])
        for k in range(n):
            q = copy.deepcopy(p)
            if k:
                q["id"] = f"{p['id']}_{k}"
                d = [st[i] * k for i in range(3)]
                q["pos"] = [p["pos"][i] + d[i] for i in range(3)]
                for c in q["cuts"]:
                    c["pos"] = [c["pos"][i] + d[i] for i in range(3)]
                for sm in q["seams"]:
                    ai = "xyz".index(sm["axis"])
                    sm["at"] = [a + d[ai] for a in sm["at"]]
            parts.append(q)
    out["parts"] = parts[:MAX_PARTS * 2]
    return out


def expand_mirrors(spec: dict) -> dict:
    """Add the -Y copy of every part with mirror_y (reflection across the XZ plane)."""
    out = expand_arrays(spec) if any(p.get("count", 1) > 1 for p in spec["parts"]) else copy.deepcopy(spec)
    for p in out["parts"]:
        p.pop("count", None)
        p.pop("step", None)
    extra = []
    for p in out["parts"]:
        if not p.get("mirror_y"):
            continue
        m = copy.deepcopy(p)
        m["id"] = p["id"] + "_m"
        m["mirror_y"] = False
        m["pos"] = [p["pos"][0], -p["pos"][1], p["pos"][2]]
        m["rot"] = _mirror_rot(p["rot"])
        if p["type"] == "tube":
            m["points"] = [[q[0], -q[1], q[2]] for q in p["points"]]
        for c in m["cuts"]:
            c["pos"] = [c["pos"][0], -c["pos"][1], c["pos"][2]]
            c["rot"] = _mirror_rot(c["rot"])
            c["step"] = [c["step"][0], -c["step"][1], c["step"][2]]
        for s in m["seams"]:
            if s["axis"] == "y":
                s["at"] = [-a for a in s["at"]]
        p["mirror_y"] = False
        extra.append(m)
    out["parts"].extend(extra)
    return out


def budget(spec: dict) -> dict:
    style, cat = spec["style"], spec["category"]
    tex = STYLE[style]["tex"]
    return {"tris": TRI_BUDGET[style][cat], "mesh_tris": ROBLOX_MESH_TRIS, "tex": tex,
            "size_range": SIZE_RANGE[cat]}


# Baseline (single pass, STAR's old way): flat-coloured primitives only.
BASELINE_TYPES = ("cube", "cylinder", "sphere", "cone")


def validate_baseline(spec) -> dict:
    if not isinstance(spec, dict) or not isinstance(spec.get("parts"), list) or not spec["parts"]:
        raise SpecError("baseline spec needs parts")
    out = {"name": str(spec.get("name") or "asset")[:60], "parts": []}
    for i, p in enumerate(spec["parts"][:MAX_PARTS]):
        if not isinstance(p, dict) or p.get("type") not in BASELINE_TYPES:
            continue
        q = {"type": p["type"], "pos": _vec(p.get("pos", [0, 0, 0]), f"parts[{i}].pos"),
             "rot": _vec(p.get("rot", [0, 0, 0]), f"parts[{i}].rot", lo=-360, hi=360),
             "size": _vec(p.get("size", [0.1, 0.1, 0.1]), f"parts[{i}].size", lo=0.0005, hi=20)}
        c = p.get("color", "#808080")
        q["color"] = c.lower() if isinstance(c, str) and _HEX.match(c) else "#808080"
        q["metallic"] = _num(p.get("metallic", 0.0), "metallic", 0, 1)
        q["roughness"] = _num(p.get("roughness", 0.5), "roughness", 0, 1)
        out["parts"].append(q)
    if not out["parts"]:
        raise SpecError("baseline spec has no valid parts")
    return out


# ---------------------------------------------------------------- layout by attachment
# The model says WHERE a part goes relative to another part (face + position across the face); this code computes
# coordinates, so parts touch by construction. Axes: front +X, back -X, top +Z, bottom -Z, left +Y, right -Y.
SIDES = {"front": (0, 1), "back": (0, -1), "left": (1, 1), "right": (1, -1), "top": (2, 1), "bottom": (2, -1),
         "center": (None, 0)}
# (u axis, v axis) across each face
FACE_UV = {0: (1, 2), 1: (0, 2), 2: (0, 1)}


def _rot_matrix(rot_deg):
    rx, ry, rz = (math.radians(a) for a in rot_deg)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    Rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    Ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    Rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mul(A, B):
        return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(Rz, mul(Ry, Rx))  # Blender XYZ Euler


_AXIS_M = {"z": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "x": [[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
           "y": [[1, 0, 0], [0, 0, -1], [0, 1, 0]]}


def _apply(M, v):
    return [sum(M[i][k] * v[k] for k in range(3)) for i in range(3)]


def _corners(lo, hi):
    return [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def _aabb(points):
    return [min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]


def local_aabb(p) -> tuple[list, list]:
    """Axis-aligned box of the part relative to its pos (after its axis mapping and rotation)."""
    t = p["type"]
    if t == "box":
        s = p["size"]
        tp = p.get("taper", [1, 1])
        lo, hi = [-s[0] / 2 * max(1, tp[0]), -s[1] / 2 * max(1, tp[1]), -s[2] / 2], \
                 [s[0] / 2 * max(1, tp[0]), s[1] / 2 * max(1, tp[1]), s[2] / 2]
        pts = _corners(lo, hi)
    elif t in ("cylinder", "cone"):
        r = max(p["radius"], p.get("radius2", 0))
        pts = [_apply(_AXIS_M[p["axis"]], c) for c in _corners([-r, -r, -p["depth"] / 2], [r, r, p["depth"] / 2])]
    elif t == "sphere":
        r, s = p["radius"], p["scale"]
        pts = _corners([-r * s[0], -r * s[1], -r * s[2]], [r * s[0], r * s[1], r * s[2]])
    elif t == "torus":
        R = p["radius"] + p["tube"]
        pts = [_apply(_AXIS_M[p["axis"]], c) for c in _corners([-R, -R, -p["tube"]], [R, R, p["tube"]])]
    elif t == "profile":
        xs, zs = [q[0] for q in p["points"]], [q[1] for q in p["points"]]
        pts = _corners([min(xs), -p["thickness"] / 2, min(zs)], [max(xs), p["thickness"] / 2, max(zs)])
    elif t == "lathe":
        r = max(q[1] for q in p["points"])
        hs = [q[0] for q in p["points"]]
        pts = [_apply(_AXIS_M[p["axis"]], c) for c in _corners([-r, -r, min(hs)], [r, r, max(hs)])]
    else:  # tube
        r = p["radius"]
        lo, hi = _aabb(p["points"])
        pts = _corners([lo[i] - r for i in range(3)], [hi[i] + r for i in range(3)])
    M = _rot_matrix(p["rot"])
    return _aabb([_apply(M, c) for c in pts])


def _place(lo_c, hi_c, plo, phi, side, u, v, sink):
    """pos for a child with local box (lo_c, hi_c) on `side` of the parent box (plo, phi)."""
    axis, sign = SIDES[side]
    pos = [0.0, 0.0, 0.0]
    pc = [(plo[i] + phi[i]) / 2 for i in range(3)]
    ph = [(phi[i] - plo[i]) / 2 for i in range(3)]
    cc = [(lo_c[i] + hi_c[i]) / 2 for i in range(3)]
    ch = [(hi_c[i] - lo_c[i]) / 2 for i in range(3)]
    if axis is None:
        for i, f in zip(range(3), (u, v, 0.0)):
            pos[i] = pc[i] + f * max(0.0, ph[i] - ch[i]) - cc[i]
        return pos
    ext = hi_c[axis] - lo_c[axis]
    if sign > 0:
        pos[axis] = phi[axis] - lo_c[axis] - sink * ext
    else:
        pos[axis] = plo[axis] - hi_c[axis] + sink * ext
    ua, va = FACE_UV[axis]
    pos[ua] = pc[ua] + u * max(0.0, ph[ua] - ch[ua]) - cc[ua]
    pos[va] = pc[va] + v * max(0.0, ph[va] - ch[va]) - cc[va]
    return pos


def _frac(x):
    return max(-1.0, min(1.0, float(x))) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0.0


def _fit_array(p, lo_c, hi_c, plo, phi):
    """A repeated part (count/step) attached to a parent: centre the row on the attach point and squeeze the step so
    every copy stays on the parent (models often overshoot the step)."""
    n = p["count"]
    for i in range(3):
        st = p["step"][i]
        if abs(st) < 1e-9:
            continue
        room = max(0.0, (phi[i] - plo[i]) - (hi_c[i] - lo_c[i]))
        if abs(st) * (n - 1) > room:
            st = math.copysign(room / (n - 1), st)
            p["step"][i] = st
        start = p["pos"][i] - st * (n - 1) / 2
        lo_first = start + min(0.0, st * (n - 1)) + lo_c[i]
        hi_last = start + max(0.0, st * (n - 1)) + hi_c[i]
        if lo_first < plo[i]:
            start += plo[i] - lo_first
        elif hi_last > phi[i]:
            start -= hi_last - phi[i]
        p["pos"][i] = start


def resolve_layout(raw_parts: list, parts: list) -> list:
    """Turn attach/side-relative fields of the raw model parts into world coordinates on the validated parts."""
    boxes = {}
    for rp, p in zip(raw_parts, parts):
        att = rp.get("attach") if isinstance(rp, dict) else None
        lo_c, hi_c = local_aabb(p)
        if isinstance(att, dict) and str(att.get("to")) in boxes and att.get("side", "center") in SIDES:
            plo, phi = boxes[str(att["to"])]
            sink = att.get("sink", 0.12)
            sink = max(0.0, min(0.6, float(sink))) if isinstance(sink, (int, float)) else 0.12
            pos = _place(lo_c, hi_c, plo, phi, att.get("side", "center"), _frac(att.get("u", 0)),
                         _frac(att.get("v", 0)), sink)
            off = att.get("offset")
            if isinstance(off, list) and len(off) == 3 and all(isinstance(o, (int, float)) for o in off):
                pos = [pos[i] + max(-2.0, min(2.0, off[i])) for i in range(3)]
            p["pos"] = pos
            if p.get("count", 1) > 1:
                _fit_array(p, lo_c, hi_c, plo, phi)
        lo = [p["pos"][i] + lo_c[i] for i in range(3)]
        hi = [p["pos"][i] + hi_c[i] for i in range(3)]
        boxes[p["id"]] = (lo, hi)
        if p["type"] == "tube":
            pass  # builder adds pos to the tube's points
        # cuts: side-relative (face of this part) or offsets from the part centre
        rcuts = rp.get("cuts", []) if isinstance(rp, dict) else []
        for rc, c in zip(rcuts, p["cuts"]):
            clo, chi = local_aabb({**c, "type": "box" if c["shape"] == "box" else "cylinder", "rot": c["rot"],
                                   "axis": c.get("axis", "z")})
            if isinstance(rc, dict) and rc.get("side") in SIDES and rc.get("side") != "center":
                axis, sign = SIDES[rc["side"]]
                cpos = _place(clo, chi, lo, hi, rc["side"], _frac(rc.get("u", 0)), _frac(rc.get("v", 0)), 0.5)
                c["pos"] = cpos
            else:
                c["pos"] = [p["pos"][i] + c["pos"][i] for i in range(3)]
        for s in p["seams"]:
            ai = "xyz".index(s["axis"])
            s["at"] = [(lo[ai] + hi[ai]) / 2 + _frac(a) * (hi[ai] - lo[ai]) / 2 * 0.95 for a in s["at"]]
    return parts


def prepare(raw: dict) -> dict:
    """validate -> resolve attachments -> expand mirrors: the spec the Blender builder gets."""
    spec = validate(raw)
    resolve_layout(raw.get("parts", []), spec["parts"])
    return expand_mirrors(spec)


def ground(spec: dict) -> dict:
    """Shift so the lowest point is z = 0 and the asset is centred in X/Y (builder frame)."""
    los, his = [], []
    for p in spec["parts"]:
        lo, hi = local_aabb(p)
        if p["type"] == "tube":
            lo, hi = local_aabb(p)
        los.append([p["pos"][i] + lo[i] for i in range(3)])
        his.append([p["pos"][i] + hi[i] for i in range(3)])
    lo = [min(q[i] for q in los) for i in range(3)]
    hi = [max(q[i] for q in his) for i in range(3)]
    d = [-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]]
    for p in spec["parts"]:
        p["pos"] = [p["pos"][i] + d[i] for i in range(3)]
        for c in p["cuts"]:
            c["pos"] = [c["pos"][i] + d[i] for i in range(3)]
        for s in p["seams"]:
            ai = "xyz".index(s["axis"])
            s["at"] = [a + d[ai] for a in s["at"]]
    return spec
