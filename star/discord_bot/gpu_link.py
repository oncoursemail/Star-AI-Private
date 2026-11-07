"""Drawing on the owner's PC GPU for a Discord bot that runs on a STAR server (STAR_DISCORD_HOST=server).

Nothing listens on the PC. The PC GPU worker (gpu_worker.py) connects OUT over the owner's existing SSH key:
``ssh <brain 2> lxc exec starai -- runuser -u star-discord -- python -m star.discord_bot.gpu_link relay <socket>``.
The relay joins that SSH session to the bot's Unix socket (in a 0700 folder of the bot's user), so only the bot
and the one worker meet there. Messages are JSON lines:

    worker -> bot   {"type": "hello"} once, {"type": "alive"} every 15 s, {"type": "status", "id", "text"},
                    {"type": "result", "id", "ok": true, "image": base64, ...} or {"ok": false, "error"},
                    {"type": "pcfeed", "feed": {...}} every minute (pc_feed.py: what only the PC knows)
    bot -> worker   {"type": "job", "job": {"id", "prompt", "ts"}, "sig": HMAC-SHA256}

Jobs are signed with a key both sides hold (secrets/gpu-worker.key on the server, ~/.star/gpu-worker.key on the
PC); the worker refuses unsigned, stale (> 5 min) or repeated jobs. One job at a time, a 1500-character prompt,
a picture of at most 8 MB. Logs never contain prompts, pictures or the key.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import threading
import time

from .draw import MAX_DISCORD_FILE, TURN_ON_HINT, Drawing, DrawSettings, prompt_problem

_LOG = logging.getLogger(__name__)

KEY_FILE = "gpu-worker.key"
SOCKET_FILE = "gpu-worker.sock"
MAX_LINE = 12 * 1024 * 1024            # one result line: an 8 MB picture in base64 plus its note
ALIVE_SECONDS = 15
STALE_SECONDS = 45                      # no word from the worker for this long = offline (PC asleep, network gone)
JOB_MAX_AGE = 300
MAX_FEED = 64 * 1024                    # one pcfeed line
OFFLINE = ("My drawing GPU (your PC) is offline right now, so I can't draw this. When the PC is on and signed in, "
           "its STAR GPU worker reconnects by itself; then ask again.")
NO_KEY = ("Drawing through the PC is not set up on this server yet (no gpu-worker.key). "
          "See docs/STAR_DISCORD_SETUP.md, 'Drawing from the server'.")
_FILENAMES = {"star-drawing.png": b"\x89PNG\r\n\x1a\n", "star-drawing.jpg": b"\xff\xd8\xff"}


def read_key(path: Path) -> bytes:
    """The shared signing key (hex text), for memory only. b'' when missing or malformed."""
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
        key = bytes.fromhex(text)
    except (OSError, ValueError):
        return b""
    return key if len(key) >= 32 else b""


def new_key() -> str:
    return secrets.token_hex(32)


def _canonical(job: dict) -> bytes:
    return json.dumps(job, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(job: dict, key: bytes) -> str:
    return hmac.new(key, _canonical(job), hashlib.sha256).hexdigest()


def verify(message: dict, key: bytes, *, now: float | None = None) -> dict:
    """The job inside a signed message, or ValueError. Checks signature, shape and age."""
    job, sig = message.get("job"), message.get("sig")
    if not key or not isinstance(job, dict) or not isinstance(sig, str):
        raise ValueError("unsigned job")
    if not hmac.compare_digest(sign(job, key), sig):
        raise ValueError("bad signature")
    if set(job) != {"id", "prompt", "ts"} or not isinstance(job["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", job["id"]):
        raise ValueError("bad job")
    if not isinstance(job["ts"], int) or abs((time.time() if now is None else now) - job["ts"]) > JOB_MAX_AGE:
        raise ValueError("stale job")
    if not isinstance(job["prompt"], str) or prompt_problem(job["prompt"]):
        raise ValueError("bad prompt")
    return job


def encode(message: dict) -> bytes:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"


def decode(line: bytes) -> dict:
    message = json.loads(line.decode("utf-8"))
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ValueError("not a message")
    return message


def drawing_from_result(message: dict) -> Drawing:
    """A worker's result as a Drawing, after checking the picture (type, size) and the note's fields."""
    name = message.get("filename")
    if name not in _FILENAMES:
        raise ValueError("bad file name")
    raw = message.get("image")
    if not isinstance(raw, str) or len(raw) > MAX_DISCORD_FILE * 4 // 3 + 8:
        raise ValueError("picture too large")
    data = base64.b64decode(raw, validate=True)
    if not data.startswith(_FILENAMES[name]) or len(data) > MAX_DISCORD_FILE:
        raise ValueError("not a picture")
    return Drawing(data, name, str(message.get("prompt", ""))[:1500], float(message.get("seconds", 0)),
                   int(message.get("seed", 0)), int(message.get("width", 0)), int(message.get("height", 0)),
                   str(message.get("model", ""))[:80])


class _Link:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self.last_seen = time.monotonic()

    def fresh(self) -> bool:
        return time.monotonic() - self.last_seen < STALE_SECONDS and not self.writer.is_closing()

    def close(self) -> None:
        try:
            self.writer.close()
        except Exception:
            pass


class RemoteDrawer:
    """The bot side: same draw()/describe() as draw.Drawer, but the picture is made by the PC worker."""

    def __init__(self, config: DrawSettings, *, key: bytes = b"", socket_path: Path | None = None,
                 wait_seconds: float | None = None) -> None:
        self.config = config
        self.key = key
        self.socket_path = socket_path
        self.wait_seconds = wait_seconds if wait_seconds is not None else config.timeout_seconds + 45
        self._link: _Link | None = None
        self._pending: dict[str, tuple[asyncio.Future, object]] = {}
        self._lock = asyncio.Lock()
        self._server = None
        self._feed: tuple[float, dict] | None = None

    def latest_feed(self) -> tuple[float, dict] | None:
        """(age in seconds, the PC feed) from the last pcfeed message, or None."""
        if self._feed is None:
            return None
        return time.time() - self._feed[0], self._feed[1]

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @property
    def connected(self) -> bool:
        return self._link is not None and self._link.fresh()

    async def start(self) -> None:
        """Listen on the Unix socket (owner-only file in the bot's 0700 folder). Server side only."""
        if self.socket_path is None or not self.config.enabled or self._server is not None:
            return
        path = Path(self.socket_path)
        path.unlink(missing_ok=True)
        old = os.umask(0o177)
        try:
            self._server = await asyncio.start_unix_server(self.handle, path=str(path), limit=MAX_LINE + 4096)
        finally:
            os.umask(old)
        _LOG.info("PC GPU worker socket ready")

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._link is not None:
            self._link.close()

    def _fail_pending(self, text: str) -> None:
        for future, _ in list(self._pending.values()):
            if not future.done():
                future.set_exception(ValueError(text))
        self._pending.clear()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """One worker connection. A new one replaces the old (the PC reconnected after a drop)."""
        link = _Link(reader, writer)
        try:
            first = decode(await asyncio.wait_for(reader.readline(), timeout=10))
            if first.get("type") != "hello":
                raise ValueError("no hello")
        except (asyncio.TimeoutError, ValueError, UnicodeError):
            link.close()
            return
        if self._link is not None:
            self._link.close()
            self._fail_pending("My drawing GPU (your PC) reconnected during the picture; please ask again.")
        self._link = link
        _LOG.info("PC GPU worker connected")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                link.last_seen = time.monotonic()
                try:
                    message = decode(line)
                except (ValueError, UnicodeError):
                    continue
                if message["type"] == "pcfeed":
                    if isinstance(message.get("feed"), dict) and len(line) <= MAX_FEED:
                        self._feed = (time.time(), message["feed"])
                    continue
                entry = self._pending.get(str(message.get("id", "")))
                if entry is None:
                    continue
                future, on_status = entry
                if message["type"] == "status" and on_status is not None:
                    try:
                        await on_status(str(message.get("text", ""))[:200])
                    except Exception as exc:
                        _LOG.info("Draw status update failed (%s)", type(exc).__name__)
                elif message["type"] == "result" and not future.done():
                    try:
                        if message.get("ok") is True:
                            future.set_result(drawing_from_result(message))
                        else:
                            future.set_exception(ValueError(str(message.get("error", "The PC could not make the "
                                                                                     "picture."))[:600]))
                    except (ValueError, TypeError) as exc:     # binascii.Error is a ValueError
                        future.set_exception(ValueError(f"The PC sent back an unusable picture ({exc})."))
        except (asyncio.LimitOverrunError, ValueError, ConnectionError):
            pass
        finally:
            if self._link is link:
                self._link = None
                self._fail_pending("My drawing GPU (your PC) went offline during the picture; please ask again.")
                _LOG.info("PC GPU worker disconnected")
            link.close()

    async def draw(self, prompt: str, *, on_status=None) -> Drawing:
        if not self.config.enabled:
            raise ValueError("Making images is switched off for the Discord bot. " + TURN_ON_HINT)
        prompt = " ".join(str(prompt or "").split())
        problem = prompt_problem(prompt)
        if problem:
            raise ValueError(problem)
        if not self.key:
            raise ValueError(NO_KEY)
        if not self.connected:
            raise ValueError(OFFLINE)
        if self._lock.locked():
            raise ValueError("STAR is already drawing a picture. Try again when it is done (about a minute).")
        async with self._lock:
            link = self._link
            if link is None or not link.fresh():
                raise ValueError(OFFLINE)
            job = {"id": secrets.token_hex(16), "prompt": prompt, "ts": int(time.time())}
            future = asyncio.get_running_loop().create_future()
            self._pending[job["id"]] = (future, on_status)
            try:
                link.writer.write(encode({"type": "job", "job": job, "sig": sign(job, self.key)}))
                await link.writer.drain()
                return await asyncio.wait_for(future, timeout=self.wait_seconds)
            except asyncio.TimeoutError:
                raise ValueError(f"The PC did not finish the picture within {int(self.wait_seconds)} seconds.") from None
            except ConnectionError:
                raise ValueError(OFFLINE) from None
            finally:
                self._pending.pop(job["id"], None)

    def describe(self) -> str:
        if not self.config.enabled:
            return "off"
        who = "owner + approved server" if self.config.anyone else "owner only"
        state = "connected" if self.connected else "offline"
        return f"on the PC's GPU via the STAR GPU worker ({state}; {who}, one at a time)"


def remote_drawer(config: DrawSettings, env=None) -> RemoteDrawer:
    """The server bot's drawer: key from <settings folder>/gpu-worker.key, socket STAR_DISCORD_GPU_SOCKET."""
    from .local_config import config_dir
    source = os.environ if env is None else env
    folder = config_dir(source)
    sock = str(source.get("STAR_DISCORD_GPU_SOCKET", "")).strip() or str(folder / SOCKET_FILE)
    return RemoteDrawer(config, key=read_key(folder / KEY_FILE), socket_path=Path(sock))


def relay(path: str) -> int:
    """Container side of the worker's SSH session: stdin/stdout <-> the bot's Unix socket. Bytes only."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
    except OSError:
        print("The STAR Discord bot is not running (no worker socket).", file=sys.stderr)
        return 3

    def upstream() -> None:
        try:
            while True:
                chunk = os.read(0, 65536)
                if not chunk:
                    break
                sock.sendall(chunk)
        except OSError:
            pass
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    threading.Thread(target=upstream, daemon=True).start()
    try:
        while True:
            data = sock.recv(65536)
            if not data:
                break
            view = memoryview(data)
            while view:
                view = view[os.write(1, view):]
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "relay":
        raise SystemExit(relay(sys.argv[2]))
    print("Usage: python -m star.discord_bot.gpu_link relay <socket path>", file=sys.stderr)
    raise SystemExit(2)
