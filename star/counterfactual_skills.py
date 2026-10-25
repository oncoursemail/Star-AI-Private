"""Experimental proof-carrying skill selection; NOT connected to STAR's runtime.

Stores *opaque recipe references*, not executable code or raw prompts. Only independent,
reviewed development evaluations may influence read-only advice. A trusted caller must
authenticate the evaluator and owner; an 'origin' string is NOT an auth boundary.

No model calls, shell access, network access, hidden evaluation access or auto-enable.
Requires Python >= 3.11. The SQLite file is local and is NOT tamper-proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import sqlite3
from typing import Literal

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
MIN_CASES = 12
ALPHA = 0.01


def _checked(value: str, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {field}")
    return value


@dataclass(frozen=True)
class Scope:
    """Never transfer outcomes between projects, toolchains or harness revisions."""

    project: str
    task_family: str
    environment_sha256: str  # model, permissions, codebase revision, test harness, dependencies
    toolchain_sha256: str    # trusted verifier tool revisions and configuration

    def __post_init__(self) -> None:
        _checked(self.project, _IDENTIFIER, "project")
        _checked(self.task_family, _IDENTIFIER, "task_family")
        _checked(self.environment_sha256, _DIGEST, "environment_sha256")
        _checked(self.toolchain_sha256, _DIGEST, "toolchain_sha256")


@dataclass(frozen=True)
class PairedTrial:
    """A matched first-attempt evaluation of existing policy and proposed recipe."""

    case_sha256: str
    baseline_pass: bool
    candidate_pass: bool
    baseline_ms: int
    candidate_ms: int
    origin: Literal["trusted_host"] = "trusted_host"
    partition: Literal["development"] = "development"

    def __post_init__(self) -> None:
        _checked(self.case_sha256, _DIGEST, "case_sha256")
        for flag in (self.baseline_pass, self.candidate_pass):
            if type(flag) is not bool:
                raise ValueError("Outcomes must be genuine booleans")
        for latency in (self.baseline_ms, self.candidate_ms):
            if type(latency) is not int or latency <= 0 or latency > 86_400_000:
                raise ValueError("Latency must be measured positive milliseconds")
        if self.origin != "trusted_host" or self.partition != "development":
            raise ValueError("Only independent host-verified development trials are admissible")


@dataclass(frozen=True)
class Advice:
    recipe_ref: str
    eligible: bool
    mode: Literal["quality", "speed", "none"]
    cases: int
    quality_wins: int
    quality_losses: int
    one_sided_quality_p: float
    one_sided_speed_p: float
    baseline_p95_ms: int | None
    candidate_p95_ms: int | None
    reasons: tuple[str, ...]


def _p_value(wins: int, losses: int) -> float:
    """Exact one-sided paired sign test; ties are excluded.

    This is NOT a proof of generalization or a substitute for untouched holdout tests.
    """
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)


def _p95(times: list[int]) -> int | None:
    return sorted(times)[math.ceil(0.95 * len(times)) - 1] if times else None


class CounterfactualSkillStore:
    """Explicit, read-only-by-default prototype: no runtime/lesson or policy integration.

    Evaluations MUST originate from a separate trusted host and compare frozen
    candidate/baseline on exactly the same cases. Repository/model agents can NEVER
    call approve_candidate or supply a trusted receipt directly in production.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=10)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY,
                project TEXT NOT NULL, task_family TEXT NOT NULL,
                environment_sha256 TEXT NOT NULL, toolchain_sha256 TEXT NOT NULL,
                recipe_ref TEXT NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(project, task_family, environment_sha256, toolchain_sha256, recipe_ref)
            );
            CREATE TABLE IF NOT EXISTS paired_trials (
                candidate_id INTEGER NOT NULL REFERENCES candidates(id),
                case_sha256 TEXT NOT NULL,
                baseline_pass INTEGER NOT NULL, candidate_pass INTEGER NOT NULL,
                baseline_ms INTEGER NOT NULL, candidate_ms INTEGER NOT NULL,
                PRIMARY KEY (candidate_id, case_sha256)
            );
        """)

    def __enter__(self) -> CounterfactualSkillStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def propose(self, scope: Scope, recipe_ref: str) -> None:
        """Record a candidate as unapproved; never change existing approval/evidence."""
        _checked(recipe_ref, _REF, "recipe_ref")
        with self.conn:
            self.conn.execute("""INSERT INTO candidates
                (project, task_family, environment_sha256, toolchain_sha256, recipe_ref)
                VALUES (?, ?, ?, ?, ?)""", (*_scope_tuple(scope), recipe_ref))

    def _id(self, scope: Scope, recipe_ref: str) -> int:
        _checked(recipe_ref, _REF, "recipe_ref")
        row = self.conn.execute("""SELECT id FROM candidates WHERE project=? AND task_family=?
            AND environment_sha256=? AND toolchain_sha256=? AND recipe_ref=?""",
            (*_scope_tuple(scope), recipe_ref)).fetchone()
        if row is None:
            raise KeyError("Candidate does not exist in the exact scope")
        return int(row[0])

    def approve_candidate(self, scope: Scope, recipe_ref: str, *, owner_approval: bool) -> None:
        """Host UI must enforce owner identity separately; this flag is only a contract."""
        if owner_approval is not True:
            raise PermissionError("Explicit verified owner approval is required")
        candidate_id = self._id(scope, recipe_ref)
        with self.conn:
            self.conn.execute("UPDATE candidates SET reviewed=1 WHERE id=?", (candidate_id,))

    def append_trial(self, scope: Scope, recipe_ref: str, trial: PairedTrial, *, host_verified: bool) -> None:
        """First valid receipt wins; duplicates cannot inflate evidence by retries.

        'host_verified' must be set by the independently authenticated test harness,
        never by the agent or a model-written JSON result.
        """
        if host_verified is not True:
            raise PermissionError("Independent host attestation required")
        if not isinstance(trial, PairedTrial):
            raise TypeError("Expected PairedTrial")
        candidate_id = self._id(scope, recipe_ref)
        with self.conn:
            self.conn.execute("""INSERT INTO paired_trials VALUES (?, ?, ?, ?, ?, ?)""",
                (candidate_id, trial.case_sha256, int(trial.baseline_pass),
                 int(trial.candidate_pass), trial.baseline_ms, trial.candidate_ms))

    def assess(self, scope: Scope, recipe_ref: str) -> Advice:
        candidate_id = self._id(scope, recipe_ref)
        count = self.conn.execute("""SELECT COUNT(*) FROM candidates
            WHERE project=? AND task_family=? AND environment_sha256=? AND toolchain_sha256=?""",
            _scope_tuple(scope)).fetchone()[0]
        reviewed = bool(self.conn.execute("SELECT reviewed FROM candidates WHERE id=?", (candidate_id,))
                        .fetchone()[0])
        rows = self.conn.execute("""SELECT baseline_pass, candidate_pass, baseline_ms, candidate_ms
            FROM paired_trials WHERE candidate_id=? ORDER BY case_sha256""", (candidate_id,)).fetchall()
        wins = sum(not bool(a) and bool(b) for a, b, _, _ in rows)
        losses = sum(bool(a) and not bool(b) for a, b, _, _ in rows)
        q_p = _p_value(wins, losses)
        faster = sum(b <= a * 0.95 for _, _, a, b in rows)
        slower = sum(b >= a * 1.05 for _, _, a, b in rows)
        s_p = _p_value(faster, slower)
        p95_base = _p95([a for _, _, a, _ in rows])
        p95_candidate = _p95([b for _, _, _, b in rows])
        reasons: list[str] = []
        if not reviewed:
            reasons.append("not owner-reviewed")
        if len(rows) < MIN_CASES:
            reasons.append(f"needs at least {MIN_CASES} independent matched cases")
        # Bonferroni guards candidate-selection multiplicity within one exact scope.
        threshold = ALPHA / max(1, int(count))
        quality = (len(rows) >= MIN_CASES and wins >= 6 and losses <= 1 and
                   q_p <= threshold and p95_candidate is not None and p95_base is not None and
                   p95_candidate <= 1.05 * p95_base)
        # Pure latency promotion requires exactly matched pass/fail behavior on all cases.
        speed = (len(rows) >= MIN_CASES and wins == 0 and losses == 0 and faster >= 8 and
                 s_p <= threshold and p95_candidate is not None and p95_base is not None and
                 p95_candidate <= 0.9 * p95_base)
        mode: Literal["quality", "speed", "none"] = "quality" if quality else "speed" if speed else "none"
        if mode == "none":
            reasons.append("no statistically gated paired quality/speed gain yet")
        if mode != "none" and not reviewed:
            reasons.append("owner approval is still required")
        return Advice(recipe_ref, reviewed and mode != "none", mode, len(rows), wins, losses, q_p, s_p,
                      p95_base, p95_candidate, tuple(reasons))

    def recommend(self, scope: Scope) -> Advice | None:
        """Suggest an approved recipe identifier; never import, execute or enable it."""
        rows = self.conn.execute("""SELECT recipe_ref FROM candidates
            WHERE project=? AND task_family=? AND environment_sha256=? AND toolchain_sha256=?
            ORDER BY recipe_ref""", _scope_tuple(scope)).fetchall()
        eligible = [result for (ref,) in rows if (result := self.assess(scope, ref)).eligible]
        if not eligible:
            return None
        # Prefer improvements in verified task success, then time; deterministic ties.
        return sorted(eligible, key=lambda a: (a.mode != "quality", -(a.quality_wins - a.quality_losses),
                                                a.candidate_p95_ms or float("inf"), a.recipe_ref))[0]


def _scope_tuple(scope: Scope) -> tuple[str, str, str, str]:
    if not isinstance(scope, Scope):
        raise TypeError("Expected Scope")
    return (scope.project, scope.task_family, scope.environment_sha256, scope.toolchain_sha256)
