"""STAR Roblox Intelligence Hub — fixed-host public catalogs + opt-in creator analytics.

No Roblox cookies, browser session, arbitrary URLs, secret logging, game editing,
player DataStore entry access, or fabricated gameplay observations. The user's
own Creator Hub API key must already be configured with universe.analytics:read
and STAR_ROBLOX_ANALYTICS_UNIVERSES must name exactly the allowed universes.
Analytics requests are *aggregated metrics*, not individual player records.

Roblox sources (2026-10): create.roblox.com/docs/cloud/guides/analytics,
cloud/guides/analytics/metrics, projects/assets/api, and
cloud/reference/features/creator-store. Live API behavior requires real consented
integration testing on the user's Roblox account.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
import re
from typing import Any, Callable

from . import roblox_cloud

ANALYTICS_DOCS = "https://create.roblox.com/docs/cloud/guides/analytics"
METRICS_DOCS = "https://create.roblox.com/docs/cloud/guides/analytics/metrics"
CATALOG_DOCS = "https://create.roblox.com/docs/projects/assets/api"
STORE_DOCS = "https://create.roblox.com/docs/cloud/reference/features/creator-store"
BASE = "https://apis.roblox.com"
MARKET = "https://catalog.roblox.com"
MAX_BODY_BYTES = 240_000
_ALLOWED_CATEGORIES = frozenset({1, 2, 3, 4, 5, 11, 12, 13})
_CREATOR_TYPES = frozenset({"Audio", "Model", "Decal", "Plugin", "MeshPart", "Video", "FontFamily"})
# Explicit, documented metric+granularity combinations; never let a model
# supply an arbitrary metric name, filter expression or optional breakdown.
_METRICS: dict[str, frozenset[str]] = {
    "DailyActiveUsers": frozenset({"None", "OneDay", "OneWeek", "OneMonth"}),
    "MonthlyActiveUsers": frozenset({"OneDay"}),
    "Visits": frozenset({"None", "OneDay", "OneWeek", "OneMonth"}),
    "AveragePlayTimeMinutesPerDAU": frozenset({"None", "OneDay", "OneWeek", "OneMonth"}),
    "AverageSessionLengthMinutes": frozenset({"None", "OneDay", "OneWeek", "OneMonth"}),
    "ForwardD1Retention": frozenset({"OneDay"}),
    "ForwardD7Retention": frozenset({"OneDay"}),
    "ForwardD30Retention": frozenset({"OneDay"}),
    "DailyRevenue": frozenset({"None", "OneDay", "OneWeek", "OneMonth"}),
    "PayingUsersCVR": frozenset({"None", "OneDay", "OneWeek", "OneMonth"}),
}
# Dimensions here are a deliberately small subset shared across these groups;
# IsNewUser is unavailable on the forward-retention metrics.
_BREAKDOWNS = frozenset({"Country", "Platform", "OperatingSystem"})
_UTC_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OP = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ID = re.compile(r"^[1-9][0-9]{0,17}$")
_Q = re.compile(r"^[^\x00-\x1f\x7f]{1,100}$")


def _positive_id(value: object, label: str = "id") -> int:
    if type(value) not in (int, str) or not _ID.fullmatch(str(value)):
        raise ValueError(f"{label} must be a positive numeric Roblox identifier")
    return int(value)


def _query(value: object) -> str:
    if not isinstance(value, str) or not _Q.fullmatch(value.strip()):
        raise ValueError("Search needs 1-100 visible characters")
    return value.strip()


def _range(start_day: str, end_day: str) -> tuple[str, str]:
    if type(start_day) is not str or type(end_day) is not str or not (
            _UTC_DATE.fullmatch(start_day) and _UTC_DATE.fullmatch(end_day)):
        raise ValueError("Use YYYY-MM-DD UTC dates")
    try:
        start, end = date.fromisoformat(start_day), date.fromisoformat(end_day)
    except ValueError as exc:
        raise ValueError("Invalid calendar date") from exc
    days = (end - start).days
    if not 1 <= days <= 90:
        raise ValueError("Date window must be 1 to 90 days (exclusive end date)")
    return start.isoformat() + "T00:00:00Z", end.isoformat() + "T00:00:00Z"


def _allowed_universes(raw: str) -> frozenset[int]:
    if not raw:
        return frozenset()
    values = raw.split(",")
    if len(values) > 20 or any(not value.strip() for value in values):
        raise ValueError("Configure at most 20 explicit Roblox analytics universe IDs")
    return frozenset(_positive_id(item.strip(), "allowed universe") for item in values)


def _small(value: object, size: int = 150) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()[:size]


def _metric_response(body: dict, metric: str, universe_id: int) -> dict:
    """Normalize only bounded, aggregate time-series data; never raw records."""
    if body.get("error") is not None:
        error = body["error"]
        code = error.get("code") if isinstance(error, dict) else None
        raise ValueError(f"Roblox rejected the metrics query (code {str(code)[:12]})")
    if body.get("done") is False:
        return {"status": "pending", "universe_id": universe_id, "metric": metric,
                "operation_id": _operation_id(body.get("path"), universe_id),
                "note": "Roblox accepted the query. Poll this operation later; data has NOT arrived.",
                "source": ANALYTICS_DOCS}
    if body.get("done") is not True or not isinstance(body.get("response"), dict):
        raise ValueError("Roblox did not return a completed analytics operation")
    values = body["response"].get("values")
    if not isinstance(values, list):
        raise ValueError("Roblox analytics response has no validated series")
    series, truncated = [], len(values) > 12
    for row in values[:12]:
        if not isinstance(row, dict):
            continue
        points = row.get("dataPoints")
        if not isinstance(points, list):
            continue
        clean_points = []
        for point in points[:93]:
            if not isinstance(point, dict):
                continue
            val = point.get("value")
            when = point.get("time")
            if type(val) not in (float, int) or isinstance(val, bool) or not (
                    isinstance(when, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^\x00-\x1f]{1,36}", when)):
                continue
            clean_points.append({"time": when[:36], "value": val,
                                 "status": _small(point.get("status"), 30) or None})
        categories = []
        if isinstance(row.get("breakdowns"), list):
            for item in row["breakdowns"][:3]:
                if isinstance(item, dict):
                    categories.append({"dimension": _small(item.get("dimension"), 50),
                                       "value": _small(item.get("value"), 80)})
        series.append({"breakdowns": categories, "data_points": clean_points,
                       "truncated": len(points) > 93})
    return {"status": "complete", "metric": metric, "universe_id": universe_id,
            "series": series, "truncated": truncated,
            "data_kind": "private owner-authorized aggregate analytics (not public game statistics)",
            "source": ANALYTICS_DOCS, "metric_reference": METRICS_DOCS}


def _operation_id(path: object, universe_id: int) -> str:
    prefix = f"v1/universes/{universe_id}/operations/metrics/"
    if not isinstance(path, str) or not path.startswith(prefix):
        raise ValueError("Roblox operation path did not match the authorized universe")
    operation_id = path[len(prefix):]
    if not _OP.fullmatch(operation_id):
        raise ValueError("Roblox returned an invalid operation identifier")
    return operation_id


class RobloxIntelligenceHub:
    """Only approved fixed Roblox origins; readonly public requests, no secrets returned."""

    def __init__(self, *, client: Any = None, key_provider: Callable[[], str] | None = None,
                 analytics_universes: str | None = None):
        self.client = client
        self._owns_client = client is None
        self.key_provider = key_provider or (lambda: roblox_cloud.load_key()[0])
        self.allowed_universes = _allowed_universes(
            os.getenv("STAR_ROBLOX_ANALYTICS_UNIVERSES", "") if analytics_universes is None else analytics_universes)

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()
            self.client = None

    def status(self) -> dict:
        return {"read_only": True, "public_catalog": True, "public_asset_metadata": True,
                "creator_analytics_opt_in": bool(self.allowed_universes),
                "analytics_universe_count": len(self.allowed_universes),
                "analytics_metrics": sorted(_METRICS),
                "analytics_key_scope_needed": "universe.analytics:read",
                "player_data_entries": "not exposed",
                "gameplay_recordings": "not acquired",
                "note": "Public catalog is distinct from private creator analytics; configure scope and approved universes."}

    def _request(self, host: str, method: str, path: str, *, params=None, payload=None, key: str = "") -> dict:
        if host not in (BASE, MARKET) or method not in ("GET", "POST") or not path.startswith("/") or (
                "//" in path or ".." in path or "?" in path):
            raise ValueError("Unapproved Roblox endpoint")
        import httpx
        if self.client is None:
            self.client = httpx.Client(timeout=httpx.Timeout(8, connect=3),
                                       trust_env=False, follow_redirects=False,
                                       headers={"Accept": "application/json", "User-Agent": "STAR-Roblox-Hub/1.0"})
        headers = {"x-api-key": key} if key else {}
        try:
            response = self.client.request(method, host + path, params=params, json=payload,
                                           headers=headers, follow_redirects=False)
        except (httpx.RequestError, ValueError) as exc:
            raise ValueError(f"Roblox request failed ({type(exc).__name__}); no metrics verified") from None
        if response.status_code == 429:
            raise ValueError("Roblox rate-limited the request (429); retry later")
        if response.status_code in (401, 403):
            raise PermissionError("Roblox declined access (401/403); check API key, universe scope and permissions")
        if response.status_code not in (200, 202):
            raise ValueError(f"Roblox returned HTTP {response.status_code}; no data verified")
        if "application/json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Roblox returned unsupported content type")
        if len(response.content) > MAX_BODY_BYTES:
            raise ValueError("Roblox response is too large for STAR")
        try:
            data = response.json()
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Roblox sent invalid JSON") from None
        if not isinstance(data, dict):
            raise ValueError("Roblox response is not an object")
        return data

    def marketplace_search(self, query: str, *, category: int = 1, limit: int = 10) -> dict:
        query = _query(query)
        if type(category) is not int or category not in _ALLOWED_CATEGORIES:
            raise ValueError("Unknown Marketplace category")
        if type(limit) is not int or limit != 10:
            raise ValueError("Limited first-page Marketplace search only supports 10")
        body = self._request(MARKET, "GET", "/v1/search/items/details",
                             params={"Keyword": query, "Category": category, "Limit": 10})
        assets = body.get("data", [])
        if not isinstance(assets, list):
            raise ValueError("Invalid Marketplace results")
        results = []
        for item in assets[:10]:
            if not isinstance(item, dict):
                continue
            ident = item.get("id")
            if type(ident) is not int or ident <= 0:
                continue
            results.append({"asset_id": ident, "name": _small(item.get("name"), 140),
                            "creator": _small(item.get("creatorName"), 100),
                            "price_robux": item.get("price") if type(item.get("price")) is int else None,
                            "item_type": _small(item.get("itemType"), 25),
                            "url": f"https://www.roblox.com/catalog/{ident}"})
        return {"catalog": "avatar Marketplace", "query": query, "results": results,
                "count": len(results), "page": 1, "next_page_unchecked": bool(body.get("nextPageCursor")),
                "source": CATALOG_DOCS, "note": "Public listing metadata only; no ownership, downloads or purchases."}

    def creator_store_search(self, query: str, *, category: str = "Model") -> dict:
        """Beta Creator Store search. 2026 reference documents a POST endpoint.

        Roblox's older published toolbox OpenAPI used GET/query params. Keep
        compatibility status explicit, and fail on 4xx rather than silent fallback
        to undocumented cookie-protected endpoints.
        """
        query = _query(query)
        if type(category) is not str or category not in _CREATOR_TYPES:
            raise ValueError("Unknown Creator Store category")
        data = self._request(BASE, "POST", "/toolbox-service/v2/assets:search",
                             payload={"searchCategoryType": category, "query": query})
        items = data.get("data", data.get("results", data.get("assets", [])))
        if not isinstance(items, list):
            raise ValueError("Unrecognized Creator Store beta search result")
        results = []
        for item in items[:10]:
            if not isinstance(item, dict):
                continue
            ident = item.get("id", item.get("assetId"))
            if type(ident) not in (str, int) or not _ID.fullmatch(str(ident)):
                continue
            results.append({"asset_id": int(ident),
                            "name": _small(item.get("name", item.get("displayName")), 140),
                            "creator": _small(item.get("creatorName"), 100),
                            "url": f"https://create.roblox.com/store/asset/{int(ident)}"})
        return {"catalog": "Creator Store", "query": query, "asset_type": category,
                "results": results, "source": STORE_DOCS, "beta": True,
                "note": "Untrusted catalog metadata. Do not install scripts/plugins/models automatically."}

    def creator_asset(self, asset_id: int) -> dict:
        asset_id = _positive_id(asset_id, "asset_id")
        data = self._request(BASE, "GET", f"/toolbox-service/v2/assets/{asset_id}")
        # A public result can contain embedded code or claims. Only short display metadata crosses the boundary.
        return {"asset_id": asset_id, "name": _small(data.get("name", data.get("displayName")), 140),
                "description_excerpt": _small(data.get("description"), 400),
                "source": f"{BASE}/toolbox-service/v2/assets/{asset_id}",
                "data_kind": "untrusted public Creator Store metadata",
                "note": "Asset details are not permission to download or execute its contents."}

    def _analytics_key(self, universe_id: int) -> str:
        universe_id = _positive_id(universe_id, "universe_id")
        if universe_id not in self.allowed_universes:
            raise PermissionError("Universe not on STAR_ROBLOX_ANALYTICS_UNIVERSES owner-approved allowlist")
        key = self.key_provider()
        if not isinstance(key, str) or not key.strip():
            raise PermissionError("No authorized Roblox Open Cloud key configured")
        return key.strip()

    def analytics_metrics(self, universe_id: int, metric: str, start_day: str, end_day: str,
                          *, granularity: str = "OneDay", breakdown: str = "") -> dict:
        ident = _positive_id(universe_id, "universe_id")
        if type(metric) is not str or metric not in _METRICS:
            raise ValueError("Metric is not in STAR's documented allowlist")
        if type(granularity) is not str or granularity not in _METRICS[metric]:
            raise ValueError("Granularity is not supported for this metric")
        if type(breakdown) is not str or (breakdown and breakdown not in _BREAKDOWNS):
            raise ValueError("Unsupported analytics breakdown")
        start, end = _range(start_day, end_day)
        key = self._analytics_key(ident)
        payload = {"metric": metric, "granularity": granularity, "startTime": start, "endTime": end}
        if breakdown:
            payload["breakdown"] = [breakdown]
        response = self._request(BASE, "POST",
                                 f"/analytics-query-api/v1/universes/{ident}/metrics",
                                 payload=payload, key=key)
        return _metric_response(response, metric, ident)

    def analytics_poll(self, universe_id: int, operation_id: str, *, metric: str) -> dict:
        ident = _positive_id(universe_id, "universe_id")
        if type(metric) is not str or metric not in _METRICS:
            raise ValueError("Metric is not in STAR's documented allowlist")
        if type(operation_id) is not str or not _OP.fullmatch(operation_id):
            raise ValueError("Invalid analytics operation ID")
        key = self._analytics_key(ident)
        response = self._request(BASE, "GET",
                                 f"/analytics-query-api/v1/universes/{ident}/operations/metrics/{operation_id}",
                                 key=key)
        return _metric_response(response, metric, ident)

    @staticmethod
    def gameplay_plan() -> dict:
        """Evidence-safe game mechanics telemetry template, not a claim of play."""
        return {
            "tested": False, "installed": False, "events": [
                {"name": "MissionStarted", "category": "custom event"},
                {"name": "MissionCompletedDuration", "category": "custom event"},
                {"name": "LevelStart", "category": "progression"},
                {"name": "LevelFail", "category": "progression"},
                {"name": "LevelComplete", "category": "progression"},
            ],
            "reference": "https://create.roblox.com/docs/reference/engine/classes/AnalyticsService",
            "requirements": [
                "Only instrument an experience you own or administer, using server-side AnalyticsService APIs.",
                "Avoid user identifiers, raw chat, secrets, exact locations and other personal data in event fields.",
                "Observe native Studio playtests and authorized recordings before asserting real mechanics.",
            ],
            "note": "This is an instrumentation plan, NOT player statistics or watched gameplay.",
        }
