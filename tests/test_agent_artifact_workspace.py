"""Regression tests for STAR's lease-fenced virtual artifact workspace."""
from pathlib import Path
import sqlite3

import pytest

from star import agent_run_coordinator as coordinator_module
from star.agent_run_coordinator import (
    AgentRunCoordinator,
    ArtifactConflictError,
    CoordinatorError,
    StaleLeaseError,
)
from star.orchestration import Task, TaskPlan


class FakeClock:
    def __init__(self):
        self.value = 1_800_000_000_000_000_000

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += int(seconds * 1_000_000_000)


def make_coordinator(tmp_path: Path, *, clock=None, lease_seconds=1):
    private = tmp_path / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    private.chmod(0o700)
    return AgentRunCoordinator(
        private / "runs.sqlite3",
        clock_ns=clock or __import__("time").time_ns,
        lease_seconds=lease_seconds,
    )


def test_artifact_commit_is_fenced_and_readable_inside_declared_scope(tmp_path):
    plan = TaskPlan([
        Task("edit", "luau", "Create a script", reads=("game/scripts",),
             writes=("game/scripts",)),
    ])
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-1", plan)
    lease = coordinator.claim_next("workspace-1", "worker-a")

    receipt = coordinator.commit_artifact(
        lease, resource="game/scripts/main.server.lua",
        content="print('hello')", commit_id="commit-1",
    )
    record = coordinator.read_artifact(lease, "game/scripts/main.server.lua")

    assert receipt.status == "committed"
    assert receipt.version == 1
    assert record is not None
    assert record.content == b"print('hello')"
    assert record.sha256 == receipt.sha256
    assert record.fencing_token == lease.fencing_token
    assert coordinator.complete(lease, answer="Created the script") == "completed"


def test_artifact_compare_and_swap_rejects_stale_base_digest(tmp_path):
    plan = TaskPlan([
        Task("edit", "luau", "Update a script", reads=("src",), writes=("src",)),
    ])
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-2", plan)
    lease = coordinator.claim_next("workspace-2", "worker-a")

    first = coordinator.commit_artifact(
        lease, resource="src/main.lua", content="v1", commit_id="commit-v1",
    )
    second = coordinator.commit_artifact(
        lease, resource="src/main.lua", content="v2", commit_id="commit-v2",
        expected_sha256=first.sha256,
    )
    assert second.version == 2
    with pytest.raises(ArtifactConflictError, match="changed since"):
        coordinator.commit_artifact(
            lease, resource="src/main.lua", content="stale v3",
            commit_id="commit-stale", expected_sha256=first.sha256,
        )


def test_identical_commit_retry_is_idempotent_but_commit_id_reuse_is_rejected(tmp_path):
    plan = TaskPlan([Task("edit", "ui", "Create UI", writes=("ui",))])
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-3", plan)
    lease = coordinator.claim_next("workspace-3", "worker-a")
    kwargs = {
        "resource": "ui/hud.json",
        "content": '{"health":100}',
        "commit_id": "stable-commit",
    }

    first = coordinator.commit_artifact(lease, **kwargs)
    retry = coordinator.commit_artifact(lease, **kwargs)
    assert first.status == "committed"
    assert retry.status == "already_committed"
    assert retry.version == first.version

    with pytest.raises(ArtifactConflictError, match="Commit ID"):
        coordinator.commit_artifact(
            lease, resource="ui/hud.json", content='{"health":0}',
            commit_id="stable-commit",
        )


def test_expired_worker_cannot_commit_after_a_new_fenced_lease_is_issued(tmp_path):
    clock = FakeClock()
    plan = TaskPlan([Task("edit", "luau", "Edit script", writes=("src",))])
    coordinator = make_coordinator(tmp_path, clock=clock)
    coordinator.register_run("workspace-4", plan)
    stale = coordinator.claim_next("workspace-4", "worker-old")
    clock.advance(2)
    current = coordinator.claim_next("workspace-4", "worker-new")

    assert current.fencing_token > stale.fencing_token
    with pytest.raises(StaleLeaseError):
        coordinator.commit_artifact(
            stale, resource="src/main.lua", content="stale",
            commit_id="stale-commit",
        )
    receipt = coordinator.commit_artifact(
        current, resource="src/main.lua", content="fresh",
        commit_id="fresh-commit",
    )
    assert receipt.status == "committed"


def test_artifact_from_failed_task_is_not_published_to_an_independent_reader(tmp_path):
    plan = TaskPlan([
        Task("writer", "luau", "Write a file", writes=("src",)),
        Task("reader", "review", "Inspect a file", reads=("src",)),
    ], max_parallel=2)
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-5", plan)
    writer = coordinator.claim_next("workspace-5", "worker-a")
    coordinator.commit_artifact(
        writer, resource="src/main.lua", content="partial",
        commit_id="partial-commit",
    )
    assert coordinator.claim_next("workspace-5", "worker-b") is None

    coordinator.fail(writer, error_code="worker_failed", retryable=False)
    reader = coordinator.claim_next("workspace-5", "worker-b")
    assert reader.task.id == "reader"
    with pytest.raises(ArtifactConflictError, match="not visible"):
        coordinator.read_artifact(reader, "src/main.lua")
    with pytest.raises(ArtifactConflictError, match="not published"):
        coordinator.commit_artifact(
            reader, resource="src/main.lua", content="overwrite",
            commit_id="blocked-overwrite",
        )


def test_uncompleted_writer_artifact_becomes_visible_after_task_completion(tmp_path):
    plan = TaskPlan([
        Task("writer", "luau", "Write a file", writes=("src",)),
        Task("reader", "review", "Inspect the file", reads=("src",),
             dependencies=("writer",)),
    ], max_parallel=2)
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-6", plan)
    writer = coordinator.claim_next("workspace-6", "worker-a")
    coordinator.commit_artifact(
        writer, resource="src/main.lua", content="complete",
        commit_id="publish-me",
    )
    coordinator.complete(writer, answer="File is ready")

    reader = coordinator.claim_next("workspace-6", "worker-b")
    record = coordinator.read_artifact(reader, "src/main.lua")
    assert record is not None
    assert record.content == b"complete"


def test_artifact_paths_must_be_relative_and_inside_declared_scope(tmp_path):
    plan = TaskPlan([Task("edit", "luau", "Edit", writes=("src",))])
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-7", plan)
    lease = coordinator.claim_next("workspace-7", "worker-a")

    for bad in ("../secret", "/absolute/file", "src\\..\\secret", "C:/secret"):
        with pytest.raises((ValueError, PermissionError)):
            coordinator.commit_artifact(
                lease, resource=bad, content="no", commit_id="bad-" + str(len(bad)),
            )
    with pytest.raises(PermissionError, match="declared write scopes"):
        coordinator.commit_artifact(
            lease, resource="secrets/key.txt", content="no",
            commit_id="outside-scope",
        )


def test_artifact_size_limit_and_corruption_detection(tmp_path):
    plan = TaskPlan([Task("edit", "ui", "Write artifact", writes=("assets",))])
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-8", plan)
    lease = coordinator.claim_next("workspace-8", "worker-a")

    with pytest.raises(ValueError, match="4 MiB"):
        coordinator.commit_artifact(
            lease, resource="assets/too-large.bin",
            content=b"x" * (4 * 1024 * 1024 + 1), commit_id="too-large",
        )
    receipt = coordinator.commit_artifact(
        lease, resource="assets/data.bin", content=b"original",
        commit_id="good",
    )

    connection = sqlite3.connect(coordinator.database)
    try:
        connection.execute(
            "UPDATE artifacts SET content=? WHERE run_id=? AND resource=?",
            (b"tampered", "workspace-8", "assets/data.bin"),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(CoordinatorError, match="integrity"):
        coordinator.read_artifact(lease, "assets/data.bin")


def test_artifact_workspace_isolated_between_runs(tmp_path):
    coordinator = make_coordinator(tmp_path)
    writer_plan = TaskPlan([Task("writer", "ui", "Write", writes=("ui",))])
    reader_plan = TaskPlan([Task("reader", "review", "Read", reads=("ui",))])
    coordinator.register_run("workspace-9a", writer_plan)
    writer = coordinator.claim_next("workspace-9a", "worker-a")
    coordinator.commit_artifact(
        writer, resource="ui/config.json", content="{}", commit_id="run-a",
    )
    coordinator.complete(writer, answer="done")

    coordinator.register_run("workspace-9b", reader_plan)
    reader = coordinator.claim_next("workspace-9b", "worker-b")
    assert coordinator.read_artifact(reader, "ui/config.json") is None


def test_schema_v2_database_migrates_to_artifact_schema_v3(tmp_path):
    plan = TaskPlan([Task("edit", "luau", "Edit", writes=("src",))])
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-10", plan)
    connection = sqlite3.connect(coordinator.database)
    try:
        connection.execute("DROP TABLE artifact_commits")
        connection.execute("DROP TABLE artifacts")
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    finally:
        connection.close()

    migrated = AgentRunCoordinator(coordinator.database)
    connection = sqlite3.connect(migrated.database)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()
    assert version == 3
    assert {"artifacts", "artifact_commits"} <= tables
    assert migrated.register_run("workspace-10", plan) is False


def test_per_run_artifact_count_and_byte_quotas_are_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(coordinator_module, "_MAX_RUN_ARTIFACTS", 1)
    monkeypatch.setattr(coordinator_module, "_MAX_RUN_ARTIFACT_BYTES", 5)
    plan = TaskPlan([Task("edit", "ui", "Write assets", writes=("assets",))])
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("workspace-11", plan)
    lease = coordinator.claim_next("workspace-11", "worker-a")

    first = coordinator.commit_artifact(
        lease, resource="assets/a.bin", content=b"12345", commit_id="quota-first",
    )
    with pytest.raises(CoordinatorError, match="artifact-count"):
        coordinator.commit_artifact(
            lease, resource="assets/b.bin", content=b"x", commit_id="quota-second",
        )
    with pytest.raises(CoordinatorError, match="artifact-storage"):
        coordinator.commit_artifact(
            lease, resource="assets/a.bin", content=b"123456",
            commit_id="quota-too-many-bytes", expected_sha256=first.sha256,
        )
