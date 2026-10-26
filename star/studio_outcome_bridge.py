"""Bind ACTUALLY delivered private-Studio input to independent gameplay evidence.

A model may suggest actions, but it cannot create delivered input proofs, score
objectives, or sign results. The trusted host calls record() with a fresh,
host-verified post-action frame and a separately evaluated, signed PRACTICE
GameTrial. The evaluator's signing key must stay outside Star/model/chat.

Important trust boundaries:
* StudioPlaytestHost.claim_delivery requires the exact in-process dispatch report.
* A signed trial attests the declared evaluator output, not objective truth.
  The independent scorer must actually inspect the game/logs before signing.
* A successful key pulse is NEVER itself proof of successful gameplay.
* Does not perform network, game control, recording, broadcasts, or training.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from threading import RLock

from .game_action_gate import GameFrame
from .gameplay_skill_bank import GameTrial, GameplaySkillBank
from .studio_playtest_host import DeliveredAction, DispatchReport, StudioPlaytestHost
from .stream_episode import StreamEpisode

_DOMAIN = b"star.studio.verified-transition.v1\x00"
_MAX_MONOTONIC_MS = 1e13


def _ms(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label}: finite monotonic milliseconds required")
    num = float(value)
    if not math.isfinite(num) or not 0 <= num <= _MAX_MONOTONIC_MS:
        raise ValueError(f"{label}: finite monotonic milliseconds required")
    return num


def transition_digest(
    delivery: DeliveredAction, after: GameFrame, *, trial: GameTrial,
) -> str:
    """Deterministically bind the evaluator's verdict to ONE full transition.

    Host may calculate this before the independent evaluator signs the trial.
    The digest deliberately excludes any private frames, audio or player IDs.
    """
    if not isinstance(delivery, DeliveredAction) or not isinstance(after, GameFrame):
        raise TypeError("expected trusted input delivery and post-action observation")
    if not isinstance(trial, GameTrial):
        raise TypeError("expected GameTrial")
    payload = {
        "studio_id": delivery.studio_id,
        "game_id": delivery.scope.game_id,
        "version_id": delivery.scope.version_id,
        "episode_id": delivery.scope.episode_id,
        "action_id": delivery.action_id,
        "ticket": delivery.ticket,
        "before_sequence": delivery.frame_sequence,
        "before_digest": delivery.before_sha256,
        "before_ms": delivery.before_ms,
        "released_ms": delivery.released_ms,
        "after_sequence": after.sequence,
        "after_digest": after.evidence_sha256,
        "after_ms": after.captured_ms,
        "trial_id": trial.trial_id,
        "objective_id": trial.objective_id,
        "situation_id": trial.situation_id,
        "outcome": trial.outcome,
        "observed_unix_s": trial.observed_unix_s,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(_DOMAIN + canonical).hexdigest()


@dataclass(frozen=True)
class OutcomeRecord:
    accepted: bool
    episode_memory_updated: bool
    # An accepted PRACTICE result is not independent holdout mastery evidence.
    mastery_proven: bool = False


class StudioOutcomeBridge:
    """One-way private-host action -> independent trial -> skill-bank bridge.

    The host must call record() promptly, before another successful dispatch
    overwrites the one-slot delivery token. Failed reports are not recordable.
    Invalid or rejected evidence consumes its delivery token (fail closed).
    Reuse of a valid signed trial or run remains blocked by the skill bank.
    """

    def __init__(self, bank: GameplaySkillBank, *,
                 episode: StreamEpisode | None = None,
                 max_feedback_delay_ms: int = 12000) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("bank must be GameplaySkillBank")
        if episode is not None and not isinstance(episode, StreamEpisode):
            raise TypeError("episode must be StreamEpisode or None")
        if (type(max_feedback_delay_ms) is not int
                or not 200 <= max_feedback_delay_ms <= 30000):
            raise ValueError("feedback delay bound must be 200..30000 ms")
        self._bank = bank
        self._episode = episode
        self._max_feedback = max_feedback_delay_ms
        self._lock = RLock()
        self._accepted = 0
        self._rejected = 0
        self._continuity_updates = 0

    def record(
        self, *, host: StudioPlaytestHost, dispatch: DispatchReport,
        after: GameFrame, trial: GameTrial, host_verified_after: bool,
        signed_practice_receipt: str, now_ms: float, now_unix_s: int,
    ) -> OutcomeRecord:
        """Record one independently signed practice verdict, not model self-grading.

        The host provides observations under its OWN monotonic clock and the
        practice signer must be independently trusted. Nothing in this adapter
        signs outcomes or invents successful trials.
        """
        if not isinstance(host, StudioPlaytestHost):
            raise TypeError("host must be StudioPlaytestHost")
        if not isinstance(dispatch, DispatchReport):
            raise TypeError("dispatch must be DispatchReport")
        with self._lock:
            delivery = host.claim_delivery(dispatch)
            if delivery is None:
                self._rejected += 1
                raise PermissionError("no matching host-delivered action to score")
            try:
                if not isinstance(after, GameFrame) or not isinstance(trial, GameTrial):
                    raise TypeError("expected GameFrame and GameTrial")
                if host_verified_after is not True:
                    raise PermissionError("independent post-action observation required")
                now = _ms(now_ms, "now_ms")
                if (after.scope != delivery.scope
                        or after.sequence <= delivery.frame_sequence
                        or not after.focus_confirmed
                        or after.perception_confidence < 0.75):
                    raise ValueError("post observation is not a valid next game frame")
                if (after.captured_ms < delivery.released_ms
                        or after.captured_ms > now + 15
                        or now - after.captured_ms > 1000
                        or now - delivery.released_ms > self._max_feedback):
                    raise ValueError("post-action evidence expired or predates input")
                if (trial.split != "practice"
                        or trial.game_id != delivery.scope.game_id
                        or trial.game_version != delivery.scope.version_id
                        or trial.run_id != delivery.scope.episode_id
                        or trial.action_id != delivery.action_id):
                    raise ValueError("signed trial not scoped to delivered action")
                if (type(now_unix_s) is not int
                        or now_unix_s < trial.observed_unix_s
                        or now_unix_s - trial.observed_unix_s > 30):
                    raise ValueError("independent evaluator's verdict is stale")
                if transition_digest(delivery, after, trial=trial) != trial.evidence_sha256:
                    raise ValueError("trial evidence digest is not bound to transition")
                # The separate GameplaySkillBank validates the independent
                # signing key/receipt and atomic run deduplication.
                self._bank.ingest(trial, signed_practice_receipt,
                                  now_unix_s=now_unix_s)
            except (TypeError, ValueError, PermissionError, OverflowError):
                self._rejected += 1
                raise
            self._accepted += 1
            remembered = False
            if self._episode is not None:
                # An episode holds only already-ingested exact signed PRACTICE
                # evidence; separate broadcast approval is STILL required.
                remembered = self._episode.append(trial, now_unix_s=now_unix_s)
            if remembered:
                self._continuity_updates += 1
            return OutcomeRecord(True, remembered)

    def metrics(self) -> dict[str, int]:
        """Aggregate counts only; no keys, player IDs, screenshots or receipts."""
        with self._lock:
            return {"accepted": self._accepted, "rejected": self._rejected,
                    "episode_updates": self._continuity_updates}


__all__ = ["StudioOutcomeBridge", "OutcomeRecord", "transition_digest"]
