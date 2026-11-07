"""On-air, consent-scoped retrieval of verified STAR experiences and public facts.

Connects the existing StreamBrainGovernor (hardware-aware speech timing),
StreamEpisode (signed *practice* evidence) and KnowledgeStore (reviewed notes).
Unlike merely writing these packets to a document, this host actually forwards
them to a StarStage plan through the governed, live speech path.

The host performs no inference, recording, networking, playback, game input,
personal-data retention or publishing. It never reads hidden validation data.
An embedding local application must moderate audience text, provide trustworthy
clocks and explicitly curate public note IDs and game action IDs. These public
permissions cannot be granted by model-generated text or a viewer.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from threading import RLock, get_ident
from typing import Callable
import time

from .knowledge import KnowledgeStore
from .stream_brain_governor import StreamBrainGovernor
from .stream_episode import StreamEpisode
from .stream_knowledge import public_knowledge_packet
from .stream_stage import StagePlan
from .stream_turntaking import TurnAdvice

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class StreamContextHost:
    """A fail-conservative, owner-approved local streaming context adapter.

    SQLite connections belong to one host worker thread. The caller must
    marshal calls to prepare() onto the constructing thread. The two clocks
    have different purposes: UTC for knowledge age, and Unix seconds for
    signed practice freshness. The governor independently uses monotonic time.
    """

    def __init__(
        self, *, governor: StreamBrainGovernor, knowledge: KnowledgeStore,
        episode: StreamEpisode | None, project: str,
        public_note_ids: frozenset[int],
        public_action_ids: frozenset[str],
        utc_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        unix_clock: Callable[[], int] = lambda: int(time.time()),
    ) -> None:
        if not isinstance(governor, StreamBrainGovernor):
            raise TypeError("governor must be the existing StreamBrainGovernor")
        if not isinstance(knowledge, KnowledgeStore):
            raise TypeError("knowledge must be an existing KnowledgeStore")
        if episode is not None and not isinstance(episode, StreamEpisode):
            raise TypeError("episode must be StreamEpisode or None")
        if type(project) is not str or _ID.fullmatch(project) is None:
            raise ValueError("project must be a bounded project name")
        if (type(public_note_ids) is not frozenset or len(public_note_ids) > 128 or
                any(type(x) is not int or x <= 0 for x in public_note_ids)):
            raise ValueError("public notes must be curated numeric IDs")
        if (type(public_action_ids) is not frozenset or len(public_action_ids) > 32 or
                any(type(x) is not str or _ID.fullmatch(x) is None for x in public_action_ids)):
            raise ValueError("public actions must be curated short IDs")
        if not callable(utc_clock) or not callable(unix_clock):
            raise TypeError("trusted clocks are required")
        self._governor = governor
        self._knowledge = knowledge
        self._episode = episode
        self._project = project
        self._note_ids = public_note_ids
        self._action_ids = public_action_ids
        self._utc_clock = utc_clock
        self._unix_clock = unix_clock
        self._owner_thread = get_ident()
        self._lock = RLock()
        self._enabled = False
        self._counts = {
            "prepared": 0, "silence": 0, "knowledge_candidates": 0,
            "episode_candidates": 0, "retrieval_faults": 0,
        }

    def enable(self, *, owner_approved: bool = False,
               broadcast_approved: bool = False) -> None:
        """Two independent host consent decisions; no network/broadcast action."""
        if owner_approved is not True or broadcast_approved is not True:
            raise PermissionError("owner and on-air publication approvals required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before enabling a new context session")
            self._enabled = True

    def disable(self) -> None:
        """Stop context retrieval; the host separately stops the stream/voice."""
        with self._lock:
            self._enabled = False

    def prepare(
        self, *, moderated_question: str | None = None,
        voice_speaking: bool = False,
        viewer_speaking: bool = False,
        gameplay_critical: bool = False,
        turn: TurnAdvice | None = None,
    ) -> StagePlan | None:
        """Prepare a hardware-governed response with approved context only.

        The question must be supplied after upstream moderation and is used
        solely as a database lookup term. It is not placed in this packet.
        StarStage injects returned facts ONLY for viewer questions, and episode
        evidence ONLY for game/viewer intents. Inference jobs still require a
        separate governor speech lease and an actual audio device acknowledgement.
        """
        if moderated_question is not None and (
                type(moderated_question) is not str
                or not 1 <= len(moderated_question.strip()) <= 300):
            raise ValueError("moderated_question must contain 1..300 characters")
        if get_ident() != self._owner_thread:
            raise RuntimeError("marshal context retrieval to the SQLite owner thread")
        with self._lock:
            if not self._enabled or self._governor.status()["enabled"] is not True:
                self._counts["silence"] += 1
                return None
            if self._governor.status()["stage_phase"] != "idle":
                self._counts["silence"] += 1
                return None

            public_facts = None
            public_episode = None
            try:
                if moderated_question is not None and self._note_ids:
                    public_facts = public_knowledge_packet(
                        self._knowledge, project=self._project,
                        query=moderated_question,
                        public_note_ids=self._note_ids, now=self._utc_clock(),
                        limit=3,
                    )
                if self._episode is not None and self._action_ids:
                    public_episode = self._episode.public_packet(
                        now_unix_s=self._unix_clock(),
                        public_action_ids=self._action_ids,
                        broadcast_approved=True, limit=3,
                    )
            except Exception:
                # A broken note DB, UTC clock, or invalid episode state must
                # not degrade into invented context or a partial disclosure.
                self._counts["retrieval_faults"] += 1
                self._counts["silence"] += 1
                return None

            result = self._governor.prepare(
                voice_speaking=voice_speaking,
                viewer_speaking=viewer_speaking,
                gameplay_critical=gameplay_critical, turn=turn,
                knowledge=public_facts, episode=public_episode,
            )
            if result is None:
                self._counts["silence"] += 1
            else:
                self._counts["prepared"] += 1
                self._counts["knowledge_candidates"] += int(
                    public_facts is not None and result.kind == "viewer_question"
                )
                self._counts["episode_candidates"] += int(
                    public_episode is not None and result.kind in {
                        "viewer_question", "game_success", "game_observation"
                    }
                )
            return result

    def status(self) -> dict[str, int | bool]:
        """Anonymous counts, never actual viewer text or private fact content."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled}


__all__ = ["StreamContextHost"]
