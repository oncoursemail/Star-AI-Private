"""Preregistered, private real-time vs paused game-intelligence gap audit.

Gym-Anything-RT shows that paused-game competence need not transfer to a
moving world. This deterministic evaluator compares the *same* unseen game
cases in two modes using independently measured game outcomes and action
latencies. It is intentionally offline: no game, model, keyboard, microphone,
network, OBS, streaming, or training side effects.

Host booleans are declarations, not cryptographic proof. Never submit these
results to Star as permission to act, speak, publish, or promote a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil, comb, isfinite
import re
from typing import Sequence

from .game_skill_gate import GamePerformanceTrial

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


@dataclass(frozen=True)
class GameModeGapProtocol:
    """Immutable owner-curated holdout cases, defined BEFORE either mode runs."""

    game_scope: str
    cases: tuple[tuple[str, int], ...]  # (scenario_id, seed)
    max_scene_deadline_ms: float = 350.0

    def __post_init__(self) -> None:
        if type(self.game_scope) is not str or not _ID.fullmatch(self.game_scope):
            raise ValueError("invalid game scope")
        if type(self.cases) is not tuple or not 20 <= len(self.cases) <= 256:
            raise ValueError("preregister 20..256 holdout cases")
        seen: set[tuple[str, int]] = set()
        per_scenario: dict[str, int] = {}
        for item in self.cases:
            if (
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or not _ID.fullmatch(item[0])
                or type(item[1]) is not int
                or not 0 <= item[1] < 2**32
                or item in seen
            ):
                raise ValueError("cases must have unique canonical scenario/seed pairs")
            seen.add(item)
            per_scenario[item[0]] = per_scenario.get(item[0], 0) + 1
        if len(per_scenario) < 2 or any(n < 4 for n in per_scenario.values()):
            raise ValueError("holdouts require two or more scenarios with >=4 cases each")
        if (
            type(self.max_scene_deadline_ms) not in (int, float)
            or not isfinite(float(self.max_scene_deadline_ms))
            or not 50 <= self.max_scene_deadline_ms <= 2000
        ):
            raise ValueError("bounded, preregistered action deadline required")

    @property
    def digest(self) -> str:
        """Stable source-independent fingerprint; NOT a signed preregistration."""
        payload = "\n".join(
            [
                "star.game_mode_gap.v1",
                self.game_scope,
                str(self.max_scene_deadline_ms),
                *(f"{name}:{seed}" for name, seed in self.cases),
            ]
        )
        return sha256(payload.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class GameModeGapPair:
    """Host witnesses an equivalent starting position in each execution mode."""

    paused: GamePerformanceTrial
    realtime: GamePerformanceTrial
    matching_start_verified: bool
    independent_outcome_verified: bool
    realtime_scene_deadline_ms: float

    def __post_init__(self) -> None:
        p, r = self.paused, self.realtime
        if not isinstance(p, GamePerformanceTrial) or not isinstance(r, GamePerformanceTrial):
            raise TypeError("typed outcome evidence required")
        if (
            p.mode != "paused"
            or r.mode != "realtime"
            or p.split != "holdout"
            or r.split != "holdout"
            or p.game_scope != r.game_scope
            or p.scenario_id != r.scenario_id
            or p.seed != r.seed
            or p.case_id == r.case_id
        ):
            raise ValueError("different-mode outcomes must be paired on identical cases")
        if (
            not p.host_verified
            or not r.host_verified
            or self.matching_start_verified is not True
            or self.independent_outcome_verified is not True
        ):
            raise ValueError("independent host verification is required")
        deadline = self.realtime_scene_deadline_ms
        if type(deadline) not in (int, float) or not isfinite(float(deadline)):
            raise ValueError("finite scene deadline required")
        if not 50 <= deadline <= 2000:
            raise ValueError("scene deadline outside bounded range")
        if p.action_delay_ms > 60_000 or r.action_delay_ms > 60_000:
            raise ValueError("unbounded action timing measurement")


@dataclass(frozen=True)
class GameModeGapReport:
    """Anonymous descriptive summary; no subject/player information."""

    status: str
    pairs: int
    paused_successes: int
    realtime_successes: int
    paused_only_successes: int
    realtime_only_successes: int
    exact_one_sided_p: float
    paused_progress_mean: float
    realtime_progress_mean: float
    paused_action_p95_ms: float
    realtime_action_p95_ms: float
    realtime_deadline_misses: int
    deadline_misses_in_paused_only_losses: int
    protocol_sha256: str
    authorizes_play: bool = False
    authorizes_model_promotion: bool = False
    authorizes_streaming: bool = False
    establishes_cause: bool = False
    note: str = (
        "Operator-attested offline holdouts, not cryptographic proof. Pausing "
        "changes more than latency; results cannot establish why a run failed."
    )


def _p95(values: list[float]) -> float:
    return sorted(values)[ceil(0.95 * len(values)) - 1]


def audit_realtime_gap(
    protocol: GameModeGapProtocol,
    pairs: Sequence[GameModeGapPair],
) -> GameModeGapReport:
    """Compare exactly the preregistered holdouts, including every failure.

    Positive detection requires an absolute >=15-point paused/live success
    deficit and a fixed one-sided sign-test p<=.01. This is a conservative
    descriptive screening criterion, NOT a causal or real-world skill claim.
    """
    if not isinstance(protocol, GameModeGapProtocol):
        raise TypeError("frozen host-owned protocol required")
    if type(pairs) not in (list, tuple) or len(pairs) != len(protocol.cases):
        raise ValueError("all preregistered outcomes must be present")
    planned = set(protocol.cases)
    seen: set[tuple[str, int]] = set()
    case_ids: set[str] = set()
    paused_wins = live_wins = paused_only = live_only = 0
    misses = misses_on_losses = 0
    paused_progress = live_progress = 0.0
    paused_delays: list[float] = []
    live_delays: list[float] = []
    for pair in pairs:
        if not isinstance(pair, GameModeGapPair):
            raise TypeError("only verified game-mode pairs accepted")
        p, r = pair.paused, pair.realtime
        key = p.scenario_id, p.seed
        if (
            p.game_scope != protocol.game_scope
            or key not in planned
            or key in seen
            or p.case_id in case_ids
            or r.case_id in case_ids
        ):
            raise ValueError("unknown, duplicated, or cross-game holdout")
        if pair.realtime_scene_deadline_ms > protocol.max_scene_deadline_ms:
            raise ValueError("deadline differs from preregistered ceiling")
        seen.add(key)
        case_ids.update((p.case_id, r.case_id))
        paused_wins += int(p.success)
        live_wins += int(r.success)
        paused_only += int(p.success and not r.success)
        live_only += int(r.success and not p.success)
        missed = r.action_delay_ms > pair.realtime_scene_deadline_ms
        misses += int(missed)
        misses_on_losses += int(missed and p.success and not r.success)
        paused_progress += p.progress
        live_progress += r.progress
        paused_delays.append(p.action_delay_ms)
        live_delays.append(r.action_delay_ms)
    if seen != planned:
        raise ValueError("preregistered holdout case mismatch")
    discordant = paused_only + live_only
    pvalue = (
        min(1.0, sum(comb(discordant, k) for k in range(paused_only, discordant + 1)) / (1 << discordant))
        if discordant
        else 1.0
    )
    total = len(pairs)
    if paused_wins / total < 0.40 and live_wins / total < 0.40:
        status = "both_modes_struggle"
    elif paused_wins / total >= 0.60 and (paused_wins - live_wins) / total >= 0.15 and pvalue <= 0.01:
        status = "realtime_gap_detected"
    else:
        status = "no_large_gap_detected"
    return GameModeGapReport(
        status=status,
        pairs=total,
        paused_successes=paused_wins,
        realtime_successes=live_wins,
        paused_only_successes=paused_only,
        realtime_only_successes=live_only,
        exact_one_sided_p=round(pvalue, 8),
        paused_progress_mean=round(paused_progress / total, 4),
        realtime_progress_mean=round(live_progress / total, 4),
        paused_action_p95_ms=round(_p95(paused_delays), 3),
        realtime_action_p95_ms=round(_p95(live_delays), 3),
        realtime_deadline_misses=misses,
        deadline_misses_in_paused_only_losses=misses_on_losses,
        protocol_sha256=protocol.digest,
    )


__all__ = [
    "GameModeGapProtocol",
    "GameModeGapPair",
    "GameModeGapReport",
    "audit_realtime_gap",
]
