"""Litha's self-diagnosis: where is she weak, and what should be fixed first?

Her recent failures (`~/.star/pr-fixer/fixes.jsonl`, the fixer's rows; `~/.star/pr-merger/decisions.jsonl`, the
merger's errors and her review claims that the real code or a test did not back) are put into buckets by the reason
she logged. Each bucket names the lane of her pipeline it belongs to, a suspected cause and how fixable it is
(mechanical = high, her model's answers = medium, a person's call by design = low). Ranked by recency-weighted count
x fixability, written to `~/.star/litha/next_steps.json` (never the repo). A bucket whose lane went on to log
QUIET or more later attempts without it (refusals not counted) is marked quiet (probably fixed) and scores less.

    python -m litha.self_plan [--days 7] [--top 10] [--home DIR]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

HOME = Path.home() / ".star"
STAR = "oncoursemail/Star-AI-Project"
QUIET, QUIET_FACTOR = 3, 0.1    # a bucket whose lane logged >= 3 later attempts without it: likely fixed, score x 0.1

# lane -> where in her code that lane lives (what a fix for the bucket would change)
LANES = {
    "resolve": "pr_fixer.resolve / resolve_text / merge_file (merge conflicts)",
    "fix-python": "pr_fixer.fix / repair (failing pytest)",
    "fix-lint": "pr_fixer.fix_lint (ruff)",
    "fix-types": "pr_fixer.fix_types (pyright baseline)",
    "fix-frontend": "pr_fixer.fix_frontend (tsc + vitest)",
    "fix-lock": "pr_fixer.fix_lock (hashed requirements lock)",
    "fix-rust": "rust_fix (cargo build/test repair)",
    "hunt-fix": "pr_fixer.fix(found=...) (a proven hunt find)",
    "ci-rerun": "pr_fixer.fix / rerun_failed (expired logs, flaky CI)",
    "publish": "pr_fixer.fix / resolve (commit, push, PR)",
    "merge-review": "pr_merger.review / confirmed / prove_high_risks",
    "merge-gates": "pr_merger.decide / merge (gh calls)",
    "other": "unclassified",
}

# (bucket, lane, outcome, pattern on the logged reason, fixability 0..1, suspected cause, advice for her prompt or "")
# outcome: failed = she tried and it did not work; refused = a gate stopped it on purpose; rerun = CI was restarted;
# noop = a run used on nothing. First match wins.
BUCKETS = [
    ("rerun-restarted-nothing", "ci-rerun", "noop", r"failed logs expired; reran 0 run", 0.9,
     "the failed job's logs expired and GitHub restarted 0 runs; a rerun row does not mark the head tried, so the "
     "same PR came back every run", ""),
    ("conflict-brackets", "resolve", "failed", r"no usable answer for conflict.*(open and close|bracket)", 0.6,
     "her merged block does not open/close brackets the way both sides do (usually code from around the block "
     "copied in, or the block's last lines left out)",
     "Measured: your conflict answers most often break bracket balance. Give exactly the lines that replace the "
     "block; do not repeat code from before or after it."),
    ("conflict-dropped-side", "resolve", "failed", r"no usable answer for conflict.*dropped what one side added", 0.6,
     "her answer loses a function/row one side added", "Measured: you drop what one side added. Keep both sides' "
     "new functions and rows."),
    ("conflict-copied-context", "resolve", "failed", r"no usable answer for conflict.*(repeats the line|copies|copied)",
     0.6, "her answer repeats lines just outside the block",
     "Measured: you repeat the line just after the block. Give only what replaces the block."),
    ("conflict-not-json", "resolve", "failed", r"no usable answer for conflict.*not valid JSON", 0.7,
     "her answer was not valid JSON (long prose blocks such as ARCHITECTURE.md)",
     "Measured: long answers come back as invalid JSON. Escape newlines and quotes inside \"resolved\"."),
    ("conflict-markers-left", "resolve", "failed", r"no usable answer for conflict.*conflict markers", 0.7,
     "her answer still had conflict markers", "Give the merged text only, without <<<<<<< ======= >>>>>>> lines."),
    ("conflict-no-answer", "resolve", "failed", r"no usable answer for conflict", 0.5,
     "no answer passed the checks", ""),
    ("conflict-parse", "resolve", "failed", r"rustfmt rejects it|does not parse|does not compile|leftover markers", 0.6,
     "her merged file does not parse", ""),
    ("conflict-needs-person", "resolve", "refused", r"conflicts she does not resolve alone|person's call", 0.1,
     "CI files or too many files conflict: a person's call by design", ""),
    ("conflict-too-big", "resolve", "refused", r"too big for her \d+-token window", 0.4,
     "one conflict block does not fit her 4096-token window", ""),
    ("conflict-too-many-blocks", "resolve", "refused", r"conflict blocks(?: need her)? \(1-8 handled\)", 0.4,
     "more than 8 conflict blocks in one file need her", ""),
    ("conflict-no-markers", "resolve", "failed", r"\b0 conflict blocks|git marked no conflict lines", 0.6,
     "git left no conflict lines (modify/delete, rename, binary)", ""),
    ("merged-tests-fail", "resolve", "failed", r"after resolving, cargo tests fail", 0.3,
     "the textual merge is clean but the two sides disagree in behaviour (a semantic conflict)", ""),
    ("rust-still-failing", "fix-rust", "failed", r"still failing: error\[E\d+\]|cargo .* fail", 0.5,
     "her Rust edits did not make the build pass", ""),
    ("lock-pinned-by-test", "fix-lock", "refused", r"regenerated lock still fails", 0.1,
     "a test pins the dependency choice on purpose: the owner's call", ""),
    ("push-rejected", "publish", "failed", r"push failed", 0.8,
     "her branch was behind its remote copy (an earlier attempt pushed it)", ""),
    ("no-pytest-failure", "fix-python", "noop", r"no pytest failure in the failed logs", 0.5,
     "the failed job had no pytest failure she could read", ""),
    ("flaky", "ci-rerun", "rerun", r"pass locally|reran \d+ failed run|no test or lint failure", 0.2,
     "CI failed where her local run passes (flaky test, lost runner)", ""),
    ("logs-expired", "ci-rerun", "rerun", r"failed logs expired", 0.2,
     "the failed job's logs expired; CI was rerun to get them", ""),
    ("types-not-fixed", "fix-types", "failed", r"pyright|type gate|new pyright", 0.5,
     "her type fixes did not bring the errors under the baseline", ""),
    ("frontend-not-fixed", "fix-frontend", "failed", r"\btsc\b|vitest|React UI", 0.5,
     "her tsc/vitest fixes did not make the check pass", ""),
    ("lint-not-fixed", "fix-lint", "failed", r"\bruff\b|lint", 0.6, "ruff errors were left", ""),
]
_COMPILED = [(b, lane, out, re.compile(p, re.I | re.S), fix, cause, adv) for b, lane, out, p, fix, cause, adv in BUCKETS]
INFO = {b: {"lane": lane, "outcome": out, "fixability": fix, "cause": cause, "advice": adv}
        for b, lane, out, _p, fix, cause, adv in BUCKETS}
INFO.update({
    "no-reason-logged": {"lane": "fix-python", "outcome": "failed", "fixability": 0.9, "advice": "",
                         "cause": "a failed fix logged no reason: her own log cannot say why (add it to the row)"},
    "python-not-passing": {"lane": "fix-python", "outcome": "failed", "fixability": 0.5, "advice": "",
                           "cause": "her edits did not make the failing tests pass (the row's why is her own guess)"},
    "rust-not-passing": {"lane": "fix-rust", "outcome": "failed", "fixability": 0.5, "advice": "",
                         "cause": "her Rust repair did not pass the checks"},
    "exception": {"lane": "other", "outcome": "error", "fixability": 0.7, "advice": "",
                  "cause": "an exception ended the attempt (see the row's why)"},
    "merger-gh-error": {"lane": "merge-gates", "outcome": "error", "fixability": 0.7, "advice": "",
                        "cause": "a gh/GitHub API call failed (timeouts, TLS); the PR waited a run"},
    "merge-failed": {"lane": "merge-gates", "outcome": "failed", "fixability": 0.6, "advice": "",
                     "cause": "gh pr merge refused (the head moved or GitHub's state changed)"},
    "review-not-json": {"lane": "merge-review", "outcome": "failed", "fixability": 0.7, "advice": "",
                        "cause": "her review answer was not JSON"},
    "review-false-claims": {"lane": "merge-review", "outcome": "failed", "fixability": 0.5,
                            "cause": "she named high risks the real file refuted or a test could not prove",
                            "advice": ""},
})


def read_jsonl(path: Path, since: float = 0, tail: int | None = None) -> list[dict]:
    """Rows of a JSON-lines log with ts >= since; unreadable lines are skipped. tail = only the last bytes."""
    try:
        with path.open("rb") as f:
            if tail:
                f.seek(max(0, path.stat().st_size - tail))
                if f.tell():
                    f.readline()                            # a cut first line is not a row
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    rows = []
    for line in data.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and _ts(r) >= since:
            rows.append(r)
    return rows


def _ts(r: dict) -> float:
    try:
        return float(r.get("ts") or 0)
    except (TypeError, ValueError):
        return 0.0


def pr_name(r: dict) -> str:
    repo = r.get("repo") or STAR
    return f"#{r.get('pr')}" if repo == STAR else f"{repo.split('/')[-1]}#{r.get('pr')}"


def classify(r: dict) -> str:
    """The bucket of one fixes.jsonl row ('fixed' for a success)."""
    result, why = str(r.get("result", "")), str(r.get("why", ""))
    if result == "fixed":
        return "fixed"
    if result == "error":
        return "exception"
    for b, _lane, _out, pat, *_ in _COMPILED:
        if pat.search(why):
            return b
    if result in ("rerun", "flaky-rerun"):
        return "flaky"
    if result == "skip":
        return "no-pytest-failure"
    if not why.strip():
        return "no-reason-logged"
    return "python-not-passing" if (r.get("repo") or STAR) == STAR else "rust-not-passing"


def lane_of(r: dict, bucket: str) -> str:
    if bucket != "fixed":
        return INFO.get(bucket, {}).get("lane", "other")
    kind, why = str(r.get("kind", "")), str(r.get("why", ""))
    if kind == "merge" or why.startswith("merged "):
        return "resolve"
    if kind == "hunted":
        return "hunt-fix"
    if kind == "rust" or (r.get("repo") or STAR) != STAR:
        return "fix-rust"
    if "lock regenerated" in why:
        return "fix-lock"
    return {"lint": "fix-lint", "types": "fix-types", "frontend": "fix-frontend"}.get(kind, "fix-python")


def merger_rows(rows: list[dict]) -> list[dict]:
    """The merger's own failures as pseudo-rows, once per PR head (it logs every open PR every 10 minutes)."""
    out, seen = [], set()
    for d in rows:
        if d.get("replay") or d.get("replay_hunt") or "pr" not in d:
            continue
        reasons = d["reasons"] if isinstance(d.get("reasons"), list) else []
        rev = d["review"] if isinstance(d.get("review"), dict) else {}
        found = []
        if any(str(x).startswith("error:") for x in reasons):
            found.append(("merger-gh-error", next(str(x) for x in reasons if str(x).startswith("error:"))))
        if any(str(x).startswith("merge failed") for x in reasons):
            found.append(("merge-failed", next(str(x) for x in reasons if str(x).startswith("merge failed"))))
        if "not JSON" in str(rev.get("summary", "")):
            found.append(("review-not-json", "review answer was not JSON"))
        bad = [x for x in rev.get("risks") or [] if isinstance(x, dict) and x.get("severity") in ("refuted", "unproven")]
        if bad:
            found.append(("review-false-claims", str(bad[0].get("refuted") or bad[0].get("why", ""))[:200]))
        for bucket, why in found:
            key = (d.get("repo") or STAR, d.get("pr"), d.get("head"), bucket)
            if key in seen:
                continue
            seen.add(key)
            out.append({"ts": d.get("ts"), "repo": d.get("repo"), "pr": d.get("pr"), "result": "failed",
                        "why": str(why)[:200], "bucket": bucket})
    return out


def claim_rates(rows: list[dict]) -> dict:
    """Her review's high-risk claims, once per PR head: how many stood (proven/kept) vs refuted vs unproven."""
    seen, n = set(), {"high": 0, "refuted": 0, "unproven": 0, "heads": 0}
    for d in rows:
        rev = d.get("review") if isinstance(d.get("review"), dict) else None
        key = (d.get("repo") or STAR, d.get("pr"), d.get("head"))
        if not rev or d.get("replay") or key in seen:
            continue
        seen.add(key)
        n["heads"] += 1
        for x in rev.get("risks") or []:
            if isinstance(x, dict) and x.get("severity") in n:
                n[x["severity"]] += 1
    return n


def stamp(path: Path) -> list:
    try:
        st = path.stat()
        return [st.st_size, round(st.st_mtime)]
    except OSError:
        return [0, 0]


def outcomes(rows: list[dict]) -> dict[str, dict]:
    """Per lane: tries and outcomes (fixed / failed / refused / rerun / noop / error) and the top buckets."""
    lanes: dict[str, dict] = {}
    for r in rows:
        bucket = r.get("bucket") or classify(r)
        lane = lane_of(r, bucket)
        out = "fixed" if bucket == "fixed" else INFO.get(bucket, {}).get("outcome", "failed")
        s = lanes.setdefault(lane, {"n": 0, "fixed": 0, "failed": 0, "refused": 0, "rerun": 0, "noop": 0,
                                    "error": 0, "why": {}})
        s["n"] += 1
        s[out] = s.get(out, 0) + 1
        if bucket != "fixed":
            s["why"][bucket] = s["why"].get(bucket, 0) + 1
    for s in lanes.values():
        s["why"] = dict(sorted(s["why"].items(), key=lambda kv: -kv[1])[:4])
    return lanes


def plan(home: Path | None = None, now: float | None = None, days: float = 7, half_life: float = 2.0,
         top: int = 10) -> dict:
    """Buckets of her failures in the last `days`, ranked by recency-weighted count x fixability."""
    home = home or HOME
    now = now or time.time()
    since = now - days * 86400
    fixes = read_jsonl(home / "pr-fixer" / "fixes.jsonl", since)
    decisions = read_jsonl(home / "pr-merger" / "decisions.jsonl", since, tail=8_000_000)
    rows = [dict(r, bucket=classify(r)) for r in fixes] + merger_rows(decisions)
    buckets: dict[str, dict] = {}
    for r in rows:
        b = r["bucket"]
        if b == "fixed":
            continue
        info = INFO.get(b, INFO["python-not-passing"])
        e = buckets.setdefault(b, {"bucket": b, "lane": info["lane"], "where": LANES.get(info["lane"], ""),
                                   "outcome": info["outcome"], "count": 0, "weighted": 0.0, "prs": [],
                                   "fixability": info["fixability"], "cause": info["cause"],
                                   "advice": info.get("advice", ""), "last_seen": 0, "example_why": ""})
        age = max(0.0, (now - _ts(r)) / 86400)
        e["count"] += 1
        e["weighted"] += 0.5 ** (age / half_life)
        name = pr_name(r)
        if name not in e["prs"]:
            e["prs"].append(name)
        if _ts(r) >= e["last_seen"]:
            e["last_seen"], e["example_why"] = round(_ts(r)), str(r.get("why", ""))[:200]
    for e in buckets.values():          # the lane kept running without this failure since: probably fixed already
        later = sum(1 for r in rows if _ts(r) > e["last_seen"] and lane_of(r, r["bucket"]) == e["lane"]
                    and INFO.get(r["bucket"], {}).get("outcome") != "refused")   # a refusal stops before that step
        e["quiet"] = later >= QUIET
        e["later_rows_in_lane"] = later
        e["score"] = e["weighted"] * e["fixability"] * (QUIET_FACTOR if e["quiet"] else 1)
    ranked = sorted(buckets.values(), key=lambda e: (-e["score"], -e["count"]))
    for i, e in enumerate(ranked, 1):
        e.update(rank=i, score=round(e["score"], 2), weighted=round(e["weighted"], 2),
                 prs=e["prs"][:6], distinct_prs=len(e["prs"]),
                 last_seen_at=time.strftime("%Y-%m-%d %H:%M", time.localtime(e["last_seen"])))
        if e["bucket"] == "review-false-claims":
            c = claim_rates(decisions)
            total = c["high"] + c["refuted"] + c["unproven"]
            if total:
                e["advice"] = (f"Measured on your last {c['heads']} reviews: {c['refuted'] + c['unproven']} of {total} "
                               "high risks you named were refuted by the real file or not proven by a test. Mark a "
                               "risk high only when a + line visibly breaks something.")
    return {"made": round(now), "days": days, "half_life_days": half_life, "rows": len(rows),
            "fixed": sum(r["bucket"] == "fixed" for r in rows), "lanes": outcomes(rows),
            "claims": claim_rates(decisions),
            "stamps": {"fixes": stamp(home / "pr-fixer" / "fixes.jsonl"),
                       "decisions": stamp(home / "pr-merger" / "decisions.jsonl")},
            "next_steps": ranked[:top]}


def out_path(home: Path | None = None) -> Path:
    return (home or HOME) / "litha" / "next_steps.json"


def write(result: dict, home: Path | None = None) -> Path:
    path = out_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(result, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load(home: Path | None = None) -> dict:
    try:
        return json.loads(out_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.self_plan")
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--home", type=Path, help="state root (default ~/.star)")
    a = ap.parse_args(argv)
    result = plan(a.home, days=a.days, top=a.top)
    path = write(result, a.home)
    for e in result["next_steps"]:
        print(f"{e['rank']:>2}. {e['bucket']} [{e['lane']}] n={e['count']} prs={e['distinct_prs']} "
              f"score={e['score']} last={e['last_seen_at']}: {', '.join(e['prs'][:5])}", flush=True)
    print(f"wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
