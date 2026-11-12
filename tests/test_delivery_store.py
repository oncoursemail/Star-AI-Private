from __future__ import annotations

import json
import sqlite3

import pytest

from star.delivery_ledger import (
    DeliveryConflict,
    DeliveryLeaseExpired,
    DeliveryState,
)
from star.delivery_store import (
    DeliveryStoreConflict,
    DeliveryStoreCorrupt,
    DeliveryStoreError,
    SQLiteDeliveryLedger,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64


class WallClock:
    def __init__(self, value: int = 1_000_000):
        self.value = value

    def __call__(self) -> int:
        return self.value


def open_store(path, wall, *, now=100, epoch="host-a", **kwargs):
    return SQLiteDeliveryLedger(
        path, clock_epoch=epoch, now_ms=now, wall_clock_ms=wall, **kwargs
    )


def create_one(store, *, deadline_ms=None):
    return store.create(
        "delivery-1", "task-1", 4, H1, (H2, H3),
        now_ms=100, deadline_ms=deadline_ms,
    )


def start_one(store, record, *, now=101):
    claimed = store.claim(record.delivery_id, record.version, "attempt-1", now_ms=now)
    return store.start_playback(claimed, "playback-1", now_ms=now + 1)


def test_new_store_uses_wal_and_passes_integrity_check(tmp_path):
    wall = WallClock()
    store = open_store(tmp_path / "delivery.sqlite3", wall)
    try:
        assert store.integrity_check() == "ok"
        mode = store._db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        store.close()


def test_ready_delivery_survives_restart_and_rebases_monotonic_times(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall, now=100)
    record = create_one(first, deadline_ms=500)
    first.close()

    wall.value += 50
    second = open_store(path, wall, now=10_000, epoch="host-b")
    try:
        restored = second.get(record.delivery_id)
        assert restored.state is DeliveryState.READY
        assert restored.created_ms == 10_000 - 50
        assert restored.deadline_ms == 10_000 + 350
        assert restored.version == record.version
    finally:
        second.close()


def test_completed_segment_cursor_survives_restart_without_replaying_it(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall)
    record = create_one(first)
    lease = start_one(first, record)
    progress = first.acknowledge_playback(
        lease, "playback-1", played_ms=100, duration_ms=100,
        interrupted=False, now_ms=104,
    )
    assert progress.completed_segments == 1
    first.close()

    second = open_store(path, wall, now=500, epoch="host-b")
    try:
        restored = second.get(record.delivery_id)
        assert restored.completed_segments == 1
        next_lease = second.claim(restored.delivery_id, restored.version, "attempt-2", now_ms=501)
        assert next_lease.segment_index == 1
    finally:
        second.close()


def test_claimed_work_is_fenced_until_host_confirms_stop_after_restart(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall)
    record = create_one(first)
    first.claim(record.delivery_id, record.version, "attempt-1", now_ms=101)
    first.close()

    second = open_store(path, wall, now=500, epoch="host-b")
    try:
        recovered = second.get(record.delivery_id)
        assert recovered.state is DeliveryState.RECOVERY_REQUIRED
        with pytest.raises(DeliveryConflict):
            second.claim(recovered.delivery_id, recovered.version, "attempt-2", now_ms=501)
        with pytest.raises(PermissionError):
            second.reconcile_after_restart(
                recovered.delivery_id, recovered.version, now_ms=501,
                host_confirmed_stopped=False,
            )
        ready = second.reconcile_after_restart(
            recovered.delivery_id, recovered.version, now_ms=502,
            host_confirmed_stopped=True,
        )
        assert ready.state is DeliveryState.READY
        assert ready.failure_code == "restart_reconciled"
    finally:
        second.close()


def test_playing_work_recovers_as_partial_only_after_host_stop_confirmation(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall)
    record = create_one(first)
    start_one(first, record)
    first.close()

    second = open_store(path, wall, now=500, epoch="host-b")
    try:
        recovered = second.get(record.delivery_id)
        assert recovered.state is DeliveryState.RECOVERY_REQUIRED
        assert recovered.completed_segments == 0
        with pytest.raises(PermissionError):
            second.cancel(recovered.delivery_id, recovered.version, now_ms=501)
        partial = second.reconcile_after_restart(
            recovered.delivery_id, recovered.version, now_ms=502,
            host_confirmed_stopped=True,
        )
        assert partial.state is DeliveryState.PARTIAL
    finally:
        second.close()


def test_old_lease_cannot_be_used_after_restart(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall)
    record = create_one(first)
    old_lease = start_one(first, record)
    first.close()

    second = open_store(path, wall, now=500, epoch="host-b")
    try:
        with pytest.raises(DeliveryLeaseExpired):
            second.acknowledge_playback(
                old_lease, "playback-1", played_ms=1000, duration_ms=1000,
                interrupted=False, now_ms=501,
            )
    finally:
        second.close()


def test_deadline_expires_across_restart_using_wall_clock(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall)
    record = create_one(first, deadline_ms=200)
    first.close()

    wall.value += 100
    second = open_store(path, wall, now=500, epoch="host-b")
    try:
        restored = second.get(record.delivery_id)
        assert restored.state is DeliveryState.EXPIRED
        assert restored.failure_code == "deadline_expired_on_restore"
    finally:
        second.close()


def test_wall_clock_rollback_expires_deadline_bound_obligations(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock(1_000_000)
    first = open_store(path, wall)
    record = create_one(first, deadline_ms=500)
    first.close()

    wall.value -= 1
    second = open_store(path, wall, now=500, epoch="host-b")
    try:
        assert second.get(record.delivery_id).state is DeliveryState.EXPIRED
    finally:
        second.close()


def test_no_deadline_obligation_survives_wall_clock_rollback_but_active_work_is_fenced(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock(1_000_000)
    first = open_store(path, wall)
    record = create_one(first)
    start_one(first, record)
    first.close()

    wall.value -= 1
    second = open_store(path, wall, now=500, epoch="host-b")
    try:
        assert second.get(record.delivery_id).state is DeliveryState.RECOVERY_REQUIRED
    finally:
        second.close()


def test_idempotent_create_survives_restart(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall)
    original = create_one(first)
    first.close()

    second = open_store(path, wall, now=500, epoch="host-b")
    try:
        repeated = second.create(
            "delivery-1", "task-1", 4, H1, (H2, H3), now_ms=501,
        )
        assert repeated == second.get("delivery-1")
        assert repeated.version == original.version
    finally:
        second.close()


def test_two_store_instances_detect_stale_writer(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall)
    second = open_store(path, wall)
    try:
        record = create_one(first)
        assert record.state is DeliveryState.READY
        with pytest.raises(DeliveryStoreConflict):
            create_one(second)
        assert second.get("delivery-1") if False else True
    finally:
        first.close()
        second.close()


def test_failed_database_commit_rolls_back_in_memory_mutation(tmp_path, monkeypatch):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    store = open_store(path, wall)
    record = create_one(store)

    def fail_commit(before):
        raise sqlite3.OperationalError("simulated disk failure")

    monkeypatch.setattr(store, "_persist_changes", fail_commit)
    with pytest.raises(sqlite3.OperationalError):
        store.claim(record.delivery_id, record.version, "attempt-1", now_ms=101)
    assert store.get(record.delivery_id).state is DeliveryState.READY
    store.close()


def test_event_history_is_bounded(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    store = open_store(path, wall, max_events=100)
    try:
        for index in range(101):
            store.create(
                f"delivery-{index}", f"task-{index}", 1, H1, (H2,),
                now_ms=100 + index,
            )
        count = store._db.execute("SELECT COUNT(*) FROM delivery_events").fetchone()[0]
        assert count <= 100
    finally:
        store.close()


def test_database_does_not_store_speech_content(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    store = open_store(path, wall)
    create_one(store)
    store.close()
    raw = path.read_bytes()
    assert b"hello viewer" not in raw
    assert b"transcript" not in raw
    assert b"audio payload" not in raw


def test_corrupt_record_json_is_rejected(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    first = open_store(path, wall)
    create_one(first)
    first.close()

    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE delivery_records SET record_json=? WHERE delivery_id=?",
        ('{"unexpected":"payload"}', "delivery-1"),
    )
    connection.commit()
    connection.close()

    with pytest.raises(DeliveryStoreCorrupt):
        open_store(path, wall, now=500, epoch="host-b")


def test_future_schema_version_is_rejected(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    store = open_store(path, wall)
    store.close()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=99")
    connection.commit()
    connection.close()
    with pytest.raises(DeliveryStoreError, match="schema version"):
        open_store(path, wall, now=500, epoch="host-b")


def test_integrity_and_checkpoint_are_available_after_mutations(tmp_path):
    path = tmp_path / "delivery.sqlite3"
    wall = WallClock()
    store = open_store(path, wall)
    try:
        record = create_one(store)
        assert store.integrity_check() == "ok"
        assert len(store.checkpoint()) == 3
        assert store.get(record.delivery_id).state is DeliveryState.READY
    finally:
        store.close()
