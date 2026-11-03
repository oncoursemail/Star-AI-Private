"""Offline policy regression checks for Star's advisory practice ladder."""
import unittest

from star.game_learning_ladder import GameLearningLadder, PracticeSituation
from star.gameplay_skill_bank import GameplaySkillBank, PracticeEvidence
from star.stream_budget import StreamTelemetry


class PracticeBankFixture(GameplaySkillBank):
    def __init__(self):
        self.rows = {}

    def practice_evidence(self, game, version, objective, situation, *, now_unix_s, max_age_s):
        assert (game, version, objective) == ("obby", "v1", "finish")
        assert max_age_s == 7 * 24 * 3600
        return self.rows.get(situation, ())

    def add(self, situation, action, trials, successes, *, latest=True, streak=None):
        if streak is None and latest is True:
            streak = min(successes, 3)
        elif streak is None and latest is False:
            streak = 0
        self.rows[situation] = (
            PracticeEvidence(action, trials, successes, 100, latest, streak),
        )


class TestPracticeLadder(unittest.TestCase):
    def setUp(self):
        self.bank = PracticeBankFixture()
        self.ladder = GameLearningLadder(
            self.bank, game_id="obby", game_version="v1", objective_id="finish",
            situations=(PracticeSituation("intro", "jump", 1),
                        PracticeSituation("moving", "timing", 2, ("intro",))))

    def advise(self, telemetry=None):
        snapshot = telemetry if telemetry is not None else StreamTelemetry(
            live=False, game_active=True, free_vram_mib=4096,
            total_vram_mib=8192, game_fps=90, speech_backlog_ms=0)
        return self.ladder.recommend(now_unix_s=100, telemetry=snapshot)

    def test_consent_and_prerequisite_mastery(self):
        self.assertEqual(self.advise().status, "deferred")
        with self.assertRaises(PermissionError):
            self.ladder.enable(owner_approved=False)
        self.ladder.enable(owner_approved=True)
        self.assertEqual(self.advise().situation_id, "intro")
        self.bank.add("intro", "jump", 11, 11)
        self.assertEqual(self.advise().situation_id, "intro")
        self.bank.add("intro", "jump", 20, 20)
        self.assertEqual(self.advise().situation_id, "moving")
        self.bank.add("moving", "timing", 20, 20)
        self.assertEqual(self.advise().status, "complete")

    def test_repeated_failure_requires_diagnosis(self):
        self.ladder.enable(owner_approved=True)
        self.bank.add("intro", "jump", 12, 0)
        decision = self.advise()
        self.assertEqual(decision.status, "manual_diagnosis")
        self.assertFalse(decision.authorized_to_play)

    def test_recent_failure_blocks_unlock_despite_high_historical_success(self):
        self.ladder.enable(owner_approved=True)
        self.bank.add("intro", "jump", 20, 20)
        self.assertEqual(self.advise().situation_id, "moving")
        # One independently recorded most-recent failure invalidates mastery
        # even though the Wilson lower bound remains comfortably above 0.55.
        self.bank.add("intro", "jump", 21, 20, latest=False)
        decision = self.advise()
        self.assertEqual(decision.status, "practice_candidate")
        self.assertEqual(decision.situation_id, "intro")
        self.assertFalse(decision.authorized_to_play)

    def test_single_lucky_retry_cannot_instantly_unlock_harder_scene(self):
        self.ladder.enable(owner_approved=True)
        self.bank.add("intro", "jump", 20, 20, streak=3)
        self.assertEqual(self.advise().situation_id, "moving")
        self.bank.add("intro", "jump", 21, 20, latest=False, streak=0)
        self.assertEqual(self.advise().situation_id, "intro")
        for recovery in (1, 2):
            self.bank.add("intro", "jump", 21 + recovery, 20 + recovery,
                          latest=True, streak=recovery)
            self.assertEqual(self.advise().situation_id, "intro")
        self.bank.add("intro", "jump", 24, 23, latest=True, streak=3)
        self.assertEqual(self.advise().situation_id, "moving")

    def test_unsigned_or_impossible_streak_never_certifies_mastery(self):
        self.ladder.enable(owner_approved=True)
        self.bank.add("intro", "jump", 20, 20, latest=True, streak=2)
        self.assertEqual(self.advise().situation_id, "intro")
        self.bank.rows["intro"] = (PracticeEvidence("jump", 20, 20, 100, True),)
        self.assertEqual(self.advise().situation_id, "intro")
        for bad in (True, -1, 21, "three"):
            self.bank.rows["intro"] = (
                PracticeEvidence("jump", 20, 20, 100, True, bad),
            )
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.advise()

    def test_success_streak_threshold_is_bounded(self):
        for invalid in (True, 0, -1, 11):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                GameLearningLadder(
                    self.bank, game_id="obby", game_version="v1",
                    objective_id="finish",
                    situations=[PracticeSituation("intro", "jump", 1)],
                    min_consecutive_success_seconds=invalid,
                )

    def test_missing_recent_outcome_cannot_certify_mastery(self):
        self.ladder.enable(owner_approved=True)
        self.bank.add("intro", "jump", 25, 25, latest=None)
        self.assertEqual(self.advise().situation_id, "intro")
        self.bank.add("intro", "jump", 25, 25, latest="yes")
        with self.assertRaises(ValueError):
            self.advise()

    def test_practice_window_config_must_be_bounded(self):
        for invalid in (True, 0, 59, 31 * 24 * 3600):
            with self.assertRaises(ValueError):
                GameLearningLadder(
                    self.bank, game_id="obby", game_version="v1",
                    objective_id="finish", situations=[PracticeSituation("intro", "jump", 1)],
                    max_evidence_age_s=invalid,
                )

    def test_live_stream_blocks_training(self):
        self.ladder.enable(owner_approved=True)
        live = StreamTelemetry(live=True, game_active=True, free_vram_mib=4096,
            total_vram_mib=8192, game_fps=90, speech_backlog_ms=0)
        self.assertEqual(self.advise(live).status, "deferred")

    def test_wrong_action_cannot_fake_progress(self):
        self.ladder.enable(owner_approved=True)
        self.bank.add("intro", "other", 100, 100)
        self.assertEqual(self.advise().practice_trials, 0)

    def test_invalid_dependencies_rejected(self):
        with self.assertRaises(ValueError):
            GameLearningLadder(self.bank, game_id="obby", game_version="v1",
                objective_id="finish", situations=(
                    PracticeSituation("intro", "jump", 1),
                    PracticeSituation("bad", "x", 2, ("unknown",))))


def test_real_signed_bank_ignores_old_wins_and_never_promotes_latest_failure():
    """Regression: old successful practice + new failure cannot unlock tier 2."""
    from hashlib import sha256
    import hmac
    from star.gameplay_skill_bank import GameTrial

    pkey = sha256(b"game-retention-practice-key").digest()
    vkey = sha256(b"game-retention-validation-key").digest()
    now = 2_000_000_000
    bank = GameplaySkillBank(practice_key=pkey, validation_key=vkey)
    ladder = GameLearningLadder(
        bank, game_id="obby", game_version="v1", objective_id="finish",
        situations=(PracticeSituation("intro", "jump", 1),
                    PracticeSituation("moving", "timing", 2, ("intro",))),
    )
    ladder.enable(owner_approved=True)
    tele = StreamTelemetry(
        live=False, game_active=True, free_vram_mib=4096,
        total_vram_mib=8192, game_fps=90, speech_backlog_ms=0,
    )

    def sign(n, *, observed, outcome):
        item = GameTrial(
            trial_id=f"retention_trial_{n}", game_id="obby", game_version="v1",
            objective_id="finish", situation_id="intro", action_id="jump",
            run_id=f"retention_run_{n}", split="practice", outcome=outcome,
            evidence_sha256=sha256(f"evidence_{n}".encode()).hexdigest(),
            observed_unix_s=observed,
        )
        sig = hmac.new(pkey, item.canonical_bytes(), sha256).hexdigest()
        bank.ingest(item, sig, now_unix_s=observed)

    try:
        for i in range(20):
            sign(i, observed=now - 9 * 86400 + i, outcome="success")
        # Old successes were inside the ledger's default 90-day lookback,
        # but must be excluded from the ladder's explicit seven-day window.
        advice = ladder.recommend(now_unix_s=now, telemetry=tele)
        assert advice.situation_id == "intro"
        assert advice.practice_trials == 0
        for i in range(20, 40):
            sign(i, observed=now - 100 + i, outcome="success")
        advice = ladder.recommend(now_unix_s=now, telemetry=tele)
        assert advice.situation_id == "moving"

        sign(40, observed=now - 1, outcome="failure")
        advice = ladder.recommend(now_unix_s=now, telemetry=tele)
        assert advice.situation_id == "intro"
        assert advice.practice_trials == 21 and advice.practice_successes == 20
        assert advice.practice_lower_bound > .55
        assert advice.status == "practice_candidate"
        assert advice.authorized_to_play is False

        # A single lucky action cannot erase the newest failure, even
        # when historical wins keep Wilson's score above the threshold.
        for i in range(41, 43):
            sign(i, observed=now + (i - 40), outcome="success")
            advice = ladder.recommend(now_unix_s=now + (i - 40), telemetry=tele)
            assert advice.situation_id == "intro"
        sign(43, observed=now + 3, outcome="success")
        assert ladder.recommend(now_unix_s=now + 3, telemetry=tele).situation_id == "moving"
    finally:
        ladder.disable()
        bank.close()
