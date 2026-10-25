"""W1 statistical gate v2: paired statistics (star/eval_stats.py) and the paired-session mode of star/eval_gate.py.
Synthetic data only; no model, no network."""
import json
from pathlib import Path

import pytest

from star import eval_gate as gate
from star import eval_stats as s


def arm(passes: dict) -> dict:
    """{task: "PPF"} -> {task: [True, True, False]} ('E' = errored sample)."""
    return {t: [{"P": True, "F": False, "E": None}[c] for c in row] for t, row in passes.items()}


# --- exact pieces ---------------------------------------------------------------------------------------------

def test_exact_sign_test_values():
    assert s.sign_test(4, 0)["p_better"] == pytest.approx(1 / 16)
    assert s.sign_test(5, 0)["p_better"] == pytest.approx(1 / 32)
    assert s.sign_test(9, 4)["p_better"] == pytest.approx(1093 / 8192)
    assert s.sign_test(0, 6)["p_worse"] == pytest.approx(1 / 64)
    assert s.sign_test(0, 0) == {"n": 0, "p_better": 1.0, "p_worse": 1.0, "p_two_sided": 1.0}
    assert s.sign_test(3, 3)["p_two_sided"] == 1.0
    with pytest.raises(ValueError):
        s.sign_test(-1, 2)


def test_critical_wins_and_the_smallest_resolvable_number_of_pairs():
    assert s.min_resolvable_pairs(0.05) == 5
    assert [s.critical_wins(d) for d in range(5)] == [None] * 5
    assert s.critical_wins(5) == 5 and s.critical_wins(10) == 9 and s.critical_wins(20) == 15


def test_wilson_interval_and_flip_probability():
    lo, hi = s.wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert s.wilson_interval(0, 10)[0] == 0.0 and s.wilson_interval(0, 0) == (0.0, 1.0)
    f = s.flip_probability(1 / 6)
    assert 2 * f * (1 - f) == pytest.approx(1 / 6) and 0.09 < f < 0.095
    with pytest.raises(ValueError):
        s.flip_probability(0.7)


# --- the cases that motivated W1 ------------------------------------------------------------------------------

def test_the_observed_3_to_7_of_12_swing_is_not_enough_power_in_either_direction():
    base = {f"V{i}": [i < 3] for i in range(12)}
    cand = {f"V{i}": [i < 7] for i in range(12)}
    up = s.paired_decision(base, cand)
    assert up.decision == s.UNDERPOWERED and not up.promote
    assert "not enough power" in up.text() and up.power_at_smallest < 0.8
    assert (up.wins, up.losses, up.baseline_pass, up.candidate_pass) == (4, 0, 3, 7)
    assert up.p_better == pytest.approx(1 / 16) and up.mde["effect_tasks"] == 8
    assert "MDE" in up.text() and "+8 of 12" in up.text()
    down = s.paired_decision(cand, base)
    assert down.decision == s.UNDERPOWERED                    # and never a retirement on noise
    # The same totals arranged less favourably (some tasks swap) are inconclusive too.
    mixed = {f"V{i}": [i in (0, 1, 2, 3, 4, 5, 8)] for i in range(12)}
    assert s.paired_decision(base, mixed).decision == s.UNDERPOWERED


def test_the_unchanged_night_school_slice_series_never_decides():
    series = [6, 5, 6, 7, 5]                                  # with zero to two lessons, read on 12 tasks
    for a in series:
        for b in series:
            base = {f"V{i}": [i < a] for i in range(12)}
            cand = {f"V{i}": [i < b] for i in range(12)}
            assert s.paired_decision(base, cand).decision == s.UNDERPOWERED


def test_a_clear_improvement_promotes_and_a_clear_loss_rejects():
    base = arm({f"T{i}": "FF" if i < 6 else "PP" for i in range(12)})
    cand = arm({f"T{i}": "PP" for i in range(12)})
    win = s.paired_decision(base, cand)
    assert win.decision == s.PROMOTE and win.promote and (win.wins, win.losses, win.ties) == (12, 0, 12)
    assert sorted(win.improvements) == [f"T{i}" for i in range(6)]
    loss = s.paired_decision(cand, base)
    assert loss.decision == s.REJECT and sorted(loss.regressions) == [f"T{i}" for i in range(6)]


# --- regressions, canaries, incomplete input ------------------------------------------------------------------

def test_regression_means_fails_two_of_three_and_one_failure_is_only_unconfirmed():
    assert s.is_regression([True] * 3, [False, False, True]) == "confirmed"
    assert s.is_regression([True] * 3, [False, True, True]) == "unconfirmed"
    assert s.is_regression([True], [False]) == "unconfirmed"            # k = 1 can never confirm
    assert s.is_regression([True, True], [False, False]) == "confirmed"
    assert s.is_regression([False, False, True], [False, False, False]) == ""   # the baseline did not pass
    assert s.is_regression([True] * 3, [True] * 3) == ""


def test_a_reproducible_canary_failure_vetoes_an_otherwise_significant_win():
    rows = {f"T{i}": ("FFF", "PPP") for i in range(8)}
    rows["CAN"] = ("PPP", "FFP")
    base = arm({t: b for t, (b, _c) in rows.items()})
    cand = arm({t: c for t, (_b, c) in rows.items()})
    assert s.paired_decision(base, cand).decision == s.PROMOTE           # not a canary: 24 wins outweigh it
    vetoed = s.paired_decision(base, cand, canary={"CAN"})
    assert vetoed.decision == s.REJECT and vetoed.canary_vetoes == ["CAN"]
    rows["CAN"] = ("PPP", "FPP")                                         # one failure: rerun first
    base = arm({t: b for t, (b, _c) in rows.items()})
    cand = arm({t: c for t, (_b, c) in rows.items()})
    held = s.paired_decision(base, cand, canary={"CAN"})
    assert held.decision == s.INCONCLUSIVE and "rerun" in " ".join(held.notes)


def test_a_task_without_a_complete_pair_gives_no_verdict():
    base = arm({f"T{i}": "FF" for i in range(10)} | {"X": "EE"})
    cand = arm({f"T{i}": "PP" for i in range(10)} | {"X": "PP"})
    report = s.paired_decision(base, cand)
    assert report.decision == s.INCOMPLETE and report.incomplete == ["X"] and not report.promote
    only_one_arm = s.paired_decision({"A": [True]}, {"A": [True], "B": [True]})
    assert only_one_arm.decision == s.INCOMPLETE and only_one_arm.incomplete == ["B"]
    with pytest.raises(ValueError):
        s.paired_decision({"A": ["pass"]}, {"A": [True]})
    with pytest.raises(ValueError):
        s.paired_decision({"A": [True]}, {"A": [True]}, method="vibes")


def test_uneven_sample_counts_are_paired_in_order_and_noted():
    report = s.paired_decision({"A": [True, False, True]}, {"A": [True, True]})
    assert (report.wins, report.losses, report.ties, report.samples) == (1, 0, 1, 2)
    assert any("paired" in n for n in report.notes)


# --- determinism, bootstrap -----------------------------------------------------------------------------------

def test_bootstrap_is_deterministic_for_a_seed_and_the_bootstrap_method_decides():
    diffs = [1.0, 0.5, 0.0, 0.0, -0.5, 1.0, 0.0, 0.5]
    assert s.bootstrap_ci(diffs, seed=7) == s.bootstrap_ci(diffs, seed=7)
    lo, hi = s.bootstrap_ci(diffs, seed=7)
    assert lo <= sum(diffs) / len(diffs) <= hi
    assert s.bootstrap_ci([], seed=1) == (0.0, 0.0)
    base = arm({f"T{i}": "FF" if i < 6 else "PP" for i in range(12)})
    cand = arm({f"T{i}": "PP" for i in range(12)})
    one = s.paired_decision(base, cand, method="bootstrap", seed=3)
    assert one.decision == s.PROMOTE and one.ci_low > 0
    assert one.to_dict() == s.paired_decision(base, cand, method="bootstrap", seed=3).to_dict()
    assert s.paired_decision(cand, base, method="bootstrap", seed=3).decision == s.REJECT


# --- power, MDE and the pre-registered simulation (W1 acceptance test 1) --------------------------------------

def test_mde_for_the_task_counts_in_use():
    m12 = s.minimum_detectable_effect(12, 1)
    m24 = s.minimum_detectable_effect(24, 2)
    assert m12.effect_tasks == 8 and m24.effect_tasks == 6
    assert m24.power_at_effect >= 0.8 and s.power(24, 2, m24.effect_tasks - 1) < 0.8
    assert m12.net_wins_needed == 5
    assert s.minimum_detectable_effect(3, 1).effect_tasks is None          # too few tasks for any verdict
    assert "ESTIMATE" in m24.text() and "+6 of 24" in m24.text()


def test_simulation_false_promotion_is_at_most_5_percent_and_a_real_6_of_24_effect_is_found_70_percent():
    null = s.simulate(24, 2, 0, runs=1000, seed=11)
    assert null[s.PROMOTE] <= 0.05 and null[s.REJECT] <= 0.05
    real = s.simulate(24, 2, 6, runs=1000, seed=12)
    assert real[s.PROMOTE] >= 0.70 and real[s.REJECT] == 0.0
    assert real[s.PROMOTE] == pytest.approx(s.power(24, 2, 6), abs=0.05)   # the exact power matches the simulation
    assert s.simulate(24, 2, 6, runs=50, seed=12) == s.simulate(24, 2, 6, runs=50, seed=12)


def test_simulation_of_the_old_single_run_12_task_rule_is_a_coin_flip():
    """The rule W1 replaces: 'with lesson >= without lesson' on 12 tasks, one run each, promotes on no effect."""
    import random
    rng, f, promoted = random.Random(5), s.flip_probability(1 / 6), 0
    for _ in range(1000):
        truth = [i < 6 for i in range(12)]
        base = sum((rng.random() >= f) == t for t in truth)
        cand = sum((rng.random() >= f) == t for t in truth)
        promoted += cand >= base
    assert promoted / 1000 > 0.5
    assert s.simulate(12, 1, 0, runs=1000, seed=5)[s.PROMOTE] <= 0.05


# --- the paired-session mode of the evaluation gate -----------------------------------------------------------

def result(statuses: dict, *, started="2026-10-13T01:00:00+00:00", finished="2026-10-13T02:00:00+00:00",
           grader="grader", commit="commit") -> dict:
    ids = sorted(statuses)
    return {"schema": 1, "suite": {"sha256": "s1", "file": "suite.json", "tasks_total": len(ids), "automated": len(ids),
                                   "selected": ids, "identity_sha256": "identity"},
            "run": {"model": "star-fast", "mode": "auto", "app_commit": commit, "grader_sha256": grader,
                    "started_at": started, "finished_at": finished},
            "tasks": {tid: {"status": st, **({"passed": st == "pass", "checks": [], "reasons": []}
                                             if st in ("pass", "fail") else {})} for tid, st in statuses.items()}}


def at(hour: int) -> dict:
    return {"started": f"2026-10-13T{hour:02d}:00:00+00:00", "finished": f"2026-10-13T{hour:02d}:30:00+00:00"}


BASE = {f"T{i}": "fail" if i < 6 else "pass" for i in range(12)}
BETTER = {f"T{i}": "pass" for i in range(12)}


def test_paired_session_allows_only_a_significant_improvement():
    v = gate.compare_paired([result(BASE, **at(1)), result(BASE, **at(4))],
                            [result(BETTER, **at(2)), result(BETTER, **at(3))])
    assert v.code == gate.ALLOWED and v.allowed and v.paired["decision"] == "PROMOTE"
    assert v.paired["wins"] == 12 and v.compared == 12 and "paired session" in v.text() and "MDE" in v.text()
    assert v.to_dict()["paired"]["k"] == 2


def test_paired_session_without_power_is_exit_5_and_never_allowed():
    small = dict(BASE, T0="pass", T1="pass")                     # +2 tasks: below the noise floor
    v = gate.compare_paired([result(BASE, **at(1))], [result(small, **at(2))])
    assert v.code == gate.UNDERPOWERED == 5 and not v.allowed and "NOT ENOUGH POWER" in v.text()
    assert v.paired["decision"] == "UNDERPOWERED"


def test_paired_session_blocks_a_significant_loss_and_names_the_regressions():
    v = gate.compare_paired([result(BETTER, **at(1)), result(BETTER, **at(4))],
                            [result(BASE, **at(2)), result(BASE, **at(3))])
    assert v.code == gate.BLOCKED and sorted(v.regressions) == [f"T{i}" for i in range(6)]


def test_paired_session_refuses_stored_baselines_other_sessions_and_unlike_runs():
    shipped = Path(gate.__file__).resolve().parents[1] / "evals" / "results" / "baseline-v2.json"
    if shipped.is_file():
        v = gate.evaluate_paired([shipped], [result(BETTER)])
        assert v.code == gate.UNUSABLE and any("legacy" in n for n in v.notes)
    far = {"started": "2026-10-15T01:00:00+00:00", "finished": "2026-10-15T02:00:00+00:00"}
    assert gate.compare_paired([result(BASE)], [result(BETTER, **far)]).code == gate.UNUSABLE
    no_time = result(BETTER)
    del no_time["run"]["started_at"]
    assert gate.compare_paired([result(BASE)], [no_time]).code == gate.UNUSABLE
    assert gate.compare_paired([result(BASE)], [result(BETTER, grader="other")]).code == gate.UNUSABLE
    assert gate.compare_paired([], [result(BETTER)]).code == gate.UNUSABLE


def test_paired_session_notes_blocks_and_errored_tasks_make_it_incomplete():
    v = gate.compare_paired([result(BASE, **at(1)), result(BASE, **at(2))],
                            [result(BETTER, **at(3)), result(BETTER, **at(4))])
    assert v.allowed and any("blocks" in n for n in v.notes)
    errored = dict(BETTER, T0="error")
    w = gate.compare_paired([result(BASE, **at(1))], [result(errored, **at(2))])
    assert w.code == gate.INCOMPLETE and w.incomplete == ["T0"]


def test_gate_paired_runs_both_arms_interleaved():
    order = []

    def run_base(j):
        order.append(("B", j))
        return result(BASE, **at(1 + 2 * j))

    def run_cand(j):
        order.append(("C", j))
        return result(BETTER, **at(2 + 2 * j))
    v = gate.gate_paired(run_base, run_cand, samples=3)
    assert order == [("B", 0), ("C", 0), ("C", 1), ("B", 1), ("B", 2), ("C", 2)]
    assert v.allowed and v.paired["k"] == 3


def test_gate_cli_paired_session_json_and_exit_codes(tmp_path, capsys):
    files = {}
    for name, statuses, hour in (("b1", BASE, 1), ("c1", BETTER, 2), ("c2", BETTER, 3), ("b2", BASE, 4)):
        files[name] = tmp_path / f"{name}.json"
        files[name].write_text(json.dumps(result(statuses, **at(hour))), encoding="utf-8")
    code = gate.main(["--paired-session", "--baseline", str(files["b1"]), str(files["b2"]),
                      "--candidate", str(files["c1"]), str(files["c2"]), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["paired"]["decision"] == "PROMOTE" and out["allowed"]
    assert gate.main(["--paired-session", "--baseline", str(files["b1"]), "--candidate", str(files["b2"])]) == gate.UNDERPOWERED
    with pytest.raises(SystemExit):
        gate.main(["--baseline", str(files["b1"]), str(files["b2"]), "--candidate", str(files["c1"])])
    capsys.readouterr()
    assert gate.main(["--baseline", str(files["b1"]), "--candidate", str(files["c1"])]) == gate.ALLOWED
    assert "legacy single-run gate" in capsys.readouterr().out


# --- power: "not enough power" versus a powered null ----------------------------------------------------------

def test_a_powered_null_is_inconclusive_and_a_small_set_is_underpowered():
    big_base = {f"T{i}": [i % 2 == 0] for i in range(400)}
    big_cand = dict(big_base)
    for i in range(10):                       # 10 wins and 10 losses: no effect, on a set powered for +10 %
        big_cand[f"T{2 * i}"] = [False]
        big_cand[f"T{2 * i + 1}"] = [True]
    powered = s.paired_decision(big_base, big_cand)
    assert powered.decision == s.INCONCLUSIVE and powered.power_at_smallest >= 0.8
    assert "unlikely" in " ".join(powered.notes)
    small = s.paired_decision({k: big_base[k] for k in list(big_base)[:30]}, {k: big_cand[k] for k in list(big_base)[:30]})
    assert small.decision == s.UNDERPOWERED and "tasks at k=1" in " ".join(small.notes)
    stricter = s.paired_decision(big_base, big_cand, smallest_effect=0.03)
    assert stricter.decision == s.UNDERPOWERED                 # 400 tasks cannot resolve +3 % at k=1


def test_tasks_needed_matches_the_exact_power_model():
    need = s.tasks_needed(0.10, 1)
    assert 180 <= need <= 240
    assert s.power(need, 1, -(-need // 10)) == pytest.approx(0.8, abs=0.06)
    assert s.tasks_needed(0.10, 2) < need and s.tasks_needed(0.05, 1) > 3 * need
    assert s.tasks_needed(0, 1) is None


def test_sensitive_pool_keeps_only_tasks_that_varied_in_screening():
    screening = {"A": [True, True], "B": [False, False], "C": [True, False], "D": [True], "E": [None, True, False]}
    assert s.sensitive_tasks(screening) == ["C", "D", "E"]


def test_gate_decides_on_the_sensitive_pool_from_separate_runs(tmp_path):
    files = {}
    for name, statuses, hour in (("s1", dict(BASE, T0="pass"), 1), ("s2", BASE, 2), ("b", BASE, 3), ("c", BETTER, 4)):
        files[name] = tmp_path / f"{name}.json"
        files[name].write_text(json.dumps(result(statuses, **at(hour))), encoding="utf-8")
    pool = s.sensitive_tasks(gate.screening_samples([gate.load_result(files["s1"]), gate.load_result(files["s2"])]))
    assert pool == ["T0"]
    v = gate.evaluate_paired([files["b"]], [files["c"]], pool=pool)
    assert v.compared == 1 and any("sensitive task pool: 1 of 12" in n for n in v.notes)
    with pytest.raises(SystemExit):
        gate.main(["--paired-session", "--baseline", str(files["b"]), "--candidate", str(files["c"]),
                   "--pool-from", str(files["b"])])
