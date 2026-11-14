# STAR Run 14 — streaming speech, VTuber platform adapters, and real-time intelligence

**Research date:** 2026-11-13  
**Repository:** oncoursemail/Star-AI-Project  
**Integration branch:** feat/resource-admission-20261113-run21  
**Status:** source-backed engineering decision and implementation handoff. This document does not install models, enable provider credentials, change production defaults, or claim hardware acceptance.

## Executive decision

The highest-value next step is not another general-purpose agent framework. It is to make STAR's existing voice call path genuinely incremental, then connect it to the room director, existing workload admission, existing delivery ledger, and existing Live2D transport.

A fresh source audit found a concrete opportunity:

- STAR's current ASR contract is one-shot: a SpeechToText implementation exposes transcribe(pcm).
- The current FasterWhisperASR transcribes a complete PCM buffer.
- During speech, CallSession may call ASR again on the growing full buffer at the configured partial interval (0.9 seconds by default). The partial path skips if the ASR lock is busy, so it does not intentionally block final transcription, but it repeats work over overlapping audio.
- Final transcription then runs on the completed utterance unless a pause-triggered speculative transcription is accepted.
- The current TTS interface can yield chunks, but the Kokoro implementation creates one sentence waveform at a time. Sentence-level pipelining exists; true within-sentence streaming is not established by this code path.
- The room-only host can accept final classified messages without local ASR, but the repository explicitly leaves ASR, diarization, Twitch/YouTube provider clients, game observation, and provider authentication to trusted adapters.

This makes streaming ASR plus speaker attribution the most actionable new infrastructure target. NVIDIA NeMo-Speech.cpp is now a credible candidate because it offers streaming ASR, diarization, TTS, a local WebSocket server, a stable native SDK, and Windows/CPU/Vulkan/CUDA build paths. It should be evaluated as an optional engine behind STAR's existing interfaces—not adopted as a second voice assistant stack.

## 1. Repository audit: what exists and what is still missing

The following distinctions are important. A host policy, provider contract, or research document is not the same as a working external integration.

### Existing foundations on the development branch

| Area | Existing foundation | Remaining gap |
|---|---|---|
| Voice call | CallSession with VAD, endpointer, ASR, Brain, sentence chunker, TTS, speaker and cancellation | ASR is currently one-shot per buffer; no incremental ASR session contract |
| Natural persona | Three stable voice styles and explicit streaming-naturalness rules | Long-session human evaluation and real viewer rehearsal |
| Multiparty conversation | RoomCue, RoomTurnDirector, bounded queue, payload store, moderation callback and room host | Trusted platform adapters and live diarization/classification |
| Delivery | Existing segmented delivery/playback ledger work in the PR train | Host/provider receipts and real device playback acceptance |
| Avatar | Latest-wins Live2D/VTube Studio frame pump and playback epoch checks | Physical VTube Studio integration and full expression/lip-sync rehearsal |
| Scheduling | #1140 lease-based resource admission and #1142 stream-pressure composition | Trusted host telemetry, calibrated budgets and worker lifecycle integration |
| Evaluation | #1143 paired latency-versus-quality evaluator | Target-machine mixed-load baseline and repeated live rehearsal |
| Gaming | Research and evaluation plans for real-time agents, skill learning and game benchmarks | Game-specific observation/action adapters and verified play sessions |
| Game creation | Roblox inspection-first and Play-session evaluation research | End-to-end Creator pipeline across actual projects and engines |

Do not create a second scheduler, another CallSession, a competing room director, a new playback source of truth, or a second paired evaluator. Compose with the existing authorities.

### Exact code observations

- star/voice/call.py defines SpeechToText with transcribe(pcm, sample_rate), not a per-utterance streaming session.
- star/voice/engines.py implements FasterWhisperASR.transcribe by converting the supplied PCM buffer and invoking the model on that buffer.
- star/voice/call.py periodically calls _start_partial with the detector's accumulated audio. The partial worker calls the same one-shot transcribe method and is guarded by a non-blocking ASR lock.
- The completed turn calls _transcribe again unless the speculative pause transcription is available and accepted.
- star/voice/runtime.py loads VAD, endpointer, ASR and TTS through the existing Engines factory. This is the correct engine-selection seam.
- star/voice/bridge.py owns the desktop call lifecycle and reports missing packages/models. It should remain the only desktop call host.
- star/voice/room_host.py explicitly requires provider adapters to authenticate, moderate, classify and submit already-classified cues. It does not infer speakers or connect to a platform.
- star/voice/room.py uses opaque speaker IDs, source, intent, addressee flag, confidence and monotonic event times. This is a useful normalized boundary for ASR/diarization and chat adapters.

## 2. New high-value research: NVIDIA NeMo-Speech.cpp

Primary source: https://github.com/NVIDIA/NeMo-Speech.cpp

NeMo-Speech.cpp is a native ggml-based speech runtime. Its current repository documents:

- Streaming ASR: Nemotron 3.5 ASR Streaming 0.6B, Nemotron Speech Streaming 0.6B, Parakeet TDT 0.6B v3, and Parakeet CTC 1.1B.
- Speaker diarization: Streaming Sortformer 4-speaker v2 and Nemotron 3 Diarization.
- Speech synthesis: MagpieTTS Multilingual 357M.
- Silero VAD, punctuation, endpointing and text normalization.
- Realtime WebSocket transcription and a local HTTP server.
- A stable C header / native SDK and CMake package.
- CPU, CUDA, Vulkan, Windows, Linux and other build options.

Its README reports the following vendor benchmarks for Nemotron Speech Streaming 0.6B Q8_0 with 160 ms chunks:

| Device | ASR chunk latency | Throughput |
|---|---:|---:|
| GeForce RTX 4090 | 2.3 ms | 67x real time |
| CPU | 27 ms | 6x real time |

For MagpieTTS Multilingual Q8_0 with 186 ms audio chunks, it reports 9 ms first audio and 60x real time on RTX 4090, and 203 ms first audio and 2.7x real time on CPU.

These are NVIDIA's reported measurements on their configurations. They are not STAR results, not RTX 4060 results, and not a promise that the whole speech pipeline will have those latencies. The 4060 has a different memory budget and STAR must share it with the game, OBS, avatar and other foreground work.

### Recommended integration decision

**Evaluate NeMo first as an optional streaming ASR sidecar, not as a replacement for STAR's Brain or complete voice pipeline.**

Phase A: local sidecar

- Pin a tagged NeMo-Speech.cpp release and its checksum; do not track an unpinned nightly in production.
- Install only after an explicit owner opt-in.
- Keep the service bound to 127.0.0.1. The documented default is localhost port 8080; never expose the speech server on a LAN/public interface by default.
- Download model weights separately, verify their published hashes, record exact model and license metadata, and allow offline startup after the first verified download.
- Start and stop the sidecar through the existing host supervisor. Do not let the model process outlive the voice session or keep a hidden GPU allocation.
- Begin with CPU or Vulkan evaluation so the game/OBS GPU budget is not silently consumed. Test CUDA only through the existing resource-admission path.
- Prefer the documented realtime WebSocket client boundary for the first prototype. Consider the stable native C API only if process/serialization overhead is measured to be material.

Phase B: optional streaming ASR adapter

Add a backward-compatible optional interface rather than replacing SpeechToText:

~~~python
class StreamingASRSession(Protocol):
    def feed(self, pcm_16k_mono: bytes) -> None: ...
    def partial(self) -> TranscriptRevision | None: ...
    def finish(self) -> FinalTranscript: ...
    def cancel(self) -> None: ...

class StreamingSpeechToText(Protocol):
    def open_utterance(self, *, utterance_id: str) -> StreamingASRSession: ...
~~~

The names are illustrative. The contract should define bounded PCM input, sample-rate/channel requirements, monotonic timestamps, cumulative versus delta text, revision sequence, confidence, finalization, cancellation and model errors.

- Keep the existing one-shot SpeechToText fallback for current engines and tests.
- Open exactly one ASR session per utterance.
- Batch the existing 32 ms microphone frames into the engine's tested chunk size where appropriate; NeMo's cited benchmark uses 160 ms chunks, but the selected model/API's actual framing contract must decide this.
- Feed each audio sample once. Do not repeatedly resubmit the entire growing buffer to a streaming engine.
- Emit partial transcript revisions as ephemeral UI/room evidence only. Never put partial text into canonical conversation history or durable memory.
- On a revision, invalidate any speculative reasoning tied to the previous revision. Only the final transcript may commit the user turn.
- On barge-in, stop, timeout, device loss or call shutdown, cancel the exact utterance session and release its resource lease only after the sidecar confirms the stream/process is stopped.
- Keep final ASR as the authority for a response. A partial transcript may prepare read-only reasoning, but it must not speak, call tools or change files.

Phase C: diarization adapter

- Run streaming diarization as a separate, lower-priority capability.
- Attach provisional speaker labels to short-lived audio segments; finalize the speaker mapping only when the diarization engine confirms it.
- Map speakers to random, session-scoped IDs, never voiceprints or inferred real identities.
- Preserve overlap timestamps and uncertainty. If attribution is ambiguous, classify the cue as UNKNOWN or WAIT rather than guessing who addressed STAR.
- Diarization must not delay the audio callback, VAD, final transcript, or urgent interruption.
- Measure speaker-switch errors, overlap attribution, latency and false addressee decisions on multi-speaker audio.
- Do not persist raw audio or speaker embeddings by default.

### Why not replace everything with NeMo VoiceChat?

NeMo also documents a full-duplex VoiceChat path. STAR already has a Brain, persona, sentence chunker, TTS, playback clock, room director, cancellation behavior and delivery work. Replacing that with a second end-to-end voice agent would duplicate turn ownership and playback semantics.

Use NeMo's ASR/diarization components first. Evaluate MagpieTTS only as a separate voice-quality and latency candidate. Preserve STAR's existing voice identity unless the owner explicitly chooses a new voice after listening tests.

NVIDIA-authored code is Apache-2.0, but third-party components, model weights and model cards have separate terms. Check every selected model's license and use restrictions before bundling or distributing it.

## 3. Turn-taking research: use local components where local-first matters

Sources:
- LiveKit audio turn detector: https://docs.livekit.io/agents/logic/turns/turn-detector/
- LiveKit adaptive interruption: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/

LiveKit documents an audio turn detector that reads acoustic cues such as intonation, pitch and rhythm rather than relying only on transcript text. Its v1-mini model runs locally on CPU; the full v1 model uses LiveKit Inference. The docs report endpointing defaults of 0.3–2.5 seconds with the audio detector versus 0.5–3.0 seconds for the general default, and support 14 languages.

LiveKit's adaptive interruption model distinguishes intentional barge-in from backchannels such as “uh-huh” and “right.” However, its documented adaptive model uses LiveKit Inference and self-hosted use has a development allowance/usage constraints. Do not silently make it a dependency in STAR's offline/local-first path.

Recommended STAR decision:

- Keep the existing Silero VAD and Smart Turn endpointer as the baseline.
- Add LiveKit v1-mini only as a benchmark candidate if its model license and packaging fit STAR.
- Use adaptive-interruption research as an evaluation pattern, not as a mandatory cloud service.
- Compare false barge-ins, missed barge-ins, backchannel handling, endpoint latency and CPU cost on the same recordings.
- Preserve the existing room director as the final floor authority. An ASR or turn model produces evidence, not permission to speak.

## 4. Platform adapters: make STAR a real streamer without coupling the core to providers

### Twitch EventSub

Sources:
- https://dev.twitch.tv/docs/eventsub/handling-websocket-events
- https://dev.twitch.tv/docs/eventsub/reference/chat

The WebSocket flow begins with a Welcome message; the client must create subscriptions within the documented deadline. Twitch may redeliver notifications, so deduplicate by message ID. For a planned reconnect, connect to the supplied reconnect URL and keep the old connection until the new session welcomes. A disconnected session loses subscriptions, and events missed during an unplanned gap are not replayed.

Adapter requirements:

- Use least-privilege user/chat scopes.
- Subscribe only to the required channel and events.
- Deduplicate by provider message ID and bound the dedupe store.
- Treat a reconnect gap as a gap; do not fabricate missed messages or replay stale chat.
- Rate-limit per channel and opaque speaker ID, run moderation before RoomStreamHost, and make owner stop/revoke immediate.
- Keep chat messages untrusted. A viewer message can never authorize tools, purchases, file access, publishing or arbitrary game input.

### YouTube Live Chat

Source: https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages

Google documents streamList as a server-streaming method for low-latency chat delivery. Live chat is available while the live event is active and no longer available after the event ends.

Adapter requirements:

- Prefer streamList over tight polling when supported by the chosen client.
- Stop cleanly on chat-ended/broadcast-ended events.
- Deduplicate by message ID, while handling message types such as text, Super Chat, membership and tombstone distinctly.
- Enforce quotas, reconnect backoff and explicit OAuth scopes.
- Keep monetary events informational until the owner explicitly enables a separate, bounded response policy. Never purchase or spend on a viewer's behalf.

### VTube Studio

Official docs: https://github.com/DenchiSoft/VTubeStudio/wiki

The existing #1159 frame pump is the correct transport foundation. The adapter should:

- Require the owner to enable Plugin API access and approve STAR's authentication.
- Store the plugin token in the OS credential store.
- Request only the exact parameter/hotkey permissions needed.
- Register and verify custom parameters before reporting ready.
- Use the playback clock for mouth movement, not generated text or model-token timestamps.
- Send emotion/pose transitions through a bounded controller; high-frequency replaceable frames use the existing latest-wins pump.
- Flush the old playback epoch before returning to neutral after interruption.
- Revoke readiness immediately when authentication or permission is lost.

### OBS

Official project: https://github.com/obsproject/obs-websocket

obs-websocket is included by default in OBS 28 and later. Its project strongly recommends password protection. STAR should:

- Use the versioned 5.x protocol and wait for the Identify/Identified handshake before requests.
- Keep the socket on loopback by default; never expose the OBS control port to the public internet.
- Store credentials in the OS credential manager and redact them from logs.
- Begin with read-only status and scene inspection.
- Gate scene switching, source changes, recording and stream start/stop behind explicit owner-configured permissions.
- Monitor OBS render/encoding health and skipped frames as scheduler inputs, not just a dashboard decoration.
- Have a hard stop control that remains usable if STAR's model or UI is unresponsive.

## 5. STAR Gamer: generalize beyond one game without unsafe universal input

Research anchors:
- SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- MineDojo: https://github.com/MineDojo/MineDojo
- Voyager: https://github.com/MineDojo/Voyager
- GameWorld: https://gameworld-bench.github.io/

SIMA 2 is a useful research direction for language-grounded action, long-horizon tasks and transfer to unfamiliar 3D environments. MineDojo offers a broad Minecraft knowledge/task ecosystem. Voyager demonstrates an executable skill library and automatic curriculum for Minecraft. These are research systems, not plug-and-play production game controllers for STAR.

### Recommended per-game adapter contract

Each game adapter should expose:

- game and version identity;
- environment/session identity;
- authorized observation source;
- timestamped state/scene observations;
- action schema and allowed control bounds;
- action deadline and maximum observation age;
- safe stop/reset;
- deterministic or replayable evaluation where possible;
- explicit single-player/private-test/owner-authorized mode.

Every strategic action must reference the observation revision that produced it. Reject stale actions when the world has changed. Keep a bounded reflex controller separate from LLM planning. Do not build a universal unrestricted keyboard/mouse agent.

Initial sequence:

1. Deterministic local mini-games and offline benchmarks.
2. Minecraft private/local worlds with a constrained adapter.
3. Roblox Studio test places and owner-authorized Play sessions.
4. Other games only when a safe, supported adapter exists.

Do not automate competitive multiplayer, bypass anti-cheat, exploit game clients, or violate game/platform terms. Learning and practice should happen in authorized environments.

### Reusable skill record

A promoted skill should include:

- preconditions and supported game/version;
- observation and action schemas;
- strategy/code artifact and dependencies;
- evidence references and known failure modes;
- baseline and candidate versions;
- repeated-seed results;
- held-out map/level results;
- transfer tests;
- rollback pointer.

One successful attempt is not enough. A skill is promoted only after independent checks and held-out evaluation. Model self-grading is not an approval gate.

## 6. STAR Creator and general knowledge

### Creator loop

Reuse one engine-neutral pipeline:

Inspect project → map dependencies → plan bounded edits → create rollback point → implement → static checks → run actual project → capture authorized evidence → evaluate acceptance criteria → repair → repeat.

For Roblox, inspect relevant Instances and scripts before editing, then verify in Studio Play mode. For Godot/Unity, inspect scene trees, resources, scripts, shaders, animations and actual runtime behavior. For Blender, validate geometry, transforms, rigging, materials and import into the target engine.

A successful code compile is not proof of a successful game.

### General-knowledge memory

Separate four kinds of retained information:

- factual cards: claim, source, date, confidence and recheck deadline;
- episodic memory: what STAR observed/did during a specific authorized session;
- procedural skills: how to complete a task, with preconditions and tests;
- project memory: decisions, dependencies, current state and next action.

For every research claim, retain publisher/author, publication date, retrieval date, source URL, license/data-use constraints, confidence and claim-to-source mapping. Mark volatile facts for revalidation. Keep contradictions visible rather than silently blending them.

Memory promotion must preserve the existing owner-governed learning loop: no model self-approval, no editing protected evaluators, and no unverified transcript or game observation becoming permanent knowledge.

## 7. Inference speed: optimize the bottleneck STAR actually has

Sources:
- vLLM Automatic Prefix Caching: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/
- vLLM KV offloading: https://docs.vllm.ai/en/latest/features/kv_offloading_usage/
- OpenTelemetry GenAI metrics: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md

STAR already has stable prompt-prefix layout and llama.cpp prompt-cache support documented in docs/ARCHITECTURE.md. Preserve it.

vLLM Automatic Prefix Caching can skip repeated prefill for shared prefixes, but its documentation explicitly notes it does not reduce decode time. It is a possible Linux-server experiment, not an automatic replacement for the current llama.cpp path.

vLLM's KV offloading can move completed KV blocks to pinned host memory and transfer them back asynchronously, but the documented connector support is CUDA, ROCm and XPU. It adds transfer work and must be benchmarked; do not assume it benefits the Windows/Vulkan desktop path.

### Priority order

1. Remove repeated full-buffer ASR work with an incremental ASR session.
2. Measure endpointing and time-to-first-audible; do not optimize only LLM tokens/second.
3. Preserve stable prompt prefixes and existing cache reuse.
4. Keep small CPU specialists for VAD, turn classification and routing when their accuracy is sufficient.
5. Use the existing paired evaluator (#1143) for speculative decoding, cache precision, offload and concurrency experiments.
6. Run only one low-priority background worker during live mixed-load tests until host telemetry proves more capacity.
7. Keep training, large image/video generation and repository-wide indexing off the live GPU budget by default.

### Required measurements

Use the existing metrics/evaluator and add only missing dimensions:

- ASR audio-chunk processing latency and real-time factor;
- partial transcript age and revision count;
- final ASR latency and word error rate on a consented test set;
- diarization latency, speaker-switch error and overlap attribution;
- end-of-turn delay and false/missed barge-ins;
- LLM time-to-first-token and inter-token latency;
- TTS time-to-first-audio and inter-chunk latency;
- actual first-audible time from playback receipt;
- speech/viseme synchronization error;
- game frame-time p50/p95/p99 and stale-action rejection rate;
- OBS render/encode lag and skipped frames;
- audio underruns, queue depth, CPU/RAM/VRAM and process restarts;
- task success and held-out quality.

Map appropriate measurements to OpenTelemetry's GenAI operation duration, request duration, time-to-first-token, time-per-output-token and token-usage conventions. The conventions are still marked development; pin the convention version. Never attach prompts, transcripts, chat content, viewer IDs, raw audio or screenshots to metric labels or span attributes.

## 8. Acceptance plan

### Gate A — speech adapter offline contract

- Fake streaming engine receives each PCM chunk exactly once.
- Partial revisions are monotonic and bounded.
- Out-of-order, duplicate, stale and post-final revisions are rejected.
- Final text commits exactly once.
- Cancellation invalidates the exact utterance/revision.
- One-shot FasterWhisper fallback remains unchanged.
- No raw transcript enters metrics or logs.

### Gate B — NeMo CPU sidecar

- Pinned Windows build starts on loopback and reports exact version/model/backend.
- Offline smoke test works after model download.
- Sidecar failure falls back to the existing ASR engine without losing the call.
- Clean stop confirms process termination and releases its scheduler lease.
- CPU/RAM usage is measured during simultaneous game and OBS workloads.

### Gate C — RTX 4060/Vulkan/CUDA paired test

- Compare existing FasterWhisper against NeMo with the same consented recordings and exact model/quantization.
- Test CPU, Vulkan and CUDA separately.
- Record WER, partial stability, first partial, final transcript, p95 latency, CPU/RAM/VRAM and game frame time.
- Do not use the 4090 vendor benchmark as the STAR baseline.
- Keep the candidate disabled unless it wins on quality and mixed-load responsiveness.

### Gate D — diarization and Social Director

- Use 2–4 speakers first.
- Include overlapping speech, backchannels, side conversations, game audio, music, accents and noisy microphones.
- Evaluate speaker attribution and addressee classification separately.
- Incorrect or uncertain attribution must not cause an interruption or a reply to the wrong viewer.
- Use the existing RoomTurnDirector and RoomStreamHost.

### Gate E — provider rehearsals

- Fake Twitch provider: duplicate delivery, welcome timeout, planned reconnect, unplanned gap, revocation, rate limit and stop.
- Fake YouTube provider: streamList reconnect, chat-ended event, quota errors and message-type handling.
- VTube Studio: token approval, permission denial/revocation, custom parameter registration, frame coalescing and interruption flush.
- OBS: authenticated handshake, loopback-only default, read-only status, lost connection, password rotation and hard stop.
- Private rehearsal only; public broadcast requires separate owner approval.

### Gate F — 30–120 minute mixed-load stream

Run game + OBS + voice + avatar + chat + one background worker. Compare against the same system with no background worker. Require:

- no audio underruns or stale speech playback;
- no stale game action execution;
- no growing avatar-frame backlog;
- no unbounded queue or process growth;
- no incorrect speaker-triggered interruptions beyond the predeclared test threshold;
- no quality regression outside the paired evaluator's predeclared margin;
- clean recovery from sidecar, provider, OBS and model restarts.

## 9. Implementation sequence

1. Add an optional streaming-ASR protocol while preserving one-shot engines.
2. Build fake-engine contract tests and revision/cancellation tests.
3. Add a pinned NeMo-Speech.cpp CPU sidecar adapter behind an opt-in setting.
4. Run matched audio benchmark and target-hardware tests.
5. Add diarization as a separate optional capability.
6. Feed final, confidence-qualified cues to the existing RoomStreamHost.
7. Integrate Twitch and YouTube provider adapters with explicit OAuth and moderation.
8. Connect the existing VTube Studio frame pump and OBS adapter through owner-approved local permissions.
9. Build one authorized game adapter and a repeated/held-out skill evaluation.
10. Extend the existing Creator and knowledge pipelines with actual execution evidence.

## 10. Source register

1. NVIDIA NeMo-Speech.cpp repository and README: https://github.com/NVIDIA/NeMo-Speech.cpp
2. NeMo-Speech.cpp native SDK: https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/sdk.md
3. NeMo-Speech.cpp Windows/build instructions: https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/build.md
4. LiveKit audio turn detector: https://docs.livekit.io/agents/logic/turns/turn-detector/
5. LiveKit adaptive interruption: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
6. Proact-VL, ICML 2026: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
7. SIMA 2, Google DeepMind: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
8. MineDojo: https://github.com/MineDojo/MineDojo
9. Voyager: https://github.com/MineDojo/Voyager
10. GameWorld: https://gameworld-bench.github.io/
11. OpenGameEval: https://github.com/Roblox/open-game-eval
12. GameDevBench: https://github.com/waynchi/gamedevbench
13. Twitch EventSub WebSocket lifecycle: https://dev.twitch.tv/docs/eventsub/handling-websocket-events
14. Twitch chat subscription: https://dev.twitch.tv/docs/eventsub/reference/chat
15. YouTube LiveChatMessages: https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages
16. VTube Studio official API wiki: https://github.com/DenchiSoft/VTubeStudio/wiki
17. OBS WebSocket: https://github.com/obsproject/obs-websocket
18. vLLM Automatic Prefix Caching: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/
19. vLLM KV offloading: https://docs.vllm.ai/en/latest/features/kv_offloading_usage/
20. OpenTelemetry GenAI metrics: https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md

## Evidence boundary

This is a source-backed research and implementation handoff. It is not a code integration, a model installation, a live provider connection, or a hardware benchmark. NVIDIA performance numbers are vendor-reported on their own configurations. STAR's actual RTX 4060/Windows/OBS/game workload must be measured before any runtime choice or speed claim.
