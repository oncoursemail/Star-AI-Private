"""Evidence-preserving seam between STAR's gameplay evaluation and VTuber cues.

This is an offline coordinator, NOT a game controller, TTS engine, model trainer
or authentication mechanism. An authorized independent host must score every
episode; a SHA-256 checksum alone proves neither truth nor origin. Do not expose
this object directly to model-produced tool arguments or untrusted chat.
"""
from __future__ import annotations

from dataclasses import dataclass

from .game_skill_memory import Advice, Episode, GameSkillMemory
from .stream_moment_memory import CueOffer, GameMoment, StreamMomentMemory


@dataclass(frozen=True)
class IngestReceipt:
    """A valid skill outcome can be retained even if optional narration fills up."""
    skill_recorded: bool
    moment_queued: bool
    moment_status: str


class GameStreamBridge:
    """Pure in-memory, host-called bridge; no network, OS access or game inputs."""

    def __init__(self, *, skills: GameSkillMemory | None = None,
                 moments: StreamMomentMemory | None = None) -> None:
        self.skills = skills if skills is not None else GameSkillMemory()
        self.moments = moments if moments is not None else StreamMomentMemory()
        if not isinstance(self.skills, GameSkillMemory) or not isinstance(self.moments, StreamMomentMemory):
            raise TypeError("Expected validated skill and moment ledgers")
        self._story_drops = 0

    @staticmethod
    def _check_consistency(episode: Episode, moment: GameMoment) -> None:
        if (episode.session != moment.session or episode.seq != moment.seq
                or episode.state != moment.topic
                or episode.evidence_sha256 != moment.evidence_sha256):
            raise ValueError("Narration must reference this exact scored session/step/state/evidence")
        if moment.kind in ("victory", "recovery") and (not episode.success or episode.unsafe):
            raise ValueError("A win or recovery requires an observed safe success")
        if moment.kind == "failure" and episode.success:
            raise ValueError("A failure cue requires an observed failed attempt")
        if episode.unsafe and moment.kind != "failure":
            raise ValueError("Unsafe actions may only produce a failure cue")

    def ingest(self, episode: Episode, moment: GameMoment | None = None, *,
               independently_verified_by_host: bool = False) -> IngestReceipt:
        """Record trusted outcome first; then queue optional correlated story evidence.

        Once a skill record succeeds, an optional moment can still be rejected,
        e.g. if its ledger is full. The returned receipt exposes partial success
        so the caller never retries the same scored episode to fix a cue.
        This method should be serialized by the owner-controlled host.
        """
        if independently_verified_by_host is not True:
            raise PermissionError("Independent trusted host verification required")
        if type(episode) is not Episode:
            raise TypeError("Validated Episode required")
        if moment is not None:
            if type(moment) is not GameMoment:
                raise TypeError("Validated GameMoment required")
            self._check_consistency(episode, moment)

        self.skills.record(episode, trusted_host=True)
        if moment is None:
            return IngestReceipt(True, False, "not_requested")
        try:
            self.moments.observe(moment, trusted_game_adapter=True)
        except (ValueError, OverflowError):
            # Skill ledger is valid and must not be retried to fabricate more
            # independent trials. An optional stream cue must fail independently.
            self._story_drops += 1
            return IngestReceipt(True, False, "moment_rejected")
        return IngestReceipt(True, True, "queued")

    def recommend(self, game: str, state: str, allowlisted_actions: tuple[str, ...], *,
                  mode: str = "play", sandbox_approved: bool = False,
                  min_trials: int = 16, minimum_lower: float = 0.5) -> Advice:
        """Advisory policy only: a game host still owns action permission."""
        return self.skills.advise(game, state, allowlisted_actions, mode=mode,
                                  sandbox_approved=sandbox_approved,
                                  min_trials=min_trials, minimum_lower=minimum_lower)

    def offer_commentary(self, session: str, now_ms: int, *,
                         audience_can_hear: bool = False) -> CueOffer | None:
        """Reserve evidence-linked commentary; NO speech is generated or played."""
        return self.moments.propose_cue(
            session, now_ms, audience_can_hear=audience_can_hear)

    def finish_commentary(self, session: str, ticket: int, *, audible: bool,
                          now_ms: int) -> bool:
        """Only the authoritative speaker may mark audio as audible."""
        return self.moments.complete_cue(session, ticket, delivered=audible, now_ms=now_ms)

    def interrupt(self, session: str) -> bool:
        """Barge-in invalidates unplayed narrative; playback adapter must stop too."""
        return self.moments.cancel_pending(session)

    def summary(self) -> dict[str, int]:
        """No game screenshots, chat, prompts, names or TTS content are logged."""
        a, b = self.skills.summary(), self.moments.summary()
        return {
            "game_sessions": a["sessions"],
            "scored_episodes": a["episodes"],
            "state_actions": a["state_actions"],
            "stream_sessions": b["sessions"],
            "observed_moments": b["moments"],
            "completed_event_references": b["cues"],
            "dropped_optional_moments": self._story_drops,
        }
