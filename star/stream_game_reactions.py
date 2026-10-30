"""Host-scoped, evidence-grounded reactions for Star's gaming VTuber.

This planner deliberately cannot speak, stream, control a game, read a chat,
operate a device, or verify the truth of a host's game observations. The host
must first ingest an independently signed PRACTICE GameTrial into the skill
bank, arm StreamEpisode and StarStage with the owner's permission, and curate
non-private on-air action labels. Star only reacts to that specific signed
outcome; missing evidence becomes silence.

Live events are rate-limited and novelty-filtered. Each quiet attempt may
still contribute to the verified practice episode. Never use validation or
hidden holdout results as stream conversation or training hints.
"""
from __future__ import annotations

from typing import cast

from dataclasses import dataclass
from hashlib import sha256
import math
import re
from threading import RLock, get_ident
from typing import Mapping

from .gameplay_skill_bank import GameTrial
from .stream_director import StreamSignal
from .stream_episode import EpisodePacket, StreamEpisode
from .stream_stage import StarStage
from .stream_motion import MotionFrame

_ACTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_LABEL = re.compile(r"[A-Za-z][A-Za-z '’-]{0,47}\Z")
_MAX_CLOCK_S = 1e13


def _clock_s(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("monotonic time must be a finite positive number")
    try:
        number = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError("monotonic time unavailable") from exc
    if not math.isfinite(number) or not 0 <= number <= _MAX_CLOCK_S:
        raise ValueError("invalid monotonic time")
    return number


@dataclass(frozen=True)
class ReactionDecision:
    """No raw trial IDs, game evidence, signatures, or viewer content."""

    status: str
    practice_recorded: bool
    reaction_queued: bool
    episode: EpisodePacket | None = None


class VerifiedGameReactionHost:
    """Compose existing signed practice episodes with a bounded StarStage.

    Caller supplies two trusted host clocks: real Unix seconds for verifying
    the bank, and monotonic seconds for Stage scheduling and rate limits. The
    two clocks cannot be inferred from each other. The code neither captures
    frames nor certifies whether gameplay happened, and cannot grant input or
    broadcasting permission.

    shutdown() stops this WHOLE stream stage (not just gameplay reactions),
    so queued plans are invalidated. The host must independently stop/mute
    physical audio and neutralize its avatar; Python cannot do either.
    """

    def __init__(
        self,
        episode: StreamEpisode,
        stage: StarStage,
        *,
        curated_labels: Mapping[str, str],
        min_gap_s: float = 12.0,
        max_event_age_s: int = 4,
    ) -> None:
        if not isinstance(episode, StreamEpisode) or not isinstance(stage, StarStage):
            raise TypeError("expected verified episode and stream stage")
        if not isinstance(curated_labels, Mapping) or not 1 <= len(curated_labels) <= 32:
            raise ValueError("curated_labels must have 1..32 host-curated entries")
        labels: dict[str, str] = {}
        for action, label in curated_labels.items():
            if type(action) is not str or not _ACTION.fullmatch(action):
                raise ValueError("invalid curated action ID")
            if type(label) is not str or not _LABEL.fullmatch(label):
                raise ValueError("public labels must be short plain-language phrases")
            labels[action] = label
        gap = _clock_s(min_gap_s)
        if not 2 <= gap <= 120:
            raise ValueError("min_gap_s must be 2..120")
        if type(max_event_age_s) is not int or not 1 <= max_event_age_s <= 7:
            raise ValueError("max_event_age_s must be 1..7")
        self._episode = episode
        self._stage = stage
        self._labels = labels
        self._gap = gap
        self._fresh_s = max_event_age_s
        self._lock = RLock()
        # GameplaySkillBank's sqlite3 connection is owner-thread bound.
        # A trusted host must marshal trial handling onto that same worker.
        self._owner_thread = get_ident()
        self._enabled = False
        self._last_clock: float | None = None
        self._last_offered = float("-inf")
        self._successes_announced: set[str] = set()
        # One grounded relief moment per action/episode, not endless cheers.
        self._comebacks_announced: set[str] = set()
        self._failures_announced: set[str] = set()
        # Keep consecutive failures within a one-minute gameplay window.
        self._failure_streaks: dict[str, tuple[int, float]] = {}
        self._counts = dict(verified=0, offered=0, rejected=0, quiet=0,
                            private=0, stale=0, stage_busy=0)

    def enable(self, *, owner_approved: bool = False,
               broadcast_approved: bool = False) -> None:
        """This never starts a stream or automatically enables the stage."""
        if owner_approved is not True or broadcast_approved is not True:
            raise PermissionError("owner AND separate broadcast approval required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("shutdown required before restarting reactions")
            if self._episode.metrics()["enabled"] is not True:
                raise RuntimeError("start signed episode first")
            self._successes_announced.clear()
            self._comebacks_announced.clear()
            self._failures_announced.clear()
            self._failure_streaks.clear()
            self._last_clock = None
            self._last_offered = float("-inf")
            self._counts = dict.fromkeys(self._counts, 0)
            self._enabled = True

    def observe(self, trial: GameTrial, *, now_unix_s: int,
                now_monotonic_s: float) -> ReactionDecision:
        """Store a signed practice fact, optionally queue ONE grounded cue.

        A successful action is never represented as winning a whole game.
        Three independently recorded failures can prompt a single reflective
        observation, without spamming chat with every failed action.
        """
        if not isinstance(trial, GameTrial):
            raise TypeError("expected an existing GameTrial")
        if get_ident() != self._owner_thread:
            raise RuntimeError("marshal signed trials to the skill-bank owner thread")
        now = _clock_s(now_monotonic_s)
        if type(now_unix_s) is not int or not 0 < now_unix_s <= 10**11:
            raise ValueError("now_unix_s must be trusted Unix seconds")
        with self._lock:
            if self._last_clock is not None and now < self._last_clock:
                raise ValueError("monotonic clock moved backwards")
            self._last_clock = now
            if not self._enabled:
                return ReactionDecision("disabled", False, False)
            # Episode checks the EXACT bank signature, practice split, scopes,
            # original timestamp, and one-time trial ID. A matching action/run
            # reservation alone is never a trusted outcome.
            if not self._episode.append(trial, now_unix_s=now_unix_s):
                self._counts["rejected"] += 1
                return ReactionDecision("unverified", False, False)
            self._counts["verified"] += 1
            if trial.action_id not in self._labels:
                self._counts["private"] += 1
                return ReactionDecision("private", True, False)
            # A late observation may be useful to learning but is not a
            # real-time reaction. Never celebrate a buffered old success.
            age = now_unix_s - trial.observed_unix_s
            if age < 0 or age > self._fresh_s:
                self._counts["stale"] += 1
                return ReactionDecision("stale", True, False)
            action = trial.action_id
            kind: str
            recovered = False
            if trial.outcome == "success":
                failed_count, last_failure = self._failure_streaks.pop(
                    action, (0, float("-inf"))
                )
                # A new success after three *fresh signed failures* is a
                # distinct, genuinely narratable comeback. Keep only one per
                # game episode; no imaginary wins or endless repetition.
                recovered = (
                    failed_count >= 3 and 0 <= now - last_failure <= 60
                    and action not in self._comebacks_announced
                )
                if action in self._successes_announced and not recovered:
                    self._counts["quiet"] += 1
                    return ReactionDecision("already_reacted", True, False)
                kind = "game_success"
            else:
                count, last = self._failure_streaks.get(action, (0, float("-inf")))
                count = min(3, count + 1) if now - last <= 60 else 1
                self._failure_streaks[action] = (count, now)
                if count < 3 or action in self._failures_announced:
                    self._counts["quiet"] += 1
                    return ReactionDecision("deliberate_silence", True, False)
                kind = "game_observation"
            if now - self._last_offered < self._gap:
                self._counts["quiet"] += 1
                return ReactionDecision("cooldown", True, False)
            # The public_packet decision is a second, independent publication
            # boundary, so signed events are never automatically public.
            packet = self._episode.public_packet(
                now_unix_s=now_unix_s,
                public_action_ids=frozenset({action}),
                broadcast_approved=True,
                limit=1,
            )
            if packet is None or action not in packet.action_ids:
                self._counts["private"] += 1
                return ReactionDecision("not_publishable", True, False)
            label = self._labels[action]
            if kind == "game_success":
                if recovered:
                    detail = (
                        f"Host-verified practice: three recent attempts at {label} "
                        "failed, then this one action succeeded. A brief, natural "
                        "relieved reaction fits; do not claim the level was completed "
                        "or the skill mastered."
                    )
                else:
                    detail = (
                        f"Host-verified practice attempt for {label}: this one action "
                        "succeeded. Do not claim the game was won or the skill mastered."
                    )
            else:
                detail = (f"Host-verified practice: three recent attempts at {label} "
                          "failed. Briefly consider a different approach; do not invent why.")
            signal_id = "verified." + sha256(
                (trial.trial_id + "\0" + trial.evidence_sha256).encode("ascii")
            ).hexdigest()[:40]
            signal = StreamSignal(signal_id, kind, now, detail, evidence="observed")
            if not self._stage.offer(signal, now=now):
                self._counts["stage_busy"] += 1
                return ReactionDecision("stage_unavailable", True, False)
            self._last_offered = now
            if kind == "game_success":
                self._successes_announced.add(action)
                if recovered:
                    self._comebacks_announced.add(action)
            else:
                self._failures_announced.add(action)
            self._counts["offered"] += 1
            return ReactionDecision("queued_for_review", True, True, packet)

    def shutdown(self) -> MotionFrame:
        """Revoke ALL stage plans, erase session context, return neutral rig cue.

        The trusted host must still physically mute audio and neutralize the
        avatar. Restarting requires fresh explicit approvals and new sessions.
        """
        with self._lock:
            self._enabled = False
            self._successes_announced.clear()
            self._comebacks_announced.clear()
            self._failures_announced.clear()
            self._failure_streaks.clear()
            self._last_clock = None
            self._last_offered = float("-inf")
            self._episode.disable()
            return self._stage.disable()

    def metrics(self) -> dict[str, int | bool]:
        """No trial IDs, labels, media, player IDs, or transcripts."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled}


__all__ = ["ReactionDecision", "VerifiedGameReactionHost"]
