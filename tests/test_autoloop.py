"""#562 loop end to end: sealed A/B -> integrity decision -> live setting -> receipt -> automatic rollback."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from star import autoloop, integrity, sealed_eval as se
from star.desktop_core import Settings

N = 60                                   # scored tasks: enough for a powered PROMOTE when the candidate fixes half


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("STAR_RECEIPTS_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("STAR_PROMOTIONS_FILE", str(tmp_path / "promotions.json"))
    monkeypatch.delenv("STAR_AUTO_PROMOTIONS", raising=False)
    return tmp_path


@pytest.fixture
def sealed(home, monkeypatch):
    from star.eval_runner import grader_sha256
    root = home / "sealed"
    monkeypatch.setenv("STAR_SEALED_DIR", str(root))
    monkeypatch.setattr(se, "MANIFEST_DIR", home / "manifests")
    (home / "manifests").mkdir()
    folder = root / "s1"
    folder.mkdir(parents=True)
    tasks = [{"id": f"T{i:02d}", "family": "luau-bugfix", "difficulty": 1, "prompt": f"p{i}"} for i in range(N)]
    tasks.append({"id": "C1", "family": "canary", "difficulty": 1, "prompt": "impossible"})
    (folder / "suite.json").write_text(json.dumps(tasks), encoding="utf-8")
    manifest = se.build_manifest("s1", folder, grader_sha256=grader_sha256())
    se.manifest_path("s1").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "results").mkdir()
    return folder / "results"


def _run(results, name, settings, failing, *, started=None, canary="fail", count=N):
    tasks = {f"T{i:02d}": {"status": "fail" if i < failing else "pass"} for i in range(count)}
    tasks["C1"] = {"status": canary}
    started = started or datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    run = {"complete": True, "tasks": tasks,
           "run": {"settings": settings, "model": "star-fast", "provider": "star_server", "mode": "auto",
                   "skill_packs": "off", "knowledge": "on", "temperature": 0, "started_at": started.isoformat()}}
    (results / f"{name}.json").write_text(json.dumps(run), encoding="utf-8")


def _dev(home, decision="PROMOTE"):
    path = home / "dev.json"
    path.write_text(json.dumps({"paired": {"decision": decision}}), encoding="utf-8")
    return str(path)


def _cycle(*args):
    return autoloop.main(["cycle", "--set", "s1", *args])


def test_live_keys_are_measurable_and_never_owner_facing():
    from star.eval_runner import _SETTABLE
    from star.react_shell import PERMITTED_SETTINGS
    assert autoloop.LIVE_KEYS <= _SETTABLE and not autoloop.LIVE_KEYS & PERMITTED_SETTINGS
    assert autoloop.LIVE_KEYS <= set(Settings.__dataclass_fields__)


def test_settings_load_applies_only_valid_promotions_of_live_keys(home):
    file = home / "settings.json"
    Settings().save(file)
    assert Settings.load(file).verify_ladder == "on"
    integrity.write_overlay({"verify_ladder": "off", "studio_edit": True, "luau_retry_ladder": True,
                             "verify_rounds": 99, "verify_budget_s": "60"})
    s = Settings.load(file)
    assert s.verify_ladder == "off"                                 # promoted
    assert s.studio_edit is False and s.luau_retry_ladder is False  # permission / owner-facing keys: never
    assert s.verify_rounds == 2 and s.verify_budget_s == 240        # invalid value / wrong type: ignored


def test_save_never_persists_a_promotion_so_rollback_takes_effect(home):
    file = home / "settings.json"
    integrity.write_overlay({"verify_ladder": "off"})
    Settings.load(file).save(file)
    assert json.loads(file.read_text())["verify_ladder"] == "on"
    integrity.write_overlay({})
    assert Settings.load(file).verify_ladder == "on"


def test_live_use_can_be_switched_off(home, monkeypatch):
    integrity.write_overlay({"verify_ladder": "off"})
    monkeypatch.setenv("STAR_AUTO_PROMOTIONS", "0")
    assert Settings.load(home / "missing.json").verify_ladder == "on"


def test_cycle_promotes_goes_live_then_rolls_back_on_regression(home, sealed, capsys):
    _run(sealed, "on-1", {"verify_ladder": "on"}, failing=30)       # the live default loses half the tasks
    _run(sealed, "off-1", {"verify_ladder": "off"}, failing=0)
    assert _cycle("--arm", "on-1", "--arm", "off-1", "--dev", _dev(home)) == 0
    decision = json.loads(capsys.readouterr().out)["decision"]
    assert decision["promote"] and decision["apply"] == {"verify_ladder": "off"}
    assert Settings.load(home / "settings.json").verify_ladder == "off"           # adopted live, no click
    receipt = json.loads(open(decision["receipt"], encoding="utf-8").read())
    assert receipt["kind"] == "promotion" and receipt["rollback"] == {"verify_ladder": None}

    _cycle("--arm", "on-1", "--arm", "off-1", "--dev", _dev(home))
    out = json.loads(capsys.readouterr().out)
    assert out["decision"]["why"] == "already decided"
    assert out["watch"][0]["status"] == "waiting for data"                      # its own runs do not count

    later = datetime.now(timezone.utc) + timedelta(hours=1)
    _run(sealed, "off-2", {"verify_ladder": "off"}, failing=40, started=later)   # the promoted value regresses
    _run(sealed, "on-2", {"verify_ladder": "on"}, failing=50, started=later)     # other arms are not the promotion
    _cycle()
    watch = json.loads(capsys.readouterr().out)["watch"][0]
    assert watch["status"] == "rolled back" and watch["live"] == f"{N - 40}/{N}" and watch["runs"] == ["off-2"]
    assert integrity.read_overlay() == {}
    assert Settings.load(home / "settings.json").verify_ladder == "on"
    assert json.loads(open(watch["rollback_receipt"], encoding="utf-8").read())["kind"] == "rollback"
    _cycle()
    assert json.loads(capsys.readouterr().out)["watch"] == []                    # rolled back: no longer watched


def test_healthy_promotion_stays(home, sealed, capsys):
    _run(sealed, "on-1", {}, failing=40)                                         # no override = the code default
    _run(sealed, "off-1", {"verify_ladder": "off"}, failing=10)                  # promoted at 50/60
    _cycle("--arm", "off-1", "--arm", "on-1", "--dev", _dev(home))
    assert json.loads(capsys.readouterr().out)["decision"]["promote"]
    _run(sealed, "off-2", {"verify_ladder": "off"}, failing=12, started=datetime.now(timezone.utc) + timedelta(hours=1))
    _cycle()
    assert json.loads(capsys.readouterr().out)["watch"][0]["status"] == "healthy"
    assert integrity.read_overlay() == {"verify_ladder": "off"}


@pytest.mark.parametrize("dev,a,b,why", [
    ("UNDERPOWERED", {"verify_ladder": "on"}, {"verify_ladder": "off"}, "dev verdict is UNDERPOWERED"),
    ("PROMOTE", {"slop_check": "flag"}, {"slop_check": "trim"}, "neither arm"),
    ("PROMOTE", {"verify_ladder": "on", "luau_retry_ladder": True}, {"verify_ladder": "off"}, "differ outside"),
    ("PROMOTE", {"verify_ladder": "on"}, {"verify_ladder": "on"}, "do not differ"),
])
def test_refusals_leave_the_live_settings_alone(home, sealed, capsys, dev, a, b, why):
    _run(sealed, "a", a, failing=30)
    _run(sealed, "b", b, failing=0)
    _cycle("--arm", "a", "--arm", "b", "--dev", _dev(home, dev))
    decision = json.loads(capsys.readouterr().out)["decision"]
    assert not decision.get("promote") and why in (decision.get("why", "") + " ".join(decision.get("reasons", [])))
    assert integrity.read_overlay() == {}


def test_a_canary_pass_refuses(home, sealed, capsys):
    _run(sealed, "on-1", {"verify_ladder": "on"}, failing=30)
    _run(sealed, "off-1", {"verify_ladder": "off"}, failing=0, canary="pass")
    _cycle("--arm", "on-1", "--arm", "off-1", "--dev", _dev(home))
    decision = json.loads(capsys.readouterr().out)["decision"]
    assert not decision["promote"] and any("canary passed" in r for r in decision["reasons"])


def test_a_refusal_on_a_partly_written_run_does_not_block_the_full_decision(home, sealed, capsys):
    _run(sealed, "on-1", {"verify_ladder": "on"}, failing=4, count=6)            # the driver is still writing
    _run(sealed, "off-1", {"verify_ladder": "off"}, failing=0, count=6)
    _cycle("--arm", "on-1", "--arm", "off-1", "--dev", _dev(home))
    first = json.loads(capsys.readouterr().out)["decision"]
    assert not first["promote"] and any("UNDERPOWERED" in r for r in first["reasons"])
    _run(sealed, "on-1", {"verify_ladder": "on"}, failing=30)
    _run(sealed, "off-1", {"verify_ladder": "off"}, failing=0)
    _cycle("--arm", "on-1", "--arm", "off-1", "--dev", _dev(home))
    assert json.loads(capsys.readouterr().out)["decision"]["promote"]
