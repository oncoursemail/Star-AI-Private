"""Model-free Star realtime brain tests; no devices, network, game or speaker."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from star.stream_brain_governor import BrainLease, StreamBrainGovernor
from star.stream_director import StreamSignal
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_qos import AdaptiveQoS, InferenceJob
from star.stream_stage import StarStage


class Sensors:
    def __init__(self):
        self.now = 100_000.0
        self.cpu = (300, 1000)
        self.gpu = {"vram_total_mib": 8192, "vram_used_mib": 2500}
        self.memory = (32768, 20000)
        self.gpu_reads = 0

    def gpu_probe(self):
        self.gpu_reads += 1
        return self.gpu

    def cpu_probe(self):
        return self.cpu

    def memory_probe(self):
        return self.memory

    def tick(self, ms=20):
        self.now += ms
        return self.now

    def cpu_tick(self, busy=10, total=100):
        self.cpu = (self.cpu[0] + busy, self.cpu[1] + total)


def setup(*, live=True, game=True):
    sensors = Sensors()
    hardware = RealtimeTelemetryHost(
        gpu_probe=sensors.gpu_probe, cpu_probe=sensors.cpu_probe,
        memory_probe=sensors.memory_probe, clock_ms=lambda: sensors.now,
    )
    qos = AdaptiveQoS()
    stage = StarStage(clock=lambda: sensors.now / 1000)
    host = StreamBrainGovernor(
        telemetry=hardware, qos=qos, stage=stage,
        clock_ms=lambda: sensors.now,
    )
    host.enable(owner_approved=True, live=live, game_active=game, mode="cat")
    return host, sensors, hardware, qos, stage


def warm(s, hardware, *, game=True, live=True, interval=16):
    assert hardware.refresh_hardware()
    s.cpu_tick()
    s.tick(100)
    assert hardware.refresh_hardware()
    if game:
        for _ in range(23):
            s.tick(interval)
            assert hardware.presented_frame(s.now)
    if game or live:
        assert hardware.report_audio_backlog(backlog_ms=20, at_ms=s.now)
    s.cpu_tick()
    assert hardware.refresh_hardware()


def job(s, name="voice", kind="speech", device="auto", vram=200,
        ttl=1500):
    return InferenceJob(
        name, kind, s.now, s.now + ttl, 120, vram, device
    )


def signal(s, *, ident="e1", kind="game_success", evidence="observed"):
    return StreamSignal(
        ident, kind, s.now / 1000, "Star cleared the next ledge", evidence=evidence
    )


def test_consent_no_side_effects():
    s = Sensors()
    t = RealtimeTelemetryHost(
        gpu_probe=s.gpu_probe, cpu_probe=s.cpu_probe,
        memory_probe=s.memory_probe, clock_ms=lambda: s.now,
    )
    q = AdaptiveQoS()
    st = StarStage(clock=lambda: s.now / 1000)
    g = StreamBrainGovernor(
        telemetry=t, qos=q, stage=st, clock_ms=lambda: s.now
    )
    with pytest.raises(PermissionError):
        g.enable(live=True, game_active=True)
    assert g.status()["enabled"] is False
    assert s.gpu_reads == 0
    assert not g.offer(signal(s))
    assert g.prepare() is None
    assert g.admit(job(s)).reason == "owner_opt_in_missing"


@pytest.mark.parametrize("live,game", [(False, False), (True, False),
                                        (False, True), (True, True)])
def test_all_consent_modes(live, game):
    g, s, t, q, st = setup(live=live, game=game)
    assert t.status()["live"] == live
    assert t.status()["game_active"] == game
    warm(s, t, game=game, live=live)
    assert g.admit(job(s)).admitted
    assert t.status()["poll_ok"] >= 3


@pytest.mark.parametrize("item", [None, 1, "yes", float("nan")])
def test_invalid_context_flags_rejected(item):
    s = Sensors()
    h = RealtimeTelemetryHost(
        gpu_probe=s.gpu_probe, cpu_probe=s.cpu_probe,
        memory_probe=s.memory_probe, clock_ms=lambda: s.now,
    )
    g = StreamBrainGovernor(
        telemetry=h, qos=AdaptiveQoS(),
        stage=StarStage(clock=lambda: s.now / 1000),
        clock_ms=lambda: s.now,
    )
    with pytest.raises(ValueError):
        g.enable(owner_approved=True, live=item, game_active=True)


def test_missing_hardware_cpu_frame_audio_never_invents_work_eligibility():
    g, s, t, q, st = setup()
    assert not g.admit(job(s)).admitted
    assert g.prepare() is None
    assert t.refresh_hardware()
    assert not g.admit(job(s)).admitted
    s.cpu_tick()
    s.tick(10)
    assert t.refresh_hardware()
    assert not g.admit(job(s)).admitted  # no game frames
    for _ in range(23):
        s.tick(16)
        t.presented_frame(s.now)
    assert not g.admit(job(s)).admitted  # no speaker queue
    assert t.report_audio_backlog(backlog_ms=25, at_ms=s.now)
    assert not g.admit(job(s)).admitted  # stale CPU/GPU >250ms live
    s.cpu_tick()
    assert t.refresh_hardware()
    assert g.admit(job(s)).admitted


def test_enabled_brain_uses_real_snapshot_and_device_pref_for_live_speech():
    g, s, t, q, st = setup()
    warm(s, t)
    calls = s.gpu_reads
    a = g.admit(job(s))
    assert a.admitted and a.lease is not None
    assert a.lease.device == "cpu"
    assert a.predicted_p95_ms is None  # no fake latency measurement
    assert a.reason == "unmeasured_host_must_verify"
    assert s.gpu_reads == calls  # snapshot MUST NOT call nvidia-smi
    s.tick(45)
    assert g.acknowledge_worker_stopped(
        a.lease, worker_stopped=True, succeeded=True
    )
    assert q.status()["completed"] == 1


def test_duplicate_one_shot_ids_and_fabricated_tickets_rejected():
    g, s, t, q, st = setup()
    warm(s, t)
    a = g.admit(job(s))
    assert a.admitted
    assert g.admit(job(s)).reason == "duplicate_one_shot_job_id"
    copied = BrainLease(
        a.lease.generation, a.lease.ticket, a.lease.device,
        a.lease.kind, a.lease.expires_ms,
    )
    assert not g.acknowledge_worker_stopped(
        copied, worker_stopped=True, succeeded=True
    )
    assert g.status()["reserved_workers"] == 1
    assert g.acknowledge_worker_stopped(a.lease, worker_stopped=True, succeeded=True)
    assert not g.acknowledge_worker_stopped(a.lease, worker_stopped=True, succeeded=True)


def test_cancel_request_never_releases_held_gpu_memory():
    g, s, t, q, st = setup()
    warm(s, t)
    a = g.admit(job(s, "vision", "vision", "gpu"))
    # Live vision has no real calibration, cannot claim work is safe.
    assert not a.admitted
    other = g.admit(job(s, "voice", "speech", "cpu"))
    assert other.admitted
    assert not g.acknowledge_worker_stopped(other.lease, worker_stopped=False)
    assert g.status()["reserved_workers"] == 1
    assert q.status()["inflight"] == 1
    assert g.acknowledge_worker_stopped(
        other.lease, worker_stopped=True, succeeded=False
    ) is False
    assert g.status()["reserved_workers"] == 0


def test_disabled_reservations_quarantined_until_worker_stop_ack():
    g, s, t, q, st = setup()
    warm(s, t)
    a = g.admit(job(s))
    g.disable()
    assert g.status()["pending_hardware_stop"] == 1
    assert q.status()["inflight"] == 1
    with pytest.raises(RuntimeError):
        g.enable(owner_approved=True, live=True, game_active=True)
    assert not g.acknowledge_worker_stopped(a.lease, worker_stopped=False)
    s.tick(200)
    assert not g.acknowledge_worker_stopped(
        a.lease, worker_stopped=True, succeeded=True
    )
    assert q.status()["inflight"] == 0
    g.enable(owner_approved=True, live=True, game_active=True)
    assert g.status()["enabled"]


def test_expired_worker_lease_does_not_train_speed_and_never_frees_early():
    g, s, t, q, st = setup()
    warm(s, t)
    a = g.admit(job(s, ttl=500))
    assert a.admitted
    s.tick(1000)
    assert not g.acknowledge_worker_stopped(a.lease, worker_stopped=False)
    assert not g.acknowledge_worker_stopped(
        a.lease, worker_stopped=True, succeeded=True
    )
    assert q.status()["completed"] == 0
    assert g.status()["reserved_workers"] == 0


def test_background_learning_and_render_are_paused_live():
    g, s, t, q, st = setup()
    warm(s, t)
    for kind in ("research", "training", "render"):
        choice = g.admit(job(s, kind, kind, "auto"))
        assert not choice.admitted
        assert choice.reason == "protect_live_stream_from_background_work"


def test_game_low_fps_protects_nonessential_jobs():
    g, s, t, q, st = setup()
    warm(s, t)
    for _ in range(20):
        s.tick(93)
        t.presented_frame(s.now)
    assert t.report_audio_backlog(backlog_ms=22, at_ms=s.now)
    s.cpu_tick()
    assert t.refresh_hardware()
    assert t.snapshot().telemetry.game_fps < 50
    a = g.admit(job(s, "explain", "commentary"))
    assert not a.admitted and a.reason == "game_or_voice_backpressure"
    speech = g.admit(job(s, "voice"))
    assert speech.admitted and speech.lease.device == "cpu"


def test_speech_goes_quiet_if_telemetry_missing_and_owner_chat_is_moderated():
    g, s, t, q, st = setup()
    assert not g.offer(StreamSignal(
        "x", "viewer_question", s.now / 1000, "what game?", "viewer1"
    ))
    viewer = StreamSignal(
        "y", "viewer_question", s.now / 1000, "How do I jump?", "viewer2"
    )
    assert g.offer(viewer, moderated=True)
    assert g.prepare() is None  # never start inference without actual sensors
    warm(s, t)
    prepared = g.prepare()
    assert prepared is not None
    assert prepared.kind == "viewer_question"
    assert prepared.mode == "cat"
    assert prepared.user_message()["role"] == "user"
    assert not g.acknowledge_audible(prepared)
    speech = g.admit(job(s, "stream-speech"))
    assert speech.admitted
    assert g.queue_audio(prepared, speech_lease=speech.lease)
    assert not g.acknowledge_audible(prepared)
    assert g.acknowledge_audible(prepared, sound_device_confirmed=True)
    assert st.current(prepared)
    assert g.finish_audio(prepared, device_playback_finished=True)
    assert not st.current(prepared)
    assert st.metrics()["director"]["completed"] == 1


def test_tts_queue_invalidated_when_live_sensor_ages_out():
    g, s, t, q, st = setup()
    warm(s, t)
    assert g.offer(signal(s))
    p = g.prepare()
    assert p is not None
    speech = g.admit(job(s, "stream-speech"))
    assert speech.admitted
    s.tick(750)
    assert not g.queue_audio(p, speech_lease=speech.lease)
    assert st.metrics()["phase"] == "idle"
    assert g.status()["audio_abandoned"] == 1


def test_queue_is_not_first_audible_and_audio_failure_not_success():
    g, s, t, q, st = setup()
    warm(s, t)
    assert g.offer(signal(s))
    p = g.prepare()
    speech = g.admit(job(s, "stream-speech"))
    assert speech.admitted
    assert g.queue_audio(p, speech_lease=speech.lease)
    assert st.metrics()["director"]["completed"] == 0
    assert g.finish_audio(p, device_playback_finished=False)
    assert st.metrics()["director"]["completed"] == 0


def test_disable_with_active_audio_requires_physical_ack():
    g, s, t, q, st = setup()
    warm(s, t)
    g.offer(signal(s))
    p = g.prepare()
    speech = g.admit(job(s, "stream-speech"))
    assert speech.admitted
    assert g.queue_audio(p, speech_lease=speech.lease)
    with pytest.raises(RuntimeError, match="sound device"):
        g.disable()
    assert g.status()["enabled"]
    g.disable(audio_stopped_and_flushed=True)
    assert not st.current(p)
    assert not g.acknowledge_audible(p, sound_device_confirmed=True)


def test_new_game_session_cannot_reuse_old_frames_or_audio():
    g, s, t, q, st = setup()
    warm(s, t)
    assert g.prepare() is None
    g.disable()
    g.enable(owner_approved=True, live=True, game_active=True)
    assert not g.admit(job(s)).admitted
    assert not g.prepare()
    warm(s, t)
    assert g.admit(job(s, "fresh")).admitted


def test_viewer_event_does_not_reveal_private_text_in_status():
    g, s, t, q, st = setup()
    warm(s, t)
    viewer = StreamSignal(
        "v", "viewer_comment", s.now / 1000,
        "SECRET private bank-account and password", "viewer-X"
    )
    assert g.offer(viewer, moderated=True)
    assert "SECRET" not in repr(g.status())
    assert "viewer-X" not in repr(g.status())


def test_exact_same_lease_stopping_race_accepted_once():
    g, s, t, q, st = setup()
    warm(s, t)
    one = g.admit(job(s))
    assert one.admitted
    with ThreadPoolExecutor(max_workers=8) as ex:
        answers = list(ex.map(
            lambda _: g.acknowledge_worker_stopped(
                one.lease, worker_stopped=True, succeeded=True
            ), range(8)
        ))
    assert answers.count(True) == 1
    assert g.status()["reserved_workers"] == 0
    assert q.status()["completed"] == 1


def test_stage_controller_no_audio_if_pressure():
    g, s, t, q, st = setup()
    warm(s, t)
    assert g.offer(StreamSignal(
        "m", "viewer_question", s.now / 1000, "Hi", "viewer1"
    ), moderated=True)
    for _ in range(20):
        s.tick(90)
        assert t.presented_frame(s.now)
    assert t.report_audio_backlog(backlog_ms=400, at_ms=s.now)
    s.cpu_tick()
    assert t.refresh_hardware()
    assert g.prepare() is None  # defer in difficult gameplay/high TTS backlog


def test_host_clock_must_be_finite_no_model_estimates():
    s = Sensors()
    t = RealtimeTelemetryHost(
        gpu_probe=s.gpu_probe, cpu_probe=s.cpu_probe,
        memory_probe=s.memory_probe, clock_ms=lambda: s.now,
    )
    g = StreamBrainGovernor(
        telemetry=t, qos=AdaptiveQoS(),
        stage=StarStage(clock=lambda: s.now / 1000),
        clock_ms=lambda: float("nan")
    )
    with pytest.raises(ValueError, match="clock"):
        g.enable(owner_approved=True, live=True, game_active=True)
    assert s.gpu_reads == 0

def test_bare_or_fabricated_audio_reservation_never_queues_sound():
    g, s, t, q, st = setup()
    warm(s, t)
    g.offer(signal(s))
    p = g.prepare()
    a = g.admit(job(s, "legit"))
    assert a.admitted
    forged = BrainLease(
        a.lease.generation, a.lease.ticket, a.lease.device,
        a.lease.kind, a.lease.expires_ms
    )
    with pytest.raises(TypeError):
        g.queue_audio(p, speech_lease=None)
    assert not g.queue_audio(p, speech_lease=forged)
    assert st.metrics()["phase"] == "prepared"
    assert g.queue_audio(p, speech_lease=a.lease)
    assert not g.queue_audio(p, speech_lease=a.lease)


def test_vision_or_research_lease_cannot_start_voice():
    g, s, t, q, st = setup(live=False, game=False)
    warm(s, t, game=False, live=False)
    g.offer(signal(s))
    p = g.prepare()
    a = g.admit(job(s, "research-lease", "research"))
    assert a.admitted
    assert not g.queue_audio(p, speech_lease=a.lease)
    b = g.admit(job(s, "voice-lease", "speech"))
    assert b.admitted
    assert g.queue_audio(p, speech_lease=b.lease)


def test_expired_audio_reservation_rejected_no_fake_expiration_extension():
    g, s, t, q, st = setup()
    warm(s, t)
    g.offer(signal(s))
    p = g.prepare()
    speech = g.admit(job(s, "voice-lease", ttl=500))
    assert speech.admitted
    s.tick(501)
    assert not g.queue_audio(p, speech_lease=speech.lease)
    assert st.metrics()["phase"] == "prepared"
    assert not g.acknowledge_audible(p, sound_device_confirmed=True)


def test_one_audio_lease_cannot_bind_two_turns_and_acked_audio_cannot_replay():
    g, s, t, q, st = setup()
    warm(s, t)
    g.offer(signal(s))
    p = g.prepare()
    speech = g.admit(job(s, "live-voice"))
    assert speech.admitted
    assert g.queue_audio(p, speech_lease=speech.lease)
    assert g.acknowledge_audible(p, sound_device_confirmed=True)
    assert not g.queue_audio(p, speech_lease=speech.lease)
    assert g.finish_audio(p, device_playback_finished=True)
    assert not g.acknowledge_audible(p, sound_device_confirmed=True)
    assert not g.finish_audio(p, device_playback_finished=True)
