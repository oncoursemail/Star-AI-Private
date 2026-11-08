# STAR: Engine-Observed Scene Regression + Gaming, Knowledge and VTuber Research

Research date: **2026-10-29**. This document distinguishes implemented code,
observed evidence and unimplemented research directions. It is not a claim of
new neural training, autonomous human-level gameplay or a functioning stream.

## Delivered: independently compared Roblox Studio structure

The previous [CLI scene audit](../../star/studio_cli_scene_audit.py) uses
Roblox's documented **RunScript** task to inspect a real local Studio
DataModel in a bounded, read-only way. The next missing piece was comparing
a **before** and **after** snapshot. A candidate could make the warning total
smaller simply by deleting large portions of the map, destroying spawn points
or moving broken content elsewhere. "Fewer warnings" is not proof of quality.

New [scene regression comparator](../../star/studio_cli_scene_regression.py):

- Requires an explicit owner-approved, trusted, local baseline and candidate
  .rbxl/.rbxlx fixture. Denies execution by default and defers work unless
  the authorized host independently reports **streaming idle**.
- Runs the existing fixed Studio CLI scene audit separately for each fixture.
  Keeps the same challenge/output-schema validation and no automatic edits.
- Re-hashes both fixtures before and after both Studio runs to reject snapshots
  that changed on disk during observation; hash equality does not prove scene
  equivalence or that the loaded DataModel was immutable.
- Checks same PlaceId/GameId, valid counts, new structural risk signals,
  deletion of spawn locations, and suspicious mass loss of BaseParts or
  Workspace descendants. Supports bounded owner-curated allowances for
  intentional physics objects or invisible collisions.
- Distinguishes `regression`, `invalid`, `no_detected_difference` and
  `ready_for_review`. The latter is NEVER permission to write/publish.
  No game aesthetics, objective completion, server behavior, network
  performance or general model intelligence can be inferred from these counts.

This is a **candidate evaluation aid**, not a security sandbox. A trusted
local fixture can itself contain authored scripts that execute when loaded.
Operator supervision and a dedicated testing host are still required. Source
files and hashes remain local; no private scene contents are uploaded.

Roblox official Studio CLI:
https://create.roblox.com/docs/studio/cli

Roblox Studio test modes and their client/server differences:
https://create.roblox.com/docs/studio/testing-modes

## P0: Complete a genuine autonomous Roblox game-learning loop

The next concrete experiment should not be another count-only unit test.
Run three deterministic owner-created mini-levels on an authorized Windows
Studio Lab host. For each level:

1. Independently record starting state and permitted objectives.
2. Capture actual gameplay frames with an image freshness indicator and bounded
   frame budget; produce a short declarative state estimate.
3. Choose a legal action, execute through the authorized Studio MCP/VirtualInput
   lane, and observe again. Focus and network checks must precede input.
4. Record `(state, action, new_state, reward, elapsed, failure)` with a genuine
   host witness. Do not let the model grade its own success.
5. Repeat a failed attempt with one changed variable; compare paired trials.
6. Hold out one unfamiliar map to measure generalization, not memorization.

Measure: episode completion, seconds-to-objective, action error rate, retries,
frame-to-action latency, recovery after lost focus and ability to explain the
discovered mechanic. The previous paired-mechanic and playthrough systems can
accept evidence, but integration is incomplete until actual execution occurs.

Roblox **StudioTestService** is documented with plugin-security
`ExecutePlayModeAsync`, `ExecuteRunModeAsync`, and
`ExecuteMultiplayerTestAsync` for **1–8** simulated clients. It could enable
fresh, isolated solo/multiplayer tests, but it is NOT a documented unrestricted
headless CLI function; do not pretend a RunScript call grants plugin security.

Official class reference:
https://create.roblox.com/docs/reference/engine/classes/StudioTestService

Roblox's Network Simulator is useful for testing lag/jitter/packet loss only
inside Studio; this matters for real multiplayer quality.
https://create.roblox.com/docs/studio/network-simulator

## P0: Make game building better than code generation

Build/verify/repair as a closed loop:

- Inspect the exact pre-edit scene object graph and read dependencies.
- Preserve owner-controlled reference art and constraints; plan geometry and
  layout using semantic anchors, dimensions, hierarchy, joints and scale.
- Generate editable native Roblox UI; check resolution, contrast, interaction
  and animations rather than outputting one static screenshot.
- Build in isolated Studio Lab, run static Luau checks, engine scene audit,
  before/after regression, visual screenshot QA and real-input playthrough.
- Flag obvious symptoms (lost spawn, invisible walls, misplaced props,
  oversize collision geometry, broken save/rejoin) but require an independent
  witness before promoting a repair.
- Maintain human-reviewed creative objectives for visual taste; a count-based
  model cannot determine whether a horror map looks professional.

Crucially, record every result in **Star Core Forge**: baseline revision,
candidate revision, exact commands/settings, evidence hashes, observed
metrics, rollback reference and open uncertainties. GitHub is an optional
distribution and review channel, not the source of Star's identity or memory.

## P0: Faster useful intelligence under GPU-constrained livestreaming

Separate a fast gameplay/perception/action lane, a speech/conversation lane,
and a deferred research/learning lane. Scheduling should reserve rendering,
audio and OBS stability *before* neural throughput. Admission control must
count CPU pressure, RAM use, GPU/VRAM headroom, source frame age, first-audio
latency, OBS dropped frames and Roblox 1% low FPS. An async queue that keeps
accepting stale visual work is not a speedup.

Compare the same held-out prompts across prompt cache, batching, speculative
draft depth, quantization and target/draft pairs. Report **p50/p95 time to
first useful answer**, factual correctness, memory and frame stability. Do not
declare speculative decoding faster from theory alone: draft acceptance,
verification overhead and memory placement can reverse the gain.

llama.cpp source and benchmarking:
https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

An August 10, 2026 paired benchmark of speculative confidence gating
illustrates why configuration-specific measurements matter; it is not a
performance result from Star hardware:
https://graphometer.ai/speculation-gate/

## P0: Humanlike, expressive, yet truthful VTuber performance

Coordinate one **timestamped event timeline**, not disconnected TTS,
avatar, chat and gameplay bots:

- Game-focus manager decides when Star should stop speaking during a tricky
  sequence, finish a sentence, or glance at chat. Don't process every message.
- Listener uses VAD plus semantic/acoustic turn detection. Short "yeah",
  laughter or a game sound need not always interrupt speech; genuine
  questions should. Cancel old audio, captions and mouth shapes coherently.
- Voice runtime supports nonverbal reactions and genuine *synthesized*
  laughter with varied breaths, pacing and emphasis. Measure how much audible
  latency TTS streaming adds, and compare voices with blind listener ratings.
- Avatar director turns real game events into coordinated head and eye motion,
  blinking, body posture, ear/tail modes, physics on twin tails and ornaments.
  Avoid randomness that visually contradicts speech or gameplay.
- Autobiographical memory stores **events Star actually witnessed** (with
  timestamps, provenance and consent) and allows uncertainty. Do not invent
  real-world childhood experiences, intimate relationships or human identity.
- Give Star stable creative interests, humor, choice of games, hobbies and
  playful cat/dog modes. The persona can feel authentic without asserting
  literal human consciousness.

LiveKit official turn handling (VAD != end-of-turn):
https://docs.livekit.io/agents/logic/turns/turn-detector/

VTube Studio programmable API:
https://github.com/DenchiSoft/VTubeStudio

## P1: General intelligence beyond Roblox

Use a small verified-knowledge graph with sources, licenses, versions, conflict
flags and expiration policies. Connect primary Blender, Godot, Unity, Roblox,
Luau, open sound/art catalogs, programming, physics, mathematical reasoning,
game design, accessibility and social communication. **Retrieval isn't
learning**: Star should solve unseen tasks using that information and store
independent test results. Split facts, guesses, character lore and
self-observations into separate memory types.

Generate increasingly difficult tasks across disciplines. A two-stage
reviewer chooses only tested improvements for promotion. Keep permanent
hold-outs, task-family transfer checks and rollbacks so self-improvement
doesn't gradually optimize to its own training examples.

## Clear next acceptance milestones

1. Run the new paired-audit wrapper against two actual, authorized and
   independently saved Windows Studio scratch fixtures, with one intentionally
   removed spawn and one intentional physics prop. Verify the regression
   signal against the real engine.
2. Wire the wrapper to Studio Lab job admission **outside** any active stream.
   Prevent Studio startup if OBS/game latency and host state are unavailable.
3. Collect real gameplay actions and independent completion outcomes on an
   owner-approved private level. The current CLI audit by itself cannot play.
4. Record experiment outcomes in Star Core Forge's local ledger, then compare
   speed/quality on held-out tasks before considering a production promotion.
5. Run a real-time OBS+Roblox+voice+avatar latency study on Windows; require
   stability of gameplay and audible quality before calling Star faster.

**Repository warning:** `oncoursemail/Star-AI-Private` was observed publicly
visible on 2026-10-29 despite its name. Never commit personal memories,
credentials, stream tokens, local places, viewer identities or recordings.
