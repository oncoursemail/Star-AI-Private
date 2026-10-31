#!/usr/bin/env python3
"""HTTP front for real-server loads, run INSIDE the mc-plugins container next to the warm javac service (stdlib only).

    POST /load {"kind": "plugin", "job": <loadtest.py job>}   Bearer token (the javac service's /opt/mcp/token)
         -> loadtest.py's result ({stage, ok, loaded, errors, commands, log_excerpt, ...})
    GET  /health

One load at a time (a Paper/Fabric/NeoForge boot takes 5-55 s and the servers share their folders); a request that
waits longer than LOAD_WAIT_S gets 503 so the agent loop keeps its static result instead of hanging. Bodies (user
code) are never logged.

    LOAD_PORT=8106 python3 loadfront.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MCP = os.environ.get("MCP_HOME", "/opt/mcp")
TOKEN_FILE = os.environ.get("LOAD_TOKEN_FILE", MCP + "/token")
LOAD_WAIT_S = float(os.environ.get("LOAD_WAIT_S", "120"))
LOAD_TIMEOUT_S = int(os.environ.get("LOAD_TIMEOUT_S", "600"))
LOCK = threading.Lock()


def run_plugin(job: dict) -> dict:
    jid = "agent-" + uuid.uuid4().hex[:12]
    job = {**job, "id": jid}
    os.makedirs(MCP + "/jobs", exist_ok=True)
    path = f"{MCP}/jobs/{jid}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(job, f)
    try:
        p = subprocess.run([sys.executable, MCP + "/loadtest.py", path], capture_output=True, text=True,
                           timeout=LOAD_TIMEOUT_S)
        lines = [ln for ln in p.stdout.splitlines() if ln.strip().startswith("{")]
        return json.loads(lines[-1]) if lines else {"ok": False, "stage": "harness", "errors": [p.stderr[-400:]]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stage": "harness", "errors": ["load timed out"]}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
        work = os.path.join(MCP, "work", re.sub(r"[^\w.-]", "_", jid))
        subprocess.run(["rm", "-rf", work], check=False)


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, status: int, obj: dict):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"status": "ok", "busy": LOCK.locked()})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not token or self.headers.get("Authorization", "") != "Bearer " + token:
                return self._send(401, {"error": "bad token"})
            if self.path != "/load":
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1 << 20:
                return self._send(413, {"error": "too large"})
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                job = req["job"]
                assert req.get("kind") == "plugin" and isinstance(job, dict) and isinstance(job.get("sources"), dict)
                assert job.get("target") in ("paper", "spigot", "velocity", "fabric", "fabric-mojmap", "neoforge")
            except (ValueError, KeyError, AssertionError, TypeError):
                return self._send(400, {"error": "send {kind: plugin, job: {target, sources, resources, commands}}"})
            if not LOCK.acquire(timeout=LOAD_WAIT_S):
                return self._send(503, {"error": "load busy"})
            try:
                return self._send(200, run_plugin(job))
            finally:
                LOCK.release()

    return Handler


def main() -> int:
    token = open(TOKEN_FILE, encoding="utf-8").read().strip() if os.path.isfile(TOKEN_FILE) else ""
    srv = ThreadingHTTPServer((os.environ.get("LOAD_LISTEN", "0.0.0.0"), int(os.environ.get("LOAD_PORT", "8106"))),
                              make_handler(token))
    srv.daemon_threads = True
    print("star-load front ready", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
