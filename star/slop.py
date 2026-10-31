"""Anti-slop checker: deterministic, offline findings on an answer's prose, code and UI.

"Slop" is output that looks fine and is worth little: filler and hedging, restating the request, generic advice,
over-long prose, placeholder or dead code, TODO stubs, invented Roblox APIs, tests that assert nothing, generic
"AI-looking" UI and claims of success without evidence. Every rule has an id (P = prose, C = code, U = UI), a weight
and, for the worst kinds, a `hard` flag: a hard finding is what keeps an answer from counting as verified when the
night school gate is on (STAR_NS_SLOP=gate). Pure functions: no model, no network, no file writes.

Wired in three places, all opt-in or measurement-only:
  - night school (server/night_school/nightschool/real.py): STAR_NS_SLOP=measure records the score in each attempt's
    checks; =gate adds a failing check when the answer is slop, so it cannot become a verified worked example;
  - the chat answer (star/doc_grounding.finalize): setting `slop_check` = flag (a short note about invented APIs and
    unverifiable claims) or trim (also removes filler lines outside code);
  - evaluation reports (star/eval_runner.record_for): every task record carries its slop score; pass/fail is untouched.

CLI: `python -m star.slop <result.json|rows.jsonl|answer.md> ...` prints the slop numbers of stored answers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
import re
import sys

from .eval_checks import split_answer

MAX_SCORE = 100
SLOP_SCORE = 30          # at or above: the answer is slop (also when any hard finding is present)
MAX_API_CHARS = 60_000   # the API checker is skipped on absurdly long code
NOTE_MARKER = "\n\nSlop check by STAR:"   # the note doc_grounding.finalize appends; never scored as the model's text

_FENCE = re.compile(r"^[ \t]*```[ \t]*([\w+-]*)[^\n]*\n(.*?)^[ \t]*```[ \t]*$", re.S | re.M)
_WORD = re.compile(r"[A-Za-z][A-Za-z'_-]*")
_STOP = frozenset("a an the and or but of to in on for with by at from as is are was be this that it its into "
                  "your my our you we i me not no do does use using make write create add set get can should "
                  "will would when then than so if also any all each one two".split())


@dataclass(frozen=True)
class Finding:
    rule: str
    weight: int
    message: str
    line: int = 0          # 1-based line in the answer, 0 = whole answer
    hard: bool = False     # blocks "verified" under the night school gate
    trim: bool = False     # a whole filler line that trim_filler removes


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    prose_words: int = 0
    code_chars: int = 0
    blocks: int = 0

    @property
    def score(self) -> int:
        return min(MAX_SCORE, sum(f.weight for f in self.findings))

    @property
    def hard(self) -> bool:
        return any(f.hard for f in self.findings)

    @property
    def slop(self) -> bool:
        return self.hard or self.score >= SLOP_SCORE

    @property
    def rules(self) -> list[str]:
        return sorted({f.rule for f in self.findings})

    def record(self) -> dict:
        return {"score": self.score, "hard": self.hard, "slop": self.slop, "rules": self.rules,
                "prose_words": self.prose_words, "code_chars": self.code_chars,
                "findings": [{"rule": f.rule, "line": f.line, "message": f.message, "hard": f.hard}
                             for f in self.findings[:40]]}

    def summary(self) -> str:
        return f"slop {self.score}" + (" HARD" if self.hard else "") + (": " + ", ".join(self.rules) if self.rules else "")


# --- splitting the answer -------------------------------------------------------------------------------------

def _language(info: str, code: str) -> str:
    tag = (info or "").strip().lower()
    if tag in ("lua", "luau"):
        return "luau"
    if tag in ("py", "python", "python3"):
        return "python"
    if tag in ("ts", "tsx", "typescript", "js", "jsx", "javascript", "mjs"):
        return "ts"
    if tag in ("html", "css", "svelte", "vue"):
        return "ui"
    if tag:
        return "other"
    if re.search(r"^\s*(?:local\s|function\s|--!)|\bend\s*$", code, re.M):
        return "luau"
    if re.search(r"^\s*(?:def |import |from \S+ import )", code, re.M):
        return "python"
    if re.search(r"^\s*(?:const|let|export|import)\s|=>", code, re.M):
        return "ts"
    if re.search(r"<(?:div|html|section|button|body)\b", code):
        return "ui"
    return "other"


def _parts(answer: str) -> tuple[str, list[tuple[str, str, int]]]:
    """(prose with every code block blanked line for line, [(language, code, start line)])."""
    blocks: list[tuple[str, str, int]] = []
    prose_pieces: list[str] = []
    last = 0
    for match in _FENCE.finditer(answer):
        prose_pieces.append(answer[last:match.start()])
        prose_pieces.append("\n" * match.group(0).count("\n"))
        blocks.append((_language(match.group(1), match.group(2)), match.group(2),
                       answer.count("\n", 0, match.start()) + 2))
        last = match.end()
    tail = answer[last:]
    if "```" in tail:                      # an unclosed fence: the rest is code, not prose
        head, _, rest = tail.partition("```")
        prose_pieces.append(head)
        rest = rest.split("\n", 1)
        if len(rest) == 2:
            blocks.append((_language(rest[0], rest[1]), rest[1], answer.count("\n", 0, last + len(head)) + 2))
    else:
        prose_pieces.append(tail)
    return "".join(prose_pieces), blocks


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text) if len(w) > 2 and w.lower() not in _STOP}


# --- prose rules ----------------------------------------------------------------------------------------------

_OPENER = re.compile(
    r"^\s*(?:(?:certainly|sure|absolutely|of course|great question|good question|okay|ok)[!.,]?\s*)+"
    r"(?:(?:here(?:'s| is| are) (?:the|a|an|your|my) [^.\n]{0,60}[:.!]?)|(?:i(?:'d| would) be (?:happy|glad) to help[^.\n]{0,60}[.!]?)|"
    r"(?:let(?:'s| us) (?:dive|get started|begin|go)[^.\n]{0,40}[.!:]?))?\s*$"
    r"|^\s*(?:i(?:'d| would) be (?:happy|glad) to (?:help|assist)[^.\n]{0,80}[.!]?)\s*$"
    r"|^\s*here(?:'s| is| are) (?:the|a|an|your|my) (?:(?:complete|full|updated|corrected|fixed|final|working|revised|"
    r"improved|requested|clean|new|implementation|solution|code|script|module|modulescript|localscript|version)\s?){1,4}"
    r"(?:(?:for|of|that|you) [^.\n]{0,50})?[:.!]?\s*$", re.I)
_CLOSER = re.compile(
    r"^\s*(?:[*_]*)(?:(?:i )?hope (?:this|that|it) helps[^.\n]{0,40}[.!]?|let me know if (?:you|there)[^.\n]{0,100}[.!?]?|"
    r"feel free to [^.\n]{0,100}[.!]?|happy (?:coding|building|scripting)[!.]?|"
    r"if you have any (?:other |further |more )?questions[^.\n]{0,80}[.!]?|"
    r"(?:don't|do not) hesitate to [^.\n]{0,80}[.!]?|good luck[^.\n]{0,40}[!.]?|"
    r"i hope (?:this|you)[^.\n]{0,60}[.!]?|enjoy[^.\n]{0,30}[!.]?)(?:[*_]*)\s*$", re.I)
_META_AI = re.compile(r"\bas an ai\b|\bas a (?:large )?language model\b|\bi(?:'m| am) (?:just )?an ai\b|"
                      r"\bi (?:do not|don't|cannot|can't) have (?:access to|the ability to) (?:run|execute|test)\b", re.I)
_HEDGE = re.compile(r"\b(?:it'?s worth noting|it is worth noting|generally speaking|in most cases|in some cases|"
                    r"may or may not|it depends|typically|you might want to|you may want to|could potentially|"
                    r"may vary|keep in mind|note that|please note|as needed|if necessary|and so on|etc\.?|"
                    r"depending on your (?:needs|use case|requirements)|as appropriate|for the most part|arguably)\b", re.I)
_GENERIC = re.compile(r"\b(?:follow(?:ing)? best practices|make sure to test(?: it| this|\b)[^.\n]{0,30}|"
                      r"remember to (?:test|handle|check|always)\b|always handle errors|"
                      r"consider adding (?:error handling|logging|validation|more features)|"
                      r"you can (?:customize|extend|adjust|tweak|modify|expand) (?:this|the code|it) (?:further|as needed|to fit)|"
                      r"this is (?:a )?(?:basic|simple|minimal|starting)[- ](?:implementation|example|version|point)|"
                      r"you may want to add (?:more|additional)|feel free to (?:adjust|modify|customize)|"
                      r"for (?:a )?production(?:-ready)? (?:use|code|environment)[^.\n]{0,40}(?:you (?:should|would|will) want|consider|add)|"
                      r"thoroughly test|test (?:it |this )?thoroughly|ensure (?:that )?(?:everything|it) works (?:correctly|as expected))\b", re.I)
_CLAIM = re.compile(r"\b(?:i(?:'ve| have)? (?:tested|ran|run|verified|confirmed|checked)(?: this| it| the code)?|"
                    r"(?:this|the) (?:code|script|module|solution|implementation) (?:has been|was|is) (?:tested|verified)|"
                    r"tested and (?:working|verified|confirmed)|works (?:perfectly|flawlessly|great|100%)|"
                    r"fully (?:functional|tested|working)|production[- ]ready|bug[- ]free|guaranteed to work|"
                    r"(?:has|have) been thoroughly tested)\b", re.I)
_VAGUE = re.compile(r"\b(?:robust|seamless(?:ly)?|leverage[sd]?|comprehensive|elegant(?:ly)?|cutting[- ]edge|"
                    r"powerful|streamlined?|state[- ]of[- ]the[- ]art|best[- ]in[- ]class|scalable|effortless(?:ly)?|"
                    r"delve|tapestry|game[- ]changer|crucial|vital|enhance[sd]?|utilize[sd]?)\b", re.I)
_SUMMARY_HEAD = re.compile(r"^\s*(?:#{1,6}\s*|\*\*)?(?:summary|conclusion|in summary|key takeaways|wrap[- ]up|"
                           r"final thoughts|recap|to summarize)\b[^\n]*$", re.I | re.M)
_EVIDENCE = re.compile(r"\b(?:expected output|output:|test output|passed \d+|\d+ passed|assert|spec|unit test)", re.I)


def _lines_with(pattern: re.Pattern, text: str) -> list[int]:
    return [n for n, line in enumerate(text.splitlines(), 1) if pattern.search(line)]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 20]


def check_prose(prose: str, *, prompt: str = "", code_chars: int = 0, findings: list[Finding] | None = None,
                line_base: int = 1) -> list[Finding]:
    out = findings if findings is not None else []
    lines = prose.splitlines()
    words = len(_WORD.findall(prose))
    for number, line in enumerate(lines, line_base):
        if _OPENER.fullmatch(line.strip()) and line.strip():
            out.append(Finding("P01.filler_opener", 2, "filler opener line", number, trim=True))
        elif _CLOSER.fullmatch(line.strip()) and line.strip():
            out.append(Finding("P02.closing_offer", 2, "closing offer line", number, trim=True))
        elif _META_AI.search(line):
            out.append(Finding("P09.meta_ai", 3, "talks about being an AI", number))
    if prompt and lines:
        first = next((l for l in lines if len(l.split()) >= 6 and not l.lstrip().startswith(("#", "-", "*", "|"))), "")
        asked, said = _tokens(prompt), _tokens(first)
        if len(asked) >= 8 and said and len(asked & said) / max(1, len(said)) >= 0.75 and len(said) >= 8:
            out.append(Finding("P03.restates_request", 4, "first paragraph restates the request"))
    hedges = _HEDGE.findall(prose)
    allowed = max(1, words // 100)
    if len(hedges) > allowed:
        out.append(Finding("P04.hedge_density", min(10, len(hedges) - allowed),
                           f"{len(hedges)} hedges in {words} words"))
    generic = _lines_with(_GENERIC, prose)
    for number in generic[:3]:
        out.append(Finding("P05.generic_advice", 3, "generic advice without specifics", number + line_base - 1))
    claims = _lines_with(_CLAIM, prose)
    if claims and not _EVIDENCE.search(prose):
        out.append(Finding("P06.unverified_claim", 8, "claims the code was tested or works, without evidence",
                           claims[0] + line_base - 1, hard=True))
    # Prose-only answers (documentation, analysis) may need their words; an answer with code rarely does.
    long, very_long = (400, 700) if code_chars else (600, 900)
    if words > very_long:
        out.append(Finding("P07.overlong", 8, f"{words} words of prose"))
    elif words > long:
        out.append(Finding("P07.overlong", 4, f"{words} words of prose"))
    elif code_chars and words > 300 and words * 6 > 4 * code_chars:
        out.append(Finding("P07.overlong", 3, f"{words} words of prose around {code_chars} chars of code"))
    head = _SUMMARY_HEAD.search(prose)
    if head:
        before, after = _sentences(prose[:head.start()]), _sentences(prose[head.end():])
        if len(after) >= 2 and before:
            seen = [_tokens(s) for s in before]
            repeated = sum(1 for s in after if any(len(_tokens(s) & t) >= 0.6 * max(1, len(_tokens(s))) for t in seen))
            if repeated >= max(2, len(after) // 2):
                out.append(Finding("P08.summary_echo", 4, "a summary section repeats what was already said",
                                   prose.count("\n", 0, head.start()) + line_base))
    vague = _VAGUE.findall(prose)
    if words and len(vague) > max(2, words // 60):
        out.append(Finding("P10.vague_words", min(6, len(vague) - max(2, words // 60)),
                           f"{len(vague)} vague words in {words} words"))
    return out


# --- code rules -----------------------------------------------------------------------------------------------

_TODO = re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b|\b(?:implement(?:ation)? (?:this|here|later)|your (?:code|logic) here|"
                   r"rest of (?:the|your) code|add (?:your )?(?:logic|code|implementation) here|"
                   r"(?:logic|code|implementation) goes here|to be implemented|not implemented(?! error)|"
                   r"placeholder (?:for|implementation|logic|function|code)|\(placeholder\))\b", re.I)
_ELLIPSIS_LINE = re.compile(r"^\s*(?:\.\.\.|…)\s*(?:--.*|//.*|#.*)?$", re.M)
_PLACEHOLDER = re.compile(r"\b(?:YOUR_[A-Z_]+|INSERT_[A-Z_]+|CHANGE_?ME|REPLACE_?ME|your[-_ ]api[-_ ]key|<your[^>]{0,40}>|"
                          r"path\.to\.(?:module|script|folder)|TBD|xxxx+)\b", re.I)
_COMMENT_CODE = re.compile(r"^\s*(?:--|//|#)\s*(?:[A-Za-z_][\w.:]*(?:\(|\s*=\s*[^=]|\.[A-Za-z_])|local\s|end\s*$|return\b|if\b.*\bthen\b|"
                           r"for\b.*\b(?:do|in)\b|function\b|const\s|let\s|def\s)", re.M)
_ILLUSTRATION = re.compile(r"^\s*(?:--|//|#)\s*(?:result|output|example|e\.g\.|prints?|returns?|expected|yields?|gives?|"
                           r"usage|sample|shape|structure|format|produces?)\b[^\n]*:\s*$", re.I)
_DEBUG = re.compile(r"\b(?:print|console\.log|warn)\(\s*(?:\"|')(?:debug|here|test|hello|hi|xxx|asdf|got here|reached|works?)\b", re.I)
_SWALLOW = re.compile(r"except(?:\s+\w+(?:\s+as\s+\w+)?)?\s*:\s*(?:#[^\n]*)?\n\s*pass\b|catch\s*(?:\([^)]*\))?\s*\{\s*\}", re.S)

_PY_FUNC = re.compile(r"^(?P<indent>[ \t]*)(?:async\s+)?def\s+(?P<name>\w+)\s*\(.*?\)\s*(?:->[^:]+)?:\s*$", re.M)
_TS_TEST = re.compile(r"\b(?:it|test)\s*\(\s*(?:\"|'|`)(?P<name>[^\"'`]*)(?:\"|'|`)\s*,\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>\s*\{|"
                      r"\b(?:it|test)\s*\(\s*(?:\"|'|`)(?P<name2>[^\"'`]*)(?:\"|'|`)\s*,\s*(?:async\s+)?function\s*\([^)]*\)\s*\{")
_LUAU_TEST = re.compile(r"\b(?:it|test)\s*\(\s*(?:\"|')(?P<name>[^\"']*)(?:\"|')\s*,\s*function\s*\([^)]*\)")
_TS_FUNC = re.compile(r"(?:function\s+\w+\s*\([^)]*\)|=>)\s*\{")
_LUAU_FUNC = re.compile(r"\bfunction\b[^\n(]*\([^)]*\)")
_VACUOUS = re.compile(r"\bassert\s*\(?\s*(?:True|true|1)\s*\)?(?:\s*,|\s*$)|expect\s*\(\s*(?:true|1)\s*\)\s*\.\s*(?:toBe|toEqual|to\.equal)\s*\(\s*(?:true|1)\s*\)|"
                      r"expect\s*\(\s*true\s*\)\s*\.\s*toBeTruthy\s*\(\s*\)|assert\.(?:ok|isTrue|strictEqual)\s*\(\s*(?:true|1)\s*(?:,\s*(?:true|1)\s*)?\)", re.M)
_NOT_IMPLEMENTED = re.compile(r"raise\s+NotImplementedError|throw\s+new\s+Error\s*\(\s*(?:\"|')(?:not implemented|todo|unimplemented)", re.I)


def _block_end(lines: list[str], start: int, opener: str) -> int:
    """Index after the matching `end` of a Luau function whose header is at `start`; keyword depth only."""
    depth = 0
    for i in range(start, len(lines)):
        words = re.findall(r"\b(?:function|if|for|while|do|end|repeat|until)\b", _strip_luau_line(lines[i]))
        for w in words:
            if w in ("function", "if", "for", "while", "repeat"):
                depth += 1
            elif w == "do" and not re.search(r"\b(?:for|while)\b.*\bdo\b", lines[i]):
                depth += 1
            elif w in ("end", "until"):
                depth -= 1
                if depth <= 0:
                    return i + 1
    return len(lines)


def _strip_luau_line(line: str) -> str:
    line = re.sub(r"(['\"]).*?(?<!\\)\1", "''", line)
    return line.split("--", 1)[0]


def _py_body(lines: list[str], start: int, indent: str) -> list[str]:
    body = []
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if len(line) - len(line.lstrip()) <= len(indent) and line.strip():
            break
        body.append(line)
    return body


def _ts_body(code: str, open_brace: int) -> str:
    depth = 0
    for i in range(open_brace, len(code)):
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return code[open_brace + 1:i]
    return code[open_brace + 1:]


def _is_test_name(name: str) -> bool:
    return name.startswith("test") or name.endswith("_test") or name.startswith("it_")


def _unreachable(lines: list[str], language: str) -> list[int]:
    """Lines of code right after a `return` at the same indentation (not `end`/`else`/`}`/`until`/`elseif`/`except`)."""
    found = []
    closers = {"luau": r"^\s*(?:end|else|elseif|until)\b", "python": r"^\s*(?:except|finally|elif|else|@|def|class)\b",
               "ts": r"^\s*(?:\}|case\b|default\b|\)|\]|/[/*])"}[language]
    for i, line in enumerate(lines[:-1]):
        if not re.match(r"^\s*return\b", line) or line.rstrip().endswith((",", "(", "{", "[", "\\")):
            continue
        indent = len(line) - len(line.lstrip())
        for nxt in lines[i + 1:]:
            if not nxt.strip() or re.match(r"^\s*(?:--|//|#)", nxt):
                continue
            nindent = len(nxt) - len(nxt.lstrip())
            if nindent == indent and not re.match(closers, nxt) and not re.match(r"^\s*(?:\}|end)\b", nxt):
                found.append(i + 2)
            break
    return found


def check_code(code: str, language: str, *, api_dump=None, first_block: bool = True, line_base: int = 1,
               findings: list[Finding] | None = None) -> list[Finding]:
    out = findings if findings is not None else []
    lines = code.splitlines()
    for number in _lines_with(_TODO, code)[:4]:
        out.append(Finding("C01.todo_stub", 6, "TODO / placeholder comment instead of code", number + line_base - 1, hard=True))
    if _ELLIPSIS_LINE.search(code) and language != "python":
        out.append(Finding("C01.todo_stub", 6, "an ellipsis stands in for code", line_base, hard=True))
    for match in _NOT_IMPLEMENTED.finditer(code):
        out.append(Finding("C02.empty_body", 6, "a function only raises not-implemented",
                           code.count("\n", 0, match.start()) + line_base, hard=True))
    if language == "python":
        for match in _PY_FUNC.finditer(code):
            start = code.count("\n", 0, match.start())
            body = _py_body(lines, start, match.group("indent"))
            stripped = [b.strip() for b in body if not b.strip().startswith("#")]
            doc_only = all(s.startswith(("\"\"\"", "'''", "\"", "'")) for s in stripped) if stripped else True
            if not stripped or stripped == ["pass"] or stripped == ["..."] or (doc_only and len(stripped) <= 3):
                out.append(Finding("C02.empty_body", 6, f"function {match.group('name')} has no body",
                                   start + line_base, hard=True))
            elif _is_test_name(match.group("name")) and not re.search(r"\bassert\b|\.assert\w*\(|pytest\.raises|\.raises\(", "\n".join(body)):
                out.append(Finding("C06.test_without_assert", 8, f"test {match.group('name')} asserts nothing",
                                   start + line_base, hard=True))
    elif language == "ts":
        for match in _TS_TEST.finditer(code):
            body = _ts_body(code, code.index("{", match.end() - 1))
            if not re.search(r"\bexpect\s*\(|\bassert\b|\.(?:should|rejects|resolves)\b|toThrow|\bthrows?\b", body):
                out.append(Finding("C06.test_without_assert", 8,
                                   f"test '{(match.group('name') or match.group('name2') or '')[:40]}' asserts nothing",
                                   code.count("\n", 0, match.start()) + line_base, hard=True))
        for match in _TS_FUNC.finditer(code):
            body = _ts_body(code, match.end() - 1)
            if body.strip() and not re.sub(r"//[^\n]*|/\*.*?\*/", "", body, flags=re.S).strip():
                out.append(Finding("C02.empty_body", 4, "a function body holds only comments",
                                   code.count("\n", 0, match.start()) + line_base))
    elif language == "luau":
        for match in _LUAU_TEST.finditer(code):
            start = code.count("\n", 0, match.start())
            end = _block_end(lines, start, "function")
            body = "\n".join(lines[start + 1:end - 1])
            if not re.search(r"\bexpect\s*\(|\bassert\s*\(|\berror\s*\(|\.toBe|\.to\.", body):
                out.append(Finding("C06.test_without_assert", 8, f"test '{match.group('name')[:40]}' asserts nothing",
                                   start + line_base, hard=True))
        for match in _LUAU_FUNC.finditer(code):
            start = code.count("\n", 0, match.start())
            end = _block_end(lines, start, "function")
            body = [l for l in lines[start + 1:end - 1] if l.strip()]
            if body and all(l.strip().startswith("--") for l in body):
                out.append(Finding("C02.empty_body", 6, "a function body holds only comments", start + line_base, hard=True))
    if vacuous := _VACUOUS.search(code):
        out.append(Finding("C07.vacuous_assert", 6, "an assertion that is always true",
                           code.count("\n", 0, vacuous.start()) + line_base, hard=True))
    for number in _lines_with(_PLACEHOLDER, code)[:3]:
        out.append(Finding("C03.placeholder_value", 3 if first_block else 1, "placeholder value left in the code",
                           number + line_base - 1))
    comment_lines = _lines_with(_COMMENT_CODE, code)
    run = 1
    for a, b in zip(comment_lines, comment_lines[1:]):
        run = run + 1 if b == a + 1 else 1
        if run == 3:
            first = a - 1                                # 1-based line of the run's first comment
            lead = lines[first - 2] if first >= 2 else ""
            if _ILLUSTRATION.match(lead):               # "-- Result:" then a commented value: an illustration
                continue
            out.append(Finding("C04.commented_out_code", 3, "commented-out code", first + line_base - 1))
    if language in ("luau", "python", "ts"):
        for number in _unreachable(lines, language)[:2]:
            out.append(Finding("C05.unreachable", 4, "code after a return is never reached", number + line_base - 1))
    for number in _lines_with(_DEBUG, code)[:2]:
        out.append(Finding("C09.debug_leftover", 2, "debug print left in", number + line_base - 1))
    for match in _SWALLOW.finditer(code):
        out.append(Finding("C10.swallowed_error", 4, "an error is caught and dropped",
                           code.count("\n", 0, match.start()) + line_base))
    if language == "luau" and api_dump is not None and len(code) <= MAX_API_CHARS:
        from .roblox_api_checker import check_luau_api
        try:
            api = check_luau_api(code, api_dump)
        except Exception:        # the checker is advisory; a parse surprise must not break the score
            api = []
        for finding in api[:6]:
            if finding.rule_id in ("unknown-class", "unknown-service"):
                out.append(Finding("C08.invented_api", 10, f"{finding.rule_id}: {finding.name[:40]}",
                                   finding.line + line_base - 1, hard=True))
            else:
                out.append(Finding("C08.unknown_member", 4,
                                   f"possible unknown member {finding.name[:40]}" +
                                   (f" of {finding.class_name}" if finding.class_name else ""),
                                   finding.line + line_base - 1))
    return out


# --- UI rules -------------------------------------------------------------------------------------------------

_UI_PLACEHOLDER = re.compile(r"\blorem ipsum\b|\byour (?:company|brand|product|app) (?:name|here)\b|\bfeature (?:1|2|3|one|two|three)\b|"
                             r"\bclick here\b|\bjohn doe\b|\bproduct name\b|\bcompany name\b|\bimage placeholder\b", re.I)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅❌]")
_VIOLET = re.compile(r"linear-gradient\([^)]*(?:#(?:6366f1|8b5cf6|a855f7|7c3aed|4f46e5|9333ea|ec4899|d946ef|6d28d9|c084fc)|purple|violet|indigo)|"
                     r"\b(?:from|to|via)-(?:purple|violet|indigo|fuchsia|pink)-\d{3}\b|bg-gradient-to-[rltb]\b", re.I)
_GLASS = re.compile(r"backdrop-filter\s*:\s*blur|\bbackdrop-blur(?:-\w+)?\b", re.I)
_CTA = re.compile(r"get started\s*(?:→|->|&rarr;)?\s*<|learn more\s*(?:→|->|&rarr;)?\s*<", re.I)


def check_ui(code: str, *, line_base: int = 1, findings: list[Finding] | None = None) -> list[Finding]:
    out = findings if findings is not None else []
    for number in _lines_with(_UI_PLACEHOLDER, code)[:3]:
        out.append(Finding("U01.placeholder_copy", 4, "placeholder copy instead of real words", number + line_base - 1))
    emoji = _EMOJI.findall(code)
    if len(emoji) >= 2:
        out.append(Finding("U02.emoji_icons", 3, f"{len(emoji)} emoji used as icons or bullets", line_base))
    if violet := _VIOLET.search(code):
        out.append(Finding("U03.gradient_violet", 4, "violet/indigo gradient, the default AI palette",
                           code.count("\n", 0, violet.start()) + line_base))
    if len(_GLASS.findall(code)) >= 2:
        out.append(Finding("U04.glass", 3, "backdrop-blur glass panels", line_base))
    if len(_CTA.findall(code)) >= 2:
        out.append(Finding("U05.generic_cta", 3, "'Get started' / 'Learn more' twin buttons", line_base))
    return out


# --- the whole answer -----------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def bundled_api_dump():
    """The validated local Roblox API dump shipped with STAR (None when it cannot be loaded)."""
    try:
        from .roblox_api_dataset import api_dump
        return api_dump()
    except Exception:
        return None


def score_answer(answer: str, *, prompt: str = "", api_dump=None, use_api_dump: bool = True) -> Report:
    """Findings for the model's text; what STAR appended (Luau check note, sources) is ignored.

    `api_dump`: an ApiDump for invented-API checks; None loads the bundled one (unless `use_api_dump` is False).
    """
    if not isinstance(answer, str):
        raise TypeError("answer must be str")
    body, _ = split_answer(answer)
    body = body.split(NOTE_MARKER, 1)[0]
    prose, blocks = _parts(body)
    report = Report(prose_words=len(_WORD.findall(prose)), code_chars=sum(len(c) for _, c, _ in blocks),
                    blocks=len(blocks))
    dump = api_dump if api_dump is not None else (bundled_api_dump() if use_api_dump else None)
    check_prose(prose, prompt=prompt, code_chars=report.code_chars, findings=report.findings)
    seen: set[str] = set()
    for index, (language, code, start) in enumerate(blocks):
        key = re.sub(r"\s+", " ", code).strip()
        if len(key) > 80 and key in seen:
            report.findings.append(Finding("C11.duplicate_block", 3, "the same code block appears twice", start))
            continue
        seen.add(key)
        if language == "ui":
            check_ui(code, line_base=start, findings=report.findings)
            check_code(code, "ts", first_block=index == 0, line_base=start, findings=report.findings)
        elif language == "other":
            check_ui(code, line_base=start, findings=report.findings) if re.search(r"<\w+[^>]*>", code) else None
        else:
            check_code(code, language, api_dump=dump, first_block=index == 0, line_base=start, findings=report.findings)
            if language in ("ts", "luau") and re.search(r"<(?:div|section|Frame|TextLabel|TextButton)\b|UICorner|UIGradient", code):
                check_ui(code, line_base=start, findings=report.findings)
    report.findings.sort(key=lambda f: (f.line, f.rule))
    return report


def trim_filler(answer: str) -> tuple[str, list[str]]:
    """Remove whole filler lines (openers, closing offers) outside code fences. Returns (text, removed lines)."""
    body, footer = split_answer(answer)
    removed: list[str] = []
    kept: list[str] = []
    in_code = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            kept.append(line)
            continue
        text = line.strip()
        if not in_code and text and (_OPENER.fullmatch(text) or _CLOSER.fullmatch(text)):
            removed.append(line)
            continue
        kept.append(line)
    if not removed:
        return answer, []
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip("\n")
    return (text + ("\n" if body.endswith("\n") else "")) + footer, removed


def answer_note(report: Report) -> str:
    """A one-paragraph note for the chat answer: only the findings a reader must know about."""
    parts = []
    invented = [f for f in report.findings if f.rule == "C08.invented_api"]
    if invented:
        names = sorted({f.message.split(": ", 1)[-1] for f in invented})
        parts.append("the code names Roblox API(s) not in the local API dump: " + ", ".join(names[:4]) +
                     "; treat them as unverified")
    if any(f.rule == "P06.unverified_claim" for f in report.findings):
        parts.append("the answer claims the code was tested; STAR did not run it")
    stubs = [f for f in report.findings if f.rule in ("C01.todo_stub", "C02.empty_body")]
    if stubs:
        parts.append(f"{len(stubs)} placeholder or empty function(s) still need real code")
    if any(f.rule in ("C06.test_without_assert", "C07.vacuous_assert") for f in report.findings):
        parts.append("a test asserts nothing")
    return ("; ".join(parts) + ".") if parts else ""


# --- CLI: slop numbers of stored answers --------------------------------------------------------------------

def _rows(path: str) -> list[dict]:
    """Rows {answer, passed|None, id, prompt} from an eval result JSON, a JSONL of answers, or a text file."""
    raw = open(path, encoding="utf-8").read()
    if path.endswith(".jsonl"):
        rows = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            answer = row.get("answer") or row.get("response") or ""
            passed = row.get("passed")
            rows.append({"answer": answer, "passed": passed if isinstance(passed, bool) else None,
                         "id": str(row.get("id", "")), "prompt": row.get("prompt") or row.get("instruction") or ""})
        return rows
    if path.endswith(".json"):
        data = json.loads(raw)
        tasks = data.get("tasks") if isinstance(data, dict) else None
        if isinstance(tasks, dict):
            return [{"answer": r.get("answer") or "", "passed": r.get("passed") if r.get("status") in ("pass", "fail") else None,
                     "id": tid, "prompt": ""} for tid, r in tasks.items() if r.get("answer")]
        raise ValueError(f"{path}: not an evaluation result file")
    return [{"answer": raw, "passed": None, "id": path, "prompt": ""}]


def measure(rows: list[dict], *, prompts: dict[str, str] | None = None, use_api_dump: bool = True) -> dict:
    """Slop numbers for rows {answer, passed, id, prompt}: mean score, slop share, rule counts, pass/fail split."""
    scored = []
    for row in rows:
        prompt = row.get("prompt") or (prompts or {}).get(row.get("id", ""), "")
        scored.append((row, score_answer(row["answer"], prompt=prompt, use_api_dump=use_api_dump)))
    rules: dict[str, int] = {}
    for _, report in scored:
        for rule in report.rules:
            rules[rule] = rules.get(rule, 0) + 1
    out = {"answers": len(scored),
           "mean_score": round(sum(r.score for _, r in scored) / max(1, len(scored)), 1),
           "slop_share": round(sum(1 for _, r in scored if r.slop) / max(1, len(scored)), 3),
           "hard_share": round(sum(1 for _, r in scored if r.hard) / max(1, len(scored)), 3),
           "rules": dict(sorted(rules.items(), key=lambda kv: -kv[1]))}
    labelled = [(row["passed"], report) for row, report in scored if row.get("passed") is not None]
    if labelled:
        passed = [r for p, r in labelled if p]
        failed = [r for p, r in labelled if not p]
        slop_pass = sum(1 for r in passed if r.slop)
        slop_fail = sum(1 for r in failed if r.slop)
        out["by_outcome"] = {
            "pass": {"n": len(passed), "mean_score": round(sum(r.score for r in passed) / max(1, len(passed)), 1),
                     "slop_share": round(slop_pass / max(1, len(passed)), 3)},
            "fail": {"n": len(failed), "mean_score": round(sum(r.score for r in failed) / max(1, len(failed)), 1),
                     "slop_share": round(slop_fail / max(1, len(failed)), 3)},
            "fail_rate_slop": round(slop_fail / max(1, slop_fail + slop_pass), 3),
            "fail_rate_clean": round((len(failed) - slop_fail) / max(1, len(labelled) - slop_fail - slop_pass), 3)}
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import random

    parser = argparse.ArgumentParser(prog="python -m star.slop", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("paths", nargs="+", help="eval result .json, answers .jsonl, or text files")
    parser.add_argument("--prompts", action="append", default=[], help="suite JSON (id -> prompt) for the restating rule")
    parser.add_argument("--sample", type=int, default=0, help="write N random flagged findings for hand-checking")
    parser.add_argument("--out", default="", help="where the sample goes (JSONL)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--no-api-dump", action="store_true")
    args = parser.parse_args(argv)
    prompts: dict[str, str] = {}
    for path in args.prompts:
        data = json.loads(open(path, encoding="utf-8").read())
        for task in (data.get("tasks") if isinstance(data, dict) else data) or []:
            if isinstance(task, dict) and task.get("id") and task.get("prompt"):
                prompts[task["id"]] = task["prompt"]
    rows = []
    for path in args.paths:
        rows.extend(_rows(path))
    result = measure(rows, prompts=prompts, use_api_dump=not args.no_api_dump)
    print(json.dumps(result, indent=1))
    if args.sample and args.out:
        flagged = []
        for row in rows:
            report = score_answer(row["answer"], prompt=row.get("prompt") or prompts.get(row.get("id", ""), ""),
                                  use_api_dump=not args.no_api_dump)
            for finding in report.findings:
                flagged.append({"id": row["id"], "passed": row["passed"], "rule": finding.rule, "line": finding.line,
                                "message": finding.message, "answer": row["answer"]})
        random.Random(args.seed).shuffle(flagged)
        with open(args.out, "w", encoding="utf-8") as handle:
            for item in flagged[:args.sample]:
                handle.write(json.dumps(item) + "\n")
        print(f"wrote {min(args.sample, len(flagged))} of {len(flagged)} findings to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
