"""Metallic accounts client: standard library only, one file, so the launcher (and the Star app) can vendor it as is.

    c = AccountsClient("https://accounts.metallic.lan:8475", fingerprint="AB:CD:...", store=TokenStore(path))
    c.login("alex", password)              # raises AccountsError(code="otp_required") when 2FA is on
    c.friends(); c.set_presence("playing", game="RC"); c.invite("sam", "RC", "room-123"); c.news()

TLS: pass the server certificate's SHA-256 fingerprint (self-signed now) or a CA file (real certificate later).
Only the refresh token is kept on disk, encrypted with Windows DPAPI for the current user; the access token stays in
memory and is refreshed automatically when it expires.
"""
from __future__ import annotations

import ctypes
import hashlib
import http.client
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time
import urllib.parse

VERSION = "1"


class AccountsError(Exception):
    def __init__(self, status: int, code: str, text: str, extra: dict | None = None):
        super().__init__(text)
        self.status, self.code, self.text, self.extra = status, code, text, extra or {}

    def to_dict(self) -> dict:
        return {"ok": False, "status": self.status, "error": self.code, "text": self.text, **self.extra}


# ---------- refresh-token storage ----------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in, blob_out = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):   # UI_FORBIDDEN
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


class TokenStore:
    """Refresh token on disk, DPAPI-encrypted per Windows user. Elsewhere (tests, Linux) memory only."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.secure = sys.platform == "win32" and self.path is not None
        self._mem: str | None = None

    def load(self) -> str | None:
        if self.secure and self.path.is_file():
            try:
                return _dpapi(self.path.read_bytes(), False).decode()
            except (OSError, UnicodeDecodeError):
                return None
        return self._mem

    def save(self, token: str | None) -> None:
        self._mem = token
        if not self.secure:
            return
        if token is None:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(_dpapi(token.encode(), True))
        os.replace(tmp, self.path)


# ---------- client ----------

class AccountsClient:
    def __init__(self, base_url: str, fingerprint: str | None = None, cafile: str | None = None,
                 store: TokenStore | None = None, timeout: float = 8.0, user_agent: str = "Metallic-Launcher"):
        u = urllib.parse.urlsplit(base_url)
        if u.scheme not in ("https", "http"):
            raise ValueError("base_url must be https://host:port")
        self.scheme, self.host, self.port = u.scheme, u.hostname, u.port or (443 if u.scheme == "https" else 80)
        self.fingerprint = fingerprint.replace(":", "").lower() if fingerprint else None
        self.cafile, self.timeout, self.ua = cafile, timeout, f"{user_agent} accounts-client/{VERSION}"
        self.store = store or TokenStore()
        self.access: str | None = None
        self.access_exp = 0.0
        self.account: dict | None = None
        self._lock = threading.Lock()

    # transport
    def _conn(self) -> http.client.HTTPConnection:
        if self.scheme == "http":
            return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        if self.fingerprint:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE          # identity comes from the pinned fingerprint below
        else:
            ctx = ssl.create_default_context(cafile=self.cafile)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        conn = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=ctx)
        if self.fingerprint:
            conn.connect()
            der = conn.sock.getpeercert(binary_form=True)
            if hashlib.sha256(der).hexdigest() != self.fingerprint:
                conn.close()
                raise AccountsError(0, "bad_certificate", "The accounts server's certificate does not match. "
                                    "Not connecting.")
        return conn

    def _call(self, method: str, path: str, body: dict | None = None, auth: bool = False) -> dict:
        headers = {"User-Agent": self.ua, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = "Bearer " + self._access_token()
        try:
            conn = self._conn()
            try:
                conn.request(method, path, data, headers)
                resp = conn.getresponse()
                raw = resp.read()
            finally:
                conn.close()
        except AccountsError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise AccountsError(0, "unreachable", "Can't reach Metallic accounts from here.") from exc
        try:
            obj = json.loads(raw or b"{}")
        except ValueError:
            obj = {}
        if resp.status >= 400:
            extra = {k: v for k, v in obj.items() if k not in ("ok", "error", "text")}
            raise AccountsError(resp.status, obj.get("error", "error"), obj.get("text", "Something went wrong."),
                                extra)
        return obj

    def _authed(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            return self._call(method, path, body, auth=True)
        except AccountsError as e:
            if e.code != "signed_out":
                raise
            self.access = None                         # revoked or expired early: one refresh, one retry
            return self._call(method, path, body, auth=True)

    def _take(self, tokens: dict) -> dict:
        self.access = tokens["access_token"]
        self.access_exp = time.time() + tokens.get("expires_in", 900) - 30
        self.account = tokens.get("account")
        self.store.save(tokens["refresh_token"])
        return tokens

    def _access_token(self) -> str:
        with self._lock:
            if self.access and time.time() < self.access_exp:
                return self.access
            refresh = self.store.load()
            if not refresh:
                raise AccountsError(401, "signed_out", "Please sign in.")
            try:
                self._take(self._call("POST", "/v1/refresh", {"refresh_token": refresh}))
            except AccountsError as e:
                if e.status in (401, 403):
                    self.store.save(None)
                    self.access, self.account = None, None
                raise
            return self.access

    # session
    @property
    def signed_in(self) -> bool:
        return bool(self.access or self.store.load())

    def health(self) -> dict:
        return self._call("GET", "/health")

    def jwks(self) -> dict:
        return self._call("GET", "/.well-known/jwks.json")

    def register(self, username: str, password: str, age_band: str, display_name: str | None = None,
                 owner_code: str | None = None) -> dict:
        """Returns the account and its one-time recovery codes (show them once; they are not kept here)."""
        body = {"username": username, "password": password, "age_band": age_band,
                "display_name": display_name or username}
        if owner_code:
            body["owner_code"] = owner_code
        out = self._take(self._call("POST", "/v1/register", body))
        return {"account": out["account"], "recovery_codes": out["recovery_codes"]}

    def login(self, username: str, password: str, otp: str | None = None, recovery_code: str | None = None) -> dict:
        body = {"username": username, "password": password}
        if otp:
            body["otp"] = otp
        if recovery_code:
            body["recovery_code"] = recovery_code
        return self._take(self._call("POST", "/v1/login", body))["account"]

    def logout(self, everywhere: bool = False) -> None:
        try:
            if self.signed_in:
                self._authed("POST", "/v1/logout", {"everywhere": everywhere})
        except AccountsError:
            pass                                       # signing out locally always works
        finally:
            self.store.save(None)
            self.access, self.account = None, None

    def recover(self, username: str, recovery_code: str, new_password: str) -> dict:
        return self._call("POST", "/v1/recover", {"username": username, "recovery_code": recovery_code,
                                                  "new_password": new_password})

    def access_token(self) -> str:
        """For handing to another Metallic service (e.g. Metallic Control, the RC backend)."""
        return self._access_token()

    def introspect(self, token: str) -> dict:
        """For services: is this access token live right now? {active, sub, name, role, minor, sid, amr, exp}."""
        return self._call("POST", "/v1/introspect", {"token": token})

    # account
    def me(self) -> dict:
        self.account = self._authed("GET", "/v1/me")
        return self.account

    def set_privacy(self, **settings) -> dict:
        return self._authed("POST", "/v1/me/privacy", {"privacy": settings})

    def set_display_name(self, name: str) -> dict:
        return self._authed("POST", "/v1/me/profile", {"display_name": name})

    def change_password(self, old: str, new: str, otp: str | None = None) -> None:
        self._authed("POST", "/v1/me/password", {"old_password": old, "new_password": new, "otp": otp})

    def sessions(self) -> list[dict]:
        return self._authed("GET", "/v1/sessions")["sessions"]

    def totp_setup(self, password: str) -> dict:
        return self._authed("POST", "/v1/2fa/setup", {"password": password})

    def totp_confirm(self, code: str) -> dict:
        return self._authed("POST", "/v1/2fa/confirm", {"code": code})

    def totp_disable(self, password: str, otp: str) -> None:
        self._authed("POST", "/v1/2fa/disable", {"password": password, "otp": otp})

    def new_recovery_codes(self, password: str, otp: str | None = None) -> list[str]:
        return self._authed("POST", "/v1/recovery-codes", {"password": password, "otp": otp})["recovery_codes"]

    # social
    def friends(self) -> dict:
        return self._authed("GET", "/v1/friends")

    def friend(self, action: str, username: str) -> dict:
        if action not in ("request", "accept", "decline", "remove", "block", "unblock"):
            raise ValueError(action)
        return self._authed("POST", f"/v1/friends/{action}", {"username": username})

    def profile(self, username: str) -> dict:
        return self._authed("GET", "/v1/users/" + urllib.parse.quote(username))

    def set_presence(self, status: str, game: str | None = None, detail: str | None = None,
                     joinable: bool = False) -> dict:
        return self._authed("POST", "/v1/presence", {"status": status, "game": game, "detail": detail,
                                                     "joinable": joinable})

    def presence(self) -> list[dict]:
        return self._authed("GET", "/v1/presence")["friends"]

    def invite(self, username: str, game: str, target: str) -> dict:
        return self._authed("POST", "/v1/invites", {"to": username, "game": game, "target": target})

    def invites(self) -> dict:
        return self._authed("GET", "/v1/invites")

    def answer_invite(self, invite_id: str, accept: bool) -> dict:
        return self._authed("POST", f"/v1/invites/{invite_id}/{'accept' if accept else 'decline'}", {})

    def news(self, limit: int = 20, game: str | None = None) -> list[dict]:
        q = urllib.parse.urlencode({"limit": limit, **({"game": game} if game else {})})
        return self._call("GET", "/v1/news?" + q)["news"]

    def post_news(self, title: str, body: str, game: str | None = None, pinned: bool = False) -> dict:
        return self._authed("POST", "/v1/news", {"title": title, "body": body, "game": game, "pinned": pinned})

    # provider sign-in, linking, passkeys (the launcher drives the browser + loopback; see launcher/loopback.py)
    def _maybe_authed(self, path: str, body: dict) -> dict:
        out = self._authed("POST", path, body) if self.signed_in else self._call("POST", path, body)
        if "access_token" in out:
            self._take(out)
        return out

    def providers(self) -> dict:
        return self._call("GET", "/v1/providers")

    def oauth_start(self, provider: str, redirect_uri: str, code_challenge: str, intent: str = "login") -> dict:
        body = {"provider": provider, "redirect_uri": redirect_uri, "code_challenge": code_challenge, "intent": intent}
        return self._authed("POST", "/v1/oauth/start", body) if intent == "link" else             self._call("POST", "/v1/oauth/start", body)

    def oauth_finish(self, flow: str, state: str, code: str, code_verifier: str) -> dict:
        """-> tokens taken (signed in), {"needs_signup", "ticket", ...}, or {"linked": provider}."""
        return self._maybe_authed("/v1/oauth/finish", {"flow": flow, "state": state, "code": code,
                                                       "code_verifier": code_verifier})

    def steam_start(self, redirect_uri: str, intent: str = "login") -> dict:
        body = {"redirect_uri": redirect_uri, "intent": intent}
        return self._authed("POST", "/v1/steam/start", body) if intent == "link" else             self._call("POST", "/v1/steam/start", body)

    def steam_finish(self, flow: str, params: dict) -> dict:
        return self._maybe_authed("/v1/steam/finish", {"flow": flow, "params": params})

    def oauth_signup(self, ticket: str, username: str, age_band: str, display_name: str | None = None) -> dict:
        out = self._take(self._call("POST", "/v1/oauth/signup", {"ticket": ticket, "username": username,
                                                                  "age_band": age_band, "display_name": display_name}))
        return {"account": out["account"], "recovery_codes": out["recovery_codes"]}

    def login_ticket(self, ticket: str, otp: str | None = None, recovery_code: str | None = None) -> dict:
        return self._take(self._call("POST", "/v1/login/ticket", {"ticket": ticket, "otp": otp,
                                                                   "recovery_code": recovery_code}))["account"]

    def methods(self) -> dict:
        return self._authed("GET", "/v1/me/methods")

    def unlink(self, provider: str) -> dict:
        return self._authed("POST", "/v1/identities/unlink", {"provider": provider})

    def passkey_register_options(self) -> dict:
        return self._authed("POST", "/v1/passkeys/register/options", {})

    def passkey_register_finish(self, flow: str, credential: dict, name: str | None = None) -> dict:
        return self._authed("POST", "/v1/passkeys/register/finish", {"flow": flow, "credential": credential,
                                                                     "name": name})

    def passkey_login_options(self) -> dict:
        return self._call("POST", "/v1/passkeys/login/options", {})

    def passkey_login_finish(self, flow: str, credential: dict) -> dict:
        return self._take(self._call("POST", "/v1/passkeys/login/finish", {"flow": flow,
                                                                            "credential": credential}))["account"]

    def passkey_remove(self, key_id: str) -> dict:
        return self._authed("POST", "/v1/passkeys/remove", {"id": key_id})
