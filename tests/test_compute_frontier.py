"""Unit tests for STAR's offline measured compute frontier."""
import json
from pathlib import Path

import pytest

from star.compute_frontier import _reading, compare, load_bench, main


def row(threads, *, pp=512, tg=0, speed=100, noise=1, **extra):
    return {
        "build_commit": "test-revision", "cpu_info": "test 24 core CPU",
        "gpu_info": "test GPU", "backends": "CPU", "model_filename": "test-model.gguf",
        "model_type": "Q4_K_M", "model_size": 1234567, "model_n_params": 3000000000,
        "type_k": "f16", "type_v": "f16", "n_prompt": pp, "n_gen": tg, "n_depth": 0,
        "n_threads": threads, "n_batch": 512, "n_ubatch": 512, "n_gpu_layers": 0,
        "avg_ts": speed, "stddev_ts": noise, **extra,
    }


def paired(threads, *, pp=100, tg=20, noise=0.5, **extra):
    return [_reading(row(threads, pp=512, tg=0, speed=pp, noise=noise, **extra)),
            _reading(row(threads, pp=0, tg=128, speed=tg, noise=noise / 5, **extra))]


def test_winner_has_both_workloads_and_conservative_improvement():
    result = compare(paired(24), paired(16, pp=120, tg=24))
    assert result["candidate_count"] == 1
    item = result["candidates"][0]
    assert item["flags"]["n_threads"] == 16
    assert item["workloads_compared"] == 2
    assert item["benchmark_speed_ratio"] == 1.2
    assert item["verdict"] == "worth_latency_and_quality_gates"
    assert "No quality" in result["limitations"]


def test_candidate_can_be_faster_on_average_but_noisy():
    result = compare(paired(24), paired(16, pp=120, tg=24, noise=15))
    assert result["candidates"][0]["verdict"] == "retest_variability"


def test_reject_throughput_regression_even_if_other_workload_wins():
    result = compare(paired(24), paired(16, pp=150, tg=17))
    assert result["candidates"][0]["verdict"] == "throughput_regression"


def test_baseline_row_is_not_a_new_candidate():
    result = compare(paired(24), paired(24) + paired(16, pp=125, tg=25))
    assert result["candidate_count"] == 1


def test_require_fair_identity_and_unique_baseline():
    with pytest.raises(ValueError, match="Refusing incomparable"):
        compare(paired(24), [_reading(row(16, model_filename="wrong.gguf"))])
    with pytest.raises(ValueError, match="Baseline must"):
        compare(paired(24) + paired(20), paired(16))


def test_incomplete_and_duplicate_workloads_do_not_get_selected():
    result = compare(paired(24), paired(16)[:1])
    assert result["candidates"][0]["verdict"] == "incomplete_workloads"
    with pytest.raises(ValueError, match="Duplicate"):
        compare(paired(24), paired(16) + paired(16))


def test_memory_budget_is_fail_closed_when_available():
    missing = compare(paired(24), paired(16, pp=120, tg=24), max_vram_mib=7000)
    assert missing["candidates"][0]["verdict"] == "needs_peak_memory_measurement"
    over = compare(paired(24), paired(16, pp=120, tg=24, peak_vram_mib=7300),
                   max_vram_mib=7000)
    assert over["candidates"][0]["verdict"] == "exceeds_memory_budget"
    accepted = compare(paired(24), paired(16, pp=120, tg=24, peak_vram_mib=6300),
                       max_vram_mib=7000)
    assert accepted["candidates"][0]["verdict"] == "worth_latency_and_quality_gates"


@pytest.mark.parametrize("field,bad", [
    ("avg_ts", 0), ("avg_ts", True), ("stddev_ts", -1),
    ("n_prompt", -5), ("model_filename", None),
    ("avg_ts", float("nan")), ("stddev_ts", float("inf")),
])
def test_bad_metrics_and_identity_are_not_interpreted_as_speed(field, bad):
    value = row(24)
    value[field] = bad
    with pytest.raises(ValueError):
        _reading(value)


def test_json_and_jsonl_inputs_and_cli(tmp_path, capsys):
    baseline, candidates = tmp_path / "baseline.json", tmp_path / "candidates.jsonl"
    current = [row(24, speed=100), row(24, pp=0, tg=128, speed=20)]
    new = [row(16, speed=130), row(16, pp=0, tg=128, speed=26)]
    baseline.write_text(json.dumps(current), encoding="utf-8")
    candidates.write_text("\n".join(json.dumps(x) for x in new) + "\n", encoding="utf-8")
    assert len(load_bench(baseline)) == 2
    assert len(load_bench(candidates)) == 2
    assert main([str(baseline), str(candidates)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["candidates"][0]["verdict"] == "worth_latency_and_quality_gates"


def test_missing_unbounded_or_symlink_input_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_bench(tmp_path / "missing.json")
    p = tmp_path / "big.json"
    p.write_text("x" * 4_000_001)
    with pytest.raises(ValueError, match="4 MB"):
        load_bench(p)
    original = tmp_path / "ordinary.json"
    original.write_text(json.dumps(row(24)))
    alias = tmp_path / "alias.json"
    alias.symlink_to(original)
    with pytest.raises(ValueError, match="ordinary"):
        load_bench(alias)
