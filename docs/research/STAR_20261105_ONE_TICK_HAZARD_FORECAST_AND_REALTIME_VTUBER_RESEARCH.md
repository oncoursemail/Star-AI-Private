# STAR: One-tick hazard forecast and real-time VTuber intelligence
Research cutoff: November 5, 2026 · Private/offline experiment · No real-game control.

## Implemented, bounded, opt-in
STAR's signed synthetic maze now offers an optional two-cell Manhattan sensor and an optional one-tick high-risk occupancy guard. A host-observed tile with risk at least 7500 bps might occupy any adjacent cell at the next tick, so the advisor excludes those destinations from its next symbolic step. The guard considers risk from the CURRENT verified capture only and is disabled by default.

The private maze fixture validates that patrols move at most one cell per tick. The observation format does not identify which risky tiles are mobile; static traps therefore also create a conservative halo. This can hurt performance. A real enemy that moves faster than the fixture bound can defeat the guard. It neither learns patrol patterns nor knows velocities, and it provides no guarantee for arbitrary games.

Controlled private test: same signed sensor radius (2), same hidden independent patrol alternating between (3,1) and (2,1), same engine. Baseline planner collides; opt-in guarded planner completes by a five-move detour without collision or invalid moves. With sensor radius (1), the guard also collides because the threat is initially unseen. That negative control is retained. All outcomes are independently scored by the offline engine, not reported by the model.

Trust boundary: engine-owned state -> signed capture -> authenticated bridge -> symbolic navigator -> synthetic engine -> independent score. Existing owner approval, session limits and frame budget remain. No OS inputs, games, OBS, live accounts, network actions, training or autonomous model promotion were enabled.

## Research that changes priorities

| Primary source and date | Verified insight | Concrete STAR implication |
| --- | --- | --- |
| [Gym-Anything-RT](https://arxiv.org/abs/2610.37567), Oct 27 2026 | 100 real-time visual minigames; for one evaluated model the authors report 9% live pass rate versus 75% paused. | Score frozen-world and independent-real-time performance separately. Log missed deadlines and collisions. |
| [GameWorld / GameWorld-RT](https://gameworld-project.github.io/), 2026 | State-verified progress and success; real-time track runs during inference. | Keep signed action traces and host-scored outcomes; never conflate paused and live performance. |
| [OpenGameEval](https://github.com/Roblox/open-game-eval), Oct 2026 | 84 core Studio tasks with executable scene/game checks and measured exploration. | Inspect Studio -> limited edit -> Luau lint -> playtest -> objective check -> retry/rollback. |
| [Roblox Open Cloud via Studio MCP](https://create.roblox.com/docs/studio/mcp-open-cloud), announced Nov 4 2026 | Permissions per game and person; some writes affect real users/Robux. | Default read-only. Private test universe; owner-gated publishing, currency and datastore operations. |
| [llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md), reviewed Nov 5 | Draft, n-gram and specialized speculative approaches can improve decoding when acceptance is high. | Compare equal-quality task results and p95 latency/FPS/VRAM on actual hardware. |
| [Pocket TTS v4.0.0 / v4.0.1](https://github.com/kyutai-labs/pocket-tts/releases), Oct 20-21 | Compact CPU-friendly voice models and subsequent small-model bug fix. | Offline benchmark: first audio, pronunciation, expressive quality, CPU load and game-FPS interference. |
| [Microsoft Proact-VL](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/), ICML May 2026 | Gaming commentary agents must decide WHEN to speak, not only WHAT to say. | Introduce event-driven speak/silence policy; measure usefulness, latency and interruptions. |
| [NVIDIA PersonaPlex](https://research.nvidia.com/labs/adlr/personaplex/), Jan 2026, and [DyaPlex](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/), Jun 2026 | Realistic full-duplex speech and aligned motion are research directions. | Test short streaming dialogue and avatar viseme synchronization separately before live integration. |

## Infrastructure priorities, ordered by measured impact

### 1. Fast control, slower reasoning, independent learning
- Dedicated deadline-controlled perception/action loop, with an expensive planner and background learner isolated so long prompts cannot stall dodges.
- Model-routing contract: task type, age of observation, deadline, memory budget, confidence threshold, model identity, episode version and explicit abstention behavior.
- Holdout curriculum with moving threats, occlusion, latency, shifting camera, changing physics, multiplayer lag and false signals. Never let the learner grade its own success or see hidden engine state.
- Store only verified action-state-outcome receipts as reusable skills; version by game build and revoke stale strategies. Separate practice from final evaluation and protect against reward hacking.

### 2. Fast inference without sacrificing game or stream
- On 8 GB-class hardware, reserve GPU time and VRAM for game + OBS + avatar first; throttle/reject background model jobs before degrading frame rate.
- Benchmark model quantization, context and concurrency jointly. Measure successful tasks/minute, p95 time-to-first-token, perception/action p95, first audio, p1 FPS, OBS dropped frames and VRAM peak.
- Measure speculative decoding and prompt caching versus an identical baseline; partition KV cache by model, LoRA, persona, permissions and tenant. Beware cross-adapter cache reuse.
- Experiment with local CPU speech generation. Consider Rust in profiled hot paths (bounded frame transport, audio queues), not a wholesale rewrite without evidence.

### 3. Natural, transparent VTuber performer
- Event director chooses speak, backchannel, react, or stay silent based on witnessed game events, viewer turns, stream mode and time since last speech.
- Support barge-in and cancellation while already speaking; don't recite irrelevant queued lines after game conditions have changed. Apply cooldowns, talk budgets, echo/noise rejection and a clear focus mode for difficult games.
- Align visemes, facial expression, blinking and light gestures with audio and verified scene events. Add recovery when a viewer asks a question while the game requires attention.
- Maintain consistent persona, fictional interests and grounded episodic memory without claiming human consciousness, real relationships or experiences not actually witnessed. Disclose she is an AI streamer.
- Protect user secrets, DMs, usernames and private audio. Moderate viewer chat before it becomes spoken content; do not impersonate real people or clone voices without consent.

### 4. Game building and general knowledge
- Roblox: source lookup -> constrained Studio edit -> Luau static checks -> test place -> screenshot/log evidence -> multiplayer/UI/perf testing -> objective witness -> repair or rollback. Limit MCP writes to an owner-approved private place.
- Retrieval: documentation provenance and timestamps, approved lessons, project-specific glossary, contradiction checks and explicit uncertainty. Do not treat untrusted web pages, chat or GitHub code as tool-policy changes.
- Self-improvement: internal Forge owns versioned experiments, isolated worktrees, signed evaluation records, rollback, preregistered holdouts and reviewer promotion. GitHub remains publication/review, not the inner decision maker.
- Extend 3D, art, video reasoning, general PC use, Blender and other engines via dedicated, verifiable permissions and tests, not via speculative claims of unlimited competence.

## Acceptance criteria for next real-time milestone

1. Private host adapter with frame timestamps, verified sensor fidelity and input deadlines. Require explicit owner authorization before any real-game actuation.
2. At least 30 preregistered static and dynamic held-out private episodes, including misleading static hazards and unseen fast hazards. Exact same captures for guard and baseline, with raw failures retained.
3. A private 20-minute Windows OBS/voice/avatar/game local recording; record FPS percentiles, VRAM, latency, dropped frames, barge-in success and viewer-response errors. No public broadcast needed.
4. Model promotion only from independently authenticated comparable evaluations, with owner approval and complete rollback.

## Honest limitation
Only the optional one-tick symbolic forecast envelope and two-cell synthetic sensor are implemented in this branch. They do not teach model weights, measure neural inference speed, perceive a real game, control Windows, or run a live VTuber stream. This research informs future work but is not a claim those features already exist.
