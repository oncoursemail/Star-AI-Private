"""Offline end-to-end fake game observation -> input -> signed feedback tests."""
from dataclasses import replace
import hashlib
import hmac

import pytest

from star.game_action_gate import GameActionHint, GameFrame, GameScope
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_budget import StreamTelemetry
from star.studio_playtest_host import (
    StudioBinding, StudioPlaytestHost, StudioSnapshot,
)
from star.studio_outcome_bridge import StudioOutcomeBridge, transition_digest
from star.stream_episode import StreamEpisode

SCOPE = GameScope("obby", "v4", "run_1")
PRACTICE = b"p" * 32
HOLDOUT = b"v" * 32
NOW = 1_782_500_000


class FakePort:
    def __init__(self):
        self.view = StudioSnapshot("studio_3", SCOPE, True, True, True, True)
        self.keys = []
        self.fail_up = False

    def snapshot(self, studio_id):
        assert studio_id == "studio_3"
        return self.view

    def key_down(self, studio_id, key):
        self.keys.append(("down", key))

    def key_up(self, studio_id, key):
        self.keys.append(("up", key))
        if self.fail_up:
            raise OSError("missing key-up confirmation")


def setup(*, with_episode=False):
    bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=HOLDOUT)
    episode = None
    if with_episode:
        episode = StreamEpisode(
            bank, game_id="obby", game_version="v4",
            objective_id="jump_gap", situation_id="ledge")
        episode.start(owner_approved=True, now_unix_s=NOW - 8)
    bridge = StudioOutcomeBridge(bank, episode=episode)
    clock = [1020.0]

    def advance(delta_seconds):
        clock[0] += 1000 * delta_seconds

    host = StudioPlaytestHost(clock_ms=lambda: clock[0], sleeper=advance)
    host.start(studio_id="studio_3", scope=SCOPE,
               bindings=[StudioBinding("jump", "SPACE")],
               owner_approved=True)
    frame = GameFrame(SCOPE, 1, 1000, "a" * 64, True, True, 0.99)
    proposal = GameActionHint("jump", 1, frame.evidence_sha256, 1010, 70)
    tele = StreamTelemetry(False, True, 4000, 8192, 60, 0)
    permit = host.request(frame, proposal, now_ms=1020,
                          host_verified=True, telemetry=tele)
    assert permit.offered
    port = FakePort()
    report = host.dispatch(permit, port=port)
    assert report.sent and report.input_released
    assert port.keys == [("down", "SPACE"), ("up", "SPACE")]
    return bank, episode, bridge, host, report, clock


def signed_feedback(host, report, *, outcome="success", **changes):
    delivery = host.inspect_delivery(report)
    assert delivery is not None
    after = GameFrame(SCOPE, 2, delivery.released_ms + 80,
                      "b" * 64, True, True, 0.96)
    draft = GameTrial(
        trial_id="trial_1", game_id="obby", game_version="v4",
        objective_id="jump_gap", situation_id="ledge", action_id="jump",
        run_id="run_1", split="practice", outcome=outcome,
        evidence_sha256="0" * 64, observed_unix_s=NOW,
    )
    trial = replace(draft, evidence_sha256=transition_digest(
        delivery, after, trial=draft))
    if "trial" in changes:
        trial = changes["trial"](trial)
    if "after" in changes:
        after = changes["after"](after)
    signature = hmac.new(
        PRACTICE if trial.split == "practice" else HOLDOUT,
        trial.canonical_bytes(), hashlib.sha256).hexdigest()
    return after, trial, signature


def record(bridge, host, report, clock, after, trial, receipt,
           *, verified=True):
    clock[0] = max(clock[0], after.captured_ms + 20)
    return bridge.record(
        host=host, dispatch=report, after=after, trial=trial,
        host_verified_after=verified, signed_practice_receipt=receipt,
        now_ms=clock[0], now_unix_s=NOW + 1)


def test_verified_dispatch_to_signed_gameplay_skill_and_stream_memory():
    bank, episode, bridge, host, report, clock = setup(with_episode=True)
    after, trial, receipt = signed_feedback(host, report)
    result = record(bridge, host, report, clock, after, trial, receipt)
    assert result.accepted and result.episode_memory_updated
    assert not result.mastery_proven
    assert bank.verify_practice_trial(trial, now_unix_s=NOW + 1)
    rows = bank.practice_evidence("obby", "v4", "jump_gap", "ledge",
                                  now_unix_s=NOW + 1)
    assert len(rows) == 1
    assert (rows[0].action_id, rows[0].trials, rows[0].successes) == (
        "jump", 1, 1)
    assert bridge.metrics() == {
        "accepted": 1, "rejected": 0, "episode_updates": 1}
    assert host.metrics()["deliveries_claimed"] == 1
    assert host.inspect_delivery(report) is None
    with pytest.raises(PermissionError):
        record(bridge, host, report, clock, after, trial, receipt)
    bank.close()


def test_real_failed_attempt_is_still_valid_training_evidence():
    bank, _, bridge, host, report, clock = setup()
    after, trial, receipt = signed_feedback(host, report, outcome="failure")
    result = record(bridge, host, report, clock, after, trial, receipt)
    assert result.accepted and not result.mastery_proven
    rows = bank.practice_evidence("obby", "v4", "jump_gap", "ledge",
                                  now_unix_s=NOW + 1)
    assert (rows[0].trials, rows[0].successes) == (1, 0)
    bank.close()


def test_copied_dispatch_report_cannot_score_a_game():
    bank, _, bridge, host, report, clock = setup()
    after, trial, receipt = signed_feedback(host, report)
    copied = replace(report)
    assert host.inspect_delivery(copied) is None
    with pytest.raises(PermissionError):
        record(bridge, host, copied, clock, after, trial, receipt)
    assert not bridge.metrics()["accepted"]
    # Rejected copy must not consume the actual host report.
    assert record(bridge, host, report, clock, after, trial, receipt).accepted
    bank.close()


@pytest.mark.parametrize("case", [
    "wrong_game", "stale_frame", "repeated_frame", "low_confidence",
    "post_frame_missing_attestation", "wrong_action", "wrong_outcome",
    "wrong_trial_digest", "wrong_run", "wrong_split", "invalid_receipt",
    "old_verdict", "precedes_key_up", "unfocused",
])
def test_reject_unbound_or_unsafe_post_action_evidence(case):
    bank, _, bridge, host, report, clock = setup()
    after, trial, receipt = signed_feedback(host, report)
    verified = True
    if case == "wrong_game":
        after = replace(after, scope=GameScope("other", "v4", "run_1"))
    elif case == "stale_frame":
        clock[0] = 14_000
    elif case == "repeated_frame":
        after = replace(after, sequence=1)
    elif case == "low_confidence":
        after = replace(after, perception_confidence=0.24)
    elif case == "post_frame_missing_attestation":
        verified = False
    elif case == "wrong_action":
        trial = replace(trial, action_id="move")
    elif case == "wrong_outcome":
        trial = replace(trial, outcome="failure")
    elif case == "wrong_trial_digest":
        trial = replace(trial, evidence_sha256="f" * 64)
    elif case == "wrong_run":
        trial = replace(trial, run_id="run_2")
    elif case == "wrong_split":
        trial = replace(trial, split="validation")
    elif case == "invalid_receipt":
        receipt = "a" * 64
    elif case == "old_verdict":
        trial = replace(trial, observed_unix_s=NOW - 100)
    elif case == "precedes_key_up":
        after = replace(after, captured_ms=1001)
    elif case == "unfocused":
        after = replace(after, focus_confirmed=False)
    with pytest.raises((PermissionError, ValueError)):
        record(bridge, host, report, clock, after, trial, receipt,
               verified=verified)
    assert bridge.metrics()["accepted"] == 0
    assert host.inspect_delivery(report) is None  # single-use even on failure
    assert bank.practice_evidence("obby", "v4", "jump_gap", "ledge",
                                  now_unix_s=NOW + 1) == ()
    bank.close()


def test_digest_is_sensitive_to_observation_and_result():
    bank, _, _, host, report, _ = setup()
    after, trial, receipt = signed_feedback(host, report)
    delivery = host.inspect_delivery(report)
    assert transition_digest(delivery, after, trial=trial) == trial.evidence_sha256
    assert transition_digest(delivery, replace(after, evidence_sha256="c" * 64),
                             trial=trial) != trial.evidence_sha256
    assert transition_digest(delivery, after,
                             trial=replace(trial, outcome="failure")) != trial.evidence_sha256
    bank.close()


def test_unauthorized_or_failed_key_up_never_mints_delivery():
    now = [1020.0]
    host = StudioPlaytestHost(clock_ms=lambda: now[0],
                              sleeper=lambda d: now.__setitem__(0, now[0] + d * 1000))
    host.start(studio_id="studio_3", scope=SCOPE,
               bindings=[StudioBinding("jump", "SPACE")], owner_approved=True)
    frame = GameFrame(SCOPE, 1, 1000, "a" * 64, True, True, 0.95)
    proposal = GameActionHint("jump", 1, frame.evidence_sha256, 1010, 70)
    tele = StreamTelemetry(False, True, 4000, 8192, 60, 0)
    permit = host.request(frame, proposal, now_ms=1020,
                          host_verified=True, telemetry=tele)
    port = FakePort()
    port.fail_up = True
    report = host.dispatch(permit, port=port)
    assert not report.sent and not report.input_released
    assert host.inspect_delivery(report) is None
    assert host.claim_delivery(report) is None
    assert host.metrics()["key_release_pending"]


def test_preview_does_not_consume_and_double_claim_fails():
    bank, _, bridge, host, report, clock = setup()
    first = host.inspect_delivery(report)
    second = host.inspect_delivery(report)
    assert first is second
    assert host.claim_delivery(report) is first
    assert host.inspect_delivery(report) is None
    assert host.claim_delivery(report) is None
    assert bridge.metrics()["accepted"] == 0
    bank.close()


def test_nonplayable_completion_screen_can_be_scored():
    bank, _, bridge, host, report, clock = setup()
    after, trial, receipt = signed_feedback(host, report)
    after = replace(after, playable=False)  # completed game transitions to menu
    assert record(bridge, host, report, clock, after, trial, receipt).accepted
    bank.close()


def test_missing_stream_permission_does_not_publish_a_stream_event():
    bank, episode, bridge, host, report, clock = setup(with_episode=False)
    after, trial, receipt = signed_feedback(host, report)
    result = record(bridge, host, report, clock, after, trial, receipt)
    assert result.accepted and not result.episode_memory_updated
    assert episode is None
    bank.close()