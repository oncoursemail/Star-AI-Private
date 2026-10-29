"""Opt-in, read-only comparison of TWO real Roblox Studio CLI scene audits.

An owner-approved, trusted Windows host may audit existing local scene snapshots
before and after a proposed change. Star must never treat a low warning count
as proof of gameplay success, visual polish, or permission to edit/publish.

The evaluator is deliberately independent of the model's own success claims.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import math
from pathlib import Path
from typing import Callable

from .studio_cli_scene_audit import (
    CliSceneAudit, FIELDS, MAX_DESCENDANTS, _local_fixture, audit_local_scene,
)

_RISKS = ("unanchored_collidable", "invisible_collidable",
          "tiny_parts", "models_without_primary_part")
_MAX_FIXTURE_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class SceneRegressionPolicy:
    """Human-reviewed thresholds. Increased heuristic counts need review.

    Each extra risk count is a suspicion, not necessarily a design error:
    unanchored physics props, invisible boundaries and models without a
    PrimaryPart can all be intentional. Tuning a policy is an owner decision.
    """
    allowed_increases: tuple[tuple[str, int], ...] = ()
    min_basepart_retention: float = 0.75
    min_descendant_retention: float = 0.75
    preserve_spawns: bool = True

    def __post_init__(self) -> None:
        if (type(self.allowed_increases) is not tuple
                or len(self.allowed_increases) > len(_RISKS)):
            raise ValueError("invalid allowed-increase policy")
        seen: set[str] = set()
        for item in self.allowed_increases:
            if (type(item) is not tuple or len(item) != 2
                    or type(item[0]) is not str or item[0] not in _RISKS
                    or item[0] in seen or type(item[1]) is not int
                    or not 0 <= item[1] <= MAX_DESCENDANTS):
                raise ValueError("risk allowances must be unique bounded pairs")
            seen.add(item[0])
        for name in ("min_basepart_retention", "min_descendant_retention"):
            value = getattr(self, name)
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 0 <= value <= 1):
                raise ValueError("retention threshold must be finite 0..1")
        if type(self.preserve_spawns) is not bool:
            raise ValueError("preserve_spawns must be bool")


@dataclass(frozen=True)
class SceneRegressionReport:
    # disabled | deferred | invalid | unavailable | regression |
    # no_detected_difference | ready_for_review
    status: str
    deltas: tuple[tuple[str, int], ...] = ()
    concerns: tuple[str, ...] = ()
    baseline_sha256: str | None = None
    candidate_sha256: str | None = None
    verified_playthrough: bool = False
    authorized_to_edit: bool = False
    authorized_to_publish: bool = False


def _counts(audit: CliSceneAudit) -> dict[str, int] | None:
    """Validate even manually constructed receipts, not just parser output."""
    if not isinstance(audit, CliSceneAudit) or audit.status != "observed":
        return None
    if (type(audit.place_id) is not int or type(audit.game_id) is not int
            or not 0 <= audit.place_id < 2**64
            or not 0 <= audit.game_id < 2**64
            or type(audit.counts) is not tuple
            or len(audit.counts) != len(FIELDS)):
        return None
    values: dict[str, int] = {}
    for pair in audit.counts:
        if (type(pair) is not tuple or len(pair) != 2
                or type(pair[0]) is not str or pair[0] not in FIELDS
                or pair[0] in values or type(pair[1]) is not int
                or not 0 <= pair[1] <= MAX_DESCENDANTS):
            return None
        values[pair[0]] = pair[1]
    if set(values) != set(FIELDS):
        return None
    if any(values[name] > values["descendants"] for name in FIELDS[1:]):
        return None
    if any(values[name] > values["base_parts"] for name in (
            "unanchored_collidable", "invisible_collidable",
            "tiny_parts", "spawn_locations")):
        return None
    return values


def compare_scene_audits(baseline: CliSceneAudit,
                         candidate: CliSceneAudit, *,
                         policy: SceneRegressionPolicy | None = None
                         ) -> SceneRegressionReport:
    """Compare structurally observed engine results; NEVER certify quality.

    An engine-observed warning delta is suggestive, not a causal explanation.
    Changes to scripts, UI, materials and gameplay are NOT represented here.
    """
    if policy is None:
        policy = SceneRegressionPolicy()
    if not isinstance(policy, SceneRegressionPolicy):
        raise TypeError("expected a bounded SceneRegressionPolicy")
    before, after = _counts(baseline), _counts(candidate)
    if (before is None or after is None
            or baseline.place_id != candidate.place_id
            or baseline.game_id != candidate.game_id):
        return SceneRegressionReport("invalid")
    deltas = tuple((name, after[name] - before[name]) for name in FIELDS)
    issues: list[str] = []
    allowed = dict(policy.allowed_increases)
    for name in _RISKS:
        if after[name] - before[name] > allowed.get(name, 0):
            issues.append(f"increase:{name}")
    if (policy.preserve_spawns
            and before["spawn_locations"] > 0
            and after["spawn_locations"] < before["spawn_locations"]):
        issues.append("lost_spawn_locations")
    if (before["base_parts"] > 0 and
            after["base_parts"] < math.ceil(
                before["base_parts"] * policy.min_basepart_retention)):
        issues.append("large_basepart_loss")
    if (before["descendants"] > 0 and
            after["descendants"] < math.ceil(
                before["descendants"] * policy.min_descendant_retention)):
        issues.append("large_descendant_loss")
    status = ("regression" if issues
              else "no_detected_difference" if all(d == 0 for _, d in deltas)
              else "ready_for_review")
    return SceneRegressionReport(status=status, deltas=deltas,
                                 concerns=tuple(issues))


def _identity(path: Path) -> str:
    """Hash local fixtures with a hard byte ceiling; never return their content."""
    if not path.is_file() or not 0 < path.stat().st_size <= _MAX_FIXTURE_BYTES:
        raise ValueError("fixture size outside bounded range")
    digest = sha256()
    size = 0
    with path.open("rb") as file:
        while block := file.read(1024 * 1024):
            size += len(block)
            if size > _MAX_FIXTURE_BYTES:
                raise ValueError("fixture changed or too large during hashing")
            digest.update(block)
    return digest.hexdigest()


def audit_scene_change(*, studio_executable: Path,
                       baseline_fixture: Path, candidate_fixture: Path,
                       trusted_workspace: Path, owner_approved: bool = False,
                       streaming_idle: bool = False,
                       policy: SceneRegressionPolicy | None = None,
                       timeout_seconds: int = 120,
                       runner: Callable[..., object] | None = None
                       ) -> SceneRegressionReport:
    """Compare two trusted on-disk snapshots without writing either place.

    The host must independently confirm streaming is idle and both files are
    its own safe local snapshots. Loading a place can execute its authored
    scripts; a path allowlist alone is NOT a malware sandbox. The injected
    runner is for tests only; production must rely on the actual Studio CLI.
    """
    if owner_approved is not True:
        return SceneRegressionReport("disabled")
    if streaming_idle is not True:
        return SceneRegressionReport("deferred")
    if policy is None:
        policy = SceneRegressionPolicy()
    if not isinstance(policy, SceneRegressionPolicy):
        raise TypeError("expected a SceneRegressionPolicy")
    before_path = _local_fixture(baseline_fixture, trusted_workspace)
    after_path = _local_fixture(candidate_fixture, trusted_workspace)
    if before_path == after_path:
        return SceneRegressionReport("invalid")
    try:
        fingerprints = (_identity(before_path), _identity(after_path))
    except (OSError, ValueError):
        return SceneRegressionReport("invalid")
    audits: list[CliSceneAudit] = []
    for fixture in (before_path, after_path):
        audit = audit_local_scene(
            studio_executable=studio_executable, fixture=fixture,
            trusted_workspace=trusted_workspace, owner_approved=True,
            timeout_seconds=timeout_seconds, runner=runner,
        )
        if audit.status != "observed":
            return SceneRegressionReport(
                "unavailable" if audit.status in {"timeout", "unavailable"}
                else "invalid")
        audits.append(audit)
    try:
        if fingerprints != (_identity(before_path), _identity(after_path)):
            return SceneRegressionReport("invalid",
                                         concerns=("fixture_changed_during_audit",))
    except (OSError, ValueError):
        return SceneRegressionReport("invalid",
                                     concerns=("fixture_changed_during_audit",))
    result = compare_scene_audits(audits[0], audits[1], policy=policy)
    if result.status == "invalid":
        return result
    return replace(result, baseline_sha256=fingerprints[0],
                   candidate_sha256=fingerprints[1])


__all__ = [
    "SceneRegressionPolicy", "SceneRegressionReport",
    "compare_scene_audits", "audit_scene_change",
]
