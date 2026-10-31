"""Per-game evaluation: success rate over N attempts (with a Wilson 95 % interval), kept in her history.

An attempt is whatever the game can judge mechanically: an obby run that reaches the next checkpoint before a
timeout, a Minecraft task that its checker marks done. `session_attempt` turns any GameSession factory plus success
and failure moment kinds into an attempt runner. Results go to <root>/evals/<game>.jsonl, and, when her Life
(star/home/life.py) is given, one history line per evaluation (activity "eval <game>", verified because the
counts come from the game's own signal, not from her claim).
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class Attempt:
    success: bool
    progress: float = 0.0                # game-specific (checkpoints reached, items collected); 0 when unknown
    seconds: float = 0.0
    note: str = ""


@dataclass
class EvalResult:
    game: str
    policy: str
    n: int
    successes: int
    rate: float
    lo: float
    hi: float
    mean_progress: float
    mean_seconds: float
    ts: str
    notes: list


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def evaluate(game: str, run_attempt: Callable[[int], Attempt], n: int, *, policy: str = "", root: Path | None = None,
             life=None) -> EvalResult:
    attempts = [run_attempt(i) for i in range(n)]
    k = sum(a.success for a in attempts)
    lo, hi = wilson(k, n)
    result = EvalResult(game, policy, n, k, round(k / n, 4) if n else 0.0, round(lo, 4), round(hi, 4),
                        round(sum(a.progress for a in attempts) / max(1, n), 3),
                        round(sum(a.seconds for a in attempts) / max(1, n), 2),
                        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), [a.note for a in attempts if a.note][:10])
    if root is not None:
        path = Path(root) / "evals" / f"{game}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(result)) + "\n")
    if life is not None:
        life.record("play_games", f"eval {game}",
                    {"ok": k > 0, "verified": k > 0, "steps": n,
                     "evidence": [f"{k}/{n} successes", f"policy {policy}"],
                     "summary": f"{game}: {k}/{n} attempts succeeded ({result.rate:.0%}, 95% CI "
                                f"{result.lo:.0%}-{result.hi:.0%}) with policy {policy or '?'}"})
    return result


def history(game: str, root: Path) -> list[dict]:
    path = Path(root) / "evals" / f"{game}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def session_attempt(make_session: Callable[[], Any], *, success: tuple[str, ...], failure: tuple[str, ...] = (),
                    timeout_s: float = 60.0, clock: Callable[[], float] = time.monotonic,
                    sleep: Callable[[float], None] = time.sleep) -> Callable[[int], Attempt]:
    """Attempt runner for a live game: start a fresh session, wait for the first success or failure moment (or the
    timeout), stop it (which releases every key). Progress counts success moments seen."""

    def run(i: int) -> Attempt:
        session = make_session()
        seen: list[str] = []
        session.fast.on_moment.append(lambda kind, now: seen.append(kind))
        start = clock()
        session.start()
        try:
            while clock() - start < timeout_s:
                if any(k in success for k in seen) or any(k in failure for k in seen):
                    break
                sleep(0.05)
        finally:
            session.stop()
        ok = any(k in success for k in seen) and not any(
            k in failure for k in seen[:next((j for j, k in enumerate(seen) if k in success), len(seen))])
        note = "" if ok else ("failed: " + next((k for k in seen if k in failure), "timeout"))
        return Attempt(ok, float(sum(k in success for k in seen)), round(clock() - start, 2), note)

    return run
