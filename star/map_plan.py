"""Map plans: a declarative JSON description of a Roblox blockout and an offline dry run.

The shape is inspired by the SceneSpec format of ShiroKSH/skills
(https://github.com/ShiroKSH/skills, MIT, commit b1251cc): a named map under a managed root
(``Workspace/MapDrafts``), tagged Roblox values, an explicit asset allowlist, and a dry run that
reports what an apply would do before anything touches Studio. This module is an independent,
much smaller Python implementation; no ShiroKSH code is copied.

What the dry run checks (all offline, deterministic, no Studio needed):
- schema (jsonschema), unique names, managed root, object limit;
- bounds: every object's axis-aligned box (rotation included) inside the declared bounds;
- oriented-box overlap checks for solid parts, conservative mesh proxy checks and bounded analysis;
- spawns: at least one, inside the bounds, with head room above the pad;
- route: each leg between waypoints is jumpable for a default character (gap and rise);
- assets: only ids on the plan's allowlist; unanchored and floating parts are reported.

``dry_run(plan)`` returns the report; when there are no blockers it also returns the ordered
operations (create folder / part / spawn, insert allowlisted asset, set lighting) that STAR's
Studio tools can apply later, and ``to_luau(plan)`` renders the same operations as one Luau
script that records a single undo step. Nothing here applies anything.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from functools import lru_cache
import math
import re

from ._lazy import lazy_attr
from .scene_collision import from_pose, intersects
Draft202012Validator = lazy_attr("jsonschema", "Draft202012Validator")  # loaded on first validation

MANAGED_ROOT = "Workspace/MapDrafts"
# Default Roblox character: Humanoid.JumpHeight 7.2 studs (JumpPower 50, gravity 196.2) and
# WalkSpeed 16, so a flat running jump covers about 8.7 studs. The defaults leave a margin.
DEFAULT_MAX_JUMP_GAP = 8.0
DEFAULT_MAX_JUMP_RISE = 6.5
CHARACTER_HEADROOM = 6.0
SPAWN_SIZE = (6.0, 1.0, 6.0)
BATCH_SIZE = 100
OVERLAP_TOLERANCE = 0.05
SUPPORT_TOLERANCE = 0.6
MAX_REPORTED = 25
MAX_COLLISION_CANDIDATES = 50_000  # Explicit budget, never silently approve unchecked geometry.
MAX_BROAD_PAIRS = 250_000  # Bound even pathological single-plane/same-position scenes.
CREDIT = "Plan format inspired by ShiroKSH/skills SceneSpec (MIT)."

PART_CLASSES = ("Part", "WedgePart", "CornerWedgePart", "TrussPart")
MATERIALS = ("Plastic", "SmoothPlastic", "Wood", "WoodPlanks", "Slate", "Concrete", "Brick", "Cobblestone",
             "Granite", "Marble", "Pebble", "Sand", "Grass", "LeafyGrass", "Ground", "Mud", "Rock", "Basalt",
             "Sandstone", "Limestone", "Ice", "Glacier", "Snow", "Salt", "Metal", "DiamondPlate", "CorrodedMetal",
             "Foil", "Glass", "Neon", "Fabric", "Carpet", "Plaster", "Asphalt", "Pavement", "Cardboard",
             "Rubber", "ForceField")
STYLES = ("realistic", "lowpoly", "cartoon", "sci-fi", "medieval", "modern", "horror", "obby", "fantasy")
ROLES = ("floor", "wall", "platform", "ramp", "stairs", "decor", "checkpoint", "hazard", "goal", "prop", "roof")

_NAME = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$"}
_NUM = {"type": "number"}
_VEC3 = {"type": "array", "items": _NUM, "minItems": 3, "maxItems": 3}
_SIZE3 = {"type": "array", "items": {"type": "number", "exclusiveMinimum": 0, "maximum": 2048},
          "minItems": 3, "maxItems": 3}
_HEX = {"type": "string", "pattern": r"^#[0-9A-Fa-f]{6}$"}
_ASSET_ID = {"type": "integer", "minimum": 1, "maximum": 10**15}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "STAR map plan (version 1)",
    "type": "object",
    "required": ["mapName", "bounds"],
    "additionalProperties": False,
    "properties": {
        "version": {"const": 1},
        "mapName": _NAME,
        "style": {"enum": list(STYLES)},
        "description": {"type": "string", "maxLength": 600},
        "rootPath": {"type": "string", "maxLength": 120},
        "bounds": {"type": "object", "required": ["size"], "additionalProperties": False, "properties": {
            "size": {"type": "array", "items": {"type": "number", "exclusiveMinimum": 0, "maximum": 20000},
                     "minItems": 3, "maxItems": 3},
            "center": _VEC3}},
        "parts": {"type": "array", "maxItems": 5000, "items": {
            "type": "object", "required": ["name", "position", "size"], "additionalProperties": False,
            "properties": {
                "name": _NAME, "class": {"enum": list(PART_CLASSES)}, "position": _VEC3, "size": _SIZE3,
                "rotation": _VEC3, "material": {"enum": list(MATERIALS)}, "color": _HEX,
                "anchored": {"type": "boolean"}, "canCollide": {"type": "boolean"},
                "transparency": {"type": "number", "minimum": 0, "maximum": 1},
                "group": _NAME, "role": {"enum": list(ROLES)},
                "allowOverlap": {"type": "boolean"}, "floating": {"type": "boolean"}}}},
        "spawns": {"type": "array", "maxItems": 64, "items": {
            "type": "object", "required": ["name", "position"], "additionalProperties": False,
            "properties": {"name": _NAME, "position": _VEC3, "color": _HEX, "group": _NAME,
                           "neutral": {"type": "boolean"}}}},
        "assets": {"type": "array", "maxItems": 500, "items": {
            "type": "object", "required": ["name", "assetId", "position"], "additionalProperties": False,
            "properties": {"name": _NAME, "assetId": _ASSET_ID, "position": _VEC3, "rotation": _VEC3,
                           "approxSize": _SIZE3, "group": _NAME, "allowOverlap": {"type": "boolean"}}}},
        "route": {"type": "object", "required": ["waypoints"], "additionalProperties": False, "properties": {
            "waypoints": {"type": "array", "minItems": 2, "maxItems": 400,
                          "items": {"oneOf": [_NAME, _VEC3]}},
            "maxJumpGap": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
            "maxJumpRise": {"type": "number", "exclusiveMinimum": 0, "maximum": 100}}},
        "assetPolicy": {"type": "object", "additionalProperties": False, "properties": {
            "allowedAssetIds": {"type": "array", "items": _ASSET_ID, "maxItems": 500, "uniqueItems": True}}},
        "lighting": {"type": "object", "additionalProperties": False, "properties": {
            "clockTime": {"type": "number", "minimum": 0, "maximum": 24},
            "brightness": {"type": "number", "minimum": 0, "maximum": 10},
            "ambient": _HEX, "outdoorAmbient": _HEX}},
        "limits": {"type": "object", "additionalProperties": False, "properties": {
            "maxObjects": {"type": "integer", "minimum": 1, "maximum": 5000}}},
    },
}


@lru_cache(maxsize=1)
def _validator():
    """The map plan schema validator, built on first use (jsonschema is not imported at start-up)."""
    return Draft202012Validator(SCHEMA)


class _Box:
    __slots__ = ("name", "kind", "lo", "hi", "solid", "rotated", "allow_overlap", "floating", "truss", "role",
                 "anchored", "geometry", "shape_approximate")

    def __init__(self, name, kind, lo, hi, *, solid=True, rotated=False, allow_overlap=False, floating=False,
                 truss=False, role="", anchored=True, geometry=None, shape_approximate=False):
        self.name, self.kind, self.lo, self.hi = name, kind, lo, hi
        self.solid, self.rotated, self.allow_overlap = solid, rotated, allow_overlap
        self.floating, self.truss, self.role, self.anchored = floating, truss, role, anchored
        self.geometry = geometry or from_pose([(a + b) / 2 for a, b in zip(lo, hi)],
                                              [b - a for a, b in zip(lo, hi)])
        self.shape_approximate = shape_approximate


def _aabb(position, size, rotation=(0, 0, 0)):
    """Conservative world-space bounds using Roblox's Y-X-Z Orientation order."""
    box = from_pose(position, size, rotation)
    return list(box.lo), list(box.hi)


def _finite(plan) -> bool:
    if isinstance(plan, dict):
        return all(_finite(v) for v in plan.values())
    if isinstance(plan, list):
        return all(_finite(v) for v in plan)
    return type(plan) not in (int, float) or (abs(plan) <= 1e9 and math.isfinite(plan))


def _issue(code: str, message: str, objects=()) -> dict:
    objects = list(objects)
    item = {"code": code, "message": message}
    if objects:
        item["objects"] = objects[:MAX_REPORTED]
        if len(objects) > MAX_REPORTED:
            item["more"] = len(objects) - MAX_REPORTED
    return item


def _round(values, digits=3):
    return [round(v, digits) for v in values]


def _boxes(plan: dict) -> list[_Box]:
    boxes = []
    for part in plan.get("parts", []):
        geom = from_pose(part["position"], part["size"], part.get("rotation", (0, 0, 0)))
        boxes.append(_Box(part["name"], "part", geom.lo, geom.hi, solid=part.get("canCollide", True),
                          rotated=geom.rotated, allow_overlap=part.get("allowOverlap", False),
                          floating=part.get("floating", False), truss=part.get("class") == "TrussPart",
                          role=part.get("role", ""), anchored=part.get("anchored", True),
                          geometry=geom, shape_approximate=part.get("class", "Part") != "Part"))
    for spawn in plan.get("spawns", []):
        geom = from_pose(spawn["position"], SPAWN_SIZE)
        boxes.append(_Box(spawn["name"], "spawn", geom.lo, geom.hi, geometry=geom))
    for asset in plan.get("assets", []):
        if "approxSize" in asset:
            geom = from_pose(asset["position"], asset["approxSize"], asset.get("rotation", (0, 0, 0)))
            boxes.append(_Box(asset["name"], "asset", geom.lo, geom.hi, rotated=geom.rotated,
                              allow_overlap=asset.get("allowOverlap", False),
                              geometry=geom, shape_approximate=True))
    return boxes


def _penetration(a: _Box, b: _Box) -> list[float]:
    return [min(a.hi[i], b.hi[i]) - max(a.lo[i], b.lo[i]) for i in range(3)]


def _overlaps(boxes: list[_Box]) -> tuple[list[dict], list[str], dict]:
    """Adaptive-axis sweep + box SAT with bounded computation AND memory.

    Wedges, trusses and asset meshes have approximate exterior bounds. The
    reported depth is AABB depth, not a true minimum translation vector.
    """
    solid = [b for b in boxes if b.solid and not b.allow_overlap]
    # Use the sparsest world axis; stable deterministic tie-break by axis.
    if solid:
        axis = min(range(3), key=lambda k: sum(b.hi[k] - b.lo[k] for b in solid)
                   / max(0.001, max(b.hi[k] for b in solid) - min(b.lo[k] for b in solid)))
        solid.sort(key=lambda b: b.lo[axis])
    else:
        axis = 0
    pairs, zfight = [], []
    candidates = broad_pairs = overlaps_total = zfight_total = 0

    def finish(reason: str | None) -> tuple[list[dict], list[str], dict]:
        return pairs, zfight, {
            "method": "obb-sat", "sweep_axis": "xyz"[axis],
            "candidates_checked": candidates, "broad_pairs_checked": broad_pairs,
            "candidate_budget": MAX_COLLISION_CANDIDATES,
            "broad_pair_budget": MAX_BROAD_PAIRS,
            "overlap_pairs_found": overlaps_total,
            "zfight_pairs_found": zfight_total,
            "exhaustive": reason is None, "truncated_reason": reason,
        }

    for i, a in enumerate(solid):
        for j in range(i + 1, len(solid)):
            b = solid[j]
            if b.lo[axis] >= a.hi[axis] - OVERLAP_TOLERANCE:
                break
            if broad_pairs >= MAX_BROAD_PAIRS:
                return finish("broad_pair_budget")
            broad_pairs += 1
            depth = _penetration(a, b)
            if min(depth) <= OVERLAP_TOLERANCE:
                continue
            if candidates >= MAX_COLLISION_CANDIDATES:
                return finish("candidate_budget")
            candidates += 1
            if not intersects(a.geometry, b.geometry, tolerance=OVERLAP_TOLERANCE):
                continue
            overlaps_total += 1
            if len(pairs) < MAX_REPORTED:
                entry = {"a": a.name, "b": b.name, "depth": _round(depth, 2)}
                if a.rotated or b.rotated or a.shape_approximate or b.shape_approximate:
                    entry["approximate"] = True  # Previous public output field.
                    entry["approximate_depth"] = True
                if a.shape_approximate or b.shape_approximate:
                    entry["approximate_shape"] = True
                pairs.append(entry)
            # AABB plane coincidence is only a meaningful z-fighting hint for
            # two actual axis-aligned boxes, not rotated bounding envelopes.
            if not (a.rotated or b.rotated or a.shape_approximate or b.shape_approximate):
                if any(abs(a.lo[k] - b.lo[k]) < 1e-3 or abs(a.hi[k] - b.hi[k]) < 1e-3
                       for k in range(3)):
                    zfight_total += 1
                    if len(zfight) < MAX_REPORTED:
                        zfight.append(f"{a.name} / {b.name}")
    return finish(None)


def _support_index(boxes: list[_Box]) -> tuple[list[float], list[_Box]]:
    """Reusable index of top-face heights for hundreds of grounded props."""
    rows = sorted((box.hi[1], i, box) for i, box in enumerate(boxes) if box.solid)
    return [row[0] for row in rows], [row[2] for row in rows]


def _supported(box: _Box, index: tuple[list[float], list[_Box]]) -> bool:
    tops, ordered = index
    start = bisect_left(tops, box.lo[1] - SUPPORT_TOLERANCE)
    end = bisect_right(tops, box.lo[1] + SUPPORT_TOLERANCE)
    for other in ordered[start:end]:
        if other is box:
            continue
        # Approximate support: bounding-box XZ intersection and matching
        # height. A slope or imported asset needs actual Studio physics QA.
        if (other.lo[0] < box.hi[0] and other.hi[0] > box.lo[0]
                and other.lo[2] < box.hi[2] and other.hi[2] > box.lo[2]):
            return True
    return False


def _route(plan: dict, by_name: dict, blockers: list, warnings: list) -> dict | None:
    route = plan.get("route")
    if not route:
        return None
    gap_limit = route.get("maxJumpGap", DEFAULT_MAX_JUMP_GAP)
    rise_limit = route.get("maxJumpRise", DEFAULT_MAX_JUMP_RISE)
    points = []
    unknown = []
    for waypoint in route["waypoints"]:
        if isinstance(waypoint, str):
            box = by_name.get(waypoint)
            if box is None:
                unknown.append(waypoint)
                continue
            points.append((waypoint, box.lo, box.hi, box.truss))
        else:
            label = "(" + ", ".join(f"{v:g}" for v in waypoint) + ")"
            points.append((label, list(waypoint), list(waypoint), False))
    if unknown:
        blockers.append(_issue("route-unknown", "Route waypoints name objects that are not in the plan.", unknown))
        return {"legs": [], "max_jump_gap": gap_limit, "max_jump_rise": rise_limit}
    first = route["waypoints"][0]
    if not (isinstance(first, str) and by_name.get(first) and by_name[first].kind == "spawn"):
        warnings.append(_issue("route-start", "The route does not start at a spawn."))
    legs, too_far, too_high, length = [], [], [], 0.0
    for (name_a, lo_a, hi_a, _), (name_b, lo_b, hi_b, truss_b) in zip(points, points[1:]):
        dx = max(0.0, lo_b[0] - hi_a[0], lo_a[0] - hi_b[0])
        dz = max(0.0, lo_b[2] - hi_a[2], lo_a[2] - hi_b[2])
        gap = math.hypot(dx, dz)
        rise = hi_b[1] - hi_a[1]
        centre = math.dist([(lo_a[i] + hi_a[i]) / 2 for i in range(3)], [(lo_b[i] + hi_b[i]) / 2 for i in range(3)])
        length += centre
        leg = {"from": name_a, "to": name_b, "gap": round(gap, 2), "rise": round(rise, 2), "ok": True}
        if gap > gap_limit:
            leg["ok"] = False
            too_far.append(f"{name_a} -> {name_b} ({gap:.1f} studs)")
        if rise > rise_limit and not truss_b:
            leg["ok"] = False
            too_high.append(f"{name_a} -> {name_b} (+{rise:.1f} studs)")
        legs.append(leg)
    if too_far:
        blockers.append(_issue("route-gap", f"Gaps wider than {gap_limit:g} studs cannot be jumped by a default "
                                            "character. Waypoints are the surfaces a player stands on, in order: "
                                            "include floors and bridges between platforms.", too_far))
    if too_high:
        blockers.append(_issue("route-rise", f"Rises higher than {rise_limit:g} studs cannot be jumped (use stairs, "
                                             "a ramp or a TrussPart).", too_high))
    return {"legs": legs[:200], "legs_total": len(legs), "length_studs": round(length, 1),
            "max_jump_gap": gap_limit, "max_jump_rise": rise_limit}


def dry_run(plan, *, include_operations: bool = True) -> dict:
    """Validate a plan and report what applying it would do. Never raises on bad input."""
    blockers: list[dict] = []
    warnings: list[dict] = []
    info: list[dict] = []
    if not isinstance(plan, dict):
        return {"ok": False, "blockers": [_issue("schema", "A map plan must be a JSON object.")],
                "warnings": [], "info": [], "credit": CREDIT}
    errors = sorted(_validator().iter_errors(plan), key=lambda e: list(e.absolute_path))
    if errors:
        found = [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message[:200]}" for e in errors]
        return {"ok": False, "blockers": [_issue("schema", "The plan does not match the map plan schema.", found)],
                "warnings": [], "info": [], "schema_title": SCHEMA["title"], "credit": CREDIT}
    if not _finite(plan):
        return {"ok": False, "blockers": [_issue("schema", "Numbers must be finite.")], "warnings": [], "info": [],
                "credit": CREDIT}

    map_name = plan["mapName"]
    root_path = plan.get("rootPath", MANAGED_ROOT).rstrip("/")
    segment = re.compile(_NAME["pattern"])
    if ((root_path != MANAGED_ROOT and not root_path.startswith(MANAGED_ROOT + "/"))
            or not all(segment.match(part) for part in root_path.split("/"))):
        blockers.append(_issue("root-path", f"rootPath must be {MANAGED_ROOT} or a folder inside it, so an apply "
                                            "never touches existing game content."))
    root = f"{root_path}/{map_name}"

    names = [item["name"] for key in ("parts", "spawns", "assets") for item in plan.get(key, [])]
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        blockers.append(_issue("duplicate-name", "Object names must be unique within a plan.", duplicates))
    groups = sorted({item["group"] for key in ("parts", "spawns", "assets") for item in plan.get(key, [])
                     if item.get("group")})
    clash = sorted(set(groups) & set(names))
    if clash:
        blockers.append(_issue("duplicate-name", "A group folder has the same name as an object.", clash))

    counts = {"parts": len(plan.get("parts", [])), "spawns": len(plan.get("spawns", [])),
              "assets": len(plan.get("assets", [])), "groups": len(groups)}
    total = sum(counts.values()) + 1   # + the map folder
    counts["total_objects"] = total
    limit = plan.get("limits", {}).get("maxObjects", 1500)
    if total > limit:
        blockers.append(_issue("object-limit", f"The plan creates {total} objects; the limit is {limit}."))

    boxes = _boxes(plan)
    by_name = {box.name: box for box in boxes}
    size = plan["bounds"]["size"]
    center = plan["bounds"].get("center", [0, 0, 0])
    lo_bound = [c - s / 2 for c, s in zip(center, size)]
    hi_bound = [c + s / 2 for c, s in zip(center, size)]
    outside = [box.name for box in boxes
               if any(box.lo[i] < lo_bound[i] - 0.01 or box.hi[i] > hi_bound[i] + 0.01 for i in range(3))]
    if outside:
        blockers.append(_issue("out-of-bounds", "Objects extend outside the declared bounds.", outside))
    used = None
    ground = min((box.lo[1] for box in boxes), default=lo_bound[1])   # lowest surface counts as ground
    if boxes:
        used_lo = [min(box.lo[i] for box in boxes) for i in range(3)]
        used_hi = [max(box.hi[i] for box in boxes) for i in range(3)]
        used = {"min": _round(used_lo), "max": _round(used_hi), "size": _round([h - l for l, h in zip(used_lo, used_hi)])}

    pairs, zfight, collision_audit = _overlaps(boxes)
    if not collision_audit["exhaustive"]:
        blockers.append(_issue("collision-audit-incomplete",
                               "Geometry check reached its bounded work budget; map apply is blocked "
                               "until the scene is partitioned or overlaps are resolved."))
    if pairs:
        warning = {"code": "overlap", "message": "Solid objects interpenetrate (set allowOverlap on intended "
                                               "unions, or move them).", "pairs": pairs}
        extra = collision_audit["overlap_pairs_found"] - len(pairs)
        if extra:
            warning["more"] = extra
        warnings.append(warning)
    if zfight:
        warning = _issue("z-fighting", "Overlapping objects share a face plane; the shared face will flicker.",
                         zfight)
        extra = collision_audit["zfight_pairs_found"] - len(zfight)
        if extra:
            warning["more"] = extra
        warnings.append(warning)

    support_index = _support_index(boxes)
    spawns = [box for box in boxes if box.kind == "spawn"]
    if not spawns:
        blockers.append(_issue("no-spawn", "The plan has no spawn; players would spawn at the world origin."))
    blocked, floating_spawns = [], []
    for spawn in spawns:
        head = _Box(spawn.name + " headroom", "probe", [spawn.lo[0] + 1, spawn.hi[1] + 0.05, spawn.lo[2] + 1],
                    [spawn.hi[0] - 1, spawn.hi[1] + CHARACTER_HEADROOM, spawn.hi[2] - 1])
        for other in boxes:
            if other is not spawn and other.solid and intersects(head.geometry, other.geometry, tolerance=0.0):
                blocked.append(f"{spawn.name} (under {other.name})")
                break
        if spawn.lo[1] > ground + SUPPORT_TOLERANCE and not _supported(spawn, support_index):
            floating_spawns.append(spawn.name)
    if blocked:
        blockers.append(_issue("spawn-blocked", f"Spawns need {CHARACTER_HEADROOM:g} studs of free space above "
                                                "the pad.", blocked))
    if floating_spawns:
        warnings.append(_issue("spawn-floating", "Spawn pads with nothing under them; a player who steps off falls.",
                               floating_spawns))

    route = _route(plan, by_name, blockers, warnings)

    allowed = set(plan.get("assetPolicy", {}).get("allowedAssetIds", []))
    denied = [f"{a['name']} ({a['assetId']})" for a in plan.get("assets", []) if a["assetId"] not in allowed]
    if denied:
        blockers.append(_issue("asset-not-allowed", "Asset ids must be listed in assetPolicy.allowedAssetIds "
                                                    "(supplied by the owner).", denied))
    unsized = [a["name"] for a in plan.get("assets", []) if "approxSize" not in a]
    if unsized:
        warnings.append(_issue("asset-unsized", "Assets without approxSize are not checked for bounds or overlaps.",
                               unsized))
    unanchored = [p["name"] for p in plan.get("parts", []) if p.get("anchored", True) is False]
    if unanchored:
        warnings.append(_issue("unanchored", "Unanchored parts will fall or drift when the game runs.", unanchored))
    floating = [box.name for box in boxes if box.kind == "part" and box.solid and not box.floating
                and box.role not in ("decor", "roof", "hazard") and box.lo[1] > ground + SUPPORT_TOLERANCE
                and box.name not in {n for n in (plan.get("route") or {}).get("waypoints", []) if isinstance(n, str)}
                and not _supported(box, support_index)]
    if floating:
        info.append(_issue("floating", "Anchored parts with nothing under them (fine for platforms on the route; "
                                       "mark intentional ones with floating: true).", floating))

    services = ["Workspace"] + (["Lighting"] if plan.get("lighting") else [])
    if plan.get("lighting"):
        info.append(_issue("lighting", "Applying changes shared Lighting properties, outside the map folder."))
    report = {
        "ok": not blockers, "mapName": map_name, "root": root, "style": plan.get("style", ""),
        "counts": counts, "batches": math.ceil(total / BATCH_SIZE), "services": services,
        "bounds": {"declared": {"min": _round(lo_bound), "max": _round(hi_bound)}, "used": used},
        "route": route, "blockers": blockers, "warnings": warnings, "info": info, "credit": CREDIT,
        "collision_audit": collision_audit,
        "note": "Dry run only: nothing was created. Apply in a throwaway place, inside the managed root.",
    }
    if include_operations and not blockers:
        report["operations"] = operations(plan)
    return report


def _color3(hex_value: str) -> dict:
    return {"type": "Color3", "value": [round(int(hex_value[i:i + 2], 16) / 255, 4) for i in (1, 3, 5)]}


def operations(plan: dict) -> list[dict]:
    """Ordered, Studio-neutral operations with tagged values (Vector3, Color3, Enum)."""
    root = f"{plan.get('rootPath', MANAGED_ROOT).rstrip('/')}/{plan['mapName']}"
    ops: list[dict] = [{"op": "folder", "path": root, "ifExists": "abort"}]
    groups = sorted({item["group"] for key in ("parts", "spawns", "assets") for item in plan.get(key, [])
                     if item.get("group")})
    ops += [{"op": "folder", "path": f"{root}/{group}"} for group in groups]

    def parent(item):
        return f"{root}/{item['group']}" if item.get("group") else root

    for part in plan.get("parts", []):
        props = {"Size": {"type": "Vector3", "value": list(part["size"])},
                 "Position": {"type": "Vector3", "value": list(part["position"])},
                 "Anchored": part.get("anchored", True), "CanCollide": part.get("canCollide", True),
                 "Material": {"type": "Enum", "value": "Enum.Material." + part.get("material", "SmoothPlastic")}}
        if any(part.get("rotation", (0, 0, 0))):
            props["Orientation"] = {"type": "Vector3", "value": list(part["rotation"])}
        if "color" in part:
            props["Color"] = _color3(part["color"])
        if part.get("transparency"):
            props["Transparency"] = part["transparency"]
        ops.append({"op": "create", "class": part.get("class", "Part"), "parent": parent(part), "name": part["name"],
                    "properties": props})
    for spawn in plan.get("spawns", []):
        props = {"Size": {"type": "Vector3", "value": list(SPAWN_SIZE)},
                 "Position": {"type": "Vector3", "value": list(spawn["position"])},
                 "Anchored": True, "Neutral": spawn.get("neutral", True)}
        if "color" in spawn:
            props["Color"] = _color3(spawn["color"])
        ops.append({"op": "create", "class": "SpawnLocation", "parent": parent(spawn), "name": spawn["name"],
                    "properties": props})
    for asset in plan.get("assets", []):
        ops.append({"op": "insert_asset", "assetId": asset["assetId"], "parent": parent(asset), "name": asset["name"],
                    "pivot": {"position": list(asset["position"]), "rotation": list(asset.get("rotation", [0, 0, 0]))}})
    lighting = plan.get("lighting") or {}
    if lighting:
        props = {}
        if "clockTime" in lighting:
            props["ClockTime"] = lighting["clockTime"]
        if "brightness" in lighting:
            props["Brightness"] = lighting["brightness"]
        for key, prop in (("ambient", "Ambient"), ("outdoorAmbient", "OutdoorAmbient")):
            if key in lighting:
                props[prop] = _color3(lighting[key])
        ops.append({"op": "set", "path": "Lighting", "properties": props})
    return ops


def _luau_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(float(value)) if isinstance(value, float) else str(value)
    kind = value["type"]
    if kind == "Vector3":
        return "Vector3.new(" + ", ".join(_luau_value(v) for v in value["value"]) + ")"
    if kind == "Color3":
        return "Color3.new(" + ", ".join(_luau_value(v) for v in value["value"]) + ")"
    if kind == "Enum":
        if not re.fullmatch(r"Enum\.Material\.[A-Za-z]+", value["value"]):
            raise ValueError("unsupported enum value")
        return value["value"]
    raise ValueError(f"unsupported value type {kind}")


def to_luau(plan: dict) -> str:
    """One Luau script (for a throwaway place) that builds the plan under the managed root as a
    single undo step. Refuses plans with blockers. Assets are left to the Studio insert tool."""
    report = dry_run(plan, include_operations=False)
    if not report["ok"]:
        raise ValueError("The plan has blockers; fix them before generating Luau: "
                         + ", ".join(item["code"] for item in report["blockers"]))
    ops = operations(plan)
    root_parts = ops[0]["path"].split("/")   # Workspace/MapDrafts[/...]/<mapName>; names are validated
    lines = [
        "-- Generated by STAR from a map plan (dry run passed). " + CREDIT,
        "-- Run only in a throwaway place. Creates objects under " + "/".join(root_parts) + ".",
        'local ChangeHistoryService = game:GetService("ChangeHistoryService")',
        "local function folder(parent, name)",
        "\tlocal found = parent:FindFirstChild(name)",
        "\tif found then return found end",
        '\tlocal made = Instance.new("Folder")',
        "\tmade.Name = name",
        "\tmade.Parent = parent",
        "\treturn made",
        "end",
        "local folders = {}",
        "local function build()",
        "\tlocal parent = workspace",
    ]
    for name in root_parts[1:-1]:
        lines.append(f'\tparent = folder(parent, "{name}")')
    lines += [
        f'\tif parent:FindFirstChild("{root_parts[-1]}") then',
        f'\t\terror("{root_parts[-1]} already exists in the drafts folder; rename the map or remove the old draft")',
        "\tend",
        f'\tlocal root = folder(parent, "{root_parts[-1]}")',
        f'\tfolders["{ops[0]["path"]}"] = root',
    ]
    for op in ops[1:]:
        if op["op"] == "folder":
            name = op["path"].rsplit("/", 1)[1]
            lines.append(f'\tfolders["{op["path"]}"] = folder(root, "{name}")')
        elif op["op"] == "create":
            lines.append("\tdo")
            lines.append(f'\t\tlocal object = Instance.new("{op["class"]}")')
            lines.append(f'\t\tobject.Name = "{op["name"]}"')
            for prop, value in op["properties"].items():
                lines.append(f"\t\tobject.{prop} = {_luau_value(value)}")
            lines.append(f'\t\tobject.Parent = folders["{op["parent"]}"]')
            lines.append("\tend")
        elif op["op"] == "insert_asset":
            lines.append(f'\t-- asset {op["assetId"]} ("{op["name"]}"): insert with the Studio asset tool')
        elif op["op"] == "set":
            for prop, value in op["properties"].items():
                lines.append(f"\tgame:GetService(\"Lighting\").{prop} = {_luau_value(value)}")
    lines += [
        "end",
        f'local recording = ChangeHistoryService:TryBeginRecording("STAR map plan {plan["mapName"]}")',
        "local ok, err = pcall(build)",
        "if recording then",
        "\tChangeHistoryService:FinishRecording(recording, if ok then Enum.FinishRecordingOperation.Commit "
        "else Enum.FinishRecordingOperation.Cancel)",
        "end",
        "if not ok then error(err) end",
        f'print("STAR map plan built: {plan["mapName"]}")',
    ]
    return "\n".join(lines) + "\n"
