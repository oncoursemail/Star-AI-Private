"""Litha's PR merger: reviews and merges open PRs into star/next on her own.

A merge needs ALL of: hard gates that really ran (base star/next, not a draft, GitHub says mergeable + CLEAN, every
check on the exact head passed, no secret / private-address / forbidden file in the added lines) AND Litha's review
of the diff with no high-risk finding. Every risk she names must point at a changed line of the diff; claims that do
not are dropped (a model's guess is not evidence). Anything else is held with the reasons, never merged.

    python -m star.pr_merger                 dry run over the open PRs into star/next (prints decisions)
    python -m star.pr_merger --apply         merge the ones that pass
    python -m star.pr_merger --pr 846        one PR
    python -m star.pr_merger --replay 40     blind replay on closed PRs: her verdict vs what really happened
Decisions go to ~/.star/pr-merger/decisions.jsonl. Never merges into main; never force-pushes; never closes a PR.
"""
from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

REPO = "oncoursemail/Star-AI-Private"
BASE = "star/next"
LOG = Path.home() / ".star" / "pr-merger" / "decisions.jsonl"
CHUNK = 12_000          # diff characters per Litha call (the GPU nodes run 8k-token contexts)
OK_CHECKS = {"SUCCESS", "SKIPPED", "NEUTRAL"}
FORBIDDEN_FILES = re.compile(r"(^|/)(pnpm-lock\.yaml|pnpm-workspace\.yaml|[^/]+\.tsbuildinfo|[^/]+\.(gguf|safetensors|"
                             r"pem|key|pfx|p12)|\.env(\.[a-z]+)?)$")
# (?<!...) / (?!...): a version pin such as ==10.3.10.19 is not an address  # star:allow (a pattern, not an address)
SECRET = re.compile(r"(?<![=\w.~^<>-])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}"
                    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\w.])"
                    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(ghp|gho|github_pat|sk|xox[bap])[-_][A-Za-z0-9_]{16,}"
                    r"|\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]", re.I)
DOC_IP = re.compile(r"\b(10\.0\.0\.\d+|192\.168\.0\.\d+|192\.168\.1\.\d+)\b")   # textbook examples, not ours

RUBRIC = """You are Litha, reviewing one pull request for STAR's repository before it is merged into star/next.
Judge only from the diff below. Check: does the change do what the title says; could it break running code
(wrong logic, missing import, changed function signature with old callers, removed behaviour, crash on empty input,
race, resource leak); are there tests for the new behaviour; dead or debug code; anything unsafe (secrets, shell
injection, deleting user data). Do not invent problems: every risk MUST name the exact file and a line number that
is shown with '+' in the diff. Severity "high" only for something that would break, lose data or leak secrets.
The diff shows only changed lines: names defined elsewhere in the file or repository DO exist, so never report a
name as undefined or missing just because the diff does not show it, and never report that the diff is cut off.
Answer only JSON: {"verdict": "merge" or "hold", "summary": "<one sentence>",
"risks": [{"file": "<path>", "line": <number>, "severity": "high" or "low", "why": "<short>"}]}"""


def gh(*args: str, timeout: float = 120) -> str:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''}: {out.stderr.strip()[:300]}")
    return out.stdout


FIELDS = "number,title,isDraft,baseRefName,headRefName,headRefOid,mergeable,mergeStateStatus,author,body"


def open_prs(number: int | None = None) -> list[dict]:
    if number:
        return [json.loads(gh("pr", "view", str(number), "--repo", REPO, "--json", FIELDS))]
    return json.loads(gh("pr", "list", "--repo", REPO, "--base", BASE, "--state", "open", "--limit", "200",
                         "--json", FIELDS))


def head_checks(sha: str) -> list[dict]:
    """Check runs on the exact head commit: [{name, status, conclusion}]."""
    data = json.loads(gh("api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"))
    return [{"name": c["name"], "status": c["status"], "conclusion": (c.get("conclusion") or "").upper()}
            for c in data.get("check_runs", [])]


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


def gate_failures(pr: dict, checks: list[dict], files: dict[str, dict]) -> list[str]:
    """Why this PR may not be merged, from facts only ([] = all hard gates pass)."""
    why = []
    if pr.get("baseRefName") != BASE:
        why.append(f"base is {pr.get('baseRefName')}, only {BASE} is allowed")
    if pr.get("isDraft"):
        why.append("draft")
    if pr.get("mergeable") != "MERGEABLE" or pr.get("mergeStateStatus") != "CLEAN":
        why.append(f"GitHub says {pr.get('mergeable')}/{pr.get('mergeStateStatus')}")
    if not checks:
        why.append("no checks ran on the head commit")
    for c in checks:
        if c["status"].lower() != "completed":
            why.append(f"check {c['name']} still {c['status']}")
        elif c["conclusion"] not in OK_CHECKS:
            why.append(f"check {c['name']} {c['conclusion'].lower()}")
    if checks and not any(c["conclusion"] == "SUCCESS" for c in checks):
        why.append("no check succeeded (all skipped)")
    for path, f in files.items():
        if FORBIDDEN_FILES.search(path):
            why.append(f"forbidden file {path}")
        for no, text in f["added"].items():
            hit = SECRET.search(text)
            if hit and not DOC_IP.fullmatch(hit.group(0)):
                why.append(f"possible secret or private address at {path}:{no}")
                break
    return why


def chunks(files: dict[str, dict], limit: int = CHUNK) -> list[str]:
    out, cur = [], ""
    for f in files.values():
        text = f["text"] if len(f["text"]) <= limit else f["text"][:limit] + "\n[... file diff cut ...]\n"
        if cur and len(cur) + len(text) > limit:
            out.append(cur)
            cur = ""
        cur += text
    return out + ([cur] if cur else [])


def ask_litha(prompt: str) -> str:                       # one place to swap the model / transport
    from star.asset3d.llm import chat
    text, _ = chat("litha", [{"role": "user", "content": prompt}], max_tokens=700, temperature=0.1,
                   json_mode=True, timeout=600)
    return text


VISIBILITY = re.compile(r"truncat|cut off|incomplete|not (shown|included|visible|present) in|missing from the diff|"
                        r"provided diff|in the diff", re.I)
UNDEFINED = re.compile(r"not (defined|imported)|undefined|NameError|missing import|does not import", re.I)


def head_file(pr: dict, path: str) -> str | None:
    """The file as it is on the PR's head commit (None when it cannot be read)."""
    try:
        return gh("api", "-H", "Accept: application/vnd.github.raw", f"repos/{REPO}/contents/{path}?ref={pr['headRefOid']}")
    except (RuntimeError, KeyError, subprocess.TimeoutExpired):
        return None


def refuted(risk: dict, source: str | None) -> str:
    """Why a high-risk claim is false when checked against the real file ('' = it stands)."""
    why = risk["why"]
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


SPECULATIVE = re.compile(r"\b(might|could|may|potential(ly)?|if [^.]* (were|was) ever|in theory)\b", re.I)
CONFIRM = """You claimed this about a pull request:
{file}:{line}: {why}
Here is the real file around that line (line numbers on the left):
{excerpt}
Is the claim definitely true for THIS code (not a guess about code you cannot see)? Answer only JSON:
{{"true": true or false, "proof": "<the one exact code line from above that proves it, copied character for character>"}}"""


def confirmed(risk: dict, source: str, ask=None) -> str:
    """Litha re-checks a high claim against the real code; '' when she proves it with a line that really is there."""
    lines = source.splitlines()
    lo, hi = max(0, risk["line"] - 40), min(len(lines), risk["line"] + 40)
    excerpt = "\n".join(f"{i + 1}: {lines[i]}" for i in range(lo, hi))
    try:
        answer = json.loads((ask or ask_litha)(CONFIRM.format(excerpt=excerpt, **risk)))
    except (ValueError, TypeError):
        return "re-check answer was not JSON"
    proof = str(answer.get("proof", "")).strip()
    proof = re.sub(r"^\d+:\s?", "", proof).strip()
    if answer.get("true") is not True:
        return "she withdrew it after reading the real code"
    if len(proof) < 4 or not any(proof == ln.strip() for ln in lines[lo:hi]):
        return "no real code line proves it"
    return ""


def review(pr: dict, files: dict[str, dict], ask=ask_litha, read=head_file) -> dict:
    """Litha's verdict over every diff chunk. Risks that do not point at an added line are dropped."""
    verdicts, summaries, risks, dropped = [], [], [], 0
    for part in chunks(files):
        prompt = f"{RUBRIC}\n\nTitle: {pr.get('title', '')}\nDescription: {(pr.get('body') or '')[:1200]}\n\n{part}"
        try:
            answer = json.loads(ask(prompt))
        except (ValueError, TypeError):
            answer = {"verdict": "hold", "summary": "review answer was not JSON", "risks": []}
        verdicts.append(str(answer.get("verdict", "hold")).lower())
        summaries.append(str(answer.get("summary", ""))[:300])
        for r in answer.get("risks") or []:
            try:
                path, line = str(r["file"]), int(r["line"])
            except (KeyError, TypeError, ValueError):
                dropped += 1
                continue
            if path in files and line in files[path]["added"]:
                risks.append({"file": path, "line": line, "severity": str(r.get("severity", "low")).lower(),
                              "why": str(r.get("why", ""))[:300]})
            else:
                dropped += 1
    cache: dict[str, str | None] = {}
    for r in risks:                     # check every high claim against the real file before it may block a merge
        if r["severity"] == "high":
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
            "risks": risks, "dropped_claims": dropped}


SAFETY = re.compile(r"secret|token|password|credential|injection|rm -rf|delet|data loss|leak|privilege|sandbox escape",
                    re.I)


@contextlib.contextmanager
def pr_trees(pr: dict):
    """(PR head, merge-base) checkouts under worktrees/: the code after and before the PR, removed afterwards.
    The merge-base, not today's star/next: for a PR that is behind, star/next holds later fixes the PR never had,
    and a test of those would look like a bug the PR made. A merged PR (replay): star/next after vs before its merge."""
    from star import pr_fixer
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
    from star import bug_proof
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


def hunt_pr(pr: dict, files: dict, rev: dict) -> None:
    """Last look before a merge: hunt each changed function for a bug; a proven regression holds the PR."""
    from star import bug_hunt
    changed = {path: set(f["added"]) for path, f in files.items() if f["added"]}
    if not any(p.endswith(".py") and not p.startswith("tests/") for p in changed):
        return
    with pr_trees(pr) as (tree, base):
        intent = f"{pr.get('title', '')}\n{pr.get('body') or ''}"
        found = bug_hunt.hunt(tree, base, changed, sys.executable, intent=intent)
    for r in found:
        rev["risks"].append({**r, "why": "hunt: " + r["why"]})
    if found:
        rev["verdict"] = "hold"


def decide(pr: dict, ask=ask_litha, checks_fn=head_checks, diff_fn=None, prove_fn=prove_high_risks,
           hunt_fn=hunt_pr) -> dict:
    diff = diff_fn(pr) if diff_fn else gh("pr", "diff", str(pr["number"]), "--repo", REPO, timeout=300)
    files = parse_diff(diff)
    checks = checks_fn(pr["headRefOid"])
    gates = gate_failures(pr, checks, files)
    rev = review(pr, files, ask) if not gates else None          # no model time on a PR the gates already block
    if rev and rev["verdict"] == "hold" and prove_fn:
        prove_fn(pr, rev, ask)                                   # a high claim must be shown by a failing test
    if rev and rev["verdict"] == "merge" and not gates and hunt_fn:
        hunt_fn(pr, files, rev)                                  # her own proven bug finds can still stop a merge
    action = "merge" if not gates and rev and rev["verdict"] == "merge" else "hold"
    reasons = gates or [f"Litha: {r['file']}:{r['line']} {r['why']}" for r in (rev or {}).get("risks", [])
                        if r["severity"] == "high"]
    return {"pr": pr["number"], "head": pr["headRefOid"], "title": pr.get("title", ""), "action": action,
            "reasons": reasons, "review": rev, "files": len(files)}


def merge(pr: dict) -> str:
    if pr.get("baseRefName") != BASE:                            # belt and braces: never main
        raise RuntimeError("refusing a merge outside " + BASE)
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
    from star import bug_hunt, pr_fixer
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m star.pr_merger")
    ap.add_argument("--apply", action="store_true", help="really merge the PRs that pass (default: dry run)")
    ap.add_argument("--pr", type=int, help="only this PR")
    ap.add_argument("--replay", type=int, help="blind replay on this many closed PRs")
    ap.add_argument("--replay-hunt", type=int, help="false holds of the bug hunt on this many merged PRs")
    a = ap.parse_args(argv)
    if a.replay_hunt:
        print(json.dumps(replay_hunt(a.replay_hunt)))
        return 0
    if a.replay:
        print(json.dumps(replay(a.replay)))
        return 0
    merged = 0
    for pr in open_prs(a.pr):
        try:
            row = decide(pr)
        except Exception as e:  # noqa: BLE001 - one bad PR must not stop the queue
            row = {"pr": pr["number"], "action": "hold", "reasons": [f"error: {str(e)[:200]}"]}
        if row["action"] == "merge" and a.apply:
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
