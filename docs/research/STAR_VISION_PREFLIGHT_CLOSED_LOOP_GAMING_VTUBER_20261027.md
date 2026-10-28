# STAR: cheaper live game vision, smarter game learning, natural VTuber — 2026-10-27

**Status:** Engineering research and one implemented host-side optimization. Not a completed gaming agent, real-time visual understanding, a trained model, or a deployed Windows VTuber.
**Baseline:** stacked on PR #721, with foveated focus, opt-in temporal stabilization, measured host telemetry, speech governor, episodic verified practice, and quiet avatar attention.

## 1. Implemented now: skip raw-frame fingerprinting when inference cannot run

Prior `StreamVisionHost.consider_pixels` calculated a full-frame fingerprint and each focus-region fingerprint *before* checking whether current host telemetry, frame freshness, or an already-running worker would permit another vision model request. With 1080p capture and several high-frequency regions, that repeatedly spends CPU time on frames which cannot possibly result in inference.

The new preflight is **inside the existing trusted, owner-enabled host** and short-circuits before pixel access on:
1. Missing/stale or incomplete trusted CPU/GPU/frame/audio telemetry.
2. Vision-worker quarantine, including an expired worker whose physical stop is not confirmed.
3. Existing in-flight vision jobs (single-flight preserved).
4. Headroom policy rejection: rendering FPS, speech backlog, or available VRAM.
5. Frame too old or from the future, with strict timestamp validation.

Successful preflight is *not permission to run inference.* Only the existing `ObservationGovernor.consider`, invoked after fingerprinting, can issue a lease. It rechecks device state, rate limits, novelty, authorization, clock monotonicity and worker constraints. No image is retained, no host process starts, and no budget or permission can be granted by a model or remote viewer.

Counters: `pixel_preflight_skipped` and `pixel_fingerprinted` expose only aggregate activity; there is no captured content or player identity.

**Reproduction**
```sh
PYTHONPATH=. python benchmarks/stream_pixel_preflight.py
PYTHONPATH=. pytest -q tests/test_stream_pixel_preflight.py \
  tests/test_stream_vision_host.py tests/test_stream_focus_stability.py
```
The synthetic benchmark compares actual `FrameCue.from_pixels` CPU work for a 1920x1080 BGRA buffer with four fixed HUD crops against early rejection when telemetry is missing. **Not equivalent workloads**: their difference is avoided wasted fingerprinting, not evidence that inference got faster. No OBS/Studio session was profiled.

### Conservative performance acceptance

- Compare paired 30-minute Windows game sessions with raw-capture preflight disabled/enabled under *the same* scene, microphone, avatar, GPU and game settings.
- Measure frame-present p50/p95/p99, process CPU usage, inference submissions, speech first-audible p95, and memory peak.
- Confirm visual-event recall on independently labeled cases before raising temporal stabilization. Missed one-frame damage/health events are a real risk: host-trusted critical cues should bypass denoising.
- Disable preflight optimization if it causes more misses or meaningful p99 regression; it should only reduce unnecessary CPU processing.

## 2. Bigger architecture: turn STAR into a *closed-loop* general gaming agent

The biggest capability jump is not a bigger prompt or another edge filter. It is **observation tied to verifiable action outcomes**.

**State estimator**
- Maintain a bounded task representation for current game, version, objective, visible map topology, hazard classes, controls, inventory, health, recent actions, uncertainty and last verified result.
- Separate directly inspected state from inferences. Vision fingerprint novelty never means death, victory, a damage tick, or an object identity.
- Attach capture age and host device identity; reject stale observations after scene changes.
- Use broad low-cost novelty observations first; zoom or VLM-call on unexpected changes, uncertain mechanics, and planned interactions.
- Use legal/authorized game-control routes only. Keep game-input action permissions distinct from screen-capture permissions.

**Skill hypotheses & world model**
- Each unknown mechanic gets multiple plausible hypotheses (e.g., air-control sensitivity, dash cooldown, platform timing), estimated confidence and safe experiments.
- Run controlled practice trials with small action-space variation and budget-aware exploration.
- Predict result *before* action; compare against actual state from engine/host rather than self-reported success.
- Record unsuccessful attempts too, never only cherry-picked successful attempts.
- Test mechanics on held-out unseen layouts, seeds, or games. Stop promoting a skill if the generalization result is inconclusive.

**Learning into knowledge**
- Bind solved problems to executable scripts, engine version, screenshots where allowed, measured outcomes, failure traces, and license/source provenance.
- Retrieve only relevant validated recipes per task; expired engine APIs trigger revalidation.
- Allow active recall drills and spaced repeat questions, with independent answer keys and historical accuracy scores.
- Treat human viewers as social partners, not hidden game-evaluation supervisors; viewers cannot turn chat into OS commands.

**Roblox Studio full build loop**
1. Inspect DataModel, relevant scripts, connections, placement constraints and APIs before changing anything.
2. Produce 4–8 independent candidates *only when cheap offline validation makes the additional work worthwhile*.
3. Lint/format/check Luau (luau-lsp/analyze, Selene, StyLua where available).
4. Build safely in isolated Studio Lab; use Rojo/Roblox built-in MCP to inspect, edit, playtest and simulate input.
5. Check spatial integrity, anchors, props, textures, wall joints, lighting, UI hierarchy, target-device performance.
6. Evaluate completed playthrough objectives and multiplayer fairness; repair; retest previously passing mechanics.
7. Promote the smallest passing semantic diff to Star Core Forge; keep rollback, audit, reproducibility.

Roblox announced **March 5, 2026** that Studio has a built-in MCP server, and Assistant supports playtest automation including simulated input. Roblox's **OpenGameEval** (October 2026) runs executable scene and simulated-play checks on 84 curated tasks across 13 models, and reports higher success with inspection of task-relevant objects before edits. A second point of comparison, GameWorld (**April 8, 2026**), offers 34 games and 170 outcome-verifiable tasks and examines action latency and long-horizon planning.

## 3. Higher useful intelligence per second: three independently budgeted brains

**Fast path (~frame/action scale):** small temporal/controller policy with a short deadline, no general-purpose long-form reasoning. A strict no-action decision is better than delayed input when observations are stale.

**Interaction path (~viewer/voice scale):** compact chat model with structured context, selective retrieval, turn detector and verified speech. When budget tight, do not initiate costly speculative tasks. Preserve game FPS.

**Deep path (offline/background):** exploration, debugging, game-building, self-generated challenges, larger models, knowledge curation, full evaluations, asset generation, Blender rendering. Never steal frame or audio headroom.

Route by *task type, uncertainty, timeout, measured utility and available hardware*. Cache approved documents, repeated low-level tool results and stable prompt prefixes. Benchmark under mixed real workloads; avoid one repetitive easy question. llama.cpp SPEED-Bench covers draft acceptance, throughput and per-category latency for speculative decoding. Speculative decoding can regress and should be enabled only following paired measurements and rollback.

For the 8 GB RTX 4060, do **not** assume all models and TTS can reside in VRAM with a game. Prefer CPU speech when benchmarked quality is acceptable, RAM/CPU offload for background jobs, smaller models for quick decisions, and real peak-VRAM accounting. Optimize overall user-perceived task completion, not only tokens/sec.

## 4. The natural, adorable, believable VTuber: an actual behavior system

Naturalness must be *measured across the whole interaction*, not just TTS samples:

**Conversation:** voice-activity detection + endpointing; automatic interruption recovery; preempt LLM only under a resource budget; do not speak preemptive, changeable text. LiveKit recommends adaptive interruptions when available and generally keeps preemptive TTS off initially because speculative audio can waste compute. Record real first-audible timestamps and interruption mistakes.

**Attention:** game focus suppresses distracting head swings and chatter. Different gaze/blink/breathing patterns for looking at chat, navigating, surviving danger, reading and listening. Do not constantly move, blink rhythmically or speak over players.

**Expressive voice:** build separate acoustic profiles for happy, surprised, concentration, laughing, frustrated, sleepy and whispered states; gate exaggerated emotions to plausible context. Kyutai Pocket TTS has October 2026 lightweight English CPU models (18.2M, 6.9M, 1.9M params) worth testing. These are *candidates*, not automatically the best Star voice. Compare MOS-style listener preference, first audible p95, laugh quality, word stability and CPU contention.

**Avatar:** Star's approved round chibi design (indigo twin tails fading to golden tips, star clip, black-gold dress) should remain consistent. Use physical or parameter-based hair lag, skirt sway, eye highlights, mouth shapes, head anticipation, and carefully timed microexpressions. Live2D's official docs describe tunable physics for swinging hair and clothes; correct authoring and visual inspection matter more than adding random motion.

**Personality:** allow her playful cat/puppy modes, spontaneous jokes and consistent tastes, while remembering only actual verified on-stream experience. An AI character can be socially believable without claiming fabricated human childhood, offline adventures, biological emotions, or personal relationships that did not occur.

**Real-time event loop:**
```
authorized game capture + presented-frame telemetry
          |                 |
    CPU preflight       QoS governor
          |                 |
    foveated vision -> contextual game state -> action/skill planner
          |                  |                   |
    trusted gameplay events ----> social director + verified episodic context
                                     |
                             conversational LLM
                                     |
                              streaming TTS/PCM
                                     |
                           phoneme/audio lip sync
                                     |
                           Live2D/VRM avatar + OBS
```
Every actor must use session generation / monotonic timestamps so a stale model response, old avatar frame or canceled audio cannot leak into the next scene. Routine actions can be autonomous inside the owner's persistent policy; broadcasting, purchasing, public posts, irreversible changes, private-data exposure and unsafe game input still follow bounded approvals.

## 5. Evaluation gates and deployment ordering

**P0 — immediate (this PR):** skip unnecessary fingerprints; prove CPU savings offline; preserve strict workers, clock, headroom, and authentication limits. No Windows camera, capture or inference touched.

**P1 — Windows (highest priority):** connect the *authorized* capture buffer, present times, GPU telemetry and OBS audio to existing host control planes. Run 20+ paired trials per scene, inspect 1%-low FPS, speech p95 and pixel skip rate. Do not claim broad FPS improvement without measurements.

**P2 — gameplay intelligence:** record real signed, independently evaluated practice trials in a local Studio playtest, then test on unseen layouts. Metrics: success rate with confidence intervals, task completion time, collision count, recovery, and skill transfer.

**P3 — creation quality:** small real games from prompts; quality gates for inspect→edit→playtest; gameplay completion and human-blind visual evaluation. Distinguish coding competence from animation/art/layout.

**P4 — VTuber:** real microphone, CPU/GPU TTS A/B, avatar blendshapes, interruptions and live game. Evaluate grounded reaction rate, chat interruptions, motion naturalness, silence and sound-avatar alignment. Do not train on viewer data or record private content without clear permission.

**P5 — autonomous improvement:** Star Core Forge should provide signed experiments, budgeted self-generated difficulty ladders, independent evaluations, semantic diffs, versioned private history, staged deployment and auto rollback. GitHub remains an optional owner-reviewed publication mirror; do not silently merge, publish secrets or grant universal system access.

### Evidence limits and security

No fresh game capture, Roblox playtest or live stream took place in this PR. Local synthetic benchmark results do not predict real gaming performance. The repository named `Star-AI-Private` was reported **public** by GitHub on October 27, 2026; do not publish tokens, recordings, signatures, private training data or unreleased assets there.

## Sources verified October 27, 2026

1. Roblox, *Assistant Updates: Studio Built-in MCP Server and Playtest Automation* (Mar 5, 2026): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
2. Roblox, *OpenGameEval* (October 2026 paper and repository): https://github.com/Roblox/open-game-eval ; https://arxiv.org/abs/2610.02563
3. Ouyang et al., *GameWorld* (Apr 8, 2026): https://arxiv.org/abs/2604.07429
4. LiveKit, *Turn-taking tuning* (retrieved Oct 27, 2026): https://docs.livekit.io/agents/logic/turns/tuning/
5. Kyutai, *Pocket TTS* (October 2026 lightweight CPU-model release): https://github.com/kyutai-labs/pocket-tts
6. llama.cpp, *SPEED-Bench*: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
7. Live2D, *About Physics*: https://docs.live2d.com/en/cubism-editor-manual/physics-operation/
