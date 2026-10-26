"""Embeddings for memory relevance: the brain's embedder when reachable, else a small local hash embedder.

`Embedder.embed(texts) -> (model_name, vectors)`. Every stored vector keeps its model name; two vectors are compared
only when they come from the same model, otherwise both sides fall back to the hash embedder (cheap, no network).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path

from .store import tokens

HASH_MODEL = "hash256"
HASH_DIM = 256


def _bucket(feature: str) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=4).digest()
    value = int.from_bytes(digest, "little")
    return value % HASH_DIM, (1.0 if value & 0x80000000 else -1.0)


def hash_vector(text: str) -> list[float]:
    """Signed feature hashing of content-word stems (weight 1) and adjacent pairs (0.5), L2-normalised."""
    words = tokens(text)
    vec = [0.0] * HASH_DIM
    for feature, weight in [(w, 1.0) for w in words] + [(f"{a}_{b}", 0.5) for a, b in zip(words, words[1:])]:
        index, sign = _bucket(feature)
        vec[index] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec))
    return [round(v / norm, 5) for v in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class HashEmbedder:
    model = HASH_MODEL

    def embed(self, texts: list[str]) -> tuple[str, list[list[float]]]:
        return HASH_MODEL, [hash_vector(t) for t in texts]


class RemoteEmbedder:
    """OpenAI-compatible /v1/embeddings on the brain (model star-embed). A failure switches to the hash embedder for
    `backoff_s`, so an unreachable server costs one short timeout, not one per memory."""

    def __init__(self, url: str, key: str, *, model: str = "star-embed", timeout_s: float = 3.0,
                 backoff_s: float = 600.0, opener=urllib.request.urlopen, clock=time.monotonic) -> None:
        url = url.rstrip("/")
        self.endpoint = url + ("/embeddings" if url.endswith("/v1") else "/v1/embeddings")
        self.key, self.model, self.timeout_s, self.backoff_s = key, model, timeout_s, backoff_s
        self.opener, self.clock = opener, clock
        self._down_until = 0.0
        self.fallback = HashEmbedder()

    def embed(self, texts: list[str]) -> tuple[str, list[list[float]]]:
        if not texts or self.clock() < self._down_until:
            return self.fallback.embed(texts)
        try:
            body = json.dumps({"model": self.model, "input": [t[:2000] for t in texts]}).encode("utf-8")
            request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
            with self.opener(request, timeout=self.timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))["data"]
            vectors = [list(map(float, row["embedding"])) for row in sorted(data, key=lambda r: r.get("index", 0))]
            if len(vectors) != len(texts):
                raise ValueError("embedding count mismatch")
            return f"remote:{self.model}", vectors
        except Exception:
            self._down_until = self.clock() + self.backoff_s
            return self.fallback.embed(texts)


def default_embedder(life_home, settings: dict):
    """The brain's embedder when allowed and configured (star-home config.json brain_url + key file), else hashing."""
    if not (settings.get("brain_enabled") and settings.get("remote_embed")) or life_home is None:
        return HashEmbedder()
    try:
        from ..home.control import load_config
        from ..server_key_file import read_key_file
        config = load_config(Path(life_home))
        url = str(config.get("brain_url") or "")
        if not url:
            return HashEmbedder()
        key = read_key_file(path=Path(config["key_file"])) if config.get("key_file") else read_key_file()
        return RemoteEmbedder(url, key)
    except Exception:
        return HashEmbedder()
