"""Offline adversarial tests: host-watchdog clock, signed telemetry and journal.

No network transport, actual game process, Windows input, OBS or broadcast.
"""
from __future__ import annotations

import pytest

from star.authoritative_game_telemetry_source import AuthoritativeGameTelemetrySource
from star.game_state_transition_witness import GameStateSample, VerifiedGameStateObserver
from star.game_telemetry_source_bridge import AuthenticatedGameTelemetryBridge
from star.game_telemetry_liveness_guard import (
    GameTelemetryLivenessGuard, GameTelemetryLivenessLost,
)
from star.stream_episode_journal import StreamEpisodeJournal


SOURCE_KEY = b"source-only-test-key-000000000000"
MOMENT_KEY = b"moment-only-test-key-000000000000"


class Clock:
    def __init__(self) -> None:
        self.t = 100.0
        self.error: str | None = None

    def __call__(self) -> float:
        if self.error == "exception":
            raise RuntimeError("PRIVATE_CREDENTIAL_MUST_NOT_LEAK")
        if self.error == "nan":
            return float("nan")
        if self.error == "bool":
            return True  # type: ignore[return-value]
        return self.t

    def advance(self, seconds: float = 0.04) -> None:
        self.t += seconds


class Engine:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.frame = 0
        self.checkpoint = 0
        self.phase = "playing"

    def read(self) -> GameStateSample:
        self.clock.advance()
        self.frame += 1
        return GameStateSample(self.frame, 1, self.phase, self.checkpoint)


def rig(*, silence: float = 0.25, ingest_ms: float = 100.0):
    clock = Clock()
    engine = Engine(clock)
    journal = StreamEpisodeJournal(receipt_key=MOMENT_KEY)
    journal.enable(owner_approved=True)
    assert journal.session_id is not None
    observer = VerifiedGameStateObserver(
        game_scope="private_owner_game", session_id=journal.session_id,
        receipt_key=MOMENT_KEY, clock=clock,
    )
    observer.enable(owner_approved=True)
    bridge = AuthenticatedGameTelemetryBridge(
        source_id="private_engine", session_id=journal.session_id,
        source_key=SOURCE_KEY, observer=observer, journal=journal,
    )
    bridge.enable(owner_approved=True)
    source = AuthoritativeGameTelemetrySource(
        source_id="private_engine", session_id=journal.session_id,
        source_key=SOURCE_KEY, trusted_reader=engine.read, clock=clock,
    )
    source.enable(owner_approved=True)
    guard = GameTelemetryLivenessGuard(
        bridge, clock=clock, max_silence_s=silence, max_ingest_ms=ingest_ms,
    )
    return clock, engine, source, guard, bridge, journal


def test_complete_verified_pipeline_remains_private_and_nonbroadcast():
    clock, engine, source, guard, bridge, journal = rig()
    assert not guard.metrics().active
    with pytest.raises(GameTelemetryLivenessLost):
        guard.accept(b"not-an-authorized-frame")
    with pytest.raises(PermissionError):
        guard.arm(owner_approved=False)
    guard.arm(owner_approved=True)
    assert guard.accept(source.poll()) is None
    assert guard.check().accepted_frames == 1
    engine.checkpoint = 1
    assert guard.accept(source.poll()) is None
    observed = guard.accept(source.poll())
    assert observed is not None and observed.moment.kind == "checkpoint"
    engine.phase = "won"
    assert guard.accept(source.poll()) is None
    observed = guard.accept(source.poll())
    assert observed is not None and observed.moment.kind == "win"
    entries = journal.recall(now_s=clock.t, game_scope="private_owner_game")
    assert len(entries) == 2
    assert not any(entry.authorized_to_speak for entry in entries)
    assert guard.metrics().accepted_frames == 5
    assert guard.metrics().checks == 1
    assert bridge.metrics()["recorded_events"] == 2
    assert guard.metrics().active
    guard.disable()
    assert not guard.metrics().active
    assert journal.session_id is None
    assert not journal.recall(now_s=clock.t, game_scope="private_owner_game")


def test_no_first_packet_revokes_at_silence_deadline():
    clock, _, _, guard, bridge, journal = rig()
    guard.arm(owner_approved=True)
    clock.advance(0.25)
    assert guard.check().active
    clock.advance(0.00001)
    with pytest.raises(GameTelemetryLivenessLost):
        guard.check()
    assert guard.metrics().revoked and not bridge.active
    assert journal.session_id is None


def test_silent_transport_after_authenticated_frame_clears_private_memory():
    clock, engine, source, guard, bridge, journal = rig()
    guard.arm(owner_approved=True)
    guard.accept(source.poll())
    engine.checkpoint = 1
    guard.accept(source.poll())
    guard.accept(source.poll())
    assert journal.recall(now_s=clock.t, game_scope="private_owner_game")
    clock.advance(0.4)
    with pytest.raises(GameTelemetryLivenessLost):
        guard.check()
    assert journal.session_id is None
    assert not bridge.active
    with pytest.raises(GameTelemetryLivenessLost):
        guard.accept(source.poll())
    assert guard.metrics().accepted_frames == 3


def test_late_packet_is_rejected_before_it_can_enter_journal():
    clock, engine, source, guard, _, journal = rig()
    guard.arm(owner_approved=True)
    guard.accept(source.poll())
    clock.advance(0.27)
    engine.checkpoint = 1
    with pytest.raises(GameTelemetryLivenessLost):
        guard.accept(source.poll())
    assert journal.session_id is None
    assert guard.metrics().accepted_frames == 1


def test_slow_bridge_ingestion_revokes_even_if_it_accepted_a_real_event():
    clock, engine, source, guard, bridge, journal = rig(silence=0.8, ingest_ms=60)
    guard.arm(owner_approved=True)
    guard.accept(source.poll())
    engine.checkpoint = 1
    guard.accept(source.poll())
    original = bridge.accept

    def slow_accept(packet: bytes):
        clock.advance(0.09)
        return original(packet)

    bridge.accept = slow_accept  # type: ignore[method-assign]
    with pytest.raises(GameTelemetryLivenessLost):
        guard.accept(source.poll())
    assert journal.session_id is None
    assert not guard.metrics().active


def test_accept_finished_after_silence_deadline_does_not_reset_timeout():
    clock, _, source, guard, bridge, journal = rig(silence=0.25, ingest_ms=900)
    guard.arm(owner_approved=True)
    original = bridge.accept

    def slow_accept(packet: bytes):
        clock.advance(0.28)
        return original(packet)

    bridge.accept = slow_accept  # type: ignore[method-assign]
    with pytest.raises(GameTelemetryLivenessLost):
        guard.accept(source.poll())
    assert journal.session_id is None
    assert not bridge.active


@pytest.mark.parametrize("bad", ["exception", "nan", "bool"])
def test_invalid_watchdog_clock_revokes_without_exposing_callback_error(bad):
    clock, _, _, guard, bridge, journal = rig()
    guard.arm(owner_approved=True)
    clock.error = bad
    with pytest.raises(GameTelemetryLivenessLost) as exc:
        guard.check()
    assert "PRIVATE_CREDENTIAL" not in str(exc.value)
    assert not bridge.active and journal.session_id is None


def test_clock_reversal_revokes_even_before_silence_limit():
    clock, _, source, guard, _, journal = rig()
    guard.arm(owner_approved=True)
    guard.accept(source.poll())
    clock.advance(-0.5)
    with pytest.raises(GameTelemetryLivenessLost):
        guard.check()
    assert journal.session_id is None


def test_bridge_direct_revocation_detected_by_host_watchdog():
    _, _, _, guard, bridge, journal = rig()
    guard.arm(owner_approved=True)
    bridge.disable()
    with pytest.raises(GameTelemetryLivenessLost):
        guard.check()
    assert journal.session_id is None
    assert guard.metrics().revoked


def test_replayed_signed_packet_fails_closed_and_latches():
    _, _, source, guard, bridge, journal = rig()
    guard.arm(owner_approved=True)
    packet = source.poll()
    guard.accept(packet)
    with pytest.raises(GameTelemetryLivenessLost):
        guard.accept(packet)
    assert not bridge.active and journal.session_id is None
    with pytest.raises(GameTelemetryLivenessLost):
        guard.arm(owner_approved=True)
    with pytest.raises(GameTelemetryLivenessLost):
        guard.check()


@pytest.mark.parametrize("packet", [b"", b"{}", b"garbage", b"\x00" * 512])
def test_corrupt_transport_payload_fail_closed(packet):
    _, _, _, guard, bridge, journal = rig()
    guard.arm(owner_approved=True)
    with pytest.raises(GameTelemetryLivenessLost):
        guard.accept(packet)
    assert not bridge.active and journal.session_id is None


@pytest.mark.parametrize("kwargs", [
    {"max_silence_s": float("nan")},
    {"max_silence_s": 0.0},
    {"max_silence_s": 11.0},
    {"max_silence_s": True},
    {"max_ingest_ms": 0.1},
    {"max_ingest_ms": float("inf")},
    {"max_ingest_ms": False},
    {"clock": 3},
])
def test_rejects_invalid_guard_settings(kwargs):
    _, _, _, _, bridge, _ = rig()
    with pytest.raises((TypeError, ValueError)):
        GameTelemetryLivenessGuard(bridge, **kwargs)


def test_disarmed_guard_cannot_restart_and_exposes_no_keys():
    _, _, _, guard, bridge, journal = rig()
    guard.arm(owner_approved=True)
    with pytest.raises(GameTelemetryLivenessLost):
        guard.arm(owner_approved=True)
    guard.disable()
    assert journal.session_id is None and not bridge.active
    with pytest.raises(GameTelemetryLivenessLost):
        guard.arm(owner_approved=True)
    assert SOURCE_KEY.decode() not in repr(guard.metrics())
    assert MOMENT_KEY.decode() not in repr(guard.metrics())
