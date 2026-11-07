"""Read-only secondary-motion rig preflight. No exports, repairs, or auto execution.

Ordinary Python: python scripts/secondary_rig_audit.py --snapshot selected.json
Blender: blender --background --disable-autoexec selected.blend --python
scripts/secondary_rig_audit.py -- --blender
Opening an untrusted .blend is not a sandbox. Use a disposable trusted environment.
The JSON snapshot is an inspection summary, never proof of a native render/test.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

MAX_BONES = 512
MAX_VERTICES = 100_000
MAX_BYTES = 8_000_000


def number(value: object) -> bool:
    return type(value) in (int, float) and abs(value) <= 1e12 and math.isfinite(value)


def audit(snapshot: Any, *, max_influences: int = 4) -> dict:
    """Check a bounded host-extracted snapshot. Does not load external assets."""
    if type(max_influences) is not int or not 1 <= max_influences <= 16:
        raise ValueError("Invalid influence budget")
    if not isinstance(snapshot, dict):
        raise ValueError("Expected a rig snapshot object")
    bones, vertices = snapshot.get("bones"), snapshot.get("vertices")
    if not isinstance(bones, list) or not 1 <= len(bones) <= MAX_BONES:
        raise ValueError("Provide 1..512 bones")
    if not isinstance(vertices, list) or len(vertices) > MAX_VERTICES:
        raise ValueError("Vertex list is missing or over budget")
    issues: list[dict] = []
    def issue(code: str, location: str, severity: str = "error") -> None:
        if len(issues) < 200:
            issues.append({"code": code, "location": location, "severity": severity})
    errors = 0
    parents: dict[str, str | None] = {}
    for i, bone in enumerate(bones):
        if not isinstance(bone, dict):
            raise ValueError("Invalid bone row")
        name, parent, length = bone.get("name"), bone.get("parent"), bone.get("length")
        if not isinstance(name, str) or not 1 <= len(name) <= 128:
            raise ValueError("Invalid bone name")
        if parent is not None and (not isinstance(parent, str) or not 1 <= len(parent) <= 128):
            raise ValueError("Invalid parent name")
        if name in parents:
            issue("duplicate_bone", f"bones/{i}"); errors += 1
        parents[name] = parent
        if not number(length) or not 1e-8 < length <= 1e6:
            issue("degenerate_bone", f"bones/{i}"); errors += 1
    for name, parent in parents.items():
        if parent is not None and parent not in parents:
            issue("missing_parent", name); errors += 1
        seen = {name}
        while parent is not None and parent in parents:
            if parent in seen:
                issue("parent_cycle", name); errors += 1; break
            seen.add(parent); parent = parents[parent]
    scale = snapshot.get("scale")
    if not isinstance(scale, list) or len(scale) != 3 or not all(number(v) and abs(v) <= 1e6 for v in scale):
        raise ValueError("Scale must be three finite numbers")
    if any(v <= 0 for v in scale):
        issue("nonpositive_scale", "scale"); errors += 1
    elif any(abs(v-1) > 1e-5 for v in scale):
        issue("unapplied_scale_review", "scale", "warning")
    if not vertices:
        issue("empty_mesh", "vertices"); errors += 1
    counts = {"unweighted": 0, "too_many_influences": 0, "unnormalized": 0, "invalid_weights": 0}
    for i, weights in enumerate(vertices):
        if not isinstance(weights, dict) or len(weights) > MAX_BONES:
            raise ValueError("Invalid vertex weight row")
        valid = True
        for bone, weight in weights.items():
            if bone not in parents or not number(weight) or not 0 <= weight <= 1:
                valid = False
        if not valid:
            counts["invalid_weights"] += 1; issue("invalid_weights", f"vertices/{i}"); errors += 1; continue
        nonzero = sum(w > 1e-8 for w in weights.values())
        total = sum(weights.values())
        if nonzero == 0:
            counts["unweighted"] += 1; issue("unweighted_vertex", f"vertices/{i}"); errors += 1
        elif nonzero > max_influences:
            counts["too_many_influences"] += 1; issue("influence_budget", f"vertices/{i}"); errors += 1
        if nonzero and abs(total-1) > 1e-4:
            counts["unnormalized"] += 1; issue("weight_sum_review", f"vertices/{i}", "warning")
    return {"structural_ok": errors == 0, "errors": errors, "bones": len(bones), "vertices": len(vertices),
            "counts": counts, "findings": issues, "findings_capped": len(issues) == 200,
            "max_influences": max_influences, "native_motion_tested": False,
            "visual_quality_verified": False, "modified": False}


def blender_snapshot() -> dict:
    """Extract exactly one selected mesh and one armature; refuse ambiguity."""
    import bpy  # type: ignore[import-not-found]  # deliberately optional
    meshes = [o for o in bpy.context.selected_objects if o.type == "MESH"]
    if len(meshes) != 1:
        raise ValueError("Select exactly one mesh before saving the inspection copy")
    mesh = meshes[0]
    armatures = [m.object for m in mesh.modifiers if m.type == "ARMATURE" and m.object is not None]
    if len(armatures) != 1 or armatures[0].type != "ARMATURE":
        raise ValueError("Exactly one assigned armature is required")
    armature = armatures[0]
    if len(armature.data.bones) > MAX_BONES or len(mesh.data.vertices) > MAX_VERTICES:
        raise ValueError("Selected rig exceeds inspection budget")
    names = {b.name for b in armature.data.bones}
    groups = {g.index: g.name for g in mesh.vertex_groups if g.name in names}
    return {"bones": [{"name": b.name, "parent": b.parent.name if b.parent else None, "length": b.length}
                      for b in armature.data.bones],
            "vertices": [{groups[g.group]: g.weight for g in v.groups if g.group in groups}
                         for v in mesh.data.vertices],
            "scale": [float(v) for v in mesh.scale],
            "armature_scale": [float(v) for v in armature.scale]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--snapshot", type=Path)
    group.add_argument("--blender", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.blender:
            value = blender_snapshot()
        else:
            with args.snapshot.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Snapshot exceeds inspection budget")
            value = json.loads(raw)
        result = audit(value)
        if args.blender:
            arm_scale = value["armature_scale"]
            result["armature_scale_review"] = any(abs(v-1) > 1e-5 for v in arm_scale)
        result["source"] = "blender_data_read" if args.blender else "untrusted_snapshot"
    except (OSError, ValueError, TypeError, ImportError, OverflowError):
        parser.error("Rig input is invalid, unavailable or exceeds the inspection budget")
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["structural_ok"] else 1

if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else sys.argv[1:]
    raise SystemExit(main(arguments))
