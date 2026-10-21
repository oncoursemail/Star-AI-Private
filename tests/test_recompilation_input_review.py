"""Independent regressions for the original recompilation input boundary.

All files are synthetic temporary fixtures. These tests exercise observation
and rejection behavior; they do not run a guest binary or contact a service.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import re_analysis_input as inputs


def _read(root, specs):
    return inputs.read_inputs(root, lambda label: root / label, specs)


def _forbid_open(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("File content was opened before all inputs passed preflight")

    monkeypatch.setattr(inputs.os, "open", forbidden)


def _observe_reads(monkeypatch, callback):
    original = inputs.os.fdopen

    class ObservedFile:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def fileno(self):
            return self.handle.fileno()

        def read(self, amount):
            block = self.handle.read(amount)
            callback(self.handle, block)
            return block

    monkeypatch.setattr(inputs.os, "fdopen", lambda *a, **kw: ObservedFile(original(*a, **kw)))


def test_complete_reads_have_exact_identity_and_limited_provenance(tmp_path):
    first = b'{"case":"ppu-carry","observed":"00000000"}'
    second = b'\x7fELF' + bytes(range(64))
    (tmp_path / "expected.json").write_bytes(first)
    (tmp_path / "sample.elf").write_bytes(second)
    wanted = hashlib.sha256(first).hexdigest()

    snapshots = _read(tmp_path, [
        inputs.InputSpec("expected.json", len(first), wanted.upper()),
        inputs.InputSpec("sample.elf", len(second)),
    ])

    assert [item.data for item in snapshots] == [first, second]
    assert snapshots[0].sha256 == wanted
    assert snapshots[0].receipt() == {
        "path": "expected.json", "size_bytes": len(first), "sha256": wanted,
        "pin_checked": True, "provenance": "not_authenticated",
    }
    assert snapshots[1].receipt()["pin_checked"] is False
    inputs.assert_inputs_stable(tmp_path, snapshots)


@pytest.mark.parametrize("failure", ["missing", "oversize", "bad_pin", "directory"])
def test_later_invalid_input_prevents_reading_earlier_file(tmp_path, monkeypatch, failure):
    (tmp_path / "first.json").write_bytes(b"{}")
    later = tmp_path / "later.json"
    pin = None
    if failure == "directory":
        later.mkdir()
    elif failure != "missing":
        later.write_bytes(b"0123456789" if failure == "oversize" else b"{}")
    if failure == "bad_pin":
        pin = "not-a-digest"
    _forbid_open(monkeypatch)

    with pytest.raises((ValueError, OSError)):
        _read(tmp_path, [inputs.InputSpec("first.json", 2), inputs.InputSpec("later.json", 2, pin)])


@pytest.mark.parametrize("label", [
    "", "/absolute", "../escape", "a/../b", "a/./b", "a//b", "a/",
    "C:/file", "a\\b", "a:stream", "bad<name", "bad>name", 'bad"name',
    "bad|name", "bad?name", "bad*name", "trailing.", "trailing ",
    "a\x00b", "a\x1fb", "NUL", "con.txt", "COM1.log", "LPT³.log",
    "CONIN$", "conout$.json",
])
def test_ambiguous_portable_path_is_rejected_before_resolver(tmp_path, label):
    def unexpected(_label):
        pytest.fail("Invalid portable path reached the resolver")

    with pytest.raises((ValueError, PermissionError)):
        inputs.read_inputs(tmp_path, unexpected, [inputs.InputSpec(label, 16)])


def test_resolver_cannot_return_a_file_outside_workspace(tmp_path, monkeypatch):
    root = tmp_path / "selected"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}")
    _forbid_open(monkeypatch)

    with pytest.raises(PermissionError, match="escapes"):
        inputs.read_inputs(root, lambda _label: outside, [inputs.InputSpec("sample.json", 2)])


@pytest.mark.parametrize("kind", ["file", "ancestor", "root"])
def test_symlinks_are_rejected_without_opening(tmp_path, monkeypatch, kind):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "sample.json").write_bytes(b"{}")
    selected = root
    label = "sample.json"
    try:
        if kind == "file":
            (root / "link.json").symlink_to(root / "sample.json")
            label = "link.json"
        elif kind == "ancestor":
            (root / "linked").symlink_to(root, target_is_directory=True)
            label = "linked/sample.json"
        else:
            selected = tmp_path / "linked_root"
            selected.symlink_to(root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"This platform does not permit creating a test symlink: {exc}")
    _forbid_open(monkeypatch)

    with pytest.raises(PermissionError):
        _read(selected, [inputs.InputSpec(label, 2)])


def test_windows_reparse_attribute_is_rejected_on_any_host(tmp_path, monkeypatch):
    target = tmp_path / "sample.json"
    target.write_bytes(b"{}")
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_mode=value.st_mode, st_file_attributes=0x400)
        return value

    monkeypatch.setattr(Path, "lstat", reparse)
    _forbid_open(monkeypatch)
    with pytest.raises(PermissionError, match="reparse"):
        _read(tmp_path, [inputs.InputSpec("sample.json", 2)])


@pytest.mark.parametrize("kind", ["same_name", "hardlink", "casefold", "unicode_nfc"])
def test_distinct_case_inputs_cannot_alias(tmp_path, monkeypatch, kind):
    left, right = "first.json", "second.json"
    if kind == "same_name":
        right = left
    elif kind == "casefold":
        left, right = "Report.json", "report.json"
    elif kind == "unicode_nfc":
        left, right = "\u00e9.json", "e\u0301.json"
    (tmp_path / left).write_bytes(b"{}")
    if kind == "hardlink":
        try:
            os.link(tmp_path / left, tmp_path / right)
        except OSError as exc:
            pytest.skip(f"This platform cannot create a hardlink fixture: {exc}")
    elif kind != "same_name":
        (tmp_path / right).write_bytes(b"{}")
    _forbid_open(monkeypatch)

    with pytest.raises(ValueError, match="aliases"):
        _read(tmp_path, [inputs.InputSpec(left, 2), inputs.InputSpec(right, 2)])


def test_wrong_content_pin_fails_even_when_size_matches(tmp_path):
    (tmp_path / "sample.json").write_bytes(b'{"a":1}')
    other = hashlib.sha256(b'{"a":2}').hexdigest()
    with pytest.raises(ValueError, match="SHA-256"):
        _read(tmp_path, [inputs.InputSpec("sample.json", 7, other)])


def test_same_size_mutation_during_its_own_read_is_rejected(tmp_path, monkeypatch):
    target = tmp_path / "sample.json"
    target.write_bytes(b"AAAA")
    changed = False

    def mutate(_handle, block):
        nonlocal changed
        if block and not changed:
            changed = True
            target.write_bytes(b"BBBB")

    _observe_reads(monkeypatch, mutate)
    with pytest.raises(ValueError, match="changed"):
        _read(tmp_path, [inputs.InputSpec("sample.json", 4)])
    assert changed


def test_earlier_input_mutated_during_later_read_cannot_return_complete_receipts(tmp_path, monkeypatch):
    earlier = tmp_path / "expected.json"
    later = tmp_path / "observed.json"
    earlier.write_bytes(b"AAAA")
    later.write_bytes(b"BBBB")
    later_inode = later.stat().st_ino
    changed = False

    def mutate(handle, block):
        nonlocal changed
        if block and os.fstat(handle.fileno()).st_ino == later_inode and not changed:
            changed = True
            earlier.write_bytes(b"CCCC")

    _observe_reads(monkeypatch, mutate)
    with pytest.raises(ValueError, match="changed"):
        _read(tmp_path, [inputs.InputSpec("expected.json", 4), inputs.InputSpec("observed.json", 4)])
    assert changed


def test_input_growth_is_stopped_at_the_byte_budget(tmp_path, monkeypatch):
    target = tmp_path / "sample.json"
    target.write_bytes(b"{}")
    changed = False

    def append(_handle, block):
        nonlocal changed
        if block and not changed:
            changed = True
            with target.open("ab") as output:
                output.write(b"x")

    _observe_reads(monkeypatch, append)
    with pytest.raises(ValueError, match="byte budget"):
        _read(tmp_path, [inputs.InputSpec("sample.json", 2)])


def test_comparison_phase_mutation_is_detected_by_final_recheck(tmp_path):
    target = tmp_path / "sample.json"
    target.write_bytes(b"AAAA")
    snapshots = _read(tmp_path, [inputs.InputSpec("sample.json", 4)])
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b"BBBB")
    replacement.replace(target)

    with pytest.raises(ValueError, match="changed"):
        inputs.assert_inputs_stable(tmp_path, snapshots)


def test_read_budget_exhaustion_during_streaming_fails(tmp_path, monkeypatch):
    (tmp_path / "sample.json").write_bytes(b"{}")
    clock = [10.0]
    monkeypatch.setattr(inputs.time, "monotonic", lambda: clock[0])

    def consume_budget(_handle, block):
        if block:
            clock[0] += inputs.READ_TIMEOUT_SECONDS

    _observe_reads(monkeypatch, consume_budget)
    with pytest.raises(ValueError, match="budget was exhausted"):
        _read(tmp_path, [inputs.InputSpec("sample.json", 2)])


@pytest.mark.parametrize("budget", [0, -1, True, 1.0, inputs.MAX_ELF_BYTES + 1])
def test_invalid_read_budgets_never_open(tmp_path, monkeypatch, budget):
    _forbid_open(monkeypatch)
    with pytest.raises(ValueError, match="byte budget"):
        _read(tmp_path, [inputs.InputSpec("sample.json", budget)])


@pytest.mark.parametrize("document", [
    b'{"a":1,"a":2}', b'{"nested":{"x":1,"x":2}}',
    b'{"value":NaN}', b'{"value":Infinity}', b'{"value":-Infinity}',
    b'{"value":1e9999}', b'{"value":-1e9999}',
    b"[]", b"null", b"true", b"1", b'"text"', b"", b"\xff",
    b'{"a":1} trailing', b'{"a":1,}', b"\xef\xbb\xbf{}",
])
def test_json_rejects_ambiguous_or_non_object_evidence(document):
    with pytest.raises(ValueError):
        inputs.parse_strict_json(document)


def test_json_has_a_separate_size_cap():
    with pytest.raises(ValueError):
        inputs.parse_strict_json(b" " * (inputs.MAX_JSON_BYTES + 1))


def test_strict_json_preserves_valid_exact_integer_and_unicode_fields():
    assert inputs.parse_strict_json('{"case":"\u00e9","word":18446744073709551615,"nested":{"ok":true}}'.encode()) == {
        "case": "\u00e9", "word": 18446744073709551615, "nested": {"ok": True},
    }
