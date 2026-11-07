"""Password hashing (argon2id), TOTP (RFC 6238), ES256 JWT access tokens, sealed secrets (AES-GCM) and random ids.

Access tokens are standard JWTs signed with ECDSA P-256 (alg ES256) so other services verify them offline with only
the public key (GET /.well-known/jwks.json): Metallic Control in Python, the RC backend in .NET (ECDsa), anything else.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import struct
import threading
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError   # InvalidHash: argon2-cffi 21 (Ubuntu 24.04)
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ISSUER = "metallic-accounts"
AUDIENCE = "metallic"

# RFC 9106 second recommended option (t=3, 64 MiB); p=1 because the container has 1-2 CPUs.
_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=1, hash_len=32, salt_len=16)
_HASH_SLOTS = threading.BoundedSemaphore(2)          # at most 2 hashes at once: 128 MiB, keeps the box responsive
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(16))
DEFAULT_COST = (3, 64 * 1024)


def set_cost(time_cost: int, memory_kib: int) -> None:
    """Tests only: cheaper hashing. Stored hashes keep their own parameters; needs_rehash upgrades them later."""
    global _HASHER, _DUMMY_HASH
    _HASHER = PasswordHasher(time_cost=time_cost, memory_cost=memory_kib, parallelism=1, hash_len=32, salt_len=16)
    _DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    with _HASH_SLOTS:
        return _HASHER.hash(password)


def verify_password(stored: str | None, password: str) -> bool:
    """Constant work whether or not the account exists (unknown accounts verify against a dummy hash)."""
    with _HASH_SLOTS:
        try:
            return _HASHER.verify(stored or _DUMMY_HASH, password) and bool(stored)   # '' = no password set
        except (VerifyMismatchError, VerificationError, InvalidHash):
            return False


def needs_rehash(stored: str) -> bool:
    return _HASHER.check_needs_rehash(stored)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_dec(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_id(prefix: str, nbytes: int = 10) -> str:
    return prefix + base64.b32encode(secrets.token_bytes(nbytes)).decode().rstrip("=").lower()


# ---------- TOTP ----------

def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_code(secret_b32: str, step: int, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** digits).zfill(digits)


def totp_match(secret_b32: str, code: str, now: float, last_step: int, window: int = 1) -> int | None:
    """The matching time step (30 s) within +-window, or None. Steps at or before last_step are replays."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    current = int(now // 30)
    for step in range(current - window, current + window + 1):
        if step > last_step and hmac.compare_digest(totp_code(secret_b32, step), code):
            return step
    return None


def totp_uri(secret_b32: str, username: str) -> str:
    return f"otpauth://totp/Metallic:{username}?secret={secret_b32}&issuer=Metallic&algorithm=SHA1&digits=6&period=30"


# ---------- recovery codes (80 bits each; fast hash is enough at that entropy) ----------

def new_recovery_codes(n: int = 10) -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"          # 31 symbols, no 0/o/1/l/i
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(alphabet) for _ in range(16))
        codes.append("-".join(raw[i:i + 4] for i in range(0, 16, 4)))
    return codes


def recovery_digest(code: str) -> str:
    return sha256_hex("metallic-recovery:" + (code or "").strip().lower().replace(" ", ""))


# ---------- sealed secrets (TOTP secrets at rest) ----------

class Sealer:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("data key must be 32 bytes")
        self.aead = AESGCM(key)

    def seal(self, text: str) -> str:
        nonce = os.urandom(12)
        return b64u(nonce + self.aead.encrypt(nonce, text.encode(), b"metallic-accounts"))

    def open(self, sealed: str) -> str:
        raw = b64u_dec(sealed)
        return self.aead.decrypt(raw[:12], raw[12:], b"metallic-accounts").decode()


# ---------- ES256 JWT ----------

def new_signing_key_pem() -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def _kid(pub: ec.EllipticCurvePublicKey) -> str:
    der = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()[:16]


def public_jwk(pub: ec.EllipticCurvePublicKey) -> dict:
    nums = pub.public_numbers()
    return {"kty": "EC", "crv": "P-256", "alg": "ES256", "use": "sig", "kid": _kid(pub),
            "x": b64u(nums.x.to_bytes(32, "big")), "y": b64u(nums.y.to_bytes(32, "big"))}


def jwk_to_public(jwk: dict) -> ec.EllipticCurvePublicKey:
    if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise ValueError("only P-256 keys")
    x = int.from_bytes(b64u_dec(jwk["x"]), "big")
    y = int.from_bytes(b64u_dec(jwk["y"]), "big")
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()


class Signer:
    """Signs with the current key; also publishes the previous key (if any) so rotation does not sign people out."""

    def __init__(self, current_pem: bytes, previous_pem: bytes | None = None, clock=time.time):
        self.key = serialization.load_pem_private_key(current_pem, password=None)
        if not isinstance(self.key, ec.EllipticCurvePrivateKey) or self.key.curve.name != "secp256r1":
            raise ValueError("signing key must be an EC P-256 private key")
        self.kid = _kid(self.key.public_key())
        pubs = [self.key.public_key()]
        if previous_pem:
            pubs.append(serialization.load_pem_private_key(previous_pem, password=None).public_key())
        self.jwks = {"keys": [public_jwk(p) for p in pubs]}
        self.clock = clock

    @classmethod
    def from_files(cls, current: str | Path, previous: str | Path | None = None, clock=time.time) -> "Signer":
        prev = Path(previous).read_bytes() if previous and Path(previous).is_file() else None
        return cls(Path(current).read_bytes(), prev, clock)

    def sign(self, claims: dict, ttl_s: int) -> str:
        now = int(self.clock())
        body = {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "nbf": now - 5, "exp": now + ttl_s, **claims}
        head = {"alg": "ES256", "typ": "JWT", "kid": self.kid}
        signing_input = b64u(json.dumps(head, separators=(",", ":")).encode()) + "." + \
            b64u(json.dumps(body, separators=(",", ":")).encode())
        der = self.key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return signing_input + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


class TokenError(ValueError):
    pass


def verify_jwt(token: str, jwks: dict, audience: str = AUDIENCE, now: float | None = None,
               leeway: int = 30) -> dict:
    """Verify an ES256 access token against a JWKS document. Raises TokenError; returns the claims.

    Usable by any Python service (Metallic Control, tools) with only the public keys."""
    try:
        h64, b64, s64 = token.split(".")
        head = json.loads(b64u_dec(h64))
        claims = json.loads(b64u_dec(b64))
        sig = b64u_dec(s64)
    except (ValueError, AttributeError) as exc:
        raise TokenError("malformed token") from exc
    if head.get("alg") != "ES256" or len(sig) != 64:
        raise TokenError("unsupported algorithm")
    jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == head.get("kid")), None)
    if jwk is None:
        raise TokenError("unknown key")
    der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
    try:
        jwk_to_public(jwk).verify(der, (h64 + "." + b64).encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise TokenError("bad signature") from exc
    t = time.time() if now is None else now
    aud = claims.get("aud")
    if claims.get("iss") != ISSUER or (audience not in (aud if isinstance(aud, list) else [aud])):
        raise TokenError("wrong issuer or audience")
    if t > claims.get("exp", 0) + leeway or t < claims.get("nbf", 0) - leeway:
        raise TokenError("expired")
    return claims
