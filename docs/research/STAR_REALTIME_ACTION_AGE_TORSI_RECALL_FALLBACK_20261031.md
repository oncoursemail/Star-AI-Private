# Star AI: real-time intelligence, resilient VTuber memory, and 2026 research
**Prepared:** 2026-10-31 UTC. **Scope:** offline-first, owner-controlled architecture; no live game, OBS recording, GPU benchmarking, or production deployment in this change.

## What was actually implemented

1. `star/game_action_freshness.py`: opt-in, dependency-free gate for **observation-to-dispatch age**, per-session replay rejection and clock validation. Proposed actions carry timing metadata only: the gate **does not control games or authorize input**. A trusted permitted-game adapter must call `assess()` immediately before dispatch, and independently enforce the game's rules. Default OFF; per-game/session isolation; zero untrusted text retained. Synthetic tests in `tests/test_game_action_freshness.py`.
2. `star/stream_stage.py`: if an optional gameplay journal's monotonic clock is ahead of the streaming host clock, fail closed on **memory insertion only** rather than throwing after the speech director has issued a pending intent. A privacy-safe `journal_recall_skipped` counter reports the fallback. The viewer can still receive an appropriately moderated response without invented memories. Tests: `tests/test_stream_stage_journal_clock_fallback.py`.
3. These are **infrastructure capabilities**, not evidence that Star already plays faster, speaks naturally, or has improved model weights. They need GitHub CI and actual game/Windows/OBS rehearsal.

## New research: why action age matters more than isolated token speed

Pan et al., **The World Won't Wait** (posted October 14, 2026), introduce RealtimeBench: 180 tasks across six game types where the environment continues to change during model inference. They distinguish strong deliberation while paused from successful action under a live clock. Their Two-Timescale Offline Recursive Self-Improvement (TORSI) uses a strong *offline teacher* to diagnose failures and improve a fast *online student*. They report a mean test score increase from 13.51 to 24.19 after two offline improvement rounds for one agent; this is **their result, not Star's**.

Source: https://arxiv.org/abs/2610.20665

**Architecture proposal:**
- **Game clock / reflex lane (host):** capture authoritative observation with monotonic `observed_at_s`, game scope and sequence. Choose or execute a compact tested action policy. Reject commands whose observation-to-dispatch age exceeds the game-dependent budget; safe fallback is no action or an explicitly tested neutral command.
- **Fast decision lane (on-device):** cheap structured state, cached game-specific mechanical rules, frame/sample selection, bounded reasoning with a deadline. Avoid large-model calls on every movement tick. Never claim real-time skill from a paused clock.
- **Slow teacher lane (off-stream or idle):** a stronger reasoning model studies permitted practice failures, proposes revised policies/prompts, and builds novel practice maps. It may use sandboxed game simulators and knowledge retrieval. It must not issue time-sensitive game input.
- **Evaluator / Star Core Forge:** run an identical baseline/candidate harness on preregistered, unseen maps and seeds, both paused and realtime, with outcomes from game state rather than self-report. Use the existing `game_skill_gate.py` plus signed evaluation wherever applicable; never automatically promote a change based only on a positive narrative.
- **Knowledge and memory lane:** store versioned, deduplicated skills with source, license, timestamp, confidence, tested game/version and failure cases. Retrieve concise confirmed facts into the fast student, not full transcripts or an endless context window.

**Measures** to capture per action (no player identifiers): observation timestamp, decision-produced timestamp, host dispatch timestamp, game input acknowledgement, game FPS, game progress, successful objectives, and tail-latency (p50/p95/p99). For live policies, an action that arrives *after* the hazard does not count as a successful decision, regardless of its answer quality. Suggested 250 ms default in the new gate is only a configurable starting budget, **not a validated universal game threshold**.

A game adapter must separately protect mouse/keyboard control, game terms-of-service compliance, owner authorization, focus checking, and emergency stop. Never reuse replayed commands after a reconnect.

## Gaming and game-creation benchmark evidence

**GameWorld / GameWorld-RT** covers 34 browser games and 170 tasks, with outcomes derived from serialized game state; its realtime variant measures actual continuing environments rather than paused ones. Use it to build independent checks for navigation, timing, combat/puzzles, and policy transfer without inferring success from screenshots.
Source: https://gameworld-project.github.io/ (2026)

**OpenGameEval**, posted **October 1, 2026**, tests agentic Roblox development in stateful Studio sessions across 84 human-curated core tasks. It separates scene inspection from editing and evaluates changes using executable scene and play-session checks. In its reported results, inspection of related scene objects predicts greater success. Adopt a strict *inspect → plan → edit → playtest → repair* protocol, and do not call work complete from code compilation or a single pretty screenshot.
Sources: https://arxiv.org/abs/2610.02563 ; https://github.com/Roblox/open-game-eval

**StudioTestService** supports scripted Play/Run/multiplayer test sessions in Roblox Studio, including simulated clients. Build reproducible private test fixtures for spawn points, remote-event ownership, replication, joining/leaving, overlapping meshes, missing collision, UI scaling, animation timing, and win conditions. Compare successful end-to-end behavior, not merely number of generated assets.
Source: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

**Next measurable Star game-creation acceptance** (proposed): unseen Roblox tasks, verified functional completion, no missing critical scene nodes, no colliding/unattached structural parts, tested at at least two viewport sizes, paired scene snapshots, multiplayer checks where relevant, and an explicit human visual-polish review. Report independent outcomes and failures, not promotional claims.

## Faster local AI on an 8 GB gaming GPU

As of the October 2026 `llama.cpp` server docs, the server exposes continuous batching, prompt caching, speculative decoding, token/slot metrics and memory-related controls. These are **experiments**, not automatic wins.
Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md

**Experiment matrix:**
1. Establish Windows baseline while a game + rig + OBS-like local recording are actually running. Log gameplay frame-time p95, inference prefill/decode latency, peak VRAM, process RSS, input age and speech first-audio p95.
2. Compare a tiny policy/fast model vs a larger reasoning worker for each task type: player input, short viewer answer, long research, Roblox code, multimodal scene critique. Route by *quality under deadline*, not tokens/sec alone.
3. Test fixed-prefix prompt reuse and slot locality before bigger KV cache configurations. Stable prompt order matters; a cache miss can erase theoretical model-speed gains. Audit RAM pressure, not just VRAM.
4. Test speculative decoding only when acceptance rate and measured throughput justify the extra draft-model compute. Test batching under parallel user requests, but limit batching during frame-critical game play.
5. Isolate low-latency audio, input, and game graphics from heavy image generation, offline teacher training, background indexing, and large model loads. Use an explicit resource governor with admission control, deadlines, cancellation and recovery.
6. Keep machine-specific results. A speedup on one GPU or CPU must not be extrapolated to Star's hardware.

Proposed guardrails for an **initial experiment, not performance claims**: keep the streaming game's p95 frame-time near a 60-FPS budget (16.7 ms, game dependent); defer nonessential speech when FPS falls or audio backlogs; prefer avoiding VRAM thrash to squeezing in one more model; preserve owner interruptions. Record *both* latency and accuracy for the same scenario.

## Natural, expressive VTuber behavior: a falsifiable quality loop

Naturalness is not more filler or exaggerated persona. The useful target is **timely, consistent, context-specific behavior with grounded experiences**:
- **Listening:** use voice activity detection + conversational end-of-turn reasoning to avoid interrupting real pauses, with low-latency owner barge-in. LiveKit documents a local CPU `v1-mini` turn detector. This is a candidate integration that should be measured with overlaps, laughter, thinking pauses and false positive cuts.
  Source: https://docs.livekit.io/agents/logic/turns/turn-detector/
- **Speaking:** test voice duration, pronunciation, sentence prosody, interruption fade-out, acoustic laughter and pacing via blind listening. Kyutai released Pocket TTS v4.0.0 **October 20** with new small English variants and v4.0.1 **October 21** fixing small-model pronunciation; these are candidate CPU experiments, not a substitute for voice-quality listening tests.
  Source: https://github.com/kyutai-labs/pocket-tts/releases
- **Embodiment:** blend speech-driven mouth movement, gaze targets, expression timing, deliberate idle motion and secondary twin-tail/hair physics. Maintain Star's accepted black/gold original character identity, cat/puppy/normal modes and reduced-motion setting. Keep avatar animation frame generation cancellable and protect render performance.
- **Attention:** prioritize the game during danger; deliberately stay quiet during precision tasks; react after verified wins, not predictions; address viewer questions only after moderation and with platform-aware identity fairness.
- **Continuity:** recall only host-attested, in-session achievements; explicit permission is required before putting those facts into public speech context. Distinguish observed facts from unverified claims. Never invent past streams, emotions, relationships or a human biography.
- **Social authenticity:** be transparent that Star is an AI creator/VTuber. A coherent character, humor, preferences and thoughtful audience engagement are achievable software goals; personhood or consciousness cannot be guaranteed by a persona prompt.

**Quality acceptance:** blind A/B ratings for naturalness, pronunciation, timing, humor and over-talking; count interruption misfires, repetitive reactions, false-claim incidents, CPU/GPU load, first-audio delay and synchronization drift from OBS loopback. Reuse the same game segments and listener criteria across revisions.

## General intelligence and knowledge beyond Roblox

Build an evidence-oriented, local-first knowledge graph with separate **epistemic classes**: cited external claims, inspected code facts, verified exercise outcomes, synthetic hypotheses and persona preferences. Attach provenance, date, retrieval/source licensing, relevance, test-result receipts and expiration policy. Keep web search owner-controlled and OFF by default.

**Autonomous curriculum:** self-generate problems across programming, visual design, Blender/animation, audio, math, physics, writing, cyber hygiene, world knowledge, tool use and social dialogue. Use difficulty ladders and never-before-seen holdout tests. The slow teacher may propose tactics; an independent harness decides whether they work. Store successes **and failures** so Star does not repeatedly relearn broken strategies. Keep learning and self-improvement within local Star Core Forge; export GitHub PRs as optional review/publication snapshots.

**Design/build visual inspection:** 3D topology and bounding-box checks, overlap and anchor checks, camera/viewport screenshots, multi-angle silhouette assessment, Roblox client/server state checks, motion envelope comparisons and human aesthetic ratings. Use separate critics for visuals, logic, performance and safety. Never let one model grade its own work without independently testable evidence.

## Concrete next integration order

1. **Production adapter audit:** identify permitted game input boundary; make `GameActionFreshnessGate.assess()` the last timing check at dispatch. Preserve opt-in policy and a hardware-safe emergency stop. Validate under real, continuously running games before enabling.
2. **Clock-domain contract:** unify host clock for game observer, journal, stage and output device. Retain optional-memory fallback for reboot/reconnect or mismatched clocks; count skipped recalls and alert on rate increases.
3. **Rehearsal harness:** OBS local recording, desktop gameplay, STT/voice, avatar animation, telemetry; capture synchronized timestamps without personal chat data. Ensure image/video capture uses explicit opt-in and retention.
4. **Fast/slow teacher experiment:** offline practice 20+ paired unseen trials across multiple scenarios and realtime/paused separation, with independent signed outcomes; avoid benchmark leak from practice into holdout.
5. **Voice/avatar comparisons:** evaluate Pocket TTS and LiveKit turn detection against the existing pipeline. Switch only if reliable voice/timing gains justify CPU costs.
6. **New game creation gauntlet:** OpenGameEval and proprietary Roblox visual/functional tests; measure whole-task completion rather than number of assets.

**Safety and delivery boundaries:** production services, models, OBS, desktop control, broadcasting, credentials and finances have not been changed. Prototype gates neither imply independent gameplay mastery nor guarantee natural speech. All new functionality is opt-in. The repo named `Star-AI-Private` was reported public in GitHub metadata; avoid committing secrets or private recording paths, and separately review repository visibility.
