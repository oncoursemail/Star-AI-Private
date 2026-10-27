"""STAR life extras (docs/agents/life-extras-20261026.md): a shared scrapbook with the owner, her own goals and streaks, her
creative studio and gallery, and the mood-weather status API plus the owner's desktop widget.

    from star import life
    life.on_event({...})                 # a real moment with the owner -> scrapbook (needs with_owner, a source, a date)
    note = life.chat_note(home)          # "" or a note for the NEW user message of the OWNER's chat: an anniversary, or a goal
    note.text; note.done()               # she reached; done() after the reply was sent marks it as brought up
    life.tick(home, chat=chat, life=life_obj)        # STAR Home's loop, every cycle: sweep goals, set one, fill commentary
    life.after_session(home, interest, activity, outcome, life=life_obj)   # the loop, after each session
    life.register_home_activities(registry)          # "creative studio", "studio drawing", "pursue a goal", "personal style"

Everything is a setting in <home>/settings.json (store.FLAGS): scrapbook, goals and studio default ON (her PC profile); the
status API and the widget are opt-in. Every function that the loop or a chat calls never raises. No model decides what is
true here: moments, proofs and dates are checked by code; the brain only words things and writes her commentary.
"""
from __future__ import annotations

import dataclasses
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


def chat_note(home=None, *, owner: bool = True, now: float | None = None, force: bool = False) -> Note:
    """A finished goal she has not told the owner about, else an anniversary due today, else nothing. Only for the owner's
    own chat (`owner=True`): the scrapbook is theirs and never goes into a friend's chat."""
    if not owner:
        return Note()
    note = goals.goals_note(home, force=force)
    return note if note.text else scrapbook.scrapbook_note(home, now=now, force=force)


# ---- STAR Home hooks --------------------------------------------------------------------------------------------
def tick(home=None, *, chat=None, life=None, now: float | None = None) -> dict:
    """Once per loop cycle: give up goals that ran out, set a new goal at most once a day, write pending commentary."""
    out: dict = {}
    try:
        now = time.time() if now is None else now
        store = default_store(home)
        complete = None
        if chat is not None:
            from ..inner.night import complete_from_chat
            complete = complete_from_chat(chat)
        if flag("life_goals_enabled", home):
            out["abandoned"] = [g["id"] for g in goals.sweep(store, now, life=life)]
            if store.meta("last_goal_day") != time.strftime("%Y-%m-%d", time.localtime(now)):
                store.set_meta("last_goal_day", time.strftime("%Y-%m-%d", time.localtime(now)))
                made = goals.propose(store, life.interests() if life is not None else {}, complete=complete, life=life, now=now)
                out["new_goals"] = [g["text"] for g in made]
        if complete is not None and flag("life_studio_enabled", home) and now - float(store.meta("last_commentary", "0")) > 3600:
            store.set_meta("last_commentary", str(now))                 # at most one try an hour, whatever the brain says
            out["commentary"] = studio.fill_commentary(store, complete)
    except Exception as why:
        out["error"] = f"{type(why).__name__}: {why}"
    return out


def after_session(home, interest: str, activity: str, outcome: dict, *, life=None, now: float | None = None) -> dict:
    """After a home session: save the moment it reports (outcome["moment"], only with the owner), and count the session as
    practice for the open goal of that interest (unless the goal activity already did)."""
    out: dict = {}
    try:
        now = time.time() if now is None else now
        store = default_store(home)
        moment = outcome.get("moment")
        if isinstance(moment, dict) and on_event({**moment, "source": moment.get("source") or f"home-session:{activity} {time.strftime('%Y-%m-%d %H:%M', time.localtime(now))}"}, home, store=store, now=now):
            out["moment"] = True
        if flag("life_goals_enabled", home) and not outcome.get("life_counted") and not outcome.get("paused"):
            mine = [g for g in goals.goals(store, ("open", "active")) if goals.DOMAINS.get(g["domain"], ("",))[0] == interest]
            if mine:
                goal = min(mine, key=lambda g: g["tries"])
                verified = bool(outcome.get("verified"))
                goals.practice(store, goal["id"], str(outcome.get("summary", ""))[:200], verified, now=now)
                proof = goals.proof_from_outcome(goal, outcome) if verified else None
                if proof is not None:
                    try:
                        goals.complete(store, goal["id"], proof, life=life, now=now)
                        out["goal_done"] = goal["id"]
                    except goals.GoalError as why:
                        out["proof_refused"] = str(why)
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
        live = goals.goals(store, ("open", "active"))
        if not live:
            return {"ok": True, "verified": False, "summary": "no goal of her own is open", "evidence": []}
        goal = min(live, key=lambda g: (g["tries"], g["id"]))
        plan = goals.practice_plan(goal)
        pool = [a for a in registry.for_interest(plan["interest"]) if a.name != "pursue a goal"]
        if not pool:
            goals.hand_to_night_school(goal, "no activity here can practise this yet")
            return {"ok": True, "verified": False, "evidence": [], "life_counted": True,
                    "summary": f"nothing to practise '{goal['text'][:50]}' with right now; left it for night school"}
        activity = sorted(pool, key=lambda a: a.name)[0]
        inner_ctx = dataclasses.replace(ctx, interest=plan["interest"], goal={"id": f"life{goal['id']}", "interest": plan["interest"],
                                        "text": goal["text"], "status": "open", "tries": goal["tries"]})
        try:
            outcome = activity.run(inner_ctx)
        except Exception as why:
            outcome = {"ok": False, "verified": False, "summary": f"{type(why).__name__}", "evidence": []}
        if outcome.get("paused"):
            return outcome
        verified = bool(outcome.get("verified"))
        goals.practice(store, goal["id"], f"{activity.name}: {str(outcome.get('summary', ''))[:160]}", verified)
        result = dict(outcome, life_counted=True)
        if not verified:
            goals.hand_to_night_school(goal, str(outcome.get("summary", ""))[:200])
        else:
            proof = goals.proof_from_outcome(goal, outcome)
            if proof is not None:
                try:
                    goals.complete(store, goal["id"], proof)
                    result["summary"] = f"reached a goal: {goal['text'][:80]}"
                except goals.GoalError as why:
                    result["summary"] = f"{result.get('summary', '')} (proof refused: {why})"[:300]
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
