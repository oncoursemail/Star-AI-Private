"""Recorded sessions -> training samples: frame stacks + labels, a leak-free train/val split, idle down-sampling and
episode masks (which steps led to a success, which to a failure) for filtered behaviour cloning.

Split: whole sessions go to validation when there are two or more (frames next to each other are near copies, so a
random frame split would grade the policy on frames it has practically seen); with one session the last part of
it is held out. Idle steps (no key, no button, mouse still) are kept with probability `keep_idle` (Lumine dropped
~95 % of idle clips before training; standing still otherwise dominates the labels).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .actions import GameSpec
from .recorder import load_session


def episode_labels(meta: dict, n_steps: int, spec: GameSpec, max_steps: int) -> np.ndarray:
    """Per step: +1 inside an episode that ended in success, -1 in one that ended in failure, 0 elsewhere.
    An episode is the stretch before a success/failure marker, back to the previous marker, at most `max_steps`."""
    out = np.zeros(n_steps, dtype=np.int8)
    last = 0
    for m in sorted(meta.get("markers", []), key=lambda m: m["step"]):
        end = min(int(m["step"]), n_steps)
        kind = m["kind"]
        value = 1 if kind in spec.success else -1 if kind in spec.failure else 0
        if value:
            out[max(last, end - max_steps):end] = value
        last = end                                     # any marker (also "reset") closes the stretch before it
    return out


@dataclass
class Corpus:
    spec: GameSpec
    frames: np.ndarray                   # (N, H, W, 3) uint8 (RAM or np.memmap)
    keys: np.ndarray                     # (N, K) uint8
    buttons: np.ndarray                  # (N, B) uint8
    mouse: np.ndarray                    # (N, 2) bin indices
    delta: np.ndarray                    # (N, 2) raw pixels
    session: np.ndarray                  # (N,) session number
    run_pos: np.ndarray                  # (N,) steps since the session start or the last gap
    episode: np.ndarray                  # (N,) +1 success episode, -1 failure episode, 0 none
    who: list[str]
    names: list[str]

    @classmethod
    def from_sessions(cls, dirs: list[Path], spec: GameSpec | None = None, *, max_episode_s: float = 60.0,
                      cache: Path | None = None) -> Corpus:
        loaded = [load_session(Path(d)) for d in dirs]
        loaded = [s for s in loaded if s["meta"]["steps"] > 0 and "frames" in s]
        if not loaded:
            raise ValueError("no recorded steps in these sessions")
        spec = spec or GameSpec.from_dict(loaded[0]["meta"]["spec"])
        for s in loaded:
            other = GameSpec.from_dict(s["meta"]["spec"])
            if (other.keys, other.buttons, other.mouse_bins, other.frame_size) != (
                    spec.keys, spec.buttons, spec.mouse_bins, spec.frame_size):
                raise ValueError(f"session {s['meta']['session']} uses a different control layout")
        total = sum(len(s["t"]) for s in loaded)
        w, h = spec.frame_size
        if cache is not None:                          # hours of play: frames on disk, the OS caches what it can
            Path(cache).mkdir(parents=True, exist_ok=True)
            frames = np.lib.format.open_memmap(Path(cache) / "frames.npy", mode="w+", dtype=np.uint8,
                                               shape=(total, h, w, 3))
        else:
            frames = np.empty((total, h, w, 3), dtype=np.uint8)
        cols: dict[str, list] = {k: [] for k in ("keys", "buttons", "mouse", "delta", "session", "run_pos", "episode")}
        at = 0
        for number, s in enumerate(loaded):
            n = len(s["t"])
            frames[at:at + n] = s["frames"]
            at += n
            gap = s["gap"].astype(bool).copy()
            gap[0] = True
            pos = np.arange(n) - np.maximum.accumulate(np.where(gap, np.arange(n), 0))
            cols["keys"].append(s["keys"])
            cols["buttons"].append(s["buttons"])
            cols["mouse"].append(s["mouse"].astype(np.int64))
            cols["delta"].append(s["delta"])
            cols["session"].append(np.full(n, number))
            cols["run_pos"].append(pos)
            cols["episode"].append(episode_labels(s["meta"], n, spec, int(max_episode_s * spec.hz)))
        if isinstance(frames, np.memmap):
            frames.flush()
        cat = {k: np.concatenate(v) for k, v in cols.items()}
        return cls(spec, frames, cat["keys"], cat["buttons"], cat["mouse"], cat["delta"], cat["session"],
                   cat["run_pos"], cat["episode"], [s["meta"]["who"] for s in loaded],
                   [s["meta"]["session"] for s in loaded])

    def __len__(self) -> int:
        return len(self.keys)

    @property
    def idle(self) -> np.ndarray:
        still = self.spec.still_bin
        return ((self.keys.sum(1) == 0) & (self.buttons.sum(1) == 0) & (self.mouse[:, 0] == still)
                & (self.mouse[:, 1] == still))

    def usable(self) -> np.ndarray:
        """Indices with a full frame stack behind them (no gap, same session)."""
        return np.nonzero(self.run_pos >= self.spec.stack - 1)[0]

    def split(self, val_frac: float = 0.15) -> tuple[np.ndarray, np.ndarray]:
        idx = self.usable()
        n_sessions = int(self.session.max()) + 1
        if n_sessions >= 2:
            val_sessions: list[int] = []
            for number in range(n_sessions - 1, 0, -1):          # newest sessions first, always keep session 0
                val_sessions.append(number)
                if np.isin(self.session, val_sessions).sum() >= val_frac * len(self):
                    break
            in_val = np.isin(self.session[idx], val_sessions)
            return idx[~in_val], idx[in_val]
        cut = int(len(self) * (1 - val_frac))
        return idx[idx < cut], idx[idx >= cut + self.spec.stack]   # margin: no stack straddles the cut

    def thin_idle(self, idx: np.ndarray, keep_idle: float, rng: np.random.Generator) -> np.ndarray:
        idle = self.idle[idx]
        keep = ~idle | (rng.random(len(idx)) < keep_idle)
        return idx[keep]

    def stack(self, idx: np.ndarray) -> np.ndarray:
        """(B, stack*3, H, W) uint8, oldest frame first."""
        k = self.spec.stack
        parts = [self.frames[idx - (k - 1 - j)] for j in range(k)]            # each (B, H, W, 3)
        x = np.concatenate(parts, axis=3)                                    # (B, H, W, 3k)
        return np.ascontiguousarray(x.transpose(0, 3, 1, 2))

    def labels(self, idx: np.ndarray) -> dict[str, np.ndarray]:
        return {"keys": self.keys[idx].astype(np.float32), "buttons": self.buttons[idx].astype(np.float32),
                "mx": self.mouse[idx, 0], "my": self.mouse[idx, 1]}
