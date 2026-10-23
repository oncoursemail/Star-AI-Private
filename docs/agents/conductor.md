# Conductor (#414) - slice 1: verified duel

`star/conductor_duel.py` (opt-in, `enabled=False` default, backend only, no UI): runs two writers (small async
`prompt -> text` interface; fleet #406 / commons #424 adapters can plug in later) in parallel, checks both with the
existing `best_of_n` checkers, ranks with `rank_key`, builds host-tool `TaskEvidence`, gates with
`assess_learning_readiness`, and appends a hash-only event (`pending_owner_review`) to `<home>/conductor/learning_events.jsonl`.
Nothing is activated; a "code block exists" check alone never counts as verification.
Left for #414: agent adapters, planner modes, DAG, UI, promotion gate wiring, benchmarks.
