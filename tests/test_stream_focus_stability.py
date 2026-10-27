"""Realistic offline HUD flicker vs persistent change, never game-event proof."""
import pytest

from star.stream_focus_stability import TemporalFocusGate
from star.stream_observe import FocusSample, FrameCue, ObservationGovernor
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_vision_host import StreamVisionHost
from star.stream_budget import StreamTelemetry

FIRST = (10, 10, 50, 25)
SECOND = (80, 10, 50, 25)


def f(at, *, tone=0, edge=0, scope=(FIRST,), cue="none", main=0):
    samples = tuple(FocusSample(r, edge, tone) for r in scope)
    return FrameCue(at, main, cue, focus_samples=samples)


def test_single_frame_damage_flash_ignored_then_real_change_confirmed():
    gate = TemporalFocusGate()
    assert gate.filter(f(1000)).frame.focus_samples[0].tone_signature == 0
    burst = gate.filter(f(1100, tone=20 << 36))
    assert burst.suppressed == 1 and burst.confirmed == ()
    assert burst.frame.focus_samples[0].tone_signature == 0
    assert gate.filter(f(1200)).suppressed == 0
    assert gate.filter(f(1300, tone=20 << 36)).suppressed == 1
    held = gate.filter(f(1400, tone=20 << 36))
    assert held.suppressed == 0 and held.confirmed == (FIRST,)
    assert held.frame.focus_samples[0].tone_signature == 20 << 36
    assert gate.filter(f(1500, tone=20 << 36)).confirmed == ()
    assert gate.filter(f(1600)).suppressed == 1  # Return also needs confirmation.
    assert gate.filter(f(1700)).confirmed == (FIRST,)


def test_same_capture_cannot_fake_independent_confirmation():
    gate = TemporalFocusGate()
    gate.filter(f(1000))
    assert gate.filter(f(1100, tone=20 << 36)).suppressed == 1
    for _ in range(5):
        assert gate.filter(f(1100, tone=20 << 36)).confirmed == ()
    assert gate.filter(f(1050, tone=20 << 36)).confirmed == ()
    assert gate.filter(f(1200, tone=20 << 36)).confirmed == (FIRST,)


def test_gap_timeout_requires_new_confirmation_streak():
    gate = TemporalFocusGate(max_gap_ms=200)
    gate.filter(f(1000))
    gate.filter(f(1100, tone=20 << 36))
    assert gate.filter(f(2000, tone=20 << 36)).suppressed == 1
    assert gate.filter(f(2150, tone=20 << 36)).confirmed == (FIRST,)


def test_no_scope_confusion_and_scope_change_is_visible():
    gate = TemporalFocusGate()
    original = f(1000)
    gate.filter(original)
    gate.filter(f(1100, tone=20 << 36))
    changed = gate.filter(f(1200, tone=20 << 36, scope=(SECOND,)))
    assert changed.frame.focus_samples[0].region == SECOND
    assert changed.suppressed == 0 and changed.confirmed == ()
    assert gate.filter(f(1300, tone=20 << 36, scope=())).frame.focus_samples == ()
    assert gate.filter(original).confirmed == ()  # out-of-order never restores scope
    assert gate.filter(f(1400, scope=(FIRST,))).frame.focus_samples[0].region == FIRST


def test_quiet_stream_cues_and_whole_world_changes_never_suppressed():
    gate = TemporalFocusGate()
    gate.filter(f(1000))
    transient = gate.filter(f(1200, tone=20 << 36, cue="death", main=0xFF))
    assert transient.frame.cue == "death"
    assert transient.frame.perceptual_hash == 0xFF
    assert transient.frame.focus_samples[0].tone_signature == 0


def test_multiple_regions_independent_and_edge_change_detected():
    gate = TemporalFocusGate()
    gate.filter(f(1000, scope=(FIRST, SECOND)))
    first = gate.filter(f(1100, edge=0xFF, scope=(FIRST, SECOND)))
    assert first.suppressed == 2
    second = gate.filter(FrameCue(1200, 0, focus_samples=(
        FocusSample(FIRST, 0xFF, 0), FocusSample(SECOND, 0, 0),
    )))
    assert second.confirmed == (FIRST,)
    assert second.frame.focus_samples[1].edge_hash == 0


def test_small_fingerprint_jitter_never_becomes_cue():
    gate = TemporalFocusGate()
    gate.filter(f(1000))
    assert gate.filter(f(1100, tone=1 << 36, edge=0b1)).suppressed == 0
    assert gate.filter(f(1200, tone=2 << 36, edge=0b11)).confirmed == ()


@pytest.mark.parametrize("kwargs", [
    {"confirm_frames": 1}, {"confirm_frames": 6},
    {"confirm_frames": True}, {"max_gap_ms": float("nan")},
    {"max_gap_ms": True}, {"max_gap_ms": 10}, {"max_gap_ms": 10**1000},
    {"edge_threshold": 0}, {"tone_threshold": 64},
])
def test_unbounded_or_invalid_stability_settings_rejected(kwargs):
    with pytest.raises(ValueError):
        TemporalFocusGate(**kwargs)


def test_reset_erases_candidates_and_stable_state():
    gate = TemporalFocusGate()
    gate.filter(f(1000))
    gate.filter(f(1100, tone=20 << 36))
    gate.reset()
    fresh = gate.filter(f(1200, tone=20 << 36))
    assert fresh.confirmed == () and fresh.frame.focus_samples[0].tone_signature == 20 << 36
    assert gate.filter(f(1300, tone=20 << 36)).confirmed == ()


def test_temporal_confirmation_filters_vision_inference_requests_end_to_end():
    time = [1000.0]
    cpu = [100, 1000]
    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 1000},
        memory_probe=lambda: (32768, 10000),
        cpu_probe=lambda: tuple(cpu), clock_ms=lambda: time[0],
    )
    hardware.set_context(live=False, game_active=False, owner_approved=True)
    governor = ObservationGovernor(burst=4, calls_per_minute=120)
    host = StreamVisionHost(
        telemetry=hardware, governor=governor,
        clock_ms=lambda: time[0], stabilize_focus=True,
    )
    host.enable(owner_approved=True, capture_approved=True)

    def offer(sample):
        time[0] = float(sample.captured_ms)
        assert hardware.refresh_hardware()
        cpu[0] += 10
        cpu[1] += 100
        assert hardware.refresh_hardware()
        return host.consider(sample)

    start = offer(f(1000))
    assert start.admitted
    time[0] = 1010.0
    assert host.acknowledge_worker_stopped(start.lease, worker_stopped=True, succeeded=True)
    one = offer(f(1500, tone=20 << 36))
    assert one.reason == "low_visual_novelty"
    revert = offer(f(1900))
    assert revert.reason == "low_visual_novelty"
    two = offer(f(2300, tone=20 << 36))
    assert two.reason == "low_visual_novelty"
    three = offer(f(2700, tone=20 << 36))
    assert three.admitted and three.lease is not None
    assert host.status()["unstable_focus_suppressed"] == 2
    assert host.status()["focus_confirmed"] == 1
    time[0] = 2710.0
    assert host.acknowledge_worker_stopped(three.lease, worker_stopped=True, succeeded=True)
    host.disable()
    assert not host.status()["enabled"]
    host.enable(owner_approved=True, capture_approved=True)
    new_epoch = offer(f(3100))
    assert new_epoch.admitted  # fresh baseline in new, independently approved session


def test_default_host_path_does_not_change_focus_behavior():
    governor = ObservationGovernor()
    governor.enable(owner_approved=True)
    state = StreamTelemetry(True, True, 4000, 8192, 60, 20)
    first = governor.consider(f(1000), state, now_ms=1000, capture_authorized=True)
    assert first.admitted
    assert governor.complete(ticket=first.ticket, now_ms=1010, succeeded=True)
    one_frame = governor.consider(
        f(2200, tone=20 << 36), state, now_ms=2200,
        capture_authorized=True,
    )
    assert one_frame.admitted  # default low-latency mode remains unchanged


def test_opt_in_is_strict_bool_and_no_gpu_is_released_on_timeout():
    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 1000},
        memory_probe=lambda: (32768, 10000),
        cpu_probe=lambda: (100, 1000), clock_ms=lambda: 1000,
    )
    with pytest.raises(ValueError):
        StreamVisionHost(telemetry=hardware, governor=ObservationGovernor(),
                         stabilize_focus="true")
    host = StreamVisionHost(telemetry=hardware, governor=ObservationGovernor(),
                            stabilize_focus=True, clock_ms=lambda: 1000)
    assert host.consider(f(1000)).reason == "owner_opt_in_missing"
    assert host.status()["unstable_focus_suppressed"] == 0
