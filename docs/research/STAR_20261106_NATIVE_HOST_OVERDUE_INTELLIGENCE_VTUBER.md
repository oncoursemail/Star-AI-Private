# Star AI — Native input overdue health and generalist VTuber roadmap

**Research date:** 2026-11-06. **Scope:** isolated, owner-approved Windows game-host rehearsal; no live game or broadcast permission implied.

## Code shipped in this change

`star/native_game_roundtrip_audit.py` previously exposed a nonblocking `in_flight` health snapshot during a stalled host callback. An input worker that never returned would look the same as a healthy short input for the entire stall. The new **host_call_overdue** status uses an independent `time.monotonic_ns()` deadline check and a *separate, briefly held* health lock, so OBS/stream supervisors can see that a native input call crossed its configured budget **without waiting for the call to finish**. The result exposes no game identity, key names, privacy-sensitive telemetry, or successful frame counters.

When the worker finally returns, a genuine over-budget wall-clock call is also rejected, even if a supplied measurement clock falsely reports little elapsed time. This prevents a clock discrepancy from laundering a stalled input into a passing latency report. Cancellation remains nonblocking and `revoked` takes precedence; no timing success survives a failed or overdue call. Regression tests deliberately stall a fake Windows port and never inject real keys.

**Boundary:** this is measurement/health reporting and fail-closed accounting, not forcibly killing Windows threads or releasing physical keys. The existing separate Windows input watchdog remains responsible for a true key-up. An embedding native supervisor must act on `host_call_overdue` by cutting the action source, requesting neutralization via its own watchdog, and treating the entire game episode as contaminated. This health snapshot does *not* prove a game-state change or authorize input or streaming.

## Relevant research and direct implications

1. **Realtime gap is a distinct intelligence problem.** [Gym-Anything-RT, Oct 27 2026](https://arxiv.org/abs/2610.37567) reports substantial gaps between paused and real-time play across 100 generated minigames. The takeaway is not 'use a larger reasoning model for every frame' but to isolate a bounded action controller from tactical reasoning and slower learning. Evaluate both real-time and paused baselines on identical seeds and holdout tasks. Inspect for shortcuts that bypass perception/action rather than demonstrating the intended skill.
2. **A correct but late action can be unsafe.** [RT-SAFE, Oct 7 2026](https://arxiv.org/abs/2610.09294) shows real-time safety hazards can rise despite strong completion. Star should use *joint* metrics: completed objectives, native-input overdue windows, expired actions, verified input release, dropped observations, and unsafe transitions. Never optimize task success alone.
3. **Conversation is a timing policy, not just a TTS output.** [Proact-VL, Mar 3 2026](https://arxiv.org/abs/2603.03447) studies when a gaming companion should speak, including commentary, co-commentary and guidance. Star should keep a short event queue ordered by verified game time, and give gameplay-critical listening priority over narration. Add a `silence` action and explicit speaking budget; verify voice playout and captions against actual audio, not text emitted by a model.
4. **Duplex speech can be assembled from independently measured pieces.** [DuplexCascade, Mar 10 2026](https://arxiv.org/abs/2603.09180) explores chunked micro-turns in a cascaded ASR/LLM/TTS pipeline. Benchmark the cost of interruptions, simultaneous listening and speech, and cancellations across real audio devices before any public stream. Star's avatar should reflect verified playback timing, not just synthesized duration.
5. **Studio capabilities changed on Nov 4–5 2026.** [Roblox Studio MCP/Open Cloud announcement, Nov 4](https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849) introduces permission-controlled Open Cloud requests; [Prompt to Animation beta, Nov 5](https://devforum.roblox.com/t/studio-beta-generate-r15-animations-from-a-prompt-plus-optional-r6-motion-rebuilder/4977709) adds R15 animation generation and optional R6-to-R15 rebuilding. Confirm individual beta tool availability against the actual Studio installation before coding to any assumed endpoint. Keep development/test environments scoped and never grant a generalist model unreviewed production publish privileges.

## Next high-value implementation milestones (not claimed as complete)

### A. Verified game mastery, not replayed scripts

- Give the low-latency controller a bounded action vocabulary and at most one *fresh* observation per decision; separate learned policy inference from tactical planner and from private training jobs.
- Connect `NativeGameRoundtripAudit` to **trusted game-state transition witness** and **signed skill bank**. A native receipt is evidence of an attempted input, never evidence of a completed level. Only a separately observed engine transition counts as a reward.
- Use randomized seeds, counterfactual action attempts, held-out game mechanics and genuinely unfamiliar maps. Track reward gains against equally budgeted baseline policies; run offline tests before transferring skills into a private interactive rehearsal.
- Trigger automatic downgrade to a simple safe action/no-op when inference, host call, or observation deadlines fail. Pre-allocate key-up supervision *outside* the model process.

### B. Inference performance on 8 GB VRAM PCs

- First record a simultaneous baseline for game FPS/frame time, OBS rendering/encoding drops, model TTFT/tokens-per-second, VRAM headroom, CPU saturation, and voice first audible chunk.
- A router must load small reaction models when game+OBS compete for GPU VRAM; reserve long planner calls for private non-time-critical intervals. Reject new GPU work if a conservative free-VRAM reserve is not met; don't infer capacity from GPU % utilization alone.
- Evaluate llama.cpp speculative decoding, prompt reuse *per isolated session*, structured output caching, and CPU-side streaming TTS as **A/B experiments**. Require reproducible improvement in end-to-end action latency or *audible* response latency while keeping quality/coverage unchanged. Don't announce unmeasured speedup.
- Keep tests, docs, inference caches, and larger model downloads storage-aware: the connected Linux root was ~95% utilized during this research pass. No destructive cleanup without a verified inventory/backup.

### C. Consistent, natural AI VTuber persona

- Maintain durable but **verifiable** episode memory: game tried, source evidence, learned mechanic, actual wins/losses, viewers' opt-in preferences. The model must not invent victories or remember messages never received.
- Generate a short expressive reaction only after a trusted fresh event and when the stream turn-taking controller permits it. Vary excitement, restraint, laughter, and silence, with no fabricated sensory claims; keep Star clearly identified as an AI VTuber.
- Synchronize mouth motion to **measured audio playout**; blend head/eye expressions with game attentional focus and respect reduced motion. Ensure avatar and OBS can keep rendering while a reasoning or host-input worker stalls.
- Explicitly test microphone echo, interruptions, staleness, emotional continuity and repeated-joke fatigue. Rate-limit unsolicited chatter; avoid revealing private player/chat data.

### D. Game creation and broad general knowledge

- For Roblox, use the actual permission-scoped Studio MCP to inspect a *copy* of a project, propose Luau+asset edits, run StyLua/selene/luau-analyze where applicable, execute private Studio playtests and verify visual+semantic diffs before submission.
- For other games, separate retrieval of published engine documents from executable code; record source version/date, rerun tool-supported tests, and generalize skills only after holdout success.
- Train Star's agent harness on self-authored tasks from easy to hard: **plan → generate several candidates → sandbox/test → inspect → repair → holdout verify → approved knowledge update**. Measure confidence calibration and abstention, not just answer length.

## Acceptance gates for a real integrated rehearsal

A private Windows host with explicit owner approval must show real frame/host receipts, objective state transitions, native key release, working cancel, voice actually reaching the audio device, avatar animation, and OBS recorded local output **in the same session**. Run paired stress windows and regression comparisons: no missed frame hiding, no overdue native input counted as success, no unverified wins, no increasing OBS drop rate or major FPS regression, and bounded time to silence after emergency stop. Publish only objective measurements plus reproducible offline test artifacts, never passwords, viewer content or raw private chat.

**This PR implements only the native-host overdue detection and deadline-enforcement refinement.** Game mastery, increased underlying model ability, actual streaming/OBS integration, and conversational naturalness remain measurable engineering milestones, not results demonstrated by this patch.
