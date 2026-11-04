# STAR — Stream-Equivalent Rehearsal Resource Parity and Intelligence Roadmap
**Research/engineering date:** 2026-11-04
**Scope:** local-first Star AI gaming VTuber, autonomous Roblox creator, general assistant, resource-aware inference.
**Implementation status:** Resource-protection corrections in `star/stream_qos.py` and model-free regression tests in `tests/test_stream_qos_private_rehearsal_parity.py`. Other recommendations below are *research and experiments*, not shipped features.

## 1. Root cause: the private stream rehearsal was not protected like a real stream

Earlier work separated `idle`, `game_only`, `stream_only`, and `game_stream` inference-latency calibration. A host could correctly train the `game_stream` latency profile in a private recording with `private_stream_rehearsal=True`, but most admissions continued to check only `StreamTelemetry.live`.

**Consequence:** the very rehearsal meant to measure simultaneous game, avatar, speech and OBS loads could admit research/training/render tasks, use the smaller non-stream GPU reserve, accept 2-second-old telemetry, allow >1Hz new vision jobs, and skip the sustained FPS recovery guard. Worse, a route measured under these artificially favorable conditions could subsequently be considered calibrated for actual live gaming.

**Correction shipped:** a private host-attested, stream-equivalent rehearsal now inherits live-like *capacity protections* without gaining broadcast authority. Low-FPS GPU speech is blocked until stable recovery; speech can prefer CPU; private vision sampling is capped at one per second; stale sensors and background jobs are held back; live-style GPU memory reserves apply. **Deliberate exception:** private rehearsal still admits a *bounded first unmeasured vision probe* to gather safe calibration samples. Real live broadcasts must reject uncalibrated non-speech inference.

All changes are in a small advisory scheduler; they do not launch OBS, activate a mic, control a game, or authenticate a sensor. A compromised or incorrectly labeled host cannot be made trustworthy through a Python boolean.

### Rehearsal acceptance criteria
- Compare one **actual Windows host** running game+OBS+avatar+voice against game-only and idle baselines; record each interval's end-to-end capture → preprocessing → inference → input/PCM acknowledgment, never just tokens/sec.
- Preserve game 1%-low FPS/frame time and OBS encoder/render loss rates, not just mean FPS.
- Fail safe on insufficient GPU headroom, dropped microphone frames, unacknowledged input releases, stale OBS counters, unavailable physical audio stop, and overlapping windows.
- Record the *actual model/quantization/context/slot count*, CUDA version, GPU, game build, scene profile and source clock. Otherwise the calibration is not portable.
- Never call a synthetic offline pytest fixture a measured gaming-speed improvement.

## 2. Faster intelligence on an 8 GB graphics card

**Three different cognitive budgets** should be independently scheduled:
1. **Reflex lane** (tight deadlines): controller-state reading, nearby hazards, immediate navigation/aim choices, speech interrupt and key-release. Use cheap perceptual classifiers and deterministic protections where possible. Never wait for web research or a large planning LLM in this lane.
2. **Tactical lane** (seconds): route choice, short-horizon state prediction, item/skill selection, dialogue timing, explanation of a failed attempt, and game-state-conditioned VLM sampling.
3. **Deep lane** (off-stream): long reasoning, documentation retrieval, Roblox code generation, best-of-N solutions, Luau checks, Blender pipelines, world-building, procedural test generation and skill-review research.

On 8 GB VRAM, first collect cold-start time-to-first-token, warm prompt prefill, decode tokens/sec, memory peak, game 1%-low FPS and OBS skipped frames *on the same machine*. Compare baseline llama.cpp with one candidate change at a time: KV-cache size/quantization, model size, prompt-prefix reuse, speculative n-gram vs draft-model decoding, or session multiplexing. The official SPEED-Bench client reports latency and speculative token acceptance, and explicitly separates raw decoding speed from client-observed end-to-end latency [1]. Larger context windows consume KV and can make GPU contention worse: retrieval of a few verified, project-scoped facts is often a better first step than retaining a giant unbounded chat history.

**Hardware scheduling policy:** game frame and OBS budgets have priority; speech should usually have an efficient CPU option; only allow extra GPU inference after measuring free VRAM, avoiding RAM/PCIe thrash. Off-stream research and model tests can use heavier models on another machine. Report both quality and speed before allowing an experiment to replace a proven setup.

## 3. STAR as a genuinely better-playing game agent

A game-learning system needs **observed state → bounded action → independently observed state/outcome → credit audit → updated curriculum**. Input acknowledgment is not proof the game acted, and observing progress after an action is not proof that action caused progress.

**Near-term build:** run a single private test game with host-accessible instrumentation for player state, hazard phase, score, checkpoints, collisions, control acknowledgement, true game-world time and resettable level seed. Start with straightforward navigation or platforming before competitive online multiplayer. Hold out unseen map layouts and seeds; freeze the strategy before comparison; evaluate each action's full latency while the game advances (not paused), objective completion, mistakes, action cost and recovery from surprises. STAR should explicitly label an uncertain result `unverified`.

**Curriculum:** ordered movement, jumping, aim/tracking, item use, survival, tactics, multiplayer cooperation, robust transfer, game-version changes. Separate practice data from independent validation and track regressions on previously mastered maps. Existing signed skill bank, practice curriculum, randomized studies, outcome feedback, latency lab and load-drift modules provide foundations; avoid creating a second conflicting ledger.

**Important research direction:** RT-SAFE (October 7, 2026) demonstrates why a seemingly successful agent can still behave badly in a world that moves during inference [2]. Although RT-SAFE is about simulated urban navigation, its lesson applies to platformers and action games: evaluate damage, collision and deadlines independently of nominal task completion.

## 4. STAR as a better Roblox game creator

Use Roblox's **built-in Studio MCP server**, not an abandoned old standalone server, for trusted project inspection, bounded edits, screenshots and playtest automation [3,4]. Build on the repository's existing Studio loop and undo, with a preview-only initial mode.

A high-quality game-building loop:
- **Observe:** identify relevant DataModel objects, existing scripts, constraints, style, collision and network roles before editing.
- **Plan:** define acceptance tests and visual references before generating code.
- **Generate:** create four to eight candidate Luau implementations when practical, but gate admission by CPU/GPU/time budget.
- **Validate:** run syntax/lint/type checks, isolated unit tests and a private Studio playtest, including simulated mobile/client behavior and multiplayer join/leave where supported by StudioTestService [5].
- **Inspect:** compare actual camera captures/GUI hierarchy/animation/physics/network logs with design requirements; never treat a compile-only result as a visually correct asset.
- **Repair:** apply localized diffs, re-run failed tests and preserve rollback history in Star's offline-first Core Forge.

OpenGameEval's public framework emphasizes evaluating exploration and reproducible stateful edits; its October 2026 paper suggests agents that inspect relevant project objects before editing tend to perform better [6].

## 5. A much more natural, engaging AI VTuber

**Naturalness is timing and memory, not nonstop talking.** Star should identify a gameplay moment's salience, track the current conversational turn, decide whether a reply is helpful, and sometimes remain silent while focused. Proact-VL (March 3, 2026; June revision) directly studies proactive videogame commentary and guidance [7].

Prioritize:
- **Grounded commentary:** only report real observed gameplay; distinguish a failed action, level checkpoint, observed scoreboard, and verified game win. Do not invent highlights.
- **Audio turn-taking:** use VAD as a robust fallback; evaluate backchannels vs actual interruptions; synchronize physical playback cessation with the visible avatar and captions. LiveKit's adaptive interruption model distinguishes backchannels from genuine interruptions, but the current service uses LiveKit Cloud credentials outside certain hosted deployments; Star needs a separately assessed local-first option [8].
- **Voice character:** choose clear diction, laughter, pitch/prosody variation, expressive but restrained hand/eye/mouth motion, natural pauses, and consistent favorite games. Never claim subjective sentience or a human identity.
- **CPU audio:** benchmark Kyutai's October 20–21 2026 Pocket TTS small English releases (18.2M, 6.9M, 1.9M parameter configurations) on Star's **actual** Windows CPU. Measure first audible chunk, intelligibility on game proper nouns and acronyms, interruption and audio-capture reliability. No claim that smaller automatically sounds more natural [9].
- **A genuine ongoing digital life:** an opt-in journal of verified gameplay milestones, art projects, habits, meaningful interactions and viewer-approved recurring jokes. Never store chat secrets or portray AI-generated fiction as real personal experience. Allow self-directed hobbies and projects during permitted idle windows.

**Human-likeness evaluation:** preregister paired owner-reviewed voice+avatar clips and score turn timing, audible interrupt latency, wrong claims, redundant commentary, stale reactions, viewer-question completion, facial/lip-sync coherence and natural silence. Use an independent rater plus real media traces. Do not claim 'human' or 'self-aware' from stylized speech.

## 6. Stream/control-plane reliability

OBS has an embedded WebSocket server in OBS Studio 28+; by default, it uses port 4455 and supports authentication [10]. Keep it on loopback with password protection, isolate read-only GetStats from stream/start/stop controls, and never expose broadcast control to the LLM itself.

A complete, **nonbroadcast** rehearsal should prove:
- signed gameplay events → authorized input → physically released keys → observed state changes;
- microphone capture → STT/turn-taking → model choice → streaming TTS → actual speaker acknowledgment → avatar animation;
- OBS GetStats deltas from non-overlapping intervals → throughput and dropped-frame measurements;
- host-driven emergency stop with independent watchdog and no streaming credentials used;
- downgrade or silence when device pressure makes a response late; no backlog of old jokes after a crisis.

## 7. Integration, monitoring and subsequent experiments

Today's implementation touches only **resource protections** in the existing `AdaptiveQoS` scheduler. Testing uses synthetic metrics; no real model, NVIDIA configuration, Windows input, OBS recording, speech, or Studio game was started.

**Priority next:** instrument a private 5-minute representative game+avatar+OBS+CPU TTS rehearsal, compare matched routes and identify the single largest p95 bottleneck. Once reliable, tune one inference parameter at a time. A more human-sounding Star should *never* come at the cost of emergency responsiveness, unauthorized broadcast, or unverified learning claims.

Useful thresholds to preregister rather than declare already achieved: 0 unverified real-world victories; 0 unacknowledged keys on stop; 0 private rehearsal samples used as equivalent to live without matching loads; speech first-audible p95 ≤1.5s; confirmed interruption playback stop p95 ≤350ms; 0 unverified game facts broadcast; stable GPU headroom while OBS is recording. Tune thresholds after real hardware traces.

## Primary references
1. llama.cpp official SPEED-Bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
2. RT-SAFE, October 7 2026: https://arxiv.org/abs/2610.09294
3. Roblox Studio built-in MCP announcement, March 5 2026: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
4. Roblox built-in MCP guide: https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md
5. Roblox StudioTestService: https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers
6. Roblox OpenGameEval: https://github.com/Roblox/open-game-eval
7. Proact-VL, March 3 2026: https://arxiv.org/abs/2603.03447
8. LiveKit adaptive interruption: https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/
9. Pocket TTS official releases, October 20–21 2026: https://github.com/kyutai-labs/pocket-tts/releases
10. OBS WebSocket official repository: https://github.com/obsproject/obs-websocket
