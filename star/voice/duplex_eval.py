"""Offline, privacy-preserving evaluation for full-duplex and multi-party voice behavior.

The evaluator consumes labels and host-observed receipts, never raw audio, transcripts,
speaker identities, prompts, or generated speech. It does not control microphones, TTS,
avatar output, or broadcasts. Its purpose is to make conversational timing measurable:
responding, backchanneling, staying silent, yielding to an interruption, and continuing
through a non-interrupting listener cue are scored as separate actions.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import statistics
from typing import Any, Iterable

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 20_000
MAX_EVENT_MS = 60 * 60 * 1000

SPLITS = frozenset({"development", "holdout"})
SPEAKER_ROLES = frozenset({"owner", "viewer", "other", "background"})
ADDRESSED_TO = frozenset({"star", "group", "owner", "other", "none", "unknown"})
ACTIONS = frozenset({"respond", "backchannel", "silence", "yield", "continue"})
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")

_FIELDS = frozenset({
    "scenario_id", "event_id", "split", "speaker_role", "addressed_to",
    "expected_action", "observed_action", "speech_start_ms", "speech_end_ms",
    "turn_end_ms", "assistant_active_at_start", "game_critical",
    "interrupt_detected_ms", "assistant_stop_ms", "first_audio_ms",
    "first_avatar_ms", "grounding_verified",
})


def _reject(message: str) -> None:
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


def _timestamp(value: Any, label: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if type(value) is not int or not 0 <= value <= MAX_EVENT_MS:
        _reject("invalid " + label)
    return value


def _boolean(value: Any, label: str, *, optional: bool = False) -> bool | None:
    if value is None and optional:
        return None
    if type(value) is not bool:
        _reject("invalid " + label)
    return value


@dataclass(frozen=True)
class TurnReceipt:
    """One content-free annotated interaction window, using scenario-relative milliseconds."""

    scenario_id: str
    event_id: str
    split: str
    speaker_role: str
    addressed_to: str
    expected_action: str
    observed_action: str
    speech_start_ms: int
    speech_end_ms: int
    turn_end_ms: int
    assistant_active_at_start: bool
    game_critical: bool
    interrupt_detected_ms: int | None
    assistant_stop_ms: int | None
    first_audio_ms: int | None
    first_avatar_ms: int | None
    grounding_verified: bool | None

    @classmethod
    def parse(cls, value: Any) -> "TurnReceipt":
        if type(value) is not dict or set(value) != _FIELDS:
            _reject("unexpected or missing turn-receipt fields")
        split = _choice(value["split"], "evaluation split", SPLITS)
        speaker_role = _choice(value["speaker_role"], "speaker role", SPEAKER_ROLES)
        addressed_to = _choice(value["addressed_to"], "addressee", ADDRESSED_TO)
        expected_action = _choice(value["expected_action"], "expected action", ACTIONS)
        observed_action = _choice(value["observed_action"], "observed action", ACTIONS)

        start = _timestamp(value["speech_start_ms"], "speech start")
        end = _timestamp(value["speech_end_ms"], "speech end")
        turn_end = _timestamp(value["turn_end_ms"], "turn end")
        assert start is not None and end is not None and turn_end is not None
        if not start <= end <= turn_end:
            _reject("speech and turn timestamps are out of order")

        interrupt = _timestamp(value["interrupt_detected_ms"], "interrupt detection", optional=True)
        stopped = _timestamp(value["assistant_stop_ms"], "assistant stop", optional=True)
        if interrupt is not None and stopped is not None and stopped < interrupt:
            _reject("assistant stop precedes interrupt detection")

        assistant_active = _boolean(value["assistant_active_at_start"], "assistant-active flag")
        game_critical = _boolean(value["game_critical"], "game-critical flag")
        assert isinstance(assistant_active, bool) and isinstance(game_critical, bool)
        return cls(
            scenario_id=_identifier(value["scenario_id"], "scenario id"),
            event_id=_identifier(value["event_id"], "event id"),
            split=split,
            speaker_role=speaker_role,
            addressed_to=addressed_to,
            expected_action=expected_action,
            observed_action=observed_action,
            speech_start_ms=start,
            speech_end_ms=end,
            turn_end_ms=turn_end,
            assistant_active_at_start=assistant_active,
            game_critical=game_critical,
            interrupt_detected_ms=interrupt,
            assistant_stop_ms=stopped,
            first_audio_ms=_timestamp(value["first_audio_ms"], "first-audio receipt", optional=True),
            first_avatar_ms=_timestamp(value["first_avatar_ms"], "first-avatar receipt", optional=True),
            grounding_verified=_boolean(value["grounding_verified"], "grounding receipt", optional=True),
        )


def load_jsonl(path: Path) -> list[TurnReceipt]:
    """Read bounded JSONL labels/receipts. Raw content fields are rejected by the exact schema."""
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        _reject("turn-evaluation file exceeds the byte limit")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        _reject("turn-evaluation file must be UTF-8")
    if not lines or len(lines) > MAX_EVENTS:
        _reject("turn-evaluation file has no events or exceeds the event limit")

    receipts: list[TurnReceipt] = []
    seen: set[tuple[str, str]] = set()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            _reject(f"blank JSONL line at {line_number}")
        try:
            raw = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_nonfinite)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(f"invalid JSON on line {line_number}") from exc
        receipt = TurnReceipt.parse(raw)
        key = (receipt.scenario_id, receipt.event_id)
        if key in seen:
            _reject("duplicate scenario/event id")
        seen.add(key)
        receipts.append(receipt)
    return receipts


def _percentile(values: Iterable[int], q: float) -> int | None:
    ordered = sorted(values)
    if not ordered:
        return None
    # Nearest-rank percentile: stable for small private rehearsals and documented in the report.
    index = max(0, min(len(ordered) - 1, int((q * len(ordered) + 0.999999999)) - 1))
    return ordered[index]


def _latency(values: list[int]) -> dict[str, int | None]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": int(round(statistics.median(ordered))) if ordered else None,
        "p95_ms": _percentile(ordered, 0.95),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _action_metrics(receipts: list[TurnReceipt], action: str) -> dict[str, int | float | None]:
    true_positive = sum(r.expected_action == action and r.observed_action == action for r in receipts)
    false_positive = sum(r.expected_action != action and r.observed_action == action for r in receipts)
    false_negative = sum(r.expected_action == action and r.observed_action != action for r in receipts)
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = None if precision is None or recall is None or precision + recall == 0 else round(
        2 * precision * recall / (precision + recall), 4
    )
    return {
        "support": sum(r.expected_action == action for r in receipts),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate(receipts: list[TurnReceipt], *, split: str | None = None) -> dict[str, Any]:
    """Score a held-out or development set. This is an evaluator, never a promotion authority."""
    if type(receipts) is not list or not receipts or len(receipts) > MAX_EVENTS:
        _reject("evaluation requires 1..MAX_EVENTS receipts")
    if any(type(r) is not TurnReceipt for r in receipts):
        _reject("evaluation accepts only parsed TurnReceipt objects")
    if split is not None and split not in SPLITS:
        _reject("unknown evaluation split")
    selected = [r for r in receipts if split is None or r.split == split]
    if not selected:
        _reject("no receipts for the requested split")
    if len({(r.scenario_id, r.event_id) for r in selected}) != len(selected):
        _reject("duplicate scenario/event id")

    count = len(selected)
    exact = sum(r.expected_action == r.observed_action for r in selected)
    per_action = {action: _action_metrics(selected, action) for action in sorted(ACTIONS)}

    response_latencies: list[int] = []
    early_responses = 0
    avatar_latencies: list[int] = []
    early_avatar_cues = 0
    stop_latencies: list[int] = []
    missing_audio = 0
    missing_avatar = 0
    missing_stop = 0
    unexpected_audio = 0
    unexpected_avatar = 0
    false_nonstar_responses = 0
    false_nonstar_backchannels = 0
    false_interruptions = 0
    missed_interruptions = 0
    yield_without_active_assistant = 0
    background_speech_reactions = 0
    critical_game_chatter = 0
    critical_game_windows = 0
    grounding_known = 0
    grounding_passed = 0
    scenario_rows: dict[str, list[TurnReceipt]] = {}

    for receipt in selected:
        scenario_rows.setdefault(receipt.scenario_id, []).append(receipt)
        if receipt.observed_action == "respond":
            if receipt.first_audio_ms is None:
                missing_audio += 1
            elif receipt.first_audio_ms < receipt.turn_end_ms:
                early_responses += 1
            else:
                response_latencies.append(receipt.first_audio_ms - receipt.turn_end_ms)
            if receipt.addressed_to not in {"star", "group"}:
                false_nonstar_responses += 1
            if receipt.grounding_verified is not None:
                grounding_known += 1
                grounding_passed += int(receipt.grounding_verified)
        elif receipt.first_audio_ms is not None:
            unexpected_audio += 1

        if receipt.observed_action == "backchannel":
            if receipt.first_avatar_ms is None:
                missing_avatar += 1
            elif receipt.first_avatar_ms < receipt.speech_start_ms:
                early_avatar_cues += 1
            else:
                avatar_latencies.append(receipt.first_avatar_ms - receipt.speech_start_ms)
            if receipt.addressed_to not in {"star", "group"}:
                false_nonstar_backchannels += 1
        elif receipt.first_avatar_ms is not None:
            unexpected_avatar += 1

        if receipt.expected_action == "yield" and receipt.observed_action != "yield":
            missed_interruptions += 1
        if receipt.observed_action == "yield" and receipt.expected_action != "yield":
            false_interruptions += 1
        if receipt.observed_action == "yield":
            if not receipt.assistant_active_at_start:
                yield_without_active_assistant += 1
            if receipt.interrupt_detected_ms is None or receipt.assistant_stop_ms is None:
                missing_stop += 1
            else:
                stop_latencies.append(receipt.assistant_stop_ms - receipt.interrupt_detected_ms)

        if receipt.speaker_role == "background" and receipt.observed_action in {"respond", "backchannel"}:
            background_speech_reactions += 1
        if receipt.game_critical and receipt.expected_action in {"silence", "yield"}:
            critical_game_windows += 1
            if receipt.observed_action in {"respond", "backchannel"}:
                critical_game_chatter += 1

    scenario_accuracies = []
    for scenario_id, rows in scenario_rows.items():
        accuracy = sum(r.expected_action == r.observed_action for r in rows) / len(rows)
        scenario_accuracies.append({
            "scenario_key": hashlib.sha256(scenario_id.encode("utf-8")).hexdigest()[:12],
            "events": len(rows),
            "action_accuracy": round(accuracy, 4),
        })
    scenario_accuracies.sort(key=lambda row: (row["action_accuracy"], row["scenario_key"]))
    per_speaker_role = {}
    for role in sorted(SPEAKER_ROLES):
        rows = [r for r in selected if r.speaker_role == role]
        if rows:
            per_speaker_role[role] = {
                "events": len(rows),
                "action_accuracy": round(sum(r.expected_action == r.observed_action for r in rows) / len(rows), 4),
                "false_responses": sum(r.observed_action == "respond" and r.addressed_to not in {"star", "group"} for r in rows),
                "false_backchannels": sum(r.observed_action == "backchannel" and r.addressed_to not in {"star", "group"} for r in rows),
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "star_voice_duplex_evaluation",
        "split": split or "all",
        "event_count": count,
        "scenario_count": len(scenario_rows),
        "action_accuracy": round(exact / count, 4),
        "actions": per_action,
        "correct_silence_rate": _ratio(
            sum(r.expected_action == "silence" and r.observed_action == "silence" for r in selected),
            sum(r.expected_action == "silence" for r in selected),
        ),
        "false_response_to_nonstar_speech": false_nonstar_responses,
        "false_backchannel_to_nonstar_speech": false_nonstar_backchannels,
        "false_interruptions": false_interruptions,
        "missed_interruptions": missed_interruptions,
        "yield_without_active_assistant": yield_without_active_assistant,
        "background_speech_reactions": background_speech_reactions,
        "per_speaker_role": per_speaker_role,
        "critical_game_chatter": {
            "events": critical_game_windows,
            "false_speech": critical_game_chatter,
            "rate": _ratio(critical_game_chatter, critical_game_windows),
        },
        "grounding": {
            "verified_response_count": grounding_known,
            "grounded_response_rate": _ratio(grounding_passed, grounding_known),
        },
        "missing_receipts": {
            "first_audio": missing_audio,
            "first_avatar": missing_avatar,
            "interrupt_stop_pair": missing_stop,
            "unexpected_audio": unexpected_audio,
            "unexpected_avatar": unexpected_avatar,
        },
        "early_receipts": {
            "first_audio_before_turn_end": early_responses,
            "avatar_before_speech_start": early_avatar_cues,
        },
        "latency_ms": {
            "turn_end_to_first_audio": _latency(response_latencies),
            "speech_start_to_first_avatar": _latency(avatar_latencies),
            "interrupt_detect_to_stop": _latency(stop_latencies),
        },
        "scenario_accuracy": scenario_accuracies,
        "percentile_method": "nearest-rank",
        "limitations": (
            "Scores supplied annotations and host receipts only. It does not process audio, "
            "identify speakers, authenticate the host, judge response semantics, or authorize "
            "microphone, TTS, avatar, game, OBS, or broadcast actions. Use a sealed holdout and "
            "independent human annotations before changing live behavior."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate content-free STAR full-duplex turn receipts.")
    parser.add_argument("input", type=Path, help="UTF-8 JSONL with labels and host-observed receipts")
    parser.add_argument("--split", choices=sorted(SPLITS), help="evaluate only development or holdout rows")
    parser.add_argument("--output", type=Path, help="write aggregate JSON report; no event-level content is copied")
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
