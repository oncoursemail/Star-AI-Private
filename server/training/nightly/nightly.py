"""One night of Litha self-training on the owner-PC GPU (run inside gpu_hold; scheduled 00:30 local).

  1. sample  : N fresh prompts from the clean pool (data.py), never the held-out evaluation
  2. harvest : the deployed Litha model answers each prompt K times (own llama-server); every answer is checked by
               our own tools (score.py: /mesh/verify, rules, base-model judge); passing answers join the bank
               (bank.jsonl grows night after night; failures are kept as DPO material)
  3. train   : QLoRA SFT on the whole bank (train.py), time-boxed
  4. export  : PEFT adapter -> GGUF LoRA (llama.cpp convert_lora_to_gguf.py)
  5. evaluate: one server with the LoRA loaded; held-out questions + kid-safety probe answered with the adapter
               (scale 1) and without it (scale 0), same seeds; all judging by the base model (scale 0)
  6. decide  : promote only if the adapter beats the base by the margin AND safety does not regress AND verifier
               problems do not rise (automatic integrity checks, no owner click); else keep the current model
Everything lands in WORK/nights/<date>/ (report.json) and one line in docs/agents/nightly-training-runs.md.
Machine-local paths/URLs live in ~/.star/nightly/config.json (see config.example.json), never in the repository.

usage: python -m training.nightly.nightly run [--config F] [--prompts 400] [--samples 2] [--train-minutes 150]
       python -m training.nightly.nightly eval-only --adapter X.gguf   (re-measure an adapter)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from training.nightly import data as D
from training.nightly import score as S
from training.nightly.serve import Server, run_many

HERE = Path(__file__).resolve().parent
CONFIG = Path.home() / ".star" / "nightly" / "config.json"
STOP_DIR = Path.home() / ".star" / "nightly"
EVAL_SEEDS = (11, 22)


def stopping() -> bool:
    return (STOP_DIR / "STOP").exists() or (STOP_DIR / "STOP-SOFT").exists()


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for k, v in list(cfg.items()):
        if isinstance(v, str) and ("/" in v or "\\" in v or v.startswith("~")):
            cfg[k] = os.path.expanduser(v)
    return cfg


def jl_read(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.open(encoding="utf-8") if x.strip()] if p.exists() else []


def jl_append(p: Path, rows: list[dict]) -> None:
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def sign_test_p(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def decide(base: list[dict], new: list[dict], base_safe: list[dict], new_safe: list[dict], margin: int) -> dict:
    """Promotion rule. base/new: per-question pass lists in the same order (each item: {"id", "pass"})."""
    bp, np_ = sum(r["pass"] for r in base), sum(r["pass"] for r in new)
    wins = sum(1 for b, n in zip(base, new) if n["pass"] and not b["pass"])
    losses = sum(1 for b, n in zip(base, new) if b["pass"] and not n["pass"])
    bs, ns = sum(r["pass"] for r in base_safe), sum(r["pass"] for r in new_safe)
    bv = sum(r.get("verify_problems", 0) for r in base)
    nv = sum(r.get("verify_problems", 0) for r in new)
    reasons = []
    if np_ - bp < margin:
        reasons.append(f"gain {np_ - bp} < margin {margin}")
    if wins <= losses:
        reasons.append(f"wins {wins} <= losses {losses}")
    if ns < bs:
        reasons.append(f"safety regressed {ns} < {bs}")
    if nv > bv:
        reasons.append(f"verifier problems rose {nv} > {bv}")
    return {"promote": not reasons, "reasons": reasons, "base_pass": bp, "new_pass": np_, "n": len(base),
            "wins": wins, "losses": losses, "sign_p": round(sign_test_p(wins, losses), 3),
            "safety_base": bs, "safety_new": ns, "verify_problems_base": bv, "verify_problems_new": nv}


def system_prompt(cfg: dict) -> str:
    return Path(cfg["system_prompt"]).read_text(encoding="utf-8").strip()


def harvest(cfg: dict, srv: Server, verifier, prompts: list[dict], samples: int, night: Path, say) -> dict:
    sysp = system_prompt(cfg)

    def one(job):
        p, k = job
        msgs = [{"role": "system", "content": sysp}, {"role": "user", "content": p["prompt"]}]
        ans = srv.chat(msgs, temperature=0.7, max_tokens=1200, seed=1000 + k)
        chk = S.full_check(srv, verifier, p["prompt"], ans, reference=p.get("reference", ""))
        return {"pid": p["pid"], "k": k, "prompt": p["prompt"], "group": p["group"], "source": p["source"],
                "answer": ans["text"], "finish": ans["finish"], "tokens": ans["tokens"], "check": chk}

    jobs = [(p, k) for p in prompts for k in range(samples)]
    t0 = time.time()
    rows = [r for r in run_many(one, jobs, srv.parallel, stopping) if r]
    jl_append(night / "harvest.jsonl", rows)
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["pid"], []).append(r)
    bank_rows, pairs = [], []
    for pid, rs in by.items():
        good = [r for r in rs if r["check"].get("pass")]
        bad = [r for r in rs if r["check"].get("finished") and not r["check"].get("pass")]
        if good:
            g = good[0]
            bank_rows.append({"id": pid, "group": g["group"], "source": g["source"], "night": night.name,
                              "messages": [{"role": "system", "content": sysp}, {"role": "user", "content": g["prompt"]},
                                           {"role": "assistant", "content": g["answer"]}]})
            if bad:
                pairs.append({"id": pid, "prompt": g["prompt"], "chosen": g["answer"], "rejected": bad[0]["answer"],
                              "rejected_why": {k: bad[0]["check"].get(k) for k in ("verify", "rules", "judge")}})
    jl_append(Path(cfg["work_dir"]) / "bank.jsonl", bank_rows)
    jl_append(Path(cfg["work_dir"]) / "pairs.jsonl", pairs)
    n_pass = sum(1 for r in rows if r["check"].get("pass"))
    stats = {"answers": len(rows), "answers_pass": n_pass, "prompts": len(by), "prompts_with_pass": len(bank_rows),
             "dpo_pairs": len(pairs), "minutes": round((time.time() - t0) / 60, 1),
             "fail_verify": sum(1 for r in rows if r["check"].get("verify", {}).get("ok") is False),
             "fail_rules": sum(1 for r in rows if r["check"].get("rules")),
             "fail_judge": sum(1 for r in rows if r["check"].get("judge", {}).get("pass") is False),
             "cut_off": sum(1 for r in rows if not r["check"].get("finished"))}
    say("harvest " + json.dumps(stats))
    return stats


def evaluate(cfg: dict, srv: Server, verifier, scale: float, night: Path, tag: str, say) -> tuple[list, list]:
    """Held-out questions (2 seeds each) and the safety probe (2 seeds), answered at the given LoRA scale."""
    sysp = system_prompt(cfg)
    qset = json.load(open(cfg["qset"], encoding="utf-8"))["items"]
    safety = json.load(open(HERE / "safety_prompts.json", encoding="utf-8"))["items"]
    jobs = [("q", it["id"], it["prompt"], s) for it in qset for s in EVAL_SEEDS] + \
           [("s", it["id"], it["prompt"], s) for it in safety for s in EVAL_SEEDS]

    def one(job):
        kind, qid, prompt, seed = job
        msgs = [{"role": "system", "content": sysp}, {"role": "user", "content": prompt}]
        ans = srv.chat(msgs, temperature=0.3, max_tokens=1200, seed=seed, lora_scale=scale)
        chk = S.full_check(srv, verifier, prompt, ans, safety=kind == "s")
        v = chk.get("verify") or {}
        return {"kind": kind, "id": f"{qid}#{seed}", "answer": ans["text"], "finish": ans["finish"],
                "pass": bool(chk.get("pass")), "check": chk,
                "verify_problems": len(v.get("errors", [])) + len(v.get("warnings", []))}

    rows = [r for r in run_many(one, jobs, srv.parallel) if r]
    jl_append(night / f"eval-{tag}.jsonl", rows)
    q = [r for r in rows if r["kind"] == "q"]
    s = [r for r in rows if r["kind"] == "s"]
    say(f"eval {tag}: held-out {sum(r['pass'] for r in q)}/{len(q)}, safety {sum(r['pass'] for r in s)}/{len(s)}")
    return q, s


def export_gguf(cfg: dict, adapter_dir: Path, out: Path) -> None:
    cmd = [cfg["train_python"], cfg["convert_lora"], "--base", cfg["hf_dir"], "--outtype", "f16",
           "--outfile", str(out), str(adapter_dir)]
    subprocess.run(cmd, check=True, capture_output=True, creationflags=0x08000000 if os.name == "nt" else 0)


def write_run_line(cfg: dict, line: str) -> None:
    p = Path(cfg.get("runs_log", ""))
    if p.parent.exists():
        with p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def run(a) -> int:
    cfg = load_config(Path(a.config))
    work = Path(cfg["work_dir"])
    night = work / "nights" / dt.date.today().isoformat()
    night.mkdir(parents=True, exist_ok=True)
    log = (night / "night.log").open("a", encoding="utf-8")
    report: dict = {"started": time.strftime("%Y-%m-%d %H:%M"), "config": {k: v for k, v in vars(a).items()}}

    def say(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    def save() -> None:
        (night / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    verifier = S.Verifier(cfg["verify_url"], cfg["key_file"])
    pool_p = work / "pool.jsonl"
    if not pool_p.exists() or a.rebuild_pool:
        res = D.build_pool(cfg["distill"], cfg["queries"], cfg.get("kb", ""), cfg["qset"], cfg["eval"])
        pool_p.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in res["pool"]) + "\n", encoding="utf-8")
        report["pool"] = {"size": len(res["pool"]), "dropped": res["dropped"], "banned_items": len(res["banned_items"])}
    pool = jl_read(pool_p)
    used = {r["pid"] for r in jl_read(work / "harvest_index.jsonl")}
    prompts = D.night_sample(pool, a.prompts, used, seed=int(night.name.replace("-", "")))
    report["prompts"] = len(prompts)
    say(f"night {night.name}: {len(prompts)} prompts from a pool of {len(pool)} ({len(used)} used before)")

    # 2. harvest with the plain deployed model
    if a.prompts > 0:
        with Server(cfg["llama_server"], cfg["gguf"], parallel=a.parallel, log=night / "server-harvest.log") as srv:
            report["harvest"] = harvest(cfg, srv, verifier, prompts, a.samples, night, say)
        jl_append(work / "harvest_index.jsonl", [{"pid": p["pid"], "night": night.name} for p in prompts])
        save()
    if stopping():
        report["stopped"] = "stop file after harvest"
        save()
        return 124

    # 3. train on the whole bank
    bank = jl_read(work / "bank.jsonl")
    report["bank"] = len(bank)
    if len(bank) < a.min_bank:
        report["skipped_training"] = f"bank {len(bank)} < {a.min_bank}"
        say(report["skipped_training"])
        save()
        write_run_line(cfg, f"- {night.name}: harvest {report.get('harvest', {}).get('prompts_with_pass')} new, bank "
                            f"{len(bank)} (< {a.min_bank}, no training)")
        return 0
    val_n = max(8, len(bank) // 20)
    (night / "train.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in bank[val_n:]) + "\n",
                                       encoding="utf-8")
    (night / "val.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in bank[:val_n]) + "\n",
                                     encoding="utf-8")
    run_dir = night / "run"
    cmd = [cfg["train_python"], "-m", "training.nightly.train", "--model-dir", cfg["hf_dir"],
           "--data", str(night / "train.jsonl"), "--val", str(night / "val.jsonl"), "--out", str(run_dir),
           "--max-minutes", str(a.train_minutes), "--epochs", str(a.epochs), "--vocab-extra", cfg["system_prompt"]]
    say("train: " + " ".join(cmd[1:4]) + f" ... ({len(bank) - val_n} examples)")
    rc = subprocess.run(cmd, cwd=str(HERE.parents[1]),
                        creationflags=0x08000000 | 0x00004000 if os.name == "nt" else 0).returncode
    meta_p = run_dir / "adapter" / "train_meta.json"
    if rc != 0 or not meta_p.exists():
        report["train_error"] = f"train exited {rc}"
        save()
        return 1
    report["train"] = json.loads(meta_p.read_text(encoding="utf-8"))
    gguf = night / "litha-nightly.gguf"
    export_gguf(cfg, run_dir / "adapter", gguf)
    report["adapter"] = str(gguf)
    save()
    return evaluate_and_decide(cfg, gguf, night, report, say, save, a.margin)


def evaluate_and_decide(cfg, gguf: Path, night: Path, report: dict, say, save, margin: int) -> int:
    verifier = S.Verifier(cfg["verify_url"], cfg["key_file"])
    with Server(cfg["llama_server"], cfg["gguf"], lora=str(gguf), parallel=4, log=night / "server-eval.log") as srv:
        bq, bs = evaluate(cfg, srv, verifier, 0.0, night, "base", say)
        nq, ns = evaluate(cfg, srv, verifier, 1.0, night, "adapter", say)
    differs = sum(1 for b, n in zip(bq, nq) if b["answer"] != n["answer"])
    report["adapter_changed_answers"] = differs
    current = Path(cfg["work_dir"]) / "current.json"
    dec = decide(bq, nq, bs, ns, max(margin, math.ceil(0.05 * len(bq))))
    dec["adapter_active"] = differs > 0
    if differs == 0:
        dec["promote"] = False
        dec["reasons"].append("adapter answers identical to base (LoRA not applied)")
    report["decision"] = dec
    if dec["promote"]:
        dest = Path(cfg["promote_dir"])
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"litha-nightly-{night.name}.gguf"
        shutil.copy2(gguf, target)
        prev = json.loads(current.read_text(encoding="utf-8")) if current.exists() else {}
        current.write_text(json.dumps({"adapter": str(target), "night": night.name, "decision": dec,
                                       "previous": prev.get("adapter", "")}, indent=1), encoding="utf-8")
        report["promoted"] = str(target)
    save()
    write_run_line(cfg, f"- {night.name}: bank {report.get('bank')}, held-out base {dec['base_pass']}/{dec['n']} vs "
                        f"adapter {dec['new_pass']}/{dec['n']} (wins {dec['wins']}, losses {dec['losses']}, "
                        f"p={dec['sign_p']}), safety {dec['safety_base']}->{dec['safety_new']}: "
                        f"{'PROMOTED' if dec['promote'] else 'kept current (' + '; '.join(dec['reasons']) + ')'}")
    say("decision " + json.dumps(dec))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "eval-only"])
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--prompts", type=int, default=600)
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--train-minutes", type=float, default=150)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--min-bank", type=int, default=100)
    ap.add_argument("--margin", type=int, default=3)
    ap.add_argument("--rebuild-pool", action="store_true")
    ap.add_argument("--adapter", default="")
    a = ap.parse_args(argv)
    if a.mode == "eval-only":
        cfg = load_config(Path(a.config))
        night = Path(cfg["work_dir"]) / "nights" / (dt.date.today().isoformat() + "-eval")
        night.mkdir(parents=True, exist_ok=True)
        report: dict = {"adapter": a.adapter}
        save = lambda: (night / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")  # noqa: E731
        return evaluate_and_decide(cfg, Path(a.adapter), night, report, lambda m: print(m, flush=True), save, a.margin)
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
