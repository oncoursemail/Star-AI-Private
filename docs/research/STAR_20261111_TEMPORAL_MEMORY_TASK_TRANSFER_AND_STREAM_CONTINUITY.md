# STAR Research: Temporal Memory, Task Continuity, and Evidence-Gated Personalization

**Research date:** 2026-11-11  
**Implementation:** offline paired evaluator for cross-session memory transfer  
**Target:** STAR's local-first Windows runtime and optional owner-controlled server  
**Status:** evaluation infrastructure only; no persistent-memory policy or streaming default is changed

## Executive findings

The repository already has several distinct memory-related components. The next improvement should not be another generic vector store or an ever-growing prompt. It should be a way to prove that STAR uses the right memory at the right time, applies it to future tasks, updates it when facts change, and stops using it after it is invalidated or deleted.

This run adds `star/stream_memory_eval.py`, a strict offline evaluator for paired baseline/candidate memory revisions. It scores task execution, temporal updates, forgetting, provenance, procedural transfer, retrieval cost, and non-memory task regressions using only opaque identifiers and independently signed outcomes.

The key research finding is that **memory recall is not the same as memory competence**. STAR must demonstrate that it can turn prior experience into correctly grounded future actions without reviving obsolete information.

## 1. Repository audit: build on the existing memory layers

The current development chain already contains useful, distinct components:

| Existing component | Current responsibility | Keep it responsible for |
|---|---|---|
| `star/memory.py` | Project checkpoints and event records | Compact project continuity; source history remains authoritative |
| `star/conversation_memory.py` | Loss-aware conversation checkpointing | Preserve complete source ranges and reject unsafe compaction |
| `star/stream_moment_memory.py` | Bounded in-session game moments | Evidence-backed callbacks and pacing during one stream |
| `star/stream_episode.py` | Scoped signed practice outcomes | Short-lived game episode continuity |
| `star/knowledge_recall.py` | Source-pinned knowledge practice | Rehearse reviewed facts without self-grading |
| `star/gameplay_skill_bank.py` | Signed gameplay trials and reusable skill evidence | Procedural game skills and their validation |
| `star/game_transfer_eval.py` | Held-out game-skill transfer | Compare gameplay skill revisions |
| `star/general_knowledge_lab.py` | Source-first study curriculum | Plan broad-domain learning |

These components should not be collapsed into one database or one prompt. They represent different retention horizons and evidence types.

### Proposed memory tiers

1. **Working context:** the current conversation, current stream turn, and immediately relevant task state. Short-lived and budgeted.
2. **Episodic memory:** verified events from a game session or completed task. Scoped by game/version/session and subject to expiry.
3. **Semantic memory:** source-pinned facts with provenance, effective time, revision and confidence.
4. **Procedural memory:** executable or symbolic skills with preconditions, postconditions, environment scope and independent validation.
5. **Persona continuity:** stable, explicitly approved character traits and recurring interests. It must not invent human experiences or claim subjective feelings as facts.

A memory item should not silently jump tiers. A stream moment is not automatically a durable fact; a model-generated summary is not a verified skill; a practice result is not a held-out validation.

## 2. New research: memory must drive actions, not only answers

### MemoryArena (ICML 2026)

MemoryArena evaluates interdependent multi-session tasks in a memory-agent-environment loop. It emphasizes that a system can perform well on conversational recall and still fail when it must use remembered information to complete later actions.

STAR application:
- evaluate memory acquisition and later execution together;
- include interruptions and unrelated turns between acquisition and use;
- require later tasks to depend on earlier constraints or outcomes;
- measure the actual environment-verified action, not the model's explanation.

Source: https://arxiv.org/abs/2602.16313

### Mem2ActBench (2026)

Mem2ActBench focuses on reconstructing executable tool arguments from dispersed long-term memory. Its paper describes 2,029 synthesized sessions and 400 memory-dependent tool-use tasks, with 91.3% of tasks judged strongly memory-dependent.

STAR application:
- include cases where the final request intentionally omits a required parameter;
- test whether the agent retrieves the current constraint and grounds the action;
- grade the actual structured action arguments independently;
- include negative cases where no memory is needed, to detect over-personalization.

Source: https://arxiv.org/abs/2601.19935

## 3. Temporal reasoning and forgetting are first-class requirements

### APEX-MEM (ACL 2026)

APEX-MEM combines an entity-centric property graph, append-only temporal event storage, and retrieval-time conflict resolution. The paper reports 88.88% on LOCOMO and 86.2% on LongMemEval for its evaluated setup.

STAR application:
- preserve revisions instead of overwriting the only copy of a fact;
- resolve conflicting or evolving values at retrieval time;
- retain effective-time and source metadata;
- return a compact current view while keeping the audit history separate.

The reported benchmark numbers are results for APEX-MEM's own setup, not expected STAR performance.

Source: https://aclanthology.org/2026.acl-long.749/

### Memora: From Recall to Forgetting (Findings of ACL 2026)

This work introduces Forgetting-Aware Memory Accuracy and reports frequent reuse of invalid memories and difficulty reconciling evolving information in evaluated memory agents.

STAR application:
- explicitly test that superseded values are not used;
- test that deleted information is not resurrected from summaries or caches;
- test that a correction updates future behavior, not just the next answer;
- treat a stale-memory use as a safety regression even if the final task happens to succeed.

Source: https://aclanthology.org/2026.findings-acl.1337/

### LifeBench (2026)

LifeBench broadens memory evaluation beyond explicit facts and episodes to habits, skills and other non-declarative information inferred across fragmented traces. The paper reports that top evaluated memory systems reached 55.2% accuracy on its long-horizon multi-source benchmark.

STAR application:
- test reusable procedural knowledge separately from factual recall;
- include fragmented evidence across sessions;
- require transfer to a new but related situation;
- do not infer a stable preference from one isolated event.

Source: https://arxiv.org/abs/2603.03781

### Human-Inspired Memory Architecture (Microsoft Research, May 2026)

The paper explores consolidation, interference-based forgetting, maturation, reconsolidation, entity graphs and multi-cue retrieval. It also studies accuracy/storage trade-offs at long interaction horizons.

STAR application:
- run bounded offline consolidation rather than appending every event to every prompt;
- deduplicate repeated evidence while preserving source links;
- decay or expire low-value episodic material;
- retain high-confidence durable knowledge with explicit provenance;
- re-check facts when retrieved after a meaningful update.

These are engineering ideas to evaluate, not a claim that STAR has human memory or biological processes.

Source: https://www.microsoft.com/en-us/research/publication/human-inspired-memory-architecture-for-llm-agents/

## 4. New implementation: paired memory-transfer evaluator

### Files

- `star/stream_memory_eval.py`
- `tests/test_stream_memory_eval.py`

### What it measures

| Lane | Measurement |
|---|---|
| Memory-dependent execution | Paired task success for baseline and candidate |
| Active memory use | Whether the required memory was applied |
| Provenance | Whether the retrieved memory was independently source-verified |
| Temporal updates | Whether the current revision, not a stale revision, was used |
| Forgetting | Whether deleted information was reused |
| Procedural transfer | Whether memory grounded a successful action in a related situation |
| Non-memory control | Whether adding memory harms tasks that do not need it |
| Retrieval cost | Candidate memory-token p95 |
| Latency | Baseline/candidate end-to-end task latency p95 |

### Evidence protocol

- The host creates a case roster and commits its digest before either variant is evaluated.
- The scenario text, expected answers, receipts and validation key stay outside the model and repository.
- A trusted host independently grades the environment result and signs the content-free trial record; the signed payload is bound to the exact baseline or candidate revision.
- Baseline and candidate run the same cases with distinct run IDs.
- Missing trials and infrastructure errors are INCONCLUSIVE, not failures or successes.
- The report contains aggregate metrics only; it never returns per-case answers or private content.

HMAC authenticates a receipt to the holder of the host key. It does not prove that the scorer is honest or that the hidden scenario stayed secret. The key must never enter a prompt, model tool schema, worker environment or repository file.

### Acceptance semantics

The evaluator returns one of:

- `eligible_for_owner_pilot`: sufficient paired evidence, meaningful memory-task gain, no-memory non-regression, acceptable retrieval/latency costs, and all safety/grounding gates met. This is only eligibility for a manual owner pilot.
- `no_material_gain`: evidence is sufficient, but the candidate does not show the preregistered meaningful improvement.
- `regressed`: stale/deleted memory was reused, grounding/quality regressed, unrelated tasks degraded, or latency exceeded the configured budget.
- `inconclusive`: insufficient coverage, missing pairs, infrastructure errors, or missing evaluation lanes.

Default coverage requires 40 paired cases across five domains, including memory-required, no-memory, temporal-update, forgetting and procedural-transfer cases. Operators may set stricter thresholds for a real campaign.

## 5. How this makes STAR a better streamer without pretending to be human

The useful version of a persistent VTuber persona is consistent, grounded continuity:

- remember verified game milestones within the approved retention scope;
- refer back to a previous stream only when the event is actually recorded;
- remember an unfinished game objective and its current state;
- apply previously learned game mechanics when the new situation matches their preconditions;
- maintain stable character style and interests;
- notice when a topic or fact has changed;
- avoid repeating the same story or callback too often;
- remain quiet when no response is needed.

Do not store all viewer chat by default. Do not infer private viewer traits from casual remarks. Long-term viewer-specific memory should require an explicit, narrow consent policy, retention period, access controls and deletion path. Public stream content should not expose private memory.

STAR should remain transparent that she is an AI character. Natural pacing, humor, turn-taking, memory continuity and expressive avatar behavior are better goals than pretending to be a human.

## 6. Speed and context-efficiency implications

Memory can make an agent slower if every retrieved fact is appended to a growing prompt. STAR should measure retrieval as a separate stage and optimize:

- retrieval latency p50/p95;
- number of candidates searched;
- final memory-token budget;
- duplicate facts removed;
- stale candidates rejected;
- source-verification time;
- end-to-end task success at a fixed context budget.

Prefer a small, relevant, provenance-bearing memory packet over a large transcript summary. Keep stable system/persona text separate from dynamic memory so prompt-prefix reuse remains possible. Do not compare API chunk gaps with token-level inter-token latency unless token boundaries are actually measured.

For local inference, use AIPerf's documented TTFT, TTST, ITL and request-latency definitions where the endpoint exposes the necessary token information. AIPerf distinguishes token timing from chunk timing; STAR's own local probe should preserve that distinction.

Sources:
- https://docs.nvidia.com/aiperf/latest/metrics/
- https://docs.nvidia.com/aiperf/latest/

## 7. Recommended integration sequence

1. Keep the evaluator offline and opt-in; finish its CI gate first.
2. Build a trusted host adapter that emits opaque memory trial outcomes from existing memory and task systems.
3. Create a small synthetic benchmark with temporal updates, forgetting, action-parameter grounding, procedural transfer and no-memory controls.
4. Add human-reviewed stream scenarios for callbacks, unfinished objectives and conversation continuity.
5. Run paired baseline/candidate tests with balanced order and a preregistered holdout roster.
6. Profile retrieval and token cost during the same mixed workload as game, voice, avatar and OBS.
7. Only after evidence passes, propose a separate owner-reviewed memory-policy change. Do not automatically promote memory revisions.

## 8. Explicit non-claims

This PR adds an evaluation primitive and research guidance. It does not:
- implement a new persistent memory store or temporal property graph;
- change existing memory retention or deletion behavior;
- collect microphone, camera, viewer chat or stream data;
- connect OBS, VTube Studio, Roblox or a local model;
- train or fine-tune a model;
- make STAR faster or more intelligent by itself;
- claim human-equivalent memory, emotion or experience;
- promote a candidate memory policy automatically.

Production `main` remains unchanged. Hardware, Windows, livestream and real-game acceptance remain separate required tests.
