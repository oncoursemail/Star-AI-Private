"""STAR life extras (docs/agents/life-extras-20261026.md): a shared scrapbook with the owner, things she wants to do (her own, human), her
creative studio and gallery, and the mood-weather status API plus the owner's desktop widget.

    from star import life
    life.on_event({...})                 # a real moment with the owner -> scrapbook (needs with_owner, a source, a date)
    note = life.chat_note(home)          # "" or a note for the NEW user message of the OWNER's chat: an anniversary, or a goal
    note.text; note.done()               # she reached; done() after the reply was sent marks it as brought up
    life.tick(home, chat=chat, life=life_obj)        # STAR Home's loop, every cycle: her wishes drift, an idea may turn up, commentary
    life.after_session(home, interest, activity, outcome, life=life_obj)   # the loop, after each session
    life.register_home_activities(registry)          # "creative studio", "studio drawing", "pursue a goal", "personal style"

Everything is a setting in <home>/settings.json (store.FLAGS): scrapbook, goals and studio default ON (her PC profile); the
status API and the widget are opt-in. Every function that the loop or a chat calls never raises. No model decides what is
true here: moments and dates are checked by code, and what she says she achieved is checked quietly against her own record; the brain only words things.
"""
from __future__ import annotations

import dataclasses
import random
import time

from . import goals, scrapbook, studio, style
from .scrapbook import Note
from .store import FLAGS, LifeStore, default_store, flag

__all__ = ["FLAGS", "LifeStore", "Note", "after_session", "chat_note", "default_store", "flag", "goals", "on_event",
           "register_home_activities", "scrapbook", "studio", "style", "tick"]

MOMENT_KINDS = {"game_won": "game_win", "game_win": "game_win", "picture_made": "picture", "picture": "picture",
                "call_ended": "call", "call": "call", "first": "first", "build": "build", "song": "song"}


def on_event(event: dict, home=None, *, store: LifeStore | None = None, now: float | None = None) -> int | None:
    """Record a moment she really shared with the owner. `event`: kind, title, source, with_owner (must be True), and
    optional text, feeling, media (screenshot/clip path), ts, first_key. Anything else is ignored; never raises."""
    try:
        if not flag("life_scrapbook_enabled", home) or event.get("with_owner") is not True:
            return None
        store = store or default_store(home)
        kind = MOMENT_KINDS.get(str(event.get("kind")), "other")
        return scrapbook.add_moment(store, kind, event.get("title", ""), source=event.get("source", ""),
                                    text=event.get("text", ""), feeling=event.get("feeling", ""), media=event.get("media", ""),
                                    ts=event.get("ts"), first_key=event.get("first_key", ""), now=now)
    except Exception:
        return None


def honest(text: str, home=None) -> str:
    """The one check on what she says to others: a sentence that claims she did something more firmly than she can honestly
    say is softened ("I think I..." / "I've been trying..."). Use it on outgoing text; never raises, returns the text unchanged on error."""
    try:
        return goals.honest_text(default_store(home), text) if flag("life_goals_enabled", home) else text
    except Exception:
        return text


def chat_note(home=None, *, owner: bool = True, now: float | None = None, force: bool = False) -> Note:
    """Something she finished and has not told the owner about, else an anniversary due today, else nothing. Only for the owner's
    own chat (`owner=True`): the scrapbook is theirs and never goes into a friend's chat."""
    if not owner:
        return Note()
    note = goals.goals_note(home, force=force)
    return note if note.text else scrapbook.scrapbook_note(home, now=now, force=force)


# ---- STAR Home hooks --------------------------------------------------------------------------------------------
def _mood_kind() -> str:
    try:
        from .. import emotion
        from . import mood
        if emotion.enabled():
            return mood.weather_from(emotion.current(), emotion.default_engine().history(20)).kind
    except Exception:
        pass
    return ""


def _seen_hints(life) -> list[str]:
    """What she took in lately: summaries of her own recent sessions of watching, reading, playing and drawing (never a friend's chat)."""
    try:
        rows = life.history(30)
    except Exception:
        return []
    return [str(r.get("summary", ""))[:200] for r in rows[-12:] if r.get("interest") in ("watch_videos", "research", "play_games", "drawing")]


def tick(home=None, *, chat=None, life=None, now: float | None = None, rng: random.Random | None = None,
         friend_hints: list[str] | None = None, mood_kind: str | None = None) -> dict:
    """Once per loop cycle. Her wishes drift (at most every hour), a new idea may turn up (a thought every six hours or so, not
    always a wish), and pending studio commentary is written (at most once an hour). `friend_hints` are things friends are into
    (whoever knows them passes them; nothing reads friends' chats for this)."""
    out: dict = {}
    try:
        now = time.time() if now is None else now
        rng = rng or random.Random()
        store = default_store(home)
        complete = None
        if chat is not None:
            from ..inner.night import complete_from_chat
            complete = complete_from_chat(chat)
        if flag("life_goals_enabled", home):
            mood_kind = _mood_kind() if mood_kind is None else mood_kind
            seen = _seen_hints(life)
            if now - float(store.meta("last_drift", "0")) >= 3600:
                store.set_meta("last_drift", str(now))
                out["events"] = goals.drift(store, now, rng=rng, mood_kind=mood_kind, seen=seen, life=life)
            if now - float(store.meta("last_thought", "0")) >= 6 * 3600:
                store.set_meta("last_thought", str(now))
                made = goals.form(store, life.interests() if life is not None else {}, mood_kind=mood_kind, seen=seen,
                                  friends=friend_hints, complete=complete, life=life, now=now, rng=rng)
                out["new_goals"] = [made["text"]] if made else []
        if complete is not None and flag("life_studio_enabled", home) and now - float(store.meta("last_commentary", "0")) > 3600:
            store.set_meta("last_commentary", str(now))                 # at most one try an hour, whatever the brain says
            out["commentary"] = studio.fill_commentary(store, complete)
    except Exception as why:
        out["error"] = f"{type(why).__name__}: {why}"
    return out


def after_session(home, interest: str, activity: str, outcome: dict, *, life=None, now: float | None = None,
                  rng: random.Random | None = None) -> dict:
    """After a home session: save the moment it reports (outcome["moment"], only with the owner), and count the session as
    an attempt at the wish of that interest she is keenest on (unless the goal activity already did). Whether it counts as
    done is her call (`goals.judge`)."""
    out: dict = {}
    try:
        now = time.time() if now is None else now
        store = default_store(home)
        moment = outcome.get("moment")
        if isinstance(moment, dict) and on_event({**moment, "source": moment.get("source") or f"home-session:{activity} {time.strftime('%Y-%m-%d %H:%M', time.localtime(now))}"}, home, store=store, now=now):
            out["moment"] = True
        if flag("life_goals_enabled", home) and not outcome.get("life_counted") and not outcome.get("paused"):
            mine = [g for g in goals.goals(store, ("open", "active")) if g["interest"] == interest]
            if mine:
                goal = max(mine, key=lambda g: g["keen"])
                verified = bool(outcome.get("verified"))
                found = goals.evidence_from_outcome(goal, outcome) if verified else None
                goals.practice(store, goal["id"], str(outcome.get("summary", ""))[:200], verified,
                               ref=(found or {}).get("ref", ""), sure=bool(outcome.get("goal_done")) or found is not None, now=now)
                if verified and goals.judge(store, goal["id"], outcome, rng, life=life, now=now):
                    out["goal_done"] = goal["id"]
    except Exception as why:
        out["error"] = f"{type(why).__name__}: {why}"
    return out


def _ensure_interest(life, name: str, weight: float, about: str) -> None:
    try:
        if name not in life.interests():
            life.set_interest(name, weight, about)
    except Exception:
        pass


def _facts_of_today(life) -> str:
    """Her own sessions of the last day, as plain facts for a journal entry (nothing from friends' chats)."""
    try:
        rows = life.history(40)
    except Exception:
        return ""
    return "\n".join(f"- {r.get('interest', '')}: {str(r.get('summary', ''))[:100]}" +
                     ("" if r.get("verified") else " (it did not fully work)") for r in rows[-6:])


def _studio_activity(kinds: tuple[str, ...]):
    def run(ctx) -> dict:
        if not flag("life_studio_enabled", ctx.home):
            return {"ok": True, "verified": False, "summary": "the studio is switched off", "evidence": []}
        store = default_store(ctx.home)
        pause = studio.schedule_ok(store)
        if pause:
            return {"ok": True, "verified": False, "summary": pause, "evidence": []}
        from ..inner.night import complete_from_chat
        complete = complete_from_chat(ctx.chat) if ctx.chat is not None else None
        out = studio.make_work(store, complete=complete, facts=_facts_of_today(ctx.life),
                               makers={k: studio.MAKERS[k] for k in kinds})
        out["ok"] = True                                       # a missing pipeline is not her failure
        out.setdefault("evidence", [])
        return out
    return run


def _goal_activity(registry):
    def run(ctx) -> dict:
        if not flag("life_goals_enabled", ctx.home):
            return {"ok": True, "verified": False, "summary": "goals are switched off", "evidence": []}
        store = default_store(ctx.home)
        rng = random.Random()
        live = goals.goals(store, ("open", "active"))
        if not live:
            return {"ok": True, "verified": False, "summary": "nothing she feels like working on right now", "evidence": []}
        goal = rng.choices(live, weights=[max(0.05, g["keen"]) for g in live], k=1)[0]
        if rng.random() < goals.p_put_off(goal):
            goals.procrastinate(store, goal["id"])               # some days she just does not feel like it
            return {"ok": True, "verified": True, "evidence": [], "life_counted": True,
                    "summary": f"did not feel like working on '{goal['want'][:50]}' and wandered off"}
        plan = goals.practice_plan(goal)
        pool = [a for a in registry.for_interest(plan["interest"]) if a.name != "pursue a goal"]
        if not pool:
            goals.hand_to_night_school(goal, "no activity here can practise this yet")
            return {"ok": True, "verified": False, "evidence": [], "life_counted": True,
                    "summary": f"nothing to practise '{goal['want'][:50]}' with right now; left it for night school"}
        activity = sorted(pool, key=lambda a: a.name)[0]
        inner_ctx = dataclasses.replace(ctx, interest=plan["interest"], goal={"id": f"life{goal['id']}", "interest": plan["interest"],
                                        "text": goal["want"], "status": "open", "tries": goal["tries"]})
        try:
            outcome = activity.run(inner_ctx)
        except Exception as why:
            outcome = {"ok": False, "verified": False, "summary": f"{type(why).__name__}", "evidence": []}
        if outcome.get("paused"):
            return outcome
        verified = bool(outcome.get("verified"))
        found = goals.evidence_from_outcome(goal, outcome) if verified else None
        goals.practice(store, goal["id"], f"{activity.name}: {str(outcome.get('summary', ''))[:160]}", verified,
                       ref=(found or {}).get("ref", ""), sure=bool(outcome.get("goal_done")) or found is not None)
        result: dict = dict(outcome, life_counted=True)
        if not verified:
            goals.hand_to_night_school(goal, str(outcome.get("summary", ""))[:200])
        elif goals.judge(store, goal["id"], outcome, rng):
            result["summary"] = f"felt it was done: {goal['want'][:80]}"
        return result
    return run


def register_home_activities(registry) -> None:
    """star-home plug-in hook (star.home.activities.PLUGIN_MODULES)."""
    runtime = getattr(registry, "runtime", None)
    life = getattr(runtime, "life", None)
    if life is not None:
        _ensure_interest(life, "creative_studio", 1.0, "make her own drawings, stories, songs and Roblox experiments")
        _ensure_interest(life, "personal_goals", 0.9, "work on goals she set for herself and prove them")
        _ensure_interest(life, "personal_style", 0.5, "choose her own wallpaper, colours, sounds and avatar look")
    registry.register("creative studio", "creative_studio", _studio_activity(("story", "journal", "song", "roblox")),
                      "write a story, a journal entry, a song or a small Roblox experiment", needs_brain=True)
    registry.register("studio drawing", "creative_studio", _studio_activity(("drawing",)),
                      "make a drawing with the image pipeline and her style notes", gpu_mb=6000, needs_brain=True)
    registry.register("personal style", "personal_style", style.style_activity(registry),
                      "change her wallpaper, accent colour, cursor, sounds, stickers and avatar look to match her mood", needs_brain=False)
    registry.register("pursue a goal", "personal_goals", _goal_activity(registry),
                      "practise one of her own goals and prove it when she reaches it", needs_brain=True)
