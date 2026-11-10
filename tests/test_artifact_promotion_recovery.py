"""Crash-recovery regressions for STAR's host-owned artifact staging journal."""
import hashlib
from pathlib import Path
import sqlite3

import pytest

from star.agent_artifact_materializer import (
    ArtifactStagingMaterializer,
    MaterializationError,
)
from star.artifact_promotion_journal import PromotionJournalError
from star.orchestration import Task, TaskPlan


def private_database(tmp_path: Path) -> Path:
    directory = tmp_path / "private-db"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory / "runs.sqlite3"


def completed_run(tmp_path: Path, content: bytes = b"print('star')\n"):
    task = Task("build", "integration", "Build a bounded source artifact", writes=("src",))
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


def test_successful_materialization_commits_durable_intent(tmp_path):
    coordinator = completed_run(tmp_path)
    root = tmp_path / "stage"
    materializer = ArtifactStagingMaterializer.initialize(root)

    receipt = materializer.materialize(coordinator, "run-1", "src/main.py")

    assert receipt is not None
    assert receipt.status == "materialized"
    assert receipt.path.read_bytes() == b"print('star')\n"
    assert materializer.recover_pending() == ()
    with sqlite3.connect(root / ".star-promotion-journal.sqlite3") as db:
        row = db.execute(
            "SELECT state,new_sha256 FROM promotions"
        ).fetchone()
    assert row == (
        "committed",
        hashlib.sha256(b"print('star')\n").hexdigest(),
    )


def test_recovery_replays_intent_when_replace_did_not_happen(tmp_path, monkeypatch):
    coordinator = completed_run(tmp_path, b"new bytes")
    root = tmp_path / "stage"
    materializer = ArtifactStagingMaterializer.initialize(root)
    import star.agent_artifact_materializer as materializer_module

    real_replace = materializer_module.os.replace

    def fail_once(source, destination):
        if Path(destination).name == "main.py":
            raise OSError("simulated interruption before replace")
        return real_replace(source, destination)

    monkeypatch.setattr(materializer_module.os, "replace", fail_once)
    with pytest.raises(MaterializationError):
        materializer.materialize(coordinator, "run-1", "src/main.py")

    target = root / "run-1" / "src" / "main.py"
    assert not target.exists()
    monkeypatch.setattr(materializer_module.os, "replace", real_replace)

    recovered = materializer.recover_pending()
    assert [item.status for item in recovered] == ["replayed"]
    assert target.read_bytes() == b"new bytes"
    assert materializer.recover_pending() == ()


def test_recovery_recognizes_replace_before_journal_finalization(tmp_path, monkeypatch):
    coordinator = completed_run(tmp_path, b"already replaced")
    materializer = ArtifactStagingMaterializer.initialize(tmp_path / "stage")
    real_finish = materializer._journal.finish

    def fail_commit(operation_id, state, *, error_code=""):
        if state == "committed":
            raise PromotionJournalError("simulated process loss before journal finalization")
        return real_finish(operation_id, state, error_code=error_code)

    monkeypatch.setattr(materializer._journal, "finish", fail_commit)
    with pytest.raises(MaterializationError):
        materializer.materialize(coordinator, "run-1", "src/main.py")

    target = tmp_path / "stage" / "run-1" / "src" / "main.py"
    assert target.read_bytes() == b"already replaced"
    monkeypatch.setattr(materializer._journal, "finish", real_finish)

    recovered = materializer.recover_pending()
    assert [item.status for item in recovered] == ["already_applied"]
    assert materializer.recover_pending() == ()


def test_recovery_never_overwrites_external_destination_change(tmp_path, monkeypatch):
    coordinator = completed_run(tmp_path, b"new source")
    root = tmp_path / "stage"
    materializer = ArtifactStagingMaterializer.initialize(root)
    target = root / "run-1" / "src" / "main.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old source")
    expected = hashlib.sha256(b"old source").hexdigest()

    import star.agent_artifact_materializer as materializer_module

    real_replace = materializer_module.os.replace

    def collide(source, destination):
        Path(destination).write_bytes(b"external edit")
        raise OSError("simulated concurrent external modification")

    monkeypatch.setattr(materializer_module.os, "replace", collide)
    with pytest.raises(MaterializationError):
        materializer.materialize(
            coordinator, "run-1", "src/main.py",
            expected_current_sha256=expected,
        )
    monkeypatch.setattr(materializer_module.os, "replace", real_replace)

    recovered = materializer.recover_pending()
    assert [item.status for item in recovered] == ["conflict"]
    assert target.read_bytes() == b"external edit"


def test_recovery_aborts_when_prepared_temporary_file_is_missing(tmp_path, monkeypatch):
    coordinator = completed_run(tmp_path, b"new source")
    root = tmp_path / "stage"
    materializer = ArtifactStagingMaterializer.initialize(root)
    import star.agent_artifact_materializer as materializer_module

    real_replace = materializer_module.os.replace

    def fail(source, destination):
        raise OSError("simulated interruption")

    monkeypatch.setattr(materializer_module.os, "replace", fail)
    with pytest.raises(MaterializationError):
        materializer.materialize(coordinator, "run-1", "src/main.py")
    monkeypatch.setattr(materializer_module.os, "replace", real_replace)

    with sqlite3.connect(root / ".star-promotion-journal.sqlite3") as db:
        temporary_relpath = db.execute(
            "SELECT temp_relpath FROM promotions WHERE state='prepared'"
        ).fetchone()[0]
    (root / Path(*temporary_relpath.split("/"))).unlink()

    recovered = materializer.recover_pending()
    assert [item.status for item in recovered] == ["aborted"]
    assert not (root / "run-1" / "src" / "main.py").exists()


def test_journal_rejects_unknown_schema_version(tmp_path):
    root = tmp_path / "stage"
    materializer = ArtifactStagingMaterializer.initialize(root)
    database = root / ".star-promotion-journal.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(PromotionJournalError):
        type(materializer._journal)(database)
