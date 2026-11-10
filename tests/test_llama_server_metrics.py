from __future__ import annotations

from typing import Any
from urllib.error import HTTPError

import pytest

from star.llama_server_metrics import (
    MAX_METRICS_BYTES,
    LlamaMetricsSnapshot,
    MetricsParseError,
    MetricsUnavailable,
    capture_window,
    compare_snapshots,
    fetch_metrics,
    metrics_url,
    parse_metrics,
)

SAMPLE = """# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 100
llamacpp:prompt_seconds_total 2.0
llamacpp:prompt_tokens_seconds 50
llamacpp:tokens_predicted_total 80
llamacpp:tokens_predicted_seconds_total 4
llamacpp:predicted_tokens_seconds 20
llamacpp:requests_processing 0
llamacpp:requests_deferred 0
llamacpp:n_tokens_max 2048
llamacpp:n_decode_total 60
llamacpp:n_busy_slots_per_decode 1.25
llamacpp:spec_decode_num_draft_tokens_total 40
llamacpp:spec_decode_num_accepted_tokens_total 30
llamacpp:spec_decode_num_drafts_total 12
unknown_metric 99
"""


def test_parse_documented_metrics_and_ignore_unknown_and_comments():
    snapshot = parse_metrics(SAMPLE, captured_ns=123)
    assert snapshot.captured_ns == 123
    assert snapshot.get("llamacpp:prompt_tokens_total") == 100
    assert snapshot.get("llamacpp:requests_processing") == 0
    assert snapshot.get("unknown_metric") is None
    assert len(snapshot.values) == 14


def test_parse_ignores_labelled_series_instead_of_guessing_aggregation():
    snapshot = parse_metrics(
        'llamacpp:prompt_tokens_total{model="a"} 10\n'
        'llamacpp:prompt_tokens_total{model="b"} 20\n'
        'llamacpp:tokens_predicted_total 5\n',
        captured_ns=1,
    )
    assert snapshot.get("llamacpp:prompt_tokens_total") is None
    assert snapshot.get("llamacpp:tokens_predicted_total") == 5


@pytest.mark.parametrize("value", ["NaN", "+Inf", "-Inf", "-1", "1e309"])
def test_parse_rejects_nonfinite_or_negative_supported_values(value: str):
    with pytest.raises(MetricsParseError):
        parse_metrics(f"llamacpp:prompt_tokens_total {value}\n")


def test_parse_rejects_duplicate_supported_metrics():
    with pytest.raises(MetricsParseError, match="duplicate"):
        parse_metrics("llamacpp:prompt_tokens_total 1\nllamacpp:prompt_tokens_total 2\n")


def test_parse_rejects_malformed_supported_metric_but_ignores_unknown_lines():
    with pytest.raises(MetricsParseError, match="malformed"):
        parse_metrics("llamacpp:prompt_tokens_total nope extra\n")
    snapshot = parse_metrics("not a prometheus sample\nllamacpp:tokens_predicted_total 1\n")
    assert snapshot.get("llamacpp:tokens_predicted_total") == 1


def test_parse_enforces_byte_line_and_nul_bounds():
    with pytest.raises(MetricsParseError, match="size limit"):
        parse_metrics("x" * (MAX_METRICS_BYTES + 1))
    with pytest.raises(MetricsParseError, match="line limit"):
        parse_metrics("\n".join(["# comment"] * 2049))
    with pytest.raises(MetricsParseError, match="NUL"):
        parse_metrics("llamacpp:prompt_tokens_total 1\x00\n")


def test_metrics_url_is_loopback_only_and_encodes_router_model():
    assert metrics_url("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080/metrics"
    assert metrics_url("http://localhost:8080/v1/", model="star-fast") == (
        "http://localhost:8080/metrics?model=star-fast"
    )
    assert metrics_url("http://127.0.0.1:8080/v1", model="star-fast/v2") == (
        "http://127.0.0.1:8080/metrics?model=star-fast%2Fv2"
    )


@pytest.mark.parametrize("endpoint", [
    "https://127.0.0.1:8080/v1",
    "http://example.com:8080/v1",
    "http://127.0.0.1:8080/v1?token=secret",
    "http://user:pass@127.0.0.1:8080/v1",
    "http://127.0.0.1:8080/metrics",
    "http://127.0.0.1:8080/v1#fragment",
    "http://127.0.0.1:99999/v1",
    "http://127.0.0.1:1/v1",
])
def test_metrics_url_rejects_non_loopback_or_malformed_endpoints(endpoint: str):
    with pytest.raises(ValueError):
        metrics_url(endpoint)


def test_metrics_url_rejects_empty_model_query():
    with pytest.raises(ValueError):
        metrics_url("http://127.0.0.1:8080/v1", model="")


def test_compare_snapshots_calculates_prompt_decode_and_speculation_rates():
    before = parse_metrics(SAMPLE, captured_ns=1_000_000_000)
    after = parse_metrics(
        SAMPLE.replace("prompt_tokens_total 100", "prompt_tokens_total 300")
        .replace("prompt_seconds_total 2.0", "prompt_seconds_total 6.0")
        .replace("tokens_predicted_total 80", "tokens_predicted_total 200")
        .replace("tokens_predicted_seconds_total 4", "tokens_predicted_seconds_total 10")
        .replace("spec_decode_num_draft_tokens_total 40", "spec_decode_num_draft_tokens_total 100")
        .replace("spec_decode_num_accepted_tokens_total 30", "spec_decode_num_accepted_tokens_total 80")
        .replace("requests_processing 0", "requests_processing 1"),
        captured_ns=6_000_000_000,
    )
    report = compare_snapshots(before, after)
    assert report["duration_seconds"] == 5.0
    assert report["prompt_tokens_per_second_from_counters"] == 50.0
    assert report["generated_tokens_per_second_from_counters"] == 20.0
    assert report["speculative_acceptance_ratio"] == 0.8333
    assert report["gauges_after"]["llamacpp:requests_processing"] == 1
    assert report["scope"] == "endpoint_aggregate"
    assert "not per-request" in report["attribution"]


def test_compare_marks_counter_resets_and_does_not_report_negative_rates():
    before = parse_metrics("llamacpp:prompt_tokens_total 100\nllamacpp:prompt_seconds_total 2\n",
                           captured_ns=1)
    after = parse_metrics("llamacpp:prompt_tokens_total 2\nllamacpp:prompt_seconds_total 3\n",
                          captured_ns=2_000_000_001)
    report = compare_snapshots(before, after)
    assert report["counter_deltas"]["llamacpp:prompt_tokens_total"] is None
    assert report["counter_resets"] == ["llamacpp:prompt_tokens_total"]
    assert report["prompt_tokens_per_second_from_counters"] is None


def test_compare_marks_missing_counters_and_missing_rates():
    before = parse_metrics("llamacpp:prompt_tokens_total 10\n", captured_ns=10)
    after = parse_metrics("llamacpp:prompt_tokens_total 20\n", captured_ns=1_000_000_010)
    report = compare_snapshots(before, after)
    assert "llamacpp:prompt_seconds_total" in report["missing_counters"]
    assert report["prompt_tokens_per_second_from_counters"] is None


def test_compare_rejects_nonincreasing_clock_and_different_model_scope():
    before = parse_metrics("llamacpp:prompt_tokens_total 1\n", captured_ns=2, model_query="a")
    same_time = parse_metrics("llamacpp:prompt_tokens_total 2\n", captured_ns=2, model_query="a")
    other_model = parse_metrics("llamacpp:prompt_tokens_total 2\n", captured_ns=3, model_query="b")
    with pytest.raises(ValueError, match="strictly increasing"):
        compare_snapshots(before, same_time)
    with pytest.raises(ValueError, match="same model"):
        compare_snapshots(before, other_model)


class FakeResponse:
    status = 200

    def __init__(self, body: bytes):
        self.body = body
        self.read_limit: int | None = None

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self, limit: int) -> bytes:
        self.read_limit = limit
        return self.body[:limit]

    def getcode(self) -> int:
        return self.status


class FakeOpener:
    def __init__(self, response: FakeResponse | Exception):
        self.response = response
        self.request: Any = None
        self.timeout: float | None = None

    def open(self, request: object, timeout: float) -> FakeResponse:
        self.request = request
        self.timeout = timeout
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_fetch_uses_loopback_get_without_auth_and_bounds_response():
    response = FakeResponse(SAMPLE.encode())
    opener = FakeOpener(response)
    snapshot = fetch_metrics("http://127.0.0.1:8080/v1", opener=opener)
    assert snapshot.get("llamacpp:prompt_tokens_total") == 100
    assert opener.request is not None
    assert opener.request.get_method() == "GET"
    assert opener.request.full_url == "http://127.0.0.1:8080/metrics"
    assert opener.request.get_header("Authorization") is None
    assert opener.timeout == 1.5
    assert response.read_limit == MAX_METRICS_BYTES + 1


def test_fetch_reports_disabled_endpoint_without_leaking_http_body():
    opener = FakeOpener(HTTPError("http://127.0.0.1:8080/metrics", 501, "disabled", {}, None))
    with pytest.raises(MetricsUnavailable, match="metrics_disabled"):
        fetch_metrics("http://127.0.0.1:8080/v1", opener=opener)


def test_fetch_rejects_oversized_and_invalid_utf8_responses():
    with pytest.raises(MetricsUnavailable, match="too_large"):
        fetch_metrics("http://127.0.0.1:8080/v1",
                      opener=FakeOpener(FakeResponse(b"x" * (MAX_METRICS_BYTES + 1))))
    with pytest.raises(MetricsUnavailable, match="invalid_utf8"):
        fetch_metrics("http://127.0.0.1:8080/v1",
                      opener=FakeOpener(FakeResponse(b"\xff")))


def test_capture_window_uses_two_snapshots_and_returns_only_aggregate_metrics():
    snapshots = iter([
        parse_metrics("llamacpp:tokens_predicted_total 10\nllamacpp:tokens_predicted_seconds_total 1\n",
                      captured_ns=1),
        parse_metrics("llamacpp:tokens_predicted_total 30\nllamacpp:tokens_predicted_seconds_total 3\n",
                      captured_ns=2_000_000_001),
    ])
    sleeps = []

    def fake_fetcher(endpoint: str, *, model: str | None, timeout_seconds: float) -> LlamaMetricsSnapshot:
        assert endpoint == "http://127.0.0.1:8080/v1"
        assert model is None
        assert timeout_seconds == 1.5
        return next(snapshots)

    report = capture_window(
        "http://127.0.0.1:8080/v1",
        duration_seconds=2,
        fetcher=fake_fetcher,
        sleep_fn=sleeps.append,
    )
    assert sleeps == [2.0]
    assert report["generated_tokens_per_second_from_counters"] == 10.0
    assert report["scope"] == "endpoint_aggregate"


def test_capture_window_rejects_unbounded_duration():
    with pytest.raises(ValueError, match="between"):
        capture_window("http://127.0.0.1:8080/v1", duration_seconds=3601)


def test_snapshot_rejects_mutable_or_invalid_values():
    with pytest.raises(ValueError):
        LlamaMetricsSnapshot(1, [("llamacpp:prompt_tokens_total", 1)])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        LlamaMetricsSnapshot(1, (("llamacpp:prompt_tokens_total", float("nan")),))
    with pytest.raises(ValueError):
        parse_metrics("llamacpp:prompt_tokens_total 1\n", model_query="")
