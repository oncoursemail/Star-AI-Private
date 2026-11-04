# STAR research: learning effective game timing under live latency, better intelligence, and natural VTuber behavior

**Date:** November 3, 2026 (US Central)
**Scope:** Star AI / Star Intelligence, private owner-controlled development and game rehearsal.
**Implementation:** `star/game_latency_skill_lab.py` and `tests/test_game_latency_skill_lab.py` only. The implementation is a deterministic **synthetic** experiment; there is no real game, computer input, streaming, microphone, OBS, GPU or neural-model operation in this module.

## Executive decision: stop equating infrastructure correctness with game intelligence

The previous STAR pipeline can separately monitor authenticated game telemetry, validate input release, and observe signed game moments after an action. These are necessary foundations, but *a reliable safety gate is not a learning algorithm*. The next measurable leap must be an agent that can learn a better policy, then demonstrate the improvement on new scenarios while the game continues running during inference and input dispatch.

GameScaling's corrected November 1, 2026 real-time ViZDoom evaluation is a strong warning: elapsed time from screenshot capture through final action, not just decode time, changes measured performance. The corrected 9B and 27B scores are 11.5 and 8.5, respectively; the previous method omitted capture, image transfer, preprocessing, action handling and recording overhead when compensating the pause.

GameWorld (April 8, 2026) offers a useful larger benchmark: 34 browser games and 170 tasks, with outcome verification from game state rather than an LLM declaring success. Its real-time track explicitly does not pause during inference. The practical implication for STAR is to treat *real-time verified task outcomes* as the outcome variable, and tokens/sec as one explanatory metric only.

## Newly implemented: a toy game-learning closed loop

The new module provides a fully offline, reproducible timing mini-game. Each synthetic episode has a genuine hidden collision time, an aged/noisy visual estimate of time-to-collision, measured-like but simulated inference time, simulated OS dispatch time, and an objective success window. Inference and input acknowledgement consume world time. A decision that arrives after the collision is a miss, even if the action choice was otherwise correct.

1. Produce a **practice-only** seeded scenario set.
2. Compare a small, bounded set of timing corrections on that practice set, selecting the highest-scoring correction with deterministic tie breaking. No neural-model training occurs.
3. Freeze that correction and evaluate it against a naive uncalibrated policy on **distinct held-out seeds**, with both policies seeing identical held-out scenarios (matched pairs).
4. Evaluate the same fixed policies under additional synthetic inference/dispatch slowdown; never silently re-optimize using holdout results.
5. Report paired improvements, regressions and an exact one-sided sign-test value. This output **cannot authorize** gameplay, skill promotion or broadcasting.

**Demonstration only:** with practice seed 2026110301, holdout seed 2026110302, 96 training and 128 held-out synthetic episodes, the baseline scored 5.47%, the calibration -70 ms policy 88.28%, and the paired sign test found 106 improvements and zero regressions (p ~ 1.23e-32). The practice win rate was 87.5%. Under a different simulated workload (+40 ms inference and +35 ms dispatch), the calibrated policy degraded to 38.28% and the baseline to 0.0%.

The stress degradation is the most important lesson: training under one hardware load does NOT imply good performance while OBS, a game and TTS compete for resources. The simulation was deliberately constructed with compensable delay; these figures **are not empirical intelligence, real-game win rates, hardware latency, statistical proof about other games, or a new model benchmark**. A p-value from synthetic toy data proves nothing about deployment.

Run the self-contained demo: `python -m star.game_latency_skill_lab`. It emits no personal information and never launches a program or sends a key.

## Next real implementation: capture-to-action-to-outcome experiments

Build a locally owned game test adapter (prefer a simple private Roblox obby or local sandbox) whose independent engine-side recorder emits scene ID, frame count, collision/goal state, and signing receipt. Pin the exact game build. Keep game observation, control authority and reward measurement separate.

For each trial record: (1) capture time and frame ID, (2) transfer and preprocessing, (3) inference time, (4) input policy validation, (5) *physical* key acknowledgement and independent key release, (6) engine-recorded outcome, (7) OBS dropped frames, (8) audio first-sample and interrupt latency if streaming rehearsal is enabled. Use a shared monotonic host clock and trace IDs rather than comparing unrelated host clock epochs.

**Minimum study design:** preregister 100+ paired episodes per condition, randomized AB/BA order, matching initial state/seed, multiple distinct held-out levels, and no candidate changes after opening the holdout. Record timeout/missing telemetry separately from a loss. Compare p50/p95/p99 total closed-loop delay, valid actions per minute, successful objectives per real wall-clock minute, FPS, OBS dropped frames and input-release failures. Run with game alone, game+OBS local recording, and game+OBS+Star speech. Do not begin public broadcasting during these tests. Use known-good deterministic controls as a baseline, not only random or no-input policies.

**Promotion decision:** held-out game success must improve with no critical safety regression. Repeated practice successes and one positive post-action observation do not prove a causal policy improvement. Use controlled paired studies and multiple unseen game builds. A model must NOT write its own final oracle.

## Intelligence architecture: more reasoning without sacrificing reaction deadlines

Use a **fast reaction lane** that executes a small, allowed action policy with cached state and strict latency admission. It should often avoid a large LLM call. Use a **tactical lane** for route planning, mechanic hypotheses, inventory constraints and recovery, but allow it to suggest policies only, never bypass the input interlock. Use an **offline study lane** for multimodal frame/video understanding, teacher-model reasoning, strategy search, opponent simulation and 4–8 independently tested coding candidates.

On an 8 GB VRAM machine, the practical bottleneck may be shared GPU pressure from game rendering, avatar and OBS, not just model weights. Test *several* quantizations and context sizes with the actual game open; report VRAM headroom and first useful action, not theoretical maximum tokens/sec. Retain stable prompt prefixes and retrieval caches, but benchmark cache hit/miss and prompt recomputation. Try CPU voice synthesis only after measuring audible quality and onset. Stop offline teachers before they cause missed game actions or dropped OBS frames. Do not claim a universal fastest model from another person's GPU benchmark.

For persistent general knowledge, represent claims as source/version/time/confidence/evidence references and distinguish verified Luau APIs from generated code, own gameplay experiences from retrieved guides, and skill-transfer hypotheses from held-out successes. Support scheduled knowledge refresh outside live gameplay. Maintain an offline-first versioned skill library with explicit rollback, retention limits, consent and no silent promotion of unverified examples.

## Roblox game-building roadmap

Roblox's March 5, 2026 Studio announcement identifies the built-in MCP server as the recommended AI connection, with playtest automation and simulated input. Roblox's newer `StudioTestService` offers scripted multi-client tests (up to eight simulated clients) and join/leave/disconnect behavior. The April 9 Playtest Agent announcement described a beta, not a general guarantee of reliable autonomous QA.

For every independent game task: inspect the DataModel and relevant instances; retrieve version-matched creator docs; generate candidate Luau implementations in isolated project copies; run StyLua/Selene/Luau analysis and dedicated tests; run StudioTestService solo and multi-client scenarios; capture screenshots and video; compare against objective assertions for collision, UI, lighting, animation, networking and performance; preserve all failure logs and rollback pointers. Enforce that a game-building AI's self-written success criteria alone cannot certify the output. Do not operate on live public servers without separate permission.

## Natural, expressive Star VTuber: specific research and experiments

Microsoft's **RESPOND** (March 2026) frames natural dialogue as two controllable properties: backchannel intensity and propensity to claim the conversational floor. Rather than saying more, Star should learn when to acknowledge briefly, when to listen, when a viewer has finished and when gameplay urgency makes silence more appropriate. Set independent backchannel/turn-claim style knobs with bounds; owner interruption always takes priority.

**VoiceChat-TTS** (August 13, 2026) studies continuous speech synthesis that explicitly represents silence and accepts interruption without resetting KV cache. This supports testing a streaming text-to-audio pipeline rather than buffering entire sentences. But its public demonstrations and model sizes do not establish that it fits STAR's GPU/CPU budget. Measure first *audible* PCM, p95 time to mute after owner interruption, lip-sync to *heard* audio rather than planned text, spontaneous laughter/prosody, noise overlap, false interruption recovery and the cost to game FPS/OBS. Never place an experimental speech model above the physical emergency mute.

For a more human-feeling persona, ground on-air reactions in actual verified events and longer-lived interests; maintain a compact episodic memory of games, relationships and resolved tasks (with viewer consent and privacy boundaries). Build scene-specific emotional expression and gentle humor without repeating stock phrases. Keep stream status transparent: an AI-controlled VTuber character, not an undisclosed human. Emotional expressions can be convincing without pretending to experience human consciousness.

**Proposed blind evaluation:** 100 owner-consented private conversation/gameplay scenes covering 2-person co-commentary, repeated questions, jokes, silent stretches, interruptions, false VAD triggers, wins, failures, unseen puzzles and sudden resource pressure. Score conversational naturalness, factual grounding, semantic relevance, interruption latency, persona consistency and avatar/audio sync independently. The current synthetic mini-game does none of these.

## Actionable next milestones (not implemented in this iteration)

- Connect a private Windows game telemetry host to existing STAR signed game-event/actuation components; verify actual key release and post-action game outcome with process-level kill switch. Keep all controls opt-in.
- Replay matched control policies in a private locally recorded OBS rehearsal with physical audio and avatar rig; compare under stressed resources.
- Add a genuine offline learning interface (replay dataset + candidate policy + held-out simulator or game engine evaluator); do NOT call synthetic timing calibration a trained neural AI.
- Train or select reactive policies only after measurable transfer across several distinct game mechanics, including controls, timing, puzzle progression and recovery.
- Replace repetitive status reports with a user-facing experiment dashboard: build hash, tested scenario count, win rate, p95 latency, confidence interval, CPU/GPU load, active version and rollback target.

## Primary references and dates

1. GameScaling, corrected real-time ViZDoom evaluation, **November 1, 2026**: https://gamescaling.github.io/
2. GameWorld (arXiv **April 8, 2026**), 34 games / 170 tasks and verifiable outcomes: https://arxiv.org/abs/2604.07429 and https://gameworld-project.github.io/
3. Microsoft RESPOND, **March 2026** (adaptive backchannels and turn claims): https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/
4. VoiceChat-TTS, **August 13, 2026** (continuous interruption-aware speech): https://arxiv.org/abs/2608.13831
5. Roblox built-in Studio MCP, **March 5, 2026**: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
6. Roblox StudioTestService (current Creator Hub reference): https://create.roblox.com/docs/reference/engine/classes/StudioTestService
7. Roblox Playtest Agent beta, **April 9, 2026**: https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
8. Roblox new testing APIs, **2026** (StudioTestService, VirtualInput, device profiles): https://devforum.roblox.com/t/new-studio-testing-apis-and-assistant-improvements/4657854

**Status/limits:** New code and offline unit tests can demonstrate a synthetic policy adaptation. No gameplay capture, physical Windows input, streaming, model training, inference speedups, or new learned ability in a real game were demonstrated here. The current PR is deliberately a draft until device-level, independent CI and human review.
