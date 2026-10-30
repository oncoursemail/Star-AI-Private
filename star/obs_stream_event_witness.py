"""Authenticated, opt-in OBS output-event witness for local A/B stream tests.

One OBS WebSocket v5 connection subscribes to General + Outputs events and
uses read-only GetStreamStatus request/response fences on THAT SAME socket.
TCP ordering lets the collector drain prior events before accepting each
checkpoint; a vanished or unresponsive socket fails closed. No listener is
silently reconnected. The fence interval deliberately ENVELOPS the independent
OBS frame/transport sampling window.

This is local-only software, not permission to start OBS, broadcast, capture
media, read stream settings, or change scene/audio sources. No event payload,
password, stream key or OBS metadata is persisted.
"""
from __future__ import annotations

from typing import cast

import base64
import hashlib
import json
import math
import secrets
from typing import Callable


class ObsEventWitnessError(RuntimeError):
    """An OBS event interval could not be independently verified."""


def _open_local_ws(*, url: str, timeout: int, enable_multithread: bool) -> object:
    # websocket-client is a dependency of the existing obsws-python package.
    import websocket

    return websocket.create_connection(
        url, timeout=timeout, enable_multithread=enable_multithread
    )


def _local_process_identity() -> tuple[int, float]:
    # Deferred import avoids a cycle with the opt-in sampling host.
    from .obs_readonly_benchmark_host import local_obs_process_identity

    return local_obs_process_identity()


def _valid_process(identity: object) -> bool:
    return (
        type(identity) is tuple and len(identity) == 2
        and type(identity[0]) is int and identity[0] > 0
        and type(identity[1]) in (int, float)
        and math.isfinite(identity[1]) and identity[1] > 0
    )


def _message(ws: object) -> dict:
    """Decode only bounded wire frames; never expose raw OBS content."""
    raw = getattr(ws, "recv")()
    if type(raw) is not str or len(raw) > 65536:
        raise ValueError("unexpected OBS wire frame")
    message = json.loads(raw)
    if type(message) is not dict or type(message.get("d")) is not dict:
        raise ValueError("invalid OBS wire message")
    if type(message.get("op")) is not int:
        raise ValueError("invalid OBS opcode")
    return message


def _send(ws: object, op: int, data: dict) -> None:
    getattr(ws, "send")(json.dumps({"op": op, "d": data}, separators=(",", ":")))


class ObsStreamContinuityWitness:
    """Separate local OBS event connection, never enabled by model output.

    The owner-approved desktop host supplies the password; it is used for the
    standard OBS v5 challenge/response and not stored after connection.
    A witness can be reused for successive capture windows, but cannot
    overlap them. Unexpected disconnects/restarts/events revoke eligibility.

    Request fences are intentionally synchronous: they avoid a background
    event thread whose callback queue might lag behind certification.
    Each fence must receive a matching GetStreamStatus response within the
    socket timeout. StreamStateChanged (even a return to healthy output) and
    ExitStarted events invalidate an armed window.
    """

    def __init__(
        self, *,
        socket_factory: Callable[..., object] = _open_local_ws,
        process_identity: Callable[[], tuple[int, float]] = _local_process_identity,
    ) -> None:
        if not callable(socket_factory) or not callable(process_identity):
            raise TypeError("OBS event dependencies must be callables")
        self._factory = socket_factory
        self._identity = process_identity
        self._ws: object | None = None
        self._process: tuple[int, float] | None = None
        self._armed = False
        self._disrupted = True

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def connect(self, *, password: str, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("authorized owner must enable OBS event inspection")
        if type(password) is not str or not 1 <= len(password) <= 256:
            raise ValueError("provide the authenticated OBS WebSocket password")
        if self._ws is not None:
            raise RuntimeError("disconnect before opening another OBS event session")

        ws = None
        try:
            identity = self._identity()
            if not _valid_process(identity):
                raise ValueError("local OBS process identity unavailable")
            ws = self._factory(
                url="ws://127.0.0.1:4455", timeout=3,
                enable_multithread=True,
            )
            hello = _message(ws)
            if hello["op"] != 0:
                raise ValueError("not an OBS v5 Hello")
            data = hello["d"]
            if type(data.get("obsWebSocketVersion")) is not str:
                raise ValueError("missing OBS version")
            if not data["obsWebSocketVersion"].startswith("5."):
                raise ValueError("incompatible OBS protocol")
            if type(data.get("rpcVersion")) is not int or data["rpcVersion"] < 1:
                raise ValueError("unsupported OBS RPC")
            auth = data.get("authentication")
            # An unauthenticated OBS WebSocket is NOT eligible for this host.
            if type(auth) is not dict:
                raise ValueError("OBS WebSocket authentication must be enabled")
            challenge, salt = auth.get("challenge"), auth.get("salt")
            if any(type(x) is not str or not 1 <= len(x) <= 256
                   for x in (challenge, salt)):
                raise ValueError("invalid OBS authentication challenge")
            challenge = cast(str, challenge)
            salt = cast(str, salt)
            secret = base64.b64encode(
                hashlib.sha256((password + salt).encode("utf-8")).digest()
            ).decode("ascii")
            response = base64.b64encode(
                hashlib.sha256((secret + challenge).encode("utf-8")).digest()
            ).decode("ascii")
            # Subscription bits: General=1, Outputs=64. No input/mic/scene data.
            _send(ws, 1, {
                "rpcVersion": 1, "authentication": response,
                "eventSubscriptions": 65,
            })
            identified = _message(ws)
            if identified["op"] != 2 or (
                identified["d"].get("negotiatedRpcVersion") != 1
            ):
                raise ValueError("OBS did not confirm the authenticated session")
            if self._identity() != identity:
                raise ValueError("OBS restarted while connecting")
            self._ws = ws
            self._process = identity
            self._armed = False
            self._disrupted = True
        except Exception:
            if ws is not None:
                try:
                    getattr(ws, "close")()
                except Exception:
                    pass
            raise ObsEventWitnessError(
                "cannot verify authenticated local OBS event connection"
            ) from None

    def disconnect(self) -> None:
        ws = self._ws
        self._ws = None
        self._process = None
        self._armed = False
        self._disrupted = True
        if ws is not None:
            try:
                getattr(ws, "close")()
            except Exception:
                pass

    def _check_identity(self, expected_process: tuple[int, float]) -> None:
        if (
            self._ws is None or self._process is None
            or not _valid_process(expected_process)
            or self._process != expected_process
            or self._identity() != expected_process
        ):
            raise ValueError("OBS process identity changed")

    def _fence(self) -> None:
        """Drain prior output events then verify a fresh active stream status."""
        assert self._ws is not None
        token = secrets.token_hex(12)
        _send(self._ws, 6, {
            "requestType": "GetStreamStatus",
            "requestId": token,
        })
        # Bounded number of events protects against unbounded event flooding;
        # the socket itself has a 3-second request timeout.
        for _ in range(256):
            message = _message(self._ws)
            code, data = message["op"], message["d"]
            if code == 5:
                kind = data.get("eventType")
                if kind in ("StreamStateChanged", "ExitStarted"):
                    self._disrupted = True
                elif type(kind) is not str:
                    raise ValueError("malformed OBS event")
                # Deliberately discard all eventData (including record paths).
                continue
            if code != 7:
                raise ValueError("unexpected OBS message during event fence")
            if (
                data.get("requestType") != "GetStreamStatus"
                or data.get("requestId") != token
                or type(data.get("requestStatus")) is not dict
                or data["requestStatus"].get("result") is not True
                or type(data.get("responseData")) is not dict
            ):
                raise ValueError("unverified OBS stream-status response")
            response = data["responseData"]
            if (
                response.get("outputActive") is not True
                or response.get("outputReconnecting") is not False
            ):
                raise ValueError("OBS stream stopped or is reconnecting")
            return
        raise ValueError("too many OBS messages before status fence")

    def begin(self, expected_process: tuple[int, float]) -> None:
        if self._armed:
            raise ObsEventWitnessError("another OBS event window is active")
        try:
            self._check_identity(expected_process)
            # Drain stale pre-window events before arming; later events remain
            # on this same reliable ordered transport until the next fence.
            self._fence()
            self._disrupted = False
            self._armed = True
        except Exception:
            self.disconnect()
            raise ObsEventWitnessError("OBS event window could not be armed") from None

    def checkpoint(self, expected_process: tuple[int, float]) -> None:
        if not self._armed:
            raise ObsEventWitnessError("no authenticated OBS event window is active")
        try:
            self._check_identity(expected_process)
            self._fence()
            self._check_identity(expected_process)
            if self._disrupted:
                raise ValueError("OBS output changed during benchmark")
        except Exception:
            self.disconnect()
            raise ObsEventWitnessError("OBS event continuity is unverifiable") from None

    def finish(self, expected_process: tuple[int, float]) -> bool:
        self.checkpoint(expected_process)
        self._armed = False
        # The caller samples OBS INSIDE the begin/finish fence interval.
        return True


__all__ = ["ObsStreamContinuityWitness", "ObsEventWitnessError"]
