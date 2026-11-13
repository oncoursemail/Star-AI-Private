"""Tests for the bounded ephemeral room payload store."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace

import pytest

from star.voice.room import CueIntent, CueSource, RoomCue
from star.voice.room_payloads import (
    RoomPayload,
    RoomPayloadKind,
    RoomPayloadStore,
    RoomPayloadStoreConfig,
    RoomPayloadStoreResult,
)


def cue(event_id: str, *, source: CueSource = CueSource.CHAT, ended_at: float = 10.0) -> RoomCue:
    return RoomCue(
        event_id=event_id,
        speaker_id="speaker-opaque",
        source=source,
        intent=CueIntent.DIRECT_QUESTION,
        addressed_to_star=True,
        confidence=0.99,
        started_at=ended_at - 0.2,
        ended_at=ended_at,
    )


def test_store_and_take_is_destructive_and_preserves_source_kind():
    store = RoomPayloadStore()
    item = cue("chat-1")
    assert store.put(item, "hello STAR", now=10.0) is RoomPayloadStoreResult.STORED
    payload = store.take("chat-1", now=10.1)
    assert payload is not None
    assert payload.text == "hello STAR"
    assert payload.kind is RoomPayloadKind.CHAT_MESSAGE
    assert payload.cue == item
    assert store.take("chat-1", now=10.2) is None
    assert len(store) == 0
    assert store.stats.taken == 1
    assert store.stats.bytes_used == 0


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        (CueSource.AUDIO, RoomPayloadKind.TRANSCRIPT),
        (CueSource.CHAT, RoomPayloadKind.CHAT_MESSAGE),
        (CueSource.GAME, RoomPayloadKind.GAME_OBSERVATION),
    ],
)
def test_payload_kind_is_derived_from_cue_source(source, kind):
    store = RoomPayloadStore()
    item = cue(f"source-{source.value}", source=source)
    assert store.put(item, "short text", now=10.0) is RoomPayloadStoreResult.STORED
    payload = store.take(item.event_id, now=10.1)
    assert payload is not None
    assert payload.kind is kind


def test_utf8_byte_budget_counts_encoded_bytes():
    store = RoomPayloadStore(RoomPayloadStoreConfig(max_payload_bytes=8, max_total_bytes=16))
    item = cue("unicode")
    assert store.put(item, "café", now=10.0) is RoomPayloadStoreResult.STORED
    assert store.stats.bytes_used == 5
    assert store.take("unicode", now=10.1).text == "café"


def test_per_payload_limit_rejects_without_storing():
    store = RoomPayloadStore(RoomPayloadStoreConfig(max_payload_bytes=4, max_total_bytes=8))
    assert store.put(cue("large"), "12345", now=10.0) is RoomPayloadStoreResult.TOO_LARGE
    assert len(store) == 0
    assert store.stats.rejected_too_large == 1


def test_total_byte_limit_rejects_without_evicting_existing_payload():
    store = RoomPayloadStore(RoomPayloadStoreConfig(max_payload_bytes=8, max_total_bytes=8, max_items=4))
    first, second = cue("first"), cue("second")
    assert store.put(first, "123456", now=10.0) is RoomPayloadStoreResult.STORED
    assert store.put(second, "7890", now=10.0) is RoomPayloadStoreResult.FULL
    assert store.take("first", now=10.1).text == "123456"
    assert store.stats.rejected_full == 1


def test_expiry_uses_event_age_and_returns_ids_for_queue_reconciliation():
    store = RoomPayloadStore(RoomPayloadStoreConfig(max_age_seconds=2.0))
    item = cue("expires", ended_at=10.0)
    assert store.put(item, "old question", now=10.0) is RoomPayloadStoreResult.STORED
    assert store.expire(now=11.99) == ()
    assert store.expire(now=12.0) == ("expires",)
    assert store.take("expires", now=12.0) is None
    assert store.stats.expired == 1
    assert store.stats.bytes_used == 0


def test_stale_and_future_events_are_rejected():
    store = RoomPayloadStore(RoomPayloadStoreConfig(max_age_seconds=2.0))
    assert store.put(cue("stale", ended_at=5.0), "old", now=10.0) is RoomPayloadStoreResult.STALE
    assert store.put(cue("future", ended_at=11.0), "future", now=10.0) is RoomPayloadStoreResult.STALE
    assert len(store) == 0
    assert store.stats.rejected_stale == 2


def test_partial_cues_are_not_stored():
    store = RoomPayloadStore()
    partial = replace(cue("partial"), final=False)
    assert store.put(partial, "unfinished words", now=10.0) is RoomPayloadStoreResult.NOT_FINAL
    assert len(store) == 0
    assert store.stats.rejected_non_final == 1


def test_duplicate_event_is_rejected_while_pending_and_after_take():
    store = RoomPayloadStore()
    item = cue("duplicate")
    assert store.put(item, "first", now=10.0) is RoomPayloadStoreResult.STORED
    assert store.put(item, "second", now=10.1) is RoomPayloadStoreResult.DUPLICATE
    assert store.take("duplicate", now=10.2).text == "first"
    assert store.put(item, "third", now=10.3) is RoomPayloadStoreResult.DUPLICATE
    assert store.stats.duplicates == 2


def test_delete_removes_and_best_effort_wipes_mutable_buffer():
    store = RoomPayloadStore()
    item = cue("delete")
    assert store.put(item, "sensitive viewer text", now=10.0) is RoomPayloadStoreResult.STORED
    buffer = store._items["delete"].data
    assert buffer
    assert store.delete("delete")
    assert buffer == bytearray()
    assert store.stats.deleted == 1
    assert store.stats.bytes_used == 0


def test_reset_wipes_all_pending_payloads_and_counters():
    store = RoomPayloadStore()
    store.put(cue("one"), "first", now=10.0)
    store.put(cue("two"), "second", now=10.0)
    buffers = [entry.data for entry in store._items.values()]
    store.reset()
    assert all(buffer == bytearray() for buffer in buffers)
    assert len(store) == 0
    assert store.stats.bytes_used == 0
    assert store.stats.accepted == 0


def test_expiry_wipes_mutable_buffer():
    store = RoomPayloadStore(RoomPayloadStoreConfig(max_age_seconds=1.0))
    store.put(cue("expire-buffer"), "temporary", now=10.0)
    buffer = store._items["expire-buffer"].data
    assert store.expire(now=11.0) == ("expire-buffer",)
    assert buffer == bytearray()


def test_empty_text_and_invalid_text_types_are_rejected():
    store = RoomPayloadStore()
    with pytest.raises(ValueError, match="must not be empty"):
        store.put(cue("empty"), "  ", now=10.0)
    with pytest.raises(TypeError, match="string"):
        store.put(cue("not-string"), b"bytes", now=10.0)


def test_invalid_utf8_surrogates_are_rejected():
    store = RoomPayloadStore()
    with pytest.raises(ValueError, match="valid UTF-8"):
        store.put(cue("surrogate"), "\ud800", now=10.0)


def test_invalid_cue_numbers_and_monotonic_clock_are_rejected():
    store = RoomPayloadStore()
    with pytest.raises(ValueError, match="finite"):
        store.put(replace(cue("nan"), confidence=float("nan")), "x", now=10.0)
    with pytest.raises(ValueError, match="finite"):
        store.put(cue("bad-clock"), "x", now=float("nan"))


def test_invalid_event_ids_are_rejected():
    store = RoomPayloadStore()
    with pytest.raises(ValueError, match="event_id"):
        store.take("", now=10.0)
    with pytest.raises(ValueError, match="event_id"):
        store.delete("x" * 129)


def test_session_reset_allows_new_session_to_reuse_event_id():
    store = RoomPayloadStore()
    item = cue("same-id")
    assert store.put(item, "first", now=10.0) is RoomPayloadStoreResult.STORED
    store.reset()
    assert store.put(item, "second", now=10.1) is RoomPayloadStoreResult.STORED


def test_concurrent_duplicate_put_has_exactly_one_winner():
    store = RoomPayloadStore()
    item = cue("race")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.put(item, "same payload", now=10.0), range(32)))
    assert results.count(RoomPayloadStoreResult.STORED) == 1
    assert results.count(RoomPayloadStoreResult.DUPLICATE) == 31
    assert len(store) == 1


def test_payload_result_does_not_contain_raw_audio_or_voiceprint_fields():
    assert {field.name for field in fields(RoomPayload)} == {"cue", "kind", "text", "received_at"}
    assert "audio" not in RoomPayload.__dataclass_fields__
    assert "embedding" not in RoomPayload.__dataclass_fields__


def test_item_limit_rejects_without_evicting_existing_payload():
    store = RoomPayloadStore(RoomPayloadStoreConfig(max_items=1, max_payload_bytes=32, max_total_bytes=64))
    first, second = cue("item-first"), cue("item-second")
    assert store.put(first, "first", now=10.0) is RoomPayloadStoreResult.STORED
    assert store.put(second, "second", now=10.0) is RoomPayloadStoreResult.FULL
    assert store.take("item-first", now=10.1).text == "first"
    assert store.stats.rejected_full == 1


def test_take_after_deadline_expires_and_wipes_without_returning_content():
    store = RoomPayloadStore(RoomPayloadStoreConfig(max_age_seconds=1.0))
    item = cue("take-expired")
    assert store.put(item, "must not be returned", now=10.0) is RoomPayloadStoreResult.STORED
    buffer = store._items[item.event_id].data
    assert store.take(item.event_id, now=11.0) is None
    assert buffer == bytearray()
    assert store.stats.expired == 1
    assert store.stats.bytes_used == 0


def test_default_payload_store_keeps_a_question_during_a_long_reply():
    store = RoomPayloadStore()
    item = cue("long-reply", ended_at=10.0)
    assert store.put(item, "question while STAR is speaking", now=10.0) is RoomPayloadStoreResult.STORED
    payload = store.take(item.event_id, now=30.0)
    assert payload is not None
    assert payload.text == "question while STAR is speaking"
