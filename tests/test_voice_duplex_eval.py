"""Regression tests for the content-free full-duplex voice evaluator."""
import json
from pathlib import Path
import tempfile
import unittest

from star.voice import duplex_eval


def row(**overrides):
    value = {
        "scenario_id": "scenario-1",
        "event_id": "event-1",
        "split": "holdout",
        "speaker_role": "viewer",
        "addressed_to": "star",
        "expected_action": "respond",
        "observed_action": "respond",
        "speech_start_ms": 100,
        "speech_end_ms": 900,
        "turn_end_ms": 1000,
        "assistant_active_at_start": False,
        "game_critical": False,
        "interrupt_detected_ms": None,
        "assistant_stop_ms": None,
        "first_audio_ms": 1300,
        "first_avatar_ms": None,
        "grounding_verified": True,
    }
    value.update(overrides)
    return value


def parsed(**overrides):
    return duplex_eval.TurnReceipt.parse(row(**overrides))


class DuplexEvaluationTests(unittest.TestCase):
    def test_scores_actions_and_separate_latency_channels(self):
        receipts = [
            parsed(),
            parsed(scenario_id="scenario-1", event_id="event-2", expected_action="backchannel",
                   observed_action="backchannel", addressed_to="group", speech_start_ms=2000,
                   speech_end_ms=2400, turn_end_ms=2500, first_audio_ms=None,
                   first_avatar_ms=2120, grounding_verified=None),
            parsed(scenario_id="scenario-2", event_id="event-3", expected_action="silence",
                   observed_action="respond", addressed_to="other", speaker_role="background",
                   speech_start_ms=3000, speech_end_ms=3200, turn_end_ms=3300,
                   first_audio_ms=3600, grounding_verified=False, game_critical=True),
            parsed(scenario_id="scenario-2", event_id="event-4", expected_action="yield",
                   observed_action="silence", assistant_active_at_start=True,
                   speech_start_ms=4000, speech_end_ms=4300, turn_end_ms=4400,
                   first_audio_ms=None, grounding_verified=None),
            parsed(scenario_id="scenario-3", event_id="event-5", expected_action="continue",
                   observed_action="yield", assistant_active_at_start=True,
                   speech_start_ms=5000, speech_end_ms=5200, turn_end_ms=5300,
                   interrupt_detected_ms=5010, assistant_stop_ms=5090,
                   first_audio_ms=None, grounding_verified=None),
            parsed(scenario_id="scenario-3", event_id="event-6", expected_action="silence",
                   observed_action="silence", addressed_to="none", speaker_role="other",
                   speech_start_ms=6000, speech_end_ms=6200, turn_end_ms=6300,
                   first_audio_ms=None, grounding_verified=None),
        ]
        report = duplex_eval.evaluate(receipts, split="holdout")
        self.assertEqual(report["event_count"], 6)
        self.assertEqual(report["action_accuracy"], 0.5)
        self.assertEqual(report["false_response_to_nonstar_speech"], 1)
        self.assertEqual(report["false_backchannel_to_nonstar_speech"], 0)
        self.assertEqual(report["false_interruptions"], 1)
        self.assertEqual(report["missed_interruptions"], 1)
        self.assertEqual(report["critical_game_chatter"]["false_speech"], 1)
        self.assertEqual(report["latency_ms"]["turn_end_to_first_audio"]["p50_ms"], 300)
        self.assertEqual(report["latency_ms"]["turn_end_to_first_audio"]["p95_ms"], 300)
        self.assertEqual(report["latency_ms"]["speech_start_to_first_avatar"]["p50_ms"], 120)
        self.assertEqual(report["latency_ms"]["interrupt_detect_to_stop"]["p50_ms"], 80)
        self.assertEqual(report["grounding"]["verified_response_count"], 2)
        self.assertEqual(report["grounding"]["grounded_response_rate"], 0.5)
        self.assertEqual(report["scenario_count"], 3)
        self.assertNotIn("event-1", json.dumps(report))

    def test_split_filter_does_not_mix_development_and_holdout(self):
        receipts = [
            parsed(event_id="dev", split="development"),
            parsed(event_id="hold", split="holdout", observed_action="silence"),
        ]
        report = duplex_eval.evaluate(receipts, split="development")
        self.assertEqual(report["event_count"], 1)
        self.assertEqual(report["split"], "development")
        with self.assertRaises(ValueError):
            duplex_eval.evaluate(receipts, split="unknown")

    def test_missing_and_unexpected_output_receipts_are_visible(self):
        receipts = [
            parsed(event_id="missing-audio", first_audio_ms=None),
            parsed(event_id="missing-avatar", expected_action="backchannel", observed_action="backchannel",
                   first_audio_ms=None, first_avatar_ms=None),
            parsed(event_id="stray-audio", expected_action="silence", observed_action="silence",
                   first_audio_ms=1400, first_avatar_ms=None),
            parsed(event_id="stray-avatar", expected_action="silence", observed_action="silence",
                   first_audio_ms=None, first_avatar_ms=1400),
            parsed(event_id="missing-stop", expected_action="yield", observed_action="yield",
                   assistant_active_at_start=True, first_audio_ms=None),
        ]
        report = duplex_eval.evaluate(receipts)
        self.assertEqual(report["missing_receipts"], {
            "first_audio": 1,
            "first_avatar": 1,
            "interrupt_stop_pair": 1,
            "unexpected_audio": 1,
            "unexpected_avatar": 1,
        })

    def test_early_audio_and_avatar_receipts_are_not_folded_into_latency(self):
        receipts = [
            parsed(first_audio_ms=900),
            parsed(event_id="early-avatar", expected_action="backchannel", observed_action="backchannel",
                   first_audio_ms=None, first_avatar_ms=90),
        ]
        report = duplex_eval.evaluate(receipts)
        self.assertEqual(report["early_receipts"]["first_audio_before_turn_end"], 1)
        self.assertEqual(report["early_receipts"]["avatar_before_speech_start"], 1)
        self.assertEqual(report["latency_ms"]["turn_end_to_first_audio"]["count"], 0)
        self.assertEqual(report["latency_ms"]["speech_start_to_first_avatar"]["count"], 0)

    def test_background_role_is_aggregated_without_exposing_event_identity(self):
        receipts = [
            parsed(speaker_role="background", addressed_to="unknown"),
            parsed(event_id="viewer", speaker_role="viewer", addressed_to="star"),
        ]
        report = duplex_eval.evaluate(receipts)
        self.assertIn("per_speaker_role", report)
        self.assertEqual(report["per_speaker_role"]["background"]["false_responses"], 1)
        self.assertNotIn("scenario-1", json.dumps(report))

    def test_rejects_transcripts_audio_and_unknown_fields(self):
        for key, value in (("transcript", "private words"), ("audio_base64", "AAAA"), ("viewer_id", "abc")):
            candidate = row()
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                duplex_eval.TurnReceipt.parse(candidate)

    def test_rejects_unhashable_enum_and_boolean_timestamp(self):
        candidate = row()
        candidate["split"] = []
        with self.assertRaises(ValueError):
            duplex_eval.TurnReceipt.parse(candidate)
        candidate = row()
        candidate["speech_start_ms"] = True
        with self.assertRaises(ValueError):
            duplex_eval.TurnReceipt.parse(candidate)

    def test_rejects_invalid_time_order_and_stop_before_detection(self):
        candidate = row(speech_start_ms=900, speech_end_ms=800)
        with self.assertRaises(ValueError):
            duplex_eval.TurnReceipt.parse(candidate)
        candidate = row(expected_action="yield", observed_action="yield",
                        assistant_active_at_start=True, interrupt_detected_ms=500,
                        assistant_stop_ms=400)
        with self.assertRaises(ValueError):
            duplex_eval.TurnReceipt.parse(candidate)

    def test_jsonl_rejects_duplicate_keys_nonfinite_and_duplicate_events(self):
        valid = json.dumps(row())
        duplicate_key = valid[:-1] + ', "event_id": "different"}'
        nonfinite = valid.replace('"speech_start_ms": 100', '"speech_start_ms": NaN')
        duplicate_event = valid + "\n" + valid
        for payload in (duplicate_key, nonfinite, duplicate_event):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "events.jsonl"
                path.write_text(payload, encoding="utf-8")
                with self.subTest(payload=payload[:60]), self.assertRaises(ValueError):
                    duplex_eval.load_jsonl(path)

    def test_jsonl_valid_input_and_cli_report_are_aggregate_only(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "events.jsonl"
            output = Path(directory) / "report.json"
            source.write_text(json.dumps(row()) + "\n", encoding="utf-8")
            receipts = duplex_eval.load_jsonl(source)
            report = duplex_eval.evaluate(receipts)
            output.write_text(json.dumps(report), encoding="utf-8")
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["kind"], "star_voice_duplex_evaluation")
            self.assertNotIn("private words", output.read_text(encoding="utf-8"))
            self.assertEqual(duplex_eval.main([str(source), "--output", str(output)]), 0)

    def test_rejects_empty_or_unparsed_evaluation_input(self):
        with self.assertRaises(ValueError):
            duplex_eval.evaluate([])
        with self.assertRaises(ValueError):
            duplex_eval.evaluate([row()])


if __name__ == "__main__":
    unittest.main()
