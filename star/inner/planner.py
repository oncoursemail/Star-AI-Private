"""Her day: a plan of blocks (study / practise / play / social / create / rest), an energy model, and the choice of
the next activity from STAR Home's registry.

Plan (made once per day, at her first tick after waking): blocks of `block_hours` from `wake_hour` to `sleep_hour`.
Each block's category is drawn (seeded by the date, so a day's plan is stable and tests are exact) from
  category weight = sum of her interest weights in it (only categories with an activity she can run)
                    x time of day (study/practise mornings, create afternoons, play/social evenings)
                    x owner's free hours (social/play lean there) x mood (low mood -> comfort; high arousal -> play)
                    x yesterday's lessons (something still unsolved -> practise)
with variety rules: never the same category twice in a row, at most 3 blocks of one category, at least one rest block.

Energy 0..1: activities spend it per minute (create/practise most, social least; low mood costs 20 % more), idle
time gives back 0.1 an hour, a night's sleep resets it to 1.0 (0.7 without the night job). Below 0.45 demanding
categories are halved; below 0.25 she only rests. Compute is bounded by `max_active_minutes` a day on top of
STAR Home's own sessions_per_day / pause_minutes.
"""
from __future__ import annotations

import json
import random
import time

from .stream import MemoryStream

CATEGORIES = ("study", "practise", "play", "social", "create", "rest")
CATEGORY_OF = {"research": "study", "watch_videos": "study", "watch": "study", "practice": "practise",
               "play_games": "play", "use_apps": "play", "chat_with_friends": "social", "game_making": "create",
               "drawing": "create", "music": "create", "inner_life": "rest"}
DEMANDING = ("create", "practise", "study")
COST = {"create": 0.0045, "practise": 0.0045, "study": 0.0035, "play": 0.003, "social": 0.0025, "rest": -0.01}
RECOVER_PER_HOUR = 0.1
_TIME_OF_DAY = {
    "morning": {"study": 1.4, "practise": 1.3, "create": 1.0, "play": 0.7, "social": 0.6, "rest": 0.4},
    "afternoon": {"study": 0.9, "practise": 1.0, "create": 1.4, "play": 1.0, "social": 0.8, "rest": 0.8},
    "evening": {"study": 0.6, "practise": 0.6, "create": 0.9, "play": 1.3, "social": 1.4, "rest": 0.7},
}


def category_of(interest: str) -> str:
    return CATEGORY_OF.get(interest, "play")


def local_hour(ts: float) -> float:
    t = time.localtime(ts)
    return t.tm_hour + t.tm_min / 60.0


def day_of(ts: float, wake_hour: int) -> str:
    """Her day starts when she wakes: before `wake_hour` it is still yesterday."""
    t = time.localtime(ts)
    if t.tm_hour < wake_hour:
        t = time.localtime(ts - 86400)
    return time.strftime("%Y-%m-%d", t)


def asleep(ts: float, settings: dict) -> bool:
    hour = time.localtime(ts).tm_hour
    sleep, wake = int(settings["sleep_hour"]), int(settings["wake_hour"])
    return (sleep <= hour < wake) if sleep < wake else (hour >= sleep or hour < wake)


def _part(hour: float) -> str:
    hour %= 24
    return "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening"


def _owner_free(hour: float, spans) -> bool:
    hour %= 24
    return any(isinstance(s, (list, tuple)) and len(s) == 2 and s[0] <= hour < s[1] for s in spans)


def mood_factor(category: str, valence: float, arousal: float) -> float:
    f = 1.0
    if valence < -0.2:
        f *= {"play": 1.3, "social": 1.3, "rest": 1.3, "practise": 0.7}.get(category, 1.0)
    if arousal > 0.6:
        f *= {"play": 1.2, "create": 1.2, "rest": 0.7}.get(category, 1.0)
    elif arousal < 0.25:
        f *= {"rest": 1.2, "study": 1.2}.get(category, 1.0)
    return f


def make_plan(day: str, settings: dict, interests: dict, available: set[str], *, valence: float = 0.0,
              arousal: float = 0.35, practise_bonus: bool = False) -> dict:
    wake, sleep, step = int(settings["wake_hour"]), int(settings["sleep_hour"]), max(1, int(settings["block_hours"]))
    end = sleep + 24 if sleep <= wake else sleep
    base = {c: 0.0 for c in CATEGORIES}
    for name in available:
        base[category_of(name)] += float((interests.get(name) or {}).get("weight", 1.0))
    base["rest"] = max(base["rest"], 0.8)
    rng = random.Random(f"plan:{day}")
    blocks, counts = [], {c: 0 for c in CATEGORIES}
    for start in range(wake, end, step):
        hour = start + step / 2
        weights = {}
        for c in CATEGORIES:
            w = base[c] * _TIME_OF_DAY[_part(hour)][c] * mood_factor(c, valence, arousal)
            if c in ("social", "play") and _owner_free(hour, settings.get("owner_free_hours", [])):
                w *= 1.4 if c == "social" else 1.2
            if c == "practise" and practise_bonus:
                w *= 1.3
            if (blocks and blocks[-1]["category"] == c) or counts[c] >= 3:
                w = 0.0
            weights[c] = w
        names = [c for c in CATEGORIES if weights[c] > 0] or ["rest"]
        pick = rng.choices(names, weights=[weights.get(c, 1.0) or 1.0 for c in names], k=1)[0]
        counts[pick] += 1
        why = [f"{_part(hour)}"]
        if _owner_free(hour, settings.get("owner_free_hours", [])) and pick in ("social", "play"):
            why.append("owner usually free")
        if valence < -0.2 and pick in ("play", "social", "rest"):
            why.append("low mood: something comforting")
        blocks.append({"start": start % 24, "end": min(start + step, end) % 24, "category": pick,
                       "why": ", ".join(why)})
    if not any(b["category"] == "rest" for b in blocks) and blocks:
        nearest = min(blocks, key=lambda b: abs(((b["start"] - wake) % 24) - (15 - wake) % 24))
        nearest["category"], nearest["why"] = "rest", "afternoon break (every day has one)"
    return {"day": day, "blocks": blocks, "mood": {"valence": round(valence, 3), "arousal": round(arousal, 3)}}


def block_at(plan: dict, ts: float) -> dict | None:
    hour = time.localtime(ts).tm_hour
    for b in plan.get("blocks", []):
        s, e = b["start"], b["end"]
        if (s <= hour < e) if s < e else (hour >= s or hour < e):
            return b
    return None


class Energy:
    """Persisted in the memory stream's meta table."""

    def __init__(self, stream: MemoryStream) -> None:
        self.stream = stream

    def level(self, now: float) -> float:
        value = float(self.stream.meta("energy", "1.0") or 1.0)
        since = float(self.stream.meta("energy_ts", str(now)) or now)
        return round(min(1.0, value + RECOVER_PER_HOUR * max(0.0, now - since) / 3600.0), 4)

    def set(self, value: float, now: float) -> float:
        value = round(min(1.0, max(0.0, value)), 4)
        self.stream.set_meta("energy", value)
        self.stream.set_meta("energy_ts", now)
        return value

    def spend(self, category: str, minutes: float, now: float, *, valence: float = 0.0) -> float:
        cost = COST.get(category, 0.003) * max(0.0, minutes)
        if cost > 0 and valence < -0.2:
            cost *= 1.2
        return self.set(self.level(now) - cost, now)

    def wake(self, now: float, slept: bool) -> float:
        return self.set(1.0 if slept else 0.7, now)


def load_plan(stream: MemoryStream, day: str) -> dict | None:
    try:
        raw = stream.meta(f"plan:{day}")
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def choose(plan: dict, now: float, available: set[str], scores: dict[str, float], energy: float, settings: dict,
           *, active_minutes: float = 0.0, multipliers: dict[str, float] | None = None,
           rng: random.Random | None = None) -> tuple[str | None, str]:
    """(interest or None to rest, why). `scores` are star-home's Life.scores (weight x novelty x open-goal bonus)."""
    if asleep(now, settings):
        return None, "sleeping"
    if active_minutes >= float(settings["max_active_minutes"]):
        return None, f"done enough for today ({int(active_minutes)} active minutes)"
    if energy < 0.25:
        return None, f"tired (energy {energy:.2f}): resting"
    block = block_at(plan, now) or {"category": "play", "why": "outside the plan"}
    category = block["category"]
    if category == "rest":
        return None, "rest block"
    pool = [i for i in available if category_of(i) == category and i in scores]
    why = f"{category} block ({block['why']})"
    if not pool:
        totals = {}
        for i in available:
            if i in scores and category_of(i) != "rest":
                totals[category_of(i)] = totals.get(category_of(i), 0.0) + scores[i]
        if not totals:
            return None, f"{category} block, but nothing can run now"
        fallback = max(sorted(totals), key=lambda c: totals[c])
        pool = [i for i in available if category_of(i) == fallback and i in scores]
        why = f"{category} block, nothing for it can run now: {fallback} instead"
    weights = []
    for i in sorted(pool):
        w = scores[i] * (multipliers or {}).get(i, 1.0)
        if energy < 0.45 and category_of(i) in DEMANDING:
            w *= 0.5
        weights.append(max(w, 1e-6))
    pick = (rng or random.Random()).choices(sorted(pool), weights=weights, k=1)[0]
    if energy < 0.45:
        why += f", a bit tired (energy {energy:.2f})"
    return pick, why
