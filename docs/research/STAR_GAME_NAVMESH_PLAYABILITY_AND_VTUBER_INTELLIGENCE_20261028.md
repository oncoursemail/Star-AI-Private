# STAR — verified route playability, game mastery and natural streaming
Research review: 2026-10-28. Status: implementation proposal + one offline-tested
navigation smoke-test compiler extension; **not** measured inference improvement.

## 1. Why this release is different from a geometric audit

STAR's scene-integrity compiler already checks parts, duplicates, properties,
style, primitive intersections and specified positions. A technically valid
scene can still trap a character behind a wall or leave the spawn inaccessible.
Roblox `PathfindingService:CreatePath`, `Path:ComputeAsync`, `Path.Status`
and `Path:GetWaypoints` provide an engine-specific navigation signal.

This extension adds `NavigableRoute` to an owner-curated `StudioSceneTest`.
It checks specified primitive platform pairs, agent radius/height/jump/climb
settings, pathfinder success, bounded waypoint count and detour distance.
Endpoints are lifted above each platform's top in the local up direction.
It rejects unknown endpoints, model-authored Luau, 9+ routes, oversized agent
profiles and invalid distances. Each changed route changes the suite hash.
A server-side 45-second watchdog fails a stalled script conservatively.
The plugin remains opt-in for a private Studio test place.

**Critical distinction:** engine path success is not proof a player will
successfully navigate the scene. It does not certify precise parkour timing,
dynamic moving platforms, human input, terrain after streaming, visual quality,
UI responsiveness, game endings, or production availability. No actual Studio
test or game input took place in this release. Pathfinding has engine distance
(3,000 studs) and node budget limitations; route tests can return false
negatives for deliberately difficult or special-movement levels. A model must
not treat such an outcome as permission to rewrite the game.

## 2. Verified sources and practical conclusions

### Roblox engine and automation

- Roblox, *Pathfinding* (live Creator Hub reference): parameters
  `AgentRadius`, `AgentHeight`, `AgentCanJump`, `AgentCanClimb`,
  `WaypointSpacing`, route failure factors, navigation visualization, and
  streaming limitations:
  https://create.roblox.com/docs/characters/pathfinding
- Roblox, *Path* and *PathfindingService* API references: yielded
  `ComputeAsync`, status and waypoints:
  https://create.roblox.com/docs/reference/engine/classes/Path
  https://create.roblox.com/docs/reference/engine/classes/PathfindingService/CreatePath
- Roblox, *StudioTestService* reference (Creator Hub / mirrored API):
  plugin-side automated multiplayer execution supports up to eight clients
  per local Studio instance; real multiplayer/client checks require Studio:
  https://robloxapi.github.io/ref/class/StudioTestService.html
- Roblox, *Luau Execution* Open Cloud: server-side headless tests against
  selected place versions can run up to five minutes. Do not mistake this for
  a real rendered client or an OBS stream. Use a non-production test place,
  explicit scopes, no unauthorized write operations:
  https://create.roblox.com/docs/cloud/reference/features/luau-execution

### Why passing code/builds isn't enough

- *GameWorld* (2026-04-08), 34 games and 170 outcome-verifiable tasks, finds
  challenges with latency, perception, long-horizon reasoning and memory:
  https://arxiv.org/abs/2604.07429
- *CEGame-Bench* (2026-10-19), complete game creation across five engines,
  measures whether a game can be completed with real inputs, not just built:
  https://arxiv.org/abs/2610.26098
- *GameDevBench* (ICML 2026), 333 multimodal game-development tasks; image/
  video feedback improves agent results in its evaluation framework:
  https://github.com/waynchi/gamedevbench

### Real-time speech and animation

- Kyutai Pocket TTS v4.0.0 (2026-10-20) and v4.0.1 (2026-10-21) ship
  small English CPU-oriented models, including 18M, 7M and experimental 2M
  configurations. Release notes flag fixes for sub-20M model output.
  Smaller does NOT imply better expressivity or faster audible response on
  STAR's actual PC; benchmark after installing weights locally.
  https://github.com/kyutai-labs/pocket-tts/releases
- VTube Studio plugin API allows authenticated injection of custom Live2D
  parameters. The host should correlate mouth/eye/head pose with actual
  speaker playback epochs and clear stale frames after interruption:
  https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins

### Local inference optimization

- llama.cpp's SPEED-Bench reference compares latency, throughput and
  speculative draft acceptance on an already running server; candidate
  speculative strategies should be measured alongside the game's FPS,
  speech latency and 8-GB-class VRAM use:
  https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

## 3. Next architecture milestones — prioritize integrations, not more islands

**A. Real game observer / held-out outcomes (P0).** Wire STAR's existing
game-frame observation, symbolic action gate, signed practice ledger and
independent holdout evaluator to the same authorized Windows Roblox test
session. Require host-owned, monotonic timestamps, exact game/version/episode
identity, immutable observation hashes and per-action run IDs. Reject a
learning claim if only the model grades itself. Measure completion, damage,
collisions, retries and success on unseen maps. Keep validation outcomes out
of policy prompting.

**B. Playability QA (P0).** Execute scene checks and the new navigation probes
in private Studio. Then add real-input finish-state playtests, respawn and
save/rejoin checks, two-client interaction, client GUI inspection, animation/
material screenshot review and pixel-difference follow-up. A navmesh passing
cannot replace a real agent moving the character.

**C. Fast/slow thinking policy (P0).** Reserve an always-responsive cheap
reflex tier for controls, speech interruptions, and game focus; run VLM frame
analysis at admitted sampling rates; schedule long-horizon plans between
critical moments. CPU-based motion novelty, frame sampling and existing
cache/prefill reuse should gate scarce GPU inference. Avoid heavy knowledge
retrieval, self-training, and video generation during gameplay. A bigger
prompt and more concurrent models are not automatically more intelligent.

**D. Humanlike but authentic VTuber continuity (P0).** A coherent speaking
turn must coordinate host-certified game event, attention, knowledge support,
speech generation, actual audible playback clock, eyes, blinking, hair,
ribbons and gestures. Support low-key quiet concentration, naturally timed
interruption and resumption, and appropriate comedy. Use actual signed
practice outcomes and opted-in stream memories for anecdotes. Do not fabricate
real human childhood, medical events, personal relationships or sentience.
Model self-reflection is a functional software capability, not proof of
consciousness.

**E. Curiosity and game-learning curriculum (P1).** Use exploration→prediction
→action→independent outcome→postmortem→practice with increasing challenge.
Track each action's practice Wilson lower bound, calibration/Brier score,
time-to-goal, transfer accuracy and failure taxonomy. Prioritize lessons
that resolve an observable uncertainty instead of self-rewarding repetitions.
Use held-out mechanics, seeds and levels; don't allow practice to see tests.

**F. General knowledge expansion (P1).** Build source-backed topic cards
with provenance, last verification date, reliability tier, version/locale,
contradiction notes, and retrieval confidence. Separate game observations,
search snippets and model conjectures. Revalidate changing APIs/specs rather
than treating a large vector database as updated knowledge. Follow licensing
and source attribution rules.

**G. Self-owned Forge (P1).** Maintain local transactional Git-like snapshots
(or content-addressed semantic changes), reproducible experiments, dependent
feature gates, regression batteries, rollback and a rollback rehearsal.
GitHub stays an optional export/publication channel; do not put private
stream transcripts, model keys, test-place tokens or viewer identifiers there.

## 4. Proposed experiments and acceptance requirements

All numbers here are **proposed evaluation gates**, not achieved results.

1. **Navigation:** 20 curated reachable and 20 blocked routes in private
   Studio, including rotated platforms, narrow corridors and deliberately
   invalid targets. Compare emitted pass/fail against independently inspected
   engine behavior; time out rather than assume passing. Repeat with 1 and 4
   simulated clients. Save only outcome codes/digests and anonymous test IDs.
2. **Real playability:** At least 10 held-out obbies/arenas built and tested
   end to end, including actual client input, death/respawn, win condition and
   client HUD. Report the **percentage** of executable, completable games
   compared to the preceding STAR baseline.
3. **Model-speed A/B:** Run paired baseline/candidate on the *same prompts and
   frame captures*, alternating order with warmup. Record TTFT p50/p95,
   tokens/s, prompt-cache hit rate, factual/coding correctness, GPU peak MB,
   game presented-frame p95/p99, OBS dropped frames and first-audible latency.
   Accept only candidates with no meaningful accuracy loss or stream harm.
4. **Voice and rig:** Blind listener assessment on 30 varied utterances:
   comedy, surprise, normal talk, short answers, laughter and interruptions.
   Synchronize actual audible speech to mouth movement with device-reported
   samples, not generated-audio timestamps. Compare underruns, awkward
   silences, expression jitter, and game FPS. Maintain STAR's voice identity.
5. **Learning transfer:** Randomly seed unfamiliar held-out situations. Report
   success rate before and after bounded practice plus confidence intervals.
   Re-running a memorized test is not evidence of improved general ability.

## 5. Scope/limits of this code update

Implemented here: schema, deterministic fingerprint and static generated
Luau for read-only, owner-curated NPC-style navigation smoke tests; offline
unit tests and linting. Not implemented: automatic Roblox login, Studio
runtime execution, model weight training, remote game input, new TTS
weights, stream broadcasting, or any measurable neural speed increase.

The host must verify place identity, launch consent, authorized game rules,
workspace permissions and hard stopping conditions. A successful checker
result is a new evidence input to STAR's development process, never permission
for autonomous publishing, purchases, moderation or account changes.
