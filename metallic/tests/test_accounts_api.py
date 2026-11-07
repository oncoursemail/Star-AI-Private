"""Metallic accounts over real HTTPS (self-signed cert, pinned fingerprint) with the stdlib client the launcher uses."""
from __future__ import annotations

import datetime
import hashlib
import http.client
import json
import os
import ssl

import pytest

pytest.importorskip("argon2")
pytest.importorskip("cryptography")

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from metallic.accounts import crypto, runtime  # noqa: E402
from metallic.accounts.client import AccountsClient, AccountsError, TokenStore  # noqa: E402
from metallic.accounts.server import App, serve  # noqa: E402

PW = "silver-titanium-crow-9"


@pytest.fixture(autouse=True)
def cheap_hashing():
    saved = crypto._HASHER, crypto._DUMMY_HASH
    crypto.set_cost(1, 1024)
    yield
    crypto._HASHER, crypto._DUMMY_HASH = saved


def _self_signed(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "metallic-accounts")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    (tmp_path / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                         serialization.PrivateFormat.PKCS8,
                                                         serialization.NoEncryption()))
    fp = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return str(tmp_path / "cert.pem"), str(tmp_path / "key.pem"), fp


@pytest.fixture
def live(tmp_path):
    runtime.init_keys(tmp_path / "keys")
    accounts, store = runtime.build({"key_dir": str(tmp_path / "keys"), "db": str(tmp_path / "a.sqlite3"),
                                     "audit_file": str(tmp_path / "audit.jsonl")})
    cert, key, fp = _self_signed(tmp_path)
    from metallic.accounts.federation import Federation
    fed = Federation(accounts, {"steam": {"enabled": True}}, rp_id="localhost", origins=("http://localhost:47615",))
    server = serve(App(accounts, federation=fed), "127.0.0.1", 0, (cert, key))
    port = server.server_address[1]
    yield accounts, f"https://127.0.0.1:{port}", fp, port
    server.shutdown()
    server.server_close()
    store.db.close()


def client(live, name="t"):
    _, url, fp, _ = live
    return AccountsClient(url, fingerprint=fp, store=TokenStore(None))


def raw(port, method, path, body=None, headers=None):
    ctx = ssl._create_unverified_context()
    conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=5)
    conn.request(method, path, json.dumps(body).encode() if body is not None else None, headers or {})
    r = conn.getresponse()
    out = r.status, dict(r.getheaders()), json.loads(r.read() or b"{}")
    conn.close()
    return out


def test_full_social_flow_over_https(live):
    a, b = client(live), client(live)
    reg = a.register("alexa", PW, "adult")
    assert len(reg["recovery_codes"]) == 10
    b.register("bobby", PW, "adult")
    assert a.health()["ok"] and a.me()["username"] == "alexa"
    a.friend("request", "bobby")
    assert [x["username"] for x in b.friends()["incoming"]] == ["alexa"]
    b.friend("accept", "alexa")
    a.set_presence("playing", game="RC", detail="Rec Center", joinable=True)
    assert b.presence() == [{"username": "alexa", "presence": {"status": "playing", "game": "RC",
                                                                "detail": "Rec Center", "joinable": True}}]
    inv = a.invite("bobby", "RC", "room-rec-center")
    incoming = b.invites()["incoming"]
    assert incoming[0]["id"] == inv["id"] and incoming[0]["from"] == "alexa"
    assert b.answer_invite(inv["id"], True)["target"] == "room-rec-center"
    assert a.news() == []


def test_jwks_lets_another_service_verify_offline(live):
    accounts, *_ = live
    c = client(live)
    c.register("verifier", PW, "teen")
    claims = crypto.verify_jwt(c.access_token(), c.jwks())
    assert claims["name"] == "verifier" and claims["minor"] is True and claims["role"] == "user"


def test_pinned_fingerprint_mismatch_refuses(live):
    _, url, _, _ = live
    bad = AccountsClient(url, fingerprint="00" * 32, store=TokenStore(None))
    with pytest.raises(AccountsError) as e:
        bad.health()
    assert e.value.code == "bad_certificate"


def test_unreachable_is_a_plain_error():
    c = AccountsClient("https://127.0.0.1:9", fingerprint="00" * 32, timeout=1)
    with pytest.raises(AccountsError) as e:
        c.health()
    assert e.value.code == "unreachable"


def test_client_refreshes_after_access_expiry_and_signs_out_on_reuse(live):
    accounts, url, fp, _ = live
    c = client(live)
    c.register("refresher", PW, "adult")
    first_refresh = c.store.load()
    c.access_exp = 0                                    # pretend the access token expired
    assert c.me()["username"] == "refresher"
    assert c.store.load() != first_refresh              # rotated
    thief = AccountsClient(url, fingerprint=fp, store=TokenStore(None))
    thief.store.save(first_refresh)
    with pytest.raises(AccountsError):
        thief.me()                                      # old token: session revoked
    c.access = None
    with pytest.raises(AccountsError) as e:
        c.me()
    assert e.value.status == 401 and not c.signed_in    # the real client is signed out too (safe failure)


def test_login_lockout_and_otp_required_over_https(live):
    accounts, *_ = live
    c = client(live)
    c.register("lockme", PW, "adult")
    secret = c.totp_setup(PW)["secret"]
    import time
    c.totp_confirm(crypto.totp_code(secret, int(time.time() // 30)))
    d = client(live)
    with pytest.raises(AccountsError) as e:
        d.login("lockme", PW)
    assert e.value.code == "otp_required"
    for _ in range(4):
        with pytest.raises(AccountsError):
            d.login("lockme", "wrong-wrong-wrong")
    with pytest.raises(AccountsError):
        d.login("lockme", "wrong-wrong-wrong")
    with pytest.raises(AccountsError) as e:
        d.login("lockme", PW, otp="000000")
    assert e.value.status == 429 and e.value.code in ("locked", "slow_down")


def test_ip_rate_limit_on_auth_routes(live):
    port = live[3]
    codes = [raw(port, "POST", "/v1/login", {"username": "x", "password": "y"},
                 {"Content-Type": "application/json"})[0] for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    status, headers, body = raw(port, "POST", "/v1/login", {"username": "x", "password": "y"},
                                {"Content-Type": "application/json"})
    assert status == 429 and int(headers["Retry-After"]) >= 1 and body["error"] == "slow_down"


def test_browser_origin_and_non_json_refused_and_headers(live):
    port = live[3]
    status, _, body = raw(port, "GET", "/v1/news", headers={"Origin": "http://evil.example"})
    assert status == 403 and body["error"] == "browser_refused"
    status, _, _ = raw(port, "POST", "/v1/login", {"username": "x"}, {"Content-Type": "text/plain"})
    assert status == 415
    status, headers, _ = raw(port, "GET", "/health")
    assert status == 200 and headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    status, _, body = raw(port, "GET", "/v1/friends")
    assert status == 401 and body["error"] == "signed_out"


def test_plain_http_is_refused_by_runtime(tmp_path):
    runtime.init_keys(tmp_path / "k")
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'key_dir = "{(tmp_path / "k").as_posix()}"\ndb = "{(tmp_path / "x.db").as_posix()}"\n')
    assert runtime.run(str(cfg)) == 2


def test_dpapi_store_roundtrip(tmp_path):
    if os.name != "nt":
        pytest.skip("DPAPI is Windows only")
    s = TokenStore(tmp_path / "refresh.bin")
    s.save("rt.ses_abc.secret-value")
    assert b"secret-value" not in (tmp_path / "refresh.bin").read_bytes()
    assert TokenStore(tmp_path / "refresh.bin").load() == "rt.ses_abc.secret-value"
    s.save(None)
    assert not (tmp_path / "refresh.bin").exists()


def test_account_link_accepts_owner_only_and_sees_sign_out(live):
    from metallic.accounts.link import AccountLink
    accounts, url, fp, _ = live
    link = AccountLink(url, fingerprint=fp)
    user = client(live)
    user.register("plainjoe", PW, "adult")
    owner = client(live)
    owner.register("bossy", PW, "adult", owner_code=accounts.new_owner_code())
    assert link.verify(user.access_token(), roles=("owner", "admin")) is None
    who = link.verify(owner.access_token(), roles=("owner", "admin"))
    assert who["name"] == "bossy" and who["role"] == "owner"
    token = owner.access_token()
    owner.logout()
    assert link.verify(token, roles=("owner",)) is None          # sign-out applies at once
    assert link.verify("not-a-token") is None
    assert AccountLink("https://127.0.0.1:9", fingerprint=fp, timeout=1).verify(token) is None


def test_passkey_and_providers_over_https(live):
    from test_accounts_federation import SoftKey
    c = client(live)
    c.register("haspasskey", PW, "adult")
    assert c.providers()["providers"] == [{"id": "steam", "name": "Steam"}]
    key = SoftKey()
    opts = c.passkey_register_options()
    assert c.passkey_register_finish(opts["flow"], key.create(opts), "Hello")["passkeys"][0]["name"] == "Hello"
    sub = c.me()["id"]
    d = client(live)
    lo = d.passkey_login_options()
    assert d.passkey_login_finish(lo["flow"], key.get(lo, sub))["username"] == "haspasskey"
    assert d.methods()["password"] is True and len(d.methods()["passkeys"]) == 1
    with pytest.raises(AccountsError) as e:
        d.steam_start("https://evil.example/callback")
    assert e.value.code == "bad_redirect"
