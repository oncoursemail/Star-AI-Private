"""Host-only saved passwords for STAR's own accounts; no plaintext fallback.

Not wired to model tools or computer control. The integrating trusted host must
independently authenticate its observer/sink callbacks and keep navigation and
field selection stable during a fill. These Python callbacks are not a sandbox.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ipaddress
import json
import math
import re
import secrets
import string
import time
from typing import Callable
from urllib.parse import urlsplit
import uuid

from .bulk_profiles import OSProfileSecrets


_ID = re.compile(r"credential_[0-9a-f]{32}\Z")
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_FIELD = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
_ALPHABET = string.ascii_letters + string.digits + "!#$%&*+-=?@^_"


def canonical_origin(url: str) -> str:
    """An unambiguous HTTPS origin, preserving every nondefault port.

    URL paths are allowed for observed pages, but credentials/userinfo, Unicode
    authorities, escaped hosts and browser-ambiguous numeric hosts are rejected.
    No network resolution or page access occurs.
    """
    try:
        if (not isinstance(url, str) or not 1 <= len(url) <= 4096
                or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url):
            raise ValueError
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.netloc or parsed.username is not None
                or parsed.password is not None or not parsed.netloc.isascii() or "%" in parsed.netloc):
            raise ValueError
        host = parsed.hostname
        if not host or host.endswith("."):
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        if parsed.netloc.endswith(":"):
            raise ValueError
        if ":" in host:
            if not re.fullmatch(r"\[[0-9A-Fa-f:.]+\](?::[0-9]+)?", parsed.netloc):
                raise ValueError
            host = "[" + ipaddress.IPv6Address(host).compressed + "]"
        else:
            if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc):
                raise ValueError
            try:
                host = str(ipaddress.IPv4Address(host))
            except ValueError:
                last_label = host.rsplit(".", 1)[-1]
                if (len(host) > 253 or re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", last_label)
                        or any(not _LABEL.fullmatch(label) for label in host.split("."))):
                    raise ValueError
        return "https://" + host + (f":{port}" if port is not None and port != 443 else "")
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid, unambiguous HTTPS origin is required") from None


@dataclass(frozen=True)
class CredentialRef:
    credential_id: str
    origin: str

    def validate(self) -> "CredentialRef":
        if (not isinstance(self.credential_id, str) or not _ID.fullmatch(self.credential_id)
                or canonical_origin(self.origin) != self.origin):
            raise ValueError("Invalid STAR credential reference")
        return self


@dataclass(frozen=True, repr=False)
class PasswordTarget:
    """Observation supplied by the trusted host, never accepted from the model."""
    page_url: str
    field_url: str
    field_id: str
    input_type: str
    visible: bool
    enabled: bool
    focused: bool
    observed_at: float


@dataclass(frozen=True)
class FillReceipt:
    credential_id: str
    origin: str
    filled: bool


class OSPersonalSecrets(OSProfileSecrets):
    """Reuse the strict, native OS backend allowlist; never enumerate credentials."""
    service = "STAR Personal Credentials v1"

    def put(self, account: str, secret: str) -> None:
        try:
            self._backend().set_password(self.service, account, secret)
        except Exception:
            raise RuntimeError("Could not save STAR's password in secure OS storage") from None

    def get(self, account: str) -> str | None:
        try:
            value = self._backend().get_password(self.service, account)
            return value if isinstance(value, str) and value else None
        except Exception:
            raise RuntimeError("STAR's secure password storage is unavailable") from None


class PersonalCredentials:
    """Generate/store/fill only STAR-owned entries under an opaque reference.

    Keep references in owner-local settings outside source control. There is no
    password-returning method, import path, account creation or automatic login.
    """

    def __init__(self, *, store=None, clock: Callable[[], float] = time.monotonic):
        self._store = store if store is not None else OSPersonalSecrets()
        self._clock = clock

    @staticmethod
    def _account(ref: CredentialRef) -> str:
        ref.validate()
        return ref.credential_id + ":" + sha256(ref.origin.encode("ascii")).hexdigest()

    def create(self, origin: str, *, length: int = 32) -> CredentialRef:
        """Generate inside the host and save; return metadata only, never the password."""
        origin = canonical_origin(origin)
        if type(length) is not int or not 24 <= length <= 128:
            raise ValueError("Password length must be between 24 and 128 characters")
        ref = CredentialRef("credential_" + uuid.uuid4().hex, origin)
        # Rejection sampling preserves uniformity while satisfying common site
        # requirements. Site-specific rules must be handled in the host review.
        while True:
            password = "".join(secrets.choice(_ALPHABET) for _ in range(length))
            if (any(c.islower() for c in password) and any(c.isupper() for c in password)
                    and any(c.isdigit() for c in password) and any(c in "!#$%&*+-=?@^_" for c in password)):
                break
        record = json.dumps({"version": 1, "origin": origin, "password": password}, separators=(",", ":"))
        try:
            self._store.put(self._account(ref), record)
        except Exception:
            raise RuntimeError("STAR's password could not be saved securely") from None
        finally:
            del password, record
        return ref

    def fill(self, ref: CredentialRef, *, observe: Callable[[], PasswordTarget],
             fill_password: Callable[[str, str], bool]) -> FillReceipt:
        """Pass a password only to a trusted sink after a fresh matching host observation.

        `fill_password(field_id, password)` must fill just that verified field
        and return True. Its return value and exceptions are never forwarded.
        It must not log, copy to a shared clipboard, submit or navigate.
        """
        if not isinstance(ref, CredentialRef):
            raise ValueError("A STAR credential reference is required")
        account = self._account(ref)
        if not callable(observe) or not callable(fill_password):
            raise ValueError("Trusted host observer and password sink are required")
        password = record = raw = None
        try:
            try:
                raw = self._store.get(account)
                if not isinstance(raw, str) or not 1 <= len(raw) <= 1024:
                    raise ValueError
                record = json.loads(raw)
                if (not isinstance(record, dict) or set(record) != {"version", "origin", "password"}
                        or type(record["version"]) is not int or record["version"] != 1
                        or record["origin"] != ref.origin or not isinstance(record["password"], str)
                        or not 24 <= len(record["password"]) <= 128
                        or any(c not in _ALPHABET for c in record["password"])):
                    raise ValueError
                password = record["password"]
            except Exception:
                raise RuntimeError("STAR's saved password is unavailable or invalid") from None
            try:
                target = observe()
                now = self._clock()
                if (not isinstance(target, PasswordTarget)
                        or canonical_origin(target.page_url) != ref.origin
                        or canonical_origin(target.field_url) != ref.origin
                        or not isinstance(target.field_id, str) or not _FIELD.fullmatch(target.field_id)
                        or target.input_type != "password"
                        or target.visible is not True or target.enabled is not True or target.focused is not True
                        or type(target.observed_at) not in (float, int) or not math.isfinite(target.observed_at)
                        or not math.isfinite(now) or not 0 <= now - target.observed_at <= 2.0):
                    raise ValueError
            except Exception:
                raise PermissionError("A fresh matching HTTPS password field could not be verified") from None
            try:
                if fill_password(target.field_id, password) is not True:
                    raise RuntimeError
            except Exception:
                raise RuntimeError("The trusted host could not fill STAR's password field") from None
            return FillReceipt(ref.credential_id, ref.origin, True)
        finally:
            # Python strings cannot be reliably wiped; do not imply zeroization.
            del password, record, raw


def main() -> None:
    """Read-only backend status or an in-memory demonstration; no live credential writes."""
    import argparse
    from dataclasses import asdict

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "simulate"))
    args = parser.parse_args()
    if args.command == "status":
        try:
            OSPersonalSecrets._backend()
            available = True
        except Exception:
            available = False
        print(json.dumps({"secure_backend_available": available, "live_integration": False,
                          "passwords_read": 0, "passwords_written": 0}))
        return

    class MemoryStore:
        def __init__(self):
            self.records = {}

        def put(self, account, value):
            self.records[account] = value

        def get(self, account):
            return self.records.get(account)

    vault = PersonalCredentials(store=MemoryStore())
    ref = vault.create("https://star-demo.example")
    receipt = vault.fill(ref, observe=lambda: PasswordTarget(ref.origin, ref.origin, "password-field", "password",
                                                            True, True, True, time.monotonic()),
                         fill_password=lambda field, password: field == "password-field" and len(password) == 32)
    print(json.dumps({"simulation_only": True, "credential": asdict(ref), "receipt": asdict(receipt),
                      "real_passwords_saved": 0}))


if __name__ == "__main__":
    main()
