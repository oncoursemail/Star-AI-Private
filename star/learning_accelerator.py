"""Read-only, evidence-driven curriculum for Star's locally verified practice.

Selects the next *suggested* capability to practice without starting models,
executing tools, promoting lessons, editing evaluations, or making Roblox writes.
Source of truth is the host-owned Brain 2 PracticeLedger, never an LLM claim.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Sequence

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_PROJECT = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
MAX_CYCLES = 1000
MAX_CAPABILITIES = 500
MAX_CASES_PER_CYCLE = 200


@dataclass(frozen=True)
class Capability:
    """Operator-defined opportunity; this is data, never an execution target."""
    name: str
    domain: str = "general"
    value: float = 1.0
    seconds: int = 300

    def __post_init__(self) -> None:
        if (type(self.name) is not str or not 2 <= len(self.name) <= 160
                or any(ord(c) < 32 or ord(c) == 127 for c in self.name)):
            raise ValueError("Invalid capability name")
        if (type(self.domain) is not str or not re.fullmatch(r"[A-Za-z0-9_.-]{1,48}", self.domain)):
            raise ValueError("Invalid capability domain")
        if (type(self.value) not in (int, float) or not math.isfinite(self.value)
                or not 0.1 <= self.value <= 10):
            raise ValueError("Capability value must be between 0.1 and 10")
        if type(self.seconds) is not int or not 30 <= self.seconds <= 7200:
            raise ValueError("Estimated practice seconds must be between 30 and 7200")


@dataclass(frozen=True)
class VerifiedObservation:
    """Outcome read from an independent host-owned, completed test cycle."""
    name: str
    passed: bool
    when: datetime
    revision: str
    cycle_id: int


def read_practice_evidence(
    ledger_path: Path, project: str, *, now: datetime | None = None,
    target: tuple[int, int] | None = None, max_cycles: int = MAX_CYCLES,
) -> tuple[list[VerifiedObservation], dict]:
    """Read only confirmed saved-version runs. Skip incomplete/inconsistent rows.

    A SQLite file alone is not cryptographic proof: the calling host must own
    this ledger and protect it from model writes. An agent cannot supply rows.
    """
    if type(project) is not str or not _PROJECT.fullmatch(project):
        raise ValueError("Project must be an explicit scope identifier")
    if (type(max_cycles) is not int or not 1 <= max_cycles <= MAX_CYCLES
            or target is not None and
            (type(target) is not tuple or len(target) != 2
             or any(type(v) is not int or v < 1 for v in target))):
        raise ValueError("Invalid bounded read scope")
    now = _checked_now(now)
    path = Path(ledger_path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("No completed practice ledger file")
    # SQLite read-only URI: this operation neither creates nor alters a DB.
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        query = (
            "SELECT id,project,universe_id,place_id,start_utc,finish_utc,"
            "status,source_sha256,saved_version,passed,failed,cases_json "
            "FROM practice_cycles WHERE project=? AND status IN ('passed','failed')"
        )
        params: list = [project]
        if target is not None:
            query += " AND universe_id=? AND place_id=?"
            params.extend(target)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max_cycles)
        rows = connection.execute(query, tuple(params)).fetchall()
    finally:
        connection.close()

    observations: list[VerifiedObservation] = []
    seen: set[tuple[str, str, int, int]] = set()
    accepted_cycles = 0
    rejected_cycles = 0
    duplicate_revisions = 0
    for row in rows:  # newest to oldest: one outcome per case per exact artifact
        try:
            start = datetime.fromisoformat(row["start_utc"])
            end = datetime.fromisoformat(row["finish_utc"])
            if (start.tzinfo is None or end.tzinfo is None
                    or start > end or end > now
                    or end.year < 2020
                    or type(row["saved_version"]) is not int
                    or row["saved_version"] < 1
                    or not isinstance(row["source_sha256"], str)
                    or not _DIGEST.fullmatch(row["source_sha256"])
                    or row["status"] not in ("passed", "failed")):
                raise ValueError("Incomplete or inconsistent receipt")
            cases = json.loads(row["cases_json"])
            if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES_PER_CYCLE:
                raise ValueError("Invalid case count")
            named: set[str] = set()
            for case in cases:
                if (not isinstance(case, dict) or set(case) != {"name", "ok"}
                        or type(case.get("ok")) is not bool):
                    raise ValueError("Malformed result item")
                # Names are data only, and cannot become commands or prompts.
                Capability(case["name"])
                if case["name"] in named:
                    raise ValueError("Duplicate case name in one receipt")
                named.add(case["name"])
            failures = sum(not case["ok"] for case in cases)
            if (row["passed"] != len(cases) - failures
                    or row["failed"] != failures
                    or (row["status"] == "passed") != (failures == 0)):
                raise ValueError("Stored outcome disagrees with recorded cases")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            rejected_cycles += 1
            continue
        accepted_cycles += 1
        for case in cases:
            key = (case["name"], row["source_sha256"],
                   row["universe_id"], row["place_id"])
            if key in seen:
                duplicate_revisions += 1
                continue
            seen.add(key)
            observations.append(VerifiedObservation(
                name=case["name"], passed=case["ok"], when=end.astimezone(timezone.utc),
                revision=row["source_sha256"], cycle_id=row["id"]))
    return observations, {
        "confirmed_cycles": accepted_cycles,
        "rejected_cycles": rejected_cycles,
        "duplicate_artifact_cases": duplicate_revisions,
        "distinct_evidence": len(observations),
        "scanned_cycles": len(rows),
        "ledger_read_only": True,
    }


def _checked_now(now: datetime | None) -> datetime:
    current = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("Learning clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def rank_curriculum(
    capabilities: Sequence[Capability], observations: Sequence[VerifiedObservation], *,
    now: datetime | None = None, budget_seconds: int = 1800, limit: int = 8,
) -> dict:
    """Deterministic, cost-aware suggestion; no model, tools, or network calls.

    Ranks verified failure, uncertainty, and spaced revisits; domain diversity
    prevents one class of task from monopolizing a limited compute budget.
    This is an explicit heuristic, NOT a calibrated intelligence score.
    """
    now = _checked_now(now)
    if (type(budget_seconds) is not int or not 30 <= budget_seconds <= 86400
            or type(limit) is not int or not 1 <= limit <= 50
            or len(capabilities) > MAX_CAPABILITIES):
        raise ValueError("Curriculum budget outside safe bounds")
    if any(type(cap) is not Capability for cap in capabilities):
        raise TypeError("Capabilities must be explicitly validated")
    names: set[str] = set()
    for cap in capabilities:
        if cap.name in names:
            raise ValueError("Ambiguous duplicate capability")
        names.add(cap.name)

    by_name: dict[str, list[VerifiedObservation]] = {name: [] for name in names}
    for item in observations:
        if (type(item) is not VerifiedObservation or type(item.passed) is not bool
                or type(item.cycle_id) is not int or item.cycle_id < 1
                or type(item.revision) is not str or not _DIGEST.fullmatch(item.revision)
                or not isinstance(item.when, datetime) or item.when.tzinfo is None
                or item.when.astimezone(timezone.utc) > now):
            raise ValueError("Only host-verified observations with valid metadata can be ranked")
        if item.name in by_name:
            by_name[item.name].append(item)

    candidates: list[dict] = []
    for cap in capabilities:
        rows = sorted(by_name[cap.name], key=lambda x: (x.when, x.cycle_id), reverse=True)
        passed = sum(x.passed for x in rows)
        failed = len(rows) - passed
        last = rows[0] if rows else None
        streak = 0
        for item in rows:
            if not item.passed:
                break
            streak += 1
        # Review successful skills at widening intervals. Failed skills retry
        # only after a short delay, leaving space to change the artifact.
        interval = min(30 * 86400, 6 * 3600 * 2 ** min(max(streak - 1, 0), 7)) if streak else 1800
        since = (now - last.when).total_seconds() if last else None
        due_in = max(0, math.ceil(interval - since)) if since is not None else 0
        if due_in:
            continue

        n = len(rows)
        p_failure = (failed + 1) / (n + 2)  # regularized, never assume zero risk
        uncertainty = 1.0 / math.sqrt(n + 1)
        last_failed = bool(last and not last.passed)
        # Bounded, explainable heuristic. Avoid fake "intelligence" multipliers.
        raw = (
            0.8 * p_failure + 1.2 * uncertainty + (0.45 if last_failed else 0)
            + (0.3 if n else 0.4)
        )
        priority = raw * float(cap.value) / math.sqrt(cap.seconds / 60)
        candidates.append({
            "name": cap.name, "domain": cap.domain, "estimated_seconds": cap.seconds,
            "priority": round(priority, 6), "verified_passes": passed,
            "verified_failures": failed, "revisions_seen": len({x.revision for x in rows}),
            "failure_estimate": round(p_failure, 3),
            "reason": ("untried" if not rows else
                       "recent_verified_failure" if last_failed else "spaced_recheck"),
        })

    chosen: list[dict] = []
    domain_counts: dict[str, int] = {}
    remaining = budget_seconds
    while candidates and len(chosen) < limit:
        affordable = [c for c in candidates if c["estimated_seconds"] <= remaining]
        if not affordable:
            break
        pick = max(affordable, key=lambda c: (
            c["priority"] * (0.7 ** domain_counts.get(c["domain"], 0)),
            -c["estimated_seconds"], c["name"]))
        candidates.remove(pick)
        domain_counts[pick["domain"]] = domain_counts.get(pick["domain"], 0) + 1
        chosen.append(pick)
        remaining -= pick["estimated_seconds"]

    return {
        "suggestions": chosen, "eligible": len(candidates) + len(chosen),
        "not_yet_due": len(capabilities) - len(candidates) - len(chosen),
        "budget_seconds": budget_seconds, "budget_used_seconds": budget_seconds - remaining,
        "no_execution": True, "no_training": True, "requires_operator_orchestrator": True,
        "interpretation": "Relative practice priorities, not a model intelligence metric.",
    }


def recommend_from_ledger(
    ledger_path: Path, project: str, *, catalog: Sequence[Capability] = (),
    target: tuple[int, int] | None = None, now: datetime | None = None,
    budget_seconds: int = 1800, limit: int = 8,
) -> dict:
    """Join independently recorded tested cases to optional operator-defined gaps."""
    observations, evidence = read_practice_evidence(
        ledger_path, project, now=now, target=target)
    known = {c.name: c for c in catalog}
    for item in observations:
        if item.name not in known:
            known[item.name] = Capability(item.name, domain="roblox", seconds=300)
    result = rank_curriculum(list(known.values()), observations,
                             now=now, budget_seconds=budget_seconds, limit=limit)
    return {"project": project, "target": list(target) if target else None,
            "evidence": evidence, **result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only verified practice curriculum")
    parser.add_argument("--ledger", type=Path, required=True,
                        help="Existing host-owned private practice SQLite ledger")
    parser.add_argument("--project", required=True)
    parser.add_argument("--catalog", type=Path,
                        help="Optional operator-curated JSON array of capability objects")
    parser.add_argument("--universe-id", type=int)
    parser.add_argument("--place-id", type=int)
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args(argv)
    try:
        if (args.universe_id is None) != (args.place_id is None):
            raise ValueError("Both target identifiers are required together")
        target = ((args.universe_id, args.place_id)
                  if args.universe_id is not None else None)
        catalog = ()
        if args.catalog:
            raw = json.loads(args.catalog.read_text(encoding="utf-8"))
            if not isinstance(raw, list) or len(raw) > MAX_CAPABILITIES:
                raise ValueError("Capability catalog must be a bounded JSON array")
            catalog = tuple(Capability(**item) for item in raw)
        result = recommend_from_ledger(
            args.ledger, args.project, catalog=catalog, target=target,
            budget_seconds=args.minutes * 60, limit=args.top)
    except (ValueError, TypeError, OSError, sqlite3.DatabaseError) as exc:
        print(json.dumps({"status": "refused", "reason": type(exc).__name__,
                          "notice": "Check the local private ledger and operator catalog."}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
