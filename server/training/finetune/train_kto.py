"""KTO on pass/fail answers (build_data.py kto/), starting from an SFT LoRA adapter, on the PC's 8 GB card.

    python train_kto.py --model <hf dir> --adapter runs/sft/epoch-1 --data work/ft20/data/kto --out runs/kto

- Unpaired binary labels: a verified answer is desirable, a failing answer to the same (solvable) task undesirable.
- Reference = the starting adapter, frozen: its summed log-probabilities of every completion are computed once before
  training (no second model in VRAM). Policy = a trainable copy of the same adapter.
- Loss (KTO, Ethayarajh et al. 2024): r = log pi(y|x) - log ref(y|x); desirable 1 - sigmoid(beta (r - z0)),
  undesirable 1 - sigmoid(beta (z0 - r)). Simplification: z0 is the detached running mean of r over the last 64
  rows, clamped at 0, instead of TRL's mismatched-pair KL batch (that would cost a third forward pass per row).
- Validation: share of val rows on the right side of z0 ("reward accuracy") and the mean r per label, before and
  after each epoch. Same owner guards as train_qlora.py (GPU busy, games, --stop-procs, RAM floor, STOP-TRAIN).
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import math
from pathlib import Path
import random
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apprentice"))
from train_qlora import RAM_FLOOR_GB, gpu_busy, owner_busy  # noqa: E402


def kto_loss(r: float, label: bool, z0: float, beta: float, w_good: float = 1.0, w_bad: float = 1.0):
    """Works on floats and on torch tensors (r)."""
    import torch
    x = beta * (r - z0) if label else beta * (z0 - r)
    return (w_good if label else w_bad) * (1 - torch.sigmoid(x))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--lr", type=float, default=5e-5)   # 5e-6 (full fine-tune scale) left the LoRA unchanged: loss 0.494 flat over 232 rows
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=3072)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ram-floor", type=float, default=RAM_FLOOR_GB)
    ap.add_argument("--stop-procs", default="")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    stop_file = args.out / "STOP-TRAIN"
    stop_procs = tuple(p.strip().lower() for p in args.stop_procs.split(",") if p.strip())
    why = gpu_busy() or owner_busy(args.ram_floor, stop_procs)
    if why:
        raise SystemExit("not starting: " + why)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, get_cosine_schedule_with_warmup

    tok = AutoTokenizer.from_pretrained(args.model)

    def load(name):
        return [json.loads(l) for l in (args.data / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def encode(row):
        prompt = tok.apply_chat_template(row["prompt"], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        full = tok.apply_chat_template(row["prompt"] + row["completion"], tokenize=False, enable_thinking=False)
        assert full.startswith(prompt), "chat template does not extend the prompt"
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(full[len(prompt):].rstrip("\n"), add_special_tokens=False)["input_ids"]
        ids = (p_ids + a_ids)[:args.max_len]
        labels = ([-100] * len(p_ids) + a_ids)[:args.max_len]
        return {"ids": torch.tensor([ids]), "labels": torch.tensor([labels]), "label": bool(row["label"])}

    train = [encode(r) for r in load("train")]
    val = [encode(r) for r in load("val")]
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    t0 = time.monotonic()
    model = AutoModelForCausalLM.from_pretrained(args.model, quantization_config=bnb, device_map={"": 0},
                                                 dtype=torch.bfloat16)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = PeftModel.from_pretrained(model, args.adapter, is_trainable=True)

    def seq_logp(row):
        # The answer is the tail of the sequence: ask for logits of those positions only (the full [L, 151k] logits
        # pushed the 8 GB card into shared system memory, 11 GB of RAM, in the first run).
        n = int((row["labels"] != -100).sum())
        logits = model(input_ids=row["ids"].cuda(), logits_to_keep=n + 1).logits[0, :-1].float()
        return -torch.nn.functional.cross_entropy(logits, row["labels"][0, -n:].cuda(), reduction="sum")

    model.eval()
    with torch.no_grad():
        for i, row in enumerate(train + val):
            row["ref"] = float(seq_logp(row))
            if i % 16 == 15:
                torch.cuda.empty_cache()
                why = "STOP-TRAIN file" if stop_file.exists() else owner_busy(args.ram_floor, stop_procs)
                if why:
                    raise SystemExit("stopped during the reference pass: " + why)
    ref_s = round(time.monotonic() - t0, 1)

    def evaluate(z0: float) -> dict:
        model.eval()
        good, bad, right = [], [], 0
        with torch.no_grad():
            for row in val:
                r = float(seq_logp(row)) - row["ref"]
                (good if row["label"] else bad).append(r)
                right += (r > z0) == row["label"]
        model.train()
        return {"reward_acc": round(right / max(len(val), 1), 4),
                "mean_r_good": round(sum(good) / max(len(good), 1), 3),
                "mean_r_bad": round(sum(bad) / max(len(bad), 1), 3)}

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)
    total = math.ceil(len(train) / args.accum) * args.epochs
    sched = get_cosine_schedule_with_warmup(opt, max(1, total // 10), total)
    n_good = sum(1 for r in train if r["label"])
    n_bad = len(train) - n_good
    w_bad = min(1.0, n_good / max(n_bad, 1)) if n_bad else 1.0     # keep lambda_D n_D / lambda_U n_U >= 1
    w_good = 1.0
    log = {"model": args.model, "adapter": str(args.adapter), "train": len(train), "val": len(val),
           "desirable": n_good, "undesirable": n_bad, "w_good": w_good, "w_bad": round(w_bad, 4), "beta": args.beta,
           "lr": args.lr, "ref_seconds": ref_s, "val_start": evaluate(0.0), "epochs": []}
    print(json.dumps(log), flush=True)
    torch.cuda.reset_peak_memory_stats()
    rng = random.Random(args.seed)
    recent: deque = deque(maxlen=64)
    model.train()
    stopped = ""
    for epoch in range(1, args.epochs + 1):
        order = list(range(len(train)))
        rng.shuffle(order)
        started, run_loss = time.monotonic(), 0.0
        for i, idx in enumerate(order, 1):
            row = train[idx]
            r = seq_logp(row) - row["ref"]
            z0 = max(0.0, sum(recent) / len(recent)) if recent else 0.0
            loss = kto_loss(r, row["label"], z0, args.beta, w_good, w_bad) / args.accum
            loss.backward()
            recent.append(float(r.detach()))
            run_loss += float(loss) * args.accum
            if i % args.accum == 0 or i == len(order):
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                stopped = "STOP-TRAIN file" if stop_file.exists() else owner_busy(args.ram_floor, stop_procs)
                if stopped:
                    break
                print(f"epoch {epoch} {i}/{len(order)} loss {run_loss / i:.4f} z0 {z0:.3f} "
                      f"{(time.monotonic() - started) / i:.1f}s/ex vram {torch.cuda.max_memory_allocated() / 2**30:.2f}GB",
                      flush=True)
        if stopped:
            model.save_pretrained(args.out / f"partial-epoch-{epoch}")
            log["stopped"] = f"epoch {epoch}: {stopped}"
            break
        z0 = max(0.0, sum(recent) / len(recent)) if recent else 0.0
        model.save_pretrained(args.out / f"epoch-{epoch}")
        log["epochs"].append({"epoch": epoch, "train_loss": round(run_loss / len(order), 4), "z0": round(z0, 3),
                              "val": evaluate(z0), "seconds": round(time.monotonic() - started, 1),
                              "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)})
        print(json.dumps(log["epochs"][-1]), flush=True)
    (args.out / "train-log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
