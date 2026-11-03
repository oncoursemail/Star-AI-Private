"""Litha picks her own work: each run builds a queue from what is broken or asked of her, then does the top of it.

Sources, in every repo of repos.json with mode "merge" (STAR's home repo + the clones listed there):
(a) the base branch's head commit failed CI (star/next, Studio main)            -> "ci-repair", score 100
(b) open issues labelled `litha:ready` (the owner or a lead hands it to her) or
    `litha:found` (her playtests found it)                                       -> "issue", score 40 (+20 when it
    names a failing test `tests/...py[::name]`, +5 for litha:found)
(c) her own failures in ~/.star/pr-fixer/fixes.jsonl worth another try: the PR is still open at the same head (so
    pr_fixer would never look again) and its base moved since, or the attempt ended in an error -> "retry", score
    30 minus a point per day of age
Ranked by score (home repo first on ties). Not queued: what an open PR from a litha/ branch already covers (her
litha/fix-<n>, litha/merge-<n> branches; litha/auto-* PRs carry `litha-task: <key>` in their body), and tasks she
already attempted (~/.star/litha-autonomy/state.json).

Actions:
- ci-repair: a fresh worktree at the failing base commit, the same repair machinery as pr_fixer (pytest repair,
  ruff, pyright, React; rust_fix.repair when the log ran cargo), Claude as second opinion (ask_claude_hard), the same
  checks; when they pass: commit, push HER branch litha/auto-<n>-<yyyymmdd>, open a PR into the base. She never
  pushes to a base branch; pr_merger's normal gates decide the merge.
- issue: one that names a failing test is repaired the same way (PR says "Fixes #n"); any other gets a plan comment
  from her local model (triage only, for now).
- retry: pr_fixer.mark(key, "retry:<base sha>") so pr_fixer's next run takes the PR again (at most 2 per PR).
Limits: 1 new PR per run and 3 per day, 2 issue comments and 3 retries per run.

Modes: dry (default) builds the queue, writes queue.json and says what it would do: read-only gh calls, no model,
no git. --local also does the top PR task's local work (worktree, repair, tests) and the plans, without pushing,
commenting or re-queueing. --apply, or the file ~/.star/litha-autonomy/APPLY, does everything (--dry wins over both).
Off switch: ~/.star/litha-autonomy/OFF.

    python -m litha.autonomy [--local | --apply | --dry] [--python PY]
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import time

from litha import claude, pr_fixer as F, pr_merger as M, rust_fix
from litha.pr_merger import gh, latest_runs

HOME = Path.home() / ".star" / "litha-autonomy"
OFF, APPLY = HOME / "OFF", HOME / "APPLY"
STATE, QUEUE, LOG = HOME / "state.json", HOME / "queue.json", HOME / "runs.jsonl"
LABELS = ("litha:ready", "litha:found")
PR_PER_RUN, PR_PER_DAY, COMMENTS_PER_RUN, RETRIES_PER_RUN, RETRIES_PER_PR = 1, 3, 2, 3, 2
RETRY_DAYS = 7                                  # an older failure is history, not a retry
MARK = "litha-task: "
TASK_MARK = re.compile(r"litha-task: (\S+)")
OWN = re.compile(r"^litha/(?:fix|merge)-(\d+)-")
TEST_REF = re.compile(r"\b(tests/[\w/.-]+\.py(?:::[\w\[\].-]+)?)")
BAD = ("failure", "timed_out")
TRANSIENT = ("fetch failed", "worktree add failed", "no local clone")   # not an attempt: the same key next run
PLAN_PROMPT = """You are Litha, an engineer on the owner's repository {repo}. This issue was handed to you:
#{number}: {title}
{body}

Write a short, concrete plan for it: what to change, in which files, how to check it. Do not invent file names you
cannot infer from the issue; say "find where ..." instead. Answer only JSON:
{{"summary": "<one sentence>", "steps": ["<step>", ...], "files": ["<path or area>"], "check": "<how to verify>",
"size": "small" or "medium" or "large"}}"""


def now() -> float:
    return time.time()


def load_state() -> dict:
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    for k, v in (("n", 0), ("opened", []), ("done", {}), ("retries", {})):
        state.setdefault(k, v)
    return state


def save_state(state: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    week = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    state["opened"] = [o for o in state["opened"] if o.get("day", "") >= week]
    F.write_atomic(STATE, json.dumps(state, indent=1))


def opened_today(state: dict) -> int:
    return sum(o.get("day") == dt.date.today().isoformat() for o in state["opened"])


def entries() -> list[dict]:
    """The repos she works in: mode merge. The first is STAR's home (its clone and worktrees are pr_fixer's)."""
    out = []
    for i, e in enumerate(json.loads(M.REPOS.read_text(encoding="utf-8"))["repos"]):
        if e.get("mode") != "merge":
            continue
        if i == 0:
            clone, work = F.HOME_CLONE, F.WORK
        else:
            clone = Path(e["clone"]).expanduser() if e.get("clone") else None
            work = Path(e.get("worktrees") or clone.parent / f"{clone.name}-worktrees").expanduser() if clone else None
        out.append({"repo": e["repo"], "base": e.get("base", "main"), "home": i == 0, "clone": clone, "work": work})
    return out


@contextmanager
def at_repo(entry: dict):
    """pr_fixer's helpers read the repo from module globals (as its --others loop sets them): set, then restore."""
    saved = (F.REPO, F.BASE, F.CLONE, F.WORK, M.REPO, M.BASE)
    F.REPO = M.REPO = entry["repo"]
    F.BASE = M.BASE = entry["base"]
    F.CLONE, F.WORK = entry["clone"] or F.CLONE, entry["work"] or F.WORK
    try:
        yield
    finally:
        F.REPO, F.BASE, F.CLONE, F.WORK, M.REPO, M.BASE = saved


# ---------------------------------------------------------------- the queue (read-only gh calls only)

def base_head(repo: str, base: str) -> dict:
    data = json.loads(gh("api", f"repos/{repo}/commits/{base}"))
    return {"sha": data["sha"], "date": data["commit"]["committer"]["date"]}


def ci_task(entry: dict, head: dict) -> dict | None:
    runs = latest_runs(json.loads(gh("api", f"repos/{entry['repo']}/commits/{head['sha']}/check-runs?per_page=100"))
                       .get("check_runs", []))
    if not runs or any(c.get("status") != "completed" for c in runs):    # still running: next run decides
        return None
    bad = sorted({c["name"] for c in runs if (c.get("conclusion") or "") in BAD})
    if not bad:
        return None
    return {"key": f"ci:{entry['repo']}:{head['sha']}", "kind": "ci-repair", "repo": entry["repo"],
            "base": entry["base"], "sha": head["sha"], "checks": bad, "score": 100,
            "why": f"{entry['base']} head {head['sha'][:8]} fails: {', '.join(bad)}"[:200]}


def issue_tasks(entry: dict) -> list[dict]:
    found: dict[int, dict] = {}
    for label in LABELS:
        for it in json.loads(gh("issue", "list", "--repo", entry["repo"], "--state", "open", "--label", label,
                                "--limit", "50", "--json", "number,title,body,labels")):
            found.setdefault(it["number"], it)
    out = []
    for n, it in sorted(found.items()):
        names = {lb.get("name") for lb in it.get("labels") or []}
        test = TEST_REF.search(f"{it.get('title', '')}\n{it.get('body') or ''}")
        out.append({"key": f"issue:{entry['repo']}#{n}", "kind": "issue", "repo": entry["repo"], "base": entry["base"],
                    "number": n, "title": it.get("title", ""), "body": (it.get("body") or "")[:3000],
                    "test": test.group(1) if test else "",
                    "score": 40 + (20 if test else 0) + (5 if "litha:found" in names else 0),
                    "why": f"#{n} {it.get('title', '')[:80]} ({', '.join(sorted(names & set(LABELS)))})"
                           + (f"; names {test.group(1)}" if test else "")})
    return out


def fix_rows(path: Path | None = None) -> list[dict]:
    rows = []
    try:
        for line in (path or F.LOG).read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return rows


def _ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def retry_tasks(entry: dict, prs: list[dict], head: dict | None, tried: dict, state: dict,
                rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(tasks, skipped) from her failed attempts on this repo's still-open PRs."""
    repo, latest = entry["repo"], {}
    for r in rows:                                                   # the last attempt per PR wins
        if (r.get("repo") or (repo if entry["home"] else "")) == repo and isinstance(r.get("pr"), int):   # no repo: home
            latest[r["pr"]] = r
    by_n = {p["number"]: p for p in prs}
    busy = {int(m.group(1)) for p in prs for m in [OWN.match(p.get("headRefName") or "")] if m}
    tasks, skipped = [], []
    for n, r in sorted(latest.items()):
        pr = by_n.get(n)
        if r.get("result") not in ("failed", "error") or not pr or now() - r.get("ts", 0) > RETRY_DAYS * 86400:
            continue
        key, done = (str(n) if entry["home"] else f"{repo}#{n}"), state["retries"].get(f"{repo}#{n}", [])
        moved = bool(head) and _ts(head["date"]) > r.get("ts", 0)
        why = ("" if pr.get("baseRefName") == entry["base"] else "PR is into another base")
        why = why or ("her own branch" if str(pr.get("headRefName", "")).startswith("litha/") else "")
        why = why or ("an open litha/ PR already covers it" if n in busy else "")
        why = why or ("the head changed: pr_fixer takes it on its own" if tried.get(key) != pr.get("headRefOid") else "")
        why = why or ("conflict is gone" if r.get("kind") == "merge" and pr.get("mergeable") == "MERGEABLE" else "")
        why = why or ("" if moved or r.get("result") == "error" else "nothing changed since (base did not move)")
        why = why or (f"retried {len(done)} times already" if len(done) >= RETRIES_PER_PR else "")
        why = why or ("already retried on this base" if head and head["sha"] in done else "")
        if why:
            skipped.append({"key": f"retry:{repo}#{n}", "why": why})
            continue
        age = (now() - r.get("ts", 0)) / 86400
        tasks.append({"key": f"retry:{repo}#{n}:{head['sha'] if head else 'error'}", "kind": "retry", "repo": repo,
                      "base": entry["base"], "number": n, "tried_key": key, "sha": head["sha"] if head else "",
                      "score": 30 - min(int(age), 7),
                      "why": f"#{n} {r.get('result')} {age:.1f} d ago ({str(r.get('why', ''))[:90]}); "
                             + ("base moved since" if moved else "it was an error")})
    return tasks, skipped


def build_queue(state: dict, ents: list[dict] | None = None) -> dict:
    tasks, skipped, notes = [], [], []
    tried = json.loads(F.STATE.read_text(encoding="utf-8")) if F.STATE.exists() else {}
    rows, ents = fix_rows(), ents if ents is not None else entries()
    for entry in ents:
        repo = entry["repo"]
        head = prs = None
        try:
            head = base_head(repo, entry["base"])
        except (RuntimeError, KeyError, ValueError) as e:
            notes.append(f"{repo}: no {entry['base']} head ({str(e)[:120]})")
        try:
            prs = json.loads(gh("pr", "list", "--repo", repo, "--state", "open", "--limit", "200", "--json",
                                "number,headRefName,headRefOid,baseRefName,mergeable,body"))
        except (RuntimeError, ValueError) as e:
            notes.append(f"{repo}: open PRs unreadable ({str(e)[:120]}): nothing queued here")
            continue
        busy = {m.group(1) for p in prs if str(p.get("headRefName", "")).startswith("litha/auto-")
                for m in [TASK_MARK.search(p.get("body") or "")] if m}
        found: list[dict] = []
        if head:
            try:
                t = ci_task(entry, head)
                found += [t] if t else []
            except (RuntimeError, ValueError) as e:
                notes.append(f"{repo}: checks unreadable ({str(e)[:120]})")
        try:
            found += issue_tasks(entry)
        except (RuntimeError, ValueError) as e:
            notes.append(f"{repo}: issues unreadable ({str(e)[:120]})")
        got, skip = retry_tasks(entry, prs, head, tried, state, rows)
        found += got
        skipped += skip
        for t in found:
            if t["key"] in busy or (t["kind"] == "ci-repair" and any(b.startswith(f"ci:{repo}:") for b in busy)):
                skipped.append({"key": t["key"], "why": "an open litha/auto PR already works on it"})
            elif t["key"] in state["done"]:
                skipped.append({"key": t["key"], "why": f"attempted {state['done'][t['key']].get('day', '')}: "
                                                         f"{state['done'][t['key']].get('result', '')}"})
            else:
                tasks.append({**t, "home": entry["home"]})
    home = {e["repo"] for e in ents if e["home"]}
    tasks.sort(key=lambda t: (-t["score"], t["repo"] not in home, t["key"]))
    return {"built": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "tasks": tasks,
            "skipped": skipped, "notes": notes}


# ---------------------------------------------------------------- actions

def _second(attempt):
    """Her local model first; Claude (paid, capped) once when that fails, the same checks deciding."""
    ok, why = attempt(F.ask)
    if not ok and claude.ready():
        ok, why = attempt(F.ask_claude_hard)
        why += " (with Claude)" if ok else ""
    return ok, why


def _repair(tree: Path, task: dict, entry: dict, python: str, asker) -> dict:
    """Run the matching repair in `tree`. {"ok", "why", "tests"} or {"result": skip/failed/flaky, "why"}."""
    title = f"{entry['base']} CI" if task["kind"] == "ci-repair" else f"#{task['number']}: {task['title']}"

    def two(fn):                                     # asker given (tests): only it; else local then Claude
        return fn(asker) if asker else _second(fn)
    if task["kind"] == "issue":
        tests = [task["test"]]
        passes, out = F.run_tests(tree, tests, python)
        if passes:
            return {"result": "skip", "why": f"{task['test']} passes on {entry['base']} {task['sha'][:8]}"}
        fails = F.failures(out) or [{"test": task["test"], "section": out[-2500:]}]
        ok, why = two(lambda a: F.repair(tree, title, fails, out, tests, python, a)[:2])
        return {"ok": ok, "why": why, "tests": tests}
    log = F.failed_logs(task["sha"])
    if not log.strip():
        return {"result": "skip", "why": "the failed logs are gone (expired): nothing to repair from"}
    if rust_fix.checks(log) and (rust_fix.errors(log) or "Diff in " in log):
        ok, why = two(lambda a: rust_fix.repair(tree, entry["repo"], title, log, a))
        return {"ok": ok, "why": why, "tests": ["the cargo checks of the failed CI log"]}
    fails = F.failures(log)
    if fails:
        tests = sorted({f["test"].split("::")[0] for f in fails})
        passes, out = F.run_tests(tree, tests, python)
        if passes:
            return {"result": "flaky", "why": f"{', '.join(tests)} pass locally on {task['sha'][:8]} (flaky or CI-only)"}
        diff = F.sh(["git", "show", "--format=", "HEAD"], cwd=tree).stdout       # the newest base commit
        ok, why = two(lambda a: F.repair(tree, title, fails, out, tests, python, a, diff)[:2])
        return {"ok": ok, "why": why, "tests": tests}
    for found, fn, tests in ((F.RUFF_CI.search(log), lambda a: F.fix_lint(tree, python, a), ["ruff check"]),
                             (F.TYPE_CI.search(log), lambda a: F.fix_types(tree, python, a), ["pyright gate"]),
                             (F.REACT_CI.search(log), lambda a: F.fix_frontend(tree, a, title=title), ["tsc", "vitest"])):
        if found:
            ok, why, rounds = fn(asker or F.ask)
            if rounds == 0:
                return {"result": "skip", "why": f"cannot reproduce here: {why}"}
            if not ok and not asker and claude.ready():
                ok, why, _ = fn(F.ask_claude_hard)
            return {"ok": ok, "why": why, "tests": tests}
    return {"result": "skip", "why": "no test, lint, type, React or cargo failure in the failed logs (infrastructure?)"}


def work_pr(task: dict, entry: dict, python: str, state: dict, push: bool, asker=None) -> dict:
    """ci-repair, or an issue naming a failing test: fresh worktree at the base head, repair, the same checks, and
    (push) her branch + a PR into the base."""
    n = state["n"] + 1
    branch = f"litha/auto-{n}-{dt.date.today():%Y%m%d}"
    row = {"key": task["key"], "kind": task["kind"], "repo": entry["repo"], "branch": branch}
    if not entry["clone"] or not (Path(entry["clone"]) / ".git").exists():
        return {**row, "result": "skip", "why": f"no local clone of {entry['repo']}"}
    with at_repo(entry):
        clone, tree = F.CLONE, F.WORK / f"litha-auto-{n}"
        git = ["git", "-C", str(clone)]
        if tree.exists():
            F.sh([*git, "worktree", "remove", "--force", str(tree)])
        F.sh([*git, "branch", "-D", branch])                       # a local leftover of an unpushed run
        got = F.sh([*git, "fetch", "-q", "origin", entry["base"]])
        if got.returncode:
            return {**row, "result": "skip", "why": "fetch failed: " + got.stderr[-200:]}
        if task["kind"] == "issue":
            task = {**task, "sha": F.sh([*git, "rev-parse", "FETCH_HEAD"]).stdout.strip()}
        if F.sh([*git, "worktree", "add", "-q", "-b", branch, str(tree), task["sha"]]).returncode:
            return {**row, "result": "skip", "why": f"worktree add failed at {task['sha'][:8]}"}
        pushed = False
        try:
            got = _repair(tree, task, entry, python, asker)
            if "result" in got:
                return {**row, **got}
            row.update(why=str(got["why"])[:300], tests=got["tests"])
            if not got["ok"]:
                return {**row, "result": "failed"}
            changed = [ln[3:].strip() for ln in F.sh(["git", "status", "--porcelain"], cwd=tree).stdout.splitlines()]
            if not changed:
                return {**row, "result": "failed", "why": "the checks pass here without a change (CI-only failure?)"}
            row["files"] = changed
            if not push:
                return {**row, "result": "fixed-local"}
            pushed = _ship(tree, task, entry, branch, row, state, n)
            return row
        finally:
            F.sh([*git, "worktree", "remove", "--force", str(tree)])
            if not pushed:
                F.sh([*git, "branch", "-D", branch])


def _ship(tree: Path, task: dict, entry: dict, branch: str, row: dict, state: dict, n: int) -> bool:
    """Commit, push HER branch (never a base, never force), open the PR. True once the branch is pushed."""
    assert branch.startswith("litha/auto-") and branch != entry["base"]
    subject = (f"[litha] repair {entry['base']} CI ({', '.join(task.get('checks', []))[:60]})"
               if task["kind"] == "ci-repair" else f"[litha] fix #{task['number']}: {task['title'][:60]}")
    msg = f"{subject}\n\n{row['why']}\nChecks now passing locally: {', '.join(row['tests'])}"
    if entry["home"]:                                              # STAR's repo: star commit (secret checks)
        c = F.sh([str(F.CLONE.parent / "star.cmd"), "commit", "--owner", "claude", "--worktree",
                  str(tree.relative_to(F.CLONE.parent)), "--paths", *row["files"], "-m", msg], cwd=F.CLONE.parent)
    else:
        F.sh(["git", "add", "-A"], cwd=tree)
        c = F.sh(["git", *F.IDENTITY, "commit", "-q", "--no-verify", "-m", msg], cwd=tree)
    if c.returncode:
        row.update(result="failed", why="commit refused: " + (c.stdout + c.stderr)[-300:])
        return False
    if F.sh(["git", "push", "-q", "origin", f"HEAD:refs/heads/{branch}"], cwd=tree).returncode:
        row.update(result="failed", why="push failed (the branch exists already?)")
        return False
    state["n"] = n                                                 # the name is used now, whatever happens next
    what = (f"The head of `{entry['base']}` ({task['sha'][:8]}) failed CI: {', '.join(task.get('checks', []))}."
            if task["kind"] == "ci-repair" else f"Fixes #{task['number']} ({task['test']} failed on `{entry['base']}`).")
    body = (f"Litha picked this up herself (litha/autonomy.py).\n\n{what}\nCause: {row['why']}\n"
            f"Checks passing locally: {', '.join(row['tests'])}.\nIt merges only through her merger's normal gates "
            f"(green CI on this head, review).\n\n<!-- {MARK}{task['key']} -->")
    try:
        row["pr_url"] = gh("pr", "create", "--repo", entry["repo"], "--base", entry["base"], "--head", branch,
                           "--title", subject.removeprefix("[litha] ")[:90], "--body", body).strip()
        row["result"] = "opened"
        state["opened"].append({"day": dt.date.today().isoformat(), "key": task["key"], "url": row["pr_url"]})
    except RuntimeError as e:
        row.update(result="failed", why=row["why"] + f" (PR create: {str(e)[:150]})")
    return True


def triage(task: dict, push: bool, asker=None) -> dict:
    """A plan comment on the issue from her local model (no Claude: a plan is cheap to get wrong, a comment is not
    code). push=False: the plan is only printed."""
    row = {"key": task["key"], "kind": "issue", "repo": task["repo"], "number": task["number"]}
    try:
        plan = json.loads((asker or F.ask)(PLAN_PROMPT.format(repo=task["repo"], number=task["number"],
                                                              title=task["title"], body=task["body"][:2500])))
        steps = [str(s)[:300] for s in plan.get("steps") or []][:8]
    except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        return {**row, "result": "failed", "why": f"no usable plan: {str(e)[:150]}"}
    if not steps:
        return {**row, "result": "failed", "why": "her plan had no steps"}
    body = (f"Litha's plan (triage; she picked this issue up from its label):\n\n{str(plan.get('summary', ''))[:300]}\n\n"
            + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
            + f"\n\nFiles: {', '.join(map(str, plan.get('files') or []))[:300] or 'to find'}"
            + f"\nCheck: {str(plan.get('check', ''))[:300]}\nSize: {plan.get('size', '?')}\n\n<!-- {MARK}{task['key']} -->")
    row["plan"] = body
    if not push:
        return {**row, "result": "planned-local"}
    try:
        gh("issue", "comment", str(task["number"]), "--repo", task["repo"], "--body", body)
    except RuntimeError as e:
        return {**row, "result": "failed", "why": f"comment refused: {str(e)[:150]}"}
    return {**row, "result": "commented"}


def requeue(task: dict, state: dict, push: bool) -> dict:
    row = {"key": task["key"], "kind": "retry", "repo": task["repo"], "number": task["number"]}
    if not push:
        return {**row, "result": "would-requeue"}
    F.mark(task["tried_key"], f"retry:{task['sha'][:12] or 'error'}")     # pr_fixer's own writer, its own lock
    state["retries"].setdefault(f"{task['repo']}#{task['number']}", []).append(task["sha"] or "error")
    return {**row, "result": "requeued"}


def describe(task: dict, state: dict) -> str:
    if task["kind"] == "retry":
        return f"re-queue #{task['number']} for pr_fixer (tried.json via pr_fixer.mark)"
    if task["kind"] == "issue" and not task["test"]:
        return f"comment a plan on #{task['number']}"
    at = task["sha"][:8] if task["kind"] == "ci-repair" else f"{task['base']} head"
    return (f"repair in a fresh worktree at {at} on litha/auto-{state['n'] + 1}-{dt.date.today():%Y%m%d}, run "
            f"{task.get('test') or 'the failed checks'}, open a PR into {task['base']} if they pass")


def run(mode: str, python: str, ents: list[dict] | None = None, asker=None) -> dict:
    """mode: dry | local | apply. Returns the run's summary (also appended to runs.jsonl)."""
    HOME.mkdir(parents=True, exist_ok=True)
    state = load_state()
    queue = build_queue(state, ents)
    F.write_atomic(QUEUE, json.dumps(queue, indent=1))
    by_repo = {e["repo"]: e for e in (ents if ents is not None else entries())}
    prs_left = max(0, min(PR_PER_RUN, PR_PER_DAY - opened_today(state)))
    comments_left, retries_left, acted = COMMENTS_PER_RUN, RETRIES_PER_RUN, []
    push = mode == "apply"
    for task in queue["tasks"]:
        needs_pr = task["kind"] == "ci-repair" or (task["kind"] == "issue" and task["test"] and task["home"])
        if needs_pr and prs_left <= 0:
            acted.append({"key": task["key"], "result": "limit", "why": f"{PR_PER_RUN} PR per run, {PR_PER_DAY} a day"})
            continue
        if (task["kind"] == "issue" and not needs_pr and comments_left <= 0) or                 (task["kind"] == "retry" and retries_left <= 0):
            continue
        if mode == "dry":
            row = {"key": task["key"], "result": "would", "why": describe(task, state)}
        elif needs_pr:
            row = work_pr(task, by_repo[task["repo"]], python, state, push, asker)
        elif task["kind"] == "issue":
            row = triage(task, push, asker)
        else:
            row = requeue(task, state, push)
        prs_left -= bool(needs_pr)
        comments_left -= task["kind"] == "issue" and not needs_pr
        retries_left -= task["kind"] == "retry"
        if push and task["kind"] != "retry" and not str(row.get("why", "")).startswith(TRANSIENT):
            state["done"][task["key"]] = {"day": dt.date.today().isoformat(), "result": row.get("result", "")}
        acted.append(row)
    if push:
        save_state(state)
    summary = {"ts": round(now()), "mode": mode, "tasks": len(queue["tasks"]), "skipped": len(queue["skipped"]),
               "notes": queue["notes"], "acted": [{k: v for k, v in r.items() if k != "plan"} for r in acted]}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")
    return {**summary, "queue": queue, "rows": acted}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.autonomy")
    ap.add_argument("--apply", action="store_true", help="push, open PRs, comment, re-queue (or the APPLY file)")
    ap.add_argument("--local", action="store_true", help="do the local work (repair, tests, plans), push nothing")
    ap.add_argument("--dry", action="store_true", help="only the queue, whatever --apply or the APPLY file say")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)
    if OFF.exists():
        print(f"autonomy: off ({OFF})", flush=True)
        return 0
    mode = "dry" if a.dry else "apply" if a.apply or APPLY.exists() else "local" if a.local else "dry"
    HOME.mkdir(parents=True, exist_ok=True)
    lock = HOME / "run.lock"
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        if now() - lock.stat().st_mtime < 7200:
            print("autonomy: another run is busy", flush=True)
            return 0
        lock.touch()                                                  # a run that died over 2 h ago
    try:
        out = run(mode, a.python)
    finally:
        lock.unlink(missing_ok=True)
    print(f"autonomy ({mode}): {out['tasks']} task(s), {out['skipped']} skipped", flush=True)
    for note in out["notes"]:
        print(f"  note: {note}", flush=True)
    for t in out["queue"]["tasks"]:
        print(f"  [{t['score']:3}] {t['kind']:9} {t['why']}", flush=True)
    for r in out["rows"]:
        print("  -> " + json.dumps({k: v for k, v in r.items() if k != "plan"}), flush=True)
        if r.get("plan"):
            print(r["plan"], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
