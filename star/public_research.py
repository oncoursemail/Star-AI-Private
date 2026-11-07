"""Scholarly metadata (Crossref, OpenAlex) as extra deep-research sources; off unless the owner turns on
Settings.scholarly_research_enabled.

Only two fixed official API URLs are built here; every request goes through star/web_fetch.fetch_page (public
address checks, redirect checks, size and time limits). Provider fields are untrusted data: titles, years and
identifiers are kept, abstracts and other text are dropped. The research question is sent to both providers.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlencode

from .web_fetch import Page, fetch_page

API = {
    "crossref": "https://api.crossref.org/works",
    "openalex": "https://api.openalex.org/works",
}
MAX_QUERY_CHARS = 120
PER_SOURCE = 2
_DOI = re.compile(r"^10\.\d{4,9}/\S{1,200}$")


def _query(value: object) -> str:
    """The first MAX_QUERY_CHARS of the question, cut at a word boundary."""
    if not isinstance(value, str):
        raise ValueError("Research query must be text")
    text = " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", value).split())
    if len(text) > MAX_QUERY_CHARS:
        text = text[:MAX_QUERY_CHARS].rsplit(" ", 1)[0]
    if len(text) < 2:
        raise ValueError("Research query is too short")
    return text


def _safe_text(value: Any, length: int = 240) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(re.sub(r"[\x00-\x1f\x7f]+", " ", value).split())[:length]


def normalize_items(source: str, body: object, *, limit: int) -> list[dict]:
    """Search-result rows (title, url, snippet, published) from a provider reply; no abstracts."""
    if source == "crossref":
        node = body.get("message", {}) if isinstance(body, dict) else {}
        items = node.get("items") if isinstance(node, dict) else None
    elif source == "openalex":
        items = body.get("results") if isinstance(body, dict) else None
    else:
        raise ValueError("Unknown research provider")
    if not isinstance(items, list):
        raise ValueError("Unexpected research provider schema")
    rows = []
    for row in items[:limit]:
        if not isinstance(row, dict):
            continue
        if source == "crossref":
            titles = row.get("title")
            title = _safe_text(titles[0]) if isinstance(titles, list) and titles else ""
            doi = _safe_text(row.get("DOI"), 220)
            url = "https://doi.org/" + quote(doi, safe="/.:;()-_") if _DOI.match(doi) else ""
            date = row.get("issued")
            parts = date.get("date-parts") if isinstance(date, dict) else None
            year = (parts[0][0] if isinstance(parts, list) and parts and
                    isinstance(parts[0], list) and parts[0] else None)
            label = "Crossref"
        else:
            title = _safe_text(row.get("title"))
            doi_url, work = _safe_text(row.get("doi"), 240), _safe_text(row.get("id"), 160)
            url = next((u for u in (doi_url, work) if u.startswith(("https://doi.org/10.", "https://openalex.org/W"))), "")
            year = row.get("publication_year")
            label = "OpenAlex"
        if not title or not url:
            continue
        if type(year) is not int or not 1000 <= year <= 2200:
            year = None
        rows.append({"title": title, "url": url,
                     "snippet": f"{label} scholarly metadata{f' ({year})' if year else ''}: {title}. "
                                "Title and identifier only; read the source before relying on it.",
                     "published": str(year) if year else ""})
    return rows


async def search_metadata(query: str, *, source: str, limit: int = PER_SOURCE,
                          fetcher: Callable[[str], Awaitable[Page]] = fetch_page) -> list[dict]:
    """One GET to a fixed provider URL through the guarded page reader."""
    if source not in API:
        raise ValueError("Unknown approved research source")
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("Research limit must be 1..5")
    text = _query(query)
    params = ({"query.bibliographic": text, "rows": limit, "select": "DOI,title,issued"}
              if source == "crossref" else
              {"search": text, "per_page": limit, "select": "id,doi,title,publication_year"})
    page = await fetcher(f"{API[source]}?{urlencode(params)}")
    if page.truncated:
        raise ValueError("Research metadata exceeded the page reader's text limit")
    return normalize_items(source, json.loads(page.text), limit=limit)


def with_scholarly_metadata(searcher: Callable[..., Awaitable[list[dict]]], *,
                            fetcher: Callable[[str], Awaitable[Page]] = fetch_page) -> Callable[..., Awaitable[list[dict]]]:
    """Wrap a deep-research searcher. The first query of the run also asks each provider for PER_SOURCE works,
    interleaved with the web results; later queries are web only. A provider failure never hides web results."""
    asked = False

    async def search(query: str, *, limit: int) -> list[dict]:
        nonlocal asked
        if asked:
            return await searcher(query, limit=limit)
        asked = True
        web, *scholarly = await asyncio.gather(
            searcher(query, limit=limit),
            *(search_metadata(query, source=name, fetcher=fetcher) for name in API),
            return_exceptions=True)
        if isinstance(web, BaseException):
            raise web
        extra = [row for result in scholarly if not isinstance(result, BaseException) for row in result]
        merged = [row for pair in zip(web, extra) for row in pair]
        merged += web[len(extra):] + extra[len(web):]
        return merged[:limit]

    return search
