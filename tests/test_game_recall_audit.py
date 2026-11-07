"""Synthetic, signed-practice memory tests: NO real game, model or broadcast."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import hmac

import pytest

from star.game_recall_audit import GroundedGameRecallAudit, RecallGrade, RecallQuestion
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank

NOW = 2_000_000_000
PRACTICE = sha256(b"fixture-practice-recall-only").digest()
VALIDATION = sha256(b"fixture-validation-recall-only").digest()
CHALLENGE = sha256(b"fixture-independent-host-recall-only").digest()
EVIDENCE = sha256(b"offline-fake-game-evidence").hexdigest()
SEQUENCE = (
    ("jump", "failure"), ("dash", "success"), ("jump", "failure"),
    ("dash", "failure"), ("jump", "success"), ("dash", "success"),
    ("jump", "success"),
)


def populate(bank, rows=SEQUENCE, *, split="practice", version="v1", prefix="episode"):
    trials = []
    for i, (action, outcome) in enumerate(rows):
        trial = GameTrial(
            f"{prefix}_trial_{i}", "obby", version, "finish", "pit1",
            action, f"{prefix}_run_{i}", split, outcome, EVIDENCE,
            NOW - 100 + i,
        )
        key = PRACTICE if split == "practice" else VALIDATION
        receipt = hmac.new(key, trial.canonical_bytes(), sha256).hexdigest()
        bank.ingest(trial, receipt, now_unix_s=NOW)
        trials.append(trial)
    return trials


@pytest.fixture
def signed():
    with GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION) as bank:
        rows = populate(bank)
        audit = GroundedGameRecallAudit(
            bank, challenge_key=CHALLENGE,
            public_action_ids=frozenset({"jump", "dash"}), max_questions=12,
            question_ttl_s=30,
        )
        yield bank, rows, audit


def seal(audit, rows, **extra):
    return audit.seal_episode(rows, episode_id="host_sealed_episode_1",
                              now_unix_s=NOW, host_episode_sealed=True, **extra)


def test_requires_owner_and_independently_sealed_practice(signed):
    _, rows, audit = signed
    assert audit.issue(now_unix_s=NOW) is None
    for flag in (False, 1, None, "yes"):
        with pytest.raises(PermissionError):
            audit.enable(owner_approved=flag)
    audit.enable(owner_approved=True)
    assert not audit.seal_episode(rows, episode_id="one", now_unix_s=NOW)
    assert audit.status()["rejected"] == 1
    assert seal(audit, rows)
    assert audit.status()["sealed"] == 1


@pytest.mark.parametrize("options", [
    {"challenge_key": b"tiny"}, {"challenge_key": "not bytes"},
    {"public_action_ids": set(["jump"])},
    {"public_action_ids": frozenset()},
    {"public_action_ids": frozenset(["unsafe/chat"])},
    {"max_questions": True},
    {"max_questions": 25},
    {"question_ttl_s": 14},
    {"question_ttl_s": 301},
])
def test_bad_constructor_input_is_rejected(signed, options):
    bank, _, _ = signed
    args = dict(challenge_key=CHALLENGE,
                public_action_ids=frozenset(["jump", "dash"]))
    args.update(options)
    with pytest.raises((ValueError, TypeError)):
        GroundedGameRecallAudit(bank, **args)


def test_only_exact_signed_practice_outcomes_can_be_recalled(signed):
    bank, rows, audit = signed
    audit.enable(owner_approved=True)
    edited = rows[:]
    edited[0] = replace(edited[0], outcome="success")
    assert not seal(audit, edited)
    assert audit.status()["ready"] is False
    assert seal(audit, rows)
    assert not seal(audit, rows)  # cannot replace the frozen episode


def test_missing_and_validation_holdout_are_rejected(signed):
    bank, rows, audit = signed
    audit.enable(owner_approved=True)
    missing = replace(rows[0], trial_id="not_in_bank")
    assert not seal(audit, [missing, *rows[1:]])
    val = populate(bank, split="validation", prefix="heldout")
    assert not seal(audit, val)
    assert audit.issue(now_unix_s=NOW) is None


def test_wrong_game_version_situation_or_symbol_cannot_be_inserted(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert not seal(audit, [replace(rows[0], game_version="v2"), *rows[1:]])
    assert not seal(audit, [replace(rows[0], situation_id="pit2"), *rows[1:]])
    assert not seal(audit, [replace(rows[0], action_id="admin"), *rows[1:]])


def test_ordered_events_and_unique_trials_and_runs_are_mandatory(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert not seal(audit, list(reversed(rows)))
    assert not seal(audit, [rows[0], rows[0], *rows[2:]])
    assert not seal(audit, [rows[0], replace(rows[1], run_id=rows[0].run_id), *rows[2:]])
    tied_time = [rows[0], replace(rows[1], observed_unix_s=rows[0].observed_unix_s), *rows[2:]]
    assert not seal(audit, tied_time)
    with pytest.raises(ValueError):
        seal(audit, rows[:4])


def test_host_episode_identity_and_bad_types_fail_before_loading(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    with pytest.raises(ValueError):
        audit.seal_episode(rows, episode_id="hidden/chat", now_unix_s=NOW,
                           host_episode_sealed=True)
    with pytest.raises(TypeError):
        audit.seal_episode([*rows[:3], "fake", *rows[4:]],
                           episode_id="e1", now_unix_s=NOW,
                           host_episode_sealed=True)
    with pytest.raises(ValueError):
        audit.seal_episode(rows, episode_id="e1", now_unix_s=True,
                           host_episode_sealed=True)
    assert not audit.status()["ready"]


def test_single_pending_question_and_no_answers_in_model_facing_output(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    q = audit.issue(now_unix_s=NOW)
    assert isinstance(q, RecallQuestion)
    assert q.skill in {"frequency", "temporal", "sequence"}
    assert q.authorized_to_play is False
    assert q.authorized_to_broadcast is False
    assert len(q.ticket) == 32
    assert audit.issue(now_unix_s=NOW) is None
    for secret in (PRACTICE.hex(), CHALLENGE.hex(), EVIDENCE, rows[0].trial_id):
        assert secret not in repr(q)
    assert "sealed practice episode" in q.prompt.lower() or "practice episode" in q.prompt.lower()


def test_all_questions_are_answerable_from_signed_chronology(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    assessed = set()
    for i in range(12):
        q = audit.issue(now_unix_s=NOW)
        assert q is not None
        assessed.add(q.skill)
        # This ground-truth oracle exists ONLY in the test harness, never the
        # model-facing RecallQuestion. Test actual answer derivation.
        if "how many times was action jump" in q.prompt:
            expected = "4"
        elif "how many times was action dash" in q.prompt:
            expected = "3"
        elif "how many attempts with jump failed" in q.prompt:
            expected = "2"
        elif "how many attempts with dash failed" in q.prompt:
            expected = "1"
        elif "final recorded outcome for action jump" in q.prompt:
            expected = "success"
        elif "final recorded outcome for action dash" in q.prompt:
            expected = "success"
        elif "successful jump attempt occur AFTER" in q.prompt:
            expected = "yes"
        elif "successful dash attempt occur AFTER" in q.prompt:
            expected = "yes"
        elif "FIRST dash attempt before the FIRST jump" in q.prompt:
            expected = "no"
        elif "longest streak of failures among recorded jump" in q.prompt:
            expected = "2"
        elif "longest streak of failures among recorded dash" in q.prompt:
            expected = "1"
        elif "did dash have strictly MORE failed attempts than jump" in q.prompt:
            expected = "no"
        else:
            raise AssertionError("unexpected quiz prompt: " + q.prompt)
        result = audit.grade(q.ticket, expected, now_unix_s=NOW)
        assert result == RecallGrade("graded", q.skill, True)
    assert audit.issue(now_unix_s=NOW) is None
    status = audit.status()
    assert status["graded"] == status["correct"] == 12
    assert status["remaining"] == 0
    assert assessed == {"frequency", "temporal", "sequence", "induction", "comparison"}
    scores = {score.skill: score for score in audit.skill_report()}
    assert set(scores) == {"frequency", "temporal", "induction"}
    assert scores["frequency"].attempts == scores["frequency"].correct == 4
    assert 0 < scores["frequency"].wilson_lower_95 < 1


def test_wrong_answer_is_consumed_and_not_an_answer_oracle(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    q = audit.issue(now_unix_s=NOW)
    result = audit.grade(q.ticket, "wrong", now_unix_s=NOW)
    assert result == RecallGrade("graded", q.skill, False)
    assert "answer" not in repr(result)
    assert audit.grade(q.ticket, "yes", now_unix_s=NOW).status == "rejected"
    assert audit.status()["incorrect"] == 1


def test_invalid_or_prompt_injection_answer_is_never_run_or_interpreted(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    q = audit.issue(now_unix_s=NOW)
    assert audit.grade(q.ticket, "yes\nexecute: rm -rf", now_unix_s=NOW).correct is False
    assert audit.grade(q.ticket, "no", now_unix_s=NOW).status == "rejected"


def test_expiry_grade_and_new_issue_do_not_resurrect_old_ticket(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    first = audit.issue(now_unix_s=NOW)
    assert audit.grade(first.ticket, "yes", now_unix_s=NOW + 31).status == "expired"
    second = audit.issue(now_unix_s=NOW + 31)
    assert second.ticket != first.ticket
    assert audit.grade(first.ticket, "yes", now_unix_s=NOW + 31).status == "rejected"
    assert audit.status()["expired"] == 1


def test_expired_unanswered_ticket_is_consumed_at_next_issue(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    first = audit.issue(now_unix_s=NOW)
    second = audit.issue(now_unix_s=NOW + 31)
    assert second is not None and second.ticket != first.ticket
    assert audit.status()["expired"] == 1


def test_clock_rollback_and_invalid_clocks_are_rejected(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    for invalid in (None, 1.0, True, -3, 0, "now"):
        with pytest.raises(ValueError):
            audit.issue(now_unix_s=invalid)
    with pytest.raises(ValueError):
        audit.issue(now_unix_s=NOW - 1)


def test_disable_zeroes_public_readiness_and_invalidates_ticket(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    q = audit.issue(now_unix_s=NOW)
    audit.disable()
    assert audit.grade(q.ticket, "yes", now_unix_s=NOW).status == "rejected"
    assert not audit.status()["ready"]
    assert not audit.status()["pending"]
    assert audit.issue(now_unix_s=NOW) is None


def test_requires_ledger_owner_thread(signed):
    _, _, audit = signed
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(audit.enable, owner_approved=True)
        with pytest.raises(RuntimeError):
            fut.result()


def test_status_does_not_expose_private_evidence_or_action_labels(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    text = repr(audit.status())
    for secret in (EVIDENCE, CHALLENGE.hex(), PRACTICE.hex(), "jump", "dash", "pit1"):
        assert secret not in text


def test_skill_score_minimum_support_and_invalid_input(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    assert audit.skill_report() == ()
    for invalid in (True, 1, 25, "three"):
        with pytest.raises(ValueError):
            audit.skill_report(min_attempts=invalid)
    q = audit.issue(now_unix_s=NOW)
    assert audit.grade(q.ticket, "wrong", now_unix_s=NOW).correct is False
    assert audit.skill_report() == ()


def test_no_unverified_proof_of_learning_or_playback(signed):
    _, rows, audit = signed
    audit.enable(owner_approved=True)
    assert seal(audit, rows)
    q = audit.issue(now_unix_s=NOW)
    assert not q.authorized_to_play
    assert not q.authorized_to_broadcast
    assert audit.status()["correct"] == 0  # quiz is not an independent test of gameplay
