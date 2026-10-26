"""Invitations: a friend asks "wanna call?" or "wanna play Minecraft?" and she decides with her own mind.

parse_invite(text)   reads the invitation out of a DM or a spoken turn (None when there is none)
decide(invite, mind) a deterministic judgement from what she knows right now, never a coin flip:
                     who is asking (friend memory), what she is doing and for how long, whether a round or a video is
                     running, how much of this game she played today, how much she likes it lately (interest weight),
                     her mood (star.emotion), the hour and quiet hours. The answer is yes, later (with minutes) or no,
                     with the reason that weighed most; the same inputs always give the same answer.
InviteDesk           gathers the inputs from the running system and turns an answer into a Plan: the intent she
                     answers from (the text goes to the model, which words it in her own voice; the model never
                     decides) and what happens afterwards (place the call, start the game), scheduled in the inbox.
InviteBrain          wraps the call's brain so a spoken invitation in a call is decided the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import time
from typing import Callable

from .attention import Incoming, Situation, Standing, in_quiet_hours, quiet_end

_CALL = re.compile(
    r"\b(?:wan(?:na|t)(?:\s+to)?|want\s+to|do\s+you\s+want\s+to|would\s+you\s+like\s+to|can\s+you|could\s+you|"
    r"lets?|let's|shall\s+we|hop\s+on|jump\s+(?:on|into)|join(?:\s+me)?(?:\s+in)?|come\s+(?:on|to))\s*(?:a\s+|the\s+|my\s+)?"
    r"(?:call|vc|voice(?:\s+chat)?|voice\s+call|talk\s+on\s+voice|hop\s+on\s+(?:a\s+)?call)\b|"
    r"\b(?:call\s+me|give\s+me\s+a\s+call|voice\s+call\??)\b|\bhop\s+(?:on|in)\s+(?:a\s+)?(?:call|vc|voice)\b", re.I)
_PLAY = re.compile(
    r"\b(?:wan(?:na|t)(?:\s+to)?|want\s+to|do\s+you\s+want\s+to|would\s+you\s+like\s+to|can\s+you|could\s+you|"
    r"lets?|let's|shall\s+we|come|how\s+about|up\s+for)\s+(?:(?:you\s+)?(?:to\s+)?)?(?:play|playing|join\s+me\s+(?:in|for))\s+"
    r"(?:some\s+|a\s+game\s+of\s+|a\s+bit\s+of\s+)?(?P<game>[a-z][a-z0-9' ]{1,30}?)\s*(?:\?|!|\.|,|with\s+me|together|now|"
    r"tonight|later|$)", re.I)
GAMES = {"minecraft": "minecraft", "mc": "minecraft", "roblox": "roblox", "rblx": "roblox"}
INTEREST_OF = {"call": "chat_with_friends", "minecraft": "play_games", "roblox": "play_games"}
CALL_ONLY = re.compile(r"\bplay\b", re.I)


@dataclass(frozen=True)
class Invite:
    kind: str            # call | play
    what: str            # "call" or the game ("minecraft", "roblox")
    sender: str
    text: str = ""


def parse_invite(text: str, sender: str = "") -> Invite | None:
    """"wanna call?", "hop on vc", "do you wanna play minecraft with me?". Only games she can play count as games."""
    said = " ".join(str(text or "").split())[:300]
    play = _PLAY.search(said)
    if play:
        game = GAMES.get(play.group("game").strip().lower().split(" ")[0])
        if game:
            return Invite("play", game, sender, said)
    if _CALL.search(said) and not CALL_ONLY.search(said):
        return Invite("call", "call", sender, said)
    return None


@dataclass
class Mind:
    """Everything the decision reads. Fields default to "nothing special" so a caller fills only what it knows."""
    standing: Standing = field(default_factory=Standing)
    situation: Situation = field(default_factory=Situation)
    doing: str = ""                          # activity name now ("minecraft", "drawing", "")
    doing_minutes: float = 0.0
    weights: dict = field(default_factory=dict)          # interest -> weight (life.interests())
    played_today_min: float = 0.0            # minutes of this game in the last 24 h
    mood: dict | None = None                 # star.emotion.current(): emotions, valence, ...
    now: float = 0.0
    quiet_hours: dict = field(default_factory=dict)
    close_at: float = 0.6


@dataclass(frozen=True)
class Answer:
    say: str                 # yes | later | no
    reason: str              # the factor that weighed most, in plain words
    delay_min: float = 0.0   # later: when she will do it
    tone: str = ""           # a hint for the wording: warm, excited, sleepy, apologetic, shy, busy
    score: float = 0.0
    factors: tuple = ()      # ((name, effect), ...) for the log and the tests


THRESHOLD = 0.45
LATER_BAND = 0.15            # this close under the threshold she says "give me a bit" instead of no
LATE_HOURS = (22, 6)         # 22:00-06:00 local counts as late (quiet hours are separate and stricter)
TIRED_AFTER_MIN = 120.0      # minutes of the same game in a day before it wears on her
LATER_MIN = {"game": 5.0, "video": 8.0, "work": 6.0, "mood": 12.0}


def _hour(now: float) -> int:
    return time.localtime(now).tm_hour


def _late(hour: int) -> bool:
    return hour >= LATE_HOURS[0] or hour < LATE_HOURS[1]


def _emotion(mood: dict | None, name: str, default: float) -> float:
    try:
        return float((mood or {}).get("emotions", {}).get(name, default))
    except (TypeError, ValueError):
        return default


def _mood_factors(mood: dict, kind: str) -> list[tuple[str, float]]:
    """How her mood weighs on this invitation. The emotion engine's own `invite_bias` (bounded, with a reason) when it has
    one; with the older seven-feeling engine the three plain factors below."""
    try:
        from .. import emotion
        bias_of = getattr(emotion, "invite_bias", None)
        if callable(bias_of):
            bias, why = bias_of(mood, kind)
            return [(f"her mood: {why}" if why else "her mood", float(bias))] if bias else []
    except Exception:
        pass
    frustration = _emotion(mood, "frustration", 0.03) - 0.03
    boredom = _emotion(mood, "boredom", 0.08) - 0.08
    joy = _emotion(mood, "joy", 0.30) - 0.30
    valence = float(mood.get("valence", 0.15) or 0.15) - 0.15
    return [("her mood is rough: she is frustrated" if frustration > 0.2 else "her mood", -0.6 * frustration),
            ("she is restless and wants company" if boredom > 0.1 else "her energy", 0.3 * boredom),
            ("she is happy", 0.3 * joy + 0.2 * valence)]


def decide(invite: Invite, mind: Mind) -> Answer:
    standing, situation = mind.standing, mind.situation
    tier = standing.tier(mind.close_at)
    if tier == "never":
        return Answer("no", "she does not talk with this person", tone="")
    if in_quiet_hours(mind.now, mind.quiet_hours):
        return Answer("no", "it is her quiet time", tone="sleepy",
                      delay_min=max(1.0, (quiet_end(mind.now, mind.quiet_hours) - mind.now) / 60.0))
    if invite.kind == "call" and situation.in_call:
        return Answer("no", "she is already in a call", tone="warm")
    if invite.kind == "call" and tier == "met":
        return Answer("no", "she does not know them well enough for a call yet", tone="shy")
    if situation.in_moment and situation.kind in ("game", "video"):
        what = "round" if situation.kind == "game" else "video"
        return Answer("later", f"she is in the middle of a {what}", delay_min=LATER_MIN[situation.kind], tone="busy")

    factors: list[tuple[str, float]] = []
    factors.append(("who is asking", {"close": 0.25, "friend": 0.10, "met": -0.20}[tier]))
    entry = mind.weights.get(INTEREST_OF.get(invite.what, "play_games"), 1.0)
    weight = float(entry.get("weight", 1.0) if isinstance(entry, dict) else entry)
    factors.append(("how much she likes it lately", max(-0.30, min(0.30, 0.15 * math.log2(max(weight, 0.1))))))
    if invite.kind == "play" and mind.played_today_min > TIRED_AFTER_MIN:
        over_hours = (mind.played_today_min - TIRED_AFTER_MIN) / 60.0
        factors.append((f"she already played {invite.what} a lot today", -min(0.45, 0.15 * (1 + over_hours))))
    if mind.mood:
        factors.extend(_mood_factors(mind.mood, invite.kind))
    if mind.doing and situation.kind == "work" and mind.doing_minutes < 10:
        factors.append((f"she just started {mind.doing}", -0.2))
    if _late(_hour(mind.now)) and tier != "close":
        factors.append(("it is late", -0.15))

    score = 0.5 + sum(effect for _, effect in factors)
    worst = min(factors, key=lambda f: f[1])
    kept = tuple((name, round(effect, 3)) for name, effect in factors)
    if score >= THRESHOLD:
        return Answer("yes", "she feels like it", tone="excited" if score >= 0.7 else "warm", score=score, factors=kept)
    why = worst[0]
    if score >= THRESHOLD - LATER_BAND:
        return Answer("later", why, delay_min=LATER_MIN["mood"], tone="apologetic", score=score, factors=kept)
    return Answer("no", why, tone="apologetic" if tier != "met" else "shy", score=score, factors=kept)


def intent_for(answer: Answer, invite: Invite) -> str:
    """What she decided, as a line for the model that words her reply. It never overrides the decision."""
    what = "call" if invite.kind == "call" else f"play {invite.what.capitalize()}"
    cute = " Say it in your own voice: playful, a little cute, never formal."
    if answer.say == "yes":
        do = "you will call them yourself right now" if invite.kind == "call" else f"you will start {invite.what.capitalize()} now and stay in the call"
        return f"you decided yes to '{what}': {do}; say yes happily.{cute}"
    if answer.say == "later":
        return (f"you decided not this second to '{what}': in about {int(round(answer.delay_min))} minutes, because "
                f"{answer.reason}; say that.{cute}")
    return f"you decided no to '{what}' for now because {answer.reason}; say it kindly, no long apology.{cute}"


@dataclass
class Plan:
    answer: Answer
    intent: str
    after: Callable[[], None] | None = None


class InviteDesk:
    """Collects the inputs from the running system, decides, and schedules what follows (the call, the game)."""

    def __init__(self, *, standing_of: Callable[[str, str], Standing], situation: Situation, life=None, emotion=None,
                 config: dict | None = None, schedule: Callable[..., object] | None = None,
                 clock: Callable[[], float] = time.time, log: Callable[..., None] | None = None) -> None:
        from .attention import settings
        self.standing_of, self.situation, self.life, self.emotion = standing_of, situation, life, emotion
        self.cfg = settings(config)
        self.schedule = schedule
        self.clock = clock
        self._log = log or (lambda *a, **k: None)

    def _played_today(self, game: str) -> float:
        if self.life is None:
            return 0.0
        cutoff = self.clock() - 24 * 3600
        total = 0.0
        for row in self.life.history(300):
            try:
                stamp = time.mktime(time.strptime(row.get("ts", ""), "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
            except ValueError:
                continue
            if row.get("activity") == game and stamp >= cutoff:
                total += float(row.get("minutes") or 0.0)
        return total

    def mind_for(self, invite: Invite, platform: str = "discord") -> Mind:
        now = self.clock()
        mood = None
        if self.emotion is not None:
            try:
                mood = self.emotion.current()
            except Exception:
                mood = None
        since = getattr(self.situation, "since", 0.0)
        return Mind(standing=self.standing_of(platform, invite.sender), situation=self.situation,
                    doing=getattr(self.situation, "activity", ""),
                    doing_minutes=(now - since) / 60.0 if since else 0.0,
                    weights=self.life.interests() if self.life is not None else {},
                    played_today_min=self._played_today(invite.what) if invite.kind == "play" else 0.0,
                    mood=mood, now=now, quiet_hours=self.cfg["quiet_hours"], close_at=float(self.cfg["close_at"]))

    def plan(self, invite: Invite, platform: str = "discord") -> Plan:
        answer = decide(invite, self.mind_for(invite, platform))
        self._log("invite", sender=invite.sender, what=invite.what, say=answer.say, reason=answer.reason,
                  score=round(answer.score, 3))
        after = None
        if answer.say in ("yes", "later") and self.schedule is not None:
            kind = "callout" if invite.kind == "call" else "startgame"
            text = "call" if invite.kind == "call" else invite.what
            at = self.clock() + (4.0 if answer.say == "yes" else answer.delay_min * 60.0)
            bound = float(self.cfg["moment_wait_s"]["close"])

            def after(kind=kind, text=text, at=at, bound=bound) -> None:
                self.schedule(Incoming(kind, platform, invite.sender, text, at=self.clock()), at, at + bound,
                              "she said yes to the invitation")
        return Plan(answer, intent_for(answer, invite), after)


class InviteBrain:
    """Wraps the call's brain: when the friend's last words invite her somewhere, the decision is made first and its
    intent is appended to that message (like the hearing note), so her spoken answer matches what she will do."""

    def __init__(self, brain, desk: InviteDesk, *, sender: Callable[[], str]) -> None:
        self._brain, self._desk, self._sender = brain, desk, sender

    def stream(self, messages: list[dict]):
        if messages and messages[-1].get("role") == "user":
            invite = parse_invite(str(messages[-1].get("content", "")).split("\n\n(")[0], self._sender())
            if invite is not None:
                plan = self._desk.plan(invite)
                if plan.after is not None:
                    plan.after()
                messages = messages[:-1] + [{**messages[-1], "content": f"{messages[-1]['content']}\n\n({plan.intent})"}]
        return self._brain.stream(messages)

    def __getattr__(self, name):
        return getattr(self._brain, name)
