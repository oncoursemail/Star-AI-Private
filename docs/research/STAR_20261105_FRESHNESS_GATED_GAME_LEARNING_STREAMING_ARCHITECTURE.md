# STAR: Freshness-gated game learning and humanlike VTuber architecture
**Research and implementation record — November 5, 2026**

## What changed, and what remains unproven

This change introduces two strictly opt-in improvements to STAR's existing
**symbolic**, private-game navigation advisor:

1. **Per-tile capture-time TTL** (max_tile_age_ms). After a tile's evidence
   expires, the planner treats it as unknown, not as a safe shortcut. A newly
   witnessed tile is refreshed individually. This matters for moving
   platforms, doors, opponents and hazards.
2. **One move hint per observation** (single_move_per_capture). Repeating
   advise() with the same frame returns await_observation instead of
   endlessly repeating movement advice. A new accepted capture is required.

Both options are OFF by default, require explicit configuration and never
press keys, operate OBS or enable publishing. The existing host_verified
boolean is a **host adapter contract, not cryptographic proof**. An untrusted
LLM supplying True cannot attest to actual game state.

Example for a trusted private harness:

    nav = GroundedNavigationMemory(
        max_observation_age_ms=600,
        max_tile_age_ms=300,
        single_move_per_capture=True,
    )
    nav.start(game_id="lab", game_version="v1", episode_id="e1",
              owner_approved=True)
    nav.ingest(observation, now_ms=host_clock_ms,
               host_verified=trusted_host_witness)
    hint = nav.advise(now_ms=host_clock_ms)
    # hint remains advisory: a separate GameActionGate decides real inputs.

The TTL is a *bounded evidence-age heuristic*, not a guarantee that a tile
has remained safe. A tile can change immediately after a capture. Risky games
require shorter freshness leases, action-deadline checks and authoritative
host-side safety and game-rule verification.

## The multi-speed STAR architecture

| Plane | Responsibility | Essential evidence |
|---|---|---|
| Trusted host | Screen/Studio capture, monotonic clock, session and authorized game input | Capture ID, player/game state and action receipt |
| Fast reflex | Stop/avoid, short motor actions, reject out-of-date intents | Input latency and observed outcome |
| Tactical navigation | Bounded map, per-tile freshness, safe path, frontier exploration | Verified local cells and player location |
| Strategic reasoning | Goals, plans, inventory, mechanics and tool choices | Plans checked against live observations |
| Skill learner | Guided practice, counterexamples and holdout challenges | Independent graded successes and failures |
| Knowledge learner | Source-grounded docs, APIs, general topic questions | Provenance, version, uncertainty calibration |
| VTuber director | Viewer turns, natural silence, speech priority, expressions | Speech/playback times and avatar sync |
| STAR Core Forge | Isolated experiments, tests, rollbacks, local code history | Immutable versions and independent judges |

A single hardware admission controller should reserve real-time budget for
game FPS, vision, sound and avatar output. Heavy retrieval, training, model
search, Blender rendering and repo indexing defer under contention. GPU
memory alone does not capture CPU, PCIe or encoder contention. On an 8 GB GPU,
do not load multiple expensive models by default during a stream.

## A real game-learning loop

**Observe → infer → propose → authorize → execute → witness → score → retain.**

- The trusted host supplies real observations and a version-bound episode ID;
  no assistant or generative model self-certifies its own observations.
- Invalidate stale or conflicting state before each advisory action. The new
  tile TTL can reject older safe-route assumptions. Each host capture can
  yield at most one move in the opt-in mode.
- A separate owner-authorized action gate performs actual game actions.
  Keep advisory perception and authority to press buttons isolated.
- Require the next observed player state and an input receipt to check whether
  a move occurred. A fresh frame alone does NOT prove progress.
- Log setbacks, hazards, action acknowledgements, success conditions, and
  recoveries by version and episode. Never use generated declarations of
  winning as rewards.
- Practice increasingly hard missions on separate training and hidden-test
  maps; retain only skills that transfer to unseen maps/versions without
  raising collision counts or latency.
- On stalls, reobserve, investigate a new frontier, safely backtrack or
  abstain. Bound retry counts to prevent robotic loops.

Google DeepMind SIMA 2 (November 13, 2025) demonstrates research on agents
that learn from human demonstrations, reason about goals and self-improve from
game experience. These are design directions, not claims STAR has SIMA 2's
learned policy. Source:
https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

## Roblox game creation: inspect, modify, playtest, repair

Roblox OpenGameEval's **October 2026** paper tests 13 models on 84 curated
tasks in stateful Studio sessions. Exploration was correlated with task
success; inspecting affected objects before modifying them was especially
useful. STAR should turn that into an inspect-before-edit policy:

1. Inspect hierarchy, scripts, network ownership, UI instances, assets and
   object properties. Check for client/server divergence and missing pieces.
2. Plan reversible changes and test a small candidate. Validate with Luau
   static analysis, StyLua/Selene where available, and game-specific checks.
3. Execute Studio edit-mode **and** play-mode verification. Test movement,
   mechanics, UI, replication, VFX, sound, animation, and success conditions.
4. Grade visuals using screenshots/video and known engine truth; do not
   substitute a plausible explanation for a real working experience.
5. Compare multiple candidates against the *same* private held-out tests and
   roll back failures. Measure correct mechanics finished per hour, not
   generated lines of code.

References:
https://github.com/Roblox/open-game-eval
https://arxiv.org/abs/2610.02563
Roblox's **December 17, 2025** introductory article described an earlier
47-test suite; do not confuse its size with the later 84-task paper:
https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio

## Higher intelligence and general knowledge

Bigger prompts do not prove smarter decisions. Use workload-specific model
routing with independent, version-matched verification: fast known-action
path, retrieval, multi-step tool/Studio exploration, then expensive
best-of-N generation only when the expected correctness gain justifies cost.
Grade verified task completion, uncertainty calibration, source freshness,
coding regressions, gameplay success and severe-error rate.

STAR Core Forge should own independent local experiment records, rollback and
preregistered holdouts. GitHub remains optional for publishing and review.
Never automatically promote a model just because it outputs more tokens per
second, solves its *training* tasks or signs its own outcome claims.

## Speed: measure correct actions, not only tokens/sec

Run A/B replay under **simultaneous** real game, audio output, avatar rendering,
OBS recording and inference. Record capture-to-action p50/p95, viewer question
to first audible audio p50/p95, audio interruption latency, avatar/audio
offset, real FPS and 1% lows, OBS drop rate, peak VRAM, CPU contention,
correct-action rate and retries.

Baseline llama.cpp decoding against prompt-cache, quantization and
speculative-decoding candidates. Draft-model decoding can consume enough
compute/VRAM to make total performance worse. SPEED-Bench measures acceptance
and per-category latency to make this comparison reproducible:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Kyutai Pocket TTS added smaller English voice models in its October 20, 2026
v4.0 release (18.2M, 6.9M and experimental 1.9M parameters). CPU voice
synthesis may preserve GPU resources but must be evaluated for intelligibility,
expressiveness and first-audio latency **on STAR's Windows hardware**:
https://github.com/kyutai-labs/pocket-tts/releases
https://github.com/kyutai-labs/pocket-tts

## More naturally humanlike on stream, while transparent about being AI

Create a rich interactive *AI character*: stable interests, hobbies, recurring
jokes, humor, continuity of real gameplay memories, vocal habits, and
expressive eyes, hands and gestures. Do not fabricate childhood memories,
unobserved victories or human consciousness as established facts.

- **Timing:** choose when to speak and when to stay silent. Prioritize owner
  and viewer questions, urgent gameplay danger and actual social context;
  avoid repetitive narration or conversation monopolies.
- **Grounding:** reference only witnessed gameplay. If uncertain, express
  uncertainty or stay silent, not pretend to have seen an event.
- **Real audio:** produce lip-sync/eyes/gestures from *playback* timing, not
  merely from when generated text was queued.
- **Full duplex:** distinguish chat attention, listener backchannels,
  laughter, interruptions and pauses. Keep silence latency and overtalk
  measurable, with owner-configured moderation policies.
- **Persistent personality:** save selected, verified experience records and
  reproducible character state; respect privacy, consent and retention rules.
- **Social/game rules:** disclose AI nature, obey permitted-game ToS,
  moderator decisions and platform safety rules.

Microsoft Proact-VL (ICML 2026) researches proactive speech timing and
latency in live video game companions:
https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

NVIDIA PersonaPlex (2026) studies prompt-conditioned full-duplex conversation;
DyaPlex (NeurIPS 2026 research) studies coordinated full-duplex speech and
motion. Both are research references, **not** deployed STAR components; their
resource requirements may conflict with 8 GB gaming hardware:
https://research.nvidia.com/labs/adlr/personaplex/
https://research.nvidia.com/labs/amri/projects/DyaPlex/

## Acceptance and limits

**A — This update (offline):** verified per-tile expiry, fresh re-witness,
duplicate-move throttling, replay/clock safety and compatibility tests.
These are not real-game navigation scores.

**B — Future trusted Windows adapter:** session-bound camera/Studio-state
captures, provenance/authentication, action receipts, clock checks and
game-engine truth comparisons. The LLM must not forge host_verified=True.

**C — Private game rehearsal:** one authorized sandboxed game, no public
match or broadcast; synchronized real gameplay, audible TTS, avatar motion,
OBS recording and hardware telemetry. Grade held-out map completion, stalling,
FPS and response latency with a separate evaluator.

**D — Humanlike presentation study:** compare private A/B recordings, rate
grounding, helpfulness, humor, interruption handling, appropriate silence,
human reviewer preference and audio-avatar synchrony.

**E — Autonomous curriculum:** bounded difficulty increase with independent
evaluation, rollback, verified long-term memory and cross-game transfer
checks; keep new tool permissions disabled by default.

**Not done here:** no real-game actuation, no new model weights, no observed
increase in neural intelligence or GPU token speed, no live voice session and
no stream broadcast. The only demonstrated runtime behavior is the opt-in
offline navigation logic.
