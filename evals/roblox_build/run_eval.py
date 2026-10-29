"""Run both arms (pipeline, baseline) for every held-out brief; evidence under docs/agents/roblox-build/eval/.

    env -u ROBLOX_API_KEY python evals/roblox_build/run_eval.py --set heldout [--only h01-fishing] [--workers 3]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from star.roblox_build import pipeline  # noqa: E402

OUT = ROOT.parents[1] / "docs" / "agents" / "roblox-build" / "eval"


def one(item: dict, arm: str, out: Path) -> dict:
    folder = out / f"{item['id']}-{arm}"
    if (folder / "result.json").is_file():
        return json.loads((folder / "result.json").read_text(encoding="utf-8"))
    try:
        return pipeline.build(item["brief"], item["style"], folder, arm=arm,
                              log=lambda m: print(time.strftime("%H:%M:%S"), item["id"], m, flush=True))
    except Exception as error:  # record and go on
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "error.txt").write_text(repr(error), encoding="utf-8")
        print(item["id"], arm, "FAILED", repr(error), flush=True)
        return {"error": repr(error)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="heldout")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--arms", nargs="*", default=["baseline", "pipeline"])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    items = json.loads((Path(__file__).parent / "briefs.json").read_text(encoding="utf-8"))[a.set]
    if a.only:
        items = [i for i in items if i["id"] in a.only]
    out = Path(a.out)
    jobs = [(i, arm) for i in items for arm in a.arms]
    with cf.ThreadPoolExecutor(a.workers) as pool:
        futures = {pool.submit(one, i, arm, out): (i["id"], arm) for i, arm in jobs}
        for f in cf.as_completed(futures):
            iid, arm = futures[f]
            r = f.result()
            print("DONE", iid, arm, (r.get("final") or {}).get("severity"), (r.get("timings") or {}).get("total"), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
