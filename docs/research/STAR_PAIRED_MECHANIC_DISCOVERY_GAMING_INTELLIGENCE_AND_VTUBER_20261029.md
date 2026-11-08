# STAR — Game-mechanic discovery, transferable intelligence, local inference, natural VTubing
**Research and implementation:** October 29, 2026. **Status:** experimental, offline-first, unmerged draft.

## 1. The actual bottleneck

STAR already has substantial infrastructure: GameplaySkillBank (independently signed practice and validation), ActivePracticePlanner and GameLearningLadder (practice selection), GamePredictionLab (calibration), GameTransferAuditor (unseen-game tests), StudioPlaytestHost, StudioPlaythroughGate, VirtualInput smoke tests, StreamBrainGovernor, streaming telemetry, conversational timing, audible captions, stream episode memory, avatar motion and OBS quality gates.

But it cannot yet reliably answer: **Did this maneuver actually help compared with an alternative in the same game situation?** One successful practice attempt, or a language model's explanation, is not evidence of a mechanic. The next useful intelligence step is controlled experimental feedback.

### Research evidence

- [Roblox OpenGameEval — October 1, 2026](https://arxiv.org/abs/2610.02563): 84 Roblox Studio tasks with executable scene and play-session checks. Inspection of the game before editing is associated with higher task success. Roblox published [benchmark tools](https://github.com/Roblox/open-game-eval). Implication: observe, then edit, then test.
- [CEGame-Bench — October 19, 2026](https://arxiv.org/abs/2610.26098): complete-game tasks across Defold, Godot, Roblox Studio, Unity and Unreal. Evaluated generated games reached their endings in only 16% of tested runs. That is a benchmark finding, NOT a STAR measurement. Implication: playability and returning to saved state matter beyond successful compilation.
- [GameWorld — April 8, 2026](https://arxiv.org/abs/2604.07429): 34 games and 170 outcome-verifiable tasks; latency, memory and action timing remain difficult for multimodal agents. Implication: need closed-loop perception/action/verification, not video-description memorization.
- [VISTA — October 26, 2026](https://arxiv.org/abs/2610.35051): a self-improving embodied agent harness with actively tested hypotheses and lineage of successful/failed revisions. Implication: Core Forge should retain hypotheses and rerun them on withheld fresh tasks instead of accepting reflection as proof of improvement.
- [NIST's McNemar test](https://itl.nist.gov/div898/software/dataplot/refman1/auxillar/mcnemar.htm): matched binary outcomes are measured through discordant-pair counts; requires pairs to be comparable and independent.

## 2. Implemented: PairedMechanicLab

**Files:** star/game_mechanic_experiments.py, tests/test_game_mechanic_experiments.py.

A trusted local host preregisters ONE game/version/objective/situation, baseline action, candidate action, fixed sample size of 12–64 pairs, and minimum effect. The host controls the game, not this module.

**Controlled comparison procedure:**

1. Owner-opt-in enables one offline session. New practice reservations are denied when live or when gaming/voice telemetry indicates inadequate headroom. No permission to press keys, run models or publish is issued.
2. Each pair obtains two unpredictable run IDs and randomly assigned action order, with a bounded expiration time. A trusted host must reset to a comparable starting state between attempts, independently observe outcomes and record the game version.
3. Each result must be an *exact* signed PRACTICE GameTrial already present in GameplaySkillBank, matching scope, order, action and run IDs, witness digest, and fresh time. Validation/holdout results are never read.
4. Missing, swapped, replayed, unsigned or expired pair evidence invalidates the entire experiment. Incomplete runs cannot be silently skipped because they were inconvenient.
5. Interim reports reveal only a collecting counter. Only at the FIXED preregistered sample size is the paired difference and two-sided exact McNemar probability reported. At least eight discordant pairs and a preregistered minimum practical effect are required for a directional finding.
6. A finding is **private advisory evidence**, NOT causal proof, mechanical certainty, permission to play, training of model weights, generalization to a new game or an on-air victory.

**Important statistical limits:** A p-value is not the probability that a candidate is correct. Repeatedly trying new hypotheses until one passes creates false positives; multiple tests need their own correction and a withheld confirmatory test. Randomized pair order cannot control carryover when the environment is not actually reset. Host signatures authenticate statements, not whether game observations were accurate. This is an in-memory one-session analytic component; durable host audit records and sealed preregistrations are still needed for rigorous public claims.

**Why this helps intelligence:** Instead of guessing that a dash beats walking across a gap, Star can *propose* a hypothesis for review and independently compare verified outcomes from matched practice starts. Unsupported hypotheses remain inconclusive. After unseen-level validation, supported maneuvers can become candidate reusable skills. The module does not yet generate its own hypotheses or perform real gameplay.

### Trusted-host integration sketch

Create a curated MechanicHypothesis for an obby gap, with actions walk and dash, target_pairs=24. Enable PairedMechanicLab with owner_approved=True. Reserve a pair under offline StreamTelemetry. The host uses the returned order and run IDs while separately using its existing private Studio permissions to reset the game, execute each bounded action and attest outcomes. Ingest both GameTrials into the existing bank, then submit_pair. Repeat until the fixed horizon, report once and evaluate candidate skills on unseen levels. Never expose evidence keys or create receipts from a model's conclusions.

## 3. Increasing speed without sacrificing gaming or streaming

**Fast model routing:** trusted game/voice/OBS host state should pick a small cached model for brief chat, selective fast vision for urgent HUD observations, a larger model for deeper game planning and code, and isolated workers for background research. Do not treat untrusted chat text as permission to run a tool. Optimize p95 event-to-audible-sample latency and verified task success, not tokens/s alone.

**Stable prompt prefix:** fix the order of approved persona, project references and system instructions; append current grounded observations later. Measure prompt cache hit rates and memory pressure. A huge context may reduce speed on an 8 GB GPU despite saving retrieval calls.

**Speculative decoding:** [llama.cpp SPEED-Bench](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md) compares throughput, latency and draft acceptance on the running server across draft/n-gram/MTP/EAGLE3 variants. Compare equal prompts and correctness, real GPU memory consumption, realistic streaming load and p95 latency. Speculative decoding is not automatically faster.

**Hardware-aware scheduling:** reserve gaming GPU headroom; benchmark CPU-only speech, retrieval and decoding work on the actual Windows machine. The CPU-heavy Linux server and a Windows RTX 4060 8 GB system have different bottlenecks. Prefer sensible CPU/RAM optimizations and protect live audio/OBS deadlines. Never overclock or disable thermal safety to chase theoretical throughput.

**Measured acceptance, not marketing claims:** record first-audible-sample p50/p95, speech pauses and interruptions, FPS p1/p50, OBS rendered/encoded/network frame losses, VRAM peak, RAM bandwidth, energy, cache hits, draft-token acceptance and *unseen task accuracy*. Run baseline and candidate in randomized order under comparable conditions. No deployment unless speech/stream QoS remains non-inferior and quality does not regress.

## 4. Teaching STAR to actually play games and build complete games

**Observe → hypothesize → experiment → verify → retain → transfer:**
- Observe local screenshots and game state on approved tests; freshness, field of view and confidence matter. Read actual HUD/object state, not vague model intuition.
- Learn action effects, timing, movement, enemy attack windows, cooldowns and camera/UI focus. Prefer small reversible probes.
- Match competing action hypotheses in a private Studio test; replay identical starting conditions, record outcomes and use PairedMechanicLab for statistical diagnostics.
- Save *only verified* scoped skills to the existing learning memory. A maneuver working in game v1 is not evidence for game v2 or another engine.
- Use withheld levels/version changes for genuine transfer testing, with the already existing GameTransferAuditor. Do not leak hidden outcomes back into practice.
- For game creation, evaluate build structure, materials, collisions, pathfinding, UI clarity, input delivery, actual objective completion, exit/rejoin and saved progress. Require real play and visual review; procedural geometry correctness is not aesthetic quality.

[Roblox StudioTestService](https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers) enables programmatic multi-client testing, disconnections and test arguments. [UserInputService VirtualInput](https://create.roblox.com/docs/reference/engine/classes/UserInputService) supports simulated inputs in running experiences. The outstanding milestone is connecting Star's existing test scripts to a genuine owner-authorized Windows private Studio observer which independently signs actual game state transitions. No Windows Studio playthrough was run for this PR.

## 5. A natural, expressive, truthful AI VTuber

**Natural attention and speech:** carry a critical/calm/idle game-attention state. Use one-clause reactions during dangerous moments; defer moderated questions briefly instead of talking over fights; sometimes choose silence. Handle interruptions and mid-turn pauses without robotic fixed gaps. [LiveKit's locally hosted CPU v1-mini audio turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/) is worth benchmarking for interruption accuracy and CPU load.

**Voice and expression:** compare Star's voice to the [Kyutai Pocket TTS](https://kyutai-labs.github.io/pocket-tts/) 100M-parameter CPU-oriented streaming model. Its reported ~200 ms first chunk on the project's setup is NOT measured STAR latency. Blind-test natural phrasing, breath placement, laughs, prosody, clipping, timing and identity consistency. Use only authorized voice source material. Do not imitate real people without permission.

**Avatar motion:** lip sync to audible PCM, not generated text; synchronize eyelids, eyebrows, head gaze, twin-tail secondary motion, costume sway and laughter. Support reduced motion and keep the rig within frame-time budgets. [VTube Studio API](https://github.com/DenchiSoft/VTubeStudio/blob/master/README.md) can receive tracking parameters and trigger events with plugin authorization.

**Persona:** create fun through actual interests, independent experiments, expressive cat/dog modes, occasional humor, curiosity about games and real memories of observed attempts. Preserve a consistent fictional AI character while clearly disclosing AI identity. Do not invent a human childhood, real human life events or subjective consciousness as fact. Viewer identities, chat and personal data require moderation and limited retention.

**Evaluation:** blinded recordings should be rated for conversational pacing, specificity to the screen, false victories, interruptions, repetition, expressive motion, lip sync and viewer comfort. A believable voice does not justify laggy Roblox FPS or an unstable stream.

## 6. General knowledge, creative skills and Core Forge

- Index licensed engine manuals, versioned API references, asset licenses, vetted code examples and owner-submitted learning material. Retain source, license, retrieval date and contradictions. Refresh perishable facts before presenting them as current.
- Build general knowledge through retrieval and verified practice rather than treating model-generated paragraphs as learned fact. Separate public-approved knowledge from private project memory, hidden validation answers and viewer speech.
- Let Star propose original games, storyboards, UI and animation hypotheses; test collision/layout, visual consistency, gameplay success and human taste independently. Reuse *patterns*, not copy proprietary art.
- In Star Core Forge, associate each proposed algorithm/prompt/skill change with its measured compute cost, test fixtures, baseline, previous failures, hidden holdout success and rollback. Best-of-N with execution verification often matters more than selecting the largest model.
- GitHub is a draft review/export mirror. Local Core Forge with snapshots and reviewable evidence must remain functional without GitHub; never auto-merge a claimed self-upgrade.
- High-risk publication, purchases, account changes and irreversible actions remain owner-reviewed. Safe offline experimentation can be autonomous within configured scopes.

## 7. Acceptance checklist and current limitations

**Implemented and offline-testable in this PR:** randomized pair ordering, fixed-horizon pre-registration, exact ledger matching of signed practice outcomes, tamper/replay/missing-pair invalidation, CPU/GPU/stream admission restrictions, exact paired statistical comparison, private inconclusive reports and no hidden holdout leakage.

**Not demonstrated:** model-weight improvement, actual game mastery, verified causal mechanic discovery, faster local inference, real OBS performance gains, superior natural voice or a high-quality VTuber broadcast. These require authorized Windows Studio/OBS trials and independent evaluators.

**Next milestones in priority order:**
1. Connect an actual private Windows Roblox Studio observer with resettable matched scenarios and independently signed outcomes. Verify correctness of the pair protocol and timestamps.
2. Preregister held-out levels/game versions and check whether supported maneuvers transfer; record failures and do not overfit to familiar maps.
3. Compare local inference/CPU speech settings during real Roblox + OBS + avatar streams using end-to-end latency and stream QoS; reject candidate regressions.
4. Conduct voice/Live2D/chat naturalness rehearsals with actual interrupt, laughter and gameplay-focus cases, keeping all private recordings off GitHub.
5. Add versioned knowledge provenance and one-click rollback to the Core Forge approval workflow.

**Visibility:** the GitHub repository named Star-AI-Private was reported publicly visible; the name does not secure its contents. Never commit secrets, chat identities, recordings, private memory or model weights.

This research is engineering guidance, not evidence that STAR became more intelligent or humanlike in this particular change.
