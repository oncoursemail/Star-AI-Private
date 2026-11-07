"""Synthetic game-reaction provenance regressions: no media or stream I/O."""
import pytest

from star.stream_director import StreamDirector, StreamSignal


def director() -> StreamDirector:
    result = StreamDirector(gap_seconds=0)
    result.enable(owner_approved=True)
    return result


def win(ident: str, at: float, *, scope: str = "", evidence: str = "observed",
        detail: str = "Checkpoint reached") -> StreamSignal:
    return StreamSignal(
        ident, "game_success", at, detail,
        evidence=evidence, game_scope=scope,
    )


@pytest.mark.parametrize("unverified", ["reported", "unknown"])
def test_unverified_success_cannot_silence_later_observed_victory(unverified: str) -> None:
    stage = director()
    assert stage.offer(win("rumor", 10, evidence=unverified), now=10)
    rumor = stage.propose(now=10)
    assert rumor is not None and rumor.evidence == unverified
    assert stage.complete(rumor, now=10, spoken=True)

    # A spoken rumor is not a witnessed victory receipt. An actual game
    # observation must remain available to the speaking planner.
    assert stage.offer(win("truth", 11, evidence="observed"), now=11)
    truth = stage.propose(now=11)
    assert truth is not None and truth.signal_id == "truth"
    assert truth.evidence == "observed"


def test_confirmed_success_deduplicates_same_scope_repetitions() -> None:
    stage = director()
    assert stage.offer(win("first", 10, scope="gameA-level1"), now=10)
    assert stage.complete(stage.propose(now=10), now=10, spoken=True)
    assert not stage.offer(win("repeat", 11, scope="gameA-level1",
                               detail="CHECKPOINT  reached"), now=11)
    assert stage.metrics()["suppressed_reactions"] == 1


def test_identical_successes_in_different_games_are_distinct() -> None:
    stage = director()
    assert stage.offer(win("game-A", 10, scope="gameA-level1"), now=10)
    assert stage.complete(stage.propose(now=10), now=10, spoken=True)
    assert stage.offer(win("game-B", 11, scope="gameB-level1"), now=11)
    next_intent = stage.propose(now=11)
    assert next_intent is not None and next_intent.signal_id == "game-B"


def test_verified_reaction_only_prunes_queued_echoes_in_matching_scope() -> None:
    stage = director()
    assert stage.offer(win("one", 10, scope="arena-1"), now=10)
    assert stage.offer(win("echo", 10, scope="arena-1",
                           detail="  CHECKPOINT reached "), now=10)
    assert stage.offer(win("other", 10, scope="arena-2"), now=10)
    chosen = stage.propose(now=10)
    assert chosen is not None and chosen.signal_id in {"one", "echo", "other"}
    # Make the verified spoken receipt deterministic, whichever wins FIFO.
    assert chosen.signal_id == "echo" or chosen.signal_id == "one"
    assert stage.complete(chosen, now=10, spoken=True)
    other = stage.propose(now=10.1)
    assert other is not None and other.signal_id == "other"
    assert stage.metrics()["suppressed_reactions"] == 1


@pytest.mark.parametrize("invalid", ["bad/path", "trailing ", "x" * 81, 123, True])
def test_reject_invalid_game_scopes(invalid: object) -> None:
    with pytest.raises(ValueError, match="game_scope"):
        win("bad", 10, scope=invalid)  # type: ignore[arg-type]


def test_viewer_cannot_supply_fake_game_scope() -> None:
    with pytest.raises(ValueError, match="game_scope"):
        StreamSignal("q", "viewer_question", 10, "Hi!",
                     speaker_id="viewer-1", game_scope="gameA")


def test_empty_scope_keeps_existing_reaction_dedupe_contract() -> None:
    stage = director()
    assert stage.offer(win("first", 10), now=10)
    assert stage.complete(stage.propose(now=10), now=10, spoken=True)
    assert not stage.offer(win("repeat", 11), now=11)
