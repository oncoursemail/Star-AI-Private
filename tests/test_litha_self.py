"""Litha knows herself: the self-map (litha.self_map), the planner over her failures (litha.self_plan) and the health
check that repairs only mechanical damage (litha.self_check). Every test uses a fake ~/.star in tmp_path."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from litha import self_check, self_map, self_plan

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "star-home"
    for d in ("pr-fixer", "pr-merger", "litha"):
        (home / d).mkdir(parents=True)
    for mod in (self_map, self_plan, self_check):
        monkeypatch.setattr(mod, "HOME", home)
    monkeypatch.delenv("LITHA_SELF_NOTE", raising=False)
    return home


def jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def stamp(t: float) -> str:
    return time.strftime("%a %m/%d/%Y %H:%M:%S.00", time.localtime(t))


def run_log(home: Path, ends_ago: float = 300, body: str | None = None, open_start_ago: float | None = None,
            rc: int = 0) -> None:
    body = body if body is not None else ("merged 0\nmain: HOLD star/next abc (PR #1): no receipt\n"
                                          "Metallic-Club/studio: merged 0\n")
    t = NOW - ends_ago
    text = f"{stamp(t - 120)} start \n{body}{stamp(t)} end rc={rc} \n"
    if open_start_ago is not None:
        text += f"{stamp(NOW - open_start_ago)} start \n"
    (home / "pr-merger" / "run.log").write_text(text, encoding="utf-8")


def healthy(home: Path) -> None:
    run_log(home)
    for rel in ("pr-merger/decisions.jsonl", "litha/bench.jsonl"):
        (home / rel).write_text('{"ts": 1}\n', encoding="utf-8")
        os.utime(home / rel, (NOW - 60, NOW - 60))
    (home / "pr-fixer" / "tried.json").write_text(json.dumps({"1": "a"}), encoding="utf-8")


def old(path: Path, seconds: float) -> None:
    os.utime(path, (NOW - seconds, NOW - seconds))


# ---------------------------------------------------------------- planner


@pytest.mark.parametrize("row,bucket", [
    ({"result": "rerun", "why": "failed logs expired; reran 0 run(s)"}, "rerun-restarted-nothing"),
    ({"result": "rerun", "why": "failed logs expired; reran 3 run(s)"}, "logs-expired"),
    ({"result": "failed", "why": "a.rs: no usable answer for conflict 2 (last check: Your text does not open and "
                                 "close {}, () and [] the way both sides do"}, "conflict-brackets"),
    ({"result": "failed", "why": "conflicts she does not resolve alone: ['.github/workflows/ci.yml']"},
     "conflict-needs-person"),
    ({"result": "failed", "why": "ARCHITECTURE.md: conflict 1 is too big for her 4096-token window (~4551 tokens)"},
     "conflict-too-big"),
    ({"result": "failed", "why": "after resolving, cargo tests fail: x"}, "merged-tests-fail"),
    ({"result": "failed", "why": ""}, "no-reason-logged"),
    ({"result": "failed", "why": "The new files contain __file__ references"}, "python-not-passing"),
    ({"result": "failed", "repo": "Metallic-Club/studio", "why": "something else"}, "rust-not-passing"),
    ({"result": "flaky-rerun", "why": "reran 1 failed run(s) once for this head"}, "flaky"),
    ({"result": "error", "why": "boom"}, "exception"),
    ({"result": "fixed", "why": "merged main and resolved a.rs"}, "fixed"),
])
def test_classify_puts_each_logged_reason_in_its_bucket(row, bucket):
    assert self_plan.classify(row) == bucket
    assert bucket == "fixed" or bucket in self_plan.INFO


def test_plan_ranks_by_recent_count_times_fixability_and_writes_under_star_home(fake_home):
    rows = [{"ts": NOW - 3600, "pr": 700, "result": "rerun", "why": "failed logs expired; reran 0 run(s)"}] * 6
    rows += [{"ts": NOW - 3600, "repo": "Metallic-Club/studio", "pr": n, "result": "failed",
              "why": "conflicts she does not resolve alone: ['.github/x']"} for n in range(10, 20)]
    rows += [{"ts": NOW - 7200, "repo": "Metallic-Club/studio", "pr": 255, "result": "failed",
              "why": "x.rs: no usable answer for conflict 2 (last check: Your text does not open and close {}"}] * 3
    rows += [{"ts": NOW - 30 * 86400, "pr": 1, "result": "failed", "why": ""}]          # outside the window
    jsonl(fake_home / "pr-fixer" / "fixes.jsonl", rows)
    p = self_plan.plan(fake_home, now=NOW)
    order = [e["bucket"] for e in p["next_steps"]]
    # 6 x 0.9 > 3 x 0.6 > 10 x 0.1: a person's call ranks last even with the most rows
    assert order == ["rerun-restarted-nothing", "conflict-brackets", "conflict-needs-person"]
    top = p["next_steps"][0]
    assert top["prs"] == ["#700"] and top["count"] == 6 and top["lane"] == "ci-rerun" and top["cause"]
    assert p["next_steps"][1]["prs"] == ["studio#255"]
    assert p["lanes"]["resolve"]["refused"] == 10 and p["lanes"]["resolve"]["failed"] == 3
    path = self_plan.write(p, fake_home)
    assert path == fake_home / "litha" / "next_steps.json" and ROOT not in path.parents
    assert self_plan.load(fake_home)["next_steps"][0]["bucket"] == "rerun-restarted-nothing"


def test_a_bucket_whose_lane_kept_running_without_it_is_marked_quiet(fake_home):
    rows = [{"ts": NOW - 9000, "pr": 700, "result": "rerun", "why": "failed logs expired; reran 0 run(s)"}] * 4
    rows += [{"ts": NOW - 100 * i, "pr": 800 + i, "result": "flaky-rerun", "why": "reran 1 failed run(s) once"}
             for i in range(1, 4)]
    jsonl(fake_home / "pr-fixer" / "fixes.jsonl", rows)
    e = {x["bucket"]: x for x in self_plan.plan(fake_home, now=NOW)["next_steps"]}["rerun-restarted-nothing"]
    assert e["quiet"] and e["later_rows_in_lane"] == 3
    assert e["score"] == pytest.approx(e["weighted"] * 0.9 * self_plan.QUIET_FACTOR, abs=0.02)


def test_merger_failures_count_once_per_pr_head(fake_home):
    hold = {"ts": NOW - 60, "pr": 5, "head": "h1", "action": "hold", "reasons": ["error: gh pr diff: TLS timeout"]}
    claim = {"ts": NOW - 60, "pr": 6, "head": "h2", "action": "merge", "reasons": [],
             "review": {"summary": "ok", "risks": [{"severity": "refuted", "refuted": "the file compiles"},
                                                   {"severity": "high", "why": "x"}]}}
    jsonl(fake_home / "pr-merger" / "decisions.jsonl", [hold] * 5 + [claim] * 3 + [dict(hold, head="h3")])
    p = self_plan.plan(fake_home, now=NOW)
    by = {e["bucket"]: e for e in p["next_steps"]}
    assert by["merger-gh-error"]["count"] == 2 and by["merger-gh-error"]["prs"] == ["#5"]
    assert by["review-false-claims"]["count"] == 1
    assert "1 of 2 high risks" in by["review-false-claims"]["advice"]
    assert p["claims"] == {"high": 1, "refuted": 1, "unproven": 0, "heads": 1}


# ---------------------------------------------------------------- self-map


def test_real_tree_map_lists_entry_points_flags_and_gates(fake_home):
    m = self_map.code_map(ROOT, fake_home, use_cache=False)
    fixer = m["modules"]["pr_fixer"]
    assert {"--pr", "--workers", "--dry", "--others"} <= set(fixer["flags"])
    assert fixer["limits"]["ROUNDS"] >= 1 and "NO_TOUCH" in fixer["patterns"]
    assert "~/.star/pr-fixer/tried.json" in fixer["state"]
    assert any("tests, CI and locks" in r for r in fixer["refusals"]["apply_edits"])
    assert any("draft" in r for r in m["modules"]["pr_merger"]["refusals"]["list_gates"])
    steps = {s["script"]: s["steps"] for s in m["schedule"]}
    assert steps["pr_merger_run.cmd"][0].startswith("litha.self_update")
    assert steps["pr_merger_run.cmd"][1].startswith("litha.self_check")
    assert "litha.pr_fixer" in steps["pr_merger_run.cmd"]


def test_tree_hash_ignores_line_endings_and_follows_content(tmp_path):
    for eol in ("\n", "\r\n"):
        root = tmp_path / ("crlf" if eol == "\r\n" else "lf")
        (root / "litha").mkdir(parents=True)
        (root / "litha" / "a.py").write_bytes(f'"""doc"""{eol}X = 1{eol}'.encode())
    assert self_map.tree_hash(tmp_path / "lf") == self_map.tree_hash(tmp_path / "crlf")
    (tmp_path / "lf" / "litha" / "a.py").write_text('"""doc"""\nX = 2\n', encoding="utf-8")
    assert self_map.tree_hash(tmp_path / "lf") != self_map.tree_hash(tmp_path / "crlf")


def test_code_map_is_cached_per_tree_hash(tmp_path, fake_home, monkeypatch):
    root = tmp_path / "tree"
    (root / "litha").mkdir(parents=True)
    (root / "litha" / "tool.py").write_text(
        '"""Tool.\n\n    python -m litha.tool --go\n"""\nimport argparse\nfrom pathlib import Path\n'
        'LIMIT = 3\nSTATE = Path.home() / ".star" / "tool" / "s.json"\n\n'
        'def step(x):\n    why = []\n    if x:\n        why.append(f"refused {x} here")\n'
        '    return {"result": "failed", "why": "no answer"}\n\n'
        'def main():\n    ap = argparse.ArgumentParser()\n    ap.add_argument("--go", action="store_true")\n',
        encoding="utf-8")
    first = self_map.code_map(root, fake_home)
    tool = first["modules"]["tool"]
    assert tool["flags"] == ["--go"] and tool["limits"] == {"LIMIT": 3}
    assert tool["state"] == ["~/.star/tool/s.json"] and tool["usage"] == ["python -m litha.tool --go"]
    assert sorted(tool["refusals"]["step"]) == ["no answer", "refused {} here"]
    assert (fake_home / "litha" / "self_map" / f"{first['tree']}.json").exists()
    monkeypatch.setattr(self_map, "scan_module", lambda p: pytest.fail("the cache was not used"))
    assert self_map.code_map(root, fake_home) == first
    (root / "litha" / "tool.py").write_text('"""Changed."""\n', encoding="utf-8")
    with pytest.raises(pytest.fail.Exception):
        self_map.code_map(root, fake_home)                       # new tree hash: scanned again


def test_summary_fits_the_token_budget_even_with_much_to_say(fake_home):
    m = self_map.build(ROOT, fake_home)
    m["lanes"] = {f"lane-{i}": {"n": 9, "fixed": 1, "failed": 8, "refused": 0, "rerun": 0, "noop": 0, "error": 0,
                                "why": {f"bucket-{j}-" + "x" * 40: 3 for j in range(4)}} for i in range(60)}
    text = self_map.summary(m)
    assert self_map.tokens(text) <= self_map.SUMMARY_TOKENS
    assert text.startswith("LITHA SELF-MAP") and "Schedule:" in text
    assert self_map.tokens(self_map.summary(m, budget=300)) <= 300


def test_build_carries_measured_rates_from_her_logs(fake_home):
    jsonl(fake_home / "pr-fixer" / "fixes.jsonl", [
        {"ts": time.time() - 60, "repo": "Metallic-Club/studio", "pr": 1, "result": "fixed", "kind": "merge",
         "why": "merged main and resolved a.rs"},
        {"ts": time.time() - 60, "repo": "Metallic-Club/studio", "pr": 2, "result": "failed",
         "why": "conflicts she does not resolve alone: ['.github/ci.yml']"}])
    jsonl(fake_home / "litha" / "bench.jsonl", [{"at": "2026-11-02T03:00", "n": 10, "solved": 7, "seconds": 9},
                                                 {"at": "2026-11-02T03:20", "mode": "hunt", "n": 6, "caught": 2}])
    m = self_map.build(ROOT, fake_home)
    assert m["lanes"]["resolve"]["fixed"] == 1 and m["lanes"]["resolve"]["refused"] == 1
    assert m["bench"]["fix"]["ok"] == 7 and m["bench"]["hunt"]["ok"] == 2
    text = self_map.summary(m)
    assert "resolve: 2 1/0/1/0/0/0" in text and "hunt 2/6" in text
    json_path, txt_path = self_map.write_outputs(m, fake_home)
    assert json_path.parent == fake_home / "litha" and txt_path.read_text(encoding="utf-8") == text


# ---------------------------------------------------------------- prompt note


def _steps(home: Path, lane: str = "resolve", advice: str = "Measured: you break brackets.") -> None:
    self_plan.write({"next_steps": [{"bucket": "b", "lane": lane, "advice": advice, "quiet": False}]}, home)


def test_note_is_off_by_default_and_the_prompt_is_unchanged(fake_home):
    _steps(fake_home)
    build = "PROMPT{}".format
    assert self_map.fitted("resolve", build, 100) == "PROMPT"


def test_note_goes_in_only_when_it_fits_the_window(fake_home, monkeypatch):
    _steps(fake_home)
    monkeypatch.setenv("LITHA_SELF_NOTE", "1")
    build = "PROMPT{}".format
    assert "you break brackets" in self_map.fitted("resolve", build, 100)
    assert self_map.fitted("resolve", build, self_map.WINDOW - 5) == "PROMPT"        # no room left: unchanged
    assert self_map.fitted("merge-review", build, 100) == "PROMPT"                    # nothing known for this lane
    big = ("P" * int(self_map.WINDOW * self_map.CHARS_PER_TOKEN)).__add__
    assert self_map.fitted("resolve", big, 0) == big("")


def test_fixer_prompt_is_byte_identical_with_the_note_off(fake_home, monkeypatch, tmp_path):
    from litha import pr_fixer
    _steps(fake_home, lane="fix-python")
    seen: list[str] = []
    monkeypatch.setattr(pr_fixer, "run_tests", lambda *a, **k: (True, ""))
    monkeypatch.setattr(pr_fixer, "_lessons", lambda: "")
    pr_fixer.repair(tmp_path, "t", [{"test": "tests/test_x.py::t", "section": "E"}], "FAILED tests/test_x.py::t",
                    ["tests/test_x.py"], "python", asker=lambda p: seen.append(p) or '{"why": "x", "edits": []}',
                    diff="diff --git a/star/x.py b/star/x.py\n+x\n")
    monkeypatch.setenv("LITHA_SELF_NOTE", "1")
    pr_fixer.repair(tmp_path, "t", [{"test": "tests/test_x.py::t", "section": "E"}], "FAILED tests/test_x.py::t",
                    ["tests/test_x.py"], "python", asker=lambda p: seen.append(p) or '{"why": "x", "edits": []}',
                    diff="diff --git a/star/x.py b/star/x.py\n+x\n")
    assert "you break brackets" not in seen[0] and "you break brackets" in seen[1]
    assert seen[1].replace("\nMeasured: you break brackets.\n", "") == seen[0]


# ---------------------------------------------------------------- health check


def test_healthy_state_is_ok_and_fast(fake_home):
    healthy(fake_home)
    t = time.time()
    r = self_check.check(fake_home, now=NOW, plan=False)
    assert time.time() - t < 2
    assert r["ok"], r["problems"]
    assert not r["repaired"]
    assert (fake_home / "pr-fixer" / "tried.json.good").read_text(encoding="utf-8") == '{"1": "a"}'


def test_stale_locks_are_removed_and_fresh_ones_kept(fake_home):
    healthy(fake_home)
    stale, fresh = fake_home / "pr-fixer" / "others.lock", fake_home / "pr-fixer" / "tried.lock"
    for f in (stale, fresh):
        f.touch()
    old(stale, 5 * 3600)
    old(fresh, 60)
    r = self_check.check(fake_home, now=NOW, repair=False, plan=False)
    assert stale.exists() and any("stale lock" in p for p in r["problems"])
    r = self_check.check(fake_home, now=NOW, plan=False)
    assert not stale.exists() and fresh.exists()
    assert r["ok"] and any("others.lock" in x for x in r["repaired"])


def test_corrupt_state_is_restored_from_its_good_copy(fake_home):
    healthy(fake_home)
    self_check.check(fake_home, now=NOW, plan=False)                      # keeps tried.json.good
    tried = fake_home / "pr-fixer" / "tried.json"
    tried.write_text('{"1": "a", "2": ', encoding="utf-8")                  # cut off mid-write
    r = self_check.check(fake_home, now=NOW, plan=False)
    assert json.loads(tried.read_text(encoding="utf-8")) == {"1": "a"}
    assert r["ok"] and "restored from tried.json.good" in r["repaired"][0]
    kept = list(tried.parent.glob("tried.json.corrupt-*"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == '{"1": "a", "2": '
    assert not (tried.parent / "tried.lock").exists()


def test_corrupt_state_without_a_good_copy_uses_a_parseable_tmp_or_is_reported(fake_home):
    healthy(fake_home)
    hunted = fake_home / "pr-fixer" / "hunted.json"
    hunted.write_text("{not json", encoding="utf-8")
    r = self_check.check(fake_home, now=NOW, plan=False)
    assert any("hunted.json does not parse and no good copy" in p for p in r["problems"])
    assert hunted.read_text(encoding="utf-8") == "{not json"                  # nothing invented
    (hunted.parent / "hunted.json.123.456.tmp").write_text('{"9": {"head": "h"}}', encoding="utf-8")
    r = self_check.check(fake_home, now=NOW, plan=False)
    assert json.loads(hunted.read_text(encoding="utf-8")) == {"9": {"head": "h"}} and r["ok"]


def test_scheduled_run_problems_are_reported(fake_home):
    healthy(fake_home)
    run_log(fake_home, ends_ago=3 * 3600)
    assert any("last finished 3.0 h ago" in p for p in self_check.check(fake_home, now=NOW, plan=False)["problems"])
    run_log(fake_home, open_start_ago=2 * 3600)
    assert any("never ended" in p for p in self_check.check(fake_home, now=NOW, plan=False)["problems"])
    run_log(fake_home, open_start_ago=120)
    r = self_check.check(fake_home, now=NOW, plan=False)
    assert r["ok"] and any("in progress" in x for x in r["info"])
    run_log(fake_home, body='merged 0\nTraceback (most recent call last):\n  File "C:\\w\\litha\\pr_promote.py", '
                            'line 9, in main\nRuntimeError: x\nMetallic-Club/studio: merged 0\n', rc=1)
    problems = self_check.check(fake_home, now=NOW, plan=False)["problems"]
    assert any("rc=1" in p for p in problems)
    assert any("traceback in pr_promote" in p for p in problems)
    assert any("no result line for pr_promote" in p for p in problems)


def test_stale_logs_and_off_switches(fake_home):
    healthy(fake_home)
    old(fake_home / "litha" / "bench.jsonl", 30 * 3600)
    r = self_check.check(fake_home, now=NOW, plan=False)
    assert any("nightly bug bench" in p for p in r["problems"])
    (fake_home / "litha" / "OFF").touch()
    r = self_check.check(fake_home, now=NOW, plan=False)
    assert r["ok"] and any("off switch" in x for x in r["info"])


def test_stuck_prs_growing_tried_and_left_worktrees_are_reported_not_changed(fake_home, tmp_path):
    healthy(fake_home)
    jsonl(fake_home / "pr-fixer" / "fixes.jsonl",
          [{"ts": NOW - 600 * i, "repo": "Metallic-Club/studio", "pr": 255, "result": "failed",
            "why": "x.rs: no usable answer for conflict 2 (last check: does not open and close {}"} for i in range(5)]
          + [{"ts": NOW - 60, "pr": 9, "result": "fixed", "why": "ok"}] * 5)
    tried = fake_home / "pr-fixer" / "tried.json"
    tried.write_text(json.dumps({str(i): "x" * 40 for i in range(400)}), encoding="utf-8")
    work = tmp_path / "worktrees"
    (work / "litha-fix-12").mkdir(parents=True)
    (work / "someone-else").mkdir()
    old(work / "litha-fix-12", 10 * 3600)
    before = tried.read_bytes()
    r = self_check.check(fake_home, now=NOW, work=work, plan=False)
    text = "\n".join(r["problems"])
    assert "studio#255 logged failed/conflict-brackets 5 times" in text and "#9 " not in text
    assert "tried.json holds 400 PRs" in text
    assert "litha-fix-12" in text and "someone-else" not in text
    assert tried.read_bytes() == before and (work / "litha-fix-12").exists()
    r = self_check.check(fake_home, now=NOW + 7 * 3600, work=work, plan=False)            # the loop stopped
    assert not any("studio#255" in p for p in r["problems"]) and any("(stopped)" in x for x in r["info"])


def test_plan_is_refreshed_when_fixes_change(fake_home):
    healthy(fake_home)
    jsonl(fake_home / "pr-fixer" / "fixes.jsonl", [{"ts": NOW - 60, "pr": 1, "result": "failed", "why": ""}])
    r = self_check.check(fake_home, now=NOW)
    assert "next_steps.json refreshed" in r["info"]
    assert self_plan.load(fake_home)["next_steps"][0]["bucket"] == "no-reason-logged"
    r = self_check.check(fake_home, now=NOW + 60)
    assert "next_steps.json refreshed" not in r["info"]                    # same fixes.jsonl: no work


def test_main_writes_health_in_the_given_home_and_never_fails_the_run(fake_home, capsys):
    run_log(fake_home, ends_ago=99 * 3600)
    assert self_check.main(["--home", str(fake_home), "--quiet"]) == 0
    assert self_check.main(["--home", str(fake_home), "--quiet", "--strict"]) == 1
    health = json.loads((fake_home / "litha" / "health.json").read_text(encoding="utf-8"))
    assert not health["ok"] and health["problems"]
    assert capsys.readouterr().out.startswith("self_check ")


def test_the_scheduled_run_checks_herself_before_the_fixer():
    cmd = (ROOT / "litha" / "pr_merger_run.cmd").read_text(encoding="utf-8")
    assert cmd.index("-m litha.self_check") < cmd.index("-m litha.pr_fixer")
    assert "litha.self_check --quiet" in cmd
