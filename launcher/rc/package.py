"""RC tools packages: the file list (build-manifest.json), safe unpacking, directory verification, release sources.

A package is a zip whose members are listed, with size and SHA-256, in its own `build-manifest.json`. A package is
only trusted after (1) the zip matches the published SHA-256 and (2) every unpacked file matches the manifest. A zip
member that is not in the manifest, or whose name could leave the target folder, makes the whole package invalid.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import Cancelled, RcError

MANIFEST_NAME = "build-manifest.json"
MAX_PACKAGE_BYTES = 1_500_000_000
MAX_FILES = 5000
_CHUNK = 1024 * 1024
Progress = Callable[[float | None, str], None]
Cancelled_ = Callable[[], bool]


@dataclass(frozen=True)
class Release:
    version: str
    name: str
    sha256: str
    size: int | None
    location: str  # local path or URL
    kind: str  # folder | url
    notes: str = ""

    def to_dict(self) -> dict:
        return {"version": self.version, "name": self.name, "sha256": self.sha256, "size": self.size,
                "kind": self.kind, "notes": self.notes}


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:4]) or (0,)


def sha256_file(path: Path, cancelled: Cancelled_ | None = None, on_bytes: Callable[[int], None] | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
            if on_bytes:
                on_bytes(len(chunk))
            if cancelled and cancelled():
                raise Cancelled()
    return h.hexdigest()


# -- manifest -------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Manifest:
    version: str
    files: tuple[tuple[str, int, str], ...]  # relative path, bytes, sha256
    raw: dict

    @property
    def total_bytes(self) -> int:
        return sum(b for _, b, _ in self.files)


def safe_relative(name: str) -> str:
    """A manifest/zip path must be relative, forward-slash and free of traversal, drive letters and control chars."""
    if (not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name or any(ord(c) < 32 for c in name)):
        raise RcError("package_invalid", detail=f"bad path {name!r}")
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise RcError("package_invalid", detail=f"bad path {name!r}")
    return name


def parse_manifest(data: bytes | str) -> Manifest:
    try:
        raw = json.loads(data)
        if raw.get("schemaVersion") != 1 or raw.get("product") != "Metallic-RC":
            raise ValueError("unsupported manifest")
        files = []
        seen = set()
        for entry in raw["files"]:
            path = safe_relative(str(entry["path"]))
            size, digest = int(entry["bytes"]), str(entry["sha256"]).lower()
            if size < 0 or not re.fullmatch(r"[0-9a-f]{64}", digest) or path.lower() in seen:
                raise ValueError(f"bad entry {path}")
            seen.add(path.lower())
            files.append((path, size, digest))
        if not files or len(files) > MAX_FILES:
            raise ValueError("file count out of range")
    except RcError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RcError("package_invalid", detail=f"manifest: {exc}") from exc
    version = str(raw.get("version") or raw.get("packageVersion") or "")
    return Manifest(version=version, files=tuple(files), raw=raw)


def read_zip_manifest(zf: zipfile.ZipFile) -> Manifest:
    try:
        with zf.open(MANIFEST_NAME) as fh:
            return parse_manifest(fh.read(8 * 1024 * 1024))
    except KeyError as exc:
        raise RcError("package_invalid", detail="no build-manifest.json") from exc


# -- unpack and verify ----------------------------------------------------------------------------------------------
def unpack(zip_path: Path, dest: Path, report: Progress, cancelled: Cancelled_ | None = None) -> Manifest:
    """Unpack into an empty `dest`, checking every file against the manifest as it is written."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise RcError("package_invalid", detail=f"not a zip: {exc}") from exc
    with zf:
        manifest = read_zip_manifest(zf)
        if manifest.total_bytes > MAX_PACKAGE_BYTES:
            raise RcError("package_invalid", detail="package too large")
        wanted = {p: (b, h) for p, b, h in manifest.files}
        members = {}
        for info in zf.infolist():
            if info.is_dir() or info.filename == MANIFEST_NAME:
                continue
            safe_relative(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RcError("package_invalid", detail=f"symbolic link {info.filename}")
            if info.filename not in wanted:
                raise RcError("package_invalid", detail=f"{info.filename} is not in the manifest")
            members[info.filename] = info
        missing = [p for p in wanted if p not in members]
        if missing:
            raise RcError("package_invalid", detail=f"{len(missing)} listed files are not in the zip, e.g. {missing[0]}")
        free = shutil.disk_usage(dest.parent if dest.parent.exists() else Path(dest.anchor or ".")).free
        if free < manifest.total_bytes * 1.1 + 50_000_000:
            raise RcError("disk_space", detail=f"need {manifest.total_bytes} bytes, {free} free")
        dest.mkdir(parents=True, exist_ok=True)
        done, total = 0, max(manifest.total_bytes, 1)
        for rel, (size, digest) in wanted.items():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            h, written = hashlib.sha256(), 0
            with zf.open(members[rel]) as src, open(target, "wb") as out:
                while chunk := src.read(_CHUNK):
                    written += len(chunk)
                    if written > size:
                        raise RcError("package_invalid", detail=f"{rel} is larger than listed")
                    h.update(chunk)
                    out.write(chunk)
                    done += len(chunk)
                    report(done / total, f"Unpacking {rel}")
                    if cancelled and cancelled():
                        raise Cancelled()
            if written != size or h.hexdigest() != digest:
                raise RcError("package_invalid", detail=f"{rel} does not match the manifest")
        (dest / MANIFEST_NAME).write_bytes(json.dumps(manifest.raw, indent=1).encode("utf-8"))
    return manifest


@dataclass
class VerifyReport:
    checked: int
    missing: list[str]
    changed: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.changed

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checked": self.checked, "missing": self.missing[:50], "changed": self.changed[:50],
                "missingCount": len(self.missing), "changedCount": len(self.changed)}


def verify_dir(folder: Path, manifest: Manifest, report: Progress, cancelled: Cancelled_ | None = None) -> VerifyReport:
    missing, changed, done, total = [], [], 0, max(manifest.total_bytes, 1)
    for rel, size, digest in manifest.files:
        path = folder / rel
        if not path.is_file():
            missing.append(rel)
            continue
        try:
            if path.stat().st_size != size:
                changed.append(rel)
                done += size
                continue

            def tick(n: int, rel=rel) -> None:
                nonlocal done
                done += n
                report(done / total, f"Checking {rel}")
            if sha256_file(path, cancelled, tick) != digest:
                changed.append(rel)
        except OSError:
            missing.append(rel)
    return VerifyReport(len(manifest.files), missing, changed)


# -- release sources ------------------------------------------------------------------------------------------------
_ZIP_NAME = re.compile(r"Metallic-RC-(?P<ver>[0-9][0-9.]*)-tools-win-x64\.zip$", re.I)


class FolderSource:
    """A folder with the package zips and a SHA256SUMS.txt, like the one the RC agent publishes."""

    kind = "folder"

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def latest(self) -> Release:
        sums = self.folder / "SHA256SUMS.txt"
        try:
            lines = sums.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise RcError("no_source", detail=f"{sums}: {exc}") from exc
        best: Release | None = None
        for line in lines:
            m = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(\S+)", line.strip())
            if not m or not (zm := _ZIP_NAME.fullmatch(m.group(2))):
                continue
            path = self.folder / m.group(2)
            if not path.is_file():
                continue
            rel = Release(zm.group("ver"), m.group(2), m.group(1).lower(), path.stat().st_size, str(path), "folder")
            if best is None or version_key(rel.version) > version_key(best.version):
                best = rel
        if best is None:
            raise RcError("no_source", detail=f"no Windows tools package listed in {sums}")
        return best

    def fetch(self, release: Release, dest: Path, report: Progress, cancelled: Cancelled_ | None = None) -> Path:
        src = Path(release.location)
        total = max(src.stat().st_size, 1)
        done = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as a, open(dest, "wb") as b:
            while chunk := a.read(_CHUNK):
                b.write(chunk)
                done += len(chunk)
                report(done / total, f"Copying {release.name}")
                if cancelled and cancelled():
                    raise Cancelled()
        return dest


class UrlSource:
    """A release address that returns {"version","url","sha256","bytes","notes"}; the url may be relative to it."""

    kind = "url"

    def __init__(self, url: str, opener: Callable | None = None):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise RcError("no_source", detail="release address must be http(s)")
        self.url = url
        self._open = opener or (lambda u, timeout: urllib.request.urlopen(u, timeout=timeout))

    def latest(self) -> Release:
        try:
            with self._open(self.url, 15) as resp:
                data = json.loads(resp.read(1_000_000))
            pkg_url = urllib.parse.urljoin(self.url, str(data["url"]))
            if urllib.parse.urlparse(pkg_url).scheme not in ("http", "https"):
                raise ValueError("package address must be http(s)")
            digest = str(data["sha256"]).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("bad sha256")
            size = int(data["bytes"]) if data.get("bytes") is not None else None
            return Release(str(data["version"]), pkg_url.rsplit("/", 1)[-1] or "package.zip", digest, size, pkg_url, "url",
                           str(data.get("notes", ""))[:500])
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as exc:
            raise RcError("download_failed", detail=f"release info: {exc}") from exc

    def fetch(self, release: Release, dest: Path, report: Progress, cancelled: Cancelled_ | None = None) -> Path:
        part = dest.with_suffix(dest.suffix + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._open(release.location, 30) as resp, open(part, "wb") as out:
                total = int(resp.headers.get("Content-Length") or release.size or 0) or None
                done = 0
                while chunk := resp.read(_CHUNK):
                    done += len(chunk)
                    if done > MAX_PACKAGE_BYTES:
                        raise RcError("package_invalid", detail="download larger than allowed")
                    out.write(chunk)
                    report(done / total if total else None, f"Downloading {release.name}")
                    if cancelled and cancelled():
                        raise Cancelled()
        except (urllib.error.URLError, OSError) as exc:
            part.unlink(missing_ok=True)
            raise RcError("download_failed", detail=str(exc)) from exc
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        part.replace(dest)
        return dest
