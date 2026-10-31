"""One account system: how another Metallic service (Metallic Control's Star-app door, the RC backend, tools) accepts
a Metallic account instead of keeping its own passwords or codes.

    link = AccountLink("https://accounts.lan:8475", fingerprint="AB:CD:...")
    who = link.verify(access_token, roles=("owner", "admin"))   # None, or {"sub", "name", "role", "minor", ...}

Standard library only (uses the online introspection endpoint, so sign-out and role changes apply at once and the
service needs no crypto package). Services that can do ES256 may verify offline with crypto.verify_jwt + the JWKS.
"""
from __future__ import annotations

from .client import AccountsClient, AccountsError


class AccountLink:
    def __init__(self, url: str, fingerprint: str | None = None, cafile: str | None = None, timeout: float = 5.0):
        self.client = AccountsClient(url, fingerprint=fingerprint, cafile=cafile, timeout=timeout,
                                     user_agent="Metallic-Service")

    def verify(self, token: str, roles: tuple[str, ...] | None = None) -> dict | None:
        """The token's live claims, or None (bad, expired, signed out, wrong role, or the server is unreachable)."""
        if not isinstance(token, str) or token.count(".") != 2 or len(token) > 4096:
            return None
        try:
            info = self.client.introspect(token)
        except AccountsError:
            return None
        if not info.get("active") or (roles and info.get("role") not in roles):
            return None
        return info
