"""Adversarial checks for the real source-side v1 telemetry packet producer.

Synthetic trusted-engine fixtures only; no actual game, GPU, OBS or broadcast.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json

import pytest

from star.authoritative_game_telemetry_source import (
    AuthoritativeGameTelemetrySource, EngineSourceRevoked,
)
from star.game_state_transition_witness import (
    GameStateSample, VerifiedGameStateObserver,
)
from star.game_telemetry_source_bridge import (
    AuthenticatedGameTelemetryBridge, GameTelemetryTransportError,
    parse_telemetry_packet,
)
from star.stream_episode_journal import StreamEpisodeJournal


SOURCE_KEY = b"S" * 32
MOMENT_KEY = b"J" * 32
SOURCE = "private_owned_server"


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def tick(self, step: float = 0.04) -> None:
        self.t += step


class Engine:
    def __init__(self, clock: Clock):
        self.clock = clock
        self.frame = 0
        self.round = 1
        self.phase = "playing"
        self.checkpoint = 0
        self.calls = 0

    def read(self) -> GameStateSample:
        self.calls += 1
        self.clock.tick()
        self.frame += 1
        return GameStateSample(self.frame, self.round, self.phase, self.checkpoint)


def source_for(clock=None, engine=None, *, session="a" * 32, **kwargs):
    clock = clock or Clock()
    engine = engine or Engine(clock)
    source = AuthoritativeGameTelemetrySource(
        source_id=SOURCE, session_id=session, source_key=SOURCE_KEY,
        trusted_reader=engine.read, clock=clock, **kwargs,
    )
    return source, engine, clock


def enabled_source(**kwargs):
    source, engine, clock = source_for(**kwargs)
    source.enable(owner_approved=True)
    return source, engine, clock


def test_end_to_end_source_to_receiver_to_independent_witness_to_private_journal():
    clock = Clock()
    engine = Engine(clock)
    journal = StreamEpisodeJournal(receipt_key=MOMENT_KEY)
    journal.enable(owner_approved=True)
    observer = VerifiedGameStateObserver(
        game_scope="owned_game", session_id=journal.session_id,
        receipt_key=MOMENT_KEY, clock=clock, max_gap_s=0.5,
    )
    observer.enable(owner_approved=True)
    bridge = AuthenticatedGameTelemetryBridge(
        source_id=SOURCE, session_id=journal.session_id,
        source_key=SOURCE_KEY, observer=observer, journal=journal,
    )
    bridge.enable(owner_approved=True)
    source, _, _ = source_for(clock, engine, session=journal.session_id)
    source.enable(owner_approved=True)
    packet = source.poll()
    assert parse_telemetry_packet(packet).seq == 1
    assert bridge.accept(packet) is None
    engine.checkpoint = 1
    assert bridge.accept(source.poll()) is None
    checkpoint = bridge.accept(source.poll())
    assert checkpoint is not None and checkpoint.moment.kind == "checkpoint"
    engine.phase = "won"
    assert bridge.accept(source.poll()) is None
    win = bridge.accept(source.poll())
    assert win is not None and win.moment.kind == "win"
    assert len(journal.recall(now_s=clock.t, game_scope="owned_game")) == 2
    assert all(
        not row.authorized_to_speak
        for row in journal.recall(now_s=clock.t, game_scope="owned_game")
    )
    assert source.metrics().signed_frames == 5
    assert bridge.metrics()["recorded_events"] == 2
    assert bridge.active and observer.active


def test_disabled_by_default_requires_explicit_owner_and_new_instance_after_stop():
    source, _, _ = source_for()
    with pytest.raises(EngineSourceRevoked):
        source.poll()
    with pytest.raises(PermissionError):
        source.enable()
    with pytest.raises(PermissionError):
        source.enable(owner_approved=1)  # type: ignore[arg-type]
    source.enable(owner_approved=True)
    with pytest.raises(EngineSourceRevoked):
        source.enable(owner_approved=True)
    source.disable()
    assert not source.metrics().active and source.metrics().revoked
    with pytest.raises(EngineSourceRevoked):
        source.poll()
    with pytest.raises(EngineSourceRevoked):
        source.enable(owner_approved=True)


def test_source_only_reads_independent_callback_and_never_exposes_sign_api():
    source, engine, _ = enabled_source()
    with pytest.raises(TypeError):
        source.poll({"phase": "won"})  # type: ignore[call-arg]
    assert engine.calls == 0
    assert "mac" not in repr(source.metrics())
    assert SOURCE_KEY.decode() not in repr(source.metrics())
    assert len(source.poll()) <= 512
    assert engine.calls == 1


@pytest.mark.parametrize("kwargs", [
    {"source_id": "_invalid"},
    {"session_id": "bad"},
    {"source_key": b"bad"},
    {"max_gap_s": float("nan")},
    {"max_read_ms": 0},
    {"max_frame_step": 0},
    {"max_frame_step": True},
    {"max_read_ms": True},
])
def test_source_rejects_invalid_configuration(kwargs):
    clock = Clock()
    engine = Engine(clock)
    options = dict(source_id=SOURCE, session_id="a" * 32,
                   source_key=SOURCE_KEY, trusted_reader=engine.read,
                   clock=clock)
    options.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        AuthoritativeGameTelemetrySource(**options)


def test_source_rejects_reader_exceptions_without_leaking_details_or_key():
    clock = Clock()
    secret_message = "SOURCE_KEY_DO_NOT_LOG"
    def broken():
        raise RuntimeError(secret_message)
    source = AuthoritativeGameTelemetrySource(
        source_id=SOURCE, session_id="a" * 32,
        source_key=SOURCE_KEY, trusted_reader=broken, clock=clock,
    )
    source.enable(owner_approved=True)
    with pytest.raises(EngineSourceRevoked) as exc:
        source.poll()
    assert secret_message not in str(exc.value)
    assert not source.metrics().active
    with pytest.raises(EngineSourceRevoked):
        source.poll()


@pytest.mark.parametrize("kind", [
    "wrong_type", "stalled_frame", "frame_jump", "round_reverse",
    "round_jump", "checkpoint_reverse", "terminal_reversal", "gap",
    "clock_reverse", "reader_stall", "new_round_not_playing",
])
def test_invalid_authoritative_state_revokes_and_never_reissues(kind):
    source, engine, clock = enabled_source()
    source.poll()
    if kind == "wrong_type":
        source._reader = lambda: {"frame": 2, "phase": "won"}
    elif kind == "stalled_frame":
        engine.frame = 0
    elif kind == "frame_jump":
        engine.frame = 500
    elif kind == "round_reverse":
        engine.round = 2
        source.poll()
        engine.round = 1
    elif kind == "round_jump":
        engine.round = 3
    elif kind == "checkpoint_reverse":
        engine.checkpoint = 3
        source.poll()
        engine.checkpoint = 2
    elif kind == "terminal_reversal":
        engine.phase = "won"
        source.poll()
        engine.phase = "playing"
    elif kind == "gap":
        clock.tick(2.0)
    elif kind == "clock_reverse":
        clock.tick(-1.0)
    elif kind == "reader_stall":
        original = engine.read
        def slow():
            value = original()
            clock.tick(1)
            return value
        source._reader = slow
    elif kind == "new_round_not_playing":
        engine.round = 2
        engine.phase = "won"
    before = source.metrics().signed_frames
    with pytest.raises(EngineSourceRevoked):
        source.poll()
    assert source.metrics().signed_frames == before
    assert source.metrics().revoked
    with pytest.raises(EngineSourceRevoked):
        source.poll()


def test_source_frame_budget_is_strict_and_cannot_wrap_to_one():
    source, _, _ = enabled_source()
    for seq in range(1, 4097):
        packet = source.poll()
        assert parse_telemetry_packet(packet).seq == seq
    with pytest.raises(EngineSourceRevoked):
        source.poll()
    assert source.metrics().signed_frames == 4096
    assert source.metrics().revoked


def test_concurrent_polls_are_individually_signed_and_sequential():
    source, engine, _ = enabled_source()
    with ThreadPoolExecutor(max_workers=8) as pool:
        packets = list(pool.map(lambda _: source.poll(), range(40)))
    assert sorted(parse_telemetry_packet(p).seq for p in packets) == list(range(1, 41))
    assert engine.calls == 40
    assert len(set(packets)) == 40


def test_json_tampering_fails_closed_at_receiver_and_does_not_create_memory():
    clock = Clock()
    engine = Engine(clock)
    journal = StreamEpisodeJournal(receipt_key=MOMENT_KEY)
    journal.enable(owner_approved=True)
    observer = VerifiedGameStateObserver(
        game_scope="owned_game", session_id=journal.session_id,
        receipt_key=MOMENT_KEY, clock=clock,
    )
    observer.enable(owner_approved=True)
    bridge = AuthenticatedGameTelemetryBridge(
        source_id=SOURCE, session_id=journal.session_id,
        source_key=SOURCE_KEY, observer=observer, journal=journal,
    )
    bridge.enable(owner_approved=True)
    source, _, _ = source_for(clock, engine, session=journal.session_id)
    source.enable(owner_approved=True)
    message = json.loads(source.poll())
    message["phase"] = "won"  # A model/chat relay can't change signed facts.
    with pytest.raises(GameTelemetryTransportError):
        bridge.accept(json.dumps(message).encode("ascii"))
    assert not bridge.active
    assert journal.session_id is None
    assert journal.recall(now_s=clock.t, game_scope="owned_game") == ()
    # A source remains active locally after the TRANSPORT fails; the
    # deployment host must independently disable it, never silently retry.
    source.disable()
    assert source.metrics().revoked


def test_signed_payload_cannot_prove_truth_of_compromised_reader():
    source, engine, _ = enabled_source()
    assert parse_telemetry_packet(source.poll()).phase == "playing"

    def untrusted():
        return replace(engine.read(), phase="won")  # Valid shape, unproven origin.

    source._reader = untrusted
    # A compromised authoritative reader can sign a false claimed win.
    # Signatures defend the transport, NOT the source of truth itself.
    data = parse_telemetry_packet(source.poll())
    assert data.phase == "won"
    assert data.seq == 2
