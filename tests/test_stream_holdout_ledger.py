"""Tests for STAR's transactional single-use holdout ledger."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from star.stream_holdout_ledger import (
    HoldoutAlreadyConsumed,
    HoldoutGroupAlreadyConsumed,
    HoldoutLedger,
)
from star.stream_turntaking_eval import EndOfTurnScore, PauseKind, SilenceSpan
from star.stream_turntaking_validation import (
    TurnPolicyConstraints,
    ValidationStatus,
    select_and_validate_turn_policy,
)


def make_turn(prefix, index, *, hold_duration=500, final_horizon=1200):
    turn_id = f"{prefix}-turn-{index}"
    hold = SilenceSpan(
        span_id=f"{prefix}-hold-{index}",
        turn_id=turn_id,
        environment_id="private-rehearsal-v1",
        kind=PauseKind.HOLD,
        duration_ms=hold_duration,
        scores=(
            EndOfTurnScore(100, 0.10),
            EndOfTurnScore(250, 0.90),
            EndOfTurnScore(400, 0.20),
        ),
    )
    final = SilenceSpan(
        span_id=f"{prefix}-final-{index}",
        turn_id=turn_id,
        environment_id="private-rehearsal-v1",
        kind=PauseKind.END_OF_TURN,
        duration_ms=final_horizon,
        scores=(
            EndOfTurnScore(100, 0.10),
            EndOfTurnScore(300, 0.85),
            EndOfTurnScore(600, 0.95),
        ),
    )
    return hold, final


def dataset(prefix, count=100, *, hold_duration=500):
    rows = [
        span
        for index in range(count)
        for span in make_turn(prefix, index, hold_duration=hold_duration)
    ]
    groups = {
        f"{prefix}-turn-{index}": f"{prefix}-session-{index}"
        for index in range(count)
    }
    return rows, groups


def constraints(**changes):
    values = {
        "max_false_cutoff_rate": 1.0,
        "max_missed_final_rate": 1.0,
        "max_p95_latency_ms": 900,
        "min_hold_pauses": 1,
        "min_final_turns": 1,
        "min_calibration_groups": 1,
        "min_holdout_groups": 1,
    }
    values.update(changes)
    return TurnPolicyConstraints(**values)


def evaluate(calibration, holdout, groups, *, ledger=None, limits=None):
    return select_and_validate_turn_policy(
        calibration,
        holdout,
        group_ids_by_turn=groups,
        thresholds=(0.8, 0.94),
        action_delays_ms=(200, 350),
        timeouts_ms=(900, 1000),
        constraints=limits or constraints(),
        holdout_ledger=ledger,
    )


def test_ledger_claims_dataset_and_groups_once(tmp_path):
    rows, groups = dataset("hold", 4)
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    claim = ledger.claim(rows, groups, claimed_at_ms=1234)
    assert claim.group_count == 4
    assert len(claim.dataset_digest) == 64
    assert claim.claimed_at_ms == 1234
    with pytest.raises(HoldoutAlreadyConsumed):
        ledger.claim(rows, groups, claimed_at_ms=1235)


def test_same_dataset_digest_is_order_independent(tmp_path):
    rows, groups = dataset("hold", 4)
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    ledger.claim(rows, groups)
    with pytest.raises(HoldoutAlreadyConsumed):
        ledger.claim(list(reversed(rows)), groups)


def test_partial_session_group_reuse_is_rejected(tmp_path):
    first, first_groups = dataset("first", 3)
    second, second_groups = dataset("second", 3)
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    ledger.claim(first, first_groups)
    second_groups["second-turn-0"] = "first-session-0"
    with pytest.raises(HoldoutGroupAlreadyConsumed):
        ledger.claim(second, second_groups)


def test_group_collision_rolls_back_dataset_claim(tmp_path):
    first, first_groups = dataset("first", 2)
    second, second_groups = dataset("second", 2)
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    ledger.claim(first, first_groups)
    second_groups["second-turn-0"] = "first-session-0"
    with pytest.raises(HoldoutGroupAlreadyConsumed):
        ledger.claim(second, second_groups)
    second_groups["second-turn-0"] = "second-session-0"
    claim = ledger.claim(second, second_groups)
    assert claim.group_count == 2


def test_concurrent_exact_claim_has_one_winner(tmp_path):
    rows, groups = dataset("hold", 3)
    ledger_path = tmp_path / "ledger.sqlite3"

    ledger = HoldoutLedger(ledger_path)

    def attempt(_):
        try:
            ledger.claim(rows, groups)
            return "claimed"
        except HoldoutAlreadyConsumed:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert outcomes.count("claimed") == 1
    assert outcomes.count("duplicate") == 7


def test_invalid_group_mapping_is_rejected_before_claim(tmp_path):
    rows, groups = dataset("hold", 2)
    groups["hold-turn-0"] = "contains space"
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    with pytest.raises(ValueError):
        ledger.claim(rows, groups)


def test_invalid_path_and_timeout_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        HoldoutLedger(":memory:")
    with pytest.raises(ValueError):
        HoldoutLedger(tmp_path / "ledger.sqlite3", timeout_seconds=float("nan"))


def test_validation_claims_only_after_policy_is_selected(tmp_path):
    calibration, calibration_groups = dataset("cal", 100)
    holdout, holdout_groups = dataset("hold", 100)
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    result = evaluate(
        calibration,
        holdout,
        {**calibration_groups, **holdout_groups},
        ledger=ledger,
    )
    assert result.status is ValidationStatus.PASS
    assert result.holdout_ledger_claimed is True
    with pytest.raises(HoldoutAlreadyConsumed):
        evaluate(
            calibration,
            holdout,
            {**calibration_groups, **holdout_groups},
            ledger=ledger,
        )


def test_insufficient_calibration_does_not_consume_holdout(tmp_path):
    calibration, calibration_groups = dataset("cal", 2)
    holdout, holdout_groups = dataset("hold", 100)
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    result = evaluate(
        calibration,
        holdout,
        {**calibration_groups, **holdout_groups},
        ledger=ledger,
        limits=constraints(min_hold_pauses=10, min_final_turns=10),
    )
    assert result.status is ValidationStatus.INSUFFICIENT_CALIBRATION
    assert result.holdout_ledger_claimed is False

    enough_calibration, enough_groups = dataset("cal2", 100)
    second = evaluate(
        enough_calibration,
        holdout,
        {**enough_groups, **holdout_groups},
        ledger=ledger,
    )
    assert second.holdout_ledger_claimed is True


def test_no_calibration_candidate_does_not_consume_holdout(tmp_path):
    calibration, calibration_groups = dataset("cal", 100)
    holdout, holdout_groups = dataset("hold", 100)
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    no_candidate = select_and_validate_turn_policy(
        calibration,
        holdout,
        group_ids_by_turn={**calibration_groups, **holdout_groups},
        thresholds=(0.999,),
        action_delays_ms=(200,),
        timeouts_ms=(1000,),
        constraints=constraints(max_p95_latency_ms=100),
        holdout_ledger=ledger,
    )
    assert no_candidate.status is ValidationStatus.NO_CALIBRATION_CANDIDATE
    assert no_candidate.holdout_ledger_claimed is False

    selected = evaluate(
        calibration,
        holdout,
        {**calibration_groups, **holdout_groups},
        ledger=ledger,
    )
    assert selected.holdout_ledger_claimed is True


def test_inconclusive_opened_holdout_is_still_consumed(tmp_path):
    calibration, calibration_groups = dataset("cal", 100)
    holdout, holdout_groups = dataset("hold", 20)
    ledger = HoldoutLedger(tmp_path / "ledger.sqlite3")
    limits = constraints(min_hold_pauses=50, min_final_turns=50)
    result = evaluate(
        calibration,
        holdout,
        {**calibration_groups, **holdout_groups},
        ledger=ledger,
        limits=limits,
    )
    assert result.status is ValidationStatus.INCONCLUSIVE_HOLDOUT
    assert result.holdout_ledger_claimed is True
    with pytest.raises(HoldoutAlreadyConsumed):
        evaluate(
            calibration,
            holdout,
            {**calibration_groups, **holdout_groups},
            ledger=ledger,
            limits=limits,
        )


def test_without_ledger_preserves_legacy_behavior():
    calibration, calibration_groups = dataset("cal", 100)
    holdout, holdout_groups = dataset("hold", 100)
    result = evaluate(
        calibration,
        holdout,
        {**calibration_groups, **holdout_groups},
    )
    assert result.holdout_ledger_claimed is False



def test_ledger_persists_only_hashes_not_source_group_ids(tmp_path):
    rows, groups = dataset("private-holdout", 3)
    ledger_path = tmp_path / "ledger.sqlite3"
    HoldoutLedger(ledger_path).claim(rows, groups)

    connection = sqlite3.connect(ledger_path)
    try:
        claims = connection.execute(
            "SELECT dataset_digest, claimed_at_ms, evaluator_version FROM holdout_claims"
        ).fetchall()
        stored_groups = connection.execute(
            "SELECT group_digest, dataset_digest FROM holdout_groups"
        ).fetchall()
    finally:
        connection.close()

    assert len(claims) == 1
    assert len(stored_groups) == 3
    serialized = repr((claims, stored_groups))
    assert "private-holdout" not in serialized
    assert "session-" not in serialized
    assert "turn-" not in serialized
