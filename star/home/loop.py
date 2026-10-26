"""Her loop: pick an interest, run an activity, record a verified outcome, learn from failures. Repeat within bounds.

cycle() does one step and returns what happened; run_forever() repeats it every minute (the scheduled task runs it).
Failures go to the curiosity queue (star/curiosity.py) in <home>/curiosity.jsonl: a session that did not verify is a
`failed_verification` item (what night school studies), each failed action a `tool_failure`. The practice interest
takes the top open item of that queue and resolves it (`taught` when verified, else `tried`).
"""
from __future__ import annotations

from pathlib import Path
import threading
import time

from .. import curiosity
from . import control
from .activities import Context, GpuProbe, Registry


def _emotion(kind: str, **payload) -> None:
    """Tell the emotion engine (star/emotion.py, its own branch) when it is installed; never fails the loop."""
    try:
        from .. import emotion  # type: ignore[attr-defined]
        emotion.on_event({"source": "star_home", "kind": kind, **payload})
    except Exception:
        pass


def cycle(home: Path, config: dict, registry: Registry, life, executor, chat, probe=None) -> dict:
    if control.stopped(home):
        return {"state": "stopped"}
    ok, why = life.budget_ok(config)
    if not ok:
        return {"state": "waiting", "why": why}
    eligible, game_note = registry.eligible(probe or GpuProbe(), config)
    eligible = [a for a in eligible if chat is not None or not a.needs_brain]
    interest = life.pick(registry.interests(eligible))
    if interest is None:
        return {"state": "idle", "why": game_note or ("no activity can run now" if chat else
                                                       "no brain configured (config.json brain_url)")}
    activity = life.rng.choice(sorted(registry.for_interest(interest, eligible), key=lambda a: a.name))
    goal = life.goal_for(interest)
    queue = Path(home) / "curiosity.jsonl"
    practice = curiosity.ranked(1, paths=(queue,)) if interest == "practice" else []
    ctx = Context(home=Path(home), config=config, executor=executor, life=life, chat=chat, interest=interest,
                  goal=goal, practice_topic=practice[0].topic if practice else "")
    control.log_action(home, "session", "start", interest=interest, activity=activity.name,
                       goal=goal["id"] if goal else "")
    _emotion("session_start", interest=interest, activity=activity.name)
    try:
        outcome = activity.run(ctx)
    except Exception as why:
        outcome = {"ok": False, "verified": False, "summary": f"activity crashed: {type(why).__name__}: {why}",
                   "evidence": [], "failures": [f"{activity.name}: {type(why).__name__}"]}
    row = life.record(interest, activity.name, outcome, goal)
    for failure in outcome.get("failures", [])[:5]:
        curiosity.record("tool_failure", f"star home {failure.split(':', 1)[0]}", failure, path=queue)
    if not row["verified"]:
        topic = f"star home {interest}: {goal['text'] if goal else activity.about or activity.name}"
        curiosity.record("failed_verification", topic, row["summary"], path=queue)
    if practice:
        curiosity.resolve([practice[0].key], "taught" if row["verified"] else "tried", by="star-home", path=queue)
    control.log_action(home, "session", "done", interest=interest, verified=row["verified"], summary=row["summary"])
    _emotion("session_done", interest=interest, verified=row["verified"], summary=row["summary"])
    return {"state": "worked", "interest": interest, "activity": activity.name, "verified": row["verified"],
            "summary": row["summary"]}


def run_forever(home: Path, config: dict, registry: Registry, life, executor, chat,
                *, tick_s: float = 60.0) -> None:  # pragma: no cover - the long-running process on the PC
    threading.Thread(target=control.hotkey_watch, args=(home,), daemon=True).start()
    probe = GpuProbe()
    while True:
        try:
            cycle(home, config, registry, life, executor, chat, probe)
        except Exception as why:
            control.log_action(home, "loop", "error", detail=f"{type(why).__name__}: {why}")
        time.sleep(tick_s)
