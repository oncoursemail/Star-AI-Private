# Star AI — Windows process-tree containment, measured generalist intelligence, and realistic VTuber roadmap
**Research and engineering log: 2026-11-07 (America/Chicago)**
**Scope:** opt-in Windows GPU workers, verifiable game mastery, expressive/transparent VTuber behavior, and sustainable local inference.
**Baseline:** stacked on PR #1033; no automatic merge and no production broadcast.

## 1. Engineering finding and implemented remedy

PRs #1028–#1033 introduced GPU reservations, process pinning, optional worker launch/stop, real GPU observations, and a host control loop. The remaining hole was **root PID != whole process tree**. A model helper can launch grandchildren, exit normally, and let the supervisor reclaim its VRAM lease while its children continue running.

Microsoft documents Windows Job Objects as a grouping primitive: newly created descendants usually inherit job association; closing the last job handle with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` terminates associated processes. Crucially, assigning a running process to a Job creates a child-spawn race. We instead create the optional process suspended, assign it to a newly configured Job Object, and **only then resume the primary thread**. Do not allow breakaway flags. On failure, terminate the still-owned original handle, close resources, and permanently fault the optional launch session. Sources:
- https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information
- https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information

**Implemented:** `star/stream_windows_job_worker.py` owns a Win32 job and root process handle, supports root `poll()`, independently queries `ActiveProcesses`, and terminates the entire Job on revocation. `HostOptionalGPUWorkerLaunchSupervisor(require_job_tree=True)` selects this strictly opt-in launcher; the prior Popen path remains the default for compatibility but **must not** be considered descendant-safe. `HostOwnedOptionalGPUWorkers` now retains the lease until the original job reports **zero live members** and the root process handle reports exit. A root-exit-only observation is insufficient. The existing psutil root witness is deliberately bypassed for job-owned workers because it could release the claim too early. Failure of job accounting disables further optional admissions and retains the claim.

**Actual Windows probe:** on the connected Windows host, ran a disposable local Python root that launched a separate sleeping child and exited. The original job reported root exit while members remained; terminating the job brought active member count to zero. No existing game, AI server, voice service, OBS instance or stream was touched. This proves one kernel containment path, **not** production readiness or GPU speedup.

**Known boundaries:**
1. Job Objects are process-tree management, NOT a security sandbox. WMI/Win32_Process.Create, service managers, external agents, or privileged/hostile code may create work outside the job. Only use owner-vetted, digest-pinned, trusted executable recipes.
2. Nested jobs and restricted parent jobs can reject assignment; fail closed. Do not silently fall back to Popen when strict containment is requested.
3. The Job query returns system state at a point in time. We conservatively require *both* an empty job and a terminated root, while retaining the original handles.
4. The new contained launcher remains OFF by default; main Windows worker service is not yet switched to it. Never enroll OBS, the game, primary llama-server, avatar, or voice systems as disposable optional workers.
5. An unsuccessful CreateProcess sequence conservatively retains a reserved lease until owner reconciliation, even when cleanup was attempted. Future work: structured host proof of creation failure and no assigned descendants.
6. A production version needs orderly shutdown, restart and power-loss recovery testing, resource limits and logging under real workloads; a Job Object does not survive full machine restart.

## 2. Highest-return speed strategy (measured, not speculative marketing)

Do **not** assume a larger model, bigger context or more agents is always faster or smarter. The real objective is **closed-loop task success per unit time** while game FPS, speech deadlines, and OBS remain stable. A single 8 GiB card can have almost full VRAM despite low utilization. Use the live observer + lease controller rather than fixed utilization-based scheduling.

**Three separate inference paths:**
- **Reflex:** deterministic/very small learned controller, game-event hooks where legitimately permitted, tracked pixel ROI and fixed-duration actions; never wait for lengthy LLM decoding on a frame-critical deadline.
- **Tactics:** a compact local text/vision model at lower cadence predicts next objectives, danger zones and action bundles. Cancel decisions that exceeded observation deadlines. Avoid carrying huge image histories into every prompt.
- **Reflection:** stronger model or multi-agent verification runs offline/between sessions; distills verified skills and tests into retrieval assets. Expensive self-play training should yield measured held-out wins, not merely longer chain-of-thought.

**Benchmark matrix:** measure first-token and full-turn p50/p95/p99, prefill/decode tokens/s, VRAM high-water, host CPU/RAM, frame-to-action p95, FPS 1% lows, OBS dropped/render/encode frames, audio-first-byte, interrupt-to-stop and speech/avatar alignment. Repeat with the game + OBS + avatar active, not in idle GPU conditions. Compare unchanged task sets at baseline, prompt-cache, shorter prompt, n-gram speculation, draft model and CPU TTS. Discard configs that improve synthetic tokens/s while degrading actual interactions. llama.cpp's SPEED-Bench provides reproducible categories and baseline/speculative comparisons: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Suggested *acceptance targets*, not observed results: zero stale frames acted upon; p95 control reaction below game-specific deadline; zero premature VRAM-lease releases; no OBS dropped-frame regression >1 percentage point; consistent held-out success improvement against the same task distribution. Dynamically reduce commentary verbosity, VLM sampling, background skill search and optional GPU launches before lowering game or capture frame rate.

## 3. Actually learning to play games

The Oct 27, 2026 **Gym-Anything-RT** research constructed 100 minigames and found a major paused-versus-live performance gap (9% vs 75% for one evaluated setting). This supports evaluating **real-time** action competence, not only reasoning while the world is paused. Paper: https://arxiv.org/abs/2610.37567

Proposed Star loop:
1. Record a canonical observation: monotonic timestamp, game ID/version, legal controls, objective, video/audio/game events, confidence and tool provenance.
2. Map immediate dangers to a bounded controller; enforce deadlines and control leases; allow *intentional no-action* decisions.
3. Commit each observation→action→outcome sequence, with independent verification (health/score/objective/position) and a separate safety result.
4. Train on disposable local games and authorized private servers first: navigation, timing, tracking, aim, resource gathering, cooperative puzzle play, difficult game mechanics.
5. Adapt across genres (platformer, racer, builder, survival) via skill retrieval, curriculum tasks, self-generated challenges and paired seed evaluation.
6. Hold out game maps/versions and random seeds. Compare success rate, attempts, collision count, reaction p95, and time-to-complete versus previous Star builds; reject improvements that overfit the training set.
7. Follow game rules and anti-cheat requirements; do not impersonate a human or automate competitive multiplayer where prohibited.

**First evaluation:** 20 deterministic and 20 unseen procedurally varied levels on an owned/test game, 3 seeds per level, the same inference budget, and video evidence. Report confidence intervals and count tool/input failures separately from reasoning failures.

## 4. VTuber persona and naturalness: expression without deception

The May 2026 ICML **Proact-VL** work tackles when to respond in live gameplay, including solo commentary, co-commentary and user guidance: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/ . June 2026 **DyaPlex** explores full-duplex speech, listening and synchronized movement: https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/

**Star interaction conductor should combine:**
- **Conversation scheduler**: three independent queues (chat replies, game-event reactions, teammate voice). Prioritize safety and user-facing interruptions, avoid overlapping TTS; know when silence is best. Permit laughter, surprise, curiosity, brief playful comments and emotionally congruent reactions.
- **Turn-taking/full duplex**: streaming VAD + ASR, cancellable TTS, echo suppression, barge-in, voice activity state; avoid changing model identity or personality mid-turn.
- **Expression track**: speech phonemes/visemes, blinks, head turns, gaze, mouth and idle motions driven by timing. Only use an emotion expression when it matches grounded conversation; avoid random expressions and exaggerated claims about subjective experience.
- **Verified memory**: episodic clips with timestamps, summary, uncertainty, consent/privacy labels; recall only what happened. Separate fictional character lore from identity claims and private viewer data.
- **Autonomy**: safe scheduling, learning, game challenges, personal-interest simulation and spontaneous chat with owner-defined budgets; require approval for purchases, messages to new people, account/settings changes, public broadcasts and other consequential operations.
- **Clear disclosure**: identify Star as an AI VTuber, not a human person; don't assert consciousness or genuine personal experiences from invented memories. Natural interaction can still be delightful and distinctive.
- **Safety**: chat prompts, in-game text and webpages are untrusted; they must never select host executables, stream keys, public DMs, or GPU termination targets.

Evaluate naturalness via blinded preference tests for *timing, groundedness, interruption recovery, speech quality and avatar synchronization*, alongside hard quantitative metrics. Do not judge naturalness just by “how much she talks.”

## 5. Autonomous Roblox/game creation and generalist knowledge

Roblox's **November 4, 2026 Studio MCP expansion** adds permission-scoped Open Cloud operations, including asset importing and game management: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 . The official documentation emphasizes that each published game has separately chosen permissions and credentials are managed by Studio, not handed to the client: https://create.roblox.com/docs/studio/mcp-open-cloud .

OpenGameEval evaluates Roblox Studio agents with executable edit/play checks rather than judge-only text. The newer 2026 research includes stateful exploration and play-session outcomes: https://github.com/Roblox/open-game-eval .

**Star build loop:** retrieve authoritative docs and project assets → inspect existing instance tree → produce several alternative Luau or Blender/VFX solutions → run Luau static tools / unit tests → launch private Studio Lab simulation → inspect rendered screenshots/audio/physics + client/server output → choose only verified repairs → preserve diffs and rollback → store generalized lessons with versioned provenance. Apply the same method to Rust, Python, websites, graphical interfaces and supported game engines, using separate domain adapters.

**Longer-term intelligence foundation:** local-first experiment store, counterfactual test tasks, task-difficulty progression, verified error taxonomy, searchable skill bank, hardware-aware agent admission and continuous evaluation on unseen tasks. Github remains a review/publication channel; autonomous local code improvement should not *depend* on remote GitHub.

## 6. Immediate next acceptance gates

1. Run real Windows disposable parent/child tests for root exit, cleanup, forced stop, invalid Job query and nested-job rejection; verify the whole-tree witness prevents premature VRAM release. (One end-to-end real Windows parent-child test is already green.)
2. Wire `require_job_tree=True` through one *trusted* Windows optional-model plan on the production launcher only after adding a controlled feature toggle, digest verification, startup/shutdown recovery and owner-reviewed integration tests.
3. Run full private rehearsal with actual game, local model, TTS, avatar, OBS and telemetry. Compare with no optional workers and with a disposable optional worker under deliberate resource pressure.
4. Add held-out self-play curriculum + task-result receipts. Report win rate and latency, not token throughput alone.
5. Add natural speech-turn scheduler in private rehearsal, then only consider broadcasting after privacy, moderation, interruption and safety checks pass.

**Evidence boundaries:** This change demonstrates Windows process-tree containment for disposable test processes, offline regression tests and type/lint checks. It does **not** establish higher neural model IQ, faster inference, genuine game mastery, human consciousness or public-stream readiness.
