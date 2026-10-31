r"""Write a release receipt for star.pr_promote: run a check command on this checkout, record whether it passed.

    python -m star.release_receipt acceptance -- python scripts/shell_acceptance.py
    python -m star.release_receipt install -- cmd /c scripts\windows_acceptance.cmd
The receipt lands in ~/.star/release/<HEAD sha>/<name>.json as {"ok", "sha", "command", "exit", "tail", "at"}.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys

from star.pr_promote import RELEASE


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 3 or argv[0] not in ("acceptance", "install") or argv[1] != "--":
        print("usage: python -m star.release_receipt acceptance|install -- <command...>")
        return 2
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    run = subprocess.run(argv[2:], capture_output=True, text=True, encoding="utf-8", errors="replace")
    receipt = {"ok": run.returncode == 0, "sha": sha, "command": argv[2:], "exit": run.returncode,
               "tail": (run.stdout + run.stderr)[-2000:], "at": dt.datetime.now(dt.timezone.utc).isoformat()}
    out = RELEASE / sha / f"{argv[0]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print(f"{argv[0]} {'passed' if receipt['ok'] else 'FAILED'} on {sha[:8]} -> {out}")
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
