"""Offline contract tests for Roblox Intelligence Hub and STAR chat routing.

Mocks do NOT prove live Creator Store/Analytics API access or entitlement.
"""
import json

import pytest

from star.roblox_intelligence_hub import (
    BASE, MARKET, RobloxIntelligenceHub, _operation_id, _range,
)


class Response:
    def __init__(self, data, code=200, content_type="application/json"):
        self.data = data
        self.status_code = code
        self.headers = {"content-type": content_type}
        self.content = json.dumps(data).encode("utf-8")

    def json(self):
        return self.data


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, params=None, json=None, headers=None, follow_redirects=False):
        self.calls.append({"method": method, "url": url, "params": params, "json": json,
                           "headers": headers, "follow_redirects": follow_redirects})
        if not self.responses:
            raise AssertionError("Unexpected live HTTP request")
        return self.responses.pop(0)


def setup_hub(*responses, allow="1234", key="local-fixture-key"):
    client = Client(*responses)
    hub = RobloxIntelligenceHub(client=client, key_provider=lambda: key, analytics_universes=allow)
    return hub, client


def complete(value=27):
    return {"done": True, "response": {"values": [{"breakdowns": [],
            "dataPoints": [{"time": "2026-10-01T00:00:00Z", "value": value}]}]}}


def test_no_unapproved_analytics_universe_or_missing_key():
    hub, client = setup_hub(Response(complete()))
    with pytest.raises(PermissionError, match="allowlist"):
        hub.analytics_metrics(9999, "DailyActiveUsers", "2026-10-01", "2026-10-10")
    assert not client.calls
    hub2, client2 = setup_hub(Response(complete()), key="")
    with pytest.raises(PermissionError, match="No authorized"):
        hub2.analytics_metrics(1234, "DailyActiveUsers", "2026-10-01", "2026-10-10")
    assert not client2.calls


@pytest.mark.parametrize("allow", ["abc", "1,,2", "../1234", "1234/5", "0", "-1", "1," * 25])
def test_universe_allowlist_rejects_malformed_configuration(allow):
    with pytest.raises(ValueError):
        RobloxIntelligenceHub(client=Client(), analytics_universes=allow)


def test_analytics_request_is_fixed_and_authorized_with_approved_scope():
    hub, client = setup_hub(Response(complete(100)))
    data = hub.analytics_metrics(1234, "DailyActiveUsers", "2026-10-01", "2026-10-10",
                                 breakdown="Country")
    assert data["status"] == "complete"
    assert data["series"][0]["data_points"][0]["value"] == 100
    assert data["data_kind"].startswith("private owner-authorized")
    call = client.calls[0]
    assert call["url"] == BASE + "/analytics-query-api/v1/universes/1234/metrics"
    assert call["method"] == "POST" and call["follow_redirects"] is False
    assert call["json"] == {"metric": "DailyActiveUsers", "granularity": "OneDay",
                            "startTime": "2026-10-01T00:00:00Z",
                            "endTime": "2026-10-10T00:00:00Z", "breakdown": ["Country"]}
    assert call["headers"] == {"x-api-key": "local-fixture-key"}
    assert "local-fixture-key" not in str(data)


def test_pending_operation_cannot_escape_to_another_universe_or_host():
    pending = {"done": False, "path": "v1/universes/1234/operations/metrics/Op_abc-2"}
    hub, client = setup_hub(Response(pending), Response(complete(6)))
    first = hub.analytics_metrics(1234, "DailyActiveUsers", "2026-10-01", "2026-10-09")
    assert first["status"] == "pending"
    assert first["operation_id"] == "Op_abc-2"
    second = hub.analytics_poll(1234, first["operation_id"], metric="DailyActiveUsers")
    assert second["status"] == "complete"
    assert client.calls[-1]["url"].endswith("/v1/universes/1234/operations/metrics/Op_abc-2")
    for evil in (
        "v1/universes/9/operations/metrics/Op_abc-2",
        "https://evil.example/operation",
        "v1/universes/1234/operations/metrics/../hack",
        "v1/universes/1234/operations/metrics/",
    ):
        with pytest.raises(ValueError):
            _operation_id(evil, 1234)
    with pytest.raises(ValueError):
        hub.analytics_poll(1234, "../../invalid", metric="DailyActiveUsers")


@pytest.mark.parametrize("metric,granularity", [
    ("UnknownMetric", "OneDay"), ("ForwardD1Retention", "OneMonth"),
    ("DailyActiveUsers", "FiveMinutes"), ("DailyRevenue", "OneHour"),
])
def test_metric_allowlist_and_granularity_fail_before_network(metric, granularity):
    hub, client = setup_hub(Response(complete()))
    with pytest.raises(ValueError):
        hub.analytics_metrics(1234, metric, "2026-10-01", "2026-10-04",
                              granularity=granularity)
    assert not client.calls


@pytest.mark.parametrize("start,end", [
    ("2026-10-10", "2026-10-10"), ("2026-10-11", "2026-10-10"),
    ("2026-01-01", "2026-05-01"), ("2026-02-30", "2026-03-01"),
    ("2000/01/01", "2000-01-05"), ("2026-10-01T00:00:00Z", "2026-10-05"),
])
def test_invalid_or_too_wide_date_window_refused(start, end):
    with pytest.raises(ValueError):
        _range(start, end)


def test_private_analytics_denial_and_rate_limit_are_distinct_without_tokens():
    for code, exception in [(403, PermissionError), (429, ValueError), (500, ValueError)]:
        hub, client = setup_hub(Response({}, code=code))
        with pytest.raises(exception) as err:
            hub.analytics_metrics(1234, "DailyRevenue", "2026-10-01", "2026-10-08")
        assert "local-fixture-key" not in str(err.value)
        assert len(client.calls) == 1


def test_analytics_errors_and_unverified_payloads_are_not_successes():
    for payload in (
        {"done": True, "error": {"code": 2001}},
        {"done": True, "response": {}},
        {"done": False, "path": "v1/universes/999/operations/metrics/not_yours"},
        {"data": [1, 2]},
    ):
        hub, _ = setup_hub(Response(payload))
        with pytest.raises(ValueError):
            hub.analytics_metrics(1234, "DailyActiveUsers", "2026-10-01", "2026-10-08")


def test_public_marketplace_search_fixed_host_and_bounded_metadata():
    hub, client = setup_hub(Response({"data": [
        {"id": 123, "name": "Hat", "creatorName": "Alice", "price": 14, "itemType": "Asset"},
        {"id": 44, "name": "Shirt", "price": 0},
        {"id": "-2", "name": "BAD"}],
        "nextPageCursor": "opaque-and-not-followed"}))
    result = hub.marketplace_search("hat", category=11)
    assert len(result["results"]) == 2
    assert result["next_page_unchecked"]
    assert result["results"][0]["url"] == "https://www.roblox.com/catalog/123"
    assert client.calls[0]["url"] == MARKET + "/v1/search/items/details"
    assert client.calls[0]["params"] == {"Keyword": "hat", "Category": 11, "Limit": 10}
    assert "x-api-key" not in client.calls[0]["headers"]


# Response shapes recorded from the live public endpoints on 2026-10-21 (no sign-in), trimmed.
LIVE_STORE_SEARCH = {"nextPageToken": "opaque", "totalResults": 25, "queryFacets": {"availableFacets": ["pine"]},
                     "creatorStoreAssets": [
                         {"creator": {"creator": "user/24773541", "userId": 24773541, "name": "SheriffTaco", "verified": True},
                          "asset": {"id": 580221169, "name": "Tree", "description": "", "hasScripts": False,
                                    "assetTypeId": 10, "categoryPath": "3d__nature"}},
                         {"asset": {"id": "-5", "name": "BAD"}}, {"id": 7, "name": "flat item is not the live shape"}]}
LIVE_STORE_ASSET = {"creator": {"name": "SheriffTaco"},
                    "asset": {"id": 580221169, "name": "Tree", "description": "Just sample metadata", "hasScripts": False}}


def test_creator_store_search_and_asset_details_use_live_get_shapes_and_no_uploads():
    hub, client = setup_hub(Response(LIVE_STORE_SEARCH), Response(LIVE_STORE_ASSET))
    result = hub.creator_store_search("trees", category="Model")
    details = hub.creator_asset(580221169)
    assert result["beta"] and result["results"] == [
        {"asset_id": 580221169, "name": "Tree", "creator": "SheriffTaco",
         "url": "https://create.roblox.com/store/asset/580221169"}]
    assert client.calls[0]["url"] == BASE + "/toolbox-service/v2/assets:search"
    assert client.calls[0]["method"] == "GET" and client.calls[0]["json"] is None
    assert client.calls[0]["params"] == {"searchCategoryType": "Model", "query": "trees"}
    assert client.calls[1]["method"] == "GET" and client.calls[1]["url"].endswith("/assets/580221169")
    assert details["name"] == "Tree" and details["description_excerpt"] == "Just sample metadata"
    assert details["data_kind"].startswith("untrusted public")
    assert all("x-api-key" not in item["headers"] for item in client.calls)


@pytest.mark.parametrize("payload", [{"data": [{"id": 1, "name": "old shape"}]}, {"creatorStoreAssets": {}}, {}])
def test_creator_store_search_fails_closed_on_an_unrecognized_shape(payload):
    hub, _ = setup_hub(Response(payload))
    with pytest.raises(ValueError, match="unrecognized shape"):
        hub.creator_store_search("trees")


@pytest.mark.parametrize("payload", [{"name": "Tree"}, {"asset": []}, {"asset": {"id": 5, "name": "Other asset"}}])
def test_creator_asset_fails_closed_when_details_do_not_match_the_request(payload):
    hub, _ = setup_hub(Response(payload))
    with pytest.raises(ValueError, match="unrecognized shape"):
        hub.creator_asset(580221169)


def test_public_endpoint_needing_sign_in_says_so_and_never_sends_a_key():
    hub, client = setup_hub(Response({"errors": [{"code": 0, "message": "XSRF token invalid"}]}, code=403))
    with pytest.raises(PermissionError, match="does not sign in"):
        hub.creator_store_search("trees")
    assert "x-api-key" not in client.calls[0]["headers"]


@pytest.mark.parametrize("category", [2, 4, 5, 13])
def test_marketplace_categories_roblox_rejects_live_are_refused_before_any_request(category):
    hub, client = setup_hub()
    with pytest.raises(ValueError, match="Unknown Marketplace category"):
        hub.marketplace_search("hat", category=category)
    assert not client.calls


@pytest.mark.parametrize("name,keyword", [
    ("marketplace_search", "test\ntrick"),
    ("creator_store_search", "a\x00b"),
])
def test_reject_control_character_queries(name, keyword):
    hub, client = setup_hub()
    with pytest.raises(ValueError):
        getattr(hub, name)(keyword)
    assert not client.calls


def test_no_full_player_data_or_claimed_gameplay():
    hub, _ = setup_hub(allow="")
    status = hub.status()
    plan = hub.gameplay_plan()
    assert not status["creator_analytics_opt_in"]
    assert status["player_data_entries"] == "not exposed"
    assert status["gameplay_recordings"] == "not acquired"
    assert plan["tested"] is False
    assert "NOT player statistics" in plan["note"]


def test_tool_router_lists_public_catalog_and_telemetry_but_not_analytics_by_default(tmp_path):
    from star.intelligence import LocalIntelligence

    hub = LocalIntelligence(home=tmp_path, skills_enabled=False, graphify_enabled=False,
                            design_enabled=False, roblox_research_enabled=True)
    try:
        catalog = {t["name"] for t in hub.definitions("Research Roblox marketplace catalog hats")}
        assert "star_roblox_marketplace_search" in catalog
        assert "star_roblox_creator_store_search" in catalog
        assert "star_roblox_analytics_metrics" not in catalog
        gameplay = {t["name"] for t in hub.definitions("Research Roblox gameplay telemetry")}
        assert "star_roblox_gameplay_telemetry_plan" in gameplay
        data = hub.call("star_roblox_gameplay_telemetry_plan", {},
                        enabled={"star_roblox_gameplay_telemetry_plan"})
        assert not data["tested"]
    finally:
        hub.close()


@pytest.mark.parametrize("prompt", [
    "Write Luau for a Roblox Studio plugin settings panel",
    "Roblox obby: explain the game mechanics and level progression",
    "Roblox server: track session state and metrics in a DataStore",
    "Roblox tycoon statistics leaderboard with a catalog of upgrades",
])
def test_ordinary_roblox_chats_do_not_pay_for_hub_tool_schemas(tmp_path, monkeypatch, prompt):
    from star.intelligence import LocalIntelligence

    monkeypatch.setenv("STAR_ROBLOX_ANALYTICS_UNIVERSES", "1234")
    hub = LocalIntelligence(home=tmp_path, skills_enabled=False, graphify_enabled=False,
                            design_enabled=False, roblox_research_enabled=True)
    try:
        names = {t["name"] for t in hub.definitions(prompt)}
        assert not {t for t in names if t.startswith(("star_roblox_marketplace", "star_roblox_creator_",
                                                      "star_roblox_analytics", "star_roblox_gameplay"))}
    finally:
        hub.close()


@pytest.mark.parametrize("prompt", [
    "Find a Roblox plugin for terrain",
    "Search the Creator Store for tree models for my Roblox game",
    "Roblox avatar accessories on the marketplace",
])
def test_explicit_catalog_requests_still_get_the_catalog_tools(tmp_path, prompt):
    from star.intelligence import LocalIntelligence

    hub = LocalIntelligence(home=tmp_path, skills_enabled=False, graphify_enabled=False,
                            design_enabled=False, roblox_research_enabled=True)
    try:
        assert "star_roblox_creator_store_search" in {t["name"] for t in hub.definitions(prompt)}
    finally:
        hub.close()


def test_router_exposes_analytics_only_with_explicit_owner_universe_allowlist(tmp_path, monkeypatch):
    from star.intelligence import LocalIntelligence

    monkeypatch.setenv("STAR_ROBLOX_ANALYTICS_UNIVERSES", "1234")
    hub = LocalIntelligence(home=tmp_path, skills_enabled=False, graphify_enabled=False,
                            design_enabled=False, roblox_research_enabled=True)
    try:
        tools = {t["name"] for t in hub.definitions("Roblox revenue analytics last week")}
        assert "star_roblox_analytics_metrics" in tools
        assert "star_roblox_analytics_poll" in tools
        assert "star_roblox_creator_asset" not in tools
    finally:
        hub.close()

def test_bad_environment_allowlist_does_not_break_existing_star_research(tmp_path, monkeypatch):
    from star.intelligence import LocalIntelligence

    monkeypatch.setenv("STAR_ROBLOX_ANALYTICS_UNIVERSES", "bad/123")
    hub = LocalIntelligence(home=tmp_path, skills_enabled=False, graphify_enabled=False,
                            design_enabled=False, roblox_research_enabled=True)
    try:
        state = hub.status()["roblox_intelligence_hub"]
        assert state["analytics_configuration_error"] is True
        assert state["creator_analytics_opt_in"] is False
        names = {t["name"] for t in hub.definitions("Research Roblox marketplace catalog")}
        assert "star_roblox_marketplace_search" in names
        assert "star_roblox_analytics_metrics" not in names
    finally:
        hub.close()
