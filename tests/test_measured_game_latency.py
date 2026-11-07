"""Fail-closed tests for local timing trace -> private synthetic replay."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from star.measured_game_latency import (
    LocalFrameTiming, prepare_private_latency_replay,
)
from star.signed_maze_lab import MazeScenario, run_signed_maze_trial


def frame(
    sequence: int = 1, *, capture: int = 1_000_000_000,
    infer: int = 20_000_000, gate: int = 10_000_000,
    ack: int = 10_000_000,
) -> LocalFrameTiming:
    return LocalFrameTiming(
        sequence, capture, capture + infer,
        capture + infer + gate, capture + infer + gate + ack,
    )


def test_convert_real_host_intervals_to_conservative_world_ticks() -> None:
    captures = (
        frame(1, capture=1_000_000_000, infer=20_000_000, ack=10_000_000),
        frame(2, capture=1_100_000_000, infer=80_000_000, ack=50_000_000),
        frame(3, capture=1_300_000_000, infer=10_000_000, ack=10_000_000),
    )
    plan = prepare_private_latency_replay(
        captures, owner_approved=True, tick_ns=100_000_000,
    )
    assert plan.decision_delay_schedule == (1, 2, 1)
    assert plan.capture_count == 3
    assert plan.inference_p95_ns == 80_000_000
    assert plan.gate_p95_ns == 10_000_000
    assert plan.action_ack_p95_ns == 50_000_000
    assert plan.end_to_end_p95_ns == 140_000_000
    assert plan.end_to_end_max_ns == 140_000_000
    assert plan.private_report()["timing_attested"] is False
    assert plan.private_report()["independent_gameplay_proof"] is False
    assert "capture_ns" not in str(plan.private_report())
    assert "sequence" not in str(plan.private_report())
    assert 1_000_000_000 not in asdict(plan).values()


def test_exact_tick_and_one_nanosecond_over_round_up_correctly() -> None:
    plan = prepare_private_latency_replay((
        frame(1, infer=90_000_000, gate=0, ack=10_000_000),
        frame(2, capture=2_000_000_000, infer=90_000_001, gate=0, ack=10_000_000),
    ), owner_approved=True)
    assert plan.decision_delay_schedule == (1, 2)


def test_zero_elapsed_stamp_is_valid_and_does_not_create_false_delay() -> None:
    plan = prepare_private_latency_replay(
        (LocalFrameTiming(1, 0, 0, 0, 0),), owner_approved=True,
    )
    assert plan.decision_delay_schedule == (0,)
    assert plan.private_report()["end_to_end_p95_ns"] == 0


@pytest.mark.parametrize("bad", [
    (1, -1, 0, 0, 0),
    (1, 100, 99, 100, 101),
    (1, 100, 101, 100, 102),
    (1, 100, 101, 102, 99),
    (0, 1, 2, 3, 4),
    (257, 1, 2, 3, 4),
    (True, 1, 2, 3, 4),
    (1, True, 2, 3, 4),
    (1, 1.0, 2, 3, 4),
    (1, 1, 2, "3", 4),
    (1, 1, 2, 3, 2**63),
    (1, 1, 2, 3, 30_000_000_002),
])
def test_bad_frame_rejected(bad: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        LocalFrameTiming(*bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("captures", [
    (),
    [],
    (None,),
    (frame(2),),
    (frame(), frame(3, capture=2_000_000_000)),
    (frame(), frame(2, capture=1_000_000_000)),
    tuple(frame(i + 1, capture=i * 1_000_000_000) for i in range(256)) + (frame(256, capture=300_000_000_000),),
])
def test_invalid_sequences_fail_closed(captures: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        prepare_private_latency_replay(
            captures, owner_approved=True,  # type: ignore[arg-type]
        )


def test_ack_order_must_not_go_backwards_across_frames() -> None:
    captures = (
        frame(1, capture=1_000_000_000, infer=200_000_000),
        frame(2, capture=1_100_000_000, infer=0, gate=0, ack=0),
    )
    with pytest.raises(ValueError, match="acknowledgments"):
        prepare_private_latency_replay(captures, owner_approved=True)


@pytest.mark.parametrize("tick_ns", [True, 0, 9_999_999, 1_000_000_001, 1.0, None])
def test_tick_calibration_rejected_when_invalid(tick_ns: object) -> None:
    with pytest.raises(ValueError, match="tick_ns"):
        prepare_private_latency_replay(
            (frame(),), owner_approved=True, tick_ns=tick_ns,  # type: ignore[arg-type]
        )


def test_no_owner_permission_means_no_simulation_plan() -> None:
    with pytest.raises(PermissionError):
        prepare_private_latency_replay((frame(),))
    with pytest.raises(PermissionError):
        prepare_private_latency_replay((frame(),), owner_approved=1)  # type: ignore[arg-type]


def test_excessive_latency_rejected_without_clipping() -> None:
    with pytest.raises(ValueError, match="exceeds 24"):
        prepare_private_latency_replay(
            (frame(1, infer=2_500_000_000),), owner_approved=True,
        )


def test_genuine_host_wait_not_misrepresented_as_inference() -> None:
    sample = frame(1, infer=10_000_000, gate=20_000_000, ack=270_000_000)
    plan = prepare_private_latency_replay((sample,), owner_approved=True)
    assert plan.inference_p95_ns == 10_000_000
    assert plan.action_ack_p95_ns == 270_000_000
    assert plan.decision_delay_schedule == (3,)


def test_measured_schedule_is_consumed_by_existing_sealed_lab() -> None:
    scenario = MazeScenario("measured_corridor", ("#####", "#S.G#", "#####"))
    samples = (
        frame(1, capture=1_000_000_000, infer=0, gate=0, ack=0),
        frame(2, capture=1_100_000_000, infer=100_000_000, gate=0, ack=0),
    )
    schedule = prepare_private_latency_replay(
        samples, owner_approved=True,
    ).decision_delay_schedule
    baseline = run_signed_maze_trial(scenario, owner_approved=True)
    replay = run_signed_maze_trial(
        scenario, owner_approved=True, decision_delay_schedule=schedule,
    )
    assert baseline.success and replay.success
    assert replay.decision_delay_schedule_used
    assert replay.world_ticks > baseline.world_ticks
    assert replay.decision_delay_total_ticks > 0
    assert replay.invalid_move_attempts == 0


def test_input_never_contains_screenshots_audio_chat_or_prompt_fields() -> None:
    assert tuple(LocalFrameTiming.__dataclass_fields__) == (
        "sequence", "capture_ns", "decision_ready_ns",
        "action_submit_ns", "action_ack_ns",
    )
    assert "source_key" not in PrivateNames()


def PrivateNames() -> tuple[str, ...]:
    from star.measured_game_latency import PrivateLatencyReplay
    return tuple(PrivateLatencyReplay.__dataclass_fields__)
