from concurrent.futures import ThreadPoolExecutor
import hashlib

import pytest

from star.task_ledger import (
    TaskConflict, TaskDeadlineExpired, TaskLeaseExpired, TaskLedger, TaskState,
)

H1 = hashlib.sha256(b"spec-1").hexdigest()
H2 = hashlib.sha256(b"spec-2").hexdigest()
R1 = hashlib.sha256(b"result-1").hexdigest()


def ledger(**kwargs):
    return TaskLedger(clock_epoch="boot-a", **kwargs)


def test_create_and_claim_advance_versions():
    book = ledger()
    created = book.create("voice-1", "voice", H1, now_ms=10)
    lease = book.claim("voice-1", created.version, "attempt-1", now_ms=20)
    current = book.get("voice-1")
    assert current.state is TaskState.RUNNING
    assert current.version == 2
    assert lease.version == 2
    assert lease.expires_ms == 30_020


def test_two_workers_cannot_claim_same_version():
    book = ledger()
    created = book.create("game-1", "game", H1, now_ms=1)

    def claim(attempt):
        try:
            return book.claim("game-1", created.version, attempt, now_ms=2)
        except TaskConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("a1", "a2")))
    assert sum(item is not None for item in results) == 1


def test_complete_commits_digest_and_terminal_version():
    book = ledger()
    created = book.create("creator-1", "creator", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2)
    completed = book.complete(lease, R1, now_ms=3)
    assert completed.state is TaskState.COMPLETED
    assert completed.version == 3
    assert completed.result_sha256 == R1
    assert completed.attempt_id is None


def test_cancel_invalidates_late_worker_result():
    book = ledger()
    created = book.create("stream-1", "stream", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2)
    cancelled = book.cancel(created.task_id, lease.version, now_ms=3)
    assert cancelled.state is TaskState.CANCELLED
    with pytest.raises(TaskLeaseExpired):
        book.complete(lease, R1, now_ms=4)


def test_refine_running_task_invalidates_old_attempt_and_requeues():
    book = ledger()
    created = book.create("research-1", "research", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2)
    refined = book.refine(created.task_id, lease.version, H2, now_ms=3)
    assert refined.state is TaskState.QUEUED
    assert refined.version == lease.version + 1
    assert refined.spec_sha256 == H2
    with pytest.raises(TaskLeaseExpired):
        book.complete(lease, R1, now_ms=4)


def test_expired_worker_lease_requeues_with_new_version():
    book = ledger(max_lease_ms=1000)
    created = book.create("learn-1", "learning", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2, lease_ms=100)
    report = book.reap(now_ms=102)
    queued = book.get(created.task_id)
    assert report.requeued_leases == 1
    assert queued.state is TaskState.QUEUED
    assert queued.version == lease.version + 1
    with pytest.raises(TaskLeaseExpired):
        book.complete(lease, R1, now_ms=103)


def test_deadline_expiry_is_terminal_and_invalidates_lease():
    book = ledger()
    created = book.create("tool-1", "tool", H1, now_ms=1, deadline_ms=50)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2, lease_ms=1000)
    assert lease.expires_ms == 50
    report = book.reap(now_ms=50)
    assert report.expired_deadlines == 1
    assert book.get(created.task_id).state is TaskState.EXPIRED
    with pytest.raises(TaskLeaseExpired):
        book.complete(lease, R1, now_ms=51)


def test_complete_after_deadline_marks_expired_before_rejecting():
    book = ledger()
    created = book.create("voice-2", "voice", H1, now_ms=1, deadline_ms=10)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2)
    with pytest.raises(TaskDeadlineExpired):
        book.complete(lease, R1, now_ms=10)
    assert book.get(created.task_id).state is TaskState.EXPIRED


def test_renew_preserves_attempt_version_and_respects_task_deadline():
    book = ledger()
    created = book.create("research-2", "research", H1, now_ms=1, deadline_ms=500)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2, lease_ms=100)
    renewed = book.renew(lease, now_ms=50, lease_ms=300)
    assert renewed.version == lease.version
    assert renewed.attempt_id == lease.attempt_id
    assert renewed.expires_ms == 350
    assert book.get(created.task_id).lease_expires_ms == 350


def test_failed_task_can_be_refined_and_retried():
    book = ledger()
    created = book.create("creator-2", "creator", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2)
    failed = book.fail(lease, "worker_timeout", now_ms=3)
    retried = book.refine(failed.task_id, failed.version, H2, now_ms=4)
    assert retried.state is TaskState.QUEUED
    assert retried.failure_code is None
    assert retried.result_sha256 is None


def test_completed_task_cannot_be_refined_in_place():
    book = ledger()
    created = book.create("done-1", "game", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2)
    done = book.complete(lease, R1, now_ms=3)
    with pytest.raises(TaskConflict):
        book.refine(done.task_id, done.version, H2, now_ms=4)


def test_ledger_rejects_clock_regression():
    book = ledger()
    book.create("clock-1", "system", H1, now_ms=10)
    with pytest.raises(ValueError, match="moved backwards"):
        book.create("clock-2", "system", H1, now_ms=9)


def test_task_ids_are_never_reused_within_epoch():
    book = ledger()
    book.create("unique-1", "voice", H1, now_ms=1)
    with pytest.raises(TaskConflict):
        book.create("unique-1", "voice", H2, now_ms=2)


def test_capacity_is_bounded_and_never_evicts_active_work():
    book = ledger(max_records=1)
    created = book.create("cap-1", "voice", H1, now_ms=1)
    book.claim(created.task_id, created.version, "a1", now_ms=2)
    with pytest.raises(OverflowError):
        book.create("cap-2", "game", H1, now_ms=3)
    assert book.get("cap-1").state is TaskState.RUNNING


def test_old_clock_epoch_lease_is_rejected():
    book_a = ledger()
    created = book_a.create("epoch-1", "voice", H1, now_ms=1)
    lease = book_a.claim(created.task_id, created.version, "a1", now_ms=2)
    book_b = TaskLedger(clock_epoch="boot-b")
    book_b.create("epoch-1", "voice", H1, now_ms=1)
    with pytest.raises(TaskLeaseExpired):
        book_b.complete(lease, R1, now_ms=2)


@pytest.mark.parametrize("bad", ["", "ABC", "g" * 63, "G" * 64, 1, None])
def test_invalid_sha256_is_rejected(bad):
    book = ledger()
    with pytest.raises(ValueError):
        book.create("bad-1", "voice", bad, now_ms=1)


def test_invalid_domains_and_attempt_ids_are_rejected():
    book = ledger()
    with pytest.raises(ValueError):
        book.create("bad-2", "not a domain", H1, now_ms=1)
    created = book.create("good-1", "voice", H1, now_ms=2)
    with pytest.raises(ValueError):
        book.claim(created.task_id, created.version, "../bad", now_ms=3)


def test_counts_are_aggregate_and_complete():
    book = ledger()
    created = book.create("count-1", "voice", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2)
    book.complete(lease, R1, now_ms=3)
    assert book.counts() == {
        "queued": 0, "running": 0, "completed": 1,
        "failed": 0, "cancelled": 0, "expired": 0,
    }
    assert len(book.snapshot()) == 1


def test_lease_cannot_commit_at_exact_expiry():
    book = ledger()
    created = book.create("boundary-1", "voice", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2, lease_ms=100)
    with pytest.raises(TaskLeaseExpired):
        book.complete(lease, R1, now_ms=lease.expires_ms)


def test_renew_invalidates_the_previous_lease_handle():
    book = ledger()
    created = book.create("renew-1", "voice", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2, lease_ms=200)
    renewed = book.renew(lease, now_ms=50, lease_ms=300)
    with pytest.raises(TaskLeaseExpired):
        book.complete(lease, R1, now_ms=51)
    assert book.complete(renewed, R1, now_ms=52).state is TaskState.COMPLETED


def test_stale_cancel_version_cannot_override_a_newer_refinement():
    book = ledger()
    created = book.create("cas-1", "creator", H1, now_ms=1)
    refined = book.refine(created.task_id, created.version, H2, now_ms=2)
    with pytest.raises(TaskConflict):
        book.cancel(created.task_id, created.version, now_ms=3)
    assert book.get(created.task_id).state is TaskState.QUEUED
    assert book.get(created.task_id).version == refined.version


def test_reap_handles_multiple_leases_and_deadlines_independently():
    book = ledger(max_lease_ms=1000)
    a = book.create("reap-a", "voice", H1, now_ms=1, deadline_ms=500)
    b = book.create("reap-b", "game", H1, now_ms=2)
    la = book.claim(a.task_id, a.version, "aa", now_ms=3, lease_ms=100)
    lb = book.claim(b.task_id, b.version, "bb", now_ms=4, lease_ms=100)
    report = book.reap(now_ms=104)
    assert report.requeued_leases == 2
    assert report.expired_deadlines == 0
    assert book.get(la.task_id).state is TaskState.QUEUED
    assert book.get(lb.task_id).state is TaskState.QUEUED


def test_terminal_task_is_not_reaped_or_mutated():
    book = ledger()
    created = book.create("terminal-1", "voice", H1, now_ms=1)
    lease = book.claim(created.task_id, created.version, "a1", now_ms=2)
    done = book.complete(lease, R1, now_ms=3)
    report = book.reap(now_ms=10_000)
    assert report.requeued_leases == 0
    assert report.expired_deadlines == 0
    assert book.get(done.task_id) == done
