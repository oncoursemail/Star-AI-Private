"""STAR Resource Atlas: bounded discovery of public resource metadata.

A research-only candidate index. This module cannot install packages, execute
code, download media, train models, change permissions, or promote lessons.
External descriptions are UNTRUSTED data. Network use is explicitly opt-in.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 1_000_000
MAX_PER_PROVIDER = 10
REGISTRY = Path(__file__).parent / "data" / "resource_atlas_sources.json"
HOSTS = frozenset({
    "api.github.com", "huggingface.co", "api.polyhaven.com",
    "api.openverse.org", "registry.npmjs.org", "api.openalex.org",
    "freesound.org",
})
PROVIDERS = ("github", "hf_models", "hf_datasets", "polyhaven",
             "openverse_images", "openverse_audio", "npm", "openalex", "freesound")
DEFAULT_PROVIDERS = ("github", "hf_models", "hf_datasets", "polyhaven",
                     "openverse_images", "openverse_audio", "npm", "openalex")
TERMS = re.compile(r"[^\W_][\w.+-]*", re.UNICODE)
QUERY = re.compile(r"^[\w][\w .+,-]{1,99}$", re.UNICODE)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _clean(value: object, maximum: int = 300) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]{0,300}>", " ",
                  html.unescape(value))).strip()[:maximum]


def _query(value: str) -> str:
    if not isinstance(value, str) or not QUERY.fullmatch(value.strip()):
        raise ValueError("Query must be 2-100 ordinary letters/numbers or spaces")
    return value.strip()


def _host_is_allowed(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in HOSTS and
                parsed.username is None and parsed.password is None and
                parsed.port in (None, 443) and not parsed.fragment)
    except (ValueError, TypeError):
        return False


def fetch_json(url: str, headers: dict[str, str] | None = None) -> object:
    """Fixed HTTPS hosts only, no redirects, JSON size/time bounds, no cookies."""
    if not _host_is_allowed(url):
        raise ValueError("Atlas refuses an unapproved outbound host")
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "STAR-Resource-Atlas/0.1 (metadata-only)",
    }
    if headers:
        # The only credential used by an adapter is an optional Freesound token.
        for key, value in headers.items():
            if key != "Authorization" or not value.startswith("Token "):
                raise ValueError("Unsupported request header")
            if urlsplit(url).hostname != "freesound.org":
                raise ValueError("Credentials cannot be sent to this host")
            request_headers[key] = value
    request = Request(url, headers=request_headers, method="GET")
    try:
        with build_opener(NoRedirect()).open(request, timeout=8) as response:
            if response.status != 200:
                raise RuntimeError("Atlas provider did not return success")
            if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
                raise ValueError("Atlas response exceeds byte limit")
            raw = response.read(MAX_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError):
        raise RuntimeError("Atlas provider unavailable or rate limited") from None
    if len(raw) > MAX_BYTES:
        raise ValueError("Atlas response exceeds byte limit")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("Atlas provider returned invalid JSON") from None


def license_from_tags(tags: object) -> str:
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("license:"):
                return _clean(tag[8:], 70)
    return "unknown"


def _safe_license(value: object) -> str:
    result = _clean(value, 70)
    return result if re.fullmatch(r"[A-Za-z0-9.+_-]{2,70}", result) and result.lower() not in {
        "none", "noassertion", "other", "unknown", "not-found"
    } else "unknown"


@dataclass(frozen=True)
class Candidate:
    provider: str
    resource_id: str
    title: str
    summary: str
    url: str
    kind: str
    license_claim: str
    creator: str
    tags: tuple[str, ...]
    evidence_sha256: str
    discovered_at: str
    review_required: bool = True
    executable: bool = False
    installed: bool = False
    promoted_as_learning: bool = False


def _candidate(provider: str, resource_id: str, title: object, description: object,
               url: str, kind: str, license_claim: object = "unknown",
               creator: object = "", tags: object = (),
               *, seen_at: str | None = None) -> Candidate:
    rid = _clean(resource_id, 160)
    if not rid or len(rid) != len(str(resource_id)):
        raise ValueError("Invalid candidate identifier")
    if not url.startswith("https://") or len(url) > 500:
        raise ValueError("Invalid candidate landing page")
    safe_tags = tuple(_clean(x, 40) for x in tags[:12] if isinstance(x, str)) if isinstance(tags, (list, tuple)) else ()
    fields = (provider, rid, _clean(title, 150), _clean(description, 480),
              url, kind, _safe_license(license_claim), _clean(creator, 100), safe_tags)
    digest = hashlib.sha256(json.dumps(fields, ensure_ascii=True).encode("utf-8")).hexdigest()
    return Candidate(provider, rid, fields[2], fields[3], url, kind, fields[6],
                     fields[7], safe_tags, digest,
                     seen_at or datetime.now(timezone.utc).isoformat())


def _items(payload: object, key: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ValueError("Unexpected Atlas provider response")
    return [item for item in payload[key] if isinstance(item, dict)]


def decode(provider: str, payload: object, *, limit: int,
           fetched_at: str | None = None, query: str = "") -> list[Candidate]:
    """Decode untrusted fixtures/metadata; never interpret instructions."""
    if provider not in PROVIDERS:
        raise ValueError("Unknown Atlas provider")
    if type(limit) is not int or not 1 <= limit <= MAX_PER_PROVIDER:
        raise ValueError("Invalid Atlas result cap")
    found: list[Candidate] = []

    if provider == "github":
        for entry in _items(payload, "items")[:limit * 3]:
            repo = entry.get("full_name")
            if not isinstance(repo, str) or not re.fullmatch(
                r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repo
            ) or entry.get("private", False):
                continue
            lic = entry.get("license") or {}
            lic = lic.get("spdx_id") if isinstance(lic, dict) else None
            if entry.get("archived") or entry.get("disabled"):
                continue
            found.append(_candidate(provider, repo, entry.get("name", repo),
                entry.get("description", ""), "https://github.com/" + repo,
                "source-code", lic, repo.split("/")[0],
                entry.get("topics", []), seen_at=fetched_at))

    elif provider in ("hf_models", "hf_datasets"):
        if not isinstance(payload, list):
            raise ValueError("Unexpected Hugging Face response")
        for entry in payload[:limit * 3]:
            if not isinstance(entry, dict) or entry.get("private") or entry.get("gated"):
                continue
            rid = entry.get("id")
            if not isinstance(rid, str) or not re.fullmatch(
                r"[\w.-]{1,100}/[\w.-]{1,100}", rid
            ):
                continue
            tags = entry.get("tags", [])
            card = entry.get("cardData") or {}
            card_license = card.get("license") if isinstance(card, dict) else None
            license_claim = card_license or license_from_tags(tags)
            kind = "model" if provider == "hf_models" else "dataset"
            path = "datasets/" if kind == "dataset" else ""
            found.append(_candidate(provider, rid, rid,
                entry.get("description", "") or (entry.get("pipeline_tag") or ""),
                "https://huggingface.co/" + path + rid, kind, license_claim,
                rid.split("/")[0], tags, seen_at=fetched_at))

    elif provider == "polyhaven":
        if not isinstance(payload, dict):
            raise ValueError("Unexpected Poly Haven response")
        ranked = payload.get("results", [])
        if not isinstance(ranked, list):
            raise ValueError("Unexpected Poly Haven ranked results")
        query_terms = [s.lower() for s in TERMS.findall(query) if len(s) > 1]
        for row in ranked[:limit * 3]:
            slug = row if isinstance(row, str) else row.get("id", row.get("slug", "")) if isinstance(row, dict) else ""
            if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9_]{2,100}", slug):
                continue
            # The semantic endpoint always returns nearest neighbours, even for
            # queries unrelated to 3D. Suppress weak, off-topic asset matches.
            if query_terms:
                score = row.get("score", 0) if isinstance(row, dict) else 0
                if type(score) not in (int, float):
                    score = 0
                overlap = sum(term in slug.replace("_", " ") for term in query_terms)
                needed = (len(query_terms) + 1) // 2
                if not ((overlap >= needed and score >= 0.48) or score >= 0.74):
                    continue
            # Official API serves CC0 assets. Confirm listing before redistribution.
            found.append(_candidate(provider, slug, slug.replace("_", " "),
                "Poly Haven asset; verify category and format before use",
                "https://polyhaven.com/a/" + slug, "3d-texture-hdri",
                "CC0-1.0", "Poly Haven", seen_at=fetched_at))

    elif provider in ("openverse_images", "openverse_audio"):
        kind = "image" if provider == "openverse_images" else "audio"
        for item in _items(payload, "results")[:limit * 3]:
            rid = item.get("id")
            if not isinstance(rid, str) or not re.fullmatch(r"[0-9a-fA-F-]{32,36}", rid):
                continue
            claim = item.get("license", "")
            version = item.get("license_version", "")
            license_claim = (
                "CC0-1.0" if claim == "cc0" else
                "CC-BY-" + str(version) if claim == "by" and version else
                "CC-BY-SA-" + str(version) if claim == "by-sa" and version else
                "PDM-1.0" if claim == "pdm" else "unknown"
            )
            found.append(_candidate(provider, rid, item.get("title") or kind,
                "Indexed open media; verify author/license/format at original source",
                "https://openverse.org/" + kind + "/" + rid, kind,
                license_claim, item.get("creator"), seen_at=fetched_at))

    elif provider == "npm":
        for item in _items(payload, "objects")[:limit * 3]:
            package = item.get("package")
            if not isinstance(package, dict):
                continue
            name = package.get("name")
            if not isinstance(name, str) or not re.fullmatch(
                r"(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]{1,150}", name
            ):
                continue
            found.append(_candidate(provider, name, name,
                package.get("description"), "https://www.npmjs.com/package/" + quote(name, safe="@/"),
                "software-package", package.get("license"),
                str((package.get("publisher") or {}).get("username", "")) if
                isinstance(package.get("publisher"), dict) else "",
                package.get("keywords", []), seen_at=fetched_at))

    elif provider == "openalex":
        for item in _items(payload, "results")[:limit * 3]:
            uri = item.get("id", "")
            if not isinstance(uri, str) or not re.fullmatch(r"https://openalex.org/W\d+", uri):
                continue
            authors = item.get("authorships") or []
            author = ""
            if isinstance(authors, list) and authors and isinstance(authors[0], dict):
                first = authors[0].get("author")
                if isinstance(first, dict):
                    author = first.get("display_name", "")
            found.append(_candidate(provider, uri.rsplit("/", 1)[-1], item.get("title"),
                "Research discovery record; paper contents and reuse rights are not granted",
                uri, "research-paper", "unknown", author, seen_at=fetched_at))

    elif provider == "freesound":
        for item in _items(payload, "results")[:limit * 3]:
            rid = item.get("id")
            if type(rid) is not int or rid <= 0:
                continue
            raw_license = item.get("license")
            claim = "unknown"
            if isinstance(raw_license, str):
                match = re.fullmatch(
                    r"https?://creativecommons.org/(?:publicdomain/zero/1.0/|licenses/(by|by-sa|by-nc|by-nc-sa)/(3.0|4.0)/?)",
                    raw_license.strip())
                if match:
                    claim = "CC0-1.0" if match.group(1) is None else (
                        "CC-" + match.group(1).upper() + "-" + match.group(2))
            found.append(_candidate(provider, str(rid), item.get("name"),
                item.get("description"), "https://freesound.org/s/" + str(rid) + "/",
                "audio", claim, "", item.get("tags", []), seen_at=fetched_at))

    # Deduplicate case-insensitively, preserving provider relevance order.
    unique = []
    seen = set()
    for item in found:
        key = (item.provider, item.resource_id.casefold())
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:limit]


def discover(provider: str, query: str, *, limit: int = 6,
             fetch: Callable[..., object] = fetch_json,
             env: dict[str, str] | None = None) -> list[Candidate]:
    query = _query(query)
    if provider not in PROVIDERS:
        raise ValueError("Unsupported provider")
    if type(limit) is not int or not 1 <= limit <= MAX_PER_PROVIDER:
        raise ValueError("Atlas per-provider limit is 1-10")
    e = os.environ if env is None else env
    q = urlencode
    headers: dict[str, str] = {}
    if provider == "github":
        url = "https://api.github.com/search/repositories?" + q({
            "q": query + " is:public archived:false", "per_page": limit})
    elif provider in ("hf_models", "hf_datasets"):
        kind = "models" if provider == "hf_models" else "datasets"
        url = "https://huggingface.co/api/" + kind + "?" + q({
            "search": query, "limit": limit, "full": "true"})
    elif provider == "polyhaven":
        url = "https://api.polyhaven.com/search?" + q({
            "q": query.lower(), "t": "all"})
    elif provider in ("openverse_images", "openverse_audio"):
        kind = "images" if provider == "openverse_images" else "audio"
        url = "https://api.openverse.org/v1/" + kind + "/?" + q({
            "q": query, "page_size": limit, "mature": "false"})
    elif provider == "npm":
        url = "https://registry.npmjs.org/-/v1/search?" + q({
            "text": query, "size": limit})
    elif provider == "openalex":
        url = "https://api.openalex.org/works?" + q({
            "search": query, "per_page": limit})
    else:
        token = e.get("STAR_FREESOUND_API_TOKEN", "")
        if not token or not re.fullmatch(r"[A-Za-z0-9_-]{12,200}", token):
            raise RuntimeError("Freesound requires an explicitly configured API token")
        url = "https://freesound.org/apiv2/search/text/?" + q({
            "query": query, "page_size": limit,
            "fields": "id,name,description,license,tags"})
        headers["Authorization"] = "Token " + token
    payload = fetch(url, headers=headers or None)
    return decode(provider, payload, limit=limit, query=query)


class AtlasStore:
    """Simple durable metadata index, separate from Star's trusted memory."""

    def __init__(self, filename: str | Path):
        path = Path(filename).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS candidates (
            provider TEXT NOT NULL, resource_id TEXT NOT NULL,
            title TEXT NOT NULL, summary TEXT NOT NULL, url TEXT NOT NULL,
            kind TEXT NOT NULL, license_claim TEXT NOT NULL, creator TEXT NOT NULL,
            tags TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            review_required INTEGER NOT NULL CHECK(review_required = 1),
            PRIMARY KEY(provider, resource_id)
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS atlas_kind ON candidates(kind,provider)")
        self.db.commit()

    def ingest(self, candidates: list[Candidate]) -> int:
        with self.db:
            for c in candidates:
                if (not c.review_required or c.executable or c.installed or
                        c.promoted_as_learning):
                    raise ValueError("Atlas accepts discovery-only candidates")
                self.db.execute("""INSERT INTO candidates VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?,1)
                    ON CONFLICT(provider,resource_id) DO UPDATE SET
                    title=excluded.title,summary=excluded.summary,url=excluded.url,
                    kind=excluded.kind,license_claim=excluded.license_claim,
                    creator=excluded.creator,tags=excluded.tags,
                    evidence_sha256=excluded.evidence_sha256,
                    last_seen=excluded.last_seen""",
                    (c.provider,c.resource_id,c.title,c.summary,c.url,c.kind,
                     c.license_claim,c.creator,json.dumps(c.tags),c.evidence_sha256,
                     c.discovered_at,c.discovered_at))
        return len(candidates)

    def search(self, query: str, limit: int = 15) -> list[dict]:
        q = _query(query)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid Atlas search limit")
        terms = [re.sub(r"([%_\\])", r"\\\1", s) for s in TERMS.findall(q)[:8]]
        where = " AND ".join("(title LIKE ? ESCAPE '\\' OR summary LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')" for _ in terms)
        params = [f"%{term}%" for term in terms for _ in range(3)]
        self.db.row_factory = sqlite3.Row
        rows = self.db.execute(
            "SELECT * FROM candidates WHERE " + where +
            " ORDER BY last_seen DESC, provider, resource_id LIMIT ?", (*params,limit)).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]

    def close(self) -> None:
        self.db.close()


def read_sources() -> list[dict]:
    records = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Atlas seed catalog is invalid")
    return records


def _default_db() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "STAR"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "star"
    return base / "resource_atlas.sqlite3"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STAR Resource Atlas: research metadata only")
    parser.add_argument("action", choices=("catalog", "scan", "search", "stats"))
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--db", type=Path, default=_default_db())
    parser.add_argument("--providers", default=",".join(DEFAULT_PROVIDERS))
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--allow-network", action="store_true",
                        help="Requires STAR_RESOURCE_ATLAS_NETWORK=1 too")
    args = parser.parse_args(argv)
    if args.action == "catalog":
        entries = read_sources()
        if args.query:
            terms = [t.casefold() for t in TERMS.findall(_query(args.query))]
            entries = [e for e in entries if all(
                t in json.dumps(e).casefold() for t in terms)]
        print(json.dumps({"count":len(entries),"resources":entries}, indent=2))
        return 0
    if args.action == "scan":
        if not args.allow_network or os.environ.get("STAR_RESOURCE_ATLAS_NETWORK") != "1":
            parser.error("Network is OFF; opt in with flag AND STAR_RESOURCE_ATLAS_NETWORK=1")
        query = _query(args.query)
        providers = args.providers.split(",")
        if not providers or len(providers) > len(PROVIDERS) or len(set(providers)) != len(providers) or any(
            item not in PROVIDERS for item in providers
        ):
            parser.error("Select distinct supported provider names")
        if not 1 <= args.limit <= MAX_PER_PROVIDER:
            parser.error("Limit must be 1-10")
        store = AtlasStore(args.db)
        report: dict[str, object] = {"query":query,"providers":{}}
        total = 0
        # Only a few reads overlap; DB writes are serialized by this thread.
        with ThreadPoolExecutor(max_workers=min(3, len(providers))) as workers:
            jobs = {name: workers.submit(discover, name, query, limit=args.limit)
                    for name in providers}
            for name in providers:
                try:
                    candidates = jobs[name].result()
                    total += store.ingest(candidates)
                    report["providers"][name] = {"count":len(candidates),
                        "titles":[c.title for c in candidates]}
                except (RuntimeError, ValueError) as exc:
                    # No tokens, request URLs or raw provider responses in errors.
                    report["providers"][name] = {"error":str(exc)}
        report["seen_records"] = total
        report["stored_total"] = store.count()
        report["all_providers_ok"] = all(
            "error" not in d for d in report["providers"].values())
        store.close()
        print(json.dumps(report, indent=2))
        return 0 if report["all_providers_ok"] else 2
    store = AtlasStore(args.db)
    if args.action == "stats":
        result = {"count":store.count()}
    else:
        result = {"query":args.query,"results":store.search(args.query,
                  limit=min(max(args.limit,1),50))}
    store.close()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
