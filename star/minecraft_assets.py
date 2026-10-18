"""Offline Minecraft asset inspection and deterministic resource-pack packaging.

No downloads, Java execution, untrusted scripts, live server access, or pack installation.
All paths are supplied through the owner's selected, confined Workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
import zipfile

# Only versions whose Java resource-pack formats are explicitly verified here.
RESOURCE_FORMATS = {
    "1.21.4": (46, 0),
    "1.21.5": (55, 0),
    "1.21.6": (63, 0),
    "1.21.7": (64, 0),
    "1.21.8": (64, 0),
    "1.21.9": (69, 0),
    "1.21.10": (69, 0),
    "1.21.11": (75, 0),
    "26.1": (84, 0),
    "26.2": (88, 0),
    "26.3": (97, 1),
}
MAX_FILES = 4096
MAX_FILE_BYTES = 24 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_BBMODEL_BYTES = 8 * 1024 * 1024
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
NS = re.compile(r"^[a-z0-9_.-]+$")
RESOURCE_PATH = re.compile(r"^[a-z0-9_./-]+$")


def _finding(severity: str, code: str, path: str, message: str) -> dict:
    return {"severity": severity, "code": code, "path": path, "message": message}


def _normal_path(name: str) -> str:
    """Reject absolute, traversal, Windows-style, control-char and drive paths in archives."""
    if not isinstance(name, str) or not name or len(name) > 400:
        raise ValueError("Invalid pack entry name")
    if "\\" in name or ":" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("Pack entry uses unsafe path characters")
    parts = name.rstrip("/").split("/")
    if (name.startswith("/") or not parts or
            any(part in ("", ".", "..") for part in parts)):
        raise ValueError("Pack entry has an unsafe path")
    return "/".join(parts)


def _files_from_folder(root: Path) -> tuple[dict[str, bytes], list[dict]]:
    entries: dict[str, bytes] = {}
    findings = []
    total = 0
    seen: set[str] = set()
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if item.is_symlink():
            findings.append(_finding("error", "symlink", relative, "Links are not allowed in pack inputs"))
            continue
        if item.is_dir():
            continue
        if not item.is_file():
            findings.append(_finding("error", "special-file", relative, "Only regular files may be packaged"))
            continue
        try:
            name = _normal_path(relative)
        except ValueError:
            findings.append(_finding("error", "unsafe-path", relative, "Invalid resource path"))
            continue
        if name.casefold() in seen:
            findings.append(_finding("error", "case-collision", name, "Entries collide on case-insensitive clients"))
            continue
        seen.add(name.casefold())
        if len(entries) >= MAX_FILES:
            findings.append(_finding("error", "file-limit", name, "Pack exceeds file count limit"))
            break
        size = item.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            findings.append(_finding("error", "size-limit", name, "Pack exceeds bounded inspection size"))
            break
        # Resolve immediately before read, so a symlink swapped into a path cannot escape the folder.
        if not item.resolve().is_relative_to(root.resolve()):
            findings.append(_finding("error", "path-escape", name, "Entry escaped the selected pack"))
            continue
        entries[name] = item.read_bytes()
    return entries, findings


def _files_from_zip(path: Path) -> tuple[dict[str, bytes], list[dict]]:
    entries: dict[str, bytes] = {}
    findings = []
    total = 0
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES + 512:
                return {}, [_finding("error", "file-limit", path.name, "ZIP contains too many entries")]
            for info in infos:
                try:
                    name = _normal_path(info.filename)
                except ValueError:
                    findings.append(_finding("error", "unsafe-path", info.filename[:100],
                                             "ZIP path is absolute, malformed or contains traversal"))
                    continue
                if name.casefold() in seen:
                    findings.append(_finding("error", "case-collision", name, "Duplicate/colliding ZIP entry"))
                    continue
                seen.add(name.casefold())
                # UNIX symlink type 0o120000 in the upper mode bits.
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    findings.append(_finding("error", "symlink", name, "ZIP symlinks are not allowed"))
                    continue
                if info.is_dir():
                    continue
                total += info.file_size
                if (len(entries) >= MAX_FILES or info.file_size > MAX_FILE_BYTES or
                        total > MAX_TOTAL_BYTES or
                        (info.file_size > 1_000_000 and
                         info.file_size > max(info.compress_size, 1) * 200)):
                    findings.append(_finding("error", "size-limit", name,
                                             "ZIP decompression or size safety limit exceeded"))
                    break
                # file_size limits above are checked BEFORE decompressing.
                entries[name] = archive.read(info)
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        findings.append(_finding("error", "invalid-zip", path.name, type(exc).__name__))
    return entries, findings


def _json(data: bytes, path: str, findings: list[dict]) -> Any:
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError, ValueError):
        findings.append(_finding("error", "invalid-json", path, "File is not valid UTF-8 JSON"))
        return None


def _version_pair(value: Any) -> tuple[int, int] | None:
    if type(value) is int and 0 <= value < 10000:
        return (value, 0)
    if (type(value) is list and len(value) == 2 and all(type(n) is int and 0 <= n < 10000
                                                        for n in value)):
        return (value[0], value[1])
    return None


def _references(obj: Any):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("model", "parent") and isinstance(value, str):
                yield value
            yield from _references(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _references(value)


def _check_pack(entries: dict[str, bytes], findings: list[dict], version: str) -> None:
    expected = RESOURCE_FORMATS[version]
    if "pack.mcmeta" not in entries:
        findings.append(_finding("error", "missing-manifest", "pack.mcmeta",
                                 "pack.mcmeta must be at the root of the resource pack"))
        return
    manifest = _json(entries["pack.mcmeta"], "pack.mcmeta", findings)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("pack"), dict):
        findings.append(_finding("error", "invalid-manifest", "pack.mcmeta", "Missing pack object"))
        return
    pack = manifest["pack"]
    if not isinstance(pack.get("description"), (str, dict, list)):
        findings.append(_finding("warning", "missing-description", "pack.mcmeta",
                                 "Provide a pack description for Minecraft's pack menu"))
    if expected[0] >= 65:
        low = _version_pair(pack.get("min_format"))
        high = _version_pair(pack.get("max_format"))
        if low is None or high is None:
            findings.append(_finding("error", "format-range", "pack.mcmeta",
                                     "Modern packs require valid min_format and max_format"))
        elif low > high or not (low <= expected <= high):
            findings.append(_finding("error", "target-incompatible", "pack.mcmeta",
                                     f"Declared format range {low}–{high} excludes {version} ({expected})"))
    else:
        fmt = _version_pair(pack.get("pack_format"))
        if fmt is None:
            findings.append(_finding("error", "pack-format", "pack.mcmeta",
                                     "Legacy packs need integer pack_format"))
        elif fmt[0] != expected[0]:
            findings.append(_finding("warning", "target-incompatible", "pack.mcmeta",
                                     f"Pack format {fmt[0]} differs from target {version} ({expected[0]})"))
    references = []
    model_count = 0
    for name, data in entries.items():
        if name == "pack.mcmeta":
            continue
        parts = PurePosixPath(name).parts
        if parts and parts[0] == "assets" and len(parts) >= 3:
            ns = parts[1]
            if not NS.fullmatch(ns) or (len(parts) > 2 and
                                       not RESOURCE_PATH.fullmatch("/".join(parts[2:]))):
                findings.append(_finding("error", "invalid-identifier", name,
                                         "Minecraft asset namespaces and paths must be lowercase"))
        if name.lower().endswith(".png"):
            if len(data) < 24 or not data.startswith(PNG_HEADER):
                findings.append(_finding("error", "invalid-png", name, "Invalid PNG signature/header"))
            else:
                w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
                if min(w, h) == 0 or max(w, h) > 16384:
                    findings.append(_finding("error", "texture-dimensions", name,
                                             f"Unreasonable PNG dimensions {w}x{h}"))
                elif max(w, h) > 2048:
                    findings.append(_finding("warning", "large-texture", name,
                                             f"Texture {w}x{h} may affect client memory/performance"))
        elif name.lower().endswith(".ogg") and not data.startswith(b"OggS"):
            findings.append(_finding("error", "invalid-ogg", name, "Audio file is not an Ogg stream"))
        if (name.startswith("assets/") and name.endswith(".json") and
                any(f"/{segment}/" in name for segment in
                    ("models", "items", "blockstates", "particles", "font", "atlases", "equipment", "shaders"))):
            document = _json(data, name, findings)
            if "/models/" in name:
                model_count += 1
            if document is not None:
                ns = parts[1] if len(parts) > 1 else "minecraft"
                for ref in _references(document):
                    references.append((name, ns, ref))
    for source, default_ns, ref in references:
        if ref.startswith("builtin/") or ref.startswith("#"):
            continue
        ns, sep, path = ref.partition(":")
        if not sep:
            ns, path = default_ns, ns
        # References to vanilla content deliberately need not be included in a custom pack.
        if ns == "minecraft" or not NS.fullmatch(ns) or not RESOURCE_PATH.fullmatch(path):
            continue
        entry = f"assets/{ns}/models/{path}.json"
        if entry not in entries:
            findings.append(_finding("warning", "missing-model-reference", source,
                                     f"Referenced custom model '{ref}' not present in this pack; check dependencies"))
    if not model_count:
        findings.append(_finding("info", "no-models", "assets/",
                                 "Pack has no standalone Java model JSON files"))


def _check_blockbench(path: Path, findings: list[dict]) -> dict:
    if path.stat().st_size > MAX_BBMODEL_BYTES:
        findings.append(_finding("error", "size-limit", path.name, "Blockbench model exceeds 8 MiB"))
        return {}
    model = _json(path.read_bytes(), path.name, findings)
    if not isinstance(model, dict):
        findings.append(_finding("error", "invalid-model", path.name, "Expected a Blockbench JSON object"))
        return {}
    metadata = model.get("meta")
    if not isinstance(metadata, dict):
        findings.append(_finding("warning", "missing-metadata", path.name, "Missing Blockbench meta"))
    elements = model.get("elements")
    if not isinstance(elements, list):
        findings.append(_finding("error", "missing-elements", path.name, "Model elements must be an array"))
        elements = []
    textures = model.get("textures", [])
    if not isinstance(textures, list):
        findings.append(_finding("error", "missing-textures", path.name, "Model textures must be an array"))
        textures = []
    animations = model.get("animations", [])
    if not isinstance(animations, list):
        findings.append(_finding("error", "invalid-animations", path.name, "Animations must be an array"))
        animations = []
    seen = set()
    for i, el in enumerate(elements):
        if not isinstance(el, dict):
            findings.append(_finding("error", "invalid-element", f"elements/{i}", "Expected an object"))
            continue
        uid = el.get("uuid")
        if isinstance(uid, str) and uid:
            if uid in seen:
                findings.append(_finding("error", "duplicate-uuid", f"elements/{i}", "Repeated element UUID"))
            seen.add(uid)
        for key in ("from", "to"):
            vec = el.get(key)
            if vec is not None and (not isinstance(vec, list) or len(vec) != 3 or
                                    any(type(n) not in (int, float) or abs(n) > 100000 for n in vec)):
                findings.append(_finding("error", "bad-geometry", f"elements/{i}/{key}",
                                         "Expected a bounded XYZ coordinate"))
    if not elements:
        findings.append(_finding("warning", "empty-model", path.name, "No model elements to export"))
    return {"elements": len(elements), "textures": len(textures),
            "animations": len(animations), "format": metadata.get("model_format") if isinstance(metadata, dict) else None}


def audit(workspace, relative: str, *, target_version: str = "26.3") -> dict:
    """Inspect a pack folder, ZIP or .bbmodel without changing anything."""
    if target_version not in RESOURCE_FORMATS:
        raise ValueError("Unsupported Java version; choose one of the verified format mappings")
    path = workspace.resolve(relative)
    findings: list[dict] = []
    stats: dict = {}
    if path.is_file() and path.suffix.lower() == ".bbmodel":
        stats = _check_blockbench(path, findings)
        kind = "blockbench"
    elif path.is_dir() or (path.is_file() and path.suffix.lower() == ".zip"):
        entries, issues = _files_from_folder(path) if path.is_dir() else _files_from_zip(path)
        findings.extend(issues)
        # Only parse a partly-inspected pack to help diagnosis. An error always prevents packaging.
        _check_pack(entries, findings, target_version)
        stats = {"files": len(entries), "bytes": sum(map(len, entries.values())),
                 "textures": sum(p.endswith(".png") for p in entries),
                 "models": sum("/models/" in p and p.endswith(".json") for p in entries)}
        kind = "resource-pack"
    else:
        raise ValueError("Choose a Minecraft Java pack folder, .zip, or Blockbench .bbmodel")
    return {"path": relative, "kind": kind, "target_version": target_version,
            "valid": not any(f["severity"] == "error" for f in findings),
            "findings": findings[:100], "additional_findings": max(0, len(findings) - 100),
            "stats": stats, "tested_in_game": False}


def package(workspace, relative: str, output: str, *, target_version: str = "26.3",
            replace: bool = False) -> dict:
    """Package ONLY a validated directory to a new ZIP, without deploying to any live server."""
    source = workspace.resolve(relative)
    if not source.is_dir():
        raise ValueError("Input must be an existing resource-pack directory")
    destination = workspace.resolve(output, allow_missing=True)
    if destination.suffix.lower() != ".zip" or destination.is_relative_to(source):
        raise ValueError("Output must be a .zip outside the source directory")
    if destination.exists() and not replace:
        raise FileExistsError("Refusing to overwrite existing ZIP without explicit replace flag")
    report = audit(workspace, relative, target_version=target_version)
    if not report["valid"]:
        raise ValueError("Resource pack failed inspection; fix errors before packaging")
    entries, findings = _files_from_folder(source)
    if findings:
        raise ValueError("Resource pack changed or failed safety checks during packaging")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".star-pack-", suffix=".zip",
                                         dir=destination.parent, delete=False) as temp:
            staged = Path(temp.name)
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=7) as zf:
            for name, data in sorted(entries.items()):
                item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = 0o100644 << 16
                zf.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=7)
        # Use exclusive output for the default case; do not race to clobber a newly created file.
        if not replace:
            with destination.open("xb") as handle, staged.open("rb") as src:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    handle.write(chunk)
        else:
            os.replace(staged, destination)
            staged = None
        digest = hashlib.sha256()
        with destination.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"output": output, "sha256": digest.hexdigest(), "size_bytes": destination.stat().st_size,
                "files": len(entries), "target_version": target_version, "deployed": False,
                "tested_in_game": False}
    finally:
        if staged:
            staged.unlink(missing_ok=True)


def _verified_png(data: bytes) -> tuple[int, int]:
    """Verify PNG chunk framing, mandatory chunks and CRC before accepting an owner texture."""
    import zlib

    if not data.startswith(PNG_HEADER) or len(data) < 57:
        raise ValueError("Texture is not a complete PNG")
    pos = len(PNG_HEADER)
    ihdr = None
    has_idat = False
    has_iend = False
    count = 0
    while pos + 12 <= len(data) and count < 100_000:
        size = int.from_bytes(data[pos:pos+4], "big")
        if size > MAX_FILE_BYTES or pos + 12 + size > len(data):
            raise ValueError("Invalid PNG chunk length")
        name = data[pos+4:pos+8]
        chunk = data[pos+8:pos+8+size]
        crc = int.from_bytes(data[pos+8+size:pos+12+size], "big")
        if zlib.crc32(name + chunk) & 0xffffffff != crc:
            raise ValueError("PNG chunk checksum failed")
        if name == b"IHDR":
            if ihdr is not None or size != 13 or count != 0:
                raise ValueError("Invalid PNG IHDR position")
            width = int.from_bytes(chunk[0:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            if not (0 < width <= 16384 and 0 < height <= 16384):
                raise ValueError("Invalid PNG texture dimensions")
            ihdr = (width, height)
        elif name == b"IDAT":
            has_idat = True
        elif name == b"IEND":
            if size != 0 or pos + 12 != len(data):
                raise ValueError("Invalid PNG end chunk")
            has_iend = True
            break
        pos += 12 + size
        count += 1
    if ihdr is None or not has_idat or not has_iend:
        raise ValueError("PNG is missing image data or end marker")
    return ihdr


def scaffold_item(workspace, output_dir: str, *, namespace: str, item_id: str,
                  texture_path: str, target_version: str = "26.3",
                  description: str = "Minecraft custom items") -> dict:
    """Create a full modern item resource pack with an OWNER-SUPPLIED, verified PNG.

    A 2-D item asset, not a 3-D rig or plugin. No placeholder images, network access,
    plugin installation, item grants or deployment. Destination must be new.
    """
    import shutil

    if target_version not in RESOURCE_FORMATS:
        raise ValueError("Select a supported Java pack version")
    if (not isinstance(namespace, str) or not NS.fullmatch(namespace) or
            not isinstance(item_id, str) or not RESOURCE_PATH.fullmatch(item_id) or
            "/" in item_id or item_id.startswith(".")):
        raise ValueError("Namespace/item ID must be lowercase Minecraft identifiers")
    if not isinstance(description, str) or not 1 <= len(description) <= 140:
        raise ValueError("Pack description must be 1-140 characters")
    source = workspace.resolve(texture_path)
    if not source.is_file() or source.suffix.lower() != ".png" or source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Choose a PNG texture file in the selected workspace")
    image = source.read_bytes()
    dimensions = _verified_png(image)
    output = workspace.resolve(output_dir, allow_missing=True)
    if output.exists():
        raise FileExistsError("Output folder exists; this tool never overwrites an existing asset project")
    expected = RESOURCE_FORMATS[target_version]
    metadata = ({"description": description, "min_format": list(expected), "max_format": list(expected)}
                if expected[0] >= 65 else
                {"description": description, "pack_format": expected[0]})
    planned = {
        "pack.mcmeta": {"pack": metadata},
        f"assets/{namespace}/items/{item_id}.json": {
            "model": {"type": "minecraft:model", "model": f"{namespace}:item/{item_id}"}},
        f"assets/{namespace}/models/item/{item_id}.json": {
            "parent": "minecraft:item/generated", "textures": {"layer0": f"{namespace}:item/{item_id}"}},
    }
    output.mkdir(parents=True, exist_ok=False)
    try:
        for relative, data in planned.items():
            file = output / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tex = output / f"assets/{namespace}/textures/item/{item_id}.png"
        tex.parent.mkdir(parents=True, exist_ok=True)
        tex.write_bytes(image)
        report = audit(workspace, output.relative_to(workspace.root).as_posix(),
                       target_version=target_version)
        if not report["valid"]:
            raise ValueError("Generated resource pack did not pass structural validation")
        return {"output_dir": output_dir, "namespace": namespace, "item_model": f"{namespace}:{item_id}",
                "texture_dimensions": list(dimensions), "texture_sha256": hashlib.sha256(image).hexdigest(),
                "target_version": target_version, "file_count": report["stats"]["files"],
                "valid": True, "deployed": False, "tested_in_game": False,
                "next_step": "Use workspace_minecraft_package to export an archive, then test in a matching client."}
    except BaseException:
        shutil.rmtree(output)
        raise
