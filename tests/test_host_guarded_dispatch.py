"""Offline proof of the opt-in, owner-approved host submission callback.

Tests use fake clocks and fake input callbacks; no games, OBS or networking.
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
        owner_approved=True, clock=clock, max_action_age_ns=deadline,
        require_frame_opportunities=coverage,
    )


def test_host_callback_receives_one_submission_and_ack_is_separate() -> None:
    called: list[str] = []
    probe = guarded(Clock(0, 1, 2, 3, 4))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    probe.guarded_dispatch(sequence, lambda: called.append("send"))
    assert called == ["send"]
    assert probe.status()["pending_frames"] == 1
    assert probe.status()["independent_gameplay_proof"] is False
    probe.action_ack(sequence)
    replay = probe.finalize(tick_ns=10_000_000)
    assert replay.capture_count == 1
    assert replay.decision_delay_schedule == (1,)
    assert probe.status()["action_deadline_violations"] == 0
    assert "capture_ns" not in str(probe.status())


def test_stale_decision_is_rejected_without_calling_host_input() -> None:
    called: list[str] = []
    probe = guarded(Clock(0, 9_000_000, 10_000_001))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    with pytest.raises(ValueError, match="before guarded dispatch"):
        probe.guarded_dispatch(sequence, lambda: called.append("send"))
    assert called == []
    assert probe.status()["action_deadline_violations"] == 1
    assert probe.status()["completed_frames"] == 0
    assert probe.status()["revoked"]
    with pytest.raises(RuntimeError, match="revoked"):
        probe.finalize()


def test_exact_deadline_is_allowed_for_callback_and_completion() -> None:
    probe = guarded(Clock(0, 1, 10_000_000, 10_000_000, 10_000_001))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    probe.guarded_dispatch(sequence, lambda: None)
    probe.action_ack(sequence)
    assert probe.finalize().capture_count == 1


def test_callback_exception_revokes_entire_window() -> None:
    probe = guarded(Clock(0, 1, 2))
    sequence = probe.capture()
    probe.decision_ready(sequence)

    def failing_input() -> None:
        raise OSError("fake host I/O error")

    with pytest.raises(OSError, match="fake host"):
        probe.guarded_dispatch(sequence, failing_input)
    assert probe.status()["revoked"] is True
    assert probe.status()["completed_frames"] == 0
    with pytest.raises(RuntimeError, match="revoked"):
        probe.action_ack(sequence)


def test_keyboard_interrupt_does_not_leave_successful_evidence() -> None:
    probe = guarded(Clock(0, 1, 2))
    sequence = probe.capture()
    probe.decision_ready(sequence)

    def interrupt() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        probe.guarded_dispatch(sequence, interrupt)
    assert probe.status()["revoked"] is True


def test_overlong_callback_is_detected_but_cannot_unsend_input() -> None:
    submitted: list[int] = []
    probe = guarded(Clock(0, 1, 2, 11_000_000))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    with pytest.raises(ValueError, match="during guarded dispatch"):
        probe.guarded_dispatch(sequence, lambda: submitted.append(sequence))
    assert submitted == [sequence]  # physical side effects cannot be undone
    assert probe.status()["action_deadline_violations"] == 1
    assert probe.status()["revoked"] is True


def test_reentrant_probe_mutation_inside_host_callback_revokes() -> None:
    probe = guarded(Clock(0, 1, 2))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    with pytest.raises(RuntimeError, match="reentrant"):
        probe.guarded_dispatch(sequence, probe.capture)
    assert probe.status()["revoked"] is True


def test_caught_reentrant_error_still_revokes_window() -> None:
    probe = guarded(Clock(0, 1, 2))
    sequence = probe.capture()
    probe.decision_ready(sequence)

    def bad_host() -> None:
        with pytest.raises(RuntimeError, match="reentrant"):
            probe.decision_ready(sequence)

    with pytest.raises(RuntimeError, match="revoked"):
        probe.guarded_dispatch(sequence, bad_host)
    assert probe.status()["revoked"] is True


def test_guard_requires_owner_approval_and_explicit_deadline() -> None:
    with pytest.raises(PermissionError):
        HostMonotonicGameProbe()
    probe = HostMonotonicGameProbe(owner_approved=True, clock=Clock(0, 1))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    with pytest.raises(ValueError, match="requires an action age deadline"):
        probe.guarded_dispatch(sequence, lambda: None)
    assert probe.status()["revoked"] is True


@pytest.mark.parametrize("invalid", [None, True, False, 4, "send", []])
def test_invalid_callback_revokes_without_side_effects(invalid: object) -> None:
    probe = guarded(Clock(0, 1))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    with pytest.raises(ValueError, match="requires a host callback"):
        probe.guarded_dispatch(sequence, invalid)  # type: ignore[arg-type]
    assert probe.status()["revoked"] is True


def test_cannot_mix_split_and_callback_submission_paths() -> None:
    probe = guarded(Clock(0, 1, 2))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    probe.pre_submit_check(sequence)
    with pytest.raises(ValueError, match="unchecked decision"):
        probe.guarded_dispatch(sequence, lambda: None)
    assert probe.status()["revoked"] is True

    probe = guarded(Clock(0, 1, 2, 3, 4))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    probe.guarded_dispatch(sequence, lambda: None)
    with pytest.raises(ValueError, match="submission requires"):
        probe.action_submitted(sequence)
    assert probe.status()["revoked"] is True


def test_replayed_failure_cannot_hide_first_success() -> None:
    probe = guarded(Clock(0, 1, 2, 3, 4, 5, 6, 11_000_000))
    first = probe.capture()
    probe.decision_ready(first)
    probe.guarded_dispatch(first, lambda: None)
    probe.action_ack(first)
    second = probe.capture()
    probe.decision_ready(second)
    with pytest.raises(ValueError, match="before guarded dispatch"):
        probe.guarded_dispatch(second, lambda: None)
    assert probe.status()["completed_frames"] == 0
    assert probe.status()["revoked"]


def test_coverage_and_guarded_callback_feed_private_maze_replay() -> None:
    probe = guarded(
        Clock(0, 1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000),
        coverage=True,
    )
    opportunity = probe.frame_available()
    sequence = probe.capture(opportunity=opportunity)
    probe.decision_ready(sequence)
    probe.guarded_dispatch(sequence, lambda: None)
    probe.action_ack(sequence)
    replay = probe.finalize(tick_ns=10_000_000)
    scenario = MazeScenario("guarded_callback_trial", ("#####", "#S.G#", "#####"))
    baseline = run_signed_maze_trial(scenario, owner_approved=True)
    stressed = run_signed_maze_trial(
        scenario, owner_approved=True,
        decision_delay_schedule=replay.decision_delay_schedule,
    )
    assert baseline.success and stressed.success
    assert stressed.world_ticks > baseline.world_ticks
    assert probe.status()["independent_gameplay_proof"] is False
