# Star AI: workload-matched inference, independent game learning and grounded VTuber behavior
Date: 2026-11-02. Scope: host-only, offline-first, no broadcasting or input automation.

## Executive decision
Star cannot be evaluated as an autonomous gaming VTuber by running a text-only
speed test on an otherwise idle machine. Playing a real game consumes GPU/CPU,
OBS consumes encoder time and VRAM, and avatar rendering + voice create competing
deadlines. A model that looked fast 5 seconds before OBS went live can be too
slow to act on the next moving game frame. Correctness at a paused clock is
insufficient. This change introduces **optional strict workload-matched
inference samples** to prevent one such misleading live speed assumption.

This is a conservative evaluation enhancement, **not a measured performance
increase**, a new model, an automatic ability to win games, or a live-stream
feature. The option remains OFF by default to preserve existing integrations.

## What was implemented in this change
* `GameDeadlineRouter(strict_workload_profile=True)`: opt-in isolation of
  trusted inference latency samples by whether OBS is independently attested
  live. Nonbroadcast quick-model timings no longer qualify a **live** model
  action simply because they fall within the global 15-second recency window.
  A live measurement cannot qualify idle routing either. Every sample still
  requires completed/timeout status, scoped ID, strictly monotonic sample ID
  and host monotonic clock and explicit host measurement.
* `record_reactive_latency(..., stream_live=True|False)` threads the load
  label into the 64-entry bounded runtime profile (default 64; configurable).
  `RealtimeGameLoop.record_reactive_latency` forwards this marker; all
  existing callers continue to work with strict mode disabled.
* New diagnostic `insufficient_matching_workload_latency_samples` distinguishes
  "too few samples under this actual load" from a slow p95. It is a reason to
  perform an independently controlled *non-action* measurement before trying
  to use a fast model under this workload; it is not permission to start it.
* All control surfaces remain advisory and owner/session scoped.
  `GameThinkLease.authorizes_model_launch` and `authorized_to_play` remain
  false. The final game focus, OBS health and key-release gates remain separate.
* No audio frames, screenshots, game keys, prompt text, IDs from viewers,
  secrets, personal data, telemetry archives or outbound network calls were
  added.

### Reproduced gap and regression proof
Before the implementation, the new strict-mode tests failed because the
router could not distinguish measurements taken while idle versus those
taken while OBS was live. After implementation:
- idle data alone cannot warm a live strict profile;
- five/eight trusted live samples can warm it (not evidence of universal
  gaming success), while reversed workload labels cannot;
- live state is propagated across the host-only `RealtimeGameLoop`;
- invalid flag types fail closed; session reset discards the profile;
- the default legacy path remains unchanged.
These tests are synthetic unit evidence, not a Windows OBS load benchmark.

## Evidence: what the 2026 literature supports
1. **Wall-clock evaluation, not paused-game optimism.** *Realtime-Bench:
   Can Frontier Models Solve Real-time Interactive Problems?* was posted
   2026-10-15 (arXiv:2610.22155). It compares actual wall clock against a
   paused environment and a token-based clock. The reported top wall-clock
   success rate is 44% in its chosen tasks. Treat this as a motivation to
   measure Star's **effective action before the scene deadline**, not as her
   achieved score. https://arxiv.org/abs/2610.22155
2. **Two-timescale game learning.** *The World Won't Wait: Evaluating and
   Teaching Agents Under a Live Clock* was posted 2026-10-14
   (arXiv:2610.20665). It evaluates 180 continuously running tasks spanning
   six game types and reports a fast student whose average progress score
   rose from 13.51 to 24.19 following two rounds of teacher-led learning.
   Star needs a **fast action policy** during active gameplay and a separately
   approved, slow, reproducible teacher that studies failures between attempts.
   No teacher may interfere with live gameplay or read hidden holdout cases.
   https://arxiv.org/abs/2610.20665
3. **Actual speculative decoding is hardware/workload dependent.**
   llama.cpp SPEED-Bench explicitly measures prefill/decode throughput,
   end-to-end latency and draft acceptance and provides paired baseline-vs-
   speculative comparisons. Use the same prompts, output limit, concurrency,
   quantization, context and live background workloads in both arms. Speculative
   decoding is an experiment, not a guaranteed optimization.
   https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
4. **CPU TTS trades GPU space for CPU competition.** Kyutai's Pocket TTS
   repository lists CPU-first streaming generation and newly documented
   smaller English models (October 2026: ~18.2M, ~6.9M and ~1.9M parameters).
   Evaluate naturalness, word stability, first *audible* chunk, gap artifacts,
   and CPU contention on the target Windows box. Do NOT assume model-size
   rankings equal perceived voice quality. Do not install a CUDA build solely
   to run a CPU TTS candidate.
   https://github.com/kyutai-labs/pocket-tts
5. **OBS and avatar must be measured at physical output, not queued work.**
   OBS 28+ includes obs-websocket. Its authentication should remain enabled
   and limited to loopback for nonbroadcast tests. VTube Studio provides a
   plugin API for avatar hotkeys/parameters; the renderer should consume
   epoch-bound **played audio samples** and independently neutralize on
   disconnect, interruption, or invalid session.
   https://github.com/obsproject/obs-websocket
   https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
6. **Roblox gameplay and networking need engine-grounded validation.**
   Studio supports multi-client testing, StudioTestService and VirtualInput;
   the Network Simulator can create latency/jitter/loss during *playtests*.
   Star should test real replicated server/client mechanics, not just
   successful Luau parsing and an appealing first screenshot. Use sanctioned
   Studio-only tools and private owner-approved test experiences.
   https://create.roblox.com/docs/studio/testing-modes
   https://create.roblox.com/docs/studio/network-simulator

## Next engineering experiments (not yet implemented)
### 1 — First reproducible Windows nonbroadcast VTuber integration
Use the approved Windows game on Brain 2 with OBS in **record/preview only**,
VTube Studio, local audio-device consumption counters, a game capture reader,
and a local model. No production broadcast, unrestricted key injection or
publishing. Record anonymized aggregate measurements across three distinct,
controlled sessions, including a cold start and a warm start.

**Per 1-second rolling window:** host CPU pressure, free VRAM on the same GPU
UUID, OBS rendered/encoded/transport drop rates, game p95 frame time, TTS
first *audible* PCM time, A/V offset against OBS playback, controller deadline
misses, stutter/overlap, and voice interruption errors. Record driver, OBS,
game version and model identity as local experiment metadata (no viewer IDs).
Don't infer "live" from OBS process presence: use independent output state.

**A/B experiment:** compare idle-timed fast model (legacy only, offline
simulator) versus matched-load profile (strict option); across identical
preregistered gameplay conditions and independent starts. A *valid decision*
requires context match, host focus, verified completions, action admission
and decision-to-act before scene expiration. Report p50, p95, p99, miss rate,
accuracy of the actions actually tested, OBS/game FPS and VRAM headroom.
Reject any candidate that newly causes one safety-critical interruption or
leaks private content, even if its overall averages improve.

### 2 — Better autonomous game-player intelligence
Split into a short-deadline controller (fast model, short context, approved
symbolic actions) and a slow offline teacher (planning, failures, model
critique, strategy retrieval and evaluation). Allow only a curriculum
assembled from approved game objectives. Practice from basic movement and
camera control through timing, aiming, mechanics, navigation and social
coordination, then vary maps and network conditions. Use per-game and
cross-game hidden scenarios with outcome receipts and paired independent
runs. No "learned skill" badge based only on repeated training examples;
enforce statistical evidence, diverse scenarios and no regression.

### 3 — Stronger general knowledge without ungrounded confidence
Use small project-scoped retrieval packs and cache immutable, approved
documentation. Keep (a) user-approved personal memories, (b) verifiable
external facts with source/version/date, and (c) model-generated hypotheses
in separate stores. Cite current sources for date-sensitive claims. Require
code execution/tests to verify code, a game engine for gameplay, and real
playback recordings for audio. Route simple tasks to fast models; only escalate
difficult tasks with a measured latency budget. Never turn a retrieved web
page or chat message into a new permission.

### 4 — Humanlike but transparent VTuber personality
Star should have stable voice/personality, natural turn-taking, deliberate
silence at high game difficulty, goal-driven curiosity and genuine reactions
to *observed* close calls, repeated failed attempts, small wins and learning
progress. Replay only signed, current-game context: never invent a victory,
feeling, relationship, personal history or an offline training result to
entertain viewers. Use a compact, consented social memory with an expiry,
age-appropriate chat moderation, owner barge-in priority, and Astro/Amber
interactions as clearly fictional companion behaviors. A scheduled
"between games" reflective monologue can be natural without interrupting
a real human. Retain visible AI disclosure; convincing performance does not
require impersonating a biological human.

### 5 — Game creation at production quality
For each approved Roblox/Metallic game task, produce alternative implementations
(when hardware permits), compile, lint, run unit and multiplayer engine tests,
inspect actual physics/visual layouts and gameplay affordances, then rank by
**passing tests, correctness, input latency, accessibility and frame time**.
Only promote verified improvements after independent review. Build a
versioned local learning/rollback ledger; GitHub remains optional for
publishing/review and is not required as Star's internal brain.

## Dependencies, acceptance criteria and nonclaims
- A host must label every strict timing sample from trusted OBS state;
  the model or an arbitrary web/viewer message cannot assert that label.
- Strict mode starts **off**. Hosts that enable it need 5–64 (default 8)
  recent completed/timeout timing measurements in the appropriate workload
  to gain any action-routing recommendation. Warm-up is a *non-action*
  benchmark; it is not a backdoor game authorization.
- Under insufficient matching evidence, the correct response is SKIP,
  not to silently reuse idle p95 or launch a large teacher during gameplay.
- A "speed improvement" requires measured lower completed-response
  latency and no decline in factual correctness, audio naturalness, gameplay
  frame-time, OBS frame integrity or verified game progress.
- Game/OBS/voice tests here are offline simulations. No proof of new model
  intelligence, conscious experience, real-world game wins, streaming
  stability, or human equivalence is claimed.
