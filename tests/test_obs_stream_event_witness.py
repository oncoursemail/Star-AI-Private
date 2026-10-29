"""Offline OBS WebSocket v5 protocol tests; no OBS process or media needed."""
from __future__ import annotations

import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from star.obs_stream_event_witness import (
    ObsEventWitnessError, ObsStreamContinuityWitness,
)
from star.obs_readonly_benchmark_host import ObsProbeError, ObsReadOnlyProbe
from star.stream_network_qos_gate import compare_realtime_obs_transport
from star.stream_realtime_benchmark import RealtimeRun


HELLO = {
    "op": 0,
    "d": {
        "obsWebSocketVersion": "5.4.0",
        "rpcVersion": 1,
        "authentication": {"salt": "fake-salt", "challenge": "fake-challenge"},
    },
}


class FakeEventSocket:
    def __init__(self, hello=HELLO):
        self.queue = [hello]
        self.inject = []
        self.sent = []
        self.closed = False
        self.fail_next_receive = False
        self.invalid_reply = None
        self.active = True
        self.reconnecting = False

    def recv(self):
        if self.closed or self.fail_next_receive:
            self.fail_next_receive = False
            raise OSError("PRIVATE-OBS-PASSWORD")
        if not self.queue:
            raise TimeoutError("timed out on fake OBS event transport")
        frame = self.queue.pop(0)
        return frame if type(frame) is str else json.dumps(frame)

    def send(self, raw):
        if self.closed:
            raise OSError("PRIVATE-OBS-PASSWORD")
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg["op"] == 1:
            self.queue.append({
                "op": 2, "d": {"negotiatedRpcVersion": 1},
            })
        elif msg["op"] == 6:
            # The fake serializes events before its reply on the same wire.
            self.queue.extend(self.inject)
            self.inject = []
            self.queue.append(self.invalid_reply or {
                "op": 7,
                "d": {
                    "requestId": msg["d"]["requestId"],
                    "requestType": "GetStreamStatus",
                    "requestStatus": {"result": True, "code": 100},
                    "responseData": {
                        "outputActive": self.active,
                        "outputReconnecting": self.reconnecting,
                    },
                },
            })

    def event(self, name, **data):
        self.inject.append({
            "op": 5,
            "d": {"eventType": name, "eventIntent": 64,
                  "eventData": data},
        })

    def close(self):
        self.closed = True


class FakeStats:
    def __init__(self):
        self.count = 0

    def get_version(self):
        return SimpleNamespace(obs_version="31.1.0")

    def get_stats(self):
        self.count += 1
        n = self.count
        return SimpleNamespace(
            render_total_frames=1000 + 120 * n,
            render_skipped_frames=0,
            output_total_frames=1000 + 120 * n,
            output_skipped_frames=0,
        )

    def get_stream_status(self):
        n = self.count
        return SimpleNamespace(
            output_active=True, output_reconnecting=False,
            output_duration=30000 + 1000 * n,
            output_bytes=1000000 + 50000 * n,
            output_skipped_frames=0,
            output_total_frames=1000 + 120 * n,
            output_congestion=0,
        )


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.on_sleep = None

    def ms(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds * 1000
        if self.on_sleep:
            self.on_sleep(seconds)


def rig():
    ws, host, clock = FakeEventSocket(), FakeStats(), FakeClock()
    process = {"identity": (234, 123456.0)}
    urls = []

    def factory(**kwargs):
        urls.append(kwargs)
        return ws

    def identity():
        return process["identity"]

    witness = ObsStreamContinuityWitness(
        socket_factory=factory, process_identity=identity,
    )
    probe = ObsReadOnlyProbe(
        client_factory=lambda **_: host,
        process_identity=identity,
        clock_ms=clock.ms, sleep=clock.sleep,
    )
    return witness, probe, ws, host, clock, process, urls


def connected_rig():
    witness, probe, ws, host, clock, process, urls = rig()
    witness.connect(password="PRIVATE-OBS-PASSWORD", owner_approved=True)
    probe.connect(password="PRIVATE-OBS-PASSWORD", owner_approved=True)
    return witness, probe, ws, host, clock, process, urls


def capture(probe, witness):
    return probe.capture(
        pair_id="a001", variant="candidate",
        game_id="obby", game_version="v01",
        duration_s=5, poll_interval_s=1.0, event_witness=witness,
    )


def test_authenticated_local_v5_handshake_and_allowlisted_methods():
    witness, _, ws, _, _, _, urls = rig()
    with pytest.raises(PermissionError):
        witness.connect(password="PRIVATE-OBS-PASSWORD")
    witness.connect(password="PRIVATE-OBS-PASSWORD", owner_approved=True)
    assert urls == [{
        "url": "ws://127.0.0.1:4455", "timeout": 3,
        "enable_multithread": True,
    }]
    identify = ws.sent[0]
    secret = base64.b64encode(hashlib.sha256(
        b"PRIVATE-OBS-PASSWORDfake-salt"
    ).digest()).decode()
    expected = base64.b64encode(hashlib.sha256(
        (secret + "fake-challenge").encode()
    ).digest()).decode()
    assert identify == {
        "op": 1, "d": {
            "rpcVersion": 1,
            "eventSubscriptions": 65,
            "authentication": expected,
        },
    }
    witness.begin((234, 123456.0))
    assert witness.finish((234, 123456.0))
    assert {x["op"] for x in ws.sent} == {1, 6}
    assert {x["d"].get("requestType") for x in ws.sent[1:]} == {
        "GetStreamStatus",
    }
    wire = json.dumps(ws.sent)
    assert "PRIVATE-OBS-PASSWORD" not in wire
    witness.disconnect()
    assert ws.closed


def test_witness_envelopes_real_probe_capture_and_qualifies_evidence():
    witness, probe, ws, host, _, _, _ = connected_rig()
    evidence = capture(probe, witness)
    assert evidence.continuity_attested
    assert evidence.transport.connected
    assert not evidence.frames.reconnect_observed
    assert evidence.frames.render_total == 600
    assert host.count == 6
    # One begin fence, one checkpoint for each poll, one finish fence.
    assert len([m for m in ws.sent if m["op"] == 6]) == 7
    assert witness.connected


def test_racing_output_reconnect_event_causes_fail_closed():
    witness, probe, ws, _, clock, _, _ = connected_rig()
    clock.on_sleep = lambda _: ws.event(
        "StreamStateChanged",
        outputActive=True,
        outputState="OBS_WEBSOCKET_OUTPUT_RECONNECTED",
    )
    with pytest.raises(ObsProbeError, match="unverifiable"):
        capture(probe, witness)
    assert ws.closed and not witness.connected and probe._client is None


@pytest.mark.parametrize("state", [
    "OBS_WEBSOCKET_OUTPUT_RECONNECTING",
    "OBS_WEBSOCKET_OUTPUT_RECONNECTED",
    "OBS_WEBSOCKET_OUTPUT_STOPPED",
    "OBS_WEBSOCKET_OUTPUT_STARTED",
])
def test_any_mid_window_stream_state_change_vetoes_even_when_active(state):
    witness, probe, ws, _, clock, _, _ = connected_rig()
    fired = False

    def on_sleep(_):
        nonlocal fired
        if not fired:
            ws.event("StreamStateChanged", outputActive=True,
                     outputState=state)
            fired = True

    clock.on_sleep = on_sleep
    with pytest.raises(ObsProbeError):
        capture(probe, witness)
    assert not witness.connected


def test_exit_started_vetoes_even_before_windows_process_identity_changes():
    witness, probe, ws, _, clock, _, _ = connected_rig()
    clock.on_sleep = lambda _: ws.event("ExitStarted")
    with pytest.raises(ObsProbeError):
        capture(probe, witness)
    assert ws.closed


def test_other_obs_events_are_ignored_without_persisting_private_payloads():
    witness, probe, ws, _, clock, _, _ = connected_rig()
    clock.on_sleep = lambda _: ws.event(
        "RecordStateChanged", outputPath="PRIVATE-PERSON-RECORDING-PATH",
    )
    evidence = capture(probe, witness)
    rows = "".join(evidence.jsonl_rows())
    assert "PRIVATE-PERSON" not in rows
    assert evidence.continuity_attested


def test_stale_prewindow_events_are_drained_before_arming():
    witness, probe, ws, _, _, _, _ = connected_rig()
    ws.event("StreamStateChanged", outputState="OBS_WEBSOCKET_OUTPUT_STARTED")
    assert capture(probe, witness).continuity_attested


def test_events_injected_at_final_fence_cannot_qualify():
    witness, probe, ws, _, clock, _, _ = connected_rig()
    requests = 0
    original_send = ws.send

    def send(raw):
        nonlocal requests
        msg = json.loads(raw)
        if msg["op"] == 6:
            requests += 1
            if requests == 7:
                ws.event("StreamStateChanged", outputActive=True)
        return original_send(raw)

    ws.send = send
    with pytest.raises(ObsProbeError):
        capture(probe, witness)


@pytest.mark.parametrize("fault", [
    "socket", "process", "inactive", "reconnecting", "bad_status",
    "bad_request_id", "missing_reply", "binary", "oversized",
    "invalid_opcode", "too_many_events",
])
def test_faulty_event_channel_rejects_apparent_speed_improvement(fault):
    witness, probe, ws, _, clock, process, _ = connected_rig()
    fired = False

    def on_sleep(_):
        nonlocal fired
        if fired:
            return
        fired = True
        if fault == "socket":
            ws.close()
        elif fault == "process":
            process["identity"] = (1234, 999.0)
        elif fault == "inactive":
            ws.active = False
        elif fault == "reconnecting":
            ws.reconnecting = True
        elif fault in ("bad_status", "bad_request_id"):
            ws.invalid_reply = {
                "op": 7, "d": {
                    "requestType": "GetStreamStatus",
                    "requestId": "invalid",
                    "requestStatus": {"result": fault != "bad_status"},
                    "responseData": {"outputActive": True,
                                     "outputReconnecting": False},
                },
            }
        elif fault == "missing_reply":
            ws.invalid_reply = {"op": 7, "d": {"requestId": "wrong"}}
        elif fault == "binary":
            ws.inject.append(b"not-json")
            # Fake socket serializes bytes as repr? recv returns bytes directly.
        elif fault == "oversized":
            ws.inject.append("x" * 66000)
        elif fault == "invalid_opcode":
            ws.inject.append({"op": 9, "d": {}})
        elif fault == "too_many_events":
            for _ in range(260):
                ws.event("RecordStateChanged")

    clock.on_sleep = on_sleep
    with pytest.raises(ObsProbeError):
        capture(probe, witness)
    assert probe._client is None
    assert ws.closed


@pytest.mark.parametrize("bad", [
    {"op": 0, "d": {"obsWebSocketVersion": "4.9", "rpcVersion": 1,
                    "authentication": {"challenge": "c", "salt": "s"}}},
    {"op": 0, "d": {"obsWebSocketVersion": "5.0", "rpcVersion": 1}},
    {"op": 0, "d": {"obsWebSocketVersion": "5.0", "rpcVersion": 0,
                    "authentication": {"challenge": "c", "salt": "s"}}},
    {"op": 0, "d": {"obsWebSocketVersion": "5.0", "rpcVersion": 1,
                    "authentication": {"challenge": 3, "salt": "s"}}},
    {"op": 2, "d": {"negotiatedRpcVersion": 1}},
    "a" * 70000,
])
def test_rejects_unverified_hello_and_never_leaks_secret(bad):
    ws = FakeEventSocket(hello=bad)
    witness = ObsStreamContinuityWitness(
        socket_factory=lambda **_: ws,
        process_identity=lambda: (234, 123456.0),
    )
    with pytest.raises(ObsEventWitnessError) as error:
        witness.connect(password="PRIVATE-OBS-PASSWORD",
                        owner_approved=True)
    assert "PRIVATE" not in str(error.value)
    assert ws.closed and not witness.connected


def test_unauthorized_invalid_or_duplicate_connections_fail_without_io():
    witness, probe, ws, _, _, _, urls = rig()
    with pytest.raises(ValueError):
        witness.connect(password="", owner_approved=True)
    with pytest.raises(ValueError):
        witness.connect(password="x" * 257, owner_approved=True)
    assert urls == []
    witness.connect(password="p", owner_approved=True)
    with pytest.raises(RuntimeError):
        witness.connect(password="p", owner_approved=True)
    witness.disconnect()
    with pytest.raises(ObsEventWitnessError):
        witness.begin((234, 123456.0))


def test_fake_or_mixed_witness_rejected_before_sampling():
    witness, probe, _, host, _, _, _ = connected_rig()
    options = {
        "pair_id": "a001", "variant": "candidate",
        "game_id": "obby", "game_version": "v01",
        "duration_s": 5, "poll_interval_s": 1.0,
    }
    with pytest.raises(TypeError):
        probe.capture(**options, event_witness=object())
    with pytest.raises(ValueError):
        probe.capture(**options, event_witness=witness,
                      continuity_guard=lambda: True)
    assert host.count == 0


def test_reuse_witness_for_sequential_baseline_candidate_windows():
    witness, probe, ws, _, _, _, _ = connected_rig()
    for index in range(4):
        data = probe.capture(
            pair_id=f"p{index:02d}",
            variant="baseline" if index % 2 else "candidate",
            game_id="obby", game_version="v01",
            duration_s=3, poll_interval_s=1,
            event_witness=witness,
        )
        assert data.continuity_attested
    assert witness.connected


def test_cannot_arm_overlapping_windows():
    witness, _, ws, _, _, _, _ = connected_rig()
    witness.begin((234, 123456.0))
    with pytest.raises(ObsEventWitnessError):
        witness.begin((234, 123456.0))
    assert witness.finish((234, 123456.0))
    assert not ws.closed


def test_legacy_polling_without_witness_remains_conservatively_ineligible():
    witness, probe, ws, _, _, _, _ = connected_rig()
    result = probe.capture(
        pair_id="a001", variant="candidate",
        game_id="obby", game_version="v01",
        duration_s=5, poll_interval_s=1.0,
    )
    assert not result.continuity_attested
    assert result.transport.reconnect_observed
    assert ws.sent[0]["op"] == 1


def test_all_verified_event_windows_feed_existing_qos_gate():
    witness, probe, _, _, _, _, _ = connected_rig()
    runs, frames, transports = [], [], []
    for i in range(20):
        for variant in ("baseline", "candidate"):
            evidence = probe.capture(
                pair_id=f"p{i:02d}", variant=variant,
                game_id="obby", game_version="v01",
                duration_s=3, poll_interval_s=1,
                event_witness=witness,
            )
            frames.append(evidence.frames)
            transports.append(evidence.transport)
            runs.append(RealtimeRun(
                f"p{i:02d}", variant, "obby", "v01",
                650.0 if variant == "baseline" else 390.0,
                (16.7,) * 150, 4500.0, True,
            ))
    result = compare_realtime_obs_transport(runs, frames, transports)
    assert result.verdict == "eligible_for_manual_pilot"
    assert result.matched_windows == 20


def test_untrusted_identity_and_observer_failure_never_qualify():
    ws = FakeEventSocket()
    witness = ObsStreamContinuityWitness(
        socket_factory=lambda **_: ws,
        process_identity=lambda: (0, float("nan")),
    )
    with pytest.raises(ObsEventWitnessError):
        witness.connect(password="private", owner_approved=True)
    assert ws.sent == []


def test_stream_state_never_returned_in_correct_response_is_rejected():
    witness, probe, ws, _, clock, _, _ = connected_rig()
    ws.active = True
    ws.reconnecting = False
    original_send = ws.send

    def send(raw):
        original_send(raw)
        message = json.loads(raw)
        if message["op"] == 6 and clock.now >= 2000:
            ws.queue[-1]["d"]["responseData"] = {"outputActive": "true"}
    ws.send = send
    with pytest.raises(ObsProbeError):
        capture(probe, witness)


def test_completed_witness_can_catch_new_disruptions_in_next_window():
    witness, probe, ws, _, clock, _, _ = connected_rig()
    assert capture(probe, witness).continuity_attested
    ws.event("StreamStateChanged", outputActive=True)
    # A new, pre-window event is stale and drained, not evidence of failure.
    assert capture(probe, witness).continuity_attested
    clock.on_sleep = lambda _: ws.event("StreamStateChanged", outputActive=True)
    with pytest.raises(ObsProbeError):
        capture(probe, witness)
