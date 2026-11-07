"""Regressions for STAR's bounded, in-turn verified compute optimizations.

These fakes use no model, network, Studio, or unsafe code execution. They prove
work is shared only for identical inputs and repair never loses prior evidence.
"""
from __future__ import annotations

import asyncio
from star.best_of_n import BestOfN, Candidate, CheckResult, SamplePlan, STUB_MODULE

ONE = "```luau\nlocal x = 1\nreturn x\n```"
TWO = "```luau\nlocal x = 2\nreturn x\n```"


def engine(checker, *, repair=None, on_event=None):
    return BestOfN(
        SamplePlan(4, "luau", .8),
        prompt="Write Luau",
        checker=checker,
        sample=None,
        targets=[],
        repair=repair,
        on_event=on_event,
    )


class CountingChecker:
    can_run_tests = True

    def __init__(self):
        self.statics = []
        self.sandboxes = []

    def static(self, code, answer):
        self.statics.append((code, answer))
        return [CheckResult("code block", "pass"), CheckResult("syntax", "pass")]

    def run_tests(self, code, tests):
        self.sandboxes.append(code)
        return {"basic": code != STUB_MODULE, "second": code != STUB_MODULE}, ""


def test_identical_answers_reuse_static_and_identical_source_reuses_sandbox():
    checker = CountingChecker()
    events = []
    cases = [Candidate(1, "strong", answer=ONE), Candidate(2, "weak", answer=ONE),
             Candidate(3, "weak", answer="Explanation\n" + ONE), Candidate(4, "strong", answer=TWO)]
    result = asyncio.run(engine(checker, on_event=events.append).evaluate(cases, "generated tests"))
    assert len(checker.statics) == 3  # full answer affects static checker
    assert len(checker.sandboxes) == 3  # two source bodies + independent stub
    assert checker.sandboxes.count(STUB_MODULE) == 1
    assert result.tests == 2 and result.chosen.index == 1
    assert [c.unit for c in cases] == [(2, 2)] * 4
    assert cases[0].unit_raw is not cases[1].unit_raw
    assert cases[0].checks is not cases[1].checks
    assert cases[0].checks[-1] is not cases[1].checks[-1]
    stats = next(e for e in events if e["event"] == "best_of_n_verification_work")
    assert stats == {
        "event": "best_of_n_verification_work", "candidates": 4,
        "static_runs": 3, "static_reused": 1, "sandbox_runs": 2, "sandbox_reused": 2,
    }
    assert result.record()["verification_work"] == {
        key: value for key, value in stats.items() if key != "event"
    }


def test_failed_verifier_does_not_certify_candidate_or_abort_other_candidates():
    class Unavailable(CountingChecker):
        def static(self, code, answer):
            if "return x" in code and "x = 2" in code:
                raise RuntimeError("do not log source text here")
            return super().static(code, answer)

    checker = Unavailable()
    candidates = [Candidate(1, "weak", answer=TWO), Candidate(2, "strong", answer=ONE)]
    result = asyncio.run(engine(checker).evaluate(candidates, None))
    assert result.chosen.index == 2
    assert candidates[0].checks == [CheckResult("static verification", "fail", "RuntimeError")]
    assert "do not log source text" not in str(result.record())


def test_sandbox_exception_stays_not_run_and_other_work_continues():
    class Unavailable(CountingChecker):
        def run_tests(self, code, tests):
            if "x = 2" in code:
                raise ConnectionError("host contained a secret")
            return super().run_tests(code, tests)

    checker = Unavailable()
    candidates = [Candidate(1, "weak", answer=TWO), Candidate(2, "strong", answer=ONE)]
    result = asyncio.run(engine(checker).evaluate(candidates, "generated tests"))
    assert result.chosen.index == 2
    assert candidates[0].unit_raw is None
    assert any(c.status == "skip" and "ConnectionError" in c.detail for c in candidates[0].checks)
    assert "host contained a secret" not in str(result.record())


def test_stub_failure_never_counts_model_written_tests_as_independent_evidence():
    class StubDown(CountingChecker):
        def __init__(self, stub):
            super().__init__()
            self.stub = stub

        def run_tests(self, code, tests):
            if code == STUB_MODULE:
                return self.stub, "sandbox unavailable"
            return super().run_tests(code, tests)

    for stub in (None, {}, {"basic": 1}, {"basic": "yes"}):
        candidates = [Candidate(1, "x", answer=ONE), Candidate(2, "y", answer=TWO)]
        outcome = asyncio.run(engine(StubDown(stub)).evaluate(candidates, "generated tests"))
        assert outcome.tests == 0
        assert outcome.suspect_tests == 2
        assert all(c.unit is None for c in candidates)

    class PartialStub(CountingChecker):
        def run_tests(self, code, tests):
            if code == STUB_MODULE:
                return {"basic": False}, ""  # a second assertion could not run
            return super().run_tests(code, tests)

    candidates = [Candidate(1, "x", answer=ONE), Candidate(2, "y", answer=TWO)]
    outcome = asyncio.run(engine(PartialStub()).evaluate(candidates, "generated tests"))
    assert outcome.tests == 0 and outcome.suspect_tests == 2


def original_candidate():
    return Candidate(1, "strong", answer="```luau\nbroken\n```", code="broken",
                     checks=[CheckResult("syntax", "fail"), CheckResult("lint", "pass"),
                             CheckResult("unit tests", "fail")],
                     unit=(1, 2), unit_raw={"kept": True, "broken": False},
                     unit_failed=("broken",))


class RepairChecker:
    can_run_tests = True

    def __init__(self, response=None, drop_lint=False):
        self.response = response
        self.drop_lint = drop_lint

    def static(self, code, answer):
        return [CheckResult("syntax", "pass")] + ([] if self.drop_lint else [CheckResult("lint", "pass")])

    def run_tests(self, code, tests):
        return self.response


async def fix(prompt, code, problems):
    return "fixed"


def test_repair_rejected_when_previously_passing_test_regresses():
    checker = RepairChecker(({"kept": False, "broken": True}, ""))
    best = original_candidate()
    verdict = asyncio.run(engine(checker, repair=fix)._try_repair(best, "test code"))
    assert verdict is None
    assert not best.repaired and best.code == "broken"


def test_repair_rejected_when_sandbox_unavailable_or_static_coverage_disappears():
    for checker in (RepairChecker((None, "timeout")), RepairChecker(({"kept": True, "broken": True}, ""),
                                                                    drop_lint=True)):
        best = original_candidate()
        assert asyncio.run(engine(checker, repair=fix)._try_repair(best, "test code")) is None
        assert best.code == "broken" and not best.repaired


def test_repair_accepted_when_evidence_preserved_and_failures_reduced():
    checker = RepairChecker(({"kept": True, "broken": True}, ""))
    best = original_candidate()
    assert asyncio.run(engine(checker, repair=fix)._try_repair(best, "test code")) == "repaired"
    assert best.repaired and best.code.strip() == "fixed"
    assert best.unit == (2, 2) and best.unit_failed == ()
    assert best.unit_raw == {"kept": True, "broken": True}
    assert best.hard_failures == 0
