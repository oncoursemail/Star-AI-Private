"""QLoRA fine-tune of a small code model on the apprentice dataset (build_dataset.py), on the PC's 8 GB card.

    python train_qlora.py --model <hf dir or id> --data work/apprentice/data --out work/apprentice/runs/a1 --epochs 3

- 4-bit NF4 base, LoRA r16 on all attention + MLP projections, bf16 compute, gradient checkpointing, batch 1 with
  gradient accumulation. Loss only on the answer tokens (system + task prompt are masked).
- The prompt is the model's own chat template with thinking off: the same text llama-server builds at inference.
- Saves the adapter after every epoch (epoch-N/) and the one with the lowest validation loss as best/.
- Owner first: refuses to start while the card is busy (GPU util >= 50 % or > 3 GB VRAM used by others), and stops
  after the current step (saving the adapter) when a game starts, a --stop-procs process appears, free RAM drops below
  --ram-floor (6 GB), or STOP-TRAIN exists
  next to --out. `--resume-epoch N` continues from epoch-N/ (optimizer state starts fresh).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import subprocess
import time

RAM_FLOOR_GB = 6.0          # default; --ram-floor changes it (this PC: ~12 GB free with the owner's apps open)
GAME_MARKERS = ("robloxplayerbeta", "steamapps", "epic games", "riot games", "battle.net", "eaapp", "ubisoft")


def gpu_busy() -> str:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout.strip().split(",")
        util, used = int(out[0]), int(out[1])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return ""
    if util >= 50:
        return f"GPU {util}% busy"
    if used > 3072:
        return f"{used} MiB VRAM already in use"
    return ""


def owner_busy(ram_floor: float = RAM_FLOOR_GB, stop_procs: tuple[str, ...] = ()) -> str:
    import psutil
    if psutil.virtual_memory().available / 2**30 < ram_floor:
        return "free RAM below the floor"
    for proc in psutil.process_iter(["name"]) if stop_procs else ():
        name = (proc.info.get("name") or "").lower()
        if any(mark in name for mark in stop_procs):
            return "a stop process is running (" + name + ")"
    games = []
    for proc in psutil.process_iter(["name", "exe"]):
        text = f"{proc.info.get('name') or ''} {proc.info.get('exe') or ''}".lower()
        if any(mark in text for mark in GAME_MARKERS):
            try:
                proc.cpu_percent(None)
                games.append(proc)
            except psutil.Error:
                pass
    if games:
        # A game process that sits idle in the background (e.g. a Roblox player left open) is not someone playing.
        time.sleep(2)
        for proc in games:
            try:
                if proc.cpu_percent(None) >= 10:
                    return "a game is running (" + (proc.info.get("name") or "?") + ")"
            except psutil.Error:
                pass
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=3072)
    ap.add_argument("--resume-epoch", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--ram-floor", type=float, default=RAM_FLOOR_GB, help="stop below this much free RAM (GB)")
    ap.add_argument("--stop-procs", default="", help="comma-separated process-name parts that block/stop training "
                    "whenever they run, idle or not (e.g. robloxstudio)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    stop_file = args.out / "STOP-TRAIN"
    stop_procs = tuple(p.strip().lower() for p in args.stop_procs.split(",") if p.strip())
    why = gpu_busy() or owner_busy(args.ram_floor, stop_procs)
    if why:
        raise SystemExit("not starting: " + why)

    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, get_cosine_schedule_with_warmup

    tok = AutoTokenizer.from_pretrained(args.model)

    def load(name):
        return [json.loads(l) for l in (args.data / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def encode(row):
        msgs = row["messages"]
        prompt = tok.apply_chat_template(msgs[:2], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        full = tok.apply_chat_template(msgs, tokenize=False, enable_thinking=False)
        assert full.startswith(prompt), "chat template does not extend the prompt"
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(full[len(prompt):].rstrip("\n"), add_special_tokens=False)["input_ids"]
        ids = (p_ids + a_ids)[:args.max_len]
        labels = ([-100] * len(p_ids) + a_ids)[:args.max_len]
        return torch.tensor([ids]), torch.tensor([labels]), len(p_ids) + len(a_ids) > args.max_len

    train = [encode(r) for r in load("train")]
    val = [encode(r) for r in load("val")]
    cut = sum(1 for t in train if t[2])
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    t0 = time.monotonic()
    model = AutoModelForCausalLM.from_pretrained(args.model, quantization_config=bnb, device_map={"": 0},
                                                 dtype=torch.bfloat16)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    if args.resume_epoch:
        model = PeftModel.from_pretrained(model, args.out / f"epoch-{args.resume_epoch}", is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(
            r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05, task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.0)
    steps_per_epoch = math.ceil(len(train) / args.accum)
    total = steps_per_epoch * (args.epochs - args.resume_epoch)
    sched = get_cosine_schedule_with_warmup(opt, max(1, total // 10), total)

    def val_loss() -> float:
        model.eval()
        tot, n = 0.0, 0
        with torch.no_grad():
            for ids, labels, _ in val:
                out = model(input_ids=ids.cuda(), labels=labels.cuda())
                k = int((labels[:, 1:] != -100).sum())
                tot, n = tot + float(out.loss) * k, n + k
        model.train()
        return tot / max(n, 1)

    log = {"model": args.model, "train": len(train), "val": len(val), "truncated": cut, "trainable": trainable,
           "load_s": round(time.monotonic() - t0, 1), "epochs": [], "val_loss_start": None}
    log_path = args.out / "train-log.json"
    if args.resume_epoch and log_path.is_file():
        log = json.loads(log_path.read_text(encoding="utf-8"))
        log.pop("stopped", None)
    else:
        log["val_loss_start"] = round(val_loss(), 4)
    print(json.dumps({k: v for k, v in log.items() if k != "epochs"}), flush=True)
    torch.cuda.reset_peak_memory_stats()
    rng = random.Random(args.seed)
    model.train()
    stopped = ""
    for epoch in range(args.resume_epoch + 1, args.epochs + 1):
        order = list(range(len(train)))
        rng.shuffle(order)
        started, run_loss, seen = time.monotonic(), 0.0, 0
        for i, idx in enumerate(order, 1):
            ids, labels, _ = train[idx]
            loss = model(input_ids=ids.cuda(), labels=labels.cuda()).loss / args.accum
            loss.backward()
            run_loss, seen = run_loss + loss.item() * args.accum, seen + 1
            if i % args.accum == 0 or i == len(order):
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()     # WDDM spills a full card into shared (system) memory
                if stop_file.exists():
                    stopped = "STOP-TRAIN file"
                else:
                    stopped = owner_busy(args.ram_floor, stop_procs)
                if stopped:
                    break
                print(f"epoch {epoch} {i}/{len(order)} loss {run_loss / seen:.4f} "
                      f"{(time.monotonic() - started) / i:.1f}s/ex vram {torch.cuda.max_memory_allocated() / 2**30:.2f}GB", flush=True)
        if stopped:
            model.save_pretrained(args.out / f"partial-epoch-{epoch}")
            log["stopped"] = f"epoch {epoch}: {stopped}"
            break
        vl = val_loss()
        model.save_pretrained(args.out / f"epoch-{epoch}")
        log["epochs"].append({"epoch": epoch, "train_loss": round(run_loss / max(seen, 1), 4), "val_loss": round(vl, 4),
                              "seconds": round(time.monotonic() - started, 1),
                              "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)})
        print(json.dumps(log["epochs"][-1]), flush=True)
        log_path.write_text(json.dumps(log, indent=1), encoding="utf-8")
    if log["epochs"]:
        best = min(log["epochs"], key=lambda e: e["val_loss"])
        log["best_epoch"] = best["epoch"]
    log_path.write_text(json.dumps(log, indent=1), encoding="utf-8")
    print(json.dumps({"best_epoch": log.get("best_epoch"), "stopped": log.get("stopped", "")}), flush=True)


if __name__ == "__main__":
    main()
