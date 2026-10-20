"""Import reviewed Agent Skills as inert, source-tracked reference material.

This module does NOT download skills, execute scripts, install dependencies,
approve tool access, or enable untrusted network access. Review and selection
happen outside the model. Imported skills are read by the existing SkillLibrary.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .agent_skills import _frontmatter, _NAME

# Small by design: the existing reader limits SKILL.md/references to 64 KiB.
MAX_FILES = 48
MAX_BYTES = 512_000
MAX_ONE_FILE = 64_000
TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})
ROOT_LICENSES = frozenset({"LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE", "NOTICE.md", "NOTICE.txt"})
REVIEWED_LICENSES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0"})
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
MANIFEST = ".star-source.json"


def _safe_origin(url: str, revision: str) -> tuple[str, str]:
    if not isinstance(url, str) or len(url) > 300:
        raise ValueError("A short, reviewed HTTPS repository URL is required")
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.port or parts.query or parts.fragment
            or len([part for part in parts.path.split("/") if part]) < 2
            or parts.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("Source must be a clean HTTPS repository URL (not a raw file or tokenized URL)")
    if not isinstance(revision, str) or not COMMIT_RE.fullmatch(revision):
        raise ValueError("Pin the skill to a 40-character Git commit SHA")
    return url.rstrip("/"), revision.lower()


def _files(source: Path, *, installed: bool = False) -> dict[str, bytes]:
    """Read a bounded, text-only snapshot; reject links, code and unknown files."""
    source = Path(source)
    if not source.is_dir() or source.is_symlink():
        raise ValueError("Source must be an existing, non-symlink skill directory")
    files: dict[str, bytes] = {}
    total = 0
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        parts = relative.parts
        if item.is_symlink():
            raise ValueError(f"Symlinks are not allowed in skills: {relative}")
        if relative.as_posix() == MANIFEST and installed and item.is_file():
            continue
        if not parts or any(p in {".", ".."} or p.startswith(".") for p in parts):
            raise ValueError(f"Hidden or unsafe skill path: {relative}")
        if item.is_dir():
            if parts[0] not in {"references", "assets"} or len(parts) > 5:
                raise ValueError(f"Unsupported skill directory: {relative}")
            continue
        if not item.is_file():
            raise ValueError(f"Unsupported filesystem entry: {relative}")
        if (relative.as_posix() != "SKILL.md"
                and relative.as_posix() not in ROOT_LICENSES
                and not (parts[0] in {"references", "assets"}
                         and len(parts) >= 2 and item.suffix.lower() in TEXT_SUFFIXES)):
            raise ValueError(f"Only SKILL.md, licensing and text references may be imported: {relative}")
        size = item.stat().st_size
        total += size
        if size > MAX_ONE_FILE or total > MAX_BYTES or len(files) >= MAX_FILES:
            raise ValueError("Skill exceeds reviewed file count or byte limits")
        raw = item.read_bytes()
        if len(raw) != size or b"\x00" in raw:
            raise ValueError(f"Skill content changed during reading or is binary: {relative}")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"Only UTF-8 skill text is supported: {relative}") from exc
        files[relative.as_posix()] = raw
    if "SKILL.md" not in files:
        raise ValueError("SKILL.md is required")
    return files


def _hash_files(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\x00")
        digest.update(content)
        digest.update(b"\x00")
    return digest.hexdigest()


def _inspect(source: Path, *, source_url: str, commit: str,
             license_id: str, installed: bool = False) -> tuple[dict, dict[str, bytes]]:
    url, sha = _safe_origin(source_url, commit)
    if license_id not in REVIEWED_LICENSES:
        raise PermissionError("Import requires a reviewed permissive SPDX license: "
                              + ", ".join(sorted(REVIEWED_LICENSES)))
    files = _files(source, installed=installed)
    body = files["SKILL.md"].decode("utf-8")
    fields, instructions = _frontmatter(body)
    name = fields.get("name", "")
    description = fields.get("description", "")
    if (not _NAME.fullmatch(name) or not 1 <= len(name) <= 64
            or name != Path(source).name
            or not 1 <= len(description) <= 1024 or not instructions.strip()
            or len(fields.get("compatibility", "")) > 500):
        raise ValueError("Invalid Agent Skills name, description, compatibility or body")
    # The common minimal frontmatter parser reads name/description/compatibility.
    # Check the optional license field separately; never override a conflicting declaration.
    header = body.split("\n---\n", 1)[0]
    match = re.search(r"(?m)^license:\s*([^\r\n#]+)", header)
    declared_license = match.group(1).strip().strip('"').strip("'") if match else None
    if declared_license and declared_license != license_id:
        raise PermissionError("Declared skill license disagrees with the reviewed license")
    result = {
        "name": name, "description": description, "source_url": url,
        "source_commit": sha, "license": license_id,
        "snapshot_sha256": _hash_files(files),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "mode": "text-only", "tools_granted": [],
        "warning": "Source/commit are reviewer-provided metadata, not cryptographic upstream attestation",
    }
    return result, files


def preview_skill(source: Path, *, source_url: str, commit: str, license_id: str) -> dict:
    """Validation-only preview with no network request or filesystem changes."""
    info, _ = _inspect(source, source_url=source_url, commit=commit, license_id=license_id)
    return info


def import_reviewed_skill(
    source: Path, *, home: Path, source_url: str, commit: str,
    license_id: str, approved: bool = False,
) -> dict:
    """Copy a reviewed snapshot into the personal skill directory, without overwriting.

    Only a trusted UI/CLI may set approved=True following an explicit user action.
    An LLM calling a skill or reading its prompt is never approval.
    """
    if approved is not True:
        raise PermissionError("Explicit owner approval is required to import a skill")
    info, files = _inspect(source, source_url=source_url, commit=commit, license_id=license_id)
    root = Path(home) / "skills"
    if root.is_symlink():
        raise PermissionError("Skill destination must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    target = root / info["name"]
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Existing skill is unchanged: {info['name']}")
    staging = Path(tempfile.mkdtemp(prefix=".star-reviewed-", dir=root))
    try:
        for name, content in files.items():
            output = staging / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
        (staging / MANIFEST).write_text(
            json.dumps(info, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Existing skill is unchanged: {info['name']}")
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {**info, "installed_at": str(target), "status": "imported-not-executed"}


def verify_skill(home: Path, name: str) -> dict:
    """Detect changed files relative to the stored local import snapshot.

    The manifest is NOT signed: this catches drift, not malicious manifest forgery.
    """
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("Invalid skill name")
    directory = Path(home) / "skills" / name
    if directory.is_symlink():
        return {"name": name, "ok": False, "reason": "symlink"}
    try:
        info = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
        if not isinstance(info, dict) or info.get("name") != name:
            raise ValueError("Bad manifest")
        files = _files(directory, installed=True)
        expected = info.get("files")
        actual = {path: hashlib.sha256(content).hexdigest() for path, content in sorted(files.items())}
        valid = (expected == actual and info.get("snapshot_sha256") == _hash_files(files))
        return {"name": name, "ok": valid, "reason": "unchanged" if valid else "content-drift"}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"name": name, "ok": False, "reason": type(exc).__name__}
