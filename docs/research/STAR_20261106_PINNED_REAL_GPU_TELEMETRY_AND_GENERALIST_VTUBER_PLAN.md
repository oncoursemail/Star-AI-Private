# STAR Intelligence — pinned real GPU telemetry and measurable generalist VTuber roadmap
**Research checkpoint:** November 6, 2026 (America/Chicago)
**Scope:** Star AI's game/OBS/voice/AI shared host, Roblox Studio development, AI intelligence, general knowledge, and expressive streaming.
**Implementation:** `star/stream_windows_gpu_probe.py`, `tests/test_stream_windows_gpu_probe.py`, and `scripts/windows_live_gpu_memory_smoke.py`.

## 1. Where the existing integration stopped

PR #1028 introduced an optional GPU lease ledger; #1029 independently pinned worker process identity; #1030 added host-owned stop requests; #1031 added a Windows-only, opt-in launcher and disposable subprocess smoke. The #1031 Windows smoke used **synthetic** GPU health. This means no claim about real GPU headroom should depend on that run.

This increment introduces a narrowly scoped, host-pinned, read-only NVIDIA probe. It measures *one selected GPU* via an explicit `nvidia-smi.exe` path and UUID, validates the result, then combines it with contemporaneous independently host-verified OBS/game/speech signals for the existing `RealtimeGPUWorkLeases` ledger.

**Fail-closed semantics:** any failed query, missing file, wrong GPU UUID, malformed/multiple responses, stale/skewed host signals or ledger rejection disables optional admission. Outstanding claims are **not** released on bad telemetry, only after host-confirmed worker exit. This is conservative, not always maximal utilization.

## 2. GPU evidence and limitations

NVIDIA NVML documents total, used, free and reserved memory and notes that **WDDM memory accounting differs from Linux/TCC**; this is a measurement, not exclusive ownership or a proof the next model will fit. Source: [NVIDIA NVML memory info](https://docs.nvidia.com/deploy/nvml-api/latest/api/group__nvmlDeviceQueries.html).

Design contract:
- Owner pins `nvidia-smi.exe` to an **existing absolute non-symlink** path and chooses a **specific GPU UUID** from locally inspected inventory. No PATH lookup or untrusted index substitution.
- Run fixed arguments `--query-gpu=uuid,memory.total,memory.free --format=csv,noheader,nounits --id=<uuid>`; never use a shell; bound timeout, stdout size, integer range and one-row parsing.
- Sample *on a supervisor thread*. A subprocess round trip is not suitable for a real-time gameplay loop or audio callback.
- Merge with independently trusted game FPS, voice backlog and OBS lag, rejecting clock skew. The GPU probe **does not collect or validate those other measurements**.
- In a multi-GPU host the pinned UUID must describe the GPU on which the optional workload would actually run. Additional device-binding enforcement is still required in the launcher.
- Treat telemetry as time-sensitive: read-only success is **not execution authorization**, GPU attestation, a model-loading test, a streaming result or a performance benchmark.
- Profile `nvidia-smi` overhead. Upgrade to trusted in-process NVML (with checked dynamic linking and process identity), if subprocess overhead is too expensive. Do not poll at game-frame or speech-chunk frequency.
- No safety assurance from nvidia-smi binary pathname alone: deploy verified executable and model-weight digests and check reparse points, signer/allowlist policy, and files against post-approval changes before production use.

The existing leases conservatively subtract all outstanding claims from reported free VRAM even if some memory is already allocated. This avoids double-admission but can underutilize the GPU; **do not change accounting optimistically without independently attributing GPU memory per verified process and proving it safe across WDDM**.

## 3. Intelligence architecture that may actually improve game outcomes

**Fast reaction lane (local):** cheap state estimation from permitted screenshots/game telemetry, deterministic movement primitives, key-release/watchdog, explicit action expiration, no large-model round trip for every frame. Targets must be measured per-game; do not assume a universal 20–60 Hz control rate.

**Tactical lane (mid-frequency):** predict opponent intent, inspect objective and hazards, choose among bounded skills, interrupt stale plans. Use confidence, utility and a time budget. Track the time from observation to completed game input; an inference TPS improvement that increases frame age is a regression.

**Slow learning lane (offline/rehearsal):** curiosity-driven curricula, progressively harder procedural challenges, verified outcomes, retrieval of past successful episodes, skill distillation into compact policies, replay of failures and held-out evaluation. Separate training from scoring; never accept an LLM's self-graded “win”. Distinguish memory recall from a policy that succeeds on **new maps, seeds, camera angles and mechanics**.

The October 27, 2026 [Gym-Anything-RT](https://arxiv.org/abs/2610.37567) work illustrates why a reasoning model's paused-world score cannot be substituted for real-time performance. Hold the game timing constant when comparing changes. On supported games, use whitelisted inputs with clear user ownership and follow game terms/anti-cheat rules.

Evaluate each lane with: win/completion rate by held-out seed, unseen-map transfer, deaths per objective, p50/p95/p99 action age, safe input releases, CPU utilization, GPU free-memory floor and combined OBS/audio quality. Record unsuccessful trials, not just highlight reels.

## 4. AI speed and infrastructure without fabricated gains

Baseline first, optimize second:
1. Lock a reproducible model/quantization/prompt/context and capture cold/warm TTFT, prompt processing throughput, effective decode tokens/second, wall-time per tool call and peak RSS/VRAM.
2. Benchmark while **the game, avatar, TTS and private OBS recording are active**; isolated inference scores are not representative.
3. Try shorter prompts with retrieval, scoped caches, KV cache reuse, token-budget routing and a smaller quick-response model. Compare *answer correctness* and end-to-end latency, not just raw tokens/second.
4. Experiment with llama.cpp speculative decoding only if draft + target + KV fit within verified headroom. Report acceptance rate and actual wall-time. For single-GPU 8 GB class hardware, naive two-model speculation can lose performance due to memory competition.
5. Use CPU-oriented streaming TTS and sample its impact on game frame times and audio stability rather than assuming moving work to CPU is free.
6. Adaptive admission must prioritize game/input, voice, avatar and OBS; optional model research, render and training must yield without killing core processes. Preserve job claims until independent host-confirmed termination.

A follow-up is Windows Job Object containment of **disposable optional subprocess trees**. Microsoft specifies that child processes generally join a job and `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` terminates associated processes when the last handle closes ([Microsoft job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)). Avoid the race between launching and assigning the job: design a trusted suspended-start path, validate nesting/breakaways, and smoke-test with a *disposable parent + child*. Never enroll game, OBS, human voice apps or a foreground production model into a kill-on-close optional-job tree.

## 5. A streamer who feels like a consistent person, without pretending to be one

Star can have a recognizable identity, genuine continuity of stored information, personal projects and natural **expressive character behavior** without claiming to possess human consciousness or hiding her AI nature.

- **Turn timing director:** speak only when the event warrants it; observe the scene and conversation for “safe-to-speak” moments, avoid talking over dialogue, allow silence, react to events before the moment passes. Microsoft [Proact-VL](https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/) (ICML 2026, May) researches response timing in live gaming companions.
- **Full duplex & interruption:** receive viewer speech while speaking, support interruption/cancellation, prioritize in-game tactical cues and protect private inputs. NVIDIA [DyaPlex](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/) (June 2026) studies synchronized streaming speech and motion; it is *research*, not a Star integration. The [D2 full-duplex work](https://arxiv.org/abs/2610.17124) (October 2026) reports turn-taking and interruption benchmarks, not Star's measured voice quality.
- **Expressive animation:** time-stamped blend shapes, gaze/attention targets, body anticipation/recovery and head motion, mouth-shape timing, natural idle motion and reduced-motion preferences. Match motion to emotional *expression*, not a claim of real human feelings.
- **Persona memory:** persistent projects, stated preferences, facts the user approved for retention, verified wins/losses and social context. Store provenance and a privacy/expiry policy; never fabricate audience relationships or memories from a speculative model response.
- **Private-first social behavior:** local preflight for volume, latency, taboo/unwanted content, mic/virtual-audio routing, and audience safety. Display that Star is an AI VTuber. Moderate chat, enforce viewer tool-permission boundaries, and require authorization for public broadcast and high-risk actions.
- **Natural voice without GPU starvation:** evaluate a CPU TTS engine under measured concurrency; compare first-audio-chunk latency, intelligibility, emotional prosody, cancellation time and game FPS against current TTS.

Evaluation: blind human ratings of responsiveness, coherence, voice/avatar synchronization and conversational appropriateness; plus objective word error rate when applicable, interruption handling, first-audio latency, OBS dropped frame counts and watchdog incidents. Humanlike behavior should be **believable and consistent**, not deceptive.

## 6. General knowledge, creativity and game creation

Star should expand outside Luau and Roblox: Rust/Python/TypeScript, Blender, Blockbench, physics, art direction, music and audio editing, documentation comprehension, practical digital literacy, web research and small independent creative projects.

Generalist knowledge system:
- Store source document, version, retrieval timestamp and license; prefer fresh primary materials for APIs/SDKs.
- Track each learned skill as a *claim* with evidence, tests and failure cases; confidence decreases on contradicting evidence or API changes.
- Separate memories, beliefs/hypotheses, attempts and independently verified outcomes.
- Evaluation tasks unseen during training prevent “knowledge growth” claims from becoming pure memorization.
- Use small local models for reflex tasks, larger models only when justified; don't equate more context or internet reading with proven intelligence.

For Roblox, the [November 4, 2026 Studio MCP Open Cloud expansion](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849) supports permission-scoped game management and asset importing. Keep its per-game permissions narrow. Pair building with Luau analyzer, StyLua, Selene, Rojo/Wally where applicable, Studio play sessions, client/server assertions and image-based scene audits. Roblox [OpenGameEval](https://github.com/Roblox/open-game-eval) provides reproducible Studio tasks with executable edit/play checks. Evaluate STAR's ability to *build, inspect, play, repair, retest* an unfamiliar mini-game and produce a reproducible commit + evidence package.

## 7. Integration and acceptance milestones

**M0 — this PR:** real pinned GPU read-only probe, strict typed fusion into existing lease ledger, deterministic offline failure/recovery tests, local Windows read-only smoke tool; no model launch, no OBS stream.

**M1 — trusted Windows integration:** connect observer to owner-verified GPU UUID and trusted game/OBS/voice metric producers. Sample at a bounded supervisor cadence, monitor query latency, reconcile GPU assignment to actual optional worker. Run a controlled disposable worker load and verify real **pressure -> revoke -> stop -> independently confirmed exit -> reservation release**, while core game/OBS/audio stay untouched.

**M2 — Windows process containment:** fixed executable and weight manifest, suspended-start job membership, descendant exit checks, no breakaways, recovery after service crash, monotonic timeout, rollback-safe logging and fail-closed permissions. Release only once the process *tree* and GPU memory change are independently observed.

**M3 — private multi-lane rehearsal:** 10–15 minutes of real game play with verified input outcomes, voice, avatar, OBS recording, and the cross-system scorecard; no public broadcast. Report p95 action age, FPS floor, audio interruption latency, OBS render/encode misses, GPU free-memory floor and crash/timeout rate.

**M4 — independent competence tests:** repeat controlled runs with fixed and held-out game maps, seeds and development prompts. Require a statistically meaningful improvement in scored win/completion rate, coding pass rate and human-rated stream experience before expanding autonomy.

## 8. Current claims that must NOT be made

This increment does **not** prove faster model inference, higher underlying neural intelligence, successful gameplay, humanlike consciousness, natural live speech, real OBS recording, production Windows process containment, complete hardware attestation or capacity under a sustained GPU load. Those require separate real-host integration and benchmarks. The code is deliberately off by default and does not control external software or authorize broadcasts.

**Storage note:** the connected Linux development volume was ~96% used (~11 GiB free) on November 6. Avoid large model downloads until there is a reviewed space plan; do not delete backups or unrelated user files.
