"""Private-by-default, ephemeral game-moment journal for Star's streaming persona.

Only an owner-authorized host may submit a *structured* observation from actual
permitted gameplay. The journal does not ingest chat, transcripts, video, memory
from the model, arbitrary text, or supposed emotions. A returned recap is a
bounded factual *suggestion*, never a command to speak or evidence of OBS audio.
Even signed host claims cannot prove the gameplay event really happened.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import secrets
from .stream_moment_receipts import (
    SignedGameMoment, validate_receipt_key, verify_game_moment,
)
import math
import re
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_KINDS = frozenset({
    "checkpoint", "win", "loss", "close_call", "puzzle_solved",
    "mechanic_discovered", "practice_improved",
})
# A bounded session-wide replay fence survives journal FIFO eviction/expiry.
# Reject new receipts at saturation instead of silently forgetting old IDs.
_MAX_SESSION_MOMENT_IDS = 4096
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
                 observation_lag_s: float = 30.0,
                 receipt_key: bytes | None = None) -> None:
        if type(capacity) is not int or not 1 <= capacity <= 128:
            raise ValueError("capacity must be 1..128")
        self._max_age = _time(max_age_s)
        self._max_lag = _time(observation_lag_s)
        if not 60 <= self._max_age <= 28800 or not 0 <= self._max_lag <= 120:
            raise ValueError("invalid expiration or observation lag")
        self._capacity = capacity
        # Only a trusted host should hold this optional shared HMAC secret.
        # Legacy hosts remain compatible but are NOT cryptographically attested.
        self._receipt_key = (validate_receipt_key(receipt_key)
                             if receipt_key is not None else None)
        self._session_id: str | None = None
        self._receipt_watermarks: dict[str, int] = {}
        self._lock = RLock()
        self._enabled = False
        self._moments: deque[GameMoment] = deque(maxlen=capacity)
        # Memory cards expire quickly; source identities must not. Otherwise a
        # reissued game event ID can be relabeled as a new win after eviction.
        self._seen_ids: set[tuple[str, str]] = set()
        self._last_now: float | None = None
        self._counts = {"recorded": 0, "rejected": 0, "duplicates": 0,
                        "expired": 0, "identity_capacity_rejected": 0,
                        "invalid_receipts": 0, "out_of_order_receipts": 0}

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must enable game session memory")
        with self._lock:
            if self._enabled:
                raise RuntimeError("journal already enabled")
            self._moments.clear()
            self._seen_ids.clear()
            self._receipt_watermarks.clear()
            self._session_id = secrets.token_hex(16)
            self._last_now = None
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._moments.clear()
            self._seen_ids.clear()
            self._receipt_watermarks.clear()
            self._session_id = None
            self._last_now = None

    @property
    def session_id(self) -> str | None:
        """Unpredictable per-enabled-session identity, not a signing secret."""
        with self._lock:
            return self._session_id if self._enabled else None

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
        return now

    def record(self, moment: GameMoment, *, now_s: float,
               host_observed: bool = False,
               receipt: SignedGameMoment | None = None) -> bool:
        """Accept a recent, exact game-state observation from the trusted host.

        The boolean alone is NOT authentication. For protected sessions, require
        a receipt created only by an independently trusted game-state signer.
        Even a valid MAC does not prove that the underlying event was true.
        """
        if not isinstance(moment, GameMoment) or type(host_observed) is not bool:
            raise TypeError("structured GameMoment and explicit host flag required")
        with self._lock:
            # An unattested viewer/model claim must not move the session
            # clock, expire legitimate memories or poison future host calls.
            # Reject it before _advance() mutates timestamp/retention state.
            if not self._enabled or not host_observed:
                self._counts["rejected"] += 1
                return False
            if self._receipt_key is not None:
                if (self._session_id is None or not isinstance(receipt, SignedGameMoment)
                        or not verify_game_moment(
                            moment, receipt, session_id=self._session_id,
                            key=self._receipt_key,
                        )):
                    self._counts["rejected"] += 1
                    self._counts["invalid_receipts"] += 1
                    return False
                if receipt.sequence <= self._receipt_watermarks.get(moment.game_scope, 0):
                    self._counts["rejected"] += 1
                    self._counts["out_of_order_receipts"] += 1
                    return False
            elif receipt is not None:
                # Do not misleadingly claim that the legacy journal verified it.
                self._counts["rejected"] += 1
                self._counts["invalid_receipts"] += 1
                return False
            now = self._advance(now_s)
            # Event identifiers are local to their trusted game scope. Two
            # games may independently emit the same observation sequence ID.
            key = (moment.game_scope, moment.moment_id)
            if key in self._seen_ids:
                self._counts["duplicates"] += 1
                return False
            if moment.at_s > now or now - moment.at_s > min(self._max_age, self._max_lag):
                self._counts["rejected"] += 1
                return False
            if len(self._seen_ids) >= _MAX_SESSION_MOMENT_IDS:
                # Saturation is preferable to silently re-admitting a forged
                # "new" achievement that reused a previously accepted ID.
                self._counts["rejected"] += 1
                self._counts["identity_capacity_rejected"] += 1
                return False
            if len(self._moments) == self._capacity:
                self._moments.popleft()
            self._moments.append(moment)
            self._seen_ids.add(key)
            if receipt is not None:
                self._receipt_watermarks[moment.game_scope] = receipt.sequence
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
            return {**self._counts, "enabled": self._enabled,
                    "signed_receipts_required": self._receipt_key is not None,
                    "retained": len(self._moments)}


__all__ = ["GameMoment", "EpisodeRecall", "StreamEpisodeJournal"]
