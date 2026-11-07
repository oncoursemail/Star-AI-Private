# STAR: Quiet Attention, Gaming Intelligence, Fast Inference and Natural Streaming

Research date: 2026-10-27. Engineering scope: STAR local-first offline planning, with GitHub as a review/export channel. **Status:** this branch implements quiet nonverbal avatar attention only; the other sections are independently researched development proposals, NOT deployed features.

## 1. Shipped: attention and blinking during silence

STAR already has an audible-speech motion planner, turn arbitrator, signed game episodes, a proactive gameplay prediction lab and blind transfer evaluation. But the original avatar lacks a bounded animation path for the many moments when STAR concentrates on gameplay or listens without talking. A frozen avatar between words looks artificial; adding idle canned speech would be worse.

This branch adds a **pure, CPU-cheap and opt-in** QuietAttention component plus new StarStage.idle_motion and StarStage.current_idle APIs.

- Avatar can blink with deterministic, irregular timing, softly shift gaze toward verified game/listener state, and move head and hair in coordinated small motions while remaining silent.
- Cat and puppy modes have subtle nonverbal tail motion; regular mode has none. Reduced-motion disables all body, head, tail and gaze swaying while preserving blinking.
- Gameplay-critical events suppress idle flourishes; no facial expression implies joy, fear or agreement without evidence. All mouth-open values in quiet frames are **zero**.
- **200-ms dispatch lease:** host must revalidate the exact frame immediately before physical rig output. A newer idle frame, speech plan, mode change, interruption, disable, invalid host flag or clock reversal rejects stale output.
- Never process viewer text as rig authority. No external API, device control, audio, microphone, OBS, gameplay input, or private data enters the module.
- Unit tests cover cue bounds, monotonic clocks, replay behavior, reduced motion, avatar modes, invalid/replayed frames, and conflict with real audible TTS plans.

**Important boundary:** a real Windows renderer must still be integrated, so these offline rig suggestions are not a live broadcast feature yet. They cannot prove emotion, consciousness or actual visual tracking.

## 2. Natural humanlike streams are mostly timing and authentic feedback

A convincing gaming VTuber should alternate listening, concentrating, short chat replies, genuine reactions and purposeful silence. Humanlike should refer to the *quality of interactions*, not pretending STAR lived a human life. STAR should answer truthfully when asked if she is AI, and remember only things she actually observed or did.

LiveKit's current adaptive turn handling uses acoustic cues to distinguish a true barge-in from a brief acknowledgment. Its turn tuning exposes endpointing, interruption recovery and optional preemptive LLM calls. Integration principle: compute a candidate early when useful but do **not** speak until final transcript and current turn are confirmed. STAR's existing StreamPreemptiveHost and StarStage heard-audio acknowledgement logic are the intended host boundaries. Avoid registering TTS merely enqueued as audible success.

Sources:
- https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
- https://docs.livekit.io/agents/logic/turns/tuning/

Specific tests for later Windows experiments:
1. During a difficult jump, STAR looks toward the action, does not narrate every frame and does not speak over the player's key moment.
2. When a viewer speaks, the avatar listens nonverbally, and STAR starts speech only after actual end-of-turn confirmation.
3. A false interruption must not restart the sentence twice; an actual owner interrupt must revoke old audio and stale animation immediately.
4. An exciting comeback reaction must be derived from independently verified gameplay evidence, not viewer chat or an LLM guess.
5. A canceled speech plan may not accidentally animate lip movement; the quiet path has a separate short lease.
6. Reduced-motion and mute/stop operations must work even through OS focus loss and renderer reconnect.

## 3. Better gameplay and game creation require *engine-grounded* evaluation

Roblox **OpenGameEval** (published 2026-10-01) evaluates 13 models on 84 tasks inside stateful Roblox Studio with executable scene/play checks. Its inspect-before-edit correlation suggests STAR should systematically inspect relevant instances before changing them. Roblox's official built-in Studio MCP and Playtest Agent supply a real controlled test harness (March 5 / April 15, 2026 announcements). GameWorld (2026-04-08) provides 34 games and 170 independently state-verifiable tasks in runner, arcade, platformer, puzzle and simulation genres.

Sources:
- https://github.com/Roblox/open-game-eval
- https://arxiv.org/abs/2610.02563
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://about.roblox.com/en-au/newsroom/2026/04/roblox-studio-going-agentic
- https://arxiv.org/abs/2604.07429
- https://gameworld-project.github.io/

Recommended STAR gaming learning protocol:
- Observe the game's permitted state and control schema; first actions should be reversible and small.
- Pre-register a prediction before acting; compare it to a signed outcome; retain calibrated knowledge about conditions and action mechanics.
- Cluster verified errors by cause (reaction timing, locomotion physics, aiming, pathfinding, UI interaction, target identification).
- Invent controlled variations that are slightly harder, but do not retry the same exercise endlessly or overfit to static maps.
- Transfer tests must use independent untouched target levels, frozen practice baselines and a separate evaluator key. Never route holdout results to practice or livestream commentary.
- Report model and engine versions, action latencies, successful runs, sample sizes, confidence intervals and actual failures.
- Game creation acceptance must include collision/anchor checks, no floating or misplaced props, editable UI, correct animation rig transitions, PBR/UV integrity, plausible composition and a complete playable test to the end, not only screenshots or pretty scripts.
- A proposed world model should be tested against an explicit fixed-compute challenge rather than claiming humanlike intuition from model narration. AutoWorldModel-Bench (2026-07-20) is a methodological lead: https://arxiv.org/abs/2608.11216.

## 4. Faster intelligence means better *useful response per second*

STAR's planned RTX 4060 (8GB VRAM) must also render games, capture video, and drive her avatar. Fast decoding that tanks game FPS, degrades speech, or returns incorrect cached context is not a net improvement.

Suggested lanes:
- **Immediate:** game, video, microphone stop, owner STOP, physical controller. Preserve frame-time headroom.
- **Interactive:** short conversational LLM, verified low-latency turn handling and CPU TTS candidate.
- **Deliberative:** Luau coding, complex reasoning, video analysis, game planning, visual QA, creativity.
- **Background:** source-indexed knowledge, controlled self-play, internal Core Forge research, validation and reversible code experiments; yield to foreground demand.

Measure (paired and cold/warm): game frame-time p50/p95/p99 and 1% lows; audible first-phoneme and completion p50/p95; model TTFT and decode separately; GPU/VRAM peak and CPU use; cancellations, lost audio, factual accuracy, tool correctness and verified practice success. Vary real input content. Cache-stable system prefix improves efficiency but repeating one identical prompt is a misleading benchmark.

llama.cpp **SPEED-Bench** compares speculative draft acceptance, latency and throughput for representative request categories. A draft may increase RAM/VRAM and harm speed; accept only clear measured wins, not theoretical multipliers.
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**Voice candidate:** Kyutai Pocket TTS v4.0.0 released 2026-10-20 small English CPU models of 18.2M, 6.9M and experimental 1.9M parameters. These could preserve GPU headroom while gaming, but require blind Star-voice quality/expressiveness tests and same-machine benchmarks before any switch. Claims about vendor-reported speed should not be reported as Star-specific measurements.
- https://github.com/kyutai-labs/pocket-tts
- https://github.com/kyutai-labs/pocket-tts/releases

## 5. Rig polish beyond idle facial motion

Live2D Cubism supports author-configured physics groups and exported .physics3.json. A polished rig should map small head/eye targets to separately simulated twin-tail, ribbon and dress swing (correct attachment points, damping, zero clipping), rather than applying artificial sinusoids indiscriminately. VTube Studio has public plugin APIs for parameters and events. Check the Cubism licensing before distributing a runtime; its Core is proprietary.

- https://docs.live2d.com/en/cubism-sdk-manual/physics/
- https://docs.live2d.com/en/cubism-editor-manual/physical-operation-setting/
- https://github.com/DenchiSoft/VTubeStudio
- https://docs.live2d.com/en/cubism-sdk-manual/cubism-core/

Original Star model targets: coordinated amber-gold expressive eyes; indigo-black twin tails with warm golden tips; small ribbon/clip secondary motion; clean mitten-style hands; style-appropriate tiny exaggerations; optional cat/puppy transformations. All must use owner-approved original artwork. Motion stays opt-in and respects reduced-motion.

## 6. Self-directed general knowledge and creativity

Better knowledge is not a bigger unordered scrape. A high-quality STAR memory should retain concise provenance-backed facts with source URL, retrieval timestamp, domain, confidence, uncertainty and expiration. General-knowledge questions should route to a cheap retrieval fast path when unambiguous, deeper source comparison for contested or fresh questions, and independent recall quizzes for offline learning. Model-generated hypotheses should remain candidates until independently verified; no permission changes from web pages or chat.

STAR can autonomously propose interests, draw, practice games, create Blender art and Luau prototypes, and reflect on successes and mistakes. Internal Core Forge can keep local version history, semantic diffs and rollback; GitHub should be optional outward review/publishing. Do not grant the model access to self-edit trust anchors, tests, evaluation secrets, contact permissions or money controls. Practice variety matters: games, general science, user experience, animation, sound, engineering and communication.

## 7. How the new stage code should be wired (future Windows adapter)

The trusted renderer must:
1. Obtain owner enable and separate broadcast authorization, local rig mapping and muted-on-stop semantics.
2. Sample the host monotonic clock and vetted booleans game_active, gameplay_critical and viewer_speaking, not chat text or LLM self-report.
3. When stage has no active audible plan, request stage.idle_motion(...); call stage.current_idle(frame, now=clock()) just before hardware dispatch. Reject anything older than 200 ms.
4. When speech begins, abandon quiet token; use existing StagePlan audio playback and audible motion path. Do not set mouth based on generated text.
5. On interrupt/disconnect/disable or clock problems, discard queued rig frames and emit neutral reset; separately stop actual sound. Never let an old frame or thread overwrite a newer session.
6. Render at 15/30/60 FPS only as hardware allows, track frame timings, respect reduced-motion at runtime.

Acceptance requires a real Windows offline rehearsal using private test chat/audio and game inputs: 10 minutes silence/listening/game stress/replies/reconnect, zero stale lip frames, stable frame times, no private data exposure, and independently evaluated human ratings of naturalness. Test first on a rig that supports all the parameters. No stream should be started automatically.

## 8. Next experiments, in priority order

1. Integrate this attention planner with the real original Star VTube Studio/Live2D rig and inspect actual recorded frames under CPU/GPU stress.
2. A/B the new Pocket TTS CPU models with actual Star voice and measure first *audible* phoneme and 1% low game FPS on the Windows 4060.
3. Pairwise llama.cpp inference benchmarks covering gaming, knowledge, Luau, reasoning, long context, interruption and varied queries. Reject corrupted-cache responses.
4. Blind cross-game control transfer on signed, previously unplayed Roblox private Studio scenes, with withheld judge.
5. Game-builder regression suite with visual/geometry/property checks and an actual run-to-ending playthrough.
6. Consent-scoped persistent social memories and truthful long-term Star persona. Separate expressive artificial emotions from claims of literal subjective human emotion.

## Verification boundaries

**Linux synthetic sampling evidence (not an FPS claim):** 50,000 sequential quiet-frame samples took 0.5203 seconds, approximately 10.4 microseconds per sample, in a single process on the connected STAR Linux development host. No Windows or real rig latency was measured. The relevant offline suite passed 518 tests and 215 subtests; it is not the full repository suite.

This branch **does implement** silent motion planning, its stage arbitration and adversarial tests. It **does not** install a TTS engine, improve neural weights, demonstrate faster inference, connect to Windows games, render on VTube Studio, prove game skill transfer, or stream live. These remain measured milestones, not announcements of achieved performance.
