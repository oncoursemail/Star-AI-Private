"""Offline, oracle-graded frontier questions for STAR's self-practice.

This is a *training* curriculum, never a benchmark, trusted memory promotion,
model-weight update, or permission grant. The host injects the solver; generated
questions and solver output cannot write code, alter evaluators, or open PRs.
Protected holdouts stay in STAR's independent evaluation system.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import secrets
import sqlite3
import sys
from typing import Any, Awaitable, Callable

FAMILIES = ("route", "scheduler", "game-state", "fusion")
CORE_FAMILIES = FAMILIES[:3]
MAX_LEVEL = 12
MAX_CAMPAIGN = 6
MAX_ANSWER_BYTES = 8192
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = 1


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _project(project: str) -> str:
    if type(project) is not str or not _PROJECT.fullmatch(project):
        raise ValueError("Invalid project identifier")
    return project


def _level(level: int) -> int:
    if type(level) is not int or not 1 <= level <= MAX_LEVEL:
        raise ValueError("Difficulty must be 1..12")
    return level


def _seed(seed: int) -> int:
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("Seed must be a nonnegative 31-bit integer")
    return seed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _route_segment(grid: list[list[int | None]], start: tuple[int, int],
                   end: tuple[int, int]) -> tuple[int, int]:
    """A trusted dynamic-programming oracle (right/down only)."""
    sr, sc = start
    er, ec = end
    if sr > er or sc > ec:
        raise ValueError("Checkpoints must be topologically ordered")
    costs: dict[tuple[int, int], tuple[int, int]] = {}
    for r in range(sr, er + 1):
        for c in range(sc, ec + 1):
            value = grid[r][c]
            if value is None:
                continue
            if (r, c) == start:
                costs[r, c] = (value, 1)
                continue
            parents = [costs[p] for p in ((r - 1, c), (r, c - 1)) if p in costs]
            if parents:
                best = min(cost for cost, _ways in parents)
                costs[r, c] = (best + value, sum(ways for cost, ways in parents if cost == best))
    if end not in costs:
        raise ValueError("Generated route is not solvable")
    return costs[end]


def _route_problem(level: int, seed: int) -> tuple[str, dict]:
    rng = random.Random(seed ^ (level << 17) ^ 0xB077)
    size = min(3 + (level + 1) // 2, 9)
    grid: list[list[int | None]] = [
        [rng.randint(1, 9) for _ in range(size)] for _ in range(size)
    ]
    for r in range(size):
        for c in range(size):
            if rng.random() < min(0.07 + level * 0.014, 0.24):
                grid[r][c] = None
    checkpoints = []
    if level >= 4:
        checkpoints.append([size // 2, size // 2])
    if level >= 10:
        checkpoints.append([size - 2, size - 2])
    # Carve a legitimate route through *every* mandatory checkpoint.
    waypoints = [[0, 0], *checkpoints, [size - 1, size - 1]]
    for (r1, c1), (r2, c2) in zip(waypoints, waypoints[1:]):
        for c in range(c1, c2 + 1):
            if grid[r1][c] is None:
                grid[r1][c] = rng.randint(1, 9)
        for r in range(r1, r2 + 1):
            if grid[r][c2] is None:
                grid[r][c2] = rng.randint(1, 9)
    spec = {"grid": grid, "checkpoints": checkpoints, "count_optimal": level >= 7}
    path_rule = (" Pass through checkpoints IN ORDER: " + _json(checkpoints) + ".") if checkpoints else ""
    keys = ',"optimal_routes":integer' if spec["count_optimal"] else ""
    prompt = (
        "Roblox NPC navigation reasoning challenge. Grid entries are movement energy; null cells are blocked. "
        "Start at row 0, column 0; reach the bottom-right corner. Move only RIGHT or DOWN. "
        "Pay energy for every visited cell, including the start." + path_rule
        + " Minimize total energy." +
        (" Count the number of distinct minimum-energy routes." if spec["count_optimal"] else "") +
        f" Return ONLY a JSON object with {{\"minimum_cost\":integer{keys}}}. "
        "The grid is zero-indexed: " + _json(grid)
    )
    return prompt, spec


def _route_answer(spec: dict) -> dict:
    grid = spec["grid"]
    points = [(0, 0), *(tuple(p) for p in spec["checkpoints"]), (len(grid) - 1, len(grid) - 1)]
    cost = 0
    count = 1
    for a, b in zip(points, points[1:]):
        c, n = _route_segment(grid, a, b)
        cost += c
        count *= n
        if a != (0, 0):
            cost -= grid[a[0]][a[1]]
    result = {"minimum_cost": cost}
    if spec["count_optimal"]:
        result["optimal_routes"] = count
    return result


def _scheduler_problem(level: int, seed: int) -> tuple[str, dict]:
    rng = random.Random(seed ^ (level << 16) ^ 0x5155)
    tasks = []
    for i in range(min(3 + level, 16)):
        count = rng.randint(0, min(i, 1 + level // 3))
        previous = sorted(rng.sample(range(1, i + 1), count))
        tasks.append({
            "id": f"T{i+1}", "duration": rng.randint(1, min(9 + level, 18)),
            "after": [f"T{j}" for j in previous],
        })
    spec = {"tasks": tasks, "include_starts": level >= 5}
    schema = ('{"makespan":integer,"starts":{"T1":integer,...}}'
              if spec["include_starts"] else '{"makespan":integer}')
    prompt = (
        "Animation/render pipeline scheduling challenge. All tasks run on unlimited parallel workers. "
        "Each task can start only after every listed prerequisite has COMPLETED; tasks otherwise start "
        "as early as possible at time zero. Durations are positive. Compute the earliest overall finish."
        + (" Also return the earliest start time of EVERY task." if spec["include_starts"] else "")
        + " Return ONLY JSON shaped like " + schema + ". Tasks: " + _json(tasks)
    )
    return prompt, spec


def _scheduler_answer(spec: dict) -> dict:
    done: dict[str, int] = {}
    starts: dict[str, int] = {}
    for task in spec["tasks"]:
        start = max((done[d] for d in task["after"]), default=0)
        starts[task["id"]] = start
        done[task["id"]] = start + task["duration"]
    answer: dict = {"makespan": max(done.values())}
    if spec["include_starts"]:
        answer["starts"] = starts
    return answer


_RULES = (
    "Begin with health=100, coins=9, shield=0, potions=0, cooldown=0. "
    "'coin(n)' adds coins capped at 30; 'damage(n)' depletes shield first then health, "
    "never below zero; 'heal(n)' increases health up to 100. "
    "'shield(n)' increases shield up to 25. "
    "'buy' spends 5 coins to get one potion if coins>=5 and potions<3, otherwise does nothing. "
    "'use' consumes one potion and restores 20 health (capped at 100) ONLY if health<100, "
    "potions>0 and cooldown=0; a successful use sets cooldown=2. "
    "'tick' reduces cooldown by one, down to zero. Actions are processed in the listed order."
)


def _game_problem(level: int, seed: int) -> tuple[str, dict]:
    rng = random.Random(seed ^ (level << 18) ^ 0x6A63)
    kinds = ["coin", "damage", "heal"]
    if level >= 4:
        kinds.append("shield")
    if level >= 6:
        kinds.append("buy")
    if level >= 8:
        kinds.append("use")
    if level >= 10:
        kinds.append("tick")
    actions = []
    for _ in range(min(4 + 2 * level, 30)):
        kind = rng.choice(kinds)
        actions.append({"op": kind, **({"n": rng.randint(1, 20)}
                                       if kind in {"coin", "damage", "heal", "shield"} else {})})
    spec = {"actions": actions}
    prompt = (
        "Implement the reasoning for this Roblox game server state machine. " + _RULES +
        " Return ONLY JSON with EXACT integer fields: health, coins, shield, potions, cooldown. "
        "Events: " + _json(actions)
    )
    return prompt, spec


def _game_answer(spec: dict) -> dict:
    state = {"health": 100, "coins": 9, "shield": 0, "potions": 0, "cooldown": 0}
    for action in spec["actions"]:
        op = action["op"]
        n = action.get("n", 0)
        if op == "coin":
            state["coins"] = min(30, state["coins"] + n)
        elif op == "damage":
            used = min(state["shield"], n)
            state["shield"] -= used
            state["health"] = max(0, state["health"] - (n - used))
        elif op == "heal":
            state["health"] = min(100, state["health"] + n)
        elif op == "shield":
            state["shield"] = min(25, state["shield"] + n)
        elif op == "buy":
            if state["coins"] >= 5 and state["potions"] < 3:
                state["coins"] -= 5
                state["potions"] += 1
        elif op == "use":
            if state["potions"] and state["health"] < 100 and state["cooldown"] == 0:
                state["potions"] -= 1
                state["health"] = min(100, state["health"] + 20)
                state["cooldown"] = 2
        elif op == "tick":
            state["cooldown"] = max(0, state["cooldown"] - 1)
        else:
            raise ValueError("Unknown generated operation")
    return state


def build_problem(family: str, level: int, seed: int) -> tuple[str, dict]:
    """Create public text + private input spec. No model or untrusted code runs."""
    if family not in FAMILIES or type(family) is not str:
        raise ValueError("Unsupported challenge family")
    _level(level)
    _seed(seed)
    if family == "route":
        return _route_problem(level, seed)
    if family == "scheduler":
        return _scheduler_problem(level, seed)
    if family == "game-state":
        return _game_problem(level, seed)
    _route_prompt, route = _route_problem(level, seed)
    _schedule_prompt, scheduling = _scheduler_problem(level, seed ^ 0x4B29)
    # The task text contains the *original* durations. The trusted oracle
    # computes the adjusted schedule only in its private copy.
    original_tasks = [dict(task) for task in scheduling["tasks"]]
    minimum_cost = _route_answer(route)["minimum_cost"]
    scheduling["tasks"][0]["duration"] += minimum_cost % 5
    spec = {"route": route, "scheduler": scheduling}
    route_detail = {"grid": route["grid"], "checkpoints": route["checkpoints"]}
    prompt = (
        "CROSS-DOMAIN PROBLEM. Solve these two linked reasoning tasks, in order. "
        "FIRST: Find the minimum energy route from top-left to bottom-right of this zero-indexed "
        "grid. Move only RIGHT or DOWN. Numeric cells cost that energy including the start; "
        "null cells are blocked. Visit listed checkpoints in order. "
        "Routing input: " + _json(route_detail) + ". "
        "SECOND: Compute the earliest finish of a dependency-ordered rendering pipeline "
        "with unlimited parallel workers. A task starts after all its 'after' prerequisites "
        "finish (otherwise time zero). Before calculating the schedule, ADD "
        "(minimum_cost MOD 5) to the duration of task T1. "
        "The listed tasks contain the ORIGINAL, not adjusted, durations: " +
        _json(original_tasks) + ". "
        "Return ONLY JSON with exactly two integer keys: minimum_cost and makespan."
    )
    return prompt, spec


def oracle_answer(family: str, spec: dict) -> dict:
    """Reference computation is code-owned, never read from model output."""
    if family == "route":
        return _route_answer(spec)
    if family == "scheduler":
        return _scheduler_answer(spec)
    if family == "game-state":
        return _game_answer(spec)
    if family == "fusion":
        return {
            "minimum_cost": _route_answer(spec["route"])["minimum_cost"],
            "makespan": _scheduler_answer(spec["scheduler"])["makespan"],
        }
    raise ValueError("Unsupported challenge family")


def _exact(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (actual.keys() == expected.keys()
                and all(_exact(actual[k], v) for k, v in expected.items()))
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _exact(a, b) for a, b in zip(actual, expected)
        )
    return actual == expected


@dataclass(frozen=True)
class Challenge:
    id: str
    project: str
    family: str
    level: int
    prompt: str
    schema: tuple[str, ...]
    training_only: bool = True


class FrontierStore:
    """Private SQLite training memory. The *host*, never a model tool, owns writes."""

    def __init__(self, home: Path):
        home = Path(home).expanduser()
        if not home.is_dir() or home.is_symlink():
            raise PermissionError("Choose an existing, nonsymlinked private STAR data directory")
        folder = home / "frontier_quests"
        if folder.is_symlink():
            raise PermissionError("Cannot use a symlinked frontier data directory")
        folder.mkdir(mode=0o700, exist_ok=True)
        self.path = folder / "frontier.sqlite3"
        if self.path.is_symlink():
            raise PermissionError("Cannot open a symlinked frontier database")
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        if os.name == "posix":
            os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS frontier_progress (
                project TEXT NOT NULL, family TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 1,
                passed INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
                pass_streak INTEGER NOT NULL DEFAULT 0, fail_streak INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (project, family)
            );
            CREATE TABLE IF NOT EXISTS frontier_challenges (
                id TEXT PRIMARY KEY, project TEXT NOT NULL, family TEXT NOT NULL, level INTEGER NOT NULL,
                seed INTEGER NOT NULL, prompt TEXT NOT NULL, specification TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending','passed','failed')),
                created_at TEXT NOT NULL, finished_at TEXT,
                UNIQUE(project, family, seed)
            );
            CREATE INDEX IF NOT EXISTS idx_frontier_challenges
                ON frontier_challenges(project, family, status, created_at);
            CREATE TABLE IF NOT EXISTS frontier_attempts (
                challenge_id TEXT PRIMARY KEY REFERENCES frontier_challenges(id),
                answer_sha256 TEXT NOT NULL, passed INTEGER NOT NULL, graded_at TEXT NOT NULL,
                grader TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS frontier_proposals (
                id TEXT PRIMARY KEY, project TEXT NOT NULL, family TEXT NOT NULL,
                target TEXT NOT NULL, objective TEXT NOT NULL, evidence TEXT NOT NULL,
                created_at TEXT NOT NULL, status TEXT NOT NULL CHECK (status = 'candidate')
            );
            CREATE TABLE IF NOT EXISTS frontier_upgrade_jobs (
                proposal_id TEXT PRIMARY KEY REFERENCES frontier_proposals(id),
                project TEXT NOT NULL, status TEXT NOT NULL
                    CHECK (status IN ('reserved','created','unknown')),
                branch TEXT NOT NULL DEFAULT '', pr_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, finished_at TEXT
            );
        """)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "FrontierStore":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _ensure(self, project: str, family: str) -> sqlite3.Row:
        self.db.execute("INSERT OR IGNORE INTO frontier_progress(project,family,level) VALUES(?,?,1)",
                        (project, family))
        row = self.db.execute("SELECT * FROM frontier_progress WHERE project=? AND family=?",
                              (project, family)).fetchone()
        assert row is not None
        return row

    def _choose_family(self, project: str) -> str:
        stats = {family: self._ensure(project, family) for family in CORE_FAMILIES}
        eligible: list[str] = list(CORE_FAMILIES)
        if stats["route"]["level"] >= 3 and stats["scheduler"]["level"] >= 3:
            eligible.append("fusion")
            self._ensure(project, "fusion")
        def weight(family: str) -> tuple[int, int, str]:
            count = self.db.execute(
                "SELECT COUNT(*) FROM frontier_challenges WHERE project=? AND family=?",
                (project, family),
            ).fetchone()[0]
            return (count, self._ensure(project, family)["level"], family)
        return min(eligible, key=weight)

    @staticmethod
    def _challenge(row: sqlite3.Row) -> Challenge:
        spec = json.loads(row["specification"])
        schema = tuple(oracle_answer(row["family"], spec))
        return Challenge(row["id"], row["project"], row["family"],
                         row["level"], row["prompt"], schema)

    def issue(self, project: str, *, family: str = "auto", seed: int | None = None) -> Challenge:
        """Mint/reuse one pending task per domain; caller cannot set difficulty."""
        project = _project(project)
        if family != "auto" and family not in FAMILIES:
            raise ValueError("Invalid family")
        if seed is not None:
            _seed(seed)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if family == "auto":
                family = self._choose_family(project)
            progress = self._ensure(project, family)
            existing = self.db.execute(
                "SELECT * FROM frontier_challenges WHERE project=? AND family=? AND status='pending' "
                "ORDER BY created_at DESC LIMIT 1", (project, family),
            ).fetchone()
            if existing is not None:
                result = self._challenge(existing)
            else:
                result = None
                for _ in range(12):
                    selected_seed = seed if seed is not None else secrets.randbelow(2**31)
                    prompt, spec = build_problem(family, progress["level"], selected_seed)
                    ident = _sha([_VERSION, project, family, progress["level"], selected_seed, spec])
                    clash = self.db.execute(
                        "SELECT 1 FROM frontier_challenges WHERE project=? AND family=? AND seed=?",
                        (project, family, selected_seed),
                    ).fetchone()
                    if clash is None:
                        self.db.execute(
                            "INSERT INTO frontier_challenges VALUES(?,?,?,?,?,?,?,'pending',?,NULL)",
                            (ident, project, family, progress["level"], selected_seed, prompt, _json(spec), _now()),
                        )
                        row = self.db.execute(
                            "SELECT * FROM frontier_challenges WHERE id=?", (ident,),
                        ).fetchone()
                        assert row is not None
                        result = self._challenge(row)
                        break
                    if seed is not None:
                        raise ValueError("Seed already used in this project and domain")
                if result is None:
                    raise RuntimeError("Cannot mint a unique challenge")
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def grade(self, project: str, challenge_id: str, answer: str) -> dict:
        """One irreversible attempt, compared with a trusted code oracle."""
        project = _project(project)
        if type(challenge_id) is not str or not _DIGEST.fullmatch(challenge_id):
            raise ValueError("Invalid challenge id")
        if type(answer) is not str or len(answer.encode("utf-8")) > MAX_ANSWER_BYTES:
            raise ValueError("Answer must be UTF-8 JSON under 8192 bytes")
        try:
            response = json.loads(answer)
        except json.JSONDecodeError:
            response = None
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT * FROM frontier_challenges WHERE id=? AND project=?",
                (challenge_id, project),
            ).fetchone()
            if row is None or row["status"] != "pending":
                raise ValueError("Unknown or already graded challenge")
            spec = json.loads(row["specification"])
            ident = _sha([_VERSION, project, row["family"], row["level"], row["seed"], spec])
            if ident != row["id"]:
                raise ValueError("Challenge specification integrity mismatch")
            truth = oracle_answer(row["family"], spec)
            passed = _exact(response, truth)
            status = "passed" if passed else "failed"
            self.db.execute(
                "UPDATE frontier_challenges SET status=?, finished_at=? WHERE id=? AND status='pending'",
                (status, _now(), challenge_id),
            )
            self.db.execute(
                "INSERT INTO frontier_attempts VALUES(?,?,?,?,?)",
                (challenge_id, hashlib.sha256(answer.encode("utf-8")).hexdigest(),
                 int(passed), _now(), "local-deterministic-oracle-v1"),
            )
            progress = self._ensure(project, row["family"])
            next_level = int(progress["level"])
            pass_streak = progress["pass_streak"] + 1 if passed else 0
            fail_streak = progress["fail_streak"] + 1 if not passed else 0
            if pass_streak >= 3 and next_level < MAX_LEVEL:
                next_level += 1
                pass_streak = fail_streak = 0
            elif fail_streak >= 3 and next_level > 1:
                next_level -= 1
                pass_streak = fail_streak = 0
            self.db.execute(
                "UPDATE frontier_progress SET level=?,passed=passed+?,failed=failed+?,"
                "pass_streak=?,fail_streak=? WHERE project=? AND family=?",
                (next_level, int(passed), int(not passed), pass_streak, fail_streak,
                 project, row["family"]),
            )
            self.db.commit()
            return {"challenge_id": challenge_id, "passed": passed, "family": row["family"],
                    "old_level": row["level"], "next_level": next_level,
                    "grader": "local-deterministic-oracle-v1", "training_only": True,
                    "correct_answer_revealed": False}
        except BaseException:
            self.db.rollback()
            raise

    def overview(self, project: str) -> dict:
        project = _project(project)
        rows = self.db.execute(
            "SELECT project,family,level,passed,failed,pass_streak,fail_streak "
            "FROM frontier_progress WHERE project=? ORDER BY family", (project,),
        ).fetchall()
        pending = self.db.execute(
            "SELECT COUNT(*) FROM frontier_challenges WHERE project=? AND status='pending'",
            (project,),
        ).fetchone()[0]
        return {"project": project, "families": [dict(row) for row in rows],
                "pending": pending, "measured_holdout_improvement": False,
                "trained_model_weights": False}

    def propose_focus(self, project: str) -> list[dict]:
        """Candidate *skill* tasks for existing self-builder; never edits GitHub."""
        project = _project(project)
        topics = {
            "route": ("pathfinding-reasoning", "multi-stage NPC route planning, blockers and route counting"),
            "scheduler": ("pipeline-planning", "dependency scheduling, critical paths and start-time validation"),
            "game-state": ("server-state-reasoning", "ordered server-side state transitions and edge conditions"),
            "fusion": ("cross-domain-reasoning", "composing pathfinding and scheduling without dropping constraints"),
        }
        proposals = []
        for family in FAMILIES:
            results = self.db.execute(
                "SELECT c.status FROM frontier_challenges c WHERE c.project=? AND c.family=? "
                "AND c.status IN ('passed','failed') ORDER BY c.finished_at DESC, c.rowid DESC LIMIT 8",
                (project, family),
            ).fetchall()
            failed = sum(row["status"] == "failed" for row in results)
            if failed < 3 or failed <= len(results) // 2:
                continue
            slug, objective = topics[family]
            target = f"docs/skills/frontier-{slug}.md"
            statement = (
                f"Improve verified development performance on {objective}. "
                "Write small generalizable examples with counterexamples; "
                "use only the existing self-builder's allowed skill path. "
                "Re-evaluate against the independent baseline and protected holdout; "
                "never modify graders, permissions, CI, or the holdout."
            )
            total = self.db.execute(
                "SELECT COUNT(*) FROM frontier_challenges WHERE project=? AND family=? "
                "AND status IN ('passed','failed')", (project, family),
            ).fetchone()[0]
            # A stable proposal generation for each eight further attempts:
            # the fourth, fifth, etc. failed task must not spawn another PR.
            generation = max(0, (total - 3) // 8)
            evidence = f"{failed} failed of last {len(results)} independently oracle-graded training attempts"
            ident = _sha([project, family, target, generation])
            self.db.execute("INSERT OR IGNORE INTO frontier_proposals VALUES(?,?,?,?,?,?,?,'candidate')",
                            (ident, project, family, target, statement, evidence, _now()))
            saved = self.db.execute(
                "SELECT evidence FROM frontier_proposals WHERE id=?", (ident,),
            ).fetchone()
            proposals.append({"id": ident, "family": family, "suggested_path": target,
                              "objective": statement, "evidence": saved["evidence"],
                              "status": "candidate", "opened_pr": False, "executed": False})
        return proposals


async def draft_skill_upgrade(
    store: FrontierStore, project: str, *, client, model: str, repository: Path,
    github=None, host_approved: bool = False, max_turns: int = 6,
) -> dict:
    """Turn repeated oracle-backed failures into ONE guarded self-builder proposal.

    Uses STAR's existing selfbuild.develop gate. Model-controlled text is only a
    task brief; it cannot choose a repository, source path, App scope, grader,
    permission or PR base. For a PR, GitHub App migration must already be
    reviewed and configured for the source repository. Never auto-merges.
    """
    if host_approved is not True:
        raise PermissionError("Owner must enable self-build proposals in the trusted host")
    if type(max_turns) is not int or not 1 <= max_turns <= 6:
        raise ValueError("Self-builder has a 1..6 turn cap")
    if type(model) is not str or not model.strip():
        raise ValueError("A configured local model is required")
    project = _project(project)
    options = store.propose_focus(project)
    if not options:
        return {"status": "no_evidence", "review_required": True,
                "opened_pr": False, "reason": "No repeatedly failed verified training family"}
    from . import selfbuild  # optional GitHub dependencies are loaded only for actual upgrades
    proposal = options[0]
    if not selfbuild.skill_path(proposal["suggested_path"]):
        raise PermissionError("Training improvement target is outside the existing self-builder allowlist")
    # Never accept an arbitrary model-supplied publisher. The installed
    # GitHubApp itself enforces the repository/branch allowlist (including
    # any separately reviewed development-repo migration).
    if github is not None:
        from .github_app import GitHubApp
        if not isinstance(github, GitHubApp):
            raise TypeError("The trusted host must supply STAR's scoped GitHubApp writer")
    store.db.execute("BEGIN IMMEDIATE")
    try:
        claimed = store.db.execute(
            "INSERT OR IGNORE INTO frontier_upgrade_jobs(proposal_id,project,status,created_at) "
            "VALUES(?,?,'reserved',?)", (proposal["id"], project, _now()),
        )
        if claimed.rowcount == 0:
            previous = store.db.execute(
                "SELECT status,branch,pr_url FROM frontier_upgrade_jobs "
                "WHERE proposal_id=? AND project=?", (proposal["id"], project),
            ).fetchone()
            store.db.commit()
            return {"status": "already_submitted_or_needs_review",
                    "proposal_id": proposal["id"],
                    "job_status": previous["status"] if previous else "unknown",
                    "review_required": True, "opened_pr": False}
        store.db.commit()
    except BaseException:
        store.db.rollback()
        raise
    task = (
        "Improve only an allowed STAR self-builder skill/doc file, with the primary target "
        + proposal["suggested_path"] + ".\nEvidence: " + proposal["evidence"]
        + "\nObjective: " + proposal["objective"]
        + "\nUse source-grounded examples and counterexamples; no claims of test passes "
        "without independent evidence. Leave evaluators, memory policy and auth unchanged."
    )
    try:
        receipt = await selfbuild.develop(
            client=client, model=model, repository=Path(repository), task=task,
            github=github, max_turns=max_turns,
        )
        if (not isinstance(receipt, dict) or type(receipt.get("branch")) is not str
                or not receipt["branch"].startswith("star/")
                or not isinstance(receipt.get("files"), list)
                or not receipt["files"]
                or any(not selfbuild.skill_path(p) for p in receipt["files"])):
            raise ValueError("Self-builder did not produce an inspectable allowed-files receipt")
        branch = receipt["branch"]
        pr_url = receipt.get("github_pr")
        if not isinstance(pr_url, str):
            pr_url = ""
        # No claims of CI or model-quality improvement follow from creating a PR.
        store.db.execute(
            "UPDATE frontier_upgrade_jobs SET status='created',branch=?,pr_url=?,finished_at=? "
            "WHERE proposal_id=? AND status='reserved'",
            (branch, pr_url[:300], _now(), proposal["id"]),
        )
    except BaseException:
        # A crash after GitHub upload is ambiguous: preserve for human
        # inspection instead of issuing duplicate mutations on retry.
        store.db.execute(
            "UPDATE frontier_upgrade_jobs SET status='unknown',finished_at=? "
            "WHERE proposal_id=? AND status='reserved'", (_now(), proposal["id"]),
        )
        raise
    return {"status": "review_candidate_created", "proposal_id": proposal["id"],
            "branch": branch, "github_pr": pr_url or None,
            "opened_pr": bool(pr_url), "review_required": True,
            "merged": False, "model_weights_trained": False}


async def practice_campaign(
    store: FrontierStore, project: str, solve: Callable[[Challenge], Awaitable[str]], *,
    host_approved: bool = False, count: int = 3,
) -> dict:
    """Trusted-host entrypoint; model sees only prompt, never grader/storage handles."""
    if host_approved is not True:
        raise PermissionError("Owner must enable the bounded local practice session")
    if type(count) is not int or not 1 <= count <= MAX_CAMPAIGN:
        raise ValueError("One practice campaign can contain at most six questions")
    if not callable(solve):
        raise TypeError("Host must supply a solver callback")
    results = []
    for _ in range(count):
        challenge = store.issue(project)
        # Limit each model attempt; timeout leaves the question pending for retry
        # after host inspection, never incorrectly marks it failed.
        response = await asyncio.wait_for(solve(challenge), timeout=120)
        results.append(store.grade(project, challenge.id, response))
    return {"project": project, "attempts": len(results), "results": results,
            "training_only": True, "trained_model_weights": False, "opened_pr": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STAR offline, verifiable frontier practice")
    sub = parser.add_subparsers(dest="command", required=True)
    preview = sub.add_parser("preview", help="No database or model invocation")
    preview.add_argument("--family", choices=FAMILIES, required=True)
    preview.add_argument("--level", type=int, default=1)
    preview.add_argument("--seed", type=int, default=1)
    for cmd in ("next", "grade", "status", "propose"):
        p = sub.add_parser(cmd)
        p.add_argument("--home", type=Path, required=True)
        p.add_argument("--project", required=True)
        if cmd == "next":
            p.add_argument("--family", choices=("auto", *FAMILIES), default="auto")
        if cmd == "grade":
            p.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    if args.command == "preview":
        prompt, spec = build_problem(args.family, args.level, args.seed)
        print(_json({"family": args.family, "level": args.level, "prompt": prompt,
                     "answer_schema": sorted(oracle_answer(args.family, spec)),
                     "training_only": True}))
        return 0
    with FrontierStore(args.home) as store:
        if args.command == "next":
            print(_json(asdict(store.issue(args.project, family=args.family))))
        elif args.command == "grade":
            raw = sys.stdin.read(MAX_ANSWER_BYTES + 1)
            if len(raw.encode("utf-8")) > MAX_ANSWER_BYTES:
                parser.error("Answer over 8192 bytes")
            print(_json(store.grade(args.project, args.id, raw)))
        elif args.command == "propose":
            print(_json(store.propose_focus(args.project)))
        else:
            print(_json(store.overview(args.project)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
