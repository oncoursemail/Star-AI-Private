"""Synthetic paired VTuber turn timing and safety checks; no I/O or recordings."""
import math
import unittest

from star.stream_social_turn_benchmark import (
    SCENARIOS, SocialTurnMoment, assess_social_turns,
)


def case(index, scenario, variant, **overrides):
    data = dict(
        case_id=f"{scenario}-{index}", variant=variant, scenario=scenario,
        independently_reviewed=True,
    )
    if scenario == "viewer_question":
        data.update(first_audible_ms=600, overlap_ms=15)
    elif scenario == "owner_barge_in":
        data.update(interrupted=True, playback_stop_ms=125)
    elif scenario == "gameplay_commentary":
        data.update(first_audible_ms=250, overlap_ms=0)
    data.update(overrides)
    return SocialTurnMoment(**data)


def batch():
    return [case(i, scenario, variant) for scenario in SCENARIOS
            for i in range(4) for variant in ("baseline", "candidate")]


class SocialTurnBenchmarkTests(unittest.TestCase):
    def test_full_reviewed_balanced_synthetic_case_only_allows_rehearsal(self):
        report = assess_social_turns(batch())
        self.assertEqual(report.status, "eligible_for_manual_rehearsal")
        self.assertEqual(report.complete_pairs, 20)
        self.assertEqual(report.reviewed_moments, 40)
        self.assertEqual(report.candidate_question_p95_ms, 600)
        self.assertEqual(report.candidate_stop_p95_ms, 125)
        self.assertEqual(report.candidate_failures, 0)
        self.assertEqual(report.candidate_pair_regressions, 0)
        self.assertFalse(report.authorized_to_stream)

    def test_missing_variant_or_coverage_never_passes(self):
        rows = batch()
        self.assertEqual(assess_social_turns(rows[:-1]).status, "insufficient_evidence")
        rows = batch()
        rows[1] = case(0, "viewer_question", "candidate", independently_reviewed=False)
        self.assertEqual(assess_social_turns(rows).status, "insufficient_evidence")

    def test_true_owner_barge_in_must_actually_stop_audio(self):
        rows = batch()
        idx = next(i for i, r in enumerate(rows) if r.scenario == "owner_barge_in" and r.variant == "candidate")
        rows[idx] = case(0, "owner_barge_in", "candidate", interrupted=False, playback_stop_ms=None)
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "naturalness_regressed")
        self.assertEqual(report.candidate_missed_barge_ins, 1)
        self.assertEqual(report.new_case_regressions, 1)

    def test_barge_in_slow_shutdown_is_a_regression(self):
        rows = batch()
        idx = next(i for i, r in enumerate(rows) if r.scenario == "owner_barge_in" and r.variant == "candidate")
        rows[idx] = case(0, "owner_barge_in", "candidate", playback_stop_ms=600)
        self.assertEqual(assess_social_turns(rows).status, "naturalness_regressed")

    def test_false_interruptions_from_noise_fail(self):
        rows = batch()
        idx = next(i for i, r in enumerate(rows) if r.scenario == "incidental_noise" and r.variant == "candidate")
        rows[idx] = case(0, "incidental_noise", "candidate", interrupted=True, playback_stop_ms=75)
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "naturalness_regressed")
        self.assertEqual(report.candidate_false_interruptions, 1)

    def test_gameplay_focus_blocks_nonessential_speech(self):
        rows = batch()
        idx = next(i for i, r in enumerate(rows) if r.scenario == "critical_gameplay" and r.variant == "candidate")
        rows[idx] = case(0, "critical_gameplay", "candidate", first_audible_ms=10)
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "naturalness_regressed")
        self.assertEqual(report.candidate_critical_speech, 1)

    def test_grounding_and_speech_overlap_measured(self):
        for kwargs in (dict(grounded=False), dict(overlap_ms=400)):
            rows = batch()
            idx = next(i for i, r in enumerate(rows) if r.scenario == "viewer_question" and r.variant == "candidate")
            rows[idx] = case(0, "viewer_question", "candidate", **kwargs)
            self.assertEqual(assess_social_turns(rows).status, "naturalness_regressed")

    def test_candidate_can_pass_absolute_latency_but_still_regress_over_baseline(self):
        rows = [case(i, "viewer_question", variant, first_audible_ms=(500 if variant == "baseline" else 1000))
                if scenario == "viewer_question" else case(i, scenario, variant)
                for scenario in SCENARIOS for i in range(4) for variant in ("baseline", "candidate")]
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "naturalness_regressed")
        self.assertEqual(report.candidate_failures, 0)
        self.assertEqual(report.candidate_question_p95_ms, 1000)

    def test_single_question_regression_cannot_hide_under_p95(self):
        rows = batch()
        rows += [case(i, "viewer_question", variant)
                 for i in range(4, 20) for variant in ("baseline", "candidate")]
        idx = next(i for i, r in enumerate(rows) if r.scenario == "viewer_question"
                   and r.case_id == "viewer_question-19" and r.variant == "candidate")
        rows[idx] = case(19, "viewer_question", "candidate", first_audible_ms=1350)
        result = assess_social_turns(rows)
        # With 20 questions, the highest outlier is outside nearest-rank p95:
        # the old pooled comparison would have silently approved this slowdown.
        self.assertEqual(result.baseline_question_p95_ms, 600)
        self.assertEqual(result.candidate_question_p95_ms, 600)
        self.assertEqual(result.candidate_failures, 0)
        self.assertEqual(result.candidate_pair_regressions, 1)
        self.assertEqual(result.status, "naturalness_regressed")

    def test_silent_candidate_cannot_pass_by_dropping_expected_commentary(self):
        rows = batch()
        for index, row in enumerate(rows):
            if row.scenario == "gameplay_commentary" and row.variant == "candidate":
                rows[index] = case(
                    int(row.case_id.rsplit("-", 1)[-1]), "gameplay_commentary",
                    "candidate", first_audible_ms=None, overlap_ms=None,
                )
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "naturalness_regressed")
        self.assertEqual(report.candidate_dropped_commentary, 4)
        self.assertEqual(report.candidate_pair_regressions, 4)
        self.assertEqual(report.candidate_failures, 0)

    def test_single_commentary_latency_regression_is_not_hidden_by_question_p95(self):
        rows = batch()
        idx = next(i for i, row in enumerate(rows)
                   if row.case_id == "gameplay_commentary-3"
                   and row.variant == "candidate")
        rows[idx] = case(3, "gameplay_commentary", "candidate", first_audible_ms=900)
        report = assess_social_turns(rows)
        self.assertEqual(report.candidate_late_commentary, 1)
        self.assertEqual(report.candidate_pair_regressions, 1)
        self.assertEqual(report.candidate_failures, 0)
        self.assertEqual(report.status, "naturalness_regressed")

    def test_commentary_absolute_delay_is_not_a_realtime_reaction(self):
        rows = batch()
        idx = next(i for i, row in enumerate(rows)
                   if row.case_id == "gameplay_commentary-0"
                   and row.variant == "candidate")
        rows[idx] = case(0, "gameplay_commentary", "candidate", first_audible_ms=3500)
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "naturalness_regressed")
        self.assertEqual(report.candidate_failures, 1)

    def test_contextual_silence_and_small_commentary_delay_still_pass(self):
        rows = batch()
        for index, row in enumerate(rows):
            if row.case_id == "gameplay_commentary-0":
                rows[index] = case(0, "gameplay_commentary", row.variant,
                                   first_audible_ms=None, overlap_ms=None)
            elif row.case_id == "gameplay_commentary-1" and row.variant == "candidate":
                rows[index] = case(1, "gameplay_commentary", "candidate",
                                   first_audible_ms=650)
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "eligible_for_manual_rehearsal")
        self.assertEqual(report.candidate_dropped_commentary, 0)
        self.assertEqual(report.candidate_late_commentary, 0)

    def test_commentary_timing_thresholds_are_strict_bounded_inputs(self):
        for kwargs in (
            {"max_commentary_first_audible_ms": 0},
            {"max_commentary_first_audible_ms": float("inf")},
            {"max_pair_commentary_regression_ms": True},
            {"max_pair_commentary_regression_ms": 10001},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                assess_social_turns(batch(), **kwargs)

    def test_single_owner_stop_regression_cannot_hide_under_p95(self):
        rows = batch()
        rows += [case(i, "owner_barge_in", variant)
                 for i in range(4, 20) for variant in ("baseline", "candidate")]
        idx = next(i for i, r in enumerate(rows) if r.scenario == "owner_barge_in"
                   and r.case_id == "owner_barge_in-19" and r.variant == "candidate")
        rows[idx] = case(19, "owner_barge_in", "candidate", playback_stop_ms=300)
        result = assess_social_turns(rows)
        self.assertEqual(result.candidate_stop_p95_ms, 125)
        self.assertEqual(result.candidate_failures, 0)
        self.assertEqual(result.candidate_pair_regressions, 1)
        self.assertEqual(result.status, "naturalness_regressed")

    def test_small_pairwise_variation_keeps_rehearsal_eligibility(self):
        rows = batch()
        rows[1] = case(0, "viewer_question", "candidate", first_audible_ms=650)
        idx = next(i for i, r in enumerate(rows) if r.scenario == "owner_barge_in"
                   and r.case_id == "owner_barge_in-0" and r.variant == "candidate")
        rows[idx] = case(0, "owner_barge_in", "candidate", playback_stop_ms=190)
        result = assess_social_turns(rows)
        self.assertEqual(result.candidate_pair_regressions, 0)
        self.assertEqual(result.status, "eligible_for_manual_rehearsal")

    def test_invalid_pairwise_limits_never_loosen_audit(self):
        for kwargs in ({"max_pair_question_regression_ms": 0},
                       {"max_pair_stop_regression_ms": True},
                       {"max_pair_stop_regression_ms": float("nan")},):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                assess_social_turns(batch(), **kwargs)

    def test_baseline_missing_quoted_audio_cannot_claim_latency_gain(self):
        rows = batch()
        idx = next(i for i, r in enumerate(rows) if r.scenario == "viewer_question" and r.variant == "baseline")
        rows[idx] = case(0, "viewer_question", "baseline", first_audible_ms=None, overlap_ms=None)
        self.assertEqual(assess_social_turns(rows).status, "naturalness_regressed")

    def test_question_must_not_be_silently_dropped(self):
        rows = batch()
        idx = next(i for i, r in enumerate(rows) if r.scenario == "viewer_question" and r.variant == "candidate")
        rows[idx] = case(0, "viewer_question", "candidate", first_audible_ms=None, overlap_ms=None)
        self.assertEqual(assess_social_turns(rows).status, "naturalness_regressed")

    def test_duplicate_case_or_scenario_swap_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_social_turns(batch() + [batch()[0]])
        rows = batch()
        rows[1] = SocialTurnMoment(case_id=rows[0].case_id, variant="candidate",
                                   scenario="critical_gameplay", independently_reviewed=True)
        with self.assertRaises(ValueError):
            assess_social_turns(rows)

    def test_long_unplanned_audio_gap_fails_even_with_fast_first_word(self):
        rows = batch()
        for index, row in enumerate(rows):
            if row.scenario in ("viewer_question", "gameplay_commentary"):
                rows[index] = case(
                    int(row.case_id.rsplit("-", 1)[-1]), row.scenario, row.variant,
                    max_unplanned_gap_ms=(800 if row.case_id == "viewer_question-0"
                                          and row.variant == "candidate" else 100),
                )
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "naturalness_regressed")
        self.assertEqual(report.candidate_stutter_regressions, 1)
        self.assertEqual(report.candidate_question_p95_ms, 600)

    def test_relative_playback_gap_regression_is_caught_below_absolute_limit(self):
        rows = batch()
        rows[0] = case(0, "viewer_question", "baseline", max_unplanned_gap_ms=120)
        rows[1] = case(0, "viewer_question", "candidate", max_unplanned_gap_ms=410)
        report = assess_social_turns(rows)
        self.assertEqual(report.candidate_failures, 0)
        self.assertEqual(report.candidate_stutter_regressions, 1)
        self.assertEqual(report.status, "naturalness_regressed")

    def test_partial_audio_gap_instrumentation_is_not_accepted(self):
        rows = batch()
        rows[1] = case(0, "viewer_question", "candidate", max_unplanned_gap_ms=100)
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "insufficient_evidence")

    def test_matched_smooth_playback_remains_eligible(self):
        rows = batch()
        for index, row in enumerate(rows):
            if row.scenario in ("viewer_question", "gameplay_commentary"):
                rows[index] = case(
                    int(row.case_id.rsplit("-", 1)[-1]), row.scenario, row.variant,
                    max_unplanned_gap_ms=100,
                )
        report = assess_social_turns(rows)
        self.assertEqual(report.status, "eligible_for_manual_rehearsal")
        self.assertEqual(report.candidate_stutter_regressions, 0)

    def test_gap_evidence_is_strictly_numeric_and_only_for_audible_speech(self):
        for gap in (True, float("nan"), float("inf"), 60_001, "100", object()):
            with self.subTest(gap=str(type(gap))), self.assertRaises(ValueError):
                case(0, "viewer_question", "candidate", max_unplanned_gap_ms=gap)
        with self.assertRaises(ValueError):
            case(0, "critical_gameplay", "candidate", max_unplanned_gap_ms=100)
        with self.assertRaises(ValueError):
            case(0, "gameplay_commentary", "candidate", first_audible_ms=None,
                 overlap_ms=None, max_unplanned_gap_ms=100)
        with self.assertRaises(ValueError):
            assess_social_turns(batch(), max_pair_gap_regression_ms=True)

    def test_boolean_nan_and_shape_validation(self):
        with self.assertRaises(ValueError):
            case(0, "viewer_question", "baseline", first_audible_ms=math.nan)
        with self.assertRaises(ValueError):
            case(0, "owner_barge_in", "candidate", playback_stop_ms=None)
        with self.assertRaises(ValueError):
            case(0, "incidental_noise", "candidate", interrupted=1)
        with self.assertRaises(ValueError):
            case(0, "viewer_question", "candidate", overlap_ms=None)
        with self.assertRaises(ValueError):
            assess_social_turns(batch(), minimum_per_scenario=True)
        with self.assertRaises(ValueError):
            assess_social_turns(batch(), max_overlap_ms=float("inf"))

    def test_required_scenario_roster_cannot_be_cherry_picked(self):
        rows = [x for x in batch() if x.scenario != "owner_barge_in"]
        self.assertEqual(assess_social_turns(rows).status, "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
