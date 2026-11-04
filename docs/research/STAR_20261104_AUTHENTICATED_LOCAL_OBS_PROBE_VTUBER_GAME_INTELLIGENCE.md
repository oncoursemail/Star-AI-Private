# STAR: authenticated OBS host observation, gaming VTuber and intelligence research
**Date:** 2026-11-04. **Implementation:** opt-in OBS v5 localhost read-only probe. **Status:** code plus offline tests; no real OBS media or live recording confirmed.

## Why this increment matters

The prior private Windows preflight checked physical GPU and process snapshots but could not speak to OBS's actual authenticated output state. The existing `stream_obs_readonly_evidence.py` validated **injected** WebSocket responses but did not connect to a real local OBS service. This patch closes that specific integration gap with `star/stream_obs_local_readonly_probe.py`. It is not a full live stream, performance speedup, or new game-winning policy.

**Allowed requests, fixed in source:** `GetStats`, `GetStreamStatus`, `GetRecordStatus`. All on `ws://127.0.0.1:<port>` via optional `websocket-client`, protocol v5 with password challenge/response and events disabled. No URL, hostname, request type, or media text can be supplied via the CLI. Server authentication is required even on localhost, and an observed active stream OR recording causes rejection. Request IDs are one-use random values; the existing gate rejects swapped/replayed status replies and counters that reset. Sensor timestamps use one host monotonic clock. The client serializes **only a privacy-minimal report**, not credentials, request IDs, stream URLs, active window titles, webcam frames or audio.

**No automatic network action:** absent `--observe`, command exits with `explicit_observe_flag_required`. Even when observing, password must be injected by the *trusted local operator/host* as `STAR_OBS_WEBSOCKET_PASSWORD`. This is not a credential that belongs in an LLM prompt, Discord message, GitHub action, or command-line argument. No broadcast or recording can be started/stopped by this module; every result has `authorizes_broadcast=false` and `authorizes_recording=false`.

### Local usage on an owner-controlled Windows host

1. In OBS **Tools → WebSocket Server Settings**, enable password authentication and ensure connection is restricted to localhost. Do not expose the WebSocket port publicly.
2. Install the optional Python dependency (`pip install websocket-client`) in STAR's isolated Python environment. No package was installed as part of this PR.
3. Set `STAR_OBS_WEBSOCKET_PASSWORD` securely **outside** the assistant prompt/history (e.g. an owner-only environment/secret store). On the relevant host, run `python -m star.stream_obs_local_readonly_probe --observe --samples 3`.
4. Interpret `candidate` narrowly: three authenticated snapshots show both outputs inactive and OBS counters increasing. It does **not** show continuous nonbroadcast safety between samples, an OBS recording, audible TTS, correct mouth animation, actual game input, model intelligence, or permission to go live.
5. For private recording rehearsal later, implement a **separate authorized recording evidence mode**, with an independent record start/stop receipt and strict `GetStreamStatus.outputActive=false` throughout. Do *not* reuse this inactive-recording gate to claim a recording was made.

### Quality and security checks to retain

- Missing password, unauthenticated OBS server, an active stream/recording, wrong request ID, protocol mismatch, malformed/missing counter, duplicate/reordered timestamps and expired transport evidence must fail closed.
- Unexpected response fields are never logged. Unauthorized viewers and models cannot call the client directly or supply the trusted `owner_approved` flag.
- A password response does not prove continuous stream inactivity; local obs-websocket may be used by other processes. Network/OS isolation, process owner checks, and continuous output-state events are production prerequisites.
- A compromised local OBS process or monkeypatched Python dependencies can forge plausible telemetry; no cryptographic authenticity guarantee is claimed.

## Measured starting point, 2026-11-04

PR #970's *actual* Windows Main read-only sampling recorded **871 MiB** minimum GPU-free memory over a five-sample window on an 8 GiB RTX 3060 Ti and no pinned game, OBS or VTuber avatar process. Inference activity and GPU memory varied greatly across snapshots. The correct next experiment is a controlled, local OBS+avatar+game+voice test with a stable process/VRAM baseline, not launching more heavy models by default. This patch has **not** performed the full rehearsal.

## Higher-priority next upgrades (ordered by enabling evidence)

### 1. Real nonbroadcast VTuber rehearsal (integration, not simulation)
- Private-only owner-authorized Windows OBS recording with recording-state receipts, stream-active continuously blocked, process/scene/waveform evidence and bounded stop/cleanup.
- Source-game capture evidence includes independent frame timestamps and input → game-state change, not UI button presses alone. Existing STAR game-window and input-permit components should supply this.
- Audio-output clock and speaker-loopback confirmation (what was *heard*, not just TTS bytes generated); avatar expression/lip motion correlated to audible PCM; OBS render/encoding dropped frames measured at interval.
- Gate the entire run on P95/P99 game-frame time, speech-first-audible latency, worst PCM gaps, avatar frame gaps, skipped OBS frames and **minimum** VRAM across a 10–20-minute run. Require a rehearsal report with no stream authorization.

### 2. More humanlike *behavior*, still visibly an AI
Use separate, resource-bounded systems for attention, planning, dialogue and expression. Track recent observable game events and conversation turns; speak selectively when commentary helps, stay silent during combat, distinguish genuine interruptions from short acknowledgments, and interrupt speech at actual playout boundaries. Convey curiosity, surprise and consistent preferences, but never falsely claim human experiences, relationships, feelings or consciousness. Do not use deceptive viewer engagement: make AI identity obvious.

Test naturally timed voice turns on counterbalanced cases: questions, game wins/losses, social interruptions, incidental sound, co-op coordination and critical silence. The already-present `stream_social_turn_benchmark` should be fed independently checked, **audibly observed** trials rather than synthetic claims. Quantify excessive speech, missed interruptions, false interruptions, grounded factuality and avatar/PCM timing. No single "human score" proves general capability.

### 3. Faster correct answers and decisions on 8 GB GPUs
Use a two-tier responsive path: tiny/CPU task classifier, event-driven reflexes and cached game facts for under-frame decisions; large reasoning only when FPS/VRAM permits or between matches. The ability to answer quickly **and correctly** under a game+OBS+voice load matters more than token/s on an idle GPU. Benchmark four profiles independently (idle, game only, OBS/avatar only, both), with process/model/worker identities pinned to prevent cache contamination (see preceding STAR worker revisions).

Compare same model/prompt/seed/hardware with and without llama.cpp prompt caching, quantization, speculation, flash attention and CPU/GPU offload. Use cold/warm runs, quality pass rate, TTFB, time-to-first-**audible** audio, P95 end-to-end time and measured GPU peak. Do not equate reported speculative decoding speedups with universal speedups; draft acceptance and VRAM budgets differ by task.

Kyutai Pocket TTS's October 2026 CPU-oriented 18M/7M/2M model family warrants a quality×latency comparison against STAR's existing TTS: word error/consistency, phrase prosody, stream chunk delay and CPU heat under simultaneous game load. Model size does not guarantee desirable personality or natural voice.

### 4. Verified autonomous game-playing and game creation
- Build a legal, game-specific adapter for **authorized** local/test games. Make observations stateful and timestamped; maintain a belief about current objective, HP, enemy, cooldowns, navigation and action latency. No input to unrelated apps or online competitive anti-cheat bypass.
- Hierarchical gameplay: reactive controller for movement/dodging; tactical planner for fights and goals; episodic coach for skill practice. Train on a replay corpus with *outcome receipts*, then hold out levels/maps/seeds. Promote a policy only after showing improvement on blind success rate, action efficiency and P95 reaction deadline.
- Roblox Studio's MCP integration can be used to inspect Luau/scripts and simulate playtests. Verify Luau with analyzer/linter and actual multiplayer Studio sessions, frame screenshots, inventory/gameplay state, input feedback and a checkpoint/rollback before any change to a user's production game.
- Practice curriculum: navigation, platforming, camera control, hitbox/movement constraints, boss timing, cooperative communication, puzzle deduction; progress difficulty only if real successes persist across unseen maps.

### 5. General knowledge and autonomy
Create trusted, dated retrieval for game manuals, Roblox API docs, coding repositories, local project knowledge and safety rules; keep a source version, observed timestamp and confidence with every remembered claim. Separate **observation**, **hypothesis** and **verified fact**. Long-term self-improvement should propose independent tests and reversible patches, not autonomously fine-tune its production brain from unreviewed stream chat. Run research/training during low GPU pressure or overnight; preserve bounded budgets and resource priorities while interactive.

## Sources reviewed (primary references)

- OBS Project, **obs-websocket v5 protocol**, live protocol handshake and only-read request types: https://github.com/obsproject/obs-websocket/blob/master/docs/docs/partials/introduction.md
- OBS Project, **obs-websocket official repository**, included with OBS 28+: https://github.com/obsproject/obs-websocket
- Kyutai, **Pocket TTS** official code, updated October 2026 small models: https://github.com/kyutai-labs/pocket-tts
- ggml-org, **llama.cpp SPEED-Bench** benchmark methodology: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- Roblox, **Studio MCP server** (live in Studio, game testing): https://create.roblox.com/docs/studio/mcp
- LiveKit, **turn-taking and interruption configuration**: https://github.com/livekit/agents-js/blob/main/agents/src/voice/turn_config/interruption.ts

## Limits and acceptance

**Implemented now:** localhost-only authenticated OBS v5 status bridge, hardcoded read-only methods, serial bounded observations, strict replay/response validation, privacy-preserving result, tests. **Not implemented now:** device-level capture, starting OBS, local recording, guaranteed nonbroadcast continuity, model optimization/learning, actual AI gaming controls, speech generation, viewer chat service, real streaming performance. Keep draft PR, opt-in feature, independent CI and real Windows integration before enabling further behavior.
