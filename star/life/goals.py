"""Her own goals: she sets them from her interests and weak skills, practises, and only calls one done with proof.

Lifecycle (one row per goal, one log line per step; `status`):
    open -> active (first practice step) -> done        needs PROOF: a screenshot/clip file made after the goal was set,
                                                        or a passing test result the runner produced (`complete`)
    open|active -> abandoned                            needs a written reason (`abandon`); a goal whose week ran out and
                                                        stayed untouched for GRACE_DAYS more is abandoned with that reason (`sweep`)
`practice()` records one attempt (verified or not) and keeps a day streak. Practice itself is delegated, not rebuilt:
`practice_plan()` names the home activity to run (star.play's roblox/minecraft sessions, her drawing/game-making sessions)
and the topic to hand to night school through the curiosity queue (star/curiosity.py), whose practice tasks the night job
studies. Skill confidence (`skill_confidence()`, 0-1 per skill, moved by every attempt and by finished/abandoned goals) is
what the nightly self-model review reads as evidence (`evidence_text()`); it never edits the self-model itself, whose
bounds stay in star/inner/self_model.py.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .store import LifeStore, day_of, default_store, flag

MAX_OPEN = 3
WEEK_S = 7 * 86400
GRACE_DAYS = 7
NOVELTY_DAYS = 14
MIN_REASON = 8
DOMAINS = {"obby": ("play_games", "clip"), "game": ("play_games", "clip"), "luau": ("practice", "test"),
           "drawing": ("drawing", "screenshot"), "music": ("music", "clip"), "build": ("game_making", "screenshot")}
# fallback goals from an interest when nothing is known to be weak: (domain, skill, text)
FROM_INTEREST = {"play_games": ("obby", "obby:moving platforms", "Beat the obby I keep falling off, this week"),
                 "drawing": ("drawing", "drawing:dragons", "Draw a dragon I'm proud of"),
                 "game_making": ("luau", "luau:tweens", "Learn a new Luau trick and write a script that passes its test"),
                 "practice": ("luau", "luau:events", "Fix the thing I failed at before until its test passes"),
                 "music": ("music", "music:loops", "Make a loop I would play for a friend")}
FROM_WEAK = {"obby": "Beat an obby with {x} this week", "luau": "Learn a new Luau trick: {x}, with a test that passes",
             "drawing": "Draw something with {x} that I'm proud of", "game": "Win a round of a game by getting better at {x}",
             "music": "Make a short piece that gets {x} right", "build": "Build something small that shows {x} done well"}
MEDIA = {"screenshot": (".png", ".jpg", ".jpeg", ".webp", ".bmp"), "clip": (".mp4", ".webm", ".gif", ".mkv", ".mov")}
_SLUG = re.compile(r"[^a-z0-9: ]+")
COLS = ("id", "text", "domain", "skill", "interest", "proof_kind", "status", "created", "due", "tries", "ok_tries", "streak",
        "best_streak", "last_day", "closed", "reason", "proof", "announced", "home_goal")


class GoalError(ValueError):
    """A step the lifecycle refuses (no proof, no reason, unknown goal, wrong state)."""


def slug(text: str) -> str:
    return re.sub(r"\s*:\s*", ":", " ".join(_SLUG.sub(" ", str(text or "").lower()).split()))[:40]


def get(store: LifeStore, goal_id: int) -> dict | None:
    rows = store.rows(f"SELECT {', '.join(COLS)} FROM goals WHERE id = ?", (goal_id,))
    return dict(zip(COLS, rows[0])) if rows else None


def goals(store: LifeStore, status: str | tuple | None = None) -> list[dict]:
    wanted = (status,) if isinstance(status, str) else status
    rows = [dict(zip(COLS, r)) for r in store.rows(f"SELECT {', '.join(COLS)} FROM goals ORDER BY id")]
    return [g for g in rows if wanted is None or g["status"] in wanted]


def is_open(goal: dict) -> bool:
    return goal["status"] in ("open", "active")


def _log(store: LifeStore, goal_id: int, kind: str, note: str = "", verified: bool = False, ref: str = "", now=None) -> None:
    store.run("INSERT INTO goal_log (goal_id, ts, kind, note, verified, ref) VALUES (?,?,?,?,?,?)",
              (goal_id, store.clock() if now is None else now, kind, str(note)[:300], int(verified), str(ref)[:300]))


def log(store: LifeStore, goal_id: int) -> list[dict]:
    return [dict(zip(("ts", "kind", "note", "verified", "ref"), r)) for r in
            store.rows("SELECT ts, kind, note, verified, ref FROM goal_log WHERE goal_id = ? ORDER BY id", (goal_id,))]


# ---- skill confidence -----------------------------------------------------------------------------------------
def nudge_skill(store: LifeStore, skill: str, toward: float, rate: float, now: float | None = None) -> None:
    skill = slug(skill)
    if not skill:
        return
    now = store.clock() if now is None else now
    row = store.rows("SELECT confidence, n FROM skills WHERE skill = ?", (skill,))
    old, n = (row[0][0], row[0][1]) if row else (0.5, 0)
    new = round(min(1.0, max(0.0, old + rate * (toward - old))), 3)
    store.run("INSERT OR REPLACE INTO skills (skill, confidence, n, updated) VALUES (?,?,?,?)", (skill, new, n + 1, now))


def skill_confidence(store: LifeStore) -> dict[str, float]:
    return {s: c for s, c in store.rows("SELECT skill, confidence FROM skills ORDER BY skill")}


def weak_skills(store: LifeStore, limit: int = 5, below: float = 0.45) -> list[str]:
    """Skills she is unsure of: the lowest confidence first, then topics night school has not taught her yet."""
    out = [s for s, c in sorted(skill_confidence(store).items(), key=lambda kv: kv[1]) if c < below]
    return out[:limit]


def evidence_text(store: LifeStore, now: float | None = None, days: int = 7) -> str:
    """What the nightly self-review should know about her goals and skills (empty when there is nothing)."""
    now = store.clock() if now is None else now
    since = now - days * 86400
    done = [g for g in goals(store, "done") if g["closed"] >= since]
    dropped = [g for g in goals(store, "abandoned") if g["closed"] >= since]
    live = goals(store, ("open", "active"))
    lines = []
    if done:
        lines.append("Goals finished with proof this week: " + "; ".join(g["text"][:60] for g in done[:3]))
    if dropped:
        lines.append("Goals she gave up: " + "; ".join(f"{g['text'][:40]} ({g['reason'][:40]})" for g in dropped[:3]))
    if live:
        lines.append("Working on: " + "; ".join(f"{g['text'][:50]} (streak {g['streak']})" for g in live[:3]))
    skills = skill_confidence(store)
    if skills:
        ranked = sorted(skills.items(), key=lambda kv: kv[1])
        lines.append("Skill confidence, lowest first: " + ", ".join(f"{s} {c:.2f}" for s, c in ranked[:3]) +
                     "; highest: " + ", ".join(f"{s} {c:.2f}" for s, c in ranked[-2:]))
    return "\n".join(lines)


# ---- setting goals --------------------------------------------------------------------------------------------
def _similar(a: str, b: str) -> bool:
    from ..inner.store import overlap, tokens
    return overlap(tokens(a), b) >= 0.8 and overlap(tokens(b), a) >= 0.8


def _rephrase(text: str, complete) -> str:
    """Her own wording of a goal (at most 100 characters); the plain template when the brain gives nothing usable."""
    if complete is None:
        return text
    try:
        from ..persona import leaked_reasoning, strip_reasoning
        said = strip_reasoning(str(complete("You are STAR, a playful, curious AI. Say the goal in one short sentence in "
                                            "your own voice. No quotes, no list, no explanation.", text) or "")).strip()
        said = " ".join(said.split()).strip("\"' ")
        return said if 12 <= len(said) <= 100 and not leaked_reasoning(said) else text
    except Exception:
        return text


def propose(store: LifeStore, interests: dict | None = None, weak: list[str] | None = None, *, complete=None,
            life=None, now: float | None = None, max_new: int = 1) -> list[dict]:
    """Set up to `max_new` new goals (never beyond MAX_OPEN open ones): from her weak skills first, then from the
    interests she weights most. A goal that repeats an open one, or one she finished or dropped in the last NOVELTY_DAYS,
    is skipped. If `life` (star.home.life.Life) is given the goal is also added there so her sessions of that interest work on it."""
    now = store.clock() if now is None else now
    room = min(max_new, MAX_OPEN - len(goals(store, ("open", "active"))))
    if room <= 0:
        return []
    weak = weak_skills(store) if weak is None else weak
    candidates: list[tuple[str, str, str, str]] = []                  # (domain, skill, text, interest)
    for skill in weak:
        domain, _, topic = slug(skill).partition(":")
        if domain in FROM_WEAK:
            candidates.append((domain, slug(skill), FROM_WEAK[domain].format(x=topic.strip() or "the basics"),
                               DOMAINS[domain][0]))
    for name in sorted(interests or {}, key=lambda n: -float((interests or {}).get(n, {}).get("weight", 1.0))):
        if name in FROM_INTEREST:
            domain, skill, text = FROM_INTEREST[name]
            candidates.append((domain, skill, text, name))
    made: list[dict] = []
    recent = [g for g in goals(store) if not is_open(g) and now - g["closed"] < NOVELTY_DAYS * 86400]
    for domain, skill, text, interest in candidates:
        if len(made) >= room:
            break
        live = goals(store, ("open", "active"))
        if any(g["domain"] == domain or _similar(g["text"], text) for g in live):
            continue
        if any(_similar(g["text"], text) for g in recent):
            continue
        text = _rephrase(text, complete)[:140]
        proof_kind = DOMAINS[domain][1]
        cur = store.run("INSERT INTO goals (text, domain, skill, interest, proof_kind, created, due) VALUES (?,?,?,?,?,?,?)",
                        (text, domain, skill, interest, proof_kind, now, now + WEEK_S))
        goal_id = cur.lastrowid
        _log(store, goal_id, "set", f"{domain} / {skill}", now=now)
        if life is not None:
            try:
                if interest in life.interests():
                    store.run("UPDATE goals SET home_goal = ? WHERE id = ?", (life.add_goal(interest, text)["id"], goal_id))
            except Exception:
                pass
        made.append(get(store, goal_id))
    return made


# ---- practising -----------------------------------------------------------------------------------------------
def practice(store: LifeStore, goal_id: int, note: str, verified: bool, *, ref: str = "", now: float | None = None) -> dict:
    """One attempt. Moves the day streak (a missed day starts it again at 1) and the skill's confidence."""
    goal = get(store, goal_id)
    if goal is None or not is_open(goal):
        raise GoalError("that goal is not open")
    now = store.clock() if now is None else now
    today = day_of(now)
    if goal["last_day"] == today:
        streak = goal["streak"]
    elif goal["last_day"] == day_of(now - 86400):
        streak = goal["streak"] + 1
    else:
        streak = 1
    store.run("UPDATE goals SET tries = tries + 1, ok_tries = ok_tries + ?, streak = ?, best_streak = max(best_streak, ?), "
              "last_day = ?, status = 'active' WHERE id = ?", (int(bool(verified)), streak, streak, today, goal_id))
    _log(store, goal_id, "practice", note, verified, ref, now)
    nudge_skill(store, goal["skill"], 1.0 if verified else 0.0, 0.15, now)
    return get(store, goal_id)


def practice_plan(goal: dict) -> dict:
    """What practising this goal means: the home activity to run, and the topic night school should study."""
    interest = DOMAINS.get(goal["domain"], ("practice", "test"))[0]
    return {"interest": interest, "topic": f"star life goal: {goal['text'][:120]}", "skill": goal["skill"]}


def hand_to_night_school(goal: dict, detail: str = "", *, path=None) -> bool:
    """Put what she could not do yet on the curiosity queue; the night job turns it into practice tasks."""
    from .. import curiosity
    return curiosity.record("failed_verification", practice_plan(goal)["topic"], detail or goal["text"], path=path)


# ---- proof ----------------------------------------------------------------------------------------------------
def check_proof(goal: dict, proof) -> str:
    """'' when the proof is real for this goal, else why not. A media proof is a file that exists, is not empty and was
    made after the goal was set; a test proof is a result the runner reports as passed, with its name and time."""
    if not isinstance(proof, dict) or proof.get("kind") not in ("screenshot", "clip", "test"):
        return "proof must be a screenshot, a clip or a passing test"
    kind = proof["kind"]
    if kind != goal["proof_kind"] and not (kind in MEDIA and goal["proof_kind"] in MEDIA):
        return f"this goal needs a {goal['proof_kind']} as proof"
    if kind == "test":
        name, ran = str(proof.get("name") or "").strip(), proof.get("ran_at")
        if proof.get("passed") is not True or not name:
            return "the test did not pass (or has no name)"
        if not isinstance(ran, (int, float)) or ran < goal["created"]:
            return "the test result is older than the goal"
        return ""
    path = Path(str(proof.get("ref") or ""))
    if path.suffix.lower() not in MEDIA[kind]:
        return f"a {kind} proof must be one of {', '.join(MEDIA[kind])}"
    try:
        stat = path.stat()
    except OSError:
        return "the proof file does not exist"
    if not path.is_file() or stat.st_size <= 0:
        return "the proof file is empty"
    if stat.st_mtime < goal["created"]:
        return "the proof file is older than the goal"
    return ""


def complete(store: LifeStore, goal_id: int, proof, *, life=None, emotion=None, now: float | None = None) -> dict:
    """Finish a goal. Refused without real proof (GoalError says why); the same file never proves two goals."""
    goal = get(store, goal_id)
    if goal is None or not is_open(goal):
        raise GoalError("that goal is not open")
    why = check_proof(goal, proof)
    if why:
        raise GoalError(why)
    ref = str(proof.get("ref") or proof.get("name"))
    if proof["kind"] != "test" and store.rows("SELECT 1 FROM goals WHERE proof = ? AND status = 'done'", (ref,)):
        raise GoalError("that file already proved another goal")
    now = store.clock() if now is None else now
    store.run("UPDATE goals SET status = 'done', closed = ?, proof = ? WHERE id = ?", (now, ref, goal_id))
    _log(store, goal_id, "done", f"proof: {proof['kind']}", True, ref, now)
    nudge_skill(store, goal["skill"], 1.0, 0.3, now)
    _home_goal(life, goal, "done")
    _feel(emotion, "creative_done" if goal["domain"] in ("drawing", "music", "build") else "task_success")
    return get(store, goal_id)


def abandon(store: LifeStore, goal_id: int, reason: str, *, life=None, now: float | None = None) -> dict:
    reason = " ".join(str(reason or "").split())[:200]
    if len(reason) < MIN_REASON:
        raise GoalError("giving a goal up needs a reason")
    goal = get(store, goal_id)
    if goal is None or not is_open(goal):
        raise GoalError("that goal is not open")
    now = store.clock() if now is None else now
    store.run("UPDATE goals SET status = 'abandoned', closed = ?, reason = ? WHERE id = ?", (now, reason, goal_id))
    _log(store, goal_id, "abandoned", reason, now=now)
    nudge_skill(store, goal["skill"], 0.4, 0.05, now)          # a small dent: a goal she dropped is not evidence of skill
    _home_goal(life, goal, "dropped")
    return get(store, goal_id)


def sweep(store: LifeStore, now: float | None = None, *, life=None) -> list[dict]:
    """Abandon goals that nobody touched for a whole week past their due date, saying so."""
    now = store.clock() if now is None else now
    out = []
    for goal in goals(store, ("open", "active")):
        if now > goal["due"] + GRACE_DAYS * 86400 and (not goal["last_day"] or
                                                       goal["last_day"] < day_of(goal["due"])):
            out.append(abandon(store, goal["id"], "the week ran out and I did not get to it", life=life, now=now))
    return out


def _home_goal(life, goal: dict, status: str) -> None:
    if life is not None and goal["home_goal"]:
        try:
            life.set_goal(goal["home_goal"], status)
        except Exception:
            pass


def _feel(emotion, kind: str) -> None:
    try:
        if emotion is None:
            from .. import emotion as emotion_module
            emotion = emotion_module
        emotion.on_event(kind, strength=0.9, detail="a goal of hers is done", only_if_enabled=True)
    except Exception:
        pass


# ---- telling the owner ----------------------------------------------------------------------------------------
def proof_from_outcome(goal: dict, outcome: dict, *, root: Path | None = None) -> dict | None:
    """The proof a finished activity really produced, or None: `outcome["proof"]` if it set one, else the newest media file
    named in its evidence that exists. Nothing is made up here; `check_proof` still decides."""
    if isinstance(outcome.get("proof"), dict):
        return outcome["proof"]
    want = MEDIA.get(goal["proof_kind"])
    if not want:
        return None
    for item in reversed([str(e) for e in outcome.get("evidence", [])]):
        for piece in re.split(r"[\s;,|]+", item):
            path = Path(piece.strip("'\""))
            if path.suffix.lower() in want and path.is_file():
                return {"kind": goal["proof_kind"], "ref": str(path)}
    return None


def announcement(goal: dict) -> tuple[str, str]:
    """(a plain sentence, the note for the model) about a finished goal, with the proof's reference."""
    kind = "test" if goal["proof_kind"] == "test" else goal["proof_kind"]
    proof = goal["proof"]
    sentence = f"I did it: {goal['text']}" + (f" The {kind} is here: {proof}" if kind != "test" else
                                                f" The test that proves it passed: {proof}")
    note = (f"(she reached a goal of her own and may tell the owner now, with the proof; only these facts: "
            f"{goal['text']}; proof is a {kind}: {proof}; she practised {goal['tries']} times, best streak "
            f"{goal['best_streak']} days)")
    return sentence, note


def goals_note(home=None, *, store: LifeStore | None = None, force: bool = False):
    """The goals' part of the chat note: a finished goal she has not told the owner about yet. Never raises."""
    from .scrapbook import Note
    try:
        if not (force or flag("life_goals_enabled", home)):
            return Note()
        store = store or default_store(home)
        for goal in goals(store, "done"):
            if not goal["announced"]:
                text, note = announcement(goal)
                return Note(note, [text], [lambda gid=goal["id"]: store.run("UPDATE goals SET announced = 1 WHERE id = ?", (gid,))])
        return Note()
    except Exception:
        return Note()
