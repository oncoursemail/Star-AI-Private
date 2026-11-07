"""Realistic offline portfolio -> private Studio -> signed game outcome tests.

Fakes replace Windows, GPU, Roblox Studio and the independent signing host.
A test's self-created HMAC is NOT a production-independent evaluator.
"""
import base64
from dataclasses import replace
import hashlib
import hmac
import unittest

from star.game_action_gate import GameScope
from star.game_learning_ladder import GameLearningLadder, PracticeSituation
from star.game_portfolio_practice import GamePortfolioPractice
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.game_prediction_lab import GamePredictionLab
from star.portfolio_studio_bridge import PortfolioStudioBridge
from star.studio_outcome_bridge import StudioOutcomeBridge, transition_digest
from star.studio_playtest_host import StudioBinding, StudioPlaytestHost, StudioSnapshot
from star.studio_practice_runner import PracticeProposal, StudioPracticeRunner
from star.studio_visual_evidence import StudioVisualObserver, VisualAssessment
from star.studio_vision_qos import StudioVisionQoS
from star.stream_budget import StreamTelemetry

NOW = 1_782_500_000
KEY = b"P" * 32
OTHER_KEY = b"V" * 32
BEFORE = b"\x89PNG\r\n\x1a\n" + b"portfolio-observed-1"
AFTER = b"\x89PNG\r\n\x1a\n" + b"portfolio-observed-2"


class StudioFake:
    def __init__(self):
        self.image = BEFORE
        self.calls = []

    async def call_tool(self, name, arguments=None):
        self.calls.append(name)
        if name == "list_roblox_studios":
            return {"isError": False, "content": [
                {"type": "text", "text": '{"studios":[{"id":"studio_7","name":"private"}]}'}
            ]}
        if name == "get_studio_state":
            return {"isError": False, "structuredContent": {"playState": "Playing"}}
        if name == "screen_capture":
            return {"isError": False, "content": [
                {"type": "image", "mimeType": "image/png",
                 "data": base64.b64encode(self.image).decode("ascii")}
            ]}
        raise AssertionError("unexpected Studio write/control tool")


class PortFake:
    def __init__(self, scope):
        self.scope = scope
        self.keys = []

    def snapshot(self, studio_id):
        return StudioSnapshot(studio_id, self.scope, True, True, True, True)

    def key_down(self, studio_id, key):
        self.keys.append(("down", key))

    def key_up(self, studio_id, key):
        self.keys.append(("up", key))


class TestPortfolioStudioBridge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = [NOW]
        self.tick = [1000.0]
        self.tele = [StreamTelemetry(False, True, 4200, 8192, 60, 0)]
        self.bank = GameplaySkillBank(practice_key=KEY, validation_key=OTHER_KEY)
        self.ladders = []
        for game in ("practice_obby", "race"):
            item = GameLearningLadder(
                self.bank, game_id=game, game_version="v1",
                objective_id="clear_ledge",
                situations=[PracticeSituation("ledge", "jump", 1)],
            )
            item.enable(owner_approved=True)
            self.ladders.append(item)
        self.portfolio = GamePortfolioPractice(self.bank, ladders=self.ladders)
        self.portfolio.enable(owner_approved=True)
        self.offer = self.portfolio.reserve(now_unix_s=NOW, telemetry=self.tele[0])
        self.assertEqual(self.offer.game_id, "practice_obby")
        self.scope = GameScope(
            self.offer.game_id, self.offer.game_version, self.offer.expected_run_id,
        )
        self.mcp = StudioFake()
        self.port = PortFake(self.scope)

        async def assessor(img):
            return VisualAssessment(True, .97, "Verified private Studio ledge.")

        self.observer = StudioVisualObserver(
            session=self.mcp, studio_id="studio_7", scope=self.scope,
            focus_and_private=lambda _sid: True,
            assessor=assessor, clock_ms=lambda: self.tick[0])
        self.vision = StudioVisionQoS(
            self.observer, clock_ms=lambda: self.tick[0])
        self.actions = StudioPlaytestHost(
            clock_ms=lambda: self.tick[0],
            sleeper=lambda delay: self.tick.__setitem__(
                0, self.tick[0] + delay * 1000))
        self.outcomes = StudioOutcomeBridge(self.bank)
        self.runner = StudioPracticeRunner(
            scope=self.scope, observer=self.observer, vision=self.vision,
            actions=self.actions, outcomes=self.outcomes, ladder=self.ladders[0],
            port=self.port, telemetry=lambda: self.tele[0],
            clock_ms=lambda: self.tick[0])
        self.actions.start(
            studio_id="studio_7", scope=self.scope,
            bindings=[StudioBinding("jump", "SPACE")], owner_approved=True)
        await self.observer.arm(owner_approved=True)
        self.runner.enable(owner_approved=True)
        self.bridge = PortfolioStudioBridge(
            self.portfolio, self.offer, self.runner, now_unix_s=NOW,
            clock_unix_s=lambda: self.now[0])

    async def asyncTearDown(self):
        self.runner.stop()
        self.portfolio.disable()
        self.bank.close()

    async def propose(self, evidence, advice):
        self.assertEqual(advice.action_id, "jump")
        self.assertEqual(evidence.frame.scope, self.scope)
        return PracticeProposal("jump", 60)

    def signed_trial(self, *, key=KEY, **alter):
        pair = self.bridge.evidence_for_evaluator(now_unix_s=self.now[0])
        self.assertIsNotNone(pair)
        delivery, after = pair
        trial = GameTrial(
            "bound_trial_1", self.offer.game_id, self.offer.game_version,
            self.offer.objective_id, self.offer.situation_id,
            self.offer.action_id, self.offer.expected_run_id,
            "practice", "success", "0" * 64, self.now[0],
        )
        trial = replace(trial, **alter)
        trial = replace(trial, evidence_sha256=transition_digest(
            delivery, after, trial=trial))
        signature = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        return trial, signature

    async def send_and_observe(self):
        sent = await self.bridge.take_step(
            self.propose, now_unix_s=self.now[0])
        self.assertTrue(sent.action_sent, sent.reason)
        self.tick[0] = 1250
        self.mcp.image = AFTER
        seen = await self.bridge.observe_after(now_unix_s=self.now[0])
        self.assertEqual(seen.status, "feedback_ready", seen.reason)

    async def test_full_protected_cross_game_lifecycle(self):
        await self.send_and_observe()
        self.assertEqual(self.port.keys, [("down", "SPACE"), ("up", "SPACE")])
        trial, receipt = self.signed_trial()
        result = self.bridge.record_signed_outcome(
            trial, receipt, now_unix_s=self.now[0])
        self.assertTrue(result.signed_evidence_recorded)
        self.assertTrue(result.portfolio_verified)
        self.assertEqual(result.reason, "signed_practice_accepted")
        self.assertEqual(self.portfolio.metrics()["verified"], 1)
        self.assertEqual(self.bridge.metrics()["signed"], 1)
        self.assertIsNone(self.bridge.evidence_for_evaluator(
            now_unix_s=self.now[0]))
        # Different game's next offer proves actual cross-game fair scheduling.
        other = self.portfolio.reserve(now_unix_s=NOW + 2, telemetry=self.tele[0])
        self.assertEqual(other.game_id, "race", f"{other.status}: {other.reason}")
        self.assertNotEqual(other.expected_run_id, self.offer.expected_run_id)

    async def test_wrong_episode_cannot_bind_or_authorize(self):
        self.runner._scope = GameScope(
            self.scope.game_id, self.scope.version_id, "attacker_episode")
        with self.assertRaises(ValueError):
            PortfolioStudioBridge(
                self.portfolio, self.offer, self.runner, now_unix_s=NOW,
                clock_unix_s=lambda: self.now[0])
        self.runner._scope = self.scope
        with self.assertRaises(PermissionError):
            PortfolioStudioBridge(
                self.portfolio, replace(self.offer, action_id="other"),
                self.runner, now_unix_s=NOW,
                clock_unix_s=lambda: self.now[0])

    async def test_portfolio_revoked_inside_model_no_input_pulse(self):
        async def revoke(evidence, advice):
            self.portfolio.disable()
            return PracticeProposal("jump", 60)
        result = await self.bridge.take_step(revoke, now_unix_s=NOW)
        self.assertEqual(result.reason, "portfolio_reservation_revoked")
        self.assertFalse(self.port.keys)

    async def test_wrong_curriculum_during_model_proposal_blocks_input(self):
        original = self.ladders[0].recommend
        def changed(*args, **kwargs):
            return replace(original(*args, **kwargs), situation_id="other")
        self.ladders[0].recommend = changed
        result = await self.bridge.take_step(self.propose, now_unix_s=NOW)
        self.assertEqual(result.reason, "proposal_unavailable")
        self.assertFalse(self.port.keys)
        self.ladders[0].recommend = original

    async def test_fake_signature_cannot_complete_practice(self):
        await self.send_and_observe()
        trial, receipt = self.signed_trial(key=OTHER_KEY)
        with self.assertRaises(PermissionError):
            self.bridge.record_signed_outcome(
                trial, receipt, now_unix_s=NOW)
        self.assertEqual(self.portfolio.metrics()["verified"], 0)
        self.assertEqual(self.bridge.metrics()["rejected"], 1)
        self.assertEqual(self.portfolio.metrics()["unverified"], 1)
        self.assertIsNone(self.bridge.evidence_for_evaluator(
            now_unix_s=NOW))

    async def test_sealed_holdout_verdict_rejected_without_consuming(self):
        await self.send_and_observe()
        trial, receipt = self.signed_trial(split="validation")
        with self.assertRaises(ValueError):
            self.bridge.record_signed_outcome(
                trial, receipt, now_unix_s=NOW)
        self.assertEqual(self.portfolio.metrics()["verified"], 0)
        # A valid trusted signed PRACTICE trial may still finish the pending run.
        good, sig = self.signed_trial()
        result = self.bridge.record_signed_outcome(
            good, sig, now_unix_s=NOW)
        self.assertTrue(result.portfolio_verified)

    async def test_expired_offer_prevents_dispatch(self):
        self.now[0] = NOW + 91
        result = await self.bridge.take_step(self.propose, now_unix_s=self.now[0])
        self.assertEqual(result.reason, "portfolio_reservation_missing")
        self.assertFalse(self.port.keys)

    async def test_abandon_disallows_signed_credit(self):
        self.assertTrue(self.bridge.abandon(now_unix_s=NOW))
        self.assertFalse(self.bridge.abandon(now_unix_s=NOW))
        self.assertEqual(self.portfolio.metrics()["unverified"], 1)
        result = await self.bridge.take_step(self.propose, now_unix_s=NOW)
        self.assertEqual(result.reason, "portfolio_reservation_missing")
        self.assertFalse(self.port.keys)

    async def test_offer_expires_mid_proposal_at_real_dispatch_boundary(self):
        # A proposal starts on the exact last valid second of its reservation.
        # After the await, the next host-clock sample is already expired.
        self.now[0] = NOW + 90

        async def expires_during_inference(_evidence, _advice):
            self.now[0] = NOW + 91
            return PracticeProposal("jump", 60)

        blocked = await self.bridge.take_step(
            expires_during_inference, now_unix_s=NOW + 90)
        self.assertEqual(blocked.reason, "portfolio_reservation_revoked")
        self.assertEqual(self.port.keys, [])
        self.assertEqual(self.portfolio.metrics()["expired"], 1)
        self.assertEqual(self.portfolio.metrics()["verified"], 0)

    async def test_stale_clock_hint_cannot_reuse_valid_reservation(self):
        # The slot is still alive, but the caller reused its old timestamp.
        async def delay(_evidence, _advice):
            self.now[0] = NOW + 4
            return PracticeProposal("jump", 60)

        blocked = await self.bridge.take_step(delay, now_unix_s=NOW)
        self.assertEqual(blocked.reason, "portfolio_reservation_revoked")
        self.assertEqual(self.bridge.metrics()["clock_rejections"], 1)
        self.assertFalse(self.port.keys)
        self.assertEqual(self.portfolio.metrics()["verified"], 0)
        # A genuinely fresh host time and NEW scene can authorize this slot.
        # The first failed proposal already consumed the previous visual frame.
        self.mcp.image = AFTER
        self.tick[0] = 1400
        allowed = await self.bridge.take_step(
            self.propose, now_unix_s=NOW + 4)
        self.assertTrue(allowed.action_sent, allowed.reason)

    async def test_clock_unavailable_fails_closed_without_input(self):
        self.bridge._clock_unix_s = lambda: None
        result = await self.bridge.take_step(self.propose, now_unix_s=NOW)
        self.assertEqual(result.reason, "portfolio_reservation_missing")
        self.assertEqual(self.bridge.metrics()["clock_rejections"], 1)
        self.assertFalse(self.port.keys)

        def broken_clock():
            raise OSError("host clock unavailable")

        self.bridge._clock_unix_s = broken_clock
        result = await self.bridge.take_step(self.propose, now_unix_s=NOW)
        self.assertEqual(result.reason, "portfolio_reservation_missing")
        self.assertEqual(self.bridge.metrics()["clock_rejections"], 2)
        self.assertFalse(self.port.keys)

    async def test_future_timestamp_cannot_extend_portfolio_reservation(self):
        with self.assertRaises(ValueError):
            PortfolioStudioBridge(
                self.portfolio, self.offer, self.runner,
                now_unix_s=NOW + 12,
                clock_unix_s=lambda: self.now[0])
        self.assertFalse(self.port.keys)

    async def test_signed_outcome_rejected_when_reservation_expired(self):
        await self.send_and_observe()
        trial, receipt = self.signed_trial()
        self.now[0] = NOW + 91
        result = self.bridge.record_signed_outcome(
            trial, receipt, now_unix_s=NOW + 91)
        self.assertFalse(result.portfolio_verified)
        self.assertFalse(result.signed_evidence_recorded)
        self.assertEqual(result.reason, "reservation_expired_or_revoked")
        self.assertIsNone(self.bridge.evidence_for_evaluator(
            now_unix_s=self.now[0]))
        self.assertEqual(self.portfolio.metrics()["verified"], 0)

    async def test_expiry_during_second_physical_focus_snapshot_blocks_keydown(self):
        # Earlier control-plane checks are not enough. The Studio input port
        # can block on its second private-focus snapshot just before key_down.
        self.now[0] = NOW + 90
        snapshot = self.port.snapshot
        seen = [0]

        def expire_on_second_snapshot(studio_id):
            seen[0] += 1
            result = snapshot(studio_id)
            if seen[0] == 2:
                self.now[0] = NOW + 91
            return result

        self.port.snapshot = expire_on_second_snapshot
        step = await self.bridge.take_step(self.propose, now_unix_s=NOW + 90)
        self.assertEqual(step.reason,
                         "studio_input_trusted_dispatch_guard_revoked")
        self.assertFalse(step.action_sent)
        self.assertEqual(seen[0], 2)
        self.assertFalse(any(kind == "down" for kind, _ in self.port.keys))
        self.assertFalse(self.actions.metrics()["key_release_pending"])
        self.assertEqual(self.portfolio.metrics()["expired"], 1)

    async def test_capture_expiry_never_exposes_stale_scoring_input(self):
        sent = await self.bridge.take_step(self.propose, now_unix_s=NOW)
        self.assertTrue(sent.action_sent, sent.reason)
        self.tick[0] = 1250
        self.mcp.image = AFTER
        capture = self.mcp.call_tool

        async def capture_then_expire(name, arguments=None):
            result = await capture(name, arguments)
            if name == "screen_capture":
                self.now[0] = NOW + 91
            return result

        self.mcp.call_tool = capture_then_expire
        result = await self.bridge.observe_after(now_unix_s=NOW)
        self.assertEqual(result.reason, "portfolio_reservation_missing")
        self.assertIsNone(self.bridge.evidence_for_evaluator(
            now_unix_s=self.now[0]))
        self.assertEqual(self.portfolio.metrics()["verified"], 0)

    async def test_live_stream_has_priority_over_practice(self):
        self.tele[0] = StreamTelemetry(True, True, 4200, 8192, 60, 0)
        result = await self.bridge.take_step(self.propose, now_unix_s=NOW)
        self.assertEqual(result.reason, "offline_game_or_realtime_headroom_missing")
        self.assertFalse(self.port.keys)


    async def test_preaction_probability_resolves_only_from_signed_studio_result(self):
        # The model predicts BEFORE keydown. The independent post-action
        # Studio receipt is the ONLY permitted label for calibration.
        with GamePredictionLab(self.bank) as lab:
            lab.enable(owner_approved=True)
            bridge = PortfolioStudioBridge(
                self.portfolio, self.offer, self.runner, now_unix_s=NOW,
                clock_unix_s=lambda: self.now[0], prediction_lab=lab,
                forecast_model_id="star_v1",
            )
            self.bridge = bridge

            async def proposer(_evidence, _advice):
                return PracticeProposal("jump", 60, 9000)

            result = await bridge.take_step(proposer, now_unix_s=NOW)
            self.assertTrue(result.action_sent, result.reason)
            self.assertEqual(bridge.metrics()["forecast_committed"], 1)
            self.assertEqual(lab.report("star_v1").trials, 0)
            self.tick[0] = 1250
            self.mcp.image = AFTER
            observed = await bridge.observe_after(now_unix_s=NOW)
            self.assertEqual(observed.status, "feedback_ready")
            self.assertEqual(lab.report("star_v1").trials, 0)
            trial, signature = self.signed_trial()
            accepted = bridge.record_signed_outcome(trial, signature, now_unix_s=NOW)
            self.assertTrue(accepted.portfolio_verified)
            self.assertEqual(bridge.metrics()["forecast_verified"], 1)
            self.assertAlmostEqual(lab.report("star_v1").brier_score, 0.01)

    async def test_predicted_win_does_not_override_signed_game_failure(self):
        with GamePredictionLab(self.bank) as lab:
            lab.enable(owner_approved=True)
            self.bridge = PortfolioStudioBridge(
                self.portfolio, self.offer, self.runner, now_unix_s=NOW,
                clock_unix_s=lambda: self.now[0], prediction_lab=lab,
                forecast_model_id="star_v1")
            async def confident(_evidence, _advice):
                return PracticeProposal("jump", 60, 9999)
            result = await self.bridge.take_step(confident, now_unix_s=NOW)
            self.assertTrue(result.action_sent, result.reason)
            self.tick[0] = 1250
            self.mcp.image = AFTER
            self.assertEqual((await self.bridge.observe_after(
                now_unix_s=NOW)).status, "feedback_ready")
            trial, receipt = self.signed_trial(outcome="failure")
            recorded = self.bridge.record_signed_outcome(trial, receipt, now_unix_s=NOW)
            self.assertTrue(recorded.portfolio_verified)
            self.assertGreater(lab.report("star_v1").brier_score, 0.99)
            self.assertFalse(lab.advise(
                "star_v1", game_id="practice_obby", game_version="v1",
                proposed_bps=9999).authorized_to_play)

    async def test_untrusted_or_abandoned_forecast_cannot_change_gameplay(self):
        with GamePredictionLab(self.bank) as lab:
            lab.enable(owner_approved=True)
            self.bridge = PortfolioStudioBridge(
                self.portfolio, self.offer, self.runner, now_unix_s=NOW,
                clock_unix_s=lambda: self.now[0], prediction_lab=lab,
                forecast_model_id="star_v1")
            async def invalid_confidence(_evidence, _advice):
                return PracticeProposal("jump", 60, True)
            rejected = await self.bridge.take_step(
                invalid_confidence, now_unix_s=NOW)
            self.assertFalse(rejected.action_sent)
            self.assertEqual(rejected.reason, "untrusted_or_off_curriculum_action")
            self.assertEqual(lab.report("star_v1").trials, 0)
            self.assertFalse(self.port.keys)
            self.assertTrue(self.bridge.abandon(now_unix_s=NOW))
            self.assertEqual(lab.metrics()["pending"], 0)
