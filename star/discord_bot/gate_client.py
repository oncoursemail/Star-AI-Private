"""The bot's side of server/discord/gate/star_gate.py: name a verb, get one JSON answer back.

Two transports, picked per brain in discord-settings.env (values are operator configuration, never in the repo):

    STAR_DISCORD_GATE_1=ssh:user@brain1-host     the bot's key (secrets/gate_ed25519) + secrets/gate_known_hosts;
                                                 the host's authorized_keys forces star-bot-gate, so nothing else runs
    STAR_DISCORD_GATE_2=unix:/run/star-discord-gate.sock   the bot's own container (systemd socket, star-discord only)

Verbs are checked here too, so a typo never leaves the process. No shell is involved on this side.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil

VERBS = frozenset({"facts", "ns-start", "ns-stop", "ns-pause", "ns-resume", "idea", "knowledge-eval",
                   "studio-lab-run"})
RESTARTABLE = frozenset({"star-brain", "star-knowledge", "star-search-gateway", "star-night-school", "star-ns-brain",
                         "star-discord", "searxng"})
MAX_ANSWER = 512_000
_SSH = re.compile(r"ssh:([A-Za-z0-9._-]{1,64}@[A-Za-z0-9.:_-]{1,253})")
_UNIX = re.compile(r"unix:(/[A-Za-z0-9/._-]{1,200})")


def allowed(verb: str) -> bool:
    return verb in VERBS or (verb.startswith("restart:") and verb[8:] in RESTARTABLE)


@dataclass(frozen=True)
class Gate:
    name: str                # "brain 1", "brain 2"
    kind: str                # ssh | unix
    target: str              # user@host or socket path
    key_file: Path | None = None
    known_hosts: Path | None = None

    @classmethod
    def parse(cls, name: str, raw: str, *, folder: Path) -> "Gate":
        raw = raw.strip()
        if match := _SSH.fullmatch(raw):
            return cls(name, "ssh", match.group(1), folder / "gate_ed25519", folder / "gate_known_hosts")
        if match := _UNIX.fullmatch(raw):
            return cls(name, "unix", match.group(1))
        raise ValueError(f"STAR_DISCORD_GATE for {name} must be ssh:user@host or unix:/path")

    def ssh_command(self, verb: str) -> list[str]:
        command = [shutil.which("ssh") or "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                   "-o", "StrictHostKeyChecking=yes"]
        if self.key_file is not None and self.key_file.is_file():
            command += ["-i", str(self.key_file), "-o", "IdentitiesOnly=yes"]
        if self.known_hosts is not None and self.known_hosts.is_file():
            command += ["-o", f"UserKnownHostsFile={self.known_hosts}"]
        return command + [self.target, verb]

    async def call(self, verb: str, payload: str = "", *, timeout: float = 60) -> dict:
        """The gate's JSON answer. ValueError when the verb is not allowed or the brain cannot be reached."""
        if not allowed(verb):
            raise ValueError(f"not an allowed gate verb: {verb[:40]}")
        data = payload.encode("utf-8")[:8000]
        if self.kind == "unix":
            raw = await asyncio.wait_for(self._unix(verb, data), timeout=timeout)
        else:
            raw = await asyncio.wait_for(self._ssh(verb, data), timeout=timeout)
        try:
            answer = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise ValueError(f"{self.name} gave no readable answer") from None
        if not isinstance(answer, dict):
            raise ValueError(f"{self.name} gave no readable answer")
        return answer

    async def _ssh(self, verb: str, data: bytes) -> bytes:
        proc = await asyncio.create_subprocess_exec(*self.ssh_command(verb), stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, _err = await proc.communicate(data)
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.kill()
            raise
        if not out:
            raise ValueError(f"could not reach {self.name} (ssh exit {proc.returncode})")
        return out[:MAX_ANSWER]

    async def _unix(self, verb: str, data: bytes) -> bytes:
        try:
            reader, writer = await asyncio.open_unix_connection(self.target, limit=MAX_ANSWER + 1024)
        except OSError:
            raise ValueError(f"could not reach {self.name} (gate socket closed)") from None
        try:
            writer.write(verb.encode("ascii") + b"\n" + data)
            await writer.drain()
            if writer.can_write_eof():
                writer.write_eof()
            out = await reader.read(MAX_ANSWER)
        finally:
            writer.close()
        if not out:
            raise ValueError(f"{self.name} gave no answer")
        return out


def gates_from_env(env=None) -> dict[str, Gate]:
    """{"1": Gate, "2": Gate} for the configured brains (none configured: {})."""
    from .local_config import config_dir
    source = os.environ if env is None else env
    folder = config_dir(source)
    out = {}
    for number in ("1", "2"):
        raw = str(source.get(f"STAR_DISCORD_GATE_{number}", "")).strip()
        if raw:
            out[number] = Gate.parse(f"brain {number}", raw, folder=folder)
    return out
