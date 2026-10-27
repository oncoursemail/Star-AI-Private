"""python -m star.computer <command>: try her computer use by hand (on her PC; each command says what it touches).

  see-app APP        open APP (e.g. mspaint.exe), print its controls and how long UI Automation took (--close: then close it)
  draw-test          paint a fixed two-stroke plan in a fresh MS Paint window and save it (--gallery DIR, --plan FILE)
  act "goal"         run act() with the brain from config.json (--dry-run: plan and log, move nothing)
  calibrate          measure a vision endpoint's coordinate convention (settings grounder.url / grounder.model)
Options: --home DIR (default STAR_HOME_DIR or ProgramData), --require-idle SECONDS (default 300 for draw-test: refuse
to run while the owner used the keyboard or mouse that recently).
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
from pathlib import Path
import sys
import time

DEMO_PLAN = {"title": "demo house", "strokes": [
    {"color": "Black", "points": [[15, 90], [15, 45], [50, 12], [85, 45], [85, 90], [15, 90]]},
    {"color": "Red", "points": [[40, 90], [40, 62], [60, 62], [60, 90]]}]}


def idle_seconds() -> float:  # pragma: no cover - Windows only
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))  # pyright: ignore[reportAttributeAccessIssue]
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0  # pyright: ignore[reportAttributeAccessIssue]


def _context(home: Path, dry: bool):  # pragma: no cover - real backends
    from ..home import control
    from ..home.activities import Context
    from ..home.brain import http_chat
    from ..home.host import Executor
    from ..home.life import Life
    config = control.load_config(home)
    chat = http_chat(config) if config.get("brain_url") else None
    return Context(home=home, config=config, executor=Executor(home, dry_run=dry), life=Life(home), chat=chat,
                   interest="drawing", goal=None)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - drives the real desktop
    from ..home import control
    parser = argparse.ArgumentParser(prog="python -m star.computer", description=(__doc__ or "").split("\n")[0])
    parser.add_argument("command", choices=["see-app", "draw-test", "act", "calibrate"])
    parser.add_argument("arg", nargs="?", default="")
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--gallery", type=Path, default=None)
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--close", action="store_true")
    parser.add_argument("--require-idle", type=float, default=300.0)
    args = parser.parse_args(argv)
    home = args.home or control.home_dir()
    if args.command == "calibrate":
        from . import settings
        grounder = settings.make_grounder(settings.load(home))
        if grounder is None:
            print("set grounder.kind=vlm, url and model in computer.json first")
            return 2
        fmt, errors = grounder.calibrate()
        print(json.dumps({"format": fmt, "mean_error_px": {k: round(v, 1) for k, v in errors.items()}}))
        return 0
    if args.command != "see-app" and idle_seconds() < args.require_idle and not args.dry_run:
        print(f"the owner used the PC {idle_seconds():.0f} s ago (< {args.require_idle:.0f} s): not touching it")
        return 3
    from . import build_computer, draw
    ctx = _context(home, args.dry_run)
    computer = build_computer(ctx)
    if args.command == "see-app":
        info, message = computer.open_app(args.arg or "mspaint.exe")
        print(message)
        for i in range(3):
            started = time.perf_counter()
            screen = computer.see()
            print(f"see() #{i + 1}: {len(screen.elements)} elements in {(time.perf_counter() - started) * 1000:.0f} ms")
        print(screen.prompt(80))
        if info and args.close:
            ctypes.windll.user32.PostMessageW(info.hwnd, 0x10, 0, 0)           # WM_CLOSE: asks the window to close  # pyright: ignore[reportAttributeAccessIssue]
        return 0 if info else 1
    if args.command == "draw-test":
        data = json.loads(args.plan.read_text(encoding="utf-8")) if args.plan else DEMO_PLAN
        plan = draw.validate_plan(data)
        if isinstance(plan, str):
            print("bad plan:", plan)
            return 2
        gallery = args.gallery or (Path(ctx.executor.workspace) / "gallery")
        started = time.perf_counter()
        result = draw.draw_session(computer, plan, plan.title, gallery)
        print(json.dumps({k: result[k] for k in ("ok", "verified", "summary", "evidence", "failures")}, indent=1))
        print(f"{time.perf_counter() - started:.1f} s")
        return 0 if result["verified"] else 1
    if ctx.chat is None:
        print("no brain_url in config.json")
        return 2
    result = computer.act(args.arg or "open Calculator and compute 17 times 23", max_steps=int(ctx.config["max_steps"]))
    print(json.dumps({k: result[k] for k in ("ok", "verified", "summary", "steps", "failures")}, indent=1))
    return 0 if result["verified"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
