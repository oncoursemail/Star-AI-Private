"""Evidence-bounded, offline practice portfolio for STAR.

Selects *proposals* for rehearsals across gameplay, game creation, streaming,
knowledge and inference. It never launches a model, runs a game, trains weights,
or elevates permissions. Caller MUST authenticate host approvals and receipts:
a boolean or an ID in an untrusted JSON file is not proof of authorization.
Holdout observations are deliberately excluded from planning.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import sys

DOMAINS = frozenset({"gameplay", "game_creation", "streaming", "knowledge", "inference"})
SPLITS = frozenset({"practice", "holdout"})
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
MAX_TASKS = 256
MAX_RECEIPTS = 8192
MAX_INPUT_BYTES = 512_000


def _id(value: object, label: str) -> None:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded identifier")


def _int(value: object, label: str, lo: int, hi: int) -> None:
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{label} must be an integer from {lo} to {hi}")


@dataclass(frozen=True)
class PracticeTask:
    task_id: str
    domain: str
    scenario_id: str
    estimated_seconds: int
    gpu_mb: int = 0
    host_approved: bool = False
    network_required: bool = False

    def __post_init__(self) -> None:
        _id(self.task_id, "task_id")
        _id(self.scenario_id, "scenario_id")
        if type(self.domain) is not str or self.domain not in DOMAINS:
            raise ValueError("Unknown practice domain")
        _int(self.estimated_seconds, "estimated_seconds", 1, 3600)
        _int(self.gpu_mb, "gpu_mb", 0, 131_072)
        if type(self.host_approved) is not bool or type(self.network_required) is not bool:
            raise ValueError("Approval and network flags must be booleans")


@dataclass(frozen=True)
class PracticeReceipt:
    receipt_id: str
    task_id: str
    environment_id: str
    sequence: int
    score: float
    split: str = "practice"

    def __post_init__(self) -> None:
        for key in ("receipt_id", "task_id", "environment_id"):
            _id(getattr(self, key), key)
        _int(self.sequence, "sequence", 0, 2_147_483_647)
        if type(self.split) is not str or self.split not in SPLITS:
            raise ValueError("Unknown receipt split")
        if type(self.score) not in (float, int) or not 0 <= self.score <= 1 or not math.isfinite(float(self.score)):
            raise ValueError("score must be finite and between zero and one")


@dataclass(frozen=True)
class PracticeBudget:
    max_seconds: int = 600
    max_tasks: int = 4
    gpu_headroom_mb: int = 0
    live_streaming: bool = False
    network_allowed: bool = False

    def __post_init__(self) -> None:
        _int(self.max_seconds, "max_seconds", 1, 14_400)
        _int(self.max_tasks, "max_tasks", 1, 32)
        _int(self.gpu_headroom_mb, "gpu_headroom_mb", 0, 131_072)
        if type(self.live_streaming) is not bool or type(self.network_allowed) is not bool:
            raise ValueError("Streaming and network flags must be booleans")


def _practice_by_task(
    tasks: tuple[PracticeTask, ...], receipts: tuple[PracticeReceipt, ...]
) -> tuple[dict[str, list[PracticeReceipt]], int]:
    ids = {task.task_id for task in tasks}
    if len(receipts) > MAX_RECEIPTS:
        raise ValueError("Too many receipts")
    receipt_ids: set[str] = set()
    independent: set[tuple[str, str, str]] = set()
    by_task: dict[str, list[PracticeReceipt]] = {task.task_id: [] for task in tasks}
    holdouts = 0
    # Explicit chronology and deterministic tie-breaking protect against caller order.
    for r in sorted(receipts, key=lambda x: (x.sequence, x.receipt_id)):
        if r.task_id not in ids:
            raise ValueError("Receipt references an unknown task")
        if r.receipt_id in receipt_ids:
            raise ValueError("Duplicate receipt ID")
        receipt_ids.add(r.receipt_id)
        if r.split == "holdout":
            holdouts += 1
            continue
        key = (r.task_id, r.split, r.environment_id)
        if key in independent:
            continue  # Re-running one known seed never masquerades as independent trials.
        independent.add(key)
        by_task[r.task_id].append(r)
    return by_task, holdouts


def _value(task: PracticeTask, evidence: list[PracticeReceipt], domain_trials: int) -> float:
    scores = [float(x.score) for x in evidence]
    n = len(scores)
    mean = sum(scores) / n if n else 0.5
    challenge = 1 - abs(2 * mean - 1)
    uncertainty = 1 / math.sqrt(n + 1)
    novelty = 1 / math.sqrt(domain_trials + 1)
    # First and last two *independent* environments, never holdout runs.
    learning_progress = max(0.0, (sum(scores[-2:]) - sum(scores[:2])) / 2) if n >= 4 else 0.0
    # Repeated zero scores probably indicate a task too hard for productive practice.
    stalled = 0.14 if n >= 4 and max(scores) == 0 else 0.0
    potential = max(0, 0.46 * challenge + 0.24 * uncertainty +
                    0.18 * learning_progress + 0.12 * novelty - stalled)
    # Cost-aware without starving long/hard tasks; estimates are not observed runtime.
    cost = max(0.55, min(1.5, (90 / task.estimated_seconds) ** 0.35))
    return round(potential * cost, 6)


def propose_practice(
    tasks: tuple[PracticeTask, ...],
    receipts: tuple[PracticeReceipt, ...] = (),
    budget: PracticeBudget = PracticeBudget(),
) -> dict:
    """Return deterministic planning advice; *never* grants authority to execute."""
    if len(tasks) > MAX_TASKS:
        raise ValueError("Too many tasks")
    if any(not isinstance(t, PracticeTask) for t in tasks):
        raise ValueError("Tasks must be typed PracticeTask objects")
    if any(not isinstance(r, PracticeReceipt) for r in receipts):
        raise ValueError("Receipts must be typed PracticeReceipt objects")
    if not isinstance(budget, PracticeBudget):
        raise ValueError("Invalid practice budget")
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("Duplicate task ID")
    history, holdout_count = _practice_by_task(tasks, receipts)
    domain_count: dict[str, int] = {name: 0 for name in DOMAINS}
    for task in tasks:
        domain_count[task.domain] += len(history[task.task_id])
    candidates: list[tuple[PracticeTask, float]] = []
    blocked: list[dict] = []
    for task in sorted(tasks, key=lambda t: t.task_id):
        reason = None
        if budget.live_streaming:
            reason = "live_streaming_offline_practice_paused"
        elif not task.host_approved:
            reason = "host_approval_missing"
        elif task.network_required and not budget.network_allowed:
            reason = "network_not_allowed"
        elif task.gpu_mb > budget.gpu_headroom_mb:
            reason = "gpu_headroom_exceeded"
        elif task.estimated_seconds > budget.max_seconds:
            reason = "duration_exceeds_budget"
        if reason:
            blocked.append({"task_id": task.task_id, "reason": reason})
        else:
            candidates.append((task, _value(task, history[task.task_id], domain_count[task.domain])))

    selected: list[dict] = []
    used_scenarios: set[str] = set()
    spent = 0
    chosen_domains: dict[str, int] = {}
    remaining = list(candidates)
    while remaining and len(selected) < budget.max_tasks:
        fitting = [(task, value) for task, value in remaining
                   if task.scenario_id not in used_scenarios
                   and spent + task.estimated_seconds <= budget.max_seconds]
        if not fitting:
            break
        # A small diversity preference protects knowledge, speech, and game-building
        # rehearsal from being drowned out by a single easy domain.
        task, value = min(
            fitting,
            key=lambda pair: (
                -(pair[1] + (0.17 if pair[0].domain not in chosen_domains else 0)
                  - 0.09 * chosen_domains.get(pair[0].domain, 0)),
                pair[0].task_id,
            ),
        )
        selected.append({
            "task_id": task.task_id, "domain": task.domain,
            "scenario_id": task.scenario_id, "estimated_seconds": task.estimated_seconds,
            "gpu_mb": task.gpu_mb, "priority": value,
            "independent_practice_receipts": len(history[task.task_id]),
        })
        spent += task.estimated_seconds
        used_scenarios.add(task.scenario_id)
        chosen_domains[task.domain] = chosen_domains.get(task.domain, 0) + 1
        remaining = [(candidate, rank) for candidate, rank in remaining
                     if candidate.task_id != task.task_id]
    return {
        "schema_version": 1, "kind": "practice_proposal_only",
        "selected": selected, "blocked": blocked,
        "deferred_task_ids": sorted(t.task_id for t, _ in remaining),
        "budget_seconds": budget.max_seconds, "estimated_seconds": spent,
        "holdout_receipts_excluded": holdout_count,
        "executable": False, "model_trained": False,
        "notice": "Host must authorize and independently execute and evaluate each proposal.",
    }


def plan_from_json(raw: bytes) -> dict:
    """CLI convenience only; JSON approvals/receipts are NOT authenticated."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_INPUT_BYTES:
        raise ValueError("Input must be bounded UTF-8 JSON")
    def unique(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def bad_constant(value: str) -> None:
        raise ValueError("Non-finite JSON constant")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=bad_constant)
        if type(data) is not dict or set(data) != {"tasks", "receipts", "budget"}:
            raise ValueError("Expected tasks, receipts and budget")
        if type(data["tasks"]) is not list or type(data["receipts"]) is not list:
            raise ValueError("Expected task and receipt arrays")
        if len(data["tasks"]) > MAX_TASKS or len(data["receipts"]) > MAX_RECEIPTS:
            raise ValueError("Too many inputs")
        if any(type(x) is not dict for x in data["tasks"] + data["receipts"]):
            raise ValueError("Expected objects")
        if type(data["budget"]) is not dict:
            raise ValueError("Expected budget object")
        tasks = tuple(PracticeTask(**item) for item in data["tasks"])
        receipts = tuple(PracticeReceipt(**item) for item in data["receipts"])
        return propose_practice(tasks, receipts, PracticeBudget(**data["budget"]))
    except (UnicodeError, TypeError, OverflowError, RecursionError, KeyError) as exc:
        raise ValueError("Malformed practice proposal input") from exc


def main() -> int:
    try:
        result = plan_from_json(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
