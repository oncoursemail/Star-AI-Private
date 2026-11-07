"""Preregistered owner-only audit of STAR's transfer to previously unseen games.

A practice-trained maneuver does not demonstrate mastery of a new game or level.
This host-side experiment freezes source practice BEFORE any independent target
evaluation, excludes any target scope already present in the signed skill bank,
and reports only aggregate out-of-sample results with conservative uncertainty.

Never expose this auditor to LLM tools, curriculum planners, stream viewers, or
public leaderboards. The trusted host owns separate practice/evaluator keys and
signs actual observed game results via GameplaySkillBank. This module cannot
play games, create trials, sign evidence, or assert causal improvement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock

from .gameplay_skill_bank import GameplaySkillBank, wilson_lower

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_PROTOCOLS = 1000


def _id(value: object) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("expected bounded owner-curated symbolic identifier")
    return value


def _time(value: object) -> int:
    if type(value) is not int or not 0 < value <= 10**11:
        raise ValueError("expected positive integer Unix seconds")
    return value


@dataclass(frozen=True)
class TransferProtocol:
    """Owner-curated semantic mapping, NOT a claim the mechanics are identical."""

    protocol_id: str
    source_game: str
    source_version: str
    source_objective: str
    source_situation: str
    source_action: str
    target_game: str
    target_version: str
    target_objective: str
    target_situation: str
    target_action: str
    registered_unix_s: int
    minimum_source_trials: int = 12
    minimum_target_trials: int = 12
    target_wilson_floor_bps: int = 5500

    def __post_init__(self) -> None:
        for field in (
            "protocol_id", "source_game", "source_version", "source_objective",
            "source_situation", "source_action", "target_game", "target_version",
            "target_objective", "target_situation", "target_action",
        ):
            _id(getattr(self, field))
        _time(self.registered_unix_s)
        if (type(self.minimum_source_trials) is not int
                or not 8 <= self.minimum_source_trials <= 100
                or type(self.minimum_target_trials) is not int
                or not 8 <= self.minimum_target_trials <= 100
                or type(self.target_wilson_floor_bps) is not int
                or not 5000 <= self.target_wilson_floor_bps <= 9000):
            raise ValueError("invalid preregistered evidence requirements")
        source = (self.source_game, self.source_version,
                  self.source_objective, self.source_situation)
        target = (self.target_game, self.target_version,
                  self.target_objective, self.target_situation)
        if source == target:
            raise ValueError("source and holdout must be distinct game/version/scenes")


@dataclass(frozen=True)
class TransferReview:
    """Aggregate OWNER-only finding; never permission to play or train."""

    status: str
    source_trials: int
    source_success_rate: float
    holdout_trials: int
    holdout_success_rate: float | None
    holdout_wilson_lower: float | None
    observed_gap: float | None
    authorized_to_play: bool = False


class GameTransferAuditor:
    """Persistent, opt-in preregistration and verified holdout aggregation.

    The source baseline is frozen at preregistration, rather than recomputed
    after exposure to target outcomes. Target scopes with ANY previous signed
    trial cannot be reused as supposedly novel experiments.
    """

    def __init__(self, bank: GameplaySkillBank, database: str | Path = ":memory:",
                 *, registration_key: bytes) -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("independently signed GameplaySkillBank required")
        if type(registration_key) is not bytes or len(registration_key) < 32:
            raise ValueError("host-only preregistration key must be 32+ bytes")
        self._registration_key = registration_key
        path = str(database)
        if (not path or (path != ":memory:"
                         and (Path(path).is_symlink()
                              or Path(path).parent.is_symlink()
                              or not Path(path).parent.is_dir()))):
            raise ValueError("audit database needs an existing non-symlink directory")
        self._bank = bank
        self._db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self._db.execute("PRAGMA trusted_schema=OFF")
        self._db.execute("""CREATE TABLE IF NOT EXISTS transfer_protocols (
            protocol_id TEXT PRIMARY KEY,
            specification TEXT NOT NULL,
            source_successes INTEGER NOT NULL,
            source_trials INTEGER NOT NULL,
            registration_receipt TEXT NOT NULL
        )""")
        self._lock = RLock()
        self._enabled = False

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "GameTransferAuditor":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("trusted owner must enable the transfer auditor")
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    def _receipt(self, specification: str, successes: int, trials: int) -> str:
        payload = (b"star.transfer.preregister.v1\\x00" + specification.encode("utf-8")
                   + b"\\x00" + str(successes).encode("ascii")
                   + b"/" + str(trials).encode("ascii"))
        return hmac.new(self._registration_key, payload, hashlib.sha256).hexdigest()

    def register(self, protocol: TransferProtocol, *, now_unix_s: int,
                 owner_approved: bool = False) -> bool:
        """Freeze the training baseline before an unseen signed holdout exists."""
        if owner_approved is not True:
            raise PermissionError("preregistration requires owner review")
        if not isinstance(protocol, TransferProtocol):
            raise TypeError("expected immutable TransferProtocol")
        now = _time(now_unix_s)
        with self._lock:
            if not self._enabled or now != protocol.registered_unix_s:
                return False
            if self._db.execute(
                "SELECT 1 FROM transfer_protocols WHERE protocol_id=?",
                (protocol.protocol_id,),
            ).fetchone():
                return False
            if self._db.execute("SELECT COUNT(*) FROM transfer_protocols").fetchone()[0] >= _MAX_PROTOCOLS:
                return False

            # A target ever used for ANY skill practice/validation is not a
            # genuinely unseen held-out setting, including stale evidence.
            target = (protocol.target_game, protocol.target_version,
                      protocol.target_objective, protocol.target_situation)
            if self._bank._db.execute(
                "SELECT 1 FROM gameplay_trials WHERE game_id=? AND game_version=? "
                "AND objective_id=? AND situation_id=? LIMIT 1", target,
            ).fetchone():
                return False

            successes, attempts = self._bank._signed_audit_counts(
                protocol.source_game, protocol.source_version,
                protocol.source_objective, protocol.source_situation,
                protocol.source_action, split="practice", now_unix_s=now,
                before_unix_s=now,
            )
            # A weak source policy cannot be called a skill that transferred.
            if (attempts < protocol.minimum_source_trials
                    or wilson_lower(successes, attempts) < 0.55):
                return False
            specification = json.dumps(asdict(protocol), sort_keys=True,
                                       separators=(",", ":"))
            self._db.execute(
                "INSERT INTO transfer_protocols VALUES (?, ?, ?, ?, ?)",
                (protocol.protocol_id, specification, successes, attempts,
                 self._receipt(specification, successes, attempts)),
            )
            return True

    def owner_report(self, protocol_id: str, *, now_unix_s: int,
                     owner_approved: bool = False) -> TransferReview | None:
        """Read only signed, fresh POST-registration independent validation."""
        if owner_approved is not True:
            raise PermissionError("holdout results are owner-only")
        identifier = _id(protocol_id)
        now = _time(now_unix_s)
        with self._lock:
            if not self._enabled:
                return None
            row = self._db.execute(
                "SELECT specification, source_successes, source_trials, registration_receipt "
                "FROM transfer_protocols WHERE protocol_id=?", (identifier,),
            ).fetchone()
            if row is None:
                return None
            if (type(row[3]) is not str or not hmac.compare_digest(
                    self._receipt(row[0], row[1], row[2]), row[3])):
                raise sqlite3.IntegrityError("transfer preregistration signature mismatch")
            try:
                plan = TransferProtocol(**json.loads(row[0]))
            except (TypeError, ValueError) as exc:
                raise sqlite3.IntegrityError("preregistered transfer protocol corrupted") from exc
            if plan.protocol_id != identifier or now < plan.registered_unix_s:
                raise sqlite3.IntegrityError("preregistered audit identity or clock mismatch")
            source_successes, source_n = row[1], row[2]
            if not (type(source_successes) is int and type(source_n) is int
                    and 0 <= source_successes <= source_n
                    and source_n >= plan.minimum_source_trials):
                raise sqlite3.IntegrityError("frozen source baseline corrupted")
            source_verified = self._bank._signed_audit_counts(
                plan.source_game, plan.source_version,
                plan.source_objective, plan.source_situation,
                plan.source_action, split="practice", now_unix_s=now,
                before_unix_s=plan.registered_unix_s,
            )
            if source_verified != (source_successes, source_n):
                raise sqlite3.IntegrityError("frozen source baseline has changed or expired")
            # A game/scene encountered in practice is no longer a blind
            # holdout. This check includes all target actions and old records.
            _, contaminated = self._bank._signed_audit_counts(
                plan.target_game, plan.target_version, plan.target_objective,
                plan.target_situation, "*", split="practice", now_unix_s=now,
                include_stale=True,
            )
            source_rate = source_successes / source_n
            if contaminated:
                return TransferReview("holdout_contaminated_by_practice", source_n,
                                      round(source_rate, 4), 0, None, None, None)
            if now - plan.registered_unix_s > 30 * 86400:
                return TransferReview("evaluation_window_expired", source_n,
                                      round(source_rate, 4), 0, None, None, None)
            successful, attempts = self._bank._signed_audit_counts(
                plan.target_game, plan.target_version, plan.target_objective,
                plan.target_situation, plan.target_action, split="validation",
                now_unix_s=now, after_unix_s=plan.registered_unix_s,
            )
            target_rate = successful / attempts if attempts else None
            lower = wilson_lower(successful, attempts) if attempts else None
            if attempts < plan.minimum_target_trials:
                status = "insufficient_independent_holdout"
            elif lower is not None and lower >= plan.target_wilson_floor_bps / 10000:
                status = "bounded_transfer_evidence_for_owner_review"
            else:
                status = "heldout_transfer_not_demonstrated"
            return TransferReview(
                status=status, source_trials=source_n,
                source_success_rate=round(source_rate, 4),
                holdout_trials=attempts,
                holdout_success_rate=round(target_rate, 4) if target_rate is not None else None,
                holdout_wilson_lower=round(lower, 4) if lower is not None else None,
                observed_gap=round(source_rate - target_rate, 4) if target_rate is not None else None,
            )


__all__ = ["TransferProtocol", "TransferReview", "GameTransferAuditor"]
