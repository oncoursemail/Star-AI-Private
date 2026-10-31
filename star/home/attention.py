"""Attention: how STAR notices a message or a call on her own PC and decides, like a person, whether and when to answer.

    notification (toast) -> Incoming -> AvailabilityModel.decide() -> Inbox -> due -> Attention.serve() -> a handler

AvailabilityModel (pure rules plus an injectable random generator, so tests are exact):
  * blocked or muted people: never. Strangers: a DM or mention may wait a long time, a call is never answered
    (she does not join calls from people she does not know).
  * answers sooner for close friends (seconds), later for friends (a minute or two), later still for people she met
    once; sometimes she gets to it much later whoever it is.
  * mid game round or mid video she finishes the moment first, but only up to a bound (close friends: a minute),
    then she stops what she is doing and answers.
  * quiet hours (config, off by default): DMs wait for the morning plus a little, calls are not answered.
  * a call must be answered while it still rings, so its waits are short and the whole answer must fit inside the ring.
Inbox holds what is waiting; Attention connects it to the loop: a watcher thread calls `watch_tick()` (it sets the
interrupt when something is due so the running activity stops cleanly), and `serve()` runs the handlers between
activities. A paused activity is parked and resumed afterwards (loop.cycle).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import random
import threading
import time
from typing import Callable

DEFAULTS = {
    "quiet_hours": {"enabled": False, "start": "01:00", "end": "08:00"},
    "close_at": 0.6,                                      # closeness (0..1) from which a friend counts as close
    "message_delay_s": {"close": [8, 45], "friend": [30, 150], "met": [120, 600]},
    "later_chance": {"close": 0.1, "friend": 0.25, "met": 0.4},
    "later_factor": [3, 8],                               # a "later" answer takes this many times the normal delay
    "max_delay_s": 2400,
    "moment_wait_s": {"close": 60, "friend": 120, "met": 240},
    "call_answer_chance": {"close": 0.9, "friend": 0.6},  # others (strangers, muted, blocked): never
    "call_pickup_s": [2, 8],
    "call_moment_wait_s": {"close": 15, "friend": 8},
    "call_ring_s": 45,
    "resume_within_minutes": 45,
}


def settings(config: dict | None) -> dict:
    """DEFAULTS with the owner's `availability` block from config.json laid over them (one level deep)."""
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    for key, value in ((config or {}).get("availability") or {}).items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key].update(value)
        elif key in merged:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class Incoming:
    kind: str                  # dm | mention | call | hangup | followup (missed call) | callout | startgame (her own plans)
    platform: str              # discord | roblox | ...
    sender: str                # display name from the notification, or "" for hangup
    text: str = ""
    at: float = 0.0            # epoch seconds
    ring_s: float = 0.0        # calls: how long it keeps ringing

    @property
    def route(self) -> str:
        """The handler key: "discord:call", "discord:message", "discord:hangup", "discord:callout", "discord:startgame"."""
        own = ("call", "hangup", "callout", "startgame")
        return f"{self.platform}:{self.kind if self.kind in own else 'message'}"


@dataclass(frozen=True)
class Standing:
    """What she knows about the sender (from friend memory)."""
    known: bool = False
    relationship: str = "met"      # met | friend
    closeness: float = 0.0         # 0..1
    blocked: bool = False
    muted: bool = False

    def tier(self, close_at: float) -> str:
        if self.blocked or self.muted:
            return "never"
        if self.relationship == "friend" and self.closeness >= close_at:
            return "close"
        return "friend" if self.relationship == "friend" else "met"


@dataclass
class Situation:
    """What she is doing now. The loop sets `kind`; an activity sets `in_moment` while a round or a video is running."""
    kind: str = "idle"             # idle | game | video | work
    in_moment: bool = False
    in_call: bool = False
    activity: str = ""             # name of the running activity
    since: float = 0.0             # epoch when it started


@dataclass(frozen=True)
class Decision:
    action: str                    # answer | ignore
    at: float                      # epoch: not before this
    wait_until: float              # epoch: she waits for the moment to end, but not past this
    reason: str


class Interrupt:
    """Set by the watcher when something is due; the running activity looks at it between steps and stops cleanly."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self.reason = ""

    def set(self, reason: str = "") -> None:
        self.reason = reason
        self._event.set()

    def clear(self) -> None:
        self.reason = ""
        self._event.clear()

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


def _minutes(clock: str) -> int:
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def in_quiet_hours(now: float, quiet: dict) -> bool:
    if not quiet or not quiet.get("enabled"):
        return False
    start, end = _minutes(quiet["start"]), _minutes(quiet["end"])
    local = datetime.fromtimestamp(now)
    minute = local.hour * 60 + local.minute
    return (start <= minute < end) if start <= end else (minute >= start or minute < end)


def quiet_end(now: float, quiet: dict) -> float:
    """The next time the quiet hours end (epoch)."""
    local = datetime.fromtimestamp(now)
    end = _minutes(quiet["end"])
    target = local.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
    if target.timestamp() <= now:
        target += timedelta(days=1)
    return target.timestamp()


class AvailabilityModel:
    def __init__(self, config: dict | None = None, *, rng: random.Random | None = None) -> None:
        self.cfg = settings(config)
        self.rng = rng or random.Random()

    def _between(self, pair) -> float:
        low, high = float(pair[0]), float(pair[1])
        return self.rng.uniform(low, max(low, high))

    def decide(self, incoming: Incoming, standing: Standing, situation: Situation, now: float | None = None) -> Decision:
        now = incoming.at if now is None and incoming.at else (time.time() if now is None else now)
        cfg = self.cfg
        tier = standing.tier(float(cfg["close_at"]))
        if tier == "never":
            return Decision("ignore", now, now, "blocked or muted: she does not answer them")
        quiet = in_quiet_hours(now, cfg["quiet_hours"])
        if incoming.kind == "call":
            return self._call(incoming, tier, situation, now, quiet)
        delay = self._between(cfg["message_delay_s"][tier])
        if self.rng.random() < float(cfg["later_chance"][tier]):
            delay *= self._between(cfg["later_factor"])
        delay = min(delay, float(cfg["max_delay_s"]))
        at = now + delay
        why = f"{tier}: answers in about {int(delay)} s"
        if quiet:
            at = max(at, quiet_end(now, cfg["quiet_hours"]) + self.rng.uniform(0, 900))
            why = f"{tier}: quiet hours, she answers after they end"
        return Decision("answer", at, at + float(cfg["moment_wait_s"][tier]), why)

    def _call(self, incoming: Incoming, tier: str, situation: Situation, now: float, quiet: bool) -> Decision:
        cfg = self.cfg
        if tier == "met":
            return Decision("ignore", now, now, "she does not join calls from people she does not know well")
        if quiet:
            return Decision("ignore", now, now, "quiet hours: she is not taking calls")
        if situation.in_call:
            return Decision("ignore", now, now, "she is already in a call")
        if self.rng.random() >= float(cfg["call_answer_chance"][tier]):
            return Decision("ignore", now, now, f"{tier}: she lets this one ring")
        ring_s = incoming.ring_s or float(cfg["call_ring_s"])
        deadline = incoming.at + ring_s - 3.0 if incoming.at else now + ring_s - 3.0
        at = now + self._between(cfg["call_pickup_s"])
        wait_until = at + float(cfg["call_moment_wait_s"][tier])
        if wait_until >= deadline:
            return Decision("ignore", now, now, "she could not get to it before it stops ringing")
        return Decision("answer", at, wait_until, f"{tier}: picks up in about {int(at - now)} s")


@dataclass
class Pending:
    incoming: Incoming
    standing: Standing
    decision: Decision
    count: int = 1                  # notifications folded into this one (same sender, same kind)

    @property
    def expires(self) -> float | None:
        if self.incoming.kind == "call":
            return self.incoming.at + (self.incoming.ring_s or 0.0)
        return None


class Inbox:
    def __init__(self, model: AvailabilityModel, standing_of: Callable[[Incoming], Standing], situation: Situation,
                 *, clock: Callable[[], float] = time.time, on_decision: Callable[[Incoming, Decision], None] | None = None):
        self.model, self.standing_of, self.situation, self.clock = model, standing_of, situation, clock
        self.on_decision = on_decision or (lambda incoming, decision: None)
        self._items: list[Pending] = []
        self._lock = threading.RLock()

    def add(self, incoming: Incoming) -> Pending | None:
        """Takes a notification in. The delay starts with the first message from a sender; later ones just fold in."""
        with self._lock:
            for item in self._items:
                if item.incoming.route == incoming.route and item.incoming.sender == incoming.sender:
                    item.count += 1
                    item.incoming = replace(item.incoming, text=incoming.text or item.incoming.text)
                    return item
            now = self.clock()
            if incoming.kind in ("hangup",):
                standing = Standing()
                decision = Decision("answer", now, now, "her own call timer")
            else:
                standing = self.standing_of(incoming)
                decision = self.model.decide(incoming, standing, self.situation, now)
            self.on_decision(incoming, decision)
            if decision.action != "answer":
                return None
            pending = Pending(incoming, standing, decision)
            self._items.append(pending)
            return pending

    def schedule(self, incoming: Incoming, at: float, wait_until: float, reason: str = "") -> Pending:
        """Her own plan (place a call, start a game) at a time she chose; waits for a running moment like the rest."""
        with self._lock:
            pending = Pending(incoming, self.standing_of(incoming), Decision("answer", at, max(at, wait_until), reason))
            self._items.append(pending)
            self.on_decision(incoming, pending.decision)
            return pending

    def _ready(self, item: Pending, now: float) -> bool:
        if now < item.decision.at:
            return False
        if self.situation.in_call and item.incoming.kind in ("dm", "mention", "followup"):
            return False                                    # she is on a call: messages wait until it ends
        if self.situation.in_moment and now < item.decision.wait_until:
            return False                                    # finish the round or the scene first, within the bound
        return True

    def expire(self, now: float | None = None) -> list[Pending]:
        """Calls that stopped ringing: removed and returned (a missed call from a friend becomes a follow-up message)."""
        now = self.clock() if now is None else now
        with self._lock:
            gone = [i for i in self._items if i.expires is not None and now >= i.expires]
            self._items = [i for i in self._items if i not in gone]
            return gone

    def due(self, now: float | None = None) -> list[Pending]:
        now = self.clock() if now is None else now
        with self._lock:
            ready = [i for i in self._items if self._ready(i, now)]
            return sorted(ready, key=lambda i: (i.incoming.kind != "call", i.decision.at))

    def remove(self, item: Pending) -> None:
        with self._lock:
            if item in self._items:
                self._items.remove(item)

    def waiting(self) -> list[Pending]:
        with self._lock:
            return list(self._items)


class LeftOutWatch:
    """Friends chatting in a server channel for a while without including her (no message mentions her). Feed it what
    she sees each time she reads a channel; it says True once when enough of it piled up, then stays quiet for the
    cooldown. Any message that does address her clears the channel; a long gap starts a fresh conversation."""

    def __init__(self, *, min_messages: int = 6, min_authors: int = 2, cooldown_s: float = 3600.0,
                 gap_s: float = 7200.0, clock: Callable[[], float] = time.time) -> None:
        self.min_messages, self.min_authors, self.cooldown_s, self.gap_s, self._clock = (
            min_messages, min_authors, cooldown_s, gap_s, clock)
        self._channels: dict[str, dict] = {}

    def note(self, channel: str, authors: list[str], addressed: bool = False) -> bool:
        now = self._clock()
        state = self._channels.setdefault(channel, {"count": 0, "authors": set(), "seen": now, "fired": -1e18})
        if addressed or now - state["seen"] > self.gap_s:
            state.update(count=0, authors=set())
        state["seen"] = now
        if addressed or not authors:
            return False
        state["count"] += len(authors)
        state["authors"].update(a.lower() for a in authors)
        if (state["count"] >= self.min_messages and len(state["authors"]) >= self.min_authors
                and now - state["fired"] >= self.cooldown_s):
            state.update(count=0, authors=set(), fired=now)
            return True
        return False


@dataclass
class Parked:
    activity: object
    interest: str
    goal: dict | None
    state: dict
    at: float


class Attention:
    """The loop's view of the inbox: the shared situation, the interrupt, the handlers, the parked activity."""

    def __init__(self, inbox: Inbox, situation: Situation, handlers: dict[str, Callable] | None = None, *,
                 interrupt: Interrupt | None = None, config: dict | None = None, clock: Callable[[], float] = time.time,
                 log: Callable[..., None] | None = None) -> None:
        self.inbox, self.situation = inbox, situation
        self.handlers = handlers if handlers is not None else {}
        self.interrupt = interrupt or Interrupt()
        self.cfg = settings(config)
        self.clock = clock
        self._log = log or (lambda *args, **kwargs: None)
        self.parked: Parked | None = None
        self.requested = ""
        self.last_state = ""                       # "worked" / "waiting": the loop's last outcome (for took_a_break)

    # ---- the watcher thread ----------------------------------------------------------------------------------
    def watch_tick(self) -> bool:
        """Called every second or two: expired calls become follow-ups; when something is due, stop the activity."""
        for missed in self.inbox.expire():
            if missed.standing.tier(float(self.cfg["close_at"])) in ("close", "friend"):
                self.inbox.add(Incoming("followup", missed.incoming.platform, missed.incoming.sender,
                                        "missed call", at=self.clock()))
            self._log("missed", route=missed.incoming.route, sender=missed.incoming.sender)
        if self.inbox.due():
            if not self.interrupt.is_set():
                self.interrupt.set("something is waiting for her")
            return True
        return False

    def idle_wait(self, seconds: float, *, sleep: Callable[[float], None] = time.sleep, slice_s: float = 1.0) -> None:
        """Sleep up to `seconds`, but wake as soon as something is due (run_forever uses this between cycles)."""
        end = self.clock() + seconds
        while self.clock() < end:
            self.watch_tick()
            if self.inbox.due():
                return
            sleep(min(slice_s, max(0.0, end - self.clock())))

    # ---- between activities ----------------------------------------------------------------------------------
    def begin(self, kind: str, activity: str = "") -> None:
        self.situation.kind, self.situation.in_moment = kind, kind == "video"   # a video is one long moment
        self.situation.activity, self.situation.since = activity, self.clock()
        self.interrupt.clear()

    def end(self) -> None:
        self.situation.kind, self.situation.in_moment = "idle", False
        self.situation.activity, self.situation.since = "", 0.0

    def request(self, activity: str) -> None:
        """She decided to do this next (for example a game a friend invited her to): the loop takes it first."""
        self.requested = activity
        if not self.interrupt.is_set():
            self.interrupt.set(f"she wants to start {activity}")

    def take_request(self) -> str:
        wanted, self.requested = self.requested, ""
        return wanted

    def park(self, activity, interest: str, goal: dict | None, state: dict | None) -> None:
        self.parked = Parked(activity, interest, goal, dict(state or {}), self.clock())

    def take_parked(self) -> Parked | None:
        parked, self.parked = self.parked, None
        if parked is None:
            return None
        if self.clock() - parked.at > float(self.cfg["resume_within_minutes"]) * 60:
            return None                                      # too long ago: pick something fresh
        return parked

    def serve(self, context_for: Callable[[str], object]) -> list[dict]:
        """Run the handler of everything that is due. `context_for(platform)` gives the handler its Context."""
        served: list[dict] = []
        self.interrupt.clear()
        for item in self.inbox.due():
            incoming = item.incoming
            handler = self.handlers.get(incoming.route)
            self.inbox.remove(item)
            if handler is None:
                result = {"ok": False, "summary": f"no handler for {incoming.route}"}
            else:
                try:
                    result = handler(incoming, context_for(incoming.platform)) or {}
                except Exception as why:
                    result = {"ok": False, "summary": f"handler crashed: {type(why).__name__}: {why}"}
            served.append({"route": incoming.route, "sender": incoming.sender, **result})
            self._log("served", route=incoming.route, sender=incoming.sender, ok=bool(result.get("ok")),
                      summary=str(result.get("summary", ""))[:200])
        return served
