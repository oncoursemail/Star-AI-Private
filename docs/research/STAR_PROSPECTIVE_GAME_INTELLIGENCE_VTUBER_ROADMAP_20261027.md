# STAR Intelligence — Prospective Game Foresight, Faster Local Thinking, and Natural VTubing
**Research checkpoint:** 2026-10-27 · **Status:** tested local coordination prototype, not deployed gaming/streaming intelligence

## Executive finding

Previous Star components could select offline game practice, send a bounded Studio
input, collect an independent image transition, and record a signer-verified win or
loss. That loop still lacks a **pre-action prediction**: when Star fails, did the
model *expect* to succeed? Without that, the system cannot distinguish poor
mechanic understanding from unlucky but well-calibrated behavior. And an LLM's
self-reported confidence is not evidence that it understands the game.

This update adds a local-first prospective forecasting layer:

1. An owner-enabled local host connects a specific model version, verified
   curriculum reservation and private-Studio runner.
2. A model proposes the already-curated action plus an optional integer
   probability of accomplishing the immediate objective.
3. Star precommits that probability **before the physical game input**.
   The forecast is immutable and scoped to the random run ID, game, version,
   objective, situation, action, and model version.
4. The existing trusted Studio input path is unchanged. When a real independent
   game evaluator records a signed PRACTICE verdict, the lab verifies that exact
   stored verdict with GameplaySkillBank (never from the LLM or from screenshots
   alone) before scoring the prediction.
5. A bounded SQLite ledger computes proper Brier scores and five-bin
   calibration errors, per model version / game version. After enough *past*
   prospective trials, it can suggest a shrinkage-adjusted probability **for
   future offline proposals**; this is reviewable advice, not autonomy or a
   hidden-test score.

No weights are changed. This is calibrated metacognition / experimental
infrastructure, not evidence of general intelligence improvement or better
gameplay success. Genuine improvement must be shown by forward-time A/B
evaluation, blinded unseen game versions and independent held-out scoring.

## New code / interface

- `star/game_prediction_lab.py`: `GameForecast`, `GamePredictionLab`,
  `CalibrationReport`, `ForecastAdvice`. SQLite persistence is optional,
  default in-memory. Default OFF, 64 open forecasts and 20,000 rows maximum,
  short-lived outcomes and immutable run IDs.
- `star/studio_practice_runner.py`: optional
  `PracticeProposal.success_probability_bps`. Untrusted confidence **cannot**
  become a keypress, override the curriculum or make a failed attempt succeed.
- `star/portfolio_studio_bridge.py`: optional trusted forecast-lab and
  model-version binding. Precommits the proposal in the pre-input callback;
  resolves it only after a legitimate signer-verified Studio outcome. Old
  behavior remains unchanged when no forecast lab is supplied.
- `tests/test_game_prediction_lab.py` and expanded portfolio integration tests:
  wrong/unsigned results, signed failures vs claimed wins, holdout protection,
  replay, owner-disable, delayed results, duplicate prediction, malformed
  probabilities, full in-memory Studio loop and persistent restart.

### Trust and resource boundaries

- Do not expose the independent bank, signing keys or forecast-ledger SQL as a
  model-facing tool. The model only submits the scalar estimate and permitted
  action to a trusted host.
- Prediction is before action, not after output inspection. Any unverified,
  late, forged, non-practice or wrong-episode data is rejected.
- No chat history, viewer identifiers, screenshots, audio, transcripts,
  authentication tokens, hidden test answers or validation data are stored.
- Predictions are **not** evidence of gameplay success or a game permission.
- The host must continue enforcing private Studio focus, live authorization,
  physical key release, worker stop, game FPS and OBS priority.
- SQLite is a local diagnostic ledger; back it up and protect its filesystem.
  An independent signature authenticates the stored game observation's origin
  but cannot guarantee the external scorer itself is correct.
- If a forecast cannot be recorded, gameplay still relies on the existing
  independent authorization; forecasting never becomes a hard game dependency.

## Research: what should make Star meaningfully more capable?

### 1. Prediction-error-directed learning

World-model methods explicitly learn action consequences rather than relying
on the generator's plausible narration. DreamerV3 (Nature, 2025-04-02)
demonstrated model-based RL across 150+ control tasks using imagined future
states; that result DOES NOT mean an 8 GB VRAM local Star can run DreamerV3
training during a game. Begin with the cheaper prospective binary outcome
estimates here. Next build a *structured transition contract* for each game:

- Before: independently measured state tags, position/velocity buckets, nearby
  obstacles, objective progress, available inputs, version/build hash.
- Proposed action: one authorized symbolic action plus duration cap.
- Predicted: objective-success probability and up to three finite,
  observable next-state changes (without copying validation answers).
- After: independently measured game-state changes and signed objective result.
- Learn: update the skill library only on signed practice outcomes; separate
  proposed hypotheses from verified and disproved facts.
- Generalize: evaluate on disjoint levels, unseen seeds, unseen game versions
  and then unseen games. Compare improvement by **game**, not only total wins.

The 2024 TMLR Voyager study provides the curriculum/skill-library/error-feedback
pattern; it is evidence for a design direction, not a directly reusable
Roblox/Windows gaming solution.

### 2. Game creation: scene inspection before writing

OpenGameEval, published 2026-10-01 (arXiv 2610.02563), reports 13 frontier
models on 84 manually curated Roblox Studio core tasks, with 16 attempts per
task. The best single-attempt pass rate was 51.7%; six tasks defeated every
evaluated model. In task- and model-matched analyses, inspecting all relevant
objects before edits was associated with +13.4 percentage points on scene-only
tasks and +9.8 points on script-only tasks, compared with inspecting none.
Those are correlations **within that benchmark**, not a promised Star gain.

Use Roblox Studio's built-in MCP and playtest-agent capabilities (announced
March–April 2026) to build an executable, private, repeatable quality gate:

- **Building:** snap/contact graphs; no missing walls, floating props, z-fight
  surfaces, unintended overlaps, extreme scale mismatches, disconnected doors
  or broken navigation.
- **UI:** native Roblox editability, hierarchy / focus / safe area, consistent
  spacing and type, gamepad navigation, long-text and narrow-screen tests.
  A VLM's subjective 'looks good' score cannot replace pixel/geometry checks.
- **Animation:** rig bone hierarchy, normalized transforms, grounded feet,
  hand grip, frame-accurate transitions, jitter/penetration, hair physics.
- **Effects:** screen coverage, particle lifetime/count, transparency order,
  legibility and GPU frame cost at realistic crowds.
- **Gameplay:** independent objective completion, collisions, movement
  responsiveness, multiplayer synchronization and negative tests.
- **Design:** retrieval of licensed reference patterns, controlled A/B
  review and owner-approved creative direction; do not copy other games'
  copyrighted assets or present generated art as human-made.

Star can prototype multiple candidates and test the strongest, but only a
blind, held-out benchmark can establish superior build quality.

### 3. Real-time performance on an 8 GB GPU

The correct architecture is **two speed paths**, not a giant model trying to
handle every 16 ms frame. A tiny low-latency controller reacts to trusted
signals; heavier vision and strategic reasoning run on sparse observations
and stop or defer when frame time or speech queue worsens.

Benchmark candidate optimizations *one at a time*:

| Candidate | When to experiment | Failure / rejection signal |
| --- | --- | --- |
| Smaller quantized local routing model | short chat/game decisions | higher invalid-command or hallucination rates |
| Persistent KV/prompt prefix cache | repeated persona/skill context | stale facts, cache mismatch, RAM exhaustion |
| llama.cpp n-gram or draft speculative decoding | repetitive code/replies | p95 latency or first-audible speech increases |
| CPU Pocket TTS (Kyutai 2026-10 v4.0.1) | streamer GPU pressure | robotic delivery, click/pop, worse p95 speech |
| Sparse vision + frame-diff selection | continuous gaming | missed hazards, stale images or extra CPU capture cost |
| Background multi-agent generate/verify | owner-approved offline game builds | frame drops, memory contention, unverified success claims |

Use llama.cpp's SPEED-Bench with fixed prompts/model build and paired
baseline/speculative runs, not cherry-picked average tokens/sec. Log p50/p95
time-to-first-token, p95 spoken-audio onset, speech queue lag, game frame
p1 FPS, VRAM high-water mark, and *verified task accuracy*. Reject an
optimization if it makes any critical real-time criterion worse. On the
dedicated PC, run heavy knowledge practice and video work only while off-stream.

### 4. Natural and engaging VTuber personality

Star's desired expressive identity (gold/black mascot, distinct emotional
expressions, cat/dog play modes, hair movement, personal creative interests)
can be implemented as **consistent AI character behavior** without claiming
literal human memories or consciousness.

A believable streaming pipeline should include:

- **Attention:** preferentially notice real game hazards over chat chatter.
  Speak at natural breaks, celebrate genuinely new milestones, sometimes stay
  silent, and resume a question after the intense section ends.
- **Interruptions:** echo cancellation, VAD and turn detection plus a separate
  authentication path for owner interruption. Treat 'mm-hmm', coughs, noisy
  games and unconfirmed background speech differently from real questions.
  LiveKit's 2026 guidance offers dynamic endpointing and adaptive
  interruption; local variants need latency tests and opt-in.
- **Speech:** punctuation/prosody plans, expressive but not overused laughter,
  small nonverbal backchannels, natural breath/pause timing, repeat suppression,
  style consistency across voices, and no speech faster than avatar/audio
  playback can deliver.
- **Animation:** synchronize *actual audible* phonemes/timing to Live2D mouth,
  eyes, ears, ribbons, blinking, body pose, physics and reactive emotes. No
  'she already spoke' state merely because TTS text was generated. Respect
  reduced motion and prevent mismatched body parts during rapid game events.
- **Social memory:** store opt-in, relevant summaries, viewer preferences and
  creator/community boundaries; do not manufacture shared experiences or reveal
  personal information. Moderation precedes chat text reaching models.
- **Personality:** stable fictional birthday/lore, authentic running projects,
  playful comedy, autonomous hobby scheduling, distinct cat/puppy modes. Keep
  the audience informed she is AI; natural performance is not deception.
- **Livestream reliability:** independent restart/reconnect watchdog, bounded
  queues, audio flush confirmations, session-safe events, muted fallback if
  streams stall, safe STOP and audit trails, and offline replay harnesses.

Evaluation must include blinded human listening panels, games never seen by
Star, end-to-end timing traces and forced interruption trials. 'Sounds human'
must be measured rather than claimed from a text sample.

### 5. General knowledge, autonomy and local Forge

Expand topics beyond Roblox: everyday science, mathematics, languages,
history, sound design, practical engineering, social conversation and safe
online research. Use source dates, citations, a credibility score and
versioning; organize factual claims separately from hypotheses, fiction
and viewer anecdotes. Verify knowledge with fresh questions on **unseen**
sources; spaced practice can schedule reviews but does not itself
update model weights.

Star Core Forge should own local branches, semantic diffs, deterministic
tests, adversarial challenges, regression dashboards, power-loss recovery,
rollbacks and permission scopes. GitHub is optional as a publishing/review
mirror rather than the brain's required runtime. Do not merge or deploy
experimental self-modification without demonstrated test and rollback health.

## Recommended next experiment

1. Keep the currently implemented prediction lab OFF in production.
2. On a private Windows Studio test machine, have an allowed local model issue
   probability estimates for 100+ varied task attempts across multiple games.
3. Use independent before/after visual+engine scoring, fixed action bounds,
   actual key-up watchdog, precommitted chance and append-only evidence.
4. Check Brier/ECE by game + version + model before and after prospective
   calibration, with chronological train/validation boundaries.
5. Measure gameplay success *separately* from calibration improvements.
   Stronger estimation alone does not equal stronger control policy.
6. Verify streaming speech p95 and game FPS with lab on/off, then keep only
   objectively beneficial changes.
7. Feed scored prediction errors into a reviewable skill curriculum. Promote
   new skills only after held-out success on fresh seeds and versions.

## Sources checked (research, not installation claims)

- Hafner et al., *Mastering diverse control tasks through world models*,
  Nature, 2025-04-02: https://www.nature.com/articles/s41586-025-08744-2
- Wang et al., *Voyager*, TMLR 2024:
  https://mlanthology.org/tmlr/2024/wang2024tmlr-voyager/
- Turkel et al., *OpenGameEval*, published 2026-10-01:
  https://arxiv.org/abs/2610.02563
- Roblox Studio going agentic, announced 2026-04-15:
  https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- Roblox Studio MCP/playtest beta, 2026-04-09:
  https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- LiveKit 2026 turns/interruptions:
  https://docs.livekit.io/reference/agents/turn-handling-options/
- llama.cpp speculative decoding and SPEED-Bench:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Kyutai Pocket TTS, v4.0.0 2026-10-20 / v4.0.1 2026-10-21:
  https://github.com/kyutai-labs/pocket-tts/releases
- VTube Studio API documentation:
  https://github.com/DenchiSoft/VTubeStudio
- Scikit-learn probabilistic Brier scoring documentation:
  https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html

**Deployment truth:** all implementation tests use simulated locally supplied
game/visual/evaluator components. No Windows Studio test, game-playing mastery
benchmark, model weight training, real VTuber broadcast or 8 GB GPU speed
measurement is demonstrated here.
