"""Scholarly metadata for deep research: offline only (fake page readers and httpx.MockTransport)."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from star.public_research import normalize_items, search_metadata, with_scholarly_metadata
from star.web_fetch import Page

CROSSREF = {"message": {"items": [
    {"title": ["Motion Matching\nfor Games"], "DOI": "10.1145/3450626", "issued": {"date-parts": [[2021, 5]]},
     "abstract": "copyrighted abstract text"},
    {"title": ["No identifier"]},
]}}
OPENALEX = {"results": [
    {"title": "Learned Locomotion", "id": "https://openalex.org/W123", "doi": "https://doi.org/10.1000/xyz",
     "publication_year": 2024},
]}


def _json_page(url: str, body: object) -> Page:
    return Page(url=url, title="", text=json.dumps(body), content_type="application/json", truncated=False)


async def fake_fetch(url: str) -> Page:
    if url.startswith("https://api.crossref.org/works?"):
        return _json_page(url, CROSSREF)
    if url.startswith("https://api.openalex.org/works?"):
        return _json_page(url, OPENALEX)
    raise AssertionError(f"unexpected URL {url}")


def test_rows_are_search_results_with_identifiers_and_no_abstracts():
    rows = normalize_items("crossref", CROSSREF, limit=2)
    assert rows == [{"title": "Motion Matching for Games", "url": "https://doi.org/10.1145/3450626",
                     "snippet": rows[0]["snippet"], "published": "2021"}]
    assert "abstract" not in json.dumps(rows).lower()
    assert normalize_items("openalex", OPENALEX, limit=2)[0]["url"] == "https://doi.org/10.1000/xyz"
    with pytest.raises(ValueError, match="schema"):
        normalize_items("openalex", {"results": "nope"}, limit=2)


def test_only_fixed_provider_urls_are_requested():
    seen = []

    async def fetch(url):
        seen.append(url)
        return await fake_fetch(url)

    rows = asyncio.run(search_metadata("motion matching\nanimation " + "x" * 200, source="crossref", fetcher=fetch))
    assert rows[0]["url"] == "https://doi.org/10.1145/3450626"
    assert seen[0].startswith("https://api.crossref.org/works?query.bibliographic=motion+matching+animation")
    assert "%0A" not in seen[0] and "select=DOI%2Ctitle%2Cissued" in seen[0]
    with pytest.raises(ValueError, match="approved"):
        asyncio.run(search_metadata("motion", source="https://evil.example", fetcher=fetch))
    truncated = SimpleNamespace(truncated=True, text="{}")

    async def big(url):
        return truncated
    with pytest.raises(ValueError, match="text limit"):
        asyncio.run(search_metadata("motion", source="openalex", fetcher=big))


def test_requests_go_through_the_guarded_page_reader():
    """The real fetch_page: the checked public address is dialled, a private resolution is refused."""
    from star.web_fetch import fetch_page
    dialled = []

    def handler(request: httpx.Request) -> httpx.Response:
        dialled.append((request.url.host, request.headers["host"]))
        return httpx.Response(200, json=CROSSREF, headers={"content-type": "application/json"})

    async def reader(url, resolve_to):
        return await fetch_page(url, transport=httpx.MockTransport(handler), resolver=lambda host, port: [resolve_to])

    rows = asyncio.run(search_metadata("motion", source="crossref",
                                       fetcher=lambda url: reader(url, "104.18.0.1")))
    assert rows and dialled == [("104.18.0.1", "api.crossref.org")]
    with pytest.raises(ValueError, match="private or reserved"):
        asyncio.run(search_metadata("motion", source="crossref", fetcher=lambda url: reader(url, "10.0.0.5")))  # star:allow refused private address


def test_wrapper_adds_metadata_to_the_first_query_only_and_survives_provider_failure():
    calls = []

    async def web(query, *, limit):
        calls.append(query)
        return [{"url": f"https://web.example/{i}", "title": "Web", "snippet": "s"} for i in range(limit)]

    search = with_scholarly_metadata(web, fetcher=fake_fetch)
    first = asyncio.run(search("motion matching", limit=4))
    assert [row["url"] for row in first] == ["https://web.example/0", "https://doi.org/10.1145/3450626",
                                             "https://web.example/1", "https://doi.org/10.1000/xyz"]
    second = asyncio.run(search("motion matching limitations", limit=4))
    assert all(row["url"].startswith("https://web.example/") for row in second)

    async def broken(url):
        raise httpx.ConnectError("down")
    failing = with_scholarly_metadata(web, fetcher=broken)
    assert len(asyncio.run(failing("motion matching", limit=4))) == 4


def test_team_deep_research_uses_metadata_only_when_the_setting_is_on(tmp_path):
    from star.desktop_core import Settings
    from star.research_session import ResearchBudget
    from star.team_service import run_research_team

    class Completions:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Answer [S1].", tool_calls=None))])

    async def scenario(enabled: bool) -> list[str]:
        requested = []

        async def web(query, *, limit):
            return [{"url": "https://web.example/a", "title": "Web", "snippet": "Animation evidence"}]

        async def fetch(url):
            requested.append(url)
            if url.startswith("https://api."):
                return await fake_fetch(url)
            return Page(url=url, title="Page", text="Animation page text.", content_type="text/plain", truncated=False)

        settings = Settings(endpoint="http://127.0.0.1:8080/v1", model="offline", project="STAR",
                            knowledge_endpoint="off", deep_research_enabled=True,
                            scholarly_research_enabled=enabled)
        await run_research_team(prompt="Compare animation motion matching methods", home=tmp_path / str(enabled),
                                settings=settings, parallel=1, research=True, web_provider=web, page_provider=fetch,
                                client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
                                research_budget=ResearchBudget(total_seconds=5))
        return requested

    off = asyncio.run(scenario(False))
    assert off and not any(url.startswith("https://api.") for url in off)
    on = asyncio.run(scenario(True))
    assert any(url.startswith("https://api.crossref.org/works?") for url in on)
    assert any(url.startswith("https://api.openalex.org/works?") for url in on)
    assert any(url.startswith("https://doi.org/10.1145/3450626") for url in on)   # read as a normal source page
    assert Settings().scholarly_research_enabled is False
