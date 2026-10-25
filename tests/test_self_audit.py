"""Weekly self-audit (star/self_audit.py, issue #555): measured from stored data, written where the app reads it."""
import json
import sqlite3
import time

import pytest

from star import curiosity, self_audit

NOW = 1_790_000_000.0
DAY = 86400.0


def iso(days_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days_ago * DAY))


def result_file(folder, name, days_ago, tasks, suite="golden.json"):
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(json.dumps({"schema": 1, "suite": {"file": suite}, "run": {"started_at": iso(days_ago)},
                                           "tasks": tasks}), encoding="utf-8")


def passed():
    return {"status": "pass", "reasons": [], "checks": []}


def failed(reason="luau_check[1]: line 3: Unknown global 'Frob'"):
    return {"status": "fail", "reasons": [reason], "checks": [{"id": "luau_check[1]", "ok": False, "detail": reason}]}


@pytest.fixture
def sources(tmp_path):
    results = tmp_path / "results"
    # skill "REM" (remote security): last week 4 of 4, this week 1 of 4 -> down; skill "UIL": 6 of 6; "ERR": errors only
    result_file(results, "prev.json", 10, {f"REM-{i}": passed() for i in range(4)} | {f"UIL-{i}": passed() for i in range(3)})
    result_file(results, "now.json", 2, {"REM-1": passed(), "REM-2": failed(), "REM-3": failed("answer: no luau block"),
                                         "REM-4": failed()} | {f"UIL-{i}": passed() for i in range(3, 6)}
                | {"ERR-1": {"status": "error", "reasons": ["timeout"]}})
    result_file(results, "secret.json", 1, {"HOLD-1": failed()}, suite="holdout-v1.json")      # never read
    mistakes = tmp_path / "mistakes.jsonl"
    mistakes.write_text("".join(json.dumps(r) + "\n" for r in (
        {"ts": iso(1), "rung": "luau_check", "signature": "Unknown global 'Frob'", "verified": False},
        {"ts": iso(1), "rung": "luau_check", "signature": "Unknown global 'Frob'", "verified": False},
        {"ts": iso(2), "rung": "unit_test", "signature": "expected 3", "verified": True},
        {"ts": iso(30), "rung": "luau_check", "signature": "too old", "verified": False})), encoding="utf-8")
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    (receipts / "a.json").write_text(json.dumps({"kind": "rollback", "change": {"verify_ladder": "on"}, "at": iso(1) .replace("Z", "+00:00"),
                                                 "problems": ["sealed pass rate fell"]}), encoding="utf-8")
    (receipts / "b.json").write_text(json.dumps({"kind": "refusal", "change": "x", "at": iso(20), "reasons": ["old"]}), encoding="utf-8")
    queue = tmp_path / "curiosity.jsonl"
    key = curiosity.make_key("weak_retrieval", "tween chains")
    queue.write_text("".join(json.dumps(r) + chr(10) for r in (
        {"ts": iso(1), "kind": "weak_retrieval", "key": key, "topic": "tween chains", "detail": ""},
        {"ts": iso(0.5), "key": key, "resolved": "taught", "by": "conductor-1"},
        {"ts": iso(1), "kind": "api_change", "key": curiosity.make_key("api_change", "new Roblox class Zed"),
         "topic": "new Roblox class Zed", "detail": ""})), encoding="utf-8")
    lessons = tmp_path / "knowledge.sqlite3"
    db = sqlite3.connect(lessons)
    db.execute("CREATE TABLE learned_items (id INTEGER, state TEXT, live_at TEXT)")
    db.executemany("INSERT INTO learned_items VALUES (?,?,?)", [(1, "live", iso(1)), (2, "undone", iso(30)), (3, "kept", iso(3))])
    db.commit()
    db.close()
    dump = tmp_path / "dump.json"
    dump.write_text(json.dumps({"StarSource": {"studioVersion": "0.9.0.1", "generated": iso(40)[:10]}}), encoding="utf-8")
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps({"generated": "2026-10-01", "added_members_total": 7, "newly_deprecated_total": 2,
                                   "added_classes_total": 1}), encoding="utf-8")
    return dict(results_dirs=[results], suites_dir=tmp_path / "suites", mistakes=mistakes, lessons_db=lessons,
                receipts_dir=receipts, curiosity_file=queue, dump_file=dump, changes_file=changes)


def test_report_has_per_skill_rates_trend_and_failure_classes(tmp_path, sources):
    report = self_audit.build(NOW, home=tmp_path, **sources)
    skills = {r["skill"]: r for r in report["evals"]["skills"]}
    assert (skills["rem"]["scored"], skills["rem"]["passed"]) == (8, 5)
    assert skills["rem"]["recent"] == {"scored": 4, "rate": 0.25} and skills["rem"]["previous"] == {"scored": 4, "rate": 1.0}
    assert skills["rem"]["trend"] == "down"
    assert skills["uil"]["rate"] == 1.0 and skills["uil"]["trend"] == "flat"
    assert "err" not in skills and "hold" not in skills                      # infrastructure errors and holdouts are left out
    assert report["evals"]["result_files"] == 2
    classes = {c["cause"]: c for c in report["evals"]["failure_classes"]}
    assert classes["invented API name"] == {"cause": "invented API name", "failed": 2, "this_week": 2}
    assert report["mistakes"]["this_week"] == 3 and report["mistakes"]["verified_fixes"] == 1
    assert report["mistakes"]["top"] == [{"signature": "Unknown global 'Frob'", "count": 2}]
    assert report["receipts"]["this_week"] == {"rollback": 1}
    assert report["lessons"] == {"went_live_this_week": 2, "by_state": {"kept": 1, "live": 1, "undone": 1}} or \
        report["lessons"]["went_live_this_week"] == 2
    seen = report["curiosity"]
    assert seen["recorded_this_week"] == {"weak_retrieval": 1, "api_change": 1} and seen["studied_this_week"] == 1
    assert seen["open"] == 1 and seen["top_open"] == [{"kind": "api_change", "topic": "new Roblox class Zed", "count": 1}]
    assert report["api_dump"]["age_days"] == 40 and report["api_dump"]["latest_changes"]["added_members"] == 7
    assert report["missing"] == []


def test_strengths_and_weaknesses_come_from_the_numbers(tmp_path, sources):
    report = self_audit.build(NOW, home=tmp_path, **sources)
    assert "uil: 100% of 6 scored tasks" in report["strengths"]
    assert "rem went down this week: 100% to 25%" in report["weaknesses"]
    assert "rem: 62% of 8 scored tasks" not in report["weaknesses"]               # 62% is neither strong nor weak
    assert any(w.startswith("most common failure class: invented API name") for w in report["weaknesses"])
    assert "1 automatic change(s) were rolled back this week" in report["weaknesses"]
    assert "the bundled Roblox API dump is 40 days old" in report["weaknesses"]
    assert "night school studied 1 curiosity item(s) this week" in report["strengths"]
    assert any("cleared 1 of 3 mistakes" in w for w in report["weaknesses"])
    text = self_audit.render(report)
    assert text.startswith("# STAR weekly self-audit (") and "## Strengths" in text and "## Weaknesses" in text


def test_missing_sources_are_named_not_invented(tmp_path):
    nothing = {k: tmp_path / "none" for k in ("suites_dir", "mistakes", "lessons_db", "receipts_dir", "curiosity_file",
                                              "dump_file", "changes_file")}
    report = self_audit.build(NOW, home=tmp_path, results_dirs=[tmp_path / "none"], **nothing)
    assert report["missing"] == ["api_dump", "curiosity", "evals", "lessons", "mistakes", "receipts"]
    assert report["strengths"] == [] and report["weaknesses"] == []
    assert "No data on this machine for" in self_audit.render(report)


def test_the_report_is_stored_for_the_app_and_runs_once_a_week(tmp_path, sources):
    assert self_audit.latest(tmp_path) is None and self_audit.due(tmp_path, NOW)
    first = self_audit.run(tmp_path, now=NOW, **sources)
    folder = tmp_path / "self_audit"
    assert (folder / "latest.json").is_file() and (folder / "latest.md").is_file()
    assert (folder / (first["generated"][:10].replace("-", "") + ".md")).is_file()
    assert self_audit.handle_action(tmp_path, "STAR", "selfAudit", {})["report"]["generated"] == first["generated"]
    assert self_audit.run(tmp_path, now=NOW + 3 * DAY, **sources) is None            # not due
    assert self_audit.run(tmp_path, now=NOW + 7 * DAY, **sources)["generated"] != first["generated"]
    assert self_audit.run(tmp_path, now=NOW + 7 * DAY + 5, force=True, **sources) is not None
    with pytest.raises(PermissionError):
        self_audit.handle_action(tmp_path, "STAR", "deleteEverything", {})


def test_old_weekly_copies_are_pruned(tmp_path, sources):
    for week in range(15):
        self_audit.write(self_audit.build(NOW + week * 7 * DAY, home=tmp_path, **sources), tmp_path)
    assert len(list((tmp_path / "self_audit").glob("2*.md"))) == 12


def test_the_host_starts_the_audit_in_the_background_only_when_due(tmp_path, sources):
    assert self_audit.run_if_due(tmp_path, **sources) is True
    deadline = time.time() + 20
    while self_audit.latest(tmp_path) is None and time.time() < deadline:
        time.sleep(0.05)
    assert self_audit.latest(tmp_path) is not None
    time.sleep(0.1)
    assert self_audit.run_if_due(tmp_path, **sources) is False                       # fresh: nothing to do


def test_the_app_allows_the_action_and_the_full_state_starts_the_weekly_audit(tmp_path, monkeypatch):
    import star.react_shell as shell
    from star.desktop_core import Settings
    assert "selfAudit" in shell.ALLOWED_ACTIONS

    class Runtime:
        def status(self):
            return "stopped"

        def router_running(self):
            return False
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(shell, "app_data", lambda: tmp_path)
    settings_file = tmp_path / "settings.json"
    Settings(model="qwen-test").save(settings_file)
    started = []
    monkeypatch.setattr(self_audit, "run_if_due", lambda home=None, **_: started.append(home) or True)
    shell._get_state(settings_file, Runtime())
    assert started == [tmp_path]
    shell._chat_state(settings_file)                       # chat navigation never starts it
    assert started == [tmp_path]
