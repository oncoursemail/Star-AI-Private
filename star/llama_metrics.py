"""Read-only parser and interval analysis for llama.cpp server metrics.

The caller owns HTTP transport, authentication, model selection and polling. This
module accepts only a bounded Prometheus text snapshot; it never opens a socket,
changes server settings, schedules work, or stores prompts, outputs or secrets.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re

_MAX_TEXT_CHARS = 256_000
_MAX_LINES = 2_048
_MAX_LINE_CHARS = 4_096
_MAX_VALUE = Decimal("1e18")
_INSTANCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_LABEL_NAME = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\Z")
_NUMBER = re.compile(r"\+?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_SAMPLE = re.compile(
    r"(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?"
    r"\s+(?P<value>[^\s]+)(?:\s+(?P<timestamp>[0-9]+))?\Z"
)

_INTEGER_METRICS = frozenset({
    "llamacpp:prompt_tokens_total",
    "llamacpp:tokens_predicted_total",
    "llamacpp:requests_processing",
    "llamacpp:requests_deferred",
    "llamacpp:n_tokens_max",
    "llamacpp:n_decode_total",
    "llamacpp:spec_decode_num_draft_tokens_total",
    "llamacpp:spec_decode_num_accepted_tokens_total",
    "llamacpp:spec_decode_num_drafts_total",
    "llamacpp:spec_decode_num_accepted_tokens_per_pos_total",
})
_FLOAT_METRICS = frozenset({
    "llamacpp:prompt_seconds_total",
    "llamacpp:prompt_tokens_seconds",
    "llamacpp:tokens_predicted_seconds_total",
    "llamacpp:predicted_tokens_seconds",
    "llamacpp:n_busy_slots_per_decode",
})
_KNOWN_METRICS = _INTEGER_METRICS | _FLOAT_METRICS


@dataclass(frozen=True)
class LlamaCppMetricsSnapshot:
    """One bounded sample; instance_id must change whenever the server restarts."""

    instance_id: str
    captured_at_ms: float
    prompt_tokens_total: int | None = None
    prompt_seconds_total: float | None = None
    prompt_tokens_per_second: float | None = None
    generated_tokens_total: int | None = None
    generation_seconds_total: float | None = None
    generation_tokens_per_second: float | None = None
    requests_processing: int | None = None
    requests_deferred: int | None = None
    max_context_tokens: int | None = None
    decode_calls_total: int | None = None
    busy_slots_per_decode: float | None = None
    speculative_draft_tokens_total: int | None = None
    speculative_accepted_tokens_total: int | None = None
    speculative_steps_total: int | None = None
    accepted_tokens_by_position: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        if type(self.instance_id) is not str or not _INSTANCE_ID.fullmatch(self.instance_id):
            raise ValueError("instance_id must be a bounded opaque server epoch")
        if (isinstance(self.captured_at_ms, bool)
                or not isinstance(self.captured_at_ms, (int, float))
                or not math.isfinite(self.captured_at_ms)
                or not 0 <= self.captured_at_ms <= 1e13):
            raise ValueError("captured_at_ms must be a finite monotonic timestamp")
        for name in (
            "prompt_tokens_total", "generated_tokens_total", "requests_processing",
            "requests_deferred", "max_context_tokens", "decode_calls_total",
            "speculative_draft_tokens_total", "speculative_accepted_tokens_total",
            "speculative_steps_total",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not 0 <= value <= 10**18):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        for name in (
            "prompt_seconds_total", "prompt_tokens_per_second", "generation_seconds_total",
            "generation_tokens_per_second", "busy_slots_per_decode",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1e18
            ):
                raise ValueError(f"{name} must be finite and nonnegative or None")
        if type(self.accepted_tokens_by_position) is not tuple:
            raise ValueError("accepted_tokens_by_position must be a tuple")
        previous = -1
        for position, count in self.accepted_tokens_by_position:
            if type(position) is not int or not 0 <= position <= 128 or position <= previous:
                raise ValueError("speculative positions must be unique, sorted integers in 0..128")
            if type(count) is not int or not 0 <= count <= 10**18:
                raise ValueError("per-position counts must be nonnegative integers")
            previous = position


@dataclass(frozen=True)
class LlamaCppMetricsDelta:
    """Counter-derived interval rates plus current gauges; never a routing decision."""

    elapsed_ms: float
    prompt_tokens_per_second: float | None
    generated_tokens_per_second: float | None
    prefill_compute_tokens_per_second: float | None
    decode_compute_tokens_per_second: float | None
    speculative_draft_acceptance_percent: float | None
    speculative_accepted_tokens_per_step: float | None
    speculative_steps_per_second: float | None
    decode_calls_per_second: float | None
    accepted_tokens_by_position_delta: tuple[tuple[int, int], ...]
    requests_processing: int | None
    requests_deferred: int | None
    server_prompt_tokens_per_second: float | None
    server_generation_tokens_per_second: float | None
    max_context_tokens: int | None
    busy_slots_per_decode: float | None
    counter_resets: tuple[str, ...]
    anomalies: tuple[str, ...]


def _parse_labels(raw: str | None) -> dict[str, str]:
    """Parse Prometheus label pairs without CSV ambiguity or silent overwrites."""
    if raw is None:
        return {}
    if not raw.strip():
        raise ValueError("empty label sets are not valid")
    labels: dict[str, str] = {}
    index = 0
    while index < len(raw):
        while index < len(raw) and raw[index].isspace():
            index += 1
        start = index
        while index < len(raw) and (raw[index].isalnum() or raw[index] == "_"):
            index += 1
        key = raw[start:index]
        if not key or not _LABEL_NAME.fullmatch(key) or key in labels:
            raise ValueError("invalid or duplicate Prometheus label")
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw) or raw[index] != "=":
            raise ValueError("expected '=' after Prometheus label name")
        index += 1
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw) or raw[index] != '"':
            raise ValueError("Prometheus label values must be quoted")
        index += 1
        value: list[str] = []
        closed = False
        while index < len(raw):
            char = raw[index]
            index += 1
            if char == '"':
                closed = True
                break
            if char == "\\":
                if index >= len(raw):
                    raise ValueError("unterminated Prometheus label escape")
                escaped = raw[index]
                index += 1
                translations = {"\\": "\\", '"': '"', "n": "\n"}
                if escaped not in translations:
                    raise ValueError("unsupported Prometheus label escape")
                value.append(translations[escaped])
            else:
                value.append(char)
        if not closed:
            raise ValueError("unterminated Prometheus label value")
        labels[key] = "".join(value)
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index == len(raw):
            break
        if raw[index] != ",":
            raise ValueError("expected ',' between Prometheus labels")
        index += 1
        if index == len(raw):
            raise ValueError("trailing comma in Prometheus labels")
    return labels


def _parse_value(raw: str, *, integer: bool) -> int | float:
    if not _NUMBER.fullmatch(raw):
        raise ValueError("metric sample must be a finite nonnegative number")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("invalid metric number") from exc
    if not value.is_finite() or value < 0 or value > _MAX_VALUE:
        raise ValueError("metric number is outside the supported range")
    if integer:
        if value != value.to_integral_value():
            raise ValueError("counter and count metrics must be integral")
        return int(value)
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("metric number must be finite")
    return result


def parse_llama_cpp_metrics(
    text: str, *, instance_id: str, captured_at_ms: float,
) -> LlamaCppMetricsSnapshot:
    """Parse a bounded llama.cpp Prometheus metrics response.

    The caller must use the model selector required by llama.cpp router mode and
    rotate instance_id whenever the server process/model epoch is restarted.
    Unknown metric names are ignored for forward/backward compatibility.
    """
    if type(text) is not str or len(text) > _MAX_TEXT_CHARS:
        raise ValueError("metrics response must be a bounded UTF-8 text string")
    if len(text.splitlines()) > _MAX_LINES:
        raise ValueError("metrics response contains too many lines")
    values: dict[str, int | float] = {}
    positions: dict[int, int] = {}
    for raw_line in text.splitlines():
        if len(raw_line) > _MAX_LINE_CHARS:
            raise ValueError("metrics line is too long")
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE.fullmatch(line)
        if match is None:
            prefix = line.split("{", 1)[0].split(None, 1)[0]
            if prefix in _KNOWN_METRICS:
                raise ValueError("malformed known llama.cpp metric sample")
            continue
        name = match.group("name")
        if name not in _KNOWN_METRICS:
            continue
        labels = _parse_labels(match.group("labels"))
        value = _parse_value(match.group("value"), integer=name in _INTEGER_METRICS)
        if name == "llamacpp:spec_decode_num_accepted_tokens_per_pos_total":
            if set(labels) != {"position"}:
                raise ValueError("per-position speculative metrics require only a position label")
            raw_position = labels["position"]
            if not raw_position.isascii() or not raw_position.isdigit():
                raise ValueError("speculative position must be an integer")
            position = int(raw_position)
            if not 0 <= position <= 128 or position in positions:
                raise ValueError("speculative position is out of range or duplicated")
            positions[position] = int(value)
            continue
        if labels:
            raise ValueError("labelled scalar metrics are ambiguous; select one model/series first")
        if name in values:
            raise ValueError("duplicate scalar metric sample")
        values[name] = value

    if not values and not positions:
        raise ValueError("response contained no recognized llama.cpp metrics")

    def integer(name: str) -> int | None:
        value = values.get(name)
        return value if type(value) is int else None

    def floating(name: str) -> float | None:
        value = values.get(name)
        if type(value) is int:
            return float(value)
        if type(value) is float:
            return value
        return None

    return LlamaCppMetricsSnapshot(
        instance_id=instance_id,
        captured_at_ms=captured_at_ms,
        prompt_tokens_total=integer("llamacpp:prompt_tokens_total"),
        prompt_seconds_total=floating("llamacpp:prompt_seconds_total"),
        prompt_tokens_per_second=floating("llamacpp:prompt_tokens_seconds"),
        generated_tokens_total=integer("llamacpp:tokens_predicted_total"),
        generation_seconds_total=floating("llamacpp:tokens_predicted_seconds_total"),
        generation_tokens_per_second=floating("llamacpp:predicted_tokens_seconds"),
        requests_processing=integer("llamacpp:requests_processing"),
        requests_deferred=integer("llamacpp:requests_deferred"),
        max_context_tokens=integer("llamacpp:n_tokens_max"),
        decode_calls_total=integer("llamacpp:n_decode_total"),
        busy_slots_per_decode=floating("llamacpp:n_busy_slots_per_decode"),
        speculative_draft_tokens_total=integer("llamacpp:spec_decode_num_draft_tokens_total"),
        speculative_accepted_tokens_total=integer("llamacpp:spec_decode_num_accepted_tokens_total"),
        speculative_steps_total=integer("llamacpp:spec_decode_num_drafts_total"),
        accepted_tokens_by_position=tuple(sorted(positions.items())),
    )


def _counter_delta(
    previous: LlamaCppMetricsSnapshot,
    current: LlamaCppMetricsSnapshot,
    field: str,
    resets: list[str],
) -> int | float | None:
    before = getattr(previous, field)
    after = getattr(current, field)
    if before is None or after is None:
        return None
    if after < before:
        resets.append(field)
        return None
    return after - before


def _rate(delta: int | float | None, elapsed_seconds: float) -> float | None:
    if delta is None:
        return None
    return round(float(delta) / elapsed_seconds, 3)


def compare_llama_cpp_metrics(
    previous: LlamaCppMetricsSnapshot,
    current: LlamaCppMetricsSnapshot,
) -> LlamaCppMetricsDelta:
    """Compare same-process snapshots; counter resets suppress affected rates.

    This output is observability only. It must not be used as a direct model
    quality score, an automatic speculative-decoding toggle, or a scheduler
    admission decision. Pair it with request-level AIPerf and host/game/OBS data.
    """
    if not isinstance(previous, LlamaCppMetricsSnapshot) or not isinstance(current, LlamaCppMetricsSnapshot):
        raise TypeError("expected LlamaCppMetricsSnapshot values")
    if previous.instance_id != current.instance_id:
        raise ValueError("cannot compare metrics from different server instances")
    elapsed_ms = current.captured_at_ms - previous.captured_at_ms
    if elapsed_ms <= 0:
        raise ValueError("current snapshot must be later on the same monotonic clock")
    elapsed_seconds = elapsed_ms / 1000.0
    resets: list[str] = []
    anomalies: list[str] = []
    prompt_tokens = _counter_delta(previous, current, "prompt_tokens_total", resets)
    prompt_seconds = _counter_delta(previous, current, "prompt_seconds_total", resets)
    generated_tokens = _counter_delta(previous, current, "generated_tokens_total", resets)
    generation_seconds = _counter_delta(previous, current, "generation_seconds_total", resets)
    draft_tokens = _counter_delta(previous, current, "speculative_draft_tokens_total", resets)
    accepted_tokens = _counter_delta(previous, current, "speculative_accepted_tokens_total", resets)
    spec_steps = _counter_delta(previous, current, "speculative_steps_total", resets)
    decode_calls = _counter_delta(previous, current, "decode_calls_total", resets)

    acceptance: float | None = None
    accepted_per_step: float | None = None
    if draft_tokens is not None and accepted_tokens is not None and draft_tokens > 0:
        if accepted_tokens > draft_tokens:
            anomalies.append("accepted_speculative_tokens_exceed_draft_tokens")
        else:
            acceptance = round(float(accepted_tokens) * 100.0 / float(draft_tokens), 3)
    if accepted_tokens is not None and spec_steps is not None and spec_steps > 0:
        accepted_per_step = round(float(accepted_tokens) / float(spec_steps), 3)

    previous_positions = dict(previous.accepted_tokens_by_position)
    position_deltas: list[tuple[int, int]] = []
    for position, value in current.accepted_tokens_by_position:
        if position not in previous_positions:
            continue
        before = previous_positions[position]
        if value < before:
            resets.append(f"accepted_tokens_by_position[{position}]")
        else:
            position_deltas.append((position, value - before))

    return LlamaCppMetricsDelta(
        elapsed_ms=round(elapsed_ms, 3),
        prompt_tokens_per_second=_rate(prompt_tokens, elapsed_seconds),
        generated_tokens_per_second=_rate(generated_tokens, elapsed_seconds),
        prefill_compute_tokens_per_second=(
            round(float(prompt_tokens) / float(prompt_seconds), 3)
            if prompt_tokens is not None and prompt_seconds is not None and prompt_seconds > 0
            else None
        ),
        decode_compute_tokens_per_second=(
            round(float(generated_tokens) / float(generation_seconds), 3)
            if generated_tokens is not None and generation_seconds is not None and generation_seconds > 0
            else None
        ),
        speculative_draft_acceptance_percent=acceptance,
        speculative_accepted_tokens_per_step=accepted_per_step,
        speculative_steps_per_second=_rate(spec_steps, elapsed_seconds),
        decode_calls_per_second=_rate(decode_calls, elapsed_seconds),
        accepted_tokens_by_position_delta=tuple(position_deltas),
        requests_processing=current.requests_processing,
        requests_deferred=current.requests_deferred,
        server_prompt_tokens_per_second=current.prompt_tokens_per_second,
        server_generation_tokens_per_second=current.generation_tokens_per_second,
        max_context_tokens=current.max_context_tokens,
        busy_slots_per_decode=current.busy_slots_per_decode,
        counter_resets=tuple(sorted(set(resets))),
        anomalies=tuple(anomalies),
    )


__all__ = [
    "LlamaCppMetricsSnapshot",
    "LlamaCppMetricsDelta",
    "parse_llama_cpp_metrics",
    "compare_llama_cpp_metrics",
]
