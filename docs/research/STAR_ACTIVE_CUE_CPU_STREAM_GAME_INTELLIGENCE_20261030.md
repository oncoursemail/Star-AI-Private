# STAR: realtime avatar CPU work, verified game intelligence, and natural streaming

Research and implementation note — October 30, 2026. Development only, offline first.

## Executive result

This branch now includes a practical CPU hot-path optimization in the avatar motion
planner. Previously, the planner checked **every** expression cue at **every**
animation frame even after its relevance window elapsed. The new planner walks
a time-ordered, 1.5-second active-cue window. Normal-case motion equations,
cue precedence, limits, and cancellation semantics are unchanged.

This optimization has an algorithmic justification but **no measured full-system
speedup** yet. A microbenchmark and a reference regression suite are supplied
to establish the isolated effect and correctness. Nothing here proves better
model reasoning, higher game FPS, or natural speech.

The immediately preceding CI run also found a timing-sensitive, unrelated
priority-proxy assertion. Client completion can precede the server's final
resumed-cache audit. The test now waits for that actual audit value while
still failing if cache evidence never arrives. **Do not mark CI as passing
until the new GitHub workflow actually finishes.**

## A. Implementation: bounded avatar cue work

Current planner constraints in star/stream_motion.py:

- Maximum 15-second plan, 15/30/60 FPS: at most 901 frame outputs.
- At most 32 ordered expression cues and 1,500 ordered audio envelope samples.
- Cues can affect motion only from their event timestamp through 1.5 seconds
  afterward, inclusively. Future cues must not affect earlier frames.
- Later focus cues override earlier focus cues. Joy/laughter/surprise channels
  have their original max/accumulate behavior.
- A revoked speech plan can halt generation at preflight and every eight frames;
  cancelled work must return no partial rig sequence.

Old hot path: every frame scanned all cues, with an upper bound of
901 * 32 = **28,832 cue visits** in addition to the rest of motion rendering.

New hot path: the two monotonically advancing indices move across each cue
at most once. Per-frame work then visits only currently relevant cues.
The number of cue-window operations is bounded by O(frames + cues + active
cue visits), rather than O(frames * all cues). Dense clusters can still produce
significant active-cue work, but expired and future cues never enter the inner
expression loop.

This is a CPU optimization, **not a claim about the neural model's inference
throughput**. It is most relevant when game, audio and local assistant tasks
compete for CPU time.

New verification:

- tests/test_stream_motion_cue_window.py compares 15/30/60 FPS and
  normal/cat/puppy modes with a reference per-frame full scan.
- The reference checks precise expression, gaze, nod, shoulder and head motion,
  including overlapping cues, exact 1.5-second expiration and future events.
- Existing cancellation and stage tests remain part of the full offline suite.
- scripts/bench_stream_motion_cues.py reports median per-episode time for the
  **cue-selection microkernel only**. It does not benchmark OBS, GPU, TTS,
  avatar renderer, model loading or the entire motion planner.

Run the microbenchmark on the Star streaming PC and compare repeated stable
sessions before and after the commit. Do not optimize solely for a synthetic
microbenchmark if actual gameplay FPS or speech latency worsens.

## B. Highest-value system architecture

### 1. Protect what viewers perceive

Use three independent time scales. On the fast path, game input, game rendering,
audio playback and rig presentation should not wait for generative inference.
On the medium path, a short perceptual summary and a bounded speech proposal
can react to new, verified game events. On the slow path, strong reasoning,
research, indexing, Roblox builds and autonomous study can use residual resources.

Keep these as real host-enforced workloads rather than merely prompting the
model to be fast. Existing StreamBrainGovernor, StreamTelemetry, priority-proxy,
scene-observation gates and StarStage make reasonable enforcement boundaries.

Suggested measured host signals:

| Signal | Decision it supports |
| --- | --- |
| Game frame presentation p95/p99 and 1% low | Suspend vision/inference when game rendering suffers |
| Audio play queue depth and actual device output start | Decide whether a spoken reply is usable |
| Host-measured speech interruption-to-silence | Detect stale queued audio and interruption failures |
| Rig frame freshness and sequence ID | Never animate a superseded utterance |
| CPU runnable pressure and GPU VRAM headroom | Select local model, TTS and observer concurrency |
| Actual end-to-end user-turn-to-audible p50/p95 | Optimize perceived responsiveness, not token count |

Unknown or stale host measurements should not authorize heavier work.
Do not call text-generation arrival “audible”; require an independent audio
path witness, then verify the downstream OBS/recording path separately.

### 2. Give STAR a fast brain and a deliberate brain

Start with one low-latency conversational model and bounded deferred research
rather than putting multiple large models simultaneously on a shared 8 GB GPU.
A small model can route routine speech, but **complex decisions must wait for
verified deeper reasoning**. In a tense game moment, it is better to stay silent
than confidently announce an invented achievement.

On local llama.cpp, benchmark the exact model, quantization, context length,
KV-cache type, partial CPU offload, prompt caching, speculative draft
configuration and concurrency under a **simultaneous game + OBS workload**.
Prompt caching can improve reuse but may change numerical results due to
different batch shapes. Speculative decoding only helps when draft acceptance
and target verification exceed their overhead.

Each candidate needs matched quality tests, not a token-per-second contest.
Hold model hashes, prompts, sampling settings, task roster, hardware load
and warmup policy constant across A/B configurations.

### 3. Learn to play by predicting, acting, and checking

STAR's existing GamePredictionLab, GameplaySkillBank, GameLearningLadder,
GamePortfolioPractice, GamePairedStudy and GameTransferEval already cover
different components of the learning cycle. They should be connected through
one trusted host, not duplicated by another unverified planner.

A controlled training episode:

1. Host identifies a permitted game/version and obtains a truthful state
   observation, without declaring success from a screenshot alone.
2. Agent predicts the next observable outcome of a small, legal action and
   records the prediction before executing anything.
3. A separately authorized game controller acts in a sandbox/test session;
   game-state or server-side checks score the outcome.
4. Trusted host signs evidence and updates *practice* records only.
5. An independent evaluator tests a different, preregistered scenario roster;
   hidden tests and result keys are never exposed to the learning agent.
6. Failures revise the next curriculum challenge. Measured transfer to
   unfamiliar maps/games is more valuable than repeated practice on one seed.

GameWorld's verified game-state approach is an excellent reference: its 34
games and 170 tasks cover navigation, reaction, precision, reasoning and
multi-step play. Its August 2026 fine-control protocol adds a useful test
of more frequent actions. Run only within allowed game interfaces, respecting
each game's rules and platform controls.

### 4. Make complete games, not just code that compiles

Use the existing Studio systems to implement an inspect -> plan -> edit ->
compile -> simulate -> visually review -> repair -> held-out test pipeline.

OpenGameEval's October 1, 2026 benchmark has 84 core Roblox Studio tasks,
executable scene and play-session checks, and separated observation/edit tools.
Its results associate inspecting relevant objects before changes with better
task success. STAR should treat scene inspection and post-edit verification
as normal development steps.

Practical game QA matrix:

- Script correctness: Luau analysis, type checks, runtime errors and security.
- Scene integrity: collisions, attachment points, missing walls, orphaned props,
  anchored components, z-fighting and texture paths.
- Visual quality: screenshot comparisons on fixed camera paths, clear UI
  hierarchy, readable typography, real lighting, animation continuity.
- Playability: spawn, camera, inventory, interaction, checkpoints, wins and
  losses, restart, mobile/keyboard/controller support as appropriate.
- Multiplayer: joins, leaves, server authority, latency, replication, race
  conditions and malicious-client inputs.
- Performance: target device tier, frame times, memory, and network budgets.

Roblox StudioTestService can launch scripted multi-client tests; it is a
candidate for an owner-authorized test farm, not evidence that the current
desktop build already runs such tests.

### 5. Make general knowledge evidence-backed

Knowledge “size” by itself is not intelligence. The useful target is a
low-latency retrieval system with source provenance, freshness, contradictions,
confidence and domain-specific calibration.

Proposed single source-of-truth record: scoped topic identifier, source hash,
license/provenance, extraction date, claimed fact, evidence location, independent
verification status, expiration rule, and rollback parent. Store only
rights-reviewed material. Keep factual citations separate from personality
and fictional character lore.

Use short curated context for common questions, cached project-specific facts
for active Roblox work, and retrieval only where it materially improves
correctness. Rebenchmark after each ingestion against untouched general
knowledge and Roblox holdout questions. Refuse automatic promotion when a
new knowledge bank improves easy recall but worsens unseen cases.

### 6. More natural VTuber delivery without invented human experiences

A credible streamer has variation, timing and attention: quiet concentration
during hard play, unscripted small reactions to actual events, considered replies,
the ability to resume after real interruptions, and a coherent story of what
happened earlier in the stream.

The pipeline should preserve:
- An identity/persona state grounded in genuinely recorded episodes.
- Conversation-aware silence, not mandatory speech every few seconds.
- Distinguishing a viewer's brief “mhm” from a genuine barge-in or correction.
- Coherent gaze/head/shoulder motion, mouth timing from **actual audible
  playback**, a consistent expression palette, and gentle secondary hair motion.
- Respect for viewer attention: avoid repetitive catchphrases, forced laughter,
  or speaking over decisive gameplay moments.
- Clear disclosure that STAR is an AI performer, even when she is charming and
  naturally conversational. Do not invent real memories, emotions or private
  relationships as facts.

Kyutai Pocket TTS 4.0.0 (October 20, 2026) adds small English models at 18M,
7M and experimental 2M scales, with standalone Windows binaries. The 18M
and 7M candidates may move speech synthesis off the gaming GPU. Benchmark
voice identity, intelligibility, pace, listener preference, interruption
behavior and first-audible latency. Do not replace STAR's voice based on
parameter count or synthetic speed alone. Only clone a voice with consent.

LiveKit's documented turn handling highlights a useful tradeoff: preemptive
speech cuts waiting time but wastes computation when cancelled. Its adaptive
interruption handling distinguishes backchannels from true interruptions;
local/offline use and licensing must be verified before adopting any equivalent.

## C. Release-quality acceptance gates

All gates are proposals until measured on actual game/OBS sessions:

1. Full offline Python, React and typing checks green; no skipped mandatory
   tests; PR remains draft until reviewed.
2. Reference expression frames match the legacy per-frame scan across all
   supported FPS and modes; cancelled frames never leak.
3. On the same Windows hardware, motion-CPU microbenchmark shows a reproducible
   advantage in sparse-cue sessions **or** the change is revised/reverted.
   A regression in dense-cue sessions should be quantified, not hidden.
4. Typical game frame-time p95 and 1% lows do not regress by a meaningful
   device-specific threshold; streaming inference never induces starvation.
5. Real OBS rehearsal independently confirms audible TTS, A/V sync, stop/flush
   after interruption and no fake success claims.
6. A preregistered set of unseen games, Roblox tasks and general-knowledge
   questions shows non-regression and actual transfer before “smarter”
   claims are published.
7. Secrets, viewers' personal data, raw recordings and private holdouts stay
   out of this **publicly visible** development repository.

## D. Sources checked October 30, 2026

- llama.cpp server documentation: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
  (continuous batching, prompt cache, speculative decoding, timing).
- Kyutai Pocket TTS v4.0.0, **October 20, 2026**:
  https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.0
- GameWorld project, original report April 8, 2026 and August fine-control
  update: https://github.com/gameworld-project/GameWorld
- OpenGameEval paper, **October 1, 2026**:
  https://arxiv.org/abs/2610.02563
  and official harness: https://github.com/Roblox/open-game-eval
- Roblox StudioTestService documentation:
  https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- LiveKit turn-taking and interruptions:
  https://docs.livekit.io/agents/logic/turns/tuning/
  https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- LiveKit observable voice latency stages:
  https://docs.livekit.io/reference/agents/session-traces/

## What was NOT done

No model weights were trained or changed. No external games were played,
no Discord or Twitch chat was read, no OBS broadcast or recording was made,
no remote machine was benchmarked, no installer was deployed and no generated
code was automatically merged. GitHub checks and Windows performance must
be verified independently.
