"""STAR GPU worker: lets the Discord bot on a STAR server draw on this PC's graphics card.

    python -m star.discord_bot.gpu_worker run        connect to the bot and take draw jobs (Ctrl+C stops)
    python -m star.discord_bot.gpu_worker install    Task Scheduler entry "STAR GPU worker": hidden, at sign-in,
                                                     your account only, no administrator, no password stored
    python -m star.discord_bot.gpu_worker status | start | stop | remove | print

It opens no port on this PC. It connects OUT with your existing SSH key (gpu_link.py explains the path), waits
for signed jobs, makes each picture with the same code as STAR Desktop's Create image (draw.Drawer: ComfyUI on
127.0.0.1, started when a job arrives, stopped after 10 idle minutes), and sends the picture back. When the
server or the network drops it reconnects by itself (5 s, doubling to at most 60 s).

Settings: ~/.star/gpu-worker.env (STAR_GPU_WORKER_SSH=user@host of the server's LXD host; optional
STAR_GPU_WORKER_CONTAINER, default starai; STAR_GPU_WORKER_SOCKET; STAR_PC_FEED_ROOT, the workspace folder whose
STATE.md and COLLAB/BOARD.md feed Star's live status, default the folder above worktrees/), key ~/.star/gpu-worker.key
(the same key as the server's secrets/gpu-worker.key), log ~/.star/gpu-worker.log (no prompts, pictures or keys).
Every minute it also sends the PC feed (pc_feed.py) so Star on the server knows the board, PRs and the owner's day.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import collections
import logging
import logging.handlers
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from xml.sax.saxutils import escape

from .draw import Drawer, DrawSettings
from .gpu_link import ALIVE_SECONDS, KEY_FILE, MAX_LINE, decode, encode, read_key, verify

_LOG = logging.getLogger("star.gpu_worker")
TASK_NAME = "STAR GPU worker"
SETTINGS_FILE = "gpu-worker.env"
LOG_FILE = "gpu-worker.log"
LOCK_FILE = "gpu-worker.lock"
DEFAULT_SOCKET = "/opt/star/discord/state/gpu-worker.sock"
MAX_DELAY = 60
FEED_SECONDS = 60
_TARGET = re.compile(r"[A-Za-z0-9._-]{1,64}@[A-Za-z0-9.:-]{1,253}")
_CONTAINER = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_SOCKET = re.compile(r"/[A-Za-z0-9/._-]{1,100}")


def star_dir() -> Path:
    return Path.home() / ".star"


def load_settings(folder: Path | None = None) -> dict[str, str]:
    """KEY=VALUE lines of gpu-worker.env, checked. ValueError names the problem (never a value)."""
    folder = folder or star_dir()
    values: dict[str, str] = {}
    path = folder / SETTINGS_FILE
    if path.is_file():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip().strip("\"'")
    target = values.get("STAR_GPU_WORKER_SSH", "")
    container = values.get("STAR_GPU_WORKER_CONTAINER", "") or "starai"
    sock = values.get("STAR_GPU_WORKER_SOCKET", "") or DEFAULT_SOCKET
    if not _TARGET.fullmatch(target):
        raise ValueError(f"Set STAR_GPU_WORKER_SSH=user@host in {path}")
    if not _CONTAINER.fullmatch(container) or not _SOCKET.fullmatch(sock):
        raise ValueError(f"STAR_GPU_WORKER_CONTAINER or STAR_GPU_WORKER_SOCKET in {path} is invalid")
    return {"target": target, "container": container, "socket": sock,
            "feed_root": values.get("STAR_PC_FEED_ROOT", "")}


def ssh_command(settings: dict[str, str], ssh: str = "ssh") -> list[str]:
    remote = (f"lxc exec {settings['container']} --cwd /opt/star/discord/current -- runuser -u star-discord -- "
              f"/opt/star/discord/venv/bin/python -m star.discord_bot.gpu_link relay {settings['socket']}")
    return [ssh, "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", settings["target"], remote]


class Worker:
    """Takes one signed job at a time and answers it with draw.Drawer (ComfyUI on this PC)."""

    def __init__(self, drawer: Drawer, key: bytes, feed=None) -> None:
        self.drawer = drawer
        self.key = key
        self.feed = feed            # pc_feed.PcFeed or None
        self.current: asyncio.Task | None = None
        self.seen: collections.deque[str] = collections.deque(maxlen=500)

    async def session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """One connection to the bot; returns when it ends."""
        lock = asyncio.Lock()

        async def send(message: dict) -> None:
            async with lock:
                writer.write(encode(message))
                await writer.drain()

        async def alive() -> None:
            while True:
                await asyncio.sleep(ALIVE_SECONDS)
                await send({"type": "alive"})

        async def feed() -> None:
            while self.feed is not None:
                try:
                    await send({"type": "pcfeed", "feed": await asyncio.to_thread(self.feed.build)})
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    _LOG.info("PC feed not sent (%s)", type(exc).__name__)
                await asyncio.sleep(FEED_SECONDS)

        await send({"type": "hello", "version": 1})
        beat = asyncio.ensure_future(alive())
        feeder = asyncio.ensure_future(feed())
        _LOG.info("connected to the bot")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    message = decode(line)
                except (ValueError, UnicodeError):
                    continue
                if message["type"] != "job":
                    continue
                try:
                    job = verify(message, self.key)
                    if job["id"] in self.seen:
                        raise ValueError("repeated job")
                except ValueError as exc:
                    _LOG.warning("refused a job (%s)", exc)
                    continue
                self.seen.append(job["id"])
                if self.current is not None and not self.current.done():
                    await send({"type": "result", "id": job["id"], "ok": False,
                                "error": "STAR is already drawing a picture on the PC. Try again in a minute."})
                    continue
                self.current = asyncio.ensure_future(self.run_job(job, send))
        finally:
            beat.cancel()
            feeder.cancel()
            _LOG.info("connection to the bot ended")

    async def run_job(self, job: dict, send) -> None:
        short = job["id"][:8]
        started = time.monotonic()

        async def status(text: str) -> None:
            await send({"type": "status", "id": job["id"], "text": text})
        try:
            picture = await self.drawer.draw(job["prompt"], on_status=status)
            result = {"type": "result", "id": job["id"], "ok": True,
                      "image": base64.b64encode(picture.png).decode("ascii"), "filename": picture.filename,
                      "prompt": picture.prompt, "seconds": picture.seconds, "seed": picture.seed,
                      "width": picture.width, "height": picture.height, "model": picture.model}
            _LOG.info("job %s done in %.1f s (%d bytes)", short, time.monotonic() - started, len(picture.png))
        except ValueError as exc:
            result = {"type": "result", "id": job["id"], "ok": False, "error": str(exc)[:600]}
            _LOG.info("job %s not drawn: %s", short, str(exc)[:200])
        except Exception as exc:     # never log the prompt
            result = {"type": "result", "id": job["id"], "ok": False,
                      "error": f"The PC could not make the picture ({type(exc).__name__})."}
            _LOG.warning("job %s failed: %s", short, type(exc).__name__)
        try:
            await send(result)
        except (ConnectionError, OSError, RuntimeError):
            _LOG.warning("job %s: the connection dropped before the picture was sent", short)


async def open_ssh(settings: dict[str, str]):
    ssh = shutil.which("ssh") or str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/OpenSSH/ssh.exe")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = await asyncio.create_subprocess_exec(*ssh_command(settings, ssh), stdin=subprocess.PIPE,
                                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                limit=MAX_LINE + 4096, creationflags=flags)

    async def errors() -> None:
        assert proc.stderr is not None
        while line := await proc.stderr.readline():
            _LOG.info("ssh: %s", line.decode("utf-8", "replace").strip()[:200])
    asyncio.ensure_future(errors())
    return proc.stdout, proc.stdin, proc


async def run_forever(worker: Worker, settings: dict[str, str], *, connect=open_ssh, sleep=asyncio.sleep,
                      rounds: int | None = None) -> None:
    """Connect, serve, and reconnect after any drop (5 s doubling to 60 s; back to 5 s after a long session)."""
    delay = 5
    done = 0
    while rounds is None or done < rounds:
        done += 1
        started = time.monotonic()
        proc = None
        try:
            reader, writer, proc = await connect(settings)
            await worker.session(reader, writer)
        except (OSError, ConnectionError, ValueError) as exc:
            _LOG.info("connection failed (%s)", type(exc).__name__)
        finally:
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        if time.monotonic() - started > 120:
            delay = 5
        await sleep(delay)
        delay = min(delay * 2, MAX_DELAY)


def _setup_log(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(folder / LOG_FILE, maxBytes=1_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def run() -> int:
    folder = star_dir()
    _setup_log(folder)
    from .instance_lock import InstanceLock
    lock = InstanceLock(folder, LOCK_FILE)
    if not lock.acquire():
        _LOG.info("another STAR GPU worker is already running; this one exits")
        return 4
    try:
        settings = load_settings(folder)
        key = read_key(folder / KEY_FILE)
        if not key:
            raise ValueError(f"No signing key in {folder / KEY_FILE}")
    except ValueError as exc:
        _LOG.error("%s", exc)
        lock.release()
        return 2
    _LOG.info("STAR GPU worker started (container %s)", settings["container"])
    from .pc_feed import PcFeed, default_root
    checkout = Path(__file__).resolve().parents[2]
    feed = PcFeed(Path(settings["feed_root"]) if settings["feed_root"] else default_root(checkout), checkout)
    try:
        asyncio.run(run_forever(Worker(Drawer(DrawSettings()), key, feed), settings))
    except KeyboardInterrupt:
        pass
    finally:
        _LOG.info("STAR GPU worker stopped")
        lock.release()
    return 0


def task_xml(*, user: str, python: str, checkout: Path) -> str:
    """Hidden, at sign-in, the owner's own session with ordinary rights, restarted if it fails."""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>STAR GPU worker: draws pictures on this PC for STAR's Discord bot. Opens no port. Remove: python -m star.discord_bot.gpu_worker remove</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>99</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python)}</Command>
      <Arguments>-m star.discord_bot.gpu_worker run</Arguments>
      <WorkingDirectory>{escape(str(checkout))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _windowless(python: str) -> str:
    path = Path(python)
    candidate = path.with_name("pythonw.exe")
    return str(candidate) if path.name.lower() == "python.exe" and candidate.is_file() else python


def main(argv: list[str] | None = None, *, runner=subprocess.run) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.discord_bot.gpu_worker", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["run", "install", "remove", "status", "start", "stop", "print"])
    command = parser.parse_args(argv).command
    if command == "run":
        return run()

    def schtasks(*args: str) -> int:
        return int(runner(["schtasks", *args], text=True).returncode)
    if command in {"print", "install"}:
        user = (f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"
                if os.environ.get("USERDOMAIN") else os.environ.get("USERNAME", ""))
        xml = task_xml(user=user, python=_windowless(sys.executable), checkout=Path(__file__).resolve().parents[2])
        if command == "print":
            print(xml)
            return 0
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "star-gpu-worker.xml"
            path.write_text(xml, encoding="utf-16")
            return schtasks("/Create", "/TN", TASK_NAME, "/XML", str(path), "/F")
    if command == "remove":
        return schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if command == "status":
        return schtasks("/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST")
    if command == "start":
        return schtasks("/Run", "/TN", TASK_NAME)
    return schtasks("/End", "/TN", TASK_NAME)


if __name__ == "__main__":
    raise SystemExit(main())
