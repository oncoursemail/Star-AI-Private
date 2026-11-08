"""Synthetic, offline-only regression tests: never execute an EXE or capture audio."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest

from star.process_loopback_artifact_audit import (
    PortableVoiceArtifactError,
    audit_portable_voice_artifact,
    main,
)

COMMIT = "a" * 40
TREE = "b" * 40
V2 = "star.process_loopback.windows_diagnostic_artifact.v2"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def artifact(tmp_path: Path) -> tuple[Path, dict, dict]:
    folder = tmp_path / "downloaded"
    folder.mkdir()
    exe = b"synthetic executable bytes - NEVER execute this file"
    readme = b"local README\n"
    (folder / "Star.ProcessLoopback.exe").write_bytes(exe)
    (folder / "README.md").write_bytes(readme)
    record = {
        "schema": V2,
        "checkout_commit": COMMIT,
        "checkout_tree": TREE,
        "executable_sha256": digest(exe),
        "readme_sha256": digest(readme),
        "platform": "windows-x64",
        "requires_installed_dotnet": False,
        "self_test_passed": True,
        "live_audio_capture_tested": False,
        "quiet_evidence_verified": False,
        "permitted_to_stream": False,
    }
    (folder / "manifest.json").write_text(json.dumps(record), encoding="utf-8")
    args = {
        "approved_root": tmp_path,
        "expected_manifest_sha256": digest((folder / "manifest.json").read_bytes()),
        "expected_executable_sha256": digest(exe),
        "expected_checkout_commit": COMMIT,
        "expected_checkout_tree": TREE,
        "owner_approved": True,
    }
    return folder, record, args


def test_verified_artifact_is_only_byte_integrity_not_capture_authorization(artifact):
    folder, _, options = artifact
    result = audit_portable_voice_artifact(folder, **options)
    assert result.manifest_digest_matches
    assert result.executable_digest_matches
    assert result.source_commit_matches
    assert result.readme_digest_matches
    assert not result.verified_audio_capture
    assert not result.verified_physical_silence
    assert not result.verified_gameplay_skill
    assert not result.authorized_to_run_executable
    assert not result.authorized_to_record
    assert not result.authorized_to_broadcast
    assert json.loads(result.to_json()) == asdict(result)


def test_owner_gate_and_source_pins(artifact):
    folder, _, options = artifact
    with pytest.raises(PermissionError):
        audit_portable_voice_artifact(folder, **{**options, "owner_approved": False})
    for field in (
        "expected_manifest_sha256",
        "expected_executable_sha256",
        "expected_checkout_commit",
        "expected_checkout_tree",
    ):
        with pytest.raises(PortableVoiceArtifactError):
            audit_portable_voice_artifact(folder, **{**options, field: "x"})
        with pytest.raises(PortableVoiceArtifactError):
            audit_portable_voice_artifact(folder, **{**options, field: True})


@pytest.mark.parametrize(
    "name",
    ["expected_manifest_sha256", "expected_executable_sha256", "expected_checkout_commit", "expected_checkout_tree"],
)
def test_independent_mismatch_fail_closed(artifact, name):
    folder, _, options = artifact
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(
            folder,
            **{
                **options,
                name: ("f" * 40 if "checkout" in name else "f" * 64),
            },
        )


@pytest.mark.parametrize(
    "tamper",
    [
        ("schema", "untrusted.v1"),
        ("platform", "linux"),
        ("requires_installed_dotnet", True),
        ("self_test_passed", False),
        ("live_audio_capture_tested", True),
        ("quiet_evidence_verified", True),
        ("permitted_to_stream", True),
        ("checkout_commit", "f" * 40),
        ("checkout_tree", "f" * 40),
        ("executable_sha256", "f" * 64),
        ("readme_sha256", "f" * 64),
    ],
)
def test_invalid_claims_and_pins_rejected_even_if_manifest_recommitted(artifact, tamper):
    folder, record, options = artifact
    field, value = tamper
    record[field] = value
    text = json.dumps(record).encode()
    (folder / "manifest.json").write_bytes(text)
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(
            folder,
            **{
                **options,
                "expected_manifest_sha256": digest(text),
            },
        )


@pytest.mark.parametrize(
    "field, replacement",
    [
        ("schema", 5),
        ("platform", True),
        ("self_test_passed", 1),
        ("permitted_to_stream", 0),
        ("requires_installed_dotnet", 0),
        ("executable_sha256", None),
    ],
)
def test_type_confusion_rejected(artifact, field, replacement):
    folder, record, options = artifact
    record[field] = replacement
    text = json.dumps(record).encode()
    (folder / "manifest.json").write_bytes(text)
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(
            folder,
            **{
                **options,
                "expected_manifest_sha256": digest(text),
            },
        )


def test_reject_unexpected_files_manifest_truncation_and_byte_tampering(artifact):
    folder, _, options = artifact
    extra = folder / "surprise.dll"
    extra.write_bytes(b"evil")
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **options)
    extra.unlink()
    (folder / "Star.ProcessLoopback.exe").write_bytes(b"changed")
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **options)
    (folder / "Star.ProcessLoopback.exe").write_bytes(b"synthetic executable bytes - NEVER execute this file")
    (folder / "README.md").write_bytes(b"modified")
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **options)
    (folder / "README.md").write_bytes(b"local README\n")
    (folder / "manifest.json").write_bytes(b"x" * 4097)
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **options)


def test_duplicate_keys_missing_key_and_non_json_fail_closed(artifact):
    folder, record, options = artifact
    tests = [
        ('{"schema":"a","schema":"b"}').encode(),
        json.dumps({key: value for key, value in record.items() if key != "schema"}).encode(),
        b"\xff",
        b'{"bad":NaN}',
        b"[]",
    ]
    for payload in tests:
        (folder / "manifest.json").write_bytes(payload)
        with pytest.raises(PortableVoiceArtifactError):
            audit_portable_voice_artifact(
                folder,
                **{
                    **options,
                    "expected_manifest_sha256": digest(payload),
                },
            )


def test_local_directory_enclosure_and_missing_files(artifact, tmp_path):
    folder, _, options = artifact
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(Path("relative"), **options)
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **{**options, "approved_root": tmp_path / "other"})
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder.parent / ".." / folder.name, **options)
    (folder / "README.md").unlink()
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **options)


def test_symlinked_directory_or_binary_never_followed(artifact, tmp_path):
    folder, _, options = artifact
    real = folder / "Star.ProcessLoopback.exe"
    alias = folder / "synthetic.temp"
    real.rename(alias)
    try:
        real.symlink_to(alias)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privileges unavailable")
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **options)
    real.unlink()
    alias.rename(real)
    shortcut = tmp_path / "linked"
    shortcut.symlink_to(folder, target_is_directory=True)
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(shortcut, **options)


def test_hardlinked_binary_denied(artifact, tmp_path):
    folder, _, options = artifact
    extra = tmp_path / "alias"
    try:
        extra.hardlink_to(folder / "Star.ProcessLoopback.exe")
    except (OSError, NotImplementedError):
        pytest.skip("hardlink not available")
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **options)


def test_generic_cli_does_not_leak_paths_or_trust_without_explicit_consent(artifact, capsys):
    folder, _, options = artifact
    argv = [
        "--artifact-dir",
        str(folder),
        "--approved-root",
        str(options["approved_root"]),
        "--expected-manifest-sha256",
        options["expected_manifest_sha256"],
        "--expected-executable-sha256",
        options["expected_executable_sha256"],
        "--expected-checkout-commit",
        options["expected_checkout_commit"],
        "--expected-checkout-tree",
        options["expected_checkout_tree"],
    ]
    assert main(argv) == 2
    capture = capsys.readouterr()
    assert str(folder) not in capture.err
    assert capture.out == ""
    assert main(argv + ["--owner-approved"]) == 0
    capture = capsys.readouterr()
    assert json.loads(capture.out)["authorized_to_broadcast"] is False
    assert str(folder) not in capture.out


def test_manifest_directory_symlinks_unexpected_entries_and_no_exec(artifact):
    folder, _, options = artifact
    (folder / "run.ps1").write_text("bad", encoding="utf-8")
    with pytest.raises(PortableVoiceArtifactError):
        audit_portable_voice_artifact(folder, **options)
    (folder / "run.ps1").unlink()
    assert audit_portable_voice_artifact(folder, **options).authorized_to_run_executable is False
