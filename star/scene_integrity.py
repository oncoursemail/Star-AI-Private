"""Offline STAR scene geometry quality gate for bounded Blender-Z-up building plans.

No external calls, Studio mutations, generative code execution, or claims of
rendered quality. Rotations use the existing architecture plan's Blender Y axis.
AABB broad phase + exact SAT in the XZ plane prevents false collision alarms
for rotated gable-roof parts. This is a geometric *preflight*, not physics.
"""
from __future__ import annotations

from copy import deepcopy
from math import cos, isfinite, radians, sin
from typing import Any, TypeGuard

_MAX_ISSUES = 60
_EPS = 0.025


def _xyz(value: Any, *, positive: bool = False) -> bool:
    return (type(value) in (list, tuple) and len(value) == 3
            and all(type(n) in (int, float) and isfinite(n)
                    and (0.01 <= n <= 10_000 if positive else abs(n) <= 10_000)
                    for n in value))


def _box(part: object) -> TypeGuard[dict[str, Any]]:
    return (isinstance(part, dict) and part.get("kind") == "box"
            and _xyz(part.get("center")) and _xyz(part.get("size"), positive=True)
            and type(part.get("angle_y")) in (int, float)
            and isfinite(part["angle_y"]) and abs(part["angle_y"]) <= 180)


def _basis(box: dict) -> tuple[tuple[float, float], tuple[float, float]]:
    """Local X and Z directions projected into world XZ (Blender Y rotation)."""
    angle = radians(box["angle_y"])
    c, s = cos(angle), sin(angle)
    return ((c, -s), (s, c))


def _aabb(box: dict) -> tuple[float, float, float, float, float, float]:
    x, y, z = box["center"]
    dx, dy, dz = (v / 2 for v in box["size"])
    u, v = _basis(box)
    rx = abs(u[0]) * dx + abs(v[0]) * dz
    rz = abs(u[1]) * dx + abs(v[1]) * dz
    return (x - rx, x + rx, y - dy, y + dy, z - rz, z + rz)


def _penetration(a: dict, b: dict) -> float:
    """Oriented-box SAT: Y intervals and all four in-plane separating axes.

    Returns positive overlap depth, or zero when boxes only touch/separate.
    This geometry approximation does not replace Studio's mesh/physics query.
    """
    dy = (a["size"][1] + b["size"][1]) / 2 - abs(a["center"][1] - b["center"][1])
    if dy <= _EPS:
        return 0.0
    ca, cb = a["center"], b["center"]
    ua, va = _basis(a)
    ub, vb = _basis(b)
    delta = (cb[0] - ca[0], cb[2] - ca[2])
    least = dy
    for axis in (ua, va, ub, vb):
        ra = (abs(axis[0] * ua[0] + axis[1] * ua[1]) * a["size"][0]
              + abs(axis[0] * va[0] + axis[1] * va[1]) * a["size"][2]) / 2
        rb = (abs(axis[0] * ub[0] + axis[1] * ub[1]) * b["size"][0]
              + abs(axis[0] * vb[0] + axis[1] * vb[1]) * b["size"][2]) / 2
        depth = ra + rb - abs(delta[0] * axis[0] + delta[1] * axis[1])
        if depth <= _EPS:
            return 0.0
        least = min(least, depth)
    return least


def _match_structure(a: dict, b: dict) -> bool:
    # Perpendicular front and side walls overlap at structurally intended corners.
    ax = a["size"][0] >= a["size"][1]
    bx = b["size"][0] >= b["size"][1]
    return ax == bx


def _textures(part: dict, issue) -> None:
    texture = part.get("texture")
    if texture is None:
        return
    name = part.get("name", "<unnamed>")
    if not isinstance(texture, dict):
        issue("texture_metadata", [name], "Texture binding must be an object")
        return
    tile: Any = texture.get("tile_studs")
    if (type(tile) not in (int, float) or not isfinite(tile)
            or not 0.05 <= tile <= 128):
        issue("texture_scale", [name], "Texture tile_studs must be finite, 0.05..128")
    maps = ("color", "normal", "roughness", "metalness", "emissive")
    if not any(k in texture for k in maps):
        issue("texture_missing", [name], "No image map was bound to textured geometry")
    for kind in maps:
        if kind in texture:
            ref = texture[kind]
            if (not isinstance(ref, str) or not ref.startswith("rbxassetid://")
                    or not ref[13:].isdigit() or int(ref[13:]) <= 0):
                issue("texture_asset", [name], f"Invalid {kind} image asset reference")
    # UV seam positions / tangent-space encoding cannot be proved by a text manifest.


def audit_scene(parts: object) -> dict:
    """Find shifted props, duplicate geometry, overlapping solids and texture metadata defects.

    Parts are the existing architecture-plan boxes/prisms. Optional authoring
    intent for props: role='prop', placement={target_center:[x,y,z],
    max_offset_studs:float, support_name:str, support_mode:'vertical'|'attached'}.
    Normal trim/roof contacts are intentional. Error details identify exact parts.
    """
    issues: list[dict[str, Any]] = []
    comparisons = 0

    def issue(code: str, names: list[str], message: str) -> None:
        if len(issues) < _MAX_ISSUES:
            issues.append({"code": code, "parts": names, "message": message})

    if not isinstance(parts, list) or not 1 <= len(parts) <= 2500:
        issue("invalid_scene", [], "Scene must contain 1..2500 parts")
        return {"valid": False, "issues": issues, "pairs_checked": 0, "boxes_checked": 0}
    boxes = [p for p in parts if _box(p)]
    names = {p["name"]: p for p in parts if isinstance(p, dict) and isinstance(p.get("name"), str)}
    signatures = {}
    for part in boxes:
        name = part.get("name", "<unnamed>")
        _textures(part, issue)
        sig = (tuple(round(float(v), 4) for v in part["center"]),
               tuple(round(float(v), 4) for v in part["size"]),
               round(float(part["angle_y"]), 4))
        # Distinct instances with identical solids cause flicker (z-fighting)
        # even if the bound materials are different.
        if sig in signatures:
            issue("duplicate_geometry", [signatures[sig], name],
                  "Identical geometry at the same transform; remove or intentionally offset one")
        else:
            signatures[sig] = name

        placement = part.get("placement")
        if placement is None:
            if part.get("role") == "prop":
                issue("unanchored_prop", [name], "Prop has no expected placement or support contract")
            continue
        if not isinstance(placement, dict):
            issue("placement_metadata", [name], "Placement metadata is not an object")
            continue
        intended: Any = placement.get("target_center")
        limit: Any = placement.get("max_offset_studs", 0.1)
        if (not _xyz(intended) or type(limit) not in (int, float)
                or not isfinite(limit) or not 0 <= limit <= 5):
            issue("placement_metadata", [name], "Invalid expected prop center or tolerance")
            continue
        distance = sum((a - b) ** 2 for a, b in zip(part["center"], intended)) ** 0.5
        if distance > limit + _EPS:
            issue("misplaced_prop", [name],
                  f"Prop deviates {distance:.3f} studs from its authored anchor (limit {limit:.3f})")
        support = placement.get("support_name")
        if support is None:
            if part.get("role") == "prop":
                issue("unattached_prop", [name], "Prop has no declared support_name")
            continue
        other = names.get(support)
        if other is part or not _box(other):
            issue("missing_support", [name, str(support)], "Declared prop support is missing or invalid")
            continue
        mode = placement.get("support_mode", "vertical")
        if mode not in {"vertical", "attached"}:
            issue("placement_metadata", [name], "Unsupported prop support mode")
            continue
        if mode == "vertical":
            a, b = _aabb(part), _aabb(other)
            gap = a[4] - b[5]  # prop bottom above support top
            horiz = min(a[1], b[1]) - max(a[0], b[0])
            depth = min(a[3], b[3]) - max(a[2], b[2])
            if abs(gap) > 0.12 or horiz <= _EPS or depth <= _EPS:
                issue("floating_prop", [name, support],
                      f"Prop must rest on its support; vertical separation {gap:.3f} studs")
        elif _penetration(part, other) <= _EPS:
            a, b = _aabb(part), _aabb(other)
            gaps = [max(0.0, max(a[i], b[i]) - min(a[i + 1], b[i + 1]))
                    for i in (0, 2, 4)]
            if max(gaps) > 0.12:
                issue("unattached_prop", [name, support],
                      "Prop is separated from its authored attachment surface")

    # Plane sweep on X is cheaper than brute-force all pairs, and exact
    # OBB SAT runs only on broad-phase candidates.
    spans = sorted(((_aabb(p), p) for p in boxes), key=lambda item: item[0][0])
    active: list[tuple[tuple[float, ...], dict]] = []
    for bounds, part in spans:
        active = [(box, candidate) for box, candidate in active if box[1] > bounds[0] + _EPS]
        for obounds, other in active:
            if (obounds[3] <= bounds[2] + _EPS or bounds[3] <= obounds[2] + _EPS
                    or obounds[5] <= bounds[4] + _EPS or bounds[5] <= obounds[4] + _EPS):
                continue
            # Expected structure/material trim contacts are deliberate, not flaws.
            a_mat, b_mat = part.get("material"), other.get("material")
            a_role, b_role = part.get("role"), other.get("role")
            if a_role != "prop" and b_role != "prop" and (
                    a_mat in {"trim", "roof"} or b_mat in {"trim", "roof"}
                    or "foundation" in (part.get("name"), other.get("name"))
                    or str(part.get("name", "")).startswith("slab_")
                    or str(other.get("name", "")).startswith("slab_")):
                continue
            classification = None
            if a_role == "prop" or b_role == "prop":
                # Support contact is not an interpenetration unless overlap exceeds 0.15.
                classification = "prop_intersection"
            elif a_mat == b_mat == "wall" and _match_structure(part, other):
                classification = "overlapping_walls"
            elif ((a_mat in {"door", "glass"} and b_mat == "wall")
                  or (b_mat in {"door", "glass"} and a_mat == "wall")):
                classification = "blocked_opening"
            elif a_mat in {"door", "glass"} and b_mat in {"door", "glass"}:
                classification = "overlapping_openings"
            if classification is None:
                continue
            comparisons += 1
            penetration = _penetration(part, other)
            if penetration <= (0.15 if classification == "prop_intersection" else _EPS):
                continue
            # Corner masonry wall joints are perpendicular and filtered above.
            issue(classification, [str(part.get("name")), str(other.get("name"))],
                  f"Unintended solid penetration of approximately {penetration:.3f} studs")
        active.append((bounds, part))
    return {"valid": not issues, "issues": issues, "pairs_checked": comparisons,
            "boxes_checked": len(boxes), "quality_claim": "geometry_only_not_render_or_playtest"}


def audit_shell_blueprint(plan: object) -> dict:
    """Compare a procedural architecture shell against its deterministic brief.

    A missing wall, door or roof panel is rejected even when JSON and triangle
    counts still look plausible. Extras require explicit, reviewable prop intent.
    """
    issues = []

    def add(code: str, names: list[str], message: str) -> None:
        if len(issues) < _MAX_ISSUES:
            issues.append({"code": code, "parts": names, "message": message})

    if not isinstance(plan, dict) or not isinstance(plan.get("brief"), dict):
        add("missing_brief", [], "Geometry cannot be checked against a building brief")
        return {"valid": False, "issues": issues}
    try:
        from .architecture_pipeline import make_plan, validate_brief
        expected = make_plan(validate_brief(plan["brief"]))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        add("invalid_brief", [], f"Building brief is invalid: {type(exc).__name__}")
        return {"valid": False, "issues": issues}
    generated = {part["name"]: part for part in expected["parts"]}
    actual = plan.get("parts")
    if not isinstance(actual, list):
        add("missing_parts", [], "No parts were supplied")
        return {"valid": False, "issues": issues}
    present = {p["name"]: p for p in actual
               if isinstance(p, dict) and isinstance(p.get("name"), str)}
    for name, target in generated.items():
        current = present.get(name)
        if current is None:
            add("missing_component", [name], "A required shell component is missing")
            continue
        if current.get("kind") != target.get("kind") or current.get("material") != target.get("material"):
            add("wrong_component", [name], "Shell role or geometry type does not match the authored kit")
            continue
        keys = ("center", "size", "angle_y") if target["kind"] == "box" else ("vertices",)
        if any(current.get(key) != target.get(key) for key in keys):
            add("misaligned_component", [name], "Shell transform differs from its authored blueprint")
    for name, part in present.items():
        if name not in generated and (part.get("role") != "prop" or not isinstance(part.get("placement"), dict)):
            add("unplanned_object", [name], "Extra geometry requires a declared prop role and placement contract")
    return {"valid": not issues, "issues": issues, "expected_components": len(generated),
            "present_components": len(present)}


def audit_scene_contract(plan: object) -> dict:
    """Check required custom objects and authored connections (never infer intent).

    Optional plan.scene_contract:
      required: [{name, center, size, tolerance_studs?}]
      connections: [{first, second, max_gap_studs?}]
    Values are Blender XYZ studs. The source of this contract must be
    owner/artist-reviewed; model-authored requirements are not independent proof.
    """
    issues: list[dict] = []

    def add(code: str, names: list[str], message: str) -> None:
        if len(issues) < _MAX_ISSUES:
            issues.append({"code": code, "parts": names, "message": message})

    if not isinstance(plan, dict):
        add("invalid_scene", [], "Scene must be an object")
        return {"valid": False, "present": False, "issues": issues}
    contract = plan.get("scene_contract")
    if contract is None:
        return {"valid": True, "present": False, "issues": [], "status": "no_custom_contract"}
    if (not isinstance(contract, dict) or set(contract) - {"required", "connections"}
            or not isinstance(contract.get("required", []), list)
            or len(contract.get("required", [])) > 500
            or not isinstance(contract.get("connections", []), list)
            or len(contract.get("connections", [])) > 1000):
        add("invalid_contract", [], "Scene contract is malformed or exceeds budgets")
        return {"valid": False, "present": True, "issues": issues}
    parts = plan.get("parts")
    if not isinstance(parts, list):
        add("invalid_scene", [], "Scene parts are missing")
        return {"valid": False, "present": True, "issues": issues}
    by_name = {p["name"]: p for p in parts
               if isinstance(p, dict) and isinstance(p.get("name"), str)}
    checked = set()
    for required in contract.get("required", []):
        if not isinstance(required, dict):
            add("invalid_contract", [], "Required part record must be an object")
            continue
        name = required.get("name")
        center: Any = required.get("center")
        size: Any = required.get("size")
        tolerance = required.get("tolerance_studs", 0.1)
        if (not isinstance(name, str) or not 1 <= len(name) <= 100
                or name in checked or not _xyz(center) or not _xyz(size, positive=True)
                or type(tolerance) not in (int, float) or not isfinite(tolerance)
                or not 0 <= tolerance <= 5 or set(required) -
                {"name", "center", "size", "tolerance_studs"}):
            add("invalid_contract", [str(name)], "Invalid or repeated required part specification")
            continue
        checked.add(name)
        actual = by_name.get(name)
        if actual is None:
            add("missing_required_prop", [name], "Required object from the design contract is absent")
        elif not _box(actual):
            add("invalid_required_prop", [name], "Required object is not a valid box")
        else:
            displacement = sum((a - b) ** 2 for a, b in zip(actual["center"], center)) ** .5
            sizing = max(abs(a - b) for a, b in zip(actual["size"], size))
            if displacement > tolerance + _EPS or sizing > tolerance + _EPS:
                add("wrong_required_placement", [name],
                    f"Required object center/size differs from blueprint (offset {displacement:.3f}, "
                    f"size discrepancy {sizing:.3f} studs)")
    for link in contract.get("connections", []):
        if not isinstance(link, dict):
            add("invalid_contract", [], "Connection record must be an object")
            continue
        first, second = link.get("first"), link.get("second")
        allowance = link.get("max_gap_studs", .12)
        if (not isinstance(first, str) or not isinstance(second, str) or first == second
                or type(allowance) not in (int, float) or not isfinite(allowance)
                or not 0 <= allowance <= 3 or set(link) -
                {"first", "second", "max_gap_studs"}):
            add("invalid_contract", [str(first), str(second)], "Invalid connection specification")
            continue
        a, b = by_name.get(first), by_name.get(second)
        if not _box(a) or not _box(b):
            add("missing_connection", [first, second], "One or both required connected objects are absent")
            continue
        pa, pb = _aabb(a), _aabb(b)
        axis_gaps = [max(0.0, max(pa[i], pb[i]) - min(pa[i + 1], pb[i + 1]))
                     for i in (0, 2, 4)]
        gap = sum(v * v for v in axis_gaps) ** .5
        if gap > allowance + _EPS:
            add("unattached_component", [first, second],
                f"Declared connected components have gap {gap:.3f} studs (limit {allowance:.3f})")
    return {"valid": not issues, "present": True, "issues": issues,
            "status": "contract_checks_passed" if not issues else "contract_blocked"}


def propose_shell_repair(plan: dict) -> dict:
    """Return an *offline proposal*, not an edit to a live Blender or Studio scene.

    A procedure-owned component may be restored from the trusted deterministic
    brief. Unknown/unplanned objects are never silently removed or repositioned.
    Every repaired scene must pass both geometric checks before export.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("parts"), list):
        raise ValueError("A building plan with parts is required")
    from .architecture_pipeline import make_plan, validate_brief
    expected = make_plan(validate_brief(plan.get("brief")))
    new_plan = deepcopy(plan)
    names = [p.get("name") for p in plan["parts"] if isinstance(p, dict)]
    if len(names) != len(plan["parts"]) or len(names) != len(set(names)):
        raise ValueError("Ambiguous or duplicate part IDs cannot be repaired safely")
    by_name = {p["name"]: p for p in new_plan["parts"]}
    changes = []
    for part in expected["parts"]:
        existing = by_name.get(part["name"])
        if existing is None:
            new_plan["parts"].append(deepcopy(part))
            changes.append({"name": part["name"], "action": "restore_missing"})
        else:
            fields = ("kind", "material", "center", "size", "angle_y", "vertices")
            if any(existing.get(key) != part.get(key) for key in fields):
                # Do not rewrite bespoke metadata; only restore known geometry.
                for key in fields:
                    if key in part:
                        existing[key] = deepcopy(part[key])
                    else:
                        existing.pop(key, None)
                changes.append({"name": part["name"], "action": "restore_blueprint"})
    new_plan["metrics"] = {
        "parts_before_material_batch": len(new_plan["parts"]),
        "estimated_triangles": sum(12 if p.get("kind") == "box" else 8
                                   for p in new_plan["parts"] if isinstance(p, dict)),
        "material_groups": len(new_plan.get("palette", {})),
    }
    from .architecture_quality import audit_plan
    after = audit_plan(new_plan)
    return {"proposed_plan": new_plan, "changes": changes, "proposed_audit": after,
            "status": "proposed_not_applied" if after["valid"] else "blocked_review_required",
            "studio_changed": False, "original_unchanged": True}
