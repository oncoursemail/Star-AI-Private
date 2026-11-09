# STAR • Event-aware VTuber speech calibration and capability roadmap

Research and implementation note: 2026-11-09.

This update adds event-specific speech pacing to the existing owner-opt-in VTuber stage. It is an offline Python capability until the native Windows host supplies the exact stage kind and independently observed audio receipts.

## Executive finding

A single average speaking rate is too coarse for a live gaming companion. A short danger reaction, a delighted success reaction, a viewer answer, and a quiet acknowledgement have different intended delivery styles and different useful lengths. Pooling all of them can make a conservative estimate for one event unnecessarily restrictive for another, or make a slow event's timing estimate inappropriate for a short, urgent reaction.

The practical design is hierarchical, not a separate model for every event:

1. Prefer a calibrated p90 rate for the exact event kind and current game/stream load regime.
2. If that bucket has fewer than the configured minimum of eight completed samples, fall back to the same voice-route and load-regime pooled history.
3. If neither bucket has enough evidence, use the existing conservative cold-start rate.
4. Never cross a voice route, device, game-active state, streaming-load state, session reset, or event-kind boundary when using an intent-specific estimate.

This preserves a safe fallback for rare events while allowing frequently observed event types to develop their own timing profile.

## Research basis

### Proactive, real-time companions

Microsoft Research's Proact-VL (ICML 2026) evaluates gaming companion scenarios including solo commentary, co-commentary, and user guidance. Its central problem formulation includes both deciding when to respond and controlling response quantity under continuous visual input. This supports task- and event-aware commentary policies; it does not directly validate STAR's exact eight-sample p90 estimator.

Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

### Real game creation needs exploration and execution

OpenGameEval runs agents in reproducible, stateful Roblox Studio sessions and checks both edited scenes and simulated play. The October 2026 paper reports 84 curated tasks across 13 models. Its analysis finds that inspecting task-relevant objects before editing is associated with higher pass rates than editing without inspection. STAR should therefore treat project exploration as a first-class phase, not jump directly from a prompt to code generation.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

### Measure local inference, not marketing claims

The llama.cpp SPEED-Bench client reports latency, throughput, and draft acceptance by benchmark category for an already-running server. This is a useful pattern for STAR: measure short chat, long reasoning, code, and vision-adjacent workloads separately; do not promote speculative decoding or a second resident model based only on tokens/second from one prompt.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

### Real-time game skill is not paused-game skill

Gym-Anything-RT studies agents in continuously changing game environments. STAR's fast observation/action loop must be evaluated with wall-clock deadlines and fresh observations; a strong offline planner does not prove the reflex loop can act in time.

Source: https://arxiv.org/abs/2610.37567

## Implemented in this branch

- StreamSpeechPacer.observe_audible() accepts an optional host-owned intent_kind from the exact StagePlan.kind.
- Every accepted sample contributes to a bounded pooled history for its game/stream regime. A sample with a valid intent kind also contributes to a bounded event-specific history.
- advise() uses the event-specific p90 only after at least eight samples; otherwise it backs off to the pooled p90, then to the existing conservative cold-start estimate.
- PacingAdvice.calibration_scope distinguishes intent, workload, cold_start, and none.
- StagePlan exposes pacing_scope and pacing_samples as diagnostics. They are not permissions and do not authorize speech, TTS, avatar output, game input, or broadcast.
- Invalid or viewer-invented event kinds are rejected. No transcript, audio, viewer identity, or prompt is stored.
- Added regressions for event-style isolation, sparse-bucket fallback, invalid event labels, and stage diagnostics.

## Native host contract still required

The Windows host must call observe_audible() only after a completed utterance has actually reached the selected output device, with:
- the exact StagePlan.kind copied from the immutable prepared plan;
- the canonical TTS model/runtime/output-device route ID;
- a monotonic, non-replayed sample ID;
- the actual spoken-word count;
- first- and last-audible timestamps from the same monotonic clock used by the stage;
- current game-active and stream-load regime;
- explicit trusted-host confirmation.

Do not infer audible completion from a model response, TTS return code, enqueue operation, or generated PCM buffer. An interrupted utterance must not be counted as a completed sample. The Windows host still owns physical STOP/FLUSH, cancellation, output-device identity, OBS policy, and broadcast approval.

## Acceptance experiment

Run randomized paired A/B/A trials with the same game, avatar, TTS route, power mode, and prompt/event corpus. Include at least:
- urgent danger events;
- success/reward events;
- neutral gameplay observations;
- viewer questions and acknowledgements;
- cold and loaded GPU/CPU conditions;
- interruptions, device switches, OBS reconnects, and long sessions.

Report per-event and pooled p50/p90/p95 audible seconds per word, first-audible latency, deadline-miss rate, hold/silence rate, interrupted-speech rate, response correctness, viewer-turn overlap, game frame-time p95/p99, OBS dropped frames, audio underruns, CPU/RAM/VRAM peak, and model time-to-first-token. Use holdout sessions to check that calibration transfers to later streams. A route is useful only if timing improves without worsening content quality, game smoothness, or viewer turn-taking.

## Broader Star capability roadmap

- General knowledge: source-attributed, time-aware facts with contradiction handling; keep observations, experiences, opinions, owner preferences, and verified skills as distinct record types.
- Intelligence: hybrid retrieval (lexical + vector + temporal + graph), small rerankers only when latency allows, explicit uncertainty, and benchmarked model routing.
- Speed: one primary resident model on the 8 GB GPU by default; test prompt/KV reuse, n-gram speculative decoding, and CPU TTS against the same paired workload. Defer background vision/reasoning when game or OBS pressure rises.
- Gaming: fast reflex loop plus slower tactical planner; private practice curricula; hidden holdouts; skill transfer across maps/difficulties; keep game-specific action allowlists outside the model.
- Game creation: inspect → plan → edit → instrument → playtest → compare-to-intent → repair; evaluate Luau, replication, physics, UI, accessibility, performance, exploit resistance, and actual playability.
- VTuber presence: event-aware commentary, natural silence, barge-in, immediate cancellation, voice/face synchronization, memory-grounded callbacks, moderation, and long-session health checks. Make the personality expressive and consistent without claiming biological human experiences.

## Release boundary

This is a bounded offline estimator improvement, not a neural model speedup, gameplay win-rate improvement, Windows/WASAPI integration, or live broadcast capability. The feature remains owner-opt-in and host-mediated. The next gate is Windows integration and a private 30–60 minute game + OBS + voice + avatar rehearsal with independently measured receipts.
