"""One-shot, owner-enabled private Studio practice: observe -> act -> verify -> learn.

This composes EXISTING trusted hosts instead of adding another synthetic score
gate. STAR proposes a bounded symbolic action and a prospective probability;
the Studio host checks real focus/private play, dispatches a short input pulse,
and an independent evaluator signs the observed outcome. Only then may the
skill bank, calibration ledger and optional episode memory update.

This module never starts Studio, opens a game, goes live, downloads media,
selects its own signing keys, controls an OS outside the supplied StudioInputPort,
or claims that practice success proves holdout mastery. It is not enabled by
default. The observer and scorer MUST belong to an independent authorized host.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
from typing import Awaitable, Callable, Protocol

from .game_action_gate import GameActionHint
from .game_prediction_lab import GameForecast, GamePredictionLab
from .gameplay_skill_bank import GameTrial
from .stream_budget import StreamTelemetry, advise_workload
from .studio_outcome_bridge import StudioOutcomeBridge
from .studio_playtest_host import (
    DeliveredAction, StudioInputPort, StudioPlaytestHost,
)
from .studio_visual_evidence import VisualEvidence


class TrustedObservationSource(Protocol):
    async def observe(self) -> VisualEvidence: ...
    def disarm(self) -> None: ...


@dataclass(frozen=True)
class SignedPracticeVerdict:
    """The separately trusted evaluator owns this receipt, not STAR."""
    trial: GameTrial
    receipt_sha256: str


@dataclass(frozen=True)
class PracticeCycleResult:
    status: str
    reason: str
    input_delivered: bool = False
    practice_recorded: bool = False
    forecast_calibrated: bool = False
    episode_memory_updated: bool = False
    input_release_confirmed: bool = True
    certified_game_mastery: bool = False
    authorized_to_stream: bool = False


IndependentScorer = Callable[
    [DeliveredAction, VisualEvidence], Awaitable[SignedPracticeVerdict]
]


class _StopCycle(Exception):
    def __init__(self, status: str, reason: str, **_unused: object) -> None:
        self.status, self.reason = status, reason
        super().__init__(reason)


class StudioPracticeCycle:
    """A SINGLE bounded attempt; a new owner-approved session is needed to retry.

    Owner code creates/starts StudioPlaytestHost, arms StudioVisualObserver,
    enables the forecast lab, and supplies an independent signed-truth scorer.
    A model must not select the observer, scorer, port, telemetry, or clocks.
    Host callbacks must be short, local and cancellation-safe. Scoring can
    require its own trusted Studio inspection; a VLM summary is not truth.
    """

    def __init__(
        self, *,
        host: StudioPlaytestHost,
        port: StudioInputPort,
        observer: TrustedObservationSource,
        bridge: StudioOutcomeBridge,
        forecasts: GamePredictionLab,
        score_independently: IndependentScorer,
        telemetry_provider: Callable[[], StreamTelemetry],
        clock_ms: Callable[[], float],
        unix_seconds: Callable[[], int],
        stage_timeout_s: float = 12.0,
    ) -> None:
        if not isinstance(host, StudioPlaytestHost):
            raise TypeError("trusted StudioPlaytestHost required")
        if not isinstance(bridge, StudioOutcomeBridge):
            raise TypeError("existing signed StudioOutcomeBridge required")
        if not isinstance(forecasts, GamePredictionLab):
            raise TypeError("existing GamePredictionLab required")
        if (not callable(getattr(port, "snapshot", None))
                or not callable(getattr(port, "key_down", None))
                or not callable(getattr(port, "key_up", None))
                or not callable(getattr(observer, "observe", None))
                or not callable(getattr(observer, "disarm", None))
                or not callable(score_independently)
                or not callable(telemetry_provider)
                or not callable(clock_ms)
                or not callable(unix_seconds)):
            raise TypeError("trusted host dependencies/callbacks required")
        if (type(stage_timeout_s) not in (int, float)
                or not math.isfinite(stage_timeout_s)
                or not 0.2 <= stage_timeout_s <= 30):
            raise ValueError("stage_timeout_s must be 0.2..30 finite seconds")
        self._host, self._port, self._observer = host, port, observer
        self._bridge, self._forecasts = bridge, forecasts
        self._score, self._telemetry = score_independently, telemetry_provider
        self._clock, self._unix = clock_ms, unix_seconds
        self._timeout = float(stage_timeout_s)
        self._enabled = False
        self._used = False

    def enable(self, *, owner_approved: bool = False,
               private_studio_confirmed: bool = False) -> None:
        if owner_approved is not True or private_studio_confirmed is not True:
            raise PermissionError("owner approval and private Studio confirmation required")
        if self._used:
            raise RuntimeError("one-shot practice cycle cannot restart")
        self._enabled = True

    def _headroom(self) -> StreamTelemetry | None:
        """Read fresh host status at planning AND immediately before key down."""
        try:
            sample = self._telemetry()
            if not isinstance(sample, StreamTelemetry):
                return None
            if (sample.live or not sample.game_active or sample.game_fps < 50
                    or sample.speech_backlog_ms > 250
                    or not advise_workload("training", sample).allowed):
                return None
            return sample
        except Exception:
            return None

    def _ms(self) -> float:
        v = self._clock()
        if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1e13:
            raise ValueError("invalid independent monotonic host clock")
        return float(v)

    def _seconds(self) -> int:
        v = self._unix()
        if type(v) is not int or not 0 < v <= 10**11:
            raise ValueError("invalid independent Unix clock")
        return v

    async def _observe(self) -> VisualEvidence:
        value = await asyncio.wait_for(self._observer.observe(), self._timeout)
        if not isinstance(value, VisualEvidence):
            raise ValueError("trusted observer must return VisualEvidence")
        return value

    async def run_once(
        self, *,
        forecast: GameForecast,
        hold_ms: int,
    ) -> PracticeCycleResult:
        """Dispatch at most ONE input and ingest only independent signed truth.

        No result confers streaming/deployment permission. Dispatched failures
        count as legitimate practice only if the independent scorer signs them.
        Cancelled/stale/unsigned attempts are never converted into successes.
        """
        if not self._enabled or self._used:
            return PracticeCycleResult("disabled", "not_enabled_or_already_used")
        self._used = True
        recorded = calibrated = remembered = sent = False
        precommitted = False
        reason, status = "not_started", "deferred"
        try:
            if not isinstance(forecast, GameForecast):
                raise TypeError("expected pre-action GameForecast")
            if type(hold_ms) is not int or not 1 <= hold_ms <= 180:
                raise ValueError("bounded key hold must be 1..180 milliseconds")
            telemetry = self._headroom()
            if telemetry is None:
                raise _StopCycle("deferred", "offline_compute_or_stream_headroom")
            before = await self._observe()
            scope = before.frame.scope
            if (not before.changed or not before.actionable_when_captured
                    or not before.frame.focus_confirmed
                    or not before.frame.playable
                    or before.frame.perception_confidence < 0.75):
                raise _StopCycle("invalid_evidence", "no_fresh_playable_visual_frame")
            if ((scope.game_id, scope.version_id, scope.episode_id)
                    != (forecast.game_id, forecast.game_version, forecast.run_id)):
                raise _StopCycle("invalid_evidence", "game_or_episode_scope_mismatch")
            if self._headroom() is None:
                raise _StopCycle("deferred", "headroom_changed_before_forecast")
            now_s = self._seconds()
            if not self._forecasts.precommit(forecast, now_unix_s=now_s):
                raise _StopCycle("forecast_rejected", "prospective_forecast_not_registered")
            precommitted = True
            now_ms = self._ms()
            hint = GameActionHint(
                forecast.action_id, before.frame.sequence, before.frame.evidence_sha256,
                now_ms, hold_ms,
            )
            dispatch_telemetry = self._headroom()
            if dispatch_telemetry is None:
                raise _StopCycle("deferred", "headroom_changed_before_action")
            permit = self._host.request(
                before.frame, hint, now_ms=now_ms,
                host_verified=True, telemetry=dispatch_telemetry,
            )
            if not permit.offered:
                raise _StopCycle("action_denied", permit.reason)
            # dispatch() independently checks Studio identity/focus and a second
            # fresh telemetry snapshot immediately before physical key-down.
            dispatch = self._host.dispatch(
                permit, port=self._port,
                dispatch_guard=lambda: self._headroom() is not None,
            )
            if not dispatch.sent or not dispatch.input_released:
                raise _StopCycle("input_failed", dispatch.reason)
            sent = True
            delivery = self._host.inspect_delivery(dispatch)
            if delivery is None or delivery.action_id != forecast.action_id:
                raise _StopCycle("invalid_evidence", "input_delivery_unverified",
                                           input_delivered=True)
            after = await self._observe()
            if (after.frame.scope != scope or not after.changed
                    or not after.frame.focus_confirmed
                    or after.frame.sequence <= before.frame.sequence
                    or after.frame.perception_confidence < 0.75):
                raise _StopCycle("invalid_evidence", "post_action_frame_unverifiable",
                                           input_delivered=True)
            verdict = await asyncio.wait_for(
                self._score(delivery, after), timeout=self._timeout,
            )
            if not isinstance(verdict, SignedPracticeVerdict):
                raise _StopCycle("result_rejected", "independent_scorer_invalid",
                                           input_delivered=True)
            trial = verdict.trial
            if (not isinstance(trial, GameTrial) or trial.split != "practice"
                    or (trial.game_id, trial.game_version, trial.run_id,
                        trial.objective_id, trial.situation_id, trial.action_id)
                    != (forecast.game_id, forecast.game_version, forecast.run_id,
                        forecast.objective_id, forecast.situation_id, forecast.action_id)):
                raise _StopCycle("result_rejected", "scored_trial_scope_mismatch",
                                           input_delivered=True)
            receipt = verdict.receipt_sha256
            now_ms, now_s = self._ms(), self._seconds()
            outcome = self._bridge.record(
                host=self._host, dispatch=dispatch, after=after.frame,
                trial=trial, host_verified_after=True,
                signed_practice_receipt=receipt, now_ms=now_ms,
                now_unix_s=now_s,
            )
            recorded, remembered = outcome.accepted, outcome.episode_memory_updated
            calibrated = self._forecasts.resolve(trial, now_unix_s=now_s)
            status = "recorded_calibrated" if calibrated else "recorded_uncalibrated"
            reason = ("independently_signed_practice_only"
                      if calibrated else "practice_signed_but_forecast_not_resolved")
        except _StopCycle as stop:
            status, reason = stop.status, stop.reason
        except asyncio.CancelledError:
            raise
        except Exception:
            status, reason = "inconclusive", "host_evidence_or_scoring_unavailable"
        finally:
            if precommitted and not calibrated:
                # If the signed trial was accepted but calibration failed, the
                # practice ledger remains authoritative; cancellation only
                # invalidates that forecast, never the practice result.
                try:
                    self._forecasts.cancel(forecast.run_id)
                except Exception:
                    # Failed forecast cleanup must never prevent key release.
                    pass
            try:
                release_ok = self._host.revoke(port=self._port)
            except Exception:
                release_ok = False
            try:
                self._observer.disarm()
            except Exception:
                pass
            self._enabled = False
        return PracticeCycleResult(
            status, reason, sent, recorded, calibrated, remembered,
            input_release_confirmed=release_ok,
        )


__all__ = ["SignedPracticeVerdict", "PracticeCycleResult", "StudioPracticeCycle"]
