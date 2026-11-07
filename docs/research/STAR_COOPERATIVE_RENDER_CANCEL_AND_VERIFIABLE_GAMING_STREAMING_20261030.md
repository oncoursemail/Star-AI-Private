# STAR: Cooperative VTuber frame cancellation, intelligence and gaming research

**Engineering date:** 2026-10-30. **Scope:** one implemented offline cancellation improvement; the wider intelligence/gaming/VTube development directions below are researched proposals, **not deployed results**.

## Repo evidence and implementation

PR #844 (`fix/stream-motion-preemption-safety-20261030`) passed the full STAR offline checks workflow run **41141360421**: Python checks, React checks and the Pyright baseline gate each reported success. This is repository CI evidence, not a Windows OBS rehearsal. That PR moved heavy motion synthesis outside `StarStage`'s lock so a trusted owner interruption can revoke a plan while frames are being generated.

**Remaining bottleneck found by source inspection:** `star/stream_motion.py::plan_motion` computes **up to 901 frames per call** (15 s × 60 FPS plus initial frame). After a plan is revoked, #844 discards output but the obsolete task may still spend CPU building all frames. On an 8 GB gaming GPU machine where CPU time is valuable for OBS, TTS and local inference, this is avoidable work.

### Implemented here

- `plan_motion(..., cancelled=callable)` retains its preexisting deterministic output by default. For opt-in callers it validates all inputs first, then checks cancellation before computation and every eight frames; it also checks before returning. A cancelled call yields **no partial animation**.
- `StarStage.motion()` passes a host-local liveness predicate tied to the *same issued plan object and audible phase*. No viewer-provided identifier, chat text, network message or model-generated token may authorize motion.
- The stage still checks validity **after** generation. Its physical renderer must revalidate `current(plan)` before each dispatched batch, because a valid computation can become invalid between return and device output.
- Deterministic regression tests cover unchanged uninterruptible results, prestart cancellation, cancellation during generation, invalid inputs, concurrency and complete refusal of stale frames. No games, streaming services or system controls are operated.

This changes the **amount of obsolete Python work**, not neural model weights, speech quality or game-playing skill. Worst-case work after revocation depends on callback scheduling and the GIL; without Windows measurements there is no justified latency multiplier.

## High-leverage next experiments (prioritized)

| Priority | Work | Reliable evidence | Rejection gate |
| --- | --- | --- | --- |
| P0 | Complete staged PR CI and private Windows host rehearsal | Audit owner speech interrupt → PCM silence → rig reset; stale frames always 0 | Any old-frame dispatch or audible interruption regression |
| P0 | CPU/GPU budgeted stream scheduler across Star's gaming PC and Brain 1 | matched FPS 1% lows, OBS dropped/lagged frames, CPU contention, p95 host-audible latency | any gaming or audio quality regression |
| P1 | Audio-chunk-locked lip sync and hair secondary motion | sampled *played* envelope and A/V offset from decoded OBS recording, reduced-motion tests | generated-text lip sync drifting from real audio |
| P1 | Independent unfamiliar-game mastery harness | held-out game states/levels, attempts, actual verified wins, intervention count | merely explaining correct actions without executing them |
| P1 | Roblox Studio evidence-driven scene repair | inspection → edit → test; collision, object hierarchy, UI and multiplayer checks | compile-only successes, missing objects or unplayable loops |
| P2 | Verified general-knowledge memory with provenance/expiry | cited answers on unseen recent questions, false-assertion rate, update lag | claims with no source or outdated timestamps |
| P2 | Distinctive character conversational agency | blinded listening ratings, turn-taking interruption rate, consistent *true* episodic recall | fabricated personal memories, repeated catchphrases, unwanted chatter |

### Star's game-learning control stack

Separate actions by their required response time instead of blocking all gameplay on a general-purpose LLM.

1. A **high-rate controller** consumes authorized, game-specific state and issues bounded actions; decisions must not require waiting for a multi-second model response. Games must permit such automation.
2. A slower **perception/state estimator** compares video, UI cues, host events and action effects, with uncertainty and stale-frame detection. Claims like `won`, `lost`, `checkpoint`, and `health restored` require host-side validation.
3. The **strategist** proposes and revises hypotheses in bounded offline practice episodes. Build a small game-mechanics registry (control mapping, jump timing, hazard semantics, reset conditions), but record provenance and counterexamples.
4. The **evaluation harness** hides final test levels while training; success = verified play and complete goals, not fluent descriptions. Repeated learning loops should improve *held-out* scores without erasing earlier competence.

GameWorld evaluates 170 verifiable tasks across 34 games, a useful external template for outcome-based scoring. Its tasks are not automatically compatible with Star's hardware or games; integration needs separate controls, licensing and consent review.
- https://gameworld-project.github.io/
- https://github.com/gameworld-project/GameWorld

OpenGameEval's October 1, 2026 work measured 13 frontier agents on 84 Roblox Studio tasks with executable scene and play-session checks. Its key lesson for Star is **inspecting affected objects before editing**: scene constraints need their own verification, separate from Luau test success. The paper reports a 13.4 percentage-point higher pass rate on scene-only tasks when all edited objects were inspected versus none in the controlled analysis. This is a research association, not an expected Star speedup.
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

### Faster intelligence without sacrificing stream quality

For Star's RTX 4060 8 GB and CPU-heavy fallback paths, measure real end-to-end work rather than tokens/s alone. A comparison must pin model build, quantization, offloaded layers, exact prompts, stream load, thermal state, context reuse and sampling policy. Important metrics: first **audible** host PCM, 95th percentile interruption-to-silence, valid game actions/s, independent task correctness, 1% low game FPS, OBS lag and GPU memory headroom.

Compare three routing policies: (A) a short-response small model, (B) a larger model only for expensive strategic/knowledge questions, (C) idle-only background planner on Brain 1. Prefer policy (B) if it preserves interactive latency and significantly improves verified outcomes. Do **not** use more simultaneous models if it worsens memory pressure.

The October 2026 Strata benchmarks include claims of large gains against llama.cpp on some MoE/CPU-offload configurations; the author notes limited rounds, non-exhaustive llama.cpp tuning and device differences. These are a useful *hypothesis to test* rather than transferable performance numbers for Star's 8 GB card. Similarly, speculative decoding needs matched candidate/no-draft and correctness tests; lower acceptance or a memory-hungry draft can be slower.
- https://github.com/Niko1221/Strata/blob/main/bench/results/2026-10-06-llamacpp-0.6.0/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

### More natural but truthful VTuber presentation

Combine *stateful attention* and independent audio, rather than generating a line for every event. Star should recognize gameplay focus, wait during tense sequences, pause naturally, acknowledge genuine interruptions, remember actual prior episodes, and pick one relevant viewer question after a game-critical moment. An emotional performance is a character animation and voice-design choice, not evidence of human feelings or consciousness.

Keep two non-conflicting time lines: (i) verified host game events and real playback history; (ii) character-authored fiction or roleplay, always labeled appropriately. No invented human childhood, wins, physical sensations or audience relationships represented as lived facts. Add expressive facial timing, blink variation, subtle head motion, properly simulated hair inertia, laughter from playback-driven envelopes, and a clear reduced-motion fallback. Preserve her final accepted black/gold/indigo design.

LiveKit's local audio turn detector is one candidate for fewer premature responses, but a turn detector is *not* authentication, echo cancellation or proof that a viewer addressed Star. User/owner interruption must still be routed from a trusted channel. Measure interruption precision/recall, audible response latency and naturalness with local recordings.
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://docs.livekit.io/agents/build/metrics/

## Acceptance and boundaries

- Run `tests/test_stream_motion_cooperative_cancel.py`, existing motion/stage/preemption tests, Ruff, Pyright and full Python/frontend offline CI on the same commit. Record failures and repair rather than weakening cancellation safety.
- In a private authorized rehearsal, inject a CPU-heavy frame generation task and interrupt it at arbitrary points; compare old vs new branch 30+ times with deterministic timings and no internet. Record cancelled-frame count, final rig reset, per-thread CPU, PCM stop, OBS and game FPS. Pass only if there are **zero** stale frames, no regressions, and a measured CPU-work reduction.
- All new logic is offline-only, opt-in via `StarStage.enable(owner_approved=True)`. There is no OBS starter, input injection, external networking, auto-model replacement, raw viewer transcript storage, broadcast scheduling or automatic code deployment.
- The repository `oncoursemail/Star-AI-Private` currently reports **public** visibility despite its name. Do not store keys, recordings or private viewer information. Star Core Forge can remain the offline-first authority; GitHub is the reviewed release mirror.

**Evidence level:** the Python work-revocation mechanism is implemented; actual faster gaming/voice performance, smarter models, game mastery and human-quality VTuber output are **not** measured or claimed.
