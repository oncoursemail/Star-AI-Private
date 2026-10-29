"""Blockbench lane eval: single-shot (round 0) vs render-and-critique loop on held-out briefs.

  python evals/blockbench/run_eval.py --out DIR [--rounds 2] [--workers 3] [--only b01,m02]
  python evals/blockbench/run_eval.py --out DIR --packet      # blind A/B judge packet from a finished run

Critic calls are serialised (one star-fast slot) so STAR's live chat keeps the other slot.
The packet step writes packet/<id>_A.png, <id>_B.png and a separate key.json (arm per letter) that judges never see.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from star.blockbench import pipeline as PL  # noqa: E402
from star.blockbench import render as R  # noqa: E402

HERE = Path(__file__).resolve().parent


class Serial:
    def __init__(self, llm):
        self.llm, self.lock = llm, threading.Lock()

    def chat(self, *a, **k):
        with self.lock:
            return self.llm.chat(*a, **k)


def one(b, args, planner, critic):
    d = Path(args.out) / b["id"]
    if (d / "report.json").exists():
        return json.loads((d / "report.json").read_text(encoding="utf-8"))
    t = time.time()
    try:
        rep = PL.run(b["brief"], category=b["category"], rounds=args.rounds, planner=planner, critic=critic,
                     out_dir=d, seed=args.seed)
    except Exception as exc:  # noqa: BLE001 - one failed brief must not stop the eval
        (d).mkdir(parents=True, exist_ok=True)
        rep = {"brief": b["brief"], "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]}
        (d / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"{b['id']} done in {time.time() - t:.0f}s: "
          f"{[(r['checks'], r['critic']) for r in rep.get('rounds', [])]} best={rep.get('best_round')}", flush=True)
    return rep


def _bbmodel(d: Path):
    files = sorted(d.glob("*.bbmodel"))
    return json.loads(files[0].read_text(encoding="utf-8")) if files else None


def packet(args):
    out = Path(args.out)
    pk = out / "packet"
    pk.mkdir(exist_ok=True)
    rng = random.Random(20261029)
    key = {}
    briefs = json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))["briefs"]
    for b in briefs:
        d = out / b["id"]
        rep = json.loads((d / "report.json").read_text(encoding="utf-8")) if (d / "report.json").exists() else {}
        if "error" in rep or not rep:
            continue
        base = _bbmodel(d / "round0")
        loop = _bbmodel(d / "final")
        if base is None or loop is None:
            continue
        arms = [("baseline", base), ("loop", loop)]
        rng.shuffle(arms)
        key[b["id"]] = {"A": arms[0][0], "B": arms[1][0], "same": rep.get("best_round") == 0}
        for letter, (_, bb) in zip("AB", arms):
            views = R.previews(bb, ("front_left", "front_right", "back_right", "side"), size=320)
            R.sheet(list(views.values()), list(views)).save(pk / f"{b['id']}_{letter}.png")
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    (pk / "briefs.json").write_text(json.dumps({b["id"]: {"brief": b["brief"], "category": b["category"]}
                                                for b in briefs if b["id"] in key}, indent=1), encoding="utf-8")
    print(f"packet: {len(key)} pairs in {pk}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default="")
    ap.add_argument("--planner", default="litha")
    ap.add_argument("--critic", default="star-fast")
    ap.add_argument("--base-url")
    ap.add_argument("--key-file")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--packet", action="store_true")
    args = ap.parse_args()
    if args.packet:
        return packet(args)
    briefs = json.loads((HERE / "briefs.json").read_text(encoding="utf-8"))["briefs"]
    if args.only:
        keep = set(args.only.split(","))
        briefs = [b for b in briefs if b["id"] in keep]
    planner = PL.default_llm(args.planner, args.base_url, args.key_file, timeout=300, retries=3)
    critic = Serial(PL.default_llm(args.critic, args.base_url, args.key_file))
    t = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        reps = list(ex.map(lambda b: one(b, args, planner, critic), briefs))
    ok = [r for r in reps if "rounds" in r]
    print(json.dumps({"briefs": len(reps), "ok": len(ok), "minutes": round((time.time() - t) / 60, 1),
                      "best_round_counts": {i: sum(1 for r in ok if r["best_round"] == i) for i in range(args.rounds + 1)}}))


if __name__ == "__main__":
    main()
