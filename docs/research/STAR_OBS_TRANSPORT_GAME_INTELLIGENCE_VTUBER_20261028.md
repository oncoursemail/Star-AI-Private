# Star AI: Transport-safe streaming, game intelligence, and autonomous VTuber research
**Research date:** 2026-10-28 (America/Chicago)
**Implementation in this change:** `star/stream_network_qos_gate.py`, with offline test coverage.
**Deployment status:** No OBS, Windows, Roblox, microphone, stream, viewer or account connection was started.

## Why this increment matters

A local AI voice upgrade is *not* a win when it causes Star's outgoing stream to skip encoded/delivered frames. Existing Star benchmarks measure time to first audible speech, game 1%-low FPS, peak GPU use, and OBS **GetStats** render/output thread frame skips. The new component supplies a separate, strict and opt-in **GetStreamStatus** stream-output transport gate.

The sources must not be confused:

- `GetStats`: `renderTotalFrames`, `renderSkippedFrames`, `outputTotalFrames`, `outputSkippedFrames`. These measure different OBS processing stages.
- `GetStreamStatus`: `outputActive`, `outputReconnecting`, `outputDuration`, `outputCongestion`, `outputBytes`, `outputSkippedFrames`, `outputTotalFrames`. These are output-specific stream counters. The last two are **not TCP/UDP packet-loss measurements**. `outputCongestion` has no portable documented normalization; it is preserved only as bounded diagnostic metadata.
- `outputTimecode` is not retained and private OBS fields (addresses, credentials, stream keys, arbitrary host payloads) are never serialized into the report.
- OBS can return null congestion when disconnected in some versions; this gate treats unknown/invalid values as unusable evidence, not zero congestion.
- A stream can reconnect between the two snapshots. An authorized capture host must observe and attest that transition; offline data cannot prove the capture host is truthful.

Official references:
- OBS WebSocket 5.x protocol: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md
- OBS WebSocket repository and password recommendation: https://github.com/obsproject/obs-websocket
- Historic null-congestion compatibility report (2023): https://github.com/obsproject/obs-websocket/issues/1176

## Implemented network-output acceptance gate

`ObsStreamStatus` projects the seven expected fields into strict bounded values; it rejects invalid types, missing counters, booleans disguised as integers, NaN, infinity, counters that exceed the exact JSON-integer range, and skipped frames greater than totals. Unknown OBS metadata is not retained.

`ObsTransportWindow` ensures:
1. The game/version, experiment pair, OBS process session, and baseline/candidate variant are explicit and bounded.
2. Snapshots bracket a 2-second to 10-minute monotonic-clock interval and counters never move backwards.
3. There are at least 120 stream output frames, a positive byte delta, and at least 80% active-output duration coverage.
4. A reconnect/stop is never considered evidence of a healthy stream; `reconnect_observed` must come from the host's full-interval monitoring.

`compare_realtime_obs_transport` **composes** the prior sound/game/OBS rendering gate, then matches every `GetStreamStatus` window to the same game, pair, OBS process and capture interval. Any unpaired, mismatched or missing evidence is inconclusive, not a win. Baseline stream damage makes an experiment invalid; candidate stream damage vetoes the improvement.

Default provisional policy: candidate skipped-stream-output frames <=0.5% aggregated, no >0.2 percentage-point increase over matched baseline, and no single candidate window >1.0%. These are **owner-tunable conservative engineering limits**, not empirically validated perceptual thresholds or proof of improved streaming quality. Even an eligible result means **manual supervised pilot only**.

Offline CLI:

```bash
python -m star.stream_network_qos_gate paired_realtime.jsonl paired_getstats.jsonl paired_getstreamstatus.jsonl --gpu-budget-mib 6656
```

Three JSONL files are supplied by a separate trusted observer. Only bounded timing, counter, opaque run IDs and game/version IDs are permitted. It cannot contact OBS or select an inference mode. `GetStreamStatus` windows must be continuous observations from a single process; do not stitch counters across reconnects, OBS restarts, stream stopping, or scene transitions.

## Highest-impact next steps, in order

### 1. Real Windows/OBS/Roblox acceptance: close the measurement gap

Connect the authorized OBS WebSocket client on localhost with authentication, not a remotely exposed unauthenticated WebSocket. Start with **read-only** `GetStats` and `GetStreamStatus` snapshots plus host-monotonic timestamps. Assign each OBS process a random session ID and detect restarts, disconnections, and stream state transitions. Pre-register each A/B configuration, game build/version, scene, resolution, graphics settings, Roblox FPS cap, audio output and OBS encoding settings; alternate conditions to reduce warm-up/order bias. Keep the observer independent of Star's AI-generated performance claims. Never log stream keys or chat in benchmark metadata.

Measure paired:
- TTFA from request through **physical audible PCM position**, p50/p95 response latency, interruptions, percentage of dropped/late spoken turns and speech naturalness reviewed by people.
- Real Roblox frametimes, 1%-low FPS, frame pacing, input-to-action latency, controller health and crash/recovery rates.
- OBS rendering skips, output-thread skips, stream-output skips and reconnects, visual/audio sync, encoder load and output duration.
- GPU peak/headroom, VRAM thrash, RAM/CPU utilization, host thermals and simultaneous Discord/OBS/game resource pressure.

Do not auto-switch to a supposedly faster model unless a trusted test gate approves a specific supervised deployment plan.

### 2. Higher useful intelligence *per second* on 8 GB GPU machines

Keep interactive actions deterministic and very cheap; send heavyweight reasoning to slower paths only when needed. Use three tiers:
- **Reflex:** short local movement, avatar idle animation, interrupt/cancel, chat focus. No large LLM call in the render/audio loop.
- **Tactical:** HUD/VLM understanding, recent memory, mechanics hypothesis, low-cost tool planning; cache scene object identities and prefetched project context.
- **Strategic:** long research, Star Core Forge experiments, game creation, long-horizon planning; pause under GPU/OBS pressure and resume after stream.

Compare same prompts and tasks under plain llama.cpp, prefix/prompt caching, continuous batching and *candidate* speculative decoding. Speculation may be slower on CPU-bound devices or VRAM-constrained draft+target combinations; report prefill speed, decode speed, first-token delay, tool accuracy, GPU headroom, entire response latency and STREAM health together. Do not promote by token/s alone.

Official performance guide (SPEED-Bench): https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
Official llama.cpp server: https://github.com/ggml-org/llama.cpp/tree/master/tools/server

### 3. Teach Star to play games rather than narrate screenshots

A playable self-learning loop needs **independent outcomes**, not the agent self-grading its own descriptions:
1. *Observe*: game screenshots, HUD symbols, map markers, control effects, and object states with timestamps.
2. *Predict*: write a testable prediction (e.g., a jump duration, gravity, cooldown, range, respawn checkpoint).
3. *Act* (only in authorized, permitted games/private test environments): probe one mechanic at a time within a constrained action budget.
4. *Verify*: separate observer reads game state, victory conditions, death/respawn flags and exact resulting positions.
5. *Learn*: store the tested skill as a game/version-scoped recipe with evidence, failure modes, confidence, and retrieval provenance.
6. *Practice*: automate curriculum from noob-level actions to multi-step sequences; use held-out levels/seeds and compare success rates, time-to-goal, efficiency and safety failures.
7. *Transfer*: compare unseen mechanics in another permitted game rather than relying on memorized HUD images.

Roblox **OpenGameEval** (2026-10-01) offers executable Studio benchmarks for scene changes and script tasks; its findings support inspecting affected objects before edits. The May 28, 2026 Roblox Studio update describes VirtualInput, multiplayer StudioTestService and device simulation, providing legitimate building blocks for private playtests. Track *first-attempt*, *repeatable pass rate*, *time budget* and *unseen-project success*, and count repeated attempts honestly.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService

### 4. Raise autonomous game-building quality

Before editing any Roblox game, inspect architecture, assets, scripts and scene structure. Build spatial and semantic specifications: required props, scale, texture/color consistency, collision, nav routes, checkpoints, lighting and performance budgets. After each edit, run scene integrity and actual Studio simulated-input tests, then visually compare rendered frames against design constraints. Route failures into targeted repair proposals and rerun independent tests. Ensure changes do not cause unintended side effects elsewhere in the world.

**Human quality is more than valid Luau.** Evaluate art direction, readability, gameplay fun, accessibility, multiplayer desync, respawn/leave cases, mobile input and performance. Human review remains essential for aesthetic judgment. Avoid producing interchangeable cookie-cutter games from repeated prompts.

### 5. Natural, expressive, grounded streaming personality

Star should have coherent persona lore and an expressive, entertaining character without claiming she is a biological human or inventing lived memories. Create evidence-grounded episodes of *actual games she played*, projects she completed, chats she consentingly retains and mistakes she learned from. Distinguish fictional roleplay from observed experiences.

Make reactions event-driven: hold silence during critical jumps; let her laugh when a real event happens, with a separately rendered laughter event rather than a repeated canned clip; add amused, disappointed, curious, excited and concentrative expression trajectories, eye gaze, blinks, mouth shape and twin-tail/ribbon physics. Drive lip motion from the authenticated audible playout clock, not TTS-generated text timestamps. Avoid blocking her visual attention or control loops during voice generation.

**Turn-taking:** LiveKit's locally runnable `v1-mini` end-of-turn detection is a candidate; compare with simple VAD and measure false interruptions, stalled replies, and conversational rhythm on actual dialogue. **Avatar:** VTube Studio's documented custom parameter injection can animate facial/expression channels; map parameters to physically plausible ranges and gracefully return to neutral after interruptions. Star's cat/puppy modes should be optional persona presets, not hardcoded chat interruptions.

Sources:
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

### 6. General knowledge and credible autonomous self-improvement

Design a source-backed knowledge store with *origin, retrieval time, topic/version, licensing, confidence, contradiction record, validation trace, freshness/expiry,* and a visible difference between a retrieved fact and a model interpretation. Keep raw evidence separate from Star's predictions, avoid contamination from tests and her own outputs, and ask her to seek stronger references where uncertainty matters. Regularly generate challenge tasks across code, math, physics, art, design, human communication, music and game systems, but accept progress only when held-out verified tasks improve. Star Core Forge should record hypotheses, experiment manifests, evaluation receipts, reversible diffs, hardware budget impact and rollback points—GitHub remains an optional publication and review interface, not the prerequisite for her own improvement.

Continuous self-improvement does **not** establish consciousness, infinite intelligence, or superiority to every AI. Measure independent generalization and real utility. Keep routine operations autonomous, but gate irreversible/external actions, purchases and account security under owner policy.

## Acceptance / limitations

- Implemented here: a **bounded, offline, fail-closed paired transport-output QoS evaluator** and tests. No neural model was trained and no inference engine was accelerated.
- Tests use synthetic OBS and game telemetry; they cannot guarantee live broadcast quality, network packet loss, end-user playback, voice expressiveness or true humanlike interaction.
- A trusted Windows observer and multiple matched real experiments are prerequisites before any claimed live speed/quality improvement.
- Prefer preserving Star's actual game FPS, OBS output quality, user privacy and source-backed evidence over publishing an impressive but unsupported single number.
