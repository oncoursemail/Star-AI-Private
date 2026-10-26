"""Opt-in local VTube Studio transport for playback-locked Star animation.

This module deliberately owns no microphone, game controls, broadcast, credentials
on disk, or network listener. Only an explicit owner action can open the local
VTS socket. The host supplies sound-device timing and a StagePlan validated by
VTubeLive2DBridge; generated text cannot authenticate or send its own packets.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from threading import RLock
from typing import Any, Callable

from .vtube_live2d_bridge import VTubeLive2DBridge

_LOCAL_ENDPOINT = re.compile(r"ws://(?:127\.0\.0\.1|\[::1\]):([0-9]{1,5})\Z")
_TOKEN = re.compile(r"[\x21-\x7e]{1,64}\Z")


class VTSHostError(RuntimeError):
    """Local VTube Studio session failed without disclosing credentials."""


def _default_socket(url: str, timeout_s: float) -> Any:
    try:
        from websocket import create_connection  # optional websocket-client dependency
    except ImportError as exc:
        raise VTSHostError("Install websocket-client on the authorized VTuber host") from exc
    return create_connection(url, timeout=timeout_s, enable_multithread=True)


class VTubeLocalHost:
    """Synchronous, fail-closed transport; call only from a trusted host worker.

    Do not share this object with language-model tools or chat. Calling connect()
    may trigger the VTS permission dialog, only with allow_new_token=True. A
    previously permitted token should come from OS-protected local storage.
    The returned token must NEVER be logged or added to a Git repository.

    No frames are queued: network blocking, failure, or interruptions drop
    output instead of replaying stale facial expressions. VTS custom parameter
    mappings must be configured manually on the owner's Live2D model.
    """

    def __init__(
        self,
        bridge: VTubeLive2DBridge,
        *,
        owner_approved: bool = False,
        endpoint: str = "ws://127.0.0.1:8001",
        socket_factory: Callable[[str, float], Any] = _default_socket,
        monotonic: Callable[[], float] = time.monotonic,
        timeout_s: float = 2.0,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must explicitly approve local avatar connection")
        if not isinstance(bridge, VTubeLive2DBridge):
            raise TypeError("expected VTubeLive2DBridge")
        match = _LOCAL_ENDPOINT.fullmatch(endpoint) if isinstance(endpoint, str) else None
        if not match or not (1 <= int(match.group(1)) <= 65535):
            raise ValueError("VTube Studio endpoint must be an explicit IP loopback ws:// address")
        if type(timeout_s) not in (int, float) or not (0.1 <= timeout_s <= 5.0):
            raise ValueError("timeout_s must be between 0.1 and 5 seconds")
        if not callable(socket_factory) or not callable(monotonic):
            raise TypeError("socket_factory and monotonic must be callable")
        self._bridge = bridge
        self._stage = bridge._stage  # same stage used to authorize the motion adapter
        self._endpoint = endpoint
        self._socket_factory = socket_factory
        self._monotonic = monotonic
        self._timeout_s = float(timeout_s)
        self._lock = RLock()
        self._socket: Any = None
        self._registered = False
        self._nonce = secrets.token_hex(6)
        self._counter = 0

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._socket is not None

    def _close_locked(self) -> None:
        sock, self._socket = self._socket, None
        self._registered = False
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    def close(self) -> None:
        """Forget session state. VTS automatically releases input overrides on loss."""
        with self._lock:
            self._close_locked()

    def _exchange(self, message_type: str, data: dict[str, Any]) -> dict[str, Any]:
        if self._socket is None:
            raise VTSHostError("VTube Studio session is closed")
        self._counter += 1
        request_id = f"Star{self._nonce}{self._counter}"
        request = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": request_id,
            "messageType": message_type,
            "data": data,
        }
        try:
            self._socket.send(json.dumps(request, separators=(",", ":")))
            raw = self._socket.recv()
            if not isinstance(raw, str) or len(raw) > 65536:
                raise VTSHostError("invalid or oversized VTS response")
            reply = json.loads(raw)
            if not isinstance(reply, dict) or reply.get("requestID") != request_id:
                raise VTSHostError("unexpected VTS response request ID")
            if reply.get("apiName") != "VTubeStudioPublicAPI" or reply.get("apiVersion") != "1.0":
                raise VTSHostError("invalid VTS protocol header")
            if reply.get("messageType") == "APIError":
                raise VTSHostError("VTube Studio refused the request")
            if reply.get("messageType") != message_type.replace("Request", "Response"):
                raise VTSHostError("unexpected VTS response type")
            payload = reply.get("data")
            if not isinstance(payload, dict):
                raise VTSHostError("VTS response has invalid data")
            return payload
        except Exception as exc:
            self._close_locked()
            if isinstance(exc, VTSHostError):
                raise
            raise VTSHostError("VTube Studio communication failed") from None

    def connect(self, *, authentication_token: str | None = None, allow_new_token: bool = False) -> str:
        """Authenticate to the owner-approved local VTS socket.

        A new token requires a separate explicit pairing flag; VTS presents a
        native permission dialog. Returned tokens live only in caller memory.
        Re-pairing on errors is intentionally never automatic.
        """
        if authentication_token is None and allow_new_token is not True:
            raise PermissionError("explicit approval required before VTS pairing")
        if authentication_token is not None and (
            not isinstance(authentication_token, str) or not _TOKEN.fullmatch(authentication_token)
        ):
            raise ValueError("invalid local VTS token format")
        with self._lock:
            if self._socket is not None:
                raise VTSHostError("session already connected")
            self._registered = False
            try:
                self._socket = self._socket_factory(self._endpoint, self._timeout_s)
                if not callable(getattr(self._socket, "settimeout", None)):
                    raise VTSHostError("VTS transport requires bounded socket timeouts")
                state = self._exchange("APIStateRequest", {})
                if state.get("active") is not True:
                    raise VTSHostError("VTube Studio plugin API is disabled")
                if authentication_token is None:
                    self._socket.settimeout(30.0)  # native owner permission popup
                    reply = self._exchange(
                        "AuthenticationTokenRequest",
                        {"pluginName": "Star AI", "pluginDeveloper": "Star Project"},
                    )
                    authentication_token = reply.get("authenticationToken")
                    if not isinstance(authentication_token, str) or not _TOKEN.fullmatch(authentication_token):
                        raise VTSHostError("VTube Studio did not provide a valid token")
                self._socket.settimeout(self._timeout_s)
                reply = self._exchange(
                    "AuthenticationRequest",
                    {
                        "pluginName": "Star AI",
                        "pluginDeveloper": "Star Project",
                        "authenticationToken": authentication_token,
                    },
                )
                if reply.get("authenticated") is not True:
                    raise VTSHostError("VTube Studio denied authentication")
                return authentication_token
            except Exception as exc:
                self._close_locked()
                if isinstance(exc, (VTSHostError, PermissionError, ValueError)):
                    raise
                raise VTSHostError("Unable to establish local VTube Studio session") from None

    def register_parameters(self) -> None:
        """Create Star's 14 custom parameters; artist must still map the rig."""
        with self._lock:
            if self._socket is None:
                raise VTSHostError("not authenticated")
            if self._registered:
                return
            for packet in self._bridge.registration_requests():
                self._exchange(packet["messageType"], packet["data"])
            try:
                self._socket.settimeout(0.10)  # no multi-second latency in gameplay
            except Exception:
                self._close_locked()
                raise VTSHostError("Unable to enable bounded realtime socket I/O") from None
            self._registered = True

    def send_frame(
        self,
        plan: Any,
        *,
        playback_epoch: str,
        frame: Any,
        audible_cursor_s: float,
        sampled_ms: float,
    ) -> bool:
        """Send only a current, fresh, already played motion frame.

        sampled_ms MUST use the same monotonic clock as monotonic. A
        blocked sender discards frames if the sample is >100 ms old. No packet
        buffering or retries. False means no frame was sent.
        """
        with self._lock:
            if self._socket is None or not self._registered:
                raise VTSHostError("VTube Studio parameters are not registered")
            now_ms = self._monotonic() * 1000.0
            if type(sampled_ms) not in (float, int) or not (0 <= now_ms - sampled_ms <= 100):
                return False
            if not self._stage.current(plan):
                return False
            packet = self._bridge.frame_packet(
                plan,
                playback_epoch=playback_epoch,
                frame=frame,
                audible_cursor_s=audible_cursor_s,
                sampled_ms=sampled_ms,
            )
            if packet is None or not self._stage.current(plan):
                return False
            self._exchange(packet["messageType"], packet["data"])
            return True

    def send_neutral(self, plan: Any, *, playback_epoch: str, playback_stopped: bool = False) -> bool:
        """Release controls once, but only after trusted audio-stop callback."""
        with self._lock:
            if self._socket is None or not self._registered:
                raise VTSHostError("VTube Studio parameters are not registered")
            packet = self._bridge.reset(
                plan, playback_epoch=playback_epoch, playback_stopped=playback_stopped
            )
            if packet is None:
                return False
            self._exchange(packet["messageType"], packet["data"])
            return True


__all__ = ["VTSHostError", "VTubeLocalHost"]
