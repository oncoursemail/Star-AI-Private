"""Independent review regressions for portable paths and a whole-audit mutation.

These are synthetic local fixtures. They exercise integrity reporting, not
gameplay, publisher authentication, or hostile directory-replacement isolation.
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

from star.re_asset_manifest import portable_asset_path, verify_asset_manifest


@pytest.mark.parametrize("character", ['<', '>', '"', '|', '?', '*'])
def test_windows_invalid_characters_are_rejected_even_on_posix(character):
    # Validate before touching disk so this behavior is identical on Windows
    # and POSIX, where these names could otherwise identify ordinary files.
    with pytest.raises(ValueError):
        portable_asset_path(f"assets/name{character}.bin")


@pytest.mark.parametrize("name", ["CONIN$", "CONOUT$", "conin$", "conout$"])
def test_windows_console_device_paths_are_rejected(name):
    with pytest.raises(ValueError):
        portable_asset_path(f"assets/{name}")


def test_earlier_asset_changed_during_later_read_cannot_pass(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    first = assets / "a.bin"
    second = assets / "b.bin"
    original_first = b"first-content"
    replacement = b"other-content"
    assert len(original_first) == len(replacement)
    first.write_bytes(original_first)
    second.write_bytes(b"second-content")
    entries = [
        {"path": path.relative_to(tmp_path).as_posix(),
         "size_bytes": path.stat().st_size,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in (first, second)
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": "star-asset-manifest-v1",
        "package_id": "independent-review-fixture", "version": "1", "assets": entries,
    }), encoding="utf-8")
    info = second.stat()
    second_identity = info.st_dev, info.st_ino
    original_fdopen = os.fdopen
    mutated = False

    class ReadObserver:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def read(self, size=-1):
            nonlocal mutated
            data = self.handle.read(size)
            if data and not mutated:
                # A has already completed its own before/after-read checks.
                # Mutating it while B is read tests the complete audit window.
                mutated = True
                before = first.stat()
                first.write_bytes(replacement)
                os.utime(first, ns=(before.st_atime_ns,
                                    before.st_mtime_ns + 1_000_000_000))
            return data

    def observed_fdopen(fd, *args, **kwargs):
        handle = original_fdopen(fd, *args, **kwargs)
        info = os.fstat(handle.fileno())
        return (ReadObserver(handle)
                if (info.st_dev, info.st_ino) == second_identity else handle)

    monkeypatch.setattr(os, "fdopen", observed_fdopen)
    result = verify_asset_manifest(
        manifest, lambda relative: tmp_path / relative, manifest_label="manifest.json",
    )

    assert mutated, "The later asset must actually be read for this regression"
    assert hashlib.sha256(first.read_bytes()).hexdigest() != entries[0]["sha256"]
    assert result["verdict"] == "FAIL"
    by_path = {row["path"]: row["status"] for row in result["results"]}
    assert by_path["assets/a.bin"] == "changed"
    assert by_path["assets/b.bin"] == "matched"
