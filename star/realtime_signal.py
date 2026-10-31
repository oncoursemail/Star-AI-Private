"""Opt-in, bounded real-time signal arbitration and interruption-safe playback tickets.

This is pure, synchronous planning code: no microphones, game inputs, GPU work,
networking, OBS, TTS, subprocesses or timers are started. The owner-approved
runtime must provide one monotonic millisecond clock and re-check tickets just
before each media output. Not thread-safe; serialize calls in the event loop.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass
import re

_IDENT = re.compile(r"[a-z0-9][a-z0-9_.-]{0,79}\Z")
PRIORITY = ("owner", "urgent_game", "game", "chat", "vision", "background")
LIMITS = {"owner": 12, "urgent_game": 24, "game": 32, "chat": 24, "vision": 2, "background": 8}
MAX_EVENT_AGE_MS = 60_000
MAX_TICKET_MS = 30_000


def _id(value: str, name: str) -> None:
    if type(value) is not str or _IDENT.fullmatch(value) is None:
        raise ValueError(f"{name} must be an opaque 1-80 character lowercase identifier")


def _ms(value: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= 10**15:
        raise ValueError(f"{name} must be a nonnegative monotonic millisecond integer")


@dataclass(frozen=True)
class Signal:
    """Only opaque references, not raw screen frames/chat/audio/user data."""

    event_id: str
    lane: str
    observed_ms: int
    expires_ms: int
    payload_ref: str
    coalesce_key: str | None = None

    def __post_init__(self) -> None:
        _id(self.event_id, "event_id")
        _id(self.payload_ref, "payload_ref")
        if self.lane not in PRIORITY:
            raise ValueError("unknown signal lane")
        _ms(self.observed_ms, "observed_ms")
        _ms(self.expires_ms, "expires_ms")
        if not 0 < self.expires_ms - self.observed_ms <= MAX_EVENT_AGE_MS:
            raise ValueError("signal lifetime must be 1..60000 ms")
        if self.coalesce_key is not None:
            _id(self.coalesce_key, "coalesce_key")
            if self.lane not in {"game", "vision", "background"}:
                raise ValueError("only state/vision/background signals may be coalesced")


class LiveInbox:
    """Deadline-bounded FIFO within each priority lane, with optional chat fairness.

    Producers do not block. On pressure, an urgent signal can displace a lower
    priority one; background work cannot evict critical owner/game events.
    The event loop should drain before any expensive inference call.
    """

    def __init__(self, *, enabled: bool = False, capacity: int = 64, game_burst: int = 4):
        if type(enabled) is not bool or type(capacity) is not int or not 1 <= capacity <= 256:
            raise ValueError("invalid inbox enabled/capacity")
        if type(game_burst) is not int or not 1 <= game_burst <= 16:
            raise ValueError("invalid game_burst")
        self.enabled = enabled
        self.capacity = capacity
        self.game_burst = game_burst
        self._events: OrderedDict[str, Signal] = OrderedDict()
        self._game_streak = 0
        self._counts: Counter[str] = Counter()

    def disable(self) -> None:
        self.enabled = False
        self._events.clear()
        self._game_streak = 0

    def _expire(self, now_ms: int) -> None:
        for key, item in list(self._events.items()):
            if item.expires_ms <= now_ms:
                del self._events[key]
                self._counts["expired"] += 1

    def offer(self, signal: Signal, *, now_ms: int) -> str:
        _ms(now_ms, "now_ms")
        if not isinstance(signal, Signal):
            raise ValueError("offer requires a Signal")
        if not self.enabled:
            self._counts["disabled"] += 1
            return "disabled"
        self._expire(now_ms)
        if signal.expires_ms <= now_ms:
            self._counts["expired_on_arrival"] += 1
            return "expired"
        if signal.observed_ms > now_ms + 500:
            self._counts["future"] += 1
            return "future"
        pending = OrderedDict(self._events)  # Admission is atomic even on rejection.
        adjustments: Counter[str] = Counter()
        previous = pending.get(signal.event_id)
        if previous is not None:
            if previous == signal:
                self._counts["duplicate"] += 1
                return "duplicate"
            if previous.observed_ms >= signal.observed_ms:
                self._counts["out_of_order"] += 1
                return "out_of_order"
            del pending[signal.event_id]
            adjustments["updated"] += 1
        if signal.coalesce_key is not None:
            for key, item in list(pending.items()):
                if item.lane == signal.lane and item.coalesce_key == signal.coalesce_key:
                    if item.observed_ms > signal.observed_ms:
                        self._counts["out_of_order"] += 1
                        return "out_of_order"
                    del pending[key]
                    adjustments["coalesced"] += 1
        own = [(key, item) for key, item in pending.items() if item.lane == signal.lane]
        if len(own) >= LIMITS[signal.lane]:
            key, oldest = min(own, key=lambda pair: (pair[1].observed_ms, pair[1].expires_ms))
            if oldest.observed_ms > signal.observed_ms:
                self._counts["out_of_order"] += 1
                return "out_of_order"
            del pending[key]
            adjustments["lane_evicted"] += 1
        if len(pending) >= self.capacity:
            # Lowest-priority and oldest current item. Never sacrifice more urgent data.
            key, loser = max(pending.items(), key=lambda pair: (PRIORITY.index(pair[1].lane),
                                                               -pair[1].observed_ms))
            if PRIORITY.index(signal.lane) >= PRIORITY.index(loser.lane):
                self._counts["capacity_rejected"] += 1
                return "full"
            del pending[key]
            adjustments["capacity_evicted"] += 1
        pending[signal.event_id] = signal
        self._events = pending
        self._counts.update(adjustments)
        self._counts["admitted"] += 1
        return "admitted"

    def take(self, *, now_ms: int) -> Signal | None:
        _ms(now_ms, "now_ms")
        if not self.enabled:
            return None
        self._expire(now_ms)
        if not self._events:
            return None
        lanes = {item.lane for item in self._events.values()}
        if "owner" in lanes:
            lane = "owner"
        elif "urgent_game" in lanes:
            lane = "urgent_game"
        elif self._game_streak >= self.game_burst and "chat" in lanes:
            lane = "chat"
        else:
            lane = next(name for name in PRIORITY if name in lanes)
        # Closest deadline first within a lane; tie-break by oldest observation then insertion order.
        key = min((k for k, e in self._events.items() if e.lane == lane),
                  key=lambda k: (self._events[k].expires_ms, self._events[k].observed_ms))
        result = self._events.pop(key)
        self._game_streak = self._game_streak + 1 if lane == "game" else 0
        self._counts["taken"] += 1
        self._counts[f"taken_{lane}"] += 1
        return result

    def metrics(self) -> dict[str, int]:
        return {"pending": len(self._events), **dict(sorted(self._counts.items()))}


@dataclass(frozen=True)
class PlaybackTicket:
    """The session generation must match at the last possible playback boundary."""

    session_id: str
    session_generation: int
    turn_generation: int
    expires_ms: int


class PlaybackGate:
    """Fail-closed token gate for TTS, captions, lipsync and avatar motion.

    An interruption invalidates queued/generated output immediately at this
    decision layer. Host playback adapters MUST consult `allows` on every chunk.
    This does not forcibly stop an already-playing third-party media player.
    """

    def __init__(self, *, enabled: bool = False):
        if type(enabled) is not bool:
            raise ValueError("explicit boolean enablement required")
        self.enabled = enabled
        self._session: str | None = None
        self._session_generation = 0
        self._turn_generation = 0
        self._ticket: PlaybackTicket | None = None

    def open_session(self, session_id: str) -> None:
        _id(session_id, "session_id")
        if not self.enabled:
            raise PermissionError("stream output gate is disabled")
        self._session_generation += 1
        self._session = session_id
        self.interrupt()

    def begin_turn(self, *, now_ms: int, ttl_ms: int = 10_000) -> PlaybackTicket:
        _ms(now_ms, "now_ms")
        if type(ttl_ms) is not int or not 1 <= ttl_ms <= MAX_TICKET_MS:
            raise ValueError("ttl_ms must be 1..30000")
        if not self.enabled or self._session is None:
            raise PermissionError("no opted-in active stream session")
        self.interrupt()
        ticket = PlaybackTicket(self._session, self._session_generation,
                                self._turn_generation, now_ms + ttl_ms)
        self._ticket = ticket
        return ticket

    def interrupt(self) -> None:
        self._turn_generation += 1
        self._ticket = None

    def allows(self, ticket: PlaybackTicket, *, now_ms: int) -> bool:
        _ms(now_ms, "now_ms")
        return (self.enabled and isinstance(ticket, PlaybackTicket) and self._ticket == ticket
                and ticket.session_id == self._session
                and ticket.session_generation == self._session_generation
                and ticket.turn_generation == self._turn_generation
                and now_ms < ticket.expires_ms)

    def close_session(self) -> None:
        self.interrupt()
        self._session = None

    def disable(self) -> None:
        self.close_session()
        self.enabled = False
