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

from dataclasses import dataclass
from threading import RLock
from typing import Awaitable, Callable

from .game_learning_ladder import LadderAdvice
from .game_portfolio_practice import GamePortfolioPractice, PortfolioAdvice
from .gameplay_skill_bank import GameTrial
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


class PortfolioStudioBridge:
    """One reservation -> one authorized Studio input -> signed feedback.

    Construct a NEW StudioPracticeRunner for every new portfolio run, with the
    host-issued GameScope. Neither an untrusted proposal nor this adapter can
    start Studio, enable the runner, sign a result, or reach validation cases.
    """

    def __init__(
        self, portfolio: GamePortfolioPractice, offer: PortfolioAdvice,
        runner: StudioPracticeRunner, *, now_unix_s: int,
    ) -> None:
        if not isinstance(portfolio, GamePortfolioPractice):
            raise TypeError("expected GamePortfolioPractice")
        if not isinstance(offer, PortfolioAdvice):
            raise TypeError("expected PortfolioAdvice")
        if not isinstance(runner, StudioPracticeRunner):
            raise TypeError("expected StudioPracticeRunner")
        if offer.status != "practice_candidate" or offer.authorized_to_play is not False:
            raise ValueError("only a scheduler-issued practice offer is accepted")
        if not portfolio.matches_reservation(offer, now_unix_s=now_unix_s):
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
        self._lock = RLock()
        self._finished = False
        self._counts = dict(actions=0, blocked=0, signed=0, rejected=0)

    def _active(self, now_unix_s: int) -> bool:
        with self._lock:
            return not self._finished and self._portfolio.matches_reservation(
                self._offer, now_unix_s=now_unix_s,
            )

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
            # Model text may suggest hold_ms but NEVER alter the verified scope.
            return await proposer(evidence, advice)

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
        return await self._runner.observe_after()

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
                    trial, receipt, now_unix_s=now_unix_s,
                )
            except (TypeError, ValueError, PermissionError, OverflowError):
                self._counts["rejected"] += 1
                self._runner.discard_unverified()
                self._portfolio.finish(
                    self._offer.ticket, now_unix_s=now_unix_s,
                    host_reports_recorded=False,
                )
                self._finished = True
                raise
            verified = self._portfolio.finish(
                self._offer.ticket, now_unix_s=now_unix_s,
                host_reports_recorded=recorded.accepted,
            )
            self._finished = True
            if verified:
                self._counts["signed"] += 1
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
            try:
                self._portfolio.finish(
                    self._offer.ticket, now_unix_s=now_unix_s,
                    host_reports_recorded=False,
                )
            except ValueError:
                pass  # already expired/revoked; never credit a practice result
            return True

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {**self._counts, "finished": self._finished}


__all__ = ["PortfolioStudioBridge", "PortfolioStudioResult"]
