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
            self.portfolio, self.offer, self.runner, now_unix_s=NOW)

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
        trial = replace(trial, evidence_sha256=transition_digest(
            delivery, after, trial=trial), **alter)
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
                self.portfolio, self.offer, self.runner, now_unix_s=NOW)
        self.runner._scope = self.scope
        with self.assertRaises(PermissionError):
            PortfolioStudioBridge(
                self.portfolio, replace(self.offer, action_id="other"),
                self.runner, now_unix_s=NOW)

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

    async def test_live_stream_has_priority_over_practice(self):
        self.tele[0] = StreamTelemetry(True, True, 4200, 8192, 60, 0)
        result = await self.bridge.take_step(self.propose, now_unix_s=NOW)
        self.assertEqual(result.reason, "offline_game_or_realtime_headroom_missing")
        self.assertFalse(self.port.keys)
