# STAR: closed-loop gaming, useful intelligence per second, natural VTuber behavior
**Research checkpoint:** October 27, 2026 | **Implementation status:** opt-in, synthetic-test-only; no Windows renderer, game-control, capture or live broadcasting integration in this change.

## Why this upgrade is more important than another tiny fingerprint optimization

Star already has game action suggestions, owner-gated input reservations, frame fingerprints, visual novelty admission, signed practice evidence, game prediction calibration, a curriculum ladder, reaction scheduling, a speech governor and animation planning. The critical missing layer is a **bounded observation-action-observation diagnostic**.

A model may press "jump" and then see a different screen. That does **not** prove the jump worked, that its action caused the change, or that it won. Conversely, unchanged pixels do **not** prove the button failed: the camera may not move, the effect may be delayed or invisible, or the chosen ROI may miss it. Mistaking cheap heuristics for trustworthy game outcomes corrupts learning.

This PR adds an in-memory, host-mediated visual-effect probe that can track a *candidate visual effect* after a separately authorized and physically released action. It requires multiple fresh, scope-consistent post-action frames and returns only noncausal diagnostic labels. A signed, independently checked GameTrial remains the source of truth for learning and public claims.

## What is implemented in this PR

**Module:** star/game_visual_effects.py
**Tests:** tests/test_game_visual_effects.py

- Explicit owner and game-session opt-ins; a bounded allowlist of symbolic actions.
- The host supplies a GameScope, a trusted GameFrame, and the matching FrameCue. These are existing project interfaces, not a new permission system.
- Arm only **after** the host confirms the already-executed action's keys/buttons are released. A model suggestion, queued command or permit is not enough.
- At most one action effect investigation is outstanding. The ticket is identity-bound and invalid after stop/restart or resolution.
- Compare game-world hash, HUD hash, game/HUD tone signatures and configured focused HUD regions. Changes to the crop definitions or sensor scope invalidate the comparison.
- Require two or more consecutive post-action frames showing the same changed/unchanged class, with a minimum time gap. Ignore duplicate, reordered, prematurely captured and stale frames.
- Cap action-to-observation time; fail to inconclusive on scene switching, lost focus, stale timestamps, missing capture attestations, changed crop scope or deadline expiry.
- No saving screenshots, model prompts, voices, viewer chat, names, images, game keys or private footage. Status returns anonymous counts.
- Result statuses: visual_change_detected, no_visible_change, awaiting_confirmation, inconclusive or rejected. Every result explicitly has independently_verified_success=False and authorized_to_play=False.

**Security/epistemic boundary:** The module trusts a **separate** local host to provide true capture timestamps, physical release acknowledgements, focus, action allowlists and game scope. It cannot verify these claims by itself. Do not expose this module's methods to an LLM, game chat or a remote viewer as invocable commands.

### Integration contract for a real Windows host

1. Owner authorizes this game's controlled environment and curated action IDs; Star's input adapter retains independent focus/permission/anti-cheat/game-rule checks.
2. Capture the pre-action FrameCue/GameFrame from the approved game capture, before input dispatch. Retain only short-lived fingerprints for this diagnostic.
3. Use existing GameActionGate request + claim_offered; dispatch an allowlisted bounded action via the separate host. Enforce a physical key-up watchdog, then call GameActionGate.release only after actual key release.
4. **Only after successful host key release**, arm GameVisualEffectProbe using the same pre-action GameFrame/FrameCue and the trusted release timestamp.
5. Observe two or more post-action frames from the same authorized game/session/crop scope. Maintain capture sequence numbers and monotonic timestamps.
6. If visual_change_detected, ask the **independent game-state checker** (e.g. Studio playtest objective assertion) whether the intended action actually advanced the goal. If no_visible_change or inconclusive, consider targeted inspection rather than endless retries.
7. If the separately signed PRACTICE GameTrial verifies an outcome, only then feed the result into GamePredictionLab, GameplaySkillBank and GameLearningLadder. Hidden holdouts and validation must never become practice hints.
8. When streaming, VerifiedGameReactionHost may speak only about separately signed/publishable practice results. A FrameCue containing the string win is *not* permission to celebrate a victory.
9. Complete measured A/B acceptance on Windows before enabling by default; owner-facing feature defaults OFF.

Do not enable this in competitive games where automation is prohibited. The Windows/Roblox Studio host is still missing; this PR is **not** evidence of autonomous gameplay mastery.

## Independent research, dated and linked

### A. Verified game development, not merely code generation

Roblox's **October 1, 2026 OpenGameEval** paper reports 84 curated core tasks, 13 frontier models and 16 attempts per task. It separates exploration from edits and uses executable engine checks; inspecting relevant objects before editing is associated with a substantial difference in pass rate. Source: https://arxiv.org/abs/2610.02563 and code: https://github.com/Roblox/open-game-eval . Roblox officially announced its built-in Studio MCP server with playtest automation on **March 5, 2026**: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 .

**Engineering consequence:** Build a single trusted "inspect -> propose -> build -> playtest -> diagnose -> repair -> replay" adapter for Studio rather than concatenating tools and trusting their generated descriptions. Each requirement should map to an executable assertion plus a rendered artifact review (scene geometry, player spawn, animation, UI, interactions and persistence).

The **October 19, 2026 CEGame-Bench** paper shows a gap between project integration and real play completion: under tested conditions, games reached their endings in only 16% of runs. Its requirements-driven playtest-and-repair skill improved execution-based scores by 14.1-24.3 points in its reported experiments; these are *paper results*, not STAR improvements. Source: https://arxiv.org/abs/2610.26098 .

**Game-creation priority:** completion traces + save/load tests + multiplayer tests + independent playthroughs are more valuable than another code-only generation chain. Keep a rubric for visual quality: relative prop scale, intersections, alignment, sight lines, terrain support, texture fidelity, contrast/readability and gameplay affordances. Meshes and rigged props require actual Studio viewport/physics inspection.

### B. Play unfamiliar games by learning *mechanics*, not button sequences

The **April 8, 2026 GameWorld** paper evaluates game agents on 34 browser games and 170 verifiable tasks, using serialized game state for outcomes instead of trusting visual heuristics. Source: https://arxiv.org/abs/2604.07429 and https://gameworld-bench.github.io/ .

**Engineering consequence:** Separate three layers:
- Perception: timestamps, screen/video fingerprints, localized HUD changes, multimodal scene interpretation with uncertainty; never equate a changed image with a game reward.
- Control: bounded semantic action options with rules, focus checks, per-action timeouts and key-release confirmation. Avoid directly prompting arbitrary keyboard/mouse input.
- Learning: game mechanics hypotheses, prospective success estimates before action, controlled experiments, independently signed success/failure, calibration, skill transfer to unseen game layouts. Maintain no-leak holdout scenes.

Add an action-effect diagnostic (this PR), then a trusted Windows game-state assertion bridge and intervention scheduler. Compare performance on *unseen* games/objectives and measure success per minute, not only familiar-task repetition.

### C. Increase useful intelligence per second, protect the game

On an 8 GB RTX 4060 target, total GPU memory and contention with the game/OBS/avatar matter more than one advertised model benchmark. Star should have three latency tiers:
1. Reflex tier (<frame-to-frame attention latency as budget allows): cheap game/HUD signals, fixed safe actions and silence; no large-model call for every frame.
2. Interactive tier (speech and strategy): small draft/retrieval models and governed strong-model escalation; response may be prepared early but spoken only after turn confirmation.
3. Offline tier (learning and creation): best-of-N with independent checks, harder curricula, retrieval consolidation and code experiments. Pause under live-game GPU pressure.

Benchmark effective latency **end-to-end**: capture -> meaningful observation -> proposal -> physical input -> confirmed effect -> verified game outcome; separately STT end -> first audio actually heard, viewer interruption recovery, p95 FPS and VRAM. Always compare the same randomized task mix and real hardware baseline. Speculative decoding, prompt caching, KV-cache placement and CPU offload are candidates, not guaranteed speedups. The August 28, 2026 llama.cpp issue about n-gram draft-cache slot reuse is *unconfirmed* and illustrates why cache-integrity tests matter; do not treat it as proof STAR has the bug: https://github.com/ggml-org/llama.cpp/issues/27852 .

### D. Humanlike gaming VTuber as a *consistent AI character*

LiveKit's turn-taking docs discuss adaptive interruption, backchannels, dynamic endpointing and preemptive generation. Preemptive TTS can waste work when speech changes; avoid speaking from unconfirmed transcripts. Sources: https://docs.livekit.io/agents/logic/turns/tuning/ and https://docs.livekit.io/reference/agents/turn-handling-options/ .

Kyutai's **October 20, 2026 Pocket TTS v4.0.0** added 18M, 7M and experimental 2M-parameter English variants; **October 21 v4.0.1** addressed short-model pronunciation issues. They are interesting CPU candidates to compare against the existing voice, not automatically a better natural voice. Source: https://github.com/kyutai-labs/pocket-tts/releases .

The avatar should coordinate quiet eye tracking, gaze target, purposeful blinking, expression intensity, speech-driven mouth motion, breathing, and springy twin-tail hair. Live2D Cubism supports real-time physics for hair motion. Physics settings and the rig need model-specific visual regression tests: https://docs.live2d.com/4.2/en/cubism-editor-manual/physics-operation/ .

Natural streaming **behavior** is more important than constant animation:
- Intentional silence during demanding gameplay; short reactions to real verified events.
- Playful/adorable modes with consistent preferences, conversational timing, topic transitions, and occasional jokes *when context warrants*.
- True cross-session memory of actual AI activities and projects, but no pretending Star lived human experiences or is a literal human.
- Fresh chat context only after moderation and private-data redaction. Handle real interruptions; ignore incidental backchannels. Host confirms actual audio playback before avatar says it "spoke."
- Measure human evaluation of warmth, relevance, natural pacing, interruption handling and motion synchronization against objective latency and FPS budgets.

### E. General knowledge, self-improvement and Star Core Forge

Use an evidence-backed local knowledge graph: every durable fact or learned mechanic has source, retrieval date, confidence and an invalidation/update path. Separate factual knowledge from persona fiction and from private/permissioned information. Convert research into reproducible challenges and citations, not memory accumulation without recall tests.

Star's internal development environment (Core Forge) should become the canonical experiment ledger with semantic diffs, independent baselines, test artifacts, rollback, isolated workers, and checkpoints. GitHub is an optional publishing/review boundary, not a dependency for local autonomous improvement. Self-generated difficulty increases only when a hidden-evaluator success threshold has held on unseen tests; stop/pause experiments when regression, compute pressure or integrity violations appear.

## Measurement checklist for next implementation

- **Correctness:** action-effect flags must not be counted as wins; signed game success + independent environment state check is required.
- **Performance:** no FPS regression at p95/p99; no unbounded vision/LLM/TTS calls; record actual GPU/CPU headroom under game plus avatar.
- **Robustness:** reordered frames, mismatched crops, frame age, 2-frame confirmation, session revocation, clock rollback, stopped worker and released-key acknowledgements.
- **Learning:** practice improvements must transfer to unseen layouts/games; report calibration and holdout contamination independently.
- **Naturalness:** audio-first synchronized mouth animation; purposeful silence, continuity, low false interruptions, no made-up autobiographical facts.
- **Security:** opt-in owner/game/capture permissions; no viewer-initiated OS control; default OFF. Audit repo access before storing any private content (a repository named Private may still have public visibility).

## Verification limits

This code runs purely on supplied fingerprints and synthetic tests; no game is controlled and no screenshots/voice/chat are captured. Passing these tests does **not** demonstrate a neural-network intelligence increase, an end-to-end inference-speed improvement, autonomous game skill or a finished VTuber. The next real step is a Windows host integration with GameActionGate, Roblox Studio MCP/playtest and independently signed game-state checks. Run live FPS/latency/voice/visual-quality acceptance before considering release.
