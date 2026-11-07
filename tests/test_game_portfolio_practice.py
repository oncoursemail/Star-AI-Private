"""Host-only, signed-evidence tests for Star's fair multi-game curriculum."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac

import pytest

from star.game_learning_ladder import GameLearningLadder, PracticeSituation
from star.game_portfolio_practice import GamePortfolioPractice
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_budget import StreamTelemetry

PRACTICE = hashlib.sha256(b"isolated-portfolio-test-practice-signing-key").digest()
VALIDATION = hashlib.sha256(b"isolated-portfolio-test-holdout-signing-key").digest()
NOW = 2_000_000_000
SHA = hashlib.sha256(b"independent-test-only-evidence").hexdigest()


def telemetry(*, live=False, fps=60, free=4096, backlog=0):
    return StreamTelemetry(
        live=live, game_active=True, free_vram_mib=free,
        total_vram_mib=8192, game_fps=fps, speech_backlog_ms=backlog,
    )


class Rig:
    def __init__(self, *, n=3, enabled=True):
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.games = ("arena", "obby", "racer")[:n]
        self.ladders = {}
        for game in self.games:
            ladder = GameLearningLadder(
                self.bank, game_id=game, game_version="v1", objective_id="finish",
                situations=(PracticeSituation("intro", "jump", 1),),
            )
            if enabled:
                ladder.enable(owner_approved=True)
            self.ladders[game] = ladder
        self.host = GamePortfolioPractice(
            self.bank, ladders=tuple(self.ladders.values()),
        )
        self.serial = 0

    def enable(self):
        self.host.enable(owner_approved=True)

    def reserve(self, now=NOW, tele=None):
        return self.host.reserve(
            now_unix_s=now, telemetry=telemetry() if tele is None else tele,
        )

    def sign(self, *, game, run="host_run", action="jump",
             situation="intro", version="v1", objective="finish",
             outcome="success", split="practice", at=NOW):
        self.serial += 1
        trial = GameTrial(
            f"portfolio_trial_{self.serial}", game, version, objective,
            situation, action, run, split, outcome, SHA, at,
        )
        key = PRACTICE if split == "practice" else VALIDATION
        sig = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        self.bank.ingest(trial, sig, now_unix_s=at)
        return trial

    def close(self):
        self.host.disable()
        self.bank.close()


@pytest.fixture
def rig():
    example = Rig()
    try:
        yield example
    finally:
        example.close()


def test_separate_opt_in_and_allows_no_live_game_actions(rig):
    decision = rig.reserve()
    assert (decision.status, decision.reason) == ("deferred", "owner_opt_in_missing")
    with pytest.raises(PermissionError):
        rig.host.enable(owner_approved=1)
    rig.enable()
    first = rig.reserve()
    assert first.status == "practice_candidate"
    assert first.game_id == "arena"
    assert first.authorized_to_play is False
    assert first.ticket > 0
    assert first.expected_run_id.startswith("apr_")
    assert first.situation_id == "intro"
    assert first.action_id == "jump"
    with pytest.raises(RuntimeError):
        rig.enable()


def test_works_across_three_games_not_one_easy_game(rig):
    rig.enable()
    chosen = []
    for i in range(3):
        now = NOW + 2 * i
        item = rig.reserve(now)
        chosen.append(item.game_id)
        rig.sign(game=item.game_id, run=item.expected_run_id, at=now)
        assert rig.host.finish(item.ticket, now_unix_s=now,
                               host_reports_recorded=True)
    assert chosen == ["arena", "obby", "racer"]
    assert rig.host.metrics()["verified"] == 3
    fourth = rig.reserve(NOW + 6)
    assert fourth.status == "practice_candidate"
    assert fourth.game_id == "arena"
    assert fourth.authorized_to_play is False


def test_forged_confirmation_or_holdout_never_counts_as_learning(rig):
    rig.enable()
    item = rig.reserve()
    rig.sign(game=item.game_id, run=item.expected_run_id, split="validation")
    assert not rig.host.finish(item.ticket, now_unix_s=NOW,
                               host_reports_recorded=True)
    assert rig.host.metrics()["verified"] == 0
    second = rig.reserve(NOW + 2)
    rig.sign(game="racer", run=second.expected_run_id, split="practice", at=NOW + 2)
    assert not rig.host.finish(second.ticket, now_unix_s=NOW + 2,
                               host_reports_recorded=True)
    assert rig.host.metrics()["verified"] == 0
    assert rig.host.metrics()["unverified"] == 2


def test_exact_signed_practice_run_is_required(rig):
    rig.enable()
    item = rig.reserve()
    rig.sign(game=item.game_id, run="different_verified_run")
    assert not rig.host.finish(item.ticket, now_unix_s=NOW,
                               host_reports_recorded=True)
    next_one = rig.reserve(NOW + 2)
    rig.sign(game=next_one.game_id, run=next_one.expected_run_id,
             action="unrelated", at=NOW + 2)
    assert not rig.host.finish(next_one.ticket, now_unix_s=NOW + 2,
                               host_reports_recorded=True)
    assert rig.host.metrics()["verified"] == 0


def test_playback_and_low_fps_take_priority_over_training(rig):
    rig.enable()
    for t in (
        telemetry(live=True), telemetry(fps=49), telemetry(free=1000),
        telemetry(backlog=251),
    ):
        assert rig.reserve(NOW, t).status == "deferred"
    assert rig.host.metrics()["offered"] == 0
    assert rig.host.reserve(now_unix_s=NOW, telemetry=None).status == "deferred"
    assert rig.host.metrics()["pending"] is False


def test_unauthorized_ladder_is_not_silently_enabled(rig):
    rig.enable()
    rig.ladders["arena"].disable()
    first = rig.reserve()
    assert first.game_id == "obby"


def test_expired_reservation_does_not_block_every_other_game(rig):
    rig.enable()
    first = rig.reserve()
    assert rig.reserve(NOW + 1).reason == "signed_practice_pending"
    after_expiry = rig.reserve(NOW + 91)
    assert after_expiry.status == "practice_candidate"
    assert after_expiry.ticket != first.ticket
    assert rig.host.metrics()["expired"] == 1
    assert not rig.host.finish(first.ticket, now_unix_s=NOW + 91,
                               host_reports_recorded=True)


def test_failure_cooldown_and_manual_diagnosis_prevent_infinite_retry(rig):
    rig.ladders["obby"].disable()
    rig.ladders["racer"].disable()
    rig.enable()
    for attempt in range(3):
        now = NOW + attempt * 20
        choice = rig.reserve(now)
        assert choice.game_id == "arena"
        assert not rig.host.finish(
            choice.ticket, now_unix_s=now, host_reports_recorded=True
        )
        assert rig.reserve(now + 1).status == "deferred"
    assert rig.host.metrics()["games_requiring_review"] == 1
    assert rig.reserve(NOW + 61).status == "deferred"
    assert rig.host.metrics()["offered"] == 3


def test_completes_only_when_all_signed_practice_ladders_report_mastery(rig):
    for game in rig.games:
        for i in range(20):
            rig.sign(game=game, run=f"past_{game}_{i}", at=NOW - 20 + i)
    rig.enable()
    done = rig.reserve()
    assert done.status == "complete"
    assert "not_holdout_proof" in done.reason
    assert done.ticket is None


def test_one_game_stalled_routes_to_others(rig):
    for i in range(12):
        rig.sign(game="arena", run=f"fail_{i}", outcome="failure", at=NOW - 12 + i)
    rig.enable()
    advice = rig.reserve()
    assert advice.game_id == "obby"
    assert advice.status == "practice_candidate"


def test_session_disable_rejects_old_ticket_and_new_session_can_progress(rig):
    rig.enable()
    first = rig.reserve()
    rig.host.disable()
    assert not rig.host.finish(first.ticket, now_unix_s=NOW,
                               host_reports_recorded=True)
    rig.enable()
    next_one = rig.reserve(NOW)
    assert next_one.ticket != first.ticket
    rig.sign(game=next_one.game_id, run=first.expected_run_id)
    assert not rig.host.finish(next_one.ticket, now_unix_s=NOW,
                               host_reports_recorded=True)


def test_monotonic_clock_and_strict_inputs(rig):
    rig.enable()
    assert rig.reserve(NOW).ticket
    with pytest.raises(ValueError):
        rig.host.finish(True, now_unix_s=NOW)
    with pytest.raises(ValueError):
        rig.host.finish(1, now_unix_s=NOW, host_reports_recorded=1)
    with pytest.raises(ValueError):
        rig.reserve(NOW - 1)
    with pytest.raises(TypeError):
        rig.host.reserve(now_unix_s=NOW, telemetry="fake GPU metrics")


def test_inflight_concurrent_callers_do_not_read_cross_thread_sqlite(rig):
    rig.enable()
    first = rig.reserve()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: rig.reserve(), range(24)))
    assert all(x.reason == "signed_practice_pending" for x in results)
    assert rig.host.metrics()["offered"] == 1
    assert first.game_id not in str(rig.host.metrics())
    assert first.expected_run_id not in str(rig.host.metrics())


def test_invalid_and_duplicate_portfolio_boundaries(rig):
    with pytest.raises(ValueError):
        GamePortfolioPractice(rig.bank, ladders=(rig.ladders["arena"],))
    with pytest.raises(ValueError):
        GamePortfolioPractice(
            rig.bank, ladders=(rig.ladders["arena"], rig.ladders["arena"])
        )
    separate = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
    try:
        with pytest.raises(ValueError):
            GamePortfolioPractice(
                separate, ladders=tuple(rig.ladders.values())
            )
    finally:
        separate.close()
