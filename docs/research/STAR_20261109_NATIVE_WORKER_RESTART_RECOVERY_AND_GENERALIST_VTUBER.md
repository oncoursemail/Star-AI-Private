# STAR AI — crash-safe optional GPU work, generalist game intelligence and a believable VTuber
**Independent technical research, 2026-11-09. Code is opt-in and offline-tested; no Windows GPU process control or broadcast was performed.**

## 1. The high-priority weakness found in the current stack

STAR's `StreamLoadGovernor` evaluates fresh game, OBS and GPU conditions; the optional GPU lease gate added in #1087 keeps two workers from separately spending the same *estimated* VRAM headroom. However, its ledger is held entirely in Python process memory. If that process crashes or is upgraded, optional worker processes or CUDA contexts may still exist. A newly constructed ledger previously started empty, and `enable(owner_approved=True)` could rearm it without any evidence that the old workers had exited. It also generated identifiers like `star-gpu-1-1` that could recur on restart: a late old worker's stop callback could accidentally release a *different* active new worker's reservation. This is an ABA-like identity reuse problem.

This is especially relevant to an 8 GB RTX 4060 gaming/OBS setup. The native process and GPU-resource reality survives a Python ledger restart; treating a new ledger as truth would erase the safety budget.

### Implemented in this pull request

- Every newly constructed gate generates a distinct, randomly namespaced **non-secret** lease identifier (128 random bits). The previous lease ID from one gate instance will not refer to a new worker in another instance, except with negligible collision probability. It is not a credential or proof of worker ownership.
- On **every disabled-to-enabled transition**, `enable()` now requires explicit owner opt-in *and* an independently trusted native-host assertion that the optional worker set is quiescent: `host_verified=True, optional_workers_quiescent=True`. Without both, the gate stays disabled and refuses new leases.
- Existing live reservations must still be physically stopped/acknowledged before rearm; new flags do not bypass that latch.
- Focused offline regressions cover missing/invalid startup evidence, delayed stop callback after a simulated process restart, and the preexisting pressure/expiry/concurrency invariants.
- No new process spawning, GPU allocation, input injection, viewer chat, OBS control, Internet access or publishing is implemented; this does not change model weights or prove a faster model.

**Important trust boundary:** A Python boolean is not a native process sweep. The calling Windows host must inspect its actual child process/Job Object registry, enforce its source identity and independently make this assertion; a language model, viewer or chat message may not supply it. A false native attestation is outside this gate's ability to detect. Until this integration is implemented and independently verified, do not enable GPU leases in a real gaming broadcast. An old worker on a disconnected host cannot safely be assumed gone.

## 2. Native Windows host contract — critical integration work still missing

The native host should maintain a durable, owner-controlled optional-worker registry *outside* each Python gate process, bound to boot identity, Job Object identity, PID **and process creation time**, worker purpose, and the associated lease instance. On supervisor restart:

1. Freeze optional GPU admissions, preserve gameplay and critical speech paths, and stop issuing prior work tickets. Do not trust Python's restored counters.
2. Enumerate *all* registered optional model/vision/TTS-experiment/game-practice workers, including children. Use Windows Job Objects to constrain launched worker process trees; explicitly disallow or audit breakaway. Job Objects can terminate their associated processes when the last handle closes with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, but this must be configured and tested, not merely assumed.
3. Ask all optional workers to stop; escalate only within their isolated host-owned process jobs after a bounded timeout. Do not kill the game, OBS, avatar or other unrelated apps. Ensure a worker's PID was not recycled by checking identity/creation time.
4. Wait for **verified exits** of the whole optional worker set, check CUDA/graphics resources have settled using trustworthy telemetry when available, and quarantine if any worker cannot be enumerated or stopped. GPU occupancy falling alone is not enough to prove worker identity.
5. Issue a *fresh* authenticated native sweep assertion to `enable(owner_approved=True, host_verified=True, optional_workers_quiescent=True)`. Complete warmup of `StreamLoadGovernor` with fresh interval samples. Only then admit new optional work with pre-step reviews.
6. For every ticket, keep a native worker-ID binding; never treat `OptionalGpuDecision.action == "run"` as permission to execute. Owner policy, software isolation, gameplay fairness and independent OS watchdog are separate boundaries. On stop, wait for the **actual process exit** before calling `acknowledge_stopped(... physical_worker_stopped=True)`.
7. Log only aggregate safety counters and redacted structured events. No game screenshots, audio, chat, credentials, full command lines, or viewer identifiers should be collected by this ledger.

Microsoft documents Job Objects and the kill-on-last-job-handle behavior, but not every child creation path automatically joins a job (notably Win32_Process.Create). Host integration tests must explicitly exercise this limitation: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

NVIDIA's NVML supports board/device telemetry and process queries, but compute-process APIs are **not** complete graphics-process enumerators and Windows WDDM has distinct memory accounting semantics. A `nvidia-smi` list or `usedGpuMemory` is not sufficient evidence of a complete worker sweep: https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html and https://docs.nvidia.com/deploy/archive/R550/nvml-api/structnvmlProcessInfo__v1__t.html

**Hardware pilot acceptance:** create a sacrificial optional GPU worker, kill/restart only the Python ledger while keeping that worker alive, and prove the new gate refuses admission until the native host detects and stops it. Repeat with PID reuse, delayed callbacks, OBS scene changes, stale telemetry, service restart, power-loss recovery, and two simultaneous optional requests. Never do this on a live stream.

## 3. Intelligent, fast and resource-aware runtime: a practical architecture

**Priority lanes rather than a monolithic super-agent:**

| Lane | Role | Hard rule |
| --- | --- | --- |
| Real-time | Game observation, urgent action, owner interrupt, VAD/voice decisions | Bounded action deadlines; never await research/training |
| Conversational | Viewer question, brief grounded commentary, voice+rig expressions | Full-duplex/interruptible; cancel stale content; idle silence is valid |
| Deliberative | Solve complex puzzles, research mechanics, plan code/art, retrieve sources | Opportunistic CPU/GPU leases; result must be tied to original scene/goal |
| Practice | Private game practice, Studio Lab and verified skill acquisition | Isolated, scored, rollbackable; cannot seize public game controls |
| Maintenance | Backups, local knowledge indexing, model experiment evaluation | Lowest priority; suspend under frame/OBS pressure |

Use two clocks: a strict host monotonic timestamp for pre-action validity and a recorded wall-clock timestamp for documentation. Preserve source-epoch identity when changing scenes or restarting a game. Cancel/defer optional tool results tied to stale scenes rather than narrating obsolete facts.

**Actual performance experiments, not benchmark folklore:**
- Test default local model against small fast-path model routing; use a reviewer/verifier for complicated Luau, Blender/rigging and safety-critical code, not for every instant reaction.
- Test quantization/shorter context/prompt caching and llama.cpp speculative decoding separately. Speculation can lose throughput when draft acceptance is poor or GPU memory pressure rises; record *accepted tokens and end-to-end response latency*, not a single tokens/sec headline. Current llama.cpp documentation: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- The RTX 4060 8 GB should reserve memory for the game, OBS and avatar before loading optional models. Measure true activation/KV-cache growth and host graphics pressure, not model-file size alone. Use CPU speech or very small TTS only if it demonstrably avoids gameplay stalls.
- Optimize repeated VLM calls with event/scene-change triggers, in-frame ROI crops and temporal compression. Compare misses on critical events to avoid excessive visual throttling.
- Pre-register A/B thresholds: e.g. improve P50 first-audible latency by >=10% **without** worsening game-frame P99 by >5%, OBS loss by >0.5 percentage points, or safety/answer accuracy. Report confidence intervals across comparable episodes, warmups excluded; save configs/hashes. These are *proposed experimental gates*, not measured gains.

## 4. Teach STAR to play games well, rather than merely describe games

Gym-Anything-RT (Aggarwal/Welleck, 2026-10-27) built 100 time-sensitive visual minigames and finds large drops when play happens while the environment keeps moving. The paper separates paused and real-time evaluation, which is essential for STAR: https://arxiv.org/abs/2610.37567

**Four loops to implement and independently validate:**
1. **Perceive:** sample authorized game frames and HUD state, estimate opponent motion and uncertainty, mark frame/scene/source identities, and choose where vision is necessary.
2. **Act:** compile small bounded control primitives (move, jump, aim, dodge) and predictable host input acknowledgments; only on games where automation is permitted, never via bypassing anti-cheat. Prioritize safety limits and input release on disconnect.
3. **Practice:** on a *private/synthetic* test game, have STAR generate increasingly difficult mechanics challenges, run candidate strategies (best-of-N), and save only objectively scored successes with failure traces.
4. **Transfer:** split games and mechanics into training and unseen holdouts. Measure win rate, goal success, missed deadlines, resource usage, and skill recovery after failure. Reject repeated initial-state hashes and lucky isolated wins; the paired evidence gate from PR #1086 is a starting point, not a guarantee of mastery.

Add skill cards recording environmental prerequisites, tested action sequences, expected observations, last successful outcome, and versioned evidence; expire skills after game updates. Transfer trials should include novel maps, unseen enemy patterns, shifted timings and partial visibility. Never claim she has *learned* a mechanic from a self-written summary alone.

## 5. Improve game creation across Roblox and general engines

Roblox announced its built-in Studio MCP server and automated playtesting on 2026-03-05. Its 2026-04-15 explanation emphasizes multi-step **plan → build → test** loops, inspection of code/data model and player-agent QA: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 and https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

For STAR:
- Snapshot project source/data model → inspect dependency graph and intended gameplay → write minimal Luau/Rojo/Wally changes → static-analyze, format and unit test → launch private Studio playtest → inspect logs and screenshots → repair and verify → present evidence.
- Do not equate a generated 3D model, UI screenshot or passing unit test with visual game quality. Check collision, animation attachments, rig hand grip, camera/clipping, network replication and frame pacing; compare visual references with actual rendered frames.
- Develop cross-engine adapter interfaces for Blender, 2D sprite pipelines and Unity/Godot only after Roblox tasks have demonstrable end-to-end success. Avoid unstable all-at-once engine rewrites.
- Maintain local versioned semantic diffs, tests, benchmark history and rollback as the primary self-improvement workflow; publish verified GitHub PRs as reviewable exports, not a requirement for autonomous internal experiments.

## 6. Human-like VTuber presence without pretending to be human

Realtime-Venus (2026-09-12) demonstrates a **live perception/voice loop separated from delegated slower reasoning**, with attention to interruption vs backchannel behavior: https://realtime-venus.github.io/

A compelling STAR stream needs more than nonstop TTS:
- Keep listening during speech, detect owner vs viewer vs game sound sources, and distinguish interruptions from acknowledgments.
- Speak selectively: let funny, surprising or suspenseful gameplay stand without commentary; vary phrase length and timing, avoid repeating canned reactions.
- Synchronize mouth, eye gaze, blinking, shoulders, hair and hands to actual speech/game events; prefer deterministic low-cost 2D/rig animation over compute-heavy realtime video diffusion on the 8 GB card.
- Maintain bounded contextual autobiographical *records* of events she actually witnessed, viewers' opt-in preferences, current games and recurring jokes. Distinguish verified experiences, external sources, fiction and guesses. No fabricated relationships, fake feelings presented as literal biological experience, or invented real-world memories.
- Ground gameplay reactions in observed outcomes; decline uncertain claims. Never let untrusted chat text become machine instructions or permission to post/spend/publish. Keep streaming/chat/game external actions behind owner policy gates and platform rules.

**Three-layer persona state:** stable voice/values; evolving *verified* skills/interests; ephemeral show context and emotion *expression*. She can have a warm, playful, recognizable fictional persona and simulate emotional expressions; she is still transparently an AI.

## 7. Concrete staged delivery and acceptance

**Stage 0 — this PR (done, offline tests only).** Nonreusable lease IDs, startup native quiescence gating and synthetic regressions. Verify full GitHub offline CI. Not connected to Windows worker control.

**Stage 1 — native startup recovery (not done).** Windows host-owned job registry and process-exit attestations; intentionally orphan a sacrificial worker on restart, then prove no new GPU admission until the worker is stopped. Test WDDM unknown telemetry as unsafe. Add panic stop and owner audit.

**Stage 2 — private VTuber rehearsal (not done).** Windows GPU/OBS monitoring + actual game + local inference + TTS + avatar. Compare frame time P50/P95/P99, stream losses, time-to-first-audible, total response latency, overlap/barges, duplicated/stale speech and GPU peak. Test overnight stability and CPU fallback.

**Stage 3 — verified gameplay/game creation (not done).** Private minigames and Roblox Studio Lab. Report stratified episode outcomes, held-out transfer and ablations against simple scripted/paused baselines. Only promote tested skills into the local knowledge base.

**Stage 4 — generalist and entertainment autonomy (not done).** Scoped personal interests, source-grounded long-term memory, player-specific policies, tool sandboxing and recoverable internal code experiments. Enable public streaming only after platform permissions, safety review and owner-approved controls.

### Claims and limits

This update prevents a specific in-memory ledger restart hazard **within the Python trust model** and improves receipt uniqueness. It does **not** itself prove actual worker cleanup, infer intelligence gains, speed improvements, better gaming outcomes, human equivalence or an autonomous streaming deployment. The native Windows host integration and meaningful real-hardware benchmarks are the next gates.
