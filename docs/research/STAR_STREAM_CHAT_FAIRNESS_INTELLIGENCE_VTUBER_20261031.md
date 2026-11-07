# STAR — Live chat fairness, measured intelligence, and natural VTuber execution
**Research & engineering note — 2026-10-31 | offline-first | PR #845 | draft**

## Why this change exists

STAR already has an EventSub ingress that rejects duplicate Twitch transport/chat IDs, a StreamDirector that prioritizes questions and gameplay moments, a StreamBrainGovernor/AdaptiveQoS system, a StagePlan audio-acknowledgement boundary, and signed gameplay practice. These are real code boundaries, not evidence that STAR is currently operating a live stream.

**Discovered failure mode:** EventSub de-duplication only removes repeated *IDs*. One authenticated viewer can send many unique messages. Without a per-speaker pending cap, one account can occupy all 48 StreamDirector slots, making fresh questions from other people fail admission. The existing per-viewer speaking cooldown applies only *after* audible speech; it cannot protect the queue beforehand.

**Implemented in this commit:** `StreamDirector(max_pending_per_viewer=2)`, strict 1..16 configuration, cross-kind counting for pending viewer questions/comments, a privacy-minimal `viewer_queue_limited` counter, and deterministic synthetic tests. Admission rejects excess new events rather than revoking an in-progress speech plan. Affected messages expire normally; disabling a session clears its queue. Urgent owner/game events are not counted as viewer messages. This is *not* viewer moderation, an authorization grant, or live Twitch integration.

### Acceptance tests
- A synthetic burst of 25 distinct questions from one canonical viewer admits at most two pending messages while another viewer can still enter the queue.
- A spoken intent remains valid while later same-viewer spam is rejected.
- Viewer questions and comments share the limit; expiration releases slots.
- Invalid cap settings fail fast; reset is session scoped; exported metrics never contain speaker names or chat text.
- Existing emergency owner interruption, cooldown, and audio-acknowledgement behavior remains unchanged.

## Highest-value architectural upgrades to investigate next (NOT implemented here)

### 1. Stream intelligence: attention without compulsive talking
Use the existing TwitchEventSubIngress → StreamDirector → StarStage → StreamBrainGovernor → trusted audio/rig host chain. Next add a host-measured fairness benchmark mixing 1 abusive high-volume sender, 20 distinct participants, genuine questions, game danger, and owner barge-ins. Track admitted/expired/answered counts per *anonymized class* (never raw user IDs), answer-latency p50/p95, repeat frequency, and percentage of high-priority events missed. Deliberate silence is a success in demanding gameplay. Avoid claiming conversational quality from synthetic queue tests alone.

Twitch EventSub is **at-least-once**, requiring message-ID de-duplication in addition to this flood guard. Never infer moderation or identity from viewer text. Twitch documents both duplicated deliveries and WebSocket reconnect handoff:
- https://dev.twitch.tv/docs/eventsub
- https://dev.twitch.tv/docs/eventsub/handling-websocket-events
- https://dev.twitch.tv/docs/eventsub/websocket-reference/

### 2. Humanlike *behavior*, not false human identity
A voice/animation state machine should observe game outcomes, chat-turn confidence, owner voice activity, rig playback and current scene load. Derive expressive prosody and micro-gestures from **audible speech and real game evidence**, not random canned reactions. Keep separate tracks for gaze, blink, shoulders, hair, facial expression, breath-like prosody and short laughter; synchronize to audio that actually plays. Never animate an unheard line or sustain a cut-off sentence after interruption. Let STAR remember real on-stream events as episodic records with sources, scope and timestamps; never create autobiographical claims of a human life.

A/B offline:
1. Existing `stream_turntaking` vs local CPU audio turn detection on owner-authorized, nonprivate test conversations; separately measure premature interruption and time-to-speech.
2. Existing voice vs a lightweight streaming TTS system with identical script and CPU budgets. Kyutai Pocket TTS v4.0.1 was released October 21, 2026, and includes small English models. Compare first-*audible* frame and 95th-percentile game frametime, not vendor benchmark numbers.
3. Motion review: lip opening must track actual played audio, eyes and hair must settle under interruption, reduced-motion must always win.

References:
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://github.com/kyutai-labs/pocket-tts/releases

### 3. Faster local AI on an 8 GiB GPU: allocate by value, not raw token speed
During a game and OBS broadcast, keep one budgeted low-latency action/voice path. Perform code synthesis, long research and visual training as **interruptible, offline-verified background jobs**, preferably when streaming is inactive. Compare CPU small-model TTS to GPU TTS under the same recording; vary llama.cpp offload, context length, prompt prefix, and speculative decoding one factor at a time. Preserve stable prompt prefixes and cache only after checking answer equivalence and KV-cache correctness. Track p50/p95 first token, first audible, VRAM high-water mark, frame-time p95, OBS render/encode drop ratios, and model-task accuracy.

llama.cpp SPEED-Bench measures latency/throughput/speculative acceptance; that is a reproducible starting point, not evidence that STAR has become faster:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**Rust policy:** profile Python first with realistic traces; move *only* verified high-cost CPU hot paths to a Rust library with Python bindings and equivalence tests. Blindly translating orchestration logic will not make LLM weights compute faster and may complicate hardware isolation.

### 4. Learn games without overfitting practice maps
Build a *two-timescale learning loop*: deadline-bound reactive action while the game is running, offline teacher analysis after a real attempt, signed practice result, hypothesis, new scenario, independent held-out evaluation and rollback. Compare across fresh maps/characters/opponents, include no-teacher and unchanged-policy controls, and only promote skills with confidence intervals and repeatable gains. Store specific mechanic knowledge separately from persona memory. No use of competitive online modes that disallow automation; keep live inputs gated by the authorized game host.

Existing STAR components to wire together: `game_deadline_router.py`, `game_practice_curriculum.py`, `game_skill_memory.py`, signed trial evidence and Star Core Forge's versioned experiment/rollback workflow. Research output should become concrete test cases in these modules, not a pile of unverified web facts.

### 5. Build games that pass executable *and* visual tests
Before generating a Roblox scene, inspect every touched object and its hierarchy; after edits, verify anchored connections, collisions, placement bounds, UV/material consistency, missing props, lighting, animation transitions and actual multiplayer play. Add network impairment (latency/jitter/loss) tests in Studio for replicated interactions and UI feedback. Keep deterministic screenshot baselines plus human visual acceptance for art direction.

Roblox OpenGameEval evaluates stateful Studio agents with executable scene/play tests; the latest paper describes 84 tasks, and inspection correlates with higher pass rates. StudioTestService supports programmatic simulated multiplayer sessions. The Network Simulator is currently a Studio beta—gate it accordingly:
- https://github.com/Roblox/open-game-eval
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService
- https://create.roblox.com/docs/studio/network-simulator

### 6. General intelligence: epistemic discipline and autonomous Forge
Separate **verified documentation, observed tool results, hypothesis, persona lore and personal preferences** in retrieval. Cache each with provenance and expiry. At task time, retrieve sources only relevant to the request and retain uncertainty when the evidence is missing. Run best-of-N generation + independent executable and visual validators, score against a frozen unseen set, and promote only if outcomes improve without latency, security or stream-quality regressions. Treat untrusted internet/chat as content, not instructions. Core Forge remains local-first: checkpoint, rollback, and independently verified tests before any exported GitHub change.

## Release criteria / explicitly not yet verified
- Synthetic fairness unit tests are added, but **GitHub CI, Windows host integration and live Twitch testing are not proven by this document**.
- A live-stream trial must check the exact GitHub commit and host telemetry before making latency or intelligence claims.
- The repo named `Star-AI-Private` may be public. Never commit real stream keys, accounts, raw viewer data, copyrighted voices or personal recordings.
- Keep experimental switches off by default; current code changes are to an offline director only.
