import json
import os
import subprocess

import pytest

from litha import pr_fixer as F
from litha import self_tune as st

RAW = ("a = 0\n<<<<<<< HEAD\ny = 1\n||||||| base\ny = 0\n=======\ny = 2\n>>>>>>> origin/main\nb = 0\n")


def case(cid, kind="merge", good="a = 0\ny = 3\nb = 0\n", **extra):
    return {"id": cid, "repo": "o/r", "base": "main", "source": "history", "kind": kind, "ours": "1" * 40,
            "theirs": "2" * 40, "path": "m.py", "title": "t", "raw": RAW, "good": good, "base_text": "y = 2\n",
            "edition": "2021", "split": "tune", **extra}


def answering(table, calls=None):
    """A fake model: the first (needle, answer) whose needle is in the prompt (None = no needle) answers."""
    def model(prompt):
        if calls is not None:
            calls.append(prompt)
        for needle, ans in table:
            if needle is None or needle in prompt:
                if isinstance(ans, Exception):
                    raise ans
                return json.dumps({"resolved": ans})
        raise ValueError("no answer")
    return model


def test_score_counts_exact_wrong_refusals_and_caches_her_answers(tmp_path):
    cases = [case("exact"), case("wrong", good="a = 0\ny = 9\nb = 0\n"), case("nogood", good=None),
             case("refuse", kind="must_refuse", good=None, reason="semantic")]
    calls, cache = [], st.Cache(tmp_path / "answers.jsonl")
    model = answering([(None, "y = 3\n")], calls)
    r = st.score({}, cases, model, 0, cache, log=tmp_path / "runs.jsonl")
    got = {cid: x["outcome"] for cid, x in r["cases"].items()}
    assert got == {"exact": "exact", "wrong": "wrong", "nogood": "compiles", "refuse": "resolved-must-refuse"}
    assert r["points"] == 2 and r["total"] == 4 and r["calls"] == 4 == len(calls)
    assert r["cases"]["wrong"]["blocks"][0]["mine"] == "y = 3\n"
    again = st.score({}, cases, model, 0, st.Cache(tmp_path / "answers.jsonl"), log=None)   # from the file
    assert again["calls"] == 0 and again["cached"] == 4 and len(calls) == 4
    assert json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[0])["points"] == 2
    refused = st.score({}, cases[3:], answering([(None, ValueError("no"))]), 1, st.Cache(None), log=None)
    assert refused["cases"]["refuse"]["outcome"] == "refused-ok"


def test_an_override_reaches_her_prompt_and_is_put_back(tmp_path):
    seen = []
    prompt = F.MERGE_PROMPT.replace("Keep BOTH sides' changes", "Keep BOTH sides' changes (NEW)")
    st.score({"MERGE_PROMPT": prompt}, [case("x")], answering([(None, "y = 3\n")], seen), 0, st.Cache(None), log=None)
    assert "(NEW)" in seen[0] and "(NEW)" not in F.MERGE_PROMPT
    assert st.prompt_hash({"MERGE_PROMPT": prompt}) != st.prompt_hash({})
    with pytest.raises(KeyError):
        with st.replay(case("x"), {"ROUNDS": 9}):
            pass
    assert F.ROUNDS == 5


def test_a_replay_runs_no_git_command():
    with st.replay(case("x"), {}) as tree:
        assert F.sh(["git", "show", "origin/main:m.py"], cwd=tree).stdout == "y = 2\n"
        assert F.sh(["git", "status"], cwd=tree).returncode == 1
        assert F.sh(["git", "push", "origin", "x"], cwd=tree).returncode == 1
        assert (tree / "Cargo.toml").read_text() == 'edition = "2021"\n'
    assert F.sh is not None and F.sh.__name__ == "sh"


def test_an_edit_must_be_one_exact_small_change_and_becomes_a_patch():
    old = "Keep BOTH sides' changes"
    text = json.dumps({"target": "MERGE_PROMPT", "old": old, "new": old + " (rule)", "why": "w"})
    over, why = st.parse_edit("Here: " + text)
    assert why == "w" and "(rule)" in over["MERGE_PROMPT"]
    diff = st.patch(over)
    assert diff.startswith("--- a/litha/pr_fixer.py") and "+Keep BOTH sides' changes (rule)" in diff
    assert st.parse_edit(json.dumps({"target": "ANSWER", "new": 1800})) == ({"ANSWER": 1800}, "")
    assert "ANSWER = 1800" in st.patch({"ANSWER": 1800})
    for bad in ({"target": "MERGE_PROMPT", "old": "not in it", "new": "x"},
                {"target": "MERGE_PROMPT", "old": "{context}", "new": ""},                  # loses the code
                {"target": "MERGE_PROMPT", "old": "{feedback}", "new": "{nope}"},            # unknown placeholder
                {"target": "ANSWER", "new": 99}, {"target": "ROUNDS", "new": 9}):
        with pytest.raises((ValueError, KeyError)):
            st.parse_edit(json.dumps(bad))


def edit(rule="Keep BOTH sides' changes"):
    return lambda prompt: json.dumps({"target": "MERGE_PROMPT", "old": rule, "new": rule + " RULE", "why": "w"})


def test_a_proposal_is_kept_only_when_the_replay_score_rises(tmp_path):
    cases = [case(f"c{i}") for i in range(3)] + [case("same", good=None)]
    cases[2]["split"] = "hold"                                          # a gain must show on a held-out case too
    model = answering([("RULE", "y = 3\n"), (None, "y = 1\n")])         # the new rule fixes 3 cases
    asked = []
    reps = st.propose(cases, model, lambda p: asked.append(p) or edit()(p), cache=st.Cache(None),
                      out=tmp_path / "prop", ledger=tmp_path / "spend.jsonl", log=None)
    assert reps[-1]["result"] == "kept" and reps[-1]["verdict"]["gains"] == ["c0", "c1", "c2"]
    assert reps[-1]["verdict"]["old"] == 1 and reps[-1]["verdict"]["new"] == 4
    assert "RULE" in (tmp_path / "prop" / os.path.basename(reps[-1]["patch"])).read_text()
    assert "Her 5 worst failures" in asked[0] and "### c0" in asked[0]
    assert " RULE" not in F.MERGE_PROMPT                                # never written into the code


def test_a_proposal_that_breaks_one_good_case_is_rejected(tmp_path):
    cases = [case(f"c{i}") for i in range(3)] + [case("other")]
    model = answering([("RULE", "y = 3\n"), (None, "y = 1\n")])
    cases[3]["good"] = "a = 0\ny = 1\nb = 0\n"                          # solved by the old prompt, broken by the new
    reps = st.propose(cases, model, edit(), cache=st.Cache(None), out=tmp_path / "prop",
                      ledger=tmp_path / "spend.jsonl", log=None)
    v = reps[-1]["verdict"]
    assert reps[-1]["result"] == "rejected" and v["flips"] == ["other"] and v["new"] > v["old"]
    assert "patch" not in reps[-1] and not list((tmp_path / "prop").glob("*.patch"))
    asked = []
    st.propose(cases, model, lambda p: asked.append(p) or "no edit", cache=st.Cache(None), out=tmp_path / "prop",
               ledger=tmp_path / "spend.jsonl", log=None)
    assert "already tried and rejected" in asked[0] and "RULE" in asked[0]           # the next round tries another


def test_no_claude_call_once_the_lane_budget_is_spent(tmp_path):
    ledger = tmp_path / "spend.jsonl"
    ledger.write_text("\n".join(json.dumps({"usd": u, "what": w}) for u, w in
                                ((4.7, "selftune: propose"), (50.0, "Metallic-Club/studio: merge"))) + "\n")
    assert st.lane_spent(ledger) == pytest.approx(4.7)
    reps = st.propose([case("c0")], answering([(None, "y = 1\n")]), lambda p: pytest.fail("no Claude call"),
                      cache=st.Cache(None), out=tmp_path / "prop", ledger=ledger, log=None)
    assert reps == [{"result": "budget", "spent": 4.7}]


def git(repo, *args, check=True):
    env = dict(os.environ, GIT_AUTHOR_NAME="p", GIT_AUTHOR_EMAIL="p@x", GIT_COMMITTER_NAME="p",
               GIT_COMMITTER_EMAIL="p@x")
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=check).stdout


def test_build_freezes_conflicting_merges_with_the_committed_answer(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "m.py").write_bytes(b"a = 0\ny = 0\nb = 0\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    git(repo, "checkout", "-qb", "pr")
    (repo / "m.py").write_bytes(b"a = 0\ny = 1\nb = 0\n")
    git(repo, "commit", "-qam", "pr")
    git(repo, "checkout", "-q", "main")
    (repo / "m.py").write_bytes(b"a = 0\ny = 2\nb = 0\n")
    git(repo, "commit", "-qam", "main")
    git(repo, "checkout", "-q", "pr")
    git(repo, "merge", "-q", "main", check=False)                        # conflicts
    (repo / "m.py").write_bytes(b"a = 0\ny = 3\nb = 0\n")
    git(repo, "add", "m.py")
    git(repo, "commit", "-qm", "Merge main into pr")
    merge = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-ref", "refs/remotes/origin/main", "main")
    monkeypatch.setattr(st, "MUST_REFUSE", [("o/r", merge, "m.py", "a test case")])
    out = tmp_path / "cases.json"
    got = st.build([("o/r", "main", repo, True)], log=tmp_path / "none.jsonl", out=out)
    assert [c["source"] for c in got] == ["refuse"]                     # the same conflict once, as must-refuse
    c = got[0]
    assert c["kind"] == "must_refuse" and c["bad"] == "a = 0\ny = 3\nb = 0\n" and c["base_text"] == "a = 0\ny = 2\nb = 0\n"
    assert "<<<<<<< HEAD\ny = 1\n||||||| " in c["raw"] and ">>>>>>> origin/main\n" in c["raw"]
    assert st.cases(out) == got                                          # the frozen file is what cases() reads
    monkeypatch.setattr(st, "MUST_REFUSE", [])
    h = st.build([("o/r", "main", repo, True)], log=tmp_path / "none.jsonl", out=out)
    assert len(h) == 1 and h[0]["source"] == "history" and h[0]["good"] == "a = 0\ny = 3\nb = 0\n"
    r = st.score({}, h, answering([(None, "y = 3\n")]), 0, st.Cache(None), log=None)
    assert r["outcomes"] == {"exact": 1}
