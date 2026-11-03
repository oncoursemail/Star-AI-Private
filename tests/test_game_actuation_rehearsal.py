"""Offline adversarial tests for owner-only, receipt-gated game actuation."""
from __future__ import annotations

from dataclasses import replace
from threading import Event, Thread

import pytest

from star.game_actuation_rehearsal import GameActuationRehearsal
from star.game_action_gate import ActionPermit
from test_obs_guarded_game_episode import prepared, hint


def ready():
    episode, loop, source, socket, process, state, clock, telemetry, frame, lease = prepared()
    clock.value = 1200
    permit = episode.finish(lease, frame, hint(), telemetry=telemetry, host_verified=True)
    assert permit.offered
    clock.value = 1205
    port = {"pressed": 0, "up_requests": 0, "held": False,
            "probe_ok": True, "focus": True, "permission": True}

    def send(action, hold_ms, cancelled):
        assert action == "jump" and hold_ms == 70
        if cancelled.is_set():
            return False
        port["pressed"] += 1
        port["held"] = True
        return True

    def request_up():
        port["up_requests"] += 1
        if port["probe_ok"]:
            port["held"] = False

    guard = GameActuationRehearsal(
        episode=episode, send_action=send, request_all_up=request_up,
        all_keys_up=lambda: not port["held"],
        focus_probe=lambda: port["focus"],
        permission_probe=lambda: port["permission"],
    )
    return guard, permit, port, episode, state


def test_disabled_by_default_and_no_input_before_owner_approval():
    guard, permit, port, episode, state = ready()
    assert guard.run(permit).status == "disabled"
    assert port["pressed"] == 0
    with pytest.raises(PermissionError):
        guard.enable()
    guard.enable(owner_approved=True)
    result = guard.run(permit)
    assert result.status == "released_verified"
    assert result.claimed and result.keys_up_verified
    assert port["pressed"] == 1 and not port["held"]
    assert port["up_requests"] == 1
    assert not episode.revoked
    guard.stop()
    assert episode.revoked


def test_copied_or_model_invented_permit_does_not_dispatch():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    invented = replace(permit)
    assert invented == permit and invented is not permit
    result = guard.run(invented)
    assert result.status == "claim_rejected"
    assert port["pressed"] == 0
    assert episode.revoked
    assert guard.run(permit).status == "disabled"


def test_fabricated_ticket_also_rejected_without_any_input():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    forged = ActionPermit(True, "ok", ticket=99999, action_id="jump", hold_ms=70)
    assert guard.run(forged).status == "claim_rejected"
    assert port["pressed"] == 0


def test_unverified_physical_release_is_not_acknowledged_to_episode():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    port["probe_ok"] = False
    result = guard.run(permit)
    assert result.status == "release_unverified"
    assert result.claimed and not result.keys_up_verified
    assert port["held"] and episode.revoked
    assert guard.run(permit).status == "disabled"


def test_false_focus_at_dispatch_boundary_cannot_send_input():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    port["focus"] = False
    result = guard.run(permit)
    assert result.status == "host_denied"
    assert port["pressed"] == 0 and episode.revoked


def test_exception_from_port_is_sanitized_and_stops_episode():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    def secret_failure(action, hold_ms, cancelled):
        raise RuntimeError("PRIVATE DEVICE TOKEN AND KEY")
    guard._send_action = secret_failure
    result = guard.run(permit)
    assert result.status == "dispatch_failed"
    assert "PRIVATE" not in repr(result)
    assert episode.revoked


def test_emergency_stop_bypasses_blocked_dispatch_and_revokes_late_result():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    entered, continue_dispatch, stopped = Event(), Event(), Event()
    outcomes = []

    def blocking_dispatch(action, hold_ms, cancelled):
        entered.set()
        assert continue_dispatch.wait(3)
        # A proper native port checks stop atomically at the physical write edge.
        return not cancelled.is_set()

    guard._send_action = blocking_dispatch
    runner = Thread(target=lambda: outcomes.append(guard.run(permit)), daemon=True)
    runner.start()
    assert entered.wait(2)
    stopper = Thread(target=lambda: (guard.stop(), stopped.set()), daemon=True)
    stopper.start()
    try:
        assert stopped.wait(0.4), "owner stop cannot wait for a blocked game port"
        assert episode.revoked and port["up_requests"] >= 1
    finally:
        continue_dispatch.set()
        runner.join(3)
        stopper.join(3)
    assert not runner.is_alive() and not stopper.is_alive()
    assert len(outcomes) == 1 and outcomes[0].status == "stopped_during_dispatch"
    assert port["pressed"] == 0


def test_double_run_never_reuses_claim_or_physical_action():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    assert guard.run(permit).status == "released_verified"
    assert guard.run(permit).status == "claim_rejected"
    assert port["pressed"] == 1


def test_stop_is_terminal_before_enable_and_no_rearm():
    guard, permit, port, episode, state = ready()
    guard.stop()
    with pytest.raises(RuntimeError):
        guard.enable(owner_approved=True)
    assert guard.run(permit).status == "disabled"
    assert port["pressed"] == 0


def test_bogus_port_success_return_type_never_counts_as_dispatch():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    guard._send_action = lambda *args: 1
    assert guard.run(permit).status == "dispatch_failed"
    assert episode.revoked

def test_pre_dispatch_recheck_after_claim_catches_lost_focus():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    count = {"n": 0}
    def changing_focus():
        count["n"] += 1
        return count["n"] < 2
    guard._focus = changing_focus
    result = guard.run(permit)
    assert result.status == "host_denied" and result.claimed
    assert port["pressed"] == 0 and episode.revoked


def test_truthy_but_nonboolean_physical_receipt_is_rejected():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    guard._all_keys_up = lambda: 1
    result = guard.run(permit)
    assert result.status == "release_unverified"
    assert episode.revoked


def test_completed_but_too_slow_dispatch_latches_stop():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    times = iter((10.0, 600.0))
    guard._clock = lambda: next(times)
    result = guard.run(permit)
    assert result.status == "dispatch_deadline_exceeded"
    assert port["pressed"] == 1 and episode.revoked
    assert not port["held"]


def test_owner_stop_bypasses_blocked_obs_final_claim():
    guard, permit, port, episode, state = ready()
    guard.enable(owner_approved=True)
    entered, resume, stopped = Event(), Event(), Event()
    original = episode._witness.snapshot
    outcomes = []

    def blocked_snapshot():
        entered.set()
        assert resume.wait(3)
        return original()

    episode._witness.snapshot = blocked_snapshot
    runner = Thread(target=lambda: outcomes.append(guard.run(permit)), daemon=True)
    runner.start()
    assert entered.wait(2)
    stopper = Thread(target=lambda: (guard.stop(), stopped.set()), daemon=True)
    stopper.start()
    try:
        assert stopped.wait(0.4), "owner stop must bypass blocked OBS sample"
    finally:
        resume.set()
        runner.join(3)
        stopper.join(3)
    assert not runner.is_alive() and not stopper.is_alive()
    assert outcomes[0].status == "claim_rejected"
    assert port["pressed"] == 0 and episode.revoked
