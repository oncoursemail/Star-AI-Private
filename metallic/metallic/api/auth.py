"""Who is calling, and what may they do.

Three kinds of bearer credentials:
- Metallic sign-in token (the accounts JWT the launcher holds): first-party, every user scope; owner/admin also get
  keys:admin and webhooks:manage. Checked live with accounts' /v1/introspect (cached 60 s, never past expiry).
- Scoped token `mtk_<random>` from POST /v1/oauth/token: only its granted scopes, at most 15 minutes and never longer
  than the sign-in token it came from. It stores the sign-in token sealed (AES-GCM), so user calls are still forwarded
  to accounts as the player, and accounts' own checks (sign-out, blocks, minors' rules) still apply.
- Server key `msk_<id>_<secret>` for game servers and backends: per-key scopes, games list and rate limit. Only a
  SHA-256 digest of the secret is stored.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
import secrets
import threading

USER_SCOPES = ("profile:read", "profile:write", "friends:read", "friends:write", "presence:read", "presence:write",
               "invites:read", "invites:write")
ADMIN_SCOPES = ("keys:admin", "webhooks:manage")
KEY_SCOPES = ("servers:write", "players:read", "webhooks:manage")
MINOR_DELEGABLE = ("profile:read",)
GAMES = ("RC", "MC", "RB", "PX")
SCOPED_TTL = 900


class ApiError(Exception):
    def __init__(self, status: int, code: str, text: str, headers: dict | None = None, **extra):
        super().__init__(text)
        self.status, self.code, self.text, self.headers, self.extra = status, code, text, headers or {}, extra

    def body(self) -> dict:
        return {"ok": False, "error": self.code, "text": self.text, **self.extra}


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_id(prefix: str, n: int = 12) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return prefix + "".join(secrets.choice(alphabet) for _ in range(n))


class Sealer:
    """AES-256-GCM for secrets the service must read back (sealed sign-in tokens, webhook secrets)."""

    def __init__(self, key: bytes):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if len(key) != 32:
            raise ValueError("data key must be 32 bytes")
        self._aes = AESGCM(key)

    def seal(self, text: str, aad: str = "") -> str:
        nonce = os.urandom(12)
        return base64.b64encode(nonce + self._aes.encrypt(nonce, text.encode(), aad.encode())).decode()

    def open(self, blob: str, aad: str = "") -> str:
        raw = base64.b64decode(blob)
        return self._aes.decrypt(raw[:12], raw[12:], aad.encode()).decode()


@dataclass
class Principal:
    kind: str                       # "anonymous" | "user" | "key"
    id: str                         # account id, key id, or "ip:<addr>"
    scopes: frozenset = field(default_factory=frozenset)
    name: str | None = None
    role: str | None = None
    minor: bool = False
    upstream_token: str | None = None      # the sign-in token to forward to accounts (user principals)
    delegated: bool = False
    games: tuple = ()
    rate: int = 0                   # per minute (keys)

    @property
    def owner_ref(self) -> str:
        return f"{self.kind}:{self.id}"


class RateLimiter:
    """Token buckets keyed by string. allow() -> (ok, remaining, retry_after)."""

    def __init__(self, clock):
        self.clock, self._b, self._lock = clock, {}, threading.Lock()

    def allow(self, key: str, per_minute: float, burst: int) -> tuple[bool, int, float]:
        rate = per_minute / 60.0
        now = self.clock()
        with self._lock:
            tokens, last = self._b.get(key, (float(burst), now))
            tokens = min(float(burst), tokens + (now - last) * rate)
            if tokens < 1.0:
                self._b[key] = (tokens, now)
                return False, 0, round((1.0 - tokens) / rate, 1)
            self._b[key] = (tokens - 1.0, now)
            if len(self._b) > 20000:
                self._b = {k: v for k, v in self._b.items() if now - v[1] < 600}
            return True, int(tokens - 1.0), 0.0


class Auth:
    def __init__(self, store, accounts, sealer: Sealer | None, clock):
        self.s, self.accounts, self.sealer, self.clock = store, accounts, sealer, clock

    # ---------- resolving a bearer credential ----------
    def principal(self, header: str | None, ip: str) -> Principal:
        if not header:
            return Principal("anonymous", "ip:" + ip)
        if not header.startswith("Bearer ") or len(header) > 4200:
            raise ApiError(401, "unauthorized", "Send 'Authorization: Bearer <token>'.")
        token = header[7:].strip()
        if token.startswith("msk_"):
            return self._key(token)
        if token.startswith("mtk_"):
            return self._scoped(token)
        if token.count(".") == 2:
            return self._signin(token)
        raise ApiError(401, "unauthorized", "That token is not a Metallic token.")

    def _signin(self, token: str) -> Principal:
        info = self._introspect(token)
        scopes = set(USER_SCOPES)
        if info.get("role") in ("owner", "admin"):
            scopes |= set(ADMIN_SCOPES)
        return Principal("user", info["sub"], frozenset(scopes), info.get("name"), info.get("role"),
                         bool(info.get("minor")), token)

    def _introspect(self, token: str) -> dict:
        from .upstream import UpstreamError
        try:
            info = self.accounts.introspect(token, now=self.clock())
        except UpstreamError as exc:
            raise ApiError(502 if exc.status in (0, 502) else 401, exc.code, exc.text) from exc
        if not info.get("active"):
            raise ApiError(401, "unauthorized", "The sign-in has ended. Sign in again.")
        return info

    def _scoped(self, token: str) -> Principal:
        row = self.s.one("SELECT * FROM tokens WHERE digest=?", (digest(token),))
        if row is None or row["revoked"] or row["expires"] <= self.clock() or self.sealer is None:
            raise ApiError(401, "unauthorized", "That token has expired or was revoked.")
        upstream = self.sealer.open(row["sealed"], aad=row["digest"])
        return Principal("user", row["sub"], frozenset(row["scopes"].split()), row["name"], row["role"],
                         bool(row["minor"]), upstream, delegated=True)

    def _key(self, token: str) -> Principal:
        parts = token.split("_", 2)          # msk_<id>_<secret>; the secret itself may contain "_"
        if len(parts) != 3:
            raise ApiError(401, "unauthorized", "That server key is not valid.")
        row = self.s.one("SELECT * FROM keys WHERE id=?", ("key_" + parts[1],))
        if row is None or row["revoked"] or not hmac.compare_digest(row["digest"], digest(token)):
            raise ApiError(401, "unauthorized", "That server key is not valid or was revoked.")
        now = self.clock()
        if not row["last_used"] or now - row["last_used"] > 60:
            self.s.x("UPDATE keys SET last_used=? WHERE id=?", (now, row["id"]))
        return Principal("key", row["id"], frozenset(json.loads(row["scopes"])), row["name"],
                         games=tuple(json.loads(row["games"])), rate=row["rate"])

    # ---------- scope checks ----------
    @staticmethod
    def require(p: Principal, security: list[dict]) -> None:
        """security = the operation's alternatives from the document; [] = public."""
        if not security:
            return
        kinds = {"metallicUser": "user", "serverKey": "key"}
        if p.kind == "anonymous":
            raise ApiError(401, "unauthorized", "Sign in first.", {"WWW-Authenticate": 'Bearer realm="metallic"'})
        wrong_kind, missing = True, []
        for alt in security:
            for scheme, scopes in alt.items():
                if kinds[scheme] != p.kind:
                    continue
                wrong_kind = False
                lack = [s for s in scopes if s not in p.scopes]
                if not lack:
                    return
                missing = lack
        if wrong_kind:
            who = " or ".join(sorted({"a server key" if "serverKey" in a else "a Metallic sign-in" for a in security}))
            raise ApiError(403, "wrong_credential", f"This endpoint needs {who}.")
        scope = " ".join(missing)
        raise ApiError(403, "insufficient_scope", f"This token lacks the scope {scope}.",
                       {"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'}, scope=scope)

    # ---------- scoped tokens ----------
    def exchange(self, subject_token: str, scope: str, client: str | None, ip: str) -> dict:
        if self.sealer is None:
            raise ApiError(503, "unavailable", "Scoped tokens are switched off on this server.")
        if subject_token.startswith(("mtk_", "msk_")) or subject_token.count(".") != 2:
            raise ApiError(400, "invalid_request", "subject_token must be a Metallic sign-in token.")
        wanted = [s for s in scope.split() if s]
        unknown = [s for s in wanted if s not in USER_SCOPES + ADMIN_SCOPES + KEY_SCOPES]
        if unknown or not wanted:
            raise ApiError(400, "invalid_scope", f"Unknown scope: {' '.join(unknown) or '(none)'}.")
        not_user = [s for s in wanted if s not in USER_SCOPES]
        if not_user:
            raise ApiError(403, "invalid_scope", f"{' '.join(not_user)} cannot be given to a scoped token.")
        info = self._introspect(subject_token)
        if info.get("minor"):
            blocked = [s for s in wanted if s not in MINOR_DELEGABLE]
            if blocked:
                self.s.audit(self.clock(), "token_exchange", False, info["sub"], ip, reason="minor_scope")
                raise ApiError(403, "minor_privacy", "For players under 18, other apps may only read the profile "
                               f"(asked for {' '.join(blocked)}).")
        now = self.clock()
        expires = min(now + SCOPED_TTL, float(info.get("exp", now)))
        if expires - now < 30:
            raise ApiError(401, "unauthorized", "The sign-in token is about to expire. Refresh it first.")
        token = "mtk_" + secrets.token_urlsafe(32)
        d = digest(token)
        granted = " ".join(sorted(set(wanted)))
        self.s.x("INSERT INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                 (d, info["sub"], info.get("name"), info.get("role"), int(bool(info.get("minor"))), granted,
                  (client or "")[:64], self.sealer.seal(subject_token, aad=d), now, expires))
        self.s.x("DELETE FROM tokens WHERE expires<?", (now - 86400,))
        self.s.audit(now, "token_exchange", True, info["sub"], ip, scope=granted, client=(client or "")[:64])
        return {"access_token": token, "token_type": "Bearer", "expires_in": int(expires - now), "scope": granted,
                "issued_token_type": "urn:ietf:params:oauth:token-type:access_token"}

    def revoke(self, token: str, ip: str) -> dict:
        if token.startswith("mtk_"):
            n = self.s.x("UPDATE tokens SET revoked=? WHERE digest=? AND revoked IS NULL", (self.clock(), digest(token)))
            self.s.audit(self.clock(), "token_revoke", bool(n), None, ip)
        return {"ok": True}

    # ---------- server keys ----------
    def create_key(self, name: str, scopes: list[str], games: list[str] | None, rate: int | None,
                   created_by: str | None) -> dict:
        bad = [s for s in scopes if s not in KEY_SCOPES]
        if bad or not scopes:
            raise ApiError(400, "invalid_scope", f"Server keys can hold {', '.join(KEY_SCOPES)}.")
        games = sorted(set(games or GAMES))
        if any(g not in GAMES for g in games):
            raise ApiError(400, "bad_request", "Games are RC, MC, RB or PX.")
        kid = new_id("key_", 12)
        secret = f"msk_{kid[4:]}_{secrets.token_urlsafe(32)}"
        now = self.clock()
        self.s.x("INSERT INTO keys (id, name, digest, scopes, games, rate, created, created_by) VALUES (?,?,?,?,?,?,?,?)",
                 (kid, name, digest(secret), json.dumps(sorted(set(scopes))), json.dumps(games), int(rate or 120), now,
                  created_by))
        self.s.audit(now, "key_create", True, created_by, None, key=kid, scopes=sorted(set(scopes)))
        return {**self.key_row(self.s.one("SELECT * FROM keys WHERE id=?", (kid,))), "secret": secret}

    @staticmethod
    def key_row(r) -> dict:
        return {"id": r["id"], "name": r["name"], "scopes": json.loads(r["scopes"]), "games": json.loads(r["games"]),
                "rate_per_minute": r["rate"], "created": r["created"], "last_used": r["last_used"],
                "revoked": bool(r["revoked"])}

    def list_keys(self) -> list[dict]:
        return [self.key_row(r) for r in self.s.q("SELECT * FROM keys ORDER BY created DESC")]

    def revoke_key(self, kid: str, actor: str | None) -> dict:
        n = self.s.x("UPDATE keys SET revoked=? WHERE id=? AND revoked IS NULL", (self.clock(), kid))
        self.s.audit(self.clock(), "key_revoke", bool(n), actor, None, key=kid)
        if not n:
            raise ApiError(404, "not_found", "No active key with that id.")
        return {"ok": True}
