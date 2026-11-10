# STAR — Cross-Engine Game-Creation Intelligence and Evaluation Research

**Research date:** 2026-11-10  
**Implementation:** star/game_dev_eval.py  
**Status:** Draft, offline evidence adapter; no game engine, agent or live project is executed.

## Executive finding

STAR already has a substantial Roblox-specific creator and gameplay-validation stack: Studio inspection/playtest workflows, visual quality checks, Luau analysis, signed gameplay evidence, scenario-balanced real-time mastery, host input timing, and resource-aware streaming. The gap identified in this review is a reproducible way to evaluate STAR's broader game-creation ability across a second engine without confusing a partial smoke test with a full benchmark or allowing a pooled score to hide a category regression.

This update adds an evidence-only paired evaluator for GameDevBench-style runs. It does not vendor the benchmark dataset or launch Godot. A trusted local runner must execute tasks and sign the result receipts. The model never receives the signing key.

## Research findings

### 1. Game development is multimodal, not just code generation

**GameDevBench (ICML 2026)** contains 333 Godot game-development tasks derived from tutorials. Its four categories are 2D graphics/animation, 3D graphics/animation, UI, and gameplay logic. The benchmark reports that reference solutions average 4.7 files, 114 lines of code, and 3.2 file types. It reports lower performance on 2D graphics tasks than gameplay tasks, and visual/image/video feedback improved one evaluated GPT-5.4 setup from 41.1% to 52.0%. This is a benchmark-specific result, not an expected STAR gain.

Official repository: https://github.com/waynchi/gamedevbench

The benchmark requires Godot 4.4.1 for comparable official runs. STAR should pin the exact upstream task revision, engine build, validator, agent revision, tool configuration and visual-feedback mode before comparing candidates.

The upstream repository's current leaderboard snapshot (checked 2026-11-10) lists Claude Opus 5.5 xhigh at 70.6%, GPT-6.1 Sol xhigh at 70.0%, and GPT-6 Astra High at 68.8% (229/333) with Codex, runtime-video and strict confinement. These are agent-plus-harness configurations, not model-only measurements; effort level, tools and visual feedback must be held constant before drawing comparisons.

### 2. Roblox and Godot test different but complementary creator capabilities

**OpenGameEval (2026)** evaluates 84 Roblox Studio tasks across 13 models, including project inspection and executable scene checks. It is a better fit for STAR's existing Roblox workflow. The paper reports a best single-attempt pass rate of 51.7% and 39.4% for tasks solved on all five attempts; inspecting every relevant object before editing correlated with +13.4 percentage points on scene-only tasks and +9.8 points on script-only tasks. This supports an inspect-before-edit discipline, not an assumption that inspection alone guarantees success.

**GameDevBench** broadens the creator stack to Godot and emphasizes multimodal assets and multi-file edits. STAR should keep separate per-engine scores rather than blend unlike task suites into one universal score.

**GameWorld (2026)** provides 34 browser games and 170 tasks with state-verifiable success/progress. Its real-time variant distinguishes a paused reasoning track from a live-clock interaction track. This complements (but should not be merged with) game-development task completion.

Sources:
- https://arxiv.org/abs/2610.02563 (OpenGameEval)
- https://arxiv.org/abs/2604.07429 (GameWorld)
- https://github.com/waynchi/gamedevbench (GameDevBench)

### 3. Visual feedback should be controlled as an experimental variable

GameDevBench reports a substantial visual-feedback improvement in one model configuration. STAR should therefore compare none, screenshot, and video feedback as separate, pinned experiment conditions. Baseline and candidate must use the same mode; otherwise a measured gain may come from a changed tool/feedback pipeline rather than a better model or agent.

The new campaign binds feedback mode, engine version, validator digest, upstream suite revision, task-roster digest and both agent revision digests before any run begins.

### 4. Long-term memory needs temporal resolution, not ever-larger prompts

**APEX-MEM (ACL 2026)** uses an entity-centric property graph, append-only temporal storage and query-time conflict resolution. It reports 88.88% on LOCOMO and 86.2% on LongMemEval. STAR should preserve old project decisions and resolve the current one at retrieval time, while keeping compact source-linked context in the live loop.

Source: https://aclanthology.org/2026.acl-long.749/

### 5. Low-VRAM inference research: transfer the principle, not the headline

**FlashOffloading (November 5, 2026)** studies tiered KV-cache placement, hot-cache reuse and overlapping compute with data movement. Its reported results use an Ascend910C platform and GLM-5.2; they are not evidence of a speedup on STAR's RTX 4060 8 GB. The transferable research question is whether CPU/RAM cache tiers and smarter reuse can reduce VRAM pressure without increasing first-audible latency or game-frame jitter.

STAR should benchmark the actual llama.cpp/vLLM runtime, model quantization, context size, KV-cache type, prefix reuse, CPU/GPU placement and concurrency on the target Windows machine. Use matched baseline/candidate requests and report TTFT, inter-token latency, end-to-end p50/p95, tokens/sec, RAM, VRAM, game frame times, OBS drops and audio underruns separately.

Source: https://arxiv.org/abs/2611.07542

### 6. Natural VTuber interaction remains a separate capability lane

Full-Duplex-Bench v3 evaluates real human speech, disfluencies, chained tasks, tool accuracy, latency and turn-taking separately. MP-Bench evaluates multi-party turn-taking and comprehension; its results show that multi-party understanding remains a weak point for current voice agents. FDB-v3 uses 100 human-recorded requests across 79 scenarios and 12 speakers, with tool-call accuracy, Pass@1, latency and turn-taking as separate measures. MP-Bench's 12-agent study reports real-time systems at or below 22% on multi-party comprehension and near chance on turn-taking. STAR's existing PRs #1096, #1099, #1100, #1105, #1106 and #1107 already address active listening, turn-taking, delivery evaluation, semantic endpointing and addressee gating. This update deliberately does not duplicate those systems.

Sources:
- https://www.full-duplex.ai/benchmarks/fdb-v3
- https://www.full-duplex.ai/benchmarks/mp-bench

### 7. Roblox permissions must stay scoped

Roblox Studio MCP/Open Cloud permissions are per game and per person. Full access includes scopes that can spend Robux, affect players, or publish to live experiences. Studio enforces approved scopes, upload folders and network allowlists; the agent cannot grant itself broader access. STAR should use the least scope needed and private test experiences for DataStore work.

Official documentation: https://create.roblox.com/docs/studio/mcp-open-cloud

## Implementation: star/game_dev_eval.py

The new standard-library-only adapter adds:

- An immutable preregistered campaign with exact upstream suite commit, Godot version, validator digest, baseline/candidate agent digests, feedback mode and task roster.
- Four explicit GameDevBench task categories.
- Balanced baseline-first/candidate-first order precommitted per task to reduce order effects.
- HMAC-SHA256 receipts signed by a trusted local runner; the signing key must remain outside model/tool context.
- Exact task/arm, agent revision, validator, engine, feedback-mode and environment binding.
- One-shot task-arm receipts and replayed run-ID rejection within one evaluator process. The trusted host must persist campaign IDs in its durable ledger to prevent replay across restarts.
- Paired pass/fail/timeout outcomes; infrastructure errors contaminate the campaign rather than count as model failures.
- Per-category pass rates and regression checks so a pooled gain cannot hide a 2D, 3D, UI or gameplay regression.
- Exact one-sided paired sign-test p-value.
- Elapsed-time p50/p95 reported separately from quality; elapsed task time is not mislabeled as model inference speed.
- A full-suite shape flag for 333 tasks on Godot 4.4.1, plus a separate host-verified upstream manifest digest. The adapter only marks official_roster_verified=True when the trusted host's pinned manifest digest exactly matches the task roster; a matching task count alone is never enough.

The adapter is read-only with respect to games and projects. It does not launch processes, access files, call MCP, control inputs, upload assets, publish a game, or alter model routing.

## STAR capability roadmap

### Game creator
1. Retain Roblox Studio as the primary target and add Godot as a second engine through a separately versioned adapter.
2. Inspect project structure and scene graph before editing.
3. Use a task plan with explicit file ownership and dependencies.
4. Build in a disposable project copy.
5. Run static checks and engine-native validators.
6. Capture screenshots/video from the actual running scene.
7. Compare geometry, composition, readability, animation and effects independently.
8. Playtest gameplay tasks and verify state outcomes independently.
9. Run cumulative regression tasks after each multi-file change.
10. Save only reproducible, source-linked lessons; do not treat one successful run as a reusable skill.

### Gamer
- Keep reflex, tactical, strategic and practice policies separate.
- Use live-clock tests, scenario-balanced cohorts, precommitted holdouts and independent outcome witnesses.
- Transfer navigation, timing, camera, inventory and objective skills across unseen games; never infer mastery from a paused-only result.

### VTuber
- Preserve the fast foreground conversation loop and asynchronous research/game-building loop.
- Keep turn-taking, addressee recognition, voice delivery, avatar synchronization and audible output as separate metrics.
- Allow silence; do not optimize for constant speech or fabricated emotion.

### General intelligence
- Evaluate knowledge accuracy, temporal updates, source attribution, uncertainty and abstention separately.
- Maintain working, episodic, semantic, procedural and project memory with provenance and supersession history.
- Keep development tasks separate from sealed holdouts.

### Speed
- Use real mixed-workload A/B runs on the target PC.
- Keep prompt/prefix caching, speculative decoding, quantization, CPU/GPU offload and KV-cache tiering as separate experiments.
- Reject any candidate that improves tokens/sec but worsens first-audible p95, game frame times, OBS output or audio stability beyond the preregistered budget.

## Verification and acceptance

The new tests cover signature validation, task-roster binding, exact A/B agent revisions, balanced run order, duplicate/replayed receipts, missing-result accounting, environment mismatch, infrastructure contamination, category regressions, partial-vs-full suite labeling and separate latency reporting.

Not performed in this change:
- Downloading or redistributing GameDevBench's 333-task dataset.
- Installing or running Godot 4.4.1.
- Running the 333 benchmark tasks.
- Measuring a model or inference speedup.
- Running the actual Windows game + OBS + TTS + avatar rehearsal.
- Verifying that a supplied task roster matches the official upstream manifest; the host must perform that independent check and pass the verified manifest digest.

Before a model/agent candidate is considered for a private pilot, the trusted Windows runner must pin the upstream commit and task manifest, run both arms with balanced order, verify all 666 receipts, preserve all task artifacts, and inspect category-level regressions. Production main remains unchanged until independent CI, review and owner approval.
