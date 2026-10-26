# Home memory provenance, 2026-10-26

Home activity history previously became `kind="home"` episodes without its
verification status or event time. Recall rendered every such episode as
“you,” so an unverified summary claiming completion could later read as a
completed action. Reflection time also replaced the original event time.

The reflection entry point now normalizes Home history once before all its
consumers. Rows require string timestamps, interests, and summaries; timestamps
must parse as timezone-aware, finite instants. Missing, naive, or invalid times
are skipped instead of being assigned the reflection date. Interests and
summaries use the existing Home length bounds and must encode as UTF-8.
Generators are materialized once; source rows are not mutated. The raw
verification value is retained for consumers that distinguish non-boolean or
unknown status from explicit boolean False. False remains an unverified report,
which can also represent STOP or cancellation.

New stored episode kinds are `home_verified` only for literal `verified=True`,
and `home_unverified` for every other value. They carry the original event time
and the existing `h:<original timestamp>` source identifier. No schema migration
or new memory service is required. The identifier still prevents replay from
adding another episode, including when an old `home` row already occupies it.

Recall says “activity reported success” or “unverified activity report.” Old
`home` entries say “legacy unverified report”; reprocessing history does not
silently promote them. These are reports from the activity implementation,
not independent proof of native game or PC outcomes. The line length budget
includes the full provenance label.

Home consolidation preserves separate episode IDs rather than merging distinct
events solely because their summary text matches. Existing text consolidation
for other episode kinds is unchanged. The existing aging, forgetting, storage
caps, and timestamp-based source-ID limitations remain; this does not add new
durable action receipts or recover missing provenance in historical rows.

`python scripts/verify_memory_provenance.py` passes 12 offline checks using
temporary real InnerStore/FriendMemory databases and no model. Cases cover
strict booleans, attributed unverified completion text, legacy entries, original
times and identifiers, offset/fractional timestamps, invalid history filtering
before every consumer, one-shot iterables, replay/consolidation, separate events
with matching text, normal fact/moment compatibility, and recall line bounds.
All 91 existing inner-life and wiring tests passed without edits. Ruff, Pyright,
targeted compilation and whitespace checks passed for the changed Python files.
No prompts,
default flags, evaluation fixtures, or live model/desktop actions are changed
by this work.
