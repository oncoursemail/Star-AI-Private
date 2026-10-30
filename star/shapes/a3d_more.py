"""More 3D part templates (art-v2): characters, creatures, buildings, bookshelf, blunt weapons, two-wheelers, lanterns.

Same rules as star.shapes.a3d (absolute positions in metres, +X front, +Y left, +Z up), with one exception:
humanoids and buildings face -Y (the side the default renders look at most), so their left/right pairs run
along X and are added explicitly instead of with mirror_y. Creatures and two-wheelers point their head/front at +X.
"""
from __future__ import annotations

import math

from .a3d import Kit, _alt, _r
from .core import Param, Role


def _dir_rot(p0, p1):
    """Euler (deg) turning a z-axis part so it runs from p0 to p1; returns (centre, length, rot)."""
    d = [p1[i] - p0[i] for i in range(3)]
    L = math.sqrt(sum(x * x for x in d)) or 1e-6
    u = [x / L for x in d]
    a = math.asin(max(-1.0, min(1.0, -u[1])))
    b = math.atan2(u[0], u[2])
    c = [(p0[i] + p1[i]) / 2 for i in range(3)]
    return c, L, [math.degrees(a), math.degrees(b), 0.0]


def _limb(k, pid, role, p0, p1, r0, r1, **kw):
    """Tapered round limb from p0 (radius r0) to p1 (radius r1)."""
    c, L, rot = _dir_rot(p0, p1)
    return k.cone(pid, role, c, r0, r1, L, "z", rot=rot, **kw)


def _beam(k, pid, role, p0, p1, w, h, **kw):
    """Square beam from p0 to p1 (w x h cross-section)."""
    c, L, rot = _dir_rot(p0, p1)
    return k.box(pid, role, c, (w, h, L), rot=rot, **kw)


def _fit(k, longest):
    """Spec scaled down (never up) so its longest side stays within `longest` metres."""
    from .a3d import bounds
    raw = k.spec()
    lo, hi = bounds(raw)
    m = max(hi[i] - lo[i] for i in range(3))
    return k.spec(longest / m) if m > longest else raw


def _lr(fn, *args):
    """Call fn(sx) for the left (+1) and right (-1) side."""
    for sx in (1, -1):
        fn(sx, *args)


# ------------------------------------------------------------------ humanoid character (faces -Y)
HUMAN_ROLES = {
    "skin": Role("#d9a27a", "fabric", "face and hands (or robot plating)"),
    "outfit": Role("#3f6a8a", "fabric", "tunic / robe / armour plates"),
    "legs": Role("#4a4038", "fabric", "trousers / leg armour"),
    "boots": Role("#3a2a1e", "leather", "boots / feet"),
    "hair": Role("#4a3122", "fabric", "hair, beard, hood"),
    "accent": Role("#8a5a2a", "leather", "belt, straps, trim, hat"),
}
_FIXED = {"metal": {"kind": "bare_metal", "color": "#a9adb3"}, "glow": {"kind": "emissive", "color": "#3fe0ff"}}
HUMAN_PARAMS = {
    "variant": Param("enum", "villager", choices=("villager", "adventurer", "knight", "soldier", "wizard", "robot"),
                     doc="villager | adventurer | armoured knight | soldier | robed wizard | robot"),
    "height": Param("num", 1.0, 0.75, 1.25, doc="height factor (1 = 1.8 m)"),
    "bulk": Param("num", 1.0, 0.8, 1.4, doc="body width factor"),
    "head_scale": Param("num", 1.0, 0.8, 1.6, doc="head size factor (cartoon > 1.2)"),
    "helmet": Param("enum", "auto", choices=("auto", "none", "great_helm", "open")),
    "hat": Param("enum", "none", choices=("none", "wide", "hood", "pointed", "cap")),
    "weapon": Param("enum", "auto", choices=("auto", "none", "sword", "staff", "axe")),
    "shield": Param("bool", False),
    "cape": Param("bool", False),
    "backpack": Param("bool", False),
    "beard": Param("bool", False),
    "antenna": Param("bool", True, doc="robot antenna"),
    "chest_light": Param("bool", True, doc="robot chest light"),
}
_H_AUTO = {"villager": ("none", "none"), "adventurer": ("none", "sword"), "knight": ("great_helm", "sword"),
           "soldier": ("open", "none"), "wizard": ("none", "staff"), "robot": ("none", "none")}


def _head_human(k, z, hr, P, v, blocky):
    """Head centred at height z (radius hr); face toward -Y."""
    if blocky:
        k.box("head", "skin", (0, 0, z), (hr * 2.0, hr * 1.9, hr * 1.9), bevel=k.bev(3))
        if v == "robot":
            k.box("visor", "glow", (0, -hr * 0.96, z + hr * 0.1), (hr * 1.5, hr * 0.06, hr * 0.42))
            if P["antenna"] and k.small:
                k.cyl("antenna", "metal", (hr * 0.5, 0, z + hr * 1.25), hr * 0.06, hr * 0.6)
                k.ball("antenna_tip", "glow", (hr * 0.5, 0, z + hr * 1.6), hr * 0.14)
            k.cyl("ear_l", "metal", (hr * 1.02, 0, z), hr * 0.3, hr * 0.12, "x")
            k.cyl("ear_r", "metal", (-hr * 1.02, 0, z), hr * 0.3, hr * 0.12, "x")
        else:
            for sx in (1, -1):
                k.box(f"eye{'l' if sx > 0 else 'r'}", "accent", (sx * hr * 0.42, -hr * 0.96, z + hr * 0.15),
                      (hr * 0.28, hr * 0.06, hr * 0.32), mat="plastic", color="#1c1a24")
            k.box("mouth", "accent", (0, -hr * 0.96, z - hr * 0.45), (hr * 0.6, hr * 0.06, hr * 0.12), mat="plastic",
                  color="#5a2a2a")
            if P["hat"] == "none":
                k.box("hair", "hair", (0, hr * 0.12, z + hr * 0.8), (hr * 2.1, hr * 1.8, hr * 0.45), bevel=k.bev(2))
        return
    k.ball("head", "skin", (0, 0, z), hr, scale=[0.92, 1.0, 1.12])
    if k.small:
        k.ball("nose", "skin", (0, -hr * 0.95, z - hr * 0.1), hr * 0.18, scale=[0.8, 1.0, 1.1])
        for sx in (1, -1):
            k.ball(f"eye{'l' if sx > 0 else 'r'}", "accent", (sx * hr * 0.36, -hr * 0.86, z + hr * 0.12), hr * 0.12,
                   mat="plastic", color="#1c1a24")
            k.ball(f"ear{'l' if sx > 0 else 'r'}", "skin", (sx * hr * 0.9, hr * 0.05, z), hr * 0.2,
                   scale=[0.5, 1.0, 1.3])
    if P["hat"] == "none" and v not in ("wizard",):
        k.ball("hair", "hair", (0, hr * 0.12, z + hr * 0.22), hr * 1.04, scale=[0.95, 1.0, 0.95])
    if P["beard"] or v == "wizard":
        k.cone("beard", "hair", (0, -hr * 0.62, z - hr * 0.85), hr * 0.62, hr * 0.12, hr * (1.4 if v == "wizard" else
                                                                                           0.8), rot=[180, 0, 0])


def build_humanoid(P, R, style):
    v = P["variant"]
    if v == "knight":
        R = _alt(R, HUMAN_ROLES, "outfit", "bare_metal", "#b4b8be")
        R = _alt(R, HUMAN_ROLES, "legs", "bare_metal", "#a4a8ae")
        R = _alt(R, HUMAN_ROLES, "boots", "bare_metal", "#9a9ea4")
        R = _alt(R, HUMAN_ROLES, "accent", "fabric", "#7a1f24")
    elif v == "robot":
        R = _alt(R, HUMAN_ROLES, "skin", "painted_metal", "#c9ced4")
        R = _alt(R, HUMAN_ROLES, "outfit", "painted_metal", "#4f8ad0")
        R = _alt(R, HUMAN_ROLES, "legs", "painted_metal", "#5a5f66")
        R = _alt(R, HUMAN_ROLES, "boots", "gunmetal", "#3a3c40")
        R = _alt(R, HUMAN_ROLES, "accent", "gunmetal", "#3a3c40")
    elif v == "wizard":
        R = _alt(R, HUMAN_ROLES, "outfit", "fabric", "#3a3a8a")
        R = _alt(R, HUMAN_ROLES, "hair", "fabric", "#d8d4cc")
    elif v == "soldier":
        R = _alt(R, HUMAN_ROLES, "outfit", "fabric", "#5a6346")
        R = _alt(R, HUMAN_ROLES, "legs", "fabric", "#4f5640")
    k = Kit(v, "character", style, dict(R, **_FIXED))
    blocky = k.rbx or v == "robot"
    helm_a, weap_a = _H_AUTO[v]
    helm = helm_a if P["helmet"] == "auto" else P["helmet"]
    weapon = weap_a if P["weapon"] == "auto" else P["weapon"]
    H = 1.8 * P["height"]
    s = H / 1.8
    bk = P["bulk"] * (1.1 if v in ("knight", "robot") else 1.0)
    hs = P["head_scale"] * (1.3 if k.sty else 1.15 if k.rbx else 1.0)
    hr = 0.115 * s * hs
    # key heights (realistic 1.8 m figure; a big cartoon head is added on top, not squeezed in)
    z_knee, z_hip, z_waist, z_sh = 0.5 * s, 0.92 * s, 1.08 * s, 1.47 * s
    sw = 0.2 * s * bk  # half shoulder width
    hx = 0.095 * s * bk  # hip joint offset
    if blocky:
        lw = 0.15 * s * bk
        for sx in (1, -1):
            n = "l" if sx > 0 else "r"
            k.box(f"leg_{n}", "legs", (sx * lw * 0.55, 0, z_hip / 2 + 0.03 * s), (lw, lw * 1.1, z_hip - 0.06 * s),
                  bevel=k.bev(2))
            k.box(f"boot_{n}", "boots", (sx * lw * 0.55, -0.02 * s, 0.05 * s), (lw * 1.08, lw * 1.35, 0.1 * s),
                  bevel=k.bev(2))
            k.box(f"arm_{n}", "outfit" if v != "robot" else "legs", (sx * (sw + lw * 0.5), 0, z_sh - 0.28 * s),
                  (lw, lw, 0.58 * s), bevel=k.bev(2))
            k.box(f"hand_{n}", "skin", (sx * (sw + lw * 0.5), 0, z_sh - 0.62 * s), (lw * 0.9, lw * 0.9, 0.12 * s),
                  bevel=k.bev(2))
            if v == "robot" and k.small:
                k.cyl(f"shoulder_{n}", "accent", (sx * (sw + lw * 0.1), 0, z_sh - 0.03 * s), lw * 0.45, lw * 0.4, "x")
        k.box("torso", "outfit", (0, 0, (z_hip + z_sh) / 2), (sw * 2, 0.2 * s * bk, z_sh - z_hip + 0.04 * s),
              bevel=k.bev(3))
        if v == "robot":
            if P["chest_light"]:
                k.cyl("chest_light", "glow", (0, -0.1 * s * bk - 0.004, z_sh - 0.17 * s), 0.045 * s, 0.02, "y")
            if k.small:
                k.box("chest_panel", "accent", (0, -0.1 * s * bk - 0.002, z_sh - 0.32 * s), (sw * 1.1, 0.012, 0.12 * s))
                k.box("belt", "accent", (0, 0, z_hip + 0.03 * s), (sw * 2.04, 0.21 * s * bk, 0.06 * s))
        else:
            k.box("belt", "accent", (0, 0, z_hip + 0.04 * s), (sw * 2.04, 0.21 * s * bk, 0.05 * s))
        k.box("neck", "skin", (0, 0, z_sh + 0.03 * s), (0.08 * s, 0.08 * s, 0.06 * s))
        zh = z_sh + 0.06 * s + hr * 0.95
    else:
        lr = 0.072 * s * bk
        for sx in (1, -1):
            n = "l" if sx > 0 else "r"
            x = sx * hx
            _limb(k, f"thigh_{n}", "legs", (x, 0, z_hip), (x * 0.96, -0.01 * s, z_knee), lr * 1.15, lr * 0.85)
            _limb(k, f"shin_{n}", "legs" if v != "knight" else "boots", (x * 0.96, -0.01 * s, z_knee),
                  (x * 0.94, 0, 0.09 * s), lr * 0.85, lr * 0.62)
            if k.small:
                k.ball(f"knee_{n}", "legs" if v != "knight" else "metal", (x * 0.96, -0.012 * s, z_knee), lr * 0.88)
            k.box(f"boot_{n}", "boots", (x * 0.94, -0.045 * s, 0.045 * s), (lr * 1.6, 0.25 * s, 0.09 * s),
                  bevel=k.bev(3))
            if v not in ("wizard",):
                k.ball(f"bootcuff_{n}", "boots", (x * 0.94, 0, 0.1 * s), lr * 0.78, scale=[1.0, 1.0, 1.1])
            # arms hang slightly out from the body
            shp = (sx * sw, 0, z_sh - 0.03 * s)
            elb = (sx * (sw + 0.03 * s), 0.01 * s, z_sh - 0.31 * s)
            wri = (sx * (sw + 0.045 * s), -0.03 * s, z_sh - 0.57 * s)
            arm_role = "outfit" if v != "knight" else "legs"
            k.ball(f"shoulder_{n}", arm_role, shp, lr * 0.95)
            _limb(k, f"upperarm_{n}", arm_role, shp, elb, lr * 0.85, lr * 0.68)
            _limb(k, f"forearm_{n}", arm_role, elb, wri, lr * 0.68, lr * 0.55)
            k.ball(f"hand_{n}", "skin" if v != "knight" else "metal", (wri[0], wri[1] - 0.005 * s, wri[2] - 0.05 * s),
                   lr * 0.62, scale=[0.8, 1.0, 1.3])
            if v == "knight":
                k.ball(f"pauldron_{n}", "outfit", (sx * (sw + 0.01 * s), 0, z_sh + 0.005 * s), lr * 1.55,
                       scale=[1.1, 1.05, 0.72])
                if k.small:
                    k.ball(f"couter_{n}", "metal", elb, lr * 0.75)
        k.ball("pelvis", "legs", (0, 0, z_hip + 0.02 * s), 0.16 * s * bk, scale=[1.0, 0.72, 0.6])
        k.ball("chest", "outfit", (0, 0, z_sh - 0.17 * s), 0.21 * s * bk, scale=[1.0, 0.62, 1.05])
        k.lathe("waist", "outfit", (0, 0, z_hip), [[0, 0.15 * s * bk], [z_waist - z_hip, 0.135 * s * bk],
                                                   [z_sh - 0.17 * s - z_hip, 0.17 * s * bk]], axis="z")
        if v in ("villager", "adventurer", "soldier", "knight"):  # tunic skirt / faulds
            k.cone("skirt", "outfit" if v != "knight" else "metal", (0, 0, z_hip - 0.03 * s), 0.2 * s * bk,
                   0.155 * s * bk, 0.16 * s, rot=[0, 0, 0])
        if v == "wizard":
            k.cone("robe", "outfit", (0, 0, (z_sh - 0.1 * s) / 2), 0.32 * s * bk, 0.17 * s * bk, z_sh - 0.1 * s)
        k.ring("belt", "accent", (0, 0, z_hip + 0.06 * s), 0.15 * s * bk, 0.022 * s, "z")
        if k.small:
            k.box("buckle", "metal", (0, -0.15 * s * bk - 0.01 * s, z_hip + 0.06 * s), (0.05 * s, 0.015 * s, 0.04 * s))
        if v == "knight" and k.small:
            k.ball("breastplate", "outfit", (0, -0.04 * s, z_sh - 0.2 * s), 0.2 * s * bk, scale=[0.95, 0.55, 0.95])
        k.cyl("neck", "skin", (0, 0, z_sh + 0.04 * s), 0.05 * s, 0.1 * s)
        zh = z_sh + 0.08 * s + hr * 1.0
    # head + headwear
    if helm == "great_helm":
        k.cyl("helm", "outfit", (0, 0, zh), hr * 1.08, hr * 2.25, bevel=k.bev(2))
        k.cone("helm_top", "outfit", (0, 0, zh + hr * 1.2), hr * 1.08, hr * 0.7, hr * 0.18)
        k.box("helm_slit", "accent", (0, -hr * 1.06, zh + hr * 0.25), (hr * 1.4, hr * 0.06, hr * 0.12),
              mat="gunmetal", color="#0e0e0e")
        k.box("helm_cross", "metal", (0, -hr * 1.06, zh - hr * 0.2), (hr * 0.16, hr * 0.08, hr * 1.5))
    elif helm == "open":
        _head_human(k, zh, hr, dict(P, hat="cap"), v, blocky)
        k.ball("helmet", "outfit", (0, hr * 0.05, zh + hr * 0.3), hr * 1.12, scale=[1.0, 1.05, 0.8])
        k.ring("helmet_rim", "accent", (0, hr * 0.05, zh + hr * 0.08), hr * 1.08, hr * 0.06, "z")
    else:
        _head_human(k, zh, hr, P, v, blocky)
    top = zh + hr * (1.15 if not blocky else 1.0)
    hat = P["hat"] if v != "wizard" or P["hat"] != "none" else "pointed"
    if helm == "none" and hat != "none":
        if hat == "wide":
            k.cyl("hat_brim", "accent", (0, 0, top - hr * 0.35), hr * 1.9, hr * 0.08)
            k.cone("hat_crown", "accent", (0, 0, top - hr * 0.05), hr * 0.95, hr * 0.8, hr * 0.6)
        elif hat == "pointed":
            k.cyl("hat_brim", "outfit", (0, 0, top - hr * 0.3), hr * 1.7, hr * 0.07)
            k.cone("hat_cone", "outfit", (0, 0, top + hr * 0.75), hr * 1.0, hr * 0.06, hr * 2.1, rot=[8, 0, 0])
        elif hat == "hood":
            k.ball("hood", "hair", (0, hr * 0.12, zh + hr * 0.1), hr * 1.18, scale=[1.0, 1.05, 1.1])
        elif hat == "cap":
            k.ball("cap", "accent", (0, 0, zh + hr * 0.45), hr * 1.02, scale=[1.0, 1.0, 0.6])
            k.box("cap_peak", "accent", (0, -hr * 1.0, zh + hr * 0.4), (hr * 1.2, hr * 0.6, hr * 0.06))
    # gear
    zb = z_hip + 0.06 * s
    if weapon == "sword":
        x = -(sw * 0.75)
        k.box("scabbard", "accent", (x - 0.03 * s, 0.02 * s, zb - 0.38 * s), (0.04 * s, 0.025 * s, 0.75 * s),
              rot=[0, -12, 0])
        k.box("sword_guard", "metal", (x + 0.02 * s, 0.02 * s, zb + 0.02 * s), (0.04 * s, 0.16 * s, 0.025 * s),
              rot=[0, -12, 0])
        k.cyl("sword_grip", "accent", (x + 0.035 * s, 0.02 * s, zb + 0.11 * s), 0.016 * s, 0.16 * s, rot=[0, -12, 0])
        k.ball("sword_pommel", "metal", (x + 0.05 * s, 0.02 * s, zb + 0.2 * s), 0.025 * s)
    elif weapon == "staff":
        xs = -(sw + 0.045 * s)  # held in the right hand
        k.cyl("staff", "accent", (xs, -0.035 * s, H * 0.55), 0.018 * s, H * 1.05, mat="wood", color="#6a4a2a")
        k.ball("staff_orb", "glow", (xs, -0.035 * s, H * 1.1), 0.05 * s)
        if k.small:
            k.ring("staff_claw", "metal", (xs, -0.035 * s, H * 1.06), 0.04 * s, 0.008 * s, "z")
    elif weapon == "axe":
        xs = -(sw + 0.06 * s)
        k.cyl("axe_haft", "accent", (xs, -0.05 * s, z_sh - 0.62 * s), 0.016 * s, 0.75 * s, mat="wood", color="#7a5230")
        k.box("axe_head", "metal", (xs, -0.12 * s, z_sh - 0.3 * s), (0.02 * s, 0.14 * s, 0.13 * s), taper=[1, 1.6])
    if P["shield"]:
        k.cyl("shield", "accent", (sw + 0.1 * s, -0.08 * s, z_sh - 0.45 * s), 0.25 * s, 0.03 * s, "x",
              rot=[0, 0, 0], mat="wood", color="#6a4a2a")
        k.cyl("shield_boss", "metal", (sw + 0.125 * s, -0.08 * s, z_sh - 0.45 * s), 0.06 * s, 0.03 * s, "x")
    if P["cape"]:
        k.box("cape", "accent", (0, 0.12 * s * bk, (z_sh + 0.3 * s) / 2 + 0.1 * s), (sw * 2.1, 0.02 * s, z_sh - 0.2 * s),
              taper=[0.75, 1.0], rot=[-4, 0, 0])
    if P["backpack"]:
        k.box("backpack", "accent", (0, 0.1 * s * bk + 0.06 * s, z_sh - 0.22 * s), (0.3 * s, 0.14 * s, 0.38 * s), bevel=k.bev(4))
        if k.small:
            k.cyl("bedroll", "outfit", (0, 0.1 * s * bk + 0.07 * s, z_sh - 0.0 * s), 0.06 * s, 0.34 * s, "x", mat="fabric",
                  color="#7a6a4a")
    return k.spec()


# ------------------------------------------------------------------ four-legged creature (head at +X)
BEAST_ROLES = {
    "fur": Role("#d0702a", "fabric", "main fur / hide"),
    "belly": Role("#f0e8dc", "fabric", "chest, belly, tail tip, muzzle"),
    "dark": Role("#2a221e", "leather", "nose, paws/hooves, ear tips"),
    "eye": Role("#1c1a18", "glass", "eyes"),
    "horn": Role("#d8ccb0", "ceramic", "antlers / horns / tusks"),
}
BEAST_PARAMS = {
    "variant": Param("enum", "fox", choices=("fox", "wolf", "dog", "cat", "deer", "horse", "cow", "bear", "lion"),
                     doc="sets the build; parts can be changed below"),
    "size": Param("num", 1.0, 0.5, 2.0, doc="scale vs a real animal of that kind"),
    "leg_len": Param("num", 1.0, 0.7, 1.4),
    "head_scale": Param("num", 1.0, 0.8, 1.6, doc="cartoon > 1.2"),
    "tail": Param("enum", "auto", choices=("auto", "bushy", "thin", "short", "tuft", "none")),
    "ears": Param("enum", "auto", choices=("auto", "pointy", "round", "long", "floppy")),
    "antlers": Param("bool", False),
    "horns": Param("bool", False),
    "mane": Param("bool", False),
    "chest_patch": Param("bool", True, doc="light chest/belly patch"),
}
#            body len, shoulder h, body h, head r, snout len, neck, tail, ears, hooves
_BEAST = {"fox": (0.62, 0.36, 0.22, 0.085, 0.11, 0.12, "bushy", "pointy", False),
          "wolf": (0.95, 0.68, 0.33, 0.11, 0.14, 0.18, "bushy", "pointy", False),
          "dog": (0.75, 0.5, 0.28, 0.1, 0.1, 0.15, "thin", "floppy", False),
          "cat": (0.46, 0.25, 0.17, 0.065, 0.03, 0.08, "thin", "pointy", False),
          "deer": (1.2, 0.95, 0.4, 0.1, 0.14, 0.42, "short", "long", True),
          "horse": (1.6, 1.5, 0.62, 0.14, 0.32, 0.6, "tuft", "pointy", True),
          "cow": (1.8, 1.35, 0.8, 0.16, 0.2, 0.3, "tuft", "floppy", True),
          "bear": (1.5, 0.95, 0.75, 0.17, 0.12, 0.2, "short", "round", False),
          "lion": (1.4, 0.95, 0.5, 0.15, 0.1, 0.25, "tuft", "round", False)}


def build_creature(P, R, style):
    v = P["variant"]
    Lb, Hs, Bh, hr0, sn, nk, tail_a, ears_a, hoof = _BEAST[v]
    defaults = {"wolf": "#7d7a74", "dog": "#a8743a", "cat": "#8a8076", "deer": "#9a6a3c", "horse": "#6a4228",
                "cow": "#f0ece4", "bear": "#5a3a24", "lion": "#c8923a"}
    if v in defaults:
        R = _alt(R, BEAST_ROLES, "fur", "fabric", defaults[v])
    k = Kit(v, "creature", style, R)
    s = P["size"]
    Lb, Bh, nk, sn = Lb * s, Bh * s, nk * s, sn * s
    hs = P["head_scale"] * (1.3 if k.sty else 1.15 if k.rbx else 1.0)
    hr = hr0 * s * hs
    leg = (Hs * s - Bh * 0.45) * P["leg_len"]  # ground to the body's lower third
    bw = Bh * (0.62 if v not in ("bear", "cow") else 0.8)
    zb = leg + Bh * 0.5  # body centre height
    tail = tail_a if P["tail"] == "auto" else P["tail"]
    ears = ears_a if P["ears"] == "auto" else P["ears"]
    # torso: barrel + chest + haunch
    k.ball("body", "fur", (0, 0, zb), Lb * 0.42, scale=[1.0, bw / (Lb * 0.84), Bh / (Lb * 0.84)])
    k.ball("chest", "fur", (Lb * 0.3, 0, zb + Bh * 0.06), Bh * 0.56, scale=[1.0, bw / Bh * 0.98, 1.05])
    k.ball("haunch", "fur", (-Lb * 0.3, 0, zb + Bh * 0.02), Bh * 0.54, scale=[1.0, bw / Bh * 0.98, 1.0])
    if P["chest_patch"] and v not in ("cow",):
        k.ball("chest_patch", "belly", (Lb * 0.42, 0, zb - Bh * 0.08), Bh * 0.36, scale=[0.8, bw / Bh * 0.8, 1.1])
    if v == "cow" and k.small:
        for i, (x, y, z) in enumerate(((0.05, -1, 0.1), (-0.25, -1, -0.05), (0.2, 1, 0.0))):
            k.ball(f"spot{i}", "dark", (x * Lb, y * bw * 0.4, zb + z * Bh), Bh * 0.28, scale=[1.2, 0.35, 0.9],
                   mat="fabric", color="#2a2622")
    # legs: upper + lower, hock bend on the hind legs
    lr = Bh * (0.16 if not hoof else 0.11) * (1.25 if v == "bear" else 1.0)
    for front, x in ((True, Lb * 0.32), (False, -Lb * 0.32)):
        n = "f" if front else "h"
        top = (x, bw * 0.3, zb - Bh * 0.1)
        knee = (x + (0.0 if front else -leg * 0.12), bw * 0.3, leg * 0.48)
        foot = (x + (0.0 if front else leg * 0.02), bw * 0.3, lr * 0.5)
        _limb(k, f"upper_{n}", "fur", top, knee, lr * 1.45, lr * 0.9, mirror_y=True)
        _limb(k, f"lower_{n}", "fur", knee, foot, lr * 0.9, lr * 0.72, mirror_y=True)
        if hoof:
            k.cyl(f"hoof_{n}", "dark", (foot[0], bw * 0.3, lr * 0.45), lr * 0.85, lr * 0.9, mirror_y=True)
        else:
            k.ball(f"paw_{n}", "dark" if v == "fox" else "fur", (foot[0] + lr * 0.4, bw * 0.3, lr * 0.55), lr * 1.0,
                   scale=[1.4, 1.0, 0.65], mirror_y=True)
    # neck + head
    nb = (Lb * 0.4, 0, zb + Bh * 0.25)
    ang = math.radians(55 if hoof else 35)
    hc = (nb[0] + nk * math.cos(ang) + hr * 0.4, 0, nb[2] + nk * math.sin(ang) + hr * 0.3)
    _limb(k, "neck", "fur", nb, (hc[0] - hr * 0.3, 0, hc[2] - hr * 0.2), Bh * 0.3, hr * 0.75)
    if P["mane"] or v == "lion":
        k.ball("mane", "dark" if v != "lion" else "fur", (hc[0] - hr * 0.5, 0, hc[2] - hr * 0.1), hr * 1.55,
               scale=[0.8, 1.0, 1.05], mat="fabric", color="#7a4a1e" if v == "lion" else None)
    elif v == "horse":
        _beam(k, "mane", "dark", (nb[0] - 0.05 * s, 0, nb[2] + Bh * 0.25), (hc[0] - hr * 0.6, 0, hc[2] + hr * 0.6),
              0.05 * s, 0.07 * s, mat="fabric")
    k.ball("head", "fur", hc, hr, scale=[1.1, 0.9, 0.9])
    tip = (hc[0] + hr * 0.6 + sn, 0, hc[2] - hr * (0.35 if hoof else 0.2))
    _limb(k, "snout", "fur" if v not in ("fox", "wolf", "dog") else "belly", (hc[0] + hr * 0.4, 0, hc[2] - hr * 0.15),
          tip, hr * 0.62, hr * (0.42 if hoof else 0.28))
    k.ball("nose", "dark", (tip[0], 0, tip[2] + hr * 0.08), hr * (0.22 if hoof else 0.16), scale=[0.8, 1.2, 0.8])
    k.ball("eye", "eye", (hc[0] + hr * 0.5, hr * 0.55, hc[2] + hr * 0.25), hr * 0.15, mirror_y=True)
    if ears == "pointy":
        _limb(k, "ear", "fur", (hc[0] - hr * 0.2, hr * 0.45, hc[2] + hr * 0.6),
              (hc[0] - hr * 0.3, hr * 0.62, hc[2] + hr * 1.55), hr * 0.32, hr * 0.02, mirror_y=True)
        if k.small and v == "fox":
            _limb(k, "ear_tip", "dark", (hc[0] - hr * 0.29, hr * 0.6, hc[2] + hr * 1.3),
                  (hc[0] - hr * 0.3, hr * 0.62, hc[2] + hr * 1.6), hr * 0.12, hr * 0.01, mirror_y=True)
    elif ears == "round":
        k.ball("ear", "fur", (hc[0] - hr * 0.2, hr * 0.62, hc[2] + hr * 0.75), hr * 0.3, scale=[0.5, 1.0, 1.0],
               mirror_y=True)
    elif ears == "long":
        _limb(k, "ear", "fur", (hc[0] - hr * 0.3, hr * 0.5, hc[2] + hr * 0.5),
              (hc[0] - hr * 0.45, hr * 1.5, hc[2] + hr * 1.0), hr * 0.28, hr * 0.08, mirror_y=True)
    else:  # floppy
        _limb(k, "ear", "fur" if v != "dog" else "dark", (hc[0] - hr * 0.25, hr * 0.7, hc[2] + hr * 0.4),
              (hc[0] - hr * 0.15, hr * 1.0, hc[2] - hr * 0.5), hr * 0.3, hr * 0.18, mirror_y=True)
    if P["antlers"] or (v == "deer" and not P["horns"]):
        base = (hc[0] - hr * 0.2, hr * 0.35, hc[2] + hr * 0.8)
        mid = (base[0] - hr * 0.5, hr * 1.1, base[2] + hr * 1.6)
        tipp = (mid[0] - hr * 0.6, hr * 1.5, mid[2] + hr * 1.4)
        ar = hr * 0.09
        _limb(k, "antler", "horn", base, mid, ar * 1.2, ar, mirror_y=True)
        _limb(k, "antler_top", "horn", mid, tipp, ar, ar * 0.5, mirror_y=True)
        if k.small:
            _limb(k, "antler_tine", "horn", mid, (mid[0] + hr * 0.7, hr * 1.25, mid[2] + hr * 0.9), ar * 0.8, ar * 0.3,
                  mirror_y=True)
            _limb(k, "antler_brow", "horn", (base[0], base[1] + hr * 0.2, base[2] + hr * 0.4),
                  (base[0] + hr * 0.8, hr * 0.8, base[2] + hr * 0.9), ar * 0.8, ar * 0.3, mirror_y=True)
    if P["horns"] or v == "cow":
        _limb(k, "horn", "horn", (hc[0] - hr * 0.2, hr * 0.6, hc[2] + hr * 0.55),
              (hc[0] + hr * 0.1, hr * 1.3, hc[2] + hr * 1.0), hr * 0.16, hr * 0.03, mirror_y=True)
    # tail from the rump
    rump = (-Lb * 0.3 - Bh * 0.5, 0, zb + Bh * 0.15)  # back edge of the haunch: the tail must attach
    if tail == "bushy":
        k.ball("tail", "fur", (rump[0] - Bh * 0.4, 0, rump[2] - Bh * 0.05), Bh * 0.28, scale=[1.6, 0.8, 0.8],
               rot=[0, 25, 0])
        k.ball("tail_end", "fur", (rump[0] - Bh * 1.15, 0, rump[2] - Bh * 0.22), Bh * 0.3, scale=[1.5, 0.9, 0.9],
               rot=[0, 15, 0])
        k.ball("tail_tip", "belly", (rump[0] - Bh * 1.7, 0, rump[2] - Bh * 0.3), Bh * 0.2, scale=[1.2, 0.9, 0.9])
    elif tail == "thin":
        k.tube("tail", "fur", [rump, (rump[0] - Lb * 0.2, 0, rump[2] + Bh * 0.1), (rump[0] - Lb * 0.35, 0,
                                                                                   rump[2] + Bh * 0.45)], Bh * 0.06)
    elif tail == "short":
        k.ball("tail", "fur" if v != "deer" else "belly", (rump[0] - Bh * 0.08, 0, rump[2] + Bh * 0.05), Bh * 0.14)
    elif tail == "tuft":
        k.tube("tail", "fur", [rump, (rump[0] - Lb * 0.06, 0, rump[2] - Bh * 0.4), (rump[0] - Lb * 0.08, 0,
                                                                                    rump[2] - Bh * 0.8)], Bh * 0.04)
        k.ball("tail_tuft", "dark", (rump[0] - Lb * 0.08, 0, rump[2] - Bh * 0.88), Bh * 0.1, scale=[0.8, 0.8, 1.4],
               mat="fabric")
    return _fit(k, 5.8)


# ------------------------------------------------------------------ building (door on -Y)
BUILD_ROLES = {
    "wall": Role("#e8dcc0", "stone", "walls / plaster"),
    "timber": Role("#5a3a22", "dark_wood", "beams, posts, frames, planks"),
    "roof": Role("#9a3a2a", "ceramic", "roof tiles / thatch / shingles"),
    "stone": Role("#8a8780", "stone", "foundation, chimney"),
    "door": Role("#7a4b2a", "wood", "door, shutters"),
    "glass": Role("#9fc4d8", "glass", "windows"),
}
BUILD_PARAMS = {
    "variant": Param("enum", "cottage", choices=("cottage", "house", "tower", "watchtower", "shop", "barn"),
                     doc="cottage | two-storey house | round stone tower | watchtower on legs | shop | barn"),
    "width": Param("num", 1.0, 0.7, 1.6),
    "depth": Param("num", 1.0, 0.7, 1.6),
    "floors": Param("int", 1, 1, 3),
    "roof": Param("enum", "auto", choices=("auto", "gable", "hip", "thatch", "pointed", "flat")),
    "chimney": Param("bool", True),
    "door": Param("enum", "square", choices=("square", "round")),
    "windows": Param("int", 2, 0, 4, doc="windows on the front"),
    "shutters": Param("bool", True),
    "timber_frame": Param("bool", False, doc="exposed timber beams on the walls"),
    "porch": Param("bool", False),
    "ladder": Param("bool", True, doc="watchtower ladder"),
    "crooked": Param("bool", False, doc="cartoon lean on the roof and chimney"),
}


def _window(k, x, y, z, w, h, shutters, pid):
    k.box(pid, "glass", (x, y - 0.01, z), (w, 0.04, h))
    k.box(pid + "_frame_t", "timber", (x, y - 0.035, z + h / 2), (w + 0.1, 0.06, 0.06))
    k.box(pid + "_frame_b", "timber", (x, y - 0.045, z - h / 2), (w + 0.16, 0.09, 0.07))
    if k.fine or (k.small and not shutters):
        k.box(pid + "_mullion", "timber", (x, y - 0.03, z), (0.035, 0.03, h))
        k.box(pid + "_transom", "timber", (x, y - 0.03, z), (w, 0.03, 0.035))
    if shutters:
        for sx in (1, -1):
            k.box(f"{pid}_shutter{'l' if sx > 0 else 'r'}", "door", (x + sx * (w / 2 + w * 0.27), y - 0.03, z),
                  (w * 0.5, 0.04, h + 0.06), bevel=k.bev(2))


def build_building(P, R, style):
    v = P["variant"]
    if v == "tower":
        R = _alt(R, BUILD_ROLES, "wall", "stone", "#9a968e")
        R = _alt(R, BUILD_ROLES, "roof", "ceramic", "#3a4a6a")
    elif v == "watchtower":
        R = _alt(R, BUILD_ROLES, "wall", "wood", "#9a6a3c")
        R = _alt(R, BUILD_ROLES, "roof", "wood", "#6a4a2e")
    elif v == "barn":
        R = _alt(R, BUILD_ROLES, "wall", "wood", "#9a2a22")
        R = _alt(R, BUILD_ROLES, "roof", "painted_metal", "#5a5a5a")
    k = Kit(v, "building", style, R)
    roof = P["roof"]
    if roof == "auto":
        roof = {"cottage": "thatch", "tower": "pointed", "watchtower": "pointed", "barn": "gable"}.get(v, "gable")
    lean = 4.0 if P["crooked"] else 0.0
    fh = 2.7  # storey height
    if v == "tower":
        r, H = 2.0 * P["width"], fh * max(2, P["floors"] + 1)
        k.cyl("plinth", "stone", (0, 0, 0.2), r * 1.08, 0.4)
        k.cyl("walls", "wall", (0, 0, 0.4 + H / 2), r, H, bevel=k.bev(4))
        if k.small:
            k.ring("band", "stone", (0, 0, 0.4 + H * 0.55), r * 1.01, 0.08, "z")
        k.ring("parapet", "stone", (0, 0, 0.4 + H), r * 1.02, 0.16, "z")
        zt = 0.4 + H
        if roof in ("pointed", "thatch", "gable", "hip"):
            k.cone("roof", "roof", (0, 0, zt + r * 0.9), r * 1.25, 0.03, r * 1.8, rot=[lean, 0, 0])
            if k.small:
                k.cyl("finial", "stone", (0, 0, zt + r * 1.85), 0.05, 0.4)
        else:
            for i in range(8):
                a = math.radians(45 * i)
                k.box(f"merlon{i}", "stone", (r * math.cos(a), r * math.sin(a), zt + 0.3), (0.45, 0.35, 0.5),
                      rot=[0, 0, 45 * i])
        dw = 0.95
        k.box("door", "door", (0, -r - 0.02, 0.4 + 1.0), (dw, 0.1, 2.0), bevel=k.bev(3))
        if P["door"] == "round":
            k.cyl("door_arch", "door", (0, -r - 0.02, 0.4 + 2.0), dw / 2, 0.1, "y")
        for i in range(min(P["windows"], 3)):
            z = 0.4 + fh * (i + 1) + 0.9
            if z + 0.6 > 0.4 + H:
                break
            _window(k, 0, -r * 0.985, z, 0.55, 0.8, False, f"win{i}")
        return k.spec()
    W, D = 6.0 * P["width"], 5.0 * P["depth"]
    if v == "shop":
        W *= 1.15
    nf = P["floors"] if v != "watchtower" else 1
    if v == "watchtower":
        W = D = 2.6 * P["width"]
        legh = 4.5
        for sx in (1, -1):
            for sy in (1, -1):
                _beam(k, f"leg{'l' if sx > 0 else 'r'}{'b' if sy > 0 else 'f'}", "timber",
                      (sx * (W / 2 + 0.25), sy * (D / 2 + 0.25), 0.0), (sx * (W / 2 - 0.1), sy * (D / 2 - 0.1), legh),
                      0.22, 0.22)
        if k.small:  # X braces on the front and sides
            for face, (a, b) in enumerate((((W / 2, -D / 2), (-W / 2, -D / 2)), ((W / 2, D / 2), (W / 2, -D / 2)),
                                           ((-W / 2, -D / 2), (-W / 2, D / 2)))):
                (x0, y0), (x1, y1) = a, b
                _beam(k, f"brace{face}a", "timber", (x0 * 1.06, y0 * 1.06, 0.5), (x1 * 1.0, y1 * 1.0, legh - 0.4),
                      0.1, 0.1)
                _beam(k, f"brace{face}b", "timber", (x1 * 1.06, y1 * 1.06, 0.5), (x0 * 1.0, y0 * 1.0, legh - 0.4),
                      0.1, 0.1)
        k.box("platform", "timber", (0, 0, legh + 0.1), (W + 0.7, D + 0.7, 0.2), bevel=k.bev(4))
        k.box("cabin_wall", "wall", (0, 0, legh + 0.2 + 0.5), (W, D, 1.0), bevel=k.bev(4))
        for sx in (1, -1):
            for sy in (1, -1):
                k.box(f"post{'l' if sx > 0 else 'r'}{'b' if sy > 0 else 'f'}", "timber",
                      (sx * W / 2, sy * D / 2, legh + 1.4), (0.16, 0.16, 2.4))
        zt = legh + 2.6
        k.box("roof", "roof", (0, 0, zt + 0.9), (W + 0.9, D + 0.9, 1.8), taper=[0.05, 0.05], rot=[lean, 0, 0])
        if k.small:
            k.cyl("finial", "timber", (0, 0, zt + 1.9), 0.06, 0.4)
        if P["ladder"]:
            y0, x0 = -D / 2 - 0.4, 0.0
            for sx in (1, -1):
                _beam(k, f"ladder_rail{'l' if sx > 0 else 'r'}", "timber", (x0 + sx * 0.25, y0 - 0.9, 0.0),
                      (x0 + sx * 0.25, y0 + 0.05, legh + 0.2), 0.07, 0.07)
            n = 8 if k.small else 4
            for i in range(n):
                t = (i + 0.7) / (n + 0.5)
                k.cyl(f"rung{i}", "timber", (x0, y0 - 0.9 * (1 - t) + 0.05 * t, t * (legh + 0.2)), 0.03, 0.5, "x")
        return k.spec()
    H = fh * nf
    k.box("foundation", "stone", (0, 0, 0.2), (W + 0.3, D + 0.3, 0.4), bevel=k.bev(4))
    k.box("walls", "wall", (0, 0, 0.4 + H / 2), (W, D, H), bevel=k.bev(4))
    zt = 0.4 + H
    if P["timber_frame"] or (v == "cottage" and P["timber_frame"]):
        for i, x in enumerate((-W / 2, W / 2)):
            k.box(f"corner{i}", "timber", (x, -D / 2, 0.4 + H / 2), (0.2, 0.2, H))
            k.box(f"corner_b{i}", "timber", (x, D / 2, 0.4 + H / 2), (0.2, 0.2, H))
        for f in range(nf + 1):
            k.box(f"beam{f}", "timber", (0, -D / 2 - 0.02, 0.4 + f * fh - (0.1 if f == nf else 0) + (0.1 if f == 0 else 0)),
                  (W + 0.1, 0.12, 0.2))
        if k.small:
            k.box("brace_l", "timber", (-W / 3.2, -D / 2 - 0.02, 0.4 + fh * 0.5), (0.14, 0.1, fh * 1.0), rot=[0, 35, 0])
            k.box("brace_r", "timber", (W / 3.2, -D / 2 - 0.02, 0.4 + fh * 0.5), (0.14, 0.1, fh * 1.0), rot=[0, -35, 0])
    # roof: a wedge (taper) with overhang; the ridge runs along X
    over = 0.55 if roof != "thatch" else 0.75
    rh = (D + 2 * over) * (0.42 if roof != "thatch" else 0.55)
    if roof == "flat":
        k.box("roof", "roof", (0, 0, zt + 0.15), (W + 0.4, D + 0.4, 0.3))
        k.box("parapet", "stone", (0, -D / 2 - 0.15, zt + 0.45), (W + 0.4, 0.15, 0.3))
    else:
        taper = {"gable": [1.0, 0.05], "thatch": [0.92, 0.12], "hip": [max(0.1, (W - D) / W), 0.05],
                 "pointed": [0.05, 0.05]}[roof]
        k.box("roof", "roof", (0, 0, zt + rh / 2 - 0.05), (W + 2 * over, D + 2 * over, rh), taper=taper,
              rot=[0, lean, 0], bevel=k.bev(12 if roof == "thatch" else 3))
        if roof in ("gable",) and k.small:
            k.box("ridge", "timber", (0, 0, zt + rh - 0.02), (W + 2 * over + 0.1, 0.18, 0.12))
            k.box("fascia_l", "timber", (W / 2 + over - 0.03, 0, zt + 0.05), (0.08, D + 2 * over, 0.18))
            k.box("fascia_r", "timber", (-W / 2 - over + 0.03, 0, zt + 0.05), (0.08, D + 2 * over, 0.18))
        if roof == "thatch" and k.small:
            k.box("thatch_lip", "roof", (0, -D / 2 - over + 0.15, zt + 0.08), (W + 2 * over - 0.2, 0.35, 0.22),
                  bevel=k.bev(10))
    if P["chimney"] and roof != "flat":
        cx = W * 0.28
        k.box("chimney", "stone", (cx, D * 0.15, zt + rh * 0.65), (0.6, 0.6, rh * 1.3 + 0.8), rot=[0, lean * 0.8, 0],
              bevel=k.bev(3))
        k.box("chimney_cap", "stone", (cx + lean * 0.02, D * 0.15, zt + rh * 1.3 + 0.45), (0.75, 0.75, 0.15))
    # door + windows on the front (-Y)
    dw, dh = (1.0, 2.05) if v != "barn" else (2.4, 2.6)
    dx = 0.0 if P["windows"] != 1 else -W * 0.2
    y_f = -D / 2
    k.box("door", "door", (dx, y_f - 0.03, 0.4 + dh / 2), (dw, 0.1, dh), bevel=k.bev(3))
    if P["door"] == "round":
        k.cyl("door_arch", "door", (dx, y_f - 0.03, 0.4 + dh), dw / 2, 0.1, "y")
    k.box("door_frame", "timber", (dx, y_f - 0.02, 0.4 + dh + 0.06 + (dw / 2 if P["door"] == "round" else 0)),
          (dw + 0.2, 0.1, 0.12))
    if k.small:
        k.ball("door_knob", "stone", (dx + dw * 0.35, y_f - 0.1, 0.4 + dh * 0.48), 0.05, mat="brass", color="#b8913f")
        k.box("step", "stone", (dx, y_f - 0.3, 0.12), (dw + 0.4, 0.5, 0.24))
    nw = P["windows"]
    shutters = P["shutters"] and nw <= 3  # four windows a floor leave no room for shutters
    slots = {0: [], 1: [W * 0.22], 2: [-W * 0.3, W * 0.3], 3: [-W * 0.32, W * 0.32],
             4: [-W * 0.4, -W * 0.22, W * 0.22, W * 0.4]}[nw]
    wins = [(x, f, str(i)) for f in range(nf) for i, x in enumerate(slots)]
    wins += [(0.0, f, "c") for f in range(1, nf) if nw >= 3]
    per = 3 + (2 if shutters else 0) + (2 if k.fine or (k.small and not shutters) else 0)
    room = max(0, (74 - len(k.parts)) // per)  # parts budget (80): ground floor first, then upwards
    for x, f, tag in sorted(wins, key=lambda w: w[1])[:room]:
        _window(k, x, y_f, 0.4 + f * fh + 1.45, 0.9, 1.0, shutters, f"win{f}{tag}")
    if P["porch"] or v == "shop":
        k.box("awning", "roof" if v != "shop" else "door", (dx, y_f - 0.66, 0.4 + dh + 0.35), (dw + 2.0, 1.4, 0.12),
              rot=[-14, 0, 0])
        for sx in (1, -1):
            k.cyl(f"porch_post{'l' if sx > 0 else 'r'}", "timber", (dx + sx * (dw / 2 + 0.85), y_f - 1.3, 0.4 + (dh + 0.2) / 2),
                  0.07, dh + 0.2)
    if v == "shop" and k.small:
        k.box("sign", "timber", (dx, y_f - 0.04, zt - 0.35), (W * 0.5, 0.08, 0.5))
    return k.spec()


# ------------------------------------------------------------------ bookshelf / shelving (front on -Y)
SHELF_ROLES = {
    "frame": Role("#7a5030", "wood", "sides, top, shelves"),
    "back": Role("#5a3a22", "dark_wood", "back panel"),
    "book_a": Role("#a83a3a", "leather", "books"),
    "book_b": Role("#3a6a9a", "leather", "books"),
    "book_c": Role("#4a8a4a", "leather", "books"),
    "book_d": Role("#c8a040", "leather", "books"),
}
SHELF_PARAMS = {
    "width": Param("num", 1.0, 0.5, 2.0, doc="1 = 0.9 m"),
    "height": Param("num", 1.0, 0.5, 1.6, doc="1 = 1.8 m"),
    "shelves": Param("int", 4, 2, 6),
    "fill": Param("num", 0.85, 0.0, 1.0, doc="how full the shelves are"),
    "crown": Param("bool", True, doc="moulded top"),
    "items": Param("bool", True, doc="a few jars/ornaments between the books"),
}
_BOOK_H = (0.84, 0.72, 0.9, 0.78, 0.66, 0.88, 0.75, 0.82, 0.7, 0.93)
_BOOK_W = (0.05, 0.035, 0.045, 0.06, 0.04, 0.03, 0.055, 0.04)


def build_shelf(P, R, style):
    k = Kit("bookshelf", "furniture", style, R)
    W, H, D = 0.9 * P["width"], 1.8 * P["height"], 0.32
    t = 0.03 * k.chunk
    for sx in (1, -1):
        k.box(f"side_{'l' if sx > 0 else 'r'}", "frame", (sx * (W / 2 - t / 2), 0, H / 2), (t, D, H))
    k.box("top", "frame", (0, -0.01, H + t / 2), (W + 0.04, D + 0.03, t))
    if P["crown"] and k.small:
        k.box("crown", "frame", (0, -0.02, H + t + 0.02), (W + 0.08, D + 0.06, 0.04), bevel=k.bev(3))
    k.box("plinth", "frame", (0, -0.005, 0.045), (W, D, 0.09))
    k.box("back", "back", (0, D / 2 - 0.006, H / 2), (W - 2 * t, 0.012, H))
    n = P["shelves"]
    gap = (H - 0.09) / n
    roles = ["book_a", "book_b", "book_c", "book_d"]
    inner = W - 2 * t
    count = 0
    for i in range(n):
        z0 = 0.09 + i * gap
        if i > 0:
            k.box(f"shelf{i}", "frame", (0, 0, z0 - t / 2), (inner, D - 0.01, t))
        if k.low:  # low poly: books as a few coloured blocks per shelf
            x = -inner / 2
            fillw = inner * P["fill"]
            for j in range(3):
                w = fillw / 3 - 0.01
                hb = (gap - t) * (0.8 - 0.08 * ((i + j) % 2))
                k.box(f"books{i}_{j}", roles[(i + j) % 4], (x + w / 2, -0.02, z0 + hb / 2), (w, D * 0.75, hb))
                x += w + 0.01
            continue
        x = -inner / 2 + 0.005
        j = 0
        limit = -inner / 2 + inner * P["fill"]
        while x < limit and count < 52:
            w = _BOOK_W[(i * 3 + j) % len(_BOOK_W)] * (1.3 if k.sty or k.rbx else 1.0)
            if x + w > inner / 2 - 0.005:
                break
            hb = (gap - t) * _BOOK_H[(i * 7 + j) % len(_BOOK_H)] * 0.92
            lean = 12 if (i + j) % 9 == 8 else 0
            k.box(f"book{i}_{j}", roles[(i + j * 3) % 4], (x + w / 2, -0.015, z0 + hb / 2 + (0.006 if lean else 0)),
                  (w, D * (0.72 + 0.06 * (j % 3)), hb), rot=[0, lean, 0], bevel=k.bev(1))
            x += w + 0.002
            j += 1
            count += 1
        if P["items"] and k.small and i % 2 == 1 and x < inner / 2 - 0.12:
            k.cyl(f"jar{i}", "book_d", (inner / 2 - 0.07, -0.02, z0 + 0.07), 0.04, 0.14, mat="glass", color="#6a9ab0")
            k.cyl(f"jar_lid{i}", "frame", (inner / 2 - 0.07, -0.02, z0 + 0.15), 0.042, 0.02)
    return k.spec()


# ------------------------------------------------------------------ blunt weapons (head at +X end of the haft)
BLUNT_ROLES = {
    "head": Role("#6a6c70", "gunmetal", "hammer head / mace head (stone or metal)"),
    "handle": Role("#7a5230", "wood", "haft"),
    "grip": Role("#4a2e1c", "leather", "grip wrap, straps, bindings"),
    "metal": Role("#b8913f", "brass", "bands, spikes, pommel"),
}
BLUNT_PARAMS = {
    "variant": Param("enum", "warhammer", choices=("warhammer", "sledge", "mace", "club", "maul"),
                     doc="war hammer | sledgehammer | flanged/spiked mace | wooden club | two-handed maul"),
    "length": Param("num", 1.0, 0.6, 1.6),
    "head_size": Param("num", 1.0, 0.7, 1.6),
    "bindings": Param("bool", False, doc="leather straps lashing the head on"),
    "bands": Param("bool", True, doc="metal bands on the head"),
    "spike": Param("bool", False, doc="spike on top / back"),
}
_BLUNT = {"warhammer": (0.75, 1.0), "sledge": (0.85, 1.1), "mace": (0.62, 0.9), "club": (0.7, 1.0),
          "maul": (1.1, 1.35)}


def build_blunt(P, R, style):
    v = P["variant"]
    if v == "club":
        R = _alt(R, BLUNT_ROLES, "head", "wood", "#8a5a32")
    k = Kit(v.replace("warhammer", "war hammer"), "weapon", style, R)
    c = k.chunk
    L0, hs0 = _BLUNT[v]
    L = L0 * P["length"]
    hs = min(hs0 * P["head_size"] * (1.2 if k.sty or k.rbx else 1.0), L / 0.34)  # head never longer than the haft
    hr = 0.017 * c * (1.2 if v in ("maul", "sledge") else 1.0)
    k.cyl("handle", "handle", (L / 2, 0, 0), hr, L, "x")
    k.cyl("grip", "grip", (0.1 * L, 0, 0), hr * 1.12, 0.22 * L, "x")
    k.ball("pommel", "metal", (-0.01, 0, 0), hr * 1.5)
    hx = L - 0.05 * hs
    if v in ("warhammer", "sledge", "maul"):
        hl, hw = (0.2 * hs, 0.085 * hs) if v != "maul" else (0.26 * hs, 0.12 * hs)
        if v == "warhammer":
            hl, hw = 0.22 * hs, 0.1 * hs
        k.box("head", "head", (hx, 0, 0), (hw, hw * 0.95, hl), bevel=k.bev(3 if not k.sty else 2))
        if P["bands"] and not k.low:
            for sz in (1, -1):
                k.box(f"band{'u' if sz > 0 else 'd'}", "metal", (hx, 0, sz * hl * 0.32), (hw * 1.06, hw * 1.01, hl * 0.08))
        k.box("face_u", "head", (hx, 0, hl / 2 + 0.008 * hs), (hw * 1.1, hw * 1.05, 0.02 * hs), bevel=k.bev(2))
        if v == "warhammer" and P["spike"]:
            k.cone("back_spike", "metal", (hx, 0, -hl / 2 - 0.05 * hs), hw * 0.4, 0.0, 0.1 * hs, rot=[180, 0, 0])
        else:
            k.box("face_d", "head", (hx, 0, -hl / 2 - 0.008 * hs), (hw * 1.1, hw * 1.05, 0.02 * hs), bevel=k.bev(2))
        if P["bindings"] or (v == "warhammer" and k.sty):
            for i, dz in enumerate((-hl * 0.18, hl * 0.18)):
                k.box(f"strap{i}", "grip", (hx, 0, dz), (hw * 1.12, hw * 1.08, 0.03 * hs), bevel=k.bev(1))
            k.ring("collar_wrap", "grip", (hx - hw * 0.62, 0, 0), hr * 1.25, 0.008 * c, "x", count=3,
                   step=[-0.02, 0, 0])
    elif v == "mace":
        k.ball("head", "head", (hx, 0, 0), 0.055 * hs)
        n = 6 if not k.low else 4
        for i in range(n):
            a = 360.0 * i / n
            ra = math.radians(a)
            k.box(f"flange{i}", "metal", (hx, 0.045 * hs * math.cos(ra), 0.045 * hs * math.sin(ra)),
                  (0.1 * hs, 0.012 * c, 0.04 * hs), rot=[a, 0, 0], taper=[0.6, 1.0])
        k.cone("tip", "metal", (hx + 0.07 * hs, 0, 0), 0.02 * hs, 0.0, 0.05 * hs, "x")
    else:  # club: a thickening wooden head with studs
        k.cone("head", "head", (L * 0.78, 0, 0), hr * 1.2, 0.05 * hs, L * 0.45, "x")
        k.ball("head_end", "head", (L * 1.0, 0, 0), 0.05 * hs)
        if k.small:
            for i in range(6):
                a = math.radians(60 * i)
                k.cone(f"stud{i}", "metal", (L * 0.88, 0.042 * hs * math.cos(a), 0.042 * hs * math.sin(a)), 0.008 * hs,
                       0.0, 0.03 * hs, "z", rot=[-math.degrees(a) + 90, 0, 0])
    if P["spike"] and v != "warhammer":
        k.cone("top_spike", "metal", (L + 0.04 * hs, 0, 0), hr * 1.0, 0.0, 0.08 * hs, "x")
    return k.spec()


# ------------------------------------------------------------------ two-wheeler (front at +X)
BIKE_ROLES = {
    "body": Role("#b8282a", "painted_metal", "tank and fairings"),
    "frame": Role("#2a2b2e", "gunmetal", "frame, fork, engine"),
    "chrome": Role("#d8dade", "chrome", "exhaust, rims, mirrors"),
    "seat": Role("#1e1c1a", "leather", "seat, grips"),
    "tire": Role("#161616", "rubber", "tires"),
    "light": Role("#ffe7b0", "emissive", "headlight, thruster glow"),
}
BIKE_PARAMS = {
    "variant": Param("enum", "cruiser", choices=("cruiser", "sport", "dirt", "scooter", "hover"),
                     doc="cruiser motorcycle | sport bike | dirt bike | scooter | sci-fi hover bike"),
    "size": Param("num", 1.0, 0.8, 1.2),
    "spokes": Param("bool", True, doc="spoked wheels (else solid discs)"),
    "windscreen": Param("bool", False),
    "saddlebags": Param("bool", False),
    "thrusters": Param("int", 2, 1, 4, doc="hover bike side thrusters"),
}


def _bike_wheel(k, pid, x, r, w, spokes):
    k.ring(pid, "tire", (x, 0, r), r - w * 0.5, w * 0.5, "y", bevel=None)
    k.ring(pid + "_rim", "chrome", (x, 0, r), r - w * 0.95, w * 0.14, "y")
    k.cyl(pid + "_hub", "frame", (x, 0, r), r * 0.14, w * 1.1, "y")
    if spokes and not k.low:
        n = 12 if k.fine else 8
        for i in range(n):
            a = 180.0 * i / n
            k.box(f"{pid}_spoke{i}", "chrome", (x, 0, r), (0.006 * k.chunk, 0.006 * k.chunk, 2 * (r - w * 0.95)),
                  rot=[0, a, 0])
    elif not spokes:
        k.cyl(pid + "_disc", "chrome", (x, 0, r), r - w * 0.95, w * 0.3, "y")


def build_bike(P, R, style):
    v = P["variant"]
    k = Kit({"hover": "hover bike", "scooter": "scooter"}.get(v, f"{v} motorcycle"), "vehicle", style, R)
    c = k.chunk
    if v == "hover":
        zl = 0.55
        k.ball("hull", "body", (0.0, 0, zl + 0.2), 0.9, scale=[1.0, 0.28, 0.2])
        k.ball("nose", "body", (0.75, 0, zl + 0.16), 0.35, scale=[1.0, 0.5, 0.35])
        k.box("seat", "seat", (-0.25, 0, zl + 0.38), (0.6, 0.3, 0.1), bevel=k.bev(6))
        k.box("console", "frame", (0.32, 0, zl + 0.4), (0.25, 0.22, 0.14), rot=[0, -20, 0], bevel=k.bev(3))
        k.cyl("bars", "frame", (0.28, 0, zl + 0.52), 0.018 * c, 0.6, "y")
        k.ball("headlight", "light", (1.06, 0, zl + 0.17), 0.07)
        n = P["thrusters"]
        for i in range(max(1, n // 2) if n > 1 else 1):
            x = -0.2 - 0.45 * i
            yy = 0.38 if n > 1 else 0.0
            k.cyl(f"thruster{i}", "frame", (x, yy, zl), 0.13 * c, 0.5, "x", mirror_y=n > 1)
            k.cyl(f"thruster_glow{i}", "light", (x - 0.26, yy, zl), 0.1 * c, 0.03, "x", mirror_y=n > 1)
            k.box(f"pylon{i}", "frame", (x, yy * 0.6, zl + 0.08), (0.2, yy * 0.8 if n > 1 else 0.1, 0.06),
                  mirror_y=False)
        k.box("fin", "body", (-0.75, 0, zl + 0.38), (0.3, 0.03, 0.25), taper=[0.4, 1.0])
        return k.spec(P["size"])
    r = {"cruiser": 0.33, "sport": 0.31, "dirt": 0.36, "scooter": 0.2}[v]
    w = {"cruiser": 0.13, "sport": 0.17, "dirt": 0.1, "scooter": 0.1}[v]
    wb = {"cruiser": 1.6, "sport": 1.4, "dirt": 1.45, "scooter": 1.25}[v]
    xf, xr = wb / 2, -wb / 2
    _bike_wheel(k, "wheel_f", xf, r, w, P["spokes"] and v != "scooter")
    _bike_wheel(k, "wheel_r", xr, r, w * (1.2 if v == "cruiser" else 1.0), P["spokes"] and v != "scooter")
    if v == "scooter":
        k.box("floor", "body", (-0.05, 0, 0.3), (0.7, 0.32, 0.08), bevel=k.bev(4))
        k.ball("rear_body", "body", (-0.42, 0, 0.5), 0.36, scale=[1.0, 0.55, 0.62])
        k.box("leg_shield", "body", (0.38, 0, 0.6), (0.12, 0.38, 0.62), rot=[0, -18, 0], bevel=k.bev(8))
        k.box("seat", "seat", (-0.38, 0, 0.75), (0.55, 0.28, 0.1), bevel=k.bev(6))
        _limb(k, "steer", "frame", (xf, 0, r), (0.48, 0, 1.0), 0.03, 0.03)
        k.cyl("bars", "chrome", (0.48, 0, 1.0), 0.016, 0.62, "y")
        k.ball("headlight", "light", (0.52, 0, 0.96), 0.06)
        return k.spec(P["size"])
    zt = r + {"cruiser": 0.42, "sport": 0.5, "dirt": 0.55}[v]
    # fork + frame tubes
    head = (xf - 0.28, 0, zt + 0.12)
    for sy in (1, -1):
        _limb(k, f"fork{'l' if sy > 0 else 'r'}", "chrome" if v == "cruiser" else "frame", (xf, sy * w * 0.75, r),
              (head[0], sy * w * 0.75, head[2]), 0.022 * c, 0.022 * c)
    k.tube("frame_top", "frame", [head, (xr + 0.55, 0, zt - 0.02)], 0.028 * c)
    k.tube("frame_down", "frame", [head, (0.05, 0, r * 0.75), (xr + 0.25, 0, r * 0.9)], 0.026 * c)
    _limb(k, "swingarm", "frame", (xr + 0.35, w * 0.55, r * 1.0), (xr, w * 0.55, r), 0.02 * c, 0.02 * c, mirror_y=True)
    # tank, seat, engine
    tank_x = (head[0] + xr + 0.55) / 2 + 0.12
    k.ball("tank", "body", (tank_x, 0, zt + 0.06), 0.27 if v != "dirt" else 0.22, scale=[1.0, 0.55, 0.5],
           rot=[0, 8 if v == "cruiser" else -4, 0])
    seat_x = xr + (0.5 if v != "sport" else 0.45)
    k.box("seat", "seat", (seat_x, 0, zt + (0.0 if v == "cruiser" else 0.05)), (0.5 if v != "dirt" else 0.6, 0.26, 0.09),
          bevel=k.bev(8), rot=[0, -4 if v == "sport" else 0, 0])
    k.box("engine", "frame", (0.02, 0, r + 0.12), (0.36, 0.28, 0.3), bevel=k.bev(4))
    if v == "cruiser":
        for i, zz in enumerate((0.1, 0.24)):
            k.cyl(f"cylinder{i}", "chrome", (0.02 + 0.08 * (i - 0.5), 0, r + 0.27 + zz * 0.3), 0.07, 0.16, "z",
                  rot=[0, 30 - 60 * i, 0])
    if not k.low:
        k.cyl("crankcase", "chrome", (0.02, 0.15, r + 0.08), 0.1, 0.03, "y", mirror_y=True)
    # exhaust
    ex = [(0.12, -0.16, r + 0.2), (0.05, -0.18, r - 0.05), (-0.3, -0.2, r - 0.06), (xr + 0.05, -0.2, r + 0.02)]
    if v == "dirt":
        ex = [(0.12, -0.16, r + 0.2), (-0.1, -0.18, zt), (xr + 0.15, -0.17, zt + 0.05)]
    k.tube("exhaust", "chrome", ex, 0.032 * c)
    k.cyl("muffler", "chrome", (ex[-1][0] + 0.02, -0.2, ex[-1][2] + 0.01), 0.05 * c, 0.32, "x")
    # bars, lights, fenders
    k.cyl("riser", "frame", (head[0] - 0.025, 0, head[2] + 0.06), 0.022 * c, 0.14)
    k.cyl("bars", "chrome" if v == "cruiser" else "frame", (head[0] - 0.05, 0, head[2] + 0.12), 0.016 * c,
          0.78 if v != "sport" else 0.6, "y")
    k.cyl("grip", "seat", (head[0] - 0.05, 0.33 if v != "sport" else 0.26, head[2] + 0.12), 0.022 * c, 0.12, "y",
          mirror_y=True)
    k.cyl("headlight", "chrome", (head[0] + 0.12, 0, head[2] - 0.05), 0.09 * c, 0.1, "x")
    k.cyl("headlight_lens", "light", (head[0] + 0.175, 0, head[2] - 0.05), 0.075 * c, 0.012, "x")
    k.cyl("taillight", "light", (xr + 0.2, 0, zt + 0.02), 0.03, 0.03, "x", mat="emissive", color="#ff3a2a")
    fender = [(xf - r * 0.6, 0, r + r * 0.85), (xf, 0, r * 2.15), (xf + r * 0.7, 0, r + r * 0.75)]
    k.tube("fender_f", "body", fender, w * 0.5)
    k.tube("fender_r", "body", [(xr - r * 0.75, 0, r + r * 0.7), (xr - r * 0.1, 0, r * 2.1),
                                (xr + r * 0.6, 0, r + r * 0.9)], w * 0.55)
    if v == "sport" or P["windscreen"]:
        k.ball("fairing", "body", (head[0] + 0.08, 0, head[2] - 0.02), 0.22, scale=[1.0, 0.75, 0.9])
        k.box("windscreen", "light", (head[0] + 0.02, 0, head[2] + 0.2), (0.02, 0.24, 0.2), rot=[0, -30, 0],
              mat="glass", color="#3a4a55")
    if P["saddlebags"]:
        k.box("saddlebag", "seat", (xr + 0.25, 0.2, zt - 0.12), (0.38, 0.14, 0.26), bevel=k.bev(8), mirror_y=True)
    return k.spec(P["size"])


# ------------------------------------------------------------------ lantern / lamp
LAMP_ROLES = {
    "metal": Role("#b8913f", "brass", "body, cap, frame"),
    "glass": Role("#f2dca8", "glass", "globe / panes (warm when lit)"),
    "flame": Role("#ffb347", "emissive", "flame / bulb glow"),
    "accent": Role("#2a2b2e", "gunmetal", "handle, wire, base ring"),
}
LAMP_PARAMS = {
    "variant": Param("enum", "oil", choices=("oil", "square", "candle", "street"),
                     doc="hurricane oil lantern | square cage lantern | candle holder | street lamp"),
    "size": Param("num", 1.0, 0.6, 1.6),
    "handle": Param("bool", True),
    "glow": Param("bool", True, doc="lit flame"),
}


def build_lantern(P, R, style):
    v = P["variant"]
    k = Kit(f"{v} lantern" if v != "street" else "street lamp", "prop", style, R)
    c = k.chunk
    if v == "oil":
        k.lathe("fount", "metal", (0, 0, 0), [[0, 0.0], [0, 0.07], [0.015, 0.078], [0.05, 0.074], [0.06, 0.05],
                                              [0.064, 0.0]], axis="z")
        k.ring("globe_seat", "metal", (0, 0, 0.066), 0.05, 0.006 * c, "z")
        k.ball("globe", "glass", (0, 0, 0.13), 0.06, scale=[1.0, 1.0, 1.25])
        if P["glow"]:
            k.cone("flame", "flame", (0, 0, 0.12), 0.012, 0.0, 0.04)
        k.cone("chimney_cap", "metal", (0, 0, 0.215), 0.055, 0.03, 0.04)
        k.cyl("cap_top", "metal", (0, 0, 0.245), 0.032, 0.02)
        if k.small:
            for i in range(4):
                a = math.radians(90 * i + 45)
                k.tube(f"guard{i}", "accent", [(0.05 * math.cos(a), 0.05 * math.sin(a), 0.07),
                                               (0.072 * math.cos(a), 0.072 * math.sin(a), 0.13),
                                               (0.05 * math.cos(a), 0.05 * math.sin(a), 0.2)], 0.003 * c)
            k.cyl("wick_knob", "metal", (0.052, 0, 0.055), 0.008, 0.02, "x")
        if P["handle"]:
            k.tube("handle", "accent", [(0, 0.055, 0.2)] + [(0, 0.055 * math.cos(math.radians(a)),
                                                               0.25 + 0.055 * math.sin(math.radians(a)))
                                                            for a in range(0, 181, 30)] + [(0, -0.055, 0.2)], 0.003 * c)
        return k.spec(P["size"] * 1.4)
    if v == "square":
        s = 0.12
        k.box("base", "metal", (0, 0, 0.015), (s + 0.02, s + 0.02, 0.03), bevel=k.bev(2))
        k.box("panes", "glass", (0, 0, 0.11), (s - 0.006, s - 0.006, 0.16))
        for sx in (1, -1):
            for sy in (1, -1):
                k.box(f"post{'l' if sx > 0 else 'r'}{'b' if sy > 0 else 'f'}", "metal", (sx * s / 2, sy * s / 2, 0.11),
                      (0.012, 0.012, 0.17))
        k.box("roof", "metal", (0, 0, 0.225), (s + 0.03, s + 0.03, 0.06), taper=[0.3, 0.3])
        k.cyl("roof_top", "metal", (0, 0, 0.265), 0.012, 0.03)
        if P["glow"]:
            k.cyl("candle", "glass", (0, 0, 0.07), 0.016, 0.07, mat="ceramic", color="#efe6d0")
            k.cone("flame", "flame", (0, 0, 0.125), 0.01, 0.0, 0.03)
        if P["handle"]:
            k.ring("ring", "accent", (0, 0, 0.3), 0.025, 0.004 * c, "y")
        return k.spec(P["size"] * 1.4)
    if v == "candle":
        k.cyl("dish", "metal", (0, 0, 0.008), 0.07, 0.016)
        k.cyl("stem", "metal", (0, 0, 0.03), 0.018, 0.04)
        k.cyl("candle", "glass", (0, 0, 0.09), 0.02, 0.1, mat="ceramic", color="#efe6d0")
        if P["glow"]:
            k.cone("flame", "flame", (0, 0, 0.155), 0.01, 0.0, 0.03)
        if P["handle"]:
            k.ring("finger_ring", "metal", (0.075, 0, 0.02), 0.022, 0.005 * c, "y")
        return k.spec(P["size"] * 1.5)
    H = 2.0  # garden / park lamp post (the prop size range tops out at 2.5 m)
    k.cyl("base", "accent", (0, 0, 0.15), 0.18, 0.3, bevel=k.bev(3))
    k.cyl("pole", "accent", (0, 0, H / 2), 0.05, H)
    k.box("head_roof", "accent", (0, 0, H + 0.32), (0.4, 0.4, 0.14), taper=[0.3, 0.3])
    k.box("head_glass", "glass", (0, 0, H + 0.12), (0.3, 0.3, 0.3))
    for sx in (1, -1):
        for sy in (1, -1):
            k.box(f"head_post{'l' if sx > 0 else 'r'}{'b' if sy > 0 else 'f'}", "accent", (sx * 0.15, sy * 0.15, H + 0.12),
                  (0.025, 0.025, 0.32))
    k.box("head_base", "accent", (0, 0, H - 0.04), (0.34, 0.34, 0.05))
    if P["glow"]:
        k.ball("bulb", "flame", (0, 0, H + 0.1), 0.07)
    return k.spec(min(P["size"], 0.95))


TEMPLATE_DEFS = (
    ("humanoid", "person / character figure: villager, adventurer, armoured knight, soldier, wizard, robot", "character",
     HUMAN_PARAMS, HUMAN_ROLES, build_humanoid,
     ("character", "person", "man", "woman", "knight", "villager", "soldier", "wizard", "robot", "figure", "hero",
      "adventurer", "npc", "warrior")),
    ("creature", "four-legged animal: fox, wolf, dog, cat, deer, horse, cow, bear, lion", "creature",
     BEAST_PARAMS, BEAST_ROLES, build_creature,
     ("fox", "wolf", "dog", "cat", "deer", "horse", "cow", "bear", "lion", "animal", "creature", "pony", "stag")),
    ("building", "building: cottage, two-storey house, stone tower, watchtower on legs, shop, barn", "building",
     BUILD_PARAMS, BUILD_ROLES, build_building,
     ("house", "cottage", "hut", "tower", "watchtower", "shop", "barn", "building", "cabin", "home")),
    ("shelf", "bookshelf / bookcase with books on shelves", "furniture", SHELF_PARAMS, SHELF_ROLES, build_shelf,
     ("bookshelf", "bookcase", "shelf", "shelves", "library")),
    ("blunt", "blunt weapon: war hammer, sledgehammer, mace, club, two-handed maul", "weapon", BLUNT_PARAMS,
     BLUNT_ROLES, build_blunt, ("hammer", "mace", "club", "maul", "sledge", "warhammer", "morningstar")),
    ("bike", "two-wheeler: cruiser motorcycle, sport bike, dirt bike, scooter, sci-fi hover bike", "vehicle",
     BIKE_PARAMS, BIKE_ROLES, build_bike,
     ("motorcycle", "motorbike", "bike", "scooter", "hoverbike", "hover", "chopper", "moped", "dirtbike")),
    ("lantern", "lantern or lamp: oil hurricane lantern, square cage lantern, candle holder, street lamp", "prop",
     LAMP_PARAMS, LAMP_ROLES, build_lantern, ("lantern", "lamp", "candle", "light", "streetlight", "torch")),
)
__all__ = ["TEMPLATE_DEFS", "_r"]
