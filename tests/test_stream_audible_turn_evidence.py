"""Offline regressions for physically witnessed, independent VTuber voice review."""

from dataclasses import replace

import pytest

from star.stream_audible_turn_evidence import (
    AudibleTurnEvidenceAssembler,
    CompletedVoiceReview,
    DeviceAudibleWitness,
    SpeechRequestWitness,
)
from star.stream_long_session_voice_health import LongSessionVoiceHealth


def make_session():
    health = LongSessionVoiceHealth()
    health.enable(owner_approved=True)
    joiner = AudibleTurnEvidenceAssembler(health)
    joiner.enable(owner_approved=True, session_id="nativeSession1")
    return health, joiner


def request(i: int, **change) -> SpeechRequestWitness:
    fields = dict(
        turn_id=f"turn{i}",
        output_epoch=f"native{i}",
        scene_epoch="room0",
        requested_at_ms=1000 + 20000 * i,
    )
    fields.update(change)
    return SpeechRequestWitness(**fields)


def heard(r: SpeechRequestWitness, *, delay_ms=200.0, **change):
    fields = dict(
        turn_id=r.turn_id,
        output_epoch=r.output_epoch,
        first_audible_ms=r.requested_at_ms + delay_ms,
        observed_at_ms=r.requested_at_ms + delay_ms + 20,
        device_loopback_confirmed=True,
    )
    fields.update(change)
    return DeviceAudibleWitness(**fields)


def review(w: DeviceAudibleWitness, **change):
    fields = dict(
        turn_id=w.turn_id,
        output_epoch=w.output_epoch,
        completed_audible_ms=w.first_audible_ms + 500,
        observed_at_ms=w.first_audible_ms + 550,
        voice_consistency=0.97,
        grounded=True,
        repeated=False,
        interruption_respected=True,
        reviewer_confirmed=True,
    )
    fields.update(change)
    return CompletedVoiceReview(**fields)


def play(joiner, i, *, delay_ms=200.0, **review_changes):
    req = request(i)
    assert joiner.begin(req, session_id="nativeSession1", now_ms=req.requested_at_ms + 10)
    audible = heard(req, delay_ms=delay_ms)
    assert joiner.heard(audible, now_ms=audible.observed_at_ms + 5)
    finished = review(audible, **review_changes)
    assert joiner.reviewed(
        finished, session_id="nativeSession1", current_scene_epoch="room0",
        now_ms=finished.observed_at_ms + 5,
    )


def test_off_by_default_and_guard_required():
    h = LongSessionVoiceHealth()
    a = AudibleTurnEvidenceAssembler(h)
    assert not a.begin(request(0), session_id="nativeSession1", now_ms=1010)
    assert not a.metrics().authorizes_audio
    assert not a.metrics().authorizes_broadcast
    with pytest.raises(PermissionError):
        a.enable(session_id="nativeSession1")
    with pytest.raises(RuntimeError, match="empty voice guard"):
        a.enable(session_id="nativeSession1", owner_approved=True)


def test_sixteen_independently_audible_turns_warm_long_session_monitor():
    health, joiner = make_session()
    for i in range(16):
        play(joiner, i)
        if i < 15:
            assert health.advise(now_ms=1000 + 20000 * i + 780).status == "warming"
    state = health.advise(now_ms=301900)
    assert state.status == "stable"
    assert state.allow_optional_commentary
    m = joiner.metrics()
    assert m.reviewed_turns == 16
    assert not m.pending and not m.has_device_witness
    assert m.rejected == 0


def test_audible_latency_is_derived_from_device_and_not_reviewer():
    health, joiner = make_session()
    for i in range(16):
        play(joiner, i, delay_ms=1100 if i >= 8 else 200)
    advice = health.advise(now_ms=302800)
    assert advice.status == "degraded"
    assert advice.reason == "first_audio_latency_regression"


def test_review_grounding_failure_flows_into_voice_health():
    health, joiner = make_session()
    for i in range(16):
        play(joiner, i, grounded=i != 15)
    assert health.advise(now_ms=301900).reason == "unverified_factual_claim"


def test_no_review_without_real_device_sound():
    health, joiner = make_session()
    req = request(0)
    assert joiner.begin(req, session_id="nativeSession1", now_ms=1010)
    witness = heard(req)
    finished = review(witness)
    assert not joiner.reviewed(
        finished, session_id="nativeSession1", current_scene_epoch="room0", now_ms=1755,
    )
    assert joiner.metrics().faulted
    assert health.metrics()["accepted"] == 0


@pytest.mark.parametrize(
    "replacement",
    [
        dict(device_loopback_confirmed=False),
        dict(output_epoch="other"),
        dict(turn_id="wrong"),
        dict(first_audible_ms=999),
        dict(first_audible_ms=50_000, observed_at_ms=50_010),
        dict(observed_at_ms=20_000),
    ],
)
def test_malformed_or_untrusted_device_evidence_poison_session(replacement):
    health, joiner = make_session()
    req = request(0)
    assert joiner.begin(req, session_id="nativeSession1", now_ms=1010)
    witness = heard(req, **replacement)
    assert not joiner.heard(
        witness, now_ms=max(1300, witness.observed_at_ms + 1),
    )
    assert joiner.metrics().faulted
    assert health.metrics()["accepted"] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewer_confirmed": False},
        {"turn_id": "other"},
        {"output_epoch": "other"},
        {"completed_audible_ms": 1000},
        {"completed_audible_ms": 100_000, "observed_at_ms": 100_010},
    ],
)
def test_untrusted_or_wrong_review_never_becomes_health_evidence(changes):
    health, joiner = make_session()
    req = request(0)
    joiner.begin(req, session_id="nativeSession1", now_ms=1010)
    witness = heard(req)
    joiner.heard(witness, now_ms=1225)
    finished = review(witness, **changes)
    assert not joiner.reviewed(
        finished, session_id="nativeSession1", current_scene_epoch="room0",
        now_ms=max(1800, finished.observed_at_ms + 10),
    )
    assert joiner.metrics().faulted
    assert health.metrics()["accepted"] == 0


def test_scene_revision_change_cancels_evidence():
    health, joiner = make_session()
    req = request(0)
    joiner.begin(req, session_id="nativeSession1", now_ms=1010)
    witness = heard(req)
    joiner.heard(witness, now_ms=1225)
    finished = review(witness)
    assert not joiner.reviewed(
        finished, session_id="nativeSession1", current_scene_epoch="room1", now_ms=1760,
    )
    assert joiner.metrics().faulted
    assert health.metrics()["accepted"] == 0


def test_device_and_review_input_cannot_be_replayed():
    health, joiner = make_session()
    play(joiner, 0)
    assert not joiner.begin(request(0), session_id="nativeSession1", now_ms=2000)
    assert joiner.metrics().faulted
    assert not joiner.begin(request(1), session_id="nativeSession1", now_ms=21000)
    assert health.metrics()["accepted"] == 1


def test_overlap_is_not_another_independent_turn():
    _, joiner = make_session()
    req = request(0)
    joiner.begin(req, session_id="nativeSession1", now_ms=1010)
    assert not joiner.begin(request(1), session_id="nativeSession1", now_ms=21010)
    assert joiner.metrics().faulted


def test_host_clock_rollback_is_fatal():
    _, joiner = make_session()
    joiner.begin(request(0), session_id="nativeSession1", now_ms=1010)
    with pytest.raises(ValueError, match="clock reversed"):
        joiner.heard(heard(request(0)), now_ms=1000)
    assert joiner.metrics().faulted


@pytest.mark.parametrize(
    "field,value",
    [
        ("turn_id", "bad path"),
        ("output_epoch", "bad/slash"),
        ("scene_epoch", ""),
        ("requested_at_ms", True),
        ("requested_at_ms", float("nan")),
        ("requested_at_ms", float("inf")),
    ],
)
def test_request_evidence_schema_is_strict(field, value):
    with pytest.raises(ValueError):
        request(0, **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("device_loopback_confirmed", 1),
        ("first_audible_ms", float("nan")),
        ("observed_at_ms", -1),
    ],
)
def test_device_evidence_schema_is_strict(field, value):
    with pytest.raises(ValueError):
        heard(request(0), **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("voice_consistency", True),
        ("voice_consistency", float("inf")),
        ("voice_consistency", 1.01),
        ("grounded", 1),
        ("reviewer_confirmed", "yes"),
        ("interruption_respected", None),
    ],
)
def test_independent_review_schema_is_strict(field, value):
    with pytest.raises(ValueError):
        review(heard(request(0)), **{field: value})


def test_new_session_cannot_inherit_stable_old_baseline():
    health, joiner = make_session()
    for i in range(16):
        play(joiner, i)
    assert health.advise(now_ms=301900).status == "stable"
    joiner.disable()
    with pytest.raises(RuntimeError, match="empty voice guard"):
        joiner.enable(owner_approved=True, session_id="nativeSession2")
    health.disable()
    health.enable(owner_approved=True)
    joiner.enable(owner_approved=True, session_id="nativeSession2")
    assert health.advise(now_ms=301900).status == "stale"
    assert joiner.metrics().reviewed_turns == 0
    assert not joiner.begin(request(16), session_id="nativeSession1", now_ms=321010)
    assert joiner.metrics().faulted


def test_physical_queue_ack_does_not_count_as_heard():
    health, joiner = make_session()
    r = request(0)
    joiner.begin(r, session_id="nativeSession1", now_ms=1010)
    assert not joiner.heard(replace(heard(r), device_loopback_confirmed=False), now_ms=1225)
    assert health.metrics()["accepted"] == 0


def test_rearm_requires_new_output_session_identifier():
    health, joiner = make_session()
    joiner.disable()
    health.disable()
    health.enable(owner_approved=True)
    with pytest.raises(RuntimeError, match="replay"):
        joiner.enable(owner_approved=True, session_id="nativeSession1")
    joiner.enable(owner_approved=True, session_id="nativeSession2")
    assert not joiner.metrics().faulted


def test_reviewer_observation_cannot_predate_device_callback():
    health, joiner = make_session()
    r = request(0)
    joiner.begin(r, session_id="nativeSession1", now_ms=1010)
    witness = heard(r, observed_at_ms=1700)
    joiner.heard(witness, now_ms=1710)
    finished = review(witness, observed_at_ms=1600)
    assert not joiner.reviewed(
        finished, session_id="nativeSession1", current_scene_epoch="room0", now_ms=1760,
    )
    assert joiner.metrics().faulted
    assert health.metrics()["accepted"] == 0
