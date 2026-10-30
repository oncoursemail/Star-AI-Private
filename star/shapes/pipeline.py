"""Brief -> template plan (two small router calls) -> exact geometry -> the existing Blockbench / Blender builders.

  python -m star.shapes.pipeline bb "a small orange fox" --category mob --out DIR
  python -m star.shapes.pipeline 3d "a red fire axe" --category weapon --style roblox --out DIR [--where remote]

The router is OpenAI-compatible (STAR mesh); base URL and key come from STAR_MESH_URL / STAR_API_KEY_FILE or
~/.star/mesh_url and ~/.star/server_api_key (see star.blockbench.pipeline.default_llm).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import core


def plan_bb(llm, brief: str, category: str | None = None, *, seed: int = 7, template: str | None = None) -> dict:
    from . import bb
    extra = f"Category: {category}" if category else ""
    pool = bb.TEMPLATES
    pl = core.plan(llm, brief, pool, bb.KINDS, extra=extra, seed=seed, template=template)
    t = pool[pl["template"]]
    pl["spec"] = t.build(pl["params"], pl["roles"], pl["name"])
    return pl


def make_bb(llm, brief: str, category: str | None = None, out_dir: str | Path | None = None, *, seed: int = 7,
            size: int = 384) -> dict:
    """Plan + build + checks + renders (+ files when out_dir is given). Returns the plan with the build record."""
    from star.blockbench import pipeline as BP
    t0 = time.time()
    pl = plan_bb(llm, brief, category, seed=seed)
    rec = BP.evaluate(pl["spec"], out_dir=Path(out_dir) if out_dir else None, size=size)
    pl.update({"record": rec, "seconds": round(time.time() - t0, 1)})
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        rep = {k: pl[k] for k in ("template", "name", "params", "roles", "notes", "log", "answer", "seconds")}
        rep.update({"brief": brief, "category": category, "checks": rec["checks"]["score"],
                    "findings": [f["code"] for f in rec["checks"]["findings"]], "fixes": rec["fixes"]})
        (Path(out_dir) / "report.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return pl


def plan_3d(llm, brief: str, category: str, style: str, *, seed: int = 7, template: str | None = None) -> dict:
    from . import a3d
    extra = f"Category: {category}. Style: {style}."
    pl = core.plan(llm, brief, a3d.TEMPLATES, a3d.KINDS, extra=extra, seed=seed, template=template)
    t = a3d.TEMPLATES[pl["template"]]
    raw = t.build(pl["params"], pl["roles"], style)
    raw["name"] = pl["name"]
    raw["style"] = style
    from star.asset3d.spec import CATEGORIES
    raw["category"] = category if category in CATEGORIES else t.category
    pl["spec"] = raw
    return pl


def make_3d(llm, brief: str, category: str, style: str, out_dir: str | Path, *, where: str = "remote",
            threads: int = 3, seed: int = 7, final: bool = True) -> dict:
    """Plan + Blender build (bakes, LODs, GLB/FBX/OBJ when final) + 4-view sheet under out_dir."""
    from star.asset3d import critic, pipeline as AP, runner
    from star.asset3d.spec import STYLE, ground, prepare
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    pl = plan_3d(llm, brief, category, style, seed=seed)
    (out / "spec.json").write_text(json.dumps(pl["spec"], indent=1), encoding="utf-8")
    spec = ground(prepare(pl["spec"]))
    tex = STYLE[style]["tex"]
    m = runner.build(AP._job("pipeline", spec, threads, tex=tex, bake_samples=16, render=AP.EVAL_RENDER, final=final),
                     out / "build", where)
    rep = {k: pl[k] for k in ("template", "name", "params", "roles", "notes", "log", "answer")}
    rep.update({"brief": brief, "category": category, "style": style, "metrics": AP._slim(m)})
    if m.get("ok"):
        rep["sheet"] = str(runner.contact_sheet(m["views"], out / "sheet.jpg", tile=512))
        rep["checks"] = critic.deterministic_pass(m, spec, tex)
    rep["seconds"] = round(time.time() - t0, 1)
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    pl["report"] = rep
    return pl


def main(argv=None):
    from star.blockbench.pipeline import default_llm
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=("bb", "3d"))
    ap.add_argument("brief")
    ap.add_argument("--category")
    ap.add_argument("--style", default="pbr")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="litha")
    ap.add_argument("--base-url")
    ap.add_argument("--key-file")
    ap.add_argument("--where", default="remote", choices=("remote", "local"))
    a = ap.parse_args(argv)
    llm = default_llm(a.model, a.base_url, a.key_file, timeout=300, retries=3)
    if a.kind == "bb":
        pl = make_bb(llm, a.brief, a.category, a.out)
        print(json.dumps({k: pl[k] for k in ("template", "name", "params", "notes", "seconds")}, indent=1))
    else:
        pl = make_3d(llm, a.brief, a.category or "prop", a.style, a.out, where=a.where)
        print(json.dumps({k: pl["report"].get(k) for k in ("template", "name", "params", "notes", "sheet", "seconds")},
                         indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
