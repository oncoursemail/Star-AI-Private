import json
import subprocess
import urllib.error

import pytest

from litha import experience as X
from litha import learn_nightly as N
from litha import pr_fixer as F
from litha import self_map
from litha import self_tune as st


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    """Every path the memory writes points into tmp; the switch is off unless a test turns it on."""
    monkeypatch.setattr(X, "STORE", tmp_path / "exp" / "lessons.jsonl")
    monkeypatch.setattr(X, "USES", tmp_path / "exp" / "uses.jsonl")
    monkeypatch.setattr(X, "SWITCH", tmp_path / "exp" / "on.json")
    monkeypatch.delenv("LITHA_EXPERIENCE", raising=False)
    monkeypatch.delenv("LITHA_SELF_NOTE", raising=False)
    X._LAST_USE.clear()
    X._LOCAL.ids = []


RAW = ("import os\n<<<<<<< HEAD\nwidget_total = compute_widget_total(order_lines)\n||||||| base\n"
       "widget_total = 0\n=======\nwidget_total = compute_widget_total(order_lines, tax_rate)\n"
       ">>>>>>> origin/main\nprint(widget_total)\n")
GOOD = "import os\nwidget_total = compute_widget_total(order_lines, tax_rate)\nprint(widget_total)\n"


def case(cid, split="tune", good=GOOD, kind="merge", repo="o/r"):
    return {"id": cid, "repo": repo, "base": "main", "source": "history", "kind": kind, "ours": "1" * 40,
            "theirs": "2" * 40, "path": "shop/cart.py", "title": "t", "raw": RAW, "good": good,
            "base_text": "x = 1\n", "edition": "2021", "split": split}


def lesson(text, sig_text, lane="resolve", good=True, **kw):
    return X.make(lane, kw.pop("repo", "o/r"), kw.pop("path", "shop/cart.py"), sig_text, text, good, ["e"], "test",
                  kw.pop("key", text), **kw)


def test_signature_keeps_identifiers_and_error_codes_and_drops_common_words():
    sig = X.signature("error[E0252]: the name `FrameOutput` is defined twice in compute_widget_total for the file")
    assert "e0252" in sig and "frameoutput" in sig and "compute_widget_total" in sig and "widget" in sig
    assert "the" not in sig and "file" not in sig and "error" not in sig


def test_fix_rows_become_lessons_and_noise_does_not():
    fixed = {"ts": 1, "pr": 831, "result": "fixed", "why": "requirements lock regenerated with pin_requirements.py",
             "tests": ["tests/test_home_installer.py"], "files": ["requirements-home.txt"],
             "fix_pr": "https://github.com/oncoursemail/Star-AI-Private/pull/850"}
    [x] = X.lessons_from_fix(fixed, {"state": "MERGED"})
    assert x["lane"] == "fix-python" and x["good"] and "pin_requirements" in x["text"] and "merged" in x["text"]
    assert x["evidence"][0].endswith("/Star-AI-Project/pull/831") and len(x["text"]) <= X.TEXT_CHARS
    [closed] = X.lessons_from_fix(fixed, {"state": "CLOSED"})
    assert not closed["good"] and "closed without merging" in closed["text"]
    assert X.fix_pr_number(fixed["fix_pr"]) == ("oncoursemail/Star-AI-Project", 850)     # renamed repo
    for row in ({"pr": 1, "result": "rerun", "why": "x"}, {"pr": 1, "result": "flaky-rerun", "why": "x"},
                {"pr": 1, "result": "failed", "why": "push failed (no force-push)"}, {"pr": 1, "result": "failed"}):
        assert X.lessons_from_fix(row) == []
    [m] = X.lessons_from_fix({"ts": 2, "repo": "o/r", "pr": 7, "result": "failed", "kind": "merge",
                              "why": "src/sim.rs: rustfmt rejects it: unexpected closing delimiter"})
    assert m["lane"] == "resolve" and m["path"] == "src/sim.rs" and m["kind"] == "rs" and not m["good"]


def test_holds_are_settled_by_what_a_person_did_later():
    rows = [{"repo": "o/r", "pr": 5, "action": "hold", "title": "a", "reasons": ["Litha: m.py:3 crashes on None"]},
            {"repo": "o/r", "pr": 5, "action": "hold", "title": "a",
             "reasons": ["Litha: m.py:3 crashes when widget_total is None", "check CI failure"]},
            {"repo": "o/r", "pr": 6, "action": "hold", "title": "b", "reasons": ["Litha: n.ts:9 leaks the timer"]},
            {"repo": "o/r", "pr": 7, "action": "merge", "merged": True, "title": "c", "reasons": []},
            {"repo": "o/r", "pr": 8, "action": "hold", "title": "d", "reasons": ["Litha: q.py:1 wrong"]}]
    fates = {("o/r", 5): {"state": "MERGED"}, ("o/r", 6): {"state": "CLOSED"},
             ("o/r", 7): {"state": "MERGED", "reverted": True}, ("o/r", 8): {"state": "OPEN"}}
    got = {x["evidence"][0].rsplit("/", 1)[1]: x for x in X.lessons_from_decisions(rows, fates)}
    assert set(got) == {"5", "6", "7"}                              # the last row per PR; an open PR teaches nothing
    assert not got["5"]["good"] and "overturned" in got["5"]["text"] and "widget_total" in got["5"]["text"]
    assert got["6"]["good"] and "closed unmerged" in got["6"]["text"]
    assert not got["7"]["good"] and "reverted" in got["7"]["text"]


def test_gh_fates_reads_states_and_reverts_without_writing():
    def run(args, **kw):
        assert args[:3] == ["gh", "pr", "list"]
        return subprocess.CompletedProcess(args, 0, json.dumps([
            {"number": 3, "state": "MERGED", "title": "Add carts"},
            {"number": 4, "state": "MERGED", "title": 'Revert "Add carts"'},
            {"number": 5, "state": "CLOSED", "title": "x"}]), "")
    f = X.gh_fates(["o/r"], run)
    assert f[("o/r", 3)] == {"state": "MERGED", "reverted": True} and not f[("o/r", 5)]["reverted"]


def test_retrieval_picks_the_relevant_lesson_hides_its_own_case_and_skips_retired():
    store = X.Store(None, [lesson("keep the tax_rate argument of compute_widget_total", RAW, case="c1"),
                           lesson("unrelated: renderer shader uniforms", "shader uniform buffer render pipeline"),
                           lesson("fix-python lesson about widget_total", RAW, lane="fix-python")])
    task = ("resolve", "o/r", ["shop/cart.py"], RAW)
    found = store.retrieve(*task)
    assert [x["text"][:8] for x in found] == ["keep the"]
    assert store.retrieve(*task, hide="c1") == []
    lid = found[0]["id"]
    assert store.settle([lid], False) == [] and store.settle([lid], False) == []
    assert store.settle([lid, lid], False) == [lid]                 # 3 losses, no win: retired (once per call)
    assert store.retrieve(*task) == [] and store.lessons[lid]["retired"]


def test_render_fits_the_room():
    xs = [lesson(f"lesson number {i} " + "w" * 150, RAW, key=str(i)) for i in range(5)]
    text = X.render(xs, 130)
    assert text.count("- Worked:") == 2 and len(text) / X.CHARS_PER_TOKEN <= 130
    assert X.render(xs, 10) == ""


def test_the_memory_is_off_until_the_gate_or_the_owner_turns_it_on(monkeypatch):
    X.Store(X.STORE, [lesson("keep the tax_rate argument of compute_widget_total", RAW)]).save()
    task = {"lane": "resolve", "repo": "o/r", "paths": ["shop/cart.py"], "text": RAW}
    assert X.note(task, 500) == ""
    X.SWITCH.write_text(json.dumps({"lanes": ["resolve"]}))
    assert "tax_rate argument" in X.note(task, 500)
    assert X.note({**task, "lane": "merge-review"}, 500) == ""
    monkeypatch.setenv("LITHA_EXPERIENCE", "0")
    assert X.note(task, 500) == ""


def test_fitted_adds_lessons_only_when_on_and_they_fit(monkeypatch):
    X.Store(X.STORE, [lesson("keep the tax_rate argument of compute_widget_total", RAW)]).save()
    build = lambda note: f"PROMPT{note}END"                                        # noqa: E731
    task = {"repo": "o/r", "paths": ["shop/cart.py"], "text": RAW}
    assert self_map.fitted("resolve", build, 100, task=task) == "PROMPTEND"      # off: exactly as before
    monkeypatch.setenv("LITHA_EXPERIENCE", "1")
    on = self_map.fitted("resolve", build, 100, task=task)
    assert "Worked: keep the tax_rate" in on and on.endswith("END")
    assert self_map.fitted("resolve", build, 4090, task=task) == "PROMPTEND"     # no room left in the window
    assert self_map.fitted("resolve", build, 100) == "PROMPTEND"                 # no task: no lessons


def test_live_outcomes_settle_the_lessons_that_were_shown(monkeypatch):
    X.Store(X.STORE, [lesson("keep the tax_rate argument of compute_widget_total", RAW, lane="fix-python")]).save()
    monkeypatch.setenv("LITHA_EXPERIENCE", "1")
    assert X.note({"lane": "fix-python", "repo": "o/r", "paths": ["shop/cart.py"], "text": RAW}, 500)
    X.record_fix({"ts": 5, "repo": "o/r", "pr": 9, "result": "fixed", "why": "the cause was a missing tax_rate",
                  "tests": ["tests/test_cart.py"], "files": ["shop/cart.py"]})
    store = X.Store(X.STORE)
    assert len(store.lessons) == 2 and sum(x["wins"] for x in store.lessons.values()) == 1
    assert X._LOCAL.ids == []
    review = {"lane": "fix-python", "repo": "o/r", "paths": ["shop/cart.py"], "text": RAW, "key": "o/r#4"}
    X.note(review, 500)
    X.note(review, 500)                                                            # the same PR again: one row
    [use] = [json.loads(ln) for ln in X.USES.read_text().splitlines()]
    n = X.settle_reviews(store, {("o/r", 4): {"state": "MERGED"}}, [{"repo": "o/r", "pr": 4, "action": "hold"}])
    assert n == 1 and X.USES.read_text() == "" and sum(x["losses"] for x in store.lessons.values()) == len(use["ids"]) == 2


def test_backfill_from_the_logs_is_idempotent(tmp_path):
    fixes, decisions = tmp_path / "fixes.jsonl", tmp_path / "decisions.jsonl"
    fixes.write_text(json.dumps({"ts": 1, "pr": 3, "result": "failed", "why": "the new type errors remain",
                                 "tests": ["pyright baseline gate"]}) + "\n")
    decisions.write_text(json.dumps({"repo": "o/r", "pr": 6, "action": "hold", "title": "b",
                                     "reasons": ["Litha: n.ts:9 leaks the timer"]}) + "\n")
    store = X.Store(None, [])
    fates = {("o/r", 6): {"state": "CLOSED"}}
    assert X.backfill(store, fixes, decisions, fates) == {"fixes": 1, "decisions": 1, "settled": 0}
    assert X.backfill(store, fixes, decisions, fates) == {"fixes": 0, "decisions": 0, "settled": 0}


def test_merge_shape_names_what_the_accepted_merge_did():
    assert "only the base" in X.merge_shape("a\n", "o\n", "b\n", "b\n")
    assert "only the PR" in X.merge_shape("a\n", "o\n", "b\n", "a\n")
    assert "PR's first" in X.merge_shape("o\na\n", "o\n", "o\nb\n", "o\na\nb\n")
    assert "base branch's first" in X.merge_shape("o\na\n", "o\n", "o\nb\n", "o\nb\na\n")
    assert "line by line" in X.merge_shape("a\n", "o\n", "b\n", "c\n")


def test_replay_lessons_come_from_the_tune_split_only():
    cases = [case("t1"), case("h1", split="hold"), case("t2", good=None), case("t3")]
    result = {"cases": {"t1": {"outcome": "wrong"}, "h1": {"outcome": "wrong"}, "t2": {"outcome": "refused"},
                        "t3": {"outcome": "exact"}}}
    got = X.lessons_from_replay(cases, result)
    assert [x["case"] for x in got] == ["t1"]
    assert "only the base branch's side" in got[0]["text"] and got[0]["text"].startswith("shop/cart.py")


def fake_model(calls=None):
    """Right ("tax_rate" kept) only when a lesson is in the prompt; otherwise the PR's side."""
    def model(prompt):
        if calls is not None:
            calls.append(prompt)
        right = "Lessons from your own past work" in prompt
        return json.dumps({"resolved": "widget_total = compute_widget_total(order_lines"
                           + (", tax_rate)\n" if right else ")\n")})
    return model


def test_score_with_lessons_reaches_her_prompt_but_never_the_case_itself():
    cases = [case("t1"), case("t2"), case("h1", split="hold")]
    base = st.score({}, cases, fake_model(), 0, st.Cache(None), log=None)
    assert base["points"] == 0 and base["hold_total"] == 1 and base["lessons"] is False
    store = N.lessons_for(cases, base, None)
    assert {x["case"] for x in store.active()} == {"t1", "t2"}
    calls = []
    got = st.score({}, cases, fake_model(calls), 0, st.Cache(None), log=None, lessons=store)
    assert got["hold"] == 1 and got["points"] == 3 and any("Lessons from" in c for c in calls)
    solo = st.score({}, cases[:1], fake_model(), 0, st.Cache(None), log=None, lessons=X.Store(None, list(
        x for x in store.active() if x["case"] == "t1")))
    assert solo["points"] == 0                                         # its own lesson is hidden from it
    assert X.STORE.exists() is False                                   # a replay writes nothing


def test_compare_keeps_a_change_only_with_a_held_out_gain():
    cases = [case("t1"), case("t2"), case("h1", split="hold")]
    cache = st.Cache(None)
    base = st.score({}, cases, fake_model(), 0, cache, log=None)
    store = N.lessons_for(cases, base, None)
    new = st.score({}, cases, fake_model(), 0, cache, log=None, lessons=store)
    v = st.compare(base, new, {}, cases, fake_model(), cache, None, store)
    assert v["keep"] and v["hold_old"] == 0 and v["hold_new"] == 1 and v["gains"] == ["h1", "t1", "t2"]
    tune_only = [case("t1"), case("t2"), case("t3")]                   # gains, but no held-out case to prove them
    base2 = st.score({}, tune_only, fake_model(), 0, cache, log=None)
    store2 = N.lessons_for(tune_only, base2, None)
    new2 = st.score({}, tune_only, fake_model(), 0, cache, log=None, lessons=store2)
    assert not st.compare(base2, new2, {}, tune_only, fake_model(), cache, None, store2)["keep"]


def test_cases_leave_the_excluded_repo_out(tmp_path, monkeypatch):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [case("a", repo="Metallic-Club/studio"), case("b")]}))
    assert [c["id"] for c in st.cases(path)] == ["b"]
    assert "Metallic-Club/studio" in st.EXCLUDED
    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(a))
    assert st.build([("Metallic-Club/studio", "main", tmp_path / "nope", True)], log=tmp_path / "f.jsonl",
                    out=tmp_path / "c2.json") == []
    assert "excluded" in str(printed)


def test_a_night_turns_the_memory_on_only_after_a_held_out_gain(tmp_path):
    cases = [case("t1"), case("t2"), case("h1", split="hold")]
    switch = tmp_path / "on.json"
    rep = N.run(fake_model(), cases, st.Cache(None), store_path=tmp_path / "lessons.jsonl", switch=switch,
                reports=tmp_path / "reports", cand_dir=tmp_path / "cand", log=None, nightly=tmp_path / "n.jsonl")
    assert rep["on"] == ["resolve"] and json.loads(switch.read_text())["lanes"] == ["resolve"]
    assert rep["baseline"]["hold"] == 0 and rep["experience"]["hold"] == 1
    assert json.loads((tmp_path / "n.jsonl").read_text())["experience"]["keep"] is True
    assert len(X.Store(tmp_path / "lessons.jsonl").active("resolve")) == 2          # kept for the live store
    plain = lambda p: json.dumps({"resolved": "widget_total = compute_widget_total(order_lines)\n"})   # noqa: E731
    (tmp_path / "cand").mkdir()
    old = "Keep BOTH sides' changes"
    (tmp_path / "cand" / "c1.json").write_text(json.dumps({"target": "MERGE_PROMPT", "old": old, "new": old + "!",
                                                           "why": "w"}))
    rep = N.run(plain, cases, st.Cache(None), store_path=None, switch=switch, reports=tmp_path / "reports",
                cand_dir=tmp_path / "cand", log=None, nightly=None)
    assert rep["on"] == [] and json.loads(switch.read_text())["lanes"] == []
    assert [c["result"] for c in rep["candidates"]] == ["rejected"]
    assert (tmp_path / "cand" / "done" / "c1.json").exists() and " RULE" not in F.MERGE_PROMPT


def test_node_model_retries_a_busy_node_and_gives_up_on_a_bad_request(monkeypatch):
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    seen = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return json.dumps({"choices": [{"message": {"content": '{"resolved": "x"}'}}]}).encode()

    def opener(req, timeout):
        seen.append(json.loads(req.data))
        if len(seen) == 1:
            raise ConnectionRefusedError("busy")
        return Answer()
    ask = N.node_model("http://node/v1", "tok", opener=opener)
    assert ask("p") == '{"resolved": "x"}' and len(seen) == 2
    assert seen[0]["max_tokens"] == 1500 and seen[0]["temperature"] == 0.2 and seen[0]["model"] == "litha-fast"

    def bad(req, timeout):
        raise urllib.error.HTTPError("u", 400, "too long", {}, None)
    with pytest.raises(ValueError):
        N.node_model("http://node/v1", "tok", opener=bad)("p")


def test_a_replayed_case_never_sees_a_lesson_learnt_after_it_and_the_switch_limits_sources():
    later = lesson("keep the tax_rate argument of compute_widget_total", RAW, ts=2000)
    store = X.Store(None, [later])
    assert store.retrieve("resolve", "o/r", ["shop/cart.py"], RAW, before=1000) == []
    assert store.retrieve("resolve", "o/r", ["shop/cart.py"], RAW, before=3000) == [later]
    assert store.retrieve("resolve", "o/r", ["shop/cart.py"], RAW, sources={"distilled"}) == []
    X.Store(X.STORE, [later]).save()
    X.SWITCH.write_text(json.dumps({"lanes": ["resolve"], "sources": ["distilled"]}))
    task = {"lane": "resolve", "repo": "o/r", "paths": ["shop/cart.py"], "text": RAW}
    assert X.note(task, 500) == ""                                   # a "test" lesson: not a measured source
    X.SWITCH.write_text(json.dumps({"lanes": ["resolve"], "sources": ["test"]}))
    assert "tax_rate" in X.note(task, 500)


def test_distill_asks_claude_about_tune_failures_only_and_keeps_answered_cases():
    cases = [case("t1"), case("t2"), case("h1", split="hold"), case("t3")]
    for c, at in zip(cases, (10, 20, 30, 40)):
        c["at"] = at
    result = {"cases": {"t1": {"outcome": "wrong", "blocks": [{"mine": "widget_total = 1\n"}]},
                        "t2": {"outcome": "refused", "why": "too big"}, "h1": {"outcome": "wrong"},
                        "t3": {"outcome": "exact"}}}
    asked = []

    def claude(prompt):
        asked.append(prompt)
        return json.dumps({"lessons": [{"case": "t1", "lesson": "cart totals: the base side's tax_rate call wins"},
                                       {"case": "h1", "lesson": "never: not shown"}, {"case": "t2", "lesson": ""}]})
    got = X.distill(cases, result, claude)
    assert len(asked) == 1 and "case t1" in asked[0] and "case t2" in asked[0] and "h1" not in asked[0]
    assert "Her answer:\nwidget_total = 1" in asked[0] and "refused: too big" in asked[0]
    assert [(x["case"], x["source"], x["ts"]) for x in got] == [("t1", "distilled", 10)]
    assert X.distill(cases, result, lambda p: "not json") == []


def test_stamp_reads_commit_times_from_the_clone(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "p", "GIT_AUTHOR_EMAIL": "p@x", "GIT_COMMITTER_NAME": "p", "GIT_COMMITTER_EMAIL": "p@x",
           "GIT_COMMITTER_DATE": "2026-01-02T03:04:05Z", "GIT_AUTHOR_DATE": "2026-01-02T03:04:05Z"}
    import os
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True,  # noqa: E731
                                    env={**os.environ, **env}, check=True).stdout
    run("init", "-q")
    (repo / "f").write_text("x")
    run("add", ".")
    run("commit", "-qm", "c")
    sha = run("rev-parse", "HEAD").strip()
    cases = [dict(case("a"), commit=sha), case("b", repo="other/r")]
    assert N.stamp(cases, [("o/r", "main", repo, True)]) == 1
    assert cases[0]["at"] == 1767323045 and "at" not in cases[1]


def test_same_file_variant_only_shows_lessons_about_the_tasks_own_file():
    other = lesson("keep the tax_rate argument of compute_widget_total", RAW, path="shop/other.py")
    store = X.Store(None, [other])
    assert store.retrieve("resolve", "o/r", ["shop/cart.py"], RAW) == [other]
    store.same_path = True
    assert store.retrieve("resolve", "o/r", ["shop/cart.py"], RAW) == []
    assert store.retrieve("resolve", "o/r", ["shop/other.py"], RAW) == [other]
    assert N.lessons_for([], {"cases": {}}, None, {"test"}, True).same_path is True
