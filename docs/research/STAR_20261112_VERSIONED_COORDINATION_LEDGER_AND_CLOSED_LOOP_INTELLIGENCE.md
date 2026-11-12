# STAR AI: Versioned Task Coordination, Closed-Loop Learning, and Runtime Research

**Research date:** 2026-11-12  
**Implementation branch:** \`feat/versioned-task-ledger-20261112-auto11\`  
**Parent:** draft PR #1153, stacked on the current stream/voice runtime work  
**Scope:** add a bounded control-plane primitive for coordinating STAR's concurrent tasks, then define how it should connect to streaming, local inference, game learning, creator workflows, and general knowledge.

## Executive summary

STAR already has separate components for asynchronous agent execution, dependency planning, mission checkpoints, stream workload admission, host telemetry, interruption handling, game-skill evidence, and memory evaluation. The missing primitive identified in this audit is a small, shared task-lifecycle record that can reject stale worker results when a task is cancelled, refined, retried, or superseded.

This branch adds \`star/task_ledger.py\` and focused tests. It is deliberately a **control-plane ledger**, not a process manager or permission system:

- Every mutation advances a monotonically increasing task version.
- A worker claims a task with a bounded lease and receives the exact version/attempt it may complete.
- Cancel/refine/lease-expiry/deadline-expiry invalidates old worker handles.
- A stale result cannot overwrite a newer task decision.
- The ledger stores bounded identifiers and SHA-256 digests, not prompts, transcripts, viewer identities, screenshots, audio, or credentials.
- Capacity is bounded and does not silently evict active work.
- Monotonic timestamps are scoped to one host clock epoch and must not be restored across reboot.

The implementation does **not** yet wire the ledger into \`agent_runtime.run_plan\`, Windows process supervision, OBS, VTube Studio, or game controls. Those integrations are staged below so the first change stays testable and does not silently change runtime permissions or production behavior.

## 1. Implementation: versioned task ledger

### New module

\`star/task_ledger.py\`

### Public types

- \`TaskState\`: queued, running, completed, failed, cancelled, expired.
- \`TaskRecord\`: immutable, content-free current state.
- \`TaskLease\`: host-internal attempt handle, not an authorization credential.
- \`ReapReport\`: counts of requeued expired leases and expired task deadlines.
- \`TaskLedger\`: bounded, thread-safe compare-and-swap lifecycle coordinator.

### Lifecycle

\`\`\`text
CREATE
  |
  v
QUEUED --claim(expected_version)--> RUNNING
  |                                   |
  |                                   +--complete(current lease)--> COMPLETED
  |                                   |
  |                                   +--fail(current lease)------> FAILED
  |                                   |
  |                                   +--cancel(expected_version)-> CANCELLED
  |                                   |
  |                                   +--refine(new digest)--------> QUEUED
  |                                   |
  |                                   +--lease expires-------------> QUEUED
  |                                   |
  |                                   +--deadline expires----------> EXPIRED
  |
  +--cancel--------------------------> CANCELLED
  +--deadline expires----------------> EXPIRED
\`\`\`

### Race protection

A task's \`version\` changes whenever its meaning or lifecycle changes. The worker can commit only if all of these still match:

1. task ID;
2. current task version;
3. attempt ID;
4. ledger clock epoch;
5. exact lease expiry;
6. unexpired task deadline.

This closes a common race:

1. Worker A starts version 2.
2. The owner or coordinator refines the task, creating version 3.
3. Worker A returns late.
4. The old version-2 lease is rejected; it cannot overwrite version 3.

The same rule applies after cancellation or lease expiry. A reaper returns an abandoned running task to queued state only after incrementing its version, so the old worker cannot later publish a success.

### Important boundaries

- \`cancel()\` invalidates a worker's ability to commit; it does **not** kill an operating-system process. A trusted supervisor must request termination and verify that the process actually stopped before releasing resource reservations.
- \`stop speaking\` is not \`cancel task\`. Audio playback has its own playback-generation/epoch boundary. A user may stop STAR's current speech while allowing research or game-building work to continue.
- A lease is not a credential and does not authorize a tool. Tool authorization must be checked by the trusted host immediately before the side effect.
- The ledger is in-memory. Durable recovery should use the repository's existing mission/task checkpoint formats and revalidate task contract, worker revision, source revision, and clock epoch. Do not persist raw monotonic timestamps and pretend they remain valid after restart.

### Focused tests

\`tests/test_task_ledger.py\` covers:

- concurrent claim race (exactly one winner);
- compare-and-swap version checks;
- successful completion and failure;
- cancellation and refinement invalidating late results;
- lease renewal and expiry;
- deadline expiry;
- retry after a failed attempt;
- host clock epoch mismatch;
- monotonic clock regression;
- bounded capacity without active-work eviction;
- digest/identifier validation;
- aggregate-only status counts.

Local isolated test result for this branch's new tests: **28 passed**. Repository-wide CI still must validate the exact GitHub head.

## 2. Integration map: use STAR's existing systems

Do not create a second agent framework, scheduler, memory database, or stream controller.

| Existing component | Correct responsibility | Ledger integration |
|---|---|---|
| \`star/orchestration.py\` | Validate task DAG, dependencies, read/write conflicts | Hash the validated task contract; do not duplicate dependency planning |
| \`star/agent_runtime.py\` | Execute trusted async workers, timeouts, result isolation | Later add an optional ledger observer/adapter for start/finish events |
| \`star/mission_checkpoint.py\` | Resume completed read-only mission nodes when revisions match | Restore only independently validated completed state |
| \`star/task_checkpoint.py\` | Atomic step-level checkpointing | Keep detailed resumable step data here, not in the coordination ledger |
| \`star/stream_workload_runtime.py\` | Admission, queueing, resource leases, health freshness | Link task ID to workload request/lease without treating one as the other |
| \`star/stream_hardware_telemetry.py\` | Off-hot-path host CPU/RAM/VRAM/frame/audio observations | Use real, fresh host telemetry before scheduling; unknown is not zero |
| \`star/stream_interrupt_host.py\` | Playback epoch invalidation, physical stop acknowledgement, avatar flush | Keep playback cancellation independent from task cancellation |
| \`star/game_skill_memory.py\` | Store host-scored game episodes | Store verified skill evidence there; task ledger tracks the attempt lifecycle only |
| \`star/game_skill_promotion.py\` / \`star/game_transfer_eval.py\` | Holdout evidence and manual promotion eligibility | Never promote a skill merely because a task completed |

### Recommended future adapter

An optional adapter should subscribe to the existing \`agent_started\`, \`agent_finished\`, \`agent_blocked\`, and \`agent_resumed\` events. It should:

- namespace task IDs by a host-created run ID;
- derive a canonical digest from the validated task contract;
- claim the ledger task on \`agent_started\`;
- commit only a digest of validated result content on successful finish;
- mark failures with bounded error codes, never raw exception messages;
- reconcile checkpoint-resumed nodes explicitly;
- reject duplicate or out-of-order events;
- never make a model-generated task ID or event an authorization signal.

The adapter should be opt-in until the full agent-runtime regression suite and cancellation behavior are verified.

## 3. Faster local intelligence: benchmark the whole request path

The current llama.cpp server documentation describes CPU/GPU quantized inference, parallel decoding, continuous batching, monitoring endpoints, constrained JSON, function calling, prompt-cache reuse, and speculative decoding.

Sources:

- llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- SPEED-Bench client: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

### Research findings that matter to STAR

1. SPEED-Bench measures throughput, latency, and draft acceptance for speculative decoding. Its server instructions say to match client concurrency to the configured server slot count; otherwise the comparison does not represent the intended server configuration.
2. llama.cpp documents prompt-cache reuse for shared prefixes. Its server README also warns that, depending on backend, logits may not be bit-for-bit identical for different batch sizes when prompt caching is enabled. Cache speed tests must therefore include answer-quality and determinism checks, not only tokens/second.
3. Speculative decoding is workload-dependent. A draft model that is too slow or poorly aligned with the target can add overhead. Keep it opt-in per model/task until paired measurements show a net benefit.
4. A smaller model can be faster but less reliable at planning or tool selection. Use task routing and verification rather than replacing every request with the fastest model.

### STAR benchmark matrix

| Experiment | Record | Required comparison |
|---|---|---|
| Cold model vs resident model | load time, first-token latency | same model and prompt |
| Warm prefix cache vs cold prefix | prefill time, TTFT, output quality | same conversation prefix |
| Speculative vs ordinary decoding | accepted draft tokens, tokens/s, p95 latency | same target model, sampler, output cap |
| One slot vs multiple slots | queue time, TTFT, throughput, per-request latency | match actual server slots |
| CPU offload vs GPU-heavy | RAM, VRAM, CPU busy, p95 latency | same model and context |
| Background load on/off | audio latency, game frame-time p99, OBS drops | same private rehearsal |
| Short/long context | prefill, decode, memory pressure | same task class |
| Fast model vs deep model | held-out task success and repair rate | paired task set |

Do not publish a speedup until the exact model, quantization, prompt, sampler, context, concurrency, GPU backend, and warm/cold state are recorded.

### End-to-end latency contract

Measure separate stages rather than one vague "response time":

1. user event received;
2. queue wait;
3. context assembly;
4. model prefill;
5. first token;
6. first useful text;
7. first TTS PCM;
8. speaker queue submission;
9. scheduled DAC playback;
10. optional process-loopback observation;
11. response completion.

A DAC timestamp is not proof that a physical listener heard the sound. Keep client-heard latency separate from model-server latency.

OpenTelemetry's GenAI semantic conventions provide useful metric names for client operation duration, token usage, model-server request duration, time-to-first-token, time-per-output-token, agent invocation, and tool execution. The conventions are marked development/experimental, so STAR should version its telemetry schema and avoid binding runtime behavior to unstable attribute names.

Source: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md

## 4. Natural VTuber streaming: social timing, not just a voice model

A natural streamer needs to know when to speak, when to listen, and who currently has the floor. A good TTS voice alone does not solve multiparty conversation.

### STAR Social Director

Build a deterministic fast path for turn state, with model reasoning only when the conversational context is ambiguous.

Track separately:

- speaker channel/source when the platform supplies one;
- addressee confidence;
- whether a remark is directed at STAR or another viewer;
- current floor owner;
- interruption evidence;
- topic continuity;
- whether STAR has an unfinished thought;
- whether a previous answer was actually delivered;
- uncertainty and stale transcript state.

Recommended states:

- \`LISTENING\`
- \`DIRECTED_TO_STAR\`
- \`VIEWER_TO_VIEWER\`
- \`BACKCHANNEL\`
- \`INTERRUPTION_CANDIDATE\`
- \`YIELDING\`
- \`RESUME_CANDIDATE\`
- \`RECOVERING\`

Do not infer real identity from voice similarity. Do not answer every utterance. If diarization or addressee detection is uncertain, silence or a short neutral acknowledgement is safer than inventing who said what.

### STAR Avatar Director

Use the internal avatar path as the primary controller and VTube Studio as an optional owner-authorized adapter.

VTube Studio's public API supports plugin authentication, event subscriptions, hotkeys, custom parameters, and feeding parameter values to the current Live2D model. The user must approve plugin access in VTube Studio, and that permission can be revoked. Treat the API token as a local secret; never commit it, print it, or expose it as a model tool.

Sources:

- API: https://github.com/DenchiSoft/VTubeStudio
- Plugin permission behavior: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

Coordinate separate layers:

- phoneme/viseme mouth motion synchronized to actual playback;
- amplitude-only mouth motion as a fallback;
- gaze and attention;
- blinking and eye expressions;
- facial affect;
- body gestures and idle motion;
- hair/secondary motion;
- neutral reset after disconnect or interruption.

Naturalness should mean believable timing, prosody, context-aware humor, appropriate silence, and consistent character behavior. STAR should remain transparent that she is an AI and must not fabricate offline experiences or physical sensations.

## 5. Windows audio and streaming observations

Microsoft's Application Loopback sample demonstrates capture restricted to one process and its child processes, rather than the entire system mix. It requires Windows 10 build 20348 or later. This is a promising optional boundary for measuring STAR's own output without recording unrelated application audio.

Source: https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/

Implementation rules:

- default to no capture until the owner enables the adapter;
- capture only the selected STAR process tree;
- store aggregate timing/underrun measurements, not raw audio;
- keep capture callbacks off the game/render/audio hot path;
- treat loopback silence as ambiguous when the selected process has no active render stream;
- never claim acoustic arrival from a software scheduling timestamp.

OBS WebSocket is included with OBS Studio 28.0 and newer. Its maintainers strongly recommend password protection. STAR should use loopback-only, authenticated, read-only observation by default; scene switching, streaming, recording, and source mutation require a separate explicit capability.

Sources:

- https://github.com/obsproject/obs-websocket
- https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

## 6. STAR Gamer: learn through closed-loop interaction

### Research anchors

**SIMA 2** (Google DeepMind, November 13, 2025) moves beyond fixed instruction following by combining language understanding, goal reasoning, visual interaction, and improvement from experience in 3D environments. DeepMind describes self-generated tasks and experience data as part of its self-improvement loop.

Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

**Voyager** demonstrates an automatic curriculum, an executable skill library, and feedback-driven program improvement in Minecraft. It is a useful design reference for reusable skills rather than repeatedly rediscovering the same actions.

Source: https://arxiv.org/abs/2305.16291

**OpenGameEval** evaluates agents inside reproducible, stateful Roblox Studio sessions, with executable checks over both edited scene state and simulated play. Its repository describes 84 human-curated core tasks and notes that inspecting relevant objects before editing improves outcomes.

Source: https://github.com/Roblox/open-game-eval

### STAR Gamer: two loops

**Reactive loop (deadline-bound):**
- perceive current screen/game state;
- choose an action from a host-allowlisted action set;
- execute only while the observation remains fresh;
- verify action result;
- fall back to a safe policy or pause if the state becomes stale.

**Strategic loop (background):**
- understand objectives and mechanics;
- build a map/world model;
- plan routes and resource use;
- retrieve prior skills;
- propose practice tasks;
- review failures and create a better curriculum.

The strategic model must never block the reactive controller. Never send stale movement/combat input after a pause, map transition, focus loss, or game-process restart.

### Skill record

Each reusable skill should include:

- game/version/mode/map/control scheme;
- preconditions and observable state;
- action procedure or controller reference;
- success, failure, and unsafe conditions;
- attempts and independent sessions;
- held-out environment results;
- known failure modes;
- last verified revision.

Practice evidence and held-out transfer evidence must remain separate. One win is not mastery. Promotion should remain manual and use the existing \`game_skill_memory\`, \`game_skill_promotion\`, and \`game_transfer_eval\` evidence gates.

## 7. STAR Creator: finish games, not just scripts

Use a stateful inspect/build/play/repair loop:

1. inspect the project tree, engine scene/DataModel, dependencies, and assets;
2. inspect objects that the requested change touches;
3. map requirements to executable checks;
4. work in a disposable project copy;
5. run static checks and unit tests;
6. launch the real engine;
7. exercise actual input and gameplay;
8. inspect screenshots, runtime errors, state transitions, and frame-time;
9. test save/load, restart, multiplayer, and end conditions when relevant;
10. repair and rerun until the acceptance contract passes.

A project is not finished because it compiles. It must launch, enter its intended mode, support the core loop, and reach a valid ending.

The existing Roblox benchmark harness and Studio playtest host should be the first integration target. Blender, Godot, and Unity should reuse the same artifact/verification contract, with engine-specific adapters.

## 8. General knowledge and transferable intelligence

STAR already has general-knowledge evaluation and practice components. The next improvement is to measure delayed transfer rather than counting documents ingested.

Recommended learning loop:

1. choose a small curriculum objective;
2. retrieve a verified source;
3. form a compact explanation and concept graph;
4. solve a novel problem without copying the source;
5. run an independent checker where possible;
6. schedule delayed retrieval;
7. record confidence, evidence, and known uncertainty;
8. promote only when performance transfers to a new task.

Cover mathematics, physics, computing, engineering, biology, history, geography, languages, art, music, economics, psychology, game design, and practical digital skills. Separate semantic facts from procedural skills and episodic experience.

## 9. Phased engineering plan

| Phase | Deliverable | Acceptance evidence |
|---|---|---|
| 0 | Versioned task ledger (this branch) | deterministic concurrency, stale-result, deadline, and lease tests |
| 1 | Optional adapter for \`agent_runtime\` events | exact-head full suite; no duplicate/out-of-order event commits |
| 2 | Supervisor reconciliation | process exit confirmed before resource lease release |
| 3 | Windows telemetry collector hardening | real CPU/RAM/VRAM and frame-time samples; bounded probe timeouts |
| 4 | OBS read-only transport | authenticated loopback connection, reconnect epochs, no secret logging |
| 5 | WASAPI process-loopback experiment | opt-in, process-scoped capture, no raw audio retention |
| 6 | Social Director rehearsal | held-out multiparty turns, false interruptions, p95 first-audible latency |
| 7 | Avatar Director | playback-synchronized visemes, neutral recovery, VTS permission test |
| 8 | Gamer closed-loop pilot | held-out maps/scenarios, safe action limits, verified skill transfer |
| 9 | Creator playtest pipeline | actual engine launch, core-loop completion, regression checks |
| 10 | Knowledge transfer | delayed retrieval and novel-task evaluation |

## 10. Acceptance and safety rules

- Unknown telemetry is not zero.
- A model output is not host telemetry.
- A task lease is not permission.
- A cancelled task's late result must never be accepted.
- A cancelled task is not proof that its process stopped.
- Releasing a resource reservation requires host-confirmed termination.
- Stopping speech must not silently cancel background work.
- Viewer chat cannot grant tool permissions or control local processes.
- OBS control and VTube Studio parameter injection remain opt-in capabilities.
- Do not store raw private audio, video, chat, or credentials in task records.
- Do not promote game skills from practice-only evidence.
- Do not claim human-equivalent behavior, measured speedups, or game mastery without the corresponding held-out evidence.

## Validation boundary

The new task-ledger module is an in-memory control-plane primitive with no external side effects. The 28 focused tests passed in an isolated local run. The exact repository branch still needs GitHub Actions validation. This branch does not add a Windows collector, OBS transport, WASAPI capture, VTube Studio connector, game controller, durable ledger store, or automatic process termination. It does not change model weights, routing defaults, runtime permissions, production \`main\`, or release artifacts.
