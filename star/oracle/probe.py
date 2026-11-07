"""L2 likelihood probe pairs: verified GOOD answers and automatically planted BAD twins.

GOOD = an answer that passed every automated check (a gold-bank item, or an eval answer whose task passed). BAD = the
same answer with ONE planted defect, so a model that "knows" Luau and the Roblox API should give the GOOD text a higher
log-probability than its twin. Defect kinds (each applied to the first Luau block it fits, deterministically):

* off_by_one         numeric loop bound shortened (`for i = 1, #t do` -> `#t - 1`), or `<=` -> `<`
* wrong_comparison   `==` <-> `~=` or `<` <-> `>` inside an `if`/`while` condition
* missing_nil_check  a one-line guard (`if not x then return end`, `if x == nil ...`) removed, or `x and x.Y` -> `x.Y`
* server_trust       in an OnServerEvent/OnServerInvoke answer, the argument-validation guard lines removed
* invented_api       a real method swapped for a documented confusion (data/roblox_api_confusions.json, e.g.
                     `:FindFirstChild(` -> `:FindChild(`) or a near-miss that is no member of any class in the API dump
* slop               filler prose and an unverified "I tested this" claim added around the unchanged code (checked:
                     star.slop must score the twin higher than the original)

Pure text work: no model, no network. The corpus file is JSONL, one row per GOOD answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re

KINDS = ("off_by_one", "wrong_comparison", "missing_nil_check", "server_trust", "invented_api", "slop")
CORRECTNESS_KINDS = KINDS[:5]   # what the pass rate is about; "slop" is reported on its own
_FENCE = re.compile(r"(```[ \t]*(?:luau|lua)?[ \t]*\n)(.*?)(\n[ \t]*```)", re.S)
_LOOP_LEN = re.compile(r"(\bfor\s+\w+\s*=\s*[^,\n]+,\s*)(#[\w.\[\]\"']+|[\w.]+)(\s+do\b)")
_COND_LINE = re.compile(r"^(\s*(?:if|elseif|while)\b)(.*?)(\b(?:then|do)\b.*)$", re.M)
_GUARD_ONE_LINE = re.compile(
    r"^[ \t]*if\s+(?:not\s+[\w.:\[\]\"'()]+|[\w.:\[\]\"'()]+\s*==\s*nil)\s+then\s+return\b[^\n]*\bend[ \t]*\n", re.M)
_AND_GUARD = re.compile(r"\b(if\s+)([A-Za-z_]\w*)\s+and\s+\2([.:])")
_REMOTE = re.compile(r"\bOn(?:Server|Client)?(?:Event|Invoke)\b|OnServerEvent|OnServerInvoke")
_VALIDATION = re.compile(r"\btypeof\s*\(|\btype\s*\(|\bIsA\s*\(|\btonumber\s*\(|math\.clamp|\bfinite\b|~=\s*\w|[<>]=?")
_METHOD_CALL = re.compile(r":([A-Z][A-Za-z0-9]*)\(")

SLOP_OPEN = ("Certainly! Here's a robust, comprehensive and elegant solution that leverages best practices "
             "to seamlessly handle everything you need.\n\n")
SLOP_CLOSE = ("\n\nI've tested this and it works perfectly in every case. It's worth noting that this approach is "
              "generally speaking the most scalable option. I hope this helps! Let me know if you have any other "
              "questions.")


@dataclass
class Pair:
    id: str
    source: str              # "gold:<id>" or "eval:<suite>:<task>"
    prompt: str              # the user's request (without any context blocks)
    good: str
    bads: list[dict] = field(default_factory=list)   # [{"kind": ..., "text": ...}]

    def to_dict(self) -> dict:
        return {"id": self.id, "source": self.source, "prompt": self.prompt, "good": self.good, "bads": self.bads}


def _first_block(text: str):
    for match in _FENCE.finditer(text):
        if match.group(2).strip():
            return match
    return None


def _swap_block(text: str, match: re.Match, code: str) -> str:
    return text[:match.start(2)] + code + text[match.end(2):]


def off_by_one(code: str) -> str | None:
    m = _LOOP_LEN.search(code)
    if m and not m.group(2).isdigit():
        return code[:m.start(2)] + m.group(2) + " - 1" + code[m.end(2):]
    for cm in _COND_LINE.finditer(code):
        cond = cm.group(2)
        sub = (cond.replace("<=", "<", 1) if "<=" in cond else cond.replace(">=", ">", 1) if ">=" in cond
               else None)
        if sub is not None:
            return code[:cm.start(2)] + sub + code[cm.end(2):]
    return None


def wrong_comparison(code: str) -> str | None:
    for cm in _COND_LINE.finditer(code):
        cond = cm.group(2)
        for a, b in (("==", "~="), ("~=", "=="), (" < ", " > "), (" > ", " < ")):
            if a in cond:
                return code[:cm.start(2)] + cond.replace(a, b, 1) + code[cm.end(2):]
    return None


def missing_nil_check(code: str) -> str | None:
    m = _GUARD_ONE_LINE.search(code)
    if m:
        return code[:m.start()] + code[m.end():]
    m = _AND_GUARD.search(code)
    if m:
        return code[:m.start()] + m.group(1) + m.group(2) + m.group(3) + code[m.end():]
    return None


_GUARD_BLOCK = re.compile(r"^[ \t]*if\b([^\n]*)\bthen[ \t]*(?:\n[ \t]*(?:--[^\n]*\n[ \t]*)?return\b[^\n]*\n[ \t]*end"
                          r"|[ \t]+return\b[^\n]*\bend)[ \t]*\n", re.M)


def server_trust(code: str) -> str | None:
    """Drop the argument-validation guards (one-line or three-line `if ... then return end`) after the remote hook."""
    at = re.search(r"OnServerEvent|OnServerInvoke", code)
    if not at:
        return None
    head, tail = code[:at.end()], code[at.end():]
    guards = [m for m in _GUARD_BLOCK.finditer(tail) if _VALIDATION.search(m.group(1))]
    if not guards:
        return None
    for m in reversed(guards):
        tail = tail[:m.start()] + tail[m.end():]
    return head + tail


def _all_members(dump) -> frozenset[str]:
    names: set[str] = set()
    for info in dump.classes.values():
        names.update(info.members)
    return frozenset(names)


def invented_api(code: str, dump, confusions) -> str | None:
    """Swap one real method for a documented confusion, else for a near-miss that no class has."""
    for entry in confusions:
        right, wrong = entry["right"], entry["wrong"]
        if right in code:
            return code.replace(right, wrong, 1)
    if dump is None:
        return None
    members = _all_members(dump)
    for m in _METHOD_CALL.finditer(code):
        name = m.group(1)
        if name not in members:
            continue
        for fake in (name[:-5] if name.endswith("Async") else name + "Async", "Get" + name, name + "s"):
            if fake and fake not in members:
                return code[:m.start(1)] + fake + code[m.end(1):]
    return None


def slop_variant(text: str) -> str:
    return SLOP_OPEN + text.strip() + SLOP_CLOSE


def make_bads(good: str, *, dump=None, confusions=(), slop_score=None) -> list[dict]:
    """Every defect kind that fits this answer, at most one twin per kind, in KINDS order."""
    out = []
    block = _first_block(good)
    if block is not None:
        code = block.group(2)
        for kind, fn in (("off_by_one", off_by_one), ("wrong_comparison", wrong_comparison),
                         ("missing_nil_check", missing_nil_check), ("server_trust", server_trust)):
            bad = fn(code)
            if bad is not None and bad != code:
                out.append({"kind": kind, "text": _swap_block(good, block, bad)})
        bad = invented_api(code, dump, confusions)
        if bad is not None and bad != code:
            out.append({"kind": "invented_api", "text": _swap_block(good, block, bad)})
    twin = slop_variant(good)
    if slop_score is None or slop_score(twin) > slop_score(good):
        out.append({"kind": "slop", "text": twin})
    return out


def _pair_id(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def gold_sources(path: Path) -> list[tuple[str, str, str]]:
    """(source, prompt, answer) from the gold bank JSONL."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows.append((f"gold:{row['id']}", row["request"], row["answer"]))
    return rows


def eval_sources(result_files, suite_dir: Path) -> list[tuple[str, str, str]]:
    """(source, prompt, model text) for every task that passed in any given result file; the first passing answer
    per task wins (files in the given order). Holdout suites are refused: the probe never reads them."""
    from ..eval_checks import split_answer
    prompts: dict[tuple[str, str], str] = {}
    chosen: dict[tuple[str, str], str] = {}
    for path in result_files:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        suite_file = data.get("suite", {}).get("file", "")
        if "holdout" in suite_file.lower() or "holdout" in str(path).lower():
            raise ValueError(f"{path}: holdout results are never used for probes")
        suite = Path(suite_dir) / suite_file
        if suite_file and (suite_file, "") not in prompts and suite.is_file():
            prompts[(suite_file, "")] = "loaded"
            raw = json.loads(suite.read_text(encoding="utf-8"))
            for task in raw if isinstance(raw, list) else raw.get("tasks", []):
                prompts[(suite_file, task["id"])] = task.get("prompt", "")
        for tid, rec in sorted(data.get("tasks", {}).items()):
            key = (suite_file, tid)
            if rec.get("status") == "pass" and rec.get("answer") and key not in chosen and prompts.get(key):
                chosen[key] = split_answer(rec["answer"])[0].strip()
    stem = lambda name: Path(name).stem
    return [(f"eval:{stem(s)}:{t}", prompts[(s, t)], text) for (s, t), text in sorted(chosen.items())]


def build(sources, *, dump=None, confusions=(), slop_score=None, max_answer_chars: int = 6000,
          need_bug: bool = True) -> list[Pair]:
    """Pairs for every source whose answer has a Luau block and (with need_bug) at least one bug-kind twin."""
    pairs = []
    for source, prompt, answer in sources:
        if not answer or len(answer) > max_answer_chars or _first_block(answer) is None:
            continue
        bads = make_bads(answer, dump=dump, confusions=confusions, slop_score=slop_score)
        if need_bug and not any(b["kind"] != "slop" for b in bads):
            continue
        pairs.append(Pair(_pair_id(source), source, prompt, answer, bads))
    return pairs


def write(pairs: list[Pair], path: Path) -> None:
    Path(path).write_text("".join(json.dumps(p.to_dict(), ensure_ascii=False) + "\n" for p in pairs),
                          encoding="utf-8")


def read(path: Path) -> list[Pair]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out.append(Pair(row["id"], row["source"], row["prompt"], row["good"], row["bads"]))
    return out


def spread(pairs: list[Pair], n: int) -> list[Pair]:
    """n pairs spread round-robin over gold families (gb-<family>-...), each family in a fixed hashed order."""
    groups: dict[str, list[Pair]] = {}
    for p in sorted(pairs, key=lambda p: hashlib.sha256(p.source.encode("utf-8")).hexdigest()):
        family = p.source.split(":", 1)[-1].split("-")[1] if "-" in p.source else ""
        groups.setdefault(family, []).append(p)
    out: list[Pair] = []
    queues = [groups[k] for k in sorted(groups)]
    while len(out) < n and any(queues):
        for q in queues:
            if q and len(out) < n:
                out.append(q.pop(0))
    return out
