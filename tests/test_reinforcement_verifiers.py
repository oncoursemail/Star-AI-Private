from star.reinforcement_loop import LoopConfig, Verification
from star.reinforcement_verifiers import (
    DifficultySignal,
    VerificationPanel,
    VerifierSpec,
    compute_optimal_config,
)


def test_panel_requires_independent_checks_and_preserves_evidence():
    panel = VerificationPanel([
        VerifierSpec("tests", lambda *_: Verification(0.98, True, "all tests passed", "tests"), weight=2),
        VerifierSpec("api", lambda *_: Verification(0.95, True, "api valid", "api")),
    ], min_trusted=2)
    report = panel.evaluate("task", "candidate")
    verdict = report.as_verification()
    assert report.passed is True
    assert verdict.passed is True and verdict.trusted is True
    assert verdict.verifier == "panel:tests+api"
    assert report.disagreement < 0.02
    assert all(len(c.evidence_sha256) == 64 for c in report.components)


def test_panel_blocks_required_failure_veto_and_disagreement():
    panel = VerificationPanel([
        VerifierSpec("tests", lambda *_: Verification(0.99, True, "tests pass", "tests")),
        VerifierSpec("api", lambda *_: Verification(0.10, False, "invalid api", "api"), veto_below=0.4),
    ])
    report = panel.evaluate("task", "candidate")
    assert report.passed is False
    assert "api:required" in report.hard_failures
    assert "api:veto" in report.hard_failures
    assert "panel:disagreement" in report.hard_failures


def test_panel_blocks_untrusted_evidence_even_when_it_is_optional():
    panel = VerificationPanel([
        VerifierSpec("tests", lambda *_: Verification(0.95, True, "tests pass", "tests")),
        VerifierSpec("judge", lambda *_: Verification(0.4, False, "weak judge", "judge", trusted=False), required=False),
    ])
    report = panel.evaluate("task", "candidate")
    assert report.passed is False
    assert "judge:untrusted" in report.hard_failures


def test_compute_optimal_policy_spends_most_on_useful_hard_tasks():
    easy = compute_optimal_config(DifficultySignal(0.95))
    medium = compute_optimal_config(DifficultySignal(0.60))
    hard = compute_optimal_config(DifficultySignal(0.20))
    hopeless = compute_optimal_config(DifficultySignal(0.05))

    assert easy.initial_candidates < medium.initial_candidates < hard.initial_candidates
    assert hard.max_rounds > medium.max_rounds
    assert hopeless.initial_candidates < hard.initial_candidates


def test_compute_policy_preserves_quality_thresholds_and_respects_cost():
    base = LoopConfig(pass_score=0.97, min_improvement=0.05, max_candidate_chars=4096)
    normal = compute_optimal_config(DifficultySignal(0.2), base=base)
    costly = compute_optimal_config(DifficultySignal(0.2, verifier_cost=0.9), base=base)
    assert normal.pass_score == 0.97 and normal.min_improvement == 0.05
    assert normal.max_candidate_chars == 4096
    assert costly.initial_candidates < normal.initial_candidates
