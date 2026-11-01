"""Owner-side release tooling: turn a folder into content-addressed blobs, sign a channel manifest, promote.

Output tree (static files, host anywhere):
    channels/stable.json  channels/stable.json.sig  channels/beta.json ...   (layout "tree")
    blobs/ab/abcdef...                                                      (files, or chunks of big files)
    changelog.json                                                          (informational, for the site and PX)
Layout "flat" keeps everything in one folder (`stable.json`, `<sha256>` blobs) because forge release assets are flat.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .keys import PrivateKey, TrustStore
from .manifest import (CHUNK_SIZE, CHUNK_THRESHOLD, SCHEMA, ManifestError, b64e, blob_path, check_rel_path, default_expiry,
                       fmt_time, now_utc, parse_time, validate_component, validate_manifest, version_gt)

LAYOUTS = {"tree": ("channels/{channel}.json", "blobs/{aa}/{sha256}"), "flat": ("{channel}.json", "{sha256}")}
IGNORED = {"__pycache__", ".git", ".DS_Store", "Thumbs.db"}


def manifest_rel(layout: str, channel: str) -> str:
    return LAYOUTS[layout][0].format(channel=channel)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _store_blob(root: Path, pattern: str, sha: str, data: bytes) -> None:
    dest = root / blob_path(pattern, sha)
    if not dest.exists():
        _atomic_write(dest, data)


def _iter_files(src: Path):
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if any(part in IGNORED or part.endswith(".pyc") for part in rel.parts) or not p.is_file():
            continue
        yield rel.as_posix(), p


def build_component(root: Path, name: str, version: str, src: Path, *, layout: str = "tree", entry: str | None = None,
                    notes: str = "", platform: str = "any", min_launcher: str | None = None,
                    chunk_threshold: int = CHUNK_THRESHOLD, chunk_size: int = CHUNK_SIZE,
                    released: str | None = None, installer: Path | None = None) -> dict:
    """Hash every file in `src`, store the blobs under `root`, return the component record."""
    src, root = Path(src), Path(root)
    if not src.is_dir():
        raise ManifestError(f"{src} is not a folder")
    pattern = LAYOUTS[layout][1]
    files = []
    for rel, path in _iter_files(src):
        check_rel_path(rel)
        size = path.stat().st_size
        whole = hashlib.sha256()
        item: dict = {"path": rel, "size": size}
        if size >= chunk_threshold:
            chunks = []
            with open(path, "rb") as fh:
                while True:
                    block = fh.read(chunk_size)
                    if not block:
                        break
                    whole.update(block)
                    h = hashlib.sha256(block).hexdigest()
                    chunks.append(h)
                    _store_blob(root, pattern, h, block)
            item.update(sha256=whole.hexdigest(), chunk_size=chunk_size, chunks=chunks)
        else:
            data = path.read_bytes()
            item["sha256"] = hashlib.sha256(data).hexdigest()
            _store_blob(root, pattern, item["sha256"], data)
        files.append(item)
    if not files:
        raise ManifestError(f"{src} has no files")
    comp: dict = {"version": version, "platform": platform, "released": released or fmt_time(now_utc()),
                  "size": sum(f["size"] for f in files), "notes": notes, "files": files}
    if entry:
        comp["entry"] = entry
    if installer:  # a first-install download for the website; updates never use it
        installer = Path(installer)
        rel = f"installers/{name}-{version}-{platform}{installer.suffix}"
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(installer, dest)
        comp["installer"] = {"path": rel, "size": dest.stat().st_size, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}
    if min_launcher:
        comp["min_launcher"] = min_launcher
    validate_component(name, comp)
    return comp


def _read_signed(root: Path, layout: str, channel: str, trust: TrustStore | None) -> dict | None:
    mpath = root / manifest_rel(layout, channel)
    if not mpath.is_file():
        return None
    data = mpath.read_bytes()
    if trust is not None:
        sig = json.loads((mpath.with_name(mpath.name + ".sig")).read_text(encoding="utf-8"))
        trust.verify(data, sig)
    return validate_manifest(json.loads(data), channel)


def write_manifest(root: Path, layout: str, manifest: dict, key: PrivateKey) -> Path:
    validate_manifest(manifest)
    data = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode("utf-8")
    mpath = Path(root) / manifest_rel(layout, manifest["channel"])
    sig = json.dumps({"schema": SCHEMA, "signatures": [key.sign_manifest(data)]}, indent=1).encode("utf-8")
    # signature first: a reader that sees a new manifest never pairs it with an old signature for long
    _atomic_write(mpath.with_name(mpath.name + ".sig"), sig)
    _atomic_write(mpath, data)
    return mpath


def _append_changelog(root: Path, channel: str, name: str, comp: dict) -> None:
    path = Path(root) / "changelog.json"
    log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema": 1, "entries": []}
    key = (channel, name, comp["version"])
    if any((e["channel"], e["component"], e["version"]) == key for e in log["entries"]):
        return
    log["entries"].append({"channel": channel, "component": name, "version": comp["version"],
                           "released": comp.get("released", ""), "notes": comp.get("notes", "")})
    log["entries"].sort(key=lambda e: e["released"], reverse=True)
    _atomic_write(path, (json.dumps(log, indent=1) + "\n").encode("utf-8"))


def publish(root: Path, channel: str, components: dict[str, dict], key: PrivateKey, *, layout: str = "tree",
            ttl_days: int = 60, withdraw: dict[str, list[str]] | None = None, allow_downgrade: bool = False,
            force: bool = False, now=None) -> dict:
    """Add or replace components in a channel, bump the sequence, sign and write. Returns the manifest."""
    root = Path(root)
    now = now or now_utc()
    prev = _read_signed(root, layout, channel, None if force else TrustStore([{"public": b64e(key.public)}]))
    manifest = prev or {"schema": SCHEMA, "product": "metallic", "channel": channel, "sequence": 0, "components": {}}
    manifest["blob_pattern"] = LAYOUTS[layout][1]
    for name, comp in components.items():
        old = manifest["components"].get(name)
        if old and not allow_downgrade and not version_gt(comp["version"], old["version"]) \
                and comp["version"] != old["version"]:
            raise ManifestError(f"{name} {comp['version']} is older than {old['version']} in {channel}; "
                                f"use --allow-downgrade, or --withdraw {old['version']} to pull a bad release")
        new = dict(comp)
        if old and old.get("revoked"):
            new["revoked"] = old["revoked"]
        manifest["components"][name] = new
        _append_changelog(root, channel, name, comp)
    for name, versions in (withdraw or {}).items():
        comp = manifest["components"].get(name)
        if not comp:
            raise ManifestError(f"cannot withdraw from unknown component {name!r}")
        comp["revoked"] = sorted(set(comp.get("revoked", [])) | set(versions))
        if comp["version"] in comp["revoked"]:
            raise ManifestError(f"{name}: the channel's own version {comp['version']} cannot be withdrawn")
    manifest["sequence"] += 1
    manifest["issued"] = fmt_time(now)
    manifest["expires"] = fmt_time(default_expiry(now, ttl_days))
    write_manifest(root, layout, manifest, key)
    return manifest


def promote(root: Path, src_channel: str, dst_channel: str, names: list[str] | None, key: PrivateKey, *,
            layout: str = "tree", ttl_days: int = 60, now=None) -> dict:
    """Copy components from one channel (usually beta) into another (stable) as a new signed manifest."""
    root = Path(root)
    trust = TrustStore([{"public": b64e(key.public)}])
    src = _read_signed(root, layout, src_channel, trust)
    if src is None:
        raise ManifestError(f"channel {src_channel!r} has no manifest in {root}")
    chosen = {n: src["components"][n] for n in (names or list(src["components"])) if n in src["components"]}
    missing = set(names or []) - set(chosen)
    if missing:
        raise ManifestError(f"not in {src_channel}: {', '.join(sorted(missing))}")
    return publish(root, dst_channel, {n: {k: v for k, v in c.items() if k != "revoked"} for n, c in chosen.items()},
                   key, layout=layout, ttl_days=ttl_days, now=now)


def verify_tree(root: Path, channel: str, trust: TrustStore, layout: str = "tree", now=None) -> dict:
    """Publisher self-check: signature valid, not expired, every referenced blob present with the right hash."""
    root = Path(root)
    manifest = _read_signed(root, layout, channel, trust)
    if manifest is None:
        raise ManifestError(f"no manifest for channel {channel!r}")
    if parse_time(manifest["expires"]) <= (now or now_utc()):
        raise ManifestError("manifest has expired")
    problems = []
    for name, comp in manifest["components"].items():
        for f in comp["files"]:
            for sha in f.get("chunks") or [f["sha256"]]:
                p = root / blob_path(manifest["blob_pattern"], sha)
                if not p.is_file():
                    problems.append(f"{name}/{f['path']}: blob {sha[:12]} missing")
                elif hashlib.sha256(p.read_bytes()).hexdigest() != sha:
                    problems.append(f"{name}/{f['path']}: blob {sha[:12]} is corrupt")
    if problems:
        raise ManifestError("; ".join(problems[:5]))
    return manifest
