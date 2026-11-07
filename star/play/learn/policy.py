"""A small pixels -> keys/mouse policy for ONE game, trained by behaviour cloning (needs PyTorch).

Model: IMPALA-style CNN (the encoder used for Procgen/Atari agents) on a stack of the last `spec.stack` frames at
128x72, a 256-unit layer, and four heads: one sigmoid per game key, one per mouse button, and a softmax over the
mouse-x and mouse-y bins (as in VPT and the CS:GO behavioural cloning agent). Default widths (16, 32, 32) give
about 1.3 M parameters: it trains on an 8 GB card next to a game and runs in a few ms per frame.
Training: AdamW + cosine decay, mixed precision (fp16 autocast + GradScaler) on CUDA, random-shift augmentation
(DrQ/RAD: the geometric augmentation that helps image-based control most) plus brightness/contrast jitter (the
only augmentation the CS:GO agent used; flips would break the left/right labels). Checkpoints keep the spec, the
model shape, the data stats (mouse speed cap) and the validation metrics, so a checkpoint is self-describing.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from .actions import GameSpec
from .dataset import Corpus


class _Residual(nn.Module):
    def __init__(self, ch: int) -> None:
        super().__init__()
        self.c1, self.c2 = nn.Conv2d(ch, ch, 3, padding=1), nn.Conv2d(ch, ch, 3, padding=1)

    def forward(self, x):
        return x + self.c2(F.relu(self.c1(F.relu(x))))


class _Stack(nn.Module):
    def __init__(self, cin: int, cout: int) -> None:
        super().__init__()
        self.conv, self.r1, self.r2 = nn.Conv2d(cin, cout, 3, padding=1), _Residual(cout), _Residual(cout)

    def forward(self, x):
        return self.r2(self.r1(F.max_pool2d(self.conv(x), 3, stride=2, padding=1)))


class PolicyNet(nn.Module):
    def __init__(self, stack: int, size: tuple[int, int], n_keys: int, n_buttons: int, bins: int,
                 widths: tuple[int, ...] = (16, 32, 32), hidden: int = 256) -> None:
        super().__init__()
        self.arch = {"stack": stack, "size": list(size), "n_keys": n_keys, "n_buttons": n_buttons, "bins": bins,
                     "widths": list(widths), "hidden": hidden}
        layers, cin = [], 3 * stack
        for cout in widths:
            layers.append(_Stack(cin, cout))
            cin = cout
        self.trunk = nn.Sequential(*layers)
        w, h = size
        with torch.no_grad():
            flat = self.trunk(torch.zeros(1, 3 * stack, h, w)).numel()
        self.fc = nn.Linear(flat, hidden)
        self.keys, self.buttons = nn.Linear(hidden, n_keys), nn.Linear(hidden, max(1, n_buttons))
        self.mx, self.my = nn.Linear(hidden, bins), nn.Linear(hidden, bins)
        self.n_buttons = n_buttons

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        """x: (B, 3*stack, H, W) uint8 or float in 0..255."""
        z = F.relu(self.trunk(x.to(self.fc.weight.dtype) / 255.0)).flatten(1)
        z = F.relu(self.fc(z))
        out = {"keys": self.keys(z), "mx": self.mx(z), "my": self.my(z)}
        out["buttons"] = self.buttons(z)[:, :self.n_buttons]
        return out


def build(spec: GameSpec, widths: tuple[int, ...] = (16, 32, 32), hidden: int = 256) -> PolicyNet:
    return PolicyNet(spec.stack, spec.frame_size, len(spec.keys), len(spec.buttons), spec.mouse_bins, widths, hidden)


def augment(x: torch.Tensor, shift_px: int = 4, jitter: float = 0.15) -> torch.Tensor:
    """Per sample: a random translation of up to `shift_px` (edge pixels repeat) and brightness/contrast jitter."""
    b, _, h, w = x.shape
    x = x.float()
    if shift_px:
        t = (torch.rand(b, 2, device=x.device) * 2 - 1) * shift_px
        theta = torch.zeros(b, 2, 3, device=x.device)
        theta[:, 0, 0] = theta[:, 1, 1] = 1.0
        theta[:, 0, 2], theta[:, 1, 2] = t[:, 0] * 2 / w, t[:, 1] * 2 / h
        grid = F.affine_grid(theta, list(x.shape), align_corners=False)
        x = F.grid_sample(x, grid, mode="nearest", padding_mode="border", align_corners=False)
    if jitter:
        contrast = 1 + (torch.rand(b, 1, 1, 1, device=x.device) * 2 - 1) * jitter
        bright = (torch.rand(b, 1, 1, 1, device=x.device) * 2 - 1) * jitter * 255
        mean = x.mean(dim=(1, 2, 3), keepdim=True)
        x = ((x - mean) * contrast + mean + bright).clamp(0, 255)
    return x


def loss_fn(out: dict, y: dict) -> torch.Tensor:
    loss = F.binary_cross_entropy_with_logits(out["keys"].float(), y["keys"])
    if y["buttons"].shape[1]:
        loss = loss + F.binary_cross_entropy_with_logits(out["buttons"].float(), y["buttons"])
    return loss + 0.5 * (F.cross_entropy(out["mx"].float(), y["mx"]) + F.cross_entropy(out["my"].float(), y["my"]))


@dataclass
class TrainConfig:
    steps: int = 3000
    batch: int = 64
    lr: float = 3e-4
    weight_decay: float = 1e-4
    keep_idle: float = 0.2
    val_frac: float = 0.15
    eval_every: int = 250
    val_batches: int = 20
    widths: tuple[int, ...] = (16, 32, 32)
    hidden: int = 256
    shift_px: int = 4
    jitter: float = 0.15
    device: str = "auto"
    amp: bool = True
    seed: int = 0
    cpu_threads: int = 2                       # keep the PC light when training falls back to the CPU
    extra: dict = field(default_factory=dict)


def pick_device(name: str = "auto") -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def _to(device, x: np.ndarray, labels: dict) -> tuple[torch.Tensor, dict]:
    xt = torch.from_numpy(x).to(device, non_blocking=True)
    y = {"keys": torch.from_numpy(labels["keys"]).to(device), "buttons": torch.from_numpy(labels["buttons"]).to(device),
         "mx": torch.from_numpy(labels["mx"]).to(device), "my": torch.from_numpy(labels["my"]).to(device)}
    return xt, y


@torch.no_grad()
def evaluate(model: PolicyNet, corpus: Corpus, idx: np.ndarray, device, *, batch: int = 128,
             max_batches: int = 20) -> dict:
    """Validation metrics: loss, key accuracy, F1 of pressed keys, mouse bin accuracy and within-one-bin rate."""
    model.eval()
    if len(idx) == 0:
        return {}
    picks = idx[np.linspace(0, len(idx) - 1, min(len(idx), batch * max_batches)).astype(np.int64)]
    total, n, tp, fp, fn, correct_keys, keys_seen, m_exact, m_near = 0.0, 0, 0, 0, 0, 0, 0, 0, 0
    for start in range(0, len(picks), batch):
        part = picks[start:start + batch]
        x, y = _to(device, corpus.stack(part), corpus.labels(part))
        out = model(x)
        total += float(loss_fn(out, y)) * len(part)
        n += len(part)
        pred = out["keys"] > 0
        true = y["keys"] > 0.5
        tp += int((pred & true).sum())
        fp += int((pred & ~true).sum())
        fn += int((~pred & true).sum())
        correct_keys += int((pred == true).sum())
        keys_seen += true.numel()
        for head in ("mx", "my"):
            guess = out[head].argmax(1)
            m_exact += int((guess == y[head]).sum())
            m_near += int(((guess - y[head]).abs() <= 1).sum())
    model.train()
    f1 = 2 * tp / max(1, 2 * tp + fp + fn)
    return {"loss": round(total / n, 4), "key_acc": round(correct_keys / max(1, keys_seen), 4),
            "key_f1": round(f1, 4), "mouse_acc": round(m_exact / (2 * n), 4),
            "mouse_within1": round(m_near / (2 * n), 4), "n": n}


def train(corpus: Corpus, out_dir: Path, cfg: TrainConfig | None = None, *, init: Path | None = None,
          train_idx: np.ndarray | None = None, val_idx: np.ndarray | None = None, log=print) -> dict:
    """Behaviour cloning on `corpus` (or on `train_idx` of it: filtered BC passes the chosen steps). Writes
    best.pt (lowest validation loss), last.pt and metrics.jsonl to out_dir; returns the summary."""
    cfg = cfg or TrainConfig()
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    device = pick_device(cfg.device)
    if device.type == "cpu":
        torch.set_num_threads(max(1, cfg.cpu_threads))
    use_amp = cfg.amp and device.type == "cuda"
    if train_idx is None or val_idx is None:
        tr, va = corpus.split(cfg.val_frac)
        train_idx = tr if train_idx is None else train_idx
        val_idx = va if val_idx is None else val_idx
        train_idx = corpus.thin_idle(train_idx, cfg.keep_idle, rng)
    assert train_idx is not None and val_idx is not None      # both were filled in above
    if len(train_idx) == 0:
        raise ValueError("no training samples (record more play)")
    spec = corpus.spec
    if init is not None:
        model, ckpt = load_policy(init, device)
        model.train()
    else:
        model = build(spec, tuple(cfg.widths), cfg.hidden).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: 0.5 * (1 + math.cos(math.pi * min(1.0, s / cfg.steps))))
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    abs_dx = np.abs(corpus.delta[train_idx]).ravel()
    stats = {"abs_delta_p99": float(np.percentile(abs_dx, 99)) if len(abs_dx) else 0.0,
             "train_samples": int(len(train_idx)), "val_samples": int(len(val_idx)), "sessions": corpus.names,
             "who": sorted(set(corpus.who))}
    best, history, started = math.inf, [], time.perf_counter()
    params = sum(p.numel() for p in model.parameters())
    log(f"[play-learn] {spec.game}: {params / 1e6:.2f} M params, {len(train_idx)} train / {len(val_idx)} val "
        f"samples, device={device}, amp={use_amp}")
    model.train()
    for step in range(1, cfg.steps + 1):
        part = train_idx[rng.integers(0, len(train_idx), cfg.batch)]
        x, y = _to(device, corpus.stack(part), corpus.labels(part))
        x = augment(x, cfg.shift_px, cfg.jitter)
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
            loss = loss_fn(model(x), y)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.unscale_(opt)
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(opt)
        scaler.update()
        sched.step()
        if step % cfg.eval_every == 0 or step == cfg.steps:
            metrics = evaluate(model, corpus, val_idx, device, max_batches=cfg.val_batches)
            row = {"step": step, "train_loss": round(loss.item(), 4), "s": round(time.perf_counter() - started, 1),
                   **{f"val_{k}": v for k, v in metrics.items()}}
            history.append(row)
            with (out_dir / "metrics.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            log(f"[play-learn] {json.dumps(row)}")
            val_loss = metrics.get("loss", loss.item())
            if val_loss < best:
                best = val_loss
                save(model, spec, stats, row, out_dir / "best.pt", cfg)
    save(model, spec, stats, history[-1] if history else {}, out_dir / "last.pt", cfg)
    summary = {"game": spec.game, "params": params, "device": str(device), "amp": use_amp, "steps": cfg.steps,
               "seconds": round(time.perf_counter() - started, 1), "best_val_loss": best,
               "final": history[-1] if history else {}, "out": str(out_dir), **stats}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def save(model: PolicyNet, spec: GameSpec, stats: dict, metrics: dict, path: Path, cfg: TrainConfig) -> None:
    tmp = Path(path).with_suffix(".tmp")
    cfg_dict = asdict(cfg)
    torch.save({"model": model.state_dict(), "arch": model.arch, "spec": spec.to_dict(), "stats": stats,
                "metrics": metrics, "config": cfg_dict, "format": 1}, tmp)
    tmp.replace(path)


def load_policy(path: Path, device=None) -> tuple[PolicyNet, dict]:
    ckpt = torch.load(Path(path), map_location="cpu", weights_only=True)
    a = ckpt["arch"]
    model = PolicyNet(a["stack"], tuple(a["size"]), a["n_keys"], a["n_buttons"], a["bins"], tuple(a["widths"]),
                      a["hidden"])
    model.load_state_dict(ckpt["model"])
    model.to(device or pick_device())
    model.eval()
    return model, ckpt
