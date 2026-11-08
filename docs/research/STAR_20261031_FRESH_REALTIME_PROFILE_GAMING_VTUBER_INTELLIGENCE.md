# STAR: Fresh real-time profiles, verified game intelligence, and natural VTuber operation
**Research and engineering update:** 2026-10-31. **Status:** development-only; owner opt-in; no Windows/OBS/game deployment.

## What was observed in this repository

1. The new `GameDeadlineRouter` compared the current game-scene deadline with a *session-scoped* historic p95 inference latency. Its old timing records had **no host-clock timestamps**, so an inference profile measured during idle conditions could still justify a live action much later in the same session, even when the fast path had not been measured recently. Host CPU/GPU pressure flags help, but are not a substitute for sample freshness.
2. GitHub Actions offline run [41232400677](https://github.com/oncoursemail/Star-AI-Private/actions/runs/41232400677) reported Python and React **success**, but Pyright **failure**: `game_deadline_router.py:29` had an `object`-to-float complaint; `general_knowledge_benchmark.py:314-315` subscripted app identities that might be `None`. These are genuine blocking type-checker failures, not new evidence of model performance.
3. Changes on this branch add required, ordered `sample_host_ms` timing evidence and required `now_host_ms` for *live* advisory eligibility, expire latency records older than 15 seconds by default (configurable 250–60000 ms), and require the minimum number of **recent** completed/timeout samples before advising the fast path. Timings are verified only by a future trusted host. An empty, future-clock or insufficiently fresh profile results in `skip`, **not** an optimistic route. Explicitly narrowed app identities and runtime-validated float casts address CI Pyright errors.
4. **Important:** these are advisory API and test changes, not authorization to operate a game. A Windows host must use a *single monotonic clock domain* (for example, `time.perf_counter() * 1000`) for each measured inference completion and each advisory query. A different time origin or a reboot must force a new router session. All actual input still requires the independent freshness gate, game permissions and host recheck.

## The next experiment: prove lower end-to-end gaming latency

**Do not optimize only tokens/second.** Create a repeatable, legally authorized simulated gaming loop with fixed seeds and paired game states. For each observation, capture: scene timestamp, preprocessing latency, queue time, model first token/decision completion, pre-dispatch assessment, actual input dispatch acknowledgment, scene outcome and game frame-time percentiles. Keep private frames off GitHub.

Compare (A) current reactive route, (B) recent-profile deadline-aware route, and (C) deadline-aware route plus a separately vetted CPU reactive model. Use the same model weights/configuration per A/B unless testing a *declared model axis*. Pre-register task seeds and never tune using held-out scenarios. Reject a candidate if its held-out win/progress score falls, its p95 observation-to-dispatch latency rises, or OBS/game frame-time regressions exceed the host's approved limits. Track p95 **per scene type** so easy scenes cannot hide hard-scene regressions.

A practical safety invariant: **observation age + measured inference tail + dispatch reserve must fit the host's scene deadline**. This is a *necessary* condition; the strategy may still be wrong, and actual input dispatch may be late. Use an explicit no-op for missed windows, not frantic, unverified model actions.

## Fast learner / slow teacher / third-party evaluator

Recent [RealtimeBench / TORSI (2026-10-14)](https://arxiv.org/abs/2610.20665) studies an agent learning between attempts in games that keep moving during inference. It reports 180 tasks over six game types, and improvements in its own held-out evaluation through slow teacher analysis of fast-agent failures. This is **not** proof that the same gain transfers to STAR.

STAR-specific design:

- **Real-time student:** bounded scene state + short reusable skill card + fast action hypothesis; hard deadline routing; avoid online deep reasoning under player input timing. Optional deterministic fallback rules for safe, frequently repeated actions when independently validated.
- **Slow offline teacher:** replay *consented, de-identified* synthetic or game-host-signed failure traces; propose action strategy diffs and counterexample tasks. No automatic promotion, privileged tool use, or unsupervised production edits while broadcasting.
- **Skill lab:** signed practice receipts, curriculum difficulty, adversarial scenarios, multiple maps, old-version compatibility, transfer holdouts, latency and win/progress metrics. Separate practice data from sealed evaluation tasks. Better descriptions are not the same as verified mastery.
- **Core Forge:** keep source, experiment lineage, semantic diffs, parent commits, rollback points and reproducible benchmarks **locally**. GitHub remains optional review/export. Only promote improvements after isolated tests and owner-authorized gates.

## General knowledge and autonomous problem solving

Prioritize *correctness per joule and per second*, not unchecked corpus size. Build four separate stores: (1) licensed, cited factual retrieval with provenance/expiry; (2) tested executable skills; (3) hypotheses marked unverified; (4) clearly labeled Star/Astro/Amber character lore. Prevent viewer chat, copyrighted content, and synthetic memories from entering a trusted factual store by default.

Evaluate on **new, unseen** reasoning, coding, Roblox Luau, Rust, debugging, UI composition, Blender scene geometry and games; group by task and dataset version. Include source retrieval, citation verification, abstention on insufficient evidence, and code execution where safe. STAR's existing ten-task public general-knowledge development benchmark is a **smoke test**, not a claim of general intelligence.

For software improvement, run multiple small candidate solutions in isolated containers, lint/typecheck, unit-test, run game simulation where available, examine visual screenshots and retain only independently passing candidates. Measure cost of failures, correction iterations, latency, and quality. Do not imply a Rust rewrite automatically makes inference faster: benchmark actual hot paths before moving Python components to Rust, and preserve Python model interfaces where they dominate cost.

## Inference / CPU-GPU sharing on 8 GB VRAM

[llama.cpp speculative decoding](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) supports draft models, n-gram schemes and implementation-dependent EAGLE-style variants. The official [SPEED-Bench client](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) measures concurrency, latency, throughput and acceptance against an already running llama-server. On STAR's gaming GPU, run a factorial sweep with fixed prompts and outputs: baseline / speculative mode / prompt cache; GPU-offload budget; single versus concurrent slots; game + OBS idle versus active. Confirm response **accuracy**, VRAM budget, first-response p50/p95, thermal/CPU pressure, dropped OBS frames and p95 gameplay frame-time together. A faster draft on an isolated benchmark may lose when gaming/streaming share VRAM.

Policy: reserve streaming, gameplay and critical speech capacity ahead of research/training; pause background jobs when OBS output is active or telemetry is uncertain. Monitor *actual* input/output and reset epochs on OBS reconnect. CPU TTS may improve GPU headroom, but is not automatically faster on a limited CPU.

## A more natural and clearly identified AI VTuber

STAR should be playful and expressive, **not** deceptive about being human. Her real gameplay observations can create truthful jokes, frustration reactions, victories, memories and evolving preferences; a fictional backstory must be unmistakably lore, not presented as lived human history.

Conversation loop:
1. Receive echo-cancelled, authenticated owner speech and moderated viewer-chat events. Acknowledge with low-latency backchannels only when timing/intent confidence is high; ignore noise, spam and false interruptions.
2. Distinguish uninterrupted utterance, uncertain pauses and end-of-turn. The [LiveKit local `v1-mini` detector](https://docs.livekit.io/agents/logic/turns/turn-detector/) is a candidate, not yet installed; compare it against current local VAD using false-cutoff, missed-interruption and tail latency on opt-in synthetic test audio. Keep owner barge-ins higher priority than jokes.
3. Speech should use a short plan: intent, emotional intensity, truth-grounded content, sentence length, and optional expressive cue. Audio playback acknowledgment drives mouth motion; audio cancellation must cancel the corresponding cue epoch and unfinished sentence.
4. Coordinate blinking, gaze toward actual gameplay focus, mouth visemes, head/arm micro-motion, physically plausible twin-tail movement, and occasional synchronized Star/Astro/Amber reactions. Avoid continuous idle talking, unnatural random expressions and constant eye movement.
5. Add a natural **silence budget** during fights, menu selection, high game load or unfamiliar scenes. Add occasional surprise and laughter triggered by authentic game events, never arbitrary timers alone.
6. Compare current voice with [Kyutai Pocket TTS v4.0.1 (2026-10-21)](https://github.com/kyutai-labs/pocket-tts/releases), especially lightweight CPU English models, **without replacing** the existing voice until listening tests and latency measurements pass. Score speaker identity consistency, natural emphasis, onset and stop latency, laughter quality, and CPU/game-frame contention.

## Autonomous game creation: judge the build, not the code diff

Use the [Roblox Studio built-in MCP playtesting workflow (announced 2026-03-05)](https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643) and [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) for authorized single/multi-client scenarios. A project is not finished merely because scripts compile.

Create a visual + geometric integrity gate for missing walls, unsupported props, z-fighting, misplaced meshes, scale and grip problems, anchor/collision failures, legibility, layout hierarchy, character rig joints, material/lighting consistency and animation transitions. Run simulated players across a full gameplay journey and compare screenshots under multiple camera angles. Require human review for aesthetic milestone releases.

## Reproducible acceptance on the Windows host

- Keep every new capability default-OFF. Verify that app startup, game FPS and OBS idle/broadcast behavior are unchanged when disabled.
- Host monotonic timings: simulate clock jumps, unchanged timestamps, delayed inference completion, stale cache reuse, model swap, game switch, OBS reconnect, 8 GB VRAM pressure and CPU pressure.
- Run at least 20 paired holdout game trials per scene type, measuring p50/p95 end-to-end input delay, win/progress, failures and skipped late actions. Increase sample count if confidence intervals remain wide.
- Live streaming rehearsal: 30 minutes of *authorized private test output* with synthetic chat; confirm OBS render/encoding loss, voice interruption, avatar sync and game responsiveness. Do not publish viewer voices or recordings.
- Core Forge retains clean rollback; only consider promotion after green Python/React/Pyright, independent skill checks, live hardware acceptance and owner deployment approval.
- Repo currently reports **public** despite its `Star-AI-Private` name. Do not commit tokens, private audio/chat, actual credentials or identifying gameplay logs.

**Current evidence boundary:** source/test changes and this engineering plan are published to a draft GitHub branch. No actual game was played, neural model was trained, voice synthesized, OBS broadcast started or performance increase measured in this iteration.

## Addendum: fix stale practice evidence masquerading as retained gaming skill

A second production-code audit found a real semantic mismatch. `GameplaySkillBank.practice_evidence()` previously returned all signed practice from a **90-day** bank retention window. `recommend_practice()` applied a **7-day** recency test only to `most_recent_unix_s`, while calculating Wilson confidence using the entire 90-day success/trial total. An agent with twelve successes eight days ago and **one failure now** would appear to have 12/13 recent successes and qualify for the next tier. That does **not** demonstrate current mastery.

This update adds a bounded `max_age_s` parameter to the signed bank's practice-only aggregate query and passes the curriculum's `max_evidence_age_s` through to the bank. Every signed trial must fall inside the requested lookback to contribute its win/failure. Historical records can still be retained for audit; they cannot inflate present-day retention qualification. A cross-module regression demonstrates 12 old successes + 1 current failure yielding only **0/1** recent success, hence rehearse rather than advancement. Validation trials stay excluded from practice selection, but are still integrity-checked. Lookback bounds are strict and synthetic signing keys remain only in tests.

This is an **evidence correctness** improvement, not actual game learning or proof the model can win more games. The underlying bank must continue independently validating the signed observation and remain separate from the offline teacher. The first live integration should compare promotion counts and false unlocks under aging/skill drift, not just code coverage.

This aligns with [SkillLearnBench (2026-04-22)](https://arxiv.org/abs/2604.20087), which reports that skill learning gains are task-dependent and that self-feedback alone can cause recursive drift. It supports evaluating changes against external outcomes rather than rewarding an AI for declaring that it improved.

For game creation, [Roblox OpenGameEval's 2026-10-01 paper](https://arxiv.org/abs/2610.02563) evaluates 84 core tasks in stateful Studio sessions and reports correlations between inspecting target objects before editing and higher success. An actionable STAR experiment is to require an explicit **scene inventory before mutation** on held-out scene tests, measure tool overhead and compare independently executable outcomes. Correlation is not proof that the same rule will improve STAR.

For avatar animation, [Live2D's official physics documentation](https://docs.live2d.com/en/cubism-editor-manual/physics-operation/) describes runtime swinging-hair simulation and selectable calculation frequencies (15/30/60/120 FPS). [VTube Studio's plugin API documentation](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins) describes permissioned custom parameters that can drive expressive inputs. These are integration candidates for coordinated eye/mouth/head/twin-tail motion, not installed features. Validate plugin authorization, update cadence, game/OBS frame cost, and reduced-motion behavior. Star's personality can be nuanced and consistent while **clearly remaining an AI VTuber**.
