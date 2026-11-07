# STAR — Real-GPU control loop, autonomous game mastery and humanlike VTuber research
Date: 2026-11-06 (America/Chicago). Scope: opt-in STAR infrastructure; not evidence of achieved neural intelligence, faster model throughput, autonomous game mastery or a live broadcast.

## New in this change: live GPU → revocation → OS-worker loop
PR #1031 implemented owner-fixed optional-worker launches with original Popen handles; #1032 implemented a pinned GPU memory observer. They were independent surfaces. `WindowsGPUWorkerControlLoop` now joins:
1. A host-attested game/OBS/speech health sample within a tight clock-skew window.
2. An actual pinned NVIDIA GPU UUID query by `WindowsGPUHealthObserver`, running away from real-time audio, game input and OBS threads.
3. The existing `RealtimeGPUWorkLeases` reservation decisions and `HostOptionalGPUWorkerLaunchSupervisor`.
4. `HostOwnedOptionalGPUWorkers.tick` to request stops and observe confirmed worker exits after GPU pressure/monitoring failure.

The controller starts with **zero launch authority**. Even an owner-approved plan cannot start without a recent, valid completed GPU tick. A later launch after the freshness window trips a permanent fault; the operator must reconstruct/reconcile the session. Probe failures, lag, clock regressions, untrusted health, mismatched session identity and worker-reconciliation failures disable new optional workers. The loop still services previously owned stop/exit reconciliation during faults. VRAM remains charged until independent host exit confirmation. All executable recipes must be local immutable owner-selected plans. This does NOT start the private VTuber, gaming, OBS, an arbitrary viewer process, or automatic model generation.

**Critical remaining gap:** the existing `Popen.terminate()` targets the *root* process, not necessarily its descendants. A real model tool may spawn children which outlive the root. Do not treat root exit as whole process-tree shutdown. Before deploying arbitrary optional GPU workers, adopt Windows Job Objects with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; use suspended creation and assignment *before* resuming to prevent a child-spawn race; retain job handle and query its active-process count before releasing a lease. Microsoft docs: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects ; https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject . This is *process lifecycle containment*, not a file/network/process privilege sandbox. Fail closed when nesting restrictions prohibit assignment. Never attach OBS, gameplay, voice, avatar or existing owner processes to disposable jobs. Any actual Windows launch must use a separate disposable fixture and owner-approved private environment.

## STAR intelligence: evaluate improvement, not impression
GameWorld (Apr 15 2026) provides 34 browser games and 170 tasks with state-derived, verifiable successes; a finer-control protocol appeared in Aug 2026. Use its methodology to score **held-out** task success, repetitions, adaptation to variants and generalization to different controls (source: https://gameworld-project.github.io/ , code: https://github.com/gameworld-project/gameworld).

Gym-Anything-RT (Oct 27 2026) introduced 100 minigames and a pause-vs-real-time contrast. The reported 9% vs 75% pass-rate gap for one model is a **research result on that model**, not a Star benchmark (source: https://arxiv.org/abs/2610.37567). STAR must separate:
- **Reflex tier (target tens of milliseconds):** precomputed safe policies, aiming, navigation, collision prediction and explicit frame/action deadlines. No slow free-form chain-of-thought on the game thread.
- **Tactical tier (hundreds of milliseconds to seconds):** map state, goals, resources, opponent patterns, explanation and strategy changes; updates an asynchronously versioned policy.
- **Learning tier (offline/backlog):** isolated episodes, self-play against gradually harder opponents, skill drills, counterfactual replay, bounded experimentation and retrieval of trusted rules. Require held-out improvements with confidence intervals.
- **General knowledge tier:** trustworthy local manuals, game wikis, Luau docs, programming/spec references with citations, dates, uncertainty, deduped chunk retrieval, provenance and code execution tests. Never confuse synthetic experiences with real memories.

Measure: episode success, win rate over held-out seeds, deaths/hour, mistakes caused by stale frames, median/p95 observation-to-action latency, GPU memory headroom, game FPS, OBS render/encode drop %, audio first-chunk latency, interrupt accuracy and creator intervention rate. Run same seed sets before and after feature changes, with uncertainty bars. Separate training, evaluation and demonstrations to avoid memorization/benchmark leakage.

## Faster local AI on 8 GB VRAM
Prior Windows RTX 3060 Ti readings varied from hundreds of MiB free to several GiB free while utilization remained low; free VRAM is not a constant. The policy must reserve gaming and OBS headroom FIRST, then optional inference/vision/render capacity. Model routing should prefer a tiny reflex planner for deadlines; route long reasoning and coding to a separate backend or off-peak machine. CPU TTS is a candidate to avoid VRAM competition, not a guaranteed improvement.

Avoid blanket claims that a specific 9B model fits with arbitrary 32K context: CUDA kernels, KV cache, contexts, quantization and other processes dominate headroom. Test only pinned model binaries/configs; don't replace a working server merely on benchmark marketing claims. Explore prompt-prefix caching, short stable system prompts, n-gram or draft-model speculative decoding *only with an A/B control*. Official llama.cpp SPEED-Bench reports prompt/decode throughput, end-to-end latency and draft acceptance; compare identical prompts, concurrency and context lengths: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md . Record quality and both idle + game/OBS/voice loaded regimes. Reject any apparent speedup that reduces game FPS or causes speech glitches. CPU/RAM efficiency should remain a first-class optimization independent of any GPU upgrade.

Latency budget example **target, not measurement**: screenshot/event capture 15–40 ms, perception/reflex 10–40 ms, input dispatch 5–20 ms, all within a 100 ms target for short reactions. Larger reasoning tasks may take longer only if the agent proactively avoids acting on stale frames. Always measure actual p95 under load.

## VTuber: recognizably humanlike expression without claiming personhood
Proact-VL (Microsoft/ICML 2026) studies *when* a realtime gaming companion should speak, not just what it says: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ . DyaPlex (NVIDIA, June 2026) explores simultaneous listening, speech and movement, but is not plug-and-play for this hardware: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/ .

Proposed live director state machine:
- Observe gameplay, voice, viewer chat, overlays and time-aligned events separately; tag reliability and latency.
- Decide `react / speak / listen / wait / cheer / acknowledge / ask` based on interruption relevance, confidence and cooldown.
- Keep immediate speech ("Nice!", "Oops!") distinct from expensive tactical narration; do not let chatter block game control.
- Stream TTS chunks with VAD/overlap management, barge-in cancellation, phoneme-linked mouth motion, gaze/eyes/blinks and emotion-contingent pose selection. Avoid repeated catchphrases, awkward invented memories, fabricated emotions presented as fact, or incessant chatter.
- Use a persisted identity, favorite activities, evolving project goals, a bounded autobiographical *verified event* journal and natural variation in sentence length and pauses; disclose AI identity in channel details and when directly asked.
- Private recording first; log turn opportunities, false interrupts, conversation coherence, subtitle correctness, avatar lip-sync drift, viewer engagement and response latency. Rate-limit and moderate viewer-triggered tools; keep purchase, publication and high-impact account actions owner-gated. Do not impersonate real viewers/creators.

## Game and Roblox creator pipeline
The November 4, 2026 Roblox Studio MCP expansion adds per-game, per-person permission-scoped Open Cloud access, asset import, game management and monetization APIs. Roblox explicitly warns that permissions for monetization, publishing, bans, secrets and live DataStore writes have real consequences. Source: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 ; https://create.roblox.com/docs/studio/mcp-open-cloud .

STAR should create a private test game; review API permissions; import models to approved folders; run Luau linter/typechecker; playtest with verifiable game-state assertions; inspect meshes, scale, grip and UI screenshots; automatically file reproducible bugs; and retain only improvements passing real checks. Never automate a live production publish by default.

## Next experiments, in descending engineering priority
1. Windows Job Object lifecycle containment + root/descendant exit witness with a disposable subprocess and negative tests. Do NOT use arbitrary process termination; never touch an existing model server.
2. Integrate the new control loop into a trusted Windows service runner with actual independent game/OBS/voice signal producers and a dedicated telemetry thread. Keep owner enable OFF.
3. Private end-to-end Win/OBS/voice/avatar/game rehearsal with measured FPS, latency, audio-video synchronization, GPU headroom and verifiable task results. No public broadcast.
4. React/tactical/learning benchmark harness with held-out episode success, reproducibility and rollbacks. Collect gameplay moments only with game/stream privacy controls.
5. Add proactive conversational director, voice interruption and multimodal avatar expression; A/B test audience comfort and factual grounding.
6. Only then run CPU/GPU/server tuning and speculative decoding trials, comparing identical workload quality at stable memory pressure.

**Verification claim boundary:** this PR adds an integrated host control loop and deterministic tests. It does not yet contain production Windows Job Objects, independent real gameplay experiments, live broadcasts, or measured neural inference speedups.
