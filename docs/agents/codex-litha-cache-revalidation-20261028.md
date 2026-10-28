# Preserve replacements during background cache verification

Branch: `codex/litha-cache-revalidation-20261028`, based on `7cea7eea`.

A cached answer can be replaced while its background verifier request is pending. Previously `_reverify` updated or deleted by row ID alone: an old failure could delete a freshly verified replacement, and an old success could refresh it without checking its content. A compare against only content and wall-clock timestamps also admits an A → B → A replacement when timestamps repeat.

The cache now stores an opaque revision token. Every `put`, legacy `reverified`, and accepted conditional revalidation generates a new token. Background work receives a copy of the original row and retains the same cache instance across its await. Success or failure applies through one conditional SQLite statement matching revision and stable snapshot fields. Mutable hit counts are excluded. Failed comparisons leave the row, vector index, canonical mapping, and drop counter untouched. A successful delete updates the existing local vector/canonical bookkeeping afterward.

This does not add routing, inference, prompts, model settings, deployment, authentication, source logging, persistent repair caching, or a quality score. Revalidation remains background work; this change does not prevent already-selected old answers from being served under the existing stale-while-revalidate policy. Duplicate background requests are not coalesced here. Cancellation before the verifier returns cannot apply a verdict, but the pre-existing `verify_ok` transport cleanup limitation on cancellation is outside this patch.

## Database compatibility and rollback

The source adds a `revision TEXT NOT NULL DEFAULT ''` column when opening an older answer-cache database, with schema inspection and migration serialized under `BEGIN IMMEDIATE`. Existing answers, scores, timestamps, hits, and embeddings remain. Migration failure rolls back and closes its connection. New writes use UUID tokens; they identify generations and do not authenticate the verifier or its verdict.

Only temporary synthetic databases were migrated in these checks. No live database was opened or migrated, and no target was deployed. Before a later authorized rollout, stop cache writers and back up the SQLite database using a consistent SQLite backup or checkpointed offline copy. Preserve the original backup if reverting to the old schema is necessary; do not drop the column from a live database. Older readers select their known columns and can ignore the additive column, but old writers do not rotate revisions. The guarantee therefore assumes **all writers use the upgraded mutation paths**. Running old and new writers together is unsupported. Conditional SQL was checked through two connections; this does not introduce cross-process synchronization of the separate in-memory vector indexes or a general multithreaded cache contract.

## Retained evidence

Run:

```powershell
python scripts/verify_mesh_cache_revalidation.py
python -m pytest -q tests/test_mesh_instant.py -p no:cacheprovider
```

The new standalone verifier has 15 passing groups. It uses real temporary SQLite databases, actual router revalidation methods, and a gated fake verifier transport. It covers replacements with equal IDs/timestamps, old success and failure, fixed-clock A → B → A, identical delete/reinsert, newer success at the same timestamp, backwards clocks, legacy mutation methods, schema migration with nullable score, reopening and two-connection conditional writes, failed migration cleanup, canonical-vector reassignment, unchanged hits, unavailable verification, cancellation without mutation, and the actual `serve_cached` snapshot-copy boundary. It reads no key files and opens no sockets, models, or GUI.

The unchanged `tests/test_mesh_instant.py` subset also passed: 16 tests in 33.93 seconds, including the existing background-revalidation, expiry, restart, and cache-serving contracts. These existing cases use temporary cache state and local fake services, not an installed model/provider.

Ruff passes on both production files and the verifier. The new verifier passes pinned Pyright 1.1.414 with zero errors. Comparing the two production files with the base candidate's type diagnostics found no new diagnostic signatures (21 existing errors at base, 19 after the optional-cache narrowing); this is not a claim that those complete modules are type-clean. Existing tests and evaluation fixtures are unchanged.
