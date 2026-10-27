"""Metallic sign-in for STAR Desktop: the app code goes to Metallic Control once, its token is kept per Windows user.

Bridge actions (star/react_shell.py, docs/agents/ui-2-20261026.md "Contract: desktop bridge actions"):
    metallicStatus  -> {signed_in, expires_at, configured, control_url, locked_until, secure_store}
    metallicSignIn  {code} -> {ok, signed_in, expires_at?, error?, message, attempts_left?, locked_until?}
    metallicSignOut -> status (token file deleted; the server revoke is best effort, in a thread)
    metallicState   {range?} -> {reachable, signed_in, expired?, message?, state?, speed?, series?}

Times (expires_at, locked_until) are unix seconds. Expected failures (wrong code, lockout, offline, not configured, a
reply that makes no sense) are result dicts, not exceptions. The code is never stored or logged; the token is kept
in `<app data>/metallic_session.bin`, encrypted with Windows DPAPI for the current user, or only in memory where DPAPI
is missing (`secure_store: false`). A token is only ever sent to the control URL it was issued by.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_FILE = 'metallic_session.bin'
ENV_URL = 'STAR_METALLIC_CONTROL_URL'
FAIL_WINDOW = 900
FAIL_MAX = 5
TIMEOUT = 4.0
MAX_REPLY = 4_000_000
RANGES = ('hour', 'day', 'week')
KEY_RE = re.compile(r'[A-Za-z0-9._:-]{1,120}')
METALLIC_ACTIONS = frozenset({'metallicStatus', 'metallicSignIn', 'metallicSignOut', 'metallicState'})


def normalize_url(raw) -> str:
    """An http(s) base URL without a trailing slash, or '' when `raw` is not one (no credentials, query or fragment)."""
    if not isinstance(raw, str):
        return ''
    text = raw.strip().rstrip('/')
    try:
        parts = urllib.parse.urlsplit(text)
        parts.port  # noqa: B018  (raises ValueError on a bad port)
    except ValueError:
        return ''
    if parts.scheme not in ('http', 'https') or not parts.hostname or '@' in parts.netloc:
        return ''
    if parts.query or parts.fragment or any(c.isspace() for c in text):
        return ''
    return text


def check_code(code) -> str:
    if not isinstance(code, str) or not 1 <= len(code) <= 256:
        raise ValueError('Enter the Metallic code (1 to 256 characters)')
    return code


class DpapiVault:
    """Windows DPAPI for the current user (CryptProtectData with CRYPTPROTECT_UI_FORBIDDEN)."""
    secure = True
    UI_FORBIDDEN = 0x1

    class _Blob(ctypes.Structure):
        _fields_ = [('cbData', ctypes.c_uint32), ('pbData', ctypes.POINTER(ctypes.c_char))]

    def __init__(self):
        from ctypes import wintypes
        self._crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        blob = ctypes.POINTER(self._Blob)
        for name in ('CryptProtectData', 'CryptUnprotectData'):
            fn = getattr(self._crypt, name)
            fn.argtypes = [blob, wintypes.LPCWSTR if name == 'CryptProtectData' else ctypes.c_void_p, blob,
                           ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob]
            fn.restype = wintypes.BOOL
        self._kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel.LocalFree.restype = ctypes.c_void_p

    def _call(self, fn, data: bytes, describe) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))
        src = self._Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        out = self._Blob()
        if not fn(ctypes.byref(src), describe, None, None, None, self.UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError(ctypes.get_last_error(), 'Windows could not protect or read the Metallic session')
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            self._kernel.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))

    def protect(self, data: bytes) -> bytes:
        return self._call(self._crypt.CryptProtectData, data, 'STAR Metallic session')

    def unprotect(self, data: bytes) -> bytes:
        return self._call(self._crypt.CryptUnprotectData, data, None)


def default_vault():
    if os.name != 'nt':
        return None
    try:
        return DpapiVault()
    except (OSError, AttributeError):
        return None


class _Unreachable(Exception):
    pass


class MetallicAccess:
    """One per app data folder (use `for_home`): the bootstrap and the bridge must see the same memory state."""

    def __init__(self, home: Path, *, opener=None, vault='default', clock=time.time, timeout: float = TIMEOUT):
        self.file = Path(home) / TOKEN_FILE
        self.open = opener or urllib.request.urlopen
        self.vault = default_vault() if vault == 'default' else vault
        self.clock, self.timeout = clock, timeout
        self.lock = threading.Lock()
        self.fails: list[float] = []
        self.locked_until: float = 0.0       # set from a server 429 retry_after
        self.memory: dict | None = None      # the session when there is no DPAPI

    # ---------------------------------------------------------------- settings and stored session
    @staticmethod
    def control_url(setting: str = '') -> str:
        env = os.environ.get(ENV_URL)
        return normalize_url(env if env else setting)

    def _lock_until(self) -> float | None:
        now = self.clock()
        with self.lock:
            self.fails = [t for t in self.fails if now - t < FAIL_WINDOW]
            until = self.locked_until if self.locked_until > now else 0.0
            if len(self.fails) >= FAIL_MAX:
                until = max(until, self.fails[-FAIL_MAX] + FAIL_WINDOW)
        return until or None

    def _save(self, session: dict) -> None:
        if self.vault is None:
            self.memory = session
            return
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix('.tmp')
        tmp.write_bytes(self.vault.protect(json.dumps(session).encode('utf-8')))
        os.replace(tmp, self.file)

    def _forget(self) -> None:
        self.memory = None
        try:
            self.file.unlink()
        except FileNotFoundError:
            pass

    def _session(self, url: str) -> dict | None:
        """The stored session for `url`; an expired, unreadable or other-URL one is deleted."""
        if self.vault is None:
            session = self.memory
        else:
            try:
                session = json.loads(self.vault.unprotect(self.file.read_bytes()))
            except FileNotFoundError:
                return None
            except (OSError, ValueError):
                session = None
        ok = (isinstance(session, dict) and isinstance(session.get('token'), str)
              and isinstance(session.get('expires_at'), (int, float)) and session['expires_at'] > self.clock()
              and session.get('control_url') == url and url)
        if not ok:
            self._forget()
            return None
        return session

    def status(self, setting: str = '') -> dict:
        url = self.control_url(setting)
        session = self._session(url) if url else None
        return {'signed_in': session is not None, 'expires_at': session['expires_at'] if session else None,
                'configured': bool(url), 'control_url': url, 'locked_until': self._lock_until(),
                'secure_store': self.vault is not None}

    # ---------------------------------------------------------------- HTTP
    def _request(self, method: str, url: str, body: dict | None = None, token: str | None = None):
        """(status, JSON object or None). Raises _Unreachable when the server cannot be reached."""
        headers = {'Accept': 'application/json'}
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.open(req, timeout=self.timeout) as reply:
                status, raw = reply.status, reply.read(MAX_REPLY)
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                raw = exc.read(MAX_REPLY)
            except OSError:
                raw = b''
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise _Unreachable() from None
        try:
            doc = json.loads(raw or b'null')
        except ValueError:
            doc = None
        return status, doc

    # ---------------------------------------------------------------- actions
    def sign_in(self, code, setting: str = '') -> dict:
        check_code(code)
        url = self.control_url(setting)
        if not url:
            return {'ok': False, 'signed_in': False, 'error': 'not_configured',
                    'message': 'Set the Metallic Control address in Settings first.'}
        until = self._lock_until()
        if until:
            return {'ok': False, 'signed_in': False, 'error': 'locked', 'locked_until': until,
                    'message': 'Too many wrong codes. Wait, then try again.'}
        try:
            status, doc = self._request('POST', url + '/api/app/verify', {'code': code})
        except _Unreachable:
            return {'ok': False, 'signed_in': False, 'error': 'unreachable',
                    'message': 'Metallic Control did not answer. Check the address and that it is running.'}
        doc = doc if isinstance(doc, dict) else {}
        if (status == 200 and doc.get('ok') is True and isinstance(doc.get('token'), str) and doc['token']
                and isinstance(doc.get('expires_at'), (int, float)) and doc['expires_at'] > self.clock()):
            with self.lock:
                self.fails.clear()
                self.locked_until = 0.0
            self._save({'token': doc['token'], 'expires_at': doc['expires_at'], 'control_url': url})
            return {'ok': True, 'signed_in': True, 'expires_at': doc['expires_at'], 'message': 'Signed in to Metallic.'}
        if status == 401:
            now = self.clock()
            with self.lock:
                self.fails = [t for t in self.fails if now - t < FAIL_WINDOW] + [now]
                left = max(0, FAIL_MAX - len(self.fails))
            server_left = doc.get('attempts_left')
            if type(server_left) is int:
                left = max(0, min(left, server_left))
            result = {'ok': False, 'signed_in': False, 'error': 'wrong_code', 'attempts_left': left,
                      'message': 'That code is not right.'}
            if left == 0:
                with self.lock:
                    self.locked_until = max(self.locked_until, self.clock() + FAIL_WINDOW)
                result['locked_until'] = self._lock_until()
            return result
        if status == 429:
            wait = doc.get('retry_after')
            wait = wait if isinstance(wait, (int, float)) and 0 < wait <= 86400 else FAIL_WINDOW
            with self.lock:
                self.locked_until = max(self.locked_until, self.clock() + wait)
            return {'ok': False, 'signed_in': False, 'error': 'locked', 'locked_until': self._lock_until(),
                    'message': 'Too many wrong codes. Wait, then try again.'}
        return {'ok': False, 'signed_in': False, 'error': 'bad_reply',
                'message': f'Metallic Control gave an unexpected answer (HTTP {status}).'}

    def sign_out(self, setting: str = '') -> dict:
        url = self.control_url(setting)
        session = self._session(url) if url else None
        self._forget()
        if session:
            def revoke():
                try:
                    self._request('POST', url + '/api/app/signout', {}, token=session['token'])
                except _Unreachable:
                    pass
            threading.Thread(target=revoke, daemon=True, name='metallic-signout').start()
        return self.status(setting)

    def state(self, setting: str = '', rng: str = 'hour') -> dict:
        url = self.control_url(setting)
        if not url:
            return {'reachable': False, 'signed_in': False, 'message': 'Metallic Control is not set up.'}
        session = self._session(url)
        if session is None:
            return {'reachable': False, 'signed_in': False, 'message': 'Sign in to Metallic first.'}
        rng = rng if rng in RANGES else 'hour'
        token = session['token']
        try:
            status, state = self._request('GET', url + '/api/app/state', token=token)
            if status == 401:
                self._forget()
                return {'reachable': True, 'signed_in': False, 'expired': True,
                        'message': 'Your Metallic sign-in ended. Sign in again.'}
            if status != 200 or not isinstance(state, dict):
                return {'reachable': True, 'signed_in': True, 'message': f'Metallic Control answered HTTP {status}.'}
            # CPU and memory history of every connected machine (the same keys as Metallic Control's overview)
            keys = [f"{m['id']}.{name}" for m in state.get('machines') or []
                    if isinstance(m, dict) and isinstance(m.get('id'), str) and KEY_RE.fullmatch(m['id'] + '.cpu')
                    and not m.get('pending') for name in ('cpu', 'mem_pct')][:40]
            query = urllib.parse.urlencode({'keys': ','.join(keys), 'range': rng})
            s_status, series = self._request('GET', url + '/api/app/series?' + query, token=token)
            p_status, speed = self._request('GET', url + '/api/app/speed?days=' + ('7' if rng == 'week' else '1'),
                                            token=token)
        except _Unreachable:
            return {'reachable': False, 'signed_in': True,
                    'message': 'Metallic Control did not answer. Showing nothing until it is back.'}
        if 401 in (s_status, p_status):
            self._forget()
            return {'reachable': True, 'signed_in': False, 'expired': True,
                    'message': 'Your Metallic sign-in ended. Sign in again.'}
        return {'reachable': True, 'signed_in': True, 'state': state,
                'series': series if s_status == 200 and isinstance(series, dict) else None,
                'speed': speed if p_status == 200 and isinstance(speed, dict) else None}


_SHARED: dict[str, MetallicAccess] = {}
_SHARED_LOCK = threading.Lock()


def for_home(home: Path) -> MetallicAccess:
    with _SHARED_LOCK:
        key = str(Path(home).resolve())
        if key not in _SHARED:
            _SHARED[key] = MetallicAccess(Path(home))
        return _SHARED[key]


def status_for(home: Path, setting: str = '') -> dict:
    """The bootstrap's `metallic` entry; never raises (a broken store reads as signed out)."""
    try:
        return for_home(home).status(setting)
    except Exception:
        return {'signed_in': False, 'expires_at': None, 'configured': bool(MetallicAccess.control_url(setting)),
                'control_url': MetallicAccess.control_url(setting), 'locked_until': None, 'secure_store': False}
