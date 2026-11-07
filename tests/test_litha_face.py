"""Litha's face: the state readers, the digest for her model, the owner's controls, access rules, and the pause check
in pr_merger. Everything runs on a temp ~/.star; nothing calls gh, her model or Claude."""
from __future__ import annotations

import json
import math
import time

import pytest

from litha import pr_merger
from litha.face import controls, data, server


def _jl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    now = time.time()
    _jl(tmp_path / "pr-merger" / "decisions.jsonl", [
        {"ts": now - 600, "pr": 7, "action": "hold", "reasons": ["draft"], "head": "a" * 40, "title": "old", "review": None},
        {"ts": now - 60, "pr": 7, "action": "merge", "merged": True, "reasons": [], "head": "b" * 40, "title": "seven",
         "review": {"verdict": "merge", "said": ["merge", "merge", "hold"], "summary": "fine",
                    "risks": [{"file": "a.py", "line": 3, "severity": "low", "why": "w"}]}},
        {"ts": now - 30, "repo": "oncoursemail/Metallic-RB", "pr": 42, "action": "ready", "reasons": [], "title": "rb"},
        {"ts": now - 30 * 86400, "pr": 1, "action": "hold", "reasons": ["too old"]},
        {"ts": now - 20, "replay_hunt": True, "pr": 860, "found": []},
    ])
    log = time.strftime("Mon %m/%d/%Y %H:%M:%S.00", time.localtime(now - 120))
    end = time.strftime("Mon %m/%d/%Y %H:%M:%S.00", time.localtime(now - 60))
    (tmp_path / "pr-merger" / "run.log").write_text(
        f"{log} start \n{log} step pr_fixer (previous rc=0) \nok\n{log} step pr_merger (previous rc=1) \n"
        f"RuntimeError: gh pr list: HTTP 502\n{end} end rc=0 \n", encoding="utf-8")
    _jl(tmp_path / "pr-fixer" / "fixes.jsonl", [
        {"ts": now - 100, "pr": 921, "result": "failed", "why": "types", "tests": ["t"], "seconds": 3},
        {"ts": now - 50, "repo": "Metallic-Club/studio", "pr": 5, "result": "fixed", "why": "ok",
         "fix_pr": "https://example.invalid/o/r/pull/77", "seconds": 1}])
    _jl(tmp_path / "litha-claude" / "spend.jsonl", [
        {"ts": now - 90000, "day": "2000-01-01", "usd": 1.5, "what": "old"},
        {"ts": now, "day": time.strftime("%Y-%m-%d"), "usd": 0.25, "what": "review x"}])
    (tmp_path / "litha-autonomy").mkdir()
    (tmp_path / "litha-autonomy" / "queue.json").write_text(json.dumps(
        {"built": "2026-11-03T00:26:13+00:00", "tasks": [{"key": "retry:x#832", "kind": "retry", "number": 832,
                                                          "score": 29, "why": "failed"}], "skipped": [], "notes": []}))
    _jl(tmp_path / "litha-selftune" / "runs.jsonl", [{"ts": now, "prompt": "p1", "points": 175, "total": 375}])
    _jl(tmp_path / "litha" / "bench-runs.jsonl", [
        {"at": "2026-11-02T11:57:56+00:00", "standard": {"solved": 16, "n": 32}},
        {"at": "2026-11-02T18:43:01+00:00", "suite": "real", "mode": "blind", "solved": 3, "n": 12}, {"junk": 1}])
    return tmp_path


def test_tail_bytes_starts_at_a_whole_line(tmp_path):
    p = tmp_path / "x.log"
    p.write_bytes(b"first line\nsecond\nthird\n")
    assert data.tail_bytes(p, 12) == b"third\n"            # "second\nthird\n" is 13 bytes: the cut line is dropped
    assert data.tail_bytes(p, 1000) == b"first line\nsecond\nthird\n"
    assert data.tail_bytes(tmp_path / "missing", 10) == b""


def test_cached_parses_again_only_when_the_file_changes(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    calls = []

    def parse(path):
        calls.append(1)
        return data.jsonl(path.read_bytes())

    assert data.cached(p, parse) == [{"a": 1}]
    assert data.cached(p, parse) == [{"a": 1}] and len(calls) == 1
    p.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    assert len(data.cached(p, parse)) == 2 and len(calls) == 2


def test_parse_loop_reads_start_steps_errors_and_end():
    lines = ["Mon 11/02/2026 21:21:02.14 start ", "Mon 11/02/2026 21:21:30.00 step pr_fixer --others (previous rc=0) ",
             "Traceback (most recent call last):", "RuntimeError: gh pr diff: HTTP 502",
             "Mon 11/02/2026 21:22:00.00 step forge_sync (previous rc=1) "]
    loop = data.parse_loop(lines)
    assert loop["running"] and loop["step"] == "forge_sync" and loop["end_rc"] is None
    assert loop["bad_steps"] == ["pr_fixer --others rc=1"]
    assert len(loop["errors"]) == 2
    done = data.parse_loop(lines + ["Mon 11/02/2026 21:22:27.07 end rc=0 "])
    assert not done["running"] and done["end_rc"] == 0 and done["seconds"] == 85 and done["step"] is None
    again = data.parse_loop(lines + ["Mon 11/02/2026 21:22:27.07 end rc=0 ", "Mon 11/02/2026 21:31:01.00 start "])
    assert again["running"] and again["errors"] == [] and again["bad_steps"] == []


def test_latest_prs_keeps_her_newest_decision_per_pr(root):
    p = data.prs(root)
    star = next(r for r in p["repos"] if r["repo"] == data.HOME_REPO)
    assert [x["pr"] for x in star["prs"]] == [7]                       # PR 1 is older than a week
    seven = star["prs"][0]
    assert seven["merged"] and seven["said"] == {"merge": 2, "hold": 1} and seven["head"] == "b" * 8
    assert star["counts"] == {"merged": 1} and star["mode"] == "merge"
    rb = next(r for r in p["repos"] if r["repo"] == "oncoursemail/Metallic-RB")
    assert rb["prs"][0]["action"] == "ready" and rb["mode"] == "review"


def test_pages_never_show_keys_or_private_addresses():
    row = {"ts": 1, "pr": 2, "action": "hold", "title": "t", "reasons": [
        "ssh to 203.0.113.9 failed", "key sk-ant-api03-abcdef ghp_" + "x" * 30, "Bearer abc.def"]}
    text = json.dumps(data.pr_view(row))
    for bad in ("203.0.113.9", "sk-ant", "ghp_", "abc.def"):
        assert bad not in text


def test_fixes_spend_autonomy_selftune(root):
    f = data.fixes(root)
    assert f["week"] == {"failed": 1, "fixed": 1} and f["recent"][0]["fix_pr"] == 77
    assert f["recent"][0]["repo"] == "Metallic-Club/studio" and f["recent"][1]["repo"] == data.HOME_REPO
    sp = data.spend(root)
    assert sp["total"] == 1.75 and sp["today"] == 0.25 and sp["caps"] == data.CAPS and sp["calls"] == 2
    a = data.autonomy(root)
    assert not a["apply"] and a["tasks"][0]["number"] == 832
    st = data.selftune(root)
    assert st["runs"][0]["points"] == 175
    assert [b["suite"] for b in st["bench"]] == ["standard", "real/blind"]


def test_state_and_digest_on_real_shapes(root):
    s = data.state(root)
    assert s["now"]["last_end"] and s["now"]["bad_steps"] == ["pr_fixer rc=1"]
    assert any("RuntimeError" in e for e in s["now"]["errors"])
    d = data.digest(s)
    assert "#7 merged" in d and "$0.25 today" in d and "Self-tune last: 175/375" in d and "Fix attempts today" in d
    assert len(data.digest(s, limit=200)) <= 200


def test_state_with_no_files_at_all(tmp_path):
    s = data.state(tmp_path)
    assert s["now"]["last_start"] is None and s["spend"]["total"] == 0 and s["autonomy"]["tasks"] == []
    assert isinstance(data.digest(s), str) and data.log_tail(tmp_path) == []


def test_pause_control_writes_and_removes_her_pause_file(root):
    controls.apply("pause", True, root)
    assert (root / "pr-merger" / "PAUSED").exists() and data.control_state(root)["paused"]
    controls.apply("pause", False, root)
    assert not (root / "pr-merger" / "PAUSED").exists()
    log = data.jsonl((root / "litha-face" / "controls.jsonl").read_bytes())
    assert [(r["control"], r["value"]) for r in log] == [("pause", True), ("pause", False)]


def test_apply_control_and_bool_only(root):
    controls.apply("apply", True, root)
    assert (root / "litha-autonomy" / "APPLY").exists() and data.autonomy(root)["apply"]
    controls.apply("apply", False, root)
    assert not (root / "litha-autonomy" / "APPLY").exists()
    with pytest.raises(ValueError):
        controls.apply("apply", "false", root)                      # a string is not a switch position
    with pytest.raises(ValueError):
        controls.apply("merge", True, root)                         # no control merges, pushes or posts


def test_day_cap_keeps_total_and_refuses_bad_values(root):
    (root / "litha-claude" / "cap.json").write_text('{"total": 50}', encoding="utf-8")
    assert controls.apply("day_cap", 12.5, root)["caps"] == {"total": 50, "day": 12.5}
    for bad in (-1, 101, math.nan, math.inf, "abc", None):
        with pytest.raises(ValueError):
            controls.apply("day_cap", bad, root)
    assert json.loads((root / "litha-claude" / "cap.json").read_text(encoding="utf-8")) == {"total": 50, "day": 12.5}
    log = data.jsonl((root / "litha-face" / "controls.jsonl").read_bytes())
    assert [r["ok"] for r in log] == [True] + [False] * 6


def test_who_may_use_the_face():
    tok = "t" * 30
    assert server.allowed("127.0.0.1", "127.0.0.1:8770", "", "", tok, lan=False)
    assert server.allowed("127.0.0.1", "localhost:8770", "", "", tok, lan=False)
    assert not server.allowed("127.0.0.1", "evil.example:8770", "", "", tok, lan=False)   # DNS rebinding
    assert not server.allowed("198.51.100.7", "pc:8770", f"litha_face={tok}", "", tok, lan=False)
    assert server.allowed("198.51.100.7", "pc:8770", f"litha_face={tok}", "", tok, lan=True)
    assert server.allowed("198.51.100.7", "pc:8770", "", tok, tok, lan=True)
    assert not server.allowed("198.51.100.7", "pc:8770", "litha_face=wrong", "", tok, lan=True)
    assert not server.allowed("198.51.100.7", "pc:8770", "", "", tok, lan=True)


def test_token_is_made_once_and_kept(tmp_path):
    p = tmp_path / "litha-face.token"
    t = server.token(p)
    assert len(t) >= 20 and server.token(p) == t and p.read_text(encoding="utf-8").strip() == t


def test_pr_merger_does_nothing_while_paused(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pr_merger, "PAUSED", tmp_path / "PAUSED")
    monkeypatch.setattr(pr_merger, "open_prs", lambda n=None: (_ for _ in ()).throw(AssertionError("looked at PRs")))
    monkeypatch.setattr(pr_merger, "others", lambda apply: (_ for _ in ()).throw(AssertionError("other repos")))
    monkeypatch.setattr(pr_merger, "replay", lambda n: {"replayed": n})
    (tmp_path / "PAUSED").write_text("{}", encoding="utf-8")
    assert pr_merger.main(["--apply"]) == 0
    assert pr_merger.main(["--apply", "--others"]) == 0
    assert "paused by the owner" in capsys.readouterr().out
    assert pr_merger.main(["--replay", "3"]) == 0                   # a replay only reads closed PRs: still allowed
    assert '"replayed": 3' in capsys.readouterr().out
    (tmp_path / "PAUSED").unlink()
    with pytest.raises(AssertionError, match="looked at PRs"):
        pr_merger.main(["--apply"])                                 # resumed: she looks at PRs again
