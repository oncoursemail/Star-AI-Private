"""VMC protocol sender: drives a 3D VRM avatar in VSeeFace / Warudo / any VMC receiver from the same Pose.

The VMC protocol is OSC over UDP (https://protocol.vmc.info/english): blendshape values `/VMC/Ext/Blend/Val name value`
then `/VMC/Ext/Blend/Apply`, bone poses `/VMC/Ext/Bone/Pos name px py pz qx qy qz qw`, port 39539 on the receiver. VRM0
preset names are used because every receiver understands them (A I U E O, Blink_L, Blink_R, Joy). This is the route to
a VRM body, hair physics and a GPU-drawn model if the owner picks one: the receiver renders, a virtual camera of its own
(VSeeFace has one) shows it, and this module only sends the numbers. No dependencies: the OSC encoding is 30 lines.
"""
from __future__ import annotations

import math
import socket
import struct

from .rig import Pose

DEFAULT_PORT = 39539
_ADDRESSES = ("A", "I", "U", "E", "O")            # lipsync.VISEMES order is aa ih ou ee oh -> A I U E O


def _pad(data: bytes) -> bytes:
    return data + b"\0" * (4 - len(data) % 4)


def osc_message(address: str, *args) -> bytes:
    tags, body = ",", b""
    for arg in args:
        if isinstance(arg, str):
            tags += "s"
            body += _pad(arg.encode("utf-8"))
        elif isinstance(arg, int) and not isinstance(arg, bool):
            tags += "i"
            body += struct.pack(">i", arg)
        else:
            tags += "f"
            body += struct.pack(">f", float(arg))
    return _pad(address.encode()) + _pad(tags.encode()) + body


def osc_bundle(messages: list[bytes]) -> bytes:
    out = _pad(b"#bundle") + struct.pack(">Q", 1)       # time tag 1 = "immediately"
    for message in messages:
        out += struct.pack(">i", len(message)) + message
    return out


def _quat(pitch: float, yaw: float, roll: float) -> tuple[float, float, float, float]:
    """x, y, z, w for small Euler angles in radians (Unity order: Z roll, X pitch, Y yaw)."""
    cx, sx = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    cz, sz = math.cos(roll / 2), math.sin(roll / 2)
    return (sx * cy * cz + cx * sy * sz, cx * sy * cz - sx * cy * sz, cx * cy * sz - sx * sy * cz,
            cx * cy * cz + sx * sy * sz)


def pose_messages(pose: Pose, *, t: float = 0.0) -> list[bytes]:
    """The datagram payloads for one frame (blendshapes first, Apply after them, then the bones)."""
    msgs = [osc_message("/VMC/Ext/OK", 1), osc_message("/VMC/Ext/T", float(t))]
    for name, weight in zip(_ADDRESSES, pose.shape):
        msgs.append(osc_message("/VMC/Ext/Blend/Val", name, min(1.0, weight)))
    msgs.append(osc_message("/VMC/Ext/Blend/Val", "Blink_L", 1.0 - pose.eye_open_left))
    msgs.append(osc_message("/VMC/Ext/Blend/Val", "Blink_R", 1.0 - pose.eye_open_right))
    msgs.append(osc_message("/VMC/Ext/Blend/Val", "Joy", pose.smile))
    msgs.append(osc_message("/VMC/Ext/Blend/Apply"))
    for bone, (pitch, yaw, roll) in {
        "Head": (pose.head_y * 0.5, pose.head_x * 0.7, pose.head_roll * 0.4),
        "Neck": (pose.head_y * 0.25, pose.head_x * 0.3, pose.head_roll * 0.2),
        "Spine": (pose.breath * 0.01, pose.body_lean * 0.15, 0.0),
    }.items():
        qx, qy, qz, qw = _quat(pitch, yaw, roll)
        msgs.append(osc_message("/VMC/Ext/Bone/Pos", bone, 0.0, 0.0, 0.0, qx, qy, qz, qw))
    return msgs


class VmcSink:
    """Pose sink: one OSC bundle per frame to a VMC receiver (127.0.0.1:39539 by default)."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
        self.addr = (host, int(port))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_pose(self, pose: Pose) -> None:
        try:
            self._sock.sendto(osc_bundle(pose_messages(pose, t=pose.t)), self.addr)
        except OSError:
            pass

    def close(self) -> None:
        self._sock.close()
