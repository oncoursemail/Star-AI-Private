"""STAR Home activities for the camera: "camera on", "camera off", "share screen", "stop sharing".

They belong to the interest "video_call", which the scheduler never picks on its own (it is not in her interests list):
the code that answers or joins a Discord call runs them by name, for example
    registry.items["camera on"].run(ctx)
Each returns the usual {ok, verified, summary, evidence}. "verified" needs BOTH an independent read of the Discord
screen (two screenshots) AND, for the camera, frames really flowing out of the camera process.
"""
from __future__ import annotations

from typing import Callable

from . import control
from .discord_ui import DiscordVideo, ExecutorUi, vision_planner

INTEREST = "video_call"


def _video(ctx) -> DiscordVideo:                                       # pragma: no cover - needs the real desktop
    return DiscordVideo(ExecutorUi(ctx.executor), vision_planner())


def _result(ok: bool, verified: bool, summary: str, evidence: list[str], failures: list[str] | None = None) -> dict:
    out = {"ok": ok, "verified": verified, "summary": summary, "evidence": evidence}
    if failures:
        out["failures"] = failures
    return out


def camera_on(ctx, *, video: DiscordVideo | None = None, ctl=control) -> dict:
    """Start the STAR Camera process, then switch the camera on in the call and pick "STAR Camera" there."""
    from ..home import control as home_control
    if getattr(getattr(ctx, "executor", None), "dry_run", False):
        return _result(True, False, "dry run: no camera process or call camera started", [])
    home = getattr(ctx, "home", None) or home_control.home_dir()
    interrupt = getattr(ctx, "interrupt", None)
    cancelled = lambda: (home_control.stopped(home) or (interrupt is not None and interrupt.is_set())
                         or bool(getattr(getattr(ctx, "executor", None), "dry_run", False)))
    if cancelled():
        return _result(False, False, "camera startup stopped", [])
    folder = ctl.data_dir()
    status = ctl.start(folder)
    if cancelled():
        ctl.stop(folder)
        return _result(False, False, "camera startup stopped", [])
    if not status.get("alive") or status.get("error"):
        why = status.get("error") or "the camera process did not start"
        return _result(False, False, f"STAR Camera is not running: {why}", [str(status)[:200]],
                       [f"vtuber: {why}"])
    step = (video or _video(ctx)).ensure("camera_on")
    if cancelled():
        ctl.stop(folder)
        return _result(False, False, "camera startup stopped", [])
    flowing = ctl.frames_flowing(folder)
    if cancelled():
        ctl.stop(folder)
        return _result(False, False, "camera startup stopped", [])
    evidence = [*step["evidence"], f"camera process frames flowing: {flowing}"]
    verified = bool(step["verified"] and flowing)
    return _result(bool(step["ok"] and flowing), verified, step["summary"], evidence,
                   None if step["ok"] else [f"discord: {step['summary']}"])


def camera_off(ctx, *, video: DiscordVideo | None = None, ctl=control) -> dict:
    """Switch the camera off in the call first (so Discord is not left showing a frozen frame), then stop the process."""
    step = (video or _video(ctx)).ensure("camera_off")
    stopped = ctl.stop(ctl.data_dir())
    evidence = [*step["evidence"], f"camera process stopped: {stopped.get('stopped')} (forced: {stopped.get('forced')})"]
    return _result(bool(step["ok"] or not step["clicks"]), bool(step["verified"]), step["summary"], evidence,
                   None if step["ok"] else [f"discord: {step['summary']}"])


def share_screen(ctx, *, video: DiscordVideo | None = None, ctl=control) -> dict:
    if not ctl.load_config(ctl.data_dir()).allow_share_screen:
        return _result(False, False, "screen sharing is switched off in the camera config (allow_share_screen)", [])
    step = (video or _video(ctx)).ensure("share_on")
    return _result(step["ok"], step["verified"], step["summary"], step["evidence"],
                   None if step["ok"] else [f"discord: {step['summary']}"])


def stop_sharing(ctx, *, video: DiscordVideo | None = None, ctl=control) -> dict:
    step = (video or _video(ctx)).ensure("share_off")
    return _result(step["ok"], step["verified"], step["summary"], step["evidence"],
                   None if step["ok"] else [f"discord: {step['summary']}"])


def register_home_activities(registry) -> None:
    track = getattr(registry.runtime, "track_activity", None)
    if callable(track):
        track("avatar.camera", lambda: control.stop(control.data_dir()))
    table: list[tuple[str, Callable, str]] = [
        ("camera on", camera_on, "turn on the STAR Camera (her VTuber avatar) in the Discord call she is in"),
        ("camera off", camera_off, "turn the camera off in the call and release the virtual camera"),
        ("share screen", share_screen, "share her screen in the Discord call she is in"),
        ("stop sharing", stop_sharing, "stop the screen share"),
    ]
    for name, run, about in table:
        registry.register(name, INTEREST, run, about)
