"""Tests for STAR's privacy-safe proactive response timing evaluator."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import pytest

from star.stream_response_timing_benchmark import (
    StreamResponseObservation,
    StreamResponseWindow,
    assess_stream_response_timing,
)


def window(
    event_id: str,
    expected: str,
    *,
    kind: str = "viewer_question",
    scored: bool = True,
    observed: float = 1000,
    opens: float | None = None,
    deadline: float = 3000,
) -> StreamResponseWindow:
    return StreamResponseWindow(
        session_id="session-1",
        event_id=event_id,
        event_kind=kind,
        observed_at_ms=observed,
        opens_at_ms=observed if opens is None else opens,
        deadline_at_ms=deadline,
        expected_action=expected,
        independently_scored=scored,
    )


def observation(
    event_id: str,
    decision: str,
    emitted: str,
    *,
    decision_at: float = 1050,
    audio_at: float | None = None,
    avatar_at: float | None = None,
    output_count: int = 1,
    grounded: bool | None = True,
) -> StreamResponseObservation:
    return StreamResponseObservation(
        session_id="session-1",
        event_id=event_id,
        decision=decision,
        decision_at_ms=decision_at,
        emitted_mode=emitted,
        output_count=output_count,
        first_audio_at_ms=audio_at,
        first_avatar_at_ms=avatar_at,
        grounded=grounded if emitted != "none" else None,
    )


def test_balanced_speak_backchannel_and_silence_cohort_is_measured():
    windows = []
    observations = []
    for index in range(7):
        event_id = f"question-{index}"
        windows.append(window(event_id, "speak", kind="viewer_question"))
        observations.append(observation(
            event_id, "speak", "speak", audio_at=1200 + index * 10,
        ))
    for index in range(6):
        event_id = f"comment-{index}"
        windows.append(window(event_id, "backchannel", kind="viewer_comment"))
        observations.append(observation(
            event_id, "backchannel", "backchannel", avatar_at=1180 + index * 10,
        ))
    for index in range(7):
        event_id = f"ambient-{index}"
        windows.append(window(event_id, "silence", kind="ambient"))
        observations.append(observation(
            event_id, "silence", "none", output_count=0, grounded=None,
        ))

    report = assess_stream_response_timing(windows, observations, minimum_events=20)
    assert report.verdict == "measured"
    assert report.events == report.scored_events == 20
    assert report.timely_grounded_responses == 13
    assert report.correct_silence == 7
    assert report.missed_responses == 0
    assert report.false_positive_responses == 0
    assert report.response_precision == 1.0
    assert report.response_recall == 1.0
    assert report.silence_precision == 1.0
    assert report.silence_recall == 1.0
    assert report.first_audio_latency_p50_ms == 230
    assert report.first_avatar_latency_p50_ms == 205
    assert report.by_event_kind["viewer_question"].timely_grounded_responses == 7
    assert report.by_event_kind["viewer_comment"].timely_grounded_responses == 6
    assert report.by_event_kind["ambient"].correct_silence == 7
    assert not report.authorized_to_act


def test_late_speech_is_missed_and_reported_as_late():
    event = window("late", "speak", deadline=1500)
    receipt = observation("late", "speak", "speak", audio_at=1600)
    report = assess_stream_response_timing([event], [receipt], minimum_events=1)
    assert report.late_outputs == 1
    assert report.missed_responses == 1
    assert report.timely_grounded_responses == 0
    assert report.response_recall == 0.0
    assert report.by_event_kind["viewer_question"].late_outputs == 1


def test_early_output_before_window_is_not_counted_as_success():
    event = window("early", "speak", opens=1200)
    receipt = observation("early", "speak", "speak", audio_at=1100)
    report = assess_stream_response_timing([event], [receipt], minimum_events=1)
    assert report.early_outputs == 1
    assert report.missed_responses == 1
    assert report.timely_grounded_responses == 0


def test_unwanted_commentary_during_expected_silence_is_false_positive():
    event = window("quiet", "silence", kind="ambient")
    receipt = observation("quiet", "speak", "speak", audio_at=1200)
    report = assess_stream_response_timing([event], [receipt], minimum_events=1)
    assert report.false_positive_responses == 1
    assert report.correct_silence == 0
    assert report.emitted_mode_mismatches == 1
    assert report.silence_precision is None


def test_duplicate_and_ungrounded_outputs_do_not_count_as_good_response():
    event = window("duplicate", "speak")
    receipt = observation(
        "duplicate", "speak", "speak", audio_at=1200,
        output_count=3, grounded=False,
    )
    report = assess_stream_response_timing([event], [receipt], minimum_events=1)
    assert report.duplicate_outputs == 2
    assert report.ungrounded_outputs == 1
    assert report.timely_grounded_responses == 0
    assert report.missed_responses == 1
    assert report.response_precision == 0.0


def test_output_without_independent_grounding_is_not_verified():
    event = window("unverified", "speak")
    receipt = observation("unverified", "speak", "speak", audio_at=1200, grounded=None)
    report = assess_stream_response_timing([event], [receipt], minimum_events=1)
    assert report.unverified_outputs == 1
    assert report.timely_grounded_responses == 0
    assert report.missed_responses == 1


def test_wrong_modality_is_not_a_timely_response():
    event = window("wrong-mode", "speak")
    receipt = observation(
        "wrong-mode", "speak", "backchannel",
        avatar_at=1200, audio_at=None,
    )
    report = assess_stream_response_timing([event], [receipt], minimum_events=1)
    assert report.emitted_mode_mismatches == 1
    assert report.missed_responses == 1
    assert report.timely_grounded_responses == 0


def test_missing_and_unscored_events_make_cohort_inconclusive():
    windows = [
        window("missing", "speak"),
        window("unscored", "silence", scored=False),
    ]
    report = assess_stream_response_timing(windows, [], minimum_events=1)
    assert report.verdict == "inconclusive"
    assert report.missing_observations == 1
    assert report.unscored_events == 1
    assert report.missed_responses == 1


def test_decision_before_observation_is_visible_in_latency_diagnostics():
    event = window("premature", "speak")
    receipt = observation(
        "premature", "speak", "speak",
        decision_at=900, audio_at=1200,
    )
    report = assess_stream_response_timing([event], [receipt], minimum_events=1)
    assert report.early_decisions == 1
    assert report.decision_latency_p50_ms == -100


def test_duplicate_window_and_observation_identities_are_rejected():
    event = window("same", "speak")
    with pytest.raises(ValueError, match="duplicate response window"):
        assess_stream_response_timing([event, event], [])
    receipt = observation("same", "speak", "speak", audio_at=1200)
    with pytest.raises(ValueError, match="duplicate response observation"):
        assess_stream_response_timing([event], [receipt, receipt])


def test_observation_without_matching_window_is_rejected():
    receipt = observation("orphan", "silence", "none", output_count=0, grounded=None)
    with pytest.raises(ValueError, match="no matching response window"):
        assess_stream_response_timing([], [receipt])


@pytest.mark.parametrize("field,value", [
    ("observed_at_ms", True),
    ("opens_at_ms", float("nan")),
    ("deadline_at_ms", float("inf")),
    ("independently_scored", 1),
    ("expected_action", "maybe"),
    ("event_kind", "viewer_supplied"),
])
def test_invalid_window_fields_are_rejected(field, value):
    base = window("invalid", "speak")
    with pytest.raises(ValueError):
        StreamResponseWindow(**{**asdict(base), field: value})


@pytest.mark.parametrize("field,value", [
    ("decision_at_ms", True),
    ("output_count", True),
    ("grounded", "yes"),
    ("emitted_mode", "tts-ish"),
])
def test_invalid_observation_fields_are_rejected(field, value):
    base = observation("invalid", "speak", "speak", audio_at=1200)
    with pytest.raises(ValueError):
        StreamResponseObservation(**{**asdict(base), field: value})


def test_jsonl_cli_emits_aggregate_only_and_rejects_content_fields(tmp_path: Path):
    windows_path = tmp_path / "windows.jsonl"
    observations_path = tmp_path / "observations.jsonl"
    windows = [window(f"event-{index}", "silence", kind="ambient") for index in range(20)]
    observations = [
        observation(f"event-{index}", "silence", "none", output_count=0, grounded=None)
        for index in range(20)
    ]
    windows_path.write_text(
        "".join(json.dumps(asdict(item)) + "\n" for item in windows),
        encoding="utf-8",
    )
    observations_path.write_text(
        "".join(json.dumps(asdict(item)) + "\n" for item in observations),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable, "-m", "star.stream_response_timing_benchmark",
            str(windows_path), str(observations_path),
        ],
        capture_output=True, text=True, check=True,
    )
    report = json.loads(result.stdout)
    assert report["verdict"] == "measured"
    assert report["correct_silence"] == 20
    assert "event-0" not in result.stdout
    assert "session-1" not in result.stdout

    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text(
        json.dumps({**asdict(windows[0]), "transcript": "private speech"}) + "\n",
        encoding="utf-8",
    )
    bad = subprocess.run(
        [
            sys.executable, "-m", "star.stream_response_timing_benchmark",
            str(bad_path), str(observations_path),
        ],
        capture_output=True, text=True,
    )
    assert bad.returncode != 0