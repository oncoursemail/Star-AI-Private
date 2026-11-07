"""Which parts of a PR diff Litha's merge review sees, most important first, inside her 4096-token window.

Measured on 62 real PRs (her own tokenizer, llama-server /tokenize): the old 12,000-character chunks put 410 of 598
review prompts over 4096 tokens with the 700-token answer (real code diffs run ~3.1 characters per token, not 3.5),
so they only worked on the 8192-token node and were refused (HTTP 400) by the 4096 one.

Hunks are ranked (code over config over tests over docs over data and lockfiles; removed guards, changed conditions
and dangerous calls rank higher) and packed into at most MAX_PARTS prompts that each fit the window. What did not
fit is listed, never silently cut. Each risk must quote a changed line; `anchor` finds that line in the diff.
"""
from __future__ import annotations

import re

from litha import self_map

ANSWER = 700                           # tokens kept for her answer
MARGIN = 1.15                          # worst hunk estimate was 0.8x the real count; whole prompts average out
MAX_PARTS = 12                         # review calls per PR (~4 s each); 62 real PRs: 565 calls, 53% of code lines
OMIT_CHARS = 300                       # the "not in this part" file list is cut to this

DATA = re.compile(r"\.(json|jsonl|lock|csv|tsv|sha256|patch|svg|png|webp|jpg|gif|ico|snap|min\.js|map|tsbuildinfo)$"
                  r"|(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|Cargo\.lock|poetry\.lock|uv\.lock)$", re.I)
DOCS = re.compile(r"\.(md|txt|rst|adoc)$|(^|/)docs?/", re.I)
TESTS = re.compile(r"(^|/)(tests?|__tests__|fixtures?|testdata)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$",
                   re.I)
CONFIG = re.compile(r"\.(ya?ml|toml|cfg|ini|cmd|bat|ps1|sh|service|in)$|(^|/)(Dockerfile|Makefile|requirements[^/]*)$",
                    re.I)
WEIGHT = {"code": 3.0, "config": 2.5, "test": 1.2, "docs": 0.5, "data": 0.1}
GUARD = re.compile(r"^\s*(if|elif|while|assert|raise|except|try|with|return|match|guard|unless)\b"
                   r"|\b(lock|timeout|check|valid|verify|permission|auth|allow|deny|limit|max|min)\w*", re.I)
COND = re.compile(r"^\s*(if|elif|while|assert|for|match|case|when)\b|[<>!=]=|&&|\|\||\band\b|\bor\b|\bnot\b")
DANGER = re.compile(r"subprocess|shell\s*=\s*True|os\.system|rmtree|unlink\(|\.remove\(|rm -rf|\bDROP\b|\beval\(|"
                    r"\bexec\(|pickle|\bunsafe\b|--force|chmod|token|secret|password|credential|delete", re.I)


def tokens(text: str) -> int:
    """Her tokenizer, estimated from character classes (fit on 1600 real diff hunks: median 1.0x, worst 0.8x)."""
    letters = digits = spaces = other = 0
    for c in text:
        if c.isascii() and c.isalpha():
            letters += 1
        elif c.isdigit():
            digits += 1
        elif c == " ":
            spaces += 1
        elif c != "\n":
            other += 3 if not c.isascii() else 1
    return round(0.2 * letters + 1.3 * digits + 0.06 * spaces + 1.8 * text.count("\n") + 0.8 * other) + 1


def kind(path: str) -> str:
    for name, rx in (("data", DATA), ("test", TESTS), ("docs", DOCS), ("config", CONFIG)):
        if rx.search(path):
            return name
    return "code"


def hunks(files: dict[str, dict]) -> list[dict]:
    """Every hunk: {path, order, header, lines, start (new line number of its first line), score}."""
    out = []
    for path, f in files.items():
        cur = None
        for line in f["text"].splitlines():
            if line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                cur = {"path": path, "order": len(out), "header": line, "lines": [], "start": int(m.group(1)) if m else 0}
                out.append(cur)
            elif cur is not None and not line.startswith("\\ No newline"):
                cur["lines"].append(line)
    for h in out:
        h["score"] = score(h)
    return out


def score(h: dict) -> float:
    """Kind weight x (1 + risk signals): a removed guard, a changed condition, a dangerous call."""
    gone = [ln[1:] for ln in h["lines"] if ln.startswith("-")]
    new = [ln[1:] for ln in h["lines"] if ln.startswith("+")]
    risk = min(6.0, 2.0 * sum(bool(GUARD.search(ln)) for ln in gone))
    risk += 1.5 if any(COND.search(ln) for ln in gone) and any(COND.search(ln) for ln in new) else 0
    risk += min(4.0, sum(bool(DANGER.search(ln)) for ln in new))
    risk += 1.0 if gone and not new else 0
    return WEIGHT[kind(h["path"])] * (1 + risk)


def split(h: dict, budget: int) -> list[dict]:
    """A hunk bigger than one part, cut at line boundaries; each piece gets a header with its real start line."""
    pieces, cur, cost, new_no = [], [], 0, h["start"]
    start = new_no
    for ln in h["lines"]:
        c = tokens(ln + "\n")
        if cur and cost + c > budget:
            pieces.append({**h, "lines": cur, "start": start, "header": f"@@ +{start} @@ (hunk continues)"})
            cur, cost, start = [], 0, new_no
        cur.append(ln[:2000])
        cost += c
        new_no += not ln.startswith("-")
    pieces.append({**h, "lines": cur, "start": start, "header": h["header"] if not pieces else f"@@ +{start} @@"})
    return pieces


def render(part: list[dict]) -> str:
    text, last = "", None
    for h in sorted(part, key=lambda h: (h["order"], h["start"])):
        if h["path"] != last:
            text += f"diff --git a/{h['path']} b/{h['path']}\n"
            last = h["path"]
        text += h["header"] + "\n" + "".join(ln + "\n" for ln in h["lines"])
    return text


def pack(files: dict[str, dict], budget: int, max_parts: int = MAX_PARTS) -> tuple[list[str], list[str]]:
    """(parts, not reviewed: one "path (kind)" per file with a hunk that did not fit). Highest score first, first fit;
    each part costs at most `budget` estimated tokens (a piece's cost counts its own file header line)."""
    pieces = []
    for h in hunks(files):
        pieces += split(h, budget - 60) if tokens(render([h])) > budget else [h]
    for h in pieces:
        h["cost"] = tokens(render([h]))
    pieces.sort(key=lambda h: (-h["score"], h["order"]))
    bins: list[list[dict]] = []
    used: list[int] = []
    left: dict[str, str] = {}
    for h in pieces:
        i = next((i for i, u in enumerate(used) if u + h["cost"] <= budget), None)
        if i is None and len(bins) < max_parts:
            bins.append([])
            used.append(0)
            i = len(bins) - 1
        if i is None:
            left[h["path"]] = f"{h['path']} ({kind(h['path'])})"
            continue
        bins[i].append(h)
        used[i] += h["cost"]
    order = sorted(bins, key=lambda b: min(h["order"] for h in b))
    left.update({p: f"{p} (no text diff)" for p in files if not any(h["path"] == p for h in pieces)})
    return [render(b) for b in order], list(left.values())


def others_note(part: str, files: dict[str, dict], left: list[str]) -> str:
    """The files this part does not show, so 'the diff is cut off' is never her only explanation."""
    shown = set(re.findall(r"^diff --git a/(.+?) b/", part, re.M))
    rest = [p for p in files if p not in shown]
    if not rest:
        return ""
    names = ", ".join(rest)
    if len(names) > OMIT_CHARS:
        names = names[:OMIT_CHARS].rsplit(", ", 1)[0] + ", ..."
    return (f"\nThis PR changes {len(files)} files; this part shows {len(shown)}. The other {len(rest)} are reviewed "
            f"in other parts{f' ({len(left)} skipped for room)' if left else ''}, not a fault of the PR: {names}\n")


def changed(f: dict) -> list[tuple[int, str, str]]:
    """(new line number, '+' or '-', text) for every changed line; a removed line gets the number of the next new
    line, where it used to be."""
    out, no = [], 0
    for line in f["text"].splitlines():
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            no = int(m.group(1)) if m else 0
        elif line.startswith(("+++", "---", "diff --git", "index ")):
            continue
        elif line.startswith("+"):
            out.append((no, "+", line[1:]))
            no += 1
        elif line.startswith("-"):
            out.append((no, "-", line[1:]))
        elif not line.startswith("\\"):
            no += 1
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^\s*([+-]\s)?\d*:?\s?", "", s)).strip()


def quotes(quote: str, line: str) -> bool:
    """`quote` is this line, or a part of it of at least 12 characters (she often drops a trailing `{` or comment),
    ignoring whitespace and a leading "+ " / "12: "."""
    q, ln = _norm(quote), _norm(line)
    return bool(q) and (q == ln or (len(q) >= 12 and q in ln))


def anchor(risk: dict, f: dict) -> tuple[int | None, str]:
    """(line, why not) for a claim: its quote must be a changed line of this file (exact after whitespace, or a
    part of one of at least 12 characters); the nearest match to the line she gave wins. Without a quote the old
    rule holds: the line must be an added line."""
    quote = _norm(str(risk.get("quote") or ""))
    line = risk.get("line")
    if not quote:
        return (line, "") if line in f["added"] else (None, "line is not an added line and no quote")
    rows = changed(f)
    hits = [no for no, _, text in rows if _norm(text) == quote]
    hits = hits or [no for no, _, text in rows if quotes(quote, text)]
    if not hits:
        return None, "quote is not a changed line"
    return min(hits, key=lambda no: abs(no - (line if isinstance(line, int) else 0))), ""


def budget_for(header: str, files: dict[str, dict]) -> int:
    """Diff tokens one part may hold under this prompt header: window minus answer, header and the longest files
    note this PR can get."""
    worst = others_note("", files, list(files)) if len(files) > 1 else ""
    return int((self_map.WINDOW - ANSWER) / MARGIN) - tokens(header) - tokens(worst)
