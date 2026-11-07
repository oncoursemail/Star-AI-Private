# STAR: Fresh Skill Evidence, Real-Time Intelligence & VTuber Development
**Research and code delta: 2026-11-03.** This is a planning/research report plus one measured software correctness improvement, not a claim that Star is independently playing or streaming.

## 1. What this iteration fixes
The existing `GameLearningLadder` recommended harder scenarios when enough signed practice successes cleared a Wilson confidence threshold. It used `GameplaySkillBank.practice_evidence`'s **90-day default window**, and ignored the aggregate's verified **most-recent outcome**. Consequently, twenty historic wins could unlock an advanced scenario even though the most recent attempt had just failed. An already-created `game_practice_curriculum` policy used a narrower per-trial window; the active ladder did not.

This change (a) explicitly requests a configurable **seven-day default per-trial evidence window**, rejecting invalid policy intervals; (b) requires an **affirmative latest signed success** before a scenario is considered mastered; (c) conservatively treats legacy/ambiguous outcomes as requiring more practice; (d) validates aggregates; and (e) adds adversarial tests using an actual signed practice ledger. **These are decision-correctness improvements, not increased model intelligence, win rate, or model-token speed.** Neither practice nor curriculum recommendations use withheld validation outcomes. The existing host and game input permissions remain unchanged.

Acceptance test: 20 signed wins 9 days old are excluded from the seven-day view; 20 recent wins can open a harder stage; adding one new signed loss *recloses* that stage despite a Wilson lower bound >0.55. Other tests check missing outcomes, negative values and out-of-range policy settings.

## 2. Why Star needs a three-speed brain
A single monolithic LLM loop is unsuitable for real-time games. Split compute into:
1. **Reflex lane**: host-approved bounded, cached perception/action policies with deadlines in tens/hundreds of milliseconds; no long tool chains or unbounded reasoning during a reaction.
2. **Tactics lane**: compact visual scene summaries, spatial memory, short-horizon planning and lightweight corrective reasoning during safe windows.
3. **Teacher lane**: offline search, analysis, controlled self-play, skill refinement and independent validation between episodes. Teacher training is paused during real-time/stream pressure.

The current repo has `game_deadline_router`, `game_capture_to_action_benchmark`, `stream_brain_governor`, `game_learning_ladder` and `gameplay_skill_bank`; extend and compose those rather than create a competing stack. Never count a brainstormed plan as a successful game action.

Voyager (2023) supports automatic curricula, executable skill reuse, and iterating with environment feedback, but its Minecraft results do not establish transfer to other games or Star's current system. Source: https://arxiv.org/abs/2305.16291 .

## 3. Speed: evaluate the *whole* experience
Do not choose models from isolated tokens/sec. Record capture start, frame transfer, preprocessing, visual reasoning, inference, OS input acknowledgement, game clock advancement, first **audible** PCM, OBS dropped frames and p99 game frametime.

GameScaling corrected ViZDoom real-time evaluation **on 2026-11-01**, revising two scores from 16.4 to 11.5 and 13.2 to 8.5 after accounting for previously omitted capture/transfer/other work. This directly motivates the existing capture-to-action benchmark. Source: https://gamescaling.github.io/ .

llama.cpp offers n-gram, draft-model and other speculative-decode variants, but adds resource/CPU costs; measure only with randomized, distinct prompts and multiple workload types. Avoid repeated-prompt-only speed claims; alternate long and short cache canaries. Official benchmark: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md . Speculative decoding is not universally faster: https://github.com/ggml-org/llama.cpp/issues/10664 .

**Observed, read-only Main hardware snapshot (2026-11-03):** RTX 3060 Ti, 8,192 MiB total VRAM, 5,607 MiB free, 3% GPU utilization. Python 3.15 was reported. OBS, Roblox Studio and llama-server were **not running**, so there is no valid real gameplay/voice benchmark or rehearsal to claim. This snapshot does not measure available model throughput, streaming FPS or physical keyboard safety. Device inventory must be repeated just before any nonbroadcast test. Do not assume this machine contains the owner's separate RTX 4060.

### Concrete 8 GB GPU experiment matrix
- Baseline fast model Q4 vs second candidate; same world seed, initial state, prompt set, max output tokens and quantization recording; 20+ independent matched episodes.
- Model alone vs game+OBS vs game+OBS+CPU TTS. Protect FPS, first-audible latency, GPU peak VRAM and full action deadline. Compare p95 and paired confidence intervals, including failures.
- Only activate speculative decoding or larger context when wins on **end-to-end deadlines** outweighs memory and frame regressions.
- Keep model embeddings, retrieval, code analysis, slow planners and training off the critical GPU game/OBS lane. Budget RAM and CPU, not just VRAM.

## 4. Learn games by observing, practicing and proving
Build a legal, owner-authorized training lab: collect task objective and allowed controls; inspect game state (from trusted game-engine telemetry where available) and visual frames; establish a resettable practice case; run one bounded action; independently verify the result; update signed practice evidence; escalate to harder scenarios only after fresh, repeatable success. Mix skills across seeds, FPS, camera poses and game versions. Reserve hidden holdout cases for independent validation, not as knowledge supplied to Star.

Use failures to learn *why*: failed jumps may mean bad depth judgement, controller latency, stale input, physics changes or a wrong game-state assumption. Generate one controlled hypothesis and test it. Maintain retrievable skill cards with explicit prerequisites, failure modes, version/hash and independently observed outcome. Separate roleplay reaction text from the factual gameplay ledger.

## 5. Better autonomous game creation
Roblox's **OpenGameEval** (2026-10-01) evaluated 13 models on 84 curated tasks and found that inspecting relevant project objects before editing correlated with better task outcomes. It checks both edited scenes and runtime gameplay. Source: https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval .

Roblox Studio's built-in MCP offers script inspection/editing, Luau execution and single-client playtests; StudioTestService supports scripted multiplayer tests. Sources: https://create.roblox.com/docs/studio/mcp and https://create.roblox.com/docs/reference/engine/classes/StudioTestService .

Recommended full creation loop: **inspect → plan → Best-of-N code/asset candidates → static Luau lint and type checks → isolated Studio playtest → multiplayer/regression run → screenshots/videos reviewed at multiple resolutions → compare quality → commit validated revision**. For 2D art, visual effects and animation, run image/video feedback instead of approving code merely because it compiles. GameDevBench's published benchmark documents the importance of visual feedback in engine tasks (https://proceedings.mlr.press/v306/chi26a.html).

## 6. Natural, expressive and trustworthy VTuber
Humanlike presentation is a behavioral engineering target, **not a claim that Star is human or conscious**. Keep an original transparent AI identity.

The streaming runtime should support:
- Grounded, short commentary on independent game evidence, and *deliberate silence* during high-attention gameplay. No manufactured successes, invented viewers or fictional autobiographical memories.
- Natural contractions, variable rhythm, expressive prosody, pauses, quiet reactions, personality continuity, consent-aware social conversation, explicit uncertainty and honest corrections.
- Owner interrupt priority and guest backchannels: "mhm" must not always interrupt, but a genuine owner request should stop **audible playback** and mouth rig; never merely stop text generation.
- Per-stage clocks for first-visible text, TTS-ready phrase, first audible PCM, phoneme/mouth animation, avatar expression and OBS audio/video. Drop or replan obsolete speech rather than reading a 30-second-old reaction.
- Bounded, privacy-minimal continuity: preferences and actual activities with provenance and expiry, not raw viewer private information or fabricated emotional states.

LiveKit documents adaptive interruption and false interruption recovery (https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/). Its cloud-linked models are not an automatic dependency for a local, offline-first Star. An independent local gate should be compared using the existing social-turn benchmark.

Kyutai Pocket TTS v4.0.0 (released **2026-10-20**) adds English 18M, 7M and experimental 2M choices; it is a **candidate**, not proof of naturalness or lower streaming latency. Benchmark it against Star's existing Kokoro/Pocket backends on the target CPU using identical sentences and real first-audible PCM. Source: https://github.com/kyutai-labs/pocket-tts/releases .

## 7. The next integration milestones (not completed here)
**Gate A: hardware-only nonbroadcast setup.** Confirm OBS, a local permitted game and an avatar/TTS runtime are installed, isolated, running with explicit authorization, and safe-key-release mechanisms pass Windows-specific independent checks. Main was idle at inventory time; not ready.

**Gate B: continuous game episode.** Attach authenticated game-engine telemetry (or clearly label unverified game screenshots), supervised bounded keyboard action, postflight evidence and OS key neutral verification; measure action deadlines with a continuously advancing game.

**Gate C: audible/visual VTuber rehearsal.** Combine live game observation, permitted actions, local TTS, lipsync, stage directives and read-only OBS telemetry into a private **nonbroadcast** test. Inspect logs and artifacts for hallucinated achievements, late audio, guest overlaps, game FPS drops and native-input recovery.

**Gate D: independent capability improvement.** Compare known baselines on holdouts: win/progress rate, near-miss recovery, cross-seed transfer, playtesting pass rate, first-audible p95, p99 frametime, OBS dropped frames, VRAM headroom and answer grounding. Only these measurements support speed or quality claims.

## Safety and reproducibility
No external account/chat, stream channel, microphone, input, game or OBS operation was performed in this code change. No training, model download or autonomous self-update is enabled. Every native game control and broadcast permission stays at the owner-host boundary; signed receipts authenticate a source, not world truth. AI personality, emotional expression and independent goals should not be confused with confirmed consciousness or a legal person's powers. Public GitHub is a review/export destination; local verified history remains preferable for independent offline experiments.
