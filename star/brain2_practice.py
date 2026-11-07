"""Host-controlled recurring Brain 2 practice using STAR's existing Roblox Cloud test pipeline.

Runs exact owner-chosen private test places only. A bounded operator command can
repeat Saved-version publishes and Luau tests, but is never offered as a model
tool. Actual test evidence is stored locally; learned advice needs human review.
"""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Callable

from .roblox_cloud import CloudError, RobloxCloud
from .roblox_pipeline import run_pipeline


class PracticeRefused(RuntimeError):
    """Cannot start another run without a new, explicit operator decision."""


class PracticeUnknown(PracticeRefused):
    """A previous mutation may have completed without a reliable confirmation."""


@dataclass(frozen=True)
class PracticePlan:
    """Immutable scope provided by the human-operated host, not the model."""

    project: str
    source: Path
    universe_id: int
    place_id: int
    builder: str = "builtin"
    interval_seconds: int = 900
    daily_limit: int = 24

    @classmethod
    def load(cls, filename: Path) -> "PracticePlan":
        location = Path(filename).expanduser().resolve(strict=True)
        raw = json.loads(location.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {
            "project", "source", "universe_id", "place_id", "builder",
            "interval_seconds", "daily_limit",
        }:
            raise ValueError("Practice plan must contain exactly the documented fields")
        project, source = raw["project"], raw["source"]
        if not isinstance(project, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", project):
            raise ValueError("Practice project must be a short, explicit identifier")
        if not isinstance(source, str) or not source or not Path(source).is_absolute():
            raise ValueError("Practice source must be an absolute operator-selected directory")
        path = Path(source).resolve(strict=True)
        if not path.is_dir() or location == path or path in location.parents:
            raise ValueError("Practice plan must be outside its source tree")
        for name in ("universe_id", "place_id"):
            if type(raw[name]) is not int or not 0 < raw[name] < 2**63:
                raise ValueError("Practice target IDs must be positive integers")
        if not isinstance(raw["builder"], str) or raw["builder"] not in {"builtin", "rojo"}:
            raise ValueError("Practice builder must be builtin or rojo")
        interval = raw["interval_seconds"]
        daily = raw["daily_limit"]
        if type(interval) is not int or not 300 <= interval <= 86400:
            raise ValueError("Practice interval must be between five minutes and one day")
        if type(daily) is not int or not 1 <= daily <= 48:
            raise ValueError("Practice daily limit must be between one and 48")
        return cls(project=project, source=path, universe_id=raw["universe_id"],
                   place_id=raw["place_id"], builder=raw["builder"],
                   interval_seconds=interval, daily_limit=daily)

    @property
    def target(self) -> tuple[int, int]:
        return self.universe_id, self.place_id


class PinnedCloud:
    """Never let an integration run shift to another saved test experience."""

    def __init__(self, cloud: RobloxCloud, target: tuple[int, int]):
        self.cloud, self.target = cloud, target

    def check_key(self):
        return self.cloud.check_key()

    def guard_write(self, only=None):
        if only is not None and tuple(only) != self.target:
            raise CloudError("Practice target differs from the operator's chosen test experience")
        return self.cloud.guard_write(only=self.target)

    def publish_place(self, data, *, xml=True, version_type="Saved", only=None):
        if only != self.target or version_type != "Saved":
            raise CloudError("Practice may publish only a Saved version of its pinned test place")
        return self.cloud.publish_place(data, xml=xml, version_type="Saved", only=self.target)

    def run_luau(self, script, *, version=None, only=None):
        if only != self.target or type(version) is not int or version <= 0:
            raise CloudError("Practice can test only a confirmed pinned Saved version")
        return self.cloud.run_luau(script, version=version, only=self.target)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_name(name: str) -> str:
    # No raw error strings or console output are retained in the practice ledger.
    return re.sub(r"[\x00-\x1f\x7f]+", " ", name).strip()[:160]


class PracticeLedger:
    """Durable single-run gate, daily budget, and provenance for bounded practice."""

    def __init__(self, path: Path, *, clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS practice_cycles(
            id INTEGER PRIMARY KEY,
            project TEXT NOT NULL, universe_id INTEGER NOT NULL, place_id INTEGER NOT NULL,
            start_utc TEXT NOT NULL, finish_utc TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL, source_sha256 TEXT NOT NULL DEFAULT '',
            saved_version INTEGER, passed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0, cases_json TEXT NOT NULL DEFAULT '[]'
        )""")
        self.db.execute("CREATE INDEX IF NOT EXISTS practice_project_time ON practice_cycles(project, start_utc)")

    def close(self):
        self.db.close()

    def reserve(self, plan: PracticePlan) -> int:
        stamp = self.clock()
        if stamp.tzinfo is None:
            raise ValueError("Practice clock must be timezone aware")
        now = stamp.astimezone(timezone.utc)
        cutoff = now.timestamp() - plan.interval_seconds
        self.db.execute("BEGIN IMMEDIATE")
        try:
            pending = self.db.execute(
                "SELECT id FROM practice_cycles WHERE project=? AND status IN ('running','unknown') "
                "ORDER BY id DESC LIMIT 1", (plan.project,)).fetchone()
            if pending:
                raise PracticeUnknown(
                    f"Practice run {pending['id']} has an unknown outcome; inspect Roblox versions before continuing")
            today = now.date().isoformat()
            existing = self.db.execute(
                "SELECT start_utc FROM practice_cycles WHERE project=? AND "
                "universe_id=? AND place_id=? AND start_utc>=? ORDER BY id DESC",
                (plan.project, *plan.target, today),).fetchall()
            if len(existing) >= plan.daily_limit:
                raise PracticeRefused("Practice daily budget exhausted for this target")
            # Enforce the minimum interval even across UTC date boundaries.
            last = self.db.execute(
                "SELECT start_utc FROM practice_cycles WHERE project=? AND "
                "universe_id=? AND place_id=? ORDER BY id DESC LIMIT 1",
                (plan.project, *plan.target)).fetchone()
            if last is not None:
                try:
                    recent = datetime.fromisoformat(last["start_utc"]).timestamp()
                except (ValueError, TypeError):
                    raise PracticeRefused("Practice history has an invalid timestamp") from None
                if recent > cutoff:
                    raise PracticeRefused("Practice interval has not elapsed")
            entry = self.db.execute(
                "INSERT INTO practice_cycles(project,universe_id,place_id,start_utc,status) VALUES(?,?,?,?,?)",
                (plan.project, *plan.target, now.isoformat(timespec="seconds"), "running"),
            )
            self.db.commit()
            return int(entry.lastrowid)
        except BaseException:
            self.db.rollback()
            raise

    def previous_failure(self, plan: PracticePlan, before_cycle: int) -> dict | None:
        row = self.db.execute(
            "SELECT status,source_sha256,cases_json,saved_version FROM practice_cycles "
            "WHERE project=? AND universe_id=? AND place_id=? AND id<? "
            "ORDER BY id DESC LIMIT 1", (*((plan.project,) + plan.target), before_cycle)).fetchone()
        if row is None or row["status"] != "failed":
            return None
        return {"sha256": row["source_sha256"], "cases": json.loads(row["cases_json"]),
                "version": row["saved_version"]}

    def finish(self, cycle_id: int, *, status: str, sha256: str = "", version: int | None = None,
               summary: dict | None = None):
        if status not in {"passed", "failed", "blocked", "unknown"}:
            raise ValueError("Invalid practice cycle outcome")
        if sha256 and not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("Invalid source digest")
        summary = summary or {}
        cases = [{"name": _clean_name(item["name"]), "ok": item["ok"]}
                 for item in summary.get("cases", [])[:200]
                 if isinstance(item, dict) and isinstance(item.get("name"), str)
                 and type(item.get("ok")) is bool]
        count_passed = sum(case["ok"] for case in cases)
        count_failed = len(cases) - count_passed
        if status in {"passed", "failed"} and (
                not cases or count_passed != summary.get("passed")
                or count_failed != summary.get("failed") or type(version) is not int
                or version <= 0 or not sha256):
            raise ValueError("Confirmed outcomes need an exact source, Saved version and case report")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            updated = self.db.execute(
                "UPDATE practice_cycles SET finish_utc=?,status=?,source_sha256=?,saved_version=?,"
                "passed=?,failed=?,cases_json=? WHERE id=? AND status='running'",
                (self.clock().astimezone(timezone.utc).isoformat(timespec="seconds"),
                 status, sha256, version, count_passed, count_failed,
                 json.dumps(cases, ensure_ascii=False), cycle_id),
            )
            if updated.rowcount != 1:
                raise PracticeRefused("Practice run was already completed or changed")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def acknowledge(self, cycle_id: int, *, plan: PracticePlan, human_approved=False):
        """Human-only acknowledgement after inspecting the Roblox version history."""
        if human_approved is not True:
            raise PermissionError("The operator must explicitly acknowledge the uncertain run")
        if type(cycle_id) is not int or cycle_id <= 0:
            raise ValueError("Invalid practice run identifier")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            changed = self.db.execute(
                "UPDATE practice_cycles SET status='acknowledged',finish_utc=? WHERE id=? "
                "AND project=? AND universe_id=? AND place_id=? "
                "AND status IN ('running','unknown')",
                (self.clock().astimezone(timezone.utc).isoformat(timespec="seconds"),
                 cycle_id, plan.project, *plan.target),
            )
            if changed.rowcount != 1:
                raise PracticeRefused("No unknown practice run has this identifier")
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise


def _verified_result(report: Any, plan: PracticePlan) -> tuple[str, str, int | None, dict | None]:
    """Independent check of pinned targets/versions rather than trusting an ok flag."""
    if not isinstance(report, dict) or not isinstance(report.get("steps"), list):
        return "unknown", "", None, None
    steps = report["steps"]
    first = next((s for s in steps if isinstance(s, dict) and s.get("step") == "build"), {})
    sha = first.get("sha256", "")
    sha = sha if isinstance(sha, str) and re.fullmatch("[a-f0-9]{64}", sha) else ""
    if report.get("stopped_at") in {"build", "key", "test experience"}:
        return "blocked", sha, None, None
    publish = next((s for s in steps if isinstance(s, dict) and s.get("step") == "publish"), {})
    execution = next((s for s in steps if isinstance(s, dict) and s.get("step") == "run test"), {})
    result = next((s for s in steps if isinstance(s, dict) and s.get("step") == "result"), {})
    version = publish.get("version")
    valid = (
        publish.get("ok") is True and publish.get("version_type") == "Saved"
        and type(version) is int and version > 0
        and all(type(publish.get(k)) is int and publish[k] == v for k, v in
                zip(("universe_id", "place_id"), plan.target))
        and execution.get("ok") is True and execution.get("state") == "COMPLETE"
        and not execution.get("error") and execution.get("task_error") is None
        and execution.get("version") == version
        and all(type(execution.get(k)) is int and execution[k] == v for k, v in
                zip(("universe_id", "place_id"), plan.target))
    )
    summary = result.get("summary")
    if not valid or not sha or not isinstance(summary, dict):
        return "unknown", sha, version if type(version) is int else None, None
    # Validate again independently of the code that ran the tests.
    from .roblox_pipeline import _test_summary
    trusted = _test_summary(summary)
    if trusted is None or trusted.get("passed", 0) + trusted.get("failed", 0) <= 0:
        return "unknown", sha, version, None
    if report.get("ok") is True and result.get("ok") is True and trusted["failed"] == 0:
        return "passed", sha, version, trusted
    if report.get("ok") is False and result.get("ok") is False and trusted["failed"] > 0:
        return "failed", sha, version, trusted
    return "unknown", sha, version, None


def practice_once(cloud: RobloxCloud, plan: PracticePlan, ledger: PracticeLedger, *,
                  pipeline: Callable = run_pipeline, lessons: Any = None) -> dict:
    """One serialized, bounded saved-build + test; no editing of production games."""
    pinned = PinnedCloud(cloud, plan.target)
    # Validate the selected private place before any mutation or ledger reservation.
    checked = pinned.guard_write()
    if not isinstance(checked, dict) or any(checked.get(k) != value for k, value in
                                             zip(("universe_id", "place_id"), plan.target)):
        raise PracticeRefused("Roblox did not confirm the operator-selected target")
    cycle_id = ledger.reserve(plan)
    try:
        prior = ledger.previous_failure(plan, cycle_id)
        report = pipeline(pinned, plan.source, publish_and_test=True,
                          builder=plan.builder, home=ledger.path.parent)
        status, sha, version, summary = _verified_result(report, plan)
    except BaseException:
        # A remote write may have completed before our process lost its response.
        ledger.finish(cycle_id, status="unknown")
        raise
    ledger.finish(cycle_id, status=status, sha256=sha, version=version, summary=summary)
    result = {"cycle_id": cycle_id, "status": status, "project": plan.project,
              "source_sha256": sha, "saved_version": version,
              "passed": (summary or {}).get("passed", 0),
              "failed": (summary or {}).get("failed", 0),
              "learning_candidates": 0}
    if status == "passed" and prior and prior["sha256"] != sha and lessons is not None:
        try:
            previously_failed = {case["name"] for case in prior["cases"] if case.get("ok") is False}
            now_passing = {case["name"] for case in summary["cases"] if case["ok"] is True}
            for case_name in sorted(previously_failed & now_passing)[:5]:
                # Verified *change of outcome*, not a claim that a patch caused the fix.
                text = ("Regression case " + _clean_name(case_name) +
                        " passed after a previous failure on another source revision; "
                        "inspect the code diff before extracting a reusable repair.")
                evidence = f"prior sha={prior['sha256'][:12]} new sha={sha[:12]} saved version={version}"
                recorded = lessons.capture_inferred(project=plan.project, kind="pitfall", text=text,
                                                    source_type="verified-fix",
                                                    source=f"brain2-practice:{cycle_id}:{hashlib.sha256(case_name.encode()).hexdigest()[:12]}",
                                                    evidence=evidence)
                if recorded.status == "candidate":
                    result["learning_candidates"] += 1
        except Exception as exc:
            # A lesson-db problem cannot turn a verified test into an unknown test.
            result["learning_error"] = type(exc).__name__
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bounded, host-approved Brain 2 Roblox private practice")
    parser.add_argument("--plan", type=Path, required=True, help="Operator-authored manifest outside project source")
    parser.add_argument("--home", type=Path, required=True, help="Existing STAR private data directory")
    parser.add_argument("--run", action="store_true", help="Authorize Saved-version publish and Luau tests")
    parser.add_argument("--suggest-learning", action="store_true",
                        help="Read-only recommendations from independently verified practice history")
    parser.add_argument("--cycles", type=int, default=1, help="1-12 bounded cycles; no infinite loops")
    parser.add_argument("--acknowledge", type=int, help="After independently checking an unknown run, unblock this ID")
    args = parser.parse_args(argv)
    if not args.home.is_absolute() or not 1 <= args.cycles <= 12:
        parser.error("--home must be absolute and --cycles must be 1-12")
    if args.acknowledge is not None and args.run:
        parser.error("Acknowledgement and testing must be separate operator actions")
    if args.suggest_learning and (args.run or args.acknowledge is not None):
        parser.error("Suggestions must be separate from writes and acknowledgement")
    try:
        plan = PracticePlan.load(args.plan)
        if args.suggest_learning:
            # Preview only. Do not instantiate PracticeLedger (it creates a DB),
            # RobloxCloud, or an agent tool; do not execute any practice.
            from .learning_accelerator import recommend_from_ledger
            result = recommend_from_ledger(args.home / "brain2-practice.sqlite3",
                                           plan.project, target=plan.target)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        ledger = PracticeLedger(args.home / "brain2-practice.sqlite3")
        try:
            if args.acknowledge is not None:
                ledger.acknowledge(args.acknowledge, plan=plan, human_approved=True)
                print(json.dumps({"status": "acknowledged", "cycle_id": args.acknowledge}))
                return 0
            if not args.run:
                print(json.dumps({"status": "dry_run", "project": plan.project,
                                  "target": list(plan.target), "source": str(plan.source),
                                  "interval_seconds": plan.interval_seconds,
                                  "daily_limit": plan.daily_limit, "cycles_requested": args.cycles,
                                  "notice": "No Roblox request or code execution occurred."}))
                return 0
            from .lessons import LessonStore
            cloud = RobloxCloud(home=args.home)
            lessons = LessonStore(home=args.home)
            try:
                result = {}
                for index in range(args.cycles):
                    if index:
                        time.sleep(plan.interval_seconds)
                    result = practice_once(cloud, plan, ledger, lessons=lessons)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    if result["status"] != "passed":
                        return 1
                return 0
            finally:
                lessons.close()
                cloud.close()
        finally:
            ledger.close()
    except (CloudError, PracticeRefused, ValueError, OSError) as exc:
        # Never echo credentials, server bodies, traceback data or source code.
        print(json.dumps({"status": "refused", "reason": type(exc).__name__,
                          "message": "Review the local private practice plan and Roblox test history."}))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "notice": "An in-flight Roblox write may have continued. Check the ledger and version history."}))
        return 130
    except Exception as exc:
        print(json.dumps({"status": "unknown", "reason": type(exc).__name__,
                          "notice": "Inspect the pending practice ledger and Roblox version history."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
