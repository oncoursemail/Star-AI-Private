"""HTTPS JSON API for Metallic accounts + social. Clients are native apps (launcher, Star app, RC backend), not web
pages: requests that carry a browser Origin header are refused, POST bodies must be JSON, and there are no cookies.

Public:  GET /health, GET /.well-known/jwks.json, GET /v1/news, POST /v1/register, /v1/login, /v1/refresh,
         /v1/recover, /v1/introspect
Bearer:  everything else (see ROUTES below). Admin routes need role admin or owner.
"""
from __future__ import annotations

import http.server
import json
import re
import ssl
import threading
import urllib.parse

from .service import Accounts, RateLimiter, Refused

MAX_BODY = 16_384
HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
           "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "X-Frame-Options": "DENY",
           "Strict-Transport-Security": "max-age=31536000"}
AUTH_ROUTES = {"/v1/login", "/v1/refresh", "/v1/recover", "/v1/introspect", "/v1/2fa/setup", "/v1/2fa/confirm",
               "/v1/2fa/disable", "/v1/me/password", "/v1/recovery-codes", "/v1/oauth/start", "/v1/oauth/finish",
               "/v1/steam/start", "/v1/steam/finish", "/v1/oauth/signup", "/v1/login/ticket",
               "/v1/passkeys/login/options", "/v1/passkeys/login/finish", "/v1/passkeys/register/finish"}


class App:
    def __init__(self, accounts: Accounts, limiter: RateLimiter | None = None, version: str = "1",
                 exempt: tuple[str, ...] = (), federation=None):
        self.a, self.limiter, self.version = accounts, limiter or RateLimiter(accounts.clock), version
        self.fed = federation
        self.exempt = set(exempt)          # e.g. 127.0.0.1: only processes inside the container (deploy e2e)

    @staticmethod
    def _json(code: int, obj) -> tuple[int, dict, bytes]:
        return code, {"Content-Type": "application/json"}, json.dumps(obj, separators=(",", ":")).encode()

    def _limit(self, key: str, rate: float, burst: int) -> None:
        if key.split(":", 1)[1] in self.exempt:
            return
        ok, wait = self.limiter.allow(key, rate, burst)
        if not ok:
            raise Refused(429, "slow_down", "Too many requests. Wait a moment and try again.", retry_after=wait)

    def _federation(self, method, route, req, headers, ip):
        return _fed_routes(self, method, route, req, headers, ip)

    def handle(self, method: str, path: str, headers: dict, body: bytes, client: str) -> tuple[int, dict, bytes]:
        try:
            return self._route(method, path, headers, body, client)
        except Refused as r:
            extra = {"Retry-After": str(r.extra["retry_after"])} if "retry_after" in r.extra else {}
            code, h, data = self._json(r.status, r.body())
            return code, {**h, **extra}, data

    def _route(self, method, path, headers, body, ip):
        if headers.get("origin"):
            raise Refused(403, "browser_refused", "This service is for Metallic apps, not web pages.")
        url = urllib.parse.urlsplit(path)
        route, query = url.path.rstrip("/") or "/", urllib.parse.parse_qs(url.query)
        q = {k: v[0] for k, v in query.items()}
        self._limit("all:" + ip, 240, 120)
        req: dict = {}
        if method == "POST":
            if not (headers.get("content-type") or "").startswith("application/json"):
                raise Refused(415, "bad_request", "Send JSON.")
            try:
                req = json.loads(body or b"{}")
                assert isinstance(req, dict)
            except (ValueError, AssertionError) as exc:
                raise Refused(400, "bad_request", "The request is not valid JSON.") from exc
        if route in AUTH_ROUTES or route == "/v1/register":
            self._limit("auth:" + ip, 10, 10)
        a, ok = self.a, self._json
        client = (headers.get("user-agent") or "")[:80]

        # ----- public -----
        if method == "GET" and route == "/health":
            return ok(200, {"ok": True, "service": "metallic-accounts", "version": self.version})
        if method == "GET" and route in ("/.well-known/jwks.json", "/v1/keys"):
            return ok(200, a.signer.jwks)
        if method == "GET" and route == "/v1/news":
            limit = int(q["limit"]) if q.get("limit", "").isdigit() else 20
            return ok(200, {"news": a.news(limit, q.get("game"))})
        if method == "POST" and route == "/v1/register":
            self._limit("register:" + ip, 5 / 60, 3)
            return ok(201, a.register(req.get("username"), req.get("password"), req.get("display_name"),
                                      req.get("age_band"), ip, client, req.get("owner_code")))
        if method == "POST" and route == "/v1/login":
            return ok(200, a.login(req.get("username"), req.get("password"), ip, req.get("otp"),
                                   req.get("recovery_code"), client))
        if method == "POST" and route == "/v1/refresh":
            return ok(200, a.refresh(req.get("refresh_token"), ip))
        if method == "POST" and route == "/v1/recover":
            return ok(200, a.recover(req.get("username"), req.get("recovery_code"), req.get("new_password"), ip))
        if method == "POST" and route == "/v1/introspect":
            return ok(200, a.introspect(req.get("token", "")))
        if self.fed is not None:
            out = self._federation(method, route, req, headers, ip)
            if out is not None:
                return out

        # ----- signed in -----
        c = a.authenticate(headers.get("authorization"))
        if method == "GET" and route == "/v1/me":
            return ok(200, a.me(c["sub"]))
        if method == "POST":
            name = req.get("username", "")
            simple = {
                "/v1/logout": lambda: (a.logout(c, ip, bool(req.get("everywhere"))), {"ok": True})[1],
                "/v1/me/profile": lambda: a.update_profile(c, req.get("display_name"), ip),
                "/v1/me/privacy": lambda: a.update_privacy(c, req.get("privacy") or {}, ip),
                "/v1/me/password": lambda: (a.change_password(c, req.get("old_password"), req.get("new_password"),
                                                              req.get("otp"), ip), {"ok": True})[1],
                "/v1/sessions/revoke": lambda: (a.revoke_session(c, str(req.get("id", "")), ip), {"ok": True})[1],
                "/v1/2fa/setup": lambda: a.totp_setup(c, req.get("password"), ip),
                "/v1/2fa/confirm": lambda: a.totp_confirm(c, req.get("code"), ip),
                "/v1/2fa/disable": lambda: (a.totp_disable(c, req.get("password"), req.get("otp"), ip),
                                            {"ok": True})[1],
                "/v1/recovery-codes": lambda: {"recovery_codes": a.regenerate_recovery(c, req.get("password"),
                                                                                       req.get("otp"), ip)},
                "/v1/friends/accept": lambda: a.friend_accept(c, name, ip),
                "/v1/friends/decline": lambda: a.friend_decline(c, name, ip),
                "/v1/friends/remove": lambda: a.friend_remove(c, name, ip),
                "/v1/friends/block": lambda: a.block(c, name, ip, True),
                "/v1/friends/unblock": lambda: a.block(c, name, ip, False),
                "/v1/presence": lambda: a.set_presence(c, req.get("status"), req.get("game"), req.get("detail"),
                                                       req.get("joinable", False)),
                "/v1/news": lambda: a.post_news(c, req.get("title"), req.get("body"), req.get("game"),
                                                req.get("pinned", False), ip),
            }
            if route in simple:
                return ok(200, simple[route]())
            if route == "/v1/friends/request":
                self._limit("freq:" + c["sub"], 20 / 60, 10)
                return ok(200, a.friend_request(c, name, ip))
            if route == "/v1/invites":
                return ok(201, a.invite(c, req.get("to", ""), req.get("game"), req.get("target"), ip))
            m = re.fullmatch(r"/v1/invites/(inv_[a-z0-9]+)/(accept|decline)", route)
            if m:
                return ok(200, a.answer_invite(c, m.group(1), m.group(2) == "accept", ip))
            m = re.fullmatch(r"/v1/news/(news_[a-z0-9]+)/delete", route)
            if m:
                return ok(200, a.delete_news(c, m.group(1), ip))
            m = re.fullmatch(r"/v1/admin/accounts/([A-Za-z0-9_]{3,20})", route)
            if m:
                return ok(200, a.admin_action(c, m.group(1), str(req.get("action", "")), req.get("value"), ip))
        if method == "GET":
            if route == "/v1/sessions":
                return ok(200, {"sessions": a.sessions(c)})
            if route == "/v1/friends":
                return ok(200, a.friends(c))
            if route == "/v1/presence":
                f = a.friends(c)["friends"]
                return ok(200, {"friends": [{"username": x["username"], "presence": x["presence"]} for x in f]})
            if route == "/v1/invites":
                return ok(200, a.invites(c))
            m = re.fullmatch(r"/v1/users/([A-Za-z0-9_]{3,20})", route)
            if m:
                return ok(200, a.profile(c, m.group(1)))
            if route == "/v1/admin/accounts":
                return ok(200, {"accounts": a.admin_accounts(c, q.get("q", ""))})
            if route == "/v1/admin/audit":
                limit = int(q["limit"]) if q.get("limit", "").isdigit() else 200
                return ok(200, {"audit": a.admin_audit(c, q.get("username"), limit)})
        raise Refused(404, "not_found", "No such endpoint.")


def _fed_routes(app: "App", method, route, req, headers, ip):
    """Provider sign-in, linking and passkeys (federation.py). None = not one of these routes."""
    f, a, ok = app.fed, app.a, app._json
    opt = (lambda: a.authenticate(headers["authorization"])) if headers.get("authorization") else (lambda: None)
    if method == "GET" and route == "/v1/providers":
        return ok(200, f.enabled())
    if method != "POST" and route != "/v1/me/methods":
        return None
    if route == "/v1/oauth/start":
        return ok(200, f.oauth_start(req.get("provider"), req.get("redirect_uri"), req.get("code_challenge"),
                                     req.get("intent", "login"), opt()))
    if route == "/v1/oauth/finish":
        return ok(200, f.oauth_finish(req.get("flow"), req.get("state"), req.get("code"), req.get("code_verifier"),
                                      ip, opt()))
    if route == "/v1/steam/start":
        return ok(200, f.steam_start(req.get("redirect_uri"), req.get("intent", "login"), opt()))
    if route == "/v1/steam/finish":
        return ok(200, f.steam_finish(req.get("flow"), req.get("params"), ip, opt()))
    if route == "/v1/oauth/signup":
        app._limit("register:" + ip, 5 / 60, 3)
        return ok(201, f.signup(req.get("ticket"), req.get("username"), req.get("age_band"), req.get("display_name"),
                                ip))
    if route == "/v1/login/ticket":
        return ok(200, f.finish_mfa(req.get("ticket"), req.get("otp"), req.get("recovery_code"), ip))
    if route == "/v1/passkeys/login/options":
        return ok(200, f.passkey_login_options())
    if route == "/v1/passkeys/login/finish":
        return ok(200, f.passkey_login_finish(req.get("flow"), req.get("credential"), ip))
    signed = {"/v1/me/methods", "/v1/identities/unlink", "/v1/passkeys/register/options",
              "/v1/passkeys/register/finish", "/v1/passkeys/remove"}
    if route not in signed:
        return None
    c = a.authenticate(headers.get("authorization"))
    if route == "/v1/me/methods" and method == "GET":
        return ok(200, f.methods(c["sub"]))
    if method != "POST":
        return None
    if route == "/v1/identities/unlink":
        return ok(200, f.unlink(c, req.get("provider"), ip))
    if route == "/v1/passkeys/register/options":
        return ok(200, f.passkey_register_options(c))
    if route == "/v1/passkeys/register/finish":
        return ok(200, f.passkey_register_finish(c, req.get("flow"), req.get("credential"), req.get("name"), ip))
    return ok(200, f.passkey_remove(c, req.get("id"), ip))


def make_handler(app: App):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "MetallicAccounts"
        sys_version = ""
        timeout = 15                                   # slow or idle clients are dropped
        protocol_version = "HTTP/1.1"

        def _serve(self, method: str):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
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

        def log_message(self, fmt, *args):     # the audit log records what matters; no request lines with tokens
            return
    return Handler


class _TLSServer(http.server.ThreadingHTTPServer):
    """Wraps each connection in its handler thread, so a slow TLS handshake cannot stall accept()."""
    daemon_threads = True
    ssl_ctx: ssl.SSLContext | None = None

    def finish_request(self, request, client_address):
        if self.ssl_ctx is not None:
            request.settimeout(10)
            try:
                request = self.ssl_ctx.wrap_socket(request, server_side=True)
            except (ssl.SSLError, OSError):
                return
        super().finish_request(request, client_address)


def serve(app: App, host: str, port: int, tls: tuple[str, str] | None = None) -> http.server.ThreadingHTTPServer:
    server = _TLSServer((host, port), make_handler(app))
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(*tls)
        server.ssl_ctx = ctx
    threading.Thread(target=server.serve_forever, daemon=True, name=f"accounts-{port}").start()
    return server
