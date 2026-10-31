"""python -m star.home <command>

  run [--dry-run]          her loop, forever (the scheduled task runs this, elevated, in her desktop session)
  once [--dry-run]         one cycle now, printed
  status                   stop state, config (no key), interests, open goals, last sessions
  stop | resume            the owner's global stop (resume = remove STOP; STAR's own actions cannot)
  interests                her interest weights
  weight NAME VALUE        set a weight (she does this herself through the brain; this is for the owner too)
  log [--last N]           the last N action-log lines
  check                    dry-run self-test on the PC: executor, stop, log, brain reachability (no actions run)
  acceptance [--quick|--dry-run] [--scenario dm-call] [checks...]
                           prove every ability on this PC and write a report (see star/home/acceptance.py)

--dry-run (or "dry_run": true in config.json): actions are logged and not executed; the brain is still asked.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from ..discord_bot.instance_lock import InstanceLock
from . import control
from . import runtime as home_runtime
from .host import Executor
from .life import Life
from .loop import cycle, run_forever

_LEASE_NAME = "home-runtime.lock"
# Background watchers have no shutdown contract yet. Keep their lease until the process ends.
_PROCESS_LEASES: list[InstanceLock] = []


def _message(text: str) -> None:
    try:
        print(text, file=sys.stderr)
    except (OSError, ValueError):
        pass


def _finish_runtime(rt) -> None:
    """Never release ownership while trusted cleanup is pending, failed or unknown."""
    delay, announced, retry = 0.1, False, True
    while True:
        try:
            if retry:
                shutdown = getattr(rt, "shutdown", None)
                shutdown() if callable(shutdown) else rt.stop()
            status = rt.stop_status()
            if not isinstance(status, dict) or not isinstance(status.get("pending"), list) or not isinstance(status.get("errors"), dict):
                raise RuntimeError("cleanup status unavailable")
            if not status["pending"] and not status["errors"]:
                return
            retry = bool(status["errors"])
        except (Exception, KeyboardInterrupt):
            retry = True
        try:
            if not announced:
                _message("Home is waiting for its active work to stop. This folder stays reserved until cleanup finishes.")
                announced = True
            time.sleep(delay)
        except KeyboardInterrupt:
            retry = True
        delay = min(2.0, delay * 2)


def _setup(dry: bool, *, home=None):
    home = control.home_dir() if home is None else home
    config = control.load_config(home)
    dry = dry or bool(config.get("dry_run"))
    executor = Executor(home, dry_run=dry)
    from ..inner.mind import wrap_life
    life = wrap_life(Life(home), home)      # her day planner + memory stream (star/inner/mind.py; off = plain Life)
    chat = None
    if config.get("brain_url"):
        from .brain import http_chat
        chat = http_chat(config)
    return home, config, executor, life, chat


def _execute(args, *, home, lease=None) -> int:
    rt = None
    retain = False
    try:
        home, config, executor, life, chat = _setup(args.dry_run or args.command == "check", home=home)
        retain = lease is not None  # A failed build may have constructed resources before it returns the Runtime.
        registry, rt = home_runtime.build(home, config, executor, life, chat)
        retain = False
        if args.command == "check":
            result = executor.do("shell", {"command": "Get-Date"})
            print(f"executor (dry run): {result.text}")
            print(f"stopped: {control.stopped(home)}; activities: {sorted(registry.items)}; handlers: "
                  f"{sorted(registry.handlers)}; plug-in errors: {registry.plugin_errors or 'none'}")
            from . import voicestack
            print(f"voice stack: {voicestack.build_status()}")
            if chat is None:
                print("brain: brain_url not set in config.json")
                return 1
            try:
                reply = chat([{"role": "user", "content": "Reply with the word ready."}], [])
                print(f"brain: reachable ({str(reply.get('content', ''))[:40]!r})")
            except Exception as why:
                print(f"brain: NOT reachable ({type(why).__name__})")
                return 1
            return 0
        if args.command == "once":
            print(json.dumps(cycle(home, config, registry, life, executor, chat, attention=rt.attention), ensure_ascii=False))
            return 0
        retain = True
        run_forever(home, config, registry, life, executor, chat, attention=rt.attention, background=rt.background())
        return 0
    except KeyboardInterrupt:
        if lease is None:
            raise
        _message("Home was interrupted; stopping active work before ending this run.")
        return 130
    except Exception as error:
        if lease is None:
            raise
        _message(f"Home could not finish ({type(error).__name__}). Active work is being stopped.")
        return 1
    finally:
        if lease is not None:
            _PROCESS_LEASES.append(lease)
            if rt is not None:
                _finish_runtime(rt)
            if not retain:
                lease.release()
                _PROCESS_LEASES.remove(lease)


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    if args_list[:1] == ["configure"]:
        from .onboarding import cli
        return cli(args_list[1:])
    if (sys.argv[1:] if argv is None else argv)[:1] == ["acceptance"]:
        from .acceptance import cli
        return cli((sys.argv[1:] if argv is None else argv)[1:])
    parser = argparse.ArgumentParser(prog="python -m star.home")
    parser.add_argument("command", choices=["run", "once", "status", "stop", "resume", "interests", "weight", "log",
                                            "check"])
    parser.add_argument("rest", nargs="*")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--last", type=int, default=20)
    args = parser.parse_args(argv)
    home = control.home_dir()
    if args.command == "stop":
        print(f"STOP created: {control.stop(home)}")
        return 0
    if args.command == "resume":
        print("resumed" if control.resume(home) else "was not stopped")
        return 0
    if args.command == "log":
        for row in control.read_log(home, args.last):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.command == "interests":
        print(json.dumps(Life(home).interests(), indent=1))
        return 0
    if args.command == "weight":
        if len(args.rest) != 2:
            parser.error("weight NAME VALUE")
        print(json.dumps(Life(home).set_interest(args.rest[0], float(args.rest[1]))))
        return 0
    if args.command == "status":
        life = Life(home)
        config = control.load_config(home)
        print(json.dumps({"home": str(home), "stopped": control.stopped(home), "config": config,
                          "interests": life.interests(), "open_goals": life.goals(),
                          "last_sessions": life.history(5)}, indent=1, ensure_ascii=False))
        return 0
    if args.command == "check":
        return _execute(args, home=home)
    home = home.resolve()
    lease = InstanceLock(home, name=_LEASE_NAME)
    try:
        acquired = lease.acquire()
    except OSError:
        _message("Home could not reserve this data folder. Check its permissions and try again.")
        return 2
    if not acquired:
        _message("Home is already running for this data folder. STOP, resume and status are still available.")
        return 2
    return _execute(args, home=home, lease=lease)


if __name__ == "__main__":
    sys.exit(main())
