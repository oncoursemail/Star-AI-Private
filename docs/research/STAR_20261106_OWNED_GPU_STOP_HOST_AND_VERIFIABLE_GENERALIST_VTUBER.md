# STAR AI: Host-Owned GPU Worker Enforcement and Measured Intelligence Roadmap
**Research date:** November 6, 2026 (America/Chicago)
**Code status:** opt-in Windows host subprocess stop service; offline synthetic tests. No live GPU worker, game, broadcast, or trained model introduced.

## Verified local problem and implementation

- Windows host read-only NVIDIA snapshot (Nov 6): **RTX 3060 Ti, 8,192 MiB total, 282 MiB free, 0% sampled GPU utilization**. This is a single sample, not a historical average or proof of which process owns the memory. One `llama-server` process was observed. OBS and VTube Studio were not observed under their expected process names in the same snapshot.
- Linux development host: **218 GiB root filesystem, 197 GiB used, 11 GiB available (~96% used)**. Do not download multiple models or create large checkpoints on this host.
- Existing code (PRs #1028–1029): opt-in `RealtimeGPUWorkLeases` reserves optional GPU jobs, `HostGPUWorkerLeaseBridge` monitors OS process identity, but prior code only *recommended* stops; it did not service them.
- This branch adds `HostOwnedOptionalGPUWorkers`, an **actual host-only termination-request adapter for an original Windows `subprocess.Popen` handle**. It requires an owner-approved, already launched local optional worker and the original in-process GPU ticket. It does **not** accept arbitrary PID, process command, or model-generated terminate instructions.
- A stop intent is serviced at most once through the retained process handle, not a fresh PID lookup. Missing OS identity, a thrown observation, or a failed stop does not reclaim GPU memory. Reservation release waits for observed process exit. An unbound newly spawned worker is quarantined rather than forgotten.
- New bridge `is_pinned()` uses object identity to check that the particular ticket was released. Exit from the independent pinned OS witness is required for originally bound workers.
- Default OFF; no auto-starting a model, publishing a stream, game injection, public chat, or real-device stop action in the automated test. Windows service ticks belong on the **host supervisory lane**, never a game-render/audio deadline thread.
- This service does **not** yet connect to Star's actual Windows model-spawning registry. That integration must inject ONLY Popen objects the trusted local host created, plus owner-configured launch commands. The host cannot retroactively claim arbitrary running processes.

## Evidence, performance and safe upgrade gates

A new GPU scheduler should improve **responsiveness under contention**, not be labeled an inference speedup without a benchmark. In future experiments capture:

1. Full observation-to-action latency (p50/p95/p99), discarded stale frames, all-frame coverage and verified outcomes.
2. Model time-to-first-token, decode tokens/sec, prompt throughput, peak RAM/VRAM, warm/cold cache, response quality on held-out tasks, and actual overall game frame rate.
3. First audible PCM chunk, interruption-to-stop latency, audio/video sync, mouth-animation timestamps, speech backlog and OBS render/encode loss.
4. CPU and GPU occupancy, host process PID + creation time **in private instrumentation only**; public summaries must not leak identity, file paths, prompts, or viewer data.
5. Failure-case tests: crash during model boot, child escapes before OS witness, PID recycling, process query exception, exit-before-bind, stop request not acknowledged, VM clock rollback, stale VRAM probe, stream switch, and temporary no-action decisions.
6. GPU budget admission on the current Windows snapshot MUST deny additional discretionary model launches; 282 MiB free is below a prudent minimum headroom.

Acceptance for Windows child-worker integration: one trusted local, intentionally spawned, disposable dummy worker; confirm a lease; revoke on simulated FPS/VRAM pressure; observe at most one stop request; verify exit on the **original process handle**; release exactly one ticket. Must also show no stop of game, OBS, browser, avatar, existing llama-server, or unknown user process. Testing should remain private and avoid real models until headroom is measured.

## New research and measurable directions

### Intelligent real-time gaming

[Gym-Anything-RT (Oct 27, 2026)](https://arxiv.org/abs/2610.37567) compares identical game tasks in continuously evolving vs paused conditions. Its 100 minigames expose a large gap when AI must act under real-time deadlines. Build a three-lane design:

- **Fast reflex lane:** frame-to-input deadlines, cached typed micro-policies (evade, stop, aim, jump) operating with limited latency; no expensive generalist reasoning in the hot path.
- **Tactical lane:** sparse visual/world-state analysis, opponent modeling, horizon-based plans, replan when state changes.
- **Learning lane:** after a completed session, replay signed observations, invent targeted drills, compare against a frozen baseline on untrained maps, checkpoint only statistically supported improvements. Strictly separate training seeds from holdout seeds and report confidence/variance, not just cherry-picked wins.

[GameWorld (April 8, 2026)](https://arxiv.org/abs/2604.07429) evaluates 34 games and 170 tasks with state-verifiable metrics. STAR's competence metric must be actual task success across fresh games and horizons; a successful OS input call alone is not game skill.

### Neural efficiency and routing

[llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) can improve decode throughput when extra draft compute is cheap and accepted tokens are high. **Do not assume** speedups on an 8 GiB card with 282 MiB headroom: draft models and KV cache can consume scarce memory. Run baseline vs n-gram speculation vs draft models only after GPU memory pressure is relieved. Use identical prompts, output-token counts, temperatures, prompt-cache state and game/OBS load. Keep a small fast conversational/reflex model and route deep planning to slower workers when the GPU can support them; optimize quality-per-deadline rather than raw t/s alone.

[Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) lists 18M/7M/2M English CPU models (Oct 2026), potentially removing some speech from GPU contention. Evaluate naturalness, pronunciation, latency, voice consistency, licensing and interruptibility on STAR's actual CPUs. Do not download them to the nearly full Linux system as part of this PR.

### Humanlike but transparent VTuber presence

[DyaPlex (June 2026)](https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/) explores concurrent speaking, listening and motion. STAR's near-term roadmap should instead **instrument a simple deterministic pipeline first**: VAD + streaming ASR + short utterance scheduler + interruptible TTS + timestamped lip/eye/gesture cues + OBS private recording. Use hysteresis for viewer-chat interruptions and silence, prevent repeated reactions to the same event, preserve conversational topic continuity and remember only *verified* experiences. A recognizably playful fictional persona should not claim literal human consciousness or disguise the streamer's AI nature.

A useful 10-minute privately recorded acceptance script: 4 minutes normal game exploration, 2 minutes intense gameplay, 2 minutes moderated viewer-like scripted conversation, 1 minute deliberate silence and interrupted TTS, 1 minute safe shutdown. Label every cue, record audio video sync and dropped frames, and independently score responsiveness and social appropriateness. Do not auto-broadcast.

### Autonomous Roblox creator and generalist knowledge

[Roblox Studio MCP Open Cloud permissions (Nov 4, 2026)](https://create.roblox.com/docs/studio/mcp-open-cloud) now support per-game, scoped operations. Unlike previous third-party MCP servers, prefer Studio's built-in server; keep changes on throwaway test places. Read-only scopes by default. DataStore and MemoryStore access can affect live data and needs separate safeguards. Never turn on write/publish/monetization scopes just because Star can call them.

For coding, Blender, animation, textures, UI, audio and Rust knowledge, use project-scoped retrieval with provenance, visual comparison and executable tests. STAR's self-directed training should generate difficult tasks, use 4–8 diverse candidates only when resources allow, check with Rojo/Luau analyzers/Studio tests, and admit skills only after performance on held-out tasks improves. Reuse Star's existing tests and skill corpus; avoid another parallel unverified memory store.

## Proposed rollout

**P0 — Operating safety and actual responsiveness:** adopt this host-owned adapter behind an explicit host feature toggle, write a disposable Windows subprocess smoke test, test reliable stop confirmation under VRAM pressure, then repeat with an optional controlled AI worker when enough VRAM is free.

**P1 — Measured intelligence:** build a 20–50 episode small game learning cohort with frozen baseline and held-out scenes, track verified game success and p95 loop latency, select policies by both accuracy and deadline success. Repeat with a different game to test transfer.

**P2 — Speech-avatar OBS rehearsal:** calibrate TTS and avatar sync in offline private recording, human rating of timing and expression, safe chat moderation, durable persona memory grounded in verified events, interruption and silence handling.

**P3 — Robust generalist game making:** Studio MCP read-only inspection followed by authorized test-place creation, Luau lint/static checks, verified playtests, video inspection, rollback and evaluation. Promote stable code only after independent CI and project-level review.

**Boundaries:** The new adapter does not increase weights/model intelligence, deliver an autonomous streamer, generate new assets, terminate existing user processes, or demonstrate measured inference acceleration. It closes a missing segment between host GPU stop recommendations and actual Windows-host-issued stop requests *for owner-started optional workers only*. All public streams and irreversible actions remain separately gated.
