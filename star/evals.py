"""Evaluation case catalog and audit report (definitions are not executed by this module)."""
from dataclasses import dataclass
import json
from pathlib import Path

VALID_VERDICTS = {"not_run", "passed", "failed", "blocked"}


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    goal: str
    required_evidence: tuple[str, ...]
    pass_conditions: tuple[str, ...]
    run_mode: str


def load_catalog(path: Path) -> list[Case]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Evaluation catalog must be an array")
    cases = []
    ids: set[str] = set()
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] in ids:
            raise ValueError("Evaluation case needs a unique ID")
        if row.get("run_mode") not in {"automated", "studio", "human"}:
            raise ValueError("Unknown evaluation run mode")
        for field in ("category", "goal", "required_evidence", "pass_conditions"):
            if not row.get(field):
                raise ValueError("Missing evaluation specification: " + field)
        if any(not isinstance(x, str) or not x for x in row["required_evidence"] + row["pass_conditions"]):
            raise ValueError("Evidence / conditions must be nonempty strings")
        cases.append(Case(row["id"], row["category"], row["goal"],
                          tuple(row["required_evidence"]), tuple(row["pass_conditions"]),
                          row["run_mode"]))
        ids.add(row["id"])
    return cases


def summarize_verdicts(cases: list[Case], verdicts: dict[str, str]) -> dict:
    unknown = set(verdicts) - {c.id for c in cases}
    if unknown or set(verdicts.values()) - VALID_VERDICTS:
        raise ValueError("Unknown evaluation ID or verdict")
    totals = {v: 0 for v in sorted(VALID_VERDICTS)}
    for case in cases:
        totals[verdicts.get(case.id, "not_run")] += 1
    executed = totals["passed"] + totals["failed"]
    return {
        "total": len(cases), "counts": totals,
        "pass_rate_executed": round(totals["passed"] / executed, 4) if executed else None,
        "note": "Catalog verdicts are externally supplied; this module does NOT run Roblox tests or validate proof."
    }


def main(argv=None) -> int:
    """`python -m star.evals run|selftest|list|gate|innovation|ledger ...` (star/eval_runner.py, star/eval_gate.py,
    star/innovation_gate.py); `--suite human` goes to star/human_evals.py."""
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    from .human_evals import main as human_main, wants_human
    if wants_human(args):                          # --suite human: the human-likeness suite (star/human_evals.py)
        return human_main(args)
    if args and args[0] == "pool":                 # python -m star.evals pool <grade|replay|inspect> ... (star/pool_replay.py)
        from .pool_replay import main as pool_main
        return pool_main(args[1:])
    if args and args[0] == "run":                  # --pool DIR [--pool-tag NAME]: save every candidate (star/candidate_pool.py)
        from .candidate_pool import take_flags
        args = take_flags(args)
    if args and args[0] == "ledger":
        from .failure_ledger import main as ledger_main
        return ledger_main(args[1:])
    if args and args[0] == "gate":
        from .eval_gate import main as gate_main
        return gate_main(args[1:])
    if args and args[0] == "innovation":
        from .innovation_gate import main as innovation_main
        return innovation_main(args[1:])
    from .breadth_evals import main as breadth_main, wants_breadth
    if wants_breadth(args):                        # GDScript and instruction-following suites (star/breadth_evals.py)
        return breadth_main(args)
    from .eval_runner import main as run_main
    return run_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
