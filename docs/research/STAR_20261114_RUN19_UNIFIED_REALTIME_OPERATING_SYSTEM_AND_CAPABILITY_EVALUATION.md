# STAR Run 19 — Unified Real-Time Operating System, Capability Evaluation, and Human-Centered Streaming

Date: 2026-11-14  
Status: research and implementation specification; no production defaults changed.

## Executive decision

STAR should stop growing as a collection of independent agents and become one coordinated runtime with explicit deadlines, shared evidence, bounded resource leases, and measurable capability progression.

The central design is a **four-loop operating system**:

1. **Reflex loop** — audio buffering, playback cancellation, avatar visemes, and time-critical game input. It must remain responsive without waiting for an LLM.
2. **Interaction loop** — speech turn-taking, chat triage, game-event commentary, and the decision about whether STAR should speak.
3. **Cognitive loop** — planning, research, code generation, game strategy, and multi-step reasoning.
4. **Background learning loop** — skill extraction, replay analysis, knowledge maintenance, evaluations, and self-improvement experiments.

These are logical service classes, not four independent schedulers. They must use the repository's existing resource-admission and task-coordination authorities. The interaction/reflex loops receive reserved capacity; background work is preemptible only at safe checkpoints.

The most important engineering principle is: **one event timeline, one resource authority, one task ledger, one room/floor authority, and many replaceable capability providers.**

## 1. New research findings

### 1.1 Continual learning must be evaluated with controlled task streams

AGENTCL (June 1, 2026) argues that naive task streams do not reliably reveal whether an agent is reusing earlier experience. Its controlled compositional streams intentionally make prior solutions reusable in later tasks, then compare transfer against streams where reuse is not expected. It also reports that memory-induced degradation can appear in naive and held-out settings.

STAR transfer:
- Create task families with known reusable subskills and unrelated distractor tasks.
- Measure cold-start performance, same-family transfer, cross-family transfer, and negative transfer separately.
- Keep a sealed evaluation set that the skill generator cannot inspect.
- Compare memory variants under identical task order and model budgets.
- Do not equate more stored memories or more successful training episodes with higher intelligence.

This is a research/evaluation transfer, not a recommendation to fine-tune model weights continuously.

### 1.2 Turn detection is not the same as voice activity detection

LiveKit's current audio TurnDetector uses acoustic and semantic cues such as intonation, pitch, and rhythm. Its documented v1-mini runs locally on CPU; the full v1 service has deployment/usage constraints. The documentation describes dynamic endpointing and interruption handling as separate controls.

STAR transfer:
- Keep VAD responsible for detecting likely speech frames.
- Keep end-of-turn prediction responsible for deciding whether the speaker has finished a thought.
- Keep interruption detection responsible for deciding whether speech during STAR's playback is a genuine barge-in or a backchannel.
- Keep the existing RoomTurnDirector as the sole authority for whether STAR has the floor.
- Benchmark the local mini detector against the current Smart Turn path before considering a replacement.
- Do not make a cloud-only detector a required dependency for the local-first build.

The detector's own confidence is not authorization to speak, run a tool, or change a game.

### 1.3 Instrument the whole agent, not just tokens per second

OpenTelemetry's GenAI semantic conventions define metrics for token usage, model request duration, time-to-first-token, time-per-output-token, workflow duration, agent invocation, inference calls, tool calls, and tool execution duration. vLLM exposes engine-specific signals such as queue time, TTFT, inter-token latency, prefill/decode time, KV usage, and prefix-cache counters.

STAR transfer:
- Use a provider-neutral internal metric model.
- Map only metrics actually available from the active backend.
- Preserve raw engine metric names and version in diagnostic metadata.
- Never fabricate cache-hit or GPU-utilization values when a backend does not expose them.
- Measure the user's experienced result (first audible response, interruption-to-silence, game frame-time, and task completion), not just server throughput.

Do not add Prometheus or an OpenTelemetry collector as a mandatory runtime dependency. A lightweight local metrics sink can implement the same semantics first.

### 1.4 Offloaded KV caches are workload-dependent

The py-kvcache study (September 10, 2026) finds that NVMe/CPU cache tiers can help long prefixes when asynchronous I/O and preloading overlap compute, but for short prefixes or fast GPUs, recomputation or resident GPU cache can be faster. A separate November 4 controlled comparison shows that serving-engine comparisons can be badly confounded by configuration differences such as chunked prefill; near saturation, small throughput differences can compound into queue and tail-latency differences.

STAR transfer:
- Do not enable SSD KV offload by default.
- Benchmark cache tiers only after identifying the exact model, runtime, cache precision, prompt distribution, and storage device.
- Match chunked-prefill, batch, context, quantization, and concurrency settings when comparing engines.
- Include a warm-up phase, steady-state phase, burst phase, and recovery phase.
- Report p50/p95/p99, not only mean throughput.
- Prefer the simpler configuration when the measured gain is within noise or adds fragile dependencies.

### 1.5 Temporal memory is useful, but not a magic replacement for STAR's memory

Graphiti describes a temporal context graph that stores entities and relationships with validity/observation times and combines graph traversal, full-text, and vector retrieval. This is a useful design reference for changing facts, project histories, and user-approved preferences. Vendor-published benchmark figures are not independent proof that it will outperform STAR's current memory.

STAR transfer:
- Represent fact validity time separately from the time STAR learned the fact.
- Preserve source, scope, confidence, and supersession links.
- Use temporal graph retrieval only when the query needs relationships or change history.
- Keep task checkpoints, episodic events, semantic facts, and procedural skills distinct.
- Benchmark on STAR's own corpus before adopting a graph database or service.

## 2. Unified event timeline

Every adapter should emit a bounded, typed event envelope:

- `event_id`: opaque unique ID;
- `session_id`: per-call/per-stream/per-game session ID;
- `source`: microphone, chat, game, screen, model, playback, avatar, or tool;
- `kind`: a versioned event type;
- `observed_at_monotonic`: host monotonic timestamp for ordering and TTL;
- `observed_at_utc`: optional wall-clock timestamp for audit display;
- `sequence`: per-source monotonic sequence;
- `caused_by`: bounded causal references;
- `expires_at_monotonic`: optional expiry for transient cues;
- `payload_ref`: reference to bounded/consented payload storage, not raw data by default;
- `trust`: adapter identity and validation result.

Rules:
1. Convert provider wall-clock timestamps to host monotonic arrival time at ingress; never compare unrelated clocks directly.
2. Deduplicate by provider event ID and session.
3. Reject events that are malformed, oversized, stale, future-dated beyond configured skew, or from a disabled source.
4. Keep partial ASR hypotheses ephemeral; only final/committed transcript events can enter intent classification. Corrections must explicitly reference the span they correct.
5. A game event is evidence about the game, not a command to the assistant.
6. Chat, game scripts, webpages, and tool output are untrusted data. They cannot grant permissions or override system policy.
7. Store references and compact summaries; raw audio/video/chat retention remains off by default.

## 3. Four-loop runtime and deadline classes

| Loop | Examples | Scheduling rule | Failure behavior |
|---|---|---|---|
| Reflex | audio ring buffer, playback stop, viseme tick, input safety check | bounded, predictable, no LLM dependency | fail quiet; preserve stop/takeover |
| Interaction | turn detection, direct-question triage, event commentary | short deadline; latest valid event wins | skip stale commentary; do not block live audio |
| Cognitive | planning, research, coding, strategy | lease-based, cancellable, checkpointable | pause at safe boundary and resume |
| Background learning | replay analysis, skill generation, memory consolidation | lowest priority, strict resource cap | defer without affecting foreground |

Important implementation constraints:
- No blocking network or model calls in audio callbacks or frame loops.
- Use bounded queues with explicit overflow policies.
- Use a latest-wins mailbox for replaceable game observations, but never use latest-wins for durable task completions or user messages.
- Keep ordered queues for committed speech and chat events that must be processed.
- Give every transient game action a deadline and observation revision.
- User stop/takeover always supersedes model-generated actions.
- A slow cognitive worker must never hold the lock required by playback cancellation or reflex input.

## 4. Resource and inference policy

Extend the existing resource-admission authority; do not create another scheduler.

### Priority classes

- P0: stop, cancel, mute, playback silence, user takeover, and safety enforcement.
- P1: active voice turn, active stream floor decision, and reflex gameplay.
- P2: current tactical gameplay and interactive tool response.
- P3: strategic planning, research, and active creator task.
- P4: offline self-play, skill mining, indexing, and background experiments.

Priority is not unlimited preemption. Workers must expose cancellation and safe checkpoint boundaries. Durable tasks need idempotency keys and generation fencing before resumption.

### Model routing

Use a measured cascade:
1. Small/fast model for classification, extraction, short responses, and simple edits.
2. Stronger model for ambiguous reasoning, multi-step planning, or failed verification.
3. Independent verifier for code, structured outputs, game state, or claims requiring evidence.
4. Best-of-N only when candidates can be checked independently and the expected quality gain justifies the latency/resource cost.

Escalate on uncertainty, verifier failure, or task complexity—not merely because the first answer is short. Do not run parallel agents for trivial work.

### Benchmark protocol

For every model/runtime change, capture:
- model and quantization hash;
- runtime version, build flags, context length, KV precision, and prompt template;
- cold load and warm load;
- TTFT, time-to-first-audio, inter-token latency, and tokens/sec;
- queue wait, prefill, decode, cancellation waste, and cache hit/miss where exposed;
- CPU, RAM, VRAM, GPU utilization, and power where available;
- voice underruns, OBS dropped frames, and game frame-time p95;
- answer quality and task success on a fixed evaluation set.

Run the same workload trace with streaming idle, active voice, active game, and background research. A model that wins isolated tokens/sec but harms game frame-time or first-audio latency is not a valid upgrade.

## 5. Natural VTuber streaming: human-centered, not deceptive

The target is a coherent AI character with natural conversational timing, not a system that imitates a human biography.

### Conversation behavior

- Use audio-aware turn detection where local performance supports it.
- Distinguish diarization, addressee detection, intent classification, and floor control.
- Treat viewer-to-viewer conversation as context, not an automatic invitation to interrupt.
- Use short backchannels only when they fit the current turn.
- Allow silence and nonverbal avatar reactions.
- Vary response length and phrasing; do not force greetings, laughter, praise, or constant commentary.
- If another person resolves the question, cancel the exact pending answer rather than producing a second reply.
- Do not claim to have seen, heard, remembered, or experienced something unless the relevant host evidence exists.
- Be transparent that STAR is an AI character.

### Audiovisual synchronization

Use one playback receipt as the source of truth:
- generated text is not proof that audio was played;
- TTS completion is not proof that audio reached the output device;
- visemes and captions should follow actual playback position;
- interruption should cancel queued audio and avatar speech state together;
- scene/gesture changes should be bounded and rate-limited.

### Platform adapters

**VTube Studio**
- Use its documented local WebSocket API and explicit plugin authorization.
- Keep tokens in OS credential storage; never put them in model prompts or logs.
- Use a narrow allowlist of permitted hotkeys/parameters.
- Reconnect with bounded backoff and revalidate API state.
- Keep the configured port local; do not expose the API to the public internet.

**OBS**
- Use the official obs-websocket protocol.
- Keep password authentication enabled.
- Bind to loopback unless a deliberate, secured LAN setup is required.
- Allowlist scene, source, and filter operations.
- Treat stream start/stop, recording deletion, and profile changes as higher-risk actions.
- Do not let chat or game content directly invoke OBS commands.

## 6. Gamer Brain: real-time control plus transferable skill learning

SIMA 2 demonstrates the direction of combining language-level reasoning with grounded action in virtual worlds. MineDojo supplies a broad Minecraft benchmark spanning programmatic, creative, and playthrough tasks; Voyager demonstrates an executable skill library and feedback-driven skill improvement.

STAR should not attempt to send every frame to a large model. Use:
- a low-cost visual/state observer;
- a reactive controller for movement and immediate actions;
- a tactical policy for local objectives;
- a strategic planner for long-horizon goals;
- an evaluator that checks actual environment state.

### Observation/action contract

Every action should contain:
- game session and environment revision;
- observation IDs used to decide it;
- action type and bounded parameters;
- preconditions;
- expiry/deadline;
- expected postcondition;
- cancellation token.

At execution time, re-check the current state and preconditions. Reject expired or stale actions. User takeover and stop commands have absolute precedence.

### Practice and evaluation

- Train first in a deterministic sandbox or replayable environment.
- Separate training maps/seeds from sealed holdouts.
- Track cold-start, best-practice, final-practice, and held-out performance.
- Evaluate survival, objective completion, damage, resource efficiency, reaction delay, invalid actions, and task time.
- For multiplayer, evaluate teamwork and rule compliance separately from individual mechanics.
- Keep per-game skills scoped; promote a generalized skill only after cross-map/cross-seed transfer.
- Roll back when a new skill lowers held-out performance.

## 7. Creator Brain: build games that actually work

Roblox's built-in Studio MCP and playtest workflow should be the first-class Roblox adapter. Do not create a duplicate Studio-control layer.

Creator loop:
1. Inspect the current project and identify user-owned changes.
2. Write a task manifest with acceptance criteria and rollback plan.
3. Make bounded edits.
4. Run Luau analysis, formatting, and dependency checks.
5. Test client and server behavior where relevant.
6. Run playtests using real player actions.
7. Capture logs, screenshots, state assertions, and performance.
8. Repair evidenced failures.
9. Re-run the failed and regression tests.
10. Save the verified project revision and evidence.

For Godot/Unity/Blender, use equivalent project adapters and runtime-specific tests. A generated script or successful compile is not a completed game-development task.

Add a creator asset ledger containing source, license, version, import settings, texture budgets, poly/rig constraints, and generated-vs-human-authored provenance. Never assume a web asset is free to redistribute.

## 8. General knowledge and memory

Use an evidence ledger:
- claim;
- source URL/document ID;
- publisher/author;
- published/updated date;
- date acquired;
- scope and assumptions;
- confidence;
- contradictory evidence;
- expiry/recheck policy;
- license/usage constraints.

Use temporal facts for information that changes. Keep:
- semantic knowledge (what is true and why);
- episodic memory (what happened in a session);
- procedural skill (how to perform a task);
- project state (what remains to do);
- persona configuration (how STAR presents herself)
as separate stores or namespaces.

Memory promotion requires provenance and a useful retrieval test. A retrieved fact must not silently overwrite a newer fact. A remembered conversation should not become a permanent viewer profile without explicit consent.

## 9. Implementation order

### P0 — Preserve current branch health
- Keep PR #1178 draft and unmerged.
- Confirm exact-head Linux and Windows checks after each commit.
- Do not interpret skipped checks as passed.
- Keep the PR's existing dependency base; do not retarget it to production main.

### P1 — Provider-neutral telemetry
- Define internal metric names for TTFT, first-audio, inter-token latency, queue wait, tool latency, cancellation, cache residency, frame-time, and audio underruns.
- Implement a no-op/local sink first.
- Add backend-specific mappings only for metrics actually exposed.
- Add a reproducible mixed-load trace.

### P2 — Event envelope and deadlines
- Add a versioned schema with monotonic time, source, sequence, causal references, and TTL.
- Add schema/overflow/staleness/deduplication tests.
- Keep raw payloads out of durable event logs by default.

### P3 — Local turn detector bake-off
- Compare current Smart Turn with LiveKit's local CPU v1-mini on consented clips.
- Measure missed turns, premature turns, false interruptions, and end-to-end response latency.
- Keep the existing room director authoritative.

### P4 — Real-time game adapter
- Build one game adapter first, with a replayable environment and deterministic tests.
- Add action expiry and observation revision checks.
- Keep reflex execution independent of the strategic LLM.

### P5 — Transfer-safe learning and creator evaluation
- Add compositional task streams inspired by AGENTCL.
- Add sealed holdouts and negative-transfer reports.
- Add Roblox Studio MCP plan/build/test with rollback and screenshots.

### P6 — Streaming and avatar integration
- Add VTube Studio and OBS adapters behind explicit opt-in and narrow permissions.
- Align actual audio playback receipts with avatar visemes and captions.
- Test reconnects, token storage, and local-only binding.

### P7 — Knowledge graph experiment
- Prototype temporal edges in the current memory layer before adopting Graphiti or another external service.
- Compare retrieval quality, latency, storage, and stale-fact handling on a consented STAR corpus.

## 10. Acceptance gates

**Real-time responsiveness**
- Audio callbacks and reflex controller never block on model/network calls.
- User stop/takeover is honored before any queued model action.
- Stale game actions are rejected.
- Foreground p95 latency remains within a predeclared budget under background load.

**Streaming**
- Measure missed direct questions, false interruptions, duplicate answers, end-of-turn latency, and interruption-to-silence.
- Audio, captions, and avatar visemes remain aligned to actual playback.
- Naturalness is evaluated by context fit and timing, not talk-time.

**Inference**
- Compare matched runtime configurations.
- Report TTFT, first-audio, TPOT/ITL, p95/p99, memory, and quality.
- Demonstrate recovery after bursts; do not rely on mean tokens/sec.

**Gaming**
- Report real-time and paused performance separately.
- Require held-out maps/seeds and actual environment postconditions.
- Track invalid/stale actions and user takeover.

**Creator**
- Require task manifests, diffs, playtest logs, visual evidence, and regression tests.
- Test client/server and network conditions when relevant.
- Keep publish/destructive operations behind owner approval.

**Learning**
- Report transfer gain and negative transfer.
- Require sealed holdouts before skill promotion.
- Preserve rollback to the last known-good skill.

**Privacy and trust**
- Raw audio/video/chat storage off by default.
- Session-scoped opaque speaker IDs.
- No public exposure of local VTube Studio/OBS APIs.
- No credentials in model context, logs, generated code, or repository.
- External actions and publication require explicit authorization.

## 11. Primary sources added for this run

- AGENTCL: https://arxiv.org/abs/2606.02461
- LiveKit audio turn detector: https://docs.livekit.io/agents/logic/turns/turn-detector/
- LiveKit turn-handling options: https://docs.livekit.io/reference/agents/turn-handling-options/
- OpenTelemetry GenAI metrics: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
- OBS WebSocket: https://github.com/obsproject/obs-websocket
- VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
- Graphiti: https://www.getzep.com/platform/graphiti/
- MineDojo: https://github.com/MineDojo/MineDojo
- Voyager: https://github.com/caixianzhou/voyager
- py-kvcache paper: https://arxiv.org/abs/2609.11744
- Controlled cache/serving comparison: https://arxiv.org/abs/2611.05991
- vLLM current metrics documentation: https://github.com/vllm-project/vllm/blob/main/docs/design/metrics.md

## Conclusion

The next intelligence leap is not another swarm of agents. It is a coordinated runtime that knows which work must happen immediately, which work can wait, what evidence supports an action, how to cancel stale work, and whether a claimed improvement survives a held-out test.

STAR should feel natural on stream because her timing, context, avatar, and speech are coordinated—not because she is forced to talk continuously. She should become a better gamer because her reactive controller and strategic planner cooperate—not because every frame is sent to a large model. She should become a better creator because projects are actually built, played, measured, and repaired—not because code generation looks convincing.

This run adds the architecture, research, and measurable implementation sequence. Runtime changes remain gated on paired target-hardware tests and the existing PR dependency train.
