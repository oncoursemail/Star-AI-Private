"""Emergency cancellation tests use only synthetic callbacks and monotonic clocks."""
from __future__ import annotations

from threading import Event, Thread

import pytest

from star.host_monotonic_game_probe import HostMonotonicGameProbe


class Clock:
    def __init__(self, *stamps: int) -> None:
        self._stamps = iter(stamps)

    def __call__(self) -> int:
        return next(self._stamps)


def test_abort_returns_while_host_callback_is_blocked_and_revokes_old_evidence() -> None:
    # First sample is complete. Aborting the second must invalidate BOTH.
    probe = HostMonotonicGameProbe(
        owner_approved=True, clock=Clock(0, 1, 2, 3, 4, 5, 6, 7),
        max_action_age_ns=10_000_000,
        require_submit_confirmation=True,
    )
    first = probe.capture()
    probe.decision_ready(first)
    probe.guarded_dispatch(first, lambda: True)
    probe.action_ack(first)

    second = probe.capture()
    probe.decision_ready(second)
    entered, release, cancelled = Event(), Event(), Event()
    errors: list[BaseException] = []

    def blocked_submit() -> bool:
        entered.set()
        if not release.wait(3.0):
            raise AssertionError("test callback was not released")
        return True

    def dispatch() -> None:
        try:
            probe.guarded_dispatch(second, blocked_submit)
        except BaseException as exc:
            errors.append(exc)

    def cancel() -> None:
        probe.abort()
        cancelled.set()

    sender = Thread(target=dispatch, daemon=True)
    stopper = Thread(target=cancel, daemon=True)
    sender.start()
    try:
        assert entered.wait(2.0)
        stopper.start()
        # The old implementation blocked on the RLock held by the callback.
        assert cancelled.wait(0.8), "emergency abort waited for native callback"
    finally:
        release.set()
        sender.join(3.0)
        stopper.join(3.0)

    assert not sender.is_alive() and not stopper.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    assert "revoked" in str(errors[0])
    assert probe.status()["revoked"] is True
    assert probe.status()["completed_frames"] == 0
    assert probe.status()["pending_frames"] == 0
    with pytest.raises(RuntimeError, match="revoked"):
        probe.finalize()


def test_abort_from_inside_native_callback_invalidates_dispatch() -> None:
    probe = HostMonotonicGameProbe(
        owner_approved=True, clock=Clock(0, 1, 2),
        max_action_age_ns=10_000_000, require_submit_confirmation=True,
    )
    sequence = probe.capture()
    probe.decision_ready(sequence)

    def host_submits_then_cancels() -> bool:
        probe.abort()  # Same-thread recursive lock: cancellation still wins.
        return True

    with pytest.raises(RuntimeError, match="revoked"):
        probe.guarded_dispatch(sequence, host_submits_then_cancels)
    assert probe.status()["revoked"] is True
    assert probe.status()["completed_frames"] == 0


def test_abort_is_idempotent_and_legacy_paths_cannot_resume() -> None:
    probe = HostMonotonicGameProbe(owner_approved=True, clock=Clock(0, 1, 2))
    sequence = probe.capture()
    probe.decision_ready(sequence)
    probe.abort()
    probe.abort()
    assert probe.status()["revoked"] is True
    with pytest.raises(RuntimeError, match="revoked"):
        probe.action_submitted(sequence)
    with pytest.raises(RuntimeError, match="revoked"):
        probe.capture()
