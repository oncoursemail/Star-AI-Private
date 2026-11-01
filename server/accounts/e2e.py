"""End-to-end check of a deployed Metallic accounts service, run INSIDE its container against https://127.0.0.1.

    python3 e2e.py --url https://127.0.0.1:8475 --fingerprint <sha256> --config /etc/metallic-accounts/accounts.toml

Creates throwaway accounts named e2e_<random>_* with random passwords (never printed) and checks sign-in, lockout,
refresh rotation + reuse detection, 2FA, recovery, minor privacy, friends, presence, invites and news. deploy.sh e2e
deletes the e2e_ accounts afterwards. Exit 0 only if every check passed.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import time

from metallic.accounts import crypto, runtime
from metallic.accounts.client import AccountsClient, AccountsError, TokenStore

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, note: str = "") -> None:
    RESULTS.append((name, bool(cond), note))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({note})" if note else ""), flush=True)


def refused(fn, code: str | None = None, status: int | None = None) -> bool:
    try:
        fn()
    except AccountsError as e:
        return (code is None or e.code == code) and (status is None or e.status == status)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--fingerprint", required=True)
    ap.add_argument("--config", required=True)
    a = ap.parse_args()
    tag = "e2e_" + secrets.token_hex(3)

    def new():
        return AccountsClient(a.url, fingerprint=a.fingerprint, store=TokenStore(None), user_agent="metallic-e2e")

    pw = secrets.token_urlsafe(18)
    t0 = time.time()
    c = new()
    check("health over pinned TLS", c.health().get("ok") is True)
    alice, bob, kid, stranger = new(), new(), new(), new()
    reg = alice.register(tag + "_a", pw, "adult")
    check("register returns 10 recovery codes", len(reg["recovery_codes"]) == 10)
    bob.register(tag + "_b", pw, "adult")
    kid.register(tag + "_k", pw, "child")
    stranger.register(tag + "_s", pw, "adult")
    claims = crypto.verify_jwt(alice.access_token(), c.jwks())
    check("access token verifies offline with JWKS (ES256)", claims["name"] == tag + "_a" and claims["amr"] == ["pwd"])
    check("minor flag in token", crypto.verify_jwt(kid.access_token(), c.jwks())["minor"] is True)

    alice.friend("request", tag + "_b")
    bob.friend("accept", tag + "_a")
    alice.set_presence("playing", game="RC", detail="Rec Center", joinable=True)
    p = bob.presence()
    check("friend sees presence 'playing RC'", p and p[0]["presence"].get("game") == "RC"
          and p[0]["presence"]["status"] == "playing")
    check("stranger does not see presence", stranger.profile(tag + "_a")["presence"] == {"status": "offline"})
    inv = alice.invite(tag + "_b", "RC", "room-rec-center")
    check("invite reaches friend", bob.invites()["incoming"][0]["id"] == inv["id"])
    check("invite accept returns target", bob.answer_invite(inv["id"], True).get("target") == "room-rec-center")
    check("stranger cannot invite", refused(lambda: stranger.invite(tag + "_b", "RC", "room-1"), "not_allowed"))

    check("stranger cannot friend-request a child", refused(lambda: stranger.friend("request", tag + "_k"),
                                                             "not_accepting"))
    check("stranger cannot invite a child", refused(lambda: stranger.invite(tag + "_k", "RC", "room-1")))
    check("child cannot widen presence", refused(lambda: kid.set_privacy(presence_visibility="everyone"),
                                                 "not_allowed"))
    check("child display name hidden from strangers", "display_name" not in stranger.profile(tag + "_k"))

    first = alice.store.load()
    alice.access_exp = 0
    alice.me()
    check("refresh rotates the refresh token", alice.store.load() != first)
    thief = new()
    thief.store.save(first)
    check("reused refresh token is refused", refused(thief.me, status=401))
    alice.access = None
    check("...and the whole session is ended", refused(alice.me, status=401))

    locker = new()
    locker.register(tag + "_l", pw, "adult")
    wrong = [refused(lambda: new().login(tag + "_l", "wrong-" + pw), "wrong_login") for _ in range(5)]
    check("5 wrong passwords refused", all(wrong))
    check("account locked even with the right password", refused(lambda: new().login(tag + "_l", pw), "locked", 429))

    totp_user = new()
    totp_user.register(tag + "_t", pw, "teen")
    secret = totp_user.totp_setup(pw)["secret"]
    codes = totp_user.totp_confirm(crypto.totp_code(secret, int(time.time() // 30)))["recovery_codes"]
    check("2FA on: password alone asks for a code", refused(lambda: new().login(tag + "_t", pw), "otp_required"))
    check("2FA: recovery code works once", new().login(tag + "_t", pw, recovery_code=codes[0])["totp"] is True)
    check("2FA: recovery code cannot be reused",
          refused(lambda: new().login(tag + "_t", pw, recovery_code=codes[0]), "wrong_code"))

    new_pw = secrets.token_urlsafe(18)
    bob_codes = bob.new_recovery_codes(pw)
    check("email-free recovery resets password", new().recover(tag + "_b", bob_codes[0], new_pw)["ok"])
    check("old password no longer works", refused(lambda: new().login(tag + "_b", pw), "wrong_login"))
    check("new password works", new().login(tag + "_b", new_pw)["username"] == tag + "_b")

    accounts, _ = runtime.build(runtime.load(a.config))
    owner_code = accounts.new_owner_code(hours=1)
    owner = new()
    owner.register(tag + "_o", pw, "adult", owner_code=owner_code)
    check("plain user cannot post news", refused(lambda: signed_in(new, tag + "_s", pw).post_news("x", "y"), "forbidden"))
    owner.post_news(f"{tag} test post", "e2e check", game="RC")
    check("news readable without signing in", any(n["title"] == f"{tag} test post" for n in new().news()))

    # passkeys with a software authenticator (ES256 and RS256 like Windows Hello), and provider endpoints
    for alg in (-7, -257):
        pk_user = new()
        pk_user.register(f"{tag}_p{abs(alg)}", pw, "adult")
        key = SoftKey(alg)
        opts = pk_user.passkey_register_options()
        added = pk_user.passkey_register_finish(opts["flow"], key.create(opts), "e2e key")
        check(f"passkey {alg} registered (UV + resident key required)", len(added["passkeys"]) == 1 and
              opts["publicKey"]["authenticatorSelection"]["userVerification"] == "required")
        other = new()
        lo = other.passkey_login_options()
        check(f"passkey {alg} discoverable sign-in", other.passkey_login_finish(lo["flow"], key.get(lo, pk_user.me()["id"]))
              ["username"] == f"{tag}_p{abs(alg)}")
        lo = new().passkey_login_options()
        check(f"passkey {alg} wrong origin refused", refused(lambda: new().passkey_login_finish(
            lo["flow"], key.get(lo, pk_user.me()["id"], origin="https://evil.example")), "passkey_refused"))
    check("providers listing answers", "providers" in c.providers())
    check("loopback-only redirects", refused(lambda: c.oauth_start("google", "https://evil.example/cb", "x" * 43),
                                             None, None))

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed in {time.time() - t0:.1f} s; tag {tag}")
    return 1 if failed else 0


class SoftKey:
    """Software authenticator: real WebAuthn registration/assertion data, attestation "none", UP+UV flags."""

    def __init__(self, alg: int):
        import secrets as _s
        from cryptography.hazmat.primitives.asymmetric import ec, rsa
        self.alg, self.count, self.id = alg, 0, _s.token_bytes(16)
        self.key = ec.generate_private_key(ec.SECP256R1()) if alg == -7 else             rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @staticmethod
    def cbor(v) -> bytes:
        def head(major, n):
            for ai, size in ((None, 0), (24, 1), (25, 2), (26, 4)):
                if ai is None and n < 24:
                    return bytes([major << 5 | n])
                if ai and n < 1 << (8 * size):
                    return bytes([major << 5 | ai]) + n.to_bytes(size, "big")
        if isinstance(v, int):
            return head(0, v) if v >= 0 else head(1, -1 - v)
        if isinstance(v, bytes):
            return head(2, len(v)) + v
        if isinstance(v, str):
            return head(3, len(v.encode())) + v.encode()
        return head(5, len(v)) + b"".join(SoftKey.cbor(k) + SoftKey.cbor(x) for k, x in v.items())

    def _ad(self, rp_id, flags, attested=False):
        import hashlib
        import struct
        self.count += 1
        out = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", self.count)
        if attested:
            n = self.key.public_key().public_numbers()
            cose = {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")} if self.alg == -7                 else {1: 3, 3: -257, -1: n.n.to_bytes(256, "big"), -2: n.e.to_bytes(3, "big")}
            out += b"\0" * 16 + struct.pack(">H", len(self.id)) + self.id + self.cbor(cose)
        return out

    def create(self, opts, origin="http://localhost:47615"):
        import json as _j
        pk = opts["publicKey"]
        cd = _j.dumps({"type": "webauthn.create", "challenge": pk["challenge"], "origin": origin}).encode()
        att = self.cbor({"fmt": "none", "attStmt": {}, "authData": self._ad(pk["rp"]["id"], 0x45, True)})
        return {"id": crypto.b64u(self.id), "type": "public-key",
                "response": {"clientDataJSON": crypto.b64u(cd), "attestationObject": crypto.b64u(att)}}

    def get(self, opts, user, origin="http://localhost:47615"):
        import hashlib
        import json as _j
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, padding
        pk = opts["publicKey"]
        cd = _j.dumps({"type": "webauthn.get", "challenge": pk["challenge"], "origin": origin}).encode()
        ad = self._ad(pk["rpId"], 0x05)
        msg = ad + hashlib.sha256(cd).digest()
        sig = self.key.sign(msg, ec.ECDSA(hashes.SHA256())) if self.alg == -7 else             self.key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
        return {"id": crypto.b64u(self.id), "type": "public-key",
                "response": {"clientDataJSON": crypto.b64u(cd), "authenticatorData": crypto.b64u(ad),
                             "signature": crypto.b64u(sig), "userHandle": crypto.b64u(user.encode())}}


def signed_in(new, username: str, pw: str) -> AccountsClient:
    c = new()
    c.login(username, pw)
    return c


if __name__ == "__main__":
    sys.exit(main())
