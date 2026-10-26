"""What the social chat (and the desktop chat) asks for per message: her relationship card and a short recall note.

    ctx = star.inner.turn_context(memory, person, text, first_turn=conversation_is_new)
    ctx.card   # <= CARD_CHARS about this person; pin it as the first message of the conversation (stable, so cached)
    ctx.note   # "" or "(maybe useful, only if it fits: ...)"; append to the NEW user message only, never the system prompt
    ctx.done() # call after her reply was sent: the memories she used are remembered longer

Costs: no model call, about 5 ms; the note is at most MAX_CHARS (about 40 tokens) and usually empty. Off unless the setting
`inner_chat_enabled` is true (or force=True, as the blind A/B harness does): measurement pending, see the notes file.
`person=None` is the owner's chat (her own life: home sessions, opinions, her dream).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..social import rules
from . import dreams, opinions, recall
from .reflect import CARD_CHARS, rule_card, valid_card
from .store import InnerStore, default_store, flag, person_key

__all__ = ["TurnContext", "turn_context", "card_for", "CARD_CHARS"]


@dataclass
class TurnContext:
    card: str = ""
    note: str = ""
    lines: list[str] = field(default_factory=list)
    abstained: bool = False
    _store: InnerStore | None = None
    _ids: list[int] = field(default_factory=list)

    def with_note(self, message: str) -> str:
        """The user message with the note appended (or unchanged when there is none)."""
        return f"{message}\n{self.note}" if self.note else message

    def done(self) -> None:
        if self._store is not None and self._ids:
            self._store.strengthen(self._ids)
            self._ids = []


def card_for(store: InnerStore, memory, person, now: float | None = None) -> str:
    """Use only a current source-backed card; old unsupported rows stay for audit."""
    if person is None or person.id is None:
        return ""
    try:
        person = memory.get(person.id)
    except KeyError:
        return ""
    pkey = person_key(memory, person)
    if not pkey:
        return ""
    canonical = rule_card(memory, person)
    text, _ = store.card(pkey)
    if person_key(memory, person) != pkey:
        return ""
    return valid_card(text, canonical, memory, person) or valid_card(canonical, canonical, memory, person)


def turn_context(memory, person, text: str, *, store: InnerStore | None = None, home=None, now: float | None = None,
                 first_turn: bool = False, force: bool = False) -> TurnContext:
    """Card and recall note for one incoming message. Never raises (a memory problem must not break a chat)."""
    try:
        if not (force or flag("inner_chat_enabled", home)):
            return TurnContext()
        if person is not None and person.id is None:
            return TurnContext()                         # asked to be forgotten: she keeps nothing
        if person is not None:
            try:
                person = memory.get(person.id)
            except KeyError:
                return TurnContext()
            if not person_key(memory, person):
                return TurnContext()                     # never reinterpret a forgotten identity as the owner
            if rules.age_status(person) in ("minor", "doubt"):
                canonical = rule_card(memory, person)
                return TurnContext(card=valid_card(canonical, canonical, memory, person))
        now = time.time() if now is None else now
        store = store or default_store(home)
        if not store.meta("backstory_seeded"):
            opinions.seed_backstory(store)
            store.set_meta("backstory_seeded", "1")
        pkey = ""
        if person is not None:
            recall.sync_person(store, memory, person)
            pkey = person_key(memory, person)
            if not pkey:
                return TurnContext()
        found = recall.recall(store, pkey, text, now=now, first_turn=first_turn)
        lines: list[str] = []
        dream = dreams.dream_line(store, memory, person, pkey, text, now, first_turn=first_turn) if memory else ""
        if dream:
            lines.append(dream)
        lines += found.lines
        for extra in (opinions.lookup(store, text), opinions.backstory_lines(store, text)):
            lines += extra
        lines = lines[: recall.MAX_LINES]
        ids = found.ids[: max(0, recall.MAX_LINES - (1 if dream else 0))]
        return TurnContext(card_for(store, memory, person, now) if person is not None else "",
                           recall.note(lines, abstain=found.abstain and not lines), lines, found.abstain and not lines,
                           store, ids)
    except Exception:
        return TurnContext()
