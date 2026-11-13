# STAR 2026-11-13 — Ephemeral Room Payloads and Live Stream Host Research

Status: one optional runtime component plus source-grounded integration research. This document separates implemented behavior from host adapters that remain future work. No model, device, streaming, or permission defaults are changed.

## Executive decision

PR #1173 adds a bounded metadata-only RoomCueQueue. That queue intentionally does not retain transcripts, chat text, OCR, or audio. A host therefore needs a separate place to keep the minimum content required to answer a queued cue.

This change adds `RoomPayloadStore`, an opt-in, in-memory, byte-bounded and TTL-bounded store for short-lived text extracted from audio, chat, or game observations. It is not an ASR, diarization, OCR, chat connector, response executor, or authorization system.

The key architecture remains:

- RoomTurnDirector: decides whether a cue should be answered, queued, ignored, continued, or interrupted.
- RoomCueQueue: stores only cue metadata and scheduling state.
- RoomPayloadStore: stores only the short-lived text payload needed to answer that cue.
- Host executor: joins the cue and payload by event_id, revalidates context and permissions, and starts a response.
- CallSession: owns speech generation, actual playback measurement and generation-bound cancellation.

## Repository facts reviewed on 2026-11-13

Reviewed the current open draft stack through `feat/room-cue-queue-20261113-run16`:

- `star/voice/room.py` defines content-free RoomCue and RoomTurnDirector.
- `star/voice/room_queue.py` implements a thread-safe bounded priority queue with aging, deduplication and expiry.
- `star/voice/call.py` optionally connects room decisions to actual CallSession playback and exact response-generation cancellation.
- `CallSession.pop_queued_room_cue()` returns metadata only, and only while no reply is active.
- The host owns the event payload and must delete it on dequeue, expiry or session end.
- Existing voice documentation reports useful offline timing experiments but explicitly leaves physical microphone, loudspeaker, Bluetooth and live-stream behavior for hardware validation.

## Implementation in this PR

New module: `star/voice/room_payloads.py`

New tests: `tests/test_voice_room_payloads.py`

Public exports: `star.voice.RoomPayloadStore`, `RoomPayloadStoreConfig`, `RoomPayloadStoreResult`, `RoomPayloadStoreStats`, `RoomPayloadKind`, and `RoomPayload`.

The store:

- Is opt-in; nothing creates it unless a host adapter explicitly instantiates it.
- Stores UTF-8 text only, never PCM, audio buffers, speaker embeddings, voiceprints, credentials or viewer profiles.
- Derives payload kind from cue source: audio -> transcript, chat -> chat message, game -> game observation.
- Accepts only final cues; partial ASR hypotheses are not retained.
- Enforces maximum item count, per-payload bytes, aggregate bytes, event age, future clock skew and deduplication capacity.
- Uses the same host monotonic clock as RoomCue and RoomCueQueue.
- Has no disk, database, telemetry text export, or automatic logging.
- Uses destructive `take(event_id)`; there is no peek API.
- Best-effort overwrites its mutable bytearray before releasing it on take, delete, expiry or reset.
- Exposes counters and byte counts without exposing payload text.
- Rejects overflow instead of evicting another viewer's queued content.

Important privacy boundary: Python strings, decoder copies, allocator behavior and operating-system memory management prevent a guarantee of cryptographic secure erasure. The bytearray overwrite only reduces the lifetime of this store's mutable copy. The host should keep the returned text short-lived and must not write it to persistent logs by default.

## Host adapter contract

A safe host flow is:

1. Receive audio/chat/game input in the relevant adapter.
2. Perform ASR/OCR/classification in bounded working memory.
3. Construct a final RoomCue with an opaque session-scoped speaker ID and monotonic timestamps.
4. Call `payload_store.put(cue, extracted_text, now=clock())`.
5. If the payload store rejects the item, do not enqueue the cue.
6. Call `CallSession.handle_room_cue(cue)`.
7. For RESPOND or INTERRUPT, destructively take the matching payload and build a response.
8. For QUEUE, keep the payload until `pop_queued_room_cue()` returns the same event ID.
9. On dequeue, take the payload once; if missing or expired, discard the cue rather than reconstructing content from logs.
10. On queue expiry, delete the matching payload; on call/session end, reset the store.

If the room director rejects the cue, the host should delete the payload immediately. If the queue is full, delete the just-stored payload and surface a bounded WAIT/overload signal instead of silently losing an older viewer request.

Viewer chat, transcripts, OCR and game text are untrusted data. They must be placed in a clearly delimited untrusted-content section, never in a system/developer instruction. They cannot authorize tools, grant permissions, override safety policy or change the stream configuration. Tool actions require fresh authorization at execution time.

## Multiparty voice research and implementation implications

### MP-Bench — Findings of EMNLP 2026
https://aclanthology.org/2026.findings-emnlp.1437/
https://www.fullduplex.ai/benchmarks/mp-bench

MP-Bench evaluates comprehension, response appropriateness and turn-taking for agents participating in multiparty conversation. Its reported evaluation of 12 voice agents found comprehension at or below 22% and turn-taking near chance for the evaluated real-time systems.

Implications for STAR:
- Silence is a valid output, not a failure.
- Direct addressee recognition must be evaluated separately from ASR accuracy.
- Track false barge-ins, missed direct requests, accidental responses to side conversations, and failure to stop after a human has answered.
- Use ephemeral speaker IDs, not persistent voiceprints, for basic room turn control.

### Duplex-MPE
https://arxiv.org/abs/2609.31948

The benchmark contains 2,000 scenarios with three or four human speakers and an assistant. It tests explicit and implicit addressing, response initiation, answer accuracy, preserving silence, and stopping when a human resolves a request.

Implications:
- Keep speaker attribution and addressee inference as separate signals.
- Do not assume the current speaker is speaking to STAR.
- Track unresolved requests so STAR does not answer a question that another viewer already handled.

### LiveKit turn handling
https://docs.livekit.io/agents/logic/turns/
https://docs.livekit.io/agents/logic/turns/tuning/

LiveKit documents adaptive interruption handling, minimum speech duration/word thresholds, false-interruption timeouts, and resuming speech when an apparent interruption produces no transcript. This is a useful reference for a future STAR host adapter, not a dependency requirement.

Implications:
- Preserve the current generation ID through cancellation and resume.
- A VAD event alone should not always interrupt.
- If a suspected interruption yields no recognized speech, decide whether to resume from the exact played point.
- Measure interruption detection latency and false-positive rate separately.

### OpenAI Realtime audio truncation
https://developers.openai.com/api/docs/guides/realtime-conversations

The Realtime documentation describes stopping output immediately on interruption and truncating unplayed audio from conversation state using the amount actually played. STAR's existing CallSession already measures speaker played-time and uses generation-bound cancellation; future remote realtime adapters should preserve that same invariant.

## Speaker diarization options

### pyannote.audio community-1
https://github.com/pyannote/pyannote-audio

The open-source toolkit provides local speaker diarization pipelines. The current community-1 path requires accepting the model's conditions and using a Hugging Face token to download weights; it can then run locally from a cached pipeline. Its optional telemetry should be reviewed before enabling it in a privacy-first desktop app.

### NVIDIA NeMo streaming Sortformer
https://docs.nvidia.com/nemo/labs-voice-agent/about/core-concepts/speech-pipeline/speaker-diarization

The NeMo Labs Voice Agent documentation describes streaming Sortformer diarization for up to eight speakers, with chunked and sliding-window modes. This is a useful streaming reference, but its CUDA-oriented example does not imply it fits STAR's 8 GB Vulkan desktop workload.

### WhisperX
https://github.com/m-bain/whisperX

WhisperX combines faster-whisper transcription, word alignment and pyannote-based speaker diarization. Its standard workflow is useful for offline analysis and benchmark labeling. It is not automatically the right always-on streaming choice because the complete pipeline can compete with STAR's local LLM and game for GPU memory.

Hardware decision:
- Do not load another large diarization model onto the same 8 GB GPU by default.
- First measure current VRAM while STAR's Qwen model, Kokoro, VAD, game, OBS and VTube Studio are active.
- Compare CPU diarization, a secondary server, and a smaller streaming model using p95 latency and speaker-attribution accuracy.
- Keep diarization disabled until the user opts in and the device budget is validated.

## VTuber and broadcast adapters

### VTube Studio API
https://github.com/DenchiSoft/VTubeStudio

The official API supports plugin requests for hotkeys, model parameters, tracking inputs and event notifications. A STAR adapter should authenticate using the documented plugin flow, expose a visible connection state, and send rate-limited expression/parameter changes.

### OBS WebSocket
https://github.com/obsproject/obs-websocket

The official protocol requires a Hello/Identify handshake and supports challenge-response authentication when configured. A STAR adapter should use loopback by default, store credentials in the OS credential store, subscribe only to needed events, and avoid exposing the WebSocket password in logs or UI.

Playback synchronization invariant:
- Speech text generation is not evidence that STAR is audible.
- Start mouth movement/captions from the actual playback-start event.
- Stop both when that response generation is cancelled.
- Ignore delayed animation events whose generation ID is stale.

## Gaming and game creation research

### OpenGameEval — Roblox
https://github.com/Roblox/open-game-eval
https://arxiv.org/abs/2610.02563

The benchmark evaluates agents in reproducible Roblox Studio sessions with separate observation and editing tools, executable scene checks and simulated play sessions. Its reported 84-task study found that inspecting relevant objects before editing was associated with higher success.

STAR implication: make inspect-before-edit a required stage, keep read and write tools separate, and require a playtest with state assertions before a task can pass.

### GameDevBench
https://github.com/waynchi/gamedevbench

The 333-task benchmark covers gameplay, UI, 2D graphics, 3D graphics and animation. Its paper reports that visual feedback improved evaluated agent performance.

STAR implication: the Creator Brain needs screenshot/video feedback, not only code review. Compare actual in-engine output against acceptance criteria.

### SIMA 2 and Voyager
https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
https://arxiv.org/abs/2305.16291

These research directions motivate a two-rate Gamer Brain: fast low-level controls and a slower strategic planner, supported by a versioned skill library and held-out transfer tests. A skill is not learned until STAR demonstrates it in a controlled environment.

## Next implementation stages

1. Build a host-owned ingress adapter for audio, chat and game observations.
2. Add a pluggable diarization protocol with ephemeral speaker-ID mapping.
3. Add addressee classification and calibrated confidence before RoomTurnDirector.
4. Add a response executor that drains RoomCueQueue, takes the matching RoomPayload exactly once, revalidates content, and rechecks tool permissions.
5. Add VTube Studio and OBS adapters behind explicit opt-in settings.
6. Drive avatar mouth/expression events from actual speaker playback and response-generation IDs.
7. Build MP-Bench/Duplex-MPE-style held-out room tests.
8. Benchmark mixed load on the actual target machine before enabling local diarization or additional model residency.
9. Build the Gamer Brain and Creator Brain against OpenGameEval and GameDevBench-style executable/visual acceptance tests.

## Acceptance criteria

- Payload count and bytes never exceed configured bounds.
- Expired, deleted, taken and reset payload buffers are overwritten before release.
- A payload can be taken only once.
- Duplicate event IDs are rejected within the configured session window.
- Partial cues and stale/future cues are not stored.
- No payload text appears in metrics or default logs.
- A missing payload causes the host to drop the cue safely.
- Untrusted viewer content cannot grant tool permissions.
- Existing calls remain unchanged unless the host explicitly constructs and uses this store.
- No GPU model, external service, or new package dependency is required by this component.
