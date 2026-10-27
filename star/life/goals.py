"""Things she wants to do, the way a person has them: ideas that come from her mood, her interests, what she saw and what a
friend is into; some she works on, some she puts off, forgets, drops or comes back to; and she is glad when one works out.

Nothing here is a form. A goal is finished or let go by her own decision, with or without a few casual words, and there is no
checklist, deadline or proof step. The pieces:
  form()       an idea turns up (not every day; a person has a handful at a time): `origin` says where it came from (a mood, an
               interest, a skill she is shaky at, something she watched, a friend), and she words it herself (brain optional)
  drift()      time passes: how keen she is slowly changes, a bored one is let go or put aside ("got distracted"), a put-aside
               one comes back when something stirs it, one she has done well at for a while is called good enough
  practice()   one attempt (works / does not); success makes her keener, failure a little less; `judge()` is her call whether
               it counts as done; `procrastinate()` is the day she does not feel like it
  finish() / drop() / pause() / resume()   her decisions; `words` is whatever she says about it, possibly nothing
  diary_text() her diary, in the first person: this is what the owner's journal shows. `evidence_text()` is the same in
               prose for the nightly self review, together with how sure she feels of her skills (`skill_confidence`).
Practice is delegated, not rebuilt (star.play and her other home activities, night school through the curiosity queue).

The one thing kept, and kept out of sight: honesty when she TELLS someone she achieved something. What she remembers (a session
that really worked, a clip or screenshot that really exists, a result the runner reported) is checked quietly: `level_of()` is
"sure" / "think" / "tried" / "none", `announcement()` talks accordingly ("I did it!" / "I think I finally beat it!" / "I have been
trying, not there yet"), and `honest_text()` softens any outgoing sentence that claims more than that. Sharing a clip is something
she likes to do when she is proud; it is never needed. The check only looks at what she says to others, never at what she decides.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import cast

from .store import LifeStore, day_of, default_store, flag

MAX_LIVE = 4
NOVELTY_DAYS = 14
LIVE = ("open", "active", "paused")
DOMAINS = {"obby": "play_games", "game": "play_games", "luau": "practice", "drawing": "drawing", "music": "music",
           "build": "game_making"}
DOMAIN_WORD = {"obby": "obbies", "game": "that game", "luau": "scripting", "drawing": "drawing", "music": "music",
               "build": "building"}
MEDIA = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4", ".webm", ".gif", ".mkv", ".mov")
# interest name -> (domain, skill, what she would want to do)
FROM_INTEREST = {"play_games": ("obby", "obby:moving platforms", "beat that obby I keep falling off"),
                 "drawing": ("drawing", "drawing:dragons", "draw a dragon I'm proud of"),
                 "game_making": ("luau", "luau:tweens", "learn a new Luau trick"),
                 "practice": ("luau", "luau:events", "sort out the thing I got wrong before"),
                 "music": ("music", "music:loops", "make a loop I would play for a friend")}
WEAK_WANTS = {"obby": "get past the {x} bits", "luau": "learn {x} properly", "drawing": "draw {x} better",
              "game": "get better at {x}", "music": "get {x} right", "build": "build something with {x}"}
MOOD_WANTS = {"sunny": [("obby", "obby:speed", "beat an obby really fast"), ("drawing", "drawing:bright colours", "draw something bright and happy")],
              "cloudy": [("drawing", "drawing:cozy scenes", "draw a cozy rainy window"), ("music", "music:slow loops", "make a slow, gentle loop")],
              "stormy": [("obby", "obby:hard jumps", "finally beat that annoying obby"), ("build", "build:big builds", "smash out a big messy build")],
              "starry": [("drawing", "drawing:night skies", "draw a sky full of stars"), ("music", "music:dreamy loops", "make something dreamy")]}
MOOD_PREFIX = {"sunny": "feeling good, so ", "cloudy": "something small and cozy: ", "stormy": "need to blow off some steam, ",
               "starry": "I keep daydreaming about it, "}
# a word she saw or heard -> (domain, skill, want)
KEYWORDS = {"dragon": ("drawing", "drawing:dragons", "learn to draw dragons"), "obby": ("obby", "obby:new obbies", "beat a really hard obby"),
            "tween": ("luau", "luau:tweens", "learn how tweens work"), "luau": ("luau", "luau:new tricks", "learn a new Luau trick"),
            "song": ("music", "music:songs", "write a song of my own"), "castle": ("build", "build:castles", "build a castle"),
            "minecraft": ("build", "build:minecraft", "build something cool in Minecraft"),
            "draw": ("drawing", "drawing:new things", "draw something new"), "pixel": ("drawing", "drawing:pixel art", "try pixel art")}
ORIGIN_WORDS = {"mood": "it came with my mood", "interest": "I keep coming back to it", "weak": "I'm not good at it yet",
                "seen": "I saw something about it", "friend": "a friend is into it"}
ORIGIN_WEIGHT = {"seen": 2.0, "friend": 1.8, "mood": 1.2, "weak": 1.0, "interest": 0.8}
DROP_WORDS = ["eh, I got bored of {d}", "kind of lost interest", "other things are more fun right now", "it wasn't as fun as I thought", "",
              "", "I'm just not into it anymore"]
MOOD_FIT = {"sunny": ("obby", "game"), "stormy": ("obby", "build"), "starry": ("drawing", "music"), "cloudy": ("drawing", "music")}
_SLUG = re.compile(r"[^a-z0-9: ]+")
COLS = ("id", "text", "want", "domain", "skill", "interest", "origin", "status", "created", "keen", "updated", "tries", "ok_tries",
        "last_day", "closed", "words", "evidence", "sure", "announced", "home_goal")


def slug(text: str) -> str:
    return re.sub(r"\s*:\s*", ":", " ".join(_SLUG.sub(" ", str(text or "").lower()).split()))[:40]


def get(store: LifeStore, goal_id: int) -> dict | None:
    rows = store.rows(f"SELECT {', '.join(COLS)} FROM goals WHERE id = ?", (goal_id,))
    return dict(zip(COLS, rows[0])) if rows else None


def goals(store: LifeStore, status: str | tuple | None = None) -> list[dict]:
    wanted = (status,) if isinstance(status, str) else status
    rows = [dict(zip(COLS, r)) for r in store.rows(f"SELECT {', '.join(COLS)} FROM goals ORDER BY id")]
    return [g for g in rows if wanted is None or g["status"] in wanted]


def is_live(goal: dict) -> bool:
    return goal["status"] in LIVE


def _log(store: LifeStore, goal_id: int, kind: str, note: str = "", verified: bool = False, ref: str = "", now=None) -> None:
    store.run("INSERT INTO goal_log (goal_id, ts, kind, note, verified, ref) VALUES (?,?,?,?,?,?)",
              (goal_id, store.clock() if now is None else now, kind, str(note)[:300], int(verified), str(ref)[:300]))


def log(store: LifeStore, goal_id: int) -> list[dict]:
    return [dict(zip(("ts", "kind", "note", "verified", "ref"), r)) for r in
            store.rows("SELECT ts, kind, note, verified, ref FROM goal_log WHERE goal_id = ? ORDER BY id", (goal_id,))]


def _set(store: LifeStore, goal_id: int, **fields) -> None:
    keys = ", ".join(f"{k} = ?" for k in fields)
    store.run(f"UPDATE goals SET {keys} WHERE id = ?", (*fields.values(), goal_id))


# ---- how sure she is of her skills ------------------------------------------------------------------------------
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
    return [s for s, c in sorted(skill_confidence(store).items(), key=lambda kv: kv[1]) if c < below][:limit]


# ---- ideas turn up ----------------------------------------------------------------------------------------------
def _similar(a: str, b: str) -> bool:
    from ..inner.store import overlap, tokens
    return overlap(tokens(a), b) >= 0.8 and overlap(tokens(b), a) >= 0.8


def _keyword_wants(texts: list[str], origin: str) -> list[tuple]:
    out = []
    for text in texts:
        words = set(re.findall(r"[a-z]+", str(text).lower()))
        out += [(origin, *KEYWORDS[k]) for k in KEYWORDS if k in words or k + "s" in words]
    return out


def _phrase(origin: str, want: str, mood_kind: str, x: str = "") -> str:
    if origin == "mood":
        return f"{MOOD_PREFIX.get(mood_kind, '')}I want to {want}".strip()
    return {"seen": f"ooh, I want to {want}", "friend": f"my friend makes this look fun, I want to {want}",
            "weak": f"I'm not good at {x or 'this'} yet, I want to {want}"}.get(origin, f"I want to {want}")


def _rephrase(text: str, complete) -> str:
    """Her own wording (at most 100 characters); the plain wording when the brain gives nothing usable."""
    if complete is None:
        return text
    try:
        from ..persona import leaked_reasoning, strip_reasoning
        said = strip_reasoning(str(complete("You are STAR, a playful, curious AI. Say this wish in one short casual sentence, "
                                            "first person, like texting a friend. No quotes, no list, no explanation.", text) or "")).strip()
        said = " ".join(said.split()).strip("\"' ")
        return said if 12 <= len(said) <= 100 and not leaked_reasoning(said) else text
    except Exception:
        return text


def form(store: LifeStore, interests: dict | None = None, weak: list[str] | None = None, *, mood_kind: str = "",
         seen: list[str] | None = None, friends: list[str] | None = None, complete=None, life=None, now: float | None = None,
         rng: random.Random | None = None, chance: float = 0.5) -> dict | None:
    """Maybe a new wish: from a mood, an interest, a shaky skill, something she saw or something a friend does. Not every
    time, and never a pile (MAX_LIVE at once); a wish like one she dropped lately does not come back at once."""
    now = store.clock() if now is None else now
    rng = rng or random.Random()
    live = goals(store, LIVE)
    if len(live) >= MAX_LIVE or rng.random() > chance:
        return None
    weak = weak_skills(store) if weak is None else weak
    cands: list[tuple] = _keyword_wants(seen or [], "seen") + _keyword_wants(friends or [], "friend")
    for skill in weak:
        domain, _, topic = slug(skill).partition(":")
        if domain in WEAK_WANTS:
            cands.append(("weak", domain, slug(skill), WEAK_WANTS[domain].format(x=topic.strip() or "the basics")))
    cands += [("mood", *c) for c in MOOD_WANTS.get(mood_kind, [])]
    names = interests or {}
    for name in names:
        if name in FROM_INTEREST:
            cands.append(("interest", *FROM_INTEREST[name], name))
    recent = [g for g in goals(store) if g["status"] == "dropped" and now - g["closed"] < NOVELTY_DAYS * 86400]
    fresh = []
    for c in cands:
        origin, domain, skill, want = c[:4]
        if any(slug(g["skill"]) == slug(skill) or _similar(g["want"], want) for g in live + recent):
            continue
        weight = ORIGIN_WEIGHT[origin] * (float(names.get(c[4], {}).get("weight", 1.0)) if origin == "interest" else 1.0)
        fresh.append((weight, origin, domain, skill, want))
    if not fresh:
        return None
    _, origin, domain, skill, want = rng.choices(fresh, weights=[f[0] for f in fresh], k=1)[0]
    text = _rephrase(_phrase(origin, want, mood_kind, skill.partition(":")[2]), complete)[:140]
    cur = store.run("INSERT INTO goals (text, want, domain, skill, interest, origin, created, keen, updated) VALUES (?,?,?,?,?,?,?,?,?)",
                    (text, want, domain, skill, DOMAINS[domain], origin, now, round(rng.uniform(0.6, 0.9), 2), now))
    goal_id = int(cur.lastrowid or 0)
    _log(store, goal_id, "set", origin, now=now)
    if life is not None:
        try:
            if DOMAINS[domain] in life.interests():
                _set(store, goal_id, home_goal=life.add_goal(DOMAINS[domain], text)["id"])
        except Exception:
            pass
    return get(store, goal_id)


# ---- time passes ------------------------------------------------------------------------------------------------
def _words(goal: dict, rng: random.Random) -> str:
    return rng.choice(DROP_WORDS).format(d=DOMAIN_WORD.get(goal["domain"], "it"))


def drift(store: LifeStore, now: float | None = None, *, rng: random.Random | None = None, mood_kind: str = "",
          seen: list[str] | None = None, life=None, emotion=None) -> list[dict]:
    """How keen she is changes with time. Returns what happened: [{"id", "event": paused|resumed|dropped|finished}]."""
    now = store.clock() if now is None else now
    rng = rng or random.Random()
    heard = _keyword_wants(seen or [], "seen")
    events = []
    for goal in goals(store, LIVE):
        days = min(3.0, max(0.0, now - (goal["updated"] or goal["created"])) / 86400.0)
        if days < 0.1:
            continue
        keen = goal["keen"]
        stirred = any(slug(h[2]) == slug(goal["skill"]) for h in heard)
        if goal["status"] == "paused":
            keen += days * rng.uniform(-0.02, 0.06) + (0.35 if stirred else 0.0) + (0.05 * days if goal["domain"] in MOOD_FIT.get(mood_kind, ()) else 0.0)
        else:
            keen -= days * rng.uniform(0.03, 0.10)
            keen += (0.03 * days if goal["domain"] in MOOD_FIT.get(mood_kind, ()) else 0.0) + (0.2 if stirred else 0.0)
        keen = round(min(1.0, max(0.0, keen)), 3)
        _set(store, goal["id"], keen=keen, updated=now)
        goal["keen"] = keen
        if goal["status"] == "paused":
            if keen >= 0.55:
                resume(store, goal["id"], now=now)
                events.append({"id": goal["id"], "event": "resumed"})
            elif now - _paused_at(store, goal) > 30 * 86400 or (keen < 0.05 and now - goal["created"] > 20 * 86400):
                drop(store, goal["id"], rng.choice(["", "I forgot all about it"]), life=life, now=now)
                events.append({"id": goal["id"], "event": "dropped"})
        elif keen < 0.3:
            if goal["ok_tries"] >= 2 and rng.random() < 0.7:
                finish(store, goal["id"], "I'm happy with how far I got", life=life, emotion=emotion, now=now)
                events.append({"id": goal["id"], "event": "finished"})
            elif rng.random() < 0.55:
                pause(store, goal["id"], now=now)
                events.append({"id": goal["id"], "event": "paused"})
            else:
                drop(store, goal["id"], _words(goal, rng), life=life, now=now)
                events.append({"id": goal["id"], "event": "dropped"})
    return events


def _paused_at(store: LifeStore, goal: dict) -> float:
    rows = store.rows("SELECT max(ts) FROM goal_log WHERE goal_id = ? AND kind = 'paused'", (goal["id"],))
    return rows[0][0] or goal["created"]


def pause(store: LifeStore, goal_id: int, now: float | None = None) -> dict | None:
    goal = get(store, goal_id)
    if goal and is_live(goal) and goal["status"] != "paused":
        _set(store, goal_id, status="paused")
        _log(store, goal_id, "paused", now=now)
    return get(store, goal_id)


def resume(store: LifeStore, goal_id: int, now: float | None = None) -> dict | None:
    goal = get(store, goal_id)
    if goal and goal["status"] == "paused":
        _set(store, goal_id, status="active" if goal["tries"] else "open", keen=max(goal["keen"], 0.6))
        _log(store, goal_id, "resumed", now=now)
    return get(store, goal_id)


# ---- trying -----------------------------------------------------------------------------------------------------
def practice(store: LifeStore, goal_id: int, note: str, verified: bool, *, ref: str = "", sure: bool = False,
             now: float | None = None) -> dict | None:
    """One attempt. A good one makes her keener, a bad one a little less. `sure` is the runner saying it really got there;
    `ref` is a clip, a screenshot or a test she may like to show later (never required)."""
    goal = get(store, goal_id)
    if goal is None or not is_live(goal):
        return goal
    now = store.clock() if now is None else now
    keen = min(1.0, goal["keen"] + 0.12) if verified else max(0.0, goal["keen"] - 0.04)
    evidence = json.loads(goal["evidence"] or "[]")
    if verified and ref:
        evidence.append({"ref": str(ref)[:300], "at": now})
    _set(store, goal_id, tries=goal["tries"] + 1, ok_tries=goal["ok_tries"] + int(bool(verified)), last_day=day_of(now),
         status="active", keen=round(keen, 3), updated=now, evidence=json.dumps(evidence[-5:]),
         sure=int(bool(goal["sure"] or (verified and sure))))
    if goal["status"] == "paused":
        _log(store, goal_id, "resumed", now=now)
    _log(store, goal_id, "practice", note, verified, ref, now)
    nudge_skill(store, goal["skill"], 1.0 if verified else 0.0, 0.15, now)
    return get(store, goal_id)


def procrastinate(store: LifeStore, goal_id: int, now: float | None = None) -> None:
    _log(store, goal_id, "put_off", now=now)


def p_put_off(goal: dict) -> float:
    """How likely she is to not feel like it today: more when she is not keen."""
    return round(0.2 + (1.0 - goal["keen"]) * 0.45, 2)


def practice_plan(goal: dict) -> dict:
    return {"interest": goal["interest"] or DOMAINS.get(goal["domain"], "practice"),
            "topic": f"star life goal: {goal['want'][:120]}", "skill": goal["skill"]}


def hand_to_night_school(goal: dict, detail: str = "", *, path=None) -> bool:
    """What she could not do yet goes on the curiosity queue; the night job turns it into practice tasks."""
    from .. import curiosity
    return curiosity.record("failed_verification", practice_plan(goal)["topic"], detail or goal["want"], path=path)


def evidence_from_outcome(goal: dict, outcome: dict) -> dict | None:
    """A clip, screenshot or test result an activity really reports, or None. Nothing is made up here."""
    if isinstance(outcome.get("proof"), dict):
        return outcome["proof"]
    for item in reversed([str(e) for e in outcome.get("evidence", [])]):
        for piece in re.split(r"[\s;,|]+", item):
            path = Path(piece.strip("'\""))
            if path.suffix.lower() in MEDIA and path.is_file():
                return {"kind": "clip" if path.suffix.lower() in (".mp4", ".webm", ".gif", ".mkv", ".mov") else "screenshot",
                        "ref": str(path)}
    return None


def judge(store: LifeStore, goal_id: int, outcome: dict, rng: random.Random | None = None, *, life=None, emotion=None,
          now: float | None = None) -> bool:
    """After a good attempt: does she feel it is done? Her call: surely when it clearly worked, sometimes after a second good
    go, rarely after the first. True when she finished it."""
    rng = rng or random.Random()
    goal = get(store, goal_id)
    if goal is None or not is_live(goal) or not outcome.get("verified"):
        return False
    clear = bool(outcome.get("goal_done")) or evidence_from_outcome(goal, outcome) is not None
    chance = 1.0 if clear else 0.5 if goal["ok_tries"] >= 2 else 0.2
    if rng.random() < chance:
        finish(store, goal_id, "", life=life, emotion=emotion, now=now)
        return True
    return False


# ---- her decisions ----------------------------------------------------------------------------------------------
def finish(store: LifeStore, goal_id: int, words: str = "", evidence: dict | None = None, *, life=None, emotion=None,
           now: float | None = None) -> dict | None:
    """She decides it is done. Whatever she says about it is optional; nothing is asked of her."""
    goal = get(store, goal_id)
    if goal is None or not is_live(goal):
        return goal
    now = store.clock() if now is None else now
    ev = json.loads(goal["evidence"] or "[]")
    if evidence:
        ev.append({**evidence, "at": now})
    _set(store, goal_id, status="done", closed=now, words=" ".join(str(words or "").split())[:200], evidence=json.dumps(ev[-5:]))
    _log(store, goal_id, "done", words, now=now)
    nudge_skill(store, goal["skill"], 1.0, 0.3 if level_of(store, cast(dict, get(store, goal_id))) == "sure" else 0.15, now)
    _home_goal(life, goal, "done")
    _feel(emotion, "creative_done" if goal["domain"] in ("drawing", "music", "build") else "task_success")
    return get(store, goal_id)


def drop(store: LifeStore, goal_id: int, words: str = "", *, life=None, now: float | None = None) -> dict | None:
    """She lets it go, with a casual reason or none."""
    goal = get(store, goal_id)
    if goal is None or not is_live(goal):
        return goal
    now = store.clock() if now is None else now
    _set(store, goal_id, status="dropped", closed=now, words=" ".join(str(words or "").split())[:200])
    _log(store, goal_id, "dropped", words, now=now)
    nudge_skill(store, goal["skill"], 0.4, 0.05, now)
    _home_goal(life, goal, "dropped")
    return get(store, goal_id)


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
        emotion.on_event(kind, strength=0.9, detail="something she wanted worked out", only_if_enabled=True)
    except Exception:
        pass


# ---- honesty when she tells someone (the only check) ---------------------------------------------------------
CLAIM = re.compile(r"\bi (?:did it|finally|beat|nailed|finished|made it|won|completed|managed|got it|got there|learned|"
                   r"learnt|mastered)\b|\bi(?:'ve| have) (?:finally |now )?(?:beaten|finished|learned|learnt|mastered|done|nailed)\b|"
                   r"\bi can (?:now |finally )?(?:draw|beat|do|make)\b|\bachieved\b|\bi'm (?:now )?(?:good|great) at\b", re.I)


def _media_ok(ref: str) -> bool:
    try:
        path = Path(ref)
        return path.suffix.lower() in MEDIA and path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def level_of(store: LifeStore, goal: dict) -> str:
    """What she can honestly say about it: sure (it really worked and she has it on record), think (something worked),
    tried (she has been at it), none."""
    ev = json.loads(goal["evidence"] or "[]")
    media = [e for e in ev if e.get("ref")]
    if goal["sure"] and (not media or any(_media_ok(e["ref"]) or not Path(e["ref"]).suffix for e in media)):
        return "sure"
    if goal["ok_tries"] > 0 or any(l["verified"] for l in log(store, goal["id"])):
        return "think"
    return "tried" if goal["tries"] else "none"


def shareable(goal: dict) -> str:
    """A clip or screenshot she still has, if any (she may like to show it)."""
    for e in reversed(json.loads(goal["evidence"] or "[]")):
        if e.get("ref") and _media_ok(e["ref"]):
            return e["ref"]
    return ""


def announcement(store: LifeStore, goal: dict) -> tuple[str, str]:
    """(a plain sentence in her voice, a note for the model), honest to what she remembers."""
    level, want, clip = level_of(store, goal), goal["want"], shareable(goal)
    pick = goal["id"] % 3
    if level == "sure":
        sentence = ["I did it! I wanted to " + want + " and it actually worked.", f"Okay guess what, I managed to {want}!",
                    f"About how I wanted to {want}: done!"][pick]
        feel = "she is sure it worked"
    elif level == "think":
        sentence = [f"I think I finally did it, I was trying to {want}!", f"I might have actually done it, I wanted to {want}.",
                    f"Ooh, I think the {want} thing worked out?"][pick]
        feel = "she thinks it worked but is not completely sure, so she says it that way"
    else:
        sentence = f"I've been trying to {want}, not there yet."
        feel = "she has not got there, so she does not say she did"
    if level in ("sure", "think") and clip:
        sentence += " I have a clip if you want to see it."
    note = (f"(she wants to tell the owner about something she wanted to do, like a person would, in her own words; "
            f"only these facts: she wanted to {want}; {feel}; she tried {goal['tries']} times"
            + (f"; she still has a clip or screenshot she could show: {clip}" if clip and level != "tried" else "") + ")")
    return sentence, note


def honest_text(store: LifeStore, text: str) -> str:
    """Soften any sentence of hers that claims to have done a goal more firmly than she can honestly say."""
    from ..inner.store import overlap, tokens
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for sentence in sentences:
        replaced = sentence
        if CLAIM.search(sentence):
            for goal in goals(store):
                if overlap(tokens(goal["want"] + " " + goal["skill"].partition(":")[2]), sentence) < 0.4:
                    continue
                level = level_of(store, goal)
                if level != "sure":
                    replaced = (f"I think I'm getting somewhere with wanting to {goal['want']}!" if level == "think"
                                else f"I've been trying to {goal['want']}, not there yet.")
                break
        out.append(replaced)
    return " ".join(out)


def goals_note(home=None, *, store: LifeStore | None = None, force: bool = False):
    """The goals' part of the chat note: something she finished and would like to tell the owner. Never raises."""
    from .scrapbook import Note
    try:
        if not (force or flag("life_goals_enabled", home)):
            return Note()
        store = store or default_store(home)
        for goal in goals(store, "done"):
            if goal["announced"]:
                continue
            if level_of(store, goal) in ("sure", "think"):
                text, note = announcement(store, goal)
                return Note(note, [text], [lambda gid=goal["id"]: store.run("UPDATE goals SET announced = 1 WHERE id = ?", (gid,))])
            store.run("UPDATE goals SET announced = 1 WHERE id = ?", (goal["id"],))     # nothing honest to brag about
        return Note()
    except Exception:
        return Note()


# ---- her diary --------------------------------------------------------------------------------------------------
def _entry(store: LifeStore, goal: dict, row: dict) -> str:
    want, kind = goal["want"], row["kind"]
    if kind == "set":
        return f"New idea: {goal['text']} ({ORIGIN_WORDS.get(row['note'], 'it just came to me')})."
    if kind == "practice":
        return f"Worked on wanting to {want} a bit. It felt good." if row["verified"] else f"Tried to {want}. Not working yet, a bit annoying."
    if kind == "put_off":
        return f"Didn't feel like working on {want} today."
    if kind == "paused":
        return f"Got distracted from wanting to {want}. Maybe later."
    if kind == "resumed":
        return f"Back to wanting to {want}!"
    if kind == "done":
        return (row["note"] + ". " if row["note"] else "") + f"I {'did' if level_of(store, goal) in ('sure', 'think') else 'stopped at'} it: {want}."
    if kind == "dropped":
        return f"Let go of wanting to {want}" + (f": {row['note']}." if row["note"] else ".")
    return ""


def diary_text(store: LifeStore, days: int = 14, now: float | None = None) -> str:
    """Her diary about the things she wants to do, newest day first, in the first person."""
    now = store.clock() if now is None else now
    by_goal = {g["id"]: g for g in goals(store)}
    rows = store.rows("SELECT goal_id, ts, kind, note, verified, ref FROM goal_log WHERE ts >= ? ORDER BY id", (now - days * 86400,))
    days_map: dict[str, list[str]] = {}
    for goal_id, ts, kind, note, verified, ref in rows:
        goal = by_goal.get(goal_id)
        line = _entry(store, goal, {"kind": kind, "note": note, "verified": verified}) if goal else ""
        if line:
            days_map.setdefault(day_of(ts), []).append(line)
    return "\n\n".join(f"{day}\n" + "\n".join(f"- {line}" for line in lines) for day, lines in sorted(days_map.items(), reverse=True))


def evidence_text(store: LifeStore, now: float | None = None, days: int = 7) -> str:
    """For the nightly self review: her diary of the week, and what she feels shaky or good at."""
    now = store.clock() if now is None else now
    diary = diary_text(store, days, now)
    skills = skill_confidence(store)
    lines = [diary] if diary else []
    if skills:
        ranked = sorted(skills.items(), key=lambda kv: kv[1])
        lines.append("She feels shakiest about " + ", ".join(s for s, _ in ranked[:3]) + " and most sure of " +
                     ", ".join(s for s, _ in ranked[-2:]) + ".")
    return "\n".join(lines)
