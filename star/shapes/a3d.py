"""3D part templates for STAR's prop pipeline (star.asset3d): the planner picks a template and fills parameters,
trusted code here builds every part with absolute positions in real-world metres.

Axes as in star.asset3d.spec: +X front, +Y left, +Z up. Props and furniture show their "presentation face"
(drawers, lock, stencil, pockets) on -Y, the side the default renders look at most; vehicles and weapons point
their front/muzzle at +X. Every template accepts every style:
  pbr      realistic proportions, fine detail (seams, cuts, screws)
  stylized chunkier parts (thicker tubes/blades), bigger bevels, fewer but bolder details
  lowpoly  few parts, no cuts or seams
  roblox   chunky, 12-30 parts, no booleans
Each build returns a raw asset3d spec (passes spec.prepare + spec.ground); parts touch or overlap by construction.
"""
from __future__ import annotations

import math

from star.asset3d import spec as A

from .core import Param, Role, Template, resolve

KINDS = A.MATERIALS

_BEV = {"pbr": 0.003, "stylized": 0.010, "roblox": 0.006, "lowpoly": 0.0}
_CHUNK = {"pbr": 1.0, "stylized": 1.3, "roblox": 1.25, "lowpoly": 1.15}


# ------------------------------------------------------------------ helpers
def _r(v):
    return round(float(v), 5)


def _clean(pts, eps=1e-4):
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > eps:
            out.append((p[0], p[1]))
    if len(out) > 2 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= eps:
        out.pop()
    return [[_r(x), _r(z)] for x, z in out]


def _arc(cx, cz, r, a0, a1, n, rz=None):
    rz = r if rz is None else rz
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             cz + rz * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]


def _rot2(pts, deg, cx=0.0, cz=0.0):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * c - (z - cz) * s, cz + (x - cx) * s + (z - cz) * c) for x, z in pts]


def _tr(pts, dx, dz):
    return [(x + dx, z + dz) for x, z in pts]


def _alt(roles, defaults, role, kind, color):
    """Variant-specific default for a role the planner left at the template default."""
    d = defaults[role]
    if roles[role]["kind"] == d.kind and roles[role]["color"] == d.color:
        roles = dict(roles)
        roles[role] = {"kind": kind, "color": color}
    return roles


def _scaled(p, s):
    q = dict(p)
    q["pos"] = [_r(v * s) for v in p["pos"]]
    for key in ("size", "step"):
        if key in q:
            q[key] = [_r(v * s) for v in q[key]]
    for key in ("radius", "radius2", "depth", "tube", "thickness", "bevel"):
        if key in q:
            q[key] = _r(q[key] * s)
    if "points" in q:
        q["points"] = [[_r(v * s) for v in pt] for pt in q["points"]]
    if q.get("cuts"):
        cuts = []
        for c in q["cuts"]:
            c = dict(c)
            for key in ("pos", "size", "step"):
                if key in c:
                    c[key] = [_r(v * s) for v in c[key]]
            for key in ("radius", "depth"):
                if key in c:
                    c[key] = _r(c[key] * s)
            cuts.append(c)
        q["cuts"] = cuts
    return q


def bounds(raw: dict) -> tuple[list, list]:
    """World box of a raw spec after prepare (mirrors expanded)."""
    sp = A.prepare(raw)
    lo, hi = [1e9] * 3, [-1e9] * 3
    for p in sp["parts"]:
        a, b = A.local_aabb(p)
        for i in range(3):
            lo[i] = min(lo[i], p["pos"][i] + a[i])
            hi[i] = max(hi[i], p["pos"][i] + b[i])
    return lo, hi


class Kit:
    """Collects parts for one asset; colours/materials come from the resolved roles."""

    def __init__(self, name, category, style, roles):
        self.name, self.category = name, category
        self.style = style if style in A.STYLES else "pbr"
        self.roles = roles
        self.parts: list = []
        s = self.style
        self.pbr, self.low, self.rbx, self.sty = s == "pbr", s == "lowpoly", s == "roblox", s == "stylized"
        self.chunk = _CHUNK[s]
        self.small = s != "lowpoly"  # secondary parts (pins, buckles, small knobs)
        self.fine = s == "pbr"  # tertiary detail (screws, seams, vents)
        self.cuts_ok = s in ("pbr", "stylized")
        self.bv = _BEV[s]
        self._ids: set = set()

    def bev(self, mult):
        """Per-part bevel scaled for big parts (None = builder default, always for lowpoly)."""
        return None if self.low else _r(self.bv * mult)

    def add(self, pid, typ, role, pos, mat=None, color=None, **kw):
        base, n = pid, 1
        while pid in self._ids:
            n += 1
            pid = f"{base}{n}"
        self._ids.add(pid)
        r = self.roles.get(role) or {"kind": "plastic", "color": "#808080"}
        p = {"id": pid, "type": typ, "pos": [_r(v) for v in pos], "mat": mat or r["kind"], "color": color or r["color"]}
        for k, v in kw.items():
            if v is None or (isinstance(v, (list, tuple)) and len(v) == 0):
                continue
            if k == "cuts" and not self.cuts_ok:
                continue
            if k == "seams" and not self.fine:
                continue
            if k == "mirror_y" and not v:
                continue
            p[k] = [_r(x) for x in v] if k in ("size", "rot", "taper", "scale", "step") else v
        self.parts.append(p)
        return p

    def box(self, pid, role, pos, size, **kw):
        return self.add(pid, "box", role, pos, size=[max(0.001, s) for s in size], **kw)

    def cyl(self, pid, role, pos, r, depth, axis="z", **kw):
        return self.add(pid, "cylinder", role, pos, radius=_r(max(0.0006, r)), depth=_r(max(0.0006, depth)),
                        axis=axis, **kw)

    def cone(self, pid, role, pos, r, r2, depth, axis="z", **kw):
        return self.add(pid, "cone", role, pos, radius=_r(max(0.0006, r)), radius2=_r(max(0.0, r2)),
                        depth=_r(max(0.0006, depth)), axis=axis, **kw)

    def ball(self, pid, role, pos, r, scale=None, **kw):
        return self.add(pid, "sphere", role, pos, radius=_r(max(0.0006, r)), scale=scale, **kw)

    def ring(self, pid, role, pos, R, tube, axis="y", **kw):
        tube = min(tube, R * 0.9)
        return self.add(pid, "torus", role, pos, radius=_r(R), tube=_r(max(0.0006, tube)), axis=axis, **kw)

    def prof(self, pid, role, pts, thick, y=0.0, pos=None, **kw):
        return self.add(pid, "profile", role, pos or (0.0, y, 0.0), points=_clean(pts), thickness=_r(max(0.001, thick)),
                        **kw)

    def lathe(self, pid, role, pos, pts, axis="z", **kw):
        return self.add(pid, "lathe", role, pos, points=[[_r(a), _r(max(0.0, b))] for a, b in pts], axis=axis, **kw)

    def tube(self, pid, role, pts, r, **kw):
        return self.add(pid, "tube", role, (0.0, 0.0, 0.0), points=[[_r(v) for v in q] for q in pts],
                        radius=_r(max(0.0006, r)), **kw)

    def spec(self, scale=1.0) -> dict:
        parts = [_scaled(p, scale) for p in self.parts] if abs(scale - 1.0) > 1e-9 else self.parts
        raw = {"name": self.name[:60], "category": self.category, "style": self.style, "dims": [1, 1, 1],
               "parts": parts}
        lo, hi = bounds(raw)
        raw["dims"] = [_r(max(0.01, hi[i] - lo[i])) for i in range(3)]
        return raw


def _cbox(size, pos=(0, 0, 0), count=1, step=(0, 0, 0), side=None, u=0.0, v=0.0, rot=None):
    c = {"shape": "box", "size": [_r(s) for s in size], "pos": [_r(p) for p in pos]}
    if count > 1:
        c["count"], c["step"] = int(min(24, count)), [_r(s) for s in step]
    if side:
        c["side"], c["u"], c["v"] = side, u, v
    if rot:
        c["rot"] = [_r(a) for a in rot]
    return c


def _ccyl(r, depth, axis, pos=(0, 0, 0), count=1, step=(0, 0, 0), side=None, u=0.0, v=0.0):
    c = {"shape": "cylinder", "radius": _r(r), "depth": _r(depth), "axis": axis, "pos": [_r(p) for p in pos]}
    if count > 1:
        c["count"], c["step"] = int(min(24, count)), [_r(s) for s in step]
    if side:
        c["side"], c["u"], c["v"] = side, u, v
    return c


def _slab_on_line(k, pid, role, p0, p1, width, thick, inside, inset=0.9, mat=None, color=None):
    """A thin box lying on the X-Z line p0-p1 (windshields), pushed outward from the point `inside`."""
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dz)
    nx, nz = dz / ln, -dx / ln
    mx, mz = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    if (inside[0] - mx) * nx + (inside[1] - mz) * nz > 0:
        nx, nz = -nx, -nz
    a = math.degrees(math.atan2(dz, dx))
    off = thick * 0.3
    return k.box(pid, role, (mx + nx * off, 0, mz + nz * off), (ln * inset, width, thick), rot=[0, -a, 0], mat=mat,
                 color=color)


def _line_x(p0, p1, z):
    """x of the X-Z line p0-p1 at height z."""
    return p0[0] + (z - p0[1]) * (p1[0] - p0[0]) / (p1[1] - p0[1])


# ------------------------------------------------------------------ firearm
GUN_ROLES = {
    "body": Role("#2e3034", "gunmetal", "receiver, slide, metal body"),
    "furniture": Role("#26282c", "polymer", "grip, stock, handguard, magazine"),
    "barrel": Role("#3b3d41", "gunmetal", "barrel, muzzle, bolt"),
    "accent": Role("#8c9096", "bare_metal", "sights, pins, small metal details"),
    "glow": Role("#3fe0ff", "emissive", "energy cell and glowing parts (sci-fi)"),
}
GUN_PARAMS = {
    "variant": Param("enum", "assault", choices=("pistol", "rifle", "smg", "assault", "shotgun", "blaster"),
                     doc="pistol | bolt-action hunting rifle | submachine gun | assault rifle | pump shotgun | "
                         "sci-fi blaster"),
    "size": Param("num", 1.0, 0.8, 1.25, doc="overall scale vs the real gun"),
    "barrel": Param("num", 1.0, 0.6, 1.6, doc="barrel and handguard length factor"),
    "optic": Param("enum", "auto", choices=("auto", "none", "irons", "red_dot", "scope")),
    "stock": Param("enum", "auto", choices=("auto", "none", "fixed", "adjustable")),
    "magazine": Param("enum", "auto", choices=("auto", "none", "straight", "curved")),
    "furniture": Param("enum", "auto", choices=("auto", "polymer", "wood"), doc="grip/stock material"),
    "rail": Param("bool", True, doc="top accessory rail"),
    "suppressor": Param("bool", False),
    "foregrip": Param("bool", False, doc="vertical grip under the handguard"),
    "grip_angle": Param("num", 16, 5, 28, doc="pistol grip rake in degrees"),
}


def _grip(k, pid, role, x0, z0, depth, length, rake, thick, base=True):
    """Pistol grip: top-back corner at (x0, z0), raked back by `rake` degrees."""
    L, d = length, depth
    loc = [(0, 0), (d, 0), (d * 0.98, -0.28 * L), (d * 0.9, -0.62 * L), (d * 0.95, -L), (0.1 * d, -L),
           (-0.1 * d, -0.6 * L), (-0.06 * d, -0.2 * L)]
    k.prof(pid, role, _tr(_rot2(loc, -rake), x0, z0), thick)
    if base and k.small:
        bx, bz = _tr(_rot2([(0.52 * d, -L)], -rake), x0, z0)[0]
        k.box(pid + "_base", role, (bx, 0, bz - 0.003), (d * 1.0, thick * 1.08, 0.008), rot=[0, rake, 0])


def _guard(k, xb, xf, zt, drop, xt=None):
    r = 0.0032 * k.chunk
    pts = [(xb, 0, zt + 0.003), (xb - 0.002, 0, zt - drop * 0.7), (xb + 0.007, 0, zt - drop),
           (xf - 0.004, 0, zt - drop), (xf + 0.006, 0, zt - drop * 0.45), (xf + 0.011, 0, zt + 0.003)]
    k.tube("trigger_guard", "body", pts, r)
    if k.small:
        xt = (xb + xf) / 2 if xt is None else xt
        k.prof("trigger", "accent", [(xt, zt + 0.003), (xt + 0.005, zt + 0.003), (xt + 0.001, zt - drop * 0.5),
                                      (xt - 0.006, zt - drop * 0.78), (xt - 0.004, zt - drop * 0.4)], 0.006 * k.chunk)


def _mag_curved(k, x_back, z_top, depth, length, thick, role="furniture"):
    R = 0.55
    th = math.degrees(math.asin(min(0.9, length / R)))
    back = [(x_back + R + R * math.cos(math.radians(180 + th * i / 6)), z_top + R * math.sin(math.radians(180 + th * i / 6)))
            for i in range(7)]
    Rf = R - depth
    front = [(x_back + R + Rf * math.cos(math.radians(180 + th * i / 6)), z_top + Rf * math.sin(math.radians(180 + th * i / 6)))
             for i in range(6, -1, -1)]
    k.prof("magazine", role, back + front, thick)
    if k.small:
        b, f = back[-1], front[0]
        k.box("mag_base", role, ((b[0] + f[0]) / 2 - 0.003 * math.sin(math.radians(th)), 0,
                                 (b[1] + f[1]) / 2 - 0.003 * math.cos(math.radians(th))),
              (depth * 1.12, thick * 1.15, 0.009), rot=[0, -th, 0])


def _mag_straight(k, x_back, z_top, depth, length, thick, rake=4.0, role="furniture"):
    loc = [(0, 0), (depth, 0), (depth, -length), (0, -length)]
    k.prof("magazine", role, _tr(_rot2(loc, rake), x_back, z_top), thick)
    if k.small:
        bx, bz = _tr(_rot2([(depth / 2, -length)], rake), x_back, z_top)[0]
        k.box("mag_base", role, (bx, 0, bz - 0.003), (depth * 1.15, thick * 1.15, 0.009), rot=[0, -rake, 0])


def _scope(k, xc, zbase, length=0.34, h=0.024):
    r = 0.0127 * min(k.chunk, 1.2)
    zc = zbase + h + r
    L = length
    k.lathe("scope", "body", (xc, 0, zc), [[-L / 2, 0], [-L / 2, r * 1.5], [-L / 2 + 0.05, r * 1.5],
                                          [-L / 2 + 0.075, r], [L / 2 - 0.1, r], [L / 2 - 0.05, r * 1.9],
                                          [L / 2, r * 1.9], [L / 2, 0]], "x")
    if k.small:
        k.cyl("scope_lens", "glow", (xc + L / 2 + 0.0005, 0, zc), r * 1.65, 0.004, "x", mat="glass", color="#1c2a33")
        k.cyl("turret_top", "body", (xc + 0.01, 0, zc + r + 0.007), 0.011, 0.02)
        k.cyl("turret_side", "body", (xc + 0.01, -(r + 0.007), zc), 0.011, 0.02, "y")
    for i, x in enumerate((xc - 0.06, xc + 0.05)):
        k.box(f"ring_base{i}", "accent" if k.small else "body", (x, 0, zbase + h / 2), (0.014, 0.017, h + 0.004))
        if not k.low:
            k.ring(f"scope_ring{i}", "body", (x, 0, zc), r + 0.0028, 0.0034 * k.chunk, "x")


def _reddot(k, xc, zbase):
    k.box("optic_base", "body", (xc, 0, zbase + 0.005), (0.042, 0.024, 0.012))
    k.lathe("optic", "body", (xc, 0, zbase + 0.011 + 0.016), [[-0.028, 0], [-0.028, 0.016], [0.022, 0.019],
                                                            [0.03, 0.019], [0.03, 0]], "x")
    if k.small:
        k.cyl("optic_lens", "glow", (xc + 0.0302, 0, zbase + 0.027), 0.015, 0.003, "x", mat="glass", color="#2a3c34")
        k.cyl("optic_knob", "accent", (xc - 0.006, -0.019, zbase + 0.027), 0.006, 0.01, "y")


def _stock(k, kind, xr, zt, furn):
    """Stock behind a receiver whose rear face is at x=xr; zt = height of the buffer tube / top line."""
    c = k.chunk
    if kind == "adjustable":
        back = xr - 0.24
        k.cyl("buffer_tube", "body", ((xr + 0.005 + back + 0.04) / 2, 0, zt), 0.015 * c, (xr + 0.005) - (back + 0.04), "x")
        k.prof("stock", furn, [(back + 0.14, zt + 0.017), (back + 0.004, zt + 0.021), (back, zt - 0.088),
                               (back + 0.03, zt - 0.094), (back + 0.14, zt - 0.024)], 0.034 * c,
               cuts=[_cbox((0.055, 0.06, 0.016), pos=(back + 0.08, 0, zt - 0.032), rot=(0, 24, 0))])
        if k.small:
            k.box("butt_pad", furn, (back - 0.004, 0, zt - 0.034), (0.012, 0.038 * c, 0.115), mat="rubber",
                  color="#1d1d1e")
        if k.fine:
            k.box("stock_lever", "accent", (back + 0.115, 0, zt - 0.03), (0.03, 0.012, 0.008))
    elif kind == "fixed":
        back = xr - 0.27
        k.prof("stock", furn, [(xr + 0.006, zt + 0.02), (back, zt + 0.028), (back - 0.004, zt - 0.112),
                               (back + 0.025, zt - 0.118), (xr - 0.08, zt - 0.05), (xr + 0.006, zt - 0.035)], 0.04 * c)
        if k.small:
            k.box("butt_pad", furn, (back - 0.006, 0, zt - 0.042), (0.012, 0.042 * c, 0.135), mat="rubber",
                  color="#1d1d1e")
    else:
        k.box("end_cap", "body", (xr - 0.004, 0, zt - 0.005), (0.012, 0.028 * c, 0.03))


def _g_assault(k, P, furn, optic, stock, mag):
    bf, c = P["barrel"], k.chunk
    W = 0.030 * c
    k.box("upper", "body", (-0.03, 0, 0.012), (0.25, W, 0.042),
          cuts=[_cbox((0.05, 0.006, 0.014), side="right", u=0.25, v=0.1)] if k.fine else None)
    k.box("lower", "body", (-0.045, 0, -0.023), (0.20, W * 0.94, 0.032))
    k.box("magwell", "body", (0.02, 0, -0.05), (0.07, W * 1.08, 0.036))
    hg = 0.30 * bf
    hx0, hx1 = 0.09, 0.09 + hg
    cuts = None
    if k.cuts_ok:
        n = max(2, int(hg / 0.06)) if k.fine else max(2, int(hg / 0.1))
        room = (hg - 0.03) / 2
        st = 1.7 * room / (n - 1)
        cuts = [_cbox((0.03, 0.008, 0.012), side=s, u=-0.85, v=0.0, count=n, step=(st, 0, 0)) for s in ("left", "right")]
    k.box("handguard", furn, ((hx0 + hx1) / 2, 0, 0.007), (hg, 0.046 * c, 0.052), cuts=cuts)
    ztop = 0.033
    if P["rail"]:
        rl = hx1 - 0.005 + 0.15
        cuts = None
        if k.cuts_ok:
            n = min(24, int((rl - 0.02) / (0.022 if k.fine else 0.04)) + 1)
            cuts = [_cbox((0.0045 if k.fine else 0.008, 0.03, 0.006), pos=(-rl / 2 + 0.01, 0, 0.0045), count=n,
                          step=((rl - 0.02) / (n - 1), 0, 0))]
        k.box("top_rail", "body", ((-0.15 + hx1 - 0.005) / 2, 0, 0.0365), (rl, 0.022, 0.009), cuts=cuts)
        ztop = 0.041
    xm = hx1 + 0.13 * bf
    k.cyl("barrel", "barrel", ((0.06 + xm) / 2, 0, 0.0), 0.0095 * min(c, 1.2), xm - 0.06, "x")
    if optic in ("irons", "none") or not P["rail"]:
        xs = hx1 + 0.025
        k.prof("front_sight", "body", [(xs - 0.014, -0.004), (xs + 0.012, -0.004), (xs + 0.004, 0.05), (xs - 0.006, 0.05)],
               0.014 * c)
    if P["suppressor"]:
        k.cyl("suppressor", "barrel", (xm + 0.065, 0, 0.0), 0.019 * c, 0.17, "x")
    else:
        k.cyl("muzzle", "barrel", (xm + 0.02, 0, 0.0), 0.011 * c, 0.05, "x",
              cuts=[_cbox((0.026, 0.03, 0.0035), pos=(0.008, 0, 0))] if k.fine else None)
    if k.small:
        k.box("charging_handle", "body", (-0.163, 0, 0.028), (0.03, 0.036 * c, 0.007))
        k.cyl("selector", "accent", (-0.085, 0, -0.018), 0.007, W * 0.94 + 0.005, "y")
    if k.fine:
        k.cyl("forward_assist", "body", (-0.11, -(W / 2 + 0.004), 0.022), 0.006, 0.03, "x")
        k.cyl("pin_rear", "accent", (-0.125, 0, -0.022), 0.0035, W * 0.94 + 0.004, "y")
        k.cyl("pin_front", "accent", (0.04, 0, -0.022), 0.0035, W * 0.94 + 0.004, "y")
    _grip(k, "grip", furn, -0.085, -0.036, 0.034, 0.105, P["grip_angle"], 0.03 * c)
    _guard(k, -0.05, -0.016, -0.039, 0.024, -0.034)
    if mag == "curved":
        _mag_curved(k, -0.011, -0.058, 0.062, 0.18, 0.022 * c)
    elif mag == "straight":
        _mag_straight(k, -0.011, -0.058, 0.062, 0.17, 0.022 * c, rake=6)
    _stock(k, stock, -0.155, 0.01, furn)
    if optic == "red_dot":
        _reddot(k, -0.06, ztop)
    elif optic == "scope":
        _scope(k, -0.04, ztop, 0.3, 0.02)
    elif optic == "irons":
        k.box("rear_sight", "body", (-0.135, 0, ztop + 0.008), (0.022, 0.024, 0.016))
    if P["foregrip"]:
        k.cyl("foregrip", furn, (hx0 + 0.6 * hg, 0, -0.019 - 0.04), 0.014 * c, 0.085)


def _g_smg(k, P, furn, optic, stock, mag):
    bf, c = P["barrel"], k.chunk
    W = 0.034 * c
    k.box("receiver", "body", (0, 0, 0.0), (0.27, W, 0.048),
          cuts=[_cbox((0.045, 0.006, 0.014), side="right", u=0.3, v=0.3)] if k.fine else None)
    hg = 0.11 * bf
    hx0, hx1 = 0.12, 0.12 + hg
    cuts = [_cbox((0.03, 0.006, 0.008), side=s, u=0.0, v=0.0) for s in ("left", "right")] if k.cuts_ok else None
    k.box("handguard", furn, ((hx0 + hx1) / 2, 0, -0.006), (hg, 0.044 * c, 0.04), cuts=cuts)
    k.cyl("cocking_tube", "body", ((0.03 + hx1 - 0.01) / 2, 0, 0.018), 0.012 * c, hx1 - 0.04, "x")
    xm = hx1 + 0.05 * bf
    k.cyl("barrel", "barrel", ((0.1 + xm) / 2, 0, 0.0), 0.0075 * min(c, 1.2), xm - 0.1, "x")
    k.box("lower", furn, (-0.045, 0, -0.033), (0.12, W * 0.95, 0.022))
    k.box("magwell", "body", (0.035, 0, -0.035), (0.04, W * 1.05, 0.03))
    if optic in ("irons", "none"):
        k.box("front_sight", "body", (hx1 - 0.016, 0, 0.034), (0.012, 0.016 * c, 0.018))
        k.cyl("rear_sight", "body", (-0.1, 0, 0.032), 0.011, 0.022 * c, "y")
    if k.small:
        k.cyl("cocking_handle", "accent", (hx1 - 0.04, 0.012 * c + 0.012, 0.02), 0.004, 0.03, "y")
        k.cyl("selector", "accent", (-0.07, 0, -0.03), 0.006, W * 0.95 + 0.005, "y")
    _grip(k, "grip", furn, -0.085, -0.04, 0.034, 0.1, P["grip_angle"], 0.03 * c)
    _guard(k, -0.05, -0.012, -0.043, 0.024, -0.033)
    if mag == "curved":
        _mag_curved(k, 0.019, -0.04, 0.032, 0.17, 0.022 * c)
    elif mag == "straight":
        _mag_straight(k, 0.019, -0.04, 0.032, 0.19, 0.022 * c, rake=5)
    if stock == "adjustable":
        k.tube("stock_rod", "body", [(-0.125, 0.016 * c, 0.006), (-0.33, 0.016 * c, 0.006)], 0.0045 * c, mirror_y=True)
        k.box("butt_plate", furn, (-0.335, 0, -0.03), (0.016, 0.05 * c, 0.11))
    else:
        _stock(k, stock, -0.135, 0.008, furn)
    ztop = 0.024
    if P["rail"] and optic in ("red_dot", "scope"):
        k.box("top_rail", "body", (-0.04, 0, 0.027), (0.13, 0.02, 0.008))
        ztop = 0.031
    if optic == "red_dot":
        _reddot(k, -0.045, ztop)
    elif optic == "scope":
        _scope(k, -0.03, ztop, 0.24, 0.02)
    if P["suppressor"]:
        k.cyl("suppressor", "barrel", (xm + 0.07, 0, 0.0), 0.018 * c, 0.15, "x")
    if P["foregrip"]:
        k.cyl("foregrip", furn, ((hx0 + hx1) / 2, 0, -0.026 - 0.04), 0.013 * c, 0.085)


def _g_pistol(k, P, furn, optic, stock, mag):
    c = k.chunk
    W = 0.029 * c
    cuts = []
    if k.cuts_ok:
        n, w, st = (9, 0.0018, 0.0045) if k.fine else (5, 0.003, 0.008)
        cuts = [_cbox((w, 0.004, 0.017), side=s, u=-0.92, v=0.1, count=n, step=(st, 0, 0)) for s in ("left", "right")]
        if k.fine:
            cuts.append(_cbox((0.03, 0.006, 0.012), side="right", u=0.15, v=0.6))
    k.box("slide", "body", (0, 0, 0.006), (0.19, W, 0.030), cuts=cuts)
    k.cyl("muzzle", "barrel", (0.096, 0, 0.008), 0.0065 * min(c, 1.2), 0.006, "x",
          cuts=[_ccyl(0.0045, 0.01, "x", pos=(0.003, 0, 0))] if k.fine else None)
    k.box("frame", furn, (-0.005, 0, -0.017), (0.17, W * 0.93, 0.018))
    if k.small:
        k.box("dust_cover", furn, (0.05, 0, -0.028), (0.05, W * 0.75, 0.008),
              cuts=[_cbox((0.004, 0.03, 0.004), pos=(-0.012, 0, -0.003), count=3, step=(0.012, 0, 0))] if k.fine else None)
    _grip(k, "grip", furn, -0.09, -0.022, 0.046, 0.092, max(P["grip_angle"], 12), 0.031 * c)
    _guard(k, -0.044, 0.002, -0.026, 0.026, -0.033)
    k.box("front_sight", "accent", (0.084, 0, 0.0235), (0.006, 0.006 * c, 0.006))
    k.box("rear_sight", "accent", (-0.086, 0, 0.0235), (0.009, 0.02 * c, 0.007))
    if k.small:
        k.box("hammer", "body", (-0.097, 0, 0.004), (0.008, 0.01 * c, 0.014))
    if k.fine:
        k.box("slide_stop", "accent", (-0.02, W * 0.465 + 0.0015, -0.007), (0.03, 0.003, 0.005))
        k.cyl("mag_release", "accent", (-0.042, W * 0.465, -0.022), 0.004, 0.004, "y")
    if mag == "straight":
        bx, bz = _tr(_rot2([(0.023, -0.092)], -max(P["grip_angle"], 12)), -0.09, -0.022)[0]
        k.box("mag_extension", furn, (bx, 0, bz - 0.02), (0.042, W * 0.95, 0.045), rot=[0, max(P["grip_angle"], 12), 0])
    if optic in ("red_dot", "scope"):
        k.box("optic_base", "body", (-0.055, 0, 0.0235), (0.04, 0.022 * c, 0.008))
        k.prof("optic", "body", [(-0.072, 0.027), (-0.038, 0.027), (-0.036, 0.046), (-0.07, 0.043)], 0.024 * c)
    if P["suppressor"]:
        k.cyl("suppressor", "barrel", (0.17, 0, 0.008), 0.016 * c, 0.16, "x")


def _g_rifle(k, P, furn, optic, stock, mag):
    bf, c = P["barrel"], k.chunk
    xt = 0.12 + 0.18 * bf
    pts = [(xt, -0.006), (-0.13, -0.006), (-0.175, -0.010), (-0.215, -0.016), (-0.29, 0.006), (-0.47, 0.014),
           (-0.475, -0.108), (-0.30, -0.062), (-0.225, -0.062), (-0.205, -0.098), (-0.172, -0.100), (-0.150, -0.050),
           (-0.12, -0.046), (-0.02, -0.048), (min(0.12, xt - 0.05), -0.038), (xt, -0.028)]
    k.prof("stock", furn, pts, 0.040 * c)
    k.cyl("receiver", "body", (-0.0325, 0, 0.0), 0.0165 * min(c, 1.2), 0.235, "x",
          cuts=[_cbox((0.06, 0.008, 0.012), side="right", u=0.2, v=0.3)] if k.fine else None)
    xm = 0.085 + 0.56 * bf
    k.cone("barrel", "barrel", ((0.08 + xm) / 2, 0, 0.0), 0.0115 * min(c, 1.2), 0.0085 * min(c, 1.2), xm - 0.08, "x")
    k.cyl("bolt_shroud", "barrel", (-0.162, 0, 0.0), 0.012 * min(c, 1.2), 0.03, "x")
    k.cyl("bolt_handle", "barrel", (-0.095, -0.036, -0.002), 0.004 * c, 0.045, "y")
    k.ball("bolt_knob", "barrel", (-0.095, -0.058, -0.003), 0.0085 * c)
    _guard(k, -0.152, -0.09, -0.046, 0.024, -0.124)
    if mag == "straight":
        k.box("magazine", "body", (-0.04, 0, -0.062), (0.075, 0.028 * c, 0.032))
    elif k.small:
        k.box("floorplate", "accent", (-0.04, 0, -0.0475), (0.075, 0.03 * c, 0.004))
    if k.small:
        k.box("butt_pad", furn, (-0.478, 0, -0.047), (0.012, 0.042 * c, 0.124), mat="rubber", color="#1d1d1e")
    if k.fine:
        k.ring("swivel_rear", "accent", (-0.38, 0, -0.09), 0.008, 0.0018, "y")
        k.ring("swivel_front", "accent", (xt - 0.05, 0, -0.04), 0.008, 0.0018, "y")
    if optic == "scope":
        _scope(k, -0.03, 0.0165 * min(c, 1.2), 0.34, 0.022)
    elif optic == "red_dot":
        _reddot(k, -0.04, 0.0165 * min(c, 1.2))
    elif optic == "irons":
        k.box("front_sight", "accent", (xm - 0.01, 0, 0.012), (0.01, 0.005, 0.01))
        k.box("rear_sight", "accent", (0.12, 0, 0.013), (0.012, 0.016, 0.012))
    if P["suppressor"]:
        k.cyl("suppressor", "barrel", (xm + 0.08, 0, 0.0), 0.018 * c, 0.18, "x")


def _g_shotgun(k, P, furn, optic, stock, mag):
    bf, c = P["barrel"], k.chunk
    W = 0.036 * c
    k.box("receiver", "body", (-0.03, 0, -0.012), (0.20, W, 0.058),
          cuts=[_cbox((0.07, 0.006, 0.02), side="right", u=0.1, v=0.3)] if k.fine else None)
    xm = 0.07 + 0.62 * bf
    rb = 0.0115 * min(c, 1.2)
    k.cyl("barrel", "barrel", ((0.06 + xm) / 2, 0, 0.002), rb, xm - 0.06, "x")
    xtube = 0.07 + 0.5 * bf
    k.cyl("mag_tube", "barrel", ((0.06 + xtube) / 2, 0, -0.019), 0.011 * min(c, 1.2), xtube - 0.06, "x")
    k.cyl("tube_cap", "barrel", (xtube + 0.008, 0, -0.019), 0.0125 * min(c, 1.2), 0.02, "x")
    if k.small:
        k.box("barrel_band", "barrel", (xtube - 0.012, 0, -0.008), (0.012, 0.014 * c, 0.034))
        k.ball("bead", "accent", (xm - 0.006, 0, 0.002 + rb + 0.0015), 0.0028)
    if k.fine:
        k.box("rib", "barrel", ((0.07 + xm) / 2, 0, 0.002 + rb + 0.0012), (xm - 0.08, 0.008, 0.003))
    pr = 0.022 * min(c, 1.25)
    pts = [[0, 0], [0, pr * 0.86], [0.01, pr]]
    nr = 7 if k.fine else (4 if k.sty else 0)
    for i in range(nr):
        a = 0.03 + i * 0.019
        pts += [[a, pr], [a + 0.004, pr * 0.88], [a + 0.011, pr * 0.88], [a + 0.015, pr]]
    pts += [[0.18, pr], [0.19, pr * 0.86], [0.19, 0]]
    k.lathe("pump", furn, (0.095, 0, -0.019), pts, "x")
    if stock in ("adjustable", "none"):
        if stock == "adjustable":
            _stock(k, "adjustable", -0.13, 0.0, furn)
        else:
            k.box("end_cap", "body", (-0.134, 0, -0.01), (0.012, W * 0.8, 0.04))
        _grip(k, "grip", furn, -0.115, -0.038, 0.036, 0.1, P["grip_angle"], 0.032 * c)
    else:
        k.prof("stock", furn, [(-0.125, 0.012), (-0.20, -0.004), (-0.33, 0.004), (-0.50, 0.016), (-0.505, -0.118),
                               (-0.475, -0.124), (-0.30, -0.072), (-0.19, -0.052), (-0.125, -0.040)], 0.040 * c)
        if k.small:
            k.box("butt_pad", furn, (-0.508, 0, -0.052), (0.012, 0.042 * c, 0.13), mat="rubber", color="#1d1d1e")
    _guard(k, -0.09, -0.045, -0.041, 0.024, -0.07)
    if k.fine:
        k.box("shell_carrier", "body", (-0.06, W / 2 + 0.002, -0.012), (0.1, 0.004, 0.05))
        k.cyl("shell", "glow", (-0.093, W / 2 + 0.0135, -0.012), 0.0095, 0.058, mat="plastic", color="#a8322a",
              count=4, step=[0.022, 0, 0])
    ztop = 0.017
    if optic in ("red_dot", "scope"):
        k.box("top_rail", "body", (-0.03, 0, 0.021), (0.16, 0.02, 0.008))
        ztop = 0.025
        if optic == "red_dot":
            _reddot(k, -0.04, ztop)
        else:
            _scope(k, -0.02, ztop, 0.28, 0.018)


def _g_blaster(k, P, furn, optic, stock, mag):
    bf, c = P["barrel"], k.chunk
    T = 0.046 * c
    k.prof("body", "body", [(-0.11, 0.038), (0.07, 0.038), (0.115, 0.022), (0.115, -0.022), (0.04, -0.03),
                            (-0.03, -0.034), (-0.11, -0.022)], T,
           cuts=[_cbox((0.012, 0.008, 0.02), side=s, u=0.45, v=-0.1, count=3, step=(0.018, 0, 0))
                 for s in ("left", "right")])
    k.prof("fin", furn, [(-0.06, 0.036), (0.06, 0.036), (0.035, 0.06), (-0.035, 0.057)], T * 0.45)
    xe = 0.115 + 0.10 * bf
    k.cyl("emitter", "barrel", ((0.10 + xe) / 2, 0, 0.004), 0.015 * c, xe - 0.10, "x")
    n = 3 if k.pbr or k.sty else 2
    gap = (xe - 0.13) / max(1, n)
    k.ring("coil", "glow", (0.13 + gap * 0.3, 0, 0.004), 0.0165 * c, 0.0045 * c, "x", count=n, step=[gap, 0, 0])
    k.cone("muzzle", "body", (xe + 0.012, 0, 0.004), 0.017 * c, 0.023 * c, 0.03, "x")
    k.cyl("muzzle_glow", "glow", (xe + 0.0275, 0, 0.004), 0.012 * c, 0.004, "x")
    k.cyl("cell", "glow", (-0.065, 0, 0.038 + 0.011 * c), 0.012 * c, 0.07, "x")
    k.box("cradle", "accent", (-0.065, 0, 0.0395), (0.085, 0.02 * c, 0.007))
    for i, x in enumerate((-0.103, -0.027)):
        k.cyl(f"cell_cap{i}", "accent", (x, 0, 0.038 + 0.011 * c), 0.0145 * c, 0.012, "x")
    if k.small:
        k.box("stripe", "glow", (0.02, T / 2 + 0.0015, 0.016), (0.08, 0.004, 0.005), mirror_y=True)
    _grip(k, "grip", furn, -0.085, -0.022, 0.036, 0.095, max(5, P["grip_angle"] - 4), 0.034 * c)
    _guard(k, -0.05, -0.01, -0.031, 0.022, -0.034)
    if optic == "scope":
        _scope(k, 0.0, 0.06, 0.22, 0.012)
    elif optic == "red_dot":
        _reddot(k, 0.0, 0.058)
    elif optic != "none" and k.small:
        k.box("sight", "accent", (0.03, 0, 0.061), (0.02, 0.012, 0.012))
    if stock in ("fixed", "adjustable"):
        _stock(k, stock, -0.11, 0.02, furn)


_GUN_AUTO = {  # variant: (optic, stock, magazine)
    "pistol": ("irons", "none", "none"), "rifle": ("scope", "fixed", "none"), "smg": ("irons", "adjustable", "straight"),
    "assault": ("red_dot", "adjustable", "curved"), "shotgun": ("irons", "fixed", "none"),
    "blaster": ("irons", "none", "none"),
}
_GUN_FN = {"pistol": _g_pistol, "rifle": _g_rifle, "smg": _g_smg, "assault": _g_assault, "shotgun": _g_shotgun,
           "blaster": _g_blaster}
_GUN_NAME = {"pistol": "pistol", "rifle": "hunting rifle", "smg": "submachine gun", "assault": "assault rifle",
             "shotgun": "pump shotgun", "blaster": "sci-fi blaster"}


def build_firearm(P, R, style):
    v = P["variant"]
    o, s, m = _GUN_AUTO[v]
    optic = o if P["optic"] == "auto" else P["optic"]
    stock = s if P["stock"] == "auto" else P["stock"]
    mag = m if P["magazine"] == "auto" else P["magazine"]
    wood = P["furniture"] == "wood" or (P["furniture"] == "auto" and v in ("rifle", "shotgun"))
    if wood:
        R = _alt(R, GUN_ROLES, "furniture", "wood", "#7a4b2a")
    if v == "blaster":
        R = _alt(R, GUN_ROLES, "body", "painted_metal", "#c9ced4")
        R = _alt(R, GUN_ROLES, "furniture", "polymer", "#2f3238")
        R = _alt(R, GUN_ROLES, "accent", "painted_metal", "#d8762a")
    k = Kit(_GUN_NAME[v], "weapon", style, R)
    _GUN_FN[v](k, P, "furniture", optic, stock, mag)
    return k.spec(P["size"])


# ------------------------------------------------------------------ sword
SWORD_ROLES = {
    "blade": Role("#b9bcc2", "bare_metal", "blade steel"),
    "fittings": Role("#6e6a64", "gunmetal", "crossguard and pommel"),
    "grip": Role("#4a2e1c", "leather", "grip wrap"),
    "gem": Role("#b0303a", "glass", "pommel/guard gem (only when gem=true)"),
}
SWORD_PARAMS = {
    "variant": Param("enum", "longsword", choices=("longsword", "shortsword", "sabre", "katana", "broadsword"),
                     doc="blade family"),
    "length": Param("num", 1.0, 0.7, 1.3, doc="blade length factor"),
    "width": Param("num", 1.0, 0.7, 1.5, doc="blade width factor"),
    "guard": Param("enum", "auto", choices=("auto", "straight", "curved", "disc", "knuckle", "none")),
    "pommel": Param("enum", "auto", choices=("auto", "ball", "disc", "wheel", "cap")),
    "fuller": Param("bool", True, doc="groove along the blade"),
    "wrap": Param("bool", True, doc="ridged grip wrap"),
    "gem": Param("bool", False, doc="gem set in the pommel and guard"),
}
# variant: blade length, base width, curve (m of sag at the tip), grip length, guard, pommel
_SWORD = {"longsword": (0.90, 0.050, 0.0, 0.22, "straight", "wheel"),
          "shortsword": (0.55, 0.058, 0.0, 0.12, "straight", "ball"),
          "broadsword": (0.80, 0.064, 0.0, 0.14, "curved", "disc"),
          "sabre": (0.80, 0.034, 0.055, 0.13, "knuckle", "cap"),
          "katana": (0.70, 0.032, 0.022, 0.26, "disc", "cap")}


def _blade_pts(L, w, curve, variant):
    """Blade outline in X-Z (edges up/down, flat faces to +-Y): base at x=0, tip at x=L."""
    if variant in ("sabre", "katana"):
        n = 10
        spine, edge = [], []
        for i in range(n + 1):
            t = i / n
            sag = curve * t * t
            ww = w * (1 - 0.25 * t)
            spine.append((L * t, w / 2 + sag))
            edge.append((L * t, -w / 2 + sag + (0 if t < 0.85 else (t - 0.85) / 0.15 * ww * 0.9)))
        tip = (L + w * 0.35, curve + w * 0.35)
        return edge[:-1] + [tip] + list(reversed(spine[:-1]))
    tipl = w * (1.8 if variant != "shortsword" else 2.2)
    wt = w * (0.72 if variant == "longsword" else 0.85)
    if variant == "shortsword":  # leaf blade
        return [(0, -w / 2), (L * 0.55, -w * 0.58), (L - tipl, -wt / 2), (L, 0), (L - tipl, wt / 2), (L * 0.55, w * 0.58),
                (0, w / 2)]
    return [(0, -w / 2), (L - tipl, -wt / 2), (L, 0), (L - tipl, wt / 2), (0, w / 2)]


def build_sword(P, R, style):
    v = P["variant"]
    L0, w0, curve, gl, g_auto, p_auto = _SWORD[v]
    k = Kit(v, "weapon", style, R)
    c = k.chunk
    L, w = L0 * P["length"], w0 * P["width"] * (1.12 if k.sty or k.rbx else 1.0)
    th = 0.006 * c
    guard = g_auto if P["guard"] == "auto" else P["guard"]
    pommel = p_auto if P["pommel"] == "auto" else P["pommel"]
    if curve:
        k.prof("blade", "blade", _blade_pts(L, w, curve, v), th)
    else:  # diamond section: four thin slabs meeting at the edges, ridge down the middle
        outline = _blade_pts(L, w, curve, v)
        upper = [(0.0, 0.0), (L, 0.0)] + sorted([p for p in outline if p[1] > 1e-9], key=lambda p: -p[0])
        lower = [(x, -z) for x, z in upper]
        ts = 0.0026 * c
        d = max(0.0006, (0.0075 * c - ts) / 2)
        th_deg = math.degrees(math.asin(min(0.45, 2 * d / w)))
        k.prof("blade", "blade", upper, ts, pos=(0, d, 0), rot=[th_deg, 0, 0], mirror_y=True)
        k.prof("blade_low", "blade", lower, ts, pos=(0, d, 0), rot=[-th_deg, 0, 0], mirror_y=True)
        if P["fuller"] and k.small:
            fl = L * (0.6 if v != "shortsword" else 0.45)
            k.prof("fuller", "blade", [(0.03, -w * 0.07), (fl, -w * 0.05), (fl + 0.02, 0), (fl, w * 0.05), (0.03, w * 0.07)],
                   2 * d + ts + 0.0006, mat="gunmetal", color="#6a6e74")
    if k.small and v != "katana":
        k.box("ricasso", "fittings", (0.012, 0, 0), (0.024, th * 1.8, w * 0.7))
    gz = w * (2.0 if v in ("longsword", "broadsword") else 1.6) * (1.1 if k.sty else 1.0)
    gt = 0.022 * c
    if guard == "straight":
        k.prof("guard", "fittings", [(-gt / 2, -gz), (gt / 2, -gz * 0.98), (gt * 0.42, 0), (gt / 2, gz * 0.98),
                                     (-gt / 2, gz), (-gt * 0.42, 0)], 0.024 * c)
        if k.small:
            k.ball("guard_end", "fittings", (0, 0, gz), 0.013 * c)
            k.ball("guard_end_b", "fittings", (0, 0, -gz), 0.013 * c)
    elif guard == "curved":
        pts = [(0.028 * (abs(t) ** 2), 0, gz * t) for t in (-1, -0.6, -0.25, 0, 0.25, 0.6, 1)]
        k.tube("guard", "fittings", pts, 0.0105 * c)
        k.box("guard_block", "fittings", (0, 0, 0), (0.03, 0.03 * c, w * 1.1))
    elif guard == "disc":
        k.cyl("guard", "fittings", (-0.004, 0, 0), max(0.038, w * 1.2) * min(c, 1.15), 0.008 * c, "x")
        if k.small:
            k.cyl("collar", "fittings", (0.006, 0, 0), w * 0.42, 0.014, "x")
    elif guard == "knuckle":
        k.prof("guard", "fittings", [(-0.012, -w * 1.4), (0.008, -w * 1.5), (0.012, w * 1.0), (-0.01, w * 1.1)], 0.02 * c)
    gr = 0.014 * min(c, 1.25)
    k.lathe("grip", "grip", (0, 0, 0), [[-gl - 0.004, 0], [-gl - 0.004, gr * 0.85], [-gl * 0.5, gr * 1.08],
                                         [0.006, gr * 0.9], [0.006, 0]], "x")
    if P["wrap"] and not k.low:
        n = max(2, int(gl / (0.02 if k.fine else 0.04)))
        st = (gl - 0.02) / max(1, n - 1)
        k.ring("wrap", "grip", (-gl + 0.01, 0, 0), gr * 0.95, 0.0028 * c, "x", count=n, step=[st, 0, 0])
    px = -gl - 0.004
    if pommel == "ball":
        pr = 0.021 * c
        k.ball("pommel", "fittings", (px - pr * 0.7, 0, 0), pr)
    elif pommel == "disc":
        k.cyl("pommel", "fittings", (px - 0.008, 0, 0), 0.028 * c, 0.018, "x")
    elif pommel == "wheel":
        k.cyl("pommel", "fittings", (px - 0.024, 0, 0), 0.027 * c, 0.02 * c, "y")
    else:
        k.cone("pommel", "fittings", (px - 0.012, 0, 0), gr * 1.05, gr * 1.3, 0.024, "x")
    if guard == "knuckle":
        k.tube("knuckle_bow", "fittings", [(0.0, 0, -w * 1.45), (-gl * 0.3, 0, -w * 1.45 - 0.03),
                                           (-gl * 0.75, 0, -w * 1.4 - 0.03), (px - 0.01, 0, -0.012)], 0.005 * c)
    if P["gem"]:
        if pommel == "wheel":
            k.ball("gem", "gem", (px - 0.024, 0.01 * c, 0), 0.011 * c, scale=[1, 0.6, 1], mirror_y=True)
        else:
            k.ball("gem", "gem", (0, 0.012 * c, 0), 0.009 * c, scale=[1, 0.55, 1], mirror_y=True)
    return k.spec()


# ------------------------------------------------------------------ axe
AXE_ROLES = {
    "head": Role("#4f5257", "gunmetal", "axe head"),
    "edge": Role("#c9ccd1", "bare_metal", "polished cutting edge"),
    "handle": Role("#a0703f", "wood", "handle / haft"),
    "grip": Role("#3a2a1e", "leather", "grip wrap, butt cap, langets"),
}
AXE_PARAMS = {
    "variant": Param("enum", "wood", choices=("wood", "fire", "battle", "hatchet"),
                     doc="felling axe | fire axe | battle axe | hatchet"),
    "length": Param("num", 1.0, 0.7, 1.4, doc="handle length factor"),
    "head_size": Param("num", 1.0, 0.75, 1.5),
    "bit": Param("enum", "auto", choices=("auto", "single", "double"), doc="one or two cutting edges"),
    "back": Param("enum", "auto", choices=("auto", "poll", "pick", "spike")),
    "wrap": Param("bool", False, doc="leather grip wrap"),
    "beard": Param("bool", False, doc="bearded (hooked) blade"),
}
_AXE = {"wood": (0.80, 1.0, "single", "poll"), "fire": (0.88, 1.05, "single", "pick"),
        "battle": (0.95, 1.15, "double", "spike"), "hatchet": (0.38, 0.75, "single", "poll")}


def _bez(p0, p1, p2, n):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]


def _axe_bit(k, pid, hx, hz, dirz, hs, beard, crescent=False):
    """Cheek flaring away from the eye plus a curved edge strip; dirz=+1 bit points up, -1 down."""
    c = k.chunk
    hgt = 0.11 * hs
    bw = 0.065 * hs
    if crescent:  # battle axe: narrow neck, concave sides, wide curved edge with swept horns
        hgt, span, nw = 0.13 * hs, 0.21 * hs, 0.05 * hs
        tip = 0.78 * hgt
        right = _bez((nw / 2, 0), (nw / 2, hgt * 0.55), (span / 2, tip), 6)
        left = _bez((-span / 2, tip), (-nw / 2, hgt * 0.55), (-nw / 2, 0), 6)
        R = (span / 2) ** 2 / (2 * (hgt - tip)) + (hgt - tip) / 2
        zc = hgt - R
        a0 = math.degrees(math.atan2(tip - zc, span / 2))
        edge = _arc(0, zc, R, a0, 180 - a0, 10)
        e_in = 0.022 * hs

        def shrink(pts, d):
            return [(x * (R - d) / R, zc + (z - zc) * (R - d) / R) for x, z in pts]
        inner = shrink(edge, e_in * 0.6)
        pts = right[:-1] + inner + left[1:]
        k.prof(pid, "head", [(hx + x, hz + dirz * z) for x, z in pts], 0.016 * c)
        band = edge + list(reversed(shrink(edge, e_in)))
        k.prof(pid + "_edge", "edge", [(hx + x, hz + dirz * z) for x, z in band], 0.011 * c)
        return
    k.box(pid, "head", (hx, 0, hz + dirz * hgt / 2), (bw, 0.034 * c, hgt), taper=[1.75, 0.28],
          rot=[0, 0, 0] if dirz > 0 else [180, 0, 0])
    span = bw * 1.75
    ez = hz + dirz * hgt
    arc = []
    for i in range(9):
        t = -1 + 2 * i / 8
        arc.append((hx + t * span * 0.62, ez + dirz * (0.012 * hs * (1 - t * t) - 0.004)))
    inner = [(x, z - dirz * 0.016 * hs) for x, z in reversed(arc)]
    if beard:
        lo = arc[0]
        inner = inner[:-1] + [(lo[0] + 0.012 * hs, lo[1] - dirz * 0.06 * hs), (lo[0] - 0.01 * hs, lo[1] - dirz * 0.05 * hs)]
    k.prof(pid + "_edge", "edge", arc + inner, 0.009 * c)


def build_axe(P, R, style):
    v = P["variant"]
    L0, hs0, bit_auto, back_auto = _AXE[v]
    if v == "fire":
        R = _alt(R, AXE_ROLES, "head", "painted_metal", "#a3281f")
        R = _alt(R, AXE_ROLES, "handle", "wood", "#c8a060")
    if v == "battle":
        R = _alt(R, AXE_ROLES, "handle", "dark_wood", "#5a3a22")
    k = Kit(f"{v} axe", "weapon", style, R)
    c = k.chunk
    L = L0 * P["length"]
    hs = hs0 * P["head_size"] * (1.2 if k.sty or k.rbx else 1.0)
    bit = bit_auto if P["bit"] == "auto" else P["bit"]
    back = back_auto if P["back"] == "auto" else P["back"]
    hr = 0.016 * c * (1.15 if v == "battle" else 1.0)
    sway = 0.012 if v in ("wood", "hatchet") else 0.0
    k.tube("handle", "handle", [(0.0, 0, -sway * 0.8), (L * 0.25, 0, sway * 0.3), (L * 0.6, 0, sway * 0.5), (L, 0, 0.0)], hr)
    k.ball("knob", "handle" if v != "battle" else "grip", (0.0, 0, -sway * 0.8), hr * 1.35, scale=[1.0, 0.8, 1.25])
    hx = L - 0.05 * hs
    eye_h = 0.045 * hs
    k.box("eye", "head", (hx, 0, 0), (0.055 * hs, 0.04 * c, eye_h + 0.02))
    cres = v == "battle"
    _axe_bit(k, "blade", hx, eye_h / 2 - 0.004, 1, hs, P["beard"], cres)
    if bit == "double":
        _axe_bit(k, "blade_b", hx, -eye_h / 2 + 0.004, -1, hs, P["beard"], cres)
    elif back == "pick":
        k.box("pick", "head", (hx, 0, -eye_h / 2 - 0.05 * hs), (0.04 * hs, 0.028 * c, 0.1 * hs), taper=[0.25, 0.4],
              rot=[180, 0, 0])
    elif back == "spike":
        k.cone("spike", "head", (hx, 0, -eye_h / 2 - 0.03 * hs), 0.016 * hs, 0.0, 0.06 * hs, "z", rot=[180, 0, 0])
    else:
        k.box("poll", "head", (hx, 0, -eye_h / 2 - 0.012 * hs), (0.05 * hs, 0.042 * c, 0.03 * hs))
    if v == "battle":
        k.cone("top_spike", "head", (L + 0.03 * hs, 0, 0), hr * 0.9, 0.0, 0.07 * hs, "x")
        if k.small:
            k.box("langet", "grip", (hx - 0.09 * hs, 0, 0), (0.12 * hs, hr * 2.3, 0.012))
    if k.small and v in ("wood", "hatchet", "fire"):
        k.cone("wedge", "edge", (L + 0.002, 0, 0), hr * 0.9, hr * 0.7, 0.008, "x")
    if k.small:
        k.ring("collar", "grip" if v != "fire" else "edge", (hx - 0.045 * hs, 0, sway * 0.05), hr * 1.02, 0.004 * c, "x")
    if k.fine:
        k.cyl("eye_pin", "edge", (hx - 0.012 * hs, 0, 0), 0.004, 0.044 * c, "y")
        k.cyl("eye_pin_b", "edge", (hx + 0.012 * hs, 0, 0), 0.004, 0.044 * c, "y")
    if P["wrap"] or v == "battle":
        k.cyl("grip_wrap", "grip", (0.11 * L + 0.02, 0, -sway * 0.15), hr * 1.08, 0.2 * L, "x")
        if not k.low:
            n = 4 if k.fine else 2
            k.ring("wrap", "grip", (0.03 + 0.02, 0, -sway * 0.3), hr * 1.12, 0.004 * c, "x", count=n,
                   step=[0.18 * L / n, 0, 0])
    return k.spec()


# ------------------------------------------------------------------ vehicle
VEH_ROLES = {
    "body": Role("#b8402f", "painted_metal", "main paint"),
    "trim": Role("#2b2d31", "plastic", "bumpers, grille, frame, seats"),
    "glass": Role("#22313a", "glass", "windows"),
    "tire": Role("#1b1b1b", "rubber", "tires"),
    "rim": Role("#a9adb3", "bare_metal", "wheel rims and bare metal parts"),
    "light": Role("#ffe7b0", "emissive", "headlights"),
}
VEH_PARAMS = {
    "variant": Param("enum", "car", choices=("car", "van", "pickup", "tractor", "atv", "kart"),
                     doc="sedan car | delivery van | pickup truck | farm tractor | quad bike | go-kart"),
    "size": Param("num", 1.0, 0.85, 1.2, doc="overall scale"),
    "wheel_scale": Param("num", 1.0, 0.85, 1.3, doc="wheel size factor"),
    "ride_height": Param("num", 1.0, 0.8, 1.6, doc="ground clearance factor (lifted trucks > 1)"),
    "roof_rack": Param("bool", False),
    "bull_bar": Param("bool", False, doc="front push bar"),
    "light_bar": Param("bool", False, doc="roof light bar"),
    "exhaust": Param("bool", True),
    "cab": Param("enum", "closed", choices=("closed", "open"), doc="tractor cab: glazed or open roll bar"),
    "racks": Param("bool", True, doc="ATV cargo racks"),
}
_VEH_PAINT = {"car": "#b8402f", "van": "#d8d4cb", "pickup": "#2f5f8a", "tractor": "#3f7a3a", "atv": "#5f6b3a",
              "kart": "#e07a1f"}
_TAIL = "#c8321f"


def _wheel(k, pid, x, y, zc, r, w, kind="car", knobby=False):
    """Tire (axis y) + rim on the left side, mirrored to the right."""
    cuts = None
    if knobby and k.cuts_ok:
        cuts = []
        for i in range(12):
            phi = i * 30.0
            side = 1 if i % 2 == 0 else -1
            cuts.append(_cbox((0.13 * r, w * 0.56, 0.11 * r),
                              pos=(r * math.cos(math.radians(phi)), side * w * 0.24, r * math.sin(math.radians(phi))),
                              rot=(0, 90 - phi, 0)))
    k.cyl(pid, "tire", (x, y, zc), r, w, "y", mirror_y=True, bevel=None if k.low else _r(0.2 * w), cuts=cuts)
    yo = y + w / 2
    rim_r = r * (0.62 if kind in ("car", "kart") else 0.58)
    if kind == "car" and k.fine:
        k.cyl(pid + "_disc", "trim", (x, yo - 0.006, zc), rim_r, 0.014, "y", mirror_y=True)
        k.ring(pid + "_lip", "rim", (x, yo - 0.002, zc), rim_r, 0.012, "y", mirror_y=True)
        for i in range(5):
            a = math.radians(72 * i)
            k.box(f"{pid}_spoke{i}", "rim", (x + 0.48 * rim_r * math.sin(a), yo + 0.002, zc + 0.48 * rim_r * math.cos(a)),
                  (0.045 * rim_r / 0.2, 0.014, rim_r * 0.92), rot=[0, 72 * i, 0], mirror_y=True)
    else:
        k.cyl(pid + "_rim", "rim", (x, yo - 0.004, zc), rim_r, 0.016 + 0.01 * (k.chunk - 1), "y", mirror_y=True)
        if not k.low and kind in ("car", "tractor", "atv"):
            k.ring(pid + "_lip", "rim", (x, yo + 0.002, zc), rim_r * 0.97, 0.012 * k.chunk * max(1.0, r / 0.35), "y",
                   mirror_y=True)
    if k.small:
        k.cyl(pid + "_hub", "rim", (x, yo + 0.008, zc), rim_r * 0.3, 0.022, "y", mirror_y=True)
    if knobby and k.rbx and r > 0.6:
        for i in range(6):
            a = math.radians(60 * i + 30)
            k.box(f"{pid}_lug{i}", "tire", (x + r * math.cos(a), y, zc + r * math.sin(a)), (0.1 * r, w * 0.9, 0.1 * r),
                  rot=[0, 60 - 60 * i, 0], mirror_y=True)


def _side_profile(xF, xR, zb, arches, top):
    """Side outline (x, z): bottom at zb with arch notches over the wheels, then `top` points from rear to front."""
    pts = [(xF, zb)]
    m = 0.02
    for xw, zc, ra in sorted(arches, key=lambda a: -a[0]):
        dz = zb - zc
        if abs(dz) >= ra * 0.98:
            continue
        dx = math.sqrt(ra * ra - dz * dz)
        a0 = math.degrees(math.atan2(dz, dx))
        a1 = 180 - a0
        if xw + dx > xF - m:  # arch would run past the front end: clip it with a vertical step
            a0 = math.degrees(math.acos(max(-1.0, min(1.0, (xF - m - xw) / ra))))
            pts.append((xw + ra * math.cos(math.radians(a0)), zb))
        if xw - dx < xR + m:
            a1 = math.degrees(math.acos(max(-1.0, min(1.0, (xR + m - xw) / ra))))
        pts += _arc(xw, zc, ra, a0, a1, 8)
        if a1 < 180 - math.degrees(math.atan2(dz, dx)) - 1e-6:
            pts.append((xw + ra * math.cos(math.radians(a1)), zb))
    pts.append((xR, zb))
    return pts + list(top)


def _glass_side(k, A0, A1, C0, C1, z0, z1, thick, frame=0.07, pillar=True):
    """Side window pane inside the greenhouse lines A (front pillar) and C (rear pillar), plus a B-pillar."""
    pts = [(_line_x(A0, A1, z0) - frame, z0), (_line_x(A0, A1, z1) - frame, z1),
           (_line_x(C0, C1, z1) + frame, z1), (_line_x(C0, C1, z0) + frame, z0)]
    k.prof("side_glass", "glass", pts, thick + 0.014)
    if pillar:
        xb = 0.5 * (_line_x(A0, A1, (z0 + z1) / 2) + _line_x(C0, C1, (z0 + z1) / 2))
        k.box("b_pillar", "body", (xb, 0, (z0 + z1) / 2), (0.075, thick + 0.026, z1 - z0 + 0.02))


def _car_common(k, P, xF, xR, W, zl, zb, wheels, bumper_z, bumper_role="trim", lights_z=0.65, plate=True):
    c = k.chunk
    k.box("bumper_f", bumper_role, (xF, 0, bumper_z + zl), (0.15, W * 0.97, 0.17 + 0.03 * (c - 1)))
    k.box("bumper_r", bumper_role, (xR, 0, bumper_z + 0.02 + zl), (0.15, W * 0.97, 0.17 + 0.03 * (c - 1)))
    if plate and k.small:
        k.box("plate_f", "trim", (xF + 0.078, 0, bumper_z + zl), (0.01, 0.34, 0.11), mat="plastic", color="#d9d6c8")
        k.box("plate_r", "trim", (xR - 0.078, 0, bumper_z + 0.02 + zl), (0.01, 0.34, 0.11), mat="plastic",
              color="#d9d6c8")
    for xw, yw, r, w in wheels:
        k.cyl(f"axle{'f' if xw > 0 else 'r'}", "trim", (xw, 0, r), 0.045, 2 * yw, "y")
    if P["exhaust"]:
        k.cyl("exhaust", "rim", (xR + 0.03, -W * 0.25, zb + 0.012), 0.035, 0.22, "x")
    if P["bull_bar"]:
        x0, x1 = xF + 0.05, xF + 0.17
        zb, zt = bumper_z - 0.05 + zl, lights_z + 0.12 + zl
        k.tube("bull_bar", "rim", [(x0, W * 0.3, zb), (x1, W * 0.3, zb + 0.05), (x1, W * 0.3, zt), (x1, -W * 0.3, zt),
                                   (x1, -W * 0.3, zb + 0.05), (x0, -W * 0.3, zb)], 0.03 * c)
        k.cyl("bull_cross", "rim", (x1, 0, (zb + zt) / 2), 0.025 * c, W * 0.6, "y")


def _roof_kit(k, P, x0, x1, zroof, wroof):
    if P["roof_rack"]:
        k.box("rack_rail", "trim", ((x0 + x1) / 2, wroof / 2 - 0.05, zroof + 0.02), (x1 - x0, 0.05, 0.05), mirror_y=True)
        for i, x in enumerate((x0 + 0.15, (x0 + x1) / 2, x1 - 0.15)):
            k.box(f"rack_bar{i}", "trim", (x, 0, zroof + 0.06), (0.05, wroof - 0.02, 0.035))
    if P["light_bar"]:
        k.box("light_bar_housing", "trim", (x1 - 0.12, 0, zroof + (0.11 if P["roof_rack"] else 0.04)),
              (0.1, min(1.1, wroof * 0.8), 0.08))
        k.box("light_bar", "light", (x1 - 0.065, 0, zroof + (0.11 if P["roof_rack"] else 0.04)),
              (0.012, min(1.0, wroof * 0.72), 0.05))


def _v_car(k, P):
    ws, rh = P["wheel_scale"], P["ride_height"]
    sty = 1.0 if k.pbr else 1.06
    r, w = 0.32 * ws * sty, 0.21 * (1.08 if not k.pbr else 1.0)
    zl = (r - 0.32) + 0.15 * (rh - 1)
    W, xF, xR = 1.8, 2.15, -2.15
    xf, xr, yw = 1.32, -1.32, 0.78
    ra = r + 0.05
    top = [(-2.17, 0.45 + zl), (-2.15, 0.93 + zl), (-1.9, 0.98 + zl), (-1.25, 0.99 + zl), (0.75, 0.95 + zl),
           (1.9, 0.82 + zl), (2.12, 0.74 + zl), (2.19, 0.5 + zl)]
    k.prof("body", "body", _side_profile(xF, xR, 0.2 + zl, [(xf, r, ra), (xr, r, ra)], top), W, bevel=k.bev(12),
           seams=[{"axis": "z", "at": [0.28]}])
    A0, A1 = (0.74, 0.93 + zl), (0.05, 1.40 + zl)
    C0, C1 = (-1.32, 0.97 + zl), (-0.8, 1.41 + zl)
    Wc = 1.46
    k.prof("cabin", "body", [A0, A1, (-0.3, 1.435 + zl), C1, C0], Wc, bevel=k.bev(10))
    _glass_side(k, A0, A1, C0, C1, 1.0 + zl, 1.36 + zl, Wc)
    inside = (-0.3, 1.1 + zl)
    _slab_on_line(k, "windshield", "glass", A0, A1, Wc * 0.9, 0.014, inside)
    _slab_on_line(k, "rear_window", "glass", C0, C1, Wc * 0.88, 0.014, inside)
    _car_common(k, P, 2.16, -2.17, W, zl, 0.2 + zl, [(xf, yw, r, w), (xr, yw, r, w)], 0.36, lights_z=0.66)
    k.box("grille", "trim", (2.165, 0, 0.58 + zl), (0.04, 0.7, 0.14),
          cuts=[_cbox((0.03, 0.62, 0.012), side="front", u=0.0, v=-0.6, count=4, step=(0, 0, 0.03))] if k.fine else None)
    k.box("headlight", "light", (2.13, 0.6, 0.66 + zl), (0.07, 0.32, 0.09), mirror_y=True)
    k.box("taillight", "light", (-2.16, 0.62, 0.86 + zl), (0.05, 0.3, 0.1), mirror_y=True, mat="emissive", color=_TAIL)
    if k.small:
        k.box("mirror_arm", "body", (0.62, 0.84, 1.0 + zl), (0.06, 0.24, 0.03), mirror_y=True)
        k.box("mirror", "body", (0.62, 0.96, 1.025 + zl), (0.08, 0.05, 0.08), mirror_y=True)
    if k.fine:
        for i, x in enumerate((0.1, -0.8)):
            k.box(f"door_handle{i}", "trim", (x, W / 2 + 0.006, 0.86 + zl), (0.12, 0.02, 0.025), mirror_y=True)
    for i, (xw, ) in enumerate(((xf, ), (xr, ))):
        _wheel(k, f"wheel{'f' if i == 0 else 'r'}", xw, yw, r, r, w, "car")
    _roof_kit(k, P, -0.8, 0.0, 1.43 + zl, Wc)


def _v_van(k, P):
    ws, rh = P["wheel_scale"], P["ride_height"]
    r, w = 0.34 * ws * (1.0 if k.pbr else 1.06), 0.23
    zl = (r - 0.34) + 0.15 * (rh - 1)
    W, xF, xR = 1.95, 2.48, -2.5
    xf, xr, yw = 1.62, -1.62, 0.84
    ra = r + 0.055
    ws0, ws1 = (1.95, 1.18 + zl), (1.2, 2.02 + zl)
    top = [(-2.52, 0.5 + zl), (-2.5, 2.0 + zl), (-2.42, 2.08 + zl), (1.08, 2.08 + zl), ws1, ws0, (2.42, 1.0 + zl),
           (2.52, 0.62 + zl)]
    k.prof("body", "body", _side_profile(xF, xR, 0.24 + zl, [(xf, r, ra), (xr, r, ra)], top), W, bevel=k.bev(14),
           seams=[{"axis": "z", "at": [-0.35]}])
    z0, z1 = 1.25 + zl, 1.9 + zl
    pts = [(_line_x(ws0, ws1, z0) - 0.09, z0), (_line_x(ws0, ws1, z1) - 0.09, z1), (0.55, z1), (0.55, z0)]
    k.prof("side_glass", "glass", pts, W + 0.014)
    _slab_on_line(k, "windshield", "glass", ws0, ws1, W * 0.88, 0.014, (0.0, 1.5 + zl))
    k.box("rear_glass", "glass", (-2.505, 0.45, 1.55 + zl), (0.014, 0.74, 0.5), mirror_y=True)
    _car_common(k, P, 2.49, -2.5, W, zl, 0.24 + zl, [(xf, yw, r, w), (xr, yw, r, w)], 0.4, lights_z=0.85)
    k.box("grille", "trim", (2.49, 0, 0.78 + zl), (0.05, 0.9, 0.2),
          cuts=[_cbox((0.03, 0.8, 0.014), side="front", u=0.0, v=-0.6, count=4, step=(0, 0, 0.04))] if k.fine else None)
    k.box("headlight", "light", (2.47, 0.66, 0.84 + zl), (0.06, 0.3, 0.12), mirror_y=True)
    k.box("taillight", "light", (-2.515, 0.88, 1.0 + zl), (0.04, 0.12, 0.36), mirror_y=True, mat="emissive", color=_TAIL)
    if k.small:
        zm = 1.32 + zl
        xm = _line_x(ws0, ws1, zm) - 0.05
        k.box("mirror_arm", "body", (xm, W / 2 + 0.04, zm), (0.06, 0.12, 0.04), mirror_y=True)
        k.box("mirror", "trim", (xm, W / 2 + 0.11, zm + 0.03), (0.07, 0.06, 0.22), mirror_y=True)
    if k.fine:
        k.box("door_handle", "trim", (0.9, W / 2 + 0.006, 1.2 + zl), (0.12, 0.02, 0.03), mirror_y=True)
        k.box("slide_track", "trim", (-0.4, -(W / 2 + 0.004), 1.62 + zl), (1.2, 0.015, 0.02))
    _wheel(k, "wheelf", xf, yw, r, r, w, "car")
    _wheel(k, "wheelr", xr, yw, r, r, w, "car")
    _roof_kit(k, P, -2.2, 0.9, 2.08 + zl, W)


def _v_pickup(k, P):
    ws, rh = P["wheel_scale"], P["ride_height"]
    r, w = 0.38 * ws * (1.0 if k.pbr else 1.06), 0.26
    zl = (r - 0.38) + 0.2 * (rh - 1)
    W, xF, xR = 1.9, 2.62, -2.62
    xf, xr, yw = 1.65, -1.75, 0.8
    ra = r + 0.06
    belt = max(1.22, r + ra + 0.2) + zl
    floor = r + ra + 0.06 + max(0.0, zl)
    xcab = -0.55
    top = [(-2.64, 0.6 + zl), (-2.62, floor), (xcab, floor), (xcab, belt), (1.0, belt), (2.5, belt - 0.07),
           (2.66, 0.78 + zl)]
    k.prof("body", "body", _side_profile(xF, xR, 0.32 + zl, [(xf, r, ra), (xr, r, ra)], top), W, bevel=k.bev(12))
    A0, A1 = (1.0, belt - 0.02), (0.3, belt + 0.66)
    C0, C1 = (xcab, belt - 0.02), (xcab + 0.1, belt + 0.68)
    Wc = 1.72
    k.prof("cab", "body", [A0, A1, (-0.1, belt + 0.69), C1, C0], Wc, bevel=k.bev(10))
    _glass_side(k, A0, A1, C0, C1, belt + 0.08, belt + 0.6, Wc)
    _slab_on_line(k, "windshield", "glass", A0, A1, Wc * 0.9, 0.014, (0.2, belt + 0.3))
    _slab_on_line(k, "rear_window", "glass", C0, C1, Wc * 0.8, 0.014, (0.2, belt + 0.3), inset=0.75)
    wall = belt + 0.02 - floor
    lb = xcab - xR
    k.box("bed_wall", "body", ((xR + xcab) / 2, W / 2 - 0.03, floor + wall / 2 - 0.01), (lb, 0.06, wall), mirror_y=True)
    k.box("tailgate", "body", (xR + 0.03, 0, floor + wall / 2 - 0.01), (0.06, W - 0.02, wall))
    k.box("bed_front", "body", (xcab - 0.025, 0, floor + wall / 2 - 0.01), (0.05, W - 0.02, wall))
    if k.fine:
        k.box("bed_rail_cap", "trim", ((xR + xcab) / 2, W / 2 - 0.03, floor + wall), (lb, 0.075, 0.025), mirror_y=True)
        k.box("tailgate_handle", "trim", (xR - 0.003, 0, floor + wall - 0.12), (0.02, 0.24, 0.05))
    _car_common(k, P, 2.63, -2.63, W, zl, 0.32 + zl, [(xf, yw, r, w), (xr, yw, r, w)], 0.5, bumper_role="rim",
                lights_z=belt - 0.25 - zl)
    k.box("grille", "trim", (2.62, 0, belt - 0.3), (0.06, 1.0, 0.32),
          cuts=[_cbox((0.04, 0.9, 0.02), side="front", u=0.0, v=-0.6, count=4, step=(0, 0, 0.06))] if k.fine else None)
    k.box("headlight", "light", (2.6, 0.7, belt - 0.22), (0.07, 0.26, 0.13), mirror_y=True)
    k.box("taillight", "light", (xR - 0.01, W / 2 - 0.03, floor + wall * 0.55), (0.03, 0.08, 0.26), mirror_y=True,
          mat="emissive", color=_TAIL)
    if k.small:
        k.box("mirror_arm", "body", (0.88, Wc / 2 + 0.07, belt + 0.05), (0.06, 0.16, 0.04), mirror_y=True)
        k.box("mirror", "trim", (0.88, Wc / 2 + 0.16, belt + 0.1), (0.07, 0.06, 0.18), mirror_y=True)
    _wheel(k, "wheelf", xf, yw, r, r, w, "car")
    _wheel(k, "wheelr", xr, yw, r, r, w, "car")
    _roof_kit(k, P, -0.4, 0.25, belt + 0.69, Wc)


def _v_tractor(k, P):
    c = k.chunk
    ws = P["wheel_scale"]
    rr, wr = 0.78 * ws, 0.42
    rf, wf = 0.45 * ws, 0.26
    zl = rr - 0.78
    yr, yf = 0.82, 0.72
    k.prof("hood", "body", [(0.45, 0.95 + zl), (2.52, 0.95 + zl), (2.58, 1.32 + zl), (2.45, 1.47 + zl),
                            (0.45, 1.52 + zl)], 0.74, bevel=k.bev(8),
           seams=[{"axis": "x", "at": [0.5]}])
    k.box("chassis", "trim", (1.42, 0, 0.82 + zl), (2.25, 0.5, 0.32))
    k.box("grille", "trim", (2.565, 0, 1.12 + zl), (0.05, 0.62, 0.34),
          cuts=[_cbox((0.03, 0.52, 0.02), side="front", u=0.0, v=-0.7, count=5, step=(0, 0, 0.055))] if k.fine else None)
    k.box("weights", "trim", (2.62, 0, 0.78 + zl), (0.22, 0.62, 0.28),
          seams=[{"axis": "z", "at": [-0.3, 0.3]}])
    k.box("front_axle", "trim", (2.1, 0, rf), (0.2, 2 * (yf - wf / 2) + 0.02, 0.16))
    k.box("axle_pivot", "trim", (2.1, 0, (rf + 0.7 + zl) / 2), (0.24, 0.3, 0.7 + zl - rf + 0.06))
    k.box("transmission", "trim", (0.25, 0, 0.92 + zl), (0.85, 0.75, 0.6))
    k.cyl("rear_axle", "trim", (0, 0, rr), 0.12, 2 * (yr - wr / 2) + 0.02, "y")
    zp = 1.245 + zl
    k.box("platform", "trim", (-0.05, 0, zp), (1.2, 1.12, 0.06))
    k.box("inner_fender", "body", (0.0, 0.575, 1.2 + zl), (1.5, 0.05, 0.5), mirror_y=True)
    Ro, Ri = rr + 0.1, rr + 0.04
    band = _arc(0, rr, Ro, 25, 155, 10) + list(reversed(_arc(0, rr, Ri, 25, 155, 10)))
    k.prof("fender", "body", band, wr + 0.12, y=yr, mirror_y=True, bevel=k.bev(4))
    zt = zp + 0.03
    if P["cab"] == "closed":
        for i, x in enumerate((0.5, -0.6)):
            k.box(f"post{i}", "trim", (x, 0.5, zt + 0.65), (0.06, 0.06, 1.3), mirror_y=True)
        k.box("roof", "body", (-0.05, 0, zt + 1.34), (1.35, 1.25, 0.09), bevel=k.bev(6))
        k.box("glass_front", "glass", (0.5, 0, zt + 0.66), (0.015, 0.96, 1.2))
        k.box("glass_rear", "glass", (-0.6, 0, zt + 0.66), (0.015, 0.96, 1.2))
        k.box("glass_side", "glass", (-0.05, 0.5, zt + 0.66), (1.04, 0.015, 1.2), mirror_y=True)
        if k.small:
            k.box("work_light", "light", (0.62, 0.42, zt + 1.3), (0.06, 0.1, 0.07), mirror_y=True)
    else:
        k.tube("rops", "trim", [(-0.62, 0.5, zt), (-0.62, 0.5, zt + 1.1), (-0.62, -0.5, zt + 1.1), (-0.62, -0.5, zt)],
               0.04 * c)
    k.box("seat_post", "trim", (-0.25, 0, zt + 0.15), (0.15, 0.2, 0.32))
    k.box("seat", "trim", (-0.25, 0, zt + 0.35), (0.42, 0.5, 0.1), bevel=k.bev(4))
    k.box("seat_back", "trim", (-0.45, 0, zt + 0.58), (0.08, 0.48, 0.45), rot=[0, -8, 0], bevel=k.bev(4))
    k.box("dash", "trim", (0.4, 0, zt + 0.25), (0.2, 0.5, 0.5))
    k.tube("steering_column", "trim", [(0.38, 0, zt + 0.48), (0.18, 0, zt + 0.71)], 0.025)
    k.ring("steering_wheel", "trim", (0.17, 0, zt + 0.72), 0.19, 0.017 * c, "x", rot=[0, -131, 0])
    if P["exhaust"]:
        k.cyl("exhaust", "trim", (1.9, -0.22, 1.875 + zl), 0.045 * c, 0.95, "z", mat="bare_metal", color="#8a8d92")
        k.cyl("muffler", "trim", (1.9, -0.22, 1.8 + zl), 0.07 * c, 0.3, "z", mat="gunmetal", color="#3a3c40")
        if k.small:
            k.cone("exhaust_cap", "trim", (1.9, -0.22, 2.36 + zl), 0.05 * c, 0.04 * c, 0.04)
    if k.cuts_ok or k.rbx:
        k.cyl("air_intake", "trim", (1.9, 0.22, 1.62 + zl), 0.05 * c, 0.3, "z")
    k.box("headlight", "light", (2.49, 0.28, 1.3 + zl), (0.08, 0.12, 0.08), mirror_y=True)
    if k.small:
        k.box("lower_link", "trim", (-0.45, 0.3, 0.72 + zl), (0.62, 0.06, 0.08), rot=[0, -12, 0], mirror_y=True)
        k.box("top_link", "trim", (-0.4, 0, 1.12 + zl), (0.5, 0.06, 0.06))
        k.box("step", "trim", (0.05, 0.6, zp - 0.3), (0.3, 0.12, 0.03), mirror_y=True)
        k.box("step_hanger", "trim", (0.05, 0.56, zp - 0.15), (0.04, 0.03, 0.32), mirror_y=True)
    _wheel(k, "wheelr", 0.0, yr, rr, rr, wr, "tractor", knobby=True)
    _wheel(k, "wheelf", 2.1, yf, rf, rf, wf, "tractor", knobby=True)


def _v_atv(k, P):
    c = k.chunk
    ws, rh = P["wheel_scale"], P["ride_height"]
    rf, rr = 0.28 * ws, 0.29 * ws
    wf, wr = 0.2 * (1.1 if not k.pbr else 1), 0.24 * (1.1 if not k.pbr else 1)
    zl = (rr - 0.29) + 0.1 * (rh - 1)
    xf, xr, yf, yr = 0.62, -0.62, 0.45, 0.44
    k.tube("frame", "trim", [(0.9, 0.18, 0.3 + zl), (0.75, 0.2, 0.22 + zl), (-0.7, 0.2, 0.22 + zl),
                             (-0.88, 0.18, 0.35 + zl)], 0.022 * c, mirror_y=True)
    k.box("engine", "trim", (0.0, 0, 0.38 + zl), (0.45, 0.42, 0.32), mat="gunmetal", color="#3a3c40")
    k.box("tank", "body", (0.15, 0, 0.62 + zl), (0.6, 0.38, 0.2), bevel=k.bev(4))
    k.box("seat", "trim", (-0.3, 0, 0.775 + zl), (0.75, 0.34, 0.12), bevel=k.bev(5))
    raf = rf + 0.06
    front = _side_profile(1.0, 0.30, 0.5 + zl, [(xf, rf, raf)],
                          [(0.30, 0.72 + zl), (0.5, 0.76 + zl), (0.95, 0.76 + zl), (1.03, 0.66 + zl)])
    k.prof("front_body", "body", front, 1.08, bevel=k.bev(6))
    rar = rr + 0.06
    rear = _side_profile(-0.30, -1.0, 0.52 + zl, [(xr, rr, rar)],
                         [(-1.02, 0.7 + zl), (-0.95, 0.8 + zl), (-0.5, 0.8 + zl), (-0.3, 0.74 + zl)])
    k.prof("rear_body", "body", rear, 1.08, bevel=k.bev(6))
    k.tube("steer_column", "rim", [(0.42, 0, 0.62 + zl), (0.47, 0, 0.96 + zl)], 0.022)
    k.tube("handlebar", "rim", [(0.45, -0.38, 0.98 + zl), (0.47, -0.2, 0.96 + zl), (0.47, 0.2, 0.96 + zl),
                                (0.45, 0.38, 0.98 + zl)], 0.014 * c)
    k.cyl("grip", "tire", (0.45, 0.34, 0.975 + zl), 0.019 * c, 0.11, "y", mirror_y=True)
    k.box("headlight_pod", "body", (0.52, 0, 0.93 + zl), (0.12, 0.22, 0.08), bevel=k.bev(3))
    k.box("headlight", "light", (0.995, 0.25, 0.6 + zl), (0.05, 0.14, 0.06), mirror_y=True)
    if k.small:
        k.box("pod_light", "light", (0.582, 0, 0.93 + zl), (0.008, 0.14, 0.04))
    if P["racks"]:
        for nm, x0, x1, z in (("front_rack", 0.55, 0.93, 0.77), ("rear_rack", -0.97, -0.62, 0.81)):
            z += zl
            k.tube(nm, "rim", [(x0, 0.38, z), (x1, 0.38, z), (x1, -0.38, z), (x0, -0.38, z), (x0, 0.38, z)], 0.012 * c)
            k.cyl(nm + "_bar", "rim", (x0 + (x1 - x0) * 0.25, 0, z), 0.01 * c, 0.76, "y", count=2,
                  step=[(x1 - x0) * 0.5, 0, 0])
    k.box("footrest", "trim", (0.0, 0.30, 0.3 + zl), (0.42, 0.16, 0.03), mirror_y=True,
          cuts=[_cbox((0.03, 0.12, 0.04), pos=(-0.15, 0, 0), count=5, step=(0.075, 0, 0))] if k.fine else None)
    if P["exhaust"]:
        k.cyl("exhaust", "rim", (-0.85, -0.25, 0.56 + zl), 0.035 * c, 0.25, "x")
    k.tube("bumper", "trim", [(0.88, 0.18, 0.3 + zl), (1.08, 0.25, 0.36 + zl), (1.08, -0.25, 0.36 + zl),
                              (0.88, -0.18, 0.3 + zl)], 0.02 * c)
    if k.small:
        k.tube("a_arm", "trim", [(0.7, 0.2, 0.25 + zl), (xf, yf - wf / 2 + 0.01, rf)], 0.016 * c, mirror_y=True)
        k.tube("swing_arm", "trim", [(-0.45, 0.2, 0.25 + zl), (xr, yr - wr / 2 + 0.01, rr)], 0.02 * c, mirror_y=True)
    _wheel(k, "wheelf", xf, yf, rf, rf, wf, "atv", knobby=True)
    _wheel(k, "wheelr", xr, yr, rr, rr, wr, "atv", knobby=True)


def _v_kart(k, P):
    c = k.chunk
    ws = P["wheel_scale"]
    rf, rr = 0.13 * ws, 0.14 * ws
    wf, wr = 0.13, 0.2
    zl = rr - 0.14
    xf, xr, yf, yr = 0.55, -0.5, 0.52, 0.56
    fz = 0.07 + zl
    loop = [(0.82, 0.12), (0.62, 0.30), (0.2, 0.33), (-0.35, 0.33), (-0.62, 0.30), (-0.62, -0.30), (-0.35, -0.33),
            (0.2, -0.33), (0.62, -0.30), (0.82, -0.12), (0.82, 0.12)]
    k.tube("frame", "rim", [(x, y, fz) for x, y in loop], 0.016 * c)
    k.box("kingpin", "rim", (xf, 0.31, (fz + rf) / 2 + 0.01), (0.04, 0.04, rf - fz + 0.06), mirror_y=True)
    k.cyl("spindle", "rim", (xf, 0.38, rf), 0.015 * c, 0.17, "y", mirror_y=True)
    k.cyl("rear_axle", "rim", (xr, 0, rr), 0.02 * c, 2 * yr, "y")
    k.box("bearing", "rim", (xr, 0.3, (fz + rr) / 2), (0.06, 0.05, rr - fz + 0.05), mirror_y=True)
    k.box("floor", "trim", (0.05, 0, fz - 0.015), (0.9, 0.56, 0.012))
    seat = [(-0.04, fz - 0.02), (-0.38, fz - 0.02), (-0.47, fz + 0.1), (-0.5, fz + 0.48), (-0.42, fz + 0.49),
            (-0.38, fz + 0.15), (-0.32, fz + 0.09), (-0.04, fz + 0.09)]
    k.prof("seat", "trim", seat, 0.38, bevel=k.bev(4))
    k.tube("steering_column", "rim", [(0.48, 0, fz - 0.005), (0.18, 0, fz + 0.29)], 0.014 * c)
    k.ring("steering_wheel", "trim", (0.17, 0, fz + 0.3), 0.14, 0.013 * c, "x", rot=[0, -136, 0])
    if k.small:
        k.box("wheel_spoke", "trim", (0.17, 0, fz + 0.3), (0.02, 0.26, 0.02), rot=[0, -136 + 90, 0])
    k.tube("roll_bar", "rim", [(-0.55, 0.3, fz), (-0.55, 0.25, fz + 0.6), (-0.56, 0.15, fz + 0.71),
                               (-0.56, -0.15, fz + 0.71), (-0.55, -0.25, fz + 0.6), (-0.55, -0.3, fz)], 0.017 * c)
    k.tube("roll_brace", "rim", [(-0.55, 0.27, fz + 0.5), (-0.62, 0.3, fz)], 0.013 * c, mirror_y=True)
    k.box("engine", "trim", (-0.25, -0.38, fz + 0.13), (0.26, 0.2, 0.26), mat="gunmetal", color="#3a3c40",
          cuts=[_cbox((0.2, 0.03, 0.012), side="right", u=0.0, v=0.4, count=4, step=(0, 0, 0.022))] if k.fine else None)
    if P["exhaust"]:
        k.tube("exhaust_pipe", "rim", [(-0.3, -0.47, fz + 0.18), (-0.45, -0.5, fz + 0.25), (-0.68, -0.4, fz + 0.23)],
               0.02 * c)
        k.cyl("muffler", "rim", (-0.76, -0.4, fz + 0.23), 0.045 * c, 0.2, "x")
    k.box("side_pod", "body", (0.02, 0.41, fz + 0.06), (0.55, 0.14, 0.12), taper=[0.92, 0.8], mirror_y=True,
          bevel=k.bev(3))
    k.prof("nose", "body", [(0.62, fz - 0.01), (0.98, fz - 0.01), (1.0, fz + 0.07), (0.8, fz + 0.17), (0.62, fz + 0.15)],
           0.5, bevel=k.bev(3))
    k.tube("rear_bumper", "rim", [(-0.62, 0.3, fz), (-0.75, 0.36, fz + 0.04), (-0.75, -0.36, fz + 0.04),
                                  (-0.62, -0.3, fz)], 0.016 * c)
    if k.small:
        k.box("number_plate", "trim", (0.8, 0, fz + 0.2), (0.02, 0.22, 0.14), rot=[0, -25, 0], mat="plastic",
              color="#e8e2d0")
    if k.fine:
        k.box("pedal", "rim", (0.6, 0.08, fz + 0.04), (0.03, 0.05, 0.08), mirror_y=True)
    _wheel(k, "wheelf", xf, yf, rf, rf, wf, "kart")
    _wheel(k, "wheelr", xr, yr, rr, rr, wr, "kart")


_VEH_FN = {"car": _v_car, "van": _v_van, "pickup": _v_pickup, "tractor": _v_tractor, "atv": _v_atv, "kart": _v_kart}
_VEH_NAME = {"car": "car", "van": "van", "pickup": "pickup truck", "tractor": "tractor", "atv": "quad bike",
             "kart": "go-kart"}


def build_vehicle(P, R, style):
    v = P["variant"]
    R = _alt(R, VEH_ROLES, "body", "painted_metal", _VEH_PAINT[v])
    if v == "tractor":
        R = _alt(R, VEH_ROLES, "rim", "painted_metal", "#d9b23a")
    if v == "kart":
        R = _alt(R, VEH_ROLES, "rim", "painted_metal", "#3a3c40")
    k = Kit(_VEH_NAME[v], "vehicle", style, R)
    _VEH_FN[v](k, P)
    return k.spec(P["size"])


# ------------------------------------------------------------------ table / workbench / desk
TABLE_ROLES = {
    "top": Role("#9a6a3c", "wood", "table top"),
    "frame": Role("#6b4528", "wood", "legs, apron, shelf, drawers"),
    "metal": Role("#4a4c50", "gunmetal", "handles, vise screw, lamp arm"),
    "accent": Role("#2f6b5a", "painted_metal", "lamp shade, vise body"),
}
TABLE_PARAMS = {
    "variant": Param("enum", "table", choices=("table", "workbench", "desk"),
                     doc="dining/tavern table | heavy workbench | office desk with a drawer pedestal"),
    "length": Param("num", 1.4, 0.6, 2.4, doc="metres along X"),
    "depth": Param("num", 0.8, 0.4, 1.2, doc="metres along Y"),
    "height": Param("num", 0.75, 0.45, 1.1, doc="metres to the top surface"),
    "top": Param("num", 0.04, 0.02, 0.12, doc="top thickness in metres"),
    "legs": Param("enum", "square", choices=("square", "round", "turned", "tapered", "trestle")),
    "apron": Param("bool", True, doc="rails under the top"),
    "shelf": Param("bool", False, doc="lower shelf"),
    "drawers": Param("int", 0, 0, 4),
    "vise": Param("bool", False, doc="bench vise on the top"),
    "lamp": Param("bool", False, doc="desk lamp on the top"),
    "planks": Param("bool", False, doc="top made of planks"),
}


def _leg(k, pid, role, x, y, h, lw, style, mirror=True):
    if style == "round":
        k.cyl(pid, role, (x, y, h / 2), lw / 2, h, mirror_y=mirror)
    elif style == "tapered":
        k.box(pid, role, (x, y, h / 2), (lw * 0.62, lw * 0.62, h), taper=[1.6, 1.6], mirror_y=mirror)
    elif style == "turned":
        r = lw / 2
        pts = [[0, 0], [0, r * 0.75], [0.04 * h, r * 0.85], [0.08 * h, r * 0.62], [0.35 * h, r * 0.72],
               [0.62 * h, r * 0.9], [0.7 * h, r * 0.62], [0.76 * h, r], [h, r], [h, 0]]
        k.lathe(pid, role, (x, y, 0), pts, mirror_y=mirror)
    else:
        k.box(pid, role, (x, y, h / 2), (lw, lw, h), mirror_y=mirror)


def _lamp(k, bx, by, z):
    c = k.chunk
    k.cyl("lamp_base", "metal", (bx, by, z + 0.011), 0.075 * min(c, 1.2), 0.022)
    e = (bx + 0.06, by - 0.05, z + 0.34)
    h = (bx + 0.26, by - 0.17, z + 0.43)
    k.tube("lamp_arm_low", "metal", [(bx, by, z + 0.015), e], 0.009 * c)
    k.ball("lamp_joint", "metal", e, 0.016 * c)
    k.tube("lamp_arm_up", "metal", [e, h], 0.008 * c)
    k.cone("lamp_shade", "accent", (h[0] + 0.01, h[1] - 0.005, h[2] - 0.05), 0.075 * min(c, 1.2), 0.028, 0.11,
           rot=[12, 18, 0])
    k.ball("lamp_bulb", "accent", (h[0] + 0.022, h[1] - 0.017, h[2] - 0.1), 0.026, mat="emissive", color="#ffe9b0")


def _vise(k, x, y_edge, z):
    """Machinist vise on the top surface z, its moving jaw over the front edge (-Y)."""
    c = k.chunk
    k.cyl("vise_swivel", "metal", (x, y_edge + 0.12, z + 0.01), 0.06, 0.02)
    k.box("vise_body", "accent", (x, y_edge + 0.1, z + 0.05), (0.09, 0.2, 0.06))
    k.box("vise_jaw_fixed", "accent", (x, y_edge + 0.17, z + 0.105), (0.13, 0.04, 0.07))
    k.box("vise_jaw_moving", "accent", (x, y_edge + 0.02, z + 0.095), (0.13, 0.05, 0.07))
    k.cyl("vise_screw", "metal", (x, y_edge - 0.05, z + 0.06), 0.012 * c, 0.1, "y")
    k.cyl("vise_handle", "metal", (x, y_edge - 0.095, z + 0.06), 0.006 * c, 0.22, "x")
    if k.small:
        k.ball("vise_knob", "metal", (x + 0.11, y_edge - 0.095, z + 0.06), 0.014 * c)
        k.ball("vise_knob_b", "metal", (x - 0.11, y_edge - 0.095, z + 0.06), 0.014 * c)
    if k.fine:
        k.box("vise_plate", "metal", (x, y_edge + 0.149, z + 0.11), (0.13, 0.003, 0.05))
        k.box("vise_plate_b", "metal", (x, y_edge + 0.044, z + 0.1), (0.13, 0.003, 0.05))


def build_table(P, R, style):
    v = P["variant"]
    if v == "workbench":
        R = _alt(R, TABLE_ROLES, "top", "wood", "#b08850")
        R = _alt(R, TABLE_ROLES, "accent", "painted_metal", "#2f4f7a")
    if v == "desk":
        R = _alt(R, TABLE_ROLES, "top", "dark_wood", "#6a4529")
        R = _alt(R, TABLE_ROLES, "frame", "dark_wood", "#5a3a22")
    k = Kit(v, "furniture", style, R)
    c = k.chunk
    L, D, H = P["length"], P["depth"], P["height"]
    t = P["top"] * (1.25 if k.sty or k.rbx else 1.0)
    if v == "workbench":
        t = max(t, 0.06)
    lw = {"table": 0.06, "workbench": 0.085, "desk": 0.05}[v] * (c ** 0.6)
    ins = 0.03
    xl, yl = L / 2 - ins - lw / 2, D / 2 - ins - lw / 2
    ztop = H - t
    planks = P["planks"] or (v == "workbench" and not k.fine)
    if planks and not k.fine:
        n = max(3, round(D / 0.16))
        pw = D / n
        for i in range(n):
            jz = 0.002 * ((i * 37) % 3 - 1) if not k.low else 0.0
            k.box(f"plank{i}", "top", (0.004 * ((i * 53) % 3 - 1), -D / 2 + pw * (i + 0.5), H - t / 2 + jz),
                  (L - 0.006 * (i % 2), pw - 0.006, t))
        for s in (1, -1):
            k.box(f"batten{'a' if s > 0 else 'b'}", "frame", (s * (xl - lw), 0, ztop - 0.0115), (0.06, D - 0.06, 0.025))
    else:
        seams = [{"axis": "y", "at": [-1 + 2 * i / max(2, round(D / 0.15)) for i in range(1, max(2, round(D / 0.15)))]}] \
            if planks else None
        k.box("top", "top", (0, 0, H - t / 2), (L, D, t), seams=seams, bevel=k.bev(2))
    hl = ztop + 0.004
    legstyle = P["legs"]
    if v == "desk":
        wp = min(0.42, L * 0.35)
        xp = L / 2 - 0.02 - wp / 2
        hp = ztop - 0.03 + 0.004
        k.box("pedestal", "frame", (xp, 0, 0.03 + hp / 2), (wp, D - 0.04, hp), bevel=k.bev(1.5))
        k.box("plinth", "frame", (xp, 0, 0.015), (wp - 0.03, D - 0.08, 0.032))
        n = max(1, P["drawers"])
        gap = 0.008
        hd = (hp - 0.02 - gap * (n - 1)) / n
        for i in range(n):
            zc = 0.03 + 0.01 + hd / 2 + i * (hd + gap)
            k.box(f"drawer{i}", "frame", (xp, -(D / 2 - 0.02) - 0.007, zc), (wp - 0.025, 0.018, hd),
                  bevel=k.bev(1.5))
            if n == 1:
                k.cyl(f"knob{i}", "metal", (xp + wp * 0.32, -(D / 2 - 0.02) - 0.025, zc + hd * 0.3), 0.012, 0.022, "y")
            else:
                k.box(f"handle{i}", "metal", (xp, -(D / 2 - 0.02) - 0.022, zc + hd * 0.28),
                      (min(0.12, wp * 0.4), 0.016, 0.014))
        if legstyle in ("square", "trestle"):
            k.box("end_panel", "frame", (-L / 2 + 0.035, 0, hl / 2), (0.03 * c, D - 0.04, hl))
            xe = -L / 2 + 0.05
        else:
            _leg(k, "leg", "frame", -xl, yl, hl, lw, legstyle)
            k.box("apron_end", "frame", (-xl, 0, ztop - 0.04), (0.022 * c, 2 * yl, 0.08))
            xe = -xl
        xm0, xm1 = xe, xp - wp / 2 + 0.005
        k.box("modesty", "frame", ((xm0 + xm1) / 2, D / 2 - 0.06, ztop - (ztop * 0.45) / 2 + 0.002),
              (xm1 - xm0, 0.018 * c, ztop * 0.45))
    elif legstyle == "trestle":
        for s, nm in ((1, "a"), (-1, "b")):
            k.box(f"trestle_post{nm}", "frame", (s * xl, 0, hl / 2), (lw, lw * 1.6, hl))
            k.box(f"trestle_foot{nm}", "frame", (s * xl, 0, 0.03), (lw * 1.5, D * 0.85, 0.06), bevel=k.bev(2))
            k.box(f"trestle_cleat{nm}", "frame", (s * xl, 0, ztop - 0.025), (lw * 1.3, D * 0.85, 0.05))
        k.box("stretcher", "frame", (0, 0, hl * 0.42), (2 * xl, lw * 0.6, lw * 0.9))
    else:
        _leg(k, "leg_a", "frame", xl, yl, hl, lw, legstyle)
        _leg(k, "leg_b", "frame", -xl, yl, hl, lw, legstyle)
        ah = 0.1 if v == "workbench" else 0.08
        if P["apron"]:
            k.box("apron_long", "frame", (0, yl, ztop - ah / 2 + 0.002), (2 * xl, 0.022 * c, ah), mirror_y=True)
            k.box("apron_end_a", "frame", (xl, 0, ztop - ah / 2 + 0.002), (0.022 * c, 2 * yl, ah))
            k.box("apron_end_b", "frame", (-xl, 0, ztop - ah / 2 + 0.002), (0.022 * c, 2 * yl, ah))
        if P["drawers"] and P["apron"]:
            n = P["drawers"]
            wd = (2 * xl - lw) / n - 0.02
            for i in range(n):
                x = -xl + lw / 2 + 0.01 + wd / 2 + i * (wd + 0.02)
                k.box(f"drawer{i}", "frame", (x, -yl - 0.012, ztop - ah / 2 + 0.002), (wd, 0.012, ah * 0.78))
                if k.small:
                    k.cyl(f"knob{i}", "metal", (x, -yl - 0.026, ztop - ah / 2), 0.011, 0.018, "y")
        if P["shelf"]:
            k.box("shelf", "frame", (0, 0, 0.17), (2 * xl + lw, 2 * yl + lw, 0.024 * c))
        elif v == "workbench" or k.small:
            sh = 0.035 * c
            k.box("stretcher_end_a", "frame", (xl, 0, 0.15), (0.025 * c, 2 * yl, sh))
            k.box("stretcher_end_b", "frame", (-xl, 0, 0.15), (0.025 * c, 2 * yl, sh))
            k.box("stretcher", "frame", (0, 0, 0.15), (2 * xl, 0.025 * c, sh))
    if P["vise"]:
        _vise(k, L / 2 - 0.22, -D / 2, H)
    if P["lamp"]:
        _lamp(k, -L / 2 + 0.2, D / 2 - 0.16, H)
    if v == "workbench" and k.small:
        k.box("backboard", "frame", (0, D / 2 - 0.012, H + 0.06), (L * 0.9, 0.024, 0.12))
    return k.spec()


# ------------------------------------------------------------------ chair
CHAIR_ROLES = {
    "frame": Role("#7a4e2c", "wood", "legs, posts, rails"),
    "seat": Role("#946238", "wood", "seat board / upholstery base"),
    "cushion": Role("#7a2e2a", "fabric", "cushion, backrest padding"),
    "metal": Role("#9a9da2", "bare_metal", "studs, office base, gas lift"),
}
CHAIR_PARAMS = {
    "variant": Param("enum", "dining", choices=("dining", "tavern", "office", "armchair", "stool"),
                     doc="dining chair | chunky tavern chair | swivel office chair | upholstered armchair | bar stool"),
    "seat_height": Param("num", 0.45, 0.35, 0.8),
    "seat_width": Param("num", 0.45, 0.35, 0.8),
    "back_height": Param("num", 0.45, 0.2, 0.8, doc="backrest height above the seat"),
    "back": Param("enum", "slats", choices=("slats", "spindles", "ladder", "solid")),
    "slats": Param("int", 3, 2, 7),
    "legs": Param("enum", "straight", choices=("straight", "tapered", "turned")),
    "stretchers": Param("bool", True),
    "cushion": Param("bool", False),
    "studs": Param("bool", False, doc="upholstery nail studs"),
    "crooked": Param("bool", False, doc="hand-made crooked back (fantasy tavern look)"),
    "arms": Param("bool", False, doc="armrests"),
}


def _chair_wood(k, P, tavern):
    c = k.chunk
    sh, sw = P["seat_height"], P["seat_width"]
    sd = sw * 0.95
    st = (0.05 if tavern else 0.034) * (c ** 0.5)
    lw = (0.052 if tavern else 0.038) * (c ** 0.6)
    bh = P["back_height"]
    crooked = P["crooked"]
    k.box("seat", "seat", (0, 0, sh - st / 2), (sd, sw, st), bevel=k.bev(1.5),
          seams=[{"axis": "y", "at": [-0.33, 0.33]}] if tavern else None)
    xf, xb, yl = sd / 2 - lw / 2 - 0.012, -(sd / 2 - lw / 2 - 0.012), sw / 2 - lw / 2 - 0.012
    hl = sh - st + 0.003
    _leg(k, "leg_front", "frame", xf, yl, hl, lw, P["legs"])
    _leg(k, "leg_back", "frame", xb, yl, hl, lw, "straight" if P["legs"] == "turned" else P["legs"])
    z0, z1 = sh - st, sh + bh
    lean = 7.0
    tn = math.tan(math.radians(lean))

    def at(z, extra=0.0):
        return xb - (z - z0) * tn + extra

    hp = z1 - z0
    for s, nm, ln in ((1, "post", lean + (3 if crooked else 0)), (-1, "post_r", lean - (2 if crooked else 0))):
        k.box(nm, "frame", (xb - hp / 2 * math.sin(math.radians(ln)), s * yl, (z0 + z1) / 2), (lw, lw * 0.95, hp),
              rot=[0, -ln, 0])
    ch = 0.07 if not tavern else 0.09
    zc = z1 - ch / 2
    k.box("crest", "frame", (at(zc), 0, zc), (lw * 0.9, 2 * yl + lw * (1.4 if tavern else 1.0), ch),
          rot=[3 if crooked else 0, -lean, 0], bevel=k.bev(1.5))
    zr = sh + 0.06
    back = P["back"]
    if back != "solid":
        k.box("back_rail", "frame", (at(zr), 0, zr), (lw * 0.8, 2 * yl, 0.035), rot=[0, -lean, 0])
    n = P["slats"]
    span = 2 * yl - lw
    if back == "slats":
        hs = (zc - ch / 2) - zr + 0.02
        wsl = min(0.07, span / (n * 1.5))
        for i in range(n):
            y = -span / 2 + (i + 0.5) * span / n
            zm = zr + hs / 2 - 0.01
            k.box(f"slat{i}", "frame", (at(zm), y, zm), (lw * 0.4, wsl, hs),
                  rot=[(4 if i % 2 else -3) if crooked else 0, -lean, 0])
    elif back == "spindles":
        hs = (zc - ch / 2) - zr + 0.02
        m = n + 2
        for i in range(m):
            y = -span / 2 + (i + 0.5) * span / m
            zm = zr + hs / 2 - 0.01
            k.cyl(f"spindle{i}", "frame", (at(zm), y, zm), 0.011 * c, hs, rot=[(3 if i % 2 else -3) if crooked else 0,
                                                                                   -lean, 0])
    elif back == "ladder":
        top = zc - ch / 2
        for i in range(n):
            z = zr + 0.05 + (top - zr - 0.08) * (i + 0.5) / n
            k.box(f"rung{i}", "frame", (at(z), 0, z), (lw * 0.6, 2 * yl, 0.045), rot=[2 * (i % 2) if crooked else 0,
                                                                                    -lean, 0])
    else:
        hs = (zc - ch / 2) - z0 - 0.04
        zm = z0 + 0.04 + hs / 2
        k.box("back_panel", "seat", (at(zm), 0, zm), (lw * 0.5, 2 * yl, hs), rot=[0, -lean, 0])
    if P["stretchers"]:
        zs = 0.15 if not tavern else 0.12
        k.box("stretcher_side", "frame", (0, yl, zs), (xf - xb, lw * 0.6, lw * 0.7), mirror_y=True)
        k.box("stretcher_front", "frame", (xf, 0, zs + 0.06), (lw * 0.6, 2 * yl, lw * 0.7))
        if k.small:
            k.box("stretcher_back", "frame", (xb, 0, zs + 0.06), (lw * 0.6, 2 * yl, lw * 0.7))
    if P["cushion"]:
        k.box("cushion", "cushion", (0.005, 0, sh + 0.022), (sd * 0.92, sw * 0.92, 0.05), bevel=k.bev(4))
    if P["studs"] and k.small:
        ztop = sh + (0.03 if P["cushion"] else -st / 2)
        xs = sd * 0.46 + (0.0 if P["cushion"] else 0.005)
        n = max(4, int(sw / 0.05))
        k.cyl("stud", "metal", (xs, -sw * 0.42, ztop), 0.008 * c, 0.008, "x", count=n, step=[0, sw * 0.84 / (n - 1), 0])
    if P["arms"]:
        za = sh + 0.22
        k.box("arm_post", "frame", (xf, yl, (sh + za) / 2), (lw, lw, za - sh + 0.02), mirror_y=True)
        k.box("arm", "frame", ((xf + at(za)) / 2, yl, za + 0.012), (xf - at(za) + lw, lw * 1.2, 0.03), mirror_y=True,
              bevel=k.bev(1.5))


def _chair_office(k, P):
    c = k.chunk
    sh, sw = P["seat_height"], P["seat_width"]
    bh = P["back_height"]
    k.box("seat_cushion", "cushion", (0.02, 0, sh - 0.04), (0.48, sw + 0.03, 0.08), bevel=k.bev(6))
    k.box("seat_pan", "frame", (0, 0, sh - 0.095), (0.4, sw * 0.85, 0.03))
    k.box("mechanism", "frame", (0, 0, sh - 0.13), (0.18, 0.18, 0.05))
    z_hub = 0.09
    k.cyl("hub", "frame", (0, 0, z_hub), 0.05 * c, 0.06)
    k.cyl("gas_lift", "metal", (0, 0, (z_hub + sh - 0.15) / 2), 0.025 * c, sh - 0.15 - z_hub)
    if k.small:
        k.cyl("lift_cover", "frame", (0, 0, z_hub + 0.11), 0.035 * c, 0.16)
    for i, a in enumerate((0, 72, 144)):
        r = math.radians(a)
        k.box(f"base_leg{i}", "frame", (0.17 * math.cos(r), 0.17 * math.sin(r), 0.08), (0.3, 0.05 * c, 0.035),
              rot=[0, 0, a], mirror_y=a != 0)
        k.ball(f"caster{i}", "metal", (0.31 * math.cos(r), 0.31 * math.sin(r), 0.032), 0.032, mirror_y=a != 0,
               mat="rubber", color="#1d1d1e")
    k.box("back_arm", "frame", (-0.17, 0, sh - 0.13), (0.2, 0.06, 0.03))
    k.box("back_upright", "frame", (-0.27, 0, sh + 0.0), (0.03, 0.06, 0.28))
    k.box("backrest", "cushion", (-0.29, 0, sh + 0.1 + bh / 2), (0.07, sw * 0.95, bh), rot=[0, -10, 0], bevel=k.bev(6))
    if P["arms"]:
        k.box("arm_post", "frame", (-0.03, sw / 2 + 0.02, sh + 0.06), (0.04, 0.03, 0.2), mirror_y=True)
        k.box("arm_pad", "cushion", (-0.01, sw / 2 + 0.02, sh + 0.17), (0.24, 0.07, 0.03), mirror_y=True,
              bevel=k.bev(3))


def _chair_arm(k, P):
    c = k.chunk
    sh = P["seat_height"]
    sw = max(P["seat_width"], 0.55)
    aw = 0.16 * (c ** 0.5)
    W = sw + 2 * aw
    D = 0.82
    zb = 0.1
    zs = sh - 0.12
    for s, x in (("f", D / 2 - 0.06), ("b", -D / 2 + 0.06)):
        k.cone(f"leg_{s}", "frame", (x, W / 2 - 0.06, zb / 2 + 0.002), 0.018, 0.026, zb + 0.004, mirror_y=True)
    k.box("base", "seat", (0, 0, (zb + zs) / 2), (D, W, zs - zb), bevel=k.bev(5))
    k.box("seat_cushion", "cushion", (0.06, 0, zs + 0.06), (D - 0.22, sw, 0.12), bevel=k.bev(6))
    za = zs + 0.25
    k.box("arm", "seat", (0, sw / 2 + aw / 2, (zs + za) / 2), (D, aw, za - zs + 0.01), mirror_y=True, bevel=k.bev(5))
    if not k.low:
        k.cyl("arm_roll", "seat", (0.0, sw / 2 + aw / 2, za), aw * 0.55, D, "x", mirror_y=True)
    zt = sh + P["back_height"] + 0.1
    k.box("back", "seat", (-D / 2 + 0.1, 0, (zs + zt) / 2), (0.2, W, zt - zs), rot=[0, -6, 0], bevel=k.bev(5))
    k.box("back_cushion", "cushion", (-D / 2 + 0.24, 0, zs + 0.12 + (zt - zs - 0.2) / 2), (0.12, sw, zt - zs - 0.2),
          rot=[0, -8, 0], bevel=k.bev(6))
    if P["studs"] and k.small:
        n = 6
        k.cyl("stud", "metal", (D / 2 + 0.003, sw / 2 + aw / 2, zs + 0.02), 0.009 * c, 0.008, "x", count=n,
              step=[0, 0, (za - zs) / (n - 1) * 0.9], mirror_y=True)


def _chair_stool(k, P):
    c = k.chunk
    sh, sw = P["seat_height"], P["seat_width"]
    st = 0.04 * (c ** 0.5)
    rt = sw * 0.36
    rb = sw * 0.5
    lr = 0.016 * c
    k.cyl("seat", "seat", (0, 0, sh - st / 2), sw / 2, st, bevel=k.bev(2))
    for i, a in enumerate((45, 135)):
        r = math.radians(a)
        k.tube(f"leg{i}", "frame", [(rb * math.cos(r), rb * math.sin(r), 0.0 + lr),
                                    (rt * math.cos(r), rt * math.sin(r), sh - st + 0.004)], lr, mirror_y=True)
    zr = sh * 0.3
    f = zr / (sh - st)
    rr = rb + (rt - rb) * f
    k.ring("foot_ring", "metal" if not k.low else "frame", (0, 0, zr), rr, 0.011 * c, "z")
    if P["cushion"]:
        k.cyl("cushion", "cushion", (0, 0, sh + 0.02), sw / 2 * 0.95, 0.04, bevel=k.bev(4))


def build_chair(P, R, style):
    v = P["variant"]
    if v == "office":
        R = _alt(R, CHAIR_ROLES, "frame", "polymer", "#2a2b2e")
        R = _alt(R, CHAIR_ROLES, "cushion", "fabric", "#3b3f46")
        R = _alt(R, CHAIR_ROLES, "metal", "chrome", "#c8cacd")
    if v == "armchair":
        R = _alt(R, CHAIR_ROLES, "seat", "leather", "#6b3a24")
        R = _alt(R, CHAIR_ROLES, "cushion", "leather", "#7a4429")
        R = _alt(R, CHAIR_ROLES, "frame", "dark_wood", "#3e2716")
        R = _alt(R, CHAIR_ROLES, "metal", "brass", "#b8913f")
    if v == "tavern":
        R = _alt(R, CHAIR_ROLES, "frame", "wood", "#6b4426")
        R = _alt(R, CHAIR_ROLES, "seat", "wood", "#80532e")
    if v == "stool":
        R = _alt(R, CHAIR_ROLES, "metal", "gunmetal", "#3a3c40")
    k = Kit(f"{v} chair" if v != "stool" else "bar stool", "furniture", style, R)
    if v in ("dining", "tavern"):
        _chair_wood(k, P, v == "tavern")
    elif v == "office":
        _chair_office(k, P)
    elif v == "armchair":
        _chair_arm(k, P)
    else:
        _chair_stool(k, P)
    return k.spec()


# ------------------------------------------------------------------ crate / ammo crate
CRATE_ROLES = {
    "body": Role("#a07a4a", "wood", "boards / box body"),
    "trim": Role("#6f4e2c", "wood", "frame boards, lid, cleats"),
    "metal": Role("#4a4c50", "gunmetal", "latches, handles, corners"),
    "stencil": Role("#d9c98a", "painted_metal", "stencil panel"),
}
CRATE_PARAMS = {
    "variant": Param("enum", "wood", choices=("wood", "ammo"), doc="slatted wooden crate | military ammo box"),
    "length": Param("num", 0.8, 0.25, 1.6),
    "width": Param("num", 0.55, 0.2, 1.2),
    "height": Param("num", 0.55, 0.15, 1.2),
    "frame": Param("bool", True, doc="corner posts and edge boards"),
    "brace": Param("bool", True, doc="diagonal brace boards"),
    "latches": Param("int", 2, 0, 4),
    "handles": Param("enum", "auto", choices=("auto", "none", "rope", "metal")),
    "stencil": Param("bool", True),
    "skids": Param("bool", False, doc="runners underneath"),
}


def _handles(k, kind, L, W, z, rope_color="#a8916a"):
    for s, nm in ((1, "a"), (-1, "b")):
        x = s * L / 2
        if kind == "rope":
            hw = min(0.09, W * 0.3)
            k.tube(f"rope_handle_{nm}", "trim", [(x, -hw, z + 0.02), (x + s * 0.03, -hw * 0.7, z - 0.03),
                                                 (x + s * 0.036, 0, z - 0.045), (x + s * 0.03, hw * 0.7, z - 0.03),
                                                 (x, hw, z + 0.02)], 0.009 * k.chunk, mat="fabric", color=rope_color)
            k.box(f"rope_block_{nm}", "metal", (x + s * 0.006, 0, z + 0.02), (0.014, hw * 2 + 0.04, 0.03))
        elif kind == "metal":
            hw = min(0.07, W * 0.25)
            k.box(f"handle_{nm}", "metal", (x + s * 0.03, 0, z), (0.014, hw * 2, 0.016 * k.chunk))
            k.box(f"handle_post_{nm}", "metal", (x + s * 0.016, hw - 0.008, z), (0.032, 0.014, 0.016 * k.chunk),
                  mirror_y=True)


def build_crate(P, R, style):
    v = P["variant"]
    L, W, H = P["length"], P["width"], P["height"]
    if v == "ammo":
        R = _alt(R, CRATE_ROLES, "body", "painted_metal", "#56603e")
        R = _alt(R, CRATE_ROLES, "trim", "painted_metal", "#4b5436")
        if (L, W, H) == (0.8, 0.55, 0.55):
            L, W, H = 0.72, 0.36, 0.3
    k = Kit("ammo crate" if v == "ammo" else "wooden crate", "prop", style, R)
    c = k.chunk
    handles = P["handles"] if P["handles"] != "auto" else ("metal" if v == "ammo" else "rope")
    if v == "wood":
        e = 0.02 * c
        bw = min(0.09, 0.16 * min(L, W, H)) * (c ** 0.5)
        n = max(2, round(H / 0.12))
        k.box("body", "body", (0, 0, H / 2), (L, W, H), seams=[{"axis": "z", "at": [-1 + 2 * i / n for i in range(1, n)]}])
        if P["frame"]:
            for s, nm in ((1, "a"), (-1, "b")):
                k.box(f"post_{nm}", "trim", (s * (L / 2 - bw / 2 + e + 0.004), W / 2 - bw / 2 + e + 0.004, H / 2),
                      (bw, bw, H + 0.01), mirror_y=True)
            k.box("rim_top", "trim", (0, 0, H - bw / 2), (L + 2 * e, W + 2 * e, bw))
            k.box("rim_bottom", "trim", (0, 0, bw / 2), (L + 2 * e, W + 2 * e, bw))
        if P["brace"] and not k.low:
            span_w, span_h = W - 2 * bw, H - 2 * bw
            if span_h > 0.05 and span_w > 0.05:
                a = math.degrees(math.atan2(span_h, span_w))
                for s, nm in ((1, "a"), (-1, "b")):
                    k.box(f"brace_end_{nm}", "trim", (s * (L / 2 + e / 2), 0, H / 2),
                          (e, math.hypot(span_w, span_h) * 0.98, bw * 0.8), rot=[a, 0, 0])
            span_l = L - 2 * bw
            if span_h > 0.05 and span_l > 0.05:
                a = math.degrees(math.atan2(span_h, span_l))
                k.box("brace_side", "trim", (0, W / 2 + e / 2, H / 2), (math.hypot(span_l, span_h) * 0.98, e, bw * 0.8),
                      rot=[0, -a, 0], mirror_y=not P["stencil"])
        lid_top = H
        z_handles = H * 0.62
        front = W / 2 + (e if P["frame"] else 0)
    else:
        hb = H * 0.76
        k.box("body", "body", (0, 0, hb / 2), (L, W, hb), bevel=k.bev(2))
        k.box("lid", "body", (0, 0, hb + (H - hb) / 2 - 0.002), (L + 0.012, W + 0.012, H - hb), bevel=k.bev(2))
        if P["frame"]:
            for s, nm in ((1, "a"), (-1, "b")):
                k.box(f"cleat_{nm}", "trim", (s * (L / 2 + 0.012 * c), 0, hb / 2), (0.024 * c, W * 0.86, hb * 0.86))
        if P["brace"] and not k.low:
            for s, nm in ((1, "a"), (-1, "b")):
                k.box(f"rib_{nm}", "trim", (s * L * 0.3, 0, hb / 2), (0.04 * c, W + 0.014, hb * 0.98))
        if k.small:
            cs = 0.045 * (c ** 0.5)
            for s, nm in ((1, "a"), (-1, "b")):
                k.box(f"corner_top_{nm}", "metal", (s * (L / 2 - cs / 2 + 0.008), W / 2 - cs / 2 + 0.008, H - cs / 2 + 0.002),
                      (cs, cs, cs), mirror_y=True)
                k.box(f"corner_bot_{nm}", "metal", (s * (L / 2 - cs / 2 + 0.004), W / 2 - cs / 2 + 0.004, cs / 2),
                      (cs, cs, cs), mirror_y=True)
        if k.fine:
            k.cyl("hinge", "metal", (-L * 0.3, W / 2 + 0.008, hb), 0.008, 0.08, "x", count=2, step=[L * 0.6, 0, 0])
        lid_top = H
        z_handles = hb * 0.62
        front = W / 2 + 0.006
    if P["latches"]:
        n = P["latches"]
        for i in range(n):
            x = -L * 0.3 + (L * 0.6) * (i / (n - 1) if n > 1 else 0.5)
            zl = lid_top - (0.06 if v == "wood" else (H - H * 0.76) + 0.01)
            k.box(f"latch{i}", "metal", (x, -(front + 0.005), zl), (0.04 * c, 0.012, 0.07))
            if k.small:
                k.box(f"latch_catch{i}", "metal", (x, -(front + 0.003), zl + 0.045), (0.03 * c, 0.008, 0.02))
    if handles != "none":
        if v == "wood":
            face = L + (2 * e if P["brace"] and not k.low else 0.0)
        else:
            face = L + (0.048 * c if P["frame"] else 0.0)
        _handles(k, handles, face, W, z_handles)
    if P["stencil"]:
        sw, shh = min(0.5 * L, 0.42), min(0.32 * H, 0.16)
        zc = H * (0.45 if v == "wood" else 0.4)
        k.box("stencil", "stencil", (0, -(W / 2 + 0.0015), zc), (sw, 0.004, shh))
        if k.small:
            k.box("stencil_band", "trim", (0, -(W / 2 + 0.0025), zc), (sw * 0.8, 0.004, shh * 0.22), mat="plastic",
                  color="#2a2a26")
    if P["skids"]:
        k.box("skid", "trim", (0, W / 3, -0.03), (L, 0.08, 0.06), mirror_y=True)
    return k.spec()


# ------------------------------------------------------------------ treasure chest
CHEST_ROLES = {
    "wood": Role("#7a4e2a", "wood", "planks"),
    "metal": Role("#3d3a36", "gunmetal", "bands, corners, handles"),
    "lock": Role("#c79b3b", "brass", "lock plate and hasp"),
    "treasure": Role("#d4a63a", "gold", "gold inside (only when the lid is open)"),
}
CHEST_PARAMS = {
    "length": Param("num", 0.8, 0.35, 1.4),
    "depth": Param("num", 0.5, 0.25, 0.9),
    "height": Param("num", 0.42, 0.2, 0.8, doc="body height without the lid"),
    "lid": Param("enum", "domed", choices=("domed", "flat")),
    "lid_open": Param("num", 0, 0, 110, doc="lid opening angle in degrees"),
    "bands": Param("int", 3, 0, 5),
    "corners": Param("bool", True, doc="metal corner caps"),
    "lock": Param("bool", True),
    "feet": Param("bool", False),
    "handles": Param("bool", True, doc="ring handles on the ends"),
    "treasure": Param("bool", True, doc="gold heap visible when open"),
}


def build_chest(P, R, style):
    k = Kit("treasure chest", "prop", style, R)
    c = k.chunk
    L, D, Hb = P["length"], P["depth"], P["height"]
    lid_h = D * 0.36 if P["lid"] == "domed" else 0.07 * (c ** 0.5)
    planks = max(2, round(Hb / 0.1))
    k.box("body", "wood", (0, 0, Hb / 2), (L, D, Hb), bevel=k.bev(1.5),
          seams=[{"axis": "z", "at": [-1 + 2 * i / planks for i in range(1, planks)]}])
    phi = P["lid_open"]
    lid_parts = []
    if P["lid"] == "domed":
        pts = _arc(0, 0, D / 2, 0, 180, 12, rz=lid_h)
        lid_parts.append(k.prof("lid", "wood", pts, L, pos=(0, 0, Hb - 0.001), rot=[0, 0, 90], bevel=k.bev(1.5)))
    else:
        lid_parts.append(k.box("lid", "wood", (0, 0, Hb + lid_h / 2 - 0.001), (L + 0.01, D + 0.01, lid_h),
                               bevel=k.bev(1.5)))
    nb = P["bands"]
    bw = 0.045 * (c ** 0.5)
    t = 0.006 * c
    for i in range(nb):
        x = (-L / 2 + bw / 2 + 0.02) + (L - bw - 0.04) * (i / (nb - 1) if nb > 1 else 0.5)
        k.box(f"band{i}", "metal", (x, 0, (Hb + 0.003) / 2), (bw, D + 2 * t, Hb + 0.003))
        if P["lid"] == "domed":
            ring = _arc(0, 0, D / 2 + t, 0, 180, 10, rz=lid_h + t) + list(reversed(_arc(0, 0, D / 2 - 0.02, 0, 180, 10,
                                                                                       rz=lid_h - 0.02)))
            lid_parts.append(k.prof(f"lid_band{i}", "metal", ring, bw, pos=(x, 0, Hb), rot=[0, 0, 90]))
        else:
            lid_parts.append(k.box(f"lid_band{i}", "metal", (x, 0, Hb + lid_h / 2), (bw, D + 0.01 + 2 * t, lid_h + t)))
    if P["corners"] and k.small:
        cs = 0.05 * (c ** 0.5)
        for s, nm in ((1, "a"), (-1, "b")):
            k.box(f"corner_bot_{nm}", "metal", (s * (L / 2 - cs / 2 + 0.004), D / 2 - cs / 2 + 0.004, cs / 2),
                  (cs, cs, cs), mirror_y=True)
            k.box(f"corner_top_{nm}", "metal", (s * (L / 2 - cs / 2 + 0.004), D / 2 - cs / 2 + 0.004, Hb - cs / 2),
                  (cs, cs, cs), mirror_y=True)
    if P["lock"]:
        k.box("lock_plate", "lock", (0, -D / 2 - 0.0058, Hb - 0.06), (0.09 * (c ** 0.5), 0.012, 0.11))
        if k.small:
            k.box("keyhole", "metal", (0, -D / 2 - 0.0128, Hb - 0.07), (0.012, 0.004, 0.026), mat="gunmetal",
                  color="#141414")
        lid_parts.append(k.box("hasp", "lock", (0, -D / 2 - 0.0058 - (0.003 if P["lid"] == "flat" else 0.0), Hb + 0.012),
                               (0.05 * (c ** 0.5), 0.012, 0.07)))
    if P["handles"] and k.small:
        for s, nm in ((1, "a"), (-1, "b")):
            k.box(f"handle_mount_{nm}", "metal", (s * (L / 2 + 0.003), 0, Hb * 0.6 + 0.04), (0.014, 0.05, 0.03))
            k.ring(f"handle_{nm}", "metal", (s * (L / 2 + 0.012), 0, Hb * 0.6), 0.04, 0.007 * c, "x")
    if k.small or phi > 0.5:
        k.cyl("hinge", "metal", (-L * 0.3, D / 2 + t, Hb), t + 0.006, 0.05, "x", count=2, step=[L * 0.6, 0, 0])
    if P["feet"]:
        k.box("foot_a", "metal", (L / 2 - 0.05, D / 2 - 0.05, -0.014), (0.06, 0.06, 0.03), mirror_y=True)
        k.box("foot_b", "metal", (-L / 2 + 0.05, D / 2 - 0.05, -0.014), (0.06, 0.06, 0.03), mirror_y=True)
    if phi > 0.5:
        a = math.radians(phi)
        yh, zh = D / 2 + t, Hb
        for p in lid_parts:
            y, z = p["pos"][1] - yh, p["pos"][2] - zh
            p["pos"][1] = _r(yh + y * math.cos(a) + z * math.sin(a))
            p["pos"][2] = _r(zh - y * math.sin(a) + z * math.cos(a))
            if p["type"] == "profile":
                p["rot"] = [0, _r(phi), 90]
            else:
                p["rot"] = [_r(-phi), 0, 0]
            p.pop("seams", None)
        if P["treasure"] and phi > 20:
            k.ball("gold", "treasure", (0, 0, Hb - 0.03), D * 0.4, scale=[L / D * 1.05, 1.0, 0.35])
    return k.spec()


# ------------------------------------------------------------------ jerrycan
JERRY_ROLES = {
    "body": Role("#4b5a35", "painted_metal", "can body"),
    "metal": Role("#7d8084", "bare_metal", "spout cap and clamp"),
    "decal": Role("#d8c46a", "painted_metal", "label panel"),
}
JERRY_PARAMS = {
    "size": Param("num", 1.0, 0.55, 1.4, doc="1 = 20 litre can"),
    "emboss": Param("bool", True, doc="X stiffening ribs on the sides"),
    "spout": Param("enum", "cap", choices=("cap", "nozzle")),
    "label": Param("bool", False, doc="painted label panel"),
}


def build_jerrycan(P, R, style):
    k = Kit("jerrycan", "prop", style, R)
    c = k.chunk
    H, L, W = 0.42, 0.345, 0.165 * (1.08 if k.sty or k.rbx else 1.0)
    ch = 0.03 * (c ** 0.5)
    half = [(-L / 2, ch), (-L / 2 + ch, 0), (L / 2 - ch, 0), (L / 2, ch), (L / 2, H - 0.055), (L / 2 - 0.055, H),
            (-L / 2 + 0.035, H), (-L / 2, H - 0.035)]
    tw = W / 2 - 0.004
    k.prof("half", "body", half, tw, y=W / 4 + 0.002, mirror_y=True, bevel=k.bev(4))
    cx, cz = 0.0, H / 2
    seam = [(cx + (x - cx) * 1.03, cz + (z - cz) * 1.02) for x, z in half]
    k.prof("weld_seam", "body", seam, 0.012, bevel=k.bev(1))
    if P["emboss"]:
        dx, dz = L - 0.09, H - 0.11
        a = math.degrees(math.atan2(dz, dx))
        dl = math.hypot(dx, dz)
        k.box("rib", "body", (0, W / 2 + 0.001, H * 0.48), (dl, 0.008, 0.028 * c), rot=[0, -a, 0], mirror_y=True)
        k.box("rib_x", "body", (0, W / 2 + 0.0016, H * 0.48), (dl, 0.0082, 0.026 * c), rot=[0, a, 0], mirror_y=True)
    xs = (-0.11, -0.055, 0.0)
    hr = 0.011 * c
    zh = H + 0.034
    for i, x in enumerate(xs):
        k.cyl(f"handle{i}", "body", (x, 0, zh), hr, W * 0.62, "y")
        k.box(f"handle_post{i}", "body", (x, W * 0.31 - 0.012, H + 0.014), (0.022, 0.016, 0.042), mirror_y=True)
    k.box("ridge", "body", (-0.055, 0, H + 0.008), (0.16, 0.012, 0.022))
    a = 25.0
    bx, bz = L / 2 - 0.07, H - 0.004
    d = (math.sin(math.radians(a)), math.cos(math.radians(a)))
    k.cyl("neck", "metal", (bx + d[0] * 0.02, 0, bz + d[1] * 0.02), 0.024 * c, 0.045, rot=[0, a, 0])
    if P["spout"] == "nozzle":
        k.cone("nozzle", "metal", (bx + d[0] * 0.09, 0, bz + d[1] * 0.09), 0.02 * c, 0.009, 0.1, rot=[0, a, 0])
    else:
        k.cyl("cap", "metal", (bx + d[0] * 0.05, 0, bz + d[1] * 0.05), 0.031 * c, 0.024, rot=[0, a, 0])
        if k.small:
            k.box("clamp", "metal", (bx - 0.045, 0, bz + 0.035), (0.08, 0.018, 0.012), rot=[0, -8, 0])
    if P["label"]:
        k.box("label", "decal", (0, -(W / 2 + 0.0015), H * 0.22), (L * 0.5, 0.004, H * 0.14))
    return k.spec(P["size"])


# ------------------------------------------------------------------ backpack
PACK_ROLES = {
    "bag": Role("#5f6b4a", "fabric", "main bag and pockets"),
    "trim": Role("#2f302b", "fabric", "straps and webbing"),
    "leather": Role("#6b4226", "leather", "flap and base"),
    "metal": Role("#9a9da2", "bare_metal", "buckles"),
    "roll": Role("#8b7a5c", "fabric", "bedroll"),
}
PACK_PARAMS = {
    "variant": Param("enum", "hiking", choices=("hiking", "military", "school", "adventurer"),
                     doc="tall hiking pack | boxy military rucksack | small school bag | leather adventurer pack"),
    "size": Param("num", 1.0, 0.7, 1.35),
    "flap": Param("bool", True, doc="top flap over the opening"),
    "bedroll": Param("bool", False, doc="rolled blanket on top"),
    "side_pouches": Param("bool", True),
    "front_pocket": Param("bool", True),
}
_PACK = {"hiking": (0.34, 0.24, 0.62), "military": (0.36, 0.26, 0.5), "school": (0.31, 0.18, 0.43),
         "adventurer": (0.36, 0.22, 0.5)}


def build_backpack(P, R, style):
    v = P["variant"]
    if v == "adventurer":
        R = _alt(R, PACK_ROLES, "bag", "leather", "#7a5233")
        R = _alt(R, PACK_ROLES, "leather", "leather", "#4e2f1b")
    if v == "school":
        R = _alt(R, PACK_ROLES, "bag", "fabric", "#2f5f8a")
    k = Kit(f"{v} backpack", "accessory", style, R)
    c = k.chunk
    W, D, H = _PACK[v]
    soft = k.bev(10)
    k.box("bag", "bag", (0, 0, H / 2), (W, D, H), bevel=soft)
    k.box("base", "leather", (0, 0, 0.025), (W + 0.008, D + 0.008, 0.05), bevel=k.bev(5))
    if P["flap"]:
        k.box("flap", "leather", (0, -D * 0.12, H - 0.012), (W * 0.97, D * 0.8, 0.05), bevel=k.bev(6))
        k.box("flap_lip", "leather", (0, -D / 2 - 0.008, H - H * 0.13 - 0.02), (W * 0.72, 0.03, H * 0.26), bevel=k.bev(5))
        if k.small:
            k.box("buckle", "metal", (W * 0.22, -D / 2 - 0.026, H - H * 0.26 - 0.01), (0.03, 0.01, 0.035))
            k.box("buckle_b", "metal", (-W * 0.22, -D / 2 - 0.026, H - H * 0.26 - 0.01), (0.03, 0.01, 0.035))
    if P["front_pocket"]:
        k.box("front_pocket", "bag", (0, -D / 2 - 0.028, H * 0.26), (W * 0.76, 0.075, H * 0.38), bevel=k.bev(6),
              seams=[{"axis": "z", "at": [0.6]}])
        if v == "military" and k.fine:
            k.box("molle", "trim", (0, -D / 2 - 0.067, H * 0.18), (W * 0.7, 0.006, 0.025), count=3, step=[0, 0, 0.06])
    if P["side_pouches"]:
        for s, nm in ((1, "a"), (-1, "b")):
            k.box(f"side_pouch_{nm}", "bag", (s * (W / 2 + 0.03), 0, H * 0.27), (0.075, D * 0.72, H * 0.36), bevel=soft)
    if P["bedroll"]:
        rr = 0.07 * (c ** 0.5)
        k.cyl("bedroll", "roll", (0, D * 0.12, H + rr * 0.85), rr, W * 1.25, "x", bevel=k.bev(5))
        if not k.low:
            for s, nm in ((1, "a"), (-1, "b")):
                k.ring(f"roll_strap_{nm}", "trim", (s * W * 0.32, D * 0.12, H + rr * 0.85), rr * 1.03, 0.008 * c, "x")
    elif k.small:
        yh = D * 0.15
        k.tube("carry_handle", "trim", [(-0.04, yh, H - 0.01), (-0.03, yh, H + 0.04), (0.03, yh, H + 0.04),
                                        (0.04, yh, H - 0.01)], 0.008 * c)
    sr = 0.012 * c
    for s, nm in ((1, "a"), (-1, "b")):
        x0 = s * W * 0.22
        k.tube(f"shoulder_strap_{nm}", "trim", [(x0, D / 2 - 0.01, H - 0.06), (x0, D / 2 + 0.05, H - 0.13),
                                                (x0 + s * 0.02, D / 2 + 0.06, H * 0.45), (x0 + s * 0.01, D / 2 + 0.03, H * 0.12),
                                                (x0, D / 2 - 0.01, 0.06)], sr)
        if not k.low:
            k.box(f"compression_{nm}", "trim", (s * W * 0.3, -D / 2 - 0.004, H * 0.55), (0.028, 0.008, H * 0.55))
    if not k.low:
        k.box("back_pad", "trim", (0, D / 2 + 0.008, H * 0.5), (W * 0.8, 0.03, H * 0.66), bevel=k.bev(6))
    return k.spec(P["size"])


# ------------------------------------------------------------------ helmet
HELMET_ROLES = {
    "shell": Role("#5b6146", "painted_metal", "helmet shell"),
    "trim": Role("#2a2b2d", "rubber", "edge trim, straps"),
    "metal": Role("#3a3c40", "gunmetal", "mounts, rails, rivets"),
    "accent": Role("#3b3f33", "fabric", "patch, counterweight pouch, plume"),
}
HELMET_PARAMS = {
    "variant": Param("enum", "combat", choices=("combat", "knight"), doc="modern combat helmet | medieval great helm"),
    "size": Param("num", 1.0, 0.85, 1.2),
    "nvg_mount": Param("bool", True, doc="night-vision shroud on the front (combat)"),
    "rails": Param("bool", True, doc="side accessory rails (combat)"),
    "chin_strap": Param("bool", True),
    "goggles": Param("bool", False, doc="goggles on the brow (combat)"),
    "plume": Param("bool", False, doc="plume on top (knight)"),
}


def _dome(R, Hd, t):
    """Point on the dome profile at elevation t degrees: (radius, height)."""
    a = math.radians(t)
    return R * math.cos(a), Hd * math.sin(a)


def build_helmet(P, R_, style):
    v = P["variant"]
    if v == "knight":
        R_ = _alt(R_, HELMET_ROLES, "shell", "bare_metal", "#a9adb3")
        R_ = _alt(R_, HELMET_ROLES, "metal", "brass", "#b8913f")
        R_ = _alt(R_, HELMET_ROLES, "accent", "fabric", "#8a2a2a")
    k = Kit("combat helmet" if v == "combat" else "knight helmet", "accessory", style, R_)
    c = k.chunk
    if v == "combat":
        R, Hd = 0.118, 0.135
        pts = [[-0.034, R * 0.985], [-0.016, R + 0.001], [0.0, R]] +               [[Hd * math.sin(math.radians(a)), R * math.cos(math.radians(a))] for a in range(10, 91, 10)]
        k.lathe("shell", "shell", (0, 0, 0), pts)  # no booleans on lathes: they break the bake
        k.ring("rim", "trim", (0, 0, -0.032), R * 0.985 + 0.001, 0.006 * c, "z")
        if P["nvg_mount"]:
            r, h = _dome(R, Hd, 30)
            tilt = math.degrees(math.atan2(math.sin(math.radians(30)) / Hd, math.cos(math.radians(30)) / R))
            k.box("nvg_shroud", "metal", (r + 0.006, 0, h), (0.026, 0.06, 0.05), rot=[0, -tilt, 0])
            if k.small:
                k.box("nvg_arm", "metal", (r + 0.024, 0, h - 0.03), (0.016, 0.03, 0.05), rot=[0, -tilt * 0.5, 0])
        if P["rails"]:
            r, h = _dome(R, Hd, 22)
            tilt = math.degrees(math.atan2(math.sin(math.radians(22)) / Hd, math.cos(math.radians(22)) / R))
            k.box("side_rail", "metal", (-0.005, r + 0.004, h), (0.1, 0.012, 0.022), rot=[tilt, 0, 0], mirror_y=True)
        if P["chin_strap"]:
            k.tube("chin_strap", "trim", [(-0.01, 0.112, -0.02), (0.0, 0.106, -0.06), (0.014, 0.095, -0.09)], 0.006 * c,
                   mirror_y=True)
            if k.small:
                k.box("strap_buckle", "metal", (0.016, 0.094, -0.098), (0.02, 0.012, 0.022), mirror_y=True)
        if k.small:
            r, h = _dome(R, Hd, 28)
            k.box("counterweight", "accent", (-(r + 0.012), 0, h), (0.028, 0.07, 0.05), rot=[0, 25, 0], mat="fabric",
                  color="#3b3f33")
        if k.fine:
            k.box("patch", "accent", (-0.01, 0, Hd - 0.002), (0.06, 0.045, 0.006))
        if P["goggles"]:
            r, h = _dome(R, Hd, 32)
            k.ring("goggle_strap", "trim", (0, 0, h), r + 0.003, 0.006 * c, "z")
            k.cyl("goggle_lens", "metal", (r + 0.012, 0.035, h), 0.024 * c, 0.022, "x", mirror_y=True, mat="glass",
                  color="#2a3a44")
    else:
        R = 0.115
        pts = [[0, 0], [0, R * 0.97], [0.02, R], [0.17, R], [0.22, R * 0.86], [0.255, R * 0.5], [0.272, 0]]
        k.lathe("shell", "shell", (0, 0, 0), pts)
        a = 0.36
        k.box("eye_slit", "metal", (R * math.cos(a) + 0.001, R * math.sin(a), 0.17), (0.008, 0.06, 0.014),
              rot=[0, 0, math.degrees(a)], mirror_y=True, mat="gunmetal", color="#141414")
        ridge = [(R + 0.006, 0.02), (R + 0.006, 0.17), (R * 0.86 + 0.006, 0.22), (R * 0.5 + 0.006, 0.255),
                 (0.0, 0.279), (0.0, 0.25), (R * 0.5 - 0.01, 0.235), (R * 0.84 - 0.01, 0.2), (R - 0.006, 0.16),
                 (R - 0.006, 0.02)]
        k.prof("ridge", "shell", ridge, 0.014 * c)
        if k.fine:
            for i, a in enumerate((-0.3, -0.45, -0.6)):
                k.cyl(f"breath{i}", "metal", (R * math.cos(a), R * math.sin(a), 0.08), 0.0045, 0.008, "x",
                      rot=[0, 0, math.degrees(a)], mat="gunmetal", color="#141414")

        k.ring("brow_band", "metal", (0, 0, 0.19), R + 0.003, 0.0065 * c, "z")
        if k.fine:
            for i, a in enumerate((60, 120, 180)):
                ra = math.radians(a)
                k.cyl(f"rivet{i}", "metal", ((R + 0.008) * math.cos(ra), (R + 0.008) * math.sin(ra), 0.19), 0.006,
                      0.008, "x", rot=[0, 0, a], mirror_y=a != 180)
        if P["chin_strap"] and k.small:
            k.ring("neck_band", "metal", (0, 0, 0.012), R + 0.002, 0.006 * c, "z")
        if P["plume"]:
            k.cyl("plume_holder", "metal", (0, 0, 0.285), 0.012, 0.03)
            for i, tilt in enumerate((-15, -35, -55)):
                tr = math.radians(tilt)
                k.ball(f"plume{i}", "accent", (0.07 * math.sin(tr), 0, 0.29 + 0.07 * math.cos(tr)), 0.05 * c,
                       scale=[0.32, 0.26, 1.5], rot=[0, tilt, 0])
    return k.spec(P["size"])


# ------------------------------------------------------------------ barrel
BARREL_ROLES = {
    "wood": Role("#8a5a32", "wood", "staves / drum paint"),
    "metal": Role("#3b3b3b", "gunmetal", "hoops / ribs"),
    "lid": Role("#5a3a22", "dark_wood", "heads and bung"),
    "accent": Role("#b8913f", "brass", "tap / spigot"),
}
BARREL_PARAMS = {
    "variant": Param("enum", "wood", choices=("wood", "oil_drum"), doc="wooden barrel | steel oil drum"),
    "height": Param("num", 0.86, 0.35, 1.3),
    "diameter": Param("num", 0.6, 0.25, 1.0, doc="widest diameter"),
    "bulge": Param("num", 0.14, 0.0, 0.3, doc="belly bulge (wood)"),
    "hoops": Param("int", 4, 2, 6),
    "bung": Param("bool", True, doc="bung plug on the side"),
    "spigot": Param("bool", False, doc="tap near the bottom"),
    "lying": Param("bool", False, doc="lying on its side on two chocks"),
}
_HOOPS = {2: (0.12, 0.88), 3: (0.1, 0.5, 0.9), 4: (0.08, 0.25, 0.75, 0.92), 5: (0.08, 0.25, 0.5, 0.75, 0.92),
          6: (0.06, 0.18, 0.38, 0.62, 0.82, 0.94)}


def _tip_over(parts, H):
    """Rotate an upright build 90 degrees about Y so its +Z axis points along +X (lying barrel)."""
    amap = {"z": "x", "x": "z", "y": "y"}
    for p in parts:
        x, y, z = p["pos"]
        p["pos"] = [_r(z - H / 2), y, _r(-x)]
        if "axis" in p:
            if p["axis"] == "x" and p["type"] == "cone":
                p["radius"], p["radius2"] = p["radius2"], p["radius"]
            p["axis"] = amap[p["axis"]]
        p.pop("seams", None)
        p.pop("cuts", None)


def build_barrel(P, R, style):
    v = P["variant"]
    if v == "oil_drum":
        R = _alt(R, BARREL_ROLES, "wood", "painted_metal", "#2f4f7a")
        R = _alt(R, BARREL_ROLES, "metal", "painted_metal", "#2a4670")
        R = _alt(R, BARREL_ROLES, "lid", "painted_metal", "#2f4f7a")
    k = Kit("wooden barrel" if v == "wood" else "oil drum", "prop", style, R)
    c = k.chunk
    H = P["height"]
    rb = P["diameter"] / 2
    if v == "wood":
        bulge = P["bulge"] * (1.25 if k.sty else 1.0)
        re = rb / (1 + bulge)

        def rad(h):
            u = 2 * h / H - 1
            return re + (rb - re) * (1 - u * u)
        ch = 0.014 * (c ** 0.5)
        n = 8
        side = [[H * i / n, rad(H * i / n)] for i in range(n + 1)]
        k.lathe("body", "wood", (0, 0, 0), [[0, 0]] + side + [[H, 0]])
        k.cyl("head_top", "lid", (0, 0, H + 0.002), re - ch, 0.008)
        hw, ht = 0.042 * c, 0.006 * c
        for i, f in enumerate(_HOOPS[P["hoops"]]):
            h = f * H
            h0, h1 = max(0.0, h - hw / 2), min(H, h + hw / 2)
            k.cone(f"hoop{i}", "metal", (0, 0, (h0 + h1) / 2), rad(h0) + ht, rad(h1) + ht, h1 - h0)
        hb = 0.5 if 0.5 not in _HOOPS[P["hoops"]] else 0.4
        rbng = rad(hb * H)
    else:
        lip = 0.012 * c
        k.lathe("body", "wood", (0, 0, 0), [[0, 0], [0, rb - 0.006], [lip, rb], [H - lip, rb], [H, rb - 0.006], [H, 0]])
        for i, f in enumerate((0.0, 1.0)):
            k.ring(f"rim{i}", "metal", (0, 0, max(lip * 0.5, min(H - lip * 0.5, f * H))), rb - 0.002, lip * 0.6, "z")
        for i, f in enumerate((1 / 3, 2 / 3)):
            k.ring(f"rib{i}", "metal", (0, 0, f * H), rb + 0.001, 0.009 * c, "z")
        k.cyl("bung_cap", "lid", (rb * 0.55, 0, H + 0.006), 0.03, 0.014, mat="bare_metal", color="#9a9da2")
        if k.small:
            k.cyl("vent_cap", "lid", (-rb * 0.55, 0.0, H + 0.005), 0.016, 0.012, mat="bare_metal", color="#9a9da2")
        hb = 0.5
        rbng = rb
    if P["bung"] and v == "wood":
        k.cyl("bung", "lid", (0, -(rbng - 0.004), hb * H), 0.026 * c, 0.03, "y")
    if P["spigot"]:
        hs = 0.14 * H
        rs = rad(hs) if v == "wood" else rb
        k.cyl("spigot", "accent", (0, -(rs + 0.03), hs), 0.016 * c, 0.07, "y")
        k.cyl("spigot_spout", "accent", (0, -(rs + 0.06), hs - 0.025), 0.011 * c, 0.05)
        if k.small:
            k.box("spigot_key", "accent", (0, -(rs + 0.05), hs + 0.016 * c + 0.005), (0.05, 0.012, 0.014))
    if P["lying"]:
        _tip_over(k.parts, H)
        rmax = rb + 0.01
        for s, nm in ((1, "a"), (-1, "b")):
            k.prof(f"chock_{nm}", "lid", [(-0.08, -rmax - 0.001), (0.08, -rmax - 0.001), (0.06, -rmax + 0.08),
                                          (-0.06, -rmax + 0.08)], rb * 1.5, pos=(s * H * 0.3, 0, 0),
                   rot=[0, 0, 90])
    return k.spec()


# ------------------------------------------------------------------ generic box prop
BOX_ROLES = {
    "body": Role("#6f7a80", "painted_metal", "main body"),
    "trim": Role("#2f3236", "gunmetal", "base, top cap, frame"),
    "metal": Role("#a3a6aa", "bare_metal", "handles, hinges, knobs"),
    "accent": Role("#3fd27a", "emissive", "screen / indicator light"),
}
BOX_PARAMS = {
    "variant": Param("enum", "plain", choices=("plain", "cabinet", "machine", "safe", "locker"),
                     doc="plain box | cabinet with doors | machine/console | safe | tall locker"),
    "length": Param("num", 0.6, 0.15, 2.0),
    "width": Param("num", 0.45, 0.15, 1.5),
    "height": Param("num", 0.6, 0.15, 2.2),
    "feet": Param("bool", True),
    "handle": Param("bool", True),
    "panel": Param("bool", True, doc="framed front panel / doors"),
    "light": Param("bool", False, doc="glowing screen or indicator"),
    "vents": Param("bool", False, doc="vent slots"),
}


def build_box_prop(P, R, style):
    v = P["variant"]
    L, W, H = P["length"], P["width"], P["height"]
    if v == "locker" and (L, W, H) == (0.6, 0.45, 0.6):
        L, W, H = 0.45, 0.5, 1.8
    if v == "cabinet":
        R = _alt(R, BOX_ROLES, "body", "wood", "#8a5a32")
        R = _alt(R, BOX_ROLES, "trim", "dark_wood", "#5a3a22")
    k = Kit({"plain": "box", "cabinet": "cabinet", "machine": "machine", "safe": "safe", "locker": "locker"}[v],
            "prop", style, R)
    c = k.chunk
    fz = 0.04 if P["feet"] else 0.0
    base = 0.035 * (c ** 0.5)
    k.box("plinth", "trim", (0, 0, fz + base / 2), (L, W, base))
    hb = H - fz - base - (0.03 if v != "machine" else 0.0)
    k.box("body", "body", (0, 0, fz + base + hb / 2 - 0.001), (L * 0.97, W * 0.97, hb + 0.002), bevel=k.bev(3))
    if v != "machine":
        k.box("top_cap", "trim", (0, 0, H - 0.015), (L + 0.01, W + 0.01, 0.03), bevel=k.bev(2))
    if P["feet"]:
        fx, fy = L / 2 - 0.05, W / 2 - 0.05
        k.cyl("foot_a", "trim", (fx, fy, fz / 2 + 0.001), 0.025 * c, fz + 0.002, mirror_y=True)
        k.cyl("foot_b", "trim", (-fx, fy, fz / 2 + 0.001), 0.025 * c, fz + 0.002, mirror_y=True)
    yf = -W * 0.485
    zc = fz + base + hb / 2
    if v in ("cabinet", "locker") and P["panel"]:
        nd = 2 if (v == "cabinet" and L > 0.5) else 1
        dw = (L * 0.93 - 0.008 * (nd - 1)) / nd
        for i in range(nd):
            x = -L * 0.465 + dw / 2 + i * (dw + 0.008)
            k.box(f"door{i}", "body", (x, yf - 0.008, zc), (dw, 0.016, hb * 0.94), bevel=k.bev(2))
            if P["handle"]:
                hx = x + (dw * 0.38 if i == 0 and nd == 2 else -dw * 0.38 if nd == 2 else dw * 0.38)
                k.box(f"door_handle{i}", "metal", (hx, yf - 0.026, zc + (0 if v == "cabinet" else hb * 0.05)),
                      (0.014, 0.02, min(0.14, hb * 0.18)))
            if v == "locker" and not k.low:
                st = min(0.022, hb * 0.08)
                k.box(f"vent{i}", "trim", (x, yf - 0.017, zc + hb * 0.3), (dw * 0.6, 0.004, st * 0.55), count=4,
                      step=[0, 0, st])
    elif v == "safe":
        k.box("door", "body", (0, yf - 0.012, zc), (L * 0.8, 0.024, hb * 0.82), bevel=k.bev(3))
        k.cyl("dial", "metal", (L * 0.12, yf - 0.034, zc + hb * 0.12), 0.04 * (c ** 0.5), 0.02, "y")
        if P["handle"]:
            k.cyl("wheel_hub", "metal", (-L * 0.12, yf - 0.034, zc), 0.02, 0.02, "y")
            for i in range(3):
                k.box(f"wheel_spoke{i}", "metal", (-L * 0.12, yf - 0.04, zc), (0.012, 0.012, 0.14), rot=[0, 60 * i, 0])
        k.cyl("hinge", "metal", (L * 0.4, yf - 0.012, zc - hb * 0.25), 0.012, 0.08, count=2, step=[0, 0, hb * 0.5])
    elif v == "machine":
        k.box("console", "body", (0, yf + 0.06, H + 0.0), (L * 0.9, 0.14, 0.08), taper=[1.0, 0.4], bevel=k.bev(2))
        k.box("screen", "accent", (0, yf - 0.002, zc + hb * 0.2), (L * 0.5, 0.008, hb * 0.28))
        if k.small:
            k.cyl("button", "metal", (-L * 0.25, yf - 0.006, zc - hb * 0.12), 0.015, 0.014, "y", count=3,
                  step=[L * 0.25, 0, 0])
        if P["handle"]:
            k.tube("handle", "metal", [(L * 0.49, -W * 0.2, zc + hb * 0.25), (L * 0.53, -W * 0.18, zc + hb * 0.25),
                                       (L * 0.53, W * 0.18, zc + hb * 0.25), (L * 0.49, W * 0.2, zc + hb * 0.25)],
                   0.011 * c)
    else:
        if P["panel"]:
            k.box("panel", "trim", (0, yf - 0.004, zc), (L * 0.8, 0.008, hb * 0.7), bevel=k.bev(1))
        if P["handle"]:
            k.tube("handle", "metal", [(L * 0.485, -W * 0.18, zc + hb * 0.2), (L * 0.525, -W * 0.15, zc + hb * 0.2),
                                       (L * 0.525, W * 0.15, zc + hb * 0.2), (L * 0.485, W * 0.18, zc + hb * 0.2)],
                   0.01 * c)
    if P["light"] and v != "machine":
        off = 0.024 if v == "safe" else (0.016 if v in ("cabinet", "locker") and P["panel"] else 0.0)
        k.box("indicator", "accent", (L * 0.32, yf - off - 0.004, zc + hb * 0.38), (0.04, 0.01, 0.02))
    if P["vents"] and v != "locker":
        if k.cuts_ok:
            k.parts[1].setdefault("cuts", []).append(_cbox((0.01, 0.03, hb * 0.4), side="left", u=0.0, v=0.0, count=6,
                                                           step=(0.025, 0, 0)))
        else:
            k.box("vent_grille", "trim", (0, W * 0.485 + 0.002, zc), (L * 0.5, 0.006, hb * 0.4))
    return k.spec()


# ------------------------------------------------------------------ registry
def _t(name, summary, category, params, roles, build, keywords):
    return Template(name, summary, category, params, roles, build, keywords)


TEMPLATES: dict[str, Template] = {
    "box_prop": _t("box_prop", "generic box-shaped prop: crate-like box, cabinet, machine/console, safe, locker",
                   "prop", BOX_PARAMS, BOX_ROLES, build_box_prop,
                   ("box", "cabinet", "machine", "console", "safe", "locker", "generator", "terminal", "cupboard")),
    "firearm": _t("firearm", "gun: pistol, hunting/sniper rifle, SMG, assault rifle, pump shotgun, sci-fi blaster",
                  "weapon", GUN_PARAMS, GUN_ROLES, build_firearm,
                  ("gun", "rifle", "pistol", "handgun", "shotgun", "smg", "blaster", "sniper", "carbine", "firearm",
                   "revolver", "laser")),
    "sword": _t("sword", "sword: longsword, shortsword, broadsword, sabre, katana", "weapon", SWORD_PARAMS, SWORD_ROLES,
                build_sword, ("sword", "blade", "katana", "sabre", "saber", "longsword", "claymore", "cutlass")),
    "axe": _t("axe", "axe: wood axe, fire axe with pick, battle axe, hatchet", "weapon", AXE_PARAMS, AXE_ROLES,
              build_axe, ("axe", "hatchet", "tomahawk", "pickaxe")),
    "vehicle": _t("vehicle", "wheeled vehicle: car, van, pickup truck, tractor, ATV/quad, go-kart", "vehicle",
                  VEH_PARAMS, VEH_ROLES, build_vehicle,
                  ("car", "van", "truck", "pickup", "tractor", "atv", "quad", "kart", "vehicle", "jeep", "buggy")),
    "table": _t("table", "table, workbench or office desk (legs, top, shelf, drawers, vise, lamp)", "furniture",
                TABLE_PARAMS, TABLE_ROLES, build_table, ("table", "desk", "workbench", "bench", "counter")),
    "chair": _t("chair", "seat: dining/tavern chair, office chair, armchair, bar stool", "furniture", CHAIR_PARAMS,
                CHAIR_ROLES, build_chair, ("chair", "stool", "armchair", "seat", "throne")),
    "crate": _t("crate", "wooden crate or military ammo box (boards, latches, handles, stencil)", "prop", CRATE_PARAMS,
                CRATE_ROLES, build_crate, ("crate", "ammo", "box", "supply")),
    "chest": _t("chest", "treasure chest with domed or flat lid, metal bands, lock", "prop", CHEST_PARAMS, CHEST_ROLES,
                build_chest, ("chest", "treasure", "trunk", "coffer", "loot")),
    "jerrycan": _t("jerrycan", "jerrycan fuel can with three handles and spout", "prop", JERRY_PARAMS, JERRY_ROLES,
                   build_jerrycan, ("jerrycan", "jerry", "fuel", "gas", "can", "canister")),
    "backpack": _t("backpack", "backpack: hiking, military rucksack, school bag, adventurer pack", "accessory",
                   PACK_PARAMS, PACK_ROLES, build_backpack, ("backpack", "rucksack", "bag", "pack", "knapsack")),
    "helmet": _t("helmet", "helmet: modern combat helmet or medieval knight great helm", "accessory", HELMET_PARAMS,
                 HELMET_ROLES, build_helmet, ("helmet", "helm", "headgear")),
    "barrel": _t("barrel", "barrel: wooden barrel with hoops or steel oil drum", "prop", BARREL_PARAMS, BARREL_ROLES,
                 build_barrel, ("barrel", "keg", "cask", "drum")),
}


def build_spec(template_name: str, params_answer: dict | None, style: str, category: str | None = None):
    """Clamp a planner answer ({"params", "colors", "kinds"}) and build the raw spec. Returns (raw_spec, notes).

    `category` (the brief's category) only overrides the spec's category label; geometry stays the template's."""
    t = TEMPLATES.get(template_name) or TEMPLATES["box_prop"]
    params, roles, notes = resolve(t, params_answer, KINDS)
    raw = t.build(params, roles, style if style in A.STYLES else "pbr")
    if category in A.CATEGORIES and category != raw["category"]:
        notes.append(f"category {raw['category']} -> {category}")
        raw["category"] = category
    if isinstance(params_answer, dict) and params_answer.get("name"):
        raw["name"] = str(params_answer["name"])[:60]
    return raw, notes
