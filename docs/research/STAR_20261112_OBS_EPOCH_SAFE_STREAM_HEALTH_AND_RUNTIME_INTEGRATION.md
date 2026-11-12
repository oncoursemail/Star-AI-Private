# STAR: OBS Telemetry, VTuber Runtime Integration, and the Next Intelligence Milestones

**Research date:** 12 November 2026  
**Implementation branch:** `feat/obs-stats-epoch-adapter-20261112-auto11`  
**Implementation scope:** pure OBS GetStats parsing and epoch-safe counter deltas  
**Status:** reviewable development work; no live OBS/VTube Studio connection or shipped VTuber mode is claimed

## Executive decision

STAR already has substantial candidate work in its open development chain: consent-gated speech arbitration, measured workload admission, hardware telemetry, llama.cpp metrics, trace profiling, private rehearsal scoring, task continuity, game-skill transfer and turn-taking evaluation. The immediate gap is no longer another standalone evaluator. It is the trusted host adapters that turn real Windows/OBS/audio/avatar/game observations into the existing evidence pipeline.

This change takes the first narrow step: a dependency-free parser and interval sampler for OBS WebSocket v5 `GetStats`. It keeps render-thread loss and output-thread loss separate, scopes cumulative counters to both the OBS process and a specific stream session, and refuses to invent a zero-loss interval when the first sample is only a baseline.

The adapter deliberately does **not** open a WebSocket, read a password, start/stop a stream, change scenes, or inject avatar parameters. Transport and controls belong in a separately reviewed Windows host service.

## 1. New implementation

### Files

- `star/obs_stats.py`
- `tests/test_obs_stats.py`

### Parser contract

`parse_get_stats_response(response_data, obs_epoch, stream_epoch, sampled_at_ms)` accepts the OBS `GetStats` response-data object and extracts only these allowlisted values:

| OBS field | STAR field | Meaning |
|---|---|---|
| `activeFps` | `active_fps` | Current rendered FPS |
| `averageFrameRenderTime` | `average_frame_render_time_ms` | Average render time in ms |
| `renderSkippedFrames` | `render_skipped_frames` | Render-thread skipped-frame counter |
| `renderTotalFrames` | `render_total_frames` | Render-thread total-frame counter |
| `outputSkippedFrames` | `output_skipped_frames` | Output-thread skipped-frame counter |
| `outputTotalFrames` | `output_total_frames` | Output-thread total-frame counter |
| `cpuUsage` | `cpu_usage_percent` | Optional OBS CPU percentage |
| `memoryUsage` | `memory_usage_mib` | Optional OBS memory in MiB |

Unknown fields are ignored and never copied. Values must be finite and bounded; booleans are not numbers; counters must be nonnegative integer-valued JSON numbers within the exactly representable integer range. No scene names, source names, chat, stream keys, passwords, URLs, or media are accepted.

### Epoch-safe sampling

OBS counters can outlive an individual broadcast. A valid stream report therefore needs two host-supplied epochs:

- `obs_epoch`: changes whenever the OBS process is restarted or its stats counter domain changes.
- `stream_epoch`: changes on every stream start, even if OBS remains open.

The first sample in an epoch is a baseline, not a zero-rate result. The sampler returns no interval for a new epoch, a counter rollback, a non-increasing monotonic timestamp, or an impossible counter delta. A later valid sample can begin a new interval. The caller must use one host monotonic clock for all samples.

The result keeps four counters separate: render skipped, render total, output skipped and output total. `rehearsal_counts()` maps only a valid interval into the existing private rehearsal evaluator's schema. A baseline or invalid interval cannot be submitted as a passing zero.

### Why separate the two OBS loss channels?

- **Render-thread skips** indicate OBS could not compose frames in time. Investigate GPU headroom, scene complexity, browser sources, filters, canvas size and game frame pacing.
- **Output-thread skips** indicate the output/encoder path is losing frames. Investigate encoder load, preset, output resolution and competing CPU/GPU work.
- **Network congestion/reconnects** are separate and must be sampled from `GetStreamStatus`, not inferred from `GetStats` output skips.

A single combined “stream health” score would hide the bottleneck and could cause STAR to apply the wrong fix.

## 2. OBS WebSocket research and integration contract

OBS Studio 28+ includes obs-websocket by default. The v5 server normally listens on port 4455, although the port is configurable. The OBS project explicitly recommends password protection. The v5 protocol uses a Hello/Identify handshake and challenge-response authentication when enabled.

`GetStats` is a read-only request with no request fields. The official protocol documents current FPS, average frame render time, render skipped/total frames, output skipped/total frames, CPU, memory and WebSocket message counts.

`GetStreamStatus` is a separate read-only request and exposes output-active, reconnecting, congestion, bytes, skipped frames and total frames. STAR should use it to distinguish network/output state from renderer health. Stream and recording counters should be scoped to the specific output being evaluated.

**Host integration rules**

1. Default to loopback only. Do not expose OBS WebSocket to the public internet.
2. Use OBS's authentication handshake; never disable the OBS password to make automation easier.
3. Store credentials in Windows Credential Manager, not STAR settings JSON, SQLite, logs, environment dumps or Git.
4. Start with a read-only request allowlist: `GetVersion`, `GetStats`, `GetStreamStatus`, and only the additional read-only requests needed for target FPS and output diagnosis.
5. Do not include scene/source mutation, stream start/stop, recording deletion, hotkey injection or arbitrary vendor requests in the telemetry adapter.
6. Poll on a low-rate background worker (initial experiment: 1–2 Hz); never poll from an audio callback, render callback or game-control loop.
7. Record a baseline at stream start and discard intervals across OBS restart, stream restart, counter rollback or clock discontinuity.
8. Store only aggregate numeric samples in private local rehearsal data. Do not upload stream telemetry by default.
9. If OBS disconnects or a sample becomes stale, mark the measurement missing/inconclusive. Do not carry forward a stale “healthy” state.
10. Any future automatic scene or stream control must be a separate owner-approved capability, not implied by read-only telemetry.

## 3. VTube Studio and avatar embodiment

The official VTube Studio API is a local WebSocket plugin interface (default port 8001, configurable). A plugin requests an authentication token; the user sees an approval prompt. The API supports event subscriptions, hotkey triggering, parameter injection and other operations, with additional permissions for some actions.

**Recommended STAR integration sequence**

### Phase A — read-only discovery

- Detect an active local VTube Studio API instance.
- Read API state and version.
- Ask the user to enable Plugin API access and approve the named STAR plugin.
- Store the token using the OS credential store.
- Subscribe only to required low-volume events (for example model loaded/unloaded).
- Do not request screenshot, item-loading or other unrelated permissions.

### Phase B — controlled expression and motion

- Map STAR's explicit expression state to a small allowlist of authored VTube Studio hotkeys: idle, listening, thinking, happy, laugh, surprised, confused, focused and concerned.
- Debounce repeated hotkeys; use state transitions, not a hotkey per token.
- Keep hotkey actions separate from continuous mouth/face parameter updates.
- Rate-limit parameter injection and coalesce stale updates.
- Cancel queued expression changes when the stream session ends or the owner disables the integration.

### Phase C — playback-clock lip sync

Drive mouth movement from the **actual audio playback clock**, not from generated text or TTS request completion. When speech is cancelled, clear pending mouth/viseme updates. Keep mouth, gaze, expression and body-motion layers independent so one system cannot overwrite the others.

For STAR's accepted chibi/Live2D character direction, authored expression hotkeys plus continuous playback-driven mouth movement are a practical first implementation. If a future avatar is 3D, evaluate a 3D-capable runtime rather than assuming VTube Studio supports every avatar format.

### Naturalness is a coordinated behavior, not a facial animation

The avatar director should consume explicit, evidence-backed states from the conversation/game director. It should not infer that the character is happy, scared or angry merely because a model generated those words. Useful behaviors include:
- listening posture and small acknowledgements;
- eye focus toward the current speaker or game event;
- short, varied reactions to verified events;
- laughter with an audio-aligned facial/body reaction;
- silence and idle animation when there is no useful contribution;
- immediate yield on an owner interrupt;
- no replay of a cancelled utterance.

A human-like presentation can be warm, expressive and socially fluent without claiming that the software has human feelings or lived experiences.

## 4. Full-duplex voice research: FastTurn and TurnBench

### FastTurn

The 2026 paper *FastTurn: Unifying Acoustic and Streaming Semantic Cues for Low-Latency and Robust Turn Detection* proposes combining streaming CTC/partial transcript signals with acoustic features and semantic context. Its motivation is directly relevant to a gaming stream: VAD is fast but cannot distinguish a breath or pause from a completed thought; waiting for full ASR can be too slow, especially with overlapping speech and game audio.

**STAR application:** preserve the current causal turn-policy evaluator as the acceptance layer, but prototype a small acoustic/partial-text signal adapter behind a feature flag. Evaluate with:
- normal sentence endings;
- mid-sentence pauses and hesitations;
- “yeah/uh-huh” backchannels;
- laughter, coughs and breathing;
- keyboard/controller sounds and game effects;
- overlapping viewer speech;
- direct questions and viewer-to-viewer replies;
- owner interruption and emergency stop.

Do not import a large multimodal model solely because a paper reports good benchmark results. First test whether a compact streaming signal model can improve the current policy on STAR's consented private rehearsal set.

### TurnBench

TurnBench separately scores end-of-turn and interruption detection on dual-channel conversations, reporting recall, false-positive rate and latency. Its current public leaderboard demonstrates that these objectives trade off against each other. STAR should keep its own held-out evaluation and use external benchmarks as an additional comparison, not as a substitute for owner-specific stream tests.

### STAR Social Brain

A livestream is multiparty, not a single-user voice call. The conversation director should maintain short-lived, session-local speaker labels only when the platform provides them. It should recognize:
- when a viewer addresses Star;
- when viewers are talking to each other;
- when a human moderator or co-host is already answering;
- when an acknowledgement is enough;
- when an interruption is genuine;
- when silence is better than another comment.

Do not create persistent voiceprints or identify viewers by voice. Do not retain raw audio/transcripts by default. Human-labeled evaluation must use consented rehearsal data and keep the holdout sealed.

## 5. Faster local inference without harming gameplay

### llama.cpp SPEED-Bench

The upstream SPEED-Bench client targets an already-running llama-server and reports prompt throughput, decode throughput, end-to-end latency and speculative-draft acceptance. Its documentation explicitly recommends matching benchmark client concurrency to the server's slot count (`--np`). Baseline and speculative runs must use identical prompt samples, output caps, benchmark category and concurrency.

**STAR experiment matrix**

Pin the model SHA-256, quantization, llama.cpp build, context length, GPU layers, Flash Attention setting, CPU thread count, slot count, draft model/configuration and warm-up procedure. Compare:
1. plain generation baseline;
2. prompt/prefix-cache warm and cold behavior;
3. speculative decoding configurations supported by the installed build;
4. one, two and four slots where the hardware and server permit;
5. context sizes representative of short chat, tool use and long coding tasks;
6. idle, game-only, OBS-only, game+voice, and full game+voice+avatar+OBS load.

Report prompt-processing throughput, decode throughput, first non-whitespace content, first audible playback, p50/p95 end-to-end duration, queue wait, VRAM/RAM, game frame-time p95/p99 and audio underruns. A higher tokens/second number is not a win if it increases first-audible latency or harms the game.

### Keep a two-timescale runtime

- **Fast lane:** audio continuity, speech stop/yield, game control, immediate hazard response and avatar playback timing.
- **Interactive lane:** short conversational reasoning, viewer response, visual event interpretation and tool selection.
- **Background lane:** research, long-form coding, skill consolidation, training experiments and heavy image/video generation.

The fast lane must never wait for background reasoning. Use measured resource admission, cancellation, deadlines and bounded queues. Never run disk I/O, hardware probes, model inference, tracing or Python callbacks inside audio/render/game hot paths.

### OpenTelemetry conventions

Adopt standard GenAI timing names where practical: client operation duration, server request duration, time-to-first-token, time-per-output-token, agent duration, inference-call count, tool-call count and tool execution duration. The current GenAI semantic-conventions documents are marked Development, so pin a version and avoid treating evolving attribute names as an immutable API.

Use bounded metadata by default. Prompt text, viewer chat, transcripts, audio, screenshots, credentials and model outputs should not enter telemetry unless the owner explicitly enables a private diagnostic capture with a retention policy.

## 6. Gamer Brain: learn games rather than merely issue inputs

Google DeepMind's SIMA 2 research demonstrates goal-directed interaction in diverse 3D worlds: perceive the screen, interpret a language goal, reason about a plan, execute keyboard/mouse actions and describe progress. Its research is a useful architecture reference, not a downloadable universal game controller for STAR.

STAR should split game intelligence into:

**Reactive controller**
- high-frequency input and observation;
- movement, camera, aiming, dodging and immediate hazards;
- strict action-rate and stale-observation limits;
- immediate cancellation on owner stop or game focus loss.

**Strategic planner**
- objective decomposition;
- map and mechanic discovery;
- route/strategy selection;
- task progress and recovery;
- selecting the next practice challenge.

**Skill library**
- store versioned skill procedures with prerequisites, game/version scope, evidence, failure modes and confidence;
- retrieve a skill only when the environment matches its preconditions;
- run a small verification action before applying a skill in a new game;
- record negative results and invalidate obsolete skills;
- test transfer on unseen maps/seeds/scenarios.

Use separate adapters for Roblox, desktop games and emulators. Do not assume one input API, game state model or anti-cheat policy works everywhere. Start with offline/sandbox environments and games where automation is allowed. Never automate competitive online play in ways that violate a game's terms or bypass anti-cheat.

### Gameplay evaluation

Measure objective completion, death/failure rate, time-to-objective, resource efficiency, unnecessary actions, recovery after mistakes, skill transfer to unseen levels, and frame/input responsiveness. Human review remains necessary for teamwork, sportsmanship and qualitative gameplay quality.

## 7. Creator Brain: build, playtest and repair games

The existing Roblox pipeline, Luau checkers, design system and Blender research should remain the primary foundation. Add an engine adapter only when it has a real inspect/build/run/test contract.

Recommended loop:

1. inspect project structure and engine/version;
2. extract requirements and acceptance tests;
3. plan scene/object/script ownership;
4. implement one bounded feature;
5. run static checks and type/lint tools;
6. launch a disposable test project/place;
7. capture structured engine diagnostics and screenshots;
8. playtest with deterministic scenarios or a permitted test agent;
9. repair the smallest verified defect;
10. rerun all relevant tests and inspect the final visual result.

Use separate roles for planner, builder, gameplay tester, visual reviewer and security reviewer. They must not share write access to the same files without an explicit ownership handoff. Model-generated code is untrusted until the engine, tests and sandbox verify it.

Future engine coverage:
- Roblox/Luau first;
- Blender asset and animation pipeline;
- Godot for an open, scriptable test environment;
- Unity after the same test/inspection contract is available.

## 8. Knowledge Brain and durable learning

Do not create another parallel memory database. Build on STAR's existing project-scoped lessons, checkpoints and skill-evolution gate.

Separate:
- semantic facts and concepts;
- episodic task/stream experiences;
- procedural skills;
- current working state;
- temporal facts that expire or change;
- world/environment models.

Every retained knowledge item should have provenance, timestamp, scope, confidence, version and a correction/supersession path. Retrieval should favor exact project/game/version matches and recent authoritative sources. A model-generated summary is a candidate, not ground truth.

Measure whether memory helps on future actions:
- success with memory vs no-memory controls;
- source verification;
- use of current rather than superseded facts;
- stale/deleted memory reuse;
- retrieval latency and token cost;
- procedural transfer to unseen tasks;
- forgetting when knowledge becomes obsolete.

General knowledge curriculum: math/statistics, science, programming, engineering, history, geography, languages, economics, psychology, art, music, media literacy, digital safety and practical everyday knowledge. Use authoritative references and held-out application tasks; do not call a larger vector database “higher intelligence” without outcome evidence.

## 9. Integration map: reuse existing candidate work

The current open development chain already contains candidate modules for:
- #1131: read-only llama.cpp metrics;
- #1132–#1134: causal tracing, trace adapters and span profiling;
- #1135: private stream rehearsal quality gates;
- #1136: temporal memory transfer/forgetting evaluation;
- #1137–#1139: rehearsal recording, bottleneck triage and practice continuity;
- #1140 and #1142: resource-aware admission and pressure governance;
- #1143: paired speed/quality evaluation;
- #1144–#1148: turn-taking, holdout integrity, clustered uncertainty and conservative coverage.

These are open draft PRs, not merged features. The current chain is intentionally stacked; do not create a competing scheduler, telemetry database, stream director, turn evaluator or memory store. Review the stack as one integration train, verify each base/head relationship, resolve shared-file conflicts, run full CI on the final candidate and only then consider a controlled merge sequence.

This PR is based on #1148's head and adds a narrow OBS adapter. It does not modify the preceding PRs or production `main`.

## 10. Acceptance plan

| Stage | Evidence required | Promotion rule |
|---|---|---|
| OBS parser (this PR) | Offline tests for schema, ranges, epochs, resets and rates | Merge only after CI and review |
| OBS local transport | Authenticated loopback test; read-only allowlist; no secret logs | Explicit opt-in; no remote bind |
| Stream epoch lifecycle | OBS restart, stream restart, disconnect/reconnect rehearsals | Missing/stale data is inconclusive |
| VTube Studio discovery | User-approved local plugin auth and revocation test | No token in logs/settings/repo |
| Avatar control | Expression allowlist, hotkey debounce, playback-clock lip sync | Disabled by default until owner acceptance |
| Full private rehearsal | OBS, audio, avatar, game and model telemetry on same monotonic clock | All configured gates pass |
| Voice naturalness | Consent-based held-out human scenarios | Lower false interruptions without unacceptable latency |
| Gamer skill | Unseen tasks/maps/seeds and verified outcomes | Demonstrated transfer, not self-report |
| Creator workflow | Real engine launch, test results, visual inspection and repair | No “done” without engine evidence |
| Speed optimization | Matched baseline/candidate mixed-load benchmarks | Faster audible response with quality and FPS preserved |

## 11. Limitations of this change

- The new module parses a supplied `GetStats` response; it does not connect to OBS.
- No OBS credentials, WebSocket client, VTube Studio token, microphone, TTS, playback, webcam, game input or broadcast control is added.
- No model weights, model routing, inference defaults, permissions or installer settings change.
- No Windows, OBS, VTube Studio, RTX 4060, Roblox, game or livestream test was performed in this environment.
- No speedup, naturalness improvement, intelligence gain, game mastery or production readiness is claimed.
- The parser's epoch correctness depends on the host creating a new opaque epoch at every OBS restart and stream start.
- The first sample is deliberately inconclusive for interval rates; a host must retain enough valid intervals to meet the rehearsal evaluator's minimum observation count.

## Research sources

1. OBS WebSocket project and security guidance: https://github.com/obsproject/obs-websocket
2. OBS WebSocket v5 protocol schema, including `GetStats` and `GetStreamStatus`: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.json
3. OBS `GetStats` request implementation and field descriptions: https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp
4. VTube Studio official API implementation and authentication: https://github.com/DenchiSoft/VTubeStudio
5. VTube Studio plugin permissions and events: https://github.com/DenchiSoft/VTubeStudio/tree/master/Events
6. VTube Studio plugin/API manual: https://github.com/DenchiSoft/VTubeStudio/wiki
7. Live2D Cubism SDK lip-sync manual: https://docs.live2d.com/en/cubism-sdk-manual/lipsync/
8. FastTurn (2026), *Unifying Acoustic and Streaming Semantic Cues for Low-Latency and Robust Turn Detection*: https://arxiv.org/abs/2604.01897
9. Sesame TurnBench: https://turnbench.sesame.com/
10. llama.cpp SPEED-Bench documentation: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
11. OpenTelemetry GenAI metric semantic conventions: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md
12. OpenTelemetry semantic conventions overview: https://opentelemetry.io/docs/concepts/semantic-conventions/
13. Google DeepMind SIMA 2 (13 November 2025): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
14. Voyager lifelong-learning game agent: https://github.com/MineDojo/Voyager
15. GameDevBench: https://github.com/GAIR-NLP/GameDevBench
