"""No-game, no-audio, no-network watchdog supervision regression tests."""
from __future__ import annotations

from threading import Event, Lock
import time

import pytest

from star.authoritative_game_telemetry_source import AuthoritativeGameTelemetrySource
from star.game_state_transition_witness import GameStateSample, VerifiedGameStateObserver
from star.game_telemetry_liveness_guard import GameTelemetryLivenessGuard, GameTelemetryLivenessLost
from star.game_telemetry_source_bridge import AuthenticatedGameTelemetryBridge
from star.game_telemetry_tick_supervisor import GameTelemetryTickSupervisor
from star.stream_episode_journal import StreamEpisodeJournal


class Clock:
    def __init__(self) -> None:
        self._lock = Lock()
        self.t = 100.0
        self.broken = False

    def __call__(self) -> float:
        with self._lock:
            if self.broken:
                raise RuntimeError("SECRET_CLOCK_EXCEPTION")
            return self.t

    def advance(self, amount: float = 0.02) -> None:
        with self._lock:
            self.t += amount


class Engine:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.frame = 0
        self.checkpoint = 0

    def read(self) -> GameStateSample:
        self.clock.advance()
        self.frame += 1
        return GameStateSample(self.frame, 1, "playing", self.checkpoint)


def rig():
    clock = Clock()
    engine = Engine(clock)
    journal = StreamEpisodeJournal(receipt_key=b"moment_test_key_0000000000000000")
    journal.enable(owner_approved=True)
    assert journal.session_id is not None
    observer = VerifiedGameStateObserver(
        game_scope="owner_only_game", session_id=journal.session_id,
        receipt_key=b"moment_test_key_0000000000000000", clock=clock,
    )
    observer.enable(owner_approved=True)
    bridge = AuthenticatedGameTelemetryBridge(
        source_id="local_engine", session_id=journal.session_id,
        source_key=b"source_test_key_0000000000000000",
        observer=observer, journal=journal,
    )
    bridge.enable(owner_approved=True)
    source = AuthoritativeGameTelemetrySource(
        source_id="local_engine", session_id=journal.session_id,
        source_key=b"source_test_key_0000000000000000",
        trusted_reader=engine.read, clock=clock,
    )
    source.enable(owner_approved=True)
    guard = GameTelemetryLivenessGuard(bridge, clock=clock, max_silence_s=0.15)
    return clock, engine, journal, bridge, source, guard


def test_requires_owner_and_prearmed_receiver():
    _, _, _, _, _, guard = rig()
    supervisor = GameTelemetryTickSupervisor(guard, interval_s=0.02)
    with pytest.raises(PermissionError):
        supervisor.start()
    with pytest.raises(GameTelemetryLivenessLost):
        supervisor.start(owner_approved=True)
    guard.arm(owner_approved=True)
    supervisor.start(owner_approved=True)
    try:
        with pytest.raises(RuntimeError):
            supervisor.start(owner_approved=True)
    finally:
        supervisor.stop()
    assert not supervisor.metrics().active
    with pytest.raises(RuntimeError):
        supervisor.start(owner_approved=True)


@pytest.mark.parametrize("interval", [0, -1, 0.001, 0.1, 1.1, True, float("nan"), float("inf"), "0.02"])
def test_bad_interval_rejected(interval):
    *_, guard = rig()
    with pytest.raises(ValueError):
        GameTelemetryTickSupervisor(guard, interval_s=interval)


def test_signed_source_to_private_journal_with_live_host_ticks():
    clock, engine, journal, bridge, source, guard = rig()
    guard.arm(owner_approved=True)
    supervisor = GameTelemetryTickSupervisor(guard, interval_s=0.02)
    supervisor.start(owner_approved=True)
    try:
        assert supervisor.accept(source.poll()) is None
        engine.checkpoint = 1
        assert supervisor.accept(source.poll()) is None
        moment = supervisor.accept(source.poll())
        assert moment is not None and moment.moment.kind == "checkpoint"
        assert len(journal.recall(now_s=clock(), game_scope="owner_only_game")) == 1
        assert not any(x.authorized_to_speak for x in journal.recall(
            now_s=clock(), game_scope="owner_only_game"
        ))
        # Tick happens independently of a packet or an explicit health() call.
        time.sleep(0.075)
        report = supervisor.health()
        assert report.active and report.checks >= 1 and report.accepted_frames == 3
        assert report.revoked is False and bridge.active
    finally:
        supervisor.stop()
    assert journal.session_id is None


def test_no_packets_background_tick_revokes_and_calls_host_stop_once():
    clock, engine, journal, bridge, source, guard = rig()
    calls: list[str] = []
    stopped = Event()
    def on_lost() -> None:
        calls.append("stop")
        stopped.set()

    guard.arm(owner_approved=True)
    supervisor = GameTelemetryTickSupervisor(
        guard, interval_s=0.01, on_lost=on_lost,
    )
    supervisor.start(owner_approved=True)
    # Record a real, verified practice checkpoint before simulated sensor loss.
    supervisor.accept(source.poll())
    engine.checkpoint = 1
    supervisor.accept(source.poll())
    supervisor.accept(source.poll())
    assert journal.recall(now_s=clock(), game_scope="owner_only_game")
    clock.advance(0.3)
    assert stopped.wait(timeout=1.0), "watchdog must detect silent transport"
    assert calls == ["stop"]
    assert not supervisor.metrics().active
    assert supervisor.metrics().revoked
    assert not bridge.active and journal.session_id is None
    with pytest.raises(GameTelemetryLivenessLost):
        supervisor.accept(source.poll())
    supervisor.stop()
    assert calls == ["stop"]


def test_invalid_packet_trips_and_does_not_repeat_callback():
    _, _, journal, bridge, _, guard = rig()
    hits = []
    guard.arm(owner_approved=True)
    supervisor = GameTelemetryTickSupervisor(
        guard, interval_s=0.01, on_lost=lambda: hits.append(1),
    )
    supervisor.start(owner_approved=True)
    with pytest.raises(GameTelemetryLivenessLost):
        supervisor.accept(b"not-signed-packet")
    with pytest.raises(GameTelemetryLivenessLost):
        supervisor.health()
    assert hits == [1]
    assert journal.session_id is None and not bridge.active
    supervisor.stop()


def test_clock_exception_is_sanitized_and_stop_callback_failure_is_reported():
    clock, _, journal, _, _, guard = rig()
    def broken_stop() -> None:
        raise RuntimeError("PRIVATE_STOP_HOOK")

    guard.arm(owner_approved=True)
    supervisor = GameTelemetryTickSupervisor(
        guard, interval_s=0.01, on_lost=broken_stop,
    )
    supervisor.start(owner_approved=True)
    clock.broken = True
    for _ in range(100):
        if supervisor.metrics().revoked:
            break
        time.sleep(0.01)
    report = supervisor.metrics()
    assert report.revoked and report.stop_callback_failed
    with pytest.raises(GameTelemetryLivenessLost) as exc:
        supervisor.health()
    assert "SECRET" not in str(exc.value) and "PRIVATE" not in str(exc.value)
    assert journal.session_id is None
    supervisor.stop()


def test_unexpected_worker_exit_is_detected_on_ingest():
    _, _, journal, bridge, source, guard = rig()
    calls = []
    guard.arm(owner_approved=True)
    supervisor = GameTelemetryTickSupervisor(
        guard, interval_s=0.01, on_lost=lambda: calls.append("stop"),
    )
    supervisor.start(owner_approved=True)
    # Simulate a worker exiting without revoking its guard.
    supervisor._stop.set()
    assert supervisor._thread is not None
    supervisor._thread.join(timeout=1)
    with pytest.raises(GameTelemetryLivenessLost):
        supervisor.accept(source.poll())
    assert calls == ["stop"]
    assert journal.session_id is None and not bridge.active


def test_owner_stop_is_idempotent_and_does_not_raise_false_emergency():
    _, _, journal, bridge, _, guard = rig()
    calls = []
    guard.arm(owner_approved=True)
    supervisor = GameTelemetryTickSupervisor(
        guard, interval_s=0.02, on_lost=lambda: calls.append(1),
    )
    supervisor.start(owner_approved=True)
    supervisor.stop()
    supervisor.stop()
    assert calls == [] and journal.session_id is None and not bridge.active
    # A closed guard is terminal even on an intentional stop. Only on_lost
    # differentiates an emergency callback from ordinary owner shutdown.
    assert not supervisor.metrics().active and supervisor.metrics().revoked


def test_rejects_noncallable_callback_and_wrong_guard():
    *_, guard = rig()
    with pytest.raises(TypeError):
        GameTelemetryTickSupervisor(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        GameTelemetryTickSupervisor(guard, interval_s=0.02, on_lost="tool")  # type: ignore[arg-type]
