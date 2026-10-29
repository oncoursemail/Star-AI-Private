"""STAR 3D asset pipeline: brief -> spec (litha) -> Blender build/bake/render -> QA + vision critique -> revise.

    python -m star.asset3d.pipeline --set dev --ids d01 --out <dir> [--conditions baseline,pipeline] [--rounds 3]

Each brief writes <out>/<id>/<condition>/... and <out>/<id>/result.json. Renders, maps and meshes stay out of git.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import time
import traceback
from pathlib import Path

from . import author, critic, runner
from .spec import STYLE, budget

HERE = Path(__file__).resolve().parent
PREVIEW = {"tex": 512, "bake_samples": 8, "render": {"size": 384, "samples": 16}, "final": False}
EVAL_RENDER = {"size": 512, "samples": 32}


def _job(mode, spec, threads, **kw):
    j = {"mode": mode, "spec": spec, "threads": threads}
    j.update(kw)
    return j


def run_baseline(brief, out: Path, where, threads, model):
    out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    spec, info = author.write_baseline(brief, model=model)
    (out / "spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    m = runner.build(_job("baseline", spec, threads, render=EVAL_RENDER), out / "build", where)
    res = {"seconds": round(time.time() - t, 1), "llm": info["calls"], "metrics": _slim(m)}
    if m.get("ok"):
        res["sheet"] = str(runner.contact_sheet(m["views"], out / "sheet.jpg", tile=512))
    return res


def _slim(m):
    return {k: m.get(k) for k in ("ok", "error", "parts_built", "part_errors", "contact", "dims", "qa", "tex",
                                  "lod_tris", "exports", "seconds")}


def run_pipeline(brief, out: Path, where, threads, model, critic_model, rounds):
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    spec, info = author.write_spec(brief, model=model)
    raw = info["raw"]
    hist, best = [], None
    for r in range(rounds + 1):
        rd = out / f"round{r}"
        rd.mkdir(exist_ok=True)
        (rd / "spec.json").write_text(json.dumps(raw, indent=1), encoding="utf-8")
        m = runner.build(_job("pipeline", spec, threads, **PREVIEW), rd / "build", where)
        entry = {"round": r, "llm": info["calls"], "build_s": m.get("seconds"), "ok": m.get("ok")}
        if not m.get("ok"):
            entry["error"] = m.get("error")
            hist.append(entry)
            break
        sheet = runner.contact_sheet(m["views"], rd / "sheet.jpg")
        notes, pen = critic.qa_notes(m, spec)
        crit, cmeta = critic.critique(str(sheet), brief, [p["id"] for p in spec["parts"]], model=critic_model)
        ov = crit.get("overall") if isinstance(crit.get("overall"), (int, float)) else None
        score = (ov if ov is not None else 5.0) - 0.5 * pen
        entry.update({"critic": crit, "critic_s": cmeta["seconds"], "qa_notes": notes, "penalty": pen,
                      "score": score, "tris": m["qa"]["tris"], "sheet": str(sheet)})
        hist.append(entry)
        if best is None or score > best["score"]:
            best = {"score": score, "spec": spec, "raw": raw, "round": r}
        if r == rounds or (ov is not None and ov >= 8.5 and pen == 0) or (ov is None and not notes):
            break
        try:
            spec, info = author.revise_spec(brief, raw, notes, crit, model=model)
            raw = info["raw"]
        except Exception as e:  # keep the best so far
            hist.append({"round": r + 1, "error": f"revise failed: {e}"})
            break
    res = {"rounds": hist, "best_round": best["round"] if best else None}
    if best is None:
        res["seconds"] = round(time.time() - t0, 1)
        return res
    style = brief["style"]
    tex = STYLE[style]["tex"]
    finals = {"final": best}
    # ablation: the first spec (no critique loop) built at the same final quality
    first = out / "round0" / "spec.json"
    if best["round"] != 0 and first.exists():
        from .spec import ground, prepare
        r0 = json.loads(first.read_text(encoding="utf-8"))
        finals["round0"] = {"spec": ground(prepare(r0)), "round": 0}
    for name, b in finals.items():
        fd = out / name
        m = runner.build(_job("pipeline", b["spec"], threads, tex=tex, bake_samples=16, render=EVAL_RENDER,
                              final=(name == "final")), fd / "build", where)
        r = {"metrics": _slim(m), "round": b["round"]}
        if m.get("ok"):
            r["sheet"] = str(runner.contact_sheet(m["views"], fd / "sheet.jpg", tile=512))
            r["checks"] = critic.deterministic_pass(m, b["spec"], tex)
        (fd / "spec.json").write_text(json.dumps(b.get("raw") or b["spec"], indent=1), encoding="utf-8")
        res[name] = r
    if "round0" not in res and "final" in res:
        res["round0"] = {"same_as": "final", **res["final"]}
    res["seconds"] = round(time.time() - t0, 1)
    return res


def run_brief(brief, outroot: Path, conditions, where, threads, model, critic_model, rounds):
    out = outroot / brief["id"]
    out.mkdir(parents=True, exist_ok=True)
    rpath = out / "result.json"
    result = json.loads(rpath.read_text(encoding="utf-8")) if rpath.exists() else {"brief": brief}
    for c in conditions:
        if c in result and not result[c].get("error"):
            continue
        try:
            if c == "baseline":
                result[c] = run_baseline(brief, out / "baseline", where, threads, model)
            else:
                result[c] = run_pipeline(brief, out / "pipeline", where, threads, model, critic_model, rounds)
        except Exception as e:
            result[c] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
        rpath.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
        print(f"[{brief['id']}] {c} done: {str(result[c].get('error') or result[c].get('seconds'))}", flush=True)
    return result


def rerender(run: Path, where: str, threads: int, workers: int = 2):
    """Rebuild every condition of a finished run from its saved specs with the current builder (same settings for
    all conditions; no model calls). Writes <id>/rr/<condition>/ and <id>/rr.json."""
    from .spec import ground, prepare, validate_baseline

    def one(rp: Path):
        res = json.loads(rp.read_text(encoding="utf-8"))
        b, d = res["brief"], rp.parent
        out = {}
        jobs = {}
        if (d / "baseline" / "spec.json").exists():
            jobs["baseline"] = _job("baseline", validate_baseline(json.loads((d / "baseline" / "spec.json").read_text(
                encoding="utf-8"))), threads, render=EVAL_RENDER)
        tex = STYLE[b["style"]]["tex"]
        for cond, src in (("round0", d / "pipeline" / "round0" / "spec.json"),
                          ("final", d / "pipeline" / "final" / "spec.json")):
            if src.exists():
                raw = json.loads(src.read_text(encoding="utf-8"))
                raw["style"], raw["category"] = b["style"], b["category"]
                jobs[cond] = _job("pipeline", ground(prepare(raw)), threads, tex=tex, bake_samples=16,
                                  render=EVAL_RENDER, final=(cond == "final"))
        for cond, job in jobs.items():
            m = runner.build(job, d / "rr" / cond, where)
            r = {"metrics": _slim(m)}
            if m.get("ok"):
                r["sheet"] = str(runner.contact_sheet(m["views"], d / "rr" / cond / "sheet.jpg", tile=512))
                if cond != "baseline":
                    r["checks"] = critic.deterministic_pass(m, job["spec"], job["tex"])
            out[cond] = r
        (d / "rr.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
        print(f"[{b['id']}] rerender: " + ", ".join(f"{k}={'ok' if v.get('sheet') else 'FAIL'}" for k, v in out.items()),
              flush=True)

    with cf.ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, sorted(Path(run).glob("*/result.json"))))


def make_asset(brief_text: str, category: str, style: str, out: str, where: str = "remote", rounds: int = 3) -> dict:
    """Entry point for STAR: one brief -> final game-ready asset folder (GLB/FBX/OBJ, maps, LODs, renders)."""
    brief = {"id": "asset", "brief": brief_text, "category": category, "style": style}
    return run_pipeline(brief, Path(out), where, 4, "litha", "star-fast", rounds)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--briefs", default=str(HERE / "eval_briefs.json"))
    ap.add_argument("--set", default="dev", choices=("dev", "heldout"))
    ap.add_argument("--ids", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--conditions", default="baseline,pipeline")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--threads", type=int, default=3)
    ap.add_argument("--where", default="remote", choices=("remote", "local"))
    ap.add_argument("--model", default="litha")
    ap.add_argument("--critic", default="star-fast")
    ap.add_argument("--rerender", action="store_true", help="rebuild all conditions of --out from saved specs")
    a = ap.parse_args(argv)
    if a.rerender:
        rerender(Path(a.out), a.where, a.threads, a.workers)
        return
    briefs = json.loads(Path(a.briefs).read_text(encoding="utf-8"))[a.set]
    if a.ids:
        want = set(a.ids.split(","))
        briefs = [b for b in briefs if b["id"] in want]
    conds = a.conditions.split(",")
    outroot = Path(a.out)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run_brief, b, outroot, conds, a.where, a.threads, a.model, a.critic, a.rounds)
                for b in briefs]
        for f in cf.as_completed(futs):
            f.result()


if __name__ == "__main__":
    main()
