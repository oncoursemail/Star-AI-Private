# STAR: Live Speech CPU Reserve and Priority Invariants

**Research date:** 2026-11-11  
**Implementation branch:** `fix/live-speech-cpu-reserve-20261111-auto11`  
**Parent:** `feat/game-control-qos-lane-20261111-auto11`  
**Scope:** protect conversational responsiveness when non-speech inference shares a CPU scheduler with a live VTuber stream. This is an advisory scheduling policy, not a host process-priority change or a hardware speedup claim.

## Executive finding

STAR's existing runtime already separates:
- stream-level workload advice;
- measured inference admission and one-shot resource reservations;
- audio interruption and voice generation;
- stream conversation arbitration;
- game action proposals and fresh-frame verification.

The game-control QoS lane adds `game_control` to the measured inference scheduler and prefers a calibrated CPU route during active gameplay. A further priority invariant is needed: **non-speech CPU inference must not consume the final CPU slot reserved for speech while a stream is live.**

A scheduler that can admit game-control work under speech backlog but has no reserved capacity can create priority inversion: a task intended to improve gameplay may make the streamer less responsive to viewers. The host still owns the actual CPU execution, so this module only supplies conservative admission advice.

## Implemented policy

`AdaptiveQoS` now accepts a bounded `speech_cpu_reserve_slots` setting (default 1, valid range 0–8).

When a stream is live:
- speech jobs may use the full measured CPU slot count;
- every non-speech CPU job is admitted against `cpu_slots - speech_cpu_reserve_slots`;
- a reserve larger than available slots yields zero non-speech CPU capacity;
- GPU admission remains governed by the existing game-FPS, speech-backlog, VRAM, calibration and deadline checks;
- private, non-live rehearsal does not consume the live speech reserve;
- the setting is included in aggregate scheduler status.

This does not preempt a running process. The host must continue to enforce its own deadlines, cancellation, process-tree containment and audio priority.

## Why this is the safer default

A real-time stream has a critical path: capture, turn detection, response generation, TTS, output-device playback, and avatar synchronization. Game-control inference is also time-sensitive, but it is not more important than a viewer being able to speak to STAR and hear her answer.

The reserve is deliberately expressed as a slot count, not a fabricated CPU percentage. A slot is a host-provided concurrency budget; it is not a guarantee that one core is idle or that Windows will schedule it immediately. Hosts must report a realistic slot count and must keep the speech pipeline on the same scheduler or independently enforce an equivalent reservation.

## Research and primary sources

### 1. Windows multimedia scheduling

Microsoft's Multimedia Class Scheduler Service (MMCSS) boosts threads performing time-sensitive multimedia work. Its documented categories include a High category intended for Pro Audio tasks, a foreground Medium category, and lower-priority categories. This supports assigning MMCSS only to the dedicated capture/render threads that actually need it—not to the entire LLM, game agent, research worker, or desktop process.

Source: https://learn.microsoft.com/en-us/windows/win32/procthread/multimedia-class-scheduler-service

**STAR implication:** implement a native Windows audio adapter that registers only the bounded WASAPI capture/render worker with the appropriate MMCSS task profile. Do not mark all AI threads as high priority, and do not use real-time process priority as a shortcut. Measure audio underruns and game frame pacing before and after any host change.

### 2. llama.cpp SPEED-Bench

The upstream llama.cpp SPEED-Bench client measures an already-running server and reports latency, throughput and speculative-draft acceptance by workload category. Its guidance says to match client concurrency to the server slot count (`--np`) when measuring throughput.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**STAR implication:** run separate qualitative and throughput cohorts. A one-slot interactive voice profile should not be tuned from a many-slot throughput result. Record first-content latency, inter-token latency, full completion time, category, concurrency, model/build digest and draft acceptance.

### 3. llama.cpp MoE cache tuning

The upstream MoE cache documentation describes a tuning script that performs multiple cache-size/CPU-share runs, measures host CPU computation and GPU upload behavior, then simulates other cache settings. It explicitly notes that the best CPU share depends on the machine, model, cache size, memory pinning and PCIe path.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

**STAR implication:** do not copy cache sizes or CPU shares from an H100/H200 or another consumer GPU. Tune only if the selected model is MoE and the exact server build exposes the relevant controls. Preserve a baseline and reject settings that improve token throughput but worsen first-audible p95 or game 1% lows.

### 4. Multiparty conversation quality

MP-Bench (Findings of EMNLP 2026) evaluates turn-taking awareness, response appropriateness and comprehension in multi-person speech. Its published evaluation found that evaluated real-time systems still struggled with multiparty comprehension and turn selection.

Source: https://www.fullduplex.ai/benchmarks/mp-bench

**STAR implication:** the speech reserve protects compute, but it does not make social decisions correct. Keep addressee accuracy, silence preservation, interruption behavior, grounding and first-audible latency as independent evaluation lanes.

### 5. Game creation and Roblox operations

GameDevBench provides 333 engine-based game-development tasks across 2D/3D graphics and animation, UI and gameplay logic.

Source: https://github.com/waynchi/gamedevbench

Roblox Studio MCP permissions are configured per game and per person. Full access includes high-risk scopes such as monetization, player consequences, secrets and publishing; data-store writes can affect live player data.

Source: https://create.roblox.com/docs/studio/mcp-open-cloud

**STAR implication:** use the benchmark as a coverage map, not as a claimed pass. Build in a test place, inspect the scene, playtest and verify actual outcomes. Keep publish, monetization, player restrictions, secrets and live data writes outside unattended workflows.

## Regression coverage

The focused tests verify:
1. A live non-speech CPU job is rejected when it would consume the reserved final slot.
2. With two reported CPU slots, one game-control job may use one slot while speech can still use the second.
3. A second non-speech job cannot consume the speech reserve.
4. Private, non-live rehearsal retains its full CPU slot capacity.
5. Reserve configuration rejects booleans and out-of-range values.

Fixtures are deterministic synthetic timings. They do not measure a physical CPU, Windows scheduler, GPU, audio device, OBS session or game.

## Hardware acceptance plan

On the actual Windows 11 machine, use the same model revision, server build, game scene, OBS profile, voice route and thermal state for paired runs.

Record:
- game p10 FPS and 1% low;
- OBS render/encode lag and dropped frames;
- audio underruns;
- capture-to-turn and turn-to-first-audible p50/p95;
- interruption-to-physical-silence p50/p95;
- speech queue wait;
- game-control queue wait and completion p50/p95;
- CPU busy/ready time and per-process usage;
- free RAM/VRAM;
- model prefill, first-token and inter-token latency;
- task completion and spoken answer quality.

Compare reserve values 0, 1 and (where the host has enough CPU slots) 2. Use a private rehearsal first. Retain a nonzero reserve only if it improves speech-tail latency or reduces underruns without unacceptable gameplay degradation. Do not promote from synthetic tests.

## Broader STAR roadmap

### Human-feeling VTuber interaction
- Conversation-level addressee tracking, not just diarization.
- Natural silence and short acknowledgements.
- Full-duplex interruption with confirmed device drain.
- Prosody and delivery evaluation separate from answer correctness.
- Avatar mouth/viseme timing bound to actual output playback.
- Long-session grounding with provenance-backed episodic memory.

### Game mastery
- Reactive movement/aim/control with strict action deadlines.
- Asynchronous strategic planning that cannot overwrite a newer observation.
- Scenario-balanced training and held-out game/map transfer.
- Skill preconditions bound to game/build version.
- Outcome verification from game state, not LLM self-report.

### Game creation and general knowledge
- Engine-based creation tasks, visual inspection and real playtests.
- Roblox/Luau, Blender, Godot/Unity, audio, animation, UI, networking and physics specialists.
- Source-grounded research with publication date, freshness policy and conflict tracking.
- Episodic, semantic and procedural memory, with stale evidence revalidated before reuse.

### Speed and quality
- Model routing by task difficulty and deadline.
- Stable prompt prefixes and per-session cache reuse, validated on the exact llama.cpp build.
- CPU/GPU placement and KV-cache experiments under mixed game+OBS+voice load.
- Speculative decoding accepted only when paired end-to-end latency and quality improve.
- Background research/training deferred when live workload pressure rises.

## Verification boundary

- Source and tests are committed on the child branch.
- Focused tests and repository-wide CI must pass before the change is considered verified.
- No Windows MMCSS/WASAPI implementation, process priority change, model route change, model weight change, live threshold change, game input, avatar output, OBS control, permission grant or broadcast setting is included.
- No actual speedup, better gameplay, improved human-likeness or model-quality gain is claimed.
- Production `main` remains unchanged; the parent QoS PR and this child PR remain drafts for review.
