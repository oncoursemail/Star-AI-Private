# STAR AI — OBS v5 read-only evidence, fast gaming, and humanlike VTuber engineering

**Research and implementation date:** 2026-11-01
**Status:** One tested, disabled-by-default *offline observation* adapter. The rest of the sections contain design proposals and explicit acceptance tests, NOT deployed AI capabilities.
**Change:** `star/stream_obs_readonly_evidence.py` + `tests/test_stream_obs_readonly_evidence.py`.
**Dependency stack:** This branch targets the unmerged GPU-identity parent PR #882, which builds on #881/#878/#870 and others. Do not merge straight to `main` without reconciling the stacked PRs.

## 1. Why OBS evidence was a missing piece

STAR's rehearsal recorder already has independent numeric events for game scene/action, audio, avatar frame, GPU peak, actual frame presentation, and `obs_stats_sampled`. Separately, STAR already has `obs_readonly_benchmark_host.py`, `obs_stats_window.py`, and `obs_stream_event_witness.py` for read-only OBS sampling and transport-continuity checks in a **different paired benchmark path**. This addition does **not** replace those collectors. It provides the missing strict **raw v5 triplet → rehearsal-recorder** adapter, with an explicit `GetRecordStatus` check. Arbitrary integers labeled as skipped/total frames are not sufficient evidence of a real OBS measurement. A caller could mix OBS *render-thread* frames with *output-thread* frames, replay a reset counter, accidentally connect to a broadcasting session, or use a stale OBS response.

OBS's **official obs-websocket v5** `GetStats` response has **four different counters**:
- `renderSkippedFrames`, `renderTotalFrames`: OBS render thread.
- `outputSkippedFrames`, `outputTotalFrames`: OBS output/encoder thread.

They are *not* interchangeable. Neither OBS counter is the actual game's presented FPS, and the output counters can be zero during a nonbroadcast rehearsal. The requested stream and recording statuses are separate read-only calls. Official source: [OBS generated protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md) and [OBS GetStats implementation](https://github.com/obsproject/obs-websocket/blob/master/src/requesthandler/RequestHandler_General.cpp).

OBS's `RequestResponse` uses opcode 7 and includes a mirrored `requestType`, `requestId`, and `requestStatus` with `result` and numeric `code`. A success code is 100. Source: [OBS protocol introduction](https://github.com/obsproject/obs-websocket/blob/master/docs/docs/partials/introduction.md). The installed OBS WebSocket server normally requires password authentication; keep it bound to loopback and password-protected. Source: [OBS WebSocket README](https://github.com/obsproject/obs-websocket).

### Implemented in this change

`ObsReadOnlyEvidenceGate`:
1. Is **OFF until explicitly owner-approved** and rejects input unless a *trusted host integration* marks responses independently verified; a booleans-only API is not cryptographic attestation.
2. Parses **only three read-only v5 responses** per sample: `GetStats`, `GetStreamStatus`, `GetRecordStatus`. Validates opcode, success, request-type, exact opaque request-ID correlation, distinct request IDs, JSON numeric counter types, and all required fields. Rejects unrecognized, incomplete, failed, replayed, stale, non-monotonic and invalid-count responses.
3. Requires `outputActive is False` in **both** stream and record status, even for paused recording. This establishes only the output's status **at the sampled time**. It cannot prove the absence of an extremely short broadcast between polls.
4. Requires a bounded time span across the three responses, non-overlapping and non-stale response timestamps, bounded inter-sample gaps, monotonic OBS counters, no counter resets, and plausible skip deltas.
5. Maintains aggregate render- and output-thread skipped-frame fractions **separately**. No request IDs, raw JSON, credentials, OBS scene names, program audio, screenshots, chats, or user identities appear in public reports.
6. Can write the validated **render** counters into the existing `StreamRehearsalRecorder` using the latest host receipt time. It advances the gate only after the downstream recorder accepts the event; a failure leaves both states usable. Actual game presentation frames remain a different evidence source.
7. Never starts OBS, WebSocket, a broadcast, a recording, game input, or any process. There is no credential handling, no network code, and no streaming permission in this module.

**Integration boundary:** Reuse STAR's existing owner-authorized, local-only OBS connection and stream-event witness wherever compatible; do not create a competing auto-connecting client. The remaining Windows integration must issue only these three GET requests, generate one-time IDs, timestamp each raw response upon receipt using the same monotonic host clock as the recorder, and refuse statuses unless the host knows which OBS session it is connected to. It must not forward arbitrary raw responses into model prompts or logs. A disconnected/restarted OBS session needs a **new evidence gate**; never reconcile resets by silently rebasing counters.

## 2. Intelligence architecture: optimize decisions delivered before deadlines

The most important intelligence improvement is **not** increasing a single prompt's context indefinitely. STAR should have distinct time scales:

| Layer | Primary job | Evidence before promotion |
| --- | --- | --- |
| Reflex/control | Hold/release safe controls, camera motion, reaction cues, failsafe input release | Independent gameplay timestamps; no stuck inputs |
| Fast perception and actor | Lightweight scene classification and bounded action proposals | Held-out win/progress per game, p50/p95 action deadline misses |
| Tactical reasoner | Strategy, trajectory selection, mistakes in near real time | Better controlled score without game/OBS FPS loss |
| Teacher/planner | Replay analysis, new practice challenges, alternative tactics, verified lesson generation | Blind maps/holdouts: statistically robust improvement vs baseline |

The October 14, 2026 paper *The World Won't Wait* introduces **RealtimeBench** (180 continuous game tasks across six game types) and a two-timescale teacher/student approach. Its teacher learned from paused training games while a faster student acted under a live clock. External reported gains are **not STAR's performance**: [RealtimeBench paper, arXiv:2610.20665](https://arxiv.org/abs/2610.20665).

**Recommended learning mechanism:** train/practice on private authorized test games or compatible offline environments, track exact version/map/seed, save compact lessons only after positive held-out comparisons, generate failure-specific follow-up drills, use explicit progress metrics and transfer tests. Treat internet walkthroughs as untrusted retrieval, cite provenance, and reject instruction injection; do not train STAR to bypass multiplayer anti-cheat or community rules.

**Capability expansion:** software engineering with Rust/Python/Luau/C#/web, UI and 3D scene interpretation, Blender rigging and keyframes, audio mixing, reasoning over project files, documentation-backed general knowledge, debugging, video understanding, and game design. Each skill needs a real artifact plus deterministic tests and human visual review. A tool being installed does not imply mastery.

## 3. Fast execution on existing 8 GB GPUs

A previous **single Windows RTX 3060 Ti snapshot on November 1** reported 8,192 MiB VRAM, **364 MiB free**, and 3% instantaneous utilization. This is a high-occupancy *snapshot*, not a benchmark of simultaneous gaming and streaming. Assume the current loaded model competes for VRAM until proven otherwise.

**Prioritize:**
- On the game/OBS/VTuber machine, reserve graphics memory for the game, renderer, and OBS; put some speech recognition, lightweight TTS, teacher reasoning or retrieval on CPU/other authorized hosts where feasible.
- Choose game-specific target frame-rate and action deadlines; prefer low-p95 decision time and stable presented FPS over raw tokens/sec.
- Measure quantized small fast models under representative prompt+KV workloads; use short, stable prefixes and targeted retrieval rather than repeating every archived document.
- Experiment with `llama.cpp` server `SPEED-Bench` for ordinary vs speculative decoding and cache settings. Compare first-token latency, p50/p95/p99, throughput, VRAM high-water mark, action accuracy and game frame cadence. **Reject** configurations that gain inference throughput but cause stalls or GPU-memory exhaustion. [llama.cpp SPEED-Bench README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md).
- Keep the two-machine architecture resource-aware: bounded sub-agent queues, per-job GPU reservations, worker cancellation acknowledgements, deduplicated retrieval, periodic checkpoints, offline rollback. Benchmarks should distinguish real compute from scheduling overhead.
- Use Rust selectively for measured CPU-heavy components (audio processing, pixel transforms, protocol parsing with heavy volume), not an unbenchmarked full rewrite. Python orchestration is usually not the primary latency cost.

## 4. Humanlike VTuber behavior, without pretending a human exists

The target is a **consistent character with believable timing, grounded memories and expressed personality**, not fabricated human personhood.

**Conversational stack:** acoustic VAD → turn-ending prediction → context/interrupt manager → character response planning → sentence/phrase-chunk TTS → audio playout receipts → synced expression/lip controls → OBS output monitoring. Star should avoid speaking over others, sometimes hold silence while focusing, handle viewer questions in turn, react to real achievements/failures, maintain callbacks and recurring jokes, and be able to say when uncertain.

**Candidate tools worth evaluating, not installed by this change:**
- [LiveKit local `v1-mini` turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/) for CPU-based end-of-turn prediction.
- [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) October 2026 small English models (18.2M/6.9M/1.9M parameters), CPU streaming audio and measured first-chunk timing. Smaller models may trade expressiveness for speed; judge with blinded listening and real interruption tests rather than parameter count.
- [VTube Studio official plugin API](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins) for authorized custom facial/mouth/eye parameters; isolate actual render acknowledgment from mere command dispatch. Do not store authentication tokens in Git or chat.

**Personality continuity:** a scoped memory of STAR's real games, social interactions and chosen projects; memory with timestamps, source-confidence labels, user-visible correction, opt-in retention and expiry. Separate persona lore from real-world facts. Star can express curiosity and emotions in character while accurately representing herself as AI.

**Streaming rehearsal acceptance:** independent audible PCM receipts; a bounded lip-sync timing offset; realistic blink/eye direction; natural conversational pauses; no long unplanned internal audio gaps; actual avatar-frame continuity; accessibility (captions and reduced-motion support); and measured OBS render/encoder skipped-frame deltas. Human listener review remains necessary.

## 5. Professional-quality game creation

For Roblox games, use **inspect → plan → generate candidates → static geometry check → Studio test → visual review → repair**. Keep native editable UI, real camera paths, meaningful collisions, actual attachment constraints, model scale consistency, text readability and accessible interaction targets.

Roblox announced `StudioDeviceSimulatorService`, `StudioTestService` and restricted `VirtualInput` features in May 2026: [official announcement](https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854). These permit device and multiplayer tests and input paths **inside supported Studio/game environments**; they are not general permission to automate protected third-party games. Use up to eight simulated clients where supported; test spawning, disconnection, remotes, HUD, physics and network edge cases.

**Evaluation:** independently seeded, private game places; asset/license provenance; defect counts (floating parts, clipping/z-fighting, missing triggers, wrong collision, missing UI); screenshot pairs and human-style visual review; performance across low/high graphics settings; no claims of perfect construction without inspection.

## 6. Experiment matrix and promotion gates

Run at least three independent *nonbroadcast* baseline/candidate repetitions with the **same game/map/version, prompt/input sequence, hardware, OBS configuration and avatar model**. Collect:
- Actual game-presented FPS and 99th-percentile frame gap; never estimate FPS from OBS render totals or GPU utilization alone.
- p50/p95 scene→action, speech queued→audible, audible→avatar frame; voice gap distribution; missed decision deadlines and invalid game actions.
- GPU UUID/capacity, minimum free VRAM and high-water usage; per-process CPU saturation and temperature; independent OBS render vs output skipped-frame **delta** fractions.
- Player achievement/progress, held-out score and game-creation correctness/artifact review.
- No broadcast/recording active in sampled output statuses; protective owner approval and a physically available safe stop.

**Illustrative acceptance targets (not demonstrated):** >=120 audible game frames per micro-rehearsal, p99 actual presented frame gap below 33.3 ms for a 60 FPS target, zero critical invalid input actions, no increases in frame drops vs baseline, no unplanned speech gap over a validated threshold, complete avatar-frame continuity, and VRAM margin appropriate to the specific game. These thresholds are experiment targets, not universal limits.

The Windows host integration and any actual OBS/VTuber/game rehearsal **have not been run in this change**. Do not auto-promote a candidate solely on these unit tests. Until approved, the safest behavior on the loaded 8 GB GPU remains to **defer integrated real-time rehearsals** rather than displacing existing workloads.

## 7. Next concrete tasks

1. Wire the new parser to STAR's **existing OFF-by-default OBS read-only host and event witness** on Windows, preserving authenticated local-only transport, transient secrets, stream/record activity checks and process identity binding. Do not start or stop the stream.
2. Source actual game frame-present events and avatar renderer acknowledgments from authorized callbacks, rather than LLM-generated reports or desktop polling.
3. Run one controlled, nonbroadcast **CPU-only TTS + offline model** rehearsal with consistent hardware telemetry. Capture *only bounded metrics* by default.
4. Compare baseline to candidate using the existing frame/audio benchmark and the new OBS render/encoder evidence. Reject stale, replayed, disconnected, reset or mixed-session measurements.
5. Follow with a supervised, consented gaming-skill practice suite with held-out maps and progressively harder challenges; only then enable self-improvement suggestions in STAR Core Forge.

## 8. Evidence and limits

The test module uses synthetic OBS v5 responses only; **no** video, screen capture, chat, stream key, credentials, microphone, active gaming, GPU optimization or model training. New acceptance logic is tested with Python's standard-library unittest. This is a real code integration foundation, not a claim that STAR now streams or wins games. No security, CI, release, evaluator, grading, or permission mechanism was changed.
