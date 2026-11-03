"""Litha's PR merger: reviews and merges open PRs into star/next on her own.

A merge needs ALL of: hard gates that really ran (base star/next, not a draft, GitHub says mergeable + CLEAN, every
check on the exact head passed, no secret / private-address / forbidden file in the added lines) AND Litha's review
of the diff with no high-risk finding. Every risk she names must quote a changed line of the diff; claims that do
not are dropped (a model's guess is not evidence). Anything else is held with the reasons, never merged.

    python -m litha.pr_merger                 dry run over the open PRs into star/next (prints decisions)
    python -m litha.pr_merger --apply         merge the ones that pass
    python -m litha.pr_merger --pr 846        one PR
    python -m litha.pr_merger --replay 40     blind replay on closed PRs: her verdict vs what really happened
Decisions go to ~/.star/pr-merger/decisions.jsonl. Never merges into main; never force-pushes; never closes a PR.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from litha import review_pack, self_map

REPOS = Path(__file__).with_name("repos.json")                # every repo she looks after (first = STAR's home)
REPO = "oncoursemail/Star-AI-Project"
BASE = "star/next"
ALLOW_MAIN = False                                             # set per repo from repos.json (allow_main)
LOG = Path.home() / ".star" / "pr-merger" / "decisions.jsonl"
PAUSED = Path.home() / ".star" / "pr-merger" / "PAUSED"       # the owner's pause (her face, or by hand)
OK_CHECKS = {"SUCCESS", "SKIPPED", "NEUTRAL"}
FORBIDDEN_FILES = re.compile(r"(^|/)(pnpm-lock\.yaml|pnpm-workspace\.yaml|[^/]+\.tsbuildinfo|[^/]+\.(gguf|safetensors|"
                             r"pem|key|pfx|p12)|\.env(\.[a-z]+)?)$")
# (?<!...) / (?!...): a version pin such as ==10.3.10.19 is not an address  # star:allow (a pattern, not an address)
SECRET = re.compile(r"(?<![=\w.~^<>-])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}"
                    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\w.])"
                    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(ghp|gho|github_pat|sk|xox[bap])[-_][A-Za-z0-9_]{16,}"
                    r"|\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]", re.I)
DOC_IP = re.compile(r"\b(10\.0\.0\.\d+|192\.168\.0\.\d+|192\.168\.1\.\d+)\b")   # textbook examples, not ours

RUBRIC = """You are Litha, reviewing one pull request for the owner's repository before it is merged.
Judge only from the diff below. Check: does the change do what the title says; could it break running code
(wrong logic, missing import, changed function signature with old callers, removed behaviour, crash on empty input,
race, resource leak); are there tests for the new behaviour; dead or debug code; anything unsafe (secrets, shell
injection, deleting user data). Do not invent problems: every risk MUST name the file and line, and quote one
changed line ('+' or '-') of the diff exactly as shown, without the +/-. Severity "high" only for something that
would break, lose data or leak secrets. The diff shows only changed lines and a big PR is reviewed in parts: names
defined elsewhere in the file or repository DO exist and files not shown are reviewed separately, so never report a
name as undefined or missing just because the diff does not show it, and never report that the diff is cut off.
Answer only JSON: {"verdict": "merge" or "hold", "summary": "<one sentence>", "risks": [{"file": "<path>",
"line": <number>, "quote": "<the changed line, copied exactly>", "severity": "high" or "low", "why": "<short>"}]}"""


TRANSIENT = re.compile(r"TLS handshake timeout|i/o timeout|connection (reset|refused)|timed out|unexpected EOF|"
                       r"HTTP 50[234]|no such host", re.I)
READS = {("pr", "view"), ("pr", "list"), ("pr", "diff"), ("pr", "checks"), ("run", "list"), ("run", "view")}
GH_CALLS: collections.Counter = collections.Counter()      # this process's gh calls by kind, printed per run


def gh(*args: str, timeout: float = 120, tries: int = 3, wait: float = 5) -> str:
    """A network blip (TLS timeout, 502) on a read is retried, so it does not hold a PR for a run. Writes never are."""
    for attempt in range(tries if tuple(args[:2]) in READS else 1):
        GH_CALLS["api" if args[0] == "api" else " ".join(args[:2])] += 1
        if attempt:
            time.sleep(wait * attempt)
        out = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=timeout)
        if out.returncode == 0 or not TRANSIENT.search(out.stderr):
            break
    if out.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''}: {out.stderr.strip()[:300]}")
    return out.stdout


FIELDS = "number,title,isDraft,baseRefName,baseRefOid,headRefName,headRefOid,mergeable,mergeStateStatus,author,body"


def open_prs(number: int | None = None) -> list[dict]:
    if number:
        return [json.loads(gh("pr", "view", str(number), "--repo", REPO, "--json", FIELDS))]
    return json.loads(gh("pr", "list", "--repo", REPO, *([] if BASE == "*" else ["--base", BASE]), "--state", "open",
                         "--limit", "200",
                         "--json", FIELDS))


def head_checks(sha: str) -> list[dict]:
    """Check runs on the exact head commit: [{name, status, conclusion}]."""
    data = json.loads(gh("api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"))
    return [{"name": c["name"], "status": c["status"], "conclusion": (c.get("conclusion") or "").upper(),
             "started_at": c.get("started_at") or ""} for c in latest_runs(data.get("check_runs", []))]


def latest_runs(runs: list[dict]) -> list[dict]:
    """The newest run of each check name: a check that failed on Oct 27 and passed three times since is passing
    (seen on #700: the old failure kept her rerunning it every 10 minutes)."""
    latest: dict[str | None, dict] = {}
    for c in runs:
        name = c.get("name")
        if name not in latest or (c.get("started_at") or "") >= (latest[name].get("started_at") or ""):
            latest[name] = c
    return list(latest.values())


def parse_diff(diff: str) -> dict[str, dict]:
    """{path: {"text": file diff, "added": {new line number: text}}} for every file in a unified diff."""
    files: dict[str, dict] = {}
    cur, new_no = None, 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            cur = m.group(2) if m else line
            files[cur] = {"text": line + "\n", "added": {}}
            continue
        if cur is None:
            continue
        files[cur]["text"] += line + "\n"
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_no = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            files[cur]["added"][new_no] = line[1:]
            new_no += 1
        elif not line.startswith("-"):
            new_no += 1
    return files


REQ = re.compile(r"^([+-])([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?\s*((?:[<>=!~]=?\s*[\w.*]+\s*,?\s*)+)", re.M)


def major_bumps(files: dict) -> list[str]:
    """Requirement lines whose major version numbers changed (e.g. `<2` -> `<3`, `==1.x` -> `==2.x`). CI never runs
    STAR Home's packages, so a new major version must run on her PC before it merges."""
    out = []
    for path, f in files.items():
        if not re.fullmatch(r"requirements[\w-]*\.in", path):
            continue
        rows = [(s, n.lower(), spec) for s, n, spec in REQ.findall(f["text"]) if not n.startswith(("--", "++"))]
        old = {n: spec for s, n, spec in rows if s == "-"}
        for s, n, spec in rows:
            majors = set(re.findall(r"[<>=!~]=?\s*(\d+)", spec))
            if s == "+" and n in old and majors != set(re.findall(r"[<>=!~]=?\s*(\d+)", old[n])):
                out.append(f"{n} {old[n].strip()} -> {spec.strip()}")
    return out


def gate_failures(pr: dict, checks: list[dict], files: dict[str, dict]) -> list[str]:
    """Why this PR may not be merged, from facts only ([] = all hard gates pass)."""
    return list_gates(pr) + check_gates(checks) + diff_gates(files)


def list_gates(pr: dict) -> list[str]:
    """The hard gates `gh pr list` already answers (base, draft, GitHub's merge state): no gh call."""
    why = []
    if BASE != "*" and pr.get("baseRefName") != BASE:
        why.append(f"base is {pr.get('baseRefName')}, only {BASE} is allowed")
    if pr.get("isDraft"):
        why.append("draft")
    if pr.get("mergeable") != "MERGEABLE" or pr.get("mergeStateStatus") != "CLEAN":
        why.append(f"GitHub says {pr.get('mergeable')}/{pr.get('mergeStateStatus')}")
    return why


def check_gates(checks: list[dict]) -> list[str]:
    """The hard gates on the newest check runs of the exact head commit."""
    why = []
    if not checks:
        why.append("no checks ran on the head commit")
    for c in checks:
        if c["status"].lower() != "completed":
            why.append(f"check {c['name']} still {c['status']}")
        elif c["conclusion"] not in OK_CHECKS:
            why.append(f"check {c['name']} {c['conclusion'].lower()}")
    if checks and not any(c["conclusion"] == "SUCCESS" for c in checks):
        why.append("no check succeeded (all skipped)")
    return why


def diff_gates(files: dict[str, dict]) -> list[str]:
    """The hard gates on the diff: forbidden files, secrets or private addresses, major dependency bumps."""
    why = []
    for path, f in files.items():
        if FORBIDDEN_FILES.search(path):
            why.append(f"forbidden file {path}")
        for no, text in f["added"].items():
            hit = SECRET.search(text)
            if hit and not DOC_IP.fullmatch(hit.group(0)) and "star:allow" not in text:   # star commit's reviewed marker
                why.append(f"possible secret or private address at {path}:{no}")
                break
    why += [f"major dependency bump {b}: run it on STAR's PC first (CI does not install her packages)"
            for b in major_bumps(files)]
    return why


def review_prompts(pr: dict, files: dict[str, dict]) -> tuple[list[str], list[str]]:
    """(one prompt per part, files not reviewed). Each prompt fits her 4096-token window with the answer (estimated;
    on 62 real PRs the real count of every prompt fit), most important hunks first (review_pack)."""
    head = self_map.fitted("merge-review", lambda note: f"{RUBRIC}{note}\n\nTitle: {pr.get('title', '')}\n"
                           f"Description: {(pr.get('body') or '')[:1200]}\n", review_pack.ANSWER + 200,
                           task={"repo": REPO, "paths": list(files)[:20], "key": f"{REPO}#{pr.get('number')}",
                                 "text": pr.get("title", "") + "\n" + "\n".join(list(files)[:20])})
    parts, left = review_pack.pack(files, review_pack.budget_for(head, files))
    return [f"{head}{review_pack.others_note(p, files, left)}\n{p}" for p in parts], left


def ask_litha(prompt: str) -> str:                       # one place to swap the model / transport
    from star.asset3d.llm import chat
    text, _ = chat("litha", [{"role": "user", "content": prompt}], max_tokens=700, temperature=0.1,
                   json_mode=True, timeout=600)
    return text


VISIBILITY = re.compile(r"truncat|cut off|incomplete|not (shown|included|visible|present) in|missing from the diff|"
                        r"provided diff|in the diff", re.I)
UNDEFINED = re.compile(r"not (defined|imported)|undefined|NameError|missing import|does not import", re.I)
CANT_VERIFY = re.compile(r"(impossible|not possible|unable|cannot|can't|can not) (to )?(be )?verif", re.I)


def head_file(pr: dict, path: str) -> str | None:
    """The file as it is on the PR's head commit (None when it cannot be read)."""
    try:
        return gh("api", "-H", "Accept: application/vnd.github.raw", f"repos/{REPO}/contents/{path}?ref={pr['headRefOid']}")
    except (RuntimeError, KeyError, subprocess.TimeoutExpired):
        return None


def refuted(risk: dict, source: str | None) -> str:
    """Why a high-risk claim is false when checked against the real file ('' = it stands)."""
    why = risk["why"]
    if CANT_VERIFY.search(why):        # held-out #858: "... not included in the diff, making it impossible to verify"
        return "she says she cannot verify it"
    if VISIBILITY.search(why) and not UNDEFINED.search(why):
        return "about what the diff shows, not about the code"
    if source is None:
        return ""
    if risk["file"].endswith(".py") and re.search(r"syntax", why, re.I):
        try:
            compile(source, risk["file"], "exec")
            return "the file compiles"
        except SyntaxError:
            return ""
    if UNDEFINED.search(why) or VISIBILITY.search(why):
        names = re.findall(r"[`'\"]([A-Za-z_][A-Za-z0-9_.]*)[`'\"]", why)
        found = [n for n in names if re.search(rf"^\s*(async\s+def|def|class|import|from)\s.*\b{re.escape(n.split('.')[0])}\b"
                                              rf"|^\s*{re.escape(n.split('.')[0])}\s*[:=]", source, re.M)]
        if names and len(found) == len(names):
            return "defined or imported in the file: " + ", ".join(found)
        if not names and VISIBILITY.search(why):
            return "about what the diff shows, not about the code"
    return ""


NO_HIGH = ("test", "docs")     # CI ran the tests; a doc cannot break running code (JSON data/config still can)
# also "if any other callers ..." and "if the file was deleted ...": the two blocking claims left on 8 tune PRs
SPECULATIVE = re.compile(r"\b(might|could|may|potential(ly)?|if [^.]* (were|was) ever|in theory)\b"
                         r"|\bif (any|some) (other )?callers?\b"
                         r"|\bif [^.]* (is|was|were|gets?|got) (deleted|removed|replaced|moved|missing|inaccessible)\b",
                         re.I)
# A third reviewer's claim, her check before her verdict: on 10 false and 7 true labelled claims, 2 asks each, this
# kept 7/20 false (her old "You claimed..., is it true?" kept 10/20) and 12/14 true (old 12/14).
CONFIRM = """A code reviewer made this claim about a pull request:
{file}:{line}: {why}
Here is the real file around that line (line numbers on the left):
{excerpt}
Reviewers' claims are often wrong: they misread a bound, miss a guard a few lines away, or guess about code they
cannot see. Check it yourself against the lines above, then decide. Answer only JSON, in this order:
{{"check": "<1-3 sentences: the lines that decide it and what they really do>", "true": true or false,
"proof": "<the one exact code line from above that shows the problem, copied character for character>"}}"""


def confirmed(risk: dict, source: str, ask=None) -> str:
    """Litha re-checks a high claim against the real code; '' when she proves it with a line that really is there."""
    lines = source.splitlines()
    lo, hi = max(0, risk["line"] - 40), min(len(lines), risk["line"] + 40)
    excerpt = "\n".join(f"{i + 1}: {lines[i][:200]}" for i in range(lo, hi))   # 80 lines stay inside 4096 tokens
    try:
        answer = json.loads((ask or ask_litha)(CONFIRM.format(excerpt=excerpt, **risk)))
    except (ValueError, TypeError):
        return "re-check answer was not JSON"
    proof = str(answer.get("proof", "")).strip()
    proof = re.sub(r"^\d+:\s?", "", proof).strip()
    if answer.get("true") is not True:
        return "she withdrew it after reading the real code"
    if len(proof) < 4 or not any(review_pack.quotes(proof, ln) for ln in lines[lo:hi]):
        return "no real code line proves it"
    return ""


def review(pr: dict, files: dict[str, dict], ask=ask_litha, read=head_file) -> dict:
    """Litha's verdict over every part of the diff. A risk whose quote is not a changed line of that file (or, with
    no quote, whose line is not an added line) is dropped; the same line named in two parts counts once."""
    verdicts, summaries, risks, dropped, why_dropped, not_json = [], [], {}, 0, [], 0
    prompts, left = review_prompts(pr, files)
    for prompt in prompts:
        try:
            answer = json.loads(ask(prompt))
        except (ValueError, TypeError):
            answer = None
        if not isinstance(answer, dict):
            answer = {"verdict": "hold", "summary": "review answer was not JSON", "risks": []}
            not_json += 1
        verdicts.append(str(answer.get("verdict", "hold")).lower())
        summaries.append(str(answer.get("summary", ""))[:300])
        for r in answer.get("risks") or []:
            try:
                path, line = str(r["file"]), int(r["line"])
            except (KeyError, TypeError, ValueError):
                dropped += 1
                why_dropped.append("no file or line")
                continue
            at, no = review_pack.anchor({**r, "line": line}, files[path]) if path in files else (None, "no such file")
            if at is None:
                dropped += 1
                why_dropped.append(no)
                continue
            risk = {"file": path, "line": at, "severity": str(r.get("severity", "low")).lower(),
                    "why": str(r.get("why", ""))[:300], **({"quote": str(r["quote"])[:200]} if r.get("quote") else {})}
            old = risks.get((path, at))
            if old is None or (risk["severity"] == "high" and old["severity"] != "high"):
                risks[(path, at)] = risk
    risks = list(risks.values())
    cache: dict[str, str | None] = {}
    for r in risks:                     # check every high claim against the real file before it may block a merge
        if r["severity"] == "high" and review_pack.kind(r["file"]) in NO_HIGH and not SAFETY.search(r["why"]):
            r.update(severity="low", note="a test or doc file cannot break running code")
        elif r["severity"] == "high":
            if r["file"] not in cache:
                cache[r["file"]] = read(pr, r["file"])
            no = refuted(r, cache[r["file"]])
            if not no and SPECULATIVE.search(r["why"]):
                r["severity"] = "low"                     # "could / might": worth a note, not a block
                continue
            source = cache[r["file"]]
            if not no and source is not None:
                no = confirmed(r, source, ask)
            if no:
                r.update(severity="refuted", refuted=no)
    high = [r for r in risks if r["severity"] == "high"]
    # a bare "hold" with no line-backed high risk is not evidence enough to block; a high risk always is
    return {"verdict": "hold" if high else "merge", "said": verdicts, "summary": " ".join(summaries)[:600],
            "risks": risks, "dropped_claims": dropped, "dropped_why": why_dropped[:10], "parts": len(prompts),
            "not_reviewed": left[:20], "not_json": not_json}


REVIEWS = LOG.with_name("reviews.json")
REVIEW_TTL = 6 * 3600


def cached_review(pr: dict, files: dict[str, dict], ask=ask_litha, path: Path | None = None) -> dict:
    """review(), at most once per PR head (and review code) every REVIEW_TTL seconds. In decisions.jsonl (48 h to
    2026-11-02) 852 of 898 reviews re-read a head already reviewed (Metallic-RB#138: 235 times), and 4 heads drew
    both verdicts from the same diff. Only her live model is cached; tests and replays pass their own ask."""
    if ask is not ask_litha:
        return review(pr, files, ask)
    path = path or REVIEWS
    seen = known_review(pr, path)
    if seen is not None:
        return seen
    key, now, cache = _review_key(pr), time.time(), _fresh(path, REVIEW_TTL)
    rev = review(pr, files, ask)
    if not rev["not_json"]:                             # a part that failed is asked again next run
        cache[key] = {"ts": round(now), "review": rev}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        os.replace(tmp, path)
    return json.loads(json.dumps(rev))                  # prove_high_risks edits its copy, not the cached one


def _review_key(pr: dict) -> str:
    return f"{REPO}#{pr['number']}@{pr['headRefOid']}:" + hashlib.sha1(
        f"{RUBRIC}{CONFIRM}{review_pack.MAX_PARTS}{self_map.WINDOW}".encode()).hexdigest()[:8]


def _fresh(path: Path, ttl: float) -> dict:
    """A {key: {"ts": ..., ...}} cache file without its entries older than ttl ({} when missing or broken)."""
    now = time.time()
    try:
        return {k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if now - v["ts"] < ttl}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return {}


def known_review(pr: dict, path: Path | None = None) -> dict | None:
    """A copy of her cached review of this head (None when there is none within REVIEW_TTL)."""
    hit = _fresh(path or REVIEWS, REVIEW_TTL).get(_review_key(pr))
    if hit is None:
        return None
    return {**json.loads(json.dumps(hit["review"])), "cached": round(time.time() - hit["ts"])}


DIFF_GATES = LOG.with_name("diff_gates.json")
DIFF_TTL = 6 * 3600
GATES_VERSION = hashlib.sha1(f"{FORBIDDEN_FILES.pattern}{SECRET.pattern}{DOC_IP.pattern}{REQ.pattern}".encode()
                             ).hexdigest()[:8]


def _diff_key(pr: dict) -> str:
    """The diff is a function of the head and the base it is compared with: same key, same diff."""
    return f"{REPO}#{pr['number']}@{pr['headRefOid']}^{pr.get('baseRefOid')}:{GATES_VERSION}"


def known_diff(pr: dict, path: Path | None = None) -> dict | None:
    """{"gates", "files"} of this exact head against this exact base, gated within DIFF_TTL; else None."""
    return _fresh(path or DIFF_GATES, DIFF_TTL).get(_diff_key(pr)) if pr.get("baseRefOid") else None


def remember_diff(pr: dict, files: dict[str, dict], gates: list[str], path: Path | None = None) -> None:
    if not pr.get("baseRefOid"):                        # without the base commit "the same diff" cannot be known
        return
    path = path or DIFF_GATES
    memo = _fresh(path, DIFF_TTL)
    memo[_diff_key(pr)] = {"ts": round(time.time()), "gates": gates, "files": len(files)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(memo), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass                                            # a memo that cannot be written only costs a gh call later


SAFETY = re.compile(r"secret|token|password|credential|injection|rm -rf|delet|data loss|leak|privilege|sandbox escape",
                    re.I)


@contextlib.contextmanager
def pr_trees(pr: dict):
    """(PR head, merge-base) checkouts under worktrees/: the code after and before the PR, removed afterwards.
    The merge-base, not today's star/next: for a PR that is behind, star/next holds later fixes the PR never had,
    and a test of those would look like a bug the PR made. A merged PR (replay): star/next after vs before its merge."""
    from litha import pr_fixer
    tree = pr_fixer.WORK / f"litha-proof-{pr['number']}"
    branch = f"litha/proof-{pr['number']}"
    base = pr_fixer.WORK / f"litha-base-{pr['number']}"               # the code before the PR (differential proof)
    for wt in (tree, base):
        if wt.exists():
            pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "worktree", "remove", "--force", str(wt)])
    pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "fetch", "-q", "origin", BASE])
    merged = (pr.get("mergeCommit") or {}).get("oid")
    if merged:
        head, before = merged, f"{merged}^1"
    else:
        pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "fetch", "-q", "origin", f"pull/{pr['number']}/head:{branch}",
                     "--force"])
        head = branch
        before = pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "merge-base", branch, f"origin/{BASE}"]).stdout.strip()
    pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "worktree", "add", "-q", "--detach", str(tree), head])
    pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "worktree", "add", "-q", "--detach", str(base),
                 before or f"origin/{BASE}"])
    try:
        yield tree, base
    finally:
        for wt in (tree, base):
            pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "worktree", "remove", "--force", str(wt)])


def prove_high_risks(pr: dict, rev: dict, ask=ask_litha, limit: int = 3) -> None:
    """Keep a high risk only if her test really fails on the PR and passes on star/next."""
    from litha import bug_proof
    with pr_trees(pr) as (tree, base):
        testable = [r for r in rev["risks"] if r["severity"] == "high" and not SAFETY.search(r["why"])]
        for r in testable[:limit]:                              # safety claims stay blocking without a test
            proof = bug_proof.prove(tree, r, sys.executable, bug_proof.ask if ask is ask_litha else ask, base=base)
            r["proof"] = {k: v for k, v in proof.items() if k != "test"}
            if not proof["proven"]:
                r["severity"] = "unproven"
        for r in testable[limit:]:
            r["severity"] = "unproven"                          # past the proof budget: not evidence
    rev["verdict"] = "hold" if any(r["severity"] == "high" for r in rev["risks"]) else "merge"


HUNTED = Path.home() / ".star" / "pr-fixer" / "hunted.json"


def hunt_pr(pr: dict, files: dict, rev: dict) -> None:
    """Last look before a merge: hunt each changed function for a bug; a proven regression holds the PR."""
    from litha import bug_hunt
    changed = {path: set(f["added"]) for path, f in files.items() if f["added"]}
    if not any(p.endswith(".py") and not p.startswith("tests/") for p in changed):
        return
    with pr_trees(pr) as (tree, base):
        intent = f"{pr.get('title', '')}\n{pr.get('body') or ''}"
        found = bug_hunt.hunt(tree, base, changed, sys.executable, intent=intent)
    for r in found:
        rev["risks"].append({**{k: v for k, v in r.items() if k != "test"}, "why": "hunt: " + r["why"]})
    if found:
        rev["verdict"] = "hold"
        HUNTED.parent.mkdir(parents=True, exist_ok=True)                 # the fixer turns her proof into a fix
        queue = json.loads(HUNTED.read_text(encoding="utf-8")) if HUNTED.exists() else {}
        queue[str(pr["number"])] = {"head": pr["headRefOid"], **found[0]}
        HUNTED.write_text(json.dumps(queue), encoding="utf-8")


def decide(pr: dict, ask=ask_litha, checks_fn=head_checks, diff_fn=None, prove_fn=prove_high_risks,
           hunt_fn=hunt_pr, memo: Path | None = None, build_fn=None) -> dict:
    """The hard gates cheapest first, each a sure hold on its own: the list data (no call), the head's check runs
    (one call), then the diff (one call, the slow one). Once a gate blocks, nothing fetched later can turn the hold
    into a merge, so it is not fetched. The diff of a head gated against the same base within DIFF_TTL is not
    fetched again when nothing after the gates needs it: its diff gates blocked, or (no hunt) her review of that
    head is cached. Same action as gate_failures over everything; only the reasons stop at the first gate that blocks.
    build_fn(pr, files, checks) last, only for a PR that would merge: the head merged with today's base must build
    and pass the tests the diff touches (litha.build_check, section 4s), else it holds with the failing test named."""
    row = {"pr": pr["number"], "head": pr["headRefOid"], "title": pr.get("title", "")}
    gates = list_gates(pr)
    if gates:
        return {**row, "action": "hold", "reasons": gates, "review": None, "files": None, "skipped": "checks, diff"}
    checks = checks_fn(pr["headRefOid"])
    gates = check_gates(checks)
    if gates:
        return {**row, "action": "hold", "reasons": gates, "review": None, "files": None, "skipped": "diff"}
    seen = known_diff(pr, memo) if diff_fn is None else None
    rev = None
    if seen is not None and not seen["gates"] and ask is ask_litha and hunt_fn is None:
        rev = known_review(pr)
    if seen is not None and (seen["gates"] or rev is not None):
        files, gates, n_files = {}, list(seen["gates"]), seen["files"]
        row["skipped"] = "diff (same head and base gated within 6 h)"
    else:
        diff = diff_fn(pr) if diff_fn else gh("pr", "diff", str(pr["number"]), "--repo", REPO, timeout=300)
        files = parse_diff(diff)
        gates, n_files = diff_gates(files), len(files)
        if diff_fn is None:
            remember_diff(pr, files, gates, memo)
    if not gates and rev is None:
        rev = cached_review(pr, files, ask)                     # no model time on a PR the gates already block
    if rev and rev["verdict"] == "hold" and prove_fn:
        prove_fn(pr, rev, ask)                                   # a high claim must be shown by a failing test
    if rev and rev["verdict"] == "merge" and not gates and hunt_fn:
        hunt_fn(pr, files, rev)                                  # her own proven bug finds can still stop a merge
    action = "merge" if not gates and rev and rev["verdict"] == "merge" else "hold"
    reasons = gates or [f"Litha: {r['file']}:{r['line']} {r['why']}" for r in (rev or {}).get("risks", [])
                        if r["severity"] == "high"]
    if action == "merge" and build_fn:
        names = list(files) or gh("pr", "diff", str(pr["number"]), "--repo", REPO, "--name-only", timeout=300).split()
        built = build_fn(pr, names, checks)
        row["build"] = {k: built[k] for k in ("ok", "skipped", "ran", "failed", "seconds", "cached")
                        if built.get(k) not in (None, "", [])}
        if not built.get("ok"):
            action, reasons = "hold", [f"build check: {built.get('failed') or 'failed'}"]
    return {**row, "action": action, "reasons": reasons, "review": rev, "files": n_files}


def confirm(pr: dict) -> tuple[bool, str]:
    """Claude's look at the whole diff right before a merge, paid once per head commit; (True, "") without a key."""
    from litha import claude
    seen = claude.HOME / "reviews.json"
    try:
        done = json.loads(seen.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        done = {}
    key = f"{REPO}#{pr['number']}@{pr['headRefOid']}"
    if key not in done:
        if not claude.ready():
            return True, ""
        diff = gh("pr", "diff", str(pr["number"]), "--repo", REPO, timeout=300)[:400_000]
        text = claude.ask(f"{RUBRIC}\n\nTitle: {pr.get('title', '')}\nDescription: {(pr.get('body') or '')[:3000]}"
                          f"\n\n{diff}", "high", what=f"review {key}")
        try:
            ans = json.loads(text[text.find("{"):text.rfind("}") + 1])
        except ValueError:
            return True, ""                                      # no answer: the other gates already passed
        high = [f"{r.get('file')}:{r.get('line')} {r.get('why')}" for r in ans.get("risks") or []
                if str(r.get("severity", "")).lower() == "high"]
        done[key] = {"verdict": str(ans.get("verdict", "")).lower(), "high": high[:5]}
        seen.write_text(json.dumps(done, indent=1), encoding="utf-8")
    v = done[key]
    if v["verdict"] == "hold" and v["high"]:
        return False, "Claude: " + "; ".join(v["high"])[:600]
    return True, ""


def build(pr: dict, files: list[str], checks: list[dict]) -> dict:
    """The build/test check (litha.build_check) in the clone litha.pr_fixer works in (CLONE/WORK)."""
    from litha import build_check
    return build_check.check(pr, files, sys.executable, checks)


def vetoed(row: dict, pr: dict) -> bool:
    ok, why = confirm(pr)
    if not ok:
        row.update(action="hold", reasons=[why])
    return not ok


def merge(pr: dict) -> str:
    if BASE == "*" or pr.get("baseRefName") != BASE:             # belt and braces
        raise RuntimeError("refusing a merge outside " + BASE)
    if BASE == "main" and not ALLOW_MAIN:                        # main only where the owner allowed it (repos.json)
        raise RuntimeError("refusing a merge into main of " + REPO)
    return gh("pr", "merge", str(pr["number"]), "--repo", REPO, "--merge", "--match-head-commit", pr["headRefOid"])


def log(row: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": round(time.time()), **row}) + "\n")


def replay(n: int) -> dict:
    """Blind check of her judgement: closed PRs into star/next, review only, compared with what really happened."""
    rows = json.loads(gh("pr", "list", "--repo", REPO, "--base", BASE, "--state", "closed", "--limit", str(n),
                         "--json", "number,title,body,mergedAt,headRefOid"))
    score = {"n": 0, "agree": 0, "merged_but_held": 0, "closed_but_merge": 0}
    for pr in rows:
        try:
            files = parse_diff(gh("pr", "diff", str(pr["number"]), "--repo", REPO, timeout=300))
            pr["headRefOid"] = pr.get("headRefOid") or ""
            rev = review(pr, files)
        except Exception as e:  # noqa: BLE001 - one bad PR must not end the replay
            print(f"#{pr['number']} skipped: {e}", flush=True)
            continue
        real = "merge" if pr.get("mergedAt") else "hold"
        score["n"] += 1
        score["agree"] += rev["verdict"] == real
        score["merged_but_held"] += real == "merge" and rev["verdict"] == "hold"
        score["closed_but_merge"] += real == "hold" and rev["verdict"] == "merge"
        log({"replay": True, "pr": pr["number"], "real": real, "litha": rev["verdict"], "risks": rev["risks"]})
        print(f"#{pr['number']} real {real} litha {rev['verdict']}", flush=True)
    return score


def replay_hunt(n: int) -> dict:
    """The hunt's false holds: run it on merged PRs (star/next just before vs just after each merge). Each proven
    find is a hold on a PR the project kept: read it, then it is either a real bug or a hunt mistake to fix."""
    from litha import bug_hunt, pr_fixer
    rows = json.loads(gh("pr", "list", "--repo", REPO, "--base", BASE, "--state", "merged", "--limit", str(n),
                         "--json", "number,title,body,mergeCommit"))
    score = {"n": 0, "flagged": 0}
    for pr in rows:
        oid = (pr.get("mergeCommit") or {}).get("oid")
        if not oid:
            continue
        pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "fetch", "-q", "origin", BASE])
        files = parse_diff(pr_fixer.sh(["git", "-C", str(pr_fixer.CLONE), "diff", f"{oid}^1", oid]).stdout)
        changed = {p: set(f["added"]) for p, f in files.items()
                   if f["added"] and p.endswith(".py") and not p.startswith("tests/")}
        if not changed:
            continue
        try:
            with pr_trees(pr) as (tree, base):
                found = bug_hunt.hunt(tree, base, changed, sys.executable,
                                      intent=f"{pr.get('title', '')}\n{pr.get('body') or ''}")
        except Exception as e:  # noqa: BLE001 - one bad PR must not end the replay
            print(f"#{pr['number']} skipped: {e}", flush=True)
            continue
        score["n"] += 1
        score["flagged"] += bool(found)
        log({"replay_hunt": True, "pr": pr["number"], "found": found})
        print(f"#{pr['number']} {'FLAGGED ' + found[0]['file'] + ':' + str(found[0]['line']) + ' ' + found[0]['why'][:120] if found else 'clean'}",
              flush=True)
    return score


def others(apply: bool) -> int:
    """The owner's other repos: same gates and review. No local clone there, so no test proofs and no bug hunt: an
    unproven high-risk claim keeps holding. mode review = log ready/hold only, never merge. A repo with a local
    clone (repos.json "clone") gets the build/test check too."""
    global REPO, BASE, ALLOW_MAIN
    from litha import pr_fixer
    home = (REPO, BASE, ALLOW_MAIN)
    tree_home = (pr_fixer.CLONE, pr_fixer.WORK)
    try:
        for entry in json.loads(REPOS.read_text(encoding="utf-8"))["repos"][1:]:
            REPO, BASE, ALLOW_MAIN = entry["repo"], entry.get("base", "main"), bool(entry.get("allow_main"))
            can_merge = apply and entry.get("mode") == "merge"
            clone = Path(entry["clone"]).expanduser() if entry.get("clone") else None
            pr_fixer.CLONE, pr_fixer.WORK = tree_home
            if clone:
                pr_fixer.CLONE = clone
                pr_fixer.WORK = Path(entry.get("worktrees") or clone.parent / f"{clone.name}-worktrees").expanduser()
            try:
                prs = open_prs()
            except RuntimeError as e:
                print(f"{REPO}: cannot list PRs: {str(e)[:150]}", flush=True)
                continue
            merged = 0
            for pr in prs:
                if pr.get("isDraft"):
                    continue
                try:
                    row = decide(pr, prove_fn=None, hunt_fn=None, build_fn=build if clone else None)
                except Exception as e:  # noqa: BLE001 - one bad PR must not stop the queue
                    row = {"pr": pr["number"], "action": "hold", "reasons": [f"error: {str(e)[:200]}"]}
                if row["action"] == "merge" and can_merge and not vetoed(row, pr):
                    try:
                        merge(pr)
                        row["merged"] = True
                        merged += 1
                    except Exception as e:  # noqa: BLE001
                        row.update(action="hold", reasons=[f"merge failed: {str(e)[:200]}"])
                elif row["action"] == "merge":
                    row["action"] = "ready"                     # review mode: she would merge it
                log({"repo": REPO, **row})
                print(f"{REPO}#{row['pr']} {row['action'].upper()}{' (merged)' if row.get('merged') else ''}: "
                      f"{'; '.join(row['reasons'][:2]) or (row.get('review') or {}).get('summary', '')[:140]}", flush=True)
            print(f"{REPO}: merged {merged}" if can_merge else f"{REPO}: review only", flush=True)
    finally:
        print(f"gh calls: {sum(GH_CALLS.values())} {dict(GH_CALLS)}", flush=True)
        REPO, BASE, ALLOW_MAIN = home
        pr_fixer.CLONE, pr_fixer.WORK = tree_home
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.pr_merger")
    ap.add_argument("--apply", action="store_true", help="really merge the PRs that pass (default: dry run)")
    ap.add_argument("--pr", type=int, help="only this PR")
    ap.add_argument("--replay", type=int, help="blind replay on this many closed PRs")
    ap.add_argument("--replay-hunt", type=int, help="false holds of the bug hunt on this many merged PRs")
    ap.add_argument("--others", action="store_true", help="every other repo in repos.json (review or merge mode)")
    a = ap.parse_args(argv)
    if PAUSED.exists() and not (a.replay or a.replay_hunt):     # replays only read closed PRs: they may still run
        print(f"pr_merger: paused by the owner ({PAUSED}); nothing reviewed or merged", flush=True)
        return 0
    if a.others:
        return others(a.apply)
    if a.replay_hunt:
        print(json.dumps(replay_hunt(a.replay_hunt)))
        return 0
    if a.replay:
        print(json.dumps(replay(a.replay)))
        return 0
    merged = 0
    for pr in open_prs(a.pr):
        try:
            row = decide(pr, build_fn=build)
        except Exception as e:  # noqa: BLE001 - one bad PR must not stop the queue
            row = {"pr": pr["number"], "action": "hold", "reasons": [f"error: {str(e)[:200]}"]}
        if row["action"] == "merge" and a.apply and not vetoed(row, pr):
            try:
                merge(pr)
                row["merged"] = True
                merged += 1
            except Exception as e:  # noqa: BLE001 - e.g. the head moved: next run looks again
                row.update(action="hold", reasons=[f"merge failed: {str(e)[:200]}"])
        log(row)
        print(f"#{row['pr']} {row['action'].upper()}{' (merged)' if row.get('merged') else ''}: "
              f"{'; '.join(row['reasons'][:3]) or (row.get('review') or {}).get('summary', '')[:160]}", flush=True)
    print(f"merged {merged}" if a.apply else "dry run (use --apply to merge)")
    print(f"gh calls: {sum(GH_CALLS.values())} {dict(GH_CALLS)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
