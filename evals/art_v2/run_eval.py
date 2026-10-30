"""art-v2 eval: the art-v2 template library + renderer vs the frozen shapes-templates code on NEW held-out briefs.

  python evals/art_v2/run_eval.py 3d --code ROOT --out DIR [--set heldout] [--workers 2]
  python evals/art_v2/run_eval.py bb --code ROOT --out DIR [--set briefs]
  python evals/art_v2/run_eval.py 3d-packet --a BASE_DIR --b NEW_DIR --out DIR
  python evals/art_v2/run_eval.py bb-packet --a BASE_DIR --b NEW_DIR --out DIR
  python evals/art_v2/run_eval.py score --out DIR --judges j1.json j2.json j3.json

--code is the repo root whose star/ package builds the condition (the frozen baseline is a detached worktree at
the shapes-templates commit). Set STAR_ASSET3D_BUILDER to a distinct name per condition so remote builders do not
overwrite each other. The baseline code has no 'highpoly' style: it builds those briefs as pbr.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRIEFS_3D = HERE / "briefs.json"
BRIEFS_BB = HERE / "bb_briefs.json"
SEED = 20261030


def _import(code: str):
    sys.path.insert(0, str(Path(code).resolve()))
    from star.blockbench import pipeline as BP
    from star.shapes import pipeline as SP
    return BP, SP


def _fail(d: Path, bid: str, exc: Exception):
    d.mkdir(parents=True, exist_ok=True)
    (d / "error.json").write_text(json.dumps({"error": repr(exc), "trace": traceback.format_exc()[-1500:]}),
                                  encoding="utf-8")
    print(f"{bid} FAILED {exc!r}", flush=True)


def run_3d(a):
    BP, SP = _import(a.code)
    from star.asset3d import spec as S
    briefs = json.loads(BRIEFS_3D.read_text(encoding="utf-8"))[a.set]
    llm = BP.default_llm("litha", None, None, timeout=300, retries=4)

    def one(b):
        d = Path(a.out) / b["id"]
        if (d / "report.json").exists() and json.loads((d / "report.json").read_text(encoding="utf-8")).get("sheet"):
            return
        style = b["style"] if b["style"] in S.STYLES else "pbr"
        t = time.time()
        try:
            pl = SP.make_3d(llm, b["brief"], b["category"], style, d, where=a.where)
            print(f"{b['id']} {pl['template']} {time.time() - t:.0f}s sheet={bool(pl['report'].get('sheet'))}",
                  flush=True)
        except Exception as exc:  # noqa: BLE001 - one failed brief must not stop the eval
            _fail(d, b["id"], exc)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, briefs))


def run_bb(a):
    BP, SP = _import(a.code)
    briefs = json.loads(BRIEFS_BB.read_text(encoding="utf-8"))[a.set]
    llm = BP.default_llm("litha", None, None, timeout=300, retries=4)

    def one(b):
        d = Path(a.out) / b["id"]
        if (d / "report.json").exists():
            return
        t = time.time()
        try:
            pl = SP.make_bb(llm, b["brief"], b["category"], d)
            print(f"{b['id']} {pl['template']} {time.time() - t:.0f}s", flush=True)
        except Exception as exc:  # noqa: BLE001
            _fail(d, b["id"], exc)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, briefs))


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _pair(images: dict, path: Path, rng: random.Random, tile: int = 640) -> dict:
    """Conditions side by side, labelled A/B in a shuffled order. Returns {label: condition}."""
    from PIL import Image, ImageDraw
    names = list(images)
    rng.shuffle(names)
    img = Image.new("RGB", (tile * len(names), tile + 48), (24, 24, 26))
    d = ImageDraw.Draw(img)
    for i, c in enumerate(names):
        img.paste(images[c].convert("RGB").resize((tile, tile)), (i * tile, 48))
        d.text((i * tile + 12, 6), "AB"[i], fill=(240, 240, 240), font=_font(34))
    img.save(path, quality=90)
    return dict(zip("AB", names))


def a3d_packet(a):
    from PIL import Image
    out = Path(a.out)
    pk = out / "packet"
    pk.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    key, shown = {}, {}
    for b in json.loads(BRIEFS_3D.read_text(encoding="utf-8"))["heldout"]:
        bid = b["id"]
        ims = {}
        for cond, root in (("baseline", a.a), ("v2", a.b)):
            p = Path(root) / bid / "sheet.jpg"
            ims[cond] = Image.open(p) if p.exists() else Image.new("RGB", (512, 512), (40, 40, 40))
        key[bid] = _pair(ims, pk / f"{bid}.jpg", rng)
        shown[bid] = {"brief": b["brief"], "style": b["style"], "category": b["category"], "labels": ["A", "B"]}
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    (pk / "briefs.json").write_text(json.dumps(shown, indent=1), encoding="utf-8")
    print(f"3d packet: {len(key)} briefs in {pk}")


def bb_packet(a):
    _, _ = _import(a.code)
    from PIL import Image
    from star.blockbench import render as R
    out = Path(a.out)
    pk = out / "packet"
    pk.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    key, shown = {}, {}
    for b in json.loads(BRIEFS_BB.read_text(encoding="utf-8"))["briefs"]:
        bid = b["id"]
        ims = {}
        for cond, root in (("baseline", a.a), ("v2", a.b)):
            files = sorted((Path(root) / bid).glob("*.bbmodel"))
            if not files:
                ims[cond] = Image.new("RGB", (640, 640), (40, 40, 40))
                continue
            model = json.loads(files[0].read_text(encoding="utf-8"))
            views = R.previews(model, ("front_left", "front_right", "back_right", "side"), size=320)
            ims[cond] = R.sheet(list(views.values()), list(views))
        key[bid] = _pair(ims, pk / f"{bid}.jpg", rng)
        shown[bid] = {"brief": b["brief"], "category": b["category"], "labels": ["A", "B"]}
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    (pk / "briefs.json").write_text(json.dumps(shown, indent=1), encoding="utf-8")
    print(f"bb packet: {len(key)} briefs in {pk}")


def sign_p(w: int, lo: int) -> float:
    n = w + lo
    if not n:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(w, lo) + 1)) / 2 ** n)


def _ov(s):
    return float(s["overall"]) if isinstance(s, dict) else float(s)


def score(a):
    out = Path(a.out)
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    meta = {}
    for f in (BRIEFS_3D, BRIEFS_BB):
        d = json.loads(f.read_text(encoding="utf-8"))
        for b in d.get("heldout", []) + d.get("briefs", []):
            meta[b["id"]] = b.get("style", b.get("category"))
    judges = [json.loads(Path(j).read_text(encoding="utf-8"))["scores"] for j in a.judges]
    per = {}
    for bid, lab in key.items():
        m = {}
        for lbl, cond in lab.items():
            vals = [_ov(j[bid][lbl]) for j in judges if lbl in (j.get(bid) or {})]
            if vals:
                m[cond] = sum(vals) / len(vals)
        per[bid] = m

    def summary(ids):
        ids = [i for i in ids if "v2" in per[i] and "baseline" in per[i]]
        w = sum(per[i]["v2"] > per[i]["baseline"] for i in ids)
        lo = sum(per[i]["v2"] < per[i]["baseline"] for i in ids)
        return {"n": len(ids), "v2": round(sum(per[i]["v2"] for i in ids) / max(1, len(ids)), 2),
                "baseline": round(sum(per[i]["baseline"] for i in ids) / max(1, len(ids)), 2),
                "wins": w, "losses": lo, "ties": len(ids) - w - lo, "sign_p": round(sign_p(w, lo), 5)}
    res = {"all": summary(list(per))}
    for grp in sorted({meta.get(i, "?") for i in per}):
        res[grp] = summary([i for i in per if meta.get(i) == grp])
    res["per_judge_v2_better"] = []
    for j in judges:
        n = 0
        for bid, lab in key.items():
            inv = {c: lbl for lbl, c in lab.items()}
            sj = j.get(bid) or {}
            if inv["v2"] in sj and inv["baseline"] in sj:
                n += _ov(sj[inv["v2"]]) > _ov(sj[inv["baseline"]])
        res["per_judge_v2_better"].append(n)
    res["per_brief"] = {b: {k: round(v, 2) for k, v in m.items()} for b, m in sorted(per.items())}
    (out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "per_brief"}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("3d", "bb", "3d-packet", "bb-packet", "score"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--code", default=str(HERE.parents[1]))
    ap.add_argument("--set", default=None)
    ap.add_argument("--a", help="baseline output folder")
    ap.add_argument("--b", help="art-v2 output folder")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--where", default="remote", choices=("remote", "local"))
    ap.add_argument("--judges", nargs="*", default=[])
    a = ap.parse_args()
    if a.set is None:
        a.set = "heldout" if a.mode == "3d" else "briefs"
    {"3d": run_3d, "bb": run_bb, "3d-packet": a3d_packet, "bb-packet": bb_packet, "score": score}[a.mode](a)


if __name__ == "__main__":
    main()
