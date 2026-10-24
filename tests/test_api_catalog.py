import asyncio

import httpx
import pytest

from star.api_catalog import (
    ApiCatalogDiscovery,
    CACHE_TTL_SECONDS,
    CATALOG_URL,
    MAX_REPLY_BYTES,
)


SAMPLE = """
## Index

### Weather
API | Description | Auth | HTTPS | CORS |
|:---|:---|:---|:---|:---|
| [Open Weather Demo](https://weather.example.test/docs) | Weather forecast data | No | Yes | Yes |
| [Weather Keyed](https://keyed.example.test/docs) | Historical weather | `apiKey` | Yes | Unknown |

### Currency Exchange
API | Description | Auth | HTTPS | CORS |
|:---|:---|:---|:---|:---|
| [Currency Demo](https://currency.example.test/docs) | Currency exchange rates | No | Yes | Yes |
"""


def _transport(body=SAMPLE, *, count=None):
    def handler(request):
        assert str(request.url) == CATALOG_URL
        if count is not None:
            count.append(1)
        return httpx.Response(200, headers={"content-type": "text/plain; charset=utf-8"}, text=body)
    return httpx.MockTransport(handler)


def test_definitions_are_prompt_gated(tmp_path):
    catalog = ApiCatalogDiscovery(home=tmp_path, transport=_transport(), now_fn=lambda: 1000.0)
    assert catalog.definitions("find a weather API")
    assert catalog.definitions("research an integration endpoint")
    assert catalog.definitions("build a Roblox sword") == []


def test_live_fetch_is_parsed_ranked_and_discovery_only(tmp_path):
    catalog = ApiCatalogDiscovery(home=tmp_path, transport=_transport(), now_fn=lambda: 1000.0)
    result = asyncio.run(catalog.call("star_api_catalog_search", {"query": "weather forecast", "limit": 2}))
    assert result["catalog_entries"] == 3
    assert result["catalog_stale"] is False
    assert result["results"][0]["name"] == "Open Weather Demo"
    assert result["results"][0]["category"] == "Weather"
    assert all(row["status"] == "discovery_only_unverified" for row in result["results"])
    assert "No discovered API was called" in result["notice"]


def test_fresh_disk_cache_avoids_network_on_next_instance(tmp_path):
    calls = []
    first = ApiCatalogDiscovery(home=tmp_path, transport=_transport(count=calls), now_fn=lambda: 1000.0)
    asyncio.run(first.call("star_api_catalog_search", {"query": "currency exchange"}))
    assert len(calls) == 1

    def should_not_run(request):
        raise AssertionError("fresh cache should prevent a network request")

    second = ApiCatalogDiscovery(
        home=tmp_path,
        transport=httpx.MockTransport(should_not_run),
        now_fn=lambda: 1001.0,
    )
    result = asyncio.run(second.call("star_api_catalog_search", {"query": "currency exchange"}))
    assert result["catalog_stale"] is False
    assert result["results"][0]["name"] == "Currency Demo"


def test_stale_cache_is_used_when_refresh_is_offline(tmp_path):
    first = ApiCatalogDiscovery(home=tmp_path, transport=_transport(), now_fn=lambda: 1000.0)
    asyncio.run(first.call("star_api_catalog_search", {"query": "weather"}))

    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    second = ApiCatalogDiscovery(
        home=tmp_path,
        transport=httpx.MockTransport(offline),
        now_fn=lambda: 1000.0 + CACHE_TTL_SECONDS + 1,
    )
    result = asyncio.run(second.call("star_api_catalog_search", {"query": "weather"}))
    assert result["catalog_stale"] is True
    assert result["results"]


def test_without_cache_network_failure_is_reported(tmp_path):
    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    catalog = ApiCatalogDiscovery(
        home=tmp_path,
        transport=httpx.MockTransport(offline),
        now_fn=lambda: 1000.0,
    )
    with pytest.raises(httpx.ConnectError):
        asyncio.run(catalog.call("star_api_catalog_search", {"query": "weather"}))


def test_response_size_is_bounded_before_caching(tmp_path):
    huge = "x" * (MAX_REPLY_BYTES + 1)
    catalog = ApiCatalogDiscovery(home=tmp_path, transport=_transport(huge), now_fn=lambda: 1000.0)
    with pytest.raises(ValueError, match="too large"):
        asyncio.run(catalog.call("star_api_catalog_search", {"query": "weather"}))


def test_per_turn_call_budget_is_bounded(tmp_path):
    catalog = ApiCatalogDiscovery(home=tmp_path, transport=_transport(), now_fn=lambda: 1000.0)
    for _ in range(3):
        asyncio.run(catalog.call("star_api_catalog_search", {"query": "weather"}))
    with pytest.raises(RuntimeError, match="budget exhausted"):
        asyncio.run(catalog.call("star_api_catalog_search", {"query": "weather"}))


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "x"},
        {"query": "weather", "limit": 13},
        {"query": "weather", "extra": True},
    ],
)
def test_schema_rejects_bad_requests(tmp_path, arguments):
    catalog = ApiCatalogDiscovery(home=tmp_path, transport=_transport(), now_fn=lambda: 1000.0)
    with pytest.raises(Exception):
        asyncio.run(catalog.call("star_api_catalog_search", arguments))
