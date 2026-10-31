"""Opt-in verified duel (STAR 2.0 Conductor, #414 slice 1): one task, two agents, STAR's own checks pick the winner.

Off by default. Each writer is a small async callable ``prompt -> answer text`` (a local model, a cloud client or, later,
an agent adapter from the fleet work); the duel never gives a writer tools, files or secrets. STAR's host-side checkers
(``best_of_n`` Luau/Python checkers) judge both answers, the better one that passes is the verified winner, and a
hash-only learning event is appended to a private outbox for the normal review gate. Nothing is activated here.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Awaitable, Callable, Mapping

from .atomic_io import atomic_write_text
from .best_of_n import Candidate, main_block, rank_key, strip_forged
from .conductor_evidence import CheckEvidence, TaskEvidence, assess_learning_readiness

Writer = Callable[[str], Awaitable[str]]
VERIFIER_ID = "star-host-checks"
OUTBOX = ("conductor", "learning_events.jsonl")
_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


@dataclass(frozen=True)
class DuelResult:
    winner: str | None
    verified: bool
    reason: str
    candidates: tuple[Candidate, ...]
    event: dict | None = None


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _evidence_checks(cand: Candidate, project: str, source_sha: str, art: str, report: str) -> tuple[CheckEvidence, ...]:
    hard = [c for c in cand.checks if c.hard and c.ran and c.name != "code block"]  # a block existing is not a verdict
    if not hard:
        return ()
    status = "passed" if all(c.status == "pass" for c in hard) else "failed"
    return (CheckEvidence("typecheck", status, "host_tool", VERIFIER_ID, project, source_sha, art, report),)


async def _write(writer: Writer, prompt: str, cand: Candidate, timeout: float) -> None:
    began = time.monotonic()
    try:
        text = await asyncio.wait_for(writer(prompt), timeout)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty answer")
        cand.answer = strip_forged(text)
    except Exception as exc:
        cand.error = (type(exc).__name__ + (": " + str(exc) if str(exc) else ""))[:120]
    cand.seconds = time.monotonic() - began


async def run_duel(
    prompt: str, writers: Mapping[str, Writer], checker, *,
    enabled: bool = False, project_id: str, source_sha: str, home: Path, mission_id: str = "duel",
    timeout: float = 120.0,
) -> DuelResult:
    """Run exactly two writers in parallel, check both, record the verified winner (if any) as a learning event."""
    if enabled is not True:
        raise PermissionError("Conductor duel is off until explicitly enabled")
    if len(writers) != 2 or not all(_ID.fullmatch(k) for k in writers):
        raise ValueError("A duel needs exactly two writers with simple ids")
    ids = list(writers)
    cands = [Candidate(i + 1, wid) for i, wid in enumerate(ids)]
    await asyncio.gather(*(_write(writers[w], prompt, c, timeout) for w, c in zip(ids, cands)))
    codes = {}
    for c in cands:
        if c.ok:
            codes[c.model] = main_block(c.answer, checker.kind)
            c.checks = list(checker.static(codes[c.model], c.answer))
    ranked = sorted(cands, key=rank_key)
    best = ranked[0]
    if not best.ok or best.hard_failures:
        return DuelResult(None, False, "No answer passed STAR's checks", tuple(cands))
    if len(ranked) > 1 and rank_key(ranked[0])[:-1] == rank_key(ranked[1])[:-1] and ranked[1].ok:
        note = "tie on every check; first writer kept"
    else:
        note = "best by STAR's checks"
    art = _sha(codes[best.model])
    report = _sha(json.dumps(best.summary()["checks"], sort_keys=True))
    task = TaskEvidence(mission_id, project_id, "duel-1", best.model, best.model, "local", "unreported", "completed",
                        source_sha, art, _evidence_checks(best, project_id, source_sha, art, report))
    ready = assess_learning_readiness(task, expected_project=project_id, required_checks=("typecheck",))
    if not ready.eligible_for_review:
        return DuelResult(best.model, False, ready.reason, tuple(cands))
    event = {"kind": "conductor_verified_duel", "status": "pending_owner_review", "at": int(time.time()),
             "mission_id": mission_id, "project_id": project_id, "source_sha": source_sha,
             "winner": best.model, "loser": next(c.model for c in cands if c is not best),
             "prompt_sha256": _sha(prompt), "artifact_sha256": art, "report_sha256": report,
             "checks": list(ready.verified_checks), "note": note}
    path = Path(home).joinpath(*OUTBOX)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write_text(path, old + json.dumps(event, sort_keys=True) + "\n")
    return DuelResult(best.model, True, note, tuple(cands), event)
