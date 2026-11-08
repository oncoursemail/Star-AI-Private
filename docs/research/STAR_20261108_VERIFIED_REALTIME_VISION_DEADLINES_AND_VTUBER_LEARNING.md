# Star AI — verified real-time vision freshness, VTuber intelligence and game learning

**Research date:** 2026-11-08

**Change scope:** Offline, opt-in live-vision scheduling guard. No new model weights, microphone access, game controls, OBS actions, or autonomous broadcasting.

## 1. Evidence: realtime skills have different constraints from offline reasoning

Aggarwal and Welleck's *Gym-Anything-RT* (submitted 2026-10-27) evaluates 100 automatically generated minigames in realtime and paused regimes. A large difference between these modes is an actionable systems result: even a strong model may produce a logically correct action too late to be useful. See https://arxiv.org/abs/2610.37567 . This is evidence for separating the **react** path from **think** and **learn** paths, not evidence that this repository already masters games.

A 2026 ICML paper, *Proact-VL*, focuses on low-latency continuous video understanding and learning **when to speak** in gameplay commentary/guidance. An expressive streaming agent needs a deliberate choice to say nothing, rather than narrate every frame. See https://arxiv.org/abs/2603.03447 .

Practical consequence: Star must not say "you just won" based on an obsolete, unverified HUD observation. Visual hypotheses are neither verified outcomes nor permissions to speak.

## 2. Implemented in this change: opt-in frame-to-result freshness

`WindowsGameCaptureHost(max_result_age_ms=None)` keeps the prior behavior by default. A trusted host may configure a finite value from **100 to 1500 ms**, measured with its monotonic clock from the end of an identity-verified physical capture to the final, physically stopped worker result.

Two additional enforcement points:

1. **Before the synchronous model worker:** If fingerprinting, admitted-frame scheduling or optional downscaling already consumes the budget, do not start inference. A worker that never started is safely settled as failed; the governor's reservation is released.
2. **After the worker physically stops:** If the deadline has elapsed, discard the visual packet and settle the lease unsuccessfully. Do not publish stale findings as game events, memory, commentary, or proof of winning.

On a **reversed or unavailable host clock**, keep the lease quarantined for trusted reconciliation rather than creating artificial successful timestamps. Existing window identity, approval, native-resolution fingerprints, pixel-memory scrubbing, physical stop acknowledgments, and worker nontermination quarantine remain authoritative. All counters are aggregate; no captured content is persisted.

This does not accelerate the model itself. It avoids **wasted model invocations** on already-stale frames and suppresses **outdated reactions**. Whether it improves player outcomes depends on measured gameplay experiments.

**Why opt-in:** Some tasks (map reading, puzzle inspection, asset analysis) legitimately need multi-second inference and should not inherit a reaction-deadline setting.

## 3. Recommended next architecture: multi-clock real-time intelligence

**Reflex lane (frame deadline):** Host-only capture, small visual state, game audio cues when authorized, movement prediction, and a narrowly scoped action policy for permitted game testing. Move work off render threads. Never allow chat, on-screen text, or game assets to authorize host actions. Drop obsolete state instead of accumulating unbounded queues.

**Tactical lane (inter-action planning):** Plan goals, route selection, resource use, and bounded tool calls when there is sufficient headroom. Preserve confidence estimates and trace tool results. Do not let a larger reasoning model block time-critical controls.

**Learning lane (offline or low-priority):** Save provenance-tagged attempt records: game identifier/build, task, observed state, actual actions, measured result, hardware timing, and confidence. Store player PII/chat separately under explicit retention policy. Compare baselines against new strategies on withheld seeds/maps and retain improvements only when externally verifiable.

**Streamer lane (natural social behavior):** Require verified sensory events, a pending conversation plan, VAD/voice interruption cues, and a pre-play audio gate. Use deliberate silence, expressive reactions, prosodic speech, avatar eye/blink/head/body motion, and stable persona memory. Completed speech must be confirmed by the audio host before writing "Star said X" into conversational memory. Be transparent that Star is an AI VTuber, not a person with claimed human experiences or unverified feelings.

**Creator lane (Roblox):** Turn a game brief into reviewed tasks; inspect the existing DataModel; make minimal changes; run Luau analysis, tests and private Studio playtests; compare failures to acceptance criteria; commit only verified improvements and keep rollback. Roblox announced a built-in Studio MCP server in March 2026 and a planning/build/testing agent workflow in April 2026. Its November 4, 2026 MCP update expanded permission-controlled Open Cloud and asset workflows. Use separate limited game/project permissions and do not publish, monetize, or spend without owner-approved scope.
Sources:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
- https://create.roblox.com/docs/studio/mcp

## 4. Model inference on 8 GB VRAM: benchmark or reject

Do not infer speedups from pixel-byte reductions or parameter counts. Use baseline **plus** opt-in candidate profiles at identical workloads. Measure end-to-end time from confirmed screen capture to action, and latency from verified event to speech onset; also record quality and safety regressions.

Candidate optimizations:

- Adaptive visual input sizes with independent native-resolution HUD/event checks (already optional).
- Frame freshness guard (this change) using 250 / 500 / 750 ms candidate budgets, **not** a single global setting.
- Cache-stable prompts and small local reaction models, gated on validated game state.
- Speculative decoding only when its actual client latency beats baseline without harming OBS/game FPS. llama.cpp SPEED-Bench records throughput, overall latency and draft-token acceptance, and provides baseline comparison. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md .
- CPU-oriented TTS only if full speech quality, first-audio latency and interruptions are at least as good as the current renderer.

Do not automatically download models or perform large OBS recordings on a nearly full system drive. The Windows machine was reported at ~1.60 GiB free on C: in the preceding run; reconfirm space before device experiments. Protect the game and broadcasting pipeline with a headroom-aware admission governor and fail closed on missing telemetry.

## 5. Verification plan — objective thresholds, not inflated performance claims

**Offline unit tests:** Invalid deadline types/ranges; feature default off; exactly-on-deadline accepted; stale finished workers discarded and release lease; stale fingerprint/resize work skipped before inference; reversed clock holds quarantine until trusted recovery; nonterminated worker never releases capacity; old tests continue to pass.

**Private Windows experiment (owner-controlled):** On the **same** game scenarios and OBS settings, compare feature off vs 250/500/750ms. Include real motion, HUD-small-text recognition, slow and fast model responses, revoke/close-window races, a frozen worker, GPU starvation, and return-from-sleep clock anomalies. Capture only approved game windows and redact incidental personal data.

**Measurements:** p50/p95/p99 capture-to-worker-start and capture-to-packet latency; worker runs skipped before dispatch; stale packets suppressed; incorrect/lost critical HUD cues; end-to-end action effectiveness; game FPS and 1%-low FPS; OBS dropped/render-lag frames; CPU/GPU/RAM/VRAM; p95 voice interruption latency; verified spoken-memory error rate. Reject rollout if recognition quality or game/OBS health regresses, even if model-input bytes drop.

**Broader skill evaluation:** Unseen game builds, maps, control settings and seeds. Compare success rate, death rate, actions/sec, score/time, and repeatability. Validate that lessons generalize rather than overfit a fixed minigame. Keep training and evaluation data separated.

## 6. Next work by impact

1. Wire opt-in freshness to a Windows host-controlled private dry-run **after** storage headroom and actual worker stop evidence are verified.
2. Build a small permission-scoped game reaction benchmark with frame→action timings, before adding a giant general model.
3. Use low-latency speech and a verified spoken-memory ledger to drive contextual commentary; benchmark authentic timing and interruptions, not "human" claims.
4. Add real Studio inspect→test→repair loops with independent game QA gates and rollback.
5. Instrument per-device performance so Star can choose smaller/faster local models, move TTS off GPU when useful, and maintain streaming stability.

**Claim boundary:** This change provides a deterministic freshness gate and tests. No measured GPU/model speedup, no measured gameplay skill improvement, no independent game control, and no live VTuber integration are established by these tests.
