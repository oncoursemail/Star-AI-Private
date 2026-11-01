"""Headless preview renderer for Blockbench cube models (Pillow only, no GPU, no numpy).

Reads any .bbmodel dict (cubes, groups/bones, per-face or box UV, embedded PNG textures) and draws each
visible texel as its own polygon with nearest-neighbour colours and Minecraft-style directional face
shading, sorted back to front. Crisp pixels, like the game; used for the critique loop and contact sheets.
"""
from __future__ import annotations

import base64
import io
import math

from PIL import Image, ImageDraw

BG = (184, 191, 199, 255)
VIEWS = {  # name: (yaw degrees, pitch degrees); yaw 0 looks at the north (front) face
    "front_left": (-35.0, 24.0),
    "front_right": (35.0, 24.0),
    "back_right": (145.0, 22.0),
    "side": (90.0, 6.0),
    "front": (0.0, 4.0),
    "top": (-20.0, 62.0),
}
DEFAULT_VIEWS = ("front_left", "front_right", "back_right", "side")


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _rot(p, rot, origin):
    """Rotate p around origin by Euler degrees [x, y, z] applied X, then Y, then Z (Blockbench 'ZYX')."""
    if not rot or not any(rot):
        return p
    x, y, z = _sub(p, origin)
    rx, ry, rz = (math.radians(float(a or 0)) for a in rot)
    if rx:
        c, s = math.cos(rx), math.sin(rx)
        y, z = y * c - z * s, y * s + z * c
    if ry:
        c, s = math.cos(ry), math.sin(ry)
        x, z = x * c + z * s, -x * s + z * c
    if rz:
        c, s = math.cos(rz), math.sin(rz)
        x, y = x * c - y * s, x * s + y * c
    return (x + origin[0], y + origin[1], z + origin[2])


def load_textures(bb: dict) -> list:
    res = bb.get("resolution") or {}
    out = []
    for t in bb.get("textures") or []:
        img = None
        src = t.get("source") or ""
        if isinstance(src, str) and src.startswith("data:image/png;base64,"):
            try:
                img = Image.open(io.BytesIO(base64.b64decode(src.split(",", 1)[1]))).convert("RGBA")
            except Exception:  # noqa: BLE001 - a broken texture renders as missing (magenta)
                img = None
        uw = t.get("uv_width") or res.get("width") or (img.width if img else 16)
        uh = t.get("uv_height") or res.get("height") or (img.height if img else 16)
        out.append({"img": img, "uv_w": float(uw), "uv_h": float(uh), "uuid": t.get("uuid"), "id": t.get("id")})
    return out


def box_uv_faces(el: dict) -> dict:
    """Per-face UV rects for a Blockbench box-UV cube (uv_offset)."""
    u, v = (el.get("uv_offset") or [0, 0])[:2]
    sx, sy, sz = (math.floor(abs(el["to"][j] - el["from"][j]) + 1e-6) for j in range(3))
    f = {"north": [u + sz, v + sz, u + sz + sx, v + sz + sy],
         "east": [u, v + sz, u + sz, v + sz + sy],
         "south": [u + 2 * sz + sx, v + sz, u + 2 * sz + 2 * sx, v + sz + sy],
         "west": [u + sz + sx, v + sz, u + 2 * sz + sx, v + sz + sy],
         "up": [u + sz + sx, v + sz, u + sz, v],
         "down": [u + sz + 2 * sx, v, u + sz + sx, v + sz]}
    if el.get("mirror_uv"):
        f["east"], f["west"] = f["west"], f["east"]
        for k in f:
            a = f[k]
            f[k] = [a[2], a[1], a[0], a[3]]
    return f


def face_corners(a, b, face):
    """Corners TL, TR, BR, BL of a face as seen from outside (Minecraft/Blockbench UV orientation)."""
    x0, y0, z0 = a
    x1, y1, z1 = b
    return {
        "north": [(x1, y1, z0), (x0, y1, z0), (x0, y0, z0), (x1, y0, z0)],
        "south": [(x0, y1, z1), (x1, y1, z1), (x1, y0, z1), (x0, y0, z1)],
        "east": [(x1, y1, z1), (x1, y1, z0), (x1, y0, z0), (x1, y0, z1)],
        "west": [(x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (x0, y0, z0)],
        "up": [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
        "down": [(x0, y0, z1), (x1, y0, z1), (x1, y0, z0), (x0, y0, z0)],
    }[face]


def _groups(bb):
    by_uuid = {g.get("uuid"): g for g in bb.get("groups") or [] if isinstance(g, dict)}
    parents = {}  # element uuid -> list of group dicts, outermost first

    def walk(nodes, chain):
        for n in nodes or []:
            if isinstance(n, str):
                parents[n] = chain
            elif isinstance(n, dict):
                g = dict(by_uuid.get(n.get("uuid"), {}))
                for k in ("name", "origin", "rotation"):
                    if k not in g and k in n:
                        g[k] = n[k]
                g["uuid"] = n.get("uuid")
                walk(n.get("children"), chain + [g])
    walk(bb.get("outliner"), [])
    return parents


def _anim_pose(bb, anim_name, t):
    """{group uuid: {"rotation": [..], "position": [..]}} for one animation at time t (linear)."""
    if not anim_name:
        return {}
    anim = next((a for a in bb.get("animations") or [] if a.get("name") == anim_name
                 or str(a.get("name", "")).endswith("." + anim_name)), None)
    if not anim:
        return {}
    pose = {}
    for gid, animator in (anim.get("animators") or {}).items():
        chans = {}
        for kf in animator.get("keyframes") or []:
            try:
                dp = kf["data_points"][0]
                v = [float(dp.get(k, 0) or 0) for k in ("x", "y", "z")]
                chans.setdefault(kf["channel"], []).append((float(kf["time"]), v))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        res = {}
        for ch, keys in chans.items():
            keys.sort()
            if t <= keys[0][0]:
                res[ch] = keys[0][1]
            elif t >= keys[-1][0]:
                res[ch] = keys[-1][1]
            else:
                for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
                    if t0 <= t <= t1:
                        w = (t - t0) / (t1 - t0) if t1 > t0 else 0
                        res[ch] = [v0[i] + (v1[i] - v0[i]) * w for i in range(3)]
                        break
        pose[gid] = res
    return pose


def scene_quads(bb: dict, *, anim: str | None = None, time: float = 0.0):
    """World-space textured quads: dicts with corners, normal, tex index, uv rect, rotation, element."""
    parents = _groups(bb)
    pose = _anim_pose(bb, anim, time)
    quads = []
    for el in bb.get("elements") or []:
        if not isinstance(el, dict) or el.get("type", "cube") != "cube" or el.get("visibility") is False:
            continue
        try:
            a = [float(v) for v in el["from"]]
            b = [float(v) for v in el["to"]]
        except (KeyError, TypeError, ValueError):
            continue
        inf = float(el.get("inflate") or 0)
        a = [min(a[j], b[j]) - inf for j in range(3)]
        b = [max(el["from"][j], el["to"][j]) + inf for j in range(3)]
        faces = box_uv_faces(el) if el.get("box_uv") else None
        chain = parents.get(el.get("uuid"), [])

        def xf(p, el=el, chain=chain):
            p = _rot(p, el.get("rotation"), el.get("origin") or [0, 0, 0])
            for g in reversed(chain):
                o = g.get("origin") or [0, 0, 0]
                pr = pose.get(g.get("uuid"), {})
                r = [float((g.get("rotation") or [0, 0, 0])[i]) + float((pr.get("rotation") or [0, 0, 0])[i])
                     for i in range(3)]
                p = _rot(p, r, o)
                if pr.get("position"):
                    p = (p[0] + pr["position"][0], p[1] + pr["position"][1], p[2] + pr["position"][2])
            return p

        for face, fd in (el.get("faces") or {}).items():
            if not isinstance(fd, dict) or fd.get("texture") is None or face not in (
                    "north", "east", "south", "west", "up", "down"):
                continue
            uv = faces[face] if faces else fd.get("uv")
            if not uv or len(uv) != 4:
                continue
            cs = [xf(p) for p in face_corners(a, b, face)]
            n = _norm(_cross(_sub(cs[3], cs[0]), _sub(cs[1], cs[0])))
            if _dot(n, n) < 0.5:
                continue
            quads.append({"corners": cs, "normal": n, "tex": fd.get("texture"), "uv": [float(x) for x in uv],
                          "uv_rot": int(fd.get("rotation") or 0), "element": el.get("name", ""), "face": face})
    return quads


def _tex_index(textures, ref):
    if isinstance(ref, int) and 0 <= ref < len(textures):
        return ref
    for i, t in enumerate(textures):
        if ref in (t["uuid"], t["id"]) or str(ref) == str(t["id"]):
            return i
    return 0 if textures else None


def _shade(n):
    nx, ny, nz = n
    return min(1.0, nx * nx * 0.6 + nz * nz * 0.8 + ny * ny * (1.0 if ny > 0 else 0.5))


def render(bb: dict, view: str | tuple = "front_left", *, size: int = 512, anim: str | None = None,
           time: float = 0.0, bg=BG, frame=None) -> Image.Image:
    """Render one view to an RGBA image. `frame` (lo, hi) fixes the camera framing across poses."""
    yaw, pitch = VIEWS[view] if isinstance(view, str) else view
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cam = (sy * cp, sp, -cy * cp)
    fwd = (-cam[0], -cam[1], -cam[2])
    right = _norm(_cross(fwd, (0.0, 1.0, 0.0)))
    up = _cross(right, fwd)
    textures = load_textures(bb)
    quads = scene_quads(bb, anim=anim, time=time)
    ss = 2
    W = size * ss
    img = Image.new("RGBA", (W, W), bg)
    if not quads:
        return img.resize((size, size), Image.LANCZOS)
    pts = [c for q in quads for c in q["corners"]]
    if frame is None:
        xs = [_dot(p, right) for p in pts]
        ys = [_dot(p, up) for p in pts]
        frame = (min(xs), min(ys), max(xs), max(ys))
    x0, y0, x1, y1 = frame
    span = max(x1 - x0, y1 - y0, 1e-3)
    scale = W * 0.84 / span
    ox = W / 2 - (x0 + x1) / 2 * scale
    oy = W / 2 + (y0 + y1) / 2 * scale

    def proj(p):
        return (ox + _dot(p, right) * scale, oy - _dot(p, up) * scale)

    polys = []
    for q in quads:
        if _dot(q["normal"], cam) <= 1e-6:
            continue
        ti = _tex_index(textures, q["tex"])
        tex = textures[ti] if ti is not None else None
        img_t = tex["img"] if tex else None
        u1, v1, u2, v2 = q["uv"]
        if tex:
            kx, ky = (img_t.width / tex["uv_w"], img_t.height / tex["uv_h"]) if img_t else (1, 1)
            u1, u2, v1, v2 = u1 * kx, u2 * kx, v1 * ky, v2 * ky
        nu = max(1, round(abs(u2 - u1)))
        nv = max(1, round(abs(v2 - v1)))
        if nu * nv > 4096:
            nu, nv = min(nu, 64), min(nv, 64)
        shade = _shade(q["normal"])
        tl, tr, br, bl = q["corners"]
        rot = (q["uv_rot"] // 90) % 4
        for j in range(nv):
            for i in range(nu):
                si, sj = (i + 0.5) / nu, (j + 0.5) / nv
                for _ in range(rot):
                    si, sj = sj, 1 - si
                px = int(math.floor(u1 + (u2 - u1) * si))
                py = int(math.floor(v1 + (v2 - v1) * sj))
                if img_t is None:
                    col = (255, 0, 255, 255)
                else:
                    px = min(max(px, 0), img_t.width - 1)
                    py = min(max(py, 0), img_t.height - 1)
                    col = img_t.getpixel((px, py))
                if col[3] < 128:
                    continue
                s0, s1, t0, t1 = i / nu, (i + 1) / nu, j / nv, (j + 1) / nv

                def at(s, t):
                    top = (tl[0] + (tr[0] - tl[0]) * s, tl[1] + (tr[1] - tl[1]) * s, tl[2] + (tr[2] - tl[2]) * s)
                    bot = (bl[0] + (br[0] - bl[0]) * s, bl[1] + (br[1] - bl[1]) * s, bl[2] + (br[2] - bl[2]) * s)
                    return (top[0] + (bot[0] - top[0]) * t, top[1] + (bot[1] - top[1]) * t,
                            top[2] + (bot[2] - top[2]) * t)
                cs = [at(s0, t0), at(s1, t0), at(s1, t1), at(s0, t1)]
                depth = _dot(at((s0 + s1) / 2, (t0 + t1) / 2), cam)
                c = (round(col[0] * shade), round(col[1] * shade), round(col[2] * shade), 255)
                polys.append((depth, [proj(p) for p in cs], c))
    polys.sort(key=lambda t: t[0])
    draw = ImageDraw.Draw(img)
    for _, xy, c in polys:
        draw.polygon(xy, fill=c, outline=c)
    return img.resize((size, size), Image.LANCZOS)


def sheet(images, labels=None, *, cols=2, pad=6, title=None, bg=(40, 42, 48, 255)) -> Image.Image:
    from PIL import ImageFont
    font = ImageFont.load_default()
    w, h = images[0].size
    rows = (len(images) + cols - 1) // cols
    top = 22 if title else 0
    out = Image.new("RGBA", (cols * w + (cols + 1) * pad, rows * (h + 16) + (rows + 1) * pad + top), bg)
    d = ImageDraw.Draw(out)
    if title:
        d.text((pad, 5), title[:120], fill=(235, 235, 235, 255), font=font)
    for i, im in enumerate(images):
        x = pad + (i % cols) * (w + pad)
        y = top + pad + (i // cols) * (h + 16 + pad)
        out.paste(im, (x, y + 16))
        if labels:
            d.text((x + 2, y + 2), str(labels[i])[:60], fill=(220, 220, 220, 255), font=font)
    return out


def previews(bb: dict, views=DEFAULT_VIEWS, *, size=384) -> dict:
    return {v: render(bb, v, size=size) for v in views}


def animation_strip(bb: dict, anim: str, *, frames=4, size=256, view="front_left") -> Image.Image | None:
    a = next((x for x in bb.get("animations") or [] if x.get("name") == anim
              or str(x.get("name", "")).endswith("." + anim)), None)
    if not a:
        return None
    length = float(a.get("length") or 1)
    imgs = [render(bb, view, size=size, anim=a["name"], time=length * k / frames) for k in range(frames)]
    return sheet(imgs, [f"{a['name'].split('.')[-1]} t={length * k / frames:.2f}s" for k in range(frames)],
                 cols=frames)
