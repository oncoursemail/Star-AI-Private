# STAR AI: CI recovery, gameplay-event provenance, adaptive intelligence, and expressive VTuber systems
**Researched and updated:** 2026-10-30. **Evidence level:** targeted production code + synthetic tests; hardware/inference/gameplay/OBS results NOT yet measured. **Status:** draft research/engineering plan, not shipping documentation.

## Executive findings grounded in this repository
The full GitHub workflow for `71d3fcd256f5e5c1b66f144efbac0ae54d9f8379` reported **8 failing tests, 14,352 passing, 329 skipped and 562 subtests passing**; React and baseline-gated Pyright passed. The eight failures were caused by compatibility mismatches with the stricter viewer-identity admission, not by a reported GPU bottleneck. The actual failing examples used empty viewer IDs in synthetic fixtures; an overlong ID triggered a constructor exception before the new rejection assertion could run.

**Repair strategy:** update existing fixtures to supply stable, canonical synthetic viewer account IDs; keep production host-identity validation intact; exercise overlong IDs as constructor-validation failures. No live viewer identity is introduced.

**New production edge case:** the existing successful-game-reaction suppression cache records a `game_success` utterance after audio playback regardless of whether its `evidence` was `observed`, `reported` or `unknown`. Thus a spoken but unverified success could hide a genuine verified success arriving moments later. Furthermore, two separate games/levels with identical short descriptions (e.g. "Checkpoint reached") could collide during the 18-second suppression window. The updated `StreamSignal.game_scope` optionally carries a **trusted host-supplied**, bounded scope; reaction receipts now use a digest of scope + normalized description and are written **only after an independently classified observed success is audibly completed**. Empty scope keeps the previous per-stream behavior. Host attestation alone still does not authenticate a game result.

This matters for humanlike streaming: Star should react to **what really happened**, not just the words of a viewer or a previous game session. Accurate event provenance should come before any emotional expression, celebratory motion or model-generated narration. Neither the director nor these tests start a game, inspect frames or send audio.

## New primary-source research (fact versus inference)

| Evidence & publication/update date | Established fact | Design action / caveat |
| --- | --- | --- |
| [GameASG-Bench paper, September 18, 2026](https://arxiv.org/abs/2609.21293) | 47 browser-native game-generation tasks and 12 primary genres; independent L1 static and L2 browser-executed criteria. The highest reported mean L2 check pass rate was 93.2%, while best strict task success was 55.3% (26/47). | Evaluate *whole-task* success, not an average of many easy subchecks. Add predeclared gameplay, scene and UI contracts and reject partial "looks finished" outcomes. Not a STAR benchmark result. |
| [GameWorld, published April 8, 2026; fine-control update August 2026](https://github.com/gameworld-project/GameWorld) | 34 games, 170 tasks; outcome-verifiable game state; a fine-control protocol was released. | Reproduce a legal/private benchmark adapter and collect movement latency, invalid inputs, checkpoints, recovery and transfer-to-unseen-levels. Do not claim game mastery from text descriptions of wins. |
| [Full-Duplex-Bench v3, April 6, 2026](https://arxiv.org/abs/2604.04847) | Benchmarks conversational audio disfluencies, multi-step tool calls and interruptions with real human audio. Self-correction and chained tasks remain difficult across studied voice systems. | Include corrections ("no, I meant the other thing"), overlap, silence, false starts, headset noise and meaningful interruptions in STAR's test set. Do not equate a demo with human-quality voice. |
| [Kyutai Pocket TTS docs; updated October 2026](https://kyutai-labs.github.io/pocket-tts/) | CPU-streamable speech; 100M-parameter model and October small English variants with 18.2M, 6.9M and 1.9M parameters. Official default documentation describes approximately 200 ms first audio chunk in its reference setup. | Candidate **offline opt-in** CPU voice fast path. Benchmark quality, articulation, emotional plausibility, model licensing, buffer underruns and actual OBS sound before integrating. Stated speed is not measured on Star's hardware. |
| [llama.cpp SPEED-Bench, current upstream](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) | Supports category-based throughput/latency comparisons and speculative-decoding draft acceptance; client concurrency should match server slot count. | Run pinned A/B tests using the same GGUF, backend, prompts, slot count and scoring rubric. The fastest aggregate tokens/s does not guarantee better audible streaming latency. |
| [Intuition with Evidence, October 8, 2026](https://arxiv.org/abs/2610.33019) | Reports benefits of combining episodic evidence retrieval and latent memory under adaptive routing on the authors' evaluated benchmarks. | Research candidate for Star Core Forge's provenance-linked memory, not a reason to replace existing memory. Reproduce on STAR's own held-out tasks, with retrieval overhead and hallucinations measured. |
| [llama.cpp server, upstream docs](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | Continuous batching, prompt cache features and optional server-side tool execution exist. Tool execution increases the security exposure of the inference server. | Keep server-side tools disabled by default. Separate real-time inference from privileged local command execution and use explicit capability checks. |

## Priority 0: prove the development branch works
1. Finish the eight legacy test-fixture repairs without downgrading production viewer-identity validation. Make a failing synthetic overlong ID expect a constructor exception, not an admission Boolean.
2. Keep the new scope/provenance tests **offline and deterministic**. In particular: a reported/unknown success cannot suppress a later observed success; identical events within a real game are deduplicated after confirmed playback; separate scopes are distinct; viewer chat cannot inject a scope.
3. Require full GitHub Actions verification for Python tests, Ruff, compilation, Pyright baseline and frontend. If any job fails, inspect its real log before adding more features.
4. GitHub PR status is not a release. Do not merge or deploy the stacked branch without reviewer inspection and complete CI.

## Priority 1: real-time inference and game/stream coexistence
**Scheduling rule:** game input release, audio playback and avatar frames are time-critical; model-generated chat, game-world reasoning and all background learning are preemptible. A single thread must not handle both OBS capture and slow retrieval/model callbacks.

Define a host metrics timeline per *episode*: input timestamp → visual observation received → tactical decision → first model token → first complete speakable phrase → TTS PCM ready → playback device onset → independent OBS audible onset → matching lip/eye motion. Sample p50/p95/p99, not just average token throughput. Record frame pacing, GPU/CPU VRAM/RAM pressure, dropped audio callbacks and voice interruptions. Reject improvements that trade 3% median response gains for visible stutter or incorrect game statements.

**Experiments for an 8 GB gaming GPU (RTX 4060 target):**
1. Benchmark game + OBS + animated avatar **before** launching any model. Reserve observed VRAM headroom, not a guessed fixed value.
2. Compare minimal local reaction planner versus slower deeper reasoning; the small planner may provide a short grounded utterance, while deep reasoning may refine later **only if the answer is still timely**.
3. Move indexed documents, speculative drafts, embeddings and long-context RAG to the CPU/server where practical. Test RAM bandwidth and PCIe transfer costs; offloading is not automatically faster.
4. Compare prompt-prefix caching, llama-server slot count/continuous batching, and speculative decoding on four separated task categories. Cache *validated* prompt/skill versions by content hash, not arbitrary chat content.
5. Under GPU headroom pressure, degrade by priority: skip background generation → fewer perception frames → shorter talk turn → silence. Never block game controls or the physical audio callback.
6. Promotion gate: no new wrong matched questions; no invented gameplay achievements; real OBS audio; stable A/V sync; game FPS and VRAM within individually measured per-title limits. All changes remain opt-in, measured and reversible.

## Priority 2: learn to *play* real supported games
Separate control from deliberation: a bounded local controller runs deterministic movement/aim/stop primitives; a tactical observer reasons over selective keyframes and structured events; a slower strategist plans objectives and practice sessions. No LLM call is required for each game frame.

For each unfamiliar game's private test version, record a machine-verifiable **trajectory capsule**: game/version/seed, legal action vocabulary, timestamped observations, chosen action, observed consequence, expected consequence, confidence and host-gradeable outcome receipt. A hallucinated win never becomes a durable skill. Split practice maps from evaluation maps.

Training curriculum: camera orientation and grounded movement → jumps and collision recovery → timed hazards → interaction/menu reading → enemy tells and bounded combat → inventory and multi-object objectives → navigation requiring memory → cooperative multiplayer private playtesting. Sample independent difficulty levels and cross-title transfer. Require measured success, not simply fewer tokens or prettier narration.

**Controller failure modes:** held keys persist after a crash, window focus changes, observation becomes stale, user stops play, game rules disallow automation, or the model confuses a screenshot overlay with real geometry. The host watchdog must release all inputs, record a failure and yield control immediately. Star should respect game/service rules and use permitted practice contexts.

## Priority 3: become a stronger game creator and designer
Implement a declarative **scene and behavior contract** before generation. For each level: playable path graph, reachable spawn/objectives, prop placement bounds, collision masks, min doorway width, surface material rules, lighting/color identity, camera-safe UI boundaries, frame/perf budget and multiplayer replication invariants.

Use the same *generate → inspect → execute → critique → repair → retest* cycle across:
- Roblox Studio Luau and server/client trust; real multiplayer join/leave and checkpoint tests.
- Blender mesh manifold/UV/normal checks, texture seams, scale, joint rigs, animation curves, clipping and grip integrity.
- 2D/PBR art, clean native-looking UI, legibility at mobile sizes, responsive animations, sound timing, VFX particle counts and frame-time profiling.
- Whole-game behavior including onboarding, fail/retry loops, cooperation, reward/pacing and replayability.

GameASG-Bench's strict-task result demonstrates why `90% of subchecks passed` is not the same as a playable complete game. Require **all critical invariants** to pass before marking a generated prototype as ready.

## Priority 4: long-term knowledge and self-improvement
Build on Star Core Forge, not GitHub as the live brain. Maintain two separate memory tracks:
- **Evidence memory**: cryptographically checksummed source pointers and observed episodes with dates, uncertainty and independent verifier receipts.
- **Abstract skill memory**: concise transferable rules/hypotheses, tagged with the specific evidence supporting them, tested on new examples.

Retrieval must be task-sensitive. A quick in-game question should use a small cached context; deep research can query the full hybrid index. Evidence records are *not instructions*, regardless of whether they come from a website, video transcription, viewer or retrieved document. Preserve source context and record when a document is out of date.

Core Forge runs bounded independent experiments, seeds hold-out challenges, compares against established baselines, logs costs/latency and reverts failed improvements. Keep a rollback-ready local git-compatible history or content-addressed store; GitHub is an optional publishing mirror. Avoid changes that quietly train on the answer keys of future evaluation sets.

Capability roster beyond games: code repair, UI design, math/science explanations, multilingual conversation, document reading, general factual QA with citations, video/audio understanding, music/performance, planning, and everyday software use. Each needs separate held-out tests and explicit tool permissions.

## Priority 5: convincingly natural, transparent AI VTuber
Star should be **recognizable as Star**, not pretend to be a biological person. A stable character identity, lively emotional delivery, well-timed silence, self-correction, playful humor and a credible history of actually observed game events are more useful than fabricated life stories.

Build a streaming state machine: *focused playing*, *reacting*, *listening to chat*, *speaking*, *laughing*, *thinking*, *resting*. Speech intent is conditioned on state; it never directly executes arbitrary chat instructions. Use natural idle gaze, blinking, head tilts, responsive twin-tail physics and facial expressions, coordinated with played audio and observed events. Reduced-motion switch and privacy-safe viewer handling remain mandatory.

**Voice design:** compare Star's existing TTS against an optional Pocket TTS CPU voice using blind listening tests and objectively recorded latency. Support breath groups, short confirmations, real hesitations, non-speech laughter, and a fast barge-in path. Do not clone another person's voice without their permission.

**Speech evaluation scenarios:** unexpected game event while speaking; a human corrects themselves mid-sentence; a spectator overlaps Star's speech; a question is deferred during intense gameplay; teammate voice vs chat message; game success reported but not observed; loss immediately after claimed victory; OBS captures silence despite TTS callbacks; viewer tries to inject instructions through text. Grade conversational appropriateness, truthfulness and cancellation correctness independently.

## Acceptance matrix and deployment criteria
| Dimension | Minimum evidence before any owner-reviewed live rehearsal |
| --- | --- |
| Core CI | Python tests, Ruff, Pyright gate and frontend checks all pass at the *exact PR head* |
| Gameplay truth | 0 unsupported success claims; game evidence witnessed independently of viewer chat |
| Perception/control | 100% safe release after stop/focus loss in synthetic watchdog tests; real game outcomes measured |
| Gaming skill | Held-out success rate, attempts, action validity, recovery time, title-specific FPS |
| Roblox creation | All critical scene/behavior contracts and executable tests pass (not just aggregate score) |
| General intelligence | Source-backed knowledge accuracy, citation opening, task-level correctness and latency |
| Speech | Actual captured audible output, interruption/turn overlap tests, measurable A/V sync |
| Personality | Consistent original mascot/style, appropriate emotion and purposeful silence; transparent AI identity |
| Rollout | Local/reversible, opt-in; explicit host approval for high-risk, external or irreversible actions |

## Responsible completion order
**Now:** repair inherited CI test-fixture regressions; retain the new provenanced success-dedup behavior and tests, then check CI. **Next:** one reproducible Windows private-game + OBS recording harness with event/A-V timestamps, not more disconnected "features." **After measured baseline:** compare CPU voice variants, model fast paths and chunked turn-taking; run held-out gameplay and whole-task building evaluations. **Later:** Core Forge may propose sandboxed experiments, but no unreviewed release, public livestream or external spending should arise from a benchmark recommendation.

**Current limitations:** no new Windows GPU/OBS run, no verified increase in model IQ, no new real game mastered, and no actual naturalness preference study in this change set. The repository named `Star-AI-Private` was visible as **public** in repository metadata; treat any sensitive settings/recordings as at risk until repository visibility is corrected and secrets are audited.
