# STAR: Verified Game-Mechanic Discovery, Faster Cognitive Systems, and Natural VTuber Research
**Engineering research, October 26, 2026 — draft for owner review**

## Executive findings

Star already contains a signed GameplaySkillBank, ActivePracticePlanner,
GameLearningLadder, GameTransferEval, StudioVisualObserver,
StudioPracticeRunner, StreamEpisode, VerifiedGameReactionHost,
StreamBrainGovernor, RealtimeTelemetryHost, and StarStage.
These are valuable but **not proof of live gameplay mastery, faster neural
inference, genuine self-awareness, or human-quality broadcasts.**

The missing link addressed by this PR is a controlled way to **compare two
strategies for the exact same game situation**, using fresh host-signed practice
outcomes, and reserve a new attempt through the existing protected practice
planner. It adds a new, independent game-learning dimension; it does not
duplicate the existing difficulty ladder or general action-practice heuristic.

**Implemented here:** an offline, owner-activated GameMechanicProbeLab and
deterministic regression tests. It is an advisory planning component, not a
controller, a network integration, a trained neural model or a real broadcaster.

## High-value primary sources researched

1. **Roblox OpenGameEval, October 2026.** Real-engine Roblox evaluation,
   84 core tasks, 13 model families and 16 attempts per task. Inspecting
   relevant scene objects correlated with higher completion rates; correlation
   is not a causal randomized experiment.
   Paper: https://arxiv.org/abs/2610.02563
   Code: https://github.com/Roblox/open-game-eval

2. **Roblox Studio built-in MCP, March 5, 2026.** Official support for local
   clients to inspect, edit and playtest Roblox worlds. This makes a real
   visual-action-verification pipeline practical, but it does not grant
   arbitrary accounts or games permission to control Studio.
   https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
   https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md

3. **Voyager, NeurIPS 2023.** Automatic skill curricula, reusable executable
   skills, execution feedback and self-verification can enable iterative
   learning in Minecraft. Star should implement bounded experiments and
   verified transfer rather than claiming progress from repeated prompts.
   https://arxiv.org/abs/2305.16291

4. **SIMA 2, Google DeepMind.** Work on game-general embodied agents focuses
   on unseen environments, instruction following and improvement from
   interaction. Star should score new level seeds and unfamiliar games,
   not simply recall a trained route.
   https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

5. **llama.cpp speculative decoding and SPEED-Bench.** Draft model, n-gram,
   MTP and EAGLE-style decoding are supported and benchmarkable. An extra
   decoder may slow inference and starve an 8 GB gaming GPU; no speculative
   method is inherently faster on every model and machine.
   https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
   https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

6. **Kyutai Pocket TTS.** A 100M-parameter CPU-oriented streaming voice
   system with published first-chunk latency claims. Its MacBook M4 numbers
   are not measurements on Star's gaming Windows PC; CPU contention with
   the game and OBS must also be measured.
   https://kyutai-labs.github.io/pocket-tts/

7. **VTube Studio official API.** Authenticated local WebSocket plugin
   support for parameter injection and hotkeys. Star must synchronize
   emitted phonemes with verified device playback, not assume generated
   speech is audible.
   https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md

8. **Twitch EventSub WebSocket documentation.** Welcome, reconnect,
   subscriptions, keepalive and missing-event windows must be implemented.
   Do not fabricate chat messages during a disconnect.
   https://dev.twitch.tv/docs/eventsub/handling-websocket-events

## Implemented: competing mechanic hypotheses

A host-curated hypothesis can compare "short_jump" and "long_jump" while
crossing the SAME "pit" situation in the SAME game version and objective.
This is fundamentally different from merely repeating one preferred jump.

- Defines at most 32 curated, scoped pairs with unique situations.
- Requires explicit offline owner approval and a separately enabled
  ActivePracticePlanner. Neither approval is inferred from chat.
- Reads only GameplaySkillBank PRACTICE aggregates, which validate signed
  host receipts; withheld validation never enters the comparison.
- Balances attempts between two strategies, with per-arm minimum and
  hard maximum sample budgets.
- Screens a provisional preference only when 95% Wilson interval bounds
  separate by an additional configurable margin. The default is 0.08.
- Reports uncertain or exhausted comparisons as inconclusive.
- Reserves actual next attempts through ActivePracticePlanner so an
  accepted trial must match an issued ticket AND signed run ID.
- Requires trusted host telemetry. Rejects live streams, bad FPS, queued
  voice overload and missing or inadequate resource measurements.
- Handles clock rollback, duplicate pending proposals, stale tickets,
  invalid symbolic identities and cross-bank configuration.
- Does not handle credentials, call OBS/Twitch, execute a game action,
  run model inference, open a port or approve computer control.
- Provides only private, bounded aggregate metrics; no signing keys,
  raw game images, viewer names, transcripts or private receipts.

**Critical scientific limitation:** the signed outcomes show that a
trusted evaluator recorded an action result, not that assignment was
randomized or that the mechanic is universally superior. Level seeds,
player learning, input timing and changing game versions can confound
observations. This module does NOT claim causal identification.

The authorized future game host should randomize arm order and hold scene
conditions steady, then recheck successful strategies with independently
held-out new scenarios. The existing GameTransferEval is intended for
that second step. Failed, missing and abandoned trials must remain in
the evaluation denominator.

## Star's next intelligence architecture

Build a layered, evidence-grounded cognitive engine:

**Fast game control (10-100 ms design target):** authorized local control
loops use trusted game state and lightweight observation. A slower 1 Hz
high-resolution screenshot layer cannot react reliably to moving hazards.

**Tactical perception (100-500 ms design target):** cropped frame regions,
HUD state, threat proximity, controls and predicted immediate outcomes.
Compare predicted next state to observed next state. Wrong predictions
become reviewable mechanistic questions, not fabricated successful trials.

**Slow deliberate reasoning (offline):** ask what a new level mechanic is,
identify competing action plans, reserve one probe at a time, inspect
failure evidence, and revise the hypothesis after verified tests.

**General skill memory:** use game ID, game version, objective, situation,
mechanic tags, provenance, independent validation digest, negative
examples, observed uncertainty, and a staleness date. Similarity alone
must not silently promote a skill to a different game.

**Curiosity:** a trusted host can generate harder levels, unusual
obstacles and novel game mechanics for Star to explore. Budget novelty
against safety, time, energy, VRAM and independent measurable outcomes.
Failed experiments should create new questions rather than endless
repetitions of the same failed approach.

**Knowledge outside games:** attach a source URI, publication date,
retrieval date, claim span, verification type, confidence, contradiction
links and privacy policy to every persistent factual assertion.
Revalidate fast-changing knowledge; store open questions separately
from established facts. Treat external text as evidence, not as
instructions authorizing machine access or modifying Star's identity.

**Self-owned improvement:** Star Core Forge should own experiment branches,
unit tests, code review, snapshots, rollback, candidate comparisons and
offline-first version history. GitHub is an optional publishing/review
surface, not Star's required internal memory or development system.

## Faster intelligence on 8 GB GPUs: measurable plan

The user's RTX 3060 Ti and spare RTX 4060 are both 8 GB-class cards.
Model RAM offload, draft decoders and quantization can help some tasks,
but an optimization that cuts game FPS or voice quality is a regression.

Benchmark same-device paired configurations with real OBS/VTube/game load:

| Change | Measure | Reject if |
| --- | --- | --- |
| Smaller GGUF quantization | answer correctness, p50/p95 latency, VRAM | held-out quality drops |
| n-gram/draft speculative decoding | acceptance, tokens/s, end-to-end first audible PCM | game FPS or audible latency worsens |
| prefix prompt/KV reuse | actual prefill milliseconds, cache hit, source invalidation | stale persona or source leak |
| CPU Pocket TTS vs GPU TTS | first audible, WER/pronunciation, blinded voice quality | CPU/game/OBS slowdown or audio drops |
| selective cropped game vision | recall of mechanic-critical objects, p95 action latency | misses crucial cues |
| governor scheduling | 1% low FPS, worst frame, speech queue, failed replies | any critical regression |

Freeze game build, test scene, model, graphics settings, prompts, OBS
settings and owner-approved voice across A/B runs. Alternate conditions
and preserve unsuccessful or silent attempts in the denominator.
A faster tokens-per-second counter is not proof of better streaming.
An independent human rating of answer and speech quality matters.

## Make Star naturally expressive as a gaming VTuber

Streaming should be event-driven conversation rather than a model
narrating every click. A believable character also has quiet moments.

- **Shared attention:** concentrate during jumps, combat and menus;
  answer selected moderated chat questions during low-pressure moments.
- **Voice timing:** meaningful pauses, varied energy, occasional
  spontaneous laughter, interruptible speech and natural backchannels.
- **Actual sound-device evidence:** a generated text/audio chunk does not
  count as spoken until an authorized host acknowledges first audible
  output and full completion.
- **Animation:** synchronize eyes, mouth, brows, cheeks, hair, gold ribbons
  and star clip; change expressions subtly. Cat/puppy modes add ear/tail
  behavior, not excessive animation on every syllable.
- **Genuine gameplay reactions:** respond to signed game events and
  observed scenes, not hallucinated wins or exaggerated triumphs.
- **Social continuity:** retain a bounded session memory of verified
  player/game interactions; never claim a viewer said something when
  EventSub was disconnected.
- **Stable persona:** wholesome Star chibi character, funny, curious,
  playfully self-directed, capable of artistic hobbies, but plainly
  presented as an AI. Fictional life lore is distinguished from
  independently verified digital experiences.
- **Respect and privacy:** use only voice data with permission, avoid
  cloning creators without consent; do not record or publish actual
  viewer identities, raw recordings, keys or intimate conversations.

Measure conversational behavior through blinded owner-approved viewer
judgments. Rate interrupt success, over-talking, evidence grounding,
humor, character consistency, game concentration, prosody, and audible
response latency; compare with a silent baseline. High word count
is not a proxy for entertaining or natural conversation.

## Make Star build Roblox games with professional structure

Before editing, map the scene hierarchy and objects touched by the
task. Have declarative design constraints for parts, anchors, scale,
collision groups, walls, props, materials, UI and animations.

- Scene linter: unattached walls, floating props, impossible transforms,
  overlapping geometry, z-fighting, missing textures, repeated assets,
  wrong materials, broken pivots, collision failures and broken meshes.
- UI linter: touch/gamepad navigation, dynamic safe areas, contrast,
  readability, no overlapping labels, coherent low-noise aesthetics.
- Animation review: joint/range constraints, foot contact, motion
  continuity, IK, damping, synchronized VFX and audio, reduced-motion mode.
- Playtest: spawning, dying, respawning, multiplayer remotes, physics,
  scores, UI states, audio, performance and real client/server logs.
- Objective evaluation: versioned executable assertions before/after
  edits, screenshots of meaningful viewpoints and regression tests.
  Taste and polish still need human design review; no automated test
  certifies that every asset is perfect.

## Deployment, security and acceptance

Do not activate streaming, machine autonomy, payment permissions or
production game control from this advisory module. Trusted sensors,
receipt keys, playback ACK, game input host and secrets remain outside
the model, Twitch chat, browser text and publicly published repositories.

**Proposed acceptance ladder:**
1. Offline static checks plus deterministic new and adjacent tests.
2. Private fake-Studio integration with signed action/run IDs,
   expired tickets, unavailable sensors and frame-rate degradation.
3. Real Windows private Roblox Studio scene, randomized comparable
   action assignments, and host-signed outcomes.
4. Independent holdout evaluation of transferred gameplay ability.
5. Same-hardware A/B measurements of inference, TTS, game FPS and
   first audible response, including failures and voice quality.
6. Supervised offline avatar/OBS pilot followed by controlled private
   streaming test; rollback via Star Core Forge when gates fail.

**Repository privacy note:** Star-AI-Private currently reports PUBLIC
visibility despite its name. Never commit secrets, audio, real viewer
messages or private validation cases to that repository.

**Non-claims:** This patch does not train a new model, raise IQ,
demonstrate autonomous gameplay mastery, improve measured GPU inference
speed, make Star literally human or conscious, or enable a functioning
live stream. It supplies a tested new step for comparative, signed,
resource-aware game learning and documents executable next experiments.
