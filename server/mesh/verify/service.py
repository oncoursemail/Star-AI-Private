"""HTTP front of the verifier, a sibling of the mesh router in the star-mesh container (default :8101).

    GET  /health                      no auth: {"status", "dump": {version, fetched}, "luau_analyze": bool}
    POST /mesh/verify                 Bearer key (same keys as the router/brain)
         body {"code": "...", "language"?: "luau|csharp|minecraft|mcfunction"} or {"answer": "<markdown>"}
         -> {"ok", "needs_fix", "blocks": [{index, language, ok, needs_fix, problems: [{kind, severity, name,
             message, suggestion, line}]}], "problems": [...prose...], "ms", "dump"}
    POST /mesh/verify?fix=1           also repairs failing blocks through the router's `litha` (max 2 rounds; the
                                      client's Authorization header is forwarded) -> {"answer", "ok", "rounds",
                                      "changes", "before", "after", "verify", "model_ms", "ms"}

    PYTHONPATH=server python -m mesh.verify [verify.json]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..router import KeyFile
from .apidump import ApiIndex
from .core import Verifier

DEFAULTS = {
    "listen": "0.0.0.0",
    "port": 8101,
    "index": "/var/lib/star-verify/roblox-api-index.json",
    "luau_analyze": "/opt/star-verify/bin/luau-analyze",
    "router_url": "http://127.0.0.1:8100",
    "fix_model": "litha",
    "fix_rounds": 2,
    "fix_max_tokens": 2048,
    "fix_timeout_s": 180,
    "client_keys_file": "/etc/star-mesh/api_keys",
    "max_body_kb": 512,
    "docs_url": "http://127.0.0.1:8102",      # official docs entries for the fix loop ("" = off)
    "docs_timeout_s": 1.0,
}


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    path = path or os.environ.get("STAR_VERIFY_CONFIG", "")
    if path and Path(path).is_file():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    return cfg


def model_caller(cfg: dict, auth: str):
    """call(messages) -> reply text, through the mesh router (fast tier, thinking off)."""
    def call(messages):
        body = json.dumps({"model": cfg["fix_model"], "messages": messages, "temperature": 0.2, "stream": False,
                           "max_tokens": cfg["fix_max_tokens"],
                           "chat_template_kwargs": {"enable_thinking": False},
                           "mesh_docs": False}).encode()      # the fix prompt carries its own doc entries
        req = urllib.request.Request(cfg["router_url"].rstrip("/") + "/v1/chat/completions", body,
                                     {"Content-Type": "application/json", "Authorization": auth})
        with urllib.request.urlopen(req, timeout=cfg["fix_timeout_s"]) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"].get("content") or ""
    return call


def docs_lookup(cfg: dict, auth: str):
    """docs(names) -> exact entries text from the docs service ('' when off, down or late)."""
    def docs(names):
        if not cfg.get("docs_url") or not names:
            return ""
        req = urllib.request.Request(cfg["docs_url"].rstrip("/") + "/mesh/docs/entries",
                                     json.dumps({"names": list(names)}).encode(),
                                     {"Content-Type": "application/json", "Authorization": auth})
        try:
            with urllib.request.urlopen(req, timeout=cfg["docs_timeout_s"]) as r:
                return json.loads(r.read()).get("text") or ""
        except (OSError, ValueError):
            return ""
    return docs


def make_handler(cfg: dict, verifier: Verifier, keys, caller_factory=model_caller, docs_factory=docs_lookup):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "star-verify/1"

        def log_message(self, fmt, *args):      # no request logging (bodies may hold user code)
            pass

        def _send(self, status, obj):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urllib.parse.urlsplit(self.path).path == "/health":
                return self._send(200, {"status": "ok", "dump": verifier.api.meta,
                                        "luau_analyze": bool(verifier.luau.analyzer)})
            return self._send(404, {"error": {"message": "not found"}})

        def do_POST(self):
            url = urllib.parse.urlsplit(self.path)
            if url.path != "/mesh/verify":
                return self._send(404, {"error": {"message": "not found"}})
            auth = self.headers.get("Authorization", "")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if not token or not keys.check(token):
                return self._send(401, {"error": {"message": "invalid api key"}})
            n = int(self.headers.get("Content-Length") or 0)
            if n > cfg["max_body_kb"] << 10:
                return self._send(413, {"error": {"message": "request too large"}})
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                text = req.get("answer") or req.get("code") or ""
                assert isinstance(text, str) and text.strip()
            except (ValueError, AssertionError, AttributeError):
                return self._send(400, {"error": {"message": "send {\"code\": ...} or {\"answer\": ...}"}})
            lang = req.get("language") or ("auto" if not req.get("answer") else None)
            fix = urllib.parse.parse_qs(url.query).get("fix", ["0"])[0] in ("1", "true", "yes")
            if not fix:
                return self._send(200, verifier.verify(text, lang))
            rounds = max(1, min(int(req.get("rounds") or cfg["fix_rounds"]), cfg["fix_rounds"]))
            docs = docs_factory(cfg, auth) if req.get("docs") is not False else None
            return self._send(200, verifier.fix(text, caller_factory(cfg, auth), lang, rounds, docs))

    return Handler


def serve(cfg: dict, caller_factory=model_caller) -> ThreadingHTTPServer:
    api = ApiIndex.load(cfg["index"])
    verifier = Verifier(api, cfg.get("luau_analyze"))
    srv = ThreadingHTTPServer((cfg["listen"], cfg["port"]),
                              make_handler(cfg, verifier, KeyFile(cfg["client_keys_file"]), caller_factory))
    srv.daemon_threads = True
    return srv


def main(argv: list[str]) -> int:
    cfg = load_config(argv[0] if argv else None)
    srv = serve(cfg)
    print(f"star-verify on {cfg['listen']}:{cfg['port']}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
