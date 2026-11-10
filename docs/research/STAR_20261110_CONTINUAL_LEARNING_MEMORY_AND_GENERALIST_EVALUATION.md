# STAR — Continual Learning, Memory Utility, and Generalist Capability Evaluation

**Research date:** 2026-11-10  
**Implementation:** star/continual_learning_eval.py  
**Status:** offline evaluation infrastructure; no model execution or automatic promotion.

## Executive finding

STAR already has several strong domain-specific foundations: general-knowledge question sets, verified game practice and transfer, episodic game recall, skill routing, paired inference benchmarks, and Studio/game-development evaluation. The remaining question is not simply whether STAR stores more memories. It is whether a memory policy causes **reliable transfer to future tasks**, preserves earlier skills, avoids interference on unrelated tasks, and does so at an acceptable context, token, latency, and compute cost.

This update adds a domain-neutral evaluation contract for comparing the same model/runner/prompt/tool policy with memory off versus memory on across preregistered task streams. It does not replace the existing domain-specific graders; it consumes their trusted host's aggregate outcomes through signed receipts.

## Research findings

### 1. AgentCL: task relationships matter

AgentCL: Toward Rigorous Evaluation of Continual Learning in Language Agents (arXiv 2606.02461; v2 dated 2026-09-26) distinguishes dependent/compositional task streams, conventional streams with unknown relationships, and independent tasks. Its central warning is that naive streams can make memory strategies look equivalent, while unrelated or held-out tasks can expose memory-induced degradation. The framework motivates separate transfer and stability measurements rather than a single cumulative accuracy score.

Source: https://arxiv.org/abs/2606.02461

### 2. MemGym: isolate memory from the agent backbone

MemGym: a Long-Horizon Memory Environment for LLM Agents (May 20, 2026) spans tool-use dialogue, deep research, coding, and computer-use tasks. It explicitly separates memory-system evaluation from the reasoning model and tool-use policy. STAR should compare memory-on/off with the same backbone, prompt, runner, tool policy, context budget, task roster, and scoring system; otherwise a model or harness change is confounded with memory.

Sources:
- https://arxiv.org/abs/2605.20833
- https://www.microsoft.com/en-us/research/publication/memgym-a-long-horizon-memory-environment-for-llm-agents/

### 3. MemTrace: old execution evidence can become stale

MemTrace: State-Consistent Memory for Long-Horizon Coding Agents (arXiv 2610.04838; submitted 2026-10-04) anchors immutable traces to repository entities and checks their validity against current repository state before reuse. Its key lesson for STAR Core Forge is that an old passing test or code observation is not timeless truth: file, symbol, dependency, and test state may have changed. Preserve historical traces, but invalidate their **current applicability** when the referenced state no longer matches. Reported benchmark gains are task-success results, not evidence of faster inference; the paper also reports higher mean elapsed time on one DeepSWE comparison.

Source: https://arxiv.org/abs/2610.04838

### 4. Full-duplex and multi-party streaming remain separate quality lanes

Duplex-MPE (2026-09-25; arXiv 2609.31948) evaluates 2,000 three-/four-speaker scenarios, distinguishing explicit from implicit addressing and measuring response initiation, answer accuracy, silence preservation, and stopping when another person resolves a request. This complements STAR's existing multi-party floor controller and duplex evaluator; it should be used as an external held-out reference rather than reimplemented here. The released scenarios use synthetic English speech with a small preset voice set, so this is a controlled benchmark—not a substitute for human-recorded, multilingual, noisy live-stream rehearsals.

Source: https://arxiv.org/abs/2609.31948

## Implementation design

### Paired memory experiment

The manifest pins:
- exact backbone, runner, grader, prompt-template and tool-policy digests;
- memory-off and memory-on policy digests;
- identical context/output budgets and a bounded memory budget;
- opaque task-content digests, domain/skill labels, stream order and task relationship;
- balanced first-arm assignment to reduce order effects.

Only the memory policy is intended to differ between arms. The host must preregister the manifest digest in an independent audit log before either arm runs.

### Controlled task roles

- **acquire:** an earlier task whose independently graded result may create reusable experience.
- **dependent_probe:** a later task that explicitly depends on one or more earlier acquisition tasks.
- **independent_probe:** a task deliberately unrelated to the acquired skill, used to detect interference.
- **conventional_probe:** a task whose transfer relationship is unknown; report separately and do not use it as causal transfer evidence.
- **retention_probe:** a later exact replay of an acquisition task, used to measure retention under a stable task digest.

Every dependent probe references an earlier acquisition in the same stream. Every retention probe references an earlier acquisition with the exact same task digest. Independent probes cannot reuse an acquired skill ID.

### Trusted receipts and replay resistance

The evaluator accepts only host-signed, content-free receipts. The HMAC key stays in the trusted host, never in model context, repository files, logs, or the agent's tool results. Receipts bind the exact manifest, task, stream, arm, preregistered run order, outcome, time, elapsed time, token usage, memory activity and opaque evidence digest.

Duplicate run IDs, evidence digests, task/arm pairs, stale/future timestamps, invalid signatures, wrong task/stream bindings, memory-off activity, and memory-budget overruns are rejected. Infrastructure failures contaminate the campaign; they are not counted as model failures or successes. Timeouts are measured task failures.

### Statistics and guardrails

The statistical unit is the **stream**. Task-level results within one stream are correlated, so a sign test over individual tasks would overstate the effective sample size. The report computes per-stream paired deltas, then reports:
- overall memory utility;
- dependent-task forward-transfer gain;
- independent-task interference;
- conventional-task gain (descriptive only);
- retention gain;
- improved/worse/tied stream counts and exact one-sided sign-test probabilities;
- p50 memory read/write tokens and paired elapsed-time overhead.

A positive holdout recommendation requires a complete preregistered campaign, at least eight streams and three domains by default, a dependent-task gain above the configured floor, a significant stream-level direction, and no unacceptable independent-task or retention regression. Development campaigns can only produce screening signals. No report promotes a memory policy or changes model routing.

## How STAR should use this next

1. Adapt the existing general-knowledge, coding/Luau, research, Roblox Studio, game-mechanic, and game-mastery graders to emit the same host receipt contract. Do not collapse their domain-specific oracles into one model judge.
2. Construct paired task streams with deliberate dependencies: learn a reusable Luau/API pattern, then solve a novel task that composes it; practice a game mechanic, then test it in a new map; learn a research workflow, then apply it to a new question.
3. Include unrelated tasks after memory has grown to expose retrieval interference, plus delayed retention probes for earlier skills.
4. Keep all answer keys and holdout rosters outside STAR's model/tool context. The host signs results after independent grading.
5. Run development first, freeze the memory policy, then evaluate on a newly sealed holdout. A positive result only authorizes manual review.
6. Add state-consistent trace validation for coding memory: before reusing a past test result, compare the exact file/symbol/dependency/test digests; if changed or unverifiable, reread or rerun instead of trusting stale evidence.

## Speed and intelligence roadmap

- Memory retrieval should be deadline-aware: a live VTuber turn uses a bounded, fast retrieval budget; deep repository or research trace reconstruction runs in the background.
- Measure retrieval latency, prompt tokens saved, memory tokens read/written, end-to-end response latency and task accuracy together. A memory system that raises accuracy but doubles live response time may be unsuitable for stream-time use.
- Preserve exact model/tokenizer/embedding fingerprints. The existing skill-router cache fingerprint work is a prerequisite for trustworthy semantic retrieval.
- For llama.cpp, benchmark prompt caching and speculative decoding against no-cache/no-speculation baselines using the same request traces and model artifacts. Draft acceptance alone is not end-to-end speed; include TTFT, inter-token latency, completion latency, output equivalence/quality, and simultaneous game/OBS/voice load.
- On an 8 GB RTX 4060, reserve capacity for the game, OBS and avatar first; admit optional VLM/reasoning workers only from fresh telemetry and physically confirmed worker-stop receipts. The existing GPU lease work should remain opt-in and fail-closed.

## Acceptance tests still required

- Real host adapter emits signed receipts from independent graders for at least three domains.
- At least eight genuinely independent streams with balanced first-arm order and preregistered task relations.
- A sealed holdout not used to tune the memory policy.
- Full repository pytest/Ruff/Pyright and GitHub Actions.
- Windows mixed-workload rehearsal measuring GPU/VRAM, CPU/RAM, game frame-time, OBS dropped frames, audio underruns, first-audible latency, memory retrieval latency and task quality.

## Explicit limitations

This PR is an evaluator, not a memory database, model-training pipeline, autonomous learner, game controller, TTS adapter, or streaming integration. The signatures authenticate receipts relative to a trusted host key; they cannot prove the host's real-world truthfulness or that a holdout remained secret. No neural intelligence gain or inference-speed improvement is claimed until actual model runs on sealed tasks and target hardware are completed.
