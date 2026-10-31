"""Deterministic quality checks for Blockbench cube models (any .bbmodel, not only STAR-built ones).

Measures the things that separate a clean hand-made Minecraft model from "AI slop": one texel density
everywhere, a small coherent palette, no blur/gradient near-duplicates, no partial alpha, no noise,
UVs inside the texture and not overlapping, no z-fighting or floating parts, Java/Bedrock limits.
Returns findings (severity, code, message) and a 0-100 score.
"""
from __future__ import annotations

import math
import statistics

from .palette import distance
from .render import _groups, box_uv_faces, load_textures

JAVA_ANGLES = (-45.0, -22.5, 0.0, 22.5, 45.0)
PENALTY = {"error": 15, "warning": 6, "info": 0}
FACE_AXES = {"north": (0, 1), "south": (0, 1), "east": (2, 1), "west": (2, 1), "up": (0, 2), "down": (0, 2)}
FACE_PLANE = {"north": (2, 0), "south": (2, 1), "east": (0, 1), "west": (0, 0), "up": (1, 1), "down": (1, 0)}


def _f(sev, code, msg, **extra):
    d = {"severity": sev, "code": code, "message": msg}
    d.update(extra)
    return d


def _cubes(bb):
    out = []
    for el in bb.get("elements") or []:
        if isinstance(el, dict) and el.get("type", "cube") == "cube":
            try:
                a = [float(v) for v in el["from"]]
                b = [float(v) for v in el["to"]]
                g = float(el.get("inflate") or 0)  # Blockbench draws inflated cubes bigger on every side
            except (KeyError, TypeError, ValueError):
                continue
            a, b = [min(a[j], b[j]) - g for j in range(3)], [max(a[j], b[j]) + g for j in range(3)]
            out.append((el, [min(a[j], b[j]) for j in range(3)], [max(a[j], b[j]) for j in range(3)]))
    return out


def _rotated(el, chain):
    if any(float(v or 0) for v in (el.get("rotation") or [0, 0, 0])):
        return True
    return any(any(float(v or 0) for v in (g.get("rotation") or [0, 0, 0])) for g in chain)


def _face_rects(el):
    if el.get("box_uv"):
        return box_uv_faces(el)
    return {k: v.get("uv") for k, v in (el.get("faces") or {}).items()
            if isinstance(v, dict) and v.get("texture") is not None and v.get("uv")}


def check(bb: dict) -> dict:
    findings = []
    fmt = (bb.get("meta") or {}).get("model_format", "free")
    cubes = _cubes(bb)
    textures = load_textures(bb)
    parents = _groups(bb)
    stats = {"format": fmt, "cubes": len(cubes)}
    if not cubes:
        findings.append(_f("error", "empty", "model has no cubes"))
        return {"score": 0, "findings": findings, "stats": stats}
    if not textures or textures[0]["img"] is None:
        findings.append(_f("error", "no-texture", "model has no embedded PNG texture"))
    tex = textures[0] if textures else None
    img = tex["img"] if tex else None

    # ---- UV bounds, overlap, texel density -------------------------------------------------------
    densities, used = [], {}
    overlap_pairs = set()
    for el, lo, hi in cubes:
        size = [hi[j] - lo[j] for j in range(3)]
        for face, uv in _face_rects(el).items():
            if face not in FACE_AXES or not uv or len(uv) != 4:
                continue
            if tex:
                if (min(uv[0], uv[2]) < -1e-6 or min(uv[1], uv[3]) < -1e-6
                        or max(uv[0], uv[2]) > tex["uv_w"] + 1e-6 or max(uv[1], uv[3]) > tex["uv_h"] + 1e-6):
                    findings.append(_f("error", "uv-out-of-bounds", f"{el.get('name')}.{face} UV outside the texture"))
                    continue
                kx = (img.width / tex["uv_w"]) if img else 1.0
                ky = (img.height / tex["uv_h"]) if img else 1.0
            else:
                kx = ky = 1.0
            au, av = FACE_AXES[face]
            fu, fv = size[au], size[av]
            tu, tv = abs(uv[2] - uv[0]) * kx, abs(uv[3] - uv[1]) * ky
            if fu >= 1 and fv >= 1 and tu > 0 and tv > 0:
                densities.append((tu / fu, el.get("name"), face))
                densities.append((tv / fv, el.get("name"), face))
            elif (fu >= 1 or fv >= 1) and (tu == 0 or tv == 0):
                findings.append(_f("warning", "zero-uv", f"{el.get('name')}.{face} has an empty UV on a visible face"))
            if img is not None and tu > 0 and tv > 0:
                x0, x1 = sorted((uv[0] * kx, uv[2] * kx))
                y0, y1 = sorted((uv[1] * ky, uv[3] * ky))
                key = (round(x0), round(y0), round(x1), round(y1))
                for k2, owner in used.items():
                    if (key[0] < k2[2] and k2[0] < key[2] and key[1] < k2[3] and k2[1] < key[3]
                            and owner != el.get("name") and key != k2):
                        overlap_pairs.add(tuple(sorted((str(owner), str(el.get("name"))))))
                used.setdefault(key, el.get("name"))
    if overlap_pairs:
        findings.append(_f("warning", "uv-overlap", f"{len(overlap_pairs)} part pairs share texture area "
                           f"(e.g. {sorted(overlap_pairs)[0]}); fine for deliberate mirrors, otherwise paint bleeds"))
    if densities:
        med = statistics.median(d for d, _, _ in densities)
        off = [(d, n, f) for d, n, f in densities if abs(d / med - 1) > 0.25]
        stats["texel_density"] = round(med, 3)
        stats["density_outliers"] = len(off)
        frac = len(off) / len(densities)
        if frac > 0.10:
            worst = max(off, key=lambda t: abs(math.log(t[0] / med)))
            findings.append(_f("warning" if frac < 0.3 else "error", "mixed-texel-density",
                               f"{frac:.0%} of faces differ >25% from the median texel density {med:g} "
                               f"(worst {worst[1]}.{worst[2]} at {worst[0]:.2f}); Minecraft models keep one density"))

    # ---- texture: palette, near-duplicates, partial alpha, noise -----------------------------------
    if img is not None:
        w, h = img.size
        stats["texture"] = [w, h]
        if w & (w - 1) or h & (h - 1):
            findings.append(_f("warning", "texture-not-pow2", f"texture {w}x{h} is not a power of two"))
        px = img.load()
        mask = [[False] * w for _ in range(h)]
        for el, lo, hi in cubes:
            for face, uv in _face_rects(el).items():
                if not uv or len(uv) != 4 or not tex:
                    continue
                kx, ky = w / tex["uv_w"], h / tex["uv_h"]
                x0, x1 = sorted((int(math.floor(uv[0] * kx)), int(math.ceil(uv[2] * kx))))
                y0, y1 = sorted((int(math.floor(uv[1] * ky)), int(math.ceil(uv[3] * ky))))
                for y in range(max(0, y0), min(h, y1)):
                    for x in range(max(0, x0), min(w, x1)):
                        mask[y][x] = True
        colours, partial, total, orphans = {}, 0, 0, 0
        for y in range(h):
            for x in range(w):
                if not mask[y][x]:
                    continue
                c = px[x, y]
                if c[3] == 0:
                    continue
                total += 1
                if c[3] < 255:
                    partial += 1
                colours[c[:3]] = colours.get(c[:3], 0) + 1
                nb = [px[xx, yy][:3] for xx, yy in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                      if 0 <= xx < w and 0 <= yy < h and mask[yy][xx] and px[xx, yy][3]]
                if len(nb) == 4 and all(distance(c, n) > 30 for n in nb):
                    orphans += 1
        n_col = len(colours)
        stats["palette"] = n_col
        cap = 48 if w * h <= 64 * 64 else 72
        if n_col > cap:
            findings.append(_f("error" if n_col > 2 * cap else "warning", "palette-too-large",
                               f"{n_col} colours; hand-made Minecraft textures use small ramps (<= {cap})"))
        cols = sorted(colours, key=lambda c: -colours[c])[:200]
        near = 0
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                if distance(cols[i], cols[j]) < 10:
                    near += 1
        stats["near_duplicate_pairs"] = near
        if near > max(3, n_col // 6):
            findings.append(_f("warning", "near-duplicate-colours",
                               f"{near} near-identical colour pairs: smooth gradients/blur, not pixel-art ramps"))
        if total:
            stats["partial_alpha"] = round(partial / total, 3)
            stats["orphan_ratio"] = round(orphans / total, 3)
            if partial / total > 0.02:
                findings.append(_f("warning", "partial-alpha",
                                   f"{partial / total:.0%} semi-transparent texels; Minecraft cutout textures are 0 or 255"))
            if orphans / total > 0.08:
                findings.append(_f("warning", "texture-noise",
                                   f"{orphans / total:.0%} isolated pixels: reads as noise, cluster the detail"))

    # ---- geometry: degenerate, z-fighting, floating, hidden ---------------------------------------
    zf, hidden = [], []
    axis_aligned = [(el, lo, hi) for el, lo, hi in cubes if not _rotated(el, parents.get(el.get("uuid"), []))]
    for el, lo, hi in cubes:
        zeros = sum(1 for j in range(3) if hi[j] - lo[j] <= 1e-6)
        if zeros >= 2:
            findings.append(_f("error", "degenerate-cube", f"{el.get('name')} has no area"))
    for i in range(len(axis_aligned)):
        ei, li, hi_ = axis_aligned[i]
        for j in range(i + 1, len(axis_aligned)):
            ej, lj, hj = axis_aligned[j]
            for face, (ax, side) in FACE_PLANE.items():
                pi = hi_[ax] if side else li[ax]
                pj = hj[ax] if side else lj[ax]
                if abs(pi - pj) > 1e-4:
                    continue
                o = [k for k in range(3) if k != ax]
                if all(min(hi_[k], hj[k]) - max(li[k], lj[k]) > 1e-4 for k in o):
                    if face in _face_rects(ei) and face in _face_rects(ej):
                        zf.append(f"{ei.get('name')}/{ej.get('name')}.{face}")
            if all(lj[k] - 1e-6 <= li[k] and hi_[k] <= hj[k] + 1e-6 for k in range(3)):
                hidden.append(ei.get("name"))
            elif all(li[k] - 1e-6 <= lj[k] and hj[k] <= hi_[k] + 1e-6 for k in range(3)):
                hidden.append(ej.get("name"))
    stats["z_fighting"] = len(zf)
    if zf:
        findings.append(_f("warning" if len(zf) < 4 else "error", "z-fighting",
                           f"{len(zf)} coplanar overlapping faces flicker in game: {', '.join(zf[:4])}"))
    if hidden:
        findings.append(_f("info", "hidden-cube", f"cubes fully inside another: {', '.join(sorted(set(hidden))[:5])}"))
    # connectivity on axis-aligned bounds (rotated parts use their unrotated box: conservative)
    n = len(cubes)
    adj = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            _, a0, a1 = cubes[i]
            _, b0, b1 = cubes[j]
            if all(min(a1[k], b1[k]) - max(a0[k], b0[k]) >= -0.05 for k in range(3)):
                adj[i].append(j)
                adj[j].append(i)
    comp = [-1] * n
    comps = []
    for s in range(n):
        if comp[s] >= 0:
            continue
        stack, members = [s], []
        comp[s] = len(comps)
        while stack:
            u = stack.pop()
            members.append(u)
            for v in adj[u]:
                if comp[v] < 0:
                    comp[v] = comp[s]
                    stack.append(v)
        comps.append(members)
    if len(comps) > 1:
        def vol(m):
            return sum(max(1e-3, (cubes[k][2][0] - cubes[k][1][0]) * (cubes[k][2][1] - cubes[k][1][1])
                           * (cubes[k][2][2] - cubes[k][1][2])) for k in m)
        main = max(comps, key=vol)
        floating = [cubes[k][0].get("name") for m in comps if m is not main for k in m]
        stats["floating"] = len(floating)
        findings.append(_f("warning" if len(floating) <= 2 else "error", "floating-parts",
                           f"{len(floating)} parts touch nothing else: {', '.join(map(str, floating[:6]))}"))

    # ---- format limits ----------------------------------------------------------------------------
    if fmt == "java_block":
        for el, lo, hi in cubes:
            if min(lo) < -16 or max(hi) > 32:
                findings.append(_f("error", "java-range", f"{el.get('name')} outside Java's -16..32 range"))
            r = [float(v or 0) for v in (el.get("rotation") or [0, 0, 0])]
            nz = [v for v in r if abs(v) > 1e-6]
            if len(nz) > 1:
                findings.append(_f("error", "java-multi-axis", f"{el.get('name')} rotates on {len(nz)} axes"))
            elif nz and min(abs(nz[0] - a) for a in JAVA_ANGLES) > 1e-3:
                findings.append(_f("warning", "java-angle", f"{el.get('name')} angle {nz[0]:g} is not a "
                                   "multiple of 22.5 within +-45 (only newer versions accept it)"))
        if len(cubes) > 120:
            findings.append(_f("warning", "java-element-count", f"{len(cubes)} elements is heavy for a block model"))
    elif len(cubes) > 160:
        findings.append(_f("warning", "cube-count", f"{len(cubes)} cubes is heavy for an entity"))

    score = 100
    for fd in findings:
        score -= PENALTY.get(fd["severity"], 0)
    return {"score": max(0, score), "findings": findings, "stats": stats}
