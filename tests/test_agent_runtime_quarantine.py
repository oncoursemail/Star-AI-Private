"""Deadline and cancellation-quarantine regressions for STAR's agent runtime."""
import asyncio

import pytest

from star.orchestration import Task, TaskPlan
from star.agent_runtime import AgentRuntimeState, run_plan


def test_timeout_callback_is_evaluated_once_and_pinned():
    async def scenario():
        calls = []
        async def worker(task, previous):
            await asyncio.sleep(.02)
            return task.goal
        def budget(task):
            calls.append(task.id)
            return .5
        plan = TaskPlan([Task("a", "research", "A"), Task("b", "review", "B")])
        result = await run_plan(plan, worker, task_timeout=budget)
        assert result.completed
        assert sorted(calls) == ["a", "b"]
    asyncio.run(scenario())


def test_cancellation_resistant_worker_is_quarantined_and_blocks_new_runs():
    async def scenario():
        release = asyncio.Event()
        started = asyncio.Event()
        async def stubborn(task, previous):
            try:
                await release.wait()
            except asyncio.CancelledError:
                started.set()
                await release.wait()
                return "late output must be discarded"
        plan = TaskPlan([Task("stubborn", "research", "Hold resource")])
        result = await run_plan(plan, stubborn, task_timeout=.1, total_timeout=.18,
                                cancel_grace=.02)
        assert started.is_set()
        assert result.for_id("stubborn").status == "stop_unconfirmed"
        assert result.runtime_state.status()["quarantined_workers"] == 1
        async def next_worker(task, previous):
            return "not admitted"
        with pytest.raises(RuntimeError, match="previous worker"):
            await run_plan(TaskPlan([Task("next", "review", "New run")]),
                           next_worker, runtime_state=result.runtime_state)
        release.set()
        status = await result.runtime_state.wait_for_quarantine(.2)
        assert status["quarantined_workers"] == 0
    asyncio.run(scenario())


def test_unconfirmed_worker_keeps_resource_lock_until_it_really_stops():
    async def scenario():
        release = asyncio.Event()
        started = []
        async def worker(task, previous):
            started.append(task.id)
            if task.id == "first":
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                    return "late"
            return task.id
        plan = TaskPlan([
            Task("first", "luau", "Edit", writes=("game/shared",)),
            Task("conflict", "review", "Review", reads=("game/shared/file",)),
            Task("independent", "research", "Research elsewhere", writes=("docs",)),
        ], max_parallel=2)
        run = asyncio.create_task(
            run_plan(plan, worker, allow_writes=True, task_timeout=.1,
                     total_timeout=.5, cancel_grace=.02)
        )
        await asyncio.sleep(.16)
        assert "independent" in started
        assert "conflict" not in started
        release.set()
        result = await run
        assert result.for_id("first").status in {"incomplete", "timed_out"}
        assert result.for_id("conflict").status == "completed"
        assert result.for_id("independent").status == "completed"
    asyncio.run(scenario())


def test_caller_cancellation_retains_unconfirmed_worker():
    async def scenario():
        release = asyncio.Event()
        started = asyncio.Event()
        runtime = AgentRuntimeState()
        async def stubborn(task, previous):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        run = asyncio.create_task(
            run_plan(TaskPlan([Task("stubborn", "research", "Caller cancellation")]),
                     stubborn, total_timeout=2, cancel_grace=.01,
                     runtime_state=runtime)
        )
        await started.wait()
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        assert runtime.status()["quarantined_workers"] == 1
        release.set()
        status = await runtime.wait_for_quarantine(.2)
        assert status["quarantined_workers"] == 0
    asyncio.run(scenario())
