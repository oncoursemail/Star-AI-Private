"""Independent fake-clock checks: model identity fences for stream QoS.

No GPU, game, microphone, OBS, network or model is used by these tests.
"""
import pytest

from star.stream_budget import StreamTelemetry
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSSnapshot


def snapshot(t, *, live=False, private=False, game=True):
    return QoSSnapshot(
        t, StreamTelemetry(live, game, 7000, 8192, 60, 0),
        16000, 10, 2, 1, private_stream_rehearsal=private,
    )


def task(ident, t, *, kind="speech", profile="", device="cpu", ttl=1200):
    return InferenceJob(
        ident, kind, t, t + ttl, 100, 256, device,
        route_profile=profile,
    )


def calibrate(q, profile, *, kind="speech", device="cpu", duration=125):
    for i in range(5):
        t = 1000 + i * 3000
        result = q.admit(
            task(f"cal-{profile or 'legacy'}-{kind}-{i}", t, kind=kind,
                 profile=profile, device=device),
            snapshot(t, private=True), now_ms=t,
        )
        assert result.admitted, result.reason
        assert q.finish(result.ticket, now_ms=t + duration, succeeded=True)


def test_uncalibrated_second_voice_cannot_borrow_first_voice_p95():
    q = AdaptiveQoS(require_route_profiles=True)
    q.enable(owner_approved=True)
    calibrate(q, "voice18m")
    first = q.admit(task("first", 17000, profile="voice18m"),
                    snapshot(17000, live=True), now_ms=17000)
    assert first.admitted
    assert first.predicted_p95_ms == 125
    assert q.finish(first.ticket, now_ms=17100, succeeded=True)
    second = q.admit(task("second", 18000, profile="voice100m"),
                     snapshot(18000, live=True), now_ms=18000)
    # Speech is allowed to explore under an explicit host deadline, but
    # MUST NOT be labelled as calibrated to another voice model's speed.
    assert second.admitted
    assert second.predicted_p95_ms is None
    assert second.reason == "unmeasured_host_must_verify"
    assert q.finish(second.ticket, now_ms=18200, succeeded=True)
    p95 = q.status()["route_p95_ms"]
    assert len(p95) == 1  # second voice has fewer than five samples
    assert all("voice18m" not in key and "voice100m" not in key for key in p95)


def test_uncalibrated_vision_model_denied_even_if_other_model_measured():
    q = AdaptiveQoS(require_route_profiles=True)
    q.enable(owner_approved=True)
    calibrate(q, "vision-small", kind="vision", device="gpu")
    new_model = q.admit(task("vision-new", 17000, kind="vision",
                             profile="vision-large", device="gpu"),
                        snapshot(17000, live=True), now_ms=17000)
    assert not new_model.admitted
    assert new_model.reason == "no_calibrated_deadline_safe_route_or_headroom"
    known = q.admit(task("vision-known", 18000, kind="vision",
                         profile="vision-small", device="gpu"),
                    snapshot(18000, live=True), now_ms=18000)
    assert known.admitted
    assert known.predicted_p95_ms == 125


def test_route_failures_and_half_open_probes_isolate_model_profiles():
    q = AdaptiveQoS()
    q.enable(owner_approved=True)
    for i in range(3):
        t = 1000 + i * 1000
        decision = q.admit(task(f"fail-{i}", t, profile="broken"),
                           snapshot(t, game=False), now_ms=t)
        assert decision.admitted
        assert q.finish(decision.ticket, now_ms=t + 75, succeeded=False)
    denied = q.admit(task("blocked", 4500, profile="broken"),
                     snapshot(4500, game=False), now_ms=4500)
    assert not denied.admitted
    separate = q.admit(task("different", 4600, profile="healthy"),
                       snapshot(4600, game=False), now_ms=4600)
    assert separate.admitted
    assert q.status()["unhealthy_routes"] == 1


def test_strict_identity_required_only_for_protected_stream_work():
    q = AdaptiveQoS(require_route_profiles=True)
    q.enable(owner_approved=True)
    denied_live = q.admit(task("live-unlabelled", 100), snapshot(100, live=True),
                          now_ms=100)
    assert denied_live.reason == "trusted_model_profile_required"
    denied_private = q.admit(task("private-unlabelled", 200),
                             snapshot(200, private=True), now_ms=200)
    assert denied_private.reason == "trusted_model_profile_required"
    allowed_idle = q.admit(task("idle", 300),
                           snapshot(300, game=False), now_ms=300)
    assert allowed_idle.admitted
    assert q.finish(allowed_idle.ticket, now_ms=350, succeeded=True)
    allowed_live = q.admit(task("live-labelled", 500, profile="voice18m"),
                           snapshot(500, live=True), now_ms=500)
    assert allowed_live.admitted


@pytest.mark.parametrize("profile", ["x" * 81, "with/slash", "with space",
                                     "\x00", 42, True])
def test_untrusted_profile_rejected_before_any_admission(profile):
    with pytest.raises(ValueError):
        task("invalid", 100, profile=profile)


def test_legacy_routes_remain_compatible_and_not_disclosed():
    q = AdaptiveQoS()
    q.enable(owner_approved=True)
    calibrate(q, "")
    decision = q.admit(task("legacy", 17000), snapshot(17000, live=True),
                       now_ms=17000)
    assert decision.admitted
    assert decision.predicted_p95_ms == 125
    assert q.status()["route_p95_ms"]["speech:cpu:game_stream"] == 125


def test_configuration_rejects_non_boolean_strict_mode():
    with pytest.raises(ValueError):
        AdaptiveQoS(require_route_profiles=1)
