# Star AI — cross-skill intelligence, faster local inference, gameplay mastery and natural VTuber performance

Researched **2026-10-30**. This PR adds an offline quality acceptance component; it does **not** demonstrate an upgraded model, faster token generation, completed game, live audio or humanlike streamer. GitHub is outward publication; Star Core Forge remains the desired **local-first** experiment/version/rollback system.

## Concrete source-code finding and implemented improvement

PR #838's `assess_quality_gate` compares matched, witnessed base/candidate performance and correctness **within a single game/version scope**. It is intentionally per-scenario: this is necessary for fair A/B statistics. But comparing only one streaming scenario creates a blind spot: a compact fast path could pass an obby commentary benchmark while answering a live general-knowledge question incorrectly, misunderstanding a Roblox scene, or failing natural conversation.

`star/stream_workload_quality_matrix.py` now groups four **predeclared** live workloads: `gameplay_commentary`, `general_knowledge`, `roblox_creation`, `live_dialogue`. It invokes the existing full speed+quality gate **once per category**, demands all categories pass, forbids duplicate workload groups and reuse of paired identifiers across categories, and returns only aggregate/anonymous scores. It cannot start OBS, switch models, control games, expose chat, authenticate the independent host, or authorize deployment. Synthesized passing examples are regression tests, **not actual performance experiments**.

### Why no single aggregate tokens/second score is sufficient

- Coding, knowledge retrieval, live improvisation and fast gameplay have different latency and correctness failure modes.
- Model speculative decoding can improve some content and hurt others. llama.cpp SPEED-Bench reports latency, throughput and draft acceptance **by category**. Reference: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- A throughput win that regresses any one workload should not advance to a live stream. Cross-category acceptance prevents a large easy category from concealing a regression in a smaller hard category.

## Highest-impact architecture plan, with measurable criteria

### 1) Real-time inference that protects gameplay and audio

Three independently budgeted lanes:
1. **Fast:** OS/game-input host, renderer, audio output callbacks, watchdog and physical mute; never await a language model to decide keyboard release.
2. **Interactive:** short speech, changed-region vision, tactical planning and chat turn selection with strict p95 first-audible deadlines.
3. **Background:** research retrieval, source checking, creative experiments, local knowledge indexing, Star Core Forge self-play curriculum and rollback snapshots; suspend/checkpoint when FPS or audible delivery degrades.

Keep CPU/RAM paths useful even when the 8-GB GPU is busy. Benchmark *completed requests* and independently recorded OBS audio before adopting speculative decoding, quantization, draft heads, prompt-prefix KV cache, parallel slots or a Rust service. Rust can lower host scheduling/serialization overhead but cannot automatically accelerate CUDA model math. Record llama.cpp commit SHA, backend, build flags, context length, model/quant, CPU/RAM/GPU usage, cache state, game version and live FPS for every A/B case. No theoretical speedup becomes a claim without same-machine observations.

Primary: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md and https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

### 2) Autonomously learn to play unfamiliar games and build better ones

Start with a controlled browser-game/Roblox Studio testbed, approved local inputs and a genuine state-based scorer. Separate motor control (short deterministic actions), tactical vision (recognize transitions and hazards) and strategy (plans, experiments and skill-transfer). Connect already-present Star components rather than duplicating them: `GamePredictionLab`, `GameMechanicProbeLab`, `ActivePracticePlanner`, `GameplaySkillBank`, `GameLearningLadder`, `GameTransferEval`. Require signed outcomes, precommitted holdouts, explicit failed attempts, and improvements across **unseen levels/games**, not self-reported mastery.

GameWorld benchmarks agents on **34 browser games/170 verifiable tasks** with game-state checks. Source: https://gameworld-bench.github.io/

For Roblox building, evaluate object inspection *before* edits, then compile, structural scene checks, collisions, real in-engine visual screenshots, UI readability at different resolutions, object grip alignment, animations, camera paths, and simulated multiplayer join/leave. OpenGameEval evaluates **84 curated tasks** using executable Studio and play-session checks; exploration of relevant objects is associated with greater task success. Sources: https://github.com/Roblox/open-game-eval and https://create.roblox.com/docs/reference/engine/classes/StudioTestService

A game-generation success means a player can finish a novel playable level with no severity-one geometry, logic, visual or flow defects, not merely that Luau files were emitted.

### 3) Broader general knowledge without stale or fabricated memories

Use a provenance-aware, freshness-ranked source index for general knowledge, API/version documentation, game mechanics, and Star's own experiences. Store *observations, timestamps, game/version scope, evidence receipts, alternative explanations and failure cases*. Retrieval should distinguish public, approved facts from private conversations. Review high-change facts (software versions, events, prices, game patch mechanics) with fresh sources; keep a small per-domain retrieval packet so Star does not stall speech to read an entire database. Cache stable prompt prefixes, not secret personal data.

EMemBench asks verifiable questions based on an agent's interaction history; its evaluations demonstrate why storing long notes is not the same as usable episodic memory. Source: https://github.com/InternLM/EMemBench

Proposed progress metric: first-attempt success and calibration on withheld game tasks, source-grounded fact accuracy, false-game-achievement rate = 0, memory answer accuracy, citation freshness, and latency with a game rendering concurrently. Accept no improvement based only on number of indexed documents.

### 4) Natural, funny, appealing and AI-transparent VTuber behavior

Preserve Star's original black/gold character and coordinated indigo-to-gold twin tails. Build on `StarStage`, `QuietAttention`, `TurnTakingGate`, `VerifiedGameReactionHost`, `AudibleAvatarSession`, and verified continuity. Prioritize:
- **Natural silence:** focus on difficult gameplay and answer deferred moderated questions after the critical moment. Do not narrate every frame.
- **Genuine emotion cues:** small surprise, relief, curiosity, laughter and humor tied to actually observed events, with explicit uncertainty when game-state evidence is missing. No manufactured wins or fabricated off-stream experiences.
- **Coordinated performance:** drive lip movement from actually played samples/phonemes, gaze and eyebrows from confirmed attention/events, hair/tail secondary physics from head/body movement; cap amplitude and respect reduced-motion mode.
- **Responsive social timing:** distinguish barge-in, echo and background guest speech; make interruptions cancellable with physical audio flush and neutral-frame acknowledgement; avoid delayed talking over another speaker.
- **Persona:** consistent wit and warm casual phrasing, organic pacing and occasional self-directed hobbies grounded in verified history; be transparent that she is AI rather than presenting fictional recollections as lived human biography.

Measure game event -> first recognized state -> first speakable phrase -> output callback -> independently captured OBS audio -> rendered avatar motion. Run blind A/B human evaluations for pleasantness, voice prosody, variety, purposeful quiet, responsiveness and character consistency alongside event correctness. Acoustic and visual quality cannot be inferred from model self-ratings.

Relevant: https://docs.livekit.io/agents/logic/turns/turn-detector/ and https://docs.livekit.io/reference/agents/session-traces/

## Evidence collection and acceptance protocol

1. Predeclare the four scenario rosters **before** generating candidate answers, with at least **20 matched A/B pairs per workload**, plus real OBS audio and avatar recording, and immutable version/seed manifests.
2. Collect both successful and unsuccessful requests, independent response-correctness verdicts, corroborated game-event claims, genuine captured audio and measured A/V offset for every base/candidate pair. Do not reuse a case in two workloads.
3. Apply `assess_workload_quality_matrix` to ALL categories using the existing per-scenario quality gate. No missing/failed workload can be compensated by high throughput elsewhere. (Implementation API name is `assess_workload_matrix`.)
4. Evaluate held-out games and new Roblox builds separately, with proper game scoring and human reviewer visuals. Do not contaminate practice data with validation scores.
5. Independently confirm CPU/RAM/VRAM costs, model output accuracy, FPS and first-audible latency on the real Windows streaming PC. Report confidence intervals and failure counts. Compare exact same scene loads, microphones, audio tracks and settings.
6. Keep live settings unchanged until review; verify physical stop/mute, reboot recovery, encrypted backups, approval boundaries, and offline fallback.

## Privacy and limitations

`Star-AI-Private` is currently **publicly visible** even though it is named Private. Never upload keys, recordings, viewer content, screenshots from proprietary games, live device IDs or private user memories. The code's quality witnesses are host attestations, *not* independently cryptographically authenticated proof. This PR introduces an offline, advisory aggregate review layer only; it does not increase neural-model intelligence, change inference speed, enable gameplay input, go live, or update deployed software.
