import pytest

from star.delivery_ledger import (
    DeliveryConflict,
    DeliveryDeadlineExpired,
    DeliveryLedger,
    DeliveryLeaseExpired,
    DeliveryState,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64


def ledger(**kwargs):
    return DeliveryLedger(clock_epoch="host-a", **kwargs)


def created(book=None, *, segments=(H2, H3), deadline_ms=None):
    book = book or ledger()
    return book, book.create(
        "delivery-1", "task-1", 3, H1, segments,
        now_ms=1, deadline_ms=deadline_ms,
    )


def claim_and_start(book, record, *, attempt="attempt-1", playback="playback-1", now=2):
    lease = book.claim(record.delivery_id, record.version, attempt, now_ms=now)
    return book.start_playback(lease, playback, now_ms=now + 1)


def test_create_is_idempotent_for_exact_contract():
    book, first = created()
    second = book.create("delivery-1", "task-1", 3, H1, (H2, H3), now_ms=2)
    assert second == first
    assert second.version == 1


def test_reusing_delivery_id_for_different_contract_is_rejected():
    book, _ = created()
    with pytest.raises(DeliveryConflict):
        book.create("delivery-1", "task-1", 4, H1, (H2, H3), now_ms=2)


def test_segments_must_be_tuple_of_bounded_sha256_digests():
    book = ledger()
    with pytest.raises(ValueError):
        book.create("d", "t", 1, H1, [H2], now_ms=1)
    with pytest.raises(ValueError):
        book.create("d", "t", 1, H1, ("raw speech",), now_ms=1)
    with pytest.raises(ValueError):
        book.create("d", "t", 1, H1, tuple(H2 for _ in range(257)), now_ms=1)


def test_one_segment_playback_receipt_advances_only_that_segment():
    book, record = created(segments=(H2, H3))
    lease = claim_and_start(book, record)
    updated = book.acknowledge_playback(
        lease, "playback-1", played_ms=1000, duration_ms=1000,
        interrupted=False, now_ms=4,
    )
    assert updated.state is DeliveryState.READY
    assert updated.completed_segments == 1
    assert updated.remaining_segments == 1


def test_all_segments_must_be_acknowledged_before_delivery_is_complete():
    book, record = created(segments=(H2, H3))
    first = claim_and_start(book, record)
    middle = book.acknowledge_playback(
        first, "playback-1", played_ms=100, duration_ms=100,
        interrupted=False, now_ms=4,
    )
    second = claim_and_start(book, middle, attempt="attempt-2", playback="playback-2", now=5)
    final = book.acknowledge_playback(
        second, "playback-2", played_ms=200, duration_ms=200,
        interrupted=False, now_ms=8,
    )
    assert final.state is DeliveryState.DELIVERED
    assert final.completed_segments == 2
    assert final.remaining_segments == 0
    assert book.outstanding() == ()


def test_interruption_keeps_current_segment_pending_and_does_not_replay_prior_segments():
    book, record = created(segments=(H2, H3))
    first = claim_and_start(book, record)
    middle = book.acknowledge_playback(
        first, "playback-1", played_ms=400, duration_ms=1000,
        interrupted=True, now_ms=4,
    )
    assert middle.state is DeliveryState.PARTIAL
    assert middle.completed_segments == 0
    retry = claim_and_start(book, middle, attempt="attempt-2", playback="playback-2", now=5)
    assert retry.segment_index == 0


def test_short_non_interrupted_playback_is_still_partial():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    updated = book.acknowledge_playback(
        lease, "playback-1", played_ms=700, duration_ms=1000,
        interrupted=False, now_ms=4,
    )
    assert updated.state is DeliveryState.PARTIAL
    assert updated.completed_segments == 0


def test_interrupted_playback_is_not_marked_delivered_even_at_full_position():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    updated = book.acknowledge_playback(
        lease, "playback-1", played_ms=1000, duration_ms=1000,
        interrupted=True, now_ms=4,
    )
    assert updated.state is DeliveryState.PARTIAL


def test_wrong_playback_id_cannot_acknowledge_active_segment():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    with pytest.raises(DeliveryLeaseExpired):
        book.acknowledge_playback(
            lease, "other-playback", played_ms=1000, duration_ms=1000,
            interrupted=False, now_ms=4,
        )


def test_claimed_segment_cannot_be_acknowledged_before_playback_starts():
    book, record = created(segments=(H2,))
    lease = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2)
    with pytest.raises(DeliveryLeaseExpired):
        book.acknowledge_playback(
            lease, "playback-1", played_ms=1000, duration_ms=1000,
            interrupted=False, now_ms=3,
        )


def test_stale_receipt_cannot_overwrite_a_new_attempt():
    book, record = created(segments=(H2,))
    first = claim_and_start(book, record)
    partial = book.acknowledge_playback(
        first, "playback-1", played_ms=100, duration_ms=1000,
        interrupted=True, now_ms=4,
    )
    second = claim_and_start(book, partial, attempt="attempt-2", playback="playback-2", now=5)
    with pytest.raises(DeliveryLeaseExpired):
        book.acknowledge_playback(
            first, "playback-1", played_ms=1000, duration_ms=1000,
            interrupted=False, now_ms=8,
        )
    assert book.get("delivery-1").generation == second.generation


def test_expired_claimed_lease_requires_host_stop_confirmation_before_recovery():
    book, record = created(segments=(H2,))
    lease = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2, lease_ms=100)
    with pytest.raises(PermissionError):
        book.recover_expired_lease(lease, now_ms=102, host_confirmed_stopped=False)
    recovered = book.recover_expired_lease(lease, now_ms=102, host_confirmed_stopped=True)
    assert recovered.state is DeliveryState.READY
    assert recovered.completed_segments == 0


def test_expired_playing_lease_recovers_as_partial_only_after_host_stops():
    book, record = created(segments=(H2,))
    claimed = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2, lease_ms=100)
    playing = book.start_playback(claimed, "playback-1", now_ms=3)
    with pytest.raises(PermissionError):
        book.recover_expired_lease(playing, now_ms=102, host_confirmed_stopped=False)
    recovered = book.recover_expired_lease(playing, now_ms=102, host_confirmed_stopped=True)
    assert recovered.state is DeliveryState.PARTIAL


def test_unexpired_lease_cannot_be_recovered_even_if_host_reports_stopped():
    book, record = created(segments=(H2,))
    lease = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2, lease_ms=100)
    with pytest.raises(DeliveryConflict):
        book.recover_expired_lease(lease, now_ms=50, host_confirmed_stopped=True)


def test_playing_audio_cannot_be_failed_without_host_stop_confirmation():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    with pytest.raises(PermissionError):
        book.fail(lease, "tts_error", now_ms=4)
    failed = book.fail(lease, "tts_error", now_ms=5, host_confirmed_stopped=True)
    assert failed.state is DeliveryState.FAILED


def test_claimed_but_not_started_audio_can_fail_without_stop_confirmation():
    book, record = created(segments=(H2,))
    lease = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2)
    failed = book.fail(lease, "tts_error", now_ms=3)
    assert failed.state is DeliveryState.FAILED


def test_playing_audio_cannot_be_cancelled_without_host_stop_confirmation():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    with pytest.raises(PermissionError):
        book.cancel(record.delivery_id, lease.version, now_ms=4)
    cancelled = book.cancel(
        record.delivery_id, lease.version, now_ms=5, host_confirmed_stopped=True
    )
    assert cancelled.state is DeliveryState.CANCELLED


def test_completed_delivery_is_immutable_and_cannot_be_cancelled():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    done = book.acknowledge_playback(
        lease, "playback-1", played_ms=100, duration_ms=100,
        interrupted=False, now_ms=4,
    )
    with pytest.raises(DeliveryConflict):
        book.cancel(done.delivery_id, done.version, now_ms=5)
    assert book.get(done.delivery_id) == done


def test_deadline_expiry_blocks_claim_and_is_reaped():
    book, record = created(segments=(H2,), deadline_ms=20)
    report = book.reap(now_ms=20)
    assert report.expired_deadlines == 1
    assert book.get(record.delivery_id).state is DeliveryState.EXPIRED
    with pytest.raises(DeliveryDeadlineExpired):
        book.claim(
            record.delivery_id,
            book.get(record.delivery_id).version,
            "attempt-1",
            now_ms=21,
        )


def test_completed_delivery_is_not_expired_after_deadline():
    book, record = created(segments=(H2,), deadline_ms=20)
    lease = claim_and_start(book, record)
    done = book.acknowledge_playback(
        lease, "playback-1", played_ms=100, duration_ms=100,
        interrupted=False, now_ms=4,
    )
    report = book.reap(now_ms=20)
    assert report.expired_deadlines == 0
    assert book.get(done.delivery_id) == done


def test_delivery_without_deadline_can_be_retried_after_failure():
    book, record = created(segments=(H2,))
    lease = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2)
    failed = book.fail(lease, "tts_error", now_ms=3)
    retry = book.claim(failed.delivery_id, failed.version, "attempt-2", now_ms=4)
    assert retry.segment_index == 0


def test_deadline_cannot_be_reopened_after_failure():
    book, record = created(segments=(H2,), deadline_ms=20)
    lease = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2)
    failed = book.fail(lease, "tts_error", now_ms=3)
    with pytest.raises(DeliveryDeadlineExpired):
        book.claim(failed.delivery_id, failed.version, "attempt-2", now_ms=20)
    assert book.get(record.delivery_id).state is DeliveryState.EXPIRED


def test_old_clock_epoch_lease_is_rejected():
    book, record = created(segments=(H2,))
    lease = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2)
    other = DeliveryLedger(clock_epoch="host-b")
    with pytest.raises(DeliveryLeaseExpired):
        other.start_playback(lease, "playback-1", now_ms=3)


def test_outstanding_returns_oldest_unfulfilled_only():
    book, first = created(segments=(H2,))
    second = book.create("delivery-2", "task-2", 1, H3, (H1,), now_ms=2)
    lease = claim_and_start(book, first)
    book.acknowledge_playback(
        lease, "playback-1", played_ms=100, duration_ms=100,
        interrupted=False, now_ms=4,
    )
    assert [row.delivery_id for row in book.outstanding()] == [second.delivery_id]


def test_capacity_is_bounded():
    book = ledger(max_records=1)
    book.create("d1", "t1", 1, H1, (H2,), now_ms=1)
    with pytest.raises(OverflowError):
        book.create("d2", "t2", 1, H1, (H2,), now_ms=2)


def test_monotonic_clock_cannot_move_backwards():
    book, _ = created()
    with pytest.raises(ValueError):
        book.create("delivery-2", "task-2", 1, H1, (H2,), now_ms=0)


def test_boolean_is_not_accepted_as_played_time_or_interruption_flag():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    with pytest.raises(ValueError):
        book.acknowledge_playback(
            lease, "playback-1", played_ms=True, duration_ms=100,
            interrupted=False, now_ms=4,
        )


def test_played_time_cannot_exceed_duration_and_tolerance():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    with pytest.raises(ValueError):
        book.acknowledge_playback(
            lease, "playback-1", played_ms=110, duration_ms=100,
            interrupted=False, now_ms=4,
        )


def test_completion_tolerance_is_bounded_by_segment_duration():
    book, record = created(segments=(H2,))
    lease = claim_and_start(book, record)
    with pytest.raises(ValueError):
        book.acknowledge_playback(
            lease, "playback-1", played_ms=0, duration_ms=100,
            interrupted=False, now_ms=4, completion_tolerance_ms=100,
        )


def test_delivery_snapshot_is_frozen():
    book, record = created()
    with pytest.raises(AttributeError):
        record.state = DeliveryState.DELIVERED


def test_segment_claims_are_sequential_and_unique():
    book, record = created(segments=(H2, H3))
    lease = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2)
    with pytest.raises(DeliveryConflict):
        book.claim(record.delivery_id, record.version, "attempt-2", now_ms=3)
    playing = book.start_playback(lease, "playback-1", now_ms=3)
    done = book.acknowledge_playback(
        playing, "playback-1", played_ms=100, duration_ms=100,
        interrupted=False, now_ms=4,
    )
    next_lease = book.claim(done.delivery_id, done.version, "attempt-2", now_ms=5)
    assert next_lease.segment_index == 1


def test_partial_later_segment_does_not_replay_completed_segments():
    book, record = created(segments=(H2, H3))
    first = claim_and_start(book, record)
    middle = book.acknowledge_playback(
        first, "playback-1", played_ms=100, duration_ms=100,
        interrupted=False, now_ms=4,
    )
    second = claim_and_start(book, middle, attempt="attempt-2", playback="playback-2", now=5)
    partial = book.acknowledge_playback(
        second, "playback-2", played_ms=50, duration_ms=200,
        interrupted=True, now_ms=8,
    )
    retry = book.claim(partial.delivery_id, partial.version, "attempt-3", now_ms=9)
    assert retry.segment_index == 1
    assert book.get(record.delivery_id).completed_segments == 1


def test_reaper_does_not_silently_reclaim_expired_playback_lease():
    book, record = created(segments=(H2,))
    claimed = book.claim(record.delivery_id, record.version, "attempt-1", now_ms=2, lease_ms=100)
    playing = book.start_playback(claimed, "playback-1", now_ms=3)
    report = book.reap(now_ms=102)
    assert report.expired_deadlines == 0
    assert book.get(record.delivery_id).state is DeliveryState.PLAYING
    with pytest.raises(DeliveryConflict):
        book.claim(record.delivery_id, playing.version, "attempt-2", now_ms=103)


def test_concurrent_claims_allow_only_one_worker_to_win():
    from concurrent.futures import ThreadPoolExecutor

    book, record = created(segments=(H2,))

    def attempt(index):
        try:
            return book.claim(
                record.delivery_id, record.version, f"attempt-{index}", now_ms=2
            )
        except DeliveryConflict:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(12)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
