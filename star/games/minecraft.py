"""Minecraft: a Mineflayer client (star/games/mineflayer/bot.js) on servers that allow bots, her own world first.

The Node process speaks JSON lines: events out (spawn, chat, whisper, done, kicked, end, auth_code, error) and
commands in (chat, whisper, follow, stop, gather, build_pillar, wander). Python decides: chat that addresses her (her
name, a whisper, or a quiet server) goes through SocialChat; friends can ask her to follow, stop, gather or build;
when nobody needs her she works on her own goals (gather wood, build a little pillar, wander).
Sign-in: "offline" for her own LAN world; "microsoft" uses Minecraft's device-code sign-in (the owner approves it
once in a browser; the code is shown as an auth_code event); tokens stay in Mineflayer's cache folder, never here.
No hacks: plain player movement and actions (no fly, reach, x-ray or auto-combat).
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..social import rules
from ..social.activity import StepResult
from ..social.chat import SocialChat

BOT_JS = Path(__file__).with_name("mineflayer") / "bot.js"
IDLE_GOAL_S = 90.0
QUIET_SERVER = 3                   # with this many players or fewer, every chat line is for everyone (her too)

GOALS = (("gather", {"block": "oak_log", "count": 4}, 3.0),
         ("build_pillar", {"height": 4}, 1.0),
         ("wander", {"distance": 16}, 2.0))

_FOLLOW = re.compile(r"\b(?:follow\s+me|come\s+(?:here|with\s+me)|come\s+to\s+me)\b", re.I)
_STOP = re.compile(r"\b(?:stop|stay(?:\s+here)?|wait(?:\s+here)?)\b", re.I)
_GATHER = re.compile(r"\b(?:get|gather|collect|chop|mine)\s+(?:some\s+)?(wood|logs?|stone|dirt|sand|coal)\b", re.I)
_BUILD = re.compile(r"\bbuild\s+(?:a\s+|something|us\s+)?(?:pillar|tower)?\b", re.I)
_BLOCKS = {"wood": "oak_log", "log": "oak_log", "logs": "oak_log", "stone": "stone", "dirt": "dirt",
           "sand": "sand", "coal": "coal_ore"}


@dataclass(frozen=True)
class MinecraftServer:
    name: str
    host: str
    port: int = 25565
    username: str = "Star"
    auth: str = "offline"          # offline (her own world/LAN) | microsoft (device-code sign-in, token cache)
    version: str = ""              # '' = let Mineflayer detect
    allows_bots: bool = False      # set True only for her own server or one whose rules allow bots


class Transport(Protocol):
    def send(self, command: dict) -> None: ...

    def poll(self) -> list[dict]: ...

    def close(self) -> None: ...


class NodeTransport:
    """bot.js as a hidden, below-normal-priority child process; events read on a thread."""

    def __init__(self, server: MinecraftServer, *, node: str = "node", auth_cache: Path | None = None) -> None:
        if auth_cache is None:
            from ..desktop_core import app_data
            auth_cache = app_data() / "social" / "minecraft-auth"
        auth_cache.mkdir(parents=True, exist_ok=True)
        config = {"host": server.host, "port": server.port, "username": server.username, "auth": server.auth,
                  "version": server.version, "profilesFolder": str(auth_cache)}
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        self._proc = subprocess.Popen([node, str(BOT_JS)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, encoding="utf-8", creationflags=flags,
                                      cwd=str(BOT_JS.parent), env={**os.environ, "STAR_MC_CONFIG": json.dumps(config)})
        self._events: deque[dict] = deque(maxlen=500)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self._proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                self._events.append(event)
        self._events.append({"type": "end", "reason": "process exited"})

    def send(self, command: dict) -> None:
        if self._proc.poll() is None:
            self._proc.stdin.write(json.dumps(command) + "\n")
            self._proc.stdin.flush()

    def poll(self) -> list[dict]:
        out = []
        while self._events:
            out.append(self._events.popleft())
        return out

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()


class MinecraftPlay:
    name = "minecraft"

    def __init__(self, chat: SocialChat, server: MinecraftServer, *, my_names: list[str] | None = None,
                 transport_factory: Callable[[MinecraftServer], Transport] | None = None,
                 pacer: rules.Pacer | None = None, rng: random.Random | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.chat, self.server = chat, server
        self.my_names = [n.lower() for n in (my_names or ["Star"])]
        self._factory = transport_factory or NodeTransport
        self.pacer = pacer or rules.Pacer(min_gap_s=3.0, per_minute=8)
        self._rng = rng or random.Random()
        self._clock = clock
        self.transport: Transport | None = None
        self.players = 0
        self.busy_until = 0.0
        self.last_activity = 0.0
        self.following = ""
        self.auth_code: dict | None = None
        self.log: deque[str] = deque(maxlen=50)

    def ready(self) -> tuple[bool, str]:
        if not self.server.allows_bots:
            return False, f"{self.server.name} is not marked as allowing bots (allows_bots)"
        if self._factory is NodeTransport and not (BOT_JS.parent / "node_modules" / "mineflayer").is_dir():
            return False, "Mineflayer is not installed (npm install in star/games/mineflayer)"
        return True, "ok"

    def start(self) -> StepResult:
        ok, why = self.ready()
        if not ok:
            return StepResult(False, why)
        self.transport = self._factory(self.server)
        self.last_activity = self._clock()
        return StepResult(True, f"joining {self.server.name}", acted=True)

    def stop(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None

    def _send(self, command: dict) -> None:
        if self.transport is not None:
            self.transport.send(command)
            self.last_activity = self._clock()

    def say(self, text: str, *, to: str = "") -> bool:
        if not text or not self.pacer.allow(to or "public", text):
            return False
        self._send({"cmd": "whisper", "username": to, "text": text} if to else {"cmd": "chat", "text": text})
        self.pacer.sent(to or "public", text)
        return True

    def step(self) -> StepResult:
        if self.transport is None:
            return self.start()
        notes: list[str] = []
        for event in self.transport.poll():
            note = self.on_event(event)
            if note:
                notes.append(note)
        if self.transport is None:
            return StepResult(False, "; ".join(notes) or "disconnected")
        now = self._clock()
        if not self.following and now >= self.busy_until and now - self.last_activity > IDLE_GOAL_S:
            cmd, args, _ = self._rng.choices(GOALS, weights=[g[2] for g in GOALS], k=1)[0]
            self._send({"cmd": cmd, **args})
            self.busy_until = now + 60
            notes.append(f"own goal: {cmd}")
        return StepResult(True, "; ".join(notes) or "playing", acted=bool(notes))

    def on_event(self, event: dict) -> str:
        kind = event.get("type")
        if kind == "spawn":
            self.players = int(event.get("players") or 0)
            return "spawned"
        if kind == "players":
            self.players = int(event.get("count") or 0)
            return ""
        if kind == "auth_code":
            self.auth_code = {"uri": str(event.get("uri", "")), "code": str(event.get("code", ""))}
            return "Minecraft sign-in needed: the owner opens the link and enters the code (see auth_code)"
        if kind == "done":
            self.busy_until = 0.0
            return f"finished {event.get('task', '')}"
        if kind in ("kicked", "end", "error"):
            reason = str(event.get("reason") or event.get("message") or "")[:200]
            self.log.append(f"{kind}: {reason}")
            if kind != "error":
                self.stop()
            return f"{kind}: {reason}"
        if kind in ("chat", "whisper"):
            return self._on_chat(str(event.get("username") or ""), str(event.get("message") or ""), kind == "whisper")
        return ""

    def _on_chat(self, username: str, message: str, whisper: bool) -> str:
        if not username or username.lower() in self.my_names or not message:
            return ""
        addressed = whisper or any(n in message.lower() for n in self.my_names) or self.players <= QUIET_SERVER
        if not addressed:
            return ""
        person = self.chat.memory.person("minecraft", username, username)
        if person.blocked or person.muted and not whisper:
            return ""
        acted = self._command(username, message)
        reply = self.chat.handle("minecraft", username, message, name=username, public=not whisper)
        if reply is not None:
            self.say(reply.text, to=username if whisper else "")
        return acted or (f"talked with {username}" if reply else "")

    def _command(self, username: str, message: str) -> str:
        """Friendly requests she agrees to: follow, stop, gather, build."""
        if _FOLLOW.search(message):
            self.following = username
            self._send({"cmd": "follow", "username": username})
            return f"following {username}"
        if self.following and _STOP.search(message):
            self.following = ""
            self._send({"cmd": "stop"})
            return "stopped"
        gather = _GATHER.search(message)
        if gather:
            self.following = ""
            self._send({"cmd": "gather", "block": _BLOCKS[gather.group(1).lower()], "count": 4})
            self.busy_until = self._clock() + 60
            return f"gathering {gather.group(1)}"
        if _BUILD.search(message):
            self._send({"cmd": "build_pillar", "height": 4})
            self.busy_until = self._clock() + 60
            return "building"
        return ""
