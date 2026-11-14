# STAR Resource Admission, Dual-Loop Runtime, and Capability Evaluation Research

**Date:** 2026-11-13  
**Branch:** `feat/resource-admission-20261113-run21`  
**Status:** Research only. The experimental `star/resource_admission.py` policy and its tests were removed from this branch after a repository audit found an existing lease-based scheduler and composed runtime in #1140/#1142. Do not merge a second ALLOW/DEFER authority.

## Executive recommendation

STAR should use a **two-loop runtime**:

1. **Protected interaction loop:** microphone/audio callbacks, TTS playback, foreground conversation, game input, and OBS capture/encoding. This loop must remain responsive and must not wait on background research, model training, asset generation, or database work.
2. **Capability loop:** background reasoning, research, code generation, image/video generation, indexing, practice, and specialist agents. Work enters this loop only when the host has fresh telemetry and enough resource headroom.

This architecture is supported by the September 2026 Realtime-Venus paper, which separates continuous interaction from asynchronous capability execution and binds delegated work to the originating session and its evidence snapshot. The paper also reports that routing itself remains imperfect; STAR must evaluate both unnecessary delegation and missed delegation, not assume a model always chooses correctly.

This document does not add or retain a second scheduler. Use #1140's lease-based controller and #1142's composed stream-pressure runtime as the sole admission authority. If the #1178 telemetry thresholds are useful, translate them into host-health signals and calibrated ResourceVector estimates at that single entry point.

## Consolidation decision

A repository audit found that #1140 already supplies the authoritative multi-resource scheduler and #1142 composes it with the stream-pressure governor. Those components already provide bounded queues, priority ordering, protected reserves, leases, host-confirmed release, freshness checks, and recovery hysteresis.

The experimental #1178 policy was removed from this branch because a second stateless ALLOW/DEFER decision could race with the lease-based controller: two callers could evaluate the same snapshot and both admit work without reserving resources. Its initial CPU/GPU percentages and RAM/VRAM floors were also heuristics, not calibrated reservations.

Decision:
- Keep #1140 as the sole resource-allocation and lease authority.
- Keep #1142 as the sole composed stream/game admission entry point.
- Feed fresh, coherent host telemetry into that path; do not create another admission API.
- Serialize decisions in one trusted supervisor and release leases only after confirmed worker termination.
- Treat missing or stale telemetry as degraded health for optional workloads.
- Calibrate resource vectors from repeated per-process measurements on the actual Windows target, not from generic percentage thresholds.
- Preserve distinct real-time audio/game/avatar lanes, interactive chat/tool lanes, and deferrable background learning/research lanes.

The deleted prototype's tests were specific to the removed policy and are not part of the final PR. This research document remains as a design audit and integration guide.

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

**τ-Voice** (ICML 2026) complements these benchmarks by testing grounded, multi-turn tasks under realistic audio. Its 278-task evaluation reports a substantial gap between text and voice-agent task completion, especially with noise and diverse accents. STAR should therefore score both conversation quality and whether the requested task was actually completed; a fluent response is not proof of correct execution.

Source: https://proceedings.mlr.press/v306/ray26a.html

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

#### Pipeline-aware voice routing: PAVO

**PAVO: Pipeline-Aware Voice Orchestration** (TMLR 2026) treats ASR → LLM → TTS as one coupled pipeline rather than optimizing each stage independently. Its research highlights error propagation: a low-quality transcript can push downstream factual accuracy over a cliff, so the cheapest ASR choice is not always the fastest successful end-to-end choice.

Important provenance caveat: the public PAVO repository distinguishes direct H100/M3 measurements from a 50K-turn routing simulation. Some headline aggregate results are manuscript-level and do not have a standalone raw trace in the repository. The released wrapper also documents that its 48 action indices do not map to deployable stage tuples and that route() fails rather than inventing a mapping. STAR should borrow the evaluation method and quality-coupling idea, not blindly install the controller or repeat its headline numbers as STAR results.

For STAR, first define a small set of real, measured profiles for ASR, reasoning, and TTS (local CPU, local GPU, and explicitly enabled remote provider). Route only among profiles whose quality and latency have been measured on the target hardware. If ASR confidence is low, ask for repetition or escalate to a stronger recognizer rather than allowing a weak transcript to drive a high-impact action.

Sources:
- https://github.com/vnmoorthy/pavo-bench
- https://openreview.net/pdf/6896e13d57a1fb9a543c388831c7f7c6fd18f97c.pdf

#### Distributed inference research: OServe

OServe (ICML 2026) studies workload-aware placement and switching across heterogeneous multi-device serving systems, reporting up to 2× and 1.5× average improvements in its evaluated deployment. This is a possible direction for STAR's separate Linux worker/server, not a claim that the system will accelerate a single 8 GB Windows GPU. Use it only after the local/remote split has clear network-latency, queueing, privacy, and failure-recovery measurements.

Source: https://proceedings.mlr.press/v306/jiang26k.html

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

## Additional inference finding: upstream llama.cpp MoE expert cache

Primary source: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

The current upstream llama.cpp documentation describes a MoE cache for models whose expert weights remain in host memory. Frequently used experts can be retained in device memory for small-batch decode/speculative workloads. The documented controls include:
- `--moe-cache-mib`: a bounded device-memory cache budget;
- `--moe-cache-cpu-share`: a share of cache misses computed on CPU rather than uploaded to the GPU.

The documentation notes that cache hits run on device, while cache misses can be split between CPU compute and GPU uploads. It describes this as beneficial when host-memory reads/CPU execution can beat the cost of transferring missing experts, depending on RAM and PCIe behavior.

**STAR applicability:** this is a promising candidate only for compatible Mixture-of-Experts models with experts actually offloaded to host memory. It does not accelerate dense models and is not a universal switch. It may help decode if repeated expert transfers are the bottleneck; it may hurt if the CPU is weak, memory bandwidth is constrained, or the GPU is already busy rendering the game.

**Required experiment before adoption:**
1. Confirm the selected checkpoint is MoE and inspect the exact layer/offload configuration.
2. Pin the upstream llama.cpp commit and record build/backend flags.
3. Compare cache disabled vs several bounded cache budgets and CPU-share settings.
4. Run identical prompt sets at the same context, concurrency, batch, and output length.
5. Measure prefill, decode tokens/s, first audible audio, process VRAM, host RAM, CPU utilization, PCIe/copy activity where available, game frame-time p95/p99, audio underruns, and held-out answer/tool quality.
6. Reject the candidate if it improves isolated decode but worsens mixed-load stream responsiveness or task quality.

Do not add a fork-specific MoE cache patch or set a production default based on a README benchmark. The upstream documented feature and any third-party fork implementation must be treated as separate artifacts.

## Safety and identity requirements

“Human-like” should mean natural timing, expressive delivery, continuity, humor, contextual memory, and useful initiative—not pretending to be a human. STAR should be transparent that she is an AI character, respect platform rules, and avoid deceptive claims about real-world experiences or emotions.

Viewer text, ASR, OCR, game chat, and web pages are untrusted input. They cannot grant tool permissions, authorize purchases, publish content, or change the owner's safety settings. Use per-source consent, rate limits, moderation, session-scoped IDs, and a kill switch. High-impact external actions remain owner-approved.

## Implementation status

This PR branch is research-only after the scheduler consolidation review.

Removed from this branch:
- `star/resource_admission.py`
- `tests/test_resource_admission.py`

Existing authoritative implementation to integrate and verify:
- #1140: lease-based multi-resource workload admission.
- #1142: stream-pressure governor composed with that admission controller.

Not implemented by this research:
- Windows hardware telemetry collection or calibration;
- desktop supervisor integration beyond the existing #1142 path;
- model routing or inference-engine changes;
- ASR/diarization provider installation;
- Twitch/YouTube clients;
- VTube Studio/OBS connections;
- gameplay input or game-learning agents;
- automatic training or self-modification.

The branch does not change production behavior, model weights, defaults, permissions, installers, or releases. Exact-head GitHub Actions and hardware acceptance remain separate gates.
