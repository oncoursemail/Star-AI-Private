"""A small LongMemEval-shaped memory test of our own (Wu et al., ICLR 2025, arXiv 2410.10813: information extraction,
multi-session reasoning, knowledge update, temporal reasoning, abstention), over a synthetic 6-day history.

The history goes through the real write path: inbox lines (as the social chat and star-home write them) -> ingest
-> the night's consolidation (facts with valid_from / invalid_at, lessons) -> retrieval. Answers are judged by plain
string match on the top-3 retrieved records (no model, no judge), abstention by "nothing above the relevance floor".
Deterministic: hash embedder, fixed clock.

    python -m star.inner.memeval        # prints the score per ability and every miss
"""
from __future__ import annotations

import json
import sys
import tempfile
import time

from . import consolidate
from .embed import HashEmbedder
from .stream import MemoryStream

DAY = 86400.0
START = time.mktime((2026, 10, 1, 9, 0, 0, 0, 0, -1))
MIA, SAM, ALEX = ("1.100", "Mia"), ("2.200", "Sam"), ("3.300", "Alex")

# (day, hour, who or None for her own life, text, extra fields)
HISTORY = [
    (0, 10, MIA, "Mia said: my favourite game is Doors", {}),
    (0, 11, SAM, "Sam said: I work at a bakery downtown", {}),
    (0, 15, None, "drawing: drew a fox sprite for the gallery (checked)", {"source": "activity", "place": "drawing"}),
    (0, 16, None, "tried roblox obby: did not work", {"kind": "procedural", "skill": "roblox_obby", "outcome": 0}),
    (1, 10, MIA, "Mia said: my dog's name is Biscuit", {}),
    (1, 14, None, "music: made a 30 second lofi loop (checked)", {"source": "activity", "place": "music"}),
    (1, 18, ALEX, "Alex said: I am learning Spanish for a trip", {}),
    (2, 12, SAM, "Sam said: my favourite food is ramen", {}),
    (2, 15, None, "tried roblox obby: worked", {"kind": "procedural", "skill": "roblox_obby", "outcome": 1}),
    (2, 20, None, "watched a video about volcano eruptions and took notes (checked)",
     {"source": "activity", "place": "watch_videos"}),
    (3, 10, MIA, "Mia said: my favourite game is Minecraft now", {}),
    (3, 11, SAM, "Sam said: I work at a library now", {}),
    (4, 13, None, "game_making: built a one-screen coin game with a win condition (checked)",
     {"source": "activity", "place": "game_making"}),
    (4, 19, ALEX, "Alex said: my favourite band is Daft Punk", {}),
    (5, 10, MIA, "Mia said: my favourite game is Terraria", {}),
]

# (ability, question, answer substring or None for abstain, as_of day or None, kinds)
QUESTIONS = [
    ("extraction", "what is Mia's dog called", "Biscuit", None, None),
    ("extraction", "what is Sam's favourite food", "ramen", None, None),
    ("extraction", "what is Alex learning", "Spanish", None, None),
    ("extraction", "Alex favourite band", "Daft Punk", None, None),
    ("extraction", "what did I draw for the gallery", "fox", None, None),
    ("multi_session", "did I get the roblox obby to work after failing", "Figured out", None, ("semantic",)),
    ("multi_session", "what music loop did I make", "lofi", None, None),
    ("update", "Mia favourite game", "Terraria", None, ("semantic",)),
    ("update", "where does Sam work", "library", None, ("semantic",)),
    ("temporal", "Mia favourite game", "Doors", 1, ("semantic",)),
    ("temporal", "Mia favourite game", "Minecraft", 4, ("semantic",)),
    ("temporal", "where does Sam work", "bakery", 2, ("semantic",)),
    ("temporal", "what video did I watch about volcanoes", "volcano", 3, None),
    ("abstention", "what is Mia's sister's name", None, None, None),
    ("abstention", "which city does Sam live in", None, None, None),
    ("abstention", "what car does Alex drive", None, None, None),
]
ABSTAIN_FLOOR = 0.3


def build(directory) -> tuple[MemoryStream, list]:
    clock = [START]
    stream = MemoryStream(directory, embedder=HashEmbedder(), clock=lambda: clock[0])
    by_day: dict[int, list] = {}
    for day, hour, who, text, extra in HISTORY:
        by_day.setdefault(day, []).append((hour, who, text, extra))
    nights = []
    for day in sorted(by_day):
        for hour, who, text, extra in by_day[day]:
            ts = START + day * DAY + (hour - 9) * 3600
            record = {"text": text, "ts": ts, "kind": "episodic", "source": "conversation" if who else "activity",
                      "importance": 0.5, **extra}
            if who:
                record.update(people=[who[0]], names=[who[1]], platform="discord")
            stream.observe(**record)
        night = START + day * DAY + 17 * 3600            # 02:00 the next morning
        clock[0] = night
        nights.append(consolidate.run(stream, night, night=f"d{day}", since=START + day * DAY - 3600))
    clock[0] = START + 6 * DAY
    return stream, nights


def ask(stream: MemoryStream, question: str, as_of_day, kinds) -> list:
    as_of = None if as_of_day is None else START + as_of_day * DAY + 12 * 3600
    return stream.retrieve(question, k=3, kinds=kinds, as_of=as_of, touch=False)


def run() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        stream, _ = build(tmp)
        by: dict[str, list[int]] = {}
        misses = []
        for ability, question, answer, as_of_day, kinds in QUESTIONS:
            hits = ask(stream, question, as_of_day, kinds)
            if answer is None:
                model, vecs = stream.embedder.embed([question])
                ok = all(stream.relevance(h, question, (model, vecs[0])) < ABSTAIN_FLOOR for h in hits)
            else:
                ok = any(answer.lower() in h.text.lower() for h in hits)
            by.setdefault(ability, []).append(int(ok))
            if not ok:
                misses.append({"ability": ability, "question": question, "expected": answer,
                               "got": [h.text for h in hits]})
        stream.close()
    total = sum(sum(v) for v in by.values())
    count = sum(len(v) for v in by.values())
    return {"score": round(total / count, 3), "correct": total, "questions": count,
            "by_ability": {k: f"{sum(v)}/{len(v)}" for k, v in by.items()}, "misses": misses}


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))
    sys.exit(0)
