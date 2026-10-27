"""Install, update, verify, repair and roll back the RC tools (the Metallic.RC.Launcher.exe package).

Layout under <module>/tools:
    versions/<version>/...       one unpacked package per version, each with its own build-manifest.json
    current.json / previous.json {"version", "packageSha256", "installedAt", "source"}
The switch from one version to the next is a single atomic write of current.json after the new folder has been
fully unpacked and checked, so a failed or cancelled update leaves the old version exactly as it was.

If nothing is installed here, the older desktop build the RC agent put on this PC (rework-20261020) is *adopted*:
used in place, verified against its own manifest, never modified.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import package
from .errors import RcError
from .events import Reporter
from .package import FolderSource, Release, UrlSource, VerifyReport, version_key
from .paths import TOOLS_EXE, Paths


class ToolsInstaller:
    def __init__(self, paths: Paths, *, smoke: Callable[[Path], None] | None = None, now: Callable[[], float] = time.time):
        self.paths = paths
        self.root = paths.tools_dir
        self._smoke = smoke  # called with the new exe before the switch; raises RcError if the package does not run
        self._now = now

    # -- what is installed -----------------------------------------------------------------------------------------
    def _read(self, name: str) -> dict | None:
        try:
            data = json.loads((self.root / name).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) and isinstance(data.get("version"), str) else None
        except (OSError, ValueError):
            return None

    def _write(self, name: str, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=name + ".", suffix=".tmp", dir=self.root)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, self.root / name)

    def version_dir(self, version: str) -> Path:
        if not version or any(c in version for c in "/\\:") or version in (".", ".."):
            raise RcError("package_invalid", detail=f"bad version {version!r}")
        return self.root / "versions" / version

    def _managed(self) -> tuple[str, Path] | None:
        cur = self._read("current.json")
        if cur:
            folder = self.version_dir(cur["version"])
            if (folder / TOOLS_EXE).is_file():
                return cur["version"], folder
        return None

    def exe(self) -> Path | None:
        managed = self._managed()
        if managed:
            return managed[1] / TOOLS_EXE
        legacy = self.paths.legacy_tools_exe
        return legacy if legacy.is_file() else None

    def status(self) -> dict:
        managed, prev = self._managed(), self._read("previous.json")
        if managed:
            cur = self._read("current.json") or {}
            return {"installed": True, "kind": "managed", "version": managed[0], "exe": str(managed[1] / TOOLS_EXE),
                    "installedAt": cur.get("installedAt"), "previous": prev["version"] if prev and self.version_dir(prev["version"]).is_dir() else None}
        legacy = self.paths.legacy_tools_exe
        if legacy.is_file():
            return {"installed": True, "kind": "adopted", "version": "0.2", "exe": str(legacy), "installedAt": None,
                    "previous": None, "note": "Found the RC tools installed earlier on this PC. They are used as they are and not changed."}
        return {"installed": False, "kind": "none", "version": None, "exe": None, "installedAt": None, "previous": None}

    def _tools_folder_and_manifest(self) -> tuple[Path, package.Manifest]:
        managed = self._managed()
        folder = managed[1] if managed else self.paths.legacy_tools_exe.parent
        mf = folder / package.MANIFEST_NAME
        if not (folder / TOOLS_EXE).is_file():
            raise RcError("tools_missing")
        if not mf.is_file():
            raise RcError("tools_corrupt", detail="build-manifest.json is missing")
        try:
            return folder, package.parse_manifest(mf.read_bytes())
        except RcError as exc:
            raise RcError("tools_corrupt", detail=exc.detail) from exc

    # -- sources ---------------------------------------------------------------------------------------------------
    @staticmethod
    def make_source(setting: dict | None, paths: Paths):
        """`setting` is {"kind": "folder", "path": ...} or {"kind": "url", "url": ...}; unset means the RC agent's packages folder."""
        setting = setting or {}
        kind = setting.get("kind")
        if kind == "url" and setting.get("url"):
            return UrlSource(str(setting["url"]))
        if kind == "folder" and setting.get("path"):
            return FolderSource(Path(setting["path"]))
        if paths.legacy_packages_dir.is_dir():
            return FolderSource(paths.legacy_packages_dir)
        raise RcError("no_source")

    def check_update(self, source) -> dict:
        latest = source.latest()
        st = self.status()
        have = st["version"]
        newer = (not st["installed"]) or st["kind"] == "adopted" or (have is not None and version_key(latest.version) > version_key(have))
        return {"installed": st["installed"], "current": have, "latest": latest.to_dict(), "updateAvailable": bool(newer),
                "reason": "not installed" if not st["installed"] else ("move from the adopted copy to a managed one" if st["kind"] == "adopted" and newer else "")}

    # -- install / update / repair --------------------------------------------------------------------------------
    def install(self, source, rep: Reporter, *, release: Release | None = None, force: bool = False) -> dict:
        """Install the newest release (or `release`). Returns {"version", "changed"}. Idempotent: same version = no-op."""
        rep.stage("check", "Looking for the newest RC tools")
        release = release or source.latest()
        managed = self._managed()
        if managed and managed[0] == release.version and not force:
            rep.skip("download"), rep.skip("verify"), rep.skip("unpack"), rep.skip("switch")
            return {"version": release.version, "changed": False}
        cache = self.paths.cache_dir
        cache.mkdir(parents=True, exist_ok=True)
        zip_path = cache / release.name
        if not (zip_path.is_file() and package.sha256_file(zip_path, lambda: rep.cancelled) == release.sha256):
            rep.stage("download", f"Getting {release.name}")
            tmp = source.fetch(release, cache / (release.name + ".dl"), lambda f, d: rep.progress(f, d), lambda: rep.cancelled)
            tmp.replace(zip_path)
        else:
            rep.skip("download", "Already downloaded")
        rep.stage("verify", "Checking the package against its published SHA-256")
        total = max(zip_path.stat().st_size, 1)
        seen = [0]

        def on_bytes(n: int) -> None:
            seen[0] += n
            rep.progress(seen[0] / total)
        got = package.sha256_file(zip_path, lambda: rep.cancelled, on_bytes)
        if got != release.sha256:
            zip_path.unlink(missing_ok=True)
            raise RcError("hash_mismatch", detail=f"expected {release.sha256}, got {got}")
        final = self.version_dir(release.version)
        staging = final.with_name(final.name + ".partial")
        shutil.rmtree(staging, ignore_errors=True)
        rep.stage("unpack", "Unpacking and checking every file")
        try:
            package.unpack(zip_path, staging, lambda f, d: rep.progress(f, d), lambda: rep.cancelled)
            exe = staging / TOOLS_EXE
            if not exe.is_file():
                raise RcError("package_invalid", detail=f"{TOOLS_EXE} is not in the package")
            if self._smoke:
                rep.note("Trying the new tools")
                self._smoke(exe)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        rep.stage("switch", "Switching to the new version")
        old = self._read("current.json")
        if final.exists():  # same version reinstalled (repair): replace it, it is not the only copy of anything
            shutil.rmtree(final, ignore_errors=True)
        staging.replace(final)
        if old and old["version"] != release.version:
            self._write("previous.json", old)
        self._write("current.json", {"version": release.version, "packageSha256": release.sha256,
                                     "installedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._now())),
                                     "source": release.kind})
        self._prune()
        return {"version": release.version, "changed": True}

    def _prune(self) -> None:
        keep = {r["version"] for r in (self._read("current.json"), self._read("previous.json")) if r}
        vdir = self.root / "versions"
        if not vdir.is_dir():
            return
        for child in vdir.iterdir():
            if child.is_dir() and (child.name not in keep or child.name.endswith(".partial")):
                shutil.rmtree(child, ignore_errors=True)

    def rollback(self) -> dict:
        prev, cur = self._read("previous.json"), self._read("current.json")
        if not prev or not (self.version_dir(prev["version"]) / TOOLS_EXE).is_file():
            raise RcError("tools_missing", message="There is no earlier version to go back to.", actions=[])
        self._write("current.json", prev)
        if cur:
            self._write("previous.json", cur)
        return {"version": prev["version"]}

    # -- verify / repair ------------------------------------------------------------------------------------------
    def verify(self, rep: Reporter) -> dict:
        rep.stage("verify", "Checking every RC tool file")
        folder, manifest = self._tools_folder_and_manifest()
        report = package.verify_dir(folder, manifest, lambda f, d: rep.progress(f, d), lambda: rep.cancelled)
        return report.to_dict() | {"folder": str(folder), "kind": self.status()["kind"]}

    def repair(self, source, rep: Reporter) -> dict:
        """Verify; if anything is off, reinstall the same version from the cached or fetched package."""
        rep.stage("inspect", "Checking every RC tool file")
        try:
            folder, manifest = self._tools_folder_and_manifest()
            report = package.verify_dir(folder, manifest, lambda f, d: rep.progress(f, d), lambda: rep.cancelled)
        except RcError as exc:
            if exc.code not in ("tools_missing", "tools_corrupt"):
                raise
            report = VerifyReport(0, ["(everything)"], [])
        if report.ok:
            rep.skip("download"), rep.skip("unpack"), rep.skip("switch")
            return {"repaired": False, "checked": report.checked}
        managed = self._managed()
        release = source.latest()
        want = managed[0] if managed else release.version
        if release.version != want:  # the source moved on; repairing means the same version, so look in the cache first
            cached = [p for p in self.paths.cache_dir.glob(f"Metallic-RC-{want}-tools-win-x64.zip")] if self.paths.cache_dir.is_dir() else []
            if cached:
                release = Release(want, cached[0].name, (self._read("current.json") or {}).get("packageSha256", ""), None, str(cached[0]), "folder")
        result = self.install(source, rep, release=release, force=True)
        return {"repaired": True, "version": result["version"], "problems": len(report.missing) + len(report.changed)}
