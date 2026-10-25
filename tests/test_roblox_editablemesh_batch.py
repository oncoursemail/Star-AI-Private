"""Offline regression checks for the bounded Roblox 2026 EditableMesh batch preview."""
import math

import pytest

from star.roblox_editablemesh_batch import (
    QUALITY_TIERS,
    WavePanelOptions,
    compile_wave_panel,
    estimate_wave_panel,
)


def test_deterministic_source_is_client_only_and_uses_batch_apis():
    first = compile_wave_panel()
    assert first == compile_wave_panel({})
    assert first.startswith("--!strict")
    assert "AssetService:CreateEditableMesh()" in first
    assert "BatchAdd(Enum.MeshAttribute.Vertex, points)" in first
    assert "BatchAdd(Enum.MeshAttribute.Face, faces)" in first
    assert "BatchSetValues(vertices, newPositions)" in first
    assert "RunService:IsClient()" in first
    assert "script.Destroying:Connect(cleanup)" in first
    assert "CanCollide = false" in first
    assert "task.desynchronize() around writes" in first
    assert "loadstring" not in first and "HttpService" not in first
    assert "__CELLS__" not in first and "__SPAN__" not in first


@pytest.mark.parametrize("quality", sorted(QUALITY_TIERS))
def test_tiers_bound_triangle_and_update_work(quality):
    estimate = estimate_wave_panel({"quality": quality})
    cells = estimate["grid_cells_per_side"]
    assert estimate["vertices"] == (cells + 1) ** 2
    assert estimate["triangles"] == 2 * cells ** 2
    assert estimate["triangles"] <= 3200
    assert estimate["max_vertex_updates_per_second"] <= 40344
    generated = compile_wave_panel({"quality": quality})
    assert f"local CELLS = {cells}" in generated
    assert f'local FPS = {estimate["max_visual_updates_per_second"]}' in generated


def test_custom_bounded_values_render_numeric_literals():
    options = WavePanelOptions(quality="mobile", span=32, amplitude=0.3,
                               wavelength=6, speed=2.25,
                               origin_x=-5, origin_y=2, origin_z=11)
    text = compile_wave_panel(options)
    assert "local SPAN = 32" in text
    assert "local AMPLITUDE = 0.3" in text
    assert "local ORIGIN = Vector3.new(-5, 2, 11)" in text
    assert "local SPEED = 2.25" in text


@pytest.mark.parametrize("bad", [
    {"quality": "ultra"}, {"quality": 100},
    {"span": -2}, {"span": True},
    {"amplitude": 10}, {"amplitude": float("nan")},
    {"speed": float("inf")}, {"origin_x": 999999},
    {"wavelength": "loadstring('bad')"}, {"not_a_setting": "x"},
])
def test_rejects_unsafe_or_unbounded_values(bad):
    with pytest.raises((TypeError, ValueError)):
        compile_wave_panel(bad)


def test_static_costs_are_not_claimed_as_measured_fps():
    stats = estimate_wave_panel()
    assert set(stats) == {
        "quality", "grid_cells_per_side", "vertices", "triangles",
        "max_visual_updates_per_second", "max_vertex_updates_per_second",
    }
    assert math.isfinite(stats["max_vertex_updates_per_second"])
