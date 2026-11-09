# Star AI: Single-flight speech admission, real-time gaming, and verified VTuber intelligence
**Research date:** 2026-11-08 (US Central). **Implementation branch:** \`feat/star-natural-turn-single-flight-20261108-auto174\`.
**Relationship:** Stacked on draft PR #1080; no changes to production \`main\`. Proposals below are not claims of deployed abilities.

## 1. Concrete bottleneck fixed in this patch

Before this update, \`NaturalTurnBridge.advise()\` could return a fresh \`prepare\` proposal for the same
queued event on *every* safe host polling tick. The bridge treats only the newest intent as valid.
A host that dispatches each \`prepare\` to a separate TTS worker could therefore launch many
redundant syntheses; the old responses become invalid even if the expensive work finishes.
That creates avoidable CPU/GPU contention during game + OBS + inference and can make speech
feel delayed or mechanically interrupted. This is a **scheduling inefficiency**, not a
change to a neural model.

**Implemented opt-in:** \`NaturalTurnBridge(single_flight_tts=True, preparation_lease_ms=8000)\`.

- First safe poll proposes exactly one non-executing \`SpeechIntent\`. Repeated safe polls return
  \`hold/tts_preparation_in_flight\`, never a duplicate start request. No model or audio worker
  is launched in this module.
- The host can provide an explicitly bounded **250–15,000 ms** lease. The 8-second default is
  a timeout for an unstarted *preparation*, not an automatic speech authorization.
- If a preparation stalls, the next safe, VAD-attested host poll may issue a new ticket while
  the underlying event is still fresh. A stale ticket cannot acknowledge the replacement.
- Independently observed owner speech, critical gameplay, unhealthy output, stale/invalid VAD,
  or degraded resource advice revokes the pending preparation. Important new danger and owner
  events, as well as genuine viewer questions ahead of optional chatter, preempt unstarted TTS.
- The existing identity-bound \`complete(intent, host_confirmed_spoken=...)\` is retained.
  Only real host-confirmed audible playback spends the director's speaking cooldown.
- No new network, game control, microphone, chat, OBS streaming, broadcast or audio authority.
  **Default remains OFF.** Existing callers and legacy multiple-proposal behavior are unchanged.
- Only a numerical \`single_flight_coalesced\` counter is exposed while opt-in is configured;
  neither transcripts nor speaker IDs are exposed.

The test suite covers burst polling, renewal after a timed-out preparation, stale VAD,
owner/game urgency, viewer precedence, load pressure, shutdown, ticket replay rejection,
and strict config validation. These are **offline deterministic tests**, not evidence of
higher inference tokens/s, lower GPU load, or improved human-rated naturalness.

## 2. Independent findings and why they affect the architecture

| Published | Independent source | Practical consequence for Star |
|---|---|---|
| 2026-10-27 | [Gym-Anything-RT (arXiv:2610.37567)](https://arxiv.org/abs/2610.37567) | Across 100 generated minigames, real-time interaction lags paused execution sharply. Separate subsecond reaction control from deliberative planning and measure both on clock-moving environments. The benchmark's model scores do not predict Star's local GPU performance. |
| 2026-04-08 | [GameWorld (arXiv:2604.07429)](https://arxiv.org/abs/2604.07429) | Use instrumented outcome checks and reproducible game-state metrics, not self-reported success or screenshot plausibility. Its 34 games / 170 tasks are potential **evaluation inspiration**, not a drop-in Star integration. |
| 2026-10-01 | [Roblox OpenGameEval (arXiv:2610.02563)](https://arxiv.org/abs/2610.02563), [source](https://github.com/Roblox/open-game-eval) | 84 reproducible Studio tasks, scene/play checks, observation-before-edit signals. Add scene inspection + isolated playtest verification before Star publishes game code. It evaluates 13 frontier models; not Star's measured score. |
| 2026-03-03 | [Proact-VL (arXiv:2603.03447)](https://arxiv.org/abs/2603.03447) | Proactive AI gaming companions must decide **when** and **how much** to speak. A silent interval is often better than an invented joke. Evaluate commentary timing and factual grounding separately. |
| 2026-08-13 | [VoiceChat-TTS (arXiv:2608.13831)](https://arxiv.org/abs/2608.13831) | Streaming text-token speech, interruption controls and silence generation are relevant architectural patterns. They have **not** been integrated or tested on the host. |
| 2026-04-19 | [EmbodiedHead (arXiv:2604.17211)](https://arxiv.org/abs/2604.17211) | Distinguish avatar listening from speaking; suppress fake mouth movement during silence. Compare low-cost rig-parameter animation against expensive generative facial animation on the actual 8 GB GPU. |
| 2026-11-05 | [StrataFlux (arXiv:2611.08363)](https://arxiv.org/abs/2611.08363) | Selective precision streaming is interesting for quantized inference, but reported numbers are on other GPUs/models. Treat this as a research reproduction, **not** a practical RTX 4060 speed claim or a dependency to add immediately. |
| Current | [Roblox Studio MCP Open Cloud docs](https://create.roblox.com/docs/studio/mcp-open-cloud) | Grant narrow per-game permissions for asset/import/test workflows; never give model-origin chat messages direct Open Cloud authority. |

### Research interpretation, not promised gains

A local game + OBS + speech stack needs lower **end-to-end response latency**, fewer duplicate
inferences, fewer stale observations, and better allocation of the same VRAM. Doubling tokens/s
is irrelevant if an already moved game target is acted on, or if speech monopolizes frame time.
Conversely, fast low-quality commentary that hallucinates a victory hurts audience trust.
Use **quality-preserving paired trials**, not one aggregate "intelligence" number.

## 3. Proposed three-speed generalist learning architecture (not implemented here)

1. **Reflex lane (bounded wall-clock):** native input/capture adapters generate trusted, fresh
   game evidence; a small reactive policy can act on approved game contexts only. Reject stale
   observation/action pairs; measure actual game-state transitions. This lane must not block
   on narration, an enormous chat context, or online searches.
2. **Tactics lane (hundreds of ms to seconds):** retrieve current objective, map geometry,
   nearby threats and prior verified tactics; propose several actions; use a cheap validator
   and optional planner. Explicit deadlines prevent a late "good" tactic from overriding a
   safe immediate reaction. Source and model confidence are not equivalent.
3. **Practice lane (offline or approved private sessions):** paired mechanic experiments,
   curriculum difficulty, failure replay, held-out transfer evaluation, and regression
   checks. A tactic may enter the reusable skill bank only after independently witnessed
   outcomes and at least one held-out evaluation. Hidden validation sets must never feed
   on-air narration or self-training hints.

**Persistent knowledge hierarchy:** (a) source-dated documentary facts with URL + revision,
(b) reproducible procedural recipes with run artefacts, (c) signed gameplay experience with
game/version/objective and scope, (d) subjective audience/preferences with opt-in retention,
(e) hypotheses that remain explicitly unverified. Retrieval should surface *why* a claim is
trusted; stale API docs and bad lessons must expire or be superseded. A self-critique alone is
not a truth oracle. Use judge disagreement, runnable tests and host-attested observations.

## 4. What "more human-like" should mean operationally

Keep Star openly identified as an AI streamer. Naturalness comes from **timing**, grounded
shared experiences, expressive continuity and respectful conversation—not pretending to be
biologically human or falsely claiming subjective memories.

- **Conversation:** listen/acknowledge, wait for the end of another person's turn, allow
  interruption, answer specific chat questions selectively, occasionally leave meaningful
  silence, and avoid announcing every tiny game action.
- **Emotion-like performance:** map genuinely observed local events to a bounded expressive
  state (curiosity, focus, surprise, joy, frustration), decaying to neutral instead of
  sticking in forced excitement. Use rig controls with fallback to neutral on uncertainty.
- **Voice:** maintain stable voice identity; align phonemes and mouth shapes to *physical
  audible* output, not to text generation time. Brief breaths/laughter are optional
  performative cues, not proof of internal human emotions. Monitor clipping, captions,
  turn latency and actual playout acknowledgements.
- **Audience:** maintain short conversation context and user-approved, privacy-conscious
  long-term recollections. Never narrate private IDs, telemetry signatures, inaccessible
  game state, hidden test labels or claims from untrusted chat as observed fact.
- **Personality:** consistent preferences for types of games and art; reference only real
  achievements supported by verified sessions. Choose creative ideas independently in
  offline rehearsal while keeping external interactions, spending and broadcasting within
  their separately granted host scopes.

Use a private audience-panel evaluation with randomized blind clips: natural turn timing,
relevance, overtalk count, accurate event references, expressiveness and avatar/voice
synchronization. Compare to current Star build and a silent baseline. Subjective "human-like"
ratings alone must **not** substitute for verified game outcomes and safety checks.

## 5. Hardware-level experiments on the actual 8 GB RTX 4060

Do not copy a model's reported tokens/sec from RTX 5090/H200 into an RTX 4060 projection.
Reserve headroom for the game render process and OBS; use live GPU-memory occupancy and
frame-time observations to admit optional model/TTS work. Benchmark a **fast local reaction
model** and a **stronger offline reasoning model** separately. Candidates to evaluate, not
automatic installations:

- Same prompt/quality set at two or three quantization/KV configurations; compare
  p50/p95 time to first *useful* token, prefill, decode and peak VRAM, including 8K/16K
  context. Long context means bigger KV and slower decisions; retrieve instead of
  blindly appending everything.
- On/off speculative decoding with a small draft and actual acceptance-rate telemetry.
  Revert when throughput or GPU headroom regresses.
- CPU vs GPU TTS with actual first-audible sample, CPU contention, output stability,
  playback interruption and avatar-sync distributions. No model vendor speed guarantee.
- Single-flight on/off in matched deterministic replay, holding producer and polling
  cadence constant. Measure unique synthesis starts, wasted tokens, peak concurrent
  workers, game p95/p99 frame time, OBS losses and commentary onset.
- Cache repeated project docs and stable prompts with explicit version/invalidation;
  never cache secrets in public logs or share per-user private KV contexts.

## 6. Measurable acceptance gates

| Trial | Evidence required | Pass condition for enabling |
|---|---|---|
| Offline single-flight | Repeat 30 safe polls against one pending event | At most one \`prepare\` before valid completion/timeout; no duplicate TTS launch requests. |
| Cancellation/priority | Owner barge-in, danger, authentic viewer question, telemetry pressure, VAD loss | Revoke obsolete unstarted tickets; no stale completion accepted; physical audio still gated elsewhere. |
| Recovery | Worker timeout with source event still valid | Only fresh quiet proof + healthy resources can create replacement; disabled session never self-restarts. |
| 8GB load | At least 30 min private OBS recording with game + models + avatar | No material regression in p95/p99 game frame time, OBS loss or free VRAM; measure baseline. |
| Streaming naturalness | Blind matched human evaluation and audited real event receipts | Better relevance/timing/over-talk with **zero fabricated game wins** in sampled verified cases. |
| Game learning | Held-out episodes by game/version/objective, multiple seeds | Win/success rates and latency improve beyond confidence intervals while no hidden set leaks. |
| Roblox building | OpenGameEval-style executable scene and play tests | Higher repeatable pass rate with no test contamination or accidental publish permissions. |

**Rollback:** disable \`single_flight_tts\` in trusted host config; no migration or data conversion.
No broadcast, PC input, or OBS recording begins from this patch.

## 7. Prioritized next integration tasks (not completed in this change)

**P0:** Run real Windows private nonbroadcast rehearsal with authenticated OBS + VAD + audio
playout receipts and compare single-flight polling on/off; inspect downstream host adapters
for duplicate TTS launches and ensure cancellations propagate into their worker queue.

**P1:** Build a bounded fast-game agent loop with real capture-to-action timelines and
host-verifiable action outcomes. Add failure-driven practice against varied unseen maps.
Reproduce selected OpenGameEval tasks in disposable Studio worlds. Treat real game telemetry
as authoritative only when host-signed; forbid on-air claims from practice validation data.

**P2:** Integrate actual spoken PCM clock to avatar lip/eye/gesture cues; test explicit
interruptions, idle listening animation and personality memory provenance with authorized
audience feedback. Add a naturalness/accuracy scorecard.

**P3:** Pair hardware profiling with quantization/KV/speculative decoding experiments,
resource-aware CPU/GPU voice routing, and offline index-based retrieval. Ship a winning
configuration only after multi-trial quality and load acceptance checks.

## Scope and limitations

The implemented source change only updates \`NaturalTurnBridge\` to coalesce redundant
optional speech preparations behind an opt-in single-flight lease. No streaming, gameplay
controller, voice model, avatar backend, neural-weight training, hardware benchmark,
or self-awareness claim is delivered by this patch. Tests use deterministic offline
inputs; a trusted Windows host must still prove real-world latency and safety.
