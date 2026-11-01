"""Does QLoRA on gemma-4-12b fit an 8 GB card? Builds the real text architecture from config.json with RANDOM
weights (no download) and runs training steps; prints peak VRAM, host RAM and tokens/s.

The 10-28 probe (docs/agents/litha-brain-20261028.md) measured 12.4 GiB: the 262,144 x 3,840 tied embedding in bf16
on the GPU (1.9 GiB) and full-vocabulary fp32 logits for every token. The tricks measured here:
  --embed-cpu        the embedding table stays in host RAM (bf16); only the looked-up rows go to the GPU
  --vocab-sub N      the output head scores only N token ids (the ids that occur in the training data; the ignored
                     ids are never pushed down, acceptable for a LoRA on the decoder) - 0 = full vocabulary
  chunked loss       logits only for answer tokens, 256 at a time, recomputed in backward (checkpoint)
usage: fit_probe.py CONFIG_JSON --seq 1024 [--embed-cpu] [--vocab-sub 32768] [--rank 16] [--steps 4]
"""
from __future__ import annotations

import argparse
import json
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def chunked_loss(h: torch.Tensor, labels: torch.Tensor, head: torch.Tensor, softcap: float | None,
                 chunk: int = 256) -> torch.Tensor:
    """Mean CE over rows of h (n x H) against labels (n) using head (V x H); logits are never kept for backward."""

    def part(hc, yc):
        logits = (hc @ head.t()).float()
        if softcap:
            logits = softcap * torch.tanh(logits / softcap)
        return F.cross_entropy(logits, yc, reduction="sum")

    total = h.new_zeros((), dtype=torch.float32)
    for i in range(0, h.shape[0], chunk):
        total = total + checkpoint(part, h[i:i + chunk], labels[i:i + chunk], use_reentrant=False)
    return total / max(1, h.shape[0])


def build(cfg_path: str, dev: str):
    import bitsandbytes as bnb
    from transformers.models.gemma4_unified import modeling_gemma4_unified as M
    from transformers.models.gemma4_unified.configuration_gemma4_unified import Gemma4UnifiedTextConfig

    tc = json.load(open(cfg_path, encoding="utf-8"))["text_config"]
    tc.pop("model_type", None)
    cfg = Gemma4UnifiedTextConfig(**tc)
    cfg.use_cache = False
    with torch.device("meta"):
        model = M.Gemma4UnifiedTextModel(cfg)

    def materialize(module):
        for name, child in list(module.named_children()):
            if isinstance(child, nn.Linear):
                w = torch.randn(child.out_features, child.in_features, dtype=torch.bfloat16, device=dev) * 0.02
                q = bnb.nn.Linear4bit(child.in_features, child.out_features, bias=False,
                                      compute_dtype=torch.bfloat16, quant_type="nf4", device="cpu")
                q.weight = bnb.nn.Params4bit(w, requires_grad=False, quant_type="nf4")
                setattr(module, name, q.to(dev))
            else:
                materialize(child)
        for pname, p in list(module.named_parameters(recurse=False)):
            if p.is_meta:
                setattr(module, pname, nn.Parameter(torch.ones(p.shape, dtype=torch.bfloat16, device=dev),
                                                    requires_grad=False))
        for bname, b in list(module.named_buffers(recurse=False)):
            if b is not None and b.is_meta:
                module.register_buffer(bname, torch.ones(b.shape, dtype=b.dtype, device=dev), persistent=False)

    for layer in model.layers:
        materialize(layer)
    materialize(model.norm)
    model.embed_tokens = nn.Embedding(1, cfg.hidden_size, device=dev, dtype=torch.bfloat16)  # bypassed
    model.rotary_emb = M.Gemma4UnifiedTextRotaryEmbedding(cfg, device=dev)
    left = [n for n, p in list(model.named_parameters()) + list(model.named_buffers()) if p.is_meta]
    assert not left, left[:5]
    return model, cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--seq", type=int, default=1024)
    ap.add_argument("--answer-frac", type=float, default=0.5)
    ap.add_argument("--embed-cpu", action="store_true")
    ap.add_argument("--vocab-sub", type=int, default=0)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--targets", default=",".join(TARGETS))
    ap.add_argument("--steps", type=int, default=4)
    a = ap.parse_args()
    import bitsandbytes as bnb
    import psutil
    from peft import LoraConfig, get_peft_model

    dev = "cuda"
    torch.manual_seed(0)
    t0 = time.time()
    model, cfg = build(a.config, dev)
    print(f"decoder NF4: {torch.cuda.memory_allocated() / 2**30:.2f} GiB ({time.time() - t0:.0f} s)", flush=True)
    V, H = cfg.vocab_size, cfg.hidden_size
    emb = (torch.randn(V, H, dtype=torch.bfloat16) * 0.02).to("cpu" if a.embed_cpu else dev)
    vs = a.vocab_sub or V
    head = emb[:vs].to(dev) if (a.embed_cpu or vs != V) else emb       # tied: the head = (a slice of) the table
    print(f"+ embedding/head: {torch.cuda.memory_allocated() / 2**30:.2f} GiB  host RSS "
          f"{psutil.Process().memory_info().rss / 2**30:.1f} GiB", flush=True)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    lc = LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.0, target_modules=a.targets.split(","))
    model = get_peft_model(model, lc)
    model.print_trainable_parameters()
    opt = bnb.optim.AdamW8bit([p for p in model.parameters() if p.requires_grad], lr=1e-4)
    torch.cuda.reset_peak_memory_stats()
    scale = H ** 0.5
    times = []
    for step in range(a.steps):
        ids = torch.randint(10, vs - 10, (1, a.seq))
        n_ans = int(a.seq * a.answer_frac)
        t = time.time()
        x = (emb[ids.to(emb.device)].to(dev).float() * scale).to(torch.bfloat16)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            h = model(inputs_embeds=x).last_hidden_state[0]
            hs = h[a.seq - n_ans - 1:-1]
            ys = ids[0, a.seq - n_ans:].to(dev)
            loss = chunked_loss(hs, ys, head, cfg.final_logit_softcapping)
        loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        torch.cuda.synchronize()
        dt_ = time.time() - t
        times.append(dt_)
        print(f"step {step} seq {a.seq} loss {loss.item():.2f} {dt_:.1f}s peak "
              f"{torch.cuda.max_memory_allocated() / 2**30:.2f} GiB reserved "
              f"{torch.cuda.max_memory_reserved() / 2**30:.2f} GiB", flush=True)
    steady = sorted(times[1:])[len(times[1:]) // 2] if len(times) > 1 else times[0]
    print(json.dumps({"seq": a.seq, "embed_cpu": a.embed_cpu, "vocab_sub": vs, "rank": a.rank,
                      "peak_alloc_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
                      "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / 2**30, 2),
                      "step_s": round(steady, 2), "tok_s": round(a.seq / steady, 1),
                      "host_rss_gib": round(psutil.Process().memory_info().rss / 2**30, 1)}), flush=True)


if __name__ == "__main__":
    main()
