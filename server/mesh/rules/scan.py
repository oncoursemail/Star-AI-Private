"""Reading an answer the way the rules need it: fenced code blocks, the label that says what each block is and where it
goes ("**LocalScript (inside StarterPlayerScripts):**", "-- Server Script in ServerScriptService", "Place a Script
inside your Part"), the prose outside the code, and a light Luau scan (comments and strings blanked with the same
length, `function ... end` bodies found by keyword depth). Stdlib only, no model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FENCE = re.compile(r"^(?P<ind>[ \t]{0,3})(?P<f>`{3,}|~{3,})[ \t]*(?P<info>[^\n`]*)\n(?P<code>.*?)^(?P=ind)(?P=f)[ \t]*$",
                   re.M | re.S)
LUAU_TAGS = {"lua", "luau", "rbxlua", "roblox", ""}

# where a script can be put, by what the label calls it
CLIENT_PLACES = re.compile(r"StarterPlayerScripts|StarterCharacterScripts|StarterGui|PlayerGui|PlayerScripts|"
                           r"ScreenGui|TextButton|ImageButton|\bGUI\b|\bFrame\b|\bButton\b(?!\s+part)|ReplicatedFirst",
                           re.I)
TOOL_PLACES = re.compile(r"\bTool\b|StarterPack|Backpack", re.I)
SSS = re.compile(r"ServerScriptService", re.I)
STORAGE = re.compile(r"ReplicatedStorage|ServerStorage", re.I)
WORLD_PLACES = re.compile(r"\bWorkspace\b|\b(the |your |a |an |each |that |this )?(door|part|brick|block|coin|pad|platform|"
                          r"lava|kill ?brick|npc|model|proximityprompt|prompt|clickdetector|button part|trap|zone|"
                          r"checkpoint|spawn ?location|wall|floor|belt|conveyor|hinge ?part|sign|chest|orb|gem|"
                          r"teleporter|portal)s?\b", re.I)


@dataclass
class Block:
    index: int
    lang: str
    code: str               # raw code
    clean: str              # comments and strings blanked (same length)
    nocomment: str          # comments blanked, strings kept
    label: str              # prose line(s) just before the block + the block's leading comments
    kind: str               # "local" | "server" | "module" | "either" | ""
    place: str              # "client" | "tool" | "sss" | "storage" | "world" | ""
    start: int              # offsets of the code in the answer
    end: int
    luau: bool = True


@dataclass
class Answer:
    text: str
    prose: str              # the answer with code blocks removed
    blocks: list[Block] = field(default_factory=list)

    @property
    def luau(self) -> list[Block]:
        return [b for b in self.blocks if b.luau]

    @property
    def all_code(self) -> str:
        return "\n".join(b.code for b in self.luau)


# ---- Luau text helpers ------------------------------------------------------------------------------------------------
_LONG = re.compile(r"\[(=*)\[.*?\]\1\]", re.S)


def blank(code: str, strings: bool = True) -> str:
    """Comments (and, with strings=True, string literals) replaced by spaces, newlines kept, so offsets match."""
    out = []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if code.startswith("--", i):
            m = _LONG.match(code, i + 2)
            j = m.end() if m else (code.find("\n", i) if code.find("\n", i) != -1 else n)
            out.append(re.sub(r"[^\n]", " ", code[i:j]))
            i = j
        elif c in "\"'`":
            j = i + 1
            while j < n and code[j] != c and code[j] != "\n":
                j += 2 if code[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(code[i] + " " * max(0, j - i - 2) + code[j - 1] if strings and j - i >= 2 else code[i:j])
            i = j
        elif c == "[" and _LONG.match(code, i):
            m = _LONG.match(code, i)
            out.append(re.sub(r"[^\n]", " ", m.group(0)) if strings else m.group(0))
            i = m.end()
        else:
            out.append(c)
            i += 1
    return "".join(out)


_KW = re.compile(r"(?<![\w.:])(function|if|do|repeat|end|until)(?![\w])")


def body_end(clean: str, start: int) -> int:
    """`start` is just after a `function` keyword (or any opener): offset of its matching `end` (len when unclosed)."""
    depth = 1
    for m in _KW.finditer(clean, start):
        w = m.group(1)
        if w in ("function", "if", "do", "repeat"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.start()
    return len(clean)


FUNC_AT = re.compile(r"(?<![\w.:])function\b\s*[\w.:]*\s*\(([^)]*)\)")


def handlers(clean: str, event: str) -> list[tuple[list[str], str]]:
    """Bodies connected to `<x>.<event>:Connect(...)`: [(params, body)], inline functions and named local functions."""
    out = []
    for m in re.finditer(rf"\.{event}\s*:\s*(?:Connect|Once|ConnectParallel)\s*\(\s*", clean):
        rest = clean[m.end():]
        fm = FUNC_AT.match(rest)
        if fm:
            s = m.end() + fm.end()
            out.append(([p.strip() for p in fm.group(1).split(",") if p.strip()], clean[s:body_end(clean, s)]))
            continue
        nm = re.match(r"([A-Za-z_]\w*)\s*\)", rest)
        if nm:
            dm = re.search(rf"(?<![\w.:])(?:local\s+)?function\s+{nm.group(1)}\s*\(([^)]*)\)", clean)
            if dm:
                s = dm.end()
                out.append(([p.strip() for p in dm.group(1).split(",") if p.strip()], clean[s:body_end(clean, s)]))
    return out


def protected_spans(clean: str) -> list[tuple[int, int]]:
    """Spans of code that run inside pcall/xpcall: inline `pcall(function ... end)` and named functions passed to pcall."""
    spans = []
    for m in re.finditer(r"(?<![\w.:])x?pcall\s*\(\s*function\b[^(]*\(", clean):
        s = m.end()
        spans.append((s, body_end(clean, s)))
    for m in re.finditer(r"(?<![\w.:])x?pcall\s*\(\s*([A-Za-z_]\w*)\s*[,)]", clean):
        dm = re.search(rf"(?<![\w.:])(?:local\s+)?function\s+{m.group(1)}\s*\([^)]*\)", clean)
        if dm:
            spans.append((dm.end(), body_end(clean, dm.end())))
        else:
            lm = re.search(rf"(?<![\w.:])local\s+{m.group(1)}\s*=\s*function\s*\([^)]*\)", clean)
            if lm:
                spans.append((lm.end(), body_end(clean, lm.end())))
    return spans


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ---- labels -----------------------------------------------------------------------------------------------------------
def classify_label(label: str) -> tuple[str, str]:
    """(kind, place) from a label like '**LocalScript (inside StarterPlayerScripts):**'."""
    low = label.lower()
    if re.search(r"runcontext", low):
        return "either", ""
    has_local = bool(re.search(r"local ?script", low))
    has_module = "modulescript" in low or "module script" in low
    no_local = re.sub(r"local ?script|module ?script", " ", low)
    has_server = bool(re.search(r"server[- ]?(side )?script|\bscript\b", no_local))
    if has_module and not has_local:
        kind = "module"
    elif has_local and re.search(r"local ?script\s*(or|/)\s*(a\s+)?(server\s+)?script|(server\s+)?script\s*(or|/)\s*"
                                 r"(a\s+)?local ?script", low):
        kind = "either"
    elif has_local:
        kind = "local"
    elif has_server:
        kind = "server"
    else:
        kind = ""
    # the place: where the script goes is usually named right after the script word ("put this Script inside your
    # Lucky Block part", not "your rewards in ServerStorage"); fall back to the whole label
    m = None
    for m in re.finditer(r"script\b", label, re.I):
        pass
    after = label[m.end():] if m else ""
    place = _place(after) if re.search(r"\b(in|inside|into|under|to)\b", after, re.I) else ""
    return kind, place or _place(label)


def _place(label: str) -> str:
    if SSS.search(label):
        return "sss"
    if CLIENT_PLACES.search(label):
        return "client"
    if TOOL_PLACES.search(label):
        return "tool"
    if STORAGE.search(label):
        return "storage"
    if re.search(r"\b(in|inside|into|under|to)\b", label, re.I) and WORLD_PLACES.search(label):
        return "world"
    return ""


def _label_for(text: str, prev_end: int, m: re.Match) -> str:
    """The closest prose line before the block when it reads like a label (short or ending with ':'), plus the block's
    leading comment lines. A leading comment that names the script type wins over the prose line."""
    before = text[prev_end:m.start()]
    lines = [ln.strip() for ln in before.strip().split("\n") if ln.strip()]
    pre = ""
    if lines:
        last = lines[-1]
        if last.rstrip("*").endswith(":") or len(last) <= 140:
            pre = last
        if pre and len(lines) > 1 and not re.search(r"script|server|client", pre, re.I) and \
                re.search(r"script", lines[-2], re.I) and (lines[-2].rstrip("*").endswith(":") or len(lines[-2]) <= 140):
            pre = lines[-2] + " " + pre
    head = []
    for ln in m.group("code").split("\n")[:4]:
        st = ln.strip()
        if st.startswith("--"):
            head.append(st)
        elif st:
            break
    head_s = " ".join(head)
    if re.search(r"\b(local ?script|server ?script|module ?script|script)\b", head_s, re.I):
        return head_s
    return (pre + " " + head_s).strip()


def comment_kinds(code: str) -> set[str]:
    """Script types the block's comments name ("-- Put this in a LocalScript ...", "-- Server Script ...")."""
    kinds = set()
    for c in re.findall(r"--[^\n]*", code):
        if re.search(r"\blocal ?script\b", c, re.I):
            kinds.add("local")
        if re.search(r"\bmodule ?script\b", c, re.I):
            kinds.add("module")
        if re.search(r"\b(server ?)?script\b", re.sub(r"(?i)(local|module) ?script", " ", c), re.I):
            kinds.add("server")
    return kinds


def parse(text: str) -> Answer:
    blocks, prose_parts, prev = [], [], 0
    for i, m in enumerate(FENCE.finditer(text)):
        prose_parts.append(text[prev:m.start()])
        label = _label_for(text, prev, m)
        info = (m.group("info") or "").strip().lower().split(" ")[0]
        code = m.group("code")
        kind, place = classify_label(label)
        if len(comment_kinds(code)) > 1:
            kind = "either"          # one block showing several scripts (a comparison or a demo)
        is_luau = info in LUAU_TAGS and not re.search(r"\b(using UnityEngine|public class|void Start|#include)\b|"
                                                       r"^\s*/?(execute|give|tp|summon|scoreboard)\b", code, re.M)
        blocks.append(Block(i, info, code, blank(code), blank(code, strings=False), label, kind, place,
                            m.start("code"), m.end("code"), is_luau))
        prev = m.end()
    prose_parts.append(text[prev:])
    return Answer(text, "\n".join(prose_parts), blocks)


def sentences(prose: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", prose) if s.strip()]


NEGATION = re.compile(r"\b(not|n't|never|no longer|cannot|can't|won't|only run|instead of|don't|doesn't|isn't|avoid|"
                      r"mistake|wrong|myth|unlike)\b|\bnot\b", re.I)
