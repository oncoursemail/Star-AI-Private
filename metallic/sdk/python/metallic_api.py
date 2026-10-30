"""Metallic API v1 client for Python (standard library only, one file).

    from metallic_api import MetallicAPI, verify_webhook
    api = MetallicAPI("https://metallic-api.local:8476", token=sign_in_token_or_server_key, fingerprint="AB:CD:...")
    api.list_games(); api.list_friends(); api.server_heartbeat({"game": "RC", "server_id": "eu-1", "players": 12})

Errors raise MetallicAPIError(status, code, text, retry_after). Server keys belong on servers only.
GENERATED from metallic/metallic/api/openapi.json by `python -m metallic.api.sdkgen`. Do not edit by hand.
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import ssl
import time
import urllib.parse

__version__ = "1.0.0"


class MetallicAPIError(Exception):
    def __init__(self, status: int, code: str, text: str, retry_after: float | None = None):
        super().__init__(f"{status} {code}: {text}")
        self.status, self.code, self.text, self.retry_after = status, code, text, retry_after


def verify_webhook(secret: str, signature_header: str, body: bytes, tolerance: int = 300, now: float | None = None) -> bool:
    """True when `Metallic-Signature` matches the raw body and is at most `tolerance` seconds old."""
    try:
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs((time.time() if now is None else now) - t) > tolerance:
        return False
    mac = hmac.new(secret.encode(), str(t).encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, parts.get("v1", ""))


class MetallicAPI:
    def __init__(self, base_url: str, token: str | None = None, *, fingerprint: str | None = None,
                 cafile: str | None = None, timeout: float = 10.0, user_agent: str = "metallic-api-python"):
        u = urllib.parse.urlsplit(base_url)
        if u.scheme not in ("https", "http"):
            raise ValueError("base_url must be http(s)://host:port")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port
        self.prefix = u.path.rstrip("/")
        self.token, self.timeout, self.user_agent = token, timeout, f"{user_agent}/{__version__}"
        self.fingerprint = fingerprint.replace(":", "").lower() if fingerprint else None
        self.cafile = cafile

    def _conn(self) -> http.client.HTTPConnection:
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        if self.fingerprint:
            ctx = ssl.create_default_context()
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # identity = pinned fingerprint below
        else:
            ctx = ssl.create_default_context(cafile=self.cafile)
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        if self.fingerprint:
            conn.connect()
            if hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest() != self.fingerprint:
                conn.close()
                raise MetallicAPIError(0, "bad_certificate", "The server certificate does not match the pinned one.")
        return conn

    def request(self, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
        q = {k: v for k, v in (query or {}).items() if v is not None}
        url = self.prefix + path + (("?" + urllib.parse.urlencode(q)) if q else "")
        headers = {"Accept": "application/json", "User-Agent": self.user_agent}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            conn = self._conn()
            try:
                conn.request(method, url, data, headers)
                resp = conn.getresponse()
                raw = resp.read()
            finally:
                conn.close()
        except (OSError, http.client.HTTPException) as exc:
            raise MetallicAPIError(0, "unreachable", f"Cannot reach the Metallic API ({type(exc).__name__}).") from exc
        try:
            obj = json.loads(raw) if raw else {}
        except ValueError:
            obj = {}
        if resp.status >= 400:
            ra = resp.getheader("Retry-After")
            raise MetallicAPIError(resp.status, obj.get("error", "error"), obj.get("text", "Request failed."),
                                   float(ra) if ra else None)
        return obj

    def health(self) -> dict:
        """Service health. Public."""
        return self.request("GET", "/health", None)

    def get_openapi(self) -> dict:
        """This document. Public."""
        return self.request("GET", "/v1/openapi.json", None)

    def list_scopes(self) -> dict:
        """Every scope and who may hold it. Public."""
        return self.request("GET", "/v1/scopes", None)

    def exchange_token(self, body: dict) -> dict:
        """Make a scoped token from a sign-in token. Public."""
        return self.request("POST", "/v1/oauth/token", body)

    def revoke_token(self, body: dict) -> dict:
        """Revoke a scoped token. Public."""
        return self.request("POST", "/v1/oauth/revoke", body)

    def get_me(self) -> dict:
        """Your profile. Needs sign-in [profile:read]."""
        return self.request("GET", "/v1/me", None)

    def update_me(self, body: dict) -> dict:
        """Change your display name. Needs sign-in [profile:write]."""
        return self.request("PATCH", "/v1/me", body)

    def list_friends(self) -> dict:
        """Friends and friend requests. Needs sign-in [friends:read]."""
        return self.request("GET", "/v1/friends", None)

    def send_friend_request(self, body: dict) -> dict:
        """Ask a player to be friends. Needs sign-in [friends:write]."""
        return self.request("POST", "/v1/friends/requests", body)

    def accept_friend_request(self, username) -> dict:
        """Accept a friend request (sends friend.added). Needs sign-in [friends:write]."""
        return self.request("POST", f"/v1/friends/requests/{urllib.parse.quote(str(username), safe='')}/accept", None)

    def decline_friend_request(self, username) -> dict:
        """Decline an incoming or cancel an outgoing request. Needs sign-in [friends:write]."""
        return self.request("POST", f"/v1/friends/requests/{urllib.parse.quote(str(username), safe='')}/decline", None)

    def remove_friend(self, username) -> dict:
        """Remove a friend. Needs sign-in [friends:write]."""
        return self.request("DELETE", f"/v1/friends/{urllib.parse.quote(str(username), safe='')}", None)

    def list_presence(self) -> dict:
        """What your friends are doing. Needs sign-in [presence:read]."""
        return self.request("GET", "/v1/presence", None)

    def set_presence(self, body: dict) -> dict:
        """Set your presence. Needs sign-in [presence:write]."""
        return self.request("PUT", "/v1/me/presence", body)

    def list_invites(self) -> dict:
        """Your open game invites. Needs sign-in [invites:read]."""
        return self.request("GET", "/v1/invites", None)

    def send_invite(self, body: dict) -> dict:
        """Invite a friend to a game. Needs sign-in [invites:write]."""
        return self.request("POST", "/v1/invites", body)

    def accept_invite(self, invite_id) -> dict:
        """Accept an invite. Needs sign-in [invites:write]."""
        return self.request("POST", f"/v1/invites/{urllib.parse.quote(str(invite_id), safe='')}/accept", None)

    def decline_invite(self, invite_id) -> dict:
        """Decline an invite. Needs sign-in [invites:write]."""
        return self.request("POST", f"/v1/invites/{urllib.parse.quote(str(invite_id), safe='')}/decline", None)

    def list_news(self, *, game=None, limit=None) -> dict:
        """News posts. Public."""
        return self.request("GET", "/v1/news", None, {"game": game, "limit": limit})

    def list_games(self) -> dict:
        """RC, MC, RB and PX status. Public."""
        return self.request("GET", "/v1/games", None)

    def get_game(self, game) -> dict:
        """One game's status. Public."""
        return self.request("GET", f"/v1/games/{urllib.parse.quote(str(game), safe='')}", None)

    def list_revivals(self) -> dict:
        """Every Rec Room revival: status and people online. Public."""
        return self.request("GET", "/v1/revivals", None)

    def get_revival(self, revival) -> dict:
        """One revival's status and people online. Public."""
        return self.request("GET", f"/v1/revivals/{urllib.parse.quote(str(revival), safe='')}", None)

    def list_releases(self) -> dict:
        """Release channels. Public."""
        return self.request("GET", "/v1/releases", None)

    def get_release(self, channel) -> dict:
        """A verified release channel. Public."""
        return self.request("GET", f"/v1/releases/{urllib.parse.quote(str(channel), safe='')}", None)

    def get_progress(self) -> dict:
        """PX progress (public view). Public."""
        return self.request("GET", "/v1/progress", None)

    def get_project_progress(self, project) -> dict:
        """One project's progress. Public."""
        return self.request("GET", f"/v1/progress/{urllib.parse.quote(str(project), safe='')}", None)

    def get_project_status(self) -> dict:
        """Litha and STAR status (read-only). Public."""
        return self.request("GET", "/v1/projects/status", None)

    def server_heartbeat(self, body: dict) -> dict:
        """Report a live game server. Needs server key [servers:write]."""
        return self.request("POST", "/v1/servers/heartbeat", body)

    def server_event(self, body: dict) -> dict:
        """Report a player joining or leaving (sends player.joined / player.left). Needs server key [servers:write]."""
        return self.request("POST", "/v1/servers/events", body)

    def verify_player(self, body: dict) -> dict:
        """Check a player's Metallic sign-in token. Needs server key [players:read]."""
        return self.request("POST", "/v1/players/verify", body)

    def list_webhooks(self) -> dict:
        """Your webhooks. Needs server key [webhooks:manage] or sign-in [webhooks:manage]."""
        return self.request("GET", "/v1/webhooks", None)

    def create_webhook(self, body: dict) -> dict:
        """Add a webhook (the secret is shown once). Needs server key [webhooks:manage] or sign-in [webhooks:manage]."""
        return self.request("POST", "/v1/webhooks", body)

    def delete_webhook(self, webhook_id) -> dict:
        """Delete a webhook. Needs server key [webhooks:manage] or sign-in [webhooks:manage]."""
        return self.request("DELETE", f"/v1/webhooks/{urllib.parse.quote(str(webhook_id), safe='')}", None)

    def list_deliveries(self, webhook_id, *, limit=None) -> dict:
        """Delivery log (newest first). Needs server key [webhooks:manage] or sign-in [webhooks:manage]."""
        return self.request("GET", f"/v1/webhooks/{urllib.parse.quote(str(webhook_id), safe='')}/deliveries", None, {"limit": limit})

    def ping_webhook(self, webhook_id) -> dict:
        """Send a signed `ping` event. Needs server key [webhooks:manage] or sign-in [webhooks:manage]."""
        return self.request("POST", f"/v1/webhooks/{urllib.parse.quote(str(webhook_id), safe='')}/ping", None)

    def list_keys(self) -> dict:
        """Server keys. Needs sign-in [keys:admin]."""
        return self.request("GET", "/v1/keys", None)

    def create_key(self, body: dict) -> dict:
        """Create a server key (the secret is shown once). Needs sign-in [keys:admin]."""
        return self.request("POST", "/v1/keys", body)

    def revoke_key(self, key_id) -> dict:
        """Revoke a server key. Needs sign-in [keys:admin]."""
        return self.request("DELETE", f"/v1/keys/{urllib.parse.quote(str(key_id), safe='')}", None)
