# STAR AI — Delivery Trace, InteractionBench, and Unified Runtime Research

**Research date:** 2026-11-12  
**Implementation branch:** `feat/delivery-trace-integration-20261112-auto11`  
**Parent:** draft PR #1157  
**Purpose:** connect verified user-facing delivery to STAR's existing causal traces, then use that evidence to improve realtime responsiveness, model performance, streaming behavior, game learning, and general-knowledge transfer.

## Executive summary

STAR now has three important building blocks on the active development stack:

1. a versioned task lifecycle ledger;
2. a segmented, playback-aware delivery ledger with SQLite restart recovery;
3. a bounded causal trace system for runtime, inference, tools, voice, avatar, game, hardware, and stream observations.

The missing link was explicit observability for delivery state. This change adds `AgentTraceAdapters.record_delivery_state()` and a low-cardinality `delivery_state_sampled` event.

The adapter emits only:
- delivery state enum;
- delivery and task versions;
- acknowledged segment count and total segment count;
- generation number;
- a recovery-required boolean.

It deliberately does **not** export delivery IDs, task IDs, result hashes, segment hashes, transcript text, audio, viewer identity, or credentials. The caller supplies a trace span so the sample can be correlated with the enclosing voice/runtime operation. The adapter is diagnostic only: it does not mutate the ledger, authorize playback, or prove that a remote viewer heard the stream.

The broader research conclusion is that STAR should optimize the *whole user-perceived path*, not only tokens per second. A fast model that queues behind a slow TTS worker, loses its turn, blocks on game rendering, or repeats an interrupted segment is not a fast streaming assistant.

## 1. Implementation in this branch

### 1.1 Delivery telemetry bridge

Files:
- `star/agent_trace.py`
- `star/agent_trace_adapters.py`
- `tests/test_agent_trace_adapters.py`

New trace event: `delivery_state_sampled`.

New bounded attributes:
- `delivery_state`: one of the finite delivery lifecycle states;
- `delivery_version`, `task_version`, `generation`;
- `completed_segments`, `segment_count`;
- `recovery_required`.

The adapter validates exact record type, enum type, integer types (booleans are rejected), count bounds, and the invariant that a DELIVERED record has all segments acknowledged. It accepts a parent trace span and never copies identifiers or digests into the trace.

### 1.2 Why sample rather than infer

A delivery state is not the same as a spoken transcript, generated text, or remote listener acknowledgement.

- READY means the local delivery obligation is queued.
- CLAIMED means a host worker owns the next segment.
- PLAYING means local playback has started.
- PARTIAL means the current segment was interrupted or incomplete.
- RECOVERY_REQUIRED means a prior worker may still exist; host reconciliation must establish it has stopped before retry.
- DELIVERED means all local playback segments were acknowledged.
- FAILED, CANCELLED, and EXPIRED remain distinct terminal outcomes.

A local playback receipt is not proof that a platform delivered the stream to every viewer. STAR must keep those evidence boundaries explicit.

### 1.3 Trace correlation pattern

The trusted host should create a parent span around one user-facing response and pass its `TraceContext` to the adapter:

```text
runtime.handle
  ├─ memory.retrieve
  ├─ model.generate
  ├─ tool.execute
  ├─ response.compose
  └─ voice.delivery
       ├─ delivery_state_sampled: ready
       ├─ delivery_state_sampled: claimed
       ├─ delivery_state_sampled: playing
       ├─ delivery_state_sampled: partial
       └─ delivery_state_sampled: delivered
```

Do not emit from an audio callback, render thread, or low-latency game-input callback. Queue the validated snapshot to the host/control loop and emit it there. Trace timestamps must use one process-local monotonic clock; never subtract monotonic timestamps from different processes or machines.

## 2. Realtime voice research: evaluate more than interruption speed

### 2.1 InteractionBench (2026-11-02; weekly update 2026-W46)

InteractionBench evaluates four dimensions on the same recorded user audio:
1. conversational timing and floor control;
2. spoken-task accuracy;
3. whisper and volume control;
4. groundedness over conversations longer than twenty turns.

The paper reports 221 items per system across thirteen scenarios and 1,519 graded runs over seven systems. It also reports that timing and spoken-task accuracy can move together, while the turn-based cascade had the highest spoken-task score in its tested setup despite not being the fastest. Hosted timing includes network delay. This is a useful warning against collapsing naturalness, latency, and task success into one score.

STAR application:
- report interruption precision and recall separately;
- measure false yields on backchannels and speech directed at other viewers;
- measure spoken-task completion and factual grounding separately;
- test multi-turn continuity and topic changes;
- score whisper/volume behavior from actual output audio, not a persona prompt;
- keep client-heard latency distinct from model-server latency.

Source: https://arxiv.org/abs/2611.02430  
Benchmark protocol: https://www.fullduplex.ai/benchmarks/interactionbench

### 2.2 Full-Duplex-Bench v3

FDB-v3 uses human-recorded audio, realistic disfluencies, chained tool calls, and separate accuracy, latency, and turn-taking measures. Its reported systems still struggle with self-correction and multi-step spoken tasks. STAR should include corrections such as “go left—actually, turn right,” interruptions during a tool call, and backchannels during long explanations.

Sources:
- https://arxiv.org/abs/2604.04847
- https://www.full-duplex.ai/benchmarks/fdb-v3

### 2.3 Realtime-Venus: interactive and delegated loops

Realtime-Venus describes a full-duplex interactive loop alongside asynchronous delegated work. Its project page reports 97% continuation through user backchannels on Full-Duplex-Bench v1.5; that is a project-reported benchmark result, not an independently measured STAR result or a universal guarantee.

Transferable design:
- the foreground speaker owns the current spoken turn;
- the background thinker may research, plan, and prepare, but its proposals are speculative until validated;
- a genuine interruption cancels stale speech and stale action proposals;
- completed work remains recorded;
- unfinished delivery remains explicit and resumable;
- no narration may claim an external action succeeded without a trusted result.

Source: https://realtime-venus.github.io/

### 2.4 Social Director behavior

STAR should select among speak, short backchannel, react silently, wait, ask, or yield. Silence is a valid action. She should not answer every detected sound or maximize response count. Speaker labels and who-addressed-whom hypotheses should be session-local, confidence-scored, and short-lived; do not create persistent viewer profiles from raw voice identity.

## 3. Inference speed: standardize the measurement boundary

### 3.1 AIPerf for new performance work

NVIDIA documents AIPerf as the replacement path for GenAI-Perf. The migration guide explains a crucial distinction for reasoning models: AIPerf TTFT includes the first token of any kind, while TTFO measures the first non-reasoning output token and is the closer comparison to GenAI-Perf's historical TTFT.

Use the correct metric for each question:
- TTFT: first qualifying token/chunk of any type;
- TTFO: first user-visible non-reasoning output;
- TTST: second qualifying streamed chunk/token boundary as defined by the tool;
- ITL: token-level decode timing only when token accounting supports it;
- ICL: inter-chunk timing, not token timing;
- request latency and output token counts.

STAR's lightweight streaming probe measures content chunks, not token-level ITL. Keep that label. Compare it with AIPerf only on the same pinned backend, model, prompt, concurrency, and output budget.

Sources:
- https://docs.nvidia.com/aiperf/getting-started/migrating-from-gen-ai-perf
- https://docs.nvidia.com/aiperf/dev/reference/ai-perf-metrics-reference

### 3.2 llama.cpp experiments

The llama.cpp server supports continuous batching, parallel decoding, monitoring endpoints, prompt-prefix cache reuse, and speculative decoding. Its documentation warns that prompt-cache reuse can produce non-bit-identical logits on some backend/batch configurations.

STAR experiment matrix:
- cold model load versus warm resident model;
- stable versus changing system-prefix;
- context length and retrieved-memory size;
- KV-cache type/quantization;
- speculative draft model and acceptance rate;
- CPU/GPU layer split and thread placement;
- server slot count and concurrency;
- interactive voice/game load versus idle load.

Every experiment must pair performance with answer quality and interactive health. Record p50/p95/p99 where sample counts justify it, model/build hashes, concurrency, cache state, and failures. Never promote a speed setting solely because tokens/s increased if first-audible latency, answer correctness, game frame time, OBS drops, or audio underruns regress.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

### 3.3 What delivery traces add

Model-server TTFT cannot explain the entire time until a viewer hears STAR. The user-perceived path is:

```text
request received
  → context/memory preparation
  → model first useful content
  → tool work / verification
  → response segmentation
  → TTS synthesis
  → playback queue
  → device output
  → avatar mouth/viseme synchronization
```

Use separate measurements for:
- request-to-first-useful-content;
- request-to-first-audible-output;
- task-complete-to-delivery-enqueue;
- enqueue-to-first-playback;
- playback duration and interruption stop time;
- segment retry and duplicate replay;
- model TTFT/TTFO/ITL/ICL;
- queue wait and tool latency.

Do not subtract timestamps across unrelated clocks. Prefer one host monotonic clock for the local voice path, and record cross-process clock epochs/causal trace IDs rather than assuming comparable timestamps.

## 4. Memory must improve actions, not just recall

### 4.1 Mem2ActBench (ACL 2026)

Mem2ActBench focuses on whether an agent proactively applies long-term memory to choose tools and ground action parameters. It reports 2,029 synthesized sessions and 400 tool-use tasks; its human analysis found 91.3% of tasks strongly memory-dependent. The paper reports that tested memory frameworks remain inadequate at active parameter grounding.

STAR application:
- test whether prior constraints are applied without being restated;
- test whether updated preferences supersede old values;
- test whether deleted/expired memories are not reused;
- test whether remembered tool parameters are correct for the current environment;
- measure action success with memory enabled versus a matched no-memory baseline.

Source: https://aclanthology.org/2026.acl-long.370/

### 4.2 MemoryArena

MemoryArena evaluates multi-session tasks where earlier interaction changes what the agent should do later. It finds that strong performance on static long-context recall can coexist with poor performance when memory must guide later actions.

STAR should add interdependent multi-session tasks for:
- learning a game control scheme, then using it in a later session;
- remembering a creator's project conventions, then applying them to a new file;
- tracking a changing stream role or response preference;
- remembering a failed strategy and selecting a different one;
- carrying forward a task checkpoint without repeating completed actions.

Source: https://arxiv.org/abs/2602.16313

### 4.3 General knowledge

Document ingestion is not learning. Each knowledge item should carry provenance, retrieval date, confidence, scope, freshness policy, exceptions, and an application test. Keep stable facts separate from time-sensitive facts. For current facts, retrieve and cite a fresh source; for durable knowledge, test transfer to a new question or action. STAR's small authored foundation checker must not be described as broad general intelligence or model training.

## 5. Gamer and Creator research

### 5.1 SIMA 2 and Voyager

SIMA 2 demonstrates language-guided reasoning and action in varied 3D virtual worlds. Voyager demonstrates an automatic curriculum and a growing executable skill library with iterative environment feedback.

STAR should use a two-rate game controller:
- reactive loop: camera, movement, aiming, combat, and immediate hazard response;
- strategic loop: objectives, map knowledge, resource planning, skill selection, and practice curriculum.

A skill should be a versioned executable artifact with preconditions, game/build/map scope, input bindings, expected observations, recovery steps, known failure modes, and held-out evidence. A single successful run is not mastery.

Sources:
- https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- https://github.com/MineDojo/Voyager

### 5.2 OpenGameEval for Roblox

OpenGameEval evaluates agents in reproducible, stateful Roblox Studio sessions with separate observation and editing tools, executable scene checks, and simulated gameplay. Its October 2026 paper reports 84 curated core tasks. Runs that inspected all objects later touched by the solution passed 13.4 percentage points more often on scene-only tasks and 9.8 points more often on script-only tasks than runs that inspected none.

STAR should inspect before edit, make the smallest change, execute in an isolated test place, run checks, playtest, inspect visual evidence, and repeat on held-out scenarios.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

### 5.3 GameDevBench

GameDevBench contains 333 Godot game-development tasks spanning 2D/3D graphics and animation, UI, and gameplay. The paper reports that visual feedback improved one tested GPT-5.4 configuration from 41.1% to 52.0%. The current repository also publishes newer leaderboard runs, so paper results and current leaderboard results must not be mixed.

STAR Creator should verify the actual engine scene, run the game with real/reproducible input, test progression and endings, save/reopen, inspect screenshots/video, and replay affected routes after fixes. Compilation is not game completion.

Source: https://github.com/waynchi/gamedevbench

## 6. Unified STAR architecture

The intended runtime should be one coordinated system, not a set of always-on agents competing for the same GPU and CPU budget:

- **Social Director:** conversational floor control and stream-role behavior.
- **Delivery Ledger:** exact speech obligations and playback acknowledgements.
- **Avatar Director:** playback-clock-driven mouth/viseme motion and bounded expressions.
- **Gamer Brain:** reactive control plus strategic planning and verified skill retrieval.
- **Creator Brain:** inspect/build/run/playtest/repair/complete.
- **Knowledge Brain:** source-grounded retrieval, practice, temporal updates, and action transfer.
- **Runtime Governor:** admits work against CPU, RAM, VRAM, audio, game-frame, and OBS budgets.
- **Trace/Evaluation layer:** connects model, tool, memory, game, delivery, avatar, and host timings.

Background research and creation must yield to the realtime voice/game lane. Model routing should use measured latency and current resource pressure, with residency hysteresis to avoid repeatedly unloading/reloading models during a stream.

## 7. Proposed acceptance protocol

Run a private, owner-approved 60-minute rehearsal with the same machine and pinned model/runtime build.

Workloads:
1. conversation-only baseline;
2. game-only baseline;
3. game + OBS + avatar;
4. voice + game + OBS + avatar + one bounded background research task;
5. inject backchannels, genuine interruptions, viewer-to-viewer conversation, a task revision, a TTS stall, and one simulated worker restart.

Measure:
- first useful content and first audible output p50/p95/p99;
- interruption stop latency and false-yield/false-cutoff rates;
- spoken-task completion and groundedness;
- delivery recovery success, stale resume count, duplicate replay count;
- model TTFT/TTFO/ITL/ICL where valid;
- generation throughput and memory pressure;
- game frame-time p95/p99;
- OBS render/output skipped frames;
- audio underruns and avatar synchronization error;
- held-out game-skill transfer and knowledge-to-action success.

Use enough independent sessions for session-clustered inference. If evidence is insufficient, report INCONCLUSIVE rather than PASS. Keep model-quality checks paired with speed measurements.

## 8. Safety and evidence boundaries

- The new adapter is opt-in at the call site; it installs no hooks and performs no I/O.
- Trace data is diagnostic, not an authorization token or source of truth.
- Never emit raw chat, transcript, audio, screenshot, viewer identity, tool arguments, credentials, or arbitrary exception text.
- Do not invoke trace writes from real-time audio/render/input callbacks.
- VTube Studio requires its explicit local plugin authorization; request minimum permissions.
- OBS monitoring should be read-only by default and use its password-authenticated WebSocket.
- Game control and publication remain separate from evaluation and require the existing owner-controlled policy gates.
- No live hardware, model, audio, OBS, avatar, Roblox Studio, gameplay, or livestream result is claimed by this PR.

## Sources

- OpenTelemetry GenAI metrics (development status): https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
- InteractionBench paper: https://arxiv.org/abs/2611.02430
- Full-Duplex-Bench v3: https://arxiv.org/abs/2604.04847
- Realtime-Venus: https://realtime-venus.github.io/
- NVIDIA AIPerf migration: https://docs.nvidia.com/aiperf/getting-started/migrating-from-gen-ai-perf
- NVIDIA AIPerf metrics: https://docs.nvidia.com/aiperf/dev/reference/ai-perf-metrics-reference
- llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Mem2ActBench: https://aclanthology.org/2026.acl-long.370/
- MemoryArena: https://arxiv.org/abs/2602.16313
- SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Voyager: https://github.com/MineDojo/Voyager
- OpenGameEval: https://arxiv.org/abs/2610.02563
- GameDevBench: https://github.com/waynchi/gamedevbench
