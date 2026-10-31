"""QLoRA SFT of gemma-4-12b's decoder on one 8 GB card (measured fit: fit_probe.py, notes nightly-training-20261029.md).

Memory plan: the 48 decoder layers in NF4 on the GPU; the 262,144 x 3,840 tied embedding stays in host RAM (bf16);
the output head scores only the token ids that occur in the training text plus a general vocabulary file (the
others are never pushed down); the loss is computed for answer tokens only, in chunks, recomputed in backward.
LoRA on q/k/v/o/gate/up/down of the decoder. The saved adapter uses the full checkpoint's tensor names, so
llama.cpp's convert_lora_to_gguf.py can turn it into a GGUF LoRA for `llama-server --lora`.

Data rows (JSONL): {"messages": [{"role": "system"|"user"|"assistant", "content": ...}, ...], "id": ...}; the loss
covers the LAST assistant message only.
Preference pairs (--pairs, JSONL): {"messages": [system, user], "chosen": text, "rejected": text}; trained with ORPO
(odds-ratio preference loss + NLL on the chosen answer, no reference model): one graph on the card at a time
(chosen with grad, rejected without, then rejected with grad), so a pair fits the same 8 GB as one SFT row.
The cosine schedule is fitted to the time box: after the first optimizer steps the planned steps shrink to what
the remaining minutes allow, so a time-boxed run still ends at a low learning rate.
Stops cleanly (saves the adapter) at --max-minutes, on the STOP-SOFT / STOP file next to --stop-dir, or when free
host RAM falls below --ram-floor-gb.
usage: python -m training.nightly.train --model-dir HF_DIR --data sft.jsonl --out RUN_DIR [--val val.jsonl]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from pathlib import Path

PREFIX = "model.language_model."
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def load_rows(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def encode(tok, row: dict, max_len: int) -> tuple[list[int], int] | None:
    """(token ids, index of the first answer token) or None when the prompt alone is too long."""
    # The served prompt (thinking off) ends with an empty thought block that the template leaves out of PAST model
    # turns, so: tokens = exactly the generation prompt the server sends + the answer text + end of turn.
    msgs = row["messages"]
    kw = {"enable_thinking": False}
    prompt_ids = tok.apply_chat_template(msgs[:-1], add_generation_prompt=True, tokenize=True, **kw)
    if hasattr(prompt_ids, "keys"):
        prompt_ids = prompt_ids["input_ids"]
    base = tok.apply_chat_template(msgs[:-1], add_generation_prompt=False, tokenize=False, **kw)
    gen = tok.apply_chat_template(msgs[:-1], add_generation_prompt=True, tokenize=False, **kw)
    full = tok.apply_chat_template(msgs, tokenize=False, **kw)
    if not (full.startswith(base) and gen.startswith(base)):
        return None
    header, tail = gen[len(base):], full[len(base):]
    common = 0
    while common < min(len(header), len(tail)) and header[common] == tail[common]:
        common += 1
    answer_ids = tok(tail[common:], add_special_tokens=False)["input_ids"]
    ids = list(prompt_ids) + list(answer_ids)
    if len(ids) > max_len or len(prompt_ids) >= max_len - 16:
        return None                         # never train on a cut answer
    return ids, len(prompt_ids)


def orpo_coefficients(lc: float, lr: float, beta: float) -> tuple[float, float, float]:
    """ORPO on mean answer log-probs lc (chosen) and lr (rejected), both < 0:
        L = -lc + beta * -log sigmoid(g(lc) - g(lr)),   g(x) = log(p / (1 - p)) = x - log(1 - e^x)
    Returns (dL/dlc, dL/dlr, L) so the caller can back-propagate each answer separately (one graph at a time)."""
    lc, lr = min(lc, -1e-6), min(lr, -1e-6)

    def g(x):
        return x - math.log(-math.expm1(x))

    def dg(x):
        return 1.0 / -math.expm1(x)

    z = g(lc) - g(lr)
    sig = 1.0 / (1.0 + math.exp(-z)) if z > -60 else 0.0
    loss = -lc + beta * (math.log1p(math.exp(-z)) if z > -60 else -z)
    return -1.0 + beta * (sig - 1.0) * dg(lc), beta * (1.0 - sig) * dg(lr), loss


def fit_steps(total: int, step: int, elapsed_s: float, budget_s: float) -> int:
    """Planned optimizer steps that fit the time left (never below the steps already done + 1)."""
    if step <= 0 or elapsed_s <= 0:
        return total
    per = elapsed_s / step
    return max(step + 1, min(total, step + int(max(0.0, budget_s - elapsed_s) / per)))


def vocab_subset(seqs: list[list[int]], extra: list[int], special: list[int]) -> list[int]:
    ids = set(extra) | set(special)
    for s in seqs:
        ids.update(s)
    return sorted(ids)


def build_model(model_dir: Path, dev: str):
    """Text decoder with NF4 linears on the GPU, embedding table on the CPU (returned separately)."""
    import bitsandbytes as bnb
    import torch
    import torch.nn as nn
    from safetensors import safe_open
    from transformers.models.gemma4_unified import modeling_gemma4_unified as M
    from transformers.models.gemma4_unified.configuration_gemma4_unified import Gemma4UnifiedTextConfig

    tc = json.load(open(model_dir / "config.json", encoding="utf-8"))["text_config"]
    tc.pop("model_type", None)
    cfg = Gemma4UnifiedTextConfig(**tc)
    cfg.use_cache = False
    with torch.device("meta"):
        model = M.Gemma4UnifiedTextModel(cfg)
    files = sorted(model_dir.glob("*.safetensors"))
    handles = [safe_open(str(f), framework="pt", device="cpu") for f in files]
    where = {k: h for h in handles for k in h.keys()}

    def tensor(name: str):
        return where[PREFIX + name].get_tensor(PREFIX + name)

    def materialize(module, prefix: str):
        for cname, child in list(module.named_children()):
            full = f"{prefix}{cname}"
            if isinstance(child, nn.Linear):
                w = tensor(full + ".weight").to(torch.bfloat16)
                q = bnb.nn.Linear4bit(child.in_features, child.out_features, bias=child.bias is not None,
                                      compute_dtype=torch.bfloat16, quant_type="nf4", device="cpu")
                q.weight = bnb.nn.Params4bit(w, requires_grad=False, quant_type="nf4")
                if child.bias is not None:
                    q.bias = nn.Parameter(tensor(full + ".bias").to(torch.bfloat16), requires_grad=False)
                setattr(module, cname, q.to(dev))
            else:
                materialize(child, full + ".")
        for pname, p in list(module.named_parameters(recurse=False)):
            key = PREFIX + prefix + pname
            val = where[key].get_tensor(key) if key in where else None
            if val is None:
                raise KeyError(f"missing weight {key}")
            setattr(module, pname, nn.Parameter(val.to(torch.bfloat16 if val.is_floating_point() else val.dtype)
                                                .to(dev), requires_grad=False))
        for bname, b in list(module.named_buffers(recurse=False)):
            key = PREFIX + prefix + bname
            if key in where:
                module.register_buffer(bname, where[key].get_tensor(key).to(dev), persistent=False)

    for i, layer in enumerate(model.layers):
        materialize(layer, f"layers.{i}.")
    materialize(model.norm, "norm.")
    emb = tensor("embed_tokens.weight").to(torch.bfloat16).clone()       # host RAM, own copy
    where.clear()
    del handles                         # unmap the 24 GB file: its pages counted against free RAM (stopped a run)
    import gc
    gc.collect()
    model.embed_tokens = nn.Embedding(1, cfg.hidden_size, device=dev, dtype=torch.bfloat16)  # bypassed
    model.rotary_emb = M.Gemma4UnifiedTextRotaryEmbedding(cfg, device=dev)
    # buffers that are computed, not stored (layer scalars etc. are parameters and were loaded above)
    for mod in model.modules():
        for bname, b in list(mod.named_buffers(recurse=False)):
            if b is not None and b.is_meta:
                raise RuntimeError(f"buffer {bname} of {type(mod).__name__} has no value")
    left = [n for n, p in model.named_parameters() if p.is_meta]
    if left:
        raise RuntimeError(f"weights not loaded: {left[:5]}")
    return model, emb, cfg


def save_adapter(model, out: Path, model_dir: Path, rank: int, meta: dict) -> None:
    """PEFT adapter with the full checkpoint's names (base_model.model.model.language_model.layers.N...)."""
    import torch
    from safetensors.torch import save_file

    out.mkdir(parents=True, exist_ok=True)
    sd = {}
    for name, p in model.named_parameters():
        if "lora_" not in name:
            continue
        core = name.split("base_model.model.", 1)[-1].replace(".default", "")
        sd["base_model.model." + PREFIX + core] = p.detach().to(torch.float32).cpu().contiguous()
    save_file(sd, str(out / "adapter_model.safetensors"))
    cfg = {"peft_type": "LORA", "task_type": "CAUSAL_LM", "r": rank, "lora_alpha": 2 * rank, "lora_dropout": 0.0,
           "target_modules": TARGETS, "bias": "none", "fan_in_fan_out": False, "inference_mode": True,
           "base_model_name_or_path": str(model_dir)}
    (out / "adapter_config.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    (out / "train_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


def free_ram_gb() -> float:
    import psutil
    return psutil.virtual_memory().available / 2**30


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--val", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--vocab-extra", default="", help="text file whose token ids join the output head")
    ap.add_argument("--seq", type=int, default=1024)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--max-minutes", type=float, default=120)
    ap.add_argument("--ram-floor-gb", type=float, default=2.0)
    ap.add_argument("--stop-dir", default=str(Path.home() / ".star" / "nightly"))
    ap.add_argument("--seed", type=int, default=20261029)
    ap.add_argument("--pairs", default="", help="preference pairs (ORPO)")
    ap.add_argument("--orpo-beta", type=float, default=0.1)
    ap.add_argument("--max-gib", type=float, default=7.6, help="ORPO: stop when the reserved peak passes this")
    ap.add_argument("--reserve-minutes", type=float, default=6, help="kept free at the end (val loss + save)")
    a = ap.parse_args()

    import torch
    import bitsandbytes as bnb
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer

    t_start = time.time()
    random.seed(a.seed)
    torch.manual_seed(a.seed)
    model_dir, out = Path(a.model_dir), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = open(out / "train.log", "a", encoding="utf-8")

    def say(msg: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    tok = AutoTokenizer.from_pretrained(str(model_dir))
    train, skipped = [], 0
    for row in load_rows(a.data):
        enc = encode(tok, row, a.seq)
        if enc is None:
            skipped += 1
        else:
            train.append(enc)
    val = [e for e in (encode(tok, r, a.seq) for r in load_rows(a.val)) if e] if a.val else []
    pairs = []
    for r in (load_rows(a.pairs) if a.pairs else []):
        c = encode(tok, {"messages": r["messages"] + [{"role": "assistant", "content": r["chosen"]}]}, a.seq)
        j = encode(tok, {"messages": r["messages"] + [{"role": "assistant", "content": r["rejected"]}]}, a.seq)
        if c and j:
            pairs.append((c, j))
    extra = tok(open(a.vocab_extra, encoding="utf-8").read())["input_ids"] if a.vocab_extra else []
    special = [i for i in (tok.eos_token_id, tok.pad_token_id, tok.bos_token_id) if i is not None]
    special += tok.convert_tokens_to_ids([t for t in ("<end_of_turn>", "<turn|>", "<|turn>") if t in tok.get_vocab()])
    subset = vocab_subset([s for s, _ in train + val] + [x[0] for pr in pairs for x in pr], extra, special)
    remap = {t: i for i, t in enumerate(subset)}
    say(f"train {len(train)} (skipped {skipped} too long), val {len(val)}, pairs {len(pairs)}, head ids {len(subset)}")

    dev = "cuda"
    model, emb, cfg = build_model(model_dir, dev)
    head = emb[subset].to(dev)
    scale = torch.tensor(cfg.hidden_size ** 0.5, dtype=torch.bfloat16)
    softcap = cfg.final_logit_softcapping
    say(f"loaded in {time.time() - t_start:.0f} s; GPU {torch.cuda.memory_allocated() / 2**30:.2f} GiB")
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.0,
                                             target_modules=TARGETS))
    params = [p for p in model.parameters() if p.requires_grad]
    opt = bnb.optim.AdamW8bit(params, lr=a.lr, weight_decay=0.0)
    from training.nightly.fit_probe import chunked_loss

    def loss_of(ids: list[int], start: int) -> torch.Tensor:
        x = (emb[torch.tensor(ids)] * scale).unsqueeze(0).to(dev)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            h = model(inputs_embeds=x).last_hidden_state[0]
            hs = h[start - 1:len(ids) - 1]
            ys = torch.tensor([remap[t] for t in ids[start:]], device=dev)
            return chunked_loss(hs, ys, head, softcap)

    def val_loss() -> float | None:
        if not val:
            return None
        model.eval()
        tot = 0.0
        with torch.no_grad():
            for ids, start in val:
                tot += float(loss_of(ids, start))
        model.train()
        return round(tot / len(val), 4)

    items = [("sft", i) for i in range(len(train))] + [("pair", i) for i in range(len(pairs))]
    total_steps = max(1, math.ceil(len(items) * a.epochs / a.accum))
    planned_steps = total_steps
    warm = max(1, total_steps // 10)

    def lr_at(step: int) -> float:
        if step < warm:
            return a.lr * (step + 1) / warm
        return a.lr * 0.5 * (1 + math.cos(math.pi * (step - warm) / max(1, total_steps - warm)))

    v0 = val_loss()
    say(f"val loss before {v0}; {total_steps} optimizer steps")
    stop_dir = Path(a.stop_dir)
    order: list[tuple] = []
    while len(order) < len(items) * a.epochs:
        perm = list(items)
        random.shuffle(perm)
        order += perm
    order = order[: int(len(items) * a.epochs)]
    step, seen, stopped, run_loss, tokens, pair_loss = 0, 0, "", [], 0, []
    torch.cuda.reset_peak_memory_stats()
    t_train = time.time()
    budget_s = (a.max_minutes - a.reserve_minutes) * 60 - (t_train - t_start)
    model.train()
    for n, (kind, idx) in enumerate(order):
        if kind == "sft":
            ids, start = train[idx]
            loss = loss_of(ids, start) / a.accum
            loss.backward()
            run_loss.append(float(loss.detach()) * a.accum)
            tokens += len(ids)
        else:                                    # ORPO, one graph at a time (see orpo_coefficients)
            (ci, cs), (ri, rs) = pairs[idx]
            with torch.no_grad():                # first, while no graph is alive: peak stays at one SFT row
                lr_v = float(-loss_of(ri, rs))
            lc_t = -loss_of(ci, cs)
            dc, dr, lval = orpo_coefficients(float(lc_t.detach()), lr_v, a.orpo_beta)
            (lc_t * (dc / a.accum)).backward()
            del lc_t
            (-loss_of(ri, rs) * (dr / a.accum)).backward()
            run_loss.append(lval)
            pair_loss.append(lval)
            tokens += len(ci) + 2 * len(ri)
            peak = torch.cuda.max_memory_reserved() / 2**30
            if peak > a.max_gib:                 # would spill into shared memory (8 GB card): let the caller fall back
                say(f"ORPO peak {peak:.2f} GiB > {a.max_gib}: stopping (exit 3, the night retries SFT only)")
                raise SystemExit(3)
        seen += 1
        if seen % a.accum == 0 or n == len(order) - 1:
            for g in opt.param_groups:
                g["lr"] = lr_at(step)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            step += 1
            if step == 10 or (step > 10 and step % 25 == 0):
                fitted = fit_steps(total_steps, step, time.time() - t_train, budget_s)
                if fitted < total_steps:
                    say(f"time box: {total_steps} -> {fitted} planned steps (schedule refitted)")
                    total_steps = fitted
                    warm = min(warm, max(1, total_steps // 10))
            if step % 5 == 0 or step == total_steps:
                say(f"step {step}/{total_steps} loss {sum(run_loss[-a.accum * 5:]) / len(run_loss[-a.accum * 5:]):.4f} "
                    f"{tokens / (time.time() - t_train):.0f} tok/s peak {torch.cuda.max_memory_reserved() / 2**30:.2f} GiB")
        if step >= total_steps and seen % a.accum == 0 and n < len(order) - 1:
            stopped = "fitted schedule done"
        elif (time.time() - t_start) / 60 > a.max_minutes:
            stopped = "time box"
        elif (stop_dir / "STOP-SOFT").exists() or (stop_dir / "STOP").exists():
            stopped = "stop file"
        elif free_ram_gb() < a.ram_floor_gb:
            stopped = f"free RAM below {a.ram_floor_gb} GB"
        if stopped:
            say("stopping: " + stopped)
            break
    v1 = val_loss() if not stopped or stopped in ("time box", "fitted schedule done") else None
    meta = {"examples": len(train), "pairs": len(pairs), "orpo_beta": a.orpo_beta if pairs else None,
            "pair_loss_mean": round(sum(pair_loss) / len(pair_loss), 4) if pair_loss else None,
            "seen": seen, "steps": step, "planned_steps": planned_steps, "fitted_steps": total_steps,
            "stopped": stopped,
            "val_loss_before": v0, "val_loss_after": v1, "rank": a.rank, "lr": a.lr, "seq": a.seq,
            "head_ids": len(subset), "train_minutes": round((time.time() - t_train) / 60, 1),
            "tok_s": round(tokens / max(1e-6, time.time() - t_train), 1),
            "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / 2**30, 2),
            "data": os.path.abspath(a.data), "model_dir": str(model_dir)}
    save_adapter(model, out / "adapter", model_dir, a.rank, meta)
    say("saved adapter: " + json.dumps(meta))


if __name__ == "__main__":
    main()
