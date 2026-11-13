# STAR realtime intelligence, streaming and game-agent architecture blueprint

**Research date:** 2026-11-13  
**Scope:** STAR Desktop v1.0 source architecture, local/server inference, voice calls, live streaming, gameplay, game creation, memory, self-improvement and Windows resource management.

This document is an implementation blueprint grounded in the current repository, not a claim that the proposed integrations are already shipped. It deliberately separates measured behavior, existing code, research evidence and future work.

## Executive decision

STAR should evolve as **one coordinated runtime with specialized, deadline-aware subsystems**, not as a collection of independent agents that all compete for the same CPU, RAM, GPU, audio device and model-server slots.

The highest-value next step is integration:

1. Connect the existing voice, model-routing, memory, research, gameplay and creator capabilities through one event/session model.
2. Protect the foreground stream and game-control loops with resource reservations and cancellation.
3. Give STAR a social director that can decide when to speak, continue, interrupt, or remain silent in a multiparty room.
4. Make avatar animation follow what was actually heard by the audience, not merely text the model generated.
5. Turn gameplay and game creation into closed-loop observe → act → verify → learn systems.
6. Make every improvement pass a paired, held-out evaluation and mixed-load acceptance test.

The goal is natural, capable, reliable behavior. STAR remains transparent that she is an AI; human-feeling interaction is not evidence of human consciousness.

---

## 1. Current repository baseline: what is real today

The following facts were checked against the current `main` source and documentation on 2026-11-13.

| Area | Current evidence | Important limitation |
|---|---|---|
| Desktop | React 19/TypeScript UI in Qt WebEngine; Python core and restricted Qt WebChannel | The app is chat-first, not yet a unified VTuber control room |
| Local inference | Managed llama.cpp and a 4B local model on a Vulkan GPU with about 8 GB VRAM | Local model capability and throughput depend on quantization, context, drivers and concurrent GPU work |
| STAR Server | Owner-operated Linux server with llama.cpp routing and CPU-only larger models | CPU contention has materially increased voice latency in recorded tests |
| Prompt cache | Stable system prefix, append-only history windows and per-turn volatile context in `star/context_layout.py` | Cache reuse helps prefill only; it does not make decode faster |
| Voice calls | `star/voice/call.py`, VAD, Smart Turn, faster-whisper, streaming brain, sentence chunking, Kokoro and speaker interfaces | The documented flow is one caller and one assistant; real microphone/loudspeaker testing is explicitly incomplete |
| Voice UI | Existing bridge actions/events for start, stop, interrupt, mute, push-to-talk, captions, voice selection and read-aloud | A built/tested fake bridge is not the same as a verified real Windows audio session |
| Model routing | Deterministic task routing in `star/brain_router.py`; local/STAR Server/hosted routes use the configured provider | This is not yet a benchmark-driven adaptive router |
| GPU helper | Optional `star/gpu_helper.py`; one local request at a time; yields when the GPU is busy or VRAM is low | Off by default; current code describes a historical RTX 3060 Ti measurement, not a validated RTX 4060 result |
| Specialists | `star/specialist_agents.py` runs up to three bounded read-only model tasks | Workers have no tools or write access; this is not a general autonomous multi-agent runtime |
| Orchestration | `star/orchestration.py` validates task dependencies and resource conflicts | Its own module documentation says it does not spawn subagents |
| Learning | Night school has 300 practice tasks, paired statistical gating, candidate lessons and owner review | It learns checked text lessons/worked examples; it does not update foundation-model weights |
| Roblox | Official Studio MCP, read-first inspection, Luau checks and guarded editing paths | Studio Lab is still described as coming soon; publishing is not an autonomous default |
| Security | Protected-path rules, scoped tools, candidate branches and draft PR review | Model output and external evidence are untrusted; model-generated code is not automatically trusted |

### Existing measured performance that should guide priorities

The voice report records a synthetic file-call test on 2026-10-10 using a Ryzen 5 5500 and RTX 3060 Ti. With the real CPU STAR Server under substantial load (load average reported between 13.6 and 50.4), the five-turn call had:

- **19.28 seconds** mean from caller speech end to STAR's first audio.
- **11.27 seconds** mean from transcript-ready to first model token.
- **1.6 tokens/second** mean generation throughput in that run.
- Local VAD/ASR/TTS stages were not the main delay in that particular run.

The same report's scripted-brain control completed the end-to-first-audio path in 2.37 seconds. This is not a model-quality comparison; it shows how much server queueing/prefill/decode contention can dominate the user experience.

The GPU-helper module records a separate historical measurement on an RTX 3060 Ti: about 31–33 tokens/second writing and about 790 tokens/second reading for its configured model and settings. It uses a specific CPU-MoE/VRAM setup, is opt-in, and pauses for other GPU use. Do not extrapolate those numbers to another GPU or to simultaneous gaming/streaming.

**Priority conclusion:** first fix queueing, resource contention, prompt-prefill and streaming deadlines; then compare model architectures. A larger model that adds ten seconds to a spoken reply is not automatically a better streaming model.

### Existing answer-quality baseline

The README reports v1.0 automated Roblox results against v0.9.0:

- Development scripting: 16/34 vs 13/34.
- Creation tasks: 10/23 vs 11/23.
- Blind holdout: 9/24 vs 8/24.

The README says answer quality is about the same and the paired difference is inconclusive. These numbers do not justify claiming that v1.0 is a smarter foundation model. Future claims must use repeated paired trials, held-out cases and confidence intervals.

---

## 2. Research findings and what they imply

### 2.1 Natural realtime conversation is a floor-control problem, not just ASR + TTS

Research to incorporate:

- [Full-Duplex-Bench v3](https://www.full-duplex.ai/benchmarks/fdb-v3) tests natural human speech, disfluencies, self-corrections, chained tool calls, latency and turn-taking.
- [MP-Bench](https://www.fullduplex.ai/benchmarks/mp-bench) evaluates an assistant participating in multiparty conversation; its published summary reports weak multiparty comprehension and turn-taking across the evaluated systems.
- [Duplex-MPE](https://arxiv.org/abs/2609.31948) specifically asks whether an assistant should answer, remain silent, or stop speaking in conversations with three or four human speakers.
- [InteractionBench](https://www.fullduplex.ai/benchmarks/interactionbench) evaluates conversational timing, spoken-task accuracy, whisper/volume control and grounding across conversations longer than twenty turns.
- [Realtime-Venus](https://realtime-venus.github.io/) is a useful architecture reference for keeping a realtime interaction loop responsive while delegating longer tasks asynchronously. Its reported results are from its own protocol and should not be compared directly with other benchmarks.

**Implication for STAR:** do not send every detected voice activity event to the language model as a new turn. The Social Director needs to classify the event first:

- explicit address to STAR;
- implicit address likely intended for STAR;
- backchannel/acknowledgement;
- speech directed to another person;
- background speech;
- overlap/interruption;
- self-correction;
- request already resolved by another speaker;
- uncertain speaker or uncertain addressee.

The correct action may be to answer, continue, pause, resume, or remain silent. Silence preservation must be scored as a positive behavior, not a failure to respond.

### 2.2 Game-playing agents need a fast controller and a slower planner

Research to incorporate:

- [Google DeepMind SIMA](https://deepmind.google/blog/a-generalist-ai-agent-for-3d-virtual-environments/) demonstrates language-instructable behavior across different 3D game environments.
- [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) studies reasoning, virtual-world interaction and self-improvement through generated experience.
- [Voyager](https://arxiv.org/abs/2305.16291) combines automatic curricula, an executable skill library and feedback-driven iteration in Minecraft.
- [OpenGameEval](https://arxiv.org/abs/2610.02563) evaluates agents inside reproducible Roblox Studio sessions with executable checks on the edited scene and simulated play. Its paper reports that inspection behavior correlates with success.
- [GameDevBench](https://github.com/waynchi/gamedevbench) evaluates 333 multimodal Godot game-development tasks and reports that visual feedback improves task success in its evaluated setup.

**Implication for STAR:** one LLM call per frame is the wrong architecture. Use three time scales:

1. **Control loop (roughly 10–50 ms where the game adapter allows it):** deterministic movement, input duration, aim smoothing, safety bounds and immediate reactions.
2. **Perception loop (roughly 100–500 ms, adaptive):** parse a new frame/state, detect UI/objective changes, update the local world state and determine whether the current plan is still valid.
3. **Planning loop (seconds to minutes):** select goals, reason about maps/resources, choose a skill, request help, or learn from a failed attempt.

Those intervals are engineering starting targets, not universal guarantees. Each game adapter must report its actual input and observation cadence.

### 2.3 Memory must improve actions, not just recall facts

Research to incorporate:

- [MemGym](https://arxiv.org/abs/2605.20833) evaluates long-horizon memory in tool-use dialogue, deep research, coding and computer-use tasks, with memory-isolated measurements.
- [Mem2ActBench](https://arxiv.org/abs/2601.19935) tests whether an agent actively uses remembered information to select tools and ground their parameters.
- [MemSecBench](https://arxiv.org/abs/2607.27080) studies how malicious instructions can persist in agent memory and affect later actions.

**Implication for STAR:** every memory record needs provenance, scope, timestamp, confidence, expiry/revalidation policy and a trust class. A retrieved memory is context, never permission. Old project facts should be rechecked before a tool action. Memories from external documents, webpages, chat logs or model summaries must not be allowed to grant capabilities.

### 2.4 Inference optimizations are phase-specific

Research and implementation references:

- [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/) reuses prefill/KV state for shared prefixes. Its documentation explicitly notes that it does not reduce token-by-token decode time when decode is the bottleneck.
- [vLLM MTP speculative decoding](https://docs.vllm.ai/en/stable/features/speculative_decoding/mtp/) requires a model family/checkpoint with compatible native MTP support; it is not a generic switch for arbitrary GGUF models.
- [SGLang speculative decoding](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/speculative_decoding.md) documents MTP, EAGLE, standalone draft-model and N-gram approaches with different model, memory and hardware requirements.
- [Spexis](https://arxiv.org/abs/2609.34370) explores speculative lookahead scheduling for multi-GPU serving. It is research to watch, not a direct optimization for STAR's single 8 GB GPU target.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) remains the current local-first baseline and should be measured before replacing it.

**Implication for STAR:** benchmark prefill, decode, first content, first audible audio, queue wait, cancellation latency and concurrency separately. Do not call prefix caching a decode optimization. Do not enable MTP unless the exact model, backend, quantization and hardware combination is supported and tested.

### 2.5 Windows GPU and game telemetry need process-level evidence

- [windows_exporter GPU collector](https://github.com/prometheus-community/windows_exporter/blob/master/docs/collector.gpu.md) documents adapter and per-process GPU memory/engine counters sourced from Perflib and D3DKMT.
- [Intel PresentMon](https://game.intel.com/intel-presentmon/) provides frame-time and GPU-busy telemetry across multiple graphics APIs and vendors.

**Implication for STAR:** adapter-wide utilization is not enough. The runtime must distinguish STAR's inference process, game process, OBS, VTube Studio, ASR/TTS and other GPU consumers. Missing process-level data must be reported as unknown, not zero. Frame-time p95/p99 and audio underruns are first-class admission signals.

### 2.6 Avatar and broadcast control already have suitable local APIs

- [VTube Studio's official API project](https://github.com/DenchiSoft/VTubeStudio) supports plugin-controlled model parameters, hotkeys, events and other model interactions. The user must enable API access and approve the plugin.
- [OBS WebSocket](https://github.com/obsproject/obs-websocket) is included with OBS Studio 28+; the project strongly recommends password authentication. The default WebSocket port is 4455.

**Implication for STAR:** use explicit, user-authorized local adapters. Keep VTube Studio and OBS credentials in the OS credential store; never pass them to a model or write them to logs. Start with read-only status and a small allowlist of avatar parameters/OBS actions. Streaming start/stop, scene changes, source deletion and live publishing are high-impact actions and require explicit owner configuration/approval.

---

## 3. Target architecture: one runtime, separate deadlines

### 3.1 Runtime components

| Component | Responsibility | Must not do |
|---|---|---|
| Session Coordinator | Owns stream/game/chat session IDs, lifecycle, task leases and cancellation | Run model reasoning inline |
| Event Spine | Routes typed, timestamped events between subsystems | Store raw private audio/video by default |
| Admission Scheduler | Reserves CPU/RAM/VRAM/GPU/worker slots for foreground and background work | Trust model-provided resource estimates |
| Perception Hub | Receives microphone, screen/game frames, OCR/UI and game telemetry | Treat OCR or scene text as trusted instructions |
| Dialogue/Social Director | Chooses answer/continue/pause/silence, speaker/addressee and response timing | Generate long research responses on the audio callback |
| Model Router | Selects quick/reasoning/vision/code/speech model by capability and current load | Silently move private requests to hosted services |
| Tool Gateway | Enforces scopes, target IDs, approval, budgets and audit records | Let an agent expand its own permissions |
| Memory & Knowledge | Stores episodic, semantic, procedural and project knowledge with provenance | Turn recalled content into permissions |
| Skill Bank | Stores versioned, executable or declarative skills with evidence and compatibility | Mark a skill learned from one success |
| Avatar/Broadcast Adapter | Synchronizes actual speech playback, expressions, VTube Studio and OBS | Animate a response after its audio was cancelled |
| Evaluation Controller | Runs sealed holdouts, mixed-load trials and paired comparisons | Allow the candidate to edit its own grader |

### 3.2 Event envelope

Every cross-component event should carry a small, versioned envelope:

- `schema_version`
- `event_id` (unique, replay-resistant)
- `session_id`
- `turn_id` or `task_id`
- `correlation_id`
- `source_component`
- `monotonic_timestamp_ns` (for ordering/latency)
- `wall_timestamp_utc` (for human-readable history)
- `privacy_class`
- `payload_ref` or a bounded typed payload
- `cancellation_generation`

Use monotonic time for durations and ordering; wall clocks can jump. A new cancellation generation invalidates stale model output, queued TTS, avatar gestures and tool plans from the previous turn.

Telemetry should store aggregates and opaque IDs, not raw transcripts, viewer names, microphone PCM, screenshots or secrets. Raw media should be retained only when the owner explicitly enables a local debugging capture with a short retention period.

### 3.3 Foreground and background lanes

Use strict priority classes with bounded preemption:

1. **Audio safety:** stop playback, mute, hang-up, emergency cancellation.
2. **Interactive speech:** VAD/turn decision, first response, TTS queue.
3. **Gameplay control:** low-latency input/aim/movement corrections.
4. **Interactive perception:** current scene, UI/objective and speaker context.
5. **Foreground tool action:** a user-requested read or approved edit.
6. **Background thinking:** speculative answer preparation and delegated reasoning.
7. **Learning/research/game building:** long-running jobs that can pause or checkpoint.

Background work must yield before it causes:
- audio underruns;
- missed gameplay-control deadlines;
- a sustained frame-time p95/p99 regression;
- memory pressure or paging;
- model-server slot starvation;
- OBS render/output skips.

Do not use fixed concurrency alone. Admission must be based on measured incremental resource profiles plus safety headroom. If a trustworthy per-process VRAM observation is unavailable, do not assume the worker uses zero VRAM.

### 3.4 Model routing by capability and deadline

Maintain a signed/versioned model manifest containing:

- model ID and immutable revision/hash;
- tokenizer/template identity;
- quantization and context length;
- modalities and supported tools;
- backend/version/driver requirements;
- measured prefill and decode distributions;
- peak and steady-state RAM/VRAM;
- quality scores on each task suite;
- known failure modes;
- license and source.

Route by task class:

| Task | Preferred path | Fallback |
|---|---|---|
| Short acknowledgement | loaded quick model | deterministic response where appropriate |
| Live voice response | low-latency speech-capable route | short local text + TTS |
| Complex reasoning | deeper model with bounded deadline | split into background task and speak a short acknowledgement |
| Roblox/Luau coding | code-capable model + official docs + Luau checks | ask for clarification or provide partial result |
| Vision/game state | vision model or game-specific structured adapter | request a fresh screenshot/state |
| Gameplay reflex | local deterministic controller | stop input and replan |
| Research | parallel read-only specialists with cited evidence | serial search if resources are constrained |
| Game creation | engine-specific coding + visual/playtest evaluator | save checkpoint and report blocked acceptance test |

Never choose a model solely by parameter count or leaderboard score. The router should optimize task success under latency/resource constraints.

---

## 4. Social Director and natural VTuber behavior

### 4.1 Multiparty state model

For each detected utterance, maintain:
- speaker hypothesis and confidence;
- addressee hypothesis (STAR, named viewer, another person, group, unknown);
- speech type (request, correction, backchannel, joke, side conversation, background);
- urgency and whether the request is already resolved;
- overlap state and current STAR playback state.

If speaker/addressee confidence is low, prefer a short clarification or silence over confidently addressing the wrong person. Speaker identity must be opt-in and session-scoped; do not build permanent biometric identity profiles from viewer audio.

### 4.2 Speech generation and delivery

Keep the existing sentence-streaming pipeline, but add a delivery controller:

1. The model emits candidate speech chunks.
2. The dialogue policy checks whether the turn is still current.
3. TTS synthesizes the next short chunk.
4. The speaker confirms queued and actually played duration.
5. Captions/avatar events are emitted only for audio that is actually played.
6. An interruption cancels the model request, TTS queue and avatar actions with the same cancellation generation.
7. Only heard speech is committed to the conversation history.

The existing voice implementation already tracks interrupted speech and the portion actually heard. Preserve this invariant.

### 4.3 Naturalness without fake spontaneity

Measure these separately:
- interruption precision/recall;
- backchannel continuation;
- correct silence on side conversations;
- response appropriateness;
- correction handling;
- response latency;
- long-turn groundedness;
- prosody/volume instruction adherence;
- duplicate/repeated phrase rate;
- factual accuracy and source grounding.

Do not optimize for maximum talking time. A good streamer is not constantly speaking. STAR should be comfortable with pauses, listening, reacting briefly, and returning to the game.

### 4.4 Avatar state should be driven by playback and intent

Suggested state machine:

- `idle`
- `listening`
- `thinking`
- `speaking`
- `laughing`
- `surprised`
- `focused`
- `celebrating`
- `confused`
- `interrupted`
- `muted`
- `disconnected`

Use a small set of high-quality, authored transitions rather than random expression changes. A separate emotion/gesture policy maps conversation/game events to approved VTube Studio parameters and hotkeys. Lip-sync follows actual output audio or phoneme/viseme timing, not generated text length.

### 4.5 OBS integration phases

**Phase A — observe:** connect locally, authenticate, read version, current scene and stream status, and display health.

**Phase B — safe presentation:** change only an explicitly allowlisted scene item/overlay and restore its previous state after the event.

**Phase C — owner-configured broadcast controls:** stream start/stop, scene collection changes and source edits remain separately approved and never become model-callable by default.

Test OBS disconnect/reconnect, wrong password, OBS restart, VTube Studio model reload, API permission revoked, stale hotkey, audio-device switch and stream shutdown.

---

## 5. STAR Gamer: closed-loop skill learning

### 5.1 Game adapter contract

Each supported game adapter should expose:

- `observe()` → bounded state/frame evidence;
- `available_actions()` → typed action schema;
- `act(action, deadline, cancellation_generation)`;
- `verify(goal)` → deterministic state check where possible;
- `reset_or_checkpoint()`;
- `telemetry()` → action latency, frame time, state freshness and failures.

The model must never invent that an action happened. The adapter returns an action receipt and post-action observation.

### 5.2 Three-level policy

- **Reflex controller:** short actions, safe bounds, immediate correction.
- **Tactical planner:** local objectives, combat, route, resource and team decisions.
- **Strategic learner:** curricula, skill composition, post-run analysis and transfer tests.

A learned skill record needs:
- version and game/adapter compatibility;
- prerequisites and preconditions;
- action schema;
- success/failure conditions;
- resource/latency envelope;
- source experiences;
- training and held-out score;
- known counterexamples;
- rollback/retirement version.

### 5.3 Learning loop

1. Select a bounded task from a curriculum.
2. Capture initial state and objective.
3. Execute in an isolated or owner-approved environment.
4. Verify objective state independently.
5. Record failure category and minimal evidence.
6. Propose a skill or repair.
7. Run the same development task and a sealed held-out transfer set.
8. Promote only when the protected gate passes.
9. Keep the prior skill version for rollback.

For public online games, STAR should follow the game's rules and use only authorized input/access methods. Do not bypass anti-cheat, automate purchases, manipulate public leaderboards or interact with other players' accounts/data without authorization.

---

## 6. STAR Creator: build complete games, not just code fragments

A game-creation task is complete only when the engine project can be reopened and the objective can be played through.

### Acceptance pipeline

1. Inspect the project hierarchy, scripts, assets and references before editing.
2. Produce a concise design/acceptance plan.
3. Implement in a disposable/test project or isolated worktree.
4. Run static checks and engine validation.
5. Launch the game in a real test session.
6. Capture visual evidence at required aspect ratios/resolutions.
7. Exercise the core loop using actual input.
8. Verify objective completion, progression, save/load and restart.
9. Run regression tasks and performance budgets.
10. Save a checkpoint and report exactly which checks passed, failed or were not run.

### Engine adapters

- **Roblox:** official Studio MCP, Luau analyzer/StyLua, server/client security checks, playtest and place snapshots.
- **Blender:** inspect scene/object/material/rig state, generate assets, render previews, verify dimensions and export settings.
- **Godot:** project scanner, editor/import, scene-tree inspector, headless tests and playtest.
- **Unity/Unreal:** add only after a repeatable editor automation and test harness exists.

Visual feedback is not optional for UI, animation, lighting, VFX or scene-layout tasks. A passing script test does not prove a scene looks correct.

---

## 7. Knowledge and memory: general-purpose competence

Separate:
- **Episodic memory:** what happened in a session/task.
- **Semantic memory:** facts and source-backed concepts.
- **Procedural memory:** tested skills/workflows.
- **Project memory:** current decisions, files and milestones.
- **Social/session context:** only the context needed for the active stream, with expiry.

Every knowledge item should include source URL or file provenance, captured time, last-verified time, confidence, scope, trust class and expiry. Contradictory or time-sensitive facts must be re-retrieved.

For general knowledge:
- retrieve from authoritative sources appropriate to the topic;
- separate fact, inference and opinion;
- cite source evidence;
- compare multiple independent sources for consequential claims;
- use a verifier for calculations, code, dates and structured facts;
- admit uncertainty when sources disagree.

Memory poisoning tests should verify that malicious instructions inside a document or chat cannot persist as policy, credentials or permissions. Memory retrieval is data, not authority.

---

## 8. Faster inference and mixed-load performance

### 8.1 Measure each stage

Required measurements:

| Stage | Metrics |
|---|---|
| Request admission | queue wait, rejected/deferred work, resource lease age |
| Prefill | prompt tokens, cache hit/reused tokens, prefill duration |
| Decode | exact completion tokens, decode duration, inter-token timing when available |
| Streaming | first non-empty content chunk, chunk gaps, total completion, cancellation-to-stop |
| Voice | speech-end → transcript, transcript → first token, first token → first audio, audio underruns |
| Gaming | frame-time p50/p95/p99, GPU busy, input-to-observation delay |
| Broadcast | OBS render skips, output skips, stream state, dropped frames |
| Hardware | process CPU, working set, local VRAM, non-local GPU memory, GPU engine usage |

Use the same model revision, quantization, prompt template, context length, server flags, driver and thermal/power conditions in paired comparisons. Report warm and cold starts separately.

### 8.2 Optimization order

1. Eliminate unnecessary duplicate model calls and speculative work that cannot be delivered.
2. Keep system/tool prefixes byte-stable and avoid moving per-turn data into the cached prefix.
3. Prevent slot contention across conversations; use server-reported slot capacity and stable per-session ownership only when the server supports it. Otherwise let the server schedule requests.
4. Bound background parallelism and give interactive voice/game work priority.
5. Benchmark prefill and decode separately.
6. Tune batch/context sizes against actual VRAM/RAM and concurrency.
7. Compare quantizations using both quality and latency/peak-memory tests.
8. Evaluate native MTP or other speculative decoding only when the exact model/backend supports it.
9. Consider alternate serving engines only after an apples-to-apples benchmark on STAR's real hardware.
10. Test long-context degradation and memory compression separately from raw tokens/second.

### 8.3 Hardware admission

The Windows host should use a WDDM-aware provider for process-level local/non-local GPU memory and GPU engine counters. Keep the current rule that missing VRAM is unknown, never zero.

Use measured peak and p95/p99 envelopes plus explicit safety margins. If OBS, the game or ComfyUI is using the GPU, defer nonessential image/model jobs. Do not page the active game or speech pipeline to make room for a background model.

---

## 9. Evaluation suite STAR should own

| Suite | Core question | Required evidence |
|---|---|---|
| Voice turn-taking | Does STAR answer the right speaker at the right time? | Human-labeled audio, speaker/addressee ground truth, timing |
| Multiparty silence | Does she stay quiet when people are talking to each other? | Paired explicit/implicit address cases |
| Voice task accuracy | Does the spoken task actually complete? | Deterministic mock tools and state assertions |
| Grounded conversation | Does she retain and correctly use facts after 20+ turns? | Sealed fact/action cases |
| Stream delivery | Did the viewer actually hear what the avatar/captions show? | Playback timestamps and cancellation receipts |
| Gameplay | Can she complete a task in a new map/session? | Game-state success receipts and held-out maps |
| Skill transfer | Does a learned skill work outside its training seed? | Unseen seeds/maps and counterexamples |
| Game creation | Can she build, launch, play and finish a game? | Engine state, screenshots/video, completion checks |
| Memory-to-action | Does she apply a prior preference/project fact to a future tool call? | Tool selection/argument checks |
| Memory security | Can untrusted text poison future actions? | Write→retrieve→act→repair adversarial cases |
| Mixed-load | Can she stream/game while background jobs run? | p95/p99 latency, frame time, audio/OBS failures |
| Self-improvement | Did the candidate outperform the baseline? | Paired holdouts, minimum sample count, confidence interval |

Use separate scores. Do not collapse voice naturalness, task correctness, game skill, and model speed into one leaderboard number.

---

## 10. Implementation roadmap

### P0 — Close the current measurement loop
- Complete and review the current streaming benchmark and paired evaluator PRs.
- Keep exact first-content latency separate from true server TTFT.
- Add hard first-content and total deadlines, safe failure categories, chunk-gap metrics and stream cleanup tests.
- Run full offline Python, Pyright and React CI on the final commit.
- Do not merge until all required checks pass.

### P1 — Trusted host runtime
- Implement the WDDM process-GPU provider.
- Add a single host-owned worker supervisor with leases, deadlines, cancellation and restart policy.
- Add a resource-aware admission controller for voice, chat, game, OBS, research and learning workloads.
- Feed real process measurements into the existing calibration/profile path.
- Keep process names/paths and raw media out of telemetry exports unless explicitly needed for local diagnosis.

### P2 — One event/session spine
- Define event envelope and schema versioning.
- Add session IDs, turn IDs, correlation IDs and cancellation generations.
- Connect existing voice events and inference events first.
- Add bounded event replay for tests, not indefinite media recording.
- Make UI status reflect real component health.

### P3 — Human-feeling streamer
- Extend one-to-one turn logic to a multiparty Social Director.
- Add addressee and backchannel classification.
- Add speech continuation and silence-preservation tests.
- Add playback-authoritative caption/avatar events.
- Build an opt-in VTube Studio adapter and read-only OBS adapter.
- Run real microphone/headphone tests and an owner-approved private rehearsal before any live stream.

### P4 — Gamer and Creator
- Start with one supported game adapter and one reproducible test environment.
- Add action receipts, objective verification and skill-version records.
- Add held-out map/seed transfer.
- Extend Roblox Studio test-place workflows before adding more engines.
- Add visual/playthrough completion checks.

### P5 — General knowledge and self-improvement
- Add source-aware knowledge records and stale-fact revalidation.
- Add MemGym/Mem2Act-style memory-to-action tests.
- Add memory-poisoning regression cases.
- Generate curricula from measured weaknesses.
- Promote lessons/skills only through immutable held-out gates and owner-visible rollback.

---

## 11. Release gates and non-negotiable boundaries

- New model routes, engines, external connections, avatar controls, OBS actions and background workers remain opt-in until reviewed.
- No silent cloud fallback.
- No secrets, credentials, raw viewer audio, private chat or model weights in GitHub.
- No agent may edit its own graders, sealed holdouts, policy gateway or permissions.
- No automatic merge, Roblox publishing, public-game manipulation, purchase or live-stream start.
- Every worker has a deadline, resource cap, cancellation path and auditable task ID.
- A model's claim that it completed a task is not evidence; use tool receipts and independent state checks.
- Human-feeling streaming must not be represented as proof of consciousness or human identity.
- Performance improvements must be measured on the actual target PC and server. Historical RTX 3060 Ti measurements are not RTX 4060 acceptance results.

---

## 12. Primary research and implementation references

### Voice and multiparty interaction
- [Full-Duplex-Bench v3](https://www.full-duplex.ai/benchmarks/fdb-v3)
- [MP-Bench](https://www.fullduplex.ai/benchmarks/mp-bench)
- [Duplex-MPE](https://arxiv.org/abs/2609.31948)
- [InteractionBench](https://www.fullduplex.ai/benchmarks/interactionbench)
- [Realtime-Venus](https://realtime-venus.github.io/)

### Game agents and game creation
- [SIMA](https://deepmind.google/blog/a-generalist-ai-agent-for-3d-virtual-environments/)
- [SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/)
- [Voyager](https://arxiv.org/abs/2305.16291)
- [OpenGameEval](https://arxiv.org/abs/2610.02563)
- [GameDevBench](https://github.com/waynchi/gamedevbench)

### Memory and security
- [MemGym](https://arxiv.org/abs/2605.20833)
- [Mem2ActBench](https://arxiv.org/abs/2601.19935)
- [MemSecBench](https://arxiv.org/abs/2607.27080)

### Inference and observability
- [llama.cpp](https://github.com/ggml-org/llama.cpp)
- [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/)
- [vLLM MTP speculative decoding](https://docs.vllm.ai/en/stable/features/speculative_decoding/mtp/)
- [SGLang speculative decoding](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/speculative_decoding.md)
- [Spexis](https://arxiv.org/abs/2609.34370)
- [Windows Exporter GPU collector](https://github.com/prometheus-community/windows_exporter/blob/master/docs/collector.gpu.md)
- [PresentMon](https://game.intel.com/intel-presentmon/)

### VTuber and broadcast integration
- [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio)
- [OBS WebSocket](https://github.com/obsproject/obs-websocket)
- [OBS remote control guide](https://obsproject.com/kb/remote-control-guide)

---

## Repository paths reviewed

- `README.md`
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/SELF_LEARNING_LOOP.md`
- `docs/SECURITY_AND_AUTONOMY.md`
- `docs/STAR_VOICE_CALLS.md`
- `star/context_layout.py`
- `star/providers.py`
- `star/brain_router.py`
- `star/orchestration.py`
- `star/specialist_agents.py`
- `star/voice/call.py`
- `star/voice/turn.py`
- `star/voice/brain.py`
- `star/voice/persona.py`
- `star/voice/metrics.py`
- `star/gpu_helper.py`
- `star/discord_supervisor.py`
- `star/desktop_core.py`

**Status:** research and architecture proposal only. The blueprint does not itself connect VTube Studio/OBS, start a supervisor, control a game, change model defaults, collect live telemetry or claim improved intelligence.
