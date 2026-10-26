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
import sys

from . import settings as _settings


def build_computer(ctx):  # pragma: no cover - builds the real Windows backends
    """A Computer wired to the real desktop for one STAR Home activity context."""
    from .agent import Computer, Guard
    from .eye import ScreenEye
    from .hands import Hands
    from .uia import ComtypesUia, UiaUnavailable
    from .winapi import DesktopSink, Windows, ensure_dpi_aware
    ensure_dpi_aware()
    windows = Windows()
    guard = Guard(windows, None)
    cfg = _settings.load(ctx.home)
    try:
        uia = ComtypesUia()
    except UiaUnavailable:
        uia = None
    hands = Hands(DesktopSink(guard), home=ctx.home, dry_run=bool(getattr(ctx.executor, "dry_run", False)),
                  watch_pointer=True)
    return Computer(hands, windows=windows, uia=uia, eye=ScreenEye(), grounder=_settings.make_grounder(cfg),
                    chat=ctx.chat, executor=ctx.executor, guard=guard, settings=cfg, home=ctx.home)


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
    return draw.draw_session(build_computer(ctx), plan, subject, gallery, settings=_settings.load(ctx.home))


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
    result = computer.act(goal, max_steps=int(ctx.config.get("max_steps", 12)),
                          minutes=float(ctx.config.get("session_minutes", 20)))
    result["summary"] = f"{goal[:120]}: {result['summary']}"[:600]
    return result


def register_home_activities(registry) -> None:
    registry.register("draw", "drawing", draw_activity, "paint a sketch in MS Paint and save it to the gallery",
                      needs_brain=True)
    registry.register("use_app", "use_apps", use_app_activity, "use any app with her own mouse and keyboard",
                      needs_brain=True)
