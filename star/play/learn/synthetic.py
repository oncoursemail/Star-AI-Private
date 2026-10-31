"""A tiny fake game with a known right answer, for tests and for GPU smoke runs on synthetic data only.

DotGame: a green dot on a grey screen. Turning (A/D or the mouse) moves the view, so the dot slides the other way;
the episode succeeds ("checkpoint") once the dot has stayed centred for `hold` steps. Now and then a red bar
appears at the bottom; it must be jumped (Space) within `hazard_window` steps or the episode fails ("fell").
The scripted player reacts to the bar after a human-like 3-6 step delay and plays randomly with probability `eps`,
so recordings hold both successful and failed episodes - the material filtered behaviour cloning works on.
Nothing here touches the real screen or input.
"""
from __future__ import annotations

import random
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

from .actions import GameSpec
from .adapter import PolicyAction
from .evaluate import Attempt
from .recorder import Recorder


def dot_spec(frame_size: tuple[int, int] = (32, 18), **kw) -> GameSpec:
    return GameSpec("synthetic_dot", keys=("a", "d", "space"), buttons=(), mouse_bins=11, mouse_max=8.0,
                    frame_size=frame_size, stack=2, success=("checkpoint",), failure=("fell",), chat_open=(), **kw)


class DotGame:
    def __init__(self, spec: GameSpec, rng: random.Random, *, speed: float = 1.5, tol: float = 2.0, hold: int = 3,
                 p_hazard: float = 0.04, hazard_window: int = 10, max_steps: int = 80) -> None:
        self.spec, self.rng = spec, rng
        self.speed, self.tol, self.hold, self.p_hazard = speed, tol, hold, p_hazard
        self.hazard_window, self.max_steps = hazard_window, max_steps
        self.w, self.h = spec.frame_size
        self.reset()

    def reset(self) -> None:
        side = self.rng.choice((-1, 1))
        self.x = self.w / 2 + side * self.rng.uniform(self.w * 0.2, self.w * 0.45)
        self.hazard, self.centred, self.t = -1, 0, 0

    @property
    def offset(self) -> float:
        return self.x - self.w / 2

    def frame(self) -> np.ndarray:
        img = np.full((self.h, self.w, 3), 100, dtype=np.uint8)
        cx, cy, r = int(round(self.x)), self.h // 2, max(1, self.h // 9)
        img[max(0, cy - r):cy + r + 1, max(0, cx - r):max(0, cx + r + 1)] = (40, 220, 40)
        if self.hazard >= 0:
            img[self.h - max(2, self.h // 6):, :] = (230, 30, 30)
        return img

    def step(self, a: PolicyAction) -> str:
        """Apply one step of input; returns "checkpoint", "fell", "timeout" or ""."""
        turn = (self.speed if "d" in a.keys else 0.0) - (self.speed if "a" in a.keys else 0.0) + a.dx * 0.5
        self.x = min(self.w - 1.0, max(0.0, self.x - turn))
        self.t += 1
        if self.hazard >= 0:
            if "space" in a.keys:
                self.hazard = -1
            else:
                self.hazard += 1
                if self.hazard > self.hazard_window:
                    return "fell"
        elif self.rng.random() < self.p_hazard:
            self.hazard = 0
        self.centred = self.centred + 1 if abs(self.offset) <= self.tol else 0
        if self.centred >= self.hold:
            return "checkpoint"
        return "timeout" if self.t >= self.max_steps else ""


class ScriptedPlayer:
    """Plays DotGame like a person: turns toward the dot, jumps the bar after 3-6 steps, random with p=eps."""

    def __init__(self, game: DotGame, rng: random.Random, eps: float = 0.2) -> None:
        self.game, self.rng, self.eps = game, rng, eps
        self.seen_hazard_at = -1
        self.react = 4

    def act(self) -> PolicyAction:
        g, r = self.game, self.rng
        if r.random() < self.eps:
            keys = frozenset(k for k in ("a", "d", "space") if r.random() < 0.3)
            return PolicyAction(keys, frozenset(), r.uniform(-8, 8), 0.0)
        keys = set()
        if abs(g.offset) > g.tol:
            keys.add("d" if g.offset > 0 else "a")
        if g.hazard >= 0:
            if self.seen_hazard_at < 0:
                self.seen_hazard_at, self.react = g.t, r.randint(3, 6)
            if g.t - self.seen_hazard_at >= self.react:
                keys.add("space")
        else:
            self.seen_hazard_at = -1
        dx = max(-8.0, min(8.0, g.offset * 0.5)) if abs(g.offset) > g.tol else 0.0
        return PolicyAction(frozenset(keys), frozenset(), dx, 0.0)


def _feed(recorder: Recorder, held: set, action: PolicyAction) -> None:
    """What SinkTap does for STAR's real input: key transitions and mouse movement into the InputState."""
    for key in action.keys - held:
        recorder.state.key(key, True)
    for key in held - action.keys:
        recorder.state.key(key, False)
    recorder.state.move(action.dx, action.dy)
    held.clear()
    held.update(action.keys)


def play(spec: GameSpec, episodes: int, act: Callable[[DotGame, np.ndarray], PolicyAction], *, seed: int = 0,
         recorder: Recorder | None = None, game_kw: dict | None = None) -> list[Attempt]:
    """Run episodes with `act(game, frame_stack)`; optionally record them (frames, input, moments)."""
    rng = random.Random(seed)
    game = DotGame(spec, rng, **(game_kw or {}))
    attempts, held = [], set()
    for _ in range(episodes):
        game.reset()
        frames: deque = deque(maxlen=spec.stack)
        while True:
            img = game.frame()
            while len(frames) < spec.stack - 1:
                frames.append(img)
            frames.append(img)
            if recorder is not None:
                recorder.step(img, game.t / spec.hz)
            stack = np.ascontiguousarray(np.concatenate(list(frames), axis=2).transpose(2, 0, 1))
            action = act(game, stack)
            if recorder is not None:
                _feed(recorder, held, action)
            outcome = game.step(action)
            if outcome:
                if recorder is not None:
                    recorder.step(game.frame(), game.t / spec.hz)     # stores the last frame with its input
                    recorder.mark("reset" if outcome == "timeout" else outcome)
                    _feed(recorder, held, PolicyAction(frozenset(), frozenset()))
                    recorder.cut()                                       # respawn: no stack spans episodes
                attempts.append(Attempt(outcome == "checkpoint", float(outcome == "checkpoint"), game.t / spec.hz,
                                        "" if outcome == "checkpoint" else outcome))
                break
    return attempts


def record_demos(root: Path, spec: GameSpec, episodes: int, *, eps: float = 0.2, who: str = "owner", seed: int = 0,
                 game_kw: dict | None = None) -> Path:
    rng = random.Random(seed + 1000)
    rec = Recorder(spec, consent="synthetic test data", who=who, root=root, notify=lambda line: None,
                   session_id=f"{who}-{seed}").start()
    players: dict[int, ScriptedPlayer] = {}

    def act(game: DotGame, stack) -> PolicyAction:
        player = players.setdefault(id(game), ScriptedPlayer(game, rng, eps))
        return player.act()

    play(spec, episodes, act, seed=seed, recorder=rec, game_kw=game_kw)
    return rec.stop()


def policy_act(controller) -> Callable[[DotGame, np.ndarray], PolicyAction]:
    """A trained PolicyController as a DotGame player (simulated time, so the human toggle limit still applies)."""
    from ..planner import Goal
    from .adapter import PolicyObs
    goal = Goal("play")

    def act(game: DotGame, stack) -> PolicyAction:
        now = game.t / game.spec.hz
        return controller.decide(PolicyObs(game.t, now, stack, stack[-3:].transpose(1, 2, 0)), goal, now)[0]

    return act
