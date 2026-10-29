# STAR — Evidence-Gated Intelligence, Speed, Gaming and VTuber Research
Date: October 29, 2026

## Implemented: pre-registered multidomain intelligence/speed comparison

A lightweight dependency-free Python component, star.upgrade_evidence_gate,
now compares an entire candidate AI route, model configuration, or learned
capability against a fixed baseline. Unlike tokens-per-second tests alone,
this comparison examines independently scored task success and paired
end-to-end response latency.

Six domains are protected separately: general_knowledge, coding,
roblox_build, gameplay, stream_dialogue, and safety. A fast model cannot
hide a gameplay or safety regression behind improvement in ordinary coding.
The evaluation input contains only bounded symbolic task IDs, task-scene
digests, scorer digests, completion/success flags, observed latency, VRAM
peak and declared AB/BA order. No prompt text, game captures, streams,
speaker identifiers, viewer chat, credentials, or other private material
are required by the comparator.

The comparator verifies unique pre-registered cases, matched evaluator
and environment digests, exact paired A/B observations, AB/BA order
balance, no best-of-many duplicate submissions, all six domains,
minimum quality floor, low p95 latency, VRAM headroom and safety tests.
Its verdict is one of eligible_for_owner_review, inconclusive or regressed.
It cannot promote an upgrade or change runtime settings.

Default *experimental* decision thresholds: 12 completed held-out
pairs per domain (72 pairs / 144 observations total), 30%-70%
AB/BA balance, candidate success >=70% per category, a maximum 5
percentage point observed decline, a paired-bootstrap latency
improvement lower confidence limit >30 ms, candidate p95 no worse
than baseline, and a configurable GPU peak memory budget. Safety
violations, lost safety checks, category quality loss, VRAM overage
and serious tail latency increases veto a candidate.

The 95% bootstrap intervals and thresholds are *heuristics*, not a
guarantee of human-level skill or causality. Small evaluation sets and
multiple comparisons limit their conclusions. Host evidence flags and
SHA-256 digests are not signatures; independent authentication must
be built upstream.

### Run local validation

    python -m pytest -q tests/test_upgrade_evidence_gate.py
    ruff check star/upgrade_evidence_gate.py tests/test_upgrade_evidence_gate.py
    python -m py_compile star/upgrade_evidence_gate.py

This is a tested offline evaluator, **not a measured model improvement**.
No model has been trained or deployed, no stream or Roblox game launched,
and no actual inference-speed gain measured in this change.

## Primary sources checked October 29, 2026

1. TRACE-Router, July 24, 2026. Task-level consistent model routing
   makes terminal task outcomes more meaningful than independent
   per-message token decisions. The published benchmark improvements
   belong to its authors, not STAR:
   https://arxiv.org/abs/2607.22465
2. ODAR, February 27, 2026. Investigates allocating fast heuristics
   versus slower deliberation when tasks differ in difficulty. Real
   hardware and local task benchmarks are still essential:
   https://arxiv.org/abs/2602.23681
3. llama.cpp SPEED-Bench. Benchmarks an existing llama-server
   with throughput, latency and speculative draft acceptance; do
   not assume n-gram/MTP/EAGLE speculative configurations are faster:
   https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
4. Roblox OpenGameEval, published October 2026. Stateful Studio
   tasks with executable scene and play-session verification. Its
   84-task benchmark provides a model for independently checking
   game construction, not simply compiling generated Luau:
   https://github.com/Roblox/open-game-eval
5. GameWorld, published April 2026. 34 games / 170 tasks with
   serialized game-state outcomes; better for testing transferable
   gaming than claims based on a model's own visual narration:
   https://gameworld-bench.github.io/
6. LiveKit's documented 2026 turn-handling stack separates VAD,
   end-of-turn detection, genuine interruptions and incidental
   speech/backchannels. Star's streamer voice needs these as
   different problems, not one silence threshold:
   https://docs.livekit.io/agents/logic/turns/
   https://livekit.com/blog/turn-detection-and-interruption-handling

## Recommended architecture for stronger, faster intelligence

### Independent evidence for Star Core Forge

Before an experiment starts, Core Forge should produce a frozen local
manifest of task IDs, baseline and candidate source/config digests,
suite version, scorer version and a non-model-visible held-out split.
A trusted host, not an LLM, must create signed immutable evidence and
pin the actual game scene, model and hardware configuration.

The current evaluator supplies the comparison policy, not the
signature verification or experiment-running host. Keep those outside
model context. Never use a hidden holdout set repeatedly to choose
the best of hundreds of candidates: that turns the holdout into
training data and destroys a simple confidence interpretation.

### CPU/GPU-aware multi-brain architecture

Keep game movement, render FPS, Windows audio, mouth/eye animation
and OBS on protected low-latency lanes. Quick local models handle
short conversational turns and immediate perception. Larger reasoning
or multi-agent teams handle complex tasks when headroom exists, or
run on the other authorized computer outside live hours.

Measure wall time to a *correct finished task*, first-audible speech
latency, p95 inference delay, cache hits, peak VRAM, 1%-low game FPS,
OBS frame loss, voice overlap and mouth-sync from real recordings.
Mixed contexts and randomized A/B order reveal false gains from
cache-sensitive repeated prompts. Preserve batch/Python memory budgets.

Only pass a new route to owner review if its held-out results survive
the six-domain comparison; separately apply the existing
stream_output_qoe_gate when changing live speech configurations.
Never auto-deploy from either comparator.

### Gameplay learning loop, not just gameplay descriptions

Connect authorized game capture to controlled game actions, time-aligned
observations, independent achievement flags and replayable practice
episodes. Randomize game seeds and hold out maps/versions. Teach
Star to diagnose errors, build new strategies, train on increasingly
harder tasks and retest transfer to unseen mechanics.

For Roblox creation combine pre-edit scene inspection, editable
geometry/dependencies, actual Studio engine regression checks,
real-user-input playthroughs, networking tests, UI overlap checks,
and a visual art-quality review. Perfect-looking images alone do
not prove a playable, correct game.

### Broader verified knowledge

Grow her source-checked factual and creative libraries with domain
versioning, source date, license metadata, confidence and conflicts.
Separate general factual memory from subjective social memories,
gameplay episode evidence and model-generated guesses. Route fresh
queries to source verification when the topic changes quickly.
A larger text database is not by itself better reasoning.

### Natural, humanlike AI VTuber (with transparent AI identity)

A natural streamer chooses when to stay quiet, concentrate, reply to
chat, laugh at actual unexpected events, interrupt, accept correction
and tell a grounded story about something she actually experienced.
Coordinate her voice, eye gaze, blinking, hair motion, facial
expression and timing on the same output clock. Her distinctive
interests and hobbies should evolve from real experiments, drawings,
gaming experiences and interactions rather than fictional human
experiences presented as fact.

Assess the finished Windows OBS output with human blind preference
ratings as well as audio/video metrics, interruption errors, p95
chat responsiveness and grounding in verified episodes. Differentiate
the cadence of calm chatting from intense gameplay.

### Staged implementation priorities

1. Integrate this evaluation comparator with Core Forge's local
   experiment registry; seal plans and host evidence, independent of AI.
2. Add trustworthy streaming-conversation and game-win observation
   adapters; score task-level outcomes rather than partial model turns.
3. Run actual locally authorized benchmark A/B experiments on Brain 1
   and Brain 2 with GPU/CPU models, mixed workloads and no stream load.
4. Integrate existing OBS quality evidence with gameplay + voice
   experiments, while measuring true first-audible latency and FPS.
5. Only after owner review, canary a successful configuration with
   automatic rollback and performance monitoring. GitHub remains an
   optional publication mirror, not required for local self-improvement.

## Boundaries

The evaluation package does not grant device control, broadcast
permission, in-game actions, spending, secrets access or publishing.
New abilities remain OFF until enabled by an authorized local host.
Host-provided results are not inherently authentic. No direct
intelligence, game-mastery, FPS or human-quality improvements were
measured in this code-only run. Star should be judged by reproducible
real experiments, not optimistic features or cherry-picked clips.

A repository whose name contains Private may still be public. Do
not upload private chats, local files, viewer information, API keys,
model weights with incompatible licenses, private recordings or
unreviewed internal memory to such a repository.
