# STAR AI — Blind Game-Skill Transfer, Lower-Latency Intelligence and Humanlike VTuber Research
**Research and engineering, 2026-10-27.** Implementation in this branch is a narrow, host-side **blind transfer auditor**. Everything else below is evidence-backed development guidance, not a claim of installed Windows streaming features or increased neural-model intelligence.

## Why this increment matters
STAR now has forecasting, signed practice, fair cross-game curriculum, Studio input gating, and preemptive voice inference infrastructure. However, succeeding at repeatedly rehearsed *known* challenges does not demonstrate that STAR learned a reusable mechanic. A model can memorize a scene/action sequence. The next frontier is identifying skills that generalize to **new versions, unseen levels, or different game engines**.

An independent, preregistered test is more informative than more practice hours. GameWorld (2026-04-08) explicitly studies 34 games / 170 state-verified tasks, noting persistent latency, observation and action-validity problems in generalist game agents: https://arxiv.org/abs/2604.07429 . AI GameStore's NeurIPS 2026 project explicitly asks that evaluation games not be trained on, as doing so contaminates the benchmark: https://aigamestore.org/ .

## Implemented: owner-only blind transfer experiment
New module: `star/game_transfer_audit.py`, building on STAR's independently signed `GameplaySkillBank`.

1. An **owner-curated protocol** maps one already practiced game/version/objective/situation/action to a distinct target scene and action. The host, not the model, asserts semantic similarity; IDs cannot prove two games actually require the same mechanic.
2. The evaluator scope must have **no historical signed trial of any action** before the protocol is registered. Previously played scenes cannot quietly be called unseen.
3. Registrations require at least 12 independent signed source practice outcomes, with a conservative Wilson 95% lower success bound of at least 0.55. Parameters are bounded and irrevocable for that protocol ID.
4. The source success count and denominator are **frozen at registration**, before the target feedback arrives. Later source practice cannot retroactively improve the baseline.
5. Only subsequent, independently signed **validation** outcomes on the predeclared target action contribute to the target report. Practice results do not count as validation. Any post-registration practice on the *target scene*, even a different action, contaminates the holdout and prevents a favorable finding.
6. At least 12 target validation outcomes and a target Wilson lower bound of at least 0.55 are required for the status `bounded_transfer_evidence_for_owner_review`. This is evidence of bounded out-of-sample performance, **not** human-level skill, superiority to a baseline, proof of causal learning, or authorization to play public games.
7. The preregistration ledger persists to SQLite locally, storing only symbolic identifiers, thresholds, frozen counts and an HMAC of the immutable experiment specification and baseline. The host supplies a separate 32+ byte preregistration key at runtime; **no signing secrets, screenshots, viewer IDs or hidden answers** are stored. Owner reports revalidate source signatures and the frozen counts, so late backdated source trials and SQLite protocol tampering fail closed.
8. Signed bank rows are reauthenticated on owner review. Corrupt JSON, changed outcomes, replayed trial metadata and mismatched signatures fail closed. Expired (>30 day) evaluation windows cannot be revived as new evidence.
9. This capability is **OFF by default**, and both registration and audit require a trusted owner's explicit permission. It is not attached to the AI model, public stream API, or practice scheduler. The latter must not use holdout scores to choose rehearsals.

**Limitations:** The test still relies on the game/evaluator host honestly creating *novel* scenes and signing authentic results; HMAC authenticates origin, not game-world truth. Aggregate comparison is observational, not randomized causal proof. Pre-registering multiple candidate targets and reporting only a favorable one biases conclusions; owners should register a fixed pack and disclose all results. Confidence bounds assume approximately independent runs; repeated identical seeds violate that assumption. Independent replay and human spot-checks remain essential.

**Acceptance in offline tests:** owner opt-in, denied duplicate/change, preexisting holdout and other-action exposure, frozen baseline, full clean holdout, failing holdout, insufficient data, post-registration contamination, stale evidence, tampered signatures, persistent reopen, model-free statistics and no validation leakage to practice. These are synthetic signed-trial fixtures, not real gameplay wins.

## What to build next: a reusable mechanic learner
STAR should represent a gameplay skill as:
`(observation features, action family, prerequisites, predicted outcome distribution, known failure modes, game physics context, timing window, evidence provenance)`.

A **private game-play learning episode** should follow these stages:
- Perceive: read video frames and (when authorized) Studio object/collision data. Distinguish UI, player location, camera, controls, objective, and phase. Keep scene-source timestamps and uncertainty.
- Form hypotheses: e.g., is the jump controlled by hold duration, velocity, coyote time or collision radius? Predict the next-state distribution.
- Choose a *safe* diagnostic input in a private test; compare alternative hypotheses while preserving independent holdout scenes. Budget actions and stop on repeated failures.
- Verify: compare predicted trajectory with trusted game-state/log/frame observations. Correct camera and collision assumptions before altering model memory.
- Compress the lesson into a *versioned mechanic card* with tested scope and confidence. No promotion based solely on generated explanation.
- Transfer: hold game seed and layout out of the training channel, vary timing, surfaces and controls, then ask the owner-only auditor whether the model performs in truly new contexts. Archive failures for diagnosis but **never adapt to the fixed holdout**.

A better benchmark plan uses **stratified suites**: 20 private practice layouts, 20 disjoint target layouts, 5 seeds per layout, and separately a genuinely new game/engine when a control mapping exists. Compare an old STAR build to the candidate build using paired randomization. Evaluate completion rate, action count, wall-clock time, predictions, confidence calibration, resets needed, input mistakes, CPU/GPU use and FPS. Use confidence bounds and report all experiments, not just winners.

**Evidence sources**
- GameWorld, April 8, 2026: 34 games, 170 state-verifiable tasks; interface validity and latency are substantial obstacles: https://arxiv.org/abs/2604.07429
- Roblox built-in Studio MCP + automated Playtest Agent, announced March 5, 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- GameDevBench (ICML 2026) benchmarks agent work on 333 tasks in an actual game engine; use executable checks as well as visual review: https://github.com/waynchi/gamedevbench
- AI GameStore: evaluation-only game holdings should not be trained on: https://aigamestore.org/

## More intelligence on an RTX 4060 8GB: route by urgency and evidence
Not every event merits a large LLM call. Split cognition into distinct deadlines:

| Loop | Work | Model/compute policy | Evidence gate |
| --- | --- | --- | --- |
| Reflex (fast) | Dodge warning, focus cue, scene end | finite-state / tiny classifier; no global reasoning | recent trusted frames, offline/private input permit |
| Dialogue | Answer a viewer and respond to interrupts | low-latency route, bounded token limit, preemptive LLM only | complete moderated STT, exact prompt digest and prepared plan |
| Strategist | Build map, discover controls, plan a route, debug game | deeper multimodal model with time budget | replayable traces, calibrated predictions, real Studio tests |
| Night school | Generate harder levels, learn mechanics, build art/code, research | best-of-N parallelism only when resources available and stream OFF | signed results, blind holdouts, rollback and versioned provenance |

**Hardware priority:** game renderer, capture, audio playback and rig all outrank large AI compute while Star is live. GPU inference should be denied under sustained frame-time pressure; a CPU speech route can also hurt FPS by saturating cores, so test *real frame times* and audio under CPU load, not solely GPU percentages.

**Adaptive inference research:** llama.cpp supports prompt-cache reuse and speculative decoding, but a llama.cpp issue documents that speculative decoding can be slower on high-entropy creative content. Decide by **mixed real tasks, first-token latency, tokens/sec, response correctness, wasted speculative tokens, p99 frame time and power**, rather than a single benchmark question:
https://github.com/ggml-org/llama.cpp/issues/23052 .
STAR should preserve its new mixed-prompt integrity canaries: cache reuse must not cause answers to refer to old input.

For local knowledge use versioned, licensed/source-approved engine/API retrieval; memory source attribution; distinct confidence from popularity; expiry schedules; and no arbitrary web-page instruction execution. Test unsupported questions where **abstaining** is correct. Connect lessons to actual tests (Luau compiler, UI screenshot geometry checks, animation timings, physics collision, full level completion), not mere model agreement.

## Humanlike VTuber presence: work from genuine observed experiences
Aim for a believable, playful AI performer—not false claims that she has a biological childhood, feelings proved by science, or experiences she never had. Star can be consistent, curious, expressive, funny and socially attentive while remaining clear she is an AI.

**Conversation orchestration:** process VAD + ASR + endpoint confidence continuously. Allow preemptive *reasoning* only where a worker and game resources are genuinely available. Delay TTS until the final moderated question is confirmed. Cancel and discard drafts when transcripts, scene, viewer priority or chat context changes. LiveKit's turn handling documentation specifically covers false interruptions, adaptive endpointing and preemptive computation:
https://docs.livekit.io/agents/logic/turns/tuning/ .

**Expressive timing:** do not narrate every action. Silence when concentrating is valuable. Produce a 1-2 second reaction after a genuinely verified comeback, laugh at mistakes instead of repeating stock scripted laughs, recover naturally after interruptions, and occasionally ask a viewer a genuine follow-up about the ongoing game. Distinguish owner requests, viewers, background speech and game sounds; never repeat sensitive/private owner context on stream.

**Avatar motion:** animate Star's established chibi design: indigo-black twin tails with warm gold tips and ribbons, a small four-point star clip, amber-gold eyes, black-and-gold dress, rounded hands and black boots. Drive mouth shapes and jaw motion from the *actual audible PCM*; tune eye focus, eyelid openness, pupil motion, slow breathing, head/body counter-motion, pose transitions, hair inertia and lag, subtle boot/body grounding. Prefer a layered animator with priority `barge-in > speech sync > emotional reaction > idle` and a reduced-motion mode. Do not over-animate her hair or create unnatural randomized twitches.

Live2D supplies standardized mouth, brow, eye, face, sway and hair-physics parameters:
https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/ .
NVIDIA's June 2026 DyaPlex research explores a full-duplex speech-motion model; it is relevant inspiration for synchronized dialogue/gestures, **not** something to claim can be run at live 4060 speed without benchmarking:
https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/ .
SIGGRAPH 2026 EchoAvatar explores real-time audio-stream-driven avatar motion:
https://robinwitch.github.io/EchoAvatar-Page/ .

**Speech candidates, not integrated:** Kyutai Pocket TTS is designed for CPU speech; Supertonic 3's public demonstration describes a 99M-parameter ONNX CPU model and an RTF of 0.20 on its **own** 16-thread reference system. Neither is a measured STAR result and neither should be selected based on demo clips alone:
https://kyutai.org/next/tts/ and https://supertonic3.github.io/ .
A/B human-rated voice samples for emotional transitions, game vocabulary, pronunciation, laughter and breath placement. Treat consent and voice cloning rights as product requirements.

**Persona continuity:** keep separate private owner memory, stream-public episode memory, and fictional character lore. Persist verified created artwork, levels, mistakes, accomplishments and recurring jokes as dated episodes. Her affectionate character behavior may be playful and persistent without pretending to have lived real human memories.

## Deployment and measurements
On Star's future authorized Windows gaming PC, run three independent, paired tests:
1. **Game transfer:** same model version + source practice; blind new level or game variants signed by a genuinely independent evaluator. Report *all* preregistered protocols and Wilson bounds.
2. **Streaming:** one baseline without preemptive LLM versus preview-eligible route, at least 40 different randomized questions across real gameplay states. Record first-audible response p50/p95, premature audio (must be zero), misrecognized-turn rate, interruption recoveries, 1%-low FPS and CPU/GPU peaks.
3. **VTuber impression:** blinded viewer ratings comparing Star's genuinely grounded timing/avatar motion to a scripted baseline. Evaluate coherence, originality, interruption courtesy, laugh timing, character consistency and how often she makes unsupported claims about the game.

**Promotion rule:** no performance claim or automatic update merely from synthetic unit tests. Require improvement on held-out tasks, no latency/FPS/quality regressions, offline rollback tests, and owner review. The local Star Core Forge remains the true development/versioning system; GitHub is a draft-review mirror. This repository currently appears **public** despite its name `Star-AI-Private`; commit no secrets, private memories, viewer logs, model keys or held-out challenge answers.

## Next engineering priorities
1. Connect owner preregistration to *real* Brain 2 Windows Studio evaluator sessions and external trial signatures.
2. Instrument actual mixed-model and CPU TTS A/B trials during a **private OBS rehearsal** on the intended hardware.
3. Add phase-aware avatar/audio output tracing (first audible PCM, aligned mouth parameter, hair sway, on-screen motion, interrupt stop).
4. Add game/engine skill cards with explicit transfer scopes and genuine novel scenario generators; hold back independent seeds.
5. Launch opt-in general-knowledge benchmarks with truth maintenance and abstention tests; only successful trials graduate into reusable lessons.
