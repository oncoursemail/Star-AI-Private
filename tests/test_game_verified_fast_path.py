"""Real signed-bank and adversarial tests for the O(1) game-skill fast path."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
import unittest
from typing import Any, cast

from star.game_verified_fast_path import VerifiedGameSkillFastPath
from star.gameplay_skill_bank import GameplaySkillBank, GameTrial, SkillSuggestion


PRACTICE_KEY = b"practice-a" * 5
VALIDATION_KEY = b"validation-b" * 4
NOW = 1_800_000_000
SCOPE = ("Platformer", "v1", "finish_level", "jump_gap")
GOOD = "short_jump"


class Clock:
    def __init__(self, ms: float = 100.0) -> None:
        self.ms = ms

    def __call__(self) -> float:
        return self.ms


def add_runs(bank: GameplaySkillBank, action: str, split: str, count: int, *, failed: int = 0) -> None:
    key = PRACTICE_KEY if split == "practice" else VALIDATION_KEY
    for i in range(count):
        trial = GameTrial(
            trial_id=f"{split}_{action}_{i}",
            game_id=SCOPE[0],
            game_version=SCOPE[1],
            objective_id=SCOPE[2],
            situation_id=SCOPE[3],
            action_id=action,
            run_id=f"{split}_{action}_run_{i}",
            split=split,
            outcome="failure" if i < failed else "success",
            evidence_sha256=hashlib.sha256(f"{action}\0{split}\0{i}".encode()).hexdigest(),
            observed_unix_s=NOW - 1000 + i,
        )
        receipt = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        bank.ingest(trial, receipt, now_unix_s=NOW)


class TestFastSkill(unittest.TestCase):
    def setUp(self) -> None:
        self.bank = GameplaySkillBank(practice_key=PRACTICE_KEY, validation_key=VALIDATION_KEY)
        self.clock = Clock()
        self.policy = self.make_policy()

    def tearDown(self) -> None:
        self.bank.close()

    def make_policy(self, *, allowed: tuple[str, ...] = (GOOD,), ttl: int = 1000) -> VerifiedGameSkillFastPath:
        return VerifiedGameSkillFastPath(
            self.bank,
            game_id=SCOPE[0],
            game_version=SCOPE[1],
            objective_id=SCOPE[2],
            situation_id=SCOPE[3],
            allowed_actions=allowed,
            clock_ms=self.clock,
            cache_ttl_ms=ttl,
        )

    def hint(
        self,
        *,
        now_ms: float = 100.0,
        scope: tuple[str, ...] = SCOPE,
        verified: bool = True,
        focus: bool = True,
        critical: bool = False,
    ):
        return self.policy.advise(
            now_ms=now_ms,
            game_id=scope[0],
            game_version=scope[1],
            objective_id=scope[2],
            situation_id=scope[3],
            host_scope_verified=verified,
            game_focused=focus,
            gameplay_critical=critical,
        )

    def test_requires_owner_optin(self) -> None:
        self.assertEqual(self.hint().reason, "owner_opt_in_missing")
        with self.assertRaises(PermissionError):
            self.policy.enable()
        self.assertFalse(self.policy.refresh(now_unix_s=NOW))
        self.policy.enable(owner_approved=True)
        self.assertEqual(self.hint().reason, "missing_or_expired_signed_skill_snapshot")

    def test_signed_practice_without_holdout_is_not_live_candidate(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        self.policy.enable(owner_approved=True)
        self.assertFalse(self.policy.refresh(now_unix_s=NOW))
        self.assertEqual(self.hint().reason, "independent_validation_or_action_allowlist_missing")

    def test_signed_validation_makes_fast_hint_without_game_authorization(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        add_runs(self.bank, GOOD, "validation", 30)
        self.policy.enable(owner_approved=True)
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))
        hint = self.hint()
        self.assertEqual((hint.status, hint.action_id), ("candidate_for_host_review", GOOD))
        self.assertFalse(hasattr(hint, "validation_trials"))
        self.assertFalse(hasattr(hint, "validation_lower_bound"))
        self.assertFalse(hint.authorized_to_play)
        self.assertFalse(hint.authorizes_game_input)

    def test_freshness_expiration_no_cache_extension_on_repeat_reads(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        add_runs(self.bank, GOOD, "validation", 30)
        self.policy.enable(owner_approved=True)
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))
        self.assertEqual(self.hint(now_ms=1100).status, "candidate_for_host_review")
        self.assertEqual(self.hint(now_ms=1100.0001).status, "hold")
        self.assertEqual(self.hint(now_ms=2000).status, "hold")

    def test_scope_switch_never_uses_other_game_skill(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        add_runs(self.bank, GOOD, "validation", 30)
        self.policy.enable(owner_approved=True)
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))
        for scope in (
            ("Arena", *SCOPE[1:]),
            (SCOPE[0], "v2", *SCOPE[2:]),
            (SCOPE[0], SCOPE[1], "collect", SCOPE[3]),
            (*SCOPE[:3], "different_gap"),
        ):
            self.assertEqual(self.hint(scope=scope).status, "hold")
        self.assertEqual(self.hint(verified=False).status, "hold")
        self.assertEqual(self.hint(focus=False).status, "hold")
        self.assertEqual(self.hint(critical=True).status, "hold")
        self.assertEqual(self.hint().status, "candidate_for_host_review")

    def test_allowed_action_not_selected_substituted(self) -> None:
        add_runs(self.bank, "long_jump", "practice", 30)
        add_runs(self.bank, "long_jump", "validation", 30)
        self.policy.enable(owner_approved=True)
        self.assertFalse(self.policy.refresh(now_unix_s=NOW))
        self.assertEqual(self.hint().status, "hold")

    def test_clock_rollback_invalidates_cache_until_fresh_refresh(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        add_runs(self.bank, GOOD, "validation", 30)
        self.policy.enable(owner_approved=True)
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))
        self.assertEqual(self.hint(now_ms=150).status, "candidate_for_host_review")
        self.assertEqual(self.hint(now_ms=149).reason, "host_monotonic_clock_reversed")
        self.assertEqual(self.hint(now_ms=151).status, "hold")
        self.clock.ms = 152
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))
        self.assertEqual(self.hint(now_ms=153).status, "candidate_for_host_review")

    def test_clock_fail_closed_on_refresh_and_advice(self) -> None:
        self.policy.enable(owner_approved=True)
        for value in (True, float("inf"), -1, float("nan"), "100"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.policy.advise(
                    now_ms=cast(Any, value),
                    game_id=SCOPE[0],
                    game_version=SCOPE[1],
                    objective_id=SCOPE[2],
                    situation_id=SCOPE[3],
                    host_scope_verified=True,
                    game_focused=True,
                )
            self.clock.ms = cast(Any, value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.policy.refresh(now_unix_s=NOW)

    def test_reversed_clock_on_refresh_refused(self) -> None:
        self.policy.enable(owner_approved=True)
        self.assertFalse(self.policy.refresh(now_unix_s=NOW))
        self.assertEqual(self.hint(now_ms=400).status, "hold")
        self.clock.ms = 300
        self.assertFalse(self.policy.refresh(now_unix_s=NOW))

    def test_disable_invalidates_cached_candidate(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        add_runs(self.bank, GOOD, "validation", 30)
        self.policy.enable(owner_approved=True)
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))
        self.policy.disable()
        self.assertEqual(self.hint().status, "hold")
        self.policy.enable(owner_approved=True)
        self.assertEqual(self.hint().status, "hold")

    def test_bad_signed_bank_exception_invalidates_previous_candidate(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        add_runs(self.bank, GOOD, "validation", 30)
        self.policy.enable(owner_approved=True)
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))

        def bad_suggest(*args, **kwargs):
            raise ValueError("tampered ledger")

        self.bank.suggest = bad_suggest  # type: ignore[method-assign]
        self.clock.ms = 151
        with self.assertRaisesRegex(ValueError, "tampered"):
            self.policy.refresh(now_unix_s=NOW)
        self.assertEqual(self.hint(now_ms=151).status, "hold")

    def test_disabled_during_slow_sqlite_refresh_does_not_resurrect(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        self.policy.enable(owner_approved=True)

        def delayed_suggest(*args, **kwargs):
            entered.set()
            assert release.wait(2)
            return SkillSuggestion("ready_for_host_review", GOOD, 25, 25, 0.75, "host evaluated")

        self.bank.suggest = delayed_suggest  # type: ignore[method-assign]
        result = []

        def worker() -> None:
            result.append(self.policy.refresh(now_unix_s=NOW))

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(entered.wait(2))
        # Advise stays responsive even while refresh is stuck in SQLite.
        t0 = time.perf_counter()
        self.assertEqual(self.hint().status, "hold")
        self.assertLess(time.perf_counter() - t0, 0.2)
        self.policy.disable()
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        self.assertEqual(self.hint().status, "hold")

    def test_old_overlapping_refresh_cannot_replace_newer_one(self) -> None:
        slow_started = threading.Event()
        release = threading.Event()
        self.policy.enable(owner_approved=True)
        times = []

        def delayed(*args, **kwargs):
            if threading.current_thread() is not threading.main_thread():
                slow_started.set()
                assert release.wait(2)
                return SkillSuggestion("ready_for_host_review", "older", 25, 25, 0.75, "old")
            return SkillSuggestion("ready_for_host_review", GOOD, 25, 25, 0.75, "new")

        self.bank.suggest = delayed  # type: ignore[method-assign]
        t = threading.Thread(target=lambda: times.append(self.policy.refresh(now_unix_s=NOW)))
        t.start()
        self.assertTrue(slow_started.wait(2))
        self.clock.ms = 160
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))
        release.set()
        t.join(2)
        self.assertEqual(times, [False])
        self.assertEqual(self.hint(now_ms=160).action_id, GOOD)

    def test_failed_independent_validation_never_becomes_a_fast_hint(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        add_runs(self.bank, GOOD, "validation", 30, failed=20)
        self.policy.enable(owner_approved=True)
        self.assertFalse(self.policy.refresh(now_unix_s=NOW))
        self.assertEqual(self.hint().status, "hold")

    def test_late_failed_refresh_cannot_clear_a_newer_valid_snapshot(self) -> None:
        began = threading.Event()
        release = threading.Event()
        errors: list[str] = []
        self.policy.enable(owner_approved=True)

        def delayed(*args, **kwargs):
            if threading.current_thread() is not threading.main_thread():
                began.set()
                assert release.wait(2)
                raise ValueError("older refresh failed")
            return SkillSuggestion("ready_for_host_review", GOOD, 25, 25, 0.75, "newer")

        self.bank.suggest = delayed  # type: ignore[method-assign]

        def older_worker() -> None:
            try:
                self.policy.refresh(now_unix_s=NOW)
            except ValueError as exc:
                errors.append(str(exc))

        worker = threading.Thread(target=older_worker)
        worker.start()
        self.assertTrue(began.wait(2))
        self.clock.ms = 170
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["older refresh failed"])
        self.assertEqual(self.hint(now_ms=170).action_id, GOOD)

    def test_rejects_bad_config_and_inputs(self) -> None:
        with self.assertRaises(ValueError):
            self.make_policy(allowed=(GOOD, GOOD))
        with self.assertRaises(ValueError):
            self.make_policy(ttl=0)
        with self.assertRaises(TypeError):
            VerifiedGameSkillFastPath(
                cast(Any, object()),
                game_id="g",
                game_version="v",
                objective_id="o",
                situation_id="s",
                allowed_actions=("jump",),
            )
        self.policy.enable(owner_approved=True)
        for n in (0, -1, True, "wrong"):
            with self.assertRaises(ValueError):
                self.policy.refresh(now_unix_s=cast(Any, n))
        for scope in (("space here", *SCOPE[1:]), ("", *SCOPE[1:])):
            with self.assertRaises(ValueError):
                self.hint(scope=scope)
        with self.assertRaises(ValueError):
            self.policy.advise(
                now_ms=100,
                game_id=SCOPE[0],
                game_version=SCOPE[1],
                objective_id=SCOPE[2],
                situation_id=SCOPE[3],
                host_scope_verified=cast(Any, 1),
                game_focused=True,
            )

    def test_microbenchmark_advice_without_model_or_bank_calls(self) -> None:
        add_runs(self.bank, GOOD, "practice", 30)
        add_runs(self.bank, GOOD, "validation", 30)
        self.policy.enable(owner_approved=True)
        self.assertTrue(self.policy.refresh(now_unix_s=NOW))

        def should_not_query(*args, **kwargs):
            raise AssertionError("real-time path must not hit signed SQLite")

        self.bank.suggest = should_not_query  # type: ignore[method-assign]
        start = time.perf_counter()
        for _ in range(10000):
            self.assertEqual(self.hint().action_id, GOOD)
        elapsed = time.perf_counter() - start
        # Only a soft benchmark statistic; no flaky performance SLO assertion.
        print(f"fast_skill_10000_advice_seconds={elapsed:.4f}")


if __name__ == "__main__":
    unittest.main()
