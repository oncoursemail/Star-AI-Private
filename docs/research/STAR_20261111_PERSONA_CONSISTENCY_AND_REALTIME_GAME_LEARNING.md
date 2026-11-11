# STAR 2026-11-11 — Persona Consistency, Idempotent Affect, and Real-Time Generalist Learning

**Status:** research and engineering proposal for the private development branch.  
**Scope:** observable behavioral consistency, not a claim of human identity, consciousness, or subjective emotion.

## Executive summary

STAR already has separate workstreams for memory transfer, reversible memory consolidation, multiparty turn-taking, voice delivery, game mastery, game creation, inference measurement, and mixed-workload acceptance. The next useful step is to make those lanes agree on one coherent interaction policy without collapsing their measurements into a misleading “human-likeness” score.

This pass also fixes a concrete duplicate-event defect in STAR Home: a goal-completion event could be followed by a second generic success event for the same session. Duplicate affective events can overstate the importance of one event and create repetitive avatar reactions. The loop now treats a verified goal-completion signal as the authoritative event for that session and suppresses the redundant generic signal.

## 1. Research: memory-grounded persona consistency

### HEART-Bench — 28 May 2026

Paper: https://arxiv.org/abs/2605.30058

HEART-Bench studies whether an agent makes decisions consistent with a target persona and its autobiographical memories. Its published setup contains 11 synthetic characters, 1,000 structured memories per character, 64 decision scenarios, and 673 multiple-choice questions. The abstract reports near-chance performance without memories and a best memory-augmented configuration of 64.9%; on a matched subset, human annotators reached 80.8% while the best model reached 64.0%.

**Design implication for STAR:** a static persona paragraph is not enough. When a decision genuinely depends on a past experience or accepted preference, retrieve the smallest relevant, provenance-bearing memory set. Do not inject a large autobiography into every turn: that adds prefill cost, increases distraction, and can make unrelated factual tasks worse.

Recommended memory record classes:

- Stable persona commitments: versioned, owner-reviewed, and rarely changed.
- Accepted preferences: source, timestamp, confidence, scope, and expiry/review policy.
- Episodic experiences: what happened, what was verified, and the evidence reference.
- Procedural skills: reusable methods with preconditions and test coverage.
- Tentative hypotheses: explicitly unverified and never presented as established facts.

For a persona-sensitive decision, retrieval should be relevance- and recency-aware, include contradictory or superseding evidence when present, and allow abstention when evidence is insufficient. Preserve the existing memory-off/on controlled evaluation and reversible consolidation gate; a memory that makes a response sound more consistent is not automatically a memory that improves task quality.

## 2. Research: social interaction without persona collapse

### MASCOT — EMNLP 2026

Paper and implementation: https://github.com/hello-diana/MASCOT  
Paper: https://arxiv.org/abs/2601.14230

MASCOT separates individual persona alignment from group-level dialogue coordination. Its reported evaluations emphasize persona consistency, social contribution, complementary turns, and reducing redundant agreement. The project uses a director policy to decide which speaker should contribute and what conversational action or tone is appropriate.

**Design implication for STAR:** the Social Director should decide whether a contribution is useful before asking the response model to generate one. It should consider:

1. Is the speaker addressing STAR, another viewer, or the whole group?
2. Has the question already been answered?
3. Is STAR's contribution additive, corrective, clarifying, or merely repetitive?
4. Is the moment appropriate for speech, a nonverbal cue, or silence?
5. Is the current game state too critical for optional commentary?

Keep persona fidelity and group contribution as separate evaluation lanes. A response can be in-character but socially unnecessary; a useful response can still be out of character.

Do not copy MASCOT's multi-agent training stack or datasets into STAR by default. Its reported results are tied to its own models, data, training procedure, and evaluation. First reproduce the relevant evaluation ideas with STAR's local, opt-in infrastructure.

## 3. Research: real-time game mastery needs two clocks

### SIMA 2 — Google DeepMind, 13 November 2025

Official research: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/  
Technical report: https://arxiv.org/abs/2512.04797

SIMA 2 combines language-level goal reasoning with embodied action across multiple 3D worlds. DeepMind describes using demonstrations, generated tasks, feedback, and self-directed practice to improve behavior in new environments.

### LOLPlay — submitted 25 October 2026

Paper: https://arxiv.org/abs/2611.03685

LOLPlay evaluates visual agents in native League of Legends using 36 champion-specific tasks and 82 executable subgoal checks. Its reported experiments found that higher reasoning effort did not improve success for the tested models; longer requests could reduce the number of available interaction rounds. This is a useful warning that more deliberation is not automatically better in a live environment.

**Design implication for STAR:** use two coordinated clocks.

- Reactive loop: consume a fresh observation, select a small action, enforce a short action expiry, and re-observe. It owns movement, immediate hazards, aiming, dodging, and time-sensitive inputs.
- Strategic loop: asynchronously plan objectives, route, inventory, team strategy, and learning goals. It proposes plans but cannot issue stale actions directly.

Every action should be bound to the observation version and game/session epoch that justified it. If the scene changes, the action expires. After a meaningful action, verify the expected state transition rather than assuming the input succeeded.

Build transferable skill primitives—navigation, camera control, interaction, resource collection, timing, combat spacing, inventory use, and objective tracking—then test them in held-out maps and unfamiliar games. Store failed attempts as evidence for a new practice task, not as proof that a skill was learned.

## 4. Research: turn-taking is a latency/false-cutoff tradeoff

LiveKit's current audio turn-detector documentation describes a 300 ms minimum and 2.5 s maximum endpointing window with the detector, requires at least 250 ms VAD silence, and supports 14 languages when language metadata is available.

- Documentation: https://docs.livekit.io/agents/logic/turns/turn-detector/
- EOT benchmark: https://github.com/livekit/eot-bench

The EOT benchmark explicitly treats false cutoffs and conversational dead air as competing objectives. A policy can trivially reduce one by making the other worse.

**Design implication for STAR:** calibrate per language and conversation type on disjoint conversations. Measure false cutoffs, missed turns, decision delay, first audible PCM, interruption-to-silence, and avatar stop latency separately. Do not use server text-generation time as a substitute for listener-perceived latency.

The existing semantic endpointing, multiparty floor, voice-delivery, and cross-lane rehearsal work should remain opt-in until a trusted Windows adapter supplies real microphone, speaker, avatar, and OBS observations.

## 5. Research: Roblox creator loop and permission boundary

Roblox's 15 April 2026 agentic Studio announcement describes a plan/build/test loop with playtesting and feedback into subsequent planning. The 4–5 November 2026 Studio MCP/Open Cloud documentation makes permissions per-game and per-person, including separate scopes, upload folders, DataStore access, and HTTP-domain allowlists.

- Plan/build/test: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- Studio MCP/Open Cloud permissions: https://create.roblox.com/docs/studio/mcp-open-cloud

**Design implication for STAR Creator:**

1. Inspect the actual place, scripts, hierarchy, and current state.
2. Write a plan with observable acceptance criteria.
3. Change only the authorized disposable test place.
4. Run playtests and inspect logs, state, and screenshots.
5. Repair the smallest failing part.
6. Retest on the same and at least one held-out scenario.
7. Publish only through a separate explicit owner-controlled step.

Use Safe or narrowly scoped Custom permissions for routine work. Full access is not a default: some scopes can affect live players, Robux, products, or publishing.

## 6. Speed research: optimize the actual 8 GB mixed workload

NVIDIA's TensorRT-LLM disaggregated-serving documentation explains why prefill and decode can interfere when they share a GPU, and how separate GPU pools can independently optimize TTFT and token-to-token latency:

https://nvidia.github.io/TensorRT-LLM/features/disagg-serving.html

That architecture is primarily a multi-GPU / multi-worker serving pattern. It is **not** a drop-in optimization for STAR's single 8 GB RTX 4060. KV transfer and extra server processes can cost more than they save on a constrained local machine.

For STAR's local hardware, prioritize:

- One measured interactive inference path; do not load several large models merely to create more agents.
- Short, stable system prefixes and prompt-cache reuse where the backend confirms it.
- KV-cache settings sized from measured context length and memory headroom.
- Quantization and CPU/GPU layer placement tested against answer quality.
- Small specialist models for bounded classifiers only when their CPU/GPU cost is lower than the work they save.
- Deadline-aware scheduling: speech and fresh game perception ahead of optional research, indexing, rendering, and practice.
- GPU reservations that remain held until the host confirms the worker actually stopped.
- Paired model comparisons that retain failed requests and evaluate quality, first content, first audible PCM, p95 latency, game frame-time, OBS drops, and memory pressure together.

Tokens/second alone is not the objective. The objective is the best verified task quality while the game, OBS, voice, and avatar remain responsive.

## 7. Persona and affective event integrity

STAR should be expressive without pretending to be a human. Keep the persona stable through a small, versioned behavior contract; let delivery vary naturally with context. Treat emotion labels as application state used to choose permitted expression, not as proof of subjective feeling.

Engineering rules:

- One verified event should create at most one corresponding affect transition.
- Every event needs a stable session-scoped identifier or deduplication key at the host boundary.
- Goal completion and generic task success must not both amplify the same outcome.
- Expression intensity should decay and be rate-limited; silence and neutral listening are valid.
- Nonverbal listening cues must not silently become spoken replies.
- The avatar's mouth and speaking state must follow actual audible playback and stop receipts, not merely a generated text plan.
- Persona memories and viewer-private information must remain separate; raw viewer audio/chat should not become generic durable memory.
- When STAR is uncertain about a person's intent or an event's meaning, prefer a small neutral cue or silence over an invented reaction.

## 8. Existing STAR work to integrate rather than duplicate

The repository already has active draft work for:

- Skill retrieval and offline retrieval evaluation (#1121).
- Multiparty floor evidence and calibration (#1107).
- Cross-modal stream event context (#1103).
- Continual-learning memory transfer (#1109).
- GameDevBench creator evaluation (#1108).
- Model quality/speed gating and llama.cpp metrics (#1101, #1102).
- Deadline-aware stream dispatch (#1110).
- Reversible memory consolidation (#1117).
- Signed cross-lane rehearsal acceptance (#1116).
- Process containment, durable coordination, and artifact staging (#1111–#1120).

Keep these as distinct reviewable capabilities. The main integration gap is the trusted Windows host adapter and a private mixed-workload rehearsal, not another large collection of disconnected evaluators.

## 9. Acceptance plan

A private, nonbroadcast rehearsal should report separate results for:

| Lane | Required evidence |
|---|---|
| Persona | human-reviewed trait/stance/style consistency; factuality remains separate |
| Memory | relevant-memory precision, contradiction rate, stale-evidence rejection, memory-off/on transfer |
| Social | addressee accuracy, redundant-response rate, correct silence, turn-taking and interruption |
| Voice | first audible PCM, p50/p95 delivery latency, cutoff rate, stop/flush confirmation |
| Avatar | expression/voice synchronization, duplicate expression rate, reduced-motion behavior |
| Gaming | held-out objective completion, per-scenario progress, action latency, stale-action rejection |
| Creator | build/test pass rate, visual defect rate, regression rate, engine/version identity |
| Inference | first content, inter-token gaps, end-to-end p95, memory/VRAM, quality parity |
| Mixed workload | game frame-time, OBS render/network drops, audio underruns, and background-work preemption |

A lane with missing or stale telemetry is inconclusive, not a pass. A passing offline evaluator is not a live-stream acceptance. A cross-lane rehearsal can recommend owner review only; it must never enable public broadcasting, publish a game, change model routes, or widen permissions.

## 10. Next engineering order

1. Land and test the duplicate goal-completion event fix.
2. Complete the current skill-retrieval, multiparty-floor, memory-transfer, creator, and inference PR checks.
3. Add selective persona-memory retrieval to an explicit decision path, then evaluate it against memory-off on disjoint scenarios.
4. Connect the Social Director to trusted Windows audio/addressee receipts.
5. Connect the reactive game loop to versioned observations and expiring actions.
6. Run the eight-lane private rehearsal on the actual target PC.
7. Only after repeated, reproducible success, request owner review for any opt-in runtime change.

**No benchmark result in this document is a STAR result.** External papers motivate experiments; STAR must earn its own measurements on its own models, code, games, and hardware.
