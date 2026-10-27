"""Friendships that grow and fade: met -> acquaintance -> friend -> close friend, from what really happened.

Points come from real interactions only: a new conversation (a gap of 30 minutes starts one), the lines in it (a capped
amount per conversation), a game played together (once per game and day), and positive moments (thanks, laughs, "gg",
at most three a day). Hostile lines cost points. Apart from each other the score halves every few weeks (slower for
closer friends), so a friend she has not talked to for months drifts back down; the first message after a long gap
is a reunion and she greets them like one. Each stage needs the score AND enough separate conversations, and the
step up to close friend also needs shared games or many positive moments: one long chat never makes a friend.

Per person she also keeps: what she calls them (a nickname, or the name they asked for), inside jokes (a funny line that
came back in another moment, with the two lines as evidence), shared memories (games together, becoming friends), what
they like (friend memory's interest facts), the last thing they talked about, and one thing to ask about next time
("did you beat level 5 yet?", asked once, within two weeks, on the next conversation).

The legacy `relationship` flag of friend memory stays `met | friend` and follows the stage (friend and close friend are
"friend"), so everything that already reads it keeps working. Rules that hold for the memory hold here: no chat text
about someone who may be a minor, and nothing from Roblox chat, is kept; only game names and interests. Everything is
deleted with the person ("forget me", across all their platforms). Optional: important new memories are also pushed to
the brain's memory stream when `star.brain` offers one.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from . import rules
from .friends import _INTEREST, _SENSITIVE, FriendMemory, Person, extract_facts

STAGES = ("met", "acquaintance", "friend", "close_friend")
LABEL = {"met": "someone she just met", "acquaintance": "an acquaintance", "friend": "a friend",
         "close_friend": "a close friend"}
THRESHOLD = {"acquaintance": 8.0, "friend": 25.0, "close_friend": 60.0}
MIN_CONVOS = {"acquaintance": 1, "friend": 3, "close_friend": 8}
HALF_LIFE_DAYS = {"met": 10.0, "acquaintance": 21.0, "friend": 60.0, "close_friend": 120.0}
GRACE_DAYS = 7.0                 # no decay in the first week apart
DEMOTE_FACTOR = 0.6              # a stage is kept until the score falls below 60 % of what it took to reach it
CONVO_GAP_S = 30 * 60
CONVO_POINTS = 3.0
LINE_POINTS = 0.5
CONV_LINE_CAP = 6.0
POSITIVE_POINTS = 1.5
POSITIVES_PER_DAY = 3
NEGATIVE_POINTS = 3.0
GAME_POINTS = 4.0
REUNION_AFTER_S = 3 * 24 * 3600
FOLLOWUP_MIN_AGE_S = 20 * 60
FOLLOWUP_MAX_AGE_S = 14 * 24 * 3600
JOKE_GAP_S = 10 * 60
MAX_JOKES, MAX_CANDIDATES, MAX_MEMORIES = 8, 12, 30

POSITIVE = re.compile(r"\b(?:thanks?|thank\s+you|thx|ty|gg(?:wp)?|good\s+game|so\s+fun|that\s+was\s+fun|fun\s+(?:game|time)|"
                      r"love\s+(?:this|that|it|playing)|you(?:'re|\s+are)\s+(?:the\s+best|awesome|amazing|so\s+nice|sweet|funny)|"
                      r"nice\s+one|well\s+done|appreciate|glad\s+(?:you|we)|best\s+day|lol|lmao|haha+|hehe+)\b|[😂🤣😄😁🥰❤🙏]", re.I)
STRONG_POSITIVE = re.compile(r"\b(?:thank\s+you\s+so\s+much|best\s+day|that\s+was\s+(?:so\s+)?fun|you(?:'re|\s+are)\s+the\s+best|"
                             r"so\s+glad\s+(?:you|we)|love\s+playing\s+with\s+you)\b", re.I)
NEGATIVE = re.compile(r"\b(?:shut\s+up|stupid|idiot|annoying|i\s+hate\s+you|hate\s+you|loser|trash|go\s+away|ugly|"
                      r"you\s+suck|kys|noob\s+bot)\b", re.I)
LAUGH = re.compile(r"\b(?:lol|lmao|lmfao|rofl|haha+|hehe+|hahaha+)\b|[😂🤣💀]", re.I)
CALL_ME = re.compile(r"\bcall\s+me\s+([A-Za-z][\w'-]{1,19})\b", re.I)

_PLAN = re.compile(r"\b(?:trying|tryna|gonna\s+try|going\s+to\s+try|want|wanna|about|planning|hoping)\s+to\s+"
                   r"(beat|clear|win|finish|complete|unlock|reach|get|build|make|learn)\s+(?:(the|a|my)\s+)?"
                   r"([a-z0-9' -]{3,40}?)(?=\s+(?:but|and|later|tomorrow|tonight|after|today|soon|this)\b|[.,!?]|$)", re.I)
_STUCK = re.compile(r"\bstuck\s+(?:on|at|in)\s+(?:(the|my)\s+)?([a-z0-9' -]{3,40}?)(?=\s+(?:but|and|for|again)\b|[.,!?]|$)", re.I)
_EVENT = re.compile(r"\b(?:i\s+have|i\s+got|i'?ve\s+got|starting|taking)\s+(?:a|an|my)\s+([a-z' -]{3,30}?)\s+"
                    r"(?:tomorrow|tonight|today|on\s+\w+day|next\s+week)\b", re.I)
_QUESTION = {"beat": "did you beat {o} yet?", "clear": "did you clear {o} yet?", "win": "did you win {o}?",
             "finish": "did you finish {o}?", "complete": "did you finish {o}?", "unlock": "did you unlock {o}?",
             "reach": "did you reach {o}?", "get": "did you get {o} yet?", "build": "how's {o} coming along?",
             "make": "how's {o} coming along?", "learn": "how's learning {o} going?", "stuck": "did you get past {o}?",
             "event": "how did {o} go?"}
_STOP = {"that", "this", "with", "have", "just", "like", "they", "them", "then", "than", "what", "when", "were", "will",
         "your", "from", "about", "there", "their", "would", "could", "really", "very", "haha", "lmao", "the", "and"}


@dataclass
class Bond:
    stage: str = "met"
    score: float = 0.0
    convos: int = 0
    shared_games: int = 0
    positives: int = 0
    lines: int = 0
    last_seen: float = 0.0
    nickname: str = ""
    last_topic: str = ""
    last_topic_ts: float = 0.0

    @property
    def label(self) -> str:
        return LABEL[self.stage]


@dataclass(frozen=True)
class Touch:
    """What one incoming line from a person changed (returned before she answers, so the reply can use it)."""
    stage: str = "met"
    previous: str = "met"
    new_conversation: bool = False
    reunion_days: float = 0.0
    reunion_stage: str = "met"
    followup: str = ""            # a question to ask them once (already marked as asked)
    topic: str = ""               # the last thing they talked about, before this message

    @property
    def changed(self) -> bool:
        return self.stage != self.previous

    def hint(self) -> str:
        """The note added to her message for this turn ("" when there is nothing to bring up)."""
        parts = []
        if self.reunion_days >= REUNION_AFTER_S / 86400.0:
            days = int(round(self.reunion_days))
            who = "a close friend" if self.reunion_stage == "close_friend" else "a friend" if self.reunion_stage == "friend" else "someone you know"
            parts.append(f"you have not talked for {days} days: greet them like {who} you are glad to see again"
                         + (f', and you could bring up what they said last time ("{self.topic}")' if self.topic else ""))
        if self.followup:
            parts.append(f'you remember something to ask about, once and lightly, in your own words: "{self.followup}"')
        return f"({'; '.join(parts)})" if parts else ""


def suggest_nickname(name: str) -> str:
    """"xX_MiraBuilds_Xx" -> "Mira": the first real word of a display name, '' when there is none."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name or ""))
    words = [w for w in re.sub(r"[^A-Za-z]+", " ", spaced).split()
             if len(w) >= 3 and w.lower() not in {"the", "real", "official", "pro", "gamer", "gaming", "xxx", "yt"}]
    return words[0].capitalize() if words else ""


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _salient(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']{4,}", str(text or "").lower()) if w not in _STOP}


def _similar(a: set[str], b: set[str]) -> bool:
    return len(a & b) >= 2 and len(a & b) / max(1, len(a | b)) >= 0.5


def content_ok(person: Person, platform: str) -> bool:
    """May what they said be kept as text (jokes, topics, followups)? Not for possible minors, not from Roblox chat."""
    return platform != "roblox" and rules.age_status(person) in ("adult", "unknown")


def followup_from(text: str, *, personal: bool) -> tuple[str, str]:
    """(question, evidence) for something she can ask about next time, or ("", "")."""
    text = " ".join(str(text or "").split())
    found = None
    match = _PLAN.search(text)
    if match:
        verb, det, obj = match.group(1).lower(), (match.group(2) or "").lower(), match.group(3)
        found = (verb, ("your " if det == "my" else f"{det} " if det else "") + obj.strip())
    elif _STUCK.search(text):
        match = _STUCK.search(text)
        found = ("stuck", ("your " if (match.group(1) or "").lower() == "my" else f"{match.group(1)} " if match.group(1) else "")
                 + match.group(2).strip())
    elif personal and _EVENT.search(text):
        found = ("event", "your " + _EVENT.search(text).group(1).strip())
    if not found or _SENSITIVE.search(found[1]):
        return "", ""
    return _QUESTION[found[0]].format(o=found[1].strip()), _clip(text, 120)


class Bonds:
    def __init__(self, memory: FriendMemory, *, sink=..., clock=time.time) -> None:
        self.memory = memory
        self._clock = clock
        self._sink = _default_sink() if sink is ... else sink

    @property
    def _db(self):
        return self.memory._db

    # -- rows -------------------------------------------------------------------------------------------------------
    def _load(self, person: Person) -> dict:
        row = self._db.execute("SELECT * FROM bond WHERE person_id = ?", (person.id,)).fetchone()
        if row is None:
            self._bootstrap(person)
            row = self._db.execute("SELECT * FROM bond WHERE person_id = ?", (person.id,)).fetchone()
        names = [c[1] for c in self._db.execute("PRAGMA table_info(bond)")]
        return dict(zip(names, row))

    def _bootstrap(self, person: Person) -> None:
        """A person who was met before the lifecycle existed starts from what friend memory already says."""
        lines = self._db.execute("SELECT COUNT(*), COALESCE(MAX(ts), 0) FROM moments WHERE person_id = ?", (person.id,)).fetchone()
        exchanges = lines[0] / 2.0
        score = min(CONVO_POINTS + CONV_LINE_CAP, CONVO_POINTS + LINE_POINTS * exchanges) if lines[0] else 0.0
        convos = 1 if lines[0] else 0
        stage = "met"
        if person.relationship == "friend":
            stage, score, convos = "friend", max(score, THRESHOLD["friend"]), max(convos, MIN_CONVOS["friend"])
        self._db.execute("INSERT INTO bond (person_id, stage, score, convos, lines, last_seen, last_decay, stage_changed) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (person.id, stage, score, convos, lines[0], lines[1], lines[1], lines[1]))
        self._db.commit()

    def _save(self, person: Person, b: dict) -> None:
        cols = [k for k in b if k != "person_id"]
        self._db.execute(f"UPDATE bond SET {', '.join(c + ' = ?' for c in cols)} WHERE person_id = ?",
                         [b[c] for c in cols] + [person.id])
        self._db.commit()

    def get(self, person: Person) -> Bond:
        if person.id is None:
            return Bond()
        b = self._load(person)
        return Bond(b["stage"], b["score"], b["convos"], b["shared_games"], b["positives"], b["lines"], b["last_seen"],
                    b["nickname"], b["last_topic"], b["last_topic_ts"])

    def stage(self, person: Person) -> str:
        return self.get(person).stage

    def at_least(self, person: Person, stage: str) -> bool:
        return STAGES.index(self.stage(person)) >= STAGES.index(stage)

    # -- stage machine ----------------------------------------------------------------------------------------------
    def _restage(self, person: Person, b: dict, now: float, *, decaying: bool = False) -> None:
        old = b["stage"]
        i = STAGES.index(old)
        if not decaying and i + 1 < len(STAGES):
            nxt = STAGES[i + 1]
            ready = b["score"] >= THRESHOLD[nxt] and b["convos"] >= MIN_CONVOS[nxt]
            if nxt == "close_friend":
                ready = ready and (b["shared_games"] >= 2 or b["positives"] >= 5)
            if ready:
                b["stage"], b["stage_changed"] = nxt, now
        # a stage is held until the score falls well below what it took to reach it (drifting apart can skip several)
        while STAGES.index(b["stage"]) > 0 and b["score"] < THRESHOLD[b["stage"]] * DEMOTE_FACTOR:
            b["stage"], b["stage_changed"] = STAGES[STAGES.index(b["stage"]) - 1], now
        if b["stage"] != old:
            self._stage_changed(person, old, b["stage"], b, now)

    def _stage_changed(self, person: Person, old: str, new: str, b: dict, now: float) -> None:
        up = STAGES.index(new) > STAGES.index(old)
        friend_like = new in ("friend", "close_friend")
        if (person.relationship == "friend") != friend_like:
            self.memory.update(person, relationship="friend" if friend_like else "met")
        platform = self._platform_of(person)
        self.memory.log("stage_up" if up else "stage_down", platform, person, f"{old} -> {new}")
        if up and new in ("friend", "close_friend"):
            self._remember(person, f"we became {'close friends' if new == 'close_friend' else 'friends'}", "", now,
                           key=f"stage:{new}")
            self._emit(person, f"{person.name} and I became {'close friends' if new == 'close_friend' else 'friends'}")

    def _platform_of(self, person: Person) -> str:
        row = self._db.execute("SELECT platform FROM moments WHERE person_id = ? ORDER BY id DESC LIMIT 1", (person.id,)).fetchone()
        if row:
            return row[0]
        handles = self.memory.handles(person)
        return handles[0][0] if handles else "discord"

    def _decay(self, person: Person, b: dict, now: float) -> None:
        if not b["last_seen"]:
            return
        start = max(b["last_decay"], b["last_seen"] + GRACE_DAYS * 86400)
        if now <= start:
            return
        days = (now - start) / 86400.0
        b["score"] *= 0.5 ** (days / HALF_LIFE_DAYS[b["stage"]])
        b["last_decay"] = now
        self._restage(person, b, now, decaying=True)

    def decay_all(self, now: float | None = None) -> list[tuple[int, str, str]]:
        """The night job: friends she has not talked to drift down even if nobody writes. [(person id, old, new)]."""
        now = self._clock() if now is None else now
        changed = []
        for (pid,) in self._db.execute("SELECT person_id FROM bond").fetchall():
            person = self.memory.get(pid)
            b = self._load(person)
            old = b["stage"]
            self._decay(person, b, now)
            self._save(person, b)
            if b["stage"] != old:
                changed.append((pid, old, b["stage"]))
        return changed

    # -- one incoming line ------------------------------------------------------------------------------------------
    def observe(self, person: Person, platform: str, text: str, *, now: float | None = None, game: str = "") -> Touch:
        """Call for every line a person says to her, before she answers."""
        if person.id is None:
            return Touch()
        now = self._clock() if now is None else now
        text = " ".join(str(text or "").split())
        b = self._load(person)
        if person.relationship == "friend" and STAGES.index(b["stage"]) < 2:      # set by hand (owner, older data)
            b.update(stage="friend", score=max(b["score"], THRESHOLD["friend"]), convos=max(b["convos"], MIN_CONVOS["friend"]),
                     stage_changed=now)
        before = b["stage"]
        gap = now - b["last_seen"] if b["last_seen"] else None
        topic_before = b["last_topic"]
        self._decay(person, b, now)
        new_convo = gap is None or gap > CONVO_GAP_S
        reunion = gap is not None and gap >= REUNION_AFTER_S and STAGES.index(before) >= 1
        if new_convo:
            b["convos"] += 1
            b["score"] += CONVO_POINTS
            b["conv_pts"] = 0.0
        gain = max(0.0, min(LINE_POINTS, CONV_LINE_CAP - b["conv_pts"]))
        b["conv_pts"] += gain
        b["score"] += gain
        b["lines"] += 1
        today = _day(now)
        if b["day"] != today:
            b["day"], b["day_positives"] = today, 0
        if NEGATIVE.search(text):
            b["score"] = max(0.0, b["score"] - NEGATIVE_POINTS)
        elif POSITIVE.search(text) and b["day_positives"] < POSITIVES_PER_DAY:
            b["positives"] += 1
            b["day_positives"] += 1
            b["score"] += POSITIVE_POINTS
        call = CALL_ME.search(text)
        if call:
            b["nickname"], b["nickname_locked"] = call.group(1).capitalize(), 1
        followup = ""
        if new_convo or reunion:
            followup = self._due_followup(person, now)
        keep_text = content_ok(person, platform)
        if keep_text:
            question, evidence = followup_from(text, personal=True)
            if question:
                self._add_item(person, "followup", question, evidence, now, state="open", cap=6)
        topic = self._topic(person, text, game, keep_text)
        if topic:
            b["last_topic"], b["last_topic_ts"] = topic, now
        b["last_seen"] = now
        if game:
            self._shared_game(person, b, platform, game, now)
        self._restage(person, b, now)
        if not b["nickname"] and not b["nickname_locked"] and STAGES.index(b["stage"]) >= 1:
            b["nickname"] = suggest_nickname(person.name)
        self._save(person, b)
        return Touch(b["stage"], before, new_convo, (gap or 0) / 86400.0 if reunion else 0.0, before, followup,
                     topic_before if reunion else "")

    def _topic(self, person: Person, text: str, game: str, keep_text: bool) -> str:
        question, evidence = followup_from(text, personal=False)
        if question:
            return _clip(evidence, 70)
        for fact in extract_facts(text):
            if _INTEREST.match(fact):
                return _clip(_INTEREST.sub("", fact).strip(" ,."), 70) or _clip(fact, 70)
        if keep_text and len(text) >= 24 and not text.endswith("?"):
            return _clip(text, 70)
        return f"playing {game}" if game else ""

    # -- shared games, memories, jokes ------------------------------------------------------------------------------
    def played_together(self, person: Person, platform: str, game: str, *, now: float | None = None) -> bool:
        """She and this person were in the same game (no chat needed). True if it counted (once per game and day)."""
        if person.id is None or not game:
            return False
        now = self._clock() if now is None else now
        b = self._load(person)
        counted = self._shared_game(person, b, platform, game, now)
        self._restage(person, b, now)
        self._save(person, b)
        return counted

    def _shared_game(self, person: Person, b: dict, platform: str, game: str, now: float) -> bool:
        key = f"game:{platform}:{game.lower()[:60]}:{_day(now)}"
        if self._db.execute("SELECT 1 FROM bond_items WHERE person_id = ? AND state = ?", (person.id, key)).fetchone():
            return False
        b["shared_games"] += 1
        b["score"] += GAME_POINTS
        self._remember(person, f"played {game} together on {platform} ({_day(now)})", "", now, key=key)
        return True

    def _add_item(self, person: Person, kind: str, text: str, evidence: str, ts: float, *, state: str = "", cap: int) -> None:
        self._db.execute("INSERT INTO bond_items (person_id, kind, text, evidence, ts, state) VALUES (?, ?, ?, ?, ?, ?)",
                         (person.id, kind, _clip(text, 160), _clip(evidence, 240), ts, state))
        self._db.execute("DELETE FROM bond_items WHERE person_id = ? AND kind = ? AND id NOT IN (SELECT id FROM bond_items "
                         "WHERE person_id = ? AND kind = ? ORDER BY id DESC LIMIT ?)", (person.id, kind, person.id, kind, cap))
        self._db.commit()

    def _remember(self, person: Person, text: str, evidence: str, ts: float, *, key: str) -> None:
        if not self._db.execute("SELECT 1 FROM bond_items WHERE person_id = ? AND state = ?", (person.id, key)).fetchone():
            self._add_item(person, "memory", text, evidence, ts, state=key, cap=MAX_MEMORIES)

    def items(self, person: Person, kind: str, limit: int = 8) -> list[tuple[str, str, float]]:
        if person.id is None:
            return []
        rows = self._db.execute("SELECT text, evidence, ts FROM bond_items WHERE person_id = ? AND kind = ? ORDER BY id DESC LIMIT ?",
                                (person.id, kind, limit)).fetchall()
        return list(reversed(rows))

    def _due_followup(self, person: Person, now: float) -> str:
        """The oldest open question that is neither too fresh (same chat) nor stale; marked asked."""
        row = self._db.execute("SELECT id, text FROM bond_items WHERE person_id = ? AND kind = 'followup' AND state = 'open' "
                               "AND ts <= ? AND ts >= ? ORDER BY id LIMIT 1",
                               (person.id, now - FOLLOWUP_MIN_AGE_S, now - FOLLOWUP_MAX_AGE_S)).fetchone()
        self._db.execute("UPDATE bond_items SET state = 'expired' WHERE person_id = ? AND kind = 'followup' AND state = 'open' AND ts < ?",
                         (person.id, now - FOLLOWUP_MAX_AGE_S))
        if row is None:
            self._db.commit()
            return ""
        self._db.execute("UPDATE bond_items SET state = 'asked' WHERE id = ?", (row[0],))
        self._db.commit()
        return row[1]

    def record_exchange(self, person: Person, platform: str, their_text: str, now: float | None = None) -> None:
        """Call after her reply, before the exchange is written to friend memory: inside jokes and shared good moments."""
        if person.id is None or not content_ok(person, platform):
            return
        now = self._clock() if now is None else now
        their_text = " ".join(str(their_text or "").split())
        if STRONG_POSITIVE.search(their_text):
            self._remember(person, f"they said: {_clip(their_text, 90)} ({_day(now)})", "", now, key=f"pos:{_day(now)}")
        if not LAUGH.search(their_text):
            return
        recent = [line for _, line in self.memory.moments(person, 4)]
        mine = [line[4:] for line in recent if line.startswith("me: ")]
        funny = _clip(LAUGH.sub("", their_text).strip(" ,.!"), 90) if len(LAUGH.sub("", their_text).strip()) >= 12 else (mine[-1] if mine else "")
        sal = _salient(funny)
        if len(sal) < 2:
            return
        for text, evidence, ts in self.items(person, "joke", MAX_JOKES):
            if _similar(sal, _salient(text)):
                return                                         # already an inside joke
        for row in self._db.execute("SELECT id, text, ts FROM bond_items WHERE person_id = ? AND kind = 'joke_candidate'",
                                    (person.id,)).fetchall():
            if _similar(sal, _salient(row[1])) and now - row[2] >= JOKE_GAP_S:
                self._db.execute("DELETE FROM bond_items WHERE id = ?", (row[0],))
                self._add_item(person, "joke", row[1], f"first {_day(row[2])}: {row[1]} | again {_day(now)}: {funny}", now, cap=MAX_JOKES)
                self.memory.log("inside_joke", platform, person, f"new inside joke: {_clip(row[1], 60)}")
                self._emit(person, f"inside joke with {person.name}: {_clip(row[1], 80)}")
                return
        if not any(_similar(sal, _salient(r[1])) for r in self._db.execute(
                "SELECT id, text FROM bond_items WHERE person_id = ? AND kind = 'joke_candidate'", (person.id,)).fetchall()):
            self._add_item(person, "joke_candidate", funny, "", now, cap=MAX_CANDIDATES)

    # -- what goes into her prompt ----------------------------------------------------------------------------------
    def context(self, person: Person, platform: str = "", now: float | None = None, *, short: bool = False) -> str:
        """Lines about this friendship for the user message (empty for someone forgotten). Short by design.
        `short=True` (star.inner's night-written card is already in the message) leaves the card's own content out."""
        if person.id is None:
            return ""
        now = self._clock() if now is None else now
        b = self.get(person)
        safe = platform != "roblox" and rules.age_status(person) in ("adult", "unknown")
        lines = [f"With {person.name}: {b.label} ({b.convos} chats, {b.shared_games} games together)."]
        if b.nickname:
            lines[0] += f" You call them {b.nickname}."
        if short:
            if b.last_topic and now - b.last_topic_ts < 30 * 86400:
                lines.append(f"Last time you talked about: {b.last_topic}.")
            return "\n".join(lines)
        likes = [f for f in self.memory.facts(person, 40) if _INTEREST.match(f)][-3:]
        if likes:
            lines.append("They like: " + "; ".join(likes) + ".")
        if safe:
            jokes = self.items(person, "joke", 2)
            if jokes:
                lines.append("Inside jokes: " + "; ".join(f'"{_clip(t, 60)}"' for t, _, _ in jokes) + " (mention only if it fits).")
        mems = [t for t, _, _ in self.items(person, "memory", 6)
                if safe or t.startswith(("played ", "we became"))][-2:]
        if mems:
            lines.append("Shared memories: " + "; ".join(mems) + ".")
        if b.last_topic and now - b.last_topic_ts < 30 * 86400:
            lines.append(f"Last time you talked about: {b.last_topic}.")
        return "\n".join(lines)

    # -- star.inner: the same friend cards -------------------------------------------------------------------------
    def card_notes(self, person: Person, platform: str = "") -> str:
        """What the nightly friend card (star.inner.reflect) is told about the bond. No numbers, so card checks stay clean."""
        if person.id is None:
            return ""
        b = self.get(person)
        safe = platform != "roblox" and rules.age_status(person) in ("adult", "unknown")
        parts = [f"Stage: {b.label}."]
        if b.nickname:
            parts.append(f"She calls them {b.nickname}.")
        if safe:
            jokes = self.items(person, "joke", 2)
            if jokes:
                parts.append("Inside jokes: " + "; ".join(_clip(t, 50) for t, _, _ in jokes) + ".")
        if b.last_topic:
            parts.append(f"Last talked about: {b.last_topic}.")
        return " ".join(parts)

    def night(self, store, now: float | None = None) -> dict:
        """The night job's part (star.inner.night.run_night): friends she has not talked to drift down, and follow-up
        questions for close friends become reach-out seeds, so she may open the next chat with them herself
        (reachout.add_seed does its own checks: close friend, they talked first, screening, caps)."""
        from ..inner import reachout
        now = self._clock() if now is None else now
        report = {"drifted": len(self.decay_all(now)), "seeded": 0}
        rows = self._db.execute("SELECT id, person_id, text FROM bond_items WHERE kind = 'followup' AND state = 'open' "
                                "AND ts <= ? AND ts >= ?", (now - FOLLOWUP_MIN_AGE_S, now - FOLLOWUP_MAX_AGE_S)).fetchall()
        for item_id, pid, question in rows:
            person = self.memory.get(pid)
            if reachout.add_seed(store, self.memory, person, question, kind="followup", reason="something they said",
                                 in_days=0.5, now=now) is not None:
                self._db.execute("UPDATE bond_items SET state = 'seeded' WHERE id = ?", (item_id,))
                report["seeded"] += 1
        self._db.commit()
        return report

    # -- memory stream (optional) -----------------------------------------------------------------------------------
    def _emit(self, person: Person, text: str) -> None:
        if self._sink is None or person.id is None:
            return
        try:
            self._sink(text, source="social", person=f"friend-{person.id}")
        except TypeError:
            try:
                self._sink(text)
            except Exception:
                pass
        except Exception:
            pass

    def on_forget(self, person: Person) -> None:
        """Tell the brain's stream (if it keeps per-person entries) that this person asked to be forgotten."""
        forget = getattr(self._sink, "forget", None)
        if person.id is not None and callable(forget):
            try:
                forget(f"friend-{person.id}")
            except Exception:
                pass


def _default_sink():
    """star.brain's memory stream when that module exists and offers one; otherwise None (nothing breaks)."""
    try:
        from .. import brain
    except Exception:
        return None
    for name in ("remember", "add_memory", "memory_stream_add"):
        fn = getattr(brain, name, None)
        if callable(fn):
            return fn
    return None
