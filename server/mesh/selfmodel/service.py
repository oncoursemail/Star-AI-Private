"""HTTP front of STAR's system self-model, a sibling of the mesh router in the star-mesh container (127.0.0.1:8103).

    GET  /health                        no auth: {"status", "age_s"}
    GET  /mesh/self                     Bearer key: the whole snapshot (+ reports summary, last history points)
    GET  /mesh/self/brief?q=&topic=&backend=&max=   Bearer key: {"text", "self", "topic"} short facts for a model
    POST /mesh/self/brief               the same with a JSON body {"q", "topic"?, "backend"?, "max"?} (the router uses it)
    GET  /mesh/self/schedule            Bearer key: where heavy work of her own can run now (free GPUs, brain idle)
    GET  /mesh/self/history?n=          Bearer key: compact state points over time
    POST /mesh/self/report              Bearer key or mesh token: a job reports (reports.py KINDS)

The router forwards /mesh/self* here, so clients use the router's address and key. A collector thread refreshes the
snapshot every `collect_every_s` (default 15 s); requests never wait for the sources.

    PYTHONPATH=server python -m mesh.selfmodel [self.json]
"""
from __future__ import annotations

import hmac
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import brief, collect
from .reports import History, Reports

DEFAULTS = {
    "listen": "127.0.0.1",
    "port": 8103,
    "router_url": "http://127.0.0.1:8100",
    "brain_url": "",
    "services": [],
    "deployed_files": {
        "router": "/opt/star-mesh/app/mesh/router.py",
        "verify": "/opt/star-verify/app/mesh/verify/core.py",
        "docs": "/opt/star-docs/app/mesh/docs/service.py",
        "selfmodel": "/opt/star-self/app/mesh/selfmodel/service.py",
    },
    "machines": {},
    "load_file": "/proc/loadavg",
    "client_keys_file": "/etc/star-mesh/api_keys",
    "mesh_token_file": "/etc/star-mesh/mesh_token",
    "state_dir": "/var/lib/star-self",
    "collect_every_s": 15.0,
    "history_every_s": 300.0,
    "timeout_s": 3.0,
    "heavy_min_vram_mb": 6000,
    "max_body_kb": 64,
}


class KeyFile:
    """Keys from a file (one per line, '#' comments), re-read when it changes; same format as the router's key file.
    (Not imported from router.py, so this service does not need the router's modules.) Values are never logged."""

    def __init__(self, path: str):
        self.path, self.mtime, self.keys = Path(path), None, []

    def _load(self) -> list[str]:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self.keys = []
            return self.keys
        if mtime != self.mtime:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            self.keys = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
            self.mtime = mtime
        return self.keys

    def first(self) -> str:
        keys = self._load()
        return keys[0] if keys else ""

    def check(self, token: str) -> bool:
        ok = False
        for key in self._load():
            ok |= hmac.compare_digest(token.encode(), key.encode())
        return ok


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    path = path or os.environ.get("STAR_SELF_CONFIG", "/etc/star-self/self.json")
    if path and Path(path).is_file():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    return cfg


class SelfModel:
    def __init__(self, cfg: dict, keys, fetch=collect.http_fetch, read_file=None):
        self.cfg, self.keys, self.fetch, self.read_file = cfg, keys, fetch, read_file
        self.reports = Reports(cfg["state_dir"])
        self.history = History(cfg["state_dir"], cfg["history_every_s"])
        self.snap: dict = {}
        self.lock = threading.Lock()

    def refresh(self) -> dict:
        snap = collect.collect(self.cfg, self.keys.first() or None, self.fetch, self.read_file)
        try:
            self.history.maybe_add(snap)
        except OSError:
            pass
        with self.lock:
            self.snap = snap
        return snap

    def view(self) -> dict:
        with self.lock:
            snap = dict(self.snap)
        snap["reports"] = self.reports.summary()
        return snap

    def upgrade_check(self, get=None, now: float | None = None) -> list[dict]:
        """Once a week (cfg "upgrade": {"components": ...}): official releases -> "upgrade" reports."""
        if not self.cfg.get("upgrade"):
            return []
        from ..upgrade import watch
        path = Path(self.cfg["state_dir"]) / "upgrade-state.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
        if not watch.due(state, now, float(self.cfg["upgrade"].get("every_s", watch.WEEK_S))):
            return []
        for r in self.reports.last("upgrade", 50):          # a node promoted a build: that is the current one now
            if r.get("component") == "llama.cpp" and r.get("decision") == "promote" and r.get("latest"):
                state.setdefault("llama.cpp", {})["current"] = r["latest"]
        recs = watch.check(self.cfg["upgrade"], state, get or watch.http_get, now)
        for r in recs:
            self.reports.add(r)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        return recs

    def loop(self, stop: threading.Event):
        while not stop.is_set():
            try:
                self.refresh()
            except Exception as e:   # a collector bug must not kill the service; it shows up in the snapshot
                with self.lock:
                    self.snap = {**self.snap, "collector_error": f"{type(e).__name__}: {e}"[:200]}
            try:
                self.upgrade_check()
            except Exception as e:
                self.reports.add({"kind": "error", "where": "upgrade watcher", "error": f"{type(e).__name__}: {e}"[:200]})
            stop.wait(self.cfg["collect_every_s"])


def make_handler(model: SelfModel, keys, mesh_token):
    cfg = model.cfg

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "star-self/1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, status, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _token(self) -> str:
            auth = self.headers.get("Authorization", "")
            return auth[7:].strip() if auth.lower().startswith("bearer ") else ""

        def _authed(self, allow_mesh: bool = False) -> bool:
            token = self._token()
            if token and (keys.check(token) or (allow_mesh and mesh_token.check(token))):
                return True
            self._send(401, {"error": {"message": "invalid api key"}})
            return False

        def _brief(self, q: dict) -> dict:
            text_q = str(q.get("q") or "")[:2000]
            topic = str(q.get("topic") or "") or brief.topic_of(text_q)
            try:
                max_chars = max(200, min(4000, int(q.get("max") or 1100)))
            except (TypeError, ValueError):
                max_chars = 1100
            return {"text": brief.render(model.view(), topic, str(q.get("backend") or "") or None, max_chars),
                    "self": brief.wants_self(text_q) if text_q else None, "topic": topic}

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/health":
                ts = model.snap.get("ts")
                return self._send(200, {"status": "ok", "age_s": round(time.time() - ts, 1) if ts else None})
            if not self._authed():
                return
            if url.path == "/mesh/self":
                view = model.view()
                view["history"] = model.history.points(24)
                return self._send(200, view)
            if url.path == "/mesh/self/brief":
                return self._send(200, self._brief(q))
            if url.path == "/mesh/self/schedule":
                return self._send(200, model.view().get("scheduling") or {})
            if url.path == "/mesh/self/history":
                try:
                    n = max(1, min(2016, int(q.get("n", "288"))))
                except ValueError:
                    n = 288
                return self._send(200, {"points": model.history.points(n)})
            return self._send(404, {"error": {"message": "not found"}})

        def do_POST(self):
            url = urllib.parse.urlsplit(self.path)
            if url.path not in ("/mesh/self/report", "/mesh/self/brief"):
                return self._send(404, {"error": {"message": "not found"}})
            if not self._authed(allow_mesh=url.path == "/mesh/self/report"):
                return
            n = int(self.headers.get("Content-Length") or 0)
            if n > cfg["max_body_kb"] * 1024:
                return self._send(413, {"error": {"message": "body too large"}})
            try:
                rep = json.loads(self.rfile.read(n) or b"{}")
                assert isinstance(rep, dict)
            except (ValueError, AssertionError):
                return self._send(400, {"error": {"message": "body must be a JSON object"}})
            if url.path == "/mesh/self/brief":
                return self._send(200, self._brief(rep))
            ok, why = model.reports.add(rep)
            return self._send(200 if ok else 400, {"ok": ok, "message": why})

    return Handler


def serve(cfg: dict, fetch=collect.http_fetch, read_file=None, start_collector: bool = True):
    keys = KeyFile(cfg["client_keys_file"])
    mesh_token = KeyFile(cfg["mesh_token_file"])
    model = SelfModel(cfg, keys, fetch, read_file)
    srv = ThreadingHTTPServer((cfg["listen"], cfg["port"]), make_handler(model, keys, mesh_token))
    srv.daemon_threads = True
    stop = threading.Event()
    if start_collector:
        threading.Thread(target=model.loop, args=(stop,), daemon=True).start()
    srv.self_model, srv.stop_collector = model, stop
    return srv


def main(argv: list[str]) -> int:
    cfg = load_config(argv[0] if argv else None)
    srv = serve(cfg)
    print(f"star-self on {cfg['listen']}:{cfg['port']}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
