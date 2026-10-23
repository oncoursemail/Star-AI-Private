"""Opt-in, bounded Mobbin REST references; no agent wiring or learning ingestion.

Requires a Mobbin Team/Enterprise workspace API key. This is not the OAuth MCP
integration (which also supports Pro), and does not establish a live connection
until explicitly enabled and called. Reference content is untrusted, memory-only,
and excluded from training, indexing, and evaluation. Images are never fetched.

API contract: https://docs.mobbin.com/api-reference/screens/search-screens-with-natural-language
Usage terms: https://mobbin.com/terms
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
import threading
from urllib.parse import urlsplit
from uuid import UUID

import httpx

ENDPOINT = "https://api.mobbin.com/v1/screens/search"
MAX_RESPONSE_BYTES = 128 * 1024
_MESSAGES = {
    "disabled": "Mobbin references are disabled; explicit opt-in is required.",
    "missing_credentials": "An explicitly supplied Mobbin workspace API key is required.",
    "budget_exhausted": "The Mobbin query budget for this client has been exhausted.",
    "busy": "This Mobbin client already has a request in progress.",
    "unauthorized": "Mobbin rejected the credentials; no retry was made.",
    "forbidden": "Mobbin did not allow this request; no retry was made.",
    "rate_limited": "Mobbin rate-limited the request; no retry was made.",
    "http_error": "Mobbin returned an unsuccessful HTTP status; no retry was made.",
    "timeout": "The bounded Mobbin request timed out.",
    "network_error": "The Mobbin request could not be completed.",
    "response_too_large": "The Mobbin response exceeded the byte limit.",
    "invalid_response": "Mobbin returned an unexpected response format.",
}


class MobbinReferenceError(RuntimeError):
    """Safe errors never include request text, credentials or provider bodies."""

    def __init__(self, status: str, *, status_code: int | None = None,
                 retry_after: int | None = None):
        self.status = status
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(_MESSAGES[status])

    def as_dict(self) -> dict:
        return {"ok": False, "status": self.status, "message": str(self),
                "status_code": self.status_code, "retry_after": self.retry_after}


def _integer(value, lower: int, upper: int, label: str) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{label} must be an integer in {lower}..{upper}")
    return value


def _text(value, limit: int) -> bool:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)


def _url(value, *, source: bool = False) -> str:
    if not _text(value, 8192) or "\\" in value:
        raise MobbinReferenceError("invalid_response")
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == "https" and parts.hostname and not parts.username
                 and not parts.password and parts.port in (None, 443)
                 and not any(char.isspace() for char in value))
        if source:
            valid = valid and parts.hostname in ("mobbin.com", "www.mobbin.com")
    except ValueError:
        valid = False
    if not valid:
        raise MobbinReferenceError("invalid_response")
    return value


def _retry_after(value: str | None) -> int | None:
    if not value or len(value) > 128:
        return None
    if value.isascii() and value.isdigit():
        return int(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0, math.ceil((date - datetime.now(timezone.utc)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def _screens(data, limit: int, platform: str) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("screens"), list):
        raise MobbinReferenceError("invalid_response")
    if len(data["screens"]) > limit:
        raise MobbinReferenceError("invalid_response")
    result = []
    seen = set()
    for item in data["screens"]:
        if not isinstance(item, dict) or not _text(item.get("app_name"), 300):
            raise MobbinReferenceError("invalid_response")
        try:
            identifier = str(UUID(item["id"]))
        except (ValueError, TypeError, AttributeError, KeyError):
            raise MobbinReferenceError("invalid_response") from None
        if identifier in seen or item.get("platform") != platform:
            raise MobbinReferenceError("invalid_response")
        seen.add(identifier)
        screen = {"id": identifier, "app_name": item["app_name"], "platform": platform,
                  "mobbin_url": _url(item.get("mobbin_url"), source=True),
                  "image_url": _url(item.get("image_url"))}
        if "image" in item:
            image = item["image"]
            if not isinstance(image, dict) or not _text(image.get("url_expires_at"), 64):
                raise MobbinReferenceError("invalid_response")
            try:
                expires = datetime.fromisoformat(image["url_expires_at"].replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    raise ValueError
                width = _integer(image.get("width"), 1, 200000, "image width")
                height = _integer(image.get("height"), 1, 200000, "image height")
            except ValueError:
                raise MobbinReferenceError("invalid_response") from None
            screen["image"] = {"url": _url(image.get("url")),
                               "url_expires_at": image["url_expires_at"],
                               "width": width, "height": height}
        result.append(screen)
    return result


class MobbinReferenceClient:
    """One request at a time, a small lifetime budget, and no automatic retries.

    Authentication, permission, and rate-limit refusals latch this client closed.
    Reconnection requires an explicit new client after the cause is resolved.
    The optional transport exists for offline tests, not alternate service URLs.
    """

    def __init__(self, api_key: str | None = None, *, enabled: bool = False,
                 max_queries: int = 3, max_results: int = 8,
                 timeout_s: float = 15.0, max_response_bytes: int = MAX_RESPONSE_BYTES,
                 transport: httpx.AsyncBaseTransport | None = None):
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        if api_key is not None and (not isinstance(api_key, str) or not api_key
                or len(api_key) > 4096 or not api_key.isascii()
                or any(ord(char) <= 32 or ord(char) >= 127 for char in api_key)):
            raise ValueError("Mobbin API key has an invalid format")
        if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
                or not 0 < timeout_s <= 30):
            raise ValueError("timeout_s must be greater than 0 and at most 30 seconds")
        self.enabled = enabled
        self._api_key = api_key
        self._max_queries = _integer(max_queries, 1, 10, "max_queries")
        self._max_results = _integer(max_results, 1, 20, "max_results")
        self._byte_limit = _integer(max_response_bytes, 1024, 256 * 1024, "max_response_bytes")
        self._timeout = float(timeout_s)
        self._transport = transport
        self._queries = 0
        self._busy = False
        self._blocked: tuple[str, int, int | None] | None = None
        self._lock = threading.Lock()

    async def search_screens(self, query: str, *, platform: str = "web",
                             limit: int | None = None) -> dict:
        if not self.enabled:
            raise MobbinReferenceError("disabled")
        if not self._api_key:
            raise MobbinReferenceError("missing_credentials")
        if not _text(query, 500):
            raise ValueError("query must contain 1..500 UTF-8 characters without control characters")
        if platform not in ("ios", "web"):
            raise ValueError("platform must be ios or web")
        count = self._max_results if limit is None else _integer(limit, 1, self._max_results, "limit")
        with self._lock:
            if self._blocked:
                status, code, retry_after = self._blocked
                raise MobbinReferenceError(status, status_code=code, retry_after=retry_after)
            if self._busy:
                raise MobbinReferenceError("busy")
            if self._queries >= self._max_queries:
                raise MobbinReferenceError("budget_exhausted")
            self._queries += 1
            self._busy = True
        payload = {"query": query, "platform": platform, "mode": "standard",
                   "limit": count, "image_quality": "optimized", "exclude_screen_ids": []}
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(
                    transport=self._transport, trust_env=False, follow_redirects=False,
                    timeout=httpx.Timeout(self._timeout, connect=min(5.0, self._timeout)),
                ) as client:
                    async with client.stream("POST", ENDPOINT, json=payload, headers={
                        "Authorization": "Bearer " + self._api_key,
                        "Accept": "application/json", "Accept-Encoding": "identity",
                    }) as response:
                        if response.status_code != 200:
                            status = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(
                                response.status_code, "http_error")
                            retry_after = _retry_after(response.headers.get("Retry-After"))
                            if response.status_code in (401, 403, 429):
                                with self._lock:
                                    self._blocked = (status, response.status_code, retry_after)
                            raise MobbinReferenceError(status, status_code=response.status_code,
                                                       retry_after=retry_after)
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise MobbinReferenceError("invalid_response")
                        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                        if content_type != "application/json":
                            raise MobbinReferenceError("invalid_response")
                        length = response.headers.get("content-length")
                        if length:
                            if not length.isascii() or not length.isdigit():
                                raise MobbinReferenceError("invalid_response")
                            if len(length) > 10 or int(length) > self._byte_limit:
                                raise MobbinReferenceError("response_too_large")
                        body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            if len(body) + len(chunk) > self._byte_limit:
                                raise MobbinReferenceError("response_too_large")
                            body.extend(chunk)
            try:
                data = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeError, RecursionError):
                raise MobbinReferenceError("invalid_response") from None
            return {"ok": True, "provider": "mobbin", "transport": "rest",
                    "screens": _screens(data, count, platform), "untrusted": True,
                    "usage": "on_demand_design_reference", "retention": "memory_only",
                    "training_allowed": False, "indexing_allowed": False, "evaluation_allowed": False}
        except (TimeoutError, httpx.TimeoutException):
            raise MobbinReferenceError("timeout") from None
        except httpx.HTTPError:
            raise MobbinReferenceError("network_error") from None
        finally:
            with self._lock:
                self._busy = False


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid Mobbin command arguments")


def main(argv: list[str] | None = None) -> int:
    parser = _SafeArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--query", required=True)
    parser.add_argument("--platform", default="web", choices=("web", "ios"))
    parser.add_argument("--enabled", action="store_true", help="Explicitly allow a Mobbin REST request")
    try:
        args = parser.parse_args(argv)
        key = os.environ.get("STAR_MOBBIN_API_KEY") if args.enabled else None
        client = MobbinReferenceClient(key, enabled=args.enabled, max_queries=1)
        result = asyncio.run(client.search_screens(args.query, platform=args.platform))
    except MobbinReferenceError as error:
        print(json.dumps(error.as_dict()))
        return 1
    except ValueError:
        print(json.dumps({"ok": False, "status": "invalid_input",
                          "message": "The Mobbin request configuration is invalid."}))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
