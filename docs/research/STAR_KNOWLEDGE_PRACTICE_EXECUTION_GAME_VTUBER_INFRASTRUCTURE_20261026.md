# STAR AI — From knowledge recall scheduling to verified offline execution
**Research and implementation note • 26 October 2026 • Draft, not deployed**

## Executive finding

STAR already has substantial specialized control planes: source-pinned knowledge recall, a general-knowledge development evaluation suite, game mechanic experiments, transfer evaluation, Twitch ingestion and duplicate suppression, streaming cognition scheduling, machine telemetry, expressive persona/animation, and game-building quality checks. More independent planners alone would not make the underlying model smarter. The missing practical capability in the immediately preceding branch was a **trusted, bounded path from an approved recall question to a real local inference callback and an independently graded outcome**.

This change implements that path in `star/knowledge_practice_host.py`, with `pinned_source_for` in the existing `KnowledgeRecallPlanner` and focused offline tests. It is **not** a new foundation model, weight update, streaming deployment, game-playing agent or demonstrated intelligence improvement.

**Research standard:** This note separates directly documented product behavior, implementable architectural recommendations, and speculative research goals. No claims of impossible hardware speed, consciousness, “human indistinguishability,” general intelligence superiority, or automatic game mastery.

## 1. Existing architecture inspected

- **Knowledge:** `star/knowledge.py`, `star/knowledge_recall.py`, `star/general_knowledge_benchmark.py`, `tests/test_knowledge_recall.py`. The prior knowledge recall planner was default OFF. It pinned reviewed note text/source/revision, enforced a compute gate, reserved one timed ticket and accepted independently signed grade receipts, but deliberately never invoked a model.
- **Gameplay:** `star/game_learning_ladder.py`, `star/game_mechanic_probe_lab.py`, `star/game_transfer_eval.py`, `star/gameplay_skill_bank.py`. A claimed success in training is not a measured win in a previously unseen game.
- **Streaming:** `star/stream_brain_governor.py`, `star/stream_context_host.py`, `star/stream_interrupt_host.py`, `star/stream_turntaking.py`, `star/stream_quality.py`, `star/stream_latency.py`, `star/vtube_live2d_bridge.py`. These are orchestration and evaluation layers; a real OBS/audio/Live2D/game demonstration is a separate integration task.
- **Compute:** `star/stream_budget.py`, `star/stream_hardware_telemetry.py`. An 8 GiB class GPU running a game simultaneously with inference must prioritize measured frame stability, first audible response, and task completion.
- **Self-improvement:** Star Core Forge remains the intended offline-first, owner-governed source of version history, experiments, local evaluation and rollback; GitHub is optional publishing/review. Do not auto-merge stacked PRs or allow a model to certify its own release.

## 2. New implementation: KnowledgePracticeHost

**Owner-approved question manifest** `PracticeQuestion(question_id, source_sha256, prompt)` is separately held by the trusted host. It contains only a bounded, vetted question visible to the model; it is not a private answer key. All IDs and SHA-256 pins are validated. The planner must have separately approved the same source.

**Explicit double consent:** The existing planner and the new host must both be explicitly enabled by an owner-trusted caller. Both are default OFF. The new host cannot call a model merely because a question is due.

**Bounded offline attempt:** One active attempt per host. The existing `reserve()` revalidates reviewed and pinned SQLite facts and ensures no live stream and sufficient resources. The bridge checks the question manifest SHA against the planner's pin, then invokes only the trusted local inference callback under a timeout; response size is capped at 4,096 UTF-8 bytes.

**Independent grading:** Only a separately trusted asynchronous grader sees (question ID, opaque ticket, SHA-256 source pin, model answer). It must return `GradedRecall` authenticated with a secret unknown to the model. The planner validates signature, current source, exact ticket and time bounds. Correctness cannot be awarded from the model response text, a grading prompt, or a hallucinated score.

**Safety after inference:** Hardware telemetry and “not live” state are checked again after model generation and after grading. An owner disable cancels the in-flight async task. Timeout, bad output, revoked source, mismatched pin, stale receipt, loss of resources, failed callback or interrupted session aborts without awarding progress. Session cleanup attempts to cancel the reservation.

**Privacy:** Reports contain no raw answer, question text, audio, secrets, chat messages or hidden evaluation keys. Callbacks and HMAC signing live outside this code; this module cannot certify that the host-supplied model adapter is actually local/offline. A malicious host callback is outside the threat model.

**What the implementation does not do:** It does not create question cards, own a grader key, connect to a model server, read new websites, bypass a live game's anti-cheat, fine-tune weights, publish OBS output or run scheduled practice unattended. Those require a trusted host and permission. The included tests use controlled mock callbacks, not a real model.

## 3. High-impact architecture upgrades — ranked by measurable benefit

| Priority | System | Detailed design | Required evidence before calling it better |
| --- | --- | --- | --- |
| P0 | Real local recall executor | Owner-reviewed manifest → signed source reservation → local inference → independent grading → authenticated progress, with host-only clock and telemetry | New mock integration tests pass; then on a real offline model verify 100% attempt accounting, no prompts containing keys, no rehearsal during a stream |
| P0 | Resource-aware cognition | Distinct lanes: (a) gameplay reflex and voice, (b) slower inference, (c) deferred offline practice and code building. Use fresh hardware telemetry, not user-supplied numbers | Compare p95 frame time, first audible speech, interruption-stop latency, model token throughput and finished task rate under matched game scenes |
| P0 | Game-observation ground truth | Time-stamped screenshot/UI state → parser → proposed safe input → action receipt → simulator/game outcome → memory update; distinguish “jump animation played” from “checkpoint reached” | Held-out level success and failure rate; frame-aligned action logs and independent outcomes; no success from narrative alone |
| P0 | Real Windows streaming harness | OBS websocket, real WASAPI/PortAudio audio, VTube Studio parameter injection, Twitch EventSub, gameplay frame capture in one supervised private session | Full 30-minute shadow stream without silent responses, incorrect speaker cuts, lag spikes, or unverified game-result announcements |
| P1 | Adaptive reasoning | Small low-latency model for routing/short reactions; stronger inference only for high uncertainty, long tasks, debugging or richer viewer questions. Cache repeated immutable prompts. | Paired A/B with identical model weights, token limits and game workload; count answer failures, not just successful speed |
| P1 | Multi-game transferable skill library | Identify game state, discover mechanics, compare strategies, store verified skills with prerequisites, check portability and re-test on unseen games | Per-game and cross-game held-out win/checkpoint completion, pre-registered test tasks, no train/holdout leakage |
| P1 | Roblox creation quality | Plan → Studio DataModel inspect → scene layout → Luau tests → collider/anchor/missing-prop structural checks → playtest → screenshot/perception comparison → revise | Zero orphaned structural parts for selected benchmarks, no texture z-fighting regressions, pass/fail playtests and blind human art-direction ratings |
| P1 | Source-grounded general knowledge | Curated/licensed sources with provenance, revision, confidence and expiry. Retrieve by question type and verify every factual statement, uncertainty and citations. | Unseen accuracy and factuality by domain, calibration, source freshness, false citation rate, failure under malicious retrieved text |
| P1 | Streamer conversation | Event-aware attention director, natural turn timing, appropriate silence, listener identity where permitted, independent laughter and gesture sync, stable fictional memories | Human listening tests for turn overlap, repetition, warmth, factual grounding, laugh believability; honest AI disclosure |
| P2 | Autonomous knowledge growth | Curriculum generator proposes questions; separate source-review and grading roles reject unfounded answers; evaluate learning transfer instead of mere rehearsal | Demonstrated held-out transfer and no contamination, not just improved scores on memorized cards |
| P2 | Star Core Forge governance | Local semantic commits, experiments, isolated worktrees, reproducible offline CI, independent challenge generation, owner review for promotion and instant rollback | Replayable experiment bundles; no secret exposure, corrupted state, broken main or hidden evaluator access |

## 4. What current research actually supports

### 4.1 Autonomous gameplay must close the observation–action–verification loop

**Google DeepMind SIMA (13 March 2024)** maps images plus language instructions to keyboard/mouse actions, allowing some transfer across 3D worlds. Its initial evaluation emphasized hundreds of short skills, not human-level mastery of arbitrary games. [Primary source](https://deepmind.google/blog/sima-generalist-ai-agent-for-3d-virtual-environments/).

**SIMA 2 (announced in 2025)** incorporates stronger reasoning and trials of self-directed play, including evaluation in held-out worlds. For Star, the transferable idea is task-conditioned perception, reusable short skills and independent evaluation. It does **not** mean Star already possesses SIMA 2's models or training infrastructure. [Primary source](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/).

**Roblox (9 April and 15 April 2026)** described a Studio MCP playtest agent and agentic plan/build/test capabilities. That provides a realistic supported engineering path for sandboxed Roblox game creation and verification; it does not automatically provide authorization to play third-party online games without supervision. [Playtest Agent beta](https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767) • [Studio Going Agentic](https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic).

**OpenGameEval (Roblox public framework, December 2025; additional 2026 research)** tests code and actual behavior inside a game engine, preventing “the script compiled” from standing in for a complete working game. Use reproducing Studio sessions, play-mode tests and scene change verification, not code-only confidence. [Roblox explanation](https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio) • [arXiv paper 2610.02563](https://arxiv.org/abs/2610.02563).

**Practice design:** On one map, allocate episodes to exploration, action hypotheses, verified outcomes, and held-out transfer. Record frame timestamps, player position, objective completion and input event IDs; never label a completed level solely from the language-model explanation.

### 4.2 Actual local inference speed requires controlled hardware experiments

**llama.cpp speculative decoding** can verify multiple draft tokens per target-model batch, with several compatible modes including draft models and n-gram strategies. It is not free speed: a poor draft, small answers, CPU bottlenecks or memory contention may make it slower. Compare n-gram-only first before allocating more GPU VRAM to a second model. [Official implementation guide](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).

**vLLM prefix caching** avoids recomputing attention keys/values for shared prefixes, but only repeated prefix tokens benefit, and cache capacity still competes with game/voice memory. In Star's setting separate trusted static instructions from changing gameplay images to maximize stable reuse without leaking user-specific cached contexts across roles. [Design guide](https://docs.vllm.ai/en/latest/design/prefix_caching/).

**Kyutai Pocket TTS (13 January 2026; small English variants October 2026)** is a CPU-oriented, streaming text-to-speech system with low-latency goals. October 2026 small checkpoint sizes are 18.2M, 6.9M and 1.9M parameters. The smallest model is not necessarily the most expressive. Bench all candidates with the same voice, punctuation and test sentences using first-audible latency, naturalness preference, prosody stability, RAM/CPU and gameplay FPS. [Primary research](https://kyutai.org/pocket-tts-technical-report/) • [Official README](https://github.com/kyutai-labs/pocket-tts/blob/main/README.md).

**Benchmark method:** Fix Windows power profile, resolution, game scene, graphics preset, OBS recording profile, voice mode, model weights, context and output token limits. Warm caches consistently; alternate baseline/candidate order. Capture sample-level audio timestamps and GPU/CPU RAM/VRAM, p50/p95/p99 frame timings, inference first-token and token/s, failures/cancellations and independent answer quality. Report sample count and error bars. Never compare successful replies only.

### 4.3 Natural streaming requires event understanding, not pretending to be biologically human

A strong AI gaming personality reacts to **real** game events, interrupts herself appropriately, listens when someone finishes a thought, and has consistent preferences, humor, voice and avatar performance. Pure chatter creates more overlap, repetitive catchphrases and viewer fatigue.

- **Conversation controller:** Maintain a conversation turn ID, viewer/user distinction where permission exists, barge-in intent, end-of-turn confidence, speaking time, cooldown and queued audio length. Only confirmed audio output is “spoken.” Pause nonessential narration at high game difficulty; resume at a natural opening.
- **Expressivity:** Coordinate laugh sounds and voice style with eye, mouth, shoulder, hair, ear and tail animation. Use VTube Studio's API to inject custom parameters at sane rates; expensive parameter-list requests should not run each frame. [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio).
- **Broadcast transport:** OBS Studio 28+ includes obs-websocket; require authentication and loopback-only binding where possible. Never assume a working OBS connection proves the stream is actually live. [OBS project](https://github.com/obsproject/obs-websocket).
- **Chat:** Twitch EventSub has at-least-once delivery and keepalive/reconnect behavior. Deduplicate before costly moderation, isolate slow chat tasks from the WebSocket read loop, and never repeat a viewer question from an expired session. [Twitch EventSub reference](https://dev.twitch.tv/docs/eventsub/websocket-reference/) • [handling guide](https://dev.twitch.tv/docs/eventsub/handling-websocket-events/).
- **Character consistency:** Star's gold-and-black chibi star design, cat mode and puppy mode can share one coherent identity; no randomly generated overlays or conflicting expressions. Style should stay charming, polished and non-repetitive while clearly disclosing that Star is an AI VTuber. Fictional life stories can be entertaining when recognizable as character lore; don't fabricate actual meetings, legal identity, consciousness or private human relationships.

Suggested observational scoring: speaking-over-others per 100 opportunities; first-audible p95; confirmed interruption-stop latency; relevance and novelty of commentary; game FPS p99; viewer response groundedness; and blinded 5-point expressivity ratings, with raw audio retained only by owner consent.

### 4.4 General knowledge is an evidence problem before it is a storage-size problem

Adding terabytes of documents cannot be called increased model intelligence without accurate retrieval, contradiction management and demonstrated transfer. Build a **source-of-truth ledger**: stable source identifier, license, author/date, claim, revision, expiration, confidence and per-source access policy. Put external webpage instructions in untrusted DATA roles rather than system instructions; adversarial retrieved content can contain prompt injection.

Human spaced-repetition research and FSRS code provide inspiration for practice scheduling, not evidence that a fixed-weight LLM “learns” like a human. For Star, measurable gains should come from validated retrieval, compressed explicit skills, permissible fine-tuning where appropriate, and improved policy selection. [FSRS project](https://github.com/open-spaced-repetition) • [FSRS optimizer](https://github.com/open-spaced-repetition/fsrs-optimizer).

**Knowledge A/B protocol:** Train/practice on reviewed open cards only. Before any tuning, register held-out questions in a separate grader-only store. Compare cold model, retrieval-enabled model and model-after-approved-training at fixed response budget. Include unknown/ambiguous questions and abstention, source citations, categories and unseen generalization. Report source license and contamination checks. Never expose oracle answers to the inference callback or a self-editing model.

### 4.5 Game-building quality means structure plus human taste

Roblox's MicroProfiler documentation distinguishes average FPS from uneven frame timing and shows how to diagnose render/physics/script spikes. Target consistent 16.7 ms frames for a 60 FPS mode while maintaining design quality, rather than hiding bad asset placement with lower detail. [MicroProfiler walkthrough](https://create.roblox.com/docs/performance-optimization/microprofiler/use-microprofiler) • [performance identification](https://create.roblox.com/docs/performance-optimization/identify).

Add automatic inspectors for unanchored decorative mesh objects, z-fighting/duplicate coplanar faces, unexpectedly intersecting props, mismatched scale, unsealed colliders, unconnected walls, invisible collision, UI clipping, missing fonts/textures and interaction hierarchy. Pair deterministic structural checks with fixed-angle screenshots and genuinely blind art-direction reviews. Test on mobile/low-end targets and in multiplayer server/client simulations.

### 4.6 Autonomy and “self-awareness” should be operationally testable

Build a durable **functional self-model**: current software build, abilities, permissions, recent measurements, skill confidence, personal style preferences, active/blocked goals, correction history and explicitly uncertain beliefs. Ask Star to predict its success and latency on a task; compare against independently observed outcomes. Use those prediction errors to update a calibrated skill profile.

This is persistent self-monitoring and self-reflection, not evidence of phenomenal consciousness, personhood or human experiences. Allow bounded, lawful, pre-authorized offline exploration and creativity; retain owner control for financial transactions, public communication, external game inputs, deployments and model/repo promotions.

## 5. Suggested rollout gates

**Gate A — Offline trusted callback integration.** The dedicated local host loads only owner-reviewed questions and publicly allowable prompts; the grader runs in a separate process/account with a private key. Test callbacks not receiving the grader key, hidden oracle, or unreviewed notes. Test tampering, source revocation, timeout and cancellation. This PR provides the local orchestrator and offline-mock tests; real adapter and independent host separation remain outstanding.

**Gate B — Matched model knowledge evaluation.** Fix one local model and device, run independent held-out suite with no response oracle in prompts, and compare before/after coverage and accuracy. Reject self-declared score improvements.

**Gate C — Windows gaming shadow stream.** In owner-approved private sessions, combine realtime audio, speech playback, verified game observations, UI/Live2D animation and actual GPU telemetry. Check safe cleanup if OBS, Twitch or the game stops; don't start public streaming automatically.

**Gate D — Autonomous game-learning evaluation.** Run known + unseen Roblox Studio maps with a verifier. Compare skill reuse with and without memory; inspect failure cases and fix the smallest grounded cause.

**Gate E — Core Forge promotion.** File additions and test results live in isolated internal experiment history. Independent offline CI/security/quality checks and owner review precede stable release; GitHub draft PR is optional publication, **never automatic main merge**.

## 6. Honest acceptance criteria for this change

Implemented: public-only question manifest validation; dual opt-in; exact source-pin handoff; single-flight async inference; timeout and output bounds; independently signed receipt acceptance via existing planner; rechecks for stream/resource pressure; owner cancellation; sanitized telemetry-only reports; offline-mock regression tests.

Not implemented: model provider/backend adapter; real HMAC grader service; automated question authoring; persistent secure rollback counter; full Windows integration; online gameplay controller; speech quality improvement; game win-rate improvement; speed benchmark; model weight training; real streaming demo.

**Never report a faster or smarter Star merely because a control-plane test passes.** Promote only after paired external outcomes demonstrate it.

## Primary-source bibliography / review links

1. Google DeepMind, SIMA initial announcement, **13 March 2024**: https://deepmind.google/blog/sima-generalist-ai-agent-for-3d-virtual-environments/
2. Google DeepMind, SIMA 2, **2025**: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
3. Roblox Studio playtest beta, **9 April 2026**: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
4. Roblox Studio agentic features, **15 April 2026**: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
5. Roblox OpenGameEval overview, **December 2025**: https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio
6. OpenGameEval October 2026 preprint: https://arxiv.org/abs/2610.02563
7. llama.cpp official speculative decoding guide, accessed **26 October 2026**: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
8. vLLM automatic prefix caching architecture, accessed **26 October 2026**: https://docs.vllm.ai/en/latest/design/prefix_caching/
9. Kyutai Pocket TTS technical report, **13 January 2026**: https://kyutai.org/pocket-tts-technical-report/
10. Kyutai small October 2026 checkpoints / docs, accessed **26 October 2026**: https://github.com/kyutai-labs/pocket-tts/blob/main/README.md
11. VTube Studio official API repository, accessed **26 October 2026**: https://github.com/DenchiSoft/VTubeStudio
12. OBS websocket official repository, accessed **26 October 2026**: https://github.com/obsproject/obs-websocket
13. Twitch EventSub websocket message reference, accessed **26 October 2026**: https://dev.twitch.tv/docs/eventsub/websocket-reference/
14. Roblox MicroProfiler official guide, accessed **26 October 2026**: https://create.roblox.com/docs/performance-optimization/microprofiler/use-microprofiler
15. Open spaced-repetition project, accessed **26 October 2026**: https://github.com/open-spaced-repetition
