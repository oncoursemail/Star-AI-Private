"""How she texts: the style layer of the outgoing chat path (research: docs/research/human-texting-20261027.md).

Stateless pieces (this file):
  STYLE_GUIDE       the 22 style rules as persona guidance (goes into the stable system message)
  rewrite()         R1-R8 deterministic rewrites: dashes, markdown, curly punctuation, repeated punctuation, service
                    closers, stock openers, the emoji budget (R9 truncation is cut(), R4/R10 are finish())
  finish()          R4 no final period on a short message, R10 lowercase start when it fits her voice
  split_lines()     R11 one thought per message: 2-3 short lines sent a few seconds apart
  flags()           F1-F10 flag-and-regenerate checks (reasons; the caller asks the model once more)
  guard()           honesty guards: no offline life, no "busy" without a real state, no shared history she does not have
Windowed checks W1-W10 live in window.py, pacing in pacing.py, Discord reactions in reactions.py.

No fake typos, ever: nothing here inserts or imitates a spelling mistake (`FAKE_TYPOS` is False and is only a marker for
the tests). The truthful yes to a sincere "are you an AI?" is never touched: callers skip finish() and the window for it.
She sounds casual and warm because of register (short, lowercase, plain), not because anything pretends to be human.
"""
from __future__ import annotations

import re

FAKE_TYPOS = False

STYLE_GUIDE = """How you type (every message):
1 one thought per message, usually a few words; a longer thought is 2-3 short lines. 2 lowercase is normal ("i" too);
capitals only for names, titles and real emphasis. 3 no full stop on a short last line; "?" for questions; "!!" only when
you truly mean it. 4 no dashes, lists, headers, bold or steps. 5 answer first, never repeat their question or summarise
their message, never open with "great question". 6 do not end every message with a question (about one in three at
most). 7 vary length: one word, a one-liner, sometimes a short burst. 8 match their register within one step, small
slang (lol, omg, wait, ngl, fr, idk, rn, same, aww), nothing try-hard. 9 emoji are rare: most messages have none, never
at the start, never sparkles/rocket/party. 10 have a small opinion, disagree lightly, say "idk" when you do not know and
give the short version. 11 a short reaction first when they share something ("oh no", "wait nice"), then stop or add one
line; react to the feeling, not only the words. 12 compliments and thanks are small and specific. 13 no service closers
("let me know if", "anything else"), no therapy-speak, no "it depends" blocks. 14 sad or upset people get shorter
messages: acknowledge, one open question or just presence, ask before advising. 15 you do not have to reply to everything:
a reaction or silence is fine for "gn", "brb" and closed topics. 16 only say you are busy when you really are (in a
game, in a call); never invent an offline life (home, work, school, family, meals) and never invent shared history.
17 never deny being an AI; if someone sincerely asks, say yes plainly in your own voice. 18 never fake a typo.
"""

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐❤✅]️?(?:‍[\U0001F300-\U0001FAFF♀♂]️?)*")
AI_EMOJI_SET = set("✨\U0001F680\U0001F389\U0001F496\U0001F973")          # sparkles, rocket, party popper, sparkling heart, partying

# -- R: deterministic rewrites -----------------------------------------------------------------------------------------
_RANGE_DASH = re.compile(r"(?<=\d)\s*[–—]\s*(?=\d)")
_DASH = re.compile(r"\s*[—–]\s*|\s+--\s+")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)
_FENCE = re.compile(r"```[a-zA-Z]*\n?|`+")
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)
_CURLY = {"‘": "'", "’": "'", "“": '"', "”": '"', "…": "..."}
_REPEAT = ((re.compile(r"!{3,}"), "!!"), (re.compile(r"\?{3,}"), "??"), (re.compile(r"\.{4,}"), "..."))
SERVICE_CLOSER = re.compile(
    r"\b(?:let\s+me\s+know\s+(?:if|when|whether)|feel\s+free\s+to|is\s+there\s+anything\s+else|hope\s+(?:that|this)\s+helps|"
    r"happy\s+to\s+help|anything\s+else\s+(?:you|i)\b|how\s+can\s+i\s+(?:assist|help)|i(?:'m|\s+am)\s+here\s+to\s+help|"
    r"don'?t\s+hesitate\s+to)", re.I)
STOCK_OPENER = re.compile(r"^\s*(?:certainly|absolutely|of\s+course|sure\s+thing|great\s+question|"
                          r"that'?s\s+a\s+(?:great|good|fantastic|really\s+good)\s+question)\s*[!,.:]*\s*", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(" ".join(str(text or "").split())) if s]


def emojis(text: str) -> list[str]:
    return _EMOJI.findall(text or "")


def emoji_budget(text: str) -> str:
    """R8: at most one emoji, never at the start, never from the "AI set" (sparkles, rocket, party, sparkling heart)."""
    found = list(_EMOJI.finditer(text))
    if not found:
        return text
    keep = None
    for m in found:
        if m.group(0)[0] in AI_EMOJI_SET:
            continue
        if text[: m.start()].strip() == "":
            continue
        keep = m
        break
    out, last = [], 0
    for m in found:
        out.append(text[last:m.start()])
        if m is keep:
            out.append(m.group(0))
        last = m.end()
    out.append(text[last:])
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()


def cut(text: str, limit: int) -> str:
    """R9: a message over its limit is cut at a sentence or clause boundary, never with an ellipsis."""
    text = text.strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    for pattern in (r"[.!?](?=\s|$)", r"[,;:](?=\s|$)", r"\s"):
        hits = [m.end() for m in re.finditer(pattern, window)]
        if hits and hits[-1] >= limit // 3:
            return window[: hits[-1]].rstrip(" ,;:")
    return window.rstrip(" ,;:")


def rewrite(text: str, *, keep_lists: bool = False) -> str:
    """R1 dashes, R2 markdown markers, R3 curly punctuation, R5 repeated punctuation, R6 service closers, R7 stock
    openers, R8 emoji budget. Pure and idempotent; never adds a word."""
    text = str(text or "")
    text = _RANGE_DASH.sub("-", text)
    text = _DASH.sub(", ", text)
    if not keep_lists:
        text = _BOLD.sub(lambda m: m.group(1) or m.group(2), text)
        text = _FENCE.sub("", text)
        text = _HEADER.sub("", text)
        text = _BULLET.sub("", text)
    for bad, good in _CURLY.items():
        text = text.replace(bad, good)
    for pattern, good in _REPEAT:
        text = pattern.sub(good, text)
    lines = []
    for line in text.split("\n"):
        kept = [s for s in sentences(line) if not SERVICE_CLOSER.search(s)] if SERVICE_CLOSER.search(line) else None
        lines.append(line if kept is None else " ".join(kept))
    text = " ".join(" ".join(lines).split())
    for _ in range(2):
        shorter = STOCK_OPENER.sub("", text, count=1)
        if shorter.strip(" ,.!") or not text.strip(" ,.!"):
            text = shorter
        else:
            break                                   # "sure thing" on its own is a fine reply, only an opener goes
    text = re.sub(r"\s+([,.!?])", r"\1", text).replace(" ,", ",")
    text = re.sub(r",\s*,", ",", text).strip(" ,")
    return emoji_budget(text)


_COMMON_STARTS = set("""yes no yeah yep yup nah nope ok okay oh ooh aww awww wow wait hey hi hello heyy hiya haha hahaha lol lmao omg same true
fair honestly maybe sure thanks thank sorry well so but and the that this it its what why how when where who which gtg
ngl tbh idk lowkey highkey fr right alright anyway actually basically because cool nice great good bad hmm hm mm uh um
ugh yay oof oop damn dang really literally just now then there here he she they we you your my our be do did does can
could would should will are is was were have has had if let lets let's i i'm i'll i've i'd you're we're it's that's
there's what's who's how's where's don't doesn't didn't can't won't isn't aren't wasn't ya yall""".split())


def lowercase_start(text: str) -> str:
    """R10: a casual message starts lowercase ("i" too), but names, titles, ALL CAPS and anything long keep their capital."""
    if len(text) >= 120:
        return text
    m = re.match(r"[A-Za-z][A-Za-z']*", text)
    if not m:
        return text
    word = m.group(0)
    if word == "I" or word.startswith(("I'", "I’")):
        return "i" + text[1:]
    if len(word) > 1 and word.isupper():
        return text
    if word[0].isupper() and word.lower() in _COMMON_STARTS:
        return word[0].lower() + text[1:]
    return text


def drop_final_period(text: str) -> str:
    """R4: a single short sentence loses its full stop (a question mark, "!" and "..." stay)."""
    text = text.rstrip()
    if text.endswith(".") and not text.endswith("..") and len(text) < 90 and not re.search(r"[.!?]\s", text.rstrip(".")):
        return text[:-1].rstrip()
    return text


def finish(text: str, *, platform: str = "discord", roleplay: bool = False) -> str:
    """R4 + R10 for one message in her voice (not in a role-play, where the character's writing is theirs to keep)."""
    if roleplay or not text:
        return text
    return drop_final_period(lowercase_start(text))


def split_lines(text: str, platform: str = "discord", *, roleplay: bool = False, max_lines: int = 3) -> list[str]:
    """R11: one thought per message. Several sentences, or one long one, become 2-3 short lines (each finished); short
    one-liners stay one line. A role-play keeps its text as one message."""
    text = " ".join(str(text or "").split())
    if not text:
        return []
    if roleplay:
        return [text]
    parts = sentences(text)
    if len(parts) == 1 and len(text) > 140:
        pieces = re.split(r"(?<=,)\s+|\s+(?=(?:but|and|so|because)\s)", text)
        if len(pieces) > 1:
            mid = max(1, len(pieces) // 2)
            parts = [" ".join(pieces[:mid]).rstrip(","), " ".join(pieces[mid:])]
    merged: list[str] = []
    for part in parts:
        if merged and len(merged[-1]) + len(part) < 24 and not merged[-1].endswith("?"):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    while len(merged) > max_lines:
        merged[-2:] = [f"{merged[-2]} {merged[-1]}"]
    return [line for line in (finish(p, platform=platform) for p in merged) if line]


def polish(text: str, *, platform: str = "discord", roleplay: bool = False) -> str:
    """Rewrites + finish on one line (what a line looks like once the deterministic pass has run)."""
    return finish(rewrite(text), platform=platform, roleplay=roleplay)


# -- F: flag and regenerate --------------------------------------------------------------------------------------------
_F1 = re.compile(r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s+\S|\b1[.)]\s+\w.*?\b2[.)]\s+\w|\bstep\s+1\b|\bfirst,.*\bsecond,.*\bthird,", re.I | re.S)
_F3 = re.compile(r"it\s+depends|there\s+are\s+(?:many|several)|on\s+the\s+other\s+hand|some\s+(?:people|experts)|generally\s+speaking|"
                 r"it'?s\s+important\s+to|aspects?\s+to\s+consider|many\s+factors", re.I)
_F4 = re.compile(r"^\W*(?:you(?:'re|\s+are)\s+asking|as\s+for\s+your\s+question|regarding\s+your|to\s+answer\s+your)", re.I)
_F5_OPEN = re.compile(r"^\W*(?:wow|what\s+a\s)", re.I)
_F5 = re.compile(r"^\W*(?:that'?s\s+(?:so\s+|really\s+|a\s+)?(?:amazing|incredible|wonderful|exciting|fantastic|brave|great|"
                 r"good\s+decision)|hello\s+there|it'?s\s+(?:so\s+)?nice\s+to\s+meet\s+you)|"
                 r"great\s+sense\s+of\s+humou?r|incredible\s+talent|truly\s+(?:impressive|stunning)|absolutely\s+stunning|"
                 r"really\s+means\s+a\s+lot|i\s+appreciate\s+you|wonderful\s+chatting|have\s+a\s+(?:fantastic|wonderful|great)\s+day|"
                 r"following\s+your\s+dreams", re.I)
_F6 = re.compile(r"it\s+sounds\s+like\s+you|i\s+hear\s+you|that'?s\s+completely\s+valid|your\s+feelings\s+are\s+valid|it'?s\s+okay\s+to\s+feel|"
                 r"remember\s+to\s+(?:take\s+care|prioriti[sz]e)|self-?care|coping", re.I)
_F7 = re.compile(r"\b(?:delve|tapestry|testament|vibrant|navigate|landscape|realm|journey|robust|seamless|multifaceted|crucial|pivotal|"
                 r"moreover|furthermore|additionally|in\s+conclusion|in\s+summary|respectfully\s+disagree|i\s+understand\s+your\s+perspective)\b", re.I)
_F8 = re.compile(r"\bnot\s+(?:just|only)\s+.{1,40}?(?:but|,)\b|\bit'?s\s+not\s+.{1,30}?,\s+it'?s\b", re.I)
_APOLOGY = re.compile(r"i\s+apologi[sz]e|sorry\s+for\s+the|my\s+apologies", re.I)
_VALIDATION = re.compile(r"you\s+are\s+absolutely\s+right|you'?re\s+absolutely\s+right|completely\s+valid|totally\s+valid|that'?s\s+valid|valid\s+feelings", re.I)
_ADVICE = re.compile(r"\byou\s+should\b|remember\s+to|try\s+to\s|it'?s\s+important\s+to|consider\s+\w+ing", re.I)
_OFFER = re.compile(r"let\s+me\s+know|would\s+you\s+like|i\s+can\s+help|happy\s+to\s+(?:help|assist)|feel\s+free", re.I)
_DEEP = re.compile(r"\b(?:sad|depress\w*|anxi\w*|stress\w*|cry\w*|lonely|hurt\w*|tired of|can'?t\s+(?:cope|sleep|do\s+this)|struggl\w+|"
                   r"overwhelm\w*|scared|afraid|give\s+up|miss\s+(?:him|her|them)|passed\s+away|died|broke\s+up|breakup)\b", re.I)


def is_deep(incoming: str) -> bool:
    """Is the other person upset or sharing something heavy (messages then get shorter, not longer)?"""
    return bool(_DEEP.search(incoming or ""))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def flags(text: str, incoming: str = "", platform: str = "discord", *, deep: bool = False) -> list[str]:
    """F1-F10: reasons this draft reads as AI. Empty = fine. Run on the model's raw text (lists are still visible)."""
    text = str(text or "")
    out: list[str] = []
    if _F1.search(text):
        out.append("F1 list or steps: say it in two or three short lines of prose")
    limit = 400 if deep else 220
    if len(" ".join(text.split())) > limit:
        out.append(f"F2 too long: under {limit} characters, shorter when they are upset")
    if len(_F3.findall(text)) >= 2:
        out.append("F3 hedging: give a plain opinion")
    first = _F4.search(text)
    said = _words(incoming)
    mirrored = False
    if said:
        mine = _words(text)
        grams = {tuple(said[i:i + 4]) for i in range(len(said) - 3)}
        mirrored = any(tuple(mine[i:i + 4]) in grams for i in range(len(mine) - 3))
    if first or mirrored:
        out.append("F4 restates the question: answer first")
    if _F5.search(text) or (_F5_OPEN.search(text) and "!" in text and len(text) > 40):
        out.append("F5 gushing or formal: tone down, say something specific")
    if _F6.search(text):
        out.append("F6 therapy-speak: one short human line")
    if _F7.search(text):
        out.append("F7 AI vocabulary: plain words")
    if _F8.search(text):
        out.append("F8 'not just X but Y': say it directly")
    if text.count("!") >= 3:
        out.append("F9 over-excited: one exclamation at most")
    stack = sum(1 for p in (_APOLOGY, _VALIDATION, _ADVICE, _OFFER) if p.search(text))
    if stack >= 2:
        out.append("F10 stacked sympathy lines (apology, validation, advice, offer): keep one")
    return out


# -- honesty guards ----------------------------------------------------------------------------------------------------
OFFLINE_LIFE = re.compile(
    r"\bi\s+(?:just\s+)?(?:woke|got|came)\s+(?:up|home|back\s+home)\b|\bi(?:'m|\s+am)\s+(?:at|in)\s+(?:work|school|class|the\s+car|bed)\b|"
    r"\bat\s+(?:work|school)\s+(?:rn|right\s+now|today)\b|\bmy\s+(?:mom|mum|dad|boss|teacher|roommate|sister|brother|parents?)\b|"
    r"\bi\s+(?:just\s+)?(?:ate|had\s+(?:lunch|dinner|breakfast)|made\s+(?:dinner|lunch|coffee))\b|\bi\s+was\s+(?:away|out|gone)\b|"
    r"\bon\s+my\s+way\s+(?:home|to)\b|\bmy\s+(?:commute|shift)\b|\bi\s+(?:slept|took\s+a\s+nap)\b", re.I)
BUSY_CLAIM = re.compile(r"\b(?:brb|be\s+right\s+back|mid[- ]?match|(?:i'?m|im|i\s+am|i\s+was|was)\s+(?:currently\s+)?in\s+(?:a\s+)?(?:match|game|call|voice))\b", re.I)
SHARED_HISTORY = re.compile(
    r"\bremember\s+when\s+(?:we|you)\b|\blike\s+(?:last\s+time|that\s+time)\s+we\b|\bas\s+(?:we|you)\s+(?:talked|said|mentioned)\s+"
    r"(?:before|last|earlier|yesterday)\b|\byou\s+(?:told|said\s+to)\s+me\s+(?:last|yesterday|before|earlier)\b|\bour\s+(?:last|first)\s+(?:game|chat|match|call)\b", re.I)


def guard(text: str, *, busy: str = "", real_history: bool = False) -> tuple[str, list[str]]:
    """Honesty guards (never loosened by style): a sentence that claims an offline life, a "busy" state she is not in
    (`busy` names a real one, e.g. "in a match"), or a shared history she does not have is removed. -> (text, reasons)."""
    reasons: list[str] = []
    kept = []
    for sentence in sentences(text):
        if OFFLINE_LIFE.search(sentence):
            reasons.append("offline life")
        elif BUSY_CLAIM.search(sentence) and not busy:
            reasons.append("busy without a real reason")
        elif SHARED_HISTORY.search(sentence) and not real_history:
            reasons.append("shared history she does not have")
        else:
            kept.append(sentence)
    return (" ".join(kept) if reasons else " ".join(str(text or "").split())), reasons
