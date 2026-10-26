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


DEFAULT_KINDS = {"play_games": "game", "watch": "video", "watch_videos": "video"}
CREATIVE = ("game_making", "drawing", "music")


def _emotion(kind: str, **payload) -> None:
    """Tell the emotion engine (star/emotion.py) what happened; only when it is switched on, and never fails the loop."""
    try:
        from .. import emotion
        emotion.on_event(kind, only_if_enabled=True, **payload)
    except Exception:
        pass


def _feel_outcome(interest: str, verified: bool, summary: str) -> None:
    """An activity's verified outcome is a success (a finished creation counts for more), anything else a mild failure."""
    detail = f"star home {interest}: {summary}"[:80]
    if verified and interest in CREATIVE:
        _emotion("creative_done", strength=0.8, detail=detail)
    elif verified and interest == "research":
        _emotion("learned_something", strength=0.7, detail=detail)
    elif verified:
        _emotion("task_success", strength=0.6, detail=detail)
    else:
        _emotion("task_failure", strength=0.5, detail=detail)


def _inner_tick(home: Path, chat) -> None:
    """Her night (reflection, dream, self-review) and morning wake; idempotent, does nothing outside those windows."""
    try:
        from ..inner import night
        complete = night.complete_from_chat(chat) if chat is not None else None
        night.tick(life_home=home, **({"complete": complete} if complete else {}))
    except Exception as exc:
        control.log_action(home, "inner", "error", detail=str(exc)[:200])


def cycle(home: Path, config: dict, registry: Registry, life, executor, chat, probe=None, attention=None) -> dict:
    """One step of her day. With `attention` (star.home.attention): first answer what is waiting (a friend's message or
    call that is due), then do what she asked herself to start, else resume what was paused, else pick something."""
    if control.stopped(home):
        return {"state": "stopped"}
    _inner_tick(home, chat)
    shared ={"interrupt": attention.interrupt, "situation": attention.situation} if attention is not None else {}

    def context_for(platform: str) -> Context:
        return Context(home=Path(home), config=config, executor=executor, life=life, chat=chat,
                       interest="chat_with_friends", goal=None, **shared)

    parked = None
    activity = None
    if attention is not None:
        served = attention.serve(context_for)
        if served:
            return {"state": "served", "served": served}
        wanted = attention.take_request()
        if wanted and wanted in registry.items:
            activity = registry.items[wanted]
            attention.parked = None
        elif wanted:
            control.log_action(home, "session", "refused", detail=f"no activity named {wanted}")
        if activity is None:
            parked = attention.take_parked()
    resumed = parked is not None
    if resumed:
        activity, interest, goal, state = parked.activity, parked.interest, parked.goal, parked.state
    else:
        state = {}
        ok, why = life.budget_ok(config)
        if not ok and activity is None:
            if attention is not None and attention.last_state == "worked":
                _emotion("took_a_break", strength=0.6, detail="pausing between sessions")     # the pause is her break
            if attention is not None:
                attention.last_state = "waiting"
            return {"state": "waiting", "why": why}
        eligible, game_note = registry.eligible(probe or GpuProbe(), config)
        eligible = [a for a in eligible if chat is not None or not a.needs_brain]
        if activity is None:
            interest = life.pick(registry.interests(eligible))
            if interest is None:
                return {"state": "idle", "why": game_note or ("no activity can run now" if chat else
                                                               "no brain configured (config.json brain_url)")}
            activity = life.rng.choice(sorted(registry.for_interest(interest, eligible), key=lambda a: a.name))
        else:
            interest = activity.interest
        goal = life.goal_for(interest)
    queue = Path(home) / "curiosity.jsonl"
    practice = curiosity.ranked(1, paths=(queue,)) if interest == "practice" and not resumed else []
    ctx = Context(home=Path(home), config=config, executor=executor, life=life, chat=chat, interest=interest,
                  goal=goal, practice_topic=practice[0].topic if practice else "", resume_state=state,
                  resumed=resumed, **shared)
    control.log_action(home, "session", "resume" if resumed else "start", interest=interest, activity=activity.name,
                       goal=goal["id"] if goal else "")
    if attention is not None:
        attention.begin({**DEFAULT_KINDS, **registry.situations}.get(interest, "work"), activity.name)
    started = time.monotonic()
    try:
        outcome = activity.run(ctx)
    except Exception as why:
        outcome = {"ok": False, "verified": False, "summary": f"activity crashed: {type(why).__name__}: {why}",
                   "evidence": [], "failures": [f"{activity.name}: {type(why).__name__}"]}
    finally:
        if attention is not None:
            attention.end()
    outcome.setdefault("minutes", (time.monotonic() - started) / 60.0)
    if outcome.get("paused") and attention is not None:
        attention.park(activity, interest, goal, outcome.get("resume_state"))
        control.log_action(home, "session", "paused", interest=interest, activity=activity.name,
                           summary=str(outcome.get("summary", ""))[:200])
        return {"state": "paused", "interest": interest, "activity": activity.name}
    row = life.record(interest, activity.name, outcome, goal)
    for failure in outcome.get("failures", [])[:5]:
        curiosity.record("tool_failure", f"star home {failure.split(':', 1)[0]}", failure, path=queue)
    if not row["verified"]:
        topic = f"star home {interest}: {goal['text'] if goal else activity.about or activity.name}"
        curiosity.record("failed_verification", topic, row["summary"], path=queue)
    if practice:
        curiosity.resolve([practice[0].key], "taught" if row["verified"] else "tried", by="star-home", path=queue)
    control.log_action(home, "session", "done", interest=interest, verified=row["verified"], summary=row["summary"])
    _feel_outcome(interest, row["verified"], row["summary"])
    if attention is not None:
        attention.last_state = "worked"
    return {"state": "worked", "interest": interest, "activity": activity.name, "verified": row["verified"],
            "summary": row["summary"]}


def run_forever(home: Path, config: dict, registry: Registry, life, executor, chat,
                *, tick_s: float = 60.0, attention=None, background=()) -> None:  # pragma: no cover - the long-running process on the PC
    """`background` are callables run each on their own daemon thread (the notification watcher, the call timer)."""
    threading.Thread(target=control.hotkey_watch, args=(home,), daemon=True).start()
    for job in background:
        threading.Thread(target=job, daemon=True).start()
    probe = GpuProbe()
    while True:
        result = {}
        try:
            result = cycle(home, config, registry, life, executor, chat, probe, attention)
        except Exception as why:
            control.log_action(home, "loop", "error", detail=f"{type(why).__name__}: {why}")
        busy = result.get("state") in ("served", "paused")
        if attention is not None:
            attention.idle_wait(1.0 if busy else tick_s)
        else:
            time.sleep(tick_s)
