"""Calls into Metallic accounts (standard library only). TLS identity comes from the pinned SHA-256 certificate
fingerprint (self-signed now) or a CA file later, the same way the launcher's accounts client connects."""
from __future__ import annotations

import hashlib
import http.client
import json
import ssl
import time
import urllib.parse


class UpstreamError(Exception):
    def __init__(self, status: int, code: str, text: str, extra: dict | None = None):
        super().__init__(text)
        self.status, self.code, self.text, self.extra = status, code, text, extra or {}


class Accounts:
    def __init__(self, base_url: str, fingerprint: str | None = None, cafile: str | None = None, timeout: float = 6.0):
        u = urllib.parse.urlsplit(base_url)
        if u.scheme not in ("https", "http"):
            raise ValueError("accounts url must be https://host:port")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port or (443 if u.scheme == "https" else 80)
        self.fingerprint = fingerprint.replace(":", "").lower() if fingerprint else None
        self.cafile, self.timeout = cafile, timeout
        self._introspect_cache: dict[str, tuple[float, dict]] = {}

    def _conn(self) -> http.client.HTTPConnection:
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        if self.fingerprint:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE           # identity = pinned fingerprint, checked below
        else:
            ctx = ssl.create_default_context(cafile=self.cafile)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        if self.fingerprint:
            conn.connect()
            if hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest() != self.fingerprint:
                conn.close()
                raise UpstreamError(502, "upstream_certificate", "The accounts service certificate does not match.")
        return conn

    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
        headers = {"User-Agent": "Metallic-API/1", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            conn = self._conn()
            try:
                conn.request(method, path, data, headers)
                resp = conn.getresponse()
                raw = resp.read()
            finally:
                conn.close()
        except UpstreamError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise UpstreamError(502, "accounts_unreachable", "Metallic accounts cannot be reached right now.") from exc
        try:
            obj = json.loads(raw or b"{}")
        except ValueError:
            obj = {}
        if resp.status >= 400:
            extra = {k: v for k, v in obj.items() if k == "retry_after"}
            raise UpstreamError(resp.status, obj.get("error", "error"), obj.get("text", "Something went wrong."), extra)
        return obj

    def introspect(self, token: str, now: float | None = None, max_age: float = 60.0) -> dict:
        """Live claims {active, sub, name, role, minor, exp, ...}; cached up to `max_age` seconds (never past exp)."""
        now = time.time() if now is None else now
        key = hashlib.sha256(token.encode()).hexdigest()
        hit = self._introspect_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
        info = self.call("POST", "/v1/introspect", {"token": token})
        if info.get("active"):
            until = min(now + max_age, float(info.get("exp", now)))
            if len(self._introspect_cache) > 5000:
                self._introspect_cache = {k: v for k, v in self._introspect_cache.items() if v[0] > now}
            self._introspect_cache[key] = (until, info)
        return info

    def forget(self, token: str) -> None:
        self._introspect_cache.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def health(self) -> bool:
        try:
            return bool(self.call("GET", "/health").get("ok"))
        except UpstreamError:
            return False
