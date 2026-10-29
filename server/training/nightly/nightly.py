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
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

from training.nightly import correct as C
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


def pair_row(pid: str, prompt: str, chosen: dict, rejected: dict, kind: str) -> dict:
    return {"id": pid, "prompt": prompt, "chosen": chosen["answer"], "rejected": rejected["answer"], "kind": kind,
            "rejected_why": {k: rejected["check"].get(k) for k in ("verify", "rules", "judge")}}


def harvest(cfg: dict, srv, verifier, prompts: list[dict], samples: int, night: Path, say,
            files: dict | None = None, corrections: bool = True, should_stop=None, chunk: int = 40, rounds: int = 2,
            wait_ready=None) -> dict:
    """Answer -> check -> correct the prompts with no passing answer -> re-check, in chunks (one chunk = one kind of
    request at a time, so the server's prompt cache keeps the shared system prompt). Every chunk is written at once
    (bank, pairs, harvest index), so a stopped night keeps what it made. files: {"bank", "pairs", "index"} paths."""
    sysp = system_prompt(cfg)
    work = Path(cfg["work_dir"])
    files = files or {"bank": work / "bank.jsonl", "pairs": work / "pairs.jsonl", "index": work / "harvest_index.jsonl"}
    should_stop = should_stop or stopping
    totals: dict = {"answers": 0, "answers_pass": 0, "prompts": 0, "prompts_with_pass": 0, "first_pass_prompts": 0,
                    "corrections_tried": 0, "corrections_pass": 0, "dpo_pairs": 0, "fail_verify": 0, "fail_rules": 0,
                    "fail_judge": 0, "cut_off": 0, "errors": 0, "gen_tokens": 0, "gen_s": 0.0, "draft_n": 0,
                    "draft_ok": 0}
    t0 = time.time()

    def answer(job):
        p, k = job
        msgs = [{"role": "system", "content": sysp}, {"role": "user", "content": p["prompt"]}]
        return p, k, srv.chat(msgs, temperature=0.7, max_tokens=1200, seed=1000 + k)

    def check(item):
        p, k, ans = item
        chk = S.full_check(srv, verifier, p["prompt"], ans, reference=p.get("reference", ""),
                           safety=p.get("kind") == "safety")
        return {"pid": p["pid"], "k": k, "prompt": p["prompt"], "group": p["group"], "source": p["source"],
                "answer": ans["text"], "finish": ans["finish"], "tokens": ans["tokens"], "check": chk,
                "tok_s": ans.get("tok_s"), "draft_n": ans.get("draft_n"), "draft_ok": ans.get("draft_ok")}

    def account(rows: list[dict]) -> None:
        for r in rows:
            c = r["check"]
            totals["answers"] += 1
            totals["answers_pass"] += bool(c.get("pass"))
            totals["fail_verify"] += (c.get("verify") or {}).get("ok") is False
            totals["fail_rules"] += bool(c.get("rules"))
            totals["fail_judge"] += (c.get("judge") or {}).get("pass") is False
            totals["cut_off"] += not c.get("finished")
            if r.get("tok_s") and r.get("tokens"):
                totals["gen_tokens"] += r["tokens"]
                totals["gen_s"] += r["tokens"] / r["tok_s"]
            totals["draft_n"] += r.get("draft_n") or 0
            totals["draft_ok"] += r.get("draft_ok") or 0

    for c0 in range(0, len(prompts), chunk):
        if should_stop():
            break
        if wait_ready and not wait_ready():
            break
        part = prompts[c0:c0 + chunk]
        answers = [x for x in run_many(answer, [(p, k) for p in part for k in range(samples)], srv.parallel,
                                       should_stop) if x]
        bad_pids = {p["pid"] for p, _, a in answers if a["finish"] == "error"}
        totals["errors"] += sum(1 for _, _, a in answers if a["finish"] == "error")
        answers = [x for x in answers if x[0]["pid"] not in bad_pids]      # retried another night
        rows = [r for r in run_many(check, answers, srv.parallel, should_stop) if r]
        by: dict[str, list[dict]] = {}
        for r in rows:
            by.setdefault(r["pid"], []).append(r)
        fixes: list[tuple] = []
        if corrections:
            for pid, rs in by.items():
                if not any(r["check"].get("pass") for r in rs):
                    p = next(x for x in part if x["pid"] == pid)
                    fixes.append((p, rs[0]))

        def fix(job):
            """Up to `rounds` rewrites: a rewrite that still fails gets the new findings and one more try."""
            p, r = job
            row = None
            for rnd in range(rounds):
                out = C.correct(srv, p["prompt"], r, sysp, reference=p.get("reference", ""), seed=77 + rnd)
                if out is None:
                    break
                row = check((p, 99, out))
                row.update(corrected_from=r["k"], feedback=out["feedback"], round=rnd + 1)
                if row["check"].get("pass"):
                    break
                r = row
            return row

        fixed = [r for r in run_many(fix, fixes, srv.parallel, should_stop) if r] if fixes else []
        totals["corrections_tried"] += len(fixes)
        account(rows)
        jl_append(night / "harvest.jsonl", rows + fixed)
        bank_rows, pairs = [], []
        for pid, rs in by.items():
            good = [r for r in rs if r["check"].get("pass")]
            bad = [r for r in rs if not r["check"].get("pass")]
            corr = [r for r in fixed if r["pid"] == pid and r["check"].get("pass")]
            kind = "first" if good else "corrected" if corr else ""
            if not kind:
                continue
            g = (good or corr)[0]
            totals["first_pass_prompts"] += kind == "first"
            totals["corrections_pass"] += kind == "corrected"
            bank_rows.append({"id": pid, "group": g["group"], "source": g["source"], "night": night.name,
                              "kind": kind, "messages": [{"role": "system", "content": sysp},
                                                         {"role": "user", "content": g["prompt"]},
                                                         {"role": "assistant", "content": g["answer"]}]})
            if bad:
                pairs.append(pair_row(pid, g["prompt"], g, bad[0], kind))
        jl_append(Path(files["bank"]), bank_rows)
        jl_append(Path(files["pairs"]), pairs)
        jl_append(Path(files["index"]), [{"pid": p["pid"], "night": night.name} for p in part
                                         if p["pid"] in by])
        totals["prompts"] += len(by)
        totals["prompts_with_pass"] += len(bank_rows)
        totals["dpo_pairs"] += len(pairs)
        say(f"chunk {c0 // chunk + 1}: {len(by)} prompts, first-try pass {totals['first_pass_prompts']}, corrected "
            f"{totals['corrections_pass']}/{totals['corrections_tried']}, pairs {totals['dpo_pairs']}")
    gen_s = totals.pop("gen_s")
    totals["gen_tok_s"] = round(totals["gen_tokens"] / gen_s, 1) if gen_s else None
    totals["draft_accept"] = round(totals["draft_ok"] / totals["draft_n"], 3) if totals["draft_n"] else None
    totals["minutes"] = round((time.time() - t0) / 60, 1)
    say("harvest " + json.dumps(totals))
    return totals


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


def used_pids(work: Path) -> set[str]:
    return {r["pid"] for f in sorted(work.glob("harvest_index*.jsonl")) for r in jl_read(f)}


def read_all(work: Path, pattern: str) -> list[dict]:
    return [r for f in sorted(work.glob(pattern)) for r in jl_read(f)]


def load_pool(work: Path) -> list[dict]:
    """The clean pool plus the gap-targeted prompts (gaps.py writes pool-gaps.jsonl)."""
    return jl_read(work / "pool.jsonl") + jl_read(work / "pool-gaps.jsonl")


def training_rows(bank: list[dict], upsample_corrected: int = 2) -> list[dict]:
    """One row per prompt id (the first one banked wins); corrected rows repeat: they carry what the model got wrong."""
    seen, out = set(), []
    for r in bank:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out += [r] * (upsample_corrected if r.get("kind") == "corrected" else 1)
    return out


def split_rows(rows: list[dict], seed: int) -> tuple[list[dict], list[dict]]:
    """Validation = ~5% of the prompt ids (all copies of an id stay on one side)."""
    rnd = random.Random(seed)
    ids = sorted({r["id"] for r in rows})
    rnd.shuffle(ids)
    val_ids = set(ids[:max(8, len(ids) // 20)])
    train = [r for r in rows if r["id"] not in val_ids]
    rnd.shuffle(train)
    val = list({r["id"]: r for r in rows if r["id"] in val_ids}.values())
    return train, val


def start_server(cfg: dict, night: Path, parallel: int, say) -> Server:
    """Own harvest server with the node's MTP drafter step when configured (exact decoding, ~1.8x faster on the
    card); the plain server when that does not start (memory)."""
    if cfg.get("draft_model"):
        srv = Server(cfg["llama_server"], cfg["gguf"], parallel=parallel, log=night / "server-harvest.log",
                     draft=cfg["draft_model"])
        try:
            srv.start()
            return srv
        except RuntimeError as e:
            say(f"drafter server did not start ({e}); plain server")
            srv.stop()
    srv = Server(cfg["llama_server"], cfg["gguf"], parallel=parallel, log=night / "server-harvest.log")
    srv.start()
    return srv


def harvest_line(report: dict) -> str:
    h = report.get("harvest") or {}
    if not h:
        return "no harvest"
    return (f"harvest {h.get('prompts_with_pass')}/{h.get('prompts')} prompts banked (first try "
            f"{h.get('first_pass_prompts')}, corrected {h.get('corrections_pass')}/{h.get('corrections_tried')}), "
            f"{h.get('dpo_pairs')} pairs, {h.get('gen_tok_s')} tok/s, drafter accept {h.get('draft_accept')}")


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
    pool = load_pool(work)
    used = used_pids(work)
    prompts = D.night_sample(pool, a.prompts, used, seed=int(night.name.replace("-", "")),
                             shard=D.parse_shard(a.shard), gap_share=a.gap_share)
    report["prompts"] = len(prompts)
    report["prompt_groups"] = D.group_counts(prompts)
    say(f"night {night.name}: {len(prompts)} prompts from a pool of {len(pool)} ({len(used)} used before) "
        f"{report['prompt_groups']}")

    # 2. harvest with the plain deployed model (+ self-corrections of the prompts with no passing answer)
    if a.prompts > 0:
        srv = start_server(cfg, night, a.parallel, say)
        try:
            report["harvest"] = harvest(cfg, srv, verifier, prompts, a.samples, night, say,
                                        corrections=not a.no_corrections)
        finally:
            srv.stop()
        save()
    if stopping():
        report["stopped"] = "stop file after harvest"
        save()
        write_run_line(cfg, f"- {night.name}: {harvest_line(report)}; stopped after harvest (no training)")
        return 124

    # 3. train on the whole bank (every harvest card), corrected rows weighted; ORPO once there are enough pairs
    bank = read_all(work, "bank*.jsonl")
    rows = training_rows(bank, a.upsample_corrected)
    pairs = {r["id"]: r for r in read_all(work, "pairs*.jsonl")}
    report["bank"] = len({r["id"] for r in bank})
    report["bank_corrected"] = len({r["id"] for r in bank if r.get("kind") == "corrected"})
    report["pairs_total"] = len(pairs)
    if report["bank"] < a.min_bank:
        report["skipped_training"] = f"bank {report['bank']} < {a.min_bank}"
        say(report["skipped_training"])
        save()
        write_run_line(cfg, f"- {night.name}: {harvest_line(report)}, bank {report['bank']} (< {a.min_bank}, "
                            f"no training)")
        return 0
    train_rows, val_rows = split_rows(rows, int(night.name.replace("-", "")))
    val_ids = {r["id"] for r in val_rows}
    (night / "train.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in train_rows) + "\n",
                                       encoding="utf-8")
    (night / "val.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in val_rows) + "\n",
                                     encoding="utf-8")
    run_dir = night / "run"
    cmd = [cfg["train_python"], "-m", "training.nightly.train", "--model-dir", cfg["hf_dir"],
           "--data", str(night / "train.jsonl"), "--val", str(night / "val.jsonl"), "--out", str(run_dir),
           "--max-minutes", str(a.train_minutes), "--epochs", str(a.epochs), "--vocab-extra", cfg["system_prompt"]]
    sft_cmd = list(cmd)
    if len(pairs) >= a.orpo_min_pairs:
        # ORPO trains NLL on every chosen answer too, so a prompt with a pair leaves the SFT list
        sysp = system_prompt(cfg)
        pref = [{"id": r["id"], "messages": [{"role": "system", "content": sysp},
                                             {"role": "user", "content": r["prompt"]}],
                 "chosen": r["chosen"], "rejected": r["rejected"]} for r in pairs.values() if r["id"] not in val_ids]
        pref_ids = {r["id"] for r in pref}
        (night / "pairs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in pref) + "\n",
                                           encoding="utf-8")
        (night / "train-orpo.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in train_rows
                                                          if r["id"] not in pref_ids) + "\n", encoding="utf-8")
        cmd[cmd.index("--data") + 1] = str(night / "train-orpo.jsonl")
        cmd += ["--pairs", str(night / "pairs.jsonl"), "--orpo-beta", str(a.orpo_beta)]
        report["orpo_pairs"] = len(pref)
    say("train: " + " ".join(cmd[1:4]) + f" ... ({len(train_rows)} SFT rows, {report.get('orpo_pairs', 0)} "
        f"ORPO pairs)")
    t_train = time.time()
    rc = subprocess.run(cmd, cwd=str(HERE.parents[1]),
                        creationflags=0x08000000 | 0x00004000 if os.name == "nt" else 0).returncode
    meta_p = run_dir / "adapter" / "train_meta.json"
    left = a.train_minutes - (time.time() - t_train) / 60
    if rc != 0 and report.get("orpo_pairs") and not stopping() and left > 30:   # ORPO failed: plain SFT instead
        report["orpo_error"] = f"train with pairs exited {rc}; retried SFT only"
        say(report["orpo_error"])
        sft_cmd[sft_cmd.index("--max-minutes") + 1] = str(int(left))
        rc = subprocess.run(sft_cmd, cwd=str(HERE.parents[1]),
                            creationflags=0x08000000 | 0x00004000 if os.name == "nt" else 0).returncode
    if rc != 0 or not meta_p.exists():
        report["train_error"] = f"train exited {rc}"
        save()
        write_run_line(cfg, f"- {night.name}: {harvest_line(report)}, bank {report['bank']}, TRAIN FAILED (exit {rc})")
        return 1
    report["train"] = json.loads(meta_p.read_text(encoding="utf-8"))
    gguf = night / "litha-nightly.gguf"
    export_gguf(cfg, run_dir / "adapter", gguf)
    report["adapter"] = str(gguf)
    save()
    if stopping():          # the card goes back now; `eval-only --adapter <gguf>` measures it in a later window
        report["stopped"] = "stop file after training (adapter kept, not evaluated)"
        save()
        write_run_line(cfg, f"- {night.name}: {harvest_line(report)}, bank {report['bank']}, trained "
                            f"{report['train'].get('steps')}/{report['train'].get('planned_steps')} "
                            f"steps, stopped before eval ({report['train'].get('stopped') or 'stop file'})")
        return 124
    return evaluate_and_decide(cfg, gguf, night, report, say, save, a.margin)


def remote_harvest(a) -> int:
    """Harvest on another card through its mesh node (STAR's PC 4060). Runs only while that node is loaded and idle
    (its own busy guard decides: games, OBS, her own models, CPU), and only while the owner PC has had no input for
    --min-owner-idle seconds (the owner is not using Litha then, so no request of his waits behind a harvest one). Writes bank-<name>,
    pairs-<name>, harvest_index-<name>.jsonl; the night's training reads every bank*.jsonl."""
    from training.nightly import gpu_hold as H
    from training.nightly.serve import Remote
    cfg = load_config(Path(a.config))
    work = Path(cfg["work_dir"])
    night = work / "nights" / (dt.date.today().isoformat() + "-" + a.name)
    night.mkdir(parents=True, exist_ok=True)
    log = (night / "night.log").open("a", encoding="utf-8")

    def say(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    node_cfg = (cfg.get("harvest_nodes") or {}).get(a.name, {})        # machine-local: {"url", "status"}
    srv = Remote(a.node_url or node_cfg["url"], cfg.get("mesh_token_file", "~/.star/mesh_token"),
                 a.status_url or node_cfg.get("status", ""), parallel=1)
    verifier = S.Verifier(cfg["verify_url"], cfg["key_file"])
    end = time.time() + a.max_hours * 3600

    def stop_now() -> bool:
        return (STOP_DIR / "STOP").exists() or (STOP_DIR / f"STOP-{a.name}").exists() or time.time() > end

    def wait_ready() -> bool:
        last = ""
        while not stop_now():
            ok, why = srv.available()
            owner_ok = H.idle_seconds() >= a.min_owner_idle
            if ok and owner_ok:
                return True
            msg = f"waiting: node {why}; owner idle {int(H.idle_seconds())} s"
            if msg.split(";")[0] != last:
                say(msg)
                last = msg.split(";")[0]
            time.sleep(60)
        return False

    pool = load_pool(work)
    used = used_pids(work)
    prompts = D.night_sample(pool, a.prompts, used, seed=int(time.strftime("%Y%m%d%H")),
                             shard=D.parse_shard(a.shard), gap_share=a.gap_share)
    say(f"{a.name}: {len(prompts)} prompts ({len(used)} used before) {D.group_counts(prompts)}")
    files = {"bank": work / f"bank-{a.name}.jsonl", "pairs": work / f"pairs-{a.name}.jsonl",
             "index": work / f"harvest_index-{a.name}.jsonl"}
    stats = harvest(cfg, srv, verifier, prompts, a.samples, night, say, files=files, should_stop=stop_now,
                    chunk=a.chunk, wait_ready=wait_ready)
    (night / f"report-{time.strftime('%H%M')}.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    return 0


def evaluate_and_decide(cfg, gguf: Path, night: Path, report: dict, say, save, margin: int) -> int:
    verifier = S.Verifier(cfg["verify_url"], cfg["key_file"])
    with Server(cfg["llama_server"], cfg["gguf"], lora=str(gguf), parallel=2, log=night / "server-eval.log") as srv:
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
    prev_dec = (json.loads(current.read_text(encoding="utf-8")).get("decision") or {}) if current.exists() else {}
    if prev_dec.get("new_pass") is not None and dec["new_pass"] <= prev_dec["new_pass"]:
        dec["promote"] = False             # each night trains from the base; it must also beat the adapter in use
        dec["reasons"].append(f"not better than the current adapter ({dec['new_pass']} <= {prev_dec['new_pass']})")
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
        if cfg.get("auto_deploy"):          # behind the gate only: the node answers with the adapter from now on
            from training.nightly import deploy as DP
            report["deploy"] = DP.deploy(str(target), Path(os.path.expanduser(cfg.get("node_dir", str(DP.NODE_DIR)))),
                                         say=say)
    save()
    dep = report.get("deploy") or {}
    live = (" LIVE on the node" if dep.get("deployed") else f" NOT live ({dep.get('reason')}, rolled back)"
            if dep else " (auto_deploy off: not live)") if dec["promote"] else ""
    write_run_line(cfg, f"- {night.name}: {harvest_line(report)}; bank {report.get('bank')} "
                        f"(corrected {report.get('bank_corrected')}), pairs {report.get('pairs_total')}, ORPO "
                        f"{report.get('orpo_pairs', 0)}; held-out base {dec['base_pass']}/{dec['n']} vs "
                        f"adapter {dec['new_pass']}/{dec['n']} (wins {dec['wins']}, losses {dec['losses']}, "
                        f"p={dec['sign_p']}), safety {dec['safety_base']}->{dec['safety_new']}, verifier problems "
                        f"{dec['verify_problems_base']}->{dec['verify_problems_new']}: "
                        f"{'PROMOTED' + live if dec['promote'] else 'kept current (' + '; '.join(dec['reasons']) + ')'}")
    say("decision " + json.dumps(dec))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run", "eval-only", "harvest"])
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--prompts", type=int, default=600)
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--train-minutes", type=float, default=150)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--min-bank", type=int, default=100)
    ap.add_argument("--margin", type=int, default=3)
    ap.add_argument("--rebuild-pool", action="store_true")
    ap.add_argument("--adapter", default="")
    ap.add_argument("--shard", default="0/2", help="i/n: only prompts whose id hash mod n == i (two harvest cards)")
    ap.add_argument("--gap-share", type=float, default=0.3, help="share of gap-targeted prompts (pool-gaps.jsonl)")
    ap.add_argument("--no-corrections", action="store_true")
    ap.add_argument("--upsample-corrected", type=int, default=2)
    ap.add_argument("--orpo-min-pairs", type=int, default=400)
    ap.add_argument("--orpo-beta", type=float, default=0.1)
    # harvest mode: another card through its mesh node
    ap.add_argument("--name", default="starpc")
    ap.add_argument("--node-url", default="")
    ap.add_argument("--status-url", default="")
    ap.add_argument("--chunk", type=int, default=20)
    ap.add_argument("--max-hours", type=float, default=12)
    ap.add_argument("--min-owner-idle", type=float, default=600)
    a = ap.parse_args(argv)
    if a.mode == "harvest":
        return remote_harvest(a)
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
