"""The owner's global stop for computer use: hotkey, file flag and a small HTTP API, all ending in the same STOP file.

  file    <home>\\STOP (star/home/control.py). Present = every action raises `Stopped`; checked before each action
          and every ~50 ms inside a move or drag (hands.py), so a stop lands within a fraction of a second.
  hotkey  Ctrl+Alt+Shift+F12 (control.hotkey_watch; the STAR Home loop already runs it, the CLI starts it itself).
  API     http://<host>:<port>  GET /status  ->  {"stopped": bool}
                                POST /stop   (header X-Owner-Token) -> creates STOP
                                POST /resume (header X-Owner-Token) -> removes STOP
          Default 127.0.0.1:8767. The token lives in <home>\\owner_token (created on first start); STAR's own actions
          cannot read the home folder (host.py), so only the owner can resume her. To stop her from his own PC the owner
          sets computer.json "stop_api": {"host": "0.0.0.0"} and keeps the token.
"""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading

from ..home import control

TOKEN_NAME = "owner_token"
DEFAULT_PORT = 8767


class StopSwitch:
    """One place to ask "stop?": the STOP file or a trip in this process (the API and hotkey also write the file)."""

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self._tripped = threading.Event()

    def is_set(self) -> bool:
        return self._tripped.is_set() or control.stopped(self.home)

    def trip(self, reason: str = "owner") -> None:
        self._tripped.set()
        control.stop(self.home, reason)
        control.log_action(self.home, "computer.stop", "done", detail=reason)

    def clear(self) -> bool:
        self._tripped.clear()
        removed = control.resume(self.home)
        control.log_action(self.home, "computer.resume", "done", detail="owner")
        return removed


def owner_token(home: Path) -> str:
    path = Path(home) / TOKEN_NAME
    try:
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    return token


def make_handler(switch: StopSwitch, token: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _owner(self) -> bool:
            given = self.headers.get("X-Owner-Token", "")
            return bool(given) and hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path.rstrip("/") == "/status":
                self._send(200, {"stopped": switch.is_set()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            route = self.path.rstrip("/")
            if route not in ("/stop", "/resume"):
                self._send(404, {"error": "not found"})
                return
            if not self._owner():
                control.log_action(switch.home, "computer.api", "refused", detail=f"{route} without the owner token")
                self._send(403, {"error": "owner token required"})
                return
            if route == "/stop":
                switch.trip("api")
            else:
                switch.clear()
            self._send(200, {"stopped": switch.is_set()})

        def log_message(self, *args) -> None:    # no console noise; the action log has the record
            return

    return Handler


def serve(switch: StopSwitch, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """Start the API in a daemon thread; returns the server (call .shutdown() to end it)."""
    server = ThreadingHTTPServer((host, port), make_handler(switch, owner_token(switch.home)))
    threading.Thread(target=server.serve_forever, daemon=True, name="star-stop-api").start()
    return server


_started: set[str] = set()


def start_owner_controls(switch: StopSwitch, cfg: dict, *, hotkey: bool) -> None:  # pragma: no cover - real desktop
    """Once per process: the API (and the hotkey when no STAR Home loop runs it already)."""
    key = str(switch.home)
    if key in _started:
        return
    _started.add(key)
    api = cfg.get("stop_api") or {}
    if api.get("enabled", True):
        try:
            serve(switch, str(api.get("host") or "127.0.0.1"), int(api.get("port") or DEFAULT_PORT))
        except OSError as why:                    # port taken: the STOP file and hotkey still work
            control.log_action(switch.home, "computer.api", "error", detail=f"{type(why).__name__}: {why}")
    if hotkey:
        threading.Thread(target=control.hotkey_watch, args=(switch.home,), daemon=True).start()
