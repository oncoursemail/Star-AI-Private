"""Offline, privacy-preserving evaluation of voice delivery and long-context interaction.

The evaluator consumes only human/host-produced labels and scalar acoustic receipts.
It never reads audio, transcripts, prompts, viewer identities, or generated speech.
It is designed as a separate companion lane to floor-control evaluation: this module scores
delivery style, volume, spoken-task completion, and conversation grounding without importing
or depending on another evaluator.
It does not control microphones, TTS, avatar output, OBS, game input, or broadcasts.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, NoReturn

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 20_000
MAX_TURNS = 100_000
LONG_CONTEXT_TURNS = 20
WHISPER_HNR_MAX_DB = 6.0
WHISPER_VOICED_FRACTION_MAX = 0.4
NEAR_FULL_SCALE_DBFS = -1.0

SPLITS = frozenset({"development", "holdout"})
STYLES = frozenset({
    "neutral", "warm", "playful", "excited", "concerned", "serious",
    "whisper", "projected", "muted",
})
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")

_FIELDS = frozenset({
    "scenario_id", "event_id", "conversation_id", "split", "turn_index",
    "context_turn_count", "expected_style", "observed_style", "audio_present",
    "expected_rms_min_dbfs", "expected_rms_max_dbfs", "measured_rms_dbfs",
    "measured_true_peak_dbfs", "whisper_hnr_db", "voiced_fraction",
    "grounding_required", "grounding_verified", "task_required", "task_verified",
    "conversation_coherence",
})


def _reject(message: str) -> NoReturn:
    raise ValueError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject("duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    _reject("non-finite JSON number: " + value)


def _identifier(value: Any, label: str) -> str:
    if type(value) is not str or not ID_PATTERN.fullmatch(value):
        _reject("invalid " + label)
    return value


def _choice(value: Any, label: str, allowed: frozenset[str]) -> str:
    if type(value) is not str or value not in allowed:
        _reject("unknown " + label)
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _reject("invalid " + label)
    return value


def _boolean(value: Any, label: str, *, optional: bool = False) -> bool | None:
    if value is None and optional:
        return None
    if type(value) is not bool:
        _reject("invalid " + label)
    return value


def _number(
    value: Any,
    label: str,
    minimum: float,
    maximum: float,
    *,
    optional: bool = False,
) -> float | None:
    if value is None and optional:
        return None
    if type(value) not in (int, float):
        _reject("invalid " + label)
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _reject("invalid " + label)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        _reject("invalid " + label)
    return result


@dataclass(frozen=True)
class InteractionReceipt:
    """One content-free interaction item; identifiers must be random opaque tokens."""

    scenario_id: str
    event_id: str
    conversation_id: str
    split: str
    turn_index: int
    context_turn_count: int
    expected_style: str
    observed_style: str
    audio_present: bool
    expected_rms_min_dbfs: float | None
    expected_rms_max_dbfs: float | None
    measured_rms_dbfs: float | None
    measured_true_peak_dbfs: float | None
    whisper_hnr_db: float | None
    voiced_fraction: float | None
    grounding_required: bool
    grounding_verified: bool | None
    task_required: bool
    task_verified: bool | None
    conversation_coherence: int | None

    @classmethod
    def parse(cls, value: Any) -> "InteractionReceipt":
        if type(value) is not dict or set(value) != _FIELDS:
            _reject("unexpected or missing interaction-receipt fields")

        split = _choice(value["split"], "evaluation split", SPLITS)
        expected_style = _choice(value["expected_style"], "expected style", STYLES)
        observed_style = _choice(value["observed_style"], "observed style", STYLES)
        audio_present = _boolean(value["audio_present"], "audio-present flag")
        grounding_required = _boolean(value["grounding_required"], "grounding-required flag")
        grounding_verified = _boolean(value["grounding_verified"], "grounding result", optional=True)
        task_required = _boolean(value["task_required"], "task-required flag")
        task_verified = _boolean(value["task_verified"], "task result", optional=True)
        assert isinstance(audio_present, bool)
        assert isinstance(grounding_required, bool)
        assert isinstance(task_required, bool)

        turn_index = _integer(value["turn_index"], "turn index", 1, MAX_TURNS)
        context_turn_count = _integer(value["context_turn_count"], "context turn count", 0, MAX_TURNS)

        expected_min = _number(value["expected_rms_min_dbfs"], "expected RMS minimum", -120.0, 0.0, optional=True)
        expected_max = _number(value["expected_rms_max_dbfs"], "expected RMS maximum", -120.0, 0.0, optional=True)
        measured_rms = _number(value["measured_rms_dbfs"], "measured RMS", -120.0, 12.0, optional=True)
        measured_peak = _number(value["measured_true_peak_dbfs"], "measured true peak", -120.0, 12.0, optional=True)
        whisper_hnr = _number(value["whisper_hnr_db"], "whisper HNR", -100.0, 100.0, optional=True)
        voiced_fraction = _number(value["voiced_fraction"], "voiced fraction", 0.0, 1.0, optional=True)
        coherence = value["conversation_coherence"]
        if coherence is not None:
            coherence = _integer(coherence, "conversation coherence", 0, 100)

        if expected_style == "muted":
            if expected_min is not None or expected_max is not None:
                _reject("muted expectation must not define an RMS band")
        elif expected_min is None or expected_max is None or expected_min > expected_max:
            _reject("non-muted expectation needs an ordered RMS band")

        if audio_present:
            if observed_style == "muted" or measured_rms is None or measured_peak is None:
                _reject("present audio needs a non-muted style, RMS, and true-peak receipt")
        else:
            if observed_style != "muted":
                _reject("absent audio must be labeled muted")
            if any(x is not None for x in (measured_rms, measured_peak, whisper_hnr, voiced_fraction)):
                _reject("absent audio cannot have acoustic measurements")

        if not grounding_required and grounding_verified is not None:
            _reject("grounding result supplied when grounding was not required")
        if not task_required and task_verified is not None:
            _reject("task result supplied when a spoken task was not required")

        return cls(
            scenario_id=_identifier(value["scenario_id"], "scenario id"),
            event_id=_identifier(value["event_id"], "event id"),
            conversation_id=_identifier(value["conversation_id"], "conversation id"),
            split=split,
            turn_index=turn_index,
            context_turn_count=context_turn_count,
            expected_style=expected_style,
            observed_style=observed_style,
            audio_present=audio_present,
            expected_rms_min_dbfs=expected_min,
            expected_rms_max_dbfs=expected_max,
            measured_rms_dbfs=measured_rms,
            measured_true_peak_dbfs=measured_peak,
            whisper_hnr_db=whisper_hnr,
            voiced_fraction=voiced_fraction,
            grounding_required=grounding_required,
            grounding_verified=grounding_verified,
            task_required=task_required,
            task_verified=task_verified,
            conversation_coherence=coherence,
        )


def load_jsonl(path: Path) -> list[InteractionReceipt]:
    """Read bounded labels and scalar receipts; raw content is rejected by the exact schema."""
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        _reject("interaction-evaluation file exceeds the byte limit")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        _reject("interaction-evaluation file must be UTF-8")
    if not lines or len(lines) > MAX_EVENTS:
        _reject("interaction-evaluation file has no events or exceeds the event limit")

    receipts: list[InteractionReceipt] = []
    seen_events: set[tuple[str, str]] = set()
    seen_turns: set[tuple[str, int]] = set()
    coherence_seen: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            _reject(f"blank JSONL line at {line_number}")
        try:
            raw = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(f"invalid JSON on line {line_number}") from exc
        receipt = InteractionReceipt.parse(raw)
        event_key = (receipt.scenario_id, receipt.event_id)
        turn_key = (receipt.conversation_id, receipt.turn_index)
        if event_key in seen_events:
            _reject("duplicate scenario/event id")
        if turn_key in seen_turns:
            _reject("duplicate conversation turn index")
        if receipt.conversation_coherence is not None:
            if receipt.conversation_id in coherence_seen:
                _reject("conversation coherence may be supplied only once per conversation")
            coherence_seen.add(receipt.conversation_id)
        seen_events.add(event_key)
        seen_turns.add(turn_key)
        receipts.append(receipt)
    return receipts


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _style_metrics(rows: list[InteractionReceipt], style: str) -> dict[str, int | float | None]:
    true_positive = sum(r.expected_style == style and r.observed_style == style for r in rows)
    false_positive = sum(r.expected_style != style and r.observed_style == style for r in rows)
    false_negative = sum(r.expected_style == style and r.observed_style != style for r in rows)
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = None if precision is None or recall is None or precision + recall == 0 else round(
        2 * precision * recall / (precision + recall), 4
    )
    return {
        "support": sum(r.expected_style == style for r in rows),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _evidence_summary(rows: list[InteractionReceipt], field: str) -> dict[str, int | float | None]:
    required = len(rows)
    known = sum(getattr(row, field) is not None for row in rows)
    passed = sum(getattr(row, field) is True for row in rows)
    return {
        "required": required,
        "verified": known,
        "missing": required - known,
        "passed": passed,
        "evidence_coverage": _ratio(known, required),
        # Missing evidence remains a failure in the all-required denominator.
        "pass_rate_required": _ratio(passed, required),
        "pass_rate_verified": _ratio(passed, known),
    }


def _coherence_summary(values: list[int]) -> dict[str, int | float | None]:
    return {
        "conversation_count": len(values),
        "mean": round(statistics.mean(values), 2) if values else None,
        "median": round(statistics.median(values), 2) if values else None,
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
    }


def evaluate(receipts: list[InteractionReceipt], *, split: str | None = None) -> dict[str, Any]:
    """Score style, acoustic delivery, task completion and groundedness separately.

    There is deliberately no composite 'human-likeness' score. A high style score must
    not hide poor grounding, missing evidence, or weak spoken-task completion.
    """
    if type(receipts) is not list or not receipts or len(receipts) > MAX_EVENTS:
        _reject("evaluation requires 1..MAX_EVENTS receipts")
    if any(type(row) is not InteractionReceipt for row in receipts):
        _reject("evaluation accepts only parsed InteractionReceipt objects")
    if split is not None and (type(split) is not str or split not in SPLITS):
        _reject("unknown evaluation split")

    selected = [row for row in receipts if split is None or row.split == split]
    if not selected:
        _reject("no receipts for the requested split")
    if len({(r.scenario_id, r.event_id) for r in selected}) != len(selected):
        _reject("duplicate scenario/event id")
    if len({(r.conversation_id, r.turn_index) for r in selected}) != len(selected):
        _reject("duplicate conversation turn index")

    coherence_by_conversation: dict[str, int] = {}
    for row in selected:
        if row.conversation_coherence is not None:
            if row.conversation_id in coherence_by_conversation:
                _reject("conversation coherence may be supplied only once per conversation")
            coherence_by_conversation[row.conversation_id] = row.conversation_coherence

    count = len(selected)
    exact_style = sum(r.expected_style == r.observed_style for r in selected)
    per_style = {style: _style_metrics(selected, style) for style in sorted(STYLES)}

    non_muted = [r for r in selected if r.expected_style != "muted"]
    volume_passed = sum(
        r.audio_present
        and r.measured_rms_dbfs is not None
        and r.expected_rms_min_dbfs is not None
        and r.expected_rms_max_dbfs is not None
        and r.expected_rms_min_dbfs <= r.measured_rms_dbfs <= r.expected_rms_max_dbfs
        for r in non_muted
    )
    missing_audio = sum(not r.audio_present for r in non_muted)
    volume_out_of_range = len(non_muted) - volume_passed - missing_audio
    muted_rows = [r for r in selected if r.expected_style == "muted"]
    muted_correct = sum(not r.audio_present for r in muted_rows)
    peak_values = [r.measured_true_peak_dbfs for r in selected if r.measured_true_peak_dbfs is not None]
    near_full_scale = sum(value >= NEAR_FULL_SCALE_DBFS for value in peak_values)
    over_full_scale = sum(value > 0.0 for value in peak_values)

    whisper_rows = [r for r in selected if r.expected_style == "whisper"]
    whisper_measured = [
        r for r in whisper_rows
        if r.audio_present and r.whisper_hnr_db is not None and r.voiced_fraction is not None
    ]
    whisper_passed = sum(
        r.whisper_hnr_db is not None
        and r.voiced_fraction is not None
        and r.whisper_hnr_db < WHISPER_HNR_MAX_DB
        and r.voiced_fraction < WHISPER_VOICED_FRACTION_MAX
        for r in whisper_measured
    )

    grounding_rows = [r for r in selected if r.grounding_required]
    short_grounding = [r for r in grounding_rows if r.context_turn_count < LONG_CONTEXT_TURNS]
    long_grounding = [r for r in grounding_rows if r.context_turn_count >= LONG_CONTEXT_TURNS]
    task_rows = [r for r in selected if r.task_required]
    coherence_values = list(coherence_by_conversation.values())

    scenario_groups: dict[str, list[InteractionReceipt]] = {}
    conversation_ids = {r.conversation_id for r in selected}
    for row in selected:
        scenario_groups.setdefault(row.scenario_id, []).append(row)
    scenario_summary = [
        {
            "scenario_key": hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()[:12],
            "events": len(rows),
            "style_accuracy": round(
                sum(r.expected_style == r.observed_style for r in rows) / len(rows), 4
            ),
        }
        for scenario_id, rows in scenario_groups.items()
    ]
    scenario_summary.sort(key=lambda item: (item["style_accuracy"], item["scenario_key"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "star_voice_interaction_quality_evaluation",
        "split": split or "all",
        "event_count": count,
        "scenario_count": len(scenario_groups),
        "conversation_count": len(conversation_ids),
        "delivery_style": {
            "accuracy": round(exact_style / count, 4),
            "per_style": per_style,
        },
        "volume": {
            "non_muted_expected": len(non_muted),
            "in_range": volume_passed,
            "missing_audio": missing_audio,
            "out_of_range": volume_out_of_range,
            "in_range_rate_required": _ratio(volume_passed, len(non_muted)),
            "muted_expected": len(muted_rows),
            "muted_correct": muted_correct,
            "unexpected_audio": len(muted_rows) - muted_correct,
            "muted_correct_rate": _ratio(muted_correct, len(muted_rows)),
            "near_full_scale_peaks": near_full_scale,
            "over_full_scale_peaks": over_full_scale,
            "near_full_scale_threshold_dbfs": NEAR_FULL_SCALE_DBFS,
        },
        "whisper": {
            "required": len(whisper_rows),
            "measured": len(whisper_measured),
            "missing_measurements": len(whisper_rows) - len(whisper_measured),
            "acoustic_passed": whisper_passed,
            "pass_rate_required": _ratio(whisper_passed, len(whisper_rows)),
            "evidence_coverage": _ratio(len(whisper_measured), len(whisper_rows)),
            "hnr_below_db": WHISPER_HNR_MAX_DB,
            "voiced_fraction_below": WHISPER_VOICED_FRACTION_MAX,
            "limitations": "Acoustic screening thresholds are benchmark-specific, not a universal definition of whispering.",
        },
        "grounding": {
            "long_context_threshold_turns": LONG_CONTEXT_TURNS,
            "short_context": _evidence_summary(short_grounding, "grounding_verified"),
            "long_context": _evidence_summary(long_grounding, "grounding_verified"),
            "all_contexts": _evidence_summary(grounding_rows, "grounding_verified"),
        },
        "spoken_task": _evidence_summary(task_rows, "task_verified"),
        "conversation_coherence": _coherence_summary(coherence_values),
        "missing_evidence": {
            "non_muted_audio": missing_audio,
            "whisper_acoustics": len(whisper_rows) - len(whisper_measured),
            "short_context_grounding": sum(r.grounding_verified is None for r in short_grounding),
            "long_context_grounding": sum(r.grounding_verified is None for r in long_grounding),
            "spoken_task": sum(r.task_verified is None for r in task_rows),
            "conversation_coherence": len(conversation_ids) - len(coherence_values),
        },
        "scenario_summary": scenario_summary,
        "limitations": (
            "Scores supplied labels and scalar host receipts only. It does not process audio, "
            "transcribe speech, authenticate the host, judge semantic correctness, or authorize "
            "microphone, TTS, avatar, game, OBS, tool, or broadcast actions. Use independent "
            "human annotations, a sealed holdout, and a private client-side recording rehearsal."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate content-free STAR voice delivery, spoken-task, and grounding receipts."
    )
    parser.add_argument("input", type=Path, help="UTF-8 JSONL with labels and scalar host receipts")
    parser.add_argument("--split", choices=sorted(SPLITS), help="evaluate only development or holdout rows")
    parser.add_argument("--output", type=Path, help="write aggregate JSON report; event-level content is not copied")
    args = parser.parse_args(argv)
    report = evaluate(load_jsonl(args.input), split=args.split)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
