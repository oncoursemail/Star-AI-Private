# STAR 2026-11-13 — Host Runtime, Human-Feeling VTuber, Gamer, Creator, and Intelligence Roadmap

**Research date:** 2026-11-13  
**Repository baseline inspected:** `main` / STAR v1.0.0 release notes  
**Purpose:** turn STAR's existing chat, voice, model-routing, Roblox, and learning foundations into one measured realtime system  
**Status:** architecture and implementation plan; no live devices, models, games, or broadcast controls were started in this research pass

## Executive assessment

STAR already has meaningful foundations, but the public v1.0 product must be distinguished from open development work.

The v1.0 README describes a Windows 11 local-first chat application with a local 4B Vulkan model, optional CPU-only STAR Server, deterministic model routing, opt-in Roblox Studio MCP, image generation, web search, and server-side night school. It describes basic voice calls as existing, while a richer streaming/VTuber experience and Studio Lab are still marked coming soon. The release notes explicitly say that a passing test or open PR does not mean a feature is in the installer.

The current source also has useful building blocks:
- `star/voice/runtime.py` loads and warms VAD, endpointer, ASR, and TTS engines once per runtime.
- `star/voice/bridge.py` exposes a bounded desktop action/event contract and requires microphone consent before a call.
- `star/voice/call.py` handles speech turns, streamed brain output, sentence chunking, TTS, playback, and barge-in.
- `star/voice/turn.py` separates speech detection, pauses, end-of-turn decisions, and interruption thresholds.
- `star/voice/metrics.py` records per-turn stage timings.
- `star/brain_router.py` provides deterministic, zero-extra-inference routing and keeps alternatives on the same configured provider/endpoint.
- `star/inference_benchmark.py` performs real, explicit local/server probes, but its current probe is deliberately small and does not yet characterize the complete live stream workload.
- Existing release documentation describes opt-in Studio MCP, worked-example retrieval, specialist agents, and idle-time paired learning.

The biggest gap is not a lack of proposed subsystems. It is the **host integration gap**: several recent development PRs add carefully bounded policy and evaluation objects, but the trusted Windows host still has to collect real measurements, supervise real processes, connect those policies to real devices, and prove the integrated behavior.

Do not add a second voice stack, second scheduler, second memory database, or a second VTube control loop. Compose the existing components through one host-owned runtime.

## 1. Target architecture: one coordinator, several deadline classes

Use one long-lived `StarRuntime` (name is conceptual until the implementation is reviewed) with explicit lifecycle, health, cancellation, and ownership boundaries.

### Realtime lanes

1. **Audio I/O:** microphone capture, device health, mute state, output playback, and immediate stop.
2. **Turn detection:** VAD, endpointing, partial/final ASR, backchannel filtering, and barge-in.
3. **Fast response:** short acknowledgements, stream reactions, and concise answers with strict time/token budgets.
4. **Avatar output:** playback-clock-driven mouth/face state and a bounded latest-wins parameter sender.
5. **Game control:** low-latency input policy and emergency stop; never wait for a large language-model call per frame.

### Deferred lanes

6. **Strategic reasoning:** longer plans, explanation, game strategy, and multi-step tool decisions.
7. **Research and retrieval:** web/document search, source verification, summarization, and knowledge refresh.
8. **Creation:** Roblox/Blender/Godot/Unity/Unreal work, asset generation, builds, and playtests.
9. **Learning:** offline practice, replay analysis, skill proposals, benchmark runs, and model experiments.
10. **Memory consolidation:** summarize approved experiences, resolve temporal conflicts, expire stale data, and produce bounded retrieval indexes.

The existing resource-aware admission work is the right policy direction. The trusted host must be the only component that turns an admitted lease into an OS process or device action. A policy object is not a process supervisor, and a successful queue admission is not proof that a worker started or stopped.

### Runtime invariants

- Audio capture/playback, avatar synchronization, and emergency game stop must not wait behind research or asset-generation queues.
- Every long-running operation has a deadline, cancellation token, bounded output, and explicit final state.
- A resource lease remains reserved until the host confirms the worker has stopped.
- Unknown hardware readings stay unknown; never convert missing VRAM to zero.
- All child workers are tied to a stable process identity, start token, configuration fingerprint, and host epoch.
- A crash or device disconnect moves the affected lane to a known degraded state; it must not silently start a different provider or send private prompts elsewhere.
- The runtime exposes aggregate diagnostics, not prompts, transcripts, viewer identities, API keys, or raw media.

## 2. Make STAR feel natural on stream

“Human-like” here means natural timing, expressive behavior, conversational continuity, and context-appropriate reactions. It must not mean claiming that STAR is a human being or concealing that she is an AI character.

### Conversation floor and turn-taking

Build on the existing VAD/endpointer/ASR/CallSession path. Do not bolt on a parallel voice agent.

Research-backed behaviors to implement and evaluate:
- Adaptive interruption detection that distinguishes a real barge-in from a brief “mm-hmm,” laughter, cough, or speech directed at another person.
- False-interruption recovery: if speech was detected but no meaningful transcript follows, resume only the unheard remainder of the interrupted sentence.
- Partial-transcript precomputation with revision invalidation: speculative work may begin on a stable prefix, but a corrected transcript must cancel every result derived from the superseded text.
- Short acknowledgement policy: backchannels should not always cancel STAR's speech or trigger a full answer.
- Dynamic endpointing: use phrase completion and pause statistics rather than one fixed silence threshold.
- Playback-grounded history: only audio that was actually played should be committed as heard assistant speech.
- Queue-aware speech: a new answer must not be spoken after its request was cancelled or its context has become stale.
- Explicit “thinking / listening / speaking / interrupted / recovering” states shared by the UI, avatar, and voice runtime.

LiveKit's turn-taking documentation is useful as a design reference for VAD, model-based end-of-turn detection, adaptive interruption, preemptive generation, and false-interruption recovery. STAR should borrow the behavior and test methodology, not adopt a new framework wholesale without a dependency and latency review.

### Personality and social behavior

Use a small, versioned persona specification plus live context, not an ever-growing prompt.

The persona layer should define:
- Stable voice, humor, warmth, boundaries, and conversational style.
- A compact current-stream state: current game, objective, recent event, current topic, current emotional tone, and unfinished thought.
- A short audience context window for the current stream.
- A small set of expressive response patterns (curious, amused, surprised, focused, frustrated-but-composed, proud, confused, relieved).
- Natural variation in sentence length and acknowledgement timing.
- A “do not speak” decision when a viewer-to-viewer conversation does not require STAR.
- A recovery style for mistakes: acknowledge, correct, continue; do not invent confidence.

Do not create permanent viewer dossiers by default. Keep audience context ephemeral and session-scoped. Any cross-stream viewer memory must be separately opt-in, purpose-limited, inspectable, and deletable.

### Human-feeling speech

Evaluate more than voice similarity:
- First audible latency and interruption stop latency.
- Prosody and phrase-boundary naturalness.
- Pronunciation of names, game terms, acronyms, and user-defined words.
- Loudness consistency and clipping.
- Whisper/quiet voice control when explicitly requested.
- Laugh and reaction timing.
- Repetition rate and filler-word overuse.
- Whether the spoken response matches the text and actual stream event.

A speech model should not be asked to improvise emotional audio that contradicts the words or the avatar state. Prefer a small, controlled expressive speech layer with measured styles over uncontrolled voice changes.

## 3. Avatar and broadcast integration

### VTube Studio

The official VTube Studio API supports a local WebSocket plugin interface, authentication approved by the user inside VTube Studio, hotkeys, model/parameter access, event notifications, and feeding parameter values. Use the official protocol as the contract.

Recommended adapter:
- One authenticated local connection manager.
- Persist the token only in the OS credential store; never in settings JSON, logs, crash reports, or model context.
- Request the minimum permissions needed.
- Discover the loaded model and supported parameters at session start.
- Map semantic avatar intents to existing model parameter IDs and hotkeys.
- Coalesce stale parameter frames; do not queue a FIFO of old face positions.
- Drive mouth movement from the audio playback clock, not generated text or TTS synthesis completion.
- Drive expressions from the same event timeline as conversation/game events.
- On disconnect, stop sending, preserve the last safe neutral state, and reconnect with bounded backoff.
- Keep tracking input and STAR-authored expression output separate so STAR does not fight the face tracker.

### OBS

Use the official obs-websocket protocol (OBS 28+ includes it). Require authentication and default to loopback/local-only connections.

Start with a narrow command allowlist:
- Read stream/recording status.
- Read scene and source status.
- Switch only among owner-approved scenes.
- Toggle only owner-approved sources.
- Read render/output health counters where supported.
- Never expose arbitrary OBS request names as model tools.

A “go live” or “end stream” operation should remain a distinct owner-controlled action. Routine scene/status operations can be automated only after explicit setup and visible status.

### Shared event clock

Every event should carry:
- monotonic timestamp and source epoch;
- stream-session ID (opaque);
- conversation turn ID (opaque);
- playback segment/generation ID (opaque);
- semantic event type;
- confidence/quality flag;
- cancellation/revision generation.

This is how STAR avoids avatar/audio/gameplay desynchronization and prevents late events from an earlier turn from changing the current face.

## 4. Gamer: learn mechanics, not just describe them

Use a dual-rate controller.

### Fast control loop

The fast loop should use deterministic state machines, simple learned policies, and direct game feedback:
- movement and camera control;
- aiming and interaction;
- dodge/jump/timing windows;
- menu navigation;
- immediate hazard avoidance;
- input release and stop handling.

Do not call the large reasoning model on every frame. The model is too slow and expensive for high-frequency control, and long reasoning can make a reactive agent worse.

### Strategic loop

The slower loop handles:
- objective decomposition;
- map/route planning;
- resource and inventory planning;
- enemy/player strategy;
- team coordination;
- learning a new mechanic;
- deciding when to practice, retreat, or ask for help.

It emits bounded goals to the fast controller, then checks actual game-state progress.

### Skill learning cycle

1. Observe a game/version and establish a baseline.
2. Identify one small mechanic or objective.
3. Generate a curriculum from easy to difficult situations.
4. Practice in a private/sandboxed environment.
5. Record only structured state/action/outcome evidence.
6. Diagnose failure using actual game state where available.
7. Produce a versioned skill artifact with preconditions, action policy, expected outcome, and failure modes.
8. Validate on held-out maps, seeds, or scenarios.
9. Compare against the prior skill version.
10. Promote only after the independent evaluator passes; keep rollback.

A skill should include game ID/version, objective ID, environment assumptions, controller version, evidence digest, training/holdout split, success rate, failure rate, latency, and confidence. Never treat the LLM's own “I learned it” statement as evidence.

### Cross-game transfer

Store reusable concepts (navigation, aiming, timing, inventory planning, resource gathering, map reading) separately from game-specific controls. A skill transfers only after it passes a new game's held-out test. SIMA 2 and Voyager are useful research precedents for multi-world instruction following, self-directed practice, executable skill libraries, and transfer—but their published results are not STAR performance claims.

### Safety and fairness

- Use private test worlds and approved games first.
- Respect game terms, anti-cheat, rate limits, and other players.
- Do not implement anti-cheat bypass, exploit automation, account abuse, or unattended competitive matchmaking.
- Keep a physical/keyboard emergency stop and an obvious pause state.
- Do not allow untrusted chat messages to become raw game commands.
- Separate gameplay control from publishing, purchases, account changes, and moderation powers.

## 5. Creator: finish playable games

The strongest game-development loop is inspect → plan → edit → build → play → observe → repair → verify.

For Roblox:
- Prefer the official Studio MCP integration already documented in the v1.0 roadmap.
- Always target an explicit `studio_id`; never assume the focused Studio window is the intended project.
- Inspect the hierarchy and referenced scripts before editing.
- Keep changes in an unpublished test place or isolated copy.
- Run Luau analysis/formatting and project preflight.
- Use playtest scenarios with deterministic setup and expected state.
- Capture screenshots/video only when the test harness explicitly authorizes it.
- Verify multiplayer/server-client behavior, not only local appearance.
- Complete objectives and test save/reopen behavior before claiming a game is finished.

Roblox's current Studio MCP documentation describes model exploration, script reading/editing, Luau execution, playtesting, multiple Studio instances with explicit IDs, and Open Cloud actions subject to per-game permissions. This is a strong path for STAR's Studio Lab, but the user must connect only trusted clients and keep write/publish scopes distinct.

For Godot and other engines, use GameDevBench as a source of task categories and evaluation methodology: gameplay logic, UI, 2D/3D graphics, animation, and visual feedback. Its 333-task benchmark demonstrates that game development is multimodal and that code-only checks miss important failures.

### Game completion gate

A project is not “done” because code compiles. The acceptance report should show:
- project opens from a clean checkout;
- build succeeds;
- launch succeeds;
- core loop can be played;
- each required objective can be completed;
- no blocker/crash in the smoke suite;
- save/reload works if persistence exists;
- UI is checked at target resolutions;
- assets are present and licensed;
- performance is within the target budget;
- all known limitations are listed.

## 6. General knowledge and research intelligence

Build a source-grounded knowledge pipeline, not a giant unqualified memory dump.

Each knowledge item should contain:
- claim or answer;
- source URL and publisher;
- source publication/update date;
- retrieval date;
- source type and authority;
- quoted evidence span or exact section reference;
- confidence and unresolved conflicts;
- expiry/recheck policy;
- topic tags and related claims.

Use authority by domain: official documentation/specifications for APIs and product behavior; peer-reviewed papers or original preprints for research claims; primary datasets and code for benchmarks; reputable secondary reporting only for context.

For time-sensitive claims, require a current source and show the “as of” date. When sources disagree, preserve the conflict rather than averaging it away. Do not allow model-generated summaries to become their own sources.

A useful research workflow is:
1. Clarify the question and freshness requirement.
2. Retrieve primary sources.
3. Extract claims and evidence.
4. Cross-check important claims independently.
5. Separate measured results from author-reported results and hypotheses.
6. Produce a concise answer with citations.
7. Save only reusable, source-backed facts.
8. Schedule revalidation for fast-changing technical facts.

## 7. Memory that changes future actions

Use distinct memory types with different retention rules:
- **Working:** current turn/task only.
- **Episodic:** approved experience summaries.
- **Semantic:** source-backed facts.
- **Procedural:** verified reusable skills.
- **Project:** repository decisions, constraints, milestones, and artifacts.
- **Social:** session context by default; persistent viewer context only with explicit consent.

The key evaluation is not “can STAR repeat the memory?” It is “does the memory improve the next task without causing a stale or irrelevant action?”

Mem2ActBench is a useful precedent because it evaluates whether agents use prior interactions to choose tools and ground action parameters, not just retrieve facts. Pair it with no-memory controls, temporal-update tasks, forgetting tests, and procedural transfer.

Forgetting is a feature: expire time-sensitive facts, supersede obsolete project decisions, and never reuse information that has been explicitly deleted or revoked.

## 8. Faster local intelligence: benchmark before changing defaults

STAR's existing `inference_benchmark.py` is a useful starting point, but the next benchmark should characterize a mixed stream workload.

### Measure separately

- model cold-load time;
- warm time-to-first-token (TTFT);
- time-per-output-token (TPOT);
- end-to-end completion latency;
- first audible latency;
- cancellation-to-silence latency;
- queue wait and slot wait;
- prompt tokens and output tokens;
- cache hit/reuse counts;
- output tokens per second and aggregate throughput;
- p50/p95/p99 per-turn latency;
- peak CPU, RAM, local VRAM, and non-local GPU memory;
- game frame-time p95/p99;
- audio underruns;
- OBS render skips and output skips.

Do not subtract unrelated percentiles. Pair each baseline and candidate on the same request, host, game scene, stream state, and model context. Run both idle and mixed-load suites.

### Inference experiments, in order

1. **Prompt stability:** keep the system prefix and tool schema stable; avoid needless prompt churn.
2. **Context budgeting:** retrieve only relevant history; summarize old turns with source pointers; avoid sending the entire project every turn.
3. **KV/prefix reuse:** measure actual cache reuse and memory cost. Prefix caching mostly avoids repeated prefill; it does not automatically speed decode.
4. **Continuous batching/slots:** test one, two, and higher concurrency levels only if memory allows. Match benchmark concurrency to server slots.
5. **Speculative decoding:** compare no speculation, native MTP where supported, and a draft model only when its extra memory is justified.
6. **Quantization:** compare quality, tool-call correctness, memory, TTFT, and TPOT; do not select solely by tokens/second.
7. **CPU/GPU split:** test Vulkan/CPU offload and thread/affinity settings with a concurrent game/OBS/audio load.
8. **Model routing:** route short reactions to the fast model, complex planning/coding to the stronger model, and perception to a vision-capable model only when needed. Keep every route on the configured provider/endpoint unless the owner explicitly opts into a different provider.
9. **Model residency:** prefer one warm model on the constrained 8 GB GPU; load larger specialists on the server or on demand if the measured load penalty is acceptable.
10. **Speculation admission:** pause optional speculative work when audio, game frame time, OBS output, or memory headroom degrades.

### Model candidates

Qwen3.5-4B/9B and Granite 4.2-8B are candidates to test, not automatic replacements. Pin immutable model revision, file hashes, quantization, tokenizer/chat template, backend build, GPU offload, KV-cache type, context length, reasoning mode, and tool parser. Run the same held-out STAR tasks and mixed-load stream tests for each.

Qwen3.5's native multi-token prediction is worth an isolated vLLM/SGLang experiment because it may avoid a separate draft model. It is not a drop-in speed switch for STAR's current llama.cpp/Vulkan setup: confirm exact model/backend support, tool-call format, memory overhead, and Windows packaging before attempting integration.

### Avoid misleading optimizations

- Bigger context is not automatically better; long contexts increase prefill cost and can dilute relevant evidence.
- More parallel agents are not automatically faster; they compete for CPU, RAM, VRAM, disk, and model slots.
- More draft tokens are not automatically faster; acceptance rate and verification cost determine the result.
- A high average tokens/second can hide poor first-audible latency and p99 stalls.
- CPU offload can increase capacity while reducing speed; measure the complete workload.
- Never benchmark while changing several variables at once.

## 9. Windows host telemetry and resource supervision

For the Windows desktop, combine:
- process CPU time and working set tied to PID plus process-start identity;
- WDDM-aware per-process GPU memory and engine counters;
- adapter-level local and non-local memory;
- game frame timing (PresentMon/ETW where appropriate);
- OBS render/output counters;
- audio device health and underrun counters.

The Windows Exporter GPU collector is a useful implementation reference: it uses Perflib, D3DKMT, and Configuration Manager and exposes adapter-level and per-process GPU usage/memory. Microsoft's GPUView documentation distinguishes local video memory from system memory in process- and adapter-scoped memory charts.

Do not use NVML's WDDM process-memory field as the sole source of per-process VRAM. Keep the provider injectable and fail closed when it cannot produce a trustworthy process/adapter sample.

The supervisor should:
- launch only allowlisted worker commands;
- pass secrets through protected handles/credential storage, not command lines;
- assign a stable worker generation;
- capture exit code and stop acknowledgement;
- enforce deadlines and graceful-then-forced shutdown;
- confirm process termination before releasing resource leases;
- restart only idempotent services with bounded backoff;
- persist a small crash-recovery journal;
- avoid collecting command lines, window titles, or user content unless strictly necessary.

## 10. Self-improvement without self-corruption

Use a controlled experiment loop:
1. Create a hypothesis tied to one measurable failure.
2. Generate one isolated candidate change.
3. Run unit, type, lint, security, and integration tests.
4. Run a fixed development suite.
5. Run a sealed holdout suite that the candidate cannot read.
6. Compare paired task outcomes and realtime metrics.
7. Reject if quality, privacy, safety, or stream stability regresses.
8. Produce a reviewable change with evidence and rollback.
9. Keep promotion manual.
10. Preserve a known-good version.

Do not let STAR rewrite its evaluator, holdout cases, scoring key, or promotion thresholds in the same experiment it is evaluating. Keep the host key and hidden cases outside model/tool access. HMAC proves that a holder of the key signed a payload; it does not prove that the observer or scorer was honest. Use an independent trusted host and auditable evidence where possible.

## 11. Acceptance gates for the next milestones

### Milestone A — CI and offline correctness
- All stacked PRs have green offline tests, lint, and type-baseline checks.
- No new type errors.
- Parent/child PR stack is clearly documented.
- Production `main` remains unchanged until review.

### Milestone B — Windows measurement
- CPU/RAM process samples match stable process identity.
- WDDM local/non-local process memory is independently cross-checked.
- Unknown readings remain unknown.
- Host clock resets, PID reuse, driver restart, and process exit are tested.

### Milestone C — private stream rehearsal
- 60-minute private rehearsal with the actual microphone, TTS, avatar, OBS, game, and model.
- No audio underruns or OBS output skips beyond the operator-set budget.
- Barge-in stops speech promptly and only heard audio enters history.
- Avatar mouth/expressions track playback and recover after interruption.
- p95/p99 first-audible latency and game frame time remain within agreed budgets.
- Every test is repeated under idle and mixed load.

### Milestone D — gamer learning
- Complete a fixed training curriculum.
- Demonstrate improvement on held-out seeds/maps.
- Test transfer to a new map or game version.
- Report failure cases and confidence; do not claim mastery from one win.

### Milestone E — game creator
- Complete a Roblox Studio task through inspect/edit/playtest/repair.
- Verify a separate held-out task.
- For a full game, pass the game-completion gate, not just static code checks.

### Milestone F — general knowledge and memory
- Evaluate source correctness, freshness, conflict handling, and citation precision.
- Include no-memory controls, temporal updates, stale-memory traps, and action-parameter grounding.
- Measure retrieval latency and context-token cost.

## 12. Prioritized implementation order

| Priority | Work | Why |
|---|---|---|
| P0 | Repair and re-run CI on the current paired-evaluation PR | Do not build on a red type gate |
| P1 | Finish the trusted Windows telemetry/supervisor adapter | Connect existing policy to real resource use |
| P1 | Extend inference benchmark to TTFT/TPOT and mixed-load trials | Find actual bottlenecks before model changes |
| P1 | Keep voice/avatar/playback on one event clock | Prevent speech and face desynchronization |
| P2 | Integrate adaptive turn-taking and false-interruption recovery | Natural multiparty conversation |
| P2 | Add a private-stream OBS/VTube Studio adapter with narrow permissions | Real VTuber capability |
| P2 | Add fast controller + slow strategic Gamer loop | Responsive gameplay |
| P2 | Connect Roblox Studio MCP to explicit multi-Studio test sessions | Real game creation and playtesting |
| P3 | Versioned procedural skills and held-out transfer | Reliable self-learning |
| P3 | Source-backed general knowledge and memory-to-action evaluation | Broad knowledge with evidence |
| P3 | Controlled model portfolio and MTP experiments | Improve capability/speed without destabilizing the stream |

## Research references

### Voice, turn-taking, and realtime observability
- [LiveKit Agents — Turn-taking overview](https://docs.livekit.io/agents/logic/turns/)
- [LiveKit Agents — Turn-taking tuning](https://docs.livekit.io/agents/logic/turns/tuning/)
- [OpenTelemetry GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai)
- [OpenTelemetry GenAI metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md)

### Avatar and broadcast
- [VTube Studio official API development page](https://github.com/DenchiSoft/VTubeStudio)
- [OBS Project obs-websocket](https://github.com/obsproject/obs-websocket)
- [OBS WebSocket protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md)

### Inference and performance
- [llama.cpp server development documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README-dev.md)
- [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [vLLM speculative decoding / MTP](https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp/)
- [vLLM Qwen3.5-9B recipe](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3.5-9B.yaml)
- [OpenTelemetry GenAI metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md)

### Gaming and game creation
- [Google DeepMind — SIMA 2](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/)
- [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/abs/2305.16291)
- [GameWorld benchmark](https://gameworld-project.github.io/)
- [OpenGameEval — Roblox](https://github.com/Roblox/open-game-eval)
- [GameDevBench](https://github.com/waynchi/gamedevbench)
- [Roblox Studio MCP documentation](https://create.roblox.com/docs/studio/mcp)
- [Roblox Studio MCP and Open Cloud](https://create.roblox.com/docs/studio/mcp-open-cloud)

### Memory and Windows telemetry
- [Mem2ActBench](https://arxiv.org/abs/2601.19935)
- [windows_exporter GPU collector](https://github.com/prometheus-community/windows_exporter/blob/master/docs/collector.gpu.md)
- [Microsoft GPUView memory charts](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/memory-charts)

## Scope and limitations

This document is research and architecture guidance. It does not claim that STAR has acquired human-level behavior, mastered games, improved model intelligence, or achieved any measured speedup. It does not download models, change runtime defaults, enable tools, capture audio/video, control OBS/VTube Studio, launch Roblox Studio, or publish anything. All new runtime adapters require implementation, review, tests, and private-hardware acceptance before they are considered shipped.
