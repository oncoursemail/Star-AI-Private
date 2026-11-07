"""Fail-closed private host frame coverage and measured queue delay."""
from __future__ import annotations

from dataclasses import asdict
from time import monotonic_ns

import pytest

from star.host_monotonic_game_probe import HostMonotonicGameProbe
from star.signed_maze_lab import MazeScenario, run_signed_maze_trial


class Clock:
    def __init__(self, *stamps: int) -> None:
        self._stamps = iter(stamps)

    def __call__(self) -> int:
        return next(self._stamps)


def _complete(probe: HostMonotonicGameProbe, opportunity: int) -> int:
    sequence = probe.capture(opportunity=opportunity)
    probe.decision_ready(sequence)
    probe.action_submitted(sequence)
    probe.action_ack(sequence)
    return sequence


def test_opt_in_mode_is_strict_and_legacy_works() -> None:
    with pytest.raises(PermissionError):
        HostMonotonicGameProbe(require_frame_opportunities=True)
    with pytest.raises(TypeError, match="bool"):
        HostMonotonicGameProbe(owner_approved=True, require_frame_opportunities=1)  # type: ignore[arg-type]
    legacy = HostMonotonicGameProbe(owner_approved=True, clock=Clock(0, 1, 2, 3))
    sequence = legacy.capture()
    legacy.decision_ready(sequence)
    legacy.action_submitted(sequence)
    legacy.action_ack(sequence)
    assert legacy.finalize().capture_count == 1
    assert "frame_opportunities" not in legacy.status()


def test_witnessed_queue_delay_counts_as_real_latency_and_replays() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        clock=Clock(0, 5_000_000, 20_000_000, 30_000_000, 40_000_000),
    )
    token = probe.frame_available()
    assert probe.status()["unclaimed_opportunities"] == 1
    assert _complete(probe, token) == token
    replay = probe.finalize(tick_ns=10_000_000)
    assert replay.inference_p95_ns == 20_000_000  # Includes 5ms queue time.
    assert replay.gate_p95_ns == 10_000_000
    assert replay.action_ack_p95_ns == 10_000_000
    assert replay.end_to_end_max_ns == 40_000_000
    assert replay.decision_delay_schedule == (4,)
    status = probe.status()
    assert status["frame_opportunities"] == 1
    assert status["dropped_opportunities"] == 0
    assert status["unclaimed_opportunities"] == 0
    assert status["finalized"] is True
    assert status["host_coverage_attested"] is False
    assert replay.private_report()["timing_attested"] is False
    assert "capture_ns" not in asdict(replay)
    assert "decision_ready_ns" not in replay.private_report()
    with pytest.raises(RuntimeError, match="finalized"):
        probe.frame_available()
    with pytest.raises(RuntimeError, match="finalized"):
        probe.capture(opportunity=1)


def test_offered_but_unprocessed_frame_refuses_success_only_report() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        clock=Clock(0, 1, 2, 3, 4, 5),
    )
    first = probe.frame_available()
    second = probe.frame_available()
    _complete(probe, first)
    assert probe.status()["unclaimed_opportunities"] == 1
    assert second == 2
    with pytest.raises(ValueError, match="incomplete"):
        probe.finalize()
    assert probe.status()["revoked"] is True
    assert probe.status()["completed_frames"] == 0
    assert probe.status()["frame_opportunities"] == 2
    assert probe.status()["unclaimed_opportunities"] == 1


@pytest.mark.parametrize("reason", [
    "capture_overrun", "inference_timeout", "host_error", "privacy_stop",
])
def test_explicit_dropped_frame_revokes_and_counts(reason: str) -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True, clock=Clock(0),
    )
    frame = probe.frame_available()
    with pytest.raises(ValueError, match="dropped"):
        probe.drop_frame(frame, reason=reason)
    assert probe.status()["dropped_opportunities"] == 1
    assert probe.status()["revoked"] is True
    with pytest.raises(RuntimeError, match="revoked"):
        probe.finalize()


@pytest.mark.parametrize("opportunity,reason", [
    (True, "host_error"), (0, "host_error"), (2, "host_error"),
    (1, "fabricated"), (1, ""), (1, 42), (1, []),
])
def test_invalid_drop_reports_fail_closed(opportunity: object, reason: object) -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True, clock=Clock(0),
    )
    probe.frame_available()
    with pytest.raises(ValueError, match="invalid"):
        probe.drop_frame(opportunity, reason=reason)  # type: ignore[arg-type]
    assert probe.status()["revoked"] is True
    assert probe.status()["dropped_opportunities"] == 0


def test_out_of_order_opportunities_fail_closed() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True, clock=Clock(0, 1),
    )
    probe.frame_available()
    probe.frame_available()
    with pytest.raises(ValueError, match="out-of-order"):
        probe.capture(opportunity=2)
    assert probe.status()["revoked"]


@pytest.mark.parametrize("invalid", [None, True, 0, 1.0, "1"])
def test_missing_or_invalid_opportunity_fails_closed(invalid: object) -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True, clock=Clock(0),
    )
    probe.frame_available()
    with pytest.raises(ValueError, match="missing"):
        probe.capture(opportunity=invalid)  # type: ignore[arg-type]
    assert probe.status()["revoked"]


def test_unexpected_token_in_legacy_mode_is_rejected() -> None:
    probe = HostMonotonicGameProbe(owner_approved=True)
    with pytest.raises(ValueError, match="unexpected"):
        probe.capture(opportunity=1)
    assert probe.status()["revoked"]


def test_unenabled_opportunity_tracking_cannot_be_called() -> None:
    probe = HostMonotonicGameProbe(owner_approved=True)
    with pytest.raises(ValueError, match="not enabled"):
        probe.frame_available()
    assert probe.status()["revoked"]


def test_two_queued_frames_have_ordered_contiguous_coverage() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        clock=Clock(0, 10, 20, 25, 30, 40, 45, 50, 60, 70),
    )
    one, two = probe.frame_available(), probe.frame_available()
    _complete(probe, one)
    _complete(probe, two)
    replay = probe.finalize(tick_ns=10_000_000)
    assert replay.capture_count == 2
    assert replay.end_to_end_total_ns == 100
    assert replay.end_to_end_max_ns == 60
    assert probe.status()["frame_opportunities"] == 2


def test_opportunity_limit_rejects_overflow_without_misreporting() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        clock=Clock(*range(256)),
    )
    assert [probe.frame_available() for _ in range(256)] == list(range(1, 257))
    with pytest.raises(ValueError, match="256"):
        probe.frame_available()
    assert probe.status()["frame_opportunities"] == 256
    assert probe.status()["revoked"] is True


def test_incomplete_or_aborted_coverage_cannot_finalize() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True, clock=Clock(0),
    )
    probe.frame_available()
    probe.abort()
    assert probe.status()["revoked"] is True
    with pytest.raises(RuntimeError, match="revoked"):
        probe.finalize()
    empty = HostMonotonicGameProbe(owner_approved=True, require_frame_opportunities=True)
    with pytest.raises(ValueError, match="incomplete"):
        empty.finalize()


def test_queue_wait_too_long_revokes_at_ack() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        clock=Clock(0, 30_000_000_001, 30_000_000_002,
                    30_000_000_003, 30_000_000_004),
    )
    _complete_raised = probe.frame_available()
    n = probe.capture(opportunity=_complete_raised)
    probe.decision_ready(n)
    probe.action_submitted(n)
    with pytest.raises(ValueError, match="invalid host"):
        probe.action_ack(n)
    assert probe.status()["revoked"]


def test_host_clock_with_real_monotonic_still_is_not_independent_attestation() -> None:
    before = monotonic_ns()
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
    )
    _complete(probe, probe.frame_available())
    replay = probe.finalize()
    assert replay.capture_count == 1
    assert monotonic_ns() >= before
    assert probe.status()["host_coverage_attested"] is False
    assert probe.status()["independent_gameplay_proof"] is False


def test_witnessed_latency_schedule_can_stress_a_private_synthetic_game() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        clock=Clock(0, 10_000_000, 20_000_000, 30_000_000, 40_000_000),
    )
    _complete(probe, probe.frame_available())
    schedule = probe.finalize(tick_ns=100_000_000).decision_delay_schedule
    maze = MazeScenario("coverage_private", ("#####", "#S.G#", "#####"))
    baseline = run_signed_maze_trial(maze, owner_approved=True)
    stressed = run_signed_maze_trial(
        maze, owner_approved=True, decision_delay_schedule=schedule,
    )
    assert baseline.success and stressed.success
    assert stressed.world_ticks > baseline.world_ticks


@pytest.mark.parametrize("bad", [True, 0, 999_999, 10_000_000_001, 1.5, "2000000"])
def test_invalid_queue_deadline_rejected(bad: object) -> None:
    with pytest.raises(ValueError, match="max_queue_wait_ns"):
        HostMonotonicGameProbe(
            owner_approved=True, require_frame_opportunities=True,
            max_queue_wait_ns=bad,  # type: ignore[arg-type]
        )


def test_queue_deadline_requires_coverage() -> None:
    with pytest.raises(ValueError, match="coverage"):
        HostMonotonicGameProbe(owner_approved=True, max_queue_wait_ns=1_000_000)


def test_queue_deadline_fails_before_unusable_action_is_issued() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        max_queue_wait_ns=5_000_000, clock=Clock(0, 5_000_001),
    )
    frame = probe.frame_available()
    with pytest.raises(ValueError, match="deadline"):
        probe.capture(opportunity=frame)
    assert probe.status()["dropped_opportunities"] == 1
    assert probe.status()["started_frames"] == 0
    assert probe.status()["unclaimed_opportunities"] == 1
    assert probe.status()["revoked"]
    with pytest.raises(RuntimeError, match="revoked"):
        probe.finalize()


def test_queue_deadline_equality_is_allowed() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        max_queue_wait_ns=5_000_000,
        clock=Clock(0, 5_000_000, 6_000_000, 7_000_000, 8_000_000),
    )
    _complete(probe, probe.frame_available())
    result = probe.finalize(tick_ns=10_000_000)
    assert result.capture_count == 1
    assert result.end_to_end_max_ns == 8_000_000
    assert probe.status()["dropped_opportunities"] == 0


def test_late_drop_discards_earlier_fast_frames() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, require_frame_opportunities=True,
        clock=Clock(0, 1, 2, 3, 4, 5),
    )
    _complete(probe, probe.frame_available())
    assert probe.status()["completed_frames"] == 1
    missing = probe.frame_available()
    with pytest.raises(ValueError, match="dropped"):
        probe.drop_frame(missing, reason="capture_overrun")
    assert probe.status()["completed_frames"] == 0
    assert probe.status()["frame_opportunities"] == 2
    assert probe.status()["unclaimed_opportunities"] == 1
    assert probe.status()["dropped_opportunities"] == 1
    with pytest.raises(RuntimeError, match="revoked"):
        probe.finalize()
