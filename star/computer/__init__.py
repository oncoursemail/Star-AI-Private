"""STAR uses any app on her own PC with her own mouse and keyboard (owner, 2026-10-26).

screen.py     Element / Screen: what is on screen, how to find a control, whether two looks differ
uia.py        Windows UI Automation (comtypes): exact control names, roles and rectangles in ~150-280 ms
grounding.py  vision grounding behind one interface (UI-TARS, Qwen3-VL, ShowUI ... through any OpenAI-style endpoint)
hands.py      human-like mouse and keyboard on star/play/humanlike.py, the owner's STOP, a log line per action
agent.py      Computer.see() and Computer.act(goal): observe, plan, act, verify, recover
draw.py       the "draw" activity: stroke plan from the model, painted in MS Paint, saved and checked
risk.py       money, public posts and accounts go to the owner; no typing into password fields
driver.py     one Step at a time: observe (screenshot + UIA + windows) -> ground -> act -> verify -> retry/replan
ground.py     grounding chain: UIA, then her GPU grounder, then STAR's remote vision (star.vision.ask)
skills.py     macros: open/focus app, browser, Discord DM/reply, Roblox join/leave, settings switches, installers
gates.py      gated (money, accounts, passwords, mass messaging) and never (CAPTCHAs, cheat tools)
limits.py     action pace and messaging limits
identity.py   runs only on the PC the owner enrolled as STAR's (machine.json); refuses anywhere else
stopswitch.py the owner's global stop: STOP file, Ctrl+Alt+Shift+F12, HTTP API with the owner's token
actionlog.py  per-step log with before/after screenshots in <home>/computer-log
Research: docs/research/computer-use-20261026.md. Notes: docs/agents/computer-use-20261026.md.
Plug-in for STAR Home: `register_home_activities(registry)` adds "draw" (interest drawing) and "use_app"
(interest use_apps; the interest needs a seed in star/home/life.py or STAR adds it herself with set_interest).
"""
from __future__ import annotations

from pathlib import Path
import sys

from . import settings as _settings


def build_computer(ctx):  # pragma: no cover - builds the real Windows backends
    """A Computer wired to the real desktop for one STAR Home activity context. Raises identity.WrongMachine on any PC
    other than the one the owner enrolled as STAR's."""
    from . import identity
    identity.require(ctx.home)
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


def build_driver(ctx, *, hotkey: bool = False):  # pragma: no cover - the real desktop
    """The Driver (and its Computer, sharing the grounding chain, log and limits) for one context. `hotkey` = also
    register Ctrl+Alt+Shift+F12 (the STAR Home loop already does; the CLI does not)."""
    from .actionlog import ActionLog
    from .driver import Driver
    from .ground import default_chain
    from .limits import RateLimits
    from .stopswitch import StopSwitch, start_owner_controls
    computer = build_computer(ctx)
    cfg = computer.cfg
    switch = StopSwitch(ctx.home)
    start_owner_controls(switch, cfg, hotkey=hotkey)
    driver = Driver(computer, home=ctx.home, chain=default_chain(cfg, local=computer.grounder), switch=switch,
                    limits=RateLimits(cfg.get("limits")),
                    log=ActionLog(ctx.home, keep_days=int(cfg.get("log_keep_days", 7)),
                                  screenshots=bool(cfg.get("log_screenshots", True))))
    computer.chain, computer.actionlog, computer.limits = driver.chain, driver.log, driver.limits
    return driver


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
    from .identity import WrongMachine
    try:
        computer = build_computer(ctx)
    except WrongMachine as why:
        return {"ok": False, "verified": False, "summary": f"not STAR's PC: {why}", "evidence": [],
                "failures": ["draw: wrong machine"]}
    return draw.draw_session(computer, plan, subject, gallery, settings=_settings.load(ctx.home))


def use_app_activity(ctx) -> dict:  # pragma: no cover - needs her desktop
    if sys.platform != "win32":
        return {"ok": False, "verified": False, "summary": "using apps needs Windows", "evidence": [],
                "failures": ["use_app: not Windows"]}
    goal = (ctx.goal or {}).get("text") or ctx.practice_topic or _ask(
        ctx.chat, "You are STAR on your own PC. Reply with ONE small task to do in an app on this computer (open an "
        "app and do something you can check on screen), at most 25 words, nothing else.",
        "Pick something you have not done lately: a calculation, a note, a setting in one of your own apps, a music "
        "player, a browser search. Nothing that spends money, posts publicly or creates an account.", 200)
    from .identity import WrongMachine
    try:
        computer = build_driver(ctx).c
    except WrongMachine as why:
        return {"ok": False, "verified": False, "summary": f"not STAR's PC: {why}", "evidence": [],
                "failures": ["use_app: wrong machine"]}
    result = computer.act(goal, max_steps=int(ctx.config.get("max_steps", 12)),
                          minutes=float(ctx.config.get("session_minutes", 20)))
    result["summary"] = f"{goal[:120]}: {result['summary']}"[:600]
    return result


def register_home_activities(registry) -> None:
    registry.register("draw", "drawing", draw_activity, "paint a sketch in MS Paint and save it to the gallery",
                      needs_brain=True)
    registry.register("use_app", "use_apps", use_app_activity, "use any app with her own mouse and keyboard",
                      needs_brain=True)
