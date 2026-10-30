"""Deterministic oriented-box narrow phase for STAR's offline Roblox blockouts.

Roblox BasePart.Orientation uses the Y-X-Z Euler order. Parts and spawn
pads are boxes; wedge/truss and imported mesh *contents* are only represented
by a conservative surrounding box. This sensor never proves physical gameplay
or mesh fidelity: real Studio playtesting remains authoritative.

AABB broad-phase is followed by 15-axis SAT for rotated boxes; face touching
and penetrations <= tolerance are not counted as clashes. Pure arithmetic,
no GPU dependency, engine writes, network calls, or additional packages.
"""
from __future__ import annotations

from typing import cast

from dataclasses import dataclass
import math

Vector = tuple[float, float, float]
AxisSet = tuple[Vector, Vector, Vector]
IDENTITY: AxisSet = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True, slots=True)
class OrientedBox:
    center: Vector
    half: Vector
    axes: AxisSet  # Three columns of Roblox's Y-X-Z orientation matrix.
    lo: Vector
    hi: Vector
    rotated: bool


def from_pose(position, size, rotation=(0, 0, 0)) -> OrientedBox:
    """Bounds and local axes for a Roblox oriented rectangular part."""
    center = cast(Vector, tuple(float(p) for p in position))
    half = cast(Vector, tuple(float(s) * 0.5 for s in size))
    rotated = any(angle % 360 != 0 for angle in rotation)
    axes = IDENTITY
    if rotated:
        rx, ry, rz = (math.radians(angle % 360) for angle in rotation)
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        # Rotation matrix R = Ry @ Rx @ Rz (CFrame.fromOrientation).
        rows = (
            (cy * cz + sy * sx * sz, -cy * sz + sy * sx * cz, sy * cx),
            (cx * sz, cx * cz, -sx),
            (-sy * cz + cy * sx * sz, sy * sz + cy * sx * cz, cy * cx),
        )
        axes = cast(AxisSet, tuple(tuple(rows[i][j] for i in range(3)) for j in range(3)))
    extent = tuple(sum(abs(axes[j][i]) * half[j] for j in range(3)) for i in range(3))
    lo = cast(Vector, tuple(center[i] - extent[i] for i in range(3)))
    hi = cast(Vector, tuple(center[i] + extent[i] for i in range(3)))
    return OrientedBox(center, half, axes, lo, hi, rotated)


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vector, b: Vector) -> Vector:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def intersects(a: OrientedBox, b: OrientedBox, *, tolerance: float = 0.05) -> bool:
    """Whether two closed box volumes penetrate by > tolerance in every SAT axis.

    Even for nearly parallel edges, the cross-axis threshold is scaled by the
    axis length. This avoids treating harmless contact as penetration. Overlap
    of a conservative wedge/asset bounding box is *not* proof of mesh contact.
    """
    if any(min(a.hi[i], b.hi[i]) - max(a.lo[i], b.lo[i]) <= tolerance for i in range(3)):
        return False
    if not (a.rotated or b.rotated):
        return True

    delta = cast(Vector, tuple(b.center[i] - a.center[i] for i in range(3)))

    def separated(axis: Vector) -> bool:
        length_sq = _dot(axis, axis)
        if length_sq < 1e-20:  # Parallel edges: a face axis already covers this case.
            return False
        radius_a = sum(a.half[i] * abs(_dot(a.axes[i], axis)) for i in range(3))
        radius_b = sum(b.half[i] * abs(_dot(b.axes[i], axis)) for i in range(3))
        return abs(_dot(delta, axis)) >= radius_a + radius_b - tolerance * math.sqrt(length_sq)

    for axis in a.axes + b.axes:
        if separated(axis):
            return False
    for ax in a.axes:
        for bx in b.axes:
            if separated(_cross(ax, bx)):
                return False
    return True
