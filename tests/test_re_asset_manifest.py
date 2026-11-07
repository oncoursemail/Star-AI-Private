"""Independent offline behavior checks for the asset-manifest integrity oracle.

Fixtures contain original synthetic bytes. These checks establish bounded local
verification behavior, not gameplay correctness, trusted origin, or a real port.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from star import re_asset_manifest
from star.re_asset_manifest import verify_asset_manifest


def entry(path="assets/model.bin", raw=b"original model"):
    return {"path": path, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write_manifest(root, assets=None, **changes):
    data = {"schema_version": "star-asset-manifest-v1", "package_id": "synthetic-game",
            "version": "1.0", "assets": [entry()] if assets is None else assets}
    data.update(changes)
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return manifest


def verify(root, manifest=None, **options):
    return verify_asset_manifest(manifest or root / "manifest.json", lambda relative: root / relative,
                                 manifest_label="manifest.json", **options)


def allow_only_manifest_reads(monkeypatch, manifest):
    original_open = Path.open
    original_os_open = os.open

    def checked_open(path, *args, **kwargs):
        assert Path(path) == manifest, "An asset was opened before validation completed"
        return original_open(path, *args, **kwargs)

    def checked_os_open(path, *args, **kwargs):
        assert Path(path) == manifest, "An asset was opened before validation completed"
        return original_os_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)
    monkeypatch.setattr(os, "open", checked_os_open)


@pytest.fixture
def sample(tmp_path):
    asset = tmp_path / "assets" / "model.bin"
    asset.parent.mkdir()
    asset.write_bytes(b"original model")
    write_manifest(tmp_path)
    return tmp_path


def test_correct_assets_and_manifest_pin_pass_without_authenticating_origin(sample):
    manifest = sample / "manifest.json"
    asset = sample / "assets" / "model.bin"
    before = (manifest.read_bytes(), asset.read_bytes())
    result = verify(sample, expected_manifest_sha256=hashlib.sha256(before[0]).hexdigest().upper())
    assert result["verdict"] == "PASS"
    assert result["asset_count"] == result["checked_files"] == 1
    assert result["bytes_hashed"] == len(before[1])
    assert result["read_only"] is True
    assert result["executed"] is False
    assert result["runtime_verified"] is False
    assert result["reference_provenance"] == "not_authenticated"
    assert [row["status"] for row in result["results"]] == ["matched"]
    assert before == (manifest.read_bytes(), asset.read_bytes())


def test_empty_asset_is_valid_and_optional_metadata_does_not_grant_trust(sample):
    asset = sample / "assets" / "model.bin"
    asset.write_bytes(b"")
    row = entry(raw=b"")
    row.update(source="https://example.org/assets/model", license="CC0-1.0")
    row["sha256"] = row["sha256"].upper()
    write_manifest(sample, [row])
    result = verify(sample)
    assert result["verdict"] == "PASS"
    assert result["bytes_hashed"] == 0
    assert result["runtime_verified"] is False
    assert result["reference_provenance"] == "not_authenticated"


def test_same_size_corruption_is_detected(sample):
    (sample / "assets" / "model.bin").write_bytes(b"corrupt! model")
    result = verify(sample)
    assert result["verdict"] == "FAIL"
    assert any(row["status"] == "hash_mismatch" for row in result["results"])


@pytest.mark.parametrize("replacement", [b"short", b"a longer replacement than the original"])
def test_wrong_size_is_a_failed_audit(sample, replacement):
    (sample / "assets" / "model.bin").write_bytes(replacement)
    result = verify(sample)
    assert result["verdict"] == "FAIL"
    assert any(row["status"] == "size_mismatch" for row in result["results"])


def test_missing_asset_is_not_a_pass(sample):
    (sample / "assets" / "model.bin").unlink()
    result = verify(sample)
    assert result["verdict"] == "FAIL"
    assert any(row["status"] == "unavailable" for row in result["results"])


def test_wrong_manifest_pin_fails_before_any_asset_read(sample, monkeypatch):
    allow_only_manifest_reads(monkeypatch, sample / "manifest.json")
    result = verify(sample, expected_manifest_sha256="0" * 64)
    assert result["verdict"] == "FAIL"
    assert result["reason"] == "manifest_pin_mismatch"
    assert result["checked_files"] == 0
    assert result["results"] == []


@pytest.mark.parametrize("pin", ["", "a" * 63, "z" * 64, True, 12])
def test_invalid_pin_is_rejected(sample, pin):
    with pytest.raises((TypeError, ValueError)):
        verify(sample, expected_manifest_sha256=pin)


@pytest.mark.parametrize("changes", [
    {"schema_version": "unknown"}, {"extra": True}, {"package_id": ""},
    {"package_id": "x" * 4096}, {"version": ""}, {"version": False},
    {"assets": []}, {"assets": {}},
])
def test_invalid_root_schema_is_rejected_before_resolving_assets(sample, changes):
    manifest = write_manifest(sample, **changes)

    def no_resolution(_relative):
        pytest.fail("Malformed manifest must be rejected before asset resolution")

    with pytest.raises(ValueError):
        verify_asset_manifest(manifest, no_resolution, manifest_label="manifest.json")


@pytest.mark.parametrize("changes", [
    {"size_bytes": True}, {"size_bytes": -1}, {"size_bytes": 1.5},
    {"size_bytes": 128 * 1024 * 1024 + 1}, {"sha256": "xyz"},
    {"sha256": "0" * 63}, {"source": "http://example.org/model"},
    {"source": "file:///tmp/model"}, {"source": "https://example.org/" + "a" * 1000},
    {"license": "a" * 121}, {"unknown": "field"},
])
def test_invalid_asset_schema_is_rejected(sample, changes):
    write_manifest(sample, [{**entry(), **changes}])
    with pytest.raises(ValueError):
        verify(sample)


@pytest.mark.parametrize("path", [
    "../outside.bin", "assets/../../outside.bin", "assets/../model.bin",
    "./assets/model.bin", "/absolute.bin", "C:/model.bin", "C:\\model.bin",
    "\\\\server\\share\\model.bin", "//server/share/model.bin", "assets\\model.bin",
    "assets/model.bin:stream", "assets//model.bin", "assets/CON.bin",
    "assets/NUL", "assets/model.bin.", "assets/model.bin ", "assets/bad\x00.bin",
])
def test_nonportable_or_escaping_paths_are_rejected_before_resolution(sample, path):
    manifest = write_manifest(sample, [{**entry(), "path": path}])

    def no_resolution(_relative):
        pytest.fail("Nonportable paths must be rejected before resolution")

    with pytest.raises((PermissionError, ValueError)):
        verify_asset_manifest(manifest, no_resolution, manifest_label="manifest.json")


def test_late_invalid_entry_prevents_reading_earlier_assets(sample, monkeypatch):
    manifest = write_manifest(sample, [entry(), entry("../outside.bin")])
    allow_only_manifest_reads(monkeypatch, manifest)
    with pytest.raises((PermissionError, ValueError)):
        verify(sample)


def test_casefold_duplicates_are_rejected(sample):
    write_manifest(sample, [entry(), entry("ASSETS/MODEL.BIN")])
    with pytest.raises(ValueError):
        verify(sample)


def test_distinct_names_cannot_double_count_the_same_resolved_file(sample):
    manifest = write_manifest(sample, [entry("first.bin"), entry("second.bin")])
    with pytest.raises(ValueError):
        verify_asset_manifest(manifest, lambda _name: sample / "assets" / "model.bin",
                              manifest_label="manifest.json")


def test_hardlinked_assets_cannot_be_counted_twice(sample):
    alias = sample / "assets" / "alias.bin"
    try:
        os.link(sample / "assets" / "model.bin", alias)
    except (OSError, NotImplementedError):
        pytest.skip("This filesystem does not support hard links")
    write_manifest(sample, [entry(), entry("assets/alias.bin")])
    with pytest.raises(ValueError):
        verify(sample)


@pytest.mark.parametrize("assets", [
    [entry(f"asset-{i}.bin") for i in range(129)],
    [{**entry(f"asset-{i}.bin"), "size_bytes": 128 * 1024 * 1024} for i in range(5)],
])
def test_file_count_and_declared_total_caps_precede_asset_resolution(sample, assets):
    manifest = write_manifest(sample, assets)

    def no_resolution(_relative):
        pytest.fail("An oversized manifest must be rejected before asset resolution")

    with pytest.raises(ValueError):
        verify_asset_manifest(manifest, no_resolution, manifest_label="manifest.json")


def test_manifest_byte_limit_is_enforced(sample):
    manifest = sample / "manifest.json"
    manifest.write_bytes(b" " * (128 * 1024 + 1))
    with pytest.raises(ValueError):
        verify(sample)


@pytest.mark.parametrize("raw", [
    b'{"schema_version":"star-asset-manifest-v1","package_id":"one","package_id":"two","version":"1","assets":[]}',
    b'{"schema_version":"star-asset-manifest-v1","package_id":"game","version":NaN,"assets":[]}',
    b"\xff\xfe invalid UTF-8",
])
def test_ambiguous_or_non_json_input_is_rejected(sample, raw):
    (sample / "manifest.json").write_bytes(raw)
    with pytest.raises(ValueError):
        verify(sample)


def test_actual_file_limit_is_checked_without_hashing_oversized_file(sample, monkeypatch):
    asset = sample / "assets" / "model.bin"
    with asset.open("wb") as handle:
        handle.truncate(128 * 1024 * 1024 + 1)
    allow_only_manifest_reads(monkeypatch, sample / "manifest.json")
    with pytest.raises(ValueError):
        verify(sample)


def test_actual_total_budget_is_enforced_before_hashing(sample, monkeypatch):
    # A small injected budget checks the aggregate ceiling without allocating
    # hundreds of megabytes merely to exercise a metadata preflight.
    rows = []
    for number in range(5):
        relative = f"assets/small-{number}.bin"
        (sample / relative).write_bytes(b"four")
        rows.append(entry(relative, b"xx"))
    manifest = write_manifest(sample, rows)
    monkeypatch.setattr(re_asset_manifest, "MAX_TOTAL_BYTES", 16)
    allow_only_manifest_reads(monkeypatch, manifest)
    with pytest.raises(ValueError):
        verify(sample)


def test_expired_time_budget_is_incomplete_without_reading_assets(sample, monkeypatch):
    observed_times = iter((0.0, 0.0, 16.0))
    monkeypatch.setattr(re_asset_manifest.time, "monotonic", lambda: next(observed_times, 16.0))
    allow_only_manifest_reads(monkeypatch, sample / "manifest.json")
    result = verify(sample)
    assert result["verdict"] == "INCOMPLETE"
    assert result["checked_files"] == 0
    assert result["bytes_hashed"] == 0
    assert any(row["status"] == "not_checked_time_budget" for row in result["results"])


def test_manifest_changed_while_assets_are_processed_cannot_pass(sample):
    manifest = sample / "manifest.json"
    changed = False

    def changing_resolver(relative):
        nonlocal changed
        if not changed:
            changed = True
            before = manifest.stat()
            manifest.write_text(json.dumps({**json.loads(manifest.read_text()), "version": "2"}),
                                encoding="utf-8")
            os.utime(manifest, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        return sample / relative

    result = verify_asset_manifest(manifest, changing_resolver, manifest_label="manifest.json")
    assert result["verdict"] == "FAIL"
    assert result["reason"] == "manifest_changed"


class _ReadObserver:
    def __init__(self, wrapped, callback):
        self.wrapped = wrapped
        self.callback = callback

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def __enter__(self):
        self.wrapped.__enter__()
        return self

    def __exit__(self, *args):
        return self.wrapped.__exit__(*args)

    def read(self, size=-1):
        data = self.wrapped.read(size)
        self.callback(size, data)
        return data


def observe_asset_reads(monkeypatch, asset, callback):
    original_open = Path.open
    original_fdopen = os.fdopen
    initial = asset.stat()

    def wrap(handle):
        info = os.fstat(handle.fileno())
        return (_ReadObserver(handle, callback)
                if (info.st_dev, info.st_ino) == (initial.st_dev, initial.st_ino) else handle)

    def tracked_open(path, *args, **kwargs):
        return wrap(original_open(path, *args, **kwargs))

    def tracked_fdopen(fd, *args, **kwargs):
        return wrap(original_fdopen(fd, *args, **kwargs))

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(os, "fdopen", tracked_fdopen)


def test_hashing_streams_at_most_64_kib_per_read(sample, monkeypatch):
    raw = bytes(range(256)) * 769
    asset = sample / "assets" / "model.bin"
    asset.write_bytes(raw)
    write_manifest(sample, [entry(raw=raw)])
    reads = []

    def observe(size, _data):
        assert 0 < size <= 64 * 1024
        reads.append(size)

    observe_asset_reads(monkeypatch, asset, observe)
    result = verify(sample)
    assert result["verdict"] == "PASS"
    assert result["bytes_hashed"] == len(raw)
    assert len(reads) >= 4


def test_file_mutation_during_read_never_receives_a_pass(sample, monkeypatch):
    raw = b"a" * (128 * 1024 + 17)
    asset = sample / "assets" / "model.bin"
    asset.write_bytes(raw)
    write_manifest(sample, [entry(raw=raw)])
    original_open = Path.open
    changed = False

    def mutate_once(_size, data):
        nonlocal changed
        if data and not changed:
            changed = True
            before = asset.stat()
            with original_open(asset, "r+b") as writer:
                writer.seek(len(raw) - 1)
                writer.write(b"b")
            os.utime(asset, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))

    observe_asset_reads(monkeypatch, asset, mutate_once)
    result = verify(sample)
    assert changed
    assert result["verdict"] == "FAIL"
    assert any(row["status"] == "changed" for row in result["results"])
