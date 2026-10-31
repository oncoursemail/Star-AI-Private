"""S2 mistake memory and self-written fixers (setting `mistake_memory`: off | retrieve | fix, default retrieve).

Input: the check-fix loop's mistake log (star/verify_ladder.py: one JSON line per failure with its error signature,
the changed lines of the fix that cleared it, and whether that fix was verified) plus the shipped seed rows.

Retrieval (`retrieve` and `fix`): `pitfalls()` picks the few VERIFIED fixes most like the request (shared API names and
task words), as a small reference note. Nothing is added when nothing matches.

Fixers (`fix` only): when one error signature has MIN_SUPPORT or more verified fixes that make the same token-level
change, `synthesize()` anti-unifies them into a deterministic rewrite (a regex plus replacement and a lint message).
A rule becomes active only if (1) it reproduces every one of its source fixes and (2) it changes none of the guard
blocks (the verified gold bank and the evaluation reference answers). `apply()` then rewrites a Luau block with no
model call; the ladder runs it before any model fix call and keeps it only if the block climbs no worse.

Developer tool: `python -m star.mistake_memory seed|synthesize|report` (see main()).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

MODES = ("off", "retrieve", "fix")
HEADING = "KNOWN PITFALLS (verified fixes from earlier failures; reference data, the user's request comes first)"
MAX_CHARS = 900
MAX_ITEMS = 3
MIN_SUPPORT = 3
SEED_PER_SIGNATURE = 12
MAX_STORED_CASES = 6
ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).with_name("data") / "mistake_memory"
SHIPPED_FIXERS = DATA / "fixers.json"
SHIPPED_SEED = DATA / "seed.jsonl"

_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'|\.\.\.|\.\.|::|~=|==|<=|>=|//|\S")
_WORD = re.compile(r"[A-Za-z_]\w*\Z")
_FENCE = re.compile(r"```[ \t]*(?:lua|luau)\b[^\n]*\n(.*?)```", re.S | re.I)
_STOP = frozenset("""a an and are as at be by do for from has have how i if in is it its make me my not of on or our
so that the then this to use using want we what when where which with without you your local end function return
nil true false then else elseif while repeat until break continue script code roblox luau lua game player players
write create need please help should would could can also each every one new set get add into only more less""".split())


# --- paths and rows ---------------------------------------------------------------------------------------------

def fixers_path() -> Path:
    override = os.environ.get("STAR_FIXERS")
    if override:
        return Path(override)
    from .desktop_core import app_data
    return app_data() / "verify_ladder" / "fixers.json"


def read_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("signature"), str):
                rows.append(row)
    except OSError:
        pass
    return rows


def memory_rows() -> list[dict]:
    """Shipped seed rows plus the user's own mistake log (never raises)."""
    try:
        from .verify_ladder import memory_path
        return read_rows(SHIPPED_SEED) + read_rows(memory_path())
    except Exception:
        return read_rows(SHIPPED_SEED)


# --- masking and applying a fixer -------------------------------------------------------------------------------

def mask(code: str, strings: bool = True) -> str:
    """The code with comments (and, with `strings`, string contents) blanked to spaces, same length."""
    from .luau_lint import _SCAN
    out = list(code)
    for match in _SCAN.finditer(code):
        skip = match.group("skip")
        if not skip or skip.isspace():
            continue
        if not strings and skip[:1] in "\"'[":
            continue
        for i in range(match.start(), match.end()):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def _regex(fixer: dict):
    return re.compile(fixer["pattern"])


def _defined(masked: str, name: str) -> bool:
    """True when the script itself binds `name` (local, function, parameter or loop variable): a call of `name` is
    then not the global the rule is about."""
    n = re.escape(name)
    patterns = (rf"\blocal\s+(?:function\s+)?{n}\b", rf"\bfunction\s+{n}\b", rf"\bfunction\b[^\n]*[(,]\s*{n}\s*[:,)]",
                rf"\blocal\s+[\w,\s]*\b{n}\b[\w,\s]*=", rf"\bfor\s+[\w,\s]*\b{n}\b")
    return any(re.search(pattern, masked) for pattern in patterns)


def _blocked(masked: str, match, start: int) -> bool:
    lead = re.match(r"[A-Za-z_]\w*", match.group(0))
    return bool(lead) and (_defined(masked, lead.group())
                           or bool(re.search(r"(?:function|local)\s+$", masked[max(0, start - 12):start])))


def apply_one(code: str, fixer: dict) -> str:
    try:
        rx = _regex(fixer)
    except re.error:
        return code
    text = mask(code, strings='"' not in fixer["pattern"] and "'" not in fixer["pattern"])
    out, last = [], 0
    for match in rx.finditer(text):
        if match.start() < last or _blocked(text, match, match.start()):
            continue
        out.append(code[last:match.start()])
        out.append(match.expand(fixer["replacement"]))
        last = match.end()
    if not out:
        return code
    out.append(code[last:])
    return "".join(out)


def apply(code: str, fixers: list[dict]) -> tuple[str, list[str]]:
    """Rewrite `code` with every matching fixer in order; returns (new code, ids that changed something)."""
    used: list[str] = []
    for fixer in fixers:
        new = apply_one(code, fixer)
        if new != code:
            code = new
            used.append(fixer["id"])
    return code, used


def lint(code: str, fixers: list[dict]) -> list[tuple[int, str]]:
    """The lint message of each fixer that would change something, with the 1-based line of the first match."""
    found = []
    for fixer in fixers:
        try:
            match = _regex(fixer).search(mask(code, strings='"' not in fixer["pattern"]))
        except re.error:
            continue
        if match and apply_one(code, fixer) != code:
            found.append((code.count("\n", 0, match.start()) + 1, fixer.get("message") or fixer["signature"]))
    return found


# --- storing fixers ----------------------------------------------------------------------------------------------

def _trusted(fixer: dict) -> bool:
    check = fixer.get("validation") or {}
    return (fixer.get("active") is True and check.get("false_changes") == 0 and check.get("guard_blocks", 0) > 0
            and check.get("cases", 0) >= MIN_SUPPORT and check.get("fixed") == check.get("cases"))


def load_fixers(path: Path | None = None) -> list[dict]:
    """Every stored fixer."""
    out: list[dict] = []
    for source in ((SHIPPED_FIXERS, path or fixers_path()) if path is None else (path,)):
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.extend(f for f in data.get("fixers", []) if isinstance(f, dict) and "pattern" in f and "id" in f)
    seen: dict[str, dict] = {}
    for fixer in out:
        seen[fixer["id"]] = fixer
    return list(seen.values())


def active_fixers(path: Path | None = None) -> list[dict]:
    """Only fixers that passed their validation (reproduce their cases, change no guard block)."""
    return [f for f in load_fixers(path) if _trusted(f)]


def save_fixers(fixers: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "fixers": fixers}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# --- learning a fixer from verified fixes -----------------------------------------------------------------------

def parse_diff(diff: str) -> list[tuple[str, str]]:
    """(before line, after line) pairs of a mistake row's changed-lines diff; only when the counts match."""
    removed = [l[1:] for l in str(diff).splitlines() if l.startswith("-")]
    added = [l[1:] for l in str(diff).splitlines() if l.startswith("+")]
    return list(zip(removed, added)) if removed and len(removed) == len(added) else []


def _tokens(line: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(line)]


def _is_word(token: str) -> bool:
    return _WORD.match(token) is not None


def _windows(before: str, after: str) -> dict[tuple[int, int], tuple[list, list]]:
    """The single changed token span of a line pair, widened by 0-2 equal tokens each side."""
    a, b = _tokens(before), _tokens(after)
    ops = [o for o in difflib.SequenceMatcher(None, [t[0] for t in a], [t[0] for t in b], autojunk=False)
           .get_opcodes() if o[0] != "equal"]
    if len(ops) != 1:
        return {}
    _, i1, i2, j1, j2 = ops[0]
    out = {}
    for left in range(3):
        for right in range(3):
            if i1 - left >= 0 and j1 - left >= 0 and i2 + right <= len(a) and j2 + right <= len(b):
                out[(left, right)] = (a[i1 - left:i2 + right], b[j1 - left:j2 + right])
    return out


def _unify(group: list[tuple[list, list, str, str, str]]) -> dict | None:
    """One regex rewrite that explains every case of the group (same token shape), or None."""
    old0, new0, before0, after0, _ = group[0]
    n = len(old0)
    if n == 0 or any(len(g[0]) != n for g in group):
        return None
    caps: dict[int, int] = {}
    seen: dict[int, list[str]] = {}
    for k in range(n):
        values = {g[0][k][0] for g in group}
        if len(values) > 1:
            if not all(_is_word(v) for v in values):
                return None
            caps[k] = len(caps)
            seen[k] = sorted(values)          # a capture matches only the names seen in the source cases
    if n == 1 or len(caps) > 2 or not (0 in caps or any(_is_word(old0[k][0]) and k not in caps for k in range(n))):
        return None
    parts: list[str] = []
    for k, (token, _, _) in enumerate(old0):
        if k:
            parts.append(r"\s+" if _is_word(old0[k - 1][0]) and _is_word(token) else r"\s*")
        parts.append("(?P<v%d>%s)" % (caps[k], "|".join(map(re.escape, seen[k]))) if k in caps else re.escape(token))
    left = r"(?<![\w.:])" if _is_word(old0[0][0]) else ""
    right = r"(?!\w)" if _is_word(old0[-1][0]) else ""
    text = after0[new0[0][1]:new0[-1][2]] if new0 else ""
    replacement = text.replace("\\", "\\\\")
    for k, var in caps.items():
        replacement = re.sub(rf"(?<!\w){re.escape(old0[k][0])}(?!\w)", lambda _m, v=var: f"\\g<v{v}>", replacement)
    pattern = left + "".join(parts) + right
    fixer = {"pattern": pattern, "replacement": replacement}
    try:
        re.compile(pattern)
    except re.error:
        return None
    return fixer


def _fixer_id(fixer: dict) -> str:
    return "fx-" + hashlib.sha1((fixer["pattern"] + "\0" + fixer["replacement"]).encode()).hexdigest()[:8]


def validate(fixer: dict, cases: list[tuple[str, str]], guard: list[tuple[str, str]]) -> dict:
    fixed = sum(1 for before, after in cases if apply_one(before, fixer).strip() == after.strip())
    changed = [label for label, code in guard if apply_one(code, fixer) != code]
    return {"cases": len(cases), "fixed": fixed, "guard_blocks": len(guard), "false_changes": len(changed),
            "changed": changed[:5], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def guard_blocks(extra_answers: Sequence[tuple[str, str]] = ()) -> list[tuple[str, str]]:
    """Luau blocks the fixers must never change: the verified gold bank and the evaluation reference answers
    (plus any `extra_answers`: (label, markdown))."""
    blocks: list[tuple[str, str]] = []

    def take(label: str, markdown: str) -> None:
        for number, found in enumerate(_FENCE.finditer(markdown or ""), 1):
            blocks.append((f"{label}#{number}", found.group(1)))
    try:
        for line in (ROOT / "data" / "gold_bank" / "bank.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            take("gold:" + str(row.get("id")), str(row.get("answer", "")))
    except (OSError, ValueError):
        pass
    for path in sorted((ROOT / "evals" / "roblox" / "reference").glob("*.md")):
        try:
            take("ref:" + path.stem, path.read_text(encoding="utf-8"))
        except OSError:
            pass
    for label, markdown in extra_answers:
        take(label, markdown)
    return blocks


def synthesize(rows: list[dict], guard: list[tuple[str, str]], *, min_support: int = MIN_SUPPORT) -> tuple[list[dict], list[dict]]:
    """(fixers, rejected). Fixers are returned inactive-or-active exactly as validated; rejected say why."""
    by_signature: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)
    for row in rows:
        if row.get("verified") is True and not str(row.get("by", "")).startswith("fixer:"):
            for before, after in parse_diff(row.get("diff", "")):
                if before.strip() != after.strip():
                    by_signature[row["signature"]].append((before, after, row))
    fixers, rejected = [], []
    for signature, cases in sorted(by_signature.items()):
        distinct = {_task_key(row) for _, _, row in cases}
        if len(distinct) < min_support:
            continue
        done = False
        reasons: list[str] = []
        windows = [(before, after, _windows(before, after), _task_key(row)) for before, after, row in cases]
        for width in sorted([(l, r) for l in range(3) for r in range(3)], key=lambda w: (sum(w), w)):
            shaped: dict[tuple[int, int], list] = defaultdict(list)
            for before, after, found, task in windows:
                if width in found:
                    old, new = found[width]
                    shaped[(len(old), len(new))].append((old, new, before, after, task))
            for group in shaped.values():
                if len({g[4] for g in group}) < min_support:
                    continue
                fixer = _unify(group)
                if fixer is None:
                    reasons.append(f"width {width}: the cases do not share one pattern")
                    continue
                check = validate(fixer, [(g[2], g[3]) for g in group], guard)
                fixer.update(signature=signature, id=_fixer_id(fixer), validation=check,
                             message=_message(cases[0][2]), support=len({g[4] for g in group}),
                             cases=[[g[2], g[3]] for g in group[:MAX_STORED_CASES]], created=check["at"],
                             origin=cases[0][2].get("by") or "mined")
                if check["fixed"] != check["cases"]:
                    reasons.append(f"width {width}: reproduces only {check['fixed']} of {check['cases']} cases")
                elif check["guard_blocks"] == 0:
                    reasons.append("no guard blocks available to prove it changes nothing else")
                elif check["false_changes"]:
                    reasons.append(f"width {width}: would change {check['false_changes']} guard block(s), e.g. "
                                   + ", ".join(check["changed"][:2]))
                else:
                    fixer["active"] = True
                    fixers.append(fixer)
                    done = True
                    break
            if done:
                break
        if not done:
            rejected.append({"signature": signature, "cases": len(distinct), "reasons": reasons[:3] or ["no common change"]})
    return fixers, rejected


def _task_key(row: dict) -> str:
    """One failure source per task: the same mistake in two answers to one task counts once."""
    src = str(row.get("src") or row.get("ts") or "")
    return src.split(":", 1)[-1].split("#")[0] + "|" + str(row.get("task", ""))[:60]


def _message(row: dict) -> str:
    return " ".join(str(row.get("message", "")).split())[:160]


# --- retrieval ----------------------------------------------------------------------------------------------------

def _fragment(before: str, after: str, context: int = 10) -> tuple[str, str]:
    """The changed part of a line pair with a little context, so the note stays short."""
    before, after = before.strip(), after.strip()
    head = 0
    while head < min(len(before), len(after)) and before[head] == after[head]:
        head += 1
    tail = 0
    while tail < min(len(before), len(after)) - head and before[-1 - tail] == after[-1 - tail]:
        tail += 1
    start = max(0, head - context)
    return before[start:len(before) - tail + context][:90], after[start:len(after) - tail + context][:90]


def _terms(text: str) -> set[str]:
    words = {w.lower() for w in re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,}", str(text))}
    return {w for w in words if w not in _STOP}


def pitfalls(prompt: str, rows: list[dict] | None = None, *, max_chars: int = MAX_CHARS,
             max_items: int = MAX_ITEMS) -> tuple[str, list[str]]:
    """(note, signatures used). Only verified fixes whose API names or task words appear in `prompt`."""
    rows = memory_rows() if rows is None else rows
    asked = _terms(prompt)
    if not asked or max_chars < 120:
        return "", []
    scored: dict[str, tuple[float, dict]] = {}
    for row in rows:
        if row.get("verified") is not True:
            continue
        pairs = parse_diff(row.get("diff", ""))
        if not pairs:
            continue
        api = _terms(" ".join(b for b, _ in pairs)) | _terms(row.get("apis", ""))
        hit = len(asked & api)
        task = _terms(row.get("task", ""))
        overlap = len(asked & task) / max(6, len(task)) if task else 0.0
        score = hit + overlap
        if hit and score > scored.get(row["signature"], (0.0, {}))[0]:
            scored[row["signature"]] = (score, row)
    lines, used, size = [], [], 0
    for signature, (_, row) in sorted(scored.items(), key=lambda kv: -kv[1][0])[:max_items]:
        before, after = _fragment(*parse_diff(row["diff"])[0])
        line = f"- {_message(row)[:90]} Change `{before}` to `{after}`."
        if size + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used.append(signature)
        size += len(line) + 1
    return "\n".join(lines), used


# --- developer tool: seed and synthesize -------------------------------------------------------------------------

def _eval_blocks(paths: list[Path]) -> list[dict]:
    from .doc_grounding import luau_blocks
    seen: set[str] = set()
    out = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tasks = data.get("tasks") if isinstance(data, dict) else None
        if not isinstance(tasks, dict):
            continue
        for task, record in tasks.items():
            for number, (_, _, code) in enumerate(luau_blocks(str((record or {}).get("answer") or "")), 1):
                key = hashlib.sha1(code.encode()).hexdigest()
                if key not in seen:
                    seen.add(key)
                    out.append({"src": f"{path.parent.name}/{path.stem}:{task}#{number}", "code": code,
                                "status": (record or {}).get("status")})
    return out


def _rename(finding) -> tuple[str, str, bool | None] | None:
    # kind of the third item: True = bare global call, False = method after ':', None = `game.X` service property
    """(old, new, is_global) for the lint findings that are a plain rename; the curated lint tables are the teacher."""
    message, fix = finding.message, finding.suggested_fix
    if finding.rule_id == "service-property":
        m = re.match(r"Service game\.(\w+) accessed as a property\.", message)
        return (m.group(1), f'game:GetService("{m.group(1)}")', None) if m else None
    if finding.rule_id == "deprecated-task-global":
        m = re.match(r"Deprecated global (\w+)\(\)\.", message)
        return (m.group(1), "task." + m.group(1), True) if m else None
    if finding.rule_id == "deprecated-api":
        m, f = re.match(r"(\w+):(\w+) is deprecated\.", message), re.match(r"Use (\w+):(\w+)\.$", fix)
        if m and f and m.group(1) == f.group(1):
            return m.group(2), f.group(2), False
        m, f = re.match(r"The global (\w+)\(\) is deprecated\.", message), re.match(r"Use (\w+)\.$", fix)
        if m and f:
            return m.group(1), f.group(1), True
    return None


def _analyze(path: str, code: str, tmp: Path) -> Counter:
    """Error signatures of `code` from a local luau-analyze (environment-only 'Unknown global/type' dropped)."""
    import subprocess
    from .verify_ladder import _signature
    target = tmp / "block.luau"
    target.write_text(code, encoding="utf-8")
    flags = 0x4000 if os.name == "nt" else 0
    run = subprocess.run([path, str(target)], capture_output=True, text=True, timeout=30, creationflags=flags)
    counts: Counter = Counter()
    for line in (run.stdout + run.stderr).splitlines():
        m = re.search(r"\): (SyntaxError|TypeError): (.*)", line)
        if m and not m.group(2).startswith(("Unknown global", "Unknown type")):
            counts[_signature("compile", m.group(2))] += 1
    return counts


def seed(eval_files: list[Path], log_files: list[Path], analyzer: str | None = None) -> dict:
    """Mine stored answers and mistake logs; returns {rows, census, report}. No model call, no network."""
    from . import luau_lint, verify_ladder
    import tempfile
    blocks = _eval_blocks(eval_files)
    census: Counter = Counter()
    compile_census: Counter = Counter()
    rows, seen_pairs = [], set()
    tmp = Path(tempfile.mkdtemp(prefix="mm-"))
    stats = {"blocks": len(blocks), "blocks_failing_answers": sum(1 for b in blocks if b["status"] == "fail"),
             "verified_pairs": 0, "pairs_rejected": 0}
    for block in blocks:
        code = block["code"]
        try:
            findings = luau_lint.lint(code, safety_checks=True, server_security=True, roblox_rules=True)
        except Exception:
            continue
        before_keys = Counter((f.rule_id, f.message) for f in findings)
        for f in findings:
            census["lint:" + f.rule_id + ":" + re.sub(r"\d+", "N", f.message)[:60]] += 1
        base = _analyze(analyzer, code, tmp) if analyzer else Counter()
        compile_census.update(base)
        lines = code.splitlines()
        for finding in findings:
            rename = _rename(finding)
            if not rename or not 1 <= finding.line <= len(lines):
                continue
            old, new, is_global = rename
            line = lines[finding.line - 1]
            if is_global is None:
                pattern = rf"(?<![\w.:])game\.{re.escape(old)}(?!\w)"
            else:
                pattern = rf"(?<![\w.:]){re.escape(old)}(?=\s*\()" if is_global else rf"(?<=:){re.escape(old)}(?=\s*\()"
            after_line = re.sub(pattern, new.replace("\\", "\\\\"), line)
            if after_line == line:
                continue
            fixed = "\n".join(lines[:finding.line - 1] + [after_line] + lines[finding.line:]) + ("\n" if code.endswith("\n") else "")
            after = Counter((f.rule_id, f.message) for f in luau_lint.lint(
                fixed, safety_checks=True, server_security=True, roblox_rules=True))
            ok = (after[(finding.rule_id, finding.message)] < before_keys[(finding.rule_id, finding.message)]
                  and not (set(after) - set(before_keys)))
            if ok and analyzer:
                ok = not (_analyze(analyzer, fixed, tmp) - base)
            key = (finding.rule_id, finding.message, line.strip(), block["src"].split("#")[0])
            if not ok:
                stats["pairs_rejected"] += 1
                continue
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            stats["verified_pairs"] += 1
            rows.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rung": "lint",
                         "signature": "lint:" + finding.rule_id, "message": finding.message,
                         "diff": f"-{line}\n+{after_line}", "verified": True, "by": "seed", "src": block["src"],
                         "apis": old})
    for path in log_files:
        for row in read_rows(path):
            census[row["signature"]] += 1
            if row.get("verified") is True and row.get("diff"):
                rows.append({**row, "by": row.get("by") or "log", "src": path.parent.name})
    stats["analyzer"] = bool(analyzer)
    for row in rows:
        for key in ("diff", "message"):
            row[key] = verify_ladder.scrub(row[key])
    return {"rows": rows, "lint_and_log_signatures": census, "compile_signatures": compile_census, "stats": stats}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import glob
    import sys
    parser = argparse.ArgumentParser(prog="python -m star.mistake_memory", description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="mine stored answers + mistake logs, write seed rows and validated fixers")
    s.add_argument("--evals", nargs="*", default=[], help="eval result json globs (work/eval-runs/**/*.json)")
    s.add_argument("--logs", nargs="*", default=[], help="mistakes.jsonl files")
    s.add_argument("--analyzer", default=os.environ.get("STAR_LUAU_ANALYZE"), help="local luau-analyze binary (optional)")
    s.add_argument("--out", default=str(DATA), help="directory for seed.jsonl and fixers.json")
    s.add_argument("--extra-guard", nargs="*", default=[], help="eval result json globs whose PASSING answers also guard")
    r = sub.add_parser("synthesize", help="learn fixers from the user's mistake log (+ seed rows)")
    r.add_argument("--out", default="", help="fixers file (default: the app's own)")
    args = parser.parse_args(argv)
    if args.cmd == "seed":
        files = sorted({Path(p) for g in args.evals for p in glob.glob(g, recursive=True)})
        result = seed(files, [Path(p) for g in args.logs for p in glob.glob(g, recursive=True)], args.analyzer)
        guard = guard_blocks()
        extra = []
        for path in sorted({Path(p) for g in args.extra_guard for p in glob.glob(g, recursive=True)}):
            for block in _eval_blocks([path]):
                if block["status"] == "pass":
                    extra.append((block["src"], "```luau\n" + block["code"] + "\n```"))
        guard_all = guard
        fixers, rejected = synthesize(result["rows"], guard_all)
        for fixer in fixers:      # informational: passing stored answers a fixer would still touch (not a blocker)
            fixer["validation"]["passing_eval_answers"] = len(extra)
            fixer["validation"]["passing_eval_answers_changed"] = sum(
                1 for _, text in extra
                if (m := _FENCE.search(text)) and apply_one(m.group(1), fixer) != m.group(1))
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        with (out / "seed.jsonl").open("w", encoding="utf-8") as handle:
            kept: Counter = Counter()
            per_task: Counter = Counter()
            for row in result["rows"]:                # one row per task first, so the cap keeps the most varied ones
                per_task[(row["signature"], _task_key(row))] += 1
                row["_n"] = per_task[(row["signature"], _task_key(row))]
            for row in sorted(result["rows"], key=lambda r: r.pop("_n")):            # at most SEED_PER_SIGNATURE rows each keep the shipped file small
                if kept[row["signature"]] < SEED_PER_SIGNATURE:
                    kept[row["signature"]] += 1
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        save_fixers(fixers, out / "fixers.json")
        report = {"stats": result["stats"], "signatures_total": len(result["lint_and_log_signatures"]) + len(result["compile_signatures"]),
                  "lint_and_log_signatures": result["lint_and_log_signatures"].most_common(40),
                  "compile_signatures": result["compile_signatures"].most_common(15),
                  "seed_rows": len(result["rows"]), "guard_blocks": len(guard_all),
                  "fixers": [{"id": f["id"], "signature": f["signature"], "pattern": f["pattern"],
                              "replacement": f["replacement"], "validation": f["validation"]} for f in fixers],
                  "rejected": rejected}
        json.dump(report, sys.stdout, indent=1)
        print()
        return 0
    rows = memory_rows()
    fixers, rejected = synthesize(rows, guard_blocks())
    target = Path(args.out) if args.out else fixers_path()
    keep = {f["id"]: f for f in load_fixers(target)}
    keep.update({f["id"]: f for f in fixers})
    save_fixers(list(keep.values()), target)
    print(json.dumps({"fixers": [f["id"] for f in fixers], "rejected": rejected}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
