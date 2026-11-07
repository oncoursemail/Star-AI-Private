"""Read-only command-line gate for STAR's procedural building-plan JSON.

Usage:
  python -m star.scene_quality_cli building-plan.json
  python -m star.scene_quality_cli building-plan.json --repair-proposal repaired.json

A repair is a new, offline *proposal*. This tool never touches Roblox Studio,
uploads assets, changes a source plan or asserts visual quality.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .architecture_quality import audit_plan
from .scene_integrity import propose_shell_repair

_MAX_PLAN_BYTES = 6 * 1024 * 1024


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight a STAR procedural building scene")
    parser.add_argument("plan", type=Path, help="Existing building-plan JSON")
    parser.add_argument("--repair-proposal", type=Path,
                        help="Write a NEW corrected plan, without modifying the original")
    args = parser.parse_args(argv)
    try:
        path = args.plan
        if (path.is_symlink() or not path.is_file() or
                not 0 < path.stat().st_size <= _MAX_PLAN_BYTES):
            raise ValueError("Plan must be an ordinary JSON file no larger than 6 MB")
        plan = json.loads(path.read_text(encoding="utf-8"))
        before = audit_plan(plan)
        response = {"status": before["status"], "audit": before,
                    "plan_unchanged": True, "studio_changed": False}
        if args.repair_proposal is not None:
            output = args.repair_proposal
            if output.exists() or output.is_symlink():
                raise FileExistsError("Repair output exists; use a new destination")
            proposal = propose_shell_repair(plan)
            response["proposal"] = {
                "status": proposal["status"],
                "changes": proposal["changes"],
                "audit": proposal["proposed_audit"],
            }
            if not proposal["proposed_audit"]["valid"] or not proposal["changes"]:
                response["proposal_not_written"] = "No safe, necessary, passing repair"
            else:
                # Exclusive creation prevents silent overwrite during concurrent agent work.
                content = json.dumps(proposal["proposed_plan"], indent=2, allow_nan=False) + "\n"
                with output.open("x", encoding="utf-8") as stream:
                    stream.write(content)
                response["proposal_file"] = str(output)
        print(json.dumps(response, indent=2, allow_nan=False))
        return 0 if before["valid"] else (0 if response.get("proposal_file") else 2)
    except (ValueError, TypeError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
