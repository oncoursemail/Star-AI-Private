"""Flaw miner: the router's decision log (journal lines `mesh {...}`) -> failure clusters by cause, with counts.

Causes (measured, never guessed):
  capacity  no first token within N s | mesh busy (...) | HTTP NNN | no backend | client went away | stream cut
  answer    cut at max_tokens (finish_reason "length") | user re-asked / said it was wrong on the next turn
            ("reask"/"repeat" flag on the following turn of the same chat) | misrouted turn (a flaw-fix rule matched:
            game-build, code-followup, soft-safety, safety-substring) | reask in a coding chat
The report (no user text) goes to the self-model as {"kind": "eval", "suite": "flaws", "clusters": [...]}, so Litha
can answer "what are your weak spots" from measured counts.
"""
from __future__ import annotations

import collections
import json
import re
import subprocess

CAUSE_RULES = [
    (re.compile(r"no first token within (\d+) s"), lambda m: f"timeout: no first token within {m.group(1)} s"),
    (re.compile(r"mesh busy: ([\w' ]+?)(?: \(|$| and)"), lambda m: f"mesh busy: {m.group(1).strip()}"),
    (re.compile(r"HTTP (\d{3})"), lambda m: f"backend HTTP {m.group(1)}"),
    (re.compile(r"no backend"), lambda m: "no backend answered"),
    (re.compile(r"client went away"), lambda m: "client went away (closed early)"),
]
RULE_CAUSE = {
    "game-build": "misrouted: game-build ask without an engine word got the general-question note",
    "code-followup": "misrouted: follow-up in a coding chat got the general-question note",
    "soft-safety": "misrouted: coding question with a soft safety word got the general/safety note",
    "safety-substring": "misrouted: safety word inside another word got the safety card",
    "reask-note": "user said the code did not work (coding chat)",
}


def read_journal(since: str = "24 hours ago", unit: str = "star-mesh") -> list[str]:
    out = subprocess.run(["journalctl", "-u", unit, "-o", "cat", "--no-pager", "--since", since],
                         capture_output=True, text=True, timeout=120)
    return out.stdout.splitlines()


def parse(lines) -> list[dict]:
    rows = []
    for line in lines:
        i = line.find("mesh {")
        if i < 0:
            continue
        try:
            rows.append(json.loads(line[i + 5:]))
        except ValueError:
            continue
    return rows


def outcome_cause(row: dict) -> str | None:
    oc = str(row.get("outcome") or "")
    if row.get("cuts"):
        return "stream cut mid-answer (continued or failed)"
    if not oc or oc == "ok" or oc.startswith("cancelled"):
        return None
    for rx, name in CAUSE_RULES:
        m = rx.search(oc)
        if m:
            return name(m)
    return "failed: " + oc[:60]


def next_turn_reask(rows: list[dict], window_s: float = 900.0) -> dict[int, bool]:
    """index of a row -> whether the same chat's next turn (within window_s) re-asked or said it was wrong."""
    by_conv = collections.defaultdict(list)
    for i, r in enumerate(rows):
        if r.get("conv") and r.get("flaw"):
            by_conv[r["conv"]].append(i)
    out = {}
    for idx in by_conv.values():
        idx.sort(key=lambda i: rows[i].get("ts", 0))
        for a, b in zip(idx, idx[1:]):
            if rows[b].get("ts", 0) - rows[a].get("ts", 0) <= window_s:
                out[a] = bool({"reask", "repeat"} & set(rows[b]["flaw"].get("sig") or []))
    return out


def live(rows: list[dict], models=("litha",)) -> list[dict]:
    """Real traffic only: the gate's own A/B requests carry an X-Mesh-Fixes override and are left out."""
    return [r for r in rows if r.get("model") in models and not (r.get("flaw") or {}).get("override")]


def clusters(rows: list[dict], models=("litha",)) -> dict:
    rows = live(rows, models)
    total = len(rows)
    count = collections.Counter()
    group = {}
    for r in rows:
        c = outcome_cause(r)
        if c:
            count[c] += 1
            group[c] = "capacity"
        if r.get("finish") == "length":
            count["answer cut at max_tokens (finish_reason length)"] += 1
            group["answer cut at max_tokens (finish_reason length)"] = "answer"
        f = r.get("flaw") or {}
        for rule in (f.get("fire") or []) + (f.get("would") or []):
            name = RULE_CAUSE.get(rule, rule)
            if rule in (f.get("fire") or []):
                name += " (fix shipped, applied)"
            count[name] += 1
            group[name] = "answer"
    nxt = next_turn_reask(rows)
    reasked = [i for i, v in nxt.items() if v]
    if reasked:
        by_kind = collections.Counter((rows[i]["flaw"].get("kind"), "codectx" in (rows[i]["flaw"].get("sig") or []))
                                      for i in reasked)
        for (kind, code), n in by_kind.items():
            name = f"user re-asked or said it was wrong after a {'coding' if code else kind or '?'} answer"
            count[name] += n
            group[name] = "answer"
    with_flaw = sum(1 for r in rows if r.get("flaw"))
    out = [{"cause": c, "group": group[c], "count": n, "rate": round(n / total, 4) if total else 0.0}
           for c, n in count.most_common()]
    ts = [r.get("ts") for r in rows if r.get("ts")]
    return {"requests": total, "with_flaw_signals": with_flaw, "turns_followed": len(nxt), "reasked_next": len(reasked),
            "since": min(ts) if ts else None, "until": max(ts) if ts else None, "clusters": out}


def report(result: dict, top: int = 10) -> dict:
    """The self-model report (counts only, no user text)."""
    answer = [c for c in result["clusters"] if c["group"] == "answer"]
    return {"kind": "eval", "suite": "flaws", "score": sum(c["count"] for c in answer), "max": result["requests"],
            "requests": result["requests"], "since": result["since"], "until": result["until"],
            "clusters": result["clusters"][:top]}
