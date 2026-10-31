"""Private-by-default, ephemeral game-moment journal for Star's streaming persona.

Only an owner-authorized host may submit a *structured* observation from actual
permitted gameplay. The journal does not ingest chat, transcripts, video, memory
from the model, arbitrary text, or supposed emotions. A returned recap is a
bounded factual *suggestion*, never a command to speak or evidence of OBS audio.
Host attestation is not a cryptographic proof that the gameplay really happened.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import re
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_KINDS = frozenset({
    "checkpoint", "win", "loss", "close_call", "puzzle_solved",
    "mechanic_discovered", "practice_improved",
})
_CAPTIONS = {
    "checkpoint": "reached a checkpoint",
    "win": "won a round",
    "loss": "lost a round",
    "close_call": "had a close call",
    "puzzle_solved": "solved a puzzle",
    "mechanic_discovered": "discovered a game mechanic",
    "practice_improved": "improved during practice",
}


def _time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("timestamp must be finite and nonnegative")
    try:
        converted = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("timestamp must be finite and nonnegative") from exc
    if not math.isfinite(converted) or converted < 0:
        raise ValueError("timestamp must be finite and nonnegative")
    return converted


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded canonical identifier")
    return value


@dataclass(frozen=True)
class GameMoment:
    """Host-extracted game-state fact; no player IDs or arbitrary prose."""

    moment_id: str
    game_scope: str
    kind: str
    at_s: float
    stage_id: str = ""

    def __post_init__(self) -> None:
        _identifier(self.moment_id, "moment_id")
        _identifier(self.game_scope, "game_scope")
        if self.stage_id:
            _identifier(self.stage_id, "stage_id")
        elif type(self.stage_id) is not str:
            raise ValueError("stage_id must be a canonical identifier or empty")
        if type(self.kind) is not str or self.kind not in _KINDS:
            raise ValueError("unsupported structured game moment")
        _time(self.at_s)


@dataclass(frozen=True)
class EpisodeRecall:
    """Prompt DATA, not an instruction or a verified historical biography."""

    context: str
    age_seconds: int
    game_scope: str
    provenance: str = "host_attested_game_state"
    authorized_to_speak: bool = False


class StreamEpisodeJournal:
    """Bounded, session-only memory for genuine host-attested game experiences.

    The default is OFF. Memory disappears on disable. No disk/network writes,
    model calls, untrusted viewer messages, private identifiers or chat logs.
    The host must keep the observed flag tied to a trusted game-state reader.
    """

    def __init__(self, *, capacity: int = 48, max_age_s: float = 3600.0,
                 observation_lag_s: float = 30.0) -> None:
        if type(capacity) is not int or not 1 <= capacity <= 128:
            raise ValueError("capacity must be 1..128")
        self._max_age = _time(max_age_s)
        self._max_lag = _time(observation_lag_s)
        if not 60 <= self._max_age <= 28800 or not 0 <= self._max_lag <= 120:
            raise ValueError("invalid expiration or observation lag")
        self._capacity = capacity
        self._lock = RLock()
        self._enabled = False
        self._moments: deque[GameMoment] = deque(maxlen=capacity)
        self._moment_ids: set[tuple[str, str]] = set()
        self._last_now: float | None = None
        self._counts = {"recorded": 0, "rejected": 0, "duplicates": 0, "expired": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must enable game session memory")
        with self._lock:
            if self._enabled:
                raise RuntimeError("journal already enabled")
            self._moments.clear()
            self._moment_ids.clear()
            self._last_now = None
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._moments.clear()
            self._moment_ids.clear()
            self._last_now = None

    def _advance(self, now_s: float) -> float:
        now = _time(now_s)
        if self._last_now is not None and now < self._last_now:
            raise ValueError("host journal clock moved backwards")
        self._last_now = now
        # Ingest can arrive out of event-time order. Expire *all* old facts,
        # not just an insertion-order prefix (capacity is at most 128).
        fresh = deque((m for m in self._moments
                       if now - m.at_s <= self._max_age), maxlen=self._capacity)
        self._counts["expired"] += len(self._moments) - len(fresh)
        self._moments = fresh
        self._moment_ids = {(m.game_scope, m.moment_id) for m in fresh}
        return now

    def record(self, moment: GameMoment, *, now_s: float,
               host_observed: bool = False) -> bool:
        """Accept a recent, exact game-state observation from the trusted host.

        The boolean is an API boundary, *not* authentication. Never route a
        viewer/model supplied assertion to this method as host_observed=True.
        """
        if not isinstance(moment, GameMoment) or type(host_observed) is not bool:
            raise TypeError("structured GameMoment and explicit host flag required")
        with self._lock:
            now = self._advance(now_s)
            if not self._enabled or not host_observed:
                self._counts["rejected"] += 1
                return False
            # Event identifiers are local to their trusted game scope. Two
            # games may independently emit the same observation sequence ID.
            key = (moment.game_scope, moment.moment_id)
            if key in self._moment_ids:
                self._counts["duplicates"] += 1
                return False
            if moment.at_s > now or now - moment.at_s > min(self._max_age, self._max_lag):
                self._counts["rejected"] += 1
                return False
            if len(self._moments) == self._capacity:
                removed = self._moments.popleft()
                self._moment_ids.discard((removed.game_scope, removed.moment_id))
            self._moments.append(moment)
            self._moment_ids.add(key)
            self._counts["recorded"] += 1
            return True

    def recall(self, *, now_s: float, game_scope: str, limit: int = 3
               ) -> tuple[EpisodeRecall, ...]:
        """Offer concise, accurately scoped recollections, newest first.

        Prefer different moment types to avoid monotonous commentary. Results
        are suggestions to a host, not freeform autonomous AI memories.
        """
        _identifier(game_scope, "game_scope")
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError("limit must be 1..5")
        with self._lock:
            now = self._advance(now_s)
            if not self._enabled:
                return ()
            seen_kinds: set[str] = set()
            cards: list[EpisodeRecall] = []
            # Event timestamps, not network arrival order, define memory age.
            for moment in sorted(self._moments,
                                 key=lambda m: (m.at_s, m.moment_id), reverse=True):
                if moment.game_scope != game_scope or moment.kind in seen_kinds:
                    continue
                seen_kinds.add(moment.kind)
                scope = moment.game_scope
                where = f" on stage {moment.stage_id}" if moment.stage_id else ""
                # Copy-free deterministic template; not a raw transcript or
                # untrusted viewer instruction. Game names are canonical IDs.
                context = f"Earlier in {scope}, Star {_CAPTIONS[moment.kind]}{where}."
                cards.append(EpisodeRecall(context, int(max(0, now - moment.at_s)), scope))
                if len(cards) == limit:
                    break
            return tuple(cards)

    def metrics(self) -> dict[str, int | bool]:
        """Anonymous counters only, never raw moments or session details."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled, "retained": len(self._moments)}


__all__ = ["GameMoment", "EpisodeRecall", "StreamEpisodeJournal"]
