"""python -m star.home <command>

  run [--dry-run]          her loop, forever (the scheduled task runs this, elevated, in her desktop session)
  once [--dry-run]         one cycle now, printed
  status                   stop state, config (no key), interests, open goals, last sessions
  stop | resume            the owner's global stop (resume = remove STOP; STAR's own actions cannot)
  interests                her interest weights
  weight NAME VALUE        set a weight (she does this herself through the brain; this is for the owner too)
  log [--last N]           the last N action-log lines
  check                    dry-run self-test on the PC: executor, stop, log, brain reachability (no actions run)

--dry-run (or "dry_run": true in config.json): actions are logged and not executed; the brain is still asked.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import control
from .activities import default_registry
from .host import Executor
from .life import Life
from .loop import cycle, run_forever


def _setup(dry: bool):
    home = control.home_dir()
    config = control.load_config(home)
    dry = dry or bool(config.get("dry_run"))
    executor = Executor(home, dry_run=dry)
    life = Life(home)
    chat = None
    if config.get("brain_url"):
        from .brain import http_chat
        chat = http_chat(config)
    return home, config, executor, life, chat


def main(argv: list[str] | None = None) -> int:
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
    home, config, executor, life, chat = _setup(args.dry_run or args.command == "check")
    registry = default_registry()
    if args.command == "check":
        result = executor.do("shell", {"command": "Get-Date"})
        print(f"executor (dry run): {result.text}")
        print(f"stopped: {control.stopped(home)}; activities: {sorted(registry.items)}; plug-in errors: "
              f"{registry.plugin_errors or 'none'}")
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
        print(json.dumps(cycle(home, config, registry, life, executor, chat), ensure_ascii=False))
        return 0
    run_forever(home, config, registry, life, executor, chat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
