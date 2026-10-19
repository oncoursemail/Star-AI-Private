#!/usr/bin/env python3
"""Manually prune old Windows PR artifacts using an already authenticated gh CLI.

Read-only by default; no tokens are read, printed, or copied by this program.
  python scripts/prune_old_windows_artifacts.py --plan cleanup.json
  python scripts/prune_old_windows_artifacts.py --only-run 123 --plan small.json
  python scripts/prune_old_windows_artifacts.py --apply cleanup.json

Only the verified Windows Desktop workflow ID/path can supply candidates.
The default/minimum age is three days, matching the proposed PR retention policy.
When a run omits PR links, commit associations must include its exact branch and
head repository. If not, a paginated state=all PR-by-head lookup must resolve one
unambiguous original PR; all associated PRs must still be closed. Missing evidence
preserves artifacts. These metadata reads repeat during planning, full preflight
and immediately before deletion; archives are never downloaded by this helper.
Open PR branches/SHAs, unknown associations, explicit --keep-run IDs, non-PR runs,
main builds, releases, logs, source, and branches are preserved. A plan expires in
24 hours. Applying never adds candidates and stops at the first error. GitHub has
no atomic conditional artifact DELETE: even with fresh checks, a remote state
change between the last check and DELETE remains possible. Preserve special
review/recovery builds with --keep-run. SHA-256 detects accidental manifest edits;
it is not an approval signature. Do not put this helper on a schedule.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

REPO = "oncoursemail/Star-AI-Private"
REPO_ID = 1412474221
ROOT = "repos/" + REPO
WINDOWS_WORKFLOW_ID = 380060164
WINDOWS_WORKFLOW_PATH = ".github/workflows/windows-desktop.yml"
NAMES = frozenset(("STAR-Fast-Brain-Preview", "STAR-Ultimate-Windows-Setup",
                   "STAR-Ultimate-Windows-Portable"))
SHA = re.compile(r"[0-9a-f]{40}\Z")


class Stop(RuntimeError):
    """Fail closed without exposing raw CLI output or credentials."""


class ApiError(Stop):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Preserve(Stop):
    """A candidate is not proven eligible."""


def require(condition, message):
    if not condition:
        raise Stop(message)


def integer(value, minimum=1):
    return type(value) is int and value >= minimum


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise Preserve("Missing or invalid timestamp") from None


def now_utc():
    return datetime.now(timezone.utc)


def digest(manifest):
    payload = {k: v for k, v in manifest.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


class GitHub:
    def _call(self, path, method="GET", paginate=False):
        require(path.startswith(ROOT + "/") or path == ROOT, "Endpoint outside private repository")
        require(method in ("GET", "DELETE"), "Unsupported HTTP method")
        if method == "DELETE":
            require(re.fullmatch(re.escape(ROOT) + r"/actions/artifacts/[1-9][0-9]*", path),
                    "DELETE outside exact artifact scope")
        args = ["gh", "api", "--hostname", "github.com", "--method", method,
                "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2022-11-28"]
        if paginate:
            args += ["--paginate", "--slurp"]
        args.append(path)
        try:
            result = subprocess.run(args, capture_output=True, text=True, shell=False,
                                    check=False, timeout=60)
        except FileNotFoundError:
            raise Stop("GitHub CLI is unavailable; install and authenticate gh for github.com") from None
        except subprocess.TimeoutExpired:
            raise Stop("GitHub request timed out; no retry or broader selection was attempted") from None
        if result.returncode:
            match = re.search(r"\(HTTP (\d{3})\)", result.stderr)
            status = int(match[1]) if match else None
            raise ApiError(f"GitHub {method} failed for {path} (HTTP {status or 'unknown'})", status)
        if method == "DELETE":
            require(not result.stdout.strip(), "Unexpected artifact DELETE response")
            return None
        try:
            return json.loads(result.stdout)
        except (TypeError, ValueError):
            raise Stop("GitHub returned invalid JSON") from None

    def get(self, path):
        return self._call(path)

    def pages(self, path):
        return self._call(path, paginate=True)

    def delete(self, artifact_id):
        return self._call(f"{ROOT}/actions/artifacts/{artifact_id}", "DELETE")


def collection(client, path, key=None):
    pages = client.pages(path)
    require(isinstance(pages, list) and bool(pages), "Missing paginated response")
    rows, totals = [], []
    for index, page in enumerate(pages):
        batch = page.get(key) if key and isinstance(page, dict) else page if not key else None
        require(isinstance(batch, list) and len(batch) <= 100, "Invalid collection page")
        require(index == len(pages) - 1 or len(batch) == 100, "Incomplete intermediate page")
        if key:
            total = page.get("total_count")
            require(integer(total, 0), "Missing collection total")
            totals.append(total)
        rows.extend(batch)
    require(all(isinstance(row, dict) and integer(row.get("id")) for row in rows), "Invalid collection ID")
    require(len({row["id"] for row in rows}) == len(rows), "Duplicate collection IDs; snapshot changed")
    if key:
        require(len(set(totals)) == 1 and len(rows) == totals[0], "Incomplete or changing artifact inventory")
    return rows


def repository(client):
    meta = client.get(ROOT)
    require(isinstance(meta, dict) and type(meta.get("id")) is int and meta["id"] == REPO_ID
            and meta.get("full_name") == REPO and meta.get("private") is True
            and meta.get("default_branch") == "main", "Private repository identity/default branch changed")


def open_refs(client):
    branches, shas = {"main"}, set()
    for pr in collection(client, ROOT + "/pulls?state=open&per_page=100"):
        base = pr.get("base") or {}
        base_repo = base.get("repo") if isinstance(base, dict) else None
        require(pr.get("state") == "open" and isinstance(base_repo, dict) and base_repo.get("id") == REPO_ID,
                "Invalid open PR inventory")
        head = pr.get("head") or {}
        require(isinstance(head, dict) and isinstance(head.get("ref"), str) and bool(head["ref"])
                and isinstance(head.get("sha"), str) and SHA.fullmatch(head["sha"]), "Unverifiable open PR head")
        branches.add(head["ref"])
        shas.add(head["sha"])
    return branches, shas


def artifact_snapshot(item):
    try:
        result = {key: item[key] for key in ("id", "name", "size_in_bytes", "created_at",
                                           "updated_at", "expires_at", "expired", "workflow_run")}
        run = item["workflow_run"]
        result["workflow_run"] = {key: run[key] for key in
                                  ("id", "repository_id", "head_repository_id", "head_branch", "head_sha")}
        valid = (integer(item["id"]) and item["name"] in NAMES and integer(item["size_in_bytes"], 0)
                 and item["expired"] is False and integer(run["id"])
                 and type(run["repository_id"]) is int and run["repository_id"] == REPO_ID
                 and integer(run["head_repository_id"]) and isinstance(run["head_branch"], str)
                 and bool(run["head_branch"]) and isinstance(run["head_sha"], str)
                 and SHA.fullmatch(run["head_sha"]))
        if not valid:
            raise ValueError
        for key in ("created_at", "updated_at", "expires_at"):
            timestamp(item[key])
        return result
    except (KeyError, TypeError, ValueError):
        raise Preserve("Unverified artifact identity or metadata") from None


def matching_pr_head(pr, run):
    head = pr.get("head") or {}
    repo = head.get("repo") or {}
    return (head.get("ref") == run["head_branch"] and integer(repo.get("id"))
            and repo["id"] == run["head_repository"]["id"])


def run_snapshot(client, run_id, refs, cutoff, keep):
    run = client.get(f"{ROOT}/actions/runs/{run_id}")
    try:
        result = {key: run[key] for key in ("id", "workflow_id", "path", "run_attempt", "event", "status",
                                          "conclusion", "head_branch", "head_sha", "created_at", "updated_at")}
        result["repository_id"] = run["repository"]["id"]
        result["head_repository_id"] = run["head_repository"]["id"]
        if (not integer(run["id"]) or run["id"] != run_id or run_id in keep
                or not integer(run["workflow_id"]) or run["workflow_id"] != WINDOWS_WORKFLOW_ID
                or run["path"] != WINDOWS_WORKFLOW_PATH or not integer(run["run_attempt"])
                or type(result["repository_id"]) is not int or result["repository_id"] != REPO_ID
                or not integer(result["head_repository_id"]) or run["event"] != "pull_request"
                or run["status"] != "completed" or not isinstance(run["conclusion"], str)
                or not isinstance(run["head_branch"], str) or not run["head_branch"]
                or run["head_branch"] in refs[0] or not isinstance(run["head_sha"], str)
                or not SHA.fullmatch(run["head_sha"]) or run["head_sha"] in refs[1]
                or timestamp(run["created_at"]) > cutoff or timestamp(run["updated_at"]) > cutoff):
            raise ValueError
        associated = run.get("pull_requests")
        if not isinstance(associated, list):
            raise ValueError
        fallback = not associated
        if not associated:
            associated = collection(client, f"{ROOT}/commits/{run['head_sha']}/pulls?per_page=100")
            if not any(matching_pr_head(pr, run) for pr in associated):
                owner = run["head_repository"]["owner"]["login"]
                if not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner):
                    raise ValueError
                head = quote(owner + ":" + run["head_branch"], safe="")
                matches = collection(client, f"{ROOT}/pulls?state=all&head={head}&per_page=100")
                if len(matches) != 1 or not matching_pr_head(matches[0], run):
                    raise ValueError  # A reused branch or unexpected search result is ambiguous.
                existing = next((pr for pr in associated if pr.get("number") == matches[0]["number"]), None)
                if existing is None:
                    associated.append(matches[0])
                elif existing["id"] != matches[0]["id"]:
                    raise ValueError
        if any(not isinstance(p, dict) or not integer(p.get("number"))
               or p.get("base", {}).get("repo", {}).get("id") != REPO_ID for p in associated):
            raise ValueError
        numbers = sorted({p["number"] for p in associated})
        if not numbers or len(numbers) != len(associated):
            raise ValueError
        prs = []
        for number in numbers:
            pr = client.get(f"{ROOT}/pulls/{number}")
            if (type(pr["number"]) is not int or pr["number"] != number or pr["state"] != "closed"
                    or pr["base"]["repo"]["id"] != REPO_ID or not isinstance(pr["head"]["ref"], str)
                    or not SHA.fullmatch(pr["head"]["sha"])):
                raise ValueError
            timestamp(pr["closed_at"])
            prs.append({"number": number, "state": "closed", "closed_at": pr["closed_at"],
                        "head_ref": pr["head"]["ref"], "head_sha": pr["head"]["sha"],
                        "head_repository_id": pr["head"]["repo"]["id"]})
        if fallback and sum(pr["head_ref"] == run["head_branch"]
                                and type(pr["head_repository_id"]) is int
                                and pr["head_repository_id"] == result["head_repository_id"] for pr in prs) != 1:
            raise ValueError  # Containing the commit alone does not prove the original PR.
        return result, prs
    except (AttributeError, KeyError, TypeError, ValueError):
        raise Preserve("Run is retained, active, recent, non-PR, or has unverified/active PR associations") from None


def candidate(item, run, prs, refs, cutoff, current):
    art = artifact_snapshot(item)
    source = art["workflow_run"]
    if (source["id"] != run["id"] or any(source[key] != run[key] for key in
            ("repository_id", "head_repository_id", "head_branch", "head_sha"))
            or source["head_branch"] in refs[0] or source["head_sha"] in refs[1]
            or timestamp(art["created_at"]) > cutoff or timestamp(art["updated_at"]) > cutoff
            or timestamp(art["expires_at"]) <= current):
        raise Preserve("Artifact is retained, recent, expired, or differs from its run")
    return {"artifact": art, "run": run, "pull_requests": prs}


def create_plan(client, current=None, age=3, keep=(), scope_runs=()):
    current = current or now_utc()
    require(integer(age, 3), "Minimum age must be at least three whole days")
    require(all(integer(i) for i in (*keep, *scope_runs)), "Invalid run ID")
    repository(client)
    refs = open_refs(client)
    endpoints = ([f"{ROOT}/actions/runs/{i}/artifacts?per_page=100" for i in sorted(set(scope_runs))]
                 if scope_runs else [ROOT + "/actions/artifacts?per_page=100"])
    items = [item for path in endpoints for item in collection(client, path, "artifacts")]
    require(len({item["id"] for item in items}) == len(items), "Duplicate artifacts across selected runs")
    require(all(integer(item.get("size_in_bytes"), 0) for item in items), "Invalid artifact byte count")
    cutoff, entries, reasons, cache = current - timedelta(days=age), [], Counter(), {}
    for item in items:
        if not isinstance(item.get("name"), str) or item["name"] not in NAMES:
            reasons["other artifact family"] += 1
            continue
        try:
            art = artifact_snapshot(item)
            run_id = art["workflow_run"]["id"]
            if scope_runs and run_id not in scope_runs:
                raise Stop("Artifact appeared outside the selected run inventory")
            if run_id not in cache:
                try:
                    cache[run_id] = run_snapshot(client, run_id, refs, cutoff, keep)
                except Preserve as exc:
                    cache[run_id] = exc
            if isinstance(cache[run_id], Preserve):
                raise cache[run_id]
            entries.append(candidate(item, *cache[run_id], refs, cutoff, current))
        except Preserve as exc:
            reasons[str(exc)] += 1
    entries.sort(key=lambda entry: entry["artifact"]["id"])
    result = {"schema": 1, "repository": REPO, "repository_id": REPO_ID,
              "created_at": current.isoformat(), "min_age_days": age,
              "keep_run_ids": sorted(set(keep)), "scope_run_ids": sorted(set(scope_runs)),
              "artifacts": entries, "statistics": {"listed_count": len(items),
                  "listed_bytes": sum(i["size_in_bytes"] for i in items), "candidate_count": len(entries),
                  "candidate_bytes": sum(e["artifact"]["size_in_bytes"] for e in entries),
                  "preserved_count": len(items) - len(entries),
                  "preserved_bytes": sum(i["size_in_bytes"] for i in items)
                      - sum(e["artifact"]["size_in_bytes"] for e in entries),
                  "preserved_reasons": dict(reasons)}}
    result["sha256"] = digest(result)
    return result


def validate_plan(plan, current):
    require(isinstance(plan, dict) and type(plan.get("schema")) is int and plan["schema"] == 1,
            "Unknown manifest schema")
    require(plan.get("repository") == REPO and type(plan.get("repository_id")) is int
            and plan["repository_id"] == REPO_ID, "Manifest repository mismatch")
    require(plan.get("sha256") == digest(plan), "Manifest SHA-256 mismatch; recreate the plan")
    elapsed = current - timestamp(plan.get("created_at"))
    require(timedelta(0) <= elapsed <= timedelta(hours=24), "Manifest is expired or future-dated")
    require(integer(plan.get("min_age_days"), 3), "Manifest age violates three-day minimum")
    for key in ("keep_run_ids", "scope_run_ids"):
        values = plan.get(key)
        require(isinstance(values, list) and all(integer(i) for i in values)
                and len(set(values)) == len(values), "Invalid manifest run IDs")
    entries = plan.get("artifacts")
    require(isinstance(entries, list), "Missing manifest artifacts")
    ids = []
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == {"artifact", "run", "pull_requests"},
                "Invalid manifest candidate")
        art = artifact_snapshot(entry["artifact"])
        run_id = art["workflow_run"]["id"]
        require(run_id not in plan["keep_run_ids"] and (not plan["scope_run_ids"]
                or run_id in plan["scope_run_ids"]), "Candidate violates retained/scoped runs")
        require(isinstance(entry["run"], dict) and isinstance(entry["pull_requests"], list), "Missing evidence")
        require(type(entry["run"].get("workflow_id")) is int
                and entry["run"]["workflow_id"] == WINDOWS_WORKFLOW_ID
                and entry["run"].get("path") == WINDOWS_WORKFLOW_PATH,
                "Manifest does not identify the verified Windows workflow; recreate plan")
        ids.append(art["id"])
    require(len(set(ids)) == len(ids), "Duplicate manifest artifact IDs")
    stats = plan.get("statistics", {})
    require(stats.get("candidate_count") == len(entries) and stats.get("candidate_bytes") ==
            sum(e["artifact"]["size_in_bytes"] for e in entries), "Manifest statistics mismatch")


def verify_entries(client, entries, plan, current, refs):
    cutoff = current - timedelta(days=plan["min_age_days"])
    runs = {}
    for entry in entries:
        art_id, run_id = entry["artifact"]["id"], entry["artifact"]["workflow_run"]["id"]
        if run_id not in runs:
            runs[run_id] = run_snapshot(client, run_id, refs, cutoff, plan["keep_run_ids"])
        fresh = candidate(client.get(f"{ROOT}/actions/artifacts/{art_id}"),
                          *runs[run_id], refs, cutoff, current)
        require(fresh == entry, f"Artifact {art_id} or its run/PR evidence changed; recreate plan")


def apply_plan(client, plan, emit, clock=now_utc):
    validate_plan(plan, clock())
    repository(client)
    # Check every exact candidate before the first destructive call; 404 here is an error.
    verify_entries(client, plan["artifacts"], plan, clock(), open_refs(client))
    emit({"status": "preflight_passed", "manifest_sha256": plan["sha256"],
          "candidate_count": len(plan["artifacts"])})
    for entry in plan["artifacts"]:
        identifier = entry["artifact"]["id"]
        try:
            validate_plan(plan, clock())
            repository(client)
            # Check immediately before each DELETE, including reopened/new PRs.
            verify_entries(client, [entry], plan, clock(), open_refs(client))
            client.delete(identifier)
            emit({"artifact_id": identifier, "status": "delete_acknowledged",
                  "run_id": entry["run"]["id"], "bytes": entry["artifact"]["size_in_bytes"],
                  "manifest_sha256": plan["sha256"]})
            repository(client)  # Lost/private-repo permission must not masquerade as absence.
            try:
                client.get(f"{ROOT}/actions/artifacts/{identifier}")
            except ApiError as exc:
                if exc.status != 404:
                    raise
                # Confirm artifact-list access still works before accepting 404 as removal.
                remaining = collection(client, f"{ROOT}/actions/runs/{entry['run']['id']}/artifacts?per_page=100", "artifacts")
                require(all(a["id"] != identifier for a in remaining), "Deleted artifact still listed")
            else:
                raise Stop("Artifact still exists after DELETE; stopping")
        except Stop as exc:
            emit({"artifact_id": identifier, "status": "stopped", "error": str(exc)})
            raise
        emit({"artifact_id": identifier, "status": "deleted_and_absence_verified",
              "bytes": entry["artifact"]["size_in_bytes"]})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", type=Path, help="Write a read-only JSON plan; otherwise print it")
    mode.add_argument("--apply", type=Path, help="Apply only this exact, fresh manifest")
    parser.add_argument("--min-age-days", type=int, default=3)
    parser.add_argument("--keep-run", type=int, action="append", default=[])
    parser.add_argument("--only-run", type=int, action="append", default=[], help="Narrow planning to fully enumerated run IDs")
    args = parser.parse_args(argv)
    try:
        if args.apply:
            require(not args.keep_run and not args.only_run and args.min_age_days == 3,
                    "Apply reads selection and exclusions only from the manifest")
            with args.apply.open(encoding="utf-8") as handle:
                plan = json.load(handle)
            apply_plan(GitHub(), plan, lambda event: print(json.dumps(event), flush=True))
        else:
            plan = create_plan(GitHub(), age=args.min_age_days, keep=args.keep_run, scope_runs=args.only_run)
            output = json.dumps(plan, indent=2, ensure_ascii=True) + "\n"
            if args.plan:
                descriptor = os.open(args.plan, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(output)
                print(json.dumps({"plan": str(args.plan), "sha256": plan["sha256"], **plan["statistics"]}))
            else:
                print(output, end="")
    except (Stop, OSError, ValueError, KeyError, TypeError) as exc:
        message = str(exc) if isinstance(exc, Stop) else "Invalid manifest or local file operation failed"
        print(json.dumps({"status": "stopped", "error": message}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
