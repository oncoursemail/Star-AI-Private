"""A lenient SNBT reader (Minecraft's stringified NBT, 1.20.5-1.21.x and 26.x): enough to tell valid from broken and to
give the parsed value to the checks. Raises SnbtError(pos, message).

    value, end = parse(text, pos=0)
"""
from __future__ import annotations

import re

UNQUOTED = re.compile(r"[0-9A-Za-z_\-.+]+")
NUMBER = re.compile(r"[-+]?(0x[0-9a-fA-F_]+|0b[01_]+|(\d[\d_]*)?\.?\d[\d_]*(e[-+]?\d+)?)([bslfdBSLFD]|[us][bsil])?$")
ARRAY_TYPES = {"B", "I", "L"}


class SnbtError(ValueError):
    def __init__(self, pos: int, message: str):
        super().__init__(message)
        self.pos = pos
        self.message = message


class Num(float):
    """A number with its SNBT suffix (b, s, l, f, d or '')."""
    suffix = ""


def _ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def _quoted(s: str, i: int) -> tuple[str, int]:
    q, i, out = s[i], i + 1, []
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
            continue
        if ch == q:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise SnbtError(i, "unclosed quoted string")


def parse(s: str, i: int = 0):
    i = _ws(s, i)
    if i >= len(s):
        raise SnbtError(i, "expected a value")
    ch = s[i]
    if ch == "{":
        out, i = {}, _ws(s, i + 1)
        if i < len(s) and s[i] == "}":
            return out, i + 1
        while True:
            i = _ws(s, i)
            if i < len(s) and s[i] in "\"'":
                key, i = _quoted(s, i)
            else:
                m = UNQUOTED.match(s, i)
                if not m:
                    raise SnbtError(i, "expected a key")
                key, i = m.group(0), m.end()
            i = _ws(s, i)
            if i >= len(s) or s[i] != ":":
                raise SnbtError(i, f"expected ':' after key '{key}'")
            val, i = parse(s, i + 1)
            out[key] = val
            i = _ws(s, i)
            if i < len(s) and s[i] == ",":
                i = _ws(s, i + 1)
                if i < len(s) and s[i] == "}":          # trailing comma (accepted since 1.21.5)
                    return out, i + 1
                continue
            if i < len(s) and s[i] == "}":
                return out, i + 1
            raise SnbtError(i, "expected ',' or '}'")
    if ch == "[":
        i = _ws(s, i + 1)
        if i + 1 < len(s) and s[i] in ARRAY_TYPES and s[i + 1] == ";":
            i += 2
        out = []
        i = _ws(s, i)
        if i < len(s) and s[i] == "]":
            return out, i + 1
        while True:
            val, i = parse(s, i)
            out.append(val)
            i = _ws(s, i)
            if i < len(s) and s[i] == ",":
                i = _ws(s, i + 1)
                if i < len(s) and s[i] == "]":
                    return out, i + 1
                continue
            if i < len(s) and s[i] == "]":
                return out, i + 1
            raise SnbtError(i, "expected ',' or ']'")
    if ch in "\"'":
        return _quoted(s, i)
    m = UNQUOTED.match(s, i)
    if not m:
        raise SnbtError(i, f"unexpected '{ch}'")
    word, end = m.group(0), m.end()
    if end < len(s) and s[end] == "(" and word in ("bool", "uuid"):       # 1.21.5 operations: bool(x), uuid("...")
        depth, j = 0, end
        while j < len(s):
            depth += {"(": 1, ")": -1}.get(s[j], 0)
            j += 1
            if depth == 0:
                return word, j
        raise SnbtError(end, "unclosed '('")
    if word in ("true", "false"):
        return word == "true", end
    if NUMBER.match(word):
        try:
            n = Num(float(re.sub(r"[bslfdBSLFD]$|[us][bsil]$|_", "", word)) if not word.lower().startswith(("0x", "0b",
                    "-0x", "-0b", "+0x", "+0b")) else 0)
        except ValueError:
            return word, end
        n.suffix = word[-1].lower() if word[-1].isalpha() and not word.lower().startswith(("0x", "-0x")) else ""
        return n, end
    return word, end


def parse_all(s: str):
    val, end = parse(s, 0)
    end = _ws(s, end)
    if end != len(s):
        raise SnbtError(end, f"trailing data after the value: '{s[end:end + 20]}'")
    return val
