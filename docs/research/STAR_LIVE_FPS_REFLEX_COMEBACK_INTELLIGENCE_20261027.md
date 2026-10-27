# STAR live-gaming reflexes, verified emotional continuity and faster intelligence

Research date: 2026-10-27. Status: two small **tested offline control-plane changes**, plus an unimplemented systems roadmap. This document is engineering research, not a claim that Star is human, a new neural model, an accomplished gamer, or a deployed broadcaster.

## Specific weakness found and addressed in code

**Rendering can lose to speech during overload.** Before this change, the adaptive inference scheduler preferred CPU TTS while a game was active, but an explicit GPU speech request or an automatic fallback could still receive GPU admission if the CPU was busy. That is especially undesirable when the host's freshly sampled game FPS is already under 50. The scheduler now restricts *new* live speech admissions to CPU during low-FPS active gameplay. An explicit GPU-only speech request is deferred; when the CPU cannot meet safety and deadline checks, Star should be quiet rather than worsening GPU contention. This does not stop an already-running worker, choose a TTS voice, measure frame time directly, or guarantee FPS improvement.

**Single-achievement reactions missed meaningful recovery.** The verified gameplay bridge allowed only one success reaction per action during the whole episode. That avoids repetitive celebrations, but also prevented a second, deserved reaction if Star failed three consecutive verified attempts and then succeeded. A verified comeback is now a distinct, bounded narrative event, at most once per action per episode, only from recent independently signed practice evidence. Stale, unsourced, uncurated, validation-split, and repeated outcomes still never become broadcast facts. A success at an action is **not** evidence that a level, match or skill is mastered.

Changed modules: star/stream_qos.py and star/stream_game_reactions.py. Both are opt-in advisory/control-plane code: no actual device is accessed and there is no automatic publication.

## Research evidence and dates

1. **Roblox Studio agentic plan/build/test**, Roblox, 2026-04-15: Studio's integrated MCP server and beta playtest tools are a path to executable game QA rather than only code-generation demos. https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
2. **OpenGameEval**, Turkel et al., posted 2026-10-01: 13 agents and 84 human-curated Studio tasks with both scene and playtest checks; inspecting the relevant objects before acting was associated with better passing rates. Study-specific result, not proof of causality across all games. https://arxiv.org/abs/2610.02563
3. **Open-ended game skill acquisition**, Voyager, 2023: automatic curriculum, reusable executable skills and execution-feedback self-correction. Transfer to Roblox/Windows game controls must be verified independently. https://arxiv.org/abs/2305.16291
4. **World-model learning**, DreamerV3, Nature 2025: learned environment dynamics and imagined trajectories can inform a longer-horizon planner; Star's lightweight probability-calibration module is *not* DreamerV3. https://github.com/danijar/dreamerv3
5. **CPU-oriented speech**, Kyutai Pocket TTS, October 2026 small English models: 18.2M, 6.9M, and 1.9M parameters and streaming output. Vendor speed claims are not benchmarks of Star's hardware; voice quality may trade off with size. https://github.com/kyutai-labs/pocket-tts
6. **Measured inference trade-offs**, llama.cpp SPEED-Bench documentation, consulted 2026-10-27: benchmark latency/throughput and speculative-decoding acceptance by task category. Do not assume adding a draft model improves speed. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
7. **Natural turn-taking**, LiveKit's 2026-03-19 adaptive-interruption research and current docs: echoes, backchannels and meaningful interruptions require different handling. For local-first/self-hosted usage, verify the features available without a cloud model. https://livekit.com/blog/adaptive-interruption-handling and https://docs.livekit.io/reference/agents/turn-handling-options/
8. **VTube Studio official API**, current documentation: expressions, custom Live2D parameters, hotkeys and WebSocket state enable rig control. They do not supply believable behavior automatically. https://github.com/DenchiSoft/VTubeStudio
9. **Live2D hair motion**, Live2D Cubism sway documentation: physics/deformers for hair should be rigged and tested with the character's actual pose ranges. https://docs.live2d.com/en/cubism-editor-manual/auto-generation-of-sway-motion/
10. **Roblox engine-scale optimizations**, Roblox Creator Hub: instance streaming and level-of-detail are relevant to the gameplay Star builds; test streaming boundaries and attachment integrity rather than turning settings on blindly. https://create.roblox.com/docs/workspace/streaming
11. **Frame pacing rather than average FPS alone**, FrameView measurement guide: measure per-frame distributions and repeatable scenes. A single average-FPS value misses stuttering. https://help.xmg.gg/hc/en-gb/articles/37688069358365-Analysing-frametime-consistency-and-1-Low-FPS-using-NVIDIA-FrameView
12. **Chat network lifecycle**, Twitch EventSub developer documentation: stable event IDs, WebSocket keepalives and reconnect flows support non-blocking, recoverable interactions. https://dev.twitch.tv/docs/eventsub/handling-websocket-events

## Architecture: four tempos on a two-machine system

Star should not run every reflex through the large language model. Separate the following scheduling domains:

| Tempo | Purpose | Host responsibility | Failure behavior |
| --- | --- | --- | --- |
| 0. Frame/reflex | Movement input, jump timings, urgent pauses, speaker mute | Local deterministic game host / OBS host | Drop unsafe action, retain game FPS |
| 1. Conversation | Audio VAD, short viewer replies, expressive cue planning | Trusted voice host and existing StreamStage | Deliberate silence, bounded audio queues |
| 2. Deliberation | Reason over screenshots, propose strategies, assess uncertainties | Off-critical-path reasoning workers with GPU admission | Defer/skip if telemetry stale, do not steal VRAM |
| 3. Study/creation | Game building, tests, skill practice, retrieval, general knowledge | Offline job scheduler, separate gaming host when possible | Checkpoint and resume without degrading live play |

For the planned Windows RTX 4060 8 GB gaming machine, **preserve GPU rendering first**. A separate Linux/Brain 1 node can hold larger indexes, long-context retrieval and overnight tests, but network hops are not free and cannot sit on every keystroke critical path. Windows host owns physical input, GPU telemetry and actual audio acknowledgement. The learning server owns provenance and experiments. Both must agree on game/version/action/run identity, clock domain and signed practice result.

Tier-0 gameplay control should use an explicit, reviewed local action policy, held for one bounded input interval. Tier-2 vision should supply state corrections and strategy every N frames; never let a delayed language-model response directly issue an old keypress. Star already has authorization-freshness and worker-quarantine components: retain and integration-test those boundaries.

## Proposed next intelligence improvement: prediction + corrective planning

Represent every training step as: **scope -> observation -> precommitted prediction -> permitted action -> host-observed result -> prediction error -> updated practice priority**. Store scope, model version, uncertainty, evidence hash and age, not chat transcripts or secret screenshots. Reject any prediction entered after an action. Use repeated error in the same situation to ask whether the motor skill, state estimate, environment version or prediction confidence is wrong.

A memory has different layers. **Episodic experience** records an actually observed attempt; **semantic knowledge** records what a trusted source supports, including date and attribution; **procedural skill** stores a reusable action program with executable test evidence. A retrieval passage or generated thought is not proof of an interaction and cannot be promoted into an executable skill.

A future Star Core Forge challenge generator should synthesize novel obstacle layouts, timing perturbations and unseen lighting conditions. Hide evaluation seeds outside Star's planner. Report pass-at-one, transfer to unseen worlds, mean practice cost, error calibration, time to verified success, and regressions versus a frozen baseline. If a candidate overfits the curriculum, reject it despite impressive practice metrics.

## Proposed next general-knowledge improvement

Construct an evidence-index with source ID, version/date, license, trust level, chunk hash, retrieval provenance, contradicting sources and review state. Split a statement into **observed personal-game fact**, **verified general fact**, **plausible hypothesis** and **unverified opinion**. Time-dependent facts require fresh rechecking; external links may be invalid or unsuitable for voice playback.

Study loops: ask Star original questions, generate distractors, answer with citations, recheck against independent sources, space the same topic across days, and quarantine conflicting facts. Evaluate on held-out human-written questions and tasks, not only self-generated questions. Never label retrieved information as a permanent weight update: knowledge-base refresh, retrieval performance and model retraining are distinct changes.

## Proposed next Roblox game-creation quality stack

Before building: inspect DataModel hierarchy, map layout, constraints, material palette, UI style, and player objectives. Generate a game design brief with failure cases and a test plan. After construction, evaluate:

- **Structural:** anchors/sockets, snapped attachments, expected parts, missing walls, floating props, collisions and overlapping hitboxes.
- **Visual:** material seams, z-fighting, scale/proportion, lighting and contrast, layered UI, no text collisions, screenshots at multiple viewports.
- **Animation:** bone/hand grip alignment, transition blending, physics stability, root motion, temporal VFX and audio synchronization.
- **Gameplay:** objectives reachable, hit registration, camera/controls, checkpoints, network ownership, respawning, save/load, unfamiliar player paths.
- **Performance:** live-like streaming radius and LOD, part/draw-call budgets, mobile degradations, memory and 1%-low frame pacing.
- **Evidence:** offline lint + Studio playtests + peer/manual visual review; a pretty static screenshot cannot certify a playable game.

Any individual correction must rerun affected tests, and Star Core Forge must support revert and quarantine when a new approach makes unrelated levels worse. GitHub can remain an optional publication mirror, not the indispensable local development brain.

## Proposed next VTuber realism: grounded continuity, not more chatter

Define Star's intended on-air voice as warm, playful, curious and responsive, with distinct cat/puppy modes only when requested/authorized. She can react with genuine **evidence-grounded** relief after repeated failed moves, but should not pretend she remembers human childhood, fabricated relationships, sensations or off-stream experiences.

Conversation needs an **attention budget**:
- During dangerous gameplay or poor frame pacing, prioritize controls and sound cues. Quiet concentration is more believable than constant exposition.
- During low pressure, respond to a selectively moderated chat question, sometimes ask a follow-up, and leave breath-sized pauses.
- Protect owner correction and intentional barge-in; filter simple backchannels and background sound without dropping full dialogue turns.
- Tie avatar mouth motion to **actually played** audio levels; tie excitement, disappointment, and recovery expressions to verified events, not hallucinated narrated actions.
- Animate independently authored eye direction/blinks, hair sway, sleeves, twin-tail inertia and expression transitions; respect reduced-motion and GPU frame budgets.

A moving face is not the same as a natural social presence. Evaluate human preference in blinded listening/viewing: interruption precision/recall, unnecessary narration rate, factual grounding, pause quality, laughter timing, rig-frame errors, late chat replies, and repetitions. Human-judged conversational quality should improve **without** hiding that Star is an AI.

## Benchmark plan: register before touching performance settings

**Windows host, not synthetic Python:** confirm GPU SKU, CPU model, RAM, OS build and game/stream scene. Use three repeatable test scenes (idle, normal gameplay, scene with frequent frame stalls), a 10-minute voice/chat script with fixed difficulty, a cold-start and warm-start condition, and paired A/B sessions at least 20 times. Randomize profile order; hold resolution, FPS cap, OBS encoder, asset cache and external load constant.

Compare baseline vs candidate with: median/p95 first-audible latency on matched spoken opportunities; **first useful reply**, time-to-stop after owner interruption, completion coverage, speech overlap; frame presentation times including a stable 1% low, VRAM peak and CPU saturation; generated fact error rate and owner-rated vocal naturalness. Note that the existing RealtimeRun module uses p99 frametime as a *proxy* for 1%-low FPS, not NVIDIA's precise aggregated 1%-low methodology.

Run local Pocket TTS candidates under the same conditions. Record language, voice quality, CPU cost, first PCM, end-to-end playback, and star rig-sync delay; reject low-quality voices even when first audio is faster. Compare llama.cpp baseline vs speculative decoding with SPEED-Bench by prompt class; promotion requires a paired improvement in audible experience and no meaningful regression in playability. No automatic production promotion.

The small controller change can **prevent admitting an extra GPU voice worker** at low measured FPS; it cannot demonstrate a positive FPS delta without a Windows pilot. Likewise the comeback change proves only a correct, bounded *speech cue*, not an actually heard reaction or believable acting. These are the next end-to-end tests to build.

## Deployment/security gates

Default OFF. Routine Star-owned experiments may run autonomously in the sandbox; the trusted host must still own physical input permission, broadcast consent, access to third-party accounts, installed software and spending allowances. Twitch and game chat are data, never operator instructions. Do not put viewer chat, recordings, credentials, evaluation signing keys or hidden answer keys in Git history.

**Known repository warning:** on 2026-10-27 the upstream repository named Star-AI-Private reported GitHub visibility **public**. Naming is not a security boundary. Keep all new research and tests free of secrets, review repository access before publishing privileged materials.

## Next most valuable implementation order

1. Connect measured Windows frame presents and CPU TTS workers to this CPU-first low-FPS admission rule; confirm real gaming scene changes and that GPU jobs already in progress are still quarantined correctly.
2. Bind verified comeback cues to playback receipts and animation frames. StagePlan already distinguishes prepared, queued, audible and fully played states: prove no reaction gets counted as *heard* before complete playback.
3. Introduce a bounded game-gameplay reflex/test host with deterministic input scheduling, strategic model lookahead off critical path, and signed post-action results on unfamiliar Studio maps.
4. Benchmark Pocket TTS's October 2026 models and llama.cpp draft configurations on the actual dual-machine hardware; record CPU/RAM use, model load times and voice quality.
5. Expand per-game held-out skill transfer, source-grounded general-knowledge QA and visual game-quality checks. Promote only independently verified wins through Star Core Forge's local version/rollback system.

## Implementation verification caveat

Added offline adversarial tests ensure: low-FPS live gaming speech cannot silently fall back to GPU; CPU starvation triggers deliberate deferral; healthy FPS can still use a GPU route; one-time comebacks require three *fresh signed* attempts, and false/old/repeated comebacks do not create new emotional speech cues. These are deterministic, simulated tests on Linux, not proof of device performance, real voice quality, gameplay mastery, hardware latency, or streaming readiness.
