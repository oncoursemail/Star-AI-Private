# STAR AI: bounded realtime dialogue, faster intelligence, gaming practice, and expressive VTuber research
**Research and implementation date:** 2026-10-31 (America/Chicago)
**Status:** concrete Python cache-pressure fix + synthetic regression suite committed separately; all other integrations in this document are research/acceptance plans, not delivered live features.
**Default policy:** offline-first, feature flags OFF, no authority to broadcast, launch games, create accounts, spend money, or move the OS granted by generated content.

## 1. Actual repository finding and implemented correction

Inspected `star/stream_director.py` on PR #845, branch `feat/stream-cooperative-motion-cancel-20261030`. StreamDirector already holds an RLock for `enable`, `disable`, `offer`, `propose`, `complete`, and `metrics`. Prior tests verified basic fairness but lacked adversarial multi-threaded synthetic traffic and persistent-cache pressure.

The runtime keeps three distinct time-window receipts: `_recent` (dedupe hashes for moderated chat/ambient events), `_viewer_last_spoken` (per-viewer cooldowns), and `_game_reactions` (heard, independently observed victory reactions). These were time-pruned but had no absolute cardinality limits. An attacker or broken host clock, large configured cooldown, rapid message churn, or many unique game success signals could grow memory beyond the bounded event queue. Worse, `offer()` rebuilds `_recent` when expiring entries, so very large hash sets also increase CPU load per event.

**Implemented:** a 4,096-entry ceiling for each in-memory receipt map. If the dedupe map is full, *new* viewer/ambient content is denied with the anonymous `dedupe_capacity_rejected` counter. Existing duplicate checks still run before capacity checks. Owner interrupts and independently host-verified game events are not subject to chat-dedupe saturation. Older viewer cooldown and verified-reaction receipts are evicted by oldest timestamp if their separate stores hit the cap after audible completion. TTL pruning and disabling the session still clear caches. This deliberately favors bounded memory and live-game responsiveness over admitting all new chat under overload.

**Added offline regression coverage:** concurrent duplicate-message admission, sixteen simultaneous different questions from one authenticated viewer, duplicate speech acknowledgements, disable/ack race, capacity saturation, TTL-based recovery, long-lived per-viewer cooldown bounds, and independently verified game-reaction bounds. No real stream, user data, or Windows hardware is touched. The PR remains draft: these tests are not proof of a production broadcast.

Important limitations: a 4,096-entry deny-new policy is a conservative stream overload policy, not a Twitch API rate limit and not a semantic moderation solution. The authenticated host must still apply separate moderation, per-channel budgets, source identity and duplicate-message IDs; it should also log only aggregate pressure, not message bodies.

## 2. Intelligence = success under constraints, not model size

A larger model can make a better strategy but a worse *real-time* player if it takes too long to act. The best architecture for Star distinguishes four execution bands:

| Band | Typical work | Device intent | Pass/fail criteria |
| --- | --- | --- | --- |
| Reactive, under a live deadline | dodge, aim, move, stop playback, one-clause hazard callout | approved fast path, CPU if game GPU saturated | p95 inference + dispatch reserve fits remaining observation lifetime; fresh host samples |
| Conversational | answer a selected chat question, reason about a visible event, coordinate mascot reactions | bounded language model and low-backlog TTS | first audible response, full answer correctness, no unsupported event claims, no speaking over a turn |
| Deliberative between rounds | analyze mistakes, generate practice drills, retrieve tutorials, plan building steps | stronger offline teacher only after gameplay ends | holdout performance improvements, not subjective claims |
| Autonomic idle/night | research sources, code candidates, test, benchmark and rollback | resource-admitted background workers | independent green tests, bounded CPU/RAM/VRAM and reversible state |

**Reference:** [RealtimeBench: The World Won't Wait, 2026-10-14](https://arxiv.org/abs/2610.20665) evaluates 180 continuously advancing game tasks and reports research improvements using a slower teacher between attempts. Its numbers are not STAR measurements. [Realtime-Bench](https://github.com/RealtimeAgents/Realtime-Bench) provides another relevant continuously running evaluation setup.

Star's existing `game_deadline_router.py`, `game_practice_curriculum.py`, `gameplay_skill_bank.py`, `stream_qos.py`, and `stream_brain_governor.py` already implement pieces of this. Next integration: use a *single* host-owned monotonic clock and a signed gameplay-trial record that joins observation age, action choice, physical dispatch, episode outcome, and independent game-state validation. A correct strategy never excuses a late input.

**Learning gate:** compare each proposed skill against baseline on a balanced held-out set of unfamiliar maps, seeds, enemies and FPS/load regimes. Do not let hundreds of easy attempts mask a failure on one important rare scenario. Keep a short skill provenance record (game version, scene ID, approved permissions, successful/failed evidence, source model, promotion and rollback version). Train or distill only on appropriately licensed data with offline tests.

## 3. Do not assume prompt caching is safe or fast

The official [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures throughput, latency and speculative-draft acceptance against a running server; it does not prove an end-to-end speedup for Star's game + OBS + voice workload.

As of 2026-10-31, published upstream *issue reports*, not independently reproduced Star failures, warn that:

- [#30961, opened October 22, 2026](https://github.com/ggml-org/llama.cpp/issues/30961): unified KV + multiple slots can fail a RAM prompt-cache restore and force costly re-prefill.
- [#27148, opened August 15, 2026](https://github.com/ggml-org/llama.cpp/issues/27148): a reported cross-conversation RAM-cache restore can contaminate output under concurrency. Treat this as a security test case, not a verified vulnerability on Star's installed build.
- [#26207, opened July 28, 2026](https://github.com/ggml-org/llama.cpp/issues/26207): a report describes per-request LoRA changes sharing a cache prefix; the issue was closed as not planned. Isolate model/adapter identity before trusting the cache.

**Suggested A/B setup, not deployed:** pin exact llama.cpp commit, Windows driver, model checksum, quantization, context and slots. For each of 1, 2 and 4 concurrent requests test cache disabled, same-session reuse, and guarded cross-session reuse. Repeat with different persona adapters, private/public prompt separation, same-prefix different conversations, model switch and untrusted prompt. Record cache hit tokens and prefill milliseconds from actual server telemetry, as well as correctness and content isolation. If a reply carries another persona's/private data, reject the configuration regardless of throughput. If real cache hits do not materially reduce p95 first-audio latency, turn off the feature.

Do **not** preallocate an 80 GB RAM prompt cache on Star's 32 GB target computer. Size RAM caches from measured free RAM, OS page faults and actual eviction behavior. Preserve game, OBS and audio headroom. Speculative decoding helps only when the draft model's acceptance gain exceeds its CPU/VRAM costs under the *same* stream load.

## 4. Streaming like a naturally expressive person—without fake human memories

Natural streaming quality requires a closed feedback loop across perception, talking, audio playback and animation, not just more expressive TTS:

1. **Perception:** trust locally captured frames and separately authenticated gameplay success signals; recognize uncertainty, occlusion, hidden HUD elements and game-menu state. Do not narrate viewer claims as witnessed events.
2. **Conversation:** select a question from moderated chat fairly; allow authentic pauses and backchannels rather than interrupting on every VAD peak. [LiveKit's guidance](https://livekit.com/blog/turn-detection-and-interruption-handling) describes adaptive interruptions vs simplistic VAD; self-hosted availability/configuration must be verified rather than assumed.
3. **Voice:** compare Star's current engine with [Kyutai Pocket TTS releases](https://github.com/kyutai-labs/pocket-tts/releases), including October 20, 2026 small English models. Test CPU real-time factor, Windows startup, first PCM chunk latency, voice consistency, laughter quality, interruptions, and licensing before selecting any model. The GPU may be better reserved for the game.
4. **Avatar:** animate mouth volume from **actually played** audio (not generated but unplayed speech); eyes should track appropriate screen objects only when perception confidence is sufficient; blink, breathing, gaze, twin-tail spring physics, emotion intensity and idle microgestures should share one stage clock. Current `StarStage` permits motion only after a host-audible stage, and revoked plans should produce no stale frames.
5. **Identity and memory:** Star can have a coherent fictional persona, interests, playful cat/puppy modes, continuity with Astro and Amber, and stories of episodes she actually streamed. Distinguish confirmed events from fiction and model guesses. Do not fabricate offline friendships, human childhood, or human experiences as facts. Maintain viewer privacy and clear AI disclosure.
6. **Silence:** target better *timing*, not more chatter. Silence during an intense fight is often more believable than narrating every input. Even a voice model with expressive prosody feels artificial if it repeats victory lines or lags an entire round.

**Measure with independent OBS recordings**, not application callback flags alone. Report time from last viewer word to first audible PCM, interruption-to-physical-stop p95, mouth-vs-audio offset p95, words per minute, fraction of unsupported claims, viewer turn fairness, OBS encoded/dropped frames, game 1% low FPS, and measured time spent in idle silence. Ask human raters to compare paired blind recordings with the same game seed and comparable chat load. Star should never label a synthetic reaction as evidence of real feelings or experiences.

## 5. Gaming practice loop that can improve ability

A useful self-learning cycle: **identify one skill -> construct graded practice -> run approved game sessions -> record independent signed outcomes -> diagnose failure -> propose one change -> evaluate on held-out cases -> promote/rollback**. For supported games, prefer public training modes, offline levels, and authorized private servers; do not circumvent anti-cheat or abuse multiplayer games.

Compare adaptive gameplay strategies against fixed baselines using matched seeds. Track (a) win/success rate by difficulty and map, (b) action latency and missed windows, (c) unexpected falls/deaths/damage, (d) recovery after scene transitions, and (e) performance with new rules introduced. Recency windows and skill retention tests must recompute **each** trial in the relevant window, not just the most recent timestamp. Keep mistakes as short verifiable lessons with expiry and confidence, not as automatically accepted model self-criticism.

For general knowledge, organize `source -> claim -> date -> verification method -> permission class -> retrieval scope`. Keep public citations separate from private/project data; monitor staleness for time-sensitive facts, and use a held-out retrieval + question-answer evaluation to catch misattribution and hallucinated citations. Self-improvement proposals belong in Star Core Forge experiments, not direct mutation of the active process.

## 6. Making better games, assets and animations

[Roblox StudioTestService documentation](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) describes scripted multiplayer scenarios and simulated clients. Use it as an executable test lane, not proof of visuals. Star's game-build completion needs:

- **Structural assertions:** tagged instances, dimensions, door clearance, grounded support, anchored props, connected walkable paths, collision groups, no missing walls/mesh references, no obstructed interaction volumes.
- **Visual assertions:** authored camera viewpoints, consistent materials and lighting, legibility at target resolutions, UI alignment, color contrast, animation silhouette/foot planting, transparency/depth sorting, physical hair/cloth clipping, sound synchronization.
- **Functional assertions:** solo and multiplayer join/leave/respawn, mobile/controller inputs, replicated inventory, persistence edge cases, network latency, player-count stress, reconnect paths and full gameplay completion.
- **Creative evaluation:** compare several independently generated concepts using a fixed art-direction rubric; do not mistake a compiling Luau script for a polished experience. Attach reproducible screenshots/videos and independent pass/fail results to candidate builds, not just the model's self-assessment.

Treat Rust as an **optimization tool for proven hot spots** (frame preprocessing, structured telemetry, high-volume event filters, and safe native IPC). Profile before migrating working Python orchestration: Rust alone does not increase model reasoning accuracy, and additional FFI/process boundaries may *increase* end-to-end latency. Retain a Python fallback, Rust tests, measured p95 win, and compatibility checks before changing defaults.

### New October 2026 evidence: inspect before editing

The [October 1, 2026 OpenGameEval paper](https://arxiv.org/abs/2610.02563) evaluated 13 frontier agents on 84 human-curated Roblox Studio development tasks with 16 attempts each. Its analysis reports that *within matched task/model comparisons*, inspecting all reference-touched objects before changing them correlates with a 13.4 percentage point higher pass rate on scene-only tasks and 9.8 points on script-only tasks relative to inspecting none. This is observational correlation in the research, not a STAR speedup or guaranteed causal effect.

**STAR change proposal:** add an explicit `inventory -> inspect references -> plan edits -> apply bounded patch -> run Studio tests -> compare camera captures` contract in the game builder. Before creation, collect the instance hierarchy, relevant properties, constraint relationships, Humanoid/RigType assumptions, world transform/anchoring, UI scales, and dependency graph. Fail a build candidate if it edits an unseen target, breaks support geometry, leaves orphan attachments, or degrades a known-good scene. Validate across several game variants rather than replaying the same place. Roblox publishes the [open-source evaluation harness](https://github.com/Roblox/open-game-eval) for reproducible Studio-based checks.

For animation, [Live2D Cubism physics documentation](https://docs.live2d.com/en/cubism-editor-manual/physics-operation/) explains real-time hair movement driven by face turning and physics sampling. Treat hair/cloth/tail simulation as *render-side parameters derived from motion*, not as LLM-generated frame-by-frame commands. Start with 30 or 60 Hz rig output and measure lip/eye/hair latency while OBS and the game are active; keep reduced-motion ON when opted in, and stop all physics cues on a revoked audio/scene epoch.

## 7. Priority implementation sequence and release gates

**P0 — trustworthy realtime baseline.** Publish concurrency/cache-pressure regressions; run Python/Ruff/Pyright and existing stream suites; inspect exact-commit Actions status. On the authorized Windows box, collect real CPU/GPU/RAM/VRAM/game FPS/OBS/TTS data, and verify actual audio/visual playback. No headline speedups without paired measurements.

**P1 — complete the measured realtime loop.** Use existing governor, deadline router, stage and stream adapters as one host-owned process graph with monotonic clocks. Enforce bounded queues, physical stop/flush, no stale animation, and strong chat trust boundaries. Simulate network outages, Twitch reconnect duplication, VAD false barge-ins, gameplay success rumors and overloaded CPU.

**P2 — offline game skill distillation.** Use practice curriculum + signed evidence + independently held-out trials before promoting a new strategy; incorporate hardware-load regimes into acceptance. Keep the live reactive model fixed during active matches.

**P3 — expressive voice and coordinated mascot.** Compare local TTS options including October 2026 Pocket TTS, implement actual PCM-based motion sync and animation cancellation, and test paired human preference with no false memories.

**P4 — game-building quality forge.** Prioritize a complete, instrumented Roblox sample project with build integrity, StudioTestService multiplayer lanes, visual screenshots, owner-readable failure reports and rollback.

### Provisional acceptance matrix (targets, not observed results)

| Workload | Proposed threshold | Reject on |
| --- | --- | --- |
| Chat admission under 16 parallel offers | at most 2 pending per viewer; no duplicate acceptance | queue corruption, uncaught errors, unbounded receipts |
| Interrupt | cancellation and audio stop acknowledged before new speech; p95 measured against baseline | older epoch stops newer speech |
| Active game inference | p95 latency + dispatch strictly below scene deadline | stale clocks, unverified skill, FPS regression |
| Voice / avatar | p95 A/V mouth offset <=100ms on independently captured output | unplayed audio drives lips, fabricated victory |
| Gaming skill | higher holdout pass rates across game/scene strata with paired confidence intervals | gains only on training maps, increased missed deadlines |
| Infrastructure | stream and OBS stable while memory stays under observed host budgets | OOM, paging storms, uncontrolled background worker |
| Game creation | functional automated tests + manual/vision review of geometry and presentation | code compiles but scene visually breaks |

These are engineering goals, not claims of achieved Star performance. A speed change must preserve game success, factuality, viewer safety and broadcast stability. Keep GitHub PR #845 draft until reviewers validate the full stream path; GitHub is an export/review channel, while Star Core Forge remains the intended internal source-of-truth for self-directed experiments.

### Security and ethics

Never publish API keys, raw chat logs, private TTS/voice recordings, account IDs, private game assets or private knowledge in public GitHub. The repository named `Star-AI-Project` is public. Signed evidence and permission attestations must originate from trusted local host devices, not model text. Maintain irreversible/external action approval; normal self-tests and offline learning can proceed without repeated prompts in owner-approved bounded budgets.
