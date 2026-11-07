"""Bind fair cross-game curriculum reservations to a REAL private Studio episode.

No new input permission is created here. A trusted host must arm the visual
observer, start the private playtest input host, enable the ladder, enable the
runner, provide physical key-release watchdog, and obtain an independent
signed post-action GameTrial. The model only proposes a symbolic action.

The scheduler's reservation run ID MUST equal the Studio game episode ID.
This connection was previously left to callers and could silently result in
practice evidence for the wrong game/episode, or an arbitrary ladder action.
This adapter closes that handoff and confirms it again at input dispatch.
"""
from __future__ import annotations

from typing import cast

from dataclasses import dataclass
import re
import sqlite3
from threading import RLock
import time
from typing import Awaitable, Callable

from .game_learning_ladder import LadderAdvice
from .game_portfolio_practice import GamePortfolioPractice, PortfolioAdvice
from .gameplay_skill_bank import GameTrial
from .game_prediction_lab import GameForecast, GamePredictionLab
from .studio_practice_runner import (
    PracticeProposal, PracticeStep, StudioPracticeRunner,
)
from .studio_visual_evidence import VisualEvidence


@dataclass(frozen=True)
class PortfolioStudioResult:
    signed_evidence_recorded: bool
    portfolio_verified: bool
    episode_memory_updated: bool
    reason: str


def _unix_clock() -> int:
    """Read the trusted host wall-clock. Unit tests inject a deterministic clock."""
    return int(time.time())


class PortfolioStudioBridge:
    """One reservation -> one authorized Studio input -> signed feedback.

    Construct a NEW StudioPracticeRunner for every new portfolio run, with the
    host-issued GameScope. Neither an untrusted proposal nor this adapter can
    start Studio, enable the runner, sign a result, or reach validation cases.
    """

    def __init__(
        self, portfolio: GamePortfolioPractice, offer: PortfolioAdvice,
        runner: StudioPracticeRunner, *, now_unix_s: int,
        clock_unix_s: Callable[[], int] = _unix_clock,
        prediction_lab: GamePredictionLab | None = None,
        forecast_model_id: str | None = None,
    ) -> None:
        if not isinstance(portfolio, GamePortfolioPractice):
            raise TypeError("expected GamePortfolioPractice")
        if not isinstance(offer, PortfolioAdvice):
            raise TypeError("expected PortfolioAdvice")
        if not isinstance(runner, StudioPracticeRunner):
            raise TypeError("expected StudioPracticeRunner")
        if offer.status != "practice_candidate" or offer.authorized_to_play is not False:
            raise ValueError("only a scheduler-issued practice offer is accepted")
        if not callable(clock_unix_s):
            raise ValueError("a trusted live Unix clock is required")
        if prediction_lab is not None:
            if (not isinstance(prediction_lab, GamePredictionLab)
                    or prediction_lab._bank is not runner._outcomes._bank):
                raise ValueError("forecast lab must share the signed game evidence bank")
            if (type(forecast_model_id) is not str or
                    re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", forecast_model_id) is None):
                raise ValueError("trusted host must supply a bounded model version ID")
        elif forecast_model_id is not None:
            raise ValueError("model version without forecast lab")
        # The caller's timestamp is NOT a trusted dispatch clock. A previously
        # checked, perfectly valid offer could expire during model inference.
        self._clock_unix_s = clock_unix_s
        live_now = self._trusted_now(now_unix_s)
        if not portfolio.matches_reservation(offer, now_unix_s=live_now):
            raise PermissionError("practice reservation missing, revoked or expired")
        scope = runner._scope
        ladder = runner._ladder
        if (scope.game_id != offer.game_id
                or scope.version_id != offer.game_version
                or scope.episode_id != offer.expected_run_id
                or ladder.game_id != offer.game_id
                or ladder.game_version != offer.game_version
                or ladder.objective_id != offer.objective_id
                or not any(item is ladder for item in portfolio._ladders)):
            raise ValueError("Studio episode, curriculum and reservation differ")
        if (runner._outcomes._bank is not portfolio._planner._bank):
            raise ValueError("Studio outcome ledger differs from reservation ledger")
        self._portfolio = portfolio
        self._offer = offer
        self._runner = runner
        self._prediction_lab = prediction_lab
        self._forecast_model_id = forecast_model_id
        self._lock = RLock()
        self._finished = False
        self._counts = dict(actions=0, blocked=0, signed=0, rejected=0,
                            clock_rejections=0, forecast_committed=0,
                            forecast_rejected=0, forecast_verified=0)

    def _trusted_now(self, hint_unix_s: int) -> int:
        """Require a recent host clock read, not an old caller-supplied time.

        The ±1 second boundary tolerance accounts for Unix-second rollover
        between the embedding host and this call. It never extends the
        portfolio's own reservation expiry. Bad clocks fail closed.
        """
        if type(hint_unix_s) is not int or not 0 < hint_unix_s <= 10**11:
            raise ValueError("invalid time hint")
        try:
            now = self._clock_unix_s()
        except Exception:
            raise ValueError("trusted live clock unavailable") from None
        if type(now) is not int or not 0 < now <= 10**11:
            raise ValueError("trusted live clock invalid")
        if abs(now - hint_unix_s) > 1:
            raise ValueError("caller time is stale or in the future")
        return now

    def _active(self, now_unix_s: int) -> bool:
        with self._lock:
            if self._finished:
                return False
            try:
                live_now = self._trusted_now(now_unix_s)
                return self._portfolio.matches_reservation(
                    self._offer, now_unix_s=live_now,
                )
            except (TypeError, ValueError):
                self._counts["clock_rejections"] += 1
                return False

    async def take_step(
        self,
        proposer: Callable[
            [VisualEvidence, LadderAdvice], Awaitable[PracticeProposal],
        ],
        *, now_unix_s: int,
    ) -> PracticeStep:
        """At most one bounded input. NO general keypresses or online games."""
        if not callable(proposer):
            raise TypeError("model proposer must be callable")
        if not self._active(now_unix_s):
            self._counts["blocked"] += 1
            return PracticeStep("deferred", "portfolio_reservation_missing")

        async def reserved_proposer(
            evidence: VisualEvidence, advice: LadderAdvice,
        ) -> PracticeProposal:
            if (advice.status != "practice_candidate"
                    or advice.action_id != self._offer.action_id
                    or advice.situation_id != self._offer.situation_id
                    or advice.difficulty != self._offer.difficulty):
                raise PermissionError("current curriculum differs from reserved action")
            # Model text may suggest hold_ms and confidence; neither can
            # alter the verified scope, reserved action or input permissions.
            proposal = await proposer(evidence, advice)
            if (isinstance(proposal, PracticeProposal)
                    and self._prediction_lab is not None
                    and proposal.success_probability_bps is not None):
                # The exact estimate is immutable BEFORE the input dispatch;
                # a later game result cannot retroactively change confidence.
                try:
                    stamp = self._clock_unix_s()
                    forecast = GameForecast(
                        cast(str, self._offer.game_id), cast(str, self._offer.game_version),
                        cast(str, self._offer.objective_id), cast(str, self._offer.situation_id),
                        cast(str, self._offer.action_id), cast(str, self._offer.expected_run_id),
                        cast(str, self._forecast_model_id), proposal.success_probability_bps,
                        stamp,
                    )
                    if self._prediction_lab.precommit(forecast, now_unix_s=stamp):
                        self._counts["forecast_committed"] += 1
                    else:
                        self._counts["forecast_rejected"] += 1
                except (TypeError, ValueError, OverflowError, sqlite3.Error):
                    self._counts["forecast_rejected"] += 1
            return proposal

        result = await self._runner.take_step(
            reserved_proposer, now_unix_s=now_unix_s,
            dispatch_guard=lambda: self._active(now_unix_s),
        )
        self._counts["actions" if result.action_sent else "blocked"] += 1
        return result

    async def observe_after(self, *, now_unix_s: int) -> PracticeStep:
        """Forward physical post-input observation, NOT success evaluation."""
        if not self._active(now_unix_s):
            self._counts["blocked"] += 1
            return PracticeStep("deferred", "portfolio_reservation_missing")
        result = await self._runner.observe_after()
        # Observing can itself block on screen capture or visual inference.
        # Never expose a formerly valid episode for external scoring.
        if not self._active(now_unix_s):
            self._counts["blocked"] += 1
            return PracticeStep("deferred", "portfolio_reservation_missing")
        return result

    def evidence_for_evaluator(self, *, now_unix_s: int):
        """Trusted host ONLY; never put image, receipts or proof in model chat."""
        if not self._active(now_unix_s):
            return None
        return self._runner.evidence_for_evaluator()

    def record_signed_outcome(
        self, trial: GameTrial, receipt: str, *, now_unix_s: int,
    ) -> PortfolioStudioResult:
        """Consume a real independently signed practice transition.

        The outcome may be a FAILURE: failure evidence is useful for training
        and is not to be inflated into a success or holdout mastery claim.
        """
        if not isinstance(trial, GameTrial):
            raise TypeError("independently scored GameTrial required")
        with self._lock:
            if not self._active(now_unix_s):
                return PortfolioStudioResult(False, False, False,
                                             "reservation_expired_or_revoked")
            live_now = self._trusted_now(now_unix_s)
            if (trial.split != "practice"
                    or trial.game_id != self._offer.game_id
                    or trial.game_version != self._offer.game_version
                    or trial.objective_id != self._offer.objective_id
                    or trial.situation_id != self._offer.situation_id
                    or trial.action_id != self._offer.action_id
                    or trial.run_id != self._offer.expected_run_id):
                self._counts["rejected"] += 1
                raise ValueError("signed verdict does not match portfolio reservation")
            # The runner/bridge verifies REAL delivery and image transition,
            # digest, timestamp, independent signature, and single-use run ID.
            try:
                recorded = self._runner.record_signed_outcome(
                    trial, receipt, now_unix_s=live_now,
                )
            except (TypeError, ValueError, PermissionError, OverflowError):
                self._counts["rejected"] += 1
                self._runner.discard_unverified()
                self._portfolio.finish(
                    cast(int, self._offer.ticket), now_unix_s=now_unix_s,
                    host_reports_recorded=False,
                )
                self._finished = True
                raise
            verified = self._portfolio.finish(
                cast(int, self._offer.ticket), now_unix_s=live_now,
                host_reports_recorded=recorded.accepted,
            )
            self._finished = True
            if verified:
                self._counts["signed"] += 1
                if self._prediction_lab is not None:
                    # Non-authoritative analytics: a forecasting failure never
                    # changes the independently verified gameplay verdict.
                    try:
                        if self._prediction_lab.resolve(trial, now_unix_s=live_now):
                            self._counts["forecast_verified"] += 1
                        else:
                            self._counts["forecast_rejected"] += 1
                    except (TypeError, ValueError, OverflowError, sqlite3.Error):
                        self._counts["forecast_rejected"] += 1
            return PortfolioStudioResult(
                recorded.accepted, verified, recorded.episode_memory_updated,
                "signed_practice_accepted" if verified
                else "portfolio_receipt_not_verified",
            )

    def abandon(self, *, now_unix_s: int) -> bool:
        """Release an unverified slot; host must also stop/reset Studio input."""
        with self._lock:
            if self._finished:
                return False
            self._finished = True
            self._runner.discard_unverified()
            if self._prediction_lab is not None:
                try:
                    self._prediction_lab.cancel(cast(str, self._offer.expected_run_id))
                except (TypeError, ValueError, sqlite3.Error):
                    self._counts["forecast_rejected"] += 1
            try:
                self._portfolio.finish(
                    cast(int, self._offer.ticket), now_unix_s=now_unix_s,
                    host_reports_recorded=False,
                )
            except ValueError:
                pass  # already expired/revoked; never credit a practice result
            return True

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {**self._counts, "finished": self._finished}


__all__ = ["PortfolioStudioBridge", "PortfolioStudioResult"]
