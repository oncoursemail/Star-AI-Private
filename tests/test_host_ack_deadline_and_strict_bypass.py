"""Offline invariants: strict host acceptance cannot be self-asserted; ACK must be timely."""
from __future__ import annotations

import pytest

from star.host_monotonic_game_probe import HostMonotonicGameProbe


class Clock:
    def __init__(self, *times: int) -> None:
        self._times = iter(times)

    def __call__(self) -> int:
        return next(self._times)


def strict(*times: int, ack_budget: int | None = None) -> HostMonotonicGameProbe:
    return HostMonotonicGameProbe(
        owner_approved=True,
        clock=Clock(*times),
        max_action_age_ns=10_000_000,
        require_submit_confirmation=True,
        max_ack_wait_ns=ack_budget,
    )


def test_strict_mode_cannot_use_legacy_manual_submission() -> None:
    host = strict(0, 1, 2)
    frame = host.capture()
    host.decision_ready(frame)
    with pytest.raises(ValueError, match="requires guarded_dispatch"):
        host.action_submitted(frame)
    assert host.status()["revoked"] is True
    assert host.status()["completed_frames"] == 0
    with pytest.raises(RuntimeError, match="revoked"):
        host.finalize()


def test_strict_mode_cannot_bypass_after_pre_submit_deadline_check() -> None:
    host = strict(0, 1, 2, 3)
    frame = host.capture()
    host.decision_ready(frame)
    host.pre_submit_check(frame)
    with pytest.raises(ValueError, match="requires guarded_dispatch"):
        host.action_submitted(frame)
    assert host.status()["revoked"] is True


def test_prior_completed_samples_revoked_after_strict_bypass_attempt() -> None:
    host = strict(0, 1, 2, 3, 4, 5, 6, 7)
    first = host.capture()
    host.decision_ready(first)
    host.guarded_dispatch(first, lambda: True)
    host.action_ack(first)
    second = host.capture()
    host.decision_ready(second)
    with pytest.raises(ValueError, match="requires guarded_dispatch"):
        host.action_submitted(second)
    assert host.status()["completed_frames"] == 0
    assert host.status()["revoked"] is True


def test_legacy_manual_host_submission_still_supported() -> None:
    host = HostMonotonicGameProbe(
        owner_approved=True,
        clock=Clock(0, 100, 200, 300, 400),
        max_action_age_ns=10_000_000,
        max_ack_wait_ns=1_000_000,
    )
    frame = host.capture()
    host.decision_ready(frame)
    host.pre_submit_check(frame)
    host.action_submitted(frame)
    host.action_ack(frame)
    assert host.finalize().capture_count == 1


def test_accepted_submission_can_still_fail_late_host_ack() -> None:
    host = strict(0, 1, 2, 3, 1_000_004, ack_budget=1_000_000)
    frame = host.capture()
    host.decision_ready(frame)
    host.guarded_dispatch(frame, lambda: True)
    with pytest.raises(ValueError, match="acknowledgment deadline"):
        host.action_ack(frame)
    status = host.status()
    assert status["revoked"] is True
    assert status["ack_deadline_violations"] == 1
    assert status["pending_frames"] == 0
    assert status["ack_delivery_attested"] is False
    with pytest.raises(RuntimeError, match="revoked"):
        host.finalize()


def test_exact_ack_deadline_boundary_is_allowed() -> None:
    host = strict(0, 1, 2, 3, 1_000_003, ack_budget=1_000_000)
    frame = host.capture()
    host.decision_ready(frame)
    host.guarded_dispatch(frame, lambda: True)
    host.action_ack(frame)
    assert host.finalize().capture_count == 1
    status = host.status()
    assert status["ack_deadline_guard_active"] is True
    assert status["ack_deadline_violations"] == 0
    assert status["independent_gameplay_proof"] is False
    assert status["ack_delivery_attested"] is False


def test_delayed_ack_revokes_prior_successful_samples() -> None:
    host = strict(
        0, 1, 2, 3, 4, 5, 6, 7, 8, 1_000_009, ack_budget=1_000_000,
    )
    first = host.capture()
    host.decision_ready(first)
    host.guarded_dispatch(first, lambda: True)
    host.action_ack(first)
    second = host.capture()
    host.decision_ready(second)
    host.guarded_dispatch(second, lambda: True)
    with pytest.raises(ValueError, match="acknowledgment deadline"):
        host.action_ack(second)
    assert host.status()["completed_frames"] == 0


@pytest.mark.parametrize("bad", [True, 0, 999_999, 10_000_000_001, 1.0, "5ms"])
def test_ack_budget_validation(bad: object) -> None:
    with pytest.raises(ValueError, match="max_ack_wait_ns"):
        HostMonotonicGameProbe(
            owner_approved=True,
            max_ack_wait_ns=bad,  # type: ignore[arg-type]
        )


def test_ack_timeout_does_not_leak_raw_clocks_or_host_details() -> None:
    host = strict(0, 1, 2, 3, 1_000_004, ack_budget=1_000_000)
    frame = host.capture()
    host.decision_ready(frame)
    host.guarded_dispatch(frame, lambda: True)
    with pytest.raises(ValueError):
        host.action_ack(frame)
    report = str(host.status())
    for secret in ("capture_ns", "action_submit_ns", "session_key", "chat", "screenshot"):
        assert secret not in report
    assert "independent_gameplay_proof': False" in report
