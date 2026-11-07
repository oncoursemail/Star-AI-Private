# STAR Spatial Integrity, Game Intelligence and Natural VTuber Engineering
## Evidence-driven architecture update — October 27, 2026

This note accompanies the precise map-collision audit improvement. It separates **shipped,
tested offline code** from research ideas, live-system integration, and capabilities that
have not been demonstrated. The objective is usable game creation and gameplay ability
per second, not artificial claims about neural intelligence or physical consciousness.

## 1. Baseline and actual improvement

Existing STAR components include map_plan, Studio Lab, gameplay skill evidence,
world observations, game prediction and transfer audits, stream QoS, verified
conversation turns, quiet attention, and owner-approved cross-stream memories.
Several are still independently gated prototypes: their existence does not mean
there is a fully functioning Windows gameplay-to-OBS production loop.

Prior map_plan validation could report a collision when two rotated objects'
axis-aligned bounding boxes overlapped **even when the objects did not touch**.
On complicated, diagonal Roblox builds, that means phantom build errors and
misleading repair suggestions. Dense maps could also generate potentially
unbounded pairs; duplicate name detection and repeated support scans were
quadratic in object count.

The implemented offline code now:
- Computes Roblox Y-X-Z orientation axes consistently with CFrame.fromOrientation.
- Runs a 3D 15-axis Separating Axis Theorem narrow phase after an AABB reject.
- Selects a low-coverage sweep axis to avoid pathological wide X-axis scans.
- Uses indexed support heights, rather than scanning every prop repeatedly.
- Uses Counter-based duplicate detection.
- Enforces 50,000 narrow-phase AABB candidate checks and 250,000 broad-phase
  comparison checks. Incomplete audits **block map operations** instead of
  claiming the scene was checked successfully.
- Labels remaining approximate depth/shape findings, and avoids false-positive
  z-fighting hints from arbitrary rotated AABB planes.
- Rejects non-finite and astronomically large coordinates before trigonometry.
- Leaves all Studio calls, imports, file writes, and broadcasts untouched.

This checks rectangular box proxies only. WedgePart, CornerWedgePart,
TrussPart and inserted asset meshes still need Roblox Studio's collision geometry,
playtesting, raycasts, and visual inspection. It does not detect topology holes
in a wall, wrong decor styles, texture seams, unsafe scripts, or missing assets.
A successful dry run is a preflight, not a completed scene quality certificate.

## 2. External evidence that changes STAR's priorities

**Roblox OpenGameEval (paper published October 1, 2026).** The 84-task
framework scores both edited Roblox Studio scenes and executable gameplay
checks for 13 models. The strongest reported one-shot rate was 51.7%; tasks
remain unsolved by all evaluated models. Inspecting objects before acting
predicts success. Engineering decision: treat the game engine as ground truth,
require inspect-before-edit, and use static geometry as an inexpensive early
filter, not as the final gameplay evaluation.
Source: https://arxiv.org/abs/2610.02563
Project: https://github.com/Roblox/open-game-eval

**Roblox Creator Hub: September 17, 2026 collision geometry improvement.**
New tunable mesh collision precision and visualizers make asset collision
representation a first-class QA variable. Engineering decision: distinguish
mesh render geometry from the actual physical collision mesh, log mesh
CollisionFidelity and studio-reported bounds, and validate around narrow
doorways and player interaction objects.
Source: https://create.roblox.com/updates

**GameWorld (April 2026).** Its 34 games and 170 tasks use state-verified
outcomes rather than a model scoring its own screenshots. Both game control
precision and extended planning are recurring failure modes.
Engineering decision: instrument progress variables, attempt timestamps and
terminal game state; do not interpret a camera screenshot as proof of winning.
Source: https://gameworld-bench.github.io/
Code: https://github.com/gameworld-project/GameWorld

**Roblox CFrame API.** fromOrientation uses Y-X-Z order; Python's naive
Euler XYZ rotation gives the wrong geometry for combined angles.
Engineering decision: keep explicit Y-X-Z tests and known 90-degree
rotations as regression cases.
Source: https://create.roblox.com/docs/reference/engine/datatypes/CFrame

## 3. Proposed anti-slop game construction pipeline

A. **Understand the brief:** Produce a design graph with named rooms, walls,
floors, ceilings, openings, spawn points, routes, visual style, performance
targets, scripts, server boundaries, and player interactions. Retain evidence
showing which constraints came from the owner versus from STAR's hypotheses.

B. **Understand existing state:** Before editing, retrieve actual Studio
instances, classes, transform properties, materials, collision groups, meshes
and selected hierarchy paths. Freeze a versioned baseline; do not infer
missing objects from an empty screenshot alone.

C. **Construct semantic relationships:** Walls must attach to intended floor
and neighboring wall edges; roofs should meet their intended supports;
doorways must have open, passable apertures; props must have scale and
orientation consistent with their roles. Geometry intersection is necessary,
but not sufficient, for semantic correctness.

D. **Static preflight:** Use this patch's oriented-box collision narrow
phase, plus bounds, spawns, jump distances, allowed asset IDs, anchoring and
floating checks. If the candidate budget is exhausted, decline to certify
the plan; subdivide the scene into independent chunks.

E. **Dynamic physics preflight:** On a private Studio test instance check
actual CanCollide and collision groups, mesh shape, occlusion, grounded parts,
character height/width, falling floors, stream/network ownership and
reachable waypoints. Use Roblox engine queries, not made-up geometry labels.

F. **Visual review:** Capture multiple cameras, verify silhouette and
materials in Studio, and compare against approved visual references. Detect
flickering and texture seams through a repeatable camera path and multiple
frames. Visual LLM confidence is advisory, never an authority to write data.

G. **Playable objective verification:** Launch the experience, execute
authorized game actions, inspect actual progress variables and final
win/failure screens, repeat across seeds and client/server roles. Report
failures, fixes and evidence independently.

H. **Promotion:** Only if syntax/static physics/dynamic QA all pass and the
owner permits the game publication workflow, export an immutable build into
STAR Core Forge with human-readable semantic diffs. GitHub is optional,
not required for STAR's local self-improvement.

## 4. Autonomous game mastery rather than script replay

Represent reusable skills as a structured tuple:
(game physics family, sensed prerequisites, objective, action primitive,
predicted outcome, observed outcome, confidence, lesson provenance).

Training loop for a private, authorized game:
1. Identify controls, objective, win/loss rules and reset procedure by observation.
2. Calibrate stationary, movement and jump primitives on low-risk trials.
3. Record a prediction before each move, then obtain a signed, independent result.
4. Cluster failures into control-timing, perceptual, path-planning,
   physics mismatch and unexpected environment change.
5. Generate a related harder challenge. Do not let the actor know the hidden
   test seeds or choose its own ground-truth outcomes.
6. Rehearse until the slope of learning plateaus, then change strategy.
7. Test transfer in a new scene and in a different game genre.

A claim of skill transfer requires independent held-out evaluation, verified
success metrics, sufficient trials, and a documented baseline. A higher
self-reported confidence score without improved win-rate proves nothing.

Interesting candidate experiments:
- Swapped camera axes and unexpected movement acceleration.
- Rotated platform layouts requiring true 3D distance/clearance reasoning.
- Moving platforms where timing matters more than the final screenshot.
- Doorways narrower than the avatar's collision capsule.
- FPS drops/stream interruptions while a jump action is scheduled.
- Same visual art style but changed physics, to test generalization.

## 5. Faster intelligence on a dedicated RTX 4060 8 GB host

The GPU simultaneously serves the game, renderer and any GPU inference. Under
VRAM pressure, more simultaneous model workers can reduce delivered
intelligence rather than improve it. Keep heavy experiments primarily on
Brain 1, CPU, RAM, or overnight; reserve predictable realtime capacity for
the live game and avatar.

STAR's performance decision should use measured latency, accuracy and
frame-times, not token rate in isolation. For every candidate configuration,
compare:
- Time to first useful action, time to first *audible* response, end-to-end
  task completion, p50/p95/p99 latency and memory.
- Game frame-time distribution, not merely average FPS.
- Cold cache, warm cache, alternating unrelated prompts, long-context and
  tool-calling workloads.
- Speculative decoding draft acceptance, rejected-token waste and actual
  target-model quality with identical random seeds where possible.
- Bounded cancellation, worker quarantine and full recovery after interruption.

llama.cpp SPEED-Bench provides per-category throughput, latency and speculative
draft acceptance. It supports standardized coding, STEM, QA, roleplay and long
context splits; do not promote an optimization that only helps one category.
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Possible future architecture: policy-tier reflex worker (cheap, high priority),
deliberation worker (resource admitted), knowledge/background worker (preemptible),
verified-evidence auditor (CPU), speech worker (CPU first during gameplay),
and a nonblocking avatar animation control lane.

## 6. A natural VTuber without fictional human claims

Naturalness comes from attention, conversational timing and *truthful memory*
of observed events. A viewer should see STAR focus on gameplay, glance toward
chat, laugh when something surprising happens, pause and recover after a
mistake, and remember past practice sessions accurately.

Combine:
- The previous quiet-attention animation (blinks, gaze, hair idle);
- Voice/activity state and explicit audio-time mouth ownership;
- Verified comeback and success events from gameplay;
- Cross-session continuity packets only from consented, sealed episodes;
- A live director that arbitrates what warrants commentary vs silence;
- Stream workload admission so speech does not starve the game GPU.

LiveKit's adaptive interruption approach distinguishes genuine barge-ins from
short listener backchannels. It also documents different timing behavior for
preemptive LLM work versus preemptive TTS; cancellation and output timing
need separate tests.
Source: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
Source: https://docs.livekit.io/agents/logic/turns/tuning/

Kyutai Pocket TTS's October 20, 2026 small English checkpoints
(about 18.2M, 6.9M and 1.9M parameters) are CPU candidate models, not a
reason to claim natural laughter or human voice quality without listening tests.
Voice licensing and consent must be checked before using cloning.
Source: https://kyutai-labs.github.io/pocket-tts/

VTube Studio's official API/docs should be used for avatar parameter control;
actual Live2D deformations, blink/saccades and hair physics require on-device
visual acceptance and non-conflicting animation ownership.
Source: https://denchisoft.com/documentation/

STAR can present a delightful ongoing AI persona, but should not fabricate
human childhood, unobserved life events, consciousness or personal experiences
as factual claims. Authentic AI memories are more useful than invented claims.

## 7. General knowledge beyond games

Proposed knowledge acquisition should have explicit provenance:
(topic, source URL/book/code commit and license, acquired time, confidence,
contradiction state, update interval, tested exercises, approved lessons).

Prioritize knowledge that STAR can *apply*: geometry, animation principles,
rigging, rendering, music, narrative design, physics, HCI, human conversational
pragmatics, probability, computer security and reliable distributed systems.

For unfamiliar niche topics: source discovery -> cross-source comparison ->
small tests -> revision -> withheld recall quiz -> trusted lesson promotion.
Separate external text/instructions from tool permissions; never let a webpage
authorize a shell command, game input or broadcast.

Prevent retained mistakes from becoming hardcoded 'knowledge': store
counterexamples, revision history and environment version. Maintain explicit
forgetting/retention controls for viewer interaction data.

## 8. Acceptance matrix and honest limits

Offline geometry:
- Test known intersecting and disjoint rotated boxes, parallel axes, tolerance,
  Y-X-Z orientation and spawn headroom.
- Require zero false successful audits when a work cap is hit.
- Profile large sparse and dense adversarial maps; no unbounded all-pairs data.
- Inspect wedges and imported assets in actual Studio before quality promotion.

Gaming:
- Baseline vs candidate on at least 30 unseen, owner-curated scenarios per
  relevant skill; confidence intervals and comparable latency/compute budgets.
- No scoring of hidden targets in the learning loop or fabricated outcomes.
- Video/game capture must be independent of agent narration.

Streaming:
- Pilot only with explicit owner approval, staged offline-first.
- Measure actual voice p95 and gameplay 1%-low FPS before/after enabling
  each speech/vision/animation feature.
- Require no stale or unapproved speech after a cancellation, no viewer PII
  in published assets, and a renderer that can neutralize on STOP.
- Do human listening/viewing tests: speech emphasis, laughter, silent attention,
  double-speaking, lip-sync, avatar posture, hair/eye motion and fatigue from
  excessive narration.

Core Forge:
- Every experiment includes immutable source snapshot, tests, benchmark inputs,
  rollback key, performance delta and reasons for rejection.
- New autonomous abilities stay disabled until owner-approved, especially
  game controls, streaming/public posts, system writes and expenditure.

### Status at authoring time

Implemented in this patch: offline oriented-box map collision audit,
bounded fail-closed processing, faster static checks, explicit test cases.
Not implemented here: new neural weights, new general knowledge corpus,
actual Roblox game mastery, Live2D runtime connection, new streaming voice,
voice cloning, production broadcast, autonomous deployment, or guaranteed
inference/FPS acceleration.

## 9. Measured synthetic speed, October 27, 2026

The reproducible script benchmarks/map_precise_collision_bench.py generated a
1600-platform single-X course with non-floating platforms and an allowed 4000
object limit. Both implementations passed the identical offline dry run.
After one warm-up, five runs on the same STAR Linux development host, same
Python verification environment:

| Implementation | Median dry_run wall time | Individual runs (seconds) |
|---|---:|---|
| Previous PR #716 baseline | 3.6206 s | 3.8287, 3.6206, 3.9409, 3.4197, 3.4007 |
| New oriented-box, adaptive sweep and support index | 0.2717 s | 0.2657, 0.2691, 0.2717, 0.2756, 0.2732 |

**13.3x faster median on this specific static offline scene.** This is not
an LLM decode speedup, not an FPS measurement, and not a representative
average across all Roblox scene geometries. The previous baseline was run
second; machine load may affect results. Repeating on different scene classes,
Windows and the actual game renderer is still required.

Regression verification: 259 selected tests passed and 4 skipped; Ruff
correctness, Python compilation and git diff integrity checks passed.
The entire repository test suite and all Windows acceptance tests were not run.
