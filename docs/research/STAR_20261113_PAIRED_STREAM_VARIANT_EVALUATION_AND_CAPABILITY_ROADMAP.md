# STAR 2026-11-13 — Paired Stream-Variant Evaluation and Unified Capability Roadmap

**Research date:** 2026-11-13  
**Implementation:** signed, paired baseline/candidate evaluator for STAR's mixed realtime workload  
**Parent:** PR #1165, 'feat/interactionbench-quality-gates-20261113-run11'  
**Status:** draft implementation; host collection and runtime integration remain future work

## Executive finding

STAR needs one repeatable way to answer a difficult question: did a new model, prompt, memory policy, voice engine, gameplay policy, or scheduler actually make her better without making the live stream worse?

A single tokens-per-second number cannot answer that. A model can generate more tokens while taking longer to produce the first audible response, reducing task accuracy, increasing VRAM use, or causing game-frame and audio regressions. Likewise, a natural-sounding voice can still misunderstand a correction, interrupt viewers, or lose context during a long conversation.

This change adds a paired, signed evaluation boundary. The same preregistered cases are run against a pinned baseline and candidate under the same host/game/harness environment. Only holdout pairs drive acceptance gates. The evaluator reports task-quality outcomes alongside first-content/first-audible latency, game frame time, audio/OBS loss, CPU/RAM/VRAM, throughput, and memory-token cost. It never promotes a candidate automatically.

The research conclusion is broader: STAR should be built as one resource-governed realtime intelligence runtime with specialized but coordinated voice, social, gamer, creator, knowledge, and memory capabilities—not as unrelated feature demos.

## What the repository currently says about shipping status

The public product README describes STAR v1.0.0 as a Windows 11 local-first chat app with Roblox development support, optional local/server models, opt-in tools, and basic voice calls. The README explicitly distinguishes shipping features from open pull requests and says that PRs, CI artifacts, and passing tests do not put a feature in the installer. The voice-call guide describes a cascaded VAD/turn detection/ASR/model/TTS pipeline and notes that a real microphone and loudspeaker test had not yet been completed in that guide.

Therefore, the new work below is a development capability and research plan. It does not imply that STAR is already an autonomous public VTuber, autonomous general game player, or complete-game factory in the v1.0 installer.

## New implementation: paired stream-variant evaluator

Files:

- 'star/stream_variant_eval.py'
- 'tests/test_stream_variant_eval.py'

### What it compares

Each preregistered case has an opaque ID, a domain ('voice', 'gaming', 'creator', 'knowledge', or 'mixed'), a split ('development' or 'holdout'), and explicit required outcome/metric dimensions. Scenario text and answer keys remain in the trusted host harness.

Each baseline/candidate trial records only:

- An independently scored task outcome.
- Optional turn-taking, groundedness, held-out skill, and game-completion outcomes.
- First content and first audible latency.
- Game frame-time p99.
- Audio-underrun and OBS output-skip rates.
- Peak CPU millicores, RAM MiB, and VRAM MiB.
- Token throughput and memory-token cost.
- Opaque environment/evidence SHA-256 digests and a timestamp.

The evaluator enforces:

1. A sealed preregistered case-roster digest that includes a SHA-256 digest of each private scenario specification.
2. HMAC-SHA256 receipts from an independent host-owned key.
3. One baseline and one candidate trial per case.
4. Exact revision binding for each variant.
5. Matching host/game/harness environment digests inside each pair.
6. Freshness limits and future-clock rejection.
7. Symmetric metric availability inside each pair.
8. Explicit required dimensions for voice, gaming, creator, and knowledge cases; only preregistered dimensions and metrics contribute to their respective summaries.
9. Holdout-only acceptance gates; development cases cannot satisfy holdout minimums.
10. Minimum pair/domain/metric coverage and explicit speed/throughput improvement goals.
11. Non-inferiority gates for task quality, turn-taking, groundedness, held-out skills, game completion, frame time, audio/OBS loss, CPU/RAM/VRAM, and memory-token cost.
12. An explicit 'never_automatic' promotion result.

Errors and incomplete pairs are excluded from success/failure denominators and reduce evidence coverage. Missing data is never silently treated as zero. The evaluator rejects transcript, audio, screenshot, viewer identity, prompt, scenario, and answer-key fields because its dataclasses accept only the documented content-free schema.

### Important trust boundary

HMAC authenticates a receipt to whoever holds the host validation key. It does not prove that the observer or scorer was honest. Keep the key, case contents, answer keys, and scoring code outside the model process. Never expose 'sign_stream_trial' or the validation key as an LLM tool. A host should independently validate the observer and scorer, randomize or counterbalance variant order, pin model/runtime versions, and record cold-cache versus warm-cache conditions.

### Why paired holdout evaluation matters

A baseline and candidate must see the same cases. This reduces variance caused by different prompts, games, viewer scenarios, or task difficulty. Development cases can guide iteration, but only sealed holdout cases should drive a promotion decision. The evaluator uses exact paired McNemar/sign-test evidence for binary outcomes and paired metric summaries for latency/resource comparisons. The p-value is reported as evidence, not treated as a universal quality score.

## Research findings and engineering implications

### 1. Full-duplex voice and human-like streaming

**MP-Bench** evaluates voice agents as active participants in multiparty conversation. Its benchmark page reports that the twelve evaluated agents remained at or below 22% on multiparty comprehension and near chance on real-time multiparty turn-taking. This is a strong warning against designing STAR as a simple “latest chat message in, answer out” bot.

Source: [MP-Bench](https://www.fullduplex.ai/benchmarks/mp-bench).

**Full-Duplex-Bench v3** uses 100 human-recorded requests across 79 scenarios and twelve speakers, including self-corrections and chained tool calls. It measures tool-call correctness, latency, and turn-taking. Its research is directly relevant to STAR's partial-ASR revision handling: speculative output from a superseded transcript must be cancelled, and partial speech must never authorize a tool call.

Source: [Full-Duplex-Bench v3](https://www.full-duplex.ai/benchmarks/fdb-v3).

**Realtime-Venus** is a useful architecture study because it separates a live perception/speech loop from an asynchronous delegated-task loop, then returns delegated results to the same conversation. Its frontend decides when a prepared reply should actually be spoken, and playback tracking confirms delivery. The project page reports continuation rates of 97% for user backchannels, 88% for speech directed at others, and 86% for background speech on its Full-Duplex-Bench v1.5 evaluation; it reports interruption response separately. These are results from that project's September 9, 2026 manuscript, not expected STAR scores or proof that its 9B models will fit STAR's local hardware.

Source: [Realtime-Venus project and technical report](https://realtime-venus.github.io/).

Recommended STAR Social Director behavior:

- Track who currently has the conversational floor without persisting viewer identities unnecessarily.
- Distinguish direct address, viewer-to-viewer conversation, backchannels, background speech, and genuine interruption.
- Preserve natural silence; do not fill every pause.
- Yield when a viewer answers another viewer's question.
- Handle self-correction by cancelling stale speculative work and committing only the final recognized instruction.
- Stop speech promptly on interruption and retain only the words actually played in canonical conversation history.
- Separate task correctness from timing, voice style, volume, whisper, and long-conversation groundedness.
- Drive avatar listening, thinking, speaking, laughing, and reacting states from the same playback/conversation state machine.

A convincing VTuber is not just a voice plus mouth movement. STAR needs coherent timing, selective participation, context retention, game-event awareness, and a stable fictional personality. Expressive behavior should not be presented as proof of human consciousness.

### 2. Faster inference without sacrificing stream quality

The official **llama.cpp server** documents parallel decoding, continuous batching, monitoring endpoints, prompt caching, function calling, and speculative decoding. These are experiment candidates, not settings to turn on indiscriminately.

Source: [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

**vLLM Automatic Prefix Caching** explains an important distinction: reusing a shared prefix skips repeated prefill computation, but it does not speed up token-by-token decoding when generation is the bottleneck. This distinction should shape STAR's prompt/cache experiments.

Source: [vLLM Automatic Prefix Caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/).

**OpenTelemetry GenAI semantic conventions** now live in the dedicated open-telemetry/semantic-conventions-genai repository; the former Microsoft repository is archived. The current conventions define server time-to-first-token, server time-per-output-token, client time-to-first-chunk, and agent/tool/workflow durations. They are still marked Development, so STAR should pin the exact convention commit/schema used by its instrumentation rather than assuming names are stable. STAR should add client-observed first-audible latency, since model-server TTFT alone excludes TTS, audio buffering, and playback.

Source: [OpenTelemetry GenAI metrics](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-metrics.md).

Recommended experiments, one at a time:

1. Pin the exact llama.cpp build, model file/hash, quantization, context, thread count, batch threads, slot count, GPU layers, and cache policy.
2. Measure baseline prefill and decode separately before changing anything.
3. Keep stable system/tool prefixes identical so prompt-cache reuse is possible; put volatile turn-specific content after the stable prefix.
4. Test continuous batching at low concurrency first, then increase slots while measuring p95/p99 client latency.
5. Test speculative decoding only with compatible target/draft models and measure acceptance rate, memory overhead, and first-audible latency.
6. Test quantization and CPU/GPU offload as matched candidates; compare answer quality on held-out cases.
7. Keep only the models needed for the current workload resident. A second resident model can cost more VRAM than its speculative speedup returns.
8. Route short reactive decisions to a small/fast model and long research/code plans to a stronger model only when resource admission allows it.
9. Use asynchronous delegation for research and asset generation while the realtime voice/game lane remains protected.
10. Benchmark under the actual combined OBS + game + voice + model workload, not isolated inference alone.

Do not compare throughput alone. Track TTFT, time per output token, first audible response, cancellation-to-stop, p95/p99, game frame-time p99, audio underruns, OBS output skips, CPU/RAM/VRAM, and task success. A candidate that produces more tokens but makes the stream stutter is a regression.

### 3. STAR Gamer: learn to play, not just describe games

**GameWorld** provides 34 browser games and 170 tasks with state-verifiable outcomes. It studies direct keyboard/mouse control and semantic action interfaces, plus real-time interaction, memory sensitivity, and action validity.

Source: [GameWorld paper](https://arxiv.org/abs/2604.07429) and [project](https://gameworld-bench.github.io/).

Recommended STAR Gamer decomposition:

- **Perception:** interpret the game frame, HUD, menus, objects, and relevant motion.
- **State estimator:** maintain a compact belief about position, health, inventory, objectives, hazards, and uncertainty.
- **Semantic planner:** choose a meaningful action such as navigate, interact, aim, defend, craft, or complete objective.
- **Low-level controller:** translate the semantic action into bounded keyboard/mouse/controller input and verify that the game accepted it.
- **Skill library:** store versioned, executable procedures with game/build compatibility and known failure conditions.
- **Independent evaluator:** score outcomes from game state, replay, or trusted test harness—not from STAR's own narration.

Separate practice from held-out evaluation. A skill should not be promoted merely because it worked once. Test transfer to unfamiliar maps, enemy layouts, objectives, and game versions. Keep live-clock reaction tests separate from slower strategic planning tests.

### 4. STAR Creator: build games that can actually be completed

**CEGame-Bench** evaluates long-horizon complete-game creation across Defold, Godot, Roblox Studio, Unity, and Unreal. Its October 2026 preprint describes runs averaging up to 295 steps and 65 million tokens; the evaluated agents reached the game's ending in only 16% of runs. Its Game Completion Boost skill improved execution-based scores by 14.1–24.3 points on the evaluated models. These are benchmark-specific results, not expected STAR scores.

Source: [CEGame-Bench, arXiv:2610.26098](https://arxiv.org/abs/2610.26098).

**GameDevBench** provides 333 Godot game-development tasks across gameplay, UI, 2D graphics/animation, and 3D graphics/animation. Its authors emphasize the value of visual feedback for multimodal game-development work.

Source: [GameDevBench repository](https://github.com/waynchi/gamedevbench).

STAR Creator should use a design document as a testable contract and follow this loop:

1. Inspect the project and its engine/version.
2. Convert requirements into observable acceptance criteria.
3. Build a minimal playable vertical slice.
4. Implement features in bounded, reversible changes.
5. Launch the real engine and inspect the scene.
6. Capture approved screenshots/video for visual QA.
7. Use real input to play every required mechanic.
8. Run state assertions and regression tests.
9. Repair failed requirements and repeat.
10. Reach the actual ending/goal, save, close, reopen in a new process, and verify restored state.
11. Package the artifact and report what was not tested.

A successful build is not a completed game. Keep Roblox Studio, Blender, Godot, Unity, and Unreal adapters separate behind a common creator contract; do not assume one engine's tool ranking or success rate transfers to another.

### 5. Long-horizon memory and general knowledge

**MemGym** studies memory during extended agent execution across tool-use dialogue, deep research, coding, and computer-use environments. It explicitly separates memory quality from reasoning, retrieval, and tool-use performance so memory strategies can be compared without conflating those capabilities.

Source: [MemGym, Microsoft Research](https://www.microsoft.com/en-us/research/publication/memgym-a-long-horizon-memory-environment-for-llm-agents/) and [paper](https://arxiv.org/abs/2605.20833).

Recommended STAR memory layers:

- Working: current task, active conversation, current game state.
- Episodic: compact summaries of completed experiences with provenance.
- Semantic: general facts with source, confidence, and freshness.
- Procedural: reusable skills and workflows.
- Project: decisions, current state, blockers, and next steps.
- Social: minimal context needed for ongoing conversations, with explicit privacy/retention boundaries.

Memory must be evaluated by future action, not just recall. Include temporal updates, stale-fact rejection, forgetting/deletion, source verification, procedural transfer, and no-memory controls. Do not allow a memory system to reintroduce deleted or superseded facts. Keep raw viewer audio/transcripts out of benchmark artifacts by default.

## Unified STAR runtime architecture

The target architecture should have one host supervisor and one admission controller with distinct workload lanes:

1. Audio capture/playback and interruption control.
2. Game input and immediate reactive control.
3. Avatar frame transport and synchronization.
4. Live conversation and short-turn reasoning.
5. Interactive tools and project editing.
6. Strategic game planning.
7. Research and general knowledge.
8. Learning, evaluation, and skill practice.
9. Asset generation and long-running creator work.

Realtime lanes need reserved CPU, RAM, GPU, and audio headroom. Background lanes should be cancellable, bounded, and resumable. A task should have an opaque ID, revision, deadline, resource lease, and explicit stop receipt. A scheduler must not free capacity merely because a lease expired if the host process may still be running.

Use one event timeline for user speech, partial/final ASR, model deltas, spoken segments, playback cursor, avatar frames, game events, and tool results. Keep sequence IDs and clock epochs so a late event cannot overwrite a newer conversation or avatar state. Only the playback owner may commit the words actually heard.

The model router should be capability- and budget-aware. Avoid running every specialist model simultaneously on an 8 GB GPU. Prefer a small fast model for immediate interaction, a stronger model for difficult reasoning, and specialized vision/audio/coding models on demand. Cache stable prompts and retrieved documentation, but bound cache RAM and invalidate entries when model/tool/config fingerprints change.

## Next implementation sequence

### P0 — complete verification

- Finish the parent voice-quality PR and this child PR's GitHub Actions checks on the exact final head.
- Keep the changes draft and stacked until their parents are reviewed.
- Do not merge into production 'main' or change the v1.0 installer as part of this evaluation-only work.

### P1 — connect the trusted Windows host

- Implement WDDM-aware per-process GPU-memory attribution; do not interpret unavailable NVML per-process readings as zero.
- Collect process CPU/RAM using stable PID + process-start identity.
- Add a Windows supervisor that owns process start/stop receipts and scheduler leases.
- Normalize CPU/RAM/VRAM observations into the same allocation units used by the scheduler.
- Keep machine/environment fingerprints separate from candidate model/config revisions.

### P1 — real inference experiment harness

- Pin model/server versions and collect OpenTelemetry-compatible TTFT/TPOT plus first-audible latency.
- Run paired cache, batching, quantization, speculative-decoding, and routing experiments.
- Test both cold-start and warm-cache cases.
- Require held-out task quality and mixed-load non-regression before recommending a candidate.

### P2 — private VTuber rehearsal

- Integrate the existing voice pipeline, VTube Studio parameter pump, OBS statistics, audio playback, and game telemetry through the trusted host.
- Rehearse multiparty chat, backchannels, interruptions, self-corrections, silence, jokes, whisper/volume requests, and 20+ turn conversations.
- Verify that the avatar follows actual audible playback, not generated text that was cancelled or never heard.

### P2 — Gamer and Creator closed loops

- Add state-verifiable game adapters and held-out skill trials.
- Start with one sandbox game and one Roblox Studio test place before broadening to more games/engines.
- Require real-input objective completion and save/reopen verification for creator tasks.

### P3 — memory and general knowledge

- Add source-aware knowledge refresh and temporal conflict handling.
- Evaluate memory-to-action transfer and forgetting on hidden cases.
- Keep owner review for persistent memory promotion and external actions.

## Local validation performed for this change

- Isolated module tests: **20 passed** under Python 3.13.
- Python compile check: passed.
- Full repository test suite, Ruff, Pyright, GitHub Actions, Windows hardware, RTX 4060, WDDM GPU counters, real microphone/speakers, OBS, VTube Studio, Roblox Studio, gameplay, and live streaming: **not run in this environment**.

## Claims and limits

This change adds an offline evaluator and a research/implementation plan. It does not call a model, collect hardware telemetry, start workers, capture audio/video, control OBS/VTube Studio, send game input, train weights, or change model defaults. It does not demonstrate a speedup, intelligence gain, human-equivalent behavior, gameplay mastery, or production readiness. GitHub Actions on the exact PR head and real Windows private-stream acceptance are required before runtime integration or release.
