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
                                 "locked_until": None, "secure_store": True}
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
    assert {"metallicStatus", "metallicSignIn", "metallicSignOut", "metallicState"} <= ALLOWED_ACTIONS
    assert "metallic_control_url" in PERMITTED_SETTINGS
    assert Settings().metallic_control_url == ""
    Settings(metallic_control_url=URL).validate()
    with pytest.raises(ValueError):
        Settings(metallic_control_url="ftp://x").validate()


def test_bootstrap_status_never_raises(tmp_path, monkeypatch):
    monkeypatch.delenv(ma.ENV_URL, raising=False)
    status = ma.status_for(tmp_path / "home", URL)
    assert status["configured"] is True and status["signed_in"] is False
    assert ma.for_home(tmp_path / "home") is ma.for_home(tmp_path / "home")
    assert set(status) == {"signed_in", "expires_at", "configured", "control_url", "locked_until", "secure_store"}
