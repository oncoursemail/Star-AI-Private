"""Her night: reflect, dream, revise herself; and her morning: wake from the dream. All background, no chat latency.

    python -m star.inner tick        # idempotent: does tonight's work once during 01:00-08:00 local, wakes her in the morning
    python -m star.inner night       # run the night job now (testing)
    star.inner.night.tick(...)       # the same, for a scheduler or star-home's loop to call every few minutes
    star.inner.register_home_activities(registry)   # star-home plug-in: activity "inner night" (see below)

Order of a night (each step independent; one failing never stops the next): reflect.run (diary, cards, opinions, consolidate,
audit) -> dreams.generate -> self_model.revise. In the morning `tick` calls dreams.wake (the mood nudge). Settings in
<app data>/settings.json: `inner_night_enabled` (default true: background work only).

Home plug-in: star-home picks activities by interest weight, so the "inner night" activity (interest `inner_life`) is only
picked once that interest exists in star/home/life.py's interests; star-home's loop calling `tick()` itself is the simpler and
exact way (it is idempotent, and does nothing outside the night window). The activity reuses the loop's brain connection.
"""
from __future__ import annotations

import calendar
import json
import random
import sys
import time
from pathlib import Path

from . import dreams, reachout, reflect, self_model
from .store import InnerStore, default_store, flag, in_night_window, night_of

DAY_S = 26 * 3600


def default_complete(max_tokens: int = 420):
    """complete(system, user) -> str on the quick model through the Discord brain's background slot (no tools, no history)."""
    def complete(system: str, user: str) -> str:
        import asyncio
        from ..discord_bot.brain import DiscordBrain
        return asyncio.run(DiscordBrain().compose(system, user, max_tokens=max_tokens))
    return complete


def complete_from_chat(chat):
    """complete(system, user) from star-home's `chat(messages, tools) -> message` brain connection."""
    def complete(system: str, user: str) -> str:
        reply = chat([{"role": "system", "content": system}, {"role": "user", "content": user}], [])
        return str(reply.get("content") or "")
    return complete


def _epoch(stamp: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return 0.0


def _history(life_home, since: float) -> list[dict]:
    """star-home's session history (<home>/life/history.jsonl) since a moment; [] when there is none."""
    try:
        lines = (Path(life_home) / "life" / "history.jsonl").read_text(encoding="utf-8").splitlines()[-300:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if _epoch(row.get("ts", "")) >= since:
            rows.append(row)
    return rows


def _life_home(life_home):
    if life_home is not None:
        return life_home
    from ..home.control import home_dir
    return home_dir()


def _emotion_events(emotion, since: float) -> list[dict]:
    try:
        engine = emotion.default_engine() if hasattr(emotion, "default_engine") else emotion
        return [e for e in engine.history(300) if e["at"] >= since]
    except Exception:
        return []


def _open_curiosity(curiosity_path, life_home) -> list:
    from .. import curiosity
    try:
        paths = (Path(curiosity_path),) if curiosity_path else (Path(life_home) / "curiosity.jsonl",)
        return curiosity.ranked(4, paths=paths)
    except Exception:
        return []


def _friends(home):
    from ..social.friends import FriendMemory
    return FriendMemory(Path(home) / "social" / "friends.sqlite3") if home is not None else FriendMemory()


def _life_evidence(life_home) -> str:
    """Her own goals and skill confidence (star.life) as evidence for the nightly self review; "" when there is none."""
    try:
        if life_home is None:
            return ""
        from ..life import goals
        from ..life.store import default_store as life_store, flag as life_flag
        return goals.evidence_text(life_store(life_home)) if life_flag("life_goals_enabled", life_home) else ""
    except Exception:
        return ""


def run_night(home=None, *, complete=None, memory=None, store: InnerStore | None = None, now: float | None = None,
              rng: random.Random | None = None, emotion=None, life_home=None, curiosity_path=None) -> dict:
    """Tonight's work. `home` is the app data folder (settings, friend memory, inner.sqlite3)."""
    now = time.time() if now is None else now
    rng = rng or random.Random()
    store = store or default_store(home)
    own_memory = memory is None
    memory = memory or _friends(home)
    complete = complete or default_complete()
    if emotion is None:
        from .. import emotion as emotion_module
        emotion = emotion_module
    life_home = _life_home(life_home)
    history = _history(life_home, now - DAY_S)
    events = _emotion_events(emotion, now - DAY_S)
    report: dict = {"night": night_of(now)}
    try:
        report["reflect"] = reflect.run(store, memory, complete, now=now, history=history, emotion_events=events,
                                        curiosity_path=curiosity_path)
    except Exception as why:
        report["reflect"] = {"error": f"{type(why).__name__}: {why}"}
    try:
        report["dream"] = dreams.generate(store, memory, complete, now, rng, history=history, emotion_events=events,
                                          curiosity_items=_open_curiosity(curiosity_path, life_home))
    except Exception as why:
        report["dream"] = {"error": f"{type(why).__name__}: {why}"}
    try:
        gist = (report.get("dream") or {}).get("gist")
        evidence = "\n".join(x for x in (
            f"Diary: {(report.get('reflect') or {}).get('diary', '')}", (report.get("reflect") or {}).get("notes", ""),
            f"Her dream was about: {gist}" if gist else "", _life_evidence(life_home)) if x)
        report["self"] = self_model.revise(store, complete, evidence, now=now)
    except Exception as why:
        report["self"] = {"error": f"{type(why).__name__}: {why}"}
    store.set_meta("last_night", night_of(now))
    if own_memory:
        memory.close()
    return report


def tick(home=None, *, now: float | None = None, force: bool = False, **kwargs) -> dict:
    """Idempotent scheduler step: run tonight's job once inside the night window; in the morning let the dream touch her mood.
    Does nothing (and loads no model) outside those cases."""
    now = time.time() if now is None else now
    store = kwargs.pop("store", None) or default_store(home)
    out: dict = {}
    kwargs = _constrained(home, kwargs)
    if (force or in_night_window(now)) and flag("inner_night_enabled", home) and store.meta("last_night") != night_of(now):
        out["night"] = run_night(home, now=now, store=store, **kwargs)
    emotion = kwargs.get("emotion")
    try:
        woke = dreams.wake(store, now, emotion=emotion)
    except Exception:
        woke = None
    if woke:
        out["woke"] = woke
    reachout.expire(store, now)
    try:                                 # the memory stream, insights, planner state, consolidation (mind.py; off = no-op)
        from .mind import default_mind
        brain = default_mind(home, kwargs.get("life_home")).tick(now, complete=kwargs.get("complete"))
        if brain:
            out["brain"] = brain
    except Exception as why:
        out["brain"] = {"error": f"{type(why).__name__}: {why}"}
    return out


def _constrained(home, kwargs: dict) -> dict:
    """On her PC with model calls on, night calls use JSON-schema constrained decoding straight to the brain
    (structured.schema_complete) instead of the loop's plain chat: small models then cannot emit broken JSON."""
    try:
        from . import settings as brain_settings
        from .structured import schema_complete
        life_home = kwargs.get("life_home")
        if life_home is None or not brain_settings.on(brain_settings.load(home), "model_calls"):
            return kwargs
        from ..home.control import load_config
        config = load_config(Path(life_home))
        if config.get("brain_url"):
            return {**kwargs, "complete": schema_complete(config)}
    except Exception:
        pass
    return kwargs


def register_home_activities(registry) -> None:
    """star-home plug-in hook (called by star.home.activities.default_registry for modules in PLUGIN_MODULES)."""
    def run(ctx) -> dict:
        complete = complete_from_chat(ctx.chat) if ctx.chat is not None else None
        done = tick(life_home=ctx.home, **({"complete": complete} if complete else {}))
        ran = "night" in done
        return {"ok": True, "verified": ran, "evidence": [], "steps": 1,
                "summary": "reflected, dreamed and reviewed herself" if ran else "nothing due (not night, or already done)"}
    registry.register("inner night", "inner_life", run, "reflect on the day, dream and revise herself at night")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "tick"
    if command in BRAIN_COMMANDS:
        return brain_cli(command, args[1:])
    if command not in ("tick", "night", "journal", "dream"):
        print("usage: python -m star.inner tick | night | journal | dream | " + " | ".join(BRAIN_COMMANDS))
        return 2
    store = default_store()
    if command == "journal":
        print(self_model.journal_text(store))
    elif command == "dream":
        found = dreams.remembered(store, time.time())
        print(found[0]["text"] if found else "no dream remembered right now")
    else:
        result = tick(force=command == "night")
        print(json.dumps(result, ensure_ascii=False, default=str, indent=1))
    return 0


BRAIN_COMMANDS = ("brain", "page", "plan", "memories", "facts", "settings", "set", "forget-person", "stop")


def brain_cli(command: str, rest: list[str]) -> int:
    """Owner commands for the memory stream / planner / journal (mind.py, journal_view.py)."""
    from . import journal_view, settings as brain_settings
    from .mind import default_mind
    mind = default_mind()
    if command == "settings":
        print(json.dumps(brain_settings.load(), indent=1))
    elif command == "set":
        if len(rest) != 2:
            print("usage: python -m star.inner set NAME VALUE   (VALUE: true/false/number/JSON)")
            return 2
        try:
            value = json.loads(rest[1])
        except ValueError:
            value = rest[1]
        print(json.dumps(brain_settings.save(None, **{rest[0]: value}), indent=1))
    elif command == "stop":
        from ..home import control
        print(f"STOP created: {control.stop(mind.life_home)}")
    elif command == "brain":
        print(json.dumps(journal_view.snapshot(mind), ensure_ascii=False, default=str, indent=1))
    elif command == "page":
        print(journal_view.write_page(mind))
    elif command == "plan":
        from . import planner
        day = planner.day_of(time.time(), int(mind.settings["wake_hour"]))
        print(json.dumps(planner.load_plan(mind.stream, day) or {"day": day, "blocks": []}, indent=1))
    elif command == "memories":
        query = " ".join(rest)
        rows = mind.stream.retrieve(query, k=10, touch=False) if query else mind.stream.all()[-20:]
        for m in rows:
            print(f"{m.id:>6} {time.strftime('%m-%d %H:%M', time.localtime(m.ts))} [{m.kind}] {m.text}")
    elif command == "facts":
        for m in mind.stream.all(kind="semantic"):
            state = "superseded" if m.invalid_at else "current"
            print(f"{m.id:>6} {state:<10} {m.fact_key}: {m.text}")
    elif command == "forget-person":
        if len(rest) != 1:
            print("usage: python -m star.inner forget-person PERSON_KEY   (the <id>.<first met> key)")
            return 2
        print(f"removed {mind.forget_person(rest[0])} memories")
    return 0
