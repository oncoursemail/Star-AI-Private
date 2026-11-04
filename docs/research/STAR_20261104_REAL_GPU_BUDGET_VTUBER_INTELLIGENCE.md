# STAR AI — GPU residency budget, VTuber/game intelligence and private-host readiness
**Engineering research and diagnostic implementation · November 4, 2026**

## Executive result

The connected Windows game/VTuber host uses an 8 GiB NVIDIA GPU. During a
read-only diagnostic check, its local AI workload was consuming almost all
available video memory. A machine that looks fast running only an LLM may
become slower and unreliable when adding a game, OBS, avatar renderer and TTS.
Before choosing a larger model or another speculative speed technique, measure
**free GPU memory throughout a window**, not a screenshot of one moment.

This change adds `star.stream_gpu_budget_diagnostic`, a one-command,
read-only opt-in Windows GPU-pressure probe that samples a pinned GPU with
`nvidia-smi`, checks monotonic cadence and GPU identity, refuses corrupted
samples and emits a privacy-minimal JSON advisory. It **does not** run a game,
launch models, release VRAM, stop processes, record audio or start OBS.

Run on an authorized Windows Python environment with the repository on the
Python path:

```powershell
python -m star.stream_gpu_budget_diagnostic --observe --samples 5 --interval-ms 500
```

No `--observe` -> no sampling. Exit 0 means a well-formed advisory was
produced; it **never means streaming or game controls are authorized**.
Exit 1 = measurement unavailable. Exit 2 = disabled/invalid configuration.

## What was implemented and why it differs from existing safeguards

Existing `AdaptiveQoS`, `StreamLoadGovernor`, `RealtimeTelemetryHost`,
`stream_windows_rehearsal_preflight`, and
`stream_windows_resource_window` regulate live task reservations and/or check
whether all required game/OBS/avatar/model processes are available. They
already do useful work and should **not be bypassed or replaced**.

The new command is instead a zero-setup **diagnostic when the game or OBS are
not yet running**. It establishes that enough *idle* GPU headroom exists to
justify attempting a measured private rehearsal (not an actual authorization).
It reports one of:

- `saturated`: measured minimum free VRAM is below a configurable GPU reserve.
  Do not start another GPU worker on this evidence.
- `constrained`: the reserve is present but an optional GPU voice footprint
  or compute utilization is concerning. Investigate CPU-based voice after
  comparing quality and end-to-end timing, not from a model-size claim.
- `preflight_only`: the sampled GPU had preliminary headroom. This does not
  establish headroom under OBS + active game + speaker/renderer load.
- `unavailable`: missing/restarted GPU identity, skipped sample, bad clock,
  wrong OS, probe error, or untrusted timing. Never fill gaps with optimistic
  values.

The reserve defaults to **1536 MiB**, matching existing Star QoS policy; it
is a configurable engineering protection margin, not a proven universal
quantity. A **512 MiB** placeholder for optional GPU speech is merely an
estimate, not a benchmark of any particular TTS model. More accurate runtime
admission must use real peak model residency, fragmentation and GPU frame
quality on the target host.

A passing *idle* preflight never asserts gameplay quality, audio naturalness,
model intelligence, or stream quality. All permission flags are false. It
stores neither GPU UUIDs nor PIDs, model names, scene titles, viewer messages,
audio, frames, credentials, Windows paths, or stream destinations. The UUID is
checked ephemerally to prevent GPU swaps during a supposedly stable window.

## Practical 8 GB host plan — priority and quality preservation

**Phase 1: record the idle baseline.** Capture 5–9 readings; record the
minimum free MiB, peak GPU utilization, and sample cadence. Run no optional GPU
background training/rendering when the reserve is unavailable. Do not
auto-terminate the owner's existing `llama-server` or other processes.

**Phase 2: profile real workloads separately.** Compare idle, game only,
game + *private local recording*, and game + recording + speech/avatar. Keep
an OBS websocket event-continuity witness, actual game-present timestamps,
real PCM consumption and independently sampled input-to-world outcomes.
Measure p95/p99 time from game observation to successful physical input
acknowledgment, p99 game frame time, OBS render/output frame skip deltas and
time-to-first *audible* phoneme. Use `GameHostLoadTick` +
`assess_host_game_load` only after genuine same-clock host instrumentation.
A sent key does not prove the game responded.

**Phase 3: choose model placement by evidence.** Keep a fast smaller controller
for time-critical game reactions; schedule more expensive reasoning and
web/retrieval tasks for quiet gaps or a second machine. Investigate partial
CPU offload, carefully sized context/KV cache, and low-overhead TTS on CPU.
Do not claim that a 9B Q4 model or a long context always fits 8 GB: model
weights, KV cache, OS reserved VRAM, CUDA buffers and the actual game/OBS
footprint can make that false. Benchmark each model's accuracy, correct
formatting, p95 end-to-end delay, peak committed VRAM and timeouts in *the
same workload* before changing routing policy.

**Phase 4: preserve intelligence while optimizing speed.** Require independent
held-out outcomes in four Star workloads: gameplay, general knowledge, Roblox
creation and dialogue. An inference throughput gain is not an intelligence
gain. Preserve difficult long-horizon problems and use verify-and-repair
rather than relying on a single untested answer. Track provenance,
calibration, factual abstentions, task success and regression counts.

**Phase 5: make Star feel more natural as a VTuber.** Prioritize believable
pacing over constant talk: speech should depend on fresh observed game
progress and social turns; silence during difficult input sequences is useful.
Adaptive barge-in/backchannel handling can improve overlap, but do not assume
the LiveKit Cloud model is a free offline model. Keep a true local owner stop,
audio playout confirmation, lip-sync from *consumed* PCM, clear AI identity,
bounded memory from signed events, and privacy-safe summaries. Use measurable
human-rater A/B naturalness trials (situation relevance, latency, interrupt
handling, repetition) instead of simply generating more emotional lines.

**Phase 6: autonomous games and Roblox creation.** Use Roblox Studio's built-in
MCP playtest tools and StudioTestService for authored tasks, multiplayer
playtests and verification on the dedicated machine. Build small escalating
games, learn by real game-state-verified outcomes, quarantine practice data
from held-out transfer cases, and test that apparent improvements survive new
levels, machine load and game versions. Never let an AI invent a win from a
single frame.

## Measurement design

1. Sample on a background worker; avoid blocking the renderer or audio thread.
2. Require 3–9 samples and >=0.7 seconds of ordered observations; consecutive
   gaps must be 0.2–4 seconds, with unchanging GPU identity and total capacity.
3. Use the **minimum** free VRAM; one high-memory-pressure observation dominates
   the window, even if other samples looked idle.
4. Consider peak compute utilization separately from VRAM residency. Under
   Windows WDDM, process-level `nvidia-smi` accounting can be incomplete.
5. Never interpret a successful preflight as an admission for another GPU
   worker. `AdaptiveQoS` retains authoritative host-side runtime controls
   and must reserve capacity before starting any worker.
6. If OBS or the game is absent, document that gap rather than fabricating
   healthy observations. A complete owner-approved *nonbroadcast* rehearsal
   remains the next milestone.

## Testing and limitations

The 20 new offline adversarial tests cover single-sample optimism, GPU swap,
GPU capacity change, clock replay, sampling gaps, missing UUID, saturated
memory, high utilization, correct headroom arithmetic, sanitized failures,
opt-in, off-Windows behavior, invalid values, CLI fail-closed mode, and no
permissions. These are simulation/contract tests **not a real game benchmark**.

No GPU process was stopped or reconfigured, no broadcasting was performed,
and no AI weights were trained here. The real Windows snapshots that motivated
this improvement were read-only, not a complete gaming/VTuber test.

## Sources and further evaluation

- NVIDIA System Management Interface overview and supported NVIDIA GPU
  telemetry: https://developer.nvidia.com/system-management-interface
- NVIDIA GPU Deployment and Management guide (NVML / nvidia-smi):
  https://docs.nvidia.com/deploy/nvidia-smi/index.html
- llama.cpp SPEED-Bench for repeatable inference speed checks:
  https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- LiveKit adaptive interruption handling (depends on deployment, VAD and
  inference availability):
  https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- Roblox Studio built-in MCP server / playtest automation (March 5, 2026):
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Roblox Studio playtest subagent beta (April 9, 2026):
  https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- GameWorld: independently verifiable game-state benchmark including
  real-time game-world variant: https://gameworld-project.github.io/

These sources inform future design. No linked third-party system was installed
or granted computer, streaming or game-control permissions in this change.
