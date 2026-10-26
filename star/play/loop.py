"""The two-tier play loop.

  FAST (10-30 Hz, this PC): observe (screen frame -> detector, or Mineflayer state) -> controller.decide(goal)
       -> act (human-like input through the Actuator, or Mineflayer commands). Never waits for a language model.
  SLOW (~1 Hz, or at once after a game moment): situation -> planner -> new goal + maybe one spoken line.
       The spoken line goes to `speak`, the voice loop's queue (star/senses / star/voice), which talks on its own
       thread, so she plays, listens and talks at the same time.
Game moments (checkpoint, death, ...) the controller notices go straight to `on_moment` listeners: the voice
context window (star.voice.game_context.GameMomentWindow), the emotion engine, and the slow loop (wakes it).
Every tick records stage timings; `LatencyStats.summary()` gives p50/p95 per stage.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .humanlike import Actuator, HumanInput
from .planner import Goal, LLMPlanner, Situation


class Controller(Protocol):
    game: str
    goals: dict[str, str]

    def decide(self, obs, goal: Goal, now: float) -> list: ...

    def moments(self, obs) -> list[str]: ...

    def describe(self, obs) -> str: ...


@dataclass
class LatencyStats:
    keep: int = 2000
    samples: dict[str, deque] = field(default_factory=dict)

    def add(self, stage: str, ms: float) -> None:
        self.samples.setdefault(stage, deque(maxlen=self.keep)).append(ms)

    def summary(self) -> dict[str, dict[str, float]]:
        out = {}
        for stage, values in self.samples.items():
            ordered = sorted(values)
            if not ordered:
                continue
            pick = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]  # noqa: E731
            out[stage] = {"n": len(ordered), "p50": round(pick(0.5), 3), "p95": round(pick(0.95), 3),
                          "max": round(ordered[-1], 3)}
        return out


class InputActor:
    """Screen games: intents -> human-like timed events -> Actuator (which plays them on its own thread)."""

    def __init__(self, human: HumanInput, actuator: Actuator) -> None:
        self.human, self.actuator = human, actuator

    def __call__(self, intents: list, now: float) -> None:
        for intent in intents:
            self.actuator.submit(self.human.plan(intent, now))


class FastLoop:
    def __init__(self, observe: Callable[[], object], controller: Controller, act: Callable[[list, float], None], *,
                 hz: float = 20.0, goal: Goal | None = None, clock: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.observe, self.controller, self.act = observe, controller, act
        self.period = 1.0 / hz
        self.clock, self._sleep = clock, sleep
        self._goal = goal or Goal(next(iter(controller.goals)))
        self._lock = threading.Lock()
        self.latest = None
        self.stats = LatencyStats()
        self.ticks = 0
        self.overruns = 0
        self.on_moment: list[Callable[[str, float], None]] = []
        self._stop = threading.Event()

    @property
    def goal(self) -> Goal:
        with self._lock:
            return self._goal

    def set_goal(self, goal: Goal) -> None:
        with self._lock:
            self._goal = goal

    def tick(self) -> None:
        t0 = self.clock()
        obs = self.observe()
        t1 = self.clock()
        if obs is None:
            self.stats.add("observe", (t1 - t0) * 1000)
            return
        self.latest = obs
        actions = self.controller.decide(obs, self.goal, t1)
        t2 = self.clock()
        if actions:
            self.act(actions, t2)
        t3 = self.clock()
        for kind in self.controller.moments(obs):
            for listener in list(self.on_moment):
                listener(kind, t3)
        self.ticks += 1
        self.stats.add("observe", (t1 - t0) * 1000)
        self.stats.add("decide", (t2 - t1) * 1000)
        self.stats.add("act", (t3 - t2) * 1000)
        for stage, ms in (getattr(obs, "stage_ms", None) or {}).items():
            self.stats.add(stage, ms)
        captured = getattr(obs, "t_capture", None)
        if captured is not None:
            self.stats.add("capture_to_action", (t3 - captured) * 1000)
        self.stats.add("tick", (t3 - t0) * 1000)

    def run(self) -> None:
        next_at = self.clock()
        while not self._stop.is_set():
            self.tick()
            next_at += self.period
            wait = next_at - self.clock()
            if wait > 0:
                self._sleep(wait)
            else:                                   # fell behind: skip ahead instead of bursting to catch up
                self.overruns += 1
                next_at = self.clock()

    def stop(self) -> None:
        self._stop.set()


class SlowLoop:
    def __init__(self, planner: LLMPlanner, fast: FastLoop, *, speak: Callable[[str], bool] | None = None,
                 mood: Callable[[], str] | None = None, period: float = 1.0, min_say_gap_s: float = 6.0,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self.planner, self.fast, self.speak, self.mood = planner, fast, speak, mood
        self.period, self.min_say_gap_s, self.clock = period, min_say_gap_s, clock
        self._moments: deque[str] = deque(maxlen=12)
        self._chat: deque[tuple[str, str]] = deque(maxlen=12)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.last_said = -1e9
        self.said: list[str] = []
        fast.on_moment.append(self.moment)

    def moment(self, kind: str, now: float) -> None:
        self._moments.append(kind)
        self._wake.set()

    def heard_chat(self, author: str, text: str) -> None:
        self._chat.append((author, text))
        self._wake.set()

    def situation(self) -> Situation:
        obs = self.fast.latest
        for line in getattr(obs, "chat", None) or []:
            if (line.author, line.text) not in self._chat:
                self._chat.append((line.author, line.text))
        mood = ""
        if self.mood is not None:
            try:
                mood = self.mood() or ""
            except Exception:                       # emotion is optional; play goes on without it
                mood = ""
        return Situation(self.fast.controller.game, self.fast.goal,
                         self.fast.controller.describe(obs) if obs is not None else "",
                         tuple(self._moments), tuple(self._chat), mood)

    def tick(self) -> None:
        situation = self.situation()
        self._moments.clear()
        plan = self.planner.plan(situation)
        if plan is None:
            return
        if plan.goal != self.fast.goal:
            self.fast.set_goal(plan.goal)
        now = self.clock()
        if plan.say and self.speak is not None and now - self.last_said >= self.min_say_gap_s:
            if self.speak(plan.say) is not False:
                self.last_said = now
                self.said.append(plan.say)
        self._chat.clear()

    def run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.period)
            self._wake.clear()
            if not self._stop.is_set():
                self.tick()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()


def voice_context_listener(window, *, session_id: str, game_id: str) -> Callable[[str, float], None]:
    """Feeds moments to the voice call's GameMomentWindow (star/voice/game_context.py) as unverified visual
    inferences, so what she says in the call knows what just happened in the game."""
    from ..voice.game_context import GameMoment
    counter = {"n": 0}

    def listen(kind: str, now: float) -> None:
        counter["n"] += 1
        seen = time.monotonic()                     # the window's clock (the play loop runs on perf_counter)
        try:
            window.add(GameMoment(session_id, f"e{counter['n']}", game_id, kind, seen, source="vision_inference"))
        except ValueError:
            pass                                    # a kind the voice context does not know: skip it

    return listen


def emotion_listener() -> Callable[[str, float], None]:
    """Game moments -> star.emotion events when that module is installed (it is built in its own branch)."""
    try:
        from .. import emotion                       # type: ignore[attr-defined]
    except ImportError:
        return lambda kind, now: None
    feel = {"death": ("task_failure", 0.5), "round_lost": ("task_failure", 0.5), "checkpoint": ("task_success", 0.4),
            "objective": ("task_success", 0.7), "round_won": ("task_success", 0.8),
            "elimination": ("task_success", 0.3)}

    def listen(kind: str, now: float) -> None:
        if kind in feel:
            event, strength = feel[kind]
            try:
                emotion.on_event(event, strength=strength, detail=f"game: {kind}", only_if_enabled=True)
            except Exception:                    # never let a mood problem stop play
                pass

    return listen


class GameSession:
    """Runs the actuator, the fast loop and the slow loop on their own threads; `stop()` releases every key."""

    def __init__(self, fast: FastLoop, slow: SlowLoop | None = None, actuator: Actuator | None = None) -> None:
        self.fast, self.slow, self.actuator = fast, slow, actuator
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for name, target in (("actuator", self.actuator and self.actuator.run), ("fast", self.fast.run),
                             ("slow", self.slow and self.slow.run)):
            if target:
                thread = threading.Thread(target=target, name=f"play-{name}", daemon=True)
                thread.start()
                self._threads.append(thread)

    def stop(self, timeout: float = 3.0) -> None:
        for part in (self.slow, self.fast, self.actuator):
            if part is not None:
                part.stop()
        for thread in self._threads:
            thread.join(timeout)
        self._threads.clear()

    def report(self) -> dict:
        out = {"ticks": self.fast.ticks, "overruns": self.fast.overruns, "goal": self.fast.goal.name,
               "latency_ms": self.fast.stats.summary()}
        if self.slow is not None:
            out["planner"] = {"calls": self.slow.planner.calls, "failures": self.slow.planner.failures,
                              "said": list(self.slow.said[-5:])}
        if self.actuator is not None:
            out["events_fired"] = self.actuator.fired
        return out
