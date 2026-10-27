"""What one game's controls look like to a cloned policy: which keys and buttons, how the mouse is binned, which
game moments count as success or failure. Pure Python (no numpy), so the label format is testable anywhere.

Labels per step (one step = 1/hz s, 20 Hz by default like VPT):
  keys[i]     1 if key i was down at the step or pressed during it (taps shorter than a step still count)
  buttons[j]  the same for mouse buttons
  mx, my      the mouse movement summed over the step, as a bin index: mu-law ("foveated") bins, fine near zero and
              coarse for big flicks (VPT: 11 bins per axis; CS:GO behavioural cloning: 19 x 13)
Only keys in `keys` are ever recorded: typing in chat, passwords and every other key are not seen by the label.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class GameSpec:
    game: str
    keys: tuple[str, ...]
    buttons: tuple[str, ...] = ()
    mouse_bins: int = 11                 # odd, so the middle bin is "no movement"
    mouse_max: float = 160.0             # |pixels per step| that maps to the outer bin (bigger moves are clipped)
    mu: float = 12.0                     # mu-law strength: higher = finer bins near zero
    hz: float = 20.0
    frame_size: tuple[int, int] = (128, 72)          # width, height stored and fed to the policy
    stack: int = 3                       # frames the policy sees (newest last): motion needs more than one
    success: tuple[str, ...] = ("checkpoint", "objective", "round_won", "task_done")
    failure: tuple[str, ...] = ("death", "round_lost", "fell")
    chat_open: tuple[str, ...] = ("slash", "/", "enter", "t")   # a press of one of these pauses recording ...
    chat_close: tuple[str, ...] = ("enter", "escape", "esc")    # ... until one of these (chat text never recorded)
    window: str = ""                     # part of the game window title (record and act only in that window)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> GameSpec:
        known = {f for f in cls.__dataclass_fields__}
        clean: dict[str, Any] = {k: tuple(v) if isinstance(v, list) else v for k, v in data.items() if k in known}
        return cls(**clean)

    # ---- mouse bins ------------------------------------------------------------------------------------------
    def mouse_bin(self, delta: float) -> int:
        half = self.mouse_bins // 2
        x = max(-1.0, min(1.0, delta / self.mouse_max))
        v = math.copysign(math.log1p(self.mu * abs(x)) / math.log1p(self.mu), x)
        return int(round(v * half)) + half

    def bin_center(self, index: int) -> float:
        half = self.mouse_bins // 2
        v = (index - half) / half
        return math.copysign((math.expm1(abs(v) * math.log1p(self.mu)) / self.mu) * self.mouse_max, v)

    @property
    def still_bin(self) -> int:
        return self.mouse_bins // 2


PRESETS = {
    # Roblox obby: walk, strafe, jump; the default camera turns while the right button is held.
    "roblox_obby": GameSpec("roblox_obby", keys=("w", "a", "s", "d", "space"), buttons=("right",),
                            window="Roblox", mouse_max=120.0),
    # Minecraft through the real client (not Mineflayer): move, jump, sneak, sprint, inventory, hotbar 1-4.
    "minecraft": GameSpec("minecraft", keys=("w", "a", "s", "d", "space", "shift", "ctrl", "e", "1", "2", "3", "4"),
                          buttons=("left", "right"), window="Minecraft", chat_open=("t", "slash", "/"),
                          success=("task_done", "objective"), failure=("death",)),
}


def spec_for(game: str, **overrides) -> GameSpec:
    base = PRESETS.get(game) or GameSpec(game, keys=("w", "a", "s", "d", "space"), buttons=("left", "right"))
    return GameSpec(**{**base.to_dict(), **overrides}) if overrides else base


@dataclass
class StepLabel:
    keys: tuple[int, ...]
    buttons: tuple[int, ...]
    mx: int
    my: int
    dx: float = 0.0                      # raw pixels (kept for stats: p99 speed caps STAR's own moves)
    dy: float = 0.0

    @property
    def idle(self) -> bool:
        return not any(self.keys) and not any(self.buttons) and self.dx == 0 and self.dy == 0


@dataclass
class InputState:
    """Collects input events between steps (from the owner's real keyboard/mouse or from STAR's own actuator) and
    turns them into one StepLabel per step. Thread-safe enough for one writer thread and one reader thread: the
    reader swaps the accumulators under the GIL."""
    spec: GameSpec
    down: set = field(default_factory=set)
    pressed: set = field(default_factory=set)      # went down since the last step
    dx: float = 0.0
    dy: float = 0.0
    chat: bool = False                             # chat box open: nothing is labelled until it closes
    pointer: tuple[float, float] | None = None

    def key(self, name: str, down: bool) -> None:
        name = name.lower()
        if down and name not in self.down:
            if self.chat and name in self.spec.chat_close:
                self.chat = False
                return
            if not self.chat and name in self.spec.chat_open and name not in self.spec.keys:
                self.chat = True
                self.down.clear()
                self.pressed.clear()
                return
        mouse = name.startswith("mouse:")
        if self.chat or (name[6:] not in self.spec.buttons if mouse else name not in self.spec.keys):
            return
        if down:
            if name not in self.down:
                self.pressed.add(name)
            self.down.add(name)
        else:
            self.down.discard(name)

    def button(self, name: str, down: bool) -> None:
        self.key("mouse:" + name.lower(), down)    # own namespace: the "left" button is not the left arrow key

    def move(self, dx: float, dy: float) -> None:
        if not self.chat:
            self.dx += dx
            self.dy += dy

    def move_to(self, x: float, y: float) -> None:
        if self.pointer is not None:
            self.move(x - self.pointer[0], y - self.pointer[1])
        self.pointer = (x, y)

    def take(self) -> StepLabel | None:
        """The label for the step that just ended, or None while the chat box is open."""
        down, pressed, dx, dy = set(self.down), self.pressed, self.dx, self.dy
        self.pressed, self.dx, self.dy = set(), 0.0, 0.0
        if self.chat:
            return None
        active = down | pressed
        s = self.spec
        return StepLabel(tuple(int(k in active) for k in s.keys), tuple(int("mouse:" + b in active) for b in s.buttons),
                         s.mouse_bin(dx), s.mouse_bin(dy), dx, dy)
