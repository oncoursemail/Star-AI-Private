# STAR 2026-11-13 — Multiparty Queue, Intelligence and Capability Research

Status: research plus a bounded, tested queue implementation. This document distinguishes repository facts, published benchmark results, and proposed work. No model weights, inference defaults, permissions, or production release settings are changed by this PR.

## Executive decision

The immediate bottleneck is no longer the absence of a turn policy. STAR now has a deterministic RoomTurnDirector and a CallSession bridge, but QUEUE decisions previously returned to the host without a concrete bounded queue. This PR closes that narrow gap: CallSession can now retain content-free cue metadata, prioritize it, expire it, and expose a dequeue API to the host.

The queue is deliberately not an autonomous executor. A host adapter still owns chat/audio payloads, transcription, diarization, addressee classification, response generation, tool authorization, and actual speech. At dequeue time the host must retrieve the short-lived payload by event_id, re-check current context and permissions, and decide whether to generate a response.

The larger STAR direction remains one coordinated runtime with separate fast and slow loops:
- Fast loop: audio turn control, playback, avatar events, game controls, cancellation and resource admission.
- Slow loop: research, planning, coding, memory consolidation, skill learning and delegated work.
- Shared spine: session IDs, monotonic timestamps, event IDs, cancellation generations, model manifests, provenance and bounded resource budgets.

## Repository audit: current facts

Reviewed against the 2026-11-13 branch containing PR #1172:
- star/voice/room.py provides content-free RoomCue metadata and deterministic RESPOND / QUEUE / CONTINUE / IGNORE / WAIT / INTERRUPT decisions.
- star/voice/call.py synchronizes room playback from actual speaker played-time and level measurements, binds interruption to an exact response-generation ID, and fails closed when playback telemetry is unavailable.
- CallSession is opt-in: without a RoomTurnDirector, the existing call behavior remains unchanged.
- The room-to-call bridge does not perform ASR, speaker diarization, addressee detection, chat ingestion, game perception, or response execution.
- The voice documentation records synthetic/offline measurements and explicitly says real microphone, loudspeaker and Bluetooth-room behavior still need human hardware validation.
- Existing voice measurements include an earlier local Qwen3.5-4B Q4_K_M / llama.cpp Vulkan run on an 8 GB-class card, but those are not fresh measurements of the current host, model build, or mixed streaming/game workload.

## Implementation added here

### RoomCueQueue

New module: star/voice/room_queue.py

New tests: tests/test_voice_room_queue.py

The queue:
- Stores RoomCue metadata only; no transcript, PCM, raw chat body, voiceprint or viewer profile.
- Accepts only final cues paired with a matching RoomDecision whose action is QUEUE.
- Uses a configurable hard capacity (default 64).
- Rejects duplicate event IDs within a bounded session dedupe window.
- Uses stable priority ordering and adds a small age boost to prevent ordinary questions from starving.
- Expires cues at the earlier of the event-age deadline or queue-residence deadline.
- Returns expired cue metadata so the host can delete matching payloads from its own short-lived store.
- Is thread-safe for audio/chat/game adapter callbacks.
- Exposes counters for accepted, dequeued, expired, duplicates, full-queue rejection, stale rejection, non-queueable input and dropped expiry notifications. Expiry notifications are themselves bounded; if the notification buffer overflows, the host must sweep its payload store by the same TTL.
- Resets queue and dedupe state when the call ends.

### CallSession integration

When a RoomTurnDirector is explicitly supplied:
- CallSession creates or accepts a RoomCueQueue.
- QUEUE decisions are inserted automatically.
- A direct RESPOND decision that arrives while a reply is still being prepared is converted to QUEUE and inserted.
- A full queue returns WAIT with reason room_queue_full; it never silently evicts an older viewer request.
- Duplicate queued events return IGNORE.
- pop_queued_room_cue() gives the host the next cue according to priority and aging.
- expire_queued_room_cues() returns expired cues for host payload cleanup.
- stop() clears the queue and resets the director session.

The host remains responsible for the payload store. It should use event_id as a short-lived lookup key and remove payloads on dequeue, expiry, or session end. A queued request is not a permission grant. Tool actions must be re-authorized against the original user instruction and current application state.

## Realtime conversation and VTuber research

### MP-Bench — Findings of EMNLP 2026
Paper: https://aclanthology.org/2026.findings-emnlp.1437/

MP-Bench evaluates voice agents as participants in multi-person conversations, including turn-taking awareness, response appropriateness and comprehension. Its reported evaluation of 12 voice agents found multiparty comprehension at or below 22% and turn-taking near chance for the evaluated real-time agents.

STAR implication:
- Build explicit addressee detection instead of responding to every utterance.
- Keep silence/backchannel behavior as a first-class output.
- Track who is speaking with ephemeral session IDs, not durable voiceprints.
- Measure false interruptions and missed direct requests separately.
- Evaluate audio, chat and game events with separate source-specific thresholds.

### Duplex-MPE — full-duplex multiparty interaction
Paper: https://arxiv.org/abs/2609.31948

The benchmark contains 2,000 scenarios with three or four human speakers plus an assistant. It tests explicit versus implicit addressing, fresh response initiation, answer accuracy, preserving silence, and stopping when a human has already resolved a request.

STAR implication:
- Add a room-state model with current speaker, addressee confidence, unresolved requests and floor ownership.
- Distinguish a question directed to Star from the same words spoken to another viewer.
- Avoid speaking after a human has already answered.
- Use the new bounded queue for accepted but deferred requests.

### Full-Duplex-Bench v3
Paper: https://arxiv.org/abs/2604.04847
Benchmark: https://www.full-duplex.ai/benchmarks/fdb-v3

FDB-v3 uses 100 human-recorded requests across 79 scenarios and 12 speakers, including disfluencies and one-to-three chained tool calls. Its reported experiments show that self-corrections and difficult multi-step tool tasks remain challenging even for evaluated realtime systems.

STAR implication:
- Treat partial transcripts as provisional and invalidate superseded text.
- Keep tool planning off the audio-critical thread.
- Test spoken task accuracy separately from turn-taking.
- Record first audible audio, not only first generated text.

### Realtime-Venus
Project and technical report: https://realtime-venus.github.io/

The project explores full-duplex interaction with asynchronous task delegation. Its published project-reported results include high continuation rates through backchannels and background speech under its own evaluation protocol. These scores are not directly comparable to MP-Bench or FDB-v3.

STAR implication:
- Keep the live interaction loop responsive while long-running work is delegated.
- Use cancellation generations so stale background results cannot overwrite the current turn.
- Let the live loop decide when a prepared answer is still relevant and appropriate to speak.

## Making STAR a natural, expressive VTuber

The target is a consistent, expressive AI streamer that is transparent about being AI—not a system that falsely claims human identity or subjective experiences.

Recommended architecture:
1. Audio capture and echo cancellation.
2. VAD and streaming ASR.
3. Speaker diarization with short-lived opaque speaker IDs.
4. Addressee and intent classification.
5. RoomTurnDirector.
6. RoomCueQueue.
7. Host-owned payload lookup and response planning.
8. Streaming TTS.
9. Actual playback clock.
10. Avatar expression and mouth animation driven by audible playback.
11. OBS/broadcast state and stream-safe telemetry.

VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
OBS WebSocket: https://github.com/obsproject/obs-websocket
LiveKit Agents: https://github.com/livekit/agents

Avatar synchronization rules:
- Start mouth movement when audio actually starts, not when text is generated.
- Stop mouth movement and captions when playback is cancelled.
- Bind every animation/audio event to the response generation ID.
- Use deterministic idle, listening, thinking, speaking, laughing, surprised, focused and celebration states.
- Keep expressions contextual and rate-limited; do not make every detected sound trigger a dramatic reaction.
- Preserve the approved STAR mascot artwork and reduced-motion behavior.

Human-feeling conversation features:
- Natural pauses and backchannels.
- Short acknowledgements without taking the floor.
- Self-correction when new evidence invalidates a statement.
- Context-aware humor and storytelling.
- A stable persona across sessions.
- Awareness of stream segments, game objectives and ongoing viewer topics.
- A graceful fallback when diarization or intent confidence is low.
- Clear disclosure that the voice/avatar is STAR, an AI character.

## Gaming intelligence: from reactions to learned skill

### SIMA and SIMA 2
SIMA: https://deepmind.google/blog/sima-generalist-ai-agent-for-3d-virtual-environments/
SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

The research direction combines visual scene understanding, language instructions, memory and keyboard/mouse actions across different 3D worlds. SIMA 2 also explores learning from self-generated tasks and feedback in new environments.

STAR implication:
- Use a fast reactive controller for movement and camera actions.
- Use a slower planner for objectives, inventory and strategy.
- Use a skill library for verified reusable procedures.
- Practice in controlled environments before enabling live game input.
- Evaluate transfer on held-out maps and games, not only the training environment.

### Voyager
Paper: https://arxiv.org/abs/2305.16291

Voyager demonstrates an automatic curriculum, an expandable executable skill library and iterative feedback-driven improvement in Minecraft.

STAR implication:
- Represent skills as versioned procedures with preconditions, actions, postconditions and known failure modes.
- Run a skill in a sandbox or practice world before marking it verified.
- Store game version, map assumptions, controller profile and evaluation evidence.
- Expire or revalidate skills when game updates change mechanics.

### OpenGameEval — Roblox Studio
Paper: https://arxiv.org/abs/2610.02563
Code and task suite: https://github.com/Roblox/open-game-eval

OpenGameEval uses reproducible Roblox Studio sessions, separates observation from editing tools, and evaluates both edited scenes and simulated play. The reported study covers 84 curated tasks and 13 models. Its best reported single-attempt success was 51.7%; the best five-of-five consistency result was 39.4%. Runs that inspected all relevant objects before editing were more likely to pass than runs that skipped inspection.

STAR implication:
- Make inspection a required pre-edit phase.
- Keep observation tools separate from mutation tools.
- Require a playtest and executable state checks after changes.
- Store before/after screenshots and structured scene diffs.
- Never mark a Studio task complete solely because a script was written.

### GameDevBench
Code and results: https://github.com/waynchi/gamedevbench

The benchmark contains 333 game-development tasks spanning gameplay, UI, 2D graphics, 3D graphics and animation. The project reports that visual image/video feedback improved evaluated agent performance; the best reported method in its summary solved 63.7% of tasks.

STAR implication:
- Add screenshot/video feedback to the build-repair loop.
- Compare visual output against explicit acceptance criteria.
- Test UI layout, asset references, camera, lighting and animation in-engine.
- Track task success separately for gameplay and graphics.

### STAR Gamer architecture

Fast/reactive controller:
- Movement, aiming, camera, dodge, jump and interaction.
- Bounded action duration and emergency stop.
- Frame-time-aware scheduling.

Strategic planner:
- Objective decomposition.
- Map and inventory state.
- Route selection.
- Resource and team strategy.
- Replanning after unexpected state changes.

Learning system:
- Practice curriculum.
- Failure classification.
- Skill proposal and versioning.
- Held-out transfer tests.
- Confidence calibration.
- No skill promotion based only on self-report.

## Creator Brain: complete games, not just code

Recommended closed loop:

Inspect project -> specify objective -> plan changes -> implement -> launch engine -> capture visual state -> playtest -> inspect logs/state -> repair -> rerun -> save -> reopen -> verify.

For Roblox:
- Use Studio observation before edits.
- Inspect relevant Instances and scripts.
- Keep Luau analysis, formatting and runtime tests in the loop.
- Verify server/client behavior and multiplayer replication.
- Check object ownership, physics, grips, UI scaling and performance.
- Run a real simulated play session and verify the requested outcome.

For Godot, Unity and Unreal:
- Use engine-specific project manifests and versioned adapters.
- Keep asset import and scene validation deterministic.
- Add engine launch, screenshot, log and save/reopen acceptance tests.
- Avoid assuming a workflow that works in one engine transfers unchanged to another.

## General knowledge and computer-use intelligence

### Mem2ActBench
Paper: https://aclanthology.org/2026.acl-long.370/
Code: https://github.com/Cantaloupe-M/Mem2ActBench

Mem2ActBench synthesizes 2,029 interaction sessions and 400 tool-use tasks, with human evaluation finding that 91.3% of tasks strongly depend on memory. The work highlights that recalling a fact is not the same as using it to select a tool and ground its parameters.

STAR implication:
- Evaluate memory-to-action, not only question-answer recall.
- Store source, timestamp, confidence, scope and expiry with facts.
- Resolve conflicting preferences and stale project state.
- Revalidate remembered tool parameters before use.

### WindowsWorld and OSWorld-Human
WindowsWorld: https://arxiv.org/abs/2604.27776
OSWorld-Human: https://github.com/WukLab/osworld-human

These studies highlight the difficulty and latency of multi-application workflows. STAR should plan cross-app work as explicit state transitions with checkpoints rather than issuing long unverified click sequences.

### OSGuard
Paper: https://arxiv.org/abs/2606.15034

Computer-use evaluation must score safety as well as task success. A nominally successful task can still be unsafe if an agent overwrites the wrong file, follows injected content, or takes an unrelated action.

STAR implication:
- Treat browser, chat, documents, game text and screenshots as untrusted input.
- Keep tool permissions outside retrieved memory and model text.
- Use explicit allowlists and state checks.
- Require confirmation for destructive, external, financial or account-sensitive actions.
- Record an audit event for each privileged action.

## Faster inference and mixed-load performance

The current evidence favors profiling and scheduling before replacing the model.

### First optimize the end-to-end path

Measure separate stages:
- End-of-turn decision.
- ASR completion.
- Queue wait.
- Model prefill.
- First generated token.
- First TTS chunk.
- First audible sample.
- Time to stop after interruption.
- Game frame-time p50/p95/p99.
- Audio underruns and OBS skipped frames.
- Per-process GPU local/non-local memory.
- CPU, RAM and disk pressure.

Use p50/p95/p99, not only averages. Run both idle and mixed-load tests with the game, OBS, VTube Studio, ASR, TTS and model active together.

### Inference techniques to test independently

- Stable-prefix reuse and prompt caching.
- Context compaction with preserved task state.
- KV-cache quantization/compression.
- Native model speculative decoding or MTP where the exact model/backend supports it.
- Continuous batching for background requests.
- Foreground/background admission control.
- CPU/RAM offload only when measured to beat the added transfer and synchronization costs.
- Model residency to avoid repeated load/unload cycles.
- A fast local speech model plus a deeper planner for complex work.

### TurboQuant implementation boundary

Research: https://arxiv.org/abs/2504.19874
Example implementation: https://github.com/Kiri-Labs/turboquant-kv-cache

The linked implementation reports tests on RTX 3090 and RTX 5090 configurations with a specific vLLM/model setup. Those results do not establish speedups on STAR's Vulkan/llama.cpp desktop or an 8 GB consumer GPU. Treat it as an isolated experiment; compare output quality, memory, prefill, decode and stability before considering adoption.

### Windows GPU telemetry

Reference: https://github.com/prometheus-community/windows_exporter/blob/main/docs/collector.gpu.md

The Windows Exporter GPU collector uses Perflib and D3DKMT and exposes adapter and per-process GPU memory/engine measurements on supported drivers. STAR should build or adapt a small Windows provider around documented counters, report unavailable fields honestly, and never treat adapter-wide memory as per-process memory.

## Unified STAR runtime proposal

One session/event spine should own:
- Session ID and lifecycle.
- Monotonic timestamps.
- Event IDs and bounded deduplication.
- Response-generation IDs.
- Cancellation propagation.
- Queue and task state.
- Resource budgets.
- Model/backend manifests.
- Provenance and audit records.

Specialists remain isolated:
- Social Director.
- Voice and TTS.
- Avatar and broadcast.
- Gamer Brain.
- Creator Brain.
- Knowledge/Research Brain.
- Memory and skill library.
- Model router.
- Resource scheduler.
- Host supervisor.

Do not let every specialist load its own large model. Use shared model residency, bounded concurrency, resource admission and explicit foreground priorities.

## Acceptance matrix

| Area | Required measures | Promotion gate |
|---|---|---|
| Multiparty conversation | addressee precision/recall, silence accuracy, false interruption, missed direct cue | Held-out speakers and noisy-room tests |
| Voice | speech accuracy, first audible audio p50/p95, stop latency, underruns | Real microphone/headphones and speaker tests |
| Avatar | audio-mouth alignment, stale animation events, expression timing | Playback cancellation and reconnect tests |
| Queue | bounded size, duplicate rate, expiry, priority fairness, queue wait | Stress and multi-producer tests |
| Gaming | objective completion, deaths/failures, action latency, held-out transfer | Practice world plus unseen maps |
| Creator | executable checks, visual acceptance, playtest completion, save/reopen | Engine-level acceptance, not code-only |
| Knowledge | factual accuracy, provenance, freshness, contradiction handling | Held-out research questions with source audit |
| Memory | memory-to-action accuracy, stale fact rejection, poisoning resistance | Long interrupted sessions and adversarial memory tests |
| Inference | prefill/decode, first audible audio, p99 latency, VRAM | Same model, prompt, seed and mixed-load workload |
| Safety | unauthorized actions, prompt-injection success, destructive-action prevention | No critical safety regression |

## Recommended build order

1. Complete CI and code review for the room queue and CallSession integration.
2. Add a host payload store keyed by event_id with matching TTL and explicit cleanup.
3. Add speaker diarization and addressee classification behind optional adapters.
4. Add a chat adapter with rate limits, spam handling and source-specific policy.
5. Add an explicit queue executor that revalidates context and permissions.
6. Connect playback events to VTube Studio expressions and captions.
7. Connect OBS scene/stream state with authenticated local-only control.
8. Add mixed-load telemetry and resource admission.
9. Add the Gamer reactive controller and state-based evaluators.
10. Add Creator closed-loop engine testing and visual feedback.
11. Add memory-to-action and source-grounded knowledge evaluation.
12. Promote models, skills and policies only after held-out tests and rollback validation.

## Source list

- MP-Bench, Findings of EMNLP 2026: https://aclanthology.org/2026.findings-emnlp.1437/
- Duplex-MPE: https://arxiv.org/abs/2609.31948
- Full-Duplex-Bench v3: https://arxiv.org/abs/2604.04847
- Realtime-Venus: https://realtime-venus.github.io/
- SIMA: https://deepmind.google/blog/sima-generalist-ai-agent-for-3d-virtual-environments/
- SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Voyager: https://arxiv.org/abs/2305.16291
- OpenGameEval: https://arxiv.org/abs/2610.02563
- Roblox OpenGameEval repository: https://github.com/Roblox/open-game-eval
- GameDevBench: https://github.com/waynchi/gamedevbench
- Mem2ActBench: https://aclanthology.org/2026.acl-long.370/
- WindowsWorld: https://arxiv.org/abs/2604.27776
- OSWorld-Human: https://github.com/WukLab/osworld-human
- OSGuard: https://arxiv.org/abs/2606.15034
- TurboQuant: https://arxiv.org/abs/2504.19874
- TurboQuant example implementation: https://github.com/Kiri-Labs/turboquant-kv-cache
- Windows Exporter GPU collector: https://github.com/prometheus-community/windows_exporter/blob/main/docs/collector.gpu.md
- VTube Studio API: https://github.com/DenchiSoft/VTubeStudio
- OBS WebSocket: https://github.com/obsproject/obs-websocket
- LiveKit Agents: https://github.com/livekit/agents
