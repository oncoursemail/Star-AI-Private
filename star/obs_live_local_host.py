"""Owner-opt-in, read-only OBS v5 localhost transport for Star's live load pipeline.

A trusted Windows host supplies its own measured game/VRAM/first-audible TTS
receipt. This client *only* authenticates to OBS on 127.0.0.1, subscribes to
output state changes, and requests GetStats / GetStreamStatus. Any unexpected
message, output transition, identity change, or missing sensor fails closed.

This is NOT a broadcaster, OBS controller, OBS stream-state attestation between
polls, game input bridge, or authority to speak. A model or viewer must never
own this object or its password, PID, sensor source, or permission flags.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import math
import platform
import secrets
from threading import RLock
import time
from typing import cast

from .obs_live_load_pipeline import LiveLoadResult, ObsLiveLoadPipeline
from .stream_load_governor import StreamLoadAdvice
from .stream_load_host_bridge import HostLoadReceipt
from .stream_obs_local_readonly_probe import (
    _WebSocket,
    _authentication,
    _local_connection,
    _monotonic_ms,
    _packet,
    _write,
)
from .stream_windows_rehearsal_preflight import ProcessWitness, enumerate_windows_processes

_OBS_NAMES = frozenset({"obs64.exe", "obs.exe"})
_OUTPUT_EVENTS = 1 << 6
_MAX_PROCESSES = 32768
_MAX_REQUEST_IDS = 16384


def _obs_listener_is_loopback_owned(pid: int, port: int) -> bool:
    """Match a unique IPv4-loopback listening socket to the authorized OBS PID.

    OS socket-table errors propagate; the caller fails closed on unknown
    ownership. Wildcard/public listeners and duplicate bindings are rejected.
    """
    import psutil

    matching = []
    for row in psutil.net_connections(kind="tcp"):
        if row.status == psutil.CONN_LISTEN and row.laddr and row.laddr.port == port:
            matching.append(row)
            if len(matching) > 1:
                return False
    return len(matching) == 1 and matching[0].pid == pid and matching[0].laddr.ip == "127.0.0.1"


class ObsLoopbackLiveHost:
    """Local authenticated OBS readings joined to real, host-owned load data.

    The externally selected OBS pid+creation time must come from the OS, not a
    caption or game/chat tool. All evidence and read callbacks stay in process.
    The socket is bound to one host-revalidated OBS epoch; rearm requires a new
    socket and new epoch. The load reader must sample real independent sensors,
    never manufacture zero/default measurements for missing input.
    """

    def __init__(
        self,
        *,
        load_reader: Callable[[], HostLoadReceipt],
        pipeline: ObsLiveLoadPipeline | None = None,
        process_reader: Callable[[], Iterable[ProcessWitness]] = enumerate_windows_processes,
        connect: Callable[[int, float], _WebSocket] = _local_connection,
        listener_check: Callable[[int, int], bool] = _obs_listener_is_loopback_owned,
        clock: Callable[[], float] = time.monotonic,
        token: Callable[[int], str] = secrets.token_hex,
        system_name: Callable[[], str] = platform.system,
        max_advice_age_ms: int = 750,
        verify_output_at_admission: bool = False,
    ) -> None:
        # A resource recommendation needs fresher OBS evidence than the
        # governor's generic multi-second sample-age allowance. This is a
        # speech-admission boundary, not a per-render-frame callback.
        if type(max_advice_age_ms) is not int or not 100 <= max_advice_age_ms <= 2000:
            raise ValueError("OBS recommendation age must be 100..2000 ms")
        if type(verify_output_at_admission) is not bool:
            raise ValueError("OBS admission output verification must be a boolean")
        if not all(
            callable(fn)
            for fn in (
                load_reader,
                process_reader,
                connect,
                listener_check,
                clock,
                token,
                system_name,
            )
        ):
            raise TypeError("host sensor, connection and clock callbacks are required")
        if pipeline is not None and type(pipeline) is not ObsLiveLoadPipeline:
            raise TypeError("only a host-owned OBS live load pipeline is accepted")
        self._pipeline = pipeline if pipeline is not None else ObsLiveLoadPipeline()
        self._load_reader = load_reader
        self._process_reader = process_reader
        self._connect = connect
        self._listener_check = listener_check
        self._clock = clock
        self._token = token
        self._system_name = system_name
        self._max_advice_age_ms = max_advice_age_ms
        self._verify_output_at_admission = verify_output_at_admission
        self._last_stream_state: tuple[int, int, int] | None = None
        self._last_accepted_ms: float | None = None
        self._lock = RLock()
        self._sock: _WebSocket | None = None
        self._pid: int | None = None
        self._created: float | None = None
        self._port: int | None = None
        self._used_ids: set[str] = set()
        self._counts = dict(opened=0, samples=0, pending=0, accepted=0, revoked=0)

    def _origin_matches(self) -> bool:
        """Independently check exact PID, birth time and executable name."""
        if self._pid is None or self._created is None or self._port is None:
            return False
        if self._listener_check(self._pid, self._port) is not True:
            return False
        matches = 0
        for i, row in enumerate(self._process_reader()):
            if i >= _MAX_PROCESSES or type(row) is not ProcessWitness:
                raise ValueError("invalid or unbounded trusted OS process snapshot")
            if row.pid == self._pid:
                if (
                    row.name.casefold() not in _OBS_NAMES
                    or type(row.created_unix_s) not in (int, float)
                    or not math.isfinite(float(row.created_unix_s))
                    or float(row.created_unix_s) != self._created
                ):
                    return False
                matches += 1
        return matches == 1

    def _id(self) -> str:
        if len(self._used_ids) >= _MAX_REQUEST_IDS:
            raise ValueError("OBS request identity window exhausted")
        value = self._token(12)
        if (
            type(value) is not str
            or not 12 <= len(value) <= 40
            or not value.isascii()
            or not value.isalnum()
            or value in self._used_ids
        ):
            raise ValueError("invalid or repeated OBS request ID")
        self._used_ids.add(value)
        return value

    @staticmethod
    def _stream_state(data: dict[str, object]) -> tuple[int, int, int]:
        """Only a live, continuous OBS stream can support optional speech.

        Counters are evaluated from authenticated GetStreamStatus responses,
        never from captions, model descriptions or stream/chat messages.
        """
        if (
            type(data.get("outputActive")) is not bool
            or type(data.get("outputReconnecting")) is not bool
            or not data["outputActive"]
            or data["outputReconnecting"]
        ):
            raise ValueError("OBS output is inactive or reconnecting")
        counters = (
            data.get("outputDuration"),
            data.get("outputTotalFrames"),
            data.get("outputSkippedFrames"),
        )
        if any(type(value) is not int or not 0 <= value <= 2**63 - 1 for value in counters):
            raise ValueError("OBS output counters missing or invalid")
        # The exact-int checks above are runtime validation; pyright cannot
        # narrow a tuple built from dict.get() using an any() generator.
        return cast(tuple[int, int, int], counters)

    def _stop(self) -> None:
        self._pipeline.stop()
        sock = self._sock
        self._sock = None
        self._pid = None
        self._created = None
        self._port = None
        self._last_accepted_ms = None
        self._last_stream_state = None
        self._used_ids.clear()
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass  # revoke prior live advice even if transport close fails

    def stop(self) -> None:
        with self._lock:
            self._stop()

    def open(
        self,
        *,
        owner_approved: bool = False,
        obs_pid: int,
        obs_created_unix_s: float,
        password: str,
        port: int = 4455,
        timeout_s: float = 2.0,
    ) -> None:
        """Observe an already-running OBS process. Never start OBS or a stream."""
        if owner_approved is not True:
            raise PermissionError("local OBS observation requires owner approval")
        if (
            type(obs_pid) is not int
            or not 1 <= obs_pid <= 2**31 - 1
            or type(obs_created_unix_s) not in (int, float)
            or not math.isfinite(float(obs_created_unix_s))
            or not 1 <= float(obs_created_unix_s) <= 10**11
            or type(port) is not int
            or not 1024 <= port <= 65535
            or type(timeout_s) not in (int, float)
            or not 0.25 <= float(timeout_s) <= 5.0
            or type(password) is not str
            or not 1 <= len(password) <= 2048
        ):
            raise ValueError("invalid bounded trusted OBS host configuration")
        with self._lock:
            if self._sock is not None:
                raise RuntimeError("close previous OBS observation before opening another")
            if self._system_name() != "Windows":
                raise RuntimeError("OBS live observation requires an authorized Windows host")
            self._pid = obs_pid
            self._created = float(obs_created_unix_s)
            self._port = port
            self._used_ids.clear()
            sock: _WebSocket | None = None
            try:
                if not self._origin_matches():
                    raise RuntimeError("pinned OBS process identity unavailable")
                sock = self._connect(port, float(timeout_s))
                hello = _packet(sock.recv(), 0)
                rpc_version = hello.get("rpcVersion")
                if (not isinstance(rpc_version, int)
                        or isinstance(rpc_version, bool) or rpc_version < 1):
                    raise ValueError("unsupported OBS RPC version")
                challenge = hello.get("authentication")
                if type(challenge) is not dict:
                    raise PermissionError("authenticated OBS websocket is required")
                salt, challenge_text = challenge.get("salt"), challenge.get("challenge")
                if not isinstance(salt, str) or not isinstance(challenge_text, str):
                    raise PermissionError("invalid OBS authentication challenge")
                _write(
                    sock,
                    1,
                    {
                        "rpcVersion": 1,
                        "eventSubscriptions": _OUTPUT_EVENTS,
                        "authentication": _authentication(password, salt, challenge_text),
                    },
                )
                identified = _packet(sock.recv(), 2)
                if identified.get("negotiatedRpcVersion") != 1:
                    raise ValueError("OBS negotiation failed")
                if not self._origin_matches():
                    raise RuntimeError("OBS process changed during handshake")
                epoch = self._id()
                self._pipeline.arm(owner_approved=True, obs_epoch=epoch)
                self._sock = sock
                self._counts["opened"] += 1
            except Exception:
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
                self._stop()
                # Never leak credentials, WebSocket error payloads, or OS PIDs.
                raise RuntimeError("authenticated local OBS observation unavailable") from None

    def _read(self, kind: str) -> tuple[dict[str, object], float]:
        if self._sock is None:
            raise RuntimeError("OBS epoch is not open")
        request_id = self._id()
        _write(self._sock, 6, {"requestType": kind, "requestId": request_id})
        # Unexpected OpCode 5 (including any output-state event) always revokes.
        # Do not skip an event to retrieve a later plausible "green" response.
        reply = _packet(self._sock.recv(), 7)
        if reply.get("requestId") != request_id or reply.get("requestType") != kind:
            raise ValueError("OBS response correlation failed")
        status = reply.get("requestStatus")
        if (
            type(status) is not dict
            or status.get("result") is not True
            or type(status.get("code")) is not int
            or status["code"] != 100
        ):
            raise ValueError("OBS read-only request unsuccessful")
        data = reply.get("responseData")
        if type(data) is not dict:
            raise ValueError("OBS responseData unavailable")
        return data, _monotonic_ms(self._clock)

    def sample(self) -> LiveLoadResult:
        """One paired read at one trusted epoch; no model/OBS writes permitted."""
        with self._lock:
            if self._sock is None:
                return LiveLoadResult("disabled", "local_obs_epoch_missing")
            try:
                if not self._origin_matches():
                    raise RuntimeError("OBS process identity changed")
                stats, at_stats = self._read("GetStats")
                stream, at_stream = self._read("GetStreamStatus")
                receipt = self._load_reader()
                if type(receipt) is not HostLoadReceipt:
                    raise ValueError("real host load receipt is required")
                now_ms = _monotonic_ms(self._clock)
                if not self._origin_matches():
                    raise RuntimeError("OBS process identity changed")
                result = self._pipeline.ingest(
                    stats=stats,
                    stream_status=stream,
                    stats_received_ms=at_stats,
                    stream_received_ms=at_stream,
                    now_ms=now_ms,
                    receipt=receipt,
                    host_verified=True,
                )
                self._counts["samples"] += 1
                if result.status == "accepted":
                    self._last_stream_state = self._stream_state(stream)
                    self._last_accepted_ms = now_ms
                    self._counts["accepted"] += 1
                elif result.status == "pending":
                    self._counts["pending"] += 1
                else:
                    self._counts["revoked"] += 1
                    self._stop()
                return result
            except Exception:
                self._counts["revoked"] += 1
                self._stop()
                return LiveLoadResult("rejected", "obs_transport_identity_or_host_receipt_unavailable")

    def recommend(self) -> StreamLoadAdvice:
        """Fresh advice only, never broadcast/game/voice authorization."""
        with self._lock:
            if self._sock is None:
                # A stopped pipeline's advice is always disabled.
                return self._pipeline.recommend(now_ms=0.0)
            try:
                now_ms = _monotonic_ms(self._clock)
                # Polling and recommending are different trust boundaries.
                # OBS can exit, rebind its listener or restart after the last
                # accepted sample but before the next speech decision.
                if not self._origin_matches():
                    raise RuntimeError("OBS process/socket ownership changed")
                accepted_at = self._last_accepted_ms
                if accepted_at is not None and (now_ms < accepted_at or now_ms - accepted_at > self._max_advice_age_ms):
                    raise RuntimeError("last accepted OBS interval expired")
                if self._verify_output_at_admission and accepted_at is not None:
                    # OBS can stop/reconnect/restart the output in the
                    # sub-second interval BETWEEN full paired samples while
                    # the exact same OBS process/socket remains alive.
                    # This bounded read-only query is only for low-frequency
                    # workload/speech decisions; never call on render threads.
                    status, _ = self._read("GetStreamStatus")
                    recent = _monotonic_ms(self._clock)
                    if not self._origin_matches():
                        raise RuntimeError("OBS identity changed during output check")
                    if recent < accepted_at or recent - accepted_at > self._max_advice_age_ms:
                        raise RuntimeError("OBS paired evidence expired during output check")
                    observed = self._stream_state(status)
                    previous = self._last_stream_state
                    if previous is None or any(a < b for a, b in zip(observed, previous)):
                        raise RuntimeError("OBS stream restarted or counters reversed")
                    self._last_stream_state = observed
                    now_ms = recent
                return self._pipeline.recommend(now_ms=now_ms)
            except Exception:
                self._counts["revoked"] += 1
                self._stop()
                return self._pipeline.recommend(now_ms=0.0)

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate state only; no password, host PID, socket or user data."""
        with self._lock:
            return {**self._counts, "armed": self._sock is not None}


__all__ = ["ObsLoopbackLiveHost"]
