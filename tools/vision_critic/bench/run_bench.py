"""Run critic variants on the benchmark; one cached call per (model, variant, pair, order).

usage: run_bench.py --url http://127.0.0.1:8093 --model qwen3vl-4b --split dev --variants sep_chk,sep_chk_facts,...
Results append to results/calls.jsonl; score.py turns them into the agreement tables.
"""
import argparse, json, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root
from star import vision_critic as vc  # noqa: E402

import os
HERE = Path(os.environ.get("VC_WORK", Path(__file__).parent)); B = HERE / "bench"; R = HERE / "results"; R.mkdir(exist_ok=True)
CALLS = R / "calls.jsonl"; lock = threading.Lock()

VARIANTS = {  # layout, checklist, facts
    "sep_chk": ("separate", True, False),
    "sep_chk_facts": ("separate", True, True),
    "sep_plain": ("separate", False, False),
    "side_chk_facts": ("side", True, True),
}


def done_keys():
    out = {}
    if CALLS.exists():
        for line in CALLS.read_text(encoding="utf-8").splitlines():
            d = json.loads(line); out[(d["model"], d["variant"], d["pair"], d["order"])] = d
    return out


def plain_prompt(brief, domain, facts, layout):
    where = ("The image shows candidate A on the left and candidate B on the right." if layout == "side"
             else "The first image is candidate A, the second image is candidate B.")
    return f"Brief: {brief}\n\n{where}\nWhich candidate is better for the brief? Answer with one letter: A or B."


def pair_call(send, model, p, variant, flip, max_side):
    layout, chk, facts = VARIANTS[variant]
    a = vc.tile([B / x for x in p["A"]], max_side); b = vc.tile([B / x for x in p["B"]], max_side)
    fa = vc.pixel_facts([B / x for x in p["A"]]) if facts else ""; fb = vc.pixel_facts([B / x for x in p["B"]]) if facts else ""
    x, y = (b, a) if flip else (a, b); fx = (fb, fa) if flip else (fa, fb)
    msgs = vc._pair_messages(x, y, p["brief"], p["domain"], fx if facts else None, layout)
    if not chk:
        msgs[-1]["content"][-1]["text"] = plain_prompt(p["brief"], p["domain"], None, layout)
    body = {"model": model, "messages": msgs, "max_tokens": 1, "temperature": 0, "logprobs": True, "top_logprobs": 20}
    t0 = time.monotonic(); resp = send(body); dt = time.monotonic() - t0
    pr = vc._letter_probs(resp, "AB"); tot = pr["A"] + pr["B"]
    p_first = pr["A"] / tot if tot else 0.5
    return {"p_a": (1 - p_first) if flip else p_first, "mass": round(tot, 3), "sec": round(dt, 2),
            "ptok": resp.get("usage", {}).get("prompt_tokens")}


def abs_call(send, model, p, arm, max_side):
    """Absolute 1-10 score of one arm (what the visual lanes did), expected value over digit logprobs."""
    im = vc.tile([B / x for x in p[arm]], max_side)
    cl = "\n".join(f"- {c}" for c in vc.checklist(p["domain"]))
    text = (f"Brief: {p['brief']}\n\nRate this render against the checklist:\n{cl}\n\n"
            "Score from 1 (unusable) to 9 (marketplace quality). Answer with one digit.")
    body = {"model": model, "temperature": 0, "max_tokens": 1, "logprobs": True, "top_logprobs": 20,
            "messages": [{"role": "system", "content": vc.SYSTEM},
                         {"role": "user", "content": [{"type": "image_url", "image_url": {"url": vc.data_url(im)}},
                                                      {"type": "text", "text": text}]}]}
    t0 = time.monotonic(); resp = send(body); dt = time.monotonic() - t0
    pr = vc._letter_probs(resp, "123456789"); tot = sum(pr.values())
    ev = sum(int(k) * v for k, v in pr.items()) / tot if tot else 5.0
    return {"score": ev, "mass": round(tot, 3), "sec": round(dt, 2), "ptok": resp.get("usage", {}).get("prompt_tokens")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True); ap.add_argument("--model", required=True)
    ap.add_argument("--split", default="dev"); ap.add_argument("--variants", default="sep_chk")
    ap.add_argument("--all-pairs", action="store_true", help="also non-clear pairs")
    ap.add_argument("--workers", type=int, default=1); ap.add_argument("--max-side", type=int, default=768)
    ap.add_argument("--domains", default="")
    a = ap.parse_args()
    send = vc.http_transport(a.url, "", timeout=900)
    pairs = [p for p in json.loads((B / "pairs.json").read_text(encoding="utf-8"))
             if (a.split == "all" or p["split"] == a.split) and (p["clear"] or a.all_pairs)
             and (not a.domains or any(p["domain"].startswith(d) for d in a.domains.split(",")))]
    have = done_keys(); jobs = []
    for v in a.variants.split(","):
        for p in pairs:
            orders = ("A", "B") if v == "abs" else (0, 1)
            for o in orders:
                if (a.model, v, p["id"], o) not in have:
                    jobs.append((v, p, o))
    jobs.sort(key=lambda j: (j[1]["id"], str(j[2]), j[0]))   # same pair+order back to back: image prefix cache hits
    print(f"{len(pairs)} pairs, {len(jobs)} calls to do", flush=True)
    n = [0]; t_start = time.monotonic()

    def run(job):
        v, p, o = job
        for attempt in range(3):
            try:
                r = abs_call(send, a.model, p, o, a.max_side) if v == "abs" else pair_call(send, a.model, p, v, bool(o), a.max_side)
                break
            except Exception as e:  # noqa: BLE001
                print("ERR", p["id"], v, o, e, flush=True); time.sleep(5)
        else:
            return
        rec = {"model": a.model, "variant": v, "pair": p["id"], "order": o, "max_side": a.max_side, **r}
        with lock:
            with CALLS.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            n[0] += 1
            if n[0] % 10 == 0:
                el = time.monotonic() - t_start
                print(f"{n[0]}/{len(jobs)} {el:.0f}s ({el / n[0]:.1f}s/call)", flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(run, jobs))
    print("done", n[0], flush=True)


if __name__ == "__main__":
    main()
