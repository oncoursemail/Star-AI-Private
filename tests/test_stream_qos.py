"""Deterministic model-free checks for the STAR live inference QoS advisor."""
import pytest

from star.stream_budget import StreamTelemetry
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSSnapshot


def stream(*, live=False, game=False, vram=6000, fps=60, backlog=0):
    return StreamTelemetry(live, game, vram, 8192, fps, backlog)


def snap(at, *, live=False, game=False, vram=6000, fps=60, backlog=0,
         ram=16000, cpu=20, cpu_slots=2, gpu_slots=1):
    return QoSSnapshot(
        at, stream(live=live, game=game, vram=vram, fps=fps, backlog=backlog),
        ram, cpu, cpu_slots, gpu_slots,
    )


def job(ident, at, *, kind="speech", device="auto", ram=100, vram=500,
        ttl=1600):
    return InferenceJob(ident, kind, at, at + ttl, ram, vram, device)


def ready():
    q = AdaptiveQoS()
    q.enable(owner_approved=True)
    return q


def train_route(q, *, kind, device, start=1000, duration=200, steps=5):
    """Realistic synthetic host acknowledgements; NOT a hardware measurement."""
    for index in range(steps):
        at = start + index * 3000
        attempt = q.admit(
            job(f"cal-{kind}-{device}-{index}", at,
                kind=kind, device=device, ttl=duration + 600),
            snap(at), now_ms=at,
        )
        assert attempt.admitted, attempt.reason
        assert attempt.device == device
        assert q.finish(attempt.ticket, now_ms=at + duration, succeeded=True)


def test_owner_consent_and_no_unapproved_calls():
    q = AdaptiveQoS()
    with pytest.raises(PermissionError):
        q.enable()
    rejected = q.admit(job("one", 500), snap(500), now_ms=500)
    assert not rejected.admitted
    assert rejected.reason == "owner_opt_in_missing"
    assert q.status()["admitted"] == 0


def test_one_shot_tickets_not_reused_on_restart():
    q = ready()
    first = q.admit(job("once", 100), snap(100), now_ms=100)
    assert first.admitted
    assert q.admit(job("once", 120), snap(120), now_ms=120).reason == (
        "duplicate_one_shot_job_id"
    )
    assert q.finish(first.ticket, now_ms=180, succeeded=True)
    assert not q.finish(first.ticket, now_ms=185, succeeded=True)
    q.disable()
    q.enable(owner_approved=True)
    again = q.admit(job("once", 200), snap(200), now_ms=200)
    assert again.admitted
    assert again.ticket != first.ticket
    assert not q.finish(first.ticket, now_ms=220, succeeded=True)


def test_training_and_rendering_never_compete_with_live_game():
    q = ready()
    for kind in ("research", "training", "render"):
        row = q.admit(
            job(f"bg-{kind}", 1000, kind=kind, device="auto"),
            snap(1000, live=True, game=True), now_ms=1000,
        )
        assert not row.admitted
        assert row.reason == "protect_live_stream_from_background_work"


@pytest.mark.parametrize("fps,backlog", [(39, 0), (60, 320), (49.99, 0)])
def test_voice_keeps_priority_under_game_or_tts_backpressure(fps, backlog):
    q = ready()
    metrics = snap(200, live=True, game=True, fps=fps, backlog=backlog)
    nonessential = q.admit(
        job("talk", 200, kind="commentary"), metrics, now_ms=200
    )
    voice = q.admit(job("voice", 200), metrics, now_ms=200)
    assert not nonessential.admitted
    assert nonessential.reason == "game_or_voice_backpressure"
    assert voice.admitted
    assert voice.device == "cpu"


def test_live_vision_rejects_uncalibrated_route_but_accepts_real_sample_history():
    q = ready()
    denied = q.admit(
        job("image", 0, kind="vision"), snap(0, live=True), now_ms=0
    )
    assert not denied.admitted
    train_route(q, kind="vision", device="gpu", start=1000)
    metrics = snap(17000, live=True, game=True)
    result = q.admit(
        job("image-live", 17000, kind="vision"), metrics, now_ms=17000
    )
    assert result.admitted
    assert result.predicted_p95_ms == 200
    assert result.device == "gpu"
    # Even if a worker finishes quickly, a stream cannot flood with screenshots.
    assert q.finish(result.ticket, now_ms=17100, succeeded=True)
    denied = q.admit(
        job("other-image", 17400, kind="vision"),
        snap(17400, live=True), now_ms=17400,
    )
    assert denied.reason == "live_vision_at_most_one_hz"
    after = q.admit(
        job("new-image", 18100, kind="vision"),
        snap(18100, live=True), now_ms=18100,
    )
    assert after.admitted


def test_live_game_prefers_calibrated_cpu_voice_even_with_faster_gpu():
    q = ready()
    train_route(q, kind="speech", device="cpu", start=1000, duration=320)
    train_route(q, kind="speech", device="gpu", start=17000, duration=100)
    attempt = q.admit(
        job("live-voice", 34000, kind="speech", ttl=1100),
        snap(34000, live=True, game=True), now_ms=34000,
    )
    assert attempt.admitted
    assert attempt.device == "cpu"
    assert attempt.predicted_p95_ms == 320


def test_cpu_fallback_is_allowed_during_low_gpu_memory_without_claiming_speed():
    q = ready()
    result = q.admit(
        job("fallback", 400), snap(400, live=True, game=True, vram=1000),
        now_ms=400,
    )
    assert result.admitted and result.device == "cpu"
    assert result.predicted_p95_ms is None
    assert result.reason == "unmeasured_host_must_verify"


def test_measured_p95_rejects_deadline_that_cannot_be_met():
    q = ready()
    train_route(q, kind="speech", device="cpu", start=1000, duration=1500)
    train_route(q, kind="speech", device="gpu", start=17000, duration=1200)
    result = q.admit(
        job("too-short", 35000, ttl=600),
        snap(35000, live=True), now_ms=35000,
    )
    assert not result.admitted
    assert result.reason == "no_calibrated_deadline_safe_route_or_headroom"


def test_gpu_vram_reservation_is_shared_across_live_jobs():
    q = ready()
    metrics = snap(1000, live=False, vram=1800, gpu_slots=2)
    one = q.admit(
        job("one", 1000, device="gpu", vram=800), metrics, now_ms=1000
    )
    two = q.admit(
        job("two", 1000, device="gpu", vram=800), metrics, now_ms=1000
    )
    assert one.admitted
    assert not two.admitted
    assert two.reason == "no_calibrated_deadline_safe_route_or_headroom"
    assert q.finish(one.ticket, now_ms=1300, succeeded=True)
    again = q.admit(
        job("three", 1400, device="gpu", vram=800),
        snap(1400, vram=1800, gpu_slots=2), now_ms=1400,
    )
    assert again.admitted


def test_cpu_slot_and_free_ram_limits():
    q = ready()
    metrics = snap(2000, cpu_slots=1, ram=1000)
    first = q.admit(
        job("first", 2000, device="cpu", ram=400), metrics, now_ms=2000
    )
    assert first.admitted
    second = q.admit(
        job("second", 2000, device="cpu", ram=400), metrics, now_ms=2000
    )
    assert not second.admitted
    assert q.finish(first.ticket, now_ms=2030, succeeded=True)
    low_ram = q.admit(
        job("large", 2100, device="cpu", ram=700),
        snap(2100, ram=1000), now_ms=2100,
    )
    assert not low_ram.admitted


def test_failure_circuit_breaker_needs_manual_reset():
    q = ready()
    for i in range(3):
        at = 1000 + i * 200
        decision = q.admit(
            job(f"broken-{i}", at, device="cpu"), snap(at), now_ms=at
        )
        assert decision.admitted
        assert q.finish(decision.ticket, now_ms=at + 100, succeeded=False)
    assert q.status()["failed"] == 3
    assert q.status()["unhealthy_routes"] == 1
    blocked = q.admit(
        job("broken-4", 1900, device="cpu"), snap(1900), now_ms=1900
    )
    assert not blocked.admitted
    q.disable()
    q.enable(owner_approved=True)
    assert q.status()["unhealthy_routes"] == 0


def test_expired_ticket_cannot_retroactively_increase_success():
    q = ready()
    accepted = q.admit(
        job("slow", 100, ttl=500, device="cpu"), snap(100), now_ms=100
    )
    assert accepted.admitted
    # Reaching a deadline must NOT automatically free GPU/CPU capacity:
    # a runaway inference worker may still be alive after its lease expires.
    assert q.status()["inflight"] == 1  # no clock advance from status()
    refused = q.admit(
        job("other", 601, device="cpu"),
        snap(601, cpu_slots=1), now_ms=601,
    )
    assert refused.reason == "no_calibrated_deadline_safe_route_or_headroom"
    assert q.status()["expired_awaiting_host_stop"] == 1
    # The trusted host reports that the worker eventually stopped; its late
    # success cannot count towards speed evidence.
    assert not q.finish(accepted.ticket, now_ms=650, succeeded=True)
    report = q.status()
    assert report["expired"] == 1 and report["completed"] == 0
    assert report["inflight"] == 0


def test_stale_snapshot_reversed_clock_and_expired_job():
    q = ready()
    stale = q.admit(
        job("stale", 500), snap(0, live=True), now_ms=500
    )
    assert stale.reason == "host_telemetry_stale_or_future_dated"
    with pytest.raises(ValueError, match="cannot reverse"):
        q.admit(job("reverse", 490), snap(490), now_ms=490)
    expired = q.admit(
        job("expired", 100, ttl=100), snap(700), now_ms=700
    )
    assert expired.reason == "job_clock_or_deadline_invalid"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "55"])
def test_rejects_bogus_sensors(bad):
    with pytest.raises(ValueError):
        QoSSnapshot(1, stream(), 100, bad)
    with pytest.raises(ValueError):
        InferenceJob("t", "speech", 1, 200, bad, 100)
    with pytest.raises(ValueError):
        AdaptiveQoS().admit(job("good", 100), snap(100), now_ms=bad)


def test_rejects_malformed_ids_devices_and_deadlines():
    with pytest.raises(ValueError):
        job("../prompt-injection", 1)
    with pytest.raises(ValueError):
        job("valid", 10, kind="vision", device="cpu")
    with pytest.raises(ValueError):
        InferenceJob("valid", "speech", 10, 10, 100, 100)
    with pytest.raises(ValueError):
        QoSSnapshot(1, stream(), 100, 50, cpu_slots=17)
    with pytest.raises(ValueError):
        AdaptiveQoS(minimum_headroom_mib=12)
    with pytest.raises(ValueError):
        AdaptiveQoS(lease_cap_ms=100)


def test_status_is_privacy_minimal_and_does_not_return_event_ids():
    q = ready()
    secretish_id = "private-utterance-20261025"
    result = q.admit(
        job(secretish_id, 100), snap(100), now_ms=100
    )
    assert result.admitted
    assert q.finish(result.ticket, now_ms=250, succeeded=True)
    assert secretish_id not in str(q.status())
    assert "basis" in q.status()
    assert not q.status()["route_p95_ms"]  # five successful samples required


def test_underloaded_offline_candidate_is_only_advisory_not_execution():
    q = ready()
    report = q.admit(
        job("game_build_lab", 2000, kind="research", device="gpu"),
        snap(2000, live=False), now_ms=2000,
    )
    assert report.admitted
    assert report.reason == "unmeasured_host_must_verify"
    assert q.status()["completed"] == 0  # No tool/model was run.
