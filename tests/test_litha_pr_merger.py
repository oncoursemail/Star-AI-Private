from __future__ import annotations

import json

import litha.pr_merger as M

DIFF = """diff --git a/star/a.py b/star/a.py
--- a/star/a.py
+++ b/star/a.py
@@ -1,2 +1,4 @@
 import os
+import asyncio
+def go():
+    return asyncio.run(work())
 x = 1
diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml
@@ -0,0 +1 @@
+lock
"""
SOURCE = "import os\nimport asyncio\ndef go():\n    return asyncio.run(work())\nx = 1\nasync def work():\n    pass\n"
GOOD = {"number": 1, "title": "t", "isDraft": False, "baseRefName": "star/next", "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN", "headRefOid": "abc"}
PASSED = [{"name": "ci", "status": "completed", "conclusion": "SUCCESS"}]


def test_parse_diff_numbers_added_lines():
    files = M.parse_diff(DIFF)
    assert files["star/a.py"]["added"] == {2: "import asyncio", 3: "def go():", 4: "    return asyncio.run(work())"}


def test_hard_gates_block_on_facts():
    files = M.parse_diff(DIFF)
    assert M.gate_failures(GOOD, PASSED, {"star/a.py": files["star/a.py"]}) == []
    why = M.gate_failures({**GOOD, "baseRefName": "main", "isDraft": True}, [], files)
    assert any("only star/next" in w for w in why) and "draft" in why and any("no checks" in w for w in why)
    assert any("forbidden file pnpm-lock.yaml" in w for w in why)
    failed = [{"name": "ci", "status": "completed", "conclusion": "FAILURE"}]
    assert M.gate_failures(GOOD, failed, {})[0] == "check ci failure"
    leak = {"x.py": {"text": "", "added": {3: 'host = "10.99.0.1"'}}}  # star:allow
    assert M.gate_failures(GOOD, PASSED, leak) == ["possible secret or private address at x.py:3"]
    marked = {"x.py": {"text": "", "added": {3: 'host = "10.99.0.1"  # star:allow'}}}  # star:allow
    assert M.gate_failures(GOOD, PASSED, marked) == []                 # the same marker star commit accepts
    pin = {"r.txt": {"text": "", "added": {1: "pywin32==10.3.10.19"}}}  # star:allow
    assert M.gate_failures(GOOD, PASSED, pin) == []


def test_claims_must_point_at_added_lines_and_survive_the_real_code():
    files = {"star/a.py": M.parse_diff(DIFF)["star/a.py"]}
    answers = iter([json.dumps({"verdict": "hold", "summary": "s", "risks": [
        {"file": "star/a.py", "line": 4, "severity": "high", "why": "`work` is not defined in the diff"},
        {"file": "star/a.py", "line": 99, "severity": "high", "why": "made up line"},
        {"file": "star/a.py", "line": 3, "severity": "high", "why": "this could leak memory"}]})])
    rev = M.review(GOOD, files, ask=lambda p: next(answers), read=lambda pr, path: SOURCE)
    assert rev["verdict"] == "merge" and rev["dropped_claims"] == 1
    assert [r["severity"] for r in rev["risks"]] == ["refuted", "low"]


def test_a_proven_high_risk_blocks_and_an_unproven_one_does_not():
    files = {"star/a.py": M.parse_diff(DIFF)["star/a.py"]}
    first = json.dumps({"verdict": "hold", "risks": [
        {"file": "star/a.py", "line": 4, "severity": "high", "why": "go() returns a coroutine result twice"}]})
    proven = iter([first, json.dumps({"true": True, "proof": "4:     return asyncio.run(work())"})])
    assert M.review(GOOD, files, ask=lambda p: next(proven), read=lambda pr, path: SOURCE)["verdict"] == "hold"
    invented = iter([first, json.dumps({"true": True, "proof": "return asyncio.run(other())"})])
    assert M.review(GOOD, files, ask=lambda p: next(invented), read=lambda pr, path: SOURCE)["verdict"] == "merge"


def test_decide_never_asks_the_model_when_gates_block_and_merge_refuses_main():
    asked = []
    row = M.decide({**GOOD, "isDraft": True}, ask=asked.append, checks_fn=lambda sha: PASSED, diff_fn=lambda pr: DIFF)
    assert row["action"] == "hold" and asked == []
    try:
        M.merge({**GOOD, "baseRefName": "main"})
    except RuntimeError as e:
        assert "refusing" in str(e)
    else:
        raise AssertionError("merged outside star/next")


def test_a_proven_hunt_find_stops_a_merge_the_review_allowed():
    clean = DIFF.split("diff --git a/pnpm-lock.yaml")[0]
    ok = lambda p: json.dumps({"verdict": "merge", "summary": "fine", "risks": []})  # noqa: E731

    def hunt(pr, files, rev):
        assert set(files["star/a.py"]["added"]) == {2, 3, 4}
        rev["risks"].append({"file": "star/a.py", "line": 4, "severity": "high", "why": "hunt: wrong call"})
        rev["verdict"] = "hold"

    row = M.decide(GOOD, ask=ok, checks_fn=lambda sha: PASSED, diff_fn=lambda pr: clean, hunt_fn=hunt)
    assert row["action"] == "hold" and row["reasons"] == ["Litha: star/a.py:4 hunt: wrong call"]
    row = M.decide(GOOD, ask=ok, checks_fn=lambda sha: PASSED, diff_fn=lambda pr: clean, hunt_fn=lambda *a: None)
    assert row["action"] == "merge"


def test_a_major_dependency_bump_waits_for_a_run_on_her_pc():
    diff = ("diff --git a/requirements-home.in b/requirements-home.in\n--- a/requirements-home.in\n"
            "+++ b/requirements-home.in\n@@ -1,2 +1,2 @@\n-huggingface-hub>=0.21,<2   # note\n"
            "+huggingface-hub>=2.4.0,<3   # note\n-yt-dlp[default]==2026.10.21\n+yt-dlp[default]==2026.10.26\n")
    files = M.parse_diff(diff)
    assert M.major_bumps(files) == ["huggingface-hub >=0.21,<2 -> >=2.4.0,<3"]
    assert any("major dependency bump" in w for w in M.gate_failures(GOOD, PASSED, files))


def test_merging_into_main_needs_the_repo_to_allow_it(monkeypatch):
    monkeypatch.setattr(M, "gh", lambda *a, **k: "merged")
    monkeypatch.setattr(M, "BASE", "main")
    for allowed, ok in ((False, False), (True, True)):
        monkeypatch.setattr(M, "ALLOW_MAIN", allowed)
        try:
            M.merge({**GOOD, "baseRefName": "main"})
            assert ok
        except RuntimeError as e:
            assert not ok and "main" in str(e)
    monkeypatch.setattr(M, "BASE", "*")                                  # review-only repos never merge
    try:
        M.merge({**GOOD, "baseRefName": "anything"})
        raise AssertionError("merged in a review-only repo")
    except RuntimeError:
        pass
    repos = json.loads(M.REPOS.read_text(encoding="utf-8"))["repos"]
    assert repos[0]["repo"] == M.REPO and all(r["mode"] in ("merge", "review") for r in repos)


def test_an_intended_change_with_its_updated_test_is_not_a_hunt_hold(tmp_path):
    """The hunt's existing-test proof on a green PR: the PR changed the behaviour AND its test, so the module's tests
    pass on the head and nothing is proven (running the base's old test on the head would be a false hold)."""
    import sys

    from litha import bug_hunt

    def tree(name, body, test):
        t = tmp_path / name
        (t / "star").mkdir(parents=True)
        (t / "tests").mkdir()
        (t / "star" / "__init__.py").write_text("", encoding="utf-8")
        (t / "star" / "calc.py").write_text(body, encoding="utf-8")
        (t / "tests" / "test_calc.py").write_text(f"from star.calc import cap\n\n\ndef test_cap():\n    {test}\n",
                                                  encoding="utf-8")
        return t

    base = tree("base", "def cap(x):\n    return min(x, 10)\n", "assert cap(50) == 10")
    head = tree("head", "def cap(x):\n    return min(x, 20)\n", "assert cap(50) == 20")    # meant: the PR body says so
    suspect = lambda p: json.dumps({"suspects": [{"line": 2, "why": "cap should stay 10"}]})  # noqa: E731
    no_test = lambda p: json.dumps({"possible": False})                                     # noqa: E731
    asks = iter([suspect, no_test, no_test, no_test])
    found = bug_hunt.hunt(head, base, {"star/calc.py": {2}}, sys.executable, lambda p: next(asks)(p))
    assert found == []


def _fake_gh(monkeypatch, results):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[1:])
        code, err = results.pop(0)
        return type("R", (), {"returncode": code, "stdout": "ok" if code == 0 else "", "stderr": err})()
    monkeypatch.setattr(M.subprocess, "run", run)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    return calls


def test_a_network_blip_on_a_read_is_retried_instead_of_holding_the_pr(monkeypatch):
    calls = _fake_gh(monkeypatch, [(1, 'Post "https://api.github.com/graphql": net/http: TLS handshake timeout'),
                                   (0, "")])
    assert M.gh("pr", "diff", "5") == "ok"
    assert len(calls) == 2


def test_a_write_or_a_real_error_is_never_retried(monkeypatch):
    calls = _fake_gh(monkeypatch, [(1, "net/http: TLS handshake timeout")])
    try:
        M.gh("pr", "merge", "5")
    except RuntimeError:
        pass
    assert len(calls) == 1
    calls = _fake_gh(monkeypatch, [(1, "GraphQL: Could not resolve to a PullRequest")])
    try:
        M.gh("pr", "view", "5")
    except RuntimeError:
        pass
    assert len(calls) == 1
