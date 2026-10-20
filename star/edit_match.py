"""Find-and-replace edits that tolerate the whitespace slips small local models make.

A model asked for an exact ``old_string`` often gets the code right but the whitespace wrong: a different
indentation depth (or tabs against spaces for the whole block), trailing spaces, ``\\n`` against a file saved with ``\\r\\n``. Refusing those edits costs a
whole tool round (and at 8-10 tokens/s a retry is about a minute); Aider measured the same effect and added flexible
patching (https://aider.chat/docs/benchmarks.html, "flexible patching"). This module tries, in order:

1. ``exact``: the text occurs exactly once (or ``replace_all`` is set and it occurs at least once);
2. ``line_endings``: the same after matching the file's ``\\r\\n`` line endings;
3. ``whitespace``: whole lines that match after ignoring trailing whitespace and a uniform indentation shift.
   The new text is re-indented by the same shift, so the edit keeps the file's own indentation.

Anything looser is refused. Every strategy must find exactly ONE place; two candidate places are refused as
ambiguous, so an edit never lands somewhere the model did not mean. A refusal carries the closest lines of the file
so the next attempt can copy them. Pure functions: no files, no model, no network.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib

MAX_HINT_CHARS = 900
MAX_HINT_WINDOWS = 4000


class EditMismatch(ValueError):
    """The edit cannot be placed safely; the message says why and shows the closest text."""


@dataclass(frozen=True)
class EditResult:
    text: str
    strategy: str   # "exact", "line_endings" or "whitespace"
    count: int      # places replaced


def apply_edit(source: str, old: str, new: str, *, replace_all: bool = False,
               whole_lines: bool = False) -> EditResult:
    """Return ``source`` with ``old`` replaced by ``new``, or raise :class:`EditMismatch`.

    ``whole_lines`` (SEARCH/REPLACE blocks, star/edit_format.py): ``old`` must match complete lines, never a
    part of a line, so only the ``whitespace`` strategy runs (it also covers the exact case)."""
    if not all(isinstance(value, str) for value in (source, old, new)):
        raise TypeError("source, old and new must be str")
    if not old:
        raise EditMismatch("old_string is empty")
    if old == new:
        raise EditMismatch("old_string and new_string are the same")
    if whole_lines:
        found = _whitespace(source, old, new)
        if found is None:
            raise EditMismatch("old_string was not found in the file" + _hint(source, old))
        return found
    found = _exact(source, old, new, replace_all, "exact")
    if found is None and "\r\n" in source and "\r\n" not in old:
        found = _exact(source, old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), replace_all, "line_endings")
    if found is None and not replace_all:
        found = _whitespace(source, old, new)
    if found is None:
        raise EditMismatch("old_string was not found in the file" + _hint(source, old))
    return found


def _exact(source: str, old: str, new: str, replace_all: bool, strategy: str) -> EditResult | None:
    count = source.count(old)
    if count == 0:
        return None
    if count > 1 and not replace_all:
        raise EditMismatch(f"old_string occurs {count} times; include more surrounding lines or set replace_all")
    return EditResult(source.replace(old, new, -1 if replace_all else 1), strategy, count if replace_all else 1)


def _indent(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" \t"))]


def _common_indent(lines: list[str]) -> str:
    indents = [_indent(line) for line in lines if line.strip()]
    if not indents:
        return ""
    prefix = indents[0]
    for indent in indents[1:]:
        while not indent.startswith(prefix):
            prefix = prefix[:-1]
    return prefix


def _whitespace(source: str, old: str, new: str) -> EditResult | None:
    old_lines = [line.rstrip() for line in old.strip("\r\n").replace("\r\n", "\n").split("\n")]
    if not any(line.strip() for line in old_lines):
        return None
    old_cut = len(_common_indent(old_lines))
    wanted = [line[old_cut:] if line.strip() else "" for line in old_lines]
    lines = source.splitlines(keepends=True)
    bare = [line.rstrip("\r\n").rstrip() for line in lines]
    size = len(wanted)
    first = next(i for i, line in enumerate(wanted) if line)
    lead = _indent(wanted[first])        # the first line may be deeper than the block's common indentation
    matches: list[tuple[int, str]] = []
    for start in range(len(lines) - size + 1):
        window = bare[start:start + size]
        have = _indent(window[first])
        if not have.endswith(lead):
            continue
        shift = have[:len(have) - len(lead)]
        if all((not want and not have.strip()) or (want and have == shift + want)
               for want, have in zip(wanted, window)):
            matches.append((start, shift))
            if len(matches) > 1:
                raise EditMismatch("old_string matches several places once whitespace is ignored; "
                                   "include more surrounding lines")
    if not matches:
        return None
    start, shift = matches[0]
    ending = "\r\n" if lines[start].endswith("\r\n") else "\n"
    last = lines[start + size - 1]
    tail = last[len(last.rstrip("\r\n")):]          # "" when the match ends the file without a newline
    new_lines = new.strip("\r\n").replace("\r\n", "\n").split("\n") if new.strip("\r\n") else []
    new_cut = len(_common_indent(new_lines))
    body = ending.join(shift + line[new_cut:] if line.strip() else "" for line in new_lines)
    replacement = body + tail if new_lines else ""
    text = "".join(lines[:start]) + replacement + "".join(lines[start + size:])
    return EditResult(text, "whitespace", 1)


def _hint(source: str, old: str) -> str:
    """The most similar run of lines in ``source`` (same line count as ``old``), for the model's next attempt."""
    lines = source.splitlines()
    want = old.strip("\r\n").replace("\r\n", "\n")
    size = max(1, want.count("\n") + 1)
    if not lines:
        return " (the file is empty)"
    best, best_ratio = 0, 0.0
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2(want)
    step = max(1, (len(lines) - size + 1) // MAX_HINT_WINDOWS)
    for start in range(0, max(1, len(lines) - size + 1), step):
        matcher.set_seq1("\n".join(lines[start:start + size]))
        if matcher.real_quick_ratio() <= best_ratio or matcher.quick_ratio() <= best_ratio:
            continue
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best, best_ratio = start, ratio
    if best_ratio < 0.5:
        return ""
    snippet = "\n".join(lines[best:best + size])[:MAX_HINT_CHARS]
    return (f". Closest text is lines {best + 1}-{min(len(lines), best + size)} "
            f"(similarity {best_ratio:.2f}); copy it exactly:\n{snippet}")
