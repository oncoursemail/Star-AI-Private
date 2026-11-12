# STAR AI: Coherent Host Sampling, Coordination Brain, and Capability Research

**Research date:** 2026-11-12  
**Implementation branch:** `fix/stream-host-sampling-coherence-20261112-auto11`  
**Parent:** draft PR #1152, stacked on draft PR #1151  
**Scope:** prevent mixed-window host telemetry from misclassifying active workloads; connect the result to a broader, evidence-driven plan for real-time streaming, game mastery, game creation, memory, and local inference.

## Executive summary

The previous `StreamHostSampler` correctly rejected missing, stale, future-dated, replayed, and cross-clock-epoch observations. A further audit found a subtler consistency problem: individually fresh observations can still describe different sampling windows.

For example, an old `streaming=False` observation can be less than the general three-second age limit while a newer OBS/voice measurement belongs to a different window. If the stream started after the old state observation, the assembler could incorrectly treat the current stream as inactive and omit the metrics required for an active stream. Similarly, a recent game-state observation could be combined with an unrelated old FPS window.

This branch adds two independent guards:

- **State freshness:** streaming and gaming state default to a maximum age of 500 ms.
- **Window coherence:** all observations actually used to assemble one sample default to a maximum timestamp spread of 500 ms.

Both values are configurable and bounded by the general observation-age limit. The oldest timestamp is still used as the assembled sample timestamp. Failed builds do not consume a sequence number or mutate the sampler's epoch state.

This is a pure validation improvement. It does not create the Windows collector or claim that host measurements are now being collected.

## 1. Implementation: coherent sample assembly

### New constructor controls

```python
StreamHostSampler(
    max_age_ms=3_000,
    max_state_age_ms=500,
    max_skew_ms=500,
)
```

- `max_age_ms` remains the outer bound for numeric telemetry.
- `max_state_age_ms` applies more strictly to explicit stream/game active-state observations.
- `max_skew_ms` limits the difference between the newest and oldest timestamps used in one sample.

When omitted, the two new limits default to `min(500, max_age_ms)`, so callers using a smaller overall freshness window do not receive an invalid default configuration.

### Why both guards are needed

State freshness and sample coherence solve different failure modes:

1. A state observation may be old even if every other observation is absent or equally old. The state-age limit rejects it.
2. Every observation may be recent enough individually, but the group may span different windows. The skew limit rejects it.
3. The assembled `captured_ms` remains the oldest timestamp used. The assembler never refreshes an old measurement merely because assembly happened now.
4. A failed build does not consume its sequence number. The host can correct the observation batch and retry the same sequence.

### Expected behavior

| Scenario | Result |
|---|---|
| Streaming/game state is 501 ms old with the default policy | Reject as stale |
| State is fresh; all measurements are within 500 ms | Accept |
| State is fresh; FPS window is 600 ms older than the other observations | Reject for sampling skew |
| Timestamp spread is exactly 500 ms | Accept |
| A required active-stream or active-game measurement is missing | Reject; never fabricate zero |
| A host clock epoch changes | Require a new sampler/runtime |

The 500 ms defaults are conservative starting points for a collector sampling at roughly 2 Hz or faster. The native Windows collector must measure its actual cadence and configure these bounds explicitly. A timestamp check cannot make several independent APIs an atomic snapshot, and a workload can change immediately after a state observation. The host must poll promptly and let the existing runtime age the assembled sample.

## 2. Windows host adapter: source-specific collection contracts

The next implementation should be a small host-owned collector service, not another policy engine. Each collector should return a typed observation with:

- value;
- monotonic capture time;
- host clock epoch;
- source/session epoch where applicable;
- validity and error state;
- bounded collection duration.

Unknown is never zero. A failed probe must produce no observation or an explicit unavailable result.

### CPU, RAM, and GPU

- Use native optional probes for CPU and memory. Do not reuse planner snapshots that substitute convenient zero values when a probe fails.
- For NVIDIA VRAM, require a valid total and used measurement, validate their ranges, and calculate free memory only when `0 <= used <= total`.
- A missing driver, unavailable NVML/`nvidia-smi`, GPU reset, or malformed response must remain unknown.
- Track per-process GPU memory where the API supports it, but do not expose process names or command lines in the scheduler telemetry schema.
- Keep CPU/RAM/VRAM measurements separate from admission decisions. The collector observes; the governor advises; the supervisor executes.

### Game state and frame time

Prefer engine instrumentation when STAR owns the game or has an approved plugin. For external games, use a documented, owner-approved frame-time source such as PresentMon/ETW where supported.

- Identify the active game using an explicit allowlist/session binding, not a language-model guess from a window title.
- Measure frame-time distributions over a declared window, then derive FPS p10 from those samples.
- Preserve sample count, capture interval, source epoch, and invalid-frame count.
- Reset baselines on game-process restart, map/session transition, instrumentation restart, or counter regression.
- Do not infer game FPS from screenshot arrival rate.

### OBS

Use the official OBS WebSocket v5 protocol through an authenticated, loopback-only, read-only adapter by default.

- Keep OBS observation separate from scene/stream control.
- Use the challenge-response authentication flow and never log credentials.
- Maintain an OBS-process epoch and a separate stream-session epoch.
- Keep render-thread and output-thread skipped frames distinct.
- Treat nullable/missing congestion and counters as unknown.
- Reconnect with bounded backoff and establish new baselines after restart.

Sources:
- https://github.com/obsproject/obs-websocket
- https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

### Audio and playback

Keep these points separate in telemetry:

1. TTS text created.
2. First PCM chunk synthesized.
3. PCM submitted to the speaker queue.
4. Output buffer scheduled for DAC playback.
5. Process-scoped loopback observes the output.
6. A physical listener hears the sound.

PortAudio DAC time is a scheduling estimate, not proof of acoustic arrival. Windows process-scoped Application Loopback is a useful optional measurement boundary for STAR's own process tree; do not capture the whole system mix by default. Store aggregate timing and underrun counters rather than raw audio.

Sources:
- https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/
- https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi

## 3. Research: a coordination brain for live conversation and background work

The October 16, 2026 paper **Jarvis: Coordination Deserves a Brain of Its Own in Agentic Interactive Models** is unusually relevant to STAR.

- Paper: https://arxiv.org/abs/2610.23804
- Reference implementation: https://github.com/JensenYX/Jarvis

Its central design principle is **models judge; code enforces**. A coordination model selects from operations constructed by the runtime from the current task state. Code validates the task ID and version before applying the operation. The paper also rechecks plans before execution and results before speaking, and counts delivery only after the full answer has been heard.

The authors report 192/278 task success versus 29/278 in one controlled tau-Voice comparison, and 69% Pass@1 on Full-Duplex-Bench v3 for their Jarvis-Audio configuration versus 60% for GPT-Realtime. These are author-reported results under their own models, task setup, and evaluation; they are not STAR measurements or a prediction of STAR's performance.

### STAR adaptation

Do not import an entire multi-model stack that assumes larger GPUs or separate hosted services. Port the control-plane invariants around STAR's existing async workers and playback clock:

- one local-first, versioned task ledger across voice, game, creator, research, and tools;
- opaque task IDs and monotonically increasing versions;
- a finite typed operation set generated from current legal state;
- compare-and-swap for refine/cancel operations;
- stale worker-result rejection;
- authorization revalidation immediately before side effects;
- separate `STOP_SPEAKING` from `CANCEL_TASK`;
- playback-generation epochs so stale queued audio cannot be delivered after an interruption;
- a delivery receipt only after the current playback epoch confirms the complete response;
- evidence timestamps and validity windows for screenshots/game state, rechecked before the response is spoken.

The coordinator should be deterministic and fast for ordinary turn management. It should not add a deep-model call to every short acknowledgement.

## 4. Research: natural streaming and social intelligence

A natural VTuber needs more than speech recognition and a voice. She needs to understand who has the floor, whether a statement is directed at her, and when silence is the correct response.

Relevant evaluations:

- **Full-Duplex-Bench v3** uses real human speech, disfluencies, chained tool-use tasks, latency, and turn-taking: https://www.full-duplex.ai/benchmarks/fdb-v3
- **MP-Bench** measures multiparty comprehension, turn-taking awareness, and response appropriateness. Its October 2026 page reports that evaluated real-time agents reached at most 22% multiparty comprehension and near-chance turn-taking: https://www.fullduplex.ai/benchmarks/mp-bench
- **InteractionBench** separates conversational timing, spoken-task accuracy, whisper/volume control, and groundedness; it measures output where the client hears it: https://www.fullduplex.ai/benchmarks/interactionbench

### STAR Social Director

Maintain a small explicit floor-state model:

- `LISTENING`: gather evidence without answering every fragment.
- `DIRECTED_TO_STAR`: likely direct address.
- `VIEWER_TO_VIEWER`: conversation is between viewers.
- `BACKCHANNEL`: brief acknowledgement or silence.
- `INTERRUPTION_CANDIDATE`: decide whether the speaker is taking the floor.
- `YIELDING`: stop stale speech and hand over.
- `RESUME_CANDIDATE`: determine whether an unfinished thought is still relevant.
- `RECOVERING`: reconcile transcript, task, audio, and avatar state after a cut-off.

Track speaker, addressee, topic, and confidence separately. If diarization is uncertain, say so internally and do not invent a speaker identity. Preserve separate voice channels when the platform supplies them.

Human-like presentation should mean natural timing, varied prosody, context-aware humor, appropriate silence, and consistent character behavior—not deceiving viewers into believing the system is human. Keep the existing truthful-answer behavior. Do not manufacture offline experiences or claim physical sensations.

### Avatar Director

Keep STAR's internal avatar path primary. Make VTube Studio optional and user-authorized:

- authenticate only after explicit plugin access approval;
- keep the token local and out of logs/source control;
- allowlist parameter names and ranges;
- rate-limit parameter updates;
- handle model-loaded, tracking-state, disconnect, and reconnect events;
- return to a neutral safe pose if the external app disappears.

Coordinate mouth/visemes, gaze, eyes, face, body, hair, and gestures as separate layers. Use phoneme/viseme timing on the playback timeline when available; amplitude-only mouth opening is a fallback.

Source: https://github.com/DenchiSoft/VTubeStudio

## 5. Research: game mastery and transferable skills

### Generalist game agents

- **SIMA 2** combines language instructions, visual interaction, goal reasoning, and improvement from experience in 3D worlds: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- **Voyager** demonstrates an automatic curriculum, an executable skill library, and feedback-driven code repair in Minecraft: https://arxiv.org/abs/2305.16291 and https://github.com/caixianzhou/voyager
- **OpenGameEval** evaluates agents in reproducible, stateful Roblox Studio sessions. Its October 2026 release includes 84 human-curated tasks and executable checks for both scene state and simulated play: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval

### STAR Gamer: two coordinated loops

**Reactive controller**
- movement, aim, camera, dodge, interaction;
- immediate visual/state estimation;
- hard action deadlines;
- safe fallback when observations or strategy are stale.

**Strategic planner**
- goals, map/world model, routes, resource planning;
- tactics, practice curriculum, skill retrieval;
- post-session reflection and next-task selection.

The strategic planner must never block the reactive controller. If the current observation expires, do not issue stale actions; continue a verified safe policy or pause.

### Verified skill record

Each skill should store:

- game/version/mode/map/control scheme;
- preconditions and expected observations;
- executable procedure/controller reference;
- success and failure conditions;
- time/resource budget;
- attempt count and confidence interval;
- held-out scenario results;
- known failure modes;
- last verification date.

Promote skills only after repeated success on fresh states and held-out variants. A single win on one map is not evidence of broad game mastery.

## 6. Research: complete game creation, not just code generation

**GameDevBench** evaluates real game-development tasks across gameplay, UI, graphics, and animation, and reports meaningful improvements from image/video feedback. **OpenGameEval** supplies the complementary Roblox Studio-native stateful harness.

Sources:
- https://github.com/waynchi/gamedevbench
- https://github.com/Roblox/open-game-eval
- https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio

STAR Creator should:

1. inspect project tree, scene/DataModel, dependencies, and assets;
2. record inspected objects before editing;
3. map each requirement to an executable test;
4. edit a disposable project copy;
5. run static checks and unit tests;
6. launch the actual engine and exercise real input;
7. inspect screenshots, frame-time, runtime errors, and state;
8. test save/load, restart, multiplayer, and end conditions where applicable;
9. repair and rerun;
10. promote only when the acceptance contract passes.

A project is not finished because it compiles. It must launch, reach its intended mode, support the core loop, and reach a valid ending.

## 7. Research: faster local inference without quality regressions

The current llama.cpp server provides quantized CPU/GPU inference, parallel decoding, continuous batching, monitoring endpoints, schema-constrained output, function calling, prompt-cache reuse, and speculative decoding.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

The SPEED-Bench client explicitly recommends matching benchmark concurrency to the server's slot count. Use the same model, prompt, sampler, output cap, and concurrency when comparing variants.

### STAR experiment matrix

| Experiment | Measure | Guardrail |
|---|---|---|
| Stable prompt prefix/cache reuse | prefill and first-token latency | context isolation and correctness |
| Speculative decoding | accepted draft tokens, decode rate | reject if draft overhead loses |
| Quantization | quality, speed, VRAM/RAM | held-out task quality must not regress |
| CPU/GPU layer placement | TTFT, tokens/s, CPU/GPU use | protect game/audio threads |
| Parallel slots/batching | throughput and interactive p95 | prevent queueing behind background tasks |
| Model residency | cold/warm start | memory pressure and unload recovery |
| Context compression | latency and long-task success | preserve every active constraint |
| Model routing | quality/speed per task class | difficult tasks cannot silently use weak models |

Report end-to-end p50/p95/p99 latency, first useful content, TTS submission, scheduled playback, optional loopback-observed output, tool completion, task success, factual correctness, peak VRAM/RAM, game frame-time, and OBS render/output drops. Tokens per second alone are not a user-experience metric.

## 8. Research: memory and general knowledge that transfer into action

**MemoryArena** evaluates interdependent multi-session tasks where an agent must acquire information and use it later to guide actions. It demonstrates that high passive recall scores do not guarantee successful memory-guided behavior.

Sources:
- https://digitaleconomy.stanford.edu/publication/memoryarena-benchmarking-agent-memory-in-interdependent-multi-session-agentic-tasks/
- https://arxiv.org/abs/2602.16313

Keep these categories distinct:

- working task state;
- episodic experience;
- semantic facts and concepts;
- procedural, verified skills;
- temporal facts with freshness;
- world/spatial models.

Every reusable memory needs provenance, observation date, verification date, confidence, scope/version, evidence, and known limitations. Separate what a viewer explicitly said from what STAR inferred. Measure memory by whether it improves held-out future actions without increasing stale-fact use or privacy errors.

General knowledge should be evaluated separately for factual accuracy, source freshness, reasoning, and practical transfer. Use projects, experiments, retrieval practice, and delayed tests—not document accumulation alone.

## 9. Security, privacy, and rollout boundaries

- Host telemetry contains bounded numeric observations only; no prompts, transcripts, viewer IDs, raw audio, screenshots, credentials, or arbitrary process metadata.
- The sampler is not a trusted collector and does not authenticate the caller. The host adapter owns source validation and must not expose this type as a model-callable tool.
- OBS health observation and OBS control are separate capabilities.
- VTube Studio tokens remain local and are never logged or committed.
- Process-scoped loopback is opt-in; raw audio is not persisted by default.
- Game input and project edits stay within owner-selected sessions and disposable project copies.
- Generated skills, memories, and model outputs never grant permissions.
- High-risk external actions, publishing, spending, and credential changes remain behind owner approval.

## 10. Validation and acceptance

New focused tests cover:

- state observations older than the stricter state-age limit;
- observations from different sampling windows;
- exact acceptance at the configured skew boundary;
- failed skew validation not consuming the sequence;
- bounded state-age/skew configuration.

The full GitHub Actions offline suite must pass on the exact PR head. Native acceptance must later include Windows cold boot, process start/exit, OBS reconnect/restart, audio endpoint/Bluetooth changes, game start/exit, GPU probe failure/reset, counter resets, voice interruption, and simultaneous game + OBS + voice + inference load.

This branch does not add the actual Windows collector, OBS WebSocket transport, WASAPI capture, VTube Studio connector, game FPS collector, task ledger, or scheduler-to-process-supervisor execution path. It does not claim a measured speedup, intelligence gain, human-equivalent behavior, game mastery, or production readiness. Production `main`, the installer, model weights, and default permissions remain unchanged.
