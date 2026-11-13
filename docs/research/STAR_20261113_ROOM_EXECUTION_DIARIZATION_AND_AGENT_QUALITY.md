# STAR room execution, streaming diarization, and agent quality research

**Research date:** 2026-11-13  
**Implementation branch:** `feat/room-response-dispatch-20261113-run18`  
**Baseline:** the existing STAR v1.0 voice call, room director, metadata-only queue, and ephemeral payload store  
**Scope:** research plus an opt-in room-message execution bridge; no production defaults or release behavior changed

## Executive findings

The next useful step after a room-turn policy, bounded queue, and ephemeral payload store is to make the queued request executable through the existing call pipeline. A queue that can retain a question but cannot deliver it is only partial infrastructure.

This branch adds that missing host API while preserving a strict separation:

1. **Room policy:** decides whether a cue should be answered, queued, ignored, continued, or interrupted.
2. **Metadata queue:** stores only the classified cue and bounded priority/expiry metadata.
3. **Ephemeral payload store:** stores the short-lived transcript/chat/game text separately.
4. **Call executor:** consumes one exact cue/payload pair and sends it through STAR's existing streamed voice path.
5. **Host adapters:** remain responsible for microphone/chat/game ingestion, diarization, classification, moderation, and external provider connections.

The new API does not grant the model tools or permissions. Room text is passed as untrusted user content to the voice Brain only.

A queue-lifetime audit found that an eight-second default would expire ordinary viewer questions while STAR was still speaking a longer answer. The default room policy and payload event-age limit are now 60 seconds, with a 45-second maximum queue residence time. The queue and payload byte/item limits remain bounded, and hosts can choose shorter TTLs for latency-sensitive game events. Tests explicitly verify that a queued question survives a 20-second spoken response and that short custom TTLs still expire correctly.

## 1. New research: streaming speaker diarization

### Nemotron 3 Diarization

The November 9, 2026 paper, [Nemotron 3 Diarization](https://arxiv.org/abs/2611.12246), describes a streaming Sortformer architecture supporting up to eight speakers. It maps coarse 80 ms encoder representations to 10 ms frame-level predictions and adds activity and phantom-speaker losses. The paper reports up to 6.4x inference throughput, 2.8x lower training memory, and 2.2x faster training than its stated predecessor/training setup.

Those are paper-reported results, not STAR measurements. The paper's throughput result is not evidence that the model will run in real time on STAR's 8 GB RTX 4060 while a game, local LLM, TTS, OBS, and avatar are active.

NVIDIA's [NeMo Labs streaming diarization documentation](https://docs.nvidia.com/nemo/labs-voice-agent/about/core-concepts/speech-pipeline/speaker-diarization/) provides useful deployment caveats:

- The shipped Nemotron 3 diarization configuration supports eight speakers.
- Speaker labels are session-local and reset with the diarization service.
- Chunked look-ahead can add up to roughly 320 ms before inference time.
- Similar voices, noisy rooms, and inference that falls behind real time can cause missing or incorrect speaker tags.
- The diarization stage provides speaker evidence; it does not itself produce the transcript.

The current NeMo Labs integration notes also expose two important constraints:

- The shipped Nemotron 3 model requires a pinned NeMo Speech repository revision; the documented PyPI NeMo 2.7.3 and 3.0.0 releases do not load this checkpoint correctly. It should be evaluated in an isolated environment, not added to STAR's normal desktop dependencies.
- The service emits at most one speaker tag per transcript. Overlapping speakers inside one transcript collapse to a single tag, so a host that needs true overlap attribution must preserve frame/segment evidence separately rather than assuming the transcript tag describes every word.

The documented chunked configuration uses three 80 ms frames plus one 80 ms look-ahead frame, so its first diarization burst arrives after about 320 ms of audio, plus model inference. The NeMo documentation also says the service runs roughly one second of silence through the model at startup; this adds several seconds to startup, while skipping warm-up can make the first CUDA forward pass take 2–4 seconds and arrive too late for the first turn. That delay and model warm-up need to be included in first-audible latency tests.

**STAR decision:** define a future host adapter around speaker evidence and confidence rather than binding the call core to one model. Keep speaker IDs ephemeral, never treat a diarization label as a verified real-world identity, and let the host disable diarization when its latency or quality is poor.

### Third-party interruptions

[Still Between Us?](https://tpi-va.github.io/) introduces TPI-Train and TPI-Bench for distinguishing a primary speaker's speech from third-party interruptions. The paper describes 88K training instances and 26 realistic scenarios, with speaker-aware hard negatives intended to reduce semantic shortcut learning.

**STAR decision:** interruption policy must use acoustic speaker evidence and addressee evidence, not merely keywords such as "Star" or the semantic content of a sentence. A person saying "stop" to another viewer should not automatically cancel STAR's current speech.

### Content-aware correction is not the same as turn-taking

The EMNLP 2026 [Model Interruption Bench](https://aclanthology.org/2026.emnlp-main.2349/) reports a detection-to-interruption gap. In its evaluated task, the strongest systems detected 59–67% of errors in turn-based conditions but achieved below 10% mid-speech true-positive interruption when required to interrupt at the right time.

**STAR decision:** separate three stages:

- Detect a possible correction or mistake.
- Decide whether it is important enough to interrupt.
- Act only when confidence, timing, and conversational context justify it.

A detected disagreement is not automatically an interruption. Prefer a short pause, queued correction, or response at the next turn when immediate interruption is not clearly warranted.

### Full-duplex evaluation

[Full-Duplex-Bench v3](https://www.full-duplex.ai/benchmarks/fdb-v3) evaluates 100 human-recorded spoken requests across 79 scenarios and 12 speakers, including disfluencies, self-corrections, chained tool calls, latency, and turn-taking. Its May 2026 benchmark page reports that the evaluated systems still struggled with self-correction and multi-step reasoning on harder scenarios; the reported fastest response was 4.25 seconds and is benchmark-specific, not a STAR target or a directly comparable local latency result.

**STAR decision:** evaluate turn-taking, spoken-task accuracy, self-correction, tool-result grounding, and latency together. Do not optimize only for fewer interruptions or faster first audio.

## 2. New implementation: room payload to spoken response

The current call path already owns the Brain stream, sentence chunker, TTS, speaker, cancellation, and heard-audio history. Rebuilding those stages for livestream chat would create a second voice stack.

This branch adds an optional `RoomPayloadStore` dependency to `CallSession` and exposes two host methods.

### `handle_room_message(cue, text)`

- Accepts only final, already-classified text.
- Stores it using the bounded, TTL-limited payload store.
- Runs the existing `RoomTurnDirector` policy.
- Starts a direct response when idle.
- Preserves the payload when the policy queues the cue.
- Falls back to the queue if another reply starts during response reservation.
- Deletes payloads for ignored, rejected, stale, or non-queueable cues.
- Emits content-free decision/receipt events.

### `dispatch_next_room_message()`

- Reconciles expired queue entries and expired payloads.
- Refuses to start a second response while a reply is active.
- Pops the highest-priority cue.
- Destructively takes the matching payload.
- Requires full cue equality before dispatch.
- Drops missing or mismatched payloads instead of attaching content to the wrong event.
- Returns a typed result: `DISPATCHED`, `BUSY`, `EMPTY`, `STOPPED`, `MISSING_PAYLOAD`, or `CUE_MISMATCH`.

When a reply finishes and queued items remain, `CallSession` emits `room_queue_ready`. The host can use that event to call the dispatcher. The call core does not start an uncontrolled background polling loop.

### Untrusted-content boundary

Transcript, viewer chat, and game-observation text is wrapped as untrusted user content. It cannot grant tool authorization, change permissions, publish a game, purchase items, or authorize external actions. The voice Brain protocol returns streamed text and has no tool executor.

The host must still implement source consent, moderation, rate limiting, speaker/addressee classification, and any separate authorization needed for external actions.

## 3. Human-feeling streaming: measure the whole interaction

A natural stream depends on more than TTS voice quality. STAR needs a coherent timeline across:

- VAD and end-of-turn detection;
- ASR finalization;
- speaker diarization;
- addressee/intent classification;
- queue wait and priority aging;
- model queue wait, prefill, and decode;
- first speakable sentence;
- TTS first chunk;
- actual audio-device playback;
- avatar parameter/hotkey delivery;
- OBS render/output state.

Record p50, p95, and p99 latency for each stage, plus false barge-in rate, missed direct-address rate, queue expiry rate, audio underruns, avatar lag, OBS skipped frames, and game frame-time p10.

The first audible sample is the user-visible latency boundary. Model first-token time is diagnostic, not a substitute for first-audible time.

### Playback-authoritative avatar synchronization

The avatar must follow audio actually played, not text merely generated. On cancellation:

- stop the matching response generation;
- drop its unplayed TTS chunks;
- truncate or mark the unheard response in conversation history;
- cancel captions/gestures for that generation;
- ignore stale completion callbacks;
- transition to listening or the next queued response.

This preserves synchronization when a viewer interrupts STAR or a game event takes priority.

## 4. Faster inference without sacrificing the stream

The [llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) documents parallel decoding, continuous batching, monitoring endpoints, schema-constrained responses, function calling, and speculative decoding. Its [speculative decoding guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) describes draft-model and n-gram-cache approaches.

The upstream [llama.cpp SPEED-Bench client](https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench) can compare a running server with identical prompt sets before and after a speculative-decoding change. It reports prompt throughput, decode throughput, end-to-end latency, and draft acceptance. Its qualitative categories include coding, humanities, math, multilingual, QA, RAG, reasoning, roleplay, STEM, summarization, and writing. Keep benchmark, category, output length, concurrency, and sample limit identical between baseline and candidate runs; otherwise the comparison is not controlled.

For STAR, evaluate optimizations in this order:

1. Preserve stable system/prefix bytes so the server can reuse prompt-cache work.
2. Avoid loading/unloading the interactive model between adjacent turns.
3. Measure server queue wait separately from prefill and decode.
4. Use small, bounded contexts for the live voice brain; retrieve long project context only when needed.
5. Compare continuous batching and slot allocation under realistic simultaneous voice/game workloads.
6. Test speculative decoding only with a compatible target/backend and paired quality holdouts.
7. Test KV-cache quantization/offload in an isolated build, checking long-context recall and tool accuracy as well as VRAM.
8. Reserve CPU/GPU capacity for audio, game control, avatar, and OBS before admitting research or asset-generation jobs.

A speed change is accepted only when it improves first-audible latency or sustained throughput without worsening held-out answer quality, false interruptions, audio underruns, or game frame-time.

## 5. STAR Gamer: separate control from planning

Use a two-rate design:

- **Fast control loop:** bounded, deterministic movement/camera/action execution and immediate safety stop.
- **Strategic loop:** objective decomposition, map reasoning, resource planning, and explanation to viewers.

The fast loop should not wait for a large language model on every frame. The strategic loop should not send raw keyboard/mouse actions without validating the current game, target window, and action policy.

Learned skills should be versioned executable procedures with preconditions, expected effects, timeout, recovery, and postcondition checks. Promote a skill only after repeated success on held-out maps/seeds and record failures as evidence, not as a successful lesson.

## 6. STAR Creator: define "finished game" by play, not compilation

[OpenGameEval](https://github.com/Roblox/open-game-eval) provides reproducible Roblox Studio tasks with executable checks in edit and play sessions. Its original public release described 47 tasks; the later benchmark paper/repository reports 84 curated core tasks. These counts refer to different releases, not a single fixed dataset.

[CEGame-Bench](https://arxiv.org/abs/2610.26098) evaluates complete-game creation across Defold, Godot, Roblox Studio, Unity, and Unreal Engine. Its reported runs reached the game ending in only 16% of cases; its Game Completion Boost skill improved execution-based scores by 14.1–24.3 points for three evaluated models.

**STAR decision:** use a completion gate:

`requirements → inspect project → build → launch → real input → objective path → ending → save → reopen → verify → repair → replay`

A script compiling, a scene rendering, or a screenshot looking plausible is not proof that a game is complete.

## 7. General knowledge and memory

General knowledge should use the same evidence discipline as code and gameplay:

- Store source, publication/retrieval time, and scope with each fact.
- Distinguish verified facts, observed state, inference, and hypotheses.
- Detect contradictions and prefer newer authoritative evidence for time-sensitive facts.
- Keep project memory, episodic experience, semantic facts, and executable skills separate.
- Do not promote arbitrary web/chat/game text into system instructions or permissions.
- Test memory-to-action: did STAR use the right remembered procedure and produce the right outcome, not merely repeat a stored fact?

## 8. Acceptance matrix

| Area | Offline acceptance | Hardware/host acceptance |
|---|---|---|
| Room dispatch | Immediate response, queue, expiry, mismatch, cancellation, no overlap | Real chat/audio source and host callback |
| Diarization | Recorded multi-speaker clips, speaker swaps, third-party interruption holdouts | Real microphone, room noise, CPU/GPU contention |
| Turn-taking | Backchannels, direct address, corrections, false interruptions | Live multi-person conversation |
| Avatar | Generation/epoch cancellation and latest-wins frame tests | VTube Studio model and actual playback sync |
| OBS | Parser, epoch and reconnect tests | OBS stream rehearsal and dropped/skipped-frame checks |
| Inference | Paired prompt/model/scheduler holdouts | RTX 4060 mixed game/voice/OBS load |
| Gamer | Deterministic tasks, skill pre/postconditions, held-out seeds | Actual game control and frame-time |
| Creator | Edit/play tests, objective journey, ending, save/reopen | Roblox Studio/engine acceptance |
| Memory | Provenance, expiry, contradiction, injection tests | Longitudinal cross-session evaluation |

## 9. Phased implementation roadmap

1. **Complete room execution:** finish CI for this branch and connect a host adapter that can supply final cues.
2. **Audio ingress:** add streaming diarization/ASR adapter contracts with explicit timestamps, confidence, speaker-session scope, and backpressure.
3. **Social Director:** combine speaker evidence, addressee classification, intent, and the room policy; calibrate on held-out TPI/multiparty sessions.
4. **Broadcast host:** connect VTube Studio and OBS through authenticated, opt-in adapters and one playback-generation timeline.
5. **Mixed-load scheduler:** use trusted host telemetry and the existing workload admission system to protect realtime audio/game-control lanes.
6. **Gamer and Creator:** expand verified skill libraries and real-input completion gates.
7. **Knowledge/memory:** strengthen evidence provenance and memory-to-action evaluation.
8. **Self-improvement:** compare candidate changes on paired holdouts, promote only after quality and stability gates, and retain rollback artifacts.

## References

- Nemotron 3 Diarization (2026-11-09): https://arxiv.org/abs/2611.12246
- NeMo Labs streaming speaker diarization: https://docs.nvidia.com/nemo/labs-voice-agent/about/core-concepts/speech-pipeline/speaker-diarization/
- TPI-Bench / Still Between Us? (ACL 2026): https://tpi-va.github.io/
- Model Interruption Bench (EMNLP 2026): https://aclanthology.org/2026.emnlp-main.2349/
- Full-Duplex-Bench v3: https://www.full-duplex.ai/benchmarks/fdb-v3
- llama.cpp server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- OpenGameEval: https://github.com/Roblox/open-game-eval
- CEGame-Bench (2026-10-19): https://arxiv.org/abs/2610.26098
- Voyager: https://github.com/MineDojo/Voyager


## 10. Broader capability expansion map

These are candidate systems, not claims that the current branch already implements them. Each should be an independently testable adapter or skill family that shares the session/runtime contracts above.

### Live creator and community features

| Feature | What STAR should do | Required guard/evaluation |
|---|---|---|
| Stream co-host | Track the current segment, topic, game objective, and unanswered questions | Session-state replay and stale-event tests |
| Live Q&A | Group duplicate questions, prioritize direct questions, answer after the current sentence | Queue fairness, duplicate rate, answer latency |
| Captions | Emit aligned captions from the audio actually played | Word/audio alignment and cancellation tests |
| Multilingual chat | Detect language, translate for comprehension, answer in configured language | Human-reviewed translation holdouts |
| Community events | Run polls, trivia, viewer challenges, and opt-in minigames | Explicit host approval for scene or platform writes |
| Highlight assistant | Mark exciting moments and prepare clip candidates | Never publish automatically; require owner review |
| Stream recap | Summarize segments, answered/unanswered questions, and game progress | Source-linked recap and no invented viewer quotes |
| Soundboard | Trigger approved sounds in response to game/social events | Curated asset allowlist, cooldowns, volume cap |
| Stream scene director | Recommend scene/overlay changes based on the current activity | Suggest first; actual OBS writes require a host policy |
| Accessibility | Live captions, adjustable speech rate, volume normalization, and optional translation | Latency, intelligibility, and user preference tests |

### General-purpose gamer features

| Feature | What STAR should do | Required guard/evaluation |
|---|---|---|
| Game adapter registry | Identify a supported game and load its observation/action adapter | Explicit process/window allowlist |
| Screen understanding | Track HUD, objectives, map, inventory, and visible events | Ground each claim in current frame/state |
| Game-state memory | Keep a compact map of discovered locations, objectives, and resources | Session scope, expiry, correction path |
| Practice coach | Generate small drills for aiming, movement, timing, and mechanics | Repeatable score and held-out seeds |
| Strategy comparison | Replay candidate routes/builds and compare objective completion | Same seed/settings and logged baseline |
| Team coordination | Communicate roles, cooldowns, and shared objectives | No unsolicited external messages |
| Game safety | Detect menus, purchases, account prompts, and irreversible actions | Pause and require owner approval |
| Cross-game transfer | Reuse abstract skills such as navigation, inventory planning, and timing | Evaluate on unseen games/maps; do not assume transfer |
| Spectator learning | Observe expert play and extract candidate skills | Human review and replay before promotion |
| Accessibility co-pilot | Explain controls, objectives, and options while playing | Don't obscure or override the player's input |

### Creator and production features

- **Project memory:** retain design decisions, assets, TODOs, and verified build steps per game.
- **Visual QA:** compare screenshots and live scene captures against authored reference layouts, spacing, readability, and style constraints.
- **Asset pipeline:** track source, license, resolution, texture format, rig, animation clips, and import settings.
- **Blender integration:** create/edit scenes and assets through bounded scripts, then render preview frames for inspection.
- **Audio pipeline:** generate or select sound effects/music, normalize levels, and validate loop points and licensing.
- **Game QA:** test input, respawn, save/load, networking, UI scaling, objective paths, endings, and performance on a fixed test matrix.
- **Release candidate:** produce a reproducible build manifest and test report; publication remains a separate owner-approved action.

### Knowledge and research features

- **Research dossiers:** every important claim carries a source, date, scope, and confidence.
- **Contradiction workbench:** show conflicting claims side by side and explain which source is more authoritative or recent.
- **Knowledge freshness:** expire or recheck prices, APIs, game patches, security guidance, and other time-sensitive facts.
- **Learning curriculum:** choose the next topic based on a demonstrated gap, then test with unseen questions or practical tasks.
- **Teach-back mode:** explain a topic, ask a short check question, and update the lesson only from verified performance.
- **Personal project search:** retrieve prior decisions and files with citations, while keeping private project data local.
- **General problem solving:** plan, use approved tools, inspect results, and verify the outcome rather than stopping after a plausible answer.

### Autonomy and reliability features

- **Goal/commitment ledger:** record task owner, success condition, deadline, dependencies, and next action.
- **Service supervisor:** health checks, restart with backoff, dependency readiness, and clear degraded-mode reporting.
- **Checkpoint/recovery:** checkpoint long tasks, persist only approved artifacts, and resume after a crash without duplicating external actions.
- **Self-improvement lab:** generate candidate changes in isolated worktrees, run independent tests, compare paired holdouts, and retain rollback artifacts.
- **Capability registry:** list each capability's adapter, required permissions, supported environments, tests, and current confidence.
- **Resource governor:** reserve CPU/GPU/RAM and latency budget for audio and gameplay; background research pauses under load.
- **Owner approval queue:** irreversible actions, public publishing, purchases, account changes, destructive edits, and external messages remain gated.

### Character consistency without deception

STAR can have a stable character voice, preferences, humor, recurring interests, expressive reactions, and a recognizable streaming style. These should be represented as an explicit character profile and session state, not as claims of biological feelings or human identity. Keep a clear AI disclosure in the channel/about information and avoid inventing private viewer relationships or memories. A consistent character is more trustworthy than pretending to be a human.

## 11. Implementation order for the broader map

1. Finish room dispatch and host event propagation.
2. Add speaker-evidence/ASR adapter contracts and offline replay fixtures.
3. Add a stream session-state model, captions, and a response scheduler.
4. Add VTube Studio and OBS adapters with authenticated opt-in connections.
5. Add game observation/action adapters one game at a time, beginning with a deterministic sandbox.
6. Add skill versioning, held-out practice, and game-completion evaluation.
7. Add creator QA and project memory for Roblox/Blender first.
8. Add research dossiers, contradiction/freshness checks, and teach-back evaluation.
9. Add service supervision, checkpoint/recovery, and paired self-improvement gates.
10. Expand integrations only after per-adapter acceptance tests pass.
