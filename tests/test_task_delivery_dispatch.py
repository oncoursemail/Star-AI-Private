import pytest

from star.delivery_ledger import DeliveryConflict, DeliveryLedger, DeliveryState
from star.task_delivery_dispatch import enqueue_completed_task
from star.task_ledger import TaskConflict, TaskLedger, TaskState

SPEC = "1" * 64
RESULT = "2" * 64
SEGMENT_A = "3" * 64
SEGMENT_B = "4" * 64


def completed_task():
    tasks = TaskLedger(clock_epoch="task-host")
    created = tasks.create("task-1", "research", SPEC, now_ms=1)
    lease = tasks.claim(created.task_id, created.version, "attempt-1", now_ms=2)
    completed = tasks.complete(lease, RESULT, now_ms=3)
    return tasks, completed


def test_completed_task_enqueues_using_authoritative_task_result_digest():
    tasks, completed = completed_task()
    deliveries = DeliveryLedger(clock_epoch="delivery-host")

    record = enqueue_completed_task(
        tasks, deliveries, completed.task_id, completed.version,
        "delivery-1", (SEGMENT_A, SEGMENT_B), now_ms=4,
    )

    assert record.task_id == completed.task_id
    assert record.task_version == completed.version
    assert record.result_sha256 == completed.result_sha256
    assert record.state is DeliveryState.READY


def test_queued_task_cannot_be_enqueued_for_delivery():
    tasks = TaskLedger(clock_epoch="task-host")
    queued = tasks.create("task-1", "research", SPEC, now_ms=1)
    deliveries = DeliveryLedger(clock_epoch="delivery-host")

    with pytest.raises(TaskConflict, match="completed task"):
        enqueue_completed_task(
            tasks, deliveries, queued.task_id, queued.version,
            "delivery-1", (SEGMENT_A,), now_ms=2,
        )


def test_stale_task_version_cannot_create_delivery():
    tasks, completed = completed_task()
    deliveries = DeliveryLedger(clock_epoch="delivery-host")

    with pytest.raises(TaskConflict, match="version changed"):
        enqueue_completed_task(
            tasks, deliveries, completed.task_id, completed.version - 1,
            "delivery-1", (SEGMENT_A,), now_ms=4,
        )

    assert deliveries.outstanding() == ()


def test_exact_retry_is_idempotent_even_after_delivery_deadline_expires():
    tasks, completed = completed_task()
    deliveries = DeliveryLedger(clock_epoch="delivery-host")

    first = enqueue_completed_task(
        tasks, deliveries, completed.task_id, completed.version,
        "delivery-1", (SEGMENT_A,), now_ms=4, deadline_ms=20,
    )
    report = deliveries.reap(now_ms=20)
    assert report.expired_deadlines == 1

    retry = enqueue_completed_task(
        tasks, deliveries, completed.task_id, completed.version,
        "delivery-1", (SEGMENT_A,), now_ms=21, deadline_ms=20,
    )

    assert retry == deliveries.get(first.delivery_id)
    assert retry.state is DeliveryState.EXPIRED
    assert retry.version > first.version


def test_conflicting_reuse_of_delivery_id_is_rejected():
    tasks, completed = completed_task()
    deliveries = DeliveryLedger(clock_epoch="delivery-host")
    enqueue_completed_task(
        tasks, deliveries, completed.task_id, completed.version,
        "delivery-1", (SEGMENT_A,), now_ms=4,
    )

    with pytest.raises(DeliveryConflict):
        enqueue_completed_task(
            tasks, deliveries, completed.task_id, completed.version,
            "delivery-1", (SEGMENT_B,), now_ms=5,
        )


def test_completed_task_result_digest_cannot_be_overridden_by_caller():
    tasks, completed = completed_task()
    deliveries = DeliveryLedger(clock_epoch="delivery-host")

    # The public bridge accepts segment digests, but takes the result digest
    # exclusively from the immutable completed TaskRecord.
    record = enqueue_completed_task(
        tasks, deliveries, completed.task_id, completed.version,
        "delivery-1", (SEGMENT_A,), now_ms=4,
    )

    assert record.result_sha256 == RESULT
    assert record.result_sha256 != SEGMENT_A
