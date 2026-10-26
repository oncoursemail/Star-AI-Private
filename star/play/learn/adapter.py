"""The trained policy as the fast loop's reflex controller (replaces e.g. ObbyController.decide for one game).

  FrameObserver     frame -> 128x72 -> stack of the last k frames (PolicyObs), with grab/shrink timings
  PolicyController  runs the net (fp16 on CUDA), SAMPLES keys and mouse bins (people are not deterministic; VPT
                    samples too) and applies human limits: a key cannot flip faster than `min_toggle_s`, and mouse
                    moves are capped at the 99th percentile speed seen in the recorded human play
  PolicyActor       turns the sampled action into input events: key transitions with a few ms of jitter, the mouse
                    delta spread over the tick with a minimum-jerk (slow-fast-slow) profile and hand tremor
                    (star/play/humanlike.py), played by the existing Actuator (window check in winput.SendInputSink)
The policy's timing is already human: it is cloned from human play, reaction delays included, so no extra reaction
delay is added on top (that would make it slower than the people it learned from).
`reflex_session` wires it into a GameSession (planner, voice moments, emotion) and can record STAR's own play for
self-improvement (improve.py).
"""
from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..humanlike import Actuator, Event, HumanProfile, _min_jerk
from ..planner import Goal
from .actions import GameSpec
from .recorder import shrink

GOALS = {"play": "let your learned reflexes play the game", "wait": "stand still (talking, or waiting)"}


@dataclass
class PolicyObs:
    frame_index: int
    t_capture: float
    stack: np.ndarray                    # (3k, H, W) uint8, oldest first
    image: np.ndarray                    # newest small frame (H, W, 3)
    stage_ms: dict = field(default_factory=dict)


class FrameObserver:
    def __init__(self, source, spec: GameSpec, clock: Callable[[], float] = time.perf_counter) -> None:
        self.source, self.spec, self.clock = source, spec, clock
        self._frames: deque = deque(maxlen=spec.stack)

    def __call__(self) -> PolicyObs | None:
        t0 = self.clock()
        frame = self.source.grab()
        if frame is None:
            return None
        t1 = self.clock()
        small = shrink(frame.image, self.spec.frame_size)
        while len(self._frames) < self.spec.stack - 1:
            self._frames.append(small)                       # first frame: repeat it to fill the stack
        self._frames.append(small)
        stack = np.concatenate(list(self._frames), axis=2).transpose(2, 0, 1)
        t2 = self.clock()
        return PolicyObs(frame.index, frame.t, np.ascontiguousarray(stack), small,
                         {"grab": (t1 - t0) * 1000, "shrink": (t2 - t1) * 1000})


@dataclass(frozen=True)
class PolicyAction:
    keys: frozenset
    buttons: frozenset
    dx: float = 0.0
    dy: float = 0.0


class PolicyController:
    goals = GOALS

    def __init__(self, model, ckpt: dict, *, temperature: float = 1.0, device=None, min_toggle_s: float = 0.06,
                 signal: Callable[[object, float], list[str]] | None = None, rng: random.Random | None = None,
                 speed_cap: float | None = None) -> None:
        import torch
        self.torch = torch
        self.model = model
        self.spec = GameSpec.from_dict(ckpt["spec"])
        self.game = self.spec.game
        self.device = device or next(model.parameters()).device
        self.half = self.device.type == "cuda"
        if self.half:
            self.model.half()
        self.temperature, self.min_toggle_s, self.signal = max(0.05, temperature), min_toggle_s, signal
        self.rng = rng or random.Random()
        cap = speed_cap if speed_cap is not None else float(ckpt.get("stats", {}).get("abs_delta_p99") or 0.0)
        self.speed_cap = cap if cap > 0 else self.spec.mouse_max
        self._on: dict[str, bool] = {}
        self._changed: dict[str, float] = {}
        self.infer_ms: deque = deque(maxlen=500)
        self.last: PolicyAction | None = None

    def probabilities(self, stack: np.ndarray) -> dict[str, np.ndarray]:
        torch = self.torch
        t0 = time.perf_counter()
        with torch.inference_mode():
            x = torch.from_numpy(stack).unsqueeze(0).to(self.device)
            if self.half:
                x = x.half()
            out = self.model(x)
            t = self.temperature
            probs = {"keys": torch.sigmoid(out["keys"].float() / t),
                     "buttons": torch.sigmoid(out["buttons"].float() / t),
                     "mx": torch.softmax(out["mx"].float() / t, -1), "my": torch.softmax(out["my"].float() / t, -1)}
            probs = {k: v[0].cpu().numpy() for k, v in probs.items()}
        self.infer_ms.append((time.perf_counter() - t0) * 1000)
        return probs

    def _gate(self, name: str, want: bool, now: float) -> bool:
        """Human limit: a key or button holds its state for at least min_toggle_s."""
        current = self._on.get(name, False)
        if want != current and now - self._changed.get(name, -1e9) >= self.min_toggle_s:
            self._on[name], self._changed[name] = want, now
            return want
        return current

    def decide(self, obs: PolicyObs, goal: Goal, now: float) -> list:
        if goal.name == "wait":
            for name in list(self._on):
                self._on[name] = False
            self.last = PolicyAction(frozenset(), frozenset())
            return [self.last]
        p = self.probabilities(obs.stack)
        r = self.rng.random
        keys = frozenset(k for k, pk in zip(self.spec.keys, p["keys"]) if self._gate(k, r() < pk, now))
        buttons = frozenset(b for b, pb in zip(self.spec.buttons, p["buttons"])
                            if self._gate("mouse:" + b, r() < pb, now))
        bins = range(self.spec.mouse_bins)
        mx = self.rng.choices(bins, weights=p["mx"].tolist())[0]
        my = self.rng.choices(bins, weights=p["my"].tolist())[0]
        cap = self.speed_cap
        dx = max(-cap, min(cap, self.spec.bin_center(mx)))
        dy = max(-cap, min(cap, self.spec.bin_center(my)))
        self.last = PolicyAction(keys, buttons, dx, dy)
        return [self.last]

    def moments(self, obs) -> list[str]:
        if self.signal is None:
            return []
        return list(self.signal(obs, time.perf_counter()))

    def describe(self, obs) -> str:
        a = self.last
        if a is None:
            return "learned reflexes starting"
        held = ",".join(sorted(a.keys | {"mouse:" + b for b in a.buttons})) or "nothing"
        return f"learned reflexes: holding {held}, turning {a.dx:+.0f}px"


class PolicyActor:
    """Sampled actions -> human-timed events on the Actuator. Keeps its own idea of what is held, so only changes
    are sent; the Actuator releases everything when the session stops."""

    def __init__(self, actuator: Actuator, *, period: float, profile: HumanProfile | None = None,
                 rng: random.Random | None = None, jitter_s: float = 0.012) -> None:
        self.actuator, self.period, self.p = actuator, period, profile or HumanProfile()
        self.rng, self.jitter_s = rng or random.Random(), jitter_s
        self.held: set[str] = set()
        self.buttons: set[str] = set()

    def events(self, action: PolicyAction, now: float) -> list[Event]:
        out: list[Event] = []
        j = lambda: now + self.rng.uniform(0.0, self.jitter_s)  # noqa: E731
        for key in sorted(action.keys - self.held):
            out.append(Event(j(), "key_down", key, None, "key:" + key))
        for key in sorted(self.held - action.keys):
            out.append(Event(j(), "key_up", key, None, "key:" + key))
        for b in sorted(action.buttons - self.buttons):
            out.append(Event(j(), "button_down", b, None, "button"))
        for b in sorted(self.buttons - action.buttons):
            out.append(Event(j(), "button_up", b, None, "button"))
        self.held, self.buttons = set(action.keys), set(action.buttons)
        if action.dx or action.dy:
            steps = max(2, int(self.period * self.p.mouse_hz))
            sent_x = sent_y = 0
            for i in range(1, steps + 1):
                s = _min_jerk(i / steps)
                shake = self.p.shake_px * (1 - i / steps)
                x = round(action.dx * s + (self.rng.gauss(0, shake) if i < steps else 0))
                y = round(action.dy * s + (self.rng.gauss(0, shake) if i < steps else 0))
                if x != sent_x or y != sent_y:
                    out.append(Event(now + self.period * i / steps, "move_rel", x - sent_x, y - sent_y, "policy"))
                    sent_x, sent_y = x, y
        return out

    def __call__(self, actions: list, now: float) -> None:
        for action in actions:
            if isinstance(action, PolicyAction):
                self.actuator.submit(self.events(action, now))


def obby_signal(profile=None) -> Callable[[PolicyObs, float], list[str]]:
    """Roblox obby progress for self-improvement: the ObbyController's colour check for 'standing on a checkpoint
    pad', run on the small policy frame."""
    from ..percept import Percept
    from ..roblox import ObbyController
    watcher = ObbyController(profile)
    detector = watcher.detector()

    def signal(obs: PolicyObs, now: float) -> list[str]:
        h, w = obs.image.shape[:2]
        watcher._note_checkpoint(Percept(obs.frame_index, obs.t_capture, w, h, detector.detect(obs.image)), now)
        return watcher.moments(None)

    return signal


def reflex_session(checkpoint, *, source, sink, brain=None, speak=None, voice_window=None, recorder=None,
                   signal=None, temperature: float = 1.0, device=None):
    """A GameSession whose fast layer is the learned policy. With `recorder` (a started Recorder for the same
    spec) STAR's own play is recorded: frames through TeeSource, her inputs through SinkTap, moments as markers."""
    from ..loop import FastLoop
    from ..session import _wire
    from .policy import load_policy
    from .recorder import SinkTap, TeeSource
    model, ckpt = load_policy(checkpoint, device)
    controller = PolicyController(model, ckpt, temperature=temperature, signal=signal)
    spec = controller.spec
    if recorder is not None:
        source, sink = TeeSource(source, recorder), SinkTap(sink, recorder.state)
    actuator = Actuator(sink)
    fast = FastLoop(FrameObserver(source, spec), controller, PolicyActor(actuator, period=1.0 / spec.hz),
                    hz=spec.hz, goal=Goal("play"))
    if recorder is not None:
        fast.on_moment.append(recorder.mark)
    return _wire(fast, brain, speak, voice_window, spec.game, actuator)
