"""Offline, credential-free OBS fake-host tests. Never starts a livestream."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from star.obs_readonly_benchmark_host import (
    ObsProbeError, ObsReadOnlyProbe,
)
from star.stream_obs_qos_gate import ObsFrameWindow
from star.stream_network_qos_gate import ObsTransportWindow


class Clock:
    def __init__(self):
        self.now = 1000.0

    def ms(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds * 1000


class FakeClient:
    def __init__(self):
        self.calls = []
        self.n = 0
        self.reconnect_at = None
        self.fail_at = None
        self.reset_at = None
        self.null_congestion_at = None

    def get_version(self):
        self.calls.append("get_version")
        return SimpleNamespace(obs_version="31.0")

    def get_stats(self):
        self.n += 1
        self.calls.append("get_stats")
        if self.n == self.fail_at:
            raise RuntimeError("private-OBS-credential")
        index = 0 if self.n == self.reset_at else self.n
        return SimpleNamespace(
            render_total_frames=1000 + 120 * index,
            render_skipped_frames=0, output_total_frames=1000 + 120 * index,
            output_skipped_frames=0,
            arbitrary_stream_key="DO_NOT_CAPTURE",
        )

    def get_stream_status(self):
        self.calls.append("get_stream_status")
        index = 0 if self.n == self.reset_at else self.n
        return SimpleNamespace(
            output_active=True, output_reconnecting=self.n == self.reconnect_at,
            output_duration=30000 + 1000 * index,
            output_bytes=1000000 + 50000 * index,
            output_skipped_frames=0,
            output_total_frames=1000 + 120 * index,
            output_congestion=None if self.n == self.null_congestion_at else 0,
            stream_key="DO_NOT_CAPTURE",
        )


def rig():
    clock, client = Clock(), FakeClient()
    process = {"identity": (123, 1234567.5)}
    connections = []

    def factory(**kwargs):
        connections.append(kwargs)
        return client

    def identity():
        return process["identity"]

    probe = ObsReadOnlyProbe(
        client_factory=factory,
        process_identity=identity,
        clock_ms=clock.ms,
        sleep=clock.sleep,
    )
    return probe, client, clock, process, connections


def capture(probe, **extra):
    return probe.capture(
        pair_id="a01", variant="candidate", game_id="obby",
        game_version="v01", duration_s=5, poll_interval_s=1.0, **extra,
    )


def test_fully_attested_capture_is_valid_and_serializes_for_existing_gates():
    probe, client, clock, _, connections = rig()
    with pytest.raises(PermissionError):
        probe.connect(password="not_logged")
    probe.connect(password="do_not_log", owner_approved=True)
    evidence = capture(probe, continuity_guard=lambda: True)
    assert evidence.continuity_attested
    assert evidence.frames.render_total == 600
    assert evidence.transport.total_frames == 600
    assert evidence.frames.end_ms == evidence.transport.end_ms
    assert evidence.frames.start_ms == evidence.transport.start_ms
    assert evidence.frames.session_id == evidence.transport.session_id
    assert evidence.transport.connected
    assert connections == [{
        "host": "127.0.0.1", "port": 4455, "password": "do_not_log",
        "timeout": 3,
    }]
    assert set(client.calls) == {
        "get_version", "get_stats", "get_stream_status",
    }
    frames_row, stream_row = evidence.jsonl_rows()
    assert ObsFrameWindow.from_dict(json.loads(frames_row)) == evidence.frames
    assert ObsTransportWindow.from_dict(json.loads(stream_row)) == evidence.transport
    assert "do_not_log" not in frames_row + stream_row
    assert "DO_NOT_CAPTURE" not in frames_row + stream_row
    assert "get_stream_settings" not in client.calls


def test_polling_without_independent_event_attestation_never_qualifies():
    probe, _, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    result = capture(probe)
    assert not result.continuity_attested
    assert result.frames.reconnect_observed
    assert result.transport.reconnect_observed
    assert not result.transport.connected


@pytest.mark.parametrize("invalid", [
    {"variant": "alternative"},
    {"duration_s": 1},
    {"duration_s": 301},
    {"duration_s": True},
    {"poll_interval_s": 0},
    {"poll_interval_s": float("nan")},
    {"poll_interval_s": True},
    {"pair_id": "foo bar"},
    {"game_id": "!" * 80},
])
def test_invalid_capture_scopes_fail_before_contact(invalid):
    probe, client, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    kwargs = dict(
        pair_id="a01", variant="candidate", game_id="obby",
        game_version="v01", duration_s=5, poll_interval_s=1.0,
    )
    kwargs.update(invalid)
    with pytest.raises((ValueError, TypeError)):
        probe.capture(**kwargs)
    assert client.n == 0


def test_requires_live_connection_and_non_empty_password():
    probe, client, _, _, _ = rig()
    with pytest.raises(PermissionError):
        capture(probe)
    with pytest.raises(ValueError):
        probe.connect(password="", owner_approved=True)
    with pytest.raises(ValueError):
        probe.connect(password="x" * 257, owner_approved=True)
    assert client.calls == []
    probe.connect(password="p", owner_approved=True)
    with pytest.raises(RuntimeError):
        probe.connect(password="p", owner_approved=True)
    probe.disconnect()
    with pytest.raises(PermissionError):
        capture(probe)


@pytest.mark.parametrize("fault", ["reconnect", "reset", "null", "error", "restart"])
def test_bad_obs_capture_fails_closed_and_sanitizes_private_exception(fault):
    probe, client, _, process, _ = rig()
    probe.connect(password="p", owner_approved=True)
    if fault == "reconnect":
        client.reconnect_at = 3
    elif fault == "reset":
        client.reset_at = 6
    elif fault == "null":
        client.null_congestion_at = 3
    elif fault == "error":
        client.fail_at = 3
    else:
        real_sleep = probe._sleep

        def restart(seconds):
            real_sleep(seconds)
            process["identity"] = (321, 1234567.5)

        probe._sleep = restart
    with pytest.raises(ObsProbeError) as error:
        capture(probe, continuity_guard=lambda: True)
    assert "private-OBS-credential" not in str(error.value)
    assert probe._client is None
    with pytest.raises(PermissionError):
        capture(probe)


def test_untrustworthy_guard_failure_marks_capture_inconclusive():
    probe, _, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    evidence = capture(probe, continuity_guard=lambda: False)
    assert evidence.transport.reconnect_observed
    assert not evidence.transport.connected


def test_guard_exception_revokes_connection():
    probe, _, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    def broken_guard():
        raise RuntimeError("guard-secret")
    with pytest.raises(ObsProbeError) as error:
        capture(probe, continuity_guard=broken_guard)
    assert "guard-secret" not in str(error.value)
    assert probe._client is None


def test_connect_failure_sanitizes_secret_and_never_persists_client():
    probe, client, _, process, connections = rig()
    process["identity"] = (0, 0)
    with pytest.raises(ObsProbeError) as error:
        probe.connect(password="private", owner_approved=True)
    assert "private" not in str(error.value)
    assert connections == []
    assert probe._client is None


def test_time_stall_cancels_capture_instead_of_returning_false_good_window():
    probe, _, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    probe._sleep = lambda _: None
    with pytest.raises(ObsProbeError):
        capture(probe)
    assert probe._client is None


def test_complete_paired_capture_feeds_existing_combined_quality_gate():
    from star.stream_network_qos_gate import compare_realtime_obs_transport
    from star.stream_realtime_benchmark import RealtimeRun

    probe, _, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    runs, frames, transports = [], [], []
    for i in range(20):
        for variant in ("baseline", "candidate"):
            evidence = probe.capture(
                pair_id=f"p{i:02d}", variant=variant, game_id="obby",
                game_version="v01", duration_s=5, poll_interval_s=1.0,
                continuity_guard=lambda: True,
            )
            runs.append(RealtimeRun(
                f"p{i:02d}", variant, "obby", "v01",
                650.0 if variant == "baseline" else 390.0,
                (16.7,) * 150, 4500.0, True,
            ))
            frames.append(evidence.frames)
            transports.append(evidence.transport)
    result = compare_realtime_obs_transport(runs, frames, transports)
    assert result.verdict == "eligible_for_manual_pilot"
    assert result.matched_windows == 20
    assert result.candidate_network_skipped_pct == 0


def test_unattested_polling_vetoes_full_quality_gate_even_if_fast_audio():
    from star.stream_network_qos_gate import compare_realtime_obs_transport
    from star.stream_realtime_benchmark import RealtimeRun

    probe, _, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    runs, frames, transports = [], [], []
    for i in range(20):
        for variant in ("baseline", "candidate"):
            evidence = probe.capture(
                pair_id=f"p{i:02d}", variant=variant, game_id="obby",
                game_version="v01", duration_s=5, poll_interval_s=1.0,
            )
            runs.append(RealtimeRun(
                f"p{i:02d}", variant, "obby", "v01",
                650.0 if variant == "baseline" else 390.0,
                (16.7,) * 150, 4500.0, True,
            ))
            frames.append(evidence.frames)
            transports.append(evidence.transport)
    result = compare_realtime_obs_transport(runs, frames, transports)
    assert result.verdict != "eligible_for_manual_pilot"


def test_overlapping_capture_is_rejected_without_corrupting_first():
    probe, _, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    real_sleep = probe._sleep
    attempts = []

    def overlap(seconds):
        with pytest.raises(ObsProbeError, match="already active"):
            capture(probe)
        attempts.append(1)
        real_sleep(seconds)

    probe._sleep = overlap
    result = capture(probe, continuity_guard=lambda: True)
    assert result.transport.connected
    assert len(attempts) == 5


def test_disconnect_during_capture_invalidates_partial_counters():
    probe, _, _, _, _ = rig()
    probe.connect(password="p", owner_approved=True)
    real_sleep = probe._sleep

    def disconnected(seconds):
        real_sleep(seconds)
        probe.disconnect()

    probe._sleep = disconnected
    with pytest.raises(ObsProbeError, match="unverifiable"):
        capture(probe, continuity_guard=lambda: True)
    assert probe._client is None
