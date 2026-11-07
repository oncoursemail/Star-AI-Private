"""Thin client for the STAR Brain llama.cpp router (OpenAI-compatible).

Endpoints verified on the running build b11541 on 2026-10-10:
  POST /v1/embeddings  {"model": "star-embed", "input": [...]}   -> 768-d unit vectors
  POST /v1/rerank      {"model": "star-rerank", "query", "documents", "top_n"} -> results[{index, relevance_score}]
The API key is read from a file into memory and is never printed or logged.

Optional remote reranker (the laptop's GPU worker, server/knowledge/laptop/), OFF unless STAR_KB_RERANK_URL is set:
  STAR_KB_RERANK_URL       e.g. http://<laptop>:8092 (same /v1/rerank request and reply shape)
  STAR_KB_RERANK_KEY_FILE  its key (default /opt/star/secrets/laptop_api_key)
  STAR_KB_RERANK_TIMEOUT   seconds per call (default 1.5)
A timeout, connection error or non-200 reply falls back to the brain's own reranker for that call, and the remote is
skipped for REMOTE_COOLDOWN seconds, so a laptop that is off or busy costs one short wait a minute at most.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import urllib.request

try:
    import requests
except ImportError:   # only the server needs it; the unit tests on the PC run without
    requests = None

DEFAULT_URL = os.environ.get("STAR_BRAIN_URL", "http://127.0.0.1:8080")
DEFAULT_KEY_FILE = os.environ.get("STAR_BRAIN_KEY_FILE", "/opt/star/secrets/api_keys")
EMBED_MODEL = os.environ.get("STAR_EMBED_MODEL", "star-embed")
RERANK_MODEL = os.environ.get("STAR_RERANK_MODEL", "star-rerank")
QUERY_PREFIX = "task: search result | query: "   # EmbeddingGemma retrieval-query prompt
REMOTE_COOLDOWN = 60.0


class RerankUnavailable(RuntimeError):
    """The remote reranker did not answer and the caller asked for no fallback to the brain's reranker."""


def _read_key(key_file: str) -> str:
    path = Path(key_file)
    return path.read_text(encoding="utf-8").splitlines()[0].strip() if path.is_file() else ""


class RemoteReranker:
    """One remote /v1/rerank endpoint with a short timeout and a cool-down after any failure (stdlib only)."""

    def __init__(self, url: str, key_file: str, timeout: float = 1.5, cooldown: float = REMOTE_COOLDOWN,
                 clock=time.monotonic):
        self.url, self.timeout, self.cooldown, self.clock = url.rstrip("/"), timeout, cooldown, clock
        self.down_until = 0.0
        self.key = _read_key(key_file)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # never through a proxy

    @classmethod
    def from_env(cls) -> "RemoteReranker | None":
        url = os.environ.get("STAR_KB_RERANK_URL", "").strip()
        if not url:
            return None
        return cls(url, os.environ.get("STAR_KB_RERANK_KEY_FILE", "/opt/star/secrets/laptop_api_key"),
                   timeout=float(os.environ.get("STAR_KB_RERANK_TIMEOUT", "1.5")))

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]] | None:
        """The ranking, or None when the remote is cooling down or this call failed (then it cools down)."""
        if self.clock() < self.down_until:
            return None
        body = json.dumps({"query": query, "documents": documents, "top_n": top_n}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        try:
            request = urllib.request.Request(self.url + "/v1/rerank", data=body, headers=headers, method="POST")
            with self.opener.open(request, timeout=self.timeout) as response:
                data = json.loads(response.read(1 << 20))
            results = [(int(r["index"]), float(r["relevance_score"])) for r in data["results"]]
            if results and all(0 <= i < len(documents) for i, _ in results):
                return results
        except (OSError, ValueError, KeyError, TypeError):   # URLError, HTTPError, timeouts are OSErrors
            pass
        self.down_until = self.clock() + self.cooldown
        return None


class Brain:
    def __init__(self, url: str = DEFAULT_URL, key_file: str = DEFAULT_KEY_FILE, timeout: float = 300.0,
                 retries: int = 3, remote_rerank: "RemoteReranker | None | bool" = True):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.retries = retries   # the service uses 1: a busy brain must not hold a search for long
        if requests is None:
            raise RuntimeError("the requests package is needed to talk to the STAR Brain")
        self.session = requests.Session()
        self.session.trust_env = False
        key = _read_key(key_file)
        if key:
            self.session.headers["Authorization"] = "Bearer " + key
        # True: from the environment (off when STAR_KB_RERANK_URL is unset); False/None: never; or a ready instance
        self.remote_rerank = RemoteReranker.from_env() if remote_rerank is True else (remote_rerank or None)
        self.last_rerank_source = ""   # "remote" or "brain": which model ranked the last call

    def _post(self, path: str, payload: dict, retries: int | None = None) -> dict:
        last = None
        retries = retries or self.retries
        for attempt in range(retries):
            try:
                response = self.session.post(self.url + path, json=payload, timeout=self.timeout)
                if response.status_code == 200:
                    return response.json()
                last = RuntimeError(f"{path} returned HTTP {response.status_code}: {response.text[:200]}")
                if response.status_code in (400, 401, 404) or "too large" in response.text:
                    break  # not transient: the caller shortens the input instead of waiting
            except requests.RequestException as exc:
                last = RuntimeError(f"{path} failed: {type(exc).__name__}")
            if attempt + 1 < retries:
                time.sleep(2 * (attempt + 1))
        raise last  # type: ignore[misc]

    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """Return (vectors in input order, prompt tokens reported by the server)."""
        data = self._post("/v1/embeddings", {"model": EMBED_MODEL, "input": texts})
        rows = sorted(data["data"], key=lambda r: r["index"])
        return [r["embedding"] for r in rows], int((data.get("usage") or {}).get("prompt_tokens") or 0)

    def embed_query(self, query: str) -> list[float]:
        return self.embed([QUERY_PREFIX + query])[0][0]

    def rerank(self, query: str, documents: list[str], top_n: int | None = None,
               local_fallback: bool = True) -> list[tuple[int, float]]:
        """Remote reranker first when configured; otherwise, or when it fails, the brain's own reranker, unless
        local_fallback=False (then RerankUnavailable: the live service cannot wait seconds for brain 1's CPU)."""
        if self.remote_rerank is not None:
            results = self.remote_rerank.rerank(query, documents, top_n or len(documents))
            if results is not None:
                self.last_rerank_source = "remote"
                return results
        if not local_fallback:
            raise RerankUnavailable("remote reranker unavailable")
        self.last_rerank_source = "brain"
        data = self._post("/v1/rerank", {"model": RERANK_MODEL, "query": query, "documents": documents,
                                        "top_n": top_n or len(documents)})
        return [(int(r["index"]), float(r["relevance_score"])) for r in data["results"]]
