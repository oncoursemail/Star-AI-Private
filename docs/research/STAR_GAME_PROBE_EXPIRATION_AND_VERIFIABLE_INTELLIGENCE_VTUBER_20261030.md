# STAR — recover stalled game-learning probes, then scale verified intelligence
Date: 2026-10-30 | Scope: offline practice control plane, research, and proposed integrations.

## Actual repo finding and implemented correction

The existing `GameMechanicProbeLab` coordinated with `ActivePracticePlanner` but made two assumptions that are false under normal configuration:

1. **Timeout mismatch.** The probe lab waited until 601 seconds after an unanswered practice reservation before retrying. The planner's default reservation expires strictly after **90 seconds** (configurable 10–600). With no result, an offline experiment could wait ~10 minutes despite capacity being available. The fix uses the planner's actual configured TTL. With the default 90s lease, the earliest next reservation can be made at **t+91s rather than t+601s**, a deterministic 6.6x reduction in the *abandoned-ticket recovery interval*. This is NOT a measurement of model inference speed.
2. **Budget mismatch.** `MechanicHypothesis` defaults to a maximum of **36** signed practice trials per arm while `ActivePracticePlanner` defaults to **24**. An inconclusive experiment at 24/24 could never reach 36/36: the planner refused all future tickets while the lab kept asking. The fix screens at the **minimum** of the hypothesis and actual host arm cap; no false preferred arm or mastery claim is permitted when a smaller host cap is below the minimum evidence threshold.

Both settings are exposed as immutable read-only planner properties; no hidden state mutation, new game input, external traffic, tool authorization, production model weights, or broadcasts were added. New regression cases cover the 90s default, 10s customized lease, 24/24 inconclusive default, and 8/8 cap with a 12/arm evidence minimum. No hidden/validation data enters practice scoring.

**Integration check:** An independently signed `GameTrial` remains mandatory for learning credit. Practice still requires explicit owner opt-in, trusted hardware telemetry, enough game FPS, and an independently authorized game-input host. `GameMechanicProbeLab` itself returns only an offline recommendation.

## Highest-impact next Star AI improvements, in priority order

### 1. Make completed *games*, not prompts, the unit of learning
Connect `GamePredictionLab` (prospective prediction), `GameMechanicProbeLab` (a bounded experiment), `GameplaySkillBank` (signed outcome), `GameLearningLadder` (difficulty), and `GameTransferEval` (withheld generalization). Each learning episode should carry a strict scope `game/version/objective/situation/action`, a precommitted success probability, a genuinely independent play result, and a source-backed lesson. Require a new unseen game/version or seed when measuring transfer.

**Why:** GameWorld (Apr–Aug 2026 releases) explicitly separates reactive control, tactical reasoning and long-horizon strategy in 170 verifiable tasks across 34 games; it derives results from game state rather than an AI's own prose. Reproduce comparable no-peeking holdouts on Star's private, approved game testbeds. The project reports a fine-control protocol introduced in Aug 2026. Source: https://github.com/gameworld-project/GameWorld and https://gameworld-bench.github.io/ .

### 2. Make Roblox creation quality executable and visual
Use Roblox's OpenGameEval methodology to measure exploration *before* editing and executable scene/play tests *after* editing. Start with a fixed set of private scenes: disconnected walls, overlapping props, missing collisions, broken spawn flow, wrong rig grips, unreadable HUD, missing material textures, and multiplayer state bugs. Use scene-tree structural checks AND rendered screenshots AND actual client/server test outcomes, not a single VLM beauty score. Keep holdout tasks outside the agent's prompt/memory.

Roblox's OpenGameEval open-source repository (paper Oct 2026) reports **84 curated core tasks**, distinct observation/edit tool spaces, and executable checks; Roblox `StudioTestService` supports controlled multiplayer sessions. Sources: https://github.com/Roblox/open-game-eval and https://create.roblox.com/docs/reference/engine/classes/StudioTestService .

### 3. Increase intelligence without making the 8-GB gaming GPU stutter
Run three independently scheduled loops: (A) fast game movement and rendering; (B) event-driven short speech, vision, and tactical reasoning; (C) slower research, search, practice and Forge experiments. Protect game FPS and audio by requiring fresh host telemetry, budgeted one-shot inference leases, cancellation acknowledgements and real hardware-stop confirmation. Prefer an existing compact CPU path for short chat and reduce needless full-frame visual scans. Use a fully local speed benchmark and reject changes that regress response correctness, p95 audible latency, or game FPS.

Before enabling speculative decoding or a second GPU model, run **paired, warmed, same-hardware** A/B experiments for coding, conversation, game commentary and reference lookup. Compare **first speakable phrase**, completed request latency, p95 game frame time, VRAM, and output correctness, not only token throughput. The official llama.cpp SPEED-Bench covers latency, throughput and draft acceptance: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md . Speculative decoding is not guaranteed to accelerate every workload.

### 4. Learn broader knowledge with verifiable experiences, not memory volume
Keep a provenance-aware retrieval index for product documentation, technical APIs, game mechanics, animation/lighting skills and general knowledge. Retrieval must label **source/time/version**, avoid leaking private viewer or evaluation data, and abstain when evidence is missing. A `Star Core Forge` promotion should require reproducible tests, regression counters, an unseen holdout, and rollback. Store successes AND failures, but avoid repeating expensive reasoning by retrieving previously verified plans and checking applicability first.

EMemBench (Findings of EMNLP, Oct 2026) computes questions and truth from agents' actual game trajectories; it finds spatial recall and induction difficult even with memory. APEX-EM (Findings of EMNLP, Oct 2026) investigates structure-aware procedural/episodic plan reuse with same-backbone comparisons. Sources: https://aclanthology.org/2026.findings-emnlp.905/ and https://aclanthology.org/2026.findings-emnlp.1996/ .

### 5. Natural VTuber behavior: grounded reactions and believable silence
Keep Star's recognizable chibi personality and distinct, expressive voice; coordinate real game events with eyes, lips, eyebrows, head, wavy twin-tail hair, body physics, and a restrained reaction vocabulary. She should notice actual achievements, recover gracefully from mistakes, maintain social context and continuity, and **stay quiet** during difficult gameplay instead of narrating every frame. Avoid invented personal memories: use verified experiences as her stories. A stage cue is advisory until physical audio playback AND output capture are confirmed.

Compare the existing opt-in `StarStage`, `StreamBrainGovernor`, `QuietAttention`, `StreamFocusInbox`, and turn-taking gate against LiveKit's documented local CPU `v1-mini` turn detector. Its VAD requires >=250ms silence. Use turn-based p50/p95 metrics for end-of-turn, LLM first token, first speakable phrase, TTS first byte, actual device output callback, and independent OBS/recording capture. Sources: https://docs.livekit.io/agents/logic/turns/turn-detector/ and https://docs.livekit.io/reference/agents/session-traces/ .

## Concrete acceptance milestones

- **Offline practice:** An abandoned default probe becomes eligible at t+91s, not t+601s; customized 10s TTL becomes eligible at t+11s; 24/24 flat comparison exits as inconclusive; a cap below 12/arm never creates a preferred action. All evidence remains signed, practice-only and unauthorizing.
- **Game learning:** On a curated private testbed, show precommitted predictions improving in Brier score on fresh episodes, and a held-out completion gain across new seeds. Compare against a baseline with the same model, time and hardware budget. Report failures.
- **Game creation:** Compare full playable-game completion and scene-integrity checks across 20+ unseen tasks. Include multiplayer join/leave via Studio tests and negative tests for broken props/collisions. Visual comparisons need human review plus automated screenshots.
- **Streaming:** Run owner-approved private OBS rehearsal: start/stop audio and visual witness, missed reaction counts, genuine player inputs, FPS and end-to-end p50/p95 audible response. Require no phantom spoken memories, no confidential viewer identifiers or fabricated wins.
- **Infrastructure:** Keep Python compile/Ruff, Pyright baseline and full offline pytest green; measure changes against baseline before claiming a speed or intelligence gain. GitHub is an optional publishing mirror; Star Core Forge remains the target local-first system.

This document is research and a proposed experimental program, not evidence that Star has achieved game mastery, model-weight intelligence gains or human-quality live broadcasts. The repository named `Star-AI-Private` is currently publicly visible; publish no credentials, real private recordings or viewer identities.
