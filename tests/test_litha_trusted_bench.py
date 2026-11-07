"""The trusted bench (litha.trusted_bench, LITHA_AUTONOMY section 8): K runs per case, score/CI/MDE, paired tests,
the nightly paired gate and the frozen extra case sets. Fake models only; no git, gh or model call."""
import json
import math

import pytest

from litha import canaries as C
from litha import experience as X
from litha import learn_nightly as N
from litha import self_tune as st
from litha import trusted_bench as tb

RAW = ("import os\n<<<<<<< HEAD\nwidget_total = compute_widget_total(order_lines)\n||||||| base\n"
       "widget_total = 0\n=======\nwidget_total = compute_widget_total(order_lines, tax_rate)\n"
       ">>>>>>> origin/main\nprint(widget_total)\n")
GOOD = "import os\nwidget_total = compute_widget_total(order_lines, tax_rate)\nprint(widget_total)\n"
RIGHT = json.dumps({"resolved": "widget_total = compute_widget_total(order_lines, tax_rate)\n"})
WRONG = json.dumps({"resolved": "widget_total = compute_widget_total(order_lines)\n"})


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "STORE", tmp_path / "exp" / "lessons.jsonl")
    monkeypatch.setattr(X, "USES", tmp_path / "exp" / "uses.jsonl")
    monkeypatch.setattr(X, "SWITCH", tmp_path / "exp" / "on.json")
    monkeypatch.setattr(C, "CORPUS", tmp_path / "canaries" / "corpus.json")
    monkeypatch.setattr(C, "RESULTS", tmp_path / "canaries" / "results.jsonl")
    monkeypatch.delenv("LITHA_EXPERIENCE", raising=False)


def case(cid, split="tune", repo="o/r"):
    return {"id": cid, "repo": repo, "base": "main", "source": "history", "kind": "merge", "ours": "1" * 40,
            "theirs": "2" * 40, "path": "shop/cart.py", "title": "t", "raw": RAW, "good": GOOD,
            "base_text": "x = 1\n", "edition": "2021", "split": split}


def test_table_runs_every_case_k_times_and_summary_reports_score_ci_mde():
    cases = [case(f"c{i}") for i in range(6)]
    seen = []

    def model(prompt):                                   # a noisy model: the same case differs between runs
        seen.append(prompt)
        return RIGHT if len(seen) % 4 in (1, 2) else WRONG
    tab = tb.table({}, cases, model, 3, st.Cache(None))
    assert set(tab) == {c["id"] for c in cases} and all(len(v) == 3 for v in tab.values())
    s = tb.summary(tab, {c["id"]: "tune" for c in cases})
    assert s["k"] == 3 and s["n"] == 6 and s["ci"][0] <= s["score"] <= s["ci"][1]
    assert s["mde_pp"] > 0 and math.isclose(s["mde_k1_pp"], s["mde_pp"] * math.sqrt(3), rel_tol=1e-3)
    assert "aa" in s and "score" in tb.line(s) and "MDE" in tb.line(s)


def test_a_steady_model_has_no_noise_and_one_run_says_nothing_about_noise():
    tab = {"a": [True, True, True], "b": [False, False, False]}
    assert tb.mde(tab) == 0 and tb.summary(tab)["flaky"] == 0
    assert tb.mde({"a": [True]}) == 0                         # K=1: the within-case variance is unknown
    one = {"a": [True, False], "b": [True, True]}             # a: variance 0.5 (unbiased), b: 0
    assert math.isclose(tb.mde(one), 100 * (tb.Z_ALPHA + tb.Z_POWER) * math.sqrt(2 * 0.5 / 2 / 4))


def test_paired_finds_a_real_gain_and_not_a_tie():
    old = {f"c{i}": [False, False, False] for i in range(40)}
    new = {c: ([True, True, True] if i < 15 else v) for i, (c, v) in enumerate(old.items())}
    p = tb.paired(old, new)
    assert p["significant"] and p["diff_pp"] == 37.5 and p["mcnemar"] == {"b": 0, "c": 15, "p": p["mcnemar"]["p"]}
    assert p["mcnemar"]["p"] < 0.001 and p["p"] < 0.01
    tie = tb.paired(old, {c: list(v) for c, v in old.items()})
    assert not tie["significant"] and tie["diff_pp"] == 0 and tie["p"] == 1.0
    mixed = {c: ([True] * 3 if i < 3 else [False] * 3) for i, c in enumerate(old)}
    back = {c: ([True] * 3 if 3 <= i < 5 else [False] * 3) for i, c in enumerate(old)}
    assert not tb.paired(mixed, back)["significant"]


def test_cases_add_the_frozen_extra_sets_once_and_never_an_excluded_repo(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [case("a"), case("b")]}))
    extra = tmp_path / "cases-extra"
    extra.mkdir()
    (extra / "o__rb.json").write_text(json.dumps({"cases": [case("b"), case("rb1", repo="o/rb"),
                                                            case("s1", repo="Metallic-Club/studio")]}))
    (extra / "broken.json").write_text("{")
    assert [c["id"] for c in st.cases(path)] == ["a", "b", "rb1"]
    with pytest.raises(ValueError):
        tb.freeze_extra("Metallic-Club/studio", "main", tmp_path)


def test_freeze_extra_stamps_commit_times(tmp_path, monkeypatch):
    got = [{**case("x"), "commit": "a" * 40}]
    monkeypatch.setattr(st, "history", lambda repo, base, clone: got)
    monkeypatch.setattr(st, "git", lambda clone, *a: type("R", (), {"stdout": f"{'a' * 40} 1790000000\n"})())
    tb.freeze_extra("o/rb", "main", tmp_path, tmp_path / "out")
    saved = json.loads((tmp_path / "out" / "o__rb.json").read_text(encoding="utf-8"))
    assert saved["cases"][0]["at"] == 1790000000 and saved["repo"] == "o/rb"


def test_the_night_with_k_runs_reports_the_bench_needs_a_paired_gain_and_runs_the_canaries(tmp_path):
    cases = [case("t1"), case("t2"), case("h1", split="hold")]

    def model(prompt):                                   # right only with a lesson in the prompt
        return RIGHT if "Lessons from your own past work" in prompt else WRONG
    rep = N.run(model, cases, st.Cache(None), store_path=tmp_path / "lessons.jsonl", switch=tmp_path / "on.json",
                reports=tmp_path / "reports", cand_dir=tmp_path / "cand", log=None, nightly=tmp_path / "n.jsonl",
                k=2, canaries=True)
    assert rep["bench"]["k"] == 2 and rep["bench"]["n"] == 3 and rep["bench"]["hold"]["n"] == 1
    v = rep["experience"]["verdict"]
    assert v["paired"]["n"] == 3 and v["paired"]["diff_pp"] == 100.0
    assert v["paired"]["significant"] and v["keep"] is True and rep["on"] == ["resolve"]   # every case gained
    line = json.loads((tmp_path / "n.jsonl").read_text())
    assert line["bench"]["k"] == 2 and line["canaries"]["gate"]["escapes"] == []
    assert rep["canaries"]["gate"]["total"] == len(C.synthetic())


def test_the_night_with_one_run_is_the_old_gate(tmp_path):
    cases = [case("t1"), case("t2"), case("h1", split="hold")]
    rep = N.run(lambda p: RIGHT if "Lessons from your own past work" in p else WRONG, cases, st.Cache(None),
                store_path=tmp_path / "lessons.jsonl", switch=tmp_path / "on.json", reports=tmp_path / "r",
                cand_dir=tmp_path / "cand", log=None, nightly=None)
    assert rep["on"] == ["resolve"] and "paired" not in rep["experience"]["verdict"] and "canaries" not in rep
    assert rep["bench"]["k"] == 1
