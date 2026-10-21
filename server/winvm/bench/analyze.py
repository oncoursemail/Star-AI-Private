#!/usr/bin/env python3
"""Paired comparison of chatbench.py runs: each condition vs the no-VM runs of the same lock hold, per prompt.

    python3 analyze.py bench-full.log

Spec decoding makes tok/s depend strongly on the prompt, so medians across prompts mislead. For each run we take
the ratio to the mean no-VM speed of the same prompt in the same hold, then the geometric mean over the prompts.
Holds are separated by lines starting with "== ".
"""
import math
import re
import sys
from collections import defaultdict

LINE = re.compile(r"^(\S+) p(\d+) gen ([\d.]+) tok/s .* other_busy (\d+)")


def main():
    holds, cur = [], []
    for line in open(sys.argv[1], encoding="utf-8"):
        if line.startswith("== "):
            if cur:
                holds.append(cur)
            cur = [line.strip()]
            continue
        m = LINE.match(line)
        if m:
            cur.append((m.group(1), int(m.group(2)), float(m.group(3)), int(m.group(4))))
    if cur:
        holds.append(cur)
    for h in holds:
        name = h[0] if isinstance(h[0], str) else "== (unnamed)"
        rows = [r for r in h if not isinstance(r, str)]
        base = defaultdict(list)
        for tag, p, gen, busy in rows:
            if tag == "novm" and busy == 0:
                base[p].append(gen)
        print(name)
        runs, last = [], None
        for tag, p, gen, busy in rows:  # split consecutive blocks of the same tag into runs
            if last != tag or (runs and p == 0):
                runs.append((tag, []))
            runs[-1][1].append((p, gen, busy))
            last = tag
        for tag, items in runs:
            ratios = [g / (sum(base[p]) / len(base[p])) for p, g, b in items if b == 0 and base.get(p)]
            gm = math.exp(sum(map(math.log, ratios)) / len(ratios)) if ratios else float("nan")
            print("  %-14s n=%d  vs no-VM %+6.1f%%  (per prompt: %s)" % (
                tag, len(ratios), (gm - 1) * 100, " ".join("%+.0f" % ((r - 1) * 100) for r in ratios)))


if __name__ == "__main__":
    main()
