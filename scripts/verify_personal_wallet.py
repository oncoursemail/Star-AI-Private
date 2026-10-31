"""Offline allowance regressions; run with ``python scripts/verify_personal_wallet.py``.

Every provider attestation is fake. Databases are disposable, outside the source
tree. No account, network, credential, payment or harness fixture is used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from star.personal_wallet import Policy, Quote, Wallet, ZONE  # noqa: E402


class Checks:
    def __init__(self):
        self.count = 0

    def check(self, condition):
        if not condition:
            raise AssertionError(f"Wallet check {self.count + 1} failed")
        self.count += 1

    def refused(self, operation, errors=(ValueError, PermissionError)):
        try:
            operation()
        except errors:
            self.count += 1
        else:
            raise AssertionError(f"Wallet check {self.count + 1}: expected refusal")


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 25, 12, tzinfo=ZONE).timestamp()

    def __call__(self):
        return self.now


def verify(folder: Path, checks: Checks):
    check, refused = checks.check, checks.refused
    clock = Clock()
    policy = Policy(True, "test-provider", "test-account", 1000, 800, 1000)

    def quote(cents=600, *, ident="quote", expiry=None):
        return Quote(policy.provider, policy.account, "test-merchant", ident, cents,
                     clock.now + 86400 if expiry is None else expiry)

    path = folder / "ledger.sqlite3"
    with Wallet(path, clock=clock) as wallet:
        check(not wallet.policy().enabled)
        check(wallet.status()["spendable_cents"] == 0)
        refused(lambda: wallet.reserve("disabled", quote()))
        refused(lambda: wallet.fund(1000, receipt="no-account"))
        wallet.configure(policy)
        refused(lambda: wallet.reserve("unfunded", quote()))
        check(wallet.fund(1000, receipt="fund-1"))
        check(not wallet.fund(1000, receipt="fund-1"))
        refused(lambda: wallet.fund(999, receipt="fund-1"))
        refused(lambda: wallet.fund(True, receipt="invalid"))
        refused(lambda: wallet.reserve("too-big", quote(801)))
        refused(lambda: wallet.reserve("expired", quote(expiry=clock.now - 1)))
        refused(lambda: wallet.reserve("wrong-account", replace(quote(), account="other")))
        fixed_quote = quote()
        check(wallet.reserve("buy-1", fixed_quote))
        check(not wallet.reserve("buy-1", fixed_quote))
        refused(lambda: wallet.reserve("buy-1", quote(601)))
        check(wallet.status()["held_cents"] == 600)
        check(wallet.mark_submitted("buy-1"))
        check(not wallet.mark_submitted("buy-1"))
        refused(lambda: wallet.cancel("buy-1"))
        refused(lambda: wallet.settle("buy-1", cents=599, receipt="charge-1"))
        check(wallet.status()["held_cents"] == 600)

    with Wallet(path, clock=clock) as wallet:
        status = wallet.status()
        check(status["held_cents"] == 600 and status["pending"][0]["state"] == "submitted")
        check(not wallet.mark_submitted("buy-1"))
        check(wallet.settle("buy-1", cents=600, receipt="charge-1"))
        check(not wallet.settle("buy-1", cents=600, receipt="charge-1"))
        refused(lambda: wallet.settle("buy-1", cents=600, receipt="different-charge"))
        check(wallet.refund("buy-1", cents=200, receipt="refund-1"))
        check(not wallet.refund("buy-1", cents=200, receipt="refund-1"))
        refused(lambda: wallet.refund("buy-1", cents=401, receipt="excess-refund"))
        refused(lambda: wallet.refund("buy-1", cents=200, receipt="charge-1"))
        check(wallet.refund("buy-1", cents=400, receipt="refund-2"))
        check(wallet.status()["available_cents"] == 1000)
        check(wallet.status()["daily_committed_cents"] == 600)
        refused(lambda: wallet.reserve("daily-cap", quote(401)))
        check(wallet.reserve("unsent", quote(100, ident="q2")))
        check(wallet.cancel("unsent"))
        check(not wallet.cancel("unsent"))
        check(wallet.reserve("voided", quote(100, ident="q3")))
        check(wallet.mark_submitted("voided"))
        check(wallet.cancel("voided", receipt="confirmed-void"))
        check(not wallet.cancel("voided", receipt="confirmed-void"))
        refused(lambda: wallet.configure(replace(policy, account="different")))
        check(wallet.reserve("policy-change", quote(100, ident="q4")))
        wallet.configure(replace(policy, per_purchase_cents=50))
        refused(lambda: wallet.mark_submitted("policy-change"))
        wallet.configure(replace(policy, enabled=False))
        refused(lambda: wallet.mark_submitted("policy-change"))
        check(wallet.status()["spendable_cents"] == 0)
        wallet.cancel("policy-change")

    # Both contenders have separate connections and begin from the same funded allowance.
    racepath = folder / "race.sqlite3"
    with Wallet(racepath, clock=clock) as wallet:
        wallet.configure(policy)
        wallet.fund(1000, receipt="fund")
    barrier = Barrier(2)

    def reserve_race(index):
        with Wallet(racepath, clock=clock) as wallet:
            barrier.wait(timeout=10)
            try:
                return wallet.reserve("race-" + str(index), quote(600, ident="race-quote"))
            except PermissionError:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        check(sum(pool.map(reserve_race, range(2))) == 1)
    with Wallet(racepath, clock=clock) as wallet:
        check(wallet.status()["held_cents"] == 600)
        action_id = wallet.status()["pending"][0]["id"]
    barrier = Barrier(2)

    def submit_race(_index):
        with Wallet(racepath, clock=clock) as wallet:
            barrier.wait(timeout=10)
            return wallet.mark_submitted(action_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        check(sum(pool.map(submit_race, range(2))) == 1)
    with Wallet(racepath, clock=clock) as wallet:
        clock.now = datetime(2026, 10, 26, 0, 1, tzinfo=ZONE).timestamp()
        check(wallet.status()["day"] == "2026-10-26")
        refused(lambda: wallet.reserve("next-day", quote(401)))
        check(wallet.status()["held_cents"] == 600)

    with Wallet(folder / "expiry.sqlite3", clock=clock) as wallet:
        wallet.configure(policy)
        wallet.fund(1000, receipt="fund")
        wallet.reserve("expires", quote(100, expiry=clock.now + 1))
        clock.now += 2
        refused(lambda: wallet.mark_submitted("expires"))
        check(wallet.status()["held_cents"] == 100)
        wallet.cancel("expires")
        check(wallet.status()["held_cents"] == 0)

    # The total budget is independent of both funding and the daily cap.
    with Wallet(folder / "budget.sqlite3", clock=clock) as wallet:
        wallet.configure(replace(policy, budget_cents=500, per_purchase_cents=1000, daily_cents=2000))
        wallet.fund(5000, receipt="fund")
        refused(lambda: wallet.reserve("over-budget", quote(501)))
        check(wallet.reserve("under-budget", quote(500)))
        wallet.mark_submitted("under-budget")
        wallet.settle("under-budget", cents=500, receipt="settled")
        clock.now += 86400
        refused(lambda: wallet.reserve("next-day-over-budget", quote(1)))
        wallet.refund("under-budget", cents=100, receipt="refund")
        check(wallet.reserve("refunded-room", quote(100)))

    # Read-only inspection must not initialize, chmod or alter an existing ledger.
    before = path.read_bytes(), path.stat().st_mtime_ns
    with Wallet(path, clock=clock, read_only=True) as wallet:
        check(wallet.status()["funded_cents"] == 1000)
        refused(lambda: wallet.fund(1, receipt="readonly-write"), sqlite3.OperationalError)
    check((path.read_bytes(), path.stat().st_mtime_ns) == before)
    output = subprocess.run([sys.executable, "-m", "star.personal_wallet", "inspect", "--database", str(path)],
                            cwd=ROOT, capture_output=True, text=True, timeout=15, check=True)
    check(json.loads(output.stdout)["funded_cents"] == 1000)
    check((path.read_bytes(), path.stat().st_mtime_ns) == before)
    missing = folder / "not-created.sqlite3"
    refused(lambda: Wallet(missing, read_only=True))
    check(not missing.exists())
    uninitialized = folder / "uninitialized.sqlite3"
    with closing(sqlite3.connect(uninitialized)) as db:
        db.execute("CREATE TABLE unrelated(id INTEGER)")
        db.commit()
    before = uninitialized.read_bytes(), uninitialized.stat().st_mtime_ns
    with Wallet(uninitialized, read_only=True) as wallet:
        refused(wallet.status, sqlite3.OperationalError)
    check((uninitialized.read_bytes(), uninitialized.stat().st_mtime_ns) == before)

    # Both folds of Chicago's DST fallback belong to the same calendar day.
    with Wallet(path, clock=clock, read_only=True) as wallet:
        clock.now = datetime(2026, 11, 1, 1, 30, tzinfo=ZONE, fold=0).timestamp()
        first = wallet.status()["day"]
        clock.now = datetime(2026, 11, 1, 1, 30, tzinfo=ZONE, fold=1).timestamp()
        check(wallet.status()["day"] == first == "2026-11-01")


def main():
    checks = Checks()
    with TemporaryDirectory(prefix="star-wallet-verification-") as folder:
        verify(Path(folder), checks)
    print(f"Wallet verification: {checks.count} checks passed; simulated attestations only, no money actions.")


if __name__ == "__main__":
    main()
