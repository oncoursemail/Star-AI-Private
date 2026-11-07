"""The signed channel manifest: format, validation and version ordering.

A channel (stable, beta) is one JSON file plus a detached signature file. The manifest lists components (the launcher,
Litha, later RC/MC/RB tools); each component is a folder of files with sizes and SHA-256 hashes. Files are stored by
hash, so two releases share every unchanged file and a client downloads only what changed. Large files are split into
fixed-size chunks that are hashed too, so a small in-place change to a big file costs a few chunks, not the file.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone

SCHEMA = 1
SIGN_PREFIX = b"metallic-release-manifest-v1\n"
CHUNK_THRESHOLD = 8 * 1024 * 1024  # files at least this big are chunked
CHUNK_SIZE = 1024 * 1024
MAX_TOTAL = 64 * 1024**3
CHANNEL_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_VER_RE = re.compile(r"^(\d{1,6})\.(\d{1,6})\.(\d{1,6})(?:-([0-9A-Za-z.-]{1,32}))?$")


class ManifestError(ValueError):
    """The manifest is malformed or unsafe."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fmt_time(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(text: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"bad timestamp {text!r}") from exc


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except Exception as exc:
        raise ManifestError("bad base64") from exc


# ---- versions ------------------------------------------------------------------------------------------------------

def parse_version(text: str) -> tuple:
    """Sortable key: 1.2.3 < 1.2.4 and 1.2.3-beta.1 < 1.2.3 (a pre-release sorts below its release)."""
    m = _VER_RE.match(text if isinstance(text, str) else "")
    if not m:
        raise ManifestError(f"bad version {text!r} (use MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-pre.1)")
    major, minor, patch, pre = int(m[1]), int(m[2]), int(m[3]), m[4]
    if pre is None:
        return (major, minor, patch, 1, ())
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (major, minor, patch, 0, parts)


def version_gt(a: str, b: str) -> bool:
    return parse_version(a) > parse_version(b)


# ---- paths ---------------------------------------------------------------------------------------------------------

def check_rel_path(path: str) -> str:
    """A component file path must stay inside the component folder on every OS (Windows rules included)."""
    if not isinstance(path, str) or not path or len(path) > 240:
        raise ManifestError(f"bad file path {path!r}")
    if path.startswith("/") or "\\" in path or ":" in path or "\x00" in path:
        raise ManifestError(f"unsafe file path {path!r}")
    for seg in path.split("/"):
        stem = seg.split(".")[0].lower()
        if seg in ("", ".", "..") or seg != seg.rstrip(". ") or stem in _RESERVED or any(ord(c) < 32 for c in seg):
            raise ManifestError(f"unsafe file path {path!r}")
    return path


def blob_path(pattern: str, sha: str) -> str:
    return pattern.replace("{aa}", sha[:2]).replace("{sha256}", sha)


def chunk_sizes(size: int, chunk_size: int) -> list[int]:
    full, rest = divmod(size, chunk_size)
    return [chunk_size] * full + ([rest] if rest else [])


# ---- validation ----------------------------------------------------------------------------------------------------

def validate_file(entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise ManifestError("file entry is not an object")
    path = check_rel_path(entry.get("path"))
    size, sha = entry.get("size"), entry.get("sha256")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ManifestError(f"{path}: bad size")
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        raise ManifestError(f"{path}: bad sha256")
    if "chunks" in entry:
        cs, chunks = entry.get("chunk_size"), entry["chunks"]
        if not isinstance(cs, int) or isinstance(cs, bool) or not 64 * 1024 <= cs <= 64 * 1024 * 1024:
            raise ManifestError(f"{path}: bad chunk_size")
        if not isinstance(chunks, list) or len(chunks) != len(chunk_sizes(size, cs)):
            raise ManifestError(f"{path}: chunk list does not match the size")
        if not all(isinstance(c, str) and SHA_RE.match(c) for c in chunks):
            raise ManifestError(f"{path}: bad chunk hash")
    return entry


def validate_component(name: str, comp: dict) -> dict:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ManifestError(f"bad component name {name!r}")
    if not isinstance(comp, dict):
        raise ManifestError(f"{name}: not an object")
    parse_version(comp.get("version"))
    if comp.get("min_launcher"):
        parse_version(comp["min_launcher"])
    files = comp.get("files")
    if not isinstance(files, list) or not files:
        raise ManifestError(f"{name}: no files")
    seen, total = set(), 0
    for entry in files:
        validate_file(entry)
        low = entry["path"].lower()
        if low in seen:
            raise ManifestError(f"{name}: duplicate path {entry['path']!r}")
        seen.add(low)
        total += entry["size"]
    if total > MAX_TOTAL:
        raise ManifestError(f"{name}: unreasonably large")
    inst = comp.get("installer")
    if inst is not None:
        if not isinstance(inst, dict) or not isinstance(inst.get("size"), int) or inst["size"] < 0                 or not isinstance(inst.get("sha256"), str) or not SHA_RE.match(inst["sha256"]):
            raise ManifestError(f"{name}: bad installer entry")
        check_rel_path(inst.get("path"))
    entry_file = comp.get("entry")
    if entry_file is not None and (not isinstance(entry_file, str) or entry_file.lower() not in seen):
        raise ManifestError(f"{name}: entry {entry_file!r} is not in the file list")
    return comp


def validate_manifest(m: dict, channel: str | None = None) -> dict:
    if not isinstance(m, dict) or m.get("schema") != SCHEMA:
        raise ManifestError("unsupported manifest schema")
    if m.get("product") != "metallic":
        raise ManifestError("not a Metallic manifest")
    if not isinstance(m.get("channel"), str) or not CHANNEL_RE.match(m["channel"]):
        raise ManifestError("bad channel name")
    if channel is not None and m["channel"] != channel:
        raise ManifestError(f"manifest is for channel {m['channel']!r}, not {channel!r}")
    seq = m.get("sequence")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise ManifestError("bad sequence")
    issued, expires = parse_time(m.get("issued")), parse_time(m.get("expires"))
    if expires <= issued:
        raise ManifestError("expires before issued")
    pattern = m.get("blob_pattern")
    if (not isinstance(pattern, str) or "{sha256}" not in pattern or pattern.startswith("/") or ".." in pattern
            or "\\" in pattern or ":" in pattern):
        raise ManifestError("bad blob_pattern")
    comps = m.get("components")
    if not isinstance(comps, dict):
        raise ManifestError("no components")
    for name, comp in comps.items():
        validate_component(name, comp)
    return m


def default_expiry(issued: datetime, ttl_days: int) -> datetime:
    return issued + timedelta(days=ttl_days)
