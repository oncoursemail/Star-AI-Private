"""Blockbench (Minecraft) part templates: each builds a complete star.blockbench spec from a few parameters.

Space as in star.blockbench.spec: 16 units = 1 block, x/z centred on 0, y = 0 on the ground, the front faces -z.
Every template attaches its parts by construction (faces share planes or overlap), mirrors pairs, keeps vanilla-
like proportions and adds idle/walk animations to mobs. The planner only fills Param values and colours.
"""
from __future__ import annotations

import colorsys
import math

from star.blockbench.paint import KINDS

from .core import Param, Role, Template

N, B, I = "num", "bool", "int"


def E(default, *choices, doc=""):
    return Param("enum", default, choices=tuple(choices), doc=doc)


def P(kind, default, lo=None, hi=None, doc=""):
    return Param(kind, default, lo, hi, doc=doc)


def shade(hexcolor: str, k: float) -> str:
    """Lighter (k > 1) or darker (k < 1) version of a colour, keeping the hue."""
    h = hexcolor.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    ll = max(0.06, min(0.92, ll * k))
    r, g, b = colorsys.hls_to_rgb(hh, ll, ss)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _snap(x: float, g: float) -> float:
    q = math.floor(abs(x) / g + 0.5) * g  # half away from zero keeps centred boxes symmetric
    return round(math.copysign(q, x), 4) if q else 0.0


class Kit:
    """Collects cuboids for one model; snaps every value to the texel grid the same way."""

    def __init__(self, name: str, category: str, roles: dict, density: int = 1):
        self.name, self.category, self.density = name, category, density
        self.g = 1.0 / density
        self.materials = {k: {"kind": v["kind"], "color": v["color"]} for k, v in roles.items()}
        self.parts: list[dict] = []
        self._names: set = set()

    def tone(self, role: str, k: float, kind: str | None = None) -> str:
        key = f"{role}_{'lt' if k > 1 else 'dk'}{int(abs(k - 1) * 100)}"
        if key not in self.materials:
            base = self.materials[role]
            self.materials[key] = {"kind": kind or base["kind"], "color": shade(base["color"], k)}
        return key

    def mat(self, key: str, kind: str, color: str) -> str:
        self.materials.setdefault(key, {"kind": kind, "color": color})
        return key

    def _uniq(self, name):
        base, n = name, 2
        while name in self._names:
            name = f"{base}{n}"
            n += 1
        self._names.add(name)
        return name

    def box(self, name, lo, hi, mat, *, parent=None, pivot=None, rot=None, decals=None, mirror_of=None,
            inflate=None) -> str:
        a = [_snap(min(lo[i], hi[i]), self.g) for i in range(3)]
        b = [_snap(max(lo[i], hi[i]), self.g) for i in range(3)]
        for i in range(3):
            if b[i] <= a[i]:
                b[i] = round(a[i] + self.g, 4)
        name = self._uniq(name)
        p = {"name": name, "from": a, "to": b, "material": mat}
        if parent:
            p["parent"] = parent
        if pivot is not None:
            p["pivot"] = [_snap(v, self.g / 2) for v in pivot]
        if rot is not None and any(rot):
            p["rotation"] = [float(r) for r in rot]
        if decals:
            p["decals"] = [d if isinstance(d, dict) else {"face": d[0], "kind": d[1], **({"color": d[2]} if len(d) > 2 and d[2] else {})}
                           for d in decals]
        if mirror_of:
            p["mirror_of"] = mirror_of
        if inflate:
            p["inflate"] = inflate
        self.parts.append(p)
        return name

    def _fit_java(self):
        _fit_java_parts(self.parts, self.g)

    def cbox(self, name, w, y0, y1, d, mat, *, x=0.0, z=0.0, **kw) -> str:
        """Box centred on (x, z) with width w (x) and depth d (z)."""
        return self.box(name, [x - w / 2, y0, z - d / 2], [x + w / 2, y1, z + d / 2], mat, **kw)

    def pair(self, name, lo, hi, mat, *, parent=None, pivot=None, rot=None, decals=None, **kw):
        """A left part (built at +x) and its mirrored right copy. Returns (left, right) names."""
        pl = parent if not parent or not parent.endswith("_r") else parent[:-2] + "_l"
        left = self.box(name + "_l", lo, hi, mat, parent=pl, pivot=pivot, rot=rot, decals=decals, **kw)
        pr = parent[:-2] + "_r" if parent and parent.endswith("_l") else parent
        mlo, mhi = [-hi[0], lo[1], lo[2]], [-lo[0], hi[1], hi[2]]
        mp = [-pivot[0], pivot[1], pivot[2]] if pivot is not None else None
        mr = [rot[0], -rot[1], -rot[2]] if rot is not None else None
        right = self.box(name + "_r", mlo, mhi, mat, parent=pr, pivot=mp, rot=mr, mirror_of=left, **kw)
        return left, right

    def spec(self, animations=()) -> dict:
        if self.category in ("block", "item", "furniture"):
            self._fit_java()
        _dezfight(self.parts)
        return {"name": self.name, "category": self.category, "density": self.density,
                "materials": self.materials, "parts": self.parts, "animations": list(animations)}


def _fit_java_parts(parts, g):
    """Scale a model down (about x = z = 0, y = 0) when extreme parameters push it past the Java range."""
    span = max(max(abs(v) for p in parts for v in (p["from"][0], p["to"][0], p["from"][2], p["to"][2])) / 24.0,
               max(p["to"][1] for p in parts) / 32.0)
    if span <= 1.0:
        return
    f = 1.0 / span
    for p in parts:
        for key in ("from", "to", "pivot"):
            if key in p:
                p[key] = [_snap(v * f, g / (2 if key == "pivot" else 1)) for v in p[key]]
                if key != "pivot":
                    p[key] = [max(-24.0, min(24.0, v)) if i != 1 else min(32.0, v) for i, v in enumerate(p[key])]


def _coplanar(a, b):
    """Two boxes have a same-facing face in one plane that overlaps (flickers in game)."""
    for ax in range(3):
        o = [k for k in range(3) if k != ax]
        if not all(min(a[1][k], b[1][k]) - max(a[0][k], b[0][k]) > 1e-4 for k in o):
            continue
        if abs(a[0][ax] - b[0][ax]) < 1e-4 or abs(a[1][ax] - b[1][ax]) < 1e-4:
            return True
    return False


def _dezfight(parts):
    """Give a part that would share a face plane with an earlier part a tiny inflate (0.03-0.33 units), so the
    texture stays on the texel grid and nothing flickers. Rotated parts (or under a rotated parent) are skipped."""
    by = {p["name"]: p for p in parts}

    def rotated(p):
        while p:
            if any(p.get("rotation") or ()):
                return True
            p = by.get(p.get("parent"))
        return False
    done = []
    for p in parts:
        if rotated(p):
            continue
        g0 = float(p.get("inflate") or 0)
        for step in range(12):
            g = g0 + 0.03 * step
            box = ([v - g for v in p["from"]], [v + g for v in p["to"]])
            if not any(_coplanar(box, d) for d in done):
                break
        if g > g0:
            p["inflate"] = round(g, 3)
        done.append(box)


def _anim(name, length, bones):
    return {"name": name, "length": length, "loop": True, "bones": bones}


def _swing(a, axis=0, length=1.0, phase=1):
    v = [0, 0, 0]
    w = [0, 0, 0]
    v[axis], w[axis] = a * phase, -a * phase
    return {"rotation": {"0": v, str(length / 2): w, str(length): v}}


def _bob(dy, length=2.0):
    return {"position": {"0": [0, 0, 0], str(length / 2): [0, dy, 0], str(length): [0, 0, 0]}}


def _spin(length=4.0):
    return {"rotation": {"0": [0, 0, 0], str(length / 2): [0, 180, 0], str(length): [0, 360, 0]}}


EYE = {"normal": "eyes", "glow": "glow_eyes", "none": None}


# ------------------------------------------------------------------------------------------------ mobs
def build_biped(p, r, name):
    if p["build"] == "golem":  # a golem is carved from one material: body, arms and legs share the head's
        r = dict(r, torso=r["skin"], legs=r["skin"], feet=r["skin"])
    k = Kit(name, "mob", r)
    shapes = {"normal": (8, 12, 4, 4, 12, 12), "stocky": (10, 10, 6, 5, 10, 8), "slim": (6, 12, 4, 3, 12, 13),
              "golem": (16, 12, 10, 6, 22, 11), "child": (6, 8, 4, 3, 8, 6)}
    bw, bh, bd, lw, al, ll = shapes[p["build"]]
    ll = max(3, round(ll * p["leg_scale"]))
    al = max(4, round(al * p["arm_scale"]))
    hs = max(4, round((10 if p["build"] == "golem" else 8) * p["head_scale"] / 2) * 2)
    top = ll + bh
    body = k.cbox("body", bw, ll, top, bd, "torso", pivot=[0, ll, 0])
    if p["build"] == "golem":  # narrow waist under a wide chest
        k.cbox("waist", bw - 6, ll, ll + 3, bd - 4, k.tone("torso", 0.85), parent=body)
    if p["belt"]:
        k.cbox("belt", bw + 1, ll + 1, ll + 3, bd + 1, "accent", parent=body)
    hz = -2 if p["build"] == "golem" else 0
    eyes = EYE[p["eyes"]]
    head = k.cbox("head", hs, top, top + hs, hs, "skin", z=hz, parent=body, pivot=[0, top, 0],
                  decals=[("north", eyes, r["eye"]["color"])] if eyes else None)
    face_z = hz - hs / 2
    if p["nose"]:
        k.box("nose", [-1, top + 1, face_z - (3 if p["build"] == "golem" else 1)], [1, top + 4, face_z], "skin", parent=head)
    if p["beard"]:
        k.box("beard", [-hs / 2, top - 2, face_z - 1], [hs / 2, top + 3, face_z + 2], "hair", parent=head)
    hat = p["hat"]
    if hat == "hair":
        k.box("hair", [-hs / 2 - 0.5, top + hs - 2, hz - hs / 2 - 0.5], [hs / 2 + 0.5, top + hs + 1, hz + hs / 2 + 0.5], "hair", parent=head)
        k.box("hair_back", [-hs / 2 - 0.5, top + 2, hz + hs / 2 - 1], [hs / 2 + 0.5, top + hs, hz + hs / 2 + 0.5], "hair", parent=head)
    elif hat == "cap":
        k.box("cap", [-hs / 2 - 0.5, top + hs - 2, hz - hs / 2 - 0.5], [hs / 2 + 0.5, top + hs + 1, hz + hs / 2 + 0.5], "accent", parent=head)
        k.box("cap_brim", [-hs / 2 + 1, top + hs - 2, face_z - 3], [hs / 2 - 1, top + hs - 1, face_z], "accent", parent=head)
    elif hat == "hood":
        k.box("hood_top", [-hs / 2 - 1, top + hs, hz - hs / 2 - 1], [hs / 2 + 1, top + hs + 1, hz + hs / 2 + 1], "hair", parent=head)
        k.box("hood_back", [-hs / 2 - 1, top - 1, hz + hs / 2], [hs / 2 + 1, top + hs, hz + hs / 2 + 1], "hair", parent=head)
        k.pair("hood_side", [hs / 2, top, hz - hs / 2 - 1], [hs / 2 + 1, top + hs, hz + hs / 2], "hair", parent=head)
    elif hat == "horns":
        k.pair("horn", [hs / 2 - 1, top + hs - 2, hz - 1], [hs / 2 + 2, top + hs, hz + 1], "accent", parent=head)
        k.pair("horn_tip", [hs / 2 + 1, top + hs, hz - 1], [hs / 2 + 2, top + hs + 3, hz + 1], "accent", parent=head)
    elif hat == "crown":
        k.box("crown", [-hs / 2 - 0.5, top + hs - 1, hz - hs / 2 - 0.5], [hs / 2 + 0.5, top + hs + 1, hz + hs / 2 + 0.5], "accent", parent=head)
        for i, x in enumerate((-hs / 2, -1, hs / 2 - 2)):
            k.box(f"crown_pt{i}", [x, top + hs + 1, face_z - 0.5], [x + 2, top + hs + 3, face_z + 1], "accent", parent=head)
    elif hat == "helmet":
        k.box("helmet", [-hs / 2 - 1, top + 3, hz - hs / 2 - 1], [hs / 2 + 1, top + hs + 1, hz + hs / 2 + 1], "accent", parent=head,
              decals=[("north", "stripe", shade(r["accent"]["color"], 0.4))])
    if p["build"] == "golem" and p["moss"]:
        k.box("moss_head", [-hs / 2, top + hs, hz - hs / 2], [1, top + hs + 1, hz + 1], "moss", parent=head)
        k.box("moss_back", [-bw / 2 + 1, top - 3, bd / 2], [2, top, bd / 2 + 1], "moss", parent=body)
    arm_top = top - (1 if p["build"] == "golem" else 0)
    arm_w = lw if p["build"] != "golem" else 5
    al_, ar_ = k.pair("arm", [bw / 2, arm_top - al, -arm_w / 2], [bw / 2 + arm_w, arm_top, arm_w / 2], "torso" if p["sleeves"] else "skin",
                      parent=body, pivot=[bw / 2 + arm_w / 2, arm_top - 2, 0])
    if p["sleeves"]:
        k.pair("hand", [bw / 2 - 0.0, arm_top - al - 0.0, -arm_w / 2 - 0.0], [bw / 2 + arm_w, arm_top - al + 3, arm_w / 2], "skin", parent=al_)
        k.parts[-2]["parent"], k.parts[-1]["parent"] = al_, ar_
    if p["build"] == "golem" and p["moss"]:
        k.box("moss_shoulder", [bw / 2, arm_top, -2], [bw / 2 + arm_w, arm_top + 1, 3], "moss", parent=al_)
    lx = max(lw, bw / 4)
    ll_, lr_ = k.pair("leg", [0 if p["build"] != "golem" else 1, 0, -lw / 2], [lx + (0 if p["build"] != "golem" else 1), ll, lw / 2],
                      "legs", parent=body, pivot=[lx / 2, ll, 0])
    k.pair("shoe", [0 if p["build"] != "golem" else 1, 0, -lw / 2 - 1], [lx + (0 if p["build"] != "golem" else 1), min(3, ll - 1), lw / 2],
           "feet", parent=ll_)
    k.parts[-2]["parent"], k.parts[-1]["parent"] = ll_, lr_
    walk = {ll_: _swing(30), lr_: _swing(30, phase=-1), al_: _swing(25, phase=-1), ar_: _swing(25)}
    idle = {head: {"rotation": {"0": [0, -8, 0], "1.5": [0, 8, 0], "3": [0, -8, 0]}},
            al_: {"rotation": {"0": [0, 0, -3], "1.5": [0, 0, 3], "3": [0, 0, -3]}},
            ar_: {"rotation": {"0": [0, 0, 3], "1.5": [0, 0, -3], "3": [0, 0, 3]}}}
    return k.spec([_anim("idle", 3.0, idle), _anim("walk", 1.0, walk)])


def build_quadruped(p, r, name):
    k = Kit(name, "mob", r)
    L, W, H = p["body_len"], p["body_w"], p["body_h"]
    lh, lw, hs = p["leg_h"], p["leg_w"], p["head"]
    fluffy = p["fluffy"]
    by0, by1 = lh, lh + H
    body = k.box("body", [-W / 2, by0, -L / 2], [W / 2, by1, L / 2], "body", pivot=[0, by0, 0],
                 decals=[("up", "spots", r["pattern"]["color"])] if p["pattern"] == "spots" else
                 ([("east", "stripe", r["pattern"]["color"]), ("west", "stripe", r["pattern"]["color"])] if p["pattern"] == "stripes" else None))
    if fluffy:
        k.box("wool", [-W / 2 - 1, by0 - 1, -L / 2 + 1], [W / 2 + 1, by1 + 1, L / 2 + 1], "body", parent=body)
        k.parts[0]["material"] = k.tone("legs", 1.0)
    if p["pattern"] == "belly":
        k.box("belly", [-W / 2 + 1, by0 - 1, -L / 2 + 2], [W / 2 - 1, by0, L / 2 - 2], "pattern", parent=body)
    if p["neck"]:
        ny = by1 + max(2, hs // 2)
        k.box("neck", [-hs / 2 + 1, by1 - 2, -L / 2 - 1], [hs / 2 - 1, ny + 1, -L / 2 + 3], "body", parent=body)
        hy0 = ny
    else:
        hy0 = by1 - hs // 2
    hz1 = -L / 2 + max(1, hs // 3)
    hz0 = hz1 - hs
    eyes = EYE[p["eyes"]]
    head = k.box("head", [-hs / 2, hy0, hz0], [hs / 2, hy0 + hs, hz1], "head", parent=body,
                 pivot=[0, hy0 + hs / 2, hz1], decals=[("north", eyes, r["eye"]["color"])] if eyes else None)
    if fluffy:
        k.box("wool_cap", [-hs / 2 - 0.5, hy0 + hs - 2, hz0 + 1], [hs / 2 + 0.5, hy0 + hs + 1, hz1 + 0.5], "body", parent=head)
    sl = p["snout_len"]
    if sl > 0:
        sw = max(2, round(hs * 0.6 / 2) * 2)
        sn = k.box("snout", [-sw / 2, hy0, hz0 - sl], [sw / 2, hy0 + max(2, hs // 2 - 1), hz0], "snout", parent=head,
                   decals=[("north", "nose", r["eye"]["color"])])
        k.box("nose", [-1, hy0 + max(2, hs // 2 - 1) - 1, hz0 - sl - 0.5 * 2], [1, hy0 + max(2, hs // 2 - 1), hz0 - sl], "nose", parent=sn)
    ears = p["ears"]
    if ears == "pointy":
        k.pair("ear", [hs / 2 - 2, hy0 + hs, hz1 - 2], [hs / 2, hy0 + hs + 3, hz1 - 1], "head", parent=head)
        k.pair("ear_in", [hs / 2 - 2, hy0 + hs, hz1 - 2.0], [hs / 2 - 1, hy0 + hs + 2, hz1 - 1.5], "snout", parent=head)
    elif ears == "floppy":
        k.pair("ear", [hs / 2, hy0 + 1, hz1 - 3], [hs / 2 + 1, hy0 + hs - 1, hz1 - 1], "head", parent=head)
    elif ears == "round":
        k.pair("ear", [hs / 2 - 2, hy0 + hs, hz1 - 2], [hs / 2, hy0 + hs + 2, hz1 - 1], "head", parent=head)
    elif ears == "long":  # rabbit / donkey
        k.pair("ear", [hs / 2 - 2, hy0 + hs, hz1 - 2], [hs / 2 - 0.0, hy0 + hs + max(4, hs), hz1 - 1], "head", parent=head)
        k.pair("ear_in", [hs / 2 - 1.0 - 0.0 - 1, hy0 + hs + 1, hz1 - 2.0 - 0.0], [hs / 2 - 1, hy0 + hs + max(4, hs) - 1, hz1 - 1.5], "snout", parent=head)
    elif ears == "horns":
        k.pair("horn", [hs / 2, hy0 + hs - 2, hz1 - 3], [hs / 2 + 2, hy0 + hs, hz1 - 1], "accent", parent=head)
        k.pair("horn_tip", [hs / 2 + 1, hy0 + hs, hz1 - 3], [hs / 2 + 2, hy0 + hs + 2, hz1 - 1], "accent", parent=head)
    ix = W / 2 - lw / 2 - (0 if W >= 2 * lw + 2 else -0.5)
    fz, bz = -L / 2 + lw / 2 + 1, L / 2 - lw / 2 - 1
    legs = []
    for tag, z in (("front", fz), ("back", bz)):
        a, b = k.pair(f"leg_{tag}", [ix - lw / 2, 0, z - lw / 2], [ix + lw / 2, lh + 1, z + lw / 2], "legs",
                      parent=body, pivot=[ix, lh, z])
        k.pair(f"paw_{tag}", [ix - lw / 2, 0, z - lw / 2 - 0.0], [ix + lw / 2, min(2, lh), z + lw / 2], "paws", parent=a)
        k.parts[-2]["parent"], k.parts[-1]["parent"] = a, b
        legs += [a, b]
    tail = p["tail"]
    tb = None
    if tail == "bushy":
        tw = max(3, W // 2)
        tb = k.box("tail", [-tw / 2, by1 - tw - 1, L / 2 - 1], [tw / 2, by1 - 1, L / 2 + 7], "body", parent=body,
                   pivot=[0, by1 - tw / 2 - 1, L / 2], rot=[-25, 0, 0])
        k.box("tail_tip", [-tw / 2 + 0.0, by1 - tw - 1, L / 2 + 7], [tw / 2, by1 - 1, L / 2 + 10], "tip", parent=tb)
    elif tail == "long":
        tb = k.box("tail", [-1, by1 - 3, L / 2 - 1], [1, by1 - 1, L / 2 + 8], "body", parent=body,
                   pivot=[0, by1 - 2, L / 2], rot=[-35, 0, 0])
        k.box("tail_tip", [-1, by1 - 3, L / 2 + 8], [1, by1 - 1, L / 2 + 10], "tip", parent=tb)
    elif tail == "short":
        tb = k.box("tail", [-1.0, by1 - 3, L / 2 - 1], [1, by1, L / 2 + 2], "body", parent=body, pivot=[0, by1 - 2, L / 2])
    elif tail == "curly":
        tb = k.box("tail", [-1, by1 - 3, L / 2], [1, by1 - 1, L / 2 + 2], "snout", parent=body, pivot=[0, by1 - 2, L / 2])
        k.box("tail_curl", [-1, by1 - 1, L / 2 + 1], [1, by1 + 1, L / 2 + 3], "snout", parent=tb)
    walk = {legs[0]: _swing(28), legs[1]: _swing(28, phase=-1), legs[2]: _swing(28, phase=-1), legs[3]: _swing(28)}
    idle = {head: {"rotation": {"0": [0, 0, 0], "1": [6, 6, 0], "2": [0, 0, 0]}}}
    if tb:
        walk[tb] = {"rotation": {"0": [-25, -12, 0], "0.5": [-25, 12, 0], "1": [-25, -12, 0]}} if tail in ("bushy",) else \
            {"rotation": {"0": [0, -12, 0], "0.5": [0, 12, 0], "1": [0, -12, 0]}}
        idle[tb] = walk[tb]
    return k.spec([_anim("idle", 2.0, idle), _anim("walk", 1.0, walk)])


def build_bird(p, r, name):
    k = Kit(name, "mob", r)
    s = p["size"]
    lh = p["leg_h"]
    upright = p["posture"] == "upright"
    if upright:
        w, h, d = s, round(s * 1.4), max(4, round(s * 0.8))
    else:
        w, h, d = max(4, round(s * 0.75)), max(4, round(s * 0.7)), s
    y0 = lh
    body = k.cbox("body", w, y0, y0 + h, d, "body", pivot=[0, y0, 0])
    if p["belly"]:
        k.box("belly", [-w / 2 + 1, y0 + 1, -d / 2 - 1], [w / 2 - 1, y0 + h - (2 if upright else 1), -d / 2 + 1], "belly", parent=body)
    hs = max(4, round(s * (0.75 if upright else 0.6) / 2) * 2)
    eyes = EYE[p["eyes"]]
    if upright:
        hy0, hz = y0 + h, 0
    else:
        hy0, hz = y0 + h - 2, -d / 2 - hs / 2 + 2
    head = k.cbox("head", hs, hy0, hy0 + hs, hs, "head", z=hz, parent=body, pivot=[0, hy0, hz],
                  decals=[("north", eyes, r["eye"]["color"])] if eyes else None)
    bl = p["beak_len"]
    bw = 2 if hs < 6 else 4 if p["beak_wide"] else 2
    k.box("beak", [-bw / 2, hy0 + 1, hz - hs / 2 - bl], [bw / 2, hy0 + 3, hz - hs / 2], "beak", parent=head)
    if p["crest"] == "tuft":
        k.box("crest", [-1, hy0 + hs, hz - 1], [1, hy0 + hs + 2, hz + 2], "accent", parent=head)
    elif p["crest"] == "comb":
        k.box("comb", [-0.0 - 1, hy0 + hs, hz - hs / 2], [1, hy0 + hs + 2, hz + 1], "accent", parent=head)
        k.box("wattle", [-1, hy0 - 1, hz - hs / 2 - 1], [1, hy0 + 1, hz - hs / 2], "accent", parent=head)
    elif p["crest"] == "ears":
        k.pair("ear_tuft", [hs / 2 - 2, hy0 + hs, hz - 1], [hs / 2, hy0 + hs + 2, hz + 1], "head", parent=head)
    wl = max(3, round(h * p["wing_scale"] * (0.85 if upright else 1.0)))
    if upright:
        wa, wb = k.pair("wing", [w / 2, y0 + h - wl, -d / 2 + 1], [w / 2 + 1, y0 + h, d / 2 - 1], "wing",
                        parent=body, pivot=[w / 2, y0 + h - 1, 0])
    else:
        wa, wb = k.pair("wing", [w / 2, y0 + 1, -d / 2 + 1], [w / 2 + 1, y0 + h - 1, -d / 2 + 1 + wl], "wing",
                        parent=body, pivot=[w / 2, y0 + h - 1, 0])
    tail = p["tail"]
    if tail != "none":
        tl = {"short": 2, "fan": 3, "long": 6}[tail]
        tw = w - 2 if tail == "fan" else max(2, w // 2)
        ty = y0 + (0 if upright else h - 3)
        k.box("tail", [-tw / 2, ty, d / 2 - 1], [tw / 2, ty + (2 if upright else 3), d / 2 + tl], "wing", parent=body,
              pivot=[0, ty, d / 2], rot=[0 if upright else -20, 0, 0])
    if lh > 0:
        la, lb = k.pair("leg", [1, 0, -0.5], [2, lh + 1, 0.5], "feet", parent=body, pivot=[1.5, lh, 0])
    else:
        la = lb = None
    fa, fb = k.pair("foot", [0.5 if upright else 0.5, 0, -2 - (d / 4 if upright else 0)], [2.5, 1, 0.5], "feet", parent=la or body)
    if la:
        k.parts[-1]["parent"] = lb
    walk = {wa: {"rotation": {"0": [0, 0, -8], "0.5": [0, 0, 8], "1": [0, 0, -8]}},
            wb: {"rotation": {"0": [0, 0, 8], "0.5": [0, 0, -8], "1": [0, 0, 8]}},
            body: {"rotation": {"0": [0, 0, -6], "0.5": [0, 0, 6], "1": [0, 0, -6]}} if upright else _bob(1, 1.0)}
    if la and lb:
        walk[la], walk[lb] = _swing(25), _swing(25, phase=-1)
    idle = {head: {"rotation": {"0": [0, -10, 0], "1": [0, 10, 0], "2": [0, -10, 0]}}}
    return k.spec([_anim("idle", 2.0, idle), _anim("walk", 1.0, walk)])


def build_frog(p, r, name):
    k = Kit(name, "mob", r)
    s = p["size"]
    w, h, d = s, max(3, round(s * 0.5)), s
    lift = 1
    body = k.cbox("body", w, lift, lift + h, d, "skin", pivot=[0, lift, 0],
                  decals=[("up", "spots", r["pattern"]["color"])] if p["spots"] else None)
    k.box("belly", [-w / 2 + 1, lift - 0.0, -d / 2 - 0.0], [w / 2 - 1, lift + 1, d / 2 - 1], "belly", parent=body)
    k.box("mouth", [-w / 2 + 1, lift + 1, -d / 2 - 0.5], [w / 2 - 1, lift + 2, -d / 2], "mouth", parent=body)
    es = p["eye_size"]
    ex = w / 2 - es
    ea, eb = k.pair("eye", [ex, lift + h - 1, -d / 2], [ex + es, lift + h + es, -d / 2 + es], "skin", parent=body)
    k.pair("eyeball", [ex + 0.0, lift + h, -d / 2 - 0.5], [ex + es, lift + h + es - 1, -d / 2], "eyeball", parent=ea)
    k.parts[-1]["parent"] = eb
    pc = ex + es / 2
    k.pair("pupil", [pc - 0.5, lift + h + 0.0, -d / 2 - 1], [pc + 0.5, lift + h + max(1, es - 2), -d / 2 - 0.5], "eye", parent=ea)
    k.parts[-1]["parent"] = eb
    ka, kb = k.pair("front_leg", [w / 2 - 3, 0, -d / 2 + 1], [w / 2 - 1, lift + 1, -d / 2 + 3], "skin", parent=body,
                    pivot=[w / 2 - 2, lift, -d / 2 + 2])
    bl = p["back_leg"]
    ta, tb = k.pair("thigh", [w / 2 - 1, 0, d / 2 - bl - 1], [w / 2 + 1, lift + 2, d / 2], "skin", parent=body,
                    pivot=[w / 2, lift + 1, d / 2 - 2])
    k.pair("foot", [w / 2 - 1, 0, -0.0 + d / 2 - bl - 3], [w / 2 + 2, 1, d / 2 - bl + 0.0], "belly", parent=ta)
    k.parts[-1]["parent"] = tb
    if p["throat"]:
        k.box("throat", [-2, lift - 0.0, -d / 2 - 1], [2, lift + 2, -d / 2 + 1], "belly", parent=body)
    hop = {body: {"position": {"0": [0, 0, 0], "0.3": [0, 3, -1], "0.6": [0, 0, 0], "1.2": [0, 0, 0]}},
           ta: {"rotation": {"0": [0, 0, 0], "0.3": [30, 0, 0], "0.6": [0, 0, 0], "1.2": [0, 0, 0]}},
           tb: {"rotation": {"0": [0, 0, 0], "0.3": [30, 0, 0], "0.6": [0, 0, 0], "1.2": [0, 0, 0]}}}
    idle = {body: {"scale": {"0": [1, 1, 1], "1": [1.03, 0.97, 1.03], "2": [1, 1, 1]}}}
    return k.spec([_anim("idle", 2.0, idle), _anim("hop", 1.2, hop)])


def build_arthropod(p, r, name):
    k = Kit(name, "mob", r)
    L, W = p["body_len"], p["body_w"]
    lh = 2
    h = 3 if p["kind"] in ("scorpion", "crab") else 4
    body = k.box("body", [-W / 2, lh, -L / 2], [W / 2, lh + h, L / 2], "shell", pivot=[0, lh, 0])
    seg = L / p["segments"]
    for i in range(1, p["segments"]):
        z = -L / 2 + i * seg
        k.box(f"plate{i}", [-W / 2 - 0.5, lh + h - 1, z - 0.5], [W / 2 + 0.5, lh + h + 0.5 * 2, z + 0.5], k.tone("shell", 0.8), parent=body)
    eyes = EYE[p["eyes"]]
    hs = max(4, W - 2)
    head = k.box("head", [-hs / 2, lh, -L / 2 - 3], [hs / 2, lh + h - 0.0, -L / 2 + 1], "shell", parent=body,
                 pivot=[0, lh + 1, -L / 2], decals=[("north", eyes, r["eye"]["color"])] if eyes else None)
    legs = []
    pairs = p["leg_pairs"]
    span = L - 4
    for i in range(pairs):
        z = -L / 2 + 2 + (span * i / max(1, pairs - 1))
        a, b = k.pair(f"leg{i}", [W / 2, 0, z - 0.5], [W / 2 + p["leg_len"], lh + 1, z + 0.5], "legs", parent=body,
                      pivot=[W / 2, lh + 1, z], rot=[0, (i - (pairs - 1) / 2) * -14, -20])
        k.pair(f"foot{i}", [W / 2 + p["leg_len"] - 1, 0, z - 0.5], [W / 2 + p["leg_len"], lh + 1, z + 0.5], "legs", parent=a)
        k.parts[-1]["parent"] = b
        legs += [a, b]
    if p["pincers"]:
        aa, ab = k.pair("arm", [hs / 2 - 1, lh, -L / 2 - 6], [hs / 2 + 1, lh + 2, -L / 2 - 1], "shell", parent=body,
                        pivot=[hs / 2, lh + 1, -L / 2 - 1], rot=[0, 25, 0])
        ca, cb = k.pair("claw", [hs / 2 - 1.0, lh - 0.0, -L / 2 - 10], [hs / 2 + 3, lh + 3, -L / 2 - 6], "claw", parent=aa)
        k.parts[-1]["parent"] = ab
        k.pair("claw_jaw", [hs / 2 - 1.0, lh, -L / 2 - 12], [hs / 2 + 0.0, lh + 2, -L / 2 - 10], "claw", parent=ca)
        k.parts[-1]["parent"] = cb
        k.pair("claw_tip", [hs / 2 + 2, lh, -L / 2 - 12], [hs / 2 + 3, lh + 2, -L / 2 - 10], "claw", parent=ca)
        k.parts[-1]["parent"] = cb
    tip = None
    if p["stinger"]:
        prev, z0, y0 = body, L / 2, lh
        n = p["tail_segments"]
        for i in range(n):
            tw = max(2, 4 - i // 2)
            prev = k.box(f"tail{i}", [-tw / 2, y0, z0 - 0.0], [tw / 2, y0 + 3, z0 + 3], "shell" if i % 2 == 0 else k.tone("shell", 0.85),
                         parent=prev, pivot=[0, y0 + 1.5, z0], rot=[-38 if i else -30, 0, 0])
            z0 += 3
        tip = k.box("stinger", [-1, y0, z0], [1, y0 + 2, z0 + 3], "claw", parent=prev, pivot=[0, y0 + 1, z0], rot=[-50, 0, 0])
    walk = {}
    for i, leg in enumerate(legs):
        walk[leg] = {"rotation": {"0": [0, 10 if (i // 2 + i) % 2 else -10, 0], "0.5": [0, -10 if (i // 2 + i) % 2 else 10, 0],
                                  "1": [0, 10 if (i // 2 + i) % 2 else -10, 0]}}
    idle = {head: {"rotation": {"0": [0, -5, 0], "1": [0, 5, 0], "2": [0, -5, 0]}}}
    if tip:
        idle[tip] = {"rotation": {"0": [0, 0, 0], "1": [-12, 0, 0], "2": [0, 0, 0]}}
    return k.spec([_anim("idle", 2.0, idle), _anim("walk", 1.0, walk)])


def build_fish(p, r, name):
    k = Kit(name, "mob", r)
    L, H, W = p["length"], p["height"], p["width"]
    y0 = 2
    body = k.box("body", [-W / 2, y0, -L / 2], [W / 2, y0 + H, L / 2], "body", pivot=[0, y0 + H / 2, 0],
                 decals=[("east", "stripe", r["accent"]["color"]), ("west", "stripe", r["accent"]["color"])] if p["stripes"] else None)
    head = k.box("head", [-W / 2 + 0.0, y0 + 1, -L / 2 - 3], [W / 2, y0 + H - 1, -L / 2], "body", parent=body,
                 decals=[("east", "eyes", r["eye"]["color"]), ("west", "eyes", r["eye"]["color"])])
    k.box("belly", [-W / 2 + 0.0, y0 - 1, -L / 2 + 1], [W / 2, y0, L / 2 - 2], "belly", parent=body)
    tail = k.box("tail", [-0.5, y0 - 1, L / 2], [0.5, y0 + H + 1, L / 2 + p["tail"]], "fin", parent=body, pivot=[0, y0 + H / 2, L / 2])
    k.box("dorsal", [-0.5, y0 + H, -L / 4], [0.5, y0 + H + p["fin"], L / 4], "fin", parent=body)
    k.pair("side_fin", [W / 2, y0 + 1, -L / 4], [W / 2 + 2, y0 + 2, -L / 4 + 3], "fin", parent=body)
    del head
    swim = {tail: {"rotation": {"0": [0, -20, 0], "0.5": [0, 20, 0], "1": [0, -20, 0]}},
            body: {"rotation": {"0": [0, 5, 0], "0.5": [0, -5, 0], "1": [0, 5, 0]}}}
    return k.spec([_anim("idle", 1.0, swim), _anim("swim", 1.0, swim)])


# ------------------------------------------------------------------------------------------------ furniture
def _legs(k, w, d, y1, leg, mat, inset=0.0, prefix="leg"):
    x, z = w / 2 - leg / 2 - inset, d / 2 - leg / 2 - inset
    for tag, zz in (("front", -z), ("back", z)):
        k.pair(f"{prefix}_{tag}", [x - leg / 2, 0, zz - leg / 2], [x + leg / 2, y1, zz + leg / 2], mat)


def build_table(p, r, name):
    k = Kit(name, "furniture", r)
    w, d, h, t = p["width"], p["depth"], p["height"], p["top_thick"]
    ov = p["overhang"]
    leg = p["leg"]
    k.cbox("top", w, h - t, h, d, "top", decals=[("north", "border", None), ("south", "border", None)])
    style = p["legs"]
    if style == "trestle":
        for s in (-1, 1):
            x = s * (w / 2 - ov - 2)
            k.cbox(f"trestle_post{s + 1}", 2, 2, h - t, 4, "legs", x=x)
            k.cbox(f"trestle_foot{s + 1}", 2, 0, 2, d - 2, "legs", x=x)
        k.cbox("stretcher", w - 2 * ov - 4, 4, 6, 2, "trim")
    elif style == "pedestal":
        k.cbox("pedestal", max(4, leg + 2), 2, h - t, max(4, leg + 2), "legs")
        k.cbox("pedestal_foot", min(w, d) - 4, 0, 2, min(w, d) - 4, "trim")
    else:
        lw = leg + (1 if style == "chunky" else 0)
        _legs(k, w - 2 * ov, d - 2 * ov, h - t, lw, "legs")
        if style == "chunky":
            x, z = (w - 2 * ov) / 2 - lw / 2, (d - 2 * ov) / 2 - lw / 2
            for tag, zz in (("front", -z), ("back", z)):
                k.pair(f"foot_{tag}", [x - lw / 2 - 0.5, 0, zz - lw / 2 - 0.5], [x + lw / 2 + 0.5, 1, zz + lw / 2 + 0.5], "trim")
        if p["stretcher"]:
            k.cbox("stretcher", w - 2 * ov - 2 * lw, 2, 3, 1.0 * 2, "trim")
            k.pair("stretcher_side", [(w - 2 * ov) / 2 - lw, 2, -(d - 2 * ov) / 2 + lw], [(w - 2 * ov) / 2 - lw / 2 - 0.5, 3, (d - 2 * ov) / 2 - lw], "trim")
    if p["apron"]:
        k.cbox("apron_front", w - 2 * ov - 2, h - t - 2, h - t, 1, "trim", z=-(d / 2 - ov - 1))
        k.cbox("apron_back", w - 2 * ov - 2, h - t - 2, h - t, 1, "trim", z=d / 2 - ov - 1)
    if p["cloth"]:
        k.cbox("runner", min(6, w - 4), h, h + 0.5 * 2, d + 1, "cloth")
    item = p["item"]
    if item == "candle":
        k.cbox("candle", 2, h, h + 4, 2, "cloth")
        k.cbox("flame", 1, h + 4, h + 5, 1, k.mat("flame", "glow", "#ffc04a"))
    elif item == "bowl":
        k.cbox("bowl", 6, h, h + 2, 6, "trim")
        k.cbox("fruit", 4, h + 2, h + 3, 4, "cloth")
    elif item == "book":
        k.cbox("book", 4, h, h + 1, 5, "cloth", x=w / 4)
    return k.spec()


def build_chair(p, r, name):
    k = Kit(name, "furniture", r)
    style = p["style"]
    w = p["width"]
    sh = p["seat_h"]
    d = w if style != "bench" else max(8, w // 2)
    if style == "bench":
        w = max(w, 24)
    elif style == "stool":
        w = d = min(w, 10)
    leg = 2
    padded = style in ("armchair", "throne") or p["cushion"]
    _legs(k, w, d, sh - 2, leg if style != "armchair" else 2, "frame")
    k.cbox("seat", w, sh - 2, sh, d, "frame")
    if padded:
        k.cbox("cushion", w - 2 if style != "armchair" else w - 4, sh, sh + 2, d - 2, "cushion", z=-0.0 if style == "armchair" else 0,
               decals=[("up", "button", r["trim"]["color"])] if p["tufted"] else None)
    if style == "stool":
        for zs in (-1, 1):
            k.cbox(f"rung{zs + 1}", w - 2 * leg, 3, 4, 1, "frame", z=zs * (d / 2 - leg / 2))
        return k.spec()
    bh = p["back_h"] if style != "throne" else max(p["back_h"], 18)
    bh = min(bh, 32 - sh - (5 if style == "throne" else 0))
    bt = 2 if style != "armchair" else 3
    back_y0 = sh
    if style == "simple" or style == "bench":
        k.pair("back_post", [w / 2 - leg, back_y0, d / 2 - leg], [w / 2, back_y0 + bh, d / 2], "frame")
        n = p["slats"]
        if n:
            for i in range(n):
                y = back_y0 + 2 + i * max(2, (bh - 3) / max(1, n))
                k.cbox(f"slat{i}", w - 2 * leg, y, min(y + 2, back_y0 + bh), 1.0 * 1, "frame", z=d / 2 - leg / 2)
        else:
            k.cbox("back_panel", w - 2 * leg, back_y0 + 2, back_y0 + bh, 1, "frame", z=d / 2 - leg / 2)
        k.cbox("back_rail", w, back_y0 + bh - 2, back_y0 + bh, leg, "frame", z=d / 2 - leg / 2)
        if p["cushion"]:
            k.cbox("back_cushion", w - 2 * leg - 2, back_y0 + 3, back_y0 + bh - 2, 1, "cushion", z=d / 2 - leg - 0.5)
    else:  # armchair / throne: one padded back block with a frame
        k.cbox("back_frame", w, back_y0, back_y0 + bh, bt, "frame", z=d / 2 - bt / 2)
        k.cbox("back_pad", w - 4, back_y0 + 2, back_y0 + bh - 2, 1, "cushion", z=d / 2 - bt - 0.5,
               decals=[("north", "button", r["trim"]["color"])] if p["tufted"] else None)
        if style == "throne":
            k.cbox("crest", w - 4, back_y0 + bh, back_y0 + bh + 3, bt, "trim", z=d / 2 - bt / 2)
            k.cbox("crest_top", 2, back_y0 + bh + 3, back_y0 + bh + 5, bt, "trim", z=d / 2 - bt / 2)
    arms = p["arms"] or style in ("armchair", "throne")
    if arms:
        aw = 3 if style == "armchair" else 2
        k.pair("arm", [w / 2 - aw, sh, -d / 2], [w / 2, sh + 5, d / 2 - (bt if style != "simple" else leg)], "cushion" if style == "armchair" else "frame")
        k.pair("arm_cap", [w / 2 - aw - 0.5, sh + 5, -d / 2 - 0.5], [w / 2 + 0.5, sh + 6, d / 2 - (bt if style != "simple" else leg)], "trim")
    if p["trim"]:
        k.cbox("seat_trim", w + 1, sh - 2, sh - 1, d + 1, "trim")
        if style in ("armchair", "throne"):
            k.cbox("back_trim", w + 1, back_y0 + bh - 1, back_y0 + bh, bt + 1, "trim", z=d / 2 - bt / 2)
    return k.spec()


BOOK_ROWS = (3, 4, 2, 4, 3, 2, 4, 3)


def build_shelf(p, r, name):
    k = Kit(name, "furniture", r)
    w, h, d = p["width"], p["height"], p["depth"]
    t = 1 if p["kind"] != "cabinet" else 2
    k.pair("side", [w / 2 - t, 0, -d / 2], [w / 2, h, d / 2], "frame")
    k.cbox("top", w + 2, h, h + 1, d + 1, "frame", z=-0.5 * 0)
    k.cbox("plinth", w - 2 * t, 0, 1, d, "frame")
    k.cbox("back", w - 2 * t, 1, h, 1, "back", z=d / 2 - 0.5)
    n = p["shelves"]
    doors = p["doors"]
    door_top = 0 if doors == "none" else (h if doors == "full" else round(h * 0.4))
    gap = (h - 1) / (n + 1)
    books = ["book_a", "book_b", "book_c"]
    bi = 0
    for i in range(n + 1):
        y = 1 + i * gap
        if i > 0:
            k.cbox(f"shelf{i}", w - 2 * t, y - 1, y, d - 1, "frame", z=-0.5)
        top_y = 1 + (i + 1) * gap - 1
        if y < door_top or not p["books"] or p["kind"] == "dresser":
            continue
        x = -w / 2 + t
        j = 0
        while x < w / 2 - t - 1:
            bw = 1 if (bi + j) % 3 else 2
            bh = min(top_y - y - 0.5, BOOK_ROWS[(bi + j) % len(BOOK_ROWS)] + (gap - 6 if gap > 6 else 0))
            if (bi + j) % 7 == 6:
                x += 1  # small gap
                j += 1
                continue
            bh = max(2, bh)
            k.box(f"book{i}_{j}", [x, y, -d / 2 + 1], [min(x + bw, w / 2 - t), y + bh, d / 2 - 1], books[(bi + j) % 3])
            x += bw
            j += 1
        bi += 3
    if doors != "none" or p["kind"] == "dresser":
        top = door_top if p["kind"] != "dresser" else h
        if p["kind"] == "dresser":
            rows = max(2, n)
            for i in range(rows):
                y0 = 1 + i * (h - 1) / rows
                k.cbox(f"drawer{i}", w - 2 * t - 1, y0 + 0.5, y0 + (h - 1) / rows - 0.5, 1, "back", z=-d / 2 + 0.5)
                k.cbox(f"handle{i}", 2, y0 + (h - 1) / rows / 2 - 0.5, y0 + (h - 1) / rows / 2 + 0.5, 1, "accent", z=-d / 2 - 0.5)
        else:
            dw = (w - 2 * t) / 2
            for s, xs in ((0, -1), (1, 1)):
                x0 = 0 if xs > 0 else -dw
                k.box(f"door{s}", [x0 + 0.0, 1, -d / 2], [x0 + dw, top, -d / 2 + 1], "back",
                      decals=[("north", "border", r["frame"]["color"])])
                k.box(f"knob{s}", [xs * 1.0 - (0 if xs > 0 else 1), top / 2, -d / 2 - 1], [xs * 1.0 + (1 if xs > 0 else 0), top / 2 + 1, -d / 2], "accent")
    return k.spec()


def build_bed(p, r, name):
    k = Kit(name, "furniture", r)
    w = 16 if p["size"] == "single" else 32
    L = p["length"]
    fh = p["frame_h"]
    mh = 3
    z0, z1 = -L / 2, L / 2  # headboard at +z (back), foot towards the front
    _legs(k, w, L, fh, 2, "frame", prefix="post")
    k.cbox("frame_base", w, fh - 2, fh, L, "frame")
    k.cbox("sheet", w - 2, fh, fh + mh, L - 2, "sheet")
    qz0, qz1 = z0 + 1, z1 - 7
    qy = fh + mh
    if p["quilt"] == "patchwork":
        cols = max(2, round((w - 2) / 4))
        rows = max(2, round((qz1 - qz0) / 4))
        cw, rz = (w + 0) / cols, (qz1 - qz0) / rows
        for i in range(cols):
            for j in range(rows):
                k.box(f"patch{i}_{j}", [-w / 2 + i * cw, qy - 1, qz0 + j * rz], [-w / 2 + (i + 1) * cw, qy + 1, qz0 + (j + 1) * rz],
                      "quilt" if (i + j) % 2 == 0 else ("quilt2" if (i + 2 * j) % 3 else "quilt3"))
        k.cbox("quilt_fold", w, qy - 1, qy + 1.0 * 1.5, 2, "sheet", z=qz1 + 1)
    else:
        k.box("quilt", [-w / 2, qy - 1, qz0], [w / 2, qy + 1, qz1], "quilt",
              decals=[("up", "stripe", r["quilt2"]["color"])] if p["quilt"] == "striped" else None)
        k.box("quilt_fold", [-w / 2, qy - 1, qz1], [w / 2, qy + 1.0 * 1.5, qz1 + 2], "sheet")
    k.pair("quilt_hang", [w / 2, fh - 1, qz0], [w / 2 + 1, qy + 1, qz1], "quilt")
    k.box("quilt_hang_foot", [-w / 2 - 1, fh - 1, qz0 - 1], [w / 2 + 1, qy + 1, qz0], "quilt")
    n = 2 if p["size"] == "double" else 1
    pw = (w - 4) / n
    for i in range(n):
        x0 = -w / 2 + 2 + i * pw
        k.box(f"pillow{i}", [x0 + 0.5, qy, z1 - 5], [x0 + pw - 0.5, qy + 2, z1 - 1.0], "pillow")
    hb = p["headboard_h"]
    k.cbox("headboard", w + 2, 0, fh + hb, 2, "frame", z=z1 + 1, decals=[("north", "border", None)])
    if p["posts"]:
        k.pair("bed_post", [w / 2 + 0.0, 0, z1], [w / 2 + 2, fh + hb + 2, z1 + 2], "frame")
        k.pair("post_cap", [w / 2 - 0.5 + 0.5, fh + hb + 2, z1 - 0.5 + 0.5], [w / 2 + 2, fh + hb + 3, z1 + 2], "accent")
    if p["footboard"]:
        k.cbox("footboard", w + 2, 0, fh + mh + 2, 2, "frame", z=z0 - 1)
    return k.spec()


def build_chest(p, r, name):
    k = Kit(name, "block", r, density=2)
    w, h, d = p["width"], p["height"], p["depth"]
    lid = p["lid_h"]
    k.cbox("base", w, 0, h - lid, d, "wood")
    k.cbox("lid", w, h - lid, h, d, "wood")
    if p["bands"]:
        for i, x in enumerate((-w / 2 + 2.5, w / 2 - 2.5)):
            k.cbox(f"band{i}", 1.5, -0.0, h + 0.5, d + 0.5, "metal", x=x)
    if p["corners"]:
        for sx in (-1, 1):
            for sz in (-1, 1):
                k.box(f"corner{sx + 1}{sz + 1}", [sx * (w / 2 + 0.5) - (0 if sx > 0 else -2), 0, sz * (d / 2 + 0.5) - (0 if sz > 0 else -2)],
                      [sx * (w / 2 + 0.5) - (2 if sx > 0 else 0), 2, sz * (d / 2 + 0.5) - (2 if sz > 0 else 0)], "metal")
                k.box(f"cornert{sx + 1}{sz + 1}", [sx * (w / 2 + 0.5) - (0 if sx > 0 else -2), h - 1.5, sz * (d / 2 + 0.5) - (0 if sz > 0 else -2)],
                      [sx * (w / 2 + 0.5) - (2 if sx > 0 else 0), h + 0.5, sz * (d / 2 + 0.5) - (2 if sz > 0 else 0)], "metal")
    k.cbox("rim", w + 0.5, h - lid - 0.5, h - lid + 0.5, d + 0.5, "metal")
    if p["lock"] != "none":
        k.box("lock", [-1.5, h - lid - 2, -d / 2 - 1], [1.5, h - lid + 1.5, -d / 2], "lock",
              decals=[("north", "keyhole", None)] if p["lock"] == "keyhole" else None)
    if p["feet"]:
        _legs(k, w - 1, d - 1, 0.5 * 2, 2, "metal", prefix="foot")
        for q in k.parts:
            if q["name"] in ("base",) or q["name"].startswith(("band", "corner", "lid", "rim", "lock", "cornert")):
                q["from"][1] += 1
                q["to"][1] += 1
    return k.spec()


def build_stall(p, r, name):
    k = Kit(name, "furniture", r)
    w, d, ch = p["width"], p["depth"], p["counter_h"]
    top = ch + p["roof_h"]
    k.cbox("counter", w, 0, ch - 1, d - 4, "wood", z=-2)
    k.cbox("counter_top", w + 2, ch - 1, ch, d - 2, "counter", z=-2)
    k.cbox("counter_panel", w - 4, 2, ch - 3, 1, "counter", z=-d / 2 - 0.5,
           decals=[("north", "planks_cross", None)])
    posts = [(-w / 2, -d / 2 - 1), (w / 2 - 2, -d / 2 - 1), (-w / 2, d / 2 - 2), (w / 2 - 2, d / 2 - 2)]
    if p["posts"] == "2":
        posts = posts[2:]
    for i, (x, z) in enumerate(posts):
        k.box(f"post{i}", [x, 0, z], [x + 2, top, z + 2], "wood")
    n = max(3, round(w / 4))
    sw = (w + 4) / n
    roof = p["roof"]
    for i in range(n):
        x0 = -w / 2 - 2 + i * sw
        mat = "cloth_a" if i % 2 == 0 else "cloth_b"
        if roof == "striped_awning":
            k.box(f"awning{i}", [x0, top, -d / 2 - 4], [x0 + sw, top + 1, d / 2 - 2], mat)
            k.box(f"awning_up{i}", [x0, top + 1, -d / 2 + 2], [x0 + sw, top + 2, d / 2 - 2], mat)
            k.box(f"valance{i}", [x0, top - 2, -d / 2 - 4], [x0 + sw, top, -d / 2 - 3], mat)
        else:
            k.box(f"roof{i}", [x0, top, -d / 2 - 2], [x0 + sw, top + 1, d / 2 + 1], mat)
    goods = p["goods"]
    if goods != "none":
        gx = -w / 2 + 2
        i = 0
        while gx + 4 <= w / 2 - 2:
            if goods == "crates":
                k.box(f"crate{i}", [gx, ch, -d / 2 + 1], [gx + 4, ch + 3, -d / 2 + 5], "wood")
                k.box(f"fill{i}", [gx + 0.0 + 1, ch + 3, -d / 2 + 2], [gx + 3, ch + 4, -d / 2 + 4], "goods_a" if i % 2 == 0 else "goods_b")
            else:
                k.box(f"good{i}", [gx, ch, -d / 2 + 1], [gx + 3, ch + 2, -d / 2 + 4], "goods_a" if i % 2 == 0 else "goods_b")
                k.box(f"good_top{i}", [gx + 1, ch + 2, -d / 2 + 2], [gx + 2, ch + 3, -d / 2 + 3], "goods_b" if i % 2 == 0 else "goods_a")
            gx += 5
            i += 1
    if p["sign"]:
        k.cbox("sign", min(w - 6, 14), top - 4, top - 1, 1, "counter", z=-d / 2 - 1, decals=[("north", "border", None)])
    return k.spec()


# ------------------------------------------------------------------------------------------------ blocks
def build_lantern(p, r, name):
    k = Kit(name, "block", r, density=2)
    s = p["size"]
    hgt = s + (4 if p["shape"] == "tall" else 2)
    y0 = 0.0
    if p["hanging"]:
        y0 = max(0.0, 16 - p["chain_len"] - hgt - 2)
    k.cbox("base", s, y0, y0 + 1.5, s, "metal")
    k.cbox("base_rim", s - 1, y0 + 1.5, y0 + 2, s - 1, k.tone("metal", 0.8))
    cy0, cy1 = y0 + 2, y0 + 2 + hgt - 2
    for sx in (-1, 1):
        for sz in (-1, 1):
            k.box(f"bar{sx + 1}{sz + 1}", [sx * s / 2 - (0 if sx > 0 else -1), cy0, sz * s / 2 - (0 if sz > 0 else -1)],
                  [sx * s / 2 - (1 if sx > 0 else 0), cy1, sz * s / 2 - (1 if sz > 0 else 0)], "metal")
    if p["glass"]:
        k.cbox("glass", s - 1, cy0, cy1, s - 1, "glass")
    light = p["light"]
    lw = max(1.5, round(s / 4 * 2) / 2)
    if light == "candle":
        k.cbox("candle", lw, cy0, cy0 + hgt * 0.45, lw, "candle")
        k.cbox("wick", 0.5, cy0 + hgt * 0.45, cy0 + hgt * 0.45 + 0.5, 0.5, k.tone("candle", 0.35, "plain"))
        k.cbox("flame", 1, cy0 + hgt * 0.45 + 0.5, cy0 + hgt * 0.45 + 2, 1, "light")
    elif light == "flame":
        k.cbox("flame", lw + 1, cy0, cy0 + hgt * 0.5, lw + 1, "light")
        k.cbox("flame_tip", lw - 0.5, cy0 + hgt * 0.5, cy0 + hgt * 0.7, lw - 0.5, k.tone("light", 1.15))
    elif light == "crystal":
        k.cbox("crystal", lw + 0.5, cy0, cy0 + hgt * 0.6, lw + 0.5, "light", rot=[0, 45, 0])
    k.cbox("cap", s, cy1, cy1 + 1, s, "metal")
    roof = p["roof"]
    ty = cy1 + 1
    if roof == "pyramid":
        k.cbox("roof1", s - 1.0, ty, ty + 1, s - 1.0, "metal")
        k.cbox("roof2", s - 3, ty + 1, ty + 2, s - 3, "metal")
        ty += 2
    elif roof == "dome":
        k.cbox("dome", s - 2, ty, ty + 1.5, s - 2, "metal")
        ty += 1.5
    k.cbox("knob", 2, ty, ty + 1, 2, k.tone("metal", 0.8))
    ty += 1
    if p["hanging"]:
        k.cbox("ring", 3, ty, ty + 2, 1, "chain")
        y = ty + 1
        i = 0
        while y < 16:
            k.cbox(f"chain{i}", 1 if i % 2 == 0 else 2, y, min(16, y + 2), 2 if i % 2 == 0 else 1, "chain")
            y += 1.5
            i += 1
        k.cbox("hook", 4, 15, 16, 4, "chain")
    return k.spec()


def build_vessel(p, r, name):
    k = Kit(name, "block", r, density=2)
    shape, sup = p["shape"], p["support"]
    w = p["width"]
    hgt = p["height"]
    t = 1.5 if shape != "bowl" else 1
    sup_h = {"none": 0, "legs3": 2, "legs4": 2, "pedestal": max(4, 14 - hgt - 2), "ring_base": 1}[sup]
    if sup == "pedestal":
        pw = max(3, round(w * 0.3))
        k.cbox("foot", pw + 4, 0, 1.5, pw + 4, "support")
        k.cbox("stem", pw, 1.5, sup_h, pw, "support", decals=[("north", "border", None)])
        k.cbox("collar", pw + 2, sup_h - 1, sup_h, pw + 2, "support")
    elif sup in ("legs3", "legs4"):
        pts = [(-1, -1), (1, -1), (0, 1)] if sup == "legs3" else [(-1, -1), (1, -1), (-1, 1), (1, 1)]
        for i, (sx, sz) in enumerate(pts):
            x, z = sx * (w / 2 - 2), sz * (w / 2 - 2)
            k.cbox(f"leg{i}", 2, 0, sup_h + 1, 2, "support", x=x, z=z)
    elif sup == "ring_base":
        k.cbox("ring_base", w - 2, 0, 1, w - 2, "support")
    y0 = sup_h
    if shape == "cauldron" or shape == "pot":
        k.cbox("bottom", w - 2, y0, y0 + 1.5, w - 2, "body")
        y0b = y0 + 1.0
    else:
        k.cbox("bottom", w, y0, y0 + 1.0, w, "body")
        y0b = y0
    top = y0 + hgt
    belly = 1 if shape in ("cauldron", "pot") else 0
    # four walls around a hollow centre
    k.box("wall_n", [-w / 2, y0b, -w / 2], [w / 2, top, -w / 2 + t], "body")
    k.box("wall_s", [-w / 2, y0b, w / 2 - t], [w / 2, top, w / 2], "body")
    k.pair("wall_e", [w / 2 - t, y0b, -w / 2 + t], [w / 2, top, w / 2 - t], "body")
    if belly:
        bh = max(2, hgt // 2)
        k.cbox("belly_n", w - 2, y0 + 2, y0 + 2 + bh, 1, "body", z=-w / 2 - 0.5)
        k.cbox("belly_s", w - 2, y0 + 2, y0 + 2 + bh, 1, "body", z=w / 2 + 0.5)
        k.pair("belly_e", [w / 2, y0 + 2, -w / 2 + 1], [w / 2 + 1, y0 + 2 + bh, w / 2 - 1], "body")
    if p["rim"]:
        k.box("rim_n", [-w / 2 - 0.5, top, -w / 2 - 0.5], [w / 2 + 0.5, top + 1, -w / 2 + t], "rim")
        k.box("rim_s", [-w / 2 - 0.5, top, w / 2 - t], [w / 2 + 0.5, top + 1, w / 2 + 0.5], "rim")
        k.pair("rim_e", [w / 2 - t, top, -w / 2 + t], [w / 2 + 0.5, top + 1, w / 2 - t], "rim")
    liq = p["liquid"]
    if liq != "none":
        ly = y0b + max(1.0, (top - y0b) * p["level"])
        k.cbox("liquid", w - 2 * t, y0b, ly, w - 2 * t, "liquid")
        if p["bubbles"]:
            for i, (x, z) in enumerate(((-1.5, -1), (1.5, 1.5), (0.5, -2.5))):
                k.cbox(f"bubble{i}", 1, ly, ly + 1, 1, k.tone("liquid", 1.25), x=x * w / 10, z=z * w / 10)
            k.cbox("bubble_big", 1.5, ly, ly + 1.5, 1.5, k.tone("liquid", 1.15), x=-w / 6, z=w / 8)
    if p["handles"]:
        k.pair("handle", [w / 2, top - 3, -1.5], [w / 2 + 1.5, top - 1, 1.5], "rim")
    if p["moss"]:
        k.box("moss_a", [-w / 2 - 0.5, top - 2, -w / 2 - 0.5], [-w / 2 + 3, top + 1.5, -w / 2 + 2], "moss")
        k.box("moss_b", [w / 2 - 4, y0 - 0.5, w / 2 - 2], [w / 2 + 0.5, y0 + 2, w / 2 + 0.5], "moss")
        if sup == "pedestal":
            k.box("moss_c", [-2.5, 0, -3.5], [1, 2.5, -1.5], "moss")
    return k.spec()


def build_box_block(p, r, name):
    k = Kit(name, "block", r, density=2)
    kind = p["kind"]
    w, h = p["width"], p["height"]
    y0 = 1.0 if p["feet"] else 0.0
    if p["feet"]:
        for i, (sx, sz) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
            k.cbox(f"foot{i}", 2, 0, 1, 2, "trim", x=sx * (w / 2 - 1.5), z=sz * (w / 2 - 1.5))
    body = k.cbox("body", w, y0, h, w, "body")
    del body
    if kind == "hive":
        for i, y in enumerate((y0 + h * 0.33, y0 + h * 0.66)):
            k.cbox(f"slat{i}", w + 1, y - 0.5, y + 0.5, w + 1, "trim")
    else:
        k.cbox("frame_bottom", w + 1, y0, y0 + 1, w + 1, "trim")
        k.cbox("frame_top", w + 1, h - 1, h, w + 1, "trim")
        for sx in (-1, 1):
            for sz in (-1, 1):
                k.box(f"edge{sx + 1}{sz + 1}", [sx * (w / 2 + 0.5) - (0 if sx > 0 else -1), y0, sz * (w / 2 + 0.5) - (0 if sz > 0 else -1)],
                      [sx * (w / 2 + 0.5) - (1 if sx > 0 else 0), h, sz * (w / 2 + 0.5) - (1 if sz > 0 else 0)], "trim")
    if p["roof"]:
        k.cbox("roof", w + 2, h, h + 1.5, w + 2, "trim")
        k.cbox("roof_cap", w - 2, h + 1.5, h + 2.5, w - 2, k.tone("trim", 0.85))
    if p["entrance"]:
        ey = y0 + (h - y0) * 0.22
        k.box("entrance", [-3, ey, -w / 2 - 0.5], [3, ey + 1.5, -w / 2], "dark")
        k.box("landing", [-3.5, ey - 1, -w / 2 - 2], [3.5, ey, -w / 2], "trim")
        if p["drips"]:
            for i, (x, ln) in enumerate(((-2.5, 3), (0.5, 1.5), (2.0, 2.5))):
                k.box(f"drip{i}", [x, ey - 1 - ln, -w / 2 - 2], [x + 1, ey - 1, -w / 2 - 1], "detail")
            k.box("drip_pool", [-3, y0, -w / 2 - 2.5], [1.5, y0 + 0.5, -w / 2], "detail")
            k.box("honey_lip", [-3.5, ey, -w / 2 - 2], [3.5, ey + 0.5, -w / 2 - 1], "detail")
    for i in range(p["pipes"]):
        side = 1 if i % 2 == 0 else -1
        z = -w / 4 + (i // 2) * (w / 2)
        x = side * (w / 2 + 1)
        k.box(f"pipe{i}", [x - 1, y0 + 2, z - 1], [x + 1, h + 2, z + 1], "accent")
        k.box(f"pipe_joint{i}", [x - 1.5, y0 + 4, z - 1.5], [x + 1.5, y0 + 5, z + 1.5], k.tone("accent", 0.8))
        k.box(f"pipe_elbow{i}", [x - 1, h + 0.0, z - 1], [x - side * 3 + (1 if side > 0 else -1) * 0, h + 2, z + 1], "accent")
    if p["gear"]:
        gs = max(4, round(w * 0.4))
        cz = -w / 2 - 1
        cy = y0 + (h - y0) * 0.58
        k.box("gear", [-gs / 2, cy - gs / 2, cz], [gs / 2, cy + gs / 2, cz + 1], "accent")
        k.box("gear_45", [-gs / 2 + 0.5, cy - gs / 2 + 0.5, cz + 0.0], [gs / 2 - 0.5, cy + gs / 2 - 0.5, cz + 1], "accent",
              rot=[0, 0, 45], pivot=[0, cy, cz + 0.5])
        k.box("gear_hub", [-1, cy - 1, cz - 1], [1, cy + 1, cz], k.tone("accent", 0.7))
    if p["gauge"]:
        k.box("gauge", [w / 4 - 1.5, h - 4.5, -w / 2 - 0.5], [w / 4 + 1.5, h - 1.5, -w / 2], "detail",
              decals=[("north", "window", r["detail"]["color"])])
    if p["vents"]:
        for i in range(3):
            k.box(f"vent{i}", [-w / 2 + 2, y0 + 2 + i * 1.5, -w / 2 - 0.5], [-w / 2 + 5, y0 + 2.5 + i * 1.5, -w / 2], "dark")
    return k.spec()


def build_totem(p, r, name):
    k = Kit(name, "entity", r)
    pw, ph = p["pillar_w"], p["pillar_h"]
    y = 0
    base = None
    if p["base"] in ("slab", "stepped"):
        base = k.cbox("base", pw + 6, 0, 2, pw + 6, "stone", decals=[("north", "border", None)])
        y = 2
        if p["base"] == "stepped":
            k.cbox("step", pw + 3, 2, 3, pw + 3, k.tone("stone", 0.85), parent=base)
            y = 3
    root = k.cbox("pillar", pw, y, y + ph, pw, "stone", parent=base,
                  decals=[("north", "rune", r["glow"]["color"]), ("south", "rune", r["glow"]["color"])] if p["runes"] else None)
    k.cbox("pillar_cap", pw + 2, y + ph, y + ph + 1, pw + 2, k.tone("stone", 0.85), parent=root)
    top_y = y + ph + 1
    gap = 2 if p["floating"] else 0
    cy = top_y + gap
    cs = p["top_size"]
    topname = p["top"]
    if topname == "crystal":
        top = k.cbox("crystal", cs, cy, cy + cs * 1.6, cs, "crystal", parent=root, pivot=[0, cy, 0], rot=[0, 45, 0])
        k.cbox("crystal_tip", cs - 2, cy + cs * 1.6, cy + cs * 1.6 + 2, cs - 2, k.tone("crystal", 1.2), parent=top)
        k.cbox("crystal_low", cs - 2, cy - 1.0, cy, cs - 2, k.tone("crystal", 0.85), parent=top)
    elif topname == "orb":
        top = k.cbox("orb", cs, cy, cy + cs, cs, "glow", parent=root, pivot=[0, cy, 0])
        k.cbox("orb_band", cs + 1, cy + cs / 2 - 0.0 - 1, cy + cs / 2, cs + 1, "crystal", parent=top)
    elif topname == "flame":
        top = k.cbox("flame", cs, cy, cy + cs, cs, "glow", parent=root, pivot=[0, cy, 0])
        k.cbox("flame_tip", cs - 2, cy + cs, cy + cs + 2, cs - 2, k.tone("glow", 1.15), parent=top)
    else:
        top = k.cbox("rune_stone", cs, cy, cy + cs, cs, "stone", parent=root, pivot=[0, cy, 0],
                     decals=[("north", "rune", r["glow"]["color"])])
    shards = []
    for i in range(p["shards"]):
        a = 2 * math.pi * i / p["shards"]
        rad = cs / 2 + 3
        x, z = math.cos(a) * rad, math.sin(a) * rad
        shards.append(k.cbox(f"shard{i}", 1.0 * 2, cy + 1 + (i % 2) * 2, cy + 4 + (i % 2) * 2, 2, "crystal", x=x, z=z, parent=top))
    if p["pillar_rings"]:
        k.cbox("ring_low", pw + 1, y + 1, y + 2, pw + 1, "crystal", parent=root)
        k.cbox("ring_high", pw + 1, y + ph - 2, y + ph - 1, pw + 1, "crystal", parent=root)
    idle = {top: {"position": {"0": [0, 0, 0], "1": [0, 1.5, 0], "2": [0, 0, 0]},
                  "rotation": {"0": [0, 0, 0], "1": [0, 90, 0], "2": [0, 180, 0]}}}
    return k.spec([_anim("idle", 2.0, idle), _anim("bob", 2.0, idle)])


def build_plant(p, r, name):
    k = Kit(name, "block", r, density=2)
    pot = p["pot"]
    y = 0
    if pot != "none":
        pw = p["pot_w"]
        k.cbox("pot", pw, 0, p["pot_h"], pw, "pot")
        k.cbox("pot_rim", pw + 1, p["pot_h"] - 1, p["pot_h"], pw + 1, k.tone("pot", 0.85))
        k.cbox("soil", pw - 1, p["pot_h"], p["pot_h"] + 0.5, pw - 1, "soil")
        y = p["pot_h"]
    sh = p["stem_h"]
    k.cbox("stem", 1, y, y + sh, 1, "stem")
    form = p["form"]
    if form in ("bush", "tree"):
        cw = p["crown_w"]
        k.cbox("crown", cw, y + sh, y + sh + cw * 0.8, cw, "leaves")
        k.cbox("crown_top", cw - 3, y + sh + cw * 0.8, y + sh + cw * 0.8 + 2, cw - 3, k.tone("leaves", 1.1))
        k.cbox("crown_low", cw - 2, y + sh - 1, y + sh, cw - 2, k.tone("leaves", 0.85))
    elif form == "flower":
        k.cbox("bloom", 3, y + sh, y + sh + 1.5, 3, "bloom")
        k.cbox("bloom_x", 5, y + sh + 0.5, y + sh + 1, 1, "bloom")
        k.cbox("bloom_z", 1, y + sh + 0.5, y + sh + 1, 5, "bloom")
        k.cbox("center", 1, y + sh + 1.5, y + sh + 2, 1, "accent")
    else:  # fern / succulent leaves fanning out
        for i, rot in enumerate((22.5, -22.5)):
            k.box(f"leaf{i}", [-3, y + sh * 0.4, -0.5], [3, y + sh * 0.4 + 0.5, 0.5], "leaves", rot=[0, 0, rot], pivot=[0, y + sh * 0.4, 0])
            k.box(f"leafz{i}", [-0.5, y + sh * 0.7, -3], [0.5, y + sh * 0.7 + 0.5, 3], "leaves", rot=[rot, 0, 0], pivot=[0, y + sh * 0.7, 0])
    if p["fruit"]:
        for i, (x, z) in enumerate(((-2, -2.5), (2.5, -1), (0, 2.5))):
            k.cbox(f"fruit{i}", 1.5, y + sh + 1, y + sh + 2.5, 1.5, "accent", x=x, z=z)
    return k.spec()


def build_boat(p, r, name):
    k = Kit(name, "entity", r)
    L, W = p["length"], p["width"]
    hh = p["hull_h"]
    t = 2
    bow = max(4, L // 5)
    hull = k.box("floor", [-W / 2 + t, 0, -L / 2 + bow], [W / 2 - t, t, L / 2 - t], "hull", pivot=[0, 0, 0])
    k.pair("side", [W / 2 - t, 0, -L / 2 + bow], [W / 2, hh, L / 2 - t], "hull", parent=hull)
    k.box("stern", [-W / 2, 0, L / 2 - t], [W / 2, hh, L / 2], "hull", parent=hull)
    # bow: two narrowing steps that meet at the front
    k.pair("bow_a", [W / 2 - t - 2, 0, -L / 2 + bow / 2], [W / 2 - 2, hh, -L / 2 + bow], "hull", parent=hull)
    k.box("bow_b", [-W / 2 + 4, 0, -L / 2], [W / 2 - 4, hh + 1, -L / 2 + bow / 2 + 1], "hull", parent=hull)
    k.box("bow_floor", [-W / 2 + t + 2, 0, -L / 2 + bow / 2], [W / 2 - t - 2, t, -L / 2 + bow], "hull", parent=hull)
    k.box("keel", [-1, -1, -L / 2 + 1], [1, 0, L / 2 - 1], k.tone("hull", 0.75), parent=hull)
    k.pair("gunwale", [W / 2 - t - 0.0, hh, -L / 2 + bow], [W / 2 + 0.0, hh + 1, L / 2], "trim", parent=hull)
    n = p["seats"]
    for i in range(n):
        z = -L / 2 + bow + (L - bow - t) * (i + 1) / (n + 1) - 1
        k.box(f"seat{i}", [-W / 2 + t, hh - 2, z], [W / 2 - t, hh - 1, z + 3], "trim", parent=hull)
    oars = []
    if p["oars"]:
        zc = -L / 2 + bow + (L - bow - t) * 0.5
        a, b = k.pair("oar", [W / 2 - 2, hh + 1, zc - 0.5], [W / 2 + 12, hh + 2, zc + 0.5], "oar", parent=hull,
                      pivot=[W / 2, hh + 1.5, zc], rot=[0, 15, -22.5])
        k.pair("oar_blade", [W / 2 + 9, hh + 0.5, zc - 1.5], [W / 2 + 14, hh + 2.5, zc + 1.5], "oar", parent=a)
        k.parts[-1]["parent"] = b
        k.pair("oarlock", [W / 2 - 1, hh + 1, zc - 1], [W / 2 + 0.0, hh + 2, zc + 1], "metal", parent=hull)
        oars = [a, b]
    anims = []
    if oars:
        row = {oars[0]: {"rotation": {"0": [0, 15, -22.5], "0.75": [0, -25, -10], "1.5": [0, 15, -22.5]}},
               oars[1]: {"rotation": {"0": [0, -15, 22.5], "0.75": [0, 25, 10], "1.5": [0, -15, 22.5]}}}
        anims.append(_anim("row", 1.5, row))
    anims.append(_anim("idle", 3.0, {hull: {"rotation": {"0": [0, 0, -2], "1.5": [0, 0, 2], "3": [0, 0, -2]}}}))
    return k.spec(anims)


# ------------------------------------------------------------------------------------------------ items
def build_tool(p, r, name):
    k = Kit(name, "item", r, density=2)
    head = p["head"]
    hl = min(p["handle_len"], 6) if head == "sword" else p["handle_len"]
    hw = 1.5
    k.cbox("handle", hw, 0, hl, hw, "handle")
    if p["grip_wrap"]:
        k.cbox("grip", hw + 0.5, 1, 1 + max(2, hl * 0.3), hw + 0.5, "grip")
    if p["pommel"]:
        k.cbox("pommel", hw + 1, 0, 1, hw + 1, "accent")
    hs = p["head_size"]
    top = hl
    gem = None
    if head == "pickaxe":
        k.cbox("head_core", 3, top - 1.5, top + 1.5, 2.5, "head")
        k.box("arm_l", [1.5, top - 1, -1], [1.5 + hs * 0.6, top + 1, 1], "head")
        k.box("arm_r", [-1.5 - hs * 0.6, top - 1, -1], [-1.5, top + 1, 1], "head")
        k.box("tip_l", [1.5 + hs * 0.6 - 0.5, top - 3, -0.75], [1.5 + hs * 0.6 + 1, top - 0.5, 0.75], "head")
        k.box("tip_r", [-1.5 - hs * 0.6 - 1, top - 3, -0.75], [-1.5 - hs * 0.6 + 0.5, top - 0.5, 0.75], "head")
        if p["gem"]:
            gem = k.cbox("gem", 1.5, top - 0.5, top + 1, 1, "gem", z=-1.25)
    elif head == "axe":
        k.box("blade", [hw / 2 - 0.5, top - hs * 0.9, -0.75], [hw / 2 + hs * 0.6, top + 0.5, 0.75], "head")
        k.box("edge", [hw / 2 + hs * 0.6, top - hs * 0.9 - 0.5, -0.5], [hw / 2 + hs * 0.6 + 1, top + 1, 0.5], k.tone("head", 1.2))
        k.box("poll", [-hw / 2 - 1.5, top - 2, -1], [hw / 2, top, 1], "head")
    elif head in ("hammer", "mace"):
        hx = hs if head == "hammer" else hs * 0.7
        k.cbox("head_block", hx, top - 1, top - 1 + hs * 0.6, hs * 0.55, "head")
        if p["bands"]:
            for i, x in enumerate((-hx / 2 + 1, hx / 2 - 1)):
                k.cbox(f"band{i}", 1, top - 1.5, top - 0.5 + hs * 0.6, hs * 0.55 + 1, "accent", x=x)
        k.cbox("socket", hw + 1, top - 2.5, top - 1, hw + 1, "accent")
        if head == "mace":
            for i, (x, y) in enumerate(((-hx / 2 - 1, 1), (hx / 2 + 1, 1), (0, hs * 0.6 + 0.5))):
                k.cbox(f"spike{i}", 1, top - 1 + y, top + y, 1, k.tone("head", 1.2), x=x)
    elif head == "sword":
        k.cbox("guard", hs, top, top + 1.5, 2, "accent")
        k.cbox("blade", 2.5, top + 1.5, top + 1.5 + hs * 1.6, 1, "head")
        k.cbox("blade_edge", 1, top + 1.5, top + 2.5 + hs * 1.6, 1.5, k.tone("head", 1.2))
        k.cbox("fuller", 0.5, top + 2.5, top + hs * 1.3, 1.5, k.tone("head", 0.8))
    elif head == "shovel":
        k.cbox("socket", hw + 1, top, top + 1.5, hw + 1, "head")
        k.cbox("blade", hs * 0.6, top + 1.5, top + 1.5 + hs * 0.8, 1, "head")
        k.cbox("blade_tip", hs * 0.6 - 1, top + 1.5 + hs * 0.8, top + 2.5 + hs * 0.8, 1, k.tone("head", 1.15))
    elif head in ("staff", "wand"):
        k.cbox("collar", hw + 1, top - 1, top, hw + 1, "accent")
        for i, (sx, sz) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
            k.box(f"prong{i}", [sx * (hs / 2 - 0.5) - 0.5, top, sz * 1.0 - 0.5], [sx * (hs / 2 - 0.5) + 0.5, top + hs * 0.7 + 1, sz * 1.0 + 0.5], "accent")
        k.cbox("cradle", hs, top - 0.0, top + 1, 3, "accent")
        gem = k.cbox("gem", hs - 2, top + 1, top + 1 + hs * 0.9, hs - 2 if hs > 4 else 2, "gem")
        k.cbox("gem_tip", max(1, hs - 4), top + 1 + hs * 0.9, top + 2 + hs * 0.9, max(1, hs - 4), k.tone("gem", 1.2))
    elif head == "spear":
        k.cbox("socket", hw + 1, top, top + 1.5, hw + 1, "accent")
        k.cbox("tip", 3, top + 1.5, top + 1.5 + hs * 0.8, 1, "head")
        k.cbox("point", 1, top + 1.5 + hs * 0.8, top + 2.5 + hs * 0.8, 1, k.tone("head", 1.2))
    elif head == "hoe":
        k.box("hoe_arm", [-hw / 2, top - 1.5, -0.75], [hw / 2 + hs * 0.5, top, 0.75], "head")
        k.box("hoe_blade", [hw / 2 + hs * 0.5 - 1.5, top - 3, -1], [hw / 2 + hs * 0.5, top, 1], "head")
    if p["bands"] and head not in ("hammer", "mace"):
        k.cbox("band_mid", hw + 0.5, hl * 0.55, hl * 0.55 + 1, hw + 0.5, "accent")
    del gem
    return k.spec()


def build_bottle(p, r, name):
    k = Kit(name, "item", r, density=2)
    shape = p["shape"]
    w = p["size"]
    h = {"round": w, "square": w, "tall": w * 1.6, "flask": w * 0.9}[shape]
    k.cbox("glass", w, 0, h, w if shape != "flask" else w * 0.7, "glass")
    if shape in ("round", "flask"):
        k.cbox("shoulder", w - 2, h, h + 1, (w if shape != "flask" else w * 0.7) - 2, "glass")
        h += 1
    lvl = max(1.0, (h - 1) * p["level"])
    k.cbox("liquid", w - 1, 0.5, 0.5 + lvl, (w if shape != "flask" else w * 0.7) - 1, "liquid")
    if p["bubbles"]:
        k.cbox("bubble", 1, 0.5 + lvl, 1.5 + lvl, 1, k.tone("liquid", 1.3), x=-w / 6)
    nl = p["neck_len"]
    k.cbox("neck", max(2, round(w * 0.35)), h, h + nl, max(2, round(w * 0.35)), "glass")
    k.cbox("lip", max(2, round(w * 0.35)) + 1, h + nl - 0.5, h + nl, max(2, round(w * 0.35)) + 1, "glass")
    if p["cork"]:
        k.cbox("cork", max(2, round(w * 0.35)) - 0.5, h + nl - 1, h + nl + 1.5, max(2, round(w * 0.35)) - 0.5, "cork")
    if p["label"]:
        k.box("label", [-w / 2 + 1, h * 0.3, -w / 2 - 0.5 * (1 if shape != "flask" else -0.0) - (0 if shape != "flask" else w * 0.0)],
              [w / 2 - 1, h * 0.6, -w / 2 + (0 if shape != "flask" else w * 0.15)], "label")
    return k.spec()


# ------------------------------------------------------------------------------------------------ armor
BONES = {"head": ([-4, 24, -4], [4, 32, 4]), "body": ([-4, 12, -2], [4, 24, 2]),
         "right_arm": ([-8, 12, -2], [-4, 24, 2]), "left_arm": ([4, 12, -2], [8, 24, 2]),
         "right_leg": ([-4, 0, -2], [0, 12, 2]), "left_leg": ([0, 0, -2], [4, 12, 2])}


def build_armor(p, r, name):
    k = Kit(name, "armor", r)
    for b, (lo, hi) in BONES.items():
        k.box(b, lo, hi, "stand", pivot=[(lo[0] + hi[0]) / 2, hi[1] if b != "head" else lo[1], 0])
    helm = p["helmet"]
    if helm != "none":
        hood = helm in ("hood", "leaf")
        k.box("helm", [-5, 25 if not hood else 24, -5], [5, 33, 5], "plate" if not hood else "under", parent="head",
              decals=[("north", "border", None)])
        if helm in ("plumed", "horned", "crown", "open"):
            k.box("helm_brow", [-5, 29, -6], [5, 30, -5], "trim", parent="head")
            if helm != "open":
                k.box("visor", [-4, 27, -6], [4, 29, -5], k.tone("plate", 0.55), parent="head")
                k.box("visor_low", [-4, 25, -6], [4, 27, -5], "plate", parent="head", decals=[("north", "spots", shade(r["plate"]["color"], 0.5))])
        else:
            k.box("helm_face", [-5, 24, -5], [5, 33, -4], "under", parent="head")
            k.box("helm_face_hole", [-3, 25, -6], [3, 30, -5], k.tone("stand", 0.5, "plain"), parent="head")
            k.parts[-2]["from"][2], k.parts[-2]["to"][2] = -6, -5
            k.parts[-2]["from"][1] = 30
        if helm == "plumed":
            k.box("plume_base", [-1, 33, -2], [1, 34, 2], "trim", parent="head")
            k.box("plume", [-1, 34, -3], [1, 38, 3], "plume", parent="head")
            k.box("plume_back", [-1, 32, 3], [1, 37, 7], "plume", parent="head")
        elif helm == "horned":
            k.pair("horn", [5, 29, -1], [8, 31, 1], "trim", parent="head")
            k.pair("horn_tip", [7, 31, -1], [8, 35, 1], "trim", parent="head")
        elif helm == "crown":
            for i, x in enumerate((-5, -1, 3)):
                k.box(f"crown_pt{i}", [x, 33, -5], [x + 2, 35, -4], "trim", parent="head")
        elif helm == "leaf":
            k.box("leaf_crest", [-3, 33, -4], [3, 35, 3], "plume", parent="head")
            k.pair("leaf_ear", [5, 29, -2], [7, 32, 1], "plume", parent="head")
    if p["chest"]:
        k.box("chestplate", [-5, 12, -3], [5, 24.5, 3], "plate", parent="body",
              decals=[("north", "border", r["trim"]["color"])] if p["trim"] else None)
        k.box("belt", [-5.5, 12, -3.5], [5.5, 14, 3.5], "under", parent="body")
        k.box("buckle", [-1, 12, -4], [1, 14, -3.5], "trim", parent="body")
        if p["emblem"]:
            k.box("emblem", [-1.5, 18, -3.5], [1.5, 21, -3], "trim", parent="body")
    pa = p["pauldrons"]
    if pa != "none":
        h = 4 if pa != "spiky" else 3
        k.box("pauldron_l", [3.5, 21, -3], [9, 21 + h, 3], "plate" if pa != "leaf" else "plume", parent="left_arm")
        k.box("pauldron_r", [-9, 21, -3], [-3.5, 21 + h, 3], "plate" if pa != "leaf" else "plume", parent="right_arm", mirror_of="pauldron_l")
        k.box("pauldron_trim_l", [3.5, 20, -3.5], [9.5, 21, 3.5], "trim", parent="left_arm")
        k.box("pauldron_trim_r", [-9.5, 20, -3.5], [-3.5, 21, 3.5], "trim", parent="right_arm", mirror_of="pauldron_trim_l")
        if pa == "spiky":
            k.box("spike_l", [6, 24, -1], [8, 27, 1], "trim", parent="left_arm")
            k.box("spike_r", [-8, 24, -1], [-6, 27, 1], "trim", parent="right_arm", mirror_of="spike_l")
    if p["gauntlets"]:
        k.box("gauntlet_l", [3.5, 12, -2.5], [8.5, 16, 2.5], "plate", parent="left_arm")
        k.box("gauntlet_r", [-8.5, 12, -2.5], [-3.5, 16, 2.5], "plate", parent="right_arm", mirror_of="gauntlet_l")
    if p["legs"]:
        k.box("tasset", [-5, 9, -3], [5, 12.5, 3], "plate", parent="body")
        k.box("greave_l", [-0.0, 4, -2.5], [4.5, 9, 2.5], "plate", parent="left_leg")
        k.box("greave_r", [-4.5, 4, -2.5], [0, 9, 2.5], "plate", parent="right_leg", mirror_of="greave_l")
    if p["boots"]:
        k.box("boot_l", [-0.0, 0, -3], [4.5, 4, 2.5], "under", parent="left_leg")
        k.box("boot_r", [-4.5, 0, -3], [0, 4, 2.5], "under", parent="right_leg", mirror_of="boot_l")
        k.box("boot_cuff_l", [-0.0, 3.5, -3], [5, 4.5, 3], "trim", parent="left_leg")
        k.box("boot_cuff_r", [-5, 3.5, -3], [0, 4.5, 3], "trim", parent="right_leg", mirror_of="boot_cuff_l")
    if p["cape"]:
        k.box("cape", [-4.5, 3, 2.5], [4.5, 24, 3.5], "under", parent="body", pivot=[0, 24, 3], rot=[8, 0, 0])
    if p["vines"]:
        k.box("vine_a", [-5.5, 14, -3.5], [-3.5, 24, -3], "plume", parent="body")
        k.box("vine_b", [2, 13, -3.5], [3.5, 20, -3], "plume", parent="body")
        k.box("vine_c", [4.5, 12, -2.5], [5, 18, 1], "plume", parent="body")
    walk = {"left_leg": _swing(25), "right_leg": _swing(25, phase=-1), "left_arm": _swing(20, phase=-1), "right_arm": _swing(20)}
    return k.spec([_anim("walk", 1.0, walk)])


# ------------------------------------------------------------------------------------------------ catalogue
DARK = "#2b2630"
TEMPLATES: dict[str, Template] = {}


def _t(name, summary, category, params, roles, build, keywords):
    TEMPLATES[name] = Template(name, summary, category, params, {k: Role(*v) for k, v in roles.items()},
                               lambda p, r, nm, _b=build: _b(p, r, nm), tuple(keywords))


_t("biped", "two-legged humanoid mob: villager, zombie, knight, golem, goblin, robot (build=golem for big golems)", "mob",
   {"build": E("normal", "normal", "stocky", "slim", "golem", "child"), "head_scale": P(N, 1.0, 0.75, 1.3),
    "arm_scale": P(N, 1.0, 0.7, 1.3), "leg_scale": P(N, 1.0, 0.6, 1.3),
    "hat": E("none", "none", "hair", "cap", "hood", "horns", "crown", "helmet"),
    "eyes": E("normal", "normal", "glow", "none"), "nose": P(B, False), "beard": P(B, False), "belt": P(B, False),
    "sleeves": P(B, True, doc="arms in torso colour with skin hands"), "moss": P(B, False, doc="moss patches (golems)")},
   {"skin": ("#c99a74", "skin", "head and hands"), "torso": ("#4e6e9a", "cloth"), "legs": ("#3b3f55", "cloth"),
    "feet": ("#4a3426", "leather"), "hair": ("#4a3122", "fur"), "accent": ("#c8a040", "gold"),
    "eye": ("#1c1a24", "plain", "eye colour"), "moss": ("#5a8a3a", "leaves")},
   build_biped, ("villager", "zombie", "knight", "golem", "humanoid", "goblin", "robot", "man", "woman", "skeleton", "guardian", "person"))
_t("quadruped", "four-legged animal: sheep, fox, cow, pig, wolf, cat, horse, deer, bear (fluffy=wool body)", "mob",
   {"body_len": P(I, 14, 6, 22), "body_w": P(I, 8, 4, 14), "body_h": P(I, 7, 3, 12), "leg_h": P(I, 6, 2, 14),
    "leg_w": P(I, 3, 2, 5), "head": P(I, 6, 4, 10), "snout_len": P(I, 2, 0, 6),
    "ears": E("pointy", "pointy", "floppy", "round", "long", "horns", "none"), "tail": E("short", "none", "short", "long", "bushy", "curly"),
    "fluffy": P(B, False, doc="thick wool coat (sheep)"), "neck": P(B, False, doc="raised neck (horse, deer, llama)"),
    "pattern": E("none", "none", "spots", "stripes", "belly"), "eyes": E("normal", "normal", "glow", "none")},
   {"body": ("#a0703c", "fur"), "head": ("#a0703c", "fur"), "legs": ("#8a5c30", "fur"), "paws": ("#3a2a22", "fur"),
    "snout": ("#e8dcc4", "fur"), "nose": ("#2a2226", "plain"), "tip": ("#ece4d4", "fur", "tail tip"),
    "pattern": ("#ece4d4", "fur"), "accent": ("#d8ccb0", "bone", "horns"), "eye": ("#1c1a24", "plain")},
   build_quadruped, ("sheep", "fox", "cow", "pig", "wolf", "dog", "cat", "horse", "deer", "bear", "goat", "lamb", "animal", "llama"))
_t("bird", "bird: penguin, owl (posture upright) or chicken, duck, parrot, crow (posture horizontal)", "mob",
   {"posture": E("horizontal", "upright", "horizontal"), "size": P(I, 6, 4, 12), "leg_h": P(I, 2, 0, 6),
    "beak_len": P(I, 2, 1, 4), "beak_wide": P(B, False, doc="duck bill"), "wing_scale": P(N, 0.8, 0.5, 1.2),
    "crest": E("none", "none", "tuft", "comb", "ears"), "tail": E("short", "none", "short", "fan", "long"),
    "belly": P(B, False, doc="light belly patch (penguin)"), "eyes": E("normal", "normal", "glow", "none")},
   {"body": ("#e8e2d4", "fur"), "head": ("#e8e2d4", "fur"), "belly": ("#f2ece0", "fur"), "wing": ("#d6cfc0", "fur"),
    "beak": ("#e8a838", "plain"), "feet": ("#e0902c", "plain"), "accent": ("#c83a30", "plain", "crest"),
    "eye": ("#1c1a24", "plain")},
   build_bird, ("bird", "penguin", "owl", "chicken", "duck", "parrot", "crow", "hen", "pigeon", "eagle"))
_t("frog", "small squat hopper: frog, toad, axolotl-like critter with big eyes", "mob",
   {"size": P(I, 8, 4, 12), "eye_size": P(I, 3, 2, 4), "back_leg": P(I, 4, 2, 6), "spots": P(B, False),
    "throat": P(B, False, doc="throat pouch")},
   {"skin": ("#5e9a3e", "skin"), "belly": ("#c8d890", "skin"), "mouth": ("#3a5a2a", "plain"),
    "eyeball": ("#e8e2c8", "plain"), "eye": ("#1c1a24", "plain", "pupils"), "pattern": ("#3e6e2a", "plain", "spots")},
   build_frog, ("frog", "toad", "axolotl", "newt"))
_t("arthropod", "many-legged critter: scorpion (pincers + stinger), spider, crab, beetle, ant", "mob",
   {"kind": E("scorpion", "scorpion", "spider", "crab", "beetle", "ant"), "body_len": P(I, 12, 6, 18), "body_w": P(I, 7, 4, 12),
    "segments": P(I, 3, 1, 5), "leg_pairs": P(I, 4, 2, 4), "leg_len": P(I, 5, 3, 8), "pincers": P(B, True),
    "stinger": P(B, True, doc="raised segmented tail"), "tail_segments": P(I, 5, 3, 6), "eyes": E("normal", "normal", "glow", "none")},
   {"shell": ("#c89a50", "scales"), "legs": ("#a87c3c", "scales"), "claw": ("#8a5a2a", "scales"), "eye": ("#1c1a24", "plain")},
   build_arthropod, ("scorpion", "spider", "crab", "beetle", "ant", "insect", "bug", "lobster"))
_t("fish", "fish or sea creature with fins and a tail", "mob",
   {"length": P(I, 10, 4, 20), "height": P(I, 5, 3, 10), "width": P(I, 3, 2, 6), "tail": P(I, 4, 2, 8),
    "fin": P(I, 2, 1, 5), "stripes": P(B, False)},
   {"body": ("#e07a3a", "scales"), "belly": ("#f0d8b0", "scales"), "fin": ("#d8603a", "scales"),
    "accent": ("#f2ece0", "plain"), "eye": ("#1c1a24", "plain")},
   build_fish, ("fish", "salmon", "cod", "shark", "koi", "carp"))
_t("table", "table or desk with legs: dining table, workbench, desk, side table", "furniture",
   {"width": P(I, 28, 10, 44), "depth": P(I, 16, 8, 30), "height": P(I, 13, 8, 18), "top_thick": P(I, 2, 1, 4),
    "leg": P(I, 3, 2, 5), "legs": E("straight", "straight", "chunky", "trestle", "pedestal"), "overhang": P(I, 1, 0, 3),
    "apron": P(B, True), "stretcher": P(B, False), "cloth": P(B, False, doc="table runner"),
    "item": E("none", "none", "candle", "bowl", "book")},
   {"top": ("#9a6a3a", "wood_planks"), "legs": ("#7a5230", "log"), "trim": ("#6a4428", "wood_planks"),
    "cloth": ("#a8403a", "cloth")},
   build_table, ("table", "desk", "workbench", "counter"))
_t("chair", "seat: chair, armchair, throne, stool, bench", "furniture",
   {"style": E("simple", "simple", "armchair", "throne", "stool", "bench"), "width": P(I, 12, 8, 20), "seat_h": P(I, 8, 5, 11),
    "back_h": P(I, 12, 6, 20), "slats": P(I, 3, 0, 4), "cushion": P(B, False), "arms": P(B, False),
    "trim": P(B, False, doc="gold/metal trim edges"), "tufted": P(B, False, doc="buttons on the cushions")},
   {"frame": ("#8a5a32", "wood_planks"), "cushion": ("#8a2a3a", "cloth"), "trim": ("#d4a840", "gold")},
   build_chair, ("chair", "armchair", "throne", "stool", "bench", "seat", "sofa"))
_t("shelf", "storage furniture: bookshelf, cabinet, open shelf, dresser with drawers", "furniture",
   {"kind": E("bookshelf", "bookshelf", "cabinet", "open_shelf", "dresser"), "width": P(I, 16, 12, 32), "height": P(I, 24, 12, 30),
    "depth": P(I, 10, 6, 16), "shelves": P(I, 3, 1, 5), "books": P(B, True), "doors": E("none", "none", "lower", "full")},
   {"frame": ("#7a5030", "wood_planks"), "back": ("#5a3a22", "wood_planks"), "book_a": ("#a83a3a", "leather"),
    "book_b": ("#3a6a9a", "leather"), "book_c": ("#4a8a4a", "leather"), "accent": ("#c8a040", "gold", "handles")},
   build_shelf, ("bookshelf", "shelf", "cabinet", "dresser", "cupboard", "wardrobe", "books"))
_t("bed", "bed with frame, mattress, quilt and pillows", "furniture",
   {"size": E("single", "single", "double"), "length": P(I, 32, 24, 32), "frame_h": P(I, 4, 2, 6),
    "headboard_h": P(I, 8, 4, 14), "quilt": E("plain", "plain", "patchwork", "striped"), "posts": P(B, False),
    "footboard": P(B, False)},
   {"frame": ("#7a5030", "wood_planks"), "sheet": ("#e8e2d6", "wool"), "quilt": ("#a84a3a", "wool"),
    "quilt2": ("#d8b060", "wool"), "quilt3": ("#4a7a9a", "wool"), "pillow": ("#f0ece2", "wool"), "accent": ("#c8a040", "gold")},
   build_bed, ("bed", "cot", "bunk"))
_t("chest", "storage chest or treasure chest with lid, metal bands, corner caps and lock", "block",
   {"width": P(I, 14, 8, 16), "height": P(I, 10, 6, 14), "depth": P(I, 12, 8, 16), "lid_h": P(I, 4, 2, 6),
    "bands": P(B, True), "corners": P(B, True), "lock": E("keyhole", "plate", "keyhole", "none"), "feet": P(B, False)},
   {"wood": ("#8a5a32", "wood_planks"), "metal": ("#5a5a62", "metal"), "lock": ("#d4a840", "gold")},
   build_chest, ("chest", "treasure", "trunk", "coffer", "box of loot"))
_t("stall", "market stand / stall / booth with counter, posts and a cloth awning", "furniture",
   {"width": P(I, 32, 16, 44), "depth": P(I, 16, 10, 24), "counter_h": P(I, 12, 8, 16), "roof_h": P(I, 12, 8, 16),
    "roof": E("striped_awning", "striped_awning", "flat_cloth"), "posts": E("4", "4", "2"),
    "goods": E("fruit", "none", "fruit", "crates"), "sign": P(B, False)},
   {"wood": ("#7a5030", "log"), "counter": ("#9a6a3a", "wood_planks"), "cloth_a": ("#c8403a", "cloth"),
    "cloth_b": ("#ece2cc", "cloth"), "goods_a": ("#d8a030", "plain"), "goods_b": ("#6a9a3a", "plain")},
   build_stall, ("market", "stall", "stand", "booth", "awning", "shop", "vendor"))
_t("lantern", "lantern or lamp: cage with glass and a candle/flame/crystal, optionally hanging on a chain", "block",
   {"size": P(I, 6, 4, 10), "shape": E("box", "box", "tall"), "hanging": P(B, False), "chain_len": P(I, 4, 2, 8),
    "light": E("candle", "candle", "flame", "crystal", "none"), "glass": P(B, True), "roof": E("pyramid", "pyramid", "flat", "dome")},
   {"metal": ("#3e3c44", "metal"), "glass": ("#c8e0e8", "glass"), "light": ("#ffb440", "glow"),
    "candle": ("#ece0c0", "plain", "wax"), "chain": ("#4a4850", "metal")},
   build_lantern, ("lantern", "lamp", "light", "candle holder", "torch"))
_t("vessel", "open container: cauldron, birdbath, basin, pot, bowl, tub, well, fountain (liquid inside)", "block",
   {"shape": E("cauldron", "cauldron", "basin", "pot", "bowl", "tub"), "support": E("none", "none", "legs3", "legs4", "pedestal", "ring_base"),
    "width": P(I, 12, 6, 16), "height": P(I, 8, 3, 14), "liquid": E("water", "water", "potion", "lava", "honey", "none"),
    "level": P(N, 0.75, 0.2, 0.95), "bubbles": P(B, False), "rim": P(B, True), "handles": P(B, False), "moss": P(B, False)},
   {"body": ("#4a4a52", "metal"), "rim": ("#3a3a42", "metal"), "support": ("#3a3a42", "metal"),
    "liquid": ("#3a7ac8", "slime", "water/potion/lava surface"), "moss": ("#5a8a3a", "leaves")},
   build_vessel, ("cauldron", "birdbath", "bird bath", "basin", "pot", "bowl", "tub", "well", "fountain", "planter", "bucket"))
_t("box_block", "solid box block with features: beehive, machine, crate, furnace, safe, generator", "block",
   {"kind": E("crate", "hive", "machine", "crate", "safe"), "width": P(I, 14, 8, 16), "height": P(I, 14, 8, 16),
    "roof": P(B, False, doc="overhanging lid"), "entrance": P(B, False, doc="slot with landing board"),
    "drips": P(B, False, doc="honey/liquid dripping from the slot"), "pipes": P(I, 0, 0, 4), "gear": P(B, False),
    "gauge": P(B, False), "vents": P(B, False), "feet": P(B, False)},
   {"body": ("#b0844a", "wood_planks"), "trim": ("#7a5430", "log"), "accent": ("#c8743a", "metal", "pipes, gears"),
    "detail": ("#f0a830", "glow", "honey, gauge glass"), "dark": ("#2e2420", "plain")},
   build_box_block, ("beehive", "hive", "machine", "crate", "furnace", "generator", "engine", "safe", "clockwork", "box"))
_t("totem", "standing monument: totem, crystal pillar, obelisk, shrine, floating crystal (can bob)", "entity",
   {"base": E("slab", "slab", "stepped", "none"), "pillar_w": P(I, 6, 2, 10), "pillar_h": P(I, 10, 0, 20),
    "top": E("crystal", "crystal", "orb", "flame", "rune_stone"), "top_size": P(I, 5, 3, 9), "floating": P(B, True),
    "shards": P(I, 0, 0, 6), "runes": P(B, True), "pillar_rings": P(B, False)},
   {"stone": ("#6a6670", "stone"), "crystal": ("#b07ae0", "crystal"), "glow": ("#7ae0ff", "glow")},
   build_totem, ("totem", "obelisk", "pillar", "shrine", "monument", "crystal", "statue", "beacon"))
_t("plant", "plant: potted plant, flower, bush, sapling, fern", "block",
   {"pot": E("clay", "clay", "none"), "pot_w": P(I, 6, 4, 10), "pot_h": P(I, 5, 3, 8), "stem_h": P(I, 5, 2, 10),
    "form": E("bush", "bush", "tree", "flower", "fern"), "crown_w": P(I, 8, 4, 12), "fruit": P(B, False)},
   {"pot": ("#b0603a", "brick"), "soil": ("#4a3424", "plain"), "stem": ("#6a4a2a", "log"), "leaves": ("#4a8a3a", "leaves"),
    "bloom": ("#d85a8a", "plain"), "accent": ("#e8c040", "plain")},
   build_plant, ("plant", "flower", "bush", "sapling", "fern", "potted", "tree", "cactus"))
_t("boat", "boat: rowboat, canoe, small ship hull, with seats and oars", "entity",
   {"length": P(I, 28, 18, 40), "width": P(I, 14, 10, 18), "hull_h": P(I, 6, 4, 9), "seats": P(I, 2, 1, 3), "oars": P(B, True)},
   {"hull": ("#8a5a32", "wood_planks"), "trim": ("#6a4428", "wood_planks"), "oar": ("#9a7044", "log"), "metal": ("#4a4850", "metal")},
   build_boat, ("boat", "rowboat", "canoe", "raft", "ship", "oars"))
_t("tool", "held item on a handle: pickaxe, axe, hammer, mace, sword, shovel, staff, wand, spear, hoe", "item",
   {"head": E("pickaxe", "pickaxe", "axe", "hammer", "mace", "sword", "shovel", "staff", "wand", "spear", "hoe"),
    "handle_len": P(N, 11, 5, 15), "head_size": P(I, 7, 4, 10), "grip_wrap": P(B, False), "pommel": P(B, False),
    "bands": P(B, False, doc="metal bands"), "gem": P(B, False)},
   {"handle": ("#7a5230", "log"), "head": ("#8a8c94", "metal"), "grip": ("#5a3a26", "leather"),
    "accent": ("#d4a840", "gold"), "gem": ("#9a5ae0", "crystal")},
   build_tool, ("pickaxe", "axe", "hammer", "sword", "shovel", "staff", "wand", "spear", "hoe", "mace", "tool", "weapon"))
_t("bottle", "item container: potion bottle, flask, jar with liquid, neck and cork", "item",
   {"shape": E("round", "round", "square", "tall", "flask"), "size": P(I, 6, 4, 10), "neck_len": P(I, 2, 1, 4),
    "level": P(N, 0.7, 0.2, 0.95), "cork": P(B, True), "label": P(B, False), "bubbles": P(B, False)},
   {"glass": ("#d0e4ec", "glass"), "liquid": ("#d85a9a", "glow"), "cork": ("#a07a4a", "log"), "label": ("#e8dcc0", "paper")},
   build_bottle, ("potion", "bottle", "flask", "jar", "vial", "elixir"))
_t("armor", "wearable armor set on a player stand: helmet, chestplate, pauldrons, leggings, boots", "armor",
   {"helmet": E("plumed", "plumed", "horned", "crown", "open", "hood", "leaf", "none"), "chest": P(B, True),
    "pauldrons": E("round", "none", "round", "spiky", "leaf"), "gauntlets": P(B, True), "legs": P(B, True), "boots": P(B, True),
    "cape": P(B, False), "trim": P(B, True), "emblem": P(B, False), "vines": P(B, False, doc="vines over the armour")},
   {"plate": ("#9a9ca4", "metal"), "under": ("#5a3a2a", "leather"), "trim": ("#c8a040", "gold"),
    "plume": ("#b03a3a", "wool"), "stand": ("#c9b08a", "wood_planks", "the wearer stand")},
   build_armor, ("armor", "armour", "helmet", "chestplate", "set", "suit", "plate"))

# a block/blockbench category hint for each brief category (keyword fallback ranks inside this subset first)
CATEGORY_HINT = {"mob": ("biped", "quadruped", "bird", "frog", "arthropod", "fish"),
                 "item": ("tool", "bottle"), "armor": ("armor",), "entity": ("boat", "totem", "biped", "quadruped"),
                 "furniture": ("table", "chair", "shelf", "bed", "stall", "chest"),
                 "block": ("lantern", "vessel", "box_block", "chest", "plant", "totem")}


def build_spec(template: str, answer: dict | None = None, name: str | None = None) -> tuple[dict, list]:
    """Planner answer -> star.blockbench spec (not yet normalized) + clamping notes."""
    from .core import resolve
    t = TEMPLATES[template]
    params, roles, notes = resolve(t, answer, KINDS)
    nm = name or (answer or {}).get("name") or template
    nm = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(nm).lower())[:40] or template
    return t.build(params, roles, nm), notes
