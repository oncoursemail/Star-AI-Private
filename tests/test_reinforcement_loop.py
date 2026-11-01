from star.reinforcement_loop import LoopConfig, Verification, run_loop


def test_loop_promotes_verified_initial_candidate():
    answers = ["bad", "correct", "almost", "different"]

    def generate(_task, seed):
        return answers[seed]

    def verify(_task, candidate):
        score = {"bad": 0.1, "correct": 0.98, "almost": 0.7, "different": 0.3}[candidate]
        return Verification(score=score, passed=candidate == "correct", evidence=f"score={score}", verifier="unit")

    result = run_loop(
        "solve",
        generate=generate,
        verify=verify,
        critique=lambda *_: "fix",
        refine=lambda *_: "unused",
    )

    assert result.passed is True
    assert result.answer == "correct"
    assert result.stop_reason == "verified_initial_candidate"
    assert result.rounds_used == 0


def test_loop_refines_until_verified():
    def generate(_task, seed):
        return f"attempt-{seed}"

    def verify(_task, candidate):
        if candidate == "fixed-1":
            return Verification(0.96, True, "all host checks passed", "sandbox")
        return Verification(0.40, False, "assertion failed", "sandbox")

    result = run_loop(
        "repair code",
        generate=generate,
        verify=verify,
        critique=lambda _task, _candidate, verdict: f"Use evidence: {verdict.evidence}",
        refine=lambda _task, _candidate, _feedback, variant: f"fixed-{variant}",
        config=LoopConfig(initial_candidates=2, max_rounds=2, refinements_per_round=2),
    )

    assert result.passed is True
    assert result.answer == "fixed-1"
    assert result.stop_reason == "verified_refinement"
    assert any(a.critique for a in result.attempts if a.round == 1)


def test_untrusted_pass_is_rejected():
    def verify(_task, _candidate):
        return Verification(1.0, True, "model says it passed", "model-self-report", trusted=False)

    try:
        run_loop(
            "task",
            generate=lambda _task, seed: f"candidate-{seed}",
            verify=verify,
            critique=lambda *_: "fix",
            refine=lambda *_: "new",
            config=LoopConfig(initial_candidates=1),
        )
    except PermissionError as exc:
        assert "untrusted" in str(exc)
    else:
        raise AssertionError("untrusted verification must never promote")


def test_score_threshold_can_downgrade_semantic_pass():
    def verify(_task, _candidate):
        return Verification(0.75, True, "partial checks", "unit")

    result = run_loop(
        "task",
        generate=lambda _task, seed: f"candidate-{seed}",
        verify=verify,
        critique=lambda *_: "re-solve",
        refine=lambda _task, _candidate, _feedback, variant: f"refined-{variant}",
        config=LoopConfig(initial_candidates=1, max_rounds=1, refinements_per_round=1, pass_score=0.9),
    )

    assert result.passed is False
    assert "below loop pass_score" in result.evidence


def test_duplicate_refinements_stop_cleanly():
    result = run_loop(
        "task",
        generate=lambda _task, _seed: "same",
        verify=lambda *_: Verification(0.2, False, "failed", "unit"),
        critique=lambda *_: "try again",
        refine=lambda *_: "same",
        config=LoopConfig(initial_candidates=3, max_rounds=3, refinements_per_round=2),
    )

    assert result.passed is False
    assert result.stop_reason == "no_novel_candidates"
    assert len(result.attempts) == 1
