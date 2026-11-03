"""The face's web server (stdlib only).

    python -m litha.face                      http://127.0.0.1:8770 (this PC only, no token needed)
    python -m litha.face --lan                also the LAN: other devices sign in with ~/.star/litha-face.token
    python -m litha.face --port 8800

Security: 127.0.0.1 unless --lan. The token file is made on first run and never printed or logged. Requests from
another machine need it (a sign-in form sets an HttpOnly cookie). Every POST needs the X-Litha-Face header and a JSON
body, so a web page in another tab cannot press her buttons. On 127.0.0.1 the Host header must be the loopback one
(no DNS rebinding)."""
from __future__ import annotations

import argparse
import hmac
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import urllib.parse

from litha.face import controls, data

STATIC = Path(__file__).with_name("static")
TOKEN = data.ROOT / "litha-face.token"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".svg": "image/svg+xml", ".png": "image/png"}
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'"
CHAT_WAIT = 240                                   # seconds the page waits for her model (it may be busy with a run)


def token(path: Path = TOKEN) -> str:
    """The LAN token, made on first use (owner reads it with: type %USERPROFILE%\\.star\\litha-face.token)."""
    try:
        t = path.read_text(encoding="utf-8").strip()
        if len(t) >= 20:
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(t + "\n", encoding="utf-8")
    return t


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def allowed(client: str, host_header: str, cookie_header: str, header_token: str, tok: str, lan: bool) -> bool:
    """Who may read or press anything: loopback clients asking for a loopback host, or anyone with the token (LAN)."""
    if is_loopback(client):
        host = (host_header or "").rsplit(":", 1)[0].strip("[]").lower()
        if host in ("127.0.0.1", "localhost", "::1"):
            return True
    if not lan:
        return False
    given = header_token
    if not given and cookie_header:
        c = cookies.SimpleCookie()
        try:
            c.load(cookie_header)
        except cookies.CookieError:
            return False
        given = c["litha_face"].value if "litha_face" in c else ""
    return bool(given) and hmac.compare_digest(given.encode(), tok.encode())


def ask(question: str, smart: bool, root: Path = data.ROOT) -> dict:
    """Her answer to the owner's question, given her current state. smart=True asks Claude (paid, logged in her
    ledger by litha.claude; refused at her caps); otherwise her own local model."""
    digest = data.digest(data.state(root))
    prompt = ("You are Litha, the AI that reviews, fixes and merges pull requests across the owner's repositories. "
              "The owner asks you something from your local dashboard. Answer briefly and plainly from the state below; "
              "say so when the state does not show the answer. Never invent numbers.\n\n"
              f"YOUR STATE NOW:\n{digest}\n\nOWNER: {question}")
    t = time.time()
    box: dict = {}

    def run():
        try:
            if smart:
                from litha import claude
                if not claude.ready():
                    box["a"] = "(Claude is not available now: no key, switched off, or her cap is reached.)"
                    return
                box["a"] = claude.ask(prompt, effort="low", what=f"face chat: {question[:60]}") or "(Claude gave no answer.)"
            else:
                from star.asset3d.llm import chat
                box["a"], _ = chat("litha", [{"role": "user", "content": prompt}], max_tokens=600, temperature=0.3,
                                   timeout=CHAT_WAIT)
        except Exception as e:  # noqa: BLE001 - the page shows what went wrong instead of hanging
            box["err"] = f"{type(e).__name__}: {data.redact(str(e))[:200]}"

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(CHAT_WAIT + 10)
    out = {"via": "claude" if smart else "litha", "seconds": round(time.time() - t, 1)}
    if "a" in box:
        out["answer"] = data.redact(box["a"])[:4000]
    else:
        out["error"] = box.get("err") or f"no answer within {CHAT_WAIT} s (her model may be busy with a run)"
    try:
        chatlog = root / "litha-face" / "chat.jsonl"
        chatlog.parent.mkdir(parents=True, exist_ok=True)
        with chatlog.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(t), "q": question[:500], **out}) + "\n")
    except OSError:
        pass
    return out


LOGIN = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,
initial-scale=1"><title>Litha sign in</title><link rel="stylesheet" href="/static/style.css"></head><body class="login">
<form method="post" action="/login"><h1>Litha</h1><p>Paste the token from <code>%USERPROFILE%\\.star\\litha-face.token</code>
on her PC.</p><input name="token" type="password" autocomplete="current-password" aria-label="Token" required>
<button type="submit">Sign in</button></form></body></html>"""


class Server(ThreadingHTTPServer):
    allow_reuse_address = False              # Windows SO_REUSEADDR lets two servers share a port: fail loudly instead
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE"), 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "LithaFace"
    sys_version = ""
    lan = False
    tok = ""
    root = data.ROOT

    def log_message(self, format, *args):  # noqa: A002 - quiet: no request lines (cookies/tokens) in any log
        pass

    def _ok(self) -> bool:
        return allowed(self.client_address[0], self.headers.get("Host", ""), self.headers.get("Cookie", ""),
                       self.headers.get("X-Litha-Token", ""), self.tok, self.lan)

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path == "/static/style.css" or (path == "/login" and self.lan):
            pass                                              # the sign-in page and its style are public
        elif not self._ok():
            if self.lan and path in ("/", "/index.html"):
                return self._send(303, b"", "text/plain", {"Location": "/login"})
            return self._send(403, b"forbidden", "text/plain")
        if path == "/login":
            return self._send(200, LOGIN.encode("utf-8"), TYPES[".html"])
        if path in ("/", "/index.html"):
            path = "/static/index.html"
        if path == "/api/state":
            try:
                return self._json(data.state(self.root))
            except Exception as e:  # noqa: BLE001 - show the error in the page rather than a dead socket
                return self._json({"error": f"{type(e).__name__}: {data.redact(str(e))[:300]}"}, 500)
        if path == "/api/log":
            return self._json({"lines": data.log_tail(self.root)})
        if path.startswith("/static/"):
            f = (STATIC / path[len("/static/"):]).resolve()
            if f.parent == STATIC.resolve() and f.suffix in TYPES and f.is_file():
                return self._send(200, f.read_bytes(), TYPES[f.suffix])
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        n = min(int(self.headers.get("Content-Length") or 0), 20_000)
        body = self.rfile.read(n)
        if path == "/login" and self.lan:
            given = urllib.parse.parse_qs(body.decode("utf-8", "replace")).get("token", [""])[0].strip()
            if given and hmac.compare_digest(given.encode(), self.tok.encode()):
                return self._send(303, b"", "text/plain", {"Location": "/", "Set-Cookie":
                                  f"litha_face={self.tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000"})
            time.sleep(1)                                      # slow down guessing
            return self._send(403, b"wrong token", "text/plain")
        if not self._ok() or self.headers.get("X-Litha-Face") != "1" or \
                not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._send(403, b"forbidden", "text/plain")
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        if path == "/api/control":
            try:
                return self._json(controls.apply(str(req.get("control")), req.get("value"), self.root))
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if path == "/api/chat":
            q = str(req.get("q", "")).strip()[:1000]
            if not q:
                return self._json({"error": "empty question"}, 400)
            return self._json(ask(q, bool(req.get("smart")), self.root))
        return self._send(404, b"not found", "text/plain")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.face")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--lan", action="store_true", help="listen on every interface; other devices need the token")
    a = ap.parse_args(argv)
    Handler.lan = a.lan
    Handler.tok = token()
    try:
        srv = Server(("0.0.0.0" if a.lan else "127.0.0.1", a.port), Handler)
    except OSError as e:
        print(f"Litha's face: port {a.port} is taken ({e}); try --port", flush=True)
        return 1
    print(f"Litha's face: http://127.0.0.1:{a.port}/" + (f"  (LAN on port {a.port}: sign in with the token in {TOKEN})"
                                                          if a.lan else ""), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
