"""Read-only views of Litha's state files for her face. Every reader takes the ~/.star folder as `root` (tests pass a
temp folder), reads only the tail of the big logs, and caches the parsed result by (path, mtime, size)."""
from __future__ import annotations

import collections
import datetime
import json
import os
from pathlib import Path
import re
import time
from typing import Any

ROOT = Path.home() / ".star"
REPOS_JSON = Path(__file__).resolve().parent.parent / "repos.json"
HOME_REPO = "oncoursemail/Star-AI-Project"                  # rows logged before "repo" was written are this repo's
CAPS = {"total": 300.0, "day": 30.0}                       # same defaults as litha.claude.CAPS
PR_DAYS = 7                                                 # PRs shown: those she decided on in the last week

_cache: dict[tuple, object] = {}

# never show a key, token or private address in a page, whatever a log line happens to hold
_SECRET = re.compile(r"(sk-ant-[\w-]+|gh[pousr]_\w{20,}|github_pat_\w+|Bearer\s+\S+|token[=:]\s*\S+|"
                     r"\b(?:\d{1,3}\.){3}\d{1,3}\b|[\w.-]+@[\w-]+\.[\w.]+)", re.I)


def redact(text: str) -> str:
    return _SECRET.sub("[hidden]", text)


def _stamp(path: Path):
    try:
        s = path.stat()
        return s.st_mtime_ns, s.st_size
    except OSError:
        return None


def cached(path: Path, parse, *extra) -> Any:
    """parse(path) once per change of the file (mtime + size); None stamp = missing file, parsed too (cheap)."""
    key = (str(path), parse.__name__, _stamp(path), *extra)
    if key not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = parse(path)
    return _cache[key]


def tail_bytes(path: Path, n: int) -> bytes:
    """The last n bytes of a file, starting at a whole line ("" when missing)."""
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - n))
            data = f.read()
    except OSError:
        return b""
    if size > n:
        data = data.split(b"\n", 1)[1] if b"\n" in data else b""
    return data


def jsonl(data: bytes) -> list[dict]:
    rows = []
    for line in data.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ---- now: her loop, from run.log --------------------------------------------------------------------------------
_STAMP = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}) +(\d{1,2}):(\d{2}):(\d{2})(?:\.\d+)? +(start|end rc=(-?\d+)|step ([^(]+?) "
                    r"\(previous rc=(-?\d+)\))")
_ERR = re.compile(r"Traceback|\b\w+Error\b:|^error:", re.I)


def parse_loop(lines: list[str]) -> dict:
    """Her 10-minute loop as written by pr_merger_run.cmd: when the last run started / ended, whether one is running,
    its current step, steps that ended with a non-zero rc, and error lines inside the last run."""
    last_start = last_end = None
    end_rc = None
    step = None
    bad_steps: list[str] = []
    errors: list[str] = []
    prev_step = "self_update"
    for line in lines:
        m = _STAMP.search(line)
        if not m:
            if last_start is not None and _ERR.search(line):
                errors.append(redact(line.strip())[:240])
            continue
        mo, d, y, hh, mm, ss = (int(x) for x in m.groups()[:6])
        try:
            ts = time.mktime((y, mo, d, hh, mm, ss, 0, 0, -1))
        except (OverflowError, ValueError):
            continue
        kind = m.group(7)
        if kind == "start":
            last_start, last_end, end_rc, step, bad_steps, errors, prev_step = ts, None, None, None, [], [], "self_update"
        elif kind.startswith("end"):
            last_end, end_rc = ts, int(m.group(8))
        else:
            if int(m.group(10)) != 0:
                bad_steps.append(f"{prev_step} rc={m.group(10)}")
            step = prev_step = m.group(9)
    running = last_start is not None and last_end is None
    return {"last_start": last_start, "last_end": last_end, "end_rc": end_rc, "running": running,
            "step": step if running else None, "bad_steps": bad_steps, "errors": errors[-8:],
            "seconds": round(last_end - last_start) if last_start and last_end else None}


def _loop(path: Path) -> dict:
    return parse_loop(tail_bytes(path, 96_000).decode("utf-8", "replace").splitlines())


def now(root: Path = ROOT, at: float | None = None) -> dict:
    at = time.time() if at is None else at
    loop = cached(root / "pr-merger" / "run.log", _loop)
    health = read_json(root / "litha" / "health.json", {}) or {}
    out = dict(loop)
    out["since_start_min"] = round((at - loop["last_start"]) / 60, 1) if loop["last_start"] else None
    out["stuck"] = bool(loop["running"] and out["since_start_min"] and out["since_start_min"] > 45)
    out["late"] = bool(loop["last_start"] and not loop["running"] and at - loop["last_start"] > 25 * 60)
    out["health"] = {"ok": health.get("ok"), "at": health.get("at"),
                     "problems": [redact(str(p))[:300] for p in health.get("problems", [])][:8],
                     "info": [redact(str(p))[:200] for p in health.get("info", [])][:8]}
    out["controls"] = control_state(root)
    return out


def control_state(root: Path = ROOT) -> dict:
    paused = read_json(root / "pr-merger" / "PAUSED", None) if (root / "pr-merger" / "PAUSED").exists() else None
    return {"paused": (root / "pr-merger" / "PAUSED").exists(),
            "paused_info": paused if isinstance(paused, dict) else {},
            "off": (root / "pr-merger" / "OFF").exists(),
            "apply": (root / "litha-autonomy" / "APPLY").exists(),
            "autonomy_off": (root / "litha-autonomy" / "OFF").exists(),
            "caps": caps(root)}


# ---- PRs: her last decision per PR ------------------------------------------------------------------------------
def _decisions(path: Path) -> list[dict]:
    return [r for r in jsonl(tail_bytes(path, 3_500_000)) if "action" in r]


def pr_view(row: dict) -> dict:
    rev = row.get("review") or {}
    said = collections.Counter(rev.get("said") or [])
    return {"pr": row.get("pr"), "title": redact(str(row.get("title", "")))[:160], "action": row["action"],
            "merged": bool(row.get("merged")), "ts": row.get("ts"), "head": str(row.get("head") or "")[:8],
            "files": row.get("files"), "reasons": [redact(str(x))[:300] for x in row.get("reasons", [])][:8],
            "verdict": rev.get("verdict"), "said": dict(said),
            "summary": redact(str(rev.get("summary") or ""))[:700],
            "risks": [{"file": r.get("file"), "line": r.get("line"), "severity": r.get("severity"),
                       "why": redact(str(r.get("why", "")))[:300]} for r in (rev.get("risks") or [])][:6],
            "not_reviewed": len(rev.get("not_reviewed") or [])}


def latest_prs(rows: list[dict], at: float, days: float = PR_DAYS) -> dict[str, list[dict]]:
    """{repo: [her newest decision on each PR, newest first]} for PRs she decided on in the last `days`."""
    newest: dict[tuple, dict] = {}
    for r in rows:
        if r.get("ts", 0) < at - days * 86400:
            continue
        key = (r.get("repo") or HOME_REPO, r.get("pr"))
        if key not in newest or r.get("ts", 0) >= newest[key].get("ts", 0):
            newest[key] = r
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for (repo, _), r in sorted(newest.items(), key=lambda kv: -kv[1].get("ts", 0)):
        out[repo].append(pr_view(r))
    return dict(out)


def prs(root: Path = ROOT, at: float | None = None) -> dict:
    at = time.time() if at is None else at
    rows = cached(root / "pr-merger" / "decisions.jsonl", _decisions)
    by_repo = latest_prs(rows, at)
    modes = {r["repo"]: r for r in (read_json(REPOS_JSON, {}) or {}).get("repos", [])}
    repos = []
    for repo in list(modes) + sorted(set(by_repo) - set(modes)):
        items = by_repo.get(repo, [])
        m = modes.get(repo)
        repos.append({"repo": repo, "mode": m["mode"] if m else "not watched now", "base": m["base"] if m else "",
                      "counts": dict(collections.Counter("merged" if i["merged"] else i["action"] for i in items)),
                      "prs": items})
    return {"days": PR_DAYS, "repos": repos}


# ---- fixes --------------------------------------------------------------------------------------------------------
def _fixes(path: Path) -> list[dict]:
    return jsonl(tail_bytes(path, 400_000))


def _pr_number(v):
    """fix_pr is logged as a number or as the PR's URL: the face shows the number only."""
    m = re.search(r"(\d+)/?$", str(v or ""))
    return int(m.group(1)) if m else None


def fix_view(row: dict) -> dict:
    return {"ts": row.get("ts"), "repo": row.get("repo") or HOME_REPO, "pr": row.get("pr"),
            "result": row.get("result"), "kind": row.get("kind"), "why": redact(str(row.get("why", "")))[:300],
            "tests": [redact(str(t))[:120] for t in (row.get("tests") or [])][:4], "fix_pr": _pr_number(row.get("fix_pr")),
            "rounds": row.get("rounds"), "seconds": row.get("seconds")}


def fixes(root: Path = ROOT, at: float | None = None, n: int = 40) -> dict:
    at = time.time() if at is None else at
    rows = cached(root / "pr-fixer" / "fixes.jsonl", _fixes)
    week = [r for r in rows if r.get("ts", 0) >= at - 7 * 86400]
    midnight = time.mktime(time.localtime(at)[:3] + (0, 0, 0, 0, 0, -1))
    return {"week": dict(collections.Counter(r.get("result") for r in week)),
            "today": dict(collections.Counter(r.get("result") for r in week if r.get("ts", 0) >= midnight)),
            "recent": [fix_view(r) for r in reversed(rows[-n:])]}


# ---- Claude spend -------------------------------------------------------------------------------------------------
def caps(root: Path = ROOT) -> dict:
    c = read_json(root / "litha-claude" / "cap.json", {})
    return {**CAPS, **(c if isinstance(c, dict) else {})}


def _spend(path: Path) -> list[dict]:
    return jsonl(tail_bytes(path, 5_000_000))


def spend_view(rows: list[dict], today: str, cap: dict) -> dict:
    total = sum(float(r.get("usd", 0)) for r in rows)
    days = collections.defaultdict(float)
    for r in rows:
        days[str(r.get("day"))] += float(r.get("usd", 0))
    return {"total": round(total, 2), "today": round(days.get(today, 0.0), 2), "caps": cap,
            "days": [{"day": d, "usd": round(v, 2)} for d, v in sorted(days.items())[-14:]],
            "calls": len(rows),
            "recent": [{"ts": r.get("ts"), "what": redact(str(r.get("what", "")))[:90], "usd": r.get("usd"),
                        "model": r.get("model")} for r in reversed(rows[-12:])]}


def spend(root: Path = ROOT) -> dict:
    rows = cached(root / "litha-claude" / "spend.jsonl", _spend)
    return spend_view(rows, datetime.date.today().isoformat(), caps(root))


# ---- autonomy queue -----------------------------------------------------------------------------------------------
def autonomy(root: Path = ROOT) -> dict:
    home = root / "litha-autonomy"
    q = read_json(home / "queue.json", {}) or {}
    runs = cached(home / "runs.jsonl", _fixes)
    return {"apply": (home / "APPLY").exists(), "off": (home / "OFF").exists(), "built": q.get("built"),
            "tasks": [{"key": t.get("key"), "kind": t.get("kind"), "repo": t.get("repo"), "number": t.get("number"),
                       "score": t.get("score"), "why": redact(str(t.get("why", "")))[:300]}
                      for t in q.get("tasks", [])][:20],
            "skipped": [{"key": s.get("key"), "why": redact(str(s.get("why", "")))[:200]}
                        for s in q.get("skipped", [])][:20],
            "notes": [redact(str(x))[:200] for x in q.get("notes", [])][:6],
            "runs": [{"ts": r.get("ts"), "mode": r.get("mode"), "tasks": r.get("tasks"),
                      "acted": [{"key": a.get("key"), "result": a.get("result"), "why": redact(str(a.get("why", "")))[:200]}
                                for a in r.get("acted", [])][:6]} for r in reversed(runs[-8:])]}


# ---- self-tune and bench scores over time -------------------------------------------------------------------------
def bench_point(row: dict) -> dict | None:
    """bench-runs.jsonl has two shapes: {suite, solved, n} and {standard: {solved, n}, real: {...}}."""
    ts = row.get("at")
    if "solved" in row and "n" in row:
        return {"at": ts, "suite": f"{row.get('suite', '?')}{'/' + row['mode'] if row.get('mode') else ''}",
                "solved": row["solved"], "n": row["n"], "fixer": row.get("fixer")}
    std = row.get("standard")
    if isinstance(std, dict) and "solved" in std:
        return {"at": ts, "suite": "standard", "solved": std["solved"], "n": std.get("n"), "fixer": row.get("fixer")}
    return None


def selftune(root: Path = ROOT) -> dict:
    runs = cached(root / "litha-selftune" / "runs.jsonl", _fixes)
    bench = [p for p in (bench_point(r) for r in cached(root / "litha" / "bench-runs.jsonl", _fixes)) if p]
    props = sorted((root / "litha-selftune" / "proposals").glob("*.json")) if (root / "litha-selftune").exists() else []
    proposals = []
    for p in props[-6:]:
        d = read_json(p, {}) or {}
        proposals.append({"name": p.stem, "ts": d.get("ts"), "spent": d.get("spent"),
                          "failures": len(d.get("failures") or [])})
    return {"runs": [{"ts": r.get("ts"), "prompt": r.get("prompt"), "points": r.get("points"), "total": r.get("total"),
                      "outcomes": r.get("outcomes"), "overrides": r.get("overrides"), "calls": r.get("calls")}
                     for r in runs[-30:]],
            "bench": bench[-30:], "proposals": proposals}


# ---- log tail -----------------------------------------------------------------------------------------------------
def log_tail(root: Path = ROOT, n: int = 150) -> list[str]:
    lines = tail_bytes(root / "pr-merger" / "run.log", 40_000).decode("utf-8", "replace").splitlines()
    return [redact(x)[:400] for x in lines[-n:]]


# ---- everything, and the digest for her model ---------------------------------------------------------------------
def state(root: Path = ROOT) -> dict:
    t = time.time()
    out = {"at": t, "now": now(root, t), "prs": prs(root, t), "fixes": fixes(root, t), "spend": spend(root),
           "autonomy": autonomy(root), "selftune": selftune(root)}
    out["read_ms"] = round((time.time() - t) * 1000)
    return out


def _ago(ts, at) -> str:
    if not ts:
        return "never"
    m = (at - ts) / 60
    return f"{m:.0f} min ago" if m < 120 else f"{m / 60:.1f} h ago"


def digest(s: dict, limit: int = 2200) -> str:
    """Her state in a few lines (her model has a 4096-token window: the digest stays under ~600 tokens)."""
    at = s.get("at") or time.time()
    n, c = s["now"], s["now"]["controls"]
    lines = [f"Loop: {('running ' + str(n['step'] or '')).strip() if n['running'] else 'idle'}; last start {_ago(n['last_start'], at)}"
             f"; last end rc={n['end_rc']}; paused={c['paused']}; autonomy APPLY={c['apply']}."]
    if n["bad_steps"] or n["errors"]:
        lines.append("Last run problems: " + "; ".join(n["bad_steps"] + n["errors"][:2]))
    if n["health"]["problems"]:
        lines.append("Health: " + "; ".join(n["health"]["problems"][:2]))
    for r in s["prs"]["repos"]:
        if not r["prs"]:
            continue
        lines.append(f"{r['repo']} ({r['mode']}): " + ", ".join(f"{k} {v}" for k, v in sorted(r["counts"].items())))
        for p in r["prs"][:3]:
            why = (p["reasons"][:1] or [p["summary"][:100]])[0][:110]
            lines.append(f"  #{p['pr']} {'merged' if p['merged'] else p['action']}: {why}")
    f = s["fixes"]
    lines.append("Fix attempts today: " + (", ".join(f"{k} {v}" for k, v in sorted(f["today"].items(), key=str)) or "none")
                 + "; this week: " + ", ".join(f"{k} {v}" for k, v in sorted(f["week"].items(), key=str)))
    for x in f["recent"][:3]:
        lines.append(f"  #{x['pr']} {x['result']}: {x['why'][:100]}")
    sp = s["spend"]
    lines.append(f"Claude: ${sp['today']} today of ${sp['caps']['day']}, ${sp['total']} total of ${sp['caps']['total']}.")
    a = s["autonomy"]
    lines.append(f"Autonomy queue: {len(a['tasks'])} task(s)" + "".join(f"; {t['key']}" for t in a["tasks"][:2]))
    st = s["selftune"]["runs"]
    if st:
        lines.append(f"Self-tune last: {st[-1]['points']}/{st[-1]['total']} points (prompt {st[-1]['prompt']}).")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit - 3] + "..."
