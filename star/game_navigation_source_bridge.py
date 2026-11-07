"""Authenticated, read-only engine-navigation evidence for private game practice.

This is a TRUSTED HOST component, not an LLM tool, game reader, network
endpoint, controller, or proof that a game server is honest. A separate,
owner-controlled engine process must sign its OWN state with a session-only key.
Keep that key out of model workers, client scripts, viewers and logs. Do not
reuse the signed gameplay-moment or Open Cloud credentials.

The receiver validates full signed terrain, monotonic sequence, scope, and
host time before supplying GroundedNavigationMemory's host_verified=True.
Every trust failure permanently revokes the session and purges the map.
There is NO automatic key input, skill credit, OBS broadcast or model update.
"""
from __future__ import annotations

from hashlib import sha256
import hmac
import json
import math
import re
from threading import RLock
import time
from typing import Callable

from .game_navigation_memory import (
    GridPosition, GroundedNavigationMemory, NavigationAdvice,
    NavigationObservation, ObservedTile,
)
from .stream_moment_receipts import validate_receipt_key

_SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_MAC = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BYTES = 16_384
_DOMAIN = b"star.navigation.engine-frame.v1\x00"
_FIELDS = frozenset({
    "v", "source", "session", "game", "version", "episode",
    "seq", "captured_ms", "player", "goal", "tiles",
})


class NavigationSourceRevoked(RuntimeError):
    """Signed game-navigation source cannot be trusted in this session."""


def _identity(source: str, session: str) -> None:
    if type(source) is not str or _SOURCE.fullmatch(source) is None:
        raise ValueError("invalid approved navigation source")
    if type(session) is not str or _SESSION.fullmatch(session) is None:
        raise ValueError("invalid navigation session")


def _canonical(data: dict[str, object]) -> bytes:
    return json.dumps(data, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def _payload(obs: NavigationObservation, source: str, session: str) -> dict[str, object]:
    if type(obs) is not NavigationObservation:
        raise TypeError("typed engine observation required")
    _identity(source, session)
    return {
        "v": 1, "source": source, "session": session,
        "game": obs.game_id, "version": obs.game_version,
        "episode": obs.episode_id, "seq": obs.sequence,
        "captured_ms": obs.captured_ms,
        "player": [obs.player.x, obs.player.y],
        "goal": None if obs.goal is None else [obs.goal.x, obs.goal.y],
        "tiles": [[t.position.x, t.position.y, t.walkable, t.risk_bps]
                  for t in obs.tiles],
    }


def sign_navigation_packet(
    observation: NavigationObservation, *, source_id: str,
    session_id: str, source_key: bytes,
) -> bytes:
    """ENGINE HOST ONLY. Sign trusted state, never a model/viewer assertion.

    This helper deliberately has no game-reading or networking code. The host
    must read authoritative state and enforce a sequential capture stream.
    Receiver handles replays, stale frames and cross-session substitutions.
    """
    payload = _payload(observation, source_id, session_id)
    key = validate_receipt_key(source_key)
    tag = hmac.new(key, _DOMAIN + _canonical(payload), sha256).hexdigest()
    packet = _canonical({**payload, "mac": tag})
    if len(packet) > _MAX_BYTES:
        raise ValueError("navigation packet exceeds bounded transport size")
    return packet


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate navigation field")
        result[key] = value
    return result


def _position(raw: object) -> GridPosition:
    if type(raw) is not list or len(raw) != 2:
        raise ValueError("invalid position shape")
    return GridPosition(raw[0], raw[1])


def parse_navigation_packet(packet: bytes) -> tuple[str, str, NavigationObservation, str]:
    """Strict, bounded parser. Parsing alone does NOT authenticate evidence."""
    if type(packet) is not bytes or not 1 <= len(packet) <= _MAX_BYTES:
        raise ValueError("invalid navigation packet size")
    try:
        fields = json.loads(packet.decode("utf-8", errors="strict"),
                            object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError("malformed navigation packet") from exc
    if type(fields) is not dict or fields.keys() != _FIELDS | {"mac"}:
        raise ValueError("navigation fields changed")
    if type(fields["v"]) is not int or fields["v"] != 1:
        raise ValueError("unsupported navigation packet version")
    _identity(fields["source"], fields["session"])
    if type(fields["mac"]) is not str or _MAC.fullmatch(fields["mac"]) is None:
        raise ValueError("invalid navigation MAC format")
    raw_tiles = fields["tiles"]
    if type(raw_tiles) is not list or not 1 <= len(raw_tiles) <= 128:
        raise ValueError("invalid bounded navigation tiles")
    tiles: list[ObservedTile] = []
    for raw in raw_tiles:
        if type(raw) is not list or len(raw) != 4:
            raise ValueError("invalid tile shape")
        tiles.append(ObservedTile(GridPosition(raw[0], raw[1]), raw[2], raw[3]))
    goal = None if fields["goal"] is None else _position(fields["goal"])
    obs = NavigationObservation(
        game_id=fields["game"], game_version=fields["version"],
        episode_id=fields["episode"], sequence=fields["seq"],
        captured_ms=fields["captured_ms"], player=_position(fields["player"]),
        goal=goal, tiles=tuple(tiles),
    )
    return fields["source"], fields["session"], obs, fields["mac"]


class AuthenticatedNavigationBridge:
    """Pinned, opt-in signed host -> private symbolic navigation advisor.

    No untrusted caller can set host_verified or the clock at the boundary.
    Host-only: accept() reads bytes from independently pinned IPC transport;
    advise() returns a hint, never an input or broadcast permit.
    """
    def __init__(
        self, *, navigator: GroundedNavigationMemory, source_id: str,
        session_id: str, source_key: bytes, game_id: str,
        game_version: str, episode_id: str,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
    ) -> None:
        _identity(source_id, session_id)
        if type(navigator) is not GroundedNavigationMemory:
            raise TypeError("private grounded navigator required")
        if not callable(clock_ms):
            raise TypeError("trusted monotonic clock required")
        self._key = validate_receipt_key(source_key)
        self._nav = navigator
        self._source = source_id
        self._session = session_id
        self._scope = (game_id, game_version, episode_id)
        self._clock = clock_ms
        self._lock = RLock()
        self._active = False
        self._revoked = False
        self._last_seq = 0
        self._last_clock = -1.0
        self._accepted = 0

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for private navigation")
        with self._lock:
            if self._active or self._revoked:
                raise NavigationSourceRevoked("navigation session already used")
            self._nav.start(
                game_id=self._scope[0], game_version=self._scope[1],
                episode_id=self._scope[2], owner_approved=True,
            )
            self._active = True

    def _revoke(self) -> None:
        self._active = False
        self._revoked = True
        self._nav.stop()

    def disable(self) -> None:
        with self._lock:
            self._revoke()

    def _time(self) -> float:
        raw = self._clock()
        if type(raw) not in (int, float):
            raise ValueError("non-numeric trusted clock")
        now = float(raw)
        if (not math.isfinite(now) or not 0 <= now <= 1e13
                or now < self._last_clock):
            raise ValueError("trusted navigation clock reversed")
        self._last_clock = now
        return now

    def accept(self, packet: bytes) -> bool:
        """Atomically authenticate and ingest exactly one engine capture."""
        with self._lock:
            if not self._active or self._revoked:
                raise NavigationSourceRevoked("navigation source not enabled")
            try:
                source, session, obs, tag = parse_navigation_packet(packet)
                if ((source, session) != (self._source, self._session)
                        or (obs.game_id, obs.game_version, obs.episode_id)
                        != self._scope or obs.sequence != self._last_seq + 1):
                    raise ValueError("navigation source continuity changed")
                payload = _payload(obs, source, session)
                expected = hmac.new(
                    self._key, _DOMAIN + _canonical(payload), sha256
                ).hexdigest()
                if not hmac.compare_digest(tag, expected):
                    raise ValueError("navigation packet authentication failed")
                now = self._time()
                if not self._nav.ingest(obs, now_ms=now, host_verified=True):
                    raise ValueError("navigation frame rejected by freshness gate")
                self._last_seq = obs.sequence
                self._accepted += 1
                return True
            except Exception:
                self._revoke()
                raise NavigationSourceRevoked(
                    "navigation evidence failed: session revoked"
                ) from None

    def advise(self) -> NavigationAdvice:
        """Use the bridge's trusted clock; output is *never* input permission."""
        with self._lock:
            if not self._active or self._revoked:
                raise NavigationSourceRevoked("navigation source not enabled")
            try:
                advice = self._nav.advise(now_ms=self._time())
                if advice.authorizes_input or advice.authorizes_broadcast:
                    raise ValueError("unexpected authorization from navigation")
                return advice
            except Exception:
                self._revoke()
                raise NavigationSourceRevoked(
                    "navigation advice failed: session revoked"
                ) from None

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            return {"active": self._active, "revoked": self._revoked,
                    "accepted": self._accepted}


__all__ = [
    "AuthenticatedNavigationBridge", "NavigationSourceRevoked",
    "parse_navigation_packet", "sign_navigation_packet",
]
