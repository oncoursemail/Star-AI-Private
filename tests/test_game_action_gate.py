"""Synthetic, no-I/O checks for STAR's owner-gated action adapter."""
from concurrent.futures import ThreadPoolExecutor
import pytest

from star.game_action_gate import (
    ActionPermit, GameActionGate, GameActionHint, GameFrame, GameScope,
)
from star.stream_budget import StreamTelemetry

SCOPE = GameScope("demo_game", "v1", "episode7")
D = "a" * 64
E = "b" * 64


def telemetry(*, active=True, fps=60, backlog=0, live=False):
    return StreamTelemetry(live, active, 4500, 8192, fps, backlog)


def frame(seq=1, at=1000, **kw):
    args = dict(scope=SCOPE, sequence=seq, captured_ms=at,
                evidence_sha256=D, focus_confirmed=True,
                playable=True, perception_confidence=0.95)
    return GameFrame(**{**args, **kw})


def hint(f=None, *, action="jump", at=None, hold=70, digest=None):
    f = f or frame()
    return GameActionHint(action, f.sequence, digest or f.evidence_sha256,
                          f.captured_ms + 15 if at is None else at, hold)


def ready(**opts):
    gate = GameActionGate(**opts)
    gate.start(SCOPE, ("jump", "move_left", "move_right"),
               owner_approved=True)
    return gate


def propose(gate, f=None, h=None, *, now=1020, verified=True, tele=None):
    f = f or frame()
    return gate.request(f, h or hint(f), now_ms=now,
                        host_verified=verified,
                        telemetry=tele or telemetry())


def test_explicit_owner_consent_and_fail_closed_defaults():
    g = GameActionGate()
    with pytest.raises(PermissionError):
        g.start(SCOPE, ["jump"])
    rejected = propose(g)
    assert not rejected.offered
    assert rejected.reason == "owner_consent_missing"
    assert rejected.authorized_to_press_keys is False
    assert not g.metrics()["enabled"]


def test_valid_two_phase_advisory_protocol():
    g = ready()
    permit = propose(g)
    assert permit == ActionPermit(True, "host_must_recheck_before_dispatch",
                                  1, "jump", 70, 1140, False)
    assert g.claim(permit.ticket, now_ms=1025, host_focus_and_permission=True)
    assert not g.claim(permit.ticket, now_ms=1026,
                       host_focus_and_permission=True)
    assert not g.release(permit.ticket, now_ms=1030)
    assert g.release(permit.ticket, now_ms=1050,
                     host_confirmed_released=True)
    assert not g.release(permit.ticket, now_ms=1050,
                         host_confirmed_released=True)
    assert g.metrics()["released"] == 1
    assert g.metrics()["claimed"] == 1


def test_host_verification_and_recheck_cannot_be_bypassed_by_model():
    g = ready()
    assert propose(g, verified=False).reason == "trusted_observation_missing"
    p = propose(g)
    assert p.offered
    assert not g.claim(p.ticket, now_ms=1021)
    assert g.metrics()["host_rechecks_failed"] == 1
    assert g.claim(p.ticket, now_ms=1023, host_focus_and_permission=True)


@pytest.mark.parametrize("change,reason", [
    ({"scope": GameScope("other", "v1", "episode7")},
     "wrong_game_version_or_episode"),
    ({"scope": GameScope("demo_game", "v2", "episode7")},
     "wrong_game_version_or_episode"),
    ({"scope": GameScope("demo_game", "v1", "other")},
     "wrong_game_version_or_episode"),
    ({"focus_confirmed": False}, "game_unfocused_or_in_menu"),
    ({"playable": False}, "game_unfocused_or_in_menu"),
    ({"perception_confidence": 0.74}, "uncertain_observation"),
])
def test_scope_focus_menu_and_calibrated_confidence(change, reason):
    g = ready()
    assert propose(g, frame(**change)).reason == reason


def test_fresh_frame_and_matching_observation_digest_required():
    g = ready()
    assert propose(g, frame(at=100), now=1020).reason == "frame_not_current"
    assert propose(g, frame(at=1100), now=1020).reason == "frame_not_current"
    f = frame()
    assert propose(g, f, hint(f, digest=E)).reason == "proposal_not_bound_to_frame"
    assert propose(g, f, GameActionHint("jump", 2, D, 1015, 70)).reason == (
        "proposal_not_bound_to_frame")
    assert propose(g, f, hint(f, at=900)).reason == "proposal_time_not_bound_to_frame"
    assert propose(g, f, hint(f, at=2000)).reason == "proposal_time_not_bound_to_frame"


def test_unallowlisted_actions_never_reach_permit():
    g = ready()
    f = frame()
    assert propose(g, f, hint(f, action="open_chat")).reason == (
        "action_not_in_host_allowlist")
    assert propose(g, f, hint(f, action="jump", hold=190)).reason == (
        "hold_exceeds_host_limit")


@pytest.mark.parametrize("tele,reason", [
    (None, "game_telemetry_missing_or_inactive"),
    (telemetry(active=False), "game_telemetry_missing_or_inactive"),
    (telemetry(fps=29), "realtime_game_or_voice_pressure"),
    (telemetry(backlog=351), "realtime_game_or_voice_pressure"),
])
def test_telemetry_pressures_avoid_input(tele, reason):
    g = ready()
    f = frame()
    outcome = g.request(f, hint(f), now_ms=1020,
                        host_verified=True, telemetry=tele)
    assert outcome.reason == reason


def test_game_stream_is_permitted_only_with_approved_focused_game():
    g = ready()
    assert propose(g, tele=telemetry(live=True)).offered


def test_replayed_sequence_even_with_new_digest_is_rejected():
    g = ready()
    p = propose(g)
    assert g.release(p.ticket, now_ms=1050, host_confirmed_released=True)
    f = frame(at=1250)
    assert propose(g, f, hint(f), now=1270).reason == (
        "stale_or_replayed_frame_sequence")
    assert propose(g, frame(seq=2, at=1250), now=1270).offered


def test_minimum_spacing_is_not_reset_by_fast_release():
    g = ready()
    p = propose(g)
    assert g.release(p.ticket, now_ms=1050, host_confirmed_released=True)
    f = frame(seq=2, at=1130)
    assert propose(g, f, hint(f), now=1150).reason == "per_action_spacing"
    assert propose(g, frame(seq=2, at=1230), now=1250).offered


def test_per_minute_budget_and_window_renewal():
    g = ready(minimum_gap_ms=50, max_per_minute=2)
    for i, now in enumerate([1020, 1220], 1):
        f = frame(seq=i, at=now - 20)
        p = propose(g, f, hint(f), now=now)
        assert p.offered
        assert g.release(p.ticket, now_ms=now + 1,
                         host_confirmed_released=True)
    f = frame(seq=3, at=1400)
    assert propose(g, f, hint(f), now=1420).reason == (
        "minute_action_budget_exhausted")
    f = frame(seq=3, at=61030)
    assert propose(g, f, hint(f), now=61050).offered


def test_expiry_never_releases_unknown_pressed_keys():
    g = ready(ticket_window_ms=30)
    first = propose(g)
    assert first.offered
    assert not g.claim(first.ticket, now_ms=1060,
                       host_focus_and_permission=True)
    assert g.metrics()["quarantined"]
    second = frame(seq=2, at=1080)
    assert propose(g, second, hint(second), now=1100).reason == (
        "awaiting_host_key_release")
    assert not g.release(first.ticket, now_ms=1110)
    assert g.release(first.ticket, now_ms=1115,
                     host_confirmed_released=True)
    assert not g.metrics()["quarantined"]


def test_revoke_before_claim_and_cleanup_after_disable():
    g = ready()
    p = propose(g)
    g.revoke()
    assert not g.claim(p.ticket, now_ms=1025,
                       host_focus_and_permission=True)
    with pytest.raises(RuntimeError):
        g.start(SCOPE, ["jump"], owner_approved=True)
    assert g.release(p.ticket, now_ms=1028, host_confirmed_released=True)
    g.start(SCOPE, ["jump"], owner_approved=True)
    q = propose(g)
    assert q.ticket != p.ticket
    assert not g.claim(p.ticket, now_ms=1030,
                       host_focus_and_permission=True)


def test_monotonic_time_cannot_go_backwards():
    g = ready()
    p = propose(g)
    with pytest.raises(ValueError):
        g.claim(p.ticket, now_ms=1010, host_focus_and_permission=True)
    with pytest.raises(ValueError):
        g.release(p.ticket, now_ms=999, host_confirmed_released=True)


def test_concurrent_actors_cannot_both_get_action_permits():
    g = ready()
    f = frame()
    h = hint(f)
    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = list(pool.map(
            lambda _: g.request(f, h, now_ms=1020,
                                host_verified=True, telemetry=telemetry()),
            range(24)))
    assert sum(row.offered for row in rows) == 1
    assert g.metrics()["offered"] == 1


@pytest.mark.parametrize("constructor,args", [
    (GameScope, ("", "v1", "ep")),
    (GameScope, ("game", "v1", "../secret")),
    (GameScope, ("game", "v1", "e" * 80)),
    (GameFrame, (SCOPE, True, 1000, D, True, True, 0.8)),
    (GameFrame, (SCOPE, 1, float("nan"), D, True, True, 0.8)),
    (GameFrame, (SCOPE, 1, 1000, E.upper(), True, True, 0.8)),
    (GameFrame, (SCOPE, 1, 1000, D, 1, True, 0.8)),
    (GameFrame, (SCOPE, 1, 1000, D, True, True, 1.1)),
    (GameActionHint, ("jump", True, D, 1000, 70)),
    (GameActionHint, ("rm -rf /", 1, D, 1000, 70)),
    (GameActionHint, ("jump", 1, D, float("inf"), 70)),
    (GameActionHint, ("jump", 1, D, 1000, 999)),
])
def test_malformed_scope_frames_and_untrusted_proposals(constructor, args):
    with pytest.raises((ValueError, TypeError)):
        constructor(*args)


def test_bad_input_parameters_rejected():
    with pytest.raises(ValueError):
        GameActionGate(max_hold_ms=True)
    with pytest.raises(ValueError):
        GameActionGate(min_confidence=float("nan"))
    g = GameActionGate()
    with pytest.raises(ValueError):
        g.start(SCOPE, ["jump", "jump"], owner_approved=True)
    with pytest.raises(ValueError):
        g.start(SCOPE, ["../jump"], owner_approved=True)
    with pytest.raises(ValueError):
        g.start(SCOPE, "jump", owner_approved=True)
    g.start(SCOPE, ["jump"], owner_approved=True)
    with pytest.raises(ValueError):
        propose(g, verified=1)
    with pytest.raises(ValueError):
        g.claim(True, now_ms=1020)
    with pytest.raises(ValueError):
        g.release(1, now_ms=1020, host_confirmed_released=1)


def test_summary_does_not_expose_private_game_or_action_identifiers():
    g = ready()
    p = propose(g)
    report = repr(g.metrics())
    assert p.action_id not in report
    assert "demo_game" not in report
    assert SCOPE.episode_id not in report
    assert D not in report
    assert "advisory" in report


def test_action_permit_never_proves_learning_or_dispatch():
    g = ready()
    p = propose(g)
    assert p.authorized_to_press_keys is False
    assert "successful_gameplay" not in g.metrics()
    assert g.claim(p.ticket, now_ms=1022, host_focus_and_permission=True)
    assert g.release(p.ticket, now_ms=1100,
                     host_confirmed_released=True)
    # A signed outcome belongs to GameplaySkillBank, not this adapter.


def test_start_without_clearing_unfinished_claim_is_rejected():
    g = ready()
    p = propose(g)
    assert g.claim(p.ticket, now_ms=1022, host_focus_and_permission=True)
    with pytest.raises(RuntimeError):
        g.start(SCOPE, ["jump"], owner_approved=True)
    g.revoke()
    with pytest.raises(RuntimeError):
        g.start(SCOPE, ["jump"], owner_approved=True)
    assert g.release(p.ticket, now_ms=1200,
                     host_confirmed_released=True)
    g.start(SCOPE, ["jump"], owner_approved=True)


def test_frame_with_insufficient_dispatch_window_is_not_reserved():
    g = ready()
    f = frame(at=685)
    decision = propose(g, f, hint(f), now=1020)
    assert not decision.offered
    assert decision.reason == "too_little_time_to_claim"
    assert g.metrics()["awaiting_host_release"] is False
    assert g.metrics()["offered"] == 0
