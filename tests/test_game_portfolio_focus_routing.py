"""Offline integration tests for fair, signed-evidence-guided game practice.

Forecasts are committed before signer-observed trials, never created from
viewer chat or hidden validation. No Studio keypress, network or GPU is used.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from star.game_learning_ladder import GameLearningLadder, PracticeSituation
from star.game_portfolio_practice import GamePortfolioPractice
from star.game_prediction_lab import GameForecast, GamePredictionLab
from star.gameplay_skill_bank import GameTrial, GameplaySkillBank
from star.stream_budget import StreamTelemetry

NOW = 2_000_000_000
PRACTICE = hashlib.sha256(b"portfolio-focus-independent-practice").digest()
VALIDATION = hashlib.sha256(b"portfolio-focus-independent-validation").digest()
DIGEST = hashlib.sha256(b"test-only-game-observation").hexdigest()


def telemetry(*, live=False):
    return StreamTelemetry(
        live=live, game_active=True, free_vram_mib=4096,
        total_vram_mib=8192, game_fps=60, speech_backlog_ms=0,
    )


class Rig:
    def __init__(self):
        self.bank = GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION)
        self.lab = GamePredictionLab(self.bank)
        self.lab.enable(owner_approved=True)
        self.ladders = tuple(
            GameLearningLadder(
                self.bank, game_id=game, game_version="v1",
                objective_id="finish",
                situations=(PracticeSituation("intro", "jump", 1),),
            )
            for game in ("arena", "obby", "racer")
        )
        for ladder in self.ladders:
            ladder.enable(owner_approved=True)
        self.host = None
        self.serial = 0

    def portfolio(self, *, model="star_v1", with_focus=True):
        self.host = GamePortfolioPractice(
            self.bank, ladders=self.ladders,
            prediction_lab=self.lab if with_focus else None,
            prediction_model_id=model if with_focus else None,
        )
        self.host.enable(owner_approved=True)
        return self.host

    def sign(self, game, run, *, when=NOW, action="jump", outcome="failure",
             split="practice"):
        self.serial += 1
        trial = GameTrial(
            f"trial_{self.serial}", game, "v1", "finish", "intro",
            action, run, split, outcome, DIGEST, when,
        )
        key = PRACTICE if split == "practice" else VALIDATION
        receipt = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        self.bank.ingest(trial, receipt, now_unix_s=when)
        return trial

    def forecast_errors(
        self, *, game="obby", action="jump", model="star_v1",
        age_seconds=50, split="practice", n=8,
    ):
        for idx in range(n):
            now = NOW - age_seconds + idx
            run = f"practice_{self.serial}_{idx}"
            assert self.lab.precommit(
                GameForecast(
                    game, "v1", "finish", "intro", action,
                    run, model, 9000, now,
                ), now_unix_s=now,
            )
            trial = self.sign(
                game, run, when=now, action=action,
                outcome="failure", split=split,
            )
            assert self.lab.resolve(trial, now_unix_s=now) is (split == "practice")

    def close(self):
        if self.host is not None:
            self.host.disable()
        self.lab.close()
        self.bank.close()


@pytest.fixture
def rig():
    item = Rig()
    try:
        yield item
    finally:
        item.close()


def test_no_diagnostic_dependency_preserves_existing_fair_order(rig):
    host = rig.portfolio(with_focus=False)
    offer = host.reserve(now_unix_s=NOW, telemetry=telemetry())
    assert offer.game_id == "arena"
    assert offer.authorized_to_play is False
    assert host.metrics()["focus_routed"] == 0


def test_signed_prediction_errors_select_current_eligible_action(rig):
    rig.forecast_errors()
    host = rig.portfolio()
    offer = host.reserve(now_unix_s=NOW, telemetry=telemetry())
    assert offer.game_id == "obby"  # unlike unconditioned lexicographic 'arena'
    assert (offer.situation_id, offer.action_id) == ("intro", "jump")
    assert offer.authorized_to_play is False
    assert host.metrics()["focus_routed"] == 1
    assert host.matches_reservation(offer, now_unix_s=NOW)

    # Signed new practice does not excuse favoring obby a second time:
    # the next unpracticed game must receive its fair exposure.
    rig.sign("obby", offer.expected_run_id, when=NOW)
    assert host.finish(offer.ticket, now_unix_s=NOW, host_reports_recorded=True)
    subsequent = host.reserve(now_unix_s=NOW + 2, telemetry=telemetry())
    assert subsequent.game_id == "arena"


def test_focus_never_ignores_offline_streaming_priority(rig):
    rig.forecast_errors()
    host = rig.portfolio()
    decision = host.reserve(now_unix_s=NOW, telemetry=telemetry(live=True))
    assert decision.status == "deferred"
    assert host.metrics()["focus_routed"] == 0


def test_irrelevant_action_forecasts_do_not_retarget_game(rig):
    rig.forecast_errors(action="crouch")
    host = rig.portfolio()
    assert host.reserve(now_unix_s=NOW, telemetry=telemetry()).game_id == "arena"


def test_model_version_scope_and_aged_forecasts_are_not_reused(rig):
    rig.forecast_errors(model="other_model")
    host = rig.portfolio()
    assert host.reserve(now_unix_s=NOW, telemetry=telemetry()).game_id == "arena"

    other = Rig()
    try:
        other.forecast_errors(age_seconds=15 * 86400)
        aged = other.portfolio()
        assert aged.reserve(now_unix_s=NOW, telemetry=telemetry()).game_id == "arena"
    finally:
        other.close()


def test_independent_validation_never_drives_practice_focus(rig):
    rig.forecast_errors(split="validation")
    host = rig.portfolio()
    assert host.reserve(now_unix_s=NOW, telemetry=telemetry()).game_id == "arena"
    assert host.metrics()["focus_routed"] == 0


def test_disabled_diagnostics_do_not_get_used(rig):
    rig.forecast_errors()
    rig.lab.disable()
    host = rig.portfolio()
    assert host.reserve(now_unix_s=NOW, telemetry=telemetry()).game_id == "arena"
    assert host.metrics()["focus_routed"] == 0


def test_closed_or_corrupt_prediction_lab_defers_instead_of_guessing(rig):
    rig.lab.close()
    host = rig.portfolio()
    result = host.reserve(now_unix_s=NOW, telemetry=telemetry())
    assert (result.status, result.reason) == (
        "deferred", "verified_prediction_diagnostics_unavailable",
    )
    assert host.metrics()["focus_unavailable"] == 1
    assert host.metrics()["offered"] == 0


def test_prediction_lab_identity_and_model_id_validation(rig):
    with pytest.raises(ValueError):
        GamePortfolioPractice(
            rig.bank, ladders=rig.ladders,
            prediction_model_id="star_v1",
        )
    with pytest.raises(ValueError):
        GamePortfolioPractice(
            rig.bank, ladders=rig.ladders,
            prediction_lab=rig.lab,
        )
    with pytest.raises(ValueError):
        GamePortfolioPractice(
            rig.bank, ladders=rig.ladders,
            prediction_lab=rig.lab, prediction_model_id="../../bad",
        )
    with GameplaySkillBank(
        practice_key=PRACTICE, validation_key=VALIDATION,
    ) as other_bank:
        with GamePredictionLab(other_bank) as other_lab:
            with pytest.raises(ValueError):
                GamePortfolioPractice(
                    rig.bank, ladders=rig.ladders,
                    prediction_lab=other_lab, prediction_model_id="star_v1",
                )


def test_failure_review_is_not_overridden_by_high_prediction_error(rig):
    # Twelve signed failures hit the ladder's diagnosis threshold. Even a
    # strong calibration error cannot sneak past the eligible-action filter.
    rig.forecast_errors(n=12)
    host = rig.portfolio()
    chosen = host.reserve(now_unix_s=NOW, telemetry=telemetry())
    assert chosen.game_id == "arena"
    assert host.metrics()["focus_routed"] == 0
