"""Litha's map of herself: what she can do, how she is started, which gates guard each step, and how well each
lane really works.

Built from her own code (`ast`, nothing is imported or run), the scheduled .cmd scripts, docs/LITHA_AUTONOMY.md and
her logs (`fixes.jsonl` via litha.self_plan, `bench.jsonl`). The code part is cached per tree hash (a hash of the
files it reads) in `~/.star/litha/self_map/<hash>.json`; the measured part is redone when the logs change. The text
summary fits SUMMARY_TOKENS (her model's window is 4096 tokens).

    python -m litha.self_map [--json] [--home DIR]       prints the summary; writes ~/.star/litha/self_map.{json,txt}

`note(lane, room)` is the one short line a prompt may carry (her measured weak spot in that lane); it is "" unless
LITHA_SELF_NOTE=1 and the line fits the room left in the prompt (see docs/LITHA_AUTONOMY.md 4k for why it is off).
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from litha import self_plan

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home() / ".star"
SUMMARY_TOKENS = 1500
WINDOW = 4096                        # her model's context (prompt + answer)
CHARS_PER_TOKEN = 3.5                # the estimate pr_fixer uses for its window checks
NOTE_CHARS = 280                     # a prompt note is at most this long (~80 tokens)
VERSION = 1                          # bump when the code map's shape changes (old cache entries are ignored)


def tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def sources(root: Path) -> list[Path]:
    lit = root / "litha"
    files = sorted(lit.glob("*.py")) + sorted(lit.glob("*.cmd")) + [lit / "repos.json",
                                                                   root / "docs" / "LITHA_AUTONOMY.md"]
    return [f for f in files if f.is_file()]


def tree_hash(root: Path = ROOT) -> str:
    """Hash of every file the map is made of (line endings normalised: a CRLF checkout is the same tree)."""
    h = hashlib.sha1(f"v{VERSION}".encode())
    for f in sources(root):
        h.update(f.relative_to(root).as_posix().encode() + b"\0")
        h.update(f.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()[:16]


def _text(node: ast.AST) -> str | None:
    """The text of a string expression: f-string holes become {}, `a + b` is joined; None when it is not a string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "{}" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _text(node.left), _text(node.right)
        return a + b if a is not None and b is not None else (a or b)
    return None


def _short(s: str, n: int = 64) -> str:
    s = re.sub(r"\s+", " ", s).strip(" :;.")
    s = re.sub(r"^(\{\}[: ]*)+", "", s).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "~"


def _refusals(fn: ast.AST) -> list[str]:
    """What a function says when it stops something: why/problems/reasons.append(str), {"result": failed|skip, "why":
    str}, `return None/False, str`, raise X(str)."""
    out: list[str] = []
    for n in ast.walk(fn):
        s = None
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append" \
                and isinstance(n.func.value, ast.Name) and n.func.value.id in ("why", "problems", "reasons") and n.args:
            s = _text(n.args[0])
        elif isinstance(n, ast.Dict):
            keys = [k.value if isinstance(k, ast.Constant) else None for k in n.keys]
            if "why" in keys and "result" in keys:
                res = n.values[keys.index("result")]
                if isinstance(res, ast.Constant) and res.value in ("failed", "skip", "error"):
                    s = _text(n.values[keys.index("why")])
        elif isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple) and len(n.value.elts) >= 2:
            first = n.value.elts[0]
            if isinstance(first, ast.Constant) and first.value in (None, False):
                s = next((t for t in map(_text, n.value.elts[1:]) if t), None)
        elif isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) and n.exc.args:
            s = _text(n.exc.args[0])
        if s and len(_short(s)) >= 4 and _short(s) not in out:
            out.append(_short(s))
    return out


def _home_path(node: ast.AST) -> str | None:
    """`Path.home() / ".star" / "x" / "y"` -> "~/.star/x/y"."""
    parts = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        t = _text(node.right)
        if t is None:
            return None
        parts.append(t)
        node = node.left
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "home" and parts:
        return "~/" + "/".join(reversed(parts))
    return None


def scan_module(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    doc = ast.get_docstring(tree) or ""
    m: dict = {"doc": _short(doc.split("\n\n")[0], 200), "usage": [], "flags": [], "functions": [], "limits": {},
               "patterns": [], "state": [], "uses": [], "refusals": {}}
    m["usage"] = [_short(ln, 120) for ln in doc.splitlines() if ln.strip().startswith("python -m litha.")]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            m["functions"].append(node.name)
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            names += [e.id for t in node.targets if isinstance(t, ast.Tuple) for e in t.elts if isinstance(e, ast.Name)]
            values = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
            for name, v in zip(names, values if len(values) == len(names) else [node.value] * len(names)):
                if not name.isupper():
                    continue
                if isinstance(v, ast.Constant) and isinstance(v.value, (int, float)) and not isinstance(v.value, bool):
                    m["limits"][name] = v.value
                elif isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "compile":
                    m["patterns"].append(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
            flag = next((a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)), None)
            if flag:
                m["flags"].append(flag)
        elif isinstance(node, ast.BinOp):
            p = _home_path(node)
            if p and p.startswith("~/.star/") and p not in m["state"] and not any(s.startswith(p + "/") for s in m["state"]):
                m["state"] = [s for s in m["state"] if not p.startswith(s + "/")] + [p]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            names = [a.name for a in node.names]
            for dep in ([mod.split(".")[1]] if mod.startswith("litha.") else names if mod == "litha" else []):
                if dep not in m["uses"] and dep != path.stem:
                    m["uses"].append(dep)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            r = _refusals(node)
            if r:
                m["refusals"][node.name] = r
    return m


SCHEDULE = re.compile(r"-m (litha\.\w+)([^>\r\n]*)")
TASKS = {"pr_merger_run.cmd": 'task "Litha PR merger", every 10 min', "bug_bench_run.cmd": 'task "Litha bug bench", 03:10'}


def scan_schedule(root: Path) -> list[dict]:
    out = []
    for f in sorted((root / "litha").glob("*.cmd")):
        text = f.read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if not ln.strip().lower().startswith(("rem", "::"))]
        steps = [(m.group(1) + " " + m.group(2).replace('--python "%~1"', "").strip()).strip()
                 for ln in lines for m in SCHEDULE.finditer(ln)]
        off = re.findall(r"if exist \"([^\"]+OFF)\"", text)
        out.append({"script": f.name, "when": TASKS.get(f.name, ""), "steps": steps,
                    "off": [o.replace("%USERPROFILE%\\", "~/").replace("\\", "/") for o in off]})
    return out


def scan_docs(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"sections": [], "open": []}
    sections = [ln[3:].strip() for ln in text.splitlines() if ln.startswith("## ")]
    open_items = []
    todo = re.search(r"^## 4\. .*?(?=^## )", text, re.M | re.S)
    for m in re.finditer(r"^\d+\. \*\*(.+?)\*\*(.*)$", todo.group(0) if todo else "", re.M):
        if "DONE" not in m.group(2)[:80]:
            open_items.append(_short(m.group(1), 60))
    return {"sections": [_short(s, 70) for s in sections], "open": open_items}


def code_map(root: Path = ROOT, home: Path | None = None, use_cache: bool = True) -> dict:
    """The part of the map that depends only on the files: cached per tree hash."""
    h = tree_hash(root)
    cache = (home or HOME) / "litha" / "self_map" / f"{h}.json"
    if use_cache:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    modules = {}
    for f in sorted((root / "litha").glob("*.py")):
        if f.name == "__init__.py":
            continue
        try:
            modules[f.stem] = scan_module(f)
        except (SyntaxError, UnicodeDecodeError, OSError) as e:
            modules[f.stem] = {"error": str(e)[:200]}
    m = {"tree": h, "modules": modules, "schedule": scan_schedule(root),
         "docs": scan_docs(root / "docs" / "LITHA_AUTONOMY.md")}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        _write(cache, json.dumps(m))
    except OSError:
        pass
    return m


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def bench(home: Path) -> dict:
    """The newest bench row per mode (fix with diff / blind / hunt / hunt survivors)."""
    latest: dict[str, dict] = {}
    for r in self_plan.read_jsonl(home / "litha" / "bench.jsonl"):
        mode = r.get("mode") or ("blind" if r.get("blind") else "fix")
        if r.get("survivors"):
            mode += "-survivors"
        latest[mode] = {"at": str(r.get("at", ""))[:10], "n": r.get("n"),
                        "ok": r.get("caught") if "caught" in r else r.get("solved"), "seconds": r.get("seconds")}
    return latest


def build(root: Path = ROOT, home: Path | None = None, use_cache: bool = True) -> dict:
    home = home or HOME
    m = code_map(root, home, use_cache)
    plan = self_plan.plan(home, top=5)
    m.update(built=round(time.time()), lanes=plan["lanes"], claims=plan["claims"], bench=bench(home),
             weak=[{k: e[k] for k in ("bucket", "lane", "count", "score", "prs", "cause", "quiet")}
                   for e in plan["next_steps"]], rows=plan["rows"], days=plan["days"])
    return m


# the steps whose gates the summary lists (module, function), in pipeline order
STEPS = [("pr_fixer", "apply_edits"), ("pr_fixer", "fix"), ("pr_fixer", "resolve_text"), ("pr_fixer", "resolve"),
         ("rust_fix", "repair"), ("pr_merger", "list_gates"), ("pr_merger", "check_gates"),
         ("pr_merger", "diff_gates"), ("pr_merger", "confirmed"), ("bug_proof", "prove"),
         ("pr_promote", "missing")]


def summary(m: dict, budget: int = SUMMARY_TOKENS) -> str:
    """The map as compact text for her prompt; lines are dropped from the least useful end until it fits."""
    mods = m.get("modules", {})
    head = [f"LITHA SELF-MAP (tree {m.get('tree', '?')}, {time.strftime('%Y-%m-%d', time.localtime(m.get('built') or time.time()))})"]
    sched = []
    for s in m.get("schedule", []):
        sched.append(f"{s['script']} ({s['when'] or 'manual'}): " + "; ".join(s["steps"]) +
                     (f". off: {', '.join(s['off'])}" if s.get("off") else ""))
    measured = [f"Measured, last {m.get('days', 7):g} days ({m.get('rows', 0)} rows): lane tries fixed/failed/refused/"
                "rerun/noop/error, top reasons"]
    for lane, s in sorted(m.get("lanes", {}).items(), key=lambda kv: -kv[1]["n"]):
        why = ", ".join(f"{b} {n}" for b, n in list(s["why"].items())[:3])
        measured.append(f"- {lane}: {s['n']} {s['fixed']}/{s['failed']}/{s['refused']}/{s['rerun']}/{s['noop']}/"
                        f"{s['error']}" + (f"; {why}" if why else ""))
    c = m.get("claims") or {}
    if c.get("heads"):
        measured.append(f"- review high risks over {c['heads']} PR heads: {c['high']} stood, {c['refuted']} refuted, "
                        f"{c['unproven']} unproven")
    b = m.get("bench") or {}
    if b:
        measured.append("- bench: " + "; ".join(f"{k} {v['ok']}/{v['n']} ({v['at']})" for k, v in b.items()))
    weak = ["Weak spots (litha.self_plan, ranked count x fixability):"] + [
        f"{i}. {w['bucket']} [{w['lane']}] x{w['count']} {', '.join(w['prs'][:3])}{' (quiet since)' if w.get('quiet') else ''}: "
        f"{_short(w['cause'], 110)}" for i, w in enumerate(m.get("weak", []), 1)]
    modules = ["Modules (entry, flags, limits):"]
    for name, mod in mods.items():
        if "error" in mod:
            modules.append(f"- {name}: does not parse: {mod['error'][:80]}")
            continue
        flags = " ".join(f for f in mod["flags"] if f.startswith("-") or f in ("cmd",))
        limits = " ".join(f"{k}={v}" for k, v in list(mod["limits"].items())[:6])
        modules.append(f"- {name}: {_short(mod['doc'], 90)}" + (f" | {flags}" if flags else "") +
                       (f" | {limits}" if limits else ""))
    gates = ["Gates (what each step refuses):"]
    for mod, fn in STEPS:
        r = mods.get(mod, {}).get("refusals", {}).get(fn)
        if r:
            gates.append(f"- {mod}.{fn}: " + "; ".join(_short(x, 48) for x in r[:5]))
    state = sorted({p for mod in mods.values() for p in mod.get("state", [])})
    docs = m.get("docs", {})
    tail = ["State: " + ", ".join(state)] if state else []
    if docs.get("open"):
        tail.append("Open (docs section 4): " + "; ".join(docs["open"]))
    # priority: what she is and how she runs, then how well, then where weak, then the gates, then the rest
    blocks = [head + ["Schedule:"] + sched, measured, weak, modules, gates, tail]
    lines = [ln for blk in blocks for ln in blk]
    while lines and tokens("\n".join(lines)) > budget:
        lines.pop(_drop_index(lines))
    return "\n".join(lines)


def _drop_index(lines: list[str]) -> int:
    """Which line goes first when the summary is over budget: the last line of the lowest-priority block left."""
    for prefix in ("Open (docs", "State: ", "- ", ):
        idx = [i for i, ln in enumerate(lines) if ln.startswith(prefix)]
        if prefix == "- ":
            gates = next((i for i, ln in enumerate(lines) if ln.startswith("Gates")), None)
            idx = [i for i in idx if gates is not None and i > gates]
        if idx:
            return idx[-1]
    return len(lines) - 1


def note(lane: str, room_tokens: float, home: Path | None = None) -> str:
    """One measured line about her weak spot in this lane for a prompt, or "" (off, nothing known, or no room).
    Off unless LITHA_SELF_NOTE=1: whether it helps her answers is not measured yet (docs section 4k)."""
    if os.environ.get("LITHA_SELF_NOTE") != "1":
        return ""
    steps = self_plan.load(home).get("next_steps") or []
    adv = next((e["advice"] for e in steps if e.get("lane") == lane and e.get("advice") and not e.get("quiet")), "")
    text = f"\n{adv[:NOTE_CHARS]}\n" if adv else ""
    return text if text and tokens(text) <= room_tokens else ""


def fitted(lane: str, build, answer_tokens: float, window: int = WINDOW, home: Path | None = None,
           task: dict | None = None) -> str:
    """build(note) -> prompt. The prompt with her note for this lane when it is on and fits the window with the
    answer, then the lessons of her experience memory that fit what is left (task = {"repo", "paths", "text"}: only
    when the lane's lessons are on and something relevant is known); otherwise exactly build("") (the prompt as it
    was)."""
    base = build("")
    extra = note(lane, window - answer_tokens - tokens(base), home)
    if task is not None:
        from litha import experience
        room = window - answer_tokens - tokens(build(extra) if extra else base)
        extra += experience.note({**task, "lane": lane}, room)
    return build(extra) if extra else base


def write_outputs(m: dict, home: Path | None = None) -> tuple[Path, Path]:
    d = (home or HOME) / "litha"
    d.mkdir(parents=True, exist_ok=True)
    _write(d / "self_map.json", json.dumps(m, indent=1))
    _write(d / "self_map.txt", summary(m))
    return d / "self_map.json", d / "self_map.txt"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.self_map")
    ap.add_argument("--json", action="store_true", help="print the full map instead of the summary")
    ap.add_argument("--home", type=Path, help="state root (default ~/.star)")
    ap.add_argument("--no-cache", action="store_true", help="rebuild the code map even if the tree is cached")
    a = ap.parse_args(argv)
    t = time.time()
    m = build(ROOT, a.home, not a.no_cache)
    write_outputs(m, a.home)
    text = json.dumps(m, indent=1) if a.json else summary(m)
    print(text)
    print(f"[self_map tree {m['tree']}: summary ~{tokens(summary(m))} tokens, {time.time() - t:.2f} s]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
