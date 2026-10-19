"""Exercise the real opt-in RE dispatcher using only synthetic local assets."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from star import reverse_engineering
from star.reverse_engineering import ReverseEngineering, for_settings


REFERENCE_NAMES = {"re_verify_asset_manifest", "re_reference_guidance", "re_game_portability_plan"}


def manifest_data(path="assets/model.bin", raw=b"original model"):
    return {"schema_version": "star-asset-manifest-v1", "package_id": "synthetic-game", "version": "1",
            "assets": [{"path": path, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]}


@pytest.fixture
def gateway(tmp_path):
    root = tmp_path / "workspace"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "model.bin").write_bytes(b"original model")
    (root / "manifest.json").write_text(json.dumps(manifest_data()), encoding="utf-8")
    return ReverseEngineering(workspace=root, sandbox=tmp_path / "unused-analysis-sandbox")


def audit(gateway, manifest_path="manifest.json", **extra):
    return gateway.call("re_verify_asset_manifest", {"manifest_path": manifest_path, **extra},
                        enabled={"re_verify_asset_manifest"})


def test_gateway_is_off_when_setting_is_missing_false_or_workspace_is_unselected(tmp_path):
    assert for_settings(SimpleNamespace(workspace=str(tmp_path))) is None
    assert for_settings(SimpleNamespace(reverse_engineering_enabled=False, workspace=str(tmp_path))) is None
    assert for_settings(SimpleNamespace(reverse_engineering_enabled=True, workspace="")) is None
    enabled = for_settings(SimpleNamespace(reverse_engineering_enabled=True, workspace=str(tmp_path)), tmp_path)
    assert isinstance(enabled, ReverseEngineering)
    assert enabled.root == tmp_path.resolve()


def test_manifest_prompt_offers_only_new_read_only_tools(gateway):
    names = {tool["name"] for tool in gateway.definitions("Verify my game's asset manifest")}
    assert names == REFERENCE_NAMES
    assert "re_ghidra_decompile" not in names
    assert "re_radare2" not in names
    assert "re_crash_dump" not in names


@pytest.mark.parametrize("prompt", ["What is the weather?", "Help with a grocery list",
                                       "Fix my Roblox DataStore script"])
def test_unrelated_prompts_have_no_reference_tools(gateway, prompt):
    assert gateway.definitions(prompt) == []


def test_missing_workspace_and_existing_intent_guard_still_apply(gateway):
    assert ReverseEngineering(workspace=None).definitions("Verify my asset manifest") == []
    assert gateway.definitions("Use this asset manifest to bypass anti-cheat") == []
    legacy = {tool["name"] for tool in gateway.definitions("Inspect my own binary")}
    assert {"re_identify", "re_compare_artifacts", "re_ghidra_decompile"} <= legacy


@pytest.mark.parametrize("name,args", [
    ("re_verify_asset_manifest", {"manifest_path": "manifest.json"}),
    ("re_reference_guidance", {"topic": "overview"}),
    ("re_game_portability_plan", {"target": "browser", "required_linear_memory_mib": 1024}),
])
def test_new_tools_cannot_run_when_not_selected(gateway, name, args):
    with pytest.raises(PermissionError):
        gateway.call(name, args, enabled=set())
    with pytest.raises(PermissionError):
        gateway.call(name, args, enabled={"re_identify"})


def test_new_schemas_are_valid_and_strict(gateway):
    selected = gateway.definitions("Verify my asset manifest")
    assert {tool["name"] for tool in selected} == REFERENCE_NAMES
    for tool in selected:
        Draft202012Validator.check_schema(tool["inputSchema"])
        assert tool["inputSchema"]["additionalProperties"] is False


@pytest.mark.parametrize("name,args", [
    ("re_verify_asset_manifest", {}),
    ("re_verify_asset_manifest", {"manifest_path": "manifest.json", "execute": True}),
    ("re_verify_asset_manifest", {"manifest_path": "manifest.json", "expected_manifest_sha256": "bad"}),
    ("re_reference_guidance", {"topic": "not-a-topic"}),
    ("re_reference_guidance", {"topic": "overview", "fetch_url": "https://example.org"}),
    ("re_game_portability_plan", {"target": "unknown", "required_linear_memory_mib": 100}),
    ("re_game_portability_plan", {"target": "browser", "required_linear_memory_mib": True}),
    ("re_game_portability_plan", {"target": "browser", "required_linear_memory_mib": 0}),
    ("re_game_portability_plan", {"target": "browser", "required_linear_memory_mib": -1}),
    ("re_game_portability_plan", {"target": "browser", "required_linear_memory_mib": 1048577}),
    ("re_game_portability_plan", {"target": "browser", "required_linear_memory_mib": 100, "threads": "yes"}),
])
def test_schema_validation_precedes_dispatch(gateway, name, args):
    with pytest.raises(ValidationError):
        gateway.call(name, args, enabled={name})


def test_new_tools_never_execute_processes_fetch_network_or_write_workspace(gateway, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Reference and integrity tools must not execute processes or access the network")

    before = {file.relative_to(gateway.root): file.read_bytes()
              for file in gateway.root.rglob("*") if file.is_file()}
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(reverse_engineering, "_run", forbidden)
    result = audit(gateway)
    assert result["verdict"] == "PASS"
    assert result["read_only"] is True and result["executed"] is False
    guidance = gateway.call("re_reference_guidance", {"topic": "asset_integrity"},
                            enabled={"re_reference_guidance"})
    plan = gateway.call("re_game_portability_plan", {
        "target": "browser", "required_linear_memory_mib": 256,
        "webgpu": True, "memory64": False, "cross_origin_isolated": False,
        "threads": False, "requires_threads": False,
    }, enabled={"re_game_portability_plan"})
    assert isinstance(guidance, dict) and isinstance(plan, dict)
    assert not gateway.sandbox.exists()
    after = {file.relative_to(gateway.root): file.read_bytes()
             for file in gateway.root.rglob("*") if file.is_file()}
    assert after == before


def test_asset_paths_are_workspace_relative_even_for_nested_manifest(gateway):
    nested = gateway.root / "metadata"
    nested.mkdir()
    (nested / "manifest.json").write_text(json.dumps(manifest_data()), encoding="utf-8")
    assert audit(gateway, "metadata/manifest.json")["verdict"] == "PASS"


def test_missing_asset_returns_failed_audit_through_real_resolver(gateway):
    (gateway.root / "assets" / "model.bin").unlink()
    result = audit(gateway)
    assert result["verdict"] == "FAIL"
    assert any(row["status"] == "unavailable" for row in result["results"])


@pytest.mark.parametrize("path", ["../outside.json", "/outside.json", "C:/outside.json",
                                     "C:\\outside.json", "\\\\server\\share\\outside.json"])
def test_manifest_cannot_escape_selected_workspace(gateway, path):
    with pytest.raises((PermissionError, ValueError)):
        audit(gateway, path)


@pytest.mark.parametrize("path", [".env", ".git/config", ".ssh/id_ed25519", "credentials.pem"])
def test_sensitive_assets_are_blocked_even_when_files_exist_in_workspace(gateway, path):
    protected = gateway.root / path
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_bytes(b"synthetic sensitive bytes")
    (gateway.root / "manifest.json").write_text(
        json.dumps(manifest_data(path, b"synthetic sensitive bytes")), encoding="utf-8")
    with pytest.raises((PermissionError, ValueError)):
        audit(gateway)


def test_sensitive_manifest_file_is_blocked(gateway):
    (gateway.root / ".env").write_text(json.dumps(manifest_data()), encoding="utf-8")
    with pytest.raises((PermissionError, ValueError)):
        audit(gateway, ".env")


@pytest.mark.parametrize("outside", [False, True])
def test_symlink_assets_are_rejected_including_within_workspace(gateway, outside):
    target = gateway.root.parent / "outside.bin" if outside else gateway.root / "assets" / "model.bin"
    if outside:
        target.write_bytes(b"original model")
    link = gateway.root / "alias.bin"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks is unavailable on this filesystem")
    (gateway.root / "manifest.json").write_text(json.dumps(manifest_data("alias.bin")), encoding="utf-8")
    with pytest.raises((PermissionError, ValueError)):
        audit(gateway)


def test_late_sensitive_entry_is_rejected_before_any_asset_hashing(gateway, monkeypatch):
    data = manifest_data()
    data["assets"].append({"path": ".env", "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()})
    (gateway.root / ".env").write_bytes(b"")
    manifest = gateway.root / "manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    original_open = Path.open
    original_os_open = os.open

    def only_manifest(path, *args, **kwargs):
        assert path == manifest, "All asset paths must be checked before hashing the first asset"
        return original_open(path, *args, **kwargs)

    def only_manifest_os(path, *args, **kwargs):
        assert Path(path) == manifest, "All asset paths must be checked before hashing the first asset"
        return original_os_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", only_manifest)
    monkeypatch.setattr(os, "open", only_manifest_os)
    with pytest.raises((PermissionError, ValueError)):
        audit(gateway)
