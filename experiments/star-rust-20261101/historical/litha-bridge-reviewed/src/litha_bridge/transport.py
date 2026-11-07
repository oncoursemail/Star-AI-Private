"""A bounded JSON transport: no automatic retries or endpoint discovery."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from .config import BridgeConfig, ConfigError, validated_api_base


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class ProviderError(RuntimeError):
    """A provider did not return a usable response (no credentials included)."""


@dataclass(frozen=True)
class JSONTransport:
    url: str
    api_key: str = field(repr=False)
    name: str
    config: BridgeConfig

    @property
    def api_base(self) -> str:
        return validated_api_base(self.url, remote_enabled=self.config.remote_enabled, name=self.name)

    def request(self, method: str, route: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in {"GET", "POST"}:
            raise ConfigError("Only GET and POST are supported")
        if not route.startswith("/") or route.startswith("//") or ".." in route or "?" in route or "#" in route:
            raise ConfigError("Invalid route")
        url = self.api_base + route
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        # Never forward credentials via proxy or redirects, including localhost->remote.
        opener = build_opener(ProxyHandler({}), _RejectRedirects())
        try:
            with opener.open(req, timeout=self.config.timeout_seconds) as response:
                if response.status >= 300:
                    raise ProviderError(f"{self.name} returned HTTP {response.status}")
                # Reject unbounded response bodies, including the sentinel byte.
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ProviderError(f"{self.name} response too large")
        except HTTPError as exc:
            raise ProviderError(f"{self.name} returned HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"{self.name} unavailable or timed out") from None
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeError):
            raise ProviderError(f"{self.name} returned invalid JSON") from None
        if not isinstance(parsed, dict):
            raise ProviderError(f"{self.name} returned an unexpected JSON shape")
        return parsed
