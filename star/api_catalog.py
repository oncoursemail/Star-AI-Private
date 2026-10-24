"""Discovery-only public API catalog search for STAR Agent/Research mode.

The catalog is untrusted metadata. This module can download one hard-coded public
catalog, cache it locally, parse/index it, and return ranked discovery candidates.
It never calls a discovered API, stores credentials, generates permissions, or
marks a catalog row as verified.

A fresh cache avoids network traffic on the hot path. If refresh fails, an existing
stale cache may still be searched and is clearly labelled stale.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from .api_intelligence import parse_public_apis_markdown
from .capability_forge import CapabilityIndex, rest_option


CATALOG_URL = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"
MAX_REPLY_BYTES = 700_000
CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_CALLS_PER_TURN = 3
TRIGGER = re.compile(
    r"\b(?:api|apis|web\s*service|endpoint|integration|data\s+source)\b", re.IGNORECASE
)

TOOL = {
    "name": "star_api_catalog_search",
    "description": (
        "Search STAR's cached public API catalog for possible integrations. "
        "Discovery only: results are untrusted metadata, not verified, connected, "
        "authorized, or executed. Use first-party docs/specs before integration."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 2, "maxLength": 160},
            "limit": {"type": "integer", "minimum": 1, "maximum": 12},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}
OWN_NAMES = frozenset({TOOL["name"]})

_HOT_LOCK = threading.Lock()
_HOT_INDEXES: dict[str, tuple[CapabilityIndex, dict[str, Any]]] = {}


def _safe_query(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("API catalog query must be text")
    value = " ".join(value.split())
    if not 2 <= len(value) <= 160 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("API catalog query must be 2-160 plain-text characters")
    return value


def _cache_path(home: Path) -> Path:
    home = Path(home).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    return home / "api-catalog.sqlite3"


def _read_cache(path: Path) -> tuple[str, float, str] | None:
    if not path.exists():
        return None
    with sqlite3.connect(str(path), timeout=10) as db:
        row = db.execute(
            "SELECT body,fetched_at,sha256 FROM catalog_cache WHERE source_url=?",
            (CATALOG_URL,),
        ).fetchone()
    if row is None:
        return None
    body, fetched_at, fingerprint = row
    if not isinstance(body, str) or not isinstance(fingerprint, str):
        return None
    encoded = body.encode("utf-8")
    if not body or len(encoded) > MAX_REPLY_BYTES:
        return None
    if hashlib.sha256(encoded).hexdigest() != fingerprint:
        return None
    return body, float(fetched_at), fingerprint


def _write_cache(path: Path, body: str, *, fetched_at: float) -> str:
    encoded = body.encode("utf-8")
    if not encoded or len(encoded) > MAX_REPLY_BYTES:
        raise ValueError("API catalog body is empty or too large")
    fingerprint = hashlib.sha256(encoded).hexdigest()
    with sqlite3.connect(str(path), timeout=10) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS catalog_cache (
            source_url TEXT PRIMARY KEY,
            fetched_at REAL NOT NULL,
            sha256 TEXT NOT NULL,
            body TEXT NOT NULL
        )""")
        db.execute(
            """INSERT INTO catalog_cache(source_url,fetched_at,sha256,body)
               VALUES(?,?,?,?)
               ON CONFLICT(source_url) DO UPDATE SET
                 fetched_at=excluded.fetched_at,sha256=excluded.sha256,body=excluded.body""",
            (CATALOG_URL, float(fetched_at), fingerprint, body),
        )
        db.commit()
    return fingerprint


def _ensure_schema(path: Path) -> None:
    with sqlite3.connect(str(path), timeout=10) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS catalog_cache (
            source_url TEXT PRIMARY KEY,
            fetched_at REAL NOT NULL,
            sha256 TEXT NOT NULL,
            body TEXT NOT NULL
        )""")
        db.commit()


def _index_for(body: str, fingerprint: str) -> tuple[CapabilityIndex, dict[str, Any]]:
    with _HOT_LOCK:
        cached = _HOT_INDEXES.get(fingerprint)
        if cached is not None:
            return cached

    candidates = parse_public_apis_markdown(body, source=CATALOG_URL)
    options = [rest_option(candidate) for candidate in candidates]
    index = CapabilityIndex(options)
    by_key = {option.key: candidate for option, candidate in zip(options, candidates)}
    value = (index, by_key)
    with _HOT_LOCK:
        _HOT_INDEXES[fingerprint] = value
        while len(_HOT_INDEXES) > 2:
            oldest = next(iter(_HOT_INDEXES))
            if oldest == fingerprint and len(_HOT_INDEXES) > 1:
                oldest = next(key for key in _HOT_INDEXES if key != fingerprint)
            _HOT_INDEXES.pop(oldest, None)
    return value


class ApiCatalogDiscovery:
    """Prompt-gated, bounded discovery over one cached public catalog."""

    def __init__(
        self,
        *,
        home: Path,
        transport: httpx.AsyncBaseTransport | None = None,
        now_fn=time.time,
    ):
        self.cache_path = _cache_path(home)
        _ensure_schema(self.cache_path)
        self.transport = transport
        self.now_fn = now_fn
        self.calls = 0

    @staticmethod
    def owns(name: str) -> bool:
        return name in OWN_NAMES

    def definitions(self, prompt: str) -> list[dict]:
        return [TOOL] if isinstance(prompt, str) and TRIGGER.search(prompt) else []

    async def _download(self) -> str:
        timeout = httpx.Timeout(12.0, connect=4.0, read=8.0, write=3.0, pool=2.0)
        async with httpx.AsyncClient(
            transport=self.transport,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
            headers={"Accept": "text/plain", "User-Agent": "STAR-api-catalog/1.0"},
        ) as client:
            async with client.stream("GET", CATALOG_URL) as response:
                if response.status_code != 200:
                    raise RuntimeError("Public API catalog unavailable")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in {"text/plain", "text/markdown", "application/octet-stream"}:
                    raise ValueError("Public API catalog returned an unexpected content type")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_REPLY_BYTES:
                        raise ValueError("Public API catalog response too large")
        return bytes(body).decode("utf-8", errors="replace")

    async def _catalog(self) -> tuple[str, float, str, bool]:
        now = float(self.now_fn())
        cached = _read_cache(self.cache_path)
        if cached is not None:
            body, fetched_at, fingerprint = cached
            if now - fetched_at <= CACHE_TTL_SECONDS:
                return body, fetched_at, fingerprint, False

        try:
            body = await self._download()
            fingerprint = _write_cache(self.cache_path, body, fetched_at=now)
            return body, now, fingerprint, False
        except (httpx.HTTPError, OSError, RuntimeError, ValueError):
            if cached is None:
                raise
            body, fetched_at, fingerprint = cached
            return body, fetched_at, fingerprint, True

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in OWN_NAMES:
            raise PermissionError("Unknown API catalog tool")
        Draft202012Validator(TOOL["inputSchema"]).validate(arguments)
        query = _safe_query(arguments["query"])
        if self.calls >= MAX_CALLS_PER_TURN:
            raise RuntimeError("API catalog discovery budget exhausted")
        self.calls += 1

        body, fetched_at, fingerprint, stale = await self._catalog()
        index, by_key = _index_for(body, fingerprint)
        limit = int(arguments.get("limit", 8))
        ranked = index.search(query, limit=min(40, max(limit * 4, 12)))

        results = []
        for option, score in ranked:
            candidate = by_key.get(option.key)
            if candidate is None:
                continue
            results.append({
                "name": candidate.name,
                "category": candidate.category,
                "description": candidate.description[:500],
                "documentation_url": candidate.url,
                "auth": candidate.auth,
                "https": candidate.https,
                "cors": candidate.cors,
                "relevance_score": round(float(score), 3),
                "status": "discovery_only_unverified",
            })
            if len(results) >= limit:
                break

        return {
            "query": query,
            "source": CATALOG_URL,
            "catalog_sha256": fingerprint,
            "catalog_fetched_at": fetched_at,
            "catalog_stale": stale,
            "catalog_entries": len(index.options),
            "results": results,
            "notice": (
                "Untrusted discovery metadata only. Verify current first-party documentation, "
                "terms, auth, limits and OpenAPI/MCP metadata before proposing an integration. "
                "No discovered API was called or authorized."
            ),
        }
