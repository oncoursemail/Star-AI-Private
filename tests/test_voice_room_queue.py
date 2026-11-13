"""Tests for the bounded, privacy-minimizing multiparty cue queue."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from star.voice.room import CueIntent, CueSource, RoomAction, RoomCue, RoomDecision
from star.voice.room_queue import RoomCueQueue, RoomQueueConfig, RoomQueueResult


def cue(event_id: str, *, ended_at: float = 10.0) -> RoomCue:
    return RoomCue(
        event_id=event_id,
        speaker_id="speaker-opaque",
        source=CueSource.CHAT,
        intent=CueIntent.DIRECT_QUESTION,
        addressed_to_star=True,
        confidence=0.99,
        started_at=ended_at - 0.2,
        ended_at=ended_at,
    )


def queued(item: RoomCue, priority: int = 75) -> RoomDecision:
    return RoomDecision(RoomAction.QUEUE, item.event_id, "test_queued", priority)


def test_add_and_pop_one_content_free_cue():
    queue = RoomCueQueue()
    item = cue("one")
    assert queue.enqueue(item, queued(item), now=10.0) is RoomQueueResult.ADDED
    assert queue.pop_next(now=10.1) == item
    assert len(queue) == 0
    assert queue.stats.accepted == 1
    assert queue.stats.dequeued == 1


def test_higher_priority_cue_is_popped_first():
    queue = RoomCueQueue()
    low, high = cue("low"), cue("high")
    assert queue.enqueue(low, queued(low, 55), now=10.0) is RoomQueueResult.ADDED
    assert queue.enqueue(high, queued(high, 100), now=10.0) is RoomQueueResult.ADDED
    assert queue.pop_next(now=10.1) == high
    assert queue.pop_next(now=10.1) == low


def test_equal_priority_is_fifo():
    queue = RoomCueQueue()
    first, second = cue("first"), cue("second")
    queue.enqueue(first, queued(first), now=10.0)
    queue.enqueue(second, queued(second), now=10.0)
    assert queue.pop_next(now=10.1) == first
    assert queue.pop_next(now=10.1) == second


def test_waiting_cue_ages_to_avoid_starvation():
    queue = RoomCueQueue(RoomQueueConfig(aging_interval_seconds=1.0))
    old, fresh = cue("old"), cue("fresh")
    queue.enqueue(old, queued(old, 55), now=10.0)
    queue.enqueue(fresh, queued(fresh, 58), now=13.0)
    assert queue.pop_next(now=14.0) == old


def test_duplicate_is_rejected_while_queued_and_after_dequeue():
    queue = RoomCueQueue()
    item = cue("duplicate")
    assert queue.enqueue(item, queued(item), now=10.0) is RoomQueueResult.ADDED
    assert queue.enqueue(item, queued(item), now=10.1) is RoomQueueResult.DUPLICATE
    assert queue.pop_next(now=10.2) == item
    assert queue.enqueue(item, queued(item), now=10.3) is RoomQueueResult.DUPLICATE
    assert queue.stats.duplicates == 2


def test_full_queue_rejects_without_silently_evicting_existing_items():
    queue = RoomCueQueue(RoomQueueConfig(max_items=1))
    first, second = cue("first"), cue("second")
    assert queue.enqueue(first, queued(first), now=10.0) is RoomQueueResult.ADDED
    assert queue.enqueue(second, queued(second), now=10.0) is RoomQueueResult.FULL
    assert queue.pop_next(now=10.1) == first
    assert queue.stats.rejected_full == 1


def test_stale_cue_is_rejected_and_queue_wait_is_also_bounded():
    queue = RoomCueQueue(RoomQueueConfig(max_event_age_seconds=2.0, max_queue_wait_seconds=1.0))
    stale = cue("stale", ended_at=5.0)
    assert queue.enqueue(stale, queued(stale), now=10.0) is RoomQueueResult.STALE
    current = cue("current", ended_at=10.0)
    assert queue.enqueue(current, queued(current), now=10.0) is RoomQueueResult.ADDED
    expired = queue.expire(now=11.0)
    assert expired == (current,)
    assert queue.stats.expired == 1
    assert queue.stats.rejected_stale == 1


def test_event_age_deadline_wins_when_queue_wait_is_longer():
    queue = RoomCueQueue(RoomQueueConfig(max_event_age_seconds=2.0, max_queue_wait_seconds=9.0))
    item = cue("age-bound", ended_at=10.0)
    queue.enqueue(item, queued(item), now=10.0)
    assert queue.pop_next(now=11.99) == item
    item2 = cue("age-bound-2", ended_at=10.0)
    queue.enqueue(item2, queued(item2), now=10.0)
    assert queue.pop_next(now=12.0) is None


def test_non_queue_decision_and_partial_cue_are_not_accepted():
    queue = RoomCueQueue()
    item = cue("respond")
    decision = RoomDecision(RoomAction.RESPOND, item.event_id, "directed", 75)
    assert queue.enqueue(item, decision, now=10.0) is RoomQueueResult.NOT_QUEUEABLE
    partial = RoomCue(
        event_id="partial",
        speaker_id="speaker-opaque",
        source=CueSource.AUDIO,
        intent=CueIntent.DIRECT_QUESTION,
        addressed_to_star=True,
        confidence=0.99,
        started_at=9.8,
        ended_at=10.0,
        final=False,
    )
    assert queue.enqueue(partial, queued(partial), now=10.0) is RoomQueueResult.NOT_QUEUEABLE
    assert len(queue) == 0
    assert queue.stats.not_queueable == 2


def test_event_id_mismatch_is_rejected():
    queue = RoomCueQueue()
    item = cue("actual")
    with pytest.raises(ValueError, match="must match"):
        queue.enqueue(item, queued(cue("other")), now=10.0)


def test_discard_does_not_make_event_reusable():
    queue = RoomCueQueue()
    item = cue("discard")
    queue.enqueue(item, queued(item), now=10.0)
    assert queue.discard(item.event_id)
    assert not queue.discard(item.event_id)
    assert queue.enqueue(item, queued(item), now=10.1) is RoomQueueResult.DUPLICATE


def test_reset_clears_queue_dedupe_and_counters():
    queue = RoomCueQueue()
    item = cue("reset")
    queue.enqueue(item, queued(item), now=10.0)
    queue.reset()
    assert len(queue) == 0
    assert queue.stats.accepted == 0
    assert queue.enqueue(item, queued(item), now=10.1) is RoomQueueResult.ADDED


def test_concurrent_enqueue_is_bounded_and_deduplicated():
    queue = RoomCueQueue(RoomQueueConfig(max_items=64))
    items = [cue(f"event-{i}") for i in range(50)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda item: queue.enqueue(item, queued(item), now=10.0), items))
    assert results.count(RoomQueueResult.ADDED) == 50
    assert len(queue) == 50


def test_invalid_config_is_rejected():
    with pytest.raises(ValueError):
        RoomQueueConfig(max_items=0)
    with pytest.raises(ValueError):
        RoomQueueConfig(max_event_age_seconds=float("nan"))


def test_invalid_monotonic_timestamp_is_rejected():
    queue = RoomCueQueue()
    with pytest.raises(ValueError, match="finite monotonic"):
        queue.pop_next(now=float("nan"))


def test_queue_stores_only_metadata_fields():
    assert set(RoomCue.__dataclass_fields__) == {
        "event_id", "speaker_id", "source", "intent", "addressed_to_star",
        "confidence", "started_at", "ended_at", "overlap_ms", "urgency", "final",
        "resolves_event_id",
    }


def test_pop_expiry_remains_available_for_host_payload_cleanup():
    queue = RoomCueQueue(RoomQueueConfig(max_event_age_seconds=8.0))
    item = cue("expired-during-pop")
    queue.enqueue(item, queued(item), now=10.0)
    assert queue.pop_next(now=18.0) is None
    assert queue.expire(now=18.0) == (item,)
    assert queue.stats.expired == 1


def test_expiry_notification_buffer_is_bounded_and_reports_overflow():
    queue = RoomCueQueue(RoomQueueConfig(max_items=4, dedupe_capacity=2, max_event_age_seconds=8.0))
    items = [cue(f"expired-{i}") for i in range(4)]
    for item in items:
        queue.enqueue(item, queued(item), now=10.0)
    assert queue.pop_next(now=18.0) is None
    assert queue.stats.expired == 4
    assert queue.stats.expired_notifications_dropped == 2
    assert len(queue.expire(now=18.0)) == 2


def test_queued_ids_stay_deduped_even_when_recent_history_is_smaller_than_queue():
    queue = RoomCueQueue(RoomQueueConfig(max_items=4, dedupe_capacity=1))
    first, second = cue("queued-first"), cue("queued-second")
    assert queue.enqueue(first, queued(first), now=10.0) is RoomQueueResult.ADDED
    assert queue.enqueue(second, queued(second), now=10.0) is RoomQueueResult.ADDED
    assert queue.enqueue(first, queued(first), now=10.1) is RoomQueueResult.DUPLICATE


def test_default_queue_keeps_a_question_during_a_long_reply():
    queue = RoomCueQueue()
    item = cue("long-reply", ended_at=10.0)
    assert queue.enqueue(item, queued(item), now=10.0) is RoomQueueResult.ADDED
    assert queue.pop_next(now=30.0) == item
