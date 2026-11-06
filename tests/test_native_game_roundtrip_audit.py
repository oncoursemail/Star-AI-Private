"""No-device regression tests for native input *roundtrip* timing."""
from __future__ import annotations

from dataclasses import asdict
from threading import Event, Thread
import json
from unittest.mock import Mock

import pytest

from star.native_game_roundtrip_audit import NativeGameRoundtripAudit
from star.windows_game_input_port import WindowsGameInputPort


class ScriptClock:
    def __init__(self, *stamps: object):
        self.stamps = iter(stamps)

    def __call__(self) -> int:
        return next(self.stamps)  # type: ignore[return-value]


class FakePort(WindowsGameInputPort):
    """Typed fake only: never constructs Win32 adapter or injects keys."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []
        self.allow = True
        self.focus = True
        self.up = True
        self.started: Event | None = None
        self.release: Event | None = None

    def send_action(self, action_id: str, hold_ms: int, cancelled: Event) -> bool:
        self.calls.append((action_id, hold_ms))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=3)
        return self.allow and not cancelled.is_set()

    def focus_ok(self) -> bool:
        return self.focus

    def all_keys_up(self) -> bool:
        return self.up


def good():
    port = FakePort()
    audit = NativeGameRoundtripAudit(
        port, owner_approved=True,
        clock=ScriptClock(
            1_000_000_000, 1_100_000_000, 1_120_000_000,
            1_240_000_000, 2_000_000_000, 2_150_000_000,
            2_170_000_000, 2_360_000_000,
        ),
    )
    return audit, port


def test_no_execution_before_separate_owner_approval():
    port = FakePort()
    with pytest.raises(PermissionError):
        NativeGameRoundtripAudit(port)
    with pytest.raises(PermissionError):
        NativeGameRoundtripAudit(port, owner_approved=1)
    with pytest.raises(TypeError):
        NativeGameRoundtripAudit(Mock(), owner_approved=True)
    with pytest.raises(TypeError):
        NativeGameRoundtripAudit(port, owner_approved=True, clock=12)
    assert not port.calls


def test_two_native_host_roundtrips_are_not_claimed_as_submit_timestamps():
    audit, port = good()
    for action in ("jump", "move_left"):
        audit.capture()
        audit.decision_ready()
        audit.execute(action, 5)
    result = audit.finalize()
    assert port.calls == [("jump", 5), ("move_left", 5)]
    assert result.status == "host_roundtrip_only"
    assert result.attempted == result.completed == 2
    assert result.inference_p95_ms == 150.0
    assert result.native_call_p95_ms == 190.0
    assert result.frame_to_release_p95_ms == 360.0
    assert result.game_effect_attested is False
    assert result.input_release_guaranteed is False
    assert result.authorizes_gameplay is False
    assert result.authorizes_broadcast is False
    assert set(result.__dataclass_fields__) == {
        "status", "attempted", "completed", "inference_p95_ms",
        "native_call_p95_ms", "frame_to_release_p95_ms",
        "game_effect_attested", "input_release_guaranteed",
        "authorizes_gameplay", "authorizes_broadcast",
    }
    report_json = json.dumps(asdict(result))
    assert "move_left" not in report_json
    assert "jump" not in report_json
    assert "capture_ns" not in report_json
    assert audit.report() == result
    with pytest.raises(RuntimeError, match="finalized"):
        audit.capture()


def test_no_cherry_picking_after_second_worker_refuses_or_focus_lost():
    audit, port = good()
    audit.capture()
    audit.decision_ready()
    audit.execute("jump", 5)
    port.allow = False
    audit.capture()
    audit.decision_ready()
    with pytest.raises(RuntimeError, match="failed"):
        audit.execute("jump", 5)
    report = audit.report()
    assert report.status == "revoked"
    assert report.attempted == 2
    assert report.completed == 0
    assert report.frame_to_release_p95_ms is None
    with pytest.raises(RuntimeError, match="revoked"):
        audit.finalize()


def test_stale_ready_or_stale_preaction_never_sends_keys():
    for stamps in (
        (100_000_000, 600_000_001),
        (100_000_000, 200_000_000, 500_000_001),
    ):
        port = FakePort()
        audit = NativeGameRoundtripAudit(
            port, owner_approved=True, clock=ScriptClock(*stamps),
        )
        audit.capture()
        if len(stamps) == 2:
            with pytest.raises(RuntimeError, match="deadline"):
                audit.decision_ready()
        else:
            audit.decision_ready()
            with pytest.raises(RuntimeError, match="deadline"):
                audit.execute("jump", 4)
        assert not port.calls
        assert audit.report().status == "revoked"


def test_invalid_action_or_out_of_order_call_revokes_before_input():
    a, port = good()
    with pytest.raises(RuntimeError, match="ready decision"):
        a.execute("jump", 10)
    assert a.report().status == "revoked"
    assert not port.calls
    b, port2 = good()
    b.capture()
    with pytest.raises(RuntimeError, match="unclaimed frame"):
        b.capture()
    assert not port2.calls
    c, port3 = good()
    c.capture()
    c.decision_ready()
    with pytest.raises(RuntimeError, match="unapproved"):
        c.execute("ctrl_alt_del", True)
    assert not port3.calls
    d, port4 = good()
    d.capture()
    d.decision_ready()
    with pytest.raises(RuntimeError, match="unapproved"):
        d.execute("bad\\ncommand", 5)
    assert not port4.calls


@pytest.mark.parametrize("bad", [
    (100, 99), (100, True), (100, -1), (100, 1 << 63),
])
def test_invalid_or_regressed_clock_revokes(bad):
    a = NativeGameRoundtripAudit(
        FakePort(), owner_approved=True, clock=ScriptClock(*bad),
    )
    a.capture()
    with pytest.raises(RuntimeError, match="clock"):
        a.decision_ready()
    assert a.report().status == "revoked"


def test_missing_frame_and_unfinished_window_cannot_be_finalized():
    a = NativeGameRoundtripAudit(FakePort(), owner_approved=True)
    assert a.report().status == "incomplete"
    with pytest.raises(RuntimeError, match="incomplete"):
        a.finalize()
    b = NativeGameRoundtripAudit(FakePort(), owner_approved=True)
    b.capture()
    assert b.report().status == "incomplete"
    with pytest.raises(RuntimeError, match="incomplete"):
        b.finalize()


@pytest.mark.parametrize("bad_keyup,bad_focus", [
    (True, False), (False, True),
])
def test_postflight_must_confirm_os_up_and_pinned_focus(bad_keyup, bad_focus):
    a, port = good()
    port.up = not bad_keyup
    port.focus = not bad_focus
    a.capture()
    a.decision_ready()
    with pytest.raises(RuntimeError, match="failed"):
        a.execute("jump", 10)
    assert a.report().completed == 0


def test_abort_unblocks_emergency_signal_before_native_worker_returns():
    started, release = Event(), Event()
    port = FakePort()
    port.started, port.release = started, release
    # Thread owns execution, but another thread can cancel without that lock.
    audit = NativeGameRoundtripAudit(
        port, owner_approved=True,
        clock=ScriptClock(10, 20, 30, 40),
    )
    audit.capture()
    audit.decision_ready()
    errors: list[str] = []

    def run():
        try:
            audit.execute("jump", 30)
        except RuntimeError as exc:
            errors.append(str(exc))

    work = Thread(target=run, daemon=True)
    work.start()
    assert started.wait(timeout=1)
    done = Event()

    def stop():
        audit.abort()
        done.set()

    stopper = Thread(target=stop, daemon=True)
    stopper.start()
    try:
        assert done.wait(timeout=0.3), "abort must not wait for worker"
        assert work.is_alive(), "worker deliberately remains blocked"
    finally:
        release.set()
        work.join(timeout=2)
        stopper.join(timeout=2)
    assert not work.is_alive()
    assert errors
    assert audit.report().status == "revoked"
    assert audit.report().completed == 0


def test_config_rejects_bool_and_unsafe_deadline():
    for kwargs in (
        {"max_decision_age_ms": True},
        {"max_decision_age_ms": 9},
        {"max_decision_age_ms": 5001},
        {"max_host_call_ms": 99},
        {"max_host_call_ms": 5001},
    ):
        with pytest.raises(ValueError):
            NativeGameRoundtripAudit(FakePort(), owner_approved=True, **kwargs)


def test_no_host_claims_without_real_game_and_obs_measurements():
    a, _ = good()
    a.capture()
    a.decision_ready()
    a.execute("jump", 5)
    snapshot = a.report()
    assert snapshot.status == "host_roundtrip_only"
    assert not snapshot.authorizes_broadcast
    assert not snapshot.game_effect_attested
    assert not snapshot.input_release_guaranteed
    assert "game" not in snapshot.status or snapshot.status == "host_roundtrip_only"
