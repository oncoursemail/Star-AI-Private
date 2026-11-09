# STAR: real-time game skill evidence, low-latency intelligence and believable VTubing
**Research and engineering note — 9 November 2026**

## Status and scope

**Implemented in this branch:** a stricter, offline, host-supplied game-win evaluation gate in `star/game_live_clock_benchmark.py`, plus regression tests. It does not train a model, execute game inputs, increase model throughput, connect to a Windows audio device or start OBS. It is *evidence hygiene* to prevent a faster but unreliable agent from claiming gameplay improvement. It builds on the existing pending PR #1085; production `main` is unchanged.

The earlier LIVE benchmark compared paired game-state progress, inference-to-input acknowledgement latency, game-world advancement, FPS and OBS loss. A candidate could still qualify from a large mean progress increase and **one** additional successful level, even though a single discordant binary result provides little evidence of improved win probability. It also accepted independent-looking IDs referring to the same scenario and same starting-state fingerprint under different pair IDs.

**New safeguards (offline):**
1. Within a cohort, reject any second paired case with the same `(scenario_id, initial_state_sha256)` even when pair and episode IDs differ. Those are repeated starting states, not fresh independent holdouts.
2. Demand >=3 distinct scenario IDs among fully verified running-world pairs before a positive manual-pilot recommendation. This is a deliberately weak *minimum diversity screen*; it does **not** demonstrate generalization across games, strategies, map families or players.
3. Compute the **one-sided exact paired discordant-win p-value**, testing new candidate-only timely wins against baseline-only timely wins. Require `p < .05` *in addition to* existing progress-CI, win-count, latency, OBS and frame-time conditions for a positive advisory. Expose the p-value in the anonymous report. If there are no discordant pairs, the p-value is `None`.
4. Preserve all existing guardrails: unverified or non-live trials, incomplete pairs, candidate regressions, game-clock pause tricks, missing input acknowledgments, repeated episode IDs and performance regressions still cannot promote an agent.

**Important statistical limitation:** A p-value is a diagnostic under genuinely independent, preregistered paired cases, not a proof of ability or causal effect. Multiple experiments or optional stopping require multiplicity correction / separate sealed evaluation. Host-supplied attestation flags are *not* cryptographic host verification. The primary trusted game-harness and persistent `HoldoutOnceLedger` must protect a *real* sealed test set.

## Findings and designs grounded in primary sources

### 1. Real-time gameplay: perception-to-action speed is not the same as game mastery

The October 2026 Gym-Anything-RT benchmark varies real-time/paused clocks on comparable minigames and exposes large real-time competence gaps. STAR already has `game_live_clock_benchmark`, game skill and transfer gates, action-feedback and input watchdog modules; the opportunity is integrating them with native validated trials rather than creating a second competing scorer.

**Proposed protocol:** owner-curated private minigames with resettable initial-state digests, sealed maps and seeds, random AB/BA model order; host-measured screenshot capture, state observation, model decision, OS input acknowledgement, world-clock advancement and independently observed victory. Include failure episodes without filtering. Compare 20+ sealed pairs over >=3 stages, and retest on entirely separate game families with a *fresh* reservation. A model is not "smarter" because it generates actions faster unless it also wins more without worsening FPS/OBS.

**Next implementation:** instrument Brain 2's game harness to issue trusted start-state receipts, write aggregate-only JSONL and invoke the existing scorer offline. Check source provenance, no overlapping holdouts and external evaluator independence; test first in a non-broadcast sandbox.

Sources: Gym-Anything-RT (Oct. 2026) https://arxiv.org/abs/2610.37567 ; https://github.com/gym-anything/gym-anything-rt ; NIST paired-binary/McNemar guidance https://itl.nist.gov/div898/software/dataplot/refman1/auxillar/mcnemar.htm

### 2. Game creation: inspect and verify, not just write Luau quickly

OpenGameEval (1 Oct. 2026) reports 84 human-curated Roblox Studio tasks, reproducible engine tests and improved outcomes associated with relevant object inspection before edits. Use STAR's Studio practice runner and best-of-N generate-and-verify to produce *executable* improvements: snapshot project -> inspect dependencies -> constrained edit -> Luau/style/static checks -> actual Studio test -> screenshots/scene checks -> repair -> rollback or graduate. Separate "code compiles," "playtest passes," "visual quality passes" and "release approved." Reuse verified work only after held-out runs.

Roblox's 4 Nov. 2026 Studio MCP/Open Cloud expansion adds permissioned asset imports and game management. Default to **Safe** scopes on a test place. Publishing, live datastore writes, purchases, moderating players and public server changes remain separately approved; never equate game-playtest authority with release authority.

Sources: https://arxiv.org/abs/2610.02563 ; https://github.com/Roblox/open-game-eval ; https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849 ; https://create.roblox.com/docs/studio/mcp-open-cloud

### 3. More natural on-stream conversation: a deadline-driven dual-brain design

Proact-VL (3 Mar. 2026) studies AI companions that *decide whether and when* to comment on live gaming scenes. Use two distinct work queues: (A) an always-responsive event and speech lane for hazards, user/owner speech, short scene-grounded reactions and stop/flush; (B) a cancellable slow-reasoning and retrieval lane for tactics, research, game creation and general knowledge. Streaming persona should be recognizably Star: consistent voice and playful interests, appropriate pauses, graceful interruptions and synchronized eye/blink/gesture/audio cues. Do not manufacture memories, feelings, physical experiences or human identity claims. Viewers should know they are interacting with an AI.

**Acceptance:** privately record 30/60/120-minute rehearsal slices. Human raters score relevance, repetitive chatter, timing, voice identity, interruptibility, avatar lip-sync and truthful contextual memory. Audio-device proof and OBS stability are required independently. Uncertain gameplay state -> say less, not assert invented achievements. Owner interruptions outrank generated chatter; nobody can trigger owner-only tools by chat message.

Source: https://arxiv.org/abs/2603.03447

### 4. Faster, smarter local inference on an 8 GB RTX 4060

STAR cannot optimize local inference and game rendering separately on the same card. Benchmark *wall-clock experience* with the game, OBS, avatar, TTS and model loaded simultaneously. Capture baseline P50/P95 time-to-first-audible (not only first token), output token latency, peak GPU memory, frame-time P99, dropped OBS frames and verified-game win rate. Use `llama-bench` for isolated prompt/decode microbenchmarks but do not mistake that for end-to-end streaming performance; tokenization and sampling are not included in its reported generation throughput. Compare 4-bit variants, KV cache format, context caps, prefix caching, context retrieval quality, speculative decoding and model routing **one change at a time**, with quality checks and A/B reversal. Use a smaller fast model for reactions and a higher-quality planner only when there is time; move non-urgent speech or training work to CPU/Brain 1/overnight when that improves *measured* results.

When GPU utilization is high, prioritize the active game and OBS; give optional VLM/TTS workers a bounded lease, and skip them when telemetry is stale or frame-time rises. **Do not blindly force Windows HAGS on/off:** NVIDIA and OBS publish differing advice depending on device and failures; benchmark with STAR's real Windows and OBS versions.

Sources: https://github.com/ggml-org/llama.cpp/tree/master/tools/llama-bench ; https://obsproject.com/kb/hags ; https://www.nvidia.com/en-gb/geforce/guides/broadcasting-guide/

### 5. General knowledge and long-term learning without self-delusion

Use claim-level evidence provenance and expiration: distinguish *verified tool result*, *project fact*, *tentative inference*, *persona fiction*, and *outdated information*. Maintain compact per-project memory indexed by source and date. Recheck fast-changing game patch notes, API signatures and prices; do not silently train on unverified model-generated answers. Preserve stable skills using reproducible tasks with pass/fail artifacts and separate preregistered holdouts. Let Star create increasingly difficult non-production practice problems, test improvements, and graduate only those that beat previous versions in independently scored trials. Protect secrets and human messages from self-training datasets unless permitted.

## Prioritized next work (NOT implemented here)

1. **Independent Brain 2 host receipts** feeding the existing live-clock scorer: game process identity, map/version, state digest, OS input acknowledgement, world advancement, real outcome; protect signed run IDs and maintain single-use holdout reservations.
2. **Measured Windows gaming + OBS + Star speech rehearsal** with workload routing toggles OFF by default; promote latency improvements only if voice quality and P99 game frame-time remain acceptable.
3. **Source-grounded conversational memory / social turn policy**, with separate public chat vs owner-privileged commands and explicit AI disclosure.
4. **Studio agent loop** using Roblox MCP playtest and OpenGameEval-like validators; restrict to disposable games and owner-approved publication.
5. **Shared hardware governor** with reserved GPU resources for the game and OBS, opportunistic inference, and fail-closed scheduling on missing data.

## Verification and rollback

Regression tests cover duplicate starts, a single lucky new win despite a large progress mean, single-stage overfitting, and a strong successful cohort. The full repository CI should run before merge; no hardware performance claim is made until native Windows verification. The only production-facing change is an *offline* and *advisory* eligibility threshold. Roll back this one module and its test changes if a genuine independently reset trial protocol is blocked; do not bypass or silently loosen the gate to obtain a positive result.
