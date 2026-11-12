# STAR AI: Trusted Host Telemetry, Unified Stream Runtime, and Capability Research

**Research date:** 2026-11-12  
**Implementation branch:** `feat/stream-host-telemetry-assembly-20261112-auto11`  
**Parent:** draft PR #1151  
**Scope:** connect existing resource/QoS policy to trustworthy live measurements; improve streaming, voice, gaming, creation, memory, and local inference without overstating what has been hardware-verified.

## Executive summary

The current development stack has useful pieces: Windows/Linux resource probes, OBS response parsers, voice playback timing, a stream-load governor, multi-resource admission, worker-process supervision, and separate game/creator/VTuber systems. The missing contract is how independently sampled measurements become one scheduler input without silently turning missing data into healthy zeros.

This branch adds `star/stream_host_sampler.py`, a pure fail-closed assembler. It accepts timestamped, clock-epoch-tagged host observations and creates the existing `StreamSample` only when the required measurements for active workloads are present and fresh.

The assembler does **not** collect hardware data, open OBS, capture audio, control a game, schedule a process, or authorize an action. Those remain host-adapter responsibilities. Its job is to make the boundary explicit and prevent the policy layer from treating unknown telemetry as healthy telemetry.

The accompanying tests cover active/inactive states, missing metrics, stale/future observations, clock-epoch changes, replayed sequence numbers, monotonic-clock regression, and the rule that a failed build does not consume a sequence number.

## 1. Repository audit: what exists and what is still a gap

The active development tree contains several distinct layers:

| Layer | Existing foundation | Remaining integration work |
|---|---|---|
| Resource observation | `star/resource_probes.py` reads Windows RAM/CPU/GPU and Linux resource state | Use raw optional measurements for authoritative stream health; do not reuse planner convenience defaults as live truth |
| Stream policy | `star/stream_load_governor.py` applies pressure thresholds and hysteresis | Feed it one coherent, freshness-bounded host sample |
| Resource admission | `star/stream_workload_admission.py` reserves CPU/RAM/VRAM by lane | Connect reservations to the actual worker supervisor and host-confirmed process lifecycle |
| Runtime bridge | `star/stream_workload_runtime.py` composes the governor and admission controller | Supply samples from a trusted host adapter |
| OBS | `star/obs_stats.py`, `star/obs_stream_status.py` validate allowlisted OBS payloads and epoch-safe counter intervals | Add an authenticated, loopback-only, read-only WebSocket transport |
| Voice | playback clock, turn metrics, bounded output-level meter | Add Windows device rehearsal, WASAPI loopback, and real output/echo calibration |
| Avatar | internal STAR VTuber/LiveRig/VMC and lip-sync path | Calibrate with actual output timing; optional VTube Studio adapter needs explicit user consent |
| Gaming | game adapters, skill-learning work, game-control QoS | Standardize observations, held-out skill trials, and real gameplay acceptance |
| Creation | Roblox-first tools, visual feedback and cross-engine evaluation work | Require playthrough and end-condition verification, not merely successful code generation |
| Learning/memory | lessons, memory and cross-session evaluation work | Evaluate whether remembered experience improves future actions and transfer |

### Important measurement audit finding

`resource_probes.pc_snapshot()` is a convenient planner snapshot. It currently substitutes values such as zero when some CPU/RAM probes fail. That is useful for a planner that wants a bounded display object, but it is not an appropriate source for an authoritative real-time health sample: zero CPU busy or zero available RAM would be a false measurement.

The stream path should use the lower-level optional probes (for example `windows_memory()` and `nvidia_gpu()`) and preserve `None` as unknown. For NVIDIA memory, derive free VRAM from a valid total-minus-used pair and reject impossible values. Never infer free VRAM from a missing `nvidia-smi` response.

## 2. New implementation: fail-closed host sample assembly

### New module

`star/stream_host_sampler.py`

Public types:

- `MetricObservation`: a value, host monotonic timestamp, and shared clock-epoch identifier.
- `StreamHostInputs`: the set of observations for one host sampling cycle.
- `StreamHostSampler`: validates and assembles the existing `StreamSample`.
- `TelemetryUnavailable`: signals missing, stale, or cross-epoch data.

### Required inputs

Always required:

- explicit streaming state;
- explicit gaming state;
- measured free VRAM.

When gaming is active:

- measured game FPS p10.

When streaming is active:

- voice response p95;
- OBS dropped-frame percentage;
- audio underrun count.

A missing measurement for an active workload raises `TelemetryUnavailable`. The caller must not pass a made-up zero to the scheduler.

Zero is used for an inactive lane only after its state has been positively observed as inactive. For example, if `gaming=False`, game FPS is not applicable; it is not being reported as a measured 0 FPS. Unknown streaming/game state is never interpreted as inactive.

### Clock and epoch rules

- Every observation must use the same host monotonic clock domain.
- Every observation must carry the current host clock epoch.
- Future-dated, stale, malformed, and cross-epoch observations are rejected.
- The assembled sample timestamp is the **oldest timestamp among the observations actually used**, not the time the assembler happened to run. This prevents a stale source from receiving a fresh timestamp merely because it was read alongside newer sources.
- Sequence numbers and sample timestamps must increase.
- A host clock-epoch change requires rebuilding the sampler and runtime. It is not silently treated as an ordinary next sample.
- Failed assembly does not consume the sequence number.

The stream runtime can then age the oldest observation using its existing freshness policy. If the source stops reporting, the runtime naturally becomes stale and background work is deferred.

### Mapping guidance for future collectors

| StreamSample field | Recommended source | Conversion |
|---|---|---|
| `streaming` | OBS `GetStreamStatus` | true only for an active output state; reconnecting/unknown must not be treated as healthy active streaming |
| `gaming` | process/window/game-session adapter | explicit process/session state, not a user prompt |
| `game_fps_p10` | engine telemetry or a frame-time sampler | p10 FPS from a defined window; preserve sample count |
| `voice_p95_ms` | STAR voice turn metrics | use the declared first-output stage; do not mix queue-submission latency with scheduled DAC output |
| `obs_dropped_pct` | OBS `GetStats` interval | conservatively use the worse of render-skip and output-skip rates, multiplied by 100; do not add the two rates |
| `vram_free_mb` | Windows NVIDIA probe | validated total MiB minus used MiB |
| `audio_underruns` | playback callback counters | monotonic interval delta, reset only at a known device/session epoch |

OBS process and stream epochs should continue to be validated by the existing OBS samplers before their intervals are mapped into this host contract. The host clock epoch is not a substitute for an OBS process epoch or stream-session epoch.

## 3. Real-time streaming: optimize the interaction, not one latency number

A natural VTuber needs a complete interaction loop:

1. capture the viewer's speech;
2. identify speech activity and likely end-of-turn;
3. distinguish a true interruption from laughter or a backchannel;
4. identify the speaker and likely addressee;
5. retrieve relevant conversation context;
6. decide whether to speak, acknowledge, or remain silent;
7. generate content;
8. synthesize expressive speech;
9. schedule audio output;
10. synchronize avatar mouth, gaze, expression, and gesture;
11. observe the result and recover cleanly if interrupted.

### Current research signals

- **MP-Bench** evaluates multiparty comprehension, turn-taking awareness, and response appropriateness. Its October 2026 benchmark page reports that evaluated real-time agents reached at most 22% multiparty comprehension and near-chance multiparty turn-taking. This is a large gap for a streamer who needs to understand conversations between viewers, not just direct questions.  
  Source: https://www.fullduplex.ai/benchmarks/mp-bench

- **Full-Duplex-Bench v3** uses real human audio, natural disfluencies, and chained tool-use scenarios. It scores tool/task accuracy, latency, and turn-taking separately. A system can be fast and still fail self-corrections or multi-step requests.  
  Sources: https://www.full-duplex.ai/benchmarks/fdb-v3 · https://arxiv.org/abs/2604.04847

- **TurnBench** measures end-of-turn and interruption detection, including false positives in backchannel-heavy conversations. A laugh or a quiet “yeah” should not automatically cut off Star's speech.  
  Sources: https://turnbench.sesame.com/ · https://github.com/SesameAILabs/turnbench

### STAR Social Director

Build on the existing turn-taking and multiparty work with an explicit floor-state model:

- `LISTENING`: accumulate evidence; do not answer every fragment.
- `DIRECTED_TO_STAR`: a speaker is likely addressing Star.
- `VIEWER_TO_VIEWER`: continue listening without taking the floor.
- `BACKCHANNEL`: acknowledge briefly or remain silent.
- `INTERRUPTION_CANDIDATE`: estimate whether the speaker is trying to take the floor.
- `YIELDING`: stop stale speech and hand the floor over.
- `RESUME_CANDIDATE`: decide whether an unfinished thought is still relevant.
- `RECOVERING`: reconcile transcript, audio, and avatar state after a cut-off.

Keep speaker identity, addressee, topic, and confidence separate. If the platform supplies separate voice channels, preserve them; if not, diarization is uncertain and must remain an estimate. Do not invent a speaker identity.

### Human-like performance without deceptive claims

The goal is natural timing, varied prosody, contextual humor, appropriate silence, and a consistent character—not pretending to be a human. Star should not manufacture offline experiences, claim to have physically felt something, or laugh on every message. If sincerely asked out of character whether she is an AI, retain the project's existing truthful-answer rule.

Viewer memory should be minimal and purpose-bound. Keep a viewer's explicit statements separate from inferred beliefs, avoid storing raw audio by default, and provide retention/deletion controls for any persistent viewer-related data.

## 4. Audio: distinguish generated, queued, scheduled, and heard

These are different points:

- text generated;
- first TTS chunk synthesized;
- PCM submitted to the speaker queue;
- output buffer scheduled for the DAC;
- audio observed by a loopback capture;
- audio physically heard by a listener.

PortAudio's output-buffer DAC timestamp is an estimate of scheduled device output, not proof of acoustic arrival in a room. A Bluetooth route, driver, endpoint, and physical speaker can add delay.

### Windows capture research

Microsoft documents WASAPI loopback capture from a rendering endpoint. Its Application Loopback sample can capture audio from a specified process and its child-process tree, rather than capturing every application's audio. This is a better privacy boundary for STAR's own TTS/game-audio measurement than indiscriminate system-mix capture.

Sources:

- https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
- https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/
- https://learn.microsoft.com/en-us/windows/win32/coreaudio/wasapi

Recommended staged implementation:

1. retain the current callback/DAC estimate;
2. add an opt-in process-scoped loopback observer;
3. use a common monotonic timeline and explicit device/route epochs;
4. store aggregate timing and underrun counters, not raw audio;
5. test route changes, Bluetooth reconnects, device removal, sleep/resume, and rapid start/stop;
6. report DAC-scheduled and loopback-observed latency as separate metrics.

Do not force a smaller audio buffer period just to improve a benchmark. Query supported device periods and test under simultaneous gaming, OBS, TTS, and inference load.

## 5. OBS and avatar integration

### OBS

OBS WebSocket is included with OBS Studio 28 and later. Its official project recommends protecting the API with a password. The v5 server normally listens on port 4455.

Source: https://github.com/obsproject/obs-websocket

Next adapter requirements:

- connect only to loopback by default;
- use the OBS challenge-response authentication flow;
- never print or persist the password in logs;
- allowlist read-only requests for health sampling;
- keep stream/scene control in a separate, owner-authorized capability;
- reconnect with bounded backoff;
- assign a new OBS-process epoch after reconnect/restart;
- assign a new stream-session epoch after every stream start;
- treat missing congestion/counters as unknown, not zero.

### VTube Studio / Live2D

VTube Studio exposes a local WebSocket API for plugins, parameter injection, hotkeys, and event subscriptions. A plugin requests authentication and the user explicitly approves access; some actions require additional permissions.

Source: https://github.com/DenchiSoft/VTubeStudio

The internal STAR avatar path should remain primary. VTube Studio should be an optional adapter with:

- explicit enablement and user consent;
- stored token kept out of logs and source control;
- reconnect/session handling;
- allowlisted parameter names and ranges;
- rate-limited updates;
- event subscriptions for model-loaded and tracking-state changes;
- a clean neutral fallback if the external app disconnects.

The Avatar Director should arbitrate mouth, gaze, expression, body, hair, and gesture layers. Speech should drive visemes from the actual audio timeline; amplitude-only mouth opening is a fallback, not the preferred lip-sync method.

## 6. Local inference: improve speed without silently lowering quality

The official llama.cpp server supports parallel decoding, continuous batching, monitoring endpoints, schema-constrained output, and speculative decoding.

Its server documentation describes `cache_prompt` reuse of a common prompt prefix. It also warns that different batch sizes can produce nondeterministic logits on some backends, so cache-enabled behavior must be tested rather than assumed bit-identical.

Sources:

- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- https://github.com/ggml-org/llama.cpp/discussions/13606

### A/B experiment matrix

Change one variable at a time and preserve the same prompt, model, sampler, output cap, and concurrency:

| Experiment | Measure | Main risk |
|---|---|---|
| Stable prompt prefix / KV reuse | prefill time and first-token latency | stale or incorrectly shared context |
| Speculative decoding | accepted draft tokens and decode throughput | draft overhead exceeds benefit |
| Quantization | quality, VRAM, speed, memory | capability regression |
| CPU/GPU layer placement | TTFT, tokens/s, CPU use, VRAM | starving game/audio threads |
| Parallel slots / batching | throughput and p95 interactive latency | queueing behind other users/tasks |
| Model residency | cold vs warm start | memory pressure |
| Context compression | quality on long tasks and latency | dropping a critical constraint |
| Task routing | quality/speed by task class | sending a hard task to a weak model |

Use a fast model for low-latency turn-taking, short acknowledgements, and simple tool routing; use a deeper model for strategic planning, difficult coding, research synthesis, and post-game analysis. Keep the same safety and authorization gateway across every model.

Do not claim improvement from tokens per second alone. Report:

- p50/p95/p99 end-to-end latency;
- prefill and decode throughput;
- time to first useful content;
- first TTS submission;
- first scheduled output;
- loopback-observed output where enabled;
- tool completion time;
- task success and factual correctness;
- VRAM/RAM peak;
- game frame-time and OBS render/output drops.

A faster model that loses game state, forgets a user constraint, or gives wrong tool arguments is a regression.

## 7. STAR Gamer: game skill acquisition and transfer

### Research

- **SIMA 2** combines language instructions, visual interaction, goal reasoning, conversation, and improvement through experience in 3D worlds. Google DeepMind also identifies limits: long-horizon tasks, short interaction memory, precise low-level actions, and robust visual understanding remain difficult.  
  Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

- **Voyager** demonstrates an automatic curriculum, an executable skill library, and feedback-driven repair in Minecraft. The transferable lesson is to store reusable procedures with preconditions and evidence, not just a prose summary of what happened.  
  Sources: https://arxiv.org/abs/2305.16291 · https://github.com/caixianzhou/voyager

- **OpenGameEval** evaluates agents inside reproducible Roblox Studio sessions, with separate observation and editing actions and executable checks in both the scene and simulated play session. Its October 1, 2026 paper reports 84 curated tasks and finds that inspecting the objects a task touches before editing correlates with higher success.  
  Sources: https://arxiv.org/abs/2610.02563 · https://github.com/Roblox/open-game-eval

### STAR Gamer architecture

Use two loops:

**Reactive controller**
- input timing;
- movement, aiming, camera and dodging;
- collision/interaction response;
- immediate state estimation;
- hard action deadlines.

**Strategic planner**
- goals and subgoals;
- map/world model;
- route and resource planning;
- tactics and practice curriculum;
- skill retrieval;
- post-session reflection.

The strategic planner must not block the reactive controller. When strategic reasoning is slow, continue with the last safe, valid control policy or pause; do not issue stale actions.

### Skill record

Each reusable skill should include:

- game, version, mode, map, and control scheme;
- preconditions and expected observations;
- executable action/controller reference;
- success and failure conditions;
- resource/time budget;
- test seeds or held-out scenarios;
- number of attempts and confidence interval;
- known failure modes;
- last verification date.

Promote a skill only after repeated success on fresh states and held-out variants. A successful run in one map is not proof of mastery across a game.

## 8. STAR Creator: finish playable games

GameDevBench evaluates multimodal game-development tasks in Godot across graphics, animation, UI, and gameplay. Its published research reports that visual feedback materially improved one evaluated configuration. OpenGameEval supplies the complementary Roblox Studio environment and stateful scene/play checks.

Sources:

- https://github.com/waynchi/gamedevbench
- https://github.com/Roblox/open-game-eval
- https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio

STAR Creator should follow this loop:

1. inspect the project tree, scene/DataModel, dependencies, and relevant assets;
2. record what was inspected before editing;
3. write a requirement-to-test matrix;
4. plan the smallest change;
5. edit a disposable project copy;
6. run static checks and unit tests;
7. launch the engine and exercise real input;
8. inspect screenshots, frame-time, runtime errors, and game state;
9. test save/load, restart, multiplayer, and end conditions where required;
10. repair, rerun, and promote only after the acceptance contract passes.

A project is not finished because it compiles. It must launch, reach its intended game mode, support its core loop, and reach a valid ending.

## 9. General knowledge and memory that changes future behavior

MemoryArena evaluates interdependent multi-session tasks where an agent must acquire information in earlier sessions and use it to make later decisions. It finds that strong passive recall does not guarantee successful memory-guided action.

Source: https://digitaleconomy.stanford.edu/publication/memoryarena-benchmarking-agent-memory-in-interdependent-multi-session-agentic-tasks/

Keep memory categories distinct:

- semantic facts and concepts;
- episodic events and experiences;
- procedural, verified skills;
- working task state;
- temporal facts with freshness;
- world/spatial models.

Every reusable memory should include provenance, observation date, last verification, confidence, scope/version, evidence, and known limitations. Separate what a viewer said from what Star inferred. Use memory to improve future tool decisions and game actions, not just to answer “what did I tell you?” questions.

For general knowledge, evaluate factual accuracy, source freshness, reasoning, and practical transfer separately. Keep benchmark questions and sealed holdouts out of tuning data. A memory change is beneficial only if it improves held-out task outcomes without increasing privacy errors or stale-fact use.

## 10. Additional capability roadmap

| Capability | Next concrete increment | Evidence required |
|---|---|---|
| Natural streamer | multiparty addressee/floor-state evaluation | MP-Bench-style comprehension and turn-taking |
| Voice | WASAPI process-loopback calibration | route-aware output latency and underrun traces |
| Avatar | VTube Studio adapter and internal Avatar Director calibration | output/viseme synchronization and disconnect recovery |
| Gamer | reactive/strategic dual-loop adapter | held-out success and frame-time budget |
| Skill learning | versioned executable skill records | repeated trials and transfer tests |
| Creator | Roblox/Godot playtest loop | executable scene checks and full playthrough |
| General knowledge | source-aware knowledge lab | freshness, provenance, and held-out reasoning |
| Inference | mixed-workload A/B harness | quality + latency + VRAM + FPS + OBS metrics |
| Autonomy | connect leases to the worker supervisor | cancellation, descendant cleanup, and host-confirmed release |
| Reliability | epoch-aware recovery and restart rehearsal | process/device/stream restart scenarios |

Other useful creator capabilities include art direction, image editing, animation, VFX, audio composition, Blender scene construction, and video review. They should share the same artifact/version/evidence model as game creation.

## 11. Security and rollout boundaries

- Host telemetry is numeric and content-free; do not put prompts, transcripts, viewer IDs, raw audio, screenshots, or secrets in scheduler samples.
- OBS control and OBS observation are separate capabilities. The stream-health adapter should be read-only.
- VTube Studio authentication tokens remain local and are never logged or committed.
- Process-specific loopback capture is opt-in and should not persist raw audio by default.
- Game input and project edits remain scoped to owner-selected accounts/projects and disposable test environments.
- Model output, memory, and generated skills never grant themselves permissions.
- High-risk external actions, publication, spending, and credential changes remain behind the existing owner approval boundary.
- No model weights, routing defaults, memory policy, avatar settings, OBS settings, or permissions are changed by this telemetry assembler.

## 12. Validation and acceptance

### New offline tests

`tests/test_stream_host_sampler.py` covers:

- known inactive lanes;
- complete live-stream measurements;
- missing active-stream metrics;
- missing game FPS;
- missing VRAM;
- stale and future-dated observations;
- cross-epoch values;
- host epoch changes;
- replayed sequence numbers;
- failed-build sequence reuse;
- booleans masquerading as numbers;
- missing state;
- monotonic clock regression;
- non-increasing assembled timestamps.

The builder is hardware-free. These tests do not prove that Windows, OBS, VTube Studio, a microphone, a GPU, or a game is producing accurate measurements.

### Required native rehearsal before enabling a collector

1. Windows 11 cold boot and host clock epoch creation.
2. OBS start/stop/reconnect and OBS-process restart.
3. Audio endpoint switch, Bluetooth reconnect, device removal, sleep/resume.
4. Game start/exit and game-window focus changes.
5. GPU driver reset or `nvidia-smi` unavailable.
6. CPU/RAM/VRAM probe timeout.
7. OBS render/output counter reset and zero-denominator windows.
8. Voice interruption while TTS is queued and while audio is playing.
9. Simultaneous game + OBS + voice + inference load.
10. Verify background work defers when any required active metric becomes stale.

### Claims boundary

This branch adds a fail-closed assembly contract and offline tests. It does **not** add the actual Windows collector, OBS WebSocket client, WASAPI loopback client, VTube Studio connector, game FPS collector, or scheduler-to-process-supervisor execution path. It does not claim a measured speedup, improved model intelligence, natural-human equivalence, game mastery, or production readiness.

Production `main`, the published installer, model weights, and default permissions remain unchanged. The child PR remains draft and is stacked on PR #1151.


## 13. New research discovery: the coordination brain (Jarvis, 2026-10-16)

A particularly relevant paper appeared on October 16, 2026:

- Paper: https://arxiv.org/abs/2610.23804
- Open-source reference implementation: https://github.com/JensenYX/Jarvis
- Project design: full-duplex front model + asynchronous workers + a typed decision model (JEV) + a versioned Task Ledger + playback delivery control.

The central idea is **models judge; code enforces**. The coordinator does not ask a model to invent arbitrary task IDs or free-form actions. The runtime constructs a finite set of legal operations from the current task state; the decision model selects one; code validates the task ID and version before applying it.

The paper reports, under its own experimental setup:

- on tau-Voice, a controlled same-front/same-backend comparison improved task success from 29/278 to 192/278;
- on Full-Duplex-Bench v3, Jarvis-Audio reported 69% Pass@1 versus 60% for GPT-Realtime;
- a scripted race suite tested stale task versions, stale plans, and false delivery records.

These are paper-reported results for the authors' models, tools, tasks, and infrastructure. They are not a prediction of STAR's performance and should not be used as an apples-to-apples comparison with STAR.

### Why this is unusually relevant to STAR

STAR already has a bounded async DAG executor in `star/agent_runtime.py` and playback timing in `star/voice/playback.py`. The current host telemetry assembler provides another part of the picture. What remains is a reliable coordinator that can see both the live conversation and long-running work at the same time.

A streamer must be able to say “keep building the game, but change the menu,” “cancel only the screenshot task,” or “stop talking while you finish the research.” Without a shared, versioned task record, a late worker result can answer an old request, an obsolete plan can still execute, or an answer can be marked delivered even though playback was interrupted.

### Proposed STAR Coordination Brain

Implement this as an adapter around existing task execution, not as a second independent agent framework:

1. **Task Ledger:** each task has an opaque ID, monotonically increasing version, objective, scope, dependencies, status, creation/update time, and evidence references.
2. **Typed operation set:** the runtime generates only legal options for the current turn: `ANSWER`, `MEMORY_LOOKUP`, `CREATE`, `REFINE(task_id, version)`, `CANCEL(task_id, version)`, `STATUS(task_id, version)`, `CLARIFY`, `STOP_SPEAKING`, `WAIT`, or `IGNORE`.
3. **Compare-and-swap:** every operation names the exact current task version. A decision against version 2 becomes a no-op after version 3 supersedes it.
4. **Plan freshness:** revalidate the task version, authorization, inputs, and evidence immediately before any side effect. Do not rely on the version that was current when planning began.
5. **Result freshness:** accept a worker result only if it belongs to the live task version and its required evidence remains valid.
6. **Separate speech from work:** `STOP_SPEAKING` advances the playback generation epoch and discards queued stale audio; it does not cancel the task. `CANCEL` stops the task and invalidates its version.
7. **Playback receipt:** `COMPLETED` becomes `DELIVERED` only after a receipt confirms that the full answer was emitted in the current playback epoch. A TTS response or queue submission is not a delivery receipt.
8. **Evidence timeline:** screen/game observations carry capture time, source, and a validity window. Recheck them before advice is generated and again before/during playback. A death, respawn, camera switch, map transition, or new game state can invalidate old claims.
9. **Uncertain decision fallback:** if the coordinator cannot select a legal operation confidently, preserve the ledger and route to a safe worker or one focused clarification. Never guess a task target.
10. **Durable memory gate:** only write long-term viewer facts when they are explicit, useful, and within the project's consent/retention policy. Task-specific instructions expire with the task.

### STAR-specific adaptation: do not copy the entire model stack

The reference implementation is a useful design and code-audit target, but its documented quick start expects Linux, Python 3.11, NVIDIA BF16-capable GPU hardware, separate model services, and API configuration. That is not a safe assumption for STAR's Windows-first, 8 GB VRAM target.

Port the **control-plane invariants**, not the whole model deployment:

- use the existing async DAG workers;
- use the existing playback clock and add generation/receipt semantics;
- keep the coordinator small and fast, with a deterministic typed schema;
- reuse STAR's existing authorization boundary;
- make the ledger local-first and restart-safe;
- use one owner-controlled task identity across voice, gaming, creator, browser, and background research;
- keep model choice replaceable behind the same typed operation contract.

### New acceptance tests for the coordinator

Before enabling it in streaming:

- refine a task while its worker is running; the old result must be rejected;
- cancel one task while independent tasks continue;
- stop speech without cancelling the underlying task;
- interrupt playback halfway through; no delivery receipt is issued;
- restart the audio device; old playback receipts cannot complete the new epoch;
- change a game scene while a response is queued; expired screen evidence is not spoken as current;
- issue an ambiguous correction that could target two tasks; no task changes without a valid typed choice;
- return a worker result after cancellation; it is ignored;
- race two refinements against the same task version; only one compare-and-swap succeeds;
- restart STAR with a persisted ledger; task IDs, versions, and cancellation state remain consistent.

Measure coordinator decision latency, stale-operation rejection, false-delivery rate, task completion, and end-to-end voice latency. The goal is to make the conversation feel immediate while background work remains correct—not to add another LLM call to every utterance.

**Decision:** treat Jarvis as a high-priority architecture reference for STAR's next coordination milestone. Do not import it wholesale or claim its benchmark results for STAR.
