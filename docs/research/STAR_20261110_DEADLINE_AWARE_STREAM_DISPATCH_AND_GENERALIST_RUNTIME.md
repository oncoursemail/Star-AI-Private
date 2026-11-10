# STAR — Deadline-Aware Stream Dispatch and Generalist Runtime Research

**Date:** 2026-11-10  
**Scope:** private source branch star/next  
**Status:** research + opt-in control-plane implementation; no production rollout

## Executive finding

STAR already has substantial pieces that should be preserved rather than rewritten:

- star/stream_qos.py measures route p95, checks CPU/RAM/VRAM headroom, issues one-shot reservations, defers background work during live gameplay, and quarantines expired workers until a trusted stop acknowledgement.
- star/stream_brain_governor.py binds those decisions to host telemetry, StarStage, and physical audio/worker acknowledgements.
- star/stream_load_governor.py supplies pressure/hysteresis advice; it does not execute or schedule workers.
- star/orchestration.py validates task DAGs and read/write resource conflicts, but explicitly does not spawn subagents.
- docs/ARCHITECTURE.md already protects llama.cpp prompt-prefix reuse by keeping stable system/history bytes separate from per-turn volatile context.

The missing layer was a bounded pending-work queue before the existing governor. Without it, callers repeatedly submit work and receive an immediate admission/defer result; there is no shared place to order urgent speech, fresh game perception, commentary, research, night-school training and asset rendering, or to discard obsolete queued frames.

This update adds star/stream_work_dispatcher.py. It orders metadata-only InferenceJobs, then delegates every actual admission to the existing StreamBrainGovernor.admit. It does not replace telemetry, QoS, model routing, the worker host, or the physical stop protocol.

## Research findings applied

### 1. Priority queues are useful only when paired with deadlines and queue limits

NVIDIA Triton documents multiple priority levels, per-priority queue policies, maximum queue sizes and timeout actions. Higher-priority requests can bypass lower-priority work; requests at the same priority remain ordered. Triton also documents that dynamic batching trades latency for throughput and should be tuned against an explicit latency budget.

Sources:
- https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/batcher.html
- https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/scheduler.html

STAR application: use a small fixed priority policy, explicit deadlines, bounded queue length, and no unbounded batching delay. Do not add Triton as a dependency merely to obtain a priority queue.

### 2. Prefill and decode interference is real, but disaggregation is not a single-GPU optimization

TensorRT-LLM explains that context/prefill and token decode have different compute characteristics. When both share a GPU, prompt processing can delay token generation and worsen token-to-token latency. Disaggregated serving separates those phases onto different GPU pools, but requires KV-cache transfer and introduces its own coordination/transfer overhead.

Source:
- https://nvidia.github.io/TensorRT-LLM/features/disagg-serving.html

STAR application: preserve the current local-first llama.cpp path and stable prefix cache. Do not deploy a multi-GPU disaggregated stack on the owner's single RTX 4060 8 GB. Revisit it only if separate Brain 1/Brain 2 accelerators, network bandwidth, and a matched mixed-workload benchmark justify the complexity. For the current gaming PC, prioritize CPU speech where calibrated, reserve VRAM for the game, and defer research/training/render work while the stream is active.

### 3. Human-feeling voice behavior depends on correct interruption accounting

LiveKit documents that when speech is interrupted, its conversation history is truncated to the portion the listener actually heard. It also distinguishes interruption detection from ordinary turn completion and provides explicit false-interruption handling.

Source:
- https://docs.livekit.io/agents/logic/turns/

STAR application: keep speech text, audible PCM, avatar motion, and conversation memory tied to the same output epoch. Never store the unheard tail of a cut-off sentence as if the audience heard it. Continue to measure VAD, semantic end-of-turn, addressee detection, interruption precision/recall, first audible PCM, and avatar synchronization separately.

### 4. Roblox's new Studio MCP/Open Cloud permission model is per-game and risk-tiered

Roblox's current Studio MCP documentation says permissions are stored per game and enforced by Studio. Safe, Balanced, Full access and Custom levels exist; Full access includes high-risk scopes that can spend Robux, affect players or publish to a live game.

Sources:
- https://create.roblox.com/docs/studio/mcp-open-cloud
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic

STAR application: use read/inspect and private test-place workflows by default. Keep live publishing, monetization, player-data and spending scopes separate and owner-approved. Build from a reviewable plan and validate against the original task manifest rather than treating generated code as proof.

### 5. Game creation and game mastery need different evaluations

GameDevBench evaluates real multi-file game-engine work and visual feedback; OpenGameEval evaluates Roblox Studio tasks; real-time game benchmarks distinguish paused reasoning from acting while the environment continues to change. These should remain separate score lanes.

Sources:
- https://github.com/waynchi/gamedevbench
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.37567

STAR application: assess creator capability through plan/build/run/inspect/playtest/repair, and gamer capability through scenario-balanced real-time trials, held-out maps/seeds, action latency and transfer to unfamiliar mechanics. Never infer gameplay mastery from code-generation scores.

## New implementation: StreamWorkDispatcher

The dispatcher is deliberately narrow. It adds the missing ordering layer without duplicating the governor's resource decisions.

| Work kind | Base priority | Rationale |
|---|---:|---|
| speech | 100 | Keep live conversation responsive |
| vision | 90 | Fresh game/scene evidence |
| commentary | 70 | Useful but not more urgent than speech/perception |
| research | 30 | Background work |
| training | 20 | Background learning |
| render | 10 | Deferrable asset work |

Implemented behavior:

- Bounded queue (default 64) and bounded session ID ledger (4,096).
- Per-kind queue cap (32 by default).
- Monotonic clock and explicit job deadlines.
- Earliest-deadline ordering within a priority class, with FIFO tie-break.
- Background aging capped at +30; research/training/render cannot age past the interactive commentary class.
- Latest-wins coalescing for keyed vision/commentary/research/training/render jobs; speech is never coalesced.
- Duplicate/replayed job IDs are rejected for the dispatcher's lifetime.
- Stale/expired work is removed before admission.
- Up to four admission attempts per tick; a transiently blocked high-priority item does not prevent a lower-priority admissible item from using a safe route.
- Permanent governor rejections are dropped; transient resource/telemetry denials remain queued until their deadline.
- One admission callback is in flight at a time. Pending work may be cancelled; in-flight admission cannot be falsely reported as stopped.
- Aggregate-only status omits job IDs, coalescing keys, prompts, chat, audio, frames, and model outputs.
- Every admitted result must carry the actual BrainLease returned by the governor.

### Host integration contract

    dispatcher = StreamWorkDispatcher(admit=stream_brain_governor.admit)
    dispatcher.submit(inference_job, coalesce_key="game-window-1")
    decision = dispatcher.dispatch()

    if decision.status == "admitted":
        # The trusted host rechecks event/frame freshness and the job deadline,
        # launches only its fixed approved worker, then acknowledges real stop.
        launch_approved_worker(decision.job, decision.admission.lease)

launch_approved_worker above is a host-owned placeholder, not a function supplied by this module. The dispatcher never launches it. The host must use the same monotonic clock domain for enqueue, dispatch and governor admission.

## Broader STAR capability roadmap

### Intelligence and general knowledge

1. Keep model identity, prompt/template, tools and grading pinned when comparing model or memory changes.
2. Expand the existing general-knowledge development suite across science, history, math, programming, game design, media literacy and current events.
3. Build a separately held-out set with source-grounded expected answers, temporal-update questions, contradiction resolution and explicit abstention scoring.
4. Keep factual retrieval, reasoning, tool execution and memory recall as separate metrics. A larger memory or longer answer is not itself intelligence.
5. Require evidence provenance: observed, source-retrieved, inferred, model-generated, or experimentally verified.

### Gaming and game creation

1. Reflex/control loop: short, fresh observations and strict action deadlines.
2. Tactical loop: positioning, combat, route choice and objective progress.
3. Strategic loop: longer plans and resource management.
4. Practice loop: scenario-balanced attempts, failure taxonomy, targeted drills and held-out transfer.
5. Creator loop: inspect project → plan → implement → static checks → run → visual inspect → playtest → repair → regression.
6. Keep Roblox, Godot, Unity and Blender evaluations separate; do not treat an engine-specific score as universal creator intelligence.

### Natural AI VTuber

Measure these independently rather than collapsing them into a misleading "human-likeness" score:

- Correctly recognizing who is speaking and whether they address Star.
- Correct response, backchannel, yield, and silence decisions.
- False interruptions and missed interruptions.
- First audible PCM and p50/p95 response delay.
- Audible completion vs generated-text completion.
- Voice delivery consistency and prosody.
- Avatar/viseme timing against actual audible audio.
- Grounded gameplay commentary and correct silence during low-information moments.
- Long-session drift, stale-event suppression, OBS loss and audio underruns.

The goal is expressive, socially aware AI interaction while remaining truthful that Star is an AI.

### Multi-agent and long-horizon work

star/orchestration.py currently validates DAGs and resource conflicts but does not run workers. The next substantial architecture step should be a host-owned multi-agent runtime with:

- Role adapters for research, coding, UI, animation, environment, review and integration.
- Bounded parallelism and explicit task deadlines.
- Read/write resource locks from TaskPlan.
- Per-worker tool scopes and separate scratch worktrees.
- Artifact handoff with source hashes and reproducible environment identity.
- Cancellation that is not treated as process termination until the host verifies exit.
- Independent integration tests and rollback before any candidate is promoted.

Do not let a worker modify the tests or protected evaluation gates that grade its own work.

## Performance and acceptance plan

### Offline/CI

- Run tests/test_stream_work_dispatcher.py.
- Run the existing stream QoS and StreamBrainGovernor tests.
- Run the full offline Python suite, Ruff, Pyright and protected-path checks.
- Verify the dispatcher is not exposed as an LLM tool and that no new package dependency is introduced.

### Private Windows mixed-workload rehearsal

On the actual RTX 4060 8 GB machine, run 30–60 minutes with a real game, local inference, OBS, TTS, avatar rendering, viewer-like test events and background work. Capture synchronized host-monotonic intervals for:

- Queue wait, admission latency, first visible content and first audible PCM.
- p50/p95/p99 speech response and inter-chunk gaps.
- Game FPS p10/frame-time p95.
- OBS render/encode/network dropped frames.
- Audio underruns and output-stop latency.
- CPU utilization, RAM, GPU utilization and VRAM.
- Correct response/silence and stale-frame rejection rates.

Compare the current direct-admission path against the dispatcher with identical tasks and randomized order. A win requires better live p95 or fewer missed deadlines without worsening game frame-time, OBS loss, audio underruns, task quality or false-interruption rate. If no improvement is demonstrated, keep the dispatcher disabled.

## Boundaries and outstanding work

- This module is an opt-in control-plane queue; it is not wired into the Windows worker launch loop yet.
- No model weights, prompts, memory databases, routes, settings, GPU processes, audio devices, OBS sessions, games or Roblox places were changed.
- No model speedup, intelligence gain, game mastery gain or human-equivalence claim is made.
- Local isolated verification: 18 focused tests passed and Python compilation passed.
- Ruff is not installed in this scratch environment.
- Full repository tests, Pyright, GitHub Actions, Windows GPU measurements and the private streaming rehearsal remain outstanding.
- The connected Remote Desktop Commander account had no remaining remote-call quota in this run, so the actual owner machines were not inspected or modified.

## Primary references

- NVIDIA Triton dynamic batching, priorities, queue caps and timeout policies: https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/user_guide/batcher.html
- NVIDIA TensorRT-LLM disaggregated prefill/decode serving: https://nvidia.github.io/TensorRT-LLM/features/disagg-serving.html
- LiveKit voice turn detection and interruption history truncation: https://docs.livekit.io/agents/logic/turns/
- Roblox Studio MCP/Open Cloud per-game scopes: https://create.roblox.com/docs/studio/mcp-open-cloud
- Roblox agentic plan/build/test workflows (April 15, 2026): https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- GameDevBench (333 Godot tasks, ICML 2026): https://github.com/waynchi/gamedevbench
- OpenGameEval: https://github.com/Roblox/open-game-eval
- Gym-Anything-RT (October 27, 2026): https://arxiv.org/abs/2610.37567
