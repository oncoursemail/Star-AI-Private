"""Regression items and their checkable graders (no judge model).

An item (one JSON line):
  {"id", "set", "messages": [{role, content}, ...], "expect": "code|general|safety",
   "grader": {"code": bool, "verify": "luau"|null, "must": [regex...], "any": [regex...], "must_not": [regex...]},
   "cluster"?: cause it came from}
`expect` is the route the turn should get (route.py, offline); the grader checks the answer (gate.py, live).
Items made from live flaw samples (clusters_to_items) only use graders that need no human answer key: a code block,
the verifier, and the general-note leak phrases; the hand-written sets in evals/flaws/ add item-specific regexes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LEAK = [r"(?i)outside (of )?my (expertise|area)", r"(?i)not a game-building", r"(?i)general question"]
LUAU_HINT = re.compile(r"```(?:lua|luau)\b|\blocal \w+ *=|game:GetService|:Connect\(", re.I)


def load(path: str | Path) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def save(path: str | Path, items: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")


def grade(item: dict, answer: str, verify=None) -> tuple[bool, list[str]]:
    """(pass, reasons it failed). `verify(answer) -> {"ok": bool, ...} | None` is called only when the grader asks
    for it and the answer has code; None (verifier down) counts as not checked, not as a failure."""
    g = item.get("grader") or {}
    why = []
    text = answer or ""
    if not text.strip():
        return False, ["empty answer"]
    if g.get("code") and "```" not in text:
        why.append("no code block")
    if text.count("```") % 2:
        why.append("unclosed code block (cut answer)")
    for rx in g.get("must") or []:
        if not re.search(rx, text):
            why.append(f"missing {rx}")
    anys = g.get("any") or []
    if anys and not any(re.search(rx, text) for rx in anys):
        why.append("none of " + " | ".join(anys))
    for rx in g.get("must_not") or []:
        if re.search(rx, text):
            why.append(f"has {rx}")
    if g.get("verify") == "luau" and verify is not None and "```" in text:
        res = verify(text)
        if res is not None and not res.get("ok", True):
            names = [p.get("name") or p.get("kind") for b in res.get("blocks") or [] for p in b.get("problems") or []
                     if p.get("severity") == "error"]
            if names or res.get("needs_fix"):
                why.append("verifier: " + ", ".join(map(str, names[:3])))
    return not why, why


EXPECT_FOR = {"game-build": "code", "code-followup": "code", "soft-safety": "code", "reask-note": "code",
              "safety-substring": "general"}


def clusters_to_items(samples: list[dict], per_cluster: int = 12) -> list[dict]:
    """Live flaw samples -> regression items, grouped by the fix rule that matched (the cluster). The grader needs no
    answer key: a coding turn must get code (verified if Luau) and never the general-note phrases; a safety-substring
    turn must just not leak them. Samples with identical last turns are one item."""
    seen, out, per = set(), [], {}
    for s in samples:
        msgs = s.get("msgs") or []
        if not msgs or msgs[-1].get("role") != "user":
            continue
        for cause in s.get("can") or []:
            key = (cause, re.sub(r"\W+", " ", msgs[-1]["content"].lower()).strip())
            if key in seen or per.get(cause, 0) >= per_cluster:
                continue
            seen.add(key)
            per[cause] = per.get(cause, 0) + 1
            expect = EXPECT_FOR.get(cause, "code")
            code_ctx = any(m.get("role") == "assistant" and "```" in m.get("content", "") for m in msgs[:-1])
            grader = {"must_not": LEAK}
            if expect == "code" and (code_ctx or cause in ("game-build", "reask-note")):
                grader["code"] = True
                if any(LUAU_HINT.search(m.get("content", "")) for m in msgs[:-1]) or cause == "game-build":
                    grader["verify"] = "luau"
            out.append({"id": f"live-{cause}-{s.get('id')}", "set": "live", "cluster": cause, "messages": msgs,
                        "expect": expect, "grader": grader})
    return out
