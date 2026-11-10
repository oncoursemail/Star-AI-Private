"""Regression tests for the content-free voice interaction quality evaluator."""
import json
from pathlib import Path
import tempfile
import unittest

from star.voice import interaction_eval


def row(**overrides):
    value = {
        "scenario_id": "scenario-1",
        "event_id": "event-1",
        "conversation_id": "conversation-1",
        "split": "holdout",
        "turn_index": 1,
        "context_turn_count": 4,
        "expected_style": "neutral",
        "observed_style": "neutral",
        "audio_present": True,
        "expected_rms_min_dbfs": -30.0,
        "expected_rms_max_dbfs": -15.0,
        "measured_rms_dbfs": -22.0,
        "measured_true_peak_dbfs": -4.0,
        "whisper_hnr_db": None,
        "voiced_fraction": None,
        "grounding_required": True,
        "grounding_verified": True,
        "task_required": True,
        "task_verified": True,
        "conversation_coherence": 92,
    }
    value.update(overrides)
    return value


def parsed(**overrides):
    return interaction_eval.InteractionReceipt.parse(row(**overrides))


class InteractionEvaluationTests(unittest.TestCase):
    def test_scores_style_volume_whisper_long_context_tasks_and_coherence_separately(self):
        receipts = [
            parsed(),
            parsed(
                scenario_id="scenario-2", event_id="event-2", conversation_id="conversation-2",
                expected_style="whisper", observed_style="whisper",
                expected_rms_min_dbfs=-55.0, expected_rms_max_dbfs=-35.0,
                measured_rms_dbfs=-44.0, measured_true_peak_dbfs=-28.0,
                whisper_hnr_db=5.5, voiced_fraction=0.35,
                grounding_required=False, grounding_verified=None,
                task_required=False, task_verified=None, conversation_coherence=88,
            ),
            parsed(
                scenario_id="scenario-3", event_id="event-3", conversation_id="conversation-3",
                turn_index=21, context_turn_count=24, conversation_coherence=95,
            ),
        ]
        report = interaction_eval.evaluate(receipts, split="holdout")
        self.assertEqual(report["event_count"], 3)
        self.assertEqual(report["delivery_style"]["accuracy"], 1.0)
        self.assertEqual(report["volume"]["in_range_rate_required"], 1.0)
        self.assertEqual(report["whisper"]["pass_rate_required"], 1.0)
        self.assertEqual(report["grounding"]["long_context"]["pass_rate_required"], 1.0)
        self.assertEqual(report["spoken_task"]["pass_rate_required"], 1.0)
        self.assertEqual(report["conversation_coherence"]["mean"], 91.67)
        self.assertNotIn("conversation-1", json.dumps(report))
        self.assertNotIn("event-1", json.dumps(report))

    def test_style_and_volume_failures_are_not_hidden_by_other_dimensions(self):
        receipts = [
            parsed(observed_style="warm", measured_rms_dbfs=-10.0),
            parsed(
                scenario_id="scenario-2", event_id="event-2", conversation_id="conversation-2",
                expected_style="whisper", observed_style="projected",
                expected_rms_min_dbfs=-55.0, expected_rms_max_dbfs=-35.0,
                measured_rms_dbfs=-12.0, measured_true_peak_dbfs=1.0,
                whisper_hnr_db=8.0, voiced_fraction=0.6,
                grounding_verified=False, task_verified=False,
            ),
        ]
        report = interaction_eval.evaluate(receipts)
        self.assertEqual(report["delivery_style"]["accuracy"], 0.0)
        self.assertEqual(report["volume"]["out_of_range"], 2)
        self.assertEqual(report["whisper"]["acoustic_passed"], 0)
        self.assertEqual(report["volume"]["over_full_scale_peaks"], 1)
        self.assertEqual(report["grounding"]["short_context"]["pass_rate_required"], 0.5)
        self.assertEqual(report["spoken_task"]["pass_rate_required"], 0.5)

    def test_missing_audio_and_missing_evidence_count_as_failures_in_required_rates(self):
        receipts = [
            parsed(
                audio_present=False, observed_style="muted",
                measured_rms_dbfs=None, measured_true_peak_dbfs=None,
                grounding_verified=None, task_verified=None, conversation_coherence=None,
            ),
            parsed(
                scenario_id="scenario-2", event_id="event-2", conversation_id="conversation-2",
                expected_style="whisper", observed_style="muted", audio_present=False,
                expected_rms_min_dbfs=-60.0, expected_rms_max_dbfs=-40.0,
                measured_rms_dbfs=None, measured_true_peak_dbfs=None,
                grounding_verified=None, task_verified=None, conversation_coherence=None,
            ),
        ]
        report = interaction_eval.evaluate(receipts)
        self.assertEqual(report["volume"]["missing_audio"], 2)
        self.assertEqual(report["volume"]["in_range_rate_required"], 0.0)
        self.assertEqual(report["whisper"]["missing_measurements"], 1)
        self.assertEqual(report["grounding"]["all_contexts"]["evidence_coverage"], 0.0)
        self.assertEqual(report["spoken_task"]["pass_rate_required"], 0.0)
        self.assertEqual(report["missing_evidence"]["conversation_coherence"], 2)

    def test_muted_expectation_is_scored_without_inventing_an_rms_value(self):
        receipt = parsed(
            expected_style="muted", observed_style="muted", audio_present=False,
            expected_rms_min_dbfs=None, expected_rms_max_dbfs=None,
            measured_rms_dbfs=None, measured_true_peak_dbfs=None,
            grounding_required=False, grounding_verified=None,
            task_required=False, task_verified=None,
        )
        report = interaction_eval.evaluate([receipt])
        self.assertEqual(report["volume"]["muted_correct_rate"], 1.0)
        self.assertEqual(report["volume"]["unexpected_audio"], 0)
        self.assertIsNone(report["volume"]["in_range_rate_required"])

    def test_short_and_long_context_grounding_are_reported_separately(self):
        receipts = [
            parsed(conversation_coherence=90),
            parsed(
                scenario_id="scenario-2", event_id="event-2", conversation_id="conversation-2",
                turn_index=22, context_turn_count=21, grounding_verified=False,
                conversation_coherence=70,
            ),
        ]
        report = interaction_eval.evaluate(receipts)
        self.assertEqual(report["grounding"]["short_context"]["pass_rate_required"], 1.0)
        self.assertEqual(report["grounding"]["long_context"]["pass_rate_required"], 0.0)

    def test_split_filter_does_not_mix_development_and_holdout(self):
        receipts = [
            parsed(event_id="dev", split="development"),
            parsed(
                scenario_id="scenario-2", event_id="hold", conversation_id="conversation-2",
                split="holdout", observed_style="muted", audio_present=False,
                measured_rms_dbfs=None, measured_true_peak_dbfs=None,
            ),
        ]
        report = interaction_eval.evaluate(receipts, split="development")
        self.assertEqual(report["event_count"], 1)
        self.assertEqual(report["split"], "development")
        with self.assertRaises(ValueError):
            interaction_eval.evaluate(receipts, split=[])

    def test_rejects_raw_audio_transcripts_viewer_identity_and_unknown_fields(self):
        for key, value in (
            ("transcript", "private words"), ("audio_base64", "AAAA"), ("viewer_id", "viewer-1"),
            ("prompt", "secret prompt"),
        ):
            candidate = row()
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                interaction_eval.InteractionReceipt.parse(candidate)

    def test_rejects_inconsistent_audio_and_style_receipts(self):
        invalid = [
            row(audio_present=False, observed_style="neutral", measured_rms_dbfs=None, measured_true_peak_dbfs=None),
            row(audio_present=True, observed_style="muted"),
            row(expected_style="muted", expected_rms_min_dbfs=-60.0, expected_rms_max_dbfs=-40.0),
            row(expected_rms_min_dbfs=-10.0, expected_rms_max_dbfs=-20.0),
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                interaction_eval.InteractionReceipt.parse(candidate)

    def test_rejects_invalid_boolean_numeric_and_acoustic_values(self):
        invalid = [
            row(audio_present=1),
            row(turn_index=True),
            row(context_turn_count=-1),
            row(measured_rms_dbfs=True),
            row(measured_true_peak_dbfs=float("inf")),
            row(measured_rms_dbfs=10 ** 1000),
            row(expected_rms_min_dbfs=float("nan")),
            row(voiced_fraction=1.1),
            row(whisper_hnr_db=101.0),
            row(grounding_required=False, grounding_verified=True),
            row(task_required=False, task_verified=False),
            row(conversation_coherence=101),
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                interaction_eval.InteractionReceipt.parse(candidate)

    def test_rejects_duplicate_event_turn_and_conversation_coherence(self):
        first = row()
        duplicate_event = row(conversation_id="conversation-2")
        duplicate_turn = row(scenario_id="scenario-2", event_id="event-2")
        duplicate_coherence = row(scenario_id="scenario-3", event_id="event-3", turn_index=2)
        for rows in (
            [first, first],
            [first, duplicate_event],
            [first, duplicate_turn],
            [first, duplicate_coherence],
        ):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "receipts.jsonl"
                path.write_text("\n".join(json.dumps(item) for item in rows), encoding="utf-8")
                with self.assertRaises(ValueError):
                    interaction_eval.load_jsonl(path)

    def test_jsonl_rejects_duplicate_keys_nonfinite_and_blank_lines(self):
        valid = json.dumps(row())
        duplicate_key = valid[:-1] + ', "event_id": "different"}'
        nonfinite = valid.replace('"measured_rms_dbfs": -22.0', '"measured_rms_dbfs": NaN')
        for payload in (duplicate_key, nonfinite, valid + "\n\n"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "receipts.jsonl"
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(ValueError):
                    interaction_eval.load_jsonl(path)

    def test_cli_writes_aggregate_only_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "receipts.jsonl"
            output = Path(directory) / "report.json"
            source.write_text(json.dumps(row()) + "\n", encoding="utf-8")
            self.assertEqual(interaction_eval.main([str(source), "--output", str(output)]), 0)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["kind"], "star_voice_interaction_quality_evaluation")
            self.assertNotIn("conversation-1", output.read_text(encoding="utf-8"))

    def test_rejects_empty_or_unparsed_evaluation_input(self):
        with self.assertRaises(ValueError):
            interaction_eval.evaluate([])
        with self.assertRaises(ValueError):
            interaction_eval.evaluate([row()])


if __name__ == "__main__":
    unittest.main()
