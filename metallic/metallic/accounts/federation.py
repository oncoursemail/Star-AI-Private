"""Sign in with Google, Microsoft, Discord, GitHub, GitLab (OAuth 2.0 / OIDC + PKCE), Steam (OpenID 2.0) and passkeys,
plus account linking.

Desktop flow (RFC 8252): the launcher opens the system browser with a loopback redirect (http://127.0.0.1:47615/
callback). The server keeps every check: it creates the flow (state, nonce, the launcher's PKCE challenge), and on
finish it requires the same state, a code_verifier that hashes to the challenge, a one-time unexpired flow, then does
the code exchange itself (client secrets live only in server config) and verifies the ID token (issuer, audience,
expiry, nonce). Steam assertions are checked field by field and then confirmed with Steam (check_authentication).

Linking rules (account-takeover safe):
  - a provider identity belongs to at most one Metallic account;
  - first sign-in with an unknown identity links to an existing account ONLY when the provider vouches for the email
    (verified flag) and exactly one account already has that same verified email from another provider; Microsoft
    emails are never trusted for this (the "nOAuth" problem); otherwise the person picks a new username;
  - an explicit link needs a signed-in session; an identity linked elsewhere is refused (and audited);
  - unlinking or removing a passkey needs another sign-in method left (password, provider or passkey);
  - accounts with two-step sign-in still need the TOTP code after a provider sign-in (passkeys with user verification
    count as two factors).
"""
from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from . import crypto, webauthn
from .service import AGE_BANDS, Refused

FLOW_TTL = 10 * 60
TICKET_TTL = 15 * 60
LOOPBACK_RE = re.compile(r"^http://(127\.0\.0\.1|localhost):([0-9]{2,5})/callback$")
CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
STEAM_OP = "https://steamcommunity.com/openid/login"
STEAM_ID_RE = re.compile(r"^https://steamcommunity\.com/openid/id/([0-9]{17})$")
OPENID_NS = "http://specs.openid.net/auth/2.0"

PROVIDERS = {
    "google": {"name": "Google", "oidc": True, "trust_email": True, "scope": "openid email profile",
               "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
               "token": "https://oauth2.googleapis.com/token",
               "jwks": "https://www.googleapis.com/oauth2/v3/certs",
               "issuers": ("https://accounts.google.com", "accounts.google.com"), "extra": {"prompt": "select_account"}},
    "microsoft": {"name": "Microsoft", "oidc": True, "trust_email": False, "scope": "openid email profile",
                  "authorize": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                  "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                  "jwks": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
                  "issuers": ("https://login.microsoftonline.com/{tid}/v2.0",), "extra": {"prompt": "select_account"}},
    "gitlab": {"name": "GitLab", "oidc": True, "trust_email": True, "scope": "openid email profile",
               "authorize": "{base}/oauth/authorize", "token": "{base}/oauth/token",
               "jwks": "{base}/oauth/discovery/keys", "issuers": ("{base}",), "extra": {}},
    "discord": {"name": "Discord", "oidc": False, "trust_email": True, "scope": "identify email",
                "authorize": "https://discord.com/oauth2/authorize", "token": "https://discord.com/api/oauth2/token",
                "user": "https://discord.com/api/users/@me", "extra": {"prompt": "consent"}},
    "github": {"name": "GitHub", "oidc": False, "trust_email": True, "scope": "read:user user:email",
               "authorize": "https://github.com/login/oauth/authorize",
               "token": "https://github.com/login/oauth/access_token",
               "user": "https://api.github.com/user", "emails": "https://api.github.com/user/emails", "extra": {}},
}


def default_http(method: str, url: str, headers: dict | None = None, body: bytes | None = None,
                 timeout: float = 10.0) -> tuple[int, bytes]:
    if not url.startswith("https://"):
        raise Refused(502, "provider_error", "Provider address must be https.")
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"User-Agent": "Metallic-Accounts/1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(1_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(100_000)
    except OSError as exc:
        raise Refused(502, "provider_unreachable", "The sign-in provider did not answer. Try again.") from exc


def pkce_challenge(verifier: str) -> str:
    return crypto.b64u(hashlib.sha256(verifier.encode("ascii")).digest())


def verify_rs256(token: str, jwks: dict) -> dict:
    try:
        h64, b64, s64 = token.split(".")
        head = json.loads(crypto.b64u_dec(h64))
        claims = json.loads(crypto.b64u_dec(b64))
        sig = crypto.b64u_dec(s64)
    except (ValueError, AttributeError) as exc:
        raise Refused(401, "bad_id_token", "The provider's answer could not be checked.") from exc
    if head.get("alg") != "RS256":
        raise Refused(401, "bad_id_token", "The provider's answer could not be checked.")
    jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == head.get("kid") and k.get("kty") == "RSA"), None)
    if jwk is None:
        raise Refused(401, "bad_id_token", "The provider's answer could not be checked.")
    key = rsa.RSAPublicNumbers(int.from_bytes(crypto.b64u_dec(jwk["e"]), "big"),
                               int.from_bytes(crypto.b64u_dec(jwk["n"]), "big")).public_key()
    try:
        key.verify(sig, (h64 + "." + b64).encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise Refused(401, "bad_id_token", "The provider's answer could not be checked.") from exc
    return claims


class Federation:
    def __init__(self, accounts, providers_conf: dict | None = None, http=default_http, clock=None,
                 rp_id: str = "localhost", origins: tuple[str, ...] = ("http://localhost:47615",)):
        self.a = accounts
        self.s = accounts.s
        self.http = http
        self.clock = clock or accounts.clock
        self.conf = {k: v for k, v in (providers_conf or {}).items() if k in PROVIDERS or k == "steam"}
        self.rp_id, self.origins = rp_id, tuple(origins)
        self._jwks: dict[str, tuple[float, dict]] = {}

    # ---------- shared ----------
    def enabled(self) -> dict:
        out = [{"id": k, "name": PROVIDERS[k]["name"]} for k in PROVIDERS if self.conf.get(k, {}).get("client_id")]
        if self.conf.get("steam", {}).get("enabled"):
            out.append({"id": "steam", "name": "Steam"})
        return {"providers": out, "passkeys": {"rp_id": self.rp_id}}

    def _new_flow(self, kind: str, **fields) -> dict:
        now = self.clock()
        flow = {"id": crypto.new_id("flow_", 16), "kind": kind, "created": now,
                "expires": now + (TICKET_TTL if kind in ("signup", "mfa") else FLOW_TTL), **fields}
        cols = ("id", "kind", "provider", "secret", "nonce", "challenge", "redirect", "account", "data", "created",
                "expires")
        self.s.x(f"INSERT INTO flows ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                 tuple(flow.get(c) for c in cols))
        return flow

    def _take_flow(self, flow_id, kind: str) -> dict:
        """Single use: the flow is spent by the first finish attempt, right or wrong."""
        if not isinstance(flow_id, str):
            raise Refused(400, "bad_flow", "That sign-in has expired. Start again.")
        now = self.clock()
        with self.s.tx():
            row = self.s.db.execute("SELECT * FROM flows WHERE id=? AND kind=?", (flow_id, kind)).fetchone()
            if row is None or row["used"] or row["expires"] < now:
                raise Refused(400, "bad_flow", "That sign-in has expired. Start again.")
            self.s.db.execute("UPDATE flows SET used=? WHERE id=?", (now, flow_id))
        self.s.x("DELETE FROM flows WHERE expires<?", (now - 86400,))
        return dict(row)

    def _endpoint(self, provider: str, key: str) -> str:
        base = self.conf.get(provider, {}).get("base_url", "https://gitlab.com").rstrip("/")
        return PROVIDERS[provider][key].replace("{base}", base)

    def _session_account(self, claims: dict | None) -> str | None:
        return claims["sub"] if claims else None

    # ---------- OAuth / OIDC ----------
    def oauth_start(self, provider, redirect_uri, code_challenge, intent: str = "login",
                    claims: dict | None = None) -> dict:
        conf = self.conf.get(provider) if provider in PROVIDERS else None
        if not conf or not conf.get("client_id"):
            raise Refused(404, "provider_off", "That sign-in option is not turned on.")
        if not isinstance(redirect_uri, str) or not LOOPBACK_RE.match(redirect_uri):
            raise Refused(400, "bad_redirect", "The app must use a loopback redirect (RFC 8252).")
        if not isinstance(code_challenge, str) or not CHALLENGE_RE.match(code_challenge):
            raise Refused(400, "bad_pkce", "A PKCE S256 code challenge is required.")
        if intent not in ("login", "link"):
            raise Refused(400, "bad_request", "Intent is login or link.")
        if intent == "link" and not claims:
            raise Refused(401, "signed_out", "Sign in first to link another account.")
        p = PROVIDERS[provider]
        flow = self._new_flow("oauth", provider=provider, secret=secrets.token_urlsafe(24),
                              nonce=secrets.token_urlsafe(24), challenge=code_challenge, redirect=redirect_uri,
                              account=self._session_account(claims) if intent == "link" else None,
                              data=json.dumps({"intent": intent}))
        q = {"response_type": "code", "client_id": conf["client_id"], "redirect_uri": redirect_uri,
             "scope": p["scope"], "state": flow["secret"], "code_challenge": code_challenge,
             "code_challenge_method": "S256", **p["extra"]}
        if p["oidc"]:
            q["nonce"] = flow["nonce"]
        return {"flow": flow["id"], "authorize_url": self._endpoint(provider, "authorize") + "?" +
                urllib.parse.urlencode(q), "state": flow["secret"]}

    def oauth_finish(self, flow_id, state, code, code_verifier, ip: str, claims: dict | None = None) -> dict:
        flow = self._take_flow(flow_id, "oauth")
        provider = flow["provider"]
        if not isinstance(state, str) or not hmac.compare_digest(state, flow["secret"]):
            self.s.audit("oauth", False, ip=ip, provider=provider, reason="state")
            raise Refused(400, "bad_state", "That sign-in did not match. Start again.")
        if not isinstance(code_verifier, str) or not 43 <= len(code_verifier) <= 128 or \
                not hmac.compare_digest(pkce_challenge(code_verifier), flow["challenge"]):
            self.s.audit("oauth", False, ip=ip, provider=provider, reason="pkce")
            raise Refused(400, "bad_pkce", "That sign-in did not match. Start again.")
        if not isinstance(code, str) or not 1 <= len(code) <= 2048:
            raise Refused(400, "bad_request", "The provider sent no code.")
        identity = self._exchange(provider, code, code_verifier, flow)
        return self._resolve(identity, json.loads(flow["data"])["intent"], flow["account"], claims, ip)

    def _exchange(self, provider: str, code: str, verifier: str, flow: dict) -> dict:
        conf, p = self.conf[provider], PROVIDERS[provider]
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": flow["redirect"],
                "client_id": conf["client_id"], "code_verifier": verifier}
        if conf.get("client_secret"):
            form["client_secret"] = conf["client_secret"]
        status, raw = self.http("POST", self._endpoint(provider, "token"),
                                {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                                urllib.parse.urlencode(form).encode())
        try:
            tok = json.loads(raw)
        except ValueError:
            tok = {}
        if status != 200 or "error" in tok:
            raise Refused(401, "provider_refused", f"{p['name']} did not accept the sign-in. Start again.")
        if p["oidc"]:
            return self._oidc_identity(provider, tok.get("id_token", ""), flow["nonce"])
        return self._profile_identity(provider, tok.get("access_token", ""))

    def _provider_jwks(self, provider: str, refresh: bool = False) -> dict:
        cached = self._jwks.get(provider)
        if cached and not refresh and self.clock() - cached[0] < 3600:
            return cached[1]
        status, raw = self.http("GET", self._endpoint(provider, "jwks"))
        if status != 200:
            raise Refused(502, "provider_error", "The provider's keys could not be loaded.")
        jwks = json.loads(raw)
        self._jwks[provider] = (self.clock(), jwks)
        return jwks

    def _oidc_identity(self, provider: str, id_token: str, nonce: str) -> dict:
        try:
            c = verify_rs256(id_token, self._provider_jwks(provider))
        except Refused:
            c = verify_rs256(id_token, self._provider_jwks(provider, refresh=True))    # key rotation
        conf, p, now = self.conf[provider], PROVIDERS[provider], self.clock()
        issuers = [i.replace("{base}", conf.get("base_url", "https://gitlab.com").rstrip("/"))
                   .replace("{tid}", str(c.get("tid", ""))) for i in p["issuers"]]
        aud = c.get("aud")
        if c.get("iss") not in issuers or conf["client_id"] not in (aud if isinstance(aud, list) else [aud]):
            raise Refused(401, "bad_id_token", "The provider's answer was not for Metallic.")
        if now > c.get("exp", 0) + 60 or c.get("iat", 0) > now + 300:
            raise Refused(401, "bad_id_token", "The provider's answer has expired. Start again.")
        if not c.get("nonce") or not hmac.compare_digest(str(c["nonce"]), nonce):
            raise Refused(401, "bad_nonce", "That sign-in did not match. Start again.")
        if not c.get("sub"):
            raise Refused(401, "bad_id_token", "The provider sent no account id.")
        verified = c.get("email_verified") in (True, "true")
        return {"provider": provider, "subject": str(c["sub"]), "email": c.get("email"),
                "email_verified": bool(verified and p["trust_email"]),
                "name": c.get("name") or c.get("preferred_username") or "",
                "hint": (c.get("preferred_username") or c.get("email") or c.get("name") or "").split("@")[0]}

    def _profile_identity(self, provider: str, access: str) -> dict:
        if not access:
            raise Refused(401, "provider_refused", "The provider sent no access.")
        auth = {"Authorization": "Bearer " + access, "Accept": "application/json"}
        status, raw = self.http("GET", PROVIDERS[provider]["user"], auth)
        if status != 200:
            raise Refused(502, "provider_error", "The provider's profile could not be read.")
        u = json.loads(raw)
        if provider == "discord":
            return {"provider": provider, "subject": str(u["id"]), "email": u.get("email"),
                    "email_verified": bool(u.get("verified") and u.get("email")), "name": u.get("global_name") or
                    u.get("username") or "", "hint": u.get("username") or ""}
        email, verified = None, False                      # github: only a primary, verified address counts
        status, raw = self.http("GET", PROVIDERS["github"]["emails"], auth)
        if status == 200:
            for e in json.loads(raw):
                if e.get("primary") and e.get("verified"):
                    email, verified = e.get("email"), True
        return {"provider": provider, "subject": str(u["id"]), "email": email, "email_verified": verified,
                "name": u.get("name") or u.get("login") or "", "hint": u.get("login") or ""}

    # ---------- Steam (OpenID 2.0) ----------
    def steam_start(self, redirect_uri, intent: str = "login", claims: dict | None = None) -> dict:
        if not self.conf.get("steam", {}).get("enabled"):
            raise Refused(404, "provider_off", "That sign-in option is not turned on.")
        if not isinstance(redirect_uri, str) or not LOOPBACK_RE.match(redirect_uri):
            raise Refused(400, "bad_redirect", "The app must use a loopback redirect (RFC 8252).")
        if intent == "link" and not claims:
            raise Refused(401, "signed_out", "Sign in first to link another account.")
        state = secrets.token_urlsafe(24)
        return_to = f"{redirect_uri}?state={state}"
        flow = self._new_flow("steam", provider="steam", secret=state, redirect=return_to,
                              account=self._session_account(claims) if intent == "link" else None,
                              data=json.dumps({"intent": intent}))
        realm = redirect_uri.rsplit("/", 1)[0] + "/"
        q = {"openid.ns": OPENID_NS, "openid.mode": "checkid_setup", "openid.return_to": return_to,
             "openid.realm": realm, "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
             "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select"}
        return {"flow": flow["id"], "authorize_url": STEAM_OP + "?" + urllib.parse.urlencode(q), "state": state}

    def steam_finish(self, flow_id, params, ip: str, claims: dict | None = None) -> dict:
        flow = self._take_flow(flow_id, "steam")
        p = {k: v for k, v in (params or {}).items() if isinstance(k, str) and isinstance(v, str)}

        def bad(reason: str):
            self.s.audit("steam", False, ip=ip, reason=reason)
            return Refused(401, "steam_refused", "Steam sign-in could not be checked. Start again.")
        if not hmac.compare_digest(p.get("state", ""), flow["secret"]):
            raise bad("state")
        if p.get("openid.ns") != OPENID_NS or p.get("openid.mode") != "id_res":
            raise bad("mode")
        if p.get("openid.op_endpoint") != STEAM_OP:
            raise bad("op_endpoint")
        if p.get("openid.return_to") != flow["redirect"]:
            raise bad("return_to")
        m = STEAM_ID_RE.match(p.get("openid.claimed_id", ""))
        if not m or p.get("openid.identity") != p.get("openid.claimed_id"):
            raise bad("claimed_id")
        signed = set(p.get("openid.signed", "").split(","))
        if not {"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce", "assoc_handle"} <= signed:
            raise bad("signed_fields")
        nonce = p.get("openid.response_nonce", "")
        try:
            issued = calendar.timegm(time.strptime(nonce[:20], "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            raise bad("nonce") from None
        now = self.clock()
        if abs(now - issued) > 300:
            raise bad("nonce_age")
        self.s.x("DELETE FROM used_nonces WHERE expires<?", (now,))
        if self.s.x("INSERT OR IGNORE INTO used_nonces VALUES (?,?)", ("steam:" + nonce, now + 900)) != 1:
            raise bad("nonce_replay")
        check = {k: v for k, v in p.items() if k.startswith("openid.")}
        check["openid.mode"] = "check_authentication"
        status, raw = self.http("POST", STEAM_OP, {"Content-Type": "application/x-www-form-urlencoded"},
                                urllib.parse.urlencode(check).encode())
        lines = dict(line.split(":", 1) for line in raw.decode("utf-8", "replace").splitlines() if ":" in line)
        if status != 200 or lines.get("is_valid", "").strip() != "true":
            raise bad("check_authentication")
        steam_id = m.group(1)
        name = self._steam_name(steam_id)
        identity = {"provider": "steam", "subject": steam_id, "email": None, "email_verified": False,
                    "name": name, "hint": name}
        return self._resolve(identity, json.loads(flow["data"])["intent"], flow["account"], claims, ip)

    def _steam_name(self, steam_id: str) -> str:
        key = self.conf.get("steam", {}).get("web_api_key")
        if not key:
            return ""
        try:
            status, raw = self.http("GET", "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?" +
                                    urllib.parse.urlencode({"key": key, "steamids": steam_id}))
            players = json.loads(raw).get("response", {}).get("players", []) if status == 200 else []
            return players[0].get("personaname", "") if players else ""
        except (Refused, ValueError):
            return ""

    # ---------- linking ----------
    def _resolve(self, ident: dict, intent: str, flow_account: str | None, claims: dict | None, ip: str) -> dict:
        now = self.clock()
        existing = self.s.one("SELECT * FROM identities WHERE provider=? AND subject=?",
                              (ident["provider"], ident["subject"]))
        if intent == "link":
            me = self._session_account(claims)
            if not me or me != flow_account:
                raise Refused(401, "signed_out", "Sign in again to link this account.")
            if existing and existing["account"] != me:
                self.s.audit("link", False, me, ip=ip, provider=ident["provider"], reason="linked_elsewhere")
                raise Refused(409, "linked_elsewhere", "That account is already linked to a different Metallic "
                                                       "account.")
            if not existing:
                self._insert_identity(me, ident)
            self.s.audit("link", True, me, ip=ip, provider=ident["provider"])
            return {"ok": True, "linked": ident["provider"]}
        if existing:
            self.s.x("UPDATE identities SET email=?, email_verified=?, name=?, last_used=? WHERE provider=? AND "
                     "subject=?", (ident["email"], int(ident["email_verified"]), ident["name"], now,
                                   ident["provider"], ident["subject"]))
            return self._sign_in(existing["account"], ["fed:" + ident["provider"]], ip)
        if ident["email_verified"] and ident.get("email"):
            matches = {r["account"] for r in self.s.q(
                "SELECT account FROM identities WHERE lower(email)=lower(?) AND email_verified=1", (ident["email"],))}
            if len(matches) == 1:
                account = matches.pop()
                self._insert_identity(account, ident)
                self.s.audit("link", True, account, ip=ip, provider=ident["provider"], reason="verified_email")
                return self._sign_in(account, ["fed:" + ident["provider"]], ip)
        ticket = self._new_flow("signup", provider=ident["provider"], data=json.dumps(ident))
        return {"ok": True, "needs_signup": True, "ticket": ticket["id"], "provider": ident["provider"],
                "suggested_username": re.sub(r"[^A-Za-z0-9_]", "", ident.get("hint") or "")[:20]}

    def _insert_identity(self, account: str, ident: dict) -> None:
        try:
            self.s.x("INSERT INTO identities VALUES (?,?,?,?,?,?,?,?)",
                     (ident["provider"], ident["subject"], account, ident.get("email"), int(ident["email_verified"]),
                      ident.get("name"), self.clock(), self.clock()))
        except Exception as exc:          # sqlite3.IntegrityError: linked a moment ago by someone else
            raise Refused(409, "linked_elsewhere", "That account is already linked.") from exc

    def _sign_in(self, account_id: str, amr: list[str], ip: str, client: str | None = None) -> dict:
        row = self.a._acct(account_id)
        if row is None or row["disabled"]:
            self.s.audit("login", False, account_id, ip=ip, amr=amr, reason="disabled")
            raise Refused(403, "disabled", "This account is turned off. Ask a Metallic admin for help.")
        self.a._locked(row)
        if row["totp_sealed"] and amr[0].startswith("fed:"):
            t = self._new_flow("mfa", account=account_id, data=json.dumps({"amr": amr}))
            raise Refused(401, "otp_required", "Enter the 6-digit code from your authenticator app.",
                          ticket=t["id"])
        self.s.audit("login", True, account_id, ip=ip, amr=amr)
        return self.a._issue(row, amr, client)

    def finish_mfa(self, ticket, otp, recovery_code, ip: str) -> dict:
        flow = self._take_flow(ticket, "mfa")
        row = self.a._acct(flow["account"])
        self.a._locked(row)
        amr = json.loads(flow["data"])["amr"]
        try:
            second = self.a._check_second_factor(row, otp, recovery_code, ip)
        except Refused as r:
            if r.code == "wrong_code":    # a fresh ticket so a typo does not restart the provider sign-in
                t = self._new_flow("mfa", account=row["id"], data=flow["data"])
                r.extra["ticket"] = t["id"]
            raise
        self.s.audit("login", True, row["id"], ip=ip, amr=amr + second[1:])
        return self.a._issue(row, amr + second[1:], None)

    def signup(self, ticket, username, age_band, display_name, ip: str) -> dict:
        flow = self._take_flow(ticket, "signup")
        ident = json.loads(flow["data"])
        if age_band not in AGE_BANDS:
            raise Refused(400, "bad_request", "Choose an age group.")
        out = self.a.register(username, None, display_name, age_band, ip, federated=True)
        self._insert_identity(out["account"]["id"], ident)
        self.s.audit("link", True, out["account"]["id"], ip=ip, provider=ident["provider"], reason="signup")
        out["account"] = self.a.me(out["account"]["id"])
        return out

    def methods(self, account_id: str) -> dict:
        row = self.a._acct(account_id)
        ids = [{"provider": r["provider"], "name": r["name"] or "", "created": r["created"]}
               for r in self.s.q("SELECT * FROM identities WHERE account=? ORDER BY created", (account_id,))]
        keys = [{"id": r["id"], "name": r["name"] or "Passkey", "created": r["created"], "last_used": r["last_used"]}
                for r in self.s.q("SELECT * FROM passkeys WHERE account=? ORDER BY created", (account_id,))]
        return {"password": bool(row["pw_hash"]), "identities": ids, "passkeys": keys}

    def _count_methods(self, account_id: str) -> int:
        m = self.methods(account_id)
        return int(m["password"]) + len(m["identities"]) + len(m["passkeys"])

    def unlink(self, claims: dict, provider, ip: str) -> dict:
        me = claims["sub"]
        if not self.s.one("SELECT 1 FROM identities WHERE account=? AND provider=?", (me, provider)):
            raise Refused(404, "not_found", "That account is not linked.")
        if self._count_methods(me) <= 1:
            raise Refused(409, "last_method", "Add a password, a passkey or another sign-in first, so you can "
                                              "still get in.")
        self.s.x("DELETE FROM identities WHERE account=? AND provider=?", (me, provider))
        self.s.audit("unlink", True, me, ip=ip, provider=provider)
        return {"ok": True, **self.methods(me)}

    # ---------- passkeys ----------
    def passkey_register_options(self, claims: dict) -> dict:
        row = self.a._acct(claims["sub"])
        challenge = crypto.b64u(secrets.token_bytes(32))
        flow = self._new_flow("pk_reg", account=row["id"], challenge=challenge)
        exclude = [{"type": "public-key", "id": r["id"]} for r in self.s.q("SELECT id FROM passkeys WHERE account=?",
                                                                           (row["id"],))]
        return {"flow": flow["id"], "publicKey": {
            "rp": {"id": self.rp_id, "name": "Metallic"},
            "user": {"id": crypto.b64u(row["id"].encode()), "name": row["username"], "displayName": row["display_name"]},
            "challenge": challenge, "timeout": 120000, "attestation": "none", "excludeCredentials": exclude,
            "pubKeyCredParams": [{"type": "public-key", "alg": a} for a in webauthn.ALGS],
            "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True,
                                       "userVerification": "required"}}}

    def passkey_register_finish(self, claims: dict, flow_id, credential, name, ip: str) -> dict:
        flow = self._take_flow(flow_id, "pk_reg")
        if flow["account"] != claims["sub"]:
            raise Refused(400, "bad_flow", "That passkey setup has expired. Start again.")
        try:
            cred = webauthn.verify_registration(credential or {}, flow["challenge"], self.rp_id, self.origins)
        except webauthn.WebAuthnError as e:
            self.s.audit("passkey_add", False, claims["sub"], ip=ip, reason=str(e))
            raise Refused(400, "passkey_refused", "That passkey could not be checked. Try again.") from e
        label = (name if isinstance(name, str) else "")[:40].strip() or "Passkey"
        try:
            self.s.x("INSERT INTO passkeys VALUES (?,?,?,?,?,?,?,NULL)",
                     (cred["id"], claims["sub"], cred["public_key"], cred["alg"], cred["sign_count"], label,
                      self.clock()))
        except Exception as exc:
            raise Refused(409, "passkey_exists", "That passkey is already registered.") from exc
        self.s.audit("passkey_add", True, claims["sub"], ip=ip)
        return {"ok": True, **self.methods(claims["sub"])}

    def passkey_login_options(self) -> dict:
        challenge = crypto.b64u(secrets.token_bytes(32))
        flow = self._new_flow("pk_login", challenge=challenge)
        return {"flow": flow["id"], "publicKey": {"challenge": challenge, "rpId": self.rp_id, "timeout": 120000,
                                                  "userVerification": "required", "allowCredentials": []}}

    def passkey_login_finish(self, flow_id, credential, ip: str) -> dict:
        flow = self._take_flow(flow_id, "pk_login")
        credential = credential or {}
        key = self.s.one("SELECT * FROM passkeys WHERE id=?", (str(credential.get("id", "")),))
        handle = (credential.get("response") or {}).get("userHandle")
        if key is None or (handle and crypto.b64u_dec(handle).decode("utf-8", "replace") != key["account"]):
            self.s.audit("login", False, ip=ip, reason="passkey_unknown")
            raise Refused(401, "passkey_refused", "That passkey is not registered with Metallic.")
        try:
            count = webauthn.verify_assertion(credential, flow["challenge"], self.rp_id, self.origins,
                                              key["public_key"], key["alg"], key["sign_count"])
        except webauthn.WebAuthnError as e:
            self.s.audit("login", False, key["account"], ip=ip, reason="passkey:" + str(e))
            raise Refused(401, "passkey_refused", "That passkey could not be checked. Try again.") from e
        self.s.x("UPDATE passkeys SET sign_count=?, last_used=? WHERE id=?", (count, self.clock(), key["id"]))
        return self._sign_in(key["account"], ["hwk", "uv"], ip)

    def passkey_remove(self, claims: dict, key_id, ip: str) -> dict:
        me = claims["sub"]
        if not self.s.one("SELECT 1 FROM passkeys WHERE id=? AND account=?", (key_id, me)):
            raise Refused(404, "not_found", "No such passkey.")
        if self._count_methods(me) <= 1:
            raise Refused(409, "last_method", "Add a password or another sign-in first, so you can still get in.")
        self.s.x("DELETE FROM passkeys WHERE id=? AND account=?", (key_id, me))
        self.s.audit("passkey_remove", True, me, ip=ip)
        return {"ok": True, **self.methods(me)}
