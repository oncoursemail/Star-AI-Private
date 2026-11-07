"""Opt-in host input-neutralization receipt invariants (synthetic, offline)."""
from __future__ import annotations

from threading import Event, Thread

import pytest

from star.host_monotonic_game_probe import HostMonotonicGameProbe


class Clock:
    def __init__(self, *stamps: int) -> None:
        self.times = iter(stamps)

    def __call__(self) -> int:
        return next(self.times)


def host(*times: int, max_hold: int = 1_000_000) -> HostMonotonicGameProbe:
    return HostMonotonicGameProbe(
        owner_approved=True, clock=Clock(*times),
        max_action_age_ns=10_000_000,
        require_submit_confirmation=True,
        require_input_neutralization=True, max_input_hold_ns=max_hold,
    )


def started(h: HostMonotonicGameProbe) -> int:
    s = h.capture()
    h.decision_ready(s)
    h.guarded_dispatch(s, lambda: True)
    return s


def test_neutralization_request_required_before_ack_and_report_not_attested() -> None:
    h = host(0, 1, 2, 3, 4, 5)
    s = started(h)
    h.guarded_neutralize(s, lambda: True)
    h.action_ack(s)
    assert h.finalize().capture_count == 1
    st = h.status()
    assert st["input_neutralization_required"] is True
    assert st["input_hold_violations"] == 0
    assert st["physical_input_release_attested"] is False
    assert st["independent_gameplay_proof"] is False


def test_missing_neutralization_revokes_entire_window() -> None:
    h = host(0, 1, 2, 3)
    s = started(h)
    with pytest.raises(ValueError, match="neutralization required"):
        h.action_ack(s)
    assert h.status()["revoked"] is True
    assert h.status()["completed_frames"] == 0


@pytest.mark.parametrize("reply", [False, None, 1, "true"])
def test_only_exact_true_acceptance_counts(reply: object) -> None:
    h = host(0, 1, 2, 3)
    s = started(h)
    with pytest.raises(ValueError, match="did not confirm neutralization"):
        h.guarded_neutralize(s, lambda: reply)
    assert h.status()["host_neutralize_rejections"] == 1
    assert h.status()["revoked"] is True


def test_neutralize_callback_failure_revokes_all_prior_completed_frames() -> None:
    h = host(0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    first = started(h)
    h.guarded_neutralize(first, lambda: True)
    h.action_ack(first)
    second = started(h)

    def broken() -> bool:
        raise OSError("native release request failed")

    with pytest.raises(OSError, match="native release"):
        h.guarded_neutralize(second, broken)
    assert h.status()["completed_frames"] == 0
    assert h.status()["revoked"] is True
    with pytest.raises(RuntimeError, match="revoked"):
        h.finalize()


def test_expired_hold_attempts_release_before_revoking_session() -> None:
    h = host(0, 1, 2, 3, 1_000_004, max_hold=1_000_000)
    s = started(h)
    attempts: list[str] = []
    with pytest.raises(ValueError, match="hold deadline"):
        h.guarded_neutralize(s, lambda: (attempts.append("release"), True)[1])
    assert attempts == ["release"], "do not skip a late neutralization request"
    assert h.status()["input_hold_violations"] == 1
    assert h.status()["physical_input_release_attested"] is False


def test_exact_hold_boundary_allows_host_request() -> None:
    h = host(0, 1, 2, 3, 1_000_003, 1_000_004)
    s = started(h)
    h.guarded_neutralize(s, lambda: True)
    h.action_ack(s)
    assert h.finalize().capture_count == 1


def test_release_callback_reentrant_probe_mutation_revokes() -> None:
    h = host(0, 1, 2, 3)
    s = started(h)
    with pytest.raises(RuntimeError, match="reentrant"):
        h.guarded_neutralize(s, lambda: (h.action_ack(s), True)[1])
    assert h.status()["revoked"] is True


def test_abort_nonblocking_during_neutralize_callback_and_revokes() -> None:
    h = host(0, 1, 2, 3, 4)
    s = started(h)
    entered, allow_return, aborted = Event(), Event(), Event()
    errors: list[Exception] = []

    def release() -> bool:
        entered.set()
        if not allow_return.wait(3):
            raise AssertionError("test callback blocked too long")
        return True

    def worker() -> None:
        try:
            h.guarded_neutralize(s, release)
        except Exception as e:
            errors.append(e)

    def stop() -> None:
        h.abort()
        aborted.set()

    sender = Thread(target=worker, daemon=True)
    stopper = Thread(target=stop, daemon=True)
    sender.start()
    try:
        assert entered.wait(2)
        stopper.start()
        assert aborted.wait(0.8), "abort blocked behind host release callback"
    finally:
        allow_return.set()
        sender.join(3)
        stopper.join(3)
    assert not sender.is_alive() and not stopper.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    assert h.status()["revoked"] is True


def test_no_release_callback_without_action_submission_and_fail_closed() -> None:
    h = host(0, 1)
    s = h.capture()
    h.decision_ready(s)
    called = False

    def release() -> bool:
        nonlocal called
        called = True
        return True

    with pytest.raises(ValueError, match="submitted, unneutralized"):
        h.guarded_neutralize(s, release)
    assert not called
    assert h.status()["revoked"] is True


def test_legacy_mode_does_not_require_neutralization() -> None:
    h = HostMonotonicGameProbe(owner_approved=True, clock=Clock(0, 1, 2, 3))
    s = h.capture()
    h.decision_ready(s)
    h.action_submitted(s)
    h.action_ack(s)
    assert h.finalize().capture_count == 1
    assert "input_neutralization_required" not in h.status()


@pytest.mark.parametrize("bad", [False, True, 0, 999_999, 10_000_000_001, 1.0, "1s"])
def test_invalid_max_hold_rejected(bad: object) -> None:
    with pytest.raises((TypeError, ValueError), match="max_input_hold_ns"):
        HostMonotonicGameProbe(
            owner_approved=True, max_action_age_ns=10_000_000,
            require_submit_confirmation=True,
            require_input_neutralization=True,
            max_input_hold_ns=bad,  # type: ignore[arg-type]
        )


def test_neutralization_requires_opt_in_and_strict_submission() -> None:
    with pytest.raises(ValueError, match="strict submission"):
        HostMonotonicGameProbe(
            owner_approved=True, require_input_neutralization=True,
            max_input_hold_ns=1_000_000,
        )
    with pytest.raises(ValueError, match="requires max_input_hold_ns"):
        HostMonotonicGameProbe(
            owner_approved=True, max_action_age_ns=10_000_000,
            require_submit_confirmation=True, require_input_neutralization=True,
        )
    with pytest.raises(TypeError, match="must be bool"):
        HostMonotonicGameProbe(
            owner_approved=True, require_input_neutralization=1,  # type: ignore[arg-type]
        )
