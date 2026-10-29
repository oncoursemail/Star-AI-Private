"""Blind judge packets: per brief one image with two builds (A on top, B below, order random), a text file with the
briefs, and a hidden key. Judges never see which arm is which.

    python evals/roblox_build/make_packets.py [--seed 29]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
EVAL = ROOT.parents[1] / "docs" / "agents" / "roblox-build" / "eval"


def main() -> int:
    from PIL import Image, ImageDraw
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=29)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    items = json.loads((Path(__file__).parent / "briefs.json").read_text(encoding="utf-8"))["heldout"]
    out = EVAL / "judge"
    out.mkdir(parents=True, exist_ok=True)
    key, lines = {}, []
    for n, item in enumerate(items, 1):
        sheets = {}
        for arm in ("pipeline", "baseline"):
            res = EVAL / f"{item['id']}-{arm}" / "result.json"
            if res.is_file():
                sheets[arm] = json.loads(res.read_text(encoding="utf-8"))["final"]["sheet"]
        if len(sheets) != 2 or not all(sheets.values()):
            print("skip", item["id"], sheets)
            continue
        order = ["pipeline", "baseline"]
        rng.shuffle(order)
        key[f"P{n:02d}"] = {"id": item["id"], "A": order[0], "B": order[1]}
        ims = [Image.open(sheets[arm]).convert("RGB") for arm in order]
        w = max(im.width for im in ims)
        canvas = Image.new("RGB", (w, sum(im.height for im in ims) + 60), (12, 12, 14))
        d = ImageDraw.Draw(canvas)
        y = 0
        for label, im in zip("AB", ims):
            d.text((10, y + 8), f"BUILD {label}", fill=(255, 255, 255))
            canvas.paste(im, (0, y + 30))
            y += im.height + 30
        canvas.save(out / f"P{n:02d}.jpg", quality=86)
        lines.append(f"P{n:02d}: style={item['style']} brief={item['brief']}")
    (out / "packets.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (EVAL / "judge-key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")   # outside the judge folder
    print(len(key), "packets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
