# Star AI: Independent Game Evidence, Faster Local Intelligence, and Natural VTuber Roadmap

**Research and implementation date:** 2026-11-03. **Status:** code and offline tests for independent gameplay evidence; other items are proposals until measured on hardware.

## Implemented in this change

Two independent game-learning evaluators previously accepted distinct signed trial/run IDs even when multiple trials referenced the **same evidence_sha256**. A valid HMAC only authenticates the signer; it does not turn duplicated source observations into independent attempts. With enough replayed evidence, an offline review could overstate transfer across seeds and games.

1. `game_transfer_eval.evaluate_transfer`: maintain a bounded, run-local set of capture digests; reject re-used observations across the entire preregistered roster, including cross-game, cross-situation, and baseline-vs-candidate aliases, **before** calculating/reporting performance. It remains an owner-reviewed advisory gate, not permission to deploy.
2. `game_paired_study.PairedGameStudy`: keep an opt-in study-local set of accepted observation digests; a second *independently signed* trial using an old observation now permanently contaminates the study, with no interim outcomes/p-values exposed. The reset/initial-state SHA256 is *not* the observation digest and is expected to match across paired runs.
3. Adversarial tests cover copied evidence in a different game, within a baseline/candidate pair, with an incomplete roster, between randomized arms, and in a later seed. The ordinary unique-evidence controls still pass.

**Boundary:** these changes cannot distinguish two different screenshots of the same faked game event. An independently trusted scorer, separate engine state witness, game reset proof, and access-controlled holdouts are still required. There is no model training, actual game control, neural-speed increase, voice integration, or live streaming in this change.

## High-leverage engineering research and next milestones

### 1. Close the real-time gaming loop, not another isolated telemetry abstraction

Build an owner-controlled, **nonbroadcast** Windows rehearsal that joins existing source telemetry, actuation interlock, watchdog, Windows input guardian, capture-to-action benchmark, and skill evaluator. Log only privacy-minimal monotonic stage latencies: capture, transport, preprocess, policy inference, input acknowledgment, engine progression, speech PCM audible start, and OBS/audio/video delivery. Score success under a **continuously moving** environment, and verify neutral/released inputs on emergency stop. Rehearse offline and use independent reset/win/loss observations; do not claim gameplay competence from unit tests alone.

GameScaling's **2026-11-01 correction** revised real-time ViZDoom scores when measurement omitted processing time and paused game simulation. The lesson for Star is to measure complete end-to-end interaction, not token/s or isolated LLM calls. Source: https://gamescaling.github.io/ .

### 2. Make generalization genuine

Separate PRACTICE (model-visible) and VALIDATION (owner/evaluator-only), preregister held-out levels and seeds, and ensure each trial uses its **own independent capture evidence**. Test multiple games and map variants; report per-game macro gains alongside paired win/loss and uncertainty. Do not promote on a single lucky run or on one game's oversampled seeds. Add an owner-only contamination audit spanning evidence store and reset witness after the Windows rehearsal exists. Avoid exposing holdout questions/outcomes through any planner, Discord status, or VTuber memory.

Roblox OpenGameEval, **October 2026**, measures stateful Studio tasks with executable checks in edit/play contexts and reports that inspecting objects before editing correlates with better success. Turn this into Star's build loop: read-only inspect -> propose 4-8 bounded candidates -> Luau/static checks -> sandbox Studio playtest -> independent output/screenshot comparison -> repair or revert. Sources: https://github.com/Roblox/open-game-eval and https://arxiv.org/abs/2610.02563 . The March 5 and March 19, 2026 Roblox Studio announcements document built-in MCP and expanded screenshot/mesh tools: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 and https://devforum.roblox.com/t/assistant-updates-mesh-generation-new-mcp-server-tools-screenshot-tool-and-more/4527258 .

### 3. Increase speed without lying about speed

Use an experiment matrix on the actual owner's 8GB-GPU host: same game scene, same timed prompts, same stream/no-stream condition, fixed capture resolution and inference context. Compare short/long prompts, quantizations, slot counts, fixed cache on/off, speculation on/off, CPU speech on/off. Record p50/p95/p99 capture-to-action, first *audible PCM*, missed frame deadlines, system RAM, VRAM peak, game FPS 1% lows, OBS dropped frames, and actual game outcomes. Enable a configuration only if correct action rate and streaming quality do not regress.

llama.cpp issue **#30961**, opened **2026-10-22**, reports KV cache restoration failures with unified KV, RAM caching and multiple slots; issue **#27148**, opened **2026-08-15**, reports cross-conversation cache confusion under other combinations. These are issue reports, not universal claims; regression-test precise Star build/config before enabling shared prompt caches. Sources: https://github.com/ggml-org/llama.cpp/issues/30961 and https://github.com/ggml-org/llama.cpp/issues/27148 .

Candidate allocation: reactive game action in a bounded low-latency lane; tactical planner only when game deadline permits; deep study, generative graphics, search and self-improvement offline or when spare compute exists. Preserve a strict small VRAM headroom for game + compositor + OBS; pause learning before harming them. Prefer truthful caching of curated documents and verified worked examples to naive ever-growing contexts.

### 4. Make Star's VTuber personality socially believable

Humanlike presentation means **timing, memory continuity, voice expression, attentive listening, and mistakes she can learn from**; it does not require pretending to be biologically human or conscious. Build conversational interruption and silence tests into the private Windows rehearsal. Generate short speech grounded in a specific verified observation, recognize viewer questions but quarantine chat from control instructions, and suppress stale/repeated reactions. Let Star have recurrent interests, likes and recurring jokes without inventing backstories or false gameplay wins.

Proact-VL (Microsoft Research, ICML **2026**) explicitly targets **when** a realtime gaming companion should speak, including controllable commentary quality/quantity and continuous video streams. Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ .

Kyutai Pocket TTS v4.0.0 (released **2026-10-20**) introduced English 18M, 7M and experimental 2M model families with CPU-friendly binaries. Try an A/B test against existing Star speech, comparing intelligibility, expressiveness, actual first PCM latency, CPU utilization and missed game deadlines rather than presuming the smaller model sounds better. Source: https://github.com/kyutai-labs/pocket-tts/releases .

Useful stretch goals after local nonbroadcast validation: distinct emotions in a compact animation state machine, matching speech prosody to verified events, phoneme-to-mouth synchronization, private co-op teammate interaction, creator sessions using Studio MCP, nondeceptive viewer polls for safe game choices, accessible captions, and automatic post-stream privacy review.

### 5. General knowledge and autonomous self-improvement

Keep a provenance-aware knowledge catalog with source date, verified example, domain, invalidation trigger and confidence; run retrieval evaluations on out-of-distribution questions. Allow autonomous sandbox tasks, but only propose code promotions when existing/novel tests, hidden evaluations, security review, and resource benchmarks all pass. Maintain local history, snapshots and rollback even if GitHub is used as a publishing mirror. Do not let untrusted web pages, gameplay chat, or retrieved text grant device permission.

## Acceptance and ownership

All new training, camera/mic, desktop control and broadcasting capabilities default OFF. No spend, external posting, account changes, or irreversible production promotion without owner approval. Keep automated evaluations private and publish only non-sensitive aggregate results. Aim for: reproducible end-to-end gaming trials; meaningful multigame generalization; short first-audible delays; uninterrupted FPS/OBS; no unsafe controls; and a clearly AI-identified but warm, funny, expressive persona.

**Minimum acceptance artifact for the next increment:** a single verified Windows rehearsal trace containing real engine observation, authorized input, controller stop verification, measured first audio, avatar/OBS status, and an independently scored game result. Until then, progress remains infrastructure/testing, not demonstrated gaming or streaming intelligence.
