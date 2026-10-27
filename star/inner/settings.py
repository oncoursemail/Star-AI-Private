"""Settings for the parts of her inner life added on 10-26 (memory stream, insights, planner, consolidation, summary).

Same file as the other inner flags: <app data>/settings.json (store.flag). Default ON on her own PC (a STAR install
root exists: star.home.paths.root()), OFF everywhere else; `"inner_profile": "own_pc"` or `"other"` overrides the
detection. The older inner flags (inner_night_enabled, inner_chat_enabled, inner_reachout_enabled) keep their own
measured defaults in store.FLAGS and are not touched here.
"""
from __future__ import annotations

import json
from pathlib import Path

PREFIX = "inner_"
FLAGS = (
    "brain_enabled",         # master switch for everything in this file
    "memory_stream",         # perceptions, chats, game events and thoughts become memory records
    "remote_embed",          # embed through the brain's /v1/embeddings (star-embed); else the local hash embedder
    "insights",              # reflection on the memory stream: insights with evidence links
    "planner",               # the day planner + energy model pick her activities (else star-home's Life.pick)
    "consolidation",         # night: replay, facts + lessons, emotional processing, dream fallback, prune/merge
    "self_summary",          # the "who I am right now" line in her STAR Home session prompts
    "model_calls",           # night-time brain calls for insights and facts (JSON-schema constrained)
)
NUMBERS = {
    "reflection_threshold": 3.0,     # summed importance (0..1 each) of new memories before she reflects
    "summary_tokens": 90,            # budget of the "who I am right now" line
    "max_active_minutes": 600,       # compute bound: minutes of activities per day
    "wake_hour": 8, "sleep_hour": 1,  # her day; the same night window as store.NIGHT_START/NIGHT_END
    "block_hours": 2,                # length of a planner block
    "max_memories": 20000,
}
LISTS = {"owner_free_hours": [[18, 23]]}   # when the owner is usually around: social / play blocks lean there


def own_pc() -> bool:
    try:
        from ..home import paths
        return paths.root() is not None
    except Exception:
        return False


def _file(home) -> Path:
    from .store import _home
    return _home(home) / "settings.json"


def load(home=None) -> dict:
    """Effective values with short names (prefix dropped). Never raises, never writes."""
    try:
        saved = json.loads(_file(home).read_text(encoding="utf-8-sig"))
        saved = saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        saved = {}
    profile = saved.get(PREFIX + "profile")
    on = own_pc() if profile not in ("own_pc", "other") else profile == "own_pc"
    out: dict = {"profile": "own_pc" if on else "other"}
    for name in FLAGS:
        value = saved.get(PREFIX + name)
        out[name] = value if isinstance(value, bool) else on
    for name, default in NUMBERS.items():
        value = saved.get(PREFIX + name)
        out[name] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else default
    for name, default in LISTS.items():
        value = saved.get(PREFIX + name)
        out[name] = value if isinstance(value, list) else default
    return out


def save(home=None, **changes) -> dict:
    """Owner edit (short names): merged into settings.json, other keys in the file kept; unknown names refused."""
    known = set(FLAGS) | set(NUMBERS) | set(LISTS) | {"profile"}
    bad = sorted(set(changes) - known)
    if bad:
        raise ValueError(f"unknown setting(s): {', '.join(bad)}")
    path = _file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
        current = current if isinstance(current, dict) else {}
    except (OSError, ValueError):
        current = {}
    current.update({PREFIX + k: v for k, v in changes.items()})
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=1), encoding="utf-8")
    tmp.replace(path)
    return load(home)


def on(settings: dict, name: str) -> bool:
    return bool(settings.get("brain_enabled")) and bool(settings.get(name))
