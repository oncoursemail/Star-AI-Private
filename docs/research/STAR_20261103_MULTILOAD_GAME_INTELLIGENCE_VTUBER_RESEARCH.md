# STAR AI — Load-Adaptive Game Intelligence & Humanlike VTuber Engineering
**Research and implementation record — November 3, 2026 (US Central)**

## Scope and evidence levels

This iteration adds a real, tested **offline algorithmic experiment** in
`star/game_contended_skill_lab.py`, not a trained model or deployed gameplay
controller. It examines why a timing policy that succeeds with a quiet GPU
can fail when a game, OBS, a voice engine, and a model compete for resources.
There is no new ability to control a game, start a stream, read viewers,
synthesize speech, or promote a skill automatically.

The new module intentionally returns `synthetic_only=true` and all real
authorizations false. Results from seeded toy worlds MUST NOT be accepted
as signed practice evidence by `GameplaySkillBank`. A workload label in this
simulation is *known to the synthetic harness*; any future real-time use
requires a trusted hardware/OBS host to measure, classify, and timestamp
workload state independently of the model, chat, or simulated experiments.

## 1. Implementation: multi-load practice and independent holdout

The preceding timing lab optimized one constant correction against practice
on a lightly loaded simulated PC, then reported the collapse of skill under
additional inference and input-ack latency. This change implements a stronger
evaluation method with three predeclared load profiles:

| Profile | Extra inference time, synthetic | Extra input-ack time, synthetic |
|---|---:|---:|
| `idle` | 0 ms | 0 ms |
| `stream_live` | random 15–45 ms | random 20–45 ms |
| `heavy_contention` | random 30–75 ms | random 35–65 ms |
| `unseen_contention` **(never trained)** | random 90–125 ms | random 75–110 ms |

The correction search is finite and deterministic: [-230, +40] ms in
10-ms increments. The training policy observes workload class and **success
outcomes only**; it cannot inspect a future episode's randomly realized
inference or dispatch penalty. Calibration comes solely from 96 practice
episodes per known class and is frozen before generating 128 new,
independently seeded holdout episodes per class. Each holdout compares
the idle-only frozen correction with the class-specific correction on the
**same exact episodes**, enabling matched improvements/regressions and
an exact paired sign test. The unseen class returns *no recommendation*
rather than silently borrowing a stale idle calibration.

### Reproducible synthetic example

```bash
python -m star.game_contended_skill_lab
pytest -q tests/test_game_contended_skill_lab.py
```

With practice seed `2026110303` and holdout seed `2026110304`,
the first locally reproduced results were:

| Blinded holdout | Idle-calibrated policy | Profile-calibrated policy | Paired improvements/regressions |
|---|---:|---:|---:|
| 128 idle | 96.09% | 96.09% | 0 / 0 |
| 128 simulated streaming | 60.94% | **88.28%** | 37 / 2 |
| 128 simulated heavy contention | 24.22% | **79.69%** | 71 / 0 |
| 128 unseen/untrained load | no licensed route | **128 abstentions** | not scored |

Learned offsets: idle -80ms; streaming -110ms; heavy -120ms.

**Interpretation:** a small context-conditioned policy is better than one
fixed timing constant *for this constructed simulator*. The apparently strong
synthetic rates and p-values are not measured gaming wins, neural intelligence,
inference acceleration, transfer learning, or evidence of working windows
audio/input. The simulator's workload classes are distinct by construction;
production workloads will be noisier and can drift mid-action. Replicate the
experiment under adversarial jitter, new game mechanics, real OBS load, and
independent engine-scored outcomes before considering a real integration.

### Integrity and failure handling

* The policy is immutable after practice; holdout data is not fed back into it.
* Bounded seed/count validation and deterministic per-profile random streams.
* Validated typing, ranges, profile names and dataset labeling.
* Reject incomplete training, unfamiliar profile IDs and mixed holdout types.
* Unknown load => abstention; no fallback to idle when the trusted
  observations are unavailable.
* No input, audio, OBS, model, filesystem writes or network interactions.
* Adversarial tests check future-delay blindness, per-profile matching,
  invalid timings, immutable frozen policies and loss of performance
  under resource contention.

## 2. Hardware observation (not a benchmark)

A **read-only** observation of the connected Windows machine named Main
returned Windows 11 Pro, an NVIDIA RTX 3060 Ti with 8192 MiB VRAM,
and a single `nvidia-smi` sample of 6294 MiB free at 38% GPU utilization.
OBS, Roblox Studio, the Roblox player and local model server processes
were not seen in the narrow process query at inspection time.

**Do not generalize this one-off observation** to continuous free memory,
game FPS, token generation throughput, driver stability, microphone
readiness, or a streaming rehearsal. The current run did not start/alter OBS,
Studio, models, the microphone, or the audio engine.

## 3. What to build next: a real load-aware gaming pipeline

### Reaction path (hard deadlines, bounded cost)

1. Trusted capture host pins the game PID, graphics/frame source,
   clock epoch and observation identity, then timestamps screenshot start
   **and** completion.
2. A small reactive model receives a *recent, relevant* world state and
   emits a structured, bounded action suggestion. Do not allow chat or
   prompt text to substitute for a game-state attestation.
3. Resource scheduler uses real game FPS, GPU utilization/free VRAM,
   model latency p95/p99, OBS QoS, and OS input-ack p95, stratified
   by **measured load conditions**, with freshness/monotonicity checks.
4. Host checks remaining world deadline *after* inference, before and
   after OS dispatch. Unverified or expired output is dropped, not executed.
5. Separately trusted engine evidence confirms what changed after input.
   Keep it distinct from AI self-explanation, from OS key acknowledgement,
   and from the action's causal attribution.

**Integration note:** `GameDeadlineRouter` already has fresh scoped
latency samples and strict live input-ack profiling; `GameActionOutcomeFeedback`
already distinguishes observed progress/loss/unknown. Connect them through
a trusted Windows supervisor only *after* real end-to-end measurements.
This new toy policy must never bypass those gates.

### Tactical path (bounded future simulation)

Cache a rolling topological map, known mechanics, goals, last safe
checkpoint, visible risks and confidence. Use a small action budget and
cheap prediction for most steps; escalate to stronger reasoning on genuine
novelty or repeated failed predictions. Under high GPU pressure, defer
strategic search rather than missing live game/stream deadlines.

### Night-school path (real learning, not simply longer prompts)

* Select game-curriculum tasks from independently measured weak skills.
* Practice on permitted private worlds; record state/action/reward and
  post-action screenshots with signed provenance, split by game and seed.
* Discover game mechanics through experiments that vary only one control
  at a time, compare counterfactual expectations, and store uncertainty.
* Build challenging transfer tasks in **held-out games**, not only new
  seeds of the same simulator. Never use holdout answers to repair the
  candidate during evaluation.
* Use verified successes/failures to improve retrieval examples and
  policy ranking first; consider offline imitation/distillation/LoRA only
  after clean independent datasets, compute budget and clear rollback.
* Evaluate completion rate, time-to-success, first-correct-action
  latency, independent task transfer, recovery after failure, and
  **game + OBS FPS**. Tokens/sec alone is not the objective.

GameWorld (April 8, 2026) includes 34 games/170 tasks with verifiable
game-state success rather than self-assessed completion. GameScaling's
**November 1, 2026 correction** shows that excluding capture, transport,
preprocessing and action overhead materially overstates real-time scores.
Those are the methodological standards to follow.

## 4. Compute and speed plan for an 8 GB GPU

Run **three budgeted lanes** instead of letting every cognitive task race
on the same GPU: (a) deadlines-first game capture/inference/input, (b)
latency-bounded voice and avatar playback, and (c) interruptible offline
reasoning, coding, retrieval and training. Reserve memory for the game
and OBS **before** allocating model KV cache. Never assume that a GGUF
model which fits at a tiny context still fits at 32K or while encoding video.

Prioritized experiments:

1. Benchmark a small **fast-policy** model and a stronger offline teacher
   on actual hardware, with first-audible-speech, game-frame p99, and
   input-ack percentiles; compare accuracy at matched deadlines.
2. Keep Star's stable persona/tool schemas as a cacheable prefix.
   Measure **warm-prefix prefill** and cold-start separately. Never cache
   untrusted viewer chat as privileged instructions.
3. Compare llama.cpp regular decode against n-gram and
   draft-model speculative modes using its SPEED-Bench and task-correctness
   evaluation. Draft overhead and VRAM can make some configurations slower.
4. CPU oriented TTS may avoid GPU contention: Kyutai Pocket TTS
   v4.0.0 (October 20, 2026) added 18M, 7M and experimental 2M families.
   Test intelligibility, emotional range, first-audible latency, steady
   CPU load and game FPS before selecting a voice model.
5. Resource governors should react to actual overloaded OBS/game/voice
   windows, not generic utilization averages: skip speculative/offline
   tasks first, then shorten optional utterances. Never drop required
   shutdown/audio-stop/input-release work.

**A performance win must be a reproducible matched A/B test** with model
quality unchanged, task latency improved, game and OBS FPS protected,
and independent hardware measurements. No such real hardware speedup
is claimed by this PR.

## 5. Making Star a compelling, humanlike AI VTuber

Humanlike *performance* is testable. Human biology or genuine subjective
emotion is not a software setting, and Star should openly identify as AI.

Design a persistent but bounded performer state:

- **Identity:** durable, consensually editable likes, recurring bits,
  relationships and self-corrections, without inventing off-camera memories.
- **Experience:** retain only source-labeled game events, collaborative
  creations and opt-in interactions; expire sensitive viewer context.
- **Turn timing:** reason about *whether* speaking improves the moment.
  Use a conversational floor model, owner barge-in, guest speech, game
  urgency and silence cost—not simply text generation every N seconds.
- **Proactivity:** occasional relevant observations and brief backchannels
  can make interaction fluid. Allow controls for acknowledgment frequency
  and interruption aggressiveness; evaluate overlap/false interruptions.
- **Voice:** realistic pauses and pacing, varied prosody, laughter only
  when situationally grounded, and interruption-safe audio playback.
  Drive mouth/viseme animation from actual PCM consumption instead of
  hypothetical queued TTS timestamps.
- **Avatar:** plausible eye/hand emphasis, expression settling,
  hair physics and reduced-motion option, with emotions expressed as
  character performance rather than false claims of sentience.
- **Social boundaries:** no secret-leaking, credential access from chat,
  unsafe viewer tasks, or implication that an AI is a human person.
  Moderation, consent, rate limiting, and explicit streaming permissions
  remain outside the model.

Microsoft RESPOND (March 2026) demonstrates a useful model of controllable
backchannel intensity and proactive turn claims. LiveKit's adaptive
interruption docs show why VAD spikes need different handling from genuine
viewer corrections; cloud-model behavior/availability is environment
dependent, so do not assume fully offline equivalence. STAR's
`TurnTakingGate`, `StarStage`, `AudibleAvatarSession`,
`StreamEpisodeJournal` and `stream_social_turn_benchmark` are existing
building blocks, but actual Windows audio/OBS integration is unverified.

Evaluate a private, *nonbroadcast* session against a human-reviewed
rubric: first audible response, unintended overlap, acknowledged
corrections, gameplay silence, memory grounding, false interruptions,
avatar-to-audio delay, and naturalness. Do not optimize only for talking
frequency or viewer attention.

## 6. Star as a general creator and researcher

Beyond games and VTubing, expand capability through verifiable tool skills:
Roblox Luau, C#/Rust, Blender/PBR, UI motion, VFX, audio, websites,
research, documentation and data workflows. A skill card should include
inputs, supported tool versions, permissions, tests, failure examples and
rollback; success requires a working artifact, not a plausible answer.

For Roblox specifically, the built-in Studio MCP server introduced
**March 5, 2026** supports inspect/build/playtest loops.
`StudioTestService` supports scripted multi-client tests with up to
eight simulated clients. A verified build agent should inspect the current
data model, produce candidate patches, run Luau analysis and Studio tests,
check screenshots/physics, compare alternatives on identical tasks,
and keep human-approved final release gates.

Keep an internal, offline-first engineering ledger (tested changes,
semantic diffs, rollbacks, experiments, approved lessons), with GitHub as
a publishing/review mirror rather than the only knowledge substrate.

## 7. Highest-utility next experiment

The blocker is still the **physical Windows integration rehearsal**,
not the absence of one more synthetic policy. In a private, nonbroadcast
rehearsal with owner-approved game tools:

1. Start from the read-only Windows capability preflight and pinned process
   identities; never infer game ownership from process names.
2. Collect timed screenshots, host-attested inference completions, OS
   key acknowledgments, actual input-release confirmations, and signed
   engine outcome observations, all from the **same local monotonic epoch**.
3. Capture game FPS, VRAM free, GPU p99 utilization, OBS dropped frames,
   audio callback underruns, and PCM playback cursor. Do not broadcast.
4. Replay the same authorized scenario under quiet, OBS recording, and
   deliberately loaded but safe configurations. Hold out both game seeds
   and complete scenarios.
5. Only after trustworthy profile measurements, consider a separately
   owner-approved integration of a calibration selector with the existing
   `GameDeadlineRouter`. Unknown profile => skip.
6. Follow with separate private speech/viseme/interrupt trials, manually
   review the output, and preserve privacy. Publishing stays disabled.

The current experiment provides a reproducible starting hypothesis.
It cannot replace steps 1–6.

## Primary sources checked

- GameScaling, corrected real-time evaluation (November 1, 2026):
  https://gamescaling.github.io/
- Ouyang et al., *GameWorld* (April 8, 2026):
  https://arxiv.org/abs/2604.07429
- ggml-org llama.cpp SPEED-Bench:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- ggml-org llama.cpp speculative decoding:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Kyutai Pocket TTS release v4.0.0 (October 20, 2026):
  https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.0
- Microsoft Research RESPOND (March 2026):
  https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/
- LiveKit adaptive interruption documentation:
  https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- Roblox built-in Studio MCP announcement (March 5, 2026):
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox StudioTestService:
  https://create.roblox.com/docs/reference/engine/classes/StudioTestService
