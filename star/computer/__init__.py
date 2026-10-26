"""STAR uses any app on her own PC with her own mouse and keyboard (owner, 2026-10-26).

screen.py     Element / Screen: what is on screen, how to find a control, whether two looks differ
uia.py        Windows UI Automation (comtypes): exact control names, roles and rectangles in ~150-280 ms
grounding.py  vision grounding behind one interface (UI-TARS, Qwen3-VL, ShowUI ... through any OpenAI-style endpoint)
hands.py      human-like mouse and keyboard on star/play/humanlike.py, the owner's STOP, a log line per action
agent.py      Computer.see() and Computer.act(goal): observe, plan, act, verify, recover
draw.py       the "draw" activity: stroke plan from the model, painted in MS Paint, saved and checked
risk.py       money, public posts and accounts go to the owner; no typing into password fields
Research: docs/research/computer-use-20261026.md. Notes: docs/agents/computer-use-20261026.md.
Plug-in for STAR Home: `register_home_activities(registry)` adds "draw" (interest drawing) and "use_app"
(interest use_apps; the interest needs a seed in star/home/life.py or STAR adds it herself with set_interest).
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
import os
import sys
import threading
from typing import Any

from . import settings as _settings


@dataclass
class _CaptureOwner:
    computer: Any = None
    active: bool = True


_CAPTURE_OWNERS: dict[str, _CaptureOwner] = {}
_CAPTURE_OWNERS_LOCK = threading.Lock()


def _ownership_key(home) -> str:
    return os.path.normcase(str(Path(home).expanduser().resolve()))


def _finish_capture(key: str, owner: _CaptureOwner, complete: bool) -> None:
    with _CAPTURE_OWNERS_LOCK:
        if _CAPTURE_OWNERS.get(key) is owner:
            owner.active = False
            if complete is True:
                del _CAPTURE_OWNERS[key]


def _claim_capture(home) -> tuple[str, _CaptureOwner]:
    key = _ownership_key(home)
    with _CAPTURE_OWNERS_LOCK:
        previous = _CAPTURE_OWNERS.get(key)
        if previous is not None and previous.active:
            raise RuntimeError('another computer activity is active for this home')
    if previous is not None:
        try:
            complete = previous.computer.close(timeout=0) is True
        except Exception:
            complete = False
        if not complete:
            raise RuntimeError('previous desktop capture is still closing')
    with _CAPTURE_OWNERS_LOCK:
        current = _CAPTURE_OWNERS.get(key)
        if current is not None and current is not previous:
            raise RuntimeError('another computer activity acquired this home')
        owner = _CaptureOwner()
        _CAPTURE_OWNERS[key] = owner
        return key, owner


def _close_result(computer, result: dict) -> None:
    try:
        complete = computer.close(timeout=.2) is True
    except Exception:
        complete = False
    if not complete:
        result['ok'] = result['verified'] = result['goal_done'] = False
        result.setdefault('failures', []).append('desktop capture cleanup is still pending')
        result['summary'] = str(result.get('summary', ''))[:520] + '; desktop capture cleanup is still pending'


def build_computer(ctx):  # pragma: no cover - builds the real Windows backends
    """A Computer wired to the real desktop for one STAR Home activity context."""
    from .agent import Computer, Guard
    from .eye import ScreenEye
    from .hands import Hands
    from .uia import ComtypesUia, UiaUnavailable
    from .winapi import DesktopSink, Windows, ensure_dpi_aware
    from ..home import control

    def cancelled() -> bool:
        try:
            interrupt = getattr(ctx, 'interrupt', None)
            return (control.stopped(ctx.home)
                    or (interrupt is not None and bool(interrupt.is_set())))
        except Exception:
            return True

    def blocked() -> bool:
        try:
            return bool(ctx.executor.dry_run) or cancelled()
        except Exception:
            return True

    key, owner = _claim_capture(ctx.home)
    computer = None
    try:
        ensure_dpi_aware()
        windows = Windows()
        guard = Guard(windows, None)
        cfg = _settings.load(ctx.home)
        try:
            uia = ComtypesUia()
        except UiaUnavailable:
            uia = None
        hands = Hands(DesktopSink(guard), home=ctx.home, dry_run=bool(getattr(ctx.executor, 'dry_run', False)),
                      watch_pointer=True, stopped=cancelled)
        eye = ScreenEye(stopped=blocked)
        computer = Computer(hands, windows=windows, uia=uia, eye=eye,
                            grounder=_settings.make_grounder(cfg), chat=ctx.chat, executor=ctx.executor,
                            guard=guard, settings=cfg, home=ctx.home, stopped=cancelled)
        owner.computer = computer
        computer._on_close = lambda complete: _finish_capture(key, owner, complete)
        if not blocked():
            eye.start()
        return computer
    except BaseException:
        if computer is not None:
            computer.close(timeout=0)
        else:
            _finish_capture(key, owner, True)
        raise


def _ask(chat, system: str, user: str, limit: int) -> str:
    reply = chat([{"role": "system", "content": system}, {"role": "user", "content": user}], [])
    return " ".join(str(reply.get("content") or "").split()).strip(" \"'")[:limit]


def _gallery(ctx) -> Path:
    workspace = getattr(ctx.executor, "workspace", None) or Path(ctx.home).parent / "workspace"
    return Path(workspace) / "gallery"


def draw_activity(ctx) -> dict:  # pragma: no cover - needs her desktop; the parts are tested in tests/test_computer_use.py
    from . import draw
    if sys.platform != "win32":
        return {"ok": False, "verified": False, "summary": "drawing in Paint needs Windows", "evidence": [],
                "failures": ["draw: not Windows"]}
    gallery = _gallery(ctx)
    recent = ", ".join(sorted(p.stem.split("-", 2)[-1] for p in gallery.glob("*.png"))[-8:]) if gallery.exists() else ""
    subject = (ctx.goal or {}).get("text") or _ask(
        ctx.chat, "You are STAR choosing what to draw next. Reply with a subject of at most six words, nothing else.",
        f"Pick something simple and drawable with a few lines. Already drawn lately: {recent or 'nothing yet'}.", 80)
    plan, error = draw.plan_drawing(ctx.chat, subject)
    if plan is None:
        return {"ok": False, "verified": False, "summary": f"no usable sketch plan for {subject!r}: {error}",
                "evidence": [], "failures": [f"draw: plan rejected ({error})"]}
    if getattr(ctx.executor, "dry_run", False):
        return {"ok": False, "verified": False, "evidence": [], "failures": [],
                "summary": f"dry run: planned {len(plan.strokes)} strokes for {subject!r}, painted nothing"}
    computer = build_computer(ctx)
    result = {}
    try:
        result = draw.draw_session(computer, plan, subject, gallery, settings=_settings.load(ctx.home))
        return result
    finally:
        _close_result(computer, result)


def use_app_activity(ctx) -> dict:  # pragma: no cover - needs her desktop
    if sys.platform != "win32":
        return {"ok": False, "verified": False, "summary": "using apps needs Windows", "evidence": [],
                "failures": ["use_app: not Windows"]}
    goal = (ctx.goal or {}).get("text") or ctx.practice_topic or _ask(
        ctx.chat, "You are STAR on your own PC. Reply with ONE small task to do in an app on this computer (open an "
        "app and do something you can check on screen), at most 25 words, nothing else.",
        "Pick something you have not done lately: a calculation, a note, a setting in one of your own apps, a music "
        "player, a browser search. Nothing that spends money, posts publicly or creates an account.", 200)
    computer = build_computer(ctx)
    result = {}
    try:
        result = computer.act(goal, max_steps=int(ctx.config.get('max_steps', 12)),
                              minutes=float(ctx.config.get('session_minutes', 20)))
        result['summary'] = f"{goal[:120]}: {result['summary']}"[:600]
        return result
    finally:
        _close_result(computer, result)


def register_home_activities(registry) -> None:
    registry.register("draw", "drawing", draw_activity, "paint a sketch in MS Paint and save it to the gallery",
                      needs_brain=True)
    registry.register("use_app", "use_apps", use_app_activity, "use any app with her own mouse and keyboard",
                      needs_brain=True)
