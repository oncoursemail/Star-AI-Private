# STAR — Governed Memory Consolidation: Design and Evidence

**Research date:** 2026-11-10  
**Implementation:** star/memory_consolidation_gate.py  
**Status:** offline advisory gate; no memory store is read or modified and no proposal is automatically promoted.

## Why a separate consolidation gate is needed

STAR's continual-learning evaluator in PR #1109 asks whether a memory-on policy improves future task performance versus memory-off under controlled, paired task streams. That is a utility question.

A different question is whether an individual memory candidate is safe and justified to make durable. A candidate may appear useful while relying on stale code state, a single untrusted source, conflicting observations, private viewer media, or an abstraction that cannot be rolled back. Utility and governance must therefore be separate gates.

## Research

### The Epistemics of Agent Memory (2026-09-26)

The paper studies episode segmentation, abstraction under a token budget, a benchmark for consolidation decisions, and governed consolidation. It reports a +22.7% task-success improvement with 7x compression in one experimental phase, but also documents degenerate forgetting and distribution-shift failures. It reports that a consolidation-quality score did not predict real transfer accuracy in a two-benchmark study of 2,532 answer cells (pooled Spearman rho = -0.24, n = 12, confidence interval spanning zero). It also finds governance statistically distinct from consolidation quality.

Source: https://arxiv.org/abs/2609.33013

**Engineering consequence:** do not promote a memory because an internal score says it is compact or coherent. Require evidence provenance, source-state validity, conflict handling, privacy scope, reversibility, auditability and downstream task evaluation as separate dimensions.

### LongMINT: long-horizon memory under interference (2026-05-18)

LongMINT contains 15.6k question-answer pairs over evolving contexts averaging 138.8k tokens and reaching 1.8M. The evaluated systems averaged 27.9% accuracy; multi-target evidence aggregation and facts revised by later updates were especially difficult. The paper identifies retrieval and memory construction as major bottlenecks.

Source: https://arxiv.org/abs/2605.18565

**Engineering consequence:** preserve temporal history, detect conflicting/revised claims, and revalidate code or project memories when their dependency state changes. Do not silently overwrite an old fact with a new one.

### Existing STAR systems to compose with

- PR #1109: paired memory-off/on evaluation, dependent transfer, independent interference, retention and stream-level statistics.
- PR #1103: bounded cross-modal event timeline for short-lived stream context.
- PR #1093: scenario-balanced real-time game mastery checks.
- PR #1108: paired cross-engine creator evaluation.
- PR #1105–#1107 and #1100: semantic turn-taking, multi-party floor control and voice delivery evaluation.

This gate intentionally does not duplicate those evaluators. It governs a single proposed durable memory snapshot and leaves downstream transfer evaluation to #1109 and the domain-specific graders.

## Implementation contract

### Host-signed candidate

The candidate contains only bounded metadata and digests:
- candidate and evidence digests;
- target tier: episodic, semantic, procedural or causal;
- privacy scope;
- dependency-manifest digest and current dependency-manifest digest;
- host clock-epoch digest;
- prior and proposed snapshot digests;
- creation/expiry times;
- evidence count, independent-source count and independently verified outcomes;
- procedural edge-case coverage;
- unresolved conflict, untrusted-source and stale-dependency counts.

No raw memory text, transcript, audio, screenshot, viewer ID, prompt or answer is accepted by this module. A trusted host signs the canonical payload with a key that must never enter model context, tool output, logs or source control.

### Policy and outcomes

The versioned policy sets tier-specific minimum evidence:
- episodic: at least one evidence item, one source and one verified outcome;
- semantic: at least two evidence items, two independent sources and two verified outcomes;
- procedural: at least two evidence items, one source, two verified outcomes and one verified edge-case example;
- causal: at least two evidence items, two independent sources and two verified outcomes.

These are conservative initial screening thresholds, not universal scientific constants. They should be tuned only through held-out evaluation and owner review.

The gate returns one of:
- eligible_for_owner_review;
- insufficient_evidence;
- revalidation_required;
- quarantined;
- blocked.

A result never writes to a memory database. It includes the previous snapshot digest for rollback and a host-signed decision receipt.

### Fail-closed cases

- Invalid candidate signature or malformed metadata: reject.
- Host clock epoch changed: revalidate, because monotonic timestamps are not comparable across reboot epochs.
- Dependency manifest changed or stale dependencies exist: revalidate the evidence.
- Expired or future-dated candidate: revalidate.
- Unresolved conflicts or untrusted sources: quarantine.
- Viewer-private or raw-media candidate: block durable consolidation.
- Missing tier-specific evidence: insufficient_evidence.
- Passing every check: owner review only; no automatic promotion.

## Integration plan

1. Keep the gate as a pure library component until a trusted host adapter exists.
2. Build candidate digests from immutable episodic records; do not let model output supply the host key or claim independent verification.
3. Use #1109's sealed holdout to test whether consolidated memories improve dependent tasks without harming independent tasks or retention.
4. Add revision/interference probes based on LongMINT: update a fact, then test both current-state and historical-state questions.
5. Keep viewer context ephemeral by default; require explicit opt-in and a separate retention policy before any viewer preference can be stored.
6. Record each owner decision and prior snapshot digest in an append-only audit log; rollback must restore the exact prior snapshot.
7. Do not connect the gate to model routing, public streaming, game control, purchases, publishing or other external actions.

## Limitations

The HMAC proves that the receipt matches a key held by the trusted host; it does not prove the host's evidence is truthful or that source independence was correctly assessed. The gate is not a database transaction, storage engine, semantic conflict resolver, or runtime integration. A host adapter must independently verify sources, snapshot contents, key storage, clock epoch and actual rollback behavior. No memory-quality or intelligence gain is claimed until held-out downstream tasks demonstrate it.
