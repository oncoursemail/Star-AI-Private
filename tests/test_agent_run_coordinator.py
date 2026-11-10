"""Regression tests for durable, lease-fenced agent run coordination."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading

import pytest

from star.agent_run_coordinator import (
    AgentRunCoordinator,
    CoordinatorError,
    PlanMismatchError,
    RunNotReadyError,
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


def private_database(tmp_path: Path) -> Path:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    return directory / "agent-runs.sqlite3"


def make_plan(*tasks, max_parallel=2):
    return TaskPlan(list(tasks), max_parallel=max_parallel)


def make_coordinator(tmp_path, *, clock=None, lease_seconds=1, max_attempts=3):
    return AgentRunCoordinator(
        private_database(tmp_path),
        clock_ns=clock or __import__("time").time_ns,
        lease_seconds=lease_seconds,
        max_attempts=max_attempts,
    )


def test_register_is_idempotent_but_plan_is_immutable(tmp_path):
    plan = make_plan(Task("a", "research", "Read docs"))
    coordinator = make_coordinator(tmp_path)
    assert coordinator.register_run("run-1", plan) is True
    assert coordinator.register_run("run-1", plan) is False

    changed = make_plan(Task("a", "research", "Read different docs"))
    with pytest.raises(PlanMismatchError):
        coordinator.register_run("run-1", changed)

    other_policy = AgentRunCoordinator(private_database(tmp_path), lease_seconds=2)
    with pytest.raises(PlanMismatchError):
        other_policy.register_run("run-1", plan)


def test_claim_respects_dependencies_and_exposes_only_direct_results(tmp_path):
    plan = make_plan(
        Task("a", "research", "Research the API"),
        Task("b", "review", "Review the API findings", dependencies=("a",)),
        Task("c", "research", "Research unrelated topic"),
    )
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("run-2", plan)

    first = coordinator.claim_next("run-2", "worker-a")
    second = coordinator.claim_next("run-2", "worker-b")
    assert first.task.id == "a"
    assert second.task.id == "c"
    assert coordinator.claim_next("run-2", "worker-c") is None

    assert coordinator.complete(
        first, answer="API findings", evidence=("docs/api.md",), elapsed_ms=20
    ) == "completed"
    third = coordinator.claim_next("run-2", "worker-c")
    assert third.task.id == "b"
    assert [item.task_id for item in third.dependency_results] == ["a"]
    assert third.dependency_results[0].answer == "API findings"
    assert coordinator.complete(second, answer="Unrelated findings") == "completed"
    assert coordinator.complete(third, answer="Review complete") == "completed"
    assert coordinator.finish_run("run-2", plan) == "completed"


def test_two_coordinator_instances_claim_distinct_tasks_atomically(tmp_path):
    plan = make_plan(
        Task("a", "research", "Task A"),
        Task("b", "research", "Task B"),
    )
    path = private_database(tmp_path)
    first = AgentRunCoordinator(path)
    second = AgentRunCoordinator(path)
    first.register_run("run-3", plan)
    assert second.register_run("run-3", plan) is False

    barrier = threading.Barrier(2)

    def claim(coordinator, worker):
        barrier.wait(timeout=2)
        return coordinator.claim_next("run-3", worker)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(claim, first, "worker-a")
        b = pool.submit(claim, second, "worker-b")
        leases = [a.result(timeout=5), b.result(timeout=5)]

    assert all(lease is not None for lease in leases)
    assert len({lease.task.id for lease in leases}) == 2
    assert len({lease.fencing_token for lease in leases}) == 2


def test_expired_lease_is_reissued_with_higher_fence_and_stale_result_rejected(tmp_path):
    clock = FakeClock()
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path, clock=clock)
    coordinator.register_run("run-4", plan)

    old = coordinator.claim_next("run-4", "worker-old")
    clock.advance(2)
    new = coordinator.claim_next("run-4", "worker-new")

    assert new.task.id == old.task.id
    assert new.attempt == old.attempt + 1
    assert new.fencing_token > old.fencing_token
    with pytest.raises(StaleLeaseError):
        coordinator.complete(old, answer="stale result")
    assert coordinator.complete(new, answer="fresh result") == "completed"


def test_renewal_keeps_fence_and_extends_expiry(tmp_path):
    clock = FakeClock()
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path, clock=clock)
    coordinator.register_run("run-5", plan)
    lease = coordinator.claim_next("run-5", "worker-a")
    clock.advance(0.5)

    renewed = coordinator.renew(lease)
    assert renewed.fencing_token == lease.fencing_token
    assert renewed.lease_id == lease.lease_id
    assert renewed.lease_expires_ns > lease.lease_expires_ns
    clock.advance(0.75)
    assert coordinator.complete(renewed, answer="still current") == "completed"


def test_retryable_failure_releases_task_for_new_fenced_attempt(tmp_path):
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path, max_attempts=2)
    coordinator.register_run("run-6", plan)

    first = coordinator.claim_next("run-6", "worker-a")
    assert coordinator.fail(first, error_code="provider_busy", retryable=True) == "pending"
    second = coordinator.claim_next("run-6", "worker-b")
    assert second.attempt == 2
    assert second.fencing_token > first.fencing_token
    assert coordinator.fail(second, error_code="provider_busy", retryable=True) == "failed"
    assert coordinator.finish_run("run-6", plan) == "finished_with_failures"


def test_expired_attempt_exhaustion_blocks_dependents(tmp_path):
    clock = FakeClock()
    plan = make_plan(
        Task("a", "research", "Upstream"),
        Task("b", "review", "Downstream", dependencies=("a",)),
    )
    coordinator = make_coordinator(tmp_path, clock=clock, max_attempts=1)
    coordinator.register_run("run-7", plan)
    coordinator.claim_next("run-7", "worker-a")
    clock.advance(2)

    assert coordinator.reap_expired("run-7", plan) == 1
    status = coordinator.status("run-7")
    assert status["counts"]["failed"] == 1
    assert status["counts"]["blocked"] == 1
    assert coordinator.claim_next("run-7", "worker-b") is None
    assert coordinator.finish_run("run-7", plan) == "finished_with_failures"


def test_identical_completion_retry_is_idempotent_but_changed_payload_is_rejected(tmp_path):
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("run-8", plan)
    lease = coordinator.claim_next("run-8", "worker-a")

    assert coordinator.complete(lease, answer="result", evidence=("source",), elapsed_ms=4) == "completed"
    assert coordinator.complete(lease, answer="result", evidence=("source",), elapsed_ms=4) == "already_completed"
    with pytest.raises(StaleLeaseError):
        coordinator.complete(lease, answer="different result", evidence=("source",), elapsed_ms=4)


def test_abort_invalidates_active_leases_but_does_not_claim_to_kill_workers(tmp_path):
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("run-9", plan)
    lease = coordinator.claim_next("run-9", "worker-a")

    assert coordinator.abort_run("run-9") is True
    assert coordinator.abort_run("run-9") is False
    with pytest.raises(StaleLeaseError):
        coordinator.complete(lease, answer="late result")
    assert coordinator.claim_next("run-9", "worker-b") is None
    assert coordinator.status("run-9")["state"] == "aborted"


def test_write_capable_tasks_are_rejected_until_a_resource_side_fence_exists(tmp_path):
    plan = make_plan(Task("a", "luau", "Edit a script", writes=("game/scripts",)))
    coordinator = make_coordinator(tmp_path)
    with pytest.raises(PermissionError, match="resource-side fencing gateway"):
        coordinator.register_run("run-10", plan)


def test_status_does_not_expose_task_answers(tmp_path):
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("run-11", plan)
    lease = coordinator.claim_next("run-11", "worker-a")
    coordinator.complete(lease, answer="private result payload")

    rendered = repr(coordinator.status("run-11"))
    assert "private result payload" not in rendered
    assert coordinator.status("run-11")["counts"]["completed"] == 1


def test_run_cannot_finish_while_a_lease_is_active(tmp_path):
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("run-12", plan)
    coordinator.claim_next("run-12", "worker-a")
    with pytest.raises(RunNotReadyError):
        coordinator.finish_run("run-12", plan)


def test_result_and_identifier_budgets_are_enforced(tmp_path):
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("run-13", plan)
    lease = coordinator.claim_next("run-13", "worker-a")

    with pytest.raises(ValueError):
        coordinator.complete(lease, answer="")
    with pytest.raises(ValueError):
        coordinator.claim_next("run-13", "../bad-worker")
    assert coordinator.status("run-13")["counts"]["leased"] == 1


def test_private_directory_is_required(tmp_path):
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    public.chmod(0o755)
    with pytest.raises(PermissionError, match="mode 0700"):
        AgentRunCoordinator(public / "runs.sqlite3")


def test_invalid_clock_is_rejected_before_claiming(tmp_path):
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = AgentRunCoordinator(private_database(tmp_path), clock_ns=lambda: 1.5)
    with pytest.raises(RuntimeError, match="invalid timestamp"):
        coordinator.register_run("run-14", plan)


def test_restart_re_registers_exact_plan_and_reuses_only_durable_completed_dependencies(tmp_path):
    clock = FakeClock()
    plan = make_plan(
        Task("a", "research", "Research the API"),
        Task("b", "review", "Review the API", dependencies=("a",)),
    )
    path = private_database(tmp_path)
    first = AgentRunCoordinator(path, clock_ns=clock, lease_seconds=1)
    first.register_run("run-15", plan)
    lease_a = first.claim_next("run-15", "worker-a")
    first.complete(lease_a, answer="durable API result", evidence=("docs/api.md",))

    restarted = AgentRunCoordinator(path, clock_ns=clock, lease_seconds=1)
    assert restarted.register_run("run-15", plan) is False
    lease_b = restarted.claim_next("run-15", "worker-b")
    assert lease_b.task.id == "b"
    assert lease_b.dependency_results[0].answer == "durable API result"


def test_restart_reclaims_expired_lease_with_new_fence(tmp_path):
    clock = FakeClock()
    plan = make_plan(Task("a", "research", "Research"))
    path = private_database(tmp_path)
    first = AgentRunCoordinator(path, clock_ns=clock, lease_seconds=1)
    first.register_run("run-16", plan)
    old = first.claim_next("run-16", "worker-old")

    clock.advance(2)
    restarted = AgentRunCoordinator(path, clock_ns=clock, lease_seconds=1)
    restarted.register_run("run-16", plan)
    new = restarted.claim_next("run-16", "worker-new")

    assert new.fencing_token > old.fencing_token
    with pytest.raises(StaleLeaseError):
        first.complete(old, answer="late old process result")
    assert restarted.complete(new, answer="recovered result") == "completed"


def test_expired_lease_cannot_be_resurrected_by_renewal(tmp_path):
    clock = FakeClock()
    plan = make_plan(Task("a", "research", "Research"))
    coordinator = make_coordinator(tmp_path, clock=clock)
    coordinator.register_run("run-17", plan)
    lease = coordinator.claim_next("run-17", "worker-a")
    clock.advance(2)

    with pytest.raises(StaleLeaseError, match="expired"):
        coordinator.renew(lease)


def test_corrupted_dependency_result_digest_fails_closed(tmp_path):
    import sqlite3

    plan = make_plan(
        Task("a", "research", "Upstream"),
        Task("b", "review", "Downstream", dependencies=("a",)),
    )
    path = private_database(tmp_path)
    coordinator = AgentRunCoordinator(path)
    coordinator.register_run("run-18", plan)
    lease = coordinator.claim_next("run-18", "worker-a")
    coordinator.complete(lease, answer="verified result")

    db = sqlite3.connect(path)
    try:
        db.execute(
            "UPDATE tasks SET result_json=? WHERE run_id=? AND task_id=?",
            ('{"answer":"tampered"}', "run-18", "a"),
        )
        db.commit()
    finally:
        db.close()

    with pytest.raises(CoordinatorError, match="integrity"):
        coordinator.claim_next("run-18", "worker-b")


def test_registered_plan_is_snapshotted_and_later_caller_mutation_is_rejected(tmp_path):
    plan = make_plan(Task("a", "research", "Original goal"))
    coordinator = make_coordinator(tmp_path)
    coordinator.register_run("run-19", plan)

    plan.tasks["a"] = Task("a", "research", "Mutated goal")
    lease = coordinator.claim_next("run-19", "worker-a")
    assert lease.task.goal == "Original goal"
    with pytest.raises(PlanMismatchError):
        coordinator.finish_run("run-19", plan)
    assert coordinator.complete(lease, answer="original plan result") == "completed"


def test_claim_samples_lease_clock_after_waiting_for_sqlite_writer(tmp_path):
    clock = FakeClock()
    plan = make_plan(Task("a", "research", "Research"))
    path = private_database(tmp_path)
    coordinator = AgentRunCoordinator(
        path, clock_ns=clock, lease_seconds=1, busy_timeout_ms=3000
    )
    coordinator.register_run("run-20", plan)

    events = []
    original_transaction = coordinator._transaction

    @contextmanager
    def observed_transaction():
        with original_transaction() as db:
            events.append("lock")
            yield db

    coordinator._transaction = observed_transaction
    coordinator._clock_ns = lambda: (events.append("clock") or clock.value)

    blocker = sqlite3.connect(path, timeout=3, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    started = threading.Event()
    result = []

    def claim():
        started.set()
        result.append(coordinator.claim_next("run-20", "worker-a"))

    thread = threading.Thread(target=claim)
    try:
        thread.start()
        assert started.wait(timeout=1)
        clock.advance(2)
        blocker.commit()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert result[0] is not None
        assert result[0].lease_expires_ns > clock()
        assert events == ["lock", "clock"]
    finally:
        if thread.is_alive():
            blocker.rollback()
            thread.join(timeout=3)
        blocker.close()
