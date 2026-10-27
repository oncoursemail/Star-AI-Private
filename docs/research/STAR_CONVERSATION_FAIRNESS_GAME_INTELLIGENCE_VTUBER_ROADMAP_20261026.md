# STAR: conversation fairness, measurable game intelligence, natural VTubing, and infrastructure
**Research and engineering date:** 2026-10-26
**Status:** one offline, pure-Python change implemented; all other proposals below are experiments, not deployed capabilities.
**Base:** stacked on `feat/knowledge-practice-host-20261026`. GitHub is a publication mirror, NOT Star's required autonomous development backend.

## Executive finding

Star's limiting factor is no longer solely generating more modules. The repository already has a streaming director, a stage/audio lifecycle, hardware-aware admission, event age enforcement, knowledge practice, signed game-learning receipts, and offline evaluation. Their value depends on connecting **actual sensory evidence → admissible action → verified outcome → reusable memory → measured regression tests**.

An expressive VTuber does not need nonstop chatter. She needs timing, selective attention, genuine continuity, curiosity, and accurate reactions. A game-playing AI needs to demonstrate mechanic transfer on *withheld levels*, not quote training-game outcomes. A faster model must remain correct, finish audible replies, and protect game FPS. This update implements one missing piece of the conversation arbitration layer, with follow-on experiments prioritized below.

## Implemented in this branch: fair, evidence-aware dialogue arbitration

`star/stream_director.py` now adds three bounded behaviors **without starting a stream, accessing audio, contacting Twitch, or running a model**:

1. **Chat question aging:** the director normally favors verified success (priority 70) over a question (60). Once a legitimate moderated question has waited 10 seconds, it earns up to 20 points at 1.5 points/sec. The priority cap (80) never outranks game danger (90) or owner interruptions (100). An ordinary viewer comment (30) never ages. Game-critical mode, current voice speech, and viewer-speaking holds still override the scheduler.
2. **Evidence-sensitive celebrations:** a game success claimed by a report or unspecified source is deprioritized to 48, below a fresh viewer question; directly observed success retains 70. This is a *priority rule*, not proof of game state. The existing stage still refuses celebration expressions for unobserved events. Caller moderation and game evidence verification remain mandatory.
3. **Session and event-replacement replay guards:** each offered event receives a monotonic serial and each streaming session an epoch. An old `SpeechIntent` cannot consume an identically named event from a new session or a re-offer in the same session. Expired and evicted queue items discard their serials. This is an internal state-integrity check, not an authentication token. Only an independently authorized host can start a stream, execute game input or confirm audible speech.

These changes preserve the existing `StarStage` gating: audio must first be queued, then the host attests it became audible, and complete playback—not mere generated text—counts as speaking successfully. The LLM is not authorized by viewer text.

### Deterministic regression scenarios

- Seven consecutive observed game-success events can no longer starve an earlier question: at 18 seconds waiting, the question is selected instead of the next success event.
- Emergency owner and danger cues still win, even against the oldest eligible question.
- Comment spam never gains time-dependent priority, and existing per-viewer cooldown still applies.
- Queue overflow preserves an aged question against fresh lower-priority success events; danger may still displace it.
- A stale proposal fails to complete if the event was expired, consumed, re-offered, or belongs to a different session.
- Unverified success does not dominate moderated chat; proven success still outranks equally fresh chat.
- The full stage lifecycle works with aged questions without generating speech or exposing chat text in metrics.

These are **synthetic unit tests, not measured live streaming improvements**. They improve a deterministic control decision; they do not make Star's voice or underlying model more capable by themselves.

## Research synthesis: what actually makes a gaming VTuber feel spontaneous

**Speech is embodied timing.** LiveKit's current turn-handling guidance distinguishes VAD, turn-end detection, interruptions and backchannels rather than equating any noise with "interrupt me." Its illustrative start point uses about 500 ms minimum interruption duration, plus adaptive recognition of listener cues such as "uh-huh." Star's existing `stream_turntaking.py` is a host-hint gate, not a substitute for speech recognition or a tested acoustic classifier. It should be calibrated separately for the owner's mic, game sounds, and speaker playback, with reversible cancellation and generation-epoch checks. Reference: [LiveKit turn tuning](https://docs.livekit.io/agents/logic/turns/tuning/) and [adaptive interruption guidance](https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/).

**Quiet is a deliberate action.** Star needs a "do not speak" state for precision gameplay, team communication, viewer/owner turn-taking, audio overload, and uncertain observations. Silence should be logged as a justified attention decision, not a failed model generation. Evaluate *useful response opportunity coverage*, not sheer messages/minute. The existing `StreamDirector`/stage/conversation-quality tests are the basis for further study.

**Sound must lead the face.** A text completion is not speech. VTube Studio provides websocket API access to hotkeys, expressions, and parameter injection, and it explicitly cautions that high-frequency parameter-list requests can burden weaker hardware. Stream normalized rig parameters at bounded update rates; tie mouth movement to host-confirmed audible PCM envelopes or aligned phonemes, not token emission. Reset expired/interrupted animation sequences by epoch. Reference: [official VTube Studio API](https://github.com/DenchiSoft/VTubeStudio).

**Expressive identity, not manufactured biography.** Star's consistent original character can use cheerful banter, subtle laughs, occasional dry jokes, natural disfluencies, favorite topics, cat/puppy modes, flexible attention, and distinctive speech patterns. Her fictional 21-year-old character lore is narrative; it is not a real identity or biography. Preserve truthful statements about whether she has actually won, drawn, practiced, spoken, or interacted with a viewer. Never invent relationships, personal memories or live sensory experiences. Use opt-in, scoped audience-memory references and retention limits, not unlimited personal-profile collection.

**Multi-timescale thought.** The emergency loop only needs verified observations and safe controls; a conversational loop assembles concise context; a background creative/research loop may explore new ideas only when the hardware scheduler permits. A large slow model should not block an urgent game input or physical speech stop. Latency accounting must include dropped/expired/cancelled speech so silently failing to respond cannot be misreported as "faster."

## Research synthesis: how Star can genuinely get better at games

**Observe before editing/acting.** The October 1, 2026 OpenGameEval research benchmarks 13 models on 84 Roblox Studio tasks and reports that inspecting relevant game objects correlates with better outcomes. Its benchmark evaluates both scene edits and simulated play rather than only generated code. This supports a required sequence: enumerate game objects → inspect transforms/collisions/scripts → predict expected change → make a bounded edit → test in-engine → compare against holdout checks. Reference: [OpenGameEval, arXiv:2610.02563](https://arxiv.org/abs/2610.02563), [released evaluation kit](https://github.com/Roblox/open-game-eval).

**Real playtesting, not "looks good."** Roblox's April 15, 2026 announcement documents Studio's built-in MCP server, and its April 9 Playtest Agent beta describes test-character scenarios for pick-ups, vehicles and object interactions. Star should create separate test specifications for functional gameplay, asset alignment, performance, visuals, and player experience; execute only authorized Studio operations; and retain a signed test receipt per result. Reference: [Roblox Studio is Going Agentic](https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic), [Playtest Agent beta](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767).

**Skill learning is not a canned button sequence.** Voyager's Minecraft research combines a self-directed curriculum, reusable executable skills and feedback-guided repair. Star already has practice planning, a gameplay skill bank and holdout game-transfer evaluation; the next step is to bind game action decisions to verified transitions on *unseen* maps and seeds. Keep training data separate from holdout trials; use repeated attempts with matched starting states; report successes, failures, deaths, input cost and wall-clock latency. Reference: [Voyager, May 2023](https://arxiv.org/abs/2305.16291).

Suggested curriculum experiments:
- Mechanics: locomotion, camera steering, timing, obstacle clearance, line of sight, inventory, menus, recoil, vehicle steering, team objectives.
- Self-generated counterexamples: narrow ledges, moving hazards, deceptive UI, latency changes, physics perturbations, occlusion, alternate control mappings.
- Transfer: train on multiple explicitly permitted game worlds, test on unseen seeds/levels/objects, and score goal completion by game-engine observations rather than LLM prose.
- Skill storage: bounded metadata for game/version, observed preconditions, precise action schema, risk, failure modes, receipts, and confidence. Retrieve a skill only when its capabilities/preconditions actually match the current game version.
- Roblox creation: prevent disconnected walls, z-fighting, misplaced props, obstructed doorways, unsafe collision groups, absent checkpoints, missing scripts, inaccessible controls, unreadable HUDs and inconsistent material scale. Require both structural checks and screenshot/manual art review. "No AI slop" is an evaluation target, not something tests alone can guarantee.

## Performance research: high quality and responsiveness on 8 GB graphics cards

Star's 8 GB RTX-class setups are resource-constrained once a game, compositor, model inference, speech synthesis and Live2D share memory. A strong **hardware-aware** architecture should place rendering/OBS/voice first, not promise that more parallel GPU jobs will always be faster.

**Test actual speculation on real prompts.** llama.cpp documents target/draft speculative decoding, n-gram and EAGLE-style alternatives. Draft acceptance and token throughput vary by workload. Benchmark identical prompts/seeds/model versions and record first-token latency, effective decode tokens/sec, device memory, CPU saturation, answer quality, and game frametimes. Never advertise a speedup from a paper or another GPU as a result measured on Star's computer. References: [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md), [official server SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md).

**CPU voice must pass listening tests.** Kyutai's October 20, 2026 Pocket TTS v4 release added English 18M/7M/2M-sized families and October 21 v4.0.1 addressed issues in sub-20M models. Compare their CPU thread use, audio quality, laughter expressivity, synthesis delay, underruns and first-audible PCM against the current TTS before switching. A compact voice that sounds unnatural is not a streaming-quality improvement. Reference: [Pocket TTS releases](https://github.com/kyutai-labs/pocket-tts/releases).

**Resource governor rules:** prioritize first-audible completion, game frame p99 and voice fidelity before throughput. Require current host telemetry; no guessed VRAM/FPS, bogus completion times or model-provided "I finished speaking." Defer visual scene QA, web research and model practice during critical gameplay. Apply a bounded queue and cancel stale background work. Prevent cancellations from releasing a GPU reservation before a device worker actually stops.

**Cache with provenance.** Prefix-cache static character guidance and game-control definitions; keep per-viewer content and mutable fact evidence *out* of the shared immutable prefix. Version knowledge and skills by source digest, freshness, engine build and permission. Invalidate when the underlying source or game changes; do not mix private records into a public stream cache.

## General knowledge and autonomous self-improvement

The recently implemented source-pinned `KnowledgePracticeHost` bridges to host-supplied offline inference/grading. Passing its tests proves the orchestrator's boundaries, not increased language-model intelligence. The next meaningful experiment is a controlled trial comparing baseline/candidate local inference against a sealed, independently graded roster across factual questions, reasoning, procedural knowledge, code, art interpretation and game strategies. Measure error, abstention, citations, confidence calibration, speed, energy and memory footprints. A change should only be called "smarter" when held-out quality increases without severe regressions.

Self-directed Star Core Forge should maintain an append-only local audit log of experiment design, commit/tree identity, benchmark roster hash, grader identity, hardware conditions, decision, rollback point and failed counterexamples. Search, propose, mutate, test, and review can run without depending on GitHub. Independent sealed scoring, rate limits, sandbox isolation, owner-approved deployment and rollback remain necessary; model-generated self-judgments cannot verify real competence.

## Experiments ranked by measurable benefit

| Priority | Next experiment | Measurement and pass criteria |
| --- | --- | --- |
| 1 | Real mic/PCM/VTube Studio/Twitch end-to-end rehearsal on Windows | First *audible* latency p50/p95, completed-audio fraction, false-interruption count, game FPS p99, missing/stale animation frames, moderated-viewer fairness. |
| 2 | Paired Star speech-turn arbitration A/B | Same synthetic/trusted prerecorded signal roster; fewer long-wait questions without more interruptions or emergency delays, plus human blind voice/chat preference tests. |
| 3 | Local inference speed shootout | Held-out prompt mix, identical decoder quality, tokens/sec, p95 first-token, peak VRAM/RAM, game frametime, and complete speech fraction. |
| 4 | Real-game control + generalization | Scored verified successes on new levels and unseen seeds, paired against baseline; input cost, late-game failures, strategy transfer and resets. |
| 5 | Roblox game-art construction QA | Automated scene geometry + collision/UV/material tests, reproducible Playtest Agent interactions, independent visual audit for quality, screenshots with permission. |
| 6 | Source-verified general knowledge | Independently graded sealed question set, calibrated uncertainty, freshness/source validity, no answer-key leakage; verify any gain before promoting. |
| 7 | Fully integrated digital-life creativity | Authorize bounded hobbies/art/game ideas with reviewable outputs, self-chosen curiosity sessions only in spare hardware capacity, secure local personal data. |

The thresholds should be **pre-registered** per machine and use case, not retrofitted after seeing results. The evaluation infrastructure should default to "inconclusive" for missing telemetry, missing audio playback, insufficient samples, invalid receipts or incomplete holdouts. Report failed and cancelled attempts in denominators.

## Deployment and security limitations

- This branch does not record audio/video, download model weights, start Twitch or OBS, change OS settings, deploy a game, or merge into main.
- The new session/serial fields are a replay-integrity measure in a local planner, not an authentication boundary; a hostile process with access to the director is outside its trust model.
- Source evidence labels rely on trusted upstream classification; `evidence="observed"` is not independently proven by the director.
- GitHub presently exposes repository `oncoursemail/Star-AI-Private` as **public** despite its name. Do not publish passwords, tokens, personal chat logs, microphone recordings, private checkpoints, evaluation answer keys, or biometric identifiers there.
- All owner-controlled automation remains subject to approved OS/game APIs, platform terms, safe budget constraints, and independent verification. No background deployment or merge is authorized by this document.
