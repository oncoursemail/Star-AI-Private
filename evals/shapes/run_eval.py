"""shapes-templates eval: template pipeline vs the saved single-shot baseline (and the old pipeline) on the SAME
held-out briefs as the blockbench and 3d-assets lanes, judged blind.

  python evals/shapes/run_eval.py bb  --out DIR [--workers 2]            # 24 Blockbench briefs (router litha)
  python evals/shapes/run_eval.py 3d  --out DIR [--workers 2]            # 16 3D briefs (litha + Blender on STAR's PC)
  python evals/shapes/run_eval.py bb-packet --out DIR --old BB_EVAL1     # blind A/B/C images + key.json
  python evals/shapes/run_eval.py 3d-packet --out DIR --old A3D_EVAL1
  python evals/shapes/run_eval.py score --out DIR --judges j1.json j2.json j3.json

Baselines are NOT regenerated: the blockbench lane's round0 (single shot) / kept round and the 3d lane's rerendered
baseline / final sheets are reused, so only the template condition costs GPU. Judges see only the packet folder.
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from star.blockbench import pipeline as BP  # noqa: E402
from star.shapes import pipeline as SP  # noqa: E402

BB_BRIEFS = ROOT / "evals" / "blockbench" / "briefs.json"
A3D_BRIEFS = ROOT / "evals" / "asset3d" / "briefs.json"
SEED = 20261029


def _llm(a):
    return BP.default_llm("litha", a.base_url, a.key_file, timeout=300, retries=4)


def run_bb(a):
    briefs = json.loads(BB_BRIEFS.read_text(encoding="utf-8"))["briefs"]
    llm = _llm(a)

    def one(b):
        d = Path(a.out) / b["id"]
        if (d / "report.json").exists():
            return
        t = time.time()
        try:
            pl = SP.make_bb(llm, b["brief"], b["category"], d)
            print(f"{b['id']} {pl['template']} {time.time() - t:.0f}s checks={pl['record']['checks']['score']}", flush=True)
        except Exception as exc:  # noqa: BLE001 - one failed brief must not stop the eval
            d.mkdir(parents=True, exist_ok=True)
            (d / "error.json").write_text(json.dumps({"error": repr(exc), "trace": traceback.format_exc()[-1500:]}),
                                          encoding="utf-8")
            print(f"{b['id']} FAILED {exc!r}", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, briefs))


def run_3d(a):
    briefs = json.loads(A3D_BRIEFS.read_text(encoding="utf-8"))["heldout"]
    llm = _llm(a)

    def one(b):
        d = Path(a.out) / b["id"]
        if (d / "report.json").exists() and json.loads((d / "report.json").read_text(encoding="utf-8")).get("sheet"):
            return
        t = time.time()
        try:
            pl = SP.make_3d(llm, b["brief"], b["category"], b["style"], d, where=a.where)
            print(f"{b['id']} {pl['template']} {time.time() - t:.0f}s sheet={bool(pl['report'].get('sheet'))}", flush=True)
        except Exception as exc:  # noqa: BLE001
            d.mkdir(parents=True, exist_ok=True)
            (d / "error.json").write_text(json.dumps({"error": repr(exc), "trace": traceback.format_exc()[-1500:]}),
                                          encoding="utf-8")
            print(f"{b['id']} FAILED {exc!r}", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, briefs))


def _bbmodel(d: Path):
    files = sorted(d.glob("*.bbmodel"))
    return json.loads(files[0].read_text(encoding="utf-8")) if files else None


def bb_packet(a):
    """Same views/size as the blockbench lane's packet; one image per condition, labels shuffled per brief."""
    from star.blockbench import render as R
    out, old = Path(a.out), Path(a.old)
    pk = out / "packet"
    pk.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    key, shown = {}, {}
    for b in json.loads(BB_BRIEFS.read_text(encoding="utf-8"))["briefs"]:
        bid = b["id"]
        rep = json.loads((old / bid / "report.json").read_text(encoding="utf-8"))
        conds = {"template": _bbmodel(out / bid), "baseline": _bbmodel(old / bid / "round0")}
        same = rep.get("best_round", 0) == 0
        if not same:
            conds["old_pipeline"] = _bbmodel(old / bid / f"round{rep['best_round']}")
        conds = {k: v for k, v in conds.items() if v is not None}
        names = list(conds)
        rng.shuffle(names)
        labels = "ABC"[:len(names)]
        key[bid] = dict(zip(labels, names))
        if same:
            key[bid]["old_pipeline_same_as_baseline"] = True
        for lab, c in zip(labels, names):
            views = R.previews(conds[c], ("front_left", "front_right", "back_right", "side"), size=320)
            R.sheet(list(views.values()), list(views)).save(pk / f"{bid}_{lab}.png")
        shown[bid] = {"brief": b["brief"], "category": b["category"], "labels": list(labels)}
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    (pk / "briefs.json").write_text(json.dumps(shown, indent=1), encoding="utf-8")
    print(f"bb packet: {len(key)} briefs in {pk}")


def a3d_packet(a):
    """Same layout as star.asset3d.judge_sheets (conditions side by side, labelled A/B/C, 640 px tiles)."""
    from PIL import Image, ImageDraw, ImageFont
    out, old = Path(a.out), Path(a.old)
    pk = out / "packet"
    pk.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    key, shown = {}, {}
    try:
        font = ImageFont.truetype("arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    for b in json.loads(A3D_BRIEFS.read_text(encoding="utf-8"))["heldout"]:
        bid = b["id"]
        sheets = {"template": out / bid / "sheet.jpg", "baseline": old / bid / "rr" / "baseline" / "sheet.jpg",
                  "old_pipeline": old / bid / "rr" / "final" / "sheet.jpg"}
        sheets = {k: v for k, v in sheets.items() if v.exists()}
        names = list(sheets)
        rng.shuffle(names)
        labels = "ABC"[:len(names)]
        tile = 640
        img = Image.new("RGB", (tile * len(names), tile + 48), (24, 24, 26))
        d = ImageDraw.Draw(img)
        for i, (lab, c) in enumerate(zip(labels, names)):
            img.paste(Image.open(sheets[c]).convert("RGB").resize((tile, tile)), (i * tile, 48))
            d.text((i * tile + 12, 6), lab, fill=(240, 240, 240), font=font)
        img.save(pk / f"{bid}.jpg", quality=90)
        key[bid] = dict(zip(labels, names))
        shown[bid] = {"brief": b["brief"], "style": b["style"], "category": b["category"], "labels": list(labels)}
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    (pk / "briefs.json").write_text(json.dumps(shown, indent=1), encoding="utf-8")
    print(f"3d packet: {len(key)} briefs in {pk}")


def sign_p(w: int, l: int) -> float:
    n = w + l
    if not n:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(w, l) + 1)) / 2 ** n)


def score(a):
    out = Path(a.out)
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    judges = [json.loads(Path(j).read_text(encoding="utf-8"))["scores"] for j in a.judges]
    conds = ("template", "baseline", "old_pipeline")
    per: dict = {}
    for bid, lab in key.items():
        m = {}
        for c in conds:
            ls = [x for x, cc in lab.items() if cc == c]
            if not ls and c == "old_pipeline" and lab.get("old_pipeline_same_as_baseline"):
                ls = [x for x, cc in lab.items() if cc == "baseline"]
            if not ls:
                continue
            vals = []
            for j in judges:
                s = (j.get(bid) or {}).get(ls[0])
                if s is None:
                    continue
                vals.append(float(s["overall"]) if isinstance(s, dict) else float(s))
            if vals:
                m[c] = sum(vals) / len(vals)
        per[bid] = m
    res = {"n": len(per), "mean": {c: round(sum(m[c] for m in per.values() if c in m) /
                                            max(1, sum(1 for m in per.values() if c in m)), 2) for c in conds}}
    for other in ("baseline", "old_pipeline"):
        w = sum(1 for m in per.values() if other in m and m["template"] > m[other])
        lo = sum(1 for m in per.values() if other in m and m["template"] < m[other])
        t = sum(1 for m in per.values() if other in m and m["template"] == m[other])
        res[f"template_vs_{other}"] = {"wins": w, "losses": lo, "ties": t, "sign_p": round(sign_p(w, lo), 5)}
    agree = []
    for j in judges:  # how often each judge alone prefers the template over the baseline
        n = sum(1 for bid, lab in key.items()
                if all(x in (j.get(bid) or {}) for x in lab if x in "ABC"))
        pref = 0
        for bid, lab in key.items():
            sj = j.get(bid) or {}
            lt = [x for x, cc in lab.items() if cc == "template"]
            lb = [x for x, cc in lab.items() if cc == "baseline"]
            if lt and lb and lt[0] in sj and lb[0] in sj:
                ov = (lambda s: float(s["overall"]) if isinstance(s, dict) else float(s))
                pref += ov(sj[lt[0]]) > ov(sj[lb[0]])
        agree.append({"briefs": n, "template_better_than_baseline": pref})
    res["per_judge"] = agree
    res["per_brief"] = {b: {k: round(v, 2) for k, v in m.items()} for b, m in sorted(per.items())}
    (out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "per_brief"}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("bb", "3d", "bb-packet", "3d-packet", "score"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--old", help="the original lane's eval folder (baseline outputs)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--where", default="remote", choices=("remote", "local"))
    ap.add_argument("--base-url")
    ap.add_argument("--key-file")
    ap.add_argument("--judges", nargs="*", default=[])
    a = ap.parse_args()
    {"bb": run_bb, "3d": run_3d, "bb-packet": bb_packet, "3d-packet": a3d_packet, "score": score}[a.mode](a)


if __name__ == "__main__":
    main()
