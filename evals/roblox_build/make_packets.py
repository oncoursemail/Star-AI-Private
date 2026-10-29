"""Blind judge packets: per brief one image with the builds stacked (BUILD A on top, then B, C, ...; order random
per brief), a text file with the briefs, and a hidden key. Judges never see which arm is which.

    python evals/roblox_build/make_packets.py [--seed 29]                       # 10-29 eval: pipeline vs baseline
    python evals/roblox_build/make_packets.py --out DIR --arm new=EVAL_DIR:pipeline --arm old=OLD_DIR:baseline ...

`--arm name=folder:arm` takes the build of each brief from <folder>/<brief id>-<arm>/result.json.
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
    ap.add_argument("--arm", action="append", default=[], help="name=folder:arm (repeat); default: the 10-29 two arms")
    ap.add_argument("--out", default=str(EVAL), help="folder for judge/ and judge-key.json")
    a = ap.parse_args()
    arms = {}
    for spec in a.arm or [f"pipeline={EVAL}:pipeline", f"baseline={EVAL}:baseline"]:
        name, rest = spec.split("=", 1)
        folder, arm = rest.rsplit(":", 1)
        arms[name] = (Path(folder), arm)
    rng = random.Random(a.seed)
    items = json.loads((Path(__file__).parent / "briefs.json").read_text(encoding="utf-8"))["heldout"]
    out_root = Path(a.out)
    out = out_root / "judge"
    out.mkdir(parents=True, exist_ok=True)
    key, lines = {}, []
    for n, item in enumerate(items, 1):
        sheets = {}
        for name, (folder, arm) in arms.items():
            res = folder / f"{item['id']}-{arm}" / "result.json"
            if res.is_file():
                sheets[name] = json.loads(res.read_text(encoding="utf-8"))["final"]["sheet"]
        if len(sheets) != len(arms) or not all(sheets.values()):
            print("skip", item["id"], sheets)
            continue
        order = list(arms)
        rng.shuffle(order)
        labels = "ABCDEFGH"[:len(order)]
        key[f"P{n:02d}"] = {"id": item["id"], **dict(zip(labels, order))}
        ims = [Image.open(sheets[name]).convert("RGB") for name in order]
        w = max(im.width for im in ims)
        canvas = Image.new("RGB", (w, sum(im.height for im in ims) + 30 * len(ims)), (12, 12, 14))
        d = ImageDraw.Draw(canvas)
        y = 0
        for label, im in zip(labels, ims):
            d.text((10, y + 8), f"BUILD {label}", fill=(255, 255, 255))
            canvas.paste(im, (0, y + 30))
            y += im.height + 30
        canvas.save(out / f"P{n:02d}.jpg", quality=86)
        lines.append(f"P{n:02d}: style={item['style']} brief={item['brief']}")
    (out / "packets.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_root / "judge-key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")   # outside the judge folder
    print(len(key), "packets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
