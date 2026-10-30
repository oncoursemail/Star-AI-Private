"""Deterministic, offline receipts: only the actual issued speech plan may be acknowledged.

No TTS, OBS, game input, microphones, accounts or external services.
"""
from dataclasses import replace

from star.stream_director import SpeechIntent, StreamDirector, StreamSignal


def director(*, max_events: int = 48) -> StreamDirector:
    stage = StreamDirector(max_events=max_events, gap_seconds=0)
    stage.enable(owner_approved=True)
    return stage


def observation(ident: str = "moment", *, at: float = 10) -> StreamSignal:
    return StreamSignal(
        ident, "game_success", at, "Verified checkpoint",
        evidence="observed", game_scope="private-level-a",
    )


def test_identical_forged_intent_cannot_consume_real_playback_receipt() -> None:
    stage = director()
    assert stage.offer(observation(), now=10)
    issued = stage.propose(now=10)
    assert issued is not None
    copied = replace(issued)
    assert copied == issued and copied is not issued
    assert not stage.complete(copied, now=10, spoken=True)
    assert stage.metrics()["completed"] == 0
    assert stage.metrics()["queued"] == 1
    # A real successful acknowledgement still records the actual reaction.
    assert stage.complete(issued, now=10, spoken=True)
    assert stage.metrics()["completed"] == 1
    assert not stage.offer(observation("echo", at=11), now=11)


def test_not_proposed_intent_cannot_be_acked_even_with_matching_session_serial() -> None:
    stage = director()
    assert stage.offer(observation(), now=10)
    # Fields are guessable: a copied value is not evidence of an actual proposal.
    unissued = SpeechIntent(
        "moment", "game_success", "Verified checkpoint", "observed",
        17.0, "made up", False, False, session_epoch=1, event_serial=1,
    )
    assert not stage.complete(unissued, now=10, spoken=True)
    assert stage.metrics()["queued"] == 1
    assert stage.metrics()["completed"] == 0


def test_latest_proposal_supersedes_previous_intent_for_same_event() -> None:
    stage = director()
    assert stage.offer(observation(), now=10)
    old = stage.propose(now=10)
    latest = stage.propose(now=10)
    assert old is not None and latest is not None
    assert old is not latest
    assert not stage.complete(old, now=10, spoken=True)
    assert stage.complete(latest, now=10, spoken=True)
    assert not stage.complete(latest, now=10, spoken=True)
    assert stage.metrics()["queued"] == 0


def test_expiration_discards_issued_receipt() -> None:
    stage = director()
    danger = StreamSignal("fire", "game_danger", 10, "Hazard observed", evidence="observed")
    assert stage.offer(danger, now=10)
    intent = stage.propose(now=10)
    assert intent is not None
    assert stage.propose(now=13) is None  # 2.5s TTL elapsed
    assert not stage.complete(intent, now=13, spoken=True)
    assert stage._issued_intents == {}
    assert stage.metrics()["expired"] == 1


def test_priority_eviction_revokes_old_receipt_without_blocking_urgent_event() -> None:
    stage = director(max_events=1)
    assert stage.offer(StreamSignal("idle", "ambient", 10, "Nice lighting"), now=10)
    old = stage.propose(now=10)
    assert old is not None
    assert stage.offer(StreamSignal("stop", "owner_interrupt", 10, "Please stop"), now=10)
    assert not stage.complete(old, now=10, spoken=True)
    urgent = stage.propose(now=10)
    assert urgent is not None and urgent.signal_id == "stop"
    assert stage.complete(urgent, now=10, spoken=True)
    assert stage.metrics()["evicted"] == 1


def test_disable_revokes_receipts_across_restarted_session() -> None:
    stage = director()
    assert stage.offer(observation(), now=10)
    issued = stage.propose(now=10)
    assert issued is not None
    stage.disable()
    stage.enable(owner_approved=True)
    assert stage.offer(observation("fresh", at=11), now=11)
    assert not stage.complete(issued, now=11, spoken=True)
    fresh = stage.propose(now=11)
    assert fresh is not None
    assert stage.complete(fresh, now=11, spoken=False)
    assert stage.metrics()["abandoned"] == 1
    assert stage.metrics()["completed"] == 0
    assert stage.metrics()["queued"] == 0


def test_issued_receipts_remain_bounded_by_queued_events() -> None:
    stage = director(max_events=2)
    for n in range(10):
        now = float(10 + 40 * n)
        event = StreamSignal(
            f"q{n}", "viewer_question", now,
            f"Question {n}", speaker_id=f"viewer{n}",
        )
        assert stage.offer(event, now=now)
        assert stage.propose(now=now) is not None
        # Prior offers have aged out; obsolete proposals are not retained.
        assert len(stage._issued_intents) <= stage.max_events
    assert len(stage._issued_intents) == 1
    stage.disable()
    assert stage._issued_intents == {}
