"""Opt-in *actual* local OBS WebSocket v5 read-only host for STAR rehearsals.

This supplies correlated, monotonic, authenticated protocol responses to the
existing Stream OBS evidence gate. Unlike an offline parser, it owns the raw
socket, uses real opaque request IDs, and drains subscribed output-state events
on that same connection. Any error revokes the session; there is no automatic
reconnect or output-control method.

Only a trusted local owner-controlled process may call connect(). Python
callbacks and socket messages are not cryptographic proof of host integrity.
No game, voice, avatar, OBS output, recording, or stream is started here.
"""
from __future__ import annotations

import base64
import hashlib
import math
import secrets
import time
from threading import Lock
from typing import Callable, cast

from .obs_stream_event_witness import (
    _local_process_identity,
    _message,
    _open_local_ws,
    _send,
    _valid_process,
)
from .stream_obs_readonly_evidence import (
    ObsReadOnlyEvidenceGate,
    ObsReadOnlyWitness,
)
from .stream_rehearsal_recorder import StreamRehearsalRecorder

_READ_ONLY = ("GetStats", "GetStreamStatus", "GetRecordStatus")
# OBS v5 General (1) + Outputs (64). Ignore event payloads, including paths.
_OUTPUT_EVENTS = frozenset({
    "StreamStateChanged", "RecordStateChanged", "ReplayBufferStateChanged",
    "VirtualcamStateChanged", "ExitStarted",
})
_EVENT_LIMIT = 128


class ObsOfflineHostError(RuntimeError):
    """Sanitized failure: never print OBS responses or credentials."""


def _monotonic_ms(clock: Callable[[], float]) -> float:
    try:
        value = clock()
        if type(value) not in (int, float):
            raise ValueError("bad clock")
        measured = float(cast(int | float, value)) * 1000
        if not math.isfinite(measured) or not 0 <= measured <= 1e13:
            raise ValueError("bad clock")
        return measured
    except Exception as exc:
        raise ObsOfflineHostError("trusted monotonic clock unavailable") from exc


class ObsNonbroadcastRehearsalHost:
    """One owner-approved, local, nonbroadcast OBS observation session.

    The authenticated socket receives both request responses and output events.
    Events are processed on the SAME ordered connection before each response.
    On any event, unsafe output status, dropped reply, invalid timestamp, OBS
    restart or downstream failure the entire host session is irrevocably
    revoked. A fresh host/connection is required; no partial sample is promoted.

    This measures OBS counters only. Independent host sources must still prove
    game frame presents, audible PCM, avatar frames and hardware usage. A clean
    sample proves only the checked interval up through its final response.
    """

    def __init__(
        self, *,
        socket_factory: Callable[..., object] = _open_local_ws,
        process_identity: Callable[[], tuple[int, float]] = _local_process_identity,
        monotonic_clock: Callable[[], float] = time.monotonic,
        max_samples: int = 2000,
    ) -> None:
        if not all(callable(fn) for fn in (
            socket_factory, process_identity, monotonic_clock,
        )):
            raise TypeError("trusted OBS dependencies must be callable")
        if type(max_samples) is not int or not 2 <= max_samples <= 10000:
            raise ValueError("max_samples must be 2..10000")
        self._socket_factory = socket_factory
        self._identity_reader = process_identity
        self._clock = monotonic_clock
        self._max_samples = max_samples
        self._mutex = Lock()
        self._socket: object | None = None
        self._identity: tuple[int, float] | None = None
        self._gate: ObsReadOnlyEvidenceGate | None = None
        self._ever_connected = False
        self._revoked = False
        self._sealed = False
        self._final_fence_completed = False

    @property
    def connected(self) -> bool:
        return self._socket is not None and not self._revoked

    def _close_socket(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is not None:
            try:
                getattr(socket, "close")()
            except Exception:
                pass

    def _fail(self) -> None:
        self._revoked = True
        self._final_fence_completed = False
        self._close_socket()

    def connect(self, *, password: str, owner_approved: bool = False) -> None:
        """Authenticate to loopback OBS without storing the password."""
        if owner_approved is not True:
            raise PermissionError("owner approval required for local OBS observation")
        if type(password) is not str or not 1 <= len(password) <= 256:
            raise ValueError("authenticated OBS password is required")
        if not self._mutex.acquire(blocking=False):
            raise ObsOfflineHostError("OBS host is busy")
        try:
            if self._ever_connected or self._revoked or self._sealed:
                raise ObsOfflineHostError("create a fresh host for each rehearsal")
            self._ever_connected = True
            socket: object | None = None
            try:
                identity = self._identity_reader()
                if not _valid_process(identity):
                    raise ValueError("invalid OBS process")
                socket = self._socket_factory(
                    url="ws://127.0.0.1:4455", timeout=3,
                    enable_multithread=True,
                )
                hello = _message(socket)
                if hello["op"] != 0:
                    raise ValueError("missing OBS hello")
                data = hello["d"]
                if (type(data.get("obsWebSocketVersion")) is not str
                        or not data["obsWebSocketVersion"].startswith("5.")
                        or type(data.get("rpcVersion")) is not int
                        or data["rpcVersion"] < 1):
                    raise ValueError("unsupported OBS protocol")
                auth = data.get("authentication")
                if type(auth) is not dict:
                    raise ValueError("authenticated OBS socket required")
                challenge, salt = auth.get("challenge"), auth.get("salt")
                if (type(challenge) is not str or not 1 <= len(challenge) <= 256
                        or type(salt) is not str or not 1 <= len(salt) <= 256):
                    raise ValueError("invalid OBS challenge")
                secret = base64.b64encode(
                    hashlib.sha256((password + salt).encode("utf-8")).digest()
                ).decode("ascii")
                response = base64.b64encode(
                    hashlib.sha256((secret + challenge).encode("utf-8")).digest()
                ).decode("ascii")
                _send(socket, 1, {
                    "rpcVersion": 1, "authentication": response,
                    "eventSubscriptions": 65,
                })
                identified = _message(socket)
                if (identified["op"] != 2
                        or identified["d"].get("negotiatedRpcVersion") != 1
                        or self._identity_reader() != identity):
                    raise ValueError("OBS authenticated session not confirmed")
                self._socket = socket
                self._identity = identity
                self._gate = ObsReadOnlyEvidenceGate(
                    owner_approved=True, max_samples=self._max_samples,
                )
            except Exception:
                if socket is not None:
                    try:
                        getattr(socket, "close")()
                    except Exception:
                        pass
                self._fail()
                raise ObsOfflineHostError(
                    "cannot establish authenticated local OBS observation"
                ) from None
        finally:
            self._mutex.release()

    def _read_response(self, *, kind: str, request_id: str) -> ObsReadOnlyWitness:
        socket = self._socket
        if socket is None:
            raise ValueError("OBS socket absent")
        _send(socket, 6, {"requestType": kind, "requestId": request_id})
        for _ in range(_EVENT_LIMIT):
            message = _message(socket)
            opcode = message["op"]
            data = message["d"]
            if opcode == 5:
                event_type = data.get("eventType")
                if type(event_type) is not str or event_type in _OUTPUT_EVENTS:
                    raise ValueError("OBS output continuity changed")
                # Discard eventData entirely. Never store scene, media or chat.
                continue
            if (opcode != 7 or data.get("requestType") != kind
                    or data.get("requestId") != request_id):
                raise ValueError("OBS response is stale or mismatched")
            return ObsReadOnlyWitness(_monotonic_ms(self._clock), message)
        raise ValueError("OBS event flood: no trustworthy response fence")

    def _sample_locked(
        self, recorder: StreamRehearsalRecorder | None = None,
    ) -> dict[str, object]:
        if (self._revoked or self._sealed or self._socket is None
                or self._identity is None or self._gate is None):
            raise ObsOfflineHostError("no active verified OBS observation session")
        try:
            if self._identity_reader() != self._identity:
                raise ValueError("OBS process changed")
            witnesses: dict[str, ObsReadOnlyWitness] = {}
            request_ids: dict[str, str] = {}
            for kind in _READ_ONLY:
                request_id = "star_obs_" + secrets.token_hex(12)
                request_ids[kind] = request_id
                witnesses[kind] = self._read_response(
                    kind=kind, request_id=request_id,
                )
                if self._identity_reader() != self._identity:
                    raise ValueError("OBS process changed")
            self._gate.accept(
                witnesses=witnesses, expected_request_ids=request_ids,
                host_verified=True, recorder=recorder,
            )
            return self.report()
        except Exception:
            self._fail()
            raise ObsOfflineHostError(
                "OBS read-only status, continuity or recorder check failed"
            ) from None

    def sample(
        self, *, recorder: StreamRehearsalRecorder | None = None,
    ) -> dict[str, object]:
        """Take one triplet; never returns response contents, IDs or credentials."""
        if not self._mutex.acquire(blocking=False):
            raise ObsOfflineHostError("OBS observation already in progress")
        try:
            return self._sample_locked(recorder)
        finally:
            self._mutex.release()

    def finish(
        self, *, recorder: StreamRehearsalRecorder | None = None,
    ) -> dict[str, object]:
        """Add a final same-socket output-state fence and seal this host.

        This is not proof of absence of output transitions after the fence.
        It does not finish the separate gameplay/audio rehearsal recorder.
        """
        if not self._mutex.acquire(blocking=False):
            raise ObsOfflineHostError("OBS observation already in progress")
        try:
            self._sample_locked(recorder)
            self._final_fence_completed = True
            self._sealed = True
            self._close_socket()
            return self.report()
        finally:
            self._mutex.release()

    def report(self) -> dict[str, object]:
        """Privacy-safe state. A valid OBS sample is not broadcast permission."""
        gate = self._gate
        metrics = gate.report() if gate is not None else {
            "sample_count": 0, "render_skipped_fraction": None,
            "output_skipped_fraction": None,
        }
        return {
            "sample_count": metrics["sample_count"],
            "render_skipped_fraction": metrics["render_skipped_fraction"],
            "output_skipped_fraction": metrics["output_skipped_fraction"],
            "continuity_intact_to_last_fence": (
                self._ever_connected and not self._revoked
                and self._final_fence_completed
                and type(metrics["sample_count"]) is int
                and cast(int, metrics["sample_count"]) >= 2
            ),
            "host_revoked": self._revoked,
            "sealed": self._sealed,
            "final_fence_completed": self._final_fence_completed,
            "authorized_to_broadcast": False,
            "note": (
                "authenticated local OBS read-only samples; no game FPS, "
                "audio quality, avatar witness or broadcasting permission"
            ),
        }

    def close(self) -> None:
        """Owner-owned teardown: never sends an OBS output command."""
        if not self._mutex.acquire(blocking=False):
            raise ObsOfflineHostError("OBS observation already in progress")
        try:
            self._sealed = True
            self._close_socket()
        finally:
            self._mutex.release()


__all__ = ["ObsNonbroadcastRehearsalHost", "ObsOfflineHostError"]
