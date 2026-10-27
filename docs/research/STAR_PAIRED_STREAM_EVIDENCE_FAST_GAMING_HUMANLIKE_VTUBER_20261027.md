# STAR — Paired Speech Evidence, Game Intelligence and a Natural VTuber

Research and implementation note, October 27, 2026.

**Scope:** One actual offline-evaluator change, an adversarial test suite and
source-checked development priorities. None of this establishes greater
model intelligence, faster neural decoding or a live broadcast. New features
remain OFF until an authorized host enables them; hidden evaluations and private
viewer/owner data must not be committed or exposed to the model.

## Why this matters

STAR already has event-driven stream direction, audio-acknowledged avatar
motion, a conversation interruption host, GPU budget and worker quarantine,
signed game results, predictive outcomes, cross-game practice, and an offline
A/B evaluation of conversational streaming. The remaining issue discovered
here was statistical: a handful of terrible baseline speech latencies could
produce a huge apparent p95 gain while most listeners noticed no improvement
or heard the candidate reply **later**.

The previous paired evaluation checked context identity, useful response
coverage, grounding, talk-over, game frame stalls, and p95 latency. It did not
check whether that latency gain was distributed across *individual matched
opportunities*. This iteration closes that evaluation gap.

### Implemented now

The updated offline stream evaluator also:

1. Pairs only audible baseline/candidate utterances for the same reviewed
   opportunity, excluding dropped responses from latency-success samples.
2. Counts individual measurable speedups and slowdowns, discounting differences
   smaller than max(10 milliseconds, 1% of the baseline turn).
3. Requires at least 60% of matched turns to improve, at most 10% to slow, and
   a one-sided exact sign-test p-value below 0.025 on non-tied cases. The
   matched sample floor is max(10, the configured minimum-spoken threshold).
4. Still requires the existing minimum aggregate p95 improvement and all
   quality/grounding/FPS regression checks.
5. Exposes aggregate statistics only; never raw chat, voices or user IDs.
6. Recommends *only independent human review*, never deployment or promotion.

Example: 2 questions improve from 10 seconds to 4 seconds, while the other 18
remain at 1 second. Old aggregate p95 suggests a 60% gain, but 90% of
conversational opportunities did not improve. New paired evidence blocks it.
Another adversarial case shows how a majority of conversations can become
slower while the few largest latency outliers improve.

This quality gate does not establish statistical independence of audit cases.
A future independent evaluation must preregister the case roster, review
grading, treatment order and hardware regime. The sign-test p-value is
descriptive conditional on that case roster, not a causal claim.

## Fresh, verified research and exact relevance

- **October 1, 2026 — Roblox OpenGameEval**: 13 frontier models on 84 curated
  Roblox Studio tasks with executable scene/play checks. Agents inspecting the
  relevant objects before editing generally performed better. Source:
  https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval.
  **Action:** give STAR an inspect -> build -> playtest -> diagnose -> repair
  protocol instead of using completed code as proof of a completed game.
- **April 15, 2026 — Roblox Studio agentic workflows**: built-in Studio MCP
  and Playtest Agent beta expose more plan/build/test automation. Source:
  https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic.
  **Action:** integrate only within owner-approved, private Studio test spaces;
  capture objective pass/fail from trusted game instrumentation.
- **October 20, 2026 — Kyutai Pocket TTS smaller models**: publisher released
  CPU-oriented English models at 18.2M, 6.9M and experimental 1.9M parameters.
  Source: https://kyutai.org/blog/2026-10-20-pocket-tts-small/ and
  https://github.com/kyutai-labs/pocket-tts.
  **Action:** blind-listening and measurable first-audible bake-off versus
  current Star voice. Do not infer local speed/quality from published numbers.
- **2026 — LiveKit adaptive interruption**: contextual audio can differentiate
  conversational backchannels from real interruptions, but local/self-hosted
  usage can depend on cloud inference and its quotas. Source:
  https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/.
  **Action:** retain a private, local VAD/STT fallback; measure false barge-ins
  and forgotten corrections, not only speech latency.
- **2026 — llama.cpp SPEED-Bench**: reports end-to-end server throughput,
  latency, and speculative draft acceptance. Source:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md.
  **Action:** compare serial decoding, n-gram and draft variants on the
  actual available Star models with GPU pressure. Speculation is not
  automatically faster.
- **April 2025 — DreamerV3, Nature**: learned predictive world models
  support multi-domain control. DOI 10.1038/s41586-025-08744-2.
  **Action:** research a small predictive transition model for a single
  private course before proposing heavyweight reinforcement learning.
- **2023 — Voyager**: automatic curriculum, reusable executable skill library,
  iterative verification (https://github.com/MineDojo/Voyager).
  **Action:** turn signed practice into reusable, versioned game behaviors
  and retest those behaviors on unseen levels before declaring transfer.
- **Live2D physics and VTube Studio expressions**: multi-stage pendulums and
  explicit expression hotkeys allow hair, ribbons and expression transitions.
  https://docs.live2d.com/4.2/en/cubism-editor-manual/physical-operation-setting/
  https://github.com/DenchiSoft/VTubeStudio/wiki/Expressions-%28a.k.a.-Stickers-or-Emotes%29.
  **Action:** synchronize eye, face, hand, ribbon and hair cues to actually
  audible speech; avoid fighting physics parameters.

## Proposed infrastructure: intelligence that survives contact with a game

STAR's active Windows game/streaming host should have a **reflex loop**
(frame capture, immediate authorized controller decisions, audio playback,
avatar pose) and a separate **deliberation loop** (language planning, strategic
reasoning, memory retrieval). Offline Brain 1 workers handle research,
benchmarking and self-study; they must not preempt the live game's CPU/GPU
budget. Always reserve capacity until timed-out work truly stops.

For unfamiliar gameplay:

1. Capture a fresh game frame and an allowed game-state observation. Label
   each claim observed, game-reported, or uncertain, with its version/age.
2. Build a bounded, short-horizon plan; precommit a success probability *before*
   dispatch and record which visual transitions would confirm the hypothesis.
3. Revalidate private-game authorization immediately before physical input;
   action plans expire when clocks or focus become unreliable.
4. Use a separate host to score the result, recording a signed practice trial.
   A model answer, arbitrary screenshot, or unsupervised claim is not a win.
5. Compare predicted vs actual outcome. Practice the most miscalibrated
   situation without starving coverage of other curated games.
6. Re-run controls and sealed unseen levels before any claim that the agent
   has actually learned transferable skills.

For game creation, add **four distinct acceptance gates**. Structural: scene
graph has correct dimensions, anchor points, joining walls, no unexpected
object penetration, stable colliders, attached props and stable references.
Functional: spawn -> control -> goals -> checkpoint -> success, including
save/restore and client/server behavior. Visual: multi-angle reference
checks for materials, textures, collisions, lighting, animation rigs, VFX
timings, UI scaling and silhouette. Playability: new-player/bot full routes,
unseen seeds, measured hardware frame-time budgets, recovery after error.

Require each asset/building to declare a planned function, world-space
footprint and valid exceptions for intentional overlap. Do not mistake
per-object validation for the quality of a fully assembled scene.

## Better general knowledge and autonomous Forge

Do not equate a large unvalidated knowledge store with intelligence. Each
knowledge lesson should retain source/version/time, quotation-versus-inference
provenance, independent cross-check, TTL for changing APIs and current facts,
and retrieval safety class. Use more difficult practice problems generated
from actual failures, then evaluate against **unseen** cases and retain
only evidence-backed improvements.

Star Core Forge should remain the source of truth for autonomous development:
local semantic diffs, snapshot/rollback, parallel isolated experiments,
separate verification workers, and owner-readable results. GitHub is optional
for draft public/private code review and releases, not mandatory for thinking
or learning. Do not auto-promote model-generated code merely because its own
unit tests pass; use independent tests, live budget criteria and regression
checks. Resource-aware admission stays on at all times; self-learning features
and Internet research remain OFF by default until approved.

## Believable and playful VTuber design

STAR should sound grounded and expressive, not like a canned emotion machine.
Use her existing original personality and gold/black/indigo mascot; preserve
her gold-tipped twin tails, star clip, playful cat and puppy modes, and
reduced-motion setting. Her conversational memory should contain **verified
actual project activity**. Never invent a human childhood, off-stream
adventures or private facts to seem more human.

A hard game action may call for silence. A verified achievement may warrant a
brief delighted reaction. A conversational acknowledgment ("mm-hm") should
not necessarily cut off a sentence, but a clear viewer/owner interruption
should. Laughter, breaths, blinks, gaze shifts and body motion should follow
content and audio timing, with neutral reset if interrupted. No celebration
animation before the trusted host reports speech audibly played.

Candidate speech engines: test existing route vs Pocket TTS English 18M and
7M on CPU, with the experimental 2M as a speed/quality control. Compare
response intelligibility, listener-rated expressiveness, laughing artifacts,
fidelity of the intended voice, first audio, CPU/VRAM use, sound continuity,
and FPS impact. Never clone a real person's voice without permission.

## Paired benchmark and pilot acceptance plan

- Preregister 40–100 reviewable anonymous cases across quiet chat, technical
  questions, rapid viewer remarks, sudden game danger, genuine interruptions,
  deliberate silences and expressive celebrations.
- Each candidate must face identical game build, scene, model input and
  response opportunity. Alternate routes to reduce hardware/order bias.
- Keep all failures. Use the same local monotonic timing domain for
  event/first-token/first-synthesized/first-*audible* stamps.
- Include game frametime p99 / 1%-low FPS, VRAM peak, speech queue buildup,
  ungrounded claims, audible coverage, talk-over time and blind listener
  judgments in the release report.
- Confirm the existing speech response target of p95 under 900 ms is
  *achievable* on actual hardware before making it a promise; preserve game
  experience, for example no more than 3 FPS regression in 1%-low comparisons.
- Any apparent speed benefit must pass the paired-evidence evaluator added
  here and a **separate independently reproduced Windows host evaluation**.

## Recommended next implementation milestones

**Milestone A:** Connect the new paired quality gate to rehearsal records
with external prerecorded case digests and an independent reviewer. **B:**
Run 8 GB gaming + CPU voice + Live2D stress tests together on Windows. **C:**
Integrate an actually authorized private Studio course with prediction,
action, signed verdict and held-out validation. **D:** Build scene-graph
consistency and complete playable-goal checks for STAR-created Roblox games.
**E:** Develop source-backed general-knowledge practice and verifier-controlled
Forge promotion.

**Exact completion for this branch:** only the evaluator, adversarial tests,
and this research note. No installed TTS engine, no new inference model, no
real-world speedup, no autonomous public-game mastery, no human consciousness,
and no real broadcast are claimed.
