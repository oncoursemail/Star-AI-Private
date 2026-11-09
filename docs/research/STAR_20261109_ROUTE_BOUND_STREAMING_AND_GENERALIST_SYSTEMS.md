# STAR — Route-bound streaming and generalist capability research

**Research date:** 2026-11-09  
**Implementation scope:** event-aware VTuber speech pacing, voice-route identity, and the next generalist-runtime milestones.

## Executive summary

The most useful immediate correction is to bind every pacing decision to the **current** host-owned voice route, not only to the route that produced historical samples. A route is the combination of TTS model, runtime/configuration, and physical output endpoint. If a device or voice changes, old timing samples are no longer trustworthy.

This update adds that binding to `StreamSpeechPacer.advise()`, `StarStage.prepare()`, the pre-TTS response review, and the final preplay witness. Missing route identity, a changed route, or missing host-load evidence now defers optional speech rather than silently falling back to an unbounded reply. Legacy stages with no paced plan retain their prior behavior.

This is an offline Python control improvement. It does not connect WASAPI, start TTS, emit PCM, control a game, start OBS, or broadcast.

## Implemented in this change

- Add canonical host route validation shared by calibration and advice.
- Require the current route ID to equal the route used for audible calibration.
- Bind the route ID to the issued `StagePlan`, recheck it at the pre-TTS text gate, and recheck it again in the fresh preplay witness immediately before PCM.
- Return a fail-closed `hold` for a missing route or route mismatch; a changed route invalidates the plan and cannot reuse the previous device's calibration.
- Count missing/mismatched advice routes without retaining route text in metrics.
- Require current host-load telemetry when the pacer is installed; a missing telemetry packet no longer creates an unbounded paced-stage response.
- Preserve owner opt-in, bounded in-memory histories, route reset erasure, and separate audio/broadcast authorization.
- Add regressions for missing route, mismatched route, valid route, stage deferral, and missing host context.

A Windows adapter must supply the same canonical route ID to `prepare()`, `review_response()`, and the final `PreplayWitness` that it uses for completed audible receipts. On an actual route change, it must disable the pacer and enable it again with owner approval so the new route starts cold. The preplay check must run immediately before the first PCM write; the Python plan is not a substitute for a native audio-device check.
## Research findings and engineering recommendations

### 1. Faster local inference on an 8 GB GPU

**Speculative decoding is a benchmark candidate, not a guaranteed speedup.** llama.cpp supports draft-model and n-gram-based speculative paths; its SPEED-Bench client reports latency, throughput, and draft acceptance by workload category. Compare short conversational turns, code, long reasoning, and structured output separately. A second resident draft model can consume VRAM that the game, OBS, vision, or avatar needs, so n-gram speculation should be tested before adding another GPU-resident model. [Speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) · [SPEED-Bench](https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench).

**Prefix caching mainly helps prefill, not token generation.** vLLM's Automatic Prefix Caching reuses KV blocks when requests share a prefix; its documentation explicitly notes that it does not reduce decode time. Keep Star's static system/persona prefix stable and place dynamic viewer/game data after it. Do not claim a faster answer merely because prompt prefill improved. [vLLM APC](https://docs.vllm.ai/en/v0.22.1/features/automatic_prefix_caching/).

**Use a one-primary-model default.** For the RTX 4060 8 GB profile, keep one primary GPU model resident unless a measured A/B test proves a second model helps end-to-end latency without harming game frame times or OBS. Route urgent short reactions to the fast path; defer expensive research, vision, and deep reasoning when frame-time, VRAM, or audio pressure rises. Keep admission and process termination in the trusted host, not in model-generated instructions.

**Test CPU speech as a GPU-relief option.** Kyutai Pocket TTS is CPU-oriented and supports streaming; its repository describes small English variants released in October 2026. It is a promising candidate for freeing VRAM, but it can still contend for CPU cores and memory bandwidth. Benchmark first-audio latency, real-time factor, voice quality, CPU load, game frame-time p95/p99, and OBS dropped frames on Star's actual machine before selecting it. [Pocket TTS](https://github.com/kyutai-labs/pocket-tts).
### 2. General intelligence and memory

Treat memory as a typed evidence system, not a larger transcript. Keep at least four distinct record classes:

- **World facts:** sourced claims about external systems, APIs, game mechanics, and general knowledge.
- **Experiences:** things Star actually did, with task/session/time and execution receipts.
- **Observations:** what a trusted sensor or tool reported, including freshness and uncertainty.
- **Opinions/preferences:** hypotheses or style preferences, explicitly separated from verified facts.

APEX-MEM describes append-only temporal event graphs and query-time conflict resolution. Hindsight separates world, experience, observation, and opinion networks and combines vector, keyword, graph, and temporal retrieval. These are useful design references, not drop-in proof that Star's memory will improve automatically. [APEX-MEM](https://aclanthology.org/2026.acl-long.749/) · [Hindsight](https://aclanthology.org/2026.acl-demo.27/).

Evaluate whether memory improves **actions**, not just trivia recall. Mem2ActBench specifically tests whether agents apply prior context to select tools and ground their parameters across interrupted sessions. Star should measure correct reuse of project constraints, API versions, game settings, and task state while rejecting stale or conflicting memories. [Mem2ActBench](https://arxiv.org/abs/2601.19935).

Recommended memory pipeline:
1. Extract atomic candidate records with source, timestamp, scope, confidence, and expiry.
2. Keep owner-authored facts distinct from model-inferred candidates.
3. Preserve superseded facts as history rather than destructively overwriting them.
4. Retrieve with lexical + vector + temporal filters; rerank only when the latency budget allows.
5. Present uncertainty and provenance to the reasoning model.
6. Promote a learned procedure only after a reproducible test passes.

### 3. Real-time gaming intelligence

Gym-Anything-RT (27 October 2026) evaluates 100 continuously evolving minigames and compares real-time play with paused/slowed environments. Its paper reports a large gap for one evaluated frontier model (9% real-time versus 75% paused). The result is not a measurement of Star; it is evidence that a strong slow reasoner does not automatically make a strong real-time player. [Paper](https://arxiv.org/abs/2610.37567).

Build two coordinated loops:
- **Reflex loop:** fresh observations, small action set, short deadlines, immediate cancellation on stale scene/input state.
- **Tactical loop:** slower strategy, map/mechanic learning, replay analysis, route planning, and practice selection.

Use a curriculum from deterministic minigames to unfamiliar maps and then held-out variants. Measure success rate, action-ack p50/p95, observation age, missed deadlines, recoveries, and transfer to unseen scenarios. Keep game-specific controls allowlisted and host-enforced. A model must not invent a win, claim a test, or write arbitrary game input.

### 4. Roblox game creation

OpenGameEval (1 October 2026) evaluates agents in reproducible, stateful Roblox Studio sessions with executable checks on both edited scenes and simulated play. It reports 84 curated tasks across 13 models; inspecting task-relevant objects before editing was associated with higher pass rates. This supports making exploration an explicit stage before edits. [Paper](https://arxiv.org/abs/2610.02563) · [Benchmark repository](https://github.com/Roblox/open-game-eval).

Recommended workflow: **inspect → state assumptions → plan → edit → static checks → playtest → compare to intent → repair → rerun holdouts**. Grade Luau correctness, scene hierarchy, client/server behavior, replication, physics, UI readability, performance, accessibility, exploit resistance, and actual playability. Keep generated code in the existing sandbox and preserve owner review for publishing or external writes.
### 5. Natural, transparent VTuber runtime

Proact-VL frames real-time companions as continuous perception plus autonomous response triggering and controllable commentary. Star should not send every frame to a large model. Use a bounded perception ticker that emits compact, timestamped events; a separate director decides whether to speak, defer, or stay silent; a fast response model writes the short reaction; a slower model handles viewer questions and between-round explanations. [Proact-VL](https://proact-vl.github.io/).

Natural streaming is not constant speech. Prioritize:
- event-grounded reactions and comfortable silence;
- immediate barge-in and cancellation of stale speech;
- route/device changes that invalidate old timing calibration;
- audio-to-expression synchronization based on actual emitted audio;
- varied sentence rhythm and specific, evidence-backed humor;
- viewer moderation and anti-harassment boundaries;
- long-session drift checks for voice, latency, memory, and persona consistency.

Keep Star transparently identified as an AI. She can have a distinctive character, preferences, humor, and continuity without claiming biological feelings, unobserved experiences, or a human life.

**Windows audio acceptance:** WASAPI loopback can capture the mix played by a rendering endpoint, and endpoint invalidation is a recoverable condition that must be handled. Use a dedicated Star output endpoint/session where possible; do not persist unrelated system audio. Record only minimal timing/health receipts for calibration, never raw audio or viewer conversations. Device invalidation, default-device changes, OBS reconnects, interruption, and audio epoch changes must clear stale readiness before another utterance. [WASAPI overview](https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi) · [Loopback recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording).

## Acceptance matrix

| Area | Required measurements | Promotion rule |
|---|---|---|
| Local inference | TTFT, decode tok/s, p50/p95 turn latency, output quality, VRAM/RAM, CPU, game frame-time p95/p99, OBS drops | Paired randomized A/B sessions; no quality or real-time regression |
| Speech | First-audible p50/p95, route identity, underruns, interruption cancellation, deadline misses, naturalness review | Host-confirmed audible receipts on the exact route; private rehearsal only |
| Gaming | Held-out win/progress, action acknowledgement p95, observation age, missed deadlines, recovery | Gains across multiple scenario families, not one easy map |
| Game creation | Inspect coverage, executable tests, scene checks, simulated play, multiplayer and performance checks | Reproducible pass on held-out tasks and rollback-ready patch |
| Memory | Recall@k, task-parameter accuracy, stale/conflict rejection, latency, memory footprint | Improves action grounding without cross-project or cross-user leakage |
| Streaming | Speech overlap, silence quality, viewer-turn response, persona drift, moderation outcomes | Private 30–60 minute session with owner review |

Run A/B/A or randomized paired sessions with the same model, prompts, game, avatar, power profile, and output route. Include warm-up, repeated trials, cold starts, route changes, long sessions, and held-out tasks. Report raw sample counts and confidence intervals; do not promote a candidate from a single favorable average or copied benchmark payload.
## Priority roadmap

**P0 — close the native contract:** pass the exact current voice-route ID into the stage, wire the hard response gate before TTS, observe actual WASAPI output completion, and invalidate route/audio readiness on device changes. Then run a private nonbroadcast Windows rehearsal.

**P1 — real-time perception and action:** add a freshness-stamped observation bus, scene/game identity binding, event deduplication, a small reflex policy, action allowlists, and replay-based evaluation.

**P2 — intelligence and memory:** add provenance-aware temporal records, contradiction handling, retrieval benchmarks, task-memory evaluation, and a nightly candidate-learning pipeline that cannot change permissions or deploy itself.

**P3 — speed experiments:** benchmark one-model GPU residency, n-gram speculative decoding, stable-prefix reuse, CPU TTS, context budgets, and workload admission on the RTX 4060 while measuring game and OBS performance.

**P4 — creator autonomy:** integrate Studio inspection and playtesting, automated Luau/static checks, visual and gameplay evaluation, asset workflow, and owner-reviewed release gates.

## Sources

- Gym-Anything-RT, 27 Oct 2026: https://arxiv.org/abs/2610.37567
- OpenGameEval, 1 Oct 2026: https://arxiv.org/abs/2610.02563
- Proact-VL, 2026: https://proact-vl.github.io/
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- vLLM Automatic Prefix Caching: https://docs.vllm.ai/en/v0.22.1/features/automatic_prefix_caching/
- Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts
- APEX-MEM, ACL 2026: https://aclanthology.org/2026.acl-long.749/
- Hindsight, ACL 2026 Demo: https://aclanthology.org/2026.acl-demo.27/
- Mem2ActBench, 13 Jan 2026: https://arxiv.org/abs/2601.19935
- Microsoft WASAPI: https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi
- Microsoft WASAPI loopback: https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording

**Evidence boundary:** these papers and upstream docs inform the design; they do not prove Star has achieved their reported results. No inference speedup, model-intelligence gain, gameplay win-rate increase, physical audio verification, or public-stream readiness is claimed by this research note.