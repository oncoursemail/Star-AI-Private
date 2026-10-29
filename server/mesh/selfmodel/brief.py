"""Short plain-text facts about herself, from the live snapshot, for a model to answer from.

`wants_self(text)` says whether a user message asks about STAR/Litha herself (her GPU, servers, speed, code, learning);
it is deliberately narrow ("how do I use the GPU in Roblox" is not about her). `topic_of` picks which facts matter, and
`render` writes at most `max_chars` of lines that state measured values only.
"""
from __future__ import annotations

import re
import time

_WHO = r"(?:you|u|ya|litha|star|yourself)"
_HW = (r"(?:gpus?|graphics\s*cards?|video\s*cards?|cards?|machines?|computers?|pcs?|servers?|hardware|models?|cpus?"
       r"|cores?|vram|memory|ram|brain|nodes?)")
SELF_PATTERNS = [re.compile(p, re.I) for p in (
    rf"\b(?:what|which)\s+{_HW}\s+(?:are|is|r)\s+{_WHO}\b",
    rf"\b{_WHO}(?:'re|\s+are|\s+r)?\s+(?:running|hosted|living)\s+on\b",
    rf"\bhow\s+(?:are|r)\s+{_WHO}\s+(?:running|doing\s+technically|set\s*up|hosted)\b",
    rf"\bwhy\s+(?:are|r|is|were|was)\s+(?:{_WHO}|your\s+(?:answers?|replies?|responses?))\s+(?:so\s+|being\s+)?(?:slow|laggy|lagging|sluggish)",
    rf"\b(?:{_WHO})\s+(?:seem|feel|are|r)\s+(?:so\s+|really\s+)?(?:slow|laggy|fast)\b",
    rf"\byour\s+(?:own\s+)?(?:{_HW}|code|source|version|speed|tok(?:ens)?/s|training|learning|setup|specs?|infrastructure|uptime|errors?)\b",
    rf"\b(?:what|which)\s+(?:version|code|commit|build)\s+(?:are|is|r)\s+{_WHO}\b",
    rf"\bhow\s+(?:fast|quick|smart)\s+(?:are|r)\s+{_WHO}\b",
    rf"\b(?:are|r)\s+{_WHO}\s+(?:learning|training|improving|upgrading|tuning|getting\s+(?:better|faster|smarter))\b",
    rf"\bwhat\s+(?:changed|is\s+new|did\s+{_WHO}\s+(?:change|learn|improve))\s+(?:in|about|with)?\s*{_WHO}?\b.*\b(?:you|yourself|litha|star)\b",
    rf"\b(?:how\s+many|which)\s+(?:gpus?|cores?|servers?|machines?|nodes?)\s+(?:do|does)\s+{_WHO}\s+(?:have|use|run)\b",
    r"\bself[- ]?(?:model|status|check|report)\b",
)]
TOPICS = {
    "gpu": re.compile(r"\b(gpus?|graphics|card|vram|cuda|nvidia|rtx|hardware|machines?|pcs?|computers?|nodes?|cores?|cpus?|servers?|running on|hosted)\b", re.I),
    "speed": re.compile(r"\b(slow|lag|fast|quick|speed|tok|latency|wait|sluggish)\b", re.I),
    "code": re.compile(r"\b(code|version|commit|build|source|deployed|pr|prs|pull request|ci|bug|changed|update[sd]?)\b", re.I),
    "learning": re.compile(r"\b(learn\w*|train\w*|improv\w*|upgrad\w*|tun\w*|better|smarter|eval\w*|score\w*)\b", re.I),
}


def wants_self(text: str) -> bool:
    text = (text or "")[-1500:]
    return any(p.search(text) for p in SELF_PATTERNS)


def topic_of(text: str) -> str:
    hits = [t for t, rx in TOPICS.items() if rx.search(text or "")]
    return hits[0] if len(hits) == 1 else ("all" if not hits else ",".join(hits))


def _age(ts) -> str:
    if not isinstance(ts, (int, float)):
        return "?"
    s = max(0, time.time() - ts)
    return f"{int(s)} s ago" if s < 120 else f"{int(s / 60)} min ago" if s < 7200 else f"{int(s / 3600)} h ago"


def _node_line(n: dict) -> str:
    gpu = n.get("gpu") or "GPU ?"
    if n.get("state") == "idle":
        what = f"idle, serving Litha at {n.get('tok_s') or '?'} tok/s, {n.get('vram_free_mb')} MB VRAM free"
    elif n.get("state") == "busy":
        what = f"busy: {n.get('reason') or 'in use'}"
    elif n.get("state") == "off":
        what = f"off: {n.get('reason') or '-'}"
    else:
        what = f"{n.get('state')}: {n.get('reason') or '-'}"
    return f"{n.get('name')} ({gpu}): {what}"


def _brain_line(snap: dict) -> str:
    b = snap.get("brain") or {}
    machine = next((m for m in snap.get("machines") or [] if m.get("name") == b.get("name", "brain1")), {})
    cpu = machine.get("cpu") or "CPU server"
    loaded = [m for m in b.get("models") or [] if m.get("loaded")]
    models = ", ".join(f"{m['id']}" + (f" ({m['tok_s_avg']} tok/s avg)" if m.get("tok_s_avg") else "") for m in loaded) or "none loaded"
    busy = sum(int(m.get("processing") or 0) for m in loaded)
    load = b.get("host_load")
    return (f"{b.get('name', 'brain1')} ({cpu}, no GPU): {'healthy' if b.get('healthy') else 'NOT healthy'}; loaded: {models}; "
            f"answering {busy} request(s) now" + (f"; host load {load[0]:.1f}" if load else ""))


def render(snap: dict, topic: str = "all", backend: str | None = None, max_chars: int = 1100) -> str:
    if not snap:
        return "System facts: the self-model has no data yet (collector starting)."
    topics = set(topic.split(",")) if topic and topic != "all" else {"gpu", "speed", "code", "learning"}
    lines = [f"Live system facts about you (measured {_age(snap.get('ts'))}; answer from these, never invent numbers):"]
    nodes = {n["name"]: n for n in snap.get("nodes") or []}
    if backend:
        n = nodes.get(backend)
        if n:
            lines.append(f"- This reply is generated on {backend} ({n.get('gpu') or 'GPU'}), ~{n.get('tok_s') or '?'} tok/s.")
        elif backend.startswith("brain"):
            lines.append(f"- This reply is generated on {backend}, the CPU server (all GPU nodes busy/off or slower).")
    if topics & {"gpu", "speed"}:
        for n in snap.get("nodes") or []:
            lines.append("- GPU node " + _node_line(n))
        lines.append("- " + _brain_line(snap))
    if "speed" in topics:
        r = ((snap.get("router") or {}).get("recent") or {})
        if r.get("requests"):
            by = ", ".join(f"{k} {v}" for k, v in sorted(r.get("by_backend", {}).items(), key=lambda kv: -kv[1]))
            lines.append(f"- Last {r['requests']} requests: median first word {r.get('median_first_word_ms')} ms, "
                         f"median {r.get('median_tok_s')} tok/s; answered by {by}.")
        for e in (snap.get("errors") or [])[:2]:
            lines.append(f"- Recent problem: {e.get('where')}: {e.get('error')}")
    if "code" in topics:
        code = snap.get("code") or {}
        rep = (snap.get("reports") or {}).get("code") or {}
        dep = code.get("deployed") or {}
        commits = rep.get("deployed") or {}
        parts = []
        for name, d in dep.items():
            c = (commits.get(name) or {}).get("commit")
            parts.append(f"{name} {c[:8] if c else (d.get('blob') or '?')[:8] + ' (file id)'}")
        if parts:
            lines.append("- Deployed code: " + ", ".join(parts) + ".")
        if rep:
            ci = rep.get("ci") or {}
            lines.append(f"- Repo {rep.get('branch', 'star/next')} head {str(rep.get('head', '?'))[:8]} (checked {_age(rep.get('ts'))}); "
                         f"CI: {ci.get('state', 'unknown')}" + (f" ({', '.join(ci.get('failing', [])[:3])} failing)" if ci.get('failing') else "")
                         + f"; {len(rep.get('prs') or [])} open PRs.")
            for pr in (rep.get("prs") or [])[:3]:
                lines.append(f"  PR #{pr.get('number')} {str(pr.get('title', ''))[:70]} (touches {', '.join(pr.get('services', [])[:3]) or 'other'})")
        else:
            lines.append("- Repo/PR/CI status: not reported yet.")
    if "learning" in topics:
        rep = snap.get("reports") or {}
        t = rep.get("training")
        lines.append(f"- Nightly self-training: {t.get('state')} ({_age(t.get('ts'))})" + (f", {t.get('result')}" if t.get("result") else "")
                     if t else "- Nightly self-training: no report yet.")
        for a in (rep.get("autotune") or [])[-2:]:
            lines.append(f"- Autotuner {_age(a.get('ts'))}: {a.get('node')} {a.get('decision')} {a.get('candidate')} "
                         f"({a.get('tok_s')} vs {a.get('baseline_tok_s')} tok/s, quality {a.get('quality')}/{a.get('baseline_quality')})")
        for u in (rep.get("upgrade") or [])[-2:]:
            lines.append(f"- Upgrade check {_age(u.get('ts'))}: {u.get('component')} running {u.get('current')}, latest {u.get('latest')}: "
                         f"{u.get('decision')} ({u.get('why', '')[:80]})")
        for suite, pts in list((rep.get("evals") or {}).items())[:3]:
            if pts:
                seq = " -> ".join(f"{p.get('score')}" for p in pts[-4:])
                lines.append(f"- Eval {suite}: {seq}")
    out, size = [], 0
    for line in lines:
        if size + len(line) + 1 > max_chars:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)
