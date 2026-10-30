# STAR: Responsive VTuber preemption, real-world performance and game intelligence

**Research and engineering log:** October 30, 2026. **Status:** one narrow
implementation plus an offline test plan; broader integrations remain proposals.

## Current repository evidence

The immediately preceding draft #843 head
928aa70fc68b7a7bb65ce333df58669cd8bf2c6d passed GitHub's complete
"STAR offline checks" workflow (run 41135504310). The previously reported
test failure was therefore repaired. Production Windows audio, OBS, gameplay,
local inference and real avatar timing were **not** exercised by that run.

Source inspection of star/stream_stage.py found that StarStage.motion() held
the stage's RLock while computing up to 15 seconds of animation at up to
60 frames per second. That is bounded but nontrivial CPU work, and a Python
owner-interruption callback calling interrupt_if_current() needed the *same*
lock. An interruption could be delayed until the entire frame computation
finished. This affects perceived turn-taking and the priority of urgent
gameplay over presentation even when average token throughput looks good.

## Implemented change and its exact limits

- Under lock: check the active audible plan and snapshot its small expression
  cue. Release lock before audio-envelope copying, validation and CPU motion
  synthesis. Reacquire lock to verify **the identical live plan object remains
  audible** before returning frames or counting the motion request.
- Reject generated frames for interrupted, completed, disabled or replaced
  plans. Preserve the physical renderer's existing current(plan) check on
  *every dispatched batch*, because caller-side TOCTOU cannot be removed by
  this method alone.
- Two concurrency regressions use a gated deterministic animation function:
  an owner interrupt must finish while generation remains paused; an earlier
  turn must never contribute frames after a new turn takes over.
- A normal-motion test confirms audio-to-mouth frames, error behavior and
  completion accounting are unchanged.

This reduces **stage-lock blocking** for interruptions; it does NOT claim a
measured reduction in LLM latency, wall-clock voice latency, or total CPU
cycles. The Python GIL, host audio device, renderer I/O, and worker priority
can still impact real interruption speed. Those require instrumented hardware
measurements.

## Performance experiments: Star's 8 GB gaming GPU plus second computer

Run bounded matched experiments on each physical machine, recording
hardware/software version, game FPS 1% low, OBS output dropped/lagged frames,
CPU/GPU/VRAM/RAM, response-to-host-audio p50/p95, physical output/decoded
recording synchronization and task correctness. Never use only tokens/sec.

llama.cpp's official SPEED-Bench evaluates speculative decoding throughput,
latency and draft acceptance by workload. Compare with speculative decoding
disabled, warmed stable prompts, matching concurrency, same model/quantization
and context length. Its server supports KV prompt cache reuse, but cache
reuse can alter numeric reproducibility; evaluate paired correctness too.
Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

A sensible workload split is a very low-latency path for game controls and
physical audio; interruptible small-model reaction/voice-turn logic; and a
background pool for document retrieval, large-model planning, practice,
training and asset generation. Defer heavy work during OBS/VRAM/FPS pressure.
The small speech model is not automatically the most natural one: use matched
listening and objective tests before switching.

Kyutai's Pocket TTS 4.0.0 release of October 20, 2026 introduced English
2m, 7m and 18m options plus quantization experiments. Test those against the
existing Star voice on naturalness, warm/cold first audible chunk, laughter,
proper nouns, intelligibility and CPU competition with game simulation;
do not silently swap the established character voice.
- https://github.com/kyutai-labs/pocket-tts/releases

LiveKit's audio turn detector v1-mini can run locally on CPU; end-of-turn
prediction depends on audio prosody as well as pauses. Study it for smarter
listener timing, but protect authenticated owner barge-ins and echo-cleared
source identity in Star's existing TurnTakingGate. Never treat a mere pause
or synthesized laughter as a verified viewer interruption.
- https://docs.livekit.io/agents/logic/turns/turn-detector/

## Gaming intelligence and game-creation evaluation

Use three independently evaluated layers: high-frequency deterministic action
control, vision+state recognition, and slower model strategy. Make each
observed transition/achievement attributable to a host-verified event. For
unfamiliar games: calibrate controls; run a safe local exploration episode;
predict next outcomes; log falsifiable failures; refine policy using signed
practice data; finally score unseen levels with independent holdout outcomes.

GameWorld's 34 games / 170 tasks and outcome-verifiable state scoring help
quantify real gameplay transfer rather than prose claims. The August 2026
fine-control branch is relevant for high-rate movement challenges.
- https://gameworld-project.github.io/
- https://github.com/gameworld-project/GameWorld

For Roblox creation, use a scene-inspect -> edit -> run -> inspect result loop
with executable test checks and explicit physics/layout assertions. Roblox's
October 1 OpenGameEval tested 13 agent models on 84 Studio tasks and observed
that inspection before editing predicts stronger outcomes. Treat its results
as motivating a benchmark, not as a performance claim about Star.
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers

## General knowledge, autonomy and believable streaming

Use query-time source retrieval + version/recency metadata rather than storing
every retrieved answer as timeless truth. Separate owner-reviewed broadcast
facts, private training notes, model-generated hypotheses, and independently
verified gameplay. Provenance must accompany any episode memory used on air.

Star's personality should express quiet concentration, event-specific humor,
responsive conversational timing, small believable eye/head reactions and
mouth motion aligned to actual played audio. She can keep a factual narrative
of prior streams while being explicit that she is an AI, not inventing a human
childhood, sensory experience or game win. Humanlike presentation needs
independent audience listening, real OBS clip examination, and accessibility
testing (including reduced motion). Avoid synthetic engagement loops.

## Acceptance / risks

1. Run the focused offline concurrency tests and the existing stage, avatar,
   playback and interruption tests; then full Python/Ruff/Pyright/React CI at
   the *new commit*.
2. On a private Windows rehearsal, inject a prolonged animation-generation
   workload while an owner interrupt arrives. Measure callback delay, actual
   PCM stop-to-silence, rig-neutralization time, frame drops and stale-frame
   dispatch count. Compare same build before and after with fixed conditions.
3. Keep changes opt-in and unmerged until reviewed. No game control,
   permission escalation, model swap, OBS start, chat send, network listener,
   credentials, private audio or external activity was added.
4. The GitHub repository currently reports public visibility despite the
   word "Private" in its name. Verify visibility before storing proprietary
   code, recordings, keys or viewer data. GitHub is an optional publication
   mirror; Star Core Forge remains the offline-first development authority.

These notes are proposals and reproducible evaluation criteria, not evidence
that Star has acquired human consciousness, superhuman intelligence, game
mastery or human-quality live speech.
