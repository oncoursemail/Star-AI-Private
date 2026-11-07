"""Prospective, independently verified outcome forecasting for offline games.

STAR can improve *how it estimates its own chance of success*: predict before
acting, commit the estimate, then compare with an independently signed game
result. This is calibration/diagnostic infrastructure, NOT model-weight
training, causal inference, skill certification, or permission to play.

Only short bounded identifiers, probabilities, outcomes and times are stored;
never store screenshots, transcripts, viewer identities or evaluator keys.
Practice and validation/holdout data are deliberately separated. New features
remain OFF until enabled by the authorized local host.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from threading import RLock

from .gameplay_skill_bank import GameTrial, GameplaySkillBank

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_TIME = 10**11
_MAX_PENDING = 64
_MAX_ROWS = 20000
_MAX_OUTCOME_DELAY_S = 180


def _symbol(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded symbolic identifier")
    return value


def _time(value: object) -> int:
    if type(value) is not int or not 0 < value <= _MAX_TIME:
        raise ValueError("expected positive integer Unix seconds")
    return value


@dataclass(frozen=True)
class GameForecast:
    """An immutable prediction prepared BEFORE game action or observation.

    success_bps is a prospective probability of completing the objective,
    measured in integer basis points; this is never an action authorization.
    """
    game_id: str
    game_version: str
    objective_id: str
    situation_id: str
    action_id: str
    run_id: str
    model_id: str
    success_bps: int
    predicted_unix_s: int

    def __post_init__(self) -> None:
        for field in ("game_id", "game_version", "objective_id", "situation_id",
                      "action_id", "run_id", "model_id"):
            _symbol(getattr(self, field), field)
        if type(self.success_bps) is not int or not 1 <= self.success_bps <= 9999:
            raise ValueError("success_bps must be 1..9999, not a bool or float")
        _time(self.predicted_unix_s)


@dataclass(frozen=True)
class CalibrationReport:
    status: str
    trials: int
    brier_score: float | None
    expected_calibration_error: float | None
    mean_predicted: float | None
    observed_success: float | None
    # A baseline of 0.25 (always predicting 50%) is descriptive, not SOTA.
    reference_brier: float = 0.25


@dataclass(frozen=True)
class ForecastAdvice:
    status: str
    calibrated_success_bps: int | None
    bucket_trials: int
    reason: str
    authorized_to_play: bool = False


class GamePredictionLab:
    """SQLite-backed, bounded prospective probability-quality ledger.

    The trusted embedding host alone can enable this component, precommit a
    model's prediction before dispatch, and submit the exact signed GameTrial.
    The GameplaySkillBank verifies the ledger's independent host signature
    BEFORE a resolved prediction can influence reports or future advice.
    """

    def __init__(self, bank: GameplaySkillBank, database: str | Path = ":memory:") -> None:
        if not isinstance(bank, GameplaySkillBank):
            raise TypeError("existing signed GameplaySkillBank required")
        db_path = str(database)
        if (not db_path or (db_path != ":memory:"
                            and (Path(db_path).is_symlink()
                                 or Path(db_path).parent.is_symlink()
                                 or not Path(db_path).parent.is_dir()))):
            raise ValueError("database path requires an existing non-symlink directory")
        self._bank = bank
        self._db = sqlite3.connect(db_path, isolation_level=None, timeout=10)
        self._db.execute("PRAGMA trusted_schema=OFF")
        self._db.execute("""CREATE TABLE IF NOT EXISTS forecast_runs (
            run_id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            game_version TEXT NOT NULL,
            objective_id TEXT NOT NULL,
            situation_id TEXT NOT NULL,
            action_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            success_bps INTEGER NOT NULL CHECK(success_bps BETWEEN 1 AND 9999),
            predicted_unix_s INTEGER NOT NULL,
            outcome INTEGER CHECK(outcome IN (0, 1)),
            status TEXT NOT NULL CHECK(status IN ('pending', 'verified', 'cancelled')),
            verified_unix_s INTEGER
        )""")
        self._db.execute("""CREATE INDEX IF NOT EXISTS forecast_model_scope
            ON forecast_runs(model_id, game_id, game_version, status)""")
        self._lock = RLock()
        self._enabled = False
        self._counts = dict(committed=0, duplicate=0, rejected=0,
                            verified=0, stale=0)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> "GamePredictionLab":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("independent local host must explicitly opt in")
        with self._lock:
            if self._enabled:
                raise RuntimeError("forecast lab already enabled")
            self._enabled = True

    def disable(self) -> None:
        """Do not allow pending predictions from an old session to be replayed."""
        with self._lock:
            self._enabled = False
            self._db.execute("UPDATE forecast_runs SET status='cancelled' WHERE status='pending'")

    def precommit(self, forecast: GameForecast, *, now_unix_s: int) -> bool:
        if not isinstance(forecast, GameForecast):
            raise TypeError("expected GameForecast")
        now = _time(now_unix_s)
        with self._lock:
            if not self._enabled or abs(now - forecast.predicted_unix_s) > 1:
                self._counts["rejected"] += 1
                return False
            # A trial that is ALREADY recorded is never eligible for a new
            # prediction (including a result from this same Unix second).
            if self._bank.signed_practice_run(
                forecast.game_id, forecast.game_version,
                forecast.objective_id, forecast.situation_id,
                forecast.action_id, forecast.run_id,
                not_before_unix_s=1, now_unix_s=now,
            ):
                self._counts["rejected"] += 1
                return False
            if self._db.execute(
                "SELECT 1 FROM forecast_runs WHERE run_id=?", (forecast.run_id,)
            ).fetchone():
                self._counts["duplicate"] += 1
                return False
            pending, total = self._db.execute(
                "SELECT SUM(status='pending'), COUNT(*) FROM forecast_runs"
            ).fetchone()
            if (pending or 0) >= _MAX_PENDING or total >= _MAX_ROWS:
                self._counts["rejected"] += 1
                return False
            self._db.execute("""INSERT INTO forecast_runs
                (run_id, game_id, game_version, objective_id, situation_id,
                 action_id, model_id, success_bps, predicted_unix_s, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (forecast.run_id, forecast.game_id, forecast.game_version,
                 forecast.objective_id, forecast.situation_id, forecast.action_id,
                 forecast.model_id, forecast.success_bps, forecast.predicted_unix_s))
            self._counts["committed"] += 1
            return True

    def cancel(self, run_id: str) -> bool:
        """Discard an unexecuted forecast; its run ID remains non-reusable."""
        _symbol(run_id, "run_id")
        with self._lock:
            changed = self._db.execute(
                "UPDATE forecast_runs SET status='cancelled' "
                "WHERE run_id=? AND status='pending'", (run_id,)
            ).rowcount
            return changed == 1

    def resolve(self, trial: GameTrial, *, now_unix_s: int) -> bool:
        """Learn from a committed forecast ONLY after signed PRACTICE truth.

        A forged outcome, mismatched run, delayed result, held-out result,
        or duplicate report can never update forecast accuracy.
        """
        if not isinstance(trial, GameTrial):
            raise TypeError("expected GameTrial")
        now = _time(now_unix_s)
        with self._lock:
            if not self._enabled or trial.split != "practice":
                self._counts["rejected"] += 1
                return False
            row = self._db.execute("""SELECT game_id, game_version, objective_id,
                    situation_id, action_id, predicted_unix_s, status
                    FROM forecast_runs WHERE run_id=?""", (trial.run_id,)).fetchone()
            if row is None or row[6] != "pending":
                self._counts["rejected"] += 1
                return False
            if tuple(row[:5]) != (trial.game_id, trial.game_version,
                                  trial.objective_id, trial.situation_id, trial.action_id):
                self._counts["rejected"] += 1
                return False
            predicted_at = row[5]
            if (trial.observed_unix_s < predicted_at
                    or trial.observed_unix_s > now
                    or now - predicted_at > _MAX_OUTCOME_DELAY_S):
                self._counts["stale"] += 1
                self._db.execute("""UPDATE forecast_runs SET status='cancelled'
                    WHERE run_id=? AND status='pending'""", (trial.run_id,))
                return False
            if not self._bank.verify_practice_trial(trial, now_unix_s=now):
                self._counts["rejected"] += 1
                return False
            self._db.execute("""UPDATE forecast_runs
                SET status='verified', outcome=?, verified_unix_s=?
                WHERE run_id=? AND status='pending'""",
                (int(trial.outcome == "success"), now, trial.run_id))
            self._counts["verified"] += 1
            return True

    def _verified_rows(self, model_id: str, game_id: str | None,
                       game_version: str | None) -> list[tuple[int, int]]:
        _symbol(model_id, "model_id")
        if game_version is not None and game_id is None:
            raise ValueError("game_version needs an explicit game_id")
        if game_id is not None:
            _symbol(game_id, "game_id")
        if game_version is not None:
            _symbol(game_version, "game_version")
        query = ("SELECT success_bps, outcome FROM forecast_runs "
                 "WHERE status='verified' AND model_id=?")
        params: list[str] = [model_id]
        if game_id is not None:
            query += " AND game_id=?"
            params.append(game_id)
        if game_version is not None:
            query += " AND game_version=?"
            params.append(game_version)
        return list(self._db.execute(query, params))

    def report(self, model_id: str, *, game_id: str | None = None,
               game_version: str | None = None) -> CalibrationReport:
        """Five-bin ECE and Brier are diagnostics, NOT a held-out benchmark."""
        with self._lock:
            rows = self._verified_rows(model_id, game_id, game_version)
            n = len(rows)
            if not n:
                return CalibrationReport("no_verified_forecasts", 0, None, None, None, None)
            buckets = [[0.0, 0.0, 0] for _ in range(5)]
            brier = predicted = observed = 0.0
            for basis_points, outcome in rows:
                p = basis_points / 10000.0
                brier += (p - outcome) ** 2
                predicted += p
                observed += outcome
                bucket = buckets[min(4, basis_points // 2000)]
                bucket[0] += p
                bucket[1] += outcome
                bucket[2] += 1
            ece = sum((count / n) * abs(p_sum / count - y_sum / count)
                      for p_sum, y_sum, count in buckets if count)
            status = "diagnostic_only_small_sample" if n < 20 else "prospective_diagnostic"
            return CalibrationReport(status, n, brier / n, ece,
                                     predicted / n, observed / n)

    def advise(self, model_id: str, *, game_id: str,
               game_version: str, proposed_bps: int) -> ForecastAdvice:
        """Suggest an evidence-shrunk calibration for FUTURE offline forecasts.

        No advice before 20 prospective trials AND eight in the probability
        bucket. Never use retrospective corrected probabilities as evidence
        that the underlying model became smarter or mastered the game.
        """
        if type(proposed_bps) is not int or not 1 <= proposed_bps <= 9999:
            raise ValueError("proposed_bps must be 1..9999")
        with self._lock:
            rows = self._verified_rows(model_id, game_id, game_version)
            if len(rows) < 20:
                return ForecastAdvice("insufficient_evidence", None, 0,
                                      "requires_20_future_verified_trials")
            bucket = min(4, proposed_bps // 2000)
            selected = [outcome for bps, outcome in rows
                        if min(4, bps // 2000) == bucket]
            if len(selected) < 8:
                return ForecastAdvice("uncertain_probability_bucket", None,
                                      len(selected), "requires_8_in_bucket")
            # Beta(2, 2) shrinkage avoids falsely certain 0/100% estimates.
            adjusted = round(10000 * (sum(selected) + 2) / (len(selected) + 4))
            return ForecastAdvice("reviewable_calibration", max(1, min(9999, adjusted)),
                                  len(selected), "practice_only_no_holdout_claim")

    def metrics(self) -> dict[str, int | bool]:
        with self._lock:
            pending, resolved = self._db.execute("""SELECT
                SUM(status='pending'), SUM(status='verified') FROM forecast_runs""").fetchone()
            return {**self._counts, "enabled": self._enabled,
                    "pending": pending or 0, "persisted_verified": resolved or 0}


__all__ = ["GameForecast", "CalibrationReport", "ForecastAdvice", "GamePredictionLab"]
