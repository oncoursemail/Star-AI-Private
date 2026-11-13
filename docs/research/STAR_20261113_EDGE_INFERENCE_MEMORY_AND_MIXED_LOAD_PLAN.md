# STAR edge inference, KV-memory research, and mixed-load acceptance plan

**Research date:** 2026-11-13  
**Target:** STAR's local-first desktop runtime, 8 GB consumer GPU class, CPU/RAM-backed larger-model server, and simultaneous voice/game/VTuber workloads.  
**Status:** Research and experiment plan only. No inference backend, model default, quantization, scheduler threshold, or release artifact is changed by this document.

## Executive decision

STAR should not adopt a new inference framework or experimental KV-cache fork on paper claims alone. The next performance gain should be selected by a **matched, paired, mixed-load experiment** that distinguishes:

1. prompt prefill and queue delay;
2. autoregressive decode;
3. KV-cache capacity and memory traffic;
4. concurrency and scheduler interference;
5. end-to-end first-audible latency;
6. answer quality and task success;
7. game frame-time, audio stability, and broadcast health.

The current source audit already records a historical five-turn voice run where a heavily loaded CPU server produced 19.28 s mean caller-speech-end-to-first-audio, 11.27 s transcript-ready-to-first-token, and 1.6 tokens/s; a scripted-brain control completed the path in 2.37 s. These measurements are not a current hardware baseline, but they show that queueing, prefill, and server contention can dominate the experience. A separate GPU-helper measurement was taken on an RTX 3060 Ti and must not be extrapolated to another adapter or to concurrent gaming.

**Priority:** measure and reduce queueing/prefill/decode contention before replacing the local model or serving backend. Preserve the known-good local path as the control.

---

## 1. New inference research reviewed

### 1.1 BitNest: bit-nested speculative decoding

Paper: [BitNest: Bit-Nested Speculative Decoding for Memory-Efficient LLM Inference Acceleration](https://arxiv.org/abs/2610.02800), posted 2026-10-02.

The paper embeds a lower-precision draft representation inside a higher-precision target representation, avoiding a separately stored draft model. It also studies lower-precision KV access on the speculative path while retaining higher precision for target verification.

Reported results include 1.48–1.61x end-to-end speedup over FP16 autoregressive decoding across the evaluated 7B–8B models. The main experiments use a single RTX A6000; additional edge-device experiments use NVIDIA Jetson Orin NX. The paper reports lower peak memory than a separately stored draft/target setup and gives separate results for 8 GB and 16 GB Orin NX devices.

**Why STAR should care:** speculative decoding can be attractive on memory-constrained hardware when a conventional draft model would compete with the target model, KV cache, game, and OBS for VRAM.

**Why this is not a drop-in change:** the paper's results are not an RTX 4060 result, and the paper is not an upstream llama.cpp feature. No compatible production implementation was identified in the paper itself. It is a research candidate, not a dependency or default.

**STAR experiment:** first reproduce the existing target-model baseline. If a maintained implementation becomes available for STAR's exact model family and backend, compare target-only decoding with BitNest-like nested drafting on identical prompts, context lengths, quantization, concurrency, and quality holdouts. Record peak VRAM, CPU RAM, first-content latency, TPOT, accepted draft tokens, total tokens/s, and task-quality deltas. Reject it if the draft path worsens p95 first-audible latency or causes game/OBS regressions.

### 1.2 TurboQuant: KV-cache compression

Primary source: [Google Research — TurboQuant](https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/).  
Paper: [TurboQuant: Online Vector Quantization with Near-optimal Distortion Rate](https://arxiv.org/abs/2504.19874).

TurboQuant applies vector quantization to reduce KV-cache memory. The useful architectural distinction is that **weight quantization and KV-cache quantization solve different memory problems**: weights occupy a mostly fixed footprint, while KV cache grows with context length and concurrent sequences.

There are experimental llama.cpp forks advertising TurboQuant-style cache types, including Vulkan paths. These are forks, not the upstream llama.cpp release line. Their benchmark claims and supported head dimensions/model families are fork-specific. A fork's README is not evidence that a given cache type is safe or faster for STAR's exact model.

**STAR decision:** keep this as a controlled, opt-in fork experiment only. Before testing, pin the exact fork commit, inspect the diff against upstream, audit its license and build scripts, verify Windows/Vulkan support on the actual adapter, and compare generated output against the uncompressed cache. Start with the least aggressive supported K/V configuration. Do not use 2–3 bit cache settings as a default for coding, tool use, or long-horizon planning without held-out quality tests.

**Important capacity note:** reducing KV memory can allow a longer context or more simultaneous sequences, but it does not automatically make single-request decode faster. If the current bottleneck is model-weight bandwidth, CPU scheduling, queueing, or prefill, KV compression may yield little or no latency benefit. If the game and OBS already leave very little free VRAM, a compressed cache must be evaluated against the complete mixed workload, not an idle model-only run.

### 1.3 SpecStream: overlapping CPU KV transfers and speculative verification

Paper: [Resource-Efficient Speculative Decoding for Long-Context LLM Serving](https://arxiv.org/abs/2609.33184), posted 2026-09-27.

SpecStream explores streaming committed KV-cache chunks from host memory while overlapping draft work with target verification. It attempts to avoid restoring the full KV history before verification and prioritizes target work to constrain draft interference.

The paper reports average throughput gains over its KV-offloading baseline on Qwen3 and InternLM2.5, with separate multi-GPU comparisons. Those are results for the paper's serving configuration, not a prediction for STAR's local llama.cpp/Vulkan process.

**STAR decision:** adopt the *scheduling principle* for research—target inference must retain priority over speculative work, and CPU↔GPU transfers should overlap only when they do not increase foreground latency. Do not attempt to transplant the research kernels into STAR's desktop runtime.

### 1.4 FlashOffloading: host-DRAM-centric KV management

Paper: [FlashOffloading: Low-Latency KV Cache Offloading for Long-Context LLM Serving](https://arxiv.org/abs/2611.07542), posted 2026-11-05.

The paper combines rolling prefill cache, a hot decode cache, sparse indexing, and compute/load overlap. Its reported deployment uses GLM-5.2 with MTP3 on a modified vLLM-Ascend stack and Ascend 910C infrastructure. The paper reports gains under a 30 ms time-per-output-token service objective.

**STAR decision:** this is a useful design reference for separating *hot decode state* from *bulk historical context*, but it is not an RTX/Vulkan implementation. It should not be presented as a ready-to-use Windows optimization. A smaller STAR analogue may be a bounded host-side conversation archive plus retrieval of only relevant turns, while keeping the active model context short and stable.

### 1.5 Spexis: speculative lookahead scheduling

Paper and code: [Spexis repository](https://github.com/mlsys-seo/spexis), [paper](https://arxiv.org/abs/2609.34370).

Spexis adds speculative parallelism and lookahead scheduling to pipeline/tensor-parallel serving. The repository states that it is a research prototype based on vLLM 0.8.4, requires CUDA 12.4 and at least two NVIDIA GPUs, and has limited model-family support. The paper reports up to 34% higher request rate in its multi-GPU evaluation.

**STAR decision:** not applicable to the single-GPU desktop path. Keep it on the research watchlist for a future multi-GPU Brain/server only if that host actually has the required CUDA GPUs and model topology. Do not add its old pinned vLLM stack to the desktop dependency set.

---

## 2. Hardware-specific decision matrix

| Candidate | Potential value | Main mismatch/risk | STAR disposition |
|---|---|---|---|
| Stable-prefix reuse | Less repeated prefill | Does not speed decode when decode is dominant | Use existing stable-prefix design; measure cache-hit and prefill time |
| Context trimming + retrieval | Less prefill and KV growth | Can omit needed facts if retrieval is weak | Prioritize with groundedness and task-success holdouts |
| Native MTP | Fewer target decode steps on supported models | Exact checkpoint/backend support; extra memory and scheduler pressure | Test only when model card and backend explicitly match |
| BitNest | Draft representation shares target storage | Research implementation and backend compatibility | Research-only until reproducible supported port exists |
| TurboQuant KV | More context/concurrency per VRAM | Experimental forks; quality sensitivity; not always a decode speedup | Isolated opt-in fork experiment |
| SpecStream | Better overlap under CPU KV offload | Research kernels/configuration not desktop-compatible | Architecture reference only |
| FlashOffloading | Efficient very-long-context host DRAM | Ascend-specific modified stack and large-cluster target | Architecture reference only |
| Spexis | Higher multi-GPU request rate | Requires 2+ CUDA GPUs; research fork on old vLLM | Future server research only |
| Larger resident model | Potential quality gain | VRAM contention and slower first audio | Do not adopt without paired quality/latency proof |
| More concurrent slots | Better aggregate throughput | Worse tail latency and game/voice interference | Find the safe concurrency knee under mixed load |

### Local GPU memory budget

The runtime should account for the full resident set:

- model weights and backend allocations;
- KV cache at the active context and slot count;
- graph/workspace and temporary buffers;
- game renderer and assets;
- OBS capture/encode/render allocations;
- VTube Studio and avatar rendering;
- vision/ASR/TTS GPU allocations, if enabled;
- driver/display overhead and a measured safety reserve.

Do not hard-code an assumed "free VRAM" figure from a model file size. Measure process and adapter usage on the host. If process-level VRAM is unavailable, mark it unknown and fail closed for optional GPU-heavy background work. Do not report missing telemetry as zero.

---

## 3. The benchmark STAR should run before changing defaults

Use the existing streaming inference benchmark and paired variant evaluator rather than introducing another benchmark framework.

### Fixed experimental manifest

Every run must record, without storing prompts or generated text:

- model repository/name and exact revision or local model-file digest;
- quantization and tokenizer/template version;
- inference backend, build commit, backend flags, and driver version;
- context length, batch/ubatch, parallel slots, cache types, and speculative settings;
- host CPU, RAM, GPU adapter/driver, power mode, and clock/thermal state;
- workload manifest digest and concurrency level;
- game, OBS, VTube Studio, ASR, and TTS active/inactive state;
- benchmark harness version and random seed where applicable.

### Workload matrix

Run the same frozen workload in each condition:

1. idle host, one request;
2. idle host, two concurrent requests;
3. idle host, four concurrent requests (only if the server supports it);
4. voice-only streaming;
5. game + voice;
6. game + voice + OBS + avatar;
7. game + voice + OBS + avatar + one low-priority background task;
8. cancellation/interruption while the background task is active;
9. long-context retrieval/reasoning;
10. cold start and warm resident-model conditions.

Do not mix cold-start and warm-cache measurements. Run multiple repetitions and report p50, p95, p99, sample count, and confidence interval where appropriate.

### Required metrics

| Layer | Metrics |
|---|---|
| Request queue | queue wait, queue depth, rejected/deferred jobs |
| Prefill | prompt tokens, prefill duration, prefill tokens/s, prefix-cache hit/miss |
| Decode | time per output token, decode tokens/s, accepted speculative tokens |
| Streaming | first content, first audible byte, inter-chunk gap, total completion |
| Cancellation | request-to-cancel acknowledgement, actual worker-stop confirmation |
| Quality | exact task success, groundedness, tool correctness, held-out skill transfer |
| GPU | process VRAM, adapter VRAM, GPU busy, copy-engine busy |
| CPU/RAM | per-process CPU, working set, page faults, memory bandwidth if available |
| Game | frame-time p50/p95/p99, missed frames, input-to-action delay |
| Broadcast/audio | OBS skipped/rendered frames, audio underruns, playback interruption correctness |

First-content is not the same as first audible audio. Server-reported token timing is not the same as end-to-end microphone-stop-to-audible-response timing. Preserve these distinctions.

### Promotion rule

A candidate may be promoted only when all of the following hold:

1. It passes the same held-out correctness and tool-use gates as baseline.
2. It improves the preregistered primary metric by a meaningful margin with a paired confidence interval.
3. It does not regress first-audible p95, cancellation, game frame-time p99, audio underruns, or OBS output beyond predeclared tolerances.
4. It is reproducible on the target host after restart.
5. Its exact model/backend/configuration fingerprint is recorded.
6. Rollback to the previous known-good configuration is tested.

A model's own self-rating is not independent quality evidence. Use deterministic assertions, held-out tasks, and human review for subjective voice/streaming quality.

---

## 4. Intelligence improvements that do not require a larger model

### 4.1 Deadline-aware model routing

Route by task and deadline, not by a single global "best model" score:

- immediate chat/backchannel: low-latency local model or deterministic acknowledgement;
- live game reaction: perception plus fast bounded controller;
- complex game planning: slower reasoning worker with a deadline and cancellation;
- coding/Roblox edits: code-capable model plus Luau analysis, tests, and Studio playtest;
- visual scene understanding: vision model only when a new frame or state change matters;
- research: retrieval-first worker with source provenance and contradiction checks;
- long-horizon creator tasks: durable task ledger, checkpoints, and independent completion tests.

The realtime path must never wait for a research or coding worker. A background result is delivered only if its task/session generation is still current.

### 4.2 Retrieval and context discipline

Use stable system prefixes and compact active context. Retrieve project notes, skills, API docs, and prior lessons by task relevance. Attach provenance and freshness. Summarize old conversation only when the summary preserves unresolved questions, decisions, and exact identifiers needed for the current task.

A larger context window is not automatically better: it increases prefill work and may make retrieval noisier. Evaluate long-context recall separately from response latency.

### 4.3 Tool-grounded reasoning

For code and game creation, use an observe → plan → act → inspect → test → repair loop. A tool call is not proof of success. Require:
- static analysis and unit tests for code;
- actual launch and input-driven playtest for games;
- visual comparison for UI/assets;
- save/reload checks for persistent game state;
- source citations and date checks for research;
- explicit uncertainty when a tool or benchmark does not cover the claim.

---

## 5. VTuber streaming: quality and responsiveness together

The Social Director, audio delivery path, playback ledger, VTube Studio frame pump, OBS adapter, and workload scheduler should share one session identity and monotonic event timeline.

Key invariants:

1. The avatar follows *actual playback acknowledgements*, not text generation.
2. A cancelled response cannot resume or animate after a newer response generation starts.
3. A backchannel or side conversation does not automatically interrupt STAR.
4. A direct high-confidence barge-in can stop only the exact current playback generation.
5. Uncertain speaker/addressee classification defaults to wait/continue, not an aggressive interruption.
6. Background research/coding cannot consume the realtime CPU/GPU reserve.
7. If audio or avatar transport becomes stale, the host returns the avatar to a neutral/listening state and records a content-free health event.
8. The UI should show when STAR is listening, thinking, speaking, interrupted, or doing a background task; it must not imply she heard or saw data that was not actually delivered to her.

Human-feeling quality should be evaluated through turn timing, response appropriateness, interruption recovery, prosody, expressive timing, conversational memory, and audience-rated naturalness. STAR should remain transparent that she is an AI; natural interaction is not a claim of human consciousness.

---

## 6. Game-playing and game-creation intelligence

### Gamer: two-rate control

- Fast loop: bounded input, movement, aiming, dodge, and immediate safety.
- Perception loop: scene/UI/objective changes and local state update.
- Slow planner: strategy, resource planning, map goals, and skill selection.

Never call a large reasoning model for every frame. The fast controller must have a maximum input duration, action allowlist, cancellation, and safe idle behavior.

### Skill learning

Each learned skill needs:
- engine/game/version scope;
- preconditions and expected state;
- action sequence or controller reference;
- provenance and training/evaluation split;
- practice count and failure modes;
- held-out transfer score;
- resource and latency cost;
- version, expiry, and rollback path.

A skill is not "learned" because a model described it or succeeded once. It must pass repeated practice and held-out tasks in a controlled environment.

### Creator: completion is the contract

Use design-document requirements as acceptance criteria. A game is not complete when it compiles. It must launch, accept real input, complete required objectives, reach a valid ending, save state, restart, and reload. Use engine-level screenshots/video and executable assertions to catch visual and gameplay defects. Keep Roblox Studio edits read-first and playtest-gated; do not publish automatically.

---

## 7. Recommended implementation order

| Priority | Work | Why |
|---|---|---|
| P0 | Finish CI/review of the current evaluation and room-director PRs | Avoid extending an unverified stack |
| P1 | Run the existing streaming benchmark against current local and server baselines | Establish the real bottleneck |
| P1 | Add process-level Windows GPU telemetry to the host supervisor | Correct resource admission |
| P1 | Integrate existing scheduler, voice-prep, playback/delivery, and avatar-frame components | Prevent duplicate queues and stale output |
| P2 | Run a model/backend matrix only after baseline is reproducible | Avoid speculative swaps |
| P2 | Test one KV-compression fork in an isolated worktree, if the baseline proves KV-bound | Bound supply-chain and quality risk |
| P2 | Wire room cues to actual diarization/chat/game adapters | Turn policy into live social behavior |
| P2 | Validate VTube Studio and OBS adapters on Windows | Confirm real broadcast behavior |
| P3 | Add a game adapter and a held-out skill-transfer suite | Prove actual game-playing ability |
| P3 | Add complete-game acceptance harnesses | Prove games can be finished and reloaded |
| P3 | Expand evidence-backed general-knowledge curricula | Improve breadth without unverified memory |

## 8. Sources and implementation references

- BitNest paper (2026-10-02): https://arxiv.org/abs/2610.02800
- TurboQuant — Google Research: https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/
- TurboQuant paper: https://arxiv.org/abs/2504.19874
- Experimental llama.cpp TurboQuant fork (not upstream): https://github.com/openalchemy/llama.cpp
- SpecStream paper (2026-09-27): https://arxiv.org/abs/2609.33184
- FlashOffloading paper (2026-11-05): https://arxiv.org/abs/2611.07542
- Spexis paper (2026-09-28): https://arxiv.org/abs/2609.34370
- Spexis research prototype and requirements: https://github.com/mlsys-seo/spexis
- GameDevBench: https://github.com/waynchi/gamedevbench
- OpenGameEval paper: https://arxiv.org/abs/2610.02563
- CEGame-Bench paper: https://arxiv.org/abs/2610.26098
- llama.cpp upstream: https://github.com/ggml-org/llama.cpp
- vLLM speculative decoding docs: https://docs.vllm.ai/en/stable/features/speculative_decoding/
- VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
- OBS WebSocket: https://github.com/obsproject/obs-websocket

## Non-goals and safety boundary

This document does not claim any measured speedup, intelligence gain, game mastery, or human-equivalent behavior. It does not add a new model, download weights, execute external model code, change default permissions, enable camera/microphone capture, connect to OBS/VTube Studio, or publish a game. All experimental backends remain opt-in and isolated. Production `main` and the installer remain unchanged.
