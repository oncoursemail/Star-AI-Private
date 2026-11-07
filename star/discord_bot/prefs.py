"""What the owner told Star to remember about him, kept with STAR's memory (star/memory.py, project 'discord-owner')
in the bot's own state folder (~/.star/discord-state/owner-memory.sqlite3 on the bot's host).

Only the owner's own words from his DM ("remember: I like short answers") are stored; never model text. The list
rides at the end of his private turns, so Star uses it without reciting it. "forget: ..." removes matching items,
"what do you remember about me" lists them. At most 30 items of 300 characters.
"""
from __future__ import annotations

from pathlib import Path
import re

PROJECT = "discord-owner"
MAX_ITEMS = 30
MAX_CHARS = 300
_REMEMBER = re.compile(r"^(?:star[, ]+)?remember(?: that|:| this:)\s*(.{3,300})$", re.I | re.S)
_FORGET = re.compile(r"^(?:star[, ]+)?forget(?: that|:)\s*(.{2,300})$", re.I | re.S)
_LIST = re.compile(r"^(?:star[, ]+)?what do you (?:remember|know) about me\??$", re.I)


def prefs_request(text: str) -> tuple[str, str] | None:
    """('remember'|'forget'|'list', text) for a preference command, else None."""
    text = " ".join(str(text or "").split())
    for kind, pattern in (("remember", _REMEMBER), ("forget", _FORGET)):
        match = pattern.fullmatch(text)
        if match:
            return kind, match.group(1).strip()
    return ("list", "") if _LIST.fullmatch(text) else None


class OwnerPrefs:
    def __init__(self, db: Path) -> None:
        self.db = Path(db)

    def _open(self):
        from ..memory import Memory
        return Memory(self.db)

    def items(self) -> list[str]:
        if not self.db.is_file():           # nothing remembered yet: reading never creates the file
            return []
        memory = self._open()
        try:
            return [line for line in memory.get(PROJECT).splitlines() if line.strip()]
        finally:
            memory.close()

    def _save(self, items: list[str]) -> None:
        memory = self._open()
        try:
            if items:
                memory.put(PROJECT, "\n".join(items))
            else:
                memory.db.execute("DELETE FROM checkpoints WHERE project=?", (PROJECT,))
                memory.db.commit()
        finally:
            memory.close()

    def remember(self, text: str) -> str:
        text = " ".join(text.split())[:MAX_CHARS]
        from ..lessons import has_secret
        if has_secret(text):
            return "That looks like a password or key, so I won't keep it."
        items = [i for i in self.items() if i.lower() != text.lower()]
        self._save((items + [text])[-MAX_ITEMS:])
        return "Got it, I'll remember that."

    def forget(self, text: str) -> str:
        items = self.items()
        words = text.lower()
        kept = [i for i in items if words not in i.lower()]
        if len(kept) == len(items):
            return "I didn't have anything like that saved."
        self._save(kept)
        return f"Forgotten ({len(items) - len(kept)} item{'s' if len(items) - len(kept) != 1 else ''})."

    def listing(self) -> str:
        items = self.items()
        if not items:
            return "Nothing yet. Tell me `remember: ...` and I will."
        return "What you've told me to remember:\n" + "\n".join(f"- {i}" for i in items)

    def context(self) -> str:
        items = self.items()
        return ("THINGS THE OWNER TOLD YOU TO REMEMBER (his own words; use them, don't recite them):\n"
                + "\n".join(f"- {i}" for i in items)) if items else ""
