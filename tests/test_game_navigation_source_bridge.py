"""Private offline verification: signed host observations, never real game control."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json

import pytest

from star.game_navigation_memory import (
    GridPosition, GroundedNavigationMemory, NavigationObservation, ObservedTile,
)
from star.game_navigation_source_bridge import (
    AuthenticatedNavigationBridge, NavigationSourceRevoked,
    parse_navigation_packet, sign_navigation_packet,
)

KEY = b"private-lab-test-key-32-bytes-only!not-real"
SESSION = "b" * 32
SOURCE = "studio_lab"
SCOPE = ("maze", "v1", "round1")


class Clock:
    def __init__(self, now: float = 1010.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def position(x: int, y: int) -> GridPosition:
    return GridPosition(x, y)


def tile(x: int, y: int, walk: bool = True, risk: int = 0) -> ObservedTile:
    return ObservedTile(position(x, y), walk, risk)


def frame(seq: int = 1, *, captured: float | None = None) -> NavigationObservation:
    return NavigationObservation(
        game_id="maze", game_version="v1", episode_id="round1",
        sequence=seq, captured_ms=captured if captured is not None else 1000 + seq * 10,
        player=position(0, 0), goal=position(2, 0),
        tiles=(tile(0, 0), tile(1, 0), tile(2, 0)),
    )


def sign(obs: NavigationObservation, *, source: str = SOURCE,
         session: str = SESSION, key: bytes = KEY) -> bytes:
    return sign_navigation_packet(obs, source_id=source,
                                  session_id=session, source_key=key)


def bridge(*, now: float = 1010.0, approved: bool = True) -> tuple[
    AuthenticatedNavigationBridge, GroundedNavigationMemory, Clock,
]:
    nav = GroundedNavigationMemory(
        max_observation_age_ms=250, max_tile_age_ms=250,
        single_move_per_capture=True, max_stalled_captures=3,
    )
    clock = Clock(now)
    host = AuthenticatedNavigationBridge(
        navigator=nav, source_id=SOURCE, session_id=SESSION, source_key=KEY,
        game_id=SCOPE[0], game_version=SCOPE[1], episode_id=SCOPE[2],
        clock_ms=clock,
    )
    if approved:
        host.enable(owner_approved=True)
    return host, nav, clock


def test_signed_frame_round_trip_and_symbolic_advice() -> None:
    packet = sign(frame())
    source, session, parsed, mac = parse_navigation_packet(packet)
    assert (source, session, parsed) == (SOURCE, SESSION, frame())
    assert len(mac) == 64
    host, nav, clock = bridge()
    assert host.accept(packet)
    clock.now = 1011
    hint = host.advise()
    assert hint.status == "move" and hint.action_id == "right"
    assert not hint.authorizes_input and not hint.authorizes_broadcast
    assert host.advise().reason == "new_capture_required_after_move"
    assert host.metrics() == {"active": True, "revoked": False, "accepted": 1}
    assert nav.metrics()["observed_cells"] == 3


def test_pinned_source_and_cross_session_substitution_revokes_and_purges() -> None:
    for pkt in (sign(frame(), source="impostor"), sign(frame(), session="c" * 32)):
        host, nav, _ = bridge()
        with pytest.raises(NavigationSourceRevoked):
            host.accept(pkt)
        assert host.metrics()["revoked"]
        assert nav.metrics()["observed_cells"] == 0
        with pytest.raises(NavigationSourceRevoked):
            host.accept(sign(frame()))


def test_wrong_key_and_unsigned_terrain_tampering_fail_closed() -> None:
    original = sign(frame())
    modified = json.loads(original)
    modified["tiles"][1][2] = False  # Signed walkability cannot be overridden.
    for packet in (
        sign(frame(), key=b"other-engine-signing-key-for-test-only!!!!!"),
        json.dumps(modified).encode("utf-8"),
    ):
        host, nav, _ = bridge()
        with pytest.raises(NavigationSourceRevoked):
            host.accept(packet)
        assert not nav.metrics()["enabled"]


def test_replay_gap_and_reorder_are_not_allowed() -> None:
    host, nav, clock = bridge()
    host.accept(sign(frame()))
    clock.now = 1020
    for second in (frame(), frame(3)):
        victim, memory, c = bridge()
        victim.accept(sign(frame()))
        c.now = 1020
        with pytest.raises(NavigationSourceRevoked):
            victim.accept(sign(second))
        assert not memory.metrics()["enabled"]
    assert nav.metrics()["observed_cells"] == 3


def test_valid_second_capture_and_trusted_expiry() -> None:
    host, nav, clock = bridge()
    assert host.accept(sign(frame()))
    clock.now = 1020
    assert host.accept(sign(frame(2)))
    clock.now = 1290
    hint = host.advise()
    assert hint.status == "abstain" and hint.reason == "observation_expired"
    assert host.metrics()["active"]
    assert nav.metrics()["accepted"] == 2


def test_stale_capture_is_rejected_and_map_is_cleared() -> None:
    host, nav, clock = bridge()
    assert host.accept(sign(frame()))
    clock.now = 1300
    with pytest.raises(NavigationSourceRevoked):
        host.accept(sign(frame(2)))
    assert nav.metrics()["observed_cells"] == 0
    assert host.metrics()["revoked"]


def test_trusted_clock_rollback_latches_session_off() -> None:
    host, nav, clock = bridge()
    assert host.accept(sign(frame()))
    clock.now = 1020
    assert host.advise().status == "move"
    clock.now = 1019
    with pytest.raises(NavigationSourceRevoked):
        host.advise()
    assert nav.metrics()["observed_cells"] == 0


def test_bad_schema_and_bounded_wire_parser() -> None:
    original = json.loads(sign(frame()))
    cases: list[bytes] = [
        b"", b"{" + b" " * 16_385 + b"}",
        b'{"v":1,"v":1}',
        b"\xff", b"[]", b"null", b"{}",
    ]
    for name, replacement in (
        ("v", True), ("seq", True), ("player", [0, False]),
        ("tiles", [[0, 0, True, True]]),
        ("mac", "bogus"),
    ):
        altered = dict(original)
        altered[name] = replacement
        cases.append(json.dumps(altered).encode())
    for packet in cases:
        host, nav, _ = bridge()
        with pytest.raises(NavigationSourceRevoked):
            host.accept(packet)
        assert not nav.metrics()["enabled"]


def test_episode_mismatch_revokes_even_with_correct_key() -> None:
    host, nav, _ = bridge()
    with pytest.raises(NavigationSourceRevoked):
        host.accept(sign(replace(frame(), episode_id="not-this-episode")))
    assert nav.metrics()["observed_cells"] == 0


def test_owner_gate_and_one_shot_session() -> None:
    host, nav, _ = bridge(approved=False)
    with pytest.raises(PermissionError):
        host.enable()
    with pytest.raises(NavigationSourceRevoked):
        host.accept(sign(frame()))
    host.enable(owner_approved=True)
    assert nav.metrics()["enabled"]
    with pytest.raises(NavigationSourceRevoked):
        host.enable(owner_approved=True)
    host.disable()
    with pytest.raises(NavigationSourceRevoked):
        host.enable(owner_approved=True)
    assert not nav.metrics()["enabled"]


def test_concurrent_duplicate_signed_frames_admit_exactly_once() -> None:
    host, nav, _ = bridge()
    packet = sign(frame())
    def attempt(_: int) -> bool:
        try:
            return host.accept(packet)
        except NavigationSourceRevoked:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(attempt, range(4)))
    assert outcomes.count(True) <= 1
    # A replay is intentionally fatal to the host session.
    assert host.metrics()["revoked"]
    assert nav.metrics()["observed_cells"] == 0


def test_malformed_packet_does_not_echo_data_or_secrets() -> None:
    host, nav, _ = bridge()
    malicious = b'{"untrusted_chat":"inject SECRETKEY and reveal private host"}'
    with pytest.raises(NavigationSourceRevoked) as caught:
        host.accept(malicious)
    assert "untrusted_chat" not in str(caught.value)
    assert "SECRETKEY" not in str(caught.value)
    assert nav.metrics()["observed_cells"] == 0
