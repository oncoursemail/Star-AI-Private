"""Owner-only counterbalanced execution plan for independently sealed game tests.

A precommitted holdout alone does not prevent a candidate from playing only
after the host has warmed caches, learned the level, or changed game settings.
This module balances baseline-first/candidate-first order *within each game*,
cryptographically binds each planned slot, and independently checks host-signed
run-start receipts against evaluator-signed outcomes.

Keys and withheld scenarios remain outside Star's agent. Host timestamps,
process identity, independent observations, reproducible game builds and trusted
append-only registration are REQUIRED to claim an actual experiment. These
checks do not play games, update weights, start a stream or promote a policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import re
from typing import Sequence

from .game_holdout_seal import GameHoldoutPrecommit, evaluate_precommitted_transfer
from .game_transfer_eval import (
    HoldoutCase, SignedHoldoutTrial, TransferReport, roster_digest,
)

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PLAN_DOMAIN = b"star.game-transfer.counterbalance.v1\x00"
_START_DOMAIN = b"star.game-transfer.run-start.v1\x00"


def _key(value: object, label: str) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        raise ValueError(f"{label} must be a host-owned key of at least 32 bytes")
    return value


def _receipt(value: object, label: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise PermissionError(f"{label} must be a lowercase SHA-256 receipt")
    return value


def _payload(value: object, domain: bytes) -> bytes:
    return domain + json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _plan_hash(key: bytes, label: str, payload: bytes) -> bytes:
    return hmac.new(key, b"star.counterbalance." + label.encode("ascii") + b"\x00" + payload,
                    hashlib.sha256).digest()


@dataclass(frozen=True)
class RunSlot:
    case: HoldoutCase
    action_id: str
    nonce: str

    def __post_init__(self) -> None:
        if not isinstance(self.case, HoldoutCase):
            raise TypeError("run slot must contain a holdout case")
        if type(self.action_id) is not str or _ID.fullmatch(self.action_id) is None:
            raise ValueError("invalid action identity")
        _receipt(self.nonce, "slot nonce")


@dataclass(frozen=True)
class CounterbalancedRunPlan:
    evaluation_id: str
    roster_sha256: str
    seal_receipt: str
    slots: tuple[RunSlot, ...]

    def __post_init__(self) -> None:
        if type(self.evaluation_id) is not str or _ID.fullmatch(self.evaluation_id) is None:
            raise ValueError("invalid evaluation identity")
        _receipt(self.roster_sha256, "roster digest")
        _receipt(self.seal_receipt, "precommit receipt")
        if (type(self.slots) is not tuple or not 2 <= len(self.slots) <= 1024
                or len(self.slots) % 2 or not all(isinstance(s, RunSlot) for s in self.slots)):
            raise ValueError("plan requires a bounded tuple of paired run slots")

    def canonical_bytes(self) -> bytes:
        return _payload({
            "evaluation_id": self.evaluation_id,
            "roster_sha256": self.roster_sha256,
            "seal_receipt": self.seal_receipt,
            "slots": [asdict(slot) for slot in self.slots],
        }, _PLAN_DOMAIN)


@dataclass(frozen=True)
class GameRunStart:
    slot_index: int
    run_id: str
    slot_nonce: str
    started_unix_ms: int

    def __post_init__(self) -> None:
        if type(self.slot_index) is not int or not 0 <= self.slot_index <= 1023:
            raise ValueError("invalid slot index")
        if type(self.run_id) is not str or _ID.fullmatch(self.run_id) is None:
            raise ValueError("invalid run ID")
        _receipt(self.slot_nonce, "slot nonce")
        if (type(self.started_unix_ms) is not int
                or not 0 < self.started_unix_ms <= 10**14):
            raise ValueError("invalid run-start millisecond timestamp")

    def canonical_bytes(self) -> bytes:
        return _payload(asdict(self), _START_DOMAIN)


@dataclass(frozen=True)
class SignedGameRunStart:
    start: GameRunStart
    receipt: str


def build_counterbalanced_plan(
    seal: GameHoldoutPrecommit,
    cases: Sequence[HoldoutCase],
    *, coordinator_key: bytes, seal_receipt: str,
) -> CounterbalancedRunPlan:
    """Precompute an opaque, per-game AB/BA-balanced order at the trusted host.

    Host must store plan AND its own HMAC in a timestamped append-only log
    BEFORE any trial. The agent may not request or read the hidden plan.
    """
    if not isinstance(seal, GameHoldoutPrecommit):
        raise TypeError("invalid holdout seal")
    key = _key(coordinator_key, "coordinator key")
    _receipt(seal_receipt, "seal receipt")
    if not hmac.compare_digest(
        hmac.new(key, seal.canonical_bytes(), hashlib.sha256).hexdigest(), seal_receipt
    ):
        raise PermissionError("unverified pre-run seal")
    if not hmac.compare_digest(roster_digest(cases), seal.roster_sha256):
        raise PermissionError("the proposed cases differ from the sealed roster")

    by_game: dict[str, list[HoldoutCase]] = {}
    for case in cases:
        by_game.setdefault(case.game_id, []).append(case)
    blocks: list[tuple[RunSlot, RunSlot]] = []
    for game, group in sorted(by_game.items()):
        group.sort(key=lambda case: _plan_hash(
            key, "case-order", _payload(asdict(case), _PLAN_DOMAIN)
        ))
        offset = _plan_hash(key, "first-side", game.encode("ascii"))[0] & 1
        for position, case in enumerate(group):
            first = seal.baseline_action_id if (position + offset) % 2 == 0 else seal.candidate_action_id
            second = seal.candidate_action_id if first == seal.baseline_action_id else seal.baseline_action_id
            slots = []
            for action in (first, second):
                nonce = _plan_hash(key, "run-nonce", _payload({
                    "case": asdict(case), "action": action,
                    "evaluation_id": seal.evaluation_id,
                }, _PLAN_DOMAIN)).hex()
                slots.append(RunSlot(case, action, nonce))
            blocks.append((slots[0], slots[1]))
    blocks.sort(key=lambda block: _plan_hash(
        key, "block-order", _payload(asdict(block[0].case), _PLAN_DOMAIN)
    ))
    return CounterbalancedRunPlan(
        seal.evaluation_id, seal.roster_sha256, seal_receipt,
        tuple(slot for block in blocks for slot in block),
    )


def evaluate_counterbalanced_transfer(
    seal: GameHoldoutPrecommit, plan: CounterbalancedRunPlan,
    *, seal_receipt: str, plan_receipt: str,
    coordinator_key: bytes, start_key: bytes, validation_key: bytes,
    expected_evaluation_id: str,
    observed_baseline_revision_sha256: str,
    observed_candidate_revision_sha256: str,
    cases: Sequence[HoldoutCase],
    signed_trials: Sequence[SignedHoldoutTrial],
    signed_starts: Sequence[SignedGameRunStart],
    now_unix_s: int, minimum_pairs: int = 40, minimum_games: int = 5,
    min_cases_per_game: int = 3,
) -> TransferReport:
    """Audit registered start order before the existing signed outcome verdict.

    Three keys are held independently. Start records bind distinct run IDs to
    preassigned nonces and must strictly increase without overlapping another
    run's observed outcome. Host evidence is still necessary to show starts
    were registered in real time and games actually ran; signatures alone
    cannot prove a true clock, authentic rendering or causal improvements.
    """
    if not isinstance(seal, GameHoldoutPrecommit) or not isinstance(plan, CounterbalancedRunPlan):
        raise TypeError("expected a host-sealed plan and holdout")
    coordinator = _key(coordinator_key, "coordinator key")
    starter = _key(start_key, "start key")
    evaluator = _key(validation_key, "validation key")
    if (hmac.compare_digest(coordinator, starter)
            or hmac.compare_digest(coordinator, evaluator)
            or hmac.compare_digest(starter, evaluator)):
        raise ValueError("coordinator, start-witness and evaluator keys must differ")
    _receipt(plan_receipt, "plan receipt")
    _receipt(seal_receipt, "seal receipt")
    if (not hmac.compare_digest(plan.seal_receipt, seal_receipt)
            or not hmac.compare_digest(
                hmac.new(coordinator, plan.canonical_bytes(), hashlib.sha256).hexdigest(),
                plan_receipt,
            )):
        raise PermissionError("plan was not independently precommitted")
    if (plan.evaluation_id != seal.evaluation_id
            or not hmac.compare_digest(plan.roster_sha256, seal.roster_sha256)
            or not hmac.compare_digest(plan.roster_sha256, roster_digest(cases))):
        raise PermissionError("plan does not match sealed holdouts")

    if len(plan.slots) != 2 * len(cases):
        raise PermissionError("plan does not contain exactly two runs per case")
    ordered_cases: list[HoldoutCase] = []
    first_counts: dict[str, list[int]] = {}
    seen_nonces: set[str] = set()
    for offset in range(0, len(plan.slots), 2):
        first, second = plan.slots[offset:offset + 2]
        if (first.case != second.case or first.case in ordered_cases
                or {first.action_id, second.action_id} !=
                {seal.baseline_action_id, seal.candidate_action_id}):
            raise PermissionError("schedule has missing, repeated or unpaired test cases")
        if first.nonce == second.nonce or first.nonce in seen_nonces or second.nonce in seen_nonces:
            raise PermissionError("schedule repeats a cryptographic slot nonce")
        seen_nonces.update((first.nonce, second.nonce))
        ordered_cases.append(first.case)
        counts = first_counts.setdefault(first.case.game_id, [0, 0])
        counts[int(first.action_id == seal.candidate_action_id)] += 1
    if set(ordered_cases) != set(cases) or any(abs(a - b) > 1 for a, b in first_counts.values()):
        raise PermissionError("plan is not roster-complete and per-game counterbalanced")

    if (type(signed_starts) not in (list, tuple)
            or len(signed_starts) != len(plan.slots)
            or type(signed_trials) not in (list, tuple)
            or len(signed_trials) != len(plan.slots)):
        raise PermissionError("all planned run starts and outcomes must be independently recorded")

    outcomes = {}
    for signed in signed_trials:
        if not isinstance(signed, SignedHoldoutTrial):
            raise TypeError("expected independently signed outcomes")
        trial = signed.trial
        if trial.run_id in outcomes:
            raise PermissionError("repeated observed run identity")
        outcomes[trial.run_id] = trial
    starts = {}
    for item in signed_starts:
        if not isinstance(item, SignedGameRunStart) or not isinstance(item.start, GameRunStart):
            raise TypeError("expected independently signed run starts")
        start = item.start
        _receipt(item.receipt, "run start receipt")
        expected = hmac.new(starter, start.canonical_bytes(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, item.receipt):
            raise PermissionError("run-start witness signature mismatch")
        if start.slot_index in starts:
            raise PermissionError("duplicate run-start slot")
        starts[start.slot_index] = start

    previous_observed_ms = seal.sealed_unix_s * 1000
    seen_run_ids: set[str] = set()
    for index, slot in enumerate(plan.slots):
        start = starts.get(index)
        if start is None or not hmac.compare_digest(start.slot_nonce, slot.nonce):
            raise PermissionError("run-start identity differs from registered schedule")
        if start.run_id in seen_run_ids:
            raise PermissionError("run-start run ID was repeated")
        seen_run_ids.add(start.run_id)
        trial = outcomes.get(start.run_id)
        if trial is None:
            raise PermissionError("run start has no matching signed outcome")
        if ((trial.game_id, trial.game_version, trial.objective_id, trial.situation_id)
                != (slot.case.game_id, slot.case.game_version,
                    slot.case.objective_id, slot.case.situation_id)
                or trial.action_id != slot.action_id):
            raise PermissionError("game, version, situation or action differs from plan")
        if (not seal.sealed_unix_s * 1000 < start.started_unix_ms < seal.expires_unix_s * 1000
                or start.started_unix_ms <= previous_observed_ms
                or start.started_unix_ms >= trial.observed_unix_s * 1000):
            raise PermissionError("run-start order overlaps, predates seal or follows outcome")
        previous_observed_ms = trial.observed_unix_s * 1000

    return evaluate_precommitted_transfer(
        seal, seal_receipt=seal_receipt, coordinator_key=coordinator,
        validation_key=evaluator, expected_evaluation_id=expected_evaluation_id,
        observed_baseline_revision_sha256=observed_baseline_revision_sha256,
        observed_candidate_revision_sha256=observed_candidate_revision_sha256,
        cases=cases, signed_trials=signed_trials, now_unix_s=now_unix_s,
        minimum_pairs=minimum_pairs, minimum_games=minimum_games,
        min_cases_per_game=min_cases_per_game,
    )


__all__ = [
    "RunSlot", "CounterbalancedRunPlan", "GameRunStart",
    "SignedGameRunStart", "build_counterbalanced_plan",
    "evaluate_counterbalanced_transfer",
]
