"""STAR Camera: her VTuber avatar as a real Windows webcam (issue #613, owner 2026-10-26).

lipsync.py     her voice -> 20 ms mouth frames on an audible-time line; LipSyncSpeaker wraps her Speaker; UDP feed
rig.py         mouth + mood + events -> a Pose per frame (blinks, breathing, sway, cues; emotion.avatar(), game reactions)
model.py       the layered 2D avatar model (avatar.json + PNG layers; "starface" = the mascot art as it is)
placeholder.py a generated test character (not Star's art) for tests and the first run
sinks.py       the virtual camera named "STAR Camera" (pyvirtualcam + Unity Capture), memory and PNG sinks
vmc.py         the same pose as VMC/OSC for a VRM avatar in VSeeFace or Warudo
camera.py      the frame loop (fixed clock, frame dropping, quality and fps degrade under load)
control.py     config, hidden below-normal camera process, heartbeat, `python -m star.vtuber on|off|status`
discord_ui.py  camera and screen share in a Discord call, through the real app (screenshot -> click -> confirm twice)
activities.py  star-home activities: "camera on", "camera off", "share screen", "stop sharing"

Driver install: installer/star-camera/install-camera.cmd. Notes: docs/agents/vtuber-camera-20261026.md.
"""


def register_home_activities(registry) -> None:
    from .activities import register_home_activities as register
    register(registry)


def attach_speaker(speaker, folder=None):
    """For the voice call: her Speaker wrapped so the camera lip-syncs to what is about to be played.

        speaker = star.vtuber.attach_speaker(speaker)

    The mouth frames go by UDP to 127.0.0.1 (port from the camera config), so this works across processes and costs
    nothing when the camera is off. If anything about the camera is broken the original speaker is returned."""
    try:
        from . import control
        from .lipsync import LipSyncSpeaker, UdpFeed
        return LipSyncSpeaker(speaker, UdpFeed(control.load_config(folder).feed_port))
    except Exception:
        return speaker


def emit_event(kind: str, strength: float = 1.0, folder=None) -> None:
    """Tell the avatar something happened (see rig.REACTIONS: game_danger, game_win, video_funny, friend_joined ...).
    Unknown kinds are ignored by the camera. Never raises."""
    try:
        from . import control
        from .lipsync import UdpFeed
        feed = UdpFeed(control.load_config(folder).feed_port)
        feed.event(kind, strength)
        feed.close()
    except Exception:
        pass


def emit_expression(name: str, *, duration_s: float | None = None, strength: float = 1.0, folder=None) -> None:
    """An explicit cosmetic expression; never changes emotion state or starts a camera."""
    import math
    from .expressions import encode_expression
    if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("expression strength must be a finite number between zero and one")
    emit_event(encode_expression(name, duration_s=duration_s), strength, folder)
