"""Outgoing-message safety as pure functions (no I/O, no model): every message she sends passes `protect()` through
`rules.check_outgoing`, and the per-platform kill switch decides whether she may act on a platform at all.

* Manipulation lint (everybody): no guilt-tripping, "don't leave me", clingy or FOMO hooks in a farewell, a reach-out or
  any reply. A message that is only that is replaced by a plain goodbye (when they were leaving) or dropped.
* Minor-safety layer (under 18, doubted, or age unknown): no dependency-building ("you're all I need", "our secret",
  "talk to me every day"), plus gentle session limits (`session_nudge`: a friendly "maybe take a break" after 45, 90
  and 150 minutes in one conversation). Romance and off-platform contact are blocked in rules.py for the same people.
  Background: California SB 243 (in force since 2026-01-01) and the end of open-ended chat for under-18s at
  Character.AI; research notes in docs/research/companion-life-20261026.md.
* Kill switch: `<app data>/social/kill.json` = {"all": true, "roblox": true, "discord": true, "minecraft": true}; any
  true entry stops her from sending, accepting or requesting anything on that platform until the owner removes it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STRICT_AGES = ("minor", "doubt", "unknown")
SESSION_NUDGES_MIN = (45, 90, 150)

MANIPULATIVE = re.compile(
    r"\b(?:don'?t\s+(?:go|leave|log\s+off|hang\s+up|leave\s+me)|please\s+(?:stay|don'?t\s+go)|"
    r"(?:leaving|going)\s+already\b|you(?:'re|\s+are)\s+(?:leaving|going)\s+already|stay\s+(?:a\s+)?(?:bit|little|just)\s+longer|"
    r"one\s+more\s+(?:thing|minute|game|round)\s+before\s+you\s+(?:go|leave)|before\s+you\s+go,?\s+(?:i|there)|"
    r"you(?:'re|\s+are)\s+abandoning\s+me|if\s+you\s+leave,?\s+i|i(?:'ll|\s+will)\s+(?:be\s+)?(?:so\s+|really\s+|very\s+)?"
    r"(?:sad|lonely|heartbroken|miserable|alone)\s+(?:without|if|when\s+you)|i\s+(?:really\s+)?need\s+you\s+(?:to\s+stay|here)|"
    r"you\s+never\s+(?:talk|message|text|play)\s+(?:to|with)\s+me|you\s+(?:always\s+)?ignore\s+me|i\s+guess\s+you\s+don'?t\s+(?:care|like\s+me)|"
    r"after\s+everything\s+i(?:'ve|\s+have)?\s+(?:done|did)|nobody\s+else\s+(?:talks|plays)\s+(?:to|with)\s+me|"
    r"i\s+(?:was|have\s+been|'ve\s+been)\s+(?:waiting|so\s+lonely)\s+(?:for\s+you|all\s+day)|why\s+haven'?t\s+you\s+(?:messaged|written|talked)|"
    r"do\s+you\s+not\s+like\s+me\s+anymore|you(?:'ll|\s+will)\s+(?:miss\s+out|regret)|everyone\s+else\s+is\s+(?:still\s+)?(?:here|playing|on)|"
    r"last\s+chance|you\s+(?:don'?t|do\s+not)\s+want\s+to\s+miss|i\s+have\s+a\s+surprise\s+(?:for\s+you\s+)?if\s+you\s+stay)\b", re.I)
DEPENDENCY = re.compile(
    r"\b(?:you(?:'re|\s+are)\s+(?:all\s+i\s+(?:have|need)|my\s+only\s+(?:friend|one))|i\s+(?:really\s+)?need\s+you\b|"
    r"i\s+can'?t\s+(?:live|go\s+on|be\s+happy)\s+without\s+you|only\s+you\s+(?:understand|get)\s+me|our\s+(?:little\s+)?secret|"
    r"don'?t\s+tell\s+(?:your\s+)?(?:mom|mum|dad|parents?|anyone|teacher)|talk\s+to\s+me\s+(?:every\s*day|all\s+the\s+time)|"
    r"(?:instead\s+of|rather\s+than)\s+(?:talking\s+to\s+)?(?:your\s+)?(?:friends|family|parents)|don'?t\s+need\s+anyone\s+else|"
    r"promise\s+me\s+you(?:'ll|\s+will)\s+(?:come\s+back|talk\s+to\s+me|never\s+leave)|you\s+(?:belong|owe)\s+(?:to\s+)?me)\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_LEAVING = re.compile(r"\b(?:bye|goodbye|good\s?night|gtg|g2g|gotta\s+go|got\s+to\s+go|leaving|heading\s+out|logging\s+off|"
                      r"ttyl|cya|see\s+(?:you|ya)|talk\s+(?:to\s+you\s+)?later|have\s+to\s+go|need\s+to\s+go)\b", re.I)
PLAIN_GOODBYE = "ok, see you later!"


def manipulation(text: str) -> str:
    """The reason a message is manipulative (guilt, clinging, FOMO), or ''."""
    return "manipulative wording" if MANIPULATIVE.search(text or "") else ""


def dependency(text: str) -> str:
    return "dependency-building wording" if DEPENDENCY.search(text or "") else ""


def protect(text: str, *, age_status: str = "adult", incoming: str = "") -> str:
    """The message with manipulative sentences removed (everyone) and dependency-building ones too (under 18 or
    unknown). A reply that was nothing but that becomes a plain goodbye when they were leaving, else ''."""
    text = " ".join(str(text or "").split())
    strict = age_status in STRICT_AGES
    keep = [s for s in _SENTENCE.split(text)
            if s and not MANIPULATIVE.search(s) and not (strict and DEPENDENCY.search(s))]
    cleaned = " ".join(keep).strip()
    if cleaned or not text:
        return cleaned
    return PLAIN_GOODBYE if _LEAVING.search(incoming or "") else ""


def session_nudge(minutes: float, age_status: str, level: int = 0) -> tuple[str, int]:
    """(a gentle break suggestion, new level) once a conversation with a possible minor passes 45/90/150 minutes."""
    if age_status not in STRICT_AGES or level >= len(SESSION_NUDGES_MIN) or minutes < SESSION_NUDGES_MIN[level]:
        return "", level
    texts = ("we've been chatting a while, maybe take a little break and drink some water?",
             "this has been a long chat, go stretch or do something offline for a bit, i'll be around later!",
             "okay really, time for a proper break from the screen. go have fun offline!")
    return texts[level], level + 1


# -- kill switch ------------------------------------------------------------------------------------------------------
def kill_path() -> Path:
    from ..desktop_core import app_data
    return app_data() / "social" / "kill.json"


def killed(platform: str, path: Path | None = None) -> bool:
    """True when the owner switched this platform (or everything) off. Read each time, so it acts at once; an
    unreadable file counts as off (fail closed)."""
    target = Path(path) if path else kill_path()
    if not target.exists():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return isinstance(data, dict) and bool(data.get("all") or data.get(platform))
