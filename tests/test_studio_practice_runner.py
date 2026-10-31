"""Offline integration proof: one Studio image -> key -> signed game result.

All game windows, MCP, model proposals and signers are TEST FAKES. No internet,
Windows Studio, external account, GPU, voice or broadcaster is used.
"""
import asyncio
import base64
from dataclasses import replace
import hashlib
import hmac
import unittest

from star.game_action_gate import GameScope
from star.game_learning_ladder import GameLearningLadder, PracticeSituation
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.studio_outcome_bridge import StudioOutcomeBridge, transition_digest
from star.studio_playtest_host import StudioBinding, StudioPlaytestHost, StudioSnapshot
from star.studio_practice_runner import PracticeProposal, StudioPracticeRunner
from star.studio_visual_evidence import StudioVisualObserver, VisualAssessment
from star.studio_vision_qos import StudioVisionQoS
from star.stream_budget import StreamTelemetry

SCOPE = GameScope("practice_obby", "v1", "episode_1")
PRACTICE_KEY = b"p" * 32
VALIDATION_KEY = b"v" * 32
NOW = 1_782_500_000
PNG = b"\x89PNG\r\n\x1a\n" + b"frame-before-1"
PNG2 = b"\x89PNG\r\n\x1a\n" + b"frame-after-2"


class FakeMCP:
    def __init__(self):
        self.image = PNG
        self.calls = []

    async def call_tool(self, name, arguments=None):
        self.calls.append(name)
        if name == "list_roblox_studios":
            return {"isError": False, "content": [
                {"type": "text",
                 "text": '{"studios":[{"id":"studio_7","name":"private"}]}'}]}
        if name == "get_studio_state":
            return {"isError": False, "structuredContent": {"playState": "Playing"}}
        if name == "screen_capture":
            return {"isError": False, "content": [{
                "type": "image", "mimeType": "image/png",
                "data": base64.b64encode(self.image).decode("ascii")}]}
        raise AssertionError("unexpected non-readonly Studio tool")


class FakePort:
    def __init__(self):
        self.keys = []
        self.authorized = True
        self.fail_up = False

    def snapshot(self, studio_id):
        return StudioSnapshot(studio_id, SCOPE, True, True, True, self.authorized)

    def key_down(self, studio_id, key):
        self.keys.append(("down", key))

    def key_up(self, studio_id, key):
        self.keys.append(("up", key))
        if self.fail_up:
            raise OSError("unreleased keys must quarantine actions")


class TestStudioPracticeRunner(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tick = [1000.]
        self.focus = [True]
        self.telemetry = [StreamTelemetry(False, True, 4200, 8192, 60, 0)]
        self.confidence = [.96]
        self.mcp = FakeMCP()
        self.port = FakePort()
        self.bank = GameplaySkillBank(practice_key=PRACTICE_KEY,
                                      validation_key=VALIDATION_KEY)

        async def assessor(image):
            return VisualAssessment(True, self.confidence[0], "Visible ledge.")

        self.observer = StudioVisualObserver(
            session=self.mcp, studio_id="studio_7", scope=SCOPE,
            focus_and_private=lambda _studio: self.focus[0],
            assessor=assessor, clock_ms=lambda: self.tick[0])
        self.vision = StudioVisionQoS(
            self.observer, clock_ms=lambda: self.tick[0])
        self.actions = StudioPlaytestHost(
            clock_ms=lambda: self.tick[0],
            sleeper=lambda delay: self.tick.__setitem__(
                0, self.tick[0] + delay * 1000))
        self.outcomes = StudioOutcomeBridge(self.bank)
        self.ladder = GameLearningLadder(
            self.bank, game_id=SCOPE.game_id, game_version=SCOPE.version_id,
            objective_id="clear_ledge",
            situations=[PracticeSituation("ledge", "jump", 1)])
        self.runner = StudioPracticeRunner(
            scope=SCOPE, observer=self.observer, vision=self.vision,
            actions=self.actions, outcomes=self.outcomes, ladder=self.ladder,
            port=self.port, telemetry=lambda: self.telemetry[0],
            clock_ms=lambda: self.tick[0])
        self.actions.start(
            studio_id="studio_7", scope=SCOPE,
            bindings=[StudioBinding("jump", "SPACE")], owner_approved=True)
        self.ladder.enable(owner_approved=True)
        await self.observer.arm(owner_approved=True)

    async def asyncTearDown(self):
        self.runner.stop()
        self.bank.close()

    async def proposal(self, evidence, advice):
        self.assertEqual(evidence.frame.scope, SCOPE)
        self.assertEqual(advice.action_id, "jump")
        return PracticeProposal("jump", 70)

    async def start(self):
        self.runner.enable(owner_approved=True)

    async def send(self):
        return await self.runner.take_step(self.proposal, now_unix_s=NOW)

    async def post(self, *, changed=True):
        self.tick[0] = 1250
        if changed:
            self.mcp.image = PNG2
        return await self.runner.observe_after()

    def signed_trial(self, *, outcome="success", wrong_key=False, **alter):
        pair = self.runner.evidence_for_evaluator()
        self.assertIsNotNone(pair)
        delivery, after = pair
        trial = GameTrial(
            trial_id="trial_1", game_id=SCOPE.game_id, game_version=SCOPE.version_id,
            objective_id="clear_ledge", situation_id="ledge", action_id="jump",
            run_id=SCOPE.episode_id, split="practice", outcome=outcome,
            evidence_sha256="0" * 64, observed_unix_s=NOW,
        )
        trial = replace(trial, evidence_sha256=transition_digest(
            delivery, after, trial=trial), **alter)
        receipt = hmac.new(
            VALIDATION_KEY if wrong_key else PRACTICE_KEY,
            trial.canonical_bytes(), hashlib.sha256).hexdigest()
        return trial, receipt

    async def test_full_closed_loop_records_independent_success(self):
        await self.start()
        sent = await self.send()
        self.assertEqual(sent.status, "action_sent")
        self.assertTrue(sent.action_sent)
        self.assertEqual(sent.situation_id, "ledge")
        self.assertEqual(self.port.keys, [("down", "SPACE"), ("up", "SPACE")])
        self.assertEqual(self.runner.metrics()["actions_sent"], 1)
        self.assertIsNone(self.runner.evidence_for_evaluator())

        # Real changed screenshot, NOT the successful key pulse, becomes the
        # post-action observation. The model has no key to sign a verdict.
        after = await self.post()
        self.assertEqual(after.status, "feedback_ready")
        trial, receipt = self.signed_trial()
        self.tick[0] += 20
        record = self.runner.record_signed_outcome(
            trial, receipt, now_unix_s=NOW + 1)
        self.assertTrue(record.accepted)
        self.assertFalse(record.mastery_proven)
        self.assertIsNone(self.runner.evidence_for_evaluator())
        self.assertIsNone(self.actions.inspect_delivery(
            self.actions._last_report or object()))
        rows = self.bank.practice_evidence(
            SCOPE.game_id, SCOPE.version_id, "clear_ledge", "ledge",
            now_unix_s=NOW + 1)
        self.assertEqual((rows[0].trials, rows[0].successes), (1, 1))

    async def test_independent_failure_is_still_useful_training_evidence(self):
        await self.start()
        await self.send()
        await self.post()
        trial, receipt = self.signed_trial(outcome="failure")
        self.tick[0] += 10
        result = self.runner.record_signed_outcome(
            trial, receipt, now_unix_s=NOW + 1)
        self.assertTrue(result.accepted)
        rows = self.bank.practice_evidence(
            SCOPE.game_id, SCOPE.version_id, "clear_ledge", "ledge",
            now_unix_s=NOW + 1)
        self.assertEqual((rows[0].trials, rows[0].successes), (1, 0))

    async def test_runner_and_other_components_keep_independent_owner_consent(self):
        denied = await self.send()
        self.assertEqual(denied.reason, "owner_practice_runner_disabled")
        self.assertNotIn("screen_capture", self.mcp.calls)
        with self.assertRaises(PermissionError):
            self.runner.enable(owner_approved=False)
        self.observer.disarm()
        await self.start()
        self.assertEqual((await self.send()).reason, "fresh_visual_evidence_missing")
        self.assertEqual(self.port.keys, [])

    async def test_stopped_or_untrusted_focus_never_dispatches(self):
        await self.start()
        self.focus[0] = False
        self.assertEqual((await self.send()).reason, "fresh_visual_evidence_missing")
        self.assertFalse(self.port.keys)
        self.assertTrue(self.runner.stop())
        self.assertFalse(self.observer.metrics()["armed"])
        self.assertFalse(self.ladder._enabled)

    async def test_live_or_slow_game_defers_input_without_observation(self):
        await self.start()
        for tele in (
            StreamTelemetry(True, True, 4200, 8192, 60, 0),
            StreamTelemetry(False, False, 4200, 8192, 60, 0),
            StreamTelemetry(False, True, 4200, 8192, 35, 0),
            StreamTelemetry(False, True, 1000, 8192, 60, 0),
            StreamTelemetry(False, True, 4200, 8192, 60, 450),
        ):
            self.telemetry[0] = tele
            self.assertEqual((await self.send()).reason,
                             "offline_game_or_realtime_headroom_missing")
        self.assertNotIn("screen_capture", self.mcp.calls)
        self.assertFalse(self.port.keys)

    async def test_remeasure_after_proposal_prevents_live_input(self):
        await self.start()

        async def turn_live(evidence, advice):
            self.telemetry[0] = StreamTelemetry(True, True, 4200, 8192, 60, 0)
            return PracticeProposal("jump", 60)
        result = await self.runner.take_step(turn_live, now_unix_s=NOW)
        self.assertEqual(result.reason, "realtime_pressure_before_input")
        self.assertFalse(self.port.keys)

    async def test_proposal_cannot_choose_arbitrary_keys_actions_or_holds(self):
        await self.start()
        async def wrong(*args):
            return PracticeProposal("delete_all", 50)
        result = await self.runner.take_step(wrong, now_unix_s=NOW)
        self.assertEqual(result.reason, "untrusted_or_off_curriculum_action")
        self.tick[0] = 1250
        self.mcp.image = PNG2
        async def oversized(*args):
            return PracticeProposal("jump", 500)
        result = await self.runner.take_step(oversized, now_unix_s=NOW + 1)
        self.assertEqual(result.reason, "untrusted_or_off_curriculum_action")
        self.assertFalse(self.port.keys)

    async def test_model_timeout_never_dispatches(self):
        self.runner._proposal_timeout = .02
        await self.start()
        async def slow(*args):
            await asyncio.sleep(.15)
            return PracticeProposal("jump", 60)
        result = await self.runner.take_step(slow, now_unix_s=NOW)
        self.assertEqual(result.reason, "proposal_deadline_exceeded")
        self.assertEqual(self.runner.metrics()["timeouts"], 1)
        self.assertFalse(self.port.keys)

    async def test_revocation_during_proposal_never_sends_key(self):
        await self.start()
        async def revoked(*args):
            self.runner.stop()
            return PracticeProposal("jump", 60)
        result = await self.runner.take_step(revoked, now_unix_s=NOW)
        self.assertEqual(result.reason, "practice_revoked_before_input")
        self.assertFalse(self.port.keys)

    async def test_duplicate_or_missing_after_scene_cannot_be_signed(self):
        await self.start()
        await self.send()
        unchanged = await self.post(changed=False)
        self.assertEqual(unchanged.reason, "usable_post_action_scene_missing")
        self.assertIsNone(self.runner.evidence_for_evaluator())
        with self.assertRaises(PermissionError):
            self.runner.record_signed_outcome(
                None, "fake", now_unix_s=NOW + 1)
        self.tick[0] = 1750
        self.mcp.image = PNG2
        self.assertEqual((await self.runner.observe_after()).status,
                         "feedback_ready")

    async def test_signed_verdict_replay_and_forgery_denied(self):
        await self.start()
        await self.send()
        await self.post()
        trial, bad_receipt = self.signed_trial(wrong_key=True)
        self.tick[0] += 25
        with self.assertRaises((ValueError, PermissionError)):
            self.runner.record_signed_outcome(
                trial, bad_receipt, now_unix_s=NOW + 1)
        self.assertIsNone(self.runner.evidence_for_evaluator())
        self.assertFalse(self.runner.discard_unverified())
        self.assertEqual(self.runner.metrics()["rejected"], 1)
        self.assertEqual(self.bank.practice_evidence(
            SCOPE.game_id, SCOPE.version_id, "clear_ledge", "ledge",
            now_unix_s=NOW + 1), ())

    async def test_no_second_action_before_signed_feedback(self):
        await self.start()
        self.assertTrue((await self.send()).action_sent)
        self.tick[0] = 1250
        self.mcp.image = PNG2
        self.assertEqual((await self.send()).reason, "independent_feedback_pending")
        self.assertEqual(self.port.keys, [("down", "SPACE"), ("up", "SPACE")])
        await self.runner.observe_after()
        self.assertEqual((await self.send()).reason, "independent_feedback_pending")
        self.assertEqual(self.port.keys, [("down", "SPACE"), ("up", "SPACE")])

    async def test_expired_feedback_is_discarded_not_assumed_success(self):
        await self.start()
        await self.send()
        self.tick[0] = 15000
        self.assertEqual((await self.runner.observe_after()).reason,
                         "post_action_feedback_expired")
        self.assertEqual(self.runner.metrics()["discarded"], 1)
        self.assertEqual(self.runner.metrics()["accepted"], 0)
        self.assertFalse(self.actions.metrics()["delivery_unclaimed"])

    async def test_stop_discards_pending_and_blocks_future_input(self):
        await self.start()
        await self.send()
        self.assertTrue(self.runner.stop())
        self.assertEqual(self.runner.metrics()["discarded"], 1)
        self.assertEqual((await self.send()).reason, "owner_practice_runner_disabled")
        self.assertFalse(self.actions.metrics()["delivery_unclaimed"])

    async def test_failed_key_release_is_not_scored_or_retried(self):
        await self.start()
        self.port.fail_up = True
        result = await self.send()
        self.assertFalse(result.action_sent)
        self.assertEqual(result.reason, "studio_input_key_up_not_confirmed_quarantined")
        self.assertTrue(self.actions.metrics()["key_release_pending"])
        self.assertFalse(self.runner.stop())

    async def test_concurrent_calls_only_one_input_pulse(self):
        await self.start()
        results = await asyncio.gather(*(
            self.runner.take_step(self.proposal, now_unix_s=NOW)
            for _ in range(12)))
        self.assertEqual(sum(step.action_sent for step in results), 1)
        self.assertEqual(len(self.port.keys), 2)

    async def test_one_signed_episode_is_not_retried_or_counted_twice(self):
        await self.start()
        await self.send()
        await self.post()
        trial, receipt = self.signed_trial()
        self.tick[0] += 15
        self.assertTrue(self.runner.record_signed_outcome(
            trial, receipt, now_unix_s=NOW + 1).accepted)
        self.tick[0] = 2000
        self.mcp.image = PNG
        result = await self.send()
        self.assertEqual(result.reason, "episode_attempt_already_consumed")
        self.assertEqual(self.port.keys, [("down", "SPACE"), ("up", "SPACE")])
        self.assertTrue(self.runner.stop())
        with self.assertRaises(RuntimeError):
            self.runner.enable(owner_approved=True)

    async def test_unverified_attempt_cannot_be_hidden_by_retry(self):
        await self.start()
        await self.send()
        self.assertTrue(self.runner.discard_unverified())
        self.tick[0] = 2000
        self.mcp.image = PNG2
        self.assertEqual((await self.send()).reason,
                         "episode_attempt_already_consumed")
        self.assertEqual(self.runner.metrics()["episode_attempted"], True)
        self.assertEqual(self.runner.metrics()["discarded"], 1)

    async def test_trusted_host_focus_rechecked_after_deliberation(self):
        await self.start()

        async def lose_focus(*args):
            self.focus[0] = False
            return PracticeProposal("jump", 60)

        result = await self.runner.take_step(lose_focus, now_unix_s=NOW)
        self.assertEqual(result.reason, "private_focus_revoked_before_input")
        self.assertFalse(self.port.keys)

    async def test_dispatch_port_permission_overrules_visual_authorization(self):
        await self.start()
        self.port.authorized = False
        result = await self.send()
        self.assertEqual(result.reason,
                         "studio_input_not_authorized_private_studio_playtest")
        self.assertFalse(self.port.keys)
        self.assertEqual(self.runner.metrics()["actions_sent"], 0)

    async def test_stop_while_proposer_is_awaiting_rejects_eventual_action(self):
        await self.start()
        ready = asyncio.Event()
        resume = asyncio.Event()

        async def slow(*args):
            ready.set()
            await resume.wait()
            return PracticeProposal("jump", 60)

        task = asyncio.create_task(
            self.runner.take_step(slow, now_unix_s=NOW))
        await asyncio.wait_for(ready.wait(), 1)
        self.assertTrue(self.runner.stop())
        resume.set()
        result = await task
        self.assertEqual(result.reason, "practice_revoked_before_input")
        self.assertFalse(self.port.keys)

    async def test_cancelled_model_cannot_leave_a_held_key(self):
        await self.start()
        ready = asyncio.Event()
        async def waiting(*args):
            ready.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(
            self.runner.take_step(waiting, now_unix_s=NOW))
        await asyncio.wait_for(ready.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.port.keys)
        self.assertFalse(self.runner.metrics()["feedback_pending"])

    async def test_live_transition_blocks_feedback_capture(self):
        await self.start()
        await self.send()
        captures = self.mcp.calls.count("screen_capture")
        self.telemetry[0] = StreamTelemetry(True, True, 4200, 8192, 60, 0)
        self.assertEqual((await self.runner.observe_after()).reason,
                         "offline_game_or_realtime_headroom_missing")
        self.assertEqual(captures, self.mcp.calls.count("screen_capture"))
        self.assertIsNone(self.runner.evidence_for_evaluator())

    async def test_invalid_telemetry_probe_deferred_without_new_actions(self):
        await self.start()
        self.runner._telemetry = lambda: {"live": False}
        self.assertEqual((await self.send()).reason,
                         "offline_game_or_realtime_headroom_missing")
        self.runner._telemetry = lambda: 1 / 0
        self.assertEqual((await self.send()).reason,
                         "offline_game_or_realtime_headroom_missing")
        self.assertFalse(self.port.keys)

    async def test_invalid_component_wiring_rejected_before_game_actions(self):
        with self.assertRaises(ValueError):
            StudioPracticeRunner(
                scope=GameScope("wrong", "v1", "episode_1"),
                observer=self.observer, vision=self.vision,
                actions=self.actions, outcomes=self.outcomes,
                ladder=self.ladder, port=self.port,
                telemetry=lambda: self.telemetry[0])
        with self.assertRaises(ValueError):
            StudioPracticeRunner(
                scope=SCOPE, observer=self.observer, vision=self.vision,
                actions=self.actions, outcomes=self.outcomes, ladder=self.ladder,
                port=self.port, telemetry=lambda: self.telemetry[0],
                proposal_timeout_s=.9)

    async def test_no_sensitive_data_in_metrics_or_errors(self):
        await self.start()
        async def bad(*args):
            raise RuntimeError("PRIVATE_TWITCH_TOKEN_123")
        result = await self.runner.take_step(bad, now_unix_s=NOW)
        self.assertEqual(result.reason, "proposal_unavailable")
        self.assertNotIn("PRIVATE_TWITCH_TOKEN_123", str(self.runner.metrics()))
        self.assertNotIn("frame-before", str(self.runner.metrics()))


if __name__ == "__main__":
    unittest.main()
