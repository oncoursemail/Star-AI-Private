# Source-backed relationship cards, 2026-10-26

The previous `valid_card` checks could accept invented biography without numbers.
For example, a card claiming that a jazz fan was a marine biologist in Lisbon
passed despite having no supporting record. A previously generated card also
appeared in the next night's notes, allowing it to support its own repetition.

Factual cards now accept only an exact match to the current deterministic
`rule_card` rendering, after whitespace normalization. This is an explicit
source-rendering check, not a semantic-entailment model, substring match or bag of
words. The canonical rendering uses the current profile and stored facts,
attributing facts as things the person told STAR. These are stored user claims;
their truth in the outside world is not established by this change.

`reflect_person` supplies the current grounded card to the existing unchanged
reflection prompt. Unsupported model output falls back to the deterministic card
when no prior row exists. An old row may remain for audit compatibility, but
`card_for` rechecks it against current sources at every read and excludes stale
or unsupported text. Fallback cards pass the same existing text restrictions.
Source deletion, updated facts and profile changes therefore affect the next
card read without requiring a model or nightly rewrite.

Reflection rechecks identity and source data after completion returns. A forget
request during that call ends the operation without creating an orphan card,
boosting records or scheduling a seed. Changed facts, age restrictions or profile
rendering discard the obsolete model result before using a fresh fallback.

Current minor/doubt status restricts canonical facts and nightly notes to stored
interests. Context for those people returns only the current interests card; it
does not retrieve historical episodes, dreams or old generated cards. A deleted
stale Person object returns empty context and cannot be interpreted as the
owner's empty-key memory. Unknown-age handling retains its existing behavior;
this change adds no platform permission or cross-platform identity proof.

`python scripts/verify_memory_cards.py` uses temporary real FriendMemory and
InnerStore databases with fake completion. It checks fabricated biography,
negation/rearrangement, exact supported output, old-card self-attestation,
fallbacks, source deletion, fresh facts/profile, forget during generation,
adult-to-minor/doubt transitions, excluded private history and the unchanged off
default. `tests/test_inner_life.py` remains untouched and passes 88 tests.

No prompts, feature flags, model settings, existing tests or evaluation baselines
were changed. `inner_chat_enabled` remains off. These deterministic checks do
not establish better live conversation quality or subjective experience; the
existing independent quality gate still applies. Diary text, opinions, dreams
and outgoing follow-up generation are separate paths with their existing
limitations; this work does not certify their factuality.
