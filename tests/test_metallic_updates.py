"""Signed update channel: signing, verification, delta downloads, resume, rollback, probation, publishing tools.

Everything runs against a local HTTP server (launcher/updates/server.py) or a folder; nothing leaves this PC.
"""
import hashlib
import json
import os
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from launcher.updates import ed25519, forge, publish as pub, server as srv
from launcher.updates.bootstrap import run_component
from launcher.updates.cli import main as cli_main
from launcher.updates.client import UpdateError, Updater, verify_dir
from launcher.updates.keys import (PrivateKey, SigningKeyError, TrustStore, generate, inside_git_worktree,
                                   load_private)
from launcher.updates.manifest import (ManifestError, check_rel_path, now_utc, parse_version, validate_manifest,
                                       version_gt)
from launcher.updates.sources import DirSource, HttpSource

# ---- helpers ---------------------------------------------------------------------------------------------------------

SEED = bytes(range(32))


def make_key(seed: bytes = SEED) -> PrivateKey:
    return PrivateKey(seed)


def trust_for(*keys: PrivateKey, revoked: tuple = ()) -> TrustStore:
    return TrustStore([{"public": base64_pub(k), "revoked": k.keyid in revoked} for k in keys])


def base64_pub(key: PrivateKey) -> str:
    import base64
    return base64.b64encode(key.public).decode()


def write_tree(folder: Path, files: dict) -> Path:
    for rel, data in files.items():
        p = folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return folder


def release(root: Path, key, channel, name, version, files, tmp_path, *, entry=None, layout="tree", now=None, **kw):
    src = write_tree(tmp_path / f"src-{name}-{version}-{channel}", files)
    kw.setdefault("chunk_threshold", 10**9)
    comp = pub.build_component(root, name, version, src, layout=layout, entry=entry, **kw)
    return pub.publish(root, channel, {name: comp}, key, layout=layout, now=now)


class Rig:
    """A release folder, a server over it, a client install folder."""

    def __init__(self, tmp_path, key=None, **client_kw):
        self.tmp, self.key = tmp_path, key or make_key()
        self.root = tmp_path / "out"
        self.root.mkdir()
        self.faults, self.log = {}, []
        self.server, self.url = srv.start(self.root, faults=self.faults, log=self.log)
        self.home = tmp_path / "install"
        self.client_kw = client_kw
        self.trust = trust_for(self.key)

    def client(self, **kw) -> Updater:
        args = {"channel": "stable", "platform": "win-x64", "launcher_version": "1.0.0", "sleep": lambda s: None,
                **self.client_kw, **kw}
        return Updater(self.home, HttpSource(self.url), kw.pop("trust", None) or self.trust, **args)

    def release(self, version, files, channel="stable", name="launcher", **kw):
        return release(self.root, self.key, channel, name, version, files, self.tmp, **kw)

    def blob_requests(self):
        return [rel for _, rel, _ in self.log if rel.startswith("blobs/")]

    def close(self):
        self.server.shutdown()


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    yield r
    r.close()


V1 = {"app.py": "print('v1')\n", "data/readme.txt": "one\n", "lib/big.bin": os.urandom(5000)}
V2 = {"app.py": "print('v2')\n", "data/readme.txt": "one\n", "lib/big.bin": V1["lib/big.bin"]}


# ---- Ed25519 ---------------------------------------------------------------------------------------------------------

RFC8032 = [  # (seed, public, message, signature) from RFC 8032 section 7.1
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46b"
     "d25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c"
     "387b2eaeb4302aeeb00d291612bb0c00"),
]


@pytest.mark.parametrize("seed,public,msg,sig", RFC8032)
def test_pure_python_matches_rfc8032_vectors(seed, public, msg, sig):
    seed, public, msg, sig = (bytes.fromhex(x) for x in (seed, public, msg, sig))
    assert ed25519._py_public(seed) == public
    assert ed25519._py_sign(seed, msg) == sig
    assert ed25519._py_verify(public, msg, sig)
    assert not ed25519._py_verify(public, msg + b"x", sig)
    bad = bytearray(sig)
    bad[10] ^= 1
    assert not ed25519._py_verify(public, msg, bytes(bad))


def test_public_api_and_accelerated_path_agree_with_pure_python():
    msg = b"channel manifest"
    sig = ed25519.sign(SEED, msg)
    assert sig == ed25519._py_sign(SEED, msg)
    assert ed25519.public_key(SEED) == ed25519._py_public(SEED)
    assert ed25519.verify(ed25519.public_key(SEED), msg, sig)
    assert not ed25519.verify(ed25519.public_key(SEED), b"other", sig)


def test_verify_never_raises_on_garbage():
    pub_key = ed25519.public_key(SEED)
    for pk, sig in [(b"", b""), (pub_key, b"x" * 63), (b"y" * 32, b"z" * 64), (pub_key, b"\xff" * 64)]:
        assert ed25519.verify(pk, b"m", sig) is False
    assert ed25519._py_verify(pub_key, b"m", b"\xff" * 64) is False


# ---- keys and trust --------------------------------------------------------------------------------------------------

def test_keygen_refuses_a_path_inside_a_git_worktree(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert inside_git_worktree(repo / "keys" / "k.json")
    with pytest.raises(SigningKeyError, match="outside every repository"):
        generate(repo / "keys" / "k.json")
    outside = generate(tmp_path / "private" / "k.json")
    assert (tmp_path / "private" / "k.json").is_file() and len(outside["keyid"]) == 16
    with pytest.raises(SigningKeyError, match="already exists"):
        generate(tmp_path / "private" / "k.json")


def test_load_private_roundtrip_and_repo_guard(tmp_path):
    info = generate(tmp_path / "k.json")
    key = load_private(tmp_path / "k.json")
    assert key.keyid == info["keyid"]
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "k.json").write_text((tmp_path / "k.json").read_text())
    with pytest.raises(SigningKeyError, match="inside a git work tree"):
        load_private(repo / "k.json")
    (tmp_path / "bad.json").write_text('{"format": "nope"}')
    with pytest.raises(SigningKeyError):
        load_private(tmp_path / "bad.json")


def test_trust_store_accepts_only_trusted_valid_signatures():
    key, other = make_key(), make_key(bytes(range(1, 33)))
    data = b'{"x": 1}\n'
    doc = {"signatures": [key.sign_manifest(data)]}
    assert trust_for(key).verify(data, doc) == key.keyid
    with pytest.raises(ManifestError, match="no valid signature"):
        trust_for(key).verify(data + b" ", doc)  # manifest changed after signing
    with pytest.raises(ManifestError, match="no valid signature"):
        trust_for(other).verify(data, doc)  # signed by a key we do not trust
    with pytest.raises(ManifestError, match="revoked"):
        trust_for(key, revoked=(key.keyid,)).verify(data, doc)
    with pytest.raises(ManifestError, match="no trusted signing key"):
        TrustStore([]).verify(data, doc)
    two = {"signatures": [other.sign_manifest(data), key.sign_manifest(data)]}  # a rotation: either key may sign
    assert trust_for(key).verify(data, two) == key.keyid


def test_signature_is_bound_to_this_format(tmp_path):
    """A signature over the same bytes without the domain prefix must not verify."""
    key = make_key()
    data = b"payload"
    raw_sig = ed25519.sign(key.seed, data)
    import base64
    doc = {"signatures": [{"keyid": key.keyid, "alg": "ed25519", "sig": base64.b64encode(raw_sig).decode()}]}
    with pytest.raises(ManifestError):
        trust_for(key).verify(data, doc)


# ---- manifest rules --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../x", "/abs", "a\\b", "C:x", "a//b", "con", "dir/NUL.txt", "a/./b", "trail.", "sp ace ",
                                 "", "x" * 300, "a\x01b"])
def test_unsafe_paths_are_rejected(bad):
    with pytest.raises(ManifestError):
        check_rel_path(bad)


def test_version_ordering():
    assert version_gt("1.2.10", "1.2.9") and version_gt("2.0.0", "1.99.99")
    assert version_gt("1.0.0", "1.0.0-beta.3") and version_gt("1.0.0-beta.10", "1.0.0-beta.2")
    assert version_gt("1.0.0-rc.1", "1.0.0-beta.9")
    with pytest.raises(ManifestError):
        parse_version("v1")


def test_duplicate_case_insensitive_paths_and_bad_chunk_lists_rejected(tmp_path):
    key = make_key()
    m = release(tmp_path / "o", key, "stable", "launcher", "1.0.0", {"a.txt": "x"}, tmp_path)
    f = dict(m["components"]["launcher"]["files"][0])
    dup = json.loads(json.dumps(m))
    dup["components"]["launcher"]["files"].append({**f, "path": "A.TXT"})
    with pytest.raises(ManifestError, match="duplicate"):
        validate_manifest(dup)
    bad = json.loads(json.dumps(m))
    bad["components"]["launcher"]["files"][0].update(chunk_size=65536, chunks=["0" * 64, "1" * 64])
    with pytest.raises(ManifestError, match="chunk list"):
        validate_manifest(bad)
    bad = json.loads(json.dumps(m))
    bad["blob_pattern"] = "../{sha256}"
    with pytest.raises(ManifestError, match="blob_pattern"):
        validate_manifest(bad)


# ---- install, delta, channels ----------------------------------------------------------------------------------------

def test_fresh_install_then_update_downloads_only_what_changed(rig):
    rig.release("1.0.0", V1, entry="app.py")
    events = []
    up = rig.client()
    plan = up.check()
    assert plan["signed_by"] == rig.key.keyid
    assert [(c["component"], c["action"]) for c in plan["components"]] == [("launcher", "install")]
    res = up.update("launcher", progress=events.append)
    assert res["ok"] and res["to"] == "1.0.0"
    stages = [e["stage"] for e in events]
    assert stages[0] == "checking" and stages.index("downloading") < stages.index("verifying") < stages.index("promoting")
    assert stages[-1] == "done"
    assert events[[e["stage"] for e in events].index("downloading")]["total"] == res["downloaded_bytes"]
    assert (rig.home / "versions/launcher/1.0.0/app.py").read_text() == "print('v1')\n"
    assert up.entry_path("launcher").name == "app.py"
    assert not (rig.home / "staging").exists() or not list((rig.home / "staging").iterdir())

    rig.release("1.1.0", V2, entry="app.py")
    rig.log.clear()
    up2 = rig.client()
    plan = up2.check()
    row = plan["components"][0]
    new_app = hashlib.sha256(V2["app.py"].encode()).hexdigest()
    assert row["action"] == "update" and row["download_bytes"] == len(V2["app.py"])
    res = up2.update("launcher")
    assert res["ok"] and res["downloaded_bytes"] == len(V2["app.py"])
    assert res["reused_bytes"] == len(V2["data/readme.txt"]) + len(V2["lib/big.bin"])
    assert rig.blob_requests() == [f"blobs/{new_app[:2]}/{new_app}"]  # one file fetched, nothing else
    assert up2.installed_version("launcher") == "1.1.0"
    assert not verify_dir(rig.home / "versions/launcher/1.1.0", json.loads(
        (rig.root / "channels/stable.json").read_text())["components"]["launcher"])
    assert up2.check()["components"][0]["action"] == "current"


def test_big_files_are_chunked_and_only_changed_chunks_download(tmp_path):
    rig = Rig(tmp_path)
    try:
        big = os.urandom(65536 * 6)
        changed = big[:65536 * 3] + os.urandom(65536) + big[65536 * 4:]
        for ver, blob in (("1.0.0", big), ("1.0.1", changed)):
            rig.release(ver, {"big.bin": blob, "small.txt": ver}, chunk_threshold=100_000, chunk_size=65536)
            if ver == "1.0.0":
                assert rig.client().update("launcher")["ok"]
        m = json.loads((rig.root / "channels/stable.json").read_text())
        f = [x for x in m["components"]["launcher"]["files"] if x["path"] == "big.bin"][0]
        assert len(f["chunks"]) == 6 and f["chunk_size"] == 65536
        rig.log.clear()
        res = rig.client().update("launcher")
        assert res["ok"] and res["downloaded_bytes"] == 65536 + len("1.0.1")
        assert (rig.home / "versions/launcher/1.0.1/big.bin").read_bytes() == changed
        assert len(rig.blob_requests()) == 2
    finally:
        rig.close()


def test_stable_and_beta_are_separate_and_promote_moves_a_release(rig):
    rig.release("1.0.0", V1, channel="stable", entry="app.py")
    rig.release("1.1.0-beta.1", V2, channel="beta", entry="app.py")
    stable, beta = rig.client(channel="stable"), rig.client(channel="beta", )
    assert stable.check()["components"][0]["available"] == "1.0.0"
    assert beta.check()["components"][0]["available"] == "1.1.0-beta.1"
    m = pub.promote(rig.root, "beta", "stable", ["launcher"], rig.key)
    assert m["components"]["launcher"]["version"] == "1.1.0-beta.1" and m["sequence"] == 2
    assert rig.client(channel="stable").check()["components"][0]["available"] == "1.1.0-beta.1"
    with pytest.raises(ManifestError, match="not in beta"):
        pub.promote(rig.root, "beta", "stable", ["nothing"], rig.key)
    # a stable manifest cannot be passed off as beta
    (rig.root / "channels/beta.json").write_bytes((rig.root / "channels/stable.json").read_bytes())
    (rig.root / "channels/beta.json.sig").write_bytes((rig.root / "channels/stable.json.sig").read_bytes())
    with pytest.raises(UpdateError, match="for channel 'stable'"):
        rig.client(channel="beta").check()


def test_two_components_in_one_channel_and_litha_can_be_removed(rig):
    rig.release("1.0.0", V1, entry="app.py")
    rig.release("0.3.0", {"litha.json": "{}", "art/bust.webp": b"RIFF"}, name="litha", min_launcher="0.9.0")
    up = rig.client()
    plan = {c["component"]: c for c in up.check()["components"]}
    assert plan["litha"]["action"] == "install" and plan["launcher"]["action"] == "install"
    assert up.update("litha")["ok"] and up.update("launcher")["ok"]
    assert up.remove("litha") and up.installed_version("litha") is None
    assert not (rig.home / "versions/litha").exists() and up.installed_version("launcher") == "1.0.0"
    old = rig.client(launcher_version="0.5.0").check()
    assert {c["component"]: c["action"] for c in old["components"]}["litha"] == "blocked"


def test_platform_specific_components_are_skipped_on_other_platforms(rig):
    rig.release("1.0.0", V1, platform="linux-x64")
    row = rig.client(platform="win-x64").check()["components"][0]
    assert row["action"] == "unsupported"
    assert not rig.client(platform="win-x64").update("launcher")["ok"]


# ---- verification: what must be refused, and what must stay untouched -------------------------------------------------

def test_tampered_manifest_is_refused_and_nothing_is_installed(rig):
    rig.release("1.0.0", V1)
    rig.faults["channels/stable.json"] = lambda d: d.replace(b'"1.0.0"', b'"9.9.9"')
    res = rig.client().update("launcher")
    assert not res["ok"] and "manifest rejected" in res["error"]
    assert not (rig.home / "versions").exists()
    with pytest.raises(UpdateError, match="manifest rejected"):
        rig.client().check()


def test_manifest_signed_by_an_unknown_key_is_refused(tmp_path):
    rig = Rig(tmp_path, key=make_key(bytes(range(7, 39))))
    try:
        rig.release("1.0.0", V1)
        client = Updater(rig.home, HttpSource(rig.url), trust_for(make_key()), channel="stable", platform="win-x64")
        with pytest.raises(UpdateError, match="no valid signature"):
            client.check()
        res = client.update("launcher")
        assert not res["ok"] and not (rig.home / "versions").exists()
    finally:
        rig.close()


def test_no_trusted_key_means_no_updates(rig):
    rig.release("1.0.0", V1)
    with pytest.raises(UpdateError, match="no trusted signing key"):
        Updater(rig.home, HttpSource(rig.url), TrustStore([]), channel="stable").check()


def test_revoked_signing_key_is_refused(rig):
    rig.release("1.0.0", V1)
    with pytest.raises(UpdateError, match="revoked"):
        rig.client(trust=trust_for(rig.key, revoked=(rig.key.keyid,))).check() if False else \
            Updater(rig.home, HttpSource(rig.url), trust_for(rig.key, revoked=(rig.key.keyid,)),
                    channel="stable").check()


def test_expired_manifest_is_refused(tmp_path):
    rig = Rig(tmp_path)
    try:
        rig.release("1.0.0", V1, now=now_utc() - timedelta(days=90))  # default ttl is 60 days
        with pytest.raises(UpdateError, match="expired"):
            rig.client().check()
        rig.release("1.0.1", V1)
        assert rig.client().check()["components"][0]["available"] == "1.0.1"
    finally:
        rig.close()


def test_replayed_old_manifest_is_refused(rig):
    rig.release("1.0.0", V1)
    old_m = (rig.root / "channels/stable.json").read_bytes()
    old_s = (rig.root / "channels/stable.json.sig").read_bytes()
    rig.release("1.1.0", V2)
    up = rig.client()
    assert up.check()["sequence"] == 2
    (rig.root / "channels/stable.json").write_bytes(old_m)  # a mirror or attacker serves the older, validly signed copy
    (rig.root / "channels/stable.json.sig").write_bytes(old_s)
    with pytest.raises(UpdateError, match="older than 2"):
        rig.client().check()


def test_corrupted_blob_is_caught_and_the_installed_version_stays(rig):
    rig.release("1.0.0", V1, entry="app.py")
    assert rig.client().update("launcher")["ok"]
    rig.release("1.1.0", V2, entry="app.py")
    sha = hashlib.sha256(V2["app.py"].encode()).hexdigest()
    rig.faults[f"blobs/{sha[:2]}/{sha}"] = lambda d: bytes(b ^ 0xFF for b in d)  # same size, wrong bytes
    res = rig.client().update("launcher")
    assert not res["ok"] and "signed hash" in res["error"]
    up = rig.client()
    assert up.installed_version("launcher") == "1.0.0"
    assert (rig.home / "versions/launcher/1.0.0/app.py").read_text() == "print('v1')\n"
    assert not (rig.home / "versions/launcher/1.1.0").exists()
    assert not list((rig.home / "staging").glob("*")) if (rig.home / "staging").exists() else True
    assert not (rig.home / "cache/blobs" / sha).exists()  # a bad blob never enters the cache
    rig.faults.clear()
    assert rig.client().update("launcher")["ok"]  # and the next honest attempt works


def test_oversized_blob_is_refused(rig):
    rig.release("1.0.0", {"a.txt": "short"})
    sha = hashlib.sha256(b"short").hexdigest()
    rig.faults[f"blobs/{sha[:2]}/{sha}"] = lambda d: d + b"MORE"
    res = rig.client().update("launcher")
    assert not res["ok"] and "longer" in res["error"]


def test_interrupted_download_resumes_with_a_range_request(rig):
    payload = os.urandom(200_000)
    rig.release("1.0.0", {"big.bin": payload})
    sha = hashlib.sha256(payload).hexdigest()
    rel = f"blobs/{sha[:2]}/{sha}"
    rig.faults[rel] = "drop-half"
    res = rig.client(retries=0).update("launcher")
    assert not res["ok"] and "download failed" in res["error"]
    part = rig.home / "cache/partial" / f"{sha}.part"
    assert 0 < part.stat().st_size < len(payload)  # the half that arrived is kept
    rig.faults.clear()
    rig.log.clear()
    res = rig.client().update("launcher")
    assert res["ok"] and (rig.home / "versions/launcher/1.0.0/big.bin").read_bytes() == payload
    ranges = [r for _, rel2, r in rig.log if rel2 == rel]
    assert ranges and ranges[0].startswith("bytes=") and not ranges[0].startswith("bytes=0-")


def test_server_that_ignores_range_still_works(tmp_path):
    root = tmp_path / "out"
    key = make_key()
    payload = os.urandom(50_000)
    release(root, key, "stable", "launcher", "1.0.0", {"big.bin": payload}, tmp_path)
    sha = hashlib.sha256(payload).hexdigest()
    handler = srv.make_handler(root)

    class NoRange(handler):
        def do_GET(self):
            self.headers.replace_header("Range", "") if self.headers.get("Range") else None
            super().do_GET()

    httpd = HTTPServer(("127.0.0.1", 0), NoRange)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        part = tmp_path / "install/cache/partial"
        part.mkdir(parents=True)
        (part / f"{sha}.part").write_bytes(payload[:20_000])
        up = Updater(tmp_path / "install", HttpSource(f"http://127.0.0.1:{httpd.server_address[1]}/"),
                     trust_for(key), channel="stable", platform="win-x64")
        assert up.update("launcher")["ok"]
        assert (tmp_path / "install/versions/launcher/1.0.0/big.bin").read_bytes() == payload
    finally:
        httpd.shutdown()


def test_missing_blob_and_unreachable_server_fail_cleanly(rig):
    rig.release("1.0.0", V1)
    sha = hashlib.sha256(V1["app.py"].encode()).hexdigest()
    rig.faults[f"blobs/{sha[:2]}/{sha}"] = "404"
    res = rig.client().update("launcher")
    assert not res["ok"] and "download failed" in res["error"]
    rig.close()
    res = rig.client().update("launcher")
    assert not res["ok"] and "unreachable" in res["error"]
    assert rig.client().installed_version("launcher") is None


def test_not_enough_disk_space_stops_before_downloading(rig, monkeypatch):
    rig.release("1.0.0", V1)
    import launcher.updates.client as client_mod
    monkeypatch.setattr(client_mod.shutil, "disk_usage", lambda p: type("U", (), {"free": 1024})())
    rig.log.clear()
    res = rig.client().update("launcher")
    assert not res["ok"] and "disk space" in res["error"]
    assert not rig.blob_requests()


def test_staged_tree_is_hashed_again_before_promotion(rig, monkeypatch):
    """If the copy that lands in staging is wrong, promotion never happens."""
    rig.release("1.0.0", V1)
    import launcher.updates.client as client_mod
    real = client_mod.shutil.copyfile

    def evil_copy(src, dst, *a, **k):
        real(src, dst, *a, **k)
        if str(dst).endswith("app.py"):
            Path(dst).write_bytes(b"print('evil')\n" + b"x" * (len(V1["app.py"]) - 14))
    monkeypatch.setattr(client_mod.shutil, "copyfile", evil_copy)
    res = rig.client().update("launcher")
    assert not res["ok"] and "failed verification" in res["error"]
    assert not (rig.home / "versions/launcher").exists()


# ---- rollback, probation, withdraw -----------------------------------------------------------------------------------

def installed_two_versions(rig):
    rig.release("1.0.0", V1, entry="app.py")
    up = rig.client()
    assert up.update("launcher")["ok"]
    up.confirm_healthy("launcher")
    rig.release("1.1.0", V2, entry="app.py")
    up = rig.client()
    assert up.update("launcher")["ok"]
    return up


def test_failed_health_check_goes_back_to_the_previous_version(rig):
    rig.release("1.0.0", V1, entry="app.py")
    up = rig.client()
    assert up.update("launcher", health_check=lambda d: True)["ok"]
    up.confirm_healthy("launcher")
    rig.release("1.1.0", V2, entry="app.py")
    res = rig.client().update("launcher", health_check=lambda d: (d / "app.py").read_text() == "print('nope')")
    assert not res["ok"] and res["rolled_back"] and "went back" in res["error"]
    up = rig.client()
    assert up.installed_version("launcher") == "1.0.0"
    row = up.check()["components"][0]
    assert row["action"] == "skipped" and "1.1.0" in row["reason"]  # does not retry the same bad release forever
    assert not (rig.home / "versions/launcher/1.1.0").exists()
    rig.release("1.1.1", V2, entry="app.py")
    assert rig.client().update("launcher", health_check=lambda d: True)["ok"]


def test_health_check_that_crashes_counts_as_failed(rig):
    rig.release("1.0.0", V1)
    up = rig.client()
    assert up.update("launcher")["ok"]
    up.confirm_healthy("launcher")
    rig.release("1.1.0", V2)

    def boom(_):
        raise RuntimeError("segfault")
    res = rig.client().update("launcher", health_check=boom)
    assert res["rolled_back"] and rig.client().installed_version("launcher") == "1.0.0"


def test_crash_loop_after_update_rolls_back_on_third_launch(rig):
    up = installed_two_versions(rig)
    assert up.status()["components"]["launcher"]["probation"] is True
    assert up.on_boot("launcher")["action"] == "ok"  # launch 1, then it dies before confirming
    assert up.on_boot("launcher")["action"] == "ok"  # launch 2
    verdict = up.on_boot("launcher")  # launch 3: switch back before starting
    assert verdict["action"] == "rolled_back" and verdict["version"] == "1.0.0"
    st = up.status()["components"]["launcher"]
    assert st["current"] == "1.0.0" and st["probation"] is False and st["failed"] == ["1.1.0"]
    assert up.on_boot("launcher")["action"] == "ok"


def test_confirming_health_ends_probation_so_no_rollback(rig):
    up = installed_two_versions(rig)
    up.on_boot("launcher")
    up.confirm_healthy("launcher")
    for _ in range(5):
        assert up.on_boot("launcher")["action"] == "ok"
    assert up.installed_version("launcher") == "1.1.0"


def test_manual_rollback_works_and_refuses_a_damaged_previous_version(rig):
    up = installed_two_versions(rig)
    prev_app = rig.home / "versions/launcher/1.0.0/app.py"
    prev_app.write_bytes(b"tampered on disk")
    res = up.rollback("launcher")
    assert not res["ok"] and "damaged" in res["error"]
    assert up.installed_version("launcher") == "1.1.0"
    prev_app.write_bytes(V1["app.py"].encode())
    res = up.rollback("launcher", reason="user asked")
    assert res["ok"] and res["to"] == "1.0.0" and up.installed_version("launcher") == "1.0.0"
    assert not up.rollback("launcher")["ok"]  # nothing further back


def test_first_install_has_nothing_to_roll_back_to(rig):
    rig.release("1.0.0", V1)
    up = rig.client()
    up.update("launcher")
    assert not up.rollback("launcher")["ok"]
    assert up.on_boot("launcher")["action"] == "ok"


def test_withdrawn_release_moves_clients_back_even_though_the_number_is_lower(rig):
    rig.release("1.0.0", V1)
    rig.release("1.1.0", V2)
    up = rig.client()
    assert up.update("launcher")["to"] == "1.1.0"
    comp = pub.build_component(rig.root, "launcher", "1.0.0", write_tree(rig.tmp / "again", V1), chunk_threshold=10**9)
    with pytest.raises(ManifestError, match="older than"):
        pub.publish(rig.root, "stable", {"launcher": comp}, rig.key)
    pub.publish(rig.root, "stable", {"launcher": comp}, rig.key, allow_downgrade=True, withdraw={"launcher": ["1.1.0"]})
    row = rig.client().check()["components"][0]
    assert row["action"] == "update" and row["available"] == "1.0.0" and "withdrawn" in row["reason"]
    assert rig.client().update("launcher")["to"] == "1.0.0"
    fresh = Updater(rig.tmp / "fresh", HttpSource(rig.url), rig.trust, channel="stable", platform="win-x64")
    assert fresh.check()["components"][0]["action"] == "install"


def test_cannot_withdraw_the_current_channel_version(rig):
    rig.release("1.0.0", V1)
    comp = json.loads((rig.root / "channels/stable.json").read_text())["components"]["launcher"]
    with pytest.raises(ManifestError, match="cannot be withdrawn"):
        pub.publish(rig.root, "stable", {}, rig.key, withdraw={"launcher": [comp["version"]]})


# ---- state robustness ------------------------------------------------------------------------------------------------

def test_leftover_staging_is_cleaned_and_state_recovers_from_backup(rig):
    rig.release("1.0.0", V1)
    up = rig.client()
    assert up.update("launcher")["ok"]
    rig.release("1.1.0", V2)
    assert rig.client().update("launcher")["ok"]  # second save leaves state.json.bak
    stale = rig.home / "staging" / "launcher-9.9.9-dead"
    stale.mkdir(parents=True)
    (rig.home / "state.json").write_text("{ this is not json")
    again = rig.client()
    assert not stale.exists()
    assert again.installed_version("launcher") == "1.0.0"  # .bak holds the state from before the last save


def test_only_one_update_at_a_time(rig):
    rig.release("1.0.0", V1)
    up = rig.client()
    (rig.home / ".lock").write_text("busy")
    res = up.update("launcher")
    assert not res["ok"] and "already running" in res["error"]
    (rig.home / ".lock").unlink()
    assert up.update("launcher")["ok"]


# ---- publishing tools ------------------------------------------------------------------------------------------------

def test_publish_writes_signed_files_changelog_and_verify_tree_catches_damage(tmp_path):
    key = make_key()
    out = tmp_path / "out"
    release(out, key, "beta", "launcher", "0.2.0", V1, tmp_path, notes="First beta.")
    release(out, key, "beta", "launcher", "0.2.1", V2, tmp_path, notes="Fix the crash.")
    log = json.loads((out / "changelog.json").read_text())["entries"]
    assert [e["version"] for e in log] == ["0.2.1", "0.2.0"] or [e["version"] for e in log] == ["0.2.0", "0.2.1"]
    assert {e["notes"] for e in log} == {"First beta.", "Fix the crash."}
    trust = trust_for(key)
    m = pub.verify_tree(out, "beta", trust)
    assert m["sequence"] == 2 and m["components"]["launcher"]["version"] == "0.2.1"
    sha = m["components"]["launcher"]["files"][0]["sha256"]
    blob = out / "blobs" / sha[:2] / sha
    blob.write_bytes(b"damaged")
    with pytest.raises(ManifestError, match="corrupt"):
        pub.verify_tree(out, "beta", trust)
    blob.unlink()
    with pytest.raises(ManifestError, match="missing"):
        pub.verify_tree(out, "beta", trust)
    with pytest.raises(ManifestError, match="expired"):
        pub.verify_tree(out, "beta", trust, now=now_utc() + timedelta(days=61))


def test_publisher_refuses_to_extend_a_manifest_it_cannot_verify(tmp_path):
    out = tmp_path / "out"
    release(out, make_key(), "stable", "launcher", "1.0.0", V1, tmp_path)
    other = make_key(bytes(range(9, 41)))
    comp = pub.build_component(out, "launcher", "1.1.0", write_tree(tmp_path / "s2", V2), chunk_threshold=10**9)
    with pytest.raises(ManifestError, match="no valid signature"):
        pub.publish(out, "stable", {"launcher": comp}, other)


def test_flat_layout_for_forge_assets_installs_too(tmp_path):
    key = make_key()
    out = tmp_path / "flat"
    release(out, key, "stable", "launcher", "1.0.0", V1, tmp_path, layout="flat")
    assert (out / "stable.json").is_file() and not (out / "channels").exists()
    up = Updater(tmp_path / "home", DirSource(out), trust_for(key), channel="stable", layout="flat", platform="win-x64")
    assert up.update("launcher")["ok"]


def test_dir_source_cannot_escape_its_folder(tmp_path):
    (tmp_path / "secret.txt").write_text("s")
    src = DirSource(tmp_path / "pub")
    (tmp_path / "pub").mkdir()
    with pytest.raises(OSError):
        src.read("../secret.txt")


def test_server_does_not_serve_outside_its_folder(rig):
    (rig.tmp / "secret.txt").write_text("s")
    with pytest.raises(OSError):
        HttpSource(rig.url).read("../secret.txt")
    with pytest.raises(OSError):
        HttpSource(rig.url).read("%2e%2e/secret.txt")


def test_http_source_only_accepts_http_urls():
    for bad in ("file:///etc/passwd", "ftp://x/y", "nonsense", ""):
        with pytest.raises(ValueError):
            HttpSource(bad)


# ---- forge upload against a fake server ------------------------------------------------------------------------------

class FakeForge(BaseHTTPRequestHandler):
    releases: dict = {}
    seen_auth: list = []

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.seen_auth.append(self.headers.get("Authorization"))
        tag = self.path.rsplit("/", 1)[-1]
        rel = self.releases.get(tag)
        self._json(200, rel) if rel else self._json(404, {})

    def do_POST(self):
        self.seen_auth.append(self.headers.get("Authorization"))
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.endswith("/releases"):
            data = json.loads(body)
            self.releases[data["tag_name"]] = {"id": 7, "tag_name": data["tag_name"], "assets": []}
            self._json(201, self.releases[data["tag_name"]])
        else:
            name = self.path.split("name=")[1]
            rel = next(iter(self.releases.values()))
            rel["assets"].append({"name": name, "id": len(rel["assets"]) + 100, "size": len(body)})
            self._json(201, {"name": name})

    def do_DELETE(self):
        asset_id = int(self.path.rsplit("/", 1)[-1])
        rel = next(iter(self.releases.values()))
        rel["assets"] = [a for a in rel["assets"] if a["id"] != asset_id]
        self._json(204, {})


def test_forge_upload_skips_existing_blobs_and_replaces_the_manifest(tmp_path):
    key, out = make_key(), tmp_path / "flat"
    release(out, key, "stable", "launcher", "1.0.0", V1, tmp_path, layout="flat")
    token = tmp_path / "token"
    token.write_text("SECRET-TOKEN-VALUE\n")
    FakeForge.releases, FakeForge.seen_auth = {}, []
    httpd = HTTPServer(("127.0.0.1", 0), FakeForge)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        first = forge.upload_release(base, token, "metallic/Metallic-Launcher", "channel-stable", out)
        n_files = len([p for p in out.iterdir() if p.is_file()])
        assert len(first["uploaded"]) == n_files and first["skipped"] == 0
        second = forge.upload_release(base, token, "metallic/Metallic-Launcher", "channel-stable", out)
        assert sorted(second["uploaded"]) == ["changelog.json", "stable.json", "stable.json.sig"]  # mutable files only
        assert second["skipped"] == n_files - 3
        assert set(FakeForge.seen_auth) == {"token SECRET-TOKEN-VALUE"}
    finally:
        httpd.shutdown()


# ---- crash-loop stub -------------------------------------------------------------------------------------------------

def test_bootstrap_falls_back_to_the_previous_version_when_the_new_one_keeps_crashing(tmp_path):
    key = make_key()
    out = tmp_path / "out"
    good = {"run.py": "import sys; sys.exit(0)\n"}
    bad = {"run.py": "import sys; sys.exit(3)\n"}
    release(out, key, "stable", "launcher", "1.0.0", good, tmp_path, entry="run.py")
    up = Updater(tmp_path / "home", DirSource(out), trust_for(key), channel="stable", platform="win-x64")
    assert up.update("launcher")["ok"]
    up.confirm_healthy("launcher")
    release(out, key, "stable", "launcher", "1.1.0", bad, tmp_path, entry="run.py")
    up = Updater(tmp_path / "home", DirSource(out), trust_for(key), channel="stable", platform="win-x64")
    assert up.update("launcher")["ok"] and up.installed_version("launcher") == "1.1.0"
    code = run_component(up, "launcher", grace=10.0, max_launches=4)
    assert up.installed_version("launcher") == "1.0.0"
    assert code == 0 or code == 3


# ---- command line, end to end ----------------------------------------------------------------------------------------

def test_cli_end_to_end_keygen_publish_verify_install_rollback(tmp_path, monkeypatch, capsys):
    keyfile = tmp_path / "private" / "key.json"
    monkeypatch.setenv("METALLIC_RELEASE_KEY", str(keyfile))
    assert cli_main(["keygen"]) == 0
    info = json.loads(capsys.readouterr().out)
    trust = tmp_path / "trust.json"
    trust.write_text(json.dumps({"keys": [{"id": info["keyid"], "alg": "ed25519", "public": info["public"]}]}))
    out = tmp_path / "out"
    for ver, files in (("1.0.0", V1), ("1.1.0", V2)):
        src = write_tree(tmp_path / f"s{ver}", files)
        assert cli_main(["publish", "--root", str(out), "--channel", "stable", "--component", "launcher",
                         "--version", ver, "--src", str(src), "--entry", "app.py", "--notes", f"release {ver}"]) == 0
        capsys.readouterr()
    assert cli_main(["verify", "--root", str(out), "--channel", "stable", "--trust", str(trust)]) == 0
    capsys.readouterr()
    home = tmp_path / "home"
    common = ["--url", str(out), "--home", str(home), "--trust", str(trust)]
    assert cli_main(["install", *common, "--component", "launcher"]) == 0
    capsys.readouterr()
    assert cli_main(["check", *common]) == 0
    assert json.loads(capsys.readouterr().out)["components"][0]["action"] == "current"
    # key reuse guard: running keygen again must not overwrite the key
    assert cli_main(["keygen"]) == 2
    # a key inside a git work tree is refused
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    monkeypatch.setenv("METALLIC_RELEASE_KEY", str(tmp_path / "repo" / "k.json"))
    assert cli_main(["keygen"]) == 2
    # a wrong trust list rejects the channel
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"keys": [{"alg": "ed25519", "public": base64_pub(make_key())}]}))
    assert cli_main(["check", "--url", str(out), "--home", str(tmp_path / "h2"), "--trust", str(wrong)]) == 2


def test_shipped_trust_list_is_valid_and_empty_until_the_owner_adds_a_key():
    ts = TrustStore.load()
    assert len(ts) == 0  # owner key is created by the owner (docs); nothing is trusted by default
    trust_json = json.loads((Path(__file__).resolve().parents[1] / "launcher/updates/trust.json").read_text())
    assert trust_json == {"keys": []} or all(k.get("id") for k in trust_json["keys"])
