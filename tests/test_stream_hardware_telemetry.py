"""Offline tests of the actual host telemetry adapter, with deterministic sensors.

No real GPU, microphone, OBS, process enumeration, game or network is used.
The separate hardware smoke gate must run on Star's intended gaming PC.
"""
import math
import pytest

from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_qos import AdaptiveQoS, InferenceJob


class Sensors:
    def __init__(self):
        self.now = 1000.0
        self.cpu = (100, 1000)
        self.gpu = {"vram_total_mib": 8192, "vram_used_mib": 3000}
        self.memory = (32768, 21000)
        self.calls = 0

    def gpu_probe(self):
        self.calls += 1
        return self.gpu

    def cpu_probe(self):
        return self.cpu

    def ram_probe(self):
        return self.memory

    def advance(self, ms):
        self.now += ms
        return self.now

    def cpu_tick(self, busy=10, total=100):
        self.cpu = (self.cpu[0] + busy, self.cpu[1] + total)


def host(sensors, *, live=True, game=True):
    h = RealtimeTelemetryHost(
        gpu_probe=sensors.gpu_probe,
        memory_probe=sensors.ram_probe,
        cpu_probe=sensors.cpu_probe,
        clock_ms=lambda: sensors.now,
    )
    h.set_context(live=live, game_active=game, owner_approved=True)
    return h


def frames(h, s, count=22, duration=16):
    for _ in range(count):
        s.advance(duration)
        assert h.presented_frame(s.now)


def ready(*, live=True, game=True, count=22, duration=16):
    s = Sensors()
    h = host(s, live=live, game=game)
    assert h.refresh_hardware()  # CPU load not known until second poll
    s.cpu_tick()
    s.advance(100)
    assert h.refresh_hardware()
    if game:
        frames(h, s, count=count, duration=duration)
    if live or game:
        assert h.report_audio_backlog(backlog_ms=20, at_ms=s.now)
    s.cpu_tick()
    assert h.refresh_hardware()
    return h, s


def test_permission_type_and_disabled_defaults():
    s = Sensors()
    h = RealtimeTelemetryHost(gpu_probe=s.gpu_probe, memory_probe=s.ram_probe,
                              cpu_probe=s.cpu_probe, clock_ms=lambda: s.now)
    assert h.snapshot() is None
    assert not h.refresh_hardware()
    with pytest.raises(PermissionError):
        h.set_context(live=True, game_active=True)
    with pytest.raises(ValueError):
        h.set_context(live=1, game_active=True, owner_approved=True)
    with pytest.raises(ValueError):
        RealtimeTelemetryHost(cpu_slots=0)
    assert s.calls == 0  # no I/O from a disabled instance


def test_live_game_backlog_and_fps_produce_real_snapshots():
    h, s = ready()
    result = h.snapshot()
    assert result is not None
    assert result.telemetry.live is True
    assert result.telemetry.game_active is True
    assert result.telemetry.free_vram_mib == 5192
    assert result.telemetry.total_vram_mib == 8192
    assert result.telemetry.game_fps == pytest.approx(62.5)
    assert result.telemetry.speech_backlog_ms == 20
    assert result.qos is not None
    assert result.qos.cpu_busy_percent == pytest.approx(10)
    assert result.qos.free_ram_mib == 21000
    assert result.game_frame_intervals == 21
    assert result.hardware_age_ms == 0
    assert h.status()["frames"] == 22


def test_qos_host_data_can_drive_existing_admission_without_pretending_faster():
    h, s = ready()
    sample = h.snapshot()
    q = AdaptiveQoS()
    q.enable(owner_approved=True)
    request = InferenceJob(
        "speech-test", "speech", s.now, s.now + 1500, 150, 300, "auto"
    )
    choice = q.admit(request, sample.qos, now_ms=s.now)
    assert choice.admitted and choice.device == "cpu"
    s.advance(70)
    assert q.finish(choice.ticket, now_ms=s.now, succeeded=True)
    assert q.status()["completed"] == 1
    # This verifies data flow, NOT a measured model-inference speedup.


def test_no_performance_measurement_imputed_from_gpu_load():
    s = Sensors()
    h = host(s)
    assert h.refresh_hardware()
    s.cpu_tick()
    s.advance(100)
    assert h.refresh_hardware()
    h.report_audio_backlog(backlog_ms=0, at_ms=s.now)
    # Memory and GPU health alone cannot establish game FPS.
    assert h.snapshot() is None
    frames(h, s, count=8)
    assert h.snapshot() is None  # only seven completed frame intervals
    frames(h, s, count=1)
    assert h.snapshot() is not None


def test_first_hardware_poll_does_not_invent_cpu_percent():
    s = Sensors()
    h = host(s, live=False, game=False)
    assert h.refresh_hardware()
    first = h.snapshot()
    assert first is not None
    assert first.telemetry.game_fps == 0
    assert first.qos is None
    s.cpu_tick(34, 100)
    s.advance(50)
    assert h.refresh_hardware()
    assert h.snapshot().qos.cpu_busy_percent == pytest.approx(34)


def test_stutter_guard_reports_lower_tail_not_peak_fps():
    h, s = ready(count=15)
    regular = h.snapshot().telemetry.game_fps
    for i in range(15):
        s.advance(90 if i % 3 == 0 else 16)
        assert h.presented_frame(s.now)
    assert h.report_audio_backlog(backlog_ms=0, at_ms=s.now)
    assert h.refresh_hardware()
    new = h.snapshot()
    assert new is not None
    assert new.telemetry.game_fps < regular / 2


def test_missing_live_speaker_data_fails_closed_even_with_real_fps():
    s = Sensors()
    h = host(s)
    assert h.refresh_hardware()
    frames(h, s)
    assert h.refresh_hardware()
    assert h.snapshot() is None
    assert h.report_audio_backlog(backlog_ms=180, at_ms=s.now)
    assert h.snapshot() is not None
    s.advance(501)
    assert h.snapshot() is None


def test_sound_speaker_backlog_adapted_without_capturing_audio():
    class GoodSpeaker:
        def pending_seconds(self):
            return .035
    h, s = ready()
    assert h.sample_speaker(GoodSpeaker())
    assert h.snapshot().telemetry.speech_backlog_ms == 35

    class BadSpeaker:
        def pending_seconds(self):
            return float("inf")
    assert not h.sample_speaker(BadSpeaker())
    assert h.snapshot() is None


def test_expired_hardware_fails_closed_and_snapshot_performs_no_io():
    h, s = ready(live=False, game=False)
    count = s.calls
    assert h.snapshot() is not None
    assert h.snapshot() is not None
    assert s.calls == count
    s.advance(1201)
    assert h.snapshot() is None
    assert s.calls == count


def test_live_qos_snapshot_refuses_stale_resources_before_stage_snapshot():
    h, s = ready()
    frames(h, s, count=16, duration=16)  # contiguous real frames while GPU probe ages
    assert h.report_audio_backlog(backlog_ms=15, at_ms=s.now)
    data = h.snapshot()
    assert data is not None
    assert data.qos is None  # AdaptiveQoS needs <=250 ms LIVE sensor age


def test_invalid_and_missing_gpu_probe_cannot_reuse_old_vram():
    h, s = ready()
    assert h.snapshot() is not None
    s.gpu = {"vram_total_mib": 8192, "vram_used_mib": 8300}
    assert not h.refresh_hardware()
    assert h.snapshot() is None
    assert not h.status()["hardware_ready"]


@pytest.mark.parametrize("value", [
    {"vram_total_mib": 8192, "vram_used_mib": -1},
    {"vram_total_mib": False, "vram_used_mib": 0},
    {"vram_total_mib": math.nan, "vram_used_mib": 10},
    None,
])
def test_malformed_gpu_readings_are_not_considered_spare_resources(value):
    s = Sensors()
    s.gpu = value
    h = host(s, live=False, game=False)
    assert not h.refresh_hardware()
    assert h.snapshot() is None


def test_repeated_duplicate_or_future_frames_do_not_raise_fps():
    h, s = ready()
    first = h.snapshot().telemetry.game_fps
    assert not h.presented_frame(s.now)  # duplicate
    assert not h.presented_frame(s.now + 100)  # future
    assert h.snapshot().telemetry.game_fps == pytest.approx(first)
    assert not h.report_audio_backlog(backlog_ms=1, at_ms=s.now + 100)


def test_frame_gap_invalidates_old_fps_until_new_frames_arrive():
    h, s = ready()
    assert h.snapshot() is not None
    s.advance(300)
    assert h.presented_frame(s.now)
    h.report_audio_backlog(backlog_ms=0, at_ms=s.now)
    assert h.snapshot() is None
    frames(h, s, count=9)
    assert h.snapshot() is not None


def test_session_changes_invalidate_stale_audio_scene_and_gpu_claims():
    h, s = ready()
    assert h.snapshot() is not None
    h.set_context(live=True, game_active=False, owner_approved=True)
    assert h.snapshot() is None
    assert h.refresh_hardware()
    assert h.snapshot() is None  # audio not supplied for new session
    h.report_audio_backlog(backlog_ms=0, at_ms=s.now)
    assert h.snapshot() is not None
    h.disable()
    assert h.snapshot() is None
    assert not h.refresh_hardware()


def test_blocking_inflight_gpu_probe_cannot_revive_disabled_session():
    s = Sensors()
    holder = {}
    def disabling_gpu():
        holder["host"].disable()
        return s.gpu
    h = RealtimeTelemetryHost(
        gpu_probe=disabling_gpu, memory_probe=s.ram_probe,
        cpu_probe=s.cpu_probe, clock_ms=lambda: s.now
    )
    holder["host"] = h
    h.set_context(live=False, game_active=False, owner_approved=True)
    assert not h.refresh_hardware()
    assert h.snapshot() is None


def test_cpu_and_mem_probe_failures_clear_old_snapshot():
    h, s = ready(live=False, game=False)
    assert h.snapshot() is not None
    s.memory = (32768, 50000)
    assert not h.refresh_hardware()
    assert h.snapshot() is None


def test_audio_timestamps_and_long_backlogs_are_rejected():
    h, s = ready()
    with pytest.raises(ValueError):
        h.report_audio_backlog(backlog_ms=-1, at_ms=s.now)
    with pytest.raises(ValueError):
        h.report_audio_backlog(backlog_ms=math.inf, at_ms=s.now)
    with pytest.raises(ValueError):
        h.report_audio_backlog(backlog_ms=120001, at_ms=s.now)
    assert not h.report_audio_backlog(backlog_ms=0, at_ms=s.now - 900)
    assert not h.report_audio_backlog(backlog_ms=0, at_ms=s.now + 99)
