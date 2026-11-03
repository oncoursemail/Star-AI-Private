"""Litha's self-tuning loop (issue #873): she changes her merge prompt or a merge rule only when a replay of her real
conflicts scores higher with the change.

1. cases()   a frozen replay set from her real history: every conflicting merge commit in the repos' history (re-merged
             with `git merge-tree`, diff3 style; the committed file is the known-good answer when a person made it or it
             reached the base branch), her own failed attempts from ~/.star/pr-fixer/fixes.jsonl (her branch at that
             time against the base as of then; no known answer) and the must-refuse cases (Studio #486 = her merge of
             #442, which compiled but broke main's raycast test; STAR #853, her merge of #549 that doubled lines).
             Saved as ~/.star/litha-selftune/cases.json (repo text: never in git). Repos in EXCLUDED (Studio, off
             limits since 2026-11-02) are never built nor scored; STAR's own history merges are in since 4s.
2. score()   pr_fixer.merge_file on every case with MERGE_PROMPT (or a rule) overridden; fully offline: no git command
             runs (the base copy the checks need is frozen in the case), nothing is pushed, Claude is never asked. Her
             model's answers are cached by (case, replicate, prompt hash), so a rescore of the same prompt is free.
3. propose() the 5 worst failures go to Claude (effort high) for ONE small edit; the edit is kept only if it scores
             higher than the old prompt by more than the measured noise, no case flips good -> bad (every changed
             case is replayed 3 times, majority counts), the held-out split scores higher and no must-refuse case
             that was refused gets resolved (section 4s). A kept edit is written as a patch + report under
             ~/.star/litha-selftune/proposals/, never into the code; the lead ships it as a normal PR.

    python -m litha.self_tune build    [--max-merges N]          freeze the replay set
    python -m litha.self_tune score    [--limit N] [--only ID,..] [--prompt-file F] [--rep R]
    python -m litha.self_tune propose  [--rounds 1] [--budget 5]
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import datetime as dt
import difflib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from litha import claude
from litha import pr_fixer as pf

HOME = Path.home() / ".star" / "litha-selftune"
CASES = HOME / "cases.json"
CACHE = HOME / "answers.jsonl"
RUNS = HOME / "runs.jsonl"
PROPOSALS = HOME / "proposals"
FIXES = Path.home() / ".star" / "pr-fixer" / "fixes.jsonl"
LANE = "selftune"                    # the `what` prefix of her Claude calls from here (spend.jsonl)
CAP = 5.0                            # dollars of real Claude calls this loop may spend in total
PER_CALL = 0.5                       # the most one proposal call can cost (16K tokens out at Opus prices + the prompt)
TUNABLE = ("MERGE_PROMPT", "ANSWER")
SKIP = re.compile(r"(^|/)(pnpm-lock\.yaml|[^/]+\.lock)$|^\.github/")   # taken from the base / a person's call
# (repo, base branch, scratch clone, replay its history merges)
REPOS = [("Metallic-Club/studio", "main", HOME / "studio.git", True),
         ("oncoursemail/Star-AI-Project", "star/next", HOME / "star.git", True),
         ("Metallic-Club/plateform", "platform/feature-list-20261030", HOME / "plateform.git", True)]   # section 8
# Frozen history cases of repos the bench machine cannot clone (private: Metallic-RB), one JSON per repo, made by
# `python -m litha.trusted_bench freeze-extra` where a clone exists; cases() adds them (section 8).
EXTRA = HOME / "cases-extra"
# Repos whose cases are left out of every build and score (they stay in an old cases.json, marked, never replayed).
EXCLUDED = {"Metallic-Club/studio": "off limits (owner 2026-11-02: Matt is rebuilding it)"}
MUST_REFUSE = [
    ("Metallic-Club/studio", "da11b38a6aa68491d74311523a5e3bbf1e1972d6", "crates/metallic_physics/src/lib.rs",
     "#486, her merge of #442: compiled, but #442 skips a part the ray starts inside and main hits it at distance 0; "
     "both have tests, no merge keeps both"),
    ("oncoursemail/Star-AI-Project", "1b242fd0dad0ed96ae2129e875d681d45835562c", "frontend/src/SettingsPage.tsx",
     "#853, her merge of #549: doubled `data:BootData` (TS2300), closed"),
]
W = re.compile(r"\s+")
GOOD = ("exact", "compiles", "refused-ok")


def git(clone: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300)


def show(clone: Path, rev: str, path: str) -> str | None:
    r = git(clone, "show", f"{rev}:{path}")
    return r.stdout if r.returncode == 0 and "\0" not in r.stdout else None


def split_of(cid: str) -> str:
    return "hold" if int(hashlib.sha1(cid.encode()).hexdigest(), 16) % 3 == 0 else "tune"


def remerge(clone: Path, ours: str, theirs: str, base: str) -> dict[str, str]:
    """{path: text with diff3 markers} of a re-merge of ours with theirs, written only to the clone's object store; the
    marker labels are the ones her real merge sees (HEAD, origin/<base>)."""
    r = git(clone, "-c", "merge.conflictStyle=diff3", "merge-tree", "--write-tree", "--name-only", ours, theirs)
    if r.returncode != 1:
        return {}
    lines = r.stdout.split("\n")
    tree, files = lines[0].strip(), []
    for ln in lines[1:]:
        if not ln.strip():
            break
        files.append(ln.strip())
    out = {}
    for f in dict.fromkeys(files):
        text = show(clone, tree, f)
        if text is None or SKIP.search(f) or not pf.CONFLICT.search(text):
            continue                     # binary, lock, CI workflow, modify/delete: not a prompt question
        text = re.sub(r"(?m)^<<<<<<< [0-9a-f]{40}$", "<<<<<<< HEAD", text)
        out[f] = re.sub(r"(?m)^>>>>>>> [0-9a-f]{40}$", f">>>>>>> origin/{base}", text)
    return out


def _edition(clone: Path, rev: str) -> str:
    m = pf.EDITION.search(show(clone, rev, "Cargo.toml") or "")
    return m.group(1) if m else "2021"


def _case(repo: str, base: str, clone: Path, source: str, ours: str, theirs: str, path: str, raw: str, title: str,
          **extra) -> dict:
    at = extra["commit"][:10] if extra.get("commit") else f"{ours[:10]}-{theirs[:7]}"
    cid = f"{repo.split('/')[-1]}:{source}:{at}:{path}"
    return {"id": cid, "repo": repo, "base": base, "source": source, "kind": "merge", "ours": ours, "theirs": theirs,
            "path": path, "title": title, "raw": raw, "good": None, "base_text": show(clone, theirs, path),
            "edition": _edition(clone, theirs), "split": split_of(cid), **extra}


def history(repo: str, base: str, clone: Path, limit: int = 0) -> list[dict]:
    """Every conflicting two-parent merge in the clone's history; the committed file is known-good when a person made
    the merge or it reached the base branch (her unmerged merges are not proof of anything)."""
    log = git(clone, "log", "--merges", "--all", "--format=%H %P\t%s").stdout.splitlines()
    landed = set(git(clone, "rev-list", f"refs/remotes/origin/{base}").stdout.split())
    out = []
    for ln in log[:limit or None]:
        shas, _, subject = ln.partition("\t")
        parts = shas.split()
        if len(parts) != 3:
            continue
        commit, ours, theirs = parts
        litha = "[litha]" in subject
        for path, raw in remerge(clone, ours, theirs, base).items():
            c = _case(repo, base, clone, "history", ours, theirs, path, raw, subject, commit=commit, litha=litha)
            if not litha or commit in landed:
                c["good"] = show(clone, commit, path)
            out.append(c)
    return out


BRANCH = re.compile(r"litha/merge-(\d+)-(\d{8})-(\d{4})$")


def attempts(repo: str, base: str, clone: Path, log: Path = FIXES) -> list[dict]:
    """Her failed conflict attempts from fixes.jsonl: her branch made at that time (the PR head then) against the base
    as of then. No known-good answer: a resolved file only has to pass the checks."""
    rows = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()] if log.exists() else []
    rows = [r for r in rows if r.get("repo", "oncoursemail/Star-AI-Project") == repo and r.get("result") == "failed"
            and re.search(r"conflict|cargo tests fail|no usable|too big", r.get("why") or "")]
    branches: dict[int, list[tuple[float, str]]] = collections.defaultdict(list)
    for ln in git(clone, "for-each-ref", "--format=%(refname) %(objectname)").stdout.splitlines():
        ref, _, sha = ln.partition(" ")
        m = BRANCH.search(ref)
        if m:
            when = dt.datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M").timestamp()   # her local clock
            branches[int(m.group(1))].append((when, sha))
    out, seen = [], set()
    for r in rows:
        near = [(abs(w - r["ts"]), s) for w, s in branches.get(r["pr"], []) if abs(w - r["ts"]) < 1800]
        if not near:
            continue
        head = min(near)[1]
        if len(git(clone, "rev-parse", f"{head}^@").stdout.split()) > 1:
            continue                     # she committed a merge on it: a history case, not a failed attempt
        then = dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc).isoformat()
        tip = git(clone, "rev-list", "-1", "--first-parent", f"--before={then}", f"refs/remotes/origin/{base}")
        theirs = tip.stdout.strip()
        if not theirs or (head, theirs) in seen:
            continue
        seen.add((head, theirs))
        for path, raw in remerge(clone, head, theirs, base).items():
            out.append(_case(repo, base, clone, "attempt", head, theirs, path, raw, f"#{r['pr']}", pr=r["pr"],
                             why_then=(r.get("why") or "")[:200]))
    return out


def must_refuse(repo: str, base: str, clone: Path) -> list[dict]:
    out = []
    for r, commit, path, why in MUST_REFUSE:
        if r != repo:
            continue
        parents = git(clone, "rev-parse", f"{commit}^1", f"{commit}^2").stdout.split()
        if len(parents) != 2:
            continue
        ours, theirs = parents
        raws = remerge(clone, ours, theirs, base)
        if path in raws:
            c = _case(repo, base, clone, "refuse", ours, theirs, path, raws[path],
                      git(clone, "log", "-1", "--format=%s", commit).stdout.strip(), commit=commit, reason=why)
            c.update(kind="must_refuse", bad=show(clone, commit, path))
            out.append(c)
    return out


def build(repos=None, max_merges: int = 0, log: Path = FIXES, out: Path = CASES) -> list[dict]:
    """Freeze the replay set (deduplicated by file text: one conflict met twice counts once, known-good kept)."""
    found = []
    for repo, base, clone, hist in repos or REPOS:
        if repo in EXCLUDED:
            print(f"self_tune: {repo} excluded: {EXCLUDED[repo]}", flush=True)
            continue
        if not Path(clone).exists():
            print(f"self_tune: no scratch clone for {repo} at {clone}; skipped", flush=True)
            continue
        found += must_refuse(repo, base, clone)
        found += history(repo, base, clone, max_merges) if hist else []
        found += attempts(repo, base, clone, log)
    rank = {"refuse": 0, "history": 1, "attempt": 2}
    keep: dict[str, dict] = {}
    for c in sorted(found, key=lambda c: (rank[c["source"]], c["good"] is None)):
        keep.setdefault(hashlib.sha1((c["path"] + "\0" + c["raw"]).encode()).hexdigest(), c)
    cases_ = sorted(keep.values(), key=lambda c: c["id"])
    out.parent.mkdir(parents=True, exist_ok=True)
    pf.write_atomic(out, json.dumps({"built": int(time.time()), "cases": cases_}, ensure_ascii=False))
    return cases_


def cases(path: Path = CASES, extra: Path | None = None) -> list[dict]:
    """The frozen replay set (built on first use) plus the frozen extra sets next to it (cases-extra/*.json), without
    the cases of EXCLUDED repos; a case id counts once."""
    got = build(out=path) if not path.exists() else json.loads(path.read_text(encoding="utf-8"))["cases"]
    folder = extra or path.with_name(EXTRA.name)
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        with contextlib.suppress(OSError, ValueError, KeyError):
            got = got + json.loads(p.read_text(encoding="utf-8"))["cases"]
    return list({c["id"]: c for c in got if c["repo"] not in EXCLUDED}.values())


# ---------------------------------------------------------------- scoring


def prompt_hash(overrides: dict) -> str:
    cur = {k: overrides.get(k, getattr(pf, k)) for k in TUNABLE}
    return hashlib.sha256(json.dumps(cur, sort_keys=True).encode()).hexdigest()[:12]


class Cache:
    """Her answers by (case, replicate, prompt hash); appended as they come, so an interrupted score loses nothing."""

    def __init__(self, path: Path | None = CACHE):
        self.path, self.data = path, {}
        if path and path.exists():
            for ln in path.read_text(encoding="utf-8").splitlines():
                with contextlib.suppress(ValueError, KeyError):
                    row = json.loads(ln)
                    self.data[row["k"]] = row["a"]

    def asker(self, model, cid: str, rep: int, stats: dict):
        def ask(prompt: str) -> str:
            k = f"{cid}|{rep}|{hashlib.sha256(prompt.encode()).hexdigest()[:24]}"
            if k not in self.data:
                t = time.time()
                self.data[k] = model(prompt)
                stats["calls"] += 1
                stats["model_s"] += time.time() - t
                if self.path:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"k": k, "a": self.data[k]}, ensure_ascii=False) + "\n")
            else:
                stats["cached"] += 1
            return self.data[k]
        return ask


@contextlib.contextmanager
def replay(case: dict, overrides: dict):
    """pr_fixer set up for one frozen case: its repo/base, the override, and a git that only knows the base's copy of
    this file (anything else returns an error: a replay never changes git state)."""
    def fake_sh(args, cwd=None, timeout=600, env=None):
        if list(args[:2]) == ["git", "show"] and str(args[2]).startswith("origin/"):
            text = case.get("base_text")
            return subprocess.CompletedProcess(args, 0 if text is not None else 128, text or "", "")
        return subprocess.CompletedProcess(args, 1, "", "self_tune: no git or other commands in a replay")
    names = ("REPO", "BASE", "sh", *overrides)
    saved = {k: getattr(pf, k) for k in names}
    try:
        pf.REPO, pf.BASE, pf.sh = case["repo"], case["base"], fake_sh
        for k, v in overrides.items():
            if k not in TUNABLE:
                raise KeyError(f"not tunable: {k}")
            setattr(pf, k, v)
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Cargo.toml").write_text(f'edition = "{case.get("edition") or "2021"}"\n', encoding="utf-8")
            yield Path(d)
    finally:
        for k, v in saved.items():
            setattr(pf, k, v)


def blocks_vs_good(raw: str, merged: str, good: str) -> list[dict]:
    """Per conflict block: her text between the unchanged lines around it, the committed text between the same lines
    (whitespace-insensitive), match True/False, or None when the committed file has no such anchors."""
    segs = pf.CONFLICT.split(raw)
    blocks = pf.CONFLICT.findall(raw)
    gw, res, pos = W.sub("", good), [], (len(segs[0]) if merged.startswith(segs[0]) else -1)
    for k in range(1, len(segs)):
        row = {"block": blocks[k - 1][:1500], "match": None, "mine": None, "good": None}
        res.append(row)
        if pos < 0:
            continue
        nxt = segs[k]
        end = merged.find(nxt, pos) if nxt else len(merged)
        if end < 0 or (not nxt and k < len(segs) - 1):
            pos = -1
            continue
        mine = merged[pos:end]
        pos = end + len(nxt)
        pre, post = W.sub("", segs[k - 1])[-150:], W.sub("", nxt)[:150]
        i = gw.find(pre) if pre else 0
        j = gw.find(post, i + len(pre)) if post and i >= 0 else (len(gw) if i >= 0 else -1)
        if i >= 0 and j >= 0:
            row.update(match=gw[i + len(pre):j] == W.sub("", mine), mine=mine[:1500])
            gi, gj = _anchor(good, segs[k - 1], nxt)
            row["good"] = good[gi:gj][:1500] if gi is not None else None
    return res


def _anchor(text: str, before: str, after: str) -> tuple[int | None, int | None]:
    """Where the text between before's last 3 lines and after's first 3 lines sits in text (for showing it)."""
    pre = "".join(before.splitlines(keepends=True)[-3:])
    post = "".join(after.splitlines(keepends=True)[:3])
    i = text.find(pre) if pre else 0
    if i < 0:
        return None, None
    j = text.find(post, i + len(pre)) if post else len(text)
    return (i + len(pre), j) if j >= 0 else (None, None)


def judge(case: dict, merged: str | None, why: str) -> dict:
    """exact / compiles / wrong / refused / refused-ok / resolved-must-refuse for one case."""
    if case["kind"] == "must_refuse":
        if merged is None or why:
            return {"outcome": "refused-ok", "why": why[:300]}
        return {"outcome": "resolved-must-refuse", "why": case.get("reason", "")[:300]}
    if merged is None or why:
        return {"outcome": "refused", "why": why[:300]}
    if case.get("good") is None:
        return {"outcome": "compiles", "why": ""}
    blocks = blocks_vs_good(case["raw"], merged, case["good"])
    seen = [b["match"] for b in blocks if b["match"] is not None]
    if not seen:
        return {"outcome": "compiles", "why": "the committed file has no anchors for its blocks"}
    if all(seen):
        return {"outcome": "exact", "why": ""}
    return {"outcome": "wrong", "why": "differs from the committed resolution",
            "blocks": [b for b in blocks if b["match"] is False][:3]}


def cached_only(prompt: str) -> str:
    """A model that never answers: a score with it reads the cache only (an uncached case comes out as "error")."""
    raise RuntimeError("not in the answer cache")


def run_case(case: dict, overrides: dict, ask, lessons=None) -> dict:
    """One case; with lessons (an experience.Store) her prompts get the relevant ones, never one made from this case."""
    from litha import experience
    with replay(case, overrides) as tree, \
            (experience.forced(lessons, ("resolve",), case["id"], case.get("at")) if lessons is not None
             else contextlib.nullcontext()):
        asker = pf.mechanical_only if pf.guarded(case["path"]) else ask
        try:
            merged, why = pf.merge_file(tree, case["path"], case["raw"], case["title"], asker)
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            return {"outcome": "error", "why": f"{type(e).__name__}: {e}"[:300]}
    return judge(case, merged, why)


def score(overrides: dict | None = None, cases_: list[dict] | None = None, model=None, rep: int = 0,
          cache: Cache | None = None, only: set[str] | None = None, log: Path | None = RUNS, lessons=None) -> dict:
    """Every case replayed with the override (and, with lessons, her experience memory in the prompts);
    {"points", "total", "hold", "refuse_ok", "outcomes", "cases": {id: result}, ...}."""
    overrides = dict(overrides or {})
    todo = [c for c in (cases_ if cases_ is not None else cases()) if only is None or c["id"] in only]
    cache = cache or Cache()
    model = model or pf.ask
    stats = {"calls": 0, "cached": 0, "model_s": 0.0}
    t, results = time.time(), {}
    for c in todo:
        results[c["id"]] = r = run_case(c, overrides, cache.asker(model, c["id"], rep, stats), lessons)
        r["split"] = c.get("split", "tune")
        r["refuse"] = c["kind"] == "must_refuse"
    counts = collections.Counter(r["outcome"] for r in results.values())
    out = {"prompt": prompt_hash(overrides), "rep": rep, "total": len(results), "lessons": lessons is not None,
           "points": sum(r["outcome"] in GOOD for r in results.values()),
           "hold": sum(r["outcome"] in GOOD for r in results.values() if r["split"] == "hold"),
           "hold_total": sum(r["split"] == "hold" for r in results.values()),
           "refuse_ok": all(r["outcome"] == "refused-ok" for r in results.values() if r["refuse"]),
           "outcomes": dict(counts), "calls": stats["calls"], "cached": stats["cached"],
           "model_s": round(stats["model_s"]), "seconds": round(time.time() - t), "cases": results}
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), **{k: v for k, v in out.items() if k != "cases"},
                                "overrides": sorted(overrides), "only": len(only) if only else None}) + "\n")
    return out


# ---------------------------------------------------------------- proposals

SEVERITY = {"resolved-must-refuse": 4, "wrong": 3, "error": 0, "refused": 2}


def worst(result: dict, cases_: list[dict], n: int = 5) -> list[dict]:
    """The n failures that hurt most, tune split first (the hold-out split stays unseen), short ones before long."""
    by = {c["id"]: c for c in cases_}
    bad = [(cid, r) for cid, r in result["cases"].items() if r["outcome"] not in GOOD and r["outcome"] != "error"]
    bad.sort(key=lambda x: (x[1]["split"] != "tune", -SEVERITY.get(x[1]["outcome"], 1),
                            by[x[0]]["good"] is None, len(by[x[0]]["raw"])))
    return [{"case": by[cid], **r} for cid, r in bad[:n]]


def show_failure(f: dict) -> str:
    c = f["case"]
    head = f"### {c['id']} ({c['path']}): {f['outcome']}. {f.get('why', '')}\n"
    if f["outcome"] == "resolved-must-refuse":
        return head + f"Why it must be refused: {c.get('reason')}\nConflict blocks:\n" + \
            "\n".join(pf.CONFLICT.findall(c["raw"]))[:2500] + "\n"
    if f.get("blocks"):
        b = f["blocks"][0]
        return head + (f"Conflict block:\n{b['block'][:1500]}\nHer resolution:\n{(b['mine'] or '')[:1200]}\n"
                       f"Committed resolution:\n{(b['good'] or '(not found)')[:1200]}\n")
    text = head + "Conflict blocks:\n" + "\n".join(pf.CONFLICT.findall(c["raw"]))[:2000] + "\n"
    if c.get("good"):
        segs = pf.CONFLICT.split(c["raw"])
        i, j = _anchor(c["good"], segs[0], segs[1])
        text += f"Committed resolution of the first block:\n{c['good'][i:j][:1200] if i is not None else '(not found)'}\n"
    return text


ASK = """You tune Litha, a local 12B model (4096-token window) that resolves git merge conflicts with this prompt
template (Python str.format: {{repo}}, {{base}}, {{title}}, {{path}}, {{i}}, {{n}}, {{context}}, {{feedback}} are filled in;
literal braces are doubled):
<MERGE_PROMPT>
{prompt}
</MERGE_PROMPT>
Her answer passes checks before it is used (nothing either side added is lost, no line from just outside the block is
repeated, brackets balance like both sides, the file parses); a failed check is fed back and she tries again (3 tries),
and an answer that is not JSON with a "resolved" string counts as no answer (the file is then refused, which is safe).
Rule: ANSWER = {answer} (a merge longer than this many tokens is refused without asking her).
Replay score now: {points}/{total} cases solved ({outcomes}).
Her 5 worst failures on real cases:
{failures}
{tried}Propose ONE small edit that should fix the most of these without hurting other merges: either replace one exact
substring of MERGE_PROMPT (keep it short, keep every {{placeholder}}, keep the JSON answer format) or change ANSWER.
Answer only JSON: {{"target": "MERGE_PROMPT", "old": "<exact substring>", "new": "<replacement>", "why": "<one line>"}}
or {{"target": "ANSWER", "new": <int>, "why": "<one line>"}}"""


def lane_spent(ledger: Path | None = None) -> float:
    total = 0.0
    with contextlib.suppress(OSError):
        for ln in (ledger or claude.LEDGER).read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(ValueError, KeyError):
                row = json.loads(ln)
                total += row["usd"] if str(row.get("what", "")).startswith(LANE) else 0.0
    return total


def parse_edit(text: str) -> tuple[dict, str]:
    """(overrides, why) from Claude's answer; raises ValueError when it is not one usable edit."""
    ans = json.loads(text[text.find("{"):text.rfind("}") + 1])
    if ans.get("target") == "ANSWER":
        n = int(ans["new"])
        if not 500 <= n <= 4000 or n == pf.ANSWER:
            raise ValueError(f"ANSWER {n} out of range or unchanged")
        return {"ANSWER": n}, str(ans.get("why", ""))
    if ans.get("target") != "MERGE_PROMPT":
        raise ValueError(f"unknown target {ans.get('target')!r}")
    old, new = str(ans["old"]), str(ans["new"])
    if not old or pf.MERGE_PROMPT.count(old) != 1 or old == new:
        raise ValueError("old text is not exactly once in MERGE_PROMPT")
    prompt = pf.MERGE_PROMPT.replace(old, new)
    if len(new) - len(old) > 800:
        raise ValueError("not a small edit")
    filled = prompt.format(repo="r", base="b", title="t", path="p", i=1, n=1, context="\0code\0", feedback="\0fb\0")
    if "\0code\0" not in filled or "\0fb\0" not in filled or '"resolved"' not in filled:
        raise ValueError("the edit loses the context or the JSON answer format")
    return {"MERGE_PROMPT": prompt}, str(ans.get("why", ""))


def patch(overrides: dict, source: Path | None = None) -> str:
    """The edit as a unified diff of litha/pr_fixer.py (the prompt's source text is its runtime value)."""
    path = source or Path(pf.__file__)
    text = path.read_text(encoding="utf-8")
    new = text
    if "MERGE_PROMPT" in overrides:
        start = new.index('MERGE_PROMPT = """') + len('MERGE_PROMPT = """')
        end = new.index('"""', start)
        if new[start:end] != pf.MERGE_PROMPT:
            raise ValueError("MERGE_PROMPT's source differs from its value; patch by hand")
        new = new[:start] + overrides["MERGE_PROMPT"] + new[end:]
    if "ANSWER" in overrides:
        new = re.sub(r"(?m)^ANSWER = \d+", f"ANSWER = {overrides['ANSWER']}", new, count=1)
    return "".join(difflib.unified_diff(text.splitlines(keepends=True), new.splitlines(keepends=True),
                                        "a/litha/pr_fixer.py", "b/litha/pr_fixer.py"))


def majority(cid: str, overrides: dict, cases_: list[dict], model, cache: Cache, first: str,
             lessons=None) -> tuple[str, bool]:
    """(outcome, whether rep 0 was a fluke): 3 replicates of one case, the outcome most of them give."""
    got = [first] + [score(overrides, cases_, model, rep, cache, {cid}, None, lessons)["cases"][cid]["outcome"]
                     for rep in (1, 2)]
    good = sum(o in GOOD for o in got) >= 2
    pick = next(o for o in got if (o in GOOD) == good)
    return pick, (first in GOOD) != good


def compare(old: dict, new: dict, overrides: dict, cases_: list[dict], model, cache: Cache,
            lessons_old=None, lessons_new=None, old_overrides: dict | None = None) -> dict:
    """Old vs new (prompt, rule or experience memory): every case whose good/bad status changed is replayed 3 times
    under both; noise = how many of those first answers the majority overturned. Kept only when the total rises by
    more than the noise, no good case breaks, the HELD-OUT cases score higher and every must-refuse case that was
    refused still is."""
    changed = [cid for cid in old["cases"] if (old["cases"][cid]["outcome"] in GOOD)
               != (new["cases"].get(cid, {}).get("outcome") in GOOD)]
    o = {cid: r["outcome"] for cid, r in old["cases"].items()}
    n = {cid: r["outcome"] for cid, r in new["cases"].items()}
    noise = 0
    for cid in changed:
        o[cid], f1 = majority(cid, old_overrides or {}, cases_, model, cache, o[cid], lessons_old)
        n[cid], f2 = majority(cid, overrides, cases_, model, cache, n[cid], lessons_new)
        noise += f1 or f2
    flips = sorted(cid for cid in changed if o[cid] in GOOD and n[cid] not in GOOD)
    gains = sorted(cid for cid in changed if o[cid] not in GOOD and n[cid] in GOOD)
    po, pn = sum(v in GOOD for v in o.values()), sum(v in GOOD for v in n.values())
    hold = [cid for cid, r in old["cases"].items() if r.get("split") == "hold"]
    ho, hn = sum(o[c] in GOOD for c in hold), sum(n.get(c) in GOOD for c in hold)
    lost_refusals = sorted(cid for cid, r in old["cases"].items()
                           if r.get("refuse") and o[cid] == "refused-ok" and n.get(cid) != "refused-ok")
    keep = pn > po + noise and not flips and hn > ho and not lost_refusals
    return {"old": po, "new": pn, "noise": noise, "flips": flips, "gains": gains, "hold_old": ho, "hold_new": hn,
            "hold_total": len(hold), "lost_refusals": lost_refusals, "keep": keep, "rechecked": changed}


def tried(out: Path) -> str:
    """The edits already scored and rejected (so a later round proposes something else)."""
    rows = []
    for p in sorted(out.glob("*.json")) if out.exists() else []:
        with contextlib.suppress(OSError, ValueError, KeyError):
            r = json.loads(p.read_text(encoding="utf-8"))
            if r.get("result") == "rejected":
                v = r["verdict"]
                rows.append(f"- {r['answer'][r['answer'].find('{'):][:500]} -> {v['old']} -> {v['new']} "
                            f"(noise {v['noise']}, {len(v['flips'])} good cases broken)")
    return ("Edits already tried and rejected (propose a different one):\n" + "\n".join(rows[-5:]) + "\n") if rows \
        else ""


def propose(cases_: list[dict] | None = None, model=None, asker=None, rounds: int = 1, budget: float = CAP,
            cache: Cache | None = None, out: Path = PROPOSALS, ledger: Path | None = None,
            log: Path | None = RUNS) -> list[dict]:
    """Up to `rounds` proposals; each is scored and kept only on a real gain. Returns one report per round."""
    cases_ = cases_ if cases_ is not None else cases()
    cache = cache or Cache()
    model = model or pf.ask
    asker = asker or (lambda prompt: claude.ask(prompt, "high", what=f"{LANE}: propose"))
    reports = []
    for _ in range(rounds):
        before = lane_spent(ledger)
        if before + PER_CALL > budget:
            reports.append({"result": "budget", "spent": round(before, 4)})
            break
        old = score({}, cases_, model, 0, cache, log=log)
        fails = worst(old, cases_)
        if not fails:
            reports.append({"result": "nothing to fix", "old": old["points"]})
            break
        text = asker(ASK.format(prompt=pf.MERGE_PROMPT, answer=pf.ANSWER, points=old["points"], total=old["total"],
                                outcomes=json.dumps(old["outcomes"]),
                                failures="\n".join(show_failure(f) for f in fails), tried=tried(out)))
        report = {"ts": int(time.time()), "failures": [f["case"]["id"] for f in fails],
                  "spent": round(lane_spent(ledger) - before, 4), "answer": text[:3000]}
        try:
            overrides, why = parse_edit(text)
        except (ValueError, KeyError, TypeError) as e:
            reports.append({**report, "result": f"unusable answer: {e}"})
            continue
        new = score(overrides, cases_, model, 0, cache, log=log)
        verdict = compare(old, new, overrides, cases_, model, cache)
        report.update(why=why, verdict=verdict, old_outcomes=old["outcomes"], new_outcomes=new["outcomes"],
                      old_hold=old["hold"], new_hold=new["hold"], result="kept" if verdict["keep"] else "rejected")
        out.mkdir(parents=True, exist_ok=True)
        stem = out / f"{dt.date.today():%Y%m%d}-{prompt_hash(overrides)}"
        if verdict["keep"]:
            stem.with_suffix(".patch").write_text(patch(overrides), encoding="utf-8")
            report["patch"] = str(stem.with_suffix(".patch"))
        stem.with_suffix(".json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        reports.append(report)
        if verdict["keep"]:
            break
    return reports


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.self_tune")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="freeze the replay set into ~/.star/litha-selftune/cases.json")
    b.add_argument("--max-merges", type=int, default=0, help="newest N merges per repo (0 = all)")
    s = sub.add_parser("score", help="replay every case with her model (or an override) and print the score")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--only", default="", help="comma-separated case ids")
    s.add_argument("--prompt-file", type=Path, help="a MERGE_PROMPT to score instead of the current one")
    s.add_argument("--rep", type=int, default=0, help="replicate number (a new one asks her model again)")
    p = sub.add_parser("propose", help="Claude proposes one edit; kept only if the replay score rises")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--budget", type=float, default=CAP)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        got = build(max_merges=a.max_merges)
        n = collections.Counter((c["source"], c["good"] is not None) for c in got)
        print(json.dumps({"cases": len(got), **{f"{k[0]}{'+good' if k[1] else ''}": v for k, v in n.items()}}))
        return 0
    if a.cmd == "score":
        all_ = cases()
        todo = all_[:a.limit] if a.limit else all_
        over = {"MERGE_PROMPT": a.prompt_file.read_text(encoding="utf-8")} if a.prompt_file else {}
        r = score(over, todo, rep=a.rep, only=set(a.only.split(",")) if a.only else None)
        print(json.dumps({k: v for k, v in r.items() if k != "cases"}))
        for cid, x in r["cases"].items():
            if x["outcome"] not in GOOD:
                print(f"  {x['outcome']:<22} {cid}  {x.get('why', '')[:100]}")
        return 0
    for rep in propose(rounds=a.rounds, budget=a.budget):
        print(json.dumps({k: v for k, v in rep.items() if k != "answer"}))
    print(f"self_tune: Claude spend in this lane so far ${lane_spent():.4f} of ${a.budget:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
