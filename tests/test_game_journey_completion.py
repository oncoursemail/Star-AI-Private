"""Synthetic independent-host evidence for complete-game release review.

Tests verify evaluator mechanics only: fake receipts are NOT proof of an
actual Roblox/Unity/Godot playthrough or of improved neural intelligence.
"""
from dataclasses import replace

import pytest

from star.game_journey_completion import (
    JourneyContract, JourneyEvent, SignedJourneyEvent,
    assess_game_release_review, contract_digest, evaluate_journey,
    sign_journey_event,
)
from star.studio_multimodal_quality_gate import QualityReport


KEY = b"independent-test-host-secret-key-2026!"  # fixture only, no production key
START = 1_782_500_000_000
BUILD = "b" * 64
STATE = "d" * 64


def contract(**changes):
    base = JourneyContract(
        "contract_42", "episode_3", "test_obby", "v5", BUILD,
        ("cross_bridge", "collect_key", "unlock_exit"), START,
    )
    return replace(base, **changes)


def evidence(c=None):
    c = c or contract()
    events = []
    reopened = False
    for index, (kind, checkpoint) in enumerate(c.required_events(), start=1):
        if kind == "relaunch":
            reopened = True
        event = JourneyEvent(
            c.contract_id, c.run_id, c.game_id, c.game_version,
            c.build_sha256, kind, checkpoint,
            "fresh_process_2" if reopened else "initial_process_1",
            f"{index:064x}", STATE if kind in {"save", "restore"} else "",
            index, START + 500 * index,
        )
        events.append(sign_journey_event(event, host_key=KEY))
    return events


def assess(c=None, receipts=None, *, now_unix_ms=START + 15_000):
    c = c or contract()
    return evaluate_journey(
        c, evidence(c) if receipts is None else receipts,
        host_key=KEY, externally_sealed_sha256=contract_digest(c),
        now_unix_ms=now_unix_ms,
    )


def replace_event(receipts, index, **changes):
    result = list(receipts)
    changed = replace(result[index].event, **changes)
    result[index] = sign_journey_event(changed, host_key=KEY)
    return result


def index_of(receipts, kind):
    return next(i for i, item in enumerate(receipts)
                if item.event.kind == kind)


def test_signed_complete_player_journey_requires_new_process_and_matching_save():
    report = assess()
    assert report.verdict == "eligible_for_review"
    assert report.observed_steps == report.required_steps == 13
    assert report.next_required is None
    assert report.authorized_to_publish is False
    assert report.certified_general_game_skill is False


def test_missing_witnessed_ending_is_never_accepted():
    receipts = evidence()
    report = assess(receipts=receipts[:-1])
    assert report.verdict == "incomplete"
    assert report.next_required == "ending"


def test_no_launch_is_not_playable():
    report = assess(receipts=[])
    assert report.verdict == "incomplete"
    assert report.next_required == "launch"


def test_missing_user_input_before_objective_rejected():
    receipts = evidence()
    reports = assess(receipts=receipts[:1] + receipts[2:])
    assert reports.verdict == "invalid_evidence"
    assert "unexpected_journey_step" in reports.concerns or "replay" in reports.concerns[0]


def test_wrong_checkpoint_is_rejected_even_with_valid_signature():
    receipts = evidence()
    k = index_of(receipts, "checkpoint")
    changed = replace_event(receipts, k, checkpoint_id="another_goal")
    assert assess(receipts=changed).verdict == "invalid_evidence"


def test_modified_mac_is_rejected():
    receipts = evidence()
    receipts[3] = SignedJourneyEvent(receipts[3].event, "e" * 64)
    report = assess(receipts=receipts)
    assert "tampered_host_event" in report.concerns


def test_modified_payload_without_resigning_is_rejected():
    receipts = evidence()
    receipts[2] = replace(receipts[2],
                          event=replace(receipts[2].event,
                                        game_version="made_up_version"))
    assert assess(receipts=receipts).verdict == "invalid_evidence"


@pytest.mark.parametrize("field,value", [
    ("run_id", "other_episode"),
    ("game_id", "unrelated_game"),
    ("game_version", "different_build"),
    ("build_sha256", "e" * 64),
    ("contract_id", "different_contract"),
])
def test_signed_wrong_scope_is_rejected(field, value):
    receipts = evidence()
    tampered = replace_event(receipts, 1, **{field: value})
    assert assess(receipts=tampered).concerns == ("wrong_game_or_build_scope",)


def test_reused_event_sequence_rejected():
    receipts = evidence()
    changed = replace_event(receipts, 3, sequence=3)
    assert "replay_or_bad_event_sequence" in assess(receipts=changed).concerns


def test_duplicate_evidence_fingerprint_rejected():
    receipts = evidence()
    changed = replace_event(
        receipts, 4, evidence_sha256=receipts[3].event.evidence_sha256)
    assert "replay_or_bad_event_sequence" in assess(receipts=changed).concerns


def test_reused_process_after_reopen_is_rejected():
    receipts = evidence()
    relaunch = index_of(receipts, "relaunch")
    changed = replace_event(receipts, relaunch,
                            process_instance_id="initial_process_1")
    assert "reopen_must_be_a_different_process" in assess(receipts=changed).concerns


def test_process_switch_before_reopen_is_rejected():
    receipts = evidence()
    changed = replace_event(receipts, 4,
                            process_instance_id="unapproved_process_3")
    assert "process_identity_changed" in assess(receipts=changed).concerns


def test_process_switch_after_reopen_is_rejected():
    receipts = evidence()
    changed = replace_event(receipts, -1,
                            process_instance_id="unapproved_process_3")
    assert "process_identity_changed" in assess(receipts=changed).concerns


def test_state_mismatch_between_save_and_restored_game_rejected():
    receipts = evidence()
    changed = replace_event(receipts, index_of(receipts, "restore"),
                            state_sha256="f" * 64)
    assert "reopened_save_state_does_not_match" in assess(receipts=changed).concerns


def test_early_timestamp_and_out_of_order_timestamp_rejected():
    receipts = evidence()
    changed = replace_event(receipts, 4, observed_unix_ms=START - 1)
    assert "stale_or_out_of_order_event" in assess(receipts=changed).concerns
    changed = replace_event(receipts, 4, observed_unix_ms=START + 1)
    assert "stale_or_out_of_order_event" in assess(receipts=changed).concerns


def test_future_event_and_too_long_playthrough_rejected():
    receipts = evidence()
    changed = replace_event(receipts, 4, observed_unix_ms=START + 100_000)
    assert "stale_or_out_of_order_event" in assess(receipts=changed).concerns
    c = contract(max_duration_ms=30_000)
    receipts = evidence(c)
    changed = replace_event(receipts, -1, observed_unix_ms=START + 31_000)
    assert "stale_or_out_of_order_event" in assess(c, changed,
                                                     now_unix_ms=START + 35_000).concerns


def test_missing_or_outdated_externally_sealed_contract_blocks_success():
    c = contract()
    assert evaluate_journey(
        c, evidence(c), host_key=KEY,
        externally_sealed_sha256="0" * 64,
        now_unix_ms=START + 20_000,
    ).verdict == "invalid_evidence"
    assert evaluate_journey(
        c, evidence(c), host_key=KEY,
        externally_sealed_sha256=contract_digest(c),
        now_unix_ms=START + 100_000_000,
    ).verdict == "invalid_evidence"


def test_event_from_other_contract_is_not_replayable():
    initial = contract()
    other = contract(contract_id="new_contract")
    assert assess(other, receipts=evidence(initial)).verdict == "invalid_evidence"


def test_extra_or_replayed_events_rejected():
    receipts = evidence()
    assert assess(receipts=receipts + receipts[:1]).verdict == "invalid_evidence"


@pytest.mark.parametrize("field,value", [
    ("checkpoints", ()),
    ("checkpoints", ("same", "same")),
    ("checkpoints", ("not a valid id",)),
    ("max_duration_ms", 0),
    ("max_duration_ms", True),
    ("build_sha256", "bad"),
])
def test_invalid_contract_rejected(field, value):
    with pytest.raises(ValueError):
        contract(**{field: value})


@pytest.mark.parametrize("field,value", [
    ("checkpoint_id", "injected"),
    ("state_sha256", STATE),
    ("sequence", True),
    ("observed_unix_ms", float(START)),
    ("process_instance_id", "untrusted id with spaces"),
])
def test_invalid_signed_event_shape_rejected(field, value):
    receipt = evidence()[0]
    with pytest.raises(ValueError):
        replace(receipt.event, **{field: value})


def test_release_review_composes_visual_and_execution_evidence():
    report = assess()
    good_visual = QualityReport("eligible_for_review", 8, 8, 2, 0.5, .7)
    passed = assess_game_release_review(report, good_visual)
    assert passed.verdict == "candidate_for_human_review"
    assert passed.authorized_to_publish is False
    denied = assess_game_release_review(
        assess(receipts=evidence()[:2]),
        QualityReport("regressed", 8, 8, 2, -0.1, .2))
    assert denied.verdict == "blocked"
    assert len(denied.concerns) == 2


def test_invalid_host_key_never_accepted():
    c = contract()
    with pytest.raises(ValueError):
        evaluate_journey(c, evidence(), host_key=b"weak",
                         externally_sealed_sha256=contract_digest(c),
                         now_unix_ms=START + 10_000)
