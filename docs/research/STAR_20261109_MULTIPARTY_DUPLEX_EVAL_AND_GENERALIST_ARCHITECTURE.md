# STAR research: multi-party full-duplex streaming and generalist capability architecture

**Date:** 2026-11-09 (America/Chicago)  
**Scope:** Natural VTuber conversation, multi-party turn-taking, grounded memory, real-time game skill, game creation, general knowledge, and end-to-end local performance.

## Executive summary

The next quality jump for STAR is not another larger prompt or another isolated token-speed benchmark. It is a coordinated system that can observe, decide, act, verify, remember, and recover under real deadlines.

This update adds one concrete piece of infrastructure: an offline evaluator for content-free, host-observed full-duplex turn receipts. It scores five distinct conversational actions:

- respond with speech;
- backchannel nonverbally;
- remain silent;
- yield to an actual interruption;
- continue speaking through a non-interrupting cue.

It separately measures multi-party addressing errors, background-speech reactions, missed and false interruptions, game-critical chatter, first-audio latency, avatar-cue latency, stop latency, grounding coverage, and per-scenario/per-speaker-role accuracy.

The evaluator does not process or store audio, transcripts, prompts, viewer identities, or generated speech. It does not control the microphone, TTS, avatar, game, OBS, or broadcast. It measures supplied annotations and host receipts; it is not proof that the receipts are authentic. Live integration still requires a trusted Windows host and independently reviewed human labels.

## 1. Implemented in this change

### New module

star/voice/duplex_eval.py

### New tests

tests/test_voice_duplex_eval.py

### Receipt contract

Each JSONL row contains only:

- opaque scenario and event identifiers;
- a development/holdout split;
- a coarse speaker role (owner, viewer, other, background);
- a coarse addressee (Star, group, owner, other, none, unknown);
- an independently annotated expected action;
- a host-observed action;
- relative speech-start, speech-end, and turn-end timestamps;
- whether Star was already active and whether gameplay was critical;
- optional interrupt-detection/stop, first-audio, first-avatar, and grounding receipts.

The parser rejects unknown fields, duplicate JSON keys, non-finite numbers, invalid enum values, duplicate events, out-of-order clocks, oversized files, and invalid UTF-8. Exact-schema rejection is deliberate: a transcript, audio payload, account ID, or other private field cannot silently enter this evaluator.

### Output metrics

| Metric | Why it matters |
|---|---|
| Per-action precision, recall, F1 | A single accuracy score can hide a dangerous failure mode |
| Correct-silence rate | Measures whether Star avoids filler and unnecessary interruptions |
| False response/backchannel to non-Star-directed speech | Measures multi-party awareness |
| False and missed interruptions | Separates echo/noise false positives from missed barge-in |
| Yield stop latency | Measures how quickly speech actually stops after a valid interruption |
| Turn-end to first-audio p50/p95 | Measures the delay a viewer experiences |
| Speech-start to first-avatar p50/p95 | Measures acknowledgement timing |
| Grounding coverage/rate | Separates a response from a response with verified support |
| Critical-game chatter | Detects optional commentary during annotated danger/precision windows |
| Per-scenario and per-speaker-role accuracy | Prevents easy cases from hiding weak multi-party behavior |

Latency percentiles use nearest-rank p95 and a median p50. Early audio/avatar receipts are counted separately instead of being clamped into a misleading zero-latency bucket.

### Run it

After a trusted host has exported a private, content-free JSONL receipt file:

~~~bash
python -m star.voice.duplex_eval private_turn_receipts.jsonl --split holdout --output duplex-report.json
~~~

Run the focused tests:

~~~bash
python -m unittest tests.test_voice_duplex_eval -v
~~~

Do not commit real recordings, raw transcripts, viewer handles, or private chat. Keep the holdout annotations sealed from any model or policy being tuned.

## 2. Research findings: full-duplex conversation is more than voice activity detection

### Full-Duplex-Bench v3

The NTU/NVIDIA-advisory benchmark uses 100 human-recorded spoken requests across 79 scenarios and 12 speakers. It includes disfluencies and tasks requiring one to three chained tool calls, and evaluates tool accuracy, Pass@1, latency, and turn-taking. This is useful because STAR must handle self-corrections and multi-step requests while maintaining conversational timing, not just transcribe clean single-speaker speech.

Source: https://www.full-duplex.ai/benchmarks/fdb-v3

### MP-Bench

The EMNLP 2026 Findings benchmark focuses on agents participating in multi-party conversations. Its benchmark summary reports that the 12 evaluated voice agents remain weak on multi-party comprehension and turn-taking. The implication for STAR is clear: speaker role, addressee, conversational floor, and background speech must be evaluated separately. A VAD event alone cannot tell STAR whether a person is talking to her, talking to another viewer, or speaking in the background.

Source: https://www.fullduplex.ai/benchmarks/mp-bench

### Realtime-Venus

Realtime-Venus explores full-duplex audio/video interaction with asynchronous delegation. Its architectural lesson is to keep the live perception/conversation loop responsive while slower reasoning and tool work proceed separately. STAR should not wait for a deep model to research a viewer's question before it can acknowledge the viewer or stop speaking when interrupted.

Source: https://realtime-venus.github.io/

### Design implication for STAR

Use a small event-driven conversation director, not a large model on every audio frame:

1. Native audio capture, echo control, VAD, and optional diarization produce timestamped observations.
2. A deterministic turn director decides whether the current event is directed to Star and whether the floor is open.
3. A fast response path chooses speech, backchannel, silence, or yield.
4. A slower model may prepare a grounded answer in the background.
5. Immediately before playback, the trusted host rechecks current speaker, interruption, route, scene, and output health.
6. The audio host enforces STOP/FLUSH and confirms the physical output epoch; a Python advisory alone is not physical stop proof.

The evaluator added here measures the decision and receipt layer. It does not implement diarization or replace the existing VAD/echo gate.

## 3. Memory and intelligence: remember evidence, not just text

Agent Zero Memory proposes three complementary memory structures: an episodic event timeline, an associative entity-event graph, and curated semantic/documentary memory. It also describes an intent gate so self-contained questions do not pay the cost of unnecessary retrieval, and a citation lock that only allows answers to cite evidence the reader actually opened.

Source: https://arxiv.org/abs/2608.29606

Recommended STAR architecture:

- **Episodic:** what happened, when, in which project/game/session, and which artifact or receipt proves it.
- **Semantic:** durable facts, definitions, verified APIs, and source-backed general knowledge.
- **Procedural:** skills and workflows with prerequisites, environment/version, action schema, evidence suite, and last verified revision.
- **Preference/persona:** owner-approved preferences and fictional persona details, kept distinct from external facts and observed experiences.

Every memory item should carry provenance, timestamp, scope, confidence, and an evidence pointer. If a game build, API version, model revision, project file, or evaluation suite changes, dependent procedural knowledge becomes "needs revalidation" instead of silently remaining verified.

Use selective retrieval: only inject memory when the current intent and scope need it. More context is not automatically more intelligence; it can increase prefill latency and distract the model.

## 4. Gaming intelligence: separate reflex, tactics, and learning

GameWorld evaluates multimodal agents over 34 browser games and 170 tasks with state-verifiable outcome metrics. Its authors identify latency, sparse feedback, and irreversible actions as important challenges.

Source: https://arxiv.org/abs/2604.07429

STAR should use three coordinated loops:

| Loop | Responsibility | Deadline style |
|---|---|---|
| Reflex | Immediate perception, movement, threat response, stop/cancel | Tight, bounded, no deep-model wait |
| Tactical | Positioning, route selection, combat, cooldowns, local objectives | Short horizon |
| Strategic learner | Mechanics, maps, practice plans, failure analysis, transferable skills | Background/asynchronous |

For every game, define an observation schema, allowed action schema, success condition, reset method, deadline, and independent outcome signal. Prefer game-state APIs where available; use screen vision when the environment does not expose state. Do not ask a large model to reason over every frame.

Evaluate live and paused/slowed conditions separately. A model that wins only when the game is paused has not demonstrated real-time mastery. Require held-out maps, seeds, and scenarios to detect memorized scripts and lucky wins.

## 5. Game creation: make the build-playtest loop evidence-driven

OpenGameEval runs agents in reproducible, stateful Roblox Studio sessions and grades both edited scenes and simulated play sessions. Its repository describes 84 human-curated core tasks and reports that inspecting task-relevant objects before editing is associated with higher success.

Sources:
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563

GameDevBench contains 333 game-development tasks across gameplay, graphics, animation, and UI. Its paper reports that visual feedback improved one evaluated model's score from 41.1% to 52.0% in its tested setup. This supports visual inspection and playtesting as first-class steps, not optional polish.

Source: https://github.com/waynchi/gamedevbench

Recommended STAR creation loop:

**Inspect → Plan → Build → Run → Inspect screenshots/video → Playtest → Grade → Repair → Retest**

For Roblox Studio, use the built-in Studio MCP server and the owner's per-game permissions. Open Cloud scopes can affect live settings, products, passes, servers, assets, and data; use the minimum scopes required and a private test experience. The Roblox documentation distinguishes Safe, Balanced, Full access, and Custom levels and notes that Full access includes high-risk scopes.

Source: https://create.roblox.com/docs/studio/mcp-open-cloud

## 6. General knowledge and research

Build a broad curriculum, but make each domain testable:

- mathematics and logic;
- physics, biology, chemistry, and earth science;
- history, geography, and civics;
- computer science, programming, and systems;
- writing, communication, and languages;
- art, music, animation, 3D, and design;
- game mechanics, game design, and player psychology;
- practical computer use and troubleshooting.

For factual answers, separate current facts from durable facts. Attach a source and retrieval timestamp to changing claims. Use multiple sources for consequential conclusions, preserve disagreements, and abstain when evidence is missing. Evaluate not only recall but transfer: can STAR use a learned concept to solve a new problem with different surface wording?

## 7. Faster inference: optimize the complete experience

NVIDIA AIPerf distinguishes time to first token (TTFT), time to second token, inter-token latency (ITL), inter-chunk latency (ICL), request latency, and throughput. These metrics answer different questions. TTFT includes queueing, prompt processing, generation, and network delivery; ITL measures generation gaps; ICL exposes chunk jitter.

Source: https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference

The llama.cpp SPEED-Bench client benchmarks an already-running server and reports per-category latency, throughput, and speculative-draft acceptance. It is intended for comparing speculative decoding modes rather than assuming that every draft method is faster.

Source: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench

Recommended experiment matrix on the actual Windows gaming PC:

1. Model alone, cold and warm.
2. Model + game.
3. Model + game + OBS.
4. Model + game + OBS + TTS.
5. Full workload with vision, avatar animation, chat, and memory retrieval.

Record model/checkpoint hashes, quantization, context length, prompt/output lengths, concurrency, server build, GPU driver, power mode, and thermal state. Compare identical workloads and include p50/p95/p99. Record TTFT, ITL, ICL, first-audio latency, CPU, VRAM, GPU utilization, game frame-time, OBS render/network drops, and audio underruns.

Speculative decoding is workload-dependent. Test it on STAR's short chat, long reasoning, Luau, and game-commentary prompts. Reject a configuration if it improves isolated tokens/second but worsens first-audio p95, game frame-time, or answer quality. Prefix caching reduces repeated prefill work; it should not be described as faster token generation. CPU TTS may free VRAM but can contend with the game and vision pipeline, so benchmark it under the full workload.

## 8. Priority roadmap

### P0 — Full-duplex measurement
- Connect the new evaluator to trusted Windows event receipts.
- Add human-labeled multi-party holdout scenarios: direct questions, group speech, viewer-to-viewer speech, background speech, self-corrections, backchannels, overlapping speech, and owner interruption.
- Measure false interruptions, missed interruptions, background reactions, correct silence, and first-audio/stop p95.
- Keep raw audio/transcripts outside the repository and out of aggregate reports.

### P1 — Conversation and persona
- Add explicit conversation-floor and addressee signals from a trusted diarization/ASR adapter.
- Use nonverbal acknowledgements only when the event is fresh, relevant, and owner-enabled.
- Keep speech, avatar expressions, and mouth movement on one timestamped playback clock.
- Preserve a consistent fictional persona without claiming biological human feelings or concealing that Star is AI.

### P2 — Evidence-grounded memory
- Version episodic, semantic, and procedural memories separately.
- Attach source/evidence pointers and invalidation conditions.
- Use intent-gated, scope-aware retrieval.
- Evaluate memory-to-action transfer on held-out tasks.

### P3 — Game mastery
- Implement game-specific observation/action adapters.
- Train practice policies only in reversible, private environments.
- Use live-time and held-out scenarios.
- Promote skills only after independent outcome verification.

### P4 — Creator intelligence
- Expand inspection-first Roblox Studio workflows.
- Run executable scene checks and simulated playtests.
- Add visual review for UI, animation, VFX, lighting, and geometry.
- Keep Open Cloud scopes least-privilege and test-place-only for writes.

### P5 — Performance
- Benchmark quantization, context length, prompt caching, speculative decoding, and TTS placement as separate factors.
- Add deadline-aware admission so optional research/vision work yields to owner speech, audio stop, and critical gameplay.
- Keep model selection manual/owner-approved until paired quality and full-workload performance gates pass.

## 9. Acceptance and rollout gates

- All new features remain opt-in until reviewed.
- The evaluator is offline and advisory; it cannot authorize speech, game input, avatar output, OBS, or broadcasting.
- Development and holdout splits remain separate. Do not tune thresholds on the holdout.
- Require independent annotations and host-authenticated receipts before using scores to change live behavior.
- Run a 30–60 minute private, nonbroadcast Windows rehearsal with game, model, TTS, audio capture, avatar, and OBS together.
- Require no critical audio-stop failure, no material OBS drop increase, no unacceptable game frame-time regression, and no quality regression before enabling an optimization.
- Keep Roblox write permissions scoped to an owner-selected private test experience; publishing, player-data writes, purchases, and live settings changes remain owner-approved.

## 10. What this update does and does not prove

Implemented here: a bounded, strict-schema, aggregate-only evaluator and 11 focused unit tests.

Not implemented here: real speaker diarization, Windows audio capture, live TTS/VTube Studio/OBS wiring, autonomous game controls, model training, or an inference speedup. The research above identifies concrete next steps; benchmark findings from external papers are not claimed as STAR's results.

## Sources

- NTU/NVIDIA-advisory, Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
- MP-Bench, Findings of EMNLP 2026: https://www.fullduplex.ai/benchmarks/mp-bench
- Realtime-Venus: https://realtime-venus.github.io/
- Agent Zero Memory: https://arxiv.org/abs/2608.29606
- GameWorld: https://arxiv.org/abs/2604.07429
- OpenGameEval: https://github.com/Roblox/open-game-eval
- GameDevBench: https://github.com/waynchi/gamedevbench
- Roblox Studio MCP Open Cloud permissions: https://create.roblox.com/docs/studio/mcp-open-cloud
- NVIDIA AIPerf metrics: https://docs.nvidia.com/aiperf/reference/ai-perf-metrics-reference
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
