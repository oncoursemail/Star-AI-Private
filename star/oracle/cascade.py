"""The cascade: cheapest layer first, stop at the first confident answer.

    perf-only change  -> L0 greedy equivalence; EQUIVALENT -> SAME. Otherwise L1: KL ~ 0 and top-1 ~ 100 % -> SAME.
    model change      -> L1 (reported) + L2 probe -> calibrated pass-rate delta; interval excludes 0 -> BETTER/WORSE.
    prompt change     -> L2 probe -> same.
    loop change       -> nothing below L3 can see it.
    anything else     -> ESCALATE, and with --max-layer 3 the adaptive paired eval (L3) decides.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from . import calibrate, config, equiv, irt, probe, prompts, score

# L1 "same function" bounds for perf-only changes: just above the measured numerical noise of ONE model scored with
# batch 128 vs 512 on the PC GPU (KL 0.0028 nats/token, top-1 agreement 98.3 %, docs/agents/oracle-20261021.md).
# For scale: a prompt change (worked-example block) measured 0.033 and a LoRA fine-tune 0.24 on the same corpus.
SAME_KL_PER_TOKEN = 0.005
SAME_TOP1 = 0.98
TOPK = 32


def _cached_scores(cfg: config.Config, items: list[dict], workdir: Path, *, topk: int = 0, ref: Path | None = None,
                   log=print) -> tuple[list[dict], dict]:
    """Reuse an earlier scorer run with byte-identical inputs (a baseline is usually compared many times)."""
    key = hashlib.sha256(json.dumps([items, cfg.model, cfg.lora, cfg.ngl, cfg.ctx, topk,
                                     str(ref) if ref else ""], sort_keys=True).encode("utf-8")).hexdigest()
    mark = Path(workdir) / f"{cfg.name}.key"
    out = Path(workdir) / f"{cfg.name}.scores.jsonl"
    if mark.is_file() and out.is_file() and mark.read_text(encoding="utf-8") == key:
        rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
        return rows, {"seconds": 0.0, "cached": True, "items": len(rows)}
    rows, cost = score.run_scorer(cfg, items, workdir, topk=topk, ref=ref, log=log)
    mark.write_text(key, encoding="utf-8")
    return rows, cost


def _l3(base: config.Config, cand: config.Config, suites: list[str], history: list[str], workdir: Path,
        log=print) -> dict:
    keys: dict[str, tuple[str, str]] = {}
    for suite in suites:
        tasks = json.loads(Path(suite).read_text(encoding="utf-8"))
        for t in tasks if isinstance(tasks, list) else tasks.get("tasks", []):
            if t.get("run_mode") == "automated":
                keys[irt.task_key(suite, t["id"])] = (suite, t["id"])
    runs = irt.load_runs(history)
    model = irt.fit(runs) if runs else irt.ItemModel()
    # The baseline's ability from its own past runs (config eval.history), else the history's average run.
    own = {k: v for r in irt.load_runs(base.eval.get("history", [])).values() for k, v in r.items()}
    if model.a and own:
        theta = model.ability(own)
    else:
        theta = sum(model.theta.values()) / len(model.theta) if model.theta else 0.0
    ordered = irt.order(model, theta, sorted(keys))

    def arm(cfg: config.Config, key: str) -> bool | None:
        suite, tid = keys[key]
        out = Path(workdir) / f"l3-{cfg.name}-{Path(suite).stem}.json"
        cmd = [sys.executable, "-m", "star.evals", "run", "--suite", suite, "--tasks", tid, "--out", str(out),
               *[str(a) for a in cfg.eval.get("args", [])]]
        subprocess.run(cmd, check=False)
        try:
            rec = json.loads(out.read_text(encoding="utf-8"))["tasks"].get(tid, {})
        except (OSError, ValueError, KeyError):
            return None
        return {"pass": True, "fail": False}.get(rec.get("status"))

    def pair(key: str):
        b, c = arm(base, key), arm(cand, key)
        return None if b is None or c is None else (b, c)

    result = irt.run_adaptive(ordered, pair, log=log)
    result["theta_base"] = round(theta, 3)
    return result


def compare(base: config.Config, cand: config.Config, *, probe_file: Path | None, workdir: Path, max_layer: int = 2,
            calibration: dict | None = None, l0_prompts: int = 50, suites=(), history=(), log=print) -> dict:
    workdir = Path(workdir)
    kinds = config.change_kinds(base, cand)
    report: dict = {"base": base.name, "cand": cand.name, "kinds": sorted(kinds), "layers": {}, "verdict": "ESCALATE",
                    "decided_at": None, "notes": []}
    if not kinds:
        report.update(verdict="SAME", decided_at="config", notes=["nothing that changes outputs differs"])
        return report
    pairs = probe.read(probe_file) if probe_file else []
    perf_only = kinds == {"perf"}
    if perf_only and max_layer >= 0:
        texts = [prompts.prefix(base, p.prompt) for p in pairs[:l0_prompts]]
        if texts:
            b = equiv.outputs(base, texts, workdir)
            c = equiv.outputs(cand, texts, workdir)
            l0 = equiv.compare(b["tokens"], c["tokens"])
            l0["seconds"] = round(b["seconds"] + c["seconds"], 1)
            report["layers"]["L0"] = l0
            if l0["verdict"] == "EQUIVALENT":
                report.update(verdict="SAME", decided_at="L0")
                return report
        else:
            report["notes"].append("L0 skipped: no probe corpus for prompts")
    if "loop" in kinds:
        report["notes"].append("the change touches the agent loop (retry ladder / slop repair): L0-L2 cannot see it")
    elif max_layer >= 1 and pairs and kinds & {"perf", "model", "prompt"}:
        brows, bcost = _cached_scores(base, score.items_for(base, pairs), workdir, topk=TOPK, log=log)
        crows, ccost = _cached_scores(cand, score.items_for(cand, pairs), workdir,
                                      ref=workdir / f"{base.name}.scores.jsonl", log=log)
        l1 = score.l1_report(crows)
        if l1:
            l1["seconds"] = bcost["seconds"] + ccost["seconds"]
            report["layers"]["L1"] = l1
            # Server-only flags (launch.args) do not reach the scorer, so L1 cannot vouch for them.
            scorer_sees_it = base.launch.get("args") == cand.launch.get("args")
            if not scorer_sees_it and perf_only:
                report["notes"].append("server-only flags differ (launch.args): L1 cannot judge them")
            if (perf_only and scorer_sees_it and l1["kl_per_token"] <= SAME_KL_PER_TOKEN
                    and l1["top1_agreement"] >= SAME_TOP1):
                report.update(verdict="SAME", decided_at="L1")
                return report
        if max_layer >= 2 and kinds & {"model", "prompt"}:
            l2 = score.l2_report(pairs, brows, crows)
            l2["seconds"] = bcost["seconds"] + ccost["seconds"]
            pred = calibrate.predict(calibration, l2["delta"])
            report["layers"]["L2"] = {**l2, "prediction": pred}
            report["predicted_delta"], report["interval"] = pred["delta"], pred["interval"]
            if pred["verdict"] in ("BETTER", "WORSE"):
                report.update(verdict=pred["verdict"], decided_at="L2")
                return report
    if max_layer >= 3:
        l3 = _l3(base, cand, list(suites), list(history), workdir, log=log)
        report["layers"]["L3"] = l3
        report.update(verdict={"NO_CLEAR_DIFFERENCE": "SAME_AT_L3"}.get(l3["decision"], l3["decision"]),
                      decided_at="L3" if l3["decision"] != irt.INCONCLUSIVE else None)
    return report


def markdown(report: dict) -> str:
    lines = [f"# Star Oracle: {report['cand']} vs {report['base']}",
             f"**Verdict: {report['verdict']}**"
             + (f" (decided at {report['decided_at']})" if report["decided_at"] else ""),
             f"Change kinds: {', '.join(report['kinds']) or 'none'}"]
    if report.get("predicted_delta") is not None:
        lo, hi = report["interval"]
        lines.append(f"Predicted pass-rate change: {report['predicted_delta']:+.3f} "
                     f"(90 % interval {lo:+.3f} .. {hi:+.3f})")
    layers = report["layers"]
    if "L0" in layers:
        l0 = layers["L0"]
        lines.append(f"- L0 greedy equivalence: {l0['verdict']} on {l0['prompts']} prompts "
                     f"({l0['differing_prompts']} differ; first {l0['first_difference']}), {l0['seconds']} s")
    if "L1" in layers:
        l1 = layers["L1"]
        lines.append(f"- L1 distribution: KL {l1['kl_per_token']:.5f} nats/token, top-1 agreement "
                     f"{100 * l1['top1_agreement']:.2f} % over {l1['tokens']} tokens")
    if "L2" in layers:
        l2 = layers["L2"]
        lines.append(f"- L2 probe: margin {l2['base_margin']} -> {l2['cand_margin']} nats (delta {l2['delta']:+.3f}, "
                     f"90 % {l2['delta_ci90'][0]:+.3f} .. {l2['delta_ci90'][1]:+.3f}); prefers GOOD "
                     f"{100 * l2['base_pref_acc']:.1f} % -> {100 * l2['cand_pref_acc']:.1f} % of {l2['twins']} twins; "
                     f"{l2['seconds']} s")
    if "L3" in layers:
        l3 = layers["L3"]
        lines.append(f"- L3 adaptive eval: {l3['decision']} after {l3['tasks_run']} tasks "
                     f"({l3['wins']}W/{l3['losses']}L/{l3['ties']}T, sign p(better) {l3['sign_p_better']})")
    lines.extend(f"- note: {n}" for n in report["notes"])
    return "\n".join(lines) + "\n"
