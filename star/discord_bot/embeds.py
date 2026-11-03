"""Star's rich cards (Discord embeds) for structured messages; chat stays plain text in her voice.

Pure builders: each returns an embed as a plain dict (Discord's JSON shape), so they are tested without discord.py;
the bot turns one into `discord.Embed.from_dict(card)` and, if sending the card fails, sends `card_text(card)`.
One look everywhere: STAR's gold accent (frontend --gold #E8BF76) for neutral cards, green / amber / red by status,
a short title, inline fields for numbers, the bot's own avatar as the small thumbnail (added at send time) and a
footer with the time and the source. Discord's limits are enforced in `fit`.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

GOLD, GREEN, AMBER, RED = 0xE8BF76, 0x3BA55C, 0xF0B232, 0xED4245
LIMITS = {"title": 256, "description": 4096, "fields": 25, "field_name": 256, "field_value": 1024,
          "footer": 2048, "author": 256, "total": 6000}


def _cut(text: object, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def fit(card: dict) -> dict:
    """Clamp a card to Discord's limits (title 256, description 4096, 25 fields of 256/1024, 6000 in total)."""
    out = dict(card)
    out["title"] = _cut(out.get("title", ""), LIMITS["title"])
    if out.get("description"):
        out["description"] = _cut(out["description"], LIMITS["description"])
    fields = []
    for field in (out.get("fields") or [])[: LIMITS["fields"]]:
        name, value = _cut(field.get("name") or "-", LIMITS["field_name"]), _cut(field.get("value") or "-", LIMITS["field_value"])
        fields.append({"name": name, "value": value, "inline": bool(field.get("inline"))})
    out["fields"] = fields
    if out.get("footer"):
        out["footer"] = {"text": _cut(out["footer"].get("text", ""), LIMITS["footer"])}
    while total_chars(out) > LIMITS["total"] and out["fields"]:
        out["fields"].pop()
    if total_chars(out) > LIMITS["total"]:
        room = LIMITS["total"] - (total_chars(out) - len(out.get("description", "")))
        out["description"] = _cut(out.get("description", ""), max(1, room))
    return out


def total_chars(card: dict) -> int:
    return (len(card.get("title", "")) + len(card.get("description", "")) + len((card.get("footer") or {}).get("text", ""))
            + len((card.get("author") or {}).get("name", ""))
            + sum(len(f.get("name", "")) + len(f.get("value", "")) for f in card.get("fields") or []))


def card(title: str, *, description: str = "", color: int = GOLD, fields=(), source: str = "",
         now: datetime | None = None, image: str = "", author: str = "") -> dict:
    now = now or datetime.now(timezone.utc)
    out = {"title": title, "description": description, "color": color, "fields": list(fields),
           "timestamp": now.astimezone(timezone.utc).isoformat(),
           "footer": {"text": "Star" + (f" · {source}" if source else "")}}
    if author:
        out["author"] = {"name": author}
    if image:
        out["image"] = {"url": image}
    return fit(out)


def card_text(card: dict) -> str:
    """The same content as plain text, for when a card cannot be sent."""
    lines = [f"**{card.get('title', '')}**"]
    if card.get("description"):
        lines.append(card["description"])
    lines += [f"{f['name']}: {f['value']}" for f in card.get("fields") or []]
    return "\n".join(lines)[:1990]


def field(name: str, value: object, inline: bool = True) -> dict:
    return {"name": name, "value": str(value), "inline": inline}


# ------------------------------------------------------------------ the cards

LEVEL_COLOR = {"good": GREEN, "info": GOLD, "warn": AMBER, "bad": RED}


def _issue_lines(report) -> str:
    return "\n\n".join(f"{'❌' if i.level == 'bad' else '⚠️'} {i.text}" for i in report.issues[:6])


def status_card(report, *, source: str = "live status", now: datetime | None = None) -> dict:
    """Live status ("what are you doing"): a one-line verdict as the title, what needs a look (or one warm line)
    underneath, then a few short fields. The color is the worst real problem's, green when nothing needs him."""
    return card(report.headline, description=_issue_lines(report) or report.note, color=LEVEL_COLOR[report.level],
                fields=report.fields, source=source, now=now, author="Star · how I'm doing")


def digest_card(when: str, text: str, report, *, now: datetime | None = None) -> dict:
    """The morning/evening note: the verdict as the title, her words, what needs a look (when her words did not
    already say it), then the numbers."""
    fields = list(report.fields)
    if report.issues and not all(issue.text in text for issue in report.issues[:6]):
        fields.insert(0, {"name": "Worth a look", "value": _issue_lines(report), "inline": False})
    return card(report.headline, description=text, color=LEVEL_COLOR[report.level], fields=fields,
                source="live status", now=now, author="Star · " + ("morning note" if when == "morning" else
                                                                       "evening note"))


# A title per kind of change and level: "Good news" only when everything in the DM is good news.
_ALERT_TITLES = {("down", "bad"): "❌ Something stopped", ("up", "good"): "✅ Back up and running",
                 ("restart", "warn"): "🔄 Something restarted", ("gate", "good"): "✅ I learned something new",
                 ("gate", "info"): "🧪 A lesson test finished", ("lab", "good"): "✅ Studio tests passed",
                 ("lab", "info"): "🎮 Studio tests finished", ("lab", "warn"): "⚠️ Studio tests went badly",
                 ("watchdog", "info"): "🔄 Knowledge search restarted", ("watchdog", "bad"): "❌ Knowledge search is down",
                 ("release", "good"): "✅ New release"}
_ONE_TITLES = {"bad": "❌ Something needs you", "warn": "⚠️ Heads up", "good": "✅ Good news", "info": "📝 An update"}
_MANY_TITLES = {"bad": "❌ Something needs you", "warn": "⚠️ A few things to know", "good": "✅ Good news",
                "info": "📝 A few updates"}
_RANK = {"good": 0, "info": 1, "warn": 2, "bad": 3}
_BULLET = {"bad": "❌", "warn": "⚠️", "good": "✅"}


def alert_card(events: list[tuple[str, str, str]], *, now: datetime | None = None) -> dict:
    """Immediate DM from (event id, plain text, level) changes. The color and title follow the worst level, so
    "Good news" appears only when every change in it is good news."""
    level = max((e[2] for e in events), key=lambda lvl: _RANK.get(lvl, 1), default="info")
    if len(events) == 1:
        title = _ALERT_TITLES.get((events[0][0].split(":")[0], level), _ONE_TITLES.get(level, "📝 An update"))
        description = events[0][1]
    else:
        title = _MANY_TITLES.get(level, "📝 A few updates")
        description = "\n".join(f"{_BULLET.get(e[2], '•')} {e[1]}" for e in events[:20])
    return card(title, description=description, color=LEVEL_COLOR.get(level, GOLD), source="live status", now=now)


def _numbers(value, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten a small result dict (e.g. starkb eval's summary) into (name, number) pairs."""
    out = []
    if isinstance(value, dict):
        for key, inner in value.items():
            out += _numbers(inner, f"{prefix} {key}".strip())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out.append((prefix, f"{value:.3g}" if isinstance(value, float) else str(value)))
    return out


def job_card(label: str, ok: bool, parts: list[str], *, summary: dict | None = None, now: datetime | None = None) -> dict:
    """An action's result: green done / red failed, one field per brain, numbers as inline fields."""
    fields = []
    for part in parts:
        name, _, rest = part.partition(": ")
        fields.append(field(name.capitalize() if name.startswith("brain") else "Result", rest or part, inline=False))
    for name, number in _numbers(summary or {})[:12]:
        fields.append(field(name, number))
    return card(("Done: " if ok else "Didn't work: ") + label, color=GREEN if ok else RED, fields=fields,
                source="brain gate", now=now)


def confirm_card(label: str, *, now: datetime | None = None) -> dict:
    return card(f"Confirm: {label}?", description="This can interrupt work in progress. The buttons work for 2 minutes.",
                color=AMBER, source="waiting for you", now=now)


def pr_card(feed_age: float, prs: list[dict], merged: list[dict], *, number: int | None = None,
            now: datetime | None = None) -> dict:
    """PR / merge-queue status from the PC feed."""
    shown = [p for p in prs if number is None or p.get("number") == number]
    failing = sum(1 for p in prs if p.get("checks") == "failing")
    fields = [field("Open", len(prs)), field("Failing checks", failing), field("Merged today", len(merged))] if number is None else []
    for p in shown[:8]:            # the overview lists the first eight; ask for one number for its detail
        state = {"passing": "✅ passing", "failing": "❌ failing", "pending": "⏳ pending"}.get(p.get("checks") or "", "no checks")
        fields.append(field(f"#{p.get('number')} {p.get('title', '')}"[:250],
                            f"{'draft' if p.get('draft') else 'ready'} · {state} · {p.get('merge') or '?'}", inline=False))
    color = RED if any(p.get("checks") == "failing" for p in shown) else GREEN if shown else GOLD
    return card("Pull requests" if number is None else f"PR #{number}", color=color, fields=fields,
                source=f"GitHub via the PC, {int(feed_age)} s old", now=now)


def drawing_card(prompt: str, filename: str, *, seconds: float | None = None, now: datetime | None = None) -> dict:
    """A finished picture: the image inside the card, the prompt as the description."""
    fields = [field("Took", f"{seconds:.0f} s")] if seconds else []
    return card("Here's your picture", description=prompt, fields=fields, source="drawn on your PC's GPU", now=now,
                image=f"attachment://{filename}")


def to_json(card: dict) -> str:
    return json.dumps(card, ensure_ascii=False)
