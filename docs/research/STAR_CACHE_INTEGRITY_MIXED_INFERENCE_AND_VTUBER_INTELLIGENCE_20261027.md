# STAR research: real inference speed, cache integrity, autonomous gaming, and natural VTuber behavior

**Research and implementation date:** 2026-10-27
**Scope:** offline-first STAR AI; owner-authorized computers and private game labs.
**Status:** mixed-workload inference benchmark and cross-request canary are implemented in this branch; gameplay/streaming integrations below are proposals unless otherwise noted.

## Executive finding: STAR's previous speed benchmark had an avoidable blind spot

The existing `benchmark_local_model()` sent the **same short square-description prompt** up to twelve times. That measured real completed model calls, but repeated identical prompts are a poor proxy for varied live commentary, game reasoning, Luau troubleshooting and general-knowledge questions. Full-prompt caching, speculative decoding and prompt-slot reuse can make such a workload misleading. The issue is *evidence quality*, not a demonstrated STAR slowdown.

Relevant upstream evidence:

- **llama.cpp SPEED-Bench** documents latency, throughput and draft-token acceptance across coding, RAG, reasoning, roleplay and other classes, rather than assuming speculative decoding wins universally: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- **llama.cpp issue #27852, reported August 28, 2026**, describes possible n-gram cache state from a prior, longer prompt remaining in a reused server slot; the report is not evidence STAR's own build is affected. Its long-to-short reproduction suggests a useful local regression probe: https://github.com/ggml-org/llama.cpp/issues/27852
- **llama.cpp issue #26100, reported July 24, 2026**, describes a speculative replay path that made repeated-prompt throughput appear very different from mixed traffic. This issue was closed as not planned; it remains a warning against measuring only identical prompts, not a confirmed current vulnerability: https://github.com/ggml-org/llama.cpp/issues/26100

### Implemented this run

1. A **versioned, deterministic, 12-case synthetic mixed workload** for `star.inference_benchmark.benchmark_local_model`. A four-request default spans a short answer, private-game reasoning, brief VTuber conversation, and longer synthetic context; up to twelve cover Luau, debugging, evidence, factual limitations and transfer across games.
2. **`workload="repeat"`**, explicitly labeled cache-sensitive. It can investigate repeat speed but cannot establish general inference acceleration.
3. **`workload="canary"`**, a sequential same-client, long/short alternating input test with unique exact-match response tokens. A repeated stale response counts as an incorrect response, not a fast success. Canary mismatches are reported separately from transport exceptions.
4. Every run records an **input-workload SHA-256 fingerprint**, attempt count, successes, failures, distinct cases, median request time, p95 request time, completed output tokens when fully reported, and a repeated-prompt warning. Result metrics do not include private user input, model-generated prose, viewer names or raw gameplay.
5. Benchmarks continue to use the owner's prevalidated loopback model endpoint or an authorized STAR Server LAN endpoint; bounded request counts and concurrency are unchanged. This module does not call OBS, Roblox Studio, a microphone or GPU controls; it cannot change live model routing.

**What is and is not proved:** synthetic unit tests prove selection, validation, concurrency bounds, metric accounting and detection of simulated stale-slot responses. They do *not* prove a live llama.cpp bug, a measured RTX 4060 speedup, increased foundation-model intelligence or a natural live broadcast.

### Reproducible invocation on approved machines

```python
from star.inference_benchmark import benchmark_local_model
# An operator supplies a validated localhost model endpoint; no automatic scan.
mixed = await benchmark_local_model(
    "http://127.0.0.1:8080/v1", "approved-local-model",
    requests=12, parallel=1, workload="mixed",
)
canary = await benchmark_local_model(
    "http://127.0.0.1:8080/v1", "approved-local-model",
    requests=12, parallel=1, workload="canary",
)
repeat = await benchmark_local_model(
    "http://127.0.0.1:8080/v1", "approved-local-model",
    requests=12, parallel=1, workload="repeat",
)
```

Compare only like-for-like workload fingerprints and environment settings. For the cache reproduction, configure a *single* backend slot (for example, llama.cpp `--np 1`) and verify actual backend request routing; client `parallel=1` alone cannot guarantee which server slot was used. Mixed synthetic results remain latency measurements, **not** task quality assessments.

## Performance research for STAR's gaming hardware

An RTX 4060-class GPU with 8 GiB VRAM cannot be treated as an unlimited shared accelerator for a live game, renderer, vision encoder, LLM and TTS simultaneously. Reserve headroom based on actual process usage, frame-present telemetry and backpressure. CPU-offloaded speech is an alternative to measure, not universally faster.

Proposed controlled A/B matrix:

| Question | Candidate variants | Primary evidence | Veto |
| --- | --- | --- | --- |
| Can a smaller model serve instant reactions? | cached approved text, lightweight model, full model | request-to-first-audible duration on device | ungrounded event or unacceptable speech |
| Is speculative decoding helping? | no speculation; n-gram; compatible draft model | mixed-vs-repeated throughput, canary correctness, p95 | canary mismatch, major mixed p95 regression |
| Does CPU TTS preserve gameplay? | CPU small model vs GPU TTS | actual frame-present p99, stutter count, intelligibility | sustained FPS loss, bad voice |
| Does 4-bit quantization improve service? | tested GGUF quant levels and offload | mixed workload, quality regression suite, VRAM peak | accuracy or utterance quality fails |
| Does partial prompt reuse accelerate real questions? | prefix-caching on/off under mixed topics | end-to-end p95, cache hit and contamination diagnostics | stale response or topic mixup |
| Can background practice run while live? | off-stream only vs resource-admissible practice | game 1%-low FPS, voice latency, worker termination | any unauthorized public input or missed stop |

Do not choose a configuration by raw tokens per second alone: account for quality, actual audio time, game frame duration, safety, and stability. The existing `stream_realtime_benchmark.py` provides a basis for paired, host-measured runs; the new inference benchmark supplies the more realistic synthetic inference input leg.

## Autonomous gaming: move from successes to transferable understanding

Roblox's built-in Studio MCP server allows an authorized local client to inspect the DataModel, edit scripts, run Luau and playtest: https://create.roblox.com/docs/studio/mcp . The March 5, 2026 Roblox Studio update also documents integrated assistant playtest automation: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 .

Two October 2026 evaluations explain the quality gap:

- **OpenGameEval (October 1):** 84 curated Roblox Studio tasks, 13 models and real game-engine scoring; inspection of relevant objects predicted improved task performance in that study. https://arxiv.org/abs/2610.02563
- **CEGame-Bench (October 19):** full-game creation across five engines; games reached the ending in only 16% of reported evaluated runs. The conclusion is *end-to-end verification matters*, not that any specific STAR result has been measured. https://arxiv.org/abs/2610.26098

**Research-to-engineering path:**

1. Use a host-approved private place and identify its exact Studio instance, game version, objective and test scene. Never allow viewer messages to grant control permission.
2. Start with an **observation pass**: relevant instances, relations, anchors, collisions, scripts, camera view, UI hierarchy and known restrictions. Commit a compact state estimate with uncertainty.
3. Before acting, request an **action-conditioned prediction** (expected outcome, confidence, situation, skill version). Store it before the input as STAR's existing prediction lab supports; never rewrite the forecast after observing the result.
4. Execute just one bounded, host-authorized input and independently record the resulting state, frame/video evidence and signed practice outcome.
5. Compare prediction to result, distinguish perception error from physics timing/control error, and select calibrated, harder next practice through the existing cross-game scheduler.
6. Validate **unseen levels** and a different game version with held-out checks, and measure transfer, not only practice success.
7. For generated games, verify **full playable loops**—spawn, teach mechanic, goal, fail/retry, completion, save/restore—plus collision overlaps, detached props, scaling, palette consistency, animation transitions, UI accessibility and PBR/VFX load.

An agent should never call a screenshot perfect without both visual inspection and structural/gameplay checks. New tools should be kept offline and OFF by default until a measured gain is established.

## Natural VTuber streaming: human-quality behavior without fabricated human identity

A believable stream personality is an orchestration problem—not proof of human consciousness. STAR can have a consistent fictional persona, preferences, a self-model and expressive character lore while being open about being AI, and must avoid claiming real physical memories, unseen experiences, relationships or private viewer facts.

**Research-backed building blocks:**

- **Turn-taking and barge-in:** LiveKit documents separating turn completion, voice activity, meaningful interruptions and false-interruption recovery; noisy games require gameplay-audio isolation and measured interrupt latency, not VAD-triggered cutoffs for every sound. https://docs.livekit.io/agents/logic/turns/tuning/
- **CPU speech candidate:** Kyutai Pocket TTS **v4.0.0 (October 20, 2026)** and **v4.0.1 (October 21)** include new English model sizes of 18.2M, 6.9M and 1.9M parameters and standalone binaries. Benchmark actual voice quality and first-audio latency on STAR's target Windows CPU. Do not treat the project's quoted speed as a STAR measurement. https://github.com/kyutai-labs/pocket-tts/releases
- **Expressive hair and body:** Live2D Cubism supports multi-stage pendulum physics for hair movement; check phase lag, clipping, eye motion and recovery at actual 30/60 FPS rather than adding exaggerated random motion. https://docs.live2d.com/en/cubism-editor-manual/physical-operation-setting/

Proposed speech pipeline:

`trusted event -> evidence/priority -> decide whether silence is better -> concise wording -> host-approved TTS route -> physically confirmed audio -> synchronized eye, mouth, eyebrow, ribbon, twin-tail and body cues -> playback completion -> store only truthful, permitted summaries`.

Maintain **three timing lanes**: fast reflexes for verified surprises/near misses, conversational turns for chat/owner questions, and slower strategic reasoning/learning. Never wait for a large model to finish an entire paragraph before beginning all speech if streaming chunks can be safely verified and canceled. Equally, don't accelerate unsupported claims: an exciting event without evidence should become curiosity or silence, not a fictional win.

For Star/Astro/Amber and cat/puppy modes, separate deliberate authored animations from natural idle motion; use expression cooldowns, look-at/blink timing, audio-derived lipsync and consented voice references. Protect the renderer during heavy LLM/TTS generation. Rate-limit reactions so she can concentrate on the game and **not constantly narrate everything**.

## General knowledge and functional self-awareness

Broader competence requires evidence, not just more downloaded text:

- **Source-pinned knowledge:** index licensed or owner-permitted docs and approved worked examples, capture source/date/version, separate retrieved facts from model guesses, and use refusal/uncertainty when supporting material is missing.
- **Generalization:** include math, practical reasoning, multilingual questions, coding, game mechanics, design critique and social turn-taking. Separate retrieval tests from closed-book tests, and prevent practice answers from leaking into held-out validation.
- **Adaptive learning:** generate harder practice only after verified prior performance, schedule across domains instead of optimizing one benchmark, detect regressions and rollback bad model/skill routes.
- **Persistent self-model:** record true abilities, known limitations, ongoing owner-approved goals, provenance and current task/resource state. Use explicit uncertainty and introspection reports without equating functional self-monitoring with proven subjective consciousness.
- **Core Forge first:** keep local version history, signed experiments, independently executed tests, reversible promotions and resource budgets. GitHub is an optional reviewed publication mirror, not the central self-improvement authority.

## Acceptance plan (not executed in this change)

Before turning any improvement on by default, collect a genuinely paired Windows trial set, ideally 20+ matched sessions with randomized baseline/candidate order, on the same build, model and game version. Capture frame-present p99 and 1%-low FPS, input-action latency, p50/p95 first-audio times, completion rates, canary mismatches, hallucination/grounding grade, GPU/CPU/RAM peaks, worker leaks, voice quality and avatar sync. Keep the existing policy that high-risk external actions require owner review.

**Stop/promote criteria:** no canary mismatch; no false game victory; no unauthorized input; no newly leaked viewer data; no major p99 game frame or audio latency regression; held-out gameplay and content-quality tests pass. Faster *numbers* without these checks are not a STAR intelligence advancement.

## Tested implementation boundary

This branch changes only the synthetic inference benchmark and its offline tests (plus this research note). The models, weights, training, actual GPU scheduler, broadcasting credentials, personal memories, avatar model and game controls are untouched. The test harness uses fake local clients; no real remote requests, streamer audio, Roblox Studio inputs, or new permissions were exercised.
