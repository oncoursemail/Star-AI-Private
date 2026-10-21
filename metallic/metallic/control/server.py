"""HTTP API + the built UI. LAN-only by deployment; every API call needs a session from the owner's login token.

    POST /api/login        {"token"} -> session cookie (HttpOnly, SameSite=Strict, Secure on HTTPS) + CSRF token
    POST /api/logout
    GET  /api/session      {"csrf"} while signed in
    GET  /api/state        the live state document (machines, Star AI, dev, backups, alerts, sources)
    GET  /api/series?keys=a,b&range=hour|day|week
    GET  /api/keys?prefix=
    GET  /api/speed?days=7
    GET  /api/actions      the allow-list for this deployment
    POST /api/actions/run  {"action", "confirm"} (confirm must repeat the action id; X-CSRF-Token header required)
    GET  /api/audit
    POST /api/push         the PC agent (Authorization: Bearer <push token>; can do nothing else)

Login failures are rate limited per client (5 per 5 minutes). Tokens are compared in constant time and never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import mimetypes
from pathlib import Path
import secrets
import ssl
import threading
import time
import urllib.parse

from . import actions as actions_mod

SESSION_S = 12 * 3600
FAIL_WINDOW = 300
FAIL_MAX = 5
MAX_BODY = 512_000
HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
           "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                      "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                      "form-action 'self'"}


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


class Auth:
    def __init__(self, login_token: str, push_token: str, clock=time.time):
        if len(login_token) < 24 or len(push_token) < 24:
            raise ValueError("login and push tokens must be at least 24 characters")
        self.login, self.push, self.clock = _digest(login_token), _digest(push_token), clock
        self.sessions: dict[str, dict] = {}
        self.fails: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def limited(self, client: str) -> bool:
        now = self.clock()
        with self.lock:
            recent = [t for t in self.fails.get(client, []) if now - t < FAIL_WINDOW]
            self.fails[client] = recent
            return len(recent) >= FAIL_MAX

    def sign_in(self, client: str, token: str) -> dict | None:
        if self.limited(client):
            return None
        if not isinstance(token, str) or not hmac.compare_digest(_digest(token), self.login):
            with self.lock:
                self.fails.setdefault(client, []).append(self.clock())
            return None
        sid = secrets.token_urlsafe(32)
        session = {"sid": sid, "csrf": secrets.token_urlsafe(24), "created": self.clock(),
                   "actor": "owner " + hashlib.sha256(sid.encode()).hexdigest()[:6]}
        with self.lock:
            self.sessions[sid] = session
            self.fails.pop(client, None)
        return session

    def session(self, cookie_header: str | None) -> dict | None:
        sid = None
        for part in (cookie_header or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "mc_session":
                sid = value
        if not sid:
            return None
        with self.lock:
            s = self.sessions.get(sid)
            if s and self.clock() - s["created"] > SESSION_S:
                del self.sessions[sid]
                return None
            return s

    def sign_out(self, session: dict) -> None:
        with self.lock:
            self.sessions.pop(session["sid"], None)

    def push_ok(self, header: str | None) -> bool:
        if not header or not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(_digest(header[7:].strip()), self.push)


class App:
    """Routes, independent of the socket server so tests can call `handle` directly."""

    def __init__(self, collector, store, runner, auth: Auth, machines: list[dict], ui_dir: str | None = None,
                 secure_cookie: bool = False):
        self.collector, self.store, self.runner, self.auth = collector, store, runner, auth
        self.machines, self.ui = machines, Path(ui_dir) if ui_dir else None
        self.secure = secure_cookie

    def handle(self, method: str, path: str, headers: dict, body: bytes, client: str) -> tuple[int, dict, bytes]:
        url = urllib.parse.urlsplit(path)
        route, query = url.path, urllib.parse.parse_qs(url.query)
        if route.startswith("/api/"):
            return self.api(method, route, query, headers, body, client)
        if method != "GET":
            return 405, {}, b""
        return self.static(route)

    def _json(self, code: int, obj, extra: dict | None = None) -> tuple[int, dict, bytes]:
        return code, {"Content-Type": "application/json", "Cache-Control": "no-store", **(extra or {})}, \
            json.dumps(obj, separators=(",", ":")).encode()

    def api(self, method, route, query, headers, body, client):
        if route == "/api/push" and method == "POST":
            if not self.auth.push_ok(headers.get("authorization")):
                return self._json(401, {"ok": False})
            try:
                payload = json.loads(body or b"{}")
            except ValueError:
                return self._json(400, {"ok": False})
            return self._json(200, {"ok": True, "commands": self.collector.on_pc_push(payload)})
        if route == "/api/login" and method == "POST":
            if self.auth.limited(client):
                return self._json(429, {"ok": False, "text": "too many failed sign-ins; wait 5 minutes"})
            try:
                token = json.loads(body or b"{}").get("token", "")
            except (ValueError, AttributeError):
                token = ""
            session = self.auth.sign_in(client, token)
            if session is None:
                return self._json(401, {"ok": False, "text": "that token is not right"})
            cookie = f"mc_session={session['sid']}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_S}"
            return self._json(200, {"ok": True, "csrf": session["csrf"]},
                              {"Set-Cookie": cookie + ("; Secure" if self.secure else "")})
        session = self.auth.session(headers.get("cookie"))
        if session is None:
            return self._json(401, {"ok": False, "text": "sign in first"})
        if method == "POST":
            origin = headers.get("origin")
            if origin and urllib.parse.urlsplit(origin).netloc != headers.get("host"):
                return self._json(403, {"ok": False, "text": "cross-site request refused"})
            if not hmac.compare_digest(headers.get("x-csrf-token", ""), session["csrf"]):
                return self._json(403, {"ok": False, "text": "missing or wrong CSRF token"})
        if method == "GET" and route == "/api/session":
            return self._json(200, {"ok": True, "csrf": session["csrf"]})
        if method == "POST" and route == "/api/logout":
            self.auth.sign_out(session)
            return self._json(200, {"ok": True}, {"Set-Cookie": "mc_session=; Path=/; Max-Age=0"})
        if method == "GET" and route == "/api/state":
            return self._json(200, self.collector.state())
        if method == "GET" and route == "/api/series":
            keys = [k for k in (query.get("keys", [""])[0]).split(",") if k][:40]
            rng = query.get("range", ["hour"])[0]
            if rng not in ("hour", "day", "week"):
                return self._json(400, {"ok": False, "text": "range is hour, day or week"})
            return self._json(200, self.store.series(keys, rng))
        if method == "GET" and route == "/api/keys":
            return self._json(200, {"keys": self.store.keys(query.get("prefix", [""])[0])})
        if method == "GET" and route == "/api/speed":
            days = min(8, max(1, int(query.get("days", ["7"])[0]) if query.get("days", ["7"])[0].isdigit() else 7))
            return self._json(200, {"hours": self.store.speed_history(days)})
        if method == "GET" and route == "/api/actions":
            return self._json(200, {"actions": actions_mod.catalog(self.machines)})
        if method == "GET" and route == "/api/audit":
            return self._json(200, {"audit": self.store.audit(100)})
        if method == "POST" and route == "/api/actions/run":
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                return self._json(400, {"ok": False})
            action = str(req.get("action", ""))[:120]
            if req.get("confirm") != action:
                return self._json(400, {"ok": False, "text": "confirm must repeat the action id"})
            result = self.runner.start(action, session["actor"], client)
            return self._json(200 if result["ok"] else 403, result)
        return self._json(404, {"ok": False, "text": "no such endpoint"})

    def static(self, route: str):
        if self.ui is None:
            return 404, {}, b"no UI built"
        rel = urllib.parse.unquote(route).lstrip("/") or "index.html"
        target = (self.ui / rel).resolve()
        root = self.ui.resolve()
        if root not in target.parents and target != root or not target.is_file():
            target = root / "index.html"          # single-page app: unknown paths get the shell
        if not target.is_file():
            return 404, {}, b"no UI built"
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        cache = "public, max-age=31536000, immutable" if "/assets/" in target.as_posix() else "no-cache"
        return 200, {"Content-Type": ctype, "Cache-Control": cache}, target.read_bytes()


def make_handler(app: App):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "MetallicControl"
        sys_version = ""

        def _serve(self, method: str):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self.send_error(413)
                return
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            code, extra, data = app.handle(method, self.path, headers, body, self.client_address[0])
            self.send_response(code)
            for k, v in {**HEADERS, **extra}.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

        def log_message(self, fmt, *args):      # no request lines (paths are harmless, but keep the journal quiet)
            return
    return Handler


def serve(app: App, host: str, port: int, tls: tuple[str, str] | None = None) -> http.server.ThreadingHTTPServer:
    server = http.server.ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(*tls)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True, name=f"http-{port}").start()
    return server
