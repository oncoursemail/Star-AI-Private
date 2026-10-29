"""STAR laptop rerank worker: a cross-encoder on the laptop's GPU behind a tiny HTTP API (LAN only).

    GET  /health                      {"ok", "model", "loaded", "device"}          (no key)
    POST /v1/rerank  {query, documents, top_n?}  -> {"model", "results": [{index, relevance_score}]}   (Bearer key)

The reply has the same shape as llama.cpp's /v1/rerank, so starkb.client can use either. Runs offline: the model is
read from a local folder (HF_HUB_OFFLINE=1), nothing here touches the internet. The model moves to system RAM after
IDLE_SECONDS without a request (the owner plays games on this laptop) and back to the GPU on the next one (about 0.3 s;
a reload from disk took 2.2 s, longer than the client's 1.5 s timeout).
Only clients with a private or loopback address are answered; the firewall rule limits it to the LAN as well.

Two model kinds:
  qwen3   Qwen3-Reranker (a causal LM): score = P("yes") after the official judge prompt.
  seqcls  any AutoModelForSequenceClassification cross-encoder: score = sigmoid(logit).

Run: python rerank_worker.py --model-dir DIR --kind qwen3 --key-file FILE [--host 0.0.0.0] [--port 8092]
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import ipaddress
import json
import os
from pathlib import Path
import threading
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

MAX_BODY = 1 << 20              # 1 MiB request cap
MAX_DOCS = 64
MAX_TOKENS = 1024               # per (query, document) pair after the template
IDLE_SECONDS = 300

QWEN_PREFIX = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the "
               "Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
QWEN_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
QWEN_TASK = "Given a web search query, retrieve relevant passages that answer the query"


class Reranker:
    """Loads lazily, scores under one lock (one GPU), unloads when idle."""

    def __init__(self, model_dir: str, kind: str, device: str = "cuda"):
        if kind not in ("qwen3", "seqcls"):
            raise ValueError("kind must be qwen3 or seqcls")
        self.model_dir, self.kind, self.device = model_dir, kind, device
        self.name = Path(model_dir).name
        self.lock = threading.Lock()
        self.model = self.tok = None
        self.on_gpu = False
        self.last_used = 0.0

    def _load(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoModelForSequenceClassification, AutoTokenizer
        dtype = torch.float32   # GTX 1650 (TU117): fp32 matmul 1.7 TFLOPs, fp16 only 0.34 in PyTorch (measured)
        if self.kind == "qwen3":
            self.tok = AutoTokenizer.from_pretrained(self.model_dir, padding_side="left")
            self.model = AutoModelForCausalLM.from_pretrained(self.model_dir, dtype=dtype).to(self.device).eval()
            self.yes = self.tok.convert_tokens_to_ids("yes")
            self.no = self.tok.convert_tokens_to_ids("no")
            self.prefix = self.tok.encode(QWEN_PREFIX, add_special_tokens=False)
            self.suffix = self.tok.encode(QWEN_SUFFIX, add_special_tokens=False)
        else:
            self.tok = AutoTokenizer.from_pretrained(self.model_dir)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_dir, dtype=dtype)
            self.model = self.model.to(self.device).eval()
        # the first batches of a new size are slow on CUDA (5 of 145 real calls timed out after a load without this)
        with torch.inference_mode():
            for n in (10, 15):
                (self._qwen if self.kind == "qwen3" else self._seqcls)("warm up", ["warm up " * 120] * n)

    def unload_if_idle(self, now: float) -> bool:
        with self.lock:
            if not self.on_gpu or now - self.last_used < IDLE_SECONDS:
                return False
            import torch
            self.model.to("cpu")
            self.on_gpu = False
            if self.device == "cuda":
                torch.cuda.empty_cache()
            return True

    def score(self, query: str, documents: list[str]) -> list[float]:
        import torch
        with self.lock:
            if self.model is None:
                self._load()
            elif not self.on_gpu:
                self.model.to(self.device)
            self.on_gpu = True
            self.last_used = time.monotonic()
            with torch.inference_mode():
                scores = self._qwen(query, documents) if self.kind == "qwen3" else self._seqcls(query, documents)
            self.last_used = time.monotonic()
            return scores

    def _qwen(self, query: str, documents: list[str]) -> list[float]:
        import torch
        room = MAX_TOKENS - len(self.prefix) - len(self.suffix)
        rows = []
        for doc in documents:
            body = self.tok.encode(f"<Instruct>: {QWEN_TASK}\n<Query>: {query}\n<Document>: {doc}",
                                   add_special_tokens=False)[:room]
            rows.append(self.prefix + body + self.suffix)
        batch = self.tok.pad({"input_ids": rows}, padding=True, return_tensors="pt").to(self.device)
        logits = self.model(**batch, logits_to_keep=1).logits[:, -1, :]   # last position only: saves ~2 GB
        pair = torch.stack([logits[:, self.no], logits[:, self.yes]], dim=1).float()
        return torch.softmax(pair, dim=1)[:, 1].tolist()

    def _seqcls(self, query: str, documents: list[str]) -> list[float]:
        import torch
        batch = self.tok([query] * len(documents), documents, padding=True, truncation="only_second",
                         max_length=min(MAX_TOKENS, getattr(self.tok, "model_max_length", 512) or 512),
                         return_tensors="pt").to(self.device)
        logits = self.model(**batch).logits.float()
        return torch.sigmoid(logits[:, -1] if logits.shape[1] > 1 else logits[:, 0]).tolist()


def is_lan(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def make_handler(reranker: Reranker, key: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):   # no request logging (queries are the owner's)
            pass

        def _reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not is_lan(self.client_address[0]):
                return self._reply(403, {"error": "LAN only"})
            if self.path != "/health":
                return self._reply(404, {"error": "not found"})
            self._reply(200, {"ok": True, "model": reranker.name, "loaded": reranker.on_gpu,
                              "device": reranker.device})

        def do_POST(self):
            if not is_lan(self.client_address[0]):
                return self._reply(403, {"error": "LAN only"})
            if self.path != "/v1/rerank":
                return self._reply(404, {"error": "not found"})
            sent = self.headers.get("Authorization", "")
            if not key or not hmac.compare_digest(sent.encode(), ("Bearer " + key).encode()):
                return self._reply(401, {"error": "bad key"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                return self._reply(413 if length > MAX_BODY else 400, {"error": "body size"})
            try:
                body = json.loads(self.rfile.read(length))
                query, docs = body["query"], body["documents"]
                top_n = int(body.get("top_n") or len(docs))
                if not (isinstance(query, str) and isinstance(docs, list) and 0 < len(docs) <= MAX_DOCS
                        and all(isinstance(d, str) for d in docs)):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                return self._reply(400, {"error": f"need query (text) and 1..{MAX_DOCS} documents (text)"})
            try:
                scores = reranker.score(query, docs)
            except Exception as exc:   # e.g. CUDA out of memory while a game holds the GPU
                return self._reply(503, {"error": type(exc).__name__})
            order = sorted(range(len(docs)), key=lambda i: -scores[i])[:max(1, top_n)]
            self._reply(200, {"model": reranker.name,
                              "results": [{"index": i, "relevance_score": scores[i]} for i in order]})

    return Handler


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--kind", default="qwen3", choices=("qwen3", "seqcls"))
    ap.add_argument("--key-file", required=True)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--preload", action="store_true", help="load the model at start instead of on first use")
    ap.add_argument("--pause-file", default="", help="exit at once while this file exists (busy_guard.py writes it "
                    "while the owner games; this process runs in another logon session than the guard, so it cannot be killed from there)")
    args = ap.parse_args(argv)
    key = Path(args.key_file).read_text(encoding="utf-8").splitlines()[0].strip()
    reranker = Reranker(args.model_dir, args.kind, args.device)
    if args.preload:
        reranker.score("warm up", ["warm up"])

    def reaper():
        while True:
            time.sleep(30)
            reranker.unload_if_idle(time.monotonic())

    threading.Thread(target=reaper, daemon=True).start()
    if args.pause_file:
        def watch_pause():
            while True:
                if os.path.exists(args.pause_file):
                    os._exit(0)                      # frees the GPU at once; the supervisor waits for the file to go
                time.sleep(0.5)
        threading.Thread(target=watch_pause, daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(reranker, key))
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
