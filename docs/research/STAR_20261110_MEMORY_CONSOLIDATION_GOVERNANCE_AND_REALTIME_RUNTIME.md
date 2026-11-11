# STAR — Memory Consolidation Governance, Realtime Intelligence and Capability Roadmap

**Research date:** 2026-11-10  
**Scope:** long-horizon memory, generalist skill transfer, realtime VTuber interaction, gaming, game creation, and low-VRAM inference  
**Status:** evidence-led design research. This document does not claim deployed runtime integration or measured performance gains.

## Executive finding

STAR already has broad offline evaluation work: continual-learning transfer (#1109), cross-engine game-creator evaluation (#1108), real-time scenario-balanced gameplay (#1093), a cross-modal stream timeline (#1103), end-of-turn/voice evaluation (#1105–#1107), and measured model-quality/speed gating (#1102). The highest-value next step is to connect these systems without duplicating them.

The newest research changes one important design assumption: a memory policy can score well on a proxy for consolidation quality and still fail to transfer to real downstream tasks. STAR should therefore separate (1) whether an experience is useful, (2) whether it is safe and justified to consolidate, and (3) whether the resulting memory actually improves future tasks.

## 1. Memory: consolidate state, not a transcript dump

### The Epistemics of Agent Memory (2026-09-26)

The four-phase study investigates episode segmentation, abstraction under a token budget, a benchmark for consolidation decisions, and governed consolidation. It reports a +22.7% task-success improvement with 7x compression in one phase, but also exposes degenerate forgetting and distribution-shift failures. Its ConsolidationBench results show that production retrieval systems can retain information yet fail cross-level transfer. Most importantly, the paper reports that its consolidation-quality score did not predict real transfer accuracy in a two-benchmark study of 2,532 answer cells (pooled Spearman rho = -0.24, n = 12, confidence interval spanning zero). It also reports governance as statistically distinct from the quality score.

Source: https://arxiv.org/abs/2609.33013

**STAR application**

- Preserve immutable, append-only experience records; never silently rewrite the historical observation.
- Treat consolidation as a separate, reviewable operation that proposes a new episodic, semantic, causal or procedural abstraction.
- Store source/provenance digests, observed outcome, environment/model/project revision, confidence, conflicts, expiry/revalidation date and the prior snapshot digest.
- Keep hypotheses, model-generated explanations and independently verified observations as different record types.
- Require poison-resistance checks, reversibility, auditability and a rollback snapshot before any candidate can be considered for promotion.
- Do not use a single memory-quality score as a promotion oracle. Keep downstream transfer, interference, retention, provenance quality and governance as separate measurements.
- Default to owner review; never let a model-generated memory proposal directly rewrite trusted memory or alter permissions.

The paper's reported percentages are results from its own experiments, not a forecast of STAR's gain. The negative transfer result is especially important: a good-looking consolidation score is not proof that the abstraction helps real tasks.

### LongMINT: memory under revision and interference (2026-05-18)

LongMINT studies evolving, highly interconnected memory across state tracking, dialogue, Wikipedia revisions and GitHub histories. Its dataset contains 15.6k QA pairs, with contexts averaging 138.8k tokens and reaching 1.8M. The paper reports 27.9% average accuracy across seven evaluated systems, with multi-target aggregation and facts revised by later updates being particularly difficult. Its analysis identifies retrieval and memory construction as major bottlenecks.

Source: https://arxiv.org/abs/2605.18565

**STAR application**

- Represent facts as versioned claims with valid-from, valid-until, observed-at, source revision and supersedes/conflicts-with links.
- Do not overwrite a previous fact when a newer fact arrives. Mark the old claim as superseded while retaining its historical validity interval.
- Retrieval must answer “what is true now?” and “what was true at revision/time X?” differently.
- Multi-target questions should collect all required evidence first, then reason over the set; a single nearest-neighbour hit is insufficient.
- Add adversarial tests where a later commit, project setting, API version or user correction changes an earlier fact.
- Measure stale-answer rate, contradiction rate, multi-evidence aggregation accuracy, retrieval latency and context tokens separately.

### Connect this to existing STAR work

PR #1109 already provides paired memory-off/memory-on streams, dependent transfer probes, independent interference probes, retention probes and stream-level statistics. Extend its task roster with revision/interference cases rather than creating a second generic memory benchmark. Keep the model, runner, prompt, tool policy, context budget and grader fixed between arms. Use held-out tasks and keep answer keys outside model context.

PR #1103 already provides a bounded, event-bound stream timeline. It is a natural source for short-lived live episodic events, but raw audio, transcripts, viewer identities and private messages should not become generic durable memory by default.

## 2. VTuber: natural turn-taking is a two-objective problem

### LiveKit End-of-Turn Benchmark

The public EOT-Bench contains real human-to-agent turns across 14 languages and annotates mid-turn pauses separately from true turn endings. It evaluates a policy frontier: how much conversational delay is needed to stay under a specified false-cutoff budget. It explicitly warns that a detector can appear fast by interrupting people too early; inference speed and endpointing delay are different measurements.

Source: https://github.com/livekit/eot-bench

**STAR application**

Track at least:
- false-cutoff rate at fixed response-delay budgets;
- median and p95 delay after true turn endings;
- missed turns and missed addressees;
- backchannel false-interruption rate;
- interruption recovery and speech-resume success;
- multi-party floor accuracy;
- grounded response rate and ungrounded commentary;
- audio underruns and first-audible p50/p95.

Use the existing voice/turn-taking work rather than a single human-likeness score. A natural AI streamer should be transparent about being AI, preserve silence when appropriate, avoid interrupting two viewers who are talking to each other, and recover cleanly from false interruptions.

### Runtime architecture

Keep a low-latency audio/turn loop, a game-control loop, and background research/creation loops separate. Use a typed event timeline with monotonic sequence numbers, freshness/expiry, confidence, privacy class and correlation IDs. Each queue must be bounded. Coalesce stale vision events, expire optional commentary and reject stale game actions. A long research or Blender task must never block audio callbacks or the game input path.

Keep persistent persona configuration (voice, humor, interests, boundaries, style) separate from temporary stream state (current game, objective, conversation floor, scene and recent events). Map observable context to explicit avatar expression controls; lip-sync against actual output audio/phoneme timing. Do not treat expression labels as proof of subjective feelings.

## 3. Gaming: evaluate skill on the live clock

STAR's existing real-time gaming work already distinguishes paused reasoning from live gameplay and checks scenario balance. Preserve that distinction. Use external game benchmarks as task sources, but keep STAR's own trusted game-state oracles and held-out maps as the acceptance authority.

Recommended curriculum:
1. Learn controls and movement in a safe tutorial.
2. Acquire one mechanic (timing, aiming, navigation, resource management).
3. Test it on a new map/seed.
4. Introduce distractors and adversarial conditions.
5. Compare progress, objective success, deaths/failures and action-ack p95 per scenario.
6. Retest after a delay to measure retention.
7. Transfer the mechanic to a different game only when the control semantics are genuinely comparable.

Never infer mastery from a lucky win or repeated attempts on one easy map. Report per-scenario metrics and effective scenario diversity; keep game-control authorization separate from skill advice.

## 4. Game creation: close the plan/build/playtest loop

Roblox's April 15, 2026 Studio announcement describes agentic plan/build/test workflows and a playtesting agent that can inspect code/data, read logs and use a player character to test behavior. Roblox's current Studio MCP/Open Cloud documentation states that permissions are per game and that the owner controls enabled scopes; Full access includes actions that can affect players, spend Robux or publish to a live game.

Sources:
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- https://create.roblox.com/docs/studio/mcp-open-cloud

**STAR application**

- Default to Safe/read-only scopes and private test places.
- Separate inspect, edit, upload, data-store, purchase and publish permissions.
- Never let a model enable its own permissions.
- Build from a structured plan and task graph; use independent specialist agents only when file ownership and test boundaries are explicit.
- Run static checks, engine playtests, log analysis, visual inspection, regression tests and a final human review.
- Keep publish/live-server operations behind owner approval.

Extend the existing GameDevBench and Studio evaluation rather than creating another generic code-generation score. Track runtime success, visual correctness, interaction correctness, regression count, repair count and completion time by category.

## 5. Local inference: optimize the complete mixed workload

The current llama.cpp MoE-cache documentation describes caching hot experts in device memory while keeping other experts in host memory. It exposes the options --moe-cache-mib and --moe-cache-cpu-share; the documentation explicitly says the best CPU share depends on machine, model, cache size and whether host weights are pinned.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

**STAR application for an 8 GB GPU**

- Establish a reproducible baseline with the exact model, quantization, context, batch, prompt trace, server slots and hardware.
- Compare no cache, prompt-prefix cache, speculative decoding and MoE cache one change at a time.
- Tune MoE cache size and CPU share on the actual CPU/RAM/PCIe path; do not copy a number from an RTX 4090 or another host.
- Measure TTFT, inter-token p50/p95, completion latency, output quality, CPU time, RAM, VRAM, game frame-time, OBS render/encode lag, avatar frame drops and TTS first-audible latency simultaneously.
- Include cold start, warm steady state, long-context and concurrent request conditions.
- Reject an optimization that raises token throughput but causes game stutter, audio underruns or poorer answers.
- Preserve a known-good configuration and roll back automatically on statistically meaningful quality or stability regressions, with owner review before any default changes.

A MoE cache can help a particular host/model path; it is not a universal speedup. Draft acceptance rate, GPU utilization and tokens/second alone are not sufficient.

## 6. Generalist knowledge and skill acquisition

Use a source-aware knowledge graph rather than one undifferentiated vector store:

- concept: definition, prerequisites, related concepts and scope;
- claim: source span, confidence, valid-time interval, counterevidence and freshness;
- source: identity, author/institution, publication/update date, license and retrieval date;
- skill: prerequisites, procedure, tools, tested examples and known failure modes;
- experience: task, environment digest, action, observed result and independently verified outcome.

A new skill should include a minimal reproducible example, positive test, edge/negative test, held-out transfer probe and “when not to use it” note. Curriculum graphs should measure prerequisite mastery, retention and cross-domain transfer in mathematics, science, history, engineering, languages, programming, art, music, game design, 3D, media literacy and practical computer operation.

## 7. Recommended implementation sequence

1. Fix the current rehearsal-gate regression fixtures and require the full offline suite to pass.
2. Add a standalone, host-signed memory-consolidation governance gate; keep it separate from the #1109 utility evaluator.
3. Add revision-aware claim validity and multi-target interference probes to the existing memory benchmark.
4. Connect trusted adapters to the existing event timeline and voice/game/OBS evidence lanes.
5. Run paired inference trials on the target 8 GB machine under the full game + OBS + avatar + TTS load.
6. Run private held-out gaming and creator tasks with independent oracles.
7. Conduct a private 60-minute rehearsal and review p50/p95, failures, audio/OBS quality, gameplay and task outcomes.

## Non-goals and proof boundaries

This research does not establish human-equivalent behavior, consciousness, autonomous safe publishing, improved game win rate, or a measured inference speedup. It does not authorize public streaming, game input, asset uploads, purchases or model changes. New runtime behavior should remain opt-in until its host adapter, permission boundary, tests and real target-hardware acceptance are complete.
