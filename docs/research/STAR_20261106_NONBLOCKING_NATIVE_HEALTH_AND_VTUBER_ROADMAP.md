# STAR — nonblocking native gaming telemetry, generalist learning, and VTuber research
Date: 2026-11-06
Scope: owner-authorized, offline/private rehearsal only. This document is research and an implementation plan; it does not claim live gameplay, human consciousness, or measured faster neural inference.

## Implementation in this change
- `NativeGameRoundtripAudit.report()` previously waited on the same RLock held by `execute()` for the duration of a native Windows input callback, which can include a blocking worker/watchdog wait.
- Monitoring code (game HUD, VTuber health loop, OBS status collector) calling `report()` could stall until that callback returned. This is particularly hazardous when a worker is hung and the stream needs immediate status.
- `report()` now checks the lock without blocking. A busy lock reports `in_flight` with zero trustworthy counters and no timings. If an abort signal is latched during a busy callback it reports `revoked`; this is **not** a guarantee that keys are physically released.
- `finalize()` now refuses an in-flight callback immediately rather than waiting for it. Existing idle success, abort revocation, and coverage semantics are preserved.
- Offline tests hold a fake native callback while concurrent monitoring and finalization run, then verify responsiveness and successful normal finalization after release. No Windows keys are injected.
- **This is measurement/monitor availability, not an increase in LLM tokens/s or ability to win games.**

## Ranked engineering roadmap — highest expected utility next
1. **True Windows private rehearsal integration:** pin an approved window and process; independently source game frames, game-state outcome receipts, input release, monotonic clocks, inference timeline, avatar/audio playback, and OBS record-only QoS. Enforce fail-closed stop on loss of focus, revoked consent, timeouts, or resource starvation. First pass uses a private local test game, not public multiplayer. Separate worker input receipt from independent *game outcome* receipt. Do not feed arbitrary game-screen pixels to a learning bank as proof of success.
2. **Adaptive inference scheduler:** a tiny policy/controller must handle deadlines and safe no-op fallback; tactical model takes medium-horizon plans; planner/research model runs only outside urgent windows. Route by measured first-token latency, effective tokens/s, context length, VRAM free, CPU cost, and task quality. Evict inactive models only on explicit resource policy. For 8-GB cards, select workload by measured VRAM residency and concurrency, not parameter-size anecdotes.
3. **Reproducible gaming skill acquisition:** create private curriculum with tutorial -> mechanic probes -> controlled practice -> randomly seeded and unseen held-out levels. Score episode completion, collision/safety, action effectiveness, response timeliness, and performance on unfamiliar levels. Preserve replay seeds, code hashes, observation timestamps, and signed game outcome receipts. Never let model-generated fixtures certify their own success.
4. **Natural VTuber dialogue:** separate speech-trigger policy from content generation. Prefer meaningful reactions to verified game events; use silence on tense/ambiguous frames; respect the owner barge-in path, short echo-cleared VAD frames, interruptible speech, gameplay attention, and movement synced to actual emitted audio. Natural character behavior means reliable turn-taking, timing, expressive animation and stable fictional persona; Star should identify herself as AI rather than claim biological human experience.
5. **Computer-use + Roblox creation:** official Studio MCP for inspecting project state, local Luau analysis, build, Studio test, visual inspection, and repair with snapshots. Require permission-scoped operations and separate private test-place writes from production updates. Treat live Roblox data stores and monetization as privileged.
6. **Generalist knowledge:** source-aware project retrieval, code/doc grounding, semantic lesson provenance, case-based memory, uncertainty calibration, and evaluation on new tasks. Avoid replaying web content as policy or training text and do not promote lessons solely from Star's own claims.

## Evaluation matrix, not marketing metrics
- Native host: monitoring p95 and worst-case latency during stalled callback; zero claimed successful frames during in-flight/aborted state; no blocked health/OBS thread.
- AI runtime: TTFT p50/p95, decode tokens/s, GPU memory high-water, CPU utilization, model warm/cold starts, cache hit rate **with session isolation**, and performance while game+OBS+avatar+TTS contend.
- Gameplay: per-seed win rate, error rate, safety violations, prompt-to-action wall-clock p95, independent game-state confirmation ratio, and transfers to never-seen mechanics; compare paused vs realtime conditions.
- Voice and social: time from verified event to first audible PCM; overlap, missed interruptions, interruption recovery, mistaken speech over viewer/owner, hallucinated reactions, speaking-time fraction, and human reviewer ratings.
- OBS: independently record rendering missed frames, encoding skipped frames, and network drops (these are distinct bottlenecks). Never summarize all three as a generic 'fps' metric.
- Roblox coding: held-out executable Studio checks, scene inspection before edits, Luau diagnostics, visual diffs, and clean rollback. Track failures as well as passes.

## Practical model experiments
- Benchmark llama.cpp speculative decoding (small draft vs n-gram variants) on the **actual** locally served models. Acceptance is both improved latency/throughput and unchanged task accuracy. A second draft model can consume scarce 8-GB VRAM and perform worse under contention.
- Benchmark Pocket TTS CPU inference on the same PC as game+OBS, measuring actual first-audio-chunk latency, audio quality, CPU contention, and audible interruptions. Kyutai reports new October 2026 English variants at approximately 18.2M, 6.9M, and 1.9M parameters; upstream throughput claims are not STAR benchmarks.
- Consider richer duplex speech/animation approaches only after local barge-in, echo handling, playout clock, motion, and backpressure gates pass. DyaPlex research describes streaming speech-motion synchrony; it is not a drop-in offline STAR integration.
- Reserve VRAM headroom for OBS and game. Sample hardware during the entire rehearsal, not one instantaneous GPU utilization reading.

## Risks / qualifications
- No-approval mode stays OFF; session scope and game window remain explicit.
- Signed observations authenticate their signer, not the physics or truthfulness of the underlying game host. A claimed key release is not proof of a game-state transition.
- In-flight results deliberately suppress intermediate counters: safety/availability takes priority over attractive but unverifiable partial speed metrics.
- Python thread locks cannot guarantee physical Windows key-up; require a separate process/watchdog and independent OS/game observation.
- Heavy model downloads should wait for verified storage headroom. Earlier host inspections reported roughly 95% root filesystem utilization; measure afresh before changes.
- STAR's internal self-improvement artifacts remain local-first; GitHub is a review/publication layer, not an autonomy prerequisite.
- Real human-level intelligence, conscious experience, general cross-game competence, and unrestricted 24/7 VTuber operation are not established by these tests.

## Verified source material
- Microsoft Research, Proact-VL (ICML 2026; May 2026): gaming companion must decide **when** to speak, not just what to say. https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- NVIDIA DyaPlex (June 2026): full-duplex simultaneous speech/motion for conversational partners. https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/
- Kyutai Pocket TTS (October 2026 small-model update): CPU-focused speech model variants and streaming. https://github.com/kyutai-labs/pocket-tts
- Roblox OpenGameEval (October 2026): executable stateful Studio checks and scene exploration, not code-looking-plausible evaluation. https://github.com/Roblox/open-game-eval
- Roblox Studio MCP expansion, announced November 4, 2026: Open Cloud access, scoped per-game permissions, asset import; live data store access is consequential. https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
- Official Roblox scoped MCP permissions: https://create.roblox.com/docs/studio/mcp-open-cloud
- llama.cpp speculative decoding documentation: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- OBS's three frame-loss sources warrant separate monitoring: https://github.com/obsproject/obs-studio
