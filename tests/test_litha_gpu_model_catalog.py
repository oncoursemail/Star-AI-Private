import pytest
from litha.gpu_model_catalog import CATALOG, ORDERS, main, plan


def test_vision_cannot_route_to_text_only_lfm():
    report = plan(free_vram_mib=7500, workload="vision")
    assert all(x["vision"] for x in report["candidates"])
    assert not any("lfm" in x["tag"] for x in report["candidates"])


def test_streaming_prefers_compact_model_even_if_9b_eligible():
    report = plan(free_vram_mib=8192, workload="gaming")
    assert report["recommended_experiment_candidate"] == "qwen3.5:4b-q4_K_M"
    assert report["gpu_fit_verified"] is False


def test_quality_does_not_force_tight_9b_into_gpu():
    report = plan(free_vram_mib=7000, reserve_mib=1024, workload="quality")
    assert report["candidates"][0]["tag"] == "qwen3.5:9b-q4_K_M"
    assert report["candidates"][0]["status"] == "outside_provisional_budget"
    assert report["recommended_experiment_candidate"] != "qwen3.5:9b-q4_K_M"


def test_no_free_space_is_explicit_and_not_fake():
    report = plan(free_vram_mib=0)
    assert report["recommended_experiment_candidate"] is None
    assert all(x["status"] == "outside_provisional_budget" for x in report["candidates"])


def test_lower_bound_and_units_are_explicit():
    report = plan(free_vram_mib=8192, workload="quality")
    assert report["candidates"][0]["approx_weight_size_mib"] >= 6200
    assert "NOT peak VRAM" in report["limitations"]
    assert CATALOG["qwen3.5:4b-q8_0"].published_size_gb == 5.2


@pytest.mark.parametrize("args", [
    {"free_vram_mib": -1}, {"free_vram_mib": True}, {"free_vram_mib": 1024.0},
    {"free_vram_mib": 999999}, {"free_vram_mib": 100, "reserve_mib": 128},
    {"free_vram_mib": 1024, "reserve_mib": True},
    {"free_vram_mib": 1024, "workload": "forgotten"},
])
def test_invalid_inputs_rejected(args):
    with pytest.raises(ValueError):
        plan(**args)


def test_all_candidate_orders_reference_known_models():
    assert all(key in CATALOG for order in ORDERS.values() for key in order)


def test_cli_does_not_query_gpu_or_download(tmp_path, capsys):
    assert main(["--free-vram-mib", "6500", "--workload", "tools"]) == 0
    output = capsys.readouterr().out
    assert "candidate_needs_live_fit_test" in output
