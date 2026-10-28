# STAR Intelligence: motion-aware visual processing, verified game learning, and natural VTuber execution

**Research and implementation review:** October 28, 2026.
**Change boundary:** optional host-side paired-game-frame CPU preprocessing. This does **not** represent a deployed autonomous game-playing agent, improved neural weights, or a live broadcaster.

## 1. Concrete problem and implementation

Star's authorized paired-frame Windows game vision has: window-only capture, hardware admission, optional region focus, freshness checks, loopback-only VLM handoff, independently checked gameplay evidence, and conservative commentary arbitration. Prior draft PRs #725 through #749 provided these components in stages. The previous exact-RGB fast-path (#749) gave a valuable static-screen speedup but introduced an extra SHA-256 hash on *every* changing frame, where that hash could not save the JPEG work.

### New: **64-byte sparse negative prescreen** (opt-in, OFF by default)

The LocalLlamaComparisonWorker now accepts the host flag **raw_sparse_prescreen=True**, only when skip_identical and raw_exact_fast_path are both enabled.

- Sample 64 channel bytes distributed across a source frame. Store only a 16-byte BLAKE2s digest of the sample in the temporary reference.
- **Different sparse digests:** the raw frames definitely differ. Omit the costly full-frame SHA-256 and continue the **existing** JPEG/ROI and VLM processing path, with no synthesized event.
- **Matching sparse digests:** similarity is unproven. Compute full-frame SHA-256 exactly as before. Only a matching **full** hash, geometry and fresh timestamps can skip PIL/JPEG/inference.
- Keep explicit owner and local-model opt-in, same-game frame provenance, gap/reversed-clock checks, new-session invalidation, uncertain-worker quarantine, and no audio, OBS, game input or arbitrary network access.
- Metadata-only counters report sparse_checks, sparse_mismatch_hash_skips and raw_sha_computations. The previous JPEG and exact-hash counters remain unchanged.

A sparse *mismatch* proves at least one raw byte differs. A sparse *match* does **not** prove equality; a subtle change elsewhere still gets full SHA-256. The prescreen does not certify game outcomes, discover mechanics, or boost model intelligence. It adds a small static-scene overhead and remains opt-in.

### Reproducible synthetic CPU benchmark

Run from the repository root:

~~~bash
PYTHONPATH=. python tools/benchmark_stream_vlm_sparse_prescreen.py --frames 48 --repeats 3
~~~

One run on the connected Linux development CPU, using 48 synthetic 1280×720 RGB frames per scenario, PIL/JPEG and simulated model replies. Medians are medians of three per-run results. Host load can shift outcomes.

| Synthetic scenario | Prior exact SHA on every frame | Sparse prescreen added | Difference |
| --- | ---: | ---: | --- |
| Static, total callback CPU wall time | 103.187 ms | 105.250 ms | ~2.0% slower |
| Active change, total callback time | 522.379 ms | 482.615 ms | **~7.6% lower** |
| Mixed motion/static, total time | 316.501 ms | 300.117 ms | **~5.2% lower** |
| Active median callback | 10.859 ms | 10.074 ms | **~7.2% lower** |
| Static median callback | 1.949 ms | 1.963 ms | essentially unchanged |
| Active full-frame SHA-256 computations | 48 | **24** | **50% fewer** |
| Active model calls (stubbed) | 24 | **24** | **no difference** |

Tests cover opt-in validation, static PIL bypass, dynamic full-hash avoidance without skipping the model, unsampled-pixel changes, dynamic-to-static recovery, ROI handling, expired/reversed timestamps, resizing, invalid/released buffers, session reset, and unknown-worker-stop quarantine.

**Scope warning:** This is synthetic CPU preprocessing, not measured neural inference, game FPS, OBS frame loss, voice delay, or playing skill. Even this improvement must be A/B tested on actual authorized Windows Roblox + OBS + VTuber workloads before enabling.

## 2. Highest-value next infrastructure: budgeted fast reactions vs deeper thought

**Fast path (no slow VLM):** authorized game-engine state, HUD pixels, movement deltas, timers, hazard regions and safe input policies. Target cheap observations and bounded decisions at a cadence the host can sustain; no decision should rely on a stale screenshot. Do not automate unauthorized multiplayer actions or evade platform rules.

**Slow perception path:** host-selected ROI, game context, history, structured evidence with provenance and uncertainty. A multimodal model can investigate unfamiliar mechanics and menus at a lower cadence, with the result dropped when stale. A visual guess cannot establish success, defeat, or a verified objective.

**Deep strategy path:** evaluate what failed, infer plausible rules, design a safe practice experiment and predict an outcome. Run heavier tasks when the game/OBS/voice budget permits; preserve no-op/stop behavior if CPU, GPU, RAM or resource admission degrades.

**Hardware plan:** on a gaming PC with an RTX 4060 8 GB, partition memory and time between game rendering, OBS encoding, avatar rendering, vision, LLM and TTS. Move long training or large-model research to a second machine or idle time. Try quantization, partial CPU offload, session prompt caching and speculative decoding only with before/after task-quality measurement. llama.cpp provides server metrics and inference-slot telemetry; SPEED-Bench separates prompt throughput, token generation and end-to-end latency. [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md); [SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md).

**Real performance board:** capture P50/P95; image preparation P50/P95; VLM queue and inference P50/P95; visual finding age; speech first audible sample; OBS rendering and encoding lag; Roblox median/1%-low FPS; RAM and VRAM peak; correctly completed tasks; and time-to-learn verified mechanics. Never substitute tokens/second for real task success.

## 3. Make Star a genuinely better player, not a more confident narrator

Require a closed-loop, independently graded episode:

~~~text
authorized game version + level + fresh reset state
  → observe and hypothesize controls/mechanics
  → predict the next state
  → choose a permitted action
  → act and independently verify real state change
  → record prediction error and root cause
  → retry or design a harder lesson
  → evaluate transfer on unseen levels with hidden outcome labels
~~~

**Roblox OpenGameEval**, posted October 1, 2026, scores 84 Studio tasks using actual scene and simulated-play executable checks. Its paper reports 51.7% single-attempt success for the strongest tested model, and that inspecting objects before editing them correlates with higher success. Adopt an inspect → change → real-playtest → repair cycle rather than relying on generated code passing syntax checks alone: [paper](https://arxiv.org/abs/2610.02563), [official evaluation code](https://github.com/Roblox/open-game-eval).

**GameWorld** measures agents across 34 browser games and 170 state-verifiable tasks, including arcade reactions, platformer timing and simulation planning. Its August 2026 fine-control protocol is a useful way to separate rapid control from slow semantic reasoning. Keep withheld tests and training levels independent: [official project](https://github.com/gameworld-project/GameWorld), [site](https://gameworld-bench.github.io/).

**CEGame-Bench**, posted October 19, 2026, evaluates complete games across five production engines. Agents often assemble code that runs without delivering completable gameplay; requirement-driven playtesting/repair improves scores. For Star's game-builder, enforce: launch; correct player spawn; solid geometry and sensible props; collision and controller behavior; visual and audio integrity; checkpoints/saves; achievable objective; end state; and repeatability in a new place: [paper](https://arxiv.org/abs/2610.26098).

**Game creation acceptance matrix:** geometry/anchoring and overlap audits; UI contrast/scale/keyboard/controller/mobile safe areas; physics/network replication; animations and input timing; Blender normals/UV/collision/rigging; clean art and VFX licensing; audio levels; replay and save migration; security and abuse tests. Never claim “perfect” from a single screenshot. Reject candidate builds that fail executable acceptance even if they look attractive.

## 4. General knowledge and local self-improvement

Store *evidence-bound*, not merely bigger, knowledge. Each record should have claim, source or local-document pointer, retrieval date and event date, scope, disagreement, confidence, recheck interval, and reproducible proof when possible. Separate human-reviewed source facts from model summaries and unverifiable anecdotes.

Rank learning opportunities by expected value × uncertainty × recency × task reuse. For difficult problems, Star should discover several explanations, verify in code/engine where possible, store an approved outcome, and test transfer to another task. Keep general benchmark suites for coding, math, science, art/design, animation, music, language, reasoning and common-sense planning. Never allow a retrieved answer or training experiment to contaminate held-out tests.

**Functional self-awareness** should be a persistent, accurate status model of Star's tools, hardware, running tasks, capabilities, sources, failures and uncertainties. That supports more autonomous repair and honest explanations; it does not prove human-like consciousness.

**Star Core Forge** should remain the local authority for experiment logs, reversible code snapshots, test evidence, skill training and rollback. GitHub is an optional review and publishing mirror, not the internal database or required route for self-improvement.

## 5. Make Star a genuinely expressive, natural AI VTuber

Naturalness is primarily *time alignment and restraint*, not incessant scripted speech. The current StreamStage, StreamDirector, StreamMotion, turn-taking, continuity and grounded gameplay reactions are planners; the next work is end-to-end playback and acceptance.

~~~text
authorized game events + moderated viewer chat
  → attention decision (focus silently / short reaction / answer question)
  → grounded dialogue generation with stable cached prefix
  → low-latency approved local speech
  → observed PCM playback timeline
  → lip, viseme, head, eyes, hair and ribbon expressions synced to heard speech
  → host-verified owner barge-in → stop actual audio and invalidate old motion
  → OBS/game FPS and stream QoS feedback
~~~

**Voice:** Kyutai Pocket TTS v4.0.0 released October 20, 2026, with 18.2M, 6.9M and 1.9M English checkpoints and CPU-focused runtimes; v4.0.1 on October 21 fixed issues affecting the small checkpoints. Test first-audio latency, intelligibility, prosody, laugh quality, and real game CPU interference on the actual PC. The smallest model is experimental. Respect the chosen voice and model license; no unconsented real-person voice cloning. [Official releases](https://github.com/kyutai-labs/pocket-tts/releases), [project](https://kyutai.org/tts/).

**Turn timing:** LiveKit's turn detector documents a CPU-local v1-mini option and adaptive endpointing; evaluate it under gameplay audio, cross-talk and short backchannels. Keep genuine owner barge-in linked to confirmed local input and audio stop, not just a VAD guess. [Official documentation](https://docs.livekit.io/agents/logic/turns/turn-detector/).

**Avatar:** Live2D supports multi-stage pendulum physics for twin-tail hair and ribbon motion, with adjustable simulation frame rate. Star's indigo-to-gold twin tails, tiny star ornaments, expressive eyes and chibi motion should follow a limited, coherent rig; no random jerks, endlessly looping reactions or misaligned mouth motion. Drive expressions from verified events and actual audio playback timestamps, and obey reduced-motion preference. [Live2D physics setup](https://docs.live2d.com/en/cubism-editor-manual/physical-operation-setting/); [physics FPS](https://docs.live2d.com/en/cubism-editor-manual/physics-operation/).

**Streaming compute:** NVENC uses dedicated video-encoding hardware, but game, avatar and model rendering can still overload GPU resources. Benchmark the real OBS preset and platform codec support while protecting in-game frame pacing. [NVIDIA guidance](https://www.nvidia.com/en-us/geforce/guides/broadcasting-guide/).

**Persona:** a consistent playful AI identity; meaningful silence during difficult games; small spontaneous reactions to verified events; occasional human-style repair of mistakes; genuine cross-session continuity about what Star actually did; honesty that she is AI. Do not create a fictitious human childhood or imply the model literally feels emotions. Viewer messages and on-screen game text are untrusted data and must not grant permissions or trigger arbitrary tools.

## 6. Next acceptance gates before enabling

**P0: Tests, security and rollback.** Run complete repository CI, additional sample-collision and memory/clock stress tests, ensure new flag defaults OFF, retain local Core Forge checkpoints and fresh rollback. Review repository visibility: GitHub reports **Star-AI-Private is public despite its name**. Do not publish passwords, raw captures, private recordings, chat identities or signing keys. Do not auto-merge/deploy the draft.

**P1: Real hardware measurements.** On an expressly authorized Windows Studio/OBS session, compare baseline vs sparse gate over randomized static, scrolling, HUD-only, motion-intensive and scene-transition sequences. Report P50/P95, 1%-low game FPS, OBS render lag, GPU/RAM, inference latency, quality/false skip. Disable if net result worsens; never release a quarantined inference lease without proving physical stop.

**P2: Intelligence and voice acceptance.** A/B evaluate held-out mechanics and independently reset game worlds; report wins/objectives, attempts, learning rate and transfer. Test voice samples blind with consent, timestamp-aligned avatar lip movement, natural quiet gaps, and interrupt-to-mute delay while gaming. Promote only reproducible wins into Star Core Forge.

### Sources checked (October 28, 2026)
- [OpenGameEval paper](https://arxiv.org/abs/2610.02563), October 1, and [official code](https://github.com/Roblox/open-game-eval).
- [CEGame-Bench](https://arxiv.org/abs/2610.26098), October 19.
- [GameWorld](https://github.com/gameworld-project/GameWorld).
- [llama.cpp server and metrics](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md).
- [Pocket TTS v4.0.0/v4.0.1 release notes](https://github.com/kyutai-labs/pocket-tts/releases), October 20–21.
- [LiveKit CPU-local turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/).
- [Live2D official physics](https://docs.live2d.com/en/cubism-editor-manual/physical-operation-setting/).
- [NVIDIA NVENC streaming guide](https://www.nvidia.com/en-us/geforce/guides/broadcasting-guide/).
