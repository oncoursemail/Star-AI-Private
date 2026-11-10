"""Tests for host-owned materialization of completed agent artifacts."""
import hashlib
import os
from pathlib import Path
import sqlite3

import pytest

from star.agent_artifact_materializer import (
    ArtifactStagingMaterializer,
    MaterializationConflict,
    MaterializationError,
)
from star.agent_run_coordinator import (
    AgentRunCoordinator,
    ArtifactConflictError,
    CoordinatorError,
)
from star.orchestration import Task, TaskPlan


def private_database(tmp_path: Path) -> Path:
    directory = tmp_path / "private-db"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory / "runs.sqlite3"


def completed_run(tmp_path: Path, content: bytes = b"print('star')\n"):
    task = Task("build", "integration", "Build a bounded source artifact",
                writes=("src",))
    plan = TaskPlan([task])
    coordinator = AgentRunCoordinator(private_database(tmp_path))
    coordinator.register_run("run-1", plan)
    lease = coordinator.claim_next("run-1", "trusted-builder")
    assert lease is not None
    coordinator.commit_artifact(
        lease, resource="src/main.py", content=content, commit_id="commit-1"
    )
    coordinator.complete(lease, answer="artifact built")
    assert coordinator.finish_run("run-1", plan) == "completed"
    return coordinator


def test_completed_artifact_requires_successful_run(tmp_path):
    task = Task("build", "integration", "Build", writes=("src",))
    plan = TaskPlan([task])
    coordinator = AgentRunCoordinator(private_database(tmp_path))
    coordinator.register_run("run-1", plan)
    lease = coordinator.claim_next("run-1", "builder")
    coordinator.commit_artifact(
        lease, resource="src/main.py", content=b"ok", commit_id="commit-1"
    )
    with pytest.raises(ArtifactConflictError):
        coordinator.read_completed_artifact("run-1", "src/main.py")
    coordinator.complete(lease, answer="done")
    assert coordinator.finish_run("run-1", plan) == "completed"
    record = coordinator.read_completed_artifact("run-1", "src/main.py")
    assert record is not None
    assert record.content == b"ok"
    assert record.fencing_token == lease.fencing_token


def test_completed_artifact_checks_immutable_commit_receipt(tmp_path):
    coordinator = completed_run(tmp_path, b"trusted bytes")
    with sqlite3.connect(coordinator.database) as db:
        db.execute(
            "UPDATE artifact_commits SET new_sha256=? WHERE run_id=? AND resource=?",
            ("0" * 64, "run-1", "src/main.py"),
        )
    with pytest.raises(CoordinatorError):
        coordinator.read_completed_artifact("run-1", "src/main.py")


def test_materializer_creates_only_inside_dedicated_staging_root(tmp_path):
    coordinator = completed_run(tmp_path)
    materializer = ArtifactStagingMaterializer.initialize(tmp_path / "stage")
    receipt = materializer.materialize(coordinator, "run-1", "src/main.py")
    assert receipt is not None
    assert receipt.status == "materialized"
    assert receipt.path == tmp_path / "stage" / "run-1" / "src" / "main.py"
    assert receipt.path.read_bytes() == b"print('star')\n"
    assert receipt.sha256 == hashlib.sha256(receipt.path.read_bytes()).hexdigest()


def test_materialization_is_idempotent_for_identical_content(tmp_path):
    coordinator = completed_run(tmp_path, b"same")
    materializer = ArtifactStagingMaterializer.initialize(tmp_path / "stage")
    first = materializer.materialize(coordinator, "run-1", "src/main.py")
    second = materializer.materialize(coordinator, "run-1", "src/main.py")
    assert first.status == "materialized"
    assert second.status == "already_present"
    assert first.sha256 == second.sha256


def test_existing_different_target_requires_exact_compare_and_swap(tmp_path):
    coordinator = completed_run(tmp_path, b"new source")
    materializer = ArtifactStagingMaterializer.initialize(tmp_path / "stage")
    first = materializer.materialize(coordinator, "run-1", "src/main.py")
    first.path.write_bytes(b"external edit")
    with pytest.raises(MaterializationConflict):
        materializer.materialize(coordinator, "run-1", "src/main.py")
    expected = hashlib.sha256(b"external edit").hexdigest()
    updated = materializer.materialize(
        coordinator, "run-1", "src/main.py", expected_current_sha256=expected
    )
    assert updated.status == "materialized"
    assert updated.path.read_bytes() == b"new source"


def test_missing_target_rejects_nonempty_expected_digest(tmp_path):
    coordinator = completed_run(tmp_path)
    materializer = ArtifactStagingMaterializer.initialize(tmp_path / "stage")
    with pytest.raises(MaterializationConflict):
        materializer.materialize(
            coordinator, "run-1", "src/main.py", expected_current_sha256="a" * 64
        )


def test_staging_root_must_be_outside_git_worktrees(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").mkdir()
    with pytest.raises(MaterializationError):
        ArtifactStagingMaterializer.initialize(repository / "staging")


def test_unmarked_nonempty_directory_is_not_adopted(tmp_path):
    root = tmp_path / "stage"
    root.mkdir()
    (root / "user-data.txt").write_text("keep")
    with pytest.raises(MaterializationError):
        ArtifactStagingMaterializer.initialize(root)


def test_staging_root_symlink_is_rejected(tmp_path):
    if os.name == "nt":
        pytest.skip("Symlink creation may require Windows developer mode or privilege")
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(MaterializationError):
        ArtifactStagingMaterializer.initialize(link)


def test_target_symlink_is_rejected(tmp_path):
    if os.name == "nt":
        pytest.skip("Symlink creation may require Windows developer mode or privilege")
    coordinator = completed_run(tmp_path)
    materializer = ArtifactStagingMaterializer.initialize(tmp_path / "stage")
    parent = tmp_path / "stage" / "run-1" / "src"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not replace")
    (parent / "main.py").symlink_to(outside)
    with pytest.raises(MaterializationError):
        materializer.materialize(coordinator, "run-1", "src/main.py")
    assert outside.read_text() == "do not replace"


def test_parent_symlink_is_rejected(tmp_path):
    if os.name == "nt":
        pytest.skip("Symlink creation may require Windows developer mode or privilege")
    coordinator = completed_run(tmp_path)
    materializer = ArtifactStagingMaterializer.initialize(tmp_path / "stage")
    root = tmp_path / "stage"
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "run-1").symlink_to(outside, target_is_directory=True)
    with pytest.raises(MaterializationError):
        materializer.materialize(coordinator, "run-1", "src/main.py")
    assert list(outside.iterdir()) == []


def test_materializer_rejects_invalid_resource_path(tmp_path):
    coordinator = completed_run(tmp_path)
    materializer = ArtifactStagingMaterializer.initialize(tmp_path / "stage")
    with pytest.raises(ValueError):
        materializer.materialize(coordinator, "run-1", "../escape.py")


def test_materializer_rejects_uninitialized_root(tmp_path):
    with pytest.raises(MaterializationError):
        ArtifactStagingMaterializer(tmp_path / "missing")
