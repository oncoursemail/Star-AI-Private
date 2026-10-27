"""Focused visual change detection under a 9x8 whole-HUD sampling blind spot.

Deterministic offline evidence. No screen capture, image model, network,
speech synthesis, game automation, or sensitive viewer data is used.
"""
from dataclasses import replace

import pytest

from star.frame_fingerprint import tone_distance
from star.stream_budget import StreamTelemetry
from star.stream_observe import FocusSample, FrameCue, ObservationGovernor
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_vision_host import StreamVisionHost


W, H = 400, 240
WORLD = (0, 0, 280, 240)
HUD = (280, 0, 120, 240)
FOCUS = (305, 24, 28, 20)
FOCUS_OTHER = (303, 21, 32, 26)


def pixels(*, icon=False, color=(0, 0, 255, 255)):
    """Small colored 12x8 HUD indicator away from whole-HUD sample rows."""
    out = bytearray(b"\x00\x00\x00\xff" * (W * H))
    if icon:
        for y in range(28, 36):
            for x in range(310, 322):
                offset = (y * W + x) * 4
                out[offset:offset + 4] = bytes(color)
    return out


def frame(at, raw, *, focus_regions=()):
    return FrameCue.from_pixels(
        at, raw, width=W, height=H, pixel_format="BGRA",
        game_region=WORLD, hud_region=HUD, focus_regions=focus_regions,
    )


def advisor():
    g = ObservationGovernor(burst=3)
    g.enable(owner_approved=True)
    return g


def decide_against(baseline, changed):
    g = advisor()
    t = StreamTelemetry(True, True, 3500, 8192, 60, 20)
    initial = g.consider(baseline, t, now_ms=1000, capture_authorized=True)
    assert initial.admitted
    assert g.complete(ticket=initial.ticket, now_ms=1010, succeeded=True)
    return g.consider(changed, t, now_ms=2200, capture_authorized=True)


def test_small_health_icon_is_invisible_to_untiled_hud_but_visible_to_focus():
    before, after = pixels(), pixels(icon=True)
    a, b = frame(1000, before), frame(2200, after)
    # A global 9x8 scan can miss this real pixel change entirely.
    assert a.perceptual_hash == b.perceptual_hash
    assert a.hud_hash == b.hud_hash
    assert a.tone_signature == b.tone_signature
    assert a.hud_tone_signature == b.hud_tone_signature
    assert decide_against(a, b).reason == "low_visual_novelty"

    c, d = (
        frame(1000, before, focus_regions=(FOCUS,)),
        frame(2200, after, focus_regions=(FOCUS,)),
    )
    assert c.focus_samples[0].edge_hash != d.focus_samples[0].edge_hash
    assert tone_distance(c.focus_samples[0].tone_signature,
                         d.focus_samples[0].tone_signature) >= 3
    assert decide_against(c, d).admitted


def test_focus_detects_color_change_without_edge_change():
    red = frame(1000, pixels(icon=True), focus_regions=(FOCUS,))
    green = frame(
        2200, pixels(icon=True, color=(0, 255, 0, 255)),
        focus_regions=(FOCUS,),
    )
    assert red.perceptual_hash == green.perceptual_hash
    assert red.hud_hash == green.hud_hash
    assert red.focus_samples[0].edge_hash == green.focus_samples[0].edge_hash
    assert decide_against(red, green).admitted


def test_same_focus_crops_do_not_repeat_costly_inference():
    original = frame(1000, pixels(icon=True), focus_regions=(FOCUS,))
    unchanged = frame(2200, pixels(icon=True), focus_regions=(FOCUS,))
    assert decide_against(original, unchanged).reason == "low_visual_novelty"


def test_focus_scope_changes_trigger_a_new_observation_instead_of_false_match():
    first = frame(1000, pixels(), focus_regions=(FOCUS,))
    new_scope = frame(2200, pixels(), focus_regions=(FOCUS_OTHER,))
    assert decide_against(first, new_scope).admitted
    legacy = frame(2200, pixels())
    assert decide_against(first, legacy).admitted
    assert decide_against(frame(1000, pixels()), new_scope).admitted


def test_focus_regions_are_canonical_even_if_configured_in_reverse_order():
    first = frame(1000, pixels(), focus_regions=(FOCUS_OTHER, FOCUS))
    second = frame(2200, pixels(), focus_regions=(FOCUS, FOCUS_OTHER))
    assert first.focus_samples == second.focus_samples
    assert first.focus_samples[0].region == min(FOCUS, FOCUS_OTHER)
    assert decide_against(first, second).reason == "low_visual_novelty"


@pytest.mark.parametrize("regions", [
    [FOCUS],
    (FOCUS,) * 2,
    (FOCUS,) * 9,
    ((0, 0, 8, 8),),
    ((399, 200, 9, 8),),
    ((0, 0, True, 20),),
    ((0, 0, -9, 20),),
    ("bad",),
])
def test_bad_focus_scopes_rejected_without_unbounded_image_scan(regions):
    with pytest.raises((ValueError, TypeError)):
        frame(1000, pixels(), focus_regions=regions)


@pytest.mark.parametrize("overrides", [
    {"region": (0, 0, 8, 8)},
    {"region": (8190, 0, 20, 30)},
    {"edge_hash": -1},
    {"edge_hash": True},
    {"edge_hash": 2**64},
    {"tone_signature": -1},
    {"tone_signature": 2**42},
])
def test_reject_bogus_focus_sample(overrides):
    attrs = {"region": FOCUS, "edge_hash": 0, "tone_signature": 0}
    attrs.update(overrides)
    with pytest.raises(ValueError):
        FocusSample(**attrs)


def test_direct_forged_bad_frame_samples_fail_closed():
    real = frame(1000, pixels(), focus_regions=(FOCUS, FOCUS_OTHER))
    with pytest.raises(ValueError):
        replace(real, focus_samples=tuple(reversed(real.focus_samples)))
    with pytest.raises(ValueError):
        replace(real, focus_samples=(real.focus_samples[0],) * 2)
    with pytest.raises(ValueError):
        replace(real, focus_samples=[real.focus_samples[0]])
    with pytest.raises(ValueError):
        replace(real, focus_samples=(object(),))


def test_background_opt_out_does_not_inspect_invalid_buffers():
    now = [1000.0]
    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 1000},
        memory_probe=lambda: (32768, 10000),
        cpu_probe=lambda: (100, 1000), clock_ms=lambda: now[0],
    )
    hardware.set_context(live=False, game_active=False, owner_approved=True)
    host = StreamVisionHost(
        telemetry=hardware, governor=ObservationGovernor(),
        clock_ms=lambda: now[0],
    )
    assert host.consider_pixels(
        "not pixels", captured_ms=now[0], width=W, height=H,
        focus_regions=(FOCUS,),
    ).reason == "owner_opt_in_missing"
    assert host.status()["admitted"] == 0
