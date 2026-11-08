"""Offline game-mode gap evaluation: exhaustive pairing and fail-closed tests."""

from dataclasses import replace
import math

import pytest

from star.game_skill_gate import GamePerformanceTrial
from star.game_realtime_gap_audit import (
    GameModeGapPair,
    GameModeGapProtocol,
    audit_realtime_gap,
)


def protocol() -> GameModeGapProtocol:
    cases = tuple((f"map{i // 10}", i) for i in range(20))
    return GameModeGapProtocol(game_scope="game.v1", cases=cases)


def pair(
    i: int,
    *,
    pause: bool = True,
    live: bool = False,
    pause_delay: float = 100,
    live_delay: float = 450,
    verified: bool = True,
) -> GameModeGapPair:
    common = dict(
        game_scope="game.v1",
        scenario_id=f"map{i // 10}",
        seed=i,
        split="holdout",
        progress=0.8,
        host_verified=True,
    )
    return GameModeGapPair(
        paused=GamePerformanceTrial(
            case_id=f"p{i}", mode="paused", success=pause, action_delay_ms=pause_delay, **common
        ),
        realtime=GamePerformanceTrial(
            case_id=f"r{i}", mode="realtime", success=live, action_delay_ms=live_delay, **common
        ),
        matching_start_verified=verified,
        independent_outcome_verified=True,
        realtime_scene_deadline_ms=300,
    )


def test_realtime_gap_detected_on_matched_holdout():
    study = protocol()
    rows = [pair(i, pause=True, live=i >= 3) for i in range(20)]
    report = audit_realtime_gap(study, rows)
    assert report.status == "no_large_gap_detected"  # 3 discordants: not significant
    rows = [pair(i, pause=True, live=i >= 15) for i in range(20)]
    report = audit_realtime_gap(study, rows)
    assert report.status == "realtime_gap_detected"
    assert report.pairs == 20 and report.paused_successes == 20
    assert report.realtime_successes == 5
    assert report.paused_only_successes == 15
    assert report.realtime_deadline_misses == 20
    assert report.deadline_misses_in_paused_only_losses == 15
    assert report.exact_one_sided_p < 0.01
    assert report.protocol_sha256 == study.digest
    assert not any(
        (
            report.authorizes_play,
            report.authorizes_model_promotion,
            report.authorizes_streaming,
            report.establishes_cause,
        )
    )


def test_equally_weak_models_do_not_claim_latency_cause():
    rows = [pair(i, pause=False, live=False, live_delay=100) for i in range(20)]
    report = audit_realtime_gap(protocol(), rows)
    assert report.status == "both_modes_struggle"
    assert report.realtime_deadline_misses == 0
    assert report.exact_one_sided_p == 1.0


def test_no_realtime_gap_with_equal_success():
    rows = [pair(i, pause=i % 2 == 0, live=i % 2 == 0, live_delay=90) for i in range(20)]
    report = audit_realtime_gap(protocol(), rows)
    assert report.status == "no_large_gap_detected"
    assert report.realtime_action_p95_ms == 90


@pytest.mark.parametrize(
    "bad_cases",
    [
        (),
        (("map0", 1),) * 20,
        tuple((f"scene{i}", i) for i in range(20)),
        tuple((f"map{i // 10}", True if i == 1 else i) for i in range(20)),
        tuple((f"map{i // 10}", i) for i in range(257)),
    ],
)
def test_protocol_rejects_non_preregistered_or_unbalanced_cases(bad_cases):
    with pytest.raises(ValueError):
        GameModeGapProtocol(game_scope="game.v1", cases=bad_cases)


def test_protocol_digest_is_order_sensitive_and_finite():
    study = protocol()
    assert study.digest == protocol().digest
    swapped = list(study.cases)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    assert study.digest != replace(study, cases=tuple(swapped)).digest
    with pytest.raises(ValueError):
        replace(study, max_scene_deadline_ms=float("nan"))
    with pytest.raises(ValueError):
        replace(study, max_scene_deadline_ms=True)


def test_missing_cases_or_repeated_cases_fail_not_optimistically():
    rows = [pair(i) for i in range(20)]
    with pytest.raises(ValueError):
        audit_realtime_gap(protocol(), rows[:-1])
    with pytest.raises(ValueError):
        audit_realtime_gap(protocol(), rows[:-1] + [rows[0]])


def test_changed_game_scope_and_forged_case_ids_fail():
    rows = [pair(i) for i in range(20)]
    with pytest.raises(ValueError):
        audit_realtime_gap(
            protocol(),
            [
                replace(rows[0], realtime=replace(rows[0].realtime, game_scope="other")),
                *rows[1:],
            ],
        )
    with pytest.raises(ValueError):
        audit_realtime_gap(
            protocol(),
            [
                rows[0],
                replace(rows[1], paused=replace(rows[1].paused, case_id=rows[0].paused.case_id)),
                *rows[2:],
            ],
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda x: replace(x, matching_start_verified=False),
        lambda x: replace(x, independent_outcome_verified=False),
        lambda x: replace(x, realtime=replace(x.realtime, host_verified=False)),
        lambda x: replace(x, realtime=replace(x.realtime, split="practice")),
        lambda x: replace(x, realtime=replace(x.realtime, mode="paused")),
        lambda x: replace(x, realtime=replace(x.realtime, seed=13)),
        lambda x: replace(x, realtime=replace(x.realtime, case_id=x.paused.case_id)),
        lambda x: replace(x, realtime_scene_deadline_ms=math.inf),
    ],
)
def test_unverified_or_unpaired_evidence_is_rejected(change):
    with pytest.raises((ValueError, TypeError)):
        change(pair(0))


def test_invalid_case_list_and_runtime_budget():
    rows = [pair(i) for i in range(20)]
    with pytest.raises(ValueError):
        audit_realtime_gap(
            protocol(),
            [
                *rows[:-1],
                replace(
                    rows[-1],
                    realtime_scene_deadline_ms=500,
                ),
            ],
        )
    with pytest.raises(TypeError):
        audit_realtime_gap(protocol(), [*rows[:-1], None])
    with pytest.raises(ValueError):
        audit_realtime_gap(protocol(), tuple(rows) + (rows[0],))


def test_no_live_speech_action_or_model_promotion():
    report = audit_realtime_gap(protocol(), [pair(i) for i in range(20)])
    fields = str(report).lower()
    assert report.status == "realtime_gap_detected"
    assert "not cryptographic" in report.note.lower()
    assert "transcript" not in fields


def test_excessive_action_delay_rejected():
    with pytest.raises(ValueError, match="unbounded"):
        pair(0, live_delay=60_001)
