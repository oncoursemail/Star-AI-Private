"""Model plan ("spec") schema, validation and deterministic auto-fixes.

A spec is the small JSON a planner (STAR or a person) writes: materials, cuboid parts in centred model
units (x/z centred on 0, y = 0 at the ground, 16 units = one block), optional decals and animations.
`normalize` returns a clean spec plus the list of fixes it applied, so the fixes can be fed back.
"""
from __future__ import annotations

import copy
import re

from .paint import DECALS, KINDS
from .palette import parse_hex

CATEGORIES = ("block", "item", "furniture", "mob", "entity", "armor")
JAVA_CATEGORIES = ("block", "item", "furniture")
FACES = ("north", "east", "south", "west", "up", "down")
PART_LIMIT = {"block": 48, "item": 48, "furniture": 96, "mob": 96, "entity": 128, "armor": 64}
JAVA_ANGLES = (-45.0, -22.5, 0.0, 22.5, 45.0)
JAVA_MIN, JAVA_MAX = -16.0, 32.0
_NAME = re.compile(r"[^a-z0-9_]+")


class SpecError(ValueError):
    pass


def model_format(category: str) -> str:
    return "java_block" if category in JAVA_CATEGORIES else "bedrock"


def _ident(value, fallback):
    s = _NAME.sub("_", str(value or "").strip().lower()).strip("_")
    return s[:48] or fallback


def _vec(v, n=3):
    if not isinstance(v, (list, tuple)) or len(v) != n:
        raise SpecError(f"expected a list of {n} numbers, got {v!r}")
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or abs(x) > 512:
            raise SpecError(f"bad number in {v!r}")
        out.append(float(x))
    return out


def _snap(x, grid):
    return round(round(x / grid) * grid, 4)


def _clean_num(x):
    return int(x) if float(x).is_integer() else x


def normalize(raw: dict) -> tuple[dict, list[str]]:
    """Validate and repair a spec. Raises SpecError when it cannot be repaired."""
    if not isinstance(raw, dict):
        raise SpecError("spec must be a JSON object")
    s = copy.deepcopy(raw)
    fixes: list[str] = []
    s["name"] = _ident(s.get("name"), "model")
    cat = str(s.get("category", "block")).lower()
    if cat not in CATEGORIES:
        fixes.append(f"unknown category {cat!r} -> block")
        cat = "block"
    s["category"] = cat
    try:
        density = int(s.get("density", 1))
    except (TypeError, ValueError):
        density = 1
    if density not in (1, 2):
        fixes.append(f"density {density} -> {1 if density < 1 else 2}")
        density = 1 if density < 1 else 2
    s["density"] = density
    grid = 1.0 / density

    mats = s.get("materials")
    if not isinstance(mats, dict) or not mats:
        raise SpecError("spec needs a non-empty 'materials' object")
    clean_m = {}
    for key, m in mats.items():
        k = _ident(key, "mat")
        if not isinstance(m, dict):
            raise SpecError(f"material {key!r} must be an object")
        kind = str(m.get("kind", "plain")).lower()
        if kind not in KINDS:
            fixes.append(f"material {k}: unknown kind {kind!r} -> plain")
            kind = "plain"
        try:
            parse_hex(m.get("color", ""))
        except ValueError as exc:
            raise SpecError(f"material {k}: {exc}") from None
        entry = {"kind": kind, "color": "#" + str(m["color"]).lstrip("#").lower()}
        if "contrast" in m:
            try:
                entry["contrast"] = max(0.5, min(1.6, float(m["contrast"])))
            except (TypeError, ValueError):
                pass
        clean_m[k] = entry
    if len(clean_m) > 8:
        fixes.append(f"{len(clean_m)} materials is a lot for one model; keep 3-6 for a coherent palette")
    s["materials"] = clean_m
    first_mat = next(iter(clean_m))

    parts = s.get("parts")
    if not isinstance(parts, list) or not parts:
        raise SpecError("spec needs a non-empty 'parts' list")
    names = set()
    clean_p = []
    for i, p in enumerate(parts):
        if not isinstance(p, dict):
            raise SpecError(f"part {i} must be an object")
        name = _ident(p.get("name"), f"part{i}")
        base = name
        n = 2
        while name in names:
            name = f"{base}_{n}"
            n += 1
        if name != base:
            fixes.append(f"duplicate part name {base} -> {name}")
        names.add(name)
        if "from" in p and "to" in p:
            a, b = _vec(p["from"]), _vec(p["to"])
        elif "origin" in p and "size" in p:
            a = _vec(p["origin"])
            b = [a[j] + _vec(p["size"])[j] for j in range(3)]
        else:
            raise SpecError(f"part {name}: needs from/to (or origin/size)")
        lo = [min(a[j], b[j]) for j in range(3)]
        hi = [max(a[j], b[j]) for j in range(3)]
        slo = [_snap(v, grid) for v in lo]
        shi = [_snap(v, grid) for v in hi]
        if slo != lo or shi != hi:
            fixes.append(f"part {name}: snapped to the {grid:g}-unit texel grid")
        zero = [j for j in range(3) if shi[j] - slo[j] <= 0]
        if len(zero) > 1:
            fixes.append(f"part {name}: degenerate (zero size on {len(zero)} axes) -> 1 texel")
            for j in zero:
                shi[j] = slo[j] + grid
        mat = _ident(p.get("material"), first_mat)
        if mat not in clean_m:
            fixes.append(f"part {name}: unknown material {p.get('material')!r} -> {first_mat}")
            mat = first_mat
        rot = _vec(p.get("rotation", [0, 0, 0]))
        center = [(slo[j] + shi[j]) / 2 for j in range(3)]
        pivot = _vec(p["pivot"]) if "pivot" in p else center
        entry = {"name": name, "from": slo, "to": shi, "pivot": [_snap(v, grid / 2) for v in pivot],
                 "rotation": rot, "material": mat}
        if p.get("parent"):
            entry["parent"] = _ident(p["parent"], "")
        if p.get("mirror_of"):
            entry["mirror_of"] = _ident(p["mirror_of"], "")
        if p.get("inflate"):
            try:
                entry["inflate"] = max(0.0, min(2.0, float(p["inflate"])))
            except (TypeError, ValueError):
                pass
        decals = []
        for d in p.get("decals") or []:
            if not isinstance(d, dict) or d.get("kind") not in DECALS or d.get("face") not in FACES:
                fixes.append(f"part {name}: dropped invalid decal {d!r}"[:160])
                continue
            dd = {"kind": d["kind"], "face": d["face"]}
            if d.get("color"):
                try:
                    parse_hex(d["color"])
                    dd["color"] = "#" + str(d["color"]).lstrip("#").lower()
                except ValueError:
                    fixes.append(f"part {name}: decal colour {d['color']!r} dropped")
            decals.append(dd)
        if decals:
            entry["decals"] = decals
        clean_p.append(entry)

    by_name = {p["name"]: p for p in clean_p}
    for p in clean_p:
        par = p.get("parent")
        if par is not None and (par not in by_name or par == p["name"]):
            fixes.append(f"part {p['name']}: parent {par!r} not found -> none")
            p.pop("parent")
    for p in clean_p:  # break cycles
        seen, cur = {p["name"]}, p
        while cur.get("parent"):
            nxt = by_name[cur["parent"]]
            if nxt["name"] in seen:
                fixes.append(f"part {cur['name']}: parent cycle -> none")
                cur.pop("parent")
                break
            seen.add(nxt["name"])
            cur = nxt
    for p in clean_p:
        src = p.get("mirror_of")
        if src and src in by_name and src != p["name"]:
            m = by_name[src]
            p["material"] = m["material"]
            if m.get("decals") and not p.get("decals"):
                p["decals"] = copy.deepcopy(m["decals"])
        elif src:
            p.pop("mirror_of")

    # ground the model: nothing below y=0; mobs and furniture stand on y=0
    min_y = min(p["from"][1] for p in clean_p)
    if min_y < 0 or (cat in ("mob", "entity", "furniture") and min_y > 0):
        for p in clean_p:
            p["from"][1] -= min_y
            p["to"][1] -= min_y
            p["pivot"][1] -= min_y
        fixes.append(f"moved the model by {-min_y:g} on y so it stands on the ground")

    if cat in JAVA_CATEGORIES:
        for p in clean_p:
            r = p["rotation"]
            axes = [j for j in range(3) if abs(r[j]) > 1e-6]
            if len(axes) > 1:
                keep = max(axes, key=lambda j: abs(r[j]))
                fixes.append(f"part {p['name']}: Java allows one rotation axis -> kept {'xyz'[keep]}")
                r = [r[j] if j == keep else 0.0 for j in range(3)]
            for j in range(3):
                if r[j]:
                    snapped = min(JAVA_ANGLES, key=lambda a: abs(a - r[j]))
                    if snapped != r[j]:
                        fixes.append(f"part {p['name']}: Java rotation {r[j]:g} -> {snapped:g}")
                    r[j] = snapped
            p["rotation"] = r
        lo = min(min(p["from"][0], p["from"][2]) for p in clean_p) + 8
        hi = max(max(p["to"][0], p["to"][2]) for p in clean_p) + 8
        top = max(p["to"][1] for p in clean_p)
        if lo < JAVA_MIN or hi > JAVA_MAX or top > JAVA_MAX:
            raise SpecError("model exceeds the Java element range -16..32 (3x3x3 blocks around the block); "
                            "make it smaller")
    limit = PART_LIMIT[cat]
    if len(clean_p) > limit:
        fixes.append(f"{len(clean_p)} parts exceeds the {cat} budget of {limit}")

    anims = []
    if model_format(cat) == "bedrock":
        for a in s.get("animations") or []:
            if not isinstance(a, dict):
                continue
            aname = _ident(a.get("name"), "idle")
            try:
                length = max(0.05, min(30.0, float(a.get("length", 1.0))))
            except (TypeError, ValueError):
                length = 1.0
            bones = {}
            for bone, chans in (a.get("bones") or {}).items():
                b = _ident(bone, "")
                if b not in by_name or not isinstance(chans, dict):
                    fixes.append(f"animation {aname}: unknown part {bone!r} dropped")
                    continue
                cc = {}
                for ch in ("rotation", "position", "scale"):
                    keys = chans.get(ch)
                    if not isinstance(keys, dict):
                        continue
                    kk = {}
                    for t, v in keys.items():
                        try:
                            tt = max(0.0, min(length, float(t)))
                            kk[round(tt, 4)] = _vec(v)
                        except (TypeError, ValueError, SpecError):
                            fixes.append(f"animation {aname}: bad keyframe {t!r} on {b}")
                    if kk:
                        cc[ch] = dict(sorted(kk.items()))
                if cc:
                    bones[b] = cc
            if bones:
                anims.append({"name": aname, "length": length, "loop": bool(a.get("loop", True)), "bones": bones})
    elif s.get("animations"):
        fixes.append("animations dropped: Java block/item models cannot animate")
    s["animations"] = anims
    for p in clean_p:
        p["from"] = [_clean_num(v) for v in p["from"]]
        p["to"] = [_clean_num(v) for v in p["to"]]
        p["pivot"] = [_clean_num(v) for v in p["pivot"]]
        p["rotation"] = [_clean_num(v) for v in p["rotation"]]
    s["parts"] = clean_p
    for k in list(s):
        if k not in ("name", "category", "density", "materials", "parts", "animations", "notes", "brief"):
            s.pop(k)
    return s, fixes
