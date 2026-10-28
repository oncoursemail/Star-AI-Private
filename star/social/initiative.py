"""Initiative: she writes first sometimes, because something real happened, through the one reach-out path.

Triggers (each one only stores a seed with `star.inner.reachout.add_seed`, which applies every check: close friend who
talked to her first, the age rules, the guilt filter, no Roblox; `reachout.due` adds quiet hours, their usual hours,
at most 3 a day, 3 h between any two, 48 h per person, never while they are chatting or an earlier one is unanswered):

* a promise she made in chat that means writing first ("i'll message you tomorrow"), due when she said;
* missing a close friend: no word from them for a few days (checked once a day, not every time; never a complaint);
* something she did or learned that fits a friend's interest ("finally beat the ender dragon" -> the friend who
  loves Minecraft);
* a friend shows up in a game she is playing too (`friend_online`, for an adapter that can see presence);
* follow-ups (lifecycle.Bonds.night, already there) are delivered by the same `deliver()`.

`deliver(send)` is the first real sender: an adapter (Discord desktop, when nothing is unread) calls it, it asks
`reachout.due` for at most one message, sends it with `send(platform, handle, text) -> bool`, then marks it sent, keeps
it in friend memory ("me: ...") and in the owner's social log. The words come from her own model when one is given
(a short brief, her social persona) and from a few plain lines otherwise; every text then passes style and screening.
Off unless the setting `inner_initiative` is on (ON on her own PC, OFF elsewhere: star/inner/settings.py).
"""
from __future__ import annotations

import random
import re
import time
from typing import Callable

from . import style
from .friends import _INTEREST, FriendMemory, Person

MISS_AFTER_DAYS = 5.0
MISS_CHANCE = 0.35           # a day with a quiet close friend does not always become a message
SHARE_MIN_OVERLAP = 1
_STOP = {"the", "and", "with", "really", "playing", "play", "like", "love", "enjoy", "games", "game", "watch", "some",
         "stuff", "things", "lot", "lots", "much", "very", "most", "favorite", "favourite", "build", "draw"}

FALLBACK = {
    "online": ("omg you're on {game} too?", "wait are you playing {game} rn", "saw you on {game}, want to team up?"),
    "miss": ("hey you, was just thinking about you. how's your week been?", "heyy how are you doing? it's been a few days",
             "random but you popped into my head today. how've you been?"),
    "share": ("ok so i was just doing {detail} and thought of you", "you'd have loved this, i was just doing {detail}",
              "was just doing {detail} and it made me think of you"),
    "promise": ("hey! said i'd message you today", "hiii, told you i'd text today", "hey, as promised, hi"),
}
BRIEF = {
    "online": "You just noticed {name} is on {game} too, like you. Write them a short first message about it.",
    "miss": ("You have not talked with {name} for a few days and you were thinking about them. Write a short first "
             "message to catch up. No complaint, nothing about them being quiet, no 'I miss you'."),
    "share": ("You were just doing {detail} ({about}), and it made you think of {name} because they told you \"{interest}\". "
              "Write a short first message telling them."),
    "promise": 'Earlier you told {name}: "{detail}". Now keep it: write that first message.',
}
WRITE_FIRST = "(You are writing first; there is no new message from them. One or two short lines, like a friend texting.)"


def enabled_setting() -> bool:
    try:
        from ..inner import settings
        return settings.on(settings.load(), "initiative")
    except Exception:
        return False


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']{3,}", str(text or "").lower()) if w not in _STOP}


class Initiative:
    def __init__(self, memory: FriendMemory, store, *, compose: Callable[[str, str], str] | None = None,
                 enabled: bool | Callable[[], bool] = True, clock: Callable[[], float] = time.time,
                 rng: random.Random | None = None) -> None:
        self.memory, self.store = memory, store
        self._complete = compose
        self._enabled = enabled
        self._clock = clock
        self._rng = rng or random.Random()

    @property
    def on(self) -> bool:
        return bool(self._enabled() if callable(self._enabled) else self._enabled)

    # -- words ------------------------------------------------------------------------------------------------------
    def compose(self, kind: str, person: Person, **detail: str) -> str:
        """Her words for a first message: her model with a short brief, else one of a few plain lines."""
        fields = {"name": person.name, "game": "", "detail": "", "interest": "", "about": "", **detail}
        text = ""
        if self._complete is not None:
            try:
                from ..persona import strip_reasoning
                from .chat import SOCIAL_CORE
                from .lifecycle import Bonds
                about = "\n".join(p for p in (self.memory.context(person), Bonds(self.memory, sink=None, felt=False)
                                              .context(person, "discord", self._clock(), short=True)) if p)
                user = f"{about}\n\n{BRIEF[kind].format(**fields)}\n{WRITE_FIRST}"
                text = strip_reasoning(self._complete(SOCIAL_CORE, user) or "")
            except Exception:
                text = ""
        if not text.strip():
            text = self._rng.choice(FALLBACK[kind]).format(**fields)
        return style.polish(" ".join(text.split()))

    def _seed(self, kind: str, person: Person, text: str, *, reason: str, in_days: float = 0.0, ttl_days: float = 1.0):
        if not self.on or person is None or person.id is None:
            return None
        from ..inner import reachout
        sid = reachout.add_seed(self.store, self.memory, person, text, kind=kind, reason=reason, in_days=in_days,
                                ttl_days=ttl_days, now=self._clock())
        if sid is not None:
            platform = (self.memory.handles(person) or [("discord", "")])[0][0]
            self.memory.log("initiative_seed", platform, person, f"{kind}: {reason}")
        return sid

    # -- triggers ---------------------------------------------------------------------------------------------------
    def on_promise(self, person: Person, promise) -> int | None:
        """A promise that means writing first ("i'll message you tomorrow"): a seed for when it is due."""
        if promise is None or not getattr(promise, "reach_out", False):
            return None
        now = self._clock()
        text = self.compose("promise", person, detail=promise.text)
        return self._seed("promise", person, text, reason="she said she would", in_days=max(0.0, (promise.due - now) / 86400),
                          ttl_days=0.75)

    def friend_online(self, person: Person, game: str) -> int | None:
        """A friend shows up in a game she is playing too (from an adapter that can see presence)."""
        if not game:
            return None
        return self._seed("online", person, self.compose("online", person, game=game), reason=f"both on {game}",
                          ttl_days=0.05)

    def on_learned(self, topic_name: str, summary: str = "", *, verified: bool) -> int | None:
        """She did or learned something (a checked STAR Home outcome, `topic_name` like "minecraft building"): tell the
        one friend whose interests fit it best, if any."""
        if not verified or not self.on:
            return None
        topic = _words(f"{topic_name} {summary}")
        best, best_hits, best_like = None, 0, ""
        for person in self.memory.people():
            if person.blocked or person.muted or person.relationship != "friend":
                continue
            for fact in self.memory.facts(person, 40):
                if not _INTEREST.match(fact):
                    continue
                hits = len(topic & _words(_INTEREST.sub("", fact)))
                if hits > best_hits:
                    best, best_hits, best_like = person, hits, fact
        if best is None or best_hits < SHARE_MIN_OVERLAP:
            return None
        interest = re.sub(r"^\s*i\s+", "", best_like, flags=re.I).rstrip(" .!")
        detail = " ".join(str(topic_name).replace("_", " ").split())[:40]
        about = " ".join(str(summary).split())[:100]
        return self._seed("share", best, self.compose("share", best, detail=detail, interest=interest, about=about),
                          reason=f"she did {detail}", ttl_days=1.0)

    def missing(self) -> list[int]:
        """Once a day: close friends she has not heard from for a few days may get a light 'how are you' (sometimes)."""
        if not self.on:
            return []
        now = self._clock()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if self.store.meta("initiative_miss_day", "") == day:
            return []
        self.store.set_meta("initiative_miss_day", day)
        from ..inner import reachout
        out = []
        for person in self.memory.people():
            if not reachout.is_close(self.memory, person, now):
                continue
            theirs = [ts for _, _, line, ts in self.memory.moment_records(person) if line.startswith("they: ")]
            if not theirs or now - max(theirs) < MISS_AFTER_DAYS * 86400 or self._rng.random() >= MISS_CHANCE:
                continue
            sid = self._seed("miss", person, self.compose("miss", person), reason="thinking of them", ttl_days=1.0)
            if sid is not None:
                out.append(sid)
        return out

    # -- the sender -------------------------------------------------------------------------------------------------
    def deliver(self, send: Callable[[str, str, str], bool], *, platforms: tuple[str, ...] = ("discord",)) -> str:
        """At most one due message, sent through `send`; '' when nothing went out."""
        if not self.on:
            return ""
        from ..inner import reachout
        now = self._clock()
        for out in reachout.due(self.store, self.memory, now=now, enabled=True):
            if out.platform not in platforms:
                continue
            try:
                ok = bool(send(out.platform, out.handle, out.text))
            except Exception:
                ok = False
            if not ok:
                return ""
            reachout.mark_sent(self.store, out.seed_id, now)
            person: Person = out.person  # type: ignore[assignment]
            self.memory.note_moment(person, out.platform, f"me: {out.text}")
            self.memory.log("reach_out", out.platform, person, f"{out.kind}: wrote first")
            return f"wrote first to {out.handle} ({out.kind})"
        return ""

    def tick(self, send: Callable[[str, str, str], bool]) -> str:
        """The adapter's idle moment: the daily 'missing someone' check, then at most one message."""
        if not self.on:
            return ""
        try:
            self.missing()
        except Exception:
            pass
        return self.deliver(send)


def for_chat(memory: FriendMemory, complete: Callable[[str, str], str] | None = None, *, home=None,
             clock: Callable[[], float] = time.time) -> Initiative | None:
    """The live Initiative when `inner_initiative` is on (her PC), else None (nothing is ever opened or sent)."""
    if not enabled_setting():
        return None
    from ..inner.store import InnerStore
    return Initiative(memory, InnerStore(home=home, clock=clock), compose=complete, enabled=enabled_setting, clock=clock)



_shared: list = []


def share_learned(topic_name: str, summary: str = "", *, verified: bool) -> int | None:
    """STAR Home hook (inner.mind.MindLife.record): a checked outcome that fits a friend's interest. Never raises.
    No model here (the home loop's brain is busy with the session): one of the plain lines, then style and screening."""
    if not verified or not enabled_setting():
        return None
    try:
        if not _shared:
            _shared.append(for_chat(FriendMemory()))
        return _shared[0].on_learned(topic_name, summary, verified=True) if _shared[0] is not None else None
    except Exception:
        return None
