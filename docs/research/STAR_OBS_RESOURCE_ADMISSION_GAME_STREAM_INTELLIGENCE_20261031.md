# STAR AI — GPU-safe VTuber admission, embodied gaming, general knowledge and game-building intelligence

**Research and engineering snapshot:** 2026-10-31.  
**Status:** Proposed architecture plus a working, **OFF-by-default, advice-only** StreamAdmissionGate and deterministic unit tests. No live OBS/game benchmark or autonomous model improvement was performed. This document deliberately separates published external findings, engineering hypotheses, and demonstrated STAR behavior.

## 1. The real constraint on an 8 GB gaming PC

STAR is attempting five competing tasks on the same machine: game rendering and input, streaming capture/encoding, realtime perception, conversational reasoning, and speech/avatar output. A sixth group—research, video generation, model training, and asset baking—should not receive the same resource priority while live.

An unloaded inference benchmark misses GPU contention, OBS frame loss, audio-start delay, and action staleness. Replacing Python with Rust will not repair an overloaded GPU or improve a neural model's reasoning. The initial optimization target is a **fast, correct end-to-end interactive loop** rather than peak isolated token throughput.

### New implementation

`star/obs_stats_window.py` is a pure in-process **OBS WebSocket v5 GetStats counter adapter**. A trusted, authenticated loopback Windows host feeds only four frame counters: `renderSkippedFrames`, `renderTotalFrames`, `outputSkippedFrames`, and `outputTotalFrames`. The adapter takes two strictly ordered host-timestamped snapshots and converts **deltas** to bounded render/output skip percentages. It re-baselines on OBS counter reset or a long gap, rejects malformed/unverified values, and never stores arbitrary GetStats fields. The `outputSkippedFrames` signal is a proxy for output/encoding pressure, **not** an isolated hardware encoder diagnostic. Official [obs-websocket GetStats implementation](https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp) and [v5 protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md) define the fields. The host must separately protect the websocket password and check actual OBS logs/recordings.

`star/stream_admission.py` extends the existing stateless `star/stream_budget.py` policy:

- An authorized Windows host supplies strictly validated monotonic timestamps, existing `StreamTelemetry`, and **windowed** OBS render/encode lag percentages. The module does not poll OBS itself.
- Under **live** operation, speech and gameplay are recommended as high priority; research, training, and rendering are deferred. Bounded vision can be advised up to the existing 1 Hz stream policy only when there is measured headroom.
- A single resource/OBS overload sample latches background deferral immediately. Three or more *spaced*, healthy samples and a minimum 1.5-second healthy dwell are required to recover. This limits repeated heavy-job start/stop thrashing.
- Missing, stale, unverifiable, out-of-order, or backwards-clock telemetry cannot clear overload or grant background admission.
- Disabled by default. `AdmissionAdvice.authorizes_execution` is always false; the host independently checks owner permissions, game rules, and actual device capacity. No media or personal data is stored.

These initial thresholds (less than 1536 MiB free VRAM, under 45 game FPS, over 350 ms speech backlog, or over 1% OBS render/encode lag) are **conservative candidate policies**, not empirically optimal settings for Star's hardware. OBS measurements should be collected as rolling rates over a documented interval, not cumulative lifetime counts. Tune and preregister thresholds *after* controlled Windows tests.

OBS itself explains that uncapped GPU-heavy games can starve OBS composition. See OBS's [Encoding Performance Troubleshooting](https://obsproject.com/kb/encoding-performance-troubleshooting/). STAR's host should also monitor *rendering lag and encoding lag separately*, not just displayed game FPS.

### Required validation

Compare baseline with admission OFF versus ON, using the same game scene and 10+ minute local OBS recordings. Collect OBS render/encode frame-loss rates, game frame-time p50/p95/p99, voice playback-start p50/p95, frame-capture-to-action p95, VRAM minimum, and total successful interactive tasks. Include deliberate 1–3 second load spikes, telemetry dropout, device restart, host clock anomalies, and cancellation tests. Success means fewer dropped frames **without** lowering verified gaming success or increasing voice latency. Record CPU load and scheduler contention; do not declare a win from synthetic advice tests alone.

## 2. An actual learning loop for playing games

STAR already has separate pieces: `game_action_gate.py` (symbolic action permits and host release), `game_action_freshness.py` (reject late/duplicate scenes), `game_skill_gate.py` (matched unseen-trial score), `stream_episode_journal.py` (attested episodic memory), and a stage/speech layer. The missing key is a **trusted, instrumented host** connecting observation → prediction → action → environment result → teacher feedback → replay → unseen challenge.

Target architecture:

1. **Realtime student:** a compact vision/state model proposes a bounded symbolic action at a fixed decision budget; expensive teacher models are never on the critical input path.
2. **Host controller:** focus, allowlisted action map, release watchdog, multiplayer/game terms, human override and fresh observation are verified *immediately before* dispatch; signed or independently verified result evidence must come from the game harness, not the model's textual description.
3. **Teacher between sessions:** inspect failed attempts and telemetry; propose one strategy change at a time. Prefer safer demonstrations, procedural variations, and short failure-specific practice, not recursive unverified prompt-writing.
4. **Skill curriculum:** retain separate practice seeds and *secret* holdouts. Test multiple unseen maps and per-scenario p95 latency; refuse promotion if one scenario regresses even when aggregate success improves.
5. **Distillation only after proof:** save reviewed traces or short skills; consider training compact models off-stream when many independently verified examples demonstrate transferable gains. Never call an increased memory count an intelligence gain.

Benchmark on continuously running environments; pause-on-inference results should never be presented as realtime gaming mastery. For STAR, a successful milestone is achieving objective completion on unseen levels with stable response delay, not merely describing game rules.

## 3. Humanlike streaming: conversational realism, not fabricated humanity

The credible target is an identifiable **AI entertainer** with a consistent personality, expressive body, situated attention and truthful continuity—not pretending to have a human childhood or hidden real-life experiences.

Develop along four coupled clocks:

- **Conversation clock:** detect speech activity, complete turns and legitimate owner interruption. A quiet acknowledgement should not cause cascading cancellations. Unknown guest audio should not impersonate an owner. Use privacy-preserving local VAD/turn detection; `stream_turntaking.py` already has an advice gate.
- **Game clock:** suppress long monologues in danger, combat or high-input scenes. Short, context-specific reactions to verified wins/near misses beat repetitive catchphrases. Give Star intentional quiet periods, including rest and concentration.
- **Audio clock:** select a measured local voice path; stream speech chunks; track actual playback start/finish, not TTS queue enqueue. Lip sync must be driven by **heard** phoneme/audio cues, with cooperative interruption and rig reset, not predicted dialogue.
- **Motion clock:** coordinate eyes, blinks, gaze, shoulders, mouth, emotes and physically plausible twin-tail secondary motion. Keep soft expression transitions and reduced-motion support; test actual OBS capture at 30/60 FPS and reject clipping, jitter and late expressions.

Kyutai's [Pocket TTS documentation](https://kyutai-labs.github.io/pocket-tts/) describes small CPU-oriented models, streaming output, and October 2026 English small-model variants. This is **a candidate** to preserve the game GPU; it must be compared blind with Star's existing voice for articulation, charm, laughter, long-utterance stability, interrupt turnaround and CPU interference. The official [Kyutai technical report, 2026-01-13](https://kyutai.org/pocket-tts-technical-report/), covers the model's basic design. No voice model is replaced by this PR.

Star can build a personal canon of **genuine** verified gaming sessions, projects, preferences and fictional mascot lore; separate fictional character background from objective claims, and never improvise viewer identities or personal histories as facts. Memory should be revocable, scope-limited, owner-approved for public speech, and never feed raw unmoderated chat into high-priority instructions.

## 4. Faster inference without model-quality regressions

Use controlled A/B measurements on the *actual* game + OBS load, not internet t/s numbers. Start with:

1. **Profile:** instrument end-to-end time to first heard audio, game decision age, prompt processing, generation, retrieval and TTS. Distinguish GPU memory residency from token decoding and from host task scheduling.
2. **Short fast path:** use a small realtime model for short game decisions, turn selection and expression cues; reserve a stronger reasoning model for offline teacher evaluations or complex code plans. Never race multiple heavy models if they destabilize stream FPS.
3. **Cache and memory:** prepack stable project docs and proven skills; bound context and use verified, source-anchored retrieval. Bench prompt reuse with clean session isolation. Reuse is disallowed until synthetic cross-context tests and long-context eviction checks pass.
4. **Batching:** llama.cpp documents continuous batching, prompt caching, slot metrics, and speculative decoding in its [server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Bench toggles independently using fixed test prompts and output quality checks; an auxiliary speculative model can consume too much VRAM and be slower on 8 GB.
5. **CPU/Rust:** port *measured* per-frame hotspots (capture transforms, feature extraction, geometry, lightweight VAD) with a stable FFI only after profiling. Improve Python task cancellation, data copy count, and queue backpressure first.

A community [Strata benchmark dated 2026-10-06](https://github.com/Niko1221/Strata/blob/main/bench/results/2026-10-06-llamacpp-0.6.0/README.md) reports substantial gains for its particular MoE models on tested GPUs, but its 3060 configurations and memory footprints do **not** establish wins for Star's RTX 4060 8 GB. Replicate under matched quantization, prompt lengths, VRAM budget, accuracy, and game FPS before considering a runtime change.

## 5. Game creation: gameplay validity plus visual craft

Roblox's [Studio testing modes](https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/testing-modes.md) document up to eight simulated clients, device emulation, and programmatic StudioTestService tests. The newer [Network Simulator](https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/network-simulator.md) permits reproduction of latency, jitter, and packet loss in Studio playtests.

Teach STAR an explicit **build → inspect → simulate → repair → test again** loop:

- Luau static checks, API signatures, permission boundaries, Rojo/project diffs and unit tests.
- Geometric integrity: wall joins, collision clearance, asset origins, hand grips, UV/textures, lighting continuity, navigation and level bounds.
- Multi-client authority tests: joins/leaves, replication, latency, persistence, respawns, unauthorized client requests and UI input across devices.
- Objective visual quality: multiple camera captures, side-by-side reference comparisons, motion video of animation and VFX, semantic inspection of outliers, human taste review and a non-AI-looking polish rubric.
- Test game **fun** separately: real/consenting playtesters and measurable replayability. A clean build does not automatically mean a good game.

A structural claim of perfection should require saved reproducible proof, not the agent checking its own output once.

## 6. General intelligence, verified knowledge and self-directed improvement

Keep four separately tagged knowledge planes: (a) source-backed facts with freshness/attribution; (b) reviewed skill procedures with reproducible tasks; (c) provisional hypotheses; and (d) fictional personality lore. A retrieval candidate must include provenance and scope/age review; context packing is token/serialization-budget aware, and longer context alone is not more intelligence.

Give the internal offline-first **Star Core Forge** an AI-native experiment ledger: immutable baseline, change intent, resource budget, preregistered unseen tasks, verification artifact hash, metrics, promotion verdict and rollback. GitHub remains optional publication/export, not required for self-improvement.

Suggested distinct evaluations: new factual questions with citations, coding on previously unseen repositories, visual UI recreation from reference without leaked source, animation timing/grip checks, cross-game transfer tasks, spoken interruption tests, and owner-approved Windows task execution. Reject self-scored gains and protect sealed holdouts from the teacher.

## 7. Deployment gates and next experiments

**Gate A (already implemented offline):** deterministic unit tests for overload trips, slow recovery, strict opt-in, stale clocks, bounded anonymous counters and non-authorization. Also tested real-shape synthetic OBS GetStats counter windows for skips, resets, low frame counts, malicious fields and the resulting deferral signal. The combined focused local suite passed 33 tests; synthetic 8 GB values are fixtures, not physical measurements.

**Gate B (next):** connect an authenticated local OBS WebSocket v5 GetStats *read-only* collector to ObsStatsWindow, and host game/VRAM/audio telemetry to StreamAdmissionGate with dry-run decisions only; benchmark a recording while game, OBS, streaming TTS and vision run concurrently. Verify lost-sample fail-closed behavior and absence of scheduling oscillation.

**Gate C:** gate background training/research through the trusted Windows job scheduler only after dry-run evidence. Do not let the advisory class directly control processes or permissions.

**Gate D:** game harness rehearsal using actual allowed games and measured action ages. Gate teacher strategy changes on independent unseen results. Connect host-verified memories to actual (not merely queued) speech.

**Gate E:** publish short local recordings for blinded quality review (with viewer privacy/consent). Compare Star's previous and new voice/rig, interruptions and attentional timing. Retain rollback and reduced-motion controls.

**Numerical SLOs are provisional:** start with p95 game action observation age under 250 ms for games able to support it, p95 TTS playback start within 600 ms for brief turns, 0% severe stale-action execution, and no new >1% OBS frame-loss windows caused by STAR background jobs. Adjust per actual game and hardware before claiming success.

### Current demonstrated work vs not done

**Committed code:** isolated, opt-in and deterministic OBS-aware admission advisor; regression tests. **Not yet done:** Windows host wiring, actual resource scheduling, dynamic GPU model switching, local TTS integration, playing games, recording OBS output, autonomously retraining models, changing the production voice, or demonstrating superior intelligence. The host must stay the authority for external actions and persistent changes.