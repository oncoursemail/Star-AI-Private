"""Her hands: mouse and keyboard actions with human-like timing, the owner's STOP, and a log line for every action.

Pointer moves reuse star/play/humanlike.py (Fitts-law time, curved minimum-jerk paths, overshoot and correction,
reaction delay before a new target); clicks, double clicks, drags, typing, key combinations and scrolling are built on
it. Typing uses an uneven rhythm (log-normal gaps, a longer pause after a space now and then) and never makes
deliberate typos. Before every action the owner's STOP file is checked (star/home/control.py: while it exists every
action raises `Stopped`), and a long move or stroke checks it again every few milliseconds. `dry_run` logs and moves
nothing. The sink (star/computer/winapi.DesktopSink on her PC, a recorder in tests) is the only thing that touches
the desktop, and it carries the window guard.
"""
from __future__ import annotations

import math
from pathlib import Path
import random
import time
from typing import Callable, cast

from ..home import control
from ..play.humanlike import Actuator, Aim, Event, HumanInput, HumanProfile


class Stopped(Exception):
    """The owner's STOP file exists: nothing more is done."""


MODIFIERS = ("ctrl", "shift", "alt", "win")
DRAW_PROFILE = HumanProfile(miss_p=0.0, overshoot_p=0.0, shake_px=0.35, curvature=0.0)


def _spline(points: list[tuple[float, float]], step: float = 3.0, corner_deg: float = 30.0
            ) -> list[tuple[float, float]]:
    """A smooth hand-drawn line through the points: cubic Hermite pieces whose tangents run along the neighbouring
    points but are no longer than the piece itself (no wild overshoot on unevenly spaced points). A point where the
    path turns by more than `corner_deg` is a corner and stays sharp (the tangent there follows the piece), so a
    triangle stays a triangle and a gentle curve stays round."""
    n = len(points)

    def unit(a, b):
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        return ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d else (0.0, 0.0)

    def corner(i: int) -> bool:
        if i == 0 or i == n - 1:
            return True
        u, v = unit(points[i - 1], points[i]), unit(points[i], points[i + 1])
        return math.degrees(math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1])))) > corner_deg

    out: list[tuple[float, float]] = [points[0]]
    for i in range(n - 1):
        p1, p2 = points[i], points[i + 1]
        chord = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if chord == 0:
            continue
        t1 = unit(p1, p2) if corner(i) else unit(points[i - 1], p2)
        t2 = unit(p1, p2) if corner(i + 1) else unit(p1, points[i + 2])
        count = max(1, int(chord / step))
        for k in range(1, count + 1):
            u = k / count
            h00, h10, h01, h11 = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
            out.append((h00 * p1[0] + h10 * chord * t1[0] + h01 * p2[0] + h11 * chord * t2[0],
                        h00 * p1[1] + h10 * chord * t1[1] + h01 * p2[1] + h11 * chord * t2[1]))
    out[-1] = (points[-1][0], points[-1][1])
    return out


def stroke_path(points: list[tuple[float, float]], speed_px_s: float, rng: random.Random,
                p: HumanProfile) -> list[tuple[float, float, float]]:
    """(t, x, y) samples at the mouse polling rate along a smooth curve through `points`: ONE minimum-jerk speed
    profile for the whole stroke (slow start, faster middle, slow end), a little hand tremor, ends exactly at the
    last point."""
    curve = _spline(points)
    cum = [0.0]
    for a, b in zip(curve, curve[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    length = cum[-1]
    if length < 0.5:
        return [(0.0, curve[-1][0], curve[-1][1])]
    total = max(0.15, length / max(1.0, speed_px_s))
    steps = max(2, int(total * p.mouse_hz))
    out, j = [], 0
    for k in range(1, steps + 1):
        tau = k / steps
        s = length * tau ** 3 * (10 - 15 * tau + 6 * tau * tau)
        while j < len(cum) - 2 and cum[j + 1] < s:
            j += 1
        seg = cum[j + 1] - cum[j] or 1.0
        f = min(1.0, max(0.0, (s - cum[j]) / seg))
        x = curve[j][0] + (curve[j + 1][0] - curve[j][0]) * f
        y = curve[j][1] + (curve[j + 1][1] - curve[j][1]) * f
        out.append((tau * total, x + rng.gauss(0, p.shake_px), y + rng.gauss(0, p.shake_px)))
    t_end = out[-1][0]
    return out[:-1] + [(t_end, curve[-1][0], curve[-1][1])]


class Hands:
    def __init__(self, sink, *, home: Path | None = None, dry_run: bool = False, profile: HumanProfile | None = None,
                 seed: int | None = None, clock: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep, stopped: Callable[[], bool] | None = None,
                 watch_pointer: bool = False) -> None:
        self.sink, self.home, self.dry_run = sink, home, dry_run
        self.watch_pointer = watch_pointer           # step back when someone else moves the mouse between actions
        self._rest: tuple[float, float] | None = None
        self.rng = random.Random(seed)
        self.profile = profile if profile is not None else HumanProfile(miss_p=0.0)
        self.clock, self.sleep = clock, sleep
        self._stopped = stopped or ((lambda: control.stopped(home)) if home is not None else (lambda: False))
        self.human = HumanInput(self.profile, rng=self.rng)
        self.actions = 0

    # ---- bookkeeping --------------------------------------------------------------------------------------
    def check(self) -> None:
        if self._stopped():
            raise Stopped("the owner's stop is on")

    def _log(self, action: str, phase: str, **fields) -> None:
        if self.home is not None:
            control.log_action(self.home, "computer." + action, phase, dry_run=self.dry_run, **fields)

    def _owner_moved_the_mouse(self) -> bool:
        position = getattr(self.sink, "position", None)
        if not (self.watch_pointer and position and self._rest):
            return False
        x, y = position()
        return math.hypot(x - self._rest[0], y - self._rest[1]) > 30

    def _run(self, action: str, fields: dict, body: Callable[[], None]) -> None:
        self.check()
        if self._owner_moved_the_mouse():
            self._log(action, "refused", detail="the pointer was moved by someone else")
            raise Stopped("someone else is using the mouse")
        self._log(action, "start", **fields)
        if not self.dry_run:
            try:
                body()
                position = getattr(self.sink, "position", None)
                self._rest = tuple(position()) if position else None
            except Exception as why:
                self._log(action, "error", detail=f"{type(why).__name__}: {why}")
                raise
        self.actions += 1
        self._log(action, "done")

    def _pointer(self) -> None:
        position = getattr(self.sink, "position", None)
        if position is not None:
            self.human.pointer = cast("tuple[float, float]", tuple(float(v) for v in position()))

    def _play(self, events: list[Event]) -> None:
        """Play timed events on the sink; checks STOP every ~50 ms and lets go of everything if it is set."""
        if not events:
            return
        player = Actuator(self.sink, clock=self.clock, sleep=self.sleep)
        player.submit(events)
        end = max(e.t for e in events)
        last_check = self.clock()
        try:
            while self.clock() <= end:
                player.pump()
                self.sleep(0.002)
                if self.clock() - last_check > 0.05:
                    last_check = self.clock()
                    if self._stopped():
                        raise Stopped("the owner's stop is on")
            player.pump()
        finally:
            player.release_all()

    # ---- actions ------------------------------------------------------------------------------------------
    def move(self, x: float, y: float, width: float = 20.0) -> None:
        def body() -> None:
            self._pointer()
            self._play(self.human.plan(Aim(x, y, width), self.clock()))
        self._run("move", {"x": int(x), "y": int(y)}, body)

    def click(self, x: float, y: float, width: float = 20.0, button: str = "left", clicks: int = 1) -> None:
        def body() -> None:
            self._pointer()
            events = self.human.plan(Aim(x, y, width, click=button), self.clock())
            down = next(e for e in events if e.kind == "button_down")
            up = next(e for e in events if e.kind == "button_up")
            step = (up.t - down.t) + self.rng.uniform(0.05, 0.10)      # release, a short gap, press again
            for n in range(1, clicks):
                events += [Event(down.t + step * n, "button_down", button), Event(up.t + step * n, "button_up", button)]
            self._play(events)
        self._run("click", {"x": int(x), "y": int(y), "button": button, "clicks": clicks}, body)

    def drag(self, points: list[tuple[float, float]], *, button: str = "left", speed_px_s: float = 380.0,
             profile: HumanProfile | None = None) -> None:
        """Press at the first point, follow the polyline smoothly, release at the last. A person draws at about
        200-500 px/s with a gentle speed-up and slow-down; the path passes through every point."""
        if len(points) < 2:
            return

        def body() -> None:
            self._pointer()
            prof = profile or DRAW_PROFILE
            events = self.human.plan(Aim(points[0][0], points[0][1], 6.0), self.clock())
            t0 = events[-1].t + self.rng.uniform(0.05, 0.12)
            events.append(Event(t0, "button_down", button))
            path = stroke_path(points, speed_px_s, self.rng, prof)
            events += [Event(t0 + 0.04 + t, "move_to", round(x), round(y)) for t, x, y in path]
            events.append(Event(t0 + 0.04 + path[-1][0] + 0.03, "button_up", button))
            self.human.pointer = points[-1]
            self._play(events)
        self._run("drag", {"points": len(points), "from": [int(v) for v in points[0]],
                           "to": [int(v) for v in points[-1]]}, body)

    def type_text(self, text: str, speed: float = 1.0) -> None:
        """`speed` > 1 types faster (a pasted-looking file path in a dialog does not need a person's rhythm)."""
        def body() -> None:
            self.sleep(max(0.15, self.rng.gauss(0.3, 0.08)))
            for ch in text:
                self.check()
                if ch in "\r\n":
                    self._tap("enter")
                else:
                    self.sink.type_char(ch)
                gap = min(0.6, max(0.04, self.rng.lognormvariate(math.log(0.11), 0.4)))
                if ch == " " and self.rng.random() < 0.15:
                    gap += self.rng.uniform(0.1, 0.3)
                self.sleep(max(0.012, gap / max(0.1, speed)))
        self._run("type", {"chars": len(text), "text": text[:30], "speed": speed}, body)

    def _tap(self, key: str) -> None:
        pressed = True
        try:
            self.sink.key(key, True)
            self.sleep(self.rng.uniform(0.04, 0.1))
        except BaseException as error:
            pressed = getattr(error, "accepted", None) != 0
            raise
        finally:
            if pressed:
                self._release_key(key)

    def _release_key(self, key: str) -> None:
        release = getattr(self.sink, "release_key", None)
        release(key) if callable(release) else self.sink.key(key, False)

    def key(self, combo: str) -> None:
        parts = [p for p in str(combo).lower().replace(" ", "").split("+") if p]
        if not parts:
            raise ValueError("no key given")
        mods, main = [p for p in parts[:-1]], parts[-1]

        def body() -> None:
            self.sleep(max(0.1, self.rng.gauss(0.2, 0.05)))
            pressed = []
            try:
                for m in mods:
                    try:
                        self.sink.key(m, True)
                    except BaseException as error:
                        if getattr(error, "accepted", None) != 0:
                            pressed.append(m)
                        raise
                    pressed.append(m)
                    self.sleep(self.rng.uniform(0.03, 0.07))
                self._tap(main)
            finally:
                failed = None
                for m in reversed(pressed):
                    try:
                        self.sleep(self.rng.uniform(0.03, 0.07))
                    except BaseException as error:
                        failed = failed or error
                    try:
                        self._release_key(m)
                    except BaseException as error:
                        failed = failed or error
                if failed is not None:
                    raise failed
        self._run("key", {"keys": "+".join(parts)}, body)

    def scroll(self, notches: int, at: tuple[float, float] | None = None) -> None:
        """Positive notches scroll up (away from you). The pointer goes to `at` first, as a person's would."""
        def body() -> None:
            if at is not None:
                self._pointer()
                self._play(self.human.plan(Aim(at[0], at[1], 60.0), self.clock()))
            left, step = abs(int(notches)), (1 if notches > 0 else -1)
            while left > 0:
                burst = min(left, self.rng.randint(1, 3))
                for _ in range(burst):
                    self.sink.wheel(step)
                    self.sleep(self.rng.uniform(0.03, 0.09))
                left -= burst
                self.check()
                self.sleep(self.rng.uniform(0.12, 0.35))
        self._run("scroll", {"notches": int(notches), "at": list(at) if at else None}, body)

    def wait(self, seconds: float) -> None:
        end = self.clock() + max(0.0, seconds)
        while self.clock() < end:
            self.check()
            self.sleep(min(0.1, max(0.0, end - self.clock())))
