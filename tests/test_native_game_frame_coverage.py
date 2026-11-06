"""Independent native-host frame accounting, all simulated, never Windows input."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from star.native_game_roundtrip_audit import NativeGameRoundtripAudit
from tests.test_native_game_roundtrip_audit import FakePort, ScriptClock


def auditor(*, stamps=(1_000_000_000, 1_050_000_000, 1_060_000_000, 1_100_000_000,
                       2_000_000_000, 2_040_000_000, 2_060_000_000,
                       3_000_000_000, 3_080_000_000, 3_100_000_000, 3_180_000_000)):
    port = FakePort()
    return NativeGameRoundtripAudit(
        port, owner_approved=True, require_frame_coverage=True,
        clock=ScriptClock(*stamps),
    ), port


def test_contiguous_host_frames_with_explicit_no_op_produce_accounted_audit():
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    a.capture(frame_sequence=2)
    a.decision_ready()
    a.no_action()
    a.capture(frame_sequence=3)
    a.decision_ready()
    a.execute("move_right", 10)
    before = a.report()
    assert before.status == "incomplete"
    assert before.completed == 0
    a.seal_frames(expected_frames=3, host_verified=True)
    report = a.finalize()
    assert report.status == "host_roundtrip_only"
    assert report.attempted == report.completed == 2
    assert report.observed_frames == 3
    assert report.no_action_frames == 1
    assert report.host_frame_coverage_declared
    assert report.all_frame_decision_p95_ms == 80.0
    assert report.native_call_p95_ms == 80.0
    assert report.frame_to_release_p95_ms == 180.0
    assert p.calls == [("jump", 5), ("move_right", 10)]
    assert report.game_effect_attested is False
    assert report.authorizes_broadcast is False
    assert report.authorizes_gameplay is False
    assert "jump" not in str(asdict(report))


def test_missing_first_sequence_drops_the_entire_window():
    a, p = auditor()
    with pytest.raises(RuntimeError, match="missing, replayed"):
        a.capture(frame_sequence=2)
    assert a.report().status == "revoked"
    assert not p.calls


@pytest.mark.parametrize("bad", [None, True, False, 0, -1, 1.0, "1", 257])
def test_invalid_first_frame_sequence_cannot_be_an_attestation(bad):
    a, p = auditor()
    with pytest.raises(RuntimeError, match="invalid native game frame"):
        a.capture(frame_sequence=bad)
    assert not p.calls


@pytest.mark.parametrize("bad", [1, 3, 0, -2, True, "2", None])
def test_replay_or_gap_after_real_dispatch_revokes_all_prior_latency(bad):
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    with pytest.raises(RuntimeError, match="missing, replayed"):
        a.capture(frame_sequence=bad)
    assert a.report().status == "revoked"
    assert a.report().completed == 0
    assert p.calls == [("jump", 5)]


def test_omitted_final_frame_cannot_be_sealed_even_if_native_calls_succeeded():
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    with pytest.raises(RuntimeError, match="not independently complete"):
        a.seal_frames(expected_frames=2, host_verified=True)
    assert a.report().completed == 0
    assert a.report().status == "revoked"


@pytest.mark.parametrize("bad_count,bad_trust", [(1, False), (True, True), (0, True),
                                                 (2, True), (1.0, True)])
def test_seal_requires_a_separate_strict_host_declaration(bad_count, bad_trust):
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    with pytest.raises(RuntimeError, match="not independently complete"):
        a.seal_frames(expected_frames=bad_count, host_verified=bad_trust)
    assert a.report().status == "revoked"


def test_no_action_is_explicit_not_a_missing_action_or_fast_dispatch():
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.no_action()
    assert a.report().status == "incomplete"
    with pytest.raises(RuntimeError, match="not independently complete"):
        a.seal_frames(expected_frames=1, host_verified=True)
    assert a.report().status == "revoked"
    assert not p.calls


def test_stale_no_action_revoke_all_previous_good_frames():
    a, p = auditor(stamps=(1_000_000_000, 1_010_000_000, 1_020_000_000, 1_025_000_000,
                          2_000_000_000, 2_010_000_000, 2_500_000_000))
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    a.capture(frame_sequence=2)
    a.decision_ready()
    with pytest.raises(RuntimeError, match="decision deadline"):
        a.no_action()
    assert a.report().status == "revoked"
    assert a.report().completed == 0


def test_missing_decision_no_action_is_not_legitimate_frame_coverage():
    a, p = auditor()
    a.capture(frame_sequence=1)
    with pytest.raises(RuntimeError, match="ready decision"):
        a.no_action()
    assert a.report().status == "revoked"
    assert not p.calls


def test_preseal_finalize_is_not_partial_success():
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    with pytest.raises(RuntimeError, match="sealed"):
        a.finalize()
    assert a.report().status == "revoked"


def test_seal_rejects_pending_undecided_frame():
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    a.capture(frame_sequence=2)
    with pytest.raises(RuntimeError, match="not independently complete"):
        a.seal_frames(expected_frames=2, host_verified=True)
    assert a.report().status == "revoked"


def test_capture_after_seal_revokes_sealed_partial_result():
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    a.seal_frames(expected_frames=1, host_verified=True)
    with pytest.raises(RuntimeError, match="already sealed"):
        a.capture(frame_sequence=2)
    assert a.report().status == "revoked"


def test_seal_twice_revokes_to_prevent_reusing_host_accounting():
    a, p = auditor()
    a.capture(frame_sequence=1)
    a.decision_ready()
    a.execute("jump", 5)
    a.seal_frames(expected_frames=1, host_verified=True)
    with pytest.raises(RuntimeError, match="not independently complete"):
        a.seal_frames(expected_frames=1, host_verified=True)
    assert a.report().status == "revoked"


def test_legacy_mode_rejects_frame_sequence_without_opt_in():
    p = FakePort()
    a = NativeGameRoundtripAudit(p, owner_approved=True)
    with pytest.raises(RuntimeError, match="explicit coverage opt-in"):
        a.capture(frame_sequence=1)
    assert a.report().status == "revoked"
    assert not p.calls


def test_legacy_mode_cannot_misrepresent_no_action_or_host_seal():
    p = FakePort()
    a = NativeGameRoundtripAudit(p, owner_approved=True)
    with pytest.raises(RuntimeError, match="not independently complete"):
        a.seal_frames(expected_frames=1, host_verified=True)
    assert a.report().status == "revoked"


def test_invalid_bool_config_rejected():
    with pytest.raises(ValueError, match="must be boolean"):
        NativeGameRoundtripAudit(
            FakePort(), owner_approved=True, require_frame_coverage=1,
        )
