"""Offline signed-host playthrough contract tests; does not launch Roblox/OBS."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac

import pytest

from star.studio_playthrough_contract import (
    PlaythroughContract, PlaythroughEvent, StudioPlaythroughGate,
)

_SECRET = b"Independent private-Studio observer fixture secret 32 bytes"


def spec(slots=(1,), *, run="trial-1", started=1000.0):
    return PlaythroughContract("obby", "v2", run, slots, started)


def verify(payload, receipt):
    return hmac.compare_digest(
        hmac.new(_SECRET, payload, hashlib.sha256).hexdigest(), receipt,
    )


def event(contract, index=0, *, slot=1, at=None, witness=None):
    phases = ("launch", "spawn", "input", "objective", "exit",
              "rejoin", "save_restored")
    phase = phases[index]
    return PlaythroughEvent(
        contract.digest, slot, index, phase,
        "input" if phase == "input" else "engine",
        at if at is not None else 1001 + index * 10 + slot / 10,
        witness if witness is not None else hashlib.sha256(
            f"{contract.run_id}:{slot}:{index}".encode(),
        ).hexdigest(),
    )


def send(gate, obj, *, at=None, receipt=None):
    return gate.submit(
        obj, receipt=receipt if receipt is not None
        else hmac.new(_SECRET, obj.canonical_bytes(), hashlib.sha256).hexdigest(),
        now_ms=obj.observed_ms + .1 if at is None else at,
    )


def ready(contract=None):
    contract = contract if contract is not None else spec()
    gate = StudioPlaythroughGate(contract, verify_independent_receipt=verify)
    gate.enable(owner_approved=True, private_studio_confirmed=True)
    return gate


def test_complete_single_client_requires_all_seven_phases():
    s = spec()
    gate = ready(s)
    for i in range(6):
        assert send(gate, event(s, i))
        report = gate.report(now_ms=1001 + i * 10 + 1)
        assert report.status == "incomplete"
        assert not report.automatically_certified
        assert report.next_phases == ((1, event(s, i + 1).phase),)
    assert send(gate, event(s, 6))
    report = gate.report(now_ms=1070)
    assert report.status == "eligible_for_manual_review"
    assert report.completed_clients == report.required_clients == 1
    assert report.accepted_events == 7
    assert not report.automatically_certified
    assert report.next_phases == ()


def test_two_clients_can_interleave_without_cross_progress():
    s = spec((1, 2))
    gate = ready(s)
    for i in range(7):
        assert send(gate, event(s, i, slot=2))
    assert gate.report(now_ms=1070).status == "incomplete"
    assert gate.report(now_ms=1070).completed_clients == 1
    for i in range(7):
        assert send(gate, event(s, i, slot=1, at=2001 + i * 10))
    assert gate.report(now_ms=2070).status == "eligible_for_manual_review"
    assert gate.report(now_ms=2070).accepted_events == 14


def test_eight_client_contract_is_bounded():
    s = spec(tuple(range(1, 9)))
    gate = ready(s)
    for i in range(7):
        for slot in s.client_slots:
            assert send(gate, event(s, i, slot=slot))
    report = gate.report(now_ms=1070)
    assert report.status == "eligible_for_manual_review"
    assert report.accepted_events == 56
    assert report.completed_clients == 8


def test_no_owner_permission_and_no_game_control_by_default():
    s = spec()
    gate = StudioPlaythroughGate(s, verify_independent_receipt=verify)
    assert gate.report(now_ms=1001).status == "disabled"
    assert not send(gate, event(s))
    with pytest.raises(PermissionError):
        gate.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        gate.enable(private_studio_confirmed=True)
    gate.enable(owner_approved=True, private_studio_confirmed=True)
    with pytest.raises(RuntimeError):
        gate.enable(owner_approved=True, private_studio_confirmed=True)


def test_out_of_order_phase_invalidates_entire_run():
    s = spec()
    gate = ready(s)
    assert not send(gate, event(s, 1))
    assert gate.report(now_ms=1020).status == "invalid"
    assert not send(gate, event(s, 0))


def test_replay_event_after_progress_cannot_rewind():
    s = spec()
    gate = ready(s)
    e = event(s)
    assert send(gate, e)
    assert not send(gate, e)
    assert gate.report(now_ms=1003).status == "invalid"


def test_receipt_tampering_rejected():
    s = spec()
    gate = ready(s)
    e = event(s)
    assert not send(gate, e, receipt="a" * 64)
    assert gate.report(now_ms=1003).status == "invalid"


def test_wrong_run_digest_even_with_valid_external_signature():
    s = spec()
    other = spec(run="trial-2")
    gate = ready(s)
    assert not send(gate, event(other))
    assert gate.report(now_ms=1003).status == "invalid"


def test_contract_digest_binds_client_scope_timestamp_and_policy():
    s = spec()
    assert spec((1, 2)).digest != s.digest
    assert spec(run="trial-2").digest != s.digest
    assert spec(started=1002).digest != s.digest
    assert replace(s, max_duration_ms=40000).digest != s.digest


def test_future_event_rejected():
    s = spec()
    gate = ready(s)
    assert not send(gate, event(s), at=999)
    assert gate.report(now_ms=1002).status == "invalid"


def test_stale_event_rejected():
    s = spec()
    gate = ready(s)
    assert not send(gate, event(s), at=4000)
    assert gate.report(now_ms=4000).status == "invalid"


def test_nonincreasing_time_for_same_client_rejected():
    s = spec()
    gate = ready(s)
    assert send(gate, event(s, 0, at=1100))
    assert not send(gate, event(s, 1, at=1099))
    assert gate.report(now_ms=1101).status == "invalid"


def test_duplicate_witness_proof_across_different_phases_rejected():
    s = spec()
    gate = ready(s)
    first = event(s, 0)
    assert send(gate, first)
    assert not send(gate, event(s, 1, witness=first.witness_sha256))
    assert gate.report(now_ms=1020).status == "invalid"


def test_expired_contract_never_becomes_valid_later():
    s = spec()
    gate = ready(s)
    assert gate.report(now_ms=602000).status == "invalid"
    assert not send(gate, event(s, 0))


def test_invalid_client_and_invalid_event_shape_rejected_before_verifier():
    s = spec()
    gate = ready(s)
    assert not send(gate, event(spec((2,)), 0, slot=2))
    assert gate.report(now_ms=1002).status == "invalid"
    with pytest.raises(ValueError):
        replace(event(s), source="input")
    with pytest.raises(ValueError):
        replace(event(s), phase="save_restored")
    with pytest.raises(ValueError):
        replace(event(s), step_index=True)
    with pytest.raises(ValueError):
        replace(event(s), witness_sha256="not-a-digest")
    with pytest.raises(ValueError):
        replace(event(s), observed_ms=float("nan"))


@pytest.mark.parametrize("slots", [(), (1, 1), (9,), (True,), tuple(range(1, 10)), [1]])
def test_bad_client_roster_rejected(slots):
    with pytest.raises(ValueError):
        spec(slots)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -2, True, 1e15])
def test_bad_monotonic_clock_rejected(bad):
    with pytest.raises(ValueError):
        spec(started=bad)


def test_fail_closed_if_independent_verifier_raises():
    s = spec()
    def broken(_payload, _receipt):
        raise RuntimeError("observer offline")
    gate = StudioPlaythroughGate(s, verify_independent_receipt=broken)
    gate.enable(owner_approved=True, private_studio_confirmed=True)
    assert not send(gate, event(s))
    assert gate.report(now_ms=1003).status == "invalid"


def test_receipt_rejects_bool_true_as_verifier_result():
    s = spec()
    gate = StudioPlaythroughGate(s, verify_independent_receipt=lambda *_: 1)
    gate.enable(owner_approved=True, private_studio_confirmed=True)
    assert not send(gate, event(s))
    assert gate.report(now_ms=1003).status == "invalid"


def test_disabling_revokes_and_cannot_restart():
    s = spec()
    gate = ready(s)
    assert send(gate, event(s))
    gate.disable()
    assert gate.report(now_ms=1010).status == "disabled"
    assert not send(gate, event(s, 1))
    with pytest.raises(RuntimeError):
        gate.enable(owner_approved=True, private_studio_confirmed=True)


def test_no_receipt_or_mismatched_studio_source_cannot_pass():
    s = spec()
    gate = ready(s)
    assert not send(gate, event(s), receipt="invalid")
    with pytest.raises(ValueError):
        replace(event(s, 2), source="engine")


def test_report_only_aggregate_data_and_opaque_phase_names():
    s = spec()
    gate = ready(s)
    e = event(s)
    assert send(gate, e)
    report = gate.report(now_ms=1005)
    assert e.witness_sha256 not in repr(report)
    assert s.run_id not in repr(report)
    assert report.accepted_events == 1



def test_host_clock_reversal_fails_closed_across_clients():
    s = spec((1, 2))
    gate = ready(s)
    assert send(gate, event(s, 0, slot=1, at=2000))
    assert not send(gate, event(s, 0, slot=2, at=1999))
    assert gate.report(now_ms=2001).status == "invalid"


def test_report_clock_cannot_rollback_after_new_evidence():
    s = spec()
    gate = ready(s)
    assert send(gate, event(s))
    assert gate.report(now_ms=1000).status == "invalid"
