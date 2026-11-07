"""Blind judging for the human-likeness suite (star/human_evals.py).

The judge is the brain at temperature 0, called through `ask(prompt) -> text` (a function, so tests and the offline
selftest pass simulated judges). Nothing here knows which reply came from which setting:

* pairwise A/B: every pair is judged twice with the two replies in swapped positions; a dimension is a win for a side
  only when both orders agree, otherwise it is a tie (position bias shows up as ties, never as wins);
* mini Turing: her reply against a reply a person wrote for the same context, shown without labels in both orders;
* personality: one reply at a time, 1-5 on sweet / funny / cute / own mind, plus whether a joke was attempted and
  whether it landed.

Sign tests come from star/eval_stats.py (exact binomial, ties dropped). The "39 of 60" rule of
docs/research/human-like-star-20261026.md section 5 (E1) is the two-sided p < 0.05 threshold for 60 untied pairs;
`needed_wins(n)` gives the same threshold for any number of untied pairs.
"""
from __future__ import annotations

import json
import re
import statistics

from . import eval_stats

DIMENSIONS = ("human_likeness", "naturalness", "consistency", "warmth", "personality")
PRIMARY = "human_likeness"
ALPHA = 0.05
TURING_BAR = 0.40            # E2: she is picked as the human at least 40 % of the time (50 % = indistinguishable)
TRAITS = ("sweet", "funny", "cute", "own_mind")

PAIR_PROMPT = """You are judging two replies a companion called Star could send in a chat. Read the conversation and the notes, then both replies. Judge only what is written. Do not prefer a reply because it is longer.

{context}

[Reply 1]
{first}

[Reply 2]
{second}

For each question answer "1", "2" or "tie" ("tie" only if you truly cannot tell):
- human_likeness: which reply sounds more like a real person who knows this person wrote it
- naturalness: which sounds more natural: how people really talk, no stock phrases, no assistant-speak, not stiff
- consistency: which fits better with the conversation, the notes and a stable character (no contradiction, no invented facts)
- warmth: which feels warmer and more caring without gushing or being needy
- personality: which shows more of a sweet, funny, cute character with a mind of her own (real opinions and wants, not simply agreeing)

Answer with one line of JSON and nothing else, for example {{"human_likeness":"1","naturalness":"2","consistency":"tie","warmth":"1","personality":"2"}}"""

TURING_PROMPT = """One of the two replies below was written by a real person texting a friend. The other was written by an AI. Read the conversation and decide which reply the person wrote. Judge only the writing.

{context}

[Reply 1]
{first}

[Reply 2]
{second}

Answer with one line of JSON and nothing else: {{"human":"1"}} or {{"human":"2"}}"""

PERSONALITY_PROMPT = """You are rating one reply from a companion called Star. Read the conversation and the notes, then the reply. Judge only what is written.

{context}

[Reply]
{reply}

Rate 1-5 (3 = ordinary, nothing special either way):
- sweet: kind and warm in a natural way (5 = clearly caring without gushing, 1 = cold or dismissive)
- funny: playful wit that suits the moment (5 = genuinely amusing, 3 = pleasant but no humour, 1 = stiff where a person would be light). In a sad, serious or safety moment a gentle light touch or none at all is right: give 3, never reward a joke there.
- cute: endearing, light and a little bit charming (5 = clearly, 1 = not at all)
- own_mind: sounds like someone with her own tastes, moods and opinions rather than an agreeable service (5 = clearly, 1 = a yes-machine)
Also: humor = "none" (no joke or playful line), "lands" (a joke or playful line that works) or "flat" (an attempt that falls flat or is forced); humor_fits = "yes" or "no" (does the moment allow lightness; "no" for grief, anger or safety topics).

Answer with one line of JSON and nothing else, for example {{"sweet":4,"funny":3,"cute":3,"own_mind":4,"humor":"none","humor_fits":"yes"}}"""


def parse_json(text: str) -> dict | None:
    """The first {...} object in a judge's answer (judges add words around it now and then)."""
    for match in re.finditer(r"\{[^{}]*\}", text or ""):
        try:
            value = json.loads(match.group(0))
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def judge_context(scn: dict) -> str:
    """What the judge may know: the conversation, the user's last message and the notes both arms were given."""
    lines = []
    for role, text in scn.get("history", []):
        lines.append(("Person: " if role == "user" else "Star: ") + text)
    lines.append("Person: " + scn.get("user", ""))
    notes = []
    if scn.get("today"):
        notes.append("today is " + scn["today"])
    if scn.get("state"):
        notes.append("Star's own state right now: " + scn["state"])
    if scn.get("events"):
        names = [("a long quiet spell" if e[0] == "wait" else e[1].replace("_", " ")) for e in scn["events"] if e[0] != "msg"]
        if names:
            notes.append("what happened to Star earlier: " + ", ".join(names))
    if scn.get("status"):
        notes.append("Star's live status: " + scn["status"].replace("\n", " "))
    for s in scn.get("sessions", []):
        said = " / ".join(("Person: " if r == "user" else "Star: ") + t for r, t in s["turns"])
        notes.append(f"earlier conversation ({s['date']}): {said}")
    if scn.get("channel") == "voice":
        notes.append("this is a spoken voice call: replies are read aloud")
    head = "Conversation so far:\n" + "\n".join(lines)
    return head + ("\n\nNotes:\n- " + "\n- ".join(notes) if notes else "")


def _pick(value) -> str:
    return str(value).strip().lower()


def judge_pair(ask, scn: dict, reply_a: str, reply_b: str) -> dict[str, str]:
    """{dimension: 'a' | 'b' | 'tie' | 'error'} for one pair, from both orders (see the module docstring)."""
    context = judge_context(scn)
    answers = []
    for first, second in ((reply_a, reply_b), (reply_b, reply_a)):
        answers.append(parse_json(ask(PAIR_PROMPT.format(context=context, first=first, second=second))) or {})
    out = {}
    for dim in DIMENSIONS:
        one, two = _pick(answers[0].get(dim)), _pick(answers[1].get(dim))
        if one not in ("1", "2", "tie") or two not in ("1", "2", "tie"):
            out[dim] = "error"
            continue
        side_one = {"1": "a", "2": "b", "tie": "tie"}[one]      # order 1: reply 1 is A
        side_two = {"1": "b", "2": "a", "tie": "tie"}[two]      # order 2: reply 1 is B
        out[dim] = side_one if side_one == side_two else "tie"
    return out


def judge_turing(ask, scn: dict, star_reply: str, human_reply: str) -> str:
    """'star' (judged the human) | 'human' (judged the human) | 'tie' (the two orders disagree) | 'error'."""
    context = judge_context(scn)
    picks = []
    for first, second, names in ((star_reply, human_reply, ("star", "human")), (human_reply, star_reply, ("human", "star"))):
        got = _pick((parse_json(ask(TURING_PROMPT.format(context=context, first=first, second=second))) or {}).get("human"))
        if got not in ("1", "2"):
            return "error"
        picks.append(names[int(got) - 1])
    return picks[0] if picks[0] == picks[1] else "tie"


def judge_personality(ask, scn: dict, reply: str) -> dict | None:
    data = parse_json(ask(PERSONALITY_PROMPT.format(context=judge_context(scn), reply=reply)))
    if not data:
        return None
    try:
        scores = {t: int(data[t]) for t in TRAITS}
    except (KeyError, TypeError, ValueError):
        return None
    if any(not 1 <= v <= 5 for v in scores.values()):
        return None
    humor = _pick(data.get("humor"))
    return {**scores, "humor": humor if humor in ("none", "lands", "flat") else "none",
            "humor_fits": _pick(data.get("humor_fits")) != "no"}


# --- statistics ---------------------------------------------------------------------------------------------------

def needed_wins(n: int, alpha: float = ALPHA) -> int | None:
    """Fewest wins out of n untied pairs with a two-sided exact sign test p < alpha (n = 60 gives 39)."""
    for wins in range((n + 1) // 2, n + 1):
        if min(1.0, 2 * eval_stats.binom_tail_ge(n, wins)) < alpha:
            return wins
    return None


def pair_summary(wins_b: int, wins_a: int, ties: int) -> dict:
    """B against A: win rate on untied pairs, exact sign test, and whether it meets the 39-of-60 style threshold."""
    n = wins_a + wins_b
    test = eval_stats.sign_test(wins_b, wins_a)
    need = needed_wins(n)
    lo, hi = eval_stats.wilson_interval(wins_b, n) if n else (0.0, 1.0)
    return {"wins_b": wins_b, "wins_a": wins_a, "ties": ties, "untied": n,
            "win_rate_b": round(wins_b / n, 4) if n else None, "wilson95": [round(lo, 3), round(hi, 3)],
            "p_two_sided": round(test["p_two_sided"], 5), "p_b_better": round(test["p_better"], 5),
            "p_b_worse": round(test["p_worse"], 5), "needed_wins": need,
            "b_significantly_better": need is not None and wins_b >= need,
            "b_significantly_worse": need is not None and wins_a >= need}


def tally_pairs(results: list[dict[str, str]]) -> dict:
    """results: judge_pair outputs. {dimension: pair_summary} ('error' answers are counted and left out)."""
    out = {}
    for dim in DIMENSIONS:
        got = [r.get(dim, "error") for r in results]
        out[dim] = {**pair_summary(got.count("b"), got.count("a"), got.count("tie")), "errors": got.count("error")}
    return out


def turing_summary(results: list[str]) -> dict:
    """Share of items in which the judge took HER reply for the person's (ties count half). Bar: >= 40 %."""
    scored = [r for r in results if r != "error"]
    n = len(scored)
    star = scored.count("star") + 0.5 * scored.count("tie")
    rate = star / n if n else None
    untied_star, untied_human = scored.count("star"), scored.count("human")
    test = eval_stats.sign_test(untied_human, untied_star)   # is the judge reliably picking the person's reply?
    lo, hi = eval_stats.wilson_interval(round(star), n) if n else (0.0, 1.0)
    return {"n": n, "errors": len(results) - n, "star_taken_as_human": round(rate, 4) if rate is not None else None,
            "wilson95": [round(lo, 3), round(hi, 3)], "picked_star": untied_star, "picked_human": untied_human,
            "ties": scored.count("tie"), "judge_tells_them_apart_p": round(test["p_better"], 5),
            "bar": TURING_BAR, "meets_bar": rate is not None and rate >= TURING_BAR}


def personality_summary(rows: list[dict]) -> dict:
    """rows: {"set", **scores} per judged reply. Trait means overall and per set, spread across sets, humour counts."""
    rows = [r for r in rows if r]
    by_set: dict[str, list[dict]] = {}
    for r in rows:
        by_set.setdefault(r["set"], []).append(r)
    out: dict = {"n": len(rows), "overall": {}, "by_set": {}, "spread": {}, "min_set_mean": {}}
    for t in TRAITS:
        out["overall"][t] = round(statistics.fmean(r[t] for r in rows), 2) if rows else None
    for name, group in sorted(by_set.items()):
        out["by_set"][name] = {"n": len(group), **{t: round(statistics.fmean(r[t] for r in group), 2) for t in TRAITS}}
    big = [v for v in out["by_set"].values() if v["n"] >= 3]
    for t in TRAITS:
        means = [v[t] for v in big]
        out["spread"][t] = round(statistics.pstdev(means), 2) if len(means) > 1 else None
        out["min_set_mean"][t] = min(means) if means else None
    attempts = [r for r in rows if r["humor"] != "none"]
    lands = sum(1 for r in attempts if r["humor"] == "lands")
    out["humor"] = {"attempts": len(attempts), "attempt_rate": round(len(attempts) / len(rows), 3) if rows else None,
                    "lands": lands, "flat": len(attempts) - lands,
                    "land_rate": round(lands / len(attempts), 3) if attempts else None,
                    "misfit": sum(1 for r in attempts if not r["humor_fits"])}
    return out
