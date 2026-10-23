"""Player Twins: personas, bundle building, detectors on synthetic data, and (when a Luau runtime is
installed) real runs of the sample game with and without its three planted flaws."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from star.player_twins import analysis, bundle, runner
from star.player_twins.personas import PERSONAS, assign, parse_personas

ROOT = Path(__file__).resolve().parents[1]
GAMES = ROOT / "star" / "player_twins" / "games"
FLAWED = GAMES / "twin_tycoon"
FIXED = GAMES / "twin_tycoon_fixed"


def _runtime():
    try:
        return runner.find_runtime("auto")
    except FileNotFoundError:
        return None


needs_runtime = pytest.mark.skipif(_runtime() is None, reason="no Lune/Luau runtime (set STAR_LUNE or STAR_LUAU)")


# ---------------------------------------------------------------- personas
def test_parse_personas_all_and_weights():
    mix = parse_personas("all")
    assert set(mix) == set(PERSONAS) and abs(sum(mix.values()) - 1) < 1e-9
    assert len(mix) >= 5
    assert parse_personas("speedrunner=3,exploiter=1") == {"speedrunner": 0.75, "exploiter": 0.25}
    with pytest.raises(ValueError):
        parse_personas("speedrunner,nobody")
    with pytest.raises(ValueError):
        parse_personas("speedrunner=0")


def test_assign_is_exact_and_deterministic():
    mix = parse_personas("all")
    names = assign(1001, mix)
    assert len(names) == 1001
    assert names == assign(1001, mix)
    assert names.count("casual_kid_mobile") in (300, 301)


def test_plan_twins_unique_seeds():
    plan = runner.plan_twins(50, parse_personas("all"), 2, seed=7)
    assert len({t["seed"] for t in plan}) == 50
    assert plan == runner.plan_twins(50, parse_personas("all"), 2, seed=7)


def test_choose_workers_respects_load():
    assert runner.choose_workers(None, 95, 12) == 1
    assert runner.choose_workers(None, 10, 12) == 4
    assert runner.choose_workers(6, 95, 4) == 4


# ---------------------------------------------------------------- bundle
def test_load_game_layers_fixed_over_flawed():
    flawed, fixed = bundle.load_game(FLAWED), bundle.load_game(FIXED)
    assert [f.rel for f in flawed.files] == [f.rel for f in fixed.files]
    by = {f.rel: f for f in fixed.files}
    assert "price = 4000" in by["ReplicatedStorage/Shared/Config.luau"].source
    assert "stage == data.stage + 1" in by["ServerScriptService/Rules.luau"].source
    assert by["ServerScriptService/TycoonServer.server.luau"].kind == "Script"
    assert by["ServerScriptService/TycoonServer.server.luau"].path == ["ServerScriptService", "TycoonServer"]
    assert fixed.adapter == flawed.adapter  # adapter comes from the base


def test_load_game_rejects_missing_manifest(tmp_path):
    with pytest.raises(FileNotFoundError):
        bundle.load_game(tmp_path)


def test_to_luau_literal():
    assert bundle.to_luau({"a": [1, 2.5, "x"], "b c": True, "n": None}) == '{a = {1, 2.5, "x"}, ["b c"] = true, n = nil}'
    with pytest.raises(ValueError):
        bundle.to_luau(float("inf"))


def test_bundle_maps_error_lines_back_to_source():
    game = bundle.load_game(FLAWED)
    b = bundle.build(game, {"settings": runner.DEFAULT_SETTINGS, "personas": {}, "twins": []})
    rules_line = next(i + 1 for i, line in enumerate(b.lines) if "function Rules.validStageClear" in line)
    mapped = bundle.map_lines(f"C:\\tmp\\twins_bundle_0.luau:{rules_line}: boom", b)
    expected = 1 + game.files[1].source.splitlines().index(
        next(l for l in game.files[1].source.splitlines() if "function Rules.validStageClear" in l))
    assert mapped == f"ServerScriptService/Rules.luau:{expected}: boom"
    assert bundle.map_lines(f'[string "twins_bundle_3"]:{rules_line}: x', b).startswith("ServerScriptService/Rules.luau:")


# ---------------------------------------------------------------- detectors on synthetic sessions
MAIN = ["a", "b", "c"]


def _session(twin, persona="speedrunner", *, idx, quit_reason="time_up", returns=False, wait=10.0, goal=None, day=1,
             timeline=None, max_price=100, actions=None, challenges=None, challenge=None):
    return {"twin": twin, "persona": persona, "day": day, "mainline": MAIN, "mainlineIndex": idx, "quit": quit_reason,
            "returns": returns, "quitInfo": {"wait": wait, "goal": goal, "challenge": challenge},
            "newMilestones": {m: 60 * (i + 1) for i, m in enumerate(MAIN[:idx])},
            "timeline": timeline or [[0, 0, 0, 0], [30, 10, 10, 0], [60, 20, 20, 0]], "maxPrice": max_price,
            "earned": 20, "sunk": 0, "actions": actions or {}, "challenges": challenges or {}, "zone": {"flow": 1}}


META = {"exploiters": ["exploiter"], "settings": {"sampleSec": 30}, "game": "synthetic", "sessions": 0, "twins": 0,
        "days": 1, "runtime": "none", "workers": 0, "elapsed_s": 0, "sessions_per_min": 0, "seed": 0}


def test_wall_detected_only_where_players_quit_bored():
    sessions = [_session(i, idx=1, quit_reason="bored", wait=7200, goal="buy:b") for i in range(40)]
    sessions += [_session(100 + i, idx=3) for i in range(60)]
    rep = analysis.analyze(sessions, META)
    walls = [s for s in rep["walls"] if s.get("wall")]
    assert [(s["from"], s["to"]) for s in walls] == [("a", "b")]
    assert any(f["kind"] == "progression_wall" and "buy:b" in f["text"] for f in rep["findings"])
    q = rep["quit_table"]
    assert q["players"] == 100 and sum(r["quit"] for r in q["rows"]) == 100
    assert q["rows"][-1]["cumulative_pct"] == 100.0


def test_frustration_is_not_an_economy_wall_but_a_difficulty_spike():
    hard = {"stage:1": {"attempts": 3, "fails": 1}, "stage:2": {"attempts": 9, "fails": 9}}
    easy = {"stage:1": {"attempts": 2, "fails": 0}, "stage:2": {"attempts": 2, "fails": 1}}
    sessions = [_session(i, idx=1, quit_reason="frustrated", challenges=hard, challenge="stage:2") for i in range(30)]
    sessions += [_session(100 + i, idx=3, challenges=easy) for i in range(60)]
    rep = analysis.analyze(sessions, META)
    assert not any(s.get("wall") for s in rep["walls"])
    spikes = [c for c in rep["challenges"] if c.get("spike")]
    assert [c["id"] for c in spikes] == ["stage:2"]


def test_inflation_needs_sustained_cheap_prices():
    boom = [[t, 0, 50000 * (t // 30) ** 2, 0] for t in range(0, 601, 30)]
    one_off = [[0, 0, 0, 0], [30, 0, 5000, 0], [60, 0, 5000, 0], [90, 0, 5000, 0]]
    sessions = [_session(i, timeline=boom, idx=3, actions={"buy:x": 40}) for i in range(5)]
    sessions += [_session(10 + i, timeline=one_off, idx=3) for i in range(5)]
    rep = analysis.analyze(sessions, META)
    assert rep["economy"]["inflated_sessions"] == 5
    finding = next(f for f in rep["findings"] if f["kind"] == "inflation")
    assert "buy:x" in finding["text"]
    calm = analysis.analyze(sessions[5:], META)
    assert not any(f["kind"] == "inflation" for f in calm["findings"])


def test_exploit_findings_aggregate_and_exploiters_stay_out_of_quit_table():
    finding = {"remote": "ReplicatedStorage.Remotes.Claim", "kind": "invalid_args_accepted",
               "examples": [{"args": "(1000000000)", "stat": "Cash", "delta": 4e10, "legitMax": 40}]}
    tests = [{"remote": "ReplicatedStorage.Remotes.Claim", "legitSample": True},
             {"remote": "ReplicatedStorage.Remotes.Work", "legitSample": True}]
    sessions = [dict(_session(i, "exploiter", idx=3), findings=[finding], fuzzTests=tests) for i in range(3)]
    sessions += [_session(10 + i, idx=2) for i in range(5)]
    rep = analysis.analyze(sessions, META)
    x = rep["exploits"]
    assert x["fuzz_sessions"] == 3 and x["checks_broken"][0]["sessions"] == 3
    assert x["checks_held"] == ["ReplicatedStorage.Remotes.Work"]
    assert rep["quit_table"]["players"] == 5
    assert any(f["kind"] == "exploit" and "Remotes.Claim" in f["text"] for f in rep["findings"])
    assert "Remotes.Claim" in analysis.render_markdown(rep)


def test_data_loss_on_rejoin_is_reported():
    sessions = [_session(1, idx=2, returns=True), dict(_session(1, idx=2, day=2), prevEndCash=5000, startCash=0)]
    rep = analysis.analyze(sessions, META)
    assert rep["data"]["progress_lost_sessions"] == 1
    assert any(f["kind"] == "data_loss" for f in rep["findings"])


# ---------------------------------------------------------------- real runs (need Lune or Luau)
ENGINE_SPEC = r"""
local W = Engine.newWorld({ tickDt = 1 })
local Instance = select(6, W.envFor(nil))
local game = W.game
local f = Instance.new("Folder")
local p = Instance.new("Part")
assert(p:IsA("BasePart") and p:IsA("Instance") and not p:IsA("Folder"), "IsA inheritance")
local ok, err = pcall(function() return p.NotAThing end)
assert(not ok and tostring(err):find("not a valid member"), "unknown member fails loudly")
ok = pcall(function() return game:GetService("MarketplaceService") end)
assert(not ok, "unknown service fails loudly")
ok = pcall(Instance.new, "Humanoid")
assert(not ok, "unsupported class fails loudly")
f.Parent = W.services.ReplicatedStorage
assert(W.services.ReplicatedStorage:FindFirstChild("Folder") == f)
local iv = Instance.new("IntValue"); iv.Value = 2.7
assert(iv.Value == 2, "IntValue truncates")
local store = game:GetService("DataStoreService"):GetDataStore("s")
local t = { a = 1 }
store:SetAsync("k", t); t.a = 2
assert(store:GetAsync("k").a == 1, "DataStore stores a copy")
local woke = nil
W.task.spawn(function() W.task.wait(3); woke = W.now end)
W.advance(2); assert(woke == nil, "not yet")
W.advance(2); assert(woke == 3, "task.wait wakes on fake clock: " .. tostring(woke))
local beats = 0
game:GetService("RunService").Heartbeat:Connect(function(dt) beats += dt end)
W.advance(5); assert(beats == 5, "Heartbeat dt sums to elapsed time")
local W2 = Engine.newWorld({ dsFailRate = 1, rand = function() return 0 end })
ok = pcall(function() W2.game:GetService("DataStoreService"):GetDataStore("x"):GetAsync("k") end)
assert(not ok and W2.dsFailures == 1, "injected DataStore failure")
print("ENGINE_SPEC_OK")
"""


@needs_runtime
def test_engine_mock_contract(tmp_path):
    kind, exe = _runtime()
    src = "\n".join(f"local {name} = (function()\n{(bundle.LUAU_DIR / f'{mod}.luau').read_text(encoding='utf-8')}\nend)()"
                    for mod, name in (("engine", "Engine"), ("json", "Json")))
    script = tmp_path / "spec.luau"
    script.write_text(src + "\n" + ENGINE_SPEC, encoding="utf-8")
    out = subprocess.run(runner.runtime_command(kind, exe, script), capture_output=True, text=True, timeout=60)
    assert "ENGINE_SPEC_OK" in out.stdout, out.stdout + out.stderr


@needs_runtime
def test_twins_find_all_three_planted_flaws_and_none_in_fixed_game():
    mix = parse_personas("all")
    flawed = runner.run(FLAWED, twins=150, mix=mix, days=2, seed=11, workers=1)
    fixed = runner.run(FIXED, twins=150, mix=mix, days=2, seed=11, workers=1)
    assert not flawed.errors and not fixed.errors
    rep_flawed = analysis.analyze(flawed.sessions, flawed.meta)
    rep_fixed = analysis.analyze(fixed.sessions, fixed.meta)
    kinds = {f["kind"] for f in rep_flawed["findings"] if f["severity"] == "high"}
    assert {"progression_wall", "exploit", "inflation"} <= kinds, json.dumps(rep_flawed["findings"], indent=1)
    wall = next(f for f in rep_flawed["findings"] if f["kind"] == "progression_wall")
    assert wall["evidence"]["to"] == "dropper4"
    exploit = next(f for f in rep_flawed["findings"] if f["kind"] == "exploit")
    assert "ClearStage" in exploit["text"]
    assert "buy:conveyor" in next(f for f in rep_flawed["findings"] if f["kind"] == "inflation")["text"]
    assert [f for f in rep_fixed["findings"] if f["severity"] == "high"] == []
    assert rep_fixed["harness_errors"] == [] and rep_fixed["errors"] == []


@needs_runtime
def test_cli_writes_reports(tmp_path):
    from star.player_twins.__main__ import main
    code = main(["run", str(FIXED), "--sessions", "12", "--days", "1", "--workers", "1", "--out", str(tmp_path)])
    assert code == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["meta"]["sessions"] == 12
    assert "Where players quit" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_collect_reports_missing_shard_output(tmp_path):
    runner.write_shards(tmp_path, FIXED, twins=4, mix=parse_personas("speedrunner"), shards=2)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["shards.json", "twins_bundle_0.luau", "twins_bundle_1.luau"]
    result = runner.collect(tmp_path)
    assert result.sessions == [] and len(result.errors) == 2


@needs_runtime
def test_shards_run_elsewhere_match_a_local_run(tmp_path):
    kind, exe = _runtime()
    mix = parse_personas("all")
    paths = runner.write_shards(tmp_path, FLAWED, twins=30, mix=mix, days=1, seed=5, shards=3)
    for path in paths:
        out = subprocess.run(runner.runtime_command(kind, exe, path), capture_output=True, text=True, timeout=120)
        Path(str(path) + ".out").write_text(out.stdout, encoding="utf-8")
    remote = runner.collect(tmp_path)
    local = runner.run(FLAWED, twins=30, mix=mix, days=1, seed=5, workers=3)
    assert not remote.errors and len(remote.sessions) == 30
    key = lambda s: (s["twin"], s["day"])  # noqa: E731
    assert [(s["quit"], s["duration"]) for s in sorted(remote.sessions, key=key)] ==         [(s["quit"], s["duration"]) for s in sorted(local.sessions, key=key)]
