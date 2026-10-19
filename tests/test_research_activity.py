"""Independent checks of the research display boundary and source-report honesty."""
from __future__ import annotations

import asyncio
import json

import pytest

from star.research_activity import (
    public_source_url,
    research_source_report,
    sanitize_research_event,
)
from star.research_session import ResearchBudget, ResearchSession
from star.web_fetch import Page


@pytest.mark.parametrize("url", [
    "https://user:password@references.example/page",
    "https://references.example/page?access_token=PRIVATE_TOKEN",
    "https://references.example/page?api%5Fkey=PRIVATE_TOKEN",
    "https://references.example/page?X-Amz-Signature=PRIVATE_TOKEN",
    "http://127.0.0.1/private",
    "http://192.168.1.1/private",
    "http://[::1]/private",
    "http://224.0.0.1/private",
    "http://[ff02::1]/private",
    "http://model.internal/private",
    "javascript:alert(1)",
    "https://references.example/\nprivate",
])
def test_source_links_hide_credentials_and_nonpublic_destinations(url):
    assert public_source_url(url) == ""


def test_source_links_preserve_document_versions_and_remove_fragment_data():
    assert public_source_url(
        "https://docs.example/api?version=2&language=en#PRIVATE_FRAGMENT"
    ) == "https://docs.example/api?version=2&language=en"


def test_real_session_events_cross_display_boundary_without_raw_evidence_or_errors():
    async def scenario():
        raw_events = []

        async def search(query, *, limit):
            return [
                {"url": "https://references.example/read", "title": "Discovery title"},
                {"url": "https://references.example/failed", "title": "Unavailable source"},
                {"url": "https://references.example/unread", "title": "A remaining lead"},
            ]

        async def fetch(url):
            if url.endswith("failed"):
                raise RuntimeError("Authorization: Bearer PRIVATE_PROVIDER_ERROR")
            return Page(url, "Read title & documentation", "PRIVATE_PAGE_BODY: ten channels.",
                        "text/plain", False)

        session = ResearchSession(
            "Roblox animation PRIVATE_OBJECTIVE", searcher=search, fetcher=fetch,
            on_event=raw_events.append,
            budget=ResearchBudget(max_queries=1, max_pages=2))
        await session.collect()
        session.report_citations("Ten channels [S1]; unknown claim [S999].")
        # A future provider or producer may add fields. They must not implicitly
        # become browser-visible just because the envelope itself is genuine.
        raw_events[0].update(query="PRIVATE_QUERY", prompt="PRIVATE_PROMPT",
                             analysis="PRIVATE_REASONING", text="PRIVATE_RAW_TEXT",
                             nested={"Authorization": "PRIVATE_NESTED_TOKEN"})
        displayed = [sanitize_research_event(event) for event in raw_events]
        assert all(item and "activity" in item for item in displayed)
        serialized = json.dumps(displayed)
        assert "PRIVATE_" not in serialized
        assert "Read title & documentation" in serialized
        source_reads = [item["activity"] for item in displayed
                        if item["activity"]["event"] == "source_read"]
        assert len(source_reads) == 1 and source_reads[0]["source_id"] == "S1"
        final = next(item["activity"] for item in reversed(displayed)
                     if item["activity"]["event"] == "research_finished")
        assert final["sources_found"] == 3
        assert final["sources_read"] == 1 and final["sources_failed"] == 1
        checked = displayed[-1]["activity"]
        assert checked["checked"] == 2 and checked["invalid"] == 1
        assert checked["semantic_support"] == "unchecked"

    asyncio.run(scenario())


@pytest.mark.parametrize("change", [
    {"seq": True},
    {"event_id": "another-run:1"},
    {"run_id": "unsafe\nrun"},
    {"query_id": "PRIVATE_QUERY"},
])
def test_malformed_envelopes_cannot_create_research_activity(change):
    event = {"event": "query_started", "run_id": "run-1", "seq": 1,
             "event_id": "run-1:1", "query_id": "Q1", "ordinal": 1}
    result = sanitize_research_event({**event, **change})
    assert result and "activity" not in result
    assert "PRIVATE_" not in json.dumps(result)


def test_semantic_verification_claim_is_not_admitted_as_a_citation_activity():
    result = sanitize_research_event({
        "event": "research_citations_checked", "run_id": "run-1", "seq": 1,
        "event_id": "run-1:1", "checked": 3, "invalid": 0,
        "semantic_support": "verified",
    })
    assert result and "activity" not in result


def test_host_source_report_discloses_unread_and_unknown_references_without_fact_badges():
    async def scenario():
        async def search(query, *, limit):
            return [
                {"url": "https://references.example/read", "title": "Readable"},
                {"url": "https://references.example/unread", "title": "Only discovered"},
                {"url": "https://references.example/signed?token=PRIVATE_URL_TOKEN", "title": "Signed lead"},
            ]

        async def fetch(url):
            return Page(url, "Reference [title] <unsafe>", "The limit is ten channels.",
                        "text/plain", False)

        session = ResearchSession(
            "Roblox animation reference evidence", searcher=search, fetcher=fetch,
            budget=ResearchBudget(max_queries=1, max_pages=1))
        await session.collect()
        # A wrong factual claim with a real citation is still only a membership
        # match. The host must say exactly what was checked, not endorse it.
        report = research_source_report(
            session, "The limit is a million channels [S1]. More [S2], [S999].")
        assert "1 pages read" in report and "3 distinct source URLs" in report
        assert "1 do not match this research session" in report
        assert "available only as search snippets: S2" in report
        assert "Claim support has not been automatically verified" in report
        assert "PRIVATE_URL_TOKEN" not in report and "link omitted" in report
        assert "[S2] Only discovered — search snippet only; page not read" in report
        assert "Reference \\[title\\] \\<unsafe\\>" in report
        assert "fact verified" not in report.lower()

    asyncio.run(scenario())
