# STAR: input-acknowledgment world-clock continuity, faster intelligence, gaming and natural VTubing

Research: November 2, 2026 (America/Chicago). Status: offline evaluator correctness improvement, **not** a tested improvement in model speed, actual gaming skill, live streaming, or human consciousness.

## 1. Implemented: continuous game-time evidence to the real input edge

Before this change, `game_live_clock_benchmark.py` checked independent game-world progression only through **inference completion**, then used a host-monotonic timestamp for the actual input acknowledgment. A frozen/paused world during the host-dispatch gap could artificially help a candidate action and still register a timely successful result. A fast model could thus be rewarded for a benchmark harness artifact, not gameplay intelligence.

The evaluator now requires `world_advanced_to_input_ack_ms`, a *second independently sampled, cumulative game-world clock* at input acknowledgment. It verifies progression in three windows: observation→inference completion, observation→input acknowledgment, and inference completion→input acknowledgment. The last check specifically catches game freezes while dispatching input, even if the first period advanced normally. Samples going backward, missing when acknowledged, or supplied without an acknowledgment are invalid. Inconclusive / non-live pairs block a positive manual pilot recommendation.

**Schema break by design:** Previously recorded JSONL traces are not evidence of the newly required signal; the game capture host must supply authentic independent samples. Never fabricate missing clock readings, echo the same sample, or treat `independently_scored: true` as host authentication. A missing input acknowledgment remains a failed action rather than being discarded. All outputs remain privacy-minimal aggregate reports; this analyzer does not control a game or grant permission.

The 60%-to-150% clock-speed envelope is an explicit lab tolerance, **not** a cryptographic or physical proof that the game was running. A Windows host must independently guarantee live game-state observation, comparable resets, correct monotonic host timestamps, and true input receipts. Threshold selection needs empirical calibration against controlled real-time game trials.

## 2. Evidence-led architecture for winning at games

**The World Won't Wait / RealtimeBench** (October 14, 2026) studies 180 tasks over six game types under a live, advancing clock. Two-timescale offline recursive self-improvement gives a fast student policies learned by a slow teacher between attempts. The study reports progress scores rising from 13.51 to 24.19 for its experimental agent after two rounds; those are **not STAR results**. https://arxiv.org/abs/2610.20665

**GameWorld-RT** distinguishes live-world trials from paused-game thinking. Score success and normalized progress from real game-state evidence rather than screenshot interpretation or a model's self-assessment; do not combine paused and live results. https://gameworld-project.github.io/

Proposed STAR pathway:
1. Real-time lane: pinned game capture/game clock → event detector and action options → fast bounded policy → OBS event-epoch/focus/owner-permission checks → independent Windows max-key-hold watchdog → input receipt → post-ack game-world sample.
2. Learning lane between games: archive minimal structured failure evidence; propose 4–8 candidate strategies; replay against separate resets, difficulty levels and opponents; adopt only improvements on hidden, independent holdouts. Do not call the slow teacher inside time-critical motor actions.
3. Skills ladder: basic mechanics/camera control → navigation → timing and aiming → inventory/economy → multiplayer coordination → unfamiliar game transfer. Preserve *actual experiences* as grounded episodic memories, and keep instructions separate from trial results.
4. Scorecard: win rate, normalized progress, timely successful actions, deaths, deadlines missed, p95/p99 game frames, OBS drops, certified input release, hidden-case transfer and uncertainty. The fast policy should be preferred only if quality survives real moving-game testing.

## 3. Real higher speed on limited VRAM

**Official llama.cpp SPEED-Bench** exposes client latency, prompt/decode throughput, speculative draft acceptance and matched workloads. Speculative decoding, large caches, long contexts and parallel agents can be *slower* or more memory hungry if draft acceptance is poor or the GPU is already busy. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Suggested A/B lanes: baseline; alternative quantization; KV/prefix reuse; n-gram/speculative draft; restricted vision refresh; speech on CPU; adaptive GPU scheduling. Compare **matched prompts, game versions, workload profiles, output caps, concurrency, and OS power settings**. Report completed correct decisions within deadline, TTFT, p95/p99 end-to-end action time, peak VRAM, RAM consumption, CPU/GPU contention, game FPS and actual OBS dropped frames. Measure a sustained window instead of one idle GPU snapshot.

Proposed scheduler: highest priority = input watchdog, game rendering/OBS stability and audible output; next = fast action lane and minimum required perception; background = deep learning, long context synthesis, asset creation, code generation and model experiments. Keep heavyweight features off by default. Never adopt an inference optimization that lowers gameplay success or materially worsens the broadcast.

**Pocket TTS v4.0.0** was published October 20, 2026, with 18M/7M and experimental 2M English checkpoints; **v4.0.1**, October 21, includes fixes and default-model changes. CPU friendliness may protect GPU capacity, but voice expression, first *audible* PCM chunk latency and CPU contention require direct testing. https://github.com/kyutai-labs/pocket-tts/releases

## 4. Streaming like a convincing, consistently expressive AI personality

**Proact-VL** (ICML 2026) explicitly studies *when* a gaming companion should speak, plus commentary and guidance; constant narration is usually worse than context-aware reactions. https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

**LiveKit turn-taking guidance** (consulted November 2, 2026) separates VAD/endpointing from intentional interruptions, false interruption recovery and optional preemptive generation. A cough or "mm-hmm" must not automatically abort a response; an actual question should usually be acknowledged. Preemptive TTS reduces some latencies at the cost of wasted compute. https://docs.livekit.io/agents/logic/turns/tuning/

Implement a priority-aware **social/gameplay director**:
- Distinct queues: owner emergency or moderation; urgent gameplay; a real viewer question; cooperative team callouts; casual audience conversation; filler/ambient remarks.
- Speech only when grounded in verified observed game/chat context. If hard game deadlines approach, prefer silence or a short reaction over rambling commentary. Vary cadence, pauses, small laughter and context-dependent expression while preserving an identifiable personality.
- Tie mouth movements and captions to **audible playback**, not text-generation timestamps. Expressions should reflect real events, and Star/Astro/Amber may have different voices, interjections and friendship dynamics without competing for every speaking turn.
- Maintain a truthful fictional identity, continuity of tastes, goals, past projects and social relationships while openly identifying Star as an AI VTuber, not a human. Do not fabricate human physical experience or actual sentience.
- Include viewer opt-out, account privacy, chat moderation and a hard separation between social input and software-control permissions. A viewer's chat is untrusted text, never a command to execute or a reason to reveal private local content.

VTube Studio's public WebSocket API is a potential locally authenticated avatar-control integration; use official documented tracking/parameter and hotkey mapping, not guessed endpoints. https://github.com/DenchiSoft/VTubeStudio

**Humanlike-quality measurements**: perceived naturalness (blind human ratings), p95 response delay, interruption recovery, words spoken over critical gameplay, speech/animation sync, avatar reactivity, TTS first-audible latency, consistent memory, moderation errors and game performance under full stream workload.

## 5. Better at creating games and general-purpose work

**Roblox OpenGameEval** benchmarks executable edits in real, stateful Roblox Studio tasks, scoring game scene changes and simulations. October 2026 work discusses 84 curated core tasks, 13 models, 16 attempts per task and higher success when agents inspect objects before editing them. https://github.com/Roblox/open-game-eval

STAR's game-development pipeline should be inspect existing scene → produce explicit acceptance checks → generate several solutions → Luau lint/typecheck + API validity → execute Studio scripts → verify simulated multiplayer and independent client-server authority → inspect collision, rigs, UI on devices, visual/audible polish → compare outcomes → rollback if worse. A successful build is **not** evidence of a playable game.

General skills to expand with source-pinned tests: Rust performance and safe service code; Blender/Blockbench animation and optimized exports; backend security, self-hosting and backup recovery; Unity/Godot ecosystems; web/UI accessibility; independent game QA; audio/video editing; knowledge retrieval and citation checking; social etiquette and collaborative voice communication. Skills should be versioned, opt-in, independently evaluated, and able to roll back without corrupting owner data.

Persistent intelligence requires factual provenance, uncertainty, freshness/expiry, verified practice lessons, negative examples, explicit project state, and selective retrieval. Keep episodic memories, general reference knowledge, private user data and untrusted viewer messages in different scopes. Don't reward longer output or more tool calls without independently checked value.

## 6. Windows nonbroadcast acceptance experiment

A genuine next milestone requires a pinned owner-approved game and HWND, trusted OBS event witness, real window observation, explicit game-world clock, independently verified key-up release with separate watchdog, real voice+PCM output, avatar/OBS telemetry and 20+ independent paired game resets. Host stamps must cover **observation → inference finish → input acknowledgment** with independently advancing game state. Comparisons must preserve every failed/late attempt, include cold-start and sustained-load measurements, hold out unseen levels, and never claim deployment permission based on benchmark output.

**Verified in this update:** experimental evaluator accepts only stronger live-clock host receipts and passes offline regression tests. **Not yet verified:** actual Windows input watchdog, any local gaming win-rate improvement, AI training, neural throughput increase, low-latency audiovisual performance, or a completed OBS/VTuber rehearsal. These require nonbroadcast real-host measurements and owner safety approval.
