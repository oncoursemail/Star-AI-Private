"""Private USD allowance ledger; no bank connection or payment execution.

Only trusted host code may configure limits, attest quotes/funding/receipts or
call reconciliation methods. None of these methods is exposed as a model tool.
An allowance is accounting, not proof of funds held at a financial institution.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from time import time
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Chicago")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _id(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError("Expected a bounded opaque identifier, without credentials")
    return value


def _cents(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 10**12:
        raise ValueError("USD amounts must be integer cents in range")
    return value


@dataclass(frozen=True)
class Policy:
    enabled: bool = False
    provider: str = ""
    account: str = ""
    budget_cents: int = 0
    per_purchase_cents: int = 0
    daily_cents: int = 0

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be boolean")
        for value in (self.budget_cents, self.per_purchase_cents, self.daily_cents):
            _cents(value, zero=True)
        if self.provider or self.account or self.enabled:
            _id(self.provider)
            _id(self.account)
        if self.enabled and not all((self.budget_cents, self.per_purchase_cents, self.daily_cents)):
            raise ValueError("Configure nonzero limits before enabling an allowance")


@dataclass(frozen=True)
class Quote:
    """Host-attested all-in USD quote; its constructor performs no verification."""
    provider: str
    account: str
    merchant: str
    quote_id: str
    cents: int
    expires_at: float

    def __post_init__(self):
        for value in (self.provider, self.account, self.merchant, self.quote_id):
            _id(value)
        _cents(self.cents)
        if type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at) or self.expires_at <= 0:
            raise ValueError("Quote requires a finite expiry timestamp")


class Wallet:
    def __init__(self, database: Path, *, clock=time, read_only: bool = False):
        database = Path(database)
        if type(read_only) is not bool:
            raise ValueError("read_only must be boolean")
        if database.is_symlink() or (database.exists() and not database.is_file()):
            raise PermissionError("Use an ordinary private local database file")
        if any((p / ".git").exists() for p in database.resolve().parents):
            raise PermissionError("Wallet records must remain outside Git checkouts")
        self.clock = clock
        self._read_only = read_only
        if read_only:
            if not database.is_file():
                raise ValueError("Inspect requires an existing wallet database")
            self.db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True,
                                      timeout=10, isolation_level=None)
        else:
            self.db = sqlite3.connect(database, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        if read_only:
            return
        if os.name == "posix":
            os.chmod(database, 0o600)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations(
                id TEXT PRIMARY KEY, quote TEXT NOT NULL, cents INTEGER NOT NULL,
                state TEXT NOT NULL, day TEXT NOT NULL, refunded INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS receipts(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, reservation TEXT NOT NULL, cents INTEGER NOT NULL);
        """)
        self.db.execute("INSERT OR IGNORE INTO policy VALUES(1,?)", (json.dumps(asdict(Policy())),))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.db.close()

    @contextmanager
    def _tx(self):
        self.db.execute("BEGIN" if self._read_only else "BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def policy(self):
        return Policy(**json.loads(self.db.execute("SELECT payload FROM policy WHERE id=1").fetchone()[0]))

    def configure(self, policy: Policy):
        """Owner-side configuration only; never grant this method to a model."""
        if not isinstance(policy, Policy):
            raise TypeError("Expected an owner-configured Policy")
        with self._tx():
            old = self.policy()
            used = self.db.execute("SELECT count(*) FROM receipts").fetchone()[0]
            used += self.db.execute("SELECT count(*) FROM reservations").fetchone()[0]
            if used and (old.provider, old.account) != (policy.provider, policy.account):
                raise ValueError("Use a separate ledger for another provider or account")
            self.db.execute("UPDATE policy SET payload=? WHERE id=1", (json.dumps(asdict(policy)),))

    def _receipt(self, receipt, kind, reservation, cents):
        _id(receipt)
        row = self.db.execute("SELECT kind,reservation,cents FROM receipts WHERE id=?", (receipt,)).fetchone()
        if row:
            if tuple(row) != (kind, reservation, cents):
                raise ValueError("Receipt already belongs to another operation")
            return False
        self.db.execute("INSERT INTO receipts VALUES(?,?,?,?)", (receipt, kind, reservation, cents))
        return True

    def fund(self, cents: int, *, receipt: str):
        """Record a provider-confirmed incoming credit; this does not transfer funds."""
        _cents(cents)
        with self._tx():
            p = self.policy()
            if not p.account or not p.provider:
                raise PermissionError("Select the owner-funded account first")
            return self._receipt(receipt, "fund", "", cents)

    def _totals(self):
        credited = self.db.execute("SELECT coalesce(sum(cents),0) FROM receipts WHERE kind IN ('fund','refund')").fetchone()[0]
        spent = self.db.execute("SELECT coalesce(sum(cents),0) FROM reservations WHERE state='settled'").fetchone()[0]
        held = self.db.execute("SELECT coalesce(sum(cents),0) FROM reservations WHERE state IN ('reserved','submitted')").fetchone()[0]
        refunds = self.db.execute("SELECT coalesce(sum(cents),0) FROM receipts WHERE kind='refund'").fetchone()[0]
        day = datetime.fromtimestamp(self.clock(), ZONE).date().isoformat()
        gross_today = self.db.execute("SELECT coalesce(sum(cents),0) FROM reservations WHERE state='settled' AND day=?", (day,)).fetchone()[0]
        return credited, spent, held, refunds, gross_today, day

    def reserve(self, action_id: str, quote: Quote):
        """Reserve an immutable host-verified quote with stable idempotency key."""
        _id(action_id)
        if not isinstance(quote, Quote):
            raise TypeError("Host must supply a verified Quote")
        raw = json.dumps(asdict(quote), sort_keys=True)
        with self._tx():
            row = self.db.execute("SELECT quote FROM reservations WHERE id=?", (action_id,)).fetchone()
            if row:
                if row[0] != raw:
                    raise ValueError("Action id is already bound to another quote")
                return False
            p = self.policy()
            if not p.enabled or (p.provider, p.account) != (quote.provider, quote.account):
                raise PermissionError("Allowance disabled or account does not match")
            if quote.expires_at <= self.clock():
                raise ValueError("Quote expired")
            credit, spent, held, refunds, today, day = self._totals()
            room = min(credit - spent - held, p.budget_cents - spent + refunds - held,
                       p.daily_cents - today - held, p.per_purchase_cents)
            if quote.cents > room:
                raise PermissionError("Quote exceeds funded allowance or purchase/daily/budget cap")
            self.db.execute("INSERT INTO reservations(id,quote,cents,state,day) VALUES(?,?,?,'reserved',?)",
                            (action_id, raw, quote.cents, day))
            return True

    def _row(self, action_id):
        _id(action_id)
        row = self.db.execute("SELECT * FROM reservations WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown reservation")
        return row

    def mark_submitted(self, action_id: str):
        """Durably mark BEFORE a host submits once; False means never submit again.

        After a crash or unknown provider outcome, reconcile using action_id.
        There is no timeout-based release and no automatic payment retry here.
        """
        with self._tx():
            row = self._row(action_id)
            if row["state"] != "reserved":
                return False
            p = self.policy()
            if not p.enabled or json.loads(row["quote"])["expires_at"] <= self.clock():
                raise PermissionError("Allowance disabled or quote expired before submission")
            credit, spent, held, refunds, today, _ = self._totals()
            if (row["cents"] > p.per_purchase_cents or spent + held > credit
                    or spent - refunds + held > p.budget_cents or today + held > p.daily_cents):
                raise PermissionError("Current owner limits no longer cover the reservation")
            day = datetime.fromtimestamp(self.clock(), ZONE).date().isoformat()
            self.db.execute("UPDATE reservations SET state='submitted',day=? WHERE id=?", (day, action_id))
            return True

    def settle(self, action_id: str, *, cents: int, receipt: str):
        """Host confirms a final exact USD charge; unknown/partial outcomes stay held."""
        _cents(cents)
        with self._tx():
            row = self._row(action_id)
            if cents != row["cents"] or row["state"] not in ("submitted", "settled"):
                raise ValueError("Charge does not match a submitted reservation")
            fresh = self._receipt(receipt, "settle", action_id, cents)
            if fresh and row["state"] != "submitted":
                raise ValueError("Reservation already has a different settlement receipt")
            self.db.execute("UPDATE reservations SET state='settled' WHERE id=?", (action_id,))
            return fresh

    def cancel(self, action_id: str, *, receipt: str = ""):
        """Release an unsent reservation; submitted payments need confirmed void proof."""
        with self._tx():
            row = self._row(action_id)
            if row["state"] == "cancelled":
                if receipt:
                    if not self._receipt(receipt, "cancel", action_id, 0):
                        return False
                    raise ValueError("Cancellation already recorded")
                return False
            if row["state"] not in ("reserved", "submitted") or (row["state"] == "submitted" and not receipt):
                raise ValueError("Submitted reservations need provider-confirmed cancellation")
            if receipt:
                self._receipt(receipt, "cancel", action_id, 0)
            self.db.execute("UPDATE reservations SET state='cancelled' WHERE id=?", (action_id,))
            return True

    def refund(self, action_id: str, *, cents: int, receipt: str):
        """Credit only an authoritative completed refund, never a pending refund request."""
        _cents(cents)
        with self._tx():
            row = self._row(action_id)
            fresh = self._receipt(receipt, "refund", action_id, cents)
            if not fresh:
                return False
            if row["state"] != "settled" or row["refunded"] + cents > row["cents"]:
                raise ValueError("Refund exceeds the settled charge")
            self.db.execute("UPDATE reservations SET refunded=refunded+? WHERE id=?", (cents, action_id))
            return True

    def status(self):
        with self._tx():
            credit, spent, held, refunds, today, day = self._totals()
            p = self.policy()
            room = min(credit - spent - held, p.budget_cents - spent + refunds - held,
                       p.daily_cents - today - held, p.per_purchase_cents) if p.enabled else 0
            return {"currency": "USD", "timezone": ZONE.key, "day": day, "enabled": p.enabled,
                    "funded_cents": credit - refunds, "spent_cents": spent, "refunded_cents": refunds,
                    "held_cents": held, "available_cents": max(0, credit - spent - held),
                    "daily_committed_cents": today + held, "spendable_cents": max(0, room), "policy": asdict(p),
                    "pending": [dict(r) for r in self.db.execute("SELECT id,state,cents,day FROM reservations"
                                " WHERE state IN ('reserved','submitted') ORDER BY id LIMIT 100")]}


def cli():
    parser = argparse.ArgumentParser(description="Local allowance accounting; no payment provider is connected")
    parser.add_argument("command", choices=("inspect", "simulate"))
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    if args.command == "inspect":
        if args.database is None or not args.database.is_file():
            parser.error("inspect requires an existing private --database")
        with Wallet(args.database, read_only=True) as wallet:
            print(json.dumps(wallet.status(), indent=2))
    else:
        with tempfile.TemporaryDirectory(prefix="star-wallet-simulation-") as folder:
            with Wallet(Path(folder) / "simulation.sqlite3") as wallet:
                wallet.configure(Policy(True, "simulation", "owner-funded", 2000, 500, 1000))
                wallet.fund(2000, receipt="simulated-credit")
                wallet.reserve("simulated-order", Quote("simulation", "owner-funded", "sample-shop", "sample-quote", 300, time() + 60))
                wallet.mark_submitted("simulated-order")
                wallet.settle("simulated-order", cents=300, receipt="simulated-charge")
                print(json.dumps({"simulation_only": True, **wallet.status()}, indent=2))


if __name__ == "__main__":
    cli()
