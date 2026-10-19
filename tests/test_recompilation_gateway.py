"""Independent real-dispatch checks for the optional recompilation tools.

The ELF bytes and observation records below are original synthetic fixtures;
no game, firmware, recompilation executable, network, or live service is used.
"""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
from types import SimpleNamespace
import urllib.request

from jsonschema.exceptions import ValidationError
import pytest

from star import re_analysis_input, re_recompilation, re_semantic_evidence
from star.re_recompilation import RECOMPILATION_NAMES
from star.recompilation_guidance import PS3RECOMP_COMMIT, TOPICS
from star.reverse_engineering import ReverseEngineering, for_settings


ELF_TOOL = "re_ps3_elf_preflight"
EVIDENCE_TOOL = "re_verify_recompilation_evidence"
GUIDANCE_TOOL = "re_recompilation_guidance"


def _spu_elf(loads=1):
    # ELF32, big endian, EM_SPU, one synthetic instruction-sized load region.
    # Repeated segments deliberately exercise bounded overlap diagnostics.
    ident = b"\x7fELF\x01\x02\x01" + b"\0" * 9
    header = struct.pack(
        ">HHIIIIIHHHHHH", 2, 23, 1, 0x2000, 52, 0, 0, 52, 32, loads, 40, 0, 0,
    )
    program = struct.pack(
        ">IIIIIIII", 1, 52 + loads * 32, 0x2000, 0, 4, 4, 5, 4,
    )
    return ident + header + program * loads + b"\0" * 4


def _documents():
    contract = {
        "schema_version": "star-semantic-contract-v1",
        "suite_id": "synthetic.spu.order.v1", "suite_sha256": "1" * 64,
        "reference_artifact_sha256": "2" * 64, "candidate_artifact_sha256": "3" * 64,
        "cases": [{
            "case_id": "spu.mailbox.order", "input_sha256": "4" * 64,
            "observables": [
                {"name": "r0", "kind": "bits", "width_bits": 128},
                {"name": "store", "kind": "memory_sha256", "size_bytes": 16},
                {"name": "dma", "kind": "events", "max_events": 4},
            ],
        }],
    }
    reference = {
        "schema_version": "star-semantic-evidence-v1",
        "suite_id": contract["suite_id"], "suite_sha256": contract["suite_sha256"],
        "artifact_sha256": "2" * 64, "producer_id": "reference.fixture", "run_id": "reference.run",
        "complete": True, "exit_code": 0, "unsupported_operations": 0, "unverified_stubs": 0,
        "cases": [{
            "case_id": "spu.mailbox.order", "input_sha256": "4" * 64, "status": "complete",
            "observations": [
                {"name": "r0", "kind": "bits", "width_bits": 128, "hex": "0" * 31 + "1"},
                {"name": "store", "kind": "memory_sha256", "size_bytes": 16, "sha256": "5" * 64},
                {"name": "dma", "kind": "events", "events": [
                    {"tag": "dma.put", "data_hex": "00000010"},
                    {"tag": "dma.wait", "data_hex": "01"},
                ]},
            ],
        }],
    }
    candidate = deepcopy(reference)
    candidate.update(artifact_sha256="3" * 64, producer_id="candidate.fixture", run_id="candidate.run")
    return contract, reference, candidate


def _write_documents(root, documents):
    labels = ("contract.json", "reference.json", "candidate.json")
    digests = []
    for label, document in zip(labels, documents):
        raw = json.dumps(document, sort_keys=True).encode()
        (root / label).write_bytes(raw)
        digests.append(hashlib.sha256(raw).hexdigest())
    return {
        "contract_path": labels[0], "reference_path": labels[1], "candidate_path": labels[2],
        "expected_contract_sha256": digests[0], "expected_reference_sha256": digests[1],
    }


@pytest.fixture
def gateway(tmp_path):
    return ReverseEngineering(workspace=tmp_path, sandbox=tmp_path / "external-tool-sandbox")


def _call(gateway, name, args):
    return gateway.call(name, args, enabled=set(RECOMPILATION_NAMES))


def _workspace_snapshot(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def _forbid_side_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Read-only recompilation dispatch attempted an external or write operation")

    original_open = builtins.open
    original_os_open = os.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(letter in mode for letter in "wax+"):
            forbidden()
        return original_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            forbidden()
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)


def test_settings_keep_recompilation_default_off(tmp_path):
    assert for_settings(SimpleNamespace(workspace=str(tmp_path))) is None
    assert for_settings(SimpleNamespace(workspace=str(tmp_path), reverse_engineering_enabled=False)) is None
    assert for_settings(SimpleNamespace(workspace="", reverse_engineering_enabled=True)) is None
    enabled = for_settings(SimpleNamespace(workspace=str(tmp_path), reverse_engineering_enabled=True), tmp_path)
    assert isinstance(enabled, ReverseEngineering)
    assert not (tmp_path / "re_sandbox").exists()


def test_selection_retains_prompt_and_intent_boundaries(gateway):
    assert {item["name"] for item in gateway.definitions("ps3recomp planning")} == RECOMPILATION_NAMES
    binary_names = {item["name"] for item in gateway.definitions("Inspect this binary file")}
    assert RECOMPILATION_NAMES < binary_names
    assert "re_identify" in binary_names
    assert gateway.definitions("Write a thank-you note") == []
    assert gateway.definitions("ps3recomp remove DRM") == []
    assert gateway.definitions("PS3 binary anti-cheat bypass") == []
    assert ReverseEngineering(workspace=None).definitions("ps3recomp planning") == []


@pytest.mark.parametrize("name", [ELF_TOOL, EVIDENCE_TOOL, GUIDANCE_TOOL])
def test_tool_allowlist_is_checked_before_any_dispatch(gateway, name):
    assert gateway.owns(name)
    with pytest.raises(PermissionError, match="not enabled"):
        gateway.call(name, {}, enabled=set())
    with pytest.raises(PermissionError, match="not enabled"):
        gateway.call("re_unregistered_probe", {}, enabled=set(RECOMPILATION_NAMES))


@pytest.mark.parametrize("name,args", [
    (ELF_TOOL, {"path": "sample.elf", "execute": True}),
    (ELF_TOOL, {"path": "sample.elf", "expected_source_sha256": "bad"}),
    (EVIDENCE_TOOL, {"contract_path": "contract.json", "reference_path": "reference.json"}),
    (EVIDENCE_TOOL, {"contract_path": "a", "reference_path": "b", "candidate_path": "c", "command": "run"}),
    (GUIDANCE_TOOL, {"topic": "unknown"}),
    (GUIDANCE_TOOL, {"topic": "overview", "learn_automatically": True}),
])
def test_schema_rejects_unknown_actions_and_incomplete_arguments(gateway, name, args):
    with pytest.raises(ValidationError):
        _call(gateway, name, args)


def test_all_three_real_tools_are_read_only_and_do_not_create_sandbox(gateway, tmp_path, monkeypatch):
    data = _spu_elf()
    (tmp_path / "sample.elf").write_bytes(data)
    args = _write_documents(tmp_path, _documents())
    before = _workspace_snapshot(tmp_path)
    _forbid_side_effects(monkeypatch)

    elf = _call(gateway, ELF_TOOL, {"path": "sample.elf", "expected_source_sha256": hashlib.sha256(data).hexdigest()})
    evidence = _call(gateway, EVIDENCE_TOOL, args)
    guidance = _call(gateway, GUIDANCE_TOOL, {"topic": "verification"})

    assert elf["status"] == "ready_for_review"
    assert elf["evidence_scope"] == "structural_preflight"
    assert elf["header"]["profile"] == "spu_local_store"
    assert elf["inputs"][0]["pin_checked"] is True
    assert evidence["verdict"] == "MATCH"
    assert evidence["comparison_complete"] is True
    assert evidence["counts"]["compared_cases"] == 1
    assert evidence["counts"]["compared_observables"] == 3
    assert evidence["scope"] == "supplied_records_only"
    assert evidence["reference_authenticity"] == "unverified"
    assert evidence["independence_verified"] is False
    assert [item["pin_checked"] for item in evidence["inputs"]] == [True, True, False]
    assert guidance["status"] == "candidate"
    for result in (elf, evidence, guidance):
        assert result["read_only"] is True
        assert result["executed"] is False
        assert result["runtime_verified"] is False
        assert len(json.dumps(result, ensure_ascii=True)) <= re_recompilation.MAX_RESULT_CHARS
    assert _workspace_snapshot(tmp_path) == before
    assert not gateway.sandbox.exists()


@pytest.mark.parametrize("kind", ["bits", "memory_sha256", "events"])
def test_actual_dispatch_returns_first_semantic_counterexample(gateway, tmp_path, kind):
    documents = _documents()
    observations = documents[2]["cases"][0]["observations"]
    if kind == "bits":
        observations[0]["hex"] = "0" * 31 + "2"
    elif kind == "memory_sha256":
        observations[1]["sha256"] = "6" * 64
    else:
        observations[2]["events"].reverse()
    result = _call(gateway, EVIDENCE_TOOL, _write_documents(tmp_path, documents))
    assert result["verdict"] == "MISMATCH"
    assert result["comparison_complete"] is True
    assert result["counts"]["mismatched_observables"] == 1
    assert result["first_counterexample"]["kind"] == kind
    assert result["first_counterexample"]["case_id"] == "spu.mailbox.order"
    if kind == "events":
        assert result["first_counterexample"]["event_index"] == 0


@pytest.mark.parametrize("failure,verdict", [
    ("empty_cases", "INCOMPLETE"), ("missing_observations", "INCOMPLETE"),
    ("unfinished", "INCOMPLETE"), ("skipped", "INCOMPLETE"),
    ("unsupported", "INCOMPLETE"), ("unverified_stubs", "INCOMPLETE"),
    ("nonzero_exit", "INCOMPLETE"), ("unknown_exit", "INCOMPLETE"),
    ("duplicate", "INCOMPARABLE"), ("unexpected", "INCOMPARABLE"),
    ("wrong_artifact", "INCOMPARABLE"), ("same_producer", "INCOMPARABLE"),
])
def test_incomplete_or_incomparable_records_cannot_match(gateway, tmp_path, failure, verdict):
    documents = _documents()
    reference, candidate = documents[1:]
    if failure == "empty_cases":
        candidate["cases"] = []
    elif failure == "missing_observations":
        candidate["cases"][0]["observations"] = []
    elif failure == "unfinished":
        candidate["complete"] = False
    elif failure == "skipped":
        candidate["cases"][0]["status"] = "skipped"
    elif failure == "unsupported":
        candidate["unsupported_operations"] = 1
    elif failure == "unverified_stubs":
        candidate["unverified_stubs"] = 1
    elif failure == "nonzero_exit":
        candidate["exit_code"] = 0xC0000005
    elif failure == "unknown_exit":
        candidate["exit_code"] = None
    elif failure == "duplicate":
        candidate["cases"].append(deepcopy(candidate["cases"][0]))
    elif failure == "unexpected":
        extra = deepcopy(candidate["cases"][0])
        extra["case_id"] = "undeclared.case"
        candidate["cases"].append(extra)
    elif failure == "wrong_artifact":
        candidate["artifact_sha256"] = "7" * 64
    else:
        candidate["producer_id"] = reference["producer_id"]
    result = _call(gateway, EVIDENCE_TOOL, _write_documents(tmp_path, documents))
    assert result["verdict"] == verdict
    assert result["comparison_complete"] is False
    assert result["counts"]["compared_cases"] == 0
    assert result["counts"]["issues"] > 0


@pytest.mark.parametrize("raw", [b"", b"{}", b'{"complete":true,"complete":false}', b"[]"])
def test_empty_or_ambiguous_json_never_becomes_a_match(gateway, tmp_path, raw):
    args = _write_documents(tmp_path, _documents())
    (tmp_path / "candidate.json").write_bytes(raw)
    with pytest.raises(ValueError):
        _call(gateway, EVIDENCE_TOOL, args)


@pytest.mark.parametrize("field", ["expected_contract_sha256", "expected_reference_sha256"])
def test_file_pins_are_checked_before_semantic_verdict(gateway, tmp_path, field):
    args = _write_documents(tmp_path, _documents())
    args[field] = "f" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        _call(gateway, EVIDENCE_TOOL, args)


def test_elf_file_pin_is_checked_before_preflight(gateway, tmp_path):
    (tmp_path / "sample.elf").write_bytes(_spu_elf())
    with pytest.raises(ValueError, match="SHA-256"):
        _call(gateway, ELF_TOOL, {"path": "sample.elf", "expected_source_sha256": "f" * 64})


@pytest.mark.parametrize("bad_path", ["reference.json", ".ssh/private.json", "../escape.json"])
def test_aliases_and_protected_paths_are_rejected_before_content_reads(gateway, tmp_path, monkeypatch, bad_path):
    args = _write_documents(tmp_path, _documents())
    args["candidate_path"] = bad_path

    def unexpected(*_args, **_kwargs):
        pytest.fail("An earlier file was opened before the complete path set was validated")

    monkeypatch.setattr(re_analysis_input.os, "open", unexpected)
    with pytest.raises((ValueError, PermissionError)):
        _call(gateway, EVIDENCE_TOOL, args)


def test_comparison_time_mutation_cannot_escape_final_stability_check(gateway, tmp_path, monkeypatch):
    args = _write_documents(tmp_path, _documents())
    original = re_semantic_evidence.compare_semantic_evidence
    seen = []

    def change_after_compare(*documents):
        result = original(*documents)
        seen.append(result["verdict"])
        with (tmp_path / "contract.json").open("ab") as handle:
            handle.write(b" ")
        return result

    monkeypatch.setattr(re_semantic_evidence, "compare_semantic_evidence", change_after_compare)
    with pytest.raises(ValueError, match="changed"):
        _call(gateway, EVIDENCE_TOOL, args)
    assert seen == ["MATCH"]


def test_large_structural_detail_set_stays_within_gateway_output_cap(gateway, tmp_path):
    (tmp_path / "many-loads.elf").write_bytes(_spu_elf(loads=128))
    result = _call(gateway, ELF_TOOL, {"path": "many-loads.elf"})
    assert result["segment_summary"]["load_regions"] == 128
    assert result["segment_summary"]["details_omitted"] > 0
    assert result["issues_omitted"] > 0
    assert len(json.dumps(result, ensure_ascii=True)) <= re_recompilation.MAX_RESULT_CHARS
    assert result["runtime_verified"] is False


@pytest.mark.parametrize("topic", TOPICS)
def test_guidance_is_candidate_context_with_coherent_pinned_sources(gateway, monkeypatch, topic):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Guidance attempted to resolve or read a local input")

    monkeypatch.setattr(gateway, "_resolve", unexpected)
    monkeypatch.setattr(re_recompilation, "read_inputs", unexpected)
    result = _call(gateway, GUIDANCE_TOOL, {"topic": topic})
    assert result["status"] == "candidate"
    assert result["evidence_scope"] == "reference_guidance"
    assert result["runtime_verified"] is False
    assert result["reference"]["commit"] == PS3RECOMP_COMMIT
    assert "No model training or automatic lesson acceptance" in result["learning_effect"]
    assert result["principles"]
    source_ids = {source["id"] for source in result["sources"]}
    for principle in result["principles"]:
        assert principle["preconditions"] and principle["acceptance_checks"]
        assert set(principle["sources"]) <= source_ids
    for source in result["sources"]:
        assert source["url"].startswith("https://")
        if "github.com/sp00nznet/ps3recomp/blob/" in source["url"]:
            assert f"/blob/{PS3RECOMP_COMMIT}/" in source["url"]
    assert len(json.dumps(result, ensure_ascii=True)) <= re_recompilation.MAX_RESULT_CHARS


def test_mutating_guidance_response_does_not_promote_or_change_later_guidance(gateway):
    first = _call(gateway, GUIDANCE_TOOL, {})
    first["principles"][0]["acceptance_checks"][0] = "accept without evidence"
    second = _call(gateway, GUIDANCE_TOOL, {})
    assert second["status"] == "candidate"
    assert second["principles"][0]["acceptance_checks"][0] != "accept without evidence"


def test_guidance_still_requires_the_owner_selected_workspace():
    gateway = ReverseEngineering(workspace=None)
    with pytest.raises(PermissionError, match="workspace"):
        _call(gateway, GUIDANCE_TOOL, {})
