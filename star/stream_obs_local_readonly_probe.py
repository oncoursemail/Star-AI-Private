"""Opt-in localhost OBS WebSocket v5 OBS *observation* for STAR's private VTuber lab.

Bridges the existing verified-triplet parser to a real authenticated local OBS
connection. ONLY GetStats, GetStreamStatus and GetRecordStatus are sent. It
never starts/stops recording, changes scenes, broadcasts, captures private
media, or grants permission to perform another action.

No network attempt without owner_approved=True. No remote host, URL, redirects,
or arbitrary request types are accepted. Password comes from the trusted host;
do not expose it to a model or pass it on command lines. Only sanitized
aggregate counters are returned. A WebSocket password is not an authorization
to issue OBS state-changing requests.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
import secrets
import time
from typing import Callable, Protocol, cast

from .stream_obs_readonly_evidence import ObsReadOnlyEvidenceGate, ObsReadOnlyWitness

_READS = ("GetStats", "GetStreamStatus", "GetRecordStatus")
_MAX_WIRE_BYTES = 64 * 1024


class _WebSocket(Protocol):
    def recv(self) -> object: ...
    def send(self, message: str) -> object: ...
    def close(self) -> object: ...


def _local_connection(port: int, timeout_s: float) -> _WebSocket:
    """Optional host-only dependency; no arbitrary server URL or proxy."""
    import websocket  # type: ignore[import-untyped]

    return cast(_WebSocket, websocket.create_connection(
        f"ws://127.0.0.1:{port}",
        timeout=timeout_s,
        subprotocols=["obswebsocket.json"],
        http_no_proxy=["127.0.0.1"],
    ))


def _packet(raw: object, op: int) -> dict[str, object]:
    if type(raw) is not str or len(raw.encode("utf-8")) > _MAX_WIRE_BYTES:
        raise ValueError("invalid OBS message bounds")
    message = json.loads(raw)
    if type(message) is not dict or type(message.get("op")) is not int or message["op"] != op:
        raise ValueError("unexpected OBS operation")
    data = message.get("d")
    if type(data) is not dict:
        raise ValueError("invalid OBS operation body")
    return cast(dict[str, object], data)


def _write(sock: _WebSocket, op: int, data: dict[str, object]) -> None:
    sock.send(json.dumps({"op": op, "d": data}, separators=(",", ":")))


def _authentication(password: str, salt: str, challenge: str) -> str:
    if (type(password) is not str or not 1 <= len(password) <= 2048
            or type(salt) is not str or not 1 <= len(salt) <= 256
            or type(challenge) is not str or not 1 <= len(challenge) <= 256):
        raise ValueError("invalid OBS authentication challenge")
    secret = base64.b64encode(sha256((password + salt).encode("utf-8")).digest()).decode("ascii")
    return base64.b64encode(sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")


@dataclass(frozen=True)
class LocalObsProbeReport:
    status: str  # candidate | deferred | unavailable
    reason: str
    samples: int
    render_skipped_fraction: float | None = None
    output_skipped_fraction: float | None = None
    nonbroadcast_verified_only_at_sample_times: bool = False
    recording_verified: bool = False
    authorizes_broadcast: bool = False
    authorizes_recording: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def observe_local_obs(
    *, owner_approved: bool = False, password: str | None = None,
    port: int = 4455, samples: int = 3, timeout_s: float = 2.0,
    interval_s: float = 0.5,
    connect: Callable[[int, float], _WebSocket] = _local_connection,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    token: Callable[[int], str] = secrets.token_hex,
) -> LocalObsProbeReport:
    """Read only three OBS requests per sample over one authenticated connection.

    Authenticated transport and local-only connection must be enforced by the
    trusted host; injected fakes are for offline deterministic tests only.
    A passing observation is advisory and does not prove continuous nonbroadcast
    safety between samples or actual game/voice/avatar/recording playback.
    """
    if owner_approved is not True:
        raise PermissionError("explicit local OBS observation required")
    if (type(port) is not int or not 1024 <= port <= 65535
            or type(samples) is not int or not 2 <= samples <= 9
            or type(timeout_s) not in (int, float) or not 0.25 <= timeout_s <= 5
            or type(interval_s) not in (int, float) or not 0.25 <= interval_s <= 2
            or not all(callable(fn) for fn in (connect, clock, sleep, token))):
        raise ValueError("invalid bounded local OBS configuration")
    if type(password) is not str or not 1 <= len(password) <= 2048:
        return LocalObsProbeReport("unavailable", "local_obs_password_required", 0)

    socket = connect(port, float(timeout_s))
    gate = ObsReadOnlyEvidenceGate(owner_approved=True)
    try:
        hello = _packet(socket.recv(), 0)
        rpc_version = hello.get("rpcVersion")
        if type(rpc_version) is not int or rpc_version < 1:
            raise ValueError("unsupported OBS RPC version")
        auth = hello.get("authentication")
        if type(auth) is not dict:
            raise PermissionError("OBS server authentication is required")
        salt, challenge = auth.get("salt"), auth.get("challenge")
        if type(salt) is not str or type(challenge) is not str:
            raise ValueError("OBS challenge missing")
        _write(socket, 1, {
            "rpcVersion": 1, "eventSubscriptions": 0,
            "authentication": _authentication(password, salt, challenge),
        })
        identified = _packet(socket.recv(), 2)
        if identified.get("negotiatedRpcVersion") != 1:
            raise ValueError("OBS RPC version negotiation failed")

        for sample in range(samples):
            if sample:
                sleep(float(interval_s))
            witnessed: dict[str, ObsReadOnlyWitness] = {}
            expected: dict[str, str] = {}
            for kind in _READS:
                request_id = token(12)
                if (type(request_id) is not str or not 12 <= len(request_id) <= 40
                        or not request_id.isascii() or not request_id.isalnum()):
                    raise ValueError("invalid OBS request identity")
                expected[kind] = request_id
                _write(socket, 6, {"requestType": kind, "requestId": request_id})
                # Validate both op and response binding in the existing gate.
                reply = _packet(socket.recv(), 7)
                witnessed[kind] = ObsReadOnlyWitness(
                    at_monotonic_ms=float(clock()) * 1000,
                    message={"op": 7, "d": reply},
                )
            gate.accept(witnesses=witnessed, expected_request_ids=expected, host_verified=True)
    finally:
        socket.close()

    report = gate.report()
    sample_count = report["sample_count"]
    if type(sample_count) is not int:
        raise ValueError("OBS parser returned invalid sample count")
    return LocalObsProbeReport(
        "candidate", "authenticated_readonly_observations_only",
        sample_count,
        cast(float | None, report["render_skipped_fraction"]),
        cast(float | None, report["output_skipped_fraction"]),
        bool(report["nonbroadcast_verified_only_at_sample_times"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STAR: local OBS v5 read-only rehearsal probe")
    parser.add_argument("--observe", action="store_true",
                        help="explicitly connect to OBS on localhost; NEVER broadcasts")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval-ms", type=int, default=500)
    parser.add_argument("--port", type=int, default=4455)
    args = parser.parse_args(argv)
    if not args.observe:
        print(LocalObsProbeReport("unavailable", "explicit_observe_flag_required", 0).to_json())
        return 2
    try:
        report = observe_local_obs(
            owner_approved=True, password=os.getenv("STAR_OBS_WEBSOCKET_PASSWORD"),
            samples=args.samples, interval_s=args.interval_ms / 1000, port=args.port,
        )
    except PermissionError:
        report = LocalObsProbeReport("deferred", "obs_authentication_or_output_state_rejected", 0)
    except Exception:  # transport exceptions must never print OBS credentials/URLs
        report = LocalObsProbeReport("unavailable", "obs_local_connection_or_evidence_unavailable", 0)
    print(report.to_json())
    return 0 if report.status == "candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
