"""Offline credential checks with an injected memory store; never opens the OS vault.

Run from any directory with the project Python environment.
"""

import sys
import json
import traceback
from pathlib import Path
from dataclasses import asdict, replace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.personal_credentials import (
    PersonalCredentials,
    CredentialRef,
    PasswordTarget,
    OSPersonalSecrets,
    canonical_origin,
)


def main():
    checks = []

    def check(name, ok):
        if not ok:
            raise AssertionError(name)
        checks.append(name)

    def rejects(name, fn, kind=Exception):
        try:
            fn()
        except kind:
            checks.append(name)
        else:
            raise AssertionError(name)

    class Memory:
        def __init__(self):
            self.records = {}
            self.gets = 0

        def put(self, k, v):
            self.records[k] = v

        def get(self, k):
            self.gets += 1
            return self.records.get(k)

    store = Memory()
    vault = PersonalCredentials(store=store, clock=lambda: 100.0)
    ref = vault.create("https://Account.Example:443/signup")
    check("canonical origin bound", ref.origin == "https://account.example")
    record = json.loads(next(iter(store.records.values())))
    password = record["password"]
    check(
        "generated length and required classes",
        len(password) == 32
        and any(c.isupper() for c in password)
        and any(c.islower() for c in password)
        and any(c.isdigit() for c in password)
        and any(not c.isalnum() for c in password),
    )
    check(
        "reference has metadata only",
        set(asdict(ref)) == {"credential_id", "origin"} and password not in repr(ref) and password not in repr(vault),
    )
    ref2 = vault.create("https://account.example")
    password2 = json.loads(list(store.records.values())[1])["password"]
    check("distinct ids and random values", ref != ref2 and password != password2)
    proof = PasswordTarget(ref.origin + "/login", ref.origin, "pw-1", "password", True, True, True, 100.0)
    filled = []
    receipt = vault.fill(ref, observe=lambda: proof, fill_password=lambda f, p: filled.append((f, p)) is None)
    check("password reaches only verified sink", filled == [("pw-1", password)] and receipt.filled)
    check(
        "receipt never contains password",
        password not in repr(receipt) and set(asdict(receipt)) == {"credential_id", "origin", "filled"},
    )
    restart = PersonalCredentials(store=store, clock=lambda: 100.0)
    check(
        "saved password reusable after helper recreation",
        restart.fill(ref, observe=lambda: proof, fill_password=lambda f, p: p == password).filled,
    )
    for name, change in [
        ("evil suffix", {"page_url": "https://account.example.evil.test"}),
        ("other port", {"page_url": "https://account.example:444"}),
        ("cross-origin field", {"field_url": "https://evil.test"}),
        ("HTTP page", {"page_url": "http://account.example"}),
        ("userinfo page", {"page_url": "https://evil@account.example"}),
        ("text field", {"input_type": "text"}),
        ("hidden field", {"visible": False}),
        ("disabled field", {"enabled": False}),
        ("unfocused field", {"focused": False}),
        ("nonboolean verification", {"visible": 1}),
        ("stale observation", {"observed_at": 97.99}),
        ("future observation", {"observed_at": 101}),
        ("NaN observation", {"observed_at": float("nan")}),
        ("boolean timestamp", {"observed_at": True}),
        ("invalid field token", {"field_id": "../../wrong"}),
    ]:
        sink = []
        rejects(
            name,
            lambda change=change: vault.fill(
                ref, observe=lambda: replace(proof, **change), fill_password=lambda f, p: sink.append(p) is None
            ),
            PermissionError,
        )
        check(name + " no disclosure", not sink)
    rejects(
        "dict proof rejected",
        lambda: vault.fill(ref, observe=lambda: asdict(proof), fill_password=lambda f, p: True),
        PermissionError,
    )
    rejects(
        "missing id fails",
        lambda: vault.fill(
            CredentialRef("credential_" + "f" * 32, ref.origin), observe=lambda: proof, fill_password=lambda f, p: True
        ),
        RuntimeError,
    )
    oldgets = store.gets
    rejects(
        "malformed id rejected before vault read",
        lambda: vault.fill(
            CredentialRef("../existing", ref.origin), observe=lambda: proof, fill_password=lambda f, p: True
        ),
        ValueError,
    )
    check("malformed ref made no read", store.gets == oldgets)
    rejects(
        "forged origin cannot find record",
        lambda: vault.fill(
            CredentialRef(ref.credential_id, "https://evil.example"),
            observe=lambda: proof,
            fill_password=lambda f, p: True,
        ),
        RuntimeError,
    )
    for bad in [
        "http://example.com",
        "https://user:pw@example.com",
        "https://example.com\\@evil.com",
        "https://example.com\n",
        "https://example.com:",
        "https://example.com:0",
        "https://example.com:65536",
        "https://example.com:+443",
        "https://example.com%40evil.test",
        "https://éxample.com",
        "https://example.com.",
        "https://127.1",
        "https://0177.0.0.1",
        "https://0x7f000001",
        "https://[::1]evil",
        "https://[::1%25eth0]",
        "https://a..example",
        "https://-a.example",
    ]:
        rejects("reject ambiguous origin " + str(len(checks)), lambda bad=bad: canonical_origin(bad), ValueError)
    check(
        "IPv6 and nondefault port canonicalized",
        canonical_origin("https://[2001:0db8::1]:8443/path") == "https://[2001:db8::1]:8443",
    )
    check("default port equivalent", canonical_origin("https://ACCOUNT.EXAMPLE:443") == ref.origin)
    for length in [True, 23, 129, "32"]:
        rejects(
            "invalid password length " + str(length),
            lambda length=length: vault.create(ref.origin, length=length),
            ValueError,
        )

    class Broken:
        def put(self, k, v):
            raise ValueError(v)

        def get(self, k):
            raise ValueError(password)

    rejects("write failure sanitized", lambda: PersonalCredentials(store=Broken()).create(ref.origin), RuntimeError)
    try:
        PersonalCredentials(store=Broken()).fill(ref, observe=lambda: proof, fill_password=lambda f, p: True)
    except RuntimeError as e:
        check("read exception sanitized", password not in "".join(traceback.format_exception(e)))

    def badsink(f, p):
        raise ValueError(p)

    try:
        vault.fill(ref, observe=lambda: proof, fill_password=badsink)
    except RuntimeError as e:
        check("sink exception sanitized", password not in "".join(traceback.format_exception(e)))
    rejects(
        "sink return not forwarded",
        lambda: vault.fill(ref, observe=lambda: proof, fill_password=lambda f, p: p),
        RuntimeError,
    )
    check("proof repr hides URLs", ref.origin not in repr(proof))
    with patch.object(OSPersonalSecrets, "_backend", side_effect=RuntimeError("backend unavailable")):
        rejects("OS storage fail closed", lambda: OSPersonalSecrets().put("test", "synthetic"), RuntimeError)
    check("dedicated namespace", OSPersonalSecrets.service == "STAR Personal Credentials v1")
    print(str(len(checks)) + " credential helper checks passed; no real keyring used")


if __name__ == "__main__":
    main()
