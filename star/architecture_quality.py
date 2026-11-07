"""Pure, offline geometry and Blender-export checks for STAR building packages.

These are engineering checks, not a human visual-quality score. No Blender,
Studio, network, subprocess, or credentials are used by this module.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from pathlib import Path
import re
import struct

from .scene_integrity import audit_scene, audit_scene_contract, audit_shell_blueprint

_MAX_PARTS = 2500
_MAX_TRIANGLES = 100_000
_MAX_GLB_BYTES = 64 * 1024 * 1024
_ROLE = re.compile(r"#[0-9a-fA-F]{6}\Z")


def _triplet(value) -> bool:
    return (type(value) in (list, tuple) and len(value) == 3
            and all(type(v) in (int, float) and isfinite(v) and abs(v) <= 10000
                    for v in value))


def _diagnostics(plan: object) -> tuple[list[str], list[str], dict]:
    errors, warnings = [], []
    metrics = {"parts": 0, "triangles": 0, "material_groups": 0}
    if type(plan) is not dict or plan.get("schema_version") != 1:
        return ["Invalid or unsupported building-plan schema"], warnings, metrics
    palette = plan.get("palette")
    if (type(palette) is not dict or not 1 <= len(palette) <= 12
            or any(type(k) is not str or not k.isidentifier() or type(v) is not str
                   or not _ROLE.fullmatch(v) for k, v in palette.items())):
        errors.append("Palette must have 1..12 named hex-color materials")
        palette = {}
    parts = plan.get("parts")
    if type(parts) is not list or not 1 <= len(parts) <= _MAX_PARTS:
        return errors + ["Part list missing or exceeds 2,500 items"], warnings, metrics
    metrics["parts"] = len(parts)
    metrics["material_groups"] = len(palette)
    seen = set()
    for index, part in enumerate(parts):
        if type(part) is not dict:
            errors.append(f"Part {index} is not an object")
            continue
        name = part.get("name")
        if type(name) is not str or not 1 <= len(name) <= 100 or not re.fullmatch(r"[a-zA-Z0-9_]+", name):
            errors.append(f"Part {index} has an invalid name")
        elif name in seen:
            errors.append(f"Duplicate part name: {name}")
        else:
            seen.add(name)
        material = part.get("material")
        if type(material) is not str or material not in palette:
            errors.append(f"Part {index} uses an unknown material")
        kind = part.get("kind")
        if kind == "box":
            if not _triplet(part.get("center")) or not _triplet(part.get("size")):
                errors.append(f"Box {index} has invalid coordinates")
            elif any(v < 0.01 for v in part["size"]):
                errors.append(f"Box {index} has a near-zero dimension")
            angle = part.get("angle_y")
            if (not isinstance(angle, (int, float)) or isinstance(angle, bool) or not isfinite(angle)
                    or abs(angle) > 180):
                errors.append(f"Box {index} has an invalid rotation")
            metrics["triangles"] += 12
        elif kind == "triangle_prism":
            vertices = part.get("vertices")
            if type(vertices) is not list or len(vertices) != 6 or not all(_triplet(v) for v in vertices):
                errors.append(f"Prism {index} requires six finite 3D vertices")
            metrics["triangles"] += 8
        else:
            errors.append(f"Part {index} has an unsupported geometry type")
        if len(errors) >= 25:
            errors.append("Further invalid parts omitted")
            break
    if metrics["triangles"] > _MAX_TRIANGLES:
        errors.append("Geometry exceeds the 100,000-triangle prototype budget")
    if "entry_door" not in seen:
        errors.append("Exterior entry is missing")
    if not any(name.endswith("_glazing") for name in seen):
        warnings.append("No facade glazing in this shell")
    brief = plan.get("brief") or {}
    if isinstance(brief, dict) and brief.get("floors", 1) > 1:
        warnings.append("Upper floors have no verified stairs or accessible internal path")
    warnings.append("Doors/glass are static visual placeholders; collision must be set in Studio")
    warnings.append("Surface texture quality, scale, navigation and mobile performance need native review")
    return errors, warnings, metrics


def audit_plan(plan: object) -> dict:
    """Structured fail-closed geometry gate. Never calls output 'AAA' or 'accepted'."""
    errors, warnings, metrics = _diagnostics(plan)
    supplied = plan.get("metrics") if isinstance(plan, dict) else None
    if isinstance(supplied, dict):
        for key, generated in (("parts_before_material_batch", metrics["parts"]),
                               ("estimated_triangles", metrics["triangles"]),
                               ("material_groups", metrics["material_groups"])):
            if supplied.get(key) != generated:
                errors.append(f"Metric mismatch: {key}")
    scene = audit_scene(plan.get("parts")) if isinstance(plan, dict) else None
    blueprint = audit_shell_blueprint(plan)
    contract = audit_scene_contract(plan)
    for gate in (scene, blueprint, contract):
        if gate is not None:
            errors.extend(f"{item['code']}: {', '.join(item['parts'])}: {item['message']}"
                          for item in gate["issues"])
    return {
        "valid": not errors,
        "status": "blocked" if errors else "static_checks_passed_visual_review_required",
        "metrics": metrics,
        "errors": errors,
        "warnings": warnings,
        "scene_integrity": scene,
        "blueprint_integrity": blueprint,
        "scene_contract": contract,
    }


def inspect_glb(path: Path, *, expected_material_roles=()) -> dict:
    """Confirm the exported .glb has a consistent glTF 2.0 header and mesh hierarchy.

    Does not claim successful import, shading, manifold topology or collision.
    """
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("GLB output must be an ordinary existing file")
    size = path.stat().st_size
    if not 28 <= size <= _MAX_GLB_BYTES:
        raise ValueError("GLB file size outside safe bounds")
    with path.open("rb") as stream:
        magic, version, total = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF" or version != 2 or total != size:
            raise ValueError("Invalid glTF 2.0 binary header or declared length")
        json_len, chunk_type = struct.unpack("<I4s", stream.read(8))
        if chunk_type != b"JSON" or json_len < 2 or json_len > min(size - 20, 4 * 1024 * 1024):
            raise ValueError("Missing or oversized GLB JSON chunk")
        data = stream.read(json_len)
        if len(data) != json_len:
            raise ValueError("Truncated GLB JSON chunk")
    try:
        scene = json.loads(data.decode("utf-8").rstrip(" \t\r\n\x00"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Malformed GLB JSON scene") from exc
    if not isinstance(scene, dict) or not isinstance(scene.get("asset"), dict) \
            or scene["asset"].get("version") != "2.0":
        raise ValueError("Missing glTF 2.0 asset metadata")
    meshes, nodes = scene.get("meshes"), scene.get("nodes")
    if not isinstance(meshes, list) or not 1 <= len(meshes) <= 12:
        raise ValueError("GLB must contain 1..12 material-batched meshes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 128:
        raise ValueError("GLB hierarchy is missing or unexpectedly large")
    names = [m.get("name") for m in meshes if isinstance(m, dict)]
    if len(names) != len(meshes) or any(not isinstance(n, str) for n in names):
        raise ValueError("Unnamed or malformed mesh in GLB")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate GLB mesh names")
    wanted = {f"STAR_{role}_mesh" for role in expected_material_roles}
    if wanted and not wanted <= set(names):
        raise ValueError("GLB is missing expected stable material mesh names")
    if any(not isinstance(m.get("primitives"), list) or not m["primitives"]
           for m in meshes):
        raise ValueError("GLB mesh without geometry primitives")
    return {
        "format": "glTF-2.0-binary",
        "bytes": size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mesh_names": names,
        "mesh_count": len(meshes),
        "validated": "GLB container and mesh manifest only",
        "studio_imported": False,
        "visual_quality_verified": False,
    }


def collision_hints(plan: dict) -> dict:
    """List world-space *candidate* box colliders with door/window gaps intact.

    Blender coordinates are Z-up; the importer transform is not known until
    Studio import has been verified. Never auto-place these into an open place.
    """
    audit = audit_plan(plan)
    if not audit["valid"]:
        raise ValueError("Cannot derive collisions from a rejected building plan")
    boxes = []
    for part in plan["parts"]:
        name = part["name"]
        if part["kind"] == "box" and (
                part["material"] == "wall" or name == "foundation" or name.startswith("slab_")):
            boxes.append({"name": name, "center": part["center"],
                          "size": part["size"], "angle_y": part["angle_y"]})
    return {
        "coordinate_space": "Blender XYZ, Z-up, studs",
        "verified_in_studio": False, "automatic_studio_placement": False,
        "boxes": boxes, "box_count": len(boxes),
        "excluded": ["visual glazing", "visual door", "trim", "complex roof", "gable prisms"],
        "operator_note": (
            "Inspect model orientation/position after import. Reconcile the Blender-to-Roblox "
            "coordinate transform before placing anchored invisible colliders; make openings "
            "walkable and test with a real avatar. Never enable collisions on the fused visual mesh."
        ),
    }


def design_summary(plan: dict) -> dict:
    """Small, truthful model-facing summary, not thousands of mesh coordinates."""
    audit = audit_plan(plan)
    brief = plan["brief"]
    return {
        "name": brief["name"], "style": brief["style"],
        "dimensions_studs": [brief["width_studs"], brief["depth_studs"],
                             brief["floors"] * brief["story_height_studs"]],
        "floors": brief["floors"], "facade_bays": brief["bays"],
        "roof": "gable" if any(p.get("name") == "roof_left" for p in plan["parts"]) else "flat",
        "openings": {"entrances": sum(p["name"] == "entry_door" for p in plan["parts"]),
                     "glazed_windows": sum(p["name"].endswith("_glazing") for p in plan["parts"])},
        "palette": plan["palette"], "audit": audit,
        "candidate_collision_boxes": collision_hints(plan)["box_count"] if audit["valid"] else 0,
        "style_grammar": plan.get("style_grammar", ""),
        "output": "PLAN_ONLY: not modeled/rendered/imported into Blender or Roblox Studio",
    }
