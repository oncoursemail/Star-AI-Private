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

from .api_intelligence import ApiCandidate, parse_public_apis_markdown
from .api_directory import ApiGuruDirectory, DirectoryEntry, DIRECTORY_URL
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
        "Search cached public APIs or APIs.guru OpenAPI definitions, or both. "
        "Use source=public for quickest lookups and source=all for deeper search. "
        "Discovery only: results never authorize access, installation, or execution."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 2, "maxLength": 160},
            "limit": {"type": "integer", "minimum": 1, "maximum": 12},
            "source": {"type": "string", "enum": ["public", "openapi", "all"]},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}
SPEC_TOOL = {
    "name": "star_api_spec_inspect",
    "description": (
        "Read one cached APIs.guru provider's machine-readable OpenAPI specification "
        "using its provider_id from star_api_catalog_search. Reports methods, "
        "auth and risks; NO endpoint execution, credentials or external $ref resolution."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"provider_id": {"type": "string", "minLength": 1, "maxLength": 180}},
        "required": ["provider_id"],
        "additionalProperties": False,
    },
}
OWN_NAMES = frozenset({TOOL["name"], SPEC_TOOL["name"]})

_HOT_LOCK = threading.Lock()
_HOT_INDEXES: dict[str, tuple[CapabilityIndex, dict[str, Any]]] = {}
_HOT_GURU: dict[str, tuple[CapabilityIndex, dict[str, DirectoryEntry]]] = {}


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


def _guru_index(snapshot) -> tuple[CapabilityIndex, dict[str, DirectoryEntry]]:
    with _HOT_LOCK:
        previous = _HOT_GURU.get(snapshot.sha256)
        if previous is not None:
            return previous
    candidates = [
        ApiCandidate(
            name=entry.title, url=entry.spec_url, description=entry.description,
            category=" ".join(entry.categories), auth="unknown", https=True,
            source=DIRECTORY_URL,
        ) for entry in snapshot.entries
    ]
    options = [rest_option(candidate) for candidate in candidates]
    index = CapabilityIndex(options)
    mapping = {option.key: entry for option, entry in zip(options, snapshot.entries)}
    with _HOT_LOCK:
        _HOT_GURU[snapshot.sha256] = (index, mapping)
        while len(_HOT_GURU) > 2:
            del _HOT_GURU[next(iter(_HOT_GURU))]
    return index, mapping


_HOT_COMBINED: dict[str, CapabilityIndex] = {}


def _combined_index(public_index: CapabilityIndex, guru_index: CapabilityIndex, fingerprint: str) -> CapabilityIndex:
    with _HOT_LOCK:
        existing = _HOT_COMBINED.get(fingerprint)
        if existing is not None:
            return existing
    index = CapabilityIndex((*public_index.options, *guru_index.options))
    with _HOT_LOCK:
        _HOT_COMBINED[fingerprint] = index
        while len(_HOT_COMBINED) > 2:
            del _HOT_COMBINED[next(iter(_HOT_COMBINED))]
    return index


class ApiCatalogDiscovery:
    """Prompt-gated, bounded API discovery over one or both cached public catalogs."""

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
        self.guru = ApiGuruDirectory(home=home, transport=transport, now_fn=now_fn)
        self.calls = 0

    @staticmethod
    def owns(name: str) -> bool:
        return name in OWN_NAMES

    def definitions(self, prompt: str) -> list[dict]:
        return [TOOL, SPEC_TOOL] if isinstance(prompt, str) and TRIGGER.search(prompt) else []

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
        schema = SPEC_TOOL if name == SPEC_TOOL["name"] else TOOL
        Draft202012Validator(schema["inputSchema"]).validate(arguments)
        if self.calls >= MAX_CALLS_PER_TURN:
            raise RuntimeError("API catalog discovery budget exhausted")
        self.calls += 1

        if name == SPEC_TOOL["name"]:
            result = await self.guru.inspect(arguments["provider_id"])
            result["status"] = "spec_observed_unverified_vendor"
            return result

        query = _safe_query(arguments["query"])
        source = arguments.get("source", "public")
        limit = int(arguments.get("limit", 8))
        public_index = None
        public_rows: dict[str, Any] = {}
        public_meta: tuple[float, str, bool] | None = None
        guru_index = None
        guru_rows: dict[str, DirectoryEntry] = {}
        guru_meta: tuple[float, str, bool] | None = None
        failures: list[str] = []

        if source in {"public", "all"}:
            try:
                body, fetched_at, fingerprint, stale = await self._catalog()
                public_index, public_rows = _index_for(body, fingerprint)
                public_meta = (fetched_at, fingerprint, stale)
            except (httpx.HTTPError, OSError, RuntimeError, ValueError):
                if source == "public":
                    raise
                failures.append("public catalog unavailable")

        if source in {"openapi", "all"}:
            try:
                snapshot = await self.guru.listing()
                guru_index, guru_rows = _guru_index(snapshot)
                guru_meta = (snapshot.fetched_at, snapshot.sha256, snapshot.stale)
            except (httpx.HTTPError, OSError, RuntimeError, ValueError):
                if source == "openapi":
                    raise
                failures.append("OpenAPI directory unavailable")

        if public_index is None and guru_index is None:
            raise RuntimeError("No API catalog is currently available")

        if public_index is not None and guru_index is not None:
            digest = hashlib.sha256(
                (public_meta[1] + ":" + guru_meta[1]).encode("utf-8")
            ).hexdigest()
            combined = _combined_index(public_index, guru_index, digest)
            ranked = combined.search(query, limit=min(60, max(limit * 6, 20)))
        else:
            index = public_index if public_index is not None else guru_index
            assert index is not None
            ranked = index.search(query, limit=min(60, max(limit * 6, 20)))

        results = []
        for option, score in ranked:
            match = public_rows.get(option.key)
            if match is not None:
                results.append({
                    "kind": "rest", "origin": "public-apis",
                    "name": match.name,
                    "category": match.category,
                    "description": match.description[:500],
                    "documentation_url": match.url,
                    "auth": match.auth,
                    "https": match.https,
                    "cors": match.cors,
                    "relevance_score": round(float(score), 3),
                    "status": "discovery_only_unverified",
                })
            else:
                match = guru_rows.get(option.key)
                if match is None:
                    continue
                results.append({
                    "kind": "rest", "origin": "apis.guru",
                    "provider_id": match.provider_id,
                    "name": match.title,
                    "category": " ".join(match.categories),
                    "description": match.description[:500],
                    "spec_url": match.spec_url,
                    "openapi_version": match.openapi_version,
                    "updated_at": match.last_updated,
                    "documentation_url": match.spec_url,
                    "auth": "unknown", "https": True, "cors": "unknown",
                    "relevance_score": round(float(score), 3),
                    "status": "discovery_only_unverified",
                })
            if len(results) >= limit:
                break

        meta = [item for item in (public_meta, guru_meta) if item is not None]
        digest = hashlib.sha256(
            ":".join(item[1] for item in meta).encode("utf-8")
        ).hexdigest() if len(meta) > 1 else meta[0][1]
        return {
            "query": query,
            "source": CATALOG_URL if source == "public" else DIRECTORY_URL if source == "openapi" else "public-apis + APIs.guru",
            "selected_source": source,
            "catalog_sha256": digest,
            "catalog_fetched_at": min(item[0] for item in meta),
            "catalog_stale": any(item[2] for item in meta),
            "catalog_entries": sum(len(idx.options) for idx in (public_index, guru_index) if idx is not None),
            "source_failures": failures,
            "results": results,
            "notice": (
                "Untrusted discovery metadata only. APIs.guru descriptions may be third-party "
                "and outdated. Verify first-party docs, licenses, auth, limits and test safely; "
                "no discovered API was called or authorized."
            ),
        }
