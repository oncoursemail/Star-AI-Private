# STAR Resource Admission, Dual-Loop Runtime, and Capability Evaluation Research

**Date:** 2026-11-13  
**Branch:** `feat/resource-admission-20261113-run21`  
**Status:** Research plus a pure, opt-in-ready admission policy. The policy is not wired into the desktop supervisor and is not enabled by default.

## Executive recommendation

STAR should use a **two-loop runtime**:

1. **Protected interaction loop:** microphone/audio callbacks, TTS playback, foreground conversation, game input, and OBS capture/encoding. This loop must remain responsive and must not wait on background research, model training, asset generation, or database work.
2. **Capability loop:** background reasoning, research, code generation, image/video generation, indexing, practice, and specialist agents. Work enters this loop only when the host has fresh telemetry and enough resource headroom.

This architecture is supported by the September 2026 Realtime-Venus paper, which separates continuous interaction from asynchronous capability execution and binds delegated work to the originating session and its evidence snapshot. The paper also reports that routing itself remains imperfect; STAR must evaluate both unnecessary delegation and missed delegation, not assume a model always chooses correctly.

The new `star/resource_admission.py` module implements only the **policy decision** for optional background work. It does not collect telemetry, create processes, reserve GPU memory, or grant permissions.

## New implementation

### `star/resource_admission.py`

A dependency-free, deterministic policy with typed inputs and decisions.

- `ResourceSnapshot`: monotonic timestamp, CPU utilization, available RAM/VRAM, GPU utilization, game FPS, audio underruns, and OBS dropped/total frames.
- `WorkloadRequest`: host-assigned workload kind and estimated incremental CPU/RAM/VRAM/GPU demand.
- `AdmissionPolicy.evaluate()`: returns `ALLOW`, `DEFER`, or `PROTECTED` with a stable reason code.
- Protected work is routed to a separate scheduler lane; it is not counted as a background admission.
- Unknown GPU telemetry blocks GPU-demanding background work.
- Stale or future-dated snapshots fail closed.
- Any audio underrun in the sample window defers background work.
- OBS drops above the configured rate defer background work; a short sample with drops is treated conservatively.
- Active-game FPS must be present and above the configured floor before background work is admitted.
- Estimated workload demand is added to current CPU/GPU utilization and subtracted from free memory before admission.
- Policy thresholds are configurable; defaults are conservative starting points, not hardware-derived truths.

### Deliberate boundaries

- The host must sample metrics using one monotonic clock and provide a bounded sample window.
- Workload estimates must be calibrated from measured STAR jobs; a guessed estimate can make admission unsafe.
- `WorkloadKind` must be assigned by trusted host code. Viewer/chat/ASR/OCR/game text must never choose its own priority or protected class.
- `PROTECTED` means “send to the protected scheduler lane,” not “unlimited resources.” The foreground lane still needs its own bounded queues, cancellation and process-level safeguards.
- The module does not stop a job already running if resources deteriorate. A future supervisor must add preemption/checkpoint rules and must never preempt audio callbacks, TTS playback, game input, or OBS capture.
- No live hardware telemetry is fabricated by this module.

## Admission policy defaults

The initial values are safety-oriented defaults to be measured and tuned on each machine:

| Signal | Default guard | Reason |
|---|---:|---|
| Snapshot age | 3 seconds maximum | Stale telemetry must not authorize new load |
| Future timestamp tolerance | 250 ms | Reject clock-domain mistakes |
| CPU after estimated work | <= 82% | Keep host/streaming headroom |
| Free RAM after estimated work | >= 2,048 MB | Preserve OS and application headroom |
| Free VRAM after estimated work | >= 1,536 MB | Avoid consuming the final graphics reserve |
| GPU after estimated work | <= 82% | Avoid saturating rendering/inference |
| Active-game FPS | >= 55 FPS | Defer optional work when game smoothness is already low |
| Audio underruns | 0 in sample window | Audio quality takes priority |
| OBS dropped-frame rate | <= 1% | Protect stream output |

These are not universal values. Calibrate with 5–10 minute representative mixed-load runs on the actual machine. Record the 95th percentile, not just the average. The 8 GB RTX 4060 target is especially sensitive to model residency, game texture allocation, OBS encoder choice, avatar rendering, and transient VRAM spikes.

## Current research findings

### 1. Dual-loop, full-duplex interaction

**Realtime-Venus: A full-duplex interaction system with asynchronous delegation** (arXiv:2609.13814, 2026-09-12) describes a live interaction loop that continuously perceives and controls turn-taking while a separate capability loop executes delegated work. Delegations capture the evidence/context boundary at request time; returned results are checked for freshness and delivered only when the live conversation can accept them.

STAR should adopt the runtime pattern, not assume the paper's 9B models fit its local GPU. The architectural lesson is to keep the Social/Voice frontend small and responsive while specialist workers handle longer tasks.

Source: https://arxiv.org/abs/2609.13814

### 2. Streaming ASR with speaker attribution

Microsoft's **VibeVoice-ASR-Streaming Technical Report** (2026-09) describes chunked streaming recognition with look-ahead and prior-text context, producing speaker-attributed transcripts. Its 1.5B and 7B model variants are useful candidates for a controlled evaluation.

STAR must keep low-latency VAD/barge-in separate from chunk-finalized transcript delivery. Provisional partial text must not be treated as a final user request, queued task, or tool instruction. Compare the 1.5B model, a CPU recognizer, and the existing pipeline under simultaneous game/OBS load before choosing a deployment.

Source: https://www.microsoft.com/en-us/research/publication/vibevoice-asr-streaming-technical-report/

### 3. Multi-party turn-taking is still hard

**MP-Bench** (Findings of EMNLP 2026) reports that evaluated real-time voice agents reached at most 22% on multi-party comprehension, with turn-taking near chance. **Full-Duplex-Bench v3** evaluates human-recorded spoken requests, disfluencies, chained tool calls, response latency, and turn-taking.

STAR therefore needs a session timeline with:
- temporary speaker IDs;
- diarization confidence and unknown-speaker handling;
- intended addressee;
- overlap and interruption boundaries;
- backchannel vs. floor-taking classification;
- current response/playback state;
- explicit “continue / yield / stop / revise / delegate” actions.

Never infer that every utterance is directed at STAR. Do not build permanent voiceprints for ordinary stream participation.

Sources:
- https://www.fullduplex.ai/benchmarks/mp-bench
- https://www.full-duplex.ai/benchmarks/fdb-v3

### 4. Local inference optimization

The current llama.cpp server documents CPU/GPU inference, parallel decoding, continuous batching, monitoring endpoints, schema-constrained outputs, speculative decoding, and prompt/KV-prefix reuse. Its SPEED-Bench client compares per-category latency/throughput and speculative-draft acceptance.

Recommended sequence:
1. Establish an unchanged baseline for the exact model, quantization, context, prompt, backend, and concurrency.
2. Measure prompt processing, time-to-first-token, decode tokens/sec, p50/p95 request latency, peak RAM/VRAM, and output quality.
3. Test prefix caching with a stable system prefix and variable user suffix.
4. Test continuous batching only when concurrent requests justify it; one interactive user may not benefit from more parallel slots.
5. Test speculative decoding only with a compatible draft/model pair and record acceptance rate plus quality.
6. Test CPU/GPU layer split and KV-cache types independently.
7. Keep the winning configuration only if it improves end-to-end latency without reducing task accuracy or destabilizing the game.

Do not blindly turn on every optimization. Some options increase VRAM, latency variance, or nondeterminism.

Sources:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- https://github.com/vllm-project/vllm

### 5. Memory must improve actions, not just recall

**MemoryArena** (2026-02-18) evaluates memory inside interdependent multi-session agent tasks. Its key lesson is that strong fact recall does not guarantee that an agent uses earlier experience correctly in a later action.

STAR's memory evaluation should test:
- capture of useful experiences;
- retrieval at the right time;
- correct action parameter grounding;
- conflict resolution when facts change;
- stale-memory avoidance;
- provenance and confidence;
- user-requested forgetting/deletion;
- measurable improvement on held-out tasks.

Store event summaries and evidence references rather than entire streams. Keep transient chat/audio data out of long-term memory unless an explicit, separate policy allows it.

Source: https://arxiv.org/abs/2602.16313

### 6. Roblox and complete game creation

**OpenGameEval** (Roblox, 2026-10-01) evaluates agents inside reproducible Roblox Studio sessions and checks both edited scenes and simulated Play sessions. It reports that inspecting all relevant objects before acting correlates with higher success: +13.4 percentage points on scene-only tasks and +9.8 points on script-only tasks in its comparison.

**GameDevBench** (ICML 2026) contains 333 Godot game-development tasks across gameplay, UI, 2D and 3D graphics/animation. It shows that visual feedback materially improves agent performance, while graphics-focused work remains difficult.

STAR's Creator Brain should therefore use a strict loop:
1. inspect hierarchy, scripts, assets, properties, and references;
2. plan a minimal diff;
3. edit in an isolated test place/project;
4. run static analyzers and unit tests;
5. launch Play mode;
6. capture screenshots/video and runtime logs;
7. compare against acceptance criteria;
8. repair only observed failures;
9. save/reload and retest;
10. promote only with reproducible evidence.

STAR's Gamer Brain must be evaluated separately from Creator Brain. Use safe sandboxed games and held-out maps/seeds. Measure objective completion, deaths/failures, time, resource efficiency, rule compliance, and transfer to unseen scenarios. Do not use unauthorized input automation in competitive games or bypass anti-cheat.

Sources:
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval
- https://github.com/waynchi/gamedevbench

### 7. General game-playing agents: SIMA 2 and GameWorld

Google DeepMind's **SIMA 2** demonstrates a generalist agent that combines visual observations, language instructions, high-level reasoning, and ordinary game controls across multiple 3D worlds. The published discussion is also unusually candid about remaining weaknesses: very long-horizon tasks, short interaction memory, precise low-level controls, and robust visual understanding remain difficult. Its self-improvement direction—generate tasks, attempt them, and evaluate outcomes—is useful as a design pattern, but STAR should keep skill promotion behind held-out evaluation rather than accepting self-reported success.

**GameWorld** provides a complementary, verifiable benchmark: 34 browser games and 170 tasks across runner, arcade, platformer, puzzle, and simulation genres. It compares computer-use actions with semantic actions and evaluates serialized game state rather than relying only on an LLM judge. This is a useful low-risk first environment for STAR's Gamer Brain before adding game-specific adapters for Roblox or Minecraft.

STAR's game agent should use a hierarchical controller:
- a fast control loop for movement, camera, aiming, timing, and immediate hazards;
- a slower strategic loop for goals, maps, inventory, resource planning, and team coordination;
- a skill memory containing preconditions, action sequences, expected effects, and failure conditions;
- a verifier that checks state changes and task completion;
- a practice harness that tests skills on held-out maps, seeds, and difficulty settings.

Do not treat a successful run on one fixed map as general mastery. Measure completion rate, progress, deaths/failures, time, resource efficiency, recovery after mistakes, and transfer to unseen environments. Keep computer input restricted to explicit, permitted game sessions; never bypass anti-cheat or automate prohibited competitive play.

Sources:
- https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- https://gameworld-bench.github.io/
- https://arxiv.org/abs/2604.07429

### 7. VTuber and broadcast integration

VTube Studio's public WebSocket API can feed Live2D parameters, trigger hotkeys, load items, and subscribe to events. The plugin must request user approval; access can be revoked. Use a local-only connection by default and store its token in the OS credential store, not source code.

OBS WebSocket is included with OBS 28+. Its maintainers recommend password protection. Keep the endpoint local, require authentication, and never expose it to the public internet.

Twitch EventSub WebSocket sends a welcome event, requires subscriptions against the returned session ID, can redeliver notifications with the same message ID, and provides a reconnect URL that should be used as-is. If the connection is lost rather than gracefully reconnected, messages may be missed. YouTube LiveChat `streamList` offers server-streamed low-latency chat; handle resume tokens and initial history without replaying old messages as new.

For a natural stream, use actual playback acknowledgements as the authority for mouth movement, captions, and “already said” history. When audio is cancelled, trim unplayed text from the conversation state. Keep a Social Director responsible for timing, addressee, humor, backchannels, and silence; the avatar renderer should only express the selected state.

Sources:
- https://github.com/DenchiSoft/VTubeStudio
- https://github.com/obsproject/obs-websocket
- https://dev.twitch.tv/docs/eventsub/handling-websocket-events
- https://dev.twitch.tv/docs/eventsub/websocket-reference/
- https://developers.google.com/youtube/v3/live/docs/liveChatMessages/streamList

## Capability roadmap

| Brain/system | Near-term measurable work | Long-term capability |
|---|---|---|
| Social Director | MP-Bench-style addressee/turn-taking tests | Multi-person live conversation without constant interruption |
| Voice | Streaming ASR, VAD, playback clock, cancellation | Low-latency full-duplex speech |
| Stream Host | Twitch/YouTube adapters with dedupe/reconnect | Multi-platform community participation |
| Avatar | VTube Studio parameter/hotkey adapter | Playback-synchronized expressions, gestures, idle behaviors |
| Broadcast | Authenticated OBS status/control adapter | Stream health, scene workflows, clips and recap |
| Gamer | Screen/state observation, safe input adapter, task goals | Practice, skill library, strategy transfer |
| Creator | Roblox Studio inspection/build/playtest loop | Complete game production across Roblox/Godot/Blender |
| Knowledge | Source-grounded retrieval and contradiction checks | Broad general research with provenance and freshness |
| Memory | MemoryArena-style memory-to-action tests | Reliable long-term project and experience memory |
| Autonomy | Leased workers, checkpointing, resource admission | Recoverable background projects and self-directed practice |

## Mixed-load acceptance matrix

Every change that touches inference, audio, avatar, or game automation should be tested under these conditions:

- idle baseline;
- game only;
- OBS + avatar only;
- voice only;
- game + OBS + avatar;
- game + OBS + avatar + voice;
- game + OBS + avatar + voice + one background CPU task;
- same plus one GPU task (only when admitted);
- stress/thermal soak for at least 30 minutes.

Record:
- game FPS and 1% low/frame-time p95;
- OBS render and output dropped-frame rates;
- audio underruns and output-device latency;
- VAD endpoint-to-first-audio latency;
- ASR finalization latency and WER;
- LLM TTFT and decode tokens/sec;
- peak CPU, RAM, VRAM and GPU utilization;
- task completion and evidence pass rate;
- user-perceived turn-taking errors.

Do not report a speedup from token/sec alone. A configuration that produces more tokens but increases first audible response, frame drops, or audio glitches is a regression for a live VTuber.

## Safety and identity requirements

“Human-like” should mean natural timing, expressive delivery, continuity, humor, contextual memory, and useful initiative—not pretending to be a human. STAR should be transparent that she is an AI character, respect platform rules, and avoid deceptive claims about real-world experiences or emotions.

Viewer text, ASR, OCR, game chat, and web pages are untrusted input. They cannot grant tool permissions, authorize purchases, publish content, or change the owner's safety settings. Use per-source consent, rate limits, moderation, session-scoped IDs, and a kill switch. High-impact external actions remain owner-approved.

## Implementation status

Implemented in this branch:
- pure typed resource snapshot and workload request;
- conservative admission decision with protected-lane routing;
- stale/future sample rejection;
- audio-underrun and OBS-drop guardrails;
- active-game FPS guard;
- CPU/RAM/VRAM/GPU headroom checks;
- configurable thresholds;
- focused regression tests.

Not implemented by this branch:
- Windows hardware telemetry collection;
- a desktop worker supervisor or preemption;
- model routing or inference-engine changes;
- ASR/diarization provider installation;
- Twitch/YouTube clients;
- VTube Studio/OBS connections;
- gameplay input or game-learning agents;
- automatic training or self-modification.

The policy is intentionally not wired into runtime defaults. GitHub Actions and hardware acceptance tests must pass before integration.
