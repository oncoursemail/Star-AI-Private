"""Read-only PS3 game and recompilation tools attached to STAR's existing optional RE gateway.

Inputs are files in the selected workspace or in the owner's own PS3 game (an ISO
image or extracted game folder chosen in Settings as `re_game_path`), read in place.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from .re_analysis_input import (
    MAX_ELF_BYTES,
    MAX_JSON_BYTES,
    InputSpec,
    assert_inputs_stable,
    parse_strict_json,
    read_inputs,
)

_PATH = {"type": "string", "minLength": 1, "maxLength": 500,
         "description": "Portable path relative to the selected workspace."}
_HASH = {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"}
_SOURCE = {"type": "string", "enum": ["workspace", "game_path"], "default": "workspace",
           "description": ("workspace = the selected workspace folder; game_path = the PS3 ISO or extracted game "
                           "folder chosen in Settings (re_game_path). For an ISO game_path, paths name files "
                           "inside the ISO, e.g. PS3_GAME/USRDIR/EBOOT.BIN.")}
_GAME_FILE = {"type": "string", "minLength": 1, "maxLength": 500,
              "description": "File relative to the chosen source (or inside the ISO), e.g. PS3_GAME/USRDIR/EBOOT.ELF."}
_ISO_MEMBER = {"type": "string", "minLength": 1, "maxLength": 500,
               "description": "When path is an .iso in the workspace: the file inside it to read."}
MAX_RESULT_CHARS = 24_000


def _definition(name: str, description: str, properties: dict, required: tuple[str, ...]) -> dict:
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": list(required), "additionalProperties": False,
    }}


RECOMPILATION_TOOLS = (
    _definition(
        "re_ps3_game_scan",
        "Scan the owner's PS3 game (ISO image or extracted game folder) in place: PARAM.SFO title/ID/versions and "
        "every executable (EBOOT.BIN, .self, .sprx, .elf, .prx) classified as PPU ELF, SPU ELF or encrypted SELF. "
        "Read-only; nothing is copied, extracted or downloaded.",
        {"source": _SOURCE, "path": {**_GAME_FILE, "description": (
            "Optional folder or .iso relative to the source; omit to scan the whole game_path/workspace.")}},
        (),
    ),
    _definition(
        "re_ps3_elf_preflight",
        "Inspect a PS3 PPU/SPU ELF (from the workspace, the owner's game folder, or inside their ISO): header, "
        "load ranges, endian/profile issues and entry metadata. Encrypted SELF/EBOOT.BIN is reported as an "
        "encrypted container (STAR has no keys and decrypts nothing). No execution, lifting or gameplay proof.",
        {"path": _GAME_FILE, "source": _SOURCE, "iso_member": _ISO_MEMBER, "expected_source_sha256": _HASH},
        ("path",),
    ),
    _definition(
        "re_verify_recompilation_evidence",
        "Check a nonempty semantic contract against distinct reference/candidate JSON records. Require exact "
        "completed case coverage, compare declared raw bits, memory digests and event order, and return the first "
        "counterexample. MATCH means supplied records agree only; it does not authenticate execution or prove a port.",
        {"contract_path": _PATH, "reference_path": _PATH, "candidate_path": _PATH,
         "expected_contract_sha256": _HASH, "expected_reference_sha256": _HASH},
        ("contract_path", "reference_path", "candidate_path"),
    ),
)
RECOMPILATION_NAMES = frozenset(tool["name"] for tool in RECOMPILATION_TOOLS)


def _bounded(result: dict) -> dict:
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False)) > MAX_RESULT_CHARS:
        raise ValueError("Analysis result exceeds the bounded output contract")
    return result


def _is_iso(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".iso"


def _game_target(args: dict, workspace: Path, game_path: Path | None, resolve: Callable) -> tuple:
    """('iso', image, member) or ('folder', root, relative-or-None) for the requested source."""
    if args.get("source", "workspace") == "game_path":
        if game_path is None:
            raise PermissionError("Choose your PS3 ISO or game folder in Settings (re_game_path) first")
        if _is_iso(game_path):
            return "iso", game_path, args.get("path")
        root = game_path
    else:
        root = workspace
    relative = args.get("path")
    if relative is None:
        return "folder", root, None
    target = resolve(relative, root=root, allow_dir=True, size_cap=False)
    if _is_iso(target):
        return "iso", target, args.get("iso_member")
    return "folder", root, relative


def dispatch_recompilation(
    name: str,
    args: dict,
    *,
    workspace: Path | None,
    resolve: Callable[..., Path],
    game_path: Path | None = None,
) -> dict:
    """Called only after the RE gateway validates schema and selected tool names."""
    if name not in RECOMPILATION_NAMES:
        raise PermissionError("Unknown recompilation tool")
    if workspace is None:
        raise PermissionError("Select a workspace before using recompilation tools")
    if name == "re_ps3_game_scan":
        from .re_ps3_disc import IsoImage, folder_files, scan

        kind, base, relative = _game_target(args, workspace, game_path, resolve)
        if kind == "iso":
            image = IsoImage(base)
            result = scan(image.files(), lambda member, n: image.read_member(member, n, head=n))
            result.update(source="iso", volume_id=image.volume_id, iso_size=image.size)
        else:
            folder = resolve(relative, root=base, allow_dir=True) if relative else base
            if not folder.is_dir():
                raise ValueError("Scan a folder or an .iso file")

            def head(member: str, n: int) -> bytes:
                with (folder / member).open("rb") as handle:
                    return handle.read(n)

            result = scan(folder_files(folder), head)
            result["source"] = "folder"
        return _bounded(result)
    if name == "re_ps3_elf_preflight":
        from .re_ps3_elf import inspect_ps3_elf

        kind, base, relative = _game_target(args, workspace, game_path, resolve)
        if kind == "iso":
            from .re_ps3_disc import IsoImage

            if not relative:
                raise ValueError("Name the file inside the ISO (path for game_path, iso_member for a workspace ISO)")
            data = IsoImage(base).read_member(relative, MAX_ELF_BYTES)
            digest = hashlib.sha256(data).hexdigest()
            pin = args.get("expected_source_sha256")
            if pin is not None and pin.lower() != digest:
                raise ValueError("Input SHA-256 does not match the supplied pin")
            result = inspect_ps3_elf(data, source_sha256=digest, label=relative)
            result.update(inputs=[{"path": relative, "iso": base.name, "size_bytes": len(data), "sha256": digest,
                                   "pin_checked": pin is not None}],
                          read_only=True, executed=False, runtime_verified=False)
            return _bounded(result)
        snapshots = read_inputs(base, lambda rel: resolve(rel, root=base), (
            InputSpec(relative, MAX_ELF_BYTES, args.get("expected_source_sha256")),
        ))
        source = snapshots[0]
        result = inspect_ps3_elf(source.data, source_sha256=source.sha256, label=source.label)
        stable_root = base
    else:
        from .re_semantic_evidence import compare_semantic_evidence

        snapshots = read_inputs(workspace, resolve, (
            InputSpec(args["contract_path"], MAX_JSON_BYTES, args.get("expected_contract_sha256")),
            InputSpec(args["reference_path"], MAX_JSON_BYTES, args.get("expected_reference_sha256")),
            InputSpec(args["candidate_path"], MAX_JSON_BYTES),
        ))
        documents = [parse_strict_json(item.data) for item in snapshots]
        result = compare_semantic_evidence(*documents)
        stable_root = workspace
    assert_inputs_stable(stable_root, snapshots)
    result.update({
        "inputs": [item.receipt() for item in snapshots],
        "input_stability": "no_change_observed",
        "read_only": True,
        "executed": False,
        "runtime_verified": False,
        "artifact_provenance": "not_authenticated",
    })
    return _bounded(result)
