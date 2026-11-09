"""Local Windows OBS transport: exact auth/identity and fail-closed offline fakes."""

import json

import pytest

from star.obs_live_local_host import ObsLoopbackLiveHost
from star.stream_load_host_bridge import HostLoadReceipt
from star.stream_windows_rehearsal_preflight import ProcessWitness


class Clock:
    ms = 0.0

    def __call__(self):
        return self.ms / 1000.0


class Socket:
    def __init__(self, clock):
        self.clock = clock
        self.closed = False
        self.writes = []
        self.inbox = [
            {
                "op": 0,
                "d": {
                    "rpcVersion": 1,
                    "authentication": {"salt": "salt", "challenge": "challenge"},
                },
            },
            {"op": 2, "d": {"negotiatedRpcVersion": 1}},
        ]
        self.sample_number = 0
        self.emit_event = False
        self.bad_id = False
        self.bad_status = False
        self.reconnecting = False
        self.fail_transport = False

    def send(self, raw):
        message = json.loads(raw)
        self.writes.append(message)
        if message["op"] == 1:
            return
        assert message["op"] == 6  # no Set, Start, Stop, scene edits or broadcasts
        kind = message["d"]["requestType"]
        assert kind in {"GetStats", "GetStreamStatus"}
        n = self.sample_number
        if kind == "GetStats":
            data = {
                "renderSkippedFrames": 0,
                "renderTotalFrames": 1000 + n * 60,
                "outputSkippedFrames": 0,
                "outputTotalFrames": 1000 + n * 60,
            }
        else:
            data = {
                "outputActive": True,
                "outputReconnecting": self.reconnecting,
                "outputDuration": 1000 + n * 500,
                "outputSkippedFrames": 0,
                "outputTotalFrames": 100 + n * 50,
            }
        self.inbox.append(
            {
                "op": 7,
                "d": {
                    "requestId": "forged" if self.bad_id else message["d"]["requestId"],
                    "requestType": kind,
                    "requestStatus": {"result": not self.bad_status, "code": 100},
                    "responseData": data,
                },
            }
        )
        if kind == "GetStreamStatus":
            self.sample_number += 1

    def recv(self):
        if self.fail_transport:
            raise TimeoutError("transport: secret should not appear in report")
        if self.emit_event and len(self.writes) > 1:
            self.emit_event = False
            return json.dumps(
                {
                    "op": 5,
                    "d": {
                        "eventType": "StreamStateChanged",
                        "eventData": {"outputActive": False},
                    },
                }
            )
        value = self.inbox.pop(0)
        if value["op"] == 7:
            kind = value["d"]["requestType"]
            n = self.sample_number - (1 if kind == "GetStreamStatus" else 0)
            self.clock.ms = 1000 + 500 * n + (40 if kind == "GetStreamStatus" else 0)
        return json.dumps(value)

    def close(self):
        self.closed = True


def load(n):
    return HostLoadReceipt(
        observed_at_ms=1000 + 500 * n,
        game_p95_frame_ms=14.0,
        game_target_fps=60,
        gpu_vram_used_mb=3500,
        gpu_vram_total_mb=8192,
        tts_first_audio_p95_ms=160.0,
        network_dropped_pct=0.0,
        obs_connected=True,
        game_frame_count=90,
    )


def ready():
    clock = Clock()
    socket = Socket(clock)
    identity = [ProcessWitness("obs64.exe", 123, 12345.0)]
    serial = iter(range(9999))

    def sensor():
        n = socket.sample_number - 1
        clock.ms = 1060 + 500 * n
        return load(n)

    host = ObsLoopbackLiveHost(
        load_reader=sensor,
        process_reader=lambda: list(identity),
        connect=lambda port, timeout: socket,
        listener_check=lambda pid, port: True,
        clock=clock,
        token=lambda length: f"obs{next(serial):020d}",
        system_name=lambda: "Windows",
    )
    return host, socket, clock, identity


def armed():
    host, socket, clock, identity = ready()
    host.open(owner_approved=True, obs_pid=123, obs_created_unix_s=12345.0, password="private-password")
    return host, socket, clock, identity


def test_owner_permission_blocks_all_socket_activity():
    host, socket, *_ = ready()
    with pytest.raises(PermissionError):
        host.open(obs_pid=123, obs_created_unix_s=12345, password="secret")
    assert not socket.writes
    assert host.metrics()["armed"] is False


def test_non_windows_or_bad_os_identity_prevents_connection():
    host, socket, _, identity = ready()
    identity[0] = ProcessWitness("obs64.exe", 123, 67890)
    with pytest.raises(RuntimeError):
        host.open(owner_approved=True, obs_pid=123, obs_created_unix_s=12345, password="secret")
    assert not socket.writes
    other, another, *_ = ready()
    other._system_name = lambda: "Linux"
    with pytest.raises(RuntimeError):
        other.open(owner_approved=True, obs_pid=123, obs_created_unix_s=12345, password="secret")
    assert not another.writes


def test_authenticated_output_events_and_only_two_reads_even_when_healthy():
    host, socket, *_ = armed()
    identify = socket.writes[0]
    assert identify["op"] == 1
    assert identify["d"]["rpcVersion"] == 1
    assert identify["d"]["eventSubscriptions"] == 64
    assert identify["d"]["authentication"] != "private-password"
    assert host.sample().status == "pending"
    for _ in range(3):
        assert host.sample().status == "accepted"
    assert host.recommend().profile == "normal"
    assert host.recommend().allow_optional_commentary
    kinds = [write["d"]["requestType"] for write in socket.writes[1:]]
    assert kinds == ["GetStats", "GetStreamStatus"] * 4
    assert host.metrics()["samples"] == 4
    assert "obs64" not in str(host.metrics())
    assert "private" not in str(host.metrics())
    host.stop()
    assert socket.closed
    assert host.recommend().profile == "disabled"


@pytest.mark.parametrize("variation", ["event", "wrong_id", "bad_status", "reconnect", "timeout"])
def test_stream_transition_corrupt_response_or_transport_revokes_green(variation):
    host, socket, *_ = armed()
    assert host.sample().status == "pending"
    assert host.sample().status == "accepted"
    if variation == "event":
        socket.emit_event = True
    elif variation == "wrong_id":
        socket.bad_id = True
    elif variation == "bad_status":
        socket.bad_status = True
    elif variation == "reconnect":
        socket.reconnecting = True
    else:
        socket.fail_transport = True
    result = host.sample()
    assert result.status == "rejected"
    assert socket.closed
    assert not result.authorizes_broadcast
    assert not host.metrics()["armed"]
    assert host.recommend().profile == "disabled"


def test_process_replacement_or_wrong_basename_revokes_and_closes_socket():
    host, socket, _, identity = armed()
    host.sample()
    identity[0] = ProcessWitness("notepad.exe", 123, 12345)
    assert host.sample().status == "rejected"
    assert socket.closed
    assert host.recommend().profile == "disabled"


def test_missing_genuine_host_sensor_data_never_defaults_to_green():
    host, socket, *_ = armed()
    host._load_reader = lambda: None
    assert host.sample().status == "rejected"
    assert socket.closed
    assert host.recommend().profile == "disabled"


def test_clock_reversal_revokes_at_pairing_boundary():
    host, socket, clock, *_ = armed()
    host.sample()
    original = host._load_reader

    def clock_reversed_sensor():
        observed = original()
        clock.ms = 1
        return observed

    host._load_reader = clock_reversed_sensor
    assert host.sample().status == "rejected"
    assert socket.closed


def test_duplicate_request_nonce_never_accepts_cross_sample_replay():
    host, socket, *_ = armed()
    host._token = lambda n: "fixedrequestid"
    assert host.sample().status == "rejected"
    assert socket.closed


def test_invalid_connection_configuration_does_not_open_socket():
    host, socket, *_ = ready()
    for values in (
        {"obs_pid": True, "obs_created_unix_s": 12345, "password": "a"},
        {"obs_pid": 123, "obs_created_unix_s": float("nan"), "password": "a"},
        {"obs_pid": 123, "obs_created_unix_s": 12345, "password": ""},
        {"obs_pid": 123, "obs_created_unix_s": 12345, "password": "a", "port": 80},
    ):
        with pytest.raises(ValueError):
            host.open(owner_approved=True, **values)
    assert not socket.writes


def test_rearm_requires_distinct_socket_epoch_and_stale_success_cannot_survive():
    host, socket, *_ = armed()
    for _ in range(4):
        host.sample()
    assert host.recommend().profile == "normal"
    host.stop()
    with pytest.raises(RuntimeError):
        host.open(owner_approved=True, obs_pid=123, obs_created_unix_s=12345, password="secret")
    assert host.recommend().profile == "disabled"


def test_socket_listener_owned_by_different_process_revokes():
    host, socket, *_ = armed()
    assert host.sample().status == "pending"
    host._listener_check = lambda pid, port: False
    assert host.sample().status == "rejected"
    assert socket.closed
    assert host.recommend().profile == "disabled"


def test_real_listener_check_requires_exact_private_binding(monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace
    from star.obs_live_local_host import _obs_listener_is_loopback_owned

    psutil = ModuleType("psutil")
    psutil.CONN_LISTEN = "LISTEN"
    monkeypatch.setitem(sys.modules, "psutil", psutil)

    def fake(ip, pid=123, status="LISTEN", port=4455):
        return SimpleNamespace(
            pid=pid,
            status=status,
            laddr=SimpleNamespace(ip=ip, port=port),
        )

    for candidate, allowed in (
        ([fake("127.0.0.1")], True),
        ([fake("0.0.0.0")], False),
        ([fake("::1")], False),
        ([fake("127.0.0.1", pid=999)], False),
        ([fake("127.0.0.1"), fake("0.0.0.0")], False),
        ([fake("127.0.0.1", port=8000)], False),
        ([fake("127.0.0.1", status="ESTABLISHED")], False),
        ([], False),
    ):
        psutil.net_connections = lambda kind: candidate
        assert _obs_listener_is_loopback_owned(123, 4455) is allowed


def test_recommend_invalidates_old_green_when_obs_process_exits_between_samples():
    host, socket, _, identity = armed()
    for _ in range(4):
        assert host.sample().status in {"pending", "accepted"}
    assert host.recommend().profile == "normal"
    identity.clear()
    # No new sample was taken. The decision boundary must independently check.
    assert host.recommend().profile == "disabled"
    assert socket.closed
    assert not host.metrics()["armed"]


def test_recommend_invalidates_old_green_on_listener_rebind_between_samples():
    host, socket, *_ = armed()
    for _ in range(4):
        host.sample()
    assert host.recommend().allow_optional_commentary
    host._listener_check = lambda pid, port: False
    assert host.recommend().profile == "disabled"
    assert socket.closed
    assert host.metrics()["revoked"] >= 1


def test_recommend_expiry_is_stricter_than_governor_three_second_cache():
    host, socket, clock, _ = armed()
    for _ in range(4):
        host.sample()
    assert host.recommend().profile == "normal"
    clock.ms += 749
    assert host.recommend().profile == "normal"
    clock.ms += 2  # Only 751 ms old; governor would still accept its 3s TTL.
    assert host.recommend().profile == "disabled"
    assert socket.closed
    assert host.metrics()["armed"] is False


def test_recommend_clock_fault_cannot_reuse_previous_normal_advice():
    host, socket, clock, _ = armed()
    for _ in range(4):
        host.sample()
    assert host.recommend().profile == "normal"
    clock.ms = float("inf")
    assert host.recommend().profile == "disabled"
    assert socket.closed


@pytest.mark.parametrize("value", [True, 0, 99, 2001, 750.0, float("nan")])
def test_advice_ttl_requires_bounded_strict_host_configuration(value):
    host, *_ = ready()
    with pytest.raises(ValueError):
        ObsLoopbackLiveHost(
            load_reader=host._load_reader,
            max_advice_age_ms=value,
        )


def test_recommend_before_initial_accepted_obs_interval_stays_warming():
    host, socket, *_ = armed()
    assert not host.recommend().allow_optional_commentary
    assert host.sample().status == "pending"
    assert not host.recommend().allow_optional_commentary
    assert not socket.closed
