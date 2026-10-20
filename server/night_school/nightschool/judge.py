"""Multi-language practice: the client of the judge container and the scorer for tasks that name a language.

A task of the new families is an ordinary pool row with `run_mode: "judge"` (older night-school code drops it
cleanly as an unknown run mode) and an `auto` block:
  language   python | javascript | typescript | c | cpp | csharp | java | go | rust | lua | gdscript | glsl | hlsl
  judge      {"tests": "<harness source appended to / compiled with the answer>", "expect": <passes>, "run_s": 10}
             the harness prints "@@PASS name" / "@@FAIL name: detail" lines and "@@DONE passed/total"
  answer     {"value": "...", "tolerance": 1e-3, "kind": "number|text|list"}   exact-answer task (no code run);
             the answer's last line "ANSWER: <value>" is compared
  require / forbid   regex items as in Luau tasks (scope "code" = the fenced block of the task's language, "body")
The judge is a shared folder (settings: STAR_NS_JUDGE_DIR, default /data/star-re/star-judge/queue): a job file in,
a result file out; the code runs in the `star-judge` LXD container (no network device, limits), see
server/night_school/judge/judge_runner.py and docs/agents/multi-school-20261018.md.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import time
import uuid

LANGUAGES = {"python", "javascript", "typescript", "c", "cpp", "csharp", "java", "go", "rust", "lua", "gdscript",
             "glsl", "hlsl"}
FENCE_TAGS = {
    "python": ("python", "py", "python3"), "javascript": ("javascript", "js", "node"), "typescript": ("typescript", "ts"),
    "c": ("c",), "cpp": ("cpp", "c++", "cxx", "cc"), "csharp": ("csharp", "cs", "c#"), "java": ("java",),
    "go": ("go", "golang"), "rust": ("rust", "rs"), "lua": ("lua", "luau"), "gdscript": ("gdscript", "gd", "godot"),
    "glsl": ("glsl", "frag", "vert"), "hlsl": ("hlsl",),
}
# The answer's code goes to the file the judge recipe reads (judge_runner.RECIPES); the harness is appended to it or
# put in a second file (java: Main.java; go: main.go; gdscript: test.gd).
MAIN_FILE = {"python": "main.py", "javascript": "main.js", "typescript": "main.ts", "c": "main.c", "cpp": "main.cpp",
             "csharp": "main.cs", "java": "Solution.java", "go": "solution.go", "rust": "main.rs", "lua": "main.lua",
             "gdscript": "solution.gd", "glsl": "shader.frag", "hlsl": "shader.hlsl"}
TEST_FILE = {"java": "Main.java", "go": "main.go", "gdscript": "test.gd"}
DEFAULT_QUEUE = "/opt/star/learning/judge"
PASS_LINE = re.compile(r"^@@PASS\b", re.M)
FAIL_LINE = re.compile(r"^@@FAIL\b(.*)$", re.M)
DONE_LINE = re.compile(r"^@@DONE\s+(\d+)\s*/\s*(\d+)", re.M)
ANSWER_LINE = re.compile(r"^\s*\**\s*ANSWER\s*\**\s*[:=]\s*\**\s*(.+?)\s*\**\s*$", re.M | re.I)
_PRIVATE = re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))(?:\.\d{1,3}){2,3}\b")


def judge_dir() -> str:
    """The shared queue folder, "" when this worker has no judge (PC, server 2): judge tasks are then left out."""
    path = os.environ.get("STAR_NS_JUDGE_DIR", DEFAULT_QUEUE)
    return path if path and Path(path).is_dir() else ""


def is_judge_task(task: dict) -> bool:
    return task.get("run_mode") == "judge" or bool((task.get("auto") or {}).get("language"))


def language_of(task: dict) -> str:
    return str((task.get("auto") or {}).get("language") or "")


def pick_with_share(ordered: list[dict], state: dict, share: float) -> dict | None:
    """The first task in priority order, except that judge tasks are held back while they already took more than
    `share` of this worker's answers (STAR_NS_MULTI_SHARE, default 0.5): Luau practice is never starved."""
    if not ordered:
        return None
    first = ordered[0]
    if not is_judge_task(first) or not 0 < share < 1:
        return first
    counters = state.get("counters", {})
    total, multi = counters.get("tasks_tried", 0), counters.get("multi_tried", 0)
    if total == 0 or multi / total <= share:
        return first
    return next((t for t in ordered if not is_judge_task(t)), first)


class Judge:
    def __init__(self, queue: str, *, poll_s: float = 0.25):
        self.queue, self.poll_s = Path(queue), poll_s

    def run(self, language: str, files: dict[str, str], *, run_s: int = 10, wait_s: float = 150.0) -> dict:
        """One job: returns the runner's result dict; {"error": ...} when the judge did not answer in time."""
        job_id = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:10]
        tmp = self.queue / (job_id + ".tmp")
        tmp.write_text(json.dumps({"language": language, "files": files, "run_s": run_s}), encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.queue / (job_id + ".job.json"))
        result_path = self.queue / (job_id + ".result.json")
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if result_path.is_file():
                try:
                    data = json.loads(result_path.read_text(encoding="utf-8"))
                finally:
                    try:
                        result_path.unlink()
                    except OSError:
                        pass
                return data
            time.sleep(self.poll_s)
        for suffix in (".job.json", ".running.json"):
            try:
                (self.queue / (job_id + suffix)).unlink()
            except OSError:
                pass
        return {"ok": False, "error": "judge did not answer in time", "steps": [], "stdout": ""}


# --- reading the answer ---------------------------------------------------------------------------------------
_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9+#_-]*)[^\n]*\n(.*?)```", re.S)


def code_blocks(body: str, language: str) -> list[str]:
    """Fenced blocks tagged for the language; if there are none, every untagged fenced block."""
    tags = set(FENCE_TAGS.get(language, (language,)))
    tagged = [m.group(2) for m in _FENCE.finditer(body) if m.group(1).lower() in tags and m.group(2).strip()]
    if tagged:
        return tagged
    return [m.group(2) for m in _FENCE.finditer(body) if not m.group(1) and m.group(2).strip()]


def strip_fences(body: str) -> str:
    return _FENCE.sub(" ", body)


def final_answer(body: str) -> str:
    found = ANSWER_LINE.findall(strip_fences(body)) or ANSWER_LINE.findall(body)
    return found[-1].strip().strip("`").strip() if found else ""


def _numbers(text: str) -> list[float] | None:
    parts = re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
    try:
        return [float(p) for p in parts] if parts else None
    except ValueError:
        return None


def answer_matches(given: str, spec: dict) -> tuple[bool, str]:
    """Exact-answer comparison: numbers (and number lists) within a tolerance, text after normalisation."""
    want = str(spec.get("value", ""))
    kind = spec.get("kind", "number")
    if not given:
        return False, "no final 'ANSWER:' line"
    if kind in ("number", "list"):
        a, b = _numbers(given), _numbers(want)
        if a is None or b is None or len(a) != len(b):
            return False, f"expected {len(b or [])} number(s)"
        tol = float(spec.get("tolerance", 1e-6))
        ok = all(math.isclose(x, y, rel_tol=tol, abs_tol=tol) for x, y in zip(a, b))
        return ok, "" if ok else "wrong value"
    norm = lambda s: " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())   # noqa: E731
    ok = norm(given) == norm(want) or (spec.get("contains") and norm(want) in norm(given))
    return bool(ok), "" if ok else "wrong answer"


def _scope_text(scope: str, blocks: list[str], body: str) -> str:
    if scope == "body":
        return body
    if scope == "prose":
        return strip_fences(body)
    return "\n".join(blocks)


def pattern_checks(auto: dict, blocks: list[str], body: str):
    from star.eval_checks import Check
    checks = []
    for item in [*auto.get("require", []), *auto.get("require_any", [])]:
        text = _scope_text(item.get("scope", "code"), blocks, body)
        patterns = item["any"] if "any" in item else [item["re"]]
        flags = re.M | (re.I if "i" in item.get("flags", "") else 0) | (re.S if "s" in item.get("flags", "") else 0)
        ok = any(re.search(p, text, flags) for p in patterns)
        checks.append(Check("require:" + item["id"], ok, "" if ok else item.get("why", "pattern not found")))
    for item in auto.get("forbid", []):
        text = _scope_text(item.get("scope", "code"), blocks, body)
        patterns = item["any"] if "any" in item else [item["re"]]
        flags = re.M | (re.I if "i" in item.get("flags", "") else 0) | (re.S if "s" in item.get("flags", "") else 0)
        hit = next((m for m in (re.search(p, text, flags) for p in patterns) if m), None)
        checks.append(Check("forbid:" + item["id"], hit is None,
                            "" if hit is None else item.get("why", "forbidden pattern") + f" (found: {hit.group(0)[:60]!r})"))
    return checks


def build_files(language: str, code: str, tests: str) -> dict[str, str]:
    if language in TEST_FILE:
        return {MAIN_FILE[language]: code, TEST_FILE[language]: tests}
    if language == "glsl":                                             # tests = the stage: frag | vert | comp
        return {"shader." + (tests.strip() or "frag"): code}
    if language == "hlsl":
        return {MAIN_FILE[language]: code}
    return {MAIN_FILE[language]: code.rstrip("\n") + "\n\n" + tests}


def _short(text: str, limit: int = 160) -> str:
    text = _PRIVATE.sub("<private-address>", " ".join(text.split()))
    return text[:limit]


def judge_checks(result: dict, expect: int | None):
    """Checks from a judge result: compile (when the recipe has one), the run, the harness lines."""
    from star.eval_checks import Check, InfraError
    if result.get("error"):
        if result["error"].startswith("judge did not answer") or result["error"] == "runner restarted":
            raise InfraError("judge: " + result["error"])
        return [Check("judge", False, _short(result["error"]))]
    checks = []
    steps = result.get("steps") or []
    if result.get("phase") == "compile":
        last = steps[-1] if steps else {}
        return [Check("compile", False, _short((last.get("stderr") or "") + " " + (last.get("stdout") or "")) or "compile failed")]
    if steps and len(steps) > 1:
        checks.append(Check("compile", True))
    run = steps[-1] if steps else {}
    out = run.get("stdout") or ""
    if run.get("timed_out"):
        return checks + [Check("unit_tests", False, "timed out (an endless loop or too slow)")]
    done = DONE_LINE.search(out)
    fails = FAIL_LINE.findall(out)
    passes = len(PASS_LINE.findall(out))
    if run.get("rc", 1) != 0 and not done:
        detail = _short((run.get("stderr") or "") or out) or f"exit status {run.get('rc')}"
        return checks + [Check("unit_tests", False, "the code did not load or crashed: " + detail)]
    if not done:
        return checks + [Check("unit_tests", False, "the test harness did not finish (no @@DONE line)")]
    got, total = int(done.group(1)), int(done.group(2))
    want = expect if expect is not None else total
    ok = got >= want and not fails and run.get("rc", 1) == 0
    detail = "" if ok else (f"{got}/{total} passed; first failure:" + _short(fails[0], 120) if fails else f"{got}/{total} passed")
    checks.append(Check("unit_tests", ok, detail))
    return checks


def score_judge_task(task: dict, answer: str, judge: Judge | None):
    """TaskScore for a judge task (the equivalent of star.eval_checks.score_answer for Luau tasks)."""
    from star.eval_checks import Check, InfraError, TaskScore, split_answer
    auto = task.get("auto") or {}
    language = language_of(task)
    score = TaskScore()
    body, _ = split_answer(answer or "")
    if not body.strip():
        score.checks.append(Check("answer", False, "empty answer"))
        return score
    exact = auto.get("answer")
    blocks = code_blocks(body, language) if language else []
    score.blocks = len(blocks)
    if exact:
        ok, why = answer_matches(final_answer(body), exact)
        score.checks.append(Check("answer", ok, why))
    spec = auto.get("judge")
    if spec is not None and language:
        if not blocks:
            score.checks.append(Check("code_block", False, f"no fenced {language} code block in the answer"))
        else:
            if judge is None:
                raise InfraError("no judge configured for a task with a language")
            code = max(blocks, key=len) if spec.get("block", "longest") == "longest" else blocks[0]
            files = build_files(language, code, spec.get("tests", ""))
            started = time.monotonic()
            result = judge.run(language, files, run_s=int(spec.get("run_s", 10)))
            score.timings["judge_s"] = round(time.monotonic() - started, 2)
            score.checks.append(Check("code_block", True))
            score.checks.extend(judge_checks(result, spec.get("expect")))
    score.checks.extend(pattern_checks(auto, blocks, body))
    return score
