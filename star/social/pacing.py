"""How fast she types: about 0.3 s per character (36 WPM) + 0.03 s per character of what they just wrote + a 0.5-2.5 s
"thinking" pause, capped at 10 s a line and 20 s a burst, never the same delay twice in a row (W9). A short reaction-like
line comes in 1-4 s. A burst is up to 3 lines of one thought with a 1-3 s gap between them.

`schedule()` gives the delays for a list of lines (pure, seeded rng in tests); the adapters sleep or queue by them. The
on-screen apps type for real (activity.HumanPace types at the same speed), so they use `think()` and `gap()` only.
"""
from __future__ import annotations

import random

SECONDS_PER_CHAR = 0.3
READ_SECONDS_PER_CHAR = 0.03
THINK = (0.5, 2.5)
GAP = (1.0, 3.0)
FAST = (1.0, 4.0)
LINE_CAP_S = 10.0
BURST_CAP_S = 20.0
SHORT_LINE = 12


class Jitter:
    """Remembers the last delays so two in a row never match (W9: constant latency is a bot tell)."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self.last: list[float] = []

    def apply(self, delay: float) -> float:
        while self.last and abs(delay - self.last[-1]) < 0.25:
            delay += self._rng.uniform(0.3, 1.2)
        self.last = (self.last + [delay])[-5:]
        return delay


def think(incoming: str, rng: random.Random | None = None) -> float:
    """Reading and thinking before she starts typing."""
    rng = rng or random.Random()
    return min(6.0, READ_SECONDS_PER_CHAR * len(incoming) + rng.uniform(*THINK))


def gap(rng: random.Random | None = None) -> float:
    """The pause between two lines of one burst."""
    return (rng or random.Random()).uniform(*GAP)


def typing_time(text: str) -> float:
    return min(LINE_CAP_S, SECONDS_PER_CHAR * len(text))


def line_delay(text: str, incoming: str = "", *, rng: random.Random | None = None, first: bool = True) -> float:
    """Seconds from "their message arrived" (first line) or from the previous line (later lines) to sending this line."""
    rng = rng or random.Random()
    if first and len(text) <= SHORT_LINE:
        return rng.uniform(*FAST)                                   # a quick "lol" or "same" is quick
    if first:
        return min(LINE_CAP_S, typing_time(text) + think(incoming, rng))
    return min(LINE_CAP_S, rng.uniform(*GAP) + 0.15 * len(text))


def schedule(lines: list[str], incoming: str = "", *, rng: random.Random | None = None, jitter: Jitter | None = None) -> list[float]:
    """Delay before each line (the first counts from the incoming message, the others from the line before). A burst
    never takes longer than 20 s in total: the later gaps shrink, the first line keeps its think time."""
    rng = rng or random.Random()
    jitter = jitter or Jitter(rng)
    delays = [jitter.apply(line_delay(line, incoming, rng=rng, first=i == 0)) for i, line in enumerate(lines)]
    total = sum(delays)
    if total > BURST_CAP_S and len(delays) > 1:
        scale = max(0.2, (BURST_CAP_S - delays[0]) / max(0.1, sum(delays[1:])))
        delays = [delays[0]] + [max(0.8, d * scale) for d in delays[1:]]
    return [round(d, 2) for d in delays]
