"""Contract tests for opt-in, read-only, revision-bound STAR mission resume."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sqlite3

import pytest

from star import agent_runtime
from star.agent_runtime import run_plan
from star.mission_checkpoint import MissionCheckpoint
from star.orchestration import Task, TaskPlan


def checkpoint(path: Path, *, project: str = "roblox", mission_id: str = "demo",
               worker_revision: str = "worker-sha1", context_revision: str = "docs-sha1"):
    return MissionCheckpoint(path, project=project, mission_id=mission_id,
                             worker_revision=worker_revision, context_revision=context_revision)


def test_completed_steps_restore_without_reexecuting_workers(tmp_path):
    plan = TaskPlan([
        Task("gather", "research", "Find facts"),
        Task("review", "review", "Inspect citations", dependencies=("gather",)),
        Task("final", "integration", "Synthesize", dependencies=("review",)),
    ])
    calls = []
    async def worker(task, prior):
        calls.append(task.id)
        assert all(entry.status == "completed" for entry in prior.values())
        return {"answer": task.goal, "evidence": ["fixture:verified"]}

    with checkpoint(tmp_path / "missions.sqlite3") as mission:
        first = asyncio.run(run_plan(plan, worker, checkpoint=mission))
        assert first.completed
        assert calls == ["gather", "review", "final"]
        events = []
        second = asyncio.run(run_plan(plan, worker, checkpoint=mission,
                                      on_event=events.append))
        assert second.completed
        assert second.peak_concurrency == 0
        assert len(calls) == 3
        assert [event["event"] for event in events] == ["agent_resumed"] * 3
        assert second.for_id("gather").evidence == ("fixture:verified",)

    with checkpoint(tmp_path / "missions.sqlite3") as reopened:
        third = asyncio.run(run_plan(plan, worker, checkpoint=reopened))
        assert third.completed and third.peak_concurrency == 0
        assert len(calls) == 3


def test_incomplete_work_is_rerun_but_finished_dependency_is_reused(tmp_path, monkeypatch):
    plan = TaskPlan([
        Task("quick", "research", "Read document"),
        Task("slow", "review", "Audit result", dependencies=("quick",)),
        Task("final", "integration", "Synthesize", dependencies=("slow",)),
    ])
    # Freeze run_plan's clock so a loaded runner cannot spend the team budget
    # before "slow" starts; the budget then expires in asyncio.wait while
    # "slow" waits on an event that is never set.
    monkeypatch.setattr(agent_runtime, "monotonic", lambda: 0.0)
    calls = []
    async def slow_worker(task, prior):
        calls.append(task.id)
        if task.id == "slow":
            await asyncio.Event().wait()
        return task.goal

    with checkpoint(tmp_path / "c.sqlite3") as mission:
        result = asyncio.run(run_plan(plan, slow_worker, checkpoint=mission,
                                      task_timeout=0.6, total_timeout=0.12))
        assert result.for_id("quick").status == "completed"
        assert result.for_id("slow").status == "cancelled"
        assert result.for_id("final").status == "blocked"
    resumed_calls = []
    async def finish(task, prior):
        resumed_calls.append(task.id)
        if task.id == "slow":
            assert prior["quick"].status == "completed"
        return task.goal
    with checkpoint(tmp_path / "c.sqlite3") as mission:
        result = asyncio.run(run_plan(plan, finish, checkpoint=mission))
        assert result.completed
        assert resumed_calls == ["slow", "final"]
        assert calls.count("quick") == 1


@pytest.mark.parametrize("change", ["worker", "context", "plan", "parallel"])
def test_fingerprint_or_revision_mismatch_refuses_reuse(tmp_path, change):
    path = tmp_path / "missions.sqlite3"
    original = TaskPlan([Task("t", "research", "Original task")])
    async def worker(task, previous):
        return "Old output"
    with checkpoint(path) as mission:
        assert asyncio.run(run_plan(original, worker, checkpoint=mission)).completed

    params = {}
    modified = original
    if change == "worker":
        params["worker_revision"] = "changed-worker"
    elif change == "context":
        params["context_revision"] = "changed-sources"
    elif change == "plan":
        modified = TaskPlan([Task("t", "research", "Different task")])
    else:
        modified = TaskPlan([Task("t", "research", "Original task")], max_parallel=3)

    with checkpoint(path, **params) as mission:
        with pytest.raises(ValueError, match="changed"):
            asyncio.run(run_plan(modified, worker, checkpoint=mission))


def test_project_scope_and_mission_id_isolate_results(tmp_path):
    path = tmp_path / "missions.sqlite3"
    plan = TaskPlan([Task("t", "research", "Read project")])
    async def answer(task, previous):
        return "project A source"
    async def other(task, previous):
        return "project B source"
    with checkpoint(path, project="project-A") as mission:
        first = asyncio.run(run_plan(plan, answer, checkpoint=mission))
    with checkpoint(path, project="project-B") as mission:
        second = asyncio.run(run_plan(plan, other, checkpoint=mission))
    with checkpoint(path, project="project-A") as mission:
        third = asyncio.run(run_plan(plan, other, checkpoint=mission))
    assert first.for_id("t").answer == third.for_id("t").answer == "project A source"
    assert second.for_id("t").answer == "project B source"


def test_failed_or_timed_out_results_do_not_become_successful_cache(tmp_path):
    plan = TaskPlan([Task("t", "research", "Try again")])
    calls = []
    async def broken(task, previous):
        calls.append(1)
        raise RuntimeError("private token value")
    async def fixed(task, previous):
        calls.append(1)
        return "fixed output"
    with checkpoint(tmp_path / "c.sqlite3") as mission:
        first = asyncio.run(run_plan(plan, broken, checkpoint=mission))
        assert first.for_id("t").status == "failed"
        assert "private token" not in first.summary()
        second = asyncio.run(run_plan(plan, fixed, checkpoint=mission))
        assert second.completed
        assert len(calls) == 2


def test_write_capability_never_receives_automatic_replay(tmp_path):
    write_plan = TaskPlan([Task("edit", "luau", "Edit place", writes=("src",))])
    read_plan = TaskPlan([Task("read", "research", "Inspect place")])
    async def worker(task, previous):
        return "OK"
    with checkpoint(tmp_path / "c.sqlite3") as mission:
        with pytest.raises(PermissionError, match="read-only"):
            asyncio.run(run_plan(write_plan, worker, allow_writes=True, checkpoint=mission))
        with pytest.raises(PermissionError, match="read-only"):
            asyncio.run(run_plan(read_plan, worker, allow_writes=True, checkpoint=mission))
    assert asyncio.run(run_plan(read_plan, worker)).completed


def test_corrupt_checkpoint_refused_without_worker_execution(tmp_path):
    path = tmp_path / "missions.sqlite3"
    plan = TaskPlan([Task("t", "research", "Collect evidence")])
    calls = []
    async def worker(task, previous):
        calls.append(task.id)
        return "old"
    with checkpoint(path) as mission:
        assert asyncio.run(run_plan(plan, worker, checkpoint=mission)).completed
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE completed SET payload='{}' WHERE project='roblox'")
    with checkpoint(path) as mission:
        with pytest.raises(ValueError, match="damaged"):
            asyncio.run(run_plan(plan, worker, checkpoint=mission))
    assert calls == ["t"]


def test_invalid_identity_and_symlinked_database_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        checkpoint(tmp_path / "c.sqlite3", mission_id="../escape")
    with pytest.raises(ValueError):
        checkpoint(tmp_path / "c.sqlite3", worker_revision="")
    target = tmp_path / "real.sqlite3"
    target.touch()
    symlink = tmp_path / "link.sqlite3"
    try:
        symlink.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks require special privileges on this platform")
    with pytest.raises(PermissionError):
        checkpoint(symlink)


def test_read_only_snapshot_storage_is_private_on_posix(tmp_path):
    path = tmp_path / "private.sqlite3"
    with checkpoint(path):
        pass
    if os.name == "posix":
        assert path.stat().st_mode & 0o077 == 0


def test_checkpoint_saving_requires_a_loaded_plan(tmp_path):
    task = Task("t", "research", "Read")
    with checkpoint(tmp_path / "c.sqlite3") as mission:
        with pytest.raises(PermissionError):
            mission.save(task, answer="no", evidence=(), elapsed_ms=2)
