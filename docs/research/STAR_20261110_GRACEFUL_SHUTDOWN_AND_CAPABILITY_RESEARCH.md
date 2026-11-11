# STAR — Graceful Worker Shutdown, Live Scheduling and Capability Research

**Research snapshot:** 2026-11-10  
**Implementation branch:** feat/graceful-worker-shutdown-20261110-auto11  
**Stacks on:** PR #1119 (suspended Windows worker launch)  
**Scope:** bounded process-tree shutdown, live-workload protection, voice turn-taking, local inference measurement, game learning and autonomous game creation.

## Executive summary

STAR already has a process-tree supervisor. Its POSIX path uses a fresh process group, but cancellation currently sends SIGKILL immediately. That is reliable for cleanup, yet it prevents cooperative workers from flushing logs, saving a safe checkpoint, closing temporary resources or releasing a local server cleanly.

This increment adds a bounded two-stage shutdown policy:

1. Send SIGTERM to the STAR-owned POSIX process group.
2. Allow a small, validated grace interval for normal shutdown.
3. Reap the root process while checking whether descendants remain.
4. Escalate to the existing process-group SIGKILL path if the group is still alive.
5. Report whether the supervisor observed an empty tree.

The Windows path deliberately retains Job Object termination. Python documents that Windows SIGTERM maps to process termination, while CTRL_BREAK is only delivered to processes sharing the caller's console. STAR's workers are not guaranteed to share a console, so a fake "graceful" Windows signal would be misleading.

No hard CPU/RAM/VRAM cap, model change, auto-promotion, stream activation, game input or production default is changed.

---

## 1. Process lifecycle and cancellation correctness

### Why graceful POSIX shutdown matters

Python's subprocess documentation states that start_new_session=True calls setsid() before the child executes, allowing STAR to address the worker process group. On POSIX, Popen.terminate() sends SIGTERM and Popen.kill() sends SIGKILL. On Windows, terminate() calls TerminateProcess; SIGTERM is not a cooperative signal there.

- Python subprocess API: https://docs.python.org/3/library/subprocess.html
- Python asyncio subprocess API: https://docs.python.org/3/library/asyncio-subprocess.html
- POSIX process-group signal semantics: https://pubs.opengroup.org/onlinepubs/9799919799/functions/kill.html

### STAR policy

| Worker class | First action | Escalation |
|---|---|---|
| POSIX agent / ACP process group | SIGTERM | SIGKILL after bounded grace |
| Windows Job Object | TerminateJobObject | Existing root cleanup if job API fails |
| Explicit root-only fallback | Root termination | Report that descendants are not proven contained |

The grace period is intentionally short and bounded (default 350 ms, maximum 5 s). A shutdown helper must never become a second unbounded wait path.

The helper returns a boolean: True means the supervisor observed an empty tree; False means cleanup could not be confirmed within the configured bounds. Callers must not interpret a timeout as successful cleanup.

### Integration points

- star/agent_fleet.py: graceful cancellation and timeout of synchronous coding/test workers, and graceful cleanup of descendants that outlive a normally exited root.
- star/acp_adapter.py: graceful async shutdown when an ACP session ends, times out or is cancelled.
- star/process_supervisor.py remains the containment authority; the new helper only selects the shutdown sequence and uses its existing process-group/Job Object operations.

---

## 2. Protect the live VTuber path

A live stream is a deadline-sensitive mixed workload. The scheduler should preserve resources for physical audio, game input, avatar motion and OBS before admitting optional research or creation tasks.

Recommended priority classes:

| Priority | Work | Policy |
|---|---|---|
| P0 | Audio device I/O, emergency stop, game-control deadline, OBS health | Reserved capacity; no background queueing |
| P1 | Direct viewer address, turn-taking, short response, avatar reaction | Tight deadline; may preempt optional work |
| P2 | Current-game planning, scene commentary, fresh vision | Bounded queue; stale work expires |
| P3 | Deep research, coding, Blender render, asset generation, memory consolidation | Background; pause/cancel at safe checkpoints |

STAR already has a deadline-aware stream queue (#1110), load-aware speech admission (#1073–#1075), optional GPU leases (#1087–#1090), single-flight TTS preparation (#1081), and event-aware speech pacing (#1094–#1095). The next work should connect these controls to one telemetry-backed admission decision rather than creating a second scheduler.

Measure the full workload:
- ASR partial/final and end-of-turn latency.
- First TTS chunk and first physically audible response.
- Audio underruns, queue depth and playback jitter.
- Game input-to-action latency and frame-time p50/p95/p99.
- OBS render/encode lag and dropped frames.
- CPU, RAM, VRAM, GPU utilization, disk I/O and worker count.
- Cancellation-to-empty-tree latency.
- Task quality, factual support, interruption correctness and gameplay outcome.

A model/configuration is a win only when the target workload improves without unacceptable quality regression or live-path degradation.

---

## 3. Natural VTuber conversation: measure timing and social understanding separately

### End-of-turn detection

LiveKit's EOT-Bench publishes real human-to-agent turns with aligned audio and text in 14 languages. It annotates both mid-turn pauses and true turn endings and reports the Pareto trade-off between false cutoffs and endpointing delay.

- Benchmark: https://github.com/livekit/eot-bench
- Methodology: https://livekit.com/benchmarks/eot-bench

The current public benchmark results illustrate why a single "voice latency" score is insufficient: a detector can be fast by interrupting people, or conservative by leaving long dead air. STAR should calibrate to an explicit false-cutoff budget and preserve a held-out conversation set.

### Multi-party turn-taking

MP-Bench (Findings of EMNLP 2026) evaluates comprehension, turn-taking and response appropriateness in multi-party voice conversations. The published benchmark summary reports that the evaluated real-time agents scored at or below 22% on multi-party comprehension and near chance on multi-party turn-taking.

- Benchmark summary: https://www.fullduplex.ai/benchmarks/mp-bench

STAR should separately estimate:
1. Speaker track (session-local, not a real-world identity).
2. Addressee (Star, another viewer, group, or unknown).
3. Turn state (continue, yield, interrupt, overlap, complete).
4. Response policy (speak, backchannel, clarify, wait, or silence).

Silence must be an explicit action. Viewer chat, speech and game events should be ranked by relevance and freshness; every message should not automatically become a spoken reply.

---

## 4. Local inference: optimize measured end-to-end behavior

### llama.cpp SPEED-Bench

The upstream SPEED-Bench client benchmarks an already-running llama-server through its OpenAI-compatible API. It reports prompt throughput, generation throughput, client latency and speculative draft acceptance per category. It recommends matching client concurrency to server slots for throughput tests.

- SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
- Speculative decoding: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- MoE cache: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

### STAR experiment matrix

| Experiment | Primary measurement | Guardrail |
|---|---|---|
| Prompt-prefix cache | TTFT and prefill time | Exact prompt/model/template identity |
| KV cache type/size | VRAM and context throughput | Long-context quality |
| Speculative decoding | End-to-end latency and decode rate | Same prompt set, output quality and memory |
| MoE cache/CPU share | Decode speed and PCIe traffic | CPU contention and game frame-time |
| Model routing | Task latency and quality | Held-out task categories |
| Context compaction | Prefill time and task completion | Required facts retained |
| Continuous batching | Throughput under concurrency | P95 live-response latency |

On an 8 GB RTX 4060, draft models, large KV caches and multiple vision/TTS workers can compete for the same VRAM. Do not assume speculative decoding or MoE offload is faster: measure the exact model, quantization, context, server revision, concurrency, CPU/RAM and mixed gaming/OBS load. Keep the existing paired, replay-resistant inference gate (#1102) as the promotion boundary.

---

## 5. Game mastery: learn skills, not scripts

STAR's game-live-clock benchmark (#1086 and #1093) already requires scenario diversity, paired outcomes and latency checks. The next integration should make skill records transferable and grounded in actual game state.

Recommended loop:

1. Observe the current game state and objective.
2. Read controls and identify the safe practice boundary.
3. Act in short bounded batches while the game clock continues.
4. Compare expected and observed state transitions.
5. Diagnose failure using screenshots, HUD/state and logs.
6. Change one strategy variable at a time.
7. Retest on a new seed, map or opponent.
8. Validate transfer to an unfamiliar scenario.
9. Store a procedural skill only after independent holdout success.

Measure objective completion, survival, progress, missed action windows, input-to-action latency, resource use, scenario diversity and transfer—not just win rate.

---

## 6. Game creation: use real engine feedback

GameDevBench contains 333 Godot game-development tasks across 2D/3D graphics and animation, UI and gameplay. Its project reports that image/video feedback improves evaluated agent performance, reinforcing the need for visual inspection in addition to compile/test output.

- GameDevBench: https://github.com/waynchi/gamedevbench
- Roblox Studio's official agentic plan/build/test announcement: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- Roblox's official Studio MCP plugin: https://github.com/Roblox/roblox-studio-agent-plugin

For Roblox, Godot and Unity, STAR's creator loop should:
- Plan against a pinned design brief.
- Inspect the existing project before editing.
- Build in an isolated worktree or saved project copy.
- Launch the actual engine.
- Capture screenshots/video and engine logs.
- Compare observable behavior against acceptance criteria.
- Repair one defect class at a time.
- Retest regressions and performance.
- Present a reviewable artifact; publishing remains a separate owner-approved action.

Roblox's first-party Studio MCP exposes read-only inspection, scripting, asset operations and playtest controls. Use least-privilege permissions per experience; save a version before large edits and do not expose publishing/account scopes to general-purpose agents.

---

## 7. Broader generalist capability roadmap

| Capability | Required evidence |
|---|---|
| General knowledge | Source-backed answers, conflict handling, freshness |
| Research | Reproducible source list and claim-to-source mapping |
| Programming | Independent tests, static checks and reviewable diffs |
| Game mastery | Live-clock scenario transfer |
| Game creation | Engine execution and visual acceptance |
| Art / animation / audio | Asset inspection and project-level integration |
| Computer use | Scoped actions, auditable receipts and reversible operations |
| Long-term memory | Memory-on/off transfer and interference evaluation |
| Streaming personality | Long-session coherence, delivery and social appropriateness |
| Self-improvement | Sealed holdouts, rollback and no self-granted permissions |

A durable skill record should include preconditions, steps, expected effects, failure modes, tool/version dependencies and tests. Historical success must be invalidated when the code, project, engine or dependency fingerprint changes.

---

## 8. Rollout and safety

- Graceful shutdown is used only for STAR-owned worker process groups.
- The grace interval is bounded; escalation remains available.
- Windows Job Object termination remains the reliable hard-stop path.
- No arbitrary shell, global process killing, account operation, game publishing or public broadcast is added.
- A shutdown result of False is a warning and must block resource re-admission until the existing host supervisor reconciles the process tree.
- New behavior is limited to worker cleanup; it does not enable the agent fleet or any live-stream feature by default.

## References

1. Python subprocess: https://docs.python.org/3/library/subprocess.html
2. Python asyncio subprocess: https://docs.python.org/3/library/asyncio-subprocess.html
3. LiveKit EOT-Bench: https://github.com/livekit/eot-bench
4. MP-Bench: https://www.fullduplex.ai/benchmarks/mp-bench
5. llama.cpp SPEED-Bench: https://github.com/ggml-org/llama.cpp/tree/master/tools/server/bench/speed-bench
6. llama.cpp MoE cache: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md
7. GameDevBench: https://github.com/waynchi/gamedevbench
8. Roblox Studio agentic workflow: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
9. Roblox Studio MCP plugin: https://github.com/Roblox/roblox-studio-agent-plugin
