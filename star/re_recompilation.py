"""Read-only recompilation tools attached to STAR's existing optional RE gateway."""
from __future__ import annotations

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
from .recompilation_guidance import TOPICS, recompilation_guidance

_PATH = {"type": "string", "minLength": 1, "maxLength": 500,
         "description": "Portable path relative to the selected workspace."}
_HASH = {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"}
MAX_RESULT_CHARS = 24_000


def _definition(name: str, description: str, properties: dict, required: tuple[str, ...]) -> dict:
    return {"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": properties, "required": list(required), "additionalProperties": False,
    }}


RECOMPILATION_TOOLS = (
    _definition(
        "re_ps3_elf_preflight",
        "Inspect an unencrypted workspace ELF for bounded PS3 PPU/SPU structural preflight: header, "
        "load ranges, endian/profile issues and entry metadata. No execution, decryption, lifting or gameplay proof.",
        {"path": _PATH, "expected_source_sha256": _HASH}, ("path",),
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
    _definition(
        "re_recompilation_guidance",
        "Retrieve original source-referenced ps3recomp/ELF/PPU/SPU verification and porting guidance with "
        "preconditions and acceptance checks. No file reads, training or automatic lesson promotion.",
        {"topic": {"type": "string", "enum": list(TOPICS), "default": "overview"}}, (),
    ),
)
RECOMPILATION_NAMES = frozenset(tool["name"] for tool in RECOMPILATION_TOOLS)


def _bounded(result: dict) -> dict:
    if len(json.dumps(result, ensure_ascii=True, allow_nan=False)) > MAX_RESULT_CHARS:
        raise ValueError("Analysis result exceeds the bounded output contract")
    return result


def dispatch_recompilation(
    name: str,
    args: dict,
    *,
    workspace: Path | None,
    resolve: Callable[[str], Path],
) -> dict:
    """Called only after the RE gateway validates schema and selected tool names."""
    if name not in RECOMPILATION_NAMES:
        raise PermissionError("Unknown recompilation tool")
    if workspace is None:
        raise PermissionError("Select a workspace before using recompilation tools")
    if name == "re_recompilation_guidance":
        return _bounded(recompilation_guidance(args.get("topic", "overview")))
    if name == "re_ps3_elf_preflight":
        from .re_ps3_elf import inspect_ps3_elf

        snapshots = read_inputs(workspace, resolve, (
            InputSpec(args["path"], MAX_ELF_BYTES, args.get("expected_source_sha256")),
        ))
        source = snapshots[0]
        result = inspect_ps3_elf(source.data, source_sha256=source.sha256, label=source.label)
    else:
        from .re_semantic_evidence import compare_semantic_evidence

        snapshots = read_inputs(workspace, resolve, (
            InputSpec(args["contract_path"], MAX_JSON_BYTES, args.get("expected_contract_sha256")),
            InputSpec(args["reference_path"], MAX_JSON_BYTES, args.get("expected_reference_sha256")),
            InputSpec(args["candidate_path"], MAX_JSON_BYTES),
        ))
        documents = [parse_strict_json(item.data) for item in snapshots]
        result = compare_semantic_evidence(*documents)
    assert_inputs_stable(workspace, snapshots)
    result.update({
        "inputs": [item.receipt() for item in snapshots],
        "input_stability": "no_change_observed",
        "read_only": True,
        "executed": False,
        "runtime_verified": False,
        "artifact_provenance": "not_authenticated",
    })
    return _bounded(result)
