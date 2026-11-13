"""Regression tests for STAR's durable task/communication ledger."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from star.task_coordination import (
    DuplicateEventError,
    InvalidTransitionError,
    ReportStatus,
    StaleGenerationError,
    TaskLedger,
    TaskLedgerConfig,
    TaskLedgerError,
    TaskStatus,
)


def create(ledger, *, now=10.0):
    return ledger.create_task("build", "Build the lobby", now=now, event_id="create", priority=80)


def start(ledger, *, now=11.0):
    ledger.transition("build", 1, TaskStatus.ACCEPTED, now=now, event_id="accept")
    return ledger.claim_task("build", 1, "worker-a", "lease-a", now=now + 1, event_id="claim")


def complete(ledger, *, generation=1, now=13.0, lease="lease-a"):
    return ledger.transition(
        "build", generation, TaskStatus.COMPLETED, now=now, event_id=f"complete-{generation}",
        lease_id=lease, result_ref="artifact://build", evidence_ref="evidence://playtest",
    )


def test_lifecycle_requires_evidence_and_result(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        with pytest.raises(ValueError, match="result_ref and evidence_ref"):
            ledger.transition("build", 1, TaskStatus.COMPLETED, now=13, event_id="bad",
                              lease_id="lease-a", result_ref="artifact://x")
        result = complete(ledger)
        assert result.status is TaskStatus.COMPLETED
        assert result.evidence_ref == "evidence://playtest"


def test_invalid_state_skips_are_rejected(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        with pytest.raises(InvalidTransitionError):
            ledger.transition("build", 1, TaskStatus.RUNNING, now=11, event_id="skip")


def test_worker_claim_is_atomic_and_lease_token_is_not_in_task_record(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        ledger.transition("build", 1, TaskStatus.ACCEPTED, now=11, event_id="accept")
        claim = ledger.claim_task("build", 1, "worker-a", "secret-lease", now=12, event_id="claim")
        assert claim.task.status is TaskStatus.RUNNING
        assert claim.task.lease_owner == "worker-a"
        assert "secret-lease" not in repr(claim.task)
        with pytest.raises(InvalidTransitionError):
            ledger.claim_task("build", 1, "worker-b", "lease-b", now=13, event_id="claim-b")


def test_lease_is_hashed_in_database(tmp_path):
    db = str(tmp_path / "tasks.db")
    with TaskLedger(db) as ledger:
        create(ledger)
        ledger.transition("build", 1, TaskStatus.ACCEPTED, now=11, event_id="accept")
        ledger.claim_task("build", 1, "worker-a", "secret-lease", now=12, event_id="claim")
        raw = ledger._db.execute("SELECT lease_hash FROM tasks WHERE task_id='build'").fetchone()[0]
        assert raw != "secret-lease"
        assert len(raw) == 64


def test_expired_worker_reclaim_increments_generation_and_fences_old_worker(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        ledger.transition("build", 1, TaskStatus.ACCEPTED, now=11, event_id="accept")
        first = ledger.claim_task("build", 1, "worker-a", "lease-a", now=12,
                                  lease_seconds=5, event_id="claim-a")
        assert first.task.lease_expires_at == 17
        second = ledger.claim_task("build", 1, "worker-b", "lease-b", now=17,
                                   event_id="claim-b")
        assert second.task.generation == 2
        assert second.task.lease_owner == "worker-b"
        with pytest.raises(StaleGenerationError):
            ledger.checkpoint_task("build", 1, "checkpoint://old", now=18,
                                   event_id="old-checkpoint", lease_id="lease-a")
        with pytest.raises(StaleGenerationError):
            ledger.transition("build", 1, TaskStatus.COMPLETED, now=18, event_id="old-complete",
                              lease_id="lease-a", result_ref="artifact://old",
                              evidence_ref="evidence://old")


def test_lease_renewal_requires_current_token_and_unexpired_lease(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        ledger.transition("build", 1, TaskStatus.ACCEPTED, now=11, event_id="accept")
        ledger.claim_task("build", 1, "worker-a", "lease-a", now=12,
                          lease_seconds=5, event_id="claim")
        renewed = ledger.renew_lease("build", 1, "lease-a", now=14,
                                     lease_seconds=20, event_id="renew")
        assert renewed.task.lease_expires_at == 34
        with pytest.raises(StaleGenerationError):
            ledger.renew_lease("build", 1, "wrong-token", now=15, event_id="renew-wrong")


def test_checkpoint_requires_active_worker_lease(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        with pytest.raises(StaleGenerationError):
            ledger.checkpoint_task("build", 1, "checkpoint://x", now=11,
                                   event_id="checkpoint", lease_id="wrong")
        start(ledger)
        saved = ledger.checkpoint_task("build", 1, "checkpoint://good", now=13,
                                       event_id="checkpoint-good", lease_id="lease-a")
        assert saved.checkpoint_ref == "checkpoint://good"


def test_block_and_retry_create_a_new_generation(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        blocked = ledger.transition("build", 1, TaskStatus.BLOCKED, now=13, event_id="block",
                                    lease_id="lease-a", checkpoint_ref="checkpoint://saved",
                                    error_code="asset_missing")
        assert blocked.lease_owner is None
        retried = ledger.retry_task("build", 1, now=14, event_id="retry")
        assert retried.generation == 2
        assert retried.status is TaskStatus.ACCEPTED
        assert retried.checkpoint_ref == "checkpoint://saved"
        assert retried.result_ref is None


def test_completed_task_can_be_retried_without_reusing_old_result(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        complete(ledger)
        retry = ledger.retry_task("build", 1, now=14, event_id="retry")
        assert retry.generation == 2
        assert retry.result_ref is None
        assert retry.evidence_ref is None


def test_duplicate_create_event_is_idempotent_but_not_reusable(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        first = create(ledger)
        again = ledger.create_task("build", "Different title", now=99, event_id="create", priority=1)
        assert again == first
        with pytest.raises(DuplicateEventError):
            ledger.create_task("other", "Other task", now=11, event_id="create")


def test_completed_report_must_match_verified_evidence(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        complete(ledger)
        with pytest.raises(ValueError, match="verified task evidence"):
            ledger.queue_report("report-1", "build", 1, "content://report", "evidence://wrong",
                                now=14, event_id="queue-wrong")
        report = ledger.queue_report("report-1", "build", 1, "content://report",
                                     "evidence://playtest", now=14, event_id="queue")
        assert report.status is ReportStatus.QUEUED


def test_report_is_pending_until_actual_playback_ack(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        complete(ledger)
        ledger.queue_report("report-1", "build", 1, "content://report",
                            "evidence://playtest", now=14, event_id="queue")
        assert len(ledger.pending_reports()) == 1
        played = ledger.mark_report_played("report-1", 1, "playback-1", now=15, event_id="played")
        assert played.status is ReportStatus.PLAYED
        assert played.playback_id == "playback-1"
        assert ledger.pending_reports() == ()


def test_stale_generation_cannot_acknowledge_report(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        complete(ledger)
        ledger.queue_report("report-1", "build", 1, "content://report",
                            "evidence://playtest", now=14, event_id="queue")
        ledger.retry_task("build", 1, now=15, event_id="retry")
        with pytest.raises(StaleGenerationError):
            ledger.mark_report_played("report-1", 1, "playback-1", now=16, event_id="played-old")
        assert ledger.pending_reports() == ()


def test_same_playback_ack_is_idempotent_different_playback_is_not(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        complete(ledger)
        ledger.queue_report("report-1", "build", 1, "content://report",
                            "evidence://playtest", now=14, event_id="queue")
        first = ledger.mark_report_played("report-1", 1, "playback-1", now=15, event_id="played")
        assert ledger.mark_report_played("report-1", 1, "playback-1", now=16,
                                         event_id="played-again") == first
        with pytest.raises(InvalidTransitionError):
            ledger.mark_report_played("report-1", 1, "playback-2", now=16, event_id="played-other")


def test_retracted_report_is_not_pending(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        ledger.queue_report("report-1", "build", 1, "content://report", "checkpoint://one",
                            now=13, event_id="queue")
        report = ledger.retract_report("report-1", 1, now=14, event_id="retract")
        assert report.status is ReportStatus.RETRACTED
        assert ledger.pending_reports() == ()


def test_sqlite_state_survives_reopen(tmp_path):
    db = str(tmp_path / "durable.db")
    with TaskLedger(db) as ledger:
        create(ledger)
        start(ledger)
        ledger.checkpoint_task("build", 1, "checkpoint://durable", now=13,
                               event_id="checkpoint", lease_id="lease-a")
    with TaskLedger(db) as reopened:
        task = reopened.get_task("build")
        assert task.status is TaskStatus.RUNNING
        assert task.checkpoint_ref == "checkpoint://durable"


def test_event_and_task_capacity_fail_closed(tmp_path):
    with TaskLedger(str(tmp_path / "bounded.db"), TaskLedgerConfig(max_tasks=1, max_events=2)) as ledger:
        create(ledger)
        start(ledger)
        assert ledger.stats.events == 2
        with pytest.raises(TaskLedgerError, match="capacity"):
            ledger.create_task("other", "Other task", now=20, event_id="other")


def test_report_capacity_fails_closed(tmp_path):
    with TaskLedger(str(tmp_path / "bounded.db"), TaskLedgerConfig(max_reports=1)) as ledger:
        create(ledger)
        start(ledger)
        ledger.queue_report("one", "build", 1, "content://one", "checkpoint://one",
                            now=13, event_id="report-one")
        with pytest.raises(TaskLedgerError, match="capacity"):
            ledger.queue_report("two", "build", 1, "content://two", "checkpoint://two",
                                now=14, event_id="report-two")


def test_invalid_values_and_closed_database_are_rejected(tmp_path):
    ledger = TaskLedger(str(tmp_path / "closed.db"))
    with pytest.raises(ValueError):
        ledger.create_task("", "title", now=1, event_id="e")
    ledger.close()
    with pytest.raises(TaskLedgerError, match="closed"):
        ledger.get_task("build")


def test_two_connections_cannot_claim_the_same_task(tmp_path):
    db = str(tmp_path / "multi.db")
    first, second = TaskLedger(db), TaskLedger(db)
    try:
        create(first)
        first.transition("build", 1, TaskStatus.ACCEPTED, now=11, event_id="accept")
        first.claim_task("build", 1, "worker-a", "lease-a", now=12, event_id="claim-a")
        with pytest.raises(InvalidTransitionError):
            second.claim_task("build", 1, "worker-b", "lease-b", now=13, event_id="claim-b")
    finally:
        first.close()
        second.close()


def test_parallel_task_creates_are_serialized(tmp_path):
    with TaskLedger(str(tmp_path / "parallel.db"), TaskLedgerConfig(max_tasks=32)) as ledger:
        def add(index):
            return ledger.create_task(f"task-{index}", f"Task {index}",
                                      now=10 + index, event_id=f"event-{index}")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(add, range(32)))
        assert len(results) == 32
        assert ledger.stats.tasks == 32


def test_cancelled_task_does_not_leave_a_queued_report_pending(tmp_path):
    with TaskLedger(str(tmp_path / "tasks.db")) as ledger:
        create(ledger)
        start(ledger)
        ledger.queue_report("report-cancel", "build", 1, "content://progress",
                            "checkpoint://progress", now=13, event_id="queue-progress")
        ledger.transition("build", 1, TaskStatus.CANCELLED, now=14,
                          event_id="cancel", lease_id="lease-a")
        assert ledger.pending_reports() == ()
