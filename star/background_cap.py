"""Shared cap on background work for star-fast: at most LIMIT background requests at once, from any process or machine.

llama.cpp has no request priorities, but it queues a request that names a busy slot (`id_slot`) until that slot is
free. So background clients (night school, the night conductor, evals, playtest learning, Studio Lab critiques) name
one of the background slots 1..LIMIT and never slot 0: the server itself then runs at most LIMIT of them at once, and
with star-fast at `parallel = LIMIT + 1` one slot is always free for the owner's chat (Discord, desktop, voice), which
STAR places on an idle slot (unpinned, or moved off a busy slot by `providers.look_for_busy_slots`).

The cap lives in the server, so it holds across processes and machines without a lock file or a service: a client on
the PC or brain 2 is capped exactly like one in the brain's container. A background client that names no slot is not
capped; every known one goes through this module (docs/agents/chat-slot-20261020.md lists them).

API (stdlib only):
    limit()                          LIMIT (STAR_BACKGROUND_SLOTS, default 2)
    is_capped(model)                 True for star-fast and its aliases
    background_slots(n_slots)        the slots background work may name: [1 .. min(LIMIT, n_slots - 1)]
    choose(report)                   from a `GET /slots` list: an idle background slot, else the first one
    slot_for(url, key, model)        asks the server, falls back to slot 1; None for a model that is not capped
    process_is_background()          STAR_BACKGROUND_WORK=1: every star-fast request of this process is background
"""
from __future__ import annotations

import json
import os

CAPPED_MODELS = frozenset({"star-fast", "star-code", "star-vision"})
DEFAULT_LIMIT = 2
FALLBACK_SLOT = 1          # exists on every multi-slot star-fast, and is never the chat's free slot 0
PROBE_TIMEOUT_S = 3.0


def limit() -> int:
    try:
        return max(1, int(os.environ.get("STAR_BACKGROUND_SLOTS", DEFAULT_LIMIT)))
    except ValueError:
        return DEFAULT_LIMIT


def is_capped(model: str) -> bool:
    return str(model or "") in CAPPED_MODELS


def process_is_background() -> bool:
    return os.environ.get("STAR_BACKGROUND_WORK", "").strip().lower() in ("1", "true", "yes", "on")


def background_slots(n_slots: int, cap: int | None = None) -> list[int]:
    """Slot ids background work may name. Empty for a single-slot model: its only slot is the chat's."""
    if type(n_slots) is not int or n_slots < 2:
        return []
    return list(range(1, min(cap or limit(), n_slots - 1) + 1))


def choose(report, cap: int | None = None) -> int | None:
    """The background slot to name, from llama.cpp's `/slots` list: the first idle one, else the first one (the
    request then waits in the server's queue, which is the cap). None when the report is not a slot list."""
    if not isinstance(report, list):
        return None
    ids = [row["id"] for row in report if isinstance(row, dict) and type(row.get("id")) is int]
    if not ids:
        return None
    allowed = background_slots(max(ids) + 1, cap)
    if not allowed:
        return None
    busy = {row["id"] for row in report if isinstance(row, dict) and row.get("is_processing") is True}
    return next((slot for slot in allowed if slot not in busy), allowed[0])


def slot_for(url: str, key: str, model: str, *, opener=None, cap: int | None = None) -> int | None:
    """The slot a background request to `model` on the brain at `url` (no /v1) should name. None when `model` is not
    capped. Any probe failure gives FALLBACK_SLOT. Never logs or returns the address or the key."""
    if not is_capped(model):
        return None
    import urllib.parse
    import urllib.request
    request = urllib.request.Request(url.rstrip("/") + "/slots?model=" + urllib.parse.quote(model),
                                     headers={"Authorization": "Bearer " + key} if key else {})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=PROBE_TIMEOUT_S) as reply:
            report = json.loads(reply.read(4 * 1024 * 1024).decode("utf-8", "replace"))
    except Exception:
        return FALLBACK_SLOT
    chosen = choose(report, cap)
    if chosen is None and isinstance(report, list) and any(isinstance(r, dict) and r.get("id") == 0 for r in report):
        return None                     # a single-slot model: naming slot 1 would wait forever, name none
    return FALLBACK_SLOT if chosen is None else chosen
