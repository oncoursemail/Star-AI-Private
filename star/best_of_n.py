"""Generate several, test, keep what works: verification-driven best-of-N for code answers.

For a code request (Roblox/Luau, Python, or a JSON map plan) STAR can write N candidate answers at once on
the model slots that are free, run every candidate through the checks STAR already has, and keep the one
that passes the most. The owner sees the best candidate with its evidence ("passed 6/6 checks").

    plan_samples()     how many candidates: 1 for easy or non-code turns, 2-8 for harder code requests,
                       never more than the free model slots allow (adaptive N)
    allocate()         which model writes each extra candidate (the main model's free slots first, then the
                       quick model's, then any other code-capable model the caller passes in, e.g. brain 2)
    BestOfN            the run: extra candidates and the shared unit tests start while the main answer is
                       written; then every candidate is checked, ranked, judged on a tie, and repaired once
                       when none passes
    Checker classes    LuauChecker (fenced block, static compile/type check by STAR Knowledge, luau-analyze,
                       StyLua parse, STAR's Luau lints incl. lifetime + SEC- server-trust rules, Roblox API
                       names from a Studio API dump, generated unit tests in the server's Luau VM sandbox),
                       PythonChecker (syntax by compile(), never executed here; tests only in a configured
                       sandbox), MapPlanChecker (star.map_plan dry run)

Honesty rules (the same as star/doc_grounding.py):
  * a check that could not run is reported as "not run", never as passed;
  * the evidence line names the checks that ran and what they cover; the code is never said to have been
    run in Roblox; generated unit tests are model-written and are labelled so;
  * nothing here executes model code on this PC: Luau unit tests run only through a sandbox runner
    (star/eval_sandbox.ContainerSandbox: the server's LXD container, user `star`, prlimit + timeout), and
    Python code is only compiled (`compile`, no exec) unless a sandbox runner is configured.

Everything that talks to a model, a server or a sandbox is passed in as a callable, so the selection rules
are unit-tested with fakes and the same rules run unchanged against the real STAR Server.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from time import monotonic
from typing import Any, Awaitable, Callable

from . import candidate_pool

MIN_N, MAX_N = 1, 8
DEFAULT_MAX_N = 4
ENV_VAR = "STAR_BEST_OF_N"              # off | auto | 2..8 (forces N); the desktop setting wins when it is on
SSH_ENV_VARS = ("STAR_BON_SSH", "STAR_EVAL_SSH")   # operator's sandbox target for generated unit tests
API_DUMP_ENV = "STAR_ROBLOX_API_DUMP"   # path of a Studio --fullApi JSON dump (optional)
BEST_MARKER = "**Best of"                # STAR's evidence line starts with this; a model may not write it
MAX_TEST_CHARS = 4000
MAX_TESTS = 10
MAX_DETAIL = 160
TEMPERATURES = (0.7, 0.9, 0.5, 1.0, 0.6, 0.8, 0.4)   # extra candidates; candidate 1 is the main answer (temp 0)

# ------------------------------------------------------------------------------------------------ request kind

_LUAU_WORDS = re.compile(
    r"```[ \t]*(?:lua|luau)\b|\b(?:luau?|roblox|studio|modulescript|localscript|serverscriptservice|"
    r"replicatedstorage|remoteevent|remotefunction|datastore(?:service)?|humanoid|tweenservice|"
    r"runservice|userinputservice|workspace|instance\.new|getservice)\b", re.I)
_PYTHON_WORDS = re.compile(r"```[ \t]*(?:python|py)\b|\b(?:python|pytest|pandas|numpy|django|flask|fastapi)\b|"
                           r"\.py\b", re.I)
_MAP_WORDS = re.compile(r"\bmap[ -]?plan\b|\bblockout\b|\bobby\s+(?:map|layout|course)\b", re.I)
_WRITE = re.compile(
    r"\b(?:write|create|make|implement|build|code|script|fix|refactor|rewrite|add|generate|give\s+me|"
    r"need|module|function|class|system|handler|convert|port|optimi[sz]e)\b", re.I)
_EXPLAIN_ONLY = re.compile(r"^\s*(?:what\s+(?:is|are|does)|why\b|explain\b|how\s+does\b|when\s+should\b|"
                           r"is\s+it\b|can\s+you\s+explain\b|tell\s+me\s+about\b)", re.I)


def code_kind(prompt: str) -> str | None:
    """'luau', 'python', 'map_plan' or None (not a request to write code STAR can check)."""
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    text = prompt[:6000]
    if _EXPLAIN_ONLY.search(text) and "```" not in text and not re.search(
            r"\b(?:write|create|make|implement|fix|give\s+me)\b", text, re.I):
        return None
    if not _WRITE.search(text):
        return None
    if _MAP_WORDS.search(text):
        return "map_plan"
    if _LUAU_WORDS.search(text):
        return "luau"
    if _PYTHON_WORDS.search(text):
        return "python"
    return None


# ------------------------------------------------------------------------------------------------ adaptive N

_HARD_TOPICS = re.compile(
    r"\b(?:datastore|session\s*lock|profile|remote(?:event|function)?s?|validat\w*|anti[- ]?(?:cheat|exploit)|"
    r"exploit\w*|secure|security|rate[- ]?limit\w*|state\s*machine|pathfinding|inventory|trading|shop|"
    r"metatable|oop|class(?:es)?|inherit\w*|coroutine|promise|signal|queue|cache|serializ\w*|"
    r"algorithm|recurs\w*|parser?|physics|raycast\w*|replicat\w*|matchmak\w*|round\s+system|"
    r"leaderboard|combat|hitbox|cooldown|debounce|edge\s+cases?|thread[- ]?safe|concurren\w*|"
    r"performance|optimi[sz]\w*|memory\s+leak)\b", re.I)
_EASY = re.compile(r"\b(?:hello\s+world|print\s+(?:a|the)\b|one[- ]liner|simple|basic|quick|tiny|small)\b", re.I)
_EXPLICIT = re.compile(r"(?:^|\s)/best\b|\bbest[- ]of[- ](\d)\b|\b(?:test\s+it|make\s+sure\s+it\s+works|"
                       r"double[- ]check|verify\s+it|bulletproof|production[- ]ready)\b", re.I)
_REQUIREMENT_LINE = re.compile(r"(?m)^\s*(?:[-*•]|\d{1,2}[.)])\s+\S")
_CLAUSE = re.compile(r"\b(?:must|should|shall|needs?\s+to|has\s+to|also|then|while|unless|except|only\s+if)\b", re.I)


@dataclass(frozen=True)
class SamplePlan:
    n: int                        # candidates in total, including the main answer
    kind: str | None              # 'luau' | 'python' | 'map_plan' | None
    difficulty: float             # 0..1, the heuristic score
    reasons: tuple[str, ...] = ()
    capacity: int | None = None   # extra candidates the free slots allow (None: unknown)

    @property
    def active(self) -> bool:
        return self.n > 1 and self.kind is not None


def difficulty(prompt: str) -> tuple[float, tuple[str, ...]]:
    """A cheap, deterministic difficulty score for a code request (0 easy .. 1 hard) and why."""
    text = prompt[:6000] if isinstance(prompt, str) else ""
    score, reasons = 0.15, []
    topics = sorted({m.group(0).lower() for m in _HARD_TOPICS.finditer(text)})
    if topics:
        score += min(0.36, 0.12 * len(topics))
        reasons.append("topics: " + ", ".join(topics[:4]))
    requirements = len(_REQUIREMENT_LINE.findall(text)) + len(_CLAUSE.findall(text))
    if requirements:
        score += min(0.3, 0.06 * requirements)
        reasons.append(f"{requirements} requirement(s)")
    words = len(text.split())
    if words > 60:
        score += min(0.2, (words - 60) / 400)
        reasons.append(f"{words} words")
    if "```" in text:
        score += 0.1
        reasons.append("includes code")
    if _EASY.search(text) and words < 40:
        score -= 0.25
        reasons.append("asked for something simple")
    return max(0.0, min(1.0, round(score, 3))), tuple(reasons)


def requested_n(prompt: str) -> int | None:
    """N the owner asked for in the message: '/best' (= the maximum) or 'best of 5'; None otherwise."""
    if not isinstance(prompt, str):
        return None
    found = _EXPLICIT.search(prompt)
    if not found:
        return None
    if found.group(1):
        return max(2, min(MAX_N, int(found.group(1))))
    return -1   # asked for checking, not a number: the caller's maximum


def plan_samples(prompt: str, *, enabled: bool, max_n: int = DEFAULT_MAX_N, capacity: int | None = None,
                 kind: str | None = None, forced: int | None = None) -> SamplePlan:
    """How many candidates this turn gets. `capacity` = extra candidates the free slots allow."""
    max_n = max(MIN_N, min(MAX_N, int(max_n))) if type(max_n) is int else DEFAULT_MAX_N
    kind = code_kind(prompt) if kind is None else kind
    if not enabled or kind is None:
        return SamplePlan(1, kind, 0.0, ("off" if not enabled else "not a code request",), capacity)
    score, reasons = difficulty(prompt)
    asked = requested_n(prompt) if forced is None else forced
    if asked:
        n = max_n if asked < 0 else min(asked, MAX_N)
        reasons = (*reasons, "requested")
    elif score < 0.3:
        n = 1
    elif score < 0.5:
        n = 2
    elif score < 0.7:
        n = 3
    else:
        n = max(4, round(max_n * score))
    n = max(MIN_N, min(n, max_n if not asked else MAX_N))
    if capacity is not None:
        if capacity <= 0 and n > 1:
            reasons = (*reasons, "no free model slot")
        n = min(n, 1 + max(0, capacity))
    return SamplePlan(n, kind, score, tuple(reasons), capacity)


def mode_from_env(environ=None) -> tuple[bool, int | None]:
    """(enabled, forced N) from STAR_BEST_OF_N: off (default) | auto | on | 2..8."""
    value = (os.environ if environ is None else environ).get(ENV_VAR, "").strip().lower()
    if value in ("auto", "on", "1", "true", "yes"):
        return True, None
    if value.isdigit() and 2 <= int(value) <= MAX_N:
        return True, int(value)
    return False, None


# ------------------------------------------------------------------------------------------------ where to sample

@dataclass(frozen=True)
class Target:
    model: str
    free: int                 # slots free right now (after the main answer took its slot, for the main model)
    client: Any = None        # None: the caller's default client


def capacity_from_planner(status: dict | None, machine: str = "brain1") -> dict[str, int]:
    """Free slots per model from the resource planner's /v1/status (`machines.<m>.models.<model>: [slot]`)."""
    found: dict[str, int] = {}
    try:
        models = ((status or {}).get("machines") or {}).get(machine, {}).get("models") or {}
        for model, slots in models.items():
            if isinstance(model, str) and isinstance(slots, list):
                found[model] = sum(1 for s in slots if isinstance(s, dict) and not s.get("processing"))
    except AttributeError:
        return {}
    return found


def allocate(extra: int, targets: list[Target]) -> list[Target]:
    """Which target writes each extra candidate: round robin over targets with free slots, in the given order."""
    pool = [[t, max(0, int(t.free))] for t in targets if t.model]
    chosen: list[Target] = []
    while len(chosen) < extra and any(left for _, left in pool):
        for entry in pool:
            if len(chosen) >= extra:
                break
            if entry[1] > 0:
                chosen.append(entry[0])
                entry[1] -= 1
    return chosen


# ------------------------------------------------------------------------------------------------ candidates

@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str               # pass | fail | skip
    detail: str = ""
    hard: bool = True         # a hard failure means "does not work"; soft ones (lints) only lower the rank

    @property
    def ran(self) -> bool:
        return self.status in ("pass", "fail")


@dataclass
class Candidate:
    index: int                # 1 = the main answer
    model: str
    temperature: float = 0.0
    answer: str = ""
    error: str = ""
    seconds: float = 0.0
    code: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    unit: tuple[int, int] | None = None     # (passed, counted) generated unit tests
    unit_failed: tuple[str, ...] = ()
    unit_raw: dict | None = None           # name -> bool, before the agreement filter
    unit_error: str = ""
    judge_rank: int | None = None
    repaired: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.answer.strip())

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == "pass")

    @property
    def ran(self) -> int:
        return sum(1 for c in self.checks if c.ran)

    @property
    def hard_failures(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail" and c.hard)

    @property
    def soft_failures(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail" and not c.hard)

    def summary(self) -> dict:
        return {"index": self.index, "model": self.model, "temperature": self.temperature,
                "seconds": round(self.seconds, 1), "error": self.error[:120], "passed": self.passed,
                "ran": self.ran, "hard_failures": self.hard_failures, "unit": list(self.unit) if self.unit else None,
                "repaired": self.repaired, "judge_rank": self.judge_rank,
                "checks": [{"name": c.name, "status": c.status, "detail": c.detail[:MAX_DETAIL]} for c in self.checks]}


def rank_key(c: Candidate):
    """Sort key, best first: works (no hard failure), fewer hard failures, unit-test share, checks passed share,
    fewer soft findings, the judge's preference, then the earlier candidate (the main answer wins ties)."""
    unit_share = (c.unit[0] / c.unit[1]) if c.unit and c.unit[1] else 0.0
    share = c.passed / c.ran if c.ran else 0.0
    return (0 if c.ok else 1, c.hard_failures, -unit_share, -share, c.soft_failures,
            c.judge_rank if c.judge_rank is not None else 99, c.index)


# ------------------------------------------------------------------------------------------------ reading answers

_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n(.*?)```", re.S)
_FENCE_LINE = re.compile(r"^[ \t]*```", re.M)
_LOOKS_LIKE_LUAU = re.compile(r"\b(?:local|function|end|then|return)\b")
_ROBLOX_CODE = re.compile(r"\b(?:game|workspace|script|plugin|Instance|Enum|Vector3|Vector2|CFrame|Color3|"
                          r"BrickColor|UDim2?|TweenInfo|Ray|RaycastParams|NumberSequence|ColorSequence)\b")
_LOOKS_LIKE_PY = re.compile(r"^\s*(?:def|class|import|from)\s", re.M)


def fenced(answer: str, kind: str) -> list[str]:
    """Code blocks of the request's language (labelled ones win, unlabelled ones that look right count)."""
    labels = {"luau": ("lua", "luau"), "python": ("python", "py", "python3"), "map_plan": ("json",)}[kind]
    blocks = [(m.group(1).lower(), m.group(2)) for m in _FENCE.finditer(answer or "") if m.group(2).strip()]
    labelled = [code for label, code in blocks if label in labels]
    if labelled:
        return labelled
    looks = {"luau": _LOOKS_LIKE_LUAU.search, "python": _LOOKS_LIKE_PY.search,
             "map_plan": lambda s: s.lstrip().startswith("{")}[kind]
    return [code for label, code in blocks if not label and looks(code)]


def main_block(answer: str, kind: str) -> str:
    blocks = fenced(answer, kind)
    return max(blocks, key=len) if blocks else ""


def truncated(answer: str) -> bool:
    return len(_FENCE_LINE.findall(answer or "")) % 2 == 1


def strip_forged(answer: str) -> str:
    """A model may not write STAR's evidence line itself."""
    return (answer or "").replace(BEST_MARKER, "**Best of (model text)")


def _clean(text, limit: int = MAX_DETAIL) -> str:
    return "".join(ch if ch.isprintable() else " " for ch in str(text))[:limit]


# ------------------------------------------------------------------------------------------------ generated tests

TEST_SYSTEM = (
    "You write unit tests for a Luau ModuleScript BEFORE it exists, from the request alone. Do NOT write the module "
    "itself: another program writes it, and your tests decide whether that program is right. The tests run in a "
    "harness that already defines these helpers:\n"
    "  local M = load_answer()        -- loads the answer; returns what its chunk returns (the module table or "
    "function). load_answer({game = mockGame({...})}) injects mock globals for code that needs them\n"
    "  check(name, condition)         -- one assertion: a short sentence and a BOOLEAN expression (not a function)\n"
    "  throws(fn, ...)                -- true when fn(...) raises an error\n"
    "  deepEqual(a, b), deepCopy(t), countKeys(t)\n"
    "  Signal.new() (with :Connect(fn) and :Fire(...)), mockGame(services), mockPlayer(name, userId, coins), "
    "mockCharacter(health), node(t)\n"
    "Example for 'a module Stack with new(), push(s, v) and pop(s) that returns nil when empty':\n"
    "```luau\nlocal Stack = load_answer()\nlocal s = Stack.new()\nStack.push(s, 1)\nStack.push(s, 2)\n"
    "check(\"pop returns the last pushed value\", Stack.pop(s) == 2)\n"
    "check(\"pop then returns the earlier value\", Stack.pop(s) == 1)\n"
    "check(\"pop on an empty stack returns nil\", Stack.pop(s) == nil)\n```\n"
    "Rules: plain Luau, no Roblox engine; 3 to 8 check(...) calls on behaviour the request clearly asks for "
    "(including one edge case); use exactly the module, function and field names the request gives; keep it under "
    "40 lines; never use print, require, loadstring, getfenv, setfenv, debug or names starting with two underscores. "
    "Reply with ONLY the test code in one ```luau block. If the request cannot be tested without the Roblox engine "
    "(UI, physics, a LocalScript, Studio building) or does not name the functions to call, reply exactly NO_TESTS."
)
_CHECK_WITH_FUNCTION = re.compile(r"\bcheck\s*\([^,()]*,\s*function\b")
_WRITES_THE_MODULE = re.compile(r"\bload_answer\s*\(\s*\{[^}]*\bfunction\b", re.S)
_FORBIDDEN_TEST = re.compile(r"@@|\b__\w+|\b(?:print|require|loadstring|getfenv|setfenv|debug|dofile|loadfile)\b")


def parse_tests(reply: str) -> str | None:
    """The test body from the test writer's reply, or None (no tests, unsafe or malformed)."""
    if not isinstance(reply, str) or "NO_TESTS" in reply[:400]:
        return None
    blocks = fenced(reply, "luau")
    body = max(blocks, key=len) if blocks else ""
    if not body.strip() or len(body) > MAX_TEST_CHARS or _FORBIDDEN_TEST.search(body):
        return None
    count = len(re.findall(r"\bcheck\s*\(", body))
    if not 2 <= count <= MAX_TESTS + 2 or "load_answer" not in body:
        return None
    if _CHECK_WITH_FUNCTION.search(body) or _WRITES_THE_MODULE.search(body):
        return None    # check(name, function() ... end) never fails; a test that brings its own module tests nothing
    return body


# Run against a module that does nothing: an assertion that passes there says nothing about any candidate.
STUB_MODULE = "return {}\n"


def agreed_units(candidates: list[Candidate]) -> tuple[set[str], set[str]]:
    """(valid test names, suspect test names). A generated assertion that fails for EVERY candidate that ran is
    more likely a wrong test than N wrong programs (the CodeT idea): it is left out of the score and reported."""
    ran = [c.unit_raw for c in candidates if c.unit_raw]
    names: set[str] = set().union(*[set(r) for r in ran]) if ran else set()
    suspect = {n for n in names if len(ran) >= 2 and all(not r.get(n, False) for r in ran)}
    return names - suspect, suspect


# ------------------------------------------------------------------------------------------------ checkers

class LuauChecker:
    """The Luau checks STAR already has, each optional: a check whose tool is missing is 'skip'."""

    kind = "luau"

    def __init__(self, *, luau_check=None, analyzer=None, formatter=None, api_dump=None, runner=None,
                 prelude: str = "", prompt: str = "", lints: bool = True):
        self.luau_check, self.analyzer, self.formatter = luau_check, analyzer, formatter
        self.api_dump, self.runner, self.prelude, self.prompt, self.lints = api_dump, runner, prelude, prompt, lints

    @property
    def can_run_tests(self) -> bool:
        return self.runner is not None and bool(self.prelude)

    def static(self, code: str, answer: str) -> list[CheckResult]:
        results = [CheckResult("code block", "pass" if code and not truncated(answer) else "fail",
                               "" if code else "no fenced Luau block" if not truncated(answer) else "cut off")]
        if not code:
            return results
        if self.luau_check is not None:
            from .eval_checks import effective_errors, lenient_source
            try:
                # Pure Luau is checked as written (its own --!strict counts); code that touches the engine is
                # checked non-strict, because the service types Roblox classes as unknown (eval_checks rule).
                report = self.luau_check(lenient_source(code) if _ROBLOX_CODE.search(code) else code)
                if isinstance(report, dict) and report.get("ran") is True:
                    errors = effective_errors(report, self.prompt)
                    results.append(CheckResult("compiles and type-checks", "fail" if errors else "pass",
                                               "; ".join(f"line {e.get('line')}: {_clean(e.get('message'), 90)}"
                                                         for e in errors[:2])))
                else:
                    results.append(CheckResult("compiles and type-checks", "skip", "no verdict"))
            except (OSError, ValueError) as exc:
                results.append(CheckResult("compiles and type-checks", "skip", type(exc).__name__))
        if self.analyzer is not None:
            try:
                findings = self.analyzer(code)
                errors = [f for f in findings if f.severity == "error"]
                results.append(CheckResult("luau-analyze", "fail" if errors else "pass",
                                           "; ".join(_clean(f.message, 90) for f in errors[:2])))
            except Exception as exc:   # an external tool: never fails the run
                results.append(CheckResult("luau-analyze", "skip", type(exc).__name__))
        if self.formatter is not None:
            try:
                self.formatter(code)
                results.append(CheckResult("StyLua parses", "pass"))
            except ValueError as exc:
                results.append(CheckResult("StyLua parses", "fail" if "rejected" in str(exc) else "skip",
                                           _clean(exc, 80)))
        if self.lints:
            from .luau_lint import lint
            try:
                findings = [f for f in lint(code, external=False, safety_checks=True, server_security=True)
                            if f.severity in ("error", "warning")]
                results.append(CheckResult("Roblox lints", "fail" if findings else "pass",
                                           ", ".join(sorted({f.rule_id for f in findings}))[:MAX_DETAIL], hard=False))
            except Exception as exc:
                results.append(CheckResult("Roblox lints", "skip", type(exc).__name__, hard=False))
        if self.api_dump is not None:
            from .roblox_api_checker import check_luau_api
            try:
                found = check_luau_api(code, self.api_dump)
                results.append(CheckResult("Roblox API names", "fail" if found else "pass",
                                           "; ".join(f"{f.class_name or ''}.{f.name}" + (f" (did you mean {f.suggestion}?)"
                                                     if f.suggestion else "") for f in found[:3])))
            except Exception as exc:
                results.append(CheckResult("Roblox API names", "skip", type(exc).__name__))
        return results

    def run_tests(self, code: str, tests: str) -> tuple[dict | None, str]:
        """{assertion name: passed} from the sandbox, or (None, reason) when it could not run."""
        from .eval_checks import build_test_script, parse_test_output
        if self.runner is None:
            return None, "sandbox: not configured"
        try:
            run = self.runner.run(build_test_script(self.prelude, code, tests))
        except Exception as exc:
            return None, "sandbox: " + type(exc).__name__
        if getattr(run, "error", ""):
            return None, "sandbox: " + _clean(run.error, 80)
        outcome = parse_test_output(run.stdout or "")
        if getattr(run, "timed_out", False):
            return {"finishes within the time and memory limit": False}, ""
        if outcome.load_error:
            return {"the module loads": False}, ""
        results: dict = {}
        for name, ok in outcome.results:
            results[name] = results.get(name, True) and ok
        if outcome.error and not results:
            results["the tests run without an error"] = False
        return results, ""


class PythonChecker:
    """Python: syntax only on this PC (compile, never exec); tests only through a configured sandbox runner."""

    kind = "python"

    def __init__(self, *, runner=None):
        self.runner = runner

    @property
    def can_run_tests(self) -> bool:
        return False   # generated Python tests need a Python sandbox runner; none is wired yet

    def static(self, code: str, answer: str) -> list[CheckResult]:
        results = [CheckResult("code block", "pass" if code and not truncated(answer) else "fail",
                               "" if code else "no fenced Python block")]
        if not code:
            return results
        try:
            compile(code, "<candidate>", "exec", dont_inherit=True)   # parses and compiles; nothing runs
            results.append(CheckResult("Python syntax", "pass"))
        except (SyntaxError, ValueError) as exc:
            results.append(CheckResult("Python syntax", "fail", _clean(f"line {getattr(exc, 'lineno', '?')}: "
                                                                       f"{getattr(exc, 'msg', exc)}", 100)))
        names = _undefined_names(code)
        results.append(CheckResult("names defined", "fail" if names else "pass",
                                   ", ".join(sorted(names)[:5]), hard=False))
        return results


def _undefined_names(code: str) -> set[str]:
    """Module-level names read but never bound, imported or built in (a cheap pyflakes-like check)."""
    import ast
    import builtins
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return set()
    bound = set(dir(builtins)) | {"__name__", "__file__", "__doc__"}
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (bound if isinstance(node.ctx, (ast.Store, ast.Del)) else loaded).add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            bound.add(node.name)
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names) for n in ast.walk(tree)):
        return set()
    return loaded - bound


class MapPlanChecker:
    """A JSON map plan (star/map_plan.py): parses, matches the schema, and the offline dry run has no blocker."""

    kind = "map_plan"
    can_run_tests = False

    def static(self, code: str, answer: str) -> list[CheckResult]:
        results = [CheckResult("plan block", "pass" if code and not truncated(answer) else "fail",
                               "" if code else "no fenced JSON plan")]
        if not code:
            return results
        try:
            plan = json.loads(code)
        except ValueError as exc:
            return [*results, CheckResult("valid JSON", "fail", _clean(exc, 80))]
        results.append(CheckResult("valid JSON", "pass"))
        from .map_plan import dry_run
        report = dry_run(plan, include_operations=False)
        blockers = report.get("blockers") or []
        results.append(CheckResult("map dry run", "fail" if blockers else "pass",
                                   "; ".join(_clean(b.get("message"), 70) for b in blockers[:2])))
        warnings = report.get("warnings") or []
        results.append(CheckResult("map warnings", "fail" if warnings else "pass",
                                   "; ".join(sorted({str(w.get("code")) for w in warnings}))[:MAX_DETAIL], hard=False))
        return results


# ------------------------------------------------------------------------------------------------ the run

Sample = Callable[[Target, float], Awaitable[str]]


@dataclass
class Outcome:
    answer: str                      # the chosen answer (unchanged text of the winning candidate, or repaired)
    chosen: Candidate | None
    candidates: list[Candidate]
    tests: int = 0                   # generated unit tests that counted
    suspect_tests: int = 0
    footer: str = ""                 # the evidence paragraph to append
    changed: bool = False            # True when the answer differs from the main answer
    tests_state: str = "none"
    state: str = "single"            # single | selected | repaired | none_passed | unavailable
    verification_work: dict[str, int] = field(default_factory=dict)

    def record(self) -> dict:
        return {"state": self.state, "n": len(self.candidates), "tests": self.tests, "tests_state": self.tests_state,
                "suspect_tests": self.suspect_tests, "verification_work": dict(self.verification_work),
                "chosen": self.chosen.index if self.chosen else None,
                "candidates": [c.summary() for c in self.candidates]}


def _emit(on_event, event: dict) -> None:
    if on_event is not None:
        try:
            on_event(event)
        except Exception:
            pass


class BestOfN:
    """One best-of-N run. `start()` launches the extra candidates (and the shared unit tests) while the main
    answer is written; `finish(main_answer)` waits for them (bounded), checks, ranks and returns the Outcome.

    sample(target, temperature) -> answer text      (one extra candidate; raise on failure)
    write_tests(prompt) -> reply text                (optional; the test writer, temperature 0)
    judge(prompt, [answers]) -> index into the list  (optional; only for candidates tied on every check)
    repair(prompt, code, problems) -> code           (optional; once, when no candidate passes)
    """

    def __init__(self, plan: SamplePlan, *, prompt: str, checker, sample: Sample | None, targets: list[Target],
                 write_tests=None, judge=None, repair=None, on_event=None, clock=monotonic):
        self.plan, self.prompt, self.checker, self._sample = plan, prompt, checker, sample
        self.targets = allocate(max(0, plan.n - 1), targets)
        self._write_tests, self._judge, self._repair = write_tests, judge, repair
        self._on_event, self._clock = on_event, clock
        self._tasks: list[asyncio.Task] = []
        self._tests_task: asyncio.Task | None = None
        self.candidates: list[Candidate] = []
        self.started = False
        self.tests_state = "none"      # none | ok | refused (NO_TESTS or unsafe) | late (not written in time)

    @property
    def extra(self) -> int:
        return len(self.targets)

    def start(self) -> None:
        """Launch the extra candidates. Call from inside the running event loop; never raises."""
        if self.started or not self.plan.active or not self.targets:
            return
        self.started = True
        _emit(self._on_event, {"event": "best_of_n_started", "n": 1 + self.extra, "kind": self.plan.kind,
                               "models": [t.model for t in self.targets]})
        # The test writer goes first: a short request that should get a slot before the long candidates queue.
        if self._write_tests is not None and getattr(self.checker, "can_run_tests", False):
            self._tests_task = asyncio.ensure_future(self._tests())
        for number, target in enumerate(self.targets, 2):
            temperature = TEMPERATURES[(number - 2) % len(TEMPERATURES)]
            candidate = Candidate(number, target.model, temperature)
            self.candidates.append(candidate)
            self._tasks.append(asyncio.ensure_future(self._run_one(candidate, target)))

    async def _run_one(self, candidate: Candidate, target: Target) -> None:
        began = self._clock()
        try:
            if self._sample is None:
                raise RuntimeError("no sampler")
            text = await self._sample(target, candidate.temperature)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty answer")
            candidate.answer = strip_forged(text)
        except asyncio.CancelledError:
            candidate.error = "not finished in time"
            raise
        except Exception as exc:
            candidate.error = _clean(type(exc).__name__ + (": " + str(exc) if str(exc) else ""), 120)
        finally:
            candidate.seconds = self._clock() - began
        _emit(self._on_event, {"event": "best_of_n_candidate", "index": candidate.index,
                               "state": "written" if candidate.ok else "failed"})

    async def _tests(self) -> str | None:
        if self._write_tests is None:
            return None
        try:
            return parse_tests(await self._write_tests(self.prompt))
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    async def cancel(self) -> None:
        pending = [t for t in [*self._tasks, self._tests_task] if t is not None and not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def finish(self, main_answer: str, main_model: str, *, wait_s: float = 120.0) -> Outcome:
        """Wait at most `wait_s` for the extra candidates, then check, rank, judge and (once) repair."""
        main = Candidate(1, main_model, 0.0, answer=main_answer or "", error="" if (main_answer or "").strip() else "empty")
        if not self.started:
            return Outcome(main_answer, main, [main], state="single")
        pending = [t for t in [*self._tasks, self._tests_task] if t is not None and not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=max(0.0, wait_s))
        tests = None
        if self._tests_task is not None and self._tests_task.done() and not self._tests_task.cancelled():
            tests = self._tests_task.result()
        self.tests_state = ("none" if self._tests_task is None else "late" if not self._tests_task.done()
                            else "ok" if tests else "refused")
        await self.cancel()
        candidates = [main, *self.candidates]
        return await self.evaluate(candidates, tests)

    async def evaluate(self, candidates: list[Candidate], tests: str | None) -> Outcome:
        kind = self.plan.kind or "luau"
        # The same code can appear in several candidates (sometimes under different prose).
        # A standalone sandbox run depends on the exact source and tests, whereas static
        # checks may also inspect the *answer* (e.g. a truncated Markdown fence). Deduplicate
        # only at those safe boundaries. No persistent cache or cross-project state exists.
        static_groups: dict[tuple[str, str], list[Candidate]] = {}
        unit_groups: dict[str, list[Candidate]] = {}
        eligible = [c for c in candidates if c.ok]
        can_run_units = bool(tests and getattr(self.checker, "can_run_tests", False))
        for c in eligible:
            c.code = main_block(c.answer, kind)
            static_groups.setdefault((c.code, c.answer), []).append(c)
            if can_run_units and c.code:
                unit_groups.setdefault(c.code, []).append(c)
        semaphore = asyncio.Semaphore(3)

        async def check_static(key: tuple[str, str], members: list[Candidate]) -> None:
            async with semaphore:
                try:
                    results = await asyncio.to_thread(self.checker.static, *key)
                    if not isinstance(results, (list, tuple)) or not all(
                            isinstance(check, CheckResult) for check in results):
                        raise TypeError("invalid verifier result")
                except Exception as exc:
                    # A broken checker cannot silently certify an otherwise unchecked answer.
                    results = [CheckResult("static verification", "fail", type(exc).__name__)]
                for c in members:
                    c.checks = list(results)  # separate lists: later unit results are per candidate

        async def check_units(code: str, members: list[Candidate]) -> None:
            async with semaphore:
                try:
                    raw, error = await asyncio.to_thread(self.checker.run_tests, code, tests)
                    if raw is not None and (not isinstance(raw, dict) or not all(
                            isinstance(name, str) and type(passed) is bool for name, passed in raw.items())):
                        raise TypeError("invalid sandbox result")
                    if not isinstance(error, str):
                        raise TypeError("invalid sandbox error")
                except Exception as exc:
                    raw, error = None, "sandbox: " + type(exc).__name__
                for c in members:
                    c.unit_raw = dict(raw) if raw is not None else None
                    c.unit_error = error

        await asyncio.gather(
            *(check_static(key, members) for key, members in static_groups.items()),
            *(check_units(code, members) for code, members in unit_groups.items()),
        )
        verification_work = {
            "candidates": len(eligible),
            "static_runs": len(static_groups),
            "static_reused": len(eligible) - len(static_groups),
            "sandbox_runs": len(unit_groups),
            "sandbox_reused": sum(len(group) - 1 for group in unit_groups.values()),
        }
        _emit(self._on_event, {"event": "best_of_n_verification_work", **verification_work})
        valid, suspect = agreed_units(candidates) if tests else (set(), set())
        if valid:
            try:
                stub, stub_error = await asyncio.to_thread(self.checker.run_tests, STUB_MODULE, tests)
            except Exception:
                stub, stub_error = None, "unavailable"
            if (stub_error or not isinstance(stub, dict) or not valid.issubset(stub)
                    or not all(isinstance(name, str) and type(ok) is bool
                               for name, ok in stub.items())):
                # We could not check whether every model-written assertion also ran
                # against an empty module. Never count unverified assertions.
                suspect |= valid
                valid = set()
            else:
                vacuous = {name for name, ok in stub.items() if ok}
                valid -= vacuous
                suspect |= vacuous & {n for c in candidates for n in (c.unit_raw or {})}
        for c in candidates:
            if not c.ok:
                continue
            if tests and c.code:
                if c.unit_raw is None:
                    c.checks.append(CheckResult("unit tests", "skip", c.unit_error or "sandbox unavailable"))
                elif valid:
                    passed = sorted(n for n in valid if c.unit_raw.get(n, False))
                    c.unit = (len(passed), len(valid))
                    c.unit_failed = tuple(sorted(n for n in valid if not c.unit_raw.get(n, False)))
                    c.checks.append(CheckResult("unit tests", "pass" if len(passed) == len(valid) else "fail",
                                                f"{len(passed)}/{len(valid)}" + (
                                                    "; failed: " + "; ".join(_clean(n, 60) for n in c.unit_failed[:3])
                                                    if c.unit_failed else "")))
            _emit(self._on_event, {"event": "best_of_n_checked", "index": c.index, "passed": c.passed,
                                   "ran": c.ran})
        ordered = sorted(candidates, key=rank_key)
        await self._break_tie(ordered)
        ordered = sorted(candidates, key=rank_key)
        best = ordered[0]
        state = "selected"
        if best.ok and best.hard_failures and self._repair is not None and best.code:
            state = await self._try_repair(best, tests) or state
        if not best.ok:
            state = "unavailable"
        elif best.hard_failures:
            state = "none_passed"
        main = candidates[0]
        answer = best.answer if best.ok else main.answer
        outcome = Outcome(answer, best if best.ok else None, candidates, tests=len(valid),
                          suspect_tests=len(suspect), changed=answer != main.answer, tests_state=self.tests_state,
                          state="repaired" if best.repaired and not best.hard_failures else state,
                          verification_work=verification_work)
        outcome.footer = evidence(outcome, kind)
        candidate_pool.record_best_of_n(self.prompt, outcome)       # M5 offline replay; no-op unless the pool flag is set
        _emit(self._on_event, {"event": "best_of_n_selected", "index": best.index, "n": len(candidates),
                               "passed": best.passed, "ran": best.ran, "state": outcome.state})
        return outcome

    async def _break_tie(self, ordered: list[Candidate]) -> None:
        if self._judge is None or len(ordered) < 2:
            return
        head = rank_key(ordered[0])[:5]
        tied = [c for c in ordered if c.ok and rank_key(c)[:5] == head][:4]
        if len(tied) < 2:
            return
        _emit(self._on_event, {"event": "best_of_n_judging", "count": len(tied)})
        try:
            pick = await self._judge(self.prompt, [c.answer for c in tied])
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        if type(pick) is int and 0 <= pick < len(tied):
            for rank, c in enumerate([tied[pick], *[t for i, t in enumerate(tied) if i != pick]]):
                c.judge_rank = rank

    async def _try_repair(self, best: Candidate, tests: str | None) -> str | None:
        problems = [f"{c.name}: {c.detail}" if c.detail else c.name for c in best.checks
                    if c.status == "fail" and c.hard]
        if self._repair is None:
            return None
        _emit(self._on_event, {"event": "best_of_n_repair", "index": best.index})
        try:
            fixed = await self._repair(self.prompt, best.code, problems)
        except asyncio.CancelledError:
            raise
        except Exception:
            return None
        if not isinstance(fixed, str) or not fixed.strip() or fixed.strip() == best.code.strip():
            return None
        fence = {"luau": "luau", "python": "python", "map_plan": "json"}[self.plan.kind or "luau"]
        answer = best.answer.replace(best.code, fixed if fixed.endswith("\n") else fixed + "\n", 1)
        if answer == best.answer:
            answer = best.answer.rstrip() + f"\n\n```{fence}\n{fixed.rstrip()}\n```\n"
        trial = Candidate(best.index, best.model, best.temperature, answer=answer)
        trial.code = main_block(answer, self.plan.kind or "luau")
        try:
            trial.checks = await asyncio.to_thread(self.checker.static, trial.code, trial.answer)
        except Exception:
            return None
        if not isinstance(trial.checks, (list, tuple)) or not all(
                isinstance(check, CheckResult) for check in trial.checks):
            return None
        trial.checks = list(trial.checks)
        # Repair must not make any previously passing static check fail or turn a
        # previously executed check into "not run". Missing verification is not an
        # improvement, even if it makes the hard-failure counter smaller.
        new_checks = {check.name: check for check in trial.checks}
        for old in best.checks:
            if old.name == "unit tests":
                continue
            fresh = new_checks.get(old.name)
            if (fresh is None or (old.ran and not fresh.ran)
                    or (old.status == "pass" and fresh.status != "pass")):
                return None
        if best.unit is not None:
            if not tests or not getattr(self.checker, "can_run_tests", False):
                return None
            try:
                raw, error = await asyncio.to_thread(self.checker.run_tests, trial.code, tests)
            except Exception:
                return None
            if (not isinstance(raw, dict) or not all(
                    isinstance(name, str) and type(passed) is bool for name, passed in raw.items())):
                return None
            names = set(best.unit_failed) | {n for n, ok in (best.unit_raw or {}).items() if ok}
            if not names:
                return None
            previously_passing = {n for n in names if (best.unit_raw or {}).get(n, False)}
            if any(not raw.get(n, False) for n in previously_passing):
                return None
            passed = sorted(n for n in names if raw.get(n, False))
            trial.unit = (len(passed), len(names))
            trial.unit_raw = dict(raw)
            trial.unit_error = error
            trial.unit_failed = tuple(sorted(names - set(passed)))
            trial.checks.append(CheckResult("unit tests", "pass" if len(passed) == len(names) else "fail",
                                            f"{len(passed)}/{len(names)}"))
        if trial.hard_failures < best.hard_failures:
            best.answer, best.code, best.checks, best.unit = trial.answer, trial.code, list(trial.checks), trial.unit
            best.unit_raw, best.unit_error, best.unit_failed = trial.unit_raw, trial.unit_error, trial.unit_failed
            best.repaired = True
            return "repaired"
        return None


# ------------------------------------------------------------------------------------------------ evidence

_SCOPE = {
    "luau": "These checks are static: the code was not run.",
    "luau_tests": "The checks are static except the unit tests, which ran in the standalone Luau VM with mocks; "
                  "the code was not run in Roblox.",
    "python": "The Python code was compiled, not run.",
    "map_plan": "The plan was checked by STAR's offline dry run, not built in Studio.",
}


def evidence(outcome: Outcome, kind: str) -> str:
    """The paragraph shown under the answer. Empty for a single-candidate turn."""
    if outcome.state == "single" or len(outcome.candidates) < 2:
        return ""
    best = outcome.chosen
    written = [c for c in outcome.candidates if c.ok]
    head = f"\n\n{BEST_MARKER} {len(outcome.candidates)} by STAR:** "
    if best is None:
        return head + "STAR tried to write several versions and none finished; the first answer is shown unchecked.\n"
    names = [c.name for c in best.checks if c.ran]
    skipped = sorted({c.name for c in best.checks if c.status == "skip"})
    missing = len(outcome.candidates) - len(written)
    text = (f"STAR started {len(outcome.candidates)} versions; {missing} did not finish in time, so only the one "
            "shown was checked. " if len(written) == 1 else
            f"STAR wrote {len(written)} versions"
            + (f" ({missing} more did not finish)" if missing else "") + " and checked each one. ")
    if outcome.state == "repaired":
        text += f"None passed everything; STAR fixed the best one and it now passes {best.passed}/{best.ran} checks"
    elif best.hard_failures:
        failed = [c for c in best.checks if c.status == "fail" and c.hard]
        text += (f"None passed every check. The one shown passed the most ({best.passed}/{best.ran}); still failing: "
                 + "; ".join(f"{c.name}" + (f" ({c.detail})" if c.detail else "") for c in failed[:3])
                 + ". Treat it as unverified")
    else:
        text += f"The one shown passed {best.passed}/{best.ran} checks"
    if names:
        text += " (" + ", ".join(names) + ")"
    others = [c for c in written if c is not best]
    if others:
        text += ". Other versions: " + ", ".join(f"{c.passed}/{c.ran}" for c in others)
    text += "."
    if outcome.tests:
        text += f" The {outcome.tests} unit tests were written by STAR from your request, before the code."
    if outcome.suspect_tests:
        text += (f" {outcome.suspect_tests} generated test(s) failed for every version and were not counted "
                 "(probably a wrong test).")
    if skipped:
        text += " Not run: " + ", ".join(skipped) + "."
    tested = any(c.name == "unit tests" and c.ran for c in best.checks)
    return head + text + " " + _SCOPE.get(kind + ("_tests" if tested else ""), _SCOPE.get(kind, "")) + "\n"


# ------------------------------------------------------------------------------------------------ wiring helpers

REPAIR_SYSTEM = (
    "You fix code. Reply with only the corrected code in one fenced block and no explanation. Keep the behaviour "
    "the request asks for and the structure; change what the listed problems require. The problems come from "
    "STAR's compiler, linters and unit tests."
)
JUDGE_SYSTEM = (
    "You compare candidate answers to a coding request. All of them passed the same automatic checks. Pick the "
    "one that best does what the request asks (correct, complete, clear, idiomatic). Reply with only its number."
)


def _first_text(response) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ValueError("no completion")
    message = choices[0].message
    if getattr(message, "tool_calls", None):
        raise ValueError("tool call instead of an answer")
    return getattr(message, "content", None) or ""


def model_writer(client, model: str, *, max_tokens: int = 700, extra_body: dict | None = None):
    """write_tests(prompt) on `client` (temperature 0)."""
    async def write(prompt: str) -> str:
        kwargs: dict = dict(model=model, temperature=0, max_tokens=max_tokens,
                      messages=[{"role": "system", "content": TEST_SYSTEM},
                                {"role": "user", "content": "REQUEST:\n" + prompt[:4000]}])
        if extra_body:
            kwargs["extra_body"] = extra_body
        return _first_text(await client.chat.completions.create(**kwargs))
    return write


def model_judge(client, model: str, *, extra_body: dict | None = None):
    """judge(prompt, answers) -> index, one short call; the code is shown, prose is clipped."""
    async def judge(prompt: str, answers: list[str]) -> int:
        listing = "\n\n".join(f"CANDIDATE {i + 1}:\n{a[:3500]}" for i, a in enumerate(answers))
        kwargs: dict = dict(model=model, temperature=0, max_tokens=8,
                      messages=[{"role": "system", "content": JUDGE_SYSTEM},
                                {"role": "user", "content": f"REQUEST:\n{prompt[:2000]}\n\n{listing}\n\n"
                                                            f"Best candidate number (1-{len(answers)}):"}])
        if extra_body:
            kwargs["extra_body"] = extra_body
        text = _first_text(await client.chat.completions.create(**kwargs))
        found = re.search(r"\d+", text)
        return int(found.group(0)) - 1 if found else -1
    return judge


def model_repair(client, model: str, kind: str, *, max_tokens: int = 1600, extra_body: dict | None = None):
    fence = {"luau": "luau", "python": "python", "map_plan": "json"}[kind]

    async def repair(prompt: str, code: str, problems: list[str]) -> str:
        listing = "\n".join("- " + _clean(p, 200) for p in problems[:8])
        kwargs: dict = dict(model=model, temperature=0, max_tokens=max_tokens,
                      messages=[{"role": "system", "content": REPAIR_SYSTEM},
                                {"role": "user", "content": f"Request:\n{prompt[:1500]}\n\nCode:\n```{fence}\n"
                                                            f"{code.rstrip()}\n```\n\nProblems:\n{listing}"}])
        if extra_body:
            kwargs["extra_body"] = extra_body
        text = _first_text(await client.chat.completions.create(**kwargs))
        return main_block(text, kind)
    return repair


def draft_fields(settings, model: str, tools: bool) -> dict:
    """Request fields of a draft candidate: the server's background slot fields, thinking off."""
    from .providers import llama_request_fields
    fields = dict(llama_request_fields(settings, model=model, background=True, tools=tools) or {})
    kwargs = dict(fields.get("chat_template_kwargs") or {})
    kwargs["enable_thinking"] = False        # a candidate is a draft answer, not a thinking session
    fields["chat_template_kwargs"] = kwargs
    return fields


def resample_tool(client, settings, request: dict, *, model: str, max_tokens: int):
    """`async (temperature) -> answer text`: the turn's own request asked again at another temperature, for the
    check-fix ladder's opt-in resample (setting verify_resample, star/verify_ladder.py)."""
    draw = sampler(client, request, max_tokens=max_tokens,
                   extra_body_for=lambda name: draft_fields(settings, name, bool(request.get("tools"))))

    async def resample(temperature: float) -> str:
        return await draw(Target(model, 1), temperature)
    return resample


def sampler(client, request: dict, *, max_tokens: int, extra_body_for=None):
    """sample(target, temperature): the main answer's own request (same messages and tools, so the server can
    reuse the prompt it already read) at another temperature on the target's model."""
    messages, tools = request.get("messages") or [], request.get("tools") or None

    async def sample(target: Target, temperature: float) -> str:
        kwargs = dict(model=target.model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        body = extra_body_for(target.model) if extra_body_for else None
        if body:
            kwargs["extra_body"] = body
        return _first_text(await (target.client or client).chat.completions.create(**kwargs))
    return sample


def sandbox_from_env(environ=None):
    """The operator's Luau sandbox for generated unit tests (STAR_BON_SSH or STAR_EVAL_SSH), else None."""
    source = os.environ if environ is None else environ
    for name in SSH_ENV_VARS:
        target = source.get(name, "").strip()
        if target:
            from .eval_sandbox import ContainerSandbox
            try:
                return ContainerSandbox(target, wall_s=10, cpu_s=5)
            except ValueError:
                return None
    return None


def harness_prelude(root: Path | None = None) -> str:
    """The eval harness prelude (evals/roblox/prelude.luau) of a source checkout; '' when it is not there."""
    path = (root or Path(__file__).resolve().parent.parent) / "evals" / "roblox" / "prelude.luau"
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.is_file() else ""
    except OSError:
        return ""


def api_dump_from_env(environ=None):
    source = os.environ if environ is None else environ
    value = source.get(API_DUMP_ENV, "").strip()
    if not value:
        return None
    try:
        from .roblox_api_checker import load_api_dump
        path = Path(value)
        return load_api_dump(path) if path.is_file() and path.stat().st_size <= 20_000_000 else None
    except Exception:
        return None


def make_checker(kind: str, *, prompt: str, luau_check=None, runner=None, prelude: str | None = None,
                 environ=None):
    """The checker for `kind` with every tool that is available on this machine."""
    if kind == "python":
        return PythonChecker()
    if kind == "map_plan":
        return MapPlanChecker()
    analyzer = formatter = None
    try:
        from .luau_analyze import analyze, locate_analyzer
        if locate_analyzer():
            analyzer = analyze
    except Exception:
        analyzer = None
    try:
        from .stylua_format import installed_formatter
        formatter = installed_formatter()
    except ValueError:
        formatter = None
    return LuauChecker(luau_check=luau_check, analyzer=analyzer, formatter=formatter,
                       api_dump=api_dump_from_env(environ), runner=runner,
                       prelude=harness_prelude() if prelude is None else prelude, prompt=prompt)


# ------------------------------------------------------------------------------------------------ desktop turn

PROBE_TIMEOUT_S = 0.5
WAIT_FACTOR = 1.0
FINISH_RESERVE_S = 75.0        # left for STAR's own Luau check, a repair and saving after the candidates


async def probe_free_slots(settings, model: str, *, transport=None) -> int | None:
    """Slots of `model` on STAR Server that are not generating right now; None when it cannot tell (<0.5 s)."""
    from .providers import _busy_from_report, _instance, connection_for, server_slots
    total = server_slots(settings, model)
    if not total:
        return None
    try:
        import httpx
        endpoint, api_key = connection_for(settings)
        root = endpoint.rstrip("/")
        root = root[:-len("/v1")] if root.endswith("/v1") else root
        async with httpx.AsyncClient(trust_env=False, timeout=PROBE_TIMEOUT_S, transport=transport) as http:
            answer = await http.get(root + "/slots", params={"model": _instance(settings, model)[1]},
                                    headers={"Authorization": f"Bearer {api_key}"})
        busy = _busy_from_report(answer.json()) if answer.status_code == 200 else None
    except Exception:
        return None
    return None if busy is None else max(0, total - len(busy))


def turn_mode(settings, environ=None) -> tuple[bool, int | None, int]:
    """(enabled, forced N, maximum N) for a desktop turn: the setting, or STAR_BEST_OF_N for evals."""
    setting = getattr(settings, "best_of_n", "off")
    maximum = getattr(settings, "best_of_n_max", DEFAULT_MAX_N)
    maximum = maximum if type(maximum) is int and 2 <= maximum <= MAX_N else DEFAULT_MAX_N
    if setting == "auto":
        return True, None, maximum
    enabled, forced = mode_from_env(environ)
    return enabled, forced, max(maximum, forced or 0)


class DesktopTurn:
    """Best-of-N wired into one desktop chat turn (star/desktop_core.run_task).

    for_turn(...) decides N before the model call; `on_first_request` is handed to star.agent.execute and starts
    the extra candidates with the main request's own messages; `apply(result, ...)` picks the answer before
    STAR's Luau check and sources list; `footer(result)` adds the evidence after them.
    """

    def __init__(self, run: BestOfN, *, client, settings, max_tokens: int):
        self.run, self.client, self.settings, self.max_tokens = run, client, settings, max_tokens
        self.outcome: Outcome | None = None
        self.began = monotonic()
        self._tools = None

    def _extra_body(self, model: str) -> dict:
        return draft_fields(self.settings, model, bool(self._tools))

    def on_first_request(self, request: dict) -> None:
        if self.run.started:
            return
        self._tools = request.get("tools")
        self.began = monotonic()
        self.run._sample = sampler(self.client, request, max_tokens=self.max_tokens, extra_body_for=self._extra_body)
        self.run.start()

    async def apply(self, result, main_model: str, *, started: float | None, budget: float, tools_ran: bool):
        """(answer, messages, archive) with the chosen candidate; the main answer when anything goes wrong."""
        if not self.run.started:
            return result
        answer, messages, archive = result
        if tools_ran:
            await self.run.cancel()
            return result
        main_seconds = monotonic() - self.began
        left = (budget - (monotonic() - started)) if started is not None and budget else 600.0
        # The candidates started with the main answer and share its server: give them as long again (2x in all).
        # First live run: 0.75x cut off a star-fast candidate that wrote a longer answer at temperature 0.7.
        wait_s = max(0.0, min(max(60.0, WAIT_FACTOR * main_seconds), left - FINISH_RESERVE_S))
        try:
            self.outcome = await self.run.finish(answer, main_model, wait_s=wait_s)
        except asyncio.CancelledError:
            await self.run.cancel()
            raise
        except Exception:
            await self.run.cancel()
            return result
        archive = [*archive, {"best_of_n": self.outcome.record()}]
        if self.outcome.changed and messages and messages[-1].get("role") == "assistant":
            messages = [*messages[:-1], {**messages[-1], "content": self.outcome.answer}]
        return (self.outcome.answer if self.outcome.changed else answer), messages, archive

    def footer(self, result):
        if self.outcome is None or not self.outcome.footer:
            return result
        answer, messages, archive = result
        answer = answer.rstrip() + self.outcome.footer
        if messages and messages[-1].get("role") == "assistant":
            messages = [*messages[:-1], {**messages[-1], "content": answer}]
        return answer, messages, archive


async def for_turn(settings, route, prompt: str, *, client, knowledge=None, eligible: bool, quick_model: str = "",
                   on_event=None, environ=None, probe=None) -> DesktopTurn | None:
    """A DesktopTurn when this turn should get several candidates, else None (the turn runs as before)."""
    enabled, forced, maximum = turn_mode(settings, environ)
    if not enabled or not eligible:
        return None
    kind = code_kind(prompt)
    if kind is None:
        return None
    first = plan_samples(prompt, enabled=True, max_n=maximum, kind=kind, forced=forced)
    if first.n < 2:
        return None
    models = [route.model] + ([quick_model] if quick_model and quick_model != route.model else [])
    probe = probe or probe_free_slots
    frees = await asyncio.gather(*(probe(settings, m) for m in models), return_exceptions=True)
    targets = []
    for index, (model, free) in enumerate(zip(models, frees)):
        free = free if type(free) is int else None
        if index == 0:
            free = 0 if free is None else max(0, free - 1)      # the main answer takes one of these
        elif free is None:
            free = 1
        targets.append(Target(model, free))
    capacity = sum(t.free for t in targets)
    plan = plan_samples(prompt, enabled=True, max_n=maximum, capacity=capacity, kind=kind, forced=forced)
    if plan.n < 2:
        _emit(on_event, {"event": "best_of_n_skipped", "reason": "busy"})
        return None
    luau_check = (lambda code: knowledge.luau_check(code)) if knowledge is not None else None
    runner = sandbox_from_env(environ) if kind == "luau" else None
    checker = make_checker(kind, prompt=prompt, luau_check=luau_check, runner=runner, environ=environ)
    helper_model = quick_model or route.model
    run = BestOfN(plan, prompt=prompt, checker=checker, sample=None, targets=targets,
                  write_tests=model_writer(client, route.model) if getattr(checker, "can_run_tests", False) else None,
                  judge=model_judge(client, helper_model,
                                    extra_body={"chat_template_kwargs": {"enable_thinking": False}}),
                  repair=model_repair(client, route.model, kind, max_tokens=min(2000, route.response_tokens)),
                  on_event=on_event)
    return DesktopTurn(run, client=client, settings=settings, max_tokens=route.response_tokens)
