"""Ed25519 (RFC 8032) with no third-party dependency.

`cryptography` is used when it is installed (constant-time, fast). Otherwise a pure-Python implementation of the
RFC 8032 reference algorithm runs. Verification is what ships inside the launcher and is fast enough for a manifest
(a few milliseconds). Signing happens only on the owner's own PC, offline, on small files; the pure-Python signer is
not constant-time, which does not matter there. Both paths are checked against the RFC test vectors.
"""
from __future__ import annotations

import hashlib

try:  # optional accelerator
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed

    HAVE_CRYPTOGRAPHY = True
except Exception:  # not installed or unusable
    HAVE_CRYPTOGRAPHY = False

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)  # extended coordinates (X, Y, Z, T)
_ZERO = (0, 1, 1, 0)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p):
    q = _ZERO
    while s:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _compress(p) -> bytes:
    zi = _inv(p[2])
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return int(y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _clamp(h: bytes) -> int:
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a


def _py_public(seed: bytes) -> bytes:
    return _compress(_mul(_clamp(_sha512(seed)), _G))


def _py_sign(seed: bytes, message: bytes) -> bytes:
    h = _sha512(seed)
    a = _clamp(h)
    pub = _compress(_mul(a, _G))
    r = int.from_bytes(_sha512(h[32:] + message), "little") % _L
    big_r = _compress(_mul(r, _G))
    k = int.from_bytes(_sha512(big_r + pub + message), "little") % _L
    return big_r + ((r + k * a) % _L).to_bytes(32, "little")


def _py_verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    r = _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(_sha512(signature[:32] + public + message), "little") % _L
    return _equal(_mul(s, _G), _add(r, _mul(k, a)))


# ---- public API -------------------------------------------------------------------------------------------------

def public_key(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("an Ed25519 seed is 32 bytes")
    if HAVE_CRYPTOGRAPHY:
        key = _ed.Ed25519PrivateKey.from_private_bytes(seed)
        return key.public_key().public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw)
    return _py_public(seed)


def sign(seed: bytes, message: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("an Ed25519 seed is 32 bytes")
    if HAVE_CRYPTOGRAPHY:
        return _ed.Ed25519PrivateKey.from_private_bytes(seed).sign(message)
    return _py_sign(seed, message)


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True only for a valid signature. Never raises on malformed input."""
    try:
        if HAVE_CRYPTOGRAPHY:
            if len(public) != 32 or len(signature) != 64:
                return False
            try:
                _ed.Ed25519PublicKey.from_public_bytes(public).verify(signature, message)
                return True
            except _InvalidSignature:
                return False
        return _py_verify(public, message, signature)
    except Exception:
        return False
