"""Offline, opt-in Roblox EditableMesh wave-panel recipe (2026 batch APIs).

This is a bounded *client visual preview* generator, not a physics ocean or a
Studio automation command. The returned Luau can be reviewed before installing
in StarterPlayerScripts of an authorized test place. No filesystem, remote, or
Roblox API access occurs in Python. Never treat a generated effect as playtested.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import math
from typing import Any, Mapping


QUALITY_TIERS: dict[str, tuple[int, int]] = {
    "mobile": (12, 12),
    "balanced": (24, 20),
    "desktop": (40, 24),
}


@dataclass(frozen=True)
class WavePanelOptions:
    quality: str = "balanced"
    span: float = 64.0
    amplitude: float = 1.0
    wavelength: float = 16.0
    speed: float = 1.4
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0


def _finite_number(value: object, *, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return number


def _validated(value: WavePanelOptions | Mapping[str, Any]) -> WavePanelOptions:
    if isinstance(value, Mapping):
        expected = {item.name for item in fields(WavePanelOptions)}
        unknown = set(value) - expected
        if unknown:
            raise ValueError("Unknown wave-panel options: " + ", ".join(sorted(map(str, unknown))))
        value = WavePanelOptions(**value)
    if not isinstance(value, WavePanelOptions):
        raise TypeError("Provide WavePanelOptions or a mapping")
    if not isinstance(value.quality, str) or value.quality not in QUALITY_TIERS:
        raise ValueError("quality must be mobile, balanced or desktop")
    for key, minimum, maximum in (
        ("span", 8, 256), ("amplitude", 0.05, 6), ("wavelength", 2, 128),
        ("speed", 0.1, 8), ("origin_x", -10000, 10000),
        ("origin_y", -10000, 10000), ("origin_z", -10000, 10000),
    ):
        _finite_number(getattr(value, key), name=key, minimum=minimum, maximum=maximum)
    if value.amplitude > value.span / 8:
        raise ValueError("amplitude must not exceed one eighth of span")
    return value


def estimate_wave_panel(value: WavePanelOptions | Mapping[str, object] = WavePanelOptions()) -> dict[str, int | str]:
    """Static upper bounds, *not* measured FPS, GPU draw calls, or memory use."""
    options = _validated(value)
    cells, fps = QUALITY_TIERS[options.quality]
    vertices = (cells + 1) ** 2
    return {"quality": options.quality, "grid_cells_per_side": cells,
            "vertices": vertices, "triangles": cells * cells * 2,
            "max_visual_updates_per_second": fps,
            "max_vertex_updates_per_second": vertices * fps}


def _luau_number(value: float) -> str:
    rendered = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if rendered in ("", "-0") else rendered


def compile_wave_panel(value: WavePanelOptions | Mapping[str, object] = WavePanelOptions()) -> str:
    """Generate deterministic, bounded Luau using the official EditableMesh batch APIs.

    Requirements: owner-authorized test place, dynamic mesh APIs permitted, and
    sufficient platform editable memory. Static fallback if creation fails.
    """
    options = _validated(value)
    cells, fps = QUALITY_TIERS[options.quality]
    replacements = {
        "__CELLS__": str(cells),
        "__FPS__": str(fps),
        "__SPAN__": _luau_number(options.span),
        "__AMPLITUDE__": _luau_number(options.amplitude),
        "__WAVELENGTH__": _luau_number(options.wavelength),
        "__SPEED__": _luau_number(options.speed),
        "__X__": _luau_number(options.origin_x),
        "__Y__": _luau_number(options.origin_y),
        "__Z__": _luau_number(options.origin_z),
    }
    source = _WAVE_LUAU
    for key, replacement in replacements.items():
        source = source.replace(key, replacement)
    return source


_WAVE_LUAU = '''--!strict
-- STAR EditableMesh wave-panel PREVIEW (client-only, non-colliding water).
-- Reviewed source required. Place under StarterPlayerScripts in an authorized test place.
-- 2026 Roblox batch APIs; all geometry writes stay on the serial thread.
-- Not a physics ocean, not published/replicated, not verified by a Studio playtest.
local AssetService = game:GetService("AssetService")
local RunService = game:GetService("RunService")
local CELLS = __CELLS__
local FPS = __FPS__
local SPAN = __SPAN__
local AMPLITUDE = __AMPLITUDE__
local WAVELENGTH = __WAVELENGTH__
local SPEED = __SPEED__
local ORIGIN = Vector3.new(__X__, __Y__, __Z__)
local STEP = 1 / FPS

local function wave(x: number, z: number, t: number): number
    local k = 2 * math.pi / WAVELENGTH
    return AMPLITUDE * (0.73 * math.sin(x * k + t * SPEED)
        + 0.27 * math.cos(z * k * 0.76 - t * SPEED * 0.62))
end

local function fallback(): BasePart
    local part = Instance.new("Part")
    part.Name = "StarWaterFallback"
    part.Anchored = true
    part.CanCollide = false
    part.CanTouch = false
    part.CanQuery = false
    part.CastShadow = false
    part.Material = Enum.Material.Glass
    part.Color = Color3.fromRGB(49, 134, 176)
    part.Transparency = 0.38
    part.Size = Vector3.new(SPAN, 0.12, SPAN)
    part.CFrame = CFrame.new(ORIGIN)
    part.Parent = workspace
    return part
end

local function start()
    if not RunService:IsClient() then
        warn("STAR wave preview is client-only")
        return function() end
    end
    local editable: EditableMesh? = nil
    local meshPart: MeshPart? = nil
    local vertices: {number} = {}
    local base: {Vector3} = {}
    local ok = pcall(function()
        editable = AssetService:CreateEditableMesh()
        assert(editable ~= nil, "device mesh budget or permissions")
        local points: {Vector3} = {}
        for iz = 0, CELLS do
            for ix = 0, CELLS do
                local x = SPAN * (ix / CELLS - 0.5)
                local z = SPAN * (iz / CELLS - 0.5)
                local p = Vector3.new(x, wave(x, z, 0), z)
                table.insert(base, Vector3.new(x, 0, z))
                table.insert(points, p)
            end
        end
        vertices = (editable :: EditableMesh):BatchAdd(Enum.MeshAttribute.Vertex, points)
        local faces: {{number}} = {}
        for iz = 0, CELLS - 1 do
            for ix = 0, CELLS - 1 do
                local a = iz * (CELLS + 1) + ix + 1
                local b = a + 1
                local c = a + CELLS + 1
                local d = c + 1
                table.insert(faces, {vertices[a], vertices[c], vertices[b]})
                table.insert(faces, {vertices[b], vertices[c], vertices[d]})
            end
        end
        (editable :: EditableMesh):BatchAdd(Enum.MeshAttribute.Face, faces)
        meshPart = AssetService:CreateMeshPartAsync(Content.fromObject(editable :: EditableMesh), {
            CollisionFidelity = Enum.CollisionFidelity.Box,
        })
        assert(meshPart ~= nil, "could not render editable mesh")
        local part = meshPart :: MeshPart
        part.Name = "StarEditableWavePreview"
        part.Anchored = true
        part.CanCollide = false
        part.CanTouch = false
        part.CanQuery = false
        part.CastShadow = false
        part.Material = Enum.Material.Glass
        part.Color = Color3.fromRGB(49, 134, 176)
        part.Transparency = 0.24
        part.CFrame = CFrame.new(ORIGIN)
        part.Parent = workspace
    end)
    if not ok or editable == nil or meshPart == nil then
        if meshPart then meshPart:Destroy() end
        if editable then editable:Destroy() end
        warn("STAR mesh preview could not be created; using a flat fallback")
        local part = fallback()
        return function() part:Destroy() end
    end
    local closed = false
    local accumulator = 0
    local elapsed = 0
    local connection: RBXScriptConnection? = nil
    local newPositions: {Vector3} = table.create(#base)
    connection = RunService.Heartbeat:Connect(function(dt: number)
        if closed then return end
        elapsed += math.max(0, math.min(dt, 0.2))
        accumulator += math.max(0, dt)
        if accumulator < STEP then return end
        accumulator = accumulator % STEP
        for i, initial in ipairs(base) do
            newPositions[i] = Vector3.new(initial.X, wave(initial.X, initial.Z, elapsed), initial.Z)
        end
        -- One batch write per visual update; NO task.desynchronize() around writes.
        local succeeded = pcall(function()
            (editable :: EditableMesh):BatchSetValues(vertices, newPositions)
        end)
        if not succeeded then
            warn("STAR mesh update stopped; preserving the last visible frame")
            if connection then connection:Disconnect() end
            connection = nil
        end
    end)
    return function()
        if closed then return end
        closed = true
        if connection then connection:Disconnect() end
        if meshPart then meshPart:Destroy() end
        if editable then editable:Destroy() end
    end
end

local cleanup = start()
script.Destroying:Connect(cleanup)
'''


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Print an opt-in Roblox EditableMesh wave preview LocalScript")
    parser.add_argument("--quality", choices=sorted(QUALITY_TIERS), default="balanced")
    parser.add_argument("--span", type=float, default=64.0)
    parser.add_argument("--amplitude", type=float, default=1.0)
    parser.add_argument("--wavelength", type=float, default=16.0)
    parser.add_argument("--speed", type=float, default=1.4)
    args = parser.parse_args()
    print(compile_wave_panel({"quality": args.quality, "span": args.span,
                              "amplitude": args.amplitude, "wavelength": args.wavelength,
                              "speed": args.speed}), end="")
