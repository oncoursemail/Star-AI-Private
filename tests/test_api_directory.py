"""Offline contract tests for the APIs.guru discovery and inspected-spec boundary."""
from __future__ import annotations

import asyncio
import sqlite3

import httpx
import pytest

from star.api_catalog import ApiCatalogDiscovery
from star.api_directory import (
    ApiGuruDirectory,
    DIRECTORY_URL,
    DIRECTORY_TTL_SECONDS,
    MAX_STALE_SECONDS,
    SPEC_MAX_BYTES,
    parse_directory,
    spec_url_allowed,
)


SPEC_URL = "https://api.apis.guru/v2/specs/weather.test/1.2.0/openapi.json"
BAD_URL = "https://private.example/openapi.json"

DIRECTORY = {
    "weather.test": {
        "preferred": "1.2.0",
        "versions": {
            "1.2.0": {
                "info": {
                    "title": "Weather Forecast",
                    "description": "Historical weather and forecast data",
                    "x-apisguru-categories": ["weather"],
                    "x-origin": [{"url": "https://weather.test/openapi.yaml"}],
                },
                "swaggerUrl": SPEC_URL,
                "openapiVer": "3.1.0",
                "updated": "2026-10-24",
            },
            "1.1.0": {
                "info": {"title": "Old forecast"},
                "swaggerUrl": "https://api.apis.guru/v2/specs/weather.test/1.1.0/openapi.json",
            },
        },
    },
    "unsafe.test": {
        "preferred": "1.0",
        "versions": {"1.0": {"info": {"title": "Unsafe"}, "swaggerUrl": BAD_URL}},
    },
}

SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Weather Forecast", "version": "1.2.0"},
    "servers": [{"url": "https://api.weather.test"}, {"url": "http://old.weather.test"}],
    "components": {"securitySchemes": {"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "x-key"}}},
    "paths": {
        "/forecast": {"get": {"operationId": "getForecast"}},
        "/alerts": {"post": {"operationId": "createAlert"}},
    },
}


def run(value):
    return asyncio.run(value)


def response(request, *, events=None, directory=DIRECTORY, spec=SPEC):
    if events is not None:
        events.append((request.method, str(request.url), request.headers.get("authorization")))
    if str(request.url) == DIRECTORY_URL:
        return httpx.Response(200, headers={"content-type": "application/json"}, json=directory)
    if str(request.url) == SPEC_URL:
        return httpx.Response(200, headers={"content-type": "application/json"}, json=spec)
    if str(request.url) == "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md":
        body = (
            "### Weather\nAPI | Description | Auth | HTTPS | CORS |\n"
            "|:---|:---|:---|:---|:---|\n"
            "| [Public Forecast](https://forecast.test/) | Weather forecast data | No | Yes | Yes |\n"
        )
        return httpx.Response(200, headers={"content-type": "text/plain"}, text=body)
    raise AssertionError("Unexpected target: " + str(request.url))


def test_parser_prefers_one_version_and_refuses_unsafe_spec_urls():
    rows = parse_directory(DIRECTORY)
    assert len(rows) == 1
    assert rows[0].provider_id == "weather.test"
    assert rows[0].title == "Weather Forecast"
    assert rows[0].categories == ("weather",)
    assert rows[0].spec_url == SPEC_URL
    assert rows[0].origin_urls == ("https://weather.test/openapi.yaml",)


@pytest.mark.parametrize("url", [
    "http://api.apis.guru/v2/specs/test/1.json",
    "https://api.apis.guru.evil.test/v2/specs/test/1.json",
    "https://api.apis.guru:8443/v2/specs/test/1.json",
    "https://user:secret@api.apis.guru/v2/specs/test/1.json",
    "https://api.apis.guru/v2/list.json",
    "https://api.apis.guru/v2/specs/a?token=secret",
    "https://api.apis.guru/v2/specs/a#x",
    "https://api.apis.guru/v2/specs/../internal",
])
def test_spec_urls_are_pinned_to_one_origin(url):
    assert not spec_url_allowed(url)


def test_directory_fetch_and_disk_hot_cache(tmp_path):
    events = []
    transport = httpx.MockTransport(lambda request: response(request, events=events))
    directory = ApiGuruDirectory(home=tmp_path, transport=transport, now_fn=lambda: 1000.0)
    first = run(directory.listing())
    assert len(first.entries) == 1 and not first.stale
    assert first.sha256 and len(events) == 1
    second = ApiGuruDirectory(home=tmp_path, transport=transport, now_fn=lambda: 1001.0)
    assert run(second.listing()).sha256 == first.sha256
    assert len(events) == 1


def test_spec_inspection_is_read_only_and_resolves_no_references(tmp_path):
    events = []
    transport = httpx.MockTransport(lambda request: response(request, events=events))
    reader = ApiGuruDirectory(home=tmp_path, transport=transport, now_fn=lambda: 1000.0)
    result = run(reader.inspect("weather.test"))
    assert result["spec_sha256"]
    assert result["source"] == SPEC_URL
    assert result["operation_count"] == 2
    assert "GET /forecast (getForecast)" in result["operations"]
    assert result["write_operation_count"] == 1
    assert result["auth_schemes"] == ["ApiKeyAuth"]
    assert result["server_urls"] == ["https://api.weather.test"]
    assert result["server_urls_hidden"] == 1
    assert result["publisher_verified"] is False
    assert result["executable"] is False
    assert result["typed_read_contracts"]
    assert result["typed_read_contracts"][0]["method"] == "GET"
    assert result["typed_read_contracts"][0]["status"] == "preview_only_no_execution"
    assert result["external_refs_resolved"] is False
    assert len(events) == 2
    assert all(method == "GET" and auth is None for method, _, auth in events)
    again = run(reader.inspect("weather.test"))
    assert again["spec_sha256"] == result["spec_sha256"]
    assert len(events) == 2


def test_spec_input_is_provider_id_not_a_url(tmp_path):
    reader = ApiGuruDirectory(home=tmp_path, transport=httpx.MockTransport(response), now_fn=lambda: 1000.0)
    with pytest.raises(ValueError, match="provider ID"):
        run(reader.inspect("https://api.apis.guru/v2/specs/test"))
    with pytest.raises(ValueError, match="Provider not present"):
        run(reader.inspect("unlisted.test"))


def test_spec_endpoint_cannot_redirect_to_a_private_address(tmp_path):
    def redirect(request):
        if str(request.url) == DIRECTORY_URL:
            return response(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
    reader = ApiGuruDirectory(home=tmp_path, transport=httpx.MockTransport(redirect), now_fn=lambda: 1000.0)
    with pytest.raises(RuntimeError, match="unavailable"):
        run(reader.inspect("weather.test"))


def test_spec_size_limit_prevents_cache_write(tmp_path):
    def enormous(request):
        if str(request.url) == DIRECTORY_URL:
            return response(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"x" * (SPEC_MAX_BYTES + 1))
    reader = ApiGuruDirectory(home=tmp_path, transport=httpx.MockTransport(enormous), now_fn=lambda: 1000.0)
    with pytest.raises(ValueError, match="size"):
        run(reader.inspect("weather.test"))


def test_corrupted_directory_cache_is_not_used_as_evidence(tmp_path):
    events = []
    transport = httpx.MockTransport(lambda request: response(request, events=events))
    directory = ApiGuruDirectory(home=tmp_path, transport=transport, now_fn=lambda: 1000.0)
    run(directory.listing())
    with sqlite3.connect(directory.path) as db:
        db.execute("UPDATE directory SET body=?", (b"tampered",))
    new = ApiGuruDirectory(home=tmp_path, transport=transport, now_fn=lambda: 1001.0)
    assert len(run(new.listing()).entries) == 1
    assert len(events) == 2


def test_stale_fallback_is_labelled_but_expires(tmp_path):
    warm = ApiGuruDirectory(
        home=tmp_path, transport=httpx.MockTransport(response), now_fn=lambda: 1000.0
    )
    run(warm.listing())
    def offline(request):
        raise httpx.ConnectError("offline", request=request)
    stale = ApiGuruDirectory(
        home=tmp_path, transport=httpx.MockTransport(offline),
        now_fn=lambda: 1000.0 + DIRECTORY_TTL_SECONDS + 1
    )
    assert run(stale.listing()).stale is True
    expired = ApiGuruDirectory(
        home=tmp_path, transport=httpx.MockTransport(offline),
        now_fn=lambda: 1000.0 + MAX_STALE_SECONDS + 1
    )
    with pytest.raises(httpx.ConnectError):
        run(expired.listing())


class FakeRegistry:
    def __init__(self):
        self.calls = []

    async def call(self, name, args):
        assert name == "star_mcp_registry_search"
        self.calls.append(args)
        return {"servers": [{
            "name": "example/weather",
            "description": "weather forecast tools for climate data",
            "repository_url": "https://github.com/example/weather",
            "version": "1.0",
        }]}


def test_combined_api_search_and_guru_only_search(tmp_path):
    calls = []
    transport = httpx.MockTransport(lambda request: response(request, events=calls))
    registry = FakeRegistry()
    catalog = ApiCatalogDiscovery(
        home=tmp_path, transport=transport, now_fn=lambda: 1000.0,
        mcp_registry=registry,
    )
    openapi = run(catalog.call("star_api_catalog_search", {
        "query": "weather forecast", "source": "openapi", "limit": 3,
    }))
    assert openapi["results"][0]["origin"] == "apis.guru"
    assert openapi["results"][0]["provider_id"] == "weather.test"
    assert openapi["catalog_entries"] == 1
    combined = run(catalog.call("star_api_catalog_search", {
        "query": "weather forecast", "source": "all", "limit": 4,
    }))
    assert {item["origin"] for item in combined["results"]} == {
        "public-apis", "apis.guru", "official-mcp-registry",
    }
    assert combined["catalog_entries"] == 3
    assert combined["source_failures"] == []
    assert len(registry.calls) == 1
    mcp = next(row for row in combined["results"] if row["kind"] == "mcp")
    assert mcp["installed"] is False and mcp["publisher_verified"] is False


def test_tool_can_inspect_only_catalog_listed_provider(tmp_path):
    transport = httpx.MockTransport(response)
    catalog = ApiCatalogDiscovery(home=tmp_path, transport=transport, now_fn=lambda: 1000.0)
    result = run(catalog.call("star_api_spec_inspect", {"provider_id": "weather.test"}))
    assert result["status"] == "spec_observed_unverified_vendor"
    assert result["executable"] is False
    assert result["operation_count"] == 2


def test_schema_refuses_user_supplied_host(tmp_path):
    catalog = ApiCatalogDiscovery(home=tmp_path, transport=httpx.MockTransport(response), now_fn=lambda: 1000.0)
    with pytest.raises(Exception):
        run(catalog.call("star_api_catalog_search", {"query": "weather", "source": "https://evil.test"}))
    with pytest.raises(Exception):
        run(catalog.call("star_api_spec_inspect", {"provider_id": "weather.test", "url": "https://evil.test"}))



def test_registry_only_mode_never_installs_or_authorizes(tmp_path):
    registry = FakeRegistry()
    catalog = ApiCatalogDiscovery(
        home=tmp_path, transport=httpx.MockTransport(response), now_fn=lambda: 1000.0,
        mcp_registry=registry,
    )
    result = run(catalog.call("star_api_catalog_search", {
        "query": "weather forecast", "source": "mcp", "limit": 3,
    }))
    assert result["catalog_entries"] == 1
    assert result["results"][0]["kind"] == "mcp"
    assert result["results"][0]["connected"] is False
    assert result["results"][0]["status"] == "discovery_only_unverified"
    assert len(registry.calls) == 1
