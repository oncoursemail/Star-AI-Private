"""python -m star.computer <command>: try her computer use by hand (on her PC; each command says what it touches).

  see-app APP        open APP (e.g. mspaint.exe), print its controls and how long UI Automation took (--close: then close it)
  draw-test          paint a fixed two-stroke plan in a fresh MS Paint window and save it (--gallery DIR, --plan FILE)
  act "goal"         run act() with the brain from config.json (--dry-run: plan and log, move nothing)
  calibrate          measure a vision endpoint's coordinate convention (settings grounder.url / grounder.model)
  enroll --star-pc   OWNER, ON HER PC ONLY: mark this machine as STAR's (writes <home>/machine.json)
  check-machine      is this STAR's enrolled PC? (exit 0 yes, 4 no)
  skill NAME         run a skill from skills.py with --args '{"url": "https://..."}' (also starts the stop API + hotkey)
  bench FILE         grounding benchmark: FILE is a JSON list of {"image", "query", "rect"} (see ground.bench)
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
    parser.add_argument("command", choices=["see-app", "draw-test", "act", "calibrate", "enroll", "check-machine",
                                            "skill", "bench"])
    parser.add_argument("--star-pc", action="store_true")
    parser.add_argument("--args", default="{}")
    parser.add_argument("arg", nargs="?", default="")
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--gallery", type=Path, default=None)
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--close", action="store_true")
    parser.add_argument("--require-idle", type=float, default=300.0)
    args = parser.parse_args(argv)
    home = args.home or control.home_dir()
    from . import identity
    if args.command == "enroll":
        if not args.star_pc:
            print("enroll marks THIS machine as STAR's own PC. Run it only on her PC, with --star-pc.")
            return 2
        print(f"enrolled: {identity.enroll(home)}")
        return 0
    if args.command == "check-machine":
        ok, why = identity.check(home)
        print("this is STAR's PC" if ok else f"NOT STAR's PC: {why}")
        return 0 if ok else 4
    if args.command == "bench":
        from . import settings
        from .ground import StarVisionGrounder, bench
        cfg = settings.load(home)
        grounders = {"remote-vision": StarVisionGrounder()} if cfg.get("remote_vision") else {}
        local = settings.make_grounder(cfg)
        if local is not None:
            grounders["local-vision"] = local
        if not grounders:
            print("no grounder configured (computer.json grounder.kind=vlm and/or remote_vision=true)")
            return 2
        cases = json.loads(Path(args.arg).read_text(encoding="utf-8"))
        base = Path(args.arg).parent
        for case in cases:
            case["image"] = str(base / case["image"])
        print(json.dumps(bench(cases, grounders), indent=1))
        return 0
    ok, why = identity.check(home)
    if not ok:
        print(f"refusing: {why}")
        return 4
    if args.command == "calibrate":
        if args.dry_run or control.stopped(home):
            print('preview or STOP: no vision calibration request was sent')
            return 3
        from . import settings
        try:
            original = settings.calibration_snapshot(home)
        except FileNotFoundError:
            print('configure grounder.url and model in computer.json first; keep kind=none while calibrating')
            return 2
        grounder = settings.make_grounder(settings.load(home), for_calibration=True)
        if grounder is None:
            print('configure grounder.url and model in computer.json first; kind=none is allowed for calibration')
            return 2
        fmt, errors = grounder.calibrate(cancelled=lambda: control.stopped(home))
        settings.save_calibration(home, original, grounder.calibration, cancelled=lambda: control.stopped(home))
        print(json.dumps({"format": fmt, "mean_error_px": {k: round(v, 1) for k, v in errors.items()},
                          'saved': True, 'validation': grounder.calibration}))
        return 0
    if args.command != "see-app" and idle_seconds() < args.require_idle and not args.dry_run:
        print(f"the owner used the PC {idle_seconds():.0f} s ago (< {args.require_idle:.0f} s): not touching it")
        return 3
    from . import build_computer, build_driver
    ctx = _context(home, args.dry_run)
    if args.command == "skill":
        from .skills import run_skill
        driver = build_driver(ctx, hotkey=True)
        try:
            result = run_skill(driver, args.arg, **json.loads(args.args))
        finally:
            closed = driver.c.close(timeout=.2) is True
        print(json.dumps(result, indent=1))
        return 0 if result["ok"] and closed else 1
    computer = build_computer(ctx)
    try:
        result = _run_desktop_command(args, ctx, computer)
    finally:
        complete = computer.close(timeout=.2) is True
        if not complete:
            print(json.dumps({'verified': False, 'capture_cleanup_complete': False}))
    return result if complete else 1


def _run_desktop_command(args, ctx, computer) -> int:
    from . import draw
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
