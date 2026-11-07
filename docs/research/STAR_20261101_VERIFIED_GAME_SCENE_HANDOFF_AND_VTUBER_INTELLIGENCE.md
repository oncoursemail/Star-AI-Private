# STAR: verified game-scene handoffs and real-time VTuber intelligence
Research date: **2026-11-01** (America/Chicago).

Status: **new scene-provenance code and offline tests implemented**; models, hardware optimizations and training integrations below remain independently researched candidates, not installed or demonstrated.

## 1. Reproduced defect and actual change

STAR's signed gameplay ledger, memory, stream director, and voice manager developed along separate boundaries. StreamSignal had a host-owned game_scope, and the Stage already accepted a current_game_scope for journal recall, but the narration planner did not check that a queued success **belonged to the game currently visible**.

Before patch: queue an observed game-A success at t=100, call StarStage.prepare(now=100, current_game_scope="game_B"), and the previous code returns a game-A joy speech plan. This was reproduced against the previous branch, not merely inferred. During a game switch or delayed capture STAR could therefore celebrate an old game's achievement.

The patch makes a safer, more natural transition:
- **stream_episode.py:** precompute a bounded opaque episode.game_scope from the four verified identifiers (game, version, objective, situation), not raw chat or generated text.
- **stream_game_reactions.py:** propagate that signed episode scope with observed reaction signals.
- **stream_director.py:** add host-only bind_game_scope, reject late/wrong-game events, flush old game cues and issued intents on transitions, reset scene-specific repeat receipts while preserving chat fairness and owner interventions.
- **stream_stage.py:** prepare rejects a proposed game narration that disagrees with independently supplied current game scope; transition_game invalidates stale plans and idle rig tokens. Already queued/audible audio cannot transition until the trusted host physically stops/flushed it and attests the stop.
- **tests/test_stream_scene_handoff.py:** tests mixed viewer/game queues, late replay, wrong-scene speech, safe same-map re-entry, no-game mode, stale plan tokens, four-key scope separation, and physical audio stop requirements.

**Host integration contract:** The authorized host first starts a signed StreamEpisode and enabled StarStage, derives the new scene token from the episode.game_scope property (never viewer/LLM text), and calls stage.transition_game(game_scope=token, owner_approved=True). If real speaker audio is queued/audible, it must stop/drain the physical playback device and neutralize the rig before supplying audio_stopped_and_flushed=True. The next stage.prepare should receive current_game_scope=token. On game exit, transition to an empty scope. These methods do **not** themselves control games, audio, or OBS.

This is a code-level correctness improvement, **not** a measured increase in human voice quality or AI intelligence. An actual Windows game-scene adapter is still missing.

## 2. Multi-timescale intelligence: training a better game player

Pan et al., "The World Won't Wait: Evaluating and Teaching Agents Under a Live Clock" ([arXiv 2610.20665](https://arxiv.org/abs/2610.20665), **2026-10-14**) introduced RealtimeBench, 180 continuously running tasks in six game types. Their slow teacher reviewed failures *between* episodes and transferred instructions to a fast student, raising a reported score from 13.51 to 24.19/100 after two cycles. **This is a third-party result, not STAR's measured improvement.**

Recommended STAR partition:
1. **Reflex:** frame-to-frame host safety logic and tested input macros, with independent authorization and scene checks. Do not call LLMs on blocking emergency actions.
2. **Tactician:** a small local model chooses among verified symbolic moves using recent vision, objective, uncertainty, and a firm action deadline. Late decisions are dropped, not applied to a changed game state.
3. **Offline teacher:** deeper reasoning processes complete practice replays, constructs hypotheses, and tests them using paused or isolated sandbox game runs.
4. **Independent promotion:** unseen maps/seeds and held-out validation, paired baseline/candidate runs, completion rate, out-of-distribution performance, decision p95, rollback on regression, and strict separation of practice from validation. A model claiming "I improved" is not evidence.

Star Core Forge should record experiment lineage, game/version scope, safe prompts, pass/fail receipts, resource consumption, and reversible promotion. GitHub remains optional external publishing. A live stream must never allocate teacher jobs that consume the game's rendering reserve.

## 3. Faster inference on 8 GB VRAM: evidence rather than hype

Prior RTX 3060 Ti Windows inspections occasionally reported only a few hundred MiB free, but other moments had significantly more. A snapshot does not prove sustained capacity. On an 8 GB gaming/streaming GPU, inference weights, KV, CUDA work buffers, game textures, OBS, compositing, and the Live2D renderer compete for the same capacity.

**Experiments in increasing order of disruption:**
- Establish a stable, unchanged baseline on actual short chat, Luau code, game commentary, long tool use, and TTS prompts; log p50/p95 time-to-first-token, p95 first **audible** speaker chunk, end-to-end completion, VRAM high water, game present FPS, OBS render/output frame drops, and decision quality.
- Compare a compact 4B-class real-time model with a larger 8-9B model for tactical tasks. Do not assume a larger model fitting at idle will fit with a running game.
- Use prefix/prompt caching and project-scoped retrieval; isolate prompt caches across sessions and protect private records. Instrument actual hit rate and long-context quality before increasing limits.
- Benchmark speculative decoding with official [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md). Its official benchmark reports per-category latency, prefill/decode throughput and draft acceptance; additional draft weights can steal VRAM and lower FPS.
- Compare offloading and MoE-specific optimizations only under fixed memory/quality constraints. [S2-MoE](https://arxiv.org/abs/2608.15018), August 2026, has [open code](https://github.com/angerybob/S2-MoE); its authors report up to 5.3x and around 2x average on their evaluation grid. STAR must reproduce and may see zero benefit or regressions.
- Partition machines: Windows game/OBS/avatar on one host, CPU TTS, retrieval, teacher/model experiments on another if measured network latency and failure recovery are acceptable. Keep local emergency mute and game stop effective when network is unavailable.
- Profile first, then selectively use Rust for capture pipelines, telemetry, audio buffer scheduling, and IPC. Rust alone does not increase model mathematical intelligence or tensor throughput.

**Promotion condition:** a measurable wall-clock speed improvement without worse gaming frametimes, audible timing, hallucinations, or quality on unseen tasks. Reject unsupported universal "X tokens/second" claims across different GPUs and context lengths.

## 4. Humanlike VTuber experience rooted in actual events

A believable AI VTuber needs attentive listening, good timing, nuanced emotional variation, consistent preferences, reactions to *observed* successes/failures, believable voice prosody, persistent verified memories, and sometimes silence. The system should disclose its AI identity rather than invent human life experiences.

- Kyutai [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) released 18.2M, 6.9M, and experimental 1.9M English models in [v4.0.0 on 2026-10-20](https://github.com/kyutai-labs/pocket-tts/releases), followed by v4.0.1 on 2026-10-21. CPU streaming and its Rust runtime deserve a **local A/B audition**, with intelligibility, prosody, pronunciation, first-audible latency, CPU load, and speaker dropouts measured. Vendor "faster than real time" claims do not establish suitability on the user's PC.
- LiveKit [TurnDetector v1-mini](https://docs.livekit.io/agents/logic/turns/turn-detector/) is local CPU turn prediction for self-hosted agents. Combine with authenticated VAD/STT, robust barge-in, a real audio cancel/flush path, and bounded chat ingress. Compare interrupt speed and false-cut rates on real recordings, not just synthetic silences.
- [VTube Studio plugins](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins) can inject authorized Live2D parameters. Make eye focus come from real visual targets, lip amplitude from played PCM, natural gaze and head turns from contextual cues, and motion only from current audible StagePlan. Preserve reduced motion, manual cutoffs, and separate opt-ins.
- Focus on responsive commentary and natural silence during combat, not reaction spam or filler catchphrases. Keep a canonical verified event journal so Star can refer to prior genuine gameplay, and forbid unsupported memories, fabricated viewers, or made-up human anecdotes.
- Astro and Amber can be additional opt-in simulated VTuber characters with distinct voice, visual, and interruption timing; do not treat simulated companion dialog as witnessed facts.
- Use bounded moderation, privacy-safe transcript retention, a visible AI disclosure, licensed voices, a hardware mute, and a hard **never broadcast without owner authorization** rule.

## 5. More capable Roblox and other game creation

Roblox [StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers), [testing modes](https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/testing-modes.md), and the [developer announcement](https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854) support scripted multiplayer and VirtualInput; Roblox describes up to eight simulated clients per session.

STAR should formalize each request into a game design specification and scene graph, generate multiple candidate solutions, statically test Luau (luau-analyze, selene, StyLua), inspect placement/collisions, generate and compare actual screenshots, run bot playtests on unseen device/network profiles, and repair errors before promotion. Quality gates should catch missing walls/props, unattached objects, clipping, texture glitches, wrong scale/lighting, unreadable native UI, broken replication, spawn failures, and low FPS. Passing lint is insufficient: screenshots and physically simulated play matter.

## 6. General knowledge and continuous independent learning

Proposed versioned retrieval foundation covers general knowledge, Rust, Luau, game engines, UI, VFX, Blender, 3D physics, speech systems, security, online etiquette, and system operations. For each snippet store source URL, publication date, version, hash, license, trust class, topical scope, and expiry; keep viewer chat in a lower-trust channel. Measure retrieval precision, supported-answer rate, tool-execution pass rate, time to completed correct work, and catastrophic-regression rate. Self-generated hypotheses must be distinguished from external verified knowledge. No autonomous publishing or irreversible host action without the established safety authorization.

## 7. Verification and next technical milestone

The scene handoff change is an opt-in trust/control plane. Offline test and lint results must be recorded separately from Windows device tests; **it has not yet been integrated with real game capture, actual OBS, TTS, Live2D rendering, or model training**.

Next priority: controlled, **nonbroadcast Windows** rehearsal with authenticated live frame identity, monitored 8 GB GPU budget, actual gameplay action traces, local voice, physical speaker playback acknowledgements, avatar expressions, and OBS read-only performance counters. Compare same conditions before/after, and make "no wrong-game narration and no stale audio after transition" a release gate. Follow with offline teacher/student evaluation on new maps and local CPU-TTS A/B listening sessions. Gate eventual autonomous streaming on trustworthy evidence, not passing synthetic tests alone.
