"""STAR Scene Topology: bounded, yaw-aware box/assembly quality preflight.

Checks authored/observed manifests, not the actual Roblox Studio scene. The
occupied volume of MeshParts, Unions and arbitrary tilted geometry needs real
Studio physics queries; bounding boxes alone cannot certify collision quality.
Nothing in this module edits, runs, publishes, or grants access to a place.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, isfinite, radians, sin
import re
from typing import Any

MAX_PARTS = 128
MAX_CONSTRAINTS = 128
EPSILON = 0.02
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")


@dataclass(frozen=True)
class Box:
    name: str
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    yaw_degrees: float
    solid: bool

    @property
    def axes(self) -> tuple[tuple[float, float], tuple[float, float]]:
        angle = radians(self.yaw_degrees)
        a, b = cos(angle), sin(angle)
        return (a, b), (-b, a)


def _name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(f"{field} must be a short object identifier")
    return value


def _num(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    n = float(value)
    if abs(n) > 100_000:
        raise ValueError(f"{field} out of supported range")
    return n


def _triple(value: Any, field: str, positive: bool = False) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field} must be three numbers")
    a, b, c = _num(value[0], field), _num(value[1], field), _num(value[2], field)
    if positive and min(a, b, c) <= 0:
        raise ValueError(f"{field} requires positive dimensions")
    return a, b, c


def _box(value: Any, field: str) -> Box:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a part record")
    solid = value.get("solid", True)
    if type(solid) is not bool:
        raise ValueError(f"{field}.solid must be boolean")
    return Box(_name(value.get("id"), f"{field}.id"),
               _triple(value.get("center"), f"{field}.center"),
               _triple(value.get("size"), f"{field}.size", True),
               _num(value.get("yaw_degrees", 0), f"{field}.yaw_degrees"), solid)


def _records(value: Any, field: str, maximum: int = MAX_CONSTRAINTS) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{field} must be a bounded list")
    return value


def _projection_radius(box: Box, axis: tuple[float, float]) -> float:
    right, front = box.axes
    return (abs(right[0] * axis[0] + right[1] * axis[1]) * box.size[0] / 2
            + abs(front[0] * axis[0] + front[1] * axis[1]) * box.size[2] / 2)


def _horizontal_separation(a: Box, b: Box) -> float:
    """Largest SAT separating-axis distance, negative for horizontal overlap."""
    cx, cz = b.center[0] - a.center[0], b.center[2] - a.center[2]
    return max(
        abs(cx * axis[0] + cz * axis[1]) - _projection_radius(a, axis) - _projection_radius(b, axis)
        for axis in (*a.axes, *b.axes)
    )


def _vertical_separation(a: Box, b: Box) -> float:
    return abs(a.center[1] - b.center[1]) - (a.size[1] + b.size[1]) / 2


def _penetrates(a: Box, b: Box) -> bool:
    return _vertical_separation(a, b) < -EPSILON and _horizontal_separation(a, b) < -EPSILON


def _separation(a: Box, b: Box) -> float:
    """Conservative face-gap lower-bound for yaw boxes, not mesh distance."""
    return max(0.0, _horizontal_separation(a, b), _vertical_separation(a, b))


def _pair(value: Any, field: str) -> frozenset[str]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must contain two IDs")
    a, b = _name(value[0], field), _name(value[1], field)
    if a == b:
        raise ValueError(f"{field} cannot pair an object with itself")
    return frozenset((a, b))


def audit_scene(packet: dict[str, Any]) -> dict[str, Any]:
    """Report missing props, unexpected box penetrations, floating supports,
    unattached joins, and obstructed passage envelopes. Zero warnings never
    means 'perfect'; actual engine observations and human art review are needed.
    """
    if not isinstance(packet, dict):
        raise ValueError("scene must be a mapping")
    project = _name(packet.get("project"), "project")
    complete = packet.get("complete") is True
    if packet.get("complete") not in (True, False):
        raise ValueError("complete must be boolean")
    items = _records(packet.get("parts"), "parts", MAX_PARTS)
    boxes = [_box(item, f"parts[{index}]") for index, item in enumerate(items)]
    parts = {part.name: part for part in boxes}
    if len(parts) != len(boxes):
        raise ValueError("duplicate part IDs")
    expected = [_name(item, "expected_parts") for item in _records(packet.get("expected_parts", []), "expected_parts", MAX_PARTS)]
    if len(expected) != len(set(expected)):
        raise ValueError("duplicate expected part IDs")
    allowed = {
        _pair(item, "allowed_overlap") for item in _records(packet.get("allowed_overlaps", []), "allowed_overlaps")
    }
    if any(not pair <= set(parts) for pair in allowed):
        raise ValueError("overlap allowlist refers to nonexistent parts")
    issues: list[dict[str, str]] = []

    def add(code: str, target: str, detail: str, remedy: str, severity: str = "error") -> None:
        issues.append({"code": code, "target": target, "severity": severity,
                       "evidence": detail, "suggested_fix": remedy})

    for ident in expected:
        if ident not in parts:
            add("missing-prop" if complete else "prop-not-observed", ident,
                "Required part missing from complete manifest." if complete else "Required part absent from partial sample.",
                "Reinspect the actual Studio instance hierarchy; add the authored prop if truly missing.",
                "error" if complete else "unverified")

    for i, a in enumerate(boxes):
        if not a.solid:
            continue
        for b in boxes[i + 1:]:
            if b.solid and frozenset((a.name, b.name)) not in allowed and _penetrates(a, b):
                add("unexpected-box-overlap", f"{a.name}+{b.name}",
                    "Non-allowlisted yaw-oriented boxes penetrate in the supplied snapshot.",
                    "Inspect actual surfaces in Studio; repair placement or mark deliberate join after owner review.")

    supports = _records(packet.get("supports", []), "supports")
    for spec in supports:
        if not isinstance(spec, dict):
            raise ValueError("support must be a record")
        item, surface = _name(spec.get("item"), "support.item"), _name(spec.get("surface"), "support.surface")
        if item == surface:
            raise ValueError("part cannot support itself")
        if item not in parts or surface not in parts:
            add("support-not-observed", f"{item}+{surface}", "Missing support or supported part.",
                "Read back both source parts before verifying support.", "unverified")
            continue
        tolerance = _num(spec.get("tolerance", 0.08), "support.tolerance")
        if not 0 <= tolerance <= 2:
            raise ValueError("support tolerance outside 0..2 studs")
        a, b = parts[item], parts[surface]
        gap = (a.center[1] - a.size[1] / 2) - (b.center[1] + b.size[1] / 2)
        xz_gap = _horizontal_separation(a, b)
        if abs(gap) > tolerance or xz_gap >= -EPSILON:
            add("unsupported-part", item,
                f"Support gap={gap:.3f} studs; horizontal separating gap={xz_gap:.3f} studs.",
                "Snap to real contact with the intended support and rerun collision/readback checks.")

    for spec in _records(packet.get("joins", []), "joins"):
        if not isinstance(spec, dict):
            raise ValueError("join must be a record")
        left, right = _name(spec.get("a"), "join.a"), _name(spec.get("b"), "join.b")
        if left == right:
            raise ValueError("part cannot join itself")
        if left not in parts or right not in parts:
            add("joint-not-observed", f"{left}+{right}", "Joint references an absent object.",
                "Check exact part IDs and hierarchy first.", "unverified")
            continue
        tolerance = _num(spec.get("max_gap", 0.08), "join.max_gap")
        if not 0 <= tolerance <= 2:
            raise ValueError("joint tolerance outside 0..2 studs")
        separation = _separation(parts[left], parts[right])
        if separation > tolerance:
            add("unattached-joint", f"{left}+{right}",
                f"Bounding box face separation exceeds tolerance: {separation:.3f} studs.",
                "Correct pivots and snap the intended join surfaces, then inspect the actual mesh.")

    for item in _records(packet.get("clearances", []), "clearances", 32):
        area = _box(item, "clearance")
        except_ids = [_name(name, "clearance.ignore") for name in
                      _records(item.get("ignore", []) if isinstance(item, dict) else [], "clearance.ignore", 24)]
        for part in boxes:
            if part.solid and part.name not in except_ids and _penetrates(area, part):
                add("blocked-clearance", f"{area.name}+{part.name}",
                    "An authored traversal or doorway clearance box intersects a scene part.",
                    "Reposition the obstruction or resize the true navigable opening in Studio.")

    errors = sum(issue["severity"] == "error" for issue in issues)
    unverified = sum(issue["severity"] == "unverified" for issue in issues)
    status = ("needs_repair" if errors else
              "needs_evidence" if unverified or not complete else "ready_for_studio_confirmation")
    return {"project": project, "status": status, "findings": issues,
            "counts": {"error": errors, "unverified": unverified},
            "inspected_parts": len(parts), "complete_manifest": complete, "studio_verified": False,
            "limitations": [
                "Yaw-only oriented boxes; tilted objects, mesh cavities, decorative trim and arbitrary CFrames are not represented.",
                "Manifests, intentional overlap flags and support IDs can be wrong or fabricated.",
                "Use Roblox Studio GetPartsInPart and real playtests before clearing collision defects.",
                "ready_for_studio_confirmation is not visual approval, an actual building certification, or publishing permission.",
            ]}
