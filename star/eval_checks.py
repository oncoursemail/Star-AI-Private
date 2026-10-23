"""Deterministic scoring of one STAR answer against one golden task.

This module is pure: it never talks to a model, a server or the disk by itself. Everything that
needs the outside world is passed in as a callable, so the scoring rules can be unit-tested with
fakes and the same rules run unchanged against the real knowledge service and sandbox.

A task is scored by the checks its `auto` block asks for:

  * a fenced Luau block exists in the answer;
  * each fenced block (at most MAX_CHECKED_BLOCKS) compiles and type-checks (`luau_check`, the
    knowledge service's /luau/check; the code is never executed there);
  * optional unit tests run the answer in the standalone Luau VM through `sandbox`
    (see star/eval_sandbox.py: server side, user `star`, time and memory limits, nothing on the PC);
  * optional type-checker probe: the module plus an appended misuse line must be REJECTED;
  * required / forbidden patterns, searched in code with comments removed (and, when asked, strings
    blanked), so a comment such as "-- no goto here" cannot satisfy or break a check;
  * a citation of a retrieved documentation page, for documentation questions.

A check that could not run because the infrastructure was down raises `InfraError`; the runner then
records the task as `error`, never as a model failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from time import monotonic

MAX_CHECKED_BLOCKS = 3
MAX_CHECK_CHARS = 20_000      # the knowledge service refuses longer code
MAX_SCAN_CHARS = 60_000
MAX_DETAIL = 400
LUAU_FENCE = re.compile(r"```[ \t]*(?:lua|luau)\b[^\n]*\n(.*?)```", re.S | re.I)
ANY_FENCE = re.compile(r"```.*?```", re.S)
# What STAR itself appends after the model's text (star/doc_grounding.py). Neither is the model's work.
_FOOTER_MARKERS = ("\n\n**Luau check by STAR:**", "\n\n---\n**Sources retrieved by STAR**")
_SOURCE_LINE = re.compile(r"^\s*(\d{1,2})\.\s+(.*?)\s+·\s+(cited|retrieved, not cited)\s*$", re.M)
_SOURCE_URL = re.compile(r"\]\((https://[^)\s]+)\)")
_RETURN_LAST = re.compile(r"^return[ \t]+([A-Za-z_]\w*)[ \t]*$", re.M)   # top level only: no indent


class InfraError(RuntimeError):
    """A check could not run (service or sandbox unavailable). The task is `error`, not `fail`."""


@dataclass
class Check:
    id: str
    ok: bool
    detail: str = ""

    def record(self) -> dict:
        return {"id": self.id, "ok": self.ok, **({"detail": self.detail} if self.detail else {})}


@dataclass
class TaskScore:
    checks: list[Check] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    blocks: int = 0

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    @property
    def reasons(self) -> list[str]:
        return [f"{c.id}: {c.detail}" if c.detail else c.id for c in self.checks if not c.ok]


# --- reading the answer ---------------------------------------------------------------------------

def split_answer(answer: str) -> tuple[str, str]:
    """(the model's text, what STAR appended: Luau check note and sources list)."""
    cut = len(answer)
    for marker in _FOOTER_MARKERS:
        at = answer.find(marker)
        if at != -1:
            cut = min(cut, at)
    return answer[:cut], answer[cut:]


PLAIN_FENCE = re.compile(r"```[ \t]*\n(.*?)```", re.S)
_LOOKS_LIKE_LUAU = re.compile(r"\b(?:local|function|end|then|return)\b")


def extract_luau_blocks(body: str) -> list[str]:
    """Fenced Luau code. Blocks labelled lua/luau win; if there are none, unlabelled fences that read as Luau count.

    A model that forgets the language tag has still written the code; the task is scored on the code, not the tag.
    """
    labelled = [m.group(1) for m in LUAU_FENCE.finditer(body) if m.group(1).strip()]
    if labelled:
        return labelled
    return [m.group(1) for m in PLAIN_FENCE.finditer(body) if _LOOKS_LIKE_LUAU.search(m.group(1))]


_FENCE_LINE = re.compile(r"^[ \t]*```", re.M)


def looks_truncated(answer: str) -> bool:
    """True when the model's text stops inside a code block (an odd number of fence lines).

    The model server can cut a stream short (a restart, a dropped connection) without any error reaching
    the client, and a model can also run into its token limit. Either way the answer is incomplete.
    """
    body, _ = split_answer(answer or "")
    return len(_FENCE_LINE.findall(body)) % 2 == 1


def prose_of(body: str) -> str:
    return ANY_FENCE.sub(" ", body)


def cited_sources(footer: str) -> list[dict]:
    """Entries of STAR's sources list: number, label, link, and whether the answer cited it."""
    entries = []
    for number, text, state in _SOURCE_LINE.findall(footer):
        url = _SOURCE_URL.search(text)
        entries.append({"n": int(number), "label": text, "url": url.group(1) if url else "",
                        "cited": state == "cited"})
    return entries


_LONG_OPEN = re.compile(r"\[(=*)\[")


def strip_luau(code: str, *, strings: bool = False) -> str:
    """Remove comments (and blank string contents when `strings`) while keeping line breaks.

    A small lexer, not a parser: it knows `--`, `--[=[ ]=]`, '...', "...", `...` and [=[ ]=].
    """
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if c == "-" and code.startswith("--", i):
            m = _LONG_OPEN.match(code, i + 2)
            if m:
                close = "]" + m.group(1) + "]"
                j = code.find(close, m.end())
                j = n if j == -1 else j + len(close)
                out.append("\n" * code.count("\n", i, j))
                i = j
                continue
            j = code.find("\n", i)
            i = n if j == -1 else j
            continue
        if c in "\"'`":
            j = i + 1
            while j < n and code[j] != c and (code[j] != "\n" or c == "`"):
                j += 2 if code[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(c + c if strings else code[i:j])
            i = j
            continue
        if c == "[":
            m = _LONG_OPEN.match(code, i)
            if m:
                close = "]" + m.group(1) + "]"
                j = code.find(close, m.end())
                j = n if j == -1 else j + len(close)
                out.append("[[]]" if strings else code[i:j])
                i = j
                continue
        out.append(c)
        i += 1
    return "".join(out)


def final_return_to_local(code: str, name: str = "__M") -> str | None:
    """Turn the module's last top-level `return X` into `local <name> = X`, or None."""
    found = None
    for found in _RETURN_LAST.finditer(code):
        pass
    if found is None:
        return None
    return code[:found.start()] + f"local {name} = {found.group(1)}" + code[found.end():]


def long_bracket(text: str) -> tuple[str, str]:
    """Opening and closing long-string brackets that cannot occur inside `text`."""
    level = 0
    while ("]" + "=" * level + "]") in text:
        level += 1
    return "[" + "=" * level + "[", "]" + "=" * level + "]"


# --- patterns ---------------------------------------------------------------------------------------

def _scope_text(scope: str, blocks: list[str], body: str) -> str:
    if scope == "prose":
        return prose_of(body)[:MAX_SCAN_CHARS]
    joined = "\n".join(blocks)[:MAX_SCAN_CHARS]
    if scope == "raw":
        return joined
    if scope == "first_raw":
        return (blocks[0] if blocks else "")[:MAX_SCAN_CHARS]
    if scope == "code_nostr":
        return strip_luau(joined, strings=True)
    return strip_luau(joined)          # "code": the default


def _compile(item: dict, pattern: str) -> re.Pattern:
    flags = re.M | (re.I if "i" in item.get("flags", "") else 0) | (re.S if "s" in item.get("flags", "") else 0)
    return re.compile(pattern, flags)


def pattern_checks(auto: dict, blocks: list[str], body: str) -> list[Check]:
    """`require` items hold either one regex (`re`) or a list of alternatives (`any`); `forbid` items one regex."""
    checks: list[Check] = []
    for item in [*auto.get("require", []), *auto.get("require_any", [])]:
        text = _scope_text(item.get("scope", "code"), blocks, body)
        patterns = item["any"] if "any" in item else [item["re"]]
        ok = any(_compile(item, p).search(text) for p in patterns)
        checks.append(Check("require:" + item["id"], ok, "" if ok else item.get("why", "pattern not found")))
    for item in auto.get("forbid", []):
        text = _scope_text(item.get("scope", "code"), blocks, body)
        patterns = item["any"] if "any" in item else [item["re"]]
        hit = next((m for m in (_compile(item, p).search(text) for p in patterns) if m), None)
        checks.append(Check("forbid:" + item["id"], hit is None,
                            "" if hit is None else (item.get("why", "forbidden pattern") + f" (found: {hit.group(0)[:60]!r})")))
    return checks


# --- unit tests in the Luau VM ----------------------------------------------------------------------

_PROLOGUE_END = "-- ===== test body ====="


def build_test_script(prelude: str, answer_code: str, test_body: str) -> str:
    """One Luau file: the answer as a string, the harness prelude, then the task's test body.

    The answer is only ever loaded with `loadstring` into a whitelisted environment (see prelude);
    nothing in it runs before the harness has set that environment up.
    """
    opener, closer = long_bracket(answer_code)
    return (f"local __SRC = {opener}\n{answer_code}\n{closer}\n{prelude}\n{_PROLOGUE_END}\n"
            f"local __ok, __err = xpcall(function()\n{test_body}\nend, function(e) return tostring(e) end)\n"
            "if not __ok then print('@@ERR\\t' .. string.sub(tostring(__err), 1, 300)) end\n"
            "print('@@DONE')\n")


@dataclass
class UnitOutcome:
    results: list[tuple[str, bool]] = field(default_factory=list)
    load_error: str = ""
    error: str = ""
    done: bool = False


def parse_test_output(stdout: str) -> UnitOutcome:
    out = UnitOutcome()
    for line in stdout.splitlines():
        if not line.startswith("@@"):
            continue
        parts = line.split("\t", 2)
        tag = parts[0]
        if tag == "@@T" and len(parts) == 3:
            out.results.append((parts[2][:120], parts[1] == "pass"))
        elif tag == "@@LOADERR":
            out.load_error = (parts[1] if len(parts) > 1 else "")[:300]
        elif tag == "@@ERR":
            out.error = (parts[1] if len(parts) > 1 else "")[:300]
        elif tag == "@@DONE":
            out.done = True
    return out


def unit_checks(outcome: UnitOutcome, sandbox_result, expected: int | None) -> list[Check]:
    if getattr(sandbox_result, "timed_out", False):
        return [Check("unit_tests", False, "timed out or exceeded the memory limit in the Luau VM")]
    if outcome.load_error:
        return [Check("unit_tests", False, "the answer did not load: " + outcome.load_error)]
    passed = [name for name, ok in outcome.results if ok]
    failed = [name for name, ok in outcome.results if not ok]
    problems = []
    if outcome.error:
        problems.append("test aborted: " + outcome.error)
    if not outcome.done:
        problems.append("harness did not finish")
    if expected is not None and len(outcome.results) != expected:
        problems.append(f"{len(outcome.results)} of {expected} assertions ran")
    if failed:
        problems.append("failed: " + "; ".join(failed[:6]))
    if not outcome.results and not problems:
        problems.append("no assertions ran")
    ok = not problems
    return [Check("unit_tests", ok, "" if ok else f"{len(passed)}/{max(len(outcome.results), expected or 0)} passed; "
                  + " | ".join(problems)[:MAX_DETAIL])]


def pick_block(blocks: list[str], how: str = "longest") -> str:
    if not blocks:
        return ""
    if how == "first":
        return blocks[0]
    if how == "last":
        return blocks[-1]
    if how == "concat":
        return "\n".join(blocks)
    return max(blocks, key=len)


# --- the whole task -------------------------------------------------------------------------------

def _first_errors(errors: list, limit: int = 2) -> str:
    return "; ".join(f"line {e.get('line')}: {str(e.get('message'))[:90]}" for e in errors[:limit])


_UNKNOWN_GLOBAL = re.compile(r"Unknown global '([A-Za-z_]\w*)'")
_IDENT = re.compile(r"[A-Za-z_]\w*")
_STRICT_HEADER = re.compile(r"\A(\s*)--!strict")


def lenient_source(code: str) -> str:
    """The same code with a leading `--!strict` turned into `--!nonstrict`.

    The knowledge service types Roblox classes as unknown, and strict mode then rejects ordinary
    operations on them ("string .. unknown"). Those errors say nothing about the answer, so Roblox
    tasks are checked in non-strict mode: syntax errors, unknown locals and real type mismatches
    still fail. Pure-Luau tasks use compile_mode "exact" and are checked as written.
    """
    return _STRICT_HEADER.sub(r"\1--!nonstrict", code, count=1)


def effective_errors(result: dict, prompt: str) -> list:
    """Diagnostics that count against the answer.

    A global the task's own prompt names (`BuyItem`, `giveItem`, `door` in a pasted snippet) is context
    the answer is expected to use without defining, so its "Unknown global" error is not a defect.
    """
    named = set(_IDENT.findall(prompt or ""))
    kept = []
    for error in result.get("errors") or []:
        found = _UNKNOWN_GLOBAL.search(str(error.get("message")))
        if found and found.group(1) in named:
            continue
        kept.append(error)
    return kept


def citation_check(auto: dict, footer: str) -> Check:
    spec = auto.get("citation") or {}
    entries = cited_sources(footer)
    cited = [e for e in entries if e["cited"]]
    if not entries:
        return Check("citation", False, "no documentation was retrieved or listed under the answer")
    if not cited:
        return Check("citation", False, "documentation was retrieved but the answer cites none of it")
    fragments = spec.get("url_contains_any") or []
    if fragments and not any(any(f.lower() in e["url"].lower() for f in fragments) for e in cited):
        return Check("citation", False, "cited pages: " + ", ".join(e["url"].rsplit("/", 1)[-1] for e in cited)[:200]
                     + "; none matches " + ", ".join(fragments))
    return Check("citation", True)


def score_answer(task: dict, answer: str, *, luau_check, sandbox=None, prelude: str = "",
                 test_body: str = "", clock=monotonic) -> TaskScore:
    """Score one answer. `luau_check(code, strict=bool)` returns the knowledge client's dict.

    Raises InfraError when a check that the task needs cannot run.
    """
    auto = task.get("auto") or {}
    score = TaskScore()
    body, footer = split_answer(answer or "")
    blocks = extract_luau_blocks(body)
    score.blocks = len(blocks)
    needs_code = auto.get("code", True)
    if needs_code:
        score.checks.append(Check("luau_block", len(blocks) >= auto.get("min_blocks", 1),
                                  f"{len(blocks)} fenced Luau block(s) in the answer" if len(blocks) < auto.get("min_blocks", 1) else ""))
    if not (answer or "").strip():
        score.checks.append(Check("answer", False, "empty answer"))
        return score

    started = clock()
    if needs_code and blocks and auto.get("compile", True):
        for index, code in enumerate(blocks[:MAX_CHECKED_BLOCKS], 1):
            if len(code) > MAX_CHECK_CHARS:
                score.checks.append(Check(f"luau_check[{index}]", False, f"block is longer than {MAX_CHECK_CHARS} characters"))
                continue
            exact = auto.get("compile_mode") == "exact"
            try:
                result = luau_check(code if exact else lenient_source(code), strict=bool(auto.get("strict")))
            except (OSError, ValueError) as exc:
                raise InfraError("Luau check unavailable: " + type(exc).__name__) from None
            errors = effective_errors(result, task.get("prompt", ""))
            if index > 1:
                # Later blocks are usually usage examples with placeholders (`require(path.to.Module)`): an unknown
                # global there is the example's placeholder, not a defect. The first block is checked in full.
                errors = [e for e in errors if not _UNKNOWN_GLOBAL.search(str(e.get("message")))]
            score.checks.append(Check(f"luau_check[{index}]", not errors, _first_errors(errors)))
    score.timings["luau_check_s"] = round(clock() - started, 2)

    probe = auto.get("typecheck_probe")
    if probe and blocks:
        module = pick_block(blocks, probe.get("block", "longest"))
        converted = final_return_to_local(module)
        if converted is None:
            score.checks.append(Check("typecheck_probe", False, "no final `return <name>` to attach the misuse call to"))
        else:
            try:
                result = luau_check(converted + "\n" + probe["suffix"], strict=True)
            except (OSError, ValueError) as exc:
                raise InfraError("Luau check unavailable: " + type(exc).__name__) from None
            rejected = (not result.get("ok")) and any("Type" in str(e.get("kind")) for e in result.get("errors") or [])
            score.checks.append(Check("typecheck_probe", rejected,
                                      "" if rejected else "the type checker accepted a call that must be rejected"))

    unit = auto.get("unit_test")
    if unit and blocks:
        if sandbox is None or not test_body:
            raise InfraError("no sandbox configured for a task with unit tests")
        module = pick_block(blocks, unit.get("block", "longest"))
        started = clock()
        script = build_test_script(prelude, module, test_body)
        run = sandbox.run(script)
        score.timings["unit_s"] = round(clock() - started, 2)
        if getattr(run, "error", ""):
            raise InfraError("sandbox: " + run.error[:120])
        score.checks.extend(unit_checks(parse_test_output(run.stdout), run, unit.get("checks")))
    elif unit and not blocks:
        score.checks.append(Check("unit_tests", False, "no code to test"))

    score.checks.extend(pattern_checks(auto, blocks, body))
    if auto.get("answer"):            # knowledge school: exact / numeric / choice / order / match / short / rubric keys
        from .knowledge_checks import answer_checks
        score.checks.extend(answer_checks(auto["answer"], answer))
    if auto.get("citation", {}).get("required"):
        score.checks.append(citation_check(auto, footer))
    return score
