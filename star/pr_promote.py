"""Litha promotes star/next to main when the release checks hold (main auto-publishes a release).

The ledger's release checks (STAR_EXECUTION_LEDGER.md, owner OK 2026-10-13) for a star/next -> main merge:
  1. every check on the exact star/next head completed and passed (tests, types, UI, Windows build);
  2. real-window acceptance passed on that head          -> receipt ~/.star/release/<sha>/acceptance.json
  3. the Windows build installed over the installed app after a data backup, acceptance list passed
                                                          -> receipt ~/.star/release/<sha>/install.json
  4. no open high-risk finding: none of the merger's last decisions held a merged PR on a proven high risk;
  5. release notes exist for that head                   -> ~/.star/release/<sha>/notes.md
Receipts are written by the runs that did the work, each {"ok": true, "sha": "<sha>", ...}. A missing or failed one
means no merge: she opens / refreshes the star/next -> main PR and reports exactly what is missing.

    python -m star.pr_promote [--apply]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from star.pr_merger import LOG, OK_CHECKS, REPO, gh, head_checks

RELEASE = Path.home() / ".star" / "release"
RECEIPTS = ("acceptance.json", "install.json")


def head_sha(branch: str = "star/next") -> str:
    return json.loads(gh("api", f"repos/{REPO}/branches/{branch}"))["commit"]["sha"]


def missing(sha: str, checks: list[dict], decisions: list[dict], release: Path = RELEASE) -> list[str]:
    why = []
    if not checks:
        why.append("no checks ran on the star/next head")
    for c in checks:
        if c["status"].lower() != "completed":
            why.append(f"check {c['name']} still {c['status']}")
        elif c["conclusion"] not in OK_CHECKS:
            why.append(f"check {c['name']} {c['conclusion'].lower()}")
    if checks and not any(c["conclusion"] == "SUCCESS" and "windows" in c["name"].lower() for c in checks):
        why.append("no successful Windows build on this head")
    for name in RECEIPTS:
        f = release / sha / name
        try:
            receipt = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            why.append(f"no {name} receipt for {sha[:8]}")
            continue
        if receipt.get("ok") is not True or receipt.get("sha") != sha:
            why.append(f"{name} for {sha[:8]} did not pass")
    if not (release / sha / "notes.md").is_file():
        why.append(f"no release notes for {sha[:8]}")
    risky = [d["pr"] for d in decisions if d.get("merged") is False and d.get("action") == "hold"
             and any(r.get("severity") == "high" for r in ((d.get("review") or {}).get("risks") or []))]
    if risky:
        why.append("open high-risk findings on PRs " + ", ".join(f"#{n}" for n in risky))
    return why


def recent_decisions(n: int = 300) -> list[dict]:
    try:
        rows = [json.loads(ln) for ln in LOG.read_text(encoding="utf-8").splitlines()[-n:] if ln.strip()]
    except OSError:
        return []
    latest: dict[int, dict] = {}
    for r in rows:                                     # the newest decision per PR counts
        if not r.get("replay") and "pr" in r:
            latest[r["pr"]] = {**r, "merged": r.get("merged", False)}
    return list(latest.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m star.pr_promote")
    ap.add_argument("--apply", action="store_true", help="merge star/next into main when every check holds")
    a = ap.parse_args(argv)
    sha = head_sha()
    why = missing(sha, head_checks(sha), recent_decisions())
    prs = json.loads(gh("pr", "list", "--repo", REPO, "--base", "main", "--head", "star/next", "--state", "open",
                        "--json", "number"))
    if prs:
        number = prs[0]["number"]
    else:
        url = gh("pr", "create", "--repo", REPO, "--base", "main", "--head", "star/next", "--title",
                 "star/next -> main (Litha's release promotion)", "--body",
                 "Opened by Litha. Merged only when the release checks in star/pr_promote.py hold for the exact head.")
        number = int(url.strip().rsplit("/", 1)[-1])
    if why:
        print(f"main: HOLD star/next {sha[:8]} (PR #{number}): " + "; ".join(why))
        return 0
    if not a.apply:
        print(f"main: READY star/next {sha[:8]} (PR #{number}); dry run")
        return 0
    gh("pr", "merge", str(number), "--repo", REPO, "--merge", "--match-head-commit", sha)
    print(f"main: MERGED star/next {sha[:8]} via PR #{number}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
