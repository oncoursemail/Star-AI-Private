# Litha: bounded multi-block repair

Candidate stacked on #746 (`95d4b157`), after #741 (`7cea7eea`); target integration remains `star/next`. This is actual
`server/mesh/verify` source. It has not been merged, deployed, or enabled on a live model.

## Behavior

`Verifier.fix(..., batch=RepairBatch(workers=2, coalesce=True))` can request several block repairs concurrently.
Workers only call the model; the owning thread checks every returned edit, preserves placeholders, applies
edits in deterministic block order, and re-verifies the full answer. An identical complete repair message may
share a result within a round. Each later round and request starts fresh. Different callers/credentials never
share results. No prompts or generated source are persisted by this dispatcher.

The server creates one shared dispatcher per handler factory when the operator enables batching. Its semaphore
bounds active model callbacks across requests to 1–4. A busy acquisition expires after `repair_wait_s` (0–5 s),
leaves that block unchanged, and reports a skipped call. This bound applies to the enabled batch path; the
default legacy synchronous path is unchanged. A callback retains its permit until it actually returns.
Thread-pool construction/submission failures likewise retain the affected source and report dispatch refusal.

Each round admits at most 64 distinct jobs and 256 KiB of serialized prompt strings; larger jobs are refused
without a model call. At most `workers` futures are submitted per window. Existing HTTP body/source limits
still apply. These limits do not bound total HTTP connections or promise remote request cancellation.
The production HTTP caller retains its existing I/O timeout. A custom callback must enforce its own timeout.

## Operator configuration and first trial

Existing defaults preserve synchronous repair: `repair_workers: 1`, `repair_coalesce: false`.
After independent integration review and the required evaluation gate, a service configuration can opt in:

```json
{"repair_workers": 2, "repair_coalesce": true, "repair_wait_s": 0.25}
```

These settings come from the service configuration, not from generated code or HTTP request fields. Invalid
worker counts, booleans masquerading as counts, nonfinite waits, and string coercions fail at construction.
Use one worker for a single-slot backend until measurement supports more. Extra client workers do not create
GPU inference slots. Compare complete repair wall time, remaining diagnostics, engine behavior, and contention
with normal chat/game/voice traffic on the actual node before retaining a configuration.

Enabled reports add `repair_batch`: actual `model_calls`, `coalesced_blocks`, `capacity_skipped`,
`dispatch_skipped`, and `budget_skipped`. Top-level `model_ms` sums unique callback durations and can exceed
wall `ms` during concurrency. Coalesced refusals also share one outcome; coalescing counts are not inherently
successful edits or saved inference. Static diagnostics do not establish correct gameplay or visual quality.

## Executed checks

- `python scripts/verify_litha_repair_batch.py -v`: 15 groups passed, including actual loopback HTTP with synthetic
  keys/caller, simultaneous clients respecting the shared cap, out-of-order completion, serial validation,
  complete-prompt coalescing, fresh rounds/requests, placeholder preservation, JSON local pack semantics,
  source refusals, callback/executor failures, and job/message budgets.
- `python scripts/verify_litha_languages.py`: 21 groups passed.
- Existing five `tests/test_mesh_*.py` files: 108 passed in 20.36 s. Existing tests/evaluation files were not edited.
- Scoped Ruff and Pyright for batch/core/service, `compileall -q star main.py server/mesh/verify`, and diff
  whitespace checks passed. No full-repository local pytest result is claimed here.
- Independent source review reproduced the new 15 groups and the existing verifier checks.

The deliberately combined source at `1fe2e217` contains the independently reviewed cache revision fix from
#746. All 15 batch groups, 15 cache-race groups, 21 language groups and 108 existing mesh tests passed together
(the existing mesh run took 18.23 s). Combined Ruff, compilation and diff checks passed; tests/evals remain
byte-identical to `star/next`. This is integration of source candidates in our task branch, not a GitHub merge
to `star/next` or a deployment. The following documentation-only commit records these results.

`python scripts/verify_litha_repair_batch.py --benchmark` ran five trials per mode with six broken Python fences,
three distinct prompts, and a deterministic synthetic callback sleeping 40 ms per call. Every output cleared
the same static checks and retained six edits. Median total times were 243.73 ms / 6 calls for legacy serial,
122.20 ms / 3 calls for serial coalescing, and 43.05 ms / 3 calls for three-worker coalescing. These numbers show
dispatcher behavior with parallelizable sleeping callbacks, not measured GPU throughput, model accuracy,
game-making skill, or a speed advantage over another AI.

## Concurrent integration

#739 changes `core.fix` and service dispatch to inject official docs into repair prompts. Keep its positional
`docs` parameter before keyword-only `batch`, preserve its per-block doc lookup, and build batch keys from the
complete final `fix_messages(..., docs=...)` result. A caller/model configuration is fixed for one batch run.
Both defaults must remain compatible. The source review for this candidate is not a claim that #739 has been
merged or that their combined live service has passed acceptance. The router/node/loop lanes are untouched.

Deployment already copies the whole verifier package, including new modules. Review the combined source tree,
run existing mesh plus both standalone checks, and perform an idle-server latency/contention trial before
changing live configuration. No remote restart, deployment, account operation, or active evaluation was run.

Primary research and the game-creation evidence roadmap:
[LITHA_REPAIR_AND_SKILL_REUSE_20261028.md](../research/LITHA_REPAIR_AND_SKILL_REUSE_20261028.md).
