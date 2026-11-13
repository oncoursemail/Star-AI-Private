# STAR multiparty streaming, embodied gaming, and intelligence research

**Research date:** 2026-11-13  
**Repository baseline:** public `main`, STAR v1.0 source and release documentation  
**Implementation in this branch:** a deterministic, privacy-minimizing room-turn policy core and offline tests  
**Status:** the policy core is not yet connected to a live microphone, chat provider, VTube Studio, OBS, or a stream session.

## Executive findings

The highest-value next step is not another standalone chatbot or another always-running agent. STAR needs a **host-owned, deadline-aware runtime** that coordinates a few specialized loops:

1. A low-latency interaction loop for microphone/chat events, turn-taking, speech playback, avatar state, and emergency stop.
2. A game-control loop that can observe and act at a stable rate without asking a large language model to decide every frame.
3. A strategic loop for planning, research, tool use, and multi-step game objectives.
4. A creator loop for editing, building, playtesting, and repairing games.
5. A learning loop that turns successful, independently checked trajectories into versioned candidate skills.
6. A memory/retrieval loop that supplies relevant, time-aware context without bloating every prompt.

The key design rule is **one trusted host and one resource scheduler, many bounded capabilities**. Independent agents should not each load a model, seize the microphone, control the avatar, or consume the same GPU without coordination.

STAR should feel natural and socially aware as a streamer while remaining transparent that she is an AI. Expressive behavior is a product interaction design goal, not evidence of human consciousness or subjective feelings.

---

## 1. Repository baseline: distinguish source from shipped product

The current README says STAR v1.0.0 is a Windows 11 local-first chat application. It describes a local 4B Vulkan model, an optional owner-operated Linux STAR Server, deterministic model routing, optional Roblox Studio MCP, image generation, web search, and server-side night school. It labels the richer voice experience and Studio Lab as **coming soon** in the release feature table.

The source tree contains a voice-call implementation and tests, but the voice documentation explicitly says real microphones and loudspeakers have not been tested. A source checkout, open PR, passing unit test, or CI artifact is not proof that a feature is in the public installer.

Relevant in-repository references:

- [README and shipping-status table](../../README.md)
- [Voice call architecture and its test limitations](../STAR_VOICE_CALLS.md)
- [Source architecture and prompt-cache layout](../ARCHITECTURE.md)
- [Self-learning loop and owner review gates](../SELF_LEARNING_LOOP.md)
- [Repository working agreement](../../AGENTS.md)

### Current foundations worth preserving

- `star/voice/turn.py`: VAD-driven turn state, end-of-turn model hook, pause/resume and barge-in thresholds.
- `star/voice/call.py`: call-session orchestration, streamed brain output, sentence chunking, TTS, playback and cancellation.
- `star/voice/bridge.py`: bounded desktop actions/events, microphone-consent gate, one active call and one speaking job.
- `star/voice/metrics.py`: per-turn stage timing.
- `star/brain_router.py`: deterministic task routing without spending an extra model call.
- `star/context_layout.py`: stable prompt prefix and append-only history layout to preserve local server prompt-cache reuse.
- `star/inference_benchmark.py`: explicit probes against an already-running local or owner-operated server model.
- `star/specialist_agents.py`: bounded read-only specialists, not unrestricted autonomous workers.
- `star/orchestration.py`: dependency/resource planning, not yet a live process supervisor.
- `star/lessons.py`, `star/learned_week.py`, and the server night-school loop: candidate lessons, paired evidence, expiry/review and undo rather than automatic weight changes.

Do not create a second voice stack, second memory database, second avatar controller, or second scheduler. Integrate through the existing host boundaries.

---

## 2. New implementation in this branch: room turn director

New files:

- `star/voice/room.py`
- `tests/test_voice_room.py`

The new `RoomTurnDirector` is deliberately a **policy-only core**. It accepts already-classified metadata from a future diarization, ASR, chat, or game-event adapter and returns one of:

- `RESPOND`: a new directed turn can be answered.
- `QUEUE`: a directed turn should wait until the current speech finishes.
- `CONTINUE`: the current answer should continue through a backchannel, side conversation, or narration.
- `INTERRUPT`: a high-confidence direct audio barge-in should cancel the exact active response generation.
- `WAIT`: more evidence or a final cue is required.
- `IGNORE`: stale, duplicate, non-directed, or low-priority input should not take the floor.

### Important safety and privacy properties

- The cue contains **no transcript, raw audio, image, or chat-message body**.
- Speaker IDs are opaque, session-scoped labels; this module does not identify a real person.
- Partial cues do not consume the final event ID.
- Final event IDs are deduplicated in a bounded ring (default 512).
- Stale and implausibly future-dated events fail closed.
- NaN, infinity, booleans masquerading as numbers, oversized integers, invalid thresholds, and invalid overlap values are rejected.
- Backchannels and side conversations do not interrupt speech.
- Chat events can queue a response but cannot trigger an audio barge-in.
- Only a high-confidence, sufficiently long **audio** overlap can request interruption.
- An interrupt decision carries the exact active `response_id`, preventing an old cue from cancelling a newer response.
- Game events need an explicit high urgency score; ordinary events do not make STAR narrate every frame.
- Session reset clears ephemeral playback and deduplication state.

This module is not a diarization system, not a semantic classifier, not a queue implementation, and not a device controller. The future host adapter must authenticate sources, produce trustworthy monotonic timestamps, obtain consent, classify cues, apply queue limits, and execute the returned action.

### Why this small policy layer matters

A model should not decide from scratch on every audio frame whether to stop talking. Low-latency floor-control decisions should be deterministic, bounded, and testable. A model can provide semantic classification asynchronously; the host policy then decides whether that classification is sufficient to take the floor.

---

## 3. Research: natural multiparty and full-duplex streaming

### MP-Bench — multiparty conversation is still a hard problem

[MP-Bench, Findings of EMNLP 2026](https://aclanthology.org/2026.findings-emnlp.1437/) evaluates voice agents as active participants in conversations with multiple human speakers. The authors tested 12 voice agents and report multiparty comprehension at or below 22%, with turn-taking near chance for the evaluated real-time agents.

**STAR implication:** ordinary ASR plus a single-user voice-call loop is not enough for a livestream. STAR needs diarization or speaker-turn segmentation, addressee inference, backchannel detection, side-conversation recognition, and an explicit floor-control policy. These components must be measured separately; do not treat a transcript as proof of who was addressed.

### InteractionBench — evaluate more than latency

[InteractionBench (arXiv:2611.02430, 2026-11-02)](https://arxiv.org/abs/2611.02430) evaluates four dimensions on the same recorded user audio: conversational timing, spoken-task accuracy, whisper/volume control, and groundedness in conversations longer than twenty turns. It uses 221 items per system across thirteen scenarios.

The paper reports that the evaluated systems have different trade-offs: good timing does not guarantee spoken-task accuracy, and open full-duplex systems in that study had weaker long-conversation groundedness than the hosted systems. These are results for the paper's protocol and evaluated systems, not universal rankings.

**STAR implication:** build a local regression suite with separate scores for:
- correct floor action (respond, continue, queue, interrupt, ignore);
- whether the requested spoken task was actually completed;
- volume/whisper behavior measured from audio output;
- continuity and factual consistency over 20+ turns;
- first-audible latency and cancellation latency.

### Full-Duplex-Bench v3 — disfluency and chained tool calls

[Full-Duplex-Bench v3 (arXiv:2604.04847)](https://arxiv.org/abs/2604.04847) uses 100 human-recorded requests across 79 scenarios and twelve speakers, including self-corrections and requests requiring chained tool calls. The paper identifies self-correction handling and hard multi-step tool use as persistent failure modes in its evaluated systems.

**STAR implication:** a correction such as “open the settings—actually, the audio settings” must supersede the abandoned phrase. Tool execution should wait until the request is stable enough, and multi-step actions need an explicit plan/result ledger rather than being inferred from one transcript.

### Realtime-Venus — separate live interaction from delegated work

[Realtime-Venus project and technical report](https://realtime-venus.github.io/) (technical report: [arXiv:2609.13814](https://arxiv.org/abs/2609.13814)) presents a full-duplex interaction architecture with asynchronous delegation. Its project page reports its own benchmark results for continuing through backchannels, speech directed at others, and background speech.

**STAR implication:** use two coordinated lanes:
- **live lane:** listen, classify, maintain the floor, speak short responses, synchronize avatar and audio;
- **delegated lane:** research, retrieve, call tools, prepare longer answers, and return a result that the live lane may choose to speak.

Delegation accuracy is not task success. STAR must verify the delegated task result before presenting it as complete.

### Recommended streamer interaction state

Use a small explicit state machine, not a single “listening/speaking” boolean:

- idle / listening;
- partial speech;
- final utterance pending classification;
- addressee uncertain;
- direct request ready;
- backchannel / side conversation;
- assistant speaking;
- queued viewer turn;
- barge-in candidate;
- response cancelled;
- device disconnected / muted;
- recovery / reconnecting.

Every transition should carry a session ID, event ID, monotonic timestamp, and response generation ID. The audio playback clock—not the text-generation callback—must define what the audience actually heard.

---

## 4. Research: VTuber embodiment and broadcast control

### VTube Studio

The [official VTube Studio API repository](https://github.com/DenchiSoft/VTubeStudio) documents a local WebSocket API, plugin authentication, parameter injection, hotkeys, model events, and optional permissions.

Recommended STAR integration:

1. Discover the local VTube Studio instance and show its identity/port.
2. Connect only to loopback by default.
3. Request plugin authentication and wait for the user to approve it in VTube Studio.
4. Store the resulting token in Windows Credential Manager, not source code or logs.
5. Request only the minimum API permissions required.
6. Start with reading API state and model metadata.
7. Add bounded parameter updates and allowlisted hotkeys.
8. Treat disconnect/reconnect and model reload as normal state transitions.

Do not request arbitrary item/image-loading permission for basic facial expression control. Do not send a hotkey every generated token. Use a rate-limited latest-wins expression controller.

### OBS Studio

The [official obs-websocket project](https://github.com/obsproject/obs-websocket) documents the WebSocket API included with OBS Studio 28+. It strongly recommends password protection.

Recommended integration:
- loopback-only by default;
- password held in the OS credential store;
- read-only scene/stream status first;
- explicit allowlist for scene switching, source visibility, and stream start/stop;
- no arbitrary OBS command forwarding from model output;
- clear user approval before starting a public broadcast;
- reconnect without assuming the previous stream state.

### Avatar and audio synchronization

Use one bounded event timeline:

`response_created → sentence_ready → tts_started → audio_enqueued → audio_started → audio_progress → audio_cancelled/audio_finished`

Mouth movement should follow actual output audio progress. Expressions and gestures should be attached to the active response generation. On interruption, cancel audio, queued sentences, captions, and the corresponding gesture together.

A useful expression controller can blend a small set of approved parameters (eyes, brows, mouth, head angle, body sway) with hysteresis and minimum dwell times. This avoids jitter from rapid model mood changes. Keep the user's accepted STAR art direction and asset budget; do not generate a second mascot or replace the approved character design.

### Natural personality without deception

- Maintain a consistent persona, voice, humor style, and conversational history.
- Use curiosity and reactions that are grounded in the current game or conversation.
- Allow silence; do not fill every gap.
- Avoid forced laughter or repeated canned reactions.
- Do not claim human identity, real-world experiences, or subjective feelings as facts.
- Make AI identity clear in channel/about text and when asked.
- Let the user set boundaries for topics, audience interaction, and stream modes.

---

## 5. Research: learning to play games

### SIMA 2

[Google DeepMind's SIMA 2 report](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) and [paper (arXiv:2512.04797)](https://arxiv.org/abs/2512.04797) describe a generalist embodied agent that combines language reasoning, visual observation, and actions in multiple 3D worlds. The report also identifies remaining challenges in very long-horizon tasks, short interaction memory, precise low-level control, and robust visual understanding.

**STAR implication:** separate high-level planning from fast control. Do not call the LLM for every frame. The strategic brain should produce a short-horizon intent (e.g. reach the doorway, gather wood, avoid the enemy); a deterministic or learned controller should execute and monitor low-level movement; the observer should verify whether the world changed as expected.

### Voyager — executable skills and automatic curriculum

[Voyager (NeurIPS 2023)](https://arxiv.org/abs/2305.16291) introduced an automatic curriculum, an expandable executable skill library, and iterative improvement using environment feedback and execution errors. It demonstrated reuse of learned skills in a new Minecraft world.

**STAR implication:** store versioned, testable skills rather than vague memories:
- preconditions and supported game/version;
- action sequence or controller;
- expected observation/result;
- timeout and stop conditions;
- failure cases;
- practice score and held-out transfer score;
- provenance and version;
- owner approval status where needed.

A skill is not “learned” because STAR described it correctly. It is learned only after repeatable execution and held-out validation.

### Practical gamer architecture

1. **Perception:** game state API when available; otherwise screenshots/video and UI/object detection.
2. **State estimator:** position, camera, inventory, health, objective, nearby threats, UI state, confidence.
3. **Strategic planner:** objective decomposition, route/resource plan, team intent.
4. **Reactive controller:** movement, aiming, camera, timing, interaction.
5. **Safety/action gate:** allowlisted inputs, focus checks, stop key, rate limits, no hidden process injection or anti-cheat bypass.
6. **Outcome verifier:** confirm inventory/objective/world-state change.
7. **Replay learner:** compare planned and actual trajectory, identify the failure cause, propose a skill revision.

Practice first in local/private worlds or explicitly permitted environments. Respect game rules and platform terms; do not build cheating, anti-cheat evasion, botting for rewards, or unauthorized player-data collection.

---

## 6. Research: making and finishing complete games

### OpenGameEval — inspect before editing

[Roblox's OpenGameEval repository](https://github.com/Roblox/open-game-eval) and [paper (arXiv:2610.02563)](https://arxiv.org/abs/2610.02563) evaluate agents in reproducible Roblox Studio sessions. The framework separates observation from editing and checks both scene changes and simulated play. It reports 84 curated core tasks and finds that inspecting relevant objects before editing correlates with better success.

**STAR implication:** enforce read/inspect-before-write. The creator should inspect the DataModel, scripts, assets, references and project conventions before changing anything. A successful code edit is not a successful Studio task.

### CEGame-Bench — completion is the real acceptance test

[CEGame-Bench (arXiv:2610.26098, 2026-10-19)](https://arxiv.org/abs/2610.26098) evaluates long-horizon game creation across Defold, Godot, Roblox Studio, Unity and Unreal. Its paper reports that the evaluated agents reached the game's ending in only 16% of runs, despite completing many integration steps.

**STAR implication:** define game completion as a player-visible contract:
- project opens and builds;
- required scenes and systems exist;
- player can start;
- controls work;
- required objectives can be completed;
- fail/win states work;
- save/load restores expected state;
- a clean restart does not depend on editor-only state;
- regression suite passes.

### Creator pipeline

`spec → inspect → plan → edit → static checks → build → launch → play → observe → repair → save/reload → regression`

Use engine-native APIs and tools: Roblox Studio MCP for Roblox, Blender Python for asset workflows, and the official editor/CLI/testing interface for Godot, Unity, and Unreal. Keep each engine adapter explicit; do not assume the same automation contract works in all engines.

For generated assets, preserve editable source files and provenance. Do not flatten UI that should remain native, and do not silently replace approved reference assets.

---

## 7. Research: faster local and server inference

### Preserve the current two-tier architecture

The public README describes a small local Vulkan model and an optional owner-operated Linux CPU server. This is a useful division:
- local fast model for short responses, classification, UI help and quick tool selection;
- server model for deeper reasoning, code generation, research synthesis and long-running delegated tasks;
- hosted models only when explicitly configured by the owner.

Do not route to a hosted model automatically when local inference fails.

### llama.cpp

The [official llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) lists parallel decoding, continuous batching, multimodal routes, monitoring, schema-constrained output, function calling, and speculative decoding. [SPEED-Bench](https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench) is designed to compare speculative-decoding methods using throughput, latency and draft acceptance.

Test one variable at a time:
- server slot count / concurrency;
- context length and KV-cache type;
- prompt-cache hit rate;
- batch and ubatch sizes;
- CPU threads and batch threads;
- GPU layer split;
- quantization;
- speculative decoding method and draft length.

Do not maximize concurrency blindly. More slots can reduce per-request memory, increase contention, or worsen first-token latency on a small GPU. Benchmark the actual mixed workload.

### Prefix caching is not decode acceleration

STAR's stable system prefix and append-only context layout are valuable because they reduce repeated prompt-prefill work. They do not make autoregressive token decoding faster. Track cache reuse separately from generation throughput.

### Speculative decoding and MTP are model/backend-specific

[llama.cpp speculative decoding documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) and [vLLM MTP documentation](https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp/) describe multiple approaches. Native MTP is only applicable when the target checkpoint and serving backend expose a compatible implementation. A method that helps a high-concurrency CUDA server may be slower or unavailable on the local Vulkan build.

Do not change STAR's default backend or download a second model on the strength of a paper or vendor benchmark. Run a paired experiment with:
- exact model file and SHA-256;
- quantization and context length;
- backend/runtime commit and GPU driver;
- warm/cold state;
- same prompts and output limits;
- serial and realistic concurrent load;
- first-content p50/p95, time-per-output-token, total latency, throughput, peak RAM/VRAM, quality and failure rate.

### Resource telemetry on Windows

The [windows_exporter GPU collector](https://github.com/prometheus-community/windows_exporter/blob/main/docs/collector.gpu.md) uses Perflib and D3DKMT and exposes adapter-level and per-process GPU memory/engine metrics on supported Windows systems.

This is a useful reference for STAR's Windows GPU provider. It is not evidence that a provider is already implemented in STAR. Keep missing readings as unknown, distinguish dedicated/local from non-local GPU memory, and bind samples to process identity plus process start time to avoid PID reuse.

---

## 8. General knowledge and long-term learning

General knowledge should not be one giant unfiltered vector store. Separate:
- stable semantic knowledge;
- time-sensitive facts with publication/observation dates;
- project-specific facts;
- episodic experience;
- executable procedures/skills;
- social context and user preferences.

Every retrieved fact should carry provenance, source quality, timestamp, scope, and a confidence/uncertainty note. Conflicting sources should be shown as conflicting, not averaged into a false fact. Expire or revalidate time-sensitive information.

For a research task, use a repeatable pipeline:

`question → scope → source search → primary-source retrieval → claim extraction → corroboration/conflict check → synthesis → citations → freshness label`

For learning from experience:

`practice → observe result → compare against expected state → diagnose failure → propose skill/lesson → run held-out tests → paired gate → review/promotion`

Keep the existing rule that STAR cannot edit its own graders, holdout sets, policy gates, or permission code. A model's self-rating is not independent evidence.

---

## 9. Unified runtime and resource priorities

### Deadline classes

| Lane | Examples | Scheduling rule |
|---|---|---|
| Critical realtime | audio capture, playback stop, mute, avatar sync, game emergency stop | bounded queues, highest priority, no waiting on research |
| Interactive | ASR, turn classification, short response, game observation | strict deadlines, cancellation, small models where possible |
| Strategic | planning, code reasoning, multi-step tool calls | admitted only with CPU/RAM/VRAM budget |
| Background | research, asset generation, practice, memory consolidation | pause or yield when stream/game load rises |

Each task should carry:
- session and task IDs;
- priority/deadline;
- cancellation token;
- resource lease;
- model/config fingerprint;
- bounded input/output size;
- explicit terminal state;
- evidence/result reference.

A lease must not be released just because a worker was asked to stop. The host should confirm process exit before reclaiming its resources.

### Recommended scheduler protections

- reserve CPU capacity for audio and UI;
- reserve RAM for model, audio buffers and the game;
- reserve GPU memory for the game/OBS/avatar before admitting image or model work;
- cap background concurrency;
- cancel stale work on turn/session changes;
- use latest-wins coalescing for high-frequency avatar/game telemetry;
- use bounded queues with explicit drop/coalesce policy;
- shed optional research and image-generation work before degrading the live stream;
- never treat unknown VRAM as zero;
- measure p95/p99 under mixed load, not only isolated model benchmarks.

---

## 10. Evaluation plan: prove capability, not appearance

| Domain | Core measures | Holdout requirement |
|---|---|---|
| Multiparty voice | addressee accuracy, turn-action accuracy, false barge-in, missed barge-in, interruption stop latency | unseen speakers, overlapping speech, noisy rooms |
| Voice delivery | first audible p50/p95, TTS underruns, word/phrase completion, volume and whisper accuracy | unseen scripts and voices |
| Memory | grounded recall, stale-fact rejection, contradiction handling, 20+ turn consistency | conversations excluded from tuning |
| General knowledge | factual accuracy, citation precision, source freshness, calibrated abstention | questions with conflicting and outdated sources |
| Gaming | objective completion, action error, death/failure rate, time-to-goal, skill transfer | unseen maps, seeds and game versions |
| Game creation | build/start, gameplay objective completion, ending reached, save/reload, regression | new design documents and clean workspaces |
| Performance | TTFT/first content, TPOT, p50/p95/p99, tokens/s, CPU/RAM/VRAM, game frame-time p99, audio dropouts | repeated paired runs under mixed stream/game/inference load |

Use paired baselines, fixed seeds where possible, sealed holdouts, confidence intervals, and exact model/config fingerprints. Report failed and incomplete trials. A single impressive demo is not evidence of general competence.

### First acceptance targets to establish

Do not invent universal numeric targets before collecting a reliable baseline. First record:
- 30–50 repeated voice trials per scenario class;
- at least three concurrency settings for inference;
- at least three representative games and a held-out map/seed;
- one full game-creation task with launch, win, save, reload and regression;
- a mixed workload with stream + game + voice + background task.

Then set improvement thresholds from measured variance and the owner's latency/quality requirements.

---

## 11. Phased implementation roadmap

### Phase A — finish the policy foundation
- Review and merge this room policy only after CI and independent code review.
- Add a typed event adapter contract to the desktop host.
- Keep the current one-to-one call path unchanged until a real multiparty source exists.
- Add deterministic replay fixtures for each room decision.

### Phase B — local integrations
- Implement an opt-in VTube Studio adapter with user-approved plugin authentication and Credential Manager storage.
- Implement an opt-in OBS adapter with authenticated loopback WebSocket and an action allowlist.
- Drive mouth/gesture state from actual audio playback events.
- Test reconnect, mute, device loss, model reload, and stream stop.

### Phase C — social and gaming perception
- Add a diarization-capable audio path and chat adapter behind explicit opt-in.
- Keep pseudonymous speaker labels per session.
- Add a game-event observer with rate limits and urgency classification.
- Connect Social Director decisions to bounded response queues and the existing voice playback cancellation path.

### Phase D — embodied game learning
- Add an observation/action interface per supported game.
- Begin in private/local sandbox environments.
- Build an executable skill registry with provenance and held-out tests.
- Add replay capture and trajectory diagnosis without storing public player data.

### Phase E — creator and general intelligence
- Add OpenGameEval-compatible Roblox task fixtures where licensing and setup permit.
- Add long-horizon game-completion contracts for the supported engines.
- Improve retrieval freshness, source provenance, memory conflict handling and memory-to-action evaluation.
- Promote only measured improvements through the existing paired gate.

---

## 12. Research references

### Realtime voice and interaction
- [MP-Bench — Findings of EMNLP 2026](https://aclanthology.org/2026.findings-emnlp.1437/)
- [InteractionBench — arXiv:2611.02430 (2026-11-02)](https://arxiv.org/abs/2611.02430)
- [Full-Duplex-Bench v3 — arXiv:2604.04847](https://arxiv.org/abs/2604.04847)
- [Realtime-Venus project](https://realtime-venus.github.io/)
- [Realtime-Venus technical report — arXiv:2609.13814](https://arxiv.org/abs/2609.13814)

### Avatar and broadcast interfaces
- [Official VTube Studio API](https://github.com/DenchiSoft/VTubeStudio)
- [Official OBS WebSocket project](https://github.com/obsproject/obs-websocket)

### Game playing and learning
- [Google DeepMind SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/)
- [SIMA 2 paper — arXiv:2512.04797](https://arxiv.org/abs/2512.04797)
- [Voyager — arXiv:2305.16291](https://arxiv.org/abs/2305.16291)
- [Voyager project](https://voyager.minedojo.org/)

### Game creation
- [Roblox OpenGameEval repository](https://github.com/Roblox/open-game-eval)
- [OpenGameEval paper — arXiv:2610.02563](https://arxiv.org/abs/2610.02563)
- [CEGame-Bench — arXiv:2610.26098](https://arxiv.org/abs/2610.26098)

### Inference and hardware
- [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md)
- [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench)
- [vLLM MTP documentation](https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp/)
- [Windows Exporter GPU collector](https://github.com/prometheus-community/windows_exporter/blob/main/docs/collector.gpu.md)

---

## Honest implementation status

Implemented in this branch:
- deterministic room cue/decision types;
- bounded event deduplication;
- stale/future event rejection;
- confidence and urgency thresholds;
- non-interrupting backchannel/side-conversation handling;
- queued chat and game events;
- high-confidence audio interruption bound to an exact response ID;
- bounded configuration and numeric validation;
- 25 offline tests in the isolated local check.

Not implemented or tested in this branch:
- speaker diarization or speaker identity;
- ASR/chat/game adapters;
- real multiparty session lifecycle;
- response queue execution;
- integration with `VoiceBridge` or `CallSession`;
- VTube Studio or OBS connections;
- microphone, speakers, GPU, game, or livestream hardware testing;
- any model-weight training or measured intelligence/speedup claim.

This distinction is intentional: the PR adds a testable decision core and research plan, not a claim that STAR is already a human-like autonomous VTuber.
