"""Read-only APIs.guru directory/specification discovery for STAR Capability Forge.

Only two fixed-host operations are allowed: download the public directory listing,
and fetch a specification URL returned by that listing from the same host.  The
listing is untrusted data and can never authorize an API call, credential, tool
installation, local file access, or recursive $ref resolution.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from .api_intelligence import summarize_openapi
from .api_contracts import compile_read_contracts


DIRECTORY_URL = "https://api.apis.guru/v2/list.json"
DIRECTORY_MAX_BYTES = 12_000_000
SPEC_MAX_BYTES = 3_000_000
DIRECTORY_TTL_SECONDS = 24 * 60 * 60
SPEC_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_STALE_SECONDS = 30 * 24 * 60 * 60
MAX_SPEC_CACHE_ROWS = 16
_MAX_PROVIDERS = 6_000
_PROVIDER_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,179}$")
_HOT_LOCK = threading.Lock()
_HOT_PARSED: dict[str, tuple["DirectoryEntry", ...]] = {}


@dataclass(frozen=True)
class DirectoryEntry:
    provider_id: str
    title: str
    description: str
    categories: tuple[str, ...]
    version: str
    spec_url: str
    openapi_version: str
    last_updated: str
    origin_urls: tuple[str, ...]


@dataclass(frozen=True)
class DirectorySnapshot:
    entries: tuple[DirectoryEntry, ...]
    sha256: str
    fetched_at: float
    stale: bool


def _plain(value: Any, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def spec_url_allowed(url: str) -> bool:
    """A directory-provided spec URL must stay on the fixed HTTPS APIs.guru host."""
    if not isinstance(url, str) or not 25 <= len(url) <= 1400:
        return False
    if any(ord(char) < 33 or ord(char) == 127 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme == "https"
            and parsed.netloc == "api.apis.guru"
            and parsed.path.startswith("/v2/specs/")
            and not any(segment in (".", "..") for segment in parsed.path.split("/"))
            and not parsed.query and not parsed.fragment
            and parsed.username is None and parsed.password is None
        )
    except ValueError:
        return False


def parse_directory(data: Any) -> tuple[DirectoryEntry, ...]:
    """Bounded parser of APIs.guru's list.json, choosing the preferred version only."""
    if not isinstance(data, dict) or len(data) > _MAX_PROVIDERS:
        raise ValueError("APIs.guru listing must be a bounded JSON object")
    entries: list[DirectoryEntry] = []
    for provider, details in data.items():
        if (not isinstance(provider, str) or not _PROVIDER_ID.fullmatch(provider)
                or not isinstance(details, dict)):
            continue
        preferred = details.get("preferred")
        versions = details.get("versions")
        if not isinstance(preferred, str) or not isinstance(versions, dict):
            continue
        definition = versions.get(preferred)
        if not isinstance(definition, dict):
            continue
        spec_url = definition.get("swaggerUrl")
        if not spec_url_allowed(spec_url):
            continue
        info = definition.get("info")
        if not isinstance(info, dict):
            info = {}
        cats = info.get("x-apisguru-categories")
        if not isinstance(cats, list):
            cats = []
        categories = tuple(_plain(v, 60) for v in cats[:8] if _plain(v, 60))
        origin = info.get("x-origin")
        origins: list[str] = []
        if isinstance(origin, list):
            for item in origin[:6]:
                if isinstance(item, dict):
                    value = item.get("url")
                    if isinstance(value, str) and value.startswith("https://") and len(value) < 900:
                        origins.append(value)
        entries.append(DirectoryEntry(
            provider_id=provider,
            title=_plain(info.get("title"), 180) or provider,
            description=_plain(info.get("description"), 700),
            categories=categories,
            version=_plain(preferred, 90),
            spec_url=spec_url,
            openapi_version=_plain(definition.get("openapiVer"), 24),
            last_updated=_plain(definition.get("updated"), 45),
            origin_urls=tuple(dict.fromkeys(origins)),
        ))
    return tuple(sorted(entries, key=lambda row: row.provider_id.lower()))


def _parse_bytes(blob: bytes, fingerprint: str) -> tuple[DirectoryEntry, ...]:
    with _HOT_LOCK:
        cached = _HOT_PARSED.get(fingerprint)
        if cached is not None:
            return cached
    entries = parse_directory(json.loads(blob))
    with _HOT_LOCK:
        _HOT_PARSED[fingerprint] = entries
        while len(_HOT_PARSED) > 2:
            del _HOT_PARSED[next(iter(_HOT_PARSED))]
    return entries


class ApiGuruDirectory:
    """Fixed-origin, bounded directory reader with durable SHA-checked local cache."""

    def __init__(
        self, *,
        home: Path,
        transport: httpx.AsyncBaseTransport | None = None,
        now_fn=time.time,
    ):
        self.path = Path(home).expanduser().resolve() / "apis-guru-cache.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.transport = transport
        self.now_fn = now_fn
        with self._connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS directory (
                id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL,
                sha256 TEXT NOT NULL, fetched_at REAL NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS specifications (
                provider_id TEXT PRIMARY KEY, spec_url TEXT NOT NULL,
                body BLOB NOT NULL, sha256 TEXT NOT NULL, fetched_at REAL NOT NULL
            )""")

    def _connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _cached(self, table: str, key: str | None) -> tuple[bytes, str, float, str] | None:
        with self._connection() as db:
            if table == "directory":
                record = db.execute("SELECT body,sha256,fetched_at,'' FROM directory WHERE id=1").fetchone()
            else:
                record = db.execute(
                    "SELECT body,sha256,fetched_at,spec_url FROM specifications WHERE provider_id=?",
                    (key,),
                ).fetchone()
        if record is None:
            return None
        raw, fingerprint, fetched_at, source_url = record
        if not isinstance(raw, bytes) or not isinstance(fingerprint, str):
            return None
        max_size = DIRECTORY_MAX_BYTES if table == "directory" else SPEC_MAX_BYTES
        if not raw or len(raw) > max_size or hashlib.sha256(raw).hexdigest() != fingerprint:
            return None
        if not isinstance(fetched_at, (int, float)) or not math.isfinite(fetched_at):
            return None
        return raw, fingerprint, float(fetched_at), str(source_url)

    def _remember(self, table: str, key: str | None, url: str, blob: bytes, now: float) -> str:
        fingerprint = hashlib.sha256(blob).hexdigest()
        with self._connection() as db:
            if table == "directory":
                db.execute("""INSERT INTO directory(id,body,sha256,fetched_at) VALUES(1,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET body=excluded.body,sha256=excluded.sha256,
                    fetched_at=excluded.fetched_at""", (blob, fingerprint, now))
            else:
                db.execute("""INSERT INTO specifications(provider_id,spec_url,body,sha256,fetched_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(provider_id) DO UPDATE SET
                    spec_url=excluded.spec_url,body=excluded.body,sha256=excluded.sha256,
                    fetched_at=excluded.fetched_at""", (key, url, blob, fingerprint, now))
                db.execute("""DELETE FROM specifications WHERE provider_id IN (
                    SELECT provider_id FROM specifications
                    ORDER BY fetched_at DESC,provider_id LIMIT -1 OFFSET ?
                )""", (MAX_SPEC_CACHE_ROWS,))
        return fingerprint

    async def _fetch(self, url: str, max_bytes: int) -> bytes:
        if url != DIRECTORY_URL and not spec_url_allowed(url):
            raise ValueError("Specification URL must be a catalog-listed APIs.guru HTTPS URL")
        timeout = httpx.Timeout(15.0, connect=4.0, read=10.0, write=4.0, pool=2.0)
        async with httpx.AsyncClient(
            transport=self.transport, follow_redirects=False, trust_env=False,
            timeout=timeout, headers={"Accept": "application/json", "User-Agent": "STAR-CapabilityForge/1.0"},
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise RuntimeError("APIs.guru directory/specification unavailable")
                media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media not in {"application/json", "application/vnd.oai.openapi+json"}:
                    raise ValueError("APIs.guru returned an unexpected media type")
                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > max_bytes:
                    raise ValueError("APIs.guru response exceeds the allowed size")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError("APIs.guru response exceeds the allowed size")
        if not body:
            raise ValueError("APIs.guru returned an empty response")
        return bytes(body)

    async def listing(self) -> DirectorySnapshot:
        now = float(self.now_fn())
        cached = self._cached("directory", None)
        if cached and 0 <= now - cached[2] < DIRECTORY_TTL_SECONDS:
            return DirectorySnapshot(_parse_bytes(cached[0], cached[1]), cached[1], cached[2], False)
        try:
            blob = await self._fetch(DIRECTORY_URL, DIRECTORY_MAX_BYTES)
            fingerprint = hashlib.sha256(blob).hexdigest()
            parsed = _parse_bytes(blob, fingerprint)
            if not parsed:
                raise ValueError("APIs.guru directory contained no valid definitions")
            self._remember("directory", None, DIRECTORY_URL, blob, now)
            return DirectorySnapshot(parsed, fingerprint, now, False)
        except (httpx.HTTPError, OSError, ValueError, RuntimeError, json.JSONDecodeError):
            if cached and 0 <= now - cached[2] <= MAX_STALE_SECONDS:
                return DirectorySnapshot(_parse_bytes(cached[0], cached[1]), cached[1], cached[2], True)
            raise

    async def inspect(self, provider_id: str) -> dict[str, Any]:
        if not isinstance(provider_id, str) or not _PROVIDER_ID.fullmatch(provider_id):
            raise ValueError("Specify a catalog-listed provider ID, not a URL")
        listing = await self.listing()
        selected = next((item for item in listing.entries if item.provider_id == provider_id), None)
        if selected is None:
            raise ValueError("Provider not present in cached APIs.guru directory")
        now = float(self.now_fn())
        cached = self._cached("specifications", provider_id)
        if cached and cached[3] != selected.spec_url:
            cached = None  # preferred spec changed; reject old evidence
        stale = False
        if cached and 0 <= now - cached[2] < SPEC_TTL_SECONDS:
            blob, sha, checked_at, _ = cached
        else:
            try:
                blob = await self._fetch(selected.spec_url, SPEC_MAX_BYTES)
                if not isinstance(json.loads(blob), dict):
                    raise ValueError("OpenAPI description must be a JSON object")
                sha = self._remember("specifications", provider_id, selected.spec_url, blob, now)
                checked_at = now
            except (httpx.HTTPError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
                if not cached or not 0 <= now - cached[2] <= MAX_STALE_SECONDS:
                    raise
                blob, sha, checked_at, _ = cached
                stale = True
        spec = json.loads(blob)
        summary = summarize_openapi(spec)
        contracts = compile_read_contracts(spec, max_contracts=4)
        return {
            "provider_id": provider_id,
            "name": selected.title,
            "source": selected.spec_url,
            "source_directory": DIRECTORY_URL,
            "source_directory_sha256": listing.sha256,
            "source_directory_stale": listing.stale,
            "spec_sha256": sha,
            "spec_observed_at": checked_at,
            "spec_stale": stale,
            "openapi_version": summary.version,
            "title": summary.title,
            "server_urls": list(summary.servers[:12]),
            "auth_schemes": list(summary.auth_schemes[:20]),
            "operation_count": len(summary.operations),
            "operations": list(summary.operations[:32]),
            "write_operation_count": len(summary.write_operations),
            "write_operations": list(summary.write_operations[:12]),
            "warnings": list(summary.warnings),
            "typed_read_contracts": contracts["contracts"],
            "typed_contracts_scanned": contracts["scanned_operations"],
            "typed_contracts_skipped": contracts["skipped"],
            "publisher_verified": False,
            "executable": False,
            "external_refs_resolved": False,
            "notice": (
                "Observed third-party API specification, not first-party authorization. "
                "No $ref dereferencing, API calls, credentials, tools or writes were performed."
            ),
        }
