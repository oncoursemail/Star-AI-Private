# STAR Research: Trusted Stream Measurements, Epoch Safety, and Integrated VTuber Acceptance

**Research date:** 2026-11-11  
**Implementation:** bounded host-measurement recorder feeding the existing rehearsal evaluator  
**Target:** STAR's local-first Windows 11 runtime, optional owner-controlled Linux inference server, and private VTuber rehearsal  
**Status:** offline measurement infrastructure; no device, broadcast, model, or game-control default is changed

## Executive findings

The repository already has substantial building blocks:

- star/stream_hardware_telemetry.py collects trusted CPU, RAM, VRAM, frame-present and speaker-backlog observations off the hot path.
- star/stream_budget.py and star/stream_qos.py provide conservative workload advice and measured inference admission.
- star/llama_metrics.py parses llama.cpp Prometheus metrics and computes same-epoch interval rates.
- star/stream_director.py arbitrates whether a stream event should become a non-binding speech proposal.
- star/gameplay_skill_bank.py, star/game_transfer_eval.py, and star/stream_episode.py separate practice evidence, independent holdout validation and short-lived stream continuity.
- star/stream_memory_eval.py evaluates cross-session memory transfer, temporal updates and forgetting.
- star/stream_rehearsal_eval.py defines the aggregate acceptance gates for a private VTuber rehearsal.
- star/agent_trace.py, its adapters and star/agent_trace_analysis.py provide bounded causal timing.

The remaining gap is practical: the rehearsal evaluator expects a normalized snapshot, but the repository did not yet provide one reusable, bounded collector that safely converts trusted host observations into that exact schema.

This change adds star/stream_rehearsal_recorder.py. It is deliberately not another scheduler, memory store, OBS client or audio system. It is the measurement boundary between real host adapters and the existing evaluator.

The central design principle is:

**A measurement is useful only when its source, clock, process epoch, denominator and missing-data behavior are known.**

## 1. New implementation

### Files

- star/stream_rehearsal_recorder.py
- tests/test_stream_rehearsal_recorder.py

### Existing evaluator integration

The recorder emits exactly the schema accepted by evaluate_rehearsal() in star/stream_rehearsal_eval.py and exposes:

- snapshot() — aggregate-only evaluator input;
- evaluate(limits) — direct call into the existing evaluator;
- health() — sample coverage, source restarts, rejected observations, duplicate events and counter regressions.

No parallel scoring policy or new threshold defaults are introduced. The operator still supplies the target-specific RehearsalLimits.

### Measurement lanes

| Lane | Trusted producer | Recorded value |
|---|---|---|
| First model content | Local streaming inference client | Request start to first non-empty content |
| First audible output | Local playback owner | Request start to playback acknowledgement |
| Game frame pacing | Actual game callback or PresentMon observer | Consecutive presented-frame interval |
| Avatar synchronization | Playback clock plus avatar update callback | Absolute timing error |
| Audio stability | Local audio device owner | Underrun and playback-chunk counter deltas |
| OBS rendering | Authenticated local OBS WebSocket GetStats | Render skipped/total frame deltas |
| OBS output | Authenticated local OBS WebSocket GetStats | Output skipped/total frame deltas |
| Conversation timing | Independently labeled rehearsal scenarios | True/false positive and false negative counts |
| Interruption recovery | Trusted task/playback coordinator | Attempts, successful recoveries, stale resumes and duplicate speech |
| Game learning | Independent held-out game scorer | Held-out trials and successes |

The recorder does not accept or store transcript text, chat messages, speaker names, audio, images, screenshots, prompts, process names, device names, credentials, or arbitrary metadata.

### Why first-content and first-audible are separate

First-content latency measures when the model begins producing useful content. It does not measure when a viewer hears Star.

A cascaded voice path may still need:
1. turn-end detection;
2. transcription or audio understanding;
3. model queueing and prefill;
4. first content;
5. TTS synthesis;
6. audio buffering;
7. actual playback.

The first-audible timestamp must come from the playback boundary, not from the TTS function returning or the model emitting text. A low TTFT can coexist with an unpleasantly long audible pause.

### Epoch-safe counters

The recorder treats audio and OBS counters as cumulative values scoped to an opaque process/device epoch.

- The first sample establishes a baseline and contributes no fabricated delta.
- Later samples are differenced only while the epoch remains unchanged.
- A process/device restart requires a new, never-reused epoch ID.
- A counter decrease inside the same epoch is rejected; the collector must not silently reset its baseline.
- A new epoch establishes a new baseline without subtracting the previous process's counters.
- Render-thread and output-thread skips remain separate.

This avoids a common false metric: interpreting a restarted process's counter reset as a huge negative delta, zero load, or healthy stream.

### Bounded high-rate sampling

Frame intervals can arrive 60–240 times per second. Retaining every observation indefinitely is unnecessary and can create memory growth during a long stream.

The recorder uses deterministic Algorithm-R reservoir sampling per numeric series:

- default maximum: 100,000 samples per series;
- same run ID and observation order produce the same reservoir;
- the retained sample is bounded;
- health() reports observed count, retained count and sampling fraction;
- all-session p95/p99 become estimates once the reservoir is full, not exact whole-session quantiles.

This is an explicit trade-off. The current evaluator consumes sample arrays and uses nearest-rank percentiles. If STAR later needs mergeable, exact-bucket telemetry across multiple processes, add an explicit-bucket or exponential-histogram schema as a separate version rather than pretending a reservoir is a lossless histogram.

### Failure behavior

- Missing samples stay missing; the evaluator reports INCONCLUSIVE.
- Duplicate event IDs are rejected.
- Reused old epochs are rejected.
- Out-of-order frame timestamps are rejected.
- Long pauses over 10 seconds are recorded as discontinuities rather than fake rendered frames.
- Counter regressions are rejected without changing the last valid baseline.
- Event and epoch ledgers have hard caps; the recorder fails closed instead of silently evicting replay protection.
- Independent labels/scoring are required for turn-taking and held-out game outcomes.

## 2. Research: metric temporality and resets

### OpenTelemetry Metrics Data Model

OpenTelemetry distinguishes monotonic cumulative sums, delta sums, gauges and histograms. It also uses start timestamps to identify the beginning of an unbroken metric stream and reason about resets or gaps. Histograms preserve a population count and bucket distribution; exponential histograms offer compressed dynamic-range buckets.

STAR application:
- treat OBS/audio totals as cumulative counters, not gauges;
- attach a fresh process epoch after a restart;
- never subtract values from unrelated process epochs;
- keep missing measurements distinct from a zero;
- keep event timing and aggregate counters separate;
- consider explicit/exponential histograms if multi-process aggregation is added.

Sources:
- https://opentelemetry.io/docs/specs/otel/metrics/data-model/
- https://opentelemetry.io/docs/specs/otel/metrics/

The current recorder is not an OpenTelemetry SDK or exporter. It borrows the temporality and reset discipline while remaining dependency-free and local.

## 3. Research: OBS and Windows game measurement

### OBS WebSocket

The official obs-websocket project is included with OBS Studio 28 and newer. Its README recommends password protection for the WebSocket server.

STAR application:
- connect only to the local OBS instance by default;
- use authenticated WebSocket access;
- never put the password in chat, prompts, source code or telemetry;
- poll GetStats from a background worker;
- record render skips separately from output skips;
- reset the counter baseline when the OBS process/session epoch changes;
- do not let an AI-generated instruction change scenes, start/stop a stream or expose private sources.

Sources:
- https://github.com/obsproject/obs-websocket
- https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

### PresentMon

PresentMon uses Windows ETW presentation events to report frame durations and latency characteristics across DirectX, OpenGL and Vulkan applications. It is a more defensible source for frame pacing than an LLM's visual estimate or a game-reported average FPS.

Caveats in the upstream documentation matter:
- OpenGL/Vulkan applications can have less complete presentation instrumentation;
- some CPU timing fields may be less accurate for those runtimes;
- hardware-accelerated GPU scheduling can affect the accuracy of certain GPU execution measurements;
- collection permissions and process targeting must be handled explicitly.

STAR application:
- use a user-authorized, process-scoped observer;
- do not collect the whole desktop by default;
- prefer actual frame intervals and p95/p99 frame time over a single average FPS;
- keep the observer off the render and game-control threads;
- expose missing/unsupported instrumentation rather than substituting a guessed frame rate.

Sources:
- https://github.com/GameTechDev/PresentMon
- https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md

### WASAPI loopback and privacy

Windows WASAPI loopback can capture the audio stream being played by a rendering endpoint. It is useful for a private playback-timing experiment, but it captures system output rather than a single abstract TTS event and can include unrelated application audio.

STAR application:
- prefer an audio-engine playback acknowledgement/clock when it is sufficient;
- use loopback only in an owner-approved private rehearsal;
- do not persist raw loopback audio;
- derive timing/underrun aggregates locally and discard the captured buffers;
- never use loopback as a hidden viewer-monitoring or recording mechanism.

Source:
- https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording

## 4. Research: natural multiparty streaming

### MP-Bench (Findings of EMNLP 2026)

MP-Bench evaluates voice agents as participants in multiparty conversation. Its benchmark report found that evaluated real-time agents reached at most 22% multiparty comprehension and near-chance turn-taking performance.

That result is a warning: a single-speaker assistant benchmark does not establish that an agent can participate naturally in a busy livestream.

STAR application:
- distinguish direct address from viewer-to-viewer conversation;
- preserve silence when the group does not need an agent response;
- measure false interruptions and missed turns separately;
- evaluate whether a human has already answered;
- test overlap, backchannels, laughter, game audio and topic changes;
- keep speaker labels session-local; do not create voiceprints by default.

Sources:
- https://arxiv.org/abs/2609.13076
- https://aclanthology.org/2026.findings-emnlp.1437/

### Duplex-MPE

Duplex-MPE evaluates whether a full-duplex assistant should answer, remain silent or stop speaking in scenarios with three or four human speakers. Its 2,000 scenarios score fresh response initiation, answer accuracy, silence preservation and stopping when a human resolves a request.

STAR application:
- include explicit and implicit addressing pairs;
- score silence preservation as a positive capability;
- test when a human answers before Star;
- do not reward high response frequency by itself.

Source:
- https://arxiv.org/abs/2609.31948

### LiveKit interruption handling

LiveKit documents adaptive interruption detection versus VAD-only detection, along with false-interruption timeout and optional recovery of speech after a false interruption.

STAR application:
- do not treat every VAD event as a genuine conversational interruption;
- measure interruption precision and recall on labeled scenarios;
- test coughs, laughter, keyboard sounds, game audio and short acknowledgements;
- resume only when the interrupted response is still relevant;
- never replay already-audible speech after a false-interruption recovery.

Sources:
- https://docs.livekit.io/reference/agents/turn-handling-options/
- https://docs.livekit.io/agents/logic/turns/tuning/

Synthetic social rehearsals can improve coverage, but they do not replace consented human evaluation.

## 5. Research: game mastery and game creation

### OpenGameEval (October 1, 2026)

OpenGameEval evaluates agents inside reproducible, stateful Roblox Studio sessions. It separates observation tools from editing tools and scores both the modified scene and a simulated play session.

The paper reports 84 human-curated tasks across 13 models and 16 attempts per task. The best model solved 51.7% of tasks on one attempt and 39.4% five times out of five. Runs that inspected relevant objects before editing were more likely to pass.

STAR application:
- inspect the relevant DataModel/scene before modifying it;
- keep observation and mutation tools separate;
- build in disposable test places;
- use executable scene checks and actual simulated playtests;
- split script-authoring, scene-editing, visual and gameplay tasks into separate evaluation lanes;
- keep a blind holdout suite that the agent cannot inspect or tune against.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

### Generalist game agents

SIMA 2 and Voyager are useful architectural references for visual observation, language-grounded actions, exploration, reusable skills and iterative practice. They do not imply that a local STAR model will inherit their capabilities.

STAR already has a signed GameplaySkillBank, a separate game_transfer_eval and a session-scoped StreamEpisode. Keep those boundaries:
- practice outcomes may guide rehearsal;
- held-out validation stays hidden from action selection;
- a skill suggestion is not permission to control a live game;
- transfer must be measured on unseen levels/seeds/situations;
- creation benchmarks and gameplay mastery benchmarks remain separate.

## 6. Research: long-horizon memory and intelligence

### Recuris: Recursive Experiential-Working Memory (August 25, 2026)

Recuris separates Working Memory (current task state and skill selection) from Experiential Memory (past execution evidence), then uses validation-gated, localized skill updates. The paper reports gains on 35 of 37 completed model-benchmark pairs across its evaluated long-horizon tasks.

STAR application:
- keep current task state compact and explicit;
- retrieve experience only when relevant to the current subgoal;
- use failed execution evidence to localize which skill needs revision;
- update one skill at a time;
- test on a sealed holdout before retaining the change;
- do not let the agent edit its own grader, test roster or promotion threshold.

This complements the existing stream_memory_eval.py, gameplay_skill_bank.py and game_transfer_eval.py; it is not a reason to add another generic vector database.

Sources:
- https://arxiv.org/abs/2608.24876
- https://github.com/Gen-Verse/Recuris

## 7. Research: faster local inference without sacrificing the stream

### llama.cpp SPEED-Bench

The upstream SPEED-Bench client targets an already-running llama-server, reports category-level prompt throughput, decode throughput, client latency and speculative draft acceptance, and provides a baseline/speculative comparison script.

Its README recommends matching benchmark concurrency to the server's slot count for throughput tests and keeping the same benchmark/category/output length when comparing baseline and speculative runs.

STAR application:
1. Pin model SHA-256, quantization, llama.cpp build, context, GPU layers, Flash Attention, CPU threads, batch sizes and server slots.
2. Warm up both candidates consistently.
3. Use the same prompt set and output length.
4. Randomize paired baseline/candidate order.
5. Measure prefill, decode, first content and end-to-end latency separately.
6. Compare quality on a fixed task suite.
7. Repeat with game, voice, avatar and OBS running.
8. Reject a configuration if it improves token throughput but worsens first-audible latency, game frame pacing or audio stability.

Source:
- https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

### NVIDIA AIPerf

AIPerf distinguishes TTFT, TTST, ITL and end-to-end request latency. TTFT includes queueing, network and prompt processing; ITL describes steady-state token generation. Client-observed chunks must not be mislabeled as individual token timestamps.

STAR application:
- retain first-content latency in the inference lane;
- retain first-audible latency in the playback lane;
- report prefill and decode separately;
- include warm-up and time-sliced runs to catch degradation over long sessions;
- do not claim that a single average tokens/second value proves a better user experience.

Sources:
- https://docs.nvidia.com/aiperf/dev/reference/ai-perf-metrics-reference
- https://docs.nvidia.com/aiperf/getting-started/ai-perf-comprehensive-llm-benchmarking

## 8. Integration sequence for the trusted Windows host

The recorder is now ready to receive normalized observations, but the real device producers still need separate implementation and acceptance.

1. Inference client: capture monotonic request-start and first-non-empty-content timestamps; pair with llama.cpp metrics from the same server epoch.
2. Audio playback owner: report actual playback acknowledgement and cumulative underrun/chunk counters. Do not infer audible time from TTS completion.
3. Avatar owner: report the playback clock and corresponding VTube Studio/Live2D update time; protect the VTube Studio token and require its explicit plugin permission.
4. Game observer: use a trusted game callback or user-authorized PresentMon process scope; never accept model-estimated FPS.
5. OBS adapter: use authenticated local GetStats; maintain separate render/output counters and a fresh OBS epoch after restart.
6. Turn evaluator: use synthetic and consented human-labeled scenarios; export only TP/FP/FN aggregates.
7. Task coordinator: report resume attempts only after task freshness has been revalidated.
8. Game evaluator: report held-out success only from an independent scorer whose hidden cases and signing key are outside the agent.

All blocking probes, file I/O and network work belong on worker threads. Audio callbacks, render callbacks and game-control loops must consume recent immutable snapshots and must never wait for this recorder.

## 9. Performance and intelligence acceptance

Run the same private 60-minute rehearsal across these phases:

| Phase | Workload |
|---|---|
| A | Local model only |
| B | Game only |
| C | Voice only |
| D | Game + voice |
| E | Game + voice + avatar |
| F | Game + voice + avatar + OBS |
| G | Full stream plus bounded background research |

For every phase record:
- first-content p50/p95;
- first-audible p50/p95;
- decode throughput and prefill throughput;
- game frame-time p95/p99;
- OBS render skips and output skips separately;
- audio underrun fraction;
- avatar synchronization p95;
- turn precision/recall and silence-preservation cases;
- task recovery and duplicate-speech counts;
- held-out skill transfer;
- CPU, RAM, VRAM and thermal headroom;
- model/server epoch and exact configuration digest.

Use paired baseline/candidate runs. A candidate is an improvement only if it passes the task-quality and privacy gates and does not regress the user-visible stream. Do not combine all measurements into one opaque score that can hide an audio or gameplay regression.

## 10. Recommended feature roadmap

| Priority | System | Next concrete work |
|---|---|---|
| 1 | Trusted host measurement | Add Windows producers for audio, OBS, PresentMon and avatar clocks |
| 2 | Unified runtime | Connect the existing trace, QoS, hardware and rehearsal components |
| 3 | Social Brain | Multiparty address detection, silence preservation and interruption recovery |
| 4 | Avatar Director | Playback-clock lip sync, expression layers and cancellation cleanup |
| 5 | Gamer Brain | Visual state, world model, action planning and held-out skill transfer |
| 6 | Creator Brain | Roblox inspect/build/test loops with OpenGameEval-compatible tasks |
| 7 | Memory | Working/episodic/semantic/procedural tiers with temporal updates and forgetting |
| 8 | Knowledge | Source-backed curricula and cross-domain transfer checks |
| 9 | Inference | Workload-specific model routing and paired SPEED-Bench/AIPerf measurements |
| 10 | Stream personality | Stable approved character traits, callbacks grounded in actual recorded events and natural quiet time |

## 11. Explicit non-claims and rollout boundary

This PR adds a bounded recorder and tests. It does not:
- connect to OBS, WASAPI, PresentMon, VTube Studio or Roblox;
- capture or store audio, video, screenshots, viewer chat or transcripts;
- change the existing stream scheduler or QoS policy;
- start a model, change model routing or alter model weights;
- control a game, publish a Roblox place or start a broadcast;
- automatically promote a memory or game skill;
- establish a measured speedup or intelligence gain;
- establish human-equivalent emotion, experience or consciousness;
- prove a 60-minute live-stream acceptance result.

The recorder is an opt-in measurement primitive. The next implementation must be a separately reviewed Windows host adapter with explicit permissions and private-device acceptance. Production main remains unchanged.
