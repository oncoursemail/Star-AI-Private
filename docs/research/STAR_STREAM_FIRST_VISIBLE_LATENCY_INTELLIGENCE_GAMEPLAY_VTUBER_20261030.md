# STAR: first-visible inference latency, faster intelligence, and believable gaming VTuber — 2026-10-30

## Status and actual implementation

This research accompanies the **opt-in** `star/inference_stream_benchmark.py` and
`scripts/benchmark_star.py --stream-startup`. It is **not** a model upgrade,
self-training, improvement in overall tokens/sec, autonomously controlled game,
or a proven improvement to live speech latency.

Unlike an ordinary nonstreamed completion benchmark, the new runner:
- measures the time from real request dispatch until **nonempty visible content**,
  ignoring empty role deltas, reasoning-only deltas, and transport chunks;
- separately measures **fully completed** response latency;
- rejects interrupted, timed-out, truncated, missing-finish, and empty responses
  rather than treating an early partial response as success;
- reuses the exact, synthetic and hashed workload of
  `star/inference_benchmark.py` for mixed, repeat, and long/short canary cases;
- explicitly labels warm-prompt repetition as cache-biased; uses a bounded 8
  requests, 2 parallel streams, and 45s per request, with no saved model output;
- uses STAR's existing localhost / private-LAN endpoint validation and
  keyring-backed client; never runs a benchmark automatically or starts a
  stream, opens Studio, or changes a running model;
- reports p50/p95 first-visible vs p50/p95 completion; a broken canary or
  incomplete stream is not counted as a successful speed result.

Manual command **only while the model endpoint is idle/owner-approved**:

```sh
python -m scripts.benchmark_star --endpoint http://127.0.0.1:8080/v1 --model YOUR_MODEL_ID --stream-startup --requests 4 --parallel 1
python -m scripts.benchmark_star --endpoint http://127.0.0.1:8080/v1 --model YOUR_MODEL_ID --stream-startup --workload canary --requests 4 --parallel 1
# Existing full-completion benchmark is still the default without --stream-startup.
```

Never run these extra requests during live OBS or gaming. Do not publish raw
logs, keys, model responses, private addresses, real viewer inputs, or game
recordings. The benchmark deliberately does not store any such material.

## Why this is a critical speed measurement

There are *five distinct latency stages* for STAR speaking while gaming:

1. `t0`: verified/curated game event selected and speech requested;
2. `t1`: first **visible** token from the response stream (this PR measures
   `t1 - request_start` only);
3. `t2`: enough words accumulated for first correctly pronounced TTS chunk;
4. `t3`: first PCM frames actually accepted/consumed by the audio device;
5. `t4`: OBS/output-recording first independently detected audible waveform,
   with aligned mouth animation.

A faster `t1` cannot imply a faster `t4`: sentence segmentation, audio model
startup, CPU contention, device buffering, animation frame pacing, and OBS
encoding may dominate. Production dashboards must never equate streaming
transport-startup with real speech. Preserve STAR's existing
`StreamPlayoutClock`, audio avatar session, OBS output evidence, and paired QoE
gates. Add a *future* narrowly scoped trace that correlates opaque event IDs and
host clock timestamps across the five stages without collecting transcripts.

Compare at least three randomized paired A/B rounds per hardware/load regime,
after separate cold-start and warm-start calibration; report distribution
p50/p95 and the confidence interval, not one flattering run. Streaming
latency and full-task *correctness* must both improve. Evaluate during a
separate nonbroadcast rehearsal while measuring game FPS/OBS frames.

## Research findings and highest-value next engineering decisions

### 1. Fast local inference without sacrificing reasoning

**Verified upstream:** llama.cpp supports multiple speculative decoding
methods including smaller draft models and draftless n-gram approaches. Its
SPEED-Bench runner reports throughput, latency and draft acceptance. These
features need **per-model measurements**, not blanket enabling:
- On 8 GB gaming VRAM, a GPU-resident draft model may evict more useful game
  or vision memory and make actual response latency worse. Test draftless
  n-gram, then CPU draft, only then additional GPU model residency.
- Keep the system persona and stable safety context prefix identical across
  requests when possible; inject fresh visual/chat evidence in a bounded
  lower-priority message instead of rewriting the prefix.
- Route **task outcomes**, not prompts, through multiple candidates:
  easy, low-risk commentary -> fast local model; hard debugging/research ->
  larger deliberative lane; practice movement -> low-latency, bounded control.
- Keep per-regime metrics (game active vs idle) and reject improvements
  if they reduce correct game completion, inference quality or stream stability.

Primary upstream references:
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**Actionable experiment:** on idle Brain 1, run matched workload digests under
baseline vs speculative config; rerun with actual Windows gaming load to check
CPU, GPU and resource contention separately. Record first-visible, complete,
quality, energy, VRAM, and canary mismatch rates; do not change production
until independent gates accept the candidate.

### 2. Autonomous gaming that learns skills instead of memorizing prompts

**Verified research:** GameWorld (arXiv:2604.07429, 2026-04-08) contains
34 games and 170 outcome-verifiable tasks. It emphasizes both slow strategic
reasoning and fast motor control; the *paused* track and real-time interaction
track answer different questions. Do not present paused benchmark success as
high-FPS game mastery. See https://arxiv.org/abs/2604.07429 and
https://gameworld-project.github.io/ .

**STAR implementation sequence proposed, not completed here:**
- Pick a *private offline* target with 10 simple platforming objectives.
- Snapshot scene state; let STAR *inspect before edit/play*; record hypotheses
  about physics, input mapping, moving platforms and timing.
- Allow bounded authorised actions; independently witness a checkpoint,
  respawn, damage, collision and finished objective.
- Precommit predicted success before action. Compare actual outcome to the
  forecast, and save verified failure causes without laundering guesses into
  permanent knowledge.
- Increase difficulty only when a held-out level demonstrates transfer.
  Maintain clear separate **practice**, **validation** and **holdout** splits.
- Report attempts-to-completion, checkpoint rate, action invalidity,
  recalibration, elapsed time, and runtime FPS. Make no claim of playing
  public multiplayer games without a game's explicit permitted interface.

Roblox's OpenGameEval (2026-10-01) measures 84 Studio agent tasks with
executable scene/play checks; inspecting relevant objects is associated with
better success. See https://arxiv.org/abs/2610.02563 and
https://github.com/Roblox/open-game-eval . The official Studio MCP
documentation supports script operations, playtesting and multiple Studio
instances with explicit `studio_id`. For STAR's two-PC setup, isolate
test places and bind each action to the designated instance:
https://create.roblox.com/docs/studio/mcp .

### 3. Entire game creation: polish **and** playability

CEGame-Bench, published 2026-10-19, tests long-horizon game building across
Defold, Godot, Roblox Studio, Unity and Unreal; only 16% of evaluated game
runs reached the ending. A build/compile pass does **not** establish a game
works as a player experience. https://arxiv.org/abs/2610.26098

Build each project as a requirement-driven, measurable journey:
- Visual scene layout and reachable path topology: geometry overlaps, missing
  walls, clipping/texture interference, lighting, occlusion, bad props;
- Interaction: controls, jumps, objectives, inventory, NPC and combat behavior;
- Presentation: mobile/desktop UI legibility, VFX occlusion, consistent art,
  animation attachments, rig/body alignment, audio;
- Player journey: launch -> spawn -> progress -> save -> separate-process
  reopen -> restore -> end -> postgame return;
- Independent tests and captured visual diffs at representative camera
  positions, then blind quality review and minimal repair patches.

Use existing STAR `game_journey_completion` and Studio visual quality gates
rather than adding parallel green-check dashboards. Compare baseline and
candidate *the same place version*, with withheld scenarios.

### 4. A natural, charming AI VTuber: **latency + meaning + movement**

Believable streaming is not a prompt telling Star to say "haha" or exaggerate
emotion. It comes from *timely, grounded* attention and synchronized
expressions, with permission for silence:
- **Situation planner:** verified small win, failed attempt, surprise,
  incoming conversation, timeout, silence and concentration each have
  different reply urgency. During precise jumps, say nothing; brief reactions
  follow verified outcomes and never turn a single success into a claim that
  the whole game was won.
- **Turn-taking:** distinguish someone still speaking from a real stop, and
  short noises/backchannels from intentional interruptions. LiveKit's
  documented `v1-mini` locally runs on CPU; its interruption API handles
  adaptive interruption and false-interruption recovery. These are useful
  *candidates*, not verified STAR hardware wins.
  https://docs.livekit.io/agents/logic/turns/turn-detector/
  https://docs.livekit.io/reference/agents/turn-handling-options/
- **Voice:** Kyutai's Pocket TTS 4.0.0 (2026-10-20) introduced smaller English
  18M/7M/2M candidate models; v4.0.1 (2026-10-21) fixed small-model issues.
  Compare first real audio chunk, natural pauses, phrasing and emotion,
  pronunciation, laughter naturalness and continuous-chat stability on
  STAR's CPU under gameplay load. Do not substitute benchmark claims from
  different hardware for STAR's measured results.
  https://github.com/kyutai-labs/pocket-tts/releases
- **Rig:** drive amber eyes, natural blinks, genuine smiling/surprise, head
  turns, indigo-to-gold twin tails and cloth secondary motion from a bounded
  event plan. Keep the original approved chibi style, mirrored-safe pointing,
  no clipping hands, and reduced-motion OFF by default.
- **Personal continuity:** she can have interests, humor, goals, preferences,
  and memories of verified activities. Fictional lore should be marked as
  lore. Never invent real friendships, off-stream game achievements or
  a human life; visibly identify her as an AI personality.
- **Viewer experience:** moderator-validated, consent-aware, private-info-safe,
  bounded delayed chat; responses to interruptions, focused silence, variety
  in phrasing, and occasional independent curiosity. No untrusted game/chat
  text should promote itself into instructions or system permissions.

### 5. Broader general intelligence: evidence over accumulation

A more useful STAR memory is not a bigger pile of web pages. Four levels:
1. Primary external source with publication date, version, licence,
   scope, retrieval time and change detection;
2. Local user-project facts tied to a commit, scene/object path, test
   receipt and expiry/freshness policy;
3. Episodic "I attempted X, observer verified Y" with uncertainty and
   revoked/failed-trial status, separated from entertaining fiction;
4. Skill cards: objective, successful procedure, tools, environment, passing
   tests, failure patterns and expected cost.

Store durable material in Star Core Forge first (offline-first) and export
chosen code/research outward to GitHub as a reviewable draft. Testing and
rollback must exist independently of GitHub. Keep risky external actions
owner-gated and routine authorized actions independent.

### 6. Concrete acceptance criteria and rollback

A speed candidate should be **rejected** if its measured output is truncated,
corrupted, produces stale canary state, degrades held-out quality, delays
first audible speech, raises OBS dropped frames, reduces game FPS, or
increases model resource pressure beyond the reserved budget. Performance
claims must report actual hardware, load and methodology.

A game-intelligence candidate should be **rejected** if its progress comes
only from repeatedly memorizing practice levels, uses holdout leakage,
invents unobserved game facts, or produces no increase in independently
verified completed objectives.

A naturalness candidate should be **rejected** if naturalistic prompts
generate false human autobiographical claims, invented achievement stories,
overlapping speech, forced nonstop chatter, audio/rig desynchronization,
repeated stereotyped squeals, or broken reduced-motion behavior.

**Current evidence:** new streaming startup parser, report and fake-server
tests only. No actual inference speedup, real model startup times, new
gameplay achievements, voice-generation speed, rig quality, or OBS
improvements are demonstrated by this change.
