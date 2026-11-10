"""Read-only, loopback-only diagnostics for llama.cpp server metrics.

The sampler reads only the documented Prometheus /metrics endpoint. It
never reads /slots (which can expose request parameters), sends prompts,
starts processes, changes server settings, or stores model output.

Counters are endpoint aggregates, not per-request evidence. Concurrent clients
may contribute to every delta; reports say so explicitly.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .brain_router import validate_alias

MAX_METRICS_BYTES = 128 * 1024
MAX_METRIC_LINES = 2048
MAX_METRIC_LINE_CHARS = 4096
MAX_WINDOW_SECONDS = 3600.0
MAX_TIMEOUT_SECONDS = 3.0
DEFAULT_TIMEOUT_SECONDS = 1.5

# Names are taken from the current upstream llama.cpp server README. Unknown
# metrics are ignored so newer servers remain forward-compatible.
_COUNTERS = (
    "llamacpp:prompt_tokens_total",
    "llamacpp:prompt_seconds_total",
    "llamacpp:tokens_predicted_total",
    "llamacpp:tokens_predicted_seconds_total",
    "llamacpp:n_tokens_max",
    "llamacpp:n_decode_total",
    "llamacpp:spec_decode_num_draft_tokens_total",
    "llamacpp:spec_decode_num_accepted_tokens_total",
    "llamacpp:spec_decode_num_drafts_total",
)
_GAUGES = (
    "llamacpp:prompt_tokens_seconds",
    "llamacpp:predicted_tokens_seconds",
    "llamacpp:requests_processing",
    "llamacpp:requests_deferred",
    "llamacpp:n_busy_slots_per_decode",
)
_SUPPORTED = frozenset((*_COUNTERS, *_GAUGES))
_ENDPOINT_RE = re.compile(r"http://(?:127\.0\.0\.1|localhost):\d{2,5}/v1/?\Z")
_SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?P<labels>\{[^}]*\})?\s+"
    r"(?P<value>[^\s]+)(?:\s+(?P<timestamp>\d+))?$"
)


class MetricsParseError(ValueError):
    """The metrics response was malformed or unsafe to interpret."""


class MetricsUnavailable(RuntimeError):
    """The optional metrics endpoint could not provide a usable snapshot."""


@dataclass(frozen=True)
class LlamaMetricsSnapshot:
    """One bounded snapshot of documented, unlabelled llama.cpp metrics."""

    captured_ns: int
    values: tuple[tuple[str, float], ...]
    model_query: str | None = None

    def __post_init__(self) -> None:
        if type(self.captured_ns) is not int or self.captured_ns < 0:
            raise ValueError("captured_ns must be a nonnegative monotonic integer")
        if type(self.values) is not tuple or len(self.values) > len(_SUPPORTED):
            raise ValueError("values must be a bounded immutable tuple")
        names: set[str] = set()
        for row in self.values:
            if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                    or row[0] not in _SUPPORTED or row[0] in names):
                raise ValueError("values contain an unsupported or duplicate metric")
            value = row[1]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError("metric values must be finite and nonnegative")
            names.add(row[0])
        if self.model_query is not None:
            if type(self.model_query) is not str or not self.model_query:
                raise ValueError("model_query must be a nonempty model ID")
            validate_alias(self.model_query, field="model")

    def get(self, name: str) -> float | None:
        return dict(self.values).get(name)


def parse_metrics(text: str, *, captured_ns: int | None = None,
                  model_query: str | None = None) -> LlamaMetricsSnapshot:
    """Parse a bounded Prometheus text response, retaining only known scalars.

    Labelled series are ignored because this adapter intentionally does not
    guess how to combine labels. The documented per-position speculative series
    is therefore not folded into the aggregate accepted-token counters.
    """
    if type(text) is not str:
        raise MetricsParseError("metrics body must be text")
    if len(text.encode("utf-8")) > MAX_METRICS_BYTES:
        raise MetricsParseError("metrics body exceeds the size limit")
    if "\x00" in text:
        raise MetricsParseError("metrics body contains a NUL byte")
    lines = text.splitlines()
    if len(lines) > MAX_METRIC_LINES:
        raise MetricsParseError("metrics body exceeds the line limit")

    values: dict[str, float] = {}
    for line in lines:
        if len(line) > MAX_METRIC_LINE_CHARS:
            raise MetricsParseError("metrics line exceeds the size limit")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _SAMPLE_RE.fullmatch(stripped)
        if match is None:
            # Ignore malformed unknown series, but do not silently accept a
            # malformed line whose prefix names a metric we rely on.
            first = stripped.split(None, 1)[0]
            metric_name = first.split("{", 1)[0]
            if metric_name in _SUPPORTED:
                raise MetricsParseError("malformed supported metric")
            continue
        name = match.group("name")
        if name not in _SUPPORTED or match.group("labels") is not None:
            continue
        if name in values:
            raise MetricsParseError("duplicate supported metric")
        raw = match.group("value")
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise MetricsParseError("supported metric is not numeric") from exc
        if not math.isfinite(value) or value < 0:
            raise MetricsParseError("supported metric must be finite and nonnegative")
        values[name] = value

    if not values:
        raise MetricsParseError("no supported unlabelled llama.cpp metrics found")
    stamp = time.monotonic_ns() if captured_ns is None else captured_ns
    return LlamaMetricsSnapshot(stamp, tuple(sorted(values.items())), model_query)


def metrics_url(endpoint: str, *, model: str | None = None) -> str:
    """Derive /metrics from STAR's validated loopback /v1 endpoint."""
    if (type(endpoint) is not str or len(endpoint) > 256
            or _ENDPOINT_RE.fullmatch(endpoint) is None):
        raise ValueError("endpoint must match STAR's validated loopback /v1 URL")
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"/v1", "/v1/"} or parsed.query or parsed.fragment):
        raise ValueError("metrics are restricted to the configured loopback /v1 endpoint")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid loopback port") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("loopback endpoint requires a valid explicit port")
    if model is not None:
        if type(model) is not str or not model:
            raise ValueError("model must be a nonempty model ID")
        validate_alias(model, field="model")
    base = f"http://{parsed.hostname}:{port}/metrics"
    return base if model is None else f"{base}?{urlencode({'model': model})}"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def fetch_metrics(endpoint: str, *, model: str | None = None,
                  timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                  opener: Any = None) -> LlamaMetricsSnapshot:
    """Fetch one snapshot without proxies, redirects, auth headers or remote hosts."""
    url = metrics_url(endpoint, model=model)
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0.1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise ValueError("timeout_seconds must be between 0.1 and 3 seconds")
    request = Request(url, headers={"Accept": "text/plain; version=0.0.4"}, method="GET")
    http = opener if opener is not None else build_opener(ProxyHandler({}), _NoRedirect())
    try:
        response = http.open(request, timeout=float(timeout_seconds))
        with response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status != 200:
                raise MetricsUnavailable("metrics_http_status")
            body = response.read(MAX_METRICS_BYTES + 1)
    except HTTPError as exc:
        reason = "metrics_disabled" if exc.code == 501 else "metrics_http_status"
        raise MetricsUnavailable(reason) from None
    except (URLError, TimeoutError, OSError):
        raise MetricsUnavailable("metrics_transport_error") from None
    if not isinstance(body, bytes) or len(body) > MAX_METRICS_BYTES:
        raise MetricsUnavailable("metrics_response_too_large")
    try:
        decoded = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise MetricsUnavailable("metrics_invalid_utf8") from None
    try:
        return parse_metrics(decoded, model_query=model)
    except MetricsParseError:
        raise MetricsUnavailable("metrics_invalid_response") from None


def _counter_delta(before: LlamaMetricsSnapshot, after: LlamaMetricsSnapshot,
                   name: str) -> tuple[float | None, bool, bool]:
    left, right = before.get(name), after.get(name)
    if left is None or right is None:
        return None, False, True
    if right < left:
        return None, True, False
    return right - left, False, False


def compare_snapshots(before: LlamaMetricsSnapshot,
                      after: LlamaMetricsSnapshot) -> dict[str, Any]:
    """Summarize one interval, marking counter resets and missing series."""
    if not isinstance(before, LlamaMetricsSnapshot) or not isinstance(after, LlamaMetricsSnapshot):
        raise TypeError("before and after must be LlamaMetricsSnapshot values")
    if after.captured_ns <= before.captured_ns:
        raise ValueError("snapshot clocks must be strictly increasing")
    if before.model_query != after.model_query:
        raise ValueError("snapshots must use the same model query scope")

    duration_seconds = (after.captured_ns - before.captured_ns) / 1_000_000_000
    deltas: dict[str, float | None] = {}
    resets: list[str] = []
    missing: list[str] = []
    for name in _COUNTERS:
        delta, reset, absent = _counter_delta(before, after, name)
        deltas[name] = round(delta, 6) if delta is not None else None
        if reset:
            resets.append(name)
        if absent:
            missing.append(name)

    prompt_tokens = deltas["llamacpp:prompt_tokens_total"]
    prompt_seconds = deltas["llamacpp:prompt_seconds_total"]
    generated_tokens = deltas["llamacpp:tokens_predicted_total"]
    generation_seconds = deltas["llamacpp:tokens_predicted_seconds_total"]
    draft_tokens = deltas["llamacpp:spec_decode_num_draft_tokens_total"]
    accepted_tokens = deltas["llamacpp:spec_decode_num_accepted_tokens_total"]

    def rate(tokens: float | None, seconds: float | None) -> float | None:
        if tokens is None or seconds is None or seconds <= 0:
            return None
        return round(tokens / seconds, 2)

    acceptance = None
    if draft_tokens is not None and accepted_tokens is not None and draft_tokens > 0:
        if accepted_tokens <= draft_tokens:
            acceptance = round(accepted_tokens / draft_tokens, 4)

    def gauge(name: str, snapshot: LlamaMetricsSnapshot) -> float | None:
        value = snapshot.get(name)
        return round(value, 6) if value is not None else None

    return {
        "schema_version": 1,
        "available": True,
        "scope": "model_query" if after.model_query is not None else "endpoint_aggregate",
        "model_query": after.model_query,
        "duration_seconds": round(duration_seconds, 3),
        "counter_deltas": deltas,
        "counter_resets": resets,
        "missing_counters": missing,
        "prompt_tokens_per_second_from_counters": rate(prompt_tokens, prompt_seconds),
        "generated_tokens_per_second_from_counters": rate(generated_tokens, generation_seconds),
        "speculative_acceptance_ratio": acceptance,
        "gauges_before": {name: gauge(name, before) for name in _GAUGES},
        "gauges_after": {name: gauge(name, after) for name in _GAUGES},
        "context_tokens_high_watermark_after": after.get("llamacpp:n_tokens_max"),
        "attribution": (
            "Cumulative server counters are aggregate observations; concurrent clients may contribute. "
            "They are not per-request attribution, raw GPU telemetry, or a standalone speedup claim."
        ),
    }


def capture_window(endpoint: str, *, duration_seconds: float,
                   model: str | None = None,
                   timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                   fetcher: Callable[..., LlamaMetricsSnapshot] = fetch_metrics,
                   sleep_fn: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Capture a bounded read-only metrics window while another local test runs."""
    if (type(duration_seconds) not in (int, float) or not math.isfinite(duration_seconds)
            or not 0.1 <= duration_seconds <= MAX_WINDOW_SECONDS):
        raise ValueError("duration_seconds must be between 0.1 and 3600 seconds")
    before = fetcher(endpoint, model=model, timeout_seconds=timeout_seconds)
    sleep_fn(float(duration_seconds))
    after = fetcher(endpoint, model=model, timeout_seconds=timeout_seconds)
    return compare_snapshots(before, after)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sample documented llama.cpp server metrics during a local STAR benchmark."
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1",
                        help="Validated loopback model URL ending in /v1")
    parser.add_argument("--model", help="Optional llama.cpp router model ID for /metrics?model=...")
    parser.add_argument("--duration-seconds", type=float, default=60.0,
                        help="Capture window while another local benchmark runs (0.1..3600)")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help="Per-snapshot HTTP timeout (0.1..3)")
    parser.add_argument("--output", type=Path, help="Optional local JSON report path")
    args = parser.parse_args()
    try:
        report = capture_window(
            args.endpoint,
            duration_seconds=args.duration_seconds,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
        )
    except (ValueError, MetricsUnavailable) as exc:
        reason = str(exc) if isinstance(exc, MetricsUnavailable) else "invalid_arguments"
        encoded = json.dumps({"schema_version": 1, "available": False, "reason": reason}, indent=2) + "\n"
        if args.output:
            args.output.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, end="")
        return 2
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
