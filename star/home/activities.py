"""Activity registry: what STAR can do for each interest, and how other packages plug in.

Built in: one brain session per creative interest (game_making, drawing, music, research, practice).
Plug-ins: any module in PLUGIN_MODULES (star.games, star.social, star.senses, being built in their own branches)
that defines `register_home_activities(registry)` adds activities, for example
    registry.register("play roblox", "play_games", play, "play Roblox on her own account")
    registry.register("listen to music", "music", listen, "listen through the system audio capture")
An activity is `run(ctx) -> dict` with ok, verified (bool, from the activity's own check), summary, evidence (list),
and optional failures, goal_done. `ctx` is Context below. An interest with no activity is never picked.

GPU budget ("game mode", her PC has one 8 GB card): an activity declares `gpu_mb`, the video memory it needs on this
PC (brain sessions run on server 1: 0). While one of config `game_processes` runs, an activity is eligible only if
free video memory minus `gpu_mb` stays at or above `game_reserve_mb`, so her game keeps enough. Outside game mode it
needs `gpu_mb` free. GpuProbe reads nvidia-smi and the process list; tests pass a fake.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import subprocess
from pathlib import Path
from typing import Callable

from . import brain

# Each one is optional: a package that is not installed (star.computer, star.watch, star.vtuber are built in their own branches) is
# skipped. A package that defines `register_home_activities` registers itself; star.social, star.play and star.senses
# are wired by star.home.plugins (they predate this hook).
PLUGIN_MODULES = ("star.games", "star.social", "star.play", "star.senses", "star.computer", "star.watch", "star.art_studio",
                  "star.vtuber", "star.vtuber.modes", "star.home.streamchat")
BUILTIN_BRIEFS = {
    "game_making": "make or improve a small game and play-test it",
    "drawing": "draw or animate something and save it to your gallery folder",
    "music": "compose or arrange music and save the audio",
    "research": "research a topic and write notes with sources",
    "practice": "practice something you failed at before",
}


class _NeverInterrupt:
    reason = ""

    def is_set(self) -> bool:
        return False


@dataclass
class Context:
    """What an activity gets. `interrupt` is set when something needs her (a friend's message, a call): look at it
    between steps and return {"paused": True, "resume_state": {...}} to stop cleanly; the loop serves what is waiting
    and calls the activity again with `resume_state`. `situation.in_moment` tells the scheduler a round is running."""
    home: Path
    config: dict
    executor: object
    life: object
    chat: Callable | None
    interest: str
    goal: dict | None
    practice_topic: str = ""
    interrupt: object = field(default_factory=lambda: _NeverInterrupt())
    situation: object = None
    resume_state: dict = field(default_factory=dict)
    resumed: bool = False


@dataclass
class Activity:
    name: str
    interest: str
    run: Callable[[Context], dict]
    about: str = ""
    gpu_mb: int = 0
    needs_brain: bool = False        # left out while no brain is configured, so a missing brain records no failures


@dataclass
class Registry:
    items: dict[str, Activity] = field(default_factory=dict)
    plugin_errors: dict[str, str] = field(default_factory=dict)
    handlers: dict[str, Callable] = field(default_factory=dict)      # "discord:message" -> handler(incoming, ctx) -> dict
    situations: dict[str, str] = field(default_factory=dict)          # interest -> idle | game | video | work
    runtime: object = None                                            # star.home.runtime.Runtime, for adapters

    def register(self, name: str, interest: str, run: Callable[[Context], dict], about: str = "",
                 gpu_mb: int = 0, needs_brain: bool = False) -> None:
        if not callable(run):
            raise TypeError("run must be callable")
        self.items[name] = Activity(name, interest, run, about, max(0, int(gpu_mb)), bool(needs_brain))

    def register_handler(self, route: str, handler: Callable) -> None:
        """A handler for something that arrives while she lives her day ("discord:message", "discord:call", ...)."""
        if not callable(handler):
            raise TypeError("handler must be callable")
        self.handlers[route] = handler

    def interests(self, eligible: list[Activity] | None = None) -> set[str]:
        return {a.interest for a in (self.items.values() if eligible is None else eligible)}

    def for_interest(self, interest: str, eligible: list[Activity] | None = None) -> list[Activity]:
        return [a for a in (self.items.values() if eligible is None else eligible) if a.interest == interest]

    def eligible(self, probe, config: dict) -> tuple[list[Activity], str]:
        """Activities that fit the GPU budget now, and a note on game mode ("" when not in game mode)."""
        if not any(a.gpu_mb > 0 for a in self.items.values()):
            return list(self.items.values()), ""
        free = probe.free_mb()
        game = probe.game_running(config.get("game_processes", GAME_PROCESSES))
        reserve = int(config.get("game_reserve_mb", 5000)) if game else 0
        fits = [a for a in self.items.values() if a.gpu_mb == 0 or (free is not None and free - a.gpu_mb >= reserve)]
        return fits, (f"game mode ({game}): keeping {reserve} MB of video memory free" if game else "")


GAME_PROCESSES = ("RobloxPlayerBeta.exe", "javaw.exe", "Minecraft.Windows.exe", "RobloxStudioBeta.exe")


class GpuProbe:  # pragma: no cover - reads the real card and process list on the PC
    def free_mb(self) -> int | None:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return int(out.split()[0])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return None

    def game_running(self, names) -> str:
        try:
            out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
        except (OSError, subprocess.SubprocessError):
            return ""
        return next((n for n in names if f'"{n.lower()}"' in out), "")


def brain_activity(brief: str) -> Callable[[Context], dict]:
    def run(ctx: Context) -> dict:
        if ctx.chat is None:
            return {"ok": False, "verified": False, "summary": "no brain connection", "evidence": [],
                    "failures": ["brain: not configured"]}
        text = brief + (f"; today: {ctx.practice_topic}" if ctx.practice_topic else "")
        return brain.run_session(ctx.chat, ctx.executor, ctx.life, interest=ctx.interest, brief=text, goal=ctx.goal,
                                 max_steps=int(ctx.config.get("max_steps", 12)),
                                 session_minutes=float(ctx.config.get("session_minutes", 20)),
                                 stop=ctx.interrupt.is_set,
                                 recall_history=ctx.config.get("life_recall_enabled") is True)
    return run


def _adapter(module_name: str):
    from . import plugins
    return plugins.ADAPTERS.get(module_name)


def default_registry(plugins: tuple[str, ...] = PLUGIN_MODULES, runtime=None) -> Registry:
    registry = Registry(runtime=runtime)
    for interest, brief in BUILTIN_BRIEFS.items():
        registry.register(interest, interest, brain_activity(brief), brief, needs_brain=True)
    for module_name in plugins:
        try:
            module = importlib.import_module(module_name)
        except ImportError as why:
            if why.name and not module_name.startswith(why.name):
                registry.plugin_errors[module_name] = f"ImportError: {why}"      # installed, but one of its needs is missing
            continue                     # not installed yet: its interests stay unpicked
        hook = getattr(module, "register_home_activities", None) or _adapter(module_name)
        if hook is None:
            continue
        try:
            hook(registry)
        except Exception as why:         # one broken plug-in must not stop her other activities
            registry.plugin_errors[module_name] = f"{type(why).__name__}: {why}"
    return registry
