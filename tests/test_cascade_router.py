"""star/cascade_router.py: offline quick-first cascade / routing simulator over eval result files."""
from __future__ import annotations

import json

import pytest

from star import cascade_router as cr


def _row(status, seconds, model, check=None):
    events = [{"event": "route_selected", "profile": "roblox", "model": model}]
    if check:
        events.append({"event": "luau_check_finished", "state": check, "blocks": 1})
    return {"status": status, "passed": status == "pass", "reasons": [], "checks": [], "seconds": seconds,
            "events": events}


def _result(tasks: dict, *, model="star-fast", started="2026-10-14T01:00:00+00:00", suite_file="golden-tasks-v2.json"):
    return {"schema": 1,
            "suite": {"file": suite_file, "sha256": "s" * 64, "identity_sha256": "i" * 64,
                      "tasks_total": len(tasks), "automated": len(tasks), "selected": sorted(tasks)},
            "run": {"model": model, "mode": "auto", "app_commit": "abc", "grader_sha256": "g" * 64,
                    "started_at": started},
            "complete": True, "tasks": tasks}


def _arms():
    # LUA: quick passes its Luau check and the golden tests on every task -> cascade keeps it, no loss.
    # NET: quick's check passes but the answer is wrong on NET-02 -> the cascade loses one pair there.
    # UI: quick's check fails -> the cascade escalates to the strong answer (same outcome, more time).
    strong = {"LUA-01": _row("pass", 100, "star-fast", "passed"), "LUA-02": _row("pass", 100, "star-fast", "passed"),
              "LUA-03": _row("fail", 100, "star-fast", "failed"),
              "NET-01": _row("pass", 100, "star-fast", "passed"), "NET-02": _row("pass", 100, "star-fast", "passed"),
              "NET-03": _row("pass", 100, "star-fast", "passed"),
              "UI-01": _row("pass", 100, "star-fast", "passed"), "UI-02": _row("fail", 100, "star-fast", "failed"),
              "UI-03": _row("pass", 100, "star-fast", "passed")}
    quick = {"LUA-01": _row("pass", 30, "star-quick", "passed"), "LUA-02": _row("pass", 30, "star-quick", "passed"),
             "LUA-03": _row("pass", 30, "star-quick", "passed"),
             "NET-01": _row("pass", 30, "star-quick", "passed"), "NET-02": _row("fail", 30, "star-quick", "passed"),
             "NET-03": _row("pass", 30, "star-quick", "passed"),
             "UI-01": _row("fail", 30, "star-quick", "failed"), "UI-02": _row("fail", 30, "star-quick", "failed"),
             "UI-03": _row("fail", 30, "star-quick", None)}
    return [_result(strong)], [_result(quick, model="star-quick")]


def test_category_of_prefers_suite_category_then_id_prefix():
    assert cr.category_of("LUA-01") == "LUA"
    assert cr.category_of("practice-animation-vfx-01-play-anim") == "practice-animation-vfx"
    assert cr.category_of("LUA-01", {"LUA-01": "luau-typing"}) == "luau-typing"


def test_runtime_accept_reads_the_apps_own_check_event():
    assert cr.runtime_accept(_row("fail", 1, "m", "passed")) is True
    assert cr.runtime_accept(_row("fail", 1, "m", "repaired")) is False
    assert cr.runtime_accept(_row("fail", 1, "m", "repaired"), accept=("passed", "repaired")) is True
    assert cr.runtime_accept(_row("pass", 1, "m", None)) is False       # no check ran: never accepted


def test_answered_by_takes_the_last_route_event():
    row = _row("pass", 1, "star-fast")
    row["events"].append({"event": "route_busy_quick", "model": "star-quick"})
    assert cr.answered_by(row) == "star-quick"
    assert cr.answered_by({"status": "pass"}) is None


def test_cascade_keeps_accepted_quick_answers_and_escalates_the_rest():
    strong, quick = _arms()
    pairs, notes = cr.build_pairs(strong, quick)
    assert notes == []
    row = cr.evaluate(pairs, "cascade")
    # Kept quick: 6 (LUA x3, NET x3); escalated: 3 (UI). Lost NET-02, won LUA-03.
    assert (row["quick_answers"], row["escalations"]) == (6, 3)
    assert (row["wins"], row["losses"]) == (1, 1)
    assert row["safe"] is False
    assert row["policy_seconds"] == 6 * 30 + 3 * (30 + 100)
    assert row["strong_seconds"] == 900
    assert row["time_saved_share"] == pytest.approx(1 - 570 / 900, abs=1e-3)
    strong_row = cr.evaluate(pairs, "strong")
    assert strong_row["losses"] == 0 and strong_row["safe"] is True and strong_row["time_saved_share"] == 0


def test_fitted_table_routes_only_loss_free_categories():
    strong, quick = _arms()
    pairs, _ = cr.build_pairs(strong, quick)
    table = cr.fit_table(pairs, min_tasks=3)
    assert table["kind"] == "star-cascade-table"
    assert table["routes"] == {"LUA": "quick", "NET": "strong", "UI": "strong"}
    row = cr.evaluate(pairs, table["routes"])
    assert row["losses"] == 0 and row["safe"] is True and row["wins"] == 1
    # Too few tasks per category: nothing is routed away from the strong model.
    assert set(cr.fit_table(pairs, min_tasks=4)["routes"].values()) == {"strong"}


def test_quick_arm_answered_by_the_strong_model_is_refused():
    strong, _ = _arms()
    rerouted = [_result({tid: _row("pass", 50, "star-fast", "passed") for tid in strong[0]["tasks"]},
                        model="star-quick")]
    with pytest.raises(ValueError, match="pin-model"):
        cr.build_pairs(strong, rerouted)
    pairs, notes = cr.build_pairs(strong, rerouted, allow_mixed=True)
    assert pairs and notes and notes[0].startswith("allowed:")


def test_different_suite_or_grader_is_refused():
    strong, quick = _arms()
    quick[0]["suite"]["sha256"] = "x" * 64
    with pytest.raises(ValueError, match="suite sha256 differs"):
        cr.build_pairs(strong, quick)
    strong, quick = _arms()
    quick[0]["run"]["grader_sha256"] = "x" * 64
    with pytest.raises(ValueError, match="grader_sha256 differs"):
        cr.build_pairs(strong, quick)


def test_errored_samples_are_not_counted_as_failures():
    strong, quick = _arms()
    quick[0]["tasks"]["LUA-01"] = {"status": "error", "passed": False, "reasons": ["x"], "checks": [], "seconds": 0,
                                   "error": "APIConnectionError"}
    pairs, _ = cr.build_pairs(strong, quick)
    row = cr.evaluate(pairs, "quick")
    assert "LUA-01" in row["incomplete"]
    assert row["decision"] == "INCOMPLETE"


def test_k_runs_are_paired_by_start_time():
    strong, quick = _arms()
    late = json.loads(json.dumps(strong[0]))
    late["run"]["started_at"] = "2026-10-14T05:00:00+00:00"
    for row in late["tasks"].values():
        row["status"], row["passed"] = "fail", False
    pairs, notes = cr.build_pairs([late, strong[0]], quick)       # given out of order
    assert pairs["LUA-01"][0].strong is True                      # the earlier strong run is sample 1
    assert notes and "first 1 of each" in notes[0]


def test_cli_writes_a_table_and_checks_a_given_one(tmp_path, capsys):
    strong, quick = _arms()
    s, q, t = tmp_path / "s.json", tmp_path / "q.json", tmp_path / "table.json"
    s.write_text(json.dumps(strong[0]), encoding="utf-8")
    q.write_text(json.dumps(quick[0]), encoding="utf-8")
    assert cr.main(["--strong", str(s), "--quick", str(q), "--write-table", str(t)]) == 0
    out = capsys.readouterr().out
    assert "cascade" in out and "NOT SAFE" in out and "fitted routes: LUA=quick" in out
    assert json.loads(t.read_text(encoding="utf-8"))["routes"]["LUA"] == "quick"
    assert cr.main(["--strong", str(s), "--quick", str(q), "--table", str(t), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["policies"]["table (given)"]["losses"] == 0


def test_cli_refuses_to_fit_on_the_holdout(tmp_path, capsys):
    strong, quick = _arms()
    for run in strong + quick:
        run["suite"]["file"] = "holdout-v1.json"
    s, q = tmp_path / "s.json", tmp_path / "q.json"
    s.write_text(json.dumps(strong[0]), encoding="utf-8")
    q.write_text(json.dumps(quick[0]), encoding="utf-8")
    assert cr.main(["--strong", str(s), "--quick", str(q)]) == 2
    assert "holdout" in capsys.readouterr().out
    table = tmp_path / "t.json"
    table.write_text(json.dumps({"kind": "star-cascade-table", "routes": {"LUA": "quick"}}), encoding="utf-8")
    assert cr.main(["--strong", str(s), "--quick", str(q), "--table", str(table)]) == 0
    out = capsys.readouterr().out
    assert "table (given)" in out and "fitted routes" not in out


def test_cli_reports_unusable_input(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert cr.main(["--strong", str(bad), "--quick", str(bad)]) == 2
    assert "unusable input" in capsys.readouterr().out


def test_eval_runner_pin_model_makes_every_role_answer_with_the_model(monkeypatch, tmp_path):
    import argparse
    from star import desktop_core, doc_knowledge, eval_runner

    seen = {}
    monkeypatch.setattr(eval_runner, "read_key", lambda path: "test-key")
    monkeypatch.setattr(eval_runner, "served_models", lambda server, key: ["star-fast", "star-quick"])
    monkeypatch.setattr(eval_runner, "git_state", lambda: {})
    monkeypatch.setattr(doc_knowledge, "client_for", lambda settings: object())
    monkeypatch.setattr(desktop_core, "run_task", lambda settings, prompt, **kw: seen.setdefault("s", settings) and "ok")
    monkeypatch.setattr(eval_runner, "isolated_appdata", lambda: __import__("contextlib").nullcontext())
    monkeypatch.setenv("STAR_BACKGROUND_WORK", "0")     # build_real marks the process; undone after this test
    for pinned in (False, True):
        seen.clear()
        args = argparse.Namespace(key_file=str(tmp_path / "k"), packs="off", server="http://127.0.0.1:8080/v1",
                                  ssh="", model="star-quick", mode="auto", pin_model=pinned, _suite=None)
        run_info, ask, *_ = eval_runner.build_real(args)
        ask({"id": "LUA-01", "prompt": "hi"})
        roles = {f: getattr(seen["s"], f) for f in ("fast_model", "reasoning_model", "roblox_model", "vision_model")}
        if pinned:
            assert set(roles.values()) == {"star-quick"} and run_info["pinned_roles"] is True
        else:
            assert set(roles.values()) == {""} and "pinned_roles" not in run_info
