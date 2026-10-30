# STAR AI — Faster *and* trustworthy gaming-VTuber development
Date: 2026-10-30. Scope: concrete code quality gate plus source-checked integration research.

## Verified repository gap and implemented increment

The existing star/stream_realtime_benchmark.py measures first-audible latency, 1%-low game FPS and GPU peak for matched A/B configurations. A successful verdict is only eligible_for_manual_pilot, **not** proof of better intelligence, natural voice, OBS capture or production permission. In particular, the original paired timing schema contains no semantic response correctness, grounded gameplay claim, or independently captured A/V synchronization observation. A fast model could win this speed-only pilot while misunderstanding game events, inventing achievements, or never entering the stream recording.

This change adds:
- star/stream_realtime_quality_gate.py — an optional, pure-Python, READ-ONLY sidecar. Per matched pair it demands baseline/candidate QualityWitness records, predeclared response correctness, independent game-event grounding, an OBS-audible recording confirmation, and measured A/V offset.
- It calls the **existing** compare_realtime() and requires its existing speed/FPS/VRAM verdict. Missing/duplicated/relabelled records cannot produce a pilot recommendation. Candidate grounding must be 100%, observed capture must be 100%, paired correctness may not regress below baseline or the configured 95% floor, candidate A/V offset p95 must be <=100ms and max <=200ms by default. These are initial engineering acceptance budgets, **not** measured human perception thresholds.
- Returns only an aggregate recommendation eligible_for_manual_rehearsal; authorized_to_stream is always False. Human/evaluator flags and OBS records remain **operator-attested** and can be wrong. The trusted capture host must authenticate measurements and ensure common clock-domain calculations. No microphone, OBS, game controller, network, private chat, transcript, signing key, training process or live broadcast is accessed.
- tests/test_stream_realtime_quality_gate.py — 23 synthetic tests, including semantic regression, invented game claims, missing OBS sound, extreme A/V drift, incomplete pairs, duplicate witness identifiers, poor speed, privacy-minimal summaries and invalid values.

Local development ran 23 tests against a simplified, explicitly labelled local stub of the existing speed comparison dependency; they do NOT substitute for the GitHub CI suite that will exercise the actual compare_realtime() code. No real game, model or OBS recording was benchmarked. Preserve default-OFF deployment and owner-approved, local-only validation.

## Primary-source research and priorities

### 1. Measure *what a viewer actually receives*

LiveKit's session tracing distinguishes E2E audible response latency, end-of-turn, transcription, LLM TTFT and TTS TTFB. Their local v1-mini audio turn detector runs on CPU and can be evaluated against STAR's existing TurnTakingGate; it is not automatically installed by this change.

Sources (checked 2026-10-30):
- https://docs.livekit.io/reference/agents/session-traces/
- https://docs.livekit.io/agents/logic/turns/turn-detector/
- https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

Use **two independent witnesses** in a private, permissioned Windows rehearsal: the host's game-state and audio playback events, and an OBS recording independently checked for audible output and A/V alignment. Compare matching baseline/candidate seeds and tasks; have independent raters label correctness and unsupported claims blind to the variant. Capture event -> first visible text -> speakable chunk -> TTS byte -> device output -> OBS-audible and animation-to-audio p50/p95. Do not call a PortAudio callback proof that a viewer heard a statement.

### 2. Local inference performance on an 8-GB gaming GPU

Official llama.cpp SPEED-Bench can compare target-only and speculative-decoding servers, reporting category-specific latency, decode speed, and draft acceptance. Speculative decoding can slow some workloads; start with the same-hardware, warmed, paired cases rather than default enabling n-gram or a second draft model. Prevent loading several models into the gaming GPU if it hurts frame pacing.

Primary source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

For Star: keep game/motor control deterministic and local; queue vision/tactics by game-event novelty; route short speech to a measured CPU/low-memory option only if quality passes; move research and Forge experiments to idle or the separate machine. Watch p95 first-audible latency, missed replies, 1%-low FPS, VRAM, CPU load and speech correctness. Cache *verified* reuse-context by project/version; flush on policy, game version or document change. A 30%-faster answer that fabricates a win **fails** the quality gate.

### 3. Transferable game skill, not self-reported mastery

Build a private testbed from STAR's existing GamePredictionLab, GameMechanicProbeLab, ActivePracticePlanner, GameplaySkillBank, GameLearningLadder, and GameTransferEval. Precommit success probabilities, reserve bounded practice tasks, observe independently signed practice runs, score calibration, and finally verify transfer on unseen map seeds or game versions in a protected holdout. The underlying Studio/game input host remains a separate authority; no language model may self-certify the result. The new paired quality witness can grade commentary about each play using the same signed source of truth.

Sources:
- https://github.com/gameworld-project/GameWorld
- https://github.com/Roblox/open-game-eval
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService

### 4. Better Roblox games, UI, animation and scene integrity

OpenGameEval's programmable Studio evaluation model is a better objective than asking an AI to judge its own screenshots. Curate scene tasks with broken collision parts, overlapping props, missing materials, inaccessible platforms, incorrect rigs/grips, and mis-sized mobile HUD. Check scene tree **and** actually rendered frames and multiplayer playtests. Score complete playable tasks with independent rubrics, not merely code compilation. Transfer only verified lessons into Star Core Forge.

### 5. Charming, natural and AI-transparent streaming

STAR's existing StarStage, QuietAttention, StreamFocusInbox, StreamGameReactions, StreamContinuityVault and latency/QoS components are already a good foundation. Integrate rather than duplicate them. The event selection policy should prefer genuine game surprises, thoughtful pauses during difficult play, short consistent humor, laughter only when triggered by actual context, and memories of events she truly witnessed. Drive lip shapes from delivered phonemes/audio, eyes and eyebrows from grounded state, and physically bounded twin-tail inertia from motion. Maintain reduced-motion and forced-neutral controls. Have the model admit uncertainty and answer unfamiliar general-knowledge questions using date/version/source-backed retrieval.

Being a realistic AI entertainer does **not** require pretending Star is biologically human or fabricating off-stream stories. In particular, no humanlike persona may override independent kill/mute, owner approval for new tool authority, platform rules or source privacy.

## Acceptance protocol before claiming improvement

1. Confirm this branch passes complete Python tests, Ruff and Pyright baseline plus frontend CI; no type-error baseline weakening.
2. In a controlled, owner-approved Windows rehearsal collect >=20 genuinely paired same-game/version runs, each with independent response correctness and game-event grounding, OBS captured audio, measured A/V alignment, identical prompts/seeds and hardware comparison conditions. Collect **failures and cancellations**, not only successful responses.
3. Demand the preexisting speed gate AND this new quality gate to return eligible_for_manual_rehearsal. Review every missing witness and error; pilot is manual, never automatically deployed.
4. Compare separately on game commentary, general knowledge, Roblox code generation, avatar/laughter/expressions, and multi-turn conversation. Use blind human animation and voice-quality review where automated truth is inadequate.
5. For autonomous learning, show improving held-out game completion and prospective prediction calibration without opening holdouts during practice. For game building, demonstrate higher complete-game completion and scene-integrity rates.
6. Require live game FPS and first-audible p95 not to worsen. Keep local Star Core Forge as the primary offline development/testing/rollback platform; GitHub is optional outward publication.

**Status:** This is a targeted, reviewable code and test increment. It has not made model weights smarter, accelerated neural inference, played a game independently, or produced a human-quality live broadcast. No real viewer content, tokens or recordings were published. The repository named Star-AI-Private is publicly visible; ensure sensitive Star Core Forge work stays in a genuinely private store.
