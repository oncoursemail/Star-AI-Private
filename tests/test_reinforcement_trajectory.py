import hashlib

import pytest

from star.reinforcement_loop import Attempt, LoopResult, Verification
from star.reinforcement_trajectory import (
    TrajectoryFence,
    build_preference_candidate,
    build_sft_candidate,
    sha256,
)


def _attempt(text, score, passed, round_no=0):
    return Attempt(
        round=round_no,
        candidate=text,
        candidate_sha256=hashlib.sha256(text.encode()).hexdigest(),
        verification=Verification(score, passed, f"evidence {text}", "trusted-host"),
    )


def _result():
    bad = _attempt("bad answer", 0.40, False)
    almost = _attempt("almost answer", 0.72, False)
    good = _attempt("verified answer", 0.98, True, 1)
    return LoopResult(
        answer=good.candidate,
        answer_sha256=good.candidate_sha256,
        passed=True,
        best_score=0.98,
        rounds_used=1,
        attempts=(bad, almost, good),
        stop_reason="verified_refinement",
        verifier="trusted-host",
    )


def test_verified_winner_becomes_sft_without_evaluator_text():
    fence = TrajectoryFence(frozenset(), "a" * 64)
    row = build_sft_candidate("solve this", _result(), task_id="task-1", domain="coding", fence=fence)
    assert row["messages"][1]["content"] == "verified answer"
    assert row["score"] == 0.98
    assert "evidence" not in str(row["messages"])
    assert len(row["verification_evidence_sha256"]) == 64
    assert row["training_started"] is False and row["requires_outer_holdout_gate"] is True


def test_preference_pair_uses_strongest_failed_candidate():
    fence = TrajectoryFence(frozenset(), "b" * 64)
    row = build_preference_candidate("solve this", _result(), task_id="task-1", domain="coding", fence=fence)
    assert row["chosen"] == "verified answer"
    assert row["rejected"] == "almost answer"
    assert row["score_margin"] == pytest.approx(0.26)


def test_holdout_and_secrets_are_refused():
    task = "solve this"
    fence = TrajectoryFence(frozenset({sha256(task)}), "c" * 64)
    with pytest.raises(PermissionError, match="holdout"):
        build_sft_candidate(task, _result(), task_id="task-1", domain="coding", fence=fence)

    fence = TrajectoryFence(frozenset(), "c" * 64)
    with pytest.raises(PermissionError, match="credential"):
        build_sft_candidate(
            "api_key=abcdefghijklmnop",
            _result(),
            task_id="task-1",
            domain="coding",
            fence=fence,
        )


def test_unverified_loop_cannot_become_training_data():
    result = _result()
    failed = LoopResult(
        answer=result.answer,
        answer_sha256=result.answer_sha256,
        passed=False,
        best_score=result.best_score,
        rounds_used=result.rounds_used,
        attempts=result.attempts,
        stop_reason="budget_exhausted",
        verifier=result.verifier,
    )
    with pytest.raises(PermissionError):
        build_sft_candidate(
            "solve this",
            failed,
            task_id="task-1",
            domain="coding",
            fence=TrajectoryFence(frozenset(), "d" * 64),
        )
