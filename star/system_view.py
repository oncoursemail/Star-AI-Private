"""`star_system`: STAR reads her own live system self-model (server/mesh/selfmodel behind the mesh router).

What it answers from real data: which machines and GPUs she runs on and what each is doing right now (idle, busy
because the owner is gaming, off), measured speeds, which brain models are loaded and busy, the commit each service
runs, open PRs and CI, nightly self-training, autotuner and upgrade-watcher decisions, and where heavy work of her own
could run now (`heavy_work_slot`). Read-only; nothing here changes a machine.

Offered (like star_clock) only when the prompt asks about her own hardware, speed, code or learning: `wants_system`.
The detector mirrors server/mesh/selfmodel/brief.py's (the app and the server are deployed separately; a test keeps
the two in agreement).

Address: env STAR_MESH_URL, else the first line of ~/.star/mesh_url (the mesh router, e.g. http://<router>:8100).
Key: the STAR Server key (Settings or ~/.star/server_api_key), kept in memory and never shown to the model.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

_WHO = r"(?:you|u|ya|litha|star|yourself)"
_HW = (r"(?:gpus?|graphics\s*cards?|video\s*cards?|cards?|machines?|computers?|pcs?|servers?|hardware|models?|cpus?"
       r"|cores?|vram|memory|ram|brain|nodes?)")
_PATTERNS = [re.compile(p, re.I) for p in (
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
TOPICS = ("all", "gpu", "speed", "code", "learning", "schedule")
TIMEOUT_S = 4.0

TOOL = {
    "name": "star_system",
    "description": ("Read live, measured facts about yourself: the machines and GPUs you run on and what each is doing "
                    "now (idle/busy/off and why), speeds, loaded brain models, which code each service runs, open PRs "
                    "and CI, nightly self-training, autotuner and upgrade results, and where heavy work could run now. "
                    "Answer questions about your own hardware, speed, code or learning from this, never from memory. "
                    "Read-only."),
    "inputSchema": {"type": "object", "properties": {
        "topic": {"type": "string", "enum": list(TOPICS),
                  "description": "gpu (machines/GPUs), speed (why slow/fast), code (deployed commits, PRs, CI), "
                                 "learning (training, autotuner, upgrades, evals), schedule (free hardware), all"}},
        "required": [], "additionalProperties": False},
}


def wants_system(prompt: str) -> bool:
    text = (prompt or "")[-1500:]
    return any(p.search(text) for p in _PATTERNS)


def mesh_url() -> str:
    if os.environ.get("STAR_MESH_URL", "").strip():
        return os.environ["STAR_MESH_URL"].strip().rstrip("/")
    f = Path.home() / ".star" / "mesh_url"
    try:
        return f.read_text(encoding="utf-8").split()[0].rstrip("/")
    except (OSError, IndexError):
        return ""


def _key() -> str:
    try:
        from .providers import STAR_SERVER, get_api_key
        key = get_api_key(STAR_SERVER)
        if key:
            return key
    except Exception:
        pass
    try:
        from .server_key_file import read_key_file
        return read_key_file()
    except (ValueError, OSError):
        return ""


def fetch(path: str, *, url: str | None = None, key: str | None = None, timeout: float = TIMEOUT_S) -> dict:
    base = url if url is not None else mesh_url()
    if not base:
        raise ValueError("the mesh router address is not configured (STAR_MESH_URL or ~/.star/mesh_url)")
    key = key if key is not None else _key()
    if not key:
        raise ValueError("no STAR Server key")
    req = urllib.request.Request(base + path, headers={"Authorization": f"Bearer {key}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # LAN: never through a system proxy
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read(2_000_000))


def read(topic: str = "all", **kw) -> str:
    """Plain text for the model (the brief), or the scheduling block for topic 'schedule'."""
    topic = topic if topic in TOPICS else "all"
    if topic == "schedule":
        s = fetch("/mesh/self/schedule", **kw)
        gpus = ", ".join(f"{g['name']} ({g.get('gpu')}, {g.get('vram_free_mb')} MB free"
                         + (", serving Litha" if g.get("serving_litha") else "") + ")" for g in s.get("free_gpus") or [])
        return (f"Free GPUs now: {gpus or 'none'}. Best for heavy work: {s.get('best_gpu') or 'none'}. "
                f"Brain idle: {s.get('brain_idle')}. Night window: {s.get('night')}. {s.get('why', '')}")
    data = fetch("/mesh/self/brief?topic=" + topic + "&max=2000", **kw)
    return str(data.get("text") or "")


def heavy_work_slot(min_vram_mb: int = 6000, *, need_night: bool = True, **kw) -> dict | None:
    """Where a heavy job of hers (training, distillation, re-indexing) may start now, or None. GPU jobs need a free
    GPU with enough memory; with need_night the owner's daytime rule is kept (night window of the router host)."""
    s = fetch("/mesh/self/schedule", **kw)
    if need_night and not s.get("night"):
        return None
    for g in sorted(s.get("free_gpus") or [], key=lambda g: -(g.get("vram_free_mb") or 0)):
        if (g.get("vram_free_mb") or 0) >= min_vram_mb or g.get("serving_litha"):
            return {"where": g["name"], "gpu": g.get("gpu"), "vram_free_mb": g.get("vram_free_mb"),
                    "must_unload_litha": bool(g.get("serving_litha"))}
    return None


async def tool_result(args: dict) -> dict:
    if not isinstance(args, dict) or set(args) - {"topic"}:
        return {"isError": True, "content": [{"type": "text", "text": "star_system takes only 'topic'"}]}
    try:
        text = await asyncio.to_thread(read, str(args.get("topic") or "all"))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"isError": True, "content": [{"type": "text",
                "text": f"Self-model unavailable ({type(exc).__name__}); say you cannot see your system state now."}]}
    return {"isError": False, "content": [{"type": "text", "text": text or "No data."}]}
