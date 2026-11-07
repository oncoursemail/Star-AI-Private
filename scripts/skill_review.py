"""Owner-invoked preview/import/verify for text-only Agent Skills.

Use from the repository root:
  python -m scripts.skill_review preview --source ... --source-url ... --commit ... --license MIT
  python -m scripts.skill_review import --source ... --source-url ... --commit ... --license MIT --home ... --approve
  python -m scripts.skill_review verify --home ... --name ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from star.skill_import import import_reviewed_skill, preview_skill, verify_skill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STAR reviewed Agent Skill importer (no download or script execution)")
    commands = parser.add_subparsers(dest="action", required=True)
    for operation in ("preview", "import"):
        sub = commands.add_parser(operation)
        sub.add_argument("--source", type=Path, required=True, help="Locally reviewed SKILL.md directory")
        sub.add_argument("--source-url", required=True, help="Repository HTTPS origin (metadata only)")
        sub.add_argument("--commit", required=True, help="Reviewed full 40-character commit SHA")
        sub.add_argument("--license", dest="license_id", required=True, help="Reviewed SPDX license")
        if operation == "import":
            sub.add_argument("--home", type=Path, required=True, help="STAR user-data directory")
            sub.add_argument("--approve", action="store_true", help="Explicitly approve import of the shown snapshot")
    verify = commands.add_parser("verify")
    verify.add_argument("--home", type=Path, required=True)
    verify.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "verify":
            result = verify_skill(args.home, args.name)
        else:
            info = {"source_url": args.source_url, "commit": args.commit, "license_id": args.license_id}
            if args.action == "preview":
                result = preview_skill(args.source, **info)
            else:
                result = import_reviewed_skill(args.source, home=args.home, approved=args.approve, **info)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok", True) else 1
    except (OSError, ValueError, PermissionError, FileExistsError) as exc:
        print(f"STAR skill review rejected: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
