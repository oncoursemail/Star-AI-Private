"""Innovation review over eval-runner result files: quality from the eval gate, time from recorded task seconds."""
import json

from star import evals, innovation_gate as ig
from tests.test_eval_stats import BASE, BETTER, at, result


def timed(statuses: dict, seconds: float, hour: int) -> dict:
    run = result(statuses, **at(hour))
    for row in run["tasks"].values():
        row["seconds"] = seconds
    return run


def arms(base_statuses, cand_statuses, base_s, cand_s):
    return ([timed(base_statuses, base_s, 1), timed(base_statuses, base_s, 4)],
            [timed(cand_statuses, cand_s, 2), timed(cand_statuses, cand_s, 3)])


def test_speed_change_needs_a_significant_saving_and_no_quality_regression():
    report = ig.review(*arms(BETTER, BETTER, 10.0, 7.0), objective="speed")
    assert report["recommendation"] == ig.REVIEW
    assert report["quality"]["paired"]["decision"] in ("INCONCLUSIVE", "UNDERPOWERED")   # same answers: no quality verdict either way
    assert report["time"]["faster"] == 12 and report["time"]["change"] == -0.3
    assert ig.review(*arms(BETTER, BETTER, 10.0, 9.5), objective="speed")["recommendation"] == ig.MORE
    assert ig.review(*arms(BETTER, BETTER, 10.0, 12.0), objective="speed")["recommendation"] == ig.REJECT
    assert ig.review(*arms(BETTER, BASE, 10.0, 5.0), objective="speed")["recommendation"] == ig.REJECT


def test_quality_gain_is_rejected_when_it_costs_too_much_time():
    assert ig.review(*arms(BASE, BETTER, 10.0, 11.0))["recommendation"] == ig.REVIEW
    slow = ig.review(*arms(BASE, BETTER, 10.0, 13.0))
    assert slow["recommendation"] == ig.REJECT and "slower" in slow["reason"]
    small = dict(BASE, T0="pass", T1="pass")
    assert ig.review(*arms(BASE, small, 10.0, 10.0))["recommendation"] == ig.MORE


def test_unusable_or_untimed_runs_give_no_recommendation():
    base, cand = arms(BASE, BETTER, 10.0, 10.0)
    cand[0]["suite"]["sha256"] = "other-suite"
    assert ig.review(base, cand)["recommendation"] == ig.INVALID
    untimed = ig.review([result(BETTER, **at(1))], [result(BETTER, **at(2))], objective="speed")
    assert untimed["recommendation"] == ig.MORE and untimed["time"]["tasks"] == 0


def test_cli_reads_runner_files_through_star_evals(tmp_path, capsys):
    base, cand = arms(BETTER, BETTER, 10.0, 7.0)
    paths = []
    for name, run in (("b1", base[0]), ("b2", base[1]), ("c1", cand[0]), ("c2", cand[1])):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(run), encoding="utf-8")
        paths.append(str(path))
    code = evals.main(["innovation", "--objective", "speed", "--baseline", *paths[:2], "--candidate", *paths[2:]])
    out = capsys.readouterr().out
    assert code == 0 and out.startswith("innovation review (speed): review_candidate")
    assert "paired gate:" in out and "120.0 s -> 84.0 s" in out
    code = evals.main(["innovation", "--json", "--baseline", *paths[2:], "--candidate", *paths[:2]])
    assert code == 1 and json.loads(capsys.readouterr().out)["recommendation"] == ig.REJECT
    assert evals.main(["innovation", "--baseline", str(tmp_path / "missing.json"), "--candidate", paths[2]]) == 2
