"""python -m star.play.learn <command>

  record    record the owner's (or a friend's) play of one game: game window only, game keys only, consent note
            required, "[STAR rec]" lines while it runs;  --game roblox_obby --who owner --consent "..." [--seconds N]
  train     behaviour cloning on every recording of a game -> models/<game>/base-<time>/ (current.pt if none yet)
  synth     synthetic end-to-end run (fake DotGame only, never the real screen): record noisy demos, train, evaluate,
            let STAR play and record herself, one filtered-BC improvement round; prints JSON
  bench     policy inference latency (p50/p95 ms) on this machine's GPU or CPU
  heavy-ok  exit 0 when heavy work is allowed now: owner idle >= 5 min (same rule as tools/pc_guard.py) or
            05:00-13:00 UTC
"""
from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import sys
import time
from pathlib import Path


def owner_idle_seconds() -> float | None:
    if sys.platform != "win32":
        return None

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def heavy_ok(now: datetime.datetime | None = None, idle: float | None = None) -> tuple[bool, str]:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if 5 <= now.hour < 13:
        return True, f"{now:%H:%M}Z is inside 05:00-13:00Z"
    if idle is not None and idle >= 300:
        return True, f"owner idle {idle:.0f} s"
    return False, f"owner active (idle {idle if idle is not None else '?'} s) at {now:%H:%M}Z"


def _root(arg: str | None) -> Path:
    from .recorder import data_root
    return Path(arg) if arg else data_root()


def cmd_record(a) -> int:  # pragma: no cover - real screen and devices
    from ..capture import open_capture, window_rect
    from ..winput import window_guard
    from .actions import spec_for
    from .recorder import RawInputSource, Recorder
    spec = spec_for(a.game)
    rect = window_rect(spec.window) if spec.window else None
    if spec.window and rect is None:
        print(f"no visible window with '{spec.window}' in its title", file=sys.stderr)
        return 2
    source = open_capture(rect)
    rec = Recorder(spec, consent=a.consent, who=a.who, root=_root(a.root) / "recordings", source=source,
                   guard=window_guard(spec.window) if spec.window else None)
    raw = RawInputSource(rec.state)
    raw.start()
    rec.start()
    try:
        rec.run(a.seconds)
    except KeyboardInterrupt:
        pass
    finally:
        raw.stop()
        print(json.dumps({"dir": str(rec.stop()), "steps": rec.steps, "paused": rec.paused}))
        source.close()
    return 0


def cmd_train(a) -> int:
    from .dataset import Corpus
    from .improve import models_dir, promote
    from .policy import TrainConfig, train
    from .recorder import sessions
    root = _root(a.root)
    dirs = sessions(root / "recordings", a.game)
    if not dirs:
        print(f"no recordings for {a.game} under {root / 'recordings'}", file=sys.stderr)
        return 2
    corpus = Corpus.from_sessions(dirs, cache=root / "cache" / a.game if a.cache else None)
    out = models_dir(root, a.game) / f"base-{time.strftime('%Y%m%d-%H%M%S')}"
    summary = train(corpus, out, TrainConfig(steps=a.steps, batch=a.batch, device=a.device))
    if a.promote or not (models_dir(root, a.game) / "current.pt").exists():
        promote(out / "best.pt", a.game, root, {"from": "", "to": str(out), "why": "base training"})
        summary["promoted"] = True
    print(json.dumps(summary, indent=1))
    return 0


def cmd_synth(a) -> int:
    import numpy as np
    import torch
    from .adapter import PolicyController
    from .evaluate import evaluate
    from .improve import improve, models_dir, promote
    from .policy import TrainConfig, load_policy, train
    from .dataset import Corpus
    from .recorder import Recorder, sessions
    from .synthetic import dot_spec, play, policy_act, record_demos
    root = Path(a.out)
    w, h = (int(v) for v in a.frame.split("x"))
    spec = dot_spec((w, h))
    rec_root = root / "recordings"
    started = time.perf_counter()
    record_demos(rec_root, spec, a.episodes, eps=a.eps, who="owner", seed=1)
    t_rec = time.perf_counter() - started
    cfg = TrainConfig(steps=a.steps, batch=a.batch, device=a.device, eval_every=max(50, a.steps // 6))
    base = train(Corpus.from_sessions(sessions(rec_root, spec.game)), models_dir(root, spec.game) / "base", cfg)
    promote(models_dir(root, spec.game) / "base" / "best.pt", spec.game, root, {"why": "base"})

    def attempt_for(ckpt):
        model, info = load_policy(ckpt)
        controller = PolicyController(model, info, temperature=a.temperature, rng=__import__("random").Random(7))
        act = policy_act(controller)
        return lambda i: play(spec, 1, act, seed=50_000 + i)[0]

    def human(i):
        from .synthetic import ScriptedPlayer
        import random
        rng = random.Random(i)
        players = {}
        return play(spec, 1, lambda g, s: players.setdefault(id(g), ScriptedPlayer(g, rng, a.eps)).act(),
                    seed=50_000 + i)[0]

    demo = evaluate(spec.game, human, a.eval_n, policy="scripted-demonstrator", root=root)
    current = models_dir(root, spec.game) / "current.pt"
    rec = Recorder(spec, consent="synthetic", who="star", root=rec_root, notify=lambda s: None,
                   session_id="star-selfplay").start()
    model, info = load_policy(current)
    play(spec, a.self_episodes, policy_act(PolicyController(model, info, temperature=a.temperature)), seed=777,
         recorder=rec)
    rec.stop()
    report = improve(spec.game, root, attempt_for, n_eval=a.eval_n,
                     cfg=TrainConfig(steps=max(100, a.steps // 3), batch=a.batch, lr=1e-4, device=a.device,
                                     eval_every=max(50, a.steps // 6)), min_success_steps=50)
    model, info = load_policy(current)
    lat = _latency(model, spec, n=300)
    print(json.dumps({"frame": a.frame, "episodes": a.episodes, "record_s": round(t_rec, 1),
                      "train": {k: base[k] for k in ("params", "device", "amp", "seconds", "final", "train_samples")},
                      "demonstrator": demo.__dict__, "improve": report, "latency_ms": lat,
                      "cuda": torch.cuda.is_available(), "np": np.__version__}, indent=1, default=str))
    return 0


def _latency(model, spec, n: int = 300) -> dict:
    import numpy as np
    import torch
    from .adapter import PolicyController
    controller = PolicyController(model, {"spec": spec.to_dict(), "stats": {}})
    w, h = spec.frame_size
    stack = np.random.default_rng(0).integers(0, 255, (3 * spec.stack, h, w), dtype=np.uint8)
    for _ in range(20):
        controller.probabilities(stack)
    controller.infer_ms.clear()
    for _ in range(n):
        controller.probabilities(stack)
    ms = sorted(controller.infer_ms)
    return {"device": str(controller.device), "fp16": controller.half, "p50": round(ms[len(ms) // 2], 3),
            "p95": round(ms[int(len(ms) * 0.95)], 3), "n": n,
            "vram_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1) if torch.cuda.is_available() else 0}


def cmd_bench(a) -> int:
    from .actions import GameSpec
    from .policy import build, load_policy, pick_device
    if a.checkpoint:
        model, ckpt = load_policy(Path(a.checkpoint), pick_device(a.device))
        spec = GameSpec.from_dict(ckpt["spec"])
    else:
        from .actions import spec_for
        spec = spec_for(a.game)
        model = build(spec).to(pick_device(a.device)).eval()
    print(json.dumps({"game": spec.game, "frame": spec.frame_size, "stack": spec.stack,
                      "params": sum(p.numel() for p in model.parameters()), **_latency(model, spec, a.n)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m star.play.learn", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--game", required=True)
    r.add_argument("--who", default="owner")
    r.add_argument("--consent", required=True, help="who agreed to be recorded, e.g. 'owner, 2026-10-27, in chat'")
    r.add_argument("--seconds", type=float)
    r.add_argument("--root")
    t = sub.add_parser("train")
    t.add_argument("--game", required=True)
    t.add_argument("--steps", type=int, default=3000)
    t.add_argument("--batch", type=int, default=64)
    t.add_argument("--device", default="auto")
    t.add_argument("--cache", action="store_true", help="frames in a memory-mapped file (hours of play)")
    t.add_argument("--promote", action="store_true")
    t.add_argument("--root")
    s = sub.add_parser("synth")
    s.add_argument("--out", required=True)
    s.add_argument("--frame", default="128x72")
    s.add_argument("--episodes", type=int, default=400)
    s.add_argument("--self-episodes", type=int, default=300)
    s.add_argument("--eps", type=float, default=0.5)
    s.add_argument("--steps", type=int, default=2000)
    s.add_argument("--batch", type=int, default=64)
    s.add_argument("--eval-n", type=int, default=100)
    s.add_argument("--temperature", type=float, default=1.0)
    s.add_argument("--device", default="auto")
    b = sub.add_parser("bench")
    b.add_argument("--checkpoint")
    b.add_argument("--game", default="roblox_obby")
    b.add_argument("--device", default="auto")
    b.add_argument("--n", type=int, default=500)
    sub.add_parser("heavy-ok")
    a = p.parse_args(argv)
    if a.cmd == "heavy-ok":
        ok, why = heavy_ok(idle=owner_idle_seconds())
        print(why)
        return 0 if ok else 1
    return {"record": cmd_record, "train": cmd_train, "synth": cmd_synth, "bench": cmd_bench}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
