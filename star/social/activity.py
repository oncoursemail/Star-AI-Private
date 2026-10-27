"""The plug between social/game activities and STAR's PC runtime (star-home).

star-home's activity scheduler and elevated host agent were not merged when this was written, so this module defines
the two small protocols it needs; star-home registers what `available_activities()` returns and passes its host agent.
  Activity:  name, ready() -> (bool, why), step() -> StepResult (one short turn, a few seconds), stop()
  HostAgent: screen + keyboard/mouse of her PC (focus_window, foreground_title, screenshot, key, type_text, hold,
             open_uri). Inputs go only to the window the activity checked is in front.
Settings (nonsecret) live in <app data>/social/settings.json; no account passwords anywhere: her accounts are
already signed in on her PC (Discord, Roblox) or use the Minecraft launcher's device-code sign-in done once by the owner.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable


@dataclass(frozen=True)
class StepResult:
    ok: bool
    note: str
    acted: bool = False          # she sent something or moved
    details: dict = field(default_factory=dict)


@runtime_checkable
class Activity(Protocol):
    name: str

    def ready(self) -> tuple[bool, str]: ...

    def step(self) -> StepResult: ...

    def stop(self) -> None: ...


@runtime_checkable
class HostAgent(Protocol):
    def focus_window(self, title: str) -> bool: ...

    def foreground_title(self) -> str: ...

    def screenshot(self) -> Path: ...

    def key(self, combo: str) -> None: ...

    def type_text(self, text: str) -> None: ...

    def hold(self, key: str, seconds: float) -> None: ...

    def open_uri(self, uri: str) -> None: ...


class HumanPace:
    """Reading, thinking and typing at a person's speed (also keeps her far from anything that looks automated)."""

    def __init__(self, *, cps: float = 7.0, max_typing_s: float = 20.0, sleep: Callable[[float], None] = time.sleep,
                 rng: random.Random | None = None) -> None:
        self.cps, self.max_typing_s, self._sleep = cps, max_typing_s, sleep
        self._rng = rng or random.Random()

    def read(self, incoming: str) -> None:
        self._sleep(min(6.0, 0.8 + len(incoming) / 40.0) * self._rng.uniform(0.8, 1.3))

    def type(self, host: HostAgent, text: str) -> None:
        """Types in word chunks with small pauses; long messages speed up so one never takes over max_typing_s."""
        words = text.split(" ")
        cps = max(self.cps, len(text) / self.max_typing_s)
        chunk: list[str] = []
        for index, word in enumerate(words):
            chunk.append(word)
            if len(chunk) >= self._rng.randint(2, 4) or index == len(words) - 1:
                piece = " ".join(chunk) + ("" if index == len(words) - 1 else " ")
                host.type_text(piece)
                self._sleep(len(piece) / cps * self._rng.uniform(0.7, 1.3))
                chunk = []


_JSON = re.compile(r"\{.*\}", re.S)


def parse_json(text: str) -> dict:
    """The first JSON object in a model's answer ({} when there is none)."""
    match = _JSON.search(text or "")
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def vision_reader(question: str, *, settings=None, max_tokens: int = 500) -> Callable[[Path], dict]:
    """A screen reader: screenshot -> JSON dict, through STAR's image model (star.vision.ask)."""
    def read(png: Path) -> dict:
        from ..desktop_core import Settings, app_data
        from ..vision import ask
        chosen = settings or Settings.load(app_data() / "settings.json")
        return parse_json(ask(chosen, question, [png], max_tokens=max_tokens, timeout=60.0).text)
    return read


def settings_path() -> Path:
    from ..desktop_core import app_data
    return app_data() / "social" / "settings.json"


DEFAULT_SETTINGS = {
    "my_names": ["Star"],
    "discord": {"enabled": False, "window_title": "Discord", "friend_requests": False},
    "roblox": {"enabled": False, "experiences": [],        # [{"place_id": 123, "name": "...", "weight": 1, "kids": false}]
               "friend_requests": False},                   # the friend-request desk (UI clicks); off until the owner checks it
    "minecraft": {"enabled": False, "servers": []},         # see star/games/minecraft.py MinecraftServer
    "friends": {},                                          # daily caps, e.g. {"roblox": {"accept": 5, "send": 2, "ask": 2}}
}


def load_settings(path: Path | None = None) -> dict:
    target = Path(path) if path else settings_path()
    data = json.loads(json.dumps(DEFAULT_SETTINGS))
    if target.exists():
        loaded = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{target} must hold a JSON object")
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                data[key].update(value)
            else:
                data[key] = value
    return data


def available_activities(host: HostAgent, *, settings: dict | None = None, chat=None) -> list[Activity]:
    """The activities switched on in settings, ready for star-home's scheduler."""
    cfg = settings or load_settings()
    if chat is None:
        from .chat import SocialChat
        from .friends import FriendMemory
        chat = SocialChat(FriendMemory(), my_names=[str(n) for n in cfg.get("my_names") or ["Star"]])
        chat.requests.caps = {k: {**v, **((cfg.get("friends") or {}).get(k) or {})} for k, v in chat.requests.caps.items()}
    names = [str(n) for n in cfg.get("my_names") or ["Star"]]
    out: list[Activity] = []
    if cfg["discord"].get("enabled"):
        from .discord_desktop import DiscordDesktop
        out.append(DiscordDesktop(host, chat, my_names=names, window_title=cfg["discord"].get("window_title", "Discord")))
    for platform in ("roblox", "discord"):
        if cfg[platform].get("enabled") and cfg[platform].get("friend_requests"):
            from .requests import FriendDesk
            out.append(FriendDesk(host, chat.requests, platform, window_title=cfg[platform].get("window_title")))
    if cfg["roblox"].get("enabled") and cfg["roblox"].get("experiences"):
        from ..games.roblox import Experience, RobloxPlay
        out.append(RobloxPlay(host, chat, [Experience(**e) for e in cfg["roblox"]["experiences"]], my_names=names))
    if cfg["minecraft"].get("enabled"):
        from ..games.minecraft import MinecraftPlay, MinecraftServer
        servers = [MinecraftServer(**s) for s in cfg["minecraft"].get("servers") or []]
        if servers:
            out.append(MinecraftPlay(chat, servers[0], my_names=names))
    return out
