# Star AI: one-shot evaluation receipts and the next intelligence / VTuber engineering frontier

**Researched November 5, 2026.** Status: *host-side anti-replay logic implemented and offline tested in this branch; real streaming and model-speed gains not demonstrated.* This plan builds on the model evidence stack in PRs #993–#997.

## Why this work exists

An agent that produces long explanations, more tokens/second, or endless autonomous activity is not necessarily smarter. Star should improve **verified outcomes per unit of wall-clock time** while preserving game FPS, privacy, reliability, owner control, and convincing realtime interaction. The previous model router already checked paired held-out task outcomes, critical-task regression, p95 latency, VRAM, preregistration, matched execution cohort, and host HMAC authenticity. The remaining immediate gap was **replay across separate process invocations**: an authenticated cohort could be presented repeatedly unless a protected host persisted its consumption.

## Implementation: protected, one-shot pilot claim

The new \`star.stream_route_cohort_ledger.claim_verified_fast_route(...)\` is an *optional host-only* wrapper around the existing signed selector. It checks owner opt-in, the exact pinned evaluator build, valid HMAC evidence and existing model/quality/latency gates **before opening the ledger**. Only a genuinely faster, independently scored candidate can produce a receipt. Baseline-only recommendations and any rejected/tampered evidence do not consume a cohort.

A local SQLite transaction uses \`BEGIN IMMEDIATE\` and a unique cohort primary key: only one concurrent caller can record the same cohort. The database records only opaque SHA-256 commitments, route aliases and trusted time, not prompts, player names, screenshots, voice clips, verification keys or scores. It creates a POSIX mode-0600 file and refuses symlink, insecure preexisting file, or group/world writable parent directories. Triggers reject ordinary UPDATE and DELETE of prior claims. Corruption and SQLite lock errors fail closed; the implementation does not silently replace damaged evidence.

**Trust boundaries:** a verified receipt is **not** an authorization to launch a model, send input to a game, push code, spend, or broadcast. \`owner_approved=True\` is a trusted host assertion; arbitrary callers cannot treat it as an authentication credential. Database protections do not defeat OS-administrator compromise, deletion/restoration from an old backup, modification by a rogue process with equivalent privileges, or cross-machine replay when ledgers do not share durable storage. A genuine production deployment needs a host-owned persistent volume, ACL review/Windows support, independent scoring, trusted time, durable backups, offline key rotation and a separate admission/broadcast gate. Do not expose this function as a tool to a model or viewer.

The ledger is evaluated **after** selection to avoid false-positive consumption of a baseline. To enforce single use at an actual external deployment boundary, the owner-controlled deployment service must consume the receipt transactionally with its own state transition (or use an idempotent orchestration/outbox protocol); the current API intentionally does not attempt that cross-service atomicity.

## Frontier research: prioritize measurable gaming intelligence

### 1. Fast perception and control without token-by-token gameplay lag

Use a **multi-rate controller**, not one enormous LLM loop:

| Layer | Trigger / candidate cadence | Inputs | Success condition |
| --- | --- | --- | --- |
| Deterministic motor controller | game state / up to game tick | verified telemetry or permitted keyboard/mouse action | avoids missed deadlines, stuck controls and cheating |
| Tactical observer | adaptive ~2–5 Hz when useful | changes in scene, HUD, health, position, chat focus | anticipates danger and reduces redundant vision frames |
| Planner | asynchronous on goal changes or loss | compressed trusted observations, previous plans and uncertainty | improves objective completion on unfamiliar levels |
| Teacher/evaluator | only during private practice or low-load windows | objective outcomes, replay receipts, held-out tests | learns transferable verified skills instead of accumulating anecdotes |
| VTuber director | event-driven; aware of game danger and speech backlog | action state, viewer intent, mic turn-taking | relevant reactions, natural silence, no overlaps |

All cadences are **proposed starting points**, not benchmarks. When the game does not expose trustworthy state, use screenshot perception with delayed/out-of-date frame checks, lower capture rate under load, and explicit abstention. Do not rely on unsupported game mods, anticheat circumvention, or automating public competitive games against terms.

[GameWorld](https://gameworld-project.github.io/) evaluates 170 tasks in 34 browser games using verifiable serialized state. Its **GameWorld-RT** keeps the game moving while the AI reasons, exposing a gap between paused benchmarks and actual play; use both tracks. In a local replay suite: record action timestamp, observation timestamp, state transition, goal completion, frame stalls and missed deadlines. Compare against scripted heuristics and a simple baseline, using held-out seeds/maps and fixed hardware/quality budgets.

[Google DeepMind's SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) is a research direction for cross-environment reasoning and adaptation, **not** a ready-made local Star integration. Star should store explicit *skill policies* with provenance and failure modes, instead of treating one successful game run as a universal skill.

### 2. Roblox game building: verified inspect–edit–playtest–repair

As of the [October 2026 OpenGameEval](https://github.com/Roblox/open-game-eval), 84 curated core tasks and executable Studio/play checks expose major gaps in stateful agent development; inspecting relevant instances before editing strongly correlates with success. Adopt tests that force Star to:

1. Inspect instance hierarchy, script dependencies, networking model, UI hierarchy, preexisting scene geometry and API version before writing code.
2. Propose a bounded diff and declare acceptance checks before running it.
3. Run Luau syntax/type/lint checks, protected Studio playtests, multiplayer and latency tests where relevant; save exact machine-verifiable outcomes.
4. Compare results with a preregistered rubric, replay failed cases and attempt bounded repair; revert if the owner-set budget or failure threshold is exceeded.
5. Benchmark *unseen* maps and tasks. A task that passes only because Star saw the test oracle should not count as learning.

A separate [Roblox Network Simulator](https://create.roblox.com/docs/studio/network-simulator) can test induced latency/jitter/packet loss in Studio playtests. Use it for multiplayer affordances, server authority, and error recovery; it is not a substitute for full production load testing.

### 3. Speed and compute scheduling on 8 GB VRAM

**Do not promise a model-specific tokens/second figure without a measurement on the actual machine.** On 8 GB cards while gaming, the major risk is GPU memory pressure and queueing among the local model, game, OBS and avatar renderer. Batch research and training when not streaming; during recording, set hard VRAM headroom/residency caps and an inference admission gate.

Use [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) to measure p50/p95 end-to-end request latency, prefill/decode throughput, and draft-token acceptance for speculative decoding at fixed prompts, concurrency and context size. Pair those results with **game frame-time percentiles**, OBS missed frames, speech start latency and task correctness. Compare no-speculation, draft-model, n-gram, MTP or EAGLE3 *only if supported on the installed build*. With 8 GB and an active game, an extra draft model can be a net loss.

The local fast path can choose a smaller model for conversational tags, short reaction suggestions and well-scoped actions; hard reasoning stays with a capable planner or cloud model (only if the owner enables it). Upgrade a route only after **paired critical-case no-regression** and a stable pilot. The newly added one-shot receipt prevents reusing the same evidence again for another pilot review, but it does not benchmark any deployed model by itself.

### 4. Humanlike VTuber behavior while staying transparent about being AI

Natural streaming is not nonstop output. [Proact-VL (ICML 2026)](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) specifically treats *when to speak* and controlling response quantity as real-time companion problems. Maintain distinct priorities: owner interruptions / safety, meaningful viewer questions, gameplay urgency, optional commentary, otherwise silence. Add momentum-aware commentary: avoid repeating a joke, react to actual in-game surprises, and stop talking during dangerous moments.

[NVIDIA DyaPlex (June 2026)](https://research.nvidia.com/labs/amri/projects/DyaPlex/) studies synchronized streaming speech and motion. A practical first implementation is timestamped **visemes, gaze and expressions** tied to real audio chunks, with cancellation on barge-in, rather than deploying a large multimodal speech-motion model on an 8 GB gaming GPU. Preserve expressiveness while respecting reduced-motion settings.

[Kyutai Pocket TTS v4.0.0 (October 20, 2026)](https://github.com/kyutai-labs/pocket-tts/releases) introduced smaller English models and CPU-oriented runtime binaries. Benchmark under the actual Windows CPU, headset, game and avatar load. Measure audible first chunk, total synthesis, interruptions and naturalness with blinded human ratings; published numbers from other machines are not valid claims for Star.

Character depth should be **grounded continuity**: verified episodic gameplay memory (what she really played/won/failed), stable voice/personality settings, voluntary hobbies, bounded curiosity tasks, relationship continuity only with user consent, sensitive-chat redaction and opt-out controls. Build a rich believable AI character; do not imply sentience or disguise her as a human to viewers. Viewers should know the channel features an AI VTuber.

### 5. General knowledge and autonomy

Separate factual knowledge from persona style. Retrieve current documentation, cite origin and date, mark uncertainty and stale facts, and practice on tasks scored by executable or human-grounded oracles. Store successful repair cases with confidence and provenance; do not self-edit skill rankings solely from the model's own self-assessment. Prefer isolated experiments, merge/promotion gates, rollback snapshots, resource budgets, and private tool permissions over open-ended recursive code rewriting.

Use a **skill map** for gameplay mechanics, Luau/Roblox, art, audio, animation, Blender, websites, moderation, and streaming, each with: required input/tools, acceptance suite, current calibrated score, failure examples, last verification and progression milestones. Maintain day-to-day experience memory separately from sensitive viewer/user data.

## Private Windows rehearsal acceptance plan (not yet performed)

1. **Preflight**: OBS record-only; never invoke broadcast API. Verify window, game, avatar, mic/audio loopback, allowed input scope, free VRAM and disk space, and opt-in toggles. Pin software/model builds and hashes.
2. **Minimum scenarios**: navigation tutorial, hazard avoidance, unfamiliar objectives, viewer interruption, owner interruption, optional commentary during intense play, no speech during quiet periods, speech/audio failure, and shutdown/recovery. Compare against a no-LLM baseline.
3. **Telemetry**: timestamp every observation/action/ASR/TTS chunk, capture missed deadlines, game fps p1/p50/p95 frametime, encoder missed frames, VRAM high water, CPU load, interruption-to-quiet delay, viewer relevance/annoyance rating, artifact completeness and objective success.
4. **Scoring**: preregister at least 30 matched attempts per chosen task/workload route, with dedicated critical cases. Report successes and all failures (do not trim). No candidate promotion if any critical regression; signed host receipts and one-shot ledger required for owner-reviewed pilot.
5. **Exit criteria**: no unauthorized network broadcast, no out-of-scope game action, no claims about wins without verified outcomes, no secret leakage, no recording without owner consent. Use objective baseline comparison instead of arbitrary marketing thresholds.

## Next development milestones

**Near-term:** connect the private scorer to durable host-owned receipts, integrate the one-shot ledger at an owner-controlled model pilot endpoint, add actual Windows preflight telemetry and live OBS *recording only* feedback, and lock down host ACLs. **Mid-term:** game-state replay for unfamiliar tasks, held-out practice curriculum, strict load-aware model/voice switching, and audiovisual synchronization scorecards. **Long-term:** robust lifelong skills with independent evaluation, game-building Studio automation and cross-title transfer; treat full-duplex models as hardware-dependent research, not a promise.

No fabricated inference gain, successful stream, recorded episode, AI consciousness, model training improvement, or autonomous public gaming is claimed in this document.
