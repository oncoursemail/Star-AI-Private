"""The cognitive core that ties her inner life into one continuous day: memory stream, insights, self-model view, day
planner + energy, night consolidation, inner monologue and the owner's journal view.

Wiring (all guarded; nothing here can break a chat, a session or the loop):
  star-home      `wrap_life(Life(home))` (star/home/__main__.py): pick() asks the planner, record() turns a session into
                 episodic + procedural memories, spends energy and nudges interests by mood; `session_context()` is
                 the "who I am right now" line + relevant lessons for STAR Home brain sessions (star/home/brain.py)
  night/tick     star.inner.night.tick() (already called by star-home's loop every cycle) calls Mind.tick(): inbox ->
                 stream, emotion events -> perceptions, insights when due, night consolidation once a night, page
  social chat    `observe_conversation()` appends one inbox line per exchange (no embedding, no model: the hot path
                 only writes a line); `forget_person()` on "forget me"
Stops: nothing runs while the owner's STOP file exists (star.home.control) or the settings are off.
"""
from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path

from . import consolidate, insights, planner, selfview
from . import settings as settings_mod
from .store import _home

EMOTION_LOOKBACK = 300


class Mind:
    def __init__(self, home=None, *, life_home=None, settings: dict | None = None, stream=None, embedder=None,
                 clock=time.time, emotion=..., rng: random.Random | None = None, inner_store=None,
                 friend_memory=None) -> None:
        self.home = _home(home)
        self.life_home = Path(life_home) if life_home is not None else None
        self._settings = settings
        self._stream, self._embedder = stream, embedder
        self.clock = clock
        self._emotion = emotion
        self.rng = rng or random.Random()
        self._inner_store, self._friends = inner_store, friend_memory
        self._page_at = 0.0
        self._lock = threading.RLock()

    # -- parts ----------------------------------------------------------------------------------------------------
    @property
    def settings(self) -> dict:
        return self._settings if self._settings is not None else settings_mod.load(self.home)

    def on(self, name: str) -> bool:
        return settings_mod.on(self.settings, name) and not self.stopped()

    def stopped(self) -> bool:
        if self.life_home is None:
            return False
        from ..home import control
        return control.stopped(self.life_home)

    @property
    def stream(self):
        with self._lock:
            if self._stream is None:
                from .embed import default_embedder
                from .stream import MemoryStream
                self._stream = MemoryStream(self.home / "inner", clock=self.clock,
                                            embedder=self._embedder or default_embedder(self.life_home, self.settings))
            return self._stream

    @property
    def energy(self) -> planner.Energy:
        return planner.Energy(self.stream)

    @property
    def emotion(self):
        if self._emotion is ...:
            try:
                from .. import emotion as module
                self._emotion = module
            except ImportError:
                self._emotion = None
        return self._emotion

    def inner_store(self):
        if self._inner_store is None:
            from .store import default_store
            self._inner_store = default_store(self.home)
        return self._inner_store

    def log(self, phase: str, **fields) -> None:
        if self.life_home is not None:
            try:
                from ..home import control
                control.log_action(self.life_home, "inner", phase, **fields)
            except Exception:
                pass

    def mood(self) -> tuple[float, float, str]:
        """(valence, arousal, dominant feeling) from star.emotion when it is on; neutral otherwise."""
        emotion = self.emotion
        try:
            if emotion is not None and (not hasattr(emotion, "enabled") or emotion.enabled()):
                state = emotion.current() if hasattr(emotion, "current") else None
                if state:
                    return float(state.get("valence", 0)), float(state.get("arousal", 0.35)), state.get("dominant") or ""
        except Exception:
            pass
        return 0.0, 0.35, ""

    # -- writing memories (hot paths only append to the inbox) -----------------------------------------------------
    def observe(self, text: str, *, kind: str = "episodic", source: str = "perception", importance: float | None = None,
                **fields) -> None:
        if not self.on("memory_stream"):
            return
        valence, arousal, feeling = self.mood()
        if importance is None:
            from .recall import rate_importance
            base, _ = rate_importance(text)
            importance = max(base, 0.2 + 0.6 * abs(valence))
        self.stream.observe(text=text, kind=kind, source=source, importance=round(importance, 3), valence=valence,
                            arousal=arousal, feeling=feeling, **fields)

    def observe_conversation(self, friend_memory, person, platform: str, said: str, reply: str = "") -> None:
        """One exchange. Only a confirmed adult outside Roblox gives a record with content; a possible minor, an unknown
        age or anyone on Roblox gives a content-free "chatted with" record (no personal details from kids)."""
        if not self.on("memory_stream") or person is None or not getattr(person, "remembered", False):
            return
        from ..social import rules
        from .store import person_key
        pkey = person_key(friend_memory, person)
        if not pkey:
            return
        name = str(person.name or "someone")[:40]
        adult = rules.age_status(person) == "adult" and platform != "roblox"
        text = f"{name} said: {' '.join(str(said).split())[:240]}" if adult else f"Chatted with {name} on {platform}"
        self.observe(text, source="conversation", platform=platform, people=[pkey], names=[name],
                     importance=None if adult else 0.25)

    def think(self, thought: str, why: str = "", *, now: float | None = None) -> None:
        """Her inner monologue: a line in <app data>/inner/monologue.jsonl for the owner, and a low-importance memory.
        The same thought again within 30 minutes is not repeated (the loop asks every minute)."""
        now = self.clock() if now is None else now
        try:
            last = json.loads(self.stream.meta("last_thought", "{}") or "{}")
        except ValueError:
            last = {}
        if last.get("thought") == thought and now - float(last.get("ts", 0)) < 1800:
            return
        self.stream.set_meta("last_thought", json.dumps({"thought": thought, "ts": now}))
        path = self.home / "inner" / "monologue.jsonl"
        try:
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"ts": now, "thought": thought, "why": why}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        if self.on("memory_stream"):
            self.stream.observe(text=thought, kind="thought", source="thought", importance=0.1, ts=now)

    def monologue(self, last: int = 30) -> list[dict]:
        try:
            lines = (self.home / "inner" / "monologue.jsonl").read_text(encoding="utf-8").splitlines()[-last:]
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    # -- her day ---------------------------------------------------------------------------------------------------
    def plan(self, now: float, available: set[str], life) -> dict:
        s = self.settings
        day = planner.day_of(now, int(s["wake_hour"]))
        found = planner.load_plan(self.stream, day)
        if found is not None:
            return found
        prev = planner.day_of(now - 86400, int(s["wake_hour"]))
        slept = self.stream.meta("last_night") == prev
        self.energy.wake(now, slept)
        valence, arousal, _ = self.mood()
        made = planner.make_plan(day, s, life.interests() if life is not None else {}, set(available),
                                 valence=valence, arousal=arousal,
                                 practise_bonus=bool(self.stream.meta(f"practise_bonus:{day}")))
        self.stream.set_meta(f"plan:{day}", json.dumps(made))
        self.log("plan", day=day, blocks=[f"{b['start']:02d} {b['category']}" for b in made["blocks"]])
        self.think("Today: " + ", ".join(f"{b['category']} at {b['start']:02d}" for b in made["blocks"][:5]),
                   "planned the day", now=now)
        return made

    def multipliers(self, available: set[str], life) -> dict[str, float]:
        try:
            from . import self_model
            model = self_model.current(self.inner_store())
            about = life.interests() if life is not None else {}
            return {i: self_model.weight_multiplier(model, i, (about.get(i) or {}).get("about", "")) for i in available}
        except Exception:
            return {}

    def pick(self, available: set[str], life) -> tuple[str | None, str]:
        now = self.clock()
        s = self.settings
        day_plan = self.plan(now, available, life)
        day = planner.day_of(now, int(s["wake_hour"]))
        active = float(self.stream.meta(f"active:{day}", "0") or 0)
        interest, why = planner.choose(day_plan, now, set(available), life.scores(set(available)),
                                       self.energy.level(now), s, active_minutes=active,
                                       multipliers=self.multipliers(set(available), life), rng=self.rng)
        thought = f"I'll do some {interest.replace('_', ' ')}" if interest else (
            "Sleeping" if why == "sleeping" else "I'll rest for a bit")
        self.think(thought, why, now=now)
        self.log("choose", interest=interest or "", why=why)
        return interest, why

    def on_session(self, interest: str, activity: str, outcome: dict, row: dict, life=None) -> None:
        """A finished STAR Home session: episodic + procedural memory, energy, interest drift by mood, a thought."""
        now = self.clock()
        s = self.settings
        verified = bool(row.get("verified"))
        minutes = float(row.get("minutes") or outcome.get("minutes") or 0.0)
        valence, arousal, feeling = self.mood()
        category = planner.category_of(interest)
        level = self.energy.spend(category, minutes, now, valence=valence)
        day = planner.day_of(now, int(s["wake_hour"]))
        self.stream.set_meta(f"active:{day}", round(float(self.stream.meta(f"active:{day}", "0") or 0) + minutes, 1))
        if not self.on("memory_stream"):
            return
        self.stream.ingest()
        stats = self.stream.skill_stats(now).get(activity, {})
        predicted = stats.get("confidence", 0.5)
        first_win = verified and stats.get("successes", 0) == 0
        summary = " ".join(str(row.get("summary") or "").split())[:200]
        common = {"platform": "pc", "place": interest, "valence": valence, "arousal": arousal, "feeling": feeling,
                  "ts": now, "verified": verified}
        self.stream.observe(text=f"{activity}: {summary} ({'checked' if verified else 'not checked'})",
                            kind="episodic", source="activity", importance=round(min(1.0, 0.35 + 0.25 * verified
                                                                                      + 0.3 * abs(valence)), 3),
                            milestone=first_win, **common)
        self.stream.observe(text=f"tried {activity}: {'worked' if verified else 'did not work'}", kind="procedural",
                            source="activity", skill=activity, outcome=int(verified), predicted=predicted,
                            importance=0.4, **common)
        if life is not None:
            entry = life.interests().get(interest)
            if entry is not None and abs(valence) > 0.3:
                life.set_interest(interest, float(entry.get("weight", 1.0)) * (1.03 if valence > 0 else 0.97))
        mood = "happy with it" if valence > 0.3 else "a bit down about it" if valence < -0.3 else ""
        self.think(f"{'Finished' if verified else 'Tried'} {activity.replace('_', ' ')}" + (f", {mood}" if mood else "")
                   + (f"; energy {level:.2f}" if level < 0.45 else ""), "session done", now=now)

    # -- background ------------------------------------------------------------------------------------------------
    def ingest_emotions(self) -> int:
        emotion = self.emotion
        if emotion is None or not hasattr(emotion, "default_engine"):
            return 0
        try:
            if hasattr(emotion, "enabled") and not emotion.enabled():
                return 0
            rows = emotion.default_engine().history(EMOTION_LOOKBACK)
            from ..emotion_model import EVENTS
        except Exception:
            return 0
        since = float(self.stream.meta("emotion_seen", "0") or 0)
        fresh = [r for r in rows if r["at"] > since and not str(r.get("detail") or "").startswith("star home")]
        records = []
        for r in sorted(fresh, key=lambda r: r["at"]):
            valence = float((EVENTS.get(r["kind"]) or ({}, 0.0, 0.0))[1])
            detail = " ".join(str(r.get("detail") or "").split())[:120]
            records.append({"text": f"felt {r['kind'].replace('_', ' ')}" + (f": {detail}" if detail else ""),
                            "kind": "episodic", "source": "emotion", "ts": r["at"], "valence": max(-1, min(1, valence * 3)),
                            "importance": round(min(1.0, 0.15 + 0.4 * float(r.get("strength") or 0.5)), 3)})
        if rows:
            self.stream.set_meta("emotion_seen", max(r["at"] for r in rows))
        self.stream.add_many(records)
        return len(records)

    def _inner_dream(self, now: float) -> dict | None:
        try:
            from .store import night_of
            row = self.inner_store().db.execute("SELECT text, gist, valence FROM dreams WHERE night = ?",
                                                (night_of(now),)).fetchone()
            return {"text": row[0], "gist": row[1], "valence": row[2]} if row else None
        except Exception:
            return None

    def night(self, now: float, *, complete=None) -> dict:
        s = self.settings
        key = planner.day_of(now, int(s["wake_hour"]))
        since = float(self.stream.meta("last_night_ts", "0") or 0) or now - 26 * 3600
        report: dict = {"night": key}
        try:
            friends = self._friends
            if friends is None:
                from .night import _friends
                friends = _friends(self.home)
            report["purged"] = self.stream.purge_orphans(friends)
        except Exception as why:
            report["purged"] = f"skipped: {type(why).__name__}"
        report.update(consolidate.run(self.stream, now, night=key, since=since, inner_dream=self._inner_dream(now),
                                      complete=complete, rng=random.Random(f"dream:{key}"),
                                      journal=self.home / "inner" / "journal.md", cap=int(s["max_memories"])))
        if self.on("insights"):
            report["insights"] = insights.reflect(self.stream, now, complete=complete)
        self.stream.set_meta("last_night", key)
        self.stream.set_meta("last_night_ts", now)
        self.log("night", **{k: v for k, v in report.items() if k in ("night", "facts", "lessons", "merged", "pruned",
                                                                       "softened", "purged")})
        return report

    def tick(self, now: float | None = None, *, complete=None, write_page: bool = True) -> dict:
        """Idempotent background step. Does nothing while off or stopped."""
        if not settings_mod.on(self.settings, "brain_enabled"):
            return {}
        if self.stopped():
            return {"state": "stopped"}
        now = self.clock() if now is None else now
        s = self.settings
        out: dict = {"ingested": self.stream.ingest() if self.on("memory_stream") else 0}
        if self.on("memory_stream"):
            out["emotions"] = self.ingest_emotions()
        key = planner.day_of(now, int(s["wake_hour"]))
        if self.on("consolidation") and planner.asleep(now, s) and self.stream.meta("last_night") != key:
            out["night"] = self.night(now, complete=complete if self.on("model_calls") else None)
        elif self.on("insights") and insights.due(self.stream, now, float(s["reflection_threshold"])):
            out["insights"] = insights.reflect(self.stream, now)
        if write_page and now - self._page_at > 600:
            self._page_at = now
            try:
                from . import journal_view
                journal_view.write_page(self, now=now)
            except Exception as why:
                out["page"] = f"failed: {type(why).__name__}"
        return out

    # -- prompts and the owner -------------------------------------------------------------------------------------
    def self_view(self, life=None, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        try:
            from . import self_model
            model = self_model.current(self.inner_store())
        except Exception:
            model = None
        return selfview.build(self.stream, life=life, inner_model=model, now=now)

    def summary(self, life=None, now: float | None = None) -> str:
        """The "who I am right now" line, rendered at most every 6 hours (a stable prompt prefix)."""
        if not self.on("self_summary"):
            return ""
        now = self.clock() if now is None else now
        s = self.settings
        day = planner.day_of(now, int(s["wake_hour"]))
        bucket = f"{day}:{time.localtime(now).tm_hour // 6}"
        try:
            cached = json.loads(self.stream.meta("summary", "{}") or "{}")
        except ValueError:
            cached = {}
        if cached.get("bucket") == bucket:
            return cached.get("text", "")
        text = selfview.summary(self.self_view(life, now), self.stream, budget_tokens=int(s["summary_tokens"]),
                                morning=selfview.morning_note(self.stream, day, now))
        self.stream.set_meta("summary", json.dumps({"bucket": bucket, "text": text}))
        return text

    def session_context(self, interest: str, goal: dict | None = None, life=None) -> str:
        """For a STAR Home brain session: the summary line + up to 3 relevant lessons/insights/past attempts (her own
        life only: no person-linked or private memory)."""
        if not self.on("self_summary"):
            return ""
        lines = [self.summary(life)]
        query = f"{interest.replace('_', ' ')} {goal.get('text', '') if goal else ''}"
        hits = [m for m in self.stream.retrieve(query, k=6, kinds=("semantic", "reflection", "procedural", "episodic"))
                if not m.people][:3]
        if hits:
            lines.append("From your memory (maybe useful): " + "; ".join(m.text[:120] for m in hits))
        return "\n".join(line for line in lines if line)

    def forget_person(self, pkey: str) -> int:
        if not pkey:
            return 0
        removed = self.stream.forget_person(pkey)
        self.log("forget", detail=f"{removed} memories about one person removed")
        return removed


class MindLife:
    """star-home's Life with her mind in it: everything delegates to Life except pick() and record()."""

    def __init__(self, life, mind: Mind) -> None:
        self._life = life
        self.mind = mind

    def __getattr__(self, name):
        return getattr(self._life, name)

    def pick(self, available: set[str]) -> str | None:
        if not self.mind.on("planner"):
            return self._life.pick(available)
        try:
            interest, _ = self.mind.pick(set(available), self._life)
            return interest
        except Exception as why:
            self.mind.log("error", detail=f"planner: {type(why).__name__}: {why}")
            return self._life.pick(available)

    def record(self, interest: str, activity: str, outcome: dict, goal: dict | None = None) -> dict:
        row = self._life.record(interest, activity, outcome, goal)
        try:
            if settings_mod.on(self.mind.settings, "brain_enabled"):
                self.mind.on_session(interest, activity, outcome, row, life=self._life)
        except Exception as why:
            self.mind.log("error", detail=f"on_session: {type(why).__name__}: {why}")
        if row.get("verified"):                 # something real she did: a friend who loves it may hear about it
            try:
                from ..social.initiative import share_learned
                share_learned(interest, str(row.get("summary") or ""), verified=True)
            except Exception:
                pass
        return row

    def session_context(self, interest: str, goal: dict | None = None) -> str:
        try:
            return self.mind.session_context(interest, goal, self._life)
        except Exception:
            return ""


def wrap_life(life, life_home=None, **kwargs) -> MindLife:
    return MindLife(life, Mind(life_home=life_home if life_home is not None else getattr(life, "dir", Path(".")).parent,
                               **kwargs))


_minds: dict[str, Mind] = {}
_minds_lock = threading.Lock()


def default_mind(home=None, life_home=None) -> Mind:
    if life_home is None:
        try:
            from ..home.control import home_dir
            life_home = home_dir()
        except Exception:
            life_home = None
    key = f"{_home(home)}|{life_home}"
    with _minds_lock:
        if key not in _minds:
            _minds[key] = Mind(home, life_home=life_home)
        return _minds[key]


def observe_conversation(friend_memory, person, platform: str, said: str, reply: str = "") -> None:
    """Social chat hook (never raises, appends one inbox line or nothing)."""
    try:
        default_mind().observe_conversation(friend_memory, person, platform, said, reply)
    except Exception:
        pass


def forget_person(friend_memory, person) -> int:
    """Social chat "forget me" hook: call before friend memory forgets them (the key needs their row)."""
    try:
        from .store import person_key
        mind = default_mind()
        if not (mind.home / "inner" / "stream.sqlite3").exists():
            return 0                     # nothing was ever stored (forget works even with the settings off)
        return mind.forget_person(person_key(friend_memory, person))
    except Exception:
        return 0
