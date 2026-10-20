"""Diff-only answers for edit requests (opt-in: Settings.edit_diff).

When the owner pastes code and asks for a change, writing the whole file again is most of the turn on a CPU
server (~10 tokens/s: a 120-line script is ~1,200 tokens, two minutes, for an 8-line change). With this on, the
model is asked for SEARCH/REPLACE blocks only (Aider's edit format, https://aider.chat/docs/benchmarks.html).
STAR applies them to the pasted code with whole-line matching (star/edit_match.py: exact or a uniform indentation
shift; an ambiguous place is refused), checks the result is not worse than the original (Luau compile check and
lint counts), and shows the prose plus the full edited code. Anything that does not apply or checks worse returns
``ok=False`` and the caller asks again for the normal full answer.

Pure functions; the only outside call is the optional ``check(code)`` the caller passes (the knowledge service's
``luau_check``).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from .edit_match import EditMismatch, apply_edit

MIN_SOURCE_LINES = 12          # shorter snippets gain little; the normal answer is kept
MAX_SOURCE_CHARS = 60_000
FENCE = chr(96) * 3
_FENCED = re.compile(r"^[ \t]*" + FENCE + r"[ \t]*([\w+#.-]*)[^\n]*\n(.*?)^[ \t]*" + FENCE + r"[ \t]*$", re.M | re.S)
# Lowercase code keywords only: an English sentence starts with a capital letter.
_CODE_START = re.compile(r"^[ \t]*(?:--|local\b|function\b|export\b|type\b|return\b|if\b|for\b|while\b|repeat\b|"
                         r"def\b|class\b|import\b|from\b|const\b|let\b|var\b|#include\b|@)")
_PROSE_LINE = re.compile(r"^[A-Z][^(){}=\[\]<>;]{40,}[.?!:]\s*$")
_EDIT_WORDS = re.compile(r"(?i)\b(?:fix|fixes|change|modify|update|add|remove|delete|rename|refactor|replace|"
                         r"make|edit|debug|optimi[sz]e|convert|clean|improve|adjust|tweak|patch|correct|move)\b")
_LUAU_HINT = re.compile(r"(?m)^\s*(?:local\b|end\b|function\b|return\b)|\bthen\b|:Connect\(|game:GetService\(")
_BLOCK = re.compile(r"^<{5,9}[ \t]*SEARCH[^\n]*\n(.*?)^={5,9}[ \t]*\n(.*?)^>{5,9}[ \t]*REPLACE[^\n]*$", re.M | re.S)
_HUNK = re.compile(r"^@@[^\n]*@@[^\n]*$", re.M)
_EMPTY_FENCE = re.compile(r"^[ \t]*" + FENCE + r"[\w+#.-]*[ \t]*\n(?:[ \t]*\n)*[ \t]*" + FENCE + r"[ \t]*$\n?", re.M)

INSTRUCTION = (
    "STAR edit mode: the code above is the file to change. Do not write the whole file again. First say in one "
    "or two sentences what you change and why. Then give only the changes, each as a SEARCH/REPLACE block in "
    "exactly this form:\n\n"
    "<<<<<<< SEARCH\n"
    "lines copied exactly from the code above, with their indentation, enough to match one place only\n"
    "=======\n"
    "the new lines that replace them\n"
    ">>>>>>> REPLACE\n\n"
    "Use one short block per place you change. To add code, SEARCH for the line just above where it goes and "
    "repeat that line at the top of REPLACE. To delete code, leave REPLACE empty. STAR applies the blocks to the "
    "code and shows the full result."
)


@dataclass(frozen=True)
class EditRequest:
    source: str     # the pasted code, exactly as given
    lang: str       # the fence language in the prompt, "luau" for unfenced Luau, else ""
    prompt: str     # the prompt to send: the owner's words plus INSTRUCTION


@dataclass(frozen=True)
class Outcome:
    ok: bool
    answer: str     # what to show (ok) or "" (not ok)
    reason: str     # "applied", "full" (the model wrote the whole code anyway) or why it failed
    edits: int = 0


def find_edit(prompt: str) -> EditRequest | None:
    """An EditRequest when the prompt carries one piece of code (>= MIN_SOURCE_LINES lines) and asks to change it."""
    if not isinstance(prompt, str) or len(prompt) > MAX_SOURCE_CHARS + 4000:
        return None
    blocks = [(m.group(1).lower(), m.group(2)) for m in _FENCED.finditer(prompt)]
    if blocks:
        long = [b for b in blocks if b[1].count("\n") >= MIN_SOURCE_LINES]
        if len(long) != 1:
            return None          # no code to edit, or several files: the normal answer decides
        lang, source = long[0]
        words = _FENCED.sub("", prompt)
    else:
        lines = prompt.split("\n")
        start = next((i for i, line in enumerate(lines) if _CODE_START.match(line)), None)
        if start is None or start == 0:
            return None
        code = lines[start:]
        while code and not code[-1].strip():
            code.pop()
        if len(code) < MIN_SOURCE_LINES or any(_PROSE_LINE.match(line) for line in code):
            return None          # a sentence after the code: the boundary is not clear
        source, words = "\n".join(code) + "\n", "\n".join(lines[:start])
        lang = "luau" if _LUAU_HINT.search(source) else ""
    if not _EDIT_WORDS.search(words) or len(source) > MAX_SOURCE_CHARS:
        return None
    if lang in ("lua", "") and _LUAU_HINT.search(source):
        lang = lang or "luau"
    return EditRequest(source, lang, prompt.rstrip() + "\n\n" + INSTRUCTION)


def parse_edits(answer: str) -> list[tuple[str, str]]:
    """(search, replace) pairs from SEARCH/REPLACE blocks, else from unified-diff hunks."""
    pairs = [(_one_newline(m.group(1)), _one_newline(m.group(2))) for m in _BLOCK.finditer(answer or "")]
    return pairs or _hunks(answer or "")


def apply_edits(source: str, edits: list[tuple[str, str]]) -> str:
    """Apply the pairs in order (whole lines only); raises EditMismatch when one cannot be placed safely."""
    text = source
    for search, replace in edits:
        if search == replace:
            continue
        if not search.strip():
            raise EditMismatch("a SEARCH section is empty")
        text = apply_edit(text, search, replace, whole_lines=True).text
    return text


def finish(request: EditRequest, answer: str, *, check=None, lint=None) -> Outcome:
    """Apply the model's edit answer to the pasted code and check it; see the module text."""
    edits = parse_edits(answer)
    if not edits:
        if _has_full_code(answer, request.source):
            return Outcome(True, answer, "full")
        return Outcome(False, "", "no SEARCH/REPLACE blocks")
    try:
        edited = apply_edits(request.source, edits)
    except EditMismatch as exc:
        return Outcome(False, "", "did not apply: " + str(exc).split("\n")[0][:160])
    if edited == request.source:
        return Outcome(False, "", "the blocks change nothing")
    if request.lang in ("luau", "lua"):
        worse = _worse(request.source, edited, check, lint)
        if worse:
            return Outcome(False, "", worse)
    prose = _EMPTY_FENCE.sub("", _BLOCK.sub("", answer) if _BLOCK.search(answer) else _strip_hunks(answer)).strip()
    shown = (prose + "\n\n" if prose else "") + FENCE + request.lang + "\n" + edited.rstrip("\n") + "\n" + FENCE
    return Outcome(True, shown, "applied", len(edits))


def _one_newline(text: str) -> str:
    return text[:-1] if text.endswith("\n") else text


def _hunks(answer: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for found in _HUNK.finditer(answer):
        old: list[str] = []
        new: list[str] = []
        for line in answer[found.end() + 1:].split("\n"):
            if line.startswith("@@") or line.strip().startswith(FENCE) or line.startswith(("--- ", "+++ ")):
                break
            if line.startswith("+"):
                new.append(line[1:])
            elif line.startswith("-"):
                old.append(line[1:])
            elif line.startswith(" ") or not line:
                old.append(line[1:])
                new.append(line[1:])
            else:
                break
        while old and new and not old[-1].strip() and not new[-1].strip():
            old.pop()
            new.pop()
        if old:
            pairs.append(("\n".join(old), "\n".join(new)))
    return pairs


def _strip_hunks(answer: str) -> str:
    """The answer without its diff fences (the prose around them stays)."""
    return re.sub(r"^[ \t]*" + FENCE + r"[ \t]*(?:diff|patch)?[^\n]*\n(?:(?!" + FENCE + r").*\n)*?[ \t]*"
                  + FENCE + r"[ \t]*$", "", answer, flags=re.M)


def _has_full_code(answer: str, source: str) -> bool:
    longest = max((m.group(2) for m in _FENCED.finditer(answer or "")), key=len, default="")
    return longest.count("\n") >= 0.6 * source.count("\n")


def _worse(before: str, after: str, check, lint) -> str:
    """Why `after` checks worse than `before`, or ""."""
    if check is not None:
        try:
            old, new = check(before), check(after)
        except (OSError, ValueError):
            old = new = None        # the check did not run: no claim either way
        if isinstance(new, dict) and new.get("ran") is True and new.get("ok") is not True:
            base = old.get("error_count", 0) if isinstance(old, dict) and old.get("ran") is True else 0
            if int(new.get("error_count") or 1) > base:
                return f"Luau check: {new.get('error_count') or 1} error(s) after the edit, {base} before"
    if lint is None:
        from .luau_lint import lint
    added = Counter(f.rule_id for f in lint(after)) - Counter(f.rule_id for f in lint(before))
    if added:
        return "lint: new " + ", ".join(sorted(added))
    return ""
