# STAR Research: Causal Agent Tracing, Runtime Observability & Evidence-Gated Learning

**Date:** 2026-11-11  
**Scope:** Python runtime foundation and implementation roadmap  
**Status:** Research-backed design; no exporter or production adapter enabled

## Executive finding

STAR has several useful but separate measurement systems already:

- `star/inference_benchmark.py` measures request and streaming latency.
- `star/llama_metrics.py` parses llama.cpp process counters.
- `star/stream_hardware_telemetry.py` samples host/GPU/game/audio state.
- `star/stream_trace_capture.py` captures paired realtime A/B runs.
- `star/stream_realtime_benchmark.py` evaluates those runs.
- `star/stream_director.py` arbitrates speech proposals.
- `star/task_checkpoint.py` preserves completed background steps.
- Game skill, game episode, knowledge and memory modules retain domain-specific evidence.

The missing layer is a common causal identity that lets the operator reconstruct one user turn or game task across runtime, retrieval, model inference, tool execution, speech synthesis, actual audio playback, avatar updates, gameplay and OBS. A model-server counter alone cannot explain why the viewer heard a late response; a TTS duration alone cannot explain whether a game frame stall or a deferred model request caused it.

This change adds a small, dependency-free trace ledger as an instrumentation contract. It does **not** add automatic instrumentation, networking, persistence, an OpenTelemetry exporter, or new permissions.

## Research findings and design implications

### 1. W3C Trace Context and OpenTelemetry: shared identifiers, semantic structure, and maturity

W3C Trace Context standardizes the `traceparent` header for request correlation. Version 00 uses a 32-hex trace ID, 16-hex parent ID and two-hex flags field; all-zero IDs are invalid, and only the sampled bit is currently defined. STAR's parser therefore accepts lowercase version-00 headers and flags `00` or `01` only. Newly recorded root traces default to sampled (`01`); a received parent context's sampling flag is preserved when creating child spans.

OpenTelemetry's semantic conventions provide common names for spans, metrics, events and resources so signals can be correlated across languages and services. The GenAI attribute registry has moved to the dedicated GenAI semantic-conventions repository; its input/output message and retrieval attributes can contain sensitive information. Treat GenAI conventions as versioned interoperability guidance, not permission to record prompts or transcripts.

Sources:
- https://www.w3.org/TR/trace-context/
- https://opentelemetry.io/docs/concepts/semantic-conventions/
- https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
- https://opentelemetry.io/docs/specs/semconv/general/events/
- https://github.com/open-telemetry/semantic-conventions-genai

**STAR application:** propagate W3C Trace Context IDs across Python, desktop/React, model host, voice, game adapters and remote workers. Keep an explicit schema version and an allowlist of safe fields. Do not add an OpenTelemetry dependency to the latency-sensitive audio callback. A later exporter can translate completed trace snapshots to OTel spans off the hot path.

### 2. LiveKit: interruption, false interruption recovery and long-running tasks are separate concerns

LiveKit documents adaptive interruption handling that distinguishes deliberate barge-in from short backchannels such as acknowledgements. It also documents false-interruption recovery and preemptive generation. Its tool guidance recommends asynchronous work for tasks lasting more than a few seconds so the agent can keep conversing and provide progress updates rather than blocking the turn.

Sources:
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://docs.livekit.io/agents/logic/turns/tuning/
- https://docs.livekit.io/agents/logic/tools/definition/

**STAR application:** trace the full path separately:
1. incoming speech/VAD;
2. turn-finalization decision;
3. interruption decision;
4. LLM request and first content;
5. TTS first chunk;
6. speaker queue submission;
7. device-confirmed output;
8. avatar lip-sync update.

Record events such as `turn_interrupted`, `turn_resumed`, `audio_queued` and `audio_playback_started`. This distinguishes a model that generated quickly from audio that reached the device late. Acknowledgements should not cancel a response unless the interruption detector identifies genuine barge-in.

### 3. Roblox Studio MCP: multi-Studio identity must be explicit

Roblox's August 19, 2026 Studio MCP update states that every MCP tool call takes an explicit `studio_id`, replacing reliance on shared active-Studio session state. The March 5, 2026 Studio update describes built-in playtest automation and multiple running Studio instances.

Sources:
- https://devforum.roblox.com/t/studio-mcp-multi-agent-improvements-and-connected-ai-clients/4820583
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic

**STAR application:** attach an opaque `studio_id`, `game_id`, `game_version` and `skill_id` to tool/game spans. Never infer the target Studio from whichever window happens to be active. The trace ID is correlation only and must not authorize script edits, publishing, purchases or live-player operations.

### 4. Continual learning: a trace is evidence, not a learned skill

AGENTCL proposes controlled task streams that distinguish genuine reuse of earlier sub-solutions from unrelated sequential tasks. It measures transfer and interference rather than treating a larger memory store as proof of learning. TraceCompiler explores compiling repeated tool traces into mostly deterministic workflows, while refusing underdetermined side-effect sequences.

Sources:
- https://arxiv.org/abs/2606.02461
- https://arxiv.org/abs/2608.02680

**STAR application:** use traces to connect:
- skill retrieval;
- environment/version and objective;
- practice attempt;
- tool/action sequence IDs;
- independent outcome evidence;
- held-out evaluation;
- regression after a skill update.

Only promote a reusable skill after external verification and held-out transfer. Repeated success on the same memorized seed is not generalization. A trace is not itself a skill, proof of causality, or proof that the underlying observer is honest.

## New implementation: `star/agent_trace.py`

The module provides:

- W3C `traceparent` parsing/formatting for version 00.
- A root trace identity and child-span context propagation.
- Bounded span and event capacity with explicit overflow errors.
- Thread-safe start/finish/event operations.
- Monotonic-millisecond timestamps supplied by the trusted host.
- Strict component, operation, event, status and attribute allowlists.
- Safe numeric measurements such as TTFT, TTST, queue wait, GPU memory, CPU busy, frame time and OBS render lag.
- Opaque model/route/tool/game/Studio/skill identifiers.
- JSON-safe snapshots for later local inspection or an exporter.

The module intentionally rejects arbitrary keys and text. It never accepts prompts, chat, viewer names, transcripts, screenshots, raw audio, credentials, URLs, exception strings or model outputs. Trace context is not an authentication token and grants no tool or broadcast authority.

## Recommended trace topology

One trace should normally represent a bounded user turn, game task or creator job. Child spans should be created around real operations, not around every token or audio frame.

| Layer | Suggested span/event | Useful evidence |
|---|---|---|
| Runtime | `session.run` | request ID, total duration, outcome |
| Retrieval | `memory.retrieve` | retrieval duration, result count in a future schema |
| Model | `model.generate` | model/route ID, input/output tokens, TTFT |
| Tool | `tool.execute` | tool ID, duration, safe outcome |
| Voice | `voice.turn` | endpointing and interruption decisions |
| TTS | `tts.synthesize` | first-audio latency |
| Audio | `audio.playback` | queue wait and device-output acknowledgement |
| Avatar | `avatar.update` | update duration, playback epoch ID |
| Game | `game.observe`, `game.act` | game/version/skill IDs and measured action outcome |
| OBS | `obs.sample` | render lag and output state |

Use events for point-in-time changes (interruption, task checkpoint, audio playback acknowledgement) and spans for operations with duration. Propagate the same W3C trace ID across process boundaries. For remote processes, use the received traceparent as the parent context and create a new local span ID.

### Clock discipline

This implementation stores host monotonic milliseconds so local durations remain robust to wall-clock corrections. W3C traceparent carries identifiers, not timestamps. A future OpenTelemetry exporter must map monotonic durations onto an epoch clock using a sampled clock-pair and must not compare monotonic timestamps from different machines. Keep device clock, host monotonic, audio stream clock, game frame-present clock and OBS clock distinct until a measured mapping exists.

## Performance and reliability plan

1. Instrument off the hot path: audio callbacks should enqueue a tiny fixed record or update counters; a worker creates spans/events and serializes snapshots.
2. Avoid per-token/per-frame span creation. Use one operation span plus sampled or aggregated events.
3. Correlate AIPerf request-level metrics, llama.cpp process metrics, hardware snapshots, device-output timing and OBS statistics with one trace.
4. Report p50/p95/p99 by workload regime (idle, game, voice, full stream), model, quantization and concurrency.
5. Use traces to locate bottlenecks before changing model routing, KV cache, speculative decoding, CPU/GPU placement or QoS.
6. Compare baseline/candidate on the same model, prompt fixture, context length, game scene and stream load. Keep quality and task-success scores beside latency.
7. Export only sampled, privacy-reviewed traces; retain detailed traces locally for a bounded period.

## Intelligence, gaming and general-knowledge evaluation

Use the trace layer to make existing learning/evaluation systems auditable:

- **Game mastery:** log observation, skill retrieval, action execution and independent result verification. Measure completion, deaths/failures, retries, resource efficiency and transfer to held-out maps/seeds.
- **Game creation:** trace inspect → plan → edit → playtest → analyze → repair → verify. Bind each run to the explicit Studio instance and project version.
- **General knowledge:** trace retrieval source IDs, evidence freshness, answer verification and calibration outcome. Keep source content outside telemetry; retain citations and artifact hashes in the knowledge system.
- **Streaming personality:** evaluate conversational timing, relevance, interruption precision/recall, false-interruption recovery, silence quality, repeated-comment avoidance, playback synchronization and viewer-rated naturalness. Do not equate more speech or human imitation with better interaction.
- **Long-horizon learning:** compare task streams with reusable sub-solutions against unrelated tasks; measure transfer gains and interference. A memory write is not a learning success.

## Phased integration roadmap

1. **Foundation (this PR):** bounded trace context, spans, events and offline tests.
2. **Model adapter:** wrap existing inference benchmark/model router calls; correlate with llama.cpp metrics and AIPerf.
3. **Voice adapter:** add VAD/turn/interruption/TTS/speaker/device-output spans from trusted callbacks, outside PortAudio callbacks.
4. **Game/Studio adapter:** use explicit `studio_id` and versioned game/skill identifiers; correlate action evidence and playtest outcomes.
5. **OBS/avatar adapter:** correlate audio playback, avatar update and OBS rendering/output samples.
6. **Local trace viewer:** visualize critical path, queue wait, model time, TTS time, audio device delay, game frame time and OBS render lag.
7. **Evidence-driven optimization:** only after enough traces, tune model routing and resource admission with baseline/candidate A/B tests.

## Validation boundary

- The new module is an in-memory tracing primitive only.
- It does not automatically instrument any existing runtime path.
- It does not export to an OTel collector or send data over a network.
- It does not store prompt/output content or personal identifiers.
- It does not alter voice, avatar, game-control, model-routing, OBS or permission defaults.
- Passing unit tests will establish the primitive's local contract, not prove a speedup, more intelligence, natural streaming, game mastery or production readiness.
- Windows audio, OBS, VTube Studio, Roblox Studio, actual GPU, and livestream integration require separate hardware acceptance tests.

## Primary references

- W3C Trace Context Recommendation: https://www.w3.org/TR/trace-context/
- OpenTelemetry semantic conventions: https://opentelemetry.io/docs/concepts/semantic-conventions/
- OpenTelemetry GenAI attributes and sensitivity notes: https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
- OpenTelemetry events: https://opentelemetry.io/docs/specs/semconv/general/events/
- LiveKit adaptive interruption: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- LiveKit turn-taking tuning: https://docs.livekit.io/agents/logic/turns/tuning/
- LiveKit asynchronous tools and interruption handling: https://docs.livekit.io/agents/logic/tools/definition/
- Roblox Studio MCP multi-agent improvements (August 19, 2026): https://devforum.roblox.com/t/studio-mcp-multi-agent-improvements-and-connected-ai-clients/4820583
- Roblox built-in Studio MCP and playtest automation (March 5, 2026): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- AGENTCL (June 1, 2026): https://arxiv.org/abs/2606.02461
- TraceCompiler (August 3, 2026): https://arxiv.org/abs/2608.02680
