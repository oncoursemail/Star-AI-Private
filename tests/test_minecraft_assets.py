"""Security, versioning and reproducibility tests for STAR's Minecraft asset tools."""
import json
from pathlib import Path
import zipfile

import pytest

from star.minecraft_assets import audit, package
from star.workspace import Workspace


def _manifest(**pack):
    return json.dumps({"pack": {"description": "Metallic test pack", **pack}})


def _pack(tmp_path: Path, *, target="26.3") -> tuple[Workspace, Path]:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "pack"
    source.mkdir()
    if target == "26.3":
        meta = _manifest(min_format=[97, 1], max_format=[97, 1])
    else:
        meta = _manifest(pack_format=46)
    (source / "pack.mcmeta").write_text(meta, encoding="utf8")
    return Workspace(root), source


def test_modern_format_and_read_only_audit(tmp_path):
    ws, _ = _pack(tmp_path)
    r = audit(ws, "pack", target_version="26.3")
    assert r["valid"]
    assert r["kind"] == "resource-pack"
    assert r["tested_in_game"] is False
    assert not [f for f in r["findings"] if f["severity"] == "error"]


def test_version_mismatch_and_missing_manifest(tmp_path):
    ws, packdir = _pack(tmp_path)
    r = audit(ws, "pack", target_version="26.2")
    assert not r["valid"]
    assert any(f["code"] == "target-incompatible" for f in r["findings"])
    (packdir / "pack.mcmeta").unlink()
    assert any(f["code"] == "missing-manifest" for f in audit(ws, "pack")["findings"])


def test_legacy_format(tmp_path):
    ws, _ = _pack(tmp_path, target="1.21.4")
    assert audit(ws, "pack", target_version="1.21.4")["valid"]
    assert not audit(ws, "pack", target_version="26.3")["valid"]


def test_model_reference_report_and_texture_signature(tmp_path):
    ws, folder = _pack(tmp_path)
    item = folder / "assets" / "metallic" / "items" / "sword.json"
    item.parent.mkdir(parents=True)
    item.write_text(json.dumps({"model": {"type": "minecraft:model",
                                          "model": "metallic:item/sword"}}))
    t = folder / "assets" / "metallic" / "textures" / "item" / "sword.png"
    t.parent.mkdir(parents=True)
    t.write_bytes(b"not a png")
    report = audit(ws, "pack")
    codes = {f["code"] for f in report["findings"]}
    assert "missing-model-reference" in codes
    assert "invalid-png" in codes
    assert not report["valid"]
    t.unlink()
    model = folder / "assets" / "metallic" / "models" / "item" / "sword.json"
    model.parent.mkdir(parents=True)
    model.write_text('{"parent":"minecraft:item/generated"}')
    assert not any(f["code"] == "missing-model-reference" for f in audit(ws, "pack")["findings"])


def test_blockbench_counts_and_bad_geometry(tmp_path):
    ws, _ = _pack(tmp_path)
    f = ws.root / "wings.bbmodel"
    f.write_text(json.dumps({"meta": {"model_format": "free"},
                             "elements": [{"uuid": "duplicate", "from": [0, 0, 0], "to": [16, 16, 16]},
                                          {"uuid": "duplicate", "from": [999999, 0, 0]}],
                             "textures": [], "animations": [{"name": "flap"}]}))
    r = audit(ws, "wings.bbmodel")
    assert r["kind"] == "blockbench" and not r["valid"]
    assert r["stats"]["animations"] == 1
    assert {f["code"] for f in r["findings"]} >= {"duplicate-uuid", "bad-geometry"}


def test_zip_traversal_and_duplicate_case(tmp_path):
    ws, _ = _pack(tmp_path)
    path = ws.root / "malicious.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("pack.mcmeta", _manifest(min_format=[97, 1], max_format=[97, 1]))
        z.writestr("../outside.json", "x")
        z.writestr("assets/metallic/MODELS/a.json", "{}")
        z.writestr("assets/metallic/models/a.json", "{}")
    r = audit(ws, "malicious.zip")
    assert not r["valid"]
    assert {f["code"] for f in r["findings"]} >= {"unsafe-path", "case-collision"}


def test_symlink_is_rejected(tmp_path):
    ws, folder = _pack(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("do not read")
    (folder / "linked.txt").symlink_to(outside)
    r = audit(ws, "pack")
    assert not r["valid"]
    assert any(f["code"] == "symlink" for f in r["findings"])


def test_deterministic_packaging_and_no_clobber(tmp_path):
    ws, folder = _pack(tmp_path)
    (folder / "pack.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"\x00\x00\x00\x10" * 2)
    first = package(ws, "pack", "one.zip")
    second = package(ws, "pack", "two.zip")
    assert first["sha256"] == second["sha256"]
    assert first["deployed"] is False
    assert audit(ws, "one.zip")["valid"]
    with pytest.raises(FileExistsError):
        package(ws, "pack", "one.zip")
    assert package(ws, "pack", "one.zip", replace=True)["sha256"] == first["sha256"]


def test_workspace_tool_is_permissioned(tmp_path):
    ws, _ = _pack(tmp_path)
    result = ws.call("workspace_minecraft_audit", {"path": "pack"})
    assert result["valid"]
    with pytest.raises(PermissionError):
        ws.call("workspace_minecraft_package",
                {"path": "pack", "output": "pack.zip", "target_version": "26.3"})
    result = ws.call("workspace_minecraft_package",
                     {"path": "pack", "output": "pack.zip", "target_version": "26.3"},
                     allow_write=True)
    assert result["files"] == 1 and (ws.root / "pack.zip").exists()


def test_workspace_escape_and_nested_output_rejected(tmp_path):
    ws, _ = _pack(tmp_path)
    (tmp_path / "secret").write_text("out-of-workspace file")
    with pytest.raises(PermissionError):
        audit(ws, "../secret")
    with pytest.raises(ValueError):
        package(ws, "pack", "pack/in-the-input.zip")


def test_invalid_blockbench_json(tmp_path):
    ws, _ = _pack(tmp_path)
    (ws.root / "broken.bbmodel").write_text("{oops")
    result = audit(ws, "broken.bbmodel")
    assert not result["valid"]
    assert any(f["code"] == "invalid-json" for f in result["findings"])


def _real_png():
    """Small, full-CRC 2x2 RGBA PNG, generated locally without third-party fixtures."""
    import struct
    import zlib

    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))
    header = struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)
    rows = (b"\x00" + b"\xff\x55\x00\xff" * 2) * 2
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
            chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def test_scaffold_creates_real_item_pack_with_owner_art(tmp_path):
    from star.minecraft_assets import scaffold_item
    ws, _ = _pack(tmp_path)
    texture = ws.root / "my-art.png"
    texture.write_bytes(_real_png())
    original = texture.read_bytes()
    result = scaffold_item(ws, "metallic-pack", namespace="metallic", item_id="azure_sword",
                           texture_path="my-art.png", target_version="26.3",
                           description="Metallic originals")
    assert result["valid"] and result["file_count"] == 4
    assert result["texture_dimensions"] == [2, 2]
    assert texture.read_bytes() == original
    assert audit(ws, "metallic-pack", target_version="26.3")["valid"]
    with (ws.root / "metallic-pack" / "assets" / "metallic" / "items" / "azure_sword.json").open() as file:
        assert json.load(file)["model"]["model"] == "metallic:item/azure_sword"
    zipped = package(ws, "metallic-pack", "metallic-items.zip")
    assert zipped["files"] == 4
    assert audit(ws, "metallic-items.zip")["valid"]


def test_scaffold_legacy_version_and_permissions(tmp_path):
    ws, _ = _pack(tmp_path)
    (ws.root / "art.png").write_bytes(_real_png())
    args = {"output_dir": "legacy-items", "namespace": "metallic", "item_id": "ancient_gem",
            "texture_path": "art.png", "target_version": "1.21.4"}
    with pytest.raises(PermissionError):
        ws.call("workspace_minecraft_item_scaffold", args)
    result = ws.call("workspace_minecraft_item_scaffold", args, allow_write=True)
    assert result["valid"]
    r = audit(ws, "legacy-items", target_version="1.21.4")
    assert r["valid"]
    metadata = json.loads((ws.root / "legacy-items" / "pack.mcmeta").read_text())["pack"]
    assert metadata["pack_format"] == 46
    with pytest.raises(FileExistsError):
        ws.call("workspace_minecraft_item_scaffold", args, allow_write=True)


def test_scaffold_rejects_invalid_texture_and_namespace(tmp_path):
    from star.minecraft_assets import scaffold_item
    ws, _ = _pack(tmp_path)
    bad = ws.root / "fake.png"
    bad.write_bytes(b"not valid png")
    with pytest.raises(ValueError):
        scaffold_item(ws, "never-made", namespace="metallic", item_id="item",
                      texture_path="fake.png", target_version="26.3")
    assert not (ws.root / "never-made").exists()
    good = ws.root / "good.png"
    good.write_bytes(_real_png())
    with pytest.raises(ValueError):
        scaffold_item(ws, "never-made", namespace="Metallic", item_id="item",
                      texture_path="good.png", target_version="26.3")
