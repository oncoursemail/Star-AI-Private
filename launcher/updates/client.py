"""The update client: check a channel, download only what changed, verify everything, install side by side, roll back.

Order of trust: the manifest signature is checked first (key on the trust list, not expired, sequence not older than
the newest this PC has seen). Every blob is then checked for size and SHA-256 as it arrives, the whole staged folder is
hashed again, and only then is the new version promoted by one atomic write of state.json. Old versions stay on disk
until the new one has proven itself, so a failed download, a bad file, a failed health check or a crash loop leaves the
working version in place or switches back to it.

Layout under `root`:
    state.json                          what is installed, what is on probation, the newest sequence seen
    versions/<component>/<version>/     one immutable folder per installed version (current + previous kept)
    staging/                            half-built versions; removed after any failure
    cache/blobs/<sha256>  cache/partial/<sha256>.part   verified blobs and resumable downloads
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .keys import TrustStore
from .manifest import (ManifestError, blob_path, chunk_sizes, now_utc, parse_time, parse_version, validate_manifest,
                       version_gt)
from .publish import LAYOUTS, manifest_rel
from .sources import FetchError

MAX_BOOT_ATTEMPTS = 2
SPACE_MARGIN = 64 * 1024 * 1024
CLOCK_SKEW_DAYS = 1


class UpdateError(Exception):
    """An update could not be completed. The installed version is unchanged unless `rolled_back` says otherwise."""


class IntegrityError(UpdateError):
    """Downloaded or staged bytes do not match the signed manifest."""


def platform_id() -> str:
    import sys
    return "win-x64" if sys.platform.startswith("win") else ("mac" if sys.platform == "darwin" else "linux-x64")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def verify_dir(folder: Path, comp: dict) -> list[str]:
    """Problems found comparing a component folder with its manifest record (empty list = intact)."""
    problems, expected = [], {f["path"]: f for f in comp["files"]}
    for rel, f in expected.items():
        p = folder / rel
        if not p.is_file():
            problems.append(f"missing {rel}")
        elif p.stat().st_size != f["size"]:
            problems.append(f"wrong size {rel}")
        elif _sha256_file(p) != f["sha256"]:
            problems.append(f"hash mismatch {rel}")
    if folder.is_dir():
        for p in folder.rglob("*"):
            if p.is_file() and p.relative_to(folder).as_posix() not in expected \
                    and p.name != ".metallic-component.json":
                problems.append(f"unexpected file {p.relative_to(folder).as_posix()}")
    return problems


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{uuid.uuid4().hex[:8]}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    if path.exists():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)


class Updater:
    def __init__(self, root: Path, source, trust: TrustStore, *, channel: str = "stable", layout: str = "tree",
                 platform: str | None = None, launcher_version: str = "0.0.0", now: Callable | None = None,
                 sleep: Callable[[float], None] = time.sleep, retries: int = 3):
        if layout not in LAYOUTS:
            raise ValueError("layout must be 'tree' or 'flat'")
        self.root, self.source, self.trust = Path(root), source, trust
        self.channel, self.layout = channel, layout
        self.platform = platform or platform_id()
        self.launcher_version = launcher_version
        self._now, self._sleep, self.retries = now or now_utc, sleep, retries
        self.root.mkdir(parents=True, exist_ok=True)
        self._cleanup_staging()
        self._manifest: dict | None = None
        self._signed_by = ""

    # ---- state ---------------------------------------------------------------------------------------------------
    @property
    def _state_path(self) -> Path:
        return self.root / "state.json"

    def _load(self) -> dict:
        for p in (self._state_path, self._state_path.with_name("state.json.bak")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("components"), dict):
                    data.setdefault("last_sequence", {})
                    return data
            except (OSError, ValueError):
                continue
        return {"schema": 1, "last_sequence": {}, "components": {}}

    def _save(self, state: dict) -> None:
        _atomic_json(self._state_path, state)

    @contextmanager
    def _locked(self):
        lock = self.root / ".lock"
        try:
            if lock.exists() and time.time() - lock.stat().st_mtime > 3600:
                lock.unlink()
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise UpdateError("another update is already running") from exc
        os.close(fd)
        try:
            yield
        finally:
            try:
                lock.unlink()
            except OSError:
                pass

    def _cleanup_staging(self) -> None:
        shutil.rmtree(self.root / "staging", ignore_errors=True)

    def installed_version(self, name: str) -> str | None:
        return self._load()["components"].get(name, {}).get("current")

    def current_dir(self, name: str) -> Path | None:
        ver = self.installed_version(name)
        return (self.root / "versions" / name / ver) if ver else None

    def entry_path(self, name: str) -> Path | None:
        st = self._load()["components"].get(name)
        if not st:
            return None
        entry = st["records"][st["current"]].get("entry")
        return (self.root / "versions" / name / st["current"] / entry) if entry else None

    def status(self) -> dict:
        st = self._load()
        return {"channel": self.channel, "components": {
            n: {"current": c["current"], "previous": c.get("previous"), "probation": c.get("probation", False),
                "failed": c.get("failed", [])} for n, c in st["components"].items()},
            "last_sequence": st["last_sequence"]}

    # ---- manifest ------------------------------------------------------------------------------------------------
    def fetch_manifest(self) -> dict:
        rel = manifest_rel(self.layout, self.channel)
        try:
            data = self.source.read(rel)
            sig_raw = self.source.read(rel + ".sig")
        except FetchError as exc:
            raise UpdateError(f"update server unreachable: {exc}") from exc
        try:
            sig = json.loads(sig_raw)
            signed_by = self.trust.verify(data, sig)
            manifest = validate_manifest(json.loads(data), self.channel)
        except (ValueError, ManifestError) as exc:
            raise UpdateError(f"manifest rejected: {exc}") from exc
        now = self._now()
        if parse_time(manifest["expires"]) <= now:
            raise UpdateError("manifest rejected: it has expired (the server has not been refreshed, or this PC's clock is wrong)")
        if (parse_time(manifest["issued"]) - now).days >= CLOCK_SKEW_DAYS:
            raise UpdateError("manifest rejected: it is dated in the future (check this PC's clock)")
        state = self._load()
        seen = state["last_sequence"].get(self.channel, 0)
        if manifest["sequence"] < seen:
            raise UpdateError(f"manifest rejected: sequence {manifest['sequence']} is older than {seen} already seen "
                              "(an old copy is being replayed)")
        if manifest["sequence"] > seen:
            with self._locked():
                state = self._load()
                state["last_sequence"][self.channel] = max(manifest["sequence"], state["last_sequence"].get(self.channel, 0))
                self._save(state)
        self._manifest, self._signed_by = manifest, signed_by
        return manifest

    # ---- planning ------------------------------------------------------------------------------------------------
    def _decide(self, name: str, comp: dict, st: dict | None) -> tuple[str, str]:
        ver = comp["version"]
        if comp.get("platform", "any") not in ("any", self.platform):
            return "unsupported", f"built for {comp.get('platform')}"
        if ver in comp.get("revoked", []):
            return "withdrawn", "this release was withdrawn"
        if comp.get("min_launcher") and parse_version(comp["min_launcher"]) > parse_version(self.launcher_version):
            return "blocked", f"needs launcher {comp['min_launcher']} or newer first"
        if st is None:
            return "install", ""
        cur = st["current"]
        if ver in st.get("failed", []):
            return "skipped", f"{ver} failed on this PC earlier; waiting for a newer release"
        if cur in comp.get("revoked", []):
            return "update", f"{cur} was withdrawn"
        if version_gt(ver, cur):
            return "update", ""
        return "current", ""

    def check(self) -> dict:
        """Fetch and verify the channel; say what would change. Raises UpdateError when the channel cannot be trusted."""
        manifest = self.fetch_manifest()
        state, rows = self._load(), []
        for name, comp in sorted(manifest["components"].items()):
            st = state["components"].get(name)
            action, why = self._decide(name, comp, st)
            need = self._missing_bytes(name, comp, st) if action in ("install", "update") else 0
            rows.append({"component": name, "installed": st["current"] if st else None, "available": comp["version"],
                         "action": action, "reason": why, "download_bytes": need, "size": comp.get("size", 0),
                         "notes": comp.get("notes", ""), "released": comp.get("released", "")})
        return {"channel": self.channel, "sequence": manifest["sequence"], "issued": manifest["issued"],
                "expires": manifest["expires"], "signed_by": self._signed_by, "components": rows}

    # ---- local reuse ---------------------------------------------------------------------------------------------
    def _old_files(self, name: str, st: dict | None) -> dict[str, tuple[Path, dict]]:
        if not st:
            return {}
        folder = self.root / "versions" / name / st["current"]
        return {f["path"]: (folder / f["path"], f) for f in st["records"][st["current"]]["files"]}

    def _cache(self, sha: str) -> Path:
        return self.root / "cache" / "blobs" / sha

    def _local_chunks(self, old: dict[str, tuple[Path, dict]]) -> dict[str, tuple[Path, int, int]]:
        """chunk hash -> where it sits in an installed chunked file."""
        found: dict[str, tuple[Path, int, int]] = {}
        for path, f in old.values():
            if "chunks" not in f or not path.is_file():
                continue
            sizes = chunk_sizes(f["size"], f["chunk_size"])
            for i, h in enumerate(f["chunks"]):
                found.setdefault(h, (path, i * f["chunk_size"], sizes[i]))
        return found

    def _missing_bytes(self, name: str, comp: dict, st: dict | None) -> int:
        old = self._old_files(name, st)
        chunks = self._local_chunks(old)
        total = 0
        for f in comp["files"]:
            o = old.get(f["path"])
            if o and o[1]["sha256"] == f["sha256"] and o[1]["size"] == f["size"]:
                continue
            if "chunks" in f:
                sizes = chunk_sizes(f["size"], f["chunk_size"])
                total += sum(s for h, s in zip(f["chunks"], sizes) if h not in chunks and not self._cache(h).exists())
            elif not self._cache(f["sha256"]).exists():
                total += f["size"]
        return total

    # ---- download ------------------------------------------------------------------------------------------------
    def _fetch_blob(self, pattern: str, sha: str, size: int, tick: Callable[[int], None]) -> Path:
        cached = self._cache(sha)
        if cached.is_file() and cached.stat().st_size == size:
            return cached
        rel = blob_path(pattern, sha)
        part = self.root / "cache" / "partial" / f"{sha}.part"
        part.parent.mkdir(parents=True, exist_ok=True)
        cached.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                self._sleep(min(2 ** attempt, 8))
            have = part.stat().st_size if part.exists() else 0
            if have > size:
                part.unlink()
                have = 0
            try:
                if have < size:
                    with open(part, "ab") as fh:
                        got = have
                        for block in self.source.stream(rel, have):
                            got += len(block)
                            if got > size:
                                raise IntegrityError(f"{rel} is longer than the manifest says")
                            fh.write(block)
                            tick(len(block))
                if part.stat().st_size != size:
                    raise FetchError(f"{rel} ended early ({part.stat().st_size} of {size} bytes)")
                if _sha256_file(part) != sha:
                    part.unlink()  # corrupt or resumed on top of bad bytes: start this blob again
                    raise IntegrityError(f"{rel} does not match its signed hash")
                os.replace(part, cached)
                return cached
            except FetchError as exc:  # network trouble: resume from what we have
                last_error = exc
            except IntegrityError as exc:
                last_error = exc
                part.unlink(missing_ok=True)
                if attempt >= 1:  # one clean retry is fair; a second mismatch is not network noise
                    break
        if isinstance(last_error, IntegrityError):
            raise last_error
        raise UpdateError(f"download failed: {last_error}") from last_error

    # ---- update --------------------------------------------------------------------------------------------------
    def update(self, name: str, *, progress: Callable[[dict], None] | None = None,
               health_check: Callable[[Path], bool] | None = None, manifest: dict | None = None) -> dict:
        """Install or update one component. Never raises for an expected failure: returns {"ok": False, "error": ...}."""
        emit = progress or (lambda e: None)
        result = {"component": name, "ok": False, "from": self.installed_version(name), "to": None,
                  "rolled_back": False, "downloaded_bytes": 0, "reused_bytes": 0, "error": ""}
        staging = None
        try:
            emit({"stage": "checking", "component": name})
            manifest = manifest or self._manifest or self.fetch_manifest()
            comp = manifest["components"].get(name)
            if not comp:
                raise UpdateError(f"{name} is not offered on the {self.channel} channel")
            state = self._load()
            st = state["components"].get(name)
            action, why = self._decide(name, comp, st)
            result["to"] = comp["version"]
            if action in ("unsupported", "withdrawn", "blocked", "skipped"):
                raise UpdateError(why)
            if action == "current":
                result.update(ok=True)
                emit({"stage": "done", "component": name, "version": comp["version"]})
                return result
            with self._locked():
                staging = self._stage(name, comp, st, manifest, emit, result)
                emit({"stage": "promoting", "component": name})
                self._promote(name, comp, staging, manifest)
            staging = None
            if health_check is not None:
                emit({"stage": "testing", "component": name})
                try:
                    healthy = bool(health_check(self.root / "versions" / name / comp["version"]))
                except Exception as exc:
                    healthy, why = False, f"health check crashed: {exc}"
                else:
                    why = "health check failed"
                if not healthy:
                    result["error"] = f"{comp['version']} failed its check ({why}); went back"
                    if self.rollback(name, reason=why)["ok"]:
                        result["rolled_back"] = True
                    emit({"stage": "failed", "component": name, "error": result["error"]})
                    return result
            result["ok"] = True
            emit({"stage": "done", "component": name, "version": comp["version"]})
        except (UpdateError, ManifestError, OSError) as exc:
            result["error"] = str(exc)
            emit({"stage": "failed", "component": name, "error": result["error"]})
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
        return result

    def _stage(self, name: str, comp: dict, st: dict | None, manifest: dict, emit, result: dict) -> Path:
        pattern = manifest["blob_pattern"]
        need = self._missing_bytes(name, comp, st)
        free = shutil.disk_usage(self.root).free
        if free < comp.get("size", 0) + need + SPACE_MARGIN:
            raise UpdateError(f"not enough disk space: need about {(comp.get('size', 0) + need) // 2**20 + 64} MB, "
                              f"{free // 2**20} MB free")
        staging = self.root / "staging" / f"{name}-{comp['version']}-{uuid.uuid4().hex[:8]}"
        staging.mkdir(parents=True)
        old = self._old_files(name, st)
        old_chunks = self._local_chunks(old)
        done = [0]
        total = max(need, 1)

        def tick(n: int) -> None:
            done[0] += n
            result["downloaded_bytes"] = done[0]
            emit({"stage": "downloading", "component": name, "done": done[0], "total": need,
                  "percent": round(min(done[0], total) * 100 / total, 1)})

        emit({"stage": "downloading", "component": name, "done": 0, "total": need, "percent": 0.0})
        for f in comp["files"]:
            dest = staging / f["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._build_file(dest, f, old.get(f["path"]), old_chunks, pattern, tick, result)
        emit({"stage": "verifying", "component": name})
        problems = verify_dir(staging, comp)
        if problems:
            raise IntegrityError("staged files failed verification: " + "; ".join(problems[:3]))
        (staging / ".metallic-component.json").write_text(json.dumps(
            {"component": name, "version": comp["version"], "channel": self.channel,
             "sequence": manifest["sequence"]}, indent=1), encoding="utf-8")
        return staging

    def _build_file(self, dest: Path, f: dict, old, old_chunks, pattern: str, tick, result: dict) -> None:
        if old and old[1]["sha256"] == f["sha256"] and old[1]["size"] == f["size"] and old[0].is_file():
            shutil.copyfile(old[0], dest)
            if dest.stat().st_size == f["size"] and _sha256_file(dest) == f["sha256"]:
                result["reused_bytes"] += f["size"]
                return
            dest.unlink()  # the old copy on disk was damaged: fall through and download it
        if "chunks" not in f:
            shutil.copyfile(self._fetch_blob(pattern, f["sha256"], f["size"], tick), dest)
            return
        sizes = chunk_sizes(f["size"], f["chunk_size"])
        with open(dest, "wb") as out:
            for h, n in zip(f["chunks"], sizes):
                local = old_chunks.get(h)
                data = None
                if local:
                    try:
                        with open(local[0], "rb") as src:
                            src.seek(local[1])
                            data = src.read(local[2])
                        if hashlib.sha256(data).hexdigest() != h:
                            data = None
                    except OSError:
                        data = None
                if data is not None:
                    result["reused_bytes"] += n
                else:
                    data = self._fetch_blob(pattern, h, n, tick).read_bytes()
                out.write(data)

    def _promote(self, name: str, comp: dict, staging: Path, manifest: dict) -> None:
        ver = comp["version"]
        target = self.root / "versions" / name / ver
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)  # a leftover from an interrupted run; the staged copy was just verified
        os.replace(staging, target)
        state = self._load()
        st = state["components"].get(name)
        record = {k: v for k, v in comp.items() if k != "revoked"}
        if st:
            records = {st["current"]: st["records"][st["current"]], ver: record}
            state["components"][name] = {**st, "previous": st["current"] if st["current"] != ver else st.get("previous"),
                                         "current": ver, "records": records}
        else:
            state["components"][name] = {"current": ver, "previous": None, "failed": [], "records": {ver: record}}
        c = state["components"][name]
        c.update(channel=self.channel, probation=True, boot_attempts=0)
        c["failed"] = [v for v in c.get("failed", []) if v != ver]
        self._save(state)  # the single atomic switch
        keep = {c["current"], c.get("previous")}
        for d in (self.root / "versions" / name).iterdir():
            if d.name not in keep:
                shutil.rmtree(d, ignore_errors=True)

    # ---- rollback and probation ----------------------------------------------------------------------------------
    def rollback(self, name: str, reason: str = "rolled back", mark_failed: bool = True) -> dict:
        """Switch a component back to its previous version, after checking that version is still intact."""
        with self._locked():
            state = self._load()
            st = state["components"].get(name)
            if not st or not st.get("previous"):
                return {"ok": False, "component": name, "error": "there is no earlier version to go back to"}
            prev, bad = st["previous"], st["current"]
            folder = self.root / "versions" / name / prev
            problems = verify_dir(folder, st["records"][prev]) if folder.is_dir() else ["folder is gone"]
            if problems:
                return {"ok": False, "component": name, "error": f"earlier version {prev} is damaged: {problems[0]}"}
            failed = list(st.get("failed", []))
            if mark_failed and bad not in failed:
                failed.append(bad)
            state["components"][name] = {**st, "current": prev, "previous": None, "probation": False,
                                         "boot_attempts": 0, "failed": failed, "records": {prev: st["records"][prev]},
                                         "last_rollback": {"from": bad, "reason": reason}}
            self._save(state)
            shutil.rmtree(self.root / "versions" / name / bad, ignore_errors=True)
        return {"ok": True, "component": name, "from": bad, "to": prev, "reason": reason}

    def on_boot(self, name: str) -> dict:
        """Call at the start of every launch of a component that is on probation. Switches back after repeated crashes."""
        with self._locked():
            state = self._load()
            st = state["components"].get(name)
            if not st or not st.get("probation"):
                return {"action": "ok", "version": st["current"] if st else None}
            if st.get("boot_attempts", 0) >= MAX_BOOT_ATTEMPTS:
                pass
            else:
                st["boot_attempts"] = st.get("boot_attempts", 0) + 1
                self._save(state)
                return {"action": "ok", "version": st["current"], "probation": True, "attempt": st["boot_attempts"]}
        res = self.rollback(name, reason=f"{st['current']} did not reach a healthy start {MAX_BOOT_ATTEMPTS} times")
        if res["ok"]:
            return {"action": "rolled_back", "version": res["to"], "from": res["from"]}
        return {"action": "ok", "version": st["current"], "warning": res["error"]}

    def confirm_healthy(self, name: str) -> None:
        """Call once the component has really started (UI loaded, service answering). Ends probation."""
        with self._locked():
            state = self._load()
            st = state["components"].get(name)
            if st and st.get("probation"):
                st.update(probation=False, boot_attempts=0)
                self._save(state)

    def remove(self, name: str) -> bool:
        """Uninstall a component (for example the Litha add-on)."""
        with self._locked():
            state = self._load()
            if name not in state["components"]:
                return False
            del state["components"][name]
            self._save(state)
            shutil.rmtree(self.root / "versions" / name, ignore_errors=True)
        return True

    def repair(self, name: str) -> list[str]:
        """Problems in the installed current version (empty = intact). A caller can re-run update() after reinstall()."""
        st = self._load()["components"].get(name)
        if not st:
            return ["not installed"]
        return verify_dir(self.root / "versions" / name / st["current"], st["records"][st["current"]])
