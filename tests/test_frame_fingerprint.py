"""Offline adversarial proof for CPU-scoped visual novelty, no real capture."""
from __future__ import annotations

import pytest

from star.frame_fingerprint import difference_hash
from star.stream_budget import StreamTelemetry
from star.stream_observe import FrameCue, ObservationGovernor
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_vision_host import StreamVisionHost


def gray_gradient(width=45, height=32, *, descending=False, offset=0):
    values = [min(255, max(0, offset + (200 - x * 4 if descending else x * 4)))
              for _ in range(height) for x in range(width)]
    return bytes(values)


def divided_frame(*, flip_hud=False):
    """Two regions with opposite horizontal gradients, 50x24 GRAY."""
    return bytes(
        (200 - ((x - 25) * 7) if flip_hud else (x - 25) * 7)
        if x >= 25 else x * 7
        for _ in range(24) for x in range(50)
    )


def test_horizontal_direction_and_brightness_stability():
    left_dark = gray_gradient()
    left_bright = gray_gradient(descending=True)
    a = difference_hash(left_dark, width=45, height=32, pixel_format="GRAY")
    b = difference_hash(left_bright, width=45, height=32, pixel_format="GRAY")
    assert a == 0
    assert b == (1 << 64) - 1
    shifted = difference_hash(
        gray_gradient(offset=10), width=45, height=32, pixel_format="GRAY"
    )
    assert shifted == a


@pytest.mark.parametrize("pixel_format", ["GRAY", "RGB", "BGR", "RGBA", "BGRA"])
def test_formats_agree_when_colors_are_equal(pixel_format):
    pixel = [min(180, x * 4) for y in range(24) for x in range(45)]
    channels = {"GRAY": 1, "RGB": 3, "BGR": 3, "RGBA": 4, "BGRA": 4}[pixel_format]
    data = bytes(item for lum in pixel for item in ([lum] * 3 + [255])[:channels])
    if channels == 1:
        data = bytes(pixel)
    assert difference_hash(
        data, width=45, height=24, pixel_format=pixel_format
    ) == 0


def test_bgra_alpha_is_not_a_visual_novelty_signal():
    raw = bytearray()
    alt = bytearray()
    for x in range(45 * 24):
        lum = (x % 45) * 4
        raw.extend((lum, lum, lum, 0))
        alt.extend((lum, lum, lum, 255))
    assert difference_hash(raw, width=45, height=24) == difference_hash(
        alt, width=45, height=24
    )


def test_stride_padding_and_memoryviews_match_packed():
    width, height = 45, 24
    packed = gray_gradient(width, height)
    with_padding = b"".join(packed[i * width:(i + 1) * width] + b"HELLO"
                            for i in range(height))
    assert difference_hash(memoryview(with_padding), width=width, height=height,
                           row_stride=50, pixel_format="GRAY") == difference_hash(
                               packed, width=width, height=height, pixel_format="GRAY")


def test_world_and_hud_crop_are_independently_sensitive():
    first = divided_frame()
    later = divided_frame(flip_hud=True)
    a = FrameCue.from_pixels(
        1000, first, width=50, height=24, pixel_format="GRAY",
        game_region=(0, 0, 25, 24), hud_region=(25, 0, 25, 24),
    )
    b = FrameCue.from_pixels(
        2200, later, width=50, height=24, pixel_format="GRAY",
        game_region=(0, 0, 25, 24), hud_region=(25, 0, 25, 24),
    )
    assert a.perceptual_hash == b.perceptual_hash
    assert (a.hud_hash ^ b.hud_hash).bit_count() >= 8


def test_unmasked_fingerprint_changes_for_large_hud_difference():
    before = difference_hash(divided_frame(), width=50, height=24,
                             pixel_format="GRAY")
    after = difference_hash(divided_frame(flip_hud=True), width=50, height=24,
                            pixel_format="GRAY")
    assert before != after


@pytest.mark.parametrize("changes", [
    {"width": True}, {"height": 0}, {"width": 8}, {"height": 7},
    {"width": 8193}, {"pixel_format": "RGBA16"}, {"row_stride": 4},
    {"row_stride": True}, {"region": (0, 0, 8, 8)},
    {"region": (-1, 0, 9, 8)}, {"region": (1, 0, 45, 24)},
    {"region": (0, 0, True, 10)}, {"region": [0, 0, 20, 20]},
])
def test_invalid_shapes_are_fail_closed(changes):
    values = dict(width=45, height=24, pixel_format="GRAY", region=None)
    values.update(changes)
    with pytest.raises((ValueError, TypeError)):
        difference_hash(gray_gradient(45, 24), **values)


def test_truncated_and_noncontiguous_buffers_are_rejected():
    with pytest.raises(ValueError):
        difference_hash(b"too short", width=45, height=24, pixel_format="GRAY")
    with pytest.raises(ValueError):
        difference_hash(memoryview(bytes(45 * 48))[::2], width=45, height=24,
                        pixel_format="GRAY")
    with pytest.raises(TypeError):
        difference_hash("raw bytes only", width=45, height=24, pixel_format="GRAY")
    with pytest.raises(ValueError):
        difference_hash(bytes(45 * 24), width=45, height=24,
                        row_stride=1000000, pixel_format="GRAY")


def test_frame_cue_hud_type_bounds_and_unsupported_events():
    for bad in [True, -1, 2**64, "1", 1.0]:
        with pytest.raises(ValueError):
            FrameCue(0, 0, hud_hash=bad)
    with pytest.raises(ValueError):
        FrameCue.from_pixels(0, bytes(45 * 24), width=45, height=24,
                             pixel_format="GRAY", cue="execute_code")


def test_governor_detects_hud_changes_without_flooding_inference():
    telem = StreamTelemetry(True, True, 3500, 8192, 60, 20)
    governor = ObservationGovernor(novelty_bits=8, hud_novelty_bits=4, burst=3)
    governor.enable(owner_approved=True)
    before = FrameCue.from_pixels(
        1000, divided_frame(), width=50, height=24,
        pixel_format="GRAY", game_region=(0, 0, 25, 24),
        hud_region=(25, 0, 25, 24),
    )
    after = FrameCue.from_pixels(
        2200, divided_frame(flip_hud=True), width=50, height=24,
        pixel_format="GRAY", game_region=(0, 0, 25, 24),
        hud_region=(25, 0, 25, 24),
    )
    first = governor.consider(before, telem, now_ms=1000, capture_authorized=True)
    assert first.admitted
    assert governor.complete(ticket=first.ticket, now_ms=1050, succeeded=True)
    early = FrameCue(1150, after.perceptual_hash, hud_hash=after.hud_hash)
    assert governor.consider(early, telem, now_ms=1150, capture_authorized=True).reason == (
        "minimum_sampling_interval"
    )
    changed = governor.consider(after, telem, now_ms=2200, capture_authorized=True)
    assert changed.admitted
    assert governor.complete(ticket=changed.ticket, now_ms=2260, succeeded=True)
    similar = governor.consider(after, telem, now_ms=3400, capture_authorized=True)
    assert similar.reason == "low_visual_novelty"


def test_missing_hud_scope_is_not_comparable_and_cannot_hide_a_change():
    telem = StreamTelemetry(True, True, 3500, 8192, 60, 20)
    governor = ObservationGovernor()
    governor.enable(owner_approved=True)
    a = governor.consider(FrameCue(0, 1), telem, now_ms=0, capture_authorized=True)
    assert governor.complete(ticket=a.ticket, now_ms=40, succeeded=True)
    b = governor.consider(FrameCue(1200, 1, hud_hash=99), telem,
                          now_ms=1200, capture_authorized=True)
    assert b.admitted


def test_authorized_host_can_admit_raw_pixels_without_relying_on_model_hashes():
    now = [1000.0]
    cpu = [100, 1000]
    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 3000},
        memory_probe=lambda: (32768, 20000),
        cpu_probe=lambda: tuple(cpu),
        clock_ms=lambda: now[0],
    )
    hardware.set_context(live=False, game_active=False, owner_approved=True)
    assert hardware.refresh_hardware()
    cpu[0] += 10
    cpu[1] += 100
    assert hardware.refresh_hardware()
    host = StreamVisionHost(
        telemetry=hardware, governor=ObservationGovernor(),
        clock_ms=lambda: now[0],
    )
    raw = divided_frame()
    # No buffer validation or memory access is needed when owner opt-in is off.
    assert host.consider_pixels(b"invalid", captured_ms=now[0], width=50,
                                height=24, pixel_format="GRAY").reason == "owner_opt_in_missing"
    host.enable(owner_approved=True, capture_approved=True)
    first = host.consider_pixels(
        raw, captured_ms=now[0], width=50, height=24,
        pixel_format="GRAY", game_region=(0, 0, 25, 24),
        hud_region=(25, 0, 25, 24),
    )
    assert first.admitted
    now[0] += 50
    assert host.acknowledge_worker_stopped(
        first.lease, worker_stopped=True, succeeded=True
    )
    now[0] += 1100
    cpu[0] += 10
    cpu[1] += 100
    assert hardware.refresh_hardware()
    unchanged = host.consider_pixels(
        raw, captured_ms=now[0], width=50, height=24, pixel_format="GRAY",
        game_region=(0, 0, 25, 24), hud_region=(25, 0, 25, 24),
    )
    assert unchanged.reason == "low_visual_novelty"
    changed = host.consider_pixels(
        divided_frame(flip_hud=True), captured_ms=now[0],
        width=50, height=24, pixel_format="GRAY",
        game_region=(0, 0, 25, 24), hud_region=(25, 0, 25, 24),
    )
    assert changed.admitted
    assert host.status()["admitted"] == 2
    host.disable()
    assert host.status()["quarantined"]
