"""Real-world actions stay with the owner: spending money, public posts, new accounts, deleting an account.

STAR decides for herself on her own PC, but these four are not hers to decide (owner rules, 2026-10-26). A click on
a control whose name says one of them is not made: the request goes to the owner's queue (`ask_owner`) instead.
Typing into a password field is refused too: she never handles passwords (the owner signs in once). The check is a
plain pattern match on the control's name, so it is a safety net, not a proof; the planner prompt says the same.
"""
from __future__ import annotations

import re

from .screen import Element

_RULES = (
    (re.compile(r"\b(buy now|buy|purchase|place (?:your |my )?order|pay now|pay|checkout|check out|complete "
                r"(?:order|purchase)|subscribe|donate|add (?:a )?payment|confirm payment|upgrade to)\b", re.I),
     "spending money"),
    (re.compile(r"\b(sign up|create (?:an? )?(?:new )?account|register|join now)\b", re.I), "creating an account"),
    (re.compile(r"\b(delete (?:my |your )?account|close (?:my |your )?account|deactivate (?:my |your )?account)\b",
                re.I), "deleting an account"),
    (re.compile(r"^\s*(post|publish|tweet|post publicly|share publicly)\s*$", re.I), "posting publicly"),
)


def risky_click(element: Element) -> str:
    """Why this control needs the owner ("" when it does not)."""
    for text in (element.name, element.auto_id):
        for pattern, why in _RULES:
            if text and pattern.search(text):
                return why
    return ""


def refuses_typing(element: Element | None) -> str:
    if element is not None and element.password:
        return "this is a password field: she never types passwords"
    return ""
