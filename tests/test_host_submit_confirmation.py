"""Deterministic host-submission confirmation tests; no real device or game I/O."""
from __future__ import annotations

import pytest

from star.host_monotonic_game_probe import HostMonotonicGameProbe


class Clock:
    def __init__(self, *stamps: int) -> None:
        self._stamps = iter(stamps)

    def __call__(self) -> int:
        return next(self._stamps)


def probe(*stamps: int, strict: bool = True) -> HostMonotonicGameProbe:
    return HostMonotonicGameProbe(
        owner_approved=True,
        clock=Clock(*stamps),
        max_action_age_ns=10_000_000,
        require_submit_confirmation=strict,
    )


def test_true_confirmation_preserves_host_ack_separation() -> None:
    called: list[str] = []
    host = probe(0, 1_000, 2_000, 3_000, 4_000)
    seq = host.capture()
    host.decision_ready(seq)

    def accepted() -> bool:
        called.append("host_called")
        return True

    host.guarded_dispatch(seq, accepted)
    assert called == ["host_called"]
    assert host.status()["pending_frames"] == 1  # Not yet acknowledged
    assert host.status()["independent_gameplay_proof"] is False
    assert host.status()["host_submission_attested"] is False
    assert host.status()["host_submit_rejections"] == 0
    host.action_ack(seq)
    assert host.finalize().capture_count == 1


@pytest.mark.parametrize("reply", [False, None, 0, 1, "ok", [], {}])
def test_strict_confirmation_requires_exact_true(reply: object) -> None:
    host = probe(0, 100, 200)
    seq = host.capture()
    host.decision_ready(seq)
    with pytest.raises(ValueError, match="did not confirm"):
        host.guarded_dispatch(seq, lambda: reply)
    assert host.status()["revoked"] is True
    assert host.status()["host_submit_rejections"] == 1
    assert host.status()["completed_frames"] == 0
    assert host.status()["pending_frames"] == 0
    with pytest.raises(RuntimeError, match="revoked"):
        host.action_ack(seq)
    with pytest.raises(RuntimeError, match="revoked"):
        host.finalize()


def test_legacy_false_is_rejected_but_none_is_compatible() -> None:
    host = probe(0, 1, 2, strict=False)
    seq = host.capture()
    host.decision_ready(seq)
    with pytest.raises(ValueError, match="did not confirm"):
        host.guarded_dispatch(seq, lambda: False)
    assert host.status()["revoked"] is True

    host = probe(0, 1, 2, 3, 4, strict=False)
    seq = host.capture()
    host.decision_ready(seq)
    host.guarded_dispatch(seq, lambda: None)  # Backward-compatible legacy host
    host.action_ack(seq)
    assert host.finalize().capture_count == 1


def test_false_confirmation_revokes_previous_completed_samples() -> None:
    host = probe(0, 1, 2, 3, 4, 5, 6, 7)
    first = host.capture()
    host.decision_ready(first)
    host.guarded_dispatch(first, lambda: True)
    host.action_ack(first)
    second = host.capture()
    host.decision_ready(second)
    with pytest.raises(ValueError, match="did not confirm"):
        host.guarded_dispatch(second, lambda: False)
    assert host.status()["completed_frames"] == 0
    assert host.status()["revoked"] is True


def test_deadline_rejection_prevents_host_callback_invocation() -> None:
    called: list[int] = []
    host = probe(0, 9_000_000, 10_000_001)
    seq = host.capture()
    host.decision_ready(seq)
    with pytest.raises(ValueError, match="expired before"):
        host.guarded_dispatch(seq, lambda: called.append(seq) or True)
    assert called == []
    assert host.status()["action_deadline_violations"] == 1


def test_bad_confirmation_configuration_is_rejected() -> None:
    for invalid in (1, None, "yes"):
        with pytest.raises(TypeError, match="must be bool"):
            HostMonotonicGameProbe(
                owner_approved=True, max_action_age_ns=1_000_000,
                require_submit_confirmation=invalid,  # type: ignore[arg-type]
            )
    with pytest.raises(ValueError, match="requires an action deadline"):
        HostMonotonicGameProbe(
            owner_approved=True, require_submit_confirmation=True,
        )


def test_callback_exception_still_revokes_and_never_confirms() -> None:
    host = probe(0, 1, 2)
    seq = host.capture()
    host.decision_ready(seq)

    def failed() -> bool:
        raise OSError("private host failed")

    with pytest.raises(OSError, match="host failed"):
        host.guarded_dispatch(seq, failed)
    assert host.status()["revoked"] is True
    assert host.status()["host_submit_rejections"] == 0  # exception, not explicit rejection


def test_strict_report_never_claims_delivery_or_exposes_callback() -> None:
    host = probe(0, 1, 2, 3, 4)
    seq = host.capture()
    host.decision_ready(seq)
    host.guarded_dispatch(seq, lambda: True)
    host.action_ack(seq)
    report = host.finalize().private_report()
    assert report["independent_gameplay_proof"] is False
    assert report["timing_attested"] is False
    status = host.status()
    assert status["host_submission_attested"] is False
    assert "secret" not in str(status)
    assert "callback" not in str(status)
