"""Bounded, opt-in, public scholarly-metadata research for STAR.

Fixed official HTTPS endpoints only. Never fetch a model-provided URL, submit
private project text automatically, install tools, or grant agent permissions.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

import httpx

MAX_BYTES = 256_000
API = {
    "crossref": "https://api.crossref.org/works",
    "openalex": "https://api.openalex.org/works",
}
SOURCES = {
    "crossref": {
        "purpose": "DOI and publication metadata (not unrestricted article text)",
        "docs": "https://www.crossref.org/documentation/retrieve-metadata/rest-api/",
        "rate_policy": "One request at a time per run; obey 429 and published rate-limit headers",
        "cost": "Public metadata API; no API key required for small queries",
    },
    "openalex": {
        "purpose": "Scholarly works, citations and open-access discovery metadata",
        "docs": "https://help.openalex.org/api/",
        "rate_policy": "One request at a time per run; obey 429 and usage budgets",
        "cost": "Casual API access may work without a key; higher quotas require an account/key",
    },
}


def _query(value: object, limit: object) -> str:
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 120 or any(ord(c) < 32 for c in value):
        raise ValueError("Research query must contain 2–120 printable characters")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("Research limit must be 1..5")
    return value.strip()


def _safe_text(value: Any, length: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()[:length]


def normalize_items(source: str, body: object, *, limit: int) -> list[dict]:
    """Treat provider fields as untrusted data; strip abstracts and raw HTML."""
    if source == "crossref":
        node = body.get("message", {}) if isinstance(body, dict) else {}
        items = node.get("items") if isinstance(node, dict) else None
    elif source == "openalex":
        items = body.get("results") if isinstance(body, dict) else None
    else:
        raise ValueError("Unknown research provider")
    if not isinstance(items, list):
        raise ValueError("Unexpected research provider schema")
    results = []
    for row in items[:limit]:
        if not isinstance(row, dict):
            continue
        titles = row.get("title", "")
        if source == "crossref":
            title = _safe_text(titles[0]) if isinstance(titles, list) and titles else ""
            identifier = _safe_text(row.get("DOI"), 160)
            date = row.get("published", {})
            parts = date.get("date-parts") if isinstance(date, dict) else None
            year = (parts[0][0] if isinstance(parts, list) and parts and
                    isinstance(parts[0], list) and parts[0] else None)
        else:
            title = _safe_text(titles)
            identifier = _safe_text(row.get("id"), 160)
            year = row.get("publication_year")
        if not title:
            continue
        if type(year) is not int or not 1000 <= year <= 2200:
            year = None
        results.append({"source": source, "title": title, "identifier": identifier, "year": year})
    return results


async def search_public_metadata(query: str, *, source: str, limit: int = 5,
                                 allow_network: bool = False,
                                 transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Explicit external-read only; no redirects and capped streaming response."""
    query = _query(query, limit)
    if source not in API:
        raise ValueError("Unknown approved research source")
    if allow_network is not True:
        raise PermissionError("Public research requires explicit external-network consent")
    params = ({"query.title": query, "rows": limit} if source == "crossref"
              else {"search": query, "per_page": limit})
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=4.0), trust_env=False,
                                     follow_redirects=False, transport=transport) as client:
            async with client.stream(
                "GET", API[source], params=params,
                headers={"Accept": "application/json", "User-Agent": "STAR-metadata-research/1.0 (https://github.com/oncoursemail/Star-AI)"},
            ) as response:
                if response.status_code == 429:
                    raise RuntimeError("Research provider rate-limited this request; retry later")
                if response.status_code != 200:
                    raise RuntimeError(f"Research provider returned HTTP {response.status_code}")
                declared = response.headers.get("content-length", "")
                if declared.isdecimal() and int(declared) > MAX_BYTES:
                    raise ValueError("Research metadata exceeds response size limit")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("Research metadata exceeds response size limit")
                body = json.loads(data)
                request_url = str(response.request.url)
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError("Research provider was unavailable or returned invalid JSON") from exc
    return {
        "source": source,
        "query": query,
        "source_api_url": request_url,
        "items": normalize_items(source, body, limit=limit),
        "external_network_used": True,
        "content_is_untrusted": True,
        "data_use_note": "Metadata and links only; verify rights before reusing abstracts, full text, artwork or datasets.",
    }


async def research_both(query: str, *, limit: int = 5, allow_network: bool = False,
                        transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """One capped request per source, in parallel; preserve partial failures."""
    _query(query, limit)
    if allow_network is not True:
        raise PermissionError("Public research requires explicit external-network consent")
    results = await asyncio.gather(*(
        search_public_metadata(query, source=name, limit=limit, allow_network=True, transport=transport)
        for name in API
    ), return_exceptions=True)
    rows, failures = [], {}
    for source, result in zip(API, results):
        if isinstance(result, Exception):
            failures[source] = str(result)[:180]
        else:
            rows.append(result)
    return {"query": query, "results": rows, "errors": failures, "sources_requested": list(API),
            "no_claim_of_completeness": True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STAR opt-in public research metadata scout")
    parser.add_argument("query", nargs="?")
    parser.add_argument("--source", choices=[*API, "both"], default="both")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--allow-network", action="store_true", help="Explicitly send this query to public services")
    parser.add_argument("--catalog", action="store_true", help="Show offline source catalog; no network")
    args = parser.parse_args(argv)
    if args.catalog:
        print(json.dumps(SOURCES, indent=2, sort_keys=True))
        return 0
    if not args.query:
        parser.error("Supply a query or use --catalog")
    try:
        if args.source == "both":
            report = asyncio.run(research_both(args.query, limit=args.limit, allow_network=args.allow_network))
        else:
            report = asyncio.run(search_public_metadata(args.query, source=args.source,
                                                        limit=args.limit, allow_network=args.allow_network))
    except (PermissionError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return int(bool(report.get("errors")))


if __name__ == "__main__":
    raise SystemExit(main())
