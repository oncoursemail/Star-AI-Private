# STAR — Active listening, generalist intelligence, game mastery, and VTuber runtime roadmap

**Research date:** 2026-11-09  
**Implementation branch:** `feat/star-intelligence-listener-backchannels-20261109-auto189`  
**Scope:** optional content-free nonverbal listener cues, conversational naturalness, generalist memory, real-time gaming, game creation, local inference, and native streaming acceptance.

## Executive summary

Star already has substantial foundations for speech turn-taking, preplay freshness, route-bound speech pacing, audio epochs, avatar synchronization, real-time game perception, GPU admission, game-skill evaluation, and private rehearsal. The next useful improvement is not another always-talking persona layer. It is a low-cost, nonverbal active-listening path that can run while a viewer is speaking without interrupting them or inventing an emotional reaction.

This branch adds an owner-opted `StreamListenerBackchannel` and exposes it through `StarStage`. A trusted local host may send a small content-free semantic event (`acknowledge`, `considering`, or `clarifying`) derived from incremental ASR/dialogue analysis. The stage maps it to a subtle, short-lived head/brow adjustment. It never generates audio, says that Star agrees, infers the viewer's emotion, or authorizes a broadcast.

The new path is deliberately conservative:
- explicit owner opt-in, disabled by default;
- host-verified, monotonic event IDs and timestamps;
- 250 ms maximum event age and 0.82 minimum confidence;
- viewer must still be speaking; owner/Star speech, critical gameplay, stream pressure, stale host context, or reduced-motion mode cancels the cue;
- 1.15 s cooldown and at most 10 cues per rolling minute;
- no transcript, audio, speaker ID, or viewer identity stored;
- existing `QuietStageFrame` freshness check still applies at the rig boundary.

The implementation is Python-side. The native Windows ASR/audio/VTube Studio host must still supply truthful evidence and render only fresh frames. No live audio, OBS session, game input, or broadcast was started.

## 1. Research: natural conversation is more than low latency

### RESPOND — predictive turn-taking and backchannels

Microsoft Research's RESPOND work describes how pause-and-respond agents can feel stiff. It uses streaming ASR and incremental semantics to predict listener backchannels and possible turn claims, with separate controls for backchannel frequency and how aggressively an agent claims the floor. This supports separating:
1. nonverbal listening signals while the other person still owns the floor;
2. a short verbal acknowledgement only when appropriate;
3. the full answer after the speaker yields.

Star should not speak over a viewer just to appear lively. Backchannels should be sparse, cancellable, and subordinate to owner speech and gameplay. [Microsoft Research: RESPOND](https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/).

### Intent-aware nonverbal feedback

The MuC 2026 paper *Intent-Aware Backchanneling for Active Listening in Human-Robot Interaction* describes a dual-stage separation between speaker intent and listener intent, with chunk-level nonverbal feedback running in parallel with a turn-level verbal response. This is a useful design pattern for Star's Live2D/VTuber rig: semantic analysis can propose a tiny listening cue without forcing a verbal interruption. It is not evidence that any particular cue is universally natural; visual review with the actual avatar remains necessary. [MuC 2026 paper](https://doi.org/10.1145/3820253.3831400).

### Proactive video companions

Proact-VL (ICML 2026) frames real-time companions around three hard problems: low-latency inference under continuous visual input, deciding when to respond, and controlling the amount of generated content. Its Live Gaming Benchmark includes solo commentary, co-commentary, and user guidance. Star should therefore have a response director that can choose **speak briefly, show a nonverbal cue, defer, or stay silent** rather than treating every observation as a prompt to talk. [ICML 2026: Proact-VL](https://proceedings.mlr.press/v306/yan26c.html).

## 2. Implemented: content-free listener micro-cues

### New runtime module

`star/stream_listener_backchannel.py`

- `ListenerIntentSignal` is a strict typed record. It accepts only three coarse intents: `acknowledge`, `considering`, and `clarifying`.
- `StreamListenerBackchannel.enable(owner_approved=True)` is required. The feature is not enabled by normal stage startup.
- `observe()` consumes each event ID once and rejects stale, future, unverified, low-confidence, owner-speaking, Star-speaking, critical-gameplay, or stream-pressure events.
- `overlay()` adjusts only small head/brow/body values on an existing `MotionFrame`; mouth movement and smile remain untouched.
- A lost host witness, viewer pause, owner speech, critical gameplay, stream pressure, or reduced-motion setting clears the pending cue rather than allowing it to resume later.
- Metrics contain aggregate counters only.

### Stage integration

`StarStage` now exposes:
- `enable_listener_backchannels(owner_approved=True)`
- `disable_listener_backchannels()`
- `observe_listener_intent(signal, now=...)`
- additional `idle_motion()` context fields: `owner_speaking`, `stream_pressure`, and `listener_context_verified`.

The resulting cue still travels through the existing `QuietStageFrame` and `current_idle()` freshness check. A prepared speech turn clears any listener cue. Disabling the stage disables the feature.

### Why the cue vocabulary is intentionally small

- `acknowledge` means “I received that,” not “I agree.”
- `considering` means “I am processing,” not a claim about the viewer's emotion.
- `clarifying` is a small question-like head/brow cue, not an assertion that the viewer was unclear.

Do not map arbitrary LLM emotion labels, raw chat text, facial-expression guesses, or voice sentiment directly to the avatar. If semantic confidence is low, do nothing.

## 3. Generalist intelligence: memory that improves actions

Star should maintain typed, source-aware memory rather than treating every transcript fragment as equally true.

Recommended record classes:
- **World facts:** externally sourced claims, API behavior, game mechanics, version-specific instructions, and reference links.
- **Experiences:** tasks Star actually executed, with environment, date, tools, result, and independent completion evidence.
- **Observations:** trusted sensor/tool outputs with freshness, scope, and uncertainty.
- **Procedures/skills:** reusable plans that have passed repeatable tests and held-out variants.
- **Preferences/opinions:** explicitly subjective, scoped, and never silently promoted to objective fact.

APEX-MEM (ACL 2026) uses temporally grounded entity events, append-only history, and retrieval-time conflict resolution. This is a strong reference for preserving changed facts without erasing the historical record. [ACL 2026: APEX-MEM](https://aclanthology.org/2026.acl-long.749/).

LongMemEval tests information extraction, multi-session reasoning, knowledge updates, temporal reasoning, and abstention. These should become separate memory acceptance dimensions, not one aggregate “recall” score. [LongMemEval](https://github.com/xiaowu0162/LongMemEval).

Mem2ActBench makes an important distinction: recalling a preference is not the same as using it to select the right tool and ground its parameters in a later task. Star should evaluate whether remembered project constraints, model versions, game settings, and user-approved procedures actually improve execution. [Mem2ActBench](https://arxiv.org/abs/2601.19935).

### Recommended memory pipeline

1. Extract atomic candidate memories with source, timestamp, project/game scope, confidence, and expiry.
2. Preserve owner-authored facts separately from model-inferred hypotheses.
3. Keep superseded values as history; resolve “current” at retrieval time.
4. Retrieve with lexical + vector + temporal filters; rerank only when the task's latency budget allows.
5. Supply the model with provenance and uncertainty, not just a flat paragraph.
6. Promote a procedure only after reproducible tests pass on held-out cases.
7. Support abstention when sources conflict or the evidence is stale.

Do not fine-tune on every stream transcript. First prove that a memory or procedure improves held-out actions and does not leak across projects or users.

## 4. Real-time gaming: two loops, not one giant model

Gym-Anything-RT (27 October 2026) studies agents in continuously evolving games and contrasts real-time interaction with paused/slowed environments. The paper's reported gap for an evaluated model illustrates why strong offline reasoning does not automatically create real-time gameplay skill. It is not a measurement of Star. [Gym-Anything-RT](https://arxiv.org/abs/2610.37567).

Recommended architecture:

### Reflex loop
- Fresh, timestamped observations.
- Small, allowlisted action vocabulary.
- Hard action deadlines and stale-observation rejection.
- Immediate cancellation when game identity, window, or input state changes.
- No large-model call for every frame.

### Tactical loop
- Learn mechanics, maps, routes, resource priorities, and opponent patterns.
- Analyze failures and successful episodes.
- Select practice tasks and adjust difficulty.
- Build strategies that can be tested on unseen maps or variants.
- Convert a strategy into a reusable skill only after repeatable evidence.

### Gaming acceptance
Measure:
- success/progress on held-out scenarios;
- observation age at action time;
- action acknowledgement p50/p95;
- missed deadlines and recoveries;
- performance under simultaneous OBS, TTS, and avatar load;
- transfer to new maps, mechanics, and game variants.

A candidate that wins one familiar level more often is not necessarily a more capable gamer. Keep per-scenario regression checks and scenario-diversity requirements.

## 5. Game creation: evaluate the running game, not only generated code

OpenGameEval evaluates agents inside reproducible Roblox Studio sessions with executable checks on edited scenes and simulated play. Its study reports 84 curated tasks across 13 models and finds that inspecting objects before acting correlates with better success. This supports making inspection a required phase in Star's build workflow. [OpenGameEval paper](https://arxiv.org/abs/2610.02563) · [Roblox/OpenGameEval repository](https://github.com/Roblox/open-game-eval).

GameDevBench (ICML 2026) contains 333 Godot game-development tasks spanning gameplay logic, UI, 2D graphics/animation, and 3D graphics/animation. It highlights how multimodal scene/assets feedback matters in game development, not just code edits. [GameDevBench](https://github.com/waynchi/gamedevbench).

Recommended workflow:

**Inspect → Clarify intent → Plan → Edit → Static checks → Run → Playtest → Visual comparison → Repair → Held-out regression → Owner-reviewed release**

The evaluation should include:
- Luau/static analysis and API-version correctness;
- client/server authority and replication;
- scene hierarchy, object properties, asset references, and collision;
- UI legibility and interaction;
- physics, animation, audio, and performance;
- exploit resistance and multiplayer behavior;
- actual playability and task completion.

Roblox's Studio MCP can call Open Cloud using per-game scopes controlled by the owner. Safe, Balanced, Full, and Custom permission levels differ; publishing, player consequences, secrets, monetization, and live data operations are higher risk. Star should request only the minimum scope needed and never turn on permissions herself. Keep publishing, monetization, bans, secrets, and live datastore writes behind explicit owner approval. [Roblox Studio MCP/Open Cloud permissions](https://create.roblox.com/docs/studio/mcp-open-cloud) · [Roblox Studio agentic workflows](https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic).

## 6. Faster local intelligence on the 8 GB GPU

### Speculative decoding

llama.cpp supports draft-model and n-gram speculative decoding. The key trade-off is verification cost and memory pressure: a second resident model may reduce the VRAM headroom available to the game, OBS, vision, or avatar. Benchmark n-gram modes before loading another model, and measure short conversational turns separately from code and long reasoning. [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).

SPEED-Bench is useful because it reports per-category throughput, latency, and draft acceptance for an already-running llama-server. It is a measurement tool, not a guarantee that speculation is faster. [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench).

### Prefix caching

vLLM Automatic Prefix Caching reuses cached KV blocks for repeated prompt prefixes. Its documented benefit is lower prefill work; it does not make autoregressive decode inherently faster. Keep stable persona/system instructions at the beginning of prompts and append changing game/viewer context after them. [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/v0.22.1/features/automatic_prefix_caching/).

### Workload policy

For an 8 GB RTX 4060 profile:
- keep one primary GPU model resident by default;
- route short urgent reactions to a fast path;
- defer deep research, bulk embeddings, and optional vision under frame-time/VRAM/audio pressure;
- use CPU speech only if it improves end-to-end quality of service without starving the game;
- cache deterministic API/schema/context material, not stale live game observations;
- measure p50/p95 first-token, first-audio, decode rate, answer quality, GPU/VRAM, CPU/RAM, game frame-time p95/p99, and OBS drops together.

A token/s improvement that causes frame drops or worse answer quality is not a streaming optimization.

## 7. Windows audio and OBS integration

WASAPI loopback captures the mix rendered by an audio endpoint. Windows Core Audio endpoint notifications report device changes and invalidation; the host must revoke stale route readiness and rebuild the capture/render stream after device changes. [WASAPI overview](https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi) · [Loopback recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording) · [Core Audio device events](https://learn.microsoft.com/en-us/windows/win32/coreaudio/device-events).

OBS WebSocket exposes a local control/event API. Keep authentication enabled, bind to loopback where possible, store the password outside logs/source control, and subscribe only to events the private rehearsal needs. [obs-websocket](https://github.com/obsproject/obs-websocket).

Privacy design:
- prefer a dedicated Star audio endpoint/session over capturing all system audio;
- do not persist raw loopback audio or unrelated desktop audio;
- keep timing/health receipts separate from transcripts;
- do not treat an OBS websocket response as proof that a viewer heard audio;
- device invalidation, stream pressure, owner barge-in, and PCM stop/flush must revoke avatar/audio epochs.

## 8. Acceptance matrix

| Area | Measurements | Promotion rule |
|---|---|---|
| Listener cues | Freshness, confidence, duplicate IDs, cues/minute, suppressions, stale replay | Private visual review; no cues during owner speech, critical gameplay, or reduced motion |
| Natural conversation | First-audible p50/p95, overlap, barge-in stop p95, unplanned gaps, groundedness | Paired baseline/candidate with reviewed cases across every scenario |
| Inference | TTFT, decode tok/s, p50/p95 turn latency, answer quality, VRAM/RAM/CPU | Randomized paired A/B; no quality, game-FPS, or OBS regression |
| Gaming | Held-out win/progress, observation age, action p95, deadline misses, recovery | Gains across balanced scenario families and unseen variants |
| Game creation | Static tests, scene checks, playtest pass rate, visual quality, multiplayer, performance | Reproducible success on held-out tasks; rollback-ready patch |
| Memory | Recall, temporal updates, abstention, tool/parameter accuracy, stale/conflict rejection | Better task execution, not recall alone; no cross-project leakage |
| VTuber | Audio/avatar sync, interruption cancellation, persona consistency, silence quality, moderation | Private 30–60 minute nonbroadcast rehearsal with owner review |

Run warm and cold starts, A/B/A or randomized paired sessions, route/device changes, game scene changes, and long-session drift. Publish sample counts and uncertainty. Never promote from one favorable mean or cloned benchmark payload.

## 9. Priority roadmap

**P0 — Native listener integration**
- Connect the trusted incremental ASR/dialogue host to `observe_listener_intent()`.
- Supply a fresh `listener_context_verified` flag on every idle render sample.
- Keep feature OFF until owner opts in and the Windows/VTube Studio path is privately rehearsed.
- Test owner barge-in, guest pauses, critical gameplay, stream pressure, reduced motion, and device changes.

**P1 — Generalist memory evaluation**
- Build a versioned benchmark using LongMemEval-style temporal/update/abstention cases and Mem2ActBench-style tool-parameter grounding.
- Compare the current memory pipeline with typed temporal/episodic retrieval.
- Track provenance, conflicts, expiry, and action success.

**P2 — Real-time game mastery**
- Pair the reflex loop with the tactical learner.
- Expand balanced held-out scenario coverage.
- Record action acknowledgement and observation freshness.
- Promote skills only after transfer tests.

**P3 — Local performance lab**
- Add reproducible llama.cpp SPEED-Bench workloads for short chat, code, long reasoning, and structured output.
- Compare baseline, n-gram speculation, prompt-prefix reuse, and CPU TTS separately.
- Run the selected candidate with game + OBS + avatar under identical hardware conditions.

**P4 — Autonomous creator**
- Connect Studio inspection, static analysis, simulated play, visual comparison, and held-out regression.
- Use minimum per-game MCP scopes.
- Keep live publishing, player consequences, monetization, and secrets owner-approved.

## Evidence boundary

This document is a source-linked engineering roadmap. The new listener cue code is deterministic and offline-testable, but it does not itself perform ASR, capture WASAPI audio, render VTube Studio parameters, operate OBS, control a game, train a model, or broadcast. No neural inference speedup, game win-rate improvement, model-intelligence gain, or public-stream readiness is claimed.
