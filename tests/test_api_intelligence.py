import json
import pytest

from star.api_intelligence import (
    ApiCandidate,
    catalog_fingerprint,
    integration_plan,
    parse_public_apis_markdown,
    rank_api_candidates,
    snapshot_manifest,
    summarize_arazzo,
    summarize_openapi,
)


SAMPLE = """
## Weather

| API | Description | Auth | HTTPS | CORS |
| --- | --- | --- | --- | --- |
| [Open-Meteo](https://open-meteo.com/) | Weather forecasts and historical data | No | Yes | Yes |
| [Old Weather](http://example.test/weather) | Legacy weather endpoint | apiKey | No | Unknown |

## Finance

| API | Description | Auth | HTTPS | CORS |
| --- | --- | --- | --- | --- |
| [Coin Demo](https://example.test/coin) | Cryptocurrency prices | apiKey | Yes | No |
"""


def test_public_apis_parser_tracks_category_and_operational_fields():
    rows = parse_public_apis_markdown(SAMPLE)
    assert len(rows) == 3
    assert rows[0].name == "Open-Meteo"
    assert rows[0].category == "Weather"
    assert rows[0].auth == "No"
    assert rows[0].https is True
    assert rows[0].cors == "yes"


def test_ranking_prefers_relevant_https_no_auth_candidate():
    rows = parse_public_apis_markdown(SAMPLE)
    ranked = rank_api_candidates(rows, "weather forecasts")
    assert ranked[0].name == "Open-Meteo"
    assert ranked[0].score > ranked[1].score
    assert "no API key listed" in ranked[0].reasons
    assert "catalog marks API as not HTTPS" in ranked[1].warnings


def test_openapi_summary_surfaces_auth_and_mutating_operations():
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1"},
        "servers": [{"url": "https://api.example.test"}],
        "components": {"securitySchemes": {"ApiKey": {"type": "apiKey", "in": "header", "name": "X-Key"}}},
        "paths": {
            "/items": {
                "get": {"operationId": "listItems"},
                "post": {"operationId": "createItem"},
            }
        },
    }
    summary = summarize_openapi(spec)
    assert "GET /items (listItems)" in summary.operations
    assert "POST /items (createItem)" in summary.write_operations
    assert summary.auth_schemes == ("ApiKey",)
    assert any("mutating operations" in warning for warning in summary.warnings)


def test_integration_plan_is_review_only_and_separates_writes():
    candidate = ApiCandidate(
        name="Example", url="https://docs.example.test", description="demo",
        auth="OAuth", https=True, cors="yes",
    )
    openapi = summarize_openapi({
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1"},
        "servers": [{"url": "https://api.example.test"}],
        "components": {"securitySchemes": {"OAuth": {"type": "oauth2"}}},
        "paths": {"/thing": {"delete": {"operationId": "deleteThing"}}},
    })
    plan = integration_plan(candidate, "manage things", openapi=openapi)
    assert plan.executable_by_star is False
    assert any("separate per-integration permission" in step for step in plan.implementation_steps)
    assert any("owner-authorized" in flag for flag in plan.risk_flags)


def test_snapshot_manifest_is_deterministic_and_requires_https():
    first = snapshot_manifest(source_url="https://example.test/catalog", body="abc", retrieved_at="2026-10-24T17:00:00-05:00")
    payload = json.loads(first)
    assert payload["sha256"] == catalog_fingerprint("abc")
    assert payload["bytes"] == 3
    with pytest.raises(ValueError):
        snapshot_manifest(source_url="http://example.test/catalog", body="abc", retrieved_at="now")



def test_arazzo_summary_extracts_workflows_without_granting_execution():
    summary = summarize_arazzo({
        "arazzo": "1.1.0",
        "info": {"title": "Weather workflow", "version": "1"},
        "sourceDescriptions": [
            {"name": "weather", "url": "https://api.example.test/openapi.json", "type": "openapi"}
        ],
        "workflows": [{
            "workflowId": "forecastAndAlert",
            "steps": [
                {"stepId": "forecast", "operationId": "getForecast", "timeout": 2000},
                {"stepId": "notify", "operationPath": "$sourceDescriptions.weather#/paths/~1alerts/post"},
            ],
        }],
    })
    assert summary.version == "1.1.0"
    assert summary.workflows == ("forecastAndAlert",)
    assert summary.step_count == 2
    assert "getForecast" in summary.operation_references
    assert any("not execution permission" in warning for warning in summary.warnings)


def test_arazzo_summary_flags_credentialed_or_plaintext_sources():
    summary = summarize_arazzo({
        "arazzo": "1.1.0",
        "info": {"title": "Unsafe", "version": "1"},
        "sourceDescriptions": [
            {"name": "bad", "url": "http://user:pass@example.test/openapi.json", "type": "openapi"}
        ],
        "workflows": [{"workflowId": "one", "steps": []}],
    })
    assert any("not HTTPS" in warning for warning in summary.warnings)
    assert any("contains credentials" in warning for warning in summary.warnings)



def test_public_apis_parser_accepts_current_2026_header_shape():
    current = """
## Index

### Transportation
API | Description | Auth | HTTPS | CORS |
|:---|:---|:---|:---|:---|
| [ADS-B Exchange](https://www.adsbexchange.com/data/) | Aircraft tracking | No | Yes | Unknown |

### Currency Exchange
API | Description | Auth | HTTPS | CORS |
|:---|:---|:---|:---|:---|
| [Currency Demo](https://currency.example.test/) | Currency exchange rates | No | Yes | Yes |
"""
    rows = parse_public_apis_markdown(current)
    assert [row.category for row in rows] == ["Transportation", "Currency Exchange"]
    assert rows[1].name == "Currency Demo"
