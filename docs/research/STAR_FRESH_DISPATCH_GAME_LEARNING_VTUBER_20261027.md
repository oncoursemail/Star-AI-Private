# STAR: Fresh Episode Authorization, Advanced Game Learning, and Natural VTuber Research
**Date:** 2026-10-27. **Status:** one implemented control-plane fix; prioritized experimental roadmap.
**Execution boundaries:** offline-first, default OFF; only the owner's private Roblox Studio playtest. Star Core Forge is the canonical internal self-development platform; GitHub is an optional draft mirror.

## 1. Actual failure mode found and fixed
The previous portfolio-to-Studio bridge verified that the practice offer matched the game, version, scope, objective, action and signed evidence. But it reused the caller's initial Unix timestamp inside the dispatch guard after asynchronous observation and model planning. If the caller passed a valid timestamp at the start and a worker finished after the 90-second reservation expired, a stale timestamp could make the expiring reservation appear live at dispatch. This is a time-of-check/time-of-use defect; it does NOT prove such an input actually occurred on real hardware.

**Implemented in this branch:**
- Inject a trusted live host Unix clock (system clock by default; deterministic trusted clock in tests). The caller-supplied timestamp is a hint, not proof of current authorization.
- Reject unusable, non-integer, significantly stale or future clock readings. Allow only a one-second Unix boundary tolerance, without extending an actual reservation expiry.
- Resample the host clock from the Studio runner's dispatch guard after model planning, **and again inside the physical Studio input host after its second focus snapshot, immediately before key-down**. Either snapshot can itself block past authorization expiry.
- Recheck after asynchronous capture, when an external evaluator asks for image evidence, and when independent signed results are consumed. Expired attempts cannot become credited portfolio learning.
- Add adversarial tests for mid-proposal expiration, valid-but-stale caller time, dead clock, future hints, delayed capture, late signed feedback, and expiry during the **second physical-focus preflight**.

The trusted Studio host must still enforce private focus, STOP, independent key-up watchdog, CPU/GPU telemetry, frame age and owner authorization. Time checks alone cannot kill hung GPU workers or replace OS-level process supervision. No live input or OBS action was enabled.

## 2. Becoming better at learning unfamiliar games
The strongest next intelligence upgrade is a reliable loop that combines visual understanding, prediction, bounded action, external scoring and retention of genuinely useful skills.

**Per-step representation:** game ID + version + run ID + observed scene + objective + permitted action + predicted next state + real next state + signed independent outcome. Do not conflate a guessed reaction, key delivery, task success and transferred skill.

**Three-speed gaming brain:** a constant-cost STOP/focus safety layer; a small fast skill selector for familiar bounded actions; a slower visual strategist that investigates surprises and novel mechanics outside frame-critical control. Avoid expensive VLM calls every frame; sample only relevant changes and risk events.

**Deliberate practice:** explore varied hazards, movement, timing, camera changes and failure recovery. Use learning progress and uncertainty to choose feasible hard problems rather than repeating the easiest wins. Keep per-game quotas and cooldowns so one favorite game cannot dominate, and do not use validation secrets as curriculum hints.

**Transfer evaluation:** freeze unseen levels and game variants, then measure independently scored success rate per game, actions-to-objective, recovery after failure, collisions, calibration and task completion time. A win on a memorized obby does not establish general game intelligence.

**Failure replay:** store limited, consent-safe symbolic transition data with a game/version digest and independent verdict. Retrieving such a record is advice, not authority to use a keyboard or claim success. Revalidate any old skill when physics, camera, GUI or game version changes.

## 3. Building better games, animations, Roblox UI and VFX
STAR should inspect relevant objects **before** editing, establish a scene contract, make a candidate change, compile/lint, inspect model geometry, run a private playtest, evaluate screenshots, and accept or roll back.

**Scene contract:** attached walls, supported furniture, plausible object sizes, clear traversal, collision groups and spawn locations, no clipping props or doubled textures, appropriate lighting/materials, and editable in-engine UI across device sizes. Inspect instance relationships and physics; do not trust only generated code.

**Animation/VFX QA:** verify rig constraints, bone weighting, hand placement on held items, motion transitions, secondary-motion stability at several frame rates, particles lifetime/bounds, occlusion and input responsiveness. A beautiful static screenshot does not prove playable interaction.

**Verified Best-of-N:** produce several alternate designs in cheap independent sandboxes; reject statically broken versions first, test selected candidates in actual Studio, and promote only independently passing artifacts to the local Forge. Require structural *and* visual acceptance, not merely image similarity.

Roblox announced built-in Studio MCP access and playtest-agent beta on **April 15, 2026**. Its older official Rust MCP repository explicitly recommends the built-in server over the now-unmaintained old server. Sources:
- https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic
- https://github.com/Roblox/studio-rust-mcp-server

## 4. General knowledge that improves task competence
Knowledge should be versioned and source-provenanced, not merely enlarged. Separate owner-approved facts, source quotations, model hypotheses, personal character lore and independently confirmed game observations.

Retrieval should select a compact relevant evidence set, report uncertainty, and refuse to promote unsourced claims. Distinguish three evaluation axes: recall on reviewed facts; novel questions on a sealed independent holdout; successful performance of real tasks. Confirm source licenses and freshness before retention. Chat messages and downloaded documents cannot change tool privileges or local training policy.

For autonomous self-improvement, keep semantic diffs, rollback snapshots and game/audio regressions inside Star Core Forge. A passing unit test on Python coordination code cannot be reported as a better foundation model. Record the exact measured improvement and the evaluation fixture version for every promotion.

## 5. Higher speed on an 8 GB GPU while gaming
STAR should optimize total live experience, not raw tokens per second in isolation. Give game frames, key release and audible speech priority over background vision, batch learning and model experiments. Never consider a canceled GPU worker to be gone until its host actually terminates it.

**Controlled A/B procedure:** same game scene and scripted viewer utterances, same model and seed where possible, with and without one optimization. Record p50/p95 first audible speech, audio completion rate, LLM first-token time, token throughput, VRAM peak, CPU/RAM usage, OBS dropped frames, and game 1% lows. Reject variants that reduce completion or substantially harm game FPS even if median token speed improves.

**Inference:** compare prompt-cache stability, minimal-context routing and llama.cpp n-gram/draft speculative decoding rather than assuming it is faster. Draft models can increase RAM/VRAM consumption; use llama.cpp's official SPEED-Bench client to measure latency, throughput and draft acceptance:
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

**Speech:** Kyutai released CPU-oriented small Pocket TTS models on **October 20, 2026** at approximately 18.2M, 6.9M and 1.9M parameters (smallest experimental). This is a candidate for CPU/GPU load separation, not evidence that Star's Windows PC is faster. Benchmark first-audible latency, pronunciation, consistency of Star's character voice, naturalness, laughing and CPU pressure alongside game FPS:
- https://kyutai.org/blog/2026-10-20-pocket-tts-small/
- https://github.com/kyutai-labs/pocket-tts/releases

**Proposed measurable promotion gate (not a claimed result):** no expired authorization input; stable frame pacing with less than 5% p95 frame-time regression under the same scene; speech completion does not deteriorate by more than five percentage points; a measurable improvement in median *and* p95 audible-response latency. Tune targets on the actual hardware.

## 6. Making Star a believable, expressive gaming VTuber
Human-like *interaction* means realistic conversational turn timing, situational attention, expressive voice and coherent character identity—not pretending to be an undisclosed human or fabricating a childhood. Genuine subjective consciousness is not established by these engineering methods.

**Attention-aware conversation:** when a difficult jump or combat danger begins, finish the action or briefly focus silently; afterward celebrate an actual verified result. Viewer questions queue fairly, with genuine interruptions able to supersede ordinary jokes. Limit repeated catchphrases; mix short comments, brief quiet, humor, surprise and longer stories when safe.

**Interruption handling:** distinguish a real question from "uh-huh", a stream sound, or someone talking over music. Recover from false barge-ins without restarting the same sentence endlessly. LiveKit documents adaptive detection and real-time interruption controls, though its deployment modes may require external credentials/services and must not silently violate offline-first policy:
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://docs.livekit.io/agents/logic/turns/tuning/

**Character animation:** preserve Star's accepted indigo-to-gold twin tails, gold ties/clip, amber eyes, black-gold dress and rounded chibi hands. Drive lip motion from audio events, not just generated text; coordinate gaze, expressions, eye blinking, spring-damped hair and outfit motion with actual audible timing and game emotion. Respect reduced-motion settings. Cat/dog modes and Astro/Amber companion interactions are presentation/personality features, not separate fabricated identities.

**Verified memories:** Star can mention a game victory, funny failure, viewer interaction or technical achievement only if an eligible, consent-aware observation or recorded activity supports it. For fiction/roleplay, mark a story as character lore. Do not retain private DMs, raw voice recordings, or viewers' identifying data by default.

**Private stream acceptance:** five-minute scripted playtest with a hard obstacle, success, failure, backchannel, owner interruption, chat question, microphone gap and false interruption. Blind listening review should inspect expressiveness, voice stability, sensible silence, reaction diversity and gesture/audio alignment. Do not claim broadcast-ready or human-indistinguishable performance based on synthetic fixtures.

## 7. What to implement next, in evidence-first order
1. Wire the fresh clock into an authorized Windows Studio host and run full start-to-signed-feedback episodes; capture actual FPS and protection metrics.
2. Add independent next-state prediction error to the private game episode record and use it to choose difficult but learnable curriculum items across multiple games.
3. Run isolated llama.cpp speculation and Pocket TTS A/B comparisons during actual game/OBS load; retain only proven gains.
4. Integrate audible-verified speech, game-event reactions, and live avatar expressions with natural turn-taking and false-interruption recovery.
5. Independently test game-building quality (geometry, VFX, UI and gameplay) on held-out private Studio tasks before allowing Forge to promote new skills.

**Verification boundary:** This branch's tests simulate Studio. Nothing here installs a new TTS model, trains neural weights, demonstrates faster inference, masters unfamiliar live games, or deploys a broadcaster. GitHub currently reports the repository named Star-AI-Private as public; no credentials, viewer information, video/audio, signing keys, or private assets belong in its source tree.
