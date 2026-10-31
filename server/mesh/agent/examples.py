"""Worked examples the USER wrote in the question, as checks the agent can run for real.

    io_examples(question)   -> [(stdin, stdout)]      "Input: ... Output: ...", "Sample input/output", "with this
                                                       input ```...``` the program should print ```...```"
    call_examples(question) -> [(call, expected)]     "`f([1, 2])` should give `"1-2"`", "f(3) returns 6"

Only what the question states is used (never invented by the model: model-written tests were measured as a bad
filter, docs/agents/polyglot-20261029.md).
"""
from __future__ import annotations

import re

FENCE = re.compile(r"(?P<f>`{3,}|~{3,})[^\n`]*\n(?P<code>.*?)\n?(?P=f)", re.S)
IN_LABEL = re.compile(r"\b(input|stdin|given)\b", re.I)
OUT_LABEL = re.compile(r"\b(output|outputs|print|prints|printed|should print|should output|stdout|expected|result|"
                       r"answer is|gives)\b", re.I)
INLINE = re.compile(r"^\s*(?:sample |example )?input\s*:\s*`?(?P<i>[^`\n]+?)`?\s*\n\s*(?:sample |example |expected )?"
                    r"output\s*:\s*`?(?P<o>[^`\n]+?)`?\s*$", re.I | re.M)
CALL = re.compile(r"`(?P<call>[A-Za-z_$][\w$.]*\((?:[^`]*)\))`\s*(?:,\s*)?(?:should\s+(?:give|return|be|print)|"
                  r"gives|returns|is|=>|->|→|==|evaluates to|outputs)\s*(?::\s*)?`(?P<exp>[^`]+)`")
CALL_BARE = re.compile(r"(?<![\w.`])(?P<call>[A-Za-z_][\w]*\([^()\n`]*\))\s*(?:should\s+(?:give|return|be)|gives|returns|"
                       r"=>|->|→|==)\s*(?P<exp>-?\d+(?:\.\d+)?|true|false|True|False|None|null|\"[^\"\n]*\"|'[^'\n]*')")


def io_examples(question: str) -> list[tuple[str, str]]:
    q = question or ""
    pairs: list[tuple[str, str]] = []
    pending: str | None = None
    prev = 0
    for m in FENCE.finditer(q):
        label = q[prev:m.start()][-160:]
        prev = m.end()
        code = m.group("code")
        last_in, last_out = _last(IN_LABEL, label), _last(OUT_LABEL, label)
        if last_in > last_out:
            pending = code
        elif last_out >= 0 and pending is not None:
            pairs.append((_nl(pending), code.strip("\n")))
            pending = None
        else:
            pending = None
    for m in INLINE.finditer(q):
        pairs.append((_nl(m.group("i").strip()), m.group("o").strip()))
    return pairs[:6]


def call_examples(question: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for rx in (CALL, CALL_BARE):
        for m in rx.finditer(question or ""):
            item = (m.group("call").strip(), m.group("exp").strip())
            if item not in out:
                out.append(item)
    return out[:6]


def _last(rx: re.Pattern, text: str) -> int:
    pos = -1
    for m in rx.finditer(text):
        pos = m.start()
    return pos


def _nl(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def same_output(got: str, want: str) -> bool:
    """Exact up to trailing spaces / blank lines; then the same tokens in the same order."""
    a = "\n".join(ln.rstrip() for ln in (got or "").strip().splitlines())
    b = "\n".join(ln.rstrip() for ln in (want or "").strip().splitlines())
    return a == b or a.split() == b.split()
