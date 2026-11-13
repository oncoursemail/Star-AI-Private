# STAR 2026-11-12 — Per-Process Thinker Telemetry, WDDM Attribution, and Capability Roadmap

## Executive summary

STAR already has a host-health telemetry path and a separate resource-admission policy. The missing measurement boundary is per-worker attribution: the host can know that total RAM/VRAM is tight, but it cannot reliably say how much CPU, resident RAM, and GPU memory the exact speculative thinker process consumes.

This change adds a small, dependency-free process measurement layer that feeds the existing paired calibration API. It deliberately does not add another scheduler, inference server, voice pipeline, or process supervisor.

The implementation adds:

- Explicit-PID Windows process sampling using GetProcessTimes and GetProcessMemoryInfo.
- Linux /proc/<pid>/stat sampling for the same process-level CPU/RSS concepts.
- PID-reuse protection using PID plus process creation/start token.
- Bounded observation windows with monotonic timestamps and a maximum sampling gap.
- CPU normalization to scheduler millicores; one logical CPU core is 1000 millicores and multi-core processes may exceed 1000.
- Peak observed working-set and GPU-memory aggregation.
- A strict optional GPU-memory provider contract.
- Conversion into the existing ThinkCalibrationPair only when GPU memory is known.
- Offline regression tests for counter rollback, PID reuse, sampling gaps, unknown GPU readings, process-window overlap, and configuration/clock-epoch mismatches.

No model, tool permission, broadcast setting, production default, or production main branch is changed.

## Repository audit: what exists already

The current stacked branch already includes:

- RealtimeTelemetryHost for whole-host CPU/RAM/VRAM health, frame-present timing, and local speaker backlog.
- StreamHostSampler for fresh, same-epoch, fail-closed QoS assembly.
- StreamWorkloadRuntime and WorkloadAdmissionController for shared CPU/RAM/VRAM allocation and protected real-time reserves.
- IncrementalThinkCoordinator for stable semantic-prefix reasoning policy.
- IncrementalThinkAdmissionBridge for the optional VOICE_PREP scheduler lane.
- ThinkResourceProfile for configuration-bound, expiring allocation envelopes.
- ThinkCalibrationSession for paired baseline/active resource samples.
- Inference A/B infrastructure for matched loopback-only model trials.
- Existing game-skill transfer evaluation and safe skill memory.
- Existing VTube frame pump and playback-locked avatar transport.

The correct next step is to provide trustworthy per-worker observations to these existing abstractions, not duplicate them.

## Process telemetry implementation

### Stable process identity

A PID alone is not a process identity because Windows and Linux reuse PIDs. ProcessIdentity therefore stores:

- PID.
- A process-start token.

On Windows, the token is the process creation FILETIME returned by GetProcessTimes. On Linux, it is the starttime field from /proc/<pid>/stat.

The token is held in memory only. It is not a username, process name, executable path, command line, or durable machine identifier.

### CPU measurement

GetProcessTimes returns cumulative kernel-mode and user-mode CPU time in 100-nanosecond units. Windows documents that the per-process total sums CPU time across all threads and can exceed elapsed wall time when the process uses multiple cores.

For a measurement window:

CPU millicores = ceil(delta_process_cpu_time_100ns * 1000 / (delta_wall_time_ms * 10000))

Interpretation:

- 1000 millicores = one fully occupied logical CPU core.
- 2000 millicores = two fully occupied logical CPU cores.
- The value is a window average, not an instantaneous CPU percentage.

The Linux reader converts user+system jiffies to the same 100-nanosecond time unit using SC_CLK_TCK.

### RAM measurement

The Windows reader uses PROCESS_MEMORY_COUNTERS_EX.WorkingSetSize. This is the current resident working set in bytes, not the process commit charge or page-file usage.

The window accumulator records the maximum observed working set. A background sampler should normally poll every 100–250 ms. The default maximum accepted gap is 500 ms; a larger gap invalidates the window because a short-lived peak could have been missed. Every observation call must also supply the current host clock epoch and inference-configuration fingerprint; the accumulator revalidates both on every sample rather than trusting only the values captured at construction.

The Linux reader uses resident pages from /proc/<pid>/stat multiplied by the system page size.

### GPU memory: important WDDM correction

Do not use NVML usedGpuMemory as the Windows per-process VRAM source when the NVIDIA driver is operating in WDDM mode. NVIDIA documents this field as unavailable under WDDM because Windows owns GPU memory management.

Recommended Windows source:

- WDDM GPU Process Memory counters through Perflib/PDH, or a validated D3DKMT-backed provider.
- Prefer the per-process Local Usage metric for dedicated/local GPU segment accounting.
- Keep Non Local Usage separate; it is GPU-accessible system memory, not dedicated VRAM.
- Retain adapter identity and distinguish local from non-local memory.
- Revalidate the PID's process-start token around the GPU query to prevent PID reuse from attributing another process's memory.

The windows_exporter GPU collector is a useful implementation reference: its documented source uses Perflib and D3DKMT and exposes per-process GPU engine and process-memory metrics. It is not added as a runtime dependency here.

The current code accepts an injected gpu_memory_probe(pid, process_start_token) callback. A missing or failed reading is None, never zero. The calibration conversion refuses to produce a ResourceVector when GPU memory is unknown. A provider may return zero only when it has a complete, successful snapshot that proves the process has no local GPU allocation.

### Why host health and worker attribution remain separate

The host-health path answers: is there enough free VRAM/RAM and is the stream/game currently healthy?

The process-attribution path answers: how much resource use belongs to this exact worker?

Both are required. A small thinker process can still be unsafe when the host is near capacity; a healthy host can still have a thinker whose actual cost is larger than its reservation.

The scheduler must continue to consider both the host-health snapshot and the calibrated per-worker envelope.

## Calibration flow

1. The trusted host chooses the exact model-worker PID and configuration fingerprint.
2. The host creates a process window bound to one clock epoch.
3. It samples that exact PID's CPU time, working set, and WDDM-aware GPU memory off the audio/game/render hot path.
4. Each observation must match the same process-start token.
5. Counter rollback, PID reuse, stale observations, long sample gaps, or configuration changes invalidate the window.
6. The host builds a baseline window while the resident thinker is idle.
7. The same process is sampled during a matched active-thinking window.
8. build_think_calibration_pair converts the non-overlapping windows into the existing ThinkCalibrationPair.
9. ThinkCalibrationSession performs the existing bounded multi-pair calibration and ThinkResourceProfile applies its configured safety margin.
10. IncrementalThinkAdmissionBridge continues to revalidate the profile and clock epoch before enqueue and launch.

This design currently measures a persistent/resident worker. If a future host starts a fresh process for every request, it must supply a valid baseline policy for process creation cost rather than pretending a missing baseline process used zero resources.

## Performance and speed research

### Measure the whole user-visible path

Do not optimize only tokens per second. For a live VTuber, the useful latency milestones are:

- ASR final/partial availability.
- Stable semantic-prefix decision.
- Background thinker start.
- Model time to first token.
- Time to first audible response.
- First audible response after barge-in recovery.
- Cancellation request to confirmed worker stop.
- Audio playback backlog and underruns.
- OBS render/output skipped frames.
- Game frame-time p50/p95/p99.

Use low-cardinality metrics and do not export prompts, transcripts, viewer identities, audio, tool arguments, model paths, or secrets.

### llama.cpp SPEED-Bench

The upstream llama.cpp SPEED-Bench client evaluates an already-running server and reports per-category throughput, latency, and speculative draft acceptance. The documentation specifically recommends matching client concurrency to the server slot count when measuring throughput.

STAR should benchmark baseline versus candidate under the same:
- Model artifact and quantization.
- llama.cpp binary/build.
- Context and batch settings.
- GPU offload and KV-cache type.
- Server slot count and request concurrency.
- Prompt suite, output-length policy, and warm-up.
- Stream/game/OBS load.

Test speculative decoding methods one at a time. An option that raises isolated tokens/sec but worsens first-audible latency, answer quality, p95/p99 latency, game frame time, or audio reliability should not be promoted.

For an 8 GB GPU, begin with the current baseline, prompt/KV-cache stability, and low-memory draftless methods before adding a second resident draft model. Measure RAM/VRAM headroom and model-load churn.

## Streaming: more human interaction without speaking constantly

### Duplex-MPE

Duplex-MPE evaluates whether a speech assistant should answer, remain silent, or stop speaking in multi-party conversation. It contains 2,000 scenarios with three or four human speakers plus an assistant, paired across explicit and implicit addressing. Its four scores separate response initiation, answer accuracy, silence preservation, and stopping after a human resolves a request.

This is a better design target for STAR than maximizing the number of replies. A natural VTuber should know when a viewer is addressing her, when two viewers are talking to each other, and when another human has already answered.

### MP-Bench

MP-Bench reports substantial gaps in multiparty comprehension and turn-taking across evaluated real-time voice agents. It motivates a STAR-specific, consented rehearsal set with separate scores for:

- Direct versus implicit addressing.
- Viewer-to-viewer conversation.
- Brief backchannels.
- Overlapping speech.
- Human resolution before STAR speaks.
- Topic changes during an unfinished answer.
- Silence preservation.
- Interruption stop latency.
- Recovery without losing the unfinished task.

The benchmark data is synthetic English speech and does not prove performance in noisy real streams, other languages, or natural viewer audio. STAR must be evaluated on separate opt-in rehearsal recordings with clear consent and retention limits.

### Avatar synchronization

The existing VTube frame pump should remain latest-wins because animation samples are replaceable time samples. Speech segments, gameplay actions, task events, and durable delivery obligations must remain ordered.

Next avatar work should synchronize:
- Playback cursor and mouth movement.
- Listening pose while ASR is active.
- Eye gaze and expression transitions.
- Interruption-to-neutral pose.
- Emotion/reaction intensity with actual audio output.
- Idle animation with the stream/game state.

A neutral pose should be emitted only after the current frame epoch is flushed; stale animation frames must not reappear after interruption.

## Gaming intelligence

### SIMA 2

Google DeepMind's SIMA 2 work is relevant because it moves beyond fixed instruction following toward an interactive agent that reasons about goals, converses, and improves through self-directed play and feedback.

STAR should use a two-timescale control design:

- Reactive controller: high-frequency movement, camera, aim, jump, dodge, and immediate safety constraints.
- Strategic controller: objectives, route planning, inventory, map understanding, team strategy, and long-horizon choices.

The strategic model must not issue stale low-level actions directly. It should submit short-lived goals to a reactive controller that can cancel or override them when the game state changes.

### Skill memory and transfer

A skill should be a versioned, executable policy with:
- Game/build/environment fingerprint.
- Preconditions and supported action space.
- Observation requirements.
- Expected reward or success criteria.
- Failure modes and stop conditions.
- Training evidence and independent holdout results.
- Last validated version and expiry policy.

Do not mark a skill as learned because the model describes it well. Require repeatable success in fresh sessions and test transfer separately from in-game memorization.

### Roblox and game creation

OpenGameEval tests agents inside reproducible Roblox Studio sessions and checks both edited scenes and simulated play sessions. Its published core evaluation contains 84 curated tasks with repeated attempts. It also measures exploration behavior and reports that inspecting relevant objects before editing is associated with higher success.

GameDevBench evaluates 333 Godot tasks across gameplay, UI, 2D graphics/animation, and 3D graphics/animation. Its research shows that image/video feedback can materially improve task success.

STAR Creator should therefore use a visual, engine-in-the-loop loop:

1. Inspect the DataModel/scene and relevant assets.
2. Plan the smallest safe edit.
3. Modify scripts and scene objects.
4. Run static checks.
5. Launch the real engine.
6. Capture runtime visuals and state.
7. Play the target interaction.
8. Compare with explicit acceptance criteria.
9. Repair and rerun.
10. Save a reproducible test artifact.

A successful compile is not a finished game.

## General knowledge and long-term memory

Mem2ActBench emphasizes that an agent must apply prior context to future tool actions, not merely retrieve facts when explicitly asked. Its 2026 ACL paper reports 2,029 synthesized interaction sessions and 400 tool-use tasks, with human evaluation finding 91.3% strongly memory-dependent.

STAR's memory evaluation should distinguish:

- Retrieval: did the right memory surface?
- Grounding: did the model correctly resolve conflicts and freshness?
- Action: did it apply the remembered constraint to a tool call or decision?
- Verification: did the resulting action satisfy the remembered intent?
- Forgetting/expiry: did stale or revoked context stop influencing behavior?

Store provenance, timestamp, confidence, source scope, and expiry. Separate working, episodic, semantic, procedural, social, skill, and project memory. Do not turn stream audio into persistent voiceprints or infer stable viewer identities from voice similarity.

## Next implementation priorities

P0 — Finish and merge the existing calibration stack only after all required CI and review checks pass.

P1 — Implement the actual Windows WDDM GPU Process Memory provider using a documented Perflib/PDH or validated D3DKMT path. Keep it off the hot path and expose local/non-local usage separately.

P1 — Wire a background Windows collector to ProcessReader, process-window accumulators, ThinkCalibrationSession, and the central host supervisor. The collector must authenticate the caller, pin process creation identity, and confirm process stop before releasing leases.

P1 — Add a host-private telemetry store for raw calibration windows. Store only opaque process references and bounded metrics; aggregate profiles remain content-free.

P1 — Extend inference A/B to record matched per-worker CPU/RAM/VRAM deltas, first-audible latency, cancellation-to-stop, and stream/game regressions.

P2 — Build a consented multiparty Social Director evaluation set based on Duplex-MPE/MP-Bench categories, but include real-room noise, natural voices, and multilingual cases in a separate holdout.

P2 — Integrate the reactive/strategic Gamer Brain with safe game adapters and independently scored skill transfer.

P2 — Integrate Roblox/Godot visual feedback and engine-in-the-loop playtesting.

P3 — Evaluate memory-to-action, knowledge freshness, citation accuracy, and skill transfer across long-running sessions.

## Acceptance criteria

The process telemetry adapter is acceptable only when:

- It never enumerates processes; callers supply the exact PID.
- PID reuse is detected using the process-start token.
- Process CPU counters never move backwards within a window.
- Every observation re-presents the current host clock epoch and inference fingerprint; any mid-window change invalidates the sample.
- A sampling gap above the configured maximum invalidates the window.
- Unknown GPU memory is represented as None, never zero.
- Windows WDDM never uses NVML usedGpuMemory as the process VRAM source.
- Only complete baseline/active process windows can become ThinkCalibrationPair values.
- No raw process names, paths, command lines, transcripts, audio, viewer identities, or secrets are persisted.
- All OS polling runs off audio, render, and game-control threads.
- Full repository CI passes on the exact PR head before merge.
- A Windows hardware rehearsal validates real GPU counters, CPU/RAM attribution, OBS stability, audio reliability, and game frame-time under simultaneous load.

## Validation boundaries

This PR adds process-reader and aggregation code plus offline tests. It does not yet implement a Windows PDH/D3DKMT GPU provider, start a collector service, supervise model processes, launch inference, connect to OBS/VTube Studio, capture audio, control games, or change production defaults.

The optional GPU provider is an explicit integration point. Until a WDDM-aware provider supplies complete per-process local-memory samples, process windows cannot be converted into an authorized ThinkResourceProfile.

No measured speedup, intelligence improvement, naturalness gain, gameplay mastery, or production readiness is claimed.

## Research sources

- Microsoft GetProcessTimes: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes
- Microsoft GetProcessMemoryInfo: https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo
- Microsoft PROCESS_MEMORY_COUNTERS: https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters
- NVIDIA NVML API Reference: https://docs.nvidia.com/deploy/nvml-api/
- Microsoft DirectX — GPUs in Task Manager: https://devblogs.microsoft.com/directx/gpus-in-the-task-manager/
- Microsoft GPU Segments: https://learn.microsoft.com/en-us/windows-hardware/drivers/display/gpu-segments
- windows_exporter GPU collector reference: https://github.com/prometheus-community/windows_exporter/blob/master/docs/collector.gpu.md
- PresentMon: https://github.com/GameTechDev/PresentMon
- llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- llama.cpp speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- Duplex-MPE: https://arxiv.org/abs/2609.31948
- MP-Bench: https://www.fullduplex.ai/benchmarks/mp-bench
- SIMA 2: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Roblox OpenGameEval: https://github.com/Roblox/open-game-eval
- GameDevBench: https://github.com/waynchi/gamedevbench
- Mem2ActBench: https://aclanthology.org/2026.acl-long.370/
