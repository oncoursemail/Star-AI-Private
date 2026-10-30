"""Metallic API v1: OpenAPI validity, auth + scopes, server keys, rate limits, minors' privacy, webhooks (signing,
retries, log), releases from signed channel files, and SDK smoke tests against a local server."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

from metallic.api import sdkgen, webhooks as wh
from metallic.api.auth import Sealer
from metallic.api.server import serve
from metallic.api.service import Api
from metallic.api.sources import Content
from metallic.api.spec import Spec
from metallic.api.store import Store
from metallic.api.upstream import Accounts, UpstreamError

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
jsonschema = pytest.importorskip("jsonschema")


# ---------------------------------------------------------------- fakes
class Clock:
    def __init__(self, t: float = 1_793_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeAccounts:
    """Just enough of Metallic accounts: introspection, me, friends, presence, invites, news."""

    def __init__(self, clock):
        self.clock = clock
        self.users = {  # token -> claims
            "eyJhbGciOiJFUzI1NiJ9.adult.sig": {"sub": "acc_adult", "name": "alex", "role": "user", "minor": False},
            "eyJhbGciOiJFUzI1NiJ9.owner.sig": {"sub": "acc_owner", "name": "boss", "role": "owner", "minor": False},
            "eyJhbGciOiJFUzI1NiJ9.teen.sig": {"sub": "acc_teen", "name": "kid_one", "role": "user", "minor": True},
            "eyJhbGciOiJFUzI1NiJ9.sam.sig": {"sub": "acc_sam", "name": "sam", "role": "user", "minor": False},
        }
        self.exp = {t: clock() + 900 for t in self.users}
        self.signed_out: set[str] = set()
        self.requests = {("acc_sam", "acc_adult")}
        self.friends: set[frozenset] = set()
        self.calls: list[tuple] = []
        self.introspections = 0

    def _claims(self, token):
        if token not in self.users or token in self.signed_out or self.exp[token] <= self.clock():
            raise UpstreamError(401, "unauthorized", "Sign in again.")
        return self.users[token]

    def introspect(self, token, now=None, max_age=60):
        self.introspections += 1
        try:
            c = self._claims(token)
        except UpstreamError:
            return {"active": False}
        return {"active": True, **c, "exp": self.exp[token]}

    def health(self):
        return True

    def _by_name(self, name):
        return next((c for c in self.users.values() if c["name"] == name.lower()), None)

    def call(self, method, path, body=None, token=None):
        self.calls.append((method, path, body, token))
        if path.startswith("/v1/news"):
            return {"news": [{"id": "news_1", "title": "Hello", "body": "First post", "game": None, "author": "Boss",
                              "created": 1.0, "pinned": False}]}
        c = self._claims(token)
        if path == "/v1/me":
            return {"id": c["sub"], "username": c["name"], "display_name": c["name"].title(), "role": c["role"],
                    "age_band": "teen" if c["minor"] else "adult", "minor": c["minor"], "created": 1.0}
        if path == "/v1/friends":
            ids = [next(iter(p - {c["sub"]})) for p in self.friends if c["sub"] in p]
            people = [x for x in self.users.values() if x["sub"] in ids]
            return {"friends": [{"id": x["sub"], "username": x["name"], "display_name": None,
                                 "presence": {"status": "online"}} for x in people],
                    "incoming": [], "outgoing": [], "blocked": []}
        if path == "/v1/friends/accept":
            other = self._by_name(body["username"])
            if other is None or (other["sub"], c["sub"]) not in self.requests:
                raise UpstreamError(404, "not_found", "There is no request from that player.")
            self.friends.add(frozenset((other["sub"], c["sub"])))
            return {"ok": True, "state": "friends"}
        if path == "/v1/presence" and method == "GET":
            return {"friends": []}
        if path == "/v1/presence" and method == "POST":
            return {"ok": True, "ttl": 120}
        if path == "/v1/invites" and method == "GET":
            return {"incoming": [], "outgoing": []}
        raise UpstreamError(404, "not_found", "No such endpoint.")


def make_release(tmp_path: Path, version="1.0.0"):
    """A real signed channel made with the PX updater's publisher, plus its trust file."""
    from launcher.updates import publish as pub
    from launcher.updates.keys import PrivateKey
    import base64
    key = PrivateKey(bytes(range(32)))
    root = tmp_path / "releases"
    src = tmp_path / f"src-{version}"
    src.mkdir(parents=True, exist_ok=True)
    (src / "Metallic.exe").write_bytes(b"MZ fake launcher " + version.encode())
    comp = pub.build_component(root, "launcher", version, src, entry="Metallic.exe", chunk_threshold=10**9)
    pub.publish(root, "beta", {"launcher": comp}, key)
    trust = tmp_path / "trust.json"
    trust.write_text(json.dumps({"keys": [{"public": base64.b64encode(key.public).decode()}]}), encoding="utf-8")
    return root, trust


class Rig:
    def __init__(self, tmp_path, conf: dict | None = None, sender=None):
        self.clock = Clock()
        self.accounts = FakeAccounts(self.clock)
        self.store = Store()
        self.sent: list[tuple] = []
        self.responses: list[int | None] = []

        def fake_sender(url, headers, body, timeout=5.0):
            self.sent.append((url, headers, body))
            code = self.responses.pop(0) if self.responses else 200
            return (code, None) if code else (None, "ConnectionRefusedError")
        self.sealer = Sealer(os.urandom(32))
        conf = {"channels": ["stable", "beta"], **(conf or {})}
        self.hooks = wh.Webhooks(self.store, self.sealer, self.clock, sender or fake_sender,
                                 allow_hosts=("hooks.lan", "127.0.0.1"))
        self.content = Content(self.store, self.clock, conf, probe=lambda url: "up")
        self.api = Api(self.store, self.accounts, self.content, self.hooks, self.sealer, self.clock,
                       allowed_origins=("https://metallic.club",))
        self.spec = self.api.spec
        self.validator_cache: dict = {}

    def call(self, method, path, token=None, body=None, origin=None, ip="203.0.113.5", raw=None):
        headers = {}
        if token:
            headers["authorization"] = "Bearer " + token
        if origin:
            headers["origin"] = origin
        data = b""
        if body is not None or raw is not None:
            data = raw if raw is not None else json.dumps(body).encode()
            headers["content-type"] = "application/json"
        code, h, out = self.api.handle(method, path, headers, data, ip)
        obj = json.loads(out) if out and h.get("Content-Type", "").startswith("application/json") else out
        self.check_response(method, path, code, obj)
        return code, h, obj

    def check_response(self, method, path, code, obj):
        """Every JSON answer must match the response schema the document declares."""
        op, _, _ = self.spec.match(method, path.split("?")[0].rstrip("/") or "/")
        if op is None or not isinstance(obj, dict):
            return
        resp = op.raw["responses"].get(str(code)) or (op.raw["responses"].get("400") if code >= 400 else None)
        if code >= 400:
            schema = self.spec.doc["components"]["schemas"]["Error"]
        elif resp is None:
            raise AssertionError(f"{op.op_id} answered {code}, which the document does not list")
        else:
            schema = self.spec.resolve(resp).get("content", {}).get("application/json", {}).get("schema")
        if schema:
            doc = dict(self.spec.doc)
            jsonschema.validate(obj, {**schema, "components": doc["components"]},
                                cls=jsonschema.Draft202012Validator)

    def owner_key(self, scopes, games=None, rate=None):
        body = {"name": "test key", "scopes": scopes}
        if games:
            body["games"] = games
        if rate:
            body["rate_per_minute"] = rate
        code, _, k = self.call("POST", "/v1/keys", "eyJhbGciOiJFUzI1NiJ9.owner.sig", body)
        assert code == 201, k
        return k


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


# ---------------------------------------------------------------- the document
def test_openapi_document_is_valid_openapi_3_1_and_matches_the_code():
    doc = json.loads((REPO / "metallic" / "metallic" / "api" / "openapi.json").read_text(encoding="utf-8"))
    meta = json.loads((HERE / "data" / "oas-3.1-schema.json").read_text(encoding="utf-8"))
    errors = list(jsonschema.Draft202012Validator(meta).iter_errors(doc))
    assert not errors, [e.message for e in errors[:5]]
    assert doc["openapi"].startswith("3.1")
    for name, schema in doc["components"]["schemas"].items():
        jsonschema.Draft202012Validator.check_schema(schema)
    spec = Spec(doc)
    assert spec.check({n[3:] for n in dir(Api) if n.startswith("op_")}) == []
    text = json.dumps(doc)
    for ref in set(__import__("re").findall(r'"\$ref": "([^"]+)"', text)):
        spec.resolve({"$ref": ref})                     # every reference resolves
    assert all(p.startswith(("/v1/", "/health")) for p in doc["paths"])
    broken = json.loads(json.dumps(doc))
    broken["paths"]["/v1/me"]["get"]["responses"] = "nope"
    assert list(jsonschema.Draft202012Validator(meta).iter_errors(broken))


def test_generated_sdks_and_docs_are_up_to_date():
    stale = [str(p) for p, text in sdkgen.outputs().items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
    assert not stale, "run: python -m metallic.api.sdkgen"


def test_served_openapi_is_the_file_and_scopes_list_matches(rig):
    code, _, doc = rig.call("GET", "/v1/openapi.json")
    assert code == 200 and doc["info"]["title"] == "Metallic API"
    code, _, sc = rig.call("GET", "/v1/scopes")
    names = {s["name"] for s in sc["scopes"]}
    assert {"friends:read", "presence:write", "servers:write", "keys:admin"} <= names


# ---------------------------------------------------------------- auth and scopes
def test_public_reads_need_no_token_and_allow_any_web_origin(rig):
    code, h, body = rig.call("GET", "/v1/news", origin="https://anyone.example")
    assert code == 200 and h["Access-Control-Allow-Origin"] == "*" and body["news"][0]["title"] == "Hello"
    code, h, body = rig.call("GET", "/v1/games")
    assert code == 200 and [g["id"] for g in body["games"]] == ["RC", "MC", "RB", "PX"]
    code, h, _ = rig.call("OPTIONS", "/v1/games", origin="https://anyone.example")
    assert code == 204 and h["Access-Control-Allow-Methods"] == "GET"


def test_signed_in_calls_from_web_pages_are_refused_unless_the_origin_is_allowed(rig):
    code, _, body = rig.call("GET", "/v1/me", "eyJhbGciOiJFUzI1NiJ9.adult.sig", origin="https://evil.example")
    assert code == 403 and body["error"] == "browser_refused"
    code, h, body = rig.call("GET", "/v1/me", "eyJhbGciOiJFUzI1NiJ9.adult.sig", origin="https://metallic.club")
    assert code == 200 and h["Access-Control-Allow-Origin"] == "https://metallic.club"


def test_first_party_sign_in_token_reaches_accounts_as_the_player(rig):
    code, _, me = rig.call("GET", "/v1/me", "eyJhbGciOiJFUzI1NiJ9.adult.sig")
    assert code == 200 and me["username"] == "alex"
    assert rig.accounts.calls[-1] == ("GET", "/v1/me", None, "eyJhbGciOiJFUzI1NiJ9.adult.sig")
    code, _, out = rig.call("PUT", "/v1/me/presence", "eyJhbGciOiJFUzI1NiJ9.adult.sig", {"status": "playing", "game": "RC"})
    assert code == 200 and out["ttl"] == 120
    assert rig.accounts.calls[-1][:3] == ("POST", "/v1/presence", {"status": "playing", "game": "RC"})


def test_missing_bad_and_signed_out_tokens(rig):
    code, h, body = rig.call("GET", "/v1/friends")
    assert code == 401 and "WWW-Authenticate" in h
    assert rig.call("GET", "/v1/friends", "not-a-token")[0] == 401
    assert rig.call("GET", "/v1/friends", "eyJhbGciOiJFUzI1NiJ9.unknown.sig")[0] == 401
    rig.accounts.signed_out.add("eyJhbGciOiJFUzI1NiJ9.adult.sig")
    assert rig.call("GET", "/v1/friends", "eyJhbGciOiJFUzI1NiJ9.adult.sig")[0] == 401


def test_invalid_bodies_are_refused_before_reaching_accounts(rig):
    n = len(rig.accounts.calls)
    code, _, body = rig.call("PUT", "/v1/me/presence", "eyJhbGciOiJFUzI1NiJ9.adult.sig", {"status": "dancing"})
    assert code == 400 and "status" in body["text"]
    code, _, body = rig.call("PUT", "/v1/me/presence", "eyJhbGciOiJFUzI1NiJ9.adult.sig", {"status": "online", "extra": 1})
    assert code == 400 and "not allowed" in body["text"]
    assert rig.call("PUT", "/v1/me/presence", "eyJhbGciOiJFUzI1NiJ9.adult.sig", raw=b"{nope")[0] == 400
    assert len(rig.accounts.calls) == n
    assert rig.call("DELETE", "/v1/games")[0] == 405
    assert rig.call("GET", "/v1/nothing")[0] == 404


def test_scoped_token_carries_only_its_scopes_and_expires(rig):
    code, _, tok = rig.call("POST", "/v1/oauth/token", body={
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "subject_token": "eyJhbGciOiJFUzI1NiJ9.adult.sig",  # star:allow (test fixture)
        "scope": "friends:read presence:read", "client_name": "test app"})
    assert code == 200 and tok["access_token"].startswith("mtk_") and tok["scope"] == "friends:read presence:read"
    assert tok["expires_in"] == 900
    t = tok["access_token"]
    assert rig.call("GET", "/v1/friends", t)[0] == 200
    assert rig.accounts.calls[-1][3] == "eyJhbGciOiJFUzI1NiJ9.adult.sig"          # forwarded as the player
    code, h, body = rig.call("PUT", "/v1/me/presence", t, {"status": "online"})
    assert code == 403 and body["error"] == "insufficient_scope" and body["scope"] == "presence:write"
    assert 'scope="presence:write"' in h["WWW-Authenticate"]
    rig.clock.t += 901
    assert rig.call("GET", "/v1/friends", t)[0] == 401


def test_scoped_token_never_outlives_the_sign_in_and_can_be_revoked(rig):
    rig.accounts.exp["eyJhbGciOiJFUzI1NiJ9.adult.sig"] = rig.clock() + 300
    _, _, tok = rig.call("POST", "/v1/oauth/token", body={"subject_token": "eyJhbGciOiJFUzI1NiJ9.adult.sig", "scope": "profile:read"})  # star:allow (test fixture)
    assert tok["expires_in"] == 300
    assert rig.call("GET", "/v1/me", tok["access_token"])[0] == 200
    assert rig.call("POST", "/v1/oauth/revoke", body={"token": tok["access_token"]})[0] == 200
    assert rig.call("GET", "/v1/me", tok["access_token"])[0] == 401


def test_admin_scopes_and_unknown_scopes_are_never_delegated(rig):
    code, _, body = rig.call("POST", "/v1/oauth/token", body={"subject_token": "eyJhbGciOiJFUzI1NiJ9.owner.sig", "scope": "keys:admin"})  # star:allow (test fixture)
    assert code == 403 and body["error"] == "invalid_scope"
    code, _, body = rig.call("POST", "/v1/oauth/token", body={"subject_token": "eyJhbGciOiJFUzI1NiJ9.adult.sig", "scope": "root:all"})  # star:allow (test fixture)
    assert code == 400 and body["error"] == "invalid_scope"
    code, _, body = rig.call("POST", "/v1/oauth/token", body={"subject_token": "msk_x_y_zzzzzzzzzzzzzzzz", "scope": "profile:read"})
    assert code == 400


def test_only_owner_or_admin_manage_server_keys(rig):
    code, _, body = rig.call("POST", "/v1/keys", "eyJhbGciOiJFUzI1NiJ9.adult.sig", {"name": "x", "scopes": ["servers:write"]})
    assert code == 403 and body["error"] == "insufficient_scope"
    k = rig.owner_key(["servers:write"], ["RC"])
    assert k["secret"].startswith("msk_") and k["games"] == ["RC"]
    code, _, keys = rig.call("GET", "/v1/keys", "eyJhbGciOiJFUzI1NiJ9.owner.sig")
    assert code == 200 and "secret" not in json.dumps(keys)
    assert rig.call("POST", "/v1/keys", "eyJhbGciOiJFUzI1NiJ9.owner.sig", {"name": "x", "scopes": ["friends:read"]})[0] == 400


def test_server_keys_have_their_own_scopes_games_and_revocation(rig):
    k = rig.owner_key(["servers:write"], ["RC"])
    s = k["secret"]
    code, _, _ = rig.call("POST", "/v1/servers/heartbeat", s, {"game": "RC", "server_id": "eu-1", "players": 7})
    assert code == 200
    rig.call("POST", "/v1/servers/heartbeat", s, {"game": "RC", "server_id": "eu-2", "players": 5})
    _, _, rc = rig.call("GET", "/v1/games/RC")
    assert rc["servers"] == {"online": 2, "players": 12, "updated": rig.clock()}
    code, _, body = rig.call("POST", "/v1/servers/heartbeat", s, {"game": "MC", "server_id": "x", "players": 1})
    assert code == 403 and body["error"] == "wrong_game"
    code, _, body = rig.call("POST", "/v1/players/verify", s, {"player_token": "eyJhbGciOiJFUzI1NiJ9.adult.sig"})  # star:allow (test fixture)
    assert code == 403 and body["error"] == "insufficient_scope"
    code, _, body = rig.call("GET", "/v1/friends", s)
    assert code == 403 and body["error"] == "wrong_credential"
    code, _, body = rig.call("POST", "/v1/servers/heartbeat", "eyJhbGciOiJFUzI1NiJ9.adult.sig", {"game": "RC", "server_id": "x", "players": 1})
    assert code == 403 and body["error"] == "wrong_credential"
    rig.clock.t += 91
    assert rig.call("GET", "/v1/games/RC")[2]["servers"]["online"] == 0       # stale servers drop out
    assert rig.call("DELETE", f"/v1/keys/{k['id']}", "eyJhbGciOiJFUzI1NiJ9.owner.sig")[0] == 200
    assert rig.call("POST", "/v1/servers/heartbeat", s, {"game": "RC", "server_id": "eu-1", "players": 1})[0] == 401
    forged = s[:-4] + ("AAAA" if not s.endswith("AAAA") else "BBBB")
    assert rig.call("POST", "/v1/servers/heartbeat", forged, {"game": "RC", "server_id": "e", "players": 1})[0] == 401


# ---------------------------------------------------------------- rate limits
def test_per_key_rate_limit_with_retry_after_and_refill(rig):
    s = rig.owner_key(["servers:write"], rate=6)["secret"]
    hb = {"game": "RC", "server_id": "eu-1", "players": 1}
    codes = [rig.call("POST", "/v1/servers/heartbeat", s, hb)[0] for _ in range(3)]
    code, h, body = rig.call("POST", "/v1/servers/heartbeat", s, hb)
    assert codes == [200, 200, 200] and code == 429 and body["error"] == "slow_down"
    assert int(h["Retry-After"]) >= 1 and h["RateLimit-Limit"] == "6" and h["RateLimit-Remaining"] == "0"
    other = rig.owner_key(["servers:write"], rate=6)["secret"]           # buckets are per key
    assert rig.call("POST", "/v1/servers/heartbeat", other, hb)[0] == 200
    rig.clock.t += 10
    assert rig.call("POST", "/v1/servers/heartbeat", s, hb)[0] == 200


def test_anonymous_and_token_exchange_limits(rig):
    codes = [rig.call("GET", "/v1/games", ip="203.0.113.9")[0] for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429
    assert rig.call("GET", "/v1/games", ip="203.0.113.8")[0] == 200        # another client is unaffected
    body = {"subject_token": "eyJhbGciOiJFUzI1NiJ9.adult.sig", "scope": "profile:read"}  # star:allow (test fixture)
    codes = [rig.call("POST", "/v1/oauth/token", body=body, ip="203.0.113.7")[0] for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_bad_tokens_are_charged_to_the_callers_ip(rig):
    codes = [rig.call("GET", "/v1/friends", "eyJhbGciOiJFUzI1NiJ9.wrong.sig", ip="203.0.113.6")[0] for _ in range(31)]
    assert codes[:30] == [401] * 30 and codes[30] == 429


# ---------------------------------------------------------------- minors' privacy
def test_minors_cannot_delegate_social_scopes(rig):
    code, _, body = rig.call("POST", "/v1/oauth/token", body={"subject_token": "eyJhbGciOiJFUzI1NiJ9.teen.sig",  # star:allow (test fixture)
                                                              "scope": "profile:read friends:read"})
    assert code == 403 and body["error"] == "minor_privacy"
    code, _, tok = rig.call("POST", "/v1/oauth/token", body={"subject_token": "eyJhbGciOiJFUzI1NiJ9.teen.sig", "scope": "profile:read"})  # star:allow (test fixture)
    assert code == 200
    assert rig.call("GET", "/v1/me", tok["access_token"])[0] == 200
    assert rig.call("GET", "/v1/presence", tok["access_token"])[0] == 403
    assert rig.call("GET", "/v1/friends", "eyJhbGciOiJFUzI1NiJ9.teen.sig")[0] == 200        # the player's own launcher still works


def test_servers_and_webhooks_never_get_a_minors_name(rig):
    s = rig.owner_key(["servers:write", "players:read", "webhooks:manage"])["secret"]
    _, _, teen = rig.call("POST", "/v1/players/verify", s, {"player_token": "eyJhbGciOiJFUzI1NiJ9.teen.sig"})  # star:allow (test fixture)
    _, _, adult = rig.call("POST", "/v1/players/verify", s, {"player_token": "eyJhbGciOiJFUzI1NiJ9.adult.sig"})  # star:allow (test fixture)
    assert teen == {"active": True, "id": "acc_teen", "username": None, "minor": True}
    assert adult["username"] == "alex" and adult["minor"] is False
    assert rig.call("POST", "/v1/players/verify", s, {"player_token": "eyJhbGciOiJFUzI1NiJ9.gone.sig"})[2] == {"active": False}  # star:allow (test fixture)
    rig.call("POST", "/v1/webhooks", s, {"url": "https://hooks.lan/in", "events": ["player.joined"]})
    rig.call("POST", "/v1/servers/events", s, {"type": "player.joined", "game": "RB", "server_id": "s1",
                                               "player_token": "eyJhbGciOiJFUzI1NiJ9.teen.sig", "players": 3})  # star:allow (test fixture)
    rig.call("POST", "/v1/servers/events", s, {"type": "player.joined", "game": "RB", "server_id": "s1",
                                               "player_token": "eyJhbGciOiJFUzI1NiJ9.adult.sig"})  # star:allow (test fixture)
    rig.hooks.run_due()
    payloads = [json.loads(b)["data"]["player"] for _, _, b in rig.sent]
    assert payloads[0] == {"account_id": "acc_teen", "username": None, "minor": True, "ref": None}
    assert payloads[1]["username"] == "alex"
    assert "kid_one" not in json.dumps([json.loads(b) for _, _, b in rig.sent])


# ---------------------------------------------------------------- webhooks
def test_webhook_secret_shown_once_and_deliveries_are_hmac_signed(rig):
    s = rig.owner_key(["webhooks:manage"])["secret"]
    code, _, hook = rig.call("POST", "/v1/webhooks", s, {"url": "https://hooks.lan/in", "events": ["ping"],
                                                         "description": "test"})
    assert code == 201 and hook["secret"].startswith("whsec_")
    _, _, listed = rig.call("GET", "/v1/webhooks", s)
    assert "secret" not in json.dumps(listed) and listed["webhooks"][0]["id"] == hook["id"]
    code, _, ev = rig.call("POST", f"/v1/webhooks/{hook['id']}/ping", s)
    assert code == 202 and ev["deliveries"] == 1
    assert rig.hooks.run_due() == 1
    url, headers, body = rig.sent[0]
    assert url == "https://hooks.lan/in" and headers["Metallic-Event"] == "ping"
    assert wh.verify(hook["secret"], headers["Metallic-Signature"], body, now=rig.clock())
    assert not wh.verify(hook["secret"], headers["Metallic-Signature"], body + b" ", now=rig.clock())
    assert not wh.verify("whsec_other", headers["Metallic-Signature"], body, now=rig.clock())
    assert not wh.verify(hook["secret"], headers["Metallic-Signature"], body, now=rig.clock() + 301)   # replay window
    env = json.loads(body)
    assert env["type"] == "ping" and env["id"] == ev["event_id"]
    _, _, log = rig.call("GET", f"/v1/webhooks/{hook['id']}/deliveries", s)
    assert log["deliveries"][0]["status"] == "delivered" and log["deliveries"][0]["http_status"] == 200
    # someone else's key cannot see or ping it
    other = rig.owner_key(["webhooks:manage"])["secret"]
    assert rig.call("GET", f"/v1/webhooks/{hook['id']}/deliveries", other)[0] == 404


def test_failed_deliveries_retry_with_backoff_then_fail(rig):
    s = rig.owner_key(["webhooks:manage"])["secret"]
    _, _, hook = rig.call("POST", "/v1/webhooks", s, {"url": "https://hooks.lan/in", "events": ["ping"]})
    rig.responses = [500, None, 503]          # then 200
    rig.call("POST", f"/v1/webhooks/{hook['id']}/ping", s)
    rig.hooks.run_due()
    _, _, log = rig.call("GET", f"/v1/webhooks/{hook['id']}/deliveries", s)
    d = log["deliveries"][0]
    assert d["status"] == "retrying" and d["attempt"] == 1 and d["http_status"] == 500
    assert d["next_attempt"] == rig.clock() + 10
    assert rig.hooks.run_due() == 0                       # not due yet
    rig.clock.t += 10
    rig.hooks.run_due()
    d = rig.call("GET", f"/v1/webhooks/{hook['id']}/deliveries", s)[2]["deliveries"][0]
    assert d["attempt"] == 2 and d["error"] == "ConnectionRefusedError" and d["next_attempt"] == rig.clock() + 60
    rig.clock.t += 60
    rig.hooks.run_due()
    rig.clock.t += 300
    rig.hooks.run_due()
    d = rig.call("GET", f"/v1/webhooks/{hook['id']}/deliveries", s)[2]["deliveries"][0]
    assert d["status"] == "delivered" and d["attempt"] == 4
    ids = {json.loads(b)["id"] for _, _, b in rig.sent}
    sigs = {h["Metallic-Signature"] for _, h, _ in rig.sent}
    assert len(ids) == 1 and len(sigs) >= 2               # same event id, fresh signature per attempt
    # a receiver that never answers: 6 attempts, then failed
    rig.responses = [500] * 10
    rig.call("POST", f"/v1/webhooks/{hook['id']}/ping", s)
    for _ in range(8):
        rig.hooks.run_due()
        rig.clock.t += 7200
    d = rig.call("GET", f"/v1/webhooks/{hook['id']}/deliveries", s)[2]["deliveries"][0]
    assert d["status"] == "failed" and d["attempt"] == len(wh.BACKOFF) and d["next_attempt"] is None


def test_webhook_targets_on_private_addresses_are_refused(rig):
    s = rig.owner_key(["webhooks:manage"])["secret"]
    for url in ("https://10.0.0.8/in", "https://localhost/in", "http://example.com/in", "https://u:p@hooks.lan/in"):  # star:allow (test fixture)
        code, _, body = rig.call("POST", "/v1/webhooks", s, {"url": url, "events": ["ping"]})
        assert code == 400, url
    rig.hooks.resolver = lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.215.14", port))]
    assert rig.call("POST", "/v1/webhooks", s, {"url": "https://example.com/in", "events": ["ping"]})[0] == 201
    rig.hooks.resolver = lambda host, port, proto=0: [(2, 1, 6, "", ("192.168.1.10", port))]  # star:allow (test fixture)
    assert rig.call("POST", "/v1/webhooks", s, {"url": "https://rebind.example/in", "events": ["ping"]})[0] == 400


def test_game_events_only_reach_keys_for_that_game(rig):
    rc = rig.owner_key(["servers:write", "webhooks:manage"], ["RC"])["secret"]
    mc = rig.owner_key(["webhooks:manage"], ["MC"])["secret"]
    rig.call("POST", "/v1/webhooks", rc, {"url": "https://hooks.lan/rc", "events": ["player.joined"]})
    rig.call("POST", "/v1/webhooks", mc, {"url": "https://hooks.lan/mc", "events": ["player.joined"]})
    _, _, ev = rig.call("POST", "/v1/servers/events", rc, {"type": "player.joined", "game": "RC", "server_id": "a",
                                                           "player_ref": "p-123"})
    assert ev["deliveries"] == 1
    rig.hooks.run_due()
    assert [u for u, _, _ in rig.sent] == ["https://hooks.lan/rc"]
    assert json.loads(rig.sent[0][2])["data"]["player"]["ref"] == "p-123"


def test_friend_added_event_carries_account_ids_only(rig):
    owner_hook = rig.call("POST", "/v1/webhooks", "eyJhbGciOiJFUzI1NiJ9.owner.sig", {"url": "https://hooks.lan/f",
                                                                     "events": ["friend.added"]})
    assert owner_hook[0] == 201
    code, _, out = rig.call("POST", "/v1/friends/requests/sam/accept", "eyJhbGciOiJFUzI1NiJ9.adult.sig")
    assert code == 200 and out["state"] == "friends"
    assert rig.accounts.calls[-2][:3] == ("POST", "/v1/friends/accept", {"username": "sam"})
    rig.hooks.run_due()
    env = json.loads(rig.sent[0][2])
    assert env["type"] == "friend.added" and env["data"] == {"accounts": ["acc_adult", "acc_sam"]}
    assert rig.call("POST", "/v1/friends/requests/nobody/accept", "eyJhbGciOiJFUzI1NiJ9.adult.sig")[0] == 404


# ---------------------------------------------------------------- releases, progress, status
def test_releases_come_from_verified_signed_channel_files(tmp_path):
    root, trust = make_release(tmp_path)
    r = Rig(tmp_path, {"releases_dir": str(root), "trust_file": str(trust)})
    code, _, lst = r.call("GET", "/v1/releases")
    assert code == 200 and {c["channel"]: c["state"] for c in lst["channels"]} == {"stable": "missing", "beta": "ok"}
    code, _, beta = r.call("GET", "/v1/releases/beta")
    assert code == 200 and beta["verified"] is True and beta["components"][0]["version"] == "1.0.0"
    assert r.call("GET", "/v1/releases/stable")[0] == 404
    assert r.call("GET", "/v1/releases/nightly")[0] == 404
    # tampered manifest: never served as verified
    m = root / "channels" / "beta.json"
    m.write_text(m.read_text(encoding="utf-8").replace("1.0.0", "9.9.9"), encoding="utf-8")
    r2 = Rig(tmp_path, {"releases_dir": str(root), "trust_file": str(trust)})
    code, _, body = r2.call("GET", "/v1/releases/beta")
    assert code == 503 and body["error"] == "unverified"
    # an empty trust list (no signing key installed yet) refuses everything
    empty = tmp_path / "empty.json"
    empty.write_text('{"keys": []}', encoding="utf-8")
    r3 = Rig(tmp_path, {"releases_dir": str(root), "trust_file": str(empty)})
    assert r3.call("GET", "/v1/releases/beta")[0] == 503


def test_release_published_fires_when_a_channel_moves_forward(tmp_path):
    root, trust = make_release(tmp_path, "1.0.0")
    r = Rig(tmp_path, {"releases_dir": str(root), "trust_file": str(trust)})
    r.call("POST", "/v1/webhooks", "eyJhbGciOiJFUzI1NiJ9.owner.sig", {"url": "https://hooks.lan/r", "events": ["release.published"]})
    assert r.content.watch_releases(r.hooks.emit) == []          # first sight: recorded, no event
    make_release(tmp_path, "1.1.0")
    assert r.content.watch_releases(r.hooks.emit) == [("beta", 2)]
    assert r.content.watch_releases(r.hooks.emit) == []
    r.hooks.run_due()
    data = json.loads(r.sent[0][2])["data"]
    assert data == {"channel": "beta", "sequence": 2, "components": [{"name": "launcher", "version": "1.1.0"}]}
    assert r.call("GET", "/v1/games")[2]["games"][0]["release"] is None    # no rc component published


def test_progress_and_project_status_are_public_and_scrubbed(rig):
    code, _, px = rig.call("GET", "/v1/progress")
    assert code == 200 and px["mode"] == "public" and "percent" not in json.dumps(px).lower()
    ids = [p["id"] for p in px["projects"]]
    assert {"rc", "mc", "rb", "litha", "star"} <= set(ids)
    assert rig.call("GET", "/v1/progress/rc")[2]["id"] == "rc"
    assert rig.call("GET", "/v1/progress/zz")[0] == 404
    code, _, st = rig.call("GET", "/v1/projects/status")
    assert code == 200 and [p["id"] for p in st["projects"]] == ["litha", "star"]
    _, _, games = rig.call("GET", "/v1/games")
    px_game = next(g for g in games["games"] if g["id"] == "PX")
    assert sum(px_game["roadmap"].values()) == sum(p["total"] for p in px["projects"])


def test_upstream_client_caches_introspection_and_maps_errors(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            n = int(self.headers["Content-Length"])
            tok = json.loads(self.rfile.read(n))["token"]
            body = {"active": True, "sub": "acc_x", "name": "x", "role": "user", "minor": False, "exp": 2e9} \
                if tok == "good.token.x" else {"active": False}
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            data = b'{"ok": false, "error": "not_found", "text": "No."}'
            self.send_response(404)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        acc = Accounts(f"http://127.0.0.1:{srv.server_port}")
        assert acc.introspect("good.token.x", now=100)["sub"] == "acc_x"
        assert acc.introspect("good.token.x", now=130)["sub"] == "acc_x"
        assert len(hits) == 1                                   # cached
        acc.introspect("good.token.x", now=170)
        assert len(hits) == 2                                   # 60 s cache
        assert acc.introspect("bad.token.x", now=100) == {"active": False}
        with pytest.raises(UpstreamError) as e:
            acc.call("GET", "/v1/me", token="good.token.x")
        assert e.value.status == 404 and e.value.code == "not_found"
        assert Accounts("http://127.0.0.1:9").health() is False
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- SDK smoke tests against a local server
@pytest.fixture
def live(tmp_path):
    root, trust = make_release(tmp_path)
    r = Rig(tmp_path, {"releases_dir": str(root), "trust_file": str(trust)})
    srv = serve(r.api, "127.0.0.1", 0)
    r.base = f"http://127.0.0.1:{srv.server_port}"
    yield r
    srv.shutdown()


def test_python_sdk_against_a_local_server(live):
    sys.path.insert(0, str(REPO / "metallic" / "sdk" / "python"))
    try:
        import metallic_api as sdk
    finally:
        sys.path.pop(0)
    anon = sdk.MetallicAPI(live.base)
    assert anon.health()["service"] == "metallic-api"
    assert [g["id"] for g in anon.list_games()["games"]] == ["RC", "MC", "RB", "PX"]
    assert anon.get_release("beta")["verified"] is True
    assert anon.list_news(limit=5)["news"][0]["id"] == "news_1"
    owner = sdk.MetallicAPI(live.base, "eyJhbGciOiJFUzI1NiJ9.owner.sig")
    key = owner.create_key({"name": "sdk test", "scopes": ["servers:write", "webhooks:manage"], "games": ["RB"]})
    server = sdk.MetallicAPI(live.base, key["secret"])
    assert server.server_heartbeat({"game": "RB", "server_id": "job-1", "players": 4})["ok"] is True
    hook = server.create_webhook({"url": "http://127.0.0.1:9/hook", "events": ["ping"]})
    server.ping_webhook(hook["id"])
    live.hooks.run_due()
    url, headers, body = live.sent[0]
    assert sdk.verify_webhook(hook["secret"], headers["Metallic-Signature"], body, now=live.clock())
    assert not sdk.verify_webhook(hook["secret"], headers["Metallic-Signature"], body + b"x", now=live.clock())
    with pytest.raises(sdk.MetallicAPIError) as e:
        server.list_friends()
    assert e.value.status == 403 and e.value.code == "wrong_credential"
    scoped = anon.exchange_token({"subject_token": "eyJhbGciOiJFUzI1NiJ9.adult.sig", "scope": "profile:read"})  # star:allow (test fixture)
    assert sdk.MetallicAPI(live.base, scoped["access_token"]).get_me()["username"] == "alex"


NODE = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"


def _node() -> str | None:
    return str(NODE) if NODE.is_file() else shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_javascript_sdk_against_a_local_server(live):
    key = live.owner_key(["servers:write", "webhooks:manage"], ["RC"])
    script = REPO / "metallic" / "sdk" / "js" / "examples" / "smoke.mjs"
    import base64
    body = b'{"id":"evt_1","type":"ping","created":1,"data":{}}'
    header = wh.sign("whsec_test", body, int(live.clock()))
    out = subprocess.run([_node(), str(script), live.base, key["secret"], "whsec_test", header,
                          base64.b64encode(body).decode(), str(live.clock())], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])
    assert report == {"games": 4, "release": "1.0.0", "heartbeat": True, "wrongCredential": 403,
                      "webhookSignatureOk": True, "tamperedRejected": True}


LUNE = Path(os.environ.get("LUNE_BIN", ""))


@pytest.mark.skipif(not LUNE.is_file(), reason="set LUNE_BIN to a lune binary to run the Luau SDK smoke test")
def test_luau_sdk_against_a_local_server(live):
    key = live.owner_key(["servers:write", "players:read"], ["RB"])
    sdk_dir = REPO / "metallic" / "sdk" / "luau"
    out = subprocess.run([str(LUNE), "run", str(sdk_dir / "tests" / "smoke.luau"), live.base, key["secret"]],
                         capture_output=True, text=True, timeout=60, cwd=str(sdk_dir))
    assert out.returncode == 0, out.stdout + out.stderr
    assert "SMOKE OK" in out.stdout
    _, _, rb = live.call("GET", "/v1/games/RB")
    assert rb["servers"]["players"] == 9


# ---------------------------------------------------------------- launcher + website use the API
def test_launcher_px_page_reads_progress_from_the_api(live, tmp_path):
    from launcher.px.service import PxService
    data = json.loads(PxService(tmp_path, {"px": {"api": live.base}}).data(refresh=True))
    assert data["mode"] == "public" and {p["id"] for p in data["projects"]} >= {"rc", "mc", "rb"}
    # API down: falls back to the local roadmap build, never an error page
    data = json.loads(PxService(tmp_path / "b", {"px": {"api": "http://127.0.0.1:9"}}).data(refresh=True))
    assert data["mode"] == "internal" and data["projects"]


def test_website_downloads_asks_the_api_first_then_the_channel_file(live):
    js = (REPO / "metallic-site" / "src" / "assets" / "downloads.js").read_text(encoding="utf-8")
    assert '"/api/v1/releases/" + channel' in js and '"/releases/channels/" + channel + ".json"' in js
    assert js.index("/api/v1/releases/") < js.index("/releases/channels/")
    op, params, _ = live.spec.match("GET", "/v1/releases/beta")
    assert op.op_id == "getRelease" and op.public
    code, h, body = live.call("GET", "/v1/releases/beta", origin="https://metallic.club")
    assert code == 200 and h["Access-Control-Allow-Origin"] == "*"
    assert body["components"][0]["size"] == len(b"MZ fake launcher 1.0.0")


# ---------------------------------------------------------------- Rec Room revivals
def _invite(online, members):
    return json.dumps({"approximate_presence_count": online, "approximate_member_count": members,
                       "guild": {"id": "42", "name": "G", "icon": "abc", "banner": None, "splash": "sp", "description": "d"}})


class FakeNet:
    """Discord invites answer `online` people (Vanilla 500); Vanilla's manifest answers with a version; RecFlare publishes
    `players` in game."""
    def __init__(self):
        self.calls, self.online, self.down, self.players = [], 10, False, 395

    def __call__(self, url, timeout=6.0):
        self.calls.append(url)
        if self.down:
            raise OSError("offline")
        if "discord.com" in url:
            return 200, _invite(500 if "vanillarec" in url else self.online, 900)
        if "vanillarec.net" in url:
            return 200, json.dumps({"version": "1.0.17"})
        if "recflare.net/api/stats/online" in url:
            return 200, json.dumps({"range": "24h", "online": self.players, "peak": 452})
        return 200, "{}"


@pytest.fixture
def rv(tmp_path):
    net = FakeNet()
    return Rig(tmp_path, {"revival_fetch": net}), net


def test_revivals_are_public_sorted_and_keep_discord_people_apart_from_players(rv):
    rig, _ = rv
    code, h, out = rig.call("GET", "/v1/revivals")                 # check_response validates the schema
    assert code == 200
    ids = [r["id"] for r in out["revivals"]]
    assert ids[0] == "vanilla" and {"stella", "meownet", "studio87", "uranium", "phoenix"} <= set(ids)
    assert "campus" not in ids and "studio8" not in ids
    by = {r["id"]: r for r in out["revivals"]}
    assert by["vanilla"]["status"] == "answering" and by["vanilla"]["version"] == "1.0.17"
    assert by["radium"]["status"] == "community" and by["uranium"]["status"] == "unknown" and by["uranium"]["discord"] is None
    assert by["radium"]["discord"]["icon"] == "https://cdn.discordapp.com/icons/42/abc.webp?size=128"
    with_invite = sum(1 for r in out["revivals"] if r["invite"])
    assert out["totals"]["online"] == 500 + 10 * (with_invite - 1) and out["totals"]["answering"] == 2        # Vanilla and RecFlare
    assert by["recflare"]["players"] == 395 and by["recflare"]["status"] == "answering"
    assert all(r["players"] is None for r in out["revivals"] if r["id"] != "recflare")   # Discord people are not players
    assert out["totals"]["in_game"] == 395 and out["totals"]["with_players"] == 1
    assert rig.call("GET", "/v1/revivals/radium")[2]["discord"]["online"] == 10
    assert rig.call("GET", "/v1/revivals/nope")[0] == 404


def test_revivals_ask_discord_at_most_every_two_minutes_and_keep_stale_numbers(rv):
    rig, net = rv
    rig.call("GET", "/v1/revivals")
    first = len(net.calls)
    rig.clock.t += 30
    rig.call("GET", "/v1/revivals")
    assert len(net.calls) == first                                  # nothing is due yet
    rig.clock.t += 31
    rig.call("GET", "/v1/revivals")
    assert all("discord.com" not in u for u in net.calls[first:])  # servers again after 1 min, Discord not yet
    net.down = True
    rig.clock.t += 120
    out = rig.call("GET", "/v1/revivals")[2]
    radium = next(r for r in out["revivals"] if r["id"] == "radium")
    assert radium["discord"]["online"] == 10 and radium["discord"]["stale"] is True
    assert next(r for r in out["revivals"] if r["id"] == "vanilla")["status"] == "not_answering"


def test_player_counts_are_read_by_path_sum_and_length():
    from metallic.api.revivals import count_at
    d = {"a": {"n": 7, "f": 3.0, "neg": -1, "b": True}, "rooms": [{"p": 2}, {"p": 5}, {"x": 1}], "list": [1, 2, 3]}
    assert [count_at(d, x) for x in ("a.n", "a.f", "a.neg", "a.b", "rooms.*.p", "rooms.*", "list", "rooms.1.p", "a.missing")] ==         [7, 3, None, None, 7, 3, 3, 5, None]
    assert count_at("text", "a") is None


def test_revival_samples_give_a_24_hour_trend_and_peak_and_expire_after_a_week(rv):
    rig, net = rv
    for online in (10, 40, 25):
        net.online = online
        rig.content.revivals.sample()
        rig.clock.t += 1800
    r = rig.call("GET", "/v1/revivals/radium")[2]
    assert [p[1] for p in r["trend"]] == [10, 40, 25]
    assert r["peak_24h"] == 40
    f = rig.call("GET", "/v1/revivals/recflare")[2]
    assert f["players_peak_24h"] == 395 and len(f["players_trend"]) >= 1
    rig.clock.t += 8 * 86400
    rig.content.revivals.sample()
    assert rig.store.one("SELECT COUNT(*) AS n FROM revival_samples WHERE t < ?", (rig.clock.t - 7 * 86400,))["n"] == 0
    assert rig.call("GET", "/v1/revivals/radium")[2]["peak_24h"] == 25   # only the newest sample is within a day
