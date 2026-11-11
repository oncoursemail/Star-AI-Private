"""Offline evaluation for STAR's multi-party streaming floor decisions.

This scores host-produced, human-annotated event decisions. It does not read
audio, transcripts, speaker identities, models, or live stream state. Keep
conversation groups disjoint between calibration and holdout splits.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import statistics
import sys
from typing import Sequence, cast

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_ACTIONS = ("respond", "listen", "backchannel", "silence", "hold")
_ADDRESSEES = frozenset({"star", "other", "group", "unknown"})
_SPEECH_ACTS = frozenset({
    "question", "request", "correction", "backchannel",
    "side_conversation", "statement", "uncertain",
})
_SPLITS = frozenset({"calibration", "holdout"})
_MAX_RECORDS = 20_000
_MAX_LINE_CHARS = 8_192
_MAX_LATENCY_MS = 60_000.0

_FIELDS = {
    "event_id", "conversation_id", "split",
    "gold_action", "predicted_action",
    "gold_addressee", "predicted_addressee",
    "gold_speech_act", "predicted_speech_act",
    "active_speakers", "receipt_age_ms", "decision_latency_ms",
    "response_probability",
}


def _identifier(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded opaque identifier")
    return value


def _enum(value: object, allowed: frozenset[str] | tuple[str, ...], field: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"invalid {field}")
    return value


def _number(
    value: object, field: str, *, minimum: float = 0.0,
    maximum: float = _MAX_LATENCY_MS,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} is outside its supported range") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{field} is outside its supported range")
    return number


def _integer(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer from {minimum} to {maximum}")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


@dataclass(frozen=True)
class FloorEvalCase:
    event_id: str
    conversation_id: str
    split: str
    gold_action: str
    predicted_action: str
    gold_addressee: str
    predicted_addressee: str
    gold_speech_act: str
    predicted_speech_act: str
    active_speakers: int
    receipt_age_ms: float
    decision_latency_ms: float
    response_probability: float

    def __post_init__(self) -> None:
        _identifier(self.event_id, "event_id")
        _identifier(self.conversation_id, "conversation_id")
        _enum(self.split, _SPLITS, "split")
        _enum(self.gold_action, _ACTIONS, "gold_action")
        _enum(self.predicted_action, _ACTIONS, "predicted_action")
        _enum(self.gold_addressee, _ADDRESSEES, "gold_addressee")
        _enum(self.predicted_addressee, _ADDRESSEES, "predicted_addressee")
        _enum(self.gold_speech_act, _SPEECH_ACTS, "gold_speech_act")
        _enum(self.predicted_speech_act, _SPEECH_ACTS, "predicted_speech_act")
        if type(self.active_speakers) is not int or not 1 <= self.active_speakers <= 8:
            raise ValueError("active_speakers must be an integer from 1 to 8")
        _number(self.receipt_age_ms, "receipt_age_ms")
        _number(self.decision_latency_ms, "decision_latency_ms")
        _number(self.response_probability, "response_probability", maximum=1.0)


def load_cases(path: Path) -> list[FloorEvalCase]:
    """Load a strict, bounded JSONL file without retaining text or identities."""
    source = Path(path)
    if source.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("evaluation dataset exceeds 8 MiB")
    cases: list[FloorEvalCase] = []
    event_ids: set[str] = set()
    conversation_splits: dict[str, str] = {}
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            if len(line) > _MAX_LINE_CHARS:
                raise ValueError(f"line {line_number} exceeds {_MAX_LINE_CHARS} characters")
            if len(cases) >= _MAX_RECORDS:
                raise ValueError(f"dataset exceeds {_MAX_RECORDS} records")
            try:
                raw = json.loads(
                    line, object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                )
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid JSONL on line {line_number}: {exc}") from exc
            if type(raw) is not dict or set(raw) != _FIELDS:
                raise ValueError(f"line {line_number} must contain exactly the declared fields")
            row = cast(dict[str, object], raw)
            case = FloorEvalCase(
                event_id=_identifier(row["event_id"], "event_id"),
                conversation_id=_identifier(row["conversation_id"], "conversation_id"),
                split=_enum(row["split"], _SPLITS, "split"),
                gold_action=_enum(row["gold_action"], _ACTIONS, "gold_action"),
                predicted_action=_enum(row["predicted_action"], _ACTIONS, "predicted_action"),
                gold_addressee=_enum(row["gold_addressee"], _ADDRESSEES, "gold_addressee"),
                predicted_addressee=_enum(
                    row["predicted_addressee"], _ADDRESSEES, "predicted_addressee"
                ),
                gold_speech_act=_enum(row["gold_speech_act"], _SPEECH_ACTS, "gold_speech_act"),
                predicted_speech_act=_enum(
                    row["predicted_speech_act"], _SPEECH_ACTS, "predicted_speech_act"
                ),
                active_speakers=_integer(
                    row["active_speakers"], "active_speakers", minimum=1, maximum=8
                ),
                receipt_age_ms=_number(row["receipt_age_ms"], "receipt_age_ms"),
                decision_latency_ms=_number(
                    row["decision_latency_ms"], "decision_latency_ms"
                ),
                response_probability=_number(
                    row["response_probability"], "response_probability", maximum=1.0
                ),
            )
            if case.event_id in event_ids:
                raise ValueError(f"line {line_number} repeats an event_id")
            previous_split = conversation_splits.get(case.conversation_id)
            if previous_split is not None and previous_split != case.split:
                raise ValueError("a conversation_id appears in both calibration and holdout")
            event_ids.add(case.event_id)
            conversation_splits[case.conversation_id] = case.split
            cases.append(case)
    return cases


def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction, 3)


def _calibration(cases: list[FloorEvalCase]) -> dict[str, float | int]:
    if not cases:
        return {"brier": 0.0, "ece_10_bins": 0.0, "count": 0}
    bins: list[list[tuple[float, float]]] = [[] for _ in range(10)]
    squared_error = 0.0
    for case in cases:
        probability = case.response_probability
        target = float(case.gold_action == "respond")
        squared_error += (probability - target) ** 2
        bins[min(int(probability * 10), 9)].append((probability, target))
    ece = 0.0
    for bucket in bins:
        if bucket:
            mean_probability = statistics.fmean(item[0] for item in bucket)
            mean_target = statistics.fmean(item[1] for item in bucket)
            ece += len(bucket) / len(cases) * abs(mean_probability - mean_target)
    return {
        "brier": round(squared_error / len(cases), 6),
        "ece_10_bins": round(ece, 6),
        "count": len(cases),
    }


def _metrics(cases: list[FloorEvalCase]) -> dict[str, object]:
    confusion = {gold: {pred: 0 for pred in _ACTIONS} for gold in _ACTIONS}
    for case in cases:
        confusion[case.gold_action][case.predicted_action] += 1

    per_action: dict[str, dict[str, float]] = {}
    for action in _ACTIONS:
        tp = confusion[action][action]
        fp = sum(confusion[gold][action] for gold in _ACTIONS if gold != action)
        fn = sum(confusion[action][pred] for pred in _ACTIONS if pred != action)
        per_action[action] = _prf(tp, fp, fn)

    response = per_action["respond"]
    non_response = [case for case in cases if case.gold_action != "respond"]
    overlap = [case for case in cases if case.active_speakers > 1]
    group = [case for case in cases if case.gold_addressee == "group"]
    side = [case for case in cases if case.gold_speech_act == "side_conversation"]
    backchannels = [case for case in cases if case.gold_speech_act == "backchannel"]
    def predicted_responses(rows: list[FloorEvalCase]) -> int:
        return sum(case.predicted_action == "respond" for case in rows)
    latencies = [case.decision_latency_ms for case in cases]
    response_latencies = [
        case.decision_latency_ms for case in cases
        if case.predicted_action == "respond"
    ]
    receipt_ages = [case.receipt_age_ms for case in cases]

    conversation_scores: list[float] = []
    conversations: dict[str, list[FloorEvalCase]] = {}
    for case in cases:
        conversations.setdefault(case.conversation_id, []).append(case)
    for rows in conversations.values():
        tp = sum(
            row.gold_action == "respond" and row.predicted_action == "respond"
            for row in rows
        )
        fp = sum(
            row.gold_action != "respond" and row.predicted_action == "respond"
            for row in rows
        )
        fn = sum(
            row.gold_action == "respond" and row.predicted_action != "respond"
            for row in rows
        )
        if tp + fp + fn > 0:
            conversation_scores.append(_prf(tp, fp, fn)["f1"])

    return {
        "event_count": len(cases),
        "conversation_count": len(conversations),
        "action_accuracy": round(
            sum(confusion[action][action] for action in _ACTIONS) / len(cases), 6
        ),
        "action_macro_f1": round(
            statistics.fmean(item["f1"] for item in per_action.values()), 6
        ),
        "per_action": per_action,
        "response_precision_recall_f1": response,
        "false_response_rate": round(
            predicted_responses(non_response) / len(non_response), 6
        ) if non_response else 0.0,
        "group_address_response_rate": round(
            predicted_responses(group) / len(group), 6
        ) if group else 0.0,
        "side_conversation_response_rate": round(
            predicted_responses(side) / len(side), 6
        ) if side else 0.0,
        "overlap_response_rate": round(
            predicted_responses(overlap) / len(overlap), 6
        ) if overlap else 0.0,
        "backchannel_spoken_rate": round(
            predicted_responses(backchannels) / len(backchannels), 6
        ) if backchannels else 0.0,
        "addressee_accuracy": round(
            sum(case.gold_addressee == case.predicted_addressee for case in cases)
            / len(cases), 6
        ),
        "speech_act_accuracy": round(
            sum(case.gold_speech_act == case.predicted_speech_act for case in cases)
            / len(cases), 6
        ),
        "conversation_response_scored_count": len(conversation_scores),
        "conversation_macro_response_f1": round(
            statistics.fmean(conversation_scores), 6
        ) if conversation_scores else 0.0,
        "response_probability_calibration": _calibration(cases),
        "decision_latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "response_decision_latency_ms": {
            "p50": _percentile(response_latencies, 0.50),
            "p95": _percentile(response_latencies, 0.95),
        },
        "receipt_age_ms": {
            "p50": _percentile(receipt_ages, 0.50),
            "p95": _percentile(receipt_ages, 0.95),
        },
        "confusion": confusion,
    }



_MIN_CALIBRATION_EVENTS = 20
_MIN_CALIBRATION_PER_CLASS = 5


def _threshold_metrics_from_counts(
    threshold: float,
    *,
    event_count: int,
    tp: int,
    fp: int,
    fn: int,
    tn: int,
) -> dict[str, float | int]:
    response = _prf(tp, fp, fn)
    non_response = fp + tn
    return {
        "threshold": threshold,
        "event_count": event_count,
        "gold_response_count": tp + fn,
        "gold_non_response_count": non_response,
        "predicted_response_count": tp + fp,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": response["precision"],
        "recall": response["recall"],
        "f1": response["f1"],
        "false_response_rate": round(fp / non_response, 6) if non_response else 0.0,
    }


def _response_threshold_metrics(
    cases: Sequence[FloorEvalCase], threshold: float,
) -> dict[str, float | int]:
    """Score one strict p > threshold decision in a single pass."""
    tp = fp = fn = tn = 0
    for case in cases:
        predicted = case.response_probability > threshold
        actual = case.gold_action == "respond"
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
    return _threshold_metrics_from_counts(
        threshold, event_count=len(cases), tp=tp, fp=fp, fn=fn, tn=tn,
    )


def _select_response_threshold(
    calibration: list[FloorEvalCase],
    holdout: list[FloorEvalCase],
    *,
    max_false_response_rate: float,
) -> dict[str, object]:
    """Choose on calibration only, then evaluate the frozen cutoff once on holdout."""
    positives = sum(case.gold_action == "respond" for case in calibration)
    negatives = len(calibration) - positives
    if (len(calibration) < _MIN_CALIBRATION_EVENTS
            or positives < _MIN_CALIBRATION_PER_CLASS
            or negatives < _MIN_CALIBRATION_PER_CLASS):
        return {
            "status": "insufficient_calibration",
            "reason": "requires_20_events_and_at_least_5_per_class",
            "minimum_calibration_events": _MIN_CALIBRATION_EVENTS,
            "minimum_per_class": _MIN_CALIBRATION_PER_CLASS,
            "observed_events": len(calibration),
            "observed_responses": positives,
            "observed_non_responses": negatives,
            "max_calibration_false_response_rate": max_false_response_rate,
            "selected_threshold": None,
            "calibration_metrics": None,
            "holdout_metrics": None,
        }

    # Prefix counts let each candidate be scored with one binary search instead
    # of rescanning the full calibration set (O(n log n), not O(n squared)).
    ordered = sorted(
        (case.response_probability, case.gold_action == "respond")
        for case in calibration
    )
    scores = [score for score, _ in ordered]
    prefix_positive = [0]
    prefix_negative = [0]
    for _, is_positive in ordered:
        prefix_positive.append(prefix_positive[-1] + int(is_positive))
        prefix_negative.append(prefix_negative[-1] + int(not is_positive))

    candidates = sorted({0.0, 1.0, *scores})
    feasible: list[dict[str, float | int]] = []
    for threshold in candidates:
        # Strict p > threshold means values equal to the cutoff are negative.
        cutoff = bisect_right(scores, threshold)
        fn = prefix_positive[cutoff]
        tn = prefix_negative[cutoff]
        metrics = _threshold_metrics_from_counts(
            threshold,
            event_count=len(calibration),
            tp=positives - fn,
            fp=negatives - tn,
            fn=fn,
            tn=tn,
        )
        if metrics["false_response_rate"] <= max_false_response_rate:
            feasible.append(metrics)

    # Threshold 1.0 always predicts silence, so a feasible point exists.
    selected = max(
        feasible,
        key=lambda item: (
            float(item["recall"]),
            float(item["f1"]),
            float(item["precision"]),
            float(item["threshold"]),
        ),
    )
    threshold = float(selected["threshold"])
    return {
        "status": "selected",
        "selection_policy": (
            "maximize calibration recall, then F1 and precision, subject to the "
            "calibration false-response-rate ceiling; predict respond only when p > threshold"
        ),
        "minimum_calibration_events": _MIN_CALIBRATION_EVENTS,
        "minimum_per_class": _MIN_CALIBRATION_PER_CLASS,
        "observed_events": len(calibration),
        "observed_responses": positives,
        "observed_non_responses": negatives,
        "max_calibration_false_response_rate": max_false_response_rate,
        "selected_threshold": threshold,
        "calibration_metrics": selected,
        "holdout_metrics": _response_threshold_metrics(holdout, threshold),
    }


def evaluate_cases(
    cases: Sequence[FloorEvalCase], *,
    max_calibration_false_response_rate: float = 0.05,
) -> dict[str, object]:
    """Report metrics and select a frozen response cutoff without holdout tuning."""
    if not isinstance(cases, (list, tuple)) or not cases:
        raise ValueError("provide a non-empty sequence of FloorEvalCase records")
    if any(type(case) is not FloorEvalCase for case in cases):
        raise ValueError("all records must be FloorEvalCase")
    event_ids = [case.event_id for case in cases]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("event_id values must be unique")
    splits: dict[str, set[str]] = {}
    for case in cases:
        splits.setdefault(case.conversation_id, set()).add(case.split)
    if any(len(values) != 1 for values in splits.values()):
        raise ValueError("conversations must not cross evaluation splits")
    calibration = [case for case in cases if case.split == "calibration"]
    holdout = [case for case in cases if case.split == "holdout"]
    if not calibration or not holdout:
        raise ValueError("both calibration and holdout conversations are required")
    max_false_rate = _number(
        max_calibration_false_response_rate,
        "max_calibration_false_response_rate",
        maximum=1.0,
    )
    return {
        "schema_version": 2,
        "split_policy": "conversation-disjoint",
        "calibration": _metrics(calibration),
        "holdout": _metrics(holdout),
        "response_threshold_selection": _select_response_threshold(
            calibration, holdout, max_false_response_rate=max_false_rate,
        ),
        "privacy": "aggregate metrics only; no event or conversation identifiers",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--max-calibration-false-response-rate", type=float, default=0.05,
        help="maximum false-response rate allowed when selecting a calibration cutoff",
    )
    args = parser.parse_args(argv)
    try:
        report = evaluate_cases(
            load_cases(args.cases),
            max_calibration_false_response_rate=args.max_calibration_false_response_rate,
        )
        output = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.out is None:
            sys.stdout.write(output)
        else:
            with args.out.open("x", encoding="utf-8") as handle:
                handle.write(output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
