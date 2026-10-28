# STAR — Controlled Game Learning, Fast Local Intelligence & Natural Streaming
**Research and implementation review:** October 27, 2026 (America/Chicago)

## Executive summary

Star's existing GameMechanicProbeLab compares actions from signed, observational
PRACTICE aggregates. Those comparisons can guide exploration, but cannot by
themselves distinguish a useful mechanic from easier seeds, player learning,
action selection or unstable initial conditions.

**Implemented in this branch:** star/game_paired_study.py adds a separately
opt-in preregistered, randomized matched-pair offline experiment. For each of
8–64 owner-curated game situations, an authorized host can attempt both
predeclared symbolic actions in secret-balanced AB/BA order. Only exact,
independently signed, host-recorded PRACTICE trials count. Matching initial
game-state fingerprints after a verified reset are mandatory. Incomplete
pairs, mismatched state, out-of-band practice, late results and restarted
experiments cannot manufacture a positive result. No interim statistical
result is returned to the agent.

**Not implemented:** an autonomous game controller, physical game reset
implementation, neural weight learning, mastery, GPU acceleration, OBS
broadcasting or an audio-to-avatar production pipeline. This component is
a bounded experiment planner and auditor, not a game-playing model.

## Why this matters for genuine game-learning intelligence

An AI that succeeds at a jump in 12 practice runs might have learned the
mechanic, encountered easier seeds, or simply become faster at timing
regardless of the chosen maneuver. Repeatedly evaluating easy conditions
can exaggerate learning.

The new study enforces:
- Identical game, version, objective and scenario ID for one trial with
  each of two owner-curated symbolic actions.
- A host-observed and reset starting scene before both actions with the
  same SHA-256 state fingerprint. The Python planner cannot verify reality.
- A host-only HMAC selects AB or BA order for each consecutive two-scenario
  block, ensuring equal first-action exposure within the preregistered set.
- No model-selected arm, early-success stopping, adaptive sample size or
  cherry-picked comparisons.
- The gameplay bank verifies the **exact** host-signed PRACTICE outcome,
  not merely a matching symbolic run ID.
- A one-sided exact matched-pair discordance test after every allocated
  scenario is settled; independent withheld validation is never consulted.
- Dropouts, mismatched resets and unexpected signed practice prevent any
  positive candidate conclusion.

A paired binomial comparison is useful for *exploratory* binary outcomes
under reproducible conditions. It does not eliminate hidden differences
between resets, host observer errors, interference, or questionable study
registration. A promising result still requires genuinely unseen trials.

### Authorized Windows adoption

1. Create isolated Roblox Studio test places with an executable success
   oracle and deterministic scene reset. The trusted adapter must hash
   the relevant pre-action physics/map/character state.
2. Predeclare action IDs, 8–64 even-count scenario IDs, game build and
   sample size **before** practice trials exist in those situations.
3. Enable PairedGameStudy with a private, independent host-only secret.
   The model and viewer chat must never see or control this key or auditor.
4. Under measured spare *offline* capacity, obtain one bounded symbolic
   reservation. No reservation grants game input permission.
5. Have a separately authorized runner execute it; have an independent
   observer assess and sign the exact game outcome; ingest into the
   signed practice ledger.
6. Return the exact trial, original ticket, initial-state digest and host
   reset attestation. Wrong outcomes, stale observations, forged successes,
   unsigned attempts and replays are rejected.
7. After **all** preregistered pairs are settled, release an aggregate
   owner-only report. Positive PRACTICE evidence goes to GameTransferAuditor
   on withheld unfamiliar situations, **not** automatic skill promotion.
8. Abort and discard studies on host restart. Transactional persistent
   resumability would require signed preregistration and atomic recovery.

Run:

    python -m pytest -q tests/test_game_paired_study.py
    python -m pytest -q tests/test_game_mechanic_probe_lab.py tests/test_game_transfer_audit.py
    ruff check star/game_paired_study.py tests/test_game_paired_study.py

Tests are synthetic and cannot certify that a host actually reset the game.

## Research reviewed, with dated sources

### 1. Real engine interaction beats model confidence

**Roblox OpenGameEval, October 1, 2026:** reproducible Roblox Studio sessions
with executable scene and simulated-play checks. The research tested 13
models on 84 curated core tasks. Inspecting relevant game objects before
edits correlated with higher success, not proof of causality.
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

**GameWorld, April 8, 2026:** 34 games and 170 verifiable tasks across runner,
arcade, platformer, puzzle and simulation genres, with large gaps from novice
human play in precise timing, navigation and long-horizon coordination.
- https://gameworld-bench.github.io/
- https://arxiv.org/abs/2604.07429

**Application:** compare short reflex controls separately from longer-term
planning. Measure engine-confirmed objective success, reset determinism,
frame-to-action latency, invalid controls, unseen-scene transfer, sample
efficiency and FPS. Start in authorized Studio Labs, not competitive games.

### 2. More knowledge requires traceable, corrected memory

**BetaMem, October 19, 2026** explores traceable working, spatial, entity,
episodic, experiential and procedural memories, with independently verified
correction. This does not establish Star's own neural intelligence.
- https://arxiv.org/abs/2610.26554

**Application:** every factual or autobiographical digital memory should
have source, time, scope, uncertainty, permission and expiry. Keep separate:
(a) Star's fictional character lore, (b) actual verified streaming/game
events, (c) external research facts with dated provenance, and (d)
uncertain observations. Never invent a real human childhood or claim
consciousness or subjective human experience as verified fact.

A valuable next subsystem is a self-reflection **proposal and correction**
writer. It proposes compact memories, independently checks them against
recorded evidence, admits corrections and measures recall on unseen
episodes without handing the model hidden answers.

### 3. Higher useful intelligence per second, without ruining game FPS

**llama.cpp SPEED-Bench** evaluates category-specific throughput,
latency and speculative decoding acceptance on an actual llama-server.
Speculative techniques can regress if a draft model or n-gram strategy
is poorly matched to the workload. Benchmark instead of assuming.
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

For the planned RTX 4060 8 GB live setup:
- **Reflex lane:** cheap visual novelty signals, deterministic input
  handling, audio/VAD and avatar updates with bounded CPU queues.
- **Conversation lane:** real turn detection, small grounded responses,
  streaming voice generation and one-flight speech cancellation.
- **Deliberation lane:** deeper strategies, coding, source retrieval,
  Best-of-N generate/test; suspend during high game frame time.
- **Study lane:** the new paired trials, model comparisons, background
  experiments and possible fine-tuning only when not broadcasting.

Measure first audible p95, meaningful grounded reply coverage, real
game-frame p95, VRAM peaks, total latency, quality and power, not just
tokens/sec. Stabilize system prompt prefixes for cache hits. CPU/RAM
offload has bandwidth costs; do not promise more memory always means
higher speed.

### 4. Humanlike VTuber behavior is a timing, truth and performance problem

**LiveKit turn tuning:** endpointing, interruption thresholds, false
interruption recovery, preemptive generation and speech gap adjustment
must be measured together. Simply lowering all thresholds makes a
streamer interrupt people or waste CPU/GPU cycles.
- https://docs.livekit.io/agents/logic/turns/tuning/

**Kyutai Pocket TTS, October 2026:** CPU-first English model variants
of 18.2M, 6.9M and 1.9M parameters are worth auditioning. Published
vendor throughput is **not** a measurement on Star's machine.
- https://github.com/kyutai-labs/pocket-tts

**Live2D motion sync** maps audible speech to visemes. VTube Studio
documents extra API permissions for some features. Honor those grants.
- https://docs.live2d.com/en/cubism-editor-manual/motion-sync/
- https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

**Star behavior design:** silence is natural when concentrating. React
briefly to verified successes; use different wording and spontaneous
but grounded humor rather than fixed catchphrases. Let viewers finish,
then resume appropriately. Coordinate eye movements, blinking,
lipsync, expression, head motion, flowing twin-tail physics and
cat/puppy modes, with reduced-motion support and reset on interruption.
Preserve Star's accepted indigo-black and gold chibi appearance,
amber eyes, gold bows and four-point star. Avoid fake personal
memories, spammy screams and unsupported victory claims.

### 5. Acceptance targets (not demonstrated yet)

1. At least 8 preregistered complete matched game scenarios, both
   actions reset to the same initial-state hash, zero missing or
   contaminated pairs before calling a preference exploratory.
2. A separate withheld-game transfer evaluation with an independent
   signed verifier; no leaked validation data or reused scenes.
3. A repeated 30-minute Windows live-game replay with actual capture,
   microphone, TTS, rig renderer and per-frame timing. Measure p95
   game FPS/frame time, voice onset and cancellation.
4. At least 20 paired independently rated streaming opportunities:
   conversational timing, factual grounding, laughter, variation,
   silence, interruption, warmth and zero unauthorized broadcasts.
5. Separate existing Star Core Forge offline tests, rollback, backups,
   safe self-upgrade checks and human review before live deployment.

## Scope, security and owner control

GitHub currently reports Star-AI-Private as **public** despite the name.
No keys, personal recordings, hidden evaluation cases, viewer data or
private experiment seed lists belong in that repository. Keep signing
keys and owner-approved execution separate from model output.

Star Core Forge is the intended local-first self-development platform;
GitHub is optional publication and review. Keep this PR draft and
features **off by default**. The new module is an offline foundation:
measurably superior game-playing intelligence and natural streaming
must be established by real-world tests, not inferred from unit tests.
