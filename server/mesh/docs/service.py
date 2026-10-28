"""HTTP front of the docs index, a sibling of the mesh router in the star-mesh container (default :8102).

    GET  /health                 no auth: {"status", "meta" (sources, commits, dates, licenses), "vectors"}
    GET  /mesh/docs?q=...&k=5    Bearer key: exact entries for the API names in q + top guide passages (with URLs)
    POST /mesh/docs/block        {"question", "extra"?, "context"?, "budget"?} -> the compact "Docs" block the router
                                 puts in front of a Litha question ({"text": ""} for chit-chat, Unity, Minecraft ...)
    POST /mesh/docs/entries      {"names": [...]} -> {"text", "found"}: exact entries (the verifier's fix loop)

The router forwards /mesh/docs* here, so clients use the router's address and key.

    PYTHONPATH=server python -m mesh.docs [docs.json]
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..router import KeyFile
from .index import DocsIndex, format_entry

DEFAULTS = {
    "listen": "127.0.0.1",                     # only the router and the verifier call it (same container)
    "port": 8102,
    "index": "/var/lib/star-docs/docs.db",
    "client_keys_file": "/etc/star-mesh/api_keys",
    "embed_url": "http://127.0.0.1:8100",      # the router passes /v1/embeddings through to the brain (star-embed)
    "embed_model": "star-embed",
    "embed_prefix": "task: search result | query: ",
    "embed_timeout_s": 0.6,
    "dense_in_block": False,                    # measured: docs/agents/litha-docs-20261028.md
    "dense_in_search": True,
    "budget_tokens": 500,
    "block_passages": 0,                        # guide passages in the block: measured harmful (wrong guides followed)
    "max_body_kb": 256,
}


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    path = path or os.environ.get("STAR_DOCS_CONFIG", "")
    if path and Path(path).is_file():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    return cfg


def embedder(cfg: dict, keys):
    """embed(text) -> vector or None (never raises; late = None)."""
    def embed(text: str):
        body = json.dumps({"model": cfg["embed_model"], "input": cfg["embed_prefix"] + text[:1000]}).encode()
        req = urllib.request.Request(cfg["embed_url"].rstrip("/") + "/v1/embeddings", body,
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {keys.first()}"})
        try:
            with urllib.request.urlopen(req, timeout=cfg["embed_timeout_s"]) as r:
                return json.loads(r.read())["data"][0]["embedding"]
        except Exception:      # noqa: BLE001 - the docs answer without embeddings
            return None
    return embed


def entry_json(row: dict) -> dict:
    return {"name": row["name"], "kind": row["kind"], "signature": row["sig"], "summary": row["summary"],
            "deprecated": bool(row["deprecated"]), "deprecation": row["depmsg"] or None, "url": row["url"],
            "line": format_entry(row)}


def make_handler(cfg: dict, idx: DocsIndex, keys, embed):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "star-docs/1"

        def log_message(self, fmt, *args):      # no request logging (questions may be personal)
            pass

        def _send(self, status, obj):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            auth = self.headers.get("Authorization", "")
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            if not token or not keys.check(token):
                self._send(401, {"error": {"message": "invalid api key"}})
                return False
            return True

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            if url.path == "/health":
                return self._send(200, {"status": "ok", "meta": idx.meta, "vectors": len(idx.vectors)})
            if url.path != "/mesh/docs":
                return self._send(404, {"error": {"message": "not found"}})
            if not self._authed():
                return
            qs = urllib.parse.parse_qs(url.query)
            q = (qs.get("q") or [""])[0].strip()[:2000]
            if not q:
                return self._send(400, {"error": {"message": "send ?q=<question or API name>"}})
            k = max(1, min(int((qs.get("k") or ["5"])[0] or 5), 20))
            t0 = time.perf_counter()
            vec = embed(q) if cfg["dense_in_search"] and (qs.get("dense") or ["1"])[0] != "0" else None
            entries = [entry_json(idx.entry(n)) for n in idx.names_in(q)]
            passages = [{key: p[key] for key in ("title", "heading", "url", "body", "bm25", "cos")}
                        for p in idx.search(q, k, vec)]
            return self._send(200, {"entries": entries, "passages": passages, "dense": vec is not None,
                                    "ms": round((time.perf_counter() - t0) * 1000, 1),
                                    "source": "Roblox Creator Docs (CC-BY-4.0, code MIT) + Luau docs (MIT)"})

        def do_POST(self):
            path = urllib.parse.urlsplit(self.path).path
            if path not in ("/mesh/docs/block", "/mesh/docs/entries"):
                return self._send(404, {"error": {"message": "not found"}})
            if not self._authed():
                return
            n = int(self.headers.get("Content-Length") or 0)
            if n > cfg["max_body_kb"] << 10:
                return self._send(413, {"error": {"message": "request too large"}})
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                assert isinstance(req, dict)
            except (ValueError, AssertionError):
                return self._send(400, {"error": {"message": "body must be a JSON object"}})
            if path == "/mesh/docs/entries":
                names = [str(x)[:120] for x in req.get("names") or [] if x][:24]
                found = [r["name"] for r in (idx.entry(x) for x in names) if r]
                return self._send(200, {"text": idx.entries_text(names), "found": found})
            question = str(req.get("question") or "")[:4000]
            if not question.strip():
                return self._send(400, {"error": {"message": "send {\"question\": ...}"}})
            budget = max(100, min(int(req.get("budget") or cfg["budget_tokens"]), 1200))
            vec = None
            if cfg["dense_in_block"] and idx.vectors and idx.wants_docs(question, str(req.get("context") or "")):
                vec = embed(question)
            out = idx.block(question, str(req.get("extra") or "")[:8000], vec, str(req.get("context") or "")[:500],
                            budget, max_passages=cfg["block_passages"])
            out["dense"] = vec is not None
            return self._send(200, out)

    return Handler


def serve(cfg: dict) -> ThreadingHTTPServer:
    idx = DocsIndex(cfg["index"])
    keys = KeyFile(cfg["client_keys_file"])
    srv = ThreadingHTTPServer((cfg["listen"], cfg["port"]), make_handler(cfg, idx, keys, embedder(cfg, keys)))
    srv.daemon_threads = True
    return srv


def main(argv: list[str]) -> int:
    cfg = load_config(argv[0] if argv else None)
    srv = serve(cfg)
    print(f"star-docs on {cfg['listen']}:{cfg['port']}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
