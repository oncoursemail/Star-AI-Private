"""Usage: python -m star.commerce path/to/offer.json (offline, no credentials).

Owner approvals for real-world actions STAR has drafted:
  python -m star.commerce approvals list
  python -m star.commerce approvals approve|reject|run ID --yes
`--yes` is the owner's confirmation; without it nothing is decided or run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .planning import inspect_offer

_MAX_BYTES = 256 * 1024


def approvals_main(argv: list[str]) -> int:
    from ..desktop_core import Settings, app_data
    from .approvals import handle_approvals, list_approvals
    from .workspace import commerce_connection
    parser = argparse.ArgumentParser(prog="python -m star.commerce approvals")
    parser.add_argument("command", choices=("list", "approve", "reject", "run"))
    parser.add_argument("id", nargs="?", default="")
    parser.add_argument("--yes", action="store_true", help="the owner's confirmation")
    parser.add_argument("--home", default="", help="STAR app-data folder (default: the installed app's)")
    args = parser.parse_args(argv)
    home = Path(args.home) if args.home else app_data()
    try:
        settings = Settings.load(home / "settings.json")
        if settings.commerce_enabled is not True:
            raise PermissionError("Business tools are off. Turn them on in STAR Settings > Tools.")
        with commerce_connection(home) as conn, conn:
            if args.command != "list":
                if not args.id:
                    raise ValueError("Give the proposed action's id")
                action = {"run": "commerceApprovalExecute"}.get(args.command, "commerceApprovalDecide")
                body = {"id": args.id, "decision": args.command, "owner_confirmed": args.yes}
                if action == "commerceApprovalExecute":
                    body = {"id": args.id}
                    if not args.yes:
                        raise PermissionError("Add --yes to confirm")
                handle_approvals(conn, settings.project, action, body)
            rows = list_approvals(conn, settings.project)
    except (OSError, ValueError, PermissionError) as exc:
        print(f"STAR approvals: {exc}", file=sys.stderr)
        return 2
    for row in rows:
        money = f" ${row['amount_cents'] / 100:.2f}" if row["amount_cents"] is not None else ""
        print(f"{row['id']}  {row['status']:<9} {row['kind_label']}{money}: {row['title']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if (argv if argv is not None else sys.argv[1:])[:1] == ["approvals"]:
        return approvals_main((argv if argv is not None else sys.argv[1:])[1:])
    parser = argparse.ArgumentParser(description="Inspect an Etsy or Fiverr offer without contacting a marketplace.")
    parser.add_argument("brief", help="A local JSON offer brief, not an API key or exported customer data.")
    args = parser.parse_args(argv)
    try:
        path = Path(args.brief)
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            raise ValueError("Offer JSON file must exist and be no larger than 256 KiB")
        data = json.loads(path.read_text(encoding="utf-8"))
        result = inspect_offer(data)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(f"STAR commerce planning failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
