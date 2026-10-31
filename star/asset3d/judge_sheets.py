"""Blind judging sheets: per brief one image with the conditions in a random order labelled A/B/C.

    python -m star.asset3d.judge_sheets --run <eval dir> --out <dir>

Writes <out>/<id>.jpg, <out>/briefs.json (what judges see) and <out>/key.json (label -> condition; judges never see it).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

CONDITIONS = {"baseline": ("baseline", "sheet"), "round0": ("pipeline", "round0"), "final": ("pipeline", "final")}


def sheet_for(result: dict, cond: str) -> str | None:
    rr = result.get("_rr")
    if rr is not None:
        return (rr.get(cond) or {}).get("sheet")
    if cond == "baseline":
        return (result.get("baseline") or {}).get("sheet")
    p = result.get("pipeline") or {}
    return (p.get(cond) or {}).get("sheet")


def main(argv=None):
    from PIL import Image, ImageDraw, ImageFont
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=20261029)
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    key, briefs = {}, {}
    for rp in sorted(Path(a.run).glob("*/result.json")):
        res = json.loads(rp.read_text(encoding="utf-8"))
        if (rp.parent / "rr.json").exists():
            res["_rr"] = json.loads((rp.parent / "rr.json").read_text(encoding="utf-8"))
        if res.get("pipeline", {}).get("best_round") == 0:
            res.setdefault("pipeline", {}).setdefault("round0", {})["same_as"] = "final"
        b = res["brief"]
        conds = [c for c in CONDITIONS if sheet_for(res, c)]
        if res.get("pipeline", {}).get("round0", {}).get("same_as") == "final":
            conds = [c for c in conds if c != "round0"] + []  # identical image: judge it once, copy the score
        rng.shuffle(conds)
        labels = "ABC"[:len(conds)]
        tile = 640
        img = Image.new("RGB", (tile * len(conds), tile + 48), (24, 24, 26))
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 34)
        except OSError:
            font = ImageFont.load_default()
        for i, (lab, c) in enumerate(zip(labels, conds)):
            im = Image.open(sheet_for(res, c)).convert("RGB").resize((tile, tile))
            img.paste(im, (i * tile, 48))
            d.text((i * tile + 12, 6), lab, fill=(240, 240, 240), font=font)
        img.save(out / f"{b['id']}.jpg", quality=90)
        key[b["id"]] = dict(zip(labels, conds))
        if res.get("pipeline", {}).get("round0", {}).get("same_as") == "final":
            key[b["id"]]["round0_same_as_final"] = True
        briefs[b["id"]] = {"brief": b["brief"], "style": b["style"], "category": b["category"],
                           "image": str((out / f"{b['id']}.jpg").resolve()), "labels": list(labels)}
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    (out / "briefs.json").write_text(json.dumps(briefs, indent=1), encoding="utf-8")
    print(f"{len(briefs)} sheets in {out}")


if __name__ == "__main__":
    main()
