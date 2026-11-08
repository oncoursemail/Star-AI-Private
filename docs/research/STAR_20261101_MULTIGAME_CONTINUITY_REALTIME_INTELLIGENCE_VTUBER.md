# STAR / Litha research: multi-game continuity, real-time intelligence and natural VTuber behavior

**Research date:** 2026-11-01 (America/Chicago); **status:** engineering proposal + locally testable multi-game continuity correction.
**Project:** Star-AI-Project, feature stack following the opt-in inference recovery PR.
**Separation of claims:** external benchmark reports are not STAR results. No new gaming model, game victory, stream, training run, speech synthesis, or improved inference throughput is claimed.

## 1. Highest-impact immediate finding: factual memories must work across many games

STAR already has a `StreamContinuityVault`: local SQLite, host-signed practice-trial facts, HMAC row integrity, owner opt-in, broadcast opt-in, limited user-role data packets and an explicit forget operation. It is **not** a general memory of subjective experiences. It must not ingest player identities, chat, audio, images, arbitrary model prose, or validation/holdout evaluations.

**Defect discovered in code review:** the old vault retrieved the 64 newest *all-game* episodes, then rejected anything outside its own game scope as an integrity failure. A second legitimate game could silence recall for the first; enough unrelated newer episodes could hide all older relevant ones. The episode HMAC identifier also omitted game scope, so the same host-generated episode ID could collide when separate games share a database/key. `forget_all()` deleted every game in the database, and status counted other games' events.

**Change in this branch:** isolate read/erase/count operations by the full four-part curated scope (game ID, version, objective, situation), bind new episode identifiers to that scope, use an atomic scoped erasure, and add hostile cross-scope regression tests. Continue to validate all selected HMAC-protected events; the patch intentionally does **not** start new gameplay, introduce hidden data retention, or allow LLM-created facts.

**Verification gates:** (a) same episode ID can occur in two separate curated game scopes, (b) a game's verified recall survives 70 unrelated newer episodes, (c) forgetting one game leaves the other's signed history, (d) corrupted foreign-game rows cannot poison or become facts for an unrelated game, (e) tampering *within* the selected scope still fails closed, (f) no private source data reaches a response. This unlocks legitimate multi-game VTuber callbacks without fabricated biography.

## 2. Make real-time intelligence a deadline-aware system, not a larger synchronous prompt

RealtimeBench (*The World Won't Wait*, Pan et al., posted October 14, 2026) contains 180 continuously running tasks across six game types. The authors report that a fast agent plus a stronger offline teacher improves a student model's average progress score from 13.51 to 24.19 after two improvement rounds. Their setting and numbers are **external research**, not replicated on STAR.

Architecture for an actual STAR rehearsal:
1. **10–100 ms symbolic control path:** cached local observation, game-state freshness/permissions, and deterministic safe action policy; avoid LLM calls for every keystroke. If evidence is stale, abstain or use a no-action policy.
2. **100–700 ms tactical inference path:** lightweight local model proposes an action from recent observations only; host enforces input validity, deadlines, and game permissions; never injects actions from viewer chat.
3. **1–60 second teacher path (paused or offline):** stronger reasoning identifies failures, proposes strategies, and writes *candidate* instructions. Practice and independent validation remain separate. Do not train from unverified game outcomes.
4. **Across-session verified memory path:** keep signed symbolic facts per game/version, schema-checked; do not treat a practice improvement as a validated general skill. Retrieve only a few relevant cards and preserve a stable prompt prefix.

Measure game-specific objectives (wins, losses, survival, build correctness), p95 action response, missed-action deadlines, first-token time, 1%-low FPS, and baseline-vs-candidate *unseen* maps. No claim of generalized intelligence without transfer tests.

Reference: https://arxiv.org/abs/2610.20665

## 3. RTX 3060 Ti 8 GiB: maintain streaming headroom with empirical measurements

Historical Windows snapshots of the owner's RTX 3060 Ti 8 GiB have shown both sub-500 MiB free VRAM and more than 6 GiB free VRAM, so neither reading should be treated as sustained workload capacity. STAR's existing sustained preflight/host-verified GPU telemetry should be consulted **before** a rehearsal.

- Pin the gaming GPU by UUID; reserve renderer/OBS/VTuber memory and headroom first. Move TTS/ASR or nonurgent teacher work to CPU or a second machine when paired latency trials prove an end-to-end benefit.
- Pair requests by identical tasks, game loads, voice utterance categories, and initial VRAM regimes. Compare p95 TTFA, p99 frame times, RSS/VRAM, sound gaps and avatar liveness rather than isolated tokens/sec.
- Keep a stable, short system prefix and retrieval budgets. Instrument actual `cache_n`, `prompt_n`, TTFT and decode tokens/sec. Avoid assuming that larger context windows or model size translate to better real-time actions.
- **Important 2026 caveat:** llama.cpp issue #27148 (opened August 15, 2026) reports possible cross-conversation RAM prompt-cache reuse under concurrent requests; issue #30961 (opened October 22, 2026) reports unified-KV cache restore failures. These are reports to reproduce on the exact pinned build, not universal confirmed behavior. Use single-user isolated model processes, tenant-safe cache boundaries, or disable host RAM prompt caching until reproducible isolation tests pass.
- Speculative decoding is not universally faster; compare SPEED-Bench results and full FPS/voice outcomes before selection. No forced migration to Rust: profile Python first, port measured hotspots only if real wins justify maintenance cost.

References:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/issues/27148
- https://github.com/ggml-org/llama.cpp/issues/30961
- https://github.com/ggml-org/llama.cpp/issues/10664

## 4. Humanlike VTuber: coordinated behavior driven by true experiences

Treat naturalness as synchronized behavior, **not** a promise of human consciousness or invented personal history:
- Keep speech concise and optional during tense gameplay; listen and honor interruptions. Evaluate uninterrupted PCM playback, pauses, delayed starts, barge-in stops, and false-positive interruption rates.
- Use host-confirmed game observations to choose blink/gaze/head/mouth emotion cues. Tie mouth to *consumed* audio sample position, not queued TTS; never animate a victory from unconfirmed game text.
- Let signed past-practice facts support callbacks such as “I struggled with this jump last session,” but do not claim a win when the stored event merely records a successful practice action. Prefer observation-based curiosity over repeated filler catchphrases.
- VTube Studio supports local authenticated WebSocket plugins and custom parameter injection. Its plugin permission grants powerful control, so bind only an authorized local renderer and owner-approved rig parameters. No auto broadcast; OBS WebSocket is a distinct authenticated gate.
- Evaluate actual human-viewer rated naturalness with randomized A/B clips, blinded reviewers where feasible, plus objective timing measures. A synthetic gaze metric is not proof of naturalness.

References:
- https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
- https://github.com/obsproject/obs-websocket
- https://docs.live2d.com/en/cubism-sdk-manual/autoeyeblink/

## 5. Become a better game creator by testing finished worlds

Roblox StudioTestService permits automated server/multiclient Play/Run tests, adding players and simulating join/leave/disconnect scenarios. Pair this with verified physics/material/attachment checks, spatial collision and gap tests, and visual screenshot comparisons; avoid passing a build solely because its Luau compiles.

A high-value local practice cycle:
**inspect a scene** -> specify a small testable change -> generate 4–8 candidates -> build in isolated Studio sessions -> compile/lint -> host-verified runtime tests -> geometry/visual scoring -> keep the best candidate -> preserve full rollback. Validate *unseen* game situations before promoting to skill memory. Use smaller practice tasks by day and heavier rendering/teacher work during idle windows.

Reference: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

## 6. Integration and acceptance checklist

The corrected continuity vault is a **library behavior**, not a completed live Windows integration. Before shipping:
- Run the entire existing continuity and signed-skill test suites, Pyright for touched files, Ruff and compilation; verify new hostile tests fail under the old logic and pass under the new logic.
- Compare a full signed game/practice -> end session -> restart process -> scoped packet -> authorized StarStage speech -> physical-audio acknowledgment -> VTS renderer -> idle nonbroadcast OBS metrics end-to-end on Windows.
- Separately verify no cross-game packet leakage, no cross-game erasure, no synthetic memory identity/biography, proper trust-level attribution and prompt-cache isolation.
- Rehearsal acceptance: no unauthorized broadcast; zero unverified game actions; no stale or overlapping audio; stable avatar frame cadence; measured p95 first audible PCM and 1%-low FPS not worse than the prior baseline.
- New features remain opt-in by default, scoped to the user's authorized hardware and game processes. External social, financial, install, and live-broadcast actions require their independent gates.

**Bottom line:** A trustworthy game-specific memory system is one necessary ingredient in a convincing AI VTuber that recognizes real prior experiences. It will not alone increase the underlying neural model's intelligence or GPU speed; the measurable teacher/student and nonbroadcast integration milestones remain next.
