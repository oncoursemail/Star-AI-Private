"""Metallic sign-in on the desktop (star/metallic_access.py): code -> token, local lockout, DPAPI file, expiry,
offline, sign-out, and the react_shell wiring. No network: a fake opener plays Metallic Control."""
from __future__ import annotations

import io
import json
import os
import urllib.error

import pytest

from star import metallic_access as ma
from star.metallic_access import MetallicAccess, normalize_url

URL = "http://metallic-control.test:8470"
CODE = "the-app-code-42"
TOKEN = "payload.signature"
ACCOUNT_TOKEN = "head.claims.sig"
ACCOUNTS = "https://accounts.test:8475"
FINGERPRINT = "ab" * 32
PASSWORD = "correct-horse-battery"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeVault:
    secure = True

    def __init__(self):
        self.seen = []

    def protect(self, data: bytes) -> bytes:
        self.seen.append(data)
        return b"V1" + bytes(b ^ 0x5A for b in data)

    def unprotect(self, data: bytes) -> bytes:
        if not data.startswith(b"V1"):
            raise OSError("not ours")
        return bytes(b ^ 0x5A for b in data[2:])


class Reply:
    def __init__(self, status, doc):
        self.status, self.data = status, json.dumps(doc).encode()

    def read(self, n=-1):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeControl:
    """Answers like metallic/metallic/control/server.py's /api/app/* routes."""

    def __init__(self, clock):
        self.clock, self.calls, self.down, self.revoked = clock, [], False, False
        self.state = {"machines": [{"id": "brain1", "cpu": 12}, {"id": "server3", "pending": "not yet"}]}

    def __call__(self, req, timeout):
        assert timeout <= 5
        body = json.loads(req.data) if req.data else None
        self.calls.append((req.get_method(), req.full_url, body, req.get_header("Authorization")))
        if self.down:
            raise urllib.error.URLError("connection refused")
        path = req.full_url[len(URL):]
        if path == "/api/app/verify" and "account_token" in body:
            if body["account_token"] != ACCOUNT_TOKEN:               # Control asks accounts; owner/admin roles only
                return self._error(401, {"ok": False, "text": "not an owner or admin account", "attempts_left": 4})
            return Reply(200, {"ok": True, "token": TOKEN, "expires_at": int(self.clock()) + 8 * 3600})
        if path == "/api/app/verify":
            if body.get("code") != CODE:
                return self._error(401, {"ok": False, "text": "that code is not right", "attempts_left": 4})
            return Reply(200, {"ok": True, "token": TOKEN, "expires_at": int(self.clock()) + 8 * 3600})
        if req.get_header("Authorization") != "Bearer " + TOKEN or self.revoked:
            return self._error(401, {"ok": False})
        if path == "/api/app/signout":
            self.revoked = True
            return Reply(200, {"ok": True})
        if path == "/api/app/state":
            return Reply(200, self.state)
        if path.startswith("/api/app/series?"):
            return Reply(200, {"range": "hour", "series": {"brain1.cpu": [[1, 2, 2, 2]]}})
        if path.startswith("/api/app/speed?"):
            return Reply(200, {"hours": []})
        return self._error(404, {"ok": False})

    def _error(self, code, doc):
        raise urllib.error.HTTPError(URL, code, "x", {}, io.BytesIO(json.dumps(doc).encode()))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.delenv(ma.ENV_URL, raising=False)
    clock = Clock()
    control = FakeControl(clock)
    vault = FakeVault()
    access = MetallicAccess(tmp_path, opener=control, vault=vault, clock=clock)
    return access, control, vault, clock, tmp_path


def all_bytes(root):
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


def test_urls_must_be_http_or_https_and_lose_the_trailing_slash(monkeypatch):
    assert normalize_url(URL + "/") == URL
    assert normalize_url("https://control.example/sub/") == "https://control.example/sub"
    for bad in ("", "ftp://x", "control.example", "http://user:pw@x", "http://x/?a=1", "http://x/#f", "http://",
                "javascript:alert(1)", "http://x:99999", 5, None):
        assert normalize_url(bad) == ""
    monkeypatch.setenv(ma.ENV_URL, "https://override.example/")
    assert MetallicAccess.control_url(URL) == "https://override.example"
    monkeypatch.setenv(ma.ENV_URL, "")
    assert MetallicAccess.control_url(URL) == URL


def test_not_configured(env):
    access, control, *_ = env
    assert access.status("") == {"signed_in": False, "expires_at": None, "configured": False, "control_url": "",
                                 "locked_until": None, "secure_store": True, "accounts_configured": False}
    res = access.sign_in(CODE, "")
    assert res["ok"] is False and res["error"] == "not_configured" and control.calls == []
    assert access.state("")["signed_in"] is False


def test_code_is_validated():
    for bad in ("", "x" * 257, 5, None, ["a"]):
        with pytest.raises(ValueError):
            ma.check_code(bad)
    assert ma.check_code("x" * 256)


def test_wrong_code_is_refused_then_locks_locally_like_the_server(env):
    access, control, _, clock, tmp = env
    res = access.sign_in("nope", URL)
    assert res == {"ok": False, "signed_in": False, "error": "wrong_code", "attempts_left": 4,
                   "message": "That code is not right."}
    for left in (3, 2, 1):
        assert access.sign_in("nope", URL)["attempts_left"] == left
    fifth = access.sign_in("nope", URL)
    assert fifth["attempts_left"] == 0 and fifth["locked_until"] == clock.t + 900
    calls = len(control.calls)
    locked = access.sign_in(CODE, URL)                                     # the right code, but locked: no request
    assert locked["error"] == "locked" and locked["locked_until"] == clock.t + 900 and len(control.calls) == calls
    assert access.status(URL)["locked_until"] == clock.t + 900
    assert not (tmp / ma.TOKEN_FILE).exists()
    clock.t += 901
    assert access.sign_in(CODE, URL)["ok"] is True and access.status(URL)["locked_until"] is None


def test_server_429_sets_the_local_lock(env):
    access, control, _, clock, _ = env

    def locked(req, timeout):
        raise urllib.error.HTTPError(URL, 429, "x", {}, io.BytesIO(b'{"ok":false,"retry_after":120}'))
    access.open = locked
    res = access.sign_in(CODE, URL)
    assert res["error"] == "locked" and res["locked_until"] == clock.t + 120


def test_right_code_stores_an_encrypted_token_and_never_the_code(env):
    access, control, vault, clock, tmp = env
    res = access.sign_in(CODE, URL)
    assert res == {"ok": True, "signed_in": True, "expires_at": int(clock.t) + 8 * 3600,
                   "message": "Signed in to Metallic."}
    status = access.status(URL)
    assert status["signed_in"] is True and status["expires_at"] == int(clock.t) + 8 * 3600
    assert status["configured"] is True and status["control_url"] == URL and status["secure_store"] is True
    stored = (tmp / ma.TOKEN_FILE).read_bytes()
    assert TOKEN.encode() not in stored                                     # encrypted at rest
    assert CODE.encode() not in all_bytes(tmp) and all(CODE.encode() not in d for d in vault.seen)
    assert control.calls[0][2] == {"code": CODE} and control.calls[0][3] is None
    # a fresh object (a restart) reads the same file
    again = MetallicAccess(tmp, opener=control, vault=vault, clock=clock)
    assert again.status(URL)["signed_in"] is True
    # the token is never sent to another address
    assert again.status("http://elsewhere.test")["signed_in"] is False
    assert not (tmp / ma.TOKEN_FILE).exists()


def test_expiry_hides_the_session_and_removes_the_file(env):
    access, _, _, clock, tmp = env
    access.sign_in(CODE, URL)
    clock.t += 8 * 3600
    assert access.status(URL)["signed_in"] is False and access.status(URL)["expires_at"] is None
    assert not (tmp / ma.TOKEN_FILE).exists()


def test_state_reads_state_series_and_speed_with_the_bearer_token(env):
    access, control, *_ = env
    access.sign_in(CODE, URL)
    res = access.state(URL, "day")
    assert res["reachable"] is True and res["signed_in"] is True
    assert res["state"]["machines"][0]["id"] == "brain1" and res["speed"] == {"hours": []}
    assert res["series"]["series"]["brain1.cpu"] == [[1, 2, 2, 2]]
    urls = [c[1] for c in control.calls[1:]]
    assert urls[0] == URL + "/api/app/state"
    assert urls[1] == URL + "/api/app/series?keys=brain1.cpu%2Cbrain1.mem_pct&range=day"   # pending machines skipped
    assert urls[2] == URL + "/api/app/speed?days=1"
    assert all(c[3] == "Bearer " + TOKEN for c in control.calls[1:])


def test_offline_keeps_the_session_and_says_unreachable(env):
    access, control, _, _, tmp = env
    access.sign_in(CODE, URL)
    control.down = True
    res = access.state(URL)
    assert res["reachable"] is False and res["signed_in"] is True and (tmp / ma.TOKEN_FILE).exists()
    assert access.sign_in(CODE, URL)["error"] == "unreachable"

    def timeout(req, timeout):
        raise TimeoutError("timed out")
    access.open = timeout
    assert access.state(URL)["reachable"] is False


def test_a_401_on_state_signs_out_as_expired(env):
    access, control, _, _, tmp = env
    access.sign_in(CODE, URL)
    control.revoked = True                                               # e.g. the server restarted
    res = access.state(URL)
    assert res == {"reachable": True, "signed_in": False, "expired": True,
                   "message": "Your Metallic sign-in ended. Sign in again."}
    assert not (tmp / ma.TOKEN_FILE).exists()


def test_bad_reply(env):
    access, *_ = env
    access.open = lambda req, timeout: Reply(200, {"ok": True})            # no token
    assert access.sign_in(CODE, URL)["error"] == "bad_reply"


def test_sign_out_deletes_the_file_and_revokes_on_the_server(env):
    access, control, _, _, tmp = env
    access.sign_in(CODE, URL)
    status = access.sign_out(URL)
    assert status["signed_in"] is False and not (tmp / ma.TOKEN_FILE).exists()
    for _ in range(200):                                                  # the revoke runs in a thread
        if control.revoked:
            break
        import time
        time.sleep(0.01)
    assert control.revoked and control.calls[-1][1] == URL + "/api/app/signout"


def test_without_dpapi_the_session_lives_in_memory_only(tmp_path, monkeypatch):
    monkeypatch.delenv(ma.ENV_URL, raising=False)
    clock = Clock()
    access = MetallicAccess(tmp_path, opener=FakeControl(clock), vault=None, clock=clock)
    assert access.sign_in(CODE, URL)["ok"] is True
    assert access.status(URL)["signed_in"] is True and access.status(URL)["secure_store"] is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_real_dpapi_round_trip():
    vault = ma.DpapiVault()
    secret = b'{"token":"abc","expires_at":1}'
    sealed = vault.protect(secret)
    assert sealed != secret and b"abc" not in sealed
    assert vault.unprotect(sealed) == secret
    with pytest.raises(OSError):
        vault.unprotect(b"not a dpapi blob")


def test_react_shell_allows_the_four_actions_and_the_url_setting():
    from star.desktop_core import Settings
    from star.react_shell import ALLOWED_ACTIONS, PERMITTED_SETTINGS
    assert {"metallicStatus", "metallicSignIn", "metallicSignOut", "metallicState",
            "metallicAccountSignIn"} <= ALLOWED_ACTIONS
    assert {"metallic_control_url", "metallic_accounts_url", "metallic_accounts_fingerprint"} <= PERMITTED_SETTINGS
    assert Settings().metallic_control_url == "" and Settings().metallic_accounts_url == ""
    Settings(metallic_control_url=URL).validate()
    Settings(metallic_accounts_url=ACCOUNTS, metallic_accounts_fingerprint=FINGERPRINT.upper()).validate()
    for bad in ({"metallic_control_url": "ftp://x"}, {"metallic_accounts_url": "http://accounts.test:8475"},
                {"metallic_accounts_url": "accounts.test"}, {"metallic_accounts_fingerprint": "abc"},
                {"metallic_accounts_fingerprint": "zz" * 32}):
        with pytest.raises(ValueError):
            Settings(**bad).validate()


def test_bootstrap_status_never_raises(tmp_path, monkeypatch):
    monkeypatch.delenv(ma.ENV_URL, raising=False)
    status = ma.status_for(tmp_path / "home", URL)
    assert status["configured"] is True and status["signed_in"] is False
    assert ma.for_home(tmp_path / "home") is ma.for_home(tmp_path / "home")
    assert set(status) == {"signed_in", "expires_at", "configured", "control_url", "locked_until", "secure_store",
                           "accounts_configured"}


# ---------------------------------------------------------------- Metallic account sign-in (one account system)
class FakeAccounts:
    """Answers like metallic/metallic/accounts/server.py: POST /v1/login (password, 2FA) and /v1/logout."""

    def __init__(self, *, otp=False):
        self.calls, self.otp, self.down, self.cert_ok, self.status_override = [], otp, False, True, None

    def __call__(self, base, fingerprint, path, body, token, timeout):
        self.calls.append((base, fingerprint, path, body, token))
        if self.down:
            raise ma._Unreachable()
        if not self.cert_ok:
            raise ma._BadCertificate()
        if self.status_override:
            return self.status_override
        if path == "/v1/logout":
            return 200, {"ok": True}
        assert path == "/v1/login"
        if body["username"] != "alex" or body["password"] != PASSWORD:
            return 401, {"ok": False, "error": "wrong_login", "text": "Wrong username or password."}
        if self.otp:
            if "otp" not in body and "recovery_code" not in body:
                return 401, {"ok": False, "error": "otp_required", "text": "Enter the 6-digit code."}
            if body.get("otp", "123456") != "123456" or body.get("recovery_code", "rc-1") != "rc-1":
                return 401, {"ok": False, "error": "wrong_code", "text": "That code is not right."}
        return 200, {"access_token": ACCOUNT_TOKEN, "refresh_token": "rt.ses.secret", "expires_in": 900,
                     "account": {"username": "alex", "role": "owner"}}


def login(**extra):
    return {"username": "alex", "password": PASSWORD, **extra}


def account_env(env, **kw):
    access, control, vault, clock, tmp = env
    accounts = FakeAccounts(**kw)
    access.account_post = accounts
    return access, control, accounts, vault, clock, tmp


def end_account_sessions():
    import threading
    for thread in threading.enumerate():
        if thread.name == "metallic-account-logout":
            thread.join(5)


def test_account_login_gives_control_the_token_and_the_password_goes_nowhere_else(env, monkeypatch):
    monkeypatch.delenv(ma.ENV_ACCOUNTS_URL, raising=False)
    monkeypatch.delenv(ma.ENV_ACCOUNTS_FINGERPRINT, raising=False)
    access, control, accounts, vault, clock, tmp = account_env(env)
    res = access.sign_in_account(login(), URL, ACCOUNTS, FINGERPRINT.upper())
    assert res == {"ok": True, "signed_in": True, "expires_at": int(clock.t) + 8 * 3600,
                   "message": "Signed in to Metallic."}
    assert access.status(URL, ACCOUNTS)["signed_in"] is True
    end_account_sessions()
    # accounts saw the password, pinned with the lower-case fingerprint, over the login route only
    base, pin, path, body, token = accounts.calls[0]
    assert (base, pin, path, token) == (ACCOUNTS, FINGERPRINT, "/v1/login", None) and body["password"] == PASSWORD
    # Control saw the account access token and no password
    assert control.calls[0][2] == {"account_token": ACCOUNT_TOKEN}
    assert PASSWORD.encode() not in json.dumps(control.calls).encode()
    # nothing but Control's token is stored: no password, no account token, no account refresh token
    stored = all_bytes(tmp)
    assert all(x.encode() not in stored and all(x.encode() not in d for d in vault.seen)
               for x in (PASSWORD, ACCOUNT_TOKEN, "rt.ses.secret"))
    # the account session was ended again (best effort)
    assert accounts.calls[-1][2:] == ("/v1/logout", {"everywhere": False}, ACCOUNT_TOKEN)


def test_account_login_with_two_factor_asks_for_the_code_then_accepts_it_or_a_recovery_code(env):
    access, control, accounts, *_ = account_env(env, otp=True)
    first = access.sign_in_account(login(), URL, ACCOUNTS)
    assert first["error"] == "otp_required" and control.calls == []            # Control is not asked yet
    wrong = access.sign_in_account(login(otp="000000"), URL, ACCOUNTS)
    assert wrong["error"] == "wrong_code" and control.calls == []
    ok = access.sign_in_account(login(otp="123456"), URL, ACCOUNTS)
    assert ok["ok"] is True
    access.sign_out(URL)
    assert access.sign_in_account(login(recovery_code="rc-1"), URL, ACCOUNTS)["ok"] is True
    end_account_sessions()


def test_account_refusals_are_results_not_exceptions(env):
    access, control, accounts, _, clock, _ = account_env(env)
    bad = access.sign_in_account({"username": "alex", "password": "nope-nope-nope"}, URL, ACCOUNTS)
    assert bad["error"] == "wrong_login" and bad["ok"] is False and control.calls == []
    accounts.status_override = (429, {"ok": False, "error": "locked", "retry_after": 600})
    locked = access.sign_in_account(login(), URL, ACCOUNTS)
    assert locked["error"] == "account_locked" and locked["locked_until"] == clock.t + 600
    accounts.status_override = (403, {"ok": False, "error": "disabled"})
    assert access.sign_in_account(login(), URL, ACCOUNTS)["error"] == "disabled"
    accounts.status_override = (500, None)
    assert access.sign_in_account(login(), URL, ACCOUNTS)["error"] == "bad_reply"
    accounts.status_override = (200, {"access_token": "not-a-jwt"})              # never forwarded as a token
    assert access.sign_in_account(login(), URL, ACCOUNTS)["error"] == "bad_reply" and control.calls == []
    accounts.status_override = None
    accounts.down = True
    assert access.sign_in_account(login(), URL, ACCOUNTS)["error"] == "accounts_unreachable"
    accounts.down, accounts.cert_ok = False, False
    assert access.sign_in_account(login(), URL, ACCOUNTS, FINGERPRINT)["error"] == "bad_certificate"
    assert access.status(URL, ACCOUNTS)["signed_in"] is False and control.calls == []


def test_account_login_needs_both_addresses_an_https_accounts_url_and_a_valid_fingerprint(env, monkeypatch):
    monkeypatch.delenv(ma.ENV_ACCOUNTS_URL, raising=False)
    monkeypatch.delenv(ma.ENV_ACCOUNTS_FINGERPRINT, raising=False)
    access, control, accounts, *_ = account_env(env)
    assert access.sign_in_account(login(), "", ACCOUNTS)["error"] == "not_configured"
    assert access.sign_in_account(login(), URL, "")["error"] == "accounts_not_configured"
    assert access.sign_in_account(login(), URL, "http://accounts.test:8475")["error"] == "accounts_not_configured"
    assert access.sign_in_account(login(), URL, ACCOUNTS, "not-a-fingerprint")["error"] == "bad_certificate"
    assert accounts.calls == [] and control.calls == []                        # the password never left
    assert access.status(URL, ACCOUNTS)["accounts_configured"] is True
    assert access.status(URL, "http://accounts.test")["accounts_configured"] is False
    monkeypatch.setenv(ma.ENV_ACCOUNTS_URL, "https://override.test")
    assert access.status(URL, "")["accounts_configured"] is True
    monkeypatch.setenv(ma.ENV_ACCOUNTS_FINGERPRINT, FINGERPRINT)
    access.sign_in_account(login(), URL, "")
    assert accounts.calls[0][:2] == ("https://override.test", FINGERPRINT)


def test_an_account_control_refuses_counts_toward_the_same_lockout_as_a_wrong_code(env):
    access, control, accounts, _, clock, tmp = account_env(env)
    access.account_post = FakeAccounts()
    real = access.account_post

    def other_role(base, fp, path, body, token, timeout):         # a valid account whose token Control rejects
        out = real(base, fp, path, body, token, timeout)
        return (200, {**out[1], "access_token": "head.other.sig"}) if path == "/v1/login" else out
    access.account_post = other_role
    first = access.sign_in_account(login(), URL, ACCOUNTS)
    assert first["error"] == "not_allowed" and first["attempts_left"] == 4 and "owner or admin" in first["message"]
    for _ in range(3):
        access.sign_in_account(login(), URL, ACCOUNTS)
    fifth = access.sign_in_account(login(), URL, ACCOUNTS)
    assert fifth["attempts_left"] == 0 and fifth["locked_until"] == clock.t + 900
    calls = len(control.calls)
    assert access.sign_in_account(login(), URL, ACCOUNTS)["error"] == "locked" and len(control.calls) == calls
    assert not (tmp / ma.TOKEN_FILE).exists()
    end_account_sessions()


def test_account_login_payload_is_checked():
    assert ma.check_account_login({"username": "alex", "password": "pw", "otp": " 123456 "}) == {
        "username": "alex", "password": "pw", "otp": "123456"}
    assert ma.check_account_login({"username": "a", "password": "p", "otp": "", "recovery_code": None}) == {
        "username": "a", "password": "p"}
    for bad in (None, [], {}, {"username": "a"}, {"username": "", "password": "p"}, {"username": "a" * 65, "password": "p"},
                {"username": "a", "password": "p" * 129}, {"username": "a", "password": 5},
                {"username": "a", "password": "p", "otp": 5}, {"username": "a", "password": "p", "otp": "1" * 65},
                {"username": "a", "password": "p", "otp": "1", "recovery_code": "2"}):
        with pytest.raises(ValueError):
            ma.check_account_login(bad)


def _self_signed(tmp_path):
    import datetime
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "metallic-accounts.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    pem, keyfile = tmp_path / "cert.pem", tmp_path / "key.pem"
    pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    import hashlib
    return pem, keyfile, hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def test_pinned_post_trusts_only_the_pinned_certificate_over_real_tls(tmp_path):
    pytest.importorskip("cryptography")
    import http.server
    import ssl
    import threading
    pem, keyfile, fingerprint = _self_signed(tmp_path)
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                         self.headers.get("Authorization"), self.headers.get("Origin")))
            body = b'{"access_token":"a.b.c"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(pem), str(keyfile))
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"https://127.0.0.1:{server.server_address[1]}"
    try:
        status, doc = ma.pinned_post(base, fingerprint, "/v1/login", {"username": "alex"}, None, 5)
        assert (status, doc) == (200, {"access_token": "a.b.c"})
        assert seen == [("/v1/login", {"username": "alex"}, None, None)]       # no Origin header, no token
        ma.pinned_post(base + "/", fingerprint, "/v1/logout", {}, "tok", 5)
        assert seen[-1][2] == "Bearer tok"
        with pytest.raises(ma._BadCertificate):
            ma.pinned_post(base, "00" * 32, "/v1/login", {"username": "alex"}, None, 5)
        assert len(seen) == 2                                                  # a wrong pin sent nothing
        with pytest.raises(ma._Unreachable):                                   # self-signed and no pin: CA check fails
            ma.pinned_post(base, "", "/v1/login", {"username": "alex"}, None, 5)
    finally:
        server.shutdown()
        server.server_close()
    with pytest.raises(ma._Unreachable):
        ma.pinned_post(base, fingerprint, "/v1/login", {}, None, 2)
