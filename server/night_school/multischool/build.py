"""Build the multi-language practice pool: every task is verified against the judge before it is written
(the reference passes its own checks, the trivial answer fails, no duplicate prompts).

    python -m multischool build --pool <folder> [--queue <judge queue>] [--date YYYYMMDD] [--only code,debug,exact,seed]

Writes pool/multi-<family>-<date>.json (tasks), <pool>/../conductor/multi-references-<date>.jsonl (reference answers,
never in the pool) and <pool>/../report/multi-build-<date>.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                                   # nightschool
for candidate in (os.environ.get("STAR_NS_APP", ""), str(HERE.parents[2])):   # the app (star/)
    if candidate and candidate not in sys.path:
        sys.path.insert(0, candidate)

from nightschool import judge as J                                     # noqa: E402
from . import bank, bank_domain, exact, harness, seeds                 # noqa: E402

LANG_NAMES = {"python": "Python 3", "javascript": "JavaScript (Node)", "typescript": "TypeScript (strict)", "cpp": "C++17",
              "csharp": "C# (.NET 8)", "java": "Java 21", "go": "Go", "rust": "Rust", "lua": "Lua 5.4", "gdscript": "GDScript (Godot 4)"}
TAGS = {"python": "python", "javascript": "javascript", "typescript": "typescript", "cpp": "cpp", "csharp": "csharp", "java": "java",
        "go": "go", "rust": "rust", "lua": "lua", "gdscript": "gdscript", "glsl": "glsl", "hlsl": "hlsl", "c": "c"}


def code_task(p: dict, lang: str, date: str, reference: str, flavor: str = "") -> dict:
    sig = harness.signature(lang, p["fn"], p["params"], p["ret"])
    cases = bank.cases_of(p)
    tests = harness.render(lang, p["fn"], p["params"], p["ret"], cases)
    where = harness.container(lang)
    prompt = (f"{flavor}Write this function in {LANG_NAMES[lang]}:\n\n`{sig}`\n\n{p['desc']}\n\n"
              f"Put it at {where}. Reply with exactly one fenced ```{TAGS[lang]} code block that contains only the code "
              f"(the function and any helpers or imports it needs; no main function, no test code, no printing).")
    if lang == "cpp":
        prompt += " Include the standard headers you use."
    if lang == "go":
        prompt += " Start with `package main` and import what you use."
    auto = {"language": lang, "code": False, "compile": False, "judge": {"tests": tests, "expect": len(cases), "run_s": 10},
            "forbid": [{"id": "no_main", "scope": "code", **p.get("forbid_main", {"re": "(?!x)x"}), "why": "no main program"}]}
    auto["forbid"] = [f for f in auto["forbid"] if f.get("re") != "(?!x)x"] + list(p.get("forbid", []))
    auto["require"] = list(p.get("require", {}).get(lang, []))
    if not auto["forbid"]:
        del auto["forbid"]
    if not auto["require"]:
        del auto["require"]
    return {
        "id": f"multi-code-{lang}-{p['fn'].replace('_', '-')}",
        "category": f"multi-code-{lang}",
        "difficulty": p.get("difficulty", 1),
        "goal": f"{p['fn']} in {LANG_NAMES[lang]}",
        "prompt": prompt,
        "run_mode": "judge",
        "hard_fail": ["unit tests fail in the judge"],
        "auto": auto,
        "source": "multi-school-" + date,
        "family": p["family"],
        "topic": p["fn"],
        "required_evidence": ["answer.md", "check-results.json"],
        "pass_conditions": ["every unit test passes in the judge container"],
        "_reference": f"```{TAGS[lang]}\n{reference.rstrip()}\n```\n",
        "_trivial": f"```{TAGS[lang]}\n{harness.wrap_reference(lang, harness.stub(lang, p['fn'], p['params'], p['ret']))}```\n",
    }


MUTATIONS = [
    (r"<=", "<"), (r"(?<![<>=!])<(?![=<])", "<="), (r">=", ">"), (r"(?<![<>=!-])>(?![=>])", ">="),
    (r"(?<![+])\+(?![+=])", "-"), (r"(?<![-])-(?![-=>])", "+"), (r"\*(?![*=/])", "+"),
    (r"% 26", "% 25"), (r"% 10", "% 9"), (r"/ 2\b", "/ 3"), (r"// 2\b", "// 3"), (r"\b100\b", "10"), (r"\b26\b", "25"),
    (r"\b0\b(?=\s*[,;)])", "1"), (r"\b1\b(?=\s*[,;)])", "0"), (r"==", "!="), (r"&&", "||"), (r"\band\b", "or"),
]


def mutants(code: str, r: random.Random) -> list[str]:
    """Code variants with one small change each (a plausible bug), in random order."""
    out = []
    for pattern, replacement in MUTATIONS:
        hits = list(re.finditer(pattern, code))
        for hit in hits[:3]:
            out.append(code[:hit.start()] + replacement + code[hit.end():])
    r.shuffle(out)
    return [m for m in out if m != code]


def debug_task(base: dict, buggy: str, lang: str) -> dict:
    task = json.loads(json.dumps({k: v for k, v in base.items()}))
    task["id"] = base["id"].replace("multi-code-", "multi-debug-")
    task["category"] = f"multi-debug-{lang}"
    task["goal"] = "find and fix the bug: " + base["goal"]
    task["prompt"] = (f"This {LANG_NAMES[lang]} function should do the following but has ONE bug.\n\n{base['prompt'].split(chr(10) + chr(10), 1)[1].split('Put it at')[0].strip()}\n\n"
                      f"```{TAGS[lang]}\n{buggy.rstrip()}\n```\n\nFind the bug and reply with the corrected code in exactly one fenced ```{TAGS[lang]} code block "
                      f"(complete function, no test code), then one sentence naming the bug.")
    task["_trivial"] = f"```{TAGS[lang]}\n{buggy.rstrip()}\n```\n"
    return task


class Verifier:
    def __init__(self, judge):
        self.judge = judge
        self.jobs = 0

    def score(self, task: dict, answer: str):
        self.jobs += 1
        return J.score_judge_task(task, answer, self.judge)

    def check(self, task: dict) -> str:
        """"" when the task is sound, else the reason."""
        ref = self.score(task, task["_reference"])
        if not ref.passed:
            return "reference fails: " + "; ".join(ref.reasons)[:200]
        triv = self.score(task, task["_trivial"])
        if triv.passed:
            return "trivial answer passes"
        return ""


def ts_to_js(judge, ts_code: str) -> str:
    result = judge.run("ts2js", {"main.ts": ts_code}, run_s=20)
    if not result.get("ok"):
        raise RuntimeError("ts2js failed: " + (result.get("steps") or [{}])[-1].get("stderr", "")[:200])
    js = result["stdout"]
    js = re.sub(r'^"use strict";\n', "", js)
    js = re.sub(r"^Object\.defineProperty\(exports.*\n", "", js, flags=re.M)
    return js.strip() + "\n"


def build(pool: Path, queue: str, date: str, only: set[str], limit: int) -> dict:
    judge = J.Judge(queue)
    verifier = Verifier(judge)
    families: dict[str, list[dict]] = {}
    rejected: list[tuple[str, str]] = []
    seen_prompts: set[str] = set()
    started = time.monotonic()

    def keep(task: dict, family_file: str) -> bool:
        h = hashlib.sha256(" ".join(task["prompt"].lower().split()).encode()).hexdigest()
        if h in seen_prompts:
            rejected.append((task["id"], "duplicate prompt"))
            return False
        why = verifier.check(task)
        if why:
            rejected.append((task["id"], why))
            return False
        seen_prompts.add(h)
        families.setdefault(family_file, []).append(task)
        return True

    problems = list(bank.PROBLEMS) + list(bank_domain.PROBLEMS)
    if limit:
        problems = problems[:limit]
    if "code" in only or "debug" in only:
        for p in problems:
            refs = dict(p["refs"])
            if "typescript" in refs and "javascript" not in refs and p.get("js", True):
                try:
                    refs["javascript"] = ts_to_js(judge, refs["typescript"])
                except RuntimeError as exc:
                    rejected.append((p["fn"] + "/javascript", str(exc)[:120]))
            for lang, ref in refs.items():
                reference = harness.wrap_reference(lang, ref)
                task = code_task(p, lang, date, reference, p.get("flavor", ""))
                family_file = p.get("file", "code-" + lang)
                if "code" in only and not keep(task, family_file):
                    continue
                if "debug" in only:
                    r = random.Random(task["id"])
                    for buggy in mutants(ref, r)[:6]:
                        wrapped = harness.wrap_reference(lang, buggy)
                        probe = verifier.score(task, f"```{TAGS[lang]}\n{wrapped}```\n")
                        if probe.passed or any(c.id == "compile" and not c.ok for c in probe.checks) or \
                                any("did not load" in str(c.detail) or "crashed" in str(c.detail) for c in probe.checks if not c.ok):
                            continue                    # not a bug (equivalent), or not even compiling: pick another
                        if keep(debug_task(task, wrapped, lang), family_file.replace("code-", "debug-")):
                            break
    if "exact" in only:
        for task in exact.make_tasks(date):
            keep(task, "exact-" + task["family"])
    if "seed" in only:
        for task in seeds.make_tasks(date):
            keep(task, task["_file"])
            task.pop("_file", None)

    pool.mkdir(parents=True, exist_ok=True)
    refs_dir = pool.parent / "conductor"
    refs_dir.mkdir(parents=True, exist_ok=True)
    report_dir = pool.parent / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(refs_dir / f"multi-references-{date}.jsonl", "w", encoding="utf-8", newline="\n") as refs:
        for family_file, tasks in sorted(families.items()):
            rows = []
            for task in tasks:
                refs.write(json.dumps({"id": task["id"], "reference": task["_reference"]}, ensure_ascii=False) + "\n")
                rows.append({k: v for k, v in task.items() if not k.startswith("_")})
            path = pool / f"multi-{family_file}-{date}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
            total += len(rows)
    lines = [f"# multi-school build {date}", "", f"verified tasks: {total}; rejected: {len(rejected)}; judge jobs: {verifier.jobs}; "
             f"minutes: {(time.monotonic() - started) / 60:.1f}", "", "| file | tasks |", "|---|---|"]
    lines += [f"| multi-{f}-{date}.json | {len(t)} |" for f, t in sorted(families.items())]
    if rejected:
        lines += ["", "## rejected", ""] + [f"- {i}: {w}" for i, w in rejected]
    (report_dir / f"multi-build-{date}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"total": total, "rejected": rejected, "files": {f: len(t) for f, t in families.items()}, "jobs": verifier.jobs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--pool", required=True)
    b.add_argument("--queue", default=os.environ.get("STAR_NS_JUDGE_DIR", J.DEFAULT_QUEUE))
    b.add_argument("--date", default=time.strftime("%Y%m%d"))
    b.add_argument("--only", default="code,debug,exact,seed")
    b.add_argument("--limit", type=int, default=0, help="first N bank problems only (a quick check)")
    args = ap.parse_args(argv)
    result = build(Path(args.pool), args.queue, args.date, set(args.only.split(",")), args.limit)
    print(json.dumps({"total": result["total"], "files": result["files"], "jobs": result["jobs"], "rejected": len(result["rejected"])}, indent=1))
    for task_id, why in result["rejected"][:80]:
        print("REJECTED", task_id, "|", why)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
