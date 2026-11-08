"""Action freshness checks for a private, authorized game-host decision path.

All clocks are deterministic fixtures; tests do not send gameplay input.
"""
from __future__ import annotations

import pytest

from star.host_monotonic_game_probe import HostMonotonicGameProbe
from star.signed_maze_lab import MazeScenario, run_signed_maze_trial


class Clock:
    def __init__(self, *stamps: int) -> None:
        self._stamps = iter(stamps)

    def __call__(self) -> int:
        return next(self._stamps)


def guarded(clock: Clock, *, deadline: int = 10_000_000,
            coverage: bool = False) -> HostMonotonicGameProbe:
    return HostMonotonicGameProbe(
        owner_approved=True, clock=clock,
        max_action_age_ns=deadline,
        require_frame_opportunities=coverage,
    )


def test_opt_in_guard_keeps_legacy_event_path_unchanged() -> None:
    probe = HostMonotonicGameProbe(owner_approved=True, clock=Clock(0, 1, 2, 3))
    n = probe.capture()
    probe.decision_ready(n)
    probe.action_submitted(n)
    probe.action_ack(n)
    assert probe.finalize().capture_count == 1
    assert "action_deadline_violations" not in probe.status()


@pytest.mark.parametrize("value", [True, False, 0, 999_999, 10_000_000_001, 1.0, "1ms", []])
def test_invalid_action_deadline_is_not_accepted(value: object) -> None:
    with pytest.raises(ValueError, match="max_action_age_ns"):
        HostMonotonicGameProbe(owner_approved=True, max_action_age_ns=value)  # type: ignore[arg-type]


def test_guard_requires_explicit_owner_approval() -> None:
    with pytest.raises(PermissionError):
        HostMonotonicGameProbe(max_action_age_ns=2_000_000)


def test_missing_pre_submit_check_revokes_without_success_report() -> None:
    probe = guarded(Clock(0, 1))
    n = probe.capture()
    probe.decision_ready(n)
    with pytest.raises(ValueError, match="pre-submit"):
        probe.action_submitted(n)
    assert probe.status()["revoked"] is True
    assert probe.status()["completed_frames"] == 0
    with pytest.raises(RuntimeError, match="revoked"):
        probe.finalize()


def test_pre_submit_check_must_happen_only_once_after_decision() -> None:
    probe = guarded(Clock(0))
    n = probe.capture()
    with pytest.raises(ValueError, match="requires one ready"):
        probe.pre_submit_check(n)
    assert probe.status()["revoked"] is True

    probe = guarded(Clock(0, 1, 2))
    n = probe.capture()
    probe.decision_ready(n)
    probe.pre_submit_check(n)
    with pytest.raises(ValueError, match="requires one ready"):
        probe.pre_submit_check(n)
    assert probe.status()["revoked"] is True


def test_guard_is_not_available_unless_opted_in() -> None:
    probe = HostMonotonicGameProbe(owner_approved=True, clock=Clock(0, 1))
    n = probe.capture()
    probe.decision_ready(n)
    with pytest.raises(ValueError, match="not enabled"):
        probe.pre_submit_check(n)
    assert probe.status()["revoked"]


def test_pre_submit_check_rejects_stale_reasoning_before_input() -> None:
    probe = guarded(Clock(0, 8_000_000, 10_000_001))
    n = probe.capture()
    probe.decision_ready(n)
    with pytest.raises(ValueError, match="before host input"):
        probe.pre_submit_check(n)
    status = probe.status()
    assert status["action_deadline_violations"] == 1
    assert status["action_freshness_attested"] is False
    assert status["completed_frames"] == 0
    assert status["revoked"]
    with pytest.raises(RuntimeError, match="revoked"):
        probe.action_submitted(n)


def test_deadline_includes_time_queued_before_capture() -> None:
    probe = guarded(Clock(0, 6_000_000, 7_000_000, 10_000_001),
                    coverage=True)
    token = probe.frame_available()
    n = probe.capture(opportunity=token)
    probe.decision_ready(n)
    with pytest.raises(ValueError, match="before host input"):
        probe.pre_submit_check(n)
    assert probe.status()["action_deadline_violations"] == 1
    assert probe.status()["frame_opportunities"] == 1
    assert probe.status()["host_coverage_attested"] is False


def test_exact_deadline_boundary_is_allowed_and_private_replay_survives() -> None:
    probe = guarded(Clock(0, 2_000_000, 10_000_000, 10_000_000, 11_000_000))
    n = probe.capture()
    probe.decision_ready(n)
    probe.pre_submit_check(n)
    probe.action_submitted(n)
    probe.action_ack(n)
    replay = probe.finalize(tick_ns=10_000_000)
    assert replay.capture_count == 1
    assert replay.decision_delay_schedule == (2,)
    assert replay.end_to_end_max_ns == 11_000_000
    assert replay.private_report()["timing_attested"] is False
    assert probe.status()["action_deadline_violations"] == 0
    assert probe.status()["action_deadline_guard_active"] is True
    assert "capture_ns" not in str(probe.status())
    assert "action_submit_ns" not in str(replay.private_report())


def test_late_submission_detected_even_after_fresh_pre_submit() -> None:
    probe = guarded(Clock(0, 1_000_000, 9_000_000, 10_000_001))
    n = probe.capture()
    probe.decision_ready(n)
    probe.pre_submit_check(n)
    with pytest.raises(ValueError, match="during host submission"):
        probe.action_submitted(n)
    assert probe.status()["action_deadline_violations"] == 1
    assert probe.status()["completed_frames"] == 0
    assert probe.status()["revoked"]


def test_old_completed_frame_cannot_hide_later_stale_frame() -> None:
    probe = guarded(Clock(0, 1, 2, 3, 4, 5, 6, 20_000_000))
    a = probe.capture()
    probe.decision_ready(a)
    probe.pre_submit_check(a)
    probe.action_submitted(a)
    probe.action_ack(a)
    assert probe.status()["completed_frames"] == 1
    b = probe.capture()
    probe.decision_ready(b)
    with pytest.raises(ValueError, match="before host input"):
        probe.pre_submit_check(b)
    assert probe.status()["completed_frames"] == 0
    assert probe.status()["action_deadline_violations"] == 1


def test_full_coverage_and_action_guard_replay_into_private_maze() -> None:
    probe = guarded(
        Clock(0, 1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000),
        coverage=True,
    )
    offered = probe.frame_available()
    n = probe.capture(opportunity=offered)
    probe.decision_ready(n)
    probe.pre_submit_check(n)
    probe.action_submitted(n)
    probe.action_ack(n)
    replay = probe.finalize(tick_ns=10_000_000)
    maze = MazeScenario("action_deadline_private", ("#####", "#S.G#", "#####"))
    baseline = run_signed_maze_trial(maze, owner_approved=True)
    stressed = run_signed_maze_trial(
        maze, owner_approved=True,
        decision_delay_schedule=replay.decision_delay_schedule,
    )
    assert baseline.success and stressed.success
    assert stressed.world_ticks > baseline.world_ticks
    assert probe.status()["independent_gameplay_proof"] is False


def test_invalid_sequence_and_clock_regression_fail_closed() -> None:
    probe = guarded(Clock(0, 1))
    n = probe.capture()
    probe.decision_ready(n)
    with pytest.raises(ValueError, match="unknown"):
        probe.pre_submit_check(True)  # type: ignore[arg-type]
    assert probe.status()["revoked"] is True

    probe = guarded(Clock(5, 6, 4))
    n = probe.capture()
    probe.decision_ready(n)
    with pytest.raises(ValueError, match="moved backward"):
        probe.pre_submit_check(n)
    assert probe.status()["revoked"] is True