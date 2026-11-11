# STAR: Speech-Reserve Utilization, Cache-Independent Continuation, and Generalist Runtime Research

**Research date:** 2026-11-11  
**Implementation branch:** `fix/qos-speech-reserve-utilization-20261111-auto11`  
**Parent:** `fix/live-speech-cpu-reserve-20261111-auto11` (draft PR #1125)  
**Scope:** improve CPU admission utilization without weakening speech reservations; make the priority proxy's correctness independent of optional upstream prompt-cache hits; establish a source-grounded next research plan for streaming, game learning, creator workflows, memory, and inference.

## Executive summary

This pass found two concrete issues in the current development stack:

1. **The live speech CPU reserve was conservative in the wrong way.** It counted already-running speech jobs against the non-speech quota. If speech had already occupied the reserved slot, non-speech work could still be rejected even though a physical CPU slot remained available. The policy was safe but unnecessarily underutilized capacity.
2. **A priority-proxy integration test treated a prompt-cache hit as a correctness requirement.** The proxy already verifies that a paused answer resumes with exactly the same final text, finish reason, and token usage. A positive `cache_n` is an optional performance outcome and depends on the upstream server build, cache configuration, exact prefix, and slot state. Requiring it made the test brittle.

The implementation now separates physical CPU capacity from the non-speech quota, adds a speech-first regression, and removes the cache-hit dependency from the continuation correctness test.

No model, prompt, process priority, game input, audio device, OBS scene, model route, memory store, permission, or production setting is changed.

## 1. Implemented: correct CPU reserve accounting

### Previous behavior

For a live stream with `cpu_slots = 2` and `speech_cpu_reserve_slots = 1`, the old admission check used the total number of in-flight CPU jobs when enforcing the non-speech capacity of one.

If one speech job was already running, a game-control job was rejected even though the second CPU slot was physically free. The reserved speech slot was already occupied by speech, so the policy was double-counting the reserve.

### New behavior

The scheduler now performs two independent checks:

1. **Physical capacity:** total in-flight jobs on the selected device must remain below the host-reported slot count.
2. **Non-speech quota:** during a live stream, non-speech CPU jobs must remain below `cpu_slots - speech_cpu_reserve_slots`.

Speech jobs can use the full physical CPU capacity. When no speech job is active, non-speech jobs cannot consume the reserved slot. When speech already occupies that slot, other work can use otherwise-idle capacity without exceeding the total physical slot count.

This preserves the safety invariant while avoiding needless underutilization.

### Regression coverage

The new speech-first test:
- calibrates the CPU route for speech and game control using synthetic timings;
- admits speech first on a two-slot CPU snapshot;
- admits one game-control job into the remaining slot;
- rejects another job once the physical two-slot limit is reached.

The fixtures are deterministic policy tests. They do not measure physical CPU throughput or Windows scheduling.

## 2. Implemented: prompt-cache-independent continuation correctness

The priority proxy can pause a background generation, release its upstream slot, and resume from the text already produced. The actual correctness contract is that the client receives the exact complete answer once, with the expected finish reason and usage.

A positive prompt-cache hit is not required for that contract. llama.cpp exposes cache-reuse controls and timing fields, but reuse depends on server configuration, slot affinity, prefix identity, and cache state. Its server documentation describes `cache_prompt` as a reuse optimization; it also notes backend-dependent non-bit-identical behavior across prompt-processing batch sizes.

The integration test now:
- retains exact final-content assertions;
- retains finish-reason and completion-usage assertions;
- confirms cache metrics are present and non-negative;
- no longer fails solely because `cache_n == 0`.

The module documentation now says a re-sent prefix **may** hit cache when conditions permit. It no longer implies that every continuation necessarily gets a cache hit.

This separates **functional correctness** from **performance telemetry**.

## 3. Inference research: optimize the actual interactive workload

### llama.cpp SPEED-Bench

The upstream SPEED-Bench client benchmarks an already-running `llama-server`, reports latency, throughput, and speculative-draft acceptance by workload category, and recommends matching client concurrency to the server slot count when measuring throughput.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**STAR implication:** maintain separate profiles for one-slot interactive voice, coding, reasoning, and throughput workloads. Do not use a many-slot throughput result to claim faster first response for a single live conversation. Record prompt length, output length, server build, model digest, slot count, concurrency, first-token latency, inter-token latency, completion time, and quality.

### Prompt caching is not free or universally beneficial

The llama.cpp server documents prompt-cache reuse and timing controls:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

A current upstream issue describes multi-second request stalls in a particular idle-slot prompt-cache save path with unified/interleaved KV cells:
https://github.com/ggml-org/llama.cpp/issues/30252

This issue is a report for a specific build/configuration, not proof that every build has the problem. It is still a useful reminder: cache persistence and eviction can create synchronization costs.

**STAR implication:** keep a baseline with the cache path disabled or minimized; compare warm prefix reuse, cache save/restore, and concurrent first-token p95. Keep prompt-cache policy configurable per workload. Never trade a visible voice pause for a theoretical cache hit.

### Speculative decoding

llama.cpp supports draft-model and n-gram speculative decoding. Draft tokens are verified by the target model; speedup depends on acceptance rate and the cost of draft/verification work.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

**STAR implication:** test speculative decoding per model and task class. Keep it only when paired measurements show better first-audible p50/p95 or completion time without answer-quality regression, excessive VRAM use, or worse game 1% lows. A high draft acceptance rate alone is not a user-facing speedup.

### MoE expert cache

The upstream MoE cache tuner measures CPU computation and GPU uploads for the selected model, cache size, memory placement, and PCIe path.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

**STAR implication:** use this only for a model with MoE experts and only on the actual target host. Do not copy cache sizes or CPU shares from H100/H200 systems to an 8 GB consumer GPU. Benchmark with the game and OBS active.

## 4. Natural VTuber interaction: treat social timing as a first-class capability

### MP-Bench

MP-Bench evaluates turn-taking awareness, response appropriateness, and comprehension in multi-person conversations. Its published evaluation reports substantial difficulty for the evaluated real-time agents on multiparty comprehension and turn selection.

Source: https://www.fullduplex.ai/benchmarks/mp-bench

### Full-Duplex-Bench v3

FDB-v3 uses natural human speech with disfluencies and chained tool-use tasks, and scores task accuracy, latency, and turn-taking separately.

Paper: https://arxiv.org/abs/2604.04847  
Benchmark: https://www.full-duplex.ai/benchmarks/fdb-v3

### Realtime-Venus

Realtime-Venus reports separate measures for continuing through backchannels, speech directed at others, and background speech, alongside response behavior for actual interruptions.

Source: https://realtime-venus.github.io/

**STAR implication:** the Social Director should not optimize for maximum reply count. It should maintain separate signals for:
- speaker diarization and addressee confidence;
- response appropriateness;
- silence preservation;
- interruption detection and physical audio cancellation;
- conversational grounding over long sessions;
- first-audible latency;
- voice delivery/prosody;
- avatar synchronization.

A short acknowledgement, a viewer-to-viewer conversation, and an explicit question directed at STAR are different events. The policy should allow her to listen without speaking.

## 5. Avatar embodiment: synchronize to the audio that actually plays

### AVTR-1

AVTR-1 describes a real-time interactive avatar stack that synchronizes motion generation with an external voice agent, schedules audiovisual playback, and handles interruptions. Its reported architecture uses a compact streaming motion generator.

Source: https://arxiv.org/abs/2609.22913  
Project: https://avtr-1.avaturn.live/

**STAR implication:** Star already has an established Live2D art direction. The useful lesson is the synchronization contract, not necessarily replacing her Live2D model with generated video. Drive mouth/viseme state from actual playback position; drive listening, thinking, laughing, and yielding from explicit interaction states; stop mouth motion when the output route confirms silence. Keep avatar rendering lightweight on the RTX 4060.

## 6. Gaming: transfer skills, but verify outcomes in each environment

### SIMA 2

Google DeepMind describes SIMA 2 as a generalist agent that can reason about goals, converse, act in multiple virtual worlds, and improve through experience.

Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

**STAR implication:** store reusable skills such as navigation, aiming, interaction, inventory management, resource gathering, and objective planning. Each skill must declare its game/build assumptions and be revalidated in the target game before reuse.

### AI GameStore

AI GameStore is a scalable, open-ended platform that converts a variety of games into evaluation tasks, including puzzles, physics games, and tactical games.

Source: https://aigamestore.org/

**STAR implication:** use diverse small games as a practice curriculum. Measure task completion, score, time, retries, invalid actions, and transfer to held-out variants. A game win should not be the only measure of competence.

### EdgeBench

EdgeBench describes an ultra-long-horizon environment-learning benchmark with 134 tasks across six task families and runs of at least 12 hours for its core protocol.

Source: https://edge-bench.org/

**STAR implication:** evaluate whether Star improves after repeated attempts, not just whether she can solve a task once. Keep a fixed holdout set and do not tune the scorer or training data against it.

## 7. Game creation: build, launch, inspect, repair, and retest

### GameDevBench

The official GameDevBench repository describes 333 Godot game-development tasks across 2D/3D graphics and animation, UI, and gameplay logic. It reports that image/video feedback improves task success for tested agents.

Source: https://github.com/waynchi/gamedevbench

**STAR implication:** use engine-based task checks and actual visual feedback. A script that compiles is not proof that a game is playable or visually correct. Star Creator should:
1. inspect the project and its current engine version;
2. plan a bounded change;
3. implement it in a disposable branch/place;
4. launch the actual game;
5. inspect screenshots/video and engine diagnostics;
6. playtest objectives and edge cases;
7. repair and retest;
8. retain only evidence-backed skills.

### Roblox Studio MCP and Open Cloud

Roblox's official documentation describes per-game, per-person scopes and the ability to call Open Cloud through Studio MCP. Full access includes scopes that can publish changes, affect players, manage monetization, access secrets, or write live data stores.

Source: https://create.roblox.com/docs/studio/mcp-open-cloud

**STAR implication:** keep development-place scopes narrow. Separate read, edit, asset upload, publishing, monetization, player consequences, secrets, and live DataStore writes. Test with disposable experiences and sanitized data. Uploads can create permanent assets owned by the game owner; do not treat them as reversible local file writes.

## 8. Continual learning: external feedback beats self-approval

### SkillLearnBench

SkillLearnBench evaluates generated skills at the skill, execution-trajectory, and task-outcome levels. Its authors report that repeated iterations with external feedback can help, while self-feedback alone can cause recursive drift.

Source: https://arxiv.org/abs/2604.20087

### Memento-Skills and MUSE-Autoskill

These projects investigate persistent, reusable skills with routing, lifecycle management, evaluation, and refinement.

Sources:
- https://arxiv.org/abs/2603.18743
- https://arxiv.org/abs/2605.27366

### MemTrace

MemTrace focuses on preserving execution history with provenance and revalidating old evidence against the current repository state before reuse.

Source: https://arxiv.org/abs/2610.04838

**STAR implication:** every learned skill should carry:
- provenance and creation date;
- task/domain and environment version;
- preconditions and expected postconditions;
- execution trace reference;
- independent evaluation result;
- failure and recovery cases;
- expiry/revalidation rules.

A skill is a candidate until it passes held-out tasks. A prior successful test must be rerun when relevant code, engine version, model, tool schema, or environment changes.

## 9. Unified runtime roadmap

The next high-value work is integration, not adding isolated agents.

### Live interaction critical path
- Audio capture and VAD.
- Streaming ASR or speech-native input.
- Addressee/social-state estimation.
- Fast response planning.
- Streaming TTS.
- Device-playback evidence.
- Avatar state synchronized to played samples.

### Game critical path
- Fresh observation.
- Reactive action selection with a short deadline.
- One-step action ticket.
- Owner-approved host dispatch.
- Fresh observation and outcome verification.

### Background path
- Strategic game planning.
- Research and knowledge ingestion.
- Creator-agent work.
- Skill proposal and evaluation.
- Long-horizon self-play.

Background work must yield under live speech, game frame-time, OBS render/encode, or audio-underrun pressure. It must not share a single unbounded queue with the live conversation.

### General knowledge
- Search and retrieval with citations and dates.
- Source reliability and conflict tracking.
- Version-aware software/API knowledge.
- Episodic, semantic, and procedural memory.
- Revalidation before applying old information.
- Tests for factual recall and real task application.

## 10. Mixed-workload acceptance protocol

Run paired, repeatable private sessions on the actual Windows 11 host with the same model digest, llama.cpp build, game scene, OBS profile, avatar, audio route, and thermal state.

Record:
- first token and inter-token latency;
- first audible response from device-clock evidence;
- interruption-to-physical-silence;
- speech queue wait and underruns;
- game FPS p50/p10 and 1% lows;
- OBS rendering lag, encoding lag, and network drops separately;
- CPU/GPU/RAM/VRAM use;
- prompt tokens, cache tokens, draft acceptance;
- game objective success and invalid actions;
- conversational response precision, silence preservation, and addressee accuracy.

Test one optimization at a time. Use a preregistered holdout. Retain an optimization only when it improves the intended user-facing metric without degrading the other critical paths.

## Verification boundary

- The CPU reserve utilization fix and regression test are committed on this branch.
- The priority-proxy test no longer treats an optional cache hit as a correctness condition; exact continuation output assertions remain.
- GitHub Actions must complete on the final commit before this branch is considered verified.
- No local hardware, Windows, OBS, audio-device, GPU, Roblox Studio, or live-game test is claimed.
- No measured speedup, win-rate gain, human-equivalent behavior, or production deployment is claimed.
- Parent PR #1125 and this child PR remain drafts; production `main` is unchanged.
