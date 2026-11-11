"""Offline parser tests; no llama.cpp process or network is started."""
import pytest

from star.llama_metrics import (
    compare_llama_cpp_metrics,
    parse_llama_cpp_metrics,
)


def metrics(*, prompt=100, prompt_seconds=10, generated=200, generation_seconds=20,
            processing=1, deferred=2, max_context=4096, decode_calls=50,
            busy=1.5, drafts=100, accepted=60, steps=40, positions=True):
    rows = [
        "# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.",
        "# TYPE llamacpp:prompt_tokens_total counter",
        f"llamacpp:prompt_tokens_total {prompt}",
        f"llamacpp:prompt_seconds_total {prompt_seconds}",
        "llamacpp:prompt_tokens_seconds 20.0",
        f"llamacpp:tokens_predicted_total {generated}",
        f"llamacpp:tokens_predicted_seconds_total {generation_seconds}",
        "llamacpp:predicted_tokens_seconds 30.0",
        f"llamacpp:requests_processing {processing}",
        f"llamacpp:requests_deferred {deferred}",
        f"llamacpp:n_tokens_max {max_context}",
        f"llamacpp:n_decode_total {decode_calls}",
        f"llamacpp:n_busy_slots_per_decode {busy}",
        f"llamacpp:spec_decode_num_draft_tokens_total {drafts}",
        f"llamacpp:spec_decode_num_accepted_tokens_total {accepted}",
        f"llamacpp:spec_decode_num_drafts_total {steps}",
        "unrelated_metric 99",
    ]
    if positions:
        rows.extend([
            'llamacpp:spec_decode_num_accepted_tokens_per_pos_total{position="0"} 50',
            'llamacpp:spec_decode_num_accepted_tokens_per_pos_total{position="1"} 10',
        ])
    return "\n".join(rows)


def test_parser_reads_supported_counters_gauges_and_position_labels():
    snap = parse_llama_cpp_metrics(metrics(), instance_id="server-a", captured_at_ms=1000)
    assert snap.prompt_tokens_total == 100
    assert snap.prompt_seconds_total == 10.0
    assert snap.prompt_tokens_per_second == 20.0
    assert snap.generated_tokens_total == 200
    assert snap.generation_tokens_per_second == 30.0
    assert snap.requests_processing == 1
    assert snap.requests_deferred == 2
    assert snap.max_context_tokens == 4096
    assert snap.decode_calls_total == 50
    assert snap.busy_slots_per_decode == 1.5
    assert snap.speculative_draft_tokens_total == 100
    assert snap.speculative_accepted_tokens_total == 60
    assert snap.speculative_steps_total == 40
    assert snap.accepted_tokens_by_position == ((0, 50), (1, 10))


def test_interval_rates_and_speculative_acceptance_are_derived_from_counter_deltas():
    before = parse_llama_cpp_metrics(metrics(), instance_id="server-a", captured_at_ms=1000)
    after = parse_llama_cpp_metrics(
        metrics(prompt=140, prompt_seconds=12, generated=260, generation_seconds=22,
                processing=2, deferred=3, max_context=8192, decode_calls=60,
                drafts=150, accepted=90, steps=60),
        instance_id="server-a", captured_at_ms=3000,
    )
    report = compare_llama_cpp_metrics(before, after)
    assert report.elapsed_ms == 2000
    assert report.prompt_tokens_per_second == 20.0
    assert report.generated_tokens_per_second == 30.0
    assert report.prefill_compute_tokens_per_second == 20.0
    assert report.decode_compute_tokens_per_second == 30.0
    assert report.speculative_draft_acceptance_percent == 60.0
    assert report.speculative_accepted_tokens_per_step == 1.5
    assert report.speculative_steps_per_second == 10.0
    assert report.decode_calls_per_second == 5.0
    assert report.accepted_tokens_by_position_delta == ((0, 0), (1, 0))
    assert report.requests_processing == 2
    assert report.requests_deferred == 3
    assert report.max_context_tokens == 8192
    assert report.counter_resets == ()


def test_counter_resets_never_create_negative_or_fabricated_rates():
    before = parse_llama_cpp_metrics(metrics(prompt=100, generated=200),
                                     instance_id="server-a", captured_at_ms=1000)
    after = parse_llama_cpp_metrics(metrics(prompt=5, generated=260),
                                    instance_id="server-a", captured_at_ms=3000)
    report = compare_llama_cpp_metrics(before, after)
    assert report.prompt_tokens_per_second is None
    assert "prompt_tokens_total" in report.counter_resets
    assert report.generated_tokens_per_second == 30.0


def test_different_server_epoch_and_reversed_clock_are_rejected():
    first = parse_llama_cpp_metrics(metrics(), instance_id="server-a", captured_at_ms=1000)
    restarted = parse_llama_cpp_metrics(metrics(), instance_id="server-b", captured_at_ms=2000)
    with pytest.raises(ValueError, match="different server instances"):
        compare_llama_cpp_metrics(first, restarted)
    earlier = parse_llama_cpp_metrics(metrics(), instance_id="server-a", captured_at_ms=900)
    with pytest.raises(ValueError, match="later"):
        compare_llama_cpp_metrics(first, earlier)


@pytest.mark.parametrize("bad", [
    "llamacpp:prompt_tokens_total NaN",
    "llamacpp:prompt_tokens_total +Inf",
    "llamacpp:prompt_tokens_total -1",
    "llamacpp:prompt_tokens_total 1.5",
    "llamacpp:prompt_tokens_total 1\nllamacpp:prompt_tokens_total 2",
    'llamacpp:prompt_tokens_total{model="a"} 1',
    'llamacpp:spec_decode_num_accepted_tokens_per_pos_total{position="999"} 1',
    'llamacpp:spec_decode_num_accepted_tokens_per_pos_total{position="0",position="1"} 1',
    'llamacpp:spec_decode_num_accepted_tokens_per_pos_total{position="0",other="x"} 1',
])
def test_malformed_or_ambiguous_known_metrics_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_llama_cpp_metrics(bad, instance_id="server-a", captured_at_ms=1000)


def test_parser_bounds_input_and_rejects_empty_or_wrong_payloads():
    with pytest.raises(ValueError):
        parse_llama_cpp_metrics("# only comments", instance_id="server-a", captured_at_ms=1000)
    with pytest.raises(ValueError):
        parse_llama_cpp_metrics("x" * 256_001, instance_id="server-a", captured_at_ms=1000)
    with pytest.raises(ValueError):
        parse_llama_cpp_metrics("llamacpp:prompt_tokens_total 1\n" + ("#x\n" * 2048),
                                instance_id="server-a", captured_at_ms=1000)
    with pytest.raises(ValueError):
        parse_llama_cpp_metrics("llamacpp:prompt_tokens_total " + ("1" * 5000),
                                instance_id="server-a", captured_at_ms=1000)


def test_speculative_acceptance_anomaly_is_reported_not_clamped():
    before = parse_llama_cpp_metrics(metrics(drafts=10, accepted=5),
                                     instance_id="server-a", captured_at_ms=1000)
    after = parse_llama_cpp_metrics(metrics(drafts=20, accepted=20),
                                    instance_id="server-a", captured_at_ms=2000)
    report = compare_llama_cpp_metrics(before, after)
    assert report.speculative_draft_acceptance_percent is None
    assert report.anomalies == ("accepted_speculative_tokens_exceed_draft_tokens",)
