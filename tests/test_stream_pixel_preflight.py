"""Skip expensive raw-frame sampling when real-time vision cannot be admitted."""
from unittest.mock import patch

import pytest

from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_observe import FrameCue, ObservationGovernor
from star.stream_vision_host import StreamVisionHost


class Rig:
    def __init__(self, *, timeout_ms=5000):
        self.now = [1000.0]
        self.cpu = [100, 1000]
        self.used_vram = 2000
        self.hardware = RealtimeTelemetryHost(
            gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": self.used_vram},
            memory_probe=lambda: (32768, 10000),
            cpu_probe=lambda: tuple(self.cpu), clock_ms=lambda: self.now[0],
        )
        self.hardware.set_context(
            live=False, game_active=False, owner_approved=True,
        )
        self.host = StreamVisionHost(
            telemetry=self.hardware,
            governor=ObservationGovernor(ticket_timeout_ms=timeout_ms),
            clock_ms=lambda: self.now[0],
        )
        self.host.enable(owner_approved=True, capture_approved=True)

    def fresh(self):
        assert self.hardware.refresh_hardware()
        self.cpu[0] += 10
        self.cpu[1] += 100
        assert self.hardware.refresh_hardware()
        assert self.hardware.snapshot() is not None

    def sample(self, *, captured=None, pixels=None, **kwargs):
        return self.host.consider_pixels(
            bytes(96 * 96) if pixels is None else pixels,
            captured_ms=self.now[0] if captured is None else captured,
            width=96, height=96, pixel_format="GRAY", **kwargs,
        )


def test_telemetry_missing_skips_all_pixels_and_never_grants_lease():
    rig = Rig()
    with patch.object(FrameCue, "from_pixels", side_effect=AssertionError("read pixel")):
        outcome = rig.sample(pixels="invalid buffer")
    assert not outcome.admitted
    assert outcome.reason == "trusted_hardware_game_audio_missing"
    assert rig.host.status()["pixel_preflight_skipped"] == 1
    assert rig.host.status()["pixel_fingerprinted"] == 0
    assert not rig.host.status()["inflight"]


def test_busy_inference_skips_fingerprints_then_accepts_after_worker_stop():
    rig = Rig()
    rig.fresh()
    start = rig.sample(focus_regions=((5, 5, 30, 30),))
    assert start.admitted and start.lease is not None
    with patch.object(FrameCue, "from_pixels", side_effect=AssertionError("read pixel")):
        rejected = rig.sample(pixels="invalid buffer")
    assert rejected.reason == "vision_request_already_in_flight"
    assert rig.host.status()["pixel_fingerprinted"] == 1
    assert rig.host.status()["pixel_preflight_skipped"] == 1
    assert rig.host.acknowledge_worker_stopped(
        start.lease, worker_stopped=True, succeeded=True,
    )
    rig.now[0] += 1200
    rig.fresh()
    # A genuinely different frame can still pass the ordinary sensor path.
    next_ = rig.sample(pixels=bytes([255]) * (96 * 96))
    assert next_.admitted and next_.lease is not None
    assert rig.host.status()["pixel_fingerprinted"] == 2


def test_expired_inflight_worker_never_frees_gpu_without_stop_proof():
    rig = Rig(timeout_ms=1000)
    rig.fresh()
    first = rig.sample()
    assert first.admitted
    rig.now[0] += 1200
    rig.fresh()
    with patch.object(FrameCue, "from_pixels", side_effect=AssertionError("read pixel")):
        blocked = rig.sample(pixels="invalid buffer")
    assert blocked.reason == "vision_worker_stop_unconfirmed"
    assert rig.host.status()["inflight"]
    assert not rig.host.acknowledge_worker_stopped(
        first.lease, worker_stopped=False, succeeded=False,
    )
    assert not rig.host.acknowledge_worker_stopped(
        first.lease, worker_stopped=True, succeeded=True,
    )
    assert not rig.host.status()["inflight"]
    assert not rig.host.status()["quarantined"]


@pytest.mark.parametrize("delta", [-9000, 9000])
def test_old_or_future_raw_frame_skips_sampling(delta):
    rig = Rig()
    rig.now[0] += 10000  # Past timestamp remains valid but out of freshness window.
    rig.fresh()
    with patch.object(FrameCue, "from_pixels", side_effect=AssertionError("read pixel")):
        result = rig.sample(captured=rig.now[0] + delta, pixels="invalid")
    assert result.reason == "frame_stale_or_future_dated"
    assert rig.host.status()["pixel_preflight_skipped"] == 1


@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf"), True, 10**1000])
def test_invalid_capture_clock_is_not_silently_accepted(invalid):
    rig = Rig()
    rig.fresh()
    with pytest.raises(ValueError):
        rig.sample(captured=invalid, pixels="invalid")
    assert rig.host.status()["pixel_fingerprinted"] == 0


def test_invalid_pixel_type_still_rejected_when_eligible():
    rig = Rig()
    rig.fresh()
    with pytest.raises(TypeError):
        rig.sample(pixels="invalid")
    assert rig.host.status()["pixel_fingerprinted"] == 0
    assert not rig.host.status()["inflight"]


def test_preflight_is_not_an_admission_and_cannot_bypass_governor_novelty():
    rig = Rig()
    rig.fresh()
    baseline = rig.sample()
    assert baseline.admitted
    assert rig.host.acknowledge_worker_stopped(
        baseline.lease, worker_stopped=True, succeeded=True,
    )
    rig.now[0] += 1200
    rig.fresh()
    duplicate = rig.sample()
    assert duplicate.reason == "low_visual_novelty"
    assert rig.host.status()["pixel_fingerprinted"] == 2
    assert rig.host.status()["admitted"] == 1


def test_session_disable_never_reads_captured_pixels():
    rig = Rig()
    rig.fresh()
    rig.host.disable()
    with patch.object(FrameCue, "from_pixels", side_effect=AssertionError("read pixel")):
        rejected = rig.sample(pixels="invalid")
    assert rejected.reason == "owner_opt_in_missing"
    assert rig.host.status()["pixel_fingerprinted"] == 0



def test_gpu_pressure_rejects_before_expensive_fingerprint():
    rig = Rig()
    rig.used_vram = 8000
    rig.fresh()
    with patch.object(FrameCue, "from_pixels", side_effect=AssertionError("read pixel")):
        result = rig.sample(pixels="invalid")
    assert not result.admitted
    assert result.reason in {
        "realtime_headroom_unavailable", "insufficient_game_or_voice_headroom",
    }
    assert rig.host.status()["pixel_preflight_skipped"] == 1
    assert rig.host.status()["pixel_fingerprinted"] == 0


def test_malformed_focus_crop_still_fails_on_healthy_device():
    rig = Rig()
    rig.fresh()
    with pytest.raises(ValueError):
        rig.sample(focus_regions=((800, 800, 100, 100),))
    assert rig.host.status()["pixel_fingerprinted"] == 0
    assert rig.host.status()["pixel_preflight_skipped"] == 0
