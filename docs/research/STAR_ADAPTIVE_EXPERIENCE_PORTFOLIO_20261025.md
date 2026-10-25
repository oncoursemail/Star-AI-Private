# STAR adaptive experience portfolio — research and implementation
**Research date:** 2026-10-25
**Status:** Offline, review-only engineering increment; not a deployed intelligent gamer or VTuber.

## Executive result

STAR already has a large collection of experimental model routing, lesson capture,
self-play, Studio Lab, UI/VFX, video, and livestream components. More unconnected
features alone will not make her more intelligent. The measurable bottleneck is
**which experiment to run next, which observations are independently verified,
which discoveries transfer to unseen tasks, and how much learning benefit is
obtained per second of limited compute without destroying stream responsiveness.**

This change adds `star/experience_portfolio.py`: a deterministic, zero-dependency
planner that proposes a bounded portfolio of offline rehearsal tasks across
`gameplay`, `game_creation`, `streaming`, `knowledge`, and `inference`.
It prioritizes estimated learning potential, novelty, and a modest domain-diversity
bonus while respecting strict wall-time, GPU-headroom, host approval, networking,
and live-stream constraints.

It **does not** learn model weights, execute the proposals, authenticate the
receipts, or claim a real-world speedup. It deliberately excludes holdout scores
from the learning scheduler so future evaluations are not optimized against.

## Why this architecture instead of a bigger pile of prompts

1. **Automatic curricula work best with feedback**. Voyager combines an
   automatic curriculum, reusable skills and feedback-driven refinement. It
   reports transfer from learned Minecraft skills, not magical general
   intelligence: https://voyager.minedojo.org/
2. **Not all replays are equally valuable**. Prioritized Level Replay (ICML 2021)
   uses estimated future learning potential to select useful game levels.
   STAR's current formula is only a lightweight proxy, *not* PLR's trained
   temporal-difference algorithm:
   https://proceedings.mlr.press/v139/jiang21b.html
3. **Transfer must be tested on environments not seen during practice**.
   DeepMind's SIMA 2 studies actions and reasoning in unfamiliar 3D games;
   its held-out environment methodology matters more than copying its claims:
   https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
4. **The Roblox host now has useful supported playtest tools**. Roblox's March 5,
   2026 Studio MCP announcement describes playtest start/stop and simulated
   input. Never treat an MCP connection alone as an editing permission.
   https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
5. **Conversational timing is its own intelligence problem**. NVIDIA PersonaPlex
   tackles duplex speech; June 2026 DyaPlex extends continuous perception and
   generation to synchronized motion. A September 2026 turn-taking paper
   distinguishes listener response intent from end-of-utterance completeness.
   None is integrated by this PR:
   https://research.nvidia.com/labs/adlr/personaplex/
   https://research.nvidia.com/labs/amri/projects/DyaPlex/
   https://www.alphaxiv.org/abs/2609.34096

## What the new module *actually* does

The caller supplies **typed task candidates**, **host-sourced outcome receipts**,
and a **resource budget**. A candidate carries an exact domain, scenario ID,
estimated execution duration, projected GPU allocation, network requirement,
and an affirmative host-approval flag. Do not construct that last flag from
a candidate model's response. A receipt supplies a task ID, environment ID,
sequence number, score between zero and one, and `practice` or `holdout` split.

The pure planner:

- Excludes offline rehearsal whenever `live_streaming=True`. This keeps
  optional self-improvement from stealing frame time while gaming live.
- Rejects unapproved, network-required (unless separately allowed), oversized,
  GPU-over-budget, and over-duration candidates.
- Counts at most one independent `practice` outcome per task/environment,
  rather than rewarding repeated replays of one easy seed.
- Ignores *all* `holdout` outcomes when computing priority or ordering tasks.
- Estimates learnability from challenge level, uncertainty, independently
  observed improvement over chronological windows, and underexplored domains.
  Estimated rehearsal time is a modest cost penalty; this is a **heuristic**
  and should be validated with controlled comparisons before trusting it.
- Spreads selected work across distinct scenarios with a modest diversity
  bonus for the first rehearsal in a domain, while honoring max tasks and
  total estimated duration.
- Returns a versioned, explicit `practice_proposal_only` report with
  `executable=false` and `model_trained=false`. No network, file writes,
  external subprocesses or model calls occur inside the planner.

Example (untrusted JSON only produces *suggestions*, never authority):

```bash
printf '%s' '{"tasks":[{"task_id":"obby-nav-seed7","domain":"gameplay","scenario_id":"obby-seed7","estimated_seconds":120,"gpu_mb":0,"host_approved":true},{"task_id":"laugh-timing-rehearsal","domain":"streaming","scenario_id":"voice-seed2","estimated_seconds":60,"host_approved":true}],"receipts":[],"budget":{"max_seconds":180,"max_tasks":2}}' | python -m star.experience_portfolio
```

The CLI's `host_approved` field is **untrusted input**; the program intentionally
does not provide an executor. A privileged host must separately resolve
authorization from its own policy and independently verify receipt provenance.
Do not feed a model's prose "passed" directly as an independent test receipt.

## High-impact next integrations (not implemented in this increment)

### A. Autonomous game playing that *gets better* across games

Use the existing guarded Studio Lab or other explicitly authorized game-test
environment as the only actuator. Record screenshot / video / HUD observations
with timestamps, action IDs and source identity. The current navigator/pilot
proposes a move, host actuates it, then independent observation checks position
and objective completion. Failed hypotheses become candidate repairs, not
instant reusable skills.

For transfer, separate **practice seeds**, **validation seeds used for development**,
and **sealed held-out environments**. Measure success rate, retries, time per
objective, stuck recovery, game FPS, and skill reuse on unseen games. Track
gameplay competence by *class* (platforming, survival, navigation, puzzle,
combat and economy), never by one memorized obby map. Start with a tiny
sandboxed benchmark before connecting to multiplayer games.

Promote skills only through the existing independently owned evaluation gate;
the portfolio planner cannot grant promotion. Preserve fixed baselines,
versions of input observations, and crash-safe logs.

### B. Roblox game creation and design quality

Separate game specification, semantic scene graph, spatial constraints, asset
selection, final in-engine validation and human-quality review. For example:
wall continuity and support contacts, snapped door/window openings, consistent
collision groups, no anchored-interpenetration, minimum thickness, z-fighting,
texture orientation and scale, lighting budget, rig pose, and working HUD
layout at desktop/mobile sizes. Add game-feel metrics: recoil/feedback,
camera response, UI animation and audio-reactive moments. A beautiful screenshot
cannot validate physics, controls, sound, accessibility or replication.

The practice portfolio can schedule standalone UI critique, building-integrity
retests, VFX benchmark shots and actual playtests as **different scenarios**
instead of reusing the same demonstration footage. Success must come from
rendered results and executable playtest checks, not model confidence.

### C. Humanlike, entertaining—but transparent—VTuber STAR

Aim for a consistent AI character rather than pretending to possess a human
biography or consciousness. A natural stream director should decide not only
*what* to say but **whether to speak at all**, and when to pause, backchannel,
or let a difficult game moment breathe. Preserve context across interruptions;
do not repeatedly read chat while aiming, fighting, or listening to audio cues.

Proposed event architecture:

`timestamped game/video/chat/audio → grounded event ledger → urgency +
attention score → talk/wait/gesture decision → text/prosody → chunked voice →
playback acknowledgment → eye/head/mouth/body/hair/ears/tail animation`

Use gameplay-specific expressive behavior: eyes track the objective before a
head turn; giggles follow real successes or jokes; mouth shapes match actual
audio, not text length; physics secondary motion continues without jitter;
black-cat/puppy modes adjust ears, tails and vocal playfulness while preserving
STAR's existing gold/indigo identity. A fictional character lore bible can
provide continuity, but on-stream anecdotes must be labeled fictional when
they refer to experiences the system did not actually have.

Measure separately: end-of-speech-to-first-audio p50/p95, interruption
cancellation success, caption/voice/mouth alignment error, speech overlap,
stale chat responses, OBS dropped frames, GPU memory peak, conversational
repetition, and human preference in blinded A/B comparisons. More words are
not automatically more engaging.

FacePlex (June 2026) is another research direction for synchronized online
face and voice; this is a paper, not a ready drop-in STAR dependency:
https://arxiv.org/abs/2606.30145

For studio control use authenticated local OBS WebSocket (OBS 28+ bundles
obs-websocket), password protected, least privilege, with no auto-broadcast:
https://github.com/obsproject/obs-websocket
Never allow a candidate model to switch scenes or go live through text alone.

### D. Reasoning, general knowledge and learning efficiency

Build durable knowledge in stages: source discovery → rights/licensing check →
capture with publication/fetch dates and source hash → passage-level retrieval →
multi-source contradiction checks → host evaluated examples → owner approval or
quarantined candidate notes. Retrieval stays opt-in where STAR policy requires.
Do not scrape everything into context; irrelevant background increases prefill
latency and creates contradictory memories.

Separate *knowledge acquisition* from *parameter updates*. Better retrieval,
tools, verified worked examples and context caching can increase performance
without retraining weights. Fine-tuning requires carefully licensed examples,
offline retention tests and rejection if coding, conversation or game metrics
regress. A memory index with a million unverified chunks is not a million
newly learned skills.

### E. Inference and infrastructure on the actual PCs

On 8 GB VRAM devices, GPU headroom and active game/OBS FPS are hard constraints.
Do not assume that game rendering, avatar physics, video vision, a speech model
and a large reasoning LLM all fit at once. Prefer separate queues and
backpressure: high priority live input/ASR/TTS, medium context updates,
lowest priority background retrieval, practice and indexing. Offload long
research and index building to another host where measured bandwidth allows.

Benchmark identical prompts, generation settings and warm-up regimes before
enabling n-gram speculation or a draft model. The official llama.cpp docs note
ngram speculation requires no extra model but depends on token repetition:
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
The project also publishes a dedicated SPEED-Bench client:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Hold constant quality (offline graders) while comparing: time-to-first-token,
output tokens/s, first-audio latency, end-to-end p95, VRAM/RAM peak, live-game
FPS and dropped frames. Promote only improvements with meaningful repeatable
results and no failed safety or compatibility checks. Input-side caching does
not inherently improve reasoning accuracy.

## Novel experiments worth testing (hypotheses, not discoveries)

1. **Evidence Return on Compute:** evaluate *independently confirmed improvement
   per rehearsal-second* against uniform and difficulty-only curricula.
   Reject the new heuristic if it is slower or overfits known maps.
2. **Speaking as an action:** treat silence, question acknowledgment and
   short laughter as actions with costs and context-dependent rewards, not
   merely generated words; evaluate viewer perception with blinded clips.
3. **Skill transfer passports:** store skill version, authorized environment,
   successful out-of-distribution tests, latency and failure boundary. A game
   transfer is genuine only if a new environment is passed without editing
   the evaluator.
4. **Counterfactual dual-track evaluation:** compare the same replay under
   baseline reasoning and a candidate skill, with deterministic simulated
   game seeds and identical observation budgets. Use a separate live pilot
   to detect simulator-to-game reality gaps.
5. **Automatic attention-budget shaping:** use streaming QoS history to defer
   expensive learning campaigns until there is stable CPU/GPU headroom.

## Acceptance ladder

1. **Now:** offline tests validate input bounds, independent-receipt accounting,
   holdout isolation, planning diversity, live-stream pause, deterministic
   selection, JSON parser hardening and total time/GPU budgets.
2. **Next:** connect to host-authenticated rehearsal manifests from existing
   learning and playtest tools; receive actual signed run provenance or
   trustworthy local-only receipts; no candidate self-approval.
3. **Then:** compare against uniform random, round-robin and easy-first on
   at least 30 unseen scenarios per domain with equal compute budgets.
   Report 95% intervals; do not claim increased learning speed without data.
4. **Only after review:** opt-in scheduling of bounded rehearsals. Keep actual
   gameplay, video watching, avatar playback and broadcasts off until the
   owner explicitly enables them.

## Verification scope

Tests are local deterministic software tests, **not** Roblox Studio tests,
GPU benchmarks, speech-listening tests, human-subject experiments, or evidence
of model-weight improvements. Protect `star/next`; use a draft PR with full
CI required before considering a merge.
