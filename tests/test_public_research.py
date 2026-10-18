"""Only MockTransport is used: never contact a real scholarly API in CI."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from star.public_research import API, normalize_items, research_both, search_public_metadata


def run(coro):
    return asyncio.run(coro)


def handler(request: httpx.Request) -> httpx.Response:
    assert request.method == "GET"
    assert request.url.scheme == "https" and request.url.host in {"api.crossref.org", "api.openalex.org"}
    assert request.headers.get("User-Agent").startswith("STAR-metadata-research")
    if request.url.host == "api.crossref.org":
        assert request.url.params["rows"] == "2"
        return httpx.Response(200, json={"message": {"items": [
            {"title": ["A Study"], "DOI": "10.1234/abc", "published": {"date-parts": [[2025]]}},
        ]}})
    assert request.url.params["per_page"] == "2"
    return httpx.Response(200, json={"results": [{
        "title": "A Study Too", "id": "https://openalex.org/W123", "publication_year": 2026,
    }]})


def test_fixed_catalog_and_manual_network_consent():
    assert set(API) == {"crossref", "openalex"}
    with pytest.raises(PermissionError, match="consent"):
        run(search_public_metadata("robot animation", source="crossref"))
    with pytest.raises(ValueError, match="Unknown approved"):
        run(search_public_metadata("robot animation", source="example.com", allow_network=True))
    with pytest.raises(ValueError, match="printable"):
        run(search_public_metadata("\nmalicious", source="crossref", allow_network=True))
    with pytest.raises(ValueError, match="1..5"):
        run(research_both("robot animation", limit=100, allow_network=True))


def test_bounded_concurrent_two_source_search_with_provenance():
    transport = httpx.MockTransport(handler)
    result = run(research_both("robot animation", limit=2, allow_network=True, transport=transport))
    assert result["errors"] == {}
    assert [row["source"] for row in result["results"]] == ["crossref", "openalex"]
    assert len(result["results"]) == 2
    assert all(row["external_network_used"] for row in result["results"])  # fake transport in test
    assert all(row["source_api_url"].startswith("https://api.") for row in result["results"])
    assert all("project file" not in str(row) for row in result["results"])


def test_fail_closed_on_oversized_redirects_invalid_json_or_rate_limit():
    def response(status, payload=b"{}"):
        return httpx.MockTransport(lambda request: httpx.Response(status, content=payload))
    with pytest.raises(RuntimeError, match="rate-limited"):
        run(search_public_metadata("hello", source="crossref", limit=2,
                                   allow_network=True, transport=response(429)))
    with pytest.raises(RuntimeError, match="HTTP 302"):
        run(search_public_metadata("hello", source="crossref", limit=2,
                                   allow_network=True, transport=response(302)))
    with pytest.raises(RuntimeError, match="invalid JSON"):
        run(search_public_metadata("hello", source="crossref", limit=2,
                                   allow_network=True, transport=response(200, b"broken")))
    with pytest.raises(ValueError, match="size limit"):
        run(search_public_metadata("hello", source="crossref", limit=2,
                                   allow_network=True, transport=response(200, b"x" * 256001)))


def test_sanitize_titles_and_dont_return_copyrighted_abstracts():
    rows = normalize_items("crossref", {"message": {"items": [{
        "title": ["Study\n<script>"], "DOI": "10.x", "abstract": "copyrighted full text",
    }]}}, limit=2)
    assert rows[0]["title"] == "Study <script>"
    assert "abstract" not in json.dumps(rows).lower()
