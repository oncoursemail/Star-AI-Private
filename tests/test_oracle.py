"""Star Oracle (star/oracle): probe twins, change kinds, L1/L2 statistics, L0 comparison, IRT + sequential stop,
calibration and the cascade. No model binary is needed: scorer and server are replaced by fakes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from star.oracle import calibrate, cascade, config, equiv, irt, probe, prompts, score

GOOD = """Here is the module.

```luau
--!strict
local Players = game:GetService("Players")
local remote = script.Parent.Buy

local function total(items: {number}): number
	local sum = 0
	for i = 1, #items do
		sum += items[i]
	end
	return sum
end

remote.OnServerEvent:Connect(function(player, amount)
	if typeof(amount) ~= "number" then return end
	if amount <= 0 then
		return
	end
	local char = player.Character
	if char and char:FindFirstChild("Humanoid") then
		print(total({amount}))
	end
end)
```
"""


def _diff(a: str, b: str) -> tuple[set[str], set[str]]:
    la, lb = a.splitlines(), b.splitlines()
    return set(la) - set(lb), set(lb) - set(la)


def test_each_bug_kind_plants_exactly_the_named_defect():
    bads = {b["kind"]: b["text"] for b in probe.make_bads(GOOD, confusions=[{"right": ":FindFirstChild(",
                                                                              "wrong": ":FindChild("}])}
    assert set(bads) == {"off_by_one", "wrong_comparison", "missing_nil_check", "server_trust", "invented_api", "slop"}
    gone, new = _diff(GOOD, bads["off_by_one"])
    assert gone == {"\tfor i = 1, #items do"} and new == {"\tfor i = 1, #items - 1 do"}
    gone, new = _diff(GOOD, bads["wrong_comparison"])
    assert new == {'\tif typeof(amount) == "number" then return end'}
    gone, new = _diff(GOOD, bads["missing_nil_check"])
    assert new == {'\tif char:FindFirstChild("Humanoid") then'}
    gone, new = _diff(GOOD, bads["server_trust"])
    assert '\tif typeof(amount) ~= "number" then return end' in gone and "\tif amount <= 0 then" in gone and not new
    assert ":FindChild(" in bads["invented_api"] and ":FindFirstChild(" not in bads["invented_api"]
    assert bads["slop"].startswith(probe.SLOP_OPEN) and GOOD.strip() in bads["slop"]


def test_slop_twin_is_kept_only_when_the_checker_scores_it_worse():
    assert [b["kind"] for b in probe.make_bads("no code here", slop_score=lambda t: 1)] == []
    assert [b["kind"] for b in probe.make_bads("no code here", slop_score=len)] == ["slop"]


def test_invented_api_fallback_never_produces_a_real_member():
    class Info:
        def __init__(self, members):
            self.members = frozenset(members)

    class Dump:
        classes = {"Players": Info({"GetPlayers", "GetPlayersAsync"}), "Model": Info({"GetPivot"})}

    code = "for _, p in Players:GetPlayers() do end"
    out = probe.invented_api(code, Dump(), ())
    assert out is not None and "GetPlayersAsync" not in out and ":GetGetPlayers(" in out


def test_build_needs_a_bug_twin_and_spread_is_deterministic():
    sources = [("gold:gb-ui-a", "make it", GOOD), ("gold:gb-ui-b", "x", "prose only"),
               ("gold:gb-data-c", "y", GOOD.replace("#items", "3")), ("gold:gb-eng-d", "z", GOOD)]
    pairs = probe.build(sources)
    assert [p.source for p in pairs] == ["gold:gb-ui-a", "gold:gb-data-c", "gold:gb-eng-d"]
    first = [p.source for p in probe.spread(pairs, 2)]
    assert first == [p.source for p in probe.spread(list(reversed(pairs)), 2)]
    assert len({s.split("-")[1] for s in first}) == 2


def test_eval_sources_take_passing_answers_and_refuse_holdout(tmp_path):
    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps([{"id": "T1", "prompt": "do it"}, {"id": "T2", "prompt": "other"}]))
    res = tmp_path / "r.json"
    res.write_text(json.dumps({"suite": {"file": "suite.json"}, "tasks": {
        "T1": {"status": "pass", "answer": GOOD}, "T2": {"status": "fail", "answer": GOOD}}}))
    got = probe.eval_sources([res], tmp_path)
    assert [(s, p) for s, p, _ in got] == [("eval:suite:T1", "do it")]
    bad = tmp_path / "holdout-v1-x.json"
    bad.write_text(res.read_text())
    with pytest.raises(ValueError):
        probe.eval_sources([bad], tmp_path)


def test_change_kinds():
    base = config.from_dict({"name": "a", "model": "m.gguf"})
    assert config.change_kinds(base, config.from_dict({"name": "b", "model": "m.gguf",
                                                        "settings": {"slop_check": "off"}})) == set()
    assert config.change_kinds(base, config.from_dict({"name": "b", "model": "m.gguf", "threads": 8})) == {"perf"}
    assert config.change_kinds(base, config.from_dict({"name": "b", "model": "m.gguf", "lora": ["x"]})) == {"model"}
    assert config.change_kinds(base, config.from_dict({"name": "b", "model": "m.gguf",
                                                        "settings": {"api_hints_enabled": True}})) == {"prompt"}
    assert config.change_kinds(base, config.from_dict({"name": "b", "model": "m.gguf",
                                                        "settings": {"luau_retry_ladder": True}})) == {"loop"}
    with pytest.raises(ValueError):
        config.from_dict({"name": "x", "modle": "typo"})


def test_prefix_adds_the_api_hint_block_only_when_enabled():
    plain = config.from_dict({"name": "a", "system": "SYS"})
    hints = config.from_dict({"name": "b", "system": "SYS", "settings": {"api_hints_enabled": True}})
    request = "Tween a Part with TweenService"
    p0, p1 = prompts.prefix(plain, request), prompts.prefix(hints, request)
    assert p0 == ("<|im_start|>system\nSYS<|im_end|>\n<|im_start|>user\nTween a Part with TweenService<|im_end|>\n"
                  "<|im_start|>assistant\n")
    assert p1.startswith(p0[:40]) and "ROBLOX API MEMBERS" in p1 and "Create" in p1
    assert prompts.target(plain, "ok") == "ok<|im_end|>"


def _pairs():
    return [probe.Pair("p1", "s1", "q", "g", [{"kind": "off_by_one", "text": "b1"}, {"kind": "slop", "text": "b2"}]),
            probe.Pair("p2", "s2", "q", "g", [{"kind": "invented_api", "text": "b3"}])]


def _rows(lp: dict[str, list[float]], kl=None):
    rows = []
    for pid, values in lp.items():
        targets = [{"n": 10, "sum_logprob": v, "top1_hits": 5} for v in values]
        if kl is not None:
            targets[0].update(kl_sum=kl * 10, agree=9)
        rows.append({"id": pid, "n_prefix": 5, "targets": targets})
    return rows


def test_l2_report_is_the_paired_margin_change():
    base = _rows({"p1": [-10, -12, -15], "p2": [-20, -21]})      # margins 2, 5 | 1
    cand = _rows({"p1": [-10, -14, -15], "p2": [-20, -25]})      # margins 4, 5 | 5
    rep = score.l2_report(_pairs(), base, cand)                  # correctness twins only: 2 -> 4 and 1 -> 5
    assert rep["twins"] == 2 and rep["answers"] == 2
    assert rep["base_margin"] == pytest.approx(1.5) and rep["cand_margin"] == pytest.approx(4.5)
    assert rep["delta"] == pytest.approx(3.0)
    assert rep["per_kind"]["off_by_one"]["delta"] == 2 and rep["per_kind"]["invented_api"]["delta"] == 4
    assert rep["per_kind"]["slop"]["delta"] == 0
    assert rep["delta_ci90"][0] <= rep["delta"] <= rep["delta_ci90"][1]
    only = score.l2_report(_pairs(), base, cand, kinds=["slop"])
    assert only["twins"] == 1 and only["delta"] == 0


def test_l1_report_and_bootstrap_determinism():
    assert score.l1_report(_rows({"p1": [-1]})) is None
    rep = score.l1_report(_rows({"p1": [-1], "p2": [-2]}, kl=0.01))
    assert rep == {"tokens": 20, "kl_per_token": 0.01, "top1_agreement": 0.9}
    groups = [[1.0, 2.0], [3.0], [-1.0]]
    assert score.bootstrap_mean_ci(groups, seed=3) == score.bootstrap_mean_ci(groups, seed=3)


def test_l0_compare_reports_the_first_divergence():
    assert equiv.compare([[1, 2], [3]], [[1, 2], [3]])["verdict"] == "EQUIVALENT"
    got = equiv.compare([[1, 2, 3], [4]], [[1, 9, 3], [5]])
    assert got["verdict"] == "DIFFERENT" and got["differing_prompts"] == 2 and got["first_difference"] == {
        "prompt": 0, "token": 1}
    assert equiv.compare([[]], [[]])["verdict"] == "DIFFERENT"


def test_l0_outputs_closes_the_server():
    closed = []

    class Fake:
        def __init__(self, cfg, workdir):
            self.cfg = cfg

        def greedy(self, prompt, n):
            return [len(prompt), n]

        def close(self):
            closed.append(True)

    got = equiv.outputs(config.from_dict({"name": "a"}), ["ab", "abc"], Path("."), n_predict=4, server_cls=Fake)
    assert got["tokens"] == [[2, 4], [3, 4]] and closed == [True]


def test_irt_fit_orders_tasks_by_information():
    # 12 runs of rising ability; task "easy" passed by all but the weakest, "mid" by the top half, "hard" by none.
    runs = {f"r{i}": {"easy": i > 0, "mid": i >= 6, "hard": False, "noise": i % 2 == 0} for i in range(12)}
    m = irt.fit(runs)
    assert m.b["hard"] > m.b["mid"] > m.b["easy"]
    assert m.a["mid"] > m.a["noise"]
    theta_mid = m.theta["r6"]
    assert irt.order(m, theta_mid, ["hard", "noise", "mid", "new"])[0] == "mid"
    assert irt.order(m, theta_mid, ["hard", "noise", "mid", "new"])[-1] == "new"
    assert m.ability({"easy": True, "mid": True}) > m.ability({"easy": False, "mid": False})


def test_sequential_stops_on_clear_results_and_not_on_ties():
    s = irt.Sequential()
    for _ in range(6):
        s.add(False, True)
    assert s.decision() is None
    s.add(False, True)
    assert s.decision() == irt.BETTER                          # 1.5 ** 7 > 16
    s = irt.Sequential()
    for _ in range(7):
        s.add(True, False)
    assert s.decision() == irt.WORSE
    s = irt.Sequential()
    for _ in range(6):
        s.add(True, False)
        s.add(False, True)
    assert s.decision() == irt.NO_DIFF
    s = irt.Sequential()
    for _ in range(30):
        s.add(True, True)
    assert s.decision() is None


def test_run_adaptive_stops_early_and_skips_errors():
    outcomes = {f"t{i}": (False, True) for i in range(20)}
    outcomes["t1"] = None
    res = irt.run_adaptive(list(outcomes), outcomes.get)
    assert res["decision"] == irt.BETTER and res["tasks_run"] == 7 and res["wins"] == 7
    assert res["trace"][1] == {"task": "t1", "error": True}
    flat = irt.run_adaptive([f"t{i}" for i in range(5)], lambda t: (True, True))
    assert flat["decision"] == irt.INCONCLUSIVE and flat["tasks_run"] == 5


def test_calibration_fit_predict_and_backtest(tmp_path):
    model = calibrate.fit([(1.0, 0.1), (2.0, 0.2), (-1.0, -0.1)])
    assert model["slope"] == pytest.approx(0.1) and model["sigma"] == pytest.approx(0.0)
    assert calibrate.predict(model, 3.0)["verdict"] == "BETTER"
    assert calibrate.predict(model, -3.0)["verdict"] == "WORSE"
    noisy = calibrate.fit([(1.0, 0.3), (1.0, -0.2), (2.0, 0.0)])
    assert calibrate.predict(noisy, 0.5)["verdict"] == "ESCALATE"
    assert calibrate.predict(None, 1.0)["verdict"] == "ESCALATE"
    assert calibrate.fit([(1.0, 1.0)]) is None

    def result(name, statuses):
        path = tmp_path / name
        path.write_text(json.dumps({"suite": {"file": "s.json"},
                                    "tasks": {f"T{i}": {"status": s} for i, s in enumerate(statuses)}}))
        return name

    pairs = [probe.Pair("p1", "s", "q", "g", [{"kind": "off_by_one", "text": "b"}])]
    probe.write(pairs, tmp_path / "probe.jsonl")
    registry = []
    for i, (gain, cand_status) in enumerate([(1.0, ["pass"] * 6 + ["fail"] * 4), (2.0, ["pass"] * 7 + ["fail"] * 3),
                                             (-1.0, ["pass"] * 4 + ["fail"] * 6)]):
        for arm, margin in (("b", 1.0), ("c", 1.0 + gain)):
            (tmp_path / f"{i}{arm}.scores.jsonl").write_text(json.dumps(
                {"id": "p1", "n_prefix": 1,
                 "targets": [{"n": 1, "sum_logprob": 0.0}, {"n": 1, "sum_logprob": -margin}]}))
        registry.append({"name": f"ab{i}", "kinds": ["model"],
                         "base": [result(f"{i}b.json", ["pass"] * 5 + ["fail"] * 5)],
                         "cand": [result(f"{i}c.json", cand_status)], "probe": "probe.jsonl",
                         "base_scores": f"{i}b.scores.jsonl", "cand_scores": f"{i}c.scores.jsonl",
                         "eval_hours": 6.0, "oracle_hours": 0.3})
    registry.append({"name": "loop", "kinds": ["loop"], "base": ["0b.json"], "cand": ["0c.json"]})
    out = calibrate.run(registry, base_dir=tmp_path)
    s = out["summary"]
    assert s["abs"] == 4 and s["with_l2"] == 3 and out["model"]["slope"] == pytest.approx(0.1)
    assert out["entries"][3]["loo"]["verdict"] == "ESCALATE"
    assert out["entries"][1]["full"]["delta"] == pytest.approx(0.2)
    assert s["time_ratio"] == pytest.approx(0.05) and s["sign_match"] == "3/3"
    assert "ab0" in calibrate.markdown(out)


def _fake_scores(monkeypatch, margins_by_cfg):
    def fake(cfg, items, workdir, *, topk=0, ref=None, log=print):
        rows = []
        for item in items:
            good, *bads = item["targets"]
            m = margins_by_cfg[cfg.name]
            targets = [{"n": 4, "sum_logprob": 0.0, "top1_hits": 4}] + [{"n": 4, "sum_logprob": -m} for _ in bads]
            if ref is not None:
                targets[0].update(kl_sum=0.0, agree=4)
            rows.append({"id": item["id"], "n_prefix": 3, "targets": targets})
        Path(workdir).mkdir(parents=True, exist_ok=True)
        return rows, {"seconds": 1.0}
    monkeypatch.setattr(score, "run_scorer", fake)


def test_cascade_decides_at_l2_with_a_calibration(tmp_path, monkeypatch):
    probe.write(_pairs(), tmp_path / "probe.jsonl")
    base = config.from_dict({"name": "base", "model": "m", "system": "S"})
    cand = config.from_dict({"name": "cand", "model": "m", "system": "S", "settings": {"api_hints_enabled": True}})
    _fake_scores(monkeypatch, {"base": 1.0, "cand": 3.0})
    cal = calibrate.fit([(1.0, 0.05), (2.0, 0.1), (-1.0, -0.05), (0.5, 0.03)])
    rep = cascade.compare(base, cand, probe_file=tmp_path / "probe.jsonl", workdir=tmp_path / "w", calibration=cal)
    assert rep["kinds"] == ["prompt"] and rep["verdict"] == "BETTER" and rep["decided_at"] == "L2"
    assert rep["layers"]["L2"]["delta"] == pytest.approx(2.0) and rep["predicted_delta"] > 0  # margin 1 -> 3
    assert "Verdict: BETTER" in cascade.markdown(rep)
    nocal = cascade.compare(base, cand, probe_file=tmp_path / "probe.jsonl", workdir=tmp_path / "w2", calibration=None)
    assert nocal["verdict"] == "ESCALATE" and nocal["decided_at"] is None


def test_cascade_same_loop_and_perf_paths(tmp_path, monkeypatch):
    probe.write(_pairs(), tmp_path / "probe.jsonl")
    base = config.from_dict({"name": "base", "model": "m", "system": "S"})
    assert cascade.compare(base, base, probe_file=None, workdir=tmp_path)["verdict"] == "SAME"
    loop = config.from_dict({"name": "loop", "model": "m", "system": "S", "settings": {"slop_check": "repair"}})
    rep = cascade.compare(base, loop, probe_file=tmp_path / "probe.jsonl", workdir=tmp_path / "l")
    assert rep["verdict"] == "ESCALATE" and "agent loop" in rep["notes"][0] and not rep["layers"]
    perf = config.from_dict({"name": "perf", "model": "m", "system": "S", "threads": 12})
    monkeypatch.setattr(equiv, "outputs", lambda cfg, texts, workdir: {"tokens": [[1, 2]] * len(texts), "seconds": 1.0})
    rep = cascade.compare(base, perf, probe_file=tmp_path / "probe.jsonl", workdir=tmp_path / "p")
    assert rep["verdict"] == "SAME" and rep["decided_at"] == "L0" and rep["layers"]["L0"]["prompts"] == 2
    monkeypatch.setattr(equiv, "outputs", lambda cfg, texts, workdir: {
        "tokens": [[1, 2 if cfg.name == "base" else 3]] * len(texts), "seconds": 1.0})
    _fake_scores(monkeypatch, {"base": 1.0, "perf": 1.0})
    rep = cascade.compare(base, perf, probe_file=tmp_path / "probe.jsonl", workdir=tmp_path / "p2")
    assert rep["layers"]["L0"]["verdict"] == "DIFFERENT" and rep["verdict"] == "SAME" and rep["decided_at"] == "L1"


def test_cascade_reuses_identical_baseline_scores(tmp_path, monkeypatch):
    calls = []

    def fake(cfg, items, workdir, *, topk=0, ref=None, log=print):
        calls.append(cfg.name)
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / f"{cfg.name}.scores.jsonl").write_text(json.dumps({"id": "x", "n_prefix": 1, "targets": []}))
        return [{"id": "x", "n_prefix": 1, "targets": []}], {"seconds": 2.0}
    monkeypatch.setattr(score, "run_scorer", fake)
    cfg = config.from_dict({"name": "base", "model": "m", "system": "S"})
    items = [{"id": "x", "prefix": "p", "targets": ["t"]}]
    cascade._cached_scores(cfg, items, tmp_path)
    _, cost = cascade._cached_scores(cfg, items, tmp_path)
    assert calls == ["base"] and cost["cached"] is True
    cascade._cached_scores(cfg, items + items, tmp_path)
    assert calls == ["base", "base"]


def test_cli_probe_writes_a_corpus(tmp_path):
    from star.oracle.__main__ import main
    gold = tmp_path / "bank.jsonl"
    gold.write_text(json.dumps({"id": "gb-ui-one", "request": "Sum a list", "answer": GOOD}) + "\n")
    assert main(["probe", "--gold", str(gold), "--size", "5", "--out", str(tmp_path / "p.jsonl")]) == 0
    pairs = probe.read(tmp_path / "p.jsonl")
    assert len(pairs) == 1 and {"off_by_one", "server_trust"} <= {b["kind"] for b in pairs[0].bads}


def test_futility_stops_only_when_nothing_could_become_significant():
    assert irt.futile(1, 1, 30, 2)                       # 2 more pairs cannot beat 1W/1L
    assert not irt.futile(0, 0, 12, 105)                 # early ties: the noise floor still allows a clear result
    assert not irt.futile(5, 0, 20, 30)
    ties = irt.run_adaptive([f"t{i}" for i in range(40)],
                            lambda t: (True, False) if t in ("t3", "t7") else (True, True))
    assert ties["decision"] == irt.INCONCLUSIVE and ties["stopped"].startswith("futility") and ties["tasks_run"] < 40
