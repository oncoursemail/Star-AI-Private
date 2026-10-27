"""Progress and background tasks.

A long job (install, update, verify, launch, backend start) runs as a `Task` on its own thread. The task owns an
ordered list of stages; the UI draws them as a track ("Checking files" done, "Starting" active ...) plus one
fraction and a detail line. Every change is published as a full task snapshot, so the UI never has to merge deltas:
it just replaces the task with the same id.
"""
from __future__ import annotations

import itertools
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from .errors import Cancelled, RcError

Listener = Callable[[dict], None]


class EventBus:
    def __init__(self):
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._listeners:
                    self._listeners.remove(fn)
        return unsubscribe

    def emit(self, event: dict) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(event)
            except Exception:  # a broken listener must not break a task
                traceback.print_exc()


@dataclass
class Stage:
    id: str
    label: str
    state: str = "pending"  # pending | active | done | failed | skipped
    detail: str = ""


@dataclass
class Task:
    id: str
    kind: str
    title: str
    stages: list[Stage]
    state: str = "queued"  # queued | running | done | failed | cancelled
    fraction: float | None = None
    detail: str = ""
    error: dict | None = None
    result: dict | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def snapshot(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "state": self.state,
            "stages": [{"id": s.id, "label": s.label, "state": s.state, "detail": s.detail} for s in self.stages],
            "fraction": self.fraction, "detail": self.detail, "error": self.error, "result": self.result,
            "startedAt": self.started, "finishedAt": self.finished,
        }


class Reporter:
    """What a job function receives: report progress, honour cancel."""

    def __init__(self, manager: "TaskManager", task: Task):
        self._m, self.task = manager, task

    @property
    def cancelled(self) -> bool:
        return self.task.cancel.is_set()

    def check(self) -> None:
        if self.task.cancel.is_set():
            raise Cancelled()

    def stage(self, stage_id: str, detail: str = "") -> None:
        """Make `stage_id` active; stages before it are marked done unless already failed/skipped."""
        self.check()
        hit = False
        for s in self.task.stages:
            if s.id == stage_id:
                s.state, s.detail, hit = "active", detail, True
            elif not hit and s.state in ("pending", "active"):
                s.state = "done"
        if not hit:
            raise KeyError(stage_id)
        self.task.fraction, self.task.detail = None, detail
        self._m._publish(self.task)

    def skip(self, stage_id: str, detail: str = "") -> None:
        for s in self.task.stages:
            if s.id == stage_id and s.state == "pending":
                s.state, s.detail = "skipped", detail
        self._m._publish(self.task)

    def progress(self, fraction: float | None, detail: str = "") -> None:
        self.check()
        self.task.fraction = None if fraction is None else min(max(float(fraction), 0.0), 1.0)
        if detail:
            self.task.detail = detail
        self._m._publish(self.task)

    def note(self, detail: str) -> None:
        self.task.detail = detail
        self._m._publish(self.task)


class SubReporter:
    """Lets a step that has its own stages (backend start) run inside another task: its stages become the detail line."""

    def __init__(self, parent: Reporter):
        self._p = parent

    @property
    def cancelled(self) -> bool:
        return self._p.cancelled

    def check(self) -> None:
        self._p.check()

    def stage(self, stage_id: str, detail: str = "") -> None:
        self._p.check()
        if detail:
            self._p.note(detail)

    def skip(self, stage_id: str, detail: str = "") -> None:
        pass

    def progress(self, fraction, detail: str = "") -> None:
        self._p.check()
        if detail:
            self._p.note(detail)

    def note(self, detail: str) -> None:
        self._p.note(detail)


Job = Callable[[Reporter], "dict | None"]


class TaskManager:
    """Runs one job per `kind` at a time (a second install while one runs is refused, not queued)."""

    def __init__(self, bus: EventBus, *, spawn: Callable[[Callable[[], None]], None] | None = None, keep: int = 20):
        self.bus = bus
        self._spawn = spawn or self._thread
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._keep = keep

    @staticmethod
    def _thread(fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, daemon=True, name="rc-task").start()

    def _publish(self, task: Task) -> None:
        self.bus.emit({"type": "task", "task": task.snapshot()})

    def start(self, kind: str, title: str, stages: list[tuple[str, str]], job: Job, *, exclusive: tuple[str, ...] = ()) -> dict:
        """Start a job. `exclusive` lists task kinds that may not be running at the same time."""
        blockers = {kind, *exclusive}
        with self._lock:
            for t in self._tasks.values():
                if t.state in ("queued", "running") and t.kind in blockers:
                    raise RcError("busy", detail=f"{t.kind} task {t.id} is {t.state}")
            task = Task(id=f"t{next(self._ids)}", kind=kind, title=title, stages=[Stage(i, l) for i, l in stages])
            self._tasks[task.id] = task
            self._order.append(task.id)
            while len(self._order) > self._keep:
                old = self._order.pop(0)
                if self._tasks[old].state not in ("queued", "running"):
                    del self._tasks[old]
                else:
                    self._order.insert(0, old)
                    break
        self._publish(task)

        def run() -> None:
            task.state = "running"
            self._publish(task)
            reporter = Reporter(self, task)
            try:
                task.result = job(reporter) or {}
                for s in task.stages:
                    if s.state in ("pending", "active"):
                        s.state = "done"
                task.state, task.fraction = "done", 1.0
            except Cancelled:
                task.state = "cancelled"
                task.error = RcError("cancelled").to_dict()
                self._mark_failed(task, "skipped")
            except RcError as err:
                task.state, task.error = "failed", err.to_dict()
                self._mark_failed(task, "failed")
            except Exception as exc:  # last resort: still a readable failure, full trace in the log
                traceback.print_exc()
                task.state = "failed"
                task.error = RcError("rc_error", detail=f"{type(exc).__name__}: {exc}",
                                     message="Something unexpected went wrong. Nothing was left half-done.").to_dict()
                self._mark_failed(task, "failed")
            task.finished = time.time()
            self._publish(task)

        self._spawn(run)
        return task.snapshot()

    @staticmethod
    def _mark_failed(task: Task, final: str) -> None:
        marked = False
        for s in task.stages:
            if s.state == "active":
                s.state, marked = final, True
        if not marked and final == "failed":
            for s in task.stages:
                if s.state == "pending":
                    s.state = "failed"
                    break

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.state in ("queued", "running"):
            task.cancel.set()
            return True
        return False

    def active(self) -> list[dict]:
        return [t.snapshot() for t in self._tasks.values() if t.state in ("queued", "running")]

    def recent(self, n: int = 10) -> list[dict]:
        return [self._tasks[i].snapshot() for i in self._order[-n:] if i in self._tasks]

    def wait(self, task_id: str, timeout: float = 10.0) -> dict:
        """Test and CLI helper: block until the task has finished."""
        end = time.time() + timeout
        while time.time() < end:
            t = self._tasks.get(task_id)
            if t and t.state in ("done", "failed", "cancelled"):
                return t.snapshot()
            time.sleep(0.01)
        raise TimeoutError(task_id)
