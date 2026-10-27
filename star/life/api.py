"""The small read-only status API on her PC that the owner's mood widget talks to (the widget never touches her PC itself).

    GET /life/mood      {"kind": "sunny|cloudy|stormy|starry|off", "label", "why", "icon", "dominant", "at"}
    GET /life/journal   plain text: her self-journal changes, her own journal entries, her gallery commentary, her goals
Both need `Authorization: Bearer <token>`; the token is a random string in <home>/life/extras/api_token, created on first
use, compared in constant time and never printed or logged. Only GET exists (no write route), nothing here can start an
action, and the journal leaves out her friends' chats and her friend diary on purpose. Off unless `life_api_enabled`
(settings.json); it listens on `life_api_host` (default 127.0.0.1: the owner opens it to the LAN himself) and `life_api_port`
(default 8765).
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import goals as goals_mod
from . import mood, studio, style
from .store import base, default_store, flag

DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8765


def token_path(home=None):
    return base(home) / "life" / "extras" / "api_token"


def read_token(home=None, *, create: bool = True) -> str:
    path = token_path(home)
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    if not create:
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    return token


def _setting(name: str, default, home=None):
    try:
        raw = json.loads((base(home) / "settings.json").read_text(encoding="utf-8"))
        return raw.get(name, default) if isinstance(raw, dict) else default
    except (OSError, ValueError):
        return default


def journal_text(home=None, *, store=None, inner_store=None) -> str:
    """Her journal page for the owner. Each part is optional; a part that cannot be read is left out."""
    store = store or default_store(home)
    parts = []
    try:
        from ..inner import self_model
        from ..inner.store import default_store as inner_default
        text = self_model.journal_text(inner_store or inner_default())
        if text.strip():
            parts.append("HOW I CHANGED\n" + text.strip())
    except Exception:
        pass
    entries = [w for w in studio.works(store, 50, "journal") if w["path"]]
    for w in entries[:3]:
        try:
            parts.append("JOURNAL " + w["title"] + "\n" + open(w["path"], encoding="utf-8").read().strip())
        except OSError:
            pass
    gallery = studio.gallery_text(store, 15)
    if gallery:
        parts.append("WHAT I MADE\n" + gallery)
    looks = style.style_text(store)
    if looks:
        parts.append("MY STYLE\n" + looks)
    live = goals_mod.goals(store, ("open", "active"))
    done = goals_mod.goals(store, "done")[-3:]
    lines = [f"- {g['text']} (streak {g['streak']}, {g['tries']} tries)" for g in live]
    lines += [f"- done: {g['text']} (proof: {g['proof']})" for g in done]
    if lines:
        parts.append("MY GOALS\n" + "\n".join(lines))
    return "\n\n".join(parts) or "Nothing in my journal yet."


def make_handler(home=None, *, token: str | None = None, emotion=None, store=None):
    secret = token if token is not None else read_token(home)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args) -> None:          # no access log: it would hold request paths and peers
            pass

        def _send(self, code: int, body: str, kind: str = "application/json") -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            given = self.headers.get("Authorization", "")
            if not given.startswith("Bearer ") or not hmac.compare_digest(given[7:].strip().encode(), secret.encode()):
                return self._send(401, '{"error": "unauthorized"}')
            path = self.path.split("?", 1)[0]
            if path == "/life/mood":
                return self._send(200, json.dumps(mood.payload(None, emotion=emotion)))
            if path == "/life/journal":
                return self._send(200, journal_text(home, store=store), "text/plain")
            self._send(404, '{"error": "not found"}')

        def _refuse(self) -> None:
            self._send(405, '{"error": "read-only"}')

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse

    return Handler


def serve(home=None, *, host: str | None = None, port: int | None = None, emotion=None, store=None) -> ThreadingHTTPServer:
    """A started-but-not-running server (call serve_forever()). Refuses to exist when the setting is off."""
    if not flag("life_api_enabled", home):
        raise RuntimeError("life_api_enabled is off in settings.json")
    host = host or str(_setting("life_api_host", DEFAULT_HOST, home))
    port = int(port if port is not None else _setting("life_api_port", DEFAULT_PORT, home))
    return ThreadingHTTPServer((host, port), make_handler(home, emotion=emotion, store=store))


def background_job(home=None):  # pragma: no cover - the long-running thread on her PC
    """For STAR Home's background list: runs the API when `life_api_enabled`."""
    def run() -> None:
        if not flag("life_api_enabled", home):
            return
        try:
            serve(home).serve_forever()
        except OSError:
            time.sleep(60)
    return run
