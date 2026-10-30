"""Offline regression tests: host identity and event-time truth in VTuber speech.

These use synthetic clock-controlled signals only: no chat accounts, hardware,
microphone, gameplay, TTS, network service or broadcast are accessed.
"""
import pytest

from star.stream_director import StreamDirector, StreamSignal


def director() -> StreamDirector:
    result = StreamDirector()
    result.enable(owner_approved=True)
    return result


def question(ident: str, speaker: str, *, at: float = 10.0,
             detail: str = "How did you jump?") -> StreamSignal:
    return StreamSignal(
        ident, "viewer_question", at, detail,
        speaker_id=speaker, evidence="reported",
    )


@pytest.mark.parametrize("speaker", [
    "", " ", "viewerA ", " viewerA", "viewer\tA",
    "viewer\u0430", "viewer\x00", "user/name",
])
def test_direct_chat_path_rejects_missing_or_noncanonical_speaker(speaker: str) -> None:
    stage = director()
    assert not stage.offer(question("q1", speaker), now=10.0)
    assert stage.propose(now=10.0) is None
    assert stage.metrics()["queued"] == 0
    assert stage.metrics()["rejected"] == 1


def test_oversized_speaker_is_rejected_at_signal_construction() -> None:
    # Length-invalid input cannot become a StreamSignal; admission is never called.
    with pytest.raises(ValueError, match="invalid speaker identifier"):
        question("oversized", "x" * 81)


def test_direct_chat_fairness_cannot_be_bypassed_by_renamed_event_ids() -> None:
    stage = director()
    assert stage.offer(question("first", "account-123"), now=10.0)
    first = stage.propose(now=10.0)
    assert first is not None and first.signal_id == "first"
    assert stage.complete(first, now=10.0, spoken=True)

    # A different event ID and new text do not reset per-viewer cooldown.
    assert stage.offer(question(
        "same-person", "account-123", at=13.0, detail="Any tips?"
    ), now=13.0)
    assert stage.propose(now=13.0) is None

    # Another authenticated, stable account can receive a turn.
    assert stage.offer(question(
        "other-person", "account-456", at=13.0, detail="Which map?"
    ), now=13.0)
    second = stage.propose(now=13.0)
    assert second is not None and second.signal_id == "other-person"
    assert stage.complete(second, now=13.0, spoken=True)


def test_viewer_comments_have_same_identity_requirement() -> None:
    stage = director()
    for ident, speaker in (("anon", ""), ("aliased", "viewerA ")):
        assert not stage.offer(StreamSignal(
            ident, "viewer_comment", 10.0, "Amazing game!",
            speaker_id=speaker, evidence="reported",
        ), now=10.0)
    assert stage.metrics()["queued"] == 0


def test_nonviewer_game_events_do_not_need_viewer_account_ids() -> None:
    stage = director()
    assert stage.offer(StreamSignal(
        "danger", "game_danger", 10.0, "Enemy projectile visible",
        evidence="observed",
    ), now=10.0)
    intent = stage.propose(now=10.0, gameplay_critical=True)
    assert intent is not None and intent.signal_id == "danger"


def test_small_clock_skew_is_accepted_but_never_narrated_early() -> None:
    stage = director()
    # The ingress layer intentionally tolerates <=500 ms positive skew.
    assert stage.offer(StreamSignal(
        "future", "game_success", 10.4, "Checkpoint reached",
        evidence="observed",
    ), now=10.0)
    assert stage.propose(now=10.0) is None
    assert stage.propose(now=10.39) is None
    intent = stage.propose(now=10.4)
    assert intent is not None and intent.signal_id == "future"
    assert stage.complete(intent, now=10.4, spoken=True)
    assert stage.metrics()["completed"] == 1


def test_future_owner_interrupt_does_not_preempt_before_timestamp() -> None:
    stage = director()
    assert stage.offer(StreamSignal(
        "stop", "owner_interrupt", 100.4, "Pause please",
        evidence="reported",
    ), now=100.0)
    assert stage.propose(now=100.2, voice_speaking=True) is None
    intent = stage.propose(now=100.4, voice_speaking=True)
    assert intent is not None and intent.interrupt_current


def test_more_than_half_second_future_is_still_rejected() -> None:
    stage = director()
    assert not stage.offer(StreamSignal(
        "far-future", "game_observation", 11.0, "Some background",
        evidence="observed",
    ), now=10.0)
    assert stage.metrics()["rejected"] == 1
