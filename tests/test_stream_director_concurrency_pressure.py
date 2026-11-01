"""Offline live-chat pressure and concurrency regression tests.

Synthetic clocks and fake events only: no Twitch, microphone, OBS, hardware,
LLM, game input or personal viewer identifiers.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from star.stream_director import StreamDirector, StreamSignal


def director(**kwargs: object) -> StreamDirector:
    stage = StreamDirector(gap_seconds=0, **kwargs)
    stage.enable(owner_approved=True)
    return stage


def chat(ident: str, *, speaker: str = "viewerA", at: float = 10.0) -> StreamSignal:
    return StreamSignal(
        ident, "viewer_question", at, f"Question {ident}?",
        speaker_id=speaker, evidence="reported",
    )


def test_simultaneous_duplicate_event_is_admitted_once() -> None:
    stage = director()
    barrier = Barrier(16)
    event = chat("same-message")

    def offer_once(_: int) -> bool:
        barrier.wait()
        return stage.offer(event, now=10.0)

    with ThreadPoolExecutor(max_workers=16) as pool:
        accepted = list(pool.map(offer_once, range(16)))
    assert sum(accepted) == 1
    assert stage.metrics()["queued"] == 1
    assert stage.metrics()["accepted"] == 1
    assert stage.metrics()["rejected"] == 15


def test_parallel_distinct_viewer_flood_cannot_bypass_pending_limit() -> None:
    stage = director(max_events=48, max_pending_per_viewer=2)
    barrier = Barrier(16)

    def offer_one(i: int) -> bool:
        barrier.wait()
        return stage.offer(chat(f"unique-{i}"), now=10.0)

    with ThreadPoolExecutor(max_workers=16) as pool:
        accepted = list(pool.map(offer_one, range(16)))
    assert sum(accepted) == 2
    assert stage.metrics()["queued"] == 2
    assert stage.metrics()["viewer_queue_limited"] == 14
    assert stage.offer(chat("other", speaker="viewerB"), now=10.0)


def test_parallel_acknowledgements_cannot_double_commit_speech() -> None:
    stage = director()
    assert stage.offer(chat("one"), now=10)
    intent = stage.propose(now=10)
    assert intent is not None
    barrier = Barrier(12)

    def finish_once(_: int) -> bool:
        barrier.wait()
        return stage.complete(intent, now=10.5, spoken=True)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(finish_once, range(12)))
    assert sum(results) == 1
    assert stage.metrics()["completed"] == 1
    assert stage.metrics()["queued"] == 0


def test_disable_interleaved_with_ack_never_leaves_speech_queued() -> None:
    stage = director()
    assert stage.offer(chat("one"), now=10)
    intent = stage.propose(now=10)
    assert intent is not None
    barrier = Barrier(2)

    def finish() -> bool:
        barrier.wait()
        return stage.complete(intent, now=10.1, spoken=True)

    def stop() -> None:
        barrier.wait()
        stage.disable()

    with ThreadPoolExecutor(max_workers=2) as pool:
        spoken = pool.submit(finish)
        disabled = pool.submit(stop)
        assert type(spoken.result()) is bool
        disabled.result()
    assert stage.metrics()["queued"] == 0
    assert stage.propose(now=10.2) is None
    assert not stage.enabled


def test_chat_dedupe_saturation_rejects_new_chatter_not_game_danger() -> None:
    stage = director()
    # Seed the *internal* bounded receipt cache to avoid thousands of unrelated
    # model-free chat iterations; all receipts are recent at this synthetic time.
    stage._recent.update({f"digest-{i}": 10.0 for i in range(4096)})
    assert not stage.offer(chat("new-unseen"), now=10)
    assert stage.metrics()["dedupe_capacity_rejected"] == 1
    assert stage.metrics()["queued"] == 0
    danger = StreamSignal(
        "game-danger", "game_danger", 10, "Host-observed projectile",
        evidence="observed",
    )
    assert stage.offer(danger, now=10)
    urgent = stage.propose(now=10, gameplay_critical=True)
    assert urgent is not None and urgent.signal_id == "game-danger"
    assert "digest-0" not in repr(stage.metrics())


def test_expiring_dedupe_entries_releases_capacity() -> None:
    stage = director()
    stage._recent.update({f"digest-{i}": 10.0 for i in range(4096)})
    assert not stage.offer(chat("blocked"), now=10)
    assert stage.offer(chat("after-expiry", at=51), now=51)
    assert len(stage._recent) == 1
    assert stage.metrics()["dedupe_capacity_rejected"] == 1


def test_many_distinct_spoken_viewers_cannot_grow_cooldown_cache() -> None:
    stage = director(viewer_cooldown=10**10)
    stage._viewer_last_spoken.update({f"old-viewer-{i}": 10.0 for i in range(4096)})
    assert stage.offer(chat("fresh", speaker="new-viewer"), now=10)
    intent = stage.propose(now=10)
    assert intent is not None
    assert stage.complete(intent, now=10, spoken=True)
    assert len(stage._viewer_last_spoken) == 4096
    assert "new-viewer" in stage._viewer_last_spoken


def test_many_distinct_verified_game_reactions_remain_bounded() -> None:
    stage = director(success_repeat_gap_seconds=10**10)
    stage._game_reactions.update({
        f"old-game-digest-{i}": (10.0, f"old-{i}") for i in range(4096)
    })
    event = StreamSignal(
        "win", "game_success", 10, "Observed unique win",
        evidence="observed", game_scope="verified-game",
    )
    assert stage.offer(event, now=10)
    intent = stage.propose(now=10)
    assert intent is not None and intent.kind == "game_success"
    assert stage.complete(intent, now=10, spoken=True)
    assert len(stage._game_reactions) == 4096
    stage.disable()
    assert len(stage._game_reactions) == 0
    assert len(stage._viewer_last_spoken) == 0
    assert len(stage._recent) == 0
