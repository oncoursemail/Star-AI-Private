"""star-mesh-agent: the agent loop as an OpenAI-compatible endpoint, a sibling of the router in star-mesh (:8104).
The router sends model `litha-agent` here when the request is a build/code task (route.wants_agent); everything else
stays plain `litha` in the router.

    POST /v1/chat/completions   Bearer key (the router's keys). Body as for `litha`, plus optional
                                "mesh_agent_rounds" (<= 6) and "mesh_agent_budget_s" (<= 600).
        non-stream -> chat.completion; content = final answer + "> verified: ..." line; "mesh_agent" = trace
        stream     -> progress as `reasoning_content` deltas while it works, then the final content, one
                      {"object": "mesh.agent", ...} event, [DONE]
    GET  /health

    PYTHONPATH=server python -m mesh.agent.service [agent.json]
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..router import KeyFile
from . import checks as ck
from .loop import Agent
from .route import AGENT_MODEL, wants_agent

DEFAULTS = {
    "listen": "127.0.0.1",
    "port": 8104,
    "router_url": "http://127.0.0.1:8100",
    "verify_url": "http://127.0.0.1:8101",
    "polyglot_url": "",
    "polyglot_url_file": "/etc/star-mesh/polyglot_url",
    "polyglot_token_file": "/etc/star-mesh/polyglot_token",
    "load_url": "",                                  # loadfront.py in the mc-plugins container ("" = no real loads)
    "load_token_file": "/var/lib/star-verify/jvm_token",
    "client_keys_file": "/etc/star-mesh/api_keys",
    "max_rounds": 4,
    "budget_s": 240,
    "max_tokens": 3000,
    "max_parallel": 2,                               # agent runs at once (each holds at most one GPU slot at a time)
    "wait_s": 60,
    "call_timeout_s": 300,
}


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    path = path or os.environ.get("STAR_AGENT_CONFIG", "")
    if path and Path(path).is_file():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    return cfg


def router_caller(cfg: dict, auth: str, extra: dict):
    """call(messages, temperature, max_tokens) -> (text, finish_reason) through the router's `litha`."""
    def call(messages, temperature, max_tokens):
        body = {**extra, "model": "litha", "messages": messages, "temperature": temperature, "stream": False,
                "max_tokens": max_tokens}
        last: Exception | None = None
        for attempt in range(3):
            req = urllib.request.Request(cfg["router_url"].rstrip("/") + "/v1/chat/completions",
                                         json.dumps(body).encode(),
                                         {"Content-Type": "application/json", "Authorization": auth})
            try:
                with urllib.request.urlopen(req, timeout=cfg["call_timeout_s"]) as r:
                    data = json.loads(r.read())
                ch = data["choices"][0]
                return ch["message"].get("content") or "", ch.get("finish_reason")
            except urllib.error.HTTPError as e:
                last = e
                if e.code != 503:                    # 503 = mesh busy: back off and try again
                    raise
                time.sleep(10 * (attempt + 1))
        raise last or RuntimeError("router busy")
    return call


def build_checks(cfg: dict, auth: str) -> ck.Checks:
    sandbox = ck.SandboxClient.from_files(cfg.get("polyglot_url") or "", cfg.get("polyglot_url_file") or "",
                                          cfg.get("polyglot_token_file") or "")
    loader = None
    tok = Path(cfg.get("load_token_file") or "")
    if cfg.get("load_url") and tok.is_file():
        loader = ck.LoadClient(cfg["load_url"], tok.read_text(encoding="utf-8").strip())
    return ck.Checks(ck.VerifierClient(cfg["verify_url"], auth), sandbox, loader)


PASS_FIELDS = ("top_p", "chat_template_kwargs", "mesh_cache", "mesh_docs", "mesh_ground", "mesh_brain")


def make_handler(cfg: dict, keys, agent_factory=None):
    slots = threading.BoundedSemaphore(int(cfg["max_parallel"]))

    def default_factory(req: dict, auth: str, progress) -> Agent:
        extra = {k: req[k] for k in PASS_FIELDS if k in req}
        extra.setdefault("chat_template_kwargs", {"enable_thinking": False})
        return Agent(router_caller(cfg, auth, extra), build_checks(cfg, auth),
                     max_rounds=max(0, min(int(req.get("mesh_agent_rounds") or cfg["max_rounds"]), 6)),
                     budget_s=max(30.0, min(float(req.get("mesh_agent_budget_s") or cfg["budget_s"]), 600.0)),
                     progress=progress)

    factory = agent_factory or default_factory

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "star-agent/1"

        def log_message(self, fmt, *args):          # bodies hold user code: no request logging
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
                return self._send(200, {"status": "ok", "model": AGENT_MODEL})
            return self._send(404, {"error": {"message": "not found"}})

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                return self._send(404, {"error": {"message": "not found"}})
            auth = self.headers.get("Authorization", "")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if not token or not keys.check(token):
                return self._send(401, {"error": {"message": "invalid api key"}})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                messages = req["messages"]
                assert isinstance(messages, list) and messages
            except (ValueError, KeyError, AssertionError, TypeError):
                return self._send(400, {"error": {"message": "send {messages: [...]}"}})
            if not slots.acquire(timeout=cfg["wait_s"]):
                return self._send(503, {"error": {"message": "agent busy, try again", "type": "server_error"}})
            try:
                if req.get("stream"):
                    return self._stream(req, auth)
                agent = factory(req, auth, lambda text: None)
                out = agent.run(messages, float(req.get("temperature") or 0.3),
                                int(req.get("max_tokens") or cfg["max_tokens"]), build=wants_agent(messages))
                return self._send(200, completion(out))
            except Exception as e:                     # router down etc.: a clear error, never a half answer
                return self._send(502, {"error": {"message": f"agent: {type(e).__name__}: {e}"[:300],
                                                  "type": "server_error"}})
            finally:
                slots.release()

        def _stream(self, req: dict, auth: str):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            cid = "chatcmpl-agent-" + uuid.uuid4().hex[:16]
            q: queue.Queue = queue.Queue()
            result: dict = {}

            def work():
                try:
                    agent = factory(req, auth, lambda text: q.put(("p", text)))
                    result["out"] = agent.run(req["messages"], float(req.get("temperature") or 0.3),
                                              int(req.get("max_tokens") or cfg["max_tokens"]),
                                              build=wants_agent(req["messages"]))
                except Exception as e:
                    result["error"] = f"{type(e).__name__}: {e}"[:300]
                q.put(("end", None))

            threading.Thread(target=work, daemon=True).start()
            try:
                self._event(chunk(cid, {"role": "assistant", "content": ""}))
                while True:
                    try:
                        kind, text = q.get(timeout=10)
                    except queue.Empty:
                        self.wfile.write(b": working\n\n")         # keep the connection alive
                        self.wfile.flush()
                        continue
                    if kind == "end":
                        break
                    self._event(chunk(cid, {"reasoning_content": text + "\n"}))
                if "error" in result:
                    self._event({"error": {"message": "agent: " + result["error"], "type": "server_error"}})
                else:
                    out = result["out"]
                    self._event(chunk(cid, {"content": out["content"]}))
                    self._event({"object": "mesh.agent", "mesh_agent": summary(out)})
                    self._event(chunk(cid, {}, "stop"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                pass                                           # client went away; the run finishes in the background

        def _event(self, obj: dict):
            self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
            self.wfile.flush()

    return Handler


def chunk(cid: str, delta: dict, finish: str | None = None) -> dict:
    return {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": AGENT_MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


def summary(out: dict) -> dict:
    return {k: out.get(k) for k in ("verified", "ok", "rounds", "score", "passed", "problems", "seconds")} | {
        "trace": [{k: v for k, v in t.items() if k != "problems"} for t in out.get("trace", [])]}


def completion(out: dict) -> dict:
    return {"id": "chatcmpl-agent-" + uuid.uuid4().hex[:16], "object": "chat.completion", "created": int(time.time()),
            "model": AGENT_MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": out["content"]},
                         "finish_reason": "stop"}],
            "mesh_agent": summary(out)}


def serve(cfg: dict) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((cfg["listen"], cfg["port"]), make_handler(cfg, KeyFile(cfg["client_keys_file"])))
    srv.daemon_threads = True
    return srv


def main(argv: list[str]) -> int:
    cfg = load_config(argv[0] if argv else None)
    srv = serve(cfg)
    print(f"star-mesh-agent on {cfg['listen']}:{cfg['port']}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
