"""Offline regression coverage for the read-only verified curriculum."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from star.brain2_practice import PracticeLedger, PracticePlan
from star.learning_accelerator import (
    Capability, VerifiedObservation, main, rank_curriculum,
    read_practice_evidence, recommend_from_ledger,
)

BASE = datetime(2026, 10, 24, 10, tzinfo=timezone.utc)


def _ledger(tmp_path):
    current = [BASE]
    store = PracticeLedger(tmp_path / "verified.sqlite3", clock=lambda: current[0])
    plan = PracticePlan("game-a", tmp_path, 101, 202, interval_seconds=300,
                        daily_limit=48)
    return store, plan, current


def _record(store, scope, clock, *, cases, sha="a", version=1):
    cycle = store.reserve(scope)
    passed = sum(x["ok"] for x in cases)
    failed = len(cases) - passed
    store.finish(
        cycle, status="passed" if failed == 0 else "failed",
        sha256=sha * 64, version=version,
        summary={"passed": passed, "failed": failed, "cases": cases})
    clock[0] += timedelta(minutes=6)
    return cycle


def test_read_only_verified_receipts_scope_exactness(tmp_path):
    store, scope, clock = _ledger(tmp_path)
    _record(store, scope, clock, cases=[
        {"name": "movement", "ok": True}, {"name": "inventory", "ok": False}])
    store.close()
    path = tmp_path / "verified.sqlite3"
    before = path.read_bytes()
    evidence, summary = read_practice_evidence(
        path, "game-a", now=BASE + timedelta(days=1), target=(101, 202))
    assert [(r.name, r.passed) for r in evidence] == [
        ("movement", True), ("inventory", False)]
    assert summary["confirmed_cycles"] == 1
    assert summary["distinct_evidence"] == 2
    assert summary["ledger_read_only"] is True
    assert path.read_bytes() == before
    other, _ = read_practice_evidence(
        path, "game-b", now=BASE + timedelta(days=1))
    assert other == []
    wrong, _ = read_practice_evidence(
        path, "game-a", target=(111, 222), now=BASE + timedelta(days=1))
    assert wrong == []


def test_replayed_identical_artifact_is_not_false_progress(tmp_path):
    store, scope, clock = _ledger(tmp_path)
    _record(store, scope, clock, sha="a", cases=[{"name": "jump", "ok": False}])
    _record(store, scope, clock, sha="a", cases=[{"name": "jump", "ok": False}])
    _record(store, scope, clock, sha="b", cases=[{"name": "jump", "ok": True}])
    store.close()
    evidence, stats = read_practice_evidence(
        tmp_path / "verified.sqlite3", "game-a", now=BASE + timedelta(days=1))
    assert len(evidence) == 2
    assert stats["duplicate_artifact_cases"] == 1
    assert {row.passed for row in evidence} == {False, True}


def test_malformed_stored_receipt_does_not_count_as_success(tmp_path):
    store, scope, clock = _ledger(tmp_path)
    cycle = _record(store, scope, clock, cases=[{"name": "attack", "ok": True}])
    # A corrupted record disagrees with the host's stored pass totals.
    store.db.execute(
        "UPDATE practice_cycles SET cases_json=? WHERE id=?",
        (json.dumps([{"name": "attack", "ok": False}]), cycle))
    store.close()
    records, stats = read_practice_evidence(
        tmp_path / "verified.sqlite3", "game-a", now=BASE + timedelta(days=1))
    assert records == []
    assert stats["rejected_cycles"] == 1


def test_unknown_blocked_and_running_are_not_training_evidence(tmp_path):
    store, scope, clock = _ledger(tmp_path)
    a = store.reserve(scope)
    store.finish(a, status="blocked")
    clock[0] += timedelta(minutes=6)
    b = store.reserve(scope)
    store.finish(b, status="unknown")
    store.close()
    records, stats = read_practice_evidence(
        tmp_path / "verified.sqlite3", "game-a", now=BASE + timedelta(days=1))
    assert not records
    assert stats["confirmed_cycles"] == 0


def test_fresh_passes_are_cooled_down():
    cap = Capability("movement")
    obs = VerifiedObservation("movement", True, BASE, "a" * 64, 1)
    result = rank_curriculum([cap], [obs], now=BASE + timedelta(hours=1))
    assert result["suggestions"] == []
    assert result["not_yet_due"] == 1


def test_failed_cases_receive_priority_after_cooldown():
    caps = [Capability("failed-case", "engine"), Capability("passed-case", "engine")]
    events = [
        VerifiedObservation("failed-case", False, BASE, "a" * 64, 1),
        VerifiedObservation("passed-case", True, BASE, "b" * 64, 2),
    ]
    recent = rank_curriculum(caps, events, now=BASE + timedelta(minutes=10))
    assert not recent["suggestions"]
    due = rank_curriculum(caps, events, now=BASE + timedelta(minutes=40))
    assert [r["name"] for r in due["suggestions"]] == ["failed-case"]
    assert due["suggestions"][0]["reason"] == "recent_verified_failure"


def test_untried_capability_can_be_suggested_without_claiming_learning():
    result = rank_curriculum(
        [Capability("untried-vfx", domain="vfx")], [],
        now=BASE, budget_seconds=360)
    assert result["suggestions"][0]["reason"] == "untried"
    assert result["suggestions"][0]["verified_passes"] == 0
    assert result["suggestions"][0]["verified_failures"] == 0
    assert result["no_training"] is True
    assert result["no_execution"] is True


def test_spaced_repetition_doubles_after_success_streak():
    cap = Capability("animation")
    rows = [
        VerifiedObservation("animation", True, BASE, "a" * 64, 1),
        VerifiedObservation("animation", True, BASE - timedelta(hours=2), "b" * 64, 2),
        VerifiedObservation("animation", True, BASE - timedelta(days=1), "c" * 64, 3),
    ]
    assert not rank_curriculum([cap], rows, now=BASE + timedelta(hours=10))["suggestions"]
    due = rank_curriculum([cap], rows, now=BASE + timedelta(hours=24))
    assert due["suggestions"][0]["reason"] == "spaced_recheck"


def test_budget_constrains_total_cost_and_domain_diversity():
    caps = [
        Capability("math-a", "math", seconds=90),
        Capability("math-b", "math", seconds=90),
        Capability("code-a", "code", seconds=90),
    ]
    result = rank_curriculum(caps, [], budget_seconds=180, now=BASE)
    assert result["budget_used_seconds"] == 180
    assert {i["domain"] for i in result["suggestions"]} == {"math", "code"}
    assert len(result["suggestions"]) == 2


def test_bad_observations_are_rejected_not_silently_counted():
    cap = Capability("script")
    with pytest.raises(ValueError, match="verified"):
        rank_curriculum(
            [cap], [VerifiedObservation("script", True, BASE, "no-digest", 1)],
            now=BASE)
    with pytest.raises(ValueError, match="verified"):
        rank_curriculum(
            [cap], [VerifiedObservation("script", True, BASE + timedelta(days=1),
                                        "a" * 64, 1)], now=BASE)
    with pytest.raises(ValueError, match="duplicate"):
        rank_curriculum([cap, cap], [], now=BASE)


def test_invalid_scope_and_catalog_are_refused(tmp_path):
    with pytest.raises(ValueError):
        Capability("bad\nshell")
    with pytest.raises(ValueError):
        Capability("long", seconds=86400)
    with pytest.raises(ValueError):
        read_practice_evidence(tmp_path / "missing.sqlite3", "bad/project")
    with pytest.raises(ValueError):
        rank_curriculum([Capability("valid")], [], now=BASE,
                        budget_seconds=-50)


def test_recommendation_does_not_execute_or_mutate_tests(tmp_path):
    store, scope, clock = _ledger(tmp_path)
    _record(store, scope, clock, cases=[{"name": "luau-case", "ok": False}])
    store.close()
    path = tmp_path / "verified.sqlite3"
    prior_hash = path.read_bytes()
    result = recommend_from_ledger(
        path, "game-a", target=(101, 202),
        now=BASE + timedelta(hours=2),
        catalog=[Capability("new-capability", "design", seconds=60)])
    assert {x["name"] for x in result["suggestions"]} == {
        "luau-case", "new-capability"}
    assert result["no_execution"] is True
    assert path.read_bytes() == prior_hash


def test_cli_suggests_only_and_handles_missing_ledger(tmp_path, capsys):
    store, scope, clock = _ledger(tmp_path)
    _record(store, scope, clock, cases=[{"name": "case-x", "ok": False}])
    store.close()
    args = ["--ledger", str(tmp_path / "verified.sqlite3"),
            "--project", "game-a", "--minutes", "30", "--top", "5"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["no_execution"] is True
    assert "suggestions" in report
    assert main(["--ledger", str(tmp_path / "missing.sqlite3"),
                 "--project", "game-a"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "refused"



def test_republishing_unchanged_source_is_not_independent_learning(tmp_path):
    store, scope, clock = _ledger(tmp_path)
    _record(store, scope, clock, sha="a", version=1,
            cases=[{"name": "render", "ok": True}])
    _record(store, scope, clock, sha="a", version=2,
            cases=[{"name": "render", "ok": True}])
    store.close()
    evidence, info = read_practice_evidence(
        tmp_path / "verified.sqlite3", "game-a", now=BASE + timedelta(days=1))
    assert len(evidence) == 1
    assert info["duplicate_artifact_cases"] == 1


def test_practice_cli_preview_only_from_existing_operator_plan(tmp_path, capsys):
    from star.brain2_practice import main as practice_main

    store, scope, clock = _ledger(tmp_path)
    _record(store, scope, clock, sha="b",
            cases=[{"name": "inventory", "ok": False}])
    store.close()
    settings = {
        "project": scope.project, "source": str(tmp_path / "source"),
        "universe_id": scope.universe_id, "place_id": scope.place_id,
        "builder": "builtin", "interval_seconds": 300, "daily_limit": 24,
    }
    (tmp_path / "source").mkdir()
    plan_file = tmp_path / "practice-plan.json"
    plan_file.write_text(json.dumps(settings))
    # brain2-practice's conventional filename is distinct from the test's
    # synthetic ledger, so use an isolated home with a copy of the DB.
    home = tmp_path / "profile"
    home.mkdir()
    import shutil
    shutil.copy2(tmp_path / "verified.sqlite3",
                 home / "brain2-practice.sqlite3")
    before = (home / "brain2-practice.sqlite3").read_bytes()
    assert practice_main([
        "--plan", str(plan_file), "--home", str(home),
        "--suggest-learning",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["no_execution"] is True
    assert result["target"] == [101, 202]
    assert (home / "brain2-practice.sqlite3").read_bytes() == before
    with pytest.raises(SystemExit):
        practice_main([
            "--plan", str(plan_file), "--home", str(home),
            "--suggest-learning", "--run",
        ])
