# STAR personal allowance ledger

Owner intent: fund STAR's own personal spending allowance and let her choose
purchases within it. `star/personal_wallet.py` provides private, durable USD
accounting for a future owner-selected account adapter. It does not open a bank
account, move funds, connect Stripe, enter checkout details, or enable purchases.
Current computer-use and commerce approval paths are unchanged.

## Implemented

`Policy` persists an explicit enabled flag, opaque provider/account references,
net total budget, per-purchase limit and daily limit. Defaults are disabled and
zero. `configure()` belongs to owner-side code; none of this API is registered
as a model tool. Once records exist, changing the account requires a separate
ledger. No credentials belong in these references or in the database.

`fund(cents, receipt=...)` records a deposit already confirmed by a trusted host
adapter. It cannot determine a real account balance. Every amount is integer USD
cents; floats, booleans, negative amounts and values over the defined ceiling
are refused. The database must live outside Git checkouts.

`reserve(action_id, Quote(...))` checks a host-verified all-in quote, its expiry,
account binding, recorded funding and all caps in one SQLite write transaction.
The total must include taxes, shipping and fees. `Quote` is a data contract:
constructing it does not verify a merchant, authorize spending, or attest funds.
Use stable host-assigned action identifiers; quote drift under an existing id
is refused and repeating an identical reservation is a no-op.

`mark_submitted(action_id)` commits the pending state **before** the host would
submit a transaction; only a `True` return can permit one submission. It rechecks
current owner limits and expiry. `False` must never cause another submission.
A crash between this commit and a provider response leaves funds held. There
is no automatic expiry, release or retry of submitted payments.

`settle`, `cancel` and `refund` only record authoritative host-verified outcomes:

- Settlement requires the exact reserved amount and a unique final charge
  receipt. Partial or mismatched charges remain pending for reconciliation.
- An unsent reservation can be cancelled locally. A submitted reservation needs
  provider-confirmed cancellation proof before funds become available again.
- Refunds count only after completion is confirmed; partial refunds are allowed,
  up to the original charge. A refund request or pending status is not a credit.
- Receipt identifiers are unique across deposit, settlement, cancellation and
  refund operations. Identical retries are no-ops; changed or reused receipts
  are rejected. A second settlement receipt cannot charge the same reservation.

Daily accounting explicitly uses `America/Chicago` calendar dates. All active
holds, including yesterday's unresolved payments, count against today's cap.
Settled purchases count on the submission day. Refunds restore recorded funds
and net total budget, while gross daily expenditure remains consumed to avoid
refund/rebuy churn. `status()` separates available recorded funds from the
amount currently spendable under policy, and lists pending action identifiers.

The reusable API intentionally contains **no execute callback**: without a
selected provider, account and authenticated receipt verification, it cannot
reliably verify an external payment. A future host adapter must enforce its
existing executable permissions, verify quote/receipt amount, currency,
merchant and account, persist the action id at the provider, reconcile uncertain
outcomes, and keep account secrets in OS storage. Local idempotency is not a
transaction spanning a remote service. The ledger does not itself prevent an
unrelated application or person spending money from the real account.

## Research and existing implementation

- [SQLite transaction documentation](https://www.sqlite.org/lang_transaction.html)
  documents serialization of writes and `BEGIN IMMEDIATE`; the ledger uses that
  transaction before reading balances and reserving funds. Separate connections
  cannot both reserve the same remaining allowance.
- [Stripe idempotency documentation](https://docs.stripe.com/api/idempotent_requests)
  describes stable request identifiers and rejecting parameter drift. Provider
  retention can be limited, so a durable local receipt record is still needed.
  This is design evidence, not a selected Stripe integration.
- [Payment lifecycle](https://docs.stripe.com/payments/paymentintents/lifecycle)
  distinguishes pending/authentication states from completed payment. An
  unknown response cannot safely release a reservation.
- [Refund documentation](https://docs.stripe.com/refunds) distinguishes completed
  and pending refunds and permits partial refunds within the original amount.
  Pending requests cannot be counted as available allowance.
- [Windows credential management](https://learn.microsoft.com/en-us/windows/win32/secauthn/credentials-management)
  documents OS-managed credential APIs. Existing `star/bulk_profiles.py`
  `OSProfileSecrets` already restricts persistent secrets to secure OS keyring
  backends; `star/providers.py` uses keyring. `star/brain_vault.py` is a notes
  export, **not** a password vault. Wallet code stores no passwords or keys.
- Existing `star/commerce/approvals.py` remains the separate owner approval queue
  for business actions. Personal allowance accounting does not bypass it.

## Use and validation

`python -m star.personal_wallet simulate` runs a complete local fake funding,
reservation, submission and settlement in a disposable temporary directory.
It prints `simulation_only: true` and never contacts a provider.

`python -m star.personal_wallet inspect --database <private-ledger.sqlite3>`
shows an existing local ledger. There is no CLI to configure a live account,
mint a deposit, submit payment or open a bank account.

`python scripts/verify_personal_wallet.py`: **69 checks passed**, including independent concurrent
reservation and submission races, restart with unknown submitted outcome,
receipt collisions, duplicate retries, partial/full/over-refunds, quote/account
drift, zero funding, disabled policy, lowered limits, expired quotes and
Chicago midnight rollover, DST fallback and read-only CLI inspection. Existing commerce approval and Windows packaging
regressions: **29 passed in 10.62 seconds**. Compilation, Ruff and whitespace
checks passed.
All provider attestations were fake; no real account, funds or external service
was used. No tests, grading code or evaluation fixtures were edited.

Windows needs IANA timezone data (`tzdata`, already in requirements). The local
verification interpreter lacked that installed dependency; it was installed
before running the checks. No dependency file was changed.
