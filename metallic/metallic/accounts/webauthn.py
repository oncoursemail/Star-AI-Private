"""WebAuthn (passkeys) verification: registration and assertion, user verification required, attestation "none".

Small on purpose: a CBOR reader for what WebAuthn sends, COSE keys for ES256 (-7), RS256 (-257, Windows Hello) and
EdDSA (-8), and the checks from the WebAuthn Level 2 spec (sections 7.1 and 7.2): type, challenge, origin, RP ID hash,
user present + user verified flags, signature, signature counter. Attestation statements are not trusted (we ask for
"none"), so a passkey proves possession, not the authenticator's make.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

from .crypto import b64u, b64u_dec

FLAG_UP, FLAG_UV, FLAG_AT = 0x01, 0x04, 0x40
ALGS = (-7, -257, -8)


class WebAuthnError(ValueError):
    pass


# ---------- CBOR (RFC 8949), only the parts WebAuthn uses ----------

def cbor_decode(data: bytes, pos: int = 0):
    """-> (value, next_pos)."""
    if pos >= len(data):
        raise WebAuthnError("truncated CBOR")
    ib = data[pos]
    major, info = ib >> 5, ib & 0x1F
    pos += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        n = 1 << (info - 24)
        if pos + n > len(data):
            raise WebAuthnError("truncated CBOR")
        arg = int.from_bytes(data[pos:pos + n], "big")
        pos += n
    else:
        raise WebAuthnError("unsupported CBOR")
    if major == 0:
        return arg, pos
    if major == 1:
        return -1 - arg, pos
    if major in (2, 3):
        if pos + arg > len(data):
            raise WebAuthnError("truncated CBOR")
        raw = data[pos:pos + arg]
        return (raw if major == 2 else raw.decode("utf-8")), pos + arg
    if major == 4:
        out = []
        for _ in range(arg):
            v, pos = cbor_decode(data, pos)
            out.append(v)
        return out, pos
    if major == 5:
        out = {}
        for _ in range(arg):
            k, pos = cbor_decode(data, pos)
            v, pos = cbor_decode(data, pos)
            out[k] = v
        return out, pos
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], pos
    raise WebAuthnError("unsupported CBOR")


# ---------- COSE keys ----------

def cose_to_public(cose: dict):
    """-> (public key object, alg)."""
    kty, alg = cose.get(1), cose.get(3)
    if kty == 2 and alg == -7 and cose.get(-1) == 1:
        x, y = cose.get(-2), cose.get(-3)
        if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y) == 32):
            raise WebAuthnError("bad EC key")
        return ec.EllipticCurvePublicNumbers(int.from_bytes(x, "big"), int.from_bytes(y, "big"),
                                             ec.SECP256R1()).public_key(), alg
    if kty == 3 and alg == -257:
        n, e = cose.get(-1), cose.get(-2)
        if not (isinstance(n, bytes) and isinstance(e, bytes)) or len(n) < 256:
            raise WebAuthnError("bad RSA key (2048 bits or more)")
        return rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key(), alg
    if kty == 1 and alg == -8 and cose.get(-1) == 6:
        return ed25519.Ed25519PublicKey.from_public_bytes(cose.get(-2)), alg
    raise WebAuthnError("unsupported key type")


def public_pem(key) -> str:
    return key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def verify_sig(pem: str, alg: int, sig: bytes, msg: bytes) -> None:
    key = serialization.load_pem_public_key(pem.encode())
    try:
        if alg == -7:
            key.verify(sig, msg, ec.ECDSA(hashes.SHA256()))
        elif alg == -257:
            key.verify(sig, msg, padding.PKCS1v15(), hashes.SHA256())
        elif alg == -8:
            key.verify(sig, msg)
        else:
            raise WebAuthnError("unsupported algorithm")
    except InvalidSignature as exc:
        raise WebAuthnError("bad signature") from exc


# ---------- checks ----------

def _client_data(raw_b64: str, kind: str, challenge: str, origins: tuple[str, ...]) -> bytes:
    raw = b64u_dec(raw_b64)
    try:
        cd = json.loads(raw)
    except ValueError as exc:
        raise WebAuthnError("bad clientDataJSON") from exc
    if cd.get("type") != kind:
        raise WebAuthnError("wrong ceremony type")
    if not hmac.compare_digest(str(cd.get("challenge", "")), challenge):
        raise WebAuthnError("wrong challenge")
    if cd.get("origin") not in origins:
        raise WebAuthnError("wrong origin")
    if cd.get("crossOrigin"):
        raise WebAuthnError("cross-origin call")
    return raw


def _auth_data(raw: bytes, rp_id: str) -> tuple[int, int, bytes]:
    if len(raw) < 37:
        raise WebAuthnError("short authenticator data")
    if not hmac.compare_digest(raw[:32], hashlib.sha256(rp_id.encode()).digest()):
        raise WebAuthnError("wrong RP ID")
    flags = raw[32]
    if not flags & FLAG_UP:
        raise WebAuthnError("user not present")
    if not flags & FLAG_UV:
        raise WebAuthnError("user not verified (Windows Hello / PIN / biometrics required)")
    return flags, struct.unpack(">I", raw[33:37])[0], raw[37:]


def verify_registration(credential: dict, challenge: str, rp_id: str, origins: tuple[str, ...]) -> dict:
    """-> {"id", "public_key" (PEM), "alg", "sign_count"}."""
    resp = credential.get("response") or {}
    _client_data(resp.get("clientDataJSON", ""), "webauthn.create", challenge, origins)
    att, _ = cbor_decode(b64u_dec(resp.get("attestationObject", "")))
    if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
        raise WebAuthnError("bad attestation object")
    flags, count, rest = _auth_data(att["authData"], rp_id)
    if not flags & FLAG_AT or len(rest) < 18:
        raise WebAuthnError("no credential in authenticator data")
    n = struct.unpack(">H", rest[16:18])[0]
    cred_id = rest[18:18 + n]
    if len(cred_id) != n or n == 0 or n > 1023:
        raise WebAuthnError("bad credential id")
    cose, _ = cbor_decode(rest, 18 + n)
    key, alg = cose_to_public(cose)
    if b64u(cred_id) != credential.get("id"):
        raise WebAuthnError("credential id mismatch")
    return {"id": b64u(cred_id), "public_key": public_pem(key), "alg": alg, "sign_count": count}


def verify_assertion(credential: dict, challenge: str, rp_id: str, origins: tuple[str, ...], public_key: str,
                     alg: int, stored_count: int) -> int:
    """-> the new signature counter. Raises WebAuthnError on any failed check (including a cloned key)."""
    resp = credential.get("response") or {}
    cd_raw = _client_data(resp.get("clientDataJSON", ""), "webauthn.get", challenge, origins)
    auth = b64u_dec(resp.get("authenticatorData", ""))
    _, count, _ = _auth_data(auth, rp_id)
    verify_sig(public_key, alg, b64u_dec(resp.get("signature", "")), auth + hashlib.sha256(cd_raw).digest())
    if (count or stored_count) and count <= stored_count:
        raise WebAuthnError("signature counter went backwards (possible cloned key)")
    return count
