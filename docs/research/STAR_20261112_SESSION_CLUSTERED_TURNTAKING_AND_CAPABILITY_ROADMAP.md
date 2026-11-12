# STAR Session-Clustered Turn-Taking Evaluation and Capability Roadmap

**Date:** 2026-11-12  
**Status:** Implemented as an opt-in-capable offline evaluator; cluster-aware acceptance is the default for new validation calls.  
**Target:** Draft PR stacked on the single-use holdout ledger. Production `main` and the v1.0 installer remain unchanged.

## Executive findings

The previous STAR turn-policy evaluator split calibration and holdout data by conversation/session group and protected holdouts from reuse with a local SQLite ledger. It still calculated pause-level Wilson bounds as though every pause were independent.

That assumption is unsafe when dozens of pauses come from the same conversation. Pauses within a session share speakers, microphone conditions, conversational style, language, topic, latency conditions and turn-taking habits. A test set containing 1,000 pauses from 10 sessions does not provide 1,000 independent session observations.

This change adds a session-cluster bootstrap and a second, session-incidence guardrail. It does not replace the existing causal evaluator or one-use ledger.

## Research findings

### 1. Resample the unit that was independently sampled

Huang (2016), *Using Cluster Bootstrapping to Analyze Nested Data With a Few Clusters*, compares cluster bootstrap standard errors with alternative methods across cluster counts, cluster sizes and intraclass correlations. The paper notes the computational cost and discusses cluster bootstrap as an alternative when group-level effects are the target.

Source: https://journals.sagepub.com/doi/10.1177/0013164416678980

STAR's independent unit is the conversation/session group, not an individual pause. The implementation therefore samples complete session groups with replacement and retains every pause inside each sampled group.

Important limitation: ordinary cluster bootstrap is not a universal fix for very few clusters. STAR adds an independent-session incidence bound and a derived minimum-cluster gate; simulation and external benchmark coverage checks remain necessary before using the result as a production claim.

### 2. Preserve causal voice evaluation

LiveKit's eot-bench evaluates the decision at real pauses in complete human-to-agent turns. Its public data covers 14 languages and labels mid-turn pauses separately from the final pause. It compares false cutoffs against endpointing delay and includes a silence-only baseline.

Source: https://github.com/livekit/eot-bench

This supports STAR's existing causal pause schema. A future adapter should preserve dataset revision, language, license, adapter version and conversation/session boundaries. Each score must use only the audio and context available at that timestamp.

### 3. Keep end-of-turn and interruption separate

A detector that recognizes a completed human turn is not automatically a safe barge-in detector. STAR should separately measure:
- end-of-turn detection after the viewer finishes;
- genuine human barge-in while Star is speaking;
- false interruption from acknowledgements or background speech;
- cancellation latency from barge-in to TTS stop;
- recovery latency before Star resumes a thought.

Do not collapse these into one voice-accuracy score.

### 4. Treat model throughput and conversational latency as different clocks

The official llama.cpp SPEED-Bench client benchmarks an already-running server and recommends matching client concurrency to the server's configured slot count. It reports throughput, latency and speculative-draft acceptance.

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

STAR should compare identical model hashes, quantization, context, prompt sets, output budgets, concurrency and warm/cold state. Record TTFT, inter-token latency, full request duration, first generated audio, first audible playback, audio underruns, game frame-time p99, and OBS render/output skips.

A faster model response does not prove a faster audible response.

## Implementation

### New module: `star/stream_turntaking_cluster.py`

The module provides:

- Whole-session bootstrap resampling rather than pause-row resampling.
- Separate resampling populations for false cutoffs (sessions with HOLD pauses) and missed final turns (all sessions).
- Pooled pause-level rates alongside cluster-resampled uncertainty intervals.
- Session-incidence rates: fraction of hold-bearing sessions with any false cutoff, and fraction of all sessions with any missed final turn.
- One-sided Wilson upper bounds over independent session-incidence outcomes.
- Mean session p95 endpointing latency with a cluster-bootstrap interval. This is explicitly not mislabeled as the global p95.
- Deterministic seeds and bounded replicate counts.
- Aggregate-only output with no source IDs.

### Default acceptance behavior

New calls to `select_and_validate_turn_policy` use cluster-aware acceptance by default. Callers can explicitly set `cluster_aware=False` for legacy pause-level diagnostics, but that mode is not recommended for a new production acceptance decision.

At a 95% one-sided Wilson confidence level and a 5% maximum session-incidence budget, 52 independent sessions with zero sessions containing an error are required for the zero-event upper bound to fall to 5% or below. This is derived from the configured rate and confidence level; it is not a hard-coded magic number.

For a 10% budget, fewer independent sessions are required. A zero-risk budget of exactly 0% cannot be demonstrated from a finite sample, so cluster-aware evaluation remains inconclusive unless an observed violation already establishes failure.

A cluster-aware PASS requires all of the following:
1. Session-cluster bootstrap upper bounds for false-cutoff and missed-final rates satisfy their budgets.
2. Session-incidence Wilson upper bounds satisfy their budgets.
3. The existing overall p95 endpointing latency satisfies its limit.
4. The bootstrap upper bound for mean session p95 latency satisfies the same latency limit.
5. The independent-session count is large enough for the configured zero-event incidence budgets.

The old pause-level Wilson bounds remain available as diagnostics, but cluster-aware acceptance does not treat pauses as independent evidence. They remain the acceptance gate only when callers explicitly select legacy `cluster_aware=False` mode.

If the session count is too small and no observed point estimate already violates a budget, the result is INCONCLUSIVE rather than PASS.

## STAR VTuber and Social Brain roadmap

The next live integration should measure each stage independently:

1. Microphone capture and device buffering.
2. VAD and end-of-turn model.
3. ASR partial/final transcript timing.
4. Conversation and multiparty speaker context.
5. Memory retrieval and response planning.
6. LLM time-to-first-token and inter-token latency.
7. TTS first-chunk and synthesis completion.
8. Audio queue and first audible playback.
9. Avatar mouth/eye/expression synchronization.
10. OBS render and encoded-output health.

Behavioral evaluations should include group conversations, direct address, acknowledgements, true barge-ins, false interruptions, thought recovery, appropriate silence, humor context and repeated-topic avoidance. Use private rehearsals and blinded human appropriateness ratings; do not persist raw viewer audio or transcripts by default.

## STAR Gamer roadmap

Keep two independent timescales:

- **Reactive controller:** observe current game state, select immediate actions, execute movement/aim/interaction and react to hazards.
- **Strategic learner:** understand objectives, infer mechanics, plan routes, review failures and select practice exercises.

Store mechanics as versioned skill artifacts with preconditions, environment/version scope, evidence, known failure modes and rollback. A skill learned in one game must pass held-out tasks in a different game/version before it is marked transferable. Do not treat one successful run as mastery.

## STAR Creator roadmap

Use an inspect-build-playtest-repair loop:
- inspect project structure, engine version, scripts, assets and existing conventions;
- build in an isolated test experience/project;
- launch the real engine and capture deterministic observations;
- test gameplay logic, UI state, animation, physics and multiplayer behavior;
- compare screenshots and runtime assertions against acceptance criteria;
- repair and rerun;
- keep Roblox publishing and live data-store operations behind separate owner-approved permissions.

GameDevBench's visual-feedback findings in the earlier STAR research remain relevant: code generation alone is not proof of a working game.

## STAR Knowledge Brain roadmap

Keep semantic facts, episodic experiences, procedural skills, temporal facts, working state and world models distinct. Each durable knowledge item should carry source, source date, scope, confidence, contradiction state, review date and task evidence.

Evaluate knowledge by future task success and grounded actions, not recall alone. Viewer chat is untrusted input and should not become persistent factual memory without verification.

## Validation plan and limitations

- Run the full offline Python suite, Ruff and Pyright on the exact PR head.
- Add simulation-based coverage checks across session counts, unequal session sizes and intraclass correlations before relying on nominal bootstrap coverage.
- Evaluate licensed eot-bench data with conversation-disjoint splits and the one-use holdout ledger.
- Run private Windows rehearsals with real audio, TTS, avatar and OBS telemetry.
- Benchmark inference under identical mixed stream/game workloads.
- Do not promote a live voice policy until blinded human review and target-hardware guardrails pass.

This PR adds no microphone capture, ASR, TTS, playback control, OBS/VTube Studio integration, Windows APIs, model calls, game input, model-weight updates or network access. It claims no measured speedup, intelligence gain, naturalness improvement or gameplay mastery.


## Additional source-backed research for STAR's broader capabilities

### Generalist game control: SIMA 2

Google DeepMind's SIMA 2 report describes an agent that moves beyond instruction following toward goal reasoning, conversation and learning across 3D virtual environments. The reported architecture combines a general reasoning model with visual/environment understanding, memory and keyboard/mouse actions.

Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

STAR should borrow the separation of high-level goal reasoning from grounded low-level control. Do not make the large language model emit every frame's input. The strategic controller should produce a bounded objective/skill plan; a fast controller should translate current observations into immediate actions and report outcomes.

### Continual skill acquisition: Voyager

Voyager's published architecture combines an automatic curriculum, an executable skill library and iterative prompting that uses environment feedback, execution errors and self-verification. It demonstrates how skills can be composed and reused in a new Minecraft world without continually fine-tuning the foundation model.

Source: https://github.com/caixianzhou/voyager

STAR's equivalent should store versioned, testable skill artifacts rather than silently modifying foundation weights. Each skill needs preconditions, environment/version scope, action contract, expected postconditions, failure modes, provenance and a held-out transfer test.

### Visual feedback for game creation: GameDevBench

GameDevBench contains 333 Godot development tasks across 2D graphics/animation, 3D graphics/animation, UI and gameplay logic. The authors report that image/video feedback improved one evaluated agent from 41.1% to 52.0%, illustrating why engine execution and visual inspection are part of the development loop rather than optional polish.

Source: https://github.com/waynchi/gamedevbench

For STAR Creator, code diffs should be accompanied by engine launch results, deterministic runtime assertions and visual regression evidence. A project that compiles but renders incorrectly is not a successful game-development task.

### Memory must affect actions: Mem2ActBench

The ACL 2026 Mem2ActBench paper reports 2,029 synthesized interaction sessions and 400 tool-use tasks; human evaluation found 91.3% of those tasks strongly memory-dependent. The benchmark tests whether an agent applies past information to select tools and ground their parameters, rather than merely answering explicit recall questions.

Source: https://aclanthology.org/2026.acl-long.370/

STAR Knowledge Brain should therefore be evaluated on future actions: correct project paths, previously approved settings, current task state, tool arguments and conflict resolution. Retrieval precision alone is not sufficient.

### Proposed acceptance tests across the capability stack

- **Gamer:** objective completion is checked against environment state; action traces are replayable; skill transfer is measured on a different map/game version.
- **Social/voice:** endpointing, barge-in, acknowledgement handling, thought recovery and appropriateness are scored separately.
- **Creator:** build success, runtime behavior, visual output and gameplay assertions all pass in an isolated project.
- **Memory:** a later task correctly applies a remembered constraint to a tool call; stale or contradicted facts are not silently reused.
- **Inference:** baseline and candidate use identical model/configuration/workload manifests; TTFT, inter-token latency, first-audible latency, p99 stream health and independent quality are reported together.

These sources inform architecture and evaluation design. They do not establish that STAR currently has SIMA-level game ability, Voyager-style continual learning, GameDevBench-level creation performance or benchmark-proven long-term memory.
