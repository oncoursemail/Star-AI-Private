"""Deterministic offline tests for measured, owner-approved vision admission.

No real GPU, game, model, capture, audio, network, or broadcast is used.
"""
from dataclasses import replace

import pytest

from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_observe import FrameCue, ObservationGovernor
from star.stream_vision_host import StreamVisionHost


class Sensors:
    def __init__(self):
        self.now = 1000.0
        self.cpu = (100, 1000)
        self.used_vram = 3000
        self.game_active = False

    def advance(self, ms):
        self.now += ms
        return self.now

    def tick_cpu(self):
        self.cpu = (self.cpu[0] + 10, self.cpu[1] + 100)

    def telemetry(self, *, live=False, game=False):
        self.game_active = game
        h = RealtimeTelemetryHost(
            gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": self.used_vram},
            memory_probe=lambda: (32768, 21000),
            cpu_probe=lambda: self.cpu,
            clock_ms=lambda: self.now,
        )
        h.set_context(live=live, game_active=game, owner_approved=True)
        return h

    def fresh(self, host):
        assert host.refresh_hardware()
        self.tick_cpu()
        assert host.refresh_hardware()
        if self.game_active:
            for _ in range(12):
                self.advance(16)
                assert host.presented_frame(self.now)
        if self.game_active:
            assert host.report_audio_backlog(backlog_ms=30, at_ms=self.now)
        assert host.snapshot() is not None
        assert host.snapshot().qos is not None


def setup(*, live=False, game=False, ticket_timeout=5000):
    s = Sensors()
    hardware = s.telemetry(live=live, game=game)
    governor = ObservationGovernor(ticket_timeout_ms=ticket_timeout)
    app = StreamVisionHost(
        telemetry=hardware, governor=governor, clock_ms=lambda: s.now
    )
    return s, hardware, governor, app


def test_opt_in_and_unmeasured_cpu_silence():
    s, hardware, _, app = setup()
    assert app.consider(FrameCue(s.now, 0)).reason == "owner_opt_in_missing"
    with pytest.raises(PermissionError):
        app.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        app.enable(capture_approved=True)
    app.enable(owner_approved=True, capture_approved=True)
    assert app.consider(FrameCue(s.now, 0)).reason == "trusted_hardware_game_audio_missing"
    # First GPU sample is not proof of CPU headroom.
    assert hardware.refresh_hardware()
    assert app.consider(FrameCue(s.now, 0)).reason == "trusted_hardware_game_audio_missing"
    s.tick_cpu()
    assert hardware.refresh_hardware()
    assert app.consider(FrameCue(s.now, 0)).admitted


def test_verified_host_sample_accepts_and_ends_single_worker():
    s, hardware, _, app = setup(live=True, game=True)
    s.fresh(hardware)
    app.enable(owner_approved=True, capture_approved=True)
    first = app.consider(FrameCue(s.now, 0xDEADBEEF, "objective"))
    assert first.admitted and first.lease is not None
    assert first.target_fps == 1
    blocked = app.consider(FrameCue(s.now, 0xABC, "win"))
    assert blocked.reason == "vision_request_already_in_flight"
    assert app.status()["inflight"]
    s.advance(50)
    assert app.acknowledge_worker_stopped(
        first.lease, worker_stopped=True, succeeded=True
    )
    assert not app.status()["inflight"]
    assert app.status()["completed"] == 1
    assert 0xDEADBEEF not in app.status().values()


def test_no_untrusted_worker_success_and_mismatched_ticket():
    s, hardware, _, app = setup()
    s.fresh(hardware)
    app.enable(owner_approved=True, capture_approved=True)
    admitted = app.consider(FrameCue(s.now, 12))
    assert admitted.admitted
    forged = replace(admitted.lease)
    assert not app.acknowledge_worker_stopped(
        forged, worker_stopped=True, succeeded=True
    )
    assert not app.acknowledge_worker_stopped(
        admitted.lease, worker_stopped=False, succeeded=True
    )
    assert app.status()["inflight"]
    s.advance(10)
    assert app.acknowledge_worker_stopped(
        admitted.lease, worker_stopped=True, succeeded=True
    )
    assert not app.acknowledge_worker_stopped(
        admitted.lease, worker_stopped=True, succeeded=True
    )
    assert app.status()["stale_lease"] == 2


def test_failed_worker_is_released_but_never_counted_successful():
    s, hardware, _, app = setup()
    s.fresh(hardware)
    app.enable(owner_approved=True, capture_approved=True)
    admitted = app.consider(FrameCue(s.now, 12))
    s.advance(30)
    assert not app.acknowledge_worker_stopped(
        admitted.lease, worker_stopped=True, succeeded=False
    )
    assert app.status()["discarded"] == 1
    assert app.status()["stopped"] == 1
    assert not app.status()["inflight"]


def test_expired_worker_blocks_reentry_even_with_fresh_hardware():
    s, hardware, _, app = setup(ticket_timeout=1000)
    s.fresh(hardware)
    app.enable(owner_approved=True, capture_approved=True)
    first = app.consider(FrameCue(s.now, 1))
    s.advance(1200)
    s.fresh(hardware)  # the device is healthy, but previous inference may still run!
    next_ = app.consider(FrameCue(s.now, 2))
    assert next_.reason == "vision_worker_stop_unconfirmed"
    assert app.status()["quarantined"]
    assert app.status()["inflight"]
    assert not app.acknowledge_worker_stopped(
        first.lease, worker_stopped=False
    )
    assert not app.acknowledge_worker_stopped(
        first.lease, worker_stopped=True, succeeded=True
    )
    assert app.status()["stopped"] == 1
    assert app.status()["discarded"] == 1
    assert not app.status()["quarantined"]
    again = app.consider(FrameCue(s.now, 3))
    assert again.admitted


def test_disable_preserves_worker_and_refuses_new_session():
    s, hardware, _, app = setup()
    s.fresh(hardware)
    app.enable(owner_approved=True, capture_approved=True)
    old = app.consider(FrameCue(s.now, 1))
    app.disable()
    assert app.status()["inflight"] and app.status()["quarantined"]
    with pytest.raises(RuntimeError):
        app.enable(owner_approved=True, capture_approved=True)
    # An old result cannot become a valid new-session outcome.
    s.advance(10)
    assert not app.acknowledge_worker_stopped(
        old.lease, worker_stopped=True, succeeded=True
    )
    app.enable(owner_approved=True, capture_approved=True)
    new = app.consider(FrameCue(s.now, 1))
    assert new.admitted and new.lease.ticket != old.lease.ticket
    assert not app.acknowledge_worker_stopped(
        old.lease, worker_stopped=True, succeeded=True
    )


def test_missing_or_stale_hardware_is_not_replaced_by_guess():
    s, hardware, _, app = setup()
    s.fresh(hardware)
    app.enable(owner_approved=True, capture_approved=True)
    s.advance(1400)
    choice = app.consider(FrameCue(s.now, 1))
    assert choice.reason == "trusted_hardware_game_audio_missing"
    assert app.status()["missing_sensor"] == 1
    assert not app.status()["inflight"]
    s.fresh(hardware)
    assert app.consider(FrameCue(s.now, 1)).admitted


def test_game_fps_and_speech_headroom_from_real_presents():
    s, hardware, _, app = setup(live=True, game=True)
    s.fresh(hardware)
    app.enable(owner_approved=True, capture_approved=True)
    # Authoritative GPU pressure defers vision even for an interesting event.
    s.used_vram = 7800
    s.tick_cpu()
    assert hardware.refresh_hardware()
    decision = app.consider(FrameCue(s.now, 42, "win"))
    assert decision.reason == "realtime_headroom_unavailable"
    assert not app.status()["inflight"]


def test_frame_staleness_is_checked_against_host_clock():
    s, hardware, _, app = setup()
    s.advance(2000)
    s.fresh(hardware)
    app.enable(owner_approved=True, capture_approved=True)
    assert app.consider(FrameCue(s.now - 2000, 1)).reason == "frame_stale_or_future_dated"
    assert app.consider(FrameCue(s.now + 100, 1)).reason == "frame_stale_or_future_dated"
    assert app.consider(FrameCue(s.now, 1)).admitted


def test_host_clock_and_api_type_boundaries():
    s, hardware, governor, app = setup()
    with pytest.raises(TypeError):
        StreamVisionHost(telemetry=hardware, governor=object())
    with pytest.raises(TypeError):
        StreamVisionHost(telemetry=object(), governor=governor)
    with pytest.raises(TypeError):
        app.consider(object())
    with pytest.raises(TypeError):
        app.acknowledge_worker_stopped(object(), worker_stopped=True)
    with pytest.raises(ValueError):
        StreamVisionHost(telemetry=hardware, governor=governor,
                         clock_ms=lambda: float("nan")).enable(
                             owner_approved=True, capture_approved=True)
    with pytest.raises(ValueError):
        StreamVisionHost(telemetry=hardware, governor=governor,
                         clock_ms=lambda: "123").enable(
                             owner_approved=True, capture_approved=True)
    app.enable(owner_approved=True, capture_approved=True)
    s.fresh(hardware)
    offer = app.consider(FrameCue(s.now, 1))
    with pytest.raises(TypeError):
        app.acknowledge_worker_stopped(offer.lease, worker_stopped="yes")
    assert app.status()["inflight"]
