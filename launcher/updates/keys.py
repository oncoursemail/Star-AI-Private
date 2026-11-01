"""Signing keys and the trust list.

The private key is a small JSON file that lives OUTSIDE every repository (default `~/.metallic/release-signing-key.json`,
override with METALLIC_RELEASE_KEY). `generate` and `load_private` refuse a path inside a git work tree. The launcher
ships only public keys (`trust.json`); any listed, non-revoked key may sign, so a new key can be added before the old
one is retired.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from . import ed25519
from .manifest import SIGN_PREFIX, ManifestError, b64d, b64e

KEY_FORMAT = "metallic-release-key-v1"
TRUST_FILE = Path(__file__).with_name("trust.json")


class SigningKeyError(Exception):
    """Key file problem (missing, unsafe location, malformed)."""


def default_key_path() -> Path:
    env = os.environ.get("METALLIC_RELEASE_KEY")
    return Path(env) if env else Path.home() / ".metallic" / "release-signing-key.json"


def key_id(public: bytes) -> str:
    return hashlib.sha256(public).hexdigest()[:16]


def inside_git_worktree(path: Path) -> bool:
    resolved = Path(path).resolve()
    return any((p / ".git").exists() for p in [resolved, *resolved.parents])


def _restrict(path: Path) -> None:
    """Owner-only access: chmod on POSIX, icacls on Windows (best effort; the folder is under the user profile)."""
    try:
        if os.name == "nt":
            user = os.environ.get("USERNAME", "")
            if user:
                subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                               capture_output=True, timeout=20, check=False)
        else:
            os.chmod(path, 0o600)
    except Exception:
        pass


def generate(path: Path, allow_in_repo: bool = False) -> dict:
    path = Path(path)
    if path.exists():
        raise SigningKeyError(f"{path} already exists; refusing to overwrite a signing key")
    if inside_git_worktree(path) and not allow_in_repo:
        raise SigningKeyError(f"{path} is inside a git work tree; the signing key must stay outside every repository")
    seed = os.urandom(32)
    public = ed25519.public_key(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"format": KEY_FORMAT, "alg": "ed25519", "keyid": key_id(public), "seed": b64e(seed),
            "public": b64e(public)}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=1)
    _restrict(path)
    return {"keyid": body["keyid"], "public": body["public"], "path": str(path)}


class PrivateKey:
    def __init__(self, seed: bytes):
        self.seed = seed
        self.public = ed25519.public_key(seed)
        self.keyid = key_id(self.public)

    def sign_manifest(self, manifest_bytes: bytes) -> dict:
        sig = ed25519.sign(self.seed, SIGN_PREFIX + manifest_bytes)
        return {"keyid": self.keyid, "alg": "ed25519", "sig": b64e(sig)}


def load_private(path: Path | None = None, allow_in_repo: bool = False) -> PrivateKey:
    path = Path(path) if path else default_key_path()
    if not path.is_file():
        raise SigningKeyError(f"no signing key at {path}. Create one with: python -m launcher.updates keygen")
    if inside_git_worktree(path) and not allow_in_repo:
        raise SigningKeyError(f"{path} is inside a git work tree; move the signing key outside every repository")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("format") != KEY_FORMAT or body.get("alg") != "ed25519":
            raise ValueError("unknown key format")
        key = PrivateKey(b64d(body["seed"]))
    except (ValueError, KeyError, ManifestError) as exc:
        raise SigningKeyError(f"{path} is not a Metallic signing key: {exc}") from exc
    if body.get("keyid") and body["keyid"] != key.keyid:
        raise SigningKeyError(f"{path}: key id does not match the seed")
    return key


class TrustStore:
    """Public keys the client accepts. Built from `trust.json` or from a list in tests."""

    def __init__(self, keys: list[dict] | None = None):
        self._keys: dict[str, dict] = {}
        for k in keys or []:
            public = b64d(k["public"])
            if len(public) != 32:
                raise ManifestError("trust key is not 32 bytes")
            kid = key_id(public)
            if k.get("id") and k["id"] != kid:
                raise ManifestError(f"trust key id {k['id']} does not match its public key")
            self._keys[kid] = {"public": public, "revoked": bool(k.get("revoked")), "note": k.get("note", "")}

    @classmethod
    def load(cls, path: Path | None = None) -> "TrustStore":
        p = Path(path) if path else TRUST_FILE
        try:
            return cls(json.loads(p.read_text(encoding="utf-8")).get("keys", []))
        except FileNotFoundError:
            return cls([])

    def __len__(self) -> int:
        return sum(1 for k in self._keys.values() if not k["revoked"])

    def verify(self, manifest_bytes: bytes, sig_doc: dict) -> str:
        """Return the key id of a valid, trusted signature; raise ManifestError otherwise."""
        if not self._keys:
            raise ManifestError("no trusted signing key is installed, so updates are refused")
        sigs = sig_doc.get("signatures") if isinstance(sig_doc, dict) else None
        if not isinstance(sigs, list) or not sigs:
            raise ManifestError("signature file has no signatures")
        revoked_hit = False
        for s in sigs:
            if not isinstance(s, dict) or s.get("alg") != "ed25519":
                continue
            k = self._keys.get(s.get("keyid"))
            if k is None:
                continue
            if k["revoked"]:
                revoked_hit = True
                continue
            try:
                raw = b64d(s.get("sig", ""))
            except ManifestError:
                continue
            if ed25519.verify(k["public"], SIGN_PREFIX + manifest_bytes, raw):
                return s["keyid"]
        raise ManifestError("signing key was revoked" if revoked_hit else "no valid signature from a trusted key")


def write_trust(public_b64: str, note: str, path: Path | None = None) -> Path:
    """Add a public key to the trust list that ships with the launcher (public keys are safe to commit)."""
    p = Path(path) if path else TRUST_FILE
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"keys": []}
    kid = key_id(b64d(public_b64))
    if not any(k.get("id") == kid for k in data["keys"]):
        data["keys"].append({"id": kid, "alg": "ed25519", "public": public_b64, "note": note})
    p.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    return p
