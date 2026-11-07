"""The rules: accounts, sign-in, lockout, sessions, 2FA, recovery, friends, presence, invites, news, admin, audit.

Every refusal is a `Refused(status, code, text)` with a plain sentence for people; nothing here prints or logs a
password, code or token. Minors (age band child or teen) get privacy defaults that cannot be widened: presence for
friends only, friend requests only from friends of friends, invites only from friends. There are no free-text
messages between players at all; an invite carries a game and a target id only.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
import threading
import time

from . import crypto
from .store import Store

ACCESS_TTL = 15 * 60
REFRESH_IDLE = 30 * 86400
REFRESH_ABSOLUTE = 90 * 86400
FAIL_WINDOW = 15 * 60
FAIL_MAX = 5
LOCK_BASE = 15 * 60
PRESENCE_TTL = 120
INVITE_TTL = 15 * 60
MAX_FRIENDS = 500
MAX_PENDING_OUT = 50
ROLES = ("user", "admin", "owner")
AGE_BANDS = ("child", "teen", "adult")
GAMES = ("RC", "MC", "RB", "PX")
STATUSES = ("online", "away", "busy", "playing", "offline")
PRESENCE_VIS = {"adult": ("friends", "everyone", "nobody"), "minor": ("friends", "nobody")}
FRIEND_REQ = {"adult": ("everyone", "friends_of_friends", "nobody"), "minor": ("friends_of_friends", "nobody")}
INVITES_FROM = ("friends", "nobody")
DEFAULTS = {"adult": {"presence_visibility": "friends", "friend_requests_from": "everyone", "invites_from": "friends"},
            "minor": {"presence_visibility": "friends", "friend_requests_from": "friends_of_friends",
                      "invites_from": "friends"}}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")
TARGET_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
RESERVED = {"admin", "administrator", "owner", "metallic", "star", "starai", "staff", "mod", "moderator", "system",
            "support", "root", "official", "help", "security", "litha"}
COMMON_PASSWORDS = {"password", "password1", "password12", "password123", "1234567890", "12345678910", "qwertyuiop",
                    "qwerty1234", "iloveyou12", "letmein123", "welcome123", "admin12345", "abc1234567", "monkey1234",
                    "dragon1234", "football12", "baseball12", "princess12", "sunshine12", "minecraft1",
                    "minecraft12", "roblox1234", "recroom123", "metallic12", "passw0rd12", "0123456789"}


class Refused(Exception):
    def __init__(self, status: int, code: str, text: str, **extra):
        super().__init__(text)
        self.status, self.code, self.text, self.extra = status, code, text, extra

    def body(self) -> dict:
        return {"ok": False, "error": self.code, "text": self.text, **self.extra}


def is_minor(age_band: str) -> bool:
    return age_band in ("child", "teen")


def _group(age_band: str) -> str:
    return "minor" if is_minor(age_band) else "adult"


class RateLimiter:
    """Token buckets per key (e.g. 'auth:<ip>'). allow() -> (ok, retry_after_seconds)."""

    def __init__(self, clock=time.time):
        self.clock, self.buckets, self.lock = clock, {}, threading.Lock()

    def allow(self, key: str, rate_per_min: float, burst: int) -> tuple[bool, int]:
        now = self.clock()
        with self.lock:
            tokens, last = self.buckets.get(key, (float(burst), now))
            tokens = min(float(burst), tokens + (now - last) * rate_per_min / 60.0)
            if tokens < 1.0:
                self.buckets[key] = (tokens, now)
                return False, max(1, int((1.0 - tokens) * 60.0 / rate_per_min) + 1)
            self.buckets[key] = (tokens - 1.0, now)
            if len(self.buckets) > 50_000:                  # drop full buckets so memory stays bounded
                self.buckets = {k: v for k, v in self.buckets.items() if v[0] < burst}
            return True, 0


def check_password(password: str, username: str) -> None:
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise Refused(400, "weak_password", "Use a password of 10 to 128 characters.")
    low = password.lower()
    if low in COMMON_PASSWORDS or len(set(password)) < 4:
        raise Refused(400, "weak_password", "That password is too easy to guess. Try a longer phrase.")
    if username and username.lower() in low:
        raise Refused(400, "weak_password", "Your password must not contain your username.")


def clean_text(value, limit: int, field: str, required: bool = True) -> str:
    text = value if isinstance(value, str) else ""
    text = "".join(ch for ch in text if ch == "\n" or ch >= " ").strip()
    if required and not text:
        raise Refused(400, "bad_request", f"{field} is required.")
    if len(text) > limit:
        raise Refused(400, "bad_request", f"{field} can be at most {limit} characters.")
    return text


class Accounts:
    def __init__(self, store: Store, signer: crypto.Signer, sealer: crypto.Sealer, clock=time.time,
                 registration: str = "open"):
        self.s, self.signer, self.sealer, self.clock = store, signer, sealer, clock
        self.registration = registration

    # ---------- helpers ----------
    def _acct(self, account_id: str):
        return self.s.one("SELECT * FROM accounts WHERE id=?", (account_id,))

    def _by_name(self, username: str):
        if not isinstance(username, str):
            return None
        return self.s.one("SELECT * FROM accounts WHERE uname=?", (username.strip().lower(),))

    def _need_user(self, username: str):
        row = self._by_name(username)
        if row is None or row["disabled"]:
            raise Refused(404, "no_such_player", "No player with that username.")
        return row

    def public(self, row) -> dict:
        return {"id": row["id"], "username": row["username"], "display_name": row["display_name"]}

    def me(self, account_id: str) -> dict:
        row = self._acct(account_id)
        recovery_left = self.s.one("SELECT COUNT(*) n FROM recovery_codes WHERE account=? AND used IS NULL",
                                   (account_id,))["n"]
        return {**self.public(row), "role": row["role"], "age_band": row["age_band"], "minor": is_minor(row["age_band"]),
                "totp": bool(row["totp_sealed"]), "recovery_codes_left": recovery_left, "created": row["created"],
                "privacy": {k: row[k] for k in ("presence_visibility", "friend_requests_from", "invites_from")},
                "privacy_choices": {"presence_visibility": PRESENCE_VIS[_group(row["age_band"])],
                                    "friend_requests_from": FRIEND_REQ[_group(row["age_band"])],
                                    "invites_from": INVITES_FROM}}

    def _issue(self, row, amr: list[str], client: str | None, sid: str | None = None) -> dict:
        now = self.clock()
        secret = secrets.token_urlsafe(32)
        if sid is None:
            sid = crypto.new_id("ses_")
            self.s.x("INSERT INTO sessions (id, account, refresh_digest, created, last_used, expires, client, amr) "
                     "VALUES (?,?,?,?,?,?,?,?)", (sid, row["id"], crypto.sha256_hex(secret), now, now,
                                                  now + REFRESH_IDLE, (client or "")[:80], ",".join(amr)))
        access = self.signer.sign({"sub": row["id"], "name": row["username"], "role": row["role"],
                                   "minor": is_minor(row["age_band"]), "sid": sid, "amr": amr}, ACCESS_TTL)
        return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL,
                "refresh_token": f"rt.{sid}.{secret}", "account": self.me(row["id"])}

    def _fail(self, row, ip: str, reason: str) -> None:
        now = self.clock()
        with self.s.tx():
            cur = self._acct(row["id"])
            count = 1 if now - cur["fail_first"] > FAIL_WINDOW else cur["fail_count"] + 1
            first = now if count == 1 else cur["fail_first"]
            if count >= FAIL_MAX:
                lockouts = cur["lockouts"] + 1
                until = now + LOCK_BASE * 2 ** (min(lockouts, 5) - 1)       # 15 min, 30, 1 h, 2 h, 4 h
                self.s.db.execute("UPDATE accounts SET fail_count=0, fail_first=0, lockouts=?, locked_until=? "
                                  "WHERE id=?", (lockouts, until, row["id"]))
            else:
                until = None
                self.s.db.execute("UPDATE accounts SET fail_count=?, fail_first=? WHERE id=?",
                                  (count, first, row["id"]))
        self.s.audit("login", False, row["id"], ip=ip, reason=reason)
        if until:
            self.s.audit("lockout", True, row["id"], ip=ip, until=round(until))

    def _locked(self, row) -> None:
        wait = int(row["locked_until"] - self.clock())
        if wait > 0:
            raise Refused(429, "locked", "Too many wrong tries. This account is paused for a while; try again later.",
                          retry_after=wait)

    def _check_second_factor(self, row, otp: str | None, recovery_code: str | None, ip: str) -> list[str]:
        """Returns the amr list, or raises. Wrong codes count toward the lockout."""
        if not row["totp_sealed"]:
            return ["pwd"]
        if recovery_code:
            if self._use_recovery(row["id"], recovery_code):
                self.s.audit("recovery_code_used", True, row["id"], ip=ip, purpose="sign-in")
                return ["pwd", "rec"]
            self._fail(row, ip, "recovery_code")
            raise Refused(401, "wrong_code", "That recovery code is not right or was already used.")
        if not otp:
            raise Refused(401, "otp_required", "Enter the 6-digit code from your authenticator app.")
        step = crypto.totp_match(self.sealer.open(row["totp_sealed"]), otp, self.clock(), row["totp_last_step"])
        if step is None:
            self._fail(row, ip, "otp")
            raise Refused(401, "wrong_code", "That code is not right. Codes change every 30 seconds.")
        self.s.x("UPDATE accounts SET totp_last_step=? WHERE id=? AND totp_last_step<?", (step, row["id"], step))
        return ["pwd", "otp"]

    def _use_recovery(self, account_id: str, code: str) -> bool:
        return self.s.x("UPDATE recovery_codes SET used=? WHERE account=? AND digest=? AND used IS NULL",
                        (self.clock(), account_id, crypto.recovery_digest(code))) == 1

    def _new_recovery(self, account_id: str) -> list[str]:
        codes = crypto.new_recovery_codes()
        with self.s.tx():
            self.s.db.execute("DELETE FROM recovery_codes WHERE account=?", (account_id,))
            self.s.db.executemany("INSERT INTO recovery_codes (account, digest) VALUES (?,?)",
                                  [(account_id, crypto.recovery_digest(c)) for c in codes])
        return codes

    def _reauth(self, row, password: str, otp: str | None, ip: str) -> None:
        self._locked(row)
        if not crypto.verify_password(row["pw_hash"], password if isinstance(password, str) else ""):
            self._fail(row, ip, "password")
            raise Refused(401, "wrong_password", "That password is not right.")
        if row["totp_sealed"]:
            self._check_second_factor(row, otp, None, ip)

    # ---------- owner bootstrap ----------
    def new_owner_code(self, hours: int = 24) -> str:
        code = secrets.token_urlsafe(18)
        self.s.x("INSERT INTO owner_codes VALUES (?,?,NULL)", (crypto.sha256_hex(code), self.clock() + hours * 3600))
        self.s.audit("owner_code_created", True, actor="server-cli")
        return code

    # ---------- account lifecycle ----------
    def register(self, username, password, display_name, age_band, ip: str, client: str | None = None,
                 owner_code: str | None = None, federated: bool = False) -> dict:
        """federated=True: the account signs in through a linked provider and has no password yet."""
        role = "user"
        if owner_code:
            digest = crypto.sha256_hex(owner_code if isinstance(owner_code, str) else "")
            if self.s.x("UPDATE owner_codes SET used=? WHERE digest=? AND used IS NULL AND expires>?",
                        (self.clock(), digest, self.clock())) != 1:
                self.s.audit("register", False, ip=ip, reason="owner_code")
                raise Refused(403, "bad_owner_code", "That owner code is not valid.")
            role = "owner"
        elif self.registration != "open":
            raise Refused(403, "registration_closed", "New accounts are not open right now.")
        if not isinstance(username, str) or not USERNAME_RE.match(username):
            raise Refused(400, "bad_username", "Usernames are 3 to 20 letters, digits or underscores.")
        if username.lower() in RESERVED:
            raise Refused(400, "bad_username", "That username is reserved. Pick another one.")
        if age_band not in AGE_BANDS:
            raise Refused(400, "bad_request", "Choose an age group.")
        display = clean_text(display_name or username, 32, "Display name").replace("\n", " ")
        if federated:
            pw_hash = ""
        else:
            check_password(password, username)
            pw_hash = crypto.hash_password(password)
        now = self.clock()
        acct_id = crypto.new_id("acct_")
        d = DEFAULTS[_group(age_band)]
        try:
            self.s.x("INSERT INTO accounts (id, username, uname, display_name, pw_hash, role, age_band, created, "
                     "pw_changed, presence_visibility, friend_requests_from, invites_from) VALUES "
                     "(?,?,?,?,?,?,?,?,?,?,?,?)", (acct_id, username, username.lower(), display, pw_hash, role,
                                                   age_band, now, now, d["presence_visibility"],
                                                   d["friend_requests_from"], d["invites_from"]))
        except sqlite3.IntegrityError as exc:
            raise Refused(409, "username_taken", "That username is taken.") from exc
        codes = self._new_recovery(acct_id)
        self.s.audit("register", True, acct_id, ip=ip, role=role, age_band=age_band, federated=federated)
        tokens = self._issue(self._acct(acct_id), ["pwd"], client)
        return {**tokens, "recovery_codes": codes}

    def login(self, username, password, ip: str, otp: str | None = None, recovery_code: str | None = None,
              client: str | None = None) -> dict:
        row = self._by_name(username)
        if row is None:
            crypto.verify_password(None, password if isinstance(password, str) else "")   # same cost as a real try
            self.s.audit("login", False, ip=ip, reason="unknown_user")
            raise Refused(401, "wrong_login", "Wrong username or password.")
        self._locked(row)
        if not crypto.verify_password(row["pw_hash"], password if isinstance(password, str) else ""):
            self._fail(row, ip, "password")
            raise Refused(401, "wrong_login", "Wrong username or password.")
        if row["disabled"]:
            self.s.audit("login", False, row["id"], ip=ip, reason="disabled")
            raise Refused(403, "disabled", "This account is turned off. Ask a Metallic admin for help.")
        amr = self._check_second_factor(row, otp, recovery_code, ip)
        if crypto.needs_rehash(row["pw_hash"]):
            self.s.x("UPDATE accounts SET pw_hash=? WHERE id=?", (crypto.hash_password(password), row["id"]))
        self.s.x("UPDATE accounts SET fail_count=0, fail_first=0, lockouts=0, locked_until=0 WHERE id=?", (row["id"],))
        self.s.audit("login", True, row["id"], ip=ip, amr=amr)
        return self._issue(self._acct(row["id"]), amr, client)

    def refresh(self, refresh_token, ip: str) -> dict:
        try:
            kind, sid, secret = str(refresh_token).split(".", 2)
            assert kind == "rt"
        except (ValueError, AssertionError) as exc:
            raise Refused(401, "bad_refresh", "Please sign in again.") from exc
        now = self.clock()
        ses = self.s.one("SELECT * FROM sessions WHERE id=?", (sid,))
        if ses is None or ses["revoked"] or ses["expires"] < now or now - ses["created"] > REFRESH_ABSOLUTE:
            raise Refused(401, "bad_refresh", "Please sign in again.")
        if not secrets.compare_digest(crypto.sha256_hex(secret), ses["refresh_digest"]):
            # an old refresh token came back: someone may have copied it. End the whole session.
            self.s.x("UPDATE sessions SET revoked=? WHERE id=?", (now, sid))
            self.s.audit("refresh_reuse", False, ses["account"], ip=ip, session=sid)
            raise Refused(401, "bad_refresh", "Please sign in again.")
        row = self._acct(ses["account"])
        if row["disabled"]:
            raise Refused(403, "disabled", "This account is turned off.")
        new_secret = secrets.token_urlsafe(32)
        if self.s.x("UPDATE sessions SET refresh_digest=?, last_used=?, expires=?, generation=generation+1 "
                    "WHERE id=? AND refresh_digest=?", (crypto.sha256_hex(new_secret), now,
                                                        min(now + REFRESH_IDLE, ses["created"] + REFRESH_ABSOLUTE),
                                                        sid, ses["refresh_digest"])) != 1:
            raise Refused(401, "bad_refresh", "Please sign in again.")
        out = self._issue(row, ses["amr"].split(","), None, sid=sid)
        out["refresh_token"] = f"rt.{sid}.{new_secret}"
        return out

    def authenticate(self, header: str | None) -> dict:
        """Bearer access token -> claims, with the session checked live (sign-out works at once here)."""
        if not header or not header.startswith("Bearer "):
            raise Refused(401, "signed_out", "Please sign in.")
        try:
            claims = crypto.verify_jwt(header[7:].strip(), self.signer.jwks, now=self.clock(), leeway=0)
        except crypto.TokenError as exc:
            raise Refused(401, "signed_out", "Please sign in again.") from exc
        ses = self.s.one("SELECT revoked FROM sessions WHERE id=?", (claims.get("sid"),))
        row = self._acct(claims.get("sub", ""))
        if ses is None or ses["revoked"] or row is None or row["disabled"]:
            raise Refused(401, "signed_out", "Please sign in again.")
        claims["role"] = row["role"]                       # role changes apply at once on this service
        return claims

    def introspect(self, token: str) -> dict:
        try:
            claims = self.authenticate("Bearer " + str(token))
        except Refused:
            return {"active": False}
        return {"active": True, **{k: claims[k] for k in ("sub", "name", "role", "minor", "sid", "amr", "exp")}}

    def logout(self, claims: dict, ip: str, everywhere: bool = False) -> None:
        now = self.clock()
        if everywhere:
            self.s.x("UPDATE sessions SET revoked=? WHERE account=? AND revoked IS NULL", (now, claims["sub"]))
        else:
            self.s.x("UPDATE sessions SET revoked=? WHERE id=?", (now, claims["sid"]))
        self.s.audit("logout", True, claims["sub"], ip=ip, everywhere=everywhere)

    def sessions(self, claims: dict) -> list[dict]:
        rows = self.s.q("SELECT id, created, last_used, client, amr FROM sessions WHERE account=? AND revoked IS NULL "
                        "AND expires>? ORDER BY last_used DESC", (claims["sub"], self.clock()))
        return [{**dict(r), "current": r["id"] == claims["sid"]} for r in rows]

    def revoke_session(self, claims: dict, sid: str, ip: str) -> None:
        if self.s.x("UPDATE sessions SET revoked=? WHERE id=? AND account=?", (self.clock(), sid, claims["sub"])) != 1:
            raise Refused(404, "not_found", "No such session.")
        self.s.audit("session_revoke", True, claims["sub"], ip=ip, session=sid)

    def change_password(self, claims: dict, old: str, new: str, otp: str | None, ip: str) -> None:
        row = self._acct(claims["sub"])
        if row["pw_hash"]:
            self._reauth(row, old, otp, ip)
        elif row["totp_sealed"]:                  # first password on a provider-only account: still needs 2FA
            self._check_second_factor(row, otp, None, ip)
        check_password(new, row["username"])
        now = self.clock()
        self.s.x("UPDATE accounts SET pw_hash=?, pw_changed=? WHERE id=?", (crypto.hash_password(new), now, row["id"]))
        self.s.x("UPDATE sessions SET revoked=? WHERE account=? AND id<>? AND revoked IS NULL",
                 (now, row["id"], claims["sid"]))
        self.s.audit("password_change", True, row["id"], ip=ip)

    def recover(self, username, recovery_code, new_password, ip: str) -> dict:
        """Email-free reset: a recovery code + a new password. Signs out every session."""
        row = self._by_name(username)
        if row is None:
            self.s.audit("recover", False, ip=ip, reason="unknown_user")
            raise Refused(401, "wrong_code", "That username and recovery code do not match.")
        self._locked(row)
        check_password(new_password, row["username"])
        if not isinstance(recovery_code, str) or not self._use_recovery(row["id"], recovery_code):
            self._fail(row, ip, "recovery_code")
            raise Refused(401, "wrong_code", "That username and recovery code do not match.")
        now = self.clock()
        self.s.x("UPDATE accounts SET pw_hash=?, pw_changed=?, fail_count=0, locked_until=0, lockouts=0 WHERE id=?",
                 (crypto.hash_password(new_password), now, row["id"]))
        self.s.x("UPDATE sessions SET revoked=? WHERE account=? AND revoked IS NULL", (now, row["id"]))
        self.s.audit("recover", True, row["id"], ip=ip)
        left = self.s.one("SELECT COUNT(*) n FROM recovery_codes WHERE account=? AND used IS NULL", (row["id"],))["n"]
        return {"ok": True, "recovery_codes_left": left}

    def regenerate_recovery(self, claims: dict, password: str, otp: str | None, ip: str) -> list[str]:
        row = self._acct(claims["sub"])
        self._reauth(row, password, otp, ip)
        codes = self._new_recovery(row["id"])
        self.s.audit("recovery_regen", True, row["id"], ip=ip)
        return codes

    # ---------- 2FA ----------
    def totp_setup(self, claims: dict, password: str, ip: str) -> dict:
        row = self._acct(claims["sub"])
        if row["totp_sealed"]:
            raise Refused(409, "totp_on", "Two-step sign-in is already on.")
        self._reauth(row, password, None, ip)
        secret = crypto.new_totp_secret()
        self.s.x("UPDATE accounts SET totp_pending=? WHERE id=?", (self.sealer.seal(secret), row["id"]))
        return {"secret": secret, "uri": crypto.totp_uri(secret, row["username"])}

    def totp_confirm(self, claims: dict, code: str, ip: str) -> dict:
        row = self._acct(claims["sub"])
        if not row["totp_pending"]:
            raise Refused(409, "no_setup", "Start two-step setup first.")
        secret = self.sealer.open(row["totp_pending"])
        step = crypto.totp_match(secret, code, self.clock(), 0)
        if step is None:
            self.s.audit("totp_enable", False, row["id"], ip=ip)
            raise Refused(400, "wrong_code", "That code is not right. Check the time on your phone and try again.")
        self.s.x("UPDATE accounts SET totp_sealed=totp_pending, totp_pending=NULL, totp_last_step=? WHERE id=?",
                 (step, row["id"]))
        self.s.audit("totp_enable", True, row["id"], ip=ip)
        return {"ok": True, "recovery_codes": self._new_recovery(row["id"])}

    def totp_disable(self, claims: dict, password: str, otp: str, ip: str) -> None:
        row = self._acct(claims["sub"])
        if not row["totp_sealed"]:
            raise Refused(409, "totp_off", "Two-step sign-in is already off.")
        self._reauth(row, password, otp or "", ip)
        self.s.x("UPDATE accounts SET totp_sealed=NULL, totp_pending=NULL WHERE id=?", (row["id"],))
        self.s.audit("totp_disable", True, row["id"], ip=ip)

    # ---------- profile + privacy ----------
    def update_profile(self, claims: dict, display_name, ip: str) -> dict:
        display = clean_text(display_name, 32, "Display name").replace("\n", " ")
        self.s.x("UPDATE accounts SET display_name=? WHERE id=?", (display, claims["sub"]))
        self.s.audit("profile_change", True, claims["sub"], ip=ip)
        return self.me(claims["sub"])

    def update_privacy(self, claims: dict, changes: dict, ip: str) -> dict:
        row = self._acct(claims["sub"])
        g = _group(row["age_band"])
        allowed = {"presence_visibility": PRESENCE_VIS[g], "friend_requests_from": FRIEND_REQ[g],
                   "invites_from": INVITES_FROM}
        updates = {}
        for key, value in (changes or {}).items():
            if key not in allowed:
                raise Refused(400, "bad_request", f"Unknown privacy setting {key!r}.")
            if value not in allowed[key]:
                raise Refused(403, "not_allowed", "That choice is not available for this account.",
                              setting=key, choices=list(allowed[key]))
            updates[key] = value
        for key, value in updates.items():
            self.s.x(f"UPDATE accounts SET {key}=? WHERE id=?", (value, row["id"]))     # key is from the allow-list
        self.s.audit("privacy_change", True, row["id"], ip=ip, **updates)
        return self.me(row["id"])

    # ---------- friends ----------
    def _pair(self, a: str, b: str) -> tuple[str, str]:
        return (a, b) if a < b else (b, a)

    def are_friends(self, a: str, b: str) -> bool:
        return self.s.one("SELECT 1 FROM friends WHERE a=? AND b=?", self._pair(a, b)) is not None

    def _friend_ids(self, a: str) -> set[str]:
        return {r["o"] for r in self.s.q("SELECT CASE WHEN a=? THEN b ELSE a END o FROM friends WHERE a=? OR b=?",
                                         (a, a, a))}

    def blocked_either(self, a: str, b: str) -> bool:
        return self.s.one("SELECT 1 FROM blocks WHERE (blocker=? AND blocked=?) OR (blocker=? AND blocked=?)",
                          (a, b, b, a)) is not None

    def friends_of_friends(self, a: str, b: str) -> bool:
        return bool(self._friend_ids(a) & self._friend_ids(b))

    def can_request(self, src: str, dst_row) -> bool:
        if self.blocked_either(src, dst_row["id"]):
            return False
        policy = dst_row["friend_requests_from"]
        if policy == "everyone" and not is_minor(dst_row["age_band"]):
            return True
        if policy in ("everyone", "friends_of_friends"):
            return self.friends_of_friends(src, dst_row["id"])
        return False

    def can_invite(self, src: str, dst_row) -> bool:
        """Also the rule any future direct message must use: only friends, never strangers, never when blocked."""
        return (dst_row["invites_from"] == "friends" and not self.blocked_either(src, dst_row["id"])
                and self.are_friends(src, dst_row["id"]))

    def friends(self, claims: dict) -> dict:
        me = claims["sub"]
        ids = self._friend_ids(me)
        rows = {r["id"]: r for r in self.s.q(f"SELECT * FROM accounts WHERE id IN ({','.join('?' * len(ids))})",
                                              tuple(ids))} if ids else {}
        friends = [{**self.public(r), "presence": self._presence_for(me, r)} for r in rows.values()]
        friends.sort(key=lambda f: (f["presence"]["status"] == "offline", f["username"].lower()))
        incoming = [self.public(r) for r in self.s.q(
            "SELECT a.* FROM friend_requests f JOIN accounts a ON a.id=f.src WHERE f.dst=? ORDER BY f.created", (me,))]
        outgoing = [self.public(r) for r in self.s.q(
            "SELECT a.* FROM friend_requests f JOIN accounts a ON a.id=f.dst WHERE f.src=? ORDER BY f.created", (me,))]
        blocked = [self.public(r) for r in self.s.q(
            "SELECT a.* FROM blocks b JOIN accounts a ON a.id=b.blocked WHERE b.blocker=?", (me,))]
        return {"friends": friends, "incoming": incoming, "outgoing": outgoing, "blocked": blocked}

    def friend_request(self, claims: dict, username: str, ip: str) -> dict:
        me = claims["sub"]
        dst = self._need_user(username)
        if dst["id"] == me:
            raise Refused(400, "bad_request", "You cannot add yourself.")
        if self.are_friends(me, dst["id"]):
            return {"ok": True, "state": "friends"}
        if self.s.one("SELECT 1 FROM friend_requests WHERE src=? AND dst=?", (dst["id"], me)):
            return self.friend_accept(claims, username, ip)              # they already asked: accept
        if not self.can_request(me, dst):
            self.s.audit("friend_request", False, me, ip=ip, to=dst["id"])
            raise Refused(403, "not_accepting", "This player is not accepting friend requests from you.")
        if len(self._friend_ids(me)) >= MAX_FRIENDS:
            raise Refused(409, "limit", f"You can have at most {MAX_FRIENDS} friends.")
        if self.s.one("SELECT COUNT(*) n FROM friend_requests WHERE src=?", (me,))["n"] >= MAX_PENDING_OUT:
            raise Refused(409, "limit", "You have too many requests waiting. Cancel some first.")
        self.s.x("INSERT OR IGNORE INTO friend_requests VALUES (?,?,?)", (me, dst["id"], self.clock()))
        self.s.audit("friend_request", True, me, ip=ip, to=dst["id"])
        return {"ok": True, "state": "requested"}

    def friend_accept(self, claims: dict, username: str, ip: str) -> dict:
        me = claims["sub"]
        src = self._need_user(username)
        with self.s.tx():
            if self.s.db.execute("DELETE FROM friend_requests WHERE src=? AND dst=?", (src["id"], me)).rowcount != 1:
                raise Refused(404, "not_found", "There is no request from that player.")
            self.s.db.execute("DELETE FROM friend_requests WHERE src=? AND dst=?", (me, src["id"]))
            self.s.db.execute("INSERT OR IGNORE INTO friends VALUES (?,?,?)", (*self._pair(me, src["id"]), self.clock()))
        self.s.audit("friend_accept", True, me, ip=ip, other=src["id"])
        return {"ok": True, "state": "friends"}

    def friend_decline(self, claims: dict, username: str, ip: str) -> dict:
        """Declines an incoming request or cancels an outgoing one."""
        me = claims["sub"]
        other = self._need_user(username)
        n = self.s.x("DELETE FROM friend_requests WHERE (src=? AND dst=?) OR (src=? AND dst=?)",
                     (other["id"], me, me, other["id"]))
        self.s.audit("friend_decline", bool(n), me, ip=ip, other=other["id"])
        return {"ok": True, "state": "none"}

    def friend_remove(self, claims: dict, username: str, ip: str) -> dict:
        me = claims["sub"]
        other = self._need_user(username)
        self.s.x("DELETE FROM friends WHERE a=? AND b=?", self._pair(me, other["id"]))
        self.s.audit("friend_remove", True, me, ip=ip, other=other["id"])
        return {"ok": True, "state": "none"}

    def block(self, claims: dict, username: str, ip: str, on: bool = True) -> dict:
        me = claims["sub"]
        other = self._need_user(username)
        if other["id"] == me:
            raise Refused(400, "bad_request", "You cannot block yourself.")
        if on:
            with self.s.tx():
                self.s.db.execute("INSERT OR IGNORE INTO blocks VALUES (?,?)", (me, other["id"]))
                self.s.db.execute("DELETE FROM friends WHERE a=? AND b=?", self._pair(me, other["id"]))
                self.s.db.execute("DELETE FROM friend_requests WHERE (src=? AND dst=?) OR (src=? AND dst=?)",
                                  (me, other["id"], other["id"], me))
                self.s.db.execute("UPDATE invites SET state='cancelled' WHERE state='open' AND "
                                  "((src=? AND dst=?) OR (src=? AND dst=?))", (me, other["id"], other["id"], me))
        else:
            self.s.x("DELETE FROM blocks WHERE blocker=? AND blocked=?", (me, other["id"]))
        self.s.audit("block" if on else "unblock", True, me, ip=ip, other=other["id"])
        return {"ok": True, "state": "blocked" if on else "none"}

    def profile(self, claims: dict, username: str) -> dict:
        me = claims["sub"]
        row = self._need_user(username)
        if row["id"] != me and self.blocked_either(me, row["id"]):
            raise Refused(404, "no_such_player", "No player with that username.")
        friend = self.are_friends(me, row["id"]) or row["id"] == me
        out = {"username": row["username"], "relationship": "self" if row["id"] == me else
               "friend" if friend else "requested" if self.s.one(
                   "SELECT 1 FROM friend_requests WHERE src=? AND dst=?", (me, row["id"])) else "none",
               "presence": self._presence_for(me, row)}
        if friend or not is_minor(row["age_band"]):          # minors' display names stay among friends
            out["display_name"] = row["display_name"]
        return out

    # ---------- presence ----------
    def set_presence(self, claims: dict, status, game=None, detail=None, joinable=False) -> dict:
        if status not in STATUSES:
            raise Refused(400, "bad_request", "Status is online, away, busy, playing or offline.")
        if game not in (None, "", *GAMES):
            raise Refused(400, "bad_request", "Game is RC, MC, RB or PX.")
        detail_text = clean_text(detail, 64, "Detail", required=False).replace("\n", " ") or None
        self.s.x("INSERT INTO presence VALUES (?,?,?,?,?,?) ON CONFLICT(account) DO UPDATE SET status=excluded.status, "
                 "game=excluded.game, detail=excluded.detail, joinable=excluded.joinable, updated=excluded.updated",
                 (claims["sub"], status, game or None, detail_text, int(bool(joinable)), self.clock()))
        return {"ok": True, "ttl": PRESENCE_TTL}

    def _presence_for(self, viewer: str, row) -> dict:
        offline = {"status": "offline"}
        p = self.s.one("SELECT * FROM presence WHERE account=?", (row["id"],))
        if p is None or p["status"] == "offline" or self.clock() - p["updated"] > PRESENCE_TTL:
            return offline
        if viewer == row["id"]:
            return {"status": p["status"], "game": p["game"], "detail": p["detail"], "joinable": bool(p["joinable"])}
        if self.blocked_either(viewer, row["id"]):
            return offline
        vis = row["presence_visibility"]
        if vis == "nobody":
            return offline
        if self.are_friends(viewer, row["id"]):
            return {"status": p["status"], "game": p["game"], "detail": p["detail"], "joinable": bool(p["joinable"])}
        if vis == "everyone" and not is_minor(row["age_band"]):
            return {"status": p["status"], "game": p["game"]}       # strangers never see rooms or join details
        return offline

    # ---------- invites ----------
    def invite(self, claims: dict, username: str, game, target, ip: str) -> dict:
        me = claims["sub"]
        dst = self._need_user(username)
        if game not in GAMES[:3]:
            raise Refused(400, "bad_request", "Invites are for RC, MC or RB.")
        if not isinstance(target, str) or not TARGET_RE.match(target):
            raise Refused(400, "bad_request", "The invite target is a short id (letters, digits, . _ : -).")
        if not self.can_invite(me, dst):
            self.s.audit("invite", False, me, ip=ip, to=dst["id"])
            raise Refused(403, "not_allowed", "You can only invite friends who accept invites.")
        now = self.clock()
        if self.s.one("SELECT COUNT(*) n FROM invites WHERE src=? AND created>?", (me, now - 3600))["n"] >= 30:
            raise Refused(429, "limit", "You sent a lot of invites. Wait a bit.", retry_after=600)
        self.s.x("UPDATE invites SET state='replaced' WHERE src=? AND dst=? AND game=? AND target=? AND state='open'",
                 (me, dst["id"], game, target))
        inv_id = crypto.new_id("inv_")
        self.s.x("INSERT INTO invites (id, src, dst, game, target, created, expires) VALUES (?,?,?,?,?,?,?)",
                 (inv_id, me, dst["id"], game, target, now, now + INVITE_TTL))
        self.s.audit("invite", True, me, ip=ip, to=dst["id"], game=game)
        return {"ok": True, "id": inv_id, "expires": now + INVITE_TTL}

    def invites(self, claims: dict) -> dict:
        me, now = claims["sub"], self.clock()

        def rows(sql):
            return [{"id": r["id"], "game": r["game"], "target": r["target"], "created": r["created"],
                     "expires": r["expires"], "state": r["state"], "from": r["src_name"], "to": r["dst_name"]}
                    for r in self.s.q(sql, (me, now))]
        base = ("SELECT i.*, s.username src_name, d.username dst_name FROM invites i JOIN accounts s ON s.id=i.src "
                "JOIN accounts d ON d.id=i.dst WHERE ")
        return {"incoming": rows(base + "i.dst=? AND i.state='open' AND i.expires>? ORDER BY i.created DESC LIMIT 50"),
                "outgoing": rows(base + "i.src=? AND i.expires>? ORDER BY i.created DESC LIMIT 50")}

    def answer_invite(self, claims: dict, inv_id: str, accept: bool, ip: str) -> dict:
        inv = self.s.one("SELECT * FROM invites WHERE id=? AND dst=?", (inv_id, claims["sub"]))
        if inv is None or inv["state"] != "open" or inv["expires"] < self.clock():
            raise Refused(404, "not_found", "That invite has expired.")
        if accept and self.blocked_either(inv["src"], inv["dst"]):
            raise Refused(404, "not_found", "That invite has expired.")
        self.s.x("UPDATE invites SET state=? WHERE id=?", ("accepted" if accept else "declined", inv_id))
        self.s.audit("invite_answer", True, claims["sub"], ip=ip, invite=inv_id, accepted=accept)
        return {"ok": True, "game": inv["game"], "target": inv["target"]} if accept else {"ok": True}

    # ---------- news ----------
    def news(self, limit: int = 20, game: str | None = None) -> list[dict]:
        limit = max(1, min(50, limit))
        if game in GAMES:
            rows = self.s.q("SELECT n.*, a.display_name author_name FROM news n JOIN accounts a ON a.id=n.author "
                            "WHERE n.game=? OR n.game IS NULL ORDER BY n.pinned DESC, n.created DESC LIMIT ?",
                            (game, limit))
        else:
            rows = self.s.q("SELECT n.*, a.display_name author_name FROM news n JOIN accounts a ON a.id=n.author "
                            "ORDER BY n.pinned DESC, n.created DESC LIMIT ?", (limit,))
        return [{"id": r["id"], "title": r["title"], "body": r["body"], "game": r["game"], "author": r["author_name"],
                 "created": r["created"], "pinned": bool(r["pinned"])} for r in rows]

    def _need_role(self, claims: dict, *roles: str) -> None:
        if claims.get("role") not in roles:
            raise Refused(403, "forbidden", "Only a Metallic admin can do that.")

    def post_news(self, claims: dict, title, body, game, pinned, ip: str) -> dict:
        self._need_role(claims, "admin", "owner")
        if game not in (None, "", *GAMES):
            raise Refused(400, "bad_request", "Game is RC, MC, RB, PX or empty.")
        nid = crypto.new_id("news_")
        self.s.x("INSERT INTO news VALUES (?,?,?,?,?,?,?)", (nid, clean_text(title, 120, "Title").replace("\n", " "),
                                                             clean_text(body, 4000, "Text"), game or None,
                                                             claims["sub"], self.clock(), int(bool(pinned))))
        self.s.audit("news_post", True, claims["sub"], ip=ip, news=nid)
        return {"ok": True, "id": nid}

    def delete_news(self, claims: dict, nid: str, ip: str) -> dict:
        self._need_role(claims, "admin", "owner")
        n = self.s.x("DELETE FROM news WHERE id=?", (nid,))
        self.s.audit("news_delete", bool(n), claims["sub"], ip=ip, news=nid)
        return {"ok": bool(n)}

    # ---------- admin ----------
    def admin_accounts(self, claims: dict, query: str = "") -> list[dict]:
        self._need_role(claims, "admin", "owner")
        rows = self.s.q("SELECT * FROM accounts WHERE uname LIKE ? ORDER BY created DESC LIMIT 200",
                        (f"%{query.lower()}%",))
        now = self.clock()
        return [{**self.public(r), "role": r["role"], "age_band": r["age_band"], "disabled": bool(r["disabled"]),
                 "totp": bool(r["totp_sealed"]), "locked": r["locked_until"] > now, "created": r["created"]}
                for r in rows]

    def admin_action(self, claims: dict, username: str, action: str, value, ip: str) -> dict:
        self._need_role(claims, "admin", "owner")
        row = self._by_name(username)
        if row is None:
            raise Refused(404, "no_such_player", "No player with that username.")
        if row["role"] == "owner" and claims["role"] != "owner":
            raise Refused(403, "forbidden", "Only the owner can change the owner's account.")
        if action == "unlock":
            self.s.x("UPDATE accounts SET locked_until=0, fail_count=0, lockouts=0 WHERE id=?", (row["id"],))
        elif action in ("disable", "enable"):
            self.s.x("UPDATE accounts SET disabled=? WHERE id=?", (int(action == "disable"), row["id"]))
            if action == "disable":
                self.s.x("UPDATE sessions SET revoked=? WHERE account=? AND revoked IS NULL", (self.clock(), row["id"]))
        elif action == "set_role":
            self._need_role(claims, "owner")
            if value not in ROLES or row["id"] == claims["sub"]:
                raise Refused(400, "bad_request", "Role is user, admin or owner (and not your own).")
            self.s.x("UPDATE accounts SET role=? WHERE id=?", (value, row["id"]))
        elif action == "set_age_band":
            if value not in AGE_BANDS:
                raise Refused(400, "bad_request", "Age group is child, teen or adult.")
            self.s.x("UPDATE accounts SET age_band=? WHERE id=?", (value, row["id"]))
            if is_minor(value):                       # clamp anything a minor may not have
                d = DEFAULTS["minor"]
                if row["presence_visibility"] not in PRESENCE_VIS["minor"]:
                    self.s.x("UPDATE accounts SET presence_visibility=? WHERE id=?", (d["presence_visibility"], row["id"]))
                if row["friend_requests_from"] not in FRIEND_REQ["minor"]:
                    self.s.x("UPDATE accounts SET friend_requests_from=? WHERE id=?",
                             (d["friend_requests_from"], row["id"]))
        else:
            raise Refused(400, "bad_request", "Action is unlock, disable, enable, set_role or set_age_band.")
        self.s.audit("admin_" + action, True, row["id"], actor=claims["sub"], ip=ip,
                     value=value if action in ("set_role", "set_age_band") else None)
        return {"ok": True}

    def admin_audit(self, claims: dict, username: str | None = None, limit: int = 200) -> list[dict]:
        self._need_role(claims, "admin", "owner")
        acct = self._by_name(username)["id"] if username and self._by_name(username) else None
        return self.s.audit_rows(max(1, min(1000, limit)), acct)
