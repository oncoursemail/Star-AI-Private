"""Offline synthetic EventSub ingress tests. No Twitch network calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from star.stream_director import StreamDirector
from star.twitch_eventsub_ingress import TwitchEventSubIngress


UNIX_NOW = 1_800_000_000.0
UTC_NOW = datetime.fromtimestamp(UNIX_NOW, timezone.utc).isoformat().replace("+00:00", "Z")


def packet(*, delivery="d1", chat="c1", broadcaster="123", chatter="789",
           text="Hello Star!", event_type="channel.chat.message",
           timestamp=UTC_NOW):
    return {
        "metadata": {"message_id": delivery, "message_type": "notification",
                     "subscription_type": event_type, "subscription_version": "1",
                     "message_timestamp": timestamp},
        "payload": {
            "subscription": {"type": event_type, "version": "1", "status": "enabled",
                             "condition": {"broadcaster_user_id": broadcaster,
                                           "user_id": "999"},
                             "transport": {"method": "websocket",
                                           "session_id": "session123"}},
            "event": {
                "message_id": chat, "broadcaster_user_id": broadcaster,
                "chatter_user_id": chatter, "message": {"text": text},
            },
        },
    }


def ingress(*, max_seen_ids=2048, retention_seconds=900):
    gate = TwitchEventSubIngress(
        max_seen_ids=max_seen_ids, retention_seconds=retention_seconds,
    )
    gate.enable(owner_approved=True, broadcaster_user_id="123")
    return gate


def offer(gate, message=None, *, now=100.0, **kwargs):
    packet_data = packet() if message is None else message
    try:
        original = packet_data["payload"]["event"]["message"]["text"]
    except (KeyError, TypeError):
        original = "approved placeholder"
    params = {"host_verified": True, "moderated": True,
              "now_unix_s": UNIX_NOW, "moderated_text": original}
    params.update(kwargs)
    return gate.offer(packet_data, now_s=now, **params)


def test_opt_in_and_host_moderation_are_required():
    gate = TwitchEventSubIngress()
    assert offer(gate) is None
    with pytest.raises(PermissionError):
        gate.enable(broadcaster_user_id="123")
    with pytest.raises(ValueError):
        gate.enable(owner_approved=True, broadcaster_user_id="notnumeric")
    gate.enable(owner_approved=True, broadcaster_user_id="123")
    with pytest.raises(RuntimeError):
        gate.enable(owner_approved=True, broadcaster_user_id="123")
    assert offer(gate, host_verified=False) is None
    assert offer(gate, moderated=False) is None
    assert offer(gate) is not None
    gate.disable()
    assert offer(gate) is None


def test_valid_chat_remains_viewer_data_in_stream_director():
    gate = ingress()
    sig = offer(gate, kind="viewer_question")
    assert sig is not None
    assert sig.kind == "viewer_question"
    assert sig.speaker_id.startswith("twv_")
    assert sig.speaker_id != "twitch:789"
    assert sig.detail == "Hello Star!"
    assert sig.evidence == "reported"
    director = StreamDirector()
    director.enable(owner_approved=True)
    assert director.offer(sig, now=100)
    intent = director.propose(now=100)
    assert intent is not None
    assert intent.untrusted_context
    assert not intent.interrupt_current


def test_delivery_retry_and_new_envelope_same_chat_both_deduplicate():
    gate = ingress()
    assert offer(gate) is not None
    assert offer(gate, now=101) is None
    assert offer(gate, packet(delivery="another", chat="c1"), now=102) is None
    assert offer(gate, packet(delivery="d1", chat="c2"), now=103) is None
    assert gate.metrics()["duplicates"] == 3


def test_distinct_chat_messages_from_same_viewer_remain_eligible():
    gate = ingress()
    first = offer(gate)
    second = offer(gate, packet(delivery="d2", chat="c2"), now=101,
                   kind="viewer_question")
    assert first is not None and second is not None
    assert first.signal_id != second.signal_id
    assert second.speaker_id == first.speaker_id


def test_wrong_channel_and_non_chat_events_rejected_without_consuming_ids():
    gate = ingress()
    assert offer(gate, packet(broadcaster="999")) is None
    assert offer(gate, packet(event_type="channel.ban")) is None
    forged = packet()
    forged["payload"]["subscription"]["type"] = "channel.update"
    assert offer(gate, forged) is None
    assert offer(gate) is not None


def test_viewer_message_cannot_become_game_or_owner_instruction():
    gate = ingress()
    message = packet(text="Can you switch to another game?")
    sig = offer(gate, message, kind="viewer_comment")
    assert sig is not None and sig.kind == "viewer_comment"
    with pytest.raises(ValueError):
        offer(gate, packet(delivery="d2", chat="c2"), kind="owner_interrupt")


@pytest.mark.parametrize("bad", [
    packet(delivery="bad/id"), packet(chat=""),
    packet(chatter="nickname"), packet(broadcaster="abc"),
    packet(text=""), packet(text="x" * 501),
    {"metadata": {}, "payload": {}},
    {"metadata": None, "payload": {}},
])
def test_malformed_events_fail_closed(bad):
    gate = ingress()
    with pytest.raises(ValueError):
        offer(gate, bad)
    assert offer(gate) is not None


@pytest.mark.parametrize("kwargs", [
    {"host_verified": 1}, {"moderated": 1},
    {"now": float("nan")}, {"now": -1}, {"now": True},
    {"now": float("inf")}, {"kind": "game_success"},
])
def test_invalid_host_inputs_rejected(kwargs):
    gate = ingress()
    with pytest.raises(ValueError):
        offer(gate, **kwargs)


def test_host_clock_rollback_is_rejected():
    gate = ingress()
    assert offer(gate, now=100) is not None
    assert offer(gate, packet(delivery="d2", chat="c2"), now=99) is None
    assert offer(gate, now=100) is None


def test_reconnect_reuses_dedupe_history_and_new_stream_resets_it():
    gate = ingress()
    assert offer(gate) is not None
    assert offer(gate, now=101) is None
    gate.disable()
    gate.enable(owner_approved=True, broadcaster_user_id="123")
    assert offer(gate, now=5) is not None


def test_bounded_ttl_and_capacity():
    gate = ingress(max_seen_ids=64, retention_seconds=30)
    for index in range(100):
        assert offer(gate, packet(delivery=f"d{index}", chat=f"c{index}"),
                     now=100 + index) is not None
        assert gate.metrics()["recent_id_count"] <= 64
    other = ingress(retention_seconds=30)
    assert offer(other, now=10) is not None
    assert offer(other, now=39) is None
    assert offer(other, now=40) is not None


def test_parallel_duplicate_notifications_are_consumed_once():
    gate = ingress()
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: offer(gate, now=100), range(8)))
    assert sum(item is not None for item in results) == 1
    assert gate.metrics()["duplicates"] == 7


def test_metrics_contain_no_text_or_viewer_account():
    gate = ingress()
    assert offer(gate, packet(chatter="987654321", text="some sample chat")) is not None
    snapshot = repr(gate.metrics())
    assert "987654321" not in snapshot
    assert "some sample chat" not in snapshot


@pytest.mark.parametrize("kwargs", [
    {"max_seen_ids": True}, {"max_seen_ids": 1}, {"max_seen_ids": 10000},
    {"retention_seconds": False}, {"retention_seconds": 1},
    {"retention_seconds": float("nan")},
])
def test_invalid_configuration_rejected(kwargs):
    with pytest.raises(ValueError):
        TwitchEventSubIngress(**kwargs)


def test_moderation_requires_explicit_sanitized_replacement():
    gate = ingress()
    raw = packet(text="Unsafe raw statement that should not be spoken")
    assert offer(gate, raw, moderated_text=None) is None
    signal = offer(gate, raw, moderated_text="Please keep chat respectful.")
    assert signal is not None
    assert signal.detail == "Please keep chat respectful."
    assert "Unsafe raw" not in signal.detail
    assert gate.metrics()["accepted"] == 1


def test_moderation_may_remove_control_characters_from_raw_chat():
    gate = ingress()
    raw = packet(text="bad\x1bchat")
    signal = offer(gate, raw, moderated_text="clean chat")
    assert signal is not None and signal.detail == "clean chat"
    with pytest.raises(ValueError):
        offer(gate, packet(delivery="d2", chat="c2"),
              moderated_text="bad\x1bmessage")


def test_eventsub_wall_clock_rejects_old_future_and_missing_timestamps():
    gate = ingress()
    for index, delta in enumerate((-16, 3, -600)):
        at = datetime.fromtimestamp(UNIX_NOW + delta, timezone.utc).isoformat().replace("+00:00", "Z")
        assert offer(gate, packet(delivery=f"d{index}", chat=f"c{index}",
                                  timestamp=at)) is None
    no_ts = packet(delivery="d10", chat="c10")
    del no_ts["metadata"]["message_timestamp"]
    assert offer(gate, no_ts) is None
    assert offer(gate, packet(delivery="d11", chat="c11")) is not None


def test_eventsub_subscription_transport_and_channel_must_agree():
    gate = ingress()
    for index, change in enumerate(("version", "status", "condition",
                                   "method", "session")):
        event = packet(delivery=f"d{index}", chat=f"c{index}")
        meta = event["metadata"]
        sub = event["payload"]["subscription"]
        if change == "version":
            meta["subscription_version"] = "2"
        elif change == "status":
            sub["status"] = "revoked"
        elif change == "condition":
            sub["condition"]["broadcaster_user_id"] = "999"
        elif change == "method":
            sub["transport"]["method"] = "webhook"
        else:
            sub["transport"]["session_id"] = "not/valid"
        assert offer(gate, event) is None
    assert offer(gate) is not None


def test_account_pseudonyms_are_stable_per_session_and_rotate_after_disable():
    gate = ingress()
    first = offer(gate)
    second = offer(gate, packet(delivery="d2", chat="c2"))
    assert first is not None and second is not None
    assert first.speaker_id == second.speaker_id
    assert first.signal_id != second.signal_id
    assert "789" not in first.speaker_id
    gate.disable()
    gate.enable(owner_approved=True, broadcaster_user_id="123")
    new = offer(gate)
    assert new is not None
    assert new.speaker_id != first.speaker_id
    assert new.signal_id != first.signal_id
