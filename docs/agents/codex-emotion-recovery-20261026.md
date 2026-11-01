# Emotion persistence recovery, 2026-10-26

The defect was in saved-state validation. A saved empty bond row raised
`IndexError` on every read; a NaN bond reached expression code and failed there;
saved anger of 1000 was returned despite the existing 0.85 cap. Ordinary JSON
decoding accepts NaN and Infinity, so decoding alone did not establish valid
state. This behavior is documented in the [Python 3.12 JSON reference](https://docs.python.org/3.12/library/json.html#infinite-and-nan-number-values).

`star/emotion.py` now validates native numeric types, finiteness, existing emotion
and drift bounds, mood/bond bounds, relationship row shapes, opaque identifiers,
and existing bond/amends capacity limits. Invalid stored state follows the
existing fresh-baseline recovery path. Snapshot reads do not rewrite the stored
state; the next valid event saves a recovered state through the existing
transaction. Strict JSON serialization prevents new nonfinite state from being
committed. Unused extra saved keys are omitted from the loaded working schema,
so a nonfinite unused value cannot poison later saves of valid known fields.
Injected clocks are checked before state computation; ordinary clock
rollback does not reset valid state.

The existing seven-emotion schema and absent optional newer fields remain
supported. This change adds no emotion categories, prompt text, model calls,
settings, or new runtime architecture. It does not establish human feelings or
consciousness.

Run `python scripts/verify_emotion_recovery.py` for 13 offline checks using only
temporary SQLite files. They cover nested malformed data, NaN/Infinity in every
numeric record location, booleans and numeric strings, declared bounds and
capacity limits, valid boundary states, legacy schemas, clock rollback, invalid
clocks, next-event recovery and restart, transaction rollback, concurrent engine
instances, and the default-off hook creating no database. Test connections close
explicitly, consistent with the [Python SQLite context-manager documentation](https://docs.python.org/3.12/library/sqlite3.html#how-to-use-the-connection-context-manager).

Recorded results: all 13 standalone checks and all 137 existing tests in
`tests/test_emotion.py` and `tests/test_emotion_range.py` passed. Ruff, verifier
Pyright, targeted compilation, and whitespace checks passed. The production
module has three existing Pyright return-type findings in its unchanged
module-level `_safe` wrappers; this change does not suppress them. No harness
fixtures, model endpoints, GPU workloads, or personal databases were used.

The measured gate in `docs/agents/emotion-20261026.md` remains unchanged: the
reported sign-test p-value was 0.09 against a required value below 0.05, so the
feature stays OFF. Persistence checks do not replace that quality evaluation.
