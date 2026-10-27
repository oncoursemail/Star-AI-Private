# STAR — Balanced Game-Skill Transfer and Natural VTuber Reactions
Engineering research and implementation — October 27, 2026 UTC (October 26 US Central)

**Scope:** Offline-first intelligence evaluation, human-natural conversational pacing, and a hardware-constrained roadmap. This update does not train model weights, start Roblox, grant permissions, or broadcast a stream. GitHub remains an optional publishing mirror; Core Forge is the primary offline development architecture.

## 1. Why independent gameplay evidence needs game-level balance

The existing game_transfer_eval.py implements strong host-signed holdout evidence, a precommitted roster digest, matched baseline/candidate cases, independent validation signatures, an exact paired McNemar test, a coverage check, and a guard against severe per-game regression.

Two weaknesses persisted. First, a roster with 80 examples of one game and only three examples from each of four others can count as five games, although nearly every trial measures the same title. Second, 10 gains in one game and ties in 40 trials across four others can satisfy an aggregate +20 percentage-point gain and statistically significant paired test, without showing broad cross-title transfer.

**Implemented generalization gates:**

- Effective game count uses Simpson's coverage formula: N_effective = (sum n_i)^2 / sum(n_i^2). An equal five-game cohort has five effective games; a heavily skewed cohort approaches one. Require at least 70% of the nominal distinct game count.
- Broad improvement requires gains of at least ten percentage points on at least 60% of distinct games; the unweighted per-game average improvement must also be at least ten points.
- Preserve the preregistered minimum case count, paired significance, minimum aggregate improvement and maximum tolerated per-game regression.
- Add non-sensitive report fields for effective_game_count, macro_paired_success_gain and games_with_meaningful_gain. Incomplete runs do not reveal those measurements.
- Never automatically promote a strategy: only an independently reviewed owner pilot is eligible.

The 70% coverage and 60% breadth thresholds are policy heuristics, not mathematically established proof of transfer. The authorized host must seal the thresholds and case roster *before* recording validation outcomes. Signing only authenticates the claimed evidence origin; it cannot establish that the scorer was correct or that withheld tasks were unseen.

The added tests prove that single-game wins and disproportionately sampled games do not yield pilot eligibility; a balanced 3-of-5 game success does; missing results remain confidential.

**Research:** Voyager (May 25, 2023) demonstrates a curriculum and reusable skill library with self-verification in Minecraft, but its evidence cannot be assumed to transfer to all games. Roblox OpenGameEval (October 1, 2026) evaluates agents inside stateful Studio sessions with executable scene and simulated gameplay checks. Its 84 core tasks and object-exploration findings support independent engine-level evaluation rather than self-reported success.

- https://arxiv.org/abs/2305.16291
- https://arxiv.org/abs/2610.02563
- https://github.com/Roblox/open-game-eval

## 2. Natural streaming means choosing when NOT to speak

The existing StreamDirector already handles owner interruptions, game danger, verified gameplay, viewer questions, time-to-live queues, replay safety, and cool-downs. A missing feature was preventing repeated triumph reactions from sounding like scripted chatter during games with many similar events.

**Implemented: audible-only reaction pacing.** After a *confirmed audible* game_success utterance, the director remembers the canonicalized narration for a default of 18 seconds. Text is case-folded and whitespace-normalized, and only a SHA-256 digest is kept. Similar events offered afterward under a different event ID are suppressed; queued repetitions are pruned. A same-ID reoffer deliberately remains eligible so the existing session/event-serial replay tests retain their semantics. Different achievements, owner interrupts, game danger and viewer questions remain eligible. Failed or canceled audio does not create a suppression entry. Disabling a session clears the memory. No audio device or model is contacted by this module.

This is a deterministic pacing rule, not human consciousness, emotion, or a proof of natural voice quality. The embedding host must confirm actual playback before signaling spoken=True.

**Next conversational experiments:** 15-minute consenting offline broadcast rehearsals with real VAD plus audio end-of-turn detection, interruption recovery, adjustable speech-to-silence ratio, expressive but not constant laughter, synchronized eyebrow/eye/hair animation, and tracking of viewer questions left unanswered. Distinguish real user barge-ins from incidental sounds. Test local v1-mini turn detection versus available cloud options, noting self-hosted quotas and latency trade-offs.

- https://docs.livekit.io/reference/agents/turn-handling-options/
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://livekit.com/blog/turn-detection-and-interruption-handling

## 3. A reliable learning-to-play pipeline

**Observe:** With permission, collect game frames and machine-readable object state, geometry, goals, collision behavior, audio cues, failure modes, and reward signals. Attach time/scene/version metadata.

**Explore:** Use a bounded practice curriculum. Test alternative symbolic strategies using a separate authorized Studio runner. Sign actual host-observed outcomes, not textual agent claims. Record mistakes and repair candidates.

**Generalize:** Evaluate on withheld levels, objective combinations, random seeds, and separate games. Seal evaluation manifest and signing keys outside Star's model. Match candidate versus baseline on the same scene. Report grouped confidence and regressions; block leaks of held-out answers.

**Compose:** Store verified behaviors as skills with prerequisites, affordances, scope, and expiry. Retrieve a relevant skill rather than regenerating every action; reevaluate when game versions or mechanics change.

**Build games:** Use a plan-build-playtest-debug-review loop. Verify anchored walls, placement, UI clipping, missing props, textures, animation timing, reliable replication, physics, game goals, correct weapon grip, and responsiveness. Compare render screenshots and actions with independent quality checks. Never treat static Luau compilation as the final measure.

Roblox announced built-in Studio MCP and playtest automation on March 5, 2026 and a Playtest Agent beta on April 9, 2026. April 15 engineering guidance describes agentic plan-build-test. Before STAR integrates with these capabilities, verify actual tool schemas and permission boundaries on the authorized Windows Studio computer.

- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

## 4. General intelligence and independent memory

Connect KnowledgePracticeHost, KnowledgeRecallPlanner, the local source-backed bank, verified gameplay skill bank and Core Forge without merging their trust levels. Source citations, retractions and version-pinned facts should persist; independently signed validation results must never become training prompts. Retrieval practice assesses a fixed model's recall without proving any change in model weights.

The fastest dependable path is skill-and-tool adaptation: task decomposition, an appropriate model route, focused retrieval, execution tools, self-checks, replayable evidence, independent grading, and a trusted rollback mechanism. Harder automatically generated exercises help only when their answers are checked by a different evaluator. Maintain both positive and negative learning examples so mistakes are not silently forgotten.

STAR can have a persistent persona, expressive emotions, humor, relationships and fictional character lore while transparently being an AI. Keep private information and hidden game test content separate from public streamer memory.

## 5. 8GB-GPU performance plan (benchmarks, not installed optimizations)

Benchmark **whole-session** performance on the dedicated PC: game median FPS and 1% lows, GPU VRAM peak, CPU contention, local AI first-token latency, speech first-audible p50/p95, speech completion percentage, audio-to-avatar sync, and quality on unseen tasks.

Candidate controlled interventions:

1. Pin a cache-stable system prompt/persona and verified task references; compare warm versus cold key-value prefix cache hits.
2. Use low-latency fixed-function game handlers for time-critical controls and small local reasoning routes for simple conversations; defer long inference and video rendering to quiet periods.
3. Compare llama.cpp n-gram speculative decoding and a compatible draft model against no speculation. Compare token/s, acceptance rate, output consistency and game FPS. Quantized or heterogeneous configurations can underperform; use pinned builds and deterministic test prompts.
4. Kyutai's October 20, 2026 small Pocket TTS English models (18.2M, 6.9M and 1.9M parameters) deserve listening and CPU load tests. Publisher speed estimates are not measured Star results; optimize intelligibility, Star's voice identity and natural laughter, not raw model size.
5. Restrict background video generation, model experiments and memory indexing during public gameplay. If speech on CPU causes frame jitter, isolate cores or choose a different voice model and demonstrate noninferior performance.

- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- https://github.com/ggml-org/llama.cpp/issues/20039
- https://kyutai.org/blog/2026-10-20-pocket-tts-small/
- https://github.com/kyutai-labs/pocket-tts

## 6. Acceptance milestones and non-negotiable boundaries

**First:** Seal held-out game rosters in an independent timestamped audit log and run diverse paired baselines. Run aggregate and macro balance checks without showing validation data to Star. Use multiple objective types and versions.

**Second:** On Windows, integrate authorized game capture + trustworthy FPS telemetry + visual host + episode memory + speech playback acknowledgements + VTube Studio/OBS adapter. Perform dry runs with no external broadcast and no unapproved credentials.

**Third:** Compare old/new director against identical simulated event traces and consenting audio samples. Assess repeated-reaction count per 15 minutes, meaningful response fraction, p95 first audible output, silent-focus duration, false barge-in, and human-rated naturalness.

**Fourth:** Run offline inference speed/quality A/B with the 8GB VRAM ceiling. Promote an optimization only when held-out quality is noninferior, audible completion >=95%, game 1% low FPS noninferior and actual p95 first-audible response improves >=10%.

**Fifth:** Use Star Core Forge to run semantic diffs, offline CI, independent evidence checking, versioned rollbacks, and approvals for high-impact actions. Treat GitHub as an optional public-safe export, not Star's only brain.

**Security:** As checked on October 27, 2026 UTC, the repo named Star-AI-Private is publicly visible on GitHub. Do not store credentials, hidden evaluation seeds or receipts, recordings, private chat text, identity information or proprietary assets in the repo until permissions and visibility are corrected.

**Limits:** These patches improve evidence interpretation and deterministic speech event pacing. They do not demonstrate faster neural inference, autonomous mastery, a live VTuber broadcast, greater underlying model intelligence or literal humanity. Real Windows hardware benchmarks and independent evaluation are still required.
