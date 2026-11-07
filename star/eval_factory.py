"""Bug-injection task factory (SWE-smith style) for the sealed blind eval set.

Input: *seeds*, verified-correct modules with a specification and a unit test (Luau, Python or JavaScript). For each
seed the factory makes one "write it from the spec" task and several "fix the bug" tasks: it mutates the reference
with realistic bug operators (flipped comparison, wrong operator, off-by-one constant, swapped and/or, min/max,
floor/ceil, a deleted statement), runs the unit test against every mutant in a sandbox and keeps only fail-to-pass
mutants (the reference passes every assertion, the mutant loads, finishes in time and fails at least one). Every
kept task therefore has a passing reference and a failing trivial answer (the buggy code returned unchanged).

Execution never happens on this PC: Luau runs in the standalone Luau VM in a STAR container (user `star`, prlimit,
timeout; star/eval_sandbox.py), Python and JavaScript in the `star-judge` container (no network device, user
`sandbox`). This module only builds scripts and parses their output; the runners are passed in.

Seed file format (one file holds many seeds):

    === id: cooldown | domain: gameplay | difficulty: 1
    --- spec
    a ModuleScript `Cooldown` for ...            (Luau: completes "Write a Luau ModuleScript that is ...")
    --- module
    <reference code>
    --- test
    <test body: Luau uses the eval prelude's load_answer/check; Python/JS use check(name, cond)>

The seeds and the built tasks are sealed (star/sealed_eval.py): they live outside the repository and only the gate
runner reads them.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import random
import re
import subprocess

from .eval_checks import build_test_script, judge_outcome as _judge_lines, judge_source, parse_test_output
from .eval_sandbox import JudgeSandbox as JudgeRunner

LANGUAGES = ("luau", "python", "javascript")
FENCE = {"luau": "lua", "python": "python", "javascript": "javascript"}
_HEADER = re.compile(r"^=== (.+)$", re.M)
_SECTION = re.compile(r"^--- (spec|module|test)[ \t]*$", re.M)


@dataclass
class Seed:
    id: str
    language: str
    domain: str
    difficulty: int
    spec: str
    module: str
    test: str
    meta: dict = field(default_factory=dict)

    @property
    def digest(self) -> str:
        return hashlib.sha256((self.language + "\0" + self.module + "\0" + self.test).encode("utf-8")).hexdigest()


def parse_seeds(text: str, language: str) -> list[Seed]:
    if language not in LANGUAGES:
        raise ValueError(f"unknown language {language!r}")
    text = text.replace("\r\n", "\n")
    heads = list(_HEADER.finditer(text))
    seeds: list[Seed] = []
    for i, head in enumerate(heads):
        body = text[head.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        meta = {}
        for part in head.group(1).split("|"):
            key, _, value = part.partition(":")
            meta[key.strip()] = value.strip()
        parts = {}
        marks = list(_SECTION.finditer(body))
        for j, mark in enumerate(marks):
            end = marks[j + 1].start() if j + 1 < len(marks) else len(body)
            parts[mark.group(1)] = body[mark.end():end].strip("\n")
        missing = [k for k in ("spec", "module", "test") if not parts.get(k, "").strip()]
        if missing or not meta.get("id"):
            raise ValueError(f"seed {meta.get('id', i)}: missing {missing or ['id']}")
        seeds.append(Seed(meta.pop("id"), language, meta.pop("domain", "general"), int(meta.pop("difficulty", "2")),
                          " ".join(parts["spec"].split()), parts["module"].rstrip() + "\n", parts["test"].rstrip() + "\n",
                          meta))
    ids = [s.id for s in seeds]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate seed ids")
    return seeds


# --- masking: which characters are code (not inside a string or a comment) ----------------------------------

def code_mask(code: str, language: str) -> list[bool]:
    mask = [True] * len(code)
    i, n = 0, len(code)
    line_comment = "--" if language == "luau" else ("#" if language == "python" else "//")
    while i < n:
        if code.startswith(line_comment, i):
            j = code.find("\n", i)
            j = n if j == -1 else j
            if language == "luau" and code.startswith("--[[", i):
                k = code.find("]]", i)
                j = n if k == -1 else k + 2
            for k in range(i, j):
                mask[k] = False
            i = j
            continue
        if language == "javascript" and code.startswith("/*", i):
            k = code.find("*/", i)
            j = n if k == -1 else k + 2
            for k in range(i, j):
                mask[k] = False
            i = j
            continue
        ch = code[i]
        if language == "python" and code.startswith(('"""', "'''"), i):
            q = code[i:i + 3]
            k = code.find(q, i + 3)
            j = n if k == -1 else k + 3
            for k in range(i, j):
                mask[k] = False
            i = j
            continue
        if ch in "\"'`":
            j = i + 1
            while j < n and code[j] != ch and code[j] != "\n":
                j += 2 if code[j] == "\\" else 1
            j = min(n, j + 1)
            for k in range(i, j):
                mask[k] = False
            i = j
            continue
        i += 1
    return mask


# --- mutation operators ------------------------------------------------------------------------------------

@dataclass
class Mutant:
    op: str
    line: int
    before: str
    after: str
    code: str


_SWAPS_COMMON = [("rel", "<=", "<"), ("rel", ">=", ">"), ("rel", "<", "<="), ("rel", ">", ">="),
                 ("arith", "+", "-"), ("arith", "-", "+"), ("arith", "*", "/")]
_WORD_SWAPS = {
    "luau": [("logic", "and", "or"), ("logic", "or", "and"), ("bool", "true", "false"), ("bool", "false", "true"),
             ("call", "math.min", "math.max"), ("call", "math.max", "math.min"), ("call", "math.floor", "math.ceil"),
             ("rel", "==", "~="), ("rel", "~=", "=="), ("arith", "//", "/"), ("logic", "not ", "")],
    "python": [("logic", "and", "or"), ("logic", "or", "and"), ("bool", "True", "False"), ("bool", "False", "True"),
               ("call", "min", "max"), ("call", "max", "min"), ("rel", "==", "!="), ("rel", "!=", "=="),
               ("arith", "//", "/"), ("logic", "not ", "")],
    "javascript": [("logic", "&&", "||"), ("logic", "||", "&&"), ("bool", "true", "false"), ("bool", "false", "true"),
                   ("call", "Math.min", "Math.max"), ("call", "Math.max", "Math.min"),
                   ("call", "Math.floor", "Math.ceil"), ("rel", "===", "!=="), ("rel", "!==", "==="),
                   ("logic", "!", "")],
}
_IDENT_CHAR = re.compile(r"[A-Za-z0-9_]")
_OPERAND_END = re.compile(r"[A-Za-z0-9_)\]}]")


def _line_of(code: str, at: int) -> int:
    return code.count("\n", 0, at) + 1


def _symbol_ok(code: str, at: int, sym: str, language: str) -> bool:
    """A binary/relational operator occurrence that is really that operator (not part of a longer one)."""
    before = code[at - 1] if at > 0 else ""
    after = code[at + len(sym)] if at + len(sym) < len(code) else ""
    longer = "<>=~!+-*/&|."
    if sym in ("<", ">"):
        if before in longer or after in "=<>" or (sym == ">" and before == "-"):
            return False
        if language == "javascript" and before == "=":
            return False
    if sym in ("<=", ">=") and (before in "<>=" or after == "="):
        return False
    if sym in ("+", "-", "*", "/"):
        if after in "=+-*/>" or before in "+-*/":
            return False
        if sym == "-" and after == "-":
            return False
        # binary only: the previous non-space character must end an operand (no unary minus in Luau)
        k = at - 1
        while k >= 0 and code[k] in " \t":
            k -= 1
        if k < 0 or not _OPERAND_END.match(code[k]):
            return False
        word = re.search(r"([A-Za-z_]+)\s*$", code[:k + 1])
        if word and word.group(1) in ("return", "then", "else", "do", "and", "or", "not", "in", "if", "elseif"):
            return False
    if sym in ("==", "~=", "!=", "===", "!==") and (before in "=<>~!" or after == "="):
        return False
    return True


def mutants(code: str, language: str) -> list[Mutant]:
    """Every single-site mutation of `code` (one operator at one place), in source order."""
    mask = code_mask(code, language)
    out: list[Mutant] = []
    seen: set[str] = set()

    def add(op: str, at: int, before: str, after: str) -> None:
        new = code[:at] + after + code[at + len(before):]
        if new != code and new not in seen:
            seen.add(new)
            out.append(Mutant(op, _line_of(code, at), before, after, new))

    swaps = list(_WORD_SWAPS[language]) + list(_SWAPS_COMMON)
    for op, before, after in swaps:
        start = 0
        while True:
            at = code.find(before, start)
            if at == -1:
                break
            start = at + 1
            if not all(mask[at:at + len(before)]):
                continue
            if before[0].isalpha():
                prev = code[at - 1] if at else ""
                nxt = code[at + len(before)] if at + len(before) < len(code) else ""
                if (prev and (_IDENT_CHAR.match(prev) or prev == ".")) or (nxt and _IDENT_CHAR.match(nxt) and not before.endswith(" ")):
                    continue
                if before in ("min", "max") and nxt != "(":
                    continue
            elif before == "!":
                nxt = code[at + 1] if at + 1 < len(code) else ""
                if nxt == "=" or (at and code[at - 1] in "=!"):
                    continue
            elif not _symbol_ok(code, at, before, language):
                continue
            add(op, at, before, after)
    for m in re.finditer(r"(?<![\w.])(\d+)(?![\w.])", code):
        at = m.start()
        if not all(mask[at:m.end()]):
            continue
        value = int(m.group(1))
        add("const", at, m.group(1), str(value + 1))
        if value > 0:
            add("const", at, m.group(1), str(value - 1))
    out.extend(_deletions(code, language, mask, seen))
    return out


_KEYWORD_LINE = {
    "luau": re.compile(r"^\s*(local|function|end|return|if|elseif|else|for|while|repeat|until|do|export|type)\b"),
    "python": re.compile(r"^\s*(def|class|return|if|elif|else|for|while|try|except|finally|with|import|from|raise|pass|@)\b"),
    "javascript": re.compile(r"^\s*(function|return|if|else|for|while|const|let|var|class|try|catch|}|\)|module)\b"),
}
_STATEMENT = re.compile(r"^\s*[A-Za-z_][\w.\[\]\"']*\s*(?:[-+*/]?=)\s*\S.*$|^\s*(?:table\.insert|table\.remove|[\w.]+\.(?:append|push|pop|remove))\(.*\)\s*;?\s*$")


def _deletions(code: str, language: str, mask: list[bool], seen: set[str]) -> list[Mutant]:
    lines = code.split("\n")
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    out = []
    for i, line in enumerate(lines):
        if not line.strip() or _KEYWORD_LINE[language].match(line) or not _STATEMENT.match(line):
            continue
        if "==" in line and language != "python":
            continue
        if not mask[offsets[i] + len(line) - len(line.lstrip())]:
            continue
        if language == "python":
            prev = next((lines[k] for k in range(i - 1, -1, -1) if lines[k].strip()), "")
            nxt = next((lines[k] for k in range(i + 1, len(lines)) if lines[k].strip()), "")
            indent = len(line) - len(line.lstrip())
            if prev.rstrip().endswith(":") and (len(nxt) - len(nxt.lstrip())) < indent:
                continue          # the only statement of its block: deleting it is a syntax error, not a bug
        new = "\n".join(lines[:i] + lines[i + 1:])
        if new not in seen:
            seen.add(new)
            out.append(Mutant("delete", i + 1, line.strip(), "", new))
    return out


# --- harness scripts ---------------------------------------------------------------------------------------

@dataclass
class Outcome:
    passed: list[str]
    failed: list[str]
    loaded: bool
    finished: bool
    timed_out: bool = False

    @property
    def all_pass(self) -> bool:
        return self.loaded and self.finished and not self.failed and bool(self.passed) and not self.timed_out


def judge_outcome(stdout: str, timed_out: bool = False) -> Outcome:
    passed, failed, finished = _judge_lines(stdout)
    return Outcome(passed, failed, bool(passed or failed), finished, timed_out)


def luau_outcome(stdout: str, timed_out: bool = False) -> Outcome:
    parsed = parse_test_output(stdout)
    return Outcome([n for n, ok in parsed.results if ok], [n for n, ok in parsed.results if not ok],
                   not parsed.load_error, parsed.done and not parsed.error, timed_out)


# --- batch runners (remote; nothing runs on the PC) -----------------------------------------------------------

LUAU_BIN = "/opt/star/bench/tools/luau/build/release/luau"


def luau_batch_script(sources: list[str], *, mem_mb: int = 256, cpu_s: int = 8, wall_s: int = 10) -> str:
    lines = ["D=$(mktemp -d /tmp/starfac.XXXXXXXX) || exit 97", 'cd "$D" || exit 97', "trap 'cd /; rm -rf \"$D\"' EXIT"]
    for i, source in enumerate(sources):
        payload = base64.b64encode(source.encode("utf-8")).decode("ascii")
        lines += [f"base64 -d > t{i}.luau <<'STAR_EOF'", payload, "STAR_EOF",
                  f"echo '@@BEGIN {i}'",
                  f"prlimit --as={mem_mb * 1024 * 1024} --cpu={cpu_s} --fsize=1048576 --nofile=32 --core=0 -- "
                  f"timeout -s KILL {wall_s} {LUAU_BIN} t{i}.luau 2>&1 | head -c 65536",
                  f'echo "@@END {i} ${{PIPESTATUS[0]}}"']
    return "\n".join(lines) + "\n"


def split_batch(stdout: str, count: int) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = [("", -1)] * count
    for m in re.finditer(r"^@@BEGIN (\d+)\n(.*?)^@@END \1 (-?\d+)$", stdout, re.M | re.S):
        out[int(m.group(1))] = (m.group(2), int(m.group(3)))
    return out


class LuauRunner:
    """Runs many Luau scripts in one SSH session in a STAR container (user star, limits)."""

    def __init__(self, ssh_target: str, container: str = "starai", runner=subprocess.run, chunk: int = 40):
        self.argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", ssh_target,
                     f"lxc exec {container} -- runuser -u star -- bash -s"]
        self.runner, self.chunk = runner, chunk

    def run(self, sources: list[str]) -> list[tuple[str, int]]:
        results: list[tuple[str, int]] = []
        for start in range(0, len(sources), self.chunk):
            part = sources[start:start + self.chunk]
            done = self.runner(self.argv, input=luau_batch_script(part).encode("utf-8"), capture_output=True,
                               timeout=60 + 15 * len(part))
            results.extend(split_batch(done.stdout.decode("utf-8", "replace"), len(part)))
        return results


# --- building tasks ----------------------------------------------------------------------------------------

def run_sources(seed_language: str, sources: list[str], *, luau: LuauRunner | None, judge: JudgeRunner | None) -> list[Outcome]:
    if seed_language == "luau":
        assert luau is not None
        return [luau_outcome(out, rc in (124, 137, 9)) for out, rc in luau.run(sources)]
    assert judge is not None
    return [judge_outcome(r.stdout, r.timed_out) for r in judge.run_many(seed_language, sources)]


def test_source(seed: Seed, code: str, prelude: str) -> str:
    if seed.language == "luau":
        return build_test_script(prelude, code, seed.test)
    return judge_source(seed.language, code, seed.test)


TRIVIAL = {"luau": "--!strict\nreturn {}\n", "python": "pass\n", "javascript": "module.exports = {};\n"}


@dataclass
class SeedReport:
    seed: str
    reference_ok: bool
    trivial_fails: bool
    assertions: int
    mutants: int
    f2p: int
    kept: list[Mutant] = field(default_factory=list)
    kept_failing: list[list[str]] = field(default_factory=list)
    problem: str = ""


def screen_seed(seed: Seed, prelude: str, *, luau=None, judge=None, max_bugs: int = 5,
                rng: random.Random | None = None) -> SeedReport:
    """Verify the reference (all pass) and the trivial answer (fails); keep up to `max_bugs` F2P mutants with
    distinct failing-test signatures, spreading operator classes."""
    rng = rng or random.Random(seed.id)
    cands = mutants(seed.module, seed.language)
    sources = [test_source(seed, seed.module, prelude), test_source(seed, TRIVIAL[seed.language], prelude)]
    sources += [test_source(seed, m.code, prelude) for m in cands]
    outs = run_sources(seed.language, sources, luau=luau, judge=judge)
    ref, trivial = outs[0], outs[1]
    report = SeedReport(seed.id, ref.all_pass, not trivial.all_pass, len(ref.passed) + len(ref.failed), len(cands), 0)
    if not ref.all_pass:
        report.problem = "reference fails: " + "; ".join(ref.failed[:4]) + ("" if ref.finished else " (did not finish)")
        return report
    groups: dict[str, list[tuple[Mutant, list[str]]]] = {}
    signatures: set[tuple[str, ...]] = set()
    for m, out in zip(cands, outs[2:]):
        if not out.loaded or out.timed_out or not out.failed:
            continue
        if len(out.passed) + len(out.failed) == 0:
            continue
        report.f2p += 1
        sig = tuple(sorted(out.failed))
        if sig in signatures:
            continue
        signatures.add(sig)
        groups.setdefault(m.op, []).append((m, list(out.failed)))
    for items in groups.values():
        rng.shuffle(items)
    order = sorted(groups)
    rng.shuffle(order)
    while len(report.kept) < max_bugs and any(groups[o] for o in order):
        for op in order:
            if groups[op] and len(report.kept) < max_bugs:
                m, failing = groups[op].pop()
                report.kept.append(m)
                report.kept_failing.append(failing)
    return report


SPEC_PROMPTS = {
    "luau": "Write a Luau ModuleScript that is {spec} Reply with the complete module in one ```lua code block; the module must return its table.",
    "python": "Write Python code: {spec} Reply with the complete code in one ```python code block (no example usage, no input()).",
    "javascript": "Write JavaScript (Node.js) code: {spec} Reply with the complete code in one ```javascript code block and export the API with module.exports.",
}
LANG_NAME = {"luau": "Luau ModuleScript", "python": "Python code", "javascript": "JavaScript code"}
BUG_PROMPTS = [
    "This {lang} should be {spec}\n\nIt has a bug: {symptom}. Find the bug and reply with the complete fixed code in one ```{fence} code block.\n\n```{fence}\n{code}```",
    "My {lang} has a bug. It is meant to be {spec}\n\n{symptom_cap}. Please fix it and send the whole corrected code in one ```{fence} block.\n\n```{fence}\n{code}```",
    "Fix the bug in this {lang}. Intended behaviour: {spec}\n\nWhat goes wrong: {symptom}.\n\n```{fence}\n{code}```\n\nReply with the full fixed code in one ```{fence} block.",
]


def _symptom(failing: list[str], hint: bool) -> str:
    if hint:
        return f'a test of "{failing[0]}" fails'
    return "one of my tests of the behaviour above fails, and I do not know which part is wrong"


def make_tasks(seed: Seed, report: SeedReport, *, set_id: str, number, rng: random.Random) -> list[dict]:
    """The spec task and one bugfix task per kept mutant. `number()` hands out the next opaque task number."""
    tasks = []
    fence = FENCE[seed.language]
    common = {"run_mode": "automated", "split": "sealed", "set": set_id, "seed_sha256": seed.digest[:16],
              "language": seed.language, "domain": seed.domain,
              "required_evidence": ["answer code", "unit test log"],
              "pass_conditions": ["the answer's code passes every assertion of the sealed unit test"],
              "fixture_status": "implemented", "helps": []}
    spec_task = {"id": number(), "category": f"{seed.language}-spec", "family": f"{seed.language}-spec",
                 "difficulty": seed.difficulty, "goal": f"write {seed.domain} code from a specification",
                 "prompt": SPEC_PROMPTS[seed.language].format(spec=seed.spec), "kind": "spec",
                 "_reference": seed.module, "_bad": TRIVIAL[seed.language], **common}
    tasks.append(spec_task)
    for m, failing in zip(report.kept, report.kept_failing):
        hint = rng.random() < 0.6
        template = rng.choice(BUG_PROMPTS)
        symptom = _symptom(failing, hint)
        prompt = template.format(lang=LANG_NAME[seed.language], spec=seed.spec[0].lower() + seed.spec[1:] if seed.spec[:2] != "a " else seed.spec,
                                 symptom=symptom, symptom_cap=symptom[0].upper() + symptom[1:], fence=fence, code=m.code)
        difficulty = min(3, seed.difficulty + (0 if hint else 1))
        tasks.append({"id": number(), "category": f"{seed.language}-bugfix", "family": f"{seed.language}-bugfix",
                      "difficulty": difficulty, "goal": f"fix an injected {m.op} bug in {seed.domain} code",
                      "prompt": prompt, "kind": "bugfix", "bug_op": m.op, "symptom_hint": hint,
                      "_reference": seed.module, "_bad": m.code, **common})
    return tasks


# --- leakage: a sealed task must not overlap anything tuning can see -----------------------------------------
# (the same token shingles as server/training/startrain/similarity.py, kept here so the app package needs no server code)

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?|[^\sA-Za-z_0-9]")
_COMMENT = re.compile(r"--\[(=*)\[.*?\]\1\]|--[^\n]*|#[^\n]*|//[^\n]*", re.S)
_MD_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def _tokens(text: str, code: bool) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(_COMMENT.sub(" ", text) if code else text)]


def _shingles(toks: list[str], n: int, min_words: int = 0) -> set[int]:
    """Hashed token n-grams; with min_words, only n-grams holding at least that many word tokens (so a shared type
    signature such as `: { [string]: number }` is not mistaken for a copied sentence)."""
    toks = toks + [""] * max(0, n - len(toks))
    return {int.from_bytes(hashlib.blake2b("\x1f".join(toks[i:i + n]).encode("utf-8"), digest_size=6).digest(), "big")
            for i in range(len(toks) - n + 1)
            if sum(1 for x in toks[i:i + n] if x[:1].isalnum()) >= min_words} if toks else set()


@dataclass
class LeakIndex:
    prose8: list[tuple[str, set[int]]] = field(default_factory=list)
    code5: list[tuple[str, set[int]]] = field(default_factory=list)

    def add_text(self, source: str, text: str, *, code: bool | None = None) -> None:
        """Add a document; markdown is split into fenced code and prose. code=True/False forces one kind."""
        if code is None:
            blocks = _MD_FENCE.findall(text)
            prose = _MD_FENCE.sub(" ", text)
            for block in blocks:
                self.code5.append((source, _shingles(_tokens(block, True), 5)))
            if prose.strip():
                self.prose8.append((source, _shingles(_tokens(prose, False), 8, 5)))
        elif code:
            self.code5.append((source, _shingles(_tokens(text, True), 5)))
        else:
            self.prose8.append((source, _shingles(_tokens(text, False), 8, 5)))

    def reasons(self, prompt: str, code: str = "", tests: str = "") -> list[str]:
        """Why a task leaks ([] = clean): shares >= 2 eight-grams of prose (5+ words each) with a visible text, or its code/tests
        have 5-gram Jaccard >= 0.5 or containment >= 0.6 with visible code."""
        out = []
        p8 = _shingles(_tokens(prompt, False), 8, 5)
        for source, sh in self.prose8:
            if len(p8 & sh) >= 2:
                out.append(f"prompt shares phrases with {source}")
                break
        for label, text in (("code", code), ("tests", tests)):
            if not text.strip():
                continue
            mine = _shingles(_tokens(text, True), 5)
            for source, sh in self.code5:
                inter = len(mine & sh)
                if mine and sh and (inter / (len(mine) + len(sh) - inter) >= 0.5 or inter / len(mine) >= 0.6):
                    out.append(f"{label} overlaps {source}")
                    break
        return out
