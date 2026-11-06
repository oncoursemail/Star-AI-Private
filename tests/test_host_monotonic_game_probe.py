"""Private host monotonic instrumentation: no game, OBS, media or network I/O."""
from __future__ import annotations

from dataclasses import asdict
from time import monotonic_ns

import pytest

from star.host_monotonic_game_probe import HostMonotonicGameProbe
from star.signed_maze_lab import MazeScenario, run_signed_maze_trial


class SequenceClock:
    def __init__(self, *stamps: object) -> None:
        self.stamps = iter(stamps)

    def __call__(self) -> int:
        return next(self.stamps)  # type: ignore[return-value]


def test_consent_required_and_exact_bool() -> None:
    with pytest.raises(PermissionError):
        HostMonotonicGameProbe()
    with pytest.raises(PermissionError):
        HostMonotonicGameProbe(owner_approved=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        HostMonotonicGameProbe(owner_approved=True, clock=123)  # type: ignore[arg-type]


def test_local_clock_sampled_at_each_host_stage_and_redacted() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True,
        clock=SequenceClock(1_000_000_000, 1_020_000_000, 1_030_000_000, 1_040_000_000),
    )
    sequence = host.capture()
    assert sequence == 1
    assert host.status()["pending_frames"] == 1
    host.decision_ready(sequence)
    host.action_submitted(sequence)
    host.action_ack(sequence)
    plan = host.finalize(tick_ns=100_000_000)
    assert plan.decision_delay_schedule == (1,)
    assert plan.inference_p95_ns == 20_000_000
    assert plan.gate_p95_ns == 10_000_000
    assert plan.action_ack_p95_ns == 10_000_000
    assert plan.end_to_end_p95_ns == 40_000_000
    assert host.status() == {
        "started_frames": 1,
        "completed_frames": 1,
        "pending_frames": 0,
        "revoked": False,
        "finalized": True,
        "independent_gameplay_proof": False,
        "timing_attested": False,
    }
    report = plan.private_report()
    assert report["timing_attested"] is False
    for secret in ("capture_ns", "decision_ready_ns", "action_submit_ns", "action_ack_ns",
                   "player", "screenshot", "chat", "audio", "prompt"):
        assert secret not in str(report)
        assert secret not in str(host.status())
    assert 1_000_000_000 not in asdict(plan).values()
    with pytest.raises(RuntimeError, match="finalized"):
        host.capture()
    with pytest.raises(RuntimeError, match="finalized"):
        host.finalize()


def test_overlapping_capture_allowed_if_acks_complete_in_order() -> None:
    clock = SequenceClock(
        1_000_000_000, 1_005_000_000,  # overlapping captures
        1_010_000_000, 1_015_000_000, 1_020_000_000,  # first decision/submit/ACK
        1_025_000_000, 1_030_000_000, 1_035_000_000,  # second decision/submit/ACK
    )
    host = HostMonotonicGameProbe(owner_approved=True, clock=clock)
    first, second = host.capture(), host.capture()
    host.decision_ready(first)
    host.action_submitted(first)
    host.action_ack(first)
    host.decision_ready(second)
    host.action_submitted(second)
    host.action_ack(second)
    plan = host.finalize(tick_ns=10_000_000)
    assert plan.capture_count == 2
    assert plan.decision_delay_schedule == (2, 3)


def test_timestamps_are_consistent_with_private_signed_maze_replay() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True,
        clock=SequenceClock(1_000_000_000, 1_100_000_000, 1_150_000_000, 1_160_000_000),
    )
    n = host.capture()
    host.decision_ready(n)
    host.action_submitted(n)
    host.action_ack(n)
    schedule = host.finalize().decision_delay_schedule
    maze = MazeScenario("private_host_probe", ("#####", "#S.G#", "#####"))
    baseline = run_signed_maze_trial(maze, owner_approved=True)
    result = run_signed_maze_trial(
        maze, owner_approved=True, decision_delay_schedule=schedule,
    )
    assert result.success and baseline.success
    assert result.world_ticks > baseline.world_ticks


def test_abort_does_not_reinterpret_missing_ack_as_success() -> None:
    host = HostMonotonicGameProbe(owner_approved=True, clock=SequenceClock(1, 2, 3))
    n = host.capture()
    host.decision_ready(n)
    host.action_submitted(n)
    host.abort()
    status = host.status()
    assert status["revoked"] and status["completed_frames"] == 0
    assert status["pending_frames"] == 0
    with pytest.raises(RuntimeError, match="revoked"):
        host.finalize()


def test_incomplete_or_empty_window_refuses_replay() -> None:
    for mark_ready in (False, True):
        host = HostMonotonicGameProbe(
            owner_approved=True, clock=SequenceClock(100, 200),
        )
        n = host.capture()
        if mark_ready:
            host.decision_ready(n)
        with pytest.raises(ValueError, match="incomplete"):
            host.finalize()
        assert host.status()["revoked"]
    empty = HostMonotonicGameProbe(owner_approved=True)
    with pytest.raises(ValueError, match="incomplete"):
        empty.finalize()


@pytest.mark.parametrize("events", [
    ("action_submitted",),
    ("action_ack",),
    ("decision_ready", "decision_ready"),
    ("decision_ready", "action_ack"),
    ("decision_ready", "action_submitted", "action_submitted"),
    ("decision_ready", "action_submitted", "action_ack", "action_ack"),
])
def test_illegal_phase_transition_fails_closed(events: tuple[str, ...]) -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True, clock=SequenceClock(0, 1, 2, 3, 4),
    )
    n = host.capture()
    with pytest.raises(ValueError):
        for phase in events:
            getattr(host, phase)(n)
    assert host.status()["revoked"] is True
    with pytest.raises(RuntimeError, match="revoked"):
        host.finalize()


@pytest.mark.parametrize("bad_clock", [
    (100, 99), (100, True), (100, -1), (100, 2**63), (100, 101.0),
])
def test_clock_regression_and_invalid_integer_revoke(bad_clock: tuple[object, ...]) -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True, clock=SequenceClock(*bad_clock),
    )
    n = host.capture()
    with pytest.raises(ValueError):
        host.decision_ready(n)
    assert host.status()["revoked"] is True


def test_clock_exception_fails_closed() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True, clock=SequenceClock(100),
    )
    n = host.capture()
    with pytest.raises(RuntimeError, match="clock failed"):
        host.decision_ready(n)
    assert host.status()["revoked"]


def test_ack_out_of_order_fails_closed_even_with_async_frames() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True, clock=SequenceClock(1, 2, 3, 4, 5),
    )
    first, second = host.capture(), host.capture()
    host.decision_ready(second)
    host.action_submitted(second)
    with pytest.raises(ValueError, match="ACK"):
        host.action_ack(second)
    assert host.status()["revoked"]
    with pytest.raises(RuntimeError):
        host.action_ack(first)


def test_overlong_host_interval_cannot_masquerade_as_fast_frame() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True,
        clock=SequenceClock(0, 20_000_000_000, 25_000_000_000, 31_000_000_000),
    )
    n = host.capture()
    host.decision_ready(n)
    host.action_submitted(n)
    with pytest.raises(ValueError, match="invalid host"):
        host.action_ack(n)
    assert host.status()["revoked"]


def test_excessive_replay_delay_is_not_clipped() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True,
        clock=SequenceClock(0, 2_500_000_000, 2_500_000_000, 2_500_000_000),
    )
    n = host.capture()
    host.decision_ready(n)
    host.action_submitted(n)
    host.action_ack(n)
    with pytest.raises(ValueError, match="exceeds"):
        host.finalize()
    assert host.status()["revoked"]


def test_duplicate_or_unknown_identity_revokes_entire_window() -> None:
    host = HostMonotonicGameProbe(owner_approved=True, clock=SequenceClock(100))
    host.capture()
    with pytest.raises(ValueError):
        host.decision_ready(True)  # type: ignore[arg-type]
    assert host.status()["revoked"]


def test_real_host_monotonic_ns_clock_smoke_without_any_game_input() -> None:
    """This tests the clock plumbing, not GPU inference or live gaming."""
    before = monotonic_ns()
    host = HostMonotonicGameProbe(owner_approved=True)
    n = host.capture()
    _ = sum(range(1000))  # small local CPU work, no external processes or I/O
    host.decision_ready(n)
    host.action_submitted(n)
    host.action_ack(n)
    plan = host.finalize()
    assert plan.capture_count == 1
    assert plan.end_to_end_max_ns >= 0
    assert monotonic_ns() >= before
    assert plan.private_report()["independent_gameplay_proof"] is False


def test_frame_cap_fails_closed_without_fabricated_dropped_samples() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True, clock=SequenceClock(*range(257)),
    )
    assert [host.capture() for _ in range(256)] == list(range(1, 257))
    with pytest.raises(ValueError, match="256"):
        host.capture()
    assert host.status()["started_frames"] == 256
    assert host.status()["revoked"]
    with pytest.raises(RuntimeError, match="revoked"):
        host.finalize()


def test_callback_with_missing_middle_frame_cannot_be_replayed() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True, clock=SequenceClock(1, 2, 3, 4, 5),
    )
    first, _second = host.capture(), host.capture()
    host.decision_ready(first)
    host.action_submitted(first)
    host.action_ack(first)
    with pytest.raises(ValueError, match="incomplete"):
        host.finalize()
    assert host.status()["revoked"]
    assert host.status()["completed_frames"] == 0  # old success discarded
