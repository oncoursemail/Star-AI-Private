# Memory integrity follow-up, 2026-10-26

This source update repairs concrete continuity defects without enabling the experimental per-turn recall hook. No live model, account, message, target-PC action or sealed evaluation was used. PR 644 was inspected before work; its separate desktop/Home continuity files were left untouched.

## Implemented

- Factual relationship cards use the current deterministic rendering of live person metadata and retained source facts. Generated text is accepted only when it exactly matches that rendering after whitespace normalization. This is deliberately conservative; it does not claim semantic entailment of paraphrases.
- Existing generated card rows remain available for audit, but unsupported/stale rows are not supplied as factual chat context or used as evidence in the next reflection. Fresh source changes, age changes or forgetting during a model callback invalidate its result before card/seed/importance writes.
- Current minor/doubt status produces only the current interests card. Old adult-era episodes, dreams and private facts do not enter that context. Forgotten/stale person objects cannot fall through into the owner's recall.
- Source synchronization now reconciles the bounded retained fact/moment records, rather than trusting an ID high-water cursor. It removes copied sources that were deleted, aged out, restricted or changed after SQLite reused a record ID. Unrelated manually stored episodes are not rewritten.
- Friend-memory metadata and source reads use public methods under the existing write lock. Inner recall, reflection, identity resolution and contact planning no longer read the friend connection directly. This is not a transaction spanning both databases or a promise to retract data from an already-running model request.
- Home reports keep their original aware event times and stable source IDs. Only exact boolean true receives the reported-success kind; other statuses remain unverified. Older ambiguous `home` rows are rendered as legacy unverified reports. Replaying a source does not duplicate its episode, while different reports with identical summaries remain distinct through consolidation.
- Night history is materialized and filtered before every consumer; malformed dates, invalid text and non-record values are omitted rather than assigned a made-up event date. Diary input and fallback retain outcome attribution. Nonboolean verification cannot generate an earned preference.

No prompt constants, feature defaults, permission boundaries, evaluation fixtures or grading baselines changed. The existing `inner_chat_enabled` default remains false and still needs its quality gate.

## Validation

**58 new offline cases** passed: cards 22, report provenance 12, public reads/reconciliation 9 and independent cross-contract boundaries 15. They use temporary databases and fake completions. The independent reviewer reproduced deletion, age-change and model-time forgetting defects, then checked the fixes and adversarial negative/role/biography claims.

The existing inner-life, inner-wiring, social-game and Home-wiring selection passed **189 tests**. After the final diary fallback attribution change, the affected existing model-unavailable case and the nine public-read checks were rerun and passed. Existing test sources were not edited.

Ruff, compilation and whitespace checks passed. Full package-free Pyright 1.1.414 reports 570 errors versus the previous 571; these pre-existing repository errors remain, with no increased per-file/per-rule error counts. It is not a wholly green type check.

Detailed notes: [cards](codex-memory-cards-20261026.md), [Home report provenance](codex-memory-provenance-20261026.md). Retained commands:

```text
python scripts/verify_memory_cards.py
python scripts/verify_memory_provenance.py
python scripts/verify_memory_reads.py
python scripts/verify_memory_boundaries.py
python -m pytest -q tests/test_inner_life.py tests/test_inner_wiring.py tests/test_social_games.py tests/test_home_wiring.py
```

## Limits

Source-backed means traceable to retained local records, not independently true in the world. Users can make false claims. Activity adapters can overstate their receipts. Snippets are bounded and can omit context. Broader generated diary/opinion content is not proven factual by these changes.

The existing exact-false preference heuristic remains a weak uncertainty penalty with an explicitly unverified reason; it is not proof that the activity failed. Repeated opinion evidence can still increase confidence on replay; only Home episode replay is deduplicated by this update. Neither behavior is described as validated personality learning.

Naturalness, appropriate memory use, latency and real conversational delivery still need the predefined blind quality comparison and target-PC rehearsal. The production avatar rig, automatic friendship delivery and public Twitch speech remain unfinished. These changes establish neither human identity nor subjective feelings.
