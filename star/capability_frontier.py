"""Capability Frontier: propose affordable, authorized *experiments* for STAR.

A metacognitive planner, NOT an autonomous execution/permission tool. It takes
reported defects and an independently registered tool catalog, explores bounded
combinations, identifies knowledge gaps and returns reproducible experiment
hypotheses. Caller MUST separately enforce policies and authenticate evidence.
No tool invocation, network access, model calls, installation or self-editing.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import re
from typing import Any

MAX_TOOLS = 16
MAX_FINDINGS = 100
MAX_STEPS = 4
MAX_RECIPE_COST_MS = 3_600_000
VALID_SCOPES = frozenset({"read_project", "sandbox_test", "studio_edit", "render", "network_research"})
VALID_ROLES = frozenset({"observe", "repair", "verify", "research"})
VALID_EVIDENCE = frozenset({"studio_log", "studio_playtest", "screen_capture", "human_review",
                            "static_check", "provenance_check", "performance_trace"})
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}\Z")
WEIGHTS = {"error": 5, "unverified": 3, "review": 1}


def _name(v: Any, what: str) -> str:
    if not isinstance(v, str) or not _NAME.fullmatch(v):
        raise ValueError(f"{what} must be an explicit, short identifier")
    return v


def _strings(v: Any, what: str, cap: int) -> tuple[str, ...]:
    if not isinstance(v, list) or len(v) > cap:
        raise ValueError(f"{what} must be a bounded list")
    names = tuple(_name(x, what) for x in v)
    if len(set(names)) != len(names):
        raise ValueError(f"{what} contains duplicates")
    return names


def _count(v: Any, what: str, limit: int, *, minimum: int = 0) -> int:
    if type(v) is not int or not minimum <= v <= limit:
        raise ValueError(f"{what} must be an integer in {minimum}..{limit}")
    return v


@dataclass(frozen=True)
class Technique:
    ident: str
    addresses: tuple[str, ...]
    requires: tuple[str, ...]
    role: str
    scope: str
    evidence: str
    cost_ms: int
    peak_memory_mb: int

    @classmethod
    def from_record(cls, item: Any) -> "Technique":
        if not isinstance(item, dict):
            raise ValueError("technique must be an object")
        allowed_keys = {"id", "addresses", "requires", "role", "scope", "evidence", "cost_ms", "peak_memory_mb"}
        if set(item) != allowed_keys:
            raise ValueError("technique requires exact, versioned schema keys")
        t = cls(
            ident=_name(item["id"], "technique.id"),
            addresses=_strings(item["addresses"], "technique.addresses", MAX_FINDINGS),
            requires=_strings(item["requires"], "technique.requires", MAX_TOOLS),
            role=str(item["role"]), scope=str(item["scope"]), evidence=str(item["evidence"]),
            cost_ms=_count(item["cost_ms"], "cost_ms", MAX_RECIPE_COST_MS, minimum=1),
            peak_memory_mb=_count(item["peak_memory_mb"], "peak_memory_mb", 131_072, minimum=1),
        )
        if not t.addresses or t.role not in VALID_ROLES or t.scope not in VALID_SCOPES or t.evidence not in VALID_EVIDENCE:
            raise ValueError("technique has unknown capability, role, scope or evidence")
        if t.ident in t.requires:
            raise ValueError("a technique cannot require itself")
        return t


def _findings(report: Any) -> list[tuple[str, str, int]]:
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    rows = report.get("findings")
    if not isinstance(rows, list) or len(rows) > MAX_FINDINGS:
        raise ValueError("report findings missing or oversized")
    out: list[tuple[str, str, int]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("severity") not in WEIGHTS:
            raise ValueError("invalid finding severity")
        code = _name(row.get("code"), "finding.code")
        target = row.get("target")
        if not isinstance(target, str) or not 1 <= len(target) <= 200 or any(ord(c) < 32 for c in target):
            raise ValueError("finding target must be short, printable text")
        out.append((code, target, WEIGHTS[row["severity"]]))
    return out


def _order(ids: tuple[str, ...], catalog: dict[str, Technique]) -> tuple[str, ...]:
    """Stable topological sort of the selected dependency-closed set."""
    remaining = set(ids)
    ordered: list[str] = []
    while remaining:
        ready = sorted(item for item in remaining if set(catalog[item].requires) <= set(ordered))
        if not ready:
            raise ValueError("technique dependency cycle")
        ordered.extend(ready)
        remaining.difference_update(ready)
    return tuple(ordered)


def plan_frontier(
    report: dict[str, Any],
    registered_techniques: list[dict[str, Any]],
    *,
    allowed_scopes: tuple[str, ...] = ("read_project",),
    wall_time_ms: int = 60_000,
    peak_memory_mb: int = 4096,
    max_steps: int = 3,
) -> dict[str, Any]:
    """Search small multistep strategies and expose unmet capabilities.

    The caller must obtain the catalog + allowed scopes from trusted code, not
    accept either from a model reply. If allowed scopes are spoofed, this pure
    function STILL does not grant or exercise any capability.
    """
    problems = _findings(report)
    if not isinstance(registered_techniques, list) or len(registered_techniques) > MAX_TOOLS:
        raise ValueError("registered tool catalog too large")
    catalog_items = [Technique.from_record(item) for item in registered_techniques]
    catalog = {t.ident: t for t in catalog_items}
    if len(catalog) != len(catalog_items):
        raise ValueError("duplicate technique IDs")
    for t in catalog_items:
        if set(t.requires) - set(catalog):
            raise ValueError("unknown technique dependency")
    # Full graph cycle detection even if dependency depth exceeds the plan limit.
    def visit(ident: str, visiting: set[str], visited: set[str]) -> None:
        if ident in visiting:
            raise ValueError("dependency cycle")
        if ident in visited:
            return
        visiting.add(ident)
        for required in catalog[ident].requires:
            visit(required, visiting, visited)
        visiting.remove(ident)
        visited.add(ident)
    visited: set[str] = set()
    for ident in catalog:
        visit(ident, set(), visited)

    if type(allowed_scopes) is not tuple or not all(scope in VALID_SCOPES for scope in allowed_scopes):
        raise ValueError("allowed scopes must come from a known policy vocabulary")
    _count(wall_time_ms, "wall_time_ms", 7_200_000, minimum=1)
    _count(peak_memory_mb, "peak_memory_mb", 131_072, minimum=1)
    _count(max_steps, "max_steps", MAX_STEPS, minimum=1)

    if not problems:
        return {
            "state": "evidence_needed", "experiments": [],
            "unknowns": ["No actionable reported defects. Do not assume the product or scene is visually good."],
            "promotion": "Independent engine and owner review required; no changes approved or executed.",
            "executed": False,
        }

    available = [t for t in catalog_items if t.scope in allowed_scopes]
    requested_codes = {code for code, _, _ in problems}
    promising = [t for t in available if set(t.addresses) & requested_codes]
    combos = []
    for count in range(1, max_steps + 1):
        for chosen in combinations(promising, count):
            selection = {t.ident for t in chosen}
            # Prerequisite tools may be measurement-only and have no direct fault coverage.
            frontier = list(selection)
            while frontier:
                for required in catalog[frontier.pop()].requires:
                    if required not in selection:
                        selection.add(required)
                        frontier.append(required)
            if len(selection) > max_steps or any(catalog[s].scope not in allowed_scopes for s in selection):
                continue
            order = _order(tuple(sorted(selection)), catalog)
            duration = sum(catalog[s].cost_ms for s in order)
            memory = max(catalog[s].peak_memory_mb for s in order)
            if duration > wall_time_ms or memory > peak_memory_mb:
                continue
            covered = {p[0] for p in problems if any(p[0] in catalog[s].addresses for s in order)}
            benefit = sum(weight for code, _, weight in problems if code in covered)
            if benefit <= 0:
                continue
            combos.append({
                "techniques": list(order),
                "addresses": sorted(covered),
                "coverage_weight": benefit,
                "estimated_ms": duration,
                "estimated_peak_memory_mb": memory,
                "proof_targets": list(dict.fromkeys(catalog[s].evidence for s in order)),
                "authority": sorted({catalog[s].scope for s in order}),
                "state": "UNTESTED_PROPOSAL",
            })

    combos.sort(key=lambda p: (-p["coverage_weight"], p["estimated_ms"], p["estimated_peak_memory_mb"],
                               len(p["techniques"]), p["techniques"]))
    unique: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    for row in combos:
        ident = tuple(row["techniques"])
        if ident not in seen:
            seen.add(ident)
            unique.append(row)
        if len(unique) >= 5:
            break

    coverable = set().union(*(set(p["addresses"]) for p in combos)) if combos else set()
    unavailable = sorted(requested_codes - coverable)
    blocked_scopes = sorted({t.scope for t in catalog_items
                             if t.scope not in allowed_scopes and set(t.addresses) & requested_codes})
    state = "experiments_proposed" if unique else "blocked_or_unmeasured"
    return {
        "state": state,
        "experiments": unique,
        "capability_gaps": unavailable,
        "scopes_needing_separate_permission": blocked_scopes,
        "questions_to_research": [
            f"Find or build a documented, authorized, verifiable technique addressing {code}."
            for code in unavailable
        ][:20],
        "budget": {"max_steps": max_steps, "wall_time_ms": wall_time_ms, "peak_memory_mb": peak_memory_mb},
        "promotion": ("These are proposals, not measured wins. Execute only through policy-owned tools, "
                      "then use independent repeated paired trials in star/frontier_lab.py, "
                      "sealed holdouts and owner creative signoff before retaining a new skill."),
        "executed": False,
    }
