"""Signed, independently validated gameplay skill evidence for STAR.

A local observer signs PRACTICE results; a separate evaluator signs VALIDATION
results. The two keys are supplied by the trusted host, NEVER by a model/chat.
The bank stores only scoped identifiers and evidence digests, not screenshots,
private player identities, tokens or untrusted action scripts.

This module only recommends candidate symbolic action IDs. It never presses
keys, controls a game, promotes skills, starts a stream or grants permissions.
HMAC proves origin to a trusted key holder, not that a game result was truthful.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DOMAIN = b"star.gameplay.trial.v1\x00"
_PRACTICE_MAX_AGE_S = 90 * 86400
_VALIDATION_MAX_AGE_S = 30 * 86400
_MAX_RECORDS = 50000


def _seconds(value: int) -> int:
    if type(value) is not int or value <= 0 or value > 10**11:
        raise ValueError("time must be a valid integer Unix timestamp")
    return value


def _key(value: bytes) -> bytes:
    if type(value) is not bytes or len(value) < 32:
        raise ValueError("independent host keys must be at least 32 bytes")
    return value


@dataclass(frozen=True)
class GameTrial:
    trial_id: str
    game_id: str
    game_version: str
    objective_id: str
    situation_id: str
    action_id: str
    run_id: str
    split: str                 # practice | validation
    outcome: str               # success | failure
    evidence_sha256: str       # digest of externally stored, reviewed observations
    observed_unix_s: int

    def __post_init__(self) -> None:
        for field in ("trial_id", "game_id", "game_version", "objective_id",
                      "situation_id", "action_id", "run_id"):
            value = getattr(self, field)
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError(f"{field} must be a bounded identifier")
        if self.split not in {"practice", "validation"}:
            raise ValueError("unknown trial split")
        if self.outcome not in {"success", "failure"}:
            raise ValueError("unknown trial outcome")
        if type(self.evidence_sha256) is not str or not _SHA.fullmatch(self.evidence_sha256):
            raise ValueError("evidence_sha256 must be a 64-character lowercase digest")
        _seconds(self.observed_unix_s)

    def canonical_bytes(self) -> bytes:
        """The exact, versioned byte payload the trusted adapters must sign."""
        return _DOMAIN + json.dumps(asdict(self), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class SkillSuggestion:
    status: str  # ready_for_host_review | rehearsal_only | no_evidence
    action_id: str | None
    practice_trials: int
    validation_trials: int
    validation_lower_bound: float
    reason: str
    authorized_to_play: bool = False


def wilson_lower(successes: int, attempts: int, *, z: float = 1.959963984540054) -> float:
    """Conservative 95% binomial confidence lower bound (not a causal claim)."""
    if (type(successes) is not int or type(attempts) is not int
            or attempts <= 0 or not 0 <= successes <= attempts):
        raise ValueError("attempts must be positive and successes must be 0..attempts")
    p = successes / attempts
    z2 = z * z
    den = 1.0 + z2 / attempts
    numerator = p + z2 / (2 * attempts) - z * math.sqrt(
        p * (1 - p) / attempts + z2 / (4 * attempts * attempts))
    return max(0.0, min(1.0, numerator / den))


@dataclass(frozen=True)
class PracticeEvidence:
    """Fresh, signed PRACTICE aggregates; independent holdouts are never exposed."""

    action_id: str
    trials: int
    successes: int
    most_recent_unix_s: int


class GameplaySkillBank:
    """SQLite-backed evidence ledger; owners can review advice before use.

    Caller is responsible for keeping independent signing keys outside STAR's
    model/skill sandbox. Ingest is not an authorization API and does not inspect
    game frames; trusted host adapters must verify outcomes before signing.
    """

    def __init__(self, database: str | Path = ":memory:", *, practice_key: bytes,
                 validation_key: bytes):
        self._practice_key = _key(practice_key)
        self._validation_key = _key(validation_key)
        if hmac.compare_digest(self._practice_key, self._validation_key):
            raise ValueError("practice and validation signers must be independent")
        db_path = str(database)
        if not db_path or (db_path != ":memory:" and
                           (Path(db_path).is_symlink() or Path(db_path).parent.is_symlink())):
            raise ValueError("database path must not be empty or symlinked")
        if db_path != ":memory:" and not Path(db_path).parent.is_dir():
            raise ValueError("database parent directory must already exist")
        self._db = sqlite3.connect(db_path, isolation_level=None, timeout=10)
        self._db.execute("PRAGMA trusted_schema=OFF")
        self._db.execute("""CREATE TABLE IF NOT EXISTS gameplay_trials (
            trial_id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            game_version TEXT NOT NULL,
            objective_id TEXT NOT NULL,
            situation_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            receipt TEXT NOT NULL,
            UNIQUE(game_id, game_version, objective_id, situation_id, run_id)
        )""")
        self._db.execute("""CREATE INDEX IF NOT EXISTS gameplay_trials_scope
            ON gameplay_trials(game_id, game_version, objective_id, situation_id)""")

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "GameplaySkillBank":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _check_receipt(self, trial: GameTrial, receipt: str) -> None:
        if type(receipt) is not str or not _SHA.fullmatch(receipt):
            raise PermissionError("invalid host evidence receipt")
        key = self._practice_key if trial.split == "practice" else self._validation_key
        expected = hmac.new(key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(receipt, expected):
            raise PermissionError("host evidence signature mismatch")

    def ingest(self, trial: GameTrial, receipt: str, *, now_unix_s: int) -> None:
        """Append a verified host event once. Never replace an existing run."""
        if not isinstance(trial, GameTrial):
            raise TypeError("expected GameTrial")
        now = _seconds(now_unix_s)
        age = now - trial.observed_unix_s
        max_age = (_PRACTICE_MAX_AGE_S if trial.split == "practice"
                   else _VALIDATION_MAX_AGE_S)
        if age < -10 or age > max_age:
            raise ValueError("stale or future-dated game trial")
        self._check_receipt(trial, receipt)
        payload = json.dumps(asdict(trial), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True)
        self._db.execute("BEGIN IMMEDIATE")
        try:
            if self._db.execute("SELECT COUNT(*) FROM gameplay_trials").fetchone()[0] >= _MAX_RECORDS:
                raise ValueError("skill bank is at its bounded record limit")
            self._db.execute(
                "INSERT INTO gameplay_trials "
                "(trial_id, game_id, game_version, objective_id, situation_id, "
                "run_id, payload_json, receipt) VALUES (?,?,?,?,?,?,?,?)",
                (trial.trial_id, trial.game_id, trial.game_version, trial.objective_id,
                 trial.situation_id, trial.run_id, payload, receipt),
            )
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    @staticmethod
    def _scope(game_id: str, game_version: str, objective_id: str,
               situation_id: str) -> tuple[str, str, str, str]:
        parts = (game_id, game_version, objective_id, situation_id)
        if any(type(p) is not str or not _ID.fullmatch(p) for p in parts):
            raise ValueError("game, version, objective and situation must be bounded IDs")
        return parts

    def practice_evidence(self, game_id: str, game_version: str,
                          objective_id: str, situation_id: str, *,
                          now_unix_s: int) -> tuple[PracticeEvidence, ...]:
        """Summarize fresh, signed practice only; never disclose holdout results.

        External agents can use these aggregates to select which skill to
        rehearse next. Neither withheld validation outcomes nor receipts, raw
        evidence, keys or individual run IDs leave this boundary. An invalid
        row fails closed rather than becoming training evidence.
        """
        scope = self._scope(game_id, game_version, objective_id, situation_id)
        now = _seconds(now_unix_s)
        rows = self._db.execute(
            "SELECT trial_id, run_id, payload_json, receipt FROM gameplay_trials "
            "WHERE game_id=? AND game_version=? AND objective_id=? AND situation_id=?",
            scope,
        ).fetchall()
        aggregates: dict[str, list[int]] = {}
        for trial_id, run_id, payload_json, receipt in rows:
            try:
                payload = json.loads(payload_json)
                if type(payload) is not dict:
                    raise ValueError("invalid trial JSON")
                trial = GameTrial(**payload)
                if (trial.trial_id != trial_id or trial.run_id != run_id
                        or self._scope(trial.game_id, trial.game_version,
                                       trial.objective_id, trial.situation_id) != scope):
                    raise ValueError("trial scope/identity mismatch")
                self._check_receipt(trial, receipt)
            except (TypeError, ValueError, PermissionError) as exc:
                raise sqlite3.IntegrityError("gameplay evidence ledger corrupted") from exc
            # Withheld validation is checked for integrity but NEVER used in
            # action selection. Otherwise the curriculum leaks its test set.
            if trial.split != "practice":
                continue
            age = now - trial.observed_unix_s
            if not 0 <= age <= _PRACTICE_MAX_AGE_S:
                continue
            entry = aggregates.setdefault(trial.action_id, [0, 0, 0])
            entry[0] += 1
            entry[1] += int(trial.outcome == "success")
            entry[2] = max(entry[2], trial.observed_unix_s)
        return tuple(PracticeEvidence(action, *totals)
                     for action, totals in sorted(aggregates.items()))

    def signed_practice_run(self, game_id: str, game_version: str,
                            objective_id: str, situation_id: str,
                            action_id: str, run_id: str, *,
                            not_before_unix_s: int,
                            now_unix_s: int) -> bool:
        """Validate one exact host-assigned practice run without leaking receipts.

        The host must use the reservation's run ID when creating its signed
        GameTrial. Other recent practice or held-out validation cannot be used
        to acknowledge this specific request.
        """
        scope = self._scope(game_id, game_version, objective_id, situation_id)
        for value in (action_id, run_id):
            if type(value) is not str or not _ID.fullmatch(value):
                raise ValueError("action and run must be bounded symbolic IDs")
        earliest = _seconds(not_before_unix_s)
        now = _seconds(now_unix_s)
        if earliest > now:
            raise ValueError("reservation starts after current time")
        row = self._db.execute(
            "SELECT trial_id, payload_json, receipt FROM gameplay_trials "
            "WHERE game_id=? AND game_version=? AND objective_id=? AND "
            "situation_id=? AND run_id=?",
            (*scope, run_id),
        ).fetchone()
        if row is None:
            return False
        trial_id, payload_json, receipt = row
        try:
            payload = json.loads(payload_json)
            if type(payload) is not dict:
                raise ValueError("invalid signed trial")
            trial = GameTrial(**payload)
            if (trial.trial_id != trial_id or trial.run_id != run_id
                    or self._scope(trial.game_id, trial.game_version,
                                   trial.objective_id, trial.situation_id) != scope):
                raise ValueError("trial identity mismatch")
            self._check_receipt(trial, receipt)
        except (TypeError, ValueError, PermissionError) as exc:
            raise sqlite3.IntegrityError("gameplay run receipt corrupted") from exc
        return (trial.split == "practice" and trial.action_id == action_id
                and earliest <= trial.observed_unix_s <= now
                and now - trial.observed_unix_s <= _PRACTICE_MAX_AGE_S)

    def suggest(self, game_id: str, game_version: str, objective_id: str,
                situation_id: str, *, now_unix_s: int,
                min_practice: int = 5, min_validation: int = 8,
                min_validation_lower_bound: float = 0.55) -> SkillSuggestion:
        """Conservative, strictly scoped advisory; never a live-play permission.

        Missing validation produces an offline rehearsal candidate only.
        A failed independent holdout cannot be overruled by practice success.
        """
        scope = self._scope(game_id, game_version, objective_id, situation_id)
        now = _seconds(now_unix_s)
        if (type(min_practice) is not int or not 5 <= min_practice <= 100
                or type(min_validation) is not int or not 8 <= min_validation <= 100
                or isinstance(min_validation_lower_bound, bool)
                or not isinstance(min_validation_lower_bound, (float, int))
                or not math.isfinite(min_validation_lower_bound)
                or not 0.55 <= min_validation_lower_bound <= 0.95):
            raise ValueError("invalid offline evidence thresholds")
        rows = self._db.execute(
            "SELECT trial_id, run_id, payload_json, receipt FROM gameplay_trials "
            "WHERE game_id=? AND game_version=? AND objective_id=? AND situation_id=?",
            scope,
        ).fetchall()
        by_action: dict[str, dict[str, list[str]]] = {}
        for trial_id, run_id, payload_json, receipt in rows:
            try:
                payload = json.loads(payload_json)
                if type(payload) is not dict:
                    raise ValueError("invalid trial JSON")
                trial = GameTrial(**payload)
                if (trial.trial_id != trial_id or trial.run_id != run_id
                        or self._scope(trial.game_id, trial.game_version,
                                       trial.objective_id, trial.situation_id) != scope):
                    raise ValueError("trial scope/identity mismatch")
                self._check_receipt(trial, receipt)
            except (TypeError, ValueError, PermissionError) as exc:
                raise sqlite3.IntegrityError("gameplay evidence ledger corrupted") from exc
            age = now - trial.observed_unix_s
            max_age = (_PRACTICE_MAX_AGE_S if trial.split == "practice"
                       else _VALIDATION_MAX_AGE_S)
            if not 0 <= age <= max_age:
                continue
            slots = by_action.setdefault(trial.action_id, {"practice": [], "validation": []})
            slots[trial.split].append(trial.outcome)

        ready: list[tuple[float, int, int, str]] = []
        rehearsal: list[tuple[float, int, str, int, float]] = []
        for action, splits in by_action.items():
            pn, vn = len(splits["practice"]), len(splits["validation"])
            ps = splits["practice"].count("success")
            vs = splits["validation"].count("success")
            plb = wilson_lower(ps, pn) if pn else 0.0
            vlb = wilson_lower(vs, vn) if vn else 0.0
            if pn >= min_practice and vn >= min_validation and vlb >= min_validation_lower_bound:
                ready.append((vlb, vn, pn, action))
            elif (pn >= min_practice and ps / pn >= 0.70
                  and (vn < min_validation or vlb >= min_validation_lower_bound)):
                rehearsal.append((plb, pn, action, vn, vlb))
        if ready:
            lb, vn, pn, action = sorted(ready, key=lambda x: (-x[0], -x[1], -x[2], x[3]))[0]
            return SkillSuggestion("ready_for_host_review", action, pn, vn, round(lb, 4),
                                   "independent signed validation met statistical review floor")
        if rehearsal:
            _p_lb, pn, action, vn, lb = sorted(
                rehearsal, key=lambda x: (-x[0], -x[1], x[2]))[0]
            return SkillSuggestion("rehearsal_only", action, pn, vn, round(lb, 4),
                                   "not enough independent validation for host review")
        return SkillSuggestion("no_evidence", None, 0, 0, 0.0,
                               "no eligible fresh evidence, or independent validation failed")
