"""Offline adversarial checks of owner-sealed, per-game AB/BA holdout runs."""
from dataclasses import replace
import hashlib
import hmac
import unittest

from star.game_holdout_schedule import (
    CounterbalancedRunPlan, GameRunStart, SignedGameRunStart, RunSlot,
    build_counterbalanced_plan, evaluate_counterbalanced_transfer,
)
from star.game_holdout_seal import GameHoldoutPrecommit
from star.game_transfer_eval import HoldoutCase, SignedHoldoutTrial, roster_digest
from star.gameplay_skill_bank import GameTrial

COORD = b"c" * 32
STARTER = b"s" * 32
EVALUATOR = b"e" * 32
NOW = 2_000_000_000
BASE = hashlib.sha256(b"baseline-v2").hexdigest()
CAND = hashlib.sha256(b"candidate-v3").hexdigest()


def sign(key, payload):
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def signed_start(start):
    return SignedGameRunStart(start, sign(STARTER, start.canonical_bytes()))


def signed_trial(trial):
    return SignedHoldoutTrial(trial, sign(EVALUATOR, trial.canonical_bytes()))


class GameCounterbalanceTests(unittest.TestCase):
    def setUp(self):
        self.cases = [
            HoldoutCase(f"game{game}", "v2", "finish", f"unknown{level}")
            for game in range(5) for level in range(8)
        ]
        self.seal = GameHoldoutPrecommit(
            "campaign_202", roster_digest(self.cases),
            "baseline", "candidate", BASE, CAND, NOW - 1000, NOW + 3600,
        )
        self.seal_receipt = sign(COORD, self.seal.canonical_bytes())
        self.plan = build_counterbalanced_plan(
            self.seal, self.cases, coordinator_key=COORD,
            seal_receipt=self.seal_receipt,
        )
        self.starts = []
        self.trials = []
        for index, slot in enumerate(self.plan.slots):
            started = (NOW - 400 + index * 4) * 1000
            run_id = f"run_{index}"
            start = GameRunStart(index, run_id, slot.nonce, started)
            trial = GameTrial(
                f"trial_{index}", slot.case.game_id, slot.case.game_version,
                slot.case.objective_id, slot.case.situation_id,
                slot.action_id, run_id, "validation",
                "success" if slot.action_id == "candidate" else "failure",
                hashlib.sha256(f"screen_{index}".encode()).hexdigest(),
                NOW - 399 + index * 4,
            )
            self.starts.append(signed_start(start))
            self.trials.append(signed_trial(trial))

    def check(self, **kwargs):
        plan = kwargs.pop("plan", self.plan)
        opts = {
            "seal_receipt": self.seal_receipt,
            "plan_receipt": sign(COORD, plan.canonical_bytes()),
            "coordinator_key": COORD,
            "start_key": STARTER,
            "validation_key": EVALUATOR,
            "expected_evaluation_id": self.seal.evaluation_id,
            "observed_baseline_revision_sha256": BASE,
            "observed_candidate_revision_sha256": CAND,
            "cases": self.cases,
            "signed_trials": self.trials,
            "signed_starts": self.starts,
            "now_unix_s": NOW,
        }
        opts.update(kwargs)
        return evaluate_counterbalanced_transfer(self.seal, plan, **opts)

    def test_good_counterbalanced_schedule_allows_manual_pilot_verdict(self):
        report = self.check()
        self.assertEqual(report.verdict, "eligible_for_owner_pilot")
        self.assertEqual(report.completed_pairs, 40)
        self.assertFalse(hasattr(report, "authorized_to_stream"))
        self.assertFalse(hasattr(report, "game_control"))

    def test_per_game_AB_BA_balance_even_after_case_shuffle(self):
        seen = {}
        for i in range(0, len(self.plan.slots), 2):
            left, right = self.plan.slots[i:i + 2]
            self.assertEqual(left.case, right.case)
            self.assertNotEqual(left.action_id, right.action_id)
            row = seen.setdefault(left.case.game_id, {"baseline": 0, "candidate": 0})
            row[left.action_id] += 1
        self.assertEqual(len(seen), 5)
        for row in seen.values():
            self.assertEqual(row, {"baseline": 4, "candidate": 4})
        self.assertEqual(len(set(slot.nonce for slot in self.plan.slots)), 80)

    def test_plan_is_reproducible_for_roster_permutations(self):
        other = build_counterbalanced_plan(
            self.seal, list(reversed(self.cases)), coordinator_key=COORD,
            seal_receipt=self.seal_receipt,
        )
        self.assertEqual(other.canonical_bytes(), self.plan.canonical_bytes())

    def test_forgeries_or_tampered_plan_are_rejected(self):
        changed = replace(self.plan, slots=tuple(reversed(self.plan.slots)))
        with self.assertRaises(PermissionError):
            self.check(plan=changed, plan_receipt=sign(COORD, self.plan.canonical_bytes()))
        with self.assertRaises(PermissionError):
            self.check(plan_receipt=sign(STARTER, self.plan.canonical_bytes()))
        with self.assertRaises(PermissionError):
            self.check(seal_receipt="0" * 64)
        with self.assertRaises(PermissionError):
            self.check(expected_evaluation_id="wrong_campaign")

    def test_unbalanced_separately_resigned_schedule_rejected(self):
        pairs = []
        for idx in range(0, len(self.plan.slots), 2):
            first, second = self.plan.slots[idx:idx + 2]
            pairs.extend((first, second) if first.action_id == "baseline"
                         else (second, first))
        unbalanced = replace(self.plan, slots=tuple(pairs))
        with self.assertRaises(PermissionError):
            self.check(plan=unbalanced)

    def test_nonadjacent_or_reused_cases_rejected_even_with_new_signature(self):
        swapped = list(self.plan.slots)
        swapped[1], swapped[3] = swapped[3], swapped[1]
        with self.assertRaises(PermissionError):
            self.check(plan=replace(self.plan, slots=tuple(swapped)))
        swapped = list(self.plan.slots)
        swapped[2] = swapped[0]
        with self.assertRaises(PermissionError):
            self.check(plan=replace(self.plan, slots=tuple(swapped)))

    def test_missing_run_start_or_outcome_blocks_all_stats(self):
        with self.assertRaises(PermissionError):
            self.check(signed_starts=self.starts[:-1])
        with self.assertRaises(PermissionError):
            self.check(signed_trials=self.trials[:-1])

    def test_forged_witness_signature_and_replay_are_rejected(self):
        with self.assertRaises(PermissionError):
            self.check(signed_starts=[
                replace(self.starts[0], receipt="0" * 64), *self.starts[1:],
            ])
        with self.assertRaises(PermissionError):
            self.check(signed_starts=[
                self.starts[0], self.starts[0], *self.starts[2:],
            ])

    def test_swapped_run_identity_rejected_even_when_host_resigns(self):
        changed = replace(self.starts[0].start, run_id=self.starts[1].start.run_id)
        with self.assertRaises(PermissionError):
            self.check(signed_starts=[signed_start(changed), *self.starts[1:]])

    def test_wrong_nonce_or_slot_rejected_even_with_valid_witness_hmac(self):
        for altered in (
            replace(self.starts[0].start, slot_nonce=self.starts[1].start.slot_nonce),
            replace(self.starts[0].start, slot_index=777),
        ):
            with self.subTest(altered=altered), self.assertRaises(PermissionError):
                self.check(signed_starts=[
                    signed_start(altered), *self.starts[1:],
                ])

    def test_retroactive_run_start_cannot_follow_outcome(self):
        changed = replace(
            self.starts[0].start,
            started_unix_ms=self.trials[0].trial.observed_unix_s * 1000 + 10,
        )
        with self.assertRaises(PermissionError):
            self.check(signed_starts=[signed_start(changed), *self.starts[1:]])

    def test_overlapping_runs_and_regressing_clock_are_rejected(self):
        # The second run begins before the first run's independently witnessed outcome.
        changed = replace(self.starts[1].start,
                          started_unix_ms=self.starts[0].start.started_unix_ms + 1)
        with self.assertRaises(PermissionError):
            self.check(signed_starts=[
                self.starts[0], signed_start(changed), *self.starts[2:],
            ])
        changed = replace(self.starts[1].start,
                          started_unix_ms=self.starts[0].start.started_unix_ms - 1)
        with self.assertRaises(PermissionError):
            self.check(signed_starts=[
                self.starts[0], signed_start(changed), *self.starts[2:],
            ])

    def test_start_before_seal_or_after_expiry_rejected(self):
        for timestamp in (
            self.seal.sealed_unix_s * 1000,
            self.seal.expires_unix_s * 1000,
        ):
            changed = replace(self.starts[0].start, started_unix_ms=timestamp)
            with self.subTest(timestamp=timestamp), self.assertRaises(PermissionError):
                self.check(signed_starts=[
                    signed_start(changed), *self.starts[1:],
                ])

    def test_valid_start_does_not_cover_tampered_evaluator_result(self):
        changed = replace(self.trials[0].trial, outcome="success")
        with self.assertRaises(PermissionError):
            self.check(signed_trials=[
                replace(self.trials[0], trial=changed), *self.trials[1:],
            ])

    def test_signing_keys_must_be_independent(self):
        with self.assertRaises(ValueError):
            self.check(start_key=COORD)
        with self.assertRaises(ValueError):
            self.check(validation_key=STARTER)
        with self.assertRaises(ValueError):
            self.check(start_key=b"x" * 8)

    def test_seal_or_roster_replacement_rejected_before_scoring(self):
        with self.assertRaises(PermissionError):
            self.check(cases=self.cases[:-1])
        with self.assertRaises(PermissionError):
            build_counterbalanced_plan(
                self.seal, self.cases[:-1], coordinator_key=COORD,
                seal_receipt=self.seal_receipt,
            )
        with self.assertRaises(PermissionError):
            build_counterbalanced_plan(
                self.seal, self.cases, coordinator_key=EVALUATOR,
                seal_receipt=self.seal_receipt,
            )

    def test_bool_time_and_invalid_id_dont_pass_schema(self):
        with self.assertRaises(ValueError):
            replace(self.starts[0].start, started_unix_ms=True)
        with self.assertRaises(PermissionError):
            RunSlot(self.cases[0], "candidate", "garbage")
        with self.assertRaises(ValueError):
            GameRunStart(0, "../path", "0" * 64, 1000)
        with self.assertRaises(ValueError):
            CounterbalancedRunPlan("x", "0" * 64, "0" * 64, tuple())

if __name__ == "__main__":
    unittest.main()
