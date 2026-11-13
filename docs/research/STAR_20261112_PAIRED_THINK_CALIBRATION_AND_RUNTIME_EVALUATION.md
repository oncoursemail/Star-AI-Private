# STAR 2026-11-12 — Paired Thinker Calibration, Runtime Integrity, and Capability Evaluation

## Executive summary

The previous resource-profile work added a configuration fingerprint and an expiring high-water allocation envelope. This follow-up closes two gaps:

1. A profile must be built from paired baseline/active measurements, not a mixture of unpaired system-wide snapshots.
2. A monotonic timestamp alone does not identify the clock epoch. A profile must be bound to the host boot/runtime epoch so it cannot be reused after a reboot or monotonic-clock reset.

The implementation adds ThinkCalibrationPair and ThinkCalibrationSession, adds optional clock-epoch binding to ThinkResourceProfile, and makes IncrementalThinkAdmissionBridge require the matching epoch for epoch-bound profiles.

This is a policy/data-integrity layer. It does not yet collect Windows process telemetry or start inference workers.

## Repository audit: what already exists

The current branch already contains substantial relevant infrastructure:

- RealtimeTelemetryHost in star/stream_hardware_telemetry.py collects global CPU/RAM/VRAM, real frame-present intervals, and local speaker backlog off the hot path.
- StreamHostSampler in star/stream_host_sampler.py enforces fresh observations, one monotonic clock epoch, sequence order, and required metrics for active stream/game workloads.
- resource_probes.py provides read-only Windows and Linux probes.
- stream_workload_admission.py owns abstract CPU/RAM/VRAM allocation units and protected real-time reserves.
- inference_ab.py already performs loopback-only, paired baseline/candidate inference experiments with a fixed synthetic prompt suite and records TTFT/total latency without logging prompt content.
- stream_latency.py records first-audible-response milestones, not just generated tokens.
- stream_turntaking_eval.py and stream_turntaking_cluster.py evaluate false cutoffs, missed end-of-turn decisions, latency, and session-cluster uncertainty.
- game_transfer_eval.py already has signed, preregistered paired holdout evaluation for skill transfer.
- game_skill_memory.py requires independent safe sessions before recommending a skill.

The next improvement should connect these components with measured host evidence rather than duplicate another scheduler, game-memory store, or voice pipeline.

## Paired calibration design

### Why pairing is necessary

A system-wide resource snapshot during a stream is not the same as the incremental cost of one background thinker. If OBS, a game, a browser, or another model changes its load between samples, the resulting profile can accidentally attribute unrelated resource usage to the thinker.

For each repetition, capture:

1. A baseline measurement immediately before the thinker run.
2. The peak/steady active measurement while that exact thinker configuration runs.
3. The same normalized measurement scope and host clock epoch for both observations.

Compute per-dimension positive deltas:

- CPU allocation delta = max(0, active CPU units − baseline CPU units)
- RAM allocation delta = max(0, active RAM units − baseline RAM units)
- VRAM allocation delta = max(0, active VRAM units − baseline VRAM units)

A pair with no positive delta is not evidence that the thinker is free; reject it. Keep the other workload conditions stable. Interleave baseline/candidate trials when comparing two inference configurations to reduce time-of-day and thermal drift.

The profile still uses the maximum observed delta per dimension plus a safety margin. This is intentionally conservative but is not a statistical p95/p99 guarantee. Keep the raw trial log in a host-private experiment artifact; the in-memory profile stores only the aggregate envelope and sample count.

### Session integrity

ThinkCalibrationSession enforces:

- One inference-configuration SHA-256 fingerprint.
- One opaque host clock-epoch identifier.
- Strictly increasing sample sequence numbers.
- Unique opaque sample IDs.
- Non-overlapping baseline/active windows.
- Bounded session lifetime and sample capacity.
- Fresh, non-future active observations.
- Explicit trusted-host assertion at the policy boundary.
- A default target of 30 paired samples, with 8 as the hard compatibility minimum.
- One-shot finalization or explicit abort.

The trusted_host argument is an assertion supplied by the host adapter, not authentication. The Windows process supervisor and IPC boundary must authenticate the caller independently.

### Why clock epochs matter

Monotonic timestamps are comparable only inside the same clock domain. A profile should not survive a host restart merely because a later process happens to report a numerically plausible clock value. New session-built profiles carry an opaque clock_epoch; the admission bridge requires the current host epoch to match before it can enqueue or launch a thinker.

Legacy profiles without an epoch remain supported only through the legacy bridge construction path. Production host integration should use epoch-bound profiles.

## Windows measurement plan: do not confuse global health with per-worker cost

The existing RealtimeTelemetryHost is appropriate for deciding whether the stream/game host is healthy. It is not sufficient by itself to attribute the incremental CPU, RAM, and VRAM cost to one thinker process.

### CPU

Use per-process CPU time deltas from a stable process identity and a shared monotonic clock. Convert process CPU-time delta divided by wall-clock delta into millicores; a process using two logical cores can exceed 1,000 millicores. Keep process start time/creation time with PID to avoid PID-reuse errors.

Microsoft's process performance-counter documentation describes process CPU time, and Microsoft recommends lower-overhead direct APIs such as GetProcessTimes for more frequent component measurements rather than high-frequency PerfMon collection.

### RAM

Use per-process working-set/peak-working-set measurements, with process identity and sampling window. Record both incremental working set and system available/committed memory so the scheduler can distinguish worker cost from host pressure. Do not interpret page-file/commit usage as resident RAM.

### NVIDIA VRAM on Windows

Do not assume NVML per-process memory is available under WDDM. NVIDIA's NVML process-detail documentation explicitly says usedGpuMemory is reported unavailable under WDDM because Windows KMD manages memory. For Windows WDDM, use the Windows GPU process-memory counters/D3DKMT path (or another validated WDDM-aware provider) and retain adapter identity class. NVML remains useful for device-wide utilization/health and supported non-WDDM process accounting.

### Game smoothness

Use real present/display frame timings, not an LLM estimate or a sampled average FPS. PresentMon captures CPU, GPU, and display frame durations through ETW across DirectX, OpenGL, Vulkan, and desktop/UWP applications. Record frame-time p50/p95/p99 and low-percentile displayed FPS during matched stream/game rehearsals.

### Host telemetry versus worker attribution

Keep two separate evidence streams:

- Host health: overall free RAM/VRAM, CPU pressure, game frame times, OBS dropped frames, local speaker backlog, audio underruns.
- Worker attribution: per-process CPU time, working set, and per-process GPU memory/engine use for the exact thinker process.

A host can be healthy while a single worker has a large memory footprint; a worker can be small while the host is already near a critical GPU or memory limit. Admission must consider both.

## Inference speed: benchmark the whole response path

inference_ab.py already has a useful loopback-only, paired baseline/candidate harness. Extend it rather than adding another generic benchmark.

Use a fixed, synthetic suite across short chat, game reaction, game strategy, Roblox code, factual explanation, reasoning, and repetition. Measure:

- Model TTFT and time per output token.
- Total generation time and output throughput.
- First audible response from stream_latency.py.
- Cancellation-to-worker-stop latency.
- CPU/RAM/VRAM incremental peaks.
- Answer correctness and tool-call correctness.
- Game frame-time p95/p99 and OBS skipped/dropped frames.
- Audio underruns and playback backlog.

The OpenTelemetry GenAI semantic conventions currently define/recommend client operation duration, server request duration, server time-to-first-token, server time-per-output-token, workflow duration, agent duration, inference-call counts, tool-call counts, and tool execution duration. Use these as stable metric names where practical. Keep labels low-cardinality; never export prompts, transcripts, viewer identities, tool arguments, secrets, or model file paths.

### llama.cpp speculative decoding

The upstream llama.cpp speculative-decoding documentation lists several materially different strategies:

- draft-simple: a smaller standalone draft model.
- draft-eagle3: a draft model conditioned on target hidden states.
- draft-dflash: block-diffusion draft proposals.
- draft-dspark: DFlash-style proposals with a Markov head.
- draft-mtp: native multi-token prediction heads when supported.
- ngram-cache, ngram-simple, ngram-map-k, ngram-map-k4v, and ngram-mod: draftless token-history/pattern methods.

These are not interchangeable flags. They have different model compatibility, memory overhead, acceptance behavior, and target-backend requirements. For STAR's constrained VRAM, start with the baseline and low-memory n-gram methods; test draft models only when the calibrated resource envelope fits. Keep one configuration fingerprint per exact combination of model artifact, quantization, backend build, context/batch settings, GPU offload, KV-cache type, and speculative method.

Do not promote a strategy based on tokens/second alone. Require a matched improvement in first-audible latency or task throughput without degrading correctness, p95/p99 latency, stream/game frame-time, or audio reliability.

## Natural VTuber interaction: new multiparty evidence

### Duplex-MPE (September 25, 2026)

Duplex-MPE introduces 2,000 scenarios with three or four human speakers plus an assistant. It pairs explicit and implicit addressing of the same request and scores fresh response initiation, answer accuracy, silence preservation, and stopping when a human resolves a request. The key lesson for STAR is that more speech is not necessarily better: a model can respond frequently while answering incorrectly or failing to remain silent.

### MP-Bench

MP-Bench evaluates multiparty comprehension, turn-taking, response appropriateness, and latency. Its benchmark page reports that the evaluated real-time agents were at or below 22% on multiparty comprehension and near chance on multiparty turn-taking. STAR should use it as motivation for a private, consented rehearsal set—not as a performance claim about STAR.

### STAR-specific Social Director acceptance set

Create matched cases for:

1. Explicitly addressed question.
2. Implicitly addressed request in a group.
3. Viewer-to-viewer conversation with no request to STAR.
4. Short backchannel ("yeah", "right", "mm-hm").
5. A viewer resolves another viewer's request before STAR responds.
6. Overlapping speakers with one clear direct address.
7. Topic change during an unfinished response.
8. The assistant should stop speaking after a human supplies the answer.
9. A false-positive near miss that resembles a question but is not directed at STAR.
10. Intentional silence after a completed game event.

Score response initiation, answer accuracy, unnecessary-speech rate, silence preservation, stop latency, interruption recovery, and per-session consistency separately. Use temporary host-assigned turn references; do not build persistent voiceprints or infer stable identities from voice similarity.

## Gaming and game creation: measure skill, not narration

### Roblox: OpenGameEval

Roblox's OpenGameEval repository describes reproducible, stateful Roblox Studio sessions, with executable checks on both the edited scene and a simulated play session. Its core set contains 84 curated tasks and 16 attempts per task in the paper's evaluation. It also tracks exploration/tool-call behavior and reports that inspecting task-relevant objects before editing is associated with higher success.

STAR Creator should:
- inspect the DataModel and relevant instances before editing;
- separate read/observe tools from mutation tools;
- validate Luau and project structure;
- run the actual play session;
- check the edited scene and gameplay state;
- preserve a replayable task artifact and independent scorer result.

### Godot: GameDevBench

The official GameDevBench repository contains 333 Godot 4.4.1 tasks across gameplay logic, UI, 2D graphics/animation, and 3D graphics/animation. It explicitly supports runtime video and screenshot feedback and defaults to strict task confinement. The official README reports that visual feedback substantially improves evaluated agent performance. STAR should adopt the evaluation design and confinement ideas, not copy benchmark results as its own.

### Cross-game learning

SIMA 2 demonstrates language-guided goal-directed behavior across 3D virtual worlds and self-directed learning. Voyager demonstrates an executable skill library and automatic curriculum in Minecraft. STAR already has game_skill_memory.py, game_skill_promotion.py, game_transfer_eval.py, and gameplay_skill_bank.py; focus on connecting actual observations/actions to those verified skill records and keeping held-out levels hidden from the learner.

For every skill, track:
- game and version scope;
- preconditions and expected observation;
- action sequence or policy;
- safe success/failure counts across independent sessions;
- known failure modes;
- latency/precision constraints;
- provenance and last verification;
- held-out transfer result.

A skill should be "verified for this game/version/objective", not universally mastered.

## General knowledge and memory-to-action

Mem2ActBench tests whether long-term memory actually changes future tool selection and parameter grounding, not merely whether an agent can answer an explicit recall question. Its dataset contains 2,029 synthesized sessions and 400 tool-use tasks; human evaluation found 91.3% of tasks strongly memory-dependent.

STAR should keep:
- working memory for the current task/conversation;
- episodic memory for sourced events and outcomes;
- semantic memory for verified facts with provenance/freshness;
- procedural memory for tested workflows;
- skill memory for game and creator abilities.

Measure memory-to-action success, stale-memory errors, contradiction handling, source freshness, and whether retrieved memory improves the result. Do not store viewer details merely because they appeared in chat; retain only consented, task-relevant information under a defined policy.

## Self-improvement and rollout gates

1. Freeze a baseline and a held-out evaluation set.
2. Change one variable per experiment.
3. Run candidate inference/skills in an isolated workspace.
4. Compare quality, latency, resource cost, and real-time regressions.
5. Store content-free metrics and a private artifact digest.
6. Require independent checks before promotion.
7. Keep a rollback point and preserve the baseline.
8. Do not let the model approve its own promotion.

## Primary sources

- Duplex-MPE paper: https://arxiv.org/abs/2609.31948
- MP-Bench: https://www.fullduplex.ai/benchmarks/mp-bench
- Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- OpenTelemetry GenAI metrics: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
- NVIDIA NVML overview: https://developer.nvidia.com/management-library-nvml
- NVIDIA NVML process detail (WDDM limitation): https://docs.nvidia.com/deploy/nvml-api/latest/api/structnvmlProcessDetail__v1__t.html
- Windows performance counters: https://learn.microsoft.com/en-us/windows/win32/perfctrs/about-performance-counters
- Windows performance troubleshooting: https://learn.microsoft.com/en-us/troubleshoot/windows-server/performance/troubleshoot-performance-problems-in-windows
- PresentMon: https://github.com/GameTechDev/PresentMon
- Roblox OpenGameEval: https://github.com/Roblox/open-game-eval
- GameDevBench: https://github.com/waynchi/gamedevbench
- SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Voyager: https://arxiv.org/abs/2305.16291
- Mem2ActBench: https://arxiv.org/abs/2601.19935

## Implementation boundaries

- Added paired-sample and one-shot calibration-session policy.
- Added clock-epoch binding to newly generated profiles and the thinker admission bridge.
- Legacy unbound profiles remain supported only through the legacy constructor path.
- No Windows process collector, NVML/D3DKMT collector, PresentMon integration, inference worker, microphone, TTS, OBS, VTube Studio, Roblox Studio, or gameplay process was started or changed.
- No measured speedup, intelligence gain, naturalness improvement, or game mastery is claimed.
- No model weights, default inference flags, tool permissions, broadcast settings, installer, or production main changed.
