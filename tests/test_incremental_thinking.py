from __future__ import annotations

import pytest

from star.voice.incremental_thinking import (
    IncrementalThinkCoordinator,
    PartialHypothesis,
    ThinkAction,
)


def hypothesis(
    sequence: int,
    text: str,
    *,
    utterance_id: str = "turn-1",
    captured_ms: float | None = None,
    confidence: float = 0.95,
    semantic: float = 0.95,
    final: bool = False,
) -> PartialHypothesis:
    return PartialHypothesis(
        utterance_id=utterance_id,
        sequence=sequence,
        captured_ms=float(1000 + sequence * 100 if captured_ms is None else captured_ms),
        text=text,
        asr_confidence=confidence,
        semantic_score=semantic,
        final=final,
    )


def start_thinker(coordinator: IncrementalThinkCoordinator) -> None:
    first = coordinator.observe(
        hypothesis(0, "I want to build a small game"),
        now_ms=1000,
    )
    assert first.action is ThinkAction.WAIT
    second = coordinator.observe(
        hypothesis(1, "I want to build a small game in Roblox"),
        now_ms=1100,
    )
    assert second.action is ThinkAction.START
    assert second.stable_prefix == "I want to build a small game"
    assert second.may_speak is False
    assert second.may_execute_tools is False


def test_requires_two_hypotheses_and_stable_semantic_prefix() -> None:
    coordinator = IncrementalThinkCoordinator()
    first = coordinator.observe(
        hypothesis(0, "I want to build a small game"),
        now_ms=1000,
    )
    assert first.action is ThinkAction.WAIT
    assert coordinator.metrics()["thinking"] is False

    second = coordinator.observe(
        hypothesis(1, "I want to build a small game in Roblox"),
        now_ms=1100,
    )
    assert second.action is ThinkAction.START
    assert second.stable_prefix == "I want to build a small game"


def test_low_semantic_confidence_does_not_start_thinker() -> None:
    coordinator = IncrementalThinkCoordinator()
    coordinator.observe(
        hypothesis(0, "Can you help me with this"),
        now_ms=1000,
    )
    result = coordinator.observe(
        hypothesis(1, "Can you help me with this project", semantic=0.2),
        now_ms=1100,
    )
    assert result.action is ThinkAction.WAIT
    assert coordinator.metrics()["thinking"] is False


def test_stable_prefix_extension_updates_existing_thinker() -> None:
    coordinator = IncrementalThinkCoordinator()
    start_thinker(coordinator)
    result = coordinator.observe(
        hypothesis(2, "I want to build a small game in Roblox with friends"),
        now_ms=1200,
    )
    assert result.action is ThinkAction.UPDATE
    assert result.stable_prefix == "I want to build a small game in Roblox"
    assert result.cancel_previous is False


def test_asr_revision_cancels_old_thinker_before_new_revision() -> None:
    coordinator = IncrementalThinkCoordinator()
    start_thinker(coordinator)
    revised = coordinator.observe(
        hypothesis(2, "I want to build a new game in Roblox"),
        now_ms=1200,
    )
    assert revised.action is ThinkAction.CANCEL
    assert revised.cancel_previous is True
    assert revised.reason == "asr_revision_invalidated_prefix"
    assert coordinator.metrics()["thinking"] is False

    restarted = coordinator.observe(
        hypothesis(3, "I want to build a new game in Roblox with friends"),
        now_ms=1300,
    )
    assert restarted.action is ThinkAction.START
    assert restarted.revision == 1


def test_final_hypothesis_is_the_only_canonical_commit() -> None:
    coordinator = IncrementalThinkCoordinator()
    start_thinker(coordinator)
    final = coordinator.observe(
        hypothesis(
            2,
            "I want to build a small game in Roblox.",
            captured_ms=1200,
            final=True,
        ),
        now_ms=1200,
    )
    assert final.action is ThinkAction.FINALIZE
    assert final.commit_final is True
    assert final.final_text == "I want to build a small game in Roblox."
    assert final.may_speak is False
    assert final.may_execute_tools is False
    assert coordinator.metrics()["active"] is False


def test_partial_directives_never_grant_speech_or_tool_authority() -> None:
    coordinator = IncrementalThinkCoordinator()
    coordinator.observe(hypothesis(0, "I want to build a small game"), now_ms=1000)
    result = coordinator.observe(
        hypothesis(1, "I want to build a small game in Roblox"),
        now_ms=1100,
    )
    assert result.action is ThinkAction.START
    assert result.may_speak is False
    assert result.may_execute_tools is False


def test_duplicate_and_out_of_order_hypotheses_are_rejected() -> None:
    coordinator = IncrementalThinkCoordinator()
    coordinator.observe(hypothesis(0, "I want to build a small game"), now_ms=1000)
    coordinator.observe(hypothesis(1, "I want to build a small game in Roblox"), now_ms=1100)
    duplicate = coordinator.observe(
        hypothesis(1, "I want to build a small game in Roblox"),
        now_ms=1100,
    )
    assert duplicate.action is ThinkAction.REJECT
    assert duplicate.reason == "out_of_order_hypothesis"
    assert coordinator.metrics()["thinking"] is True


def test_future_hypothesis_is_rejected_without_mutating_state() -> None:
    coordinator = IncrementalThinkCoordinator()
    result = coordinator.observe(
        hypothesis(0, "hello", captured_ms=1200),
        now_ms=1100,
    )
    assert result.action is ThinkAction.REJECT
    assert result.reason == "future_hypothesis"
    assert coordinator.metrics()["active"] is False


def test_stale_hypothesis_cancels_only_its_active_thinker() -> None:
    coordinator = IncrementalThinkCoordinator(max_partial_age_ms=500)
    coordinator.observe(
        hypothesis(0, "I want to build a small game", captured_ms=1000),
        now_ms=1000,
    )
    coordinator.observe(
        hypothesis(1, "I want to build a small game in Roblox", captured_ms=1100),
        now_ms=1100,
    )
    result = coordinator.observe(
        hypothesis(2, "I want to build a small game in Roblox today", captured_ms=1200),
        now_ms=2000,
    )
    assert result.action is ThinkAction.CANCEL
    assert result.cancel_previous is True
    assert result.reason == "stale_hypothesis"
    assert coordinator.metrics()["active"] is False


def test_new_utterance_cancels_previous_thinker_and_starts_fresh_state() -> None:
    coordinator = IncrementalThinkCoordinator()
    start_thinker(coordinator)
    result = coordinator.observe(
        hypothesis(0, "Can you help me", utterance_id="turn-2", captured_ms=1200),
        now_ms=1200,
    )
    assert result.action is ThinkAction.CANCEL
    assert result.cancel_previous is True
    assert coordinator.metrics()["active"] is True
    assert coordinator.metrics()["thinking"] is False


def test_cancel_requires_active_utterance_and_known_reason() -> None:
    coordinator = IncrementalThinkCoordinator()
    start_thinker(coordinator)
    result = coordinator.cancel("turn-1", reason="barge_in")
    assert result.action is ThinkAction.CANCEL
    assert result.cancel_previous is True
    assert coordinator.metrics()["active"] is False

    missing = coordinator.cancel("turn-1", reason="barge_in")
    assert missing.action is ThinkAction.REJECT
    with pytest.raises(ValueError):
        coordinator.cancel("turn-1", reason="freeform")


def test_expire_cancels_stale_background_work() -> None:
    coordinator = IncrementalThinkCoordinator(max_partial_age_ms=500)
    coordinator.observe(
        hypothesis(0, "I want to build a small game", captured_ms=1000),
        now_ms=1000,
    )
    coordinator.observe(
        hypothesis(1, "I want to build a small game in Roblox", captured_ms=1100),
        now_ms=1100,
    )
    result = coordinator.expire(now_ms=1700)
    assert result is not None
    assert result.action is ThinkAction.CANCEL
    assert result.cancel_previous is True
    assert coordinator.metrics()["active"] is False


def test_empty_final_cancels_speculation_without_committing() -> None:
    coordinator = IncrementalThinkCoordinator()
    start_thinker(coordinator)
    result = coordinator.observe(
        hypothesis(2, "   ", captured_ms=1200, final=True),
        now_ms=1200,
    )
    assert result.action is ThinkAction.CANCEL
    assert result.commit_final is False
    assert result.cancel_previous is True


def test_closed_utterance_id_cannot_be_replayed() -> None:
    coordinator = IncrementalThinkCoordinator()
    coordinator.observe(
        hypothesis(0, "hello there", captured_ms=1000, final=True),
        now_ms=1000,
    )
    replay = coordinator.observe(
        hypothesis(1, "hello there again", captured_ms=1100),
        now_ms=1100,
    )
    assert replay.action is ThinkAction.REJECT
    assert replay.reason == "utterance_replay"


def test_metrics_are_aggregate_and_content_free() -> None:
    coordinator = IncrementalThinkCoordinator()
    start_thinker(coordinator)
    metrics = coordinator.metrics()
    assert metrics["started"] == 1
    assert metrics["thinking"] is True
    assert "text" not in metrics
    assert "stable_prefix" not in metrics
    assert "utterance_id" not in metrics


def test_input_validation_rejects_bool_confidence_and_oversized_text() -> None:
    with pytest.raises(ValueError):
        hypothesis(0, "hello", confidence=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        hypothesis(0, "x" * 4097)
    with pytest.raises(ValueError):
        PartialHypothesis(
            utterance_id="bad id",
            sequence=0,
            captured_ms=1000,
            text="hello",
            asr_confidence=0.9,
            semantic_score=0.9,
        )


def test_replay_guard_capacity_fails_closed() -> None:
    coordinator = IncrementalThinkCoordinator(max_seen_utterances=1)
    first = coordinator.observe(
        hypothesis(0, "hello there", utterance_id="turn-1", captured_ms=1000, final=True),
        now_ms=1000,
    )
    assert first.action is ThinkAction.FINALIZE
    second = coordinator.observe(
        hypothesis(0, "hello there", utterance_id="turn-2", captured_ms=1100),
        now_ms=1100,
    )
    assert second.action is ThinkAction.REJECT
    assert second.reason == "replay_guard_capacity"
