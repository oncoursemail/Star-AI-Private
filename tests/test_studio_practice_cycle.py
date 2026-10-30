"""Offline integration tests for the one-shot Studio practice feedback cycle.

Fake Studio frames/ports replace Windows I/O; signed practice outcomes are
computed by a separate test evaluator, never by the practice coordinator.
"""
import asyncio
from dataclasses import replace
import hashlib
import hmac

import pytest

from star.game_action_gate import GameFrame, GameScope
from star.game_prediction_lab import GameForecast, GamePredictionLab
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_budget import StreamTelemetry
from star.stream_episode import StreamEpisode
from star.studio_outcome_bridge import StudioOutcomeBridge, transition_digest
from star.studio_playtest_host import StudioBinding, StudioPlaytestHost, StudioSnapshot
from star.studio_practice_cycle import SignedPracticeVerdict, StudioPracticeCycle
from star.studio_visual_evidence import VisualEvidence

NOW = 1_782_500_000
SCOPE = GameScope("obby", "v4", "run_1")
PRACTICE = b"p" * 32
HOLDOUT = b"v" * 32
TELEMETRY = StreamTelemetry(False, True, 4200, 8192, 60, 0)


class FakePort:
    def __init__(self, scope=SCOPE):
        self.status = StudioSnapshot("studio_3", scope, True, True, True, True)
        self.keys = []
        self.fail_up = False

    def snapshot(self, studio_id):
        assert studio_id == "studio_3"
        return self.status

    def key_down(self, studio_id, key):
        self.keys.append(("down", key))

    def key_up(self, studio_id, key):
        self.keys.append(("up", key))
        if self.fail_up:
            raise OSError("no key release receipt")


class FakeObserver:
    """Stand-in for the trusted MCP screenshot source (never used in prod)."""
    def __init__(self, clock, *, after_changed=True, first_scope=SCOPE,
                 fail_after=False):
        self.clock = clock
        self.calls = 0
        self.disarmed = False
        self.after_changed = after_changed
        self.first_scope = first_scope
        self.fail_after = fail_after

    async def observe(self):
        self.calls += 1
        if self.calls == 2:
            self.clock[0] = 1160.0
            if self.fail_after:
                raise RuntimeError("trusted Studio disconnected")
        scope = self.first_scope if self.calls == 1 else SCOPE
        seq = self.calls
        stamp = 1000 if seq == 1 else 1140
        evidence = "a" * 64 if seq == 1 else "b" * 64
        frame = GameFrame(scope, seq, stamp, evidence, True, True, 0.96)
        changed = seq == 1 or self.after_changed
        return VisualEvidence(frame, evidence, 124, changed, "test only", changed)

    def disarm(self):
        self.disarmed = True


class Lab:
    def __init__(self, *, memory=False, first_scope=SCOPE, after_changed=True,
                 fail_after=False):
        self.clock = [1020.0]
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=HOLDOUT)
        self.episode = None
        if memory:
            self.episode = StreamEpisode(
                self.bank, game_id="obby", game_version="v4",
                objective_id="jump_gap", situation_id="ledge",
            )
            self.episode.start(owner_approved=True, now_unix_s=NOW-5)
        self.bridge = StudioOutcomeBridge(self.bank, episode=self.episode)
        self.forecasts = GamePredictionLab(self.bank)
        self.forecasts.enable(owner_approved=True)
        self.host = StudioPlaytestHost(
            clock_ms=lambda: self.clock[0],
            sleeper=lambda sec: self.clock.__setitem__(0, self.clock[0] + sec*1000),
        )
        self.host.start(
            studio_id="studio_3", scope=SCOPE,
            bindings=[StudioBinding("jump", "SPACE")], owner_approved=True,
        )
        self.port = FakePort()
        self.observer = FakeObserver(
            self.clock, after_changed=after_changed,
            first_scope=first_scope, fail_after=fail_after,
        )
        self.live = [TELEMETRY]
        self.telemetry_calls = 0
        self.forecast = GameForecast(
            "obby", "v4", "jump_gap", "ledge", "jump", "run_1",
            "star_v1", 7000, NOW,
        )
        self.scorer_calls = 0
        self.outcome = "success"
        self.bad_signature = False
        self.bad_scope = False
        self.scorer_raises = False
        self.on_telemetry = None

        async def scorer(delivery, after):
            self.scorer_calls += 1
            if self.scorer_raises:
                raise TimeoutError("independent evaluator absent")
            draft = GameTrial(
                "trial_1", "obby", "v4", "jump_gap", "ledge", "jump",
                "run_1", "practice", self.outcome, "0" * 64, NOW,
            )
            trial = replace(draft, evidence_sha256=transition_digest(
                delivery, after.frame, trial=draft,
            ))
            if self.bad_scope:
                trial = replace(trial, objective_id="other")
            receipt = hmac.new(
                PRACTICE, trial.canonical_bytes(), hashlib.sha256,
            ).hexdigest()
            if self.bad_signature:
                receipt = "0" * 64
            return SignedPracticeVerdict(trial, receipt)

        def telemetry_provider():
            self.telemetry_calls += 1
            if self.on_telemetry:
                self.on_telemetry(self.telemetry_calls)
            return self.live[0]

        self.cycle = StudioPracticeCycle(
            host=self.host, port=self.port, observer=self.observer,
            bridge=self.bridge, forecasts=self.forecasts,
            score_independently=scorer,
            telemetry_provider=telemetry_provider,
            clock_ms=lambda: self.clock[0], unix_seconds=lambda: NOW,
        )

    def enable(self):
        self.cycle.enable(owner_approved=True, private_studio_confirmed=True)

    def run(self, *, forecast=None):
        return asyncio.run(self.cycle.run_once(
            forecast=forecast or self.forecast, hold_ms=70,
        ))

    def close(self):
        self.forecasts.close()
        self.bank.close()


@pytest.fixture
def lab():
    result = Lab()
    try:
        yield result
    finally:
        result.close()


def test_disabled_by_default_never_touches_port(lab):
    result = lab.run()
    assert result.status == "disabled"
    assert not lab.port.keys
    assert lab.observer.calls == 0


def test_owner_and_private_studio_opt_in_required(lab):
    with pytest.raises(PermissionError):
        lab.cycle.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        lab.cycle.enable(private_studio_confirmed=True)
    lab.enable()
    assert lab.run().practice_recorded
    with pytest.raises(RuntimeError):
        lab.enable()


def test_real_dispatch_to_signed_success_calibration_and_episode():
    case = Lab(memory=True)
    try:
        case.enable()
        r = case.run()
        assert r.status == "recorded_calibrated" and r.input_delivered
        assert r.practice_recorded and r.forecast_calibrated
        assert r.episode_memory_updated and r.input_release_confirmed
        assert not r.certified_game_mastery and not r.authorized_to_stream
        assert case.port.keys == [("down", "SPACE"), ("up", "SPACE")]
        assert case.bank.practice_evidence(
            "obby", "v4", "jump_gap", "ledge", now_unix_s=NOW,
        )[0].successes == 1
        assert case.forecasts.report("star_v1", game_id="obby",
                                     game_version="v4").trials == 1
        assert case.observer.disarmed
        assert case.run().status == "disabled"
        assert len(case.port.keys) == 2
    finally:
        case.close()


def test_signed_failure_is_real_learning_not_invented_success(lab):
    lab.outcome = "failure"
    lab.enable()
    result = lab.run()
    assert result.status == "recorded_calibrated"
    assert result.practice_recorded and result.forecast_calibrated
    evidence = lab.bank.practice_evidence(
        "obby", "v4", "jump_gap", "ledge", now_unix_s=NOW,
    )
    assert (evidence[0].trials, evidence[0].successes) == (1, 0)


def test_live_stream_or_unmeasured_headroom_defers_all_input(lab):
    lab.live[0] = replace(TELEMETRY, live=True)
    lab.enable()
    r = lab.run()
    assert r.status == "deferred" and not r.input_delivered
    assert not lab.port.keys and not lab.scorer_calls
    assert lab.forecasts.metrics()["committed"] == 0


@pytest.mark.parametrize("bad", [
    replace(TELEMETRY, game_fps=15),
    replace(TELEMETRY, game_active=False),
    replace(TELEMETRY, speech_backlog_ms=400),
    replace(TELEMETRY, free_vram_mib=500),
])
def test_offline_resource_shortages_do_not_press_keys(bad):
    case = Lab()
    try:
        case.live[0] = bad
        case.enable()
        assert case.run().status == "deferred"
        assert not case.port.keys
    finally:
        case.close()


def test_change_to_live_during_dispatch_revokes_key_pulse(lab):
    def switch(call):
        if call == 4:
            lab.live[0] = replace(TELEMETRY, live=True)
    lab.on_telemetry = switch
    lab.enable()
    result = lab.run()
    assert result.status == "input_failed" and not result.input_delivered
    assert not any(ev[0] == "down" for ev in lab.port.keys)
    assert lab.forecasts.metrics()["pending"] == 0


def test_wrong_scope_before_action_rejected():
    case = Lab(first_scope=GameScope("other_game", "v4", "run_1"))
    try:
        case.enable()
        assert case.run().status == "invalid_evidence"
        assert not case.port.keys and not case.scorer_calls
    finally:
        case.close()


def test_mismatched_forecast_cannot_select_another_action(lab):
    lab.enable()
    wrong = replace(lab.forecast, action_id="dash")
    result = lab.run(forecast=wrong)
    assert result.status in ("action_denied", "forecast_rejected")
    assert not lab.port.keys and not lab.scorer_calls


def test_duplicate_post_action_frame_is_not_verified():
    case = Lab(after_changed=False)
    try:
        case.enable()
        result = case.run()
        assert result.status == "invalid_evidence"
        assert result.input_delivered and not result.practice_recorded
        assert case.forecasts.metrics()["pending"] == 0
        assert case.port.keys == [("down", "SPACE"), ("up", "SPACE")]
    finally:
        case.close()


def test_scoring_timeout_does_not_forge_an_outcome(lab):
    lab.scorer_raises = True
    lab.enable()
    result = lab.run()
    assert result.status == "inconclusive" and result.input_delivered
    assert not result.practice_recorded
    assert lab.bank.practice_evidence(
        "obby", "v4", "jump_gap", "ledge", now_unix_s=NOW,
    ) == ()
    assert lab.forecasts.metrics()["pending"] == 0


def test_bad_independent_signature_cannot_enter_skill_bank(lab):
    lab.bad_signature = True
    lab.enable()
    r = lab.run()
    assert r.status == "inconclusive" and r.input_delivered
    assert not r.practice_recorded and not r.forecast_calibrated
    assert lab.bank.practice_evidence(
        "obby", "v4", "jump_gap", "ledge", now_unix_s=NOW,
    ) == ()


def test_scoring_wrong_objective_prevented_before_ledger(lab):
    lab.bad_scope = True
    lab.enable()
    r = lab.run()
    assert r.status == "result_rejected" and r.input_delivered
    assert lab.bridge.metrics()["accepted"] == 0


def test_key_release_failure_is_never_reported_safe(lab):
    lab.port.fail_up = True
    lab.enable()
    r = lab.run()
    assert r.status == "input_failed"
    assert not r.input_release_confirmed
    assert lab.host.metrics()["key_release_pending"]
    assert lab.forecasts.metrics()["pending"] == 0


def test_nonfinite_timeout_rejected(lab):
    with pytest.raises(ValueError):
        StudioPracticeCycle(
            host=lab.host, port=lab.port, observer=lab.observer,
            bridge=lab.bridge, forecasts=lab.forecasts,
            score_independently=lambda *_: None,
            telemetry_provider=lambda: TELEMETRY,
            clock_ms=lambda: 0, unix_seconds=lambda: NOW,
            stage_timeout_s=float("nan"),
        )
