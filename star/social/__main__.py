"""`python -m star.social log [--days N] [--limit N]`: the owner-visible social log (what she accepted, asked, sent,
joined, left, forgot and why). `python -m star.social friends`: who she knows and how close."""
from __future__ import annotations

import argparse
import time

from .friends import FriendMemory
from .lifecycle import Bonds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.social")
    sub = parser.add_subparsers(dest="cmd", required=True)
    log = sub.add_parser("log")
    log.add_argument("--days", type=float, default=7.0)
    log.add_argument("--limit", type=int, default=100)
    sub.add_parser("friends")
    args = parser.parse_args(argv)
    memory = FriendMemory()
    try:
        if args.cmd == "log":
            for row in memory.recent_log(args.limit, since=time.time() - args.days * 86400):
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["ts"]))
                print(f"{when}  {row['platform']:9} {row['event']:18} {row['who'] + ': ' if row['who'] else ''}{row['detail']}")
        else:
            bonds = Bonds(memory)
            rows = memory._db.execute("SELECT id FROM people ORDER BY updated DESC").fetchall()
            for (pid,) in rows:
                person = memory.get(pid)
                bond = bonds.get(person)
                print(f"{person.name:24} {bond.stage:13} score {bond.score:5.1f}  chats {bond.convos}  games {bond.shared_games}")
    finally:
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
