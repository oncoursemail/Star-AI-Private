# STAR Research: Trace Profiling, Interruption Recovery, Multiparty Streaming & Game Exploration

**Research date:** 2026-11-11  
**Implementation:** read-only profiler for AgentTrace schema v1  
**Status:** offline analysis primitive; host instrumentation and real-device acceptance remain separate

## Executive summary

STAR now has three complementary foundations in the development chain:

1. A bounded, privacy-safe trace ledger with parent/child spans and timestamped events.
2. Explicit adapters that attach validated aggregate measurements from inference, hardware, speech decisions, streaming arbitration, game learning and task checkpoints.
3. This update's read-only profiler, which converts one trace snapshot into a timing summary without exporting span attributes or source content.

The next bottleneck is not collecting more metrics. It is turning existing evidence into useful engineering decisions: which stage dominates the user-visible delay, how much work overlaps, where instrumentation is missing, whether an interruption loses task progress, and whether a game skill transfers to a new environment.

This document separates findings from hypotheses and describes the tests needed before changing runtime defaults.

## 1. New implementation: bounded trace profiling

### Files

- star/agent_trace_analysis.py
- tests/test_agent_trace_analysis.py

### What it computes

For each completed span:

- Inclusive wall duration: end minus start.
- Direct-child coverage: the union of completed direct-child intervals.
- Child overlap: sum of direct-child durations minus their interval union.
- Exclusive wall time: span duration minus direct-child coverage.

For each root span:

- Total duration.
- Child-covered wall time.
- Unattributed wall time not covered by direct child spans.
- Parallel overlap among direct children.

For each component:

- Completed span count.
- Nearest-rank inclusive p50, p95 and maximum duration.
- Nearest-rank exclusive p50, p95 and maximum duration.

It also reports open/completed/failed span counts, event counts, root spans and a bounded list of the slowest completed spans.

### Important interpretation rules

- Inclusive durations are not additive. A model span nested inside a request span is counted in both.
- Parallel sibling spans can overlap. Their summed durations must not be mistaken for elapsed wall time.
- Unattributed root time is time not covered by direct child spans. It is not proof of CPU idle time or a specific bottleneck.
- Exclusive time is local to each span. Exclusive values across overlapping siblings are not necessarily additive.
- Open spans are counted but are not assigned an estimated duration.
- Parent/child nesting alone does not establish all causal dependencies. The profiler deliberately does not invent a critical path.
- Event attributes are ignored. No prompt, transcript, viewer identity, screenshot, audio, model output, checkpoint payload or credential is copied into the profile.

The analyzer rejects malformed IDs, missing parents, cycles, impossible child timing, invalid clocks, duplicate event sequences, unknown events and oversized snapshots.

### Why this helps speed

The profiler makes the existing trace useful for answering questions such as:

- Did retrieval or model generation dominate this request?
- Did TTS begin before the model finished, or did it wait?
- Did voice and vision overlap with gameplay?
- How much of the request is not yet instrumented?
- Is apparent latency actually queue wait, tool time, synthesis time or playback time?

The profile is an analysis primitive, not a scheduler. It must not automatically change model routing, GPU admission, voice timing or broadcast settings.

## 2. Trace design and observability

OpenTelemetry describes a trace as related spans representing the path of a request. Spans carry start/end timestamps, parent context, events and status. Child spans provide more detailed timing for sub-operations.

References:

- https://opentelemetry.io/docs/concepts/signals/traces/
- https://opentelemetry.io/docs/specs/otel/trace/api/
- https://opentelemetry.io/docs/concepts/semantic-conventions/

### STAR application

Use a single request/session trace to correlate:

1. Input received.
2. Speech recognition or visual observation.
3. Turn/floor decision.
4. Memory retrieval.
5. Model selection and inference.
6. Tool execution.
7. TTS synthesis.
8. Speaker queue submission.
9. Device playback acknowledgement.
10. Avatar/lip-sync update.
11. Gameplay action and verified outcome.
12. OBS output sample.

Do not put arbitrary chat, transcripts, media, exception messages, URLs or credentials into trace attributes. A trace ID is correlation data, not an authorization token.

## 3. Multiparty streaming: conversational skill is more than speech generation

### MP-Bench — Findings of EMNLP 2026

MP-Bench evaluates voice agents as active participants in group conversations. Its paper reports that the 12 evaluated agents reached at most 22% multiparty comprehension and remained near chance on multiparty turn-taking.

Source:

- https://aclanthology.org/2026.findings-emnlp.1437/

**STAR implication:** dyadic voice benchmarks do not establish livestream social competence. Star needs explicit tests for direct address, side conversations, overlapping speech, viewer-to-viewer replies, group topic changes and situations where a human has already answered.

### Adaptive Turn-Taking for Real-time Multi-Party Voice Agents

The ModeratorLM research conditions turn-taking on an explicitly assigned role and reports substantial precision/recall improvements over its non-role-conditioned baselines. The paper uses real meeting data and a synthetic role-play corpus; transfer to a live gaming stream must be measured rather than assumed.

Source:

- https://arxiv.org/abs/2606.13544

**STAR implication:** make Star's social role explicit and stable: participating streamer, not meeting moderator, customer-service agent or always-on narrator. Role should influence whether she speaks, acknowledges, yields or stays silent.

### Recommended social decision set

1. Answer a direct question.
2. Acknowledge a short backchannel.
3. React nonverbally.
4. Listen while viewers speak to one another.
5. Stay silent after a human has resolved the question.
6. Yield to a genuine interruption.
7. Resume only when the current conversational context still supports the response.

Speaker attribution should use platform/session identifiers where available. Do not infer real-world identity from voice or store voiceprints by default.

## 4. Interruption recovery: preserve the task, not just the turn

### IHBench — June 17, 2026

IHBench studies post-interruption recovery in structured, multi-step workflows. It distinguishes interruption timing from what happens afterward: whether the agent addresses the interruption, resumes at the correct step and avoids repeating content already delivered. The paper evaluates six interruption types across ten domains and scores task fulfillment and recovery quality separately.

Source:

- https://arxiv.org/abs/2606.19595

**STAR implication:** a successful barge-in detector is not enough. Star must recover the task state after the viewer interruption.

### Recommended interruption state machine

- ACTIVE: current task is progressing.
- PAUSING: stop new side effects and capture a checkpoint.
- RESPONDING: handle the new conversational turn.
- REVALIDATING: check whether the original task is still current and safe.
- RESUMING: continue from the last verified checkpoint.
- SUPERSEDED: abandon the old task because the owner changed the goal.
- COMPLETED: task finished and its result was verified.

A checkpoint should identify the task revision, last verified step, pending dependencies and expiry/freshness conditions. It should not blindly replay tool calls or side effects.

Before resuming:
- confirm the task revision is still current;
- re-read mutable external state;
- reject stale prepared speech;
- do not repeat audio already acknowledged as played;
- require fresh authorization for consequential actions;
- preserve partial work as partial, not success.

STAR already has task checkpoint and durable coordinator work in the repository. The next step is a narrow adapter between those systems and the streaming session, not a duplicate task database.

## 5. Roblox and game creation: exploration before editing

### OpenGameEval — October 1, 2026

OpenGameEval evaluates agents inside reproducible, stateful Roblox Studio sessions. It separates observation tools from editing tools and checks both the resulting scene and simulated gameplay. Its study covers 84 human-curated tasks, 13 frontier models and 16 attempts per task.

The authors report that runs inspecting every object touched by the reference solution passed more often than runs inspecting none: 13.4 percentage points on scene-only tasks and 9.8 points on script-only tasks in their evaluated setting. This is an association in that benchmark, not a guaranteed STAR improvement.

Sources:

- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

### Roblox first-party direction

Roblox describes an agentic Plan → Build → Test workflow, including Studio MCP access and playtesting that inspects code, the DataModel and logs while simulating a player.

Sources:

- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- https://create.roblox.com/docs/ai/accelerated-workflows

### STAR Creator recommendations

Before editing:
- inspect the project tree and relevant instances;
- identify the exact Studio instance and project revision;
- inspect scripts, dependencies and existing conventions;
- create a short plan with acceptance criteria.

After editing:
- run static checks;
- start an isolated playtest;
- exercise the requested mechanic;
- inspect output/logs and actual scene state;
- test regression cases;
- compare against the original acceptance criteria.

Keep observation and mutation tools separate. Studio IDs and project revisions must be explicit. Live publishing, economy changes, moderation, player data and external side effects remain separately authorized.

## 6. Gaming intelligence: test transfer, not memorization

A reusable gaming skill should include:

- Preconditions and state features.
- Allowed actions.
- Expected state transition.
- Failure conditions.
- Safety constraints.
- Independent success evidence.
- Game/version/environment identity.
- Held-out transfer results.

### Proposed learning loop

Observe → hypothesize → choose an informative action → predict the next state → act → compare prediction with observation → update the skill → test on a held-out state.

A verbal explanation is not evidence of mastery. A button sequence that works on one level is not proof of a transferable mechanic.

Keep separate scorecards for:
- Game understanding.
- Action selection.
- Mechanical execution.
- Objective completion.
- Team coordination.
- Skill transfer to unseen levels/seeds.
- Robustness after patches or control changes.

Use private/sandbox environments for exploration. Live multiplayer actions that affect other players or accounts require explicit owner policy and authorization.

## 7. Inference speed: optimize the user-visible path

llama.cpp's SPEED-Bench client is designed to compare an already-running server and report category-level throughput, latency and speculative draft acceptance.

Source:

- https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

Speculative decoding is workload-dependent. Drafting can help when proposed tokens are accepted efficiently, but extra draft-model work and memory pressure can make it slower in other configurations.

### STAR's recommended order

1. Avoid interactive-model reloads during a stream.
2. Keep prompts and context appropriately bounded.
3. Reuse stable prefixes only when measured cache hits occur.
4. Measure prefill and decode separately.
5. Test quantization against answer quality as well as tokens/second.
6. Test speculative decoding by task category and prompt type.
7. Measure KV-cache memory and transfer before enabling offload/quantization.
8. Cap background concurrency to protect voice, game frame times and OBS.
9. Route simple tasks to smaller/faster models only when held-out quality remains acceptable.
10. Re-run the same workload after every model/runtime update.

### Required paired workload matrix

- Model only.
- Game only.
- Voice only.
- Game + voice.
- Game + voice + avatar.
- Full OBS stream.
- Full stream + background research/agents.

Record p50/p95/p99 first-content latency, first-audible latency, inter-token or chunk timing (label the measurement correctly), task quality, VRAM, RAM, CPU, game frame-time p95/p99, audio underruns and OBS render lag.

A speed change is accepted only if it improves the intended metric without unacceptable regressions in quality, audio or gameplay.

## 8. Human-natural streaming: capabilities and honesty

A compelling AI streamer should have:
- A stable, recognizable persona and interests.
- Memory of prior stream topics and recurring community context.
- Natural turn timing and the ability to remain silent.
- Reactions grounded in actual game state.
- Expressive voice and avatar animation synchronized to audible playback.
- Contextual humor and self-correction.
- Clear recovery after interruptions.
- A way to say "I don't know" and research a question.
- Transparent AI identity; natural presentation should not rely on deceiving viewers into believing she is human.

Avoid optimizing for constant speech. Measure relevance, interruption precision, silence preservation, recovery quality, audible latency and viewer-perceived naturalness separately.

## 9. General knowledge and continual learning

Build domain curricula for programming, mathematics, science, history, geography, languages, art, music, engineering, psychology, economics, game design and current events.

Each retained knowledge item should have:
- Source/provenance.
- Acquisition date.
- Last-verified date.
- Scope and version.
- Confidence/uncertainty.
- Contradictory evidence.
- A refresh policy.

Each promoted skill should pass independent tests and held-out examples. Preserve the previous version for rollback. Self-critique can propose tests, but should not be the only judge of its own success.

## 10. Phased implementation roadmap

### Phase A — profiling foundation (this PR)
- Parse AgentTrace snapshots.
- Validate parent/child structure and timestamps.
- Report inclusive/exclusive durations, overlap and component distributions.
- Export only aggregate profile data.
- Add deterministic offline regression tests.

### Phase B — real runtime adapters
- Instrument model request spans.
- Add trusted TTS/audio-device acknowledgements.
- Add avatar playback-epoch timing.
- Connect OBS and actual frame-present samples.
- Keep callbacks non-blocking; no trace analysis on audio/render hot paths.

### Phase C — interruption recovery
- Bridge stream session state to existing durable task checkpoints.
- Add revision/freshness checks and no-replay rules.
- Evaluate with IHBench-inspired interruption scenarios.

### Phase D — social intelligence
- Add role-conditioned floor policy.
- Evaluate multiparty comprehension, direct address, silence and human-resolution behavior.
- Use consented test conversations and session-scoped speaker IDs.

### Phase E — game and creator intelligence
- Integrate OpenGameEval in an isolated Roblox test environment.
- Measure exploration quality and verified playtest outcomes.
- Add held-out game-mechanic transfer tests.

### Phase F — measured optimization
- Use trace profiles to identify the slow stage.
- Run paired inference configurations.
- Promote only quality-preserving, reproducible improvements.

## 11. Acceptance gates

A private 60-minute stream rehearsal should verify:

- Multiple viewers can speak and address one another.
- Star distinguishes direct questions from side conversations.
- She does not interrupt every pause or acknowledgement.
- She stops when a human has already answered.
- She resumes an interrupted research/build task from the correct verified step.
- She does not replay already delivered speech.
- Lip-sync follows audible playback rather than text generation.
- Gameplay and OBS remain within agreed frame-time/render budgets.
- Background research cannot starve speech or gameplay.
- A new game mechanic is tested on a held-out state before promotion.
- A Roblox build passes both scene checks and simulated playtest.
- Knowledge claims retain provenance and freshness.

## 12. Validation boundary

This PR adds a pure in-process analysis function and offline tests. It does not install an exporter, network client, UI, polling loop, Windows hook, OBS integration, VTube Studio integration, microphone capture or Roblox controller. It does not change model routing, game controls, permissions, broadcast settings or production defaults.

No inference speedup, intelligence gain, human-equivalent behavior, live-stream readiness or game mastery is claimed. Those require completed CI, host integration, paired benchmarks and private hardware acceptance tests.
