"""Offline, evidence-gated evaluation of STAR's continual-learning memory.

This module measures whether persistent memory helps an unchanged agent reuse
skills across controlled task streams without harming unrelated tasks or
forgetting earlier capabilities. It does not execute models, tools, games, or
training. A trusted host supplies independently signed, content-free receipts.

The statistical unit is a preregistered stream, not an individual task. This
avoids treating many correlated tasks from one long session as independent
observations. Development results are screening only; a sealed holdout can
recommend manual review, never automatic memory-policy promotion.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import re
from statistics import median
from typing import Sequence

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,95}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ROLES = {"acquire", "dependent_probe", "independent_probe", "conventional_probe", "retention_probe"}
_ARMS = {"memory_off", "memory_on"}
_STATUSES = {"pass", "fail", "timeout", "infra_error"}
_MAX_TASKS = 512
_MAX_RECEIPTS = 1024
_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
_MAX_ELAPSED_MS = 30 * 60 * 1000
_MAX_TOKENS = 2_000_000


def _id(value: object, label: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def _sha(value: object, label: str) -> None:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class TaskSpec:
    """One opaque task in a preregistered stream; no prompt or oracle is stored."""

    task_id: str
    stream_id: str
    sequence: int
    domain: str
    skill_id: str
    role: str
    task_sha256: str
    first_arm: str
    prerequisite_ids: tuple[str, ...] = ()
    source_task_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("task_id", "stream_id", "domain", "skill_id"):
            _id(getattr(self, name), name)
        _sha(self.task_sha256, "task content digest")
        if type(self.sequence) is not int or not 0 <= self.sequence <= 4095:
            raise ValueError("invalid task sequence")
        if self.role not in _ROLES:
            raise ValueError("invalid task role")
        if self.first_arm not in _ARMS:
            raise ValueError("invalid stream first arm")
        if type(self.prerequisite_ids) is not tuple or len(self.prerequisite_ids) > 16:
            raise ValueError("prerequisites must be a bounded tuple")
        for item in self.prerequisite_ids:
            _id(item, "prerequisite ID")
        if len(set(self.prerequisite_ids)) != len(self.prerequisite_ids):
            raise ValueError("duplicate prerequisite")
        if self.source_task_id is not None:
            _id(self.source_task_id, "source task ID")
        if self.role == "dependent_probe":
            if not self.prerequisite_ids or self.source_task_id is not None:
                raise ValueError("dependent probes require prior skills, not a retention source")
        elif self.role == "retention_probe":
            if self.prerequisite_ids or self.source_task_id is None:
                raise ValueError("retention probes require exactly one source task")
        elif self.prerequisite_ids or self.source_task_id is not None:
            raise ValueError("only dependent/retention probes may reference prior tasks")


@dataclass(frozen=True)
class CampaignManifest:
    """Precommitted comparison; the only intended variable is memory policy."""

    campaign_id: str
    split: str
    backbone_sha256: str
    runner_sha256: str
    grader_sha256: str
    prompt_template_sha256: str
    tool_policy_sha256: str
    memory_off_policy_sha256: str
    memory_on_policy_sha256: str
    context_budget_tokens: int
    output_budget_tokens: int
    memory_budget_tokens: int
    tasks: tuple[TaskSpec, ...]

    def __post_init__(self) -> None:
        _id(self.campaign_id, "campaign ID")
        if self.split not in {"development", "holdout"}:
            raise ValueError("split must be development or holdout")
        for name in ("backbone_sha256", "runner_sha256", "grader_sha256", "prompt_template_sha256",
                     "tool_policy_sha256", "memory_off_policy_sha256", "memory_on_policy_sha256"):
            _sha(getattr(self, name), name)
        if self.memory_off_policy_sha256 == self.memory_on_policy_sha256:
            raise ValueError("memory policies must differ")
        if type(self.context_budget_tokens) is not int or not 512 <= self.context_budget_tokens <= 2_000_000:
            raise ValueError("invalid context budget")
        if type(self.output_budget_tokens) is not int or not 1 <= self.output_budget_tokens <= 65_536:
            raise ValueError("invalid output budget")
        if type(self.memory_budget_tokens) is not int or not 1 <= self.memory_budget_tokens <= 1_000_000:
            raise ValueError("invalid memory budget")
        if type(self.tasks) is not tuple or not 8 <= len(self.tasks) <= _MAX_TASKS:
            raise ValueError("campaign requires 8..512 task specifications")
        if any(not isinstance(task, TaskSpec) for task in self.tasks):
            raise TypeError("tasks must be TaskSpec values")
        if len({task.task_id for task in self.tasks}) != len(self.tasks):
            raise ValueError("duplicate task ID")
        self._validate_streams()

    def _validate_streams(self) -> None:
        streams: dict[str, list[TaskSpec]] = {}
        for task in self.tasks:
            streams.setdefault(task.stream_id, []).append(task)
        if not 4 <= len(streams) <= 128:
            raise ValueError("campaign requires 4..128 independent streams")
        first_arms = [items[0].first_arm for items in streams.values()]
        if abs(first_arms.count("memory_off") - first_arms.count("memory_on")) > 1:
            raise ValueError("stream first-arm assignment must be balanced")
        task_map = {task.task_id: task for task in self.tasks}
        non_retention_digests: set[str] = set()
        for stream_id, items in streams.items():
            items.sort(key=lambda item: item.sequence)
            if len({item.sequence for item in items}) != len(items):
                raise ValueError("duplicate sequence within stream")
            if len({item.first_arm for item in items}) != 1:
                raise ValueError("first-arm assignment changed within stream")
            if not any(item.role == "acquire" for item in items):
                raise ValueError("each stream needs an acquisition task")
            if not any(item.role == "dependent_probe" for item in items):
                raise ValueError("each stream needs a dependent transfer probe")
            if not any(item.role == "independent_probe" for item in items):
                raise ValueError("each stream needs an independent interference probe")
            seen: set[str] = set()
            acquired_skills: set[str] = set()
            for item in items:
                for prereq_id in item.prerequisite_ids:
                    prereq = task_map.get(prereq_id)
                    if prereq is None or prereq.stream_id != stream_id or prereq.role != "acquire" or prereq_id not in seen:
                        raise ValueError("dependent probe must reference an earlier acquisition in its own stream")
                if item.role == "retention_probe":
                    source = task_map.get(item.source_task_id or "")
                    if (source is None or source.stream_id != stream_id or source.role != "acquire"
                            or source.task_id not in seen or source.skill_id != item.skill_id
                            or source.task_sha256 != item.task_sha256):
                        raise ValueError("retention probe must replay the exact earlier acquisition")
                if item.role == "independent_probe":
                    if not acquired_skills:
                        raise ValueError("independent probe must follow an acquisition")
                    if item.skill_id in acquired_skills:
                        raise ValueError("independent probe overlaps an acquired skill")
                if item.role in {"dependent_probe", "conventional_probe", "retention_probe"} and not acquired_skills:
                    raise ValueError("probes must follow at least one acquisition")
                if item.role != "retention_probe":
                    if item.task_sha256 in non_retention_digests:
                        raise ValueError("duplicate task content across campaign; only retention replay is allowed")
                    non_retention_digests.add(item.task_sha256)
                if item.role == "acquire":
                    acquired_skills.add(item.skill_id)
                seen.add(item.task_id)

    def canonical_dict(self) -> dict:
        return {
            "schema": 1, "campaign_id": self.campaign_id, "split": self.split,
            "backbone_sha256": self.backbone_sha256, "runner_sha256": self.runner_sha256,
            "grader_sha256": self.grader_sha256, "prompt_template_sha256": self.prompt_template_sha256,
            "tool_policy_sha256": self.tool_policy_sha256,
            "memory_off_policy_sha256": self.memory_off_policy_sha256,
            "memory_on_policy_sha256": self.memory_on_policy_sha256,
            "context_budget_tokens": self.context_budget_tokens,
            "output_budget_tokens": self.output_budget_tokens,
            "memory_budget_tokens": self.memory_budget_tokens,
            "tasks": [
                {"task_id": t.task_id, "stream_id": t.stream_id, "sequence": t.sequence,
                 "domain": t.domain, "skill_id": t.skill_id, "role": t.role,
                 "task_sha256": t.task_sha256, "first_arm": t.first_arm,
                 "prerequisite_ids": list(t.prerequisite_ids), "source_task_id": t.source_task_id}
                for t in self.tasks
            ],
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(b"star.continual-learning.manifest.v1\x00" + _canonical(self.canonical_dict())).hexdigest()


@dataclass(frozen=True)
class TaskReceipt:
    """Host-signed aggregate result. Never contains prompt, answer or viewer data."""

    manifest_sha256: str
    task_id: str
    stream_id: str
    arm: str
    arm_order: int
    run_id: str
    evidence_sha256: str
    status: str
    observed_unix_ms: int
    elapsed_ms: int
    input_tokens: int
    output_tokens: int
    memory_tokens_read: int
    memory_tokens_written: int
    signature: str = ""

    def __post_init__(self) -> None:
        _sha(self.manifest_sha256, "manifest digest")
        _id(self.task_id, "task ID")
        _id(self.stream_id, "stream ID")
        _id(self.run_id, "run ID")
        _sha(self.evidence_sha256, "evidence digest")
        if self.arm not in _ARMS or type(self.arm_order) is not int or self.arm_order not in (0, 1):
            raise ValueError("invalid experiment arm")
        if self.status not in _STATUSES:
            raise ValueError("invalid task status")
        for name, low, high in (
            ("observed_unix_ms", 1, 10**14), ("elapsed_ms", 1, _MAX_ELAPSED_MS),
            ("input_tokens", 0, _MAX_TOKENS), ("output_tokens", 0, _MAX_TOKENS),
            ("memory_tokens_read", 0, _MAX_TOKENS), ("memory_tokens_written", 0, _MAX_TOKENS),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"invalid {name}")
        if type(self.signature) is not str or (self.signature and _SHA.fullmatch(self.signature) is None):
            raise ValueError("invalid receipt signature")

    def unsigned_dict(self) -> dict:
        return {name: getattr(self, name) for name in (
            "manifest_sha256", "task_id", "stream_id", "arm", "arm_order", "run_id",
            "evidence_sha256", "status", "observed_unix_ms", "elapsed_ms", "input_tokens",
            "output_tokens", "memory_tokens_read", "memory_tokens_written")}

    def signing_bytes(self) -> bytes:
        return b"star.continual-learning.receipt.v1\x00" + _canonical(self.unsigned_dict())


@dataclass(frozen=True)
class ContinualLearningReport:
    verdict: str
    split: str
    manifest_sha256: str
    preregistered_tasks: int
    completed_pairs: int
    incomplete_pairs: int
    contaminated_pairs: int
    streams: int
    domains: int
    overall_gain_pp: float | None
    dependent_gain_pp: float | None
    independent_gain_pp: float | None
    conventional_gain_pp: float | None
    retention_gain_pp: float | None
    improved_streams: int
    worse_streams: int
    tied_streams: int
    stream_sign_test_p: float | None
    dependent_sign_test_p: float | None
    memory_read_tokens_p50: float | None
    memory_write_tokens_p50: float | None
    latency_overhead_ms_p50: float | None
    note: str = "evaluator only; no automatic memory or model promotion"


def sign_receipt(receipt: TaskReceipt, key: bytes) -> str:
    """Trusted-host helper. Keep key outside prompts, model context and repository."""
    if type(key) is not bytes or len(key) < 32:
        raise ValueError("independent host key must contain at least 32 bytes")
    return hmac.new(key, receipt.signing_bytes(), hashlib.sha256).hexdigest()


def _sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _role_stream_deltas(per_task: dict, tasks_by_stream: dict, role: str) -> list[float]:
    deltas: list[float] = []
    for stream_id, tasks in tasks_by_stream.items():
        selected = [task for task in tasks if task.role == role and task.task_id in per_task]
        if selected:
            deltas.append(sum(per_task[task.task_id] for task in selected) / len(selected))
    return deltas


def evaluate_continual_learning(
    manifest: CampaignManifest,
    receipts: Sequence[TaskReceipt],
    *,
    validation_key: bytes,
    expected_manifest_sha256: str,
    now_unix_ms: int,
    minimum_streams: int = 8,
    minimum_domains: int = 3,
    minimum_tasks: int = 24,
    max_age_ms: int = _MAX_AGE_MS,
    minimum_dependent_gain_pp: float = 5.0,
    maximum_independent_regression_pp: float = 2.0,
    maximum_retention_regression_pp: float = 2.0,
    alpha: float = 0.05,
) -> ContinualLearningReport:
    """Compare memory-off/on across sealed, paired task streams.

    The host must commit the manifest digest to an independent audit log before
    either arm runs. Receipts must be signed by a grader/runner outside the
    evaluated model. This evaluator cannot prove the host's truthfulness or
    that a holdout remained secret.
    """
    if type(validation_key) is not bytes or len(validation_key) < 32:
        raise ValueError("independent host validation key required")
    if type(now_unix_ms) is not int or not 1 <= now_unix_ms <= 10**14:
        raise ValueError("invalid host time")
    if type(expected_manifest_sha256) is not str or not _SHA.fullmatch(expected_manifest_sha256):
        raise ValueError("invalid sealed manifest digest")
    if not hmac.compare_digest(manifest.sha256, expected_manifest_sha256):
        raise PermissionError("campaign manifest differs from independently sealed digest")
    if type(receipts) not in (tuple, list) or len(receipts) > _MAX_RECEIPTS:
        raise ValueError("receipt count exceeds limit")
    if (type(minimum_streams) is not int or not 4 <= minimum_streams <= 128
            or type(minimum_domains) is not int or not 2 <= minimum_domains <= 32
            or type(minimum_tasks) is not int or not 8 <= minimum_tasks <= _MAX_TASKS
            or type(max_age_ms) is not int or not 1_000 <= max_age_ms <= _MAX_AGE_MS
            or type(alpha) not in (int, float) or not 0.001 <= alpha <= 0.20):
        raise ValueError("invalid acceptance thresholds")
    for value in (minimum_dependent_gain_pp, maximum_independent_regression_pp,
                  maximum_retention_regression_pp):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("invalid gain/regression threshold")

    tasks = {task.task_id: task for task in manifest.tasks}
    by_stream: dict[str, list[TaskSpec]] = {}
    for task in manifest.tasks:
        by_stream.setdefault(task.stream_id, []).append(task)
    for items in by_stream.values():
        items.sort(key=lambda item: item.sequence)

    pairs: dict[tuple[str, str], TaskReceipt] = {}
    seen_runs: set[str] = set()
    seen_evidence: set[str] = set()
    seen_payloads: set[str] = set()
    contaminated = False
    for receipt in receipts:
        if not isinstance(receipt, TaskReceipt):
            raise TypeError("expected TaskReceipt")
        task = tasks.get(receipt.task_id)
        if task is None or receipt.stream_id != task.stream_id:
            raise PermissionError("receipt is outside the sealed task manifest")
        if receipt.manifest_sha256 != manifest.sha256:
            raise PermissionError("receipt manifest mismatch")
        if receipt.arm_order != (0 if receipt.arm == task.first_arm else 1):
            raise PermissionError("receipt violates preregistered arm order")
        if receipt.arm == "memory_off" and (receipt.memory_tokens_read or receipt.memory_tokens_written):
            raise PermissionError("memory-off arm reported memory activity")
        if receipt.input_tokens > manifest.context_budget_tokens or receipt.output_tokens > manifest.output_budget_tokens:
            raise PermissionError("task token usage exceeds preregistered context/output budget")
        if receipt.arm == "memory_on" and (receipt.memory_tokens_read + receipt.memory_tokens_written
                                            > manifest.memory_budget_tokens):
            raise PermissionError("memory activity exceeds preregistered budget")
        if not 0 <= now_unix_ms - receipt.observed_unix_ms <= max_age_ms:
            raise PermissionError("stale or future-dated receipt")
        if not receipt.signature or not hmac.compare_digest(sign_receipt(receipt, validation_key), receipt.signature):
            raise PermissionError("independent receipt signature mismatch")
        payload_fingerprint = hashlib.sha256(receipt.signing_bytes()).hexdigest()
        if receipt.run_id in seen_runs or receipt.evidence_sha256 in seen_evidence or payload_fingerprint in seen_payloads:
            raise ValueError("replayed run, evidence, or receipt payload")
        seen_runs.add(receipt.run_id)
        seen_evidence.add(receipt.evidence_sha256)
        seen_payloads.add(payload_fingerprint)
        key = (receipt.task_id, receipt.arm)
        if key in pairs:
            raise ValueError("duplicate task/arm receipt")
        pairs[key] = receipt
        contaminated = contaminated or receipt.status == "infra_error"

    if contaminated:
        contaminated_tasks = {receipt.task_id for receipt in pairs.values() if receipt.status == "infra_error"}
        return _empty_report(manifest, len(contaminated_tasks), "contaminated")

    # Each arm must follow the preregistered task sequence, and the designated
    # first arm must precede the second arm for every paired task.
    for task in manifest.tasks:
        off = pairs.get((task.task_id, "memory_off"))
        on = pairs.get((task.task_id, "memory_on"))
        if off is not None and on is not None:
            first = off if task.first_arm == "memory_off" else on
            second = on if task.first_arm == "memory_off" else off
            if first.observed_unix_ms >= second.observed_unix_ms:
                raise PermissionError("paired receipts violate preregistered first-arm order")
    for stream_id, stream_tasks in by_stream.items():
        ordered = sorted(stream_tasks, key=lambda item: item.sequence)
        for arm in _ARMS:
            timestamps = [pairs[(task.task_id, arm)].observed_unix_ms
                          for task in ordered if (task.task_id, arm) in pairs]
            if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
                raise PermissionError("receipts violate within-stream task order")

    per_task: dict[str, float] = {}
    latencies: list[float] = []
    reads: list[float] = []
    writes: list[float] = []
    incomplete = 0
    completed = 0
    for task in manifest.tasks:
        off = pairs.get((task.task_id, "memory_off"))
        on = pairs.get((task.task_id, "memory_on"))
        if off is None or on is None:
            incomplete += 1
            continue
        off_ok = off.status == "pass"
        on_ok = on.status == "pass"
        per_task[task.task_id] = float(on_ok) - float(off_ok)
        completed += 1
        latencies.append(float(on.elapsed_ms - off.elapsed_ms))
        reads.append(float(on.memory_tokens_read))
        writes.append(float(on.memory_tokens_written))

    overall_stream_deltas: list[float] = []
    for stream_id, stream_tasks in by_stream.items():
        selected = [task for task in stream_tasks if task.task_id in per_task]
        if selected:
            overall_stream_deltas.append(sum(per_task[t.task_id] for t in selected) / len(selected))
    dep = _role_stream_deltas(per_task, by_stream, "dependent_probe")
    independent = _role_stream_deltas(per_task, by_stream, "independent_probe")
    conventional = _role_stream_deltas(per_task, by_stream, "conventional_probe")
    retention = _role_stream_deltas(per_task, by_stream, "retention_probe")
    wins = sum(value > 0 for value in overall_stream_deltas)
    losses = sum(value < 0 for value in overall_stream_deltas)
    ties = sum(value == 0 for value in overall_stream_deltas)
    dep_wins = sum(value > 0 for value in dep)
    dep_losses = sum(value < 0 for value in dep)
    domains = len({task.domain for task in manifest.tasks})

    enough = (completed == len(manifest.tasks) and completed >= minimum_tasks
              and len(by_stream) >= minimum_streams and domains >= minimum_domains
              and len(dep) >= minimum_streams and len(independent) >= minimum_streams)
    overall_gain = _mean(overall_stream_deltas)
    dependent_gain = _mean(dep)
    independent_gain = _mean(independent)
    retention_gain = _mean(retention)
    harmful = (enough and ((overall_gain is not None and overall_gain < -0.02)
               or (independent_gain is not None and independent_gain < -maximum_independent_regression_pp / 100)
               or (retention_gain is not None and retention_gain < -maximum_retention_regression_pp / 100)))
    stream_p = _sign_test(wins, losses)
    dependent_p = _sign_test(dep_wins, dep_losses)
    statistically_supported = (dependent_gain is not None
                                and dependent_gain * 100 >= minimum_dependent_gain_pp
                                and dependent_p <= alpha and dep_wins > dep_losses)
    if harmful:
        verdict = "memory_regressed"
    elif not enough:
        verdict = "inconclusive"
    elif statistically_supported and stream_p <= alpha and wins > losses:
        verdict = "development_signal_only" if manifest.split == "development" else "manual_review_recommended"
    else:
        verdict = "no_reliable_gain"

    conventional_gain = _mean(conventional)
    return ContinualLearningReport(
        verdict=verdict, split=manifest.split, manifest_sha256=manifest.sha256,
        preregistered_tasks=len(manifest.tasks), completed_pairs=completed,
        incomplete_pairs=incomplete, contaminated_pairs=0, streams=len(by_stream), domains=domains,
        overall_gain_pp=None if overall_gain is None else round(overall_gain * 100, 3),
        dependent_gain_pp=None if dependent_gain is None else round(dependent_gain * 100, 3),
        independent_gain_pp=None if independent_gain is None else round(independent_gain * 100, 3),
        conventional_gain_pp=None if conventional_gain is None else round(conventional_gain * 100, 3),
        retention_gain_pp=None if retention_gain is None else round(retention_gain * 100, 3),
        improved_streams=wins, worse_streams=losses, tied_streams=ties,
        stream_sign_test_p=round(stream_p, 8), dependent_sign_test_p=round(dependent_p, 8),
        memory_read_tokens_p50=None if not reads else float(median(reads)),
        memory_write_tokens_p50=None if not writes else float(median(writes)),
        latency_overhead_ms_p50=None if not latencies else float(median(latencies)),
    )


def _empty_report(manifest: CampaignManifest, receipt_count: int, verdict: str) -> ContinualLearningReport:
    return ContinualLearningReport(
        verdict=verdict, split=manifest.split, manifest_sha256=manifest.sha256,
        preregistered_tasks=len(manifest.tasks), completed_pairs=0, incomplete_pairs=len(manifest.tasks),
        contaminated_pairs=receipt_count, streams=len({t.stream_id for t in manifest.tasks}),
        domains=len({t.domain for t in manifest.tasks}), overall_gain_pp=None, dependent_gain_pp=None,
        independent_gain_pp=None, conventional_gain_pp=None, retention_gain_pp=None,
        improved_streams=0, worse_streams=0, tied_streams=0, stream_sign_test_p=None,
        dependent_sign_test_p=None, memory_read_tokens_p50=None, memory_write_tokens_p50=None,
        latency_overhead_ms_p50=None, note="infrastructure-contaminated campaign; no memory verdict",
    )
