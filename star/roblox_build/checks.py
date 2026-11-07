"""Deterministic checks on a compiled build: budgets, z-fighting, floating parts, prop overlaps, wall clipping,
walkable route from spawn to every focal point, scale, empty zones. Pure Python; no Studio needed.
"""
from __future__ import annotations

from collections import defaultdict, deque
import math

from .geom import aabb, axis_aligned
from .scene import FLOOR, zone_at

TRIS = {"B": 12, "W": 10, "CW": 8, "C": 64, "S": 192}
BUDGET = {"parts": 6000, "tris": 250_000, "lights": 48, "shadow_lights": 28}
STRUCTURE = ("ground", "floor", "room", "path")
# Flat dressing and contents that legitimately sit inside or under other props.
OVERLAP_EXEMPT = {"rug", "papers", "puddle", "water", "grass_tufts", "led_strip", "string_lights", "cobweb", "vines",
                  "fish_school", "coral", "platform_edge", "candles", "picture", "sign", "sconce", "info_plaque"}
SEAT_PAIRS = ({"chair", "stool", "sofa", "bench"}, {"table", "counter", "booth", "reading_table"})


def _inst_key(p: dict):
    return (p.get("prop"), p.get("copy", 0))


def _overlap(a, b, tol=0.0):
    return all(a[0][i] < b[1][i] - tol and b[0][i] < a[1][i] - tol for i in range(3))


def _touch(a, b, tol=0.08):
    return all(a[0][i] <= b[1][i] + tol and b[0][i] <= a[1][i] + tol for i in range(3))


def _vol(box):
    return max(0.0, box[1][0] - box[0][0]) * max(0.0, box[1][1] - box[0][1]) * max(0.0, box[1][2] - box[0][2])


def _inter(a, b):
    lo = tuple(max(a[0][i], b[0][i]) for i in range(3))
    hi = tuple(min(a[1][i], b[1][i]) for i in range(3))
    return (lo, hi) if all(hi[i] > lo[i] for i in range(3)) else None


class _Grid:
    def __init__(self, cell=8.0):
        self.cell, self.cells = cell, defaultdict(list)

    def keys(self, box):
        c = self.cell
        for i in range(int(math.floor(box[0][0] / c)), int(math.floor(box[1][0] / c)) + 1):
            for j in range(int(math.floor(box[0][1] / c)), int(math.floor(box[1][1] / c)) + 1):
                for k in range(int(math.floor(box[0][2] / c)), int(math.floor(box[1][2] / c)) + 1):
                    yield (i, j, k)

    def add(self, index, box):
        for key in self.keys(box):
            self.cells[key].append(index)

    def near(self, box):
        seen = set()
        for key in self.keys(box):
            for index in self.cells.get(key, ()):
                if index not in seen:
                    seen.add(index)
                    yield index


def z_fighting(parts: list[dict], boxes) -> list[dict]:
    """Coplanar, same-facing, overlapping faces of axis-aligned opaque blocks."""
    faces = defaultdict(list)
    for i, p in enumerate(parts):
        if p["s"] != "B" or not axis_aligned(p) or p.get("t", 0) >= 0.95:
            continue
        lo, hi = boxes[i]
        for axis in range(3):
            for sign, coord in ((-1, lo[axis]), (1, hi[axis])):
                if axis == 1 and sign == -1:
                    continue        # bottoms rest on something: hidden
                faces[(axis, sign, round(coord * 50))].append(i)
    found = []
    seen = set()
    for (axis, sign, _), members in faces.items():
        if len(members) < 2 or len(members) > 400:
            continue
        others = [a for a in range(3) if a != axis]
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                i, j = members[x], members[y]
                a, b = boxes[i], boxes[j]
                area = 1.0
                for o in others:
                    ov = min(a[1][o], b[1][o]) - max(a[0][o], b[0][o])
                    area *= max(0.0, ov)
                close = parts[i]["m"] == parts[j]["m"] and sum(abs(parts[i]["c"][k] - parts[j]["c"][k]) for k in range(3)) < 40
                if area > 0.25 and not close:
                    key = (min(i, j), max(i, j))
                    if key not in seen:
                        seen.add(key)
                        found.append({"a": i, "b": j, "area": round(area, 2), "axis": "xyz"[axis]})
    return found


def floating(parts: list[dict], boxes, grid: _Grid) -> list[int]:
    """Parts not connected (touching chain) to the ground, a floor, or y <= 0.1."""
    supported = [False] * len(parts)
    queue = deque()
    for i, p in enumerate(parts):
        if p.get("kit") in ("ground", "floor", "fill_light") or boxes[i][0][1] <= 0.1 or p.get("t", 0) >= 0.99:
            supported[i] = True
            queue.append(i)
    while queue:
        i = queue.popleft()
        for j in grid.near(boxes[i]):
            if not supported[j] and _touch(boxes[i], boxes[j]):
                supported[j] = True
                queue.append(j)
    return [i for i, ok in enumerate(supported) if not ok]


def walk_grid(spec: dict, parts: list[dict], boxes, cell: float = 1.0):
    w, d = spec["size"]
    nx, nz = int(w / cell), int(d / cell)
    blocked = bytearray(nx * nz)
    for i, p in enumerate(parts):
        if not p.get("cc", True) or p.get("kit") in ("ground", "floor", "path") or p.get("sem") == "water":
            continue
        lo, hi = boxes[i]
        if hi[1] - lo[1] < 0.01:
            continue
        cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
        base = FLOOR if (z := zone_at(spec, cx, cz)) and z.get("floor") else 0.0
        if hi[1] <= base + 2.0 or lo[1] >= base + 5.5:      # steppable or above head
            continue
        for gx in range(max(0, int((lo[0] + w / 2) / cell) - 1), min(nx, int((hi[0] + w / 2) / cell) + 1)):
            for gz in range(max(0, int((lo[2] + d / 2) / cell) - 1), min(nz, int((hi[2] + d / 2) / cell) + 1)):
                blocked[gx * nz + gz] = 1
    return blocked, nx, nz


def reachable(spec, blocked, nx, nz, cell=1.0):
    w, d = spec["size"]

    def idx(x, z):
        return int(min(nx - 1, max(0, (x + w / 2) / cell))), int(min(nz - 1, max(0, (z + d / 2) / cell)))
    sx, sz = idx(*spec["spawn"])
    seen = bytearray(nx * nz)
    if blocked[sx * nz + sz]:   # spawn inside something: start from the nearest free cell
        best = min(((gx, gz) for gx in range(nx) for gz in range(nz) if not blocked[gx * nz + gz]),
                   key=lambda c: (c[0] - sx) ** 2 + (c[1] - sz) ** 2, default=None)
        if best is None:
            return seen, (sx, sz), True
        sx, sz = best
        spawn_blocked = True
    else:
        spawn_blocked = False
    q = deque([(sx, sz)])
    seen[sx * nz + sz] = 1
    while q:
        x, z = q.popleft()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            a, b = x + dx, z + dz
            if 0 <= a < nx and 0 <= b < nz and not seen[a * nz + b] and not blocked[a * nz + b]:
                seen[a * nz + b] = 1
                q.append((a, b))
    return seen, (sx, sz), spawn_blocked


def run(spec: dict, compiled: dict) -> dict:
    parts = compiled["parts"]
    boxes = [aabb(p) for p in parts]
    grid = _Grid(8.0)
    for i, box in enumerate(boxes):
        if parts[i].get("kit") != "ground":
            grid.add(i, box)
    defects: list[dict] = []
    tris = sum(2 * p["mesh"]["seg"] * len(p["mesh"]["lathe"]) if p.get("mesh") else TRIS.get(p["s"], 12) for p in parts)
    lights = [p["light"] for p in parts if p.get("light")]
    metrics = {"parts": len(parts), "tris_est": tris, "lights": len(lights),
               "shadow_lights": sum(1 for L in lights if L.get("sh")), "props": len(spec["props"]),
               "materials": len({p["m"] for p in parts}), "colors": len({tuple(p["c"]) for p in parts})}
    for key, limit in (("parts", BUDGET["parts"]), ("tris_est", BUDGET["tris"]), ("lights", BUDGET["lights"]),
                       ("shadow_lights", BUDGET["shadow_lights"])):
        if metrics[key] > limit:
            defects.append({"code": "budget", "severity": 2, "detail": f"{key} {metrics[key]} over budget {limit}"})
    # z-fighting
    zf = z_fighting(parts, boxes)
    metrics["z_fighting"] = len(zf)
    for item in zf[:12]:
        a, b = parts[item["a"]], parts[item["b"]]
        defects.append({"code": "z_fighting", "severity": 1, "parts": [item["a"], item["b"]],
                        "prop": a.get("prop", b.get("prop")),
                        "detail": f"coplanar faces ({item['area']} sq studs) between {a.get('kit')} and {b.get('kit')}"})
    # floating
    fl = floating(parts, boxes, grid)
    metrics["floating_parts"] = len(fl)
    by_inst = defaultdict(list)
    for i in fl:
        by_inst[_inst_key(parts[i]) if parts[i].get("prop") is not None else ("struct", parts[i].get("kit"))].append(i)
    for key, idxs in list(by_inst.items())[:12]:
        low = min(boxes[i][0][1] for i in idxs)
        defects.append({"code": "floating", "severity": 2, "prop": key[0] if key[0] != "struct" else None,
                        "copy": key[1] if key[0] != "struct" else 0, "parts": idxs[:6],
                        "detail": f"{len(idxs)} part(s) of {parts[idxs[0]].get('kit')} float (lowest at y={low:.1f}, "
                                  "nothing under or touching them)"})
    # prop instance boxes, overlaps between props, clipping into walls
    inst_boxes = {}
    for i, p in enumerate(parts):
        if p.get("prop") is None:
            continue
        key = _inst_key(p)
        lo, hi = boxes[i]
        if key in inst_boxes:
            a = inst_boxes[key]
            inst_boxes[key] = (tuple(min(a[0][k], lo[k]) for k in range(3)), tuple(max(a[1][k], hi[k]) for k in range(3)))
        else:
            inst_boxes[key] = (lo, hi)
    keys = list(inst_boxes)
    overlaps = 0
    for x in range(len(keys)):
        for y in range(x + 1, len(keys)):
            if keys[x][0] == keys[y][0]:
                continue
            ka, kb = spec["props"][keys[x][0]]["kit"], spec["props"][keys[y][0]]["kit"]
            if ka in OVERLAP_EXEMPT or kb in OVERLAP_EXEMPT or (ka in SEAT_PAIRS[0] and kb in SEAT_PAIRS[1])                     or (kb in SEAT_PAIRS[0] and ka in SEAT_PAIRS[1]):
                continue
            a, b = inst_boxes[keys[x]], inst_boxes[keys[y]]
            inter = _inter(a, b)
            if not inter:
                continue
            small = min(_vol(a), _vol(b)) or 1
            if _vol(inter) / small > 0.3:
                overlaps += 1
                if overlaps <= 10:
                    pa, pb = spec["props"][keys[x][0]], spec["props"][keys[y][0]]
                    defects.append({"code": "prop_overlap", "severity": 2, "prop": keys[y][0], "copy": keys[y][1],
                                    "other": keys[x][0], "detail": f"{pb['kit']} (prop {keys[y][0]}) intersects {pa['kit']} "
                                    f"(prop {keys[x][0]}) by {100 * _vol(inter) / small:.0f}% of the smaller one"})
    metrics["prop_overlaps"] = overlaps
    walls = [i for i, p in enumerate(parts) if p.get("kit") == "room" and p.get("t", 0) < 0.5]
    clips = 0
    for key, box in inst_boxes.items():
        if spec["props"][key[0]]["kit"] in ("chandelier", "pendant_lamp", "cobweb", "vines"):
            continue
        for i in walls:
            inter = _inter(box, boxes[i])
            if inter and min(inter[1][k] - inter[0][k] for k in (0, 2)) > 0.6 and inter[1][1] - inter[0][1] > 0.6:
                clips += 1
                if clips <= 10:
                    defects.append({"code": "wall_clip", "severity": 2, "prop": key[0], "copy": key[1],
                                    "detail": f"{spec['props'][key[0]]['kit']} (prop {key[0]}) pokes into a wall/roof of "
                                              f"room {parts[i].get('zone')}"})
                break
    metrics["wall_clips"] = clips
    # walkable route spawn -> focal points
    blocked, nx, nz = walk_grid(spec, parts, boxes)
    seen, start, spawn_blocked = reachable(spec, blocked, nx, nz)
    if spawn_blocked:
        defects.append({"code": "spawn_blocked", "severity": 2, "detail": "the spawn point is inside an obstacle"})
    w, d = spec["size"]
    unreachable = 0
    for f in spec["focal"]:
        fx, fz = f["at"]
        ok = False
        for gx in range(max(0, int(fx + w / 2) - 7), min(nx, int(fx + w / 2) + 8)):
            for gz in range(max(0, int(fz + d / 2) - 7), min(nz, int(fz + d / 2) + 8)):
                if seen[gx * nz + gz]:
                    ok = True
                    break
            if ok:
                break
        if not ok:
            unreachable += 1
            defects.append({"code": "unreachable", "severity": 3, "detail": f"focal point {f['id']} at {f['at']} cannot be "
                            "walked to from the spawn (walls without a door, or props blocking the way)"})
    metrics["walkable_share"] = round(sum(seen) / max(1, nx * nz), 3)
    metrics["unreachable_focal"] = unreachable
    # scale and structure
    for room in spec["rooms"]:
        doors = [o for o in room["openings"] if o["kind"] in ("door", "arch", "open")]
        if not doors:
            defects.append({"code": "no_door", "severity": 3, "detail": f"room {room['zone']} has no door/arch/open side"})
        for o in doors:
            if o["w"] < 4 or o["h"] < 7:
                defects.append({"code": "scale", "severity": 1, "detail": f"opening on {room['zone']} {o['side']} is "
                                f"{o['w']:.0f}x{o['h']:.0f}: a character needs at least 4 wide, 7 high"})
        if room["h"] < 10:
            defects.append({"code": "scale", "severity": 1, "detail": f"room {room['zone']} ceiling {room['h']:.0f} is low"})
    for key, box in inst_boxes.items():
        prop = spec["props"][key[0]]
        cx, cz = (box[0][0] + box[1][0]) / 2, (box[0][2] + box[1][2]) / 2
        room = next((r for r in spec["rooms"] if (z := zone_at(spec, cx, cz)) and r["zone"] == z["id"]), None)
        if room and room["roof"] != "none" and box[1][1] > room["h"] + 0.3 and prop["kit"] not in ("chandelier", "pendant_lamp"):
            defects.append({"code": "through_roof", "severity": 2, "prop": key[0], "copy": key[1],
                            "detail": f"{prop['kit']} (prop {key[0]}) is {box[1][1]:.0f} tall, the room is {room['h']:.0f}"})
    # density per zone (props per 100 sq studs) and empty zones
    density = {}
    for zone in spec["zones"]:
        x0, z0, x1, z1 = zone["rect"]
        count = sum(1 for key, box in inst_boxes.items()
                    if x0 <= (box[0][0] + box[1][0]) / 2 <= x1 and z0 <= (box[0][2] + box[1][2]) / 2 <= z1)
        area = (x1 - x0) * (z1 - z0)
        density[zone["id"]] = round(100 * count / max(1, area), 2)
        if count == 0:
            defects.append({"code": "empty_zone", "severity": 1, "detail": f"zone {zone['id']} has no props"})
    metrics["density"] = density
    metrics["light_sources"] = len(lights)
    if not lights and spec["mood"] in ("cozy_interior", "foggy_horror", "cold_night", "warm_evening", "neon_night"):
        defects.append({"code": "no_lights", "severity": 2, "detail": f"mood {spec['mood']} but no light sources placed"})
    score = sum(dd["severity"] for dd in defects)
    return {"ok": not any(dd["severity"] >= 2 for dd in defects), "metrics": metrics, "defects": defects,
            "severity_sum": score}
