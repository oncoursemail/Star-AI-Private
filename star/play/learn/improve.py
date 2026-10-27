"""Self-improvement by filtered behaviour cloning, guarded by an automatic eval gate (no owner click, #562).

Loop for one game (run at night or when the PC is idle):
  1. STAR plays with her current policy while recording (adapter.reflex_session(recorder=...)); game moments mark
     where an episode succeeded (obby checkpoint, Minecraft task done) or failed (death).
  2. `select_steps` keeps the steps of successful episodes (hers and the owner's) and mixes in a replay share of the
     human recordings, so the policy does not drift away from human-looking play while it sharpens.
  3. Fine-tune from current.pt on that set -> candidate.
  4. Evaluate candidate and incumbent on N fresh attempts each (evaluate.py). Promote only if the candidate is
     better (success rate, then mean progress on a tie). current.pt -> previous.pt (rollback), receipt appended.
Filtered BC is the "keep only the top trajectories" baseline: simple, stable, and often strong (Kumar et al. 2022
compare it with offline RL; on real robots it reached 71 % vs 74-86 % for RL, arXiv 2312.11374). It can only
sharpen what the policy already sometimes does; it cannot discover new skills the data never shows.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Callable

import numpy as np

from .dataset import Corpus
from .evaluate import Attempt, EvalResult, evaluate
from .recorder import sessions


def policy_id(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def select_steps(corpus: Corpus, *, replay_frac: float = 0.3, human: tuple[str, ...] = ("owner",),
                 rng: np.random.Generator | None = None) -> tuple[np.ndarray, int]:
    """(train indices, number of success steps): every usable step inside a successful episode, plus human steps
    (not from failed episodes) so that they make up `replay_frac` of the result."""
    gen = rng or np.random.default_rng(0)
    usable = corpus.usable()
    success = usable[corpus.episode[usable] == 1]
    who = np.array([corpus.who[s] in human for s in corpus.session[usable]], dtype=bool)
    pool = usable[who & (corpus.episode[usable] != -1)]
    pool = np.setdiff1d(pool, success)
    want = int(len(success) * replay_frac / max(1e-9, 1 - replay_frac))
    replay = gen.choice(pool, size=min(want, len(pool)), replace=False) if want and len(pool) else pool[:0]
    return np.sort(np.concatenate([success, replay])), int(len(success))


def models_dir(root: Path, game: str) -> Path:
    return Path(root) / "models" / game


def promote(candidate: Path, game: str, root: Path, receipt: dict) -> Path:
    base = models_dir(root, game)
    base.mkdir(parents=True, exist_ok=True)
    current = base / "current.pt"
    if current.exists():
        shutil.copy2(current, base / "previous.pt")
    shutil.copy2(candidate, base / "current.pt.tmp")
    (base / "current.pt.tmp").replace(current)
    with (base / "receipts.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**receipt, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
    return current


def better(cand: EvalResult, inc: EvalResult) -> bool:
    if cand.rate != inc.rate:
        return cand.rate > inc.rate
    return cand.successes > 0 and cand.mean_progress > inc.mean_progress


def improve(game: str, root: Path, attempt_for: Callable[[Path], Callable[[int], Attempt]], *, n_eval: int = 10,
            cfg=None, min_success_steps: int = 200, replay_frac: float = 0.3, life=None, log=print) -> dict:
    """One self-improvement round. `attempt_for(checkpoint)` returns an attempt runner that plays with that
    checkpoint (live: evaluate.session_attempt around adapter.reflex_session)."""
    from .policy import TrainConfig, train
    root = Path(root)
    current = models_dir(root, game) / "current.pt"
    if not current.exists():
        return {"done": False, "why": f"no current policy for {game}: train one from recorded play first"}
    dirs = sessions(root / "recordings", game)
    if not dirs:
        return {"done": False, "why": "no recordings"}
    corpus = Corpus.from_sessions(dirs)
    idx, n_success = select_steps(corpus, replay_frac=replay_frac)
    if n_success < min_success_steps:
        return {"done": False, "why": f"only {n_success} steps of successful play (need {min_success_steps})"}
    usable = corpus.usable()
    success = usable[corpus.episode[usable] == 1]
    val = success[int(len(success) * 0.85):]           # the newest successful steps grade the fine-tune
    idx = np.setdiff1d(idx, val)
    cfg = cfg or TrainConfig(steps=1000, lr=1e-4, eval_every=250)
    out = models_dir(root, game) / f"cand-{time.strftime('%Y%m%d-%H%M%S')}"
    summary = train(corpus, out, cfg, init=current, train_idx=idx, val_idx=val, log=log)
    candidate = out / "best.pt"
    inc_id, cand_id = policy_id(current), policy_id(candidate)
    inc = evaluate(game, attempt_for(current), n_eval, policy=inc_id, root=root, life=life)
    cand = evaluate(game, attempt_for(candidate), n_eval, policy=cand_id, root=root, life=life)
    report = {"done": True, "success_steps": n_success, "train_steps": int(len(idx)), "incumbent": inc.__dict__,
              "candidate": cand.__dict__, "promoted": better(cand, inc), "train": summary.get("final", {})}
    if report["promoted"]:
        promote(candidate, game, root, {"from": inc_id, "to": cand_id, "incumbent_rate": inc.rate,
                                        "candidate_rate": cand.rate, "n": n_eval, "success_steps": n_success})
    log(f"[play-learn] improve {game}: incumbent {inc.successes}/{n_eval}, candidate {cand.successes}/{n_eval}, "
        f"promoted={report['promoted']}")
    return report
