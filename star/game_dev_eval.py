"""Evidence-only, paired cross-engine game-development evaluation.

This module adapts externally executed GameDevBench-style task runs into a
strict, auditable comparison. It does not launch Godot, execute agent code,
inspect project files, upload assets, or control a game. A trusted local runner
must sign each completed result with a key that is never exposed to an agent.

A partial task roster is useful for screening only. A full 333-task, Godot
4.4.1-shaped run may be considered for manual review, but this module cannot
certify that a caller's roster is the official upstream roster. Pin and verify
the upstream task manifest independently before describing a run as official.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import math
import re
from threading import RLock


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40,64}\Z")
_CATEGORIES = frozenset({
    "2d_graphics_animation",
    "3d_graphics_animation",
    "ui",
    "gameplay_logic",
})
_ARMS = frozenset({"baseline", "candidate"})
_OUTCOMES = frozenset({"passed", "failed", "timeout", "infrastructure_error"})
_FEEDBACK = frozenset({"none", "screenshot", "video"})
_DOMAIN = b"star.gamedevbench.case.v1\x00"
_MAX_TASKS = 333
_MAX_ELAPSED_MS = 3_600_000
_CATEGORY_REGRESSION_TOLERANCE = 0.01


def _text(value: object, name: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")
    return value


def _key(value: bytes) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        raise ValueError("trusted evaluator key must contain at least 32 bytes")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _one_sided_sign_p(wins: int, losses: int) -> float | None:
    """Exact one-sided binomial tail over non-tied paired outcomes."""
    if wins < 0 or losses < 0:
        raise ValueError("paired outcomes cannot be negative")
    discordant = wins + losses
    if discordant == 0:
        return None
    return sum(math.comb(discordant, k) for k in range(wins, discordant + 1)) / (2 ** discordant)


@dataclass(frozen=True)
class GameDevTask:
    task_id: str
    category: str
    task_sha256: str
    first_arm: str

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id", _ID)
        if type(self.category) is not str or self.category not in _CATEGORIES:
            raise ValueError("unsupported GameDevBench task category")
        _text(self.task_sha256, "task_sha256", _SHA256)
        if type(self.first_arm) is not str or self.first_arm not in _ARMS:
            raise ValueError("first_arm must be baseline or candidate")


@dataclass(frozen=True)
class GameDevCampaign:
    """Immutable A/B contract. Every comparison input is pinned before runs."""

    campaign_id: str
    suite_revision: str
    engine_version: str
    validator_sha256: str
    baseline_agent_sha256: str
    candidate_agent_sha256: str
    feedback_mode: str
    tasks: tuple[GameDevTask, ...]
    host_verified_official_manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        _text(self.campaign_id, "campaign_id", _ID)
        _text(self.suite_revision, "suite_revision", _COMMIT)
        _text(self.validator_sha256, "validator_sha256", _SHA256)
        _text(self.baseline_agent_sha256, "baseline_agent_sha256", _SHA256)
        _text(self.candidate_agent_sha256, "candidate_agent_sha256", _SHA256)
        if self.baseline_agent_sha256 == self.candidate_agent_sha256:
            raise ValueError("baseline and candidate agent revisions must differ")
        if type(self.engine_version) is not str or not 1 <= len(self.engine_version) <= 32:
            raise ValueError("engine_version must be bounded text")
        if type(self.feedback_mode) is not str or self.feedback_mode not in _FEEDBACK:
            raise ValueError("feedback_mode must be none, screenshot or video")
        if self.host_verified_official_manifest_sha256 is not None:
            _text(self.host_verified_official_manifest_sha256,
                  "host_verified_official_manifest_sha256", _SHA256)
        if type(self.tasks) is not tuple or not 4 <= len(self.tasks) <= _MAX_TASKS:
            raise ValueError("campaign must contain 4..333 task specifications")
        if any(type(task) is not GameDevTask for task in self.tasks):
            raise TypeError("tasks must contain GameDevTask records")
        ids = [task.task_id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task roster contains duplicate task IDs")
        if {task.category for task in self.tasks} != _CATEGORIES:
            raise ValueError("task roster must cover all four GameDevBench categories")
        baseline_first = sum(task.first_arm == "baseline" for task in self.tasks)
        candidate_first = len(self.tasks) - baseline_first
        if abs(baseline_first - candidate_first) > 1:
            raise ValueError("paired run order must be balanced across the task roster")

    @property
    def task_roster_sha256(self) -> str:
        roster = [asdict(task) for task in self.tasks]
        return hashlib.sha256(_canonical(roster)).hexdigest()

    @property
    def task_manifest_sha256(self) -> str:
        """Digest of upstream task identity/category/content, excluding A/B order."""
        manifest = [
            {"task_id": task.task_id, "category": task.category,
             "task_sha256": task.task_sha256}
            for task in self.tasks
        ]
        return hashlib.sha256(_canonical(manifest)).hexdigest()

    @property
    def official_roster_verified(self) -> bool:
        return (self.full_suite_shape
                and self.host_verified_official_manifest_sha256 == self.task_manifest_sha256)

    @property
    def campaign_sha256(self) -> str:
        payload = {
            "campaign_id": self.campaign_id,
            "suite_revision": self.suite_revision,
            "engine_version": self.engine_version,
            "validator_sha256": self.validator_sha256,
            "baseline_agent_sha256": self.baseline_agent_sha256,
            "candidate_agent_sha256": self.candidate_agent_sha256,
            "feedback_mode": self.feedback_mode,
            "task_roster_sha256": self.task_roster_sha256,
            "task_manifest_sha256": self.task_manifest_sha256,
            "host_verified_official_manifest_sha256": self.host_verified_official_manifest_sha256,
        }
        return hashlib.sha256(_canonical(payload)).hexdigest()

    @property
    def full_suite_shape(self) -> bool:
        """Shape only; not proof that the roster matches upstream's official 333 tasks."""
        return len(self.tasks) == _MAX_TASKS and self.engine_version == "4.4.1"


@dataclass(frozen=True)
class GameDevReceipt:
    """Host-signed result metadata; no prompt, code, path, screenshot or media."""

    campaign_id: str
    task_id: str
    task_sha256: str
    arm: str
    agent_sha256: str
    run_id: str
    run_order: int
    outcome: str
    elapsed_ms: int
    environment_sha256: str
    artifact_sha256: str | None
    suite_revision: str
    engine_version: str
    validator_sha256: str
    feedback_mode: str

    def __post_init__(self) -> None:
        _text(self.campaign_id, "campaign_id", _ID)
        _text(self.task_id, "task_id", _ID)
        _text(self.task_sha256, "task_sha256", _SHA256)
        if type(self.arm) is not str or self.arm not in _ARMS:
            raise ValueError("arm must be baseline or candidate")
        _text(self.agent_sha256, "agent_sha256", _SHA256)
        _text(self.run_id, "run_id", _ID)
        if type(self.run_order) is not int or self.run_order not in (1, 2):
            raise ValueError("run_order must be 1 or 2")
        if type(self.outcome) is not str or self.outcome not in _OUTCOMES:
            raise ValueError("unsupported task outcome")
        if type(self.elapsed_ms) is not int or not 0 <= self.elapsed_ms <= _MAX_ELAPSED_MS:
            raise ValueError("elapsed_ms is outside the supported range")
        _text(self.environment_sha256, "environment_sha256", _SHA256)
        if self.artifact_sha256 is not None:
            _text(self.artifact_sha256, "artifact_sha256", _SHA256)
        elif self.outcome != "infrastructure_error":
            raise ValueError("completed task attempts require an artifact digest")
        _text(self.suite_revision, "suite_revision", _COMMIT)
        if type(self.engine_version) is not str or not 1 <= len(self.engine_version) <= 32:
            raise ValueError("engine_version must be bounded text")
        _text(self.validator_sha256, "validator_sha256", _SHA256)
        if type(self.feedback_mode) is not str or self.feedback_mode not in _FEEDBACK:
            raise ValueError("invalid feedback_mode")

    def canonical_bytes(self) -> bytes:
        return _DOMAIN + _canonical(asdict(self))


def sign_receipt(receipt: GameDevReceipt, key: bytes) -> str:
    """Trusted-runner helper. Never make this key available to an agent/model."""
    if type(receipt) is not GameDevReceipt:
        raise TypeError("expected GameDevReceipt")
    return hmac.new(_key(key), receipt.canonical_bytes(), hashlib.sha256).hexdigest()


class GameDevEvaluator:
    """Thread-safe, one-shot A/B receipt verifier and category-aware scorecard."""

    def __init__(self, campaign: GameDevCampaign, *, receipt_key: bytes) -> None:
        if type(campaign) is not GameDevCampaign:
            raise TypeError("expected GameDevCampaign")
        self.campaign = campaign
        self._key = _key(receipt_key)
        self._tasks = {task.task_id: task for task in campaign.tasks}
        self._receipts: dict[tuple[str, str], GameDevReceipt] = {}
        self._run_ids: set[str] = set()
        self._lock = RLock()
        self._contamination: set[str] = set()
        self._environment_sha256: str | None = None

    def add(self, receipt: GameDevReceipt, signature: str) -> None:
        if type(receipt) is not GameDevReceipt:
            raise TypeError("expected GameDevReceipt")
        if type(signature) is not str or _SHA256.fullmatch(signature) is None:
            raise PermissionError("invalid host receipt signature")
        expected = hmac.new(self._key, receipt.canonical_bytes(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise PermissionError("host receipt signature mismatch")
        with self._lock:
            campaign = self.campaign
            if (receipt.campaign_id != campaign.campaign_id
                    or receipt.suite_revision != campaign.suite_revision
                    or receipt.engine_version != campaign.engine_version
                    or receipt.validator_sha256 != campaign.validator_sha256
                    or receipt.feedback_mode != campaign.feedback_mode):
                raise ValueError("receipt does not match the preregistered campaign")
            spec = self._tasks.get(receipt.task_id)
            if spec is None or spec.task_sha256 != receipt.task_sha256:
                raise ValueError("receipt task is absent from the preregistered roster")
            expected_agent = (campaign.baseline_agent_sha256 if receipt.arm == "baseline"
                              else campaign.candidate_agent_sha256)
            if receipt.agent_sha256 != expected_agent:
                raise ValueError("receipt agent revision does not match its A/B arm")
            expected_order = 1 if receipt.arm == spec.first_arm else 2
            if receipt.run_order != expected_order:
                raise ValueError("receipt violates the preregistered paired run order")
            pair_key = (receipt.task_id, receipt.arm)
            if pair_key in self._receipts or receipt.run_id in self._run_ids:
                raise ValueError("duplicate task-arm receipt or replayed run ID")
            previous = self._receipts.get((receipt.task_id, "baseline" if receipt.arm == "candidate" else "candidate"))
            if previous is not None and previous.environment_sha256 != receipt.environment_sha256:
                self._contamination.add("paired_environment_mismatch")
            if self._environment_sha256 is None:
                self._environment_sha256 = receipt.environment_sha256
            elif self._environment_sha256 != receipt.environment_sha256:
                self._contamination.add("campaign_environment_mismatch")
            self._receipts[pair_key] = receipt
            self._run_ids.add(receipt.run_id)

    def report(self) -> dict:
        with self._lock:
            campaign = self.campaign
            missing = []
            categories: dict[str, dict[str, object]] = {}
            wins = losses = ties = infra = 0
            all_elapsed: dict[str, list[int]] = {"baseline": [], "candidate": []}
            for category in sorted(_CATEGORIES):
                specs = [task for task in campaign.tasks if task.category == category]
                baseline_pass = candidate_pass = 0
                paired = 0
                for spec in specs:
                    base = self._receipts.get((spec.task_id, "baseline"))
                    cand = self._receipts.get((spec.task_id, "candidate"))
                    if base is None:
                        missing.append(f"{spec.task_id}:baseline")
                    if cand is None:
                        missing.append(f"{spec.task_id}:candidate")
                    for arm, item in (("baseline", base), ("candidate", cand)):
                        if item is not None:
                            all_elapsed[arm].append(item.elapsed_ms)
                            infra += int(item.outcome == "infrastructure_error")
                    if base is None or cand is None:
                        continue
                    paired += 1
                    base_ok = base.outcome == "passed"
                    cand_ok = cand.outcome == "passed"
                    baseline_pass += int(base_ok)
                    candidate_pass += int(cand_ok)
                    if cand_ok and not base_ok:
                        wins += 1
                    elif base_ok and not cand_ok:
                        losses += 1
                    else:
                        ties += 1
                total = len(specs)
                baseline_rate = baseline_pass / total if total else 0.0
                candidate_rate = candidate_pass / total if total else 0.0
                categories[category] = {
                    "tasks": total,
                    "paired": paired,
                    "baseline_passes": baseline_pass,
                    "candidate_passes": candidate_pass,
                    "baseline_pass_rate": round(baseline_rate, 6),
                    "candidate_pass_rate": round(candidate_rate, 6),
                    "delta": round(candidate_rate - baseline_rate, 6),
                }
            missing.sort()
            total_tasks = len(campaign.tasks)
            complete = not missing and infra == 0 and not self._contamination
            regressions = [
                category for category, values in categories.items()
                if float(values["delta"]) < -_CATEGORY_REGRESSION_TOLERANCE
            ]
            p_value = _one_sided_sign_p(wins, losses) if complete else None
            full_shape = campaign.full_suite_shape
            if self._contamination or infra:
                status = "inconclusive_infrastructure_contamination"
            elif missing:
                status = "incomplete"
            elif regressions:
                status = "keep_baseline_category_regression"
            elif (campaign.official_roster_verified and wins > losses
                  and p_value is not None and p_value < 0.05
                  and sum(v["tasks"] for v in categories.values()) == _MAX_TASKS):
                status = "manual_review_recommended"
            elif wins > losses:
                status = "screening_only"
            else:
                status = "no_measured_improvement"
            completed_pairs = sum(int(values["paired"]) for values in categories.values())
            return {
                "campaign_sha256": campaign.campaign_sha256,
                "task_roster_sha256": campaign.task_roster_sha256,
                "task_manifest_sha256": campaign.task_manifest_sha256,
                "full_333_task_godot_4_4_1_shape": full_shape,
                "official_roster_verified": campaign.official_roster_verified,
                "status": status,
                "tasks": total_tasks,
                "completed_pairs": completed_pairs,
                "missing_receipts": len(missing),
                "infrastructure_errors": infra,
                "contamination": sorted(self._contamination),
                "paired_candidate_wins": wins,
                "paired_candidate_losses": losses,
                "paired_ties": ties,
                "paired_sign_test_p": round(p_value, 8) if p_value is not None else None,
                "category_regressions": regressions,
                "categories": categories,
                "elapsed_ms": {
                    arm: {
                        "median": _nearest_rank(values, 0.50),
                        "p95": _nearest_rank(values, 0.95),
                        "n": len(values),
                    }
                    for arm, values in all_elapsed.items()
                },
                "limitations": [
                    "This report verifies signed runner receipts, not the truthfulness of the host observer.",
                    "Official-roster status requires a trusted host to verify and pin the upstream manifest digest.",
                    "Replay protection is in-memory for this evaluator instance; persist campaign IDs in the trusted host ledger across restarts.",
                    "A positive result recommends human review only; it never changes a model or grants game/tool access.",
                    "Pass rates and elapsed times are separate lanes; elapsed time is not an inference-speed measurement.",
                ],
            }


__all__ = [
    "GameDevTask", "GameDevCampaign", "GameDevReceipt", "GameDevEvaluator",
    "sign_receipt",
]
