"""Model-free host artifact verification tests (no live GPU, model or OBS)."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from star.stream_host_artifact_preflight import (
    HostArtifactPaths, verify_host_artifacts,
)
from star.stream_host_model_catalog import HostModelRoute
from star.stream_qos import InferenceJob


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def fixture(tmp_path: Path, *, with_voice=True):
    (tmp_path / "models").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "voice").mkdir()
    (tmp_path / "models" / "weights.gguf").write_bytes(b"actual weights 123")
    (tmp_path / "bin" / "llama-server.exe").write_bytes(b"compiled runtime 234")
    (tmp_path / "voice" / "star.json").write_bytes(b'{"pitch": 1}')
    route = HostModelRoute(
        "voice-1", "speech", "cpu", "pocket-tts",
        digest(b"actual weights 123"), digest(b"compiled runtime 234"),
        500, 0, digest(b'{"pitch": 1}') if with_voice else "",
    )
    paths = HostArtifactPaths(
        ("models/weights.gguf",), "bin/llama-server.exe",
        "voice/star.json" if with_voice else "",
    )
    return route, paths


def verify(tmp_path, route, paths, **kwargs):
    return verify_host_artifacts(tmp_path, (route,), {route.alias: paths}, **kwargs)


def test_valid_verified_catalog_can_bind_real_governor_job(tmp_path):
    route, paths = fixture(tmp_path)
    checked = verify(tmp_path, route, paths)
    assert checked.checked_files == 3
    assert checked.checked_bytes == len(b"actual weights 123compiled runtime 234") + len(b'{"pitch": 1}')
    assert checked.elapsed_ms >= 0
    bound = checked.catalog.bind(
        InferenceJob("tts", "speech", 1000, 1800, 1, 0, "auto"),
        route_alias="voice-1",
    )
    assert bound.route_profile == route.route_profile
    assert bound.ram_mib == 500


def test_no_voice_route_verifies_only_two_artifacts(tmp_path):
    route, paths = fixture(tmp_path, with_voice=False)
    assert verify(tmp_path, route, paths).checked_files == 2


def test_multi_shard_content_addressed_manifest(tmp_path):
    route, paths = fixture(tmp_path)
    (tmp_path / "models" / "second.gguf").write_bytes(b"shard2")
    files = ("models/weights.gguf", "models/second.gguf")
    entries = [[name, len((tmp_path / name).read_bytes()), digest((tmp_path / name).read_bytes())]
               for name in files]
    bundle = digest(b"STAR_MODEL_BUNDLE_V1\n" + json.dumps(
        entries, ensure_ascii=True, separators=(",", ":"),
    ).encode())
    route = replace(route, model_sha256=bundle)
    paths = replace(paths, model_files=files)
    assert verify(tmp_path, route, paths).checked_files == 4
    with pytest.raises(ValueError, match="digest mismatch"):
        verify(tmp_path, replace(route, model_sha256=digest(b"shard2")), paths)
    # Explicit shard ordering and names are part of the digest.
    with pytest.raises(ValueError, match="digest mismatch"):
        verify(tmp_path, route, replace(paths, model_files=files[::-1]))


@pytest.mark.parametrize("which", ["weights", "runtime", "voice"])
def test_modified_file_fails_before_catalog_is_available(tmp_path, which):
    route, paths = fixture(tmp_path)
    target = {"weights": paths.model_files[0], "runtime": paths.runtime_file,
              "voice": paths.voice_file}[which]
    (tmp_path / target).write_bytes(b"modified by someone after deployment")
    with pytest.raises(ValueError, match="digest mismatch"):
        verify(tmp_path, route, paths)


@pytest.mark.parametrize("field", ["model_sha256", "runtime_sha256", "voice_sha256"])
def test_false_expected_digests_rejected(tmp_path, field):
    route, paths = fixture(tmp_path)
    with pytest.raises(ValueError, match="digest mismatch"):
        verify(tmp_path, replace(route, **{field: "f" * 64}), paths)


@pytest.mark.parametrize("bad", [
    "../outside", "/tmp/foo", "C:/other", "models/../a",
    "models//a", "models/./a", "models\\a", "models/a\n", "",
])
def test_path_traversal_and_untrusted_path_syntax_fails(bad):
    with pytest.raises(ValueError):
        HostArtifactPaths((bad,), "bin/runtime")


def test_missing_extra_and_untyped_manifests_fail_closed(tmp_path):
    route, paths = fixture(tmp_path)
    for contents in ({}, {route.alias: paths, "other": paths},
                     {route.alias: {"model_files": paths.model_files}}):
        with pytest.raises(ValueError):
            verify_host_artifacts(tmp_path, (route,), contents)


def test_relative_paths_do_not_escape_trusted_root(tmp_path):
    route, paths = fixture(tmp_path)
    outside = tmp_path.parent / "foreign-artifact.gguf"
    outside.write_bytes(b"anything")
    link = tmp_path / "models" / "outside.gguf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support symlinks")
    with pytest.raises(ValueError, match="links"):
        verify(tmp_path, route, replace(paths, model_files=("models/outside.gguf",)))


def test_parent_directory_symlink_is_rejected(tmp_path):
    route, paths = fixture(tmp_path)
    try:
        (tmp_path / "shortcut").symlink_to(tmp_path / "models", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("filesystem does not support symlinks")
    with pytest.raises(ValueError, match="links"):
        verify(tmp_path, route, replace(paths, model_files=("shortcut/weights.gguf",)))


def test_rejects_duplicate_roles_missing_file_and_nonfile(tmp_path):
    route, paths = fixture(tmp_path)
    with pytest.raises(ValueError):
        HostArtifactPaths((paths.runtime_file,), paths.runtime_file)
    with pytest.raises(ValueError):
        HostArtifactPaths((paths.model_files[0],) * 2, paths.runtime_file)
    with pytest.raises(ValueError):
        verify(tmp_path, route, replace(paths, runtime_file="bin/missing"))
    with pytest.raises(ValueError):
        verify(tmp_path, route, replace(paths, runtime_file="bin"))


def test_voice_role_must_match_catalog_and_budget_is_total(tmp_path):
    route, paths = fixture(tmp_path)
    with pytest.raises(ValueError, match="voice"):
        verify(tmp_path, replace(route, voice_sha256=""), paths)
    with pytest.raises(ValueError, match="voice"):
        verify(tmp_path, route, replace(paths, voice_file=""))
    for max_bytes in (True, -1, 0, 65 * 1024**3):
        with pytest.raises(ValueError):
            verify(tmp_path, route, paths, max_total_bytes=max_bytes)
    with pytest.raises(ValueError, match="budget"):
        verify(tmp_path, route, paths, max_total_bytes=20)


def test_zero_byte_file_rejected_and_no_filename_in_system_error(tmp_path):
    route, paths = fixture(tmp_path)
    (tmp_path / paths.runtime_file).write_bytes(b"")
    with pytest.raises(ValueError, match="budget"):
        verify(tmp_path, route, paths)
    (tmp_path / paths.runtime_file).unlink()
    with pytest.raises(ValueError) as error:
        verify(tmp_path, route, paths)
    assert str(tmp_path) not in str(error.value)


def test_missing_root_and_wrong_root_are_not_allowed(tmp_path):
    route, paths = fixture(tmp_path)
    with pytest.raises(ValueError):
        verify(tmp_path / "nonexistent", route, paths)
    with pytest.raises(ValueError):
        verify(tmp_path / paths.model_files[0], route, paths)


def test_many_routes_all_or_nothing(tmp_path):
    route, paths = fixture(tmp_path)
    other = replace(route, alias="other", model_sha256="0"*64)
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_host_artifacts(
            tmp_path, (route, other), {route.alias: paths, other.alias: paths},
        )


def test_read_only_preflight_does_not_change_model_files(tmp_path):
    route, paths = fixture(tmp_path)
    before = [(tmp_path / name).read_bytes() for name in
              (*paths.model_files, paths.runtime_file, paths.voice_file)]
    verify(tmp_path, route, paths)
    after = [(tmp_path / name).read_bytes() for name in
             (*paths.model_files, paths.runtime_file, paths.voice_file)]
    assert before == after


def test_cli_checks_real_local_manifest_without_leaking_paths(tmp_path, capsys):
    from dataclasses import asdict
    from star.stream_host_artifact_preflight import main

    route, paths = fixture(tmp_path)
    declared = asdict(route)
    declared["artifacts"] = {
        "model_files": list(paths.model_files),
        "runtime_file": paths.runtime_file,
        "voice_file": paths.voice_file,
    }
    manifest = tmp_path / "owner-manifest.json"
    manifest.write_text(json.dumps({"routes": [declared]}))
    assert main(["--root", str(tmp_path), "--manifest", str(manifest)]) == 0
    message = capsys.readouterr().out
    report = json.loads(message)
    assert report["verified_routes"] == 1 and report["files"] == 3
    assert report["status"] == "passed"
    assert str(tmp_path) not in message and route.model_sha256 not in message
    declared["model_sha256"] = "a" * 64
    manifest.write_text(json.dumps({"routes": [declared]}))
    assert main(["--root", str(tmp_path), "--manifest", str(manifest)]) == 2
    error = capsys.readouterr().out
    assert json.loads(error)["status"] == "failed"
    assert str(tmp_path) not in error and "weights.gguf" not in error


@pytest.mark.parametrize("payload", [
    [],
    {"routes": []},
    {"routes": [1]},
    {"routes": [{}]},
    {"routes": [None]},
    {"routes": [{}], "unused": True},
])
def test_cli_rejects_malformed_manifest_without_running(payload, tmp_path, capsys):
    from star.stream_host_artifact_preflight import main
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload))
    assert main(["--root", str(tmp_path), "--manifest", str(manifest)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_optional_voice_file_must_have_string_type():
    with pytest.raises(ValueError, match="voice file"):
        HostArtifactPaths(("model.bin",), "bin/server", voice_file=False)


def test_limit_rejects_many_shards_and_oversize_manifest(tmp_path, capsys):
    from star.stream_host_artifact_preflight import main
    with pytest.raises(ValueError, match="bounded"):
        HostArtifactPaths(tuple(f"x/{i}.gguf" for i in range(129)), "bin/server")
    config = tmp_path / "manifest.json"
    config.write_bytes(b"x" * (256*1024 + 1))
    assert main(["--root", str(tmp_path), "--manifest", str(config)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
