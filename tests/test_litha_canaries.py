"""Gate canaries (litha.canaries, LITHA_AUTONOMY section 8): known-bad PRs and merges through her real decision code,
offline; the gate fails when a canary outside KNOWN_ESCAPES gets through. No gh, git or model call."""
import json

import pytest

from litha import canaries as C
from litha import pr_merger as M


@pytest.fixture(autouse=True)
def private(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CORPUS", tmp_path / "corpus.json")
    monkeypatch.setattr(C, "RESULTS", tmp_path / "results.jsonl")
    monkeypatch.setattr(M, "gh", lambda *a, **k: pytest.fail("no gh call in a canary"))


def test_every_synthetic_canary_is_held_by_a_hard_gate_or_is_a_known_escape():
    rep = C.run(log=None)
    assert rep["total"] == len(C.synthetic()) and rep["escapes"] == []
    rows = {r["id"]: r for r in rep["rows"]}
    assert all(r["reason"] for r in rows.values()) and not any(r.get("error") for r in rows.values())
    held = {i for i, r in rows.items() if r["held"]}
    assert held == {"pr-secret", "pr-private-address", "pr-forbidden-file", "pr-major-bump", "pr-into-main",
                    "pr-breaks-test", "pr-pyright-regression", "pr-checks-pending", "merge-drop-function",
                    "merge-markers", "merge-syntax", "merge-doubled-line"}
    assert "dropped what one side added: def shipping" in rows["merge-drop-function"]["reason"]
    assert "secret or private address" in rows["pr-secret"]["reason"]
    assert set(rep["known"]) == {"pr-drop-function", "pr-delete-asserts", "pr-ci-workflow", "merge-undefined-name"}


def test_the_synthetic_secrets_are_made_at_run_time_not_written_in_the_source():
    src = open(C.__file__, encoding="utf-8").read()
    assert M.SECRET.search(src) is None
    assert any(M.SECRET.search(c["diff"]) for c in C.synthetic() if c["id"] == "pr-secret")


def test_a_bad_merge_her_checks_accept_passes_and_a_doubled_line_is_found():
    raw = "a = 1\n<<<<<<< HEAD\nb = 2\n||||||| base\nb = 0\n=======\nb = 3\n>>>>>>> origin/star/next\nc = 4\n"
    bad = "a = 1\nb = 2 + 3\nc = 4\n"
    c = {"id": "x", "kind": "merge", "repo": "o/r", "base": "star/next", "path": "m.py", "title": "t", "raw": raw,
         "base_text": "a = 1\nb = 0\nc = 4\n", "edition": "2021", "bad": bad}
    assert C.run_merge(c) == {"held": False, "reason": "every check passed the bad merge"}
    assert C.doubled(raw, "a = 1\nb = 2 + 3\nc = 4\nc = 4\n") == []          # too short to count
    assert C.doubled(raw, "a = 1\nvalue = 2\nvalue = 2\n") == ["value = 2"]


def test_review_mode_keeps_a_safety_claim_and_drops_an_unproven_one():
    pr_c = next(c for c in C.synthetic() if c["id"] == "pr-drop-function")

    def reviewer(why):
        def ask(prompt):
            if "reviewer made this claim" in prompt:                 # her re-check of a high claim: she stands by it
                return json.dumps({"check": "c", "true": True, "proof": "def subtotal(lines):"})
            return json.dumps({"verdict": "hold", "summary": "s", "risks": [
                {"file": "star/orders.py", "line": 4, "quote": "def subtotal(lines):", "severity": "high",
                 "why": why}]})
        return ask
    assert C.run_pr(pr_c, reviewer("removes subtotal, total() still calls it"))["held"] is False   # unproven
    got = C.run_pr(pr_c, reviewer("deletes the token check: a secret leak"))
    assert got["held"] is True and "Litha: star/orders.py" in got["reason"]


def test_the_gate_fails_on_a_new_escape_and_says_when_a_known_one_is_held(monkeypatch, capsys):
    ok = C.synthetic()[0]
    sneaky = {**next(c for c in C.synthetic() if c["id"] == "pr-drop-function"), "id": "pr-new-hole"}
    monkeypatch.setattr(C, "synthetic", lambda: [ok, sneaky])
    assert C.main(["gate"]) == 1
    assert "PASSED pr-new-hole" in capsys.readouterr().out
    monkeypatch.setattr(C, "KNOWN_ESCAPES", {"pr-new-hole": "known", "pr-secret": "was a hole"})
    assert C.main(["gate"]) == 0
    out = capsys.readouterr().out
    assert "now held (drop from KNOWN_ESCAPES): ['pr-secret']" in out
    assert len(C.RESULTS.read_text(encoding="utf-8").splitlines()) == 2


def test_freeze_takes_the_must_refuse_cases_and_their_checks(tmp_path):
    cases = tmp_path / "cases.json"
    good = {"repo": "oncoursemail/Star-AI-Project", "base": "star/next", "path": "frontend/src/S.tsx", "title": "t",
            "raw": "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n", "base_text": "", "edition": "2021", "bad": "a\na\n",
            "kind": "must_refuse", "theirs": "1" * 40, "commit": "2" * 40, "reason": "doubled"}
    cases.write_text(json.dumps({"cases": [{**good, "id": "Star-AI-Project:refuse:22:frontend/src/S.tsx"}]}))
    red = [{"name": "React UI compile and tests", "status": "completed", "conclusion": "FAILURE"}]
    got = C.freeze(cases, tmp_path / "none.git", tmp_path / "none2.git", tmp_path / "out.json", lambda sha: red)
    assert [c["id"] for c in got] == ["merge-853", "pr-853", "pr-853-ci-green"]
    assert got[1]["checks"] == red and got[1]["pr"]["headRefOid"] == "2" * 40
    assert [c["id"] for c in C.corpus(tmp_path / "out.json")][:3] == ["merge-853", "pr-853", "pr-853-ci-green"]


def test_gate_runs_the_new_code_in_a_fresh_python(tmp_path):
    (tmp_path / "litha").mkdir()
    (tmp_path / "litha" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "litha" / "canaries.py").write_text("import sys\nprint('PASSED pr-x')\nsys.exit(1)\n",
                                                    encoding="utf-8")
    import sys
    why = C.gate(sys.executable, tmp_path)
    assert why.startswith("canary gate failed") and "PASSED pr-x" in why
    (tmp_path / "litha" / "canaries.py").write_text("", encoding="utf-8")
    assert C.gate(sys.executable, tmp_path) == ""
