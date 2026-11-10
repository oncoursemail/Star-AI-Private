"""Bounded async agent execution with explicit cancellation quarantine.

Workers are trusted application-defined async adapters, never model-generated Python.
A cancellation request does not prove that an external thread, process, model server,
GPU operation or device worker has stopped. Unconfirmed async tasks remain retained
by AgentRuntimeState until they really complete.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
from time import monotonic
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping

from .orchestration import Task, TaskPlan
from .mission_checkpoint import MissionCheckpoint


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    role: str
    status: str
    answer: str = ""
    evidence: tuple[str, ...] = ()
    elapsed_ms: int = 0
    error: str = ""


@dataclass(frozen=True)
class _Quarantined:
    task_id: str
    role: str
    reason: str


class AgentRuntimeState:
    """Strong-reference registry for workers whose stop is not confirmed."""

    def __init__(self) -> None:
        self._quarantined: dict[asyncio.Task, _Quarantined] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def _active(self) -> tuple[asyncio.Task, ...]:
        return tuple(task for task in self._quarantined if not task.done())

    def reap(self) -> int:
        active = self._active()
        if active and self._loop is not asyncio.get_running_loop():
            raise RuntimeError("Quarantined workers belong to another event loop")
        for task in tuple(self._quarantined):
            if task.done():
                try:
                    task.exception()
                except BaseException:
                    pass
                del self._quarantined[task]
        if not self._quarantined:
            self._loop = None
        return len(self._active())

    def adopt(self, task: asyncio.Task, contract: Task, *, reason: str) -> None:
        if not isinstance(task, asyncio.Task) or not isinstance(contract, Task):
            raise TypeError("Expected an asyncio Task and its validated task contract")
        if reason not in {"task_timeout", "global_timeout", "caller_cancel"}:
            raise ValueError("Invalid quarantine reason")
        if task.done():
            return
        loop = asyncio.get_running_loop()
        if self._active() and self._loop is not loop:
            raise RuntimeError("Quarantined workers belong to another event loop")
        self._loop = loop
        self._quarantined[task] = _Quarantined(contract.id, contract.role, reason)

    def status(self) -> dict[str, object]:
        active = self._active()
        return {
            "quarantined_workers": len(active),
            "completed_waiting_reap": len(self._quarantined) - len(active),
            "task_ids": tuple(sorted(self._quarantined[t].task_id for t in active)),
        }

    async def wait_for_quarantine(self, timeout: float = 0.0) -> dict[str, object]:
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 <= timeout <= 3600):
            raise ValueError("Quarantine wait must be between 0 and 3600 seconds")
        active = self._active()
        if active:
            if asyncio.get_running_loop() is not self._loop:
                raise RuntimeError("Quarantined workers belong to another event loop")
            await asyncio.wait(active, timeout=float(timeout))
        self.reap()
        return self.status()


@dataclass(frozen=True)
class TeamResult:
    results: tuple[TaskResult, ...]
    elapsed_ms: int
    peak_concurrency: int
    runtime_state: AgentRuntimeState = field(
        default_factory=AgentRuntimeState, repr=False, compare=False
    )

    @property
    def completed(self) -> bool:
        return all(r.status == "completed" for r in self.results)

    def for_id(self, task_id: str) -> TaskResult:
        return next(r for r in self.results if r.task_id == task_id)

    def summary(self, max_chars: int = 18000) -> str:
        lines = []
        for item in self.results:
            if item.status == "completed":
                body = item.answer[:4000]
            elif item.status == "incomplete":
                body = "INCOMPLETE (deadline exceeded): " + item.answer[:4000]
            elif item.status == "stop_unconfirmed":
                body = "STOP UNCONFIRMED; worker may still be running: " + item.answer[:4000]
            else:
                body = item.status + ": " + item.error[:250]
            lines.append(f"[TASK {item.task_id} / {item.role} / {item.status}]\n{body}")
            if item.evidence:
                lines.append("Evidence references: " + ", ".join(item.evidence[:8]))
        return "\n\n".join(lines)[:max_chars]


@dataclass
class _RunningJob:
    contract: Task
    future: asyncio.Task
    started_at: float
    deadline: float
    cancel_reason: str | None = None
    cancel_requested_at: float | None = None
    quarantine_registered: bool = False


Worker = Callable[[Task, Mapping[str, TaskResult]], Awaitable[dict | str]]
Observer = Callable[[dict], None]


async def run_plan(
    plan: TaskPlan,
    worker: Worker,
    *,
    task_timeout: float | Callable[[Task], float] = 45.0,
    total_timeout: float = 180.0,
    allow_writes: bool = False,
    on_event: Observer | None = None,
    partial_answers: Mapping[str, str] | None = None,
    checkpoint: MissionCheckpoint | None = None,
    cancel_grace: float = 0.15,
    runtime_state: AgentRuntimeState | None = None,
) -> TeamResult:
    """Run a bounded task DAG without treating cancellation as worker termination.

    The runtime uses monotonic deadlines and asyncio.wait(), requests cancellation,
    and waits only for cancel_grace. A still-running task keeps its current-plan
    locks and is retained in runtime_state. New plans using that state are refused
    until the quarantine clears.

    Adapters that wrap threads, subprocesses, model servers, GPU work or devices
    must wait for the external operation's real stop acknowledgement before their
    coroutine completes. asyncio cannot kill those external workers.
    """
    seconds = {
        t.id: task_timeout(t) if callable(task_timeout) else task_timeout
        for t in plan.tasks.values()
    }
    if (any(type(v) not in (int, float) or not math.isfinite(v) or not 0.1 <= v <= 1800
            for v in seconds.values()) or type(total_timeout) not in (int, float)
            or not math.isfinite(total_timeout) or not 0.1 <= total_timeout <= 3600):
        raise ValueError("Agent time budget is outside safe bounds")
    if (type(cancel_grace) not in (int, float) or not math.isfinite(cancel_grace)
            or not 0 <= cancel_grace <= 5):
        raise ValueError("Cancellation grace must be between 0 and 5 seconds")
    if not callable(worker):
        raise TypeError("A trusted async worker callable is required")
    if not allow_writes and any(t.writes for t in plan.tasks.values()):
        raise PermissionError("Parallel agent writes require explicit authorization")
    if len(plan.tasks) > 32:
        raise ValueError("Live team runs are limited to 32 tasks")
    if checkpoint is not None and not isinstance(checkpoint, MissionCheckpoint):
        raise TypeError("Expected a trusted MissionCheckpoint instance")
    if checkpoint is not None and (allow_writes or any(t.writes for t in plan.tasks.values())):
        raise PermissionError("Mission replay is only available to read-only tasks")

    runtime_state = runtime_state or AgentRuntimeState()
    if not isinstance(runtime_state, AgentRuntimeState):
        raise TypeError("Expected a trusted AgentRuntimeState")
    runtime_state.reap()
    if runtime_state.status()["quarantined_workers"]:
        raise RuntimeError("A previous worker has not confirmed stop; wait for quarantine to clear")

    restored = checkpoint.load(plan) if checkpoint is not None else {}
    started = monotonic()
    deadline = started + total_timeout
    running: dict[str, _RunningJob] = {}
    results: dict[str, TaskResult] = {
        task_id: TaskResult(task_id, plan.tasks[task_id].role, "completed",
                            answer=data["answer"], evidence=data["evidence"],
                            elapsed_ms=data["elapsed_ms"])
        for task_id, data in restored.items()
    }
    peak = 0

    def partial_for(task_id: str) -> str:
        value = (partial_answers or {}).get(task_id, "")
        return value[:12000].strip() if isinstance(value, str) else ""

    def observe(event: dict) -> None:
        if on_event:
            try:
                on_event(dict(event))
            except Exception:
                pass

    for task_id, entry in results.items():
        observe({"event": "agent_resumed", "task": task_id, "role": entry.role,
                 "status": "completed", "from_checkpoint": True})

    async def invoke(task: Task, snapshot: Mapping[str, TaskResult]):
        raw = await worker(task, snapshot)
        return raw, monotonic()

    def cancellation_result(job: _RunningJob, *, unconfirmed: bool = False) -> TaskResult:
        partial = partial_for(job.contract.id)
        if unconfirmed:
            return TaskResult(
                job.contract.id, job.contract.role, "stop_unconfirmed",
                answer=partial, elapsed_ms=int((monotonic() - job.started_at) * 1000),
                error="Cancellation requested; worker termination not confirmed",
            )
        if job.cancel_reason == "task_timeout":
            status, error = ("incomplete" if partial else "timed_out"), "Stage time budget exceeded"
        elif job.cancel_reason == "global_timeout":
            status, error = ("incomplete" if partial else "cancelled"), "Global team time budget exceeded"
        else:
            status, error = ("incomplete" if partial else "cancelled"), "Run cancelled by caller"
        return TaskResult(
            job.contract.id, job.contract.role, status, answer=partial,
            elapsed_ms=int((monotonic() - job.started_at) * 1000), error=error,
        )

    def normalize_result(job: _RunningJob, raw: object, finished_at: float) -> TaskResult:
        if finished_at > job.deadline:
            timed = _RunningJob(
                job.contract, job.future, job.started_at, job.deadline,
                cancel_reason="task_timeout", cancel_requested_at=job.deadline,
            )
            return cancellation_result(timed)
        if isinstance(raw, str):
            answer, evidence = raw, ()
        elif isinstance(raw, dict):
            answer, evidence = raw.get("answer", ""), raw.get("evidence", ())
        else:
            raise TypeError("Worker must return text or a structured answer")
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 12000:
            raise ValueError("Agent result must be nonempty text (max 12,000 chars)")
        if not isinstance(evidence, (list, tuple)) or len(evidence) > 20 or any(
            not isinstance(v, str) or len(v) > 500 for v in evidence
        ):
            raise ValueError("Agent evidence list exceeds budget")
        return TaskResult(
            job.contract.id, job.contract.role, "completed", answer, tuple(evidence),
            int(max(0.0, finished_at - job.started_at) * 1000),
        )

    def result_for(job: _RunningJob) -> TaskResult:
        if job.cancel_reason:
            return cancellation_result(job)
        try:
            raw, finished_at = job.future.result()
            return normalize_result(job, raw, finished_at)
        except asyncio.CancelledError:
            return TaskResult(job.contract.id, job.contract.role, "cancelled",
                              elapsed_ms=int((monotonic() - job.started_at) * 1000),
                              error="Worker cancelled")
        except TimeoutError:
            return TaskResult(job.contract.id, job.contract.role, "timed_out",
                              elapsed_ms=int((monotonic() - job.started_at) * 1000),
                              error="Worker reported a timeout")
        except Exception as exc:
            return TaskResult(job.contract.id, job.contract.role, "failed",
                              elapsed_ms=int((monotonic() - job.started_at) * 1000),
                              error=type(exc).__name__)

    def store_result(job: _RunningJob, entry: TaskResult) -> None:
        if checkpoint is not None and entry.status == "completed":
            try:
                checkpoint.save(job.contract, answer=entry.answer,
                                 evidence=entry.evidence, elapsed_ms=entry.elapsed_ms)
            except Exception as exc:
                entry = TaskResult(job.contract.id, job.contract.role, "failed",
                                   error=type(exc).__name__)
        results[job.contract.id] = entry
        observe({"event": "agent_finished", "task": job.contract.id,
                 "role": job.contract.role, "status": entry.status,
                 "elapsed_ms": entry.elapsed_ms})

    def block_dependents() -> bool:
        changed = False
        for task in plan.tasks.values():
            if task.id in results or task.id in running:
                continue
            if any(dep in results and results[dep].status != "completed"
                   for dep in task.dependencies):
                results[task.id] = TaskResult(
                    task.id, task.role, "blocked",
                    error="An upstream dependency did not complete",
                )
                observe({"event": "agent_blocked", "task": task.id, "role": task.role})
                changed = True
        return changed

    def request_cancel(job: _RunningJob, reason: str, now: float) -> None:
        if job.cancel_reason is None and not job.future.done():
            job.cancel_reason = reason
            job.cancel_requested_at = now
            job.future.cancel()

    def register_unconfirmed(job: _RunningJob) -> None:
        if job.future.done() or job.quarantine_registered:
            return
        runtime_state.adopt(job.future, job.contract,
                            reason=job.cancel_reason or "global_timeout")
        job.quarantine_registered = True
        observe({"event": "agent_stop_unconfirmed", "task": job.contract.id,
                 "role": job.contract.role, "reason": job.cancel_reason})

    def settle_done() -> None:
        for task_id, job in tuple(running.items()):
            if job.future.done():
                store_result(job, result_for(job))
                del running[task_id]
        runtime_state.reap()

    try:
        while len(results) < len(plan.tasks):
            settle_done()
            now = monotonic()
            if now >= deadline:
                break

            for job in running.values():
                if job.cancel_reason is None and now >= job.deadline:
                    request_cancel(job, "task_timeout", now)
            for job in running.values():
                if (job.cancel_reason is not None and not job.future.done()
                        and not job.quarantine_registered
                        and job.cancel_requested_at is not None
                        and now - job.cancel_requested_at >= cancel_grace):
                    register_unconfirmed(job)

            while block_dependents():
                pass
            successful = {tid for tid, entry in results.items()
                          if entry.status == "completed"}
            ready = plan.ready(successful, set(running), finished=set(results))
            for item in ready:
                if item.id in results or item.id in running:
                    continue
                if any(dep in results and results[dep].status != "completed"
                       for dep in item.dependencies):
                    continue
                launch_at = monotonic()
                if launch_at >= deadline:
                    break
                future = asyncio.create_task(
                    invoke(item, MappingProxyType(dict(results))),
                    name=f"star-{item.role}-{item.id}",
                )
                running[item.id] = _RunningJob(
                    item, future, launch_at, launch_at + seconds[item.id]
                )
                peak = max(peak, len(running))
                observe({"event": "agent_started", "task": item.id,
                         "role": item.role, "active": len(running)})

            if not running:
                if len(results) < len(plan.tasks):
                    for item in plan.tasks.values():
                        if item.id not in results:
                            results[item.id] = TaskResult(
                                item.id, item.role, "blocked",
                                error="No runnable dependency-safe tasks remain",
                            )
                break

            settle_done()
            if len(results) >= len(plan.tasks):
                break
            wake_at = deadline
            for job in running.values():
                if job.cancel_reason is None:
                    wake_at = min(wake_at, job.deadline)
                elif not job.quarantine_registered and job.cancel_requested_at is not None:
                    wake_at = min(wake_at, job.cancel_requested_at + cancel_grace)
            wait_seconds = max(0.0, wake_at - monotonic())
            if wait_seconds == 0:
                continue
            await asyncio.wait(
                {job.future for job in running.values()},
                timeout=wait_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )

        if running:
            now = monotonic()
            for job in running.values():
                request_cancel(job, "global_timeout", now)
            pending = {job.future for job in running.values() if not job.future.done()}
            if pending and cancel_grace:
                await asyncio.wait(pending, timeout=cancel_grace)
            settle_done()
            for task_id, job in tuple(running.items()):
                register_unconfirmed(job)
                entry = cancellation_result(job, unconfirmed=True)
                results[task_id] = entry
                observe({"event": "agent_finished", "task": task_id,
                         "role": job.contract.role, "status": entry.status,
                         "elapsed_ms": entry.elapsed_ms})
                del running[task_id]

    except asyncio.CancelledError:
        now = monotonic()
        for job in running.values():
            request_cancel(job, "caller_cancel", now)
        pending = {job.future for job in running.values() if not job.future.done()}
        if pending and cancel_grace:
            cleanup = asyncio.create_task(asyncio.wait(pending, timeout=cancel_grace))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                pass
        for job in running.values():
            if job.future.done():
                try:
                    job.future.exception()
                except BaseException:
                    pass
            else:
                register_unconfirmed(job)
        raise

    for item in plan.tasks.values():
        if item.id not in results:
            results[item.id] = TaskResult(
                item.id, item.role, "blocked", error="Uncompleted dependency"
            )
    runtime_state.reap()
    quarantined = runtime_state.status()["quarantined_workers"]
    if quarantined:
        observe({"event": "agent_quarantine_active", "count": quarantined})
    return TeamResult(
        tuple(results[t] for t in plan.tasks),
        int((monotonic() - started) * 1000),
        peak,
        runtime_state,
    )


__all__ = ["TaskResult", "TeamResult", "AgentRuntimeState", "run_plan"]
