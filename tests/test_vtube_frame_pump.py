from __future__ import annotations

import threading
import time

import pytest

from star.stream_motion import MotionFrame
from star.stream_stage import StagePlan
from star.vtube_frame_pump import VTubeFramePump


def plan(seq=1):
    return StagePlan(
        seq, f"signal-{seq}", "viewer_question", "observed", "normal",
        False, 100.0, "safe", None, 0.0,
    )


def frame(at_s):
    return MotionFrame(at_s, 0.2, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


class FakeHost:
    def __init__(self):
        self.ready = True
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.fail = False

    def send_frame(
        self, p, *, playback_epoch, frame, audible_cursor_s, sampled_ms
    ):
        self.entered.set()
        if self.block:
            assert self.release.wait(2.0)
        if self.fail:
            raise OSError("socket failure")
        self.calls.append((p, playback_epoch, frame.at_s, audible_cursor_s, sampled_ms))
        return True


def stamp():
    return time.monotonic() * 1000.0


def wait_for(predicate, timeout=1.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def make_pump(host):
    pump = VTubeFramePump(host, flush_timeout_ms=500)
    pump.start()
    return pump


def test_latest_wins_replaces_pending_frames_without_blocking_producer():
    host = FakeHost()
    host.block = True
    pump = make_pump(host)
    p = plan()
    try:
        assert pump.arm(p, playback_epoch="epoch-1")
        assert pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.0),
            audible_cursor_s=0.0, sampled_ms=stamp(),
        )
        assert host.entered.wait(1.0)
        assert pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.033),
            audible_cursor_s=0.033, sampled_ms=stamp(),
        )
        assert pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.066),
            audible_cursor_s=0.066, sampled_ms=stamp(),
        )
        host.release.set()
        assert wait_for(lambda: len(host.calls) == 2)
        assert [call[2] for call in host.calls] == [0.0, 0.066]
        assert pump.metrics()["replaced"] == 1
        assert pump.metrics()["pending"] is False
    finally:
        host.release.set()
        assert pump.close()


def test_flush_is_a_barrier_for_inflight_send_and_revokes_new_submissions():
    host = FakeHost()
    host.block = True
    pump = make_pump(host)
    p = plan()
    result = []
    try:
        assert pump.arm(p, playback_epoch="epoch-1")
        assert pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.0),
            audible_cursor_s=0.0, sampled_ms=stamp(),
        )
        assert host.entered.wait(1.0)
        thread = threading.Thread(
            target=lambda: result.append(pump.flush_epoch("epoch-1", timeout_ms=1000))
        )
        thread.start()
        assert wait_for(lambda: pump.metrics()["active"] is False)
        assert not pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.033),
            audible_cursor_s=0.033, sampled_ms=stamp(),
        )
        assert thread.is_alive()
        host.release.set()
        thread.join(1.0)
        assert result == [True]
        assert pump.flush_epoch("epoch-1")
        assert len(host.calls) == 1
    finally:
        host.release.set()
        assert pump.close()


def test_stale_future_and_unheard_frames_are_rejected():
    host = FakeHost()
    pump = make_pump(host)
    p = plan()
    try:
        assert pump.arm(p, playback_epoch="epoch-1")
        assert not pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.0),
            audible_cursor_s=0.0, sampled_ms=stamp() - 200,
        )
        assert not pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.2),
            audible_cursor_s=0.0, sampled_ms=stamp(),
        )
        assert not pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.0),
            audible_cursor_s=0.2, sampled_ms=stamp(),
        )
        assert host.calls == []
        assert pump.metrics()["stale_dropped"] == 1
        assert pump.metrics()["rejected"] == 2
    finally:
        assert pump.close()


def test_epoch_and_plan_identity_are_enforced():
    host = FakeHost()
    pump = make_pump(host)
    p = plan()
    try:
        assert pump.arm(p, playback_epoch="epoch-1")
        assert not pump.submit(
            plan(), playback_epoch="epoch-1", frame=frame(0.0),
            audible_cursor_s=0.0, sampled_ms=stamp(),
        )
        assert not pump.submit(
            p, playback_epoch="wrong", frame=frame(0.0),
            audible_cursor_s=0.0, sampled_ms=stamp(),
        )
        assert pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.0),
            audible_cursor_s=0.0, sampled_ms=stamp(),
        )
        assert wait_for(lambda: len(host.calls) == 1)
        assert pump.flush_epoch("epoch-1")
        assert not pump.arm(p, playback_epoch="epoch-1")
        assert pump.arm(plan(2), playback_epoch="epoch-2")
    finally:
        assert pump.close()


def test_out_of_order_or_duplicate_frame_timestamps_are_rejected():
    host = FakeHost()
    pump = make_pump(host)
    p = plan()
    try:
        assert pump.arm(p, playback_epoch="epoch-1")
        assert pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.066),
            audible_cursor_s=0.066, sampled_ms=stamp(),
        )
        assert not pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.033),
            audible_cursor_s=0.066, sampled_ms=stamp(),
        )
        assert not pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.066),
            audible_cursor_s=0.066, sampled_ms=stamp(),
        )
        assert wait_for(lambda: len(host.calls) == 1)
    finally:
        assert pump.close()


def test_transport_failure_latches_fault_and_never_retries_old_frame():
    host = FakeHost()
    host.fail = True
    pump = make_pump(host)
    p = plan()
    try:
        assert pump.arm(p, playback_epoch="epoch-1")
        assert pump.submit(
            p, playback_epoch="epoch-1", frame=frame(0.0),
            audible_cursor_s=0.0, sampled_ms=stamp(),
        )
        assert wait_for(lambda: pump.metrics()["fault"] is True)
        assert pump.metrics()["send_failures"] == 1
        assert pump.metrics()["active"] is False
        assert not pump.arm(plan(2), playback_epoch="epoch-2")
        assert host.calls == []
    finally:
        assert pump.close()


def test_close_discards_pending_and_stops_worker():
    host = FakeHost()
    host.block = True
    pump = make_pump(host)
    p = plan()
    assert pump.arm(p, playback_epoch="epoch-1")
    assert pump.submit(
        p, playback_epoch="epoch-1", frame=frame(0.0),
        audible_cursor_s=0.0, sampled_ms=stamp(),
    )
    assert host.entered.wait(1.0)
    assert pump.submit(
        p, playback_epoch="epoch-1", frame=frame(0.033),
        audible_cursor_s=0.033, sampled_ms=stamp(),
    )
    result = []
    thread = threading.Thread(
        target=lambda: result.append(pump.close(timeout_ms=1000))
    )
    thread.start()
    assert wait_for(lambda: pump.metrics()["running"] is False)
    host.release.set()
    thread.join(1.0)
    assert result == [True]
    assert len(host.calls) == 1


def test_arm_requires_authenticated_and_registered_host():
    host = FakeHost()
    host.ready = False
    pump = make_pump(host)
    try:
        assert not pump.arm(plan(), playback_epoch="epoch-1")
        host.ready = True
        assert pump.arm(plan(), playback_epoch="epoch-2")
    finally:
        assert pump.close()
