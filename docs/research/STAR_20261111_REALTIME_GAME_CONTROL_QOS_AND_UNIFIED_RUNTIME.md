# STAR: Real-Time Game-Control QoS and Unified Runtime Research

**Research date:** 2026-11-11  
**Target branch:** \`star/next\`  
**Scope:** close a concrete gap between STAR's existing resource governor and its closed-loop game pilot. This is an engineering note, not a claim of human-equivalent behavior or measured hardware improvement.

## Executive finding

STAR already has substantial pieces of a real-time gaming/VTuber stack:

- \`star/stream_hardware_telemetry.py\` collects read-only host telemetry off the hot path.
- \`star/stream_budget.py\` and \`star/stream_load_governor.py\` provide conservative advisory policies.
- \`star/stream_qos.py\` reserves measured CPU/GPU routes, deadlines, memory headroom, one-shot tickets, and quarantines expired workers until the host acknowledges they stopped.
- \`star/stream_director.py\` arbitrates owner interruptions, game events, questions, comments and deliberate silence.
- \`star/game_action_gate.py\` and \`star/game_closed_loop.py\` separate action proposals from host dispatch and verification.
- \`star/game_skill_memory.py\`, \`star/game_skill_promotion.py\`, and \`star/game_transfer_eval.py\` provide reusable-skill and transfer-learning foundations.
- \`star/voice/runtime.py\` loads and warms voice engines once, instead of paying model-load costs on every call.

The audit found a small but important integration mismatch:

**The stream-level WorkRequest vocabulary already included \`game_control\`, but the measured AdaptiveQoS inference scheduler did not.** That meant the low-latency game-control inference lane had no first-class place in the component that actually reserves CPU/GPU slots and checks measured p95 deadlines.

This change adds that lane without turning an inference admission into permission to send game input.

## Implementation in this change

### 1. Explicit \`game_control\` workload

\`star/stream_qos.py\` now recognizes \`game_control\` as a valid inference kind.

### 2. CPU-first while a game is active

For both \`speech\` and \`game_control\`, automatic routing tries CPU before GPU while a game is active. This is a resource policy, not a claim that CPU is always faster.

A calibrated GPU route remains a fallback if the CPU route is unavailable (for example, saturated, out of slots, or unable to meet the deadline) and the game is otherwise healthy.

### 3. GPU protection under pressure

A game-control request cannot use the GPU when either:
- game FPS is below 50; or
- speech backlog exceeds 250 ms.

The CPU route can still be considered, subject to measured route latency, free RAM, CPU load, slots and deadline.

### 4. Live calibration requirement

During a live stream, game-control inference requires at least five successful latency observations for the **active-game** route and device. Idle measurements cannot certify a live-game route.

A private, non-live game rehearsal can collect the initial route samples. The resulting samples remain tagged as \`game_active\`; the system does not silently substitute idle measurements.

### 5. No control authority added

The QoS ticket only reserves advisory inference capacity. It does not:
- press keys or move a character;
- authorize a game or process;
- bypass \`game_action_gate\`;
- authenticate the host;
- publish a Roblox place;
- write live player data; or
- start a broadcast.

The trusted host must still validate the owner-approved game scope, dispatch at most one action, acknowledge dispatch, observe a fresh frame, and verify the effect before another action is proposed.

### 6. Regression coverage

Added \`tests/test_stream_qos_game_control.py\` for:
- refusal to use an uncalibrated game-control route during a live game;
- CPU admission under low-FPS / speech-backlog pressure;
- CPU preference even when the synthetic GPU route is faster;
- GPU rejection under game pressure;
- measured GPU fallback when CPU is saturated and the game is healthy;
- deadline rejection against measured p95 plus margin;
- advisory-only semantics; and
- invalid workload/device rejection;
- inactive-game backpressure; and
- isolation of idle calibration from active-game calibration.

All latency samples in these tests are deterministic synthetic fixtures. They are not hardware measurements.

## Research findings and design implications

### A. Multiparty streaming is a social-floor problem, not just speech recognition

**MP-Bench** (Findings of EMNLP 2026) evaluates turn-taking awareness, response appropriateness, and comprehension in group conversations. Its reported evaluation of 12 voice agents found real-time systems at or below 22% on multiparty comprehension and near chance on multiparty turn-taking. This supports keeping addressee inference, silence preservation, and turn timing as separate evaluation lanes.

Source: https://www.fullduplex.ai/benchmarks/mp-bench

**Duplex-MPE** (2026-09-25) contains 2,000 scenarios with three or four human speakers and one assistant. It separately scores fresh response initiation, answer accuracy, silence preservation, and stopping when a human resolves a request. This is a strong fit for a streamer who must understand viewer-to-viewer conversation, not only direct questions.

Sources:
- https://arxiv.org/abs/2609.31948
- https://www.fullduplex.ai/benchmarks/duplex-mpe

**Full-Duplex-Bench v3** evaluates real human audio, disfluencies, multi-step tool use, latency and turn-taking. Its paper reports that even the evaluated systems struggled with self-corrections and hard multi-step tasks. STAR should therefore evaluate both speech behavior and task completion, not collapse them into a single “voice quality” score.

Sources:
- https://arxiv.org/abs/2604.04847
- https://www.full-duplex.ai/benchmarks/fdb-v3

**STAR implication:** retain the current separation between voice perception, addressee/floor decision, stream event arbitration, language generation, TTS, actual playback, and avatar state. The next missing integration is a host adapter that measures when audio actually reaches the speaker and when cancellation has physically drained the playback queue.

### B. Game agents need closed-loop, objective evaluation

**GameDevBench** (ICML 2026) contains 333 tasks across 2D/3D graphics and animation, UI, and gameplay logic. It is useful for measuring creator-agent work in an engine, rather than grading code style alone.

Source: https://github.com/waynchi/gamedevbench

**STAR implication:** use its task categories as a coverage map, not as a claim that STAR has passed the benchmark. For each STAR Creator task, preserve:
1. the original project and requirements;
2. a plan with explicit acceptance criteria;
3. the code/scene diff;
4. an engine launch or import result;
5. a real playtest or deterministic scene check;
6. visual inspection evidence; and
7. regression results on an unseen task.

For gameplay, score objective state changes and observed outcomes. A plausible action description is not evidence that the character moved, the target was hit, or the round was won.

### C. Roblox Studio MCP now exposes more powerful per-game operations

Roblox's November 4, 2026 Studio MCP update added Open Cloud invocation from connected MCP clients. The November 5 update clarified connection behavior and known limitations. Permissions are per game and per person; Studio enforces the scopes the owner enables. Full access includes high-risk operations such as monetization, player consequences, secrets, and publishing. DataStore writes can affect real player data.

Sources:
- https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
- https://create.roblox.com/docs/studio/mcp-open-cloud

**STAR implication:** keep the normal edit loop read-only or test-place scoped. Use the minimum custom permission set for the task. Keep publishing, monetization, player restrictions, secrets, and live DataStore writes out of unattended game-building workflows. For asset imports, use an owner-approved export folder and inspect triangle counts, scale, rotation, textures, placement, and moderation status.

### D. Inference speed must be measured at the right boundary

The llama.cpp server supports slots and prompt-cache reuse. Stable prefixes and stable per-chat slots can reduce repeated prompt evaluation, but slot count, context allocation, cache behavior, and concurrent traffic affect one another.

Sources:
- https://github.com/ggml-org/llama.cpp/discussions/13606
- https://github.com/ggml-org/llama.cpp/tree/master/tools/server

The llama.cpp MoE cache tuner measures CPU expert computation, GPU upload, cache size, and CPU-share tradeoffs on the actual machine. The documented recommendation is workload- and hardware-specific; it is not safe to copy another machine's values.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

Recent llama.cpp issue reports also illustrate that prompt-cache restore/save paths can create stalls or failures in particular multi-slot/unified-KV configurations. Treat caching as an experiment to validate, not as a universally free speedup.

Sources:
- https://github.com/ggml-org/llama.cpp/issues/30961
- https://github.com/ggml-org/llama.cpp/issues/30252

**STAR implication:** record these separately:
- prompt/prefill time;
- time to first token;
- inter-token latency;
- time to first generated audio chunk;
- time to first audible sample;
- total response completion;
- queue wait;
- cancellation-to-audio-silence;
- game 1% low / p10 FPS;
- OBS render/encode drops;
- audio underruns; and
- free VRAM/RAM.

Do not optimize tokens per second if it worsens first-audible latency, game frame pacing, or OBS stability. Speculative decoding should be retained only when end-to-end measurements show a win for STAR's actual prompts and target model pair. MoE caching should be tuned on the target hardware with the exact model, context, CPU thread count, memory mode, and concurrent load.

### E. Long-term memory must be state-consistent

**MemTrace** (2026-10-04) argues that coding-agent memories become stale as repositories change. It stores immutable execution traces anchored to files, symbols, tests and dependencies, then revalidates them against current repository state before reuse.

Source: https://arxiv.org/abs/2610.04838

**STAR implication:** use the same principle for game skills and creator knowledge:
- store what was observed, the game/build revision, action, result, and verifier;
- attach provenance and timestamps;
- invalidate or recheck memories when the game version, place, API, script, or skill preconditions change;
- separate an anecdotal success from a repeatedly verified procedure;
- retain failure and recovery traces, not only successful examples.

## Recommended unified runtime

The following is the target integration, not a claim that every adapter is already connected:

~~~text
Audio / chat / game / host telemetry
              |
              v
      Evidence normalization
              |
      +-------+--------+
      |                |
      v                v
 Social floor      Game state
 / addressee       / perception
      |                |
      v                v
 Stream Director   Reactive Game Brain
      |                |
      v                v
 Voice + TTS       Game-control inference
      |                |
      v                v
 Playback ACK      AdaptiveQoS reservation
 + avatar state         |
                         v
                  Game action gate
                         |
                  one action + ACK
                         |
                  fresh observed frame
                         |
                  outcome verification

Asynchronous lane (only when capacity permits):
research -> retrieval -> strategic planning -> memory consolidation
         -> game creation -> render -> night school
~~~

### Scheduling tiers

1. **Owner stop / safety controls:** always highest priority and independent of model generation.
2. **Audio capture, VAD, interruption detection:** bounded, low-latency, non-blocking.
3. **Speech response and game-control inference:** deadline-aware; CPU-first during active gameplay where calibrated.
4. **Essential game perception:** rate-limited and tied to current frame sequence.
5. **Viewer commentary and non-urgent social responses:** may be skipped when stale.
6. **Research, training, asset rendering, memory consolidation:** defer during live gameplay/streaming unless a measured spare-capacity policy explicitly permits a small bounded job.

### Human-like streaming behavior

“Human-like” here means a more natural interaction experience, not that the model is human or has human feelings. Prioritize:
- listening without replying to every message;
- recognizing explicit versus implicit addressee;
- avoiding interruption on pauses/backchannels;
- yielding promptly when a person interrupts;
- not speaking after another viewer has already resolved the question;
- varying response length to match the moment;
- prosody, emphasis, volume, pace, and nonverbal acknowledgements;
- remembering relevant stream context without inventing personal history;
- synchronizing mouth movement to actual playback, not generated text;
- keeping avatar state coherent across listening, thinking, speaking, laughing, and yielding;
- protecting privacy by keeping speaker slots session-local and avoiding voiceprint identity claims.

### Game mastery behavior

Use two reasoning horizons:
- **Reactive controller:** short deadlines for movement, aim, dodge, interaction, and recovery.
- **Strategic planner:** longer asynchronous planning for routes, resources, team tactics, objectives, and learning.

The strategic planner must never overwrite a newer game observation. Every proposed action should be bound to a game/session epoch and observation sequence, expire quickly, and be followed by a new host-observed frame. Repeated failures should trigger a stop and diagnosis, not uncontrolled retries.

### General knowledge and creation

For research and general knowledge, store source, publication/update time, claim, confidence, conflicting evidence, and a freshness policy. Recheck facts that change frequently. Distinguish “retrieved a source” from “understood and applied it correctly.”

For game creation, transfer verified procedural skills across engines only where their preconditions match. Roblox Luau, Blender, Unity/Godot, audio, animation, UI, networking, and game design need distinct tool contracts and validators.

## Hardware experiment plan

For STAR's target 8 GB GPU class, benchmark one variable at a time:
1. small fast model vs larger reasoning model;
2. CPU-only vs GPU layer placement;
3. prompt-cache enabled/disabled with stable and changing prefixes;
4. one vs multiple server slots;
5. KV cache types and context lengths;
6. speculative decoding with measured draft acceptance;
7. MoE cache sizes/shares only for applicable MoE models;
8. voice model CPU/GPU placement;
9. game vision sampling rate;
10. simultaneous game + OBS + VAD/ASR + TTS + LLM + avatar load.

Use paired runs with the same game scene, camera, OBS profile, prompt set, model revision, and thermal state. Report median and p95/p99; include warm-up, failures, cancellations and dropped work. A configuration is better only if quality remains within a preregistered tolerance and the live workload's frame pacing and first-audible latency improve.

## Acceptance gates

- The new game-control lane passes focused deterministic unit tests.
- The complete Python suite and type/lint gates pass on the branch.
- A private, non-live game rehearsal collects five successful active-game samples for each game-control device route intended for live use.
- Live game-control requests reject stale telemetry and uncalibrated routes.
- Low-FPS or delayed-speech conditions prevent GPU game-control admission.
- A host integration test proves that QoS admission alone cannot dispatch input.
- A separate Windows rehearsal measures game p10/1% low FPS, OBS drops, audio underruns, first-audible p95, queue wait, VRAM/RAM and CPU saturation.
- A multi-party audio evaluation uses conversation-disjoint holdout and reports silence preservation, interruption, addressee accuracy, answer quality and latency separately.
- A creator evaluation uses unseen engine tasks and verifies actual scene/game outcomes.

## Verification boundary for this PR

- The source change is limited to \`star/stream_qos.py\`.
- The new tests use synthetic telemetry and durations.
- No local full-suite, Pyright/Ruff, Windows hardware, OBS, microphone, TTS, Roblox Studio, or live gameplay run is claimed here.
- No production model, model weights, prompts, memory database, live thresholds, host permissions, game inputs, avatar, or broadcast settings were changed.
- The change is advisory and review-only; production \`main\` remains unchanged until an independently reviewed merge.
