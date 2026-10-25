"""Independent, held-out skill validation before Star proposes reusable game skills.

No gameplay, file I/O, model training, persistence, auth or automatic promotion.
An authorized host must reserve the held-out scenes *before* practice starts,
score success independently, and enforce the owner-review gate externally.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_Z = 1.959963984540054


def _name(value: object, label: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"Invalid {label} identifier")


def _lower_bound(wins: int, n: int) -> float:
    if not n:
        return 0.0
    phat = wins / n
    z2 = _Z * _Z
    return max(0.0, (phat + z2 / (2 * n) - _Z * sqrt(
        phat * (1 - phat) / n + z2 / (4 * n * n))) / (1 + z2 / n))


@dataclass(frozen=True)
class SkillTrial:
    """One host-scored episode of a fixed version in a reserved scenario.

    A `holdout` string is NOT a proof that a scenario was really held out.
    Use non-overlapping host-managed scenario inventories and sealed reports.
    """

    game: str
    skill: str
    revision: str
    session: str
    environment: str
    scenario_sha256: str
    split: str
    passed: bool
    unsafe: bool

    def __post_init__(self) -> None:
        for field in ("game", "skill", "revision", "session", "environment"):
            _name(getattr(self, field), field)
        if type(self.scenario_sha256) is not str or _DIGEST.fullmatch(self.scenario_sha256) is None:
            raise ValueError("Scenario identity must be a SHA-256 digest")
        if self.split not in ("practice", "holdout"):
            raise ValueError("Unknown evaluation split")
        if type(self.passed) is not bool or type(self.unsafe) is not bool:
            raise ValueError("Results require explicit booleans")
        if self.passed and self.unsafe:
            raise ValueError("Unsafe runs are never successful")


@dataclass(frozen=True)
class PromotionReport:
    game: str
    skill: str
    revision: str
    holdout_sessions: int
    passed: int
    environments: int
    lower_95: float
    unsafe_trials: int
    status: str


class SkillPromotionGate:
    """Reject leakage, duplicate scenarios and same-session score inflation.

    Holdout scores are read only in the sense that the first accepted trial
    uniquely locks session and scenario. There is no update/delete/relabel.
    A report only *suggests owner review*, never executes/adopts a skill.
    """

    def __init__(self, *, min_holdout: int = 20,
                 min_environments: int = 3,
                 minimum_lower: float = 0.60,
                 max_trials: int = 4096) -> None:
        if type(min_holdout) is not int or not 5 <= min_holdout <= 512:
            raise ValueError("Invalid minimum held-out sessions")
        if type(min_environments) is not int or not 2 <= min_environments <= 64:
            raise ValueError("Invalid minimum environments")
        if (type(minimum_lower) not in (int, float) or not is_finite_float(minimum_lower)
                or not 0.5 <= minimum_lower < 1.0):
            raise ValueError("Invalid lower-bound threshold")
        if type(max_trials) is not int or not 1 <= max_trials <= 16384:
            raise ValueError("Invalid trial capacity")
        self.min_holdout = min_holdout
        self.min_environments = min_environments
        self.minimum_lower = minimum_lower
        self.max_trials = max_trials
        self._trials: list[SkillTrial] = []
        self._scenario: set[tuple[str, str, str]] = set()
        self._session: set[tuple[str, str, str, str]] = set()

    def record(self, trial: SkillTrial, *, trusted_host: bool = False) -> None:
        if trusted_host is not True:
            raise PermissionError("Only authorized host can score trials")
        if type(trial) is not SkillTrial:
            raise TypeError("Expected SkillTrial")
        if len(self._trials) >= self.max_trials:
            raise OverflowError("Evidence capacity reached; must rotate with review")
        common = (trial.game, trial.skill, trial.revision)
        scenario = (trial.game, trial.skill, trial.scenario_sha256)
        session = (*common, trial.session)
        if scenario in self._scenario:
            raise ValueError("Scenario reused; no repeated or cross-split evaluation")
        if session in self._session:
            raise ValueError("One independent outcome per game/skill/version/session")
        self._scenario.add(scenario)
        self._session.add(session)
        self._trials.append(trial)

    def report(self, game: str, skill: str, revision: str) -> PromotionReport:
        for label, value in (("game", game), ("skill", skill), ("revision", revision)):
            _name(value, label)
        rows = [r for r in self._trials if (r.game, r.skill, r.revision) ==
                (game, skill, revision)]
        unsafe = sum(r.unsafe for r in rows)
        holdout = [r for r in rows if r.split == "holdout"]
        passed = sum(r.passed for r in holdout)
        envs = len({r.environment for r in holdout})
        lower = _lower_bound(passed, len(holdout))
        if unsafe:
            status = "unsafe_veto"
        elif len(holdout) < self.min_holdout:
            status = "insufficient_holdout"
        elif envs < self.min_environments:
            status = "insufficient_transfer_coverage"
        elif lower < self.minimum_lower:
            status = "below_reliability_gate"
        else:
            status = "ready_for_owner_review"
        return PromotionReport(game, skill, revision, len(holdout), passed,
                               envs, round(lower, 6), unsafe, status)

    def summary(self) -> dict[str, int]:
        return {"trials": len(self._trials),
                "holdout_trials": sum(r.split == "holdout" for r in self._trials),
                "distinct_skills": len({(r.game, r.skill, r.revision) for r in self._trials})}


def is_finite_float(value: int | float) -> bool:
    return -float("inf") < value < float("inf")
