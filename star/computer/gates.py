"""What the computer-use driver will not do on its own, even with full admin on her PC (owner rules, 2026-10-26).

Gated (refused here, recorded for the owner with `ask_owner`):
  * spending money, creating or deleting accounts, public posts  (risk.risky_click on the control and the target words)
  * entering passwords or other secrets: password fields, fields named password/PIN/card/CVV/2FA code, and text that
    looks like a card number or a key
  * mass messaging: the same text to more than `same_text_recipients` people, more than `recipients_per_day` different
    people, more than `messages_per_hour` messages (limits.py counts them)
Never done (no owner override in code):
  * anti-cheat or anti-bot circumvention: cheat engines, injectors, exploit executors, input spoofers are not opened;
    a CAPTCHA or "verify you are human" page is not solved: she stops and tells the owner. Her input is ordinary
    SendInput; human pacing keeps her at a person's speed, it is not a way around a platform's detection.
The checks are pattern matches (a safety net, not a proof); the planner prompt states the same rules.
"""
from __future__ import annotations

import re

from .risk import refuses_typing, risky_click
from .screen import Element, Screen


class Gated(Exception):
    """Not hers to do alone: the reason is recorded for the owner and the step is refused."""

    def __init__(self, reason: str, *, never: bool = False) -> None:
        super().__init__(reason)
        self.reason, self.never = reason, never      # never = no owner approval either (anti-cheat, CAPTCHA)


_SECRET_FIELD = re.compile(r"\b(pass ?word|passcode|pin|card number|credit card|cvv|cvc|security code|2fa|"
                           r"two.factor|one.time code|otp|verification code|seed phrase|recovery phrase|api key|"
                           r"secret|token|serial(?: number| key)?|product key|licen[cs]e key|activation key)\b", re.I)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_KEYLIKE = re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp]|AKIA)[-_A-Za-z0-9]{12,}\b|\b[A-Fa-f0-9]{40,}\b")
_CHEAT = re.compile(r"(cheat ?engine|cheatengine|\binjector\b|dll ?inject|\bsynapse\b|\bkrnl\b|\bfluxus\b|"
                    r"\bexecutor\b|\baimbot\b|\bwallhack\b|\btriggerbot\b|\bspoofer\b|hwid ?spoof|\bkiddions\b|"
                    r"\bautoclicker\b)", re.I)
_ANTIBOT = re.compile(r"(captcha|i'?m not a robot|verify (?:that )?you(?:'re| are) (?:a )?human|are you a robot|"
                      r"unusual (?:traffic|activity)|press and hold|bot detection|automated (?:queries|requests))",
                      re.I)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


def looks_secret(text: str) -> str:
    for match in _CARD.finditer(text or ""):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return "this text looks like a payment card number"
    if _KEYLIKE.search(text or ""):
        return "this text looks like a key or token"
    return ""


def check_click(element: Element | None, words: str = "") -> None:
    for el in [element] + ([Element(0, words, "custom", (0, 0, 1, 1))] if words else []):
        if el is None:
            continue
        why = risky_click(el)
        if why:
            raise Gated(why)
        if _ANTIBOT.search(el.name or ""):
            raise Gated("a CAPTCHA or human check is not solved by STAR: the owner was told", never=True)


def check_type(element: Element | None, text: str) -> None:
    why = refuses_typing(element)
    if why:
        raise Gated(why)
    if element is not None and _SECRET_FIELD.search(" ".join((element.name, element.auto_id))):
        raise Gated(f"{element.name or element.auto_id!r} asks for a password or secret: the owner enters those")
    why = looks_secret(text)
    if why:
        raise Gated(why)


def check_open(target: str) -> None:
    if _CHEAT.search(str(target or "")):
        raise Gated("cheat and anti-cheat circumvention tools are never used", never=True)


def check_screen(screen: Screen) -> None:
    """A bot check on screen ends the step: she does not solve or dodge it."""
    for text in screen.texts():
        if _ANTIBOT.search(text or ""):
            raise Gated("the page shows a CAPTCHA / human check: STAR stops and tells the owner", never=True)
