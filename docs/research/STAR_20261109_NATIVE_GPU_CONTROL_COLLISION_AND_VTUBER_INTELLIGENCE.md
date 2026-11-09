# Star AI: native GPU-control collision containment and high-performance generalist VTuber research

**Investigation and implementation:** November 9, 2026 (America/Chicago). **Scope:** isolated, offline-tested host coordinator. No game, OBS, broadcast, model, or native GPU worker was launched.

## Engineering finding

Star currently has two approaches to optional GPU workload accounting: the newer advisory OptionalGpuLeaseGate and a separate host-owned Windows supervisor using RealtimeGPUWorkLeases, HostOptionalGPUWorkerLaunchSupervisor, WindowsGPUHealthObserver and WindowsGPUWorkerControlLoop. These are NOT interchangeable sources of permission; the latter already has a fixed-command Windows process path. Converging them under one native authority remains the architectural priority.

Inspection found that WindowsGPUWorkerControlLoop.tick() used to disable the reservation ledger on concurrent polls but did not latch the process-launch supervisor off or mark the control loop permanently faulted. A first poll could continue processing an apparently good result after the second poll invalidated exclusivity. Separately, launch() returned directly from the host launcher: an unexpected adapter exception or a fault/quarantined result did not itself latch the outer control loop off.

This patch makes a poll collision permanently fault the loop and disable the native launch supervisor. It refuses to restore health after in-flight collision. Native launch exceptions are converted to a bounded, non-sensitive deferred decision, while fault/quarantined results latch the loop off. Existing lease accounting continues to hold GPU reservations until separate OS exit evidence; the code does not claim to kill Windows processes.

**This is stronger reliability, not measured faster token generation or improved win rates.** No defaults were enabled.

## Research findings with engineering implications

1. **Windows Job Objects for disposable, owner-selected workers.** Microsoft explains that jobs group related processes, and the KILL_ON_JOB_CLOSE limit can terminate child processes when the final job handle closes. On Star's dedicated machine, use this only for explicitly approved disposable optional agents, not OBS, the game, core speech, or the main model. Ensure original process handles, fixed executable and model artifact hashes, exit verification, and startup orphan sweeps. Job Objects are not a general sandbox. Source: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

2. **Game mastery requires a real-time split.** The October 27, 2026 Gym-Anything-RT research compared play while the world moves to play with a paused clock. Star needs a fast, deterministic action/reflex path and a slower vision/strategy/planning path. Only independently verified observation, allowed actions, deadlines, real outcomes and held-out seeds count as learning; avoid unapproved game-botting. Source: https://arxiv.org/search/?query=Gym-Anything-RT&searchtype=all

3. **Natural interaction requires discretion, not constant talking.** Proact-VL explores proactively selecting when a video assistant should speak. Pair short live responses, silence, interruption, grounded humor, phoneme-driven lip movement, eye focus and expressions; use a separate asynchronous lane for detailed reasoning so Star never stalls her game controller while she thinks. Clearly identify Star as AI; avoid inventing human memories, friendships, or emotional experiences. Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

4. **Roblox game making should be executable and visual.** Inspect the scene and data model before changes; generate small Luau/asset/UI edits; run static checks and Studio playtests; inspect screenshots, player behavior, client/server replication and measured performance; repair until tests actually pass. Roblox described agentic Studio changes in April 2026. Source: https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

5. **Inference on shared 8 GB VRAM is a system-level benchmark.** Compare a small GPU-resident model, smaller fast-model routing, 4K/8K/16K contexts, KV reuse, and draft-model vs n-gram speculative decoding. Track p50/p95 time to first token, actual first-audible latency, correctness, FPS 1% lows, OBS encoder/render drops, CPU load and peak VRAM. A larger model's higher raw tokens/s is not a win when it causes delayed speech or game stutter. Sources: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md and https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

6. **Voice on the CPU is worth A/B testing.** Kyutai Pocket TTS offers compact CPU-focused speech models. Compare with Star's current voice only under simultaneous real game/OBS load, with blinded human intelligibility checks, p95 first audible latency, naturalness and CPU contention. No guarantee that Pocket TTS is faster on Star's hardware. Source: https://github.com/kyutai-labs/pocket-tts

## Recommended acceptance sequence

- Synthetic collision and malformed native-worker-launch tests: no new optional admission until host reconciliation.
- Disposable Windows Job worker crash/restart rehearsal: physically observe process stop and accounting hold through uncertainty; avoid killing other PIDs.
- Nonbroadcast 60–90 minute OBS recording plus game, voice, avatar and inference: capture p50/p99 frame times, OBS drops, first-audible p50/p95, memory growth, GPU clocks and thermal headroom.
- Held-out authorized game mini-tasks: record exact map/seed, action deadline, replay and independent score. Promote a new skill only if paired improvement survives diverse unseen conditions.
- Roblox Studio build/test/repair: retain static checks, actual Studio run logs, visual screenshots and game behavior verification.
- Only after those gates, consider enabling an owner-approved optional worker profile, never automatic public streaming.

**Scope limits:** all new regressions use fakes, not real CUDA/Windows sessions. This change does not increase neural weights, install new models, control games, deploy Star, enable OBS output, or merge production main. The full native worker-exit and physical audio-stop verification still require Windows rehearsal.
