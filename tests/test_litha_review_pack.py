from __future__ import annotations

import json

import litha.pr_merger as M
from litha import review_pack as P

CODE = """diff --git a/star/gate.py b/star/gate.py
--- a/star/gate.py
+++ b/star/gate.py
@@ -10,5 +10,4 @@ def send(user, msg):
     text = msg.strip()
-    if not user.allowed:
-        raise PermissionError(user)
+    log(text)
     return post(text)
"""
DOCS = """diff --git a/docs/notes.md b/docs/notes.md
--- a/docs/notes.md
+++ b/docs/notes.md
@@ -1,1 +1,3 @@
 # Notes
+Some words about the change.
+More words.
"""
DATA = "diff --git a/evidence/run.json b/evidence/run.json\n@@ -0,0 +1,2 @@\n+{\"a\": 1,\n+ \"b\": 2}\n"
GOOD = {"number": 1, "title": "t", "headRefOid": "abc"}


def test_kinds_and_a_removed_guard_ranks_first():
    assert [P.kind(p) for p in ("star/a.py", "tests/test_a.py", "docs/x.md", "a/b.json", "ci.yml", "Cargo.lock")] == \
        ["code", "test", "docs", "data", "config", "data"]
    hs = {h["path"]: h["score"] for h in P.hunks(M.parse_diff(DATA + DOCS + CODE))}
    assert hs["star/gate.py"] > hs["docs/notes.md"] > hs["evidence/run.json"]


def test_pack_fits_the_budget_and_lists_what_did_not_fit():
    files = M.parse_diff(DATA + DOCS + CODE)
    parts, left = P.pack(files, budget=10_000)
    assert len(parts) == 1 and left == [] and all(f"diff --git a/{p}" in parts[0] for p in files)
    one = P.tokens(P.render(P.hunks({"star/gate.py": files["star/gate.py"]})))
    parts, left = P.pack(files, budget=one + 5, max_parts=1)
    assert len(parts) == 1 and "star/gate.py" in parts[0] and "docs/notes.md" not in parts[0]
    assert sorted(left) == ["docs/notes.md (docs)", "evidence/run.json (data)"]
    note = P.others_note(parts[0], files, left)
    assert "docs/notes.md" in note and "2 skipped" in note and "not a fault" in note


def test_a_big_hunk_is_split_with_its_real_line_numbers():
    body = "".join(f"+line {i}\n" for i in range(200))
    files = M.parse_diff(f"diff --git a/star/big.py b/star/big.py\n@@ -0,0 +50,200 @@\n{body}")
    parts, left = P.pack(files, budget=300, max_parts=50)
    assert len(parts) > 1 and left == []
    assert all(P.tokens(p) <= 300 for p in parts)
    second = parts[1].splitlines()
    first_no = int(second[1].split("+")[1].split()[0])                  # "@@ +<n> @@": the next line is line n
    assert files["star/big.py"]["added"][first_no] == second[2][1:]


def test_anchor_needs_a_quote_that_is_a_changed_line():
    f = M.parse_diff(CODE)["star/gate.py"]
    assert P.anchor({"line": 99, "quote": "+    log(text)"}, f) == (11, "")             # re-anchored to the real line
    assert P.anchor({"line": 3, "quote": "if not user.allowed:"}, f) == (11, "")          # a removed guard
    assert P.anchor({"line": 12, "quote": "return post(text)"}, f)[0] is None           # context, not changed
    assert P.anchor({"line": 12, "quote": "user.delete()"}, f) == (None, "quote is not a changed line")
    assert P.anchor({"line": 11}, f) == (11, "") and P.anchor({"line": 12}, f)[0] is None   # no quote: old rule


def test_review_drops_invented_quotes_counts_a_line_once_and_every_prompt_fits():
    files = M.parse_diff(CODE + DOCS)
    seen = []

    def ask(prompt):
        seen.append(prompt)
        if prompt.startswith("A code reviewer made this claim"):
            return json.dumps({"true": True, "proof": "log(text)"})
        return json.dumps({"verdict": "hold", "summary": "s", "risks": [
            {"file": "star/gate.py", "line": 3, "quote": "log(text)", "severity": "high",
             "why": "the permission check was removed, anyone can post"},
            {"file": "star/gate.py", "line": 11, "quote": "log(text)", "severity": "low", "why": "same line again"},
            {"file": "star/gate.py", "line": 11, "quote": "os.remove(path)", "severity": "high", "why": "deletes"}]})

    source = "\n" * 11 + "    log(text)\n    return post(text)\n"
    rev = M.review(GOOD, files, ask=ask, read=lambda pr, path: source)
    assert [(r["line"], r["severity"]) for r in rev["risks"]] == [(11, "high")] and rev["verdict"] == "hold"
    assert rev["dropped_claims"] == 1 and rev["dropped_why"] == ["quote is not a changed line"]
    assert rev["parts"] == 1 and rev["not_reviewed"] == []
    review_prompt = seen[0]
    assert '"quote"' in review_prompt and P.tokens(review_prompt) + P.ANSWER <= M.self_map.WINDOW


def test_big_prs_get_several_parts_inside_the_window():
    body = "".join(f"+    value_{i} = compute(item, {i}) if item else None\n" for i in range(600))
    files = M.parse_diff(f"diff --git a/star/big.py b/star/big.py\n@@ -0,0 +1,600 @@\n{body}" + DOCS)
    prompts, left = M.review_prompts({"title": "big", "body": "x" * 5000}, files)
    assert 1 < len(prompts) <= P.MAX_PARTS
    assert all(P.tokens(p) * P.MARGIN + P.ANSWER <= M.self_map.WINDOW + 1 for p in prompts)
    assert any("this part shows 1" in p for p in prompts)


def test_a_head_is_reviewed_once_per_ttl_and_a_failed_part_is_asked_again(monkeypatch, tmp_path):
    asked = []
    answers = iter(["not json", json.dumps({"verdict": "merge", "summary": "ok", "risks": []})] + [""] * 9)

    def fake(prompt):
        asked.append(prompt)
        return next(answers)

    monkeypatch.setattr(M, "ask_litha", fake)
    files = M.parse_diff(CODE)
    cache = tmp_path / "reviews.json"
    assert M.cached_review(GOOD, files, M.ask_litha, cache)["not_json"] == 1 and not cache.exists()
    first = M.cached_review(GOOD, files, M.ask_litha, cache)
    again = M.cached_review(GOOD, files, M.ask_litha, cache)
    assert len(asked) == 2 and first["verdict"] == again["verdict"] == "merge" and "cached" in again
    M.cached_review({**GOOD, "headRefOid": "new"}, files, M.ask_litha, cache)       # a new head is a new review
    assert len(asked) == 3
    M.cached_review(GOOD, files, ask=lambda p: json.dumps({"verdict": "merge", "risks": []}), path=cache)
    assert len(asked) == 3                                                          # an own ask is never cached


def test_a_high_claim_on_a_test_or_doc_is_a_note_and_a_proof_may_drop_the_brace():
    diff = ("diff --git a/tests/test_gate.py b/tests/test_gate.py\n@@ -1,1 +1,2 @@\n x = 1\n+assert send(None)\n"
            + CODE)
    files = M.parse_diff(diff)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        if prompt.startswith("A code reviewer made this claim"):
            return json.dumps({"check": "the guard is gone", "true": True, "proof": "if user.allowed and text"})
        return json.dumps({"verdict": "hold", "risks": [
            {"file": "tests/test_gate.py", "line": 2, "quote": "assert send(None)", "severity": "high", "why": "fails"},
            {"file": "star/gate.py", "line": 11, "quote": "log(text)", "severity": "high", "why": "no auth check"}]})

    source = "\n" * 10 + "    if user.allowed and text: {\n    log(text)\n"
    rev = M.review(GOOD, files, ask=ask, read=lambda pr, path: source)
    assert [(r["file"], r["severity"]) for r in rev["risks"]] == [("tests/test_gate.py", "low"),
                                                                    ("star/gate.py", "high")]
    assert len(asked) == 2                                      # the test claim never cost a re-check
    assert P.quotes("for (let i = 1; i <= n + 1; i++)", "      for (let i = 1; i <= n + 1; i++) {")
    assert not P.quotes("return x", "    return xy") and not P.quotes("", "x")


def test_a_claim_she_cannot_verify_is_refuted_without_a_re_check():
    why = ("The method `_sleep_checked` is called but its definition is not included in the diff, making it impossible"
           " to verify if it handles the 'STOP' condition correctly or if it will cause a NameError.")
    assert M.refuted({"file": "star/a.py", "line": 1, "why": why}, "x = 1\n") == "she says she cannot verify it"
    assert M.refuted({"file": "star/a.py", "line": 1, "why": "divides by len(items), 0 for []"}, "x = 1\n") == ""
