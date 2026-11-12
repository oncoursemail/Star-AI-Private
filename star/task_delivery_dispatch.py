"""Idempotent bridge from verified task completion to result delivery.

This module does not speak text or access audio. The caller supplies ordered
segment digests produced by its separately protected response pipeline.
"""
from __future__ import annotations

from .delivery_ledger import DeliveryLedger, DeliveryRecord
from .task_ledger import TaskConflict, TaskLedger, TaskState


def enqueue_completed_task(
    task_ledger: TaskLedger,
    delivery_ledger: DeliveryLedger,
    task_id: str,
    expected_task_version: int,
    delivery_id: str,
    segment_sha256s: tuple[str, ...],
    *,
    now_ms: int,
    deadline_ms: int | None = None,
) -> DeliveryRecord:
    """Create an idempotent delivery obligation for one completed task version.

    The task must still be COMPLETED at the exact expected version. The result
    digest is taken from the task ledger, never supplied independently by the
    caller. Retrying the same delivery ID and contract is safe because the
    delivery ledger rejects conflicting reuse and returns an existing record.

    This is an in-process bridge, not an atomic transaction across the task
    ledger and delivery store. A durable task-completion outbox is still needed
    to close the crash window between task completion and delivery enqueue.
    """
    if type(expected_task_version) is not int or expected_task_version < 1:
        raise TaskConflict("expected task version must be a positive integer")

    task = task_ledger.get(task_id)
    if task.version != expected_task_version:
        raise TaskConflict("task version changed before delivery enqueue")
    if task.state is not TaskState.COMPLETED:
        raise TaskConflict("only a completed task can be enqueued for delivery")
    if task.result_sha256 is None:
        raise TaskConflict("completed task is missing its verified result digest")

    return delivery_ledger.create(
        delivery_id,
        task.task_id,
        task.version,
        task.result_sha256,
        segment_sha256s,
        now_ms=now_ms,
        deadline_ms=deadline_ms,
    )


__all__ = ["enqueue_completed_task"]
