"""Human-like input: every controller's intents become timed mouse and key events that move like a person's.

What makes input look human (sources in docs/research/game-play-20261026.md):
  * reaction delay to a NEW stimulus drawn from an ex-Gaussian (normal + exponential tail): mean ~0.26 s, rarely
    under 0.15 s, sometimes 0.4 s+; continuing an action already under way has no new delay;
  * pointing time follows Fitts' law, MT = a + b * log2(D / W + 1): far or small targets take longer;
  * the pointer path is curved (a bezier bent sideways), its speed is bell-shaped (minimum-jerk profile), it shakes a
    little, and about one aim in four overshoots and comes back with a short corrective sub-movement;
  * sometimes the aim lands a little off the target (a miss), keys are held for slightly different times, and a
    key can be released a little early or late.
Events are plain data (`Event`), so tests check them without a desktop; `Actuator` plays them on a real or fake
`InputSink` from its own thread, so a slow aim never blocks perception. Nothing here reads or changes game memory.
"""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class HumanProfile:
    reaction_mu: float = 0.20          # s, normal part of the ex-Gaussian reaction time
    reaction_sigma: float = 0.03
    reaction_tau: float = 0.06         # s, exponential tail (mean reaction = mu + tau)
    reaction_min: float = 0.13
    reaction_max: float = 1.2
    fitts_a: float = 0.08              # s
    fitts_b: float = 0.12              # s per bit
    mouse_hz: float = 125.0            # pointer events per second (a common USB mouse polling rate)
    curvature: float = 0.10            # sideways bend of the path, as a fraction of the distance
    shake_px: float = 0.8              # hand tremor, fades to 0 at the end of each sub-movement
    overshoot_p: float = 0.25
    overshoot_frac: tuple[float, float] = (0.03, 0.09)
    miss_p: float = 0.04               # aim ends off target by up to 0.8 target widths
    tap_s: tuple[float, float] = (0.06, 0.13)
    hold_jitter: float = 0.12          # held keys last +-12 %
    slip_p: float = 0.0                # chance a tap hits a neighbouring key from `slip_keys` instead (off by default)
    slip_keys: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Aim:
    """Move the pointer to an absolute screen point (menus, inventory, clicking a thing on screen)."""
    x: float
    y: float
    width: float = 20.0                # target size in pixels (Fitts' W)
    click: str = ""                    # "", "left" or "right"
    react: bool = True                 # a new stimulus: wait a reaction time first


@dataclass(frozen=True)
class Look:
    """Turn the camera by a relative mouse movement (games with mouse-look); `drag` holds a button meanwhile."""
    dx: float
    dy: float = 0.0
    drag: str = ""                     # "right" for Roblox's default camera
    react: bool = True


@dataclass(frozen=True)
class Hold:
    """Keep `key` down for `seconds`; repeating it while down extends the hold instead of pressing again."""
    key: str
    seconds: float
    react: bool = False


@dataclass(frozen=True)
class Tap:
    key: str
    react: bool = True


@dataclass(frozen=True)
class Release:
    key: str


Intent = Aim | Look | Hold | Tap | Release


@dataclass(frozen=True)
class Event:
    t: float                           # absolute time on the actuator's clock
    kind: str                          # move_to | move_rel | button_down | button_up | key_down | key_up
    a: Any = None
    b: Any = None
    channel: str = "mouse"             # mouse events of a newer aim replace pending ones; keys are per key


class InputSink(Protocol):
    def move_to(self, x: int, y: int) -> None: ...

    def move_rel(self, dx: int, dy: int) -> None: ...

    def button(self, name: str, down: bool) -> None: ...

    def key(self, name: str, down: bool) -> None: ...


def reaction_delay(rng: random.Random, p: HumanProfile) -> float:
    sample = rng.gauss(p.reaction_mu, p.reaction_sigma) + rng.expovariate(1.0 / p.reaction_tau)
    return min(p.reaction_max, max(p.reaction_min, sample))


def movement_time(distance: float, width: float, p: HumanProfile) -> float:
    return p.fitts_a + p.fitts_b * math.log2(max(0.0, distance) / max(1.0, width) + 1.0)


def _min_jerk(tau: float) -> float:
    return tau ** 3 * (10 - 15 * tau + 6 * tau * tau)


def _segment(x0: float, y0: float, x1: float, y1: float, duration: float, rng: random.Random,
             p: HumanProfile) -> list[tuple[float, float, float]]:
    """One sub-movement: (t, x, y) points along a sideways-bent bezier with a minimum-jerk speed profile."""
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy)
    bend = rng.gauss(0.0, p.curvature) * dist
    nx, ny = (-dy / dist, dx / dist) if dist else (0.0, 0.0)
    cx, cy = (x0 + x1) / 2 + nx * bend, (y0 + y1) / 2 + ny * bend
    steps = max(2, int(duration * p.mouse_hz))
    out = []
    for i in range(1, steps + 1):
        tau = i / steps
        s = _min_jerk(tau)
        bx = (1 - s) ** 2 * x0 + 2 * (1 - s) * s * cx + s * s * x1
        by = (1 - s) ** 2 * y0 + 2 * (1 - s) * s * cy + s * s * y1
        shake = p.shake_px * (1 - tau)
        out.append((tau * duration, bx + rng.gauss(0, shake), by + rng.gauss(0, shake)))
    return out


def pointer_path(start: tuple[float, float], end: tuple[float, float], width: float, rng: random.Random,
                 p: HumanProfile) -> list[tuple[float, float, float]]:
    """(t from 0, x, y) for one aim: primary movement, maybe an overshoot and correction, maybe a small miss."""
    (x0, y0), (x1, y1) = start, end
    if rng.random() < p.miss_p:
        angle = rng.uniform(0, 2 * math.pi)
        off = rng.uniform(0.5, 0.8) * width
        x1, y1 = x1 + math.cos(angle) * off, y1 + math.sin(angle) * off
    dist = math.hypot(x1 - x0, y1 - y0)
    total = movement_time(dist, width, p)
    if dist < 1.0:
        return [(0.0, x1, y1)]
    if rng.random() < p.overshoot_p and dist > 3 * width:
        over = 1.0 + rng.uniform(*p.overshoot_frac)
        ox, oy = x0 + (x1 - x0) * over, y0 + (y1 - y0) * over
        first = _segment(x0, y0, ox, oy, total * 0.8, rng, p)
        t0 = first[-1][0] + rng.uniform(0.03, 0.08)      # a short pause before the correction
        second = [(t0 + t, x, y) for t, x, y in _segment(ox, oy, x1, y1, max(0.06, total * 0.3), rng, p)]
        path = first + second
    else:
        path = _segment(x0, y0, x1, y1, total, rng, p)
    t_end = path[-1][0]
    return path[:-1] + [(t_end, x1, y1)]                 # end exactly where the (possibly missed) aim was


class HumanInput:
    """Turns intents into timed `Event`s. Keeps where it thinks the pointer is and which keys it holds."""

    def __init__(self, profile: HumanProfile | None = None, *, rng: random.Random | None = None,
                 pointer: tuple[float, float] = (0.0, 0.0)) -> None:
        self.p = profile or HumanProfile()
        self.rng = rng or random.Random()
        self.pointer = pointer
        self.mistakes = 0

    def plan(self, intent: Intent, now: float) -> list[Event]:
        start = now + (reaction_delay(self.rng, self.p) if getattr(intent, "react", False) else 0.0)
        if isinstance(intent, Aim):
            return self._aim(intent, start)
        if isinstance(intent, Look):
            return self._look(intent, start)
        if isinstance(intent, Hold):
            seconds = max(0.03, intent.seconds * (1 + self.rng.uniform(-self.p.hold_jitter, self.p.hold_jitter)))
            return [Event(start, "key_down", intent.key, None, "key:" + intent.key),
                    Event(start + seconds, "key_up", intent.key, None, "key:" + intent.key)]
        if isinstance(intent, Tap):
            key = intent.key
            if self.p.slip_p and key in self.p.slip_keys and self.rng.random() < self.p.slip_p:
                key = self.rng.choice(list(self.p.slip_keys[key]))
                self.mistakes += 1
            hold = self.rng.uniform(*self.p.tap_s)
            return [Event(start, "key_down", key, None, "key:" + key), Event(start + hold, "key_up", key, None, "key:" + key)]
        if isinstance(intent, Release):
            return [Event(now, "key_up", intent.key, None, "key:" + intent.key)]
        raise TypeError(f"unknown intent {intent!r}")

    def _aim(self, aim: Aim, start: float) -> list[Event]:
        path = pointer_path(self.pointer, (aim.x, aim.y), aim.width, self.rng, self.p)
        events = [Event(start + t, "move_to", round(x), round(y)) for t, x, y in path]
        end = path[-1]
        if (end[1] - aim.x) ** 2 + (end[2] - aim.y) ** 2 > (aim.width / 2) ** 2:
            self.mistakes += 1
        self.pointer = (end[1], end[2])
        if aim.click:
            t = events[-1].t + self.rng.uniform(0.02, 0.07)
            hold = self.rng.uniform(0.05, 0.11)
            events += [Event(t, "button_down", aim.click), Event(t + hold, "button_up", aim.click)]
        return events

    def _look(self, look: Look, start: float) -> list[Event]:
        """Relative camera turn: the same human path shape, sent as integer deltas (fractions carried over)."""
        width = 40.0                                        # camera turns are coarse targets
        path = pointer_path((0.0, 0.0), (look.dx, look.dy), width, self.rng, self.p)
        events: list[Event] = []
        if look.drag:
            events.append(Event(start, "button_down", look.drag))
        sent_x = sent_y = 0
        for t, x, y in path:
            step_x, step_y = round(x) - sent_x, round(y) - sent_y
            if step_x or step_y:
                events.append(Event(start + t, "move_rel", step_x, step_y))
                sent_x, sent_y = sent_x + step_x, sent_y + step_y
        if look.drag:
            events.append(Event((events[-1].t if events else start) + 0.03, "button_up", look.drag))
        return events


class Actuator:
    """Plays events on an InputSink at their times. A newer mouse plan replaces pending mouse events; a newer hold
    of a key that is already down only moves its release time (so walking never stutters)."""

    def __init__(self, sink: InputSink, *, clock: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.sink, self.clock, self._sleep = sink, clock, sleep
        self._pending: list[Event] = []
        self._down: set[str] = set()
        self._buttons: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.fired = 0
        self.first_fire_lag: list[float] = []               # how late events fired versus their planned time

    def submit(self, events: list[Event]) -> None:
        if not events:
            return
        with self._lock:
            if any(e.channel == "mouse" for e in events):
                self._pending = [e for e in self._pending if e.channel != "mouse"]
            for key_channel in {e.channel for e in events if e.channel.startswith("key:")}:
                key = key_channel[4:]
                if key in self._down:
                    downs = [e for e in events if e.channel == key_channel and e.kind == "key_down"]
                    if downs:                                # already held: drop the press, keep the new release
                        self._pending = [e for e in self._pending if e.channel != key_channel]
                        events = [e for e in events if not (e.channel == key_channel and e.kind == "key_down")]
                else:
                    self._pending = [e for e in self._pending if e.channel != key_channel or e.kind != "key_up"]
            self._pending.extend(events)
            self._pending.sort(key=lambda e: e.t)

    def pump(self, now: float | None = None) -> int:
        now = self.clock() if now is None else now
        with self._lock:
            due = [e for e in self._pending if e.t <= now]
            self._pending = [e for e in self._pending if e.t > now]
        for e in due:
            self._fire(e)
            self.first_fire_lag.append(now - e.t)
        if len(self.first_fire_lag) > 2000:
            del self.first_fire_lag[:1000]
        return len(due)

    def _fire(self, e: Event) -> None:
        if e.kind == "move_to":
            self.sink.move_to(int(e.a), int(e.b))
        elif e.kind == "move_rel":
            self.sink.move_rel(int(e.a), int(e.b))
        elif e.kind in ("button_down", "button_up"):
            down = e.kind == "button_down"
            if down == (e.a in self._buttons):
                return
            (self._buttons.add if down else self._buttons.discard)(e.a)
            self.sink.button(str(e.a), down)
        elif e.kind in ("key_down", "key_up"):
            down = e.kind == "key_down"
            if down == (e.a in self._down):
                return
            (self._down.add if down else self._down.discard)(e.a)
            self.sink.key(str(e.a), down)
        self.fired += 1

    def held(self) -> set[str]:
        return set(self._down)

    def release_all(self) -> None:
        with self._lock:
            self._pending.clear()
        for key in list(self._down):
            self._fire(Event(0, "key_up", key))
        for button in list(self._buttons):
            self._fire(Event(0, "button_up", button))

    def run(self, period: float = 0.002) -> None:
        while not self._stop.is_set():
            self.pump()
            self._sleep(period)
        self.release_all()

    def stop(self) -> None:
        self._stop.set()


class RecordingSink:
    """Remembers every call (tests, dry runs, and the latency bench)."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self.calls: list[tuple] = []
        self.clock = clock

    def move_to(self, x: int, y: int) -> None:
        self.calls.append(("move_to", x, y, self.clock()))

    def move_rel(self, dx: int, dy: int) -> None:
        self.calls.append(("move_rel", dx, dy, self.clock()))

    def button(self, name: str, down: bool) -> None:
        self.calls.append(("button", name, down, self.clock()))

    def key(self, name: str, down: bool) -> None:
        self.calls.append(("key", name, down, self.clock()))
