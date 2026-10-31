"""Provider sign-in (OIDC/OAuth + PKCE, Steam OpenID 2.0), passkeys (WebAuthn) and account linking, with fake
providers (signed ID tokens, fixtures) and a software authenticator that produces real WebAuthn test vectors."""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import secrets
import struct
import time
import urllib.parse

import pytest

pytest.importorskip("argon2")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa  # noqa: E402

from metallic.accounts import crypto  # noqa: E402
from metallic.accounts.federation import STEAM_OP, Federation, pkce_challenge  # noqa: E402
from metallic.accounts.service import Accounts, Refused  # noqa: E402
from metallic.accounts.store import Store  # noqa: E402

PW = "graphite-violet-crow-7"
LOOP = "http://127.0.0.1:47615/callback"
ORIGIN = "http://localhost:47615"
b64u = crypto.b64u


@pytest.fixture(autouse=True)
def cheap_hashing():
    saved = crypto._HASHER, crypto._DUMMY_HASH
    crypto.set_cost(1, 1024)
    yield
    crypto._HASHER, crypto._DUMMY_HASH = saved


class Clock:
    def __init__(self):
        self.t = float(int(time.time()))

    def __call__(self):
        return self.t


class FakeProviders:
    """Google/Microsoft/GitLab (OIDC, RS256 ID tokens), Discord, GitHub and Steam, answering like the real ones."""

    def __init__(self, clock):
        self.clock = clock
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        n = self.key.public_key().public_numbers()
        self.jwks = {"keys": [{"kty": "RSA", "kid": "k1", "alg": "RS256", "n": b64u(n.n.to_bytes(256, "big")),
                               "e": b64u(n.e.to_bytes(3, "big"))}]}
        self.next = {}            # provider -> profile for the next token exchange
        self.seen = []
        self.steam_valid = True

    def id_token(self, claims: dict) -> str:
        head = b64u(json.dumps({"alg": "RS256", "kid": "k1", "typ": "JWT"}).encode())
        body = b64u(json.dumps(claims).encode())
        sig = self.key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{head}.{body}.{b64u(sig)}"

    def __call__(self, method, url, headers=None, body=None, timeout=10.0):
        self.seen.append((method, url, body))
        form = dict(urllib.parse.parse_qsl(body.decode())) if body else {}
        if url in ("https://www.googleapis.com/oauth2/v3/certs", "https://gitlab.com/oauth/discovery/keys",
                   "https://login.microsoftonline.com/common/discovery/v2.0/keys"):
            return 200, json.dumps(self.jwks).encode()
        for prov, tok_url in (("google", "https://oauth2.googleapis.com/token"),
                              ("microsoft", "https://login.microsoftonline.com/common/oauth2/v2.0/token"),
                              ("gitlab", "https://gitlab.com/oauth/token")):
            if url == tok_url:
                p = self.next[prov]
                if form.get("code") != "good-code" or not form.get("code_verifier"):
                    return 400, b'{"error":"invalid_grant"}'
                return 200, json.dumps({"access_token": "at", "id_token": self.id_token(p)}).encode()
        if url in ("https://discord.com/api/oauth2/token", "https://github.com/login/oauth/access_token"):
            return (200, b'{"access_token":"at-x"}') if form.get("code") == "good-code" else (400, b'{"error":"x"}')
        if url == "https://discord.com/api/users/@me":
            return 200, json.dumps(self.next["discord"]).encode()
        if url == "https://api.github.com/user":
            return 200, json.dumps(self.next["github"]).encode()
        if url == "https://api.github.com/user/emails":
            return 200, json.dumps(self.next["github_emails"]).encode()
        if url == STEAM_OP and method == "POST":
            assert form["openid.mode"] == "check_authentication"
            return 200, b"ns:http://specs.openid.net/auth/2.0\nis_valid:" + (b"true" if self.steam_valid else b"false")
        return 404, b"{}"


CONF = {"google": {"client_id": "g-id.apps.googleusercontent.com", "client_secret": "g-secret"},
        "microsoft": {"client_id": "ms-id"}, "gitlab": {"client_id": "gl-id"},
        "discord": {"client_id": "dc-id", "client_secret": "dc-secret"},
        "github": {"client_id": "gh-id", "client_secret": "gh-secret"}, "steam": {"enabled": True}}


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    store = Store(":memory:", tmp_path / "audit.jsonl", clock=clock)
    acc = Accounts(store, crypto.Signer(crypto.new_signing_key_pem(), clock=clock), crypto.Sealer(os.urandom(32)),
                   clock=clock)
    fake = FakeProviders(clock)
    fed = Federation(acc, CONF, http=fake, clock=clock, rp_id="localhost", origins=(ORIGIN,))
    return acc, fed, fake, clock


def claims_of(acc, tokens):
    return acc.authenticate("Bearer " + tokens["access_token"])


def start(fed, provider="google", intent="login", claims=None):
    verifier = secrets.token_urlsafe(48)
    r = fed.oauth_start(provider, LOOP, pkce_challenge(verifier), intent, claims)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["authorize_url"]).query))
    return r, q, verifier


def google_profile(fake, clock, q, sub="g-123", email="sam@example.com", verified=True, **over):
    fake.next["google"] = {"iss": "https://accounts.google.com", "aud": CONF["google"]["client_id"], "sub": sub,
                           "email": email, "email_verified": verified, "name": "Sam", "iat": clock.t,
                           "exp": clock.t + 3600, "nonce": q.get("nonce"), **over}


def google_login(acc, fed, fake, clock, sub="g-123", email="sam@example.com", verified=True, intent="login",
                 claims=None, **over):
    r, q, v = start(fed, "google", intent, claims)
    google_profile(fake, clock, q, sub, email, verified, **over)
    return fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip", claims)


def signup(fed, result, name, band="adult"):
    assert result.get("needs_signup"), result
    return fed.signup(result["ticket"], name, band, None, "ip")


# ---------- OAuth / OIDC + PKCE ----------

def test_authorize_url_has_pkce_state_nonce_and_loopback(env):
    _, fed, _, _ = env
    r, q, v = start(fed)
    assert q["code_challenge"] == pkce_challenge(v) and q["code_challenge_method"] == "S256"
    assert q["redirect_uri"] == LOOP and q["state"] == r["state"] and len(q["nonce"]) >= 32
    assert q["client_id"] == CONF["google"]["client_id"] and "g-secret" not in r["authorize_url"]
    for bad in ("https://evil.example/callback", "http://127.0.0.1:47615/other", "http://203.0.113.5:47615/callback"):
        with pytest.raises(Refused) as e:
            fed.oauth_start("google", bad, pkce_challenge(v))
        assert e.value.code == "bad_redirect"
    with pytest.raises(Refused) as e:
        fed.oauth_start("google", LOOP, "plain-verifier")
    assert e.value.code == "bad_pkce"
    with pytest.raises(Refused):
        fed.oauth_start("myspace", LOOP, pkce_challenge(v))


def test_new_google_user_signs_up_then_signs_in(env):
    acc, fed, fake, clock = env
    out = signup(fed, google_login(acc, fed, fake, clock), "samgoogle")
    assert out["account"]["username"] == "samgoogle" and len(out["recovery_codes"]) == 10
    assert crypto.verify_jwt(out["access_token"], acc.signer.jwks, now=clock.t)["sub"] == out["account"]["id"]
    again = google_login(acc, fed, fake, clock)
    assert again["account"]["username"] == "samgoogle"
    assert crypto.verify_jwt(again["access_token"], acc.signer.jwks, now=clock.t)["amr"] == ["fed:google"]
    assert fed.methods(out["account"]["id"]) == {"password": False, "identities": [
        {"provider": "google", "name": "Sam", "created": clock.t}], "passkeys": []}
    with pytest.raises(Refused):
        acc.login("samgoogle", "", "ip")                  # no password on a provider-only account


def test_state_mismatch_wrong_verifier_and_flow_reuse_are_refused(env):
    acc, fed, fake, clock = env
    r, q, v = start(fed)
    google_profile(fake, clock, q)
    with pytest.raises(Refused) as e:
        fed.oauth_finish(r["flow"], "forged-state", "good-code", v, "ip")
    assert e.value.code == "bad_state"
    with pytest.raises(Refused) as e:                     # the flow is spent by the failed try
        fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip")
    assert e.value.code == "bad_flow"
    r, q, v = start(fed)
    google_profile(fake, clock, q)
    with pytest.raises(Refused) as e:
        fed.oauth_finish(r["flow"], q["state"], "good-code", secrets.token_urlsafe(48), "ip")
    assert e.value.code == "bad_pkce"
    r, q, v = start(fed)
    clock.t += 11 * 60
    with pytest.raises(Refused) as e:
        fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip")
    assert e.value.code == "bad_flow"
    events = [(x["event"], x["detail"].get("reason")) for x in acc.s.audit_rows()]
    assert ("oauth", "state") in events and ("oauth", "pkce") in events


@pytest.mark.parametrize("over,code", [({"nonce": "replayed-nonce"}, "bad_nonce"), ({"aud": "someone-else"}, "bad_id_token"),
                                       ({"iss": "https://evil.example"}, "bad_id_token"),
                                       ({"exp": 1_000_000}, "bad_id_token")])
def test_id_token_checks(env, over, code):
    acc, fed, fake, clock = env
    with pytest.raises(Refused) as e:
        google_login(acc, fed, fake, clock, **over)
    assert e.value.code == code


def test_forged_id_token_signature_is_refused(env):
    acc, fed, fake, clock = env
    r, q, v = start(fed)
    google_profile(fake, clock, q)
    real_key = fake.key
    fake.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)     # attacker signs, JWKS unchanged
    with pytest.raises(Refused) as e:
        fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip")
    assert e.value.code == "bad_id_token"
    fake.key = real_key


def test_provider_rejecting_the_code(env):
    acc, fed, fake, clock = env
    r, q, v = start(fed)
    google_profile(fake, clock, q)
    with pytest.raises(Refused) as e:
        fed.oauth_finish(r["flow"], q["state"], "stolen-code", v, "ip")
    assert e.value.code == "provider_refused"


def test_microsoft_issuer_with_tenant_and_github_discord_profiles(env):
    acc, fed, fake, clock = env
    r, q, v = start(fed, "microsoft")
    tid = "9188040d-6c67-4c5b-b112-36a304b66dad"
    fake.next["microsoft"] = {"iss": f"https://login.microsoftonline.com/{tid}/v2.0", "tid": tid, "aud": "ms-id",
                              "sub": "ms-1", "email": "x@example.com", "email_verified": True, "iat": clock.t,
                              "exp": clock.t + 600, "nonce": q["nonce"], "preferred_username": "x@example.com"}
    res = fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip")
    assert res["needs_signup"] and res["suggested_username"] == "x"
    r, q, v = start(fed, "github")
    fake.next["github"] = {"id": 42, "login": "octo", "name": "Octo"}
    fake.next["github_emails"] = [{"email": "old@example.com", "primary": False, "verified": True},
                                  {"email": "octo@example.com", "primary": True, "verified": True}]
    res = fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip")
    assert res["suggested_username"] == "octo"
    signup(fed, res, "octo")
    row = acc.s.one("SELECT * FROM identities WHERE provider='github'")
    assert row["subject"] == "42" and row["email"] == "octo@example.com" and row["email_verified"] == 1
    r, q, v = start(fed, "discord")
    fake.next["discord"] = {"id": "8001", "username": "dcuser", "email": "d@example.com", "verified": False}
    res = fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip")
    signup(fed, res, "dcuser")
    assert acc.s.one("SELECT email_verified FROM identities WHERE provider='discord'")["email_verified"] == 0
    secrets_sent = [b for (_, u, b) in fake.seen if b and b"client_secret" in b]
    assert secrets_sent and all(b"code_verifier" in b for b in secrets_sent)


# ---------- linking and takeover attempts ----------

def test_verified_email_links_to_the_one_matching_account(env):
    acc, fed, fake, clock = env
    first = signup(fed, google_login(acc, fed, fake, clock, email="Sam@Example.com"), "samlink")
    r, q, v = start(fed, "github")
    fake.next["github"] = {"id": 7, "login": "samgh"}
    fake.next["github_emails"] = [{"email": "sam@example.com", "primary": True, "verified": True}]
    res = fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip")
    assert res["account"]["id"] == first["account"]["id"]               # linked by verified email
    assert {i["provider"] for i in fed.methods(first["account"]["id"])["identities"]} == {"google", "github"}


def test_unverified_email_never_links(env):
    acc, fed, fake, clock = env
    signup(fed, google_login(acc, fed, fake, clock, email="victim@example.com"), "victim")
    r, q, v = start(fed, "discord")
    fake.next["discord"] = {"id": "666", "username": "attacker", "email": "victim@example.com", "verified": False}
    res = fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip")
    assert res.get("needs_signup") is True and "account" not in res
    res = google_login(acc, fed, fake, clock, sub="g-attacker", email="victim@example.com", verified=False)
    assert res.get("needs_signup") is True


def test_microsoft_email_is_never_trusted_for_linking(env):
    acc, fed, fake, clock = env
    signup(fed, google_login(acc, fed, fake, clock, email="boss@example.com"), "bossg")
    r, q, v = start(fed, "microsoft")
    tid = "t-1"
    fake.next["microsoft"] = {"iss": f"https://login.microsoftonline.com/{tid}/v2.0", "tid": tid, "aud": "ms-id",
                              "sub": "ms-evil", "email": "boss@example.com", "email_verified": True,
                              "iat": clock.t, "exp": clock.t + 600, "nonce": q["nonce"]}
    assert fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip").get("needs_signup") is True


def test_ambiguous_verified_email_does_not_link(env):
    acc, fed, fake, clock = env
    signup(fed, google_login(acc, fed, fake, clock, sub="g-a", email="shared@example.com"), "shareda")
    other = acc.register("sharedc", PW, None, "adult", "ip")       # a second account with the same verified email
    link = google_login(acc, fed, fake, clock, sub="g-c", email="shared@example.com", intent="link",
                        claims=claims_of(acc, other))
    assert link == {"ok": True, "linked": "google"}
    r, q, v = start(fed, "github")
    fake.next["github"] = {"id": 99, "login": "who"}
    fake.next["github_emails"] = [{"email": "shared@example.com", "primary": True, "verified": True}]
    assert fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip").get("needs_signup") is True


def test_explicit_link_needs_session_and_cannot_steal_a_linked_identity(env):
    acc, fed, fake, clock = env
    owner = signup(fed, google_login(acc, fed, fake, clock, sub="g-owner", email="o@example.com"), "realowner")
    attacker = acc.register("attacker1", PW, None, "adult", "ip")
    v = secrets.token_urlsafe(48)
    with pytest.raises(Refused) as e:
        fed.oauth_start("google", LOOP, pkce_challenge(v), "link", None)
    assert e.value.code == "signed_out"
    with pytest.raises(Refused) as e:
        google_login(acc, fed, fake, clock, sub="g-owner", email="o@example.com", intent="link",
                     claims=claims_of(acc, attacker))
    assert e.value.code == "linked_elsewhere"
    assert acc.s.one("SELECT account FROM identities WHERE subject='g-owner'")["account"] == owner["account"]["id"]
    assert any(r["event"] == "link" and r["detail"].get("reason") == "linked_elsewhere" for r in acc.s.audit_rows())
    # a link flow started by one session cannot be finished by another
    other = acc.register("other2", PW, None, "adult", "ip")
    r, q, v = start(fed, "google", "link", claims_of(acc, attacker))
    google_profile(fake, clock, q, sub="g-new")
    with pytest.raises(Refused):
        fed.oauth_finish(r["flow"], q["state"], "good-code", v, "ip", claims_of(acc, other))


def test_unlink_keeps_at_least_one_method(env):
    acc, fed, fake, clock = env
    out = signup(fed, google_login(acc, fed, fake, clock), "onlygoogle")
    c = claims_of(acc, out)
    with pytest.raises(Refused) as e:
        fed.unlink(c, "google", "ip")
    assert e.value.code == "last_method"
    acc.change_password(c, None, "a-brand-new-password", None, "ip")    # first password on a provider account
    assert fed.unlink(c, "google", "ip")["identities"] == []
    assert acc.login("onlygoogle", "a-brand-new-password", "ip")


def test_provider_sign_in_still_needs_totp(env):
    acc, fed, fake, clock = env
    out = signup(fed, google_login(acc, fed, fake, clock), "totpfed")
    c = claims_of(acc, out)
    acc.change_password(c, None, "pass-for-setup-123", None, "ip")
    s = acc.totp_setup(c, "pass-for-setup-123", "ip")
    acc.totp_confirm(c, crypto.totp_code(s["secret"], int(clock.t // 30)), "ip")
    with pytest.raises(Refused) as e:
        google_login(acc, fed, fake, clock)
    assert e.value.code == "otp_required" and e.value.extra["ticket"]
    ticket = e.value.extra["ticket"]
    with pytest.raises(Refused) as e2:
        fed.finish_mfa(ticket, "000000", None, "ip")
    clock.t += 30
    t = fed.finish_mfa(e2.value.extra["ticket"], crypto.totp_code(s["secret"], int(clock.t // 30)), None, "ip")
    assert crypto.verify_jwt(t["access_token"], acc.signer.jwks, now=clock.t)["amr"] == ["fed:google", "otp"]
    with pytest.raises(Refused):
        fed.finish_mfa(ticket, "123456", None, "ip")                     # tickets are single use


def test_disabled_account_cannot_sign_in_with_provider(env):
    acc, fed, fake, clock = env
    out = signup(fed, google_login(acc, fed, fake, clock), "gone")
    acc.s.x("UPDATE accounts SET disabled=1 WHERE id=?", (out["account"]["id"],))
    with pytest.raises(Refused) as e:
        google_login(acc, fed, fake, clock)
    assert e.value.code == "disabled"


def test_signup_ticket_rules(env):
    acc, fed, fake, clock = env
    res = google_login(acc, fed, fake, clock, sub="g-t")
    with pytest.raises(Refused):
        fed.signup(res["ticket"], "kid_g", "toddler", None, "ip")        # spends the ticket
    with pytest.raises(Refused) as e:
        fed.signup(res["ticket"], "kid_g", "child", None, "ip")
    assert e.value.code == "bad_flow"
    res = google_login(acc, fed, fake, clock, sub="g-t")
    kid = fed.signup(res["ticket"], "kid_g", "child", None, "ip")
    assert kid["account"]["minor"] is True
    assert kid["account"]["privacy"]["friend_requests_from"] == "friends_of_friends"


# ---------- Steam OpenID 2.0 ----------

def steam_params(fed, clock, steam_id="76561197960287930", **over):
    r = fed.steam_start(LOOP)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["authorize_url"]).query))
    nonce = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock.t)) + secrets.token_hex(4)
    claimed = f"https://steamcommunity.com/openid/id/{steam_id}"
    p = {"state": r["state"], "openid.ns": "http://specs.openid.net/auth/2.0", "openid.mode": "id_res",
         "openid.op_endpoint": STEAM_OP, "openid.claimed_id": claimed, "openid.identity": claimed,
         "openid.return_to": q["openid.return_to"], "openid.response_nonce": nonce, "openid.assoc_handle": "1234567890",
         "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle",
         "openid.sig": "W0hXk1nHnS1e2g0dV2nO2CZQZQI=", **over}
    return r, p


def test_steam_happy_path_signup_and_sign_in(env):
    acc, fed, fake, clock = env
    r, p = steam_params(fed, clock)
    assert r["authorize_url"].startswith(STEAM_OP + "?") and "checkid_setup" in r["authorize_url"]
    res = fed.steam_finish(r["flow"], p, "ip")
    out = signup(fed, res, "steamer")
    r, p = steam_params(fed, clock)
    assert fed.steam_finish(r["flow"], p, "ip")["account"]["id"] == out["account"]["id"]


@pytest.mark.parametrize("over", [
    {"openid.claimed_id": "https://steamcommunity.com/openid/id/76561197960287931"},          # identity != claimed
    {"openid.claimed_id": "https://evil.example/openid/id/76561197960287930",
     "openid.identity": "https://evil.example/openid/id/76561197960287930"},
    {"openid.op_endpoint": "https://evil.example/openid/login"},
    {"openid.return_to": "http://127.0.0.1:47615/callback?state=other"},
    {"openid.mode": "cancel"},
    {"openid.signed": "op_endpoint,claimed_id,identity"},
    {"state": "forged"},
    {"openid.response_nonce": "2001-01-01T00:00:00Zabcd"},
])
def test_steam_tampering_is_refused(env, over):
    acc, fed, fake, clock = env
    r, p = steam_params(fed, clock, **over)
    with pytest.raises(Refused) as e:
        fed.steam_finish(r["flow"], p, "ip")
    assert e.value.code == "steam_refused"


def test_steam_replayed_nonce_and_invalid_signature(env):
    acc, fed, fake, clock = env
    r, p = steam_params(fed, clock)
    signup(fed, fed.steam_finish(r["flow"], p, "ip"), "steamtwo")
    r2, p2 = steam_params(fed, clock)
    p2["openid.response_nonce"] = p["openid.response_nonce"]
    with pytest.raises(Refused):
        fed.steam_finish(r2["flow"], p2, "ip")
    fake.steam_valid = False
    r3, p3 = steam_params(fed, clock)
    with pytest.raises(Refused):
        fed.steam_finish(r3["flow"], p3, "ip")


# ---------- passkeys (WebAuthn) with a software authenticator ----------

def cbor(v) -> bytes:
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for ai, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | ai]) + n.to_bytes(size, "big")
    if isinstance(v, bool):
        return bytes([0xF5 if v else 0xF4])
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        return head(3, len(v.encode())) + v.encode()
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(cbor(x) for x in v)
    return head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())


class SoftKey:
    def __init__(self, alg=-7):
        self.alg, self.count, self.id = alg, 0, secrets.token_bytes(16)
        self.key = ec.generate_private_key(ec.SECP256R1()) if alg == -7 else \
            rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def cose(self):
        pub = self.key.public_key().public_numbers()
        if self.alg == -7:
            return {1: 2, 3: -7, -1: 1, -2: pub.x.to_bytes(32, "big"), -3: pub.y.to_bytes(32, "big")}
        return {1: 3, 3: -257, -1: pub.n.to_bytes(256, "big"), -2: pub.e.to_bytes(3, "big")}

    def auth_data(self, rp_id, flags, attested=False):
        self.count += 1
        out = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", self.count)
        if attested:
            out += b"\0" * 16 + struct.pack(">H", len(self.id)) + self.id + cbor(self.cose())
        return out

    def client_data(self, kind, challenge, origin):
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def create(self, options, origin=ORIGIN, rp_id=None, flags=0x45):
        pk = options["publicKey"]
        cd = self.client_data("webauthn.create", pk["challenge"], origin)
        att = cbor({"fmt": "none", "attStmt": {}, "authData": self.auth_data(rp_id or pk["rp"]["id"], flags, True)})
        return {"id": b64u(self.id), "rawId": b64u(self.id), "type": "public-key",
                "response": {"clientDataJSON": b64u(cd), "attestationObject": b64u(att)}}

    def get(self, options, user_handle, origin=ORIGIN, flags=0x05, tamper=False):
        pk = options["publicKey"]
        cd = self.client_data("webauthn.get", pk["challenge"], origin)
        ad = self.auth_data(pk["rpId"], flags)
        msg = ad + hashlib.sha256(cd).digest()
        sig = self.key.sign(msg, ec.ECDSA(hashes.SHA256())) if self.alg == -7 else \
            self.key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
        if tamper:
            sig = sig[:-1] + bytes([sig[-1] ^ 1])
        return {"id": b64u(self.id), "type": "public-key",
                "response": {"clientDataJSON": b64u(cd), "authenticatorData": b64u(ad), "signature": b64u(sig),
                             "userHandle": b64u(user_handle.encode())}}


@pytest.mark.parametrize("alg", [-7, -257])
def test_passkey_register_and_discoverable_login(env, alg):
    acc, fed, _, clock = env
    t = acc.register("hello" + str(abs(alg)), PW, None, "adult", "ip")
    c = claims_of(acc, t)
    key = SoftKey(alg)
    opts = fed.passkey_register_options(c)
    sel = opts["publicKey"]["authenticatorSelection"]
    assert sel == {"residentKey": "required", "requireResidentKey": True, "userVerification": "required"}
    out = fed.passkey_register_finish(c, opts["flow"], key.create(opts), "Windows Hello", "ip")
    assert out["passkeys"][0]["name"] == "Windows Hello"
    lo = fed.passkey_login_options()
    assert lo["publicKey"]["allowCredentials"] == [] and lo["publicKey"]["userVerification"] == "required"
    tokens = fed.passkey_login_finish(lo["flow"], key.get(lo, c["sub"]), "ip")
    assert crypto.verify_jwt(tokens["access_token"], acc.signer.jwks, now=clock.t)["amr"] == ["hwk", "uv"]


def test_passkey_registration_checks(env):
    acc, fed, _, _ = env
    c = claims_of(acc, acc.register("pkchecks", PW, None, "adult", "ip"))
    key = SoftKey()
    for kwargs in ({"origin": "https://evil.example"}, {"rp_id": "evil.example"}, {"flags": 0x41}):   # 0x41: no UV
        opts = fed.passkey_register_options(c)
        with pytest.raises(Refused) as e:
            fed.passkey_register_finish(c, opts["flow"], key.create(opts, **kwargs), None, "ip")
        assert e.value.code == "passkey_refused"
    opts = fed.passkey_register_options(c)
    cred = key.create(opts)
    other = fed.passkey_register_options(c)
    with pytest.raises(Refused):                          # answer to a different challenge
        fed.passkey_register_finish(c, other["flow"], cred, None, "ip")


def test_passkey_login_checks_and_clone_detection(env):
    acc, fed, _, _ = env
    c = claims_of(acc, acc.register("pklogin", PW, None, "adult", "ip"))
    key = SoftKey()
    opts = fed.passkey_register_options(c)
    fed.passkey_register_finish(c, opts["flow"], key.create(opts), None, "ip")
    for kwargs in ({"tamper": True}, {"origin": "http://localhost:9999"}, {"flags": 0x01}):
        lo = fed.passkey_login_options()
        with pytest.raises(Refused):
            fed.passkey_login_finish(lo["flow"], key.get(lo, c["sub"], **kwargs), "ip")
    lo = fed.passkey_login_options()
    with pytest.raises(Refused):                          # userHandle pointing at someone else
        fed.passkey_login_finish(lo["flow"], key.get(lo, "acct_someoneelse"), "ip")
    lo = fed.passkey_login_options()
    fed.passkey_login_finish(lo["flow"], key.get(lo, c["sub"]), "ip")
    key.count -= 5                                         # a copied key replays an older counter
    lo = fed.passkey_login_options()
    with pytest.raises(Refused):
        fed.passkey_login_finish(lo["flow"], key.get(lo, c["sub"]), "ip")
    lo = fed.passkey_login_options()
    with pytest.raises(Refused):
        fed.passkey_login_finish(lo["flow"], SoftKey().get(lo, c["sub"]), "ip")    # unknown credential


def test_passkey_only_account_cannot_remove_last_passkey(env):
    acc, fed, fake, clock = env
    out = signup(fed, google_login(acc, fed, fake, clock, sub="g-pk"), "pkonly")
    c = claims_of(acc, out)
    key = SoftKey()
    opts = fed.passkey_register_options(c)
    pk_id = fed.passkey_register_finish(c, opts["flow"], key.create(opts), None, "ip")["passkeys"][0]["id"]
    fed.unlink(c, "google", "ip")                          # the passkey remains as a method
    with pytest.raises(Refused) as e:
        fed.passkey_remove(c, pk_id, "ip")
    assert e.value.code == "last_method"


def test_steam_nonce_parse_is_utc():
    assert calendar.timegm(time.strptime("2026-10-27T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ")) == 1793059200
