# STAR research: budgeted incremental voice thinking

**Date:** 2026-11-12  
**Status:** research + offline host-policy implementation  
**Branch:** `feat/voice-thinker-budget-admission-20261112-auto11`  
**Parent:** `feat/incremental-semantic-thinking-20261112-auto11` (draft PR #1160)

## Executive finding

STAR's incremental semantic-prefix coordinator can decide that a partial ASR transcript is stable enough to prepare a response. That does not mean a background model should automatically start. During a VTuber stream, gameplay, avatar animation, audio playback, OBS, and the foreground response are competing for finite CPU, RAM, VRAM, and scheduling time.

The missing boundary was **resource admission between the semantic thinker and the existing multi-resource workload scheduler**.

This change adds that boundary without creating another scheduler or another voice pipeline.

## Important scheduler audit

The existing `WorkloadLane` policy has three relevant properties:

- `CHAT` is a protected lane. It can be admitted under degraded telemetry, although it cannot consume the hard real-time reserve.
- `INTERACTIVE`, `RESEARCH`, `LEARNING`, and `ASSET_GENERATION` are non-protected, but are deferred while streaming or gaming.
- A speculative thinker is neither ordinary chat nor long-running research: it is optional response preparation. It should be allowed during a healthy stream only when it fits outside the real-time reserve, and it must stop being admitted when host health degrades.

Using `CHAT` for speculative reasoning would therefore be too permissive during degraded conditions. Using `INTERACTIVE` would defer it for every stream/game, even when there is ample headroom.

### New lane: `VOICE_PREP`

The scheduler now has a dedicated `WorkloadLane.VOICE_PREP`:

| Property | Policy |
|---|---|
| Priority | Below audio, game-control, voice, avatar, and chat |
| Hard real-time reserve | Cannot consume it |
| Healthy live stream/game | Eligible only from unreserved capacity |
| Degraded or stale host health | Blocked as non-protected work |
| Streaming/game deferral | Not blanket-deferred; measured headroom decides |
| Execution | Still requires the central host scheduler and a worker adapter |
| Authorization | Does not grant microphone, tool, file, network, or game permissions |

This is a policy class, not a claim that the host has calibrated resource costs. The Windows host must provide a conservative `ResourceVector` measured for its selected thinker/model configuration.

## Implemented components

### `star/stream_workload_admission.py`

- Adds `VOICE_PREP` as a distinct lane.
- Places it below `CHAT` and above ordinary interactive/research work.
- Does not add it to protected lanes or the real-time reserve.
- Does not add it to the blanket stream/game-deferred set.
- Existing reserve subtraction and fail-closed health checks therefore apply.

### `star/voice/incremental_think_admission.py`

Adds `IncrementalThinkAdmissionBridge`, which connects the existing `ThinkDirective` API to `StreamWorkloadRuntime`.

Lifecycle:

1. A validated `START` directive becomes a content-free `VOICE_PREP` `WorkloadRequest`.
2. The central host scheduler observes trusted telemetry and grants a `WorkloadLease`.
3. The host routes that lease to `accept_lease()`, which returns a `ThinkLaunch` offer.
4. The host starts its local, cancellable, read-only thinker and confirms startup.
5. `UPDATE` replaces only the ephemeral stable prefix visible to that exact worker generation.
6. `CANCEL` or `FINALIZE` removes queued work, or returns a stop request for an active worker.
7. Resource capacity is released only after the host confirms the worker has stopped.

The bridge never starts a process, calls a model, speaks, executes tools, writes canonical history, polls hardware, or performs network I/O.

### Race and recovery behavior

- If cancellation races with the scheduler after a request has left the queue but before the host routes its lease, the bridge marks the generation `CANCEL_PENDING`. When the lease arrives, it is released without starting a worker.
- If an ASR revision replaces a running thinker, the new revision is blocked until the exact old generation has a host-confirmed stop.
- If startup is ambiguous, the lease remains reserved in `RECOVERY_REQUIRED`; capacity is not optimistically released.
- If a stop cannot be confirmed, the lease remains fenced.
- Request IDs are derived from opaque utterance/revision identifiers, never transcript text.
- Metrics contain aggregate counters only.
- The bridge uses the existing scheduler's replay protection; a cancelled request ID cannot be reused to create duplicate work.

## Host integration contract

The future Windows voice host should:

1. Feed only validated, monotonic host telemetry into `StreamWorkloadRuntime.observe()`.
2. Call the existing central `StreamWorkloadRuntime.schedule()` loop.
3. Route `VOICE_PREP` leases to this bridge and other lanes to their owning subsystems.
4. Start only a local worker with bounded CPU/RAM/VRAM, strict cancellation, no tools, no speech output, no network access, and no canonical-history writes.
5. Poll `current_directive(lease_id)` for the newest stable prefix.
6. Report startup and stop acknowledgements from the actual process supervisor, not from model self-report.
7. Keep final ASR, conversation-history commit, foreground answer generation, tool authorization, and playback delivery on their existing authoritative paths.

Do not call the bridge from an audio callback, render callback, OBS callback, or VTube Studio socket thread. Run it on the host control loop.

## Research findings

### 1. Semantic triggering and incremental reasoning

**LTS-VoiceAgent**, published in EMNLP 2026, separates the decision of when to think from the reasoning process itself. Its Dynamic Semantic Trigger and dual-role stream orchestrator use stable meaningful prefixes rather than fixed audio chunks alone. This supports STAR's existing `IncrementalThinkCoordinator`; the new contribution here is the resource-admission boundary between that coordinator and the actual background worker.

- Paper: https://aclanthology.org/2026.emnlp-main.1712/
- arXiv: https://arxiv.org/abs/2601.19952

### 2. Multiparty streaming is a separate capability

**MP-Bench**, Findings of EMNLP 2026, evaluates voice agents as active participants in group conversations. The paper reports that the evaluated real-time agents were at or below 22% on multiparty comprehension and near chance on multiparty turn-taking. A good single-speaker voice pipeline is therefore not sufficient for a human-feeling VTuber.

STAR's future Social Director should be evaluated separately on:
- direct address versus viewer-to-viewer conversation;
- response appropriateness;
- turn-taking and selective interruption;
- backchannels that do not seize the floor;
- silence preservation;
- multi-speaker comprehension.

Source: https://aclanthology.org/2026.findings-emnlp.1437/

### 3. Task continuity under interruptions

**Joi-Bench-Task**, posted 2026-11-09, evaluates the coordination between executing work and communicating its result while requests change or spoken delivery is interrupted. Its reported best result-completion rate under request changes was 55%; four of five evaluated agents omitted at least 23% of information after interruptions.

This supports STAR's separation of task state, delivery state, and conversation state. A viewer interrupting a sentence must not erase an unrelated game-development or research task. A completed task must remain an undelivered obligation until its result is communicated.

Source: https://arxiv.org/abs/2611.12118

### 4. Turn-taking actions need distinct evaluation

**DuplexAct-Bench** evaluates multiple full-duplex behaviors, including yielding, interruption, proactive initiation, active silence, and backchanneling. It reports that systems can perform differently across behaviors and conditions; semantic quality alone does not establish correct timing.

STAR should not collapse all conversational behavior into one interruption threshold. Measure false barge-ins, missed genuine interruptions, backchannel continuation, response timing, and unnecessary speech separately.

Source: https://arxiv.org/abs/2609.39446

### 5. Asynchronous delegation

**Realtime-Venus** demonstrates an architecture that separates a fast interactive loop from delegated work. Its published benchmark page reports 97% continuation through user backchannels on Full-Duplex-Bench v1.5 for its evaluated audio model. This is a vendor-reported result under that benchmark, not a STAR result or a direct cross-benchmark comparison.

STAR's corresponding design principle is to keep the foreground audio/game loop small and predictable while optional reasoning is delegated through explicit leases.

Source: https://realtime-venus.github.io/

### 6. Local inference and memory pressure

Upstream **llama.cpp** supports speculative decoding with draft models and n-gram cache variants. Its documentation explains that speculative decoding is useful when draft tokens are accepted often enough to offset draft/verification overhead.

STAR should compare paired configurations on the actual target host:
- baseline versus draft-model or n-gram speculative decoding;
- first-audible-token latency, not only aggregate tokens/second;
- accepted draft tokens and verification overhead;
- p50/p95 latency while OBS and a game are active;
- game frame-time and audio underruns;
- answer-quality and task-success parity.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

**StrataFlux**, posted 2026-11-05, explores memory-hierarchy-aware low-bit inference and selective precision streaming. Its reported experiments include RTX 5090 and other dedicated/unified-memory configurations; those results must not be assumed to transfer to STAR's RTX 4060 8 GB target. Treat it as a research candidate, not a production dependency. First reproduce a paired quality/performance test on supported hardware.

Source: https://arxiv.org/abs/2611.08363

### 7. Game-playing and game-creation intelligence

**SIMA 2** demonstrates language-guided, goal-directed behavior and self-improvement across virtual worlds. Its important lesson for STAR is to separate reusable skills from game-specific observations and validate transfer on held-out environments.

Source: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

**OpenGameEval** evaluates agents inside reproducible Roblox Studio sessions with executable checks on edited scenes and simulated play. It finds that inspection before editing correlates with higher task success. STAR should preserve read/inspect before edit and verify actual play outcomes.

Source: https://github.com/Roblox/open-game-eval

**GameDevBench** provides 333 Godot game-development tasks across gameplay, UI, 2D and 3D graphics/animation. Its maintainers report that visual feedback improves performance on multimodal tasks. STAR Creator should therefore use engine screenshots/runtime video and executable playtests, not source-code inspection alone.

Source: https://github.com/waynchi/gamedevbench

## Acceptance plan

The policy layer should be tested offline; the host integration must then be tested on Windows.

### Offline acceptance

- `VOICE_PREP` is lower priority than chat and every real-time lane.
- `VOICE_PREP` cannot consume the reserved CPU/RAM/VRAM slice.
- Healthy streaming/game telemetry permits admission only when unreserved capacity fits.
- Missing, stale, or degraded telemetry blocks admission.
- Queue cancellation and scheduler-grant races do not start a stale worker.
- An ASR revision cannot overlap with the old thinker generation.
- Uncertain startup/stop retains its lease.
- Finalization cancels only the exact speculative generation.
- Metrics never expose transcript text or utterance IDs.

### Windows acceptance (not performed in this PR)

Run a private rehearsal with OBS, VTube Studio, the real ASR/TTS host, and a game. Compare:
- no thinker versus thinker enabled;
- healthy versus pressured GPU/CPU conditions;
- voice first-audible latency p50/p95;
- game FPS p10 and frame-time p95;
- OBS render/output skipped-frame deltas;
- audio underruns and playback backlog;
- cancellation-to-process-stop latency;
- stale-worker count (must remain zero);
- response correctness and interruption quality.

The thinker is useful only if it improves time-to-speak without harming game smoothness, avatar timing, audio reliability, or answer quality.

## Explicit limitations

- This PR adds an offline admission bridge and a scheduler lane only.
- It does not connect a microphone, ASR engine, model process, TTS engine, Windows process supervisor, OBS, VTube Studio, game controller, or streaming platform.
- The host still owns trustworthy telemetry and process-stop evidence.
- A `WorkloadLease` is resource accounting, not security authorization.
- No latency improvement, intelligence gain, human-equivalent behavior, game mastery, or production readiness is claimed.
- Production `main`, release installers, model weights, routing defaults, permissions, and broadcast settings are unchanged.
