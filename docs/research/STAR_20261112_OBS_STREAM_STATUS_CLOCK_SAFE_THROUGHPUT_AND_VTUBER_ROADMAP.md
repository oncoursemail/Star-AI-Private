# STAR: OBS Stream Status, Clock-Safe Throughput, and Real-Time VTuber Research

**Research date:** 12 November 2026  
**Implementation branch:** `feat/obs-stream-status-clock-safe-20261112-auto11`  
**Scope:** read-only parsing and sampling of OBS WebSocket v5 GetStreamStatus  
**Status:** offline implementation; no live OBS, audio, avatar, model, or game integration is claimed

## Executive decision

PR #1149 added an epoch-safe parser for OBS GetStats. That is useful for diagnosing OBS render and output-thread pressure, but it does not fully describe whether the actual stream output is active, reconnecting, congested, or sending bytes.

The next narrow step is a separate GetStreamStatus parser and sampler. It deliberately does not merge stream-network evidence with GetStats render evidence. It also handles two protocol realities that a robust host adapter must survive:

1. OBS has been observed returning outputCongestion as JSON null when the output is not connected, despite the protocol table documenting it as a Number.
2. OBS users have reported outputDuration/outputTimecode over-counting wall-clock time with Enhanced Broadcasting. Treat these fields as diagnostics, not as the clock for bitrate or throughput calculations.

The sampler therefore calculates observed output bytes per second from a host monotonic clock and the outputBytes counter. It does not call that number Twitch ingest bitrate or viewer bitrate.

## 1. Research findings applied

### 1.1 GetStreamStatus is a distinct telemetry source

The official obs-websocket protocol documents GetStreamStatus fields:

- outputActive
- outputReconnecting
- outputTimecode
- outputDuration
- outputCongestion
- outputBytes
- outputSkippedFrames
- outputTotalFrames

Official protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

The OBS output API describes congestion as a value from 0.0 (no congestion) to 1.0 (fully congested), and describes dropped frames as frames dropped due to network congestion:

- https://docs.obsproject.com/reference-outputs
- https://github.com/obsproject/obs-studio/blob/master/docs/sphinx/reference-outputs.rst

GetStats and GetStreamStatus should remain separate. GetStats is useful for render-thread and output-thread pressure; GetStreamStatus is the stream-output view. A single blended "stream health" score can hide which subsystem is actually failing.

### 1.2 Null congestion is not zero congestion

OBS WebSocket issue #1176 records an actual GetStreamStatus response with outputCongestion: null when OBS cannot connect to the stream server:

https://github.com/obsproject/obs-websocket/issues/1176

The parser accepts null and a missing congestion field as unknown. It never converts either to 0.0. Zero means a measured no-congestion value; null means the value is unavailable.

### 1.3 OBS duration/timecode are not a reliable wall clock in every configuration

OBS WebSocket issue #1234 documents reports of GetStreamStatus outputDuration and outputTimecode being multiplied by the number of Enhanced Broadcasting tracks:

https://github.com/obsproject/obs-websocket/issues/1234

This is a reported configuration-specific issue, not proof that every OBS setup is affected. It is enough to reject outputDuration as the authoritative denominator for throughput. STAR uses the host's monotonic clock for elapsed time and retains OBS duration/timecode only as diagnostic fields.

### 1.4 Byte throughput is not the same as platform ingest bitrate

The sampler computes:

observed_bytes_per_second = delta(outputBytes) / delta(monotonic_seconds)

This is an OBS-reported output-counter rate. It is useful for detecting stalls and broad changes, but it is not guaranteed to equal the platform's received bitrate, per-track bitrate, network goodput, or viewer playback bitrate. Enhanced Broadcasting, multiple outputs, buffering, retransmission, and server-side behavior can all make those values differ.

No dropped-frame percentage is calculated here. OBS documents skipped and total frames separately; the sampler returns their raw deltas rather than assuming a denominator convention or treating the counters as interchangeable with GetStats.

## 2. Implementation

### Files

- `star/obs_stream_status.py`
- `tests/test_obs_stream_status.py`

### Parser contract

Only the required state and cumulative counter fields are accepted into the typed snapshot. Unknown response fields are ignored and never copied. Numeric values must be finite, nonnegative, and within the safe integer range where applicable. Boolean values are not accepted as numbers.

Optional diagnostics:
- outputCongestion: null/missing becomes None; numeric values must be in 0..1.
- outputDuration: retained as reported milliseconds, never used for elapsed time.
- outputTimecode: retained as a bounded string, never parsed into a clock.

### Epoch-safe interval rules

The host supplies:
- obs_epoch, changed after an OBS process restart or counter-domain reset;
- stream_epoch, changed on every stream start;
- sampled_at_ms, measured from one monotonic host clock.

The sampler:
- emits a baseline on the first sample;
- discards intervals across process/stream epoch changes;
- discards intervals across active/reconnecting state transitions;
- reports no throughput while inactive or reconnecting;
- discards counter rollbacks and non-increasing timestamps;
- computes output byte rate from monotonic elapsed time only;
- preserves congestion as unknown when OBS returns null;
- keeps output skipped-frame and total-frame deltas separate.

A stream reconnect should produce a new state transition and a fresh interval before a rate is reported. The host should still rotate stream_epoch on every deliberate stream start.

### Explicit non-goals

This parser does not:
- open a WebSocket or read the OBS password;
- start/stop a stream or change scenes;
- control OBS or VTube Studio;
- capture microphone, system, or process audio;
- capture video or viewer/chat content;
- decide whether a broadcast is safe to start;
- publish to Twitch/YouTube or interact with viewers;
- alter production settings or model routes.

## 3. Security and Windows host integration

OBS WebSocket is a control-plane interface, not a harmless metrics pipe. The future Windows host adapter should:

1. Connect only to the owner-approved local endpoint by default.
2. Use OBS WebSocket v5 authentication; never log or persist the password in telemetry.
3. Separate read-only requests from control requests at the capability layer.
4. Request only the stats/status methods needed for rehearsal.
5. Avoid binding OBS WebSocket to a public interface.
6. Fail closed when authentication, epoch identity, or sample timing is uncertain.
7. Keep stream start/stop, scene switching, and public broadcast actions behind separate explicit owner policy.

OBS WebSocket protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

## 4. New research for natural VTuber streaming

### 4.1 Full-duplex speech is more than low latency

Full-Duplex-Bench v3 evaluates real human speech with disfluencies and chained tool use. Its published results show why a single "fastest response" score is misleading: the fastest system can have a lower turn-acceptance rate, while a more conservative system can be slower. It separates task success, tool-call quality, first response, task completion, turn-taking and interruption behavior.

- Paper: https://arxiv.org/abs/2604.04847
- Benchmark: https://www.full-duplex.ai/benchmarks/fdb-v3

STAR should separately measure:
- end-of-turn detection;
- interruption detection and recovery;
- first audible word;
- first useful content;
- tool completion;
- final answer completion;
- duplicate/false responses;
- correct silence;
- audio/avatar synchronization.

Do not hide a dropped spoken response behind a fast text token or a content-free filler.

### 4.2 Multiparty conversation is a separate capability

MP-Bench reports that evaluated real-time agents remain weak at multiparty comprehension and turn-taking. Diarization alone is insufficient: STAR must estimate whether speech is addressed to her, to another person, or to the group, and whether another participant has already answered.

Benchmark: https://www.fullduplex.ai/benchmarks/mp-bench

Recommended Social Brain lanes:
- addressee recognition;
- speaker-local turn state;
- overlap handling;
- acknowledgement/backchannel recognition;
- conversation-thread tracking;
- interruption recovery;
- silence preservation;
- moderation and owner-interrupt priority.

Voice naturalness should be evaluated on held-out conversations, not only synthetic pauses.

### 4.3 Windows audio: prefer scoped capture and measured buffers

Microsoft's Application Loopback sample (published 19 February 2026) demonstrates process-specific audio capture: it can capture a selected process and child processes without capturing every app on the output endpoint.

https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/

The process-loopback structure documents target PID and include/exclude process-tree mode:

https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params

The older system loopback path captures the endpoint mix, so it is broader than process-specific loopback:

https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording

For STAR, process audio, system audio, and microphone capture must be separate consent/capability targets. A process ID alone is not a stable process identity; the host should resolve and revalidate the process instance before capture.

Microsoft documents IAudioClient3 and driver-reported buffer periodicities for low-latency shared-mode audio. The host should query the actual device/driver-supported period instead of hardcoding a 1 ms buffer. Lower latency can increase wakeups and CPU use:

https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio

### 4.4 Avatar timing

The future VTube Studio adapter should use its authenticated local WebSocket plugin API and require the user to approve plugin access. Mouth movement should follow the actual audio playback clock, not text-generation time. Expression/gesture layers should be bounded and composable; no idle animation should override speech, critical gameplay, owner interruption, or reduced-motion settings.

Official documentation: https://github.com/DenchiSoft/VTubeStudio/wiki

## 5. Intelligence, memory, gaming and creation roadmap

### 5.1 Memory must improve later actions

MemoryArena evaluates interdependent tasks across multiple sessions. It shows that high performance on static recall does not guarantee successful long-horizon tasks where the agent must learn from one session and use that memory in a later session.

- Paper: https://arxiv.org/abs/2602.16313
- Project/data: https://memoryarena.github.io/

STAR memory should store bounded, provenance-bearing facts and experience records with:
- source and observation time;
- confidence and verification state;
- project/game/version scope;
- action and outcome;
- known failure conditions;
- expiry or revalidation policy;
- contradiction links.

Measure whether memory changes the correctness of a later action, not just retrieval Recall@K.

### 5.2 Real-time game skill needs outcome verification

GameWorld provides 34 games and 170 tasks with state-verifiable success/progress, and distinguishes paused reasoning from GameWorld-RT where the game continues while the agent thinks:

https://gameworld-bench.github.io/

STAR Gamer should have:
- a low-latency reactive controller for movement and immediate threats;
- an asynchronous strategic planner for objectives and route selection;
- a versioned skill library with preconditions, controls, game build, success checks, failure cases and provenance;
- a practice curriculum that increases difficulty based on measured performance;
- transfer tests on unseen maps/scenarios;
- state-based success where the environment exposes reliable state, and independent visual/behavioral verification otherwise.

Do not claim mastery from one successful run. Report win rate, objective completion, deaths/failures, action latency, recovery rate and performance on unseen tasks separately.

### 5.3 Game creation should close the build-test-repair loop

GameDevBench's 333 Godot tasks cover 2D/3D graphics, animation, UI and gameplay. Its reported experiments show the value of visual feedback.

https://github.com/softage-ai/GameDevBench

STAR Creator should inspect the project before editing, build in an isolated copy, launch the engine, inspect screenshots/state, playtest, repair, and rerun regression tests. Roblox publishing, economy/player data, public servers and destructive project operations should remain separate capabilities from local Studio editing.

### 5.4 General knowledge should be evidence-aware

The Knowledge Brain should distinguish stable facts from changing facts, preserve source/date/confidence, detect contradictions, and route current claims to fresh research. The model should be evaluated on multi-domain problem solving and tool-grounded tasks, not on self-reported intelligence or an unsealed prompt set.

## 6. Faster local inference: what to measure before changing settings

OpenTelemetry's GenAI semantic conventions define server time-to-first-token, time-per-output-token, request duration, client operation duration, and agent/tool spans:

- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
- https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md

The llama.cpp server exposes optional Prometheus metrics for prompt tokens/time, generated tokens/time, processing requests and deferred requests:

https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

Run matched experiments for:
- model/quantization;
- GPU layer placement;
- context size and KV-cache type;
- flash attention where supported;
- prefix/prompt cache;
- speculative decoding acceptance;
- concurrency and deferred requests;
- short chat, long reasoning, coding, game commentary and tool workflows.

Report prompt throughput, decode throughput, time-to-first-token, time-per-output-token, end-to-end completion, p50/p95, peak RAM/VRAM, GPU utilization, and quality/task success. Keep the same prompt, model revision, context, sampling options, warm-up and concurrency across paired runs.

Do not assume a faster token rate means better stream responsiveness. The user hears the final TTS/audio output after model generation, queueing, synthesis and playback.

## 7. Prioritized integration plan

| Priority | Work | Acceptance evidence |
|---|---|---|
| P0 | Finish PR #1149/#1150 OBS read-only telemetry | Exact-head CI; parser tests; private OBS rehearsal |
| P1 | Windows host audio adapter | Process-scoped capture; explicit microphone consent; monotonic timestamps |
| P1 | End-to-end voice timing | First-audible p50/p95, false cutoffs, missed turns, correct silence |
| P1 | VTube Studio adapter | User-approved auth; playback-clock lip sync; reconnect/revocation tests |
| P2 | Unified stream-health timeline | Separate render, encoder/output, network, audio, model and avatar signals |
| P2 | Mixed-workload inference scheduler | Gaming + OBS + TTS + inference benchmark on target Windows machine |
| P2 | Gamer skill library | State-verifiable objectives and held-out transfer tests |
| P3 | Creator closed loop | Build, launch, inspect, playtest, repair, regression evidence |
| P3 | MemoryArena-style multi-session evaluation | Later actions demonstrably improve from prior sessions |
| P3 | General-knowledge evaluation | Domain-balanced, source-grounded, sealed holdout |

## 8. Verification boundary

The focused offline implementation was tested locally before publication: 40 pytest tests passed. Ruff and Pyright were not installed in this scratch environment. GitHub Actions is the independent repository gate.

No live OBS connection, Windows audio capture, VTube Studio connection, microphone capture, RTX benchmark, game control, model-weight update, public stream, or production configuration change is included. No actual inference speedup, intelligence gain, human-equivalent behavior, game mastery, or production readiness is claimed.

This is a narrow read-only telemetry improvement. It is designed to make the next Windows integration safer and more measurable, not to pretend the full VTuber runtime already exists.
